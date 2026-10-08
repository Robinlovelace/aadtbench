"""CI smoke test for one tool on the small frozen mini case.

    python -m benchmark.smoke --tool cityseer_od [--image aadtbench-cityseer_od] [--case ID]

Steps: fetch the mini case from the release, run the tool (in a Docker image
if ``--image`` is given, else in this process), run the baselines, score with
the benchmark scorer and apply the sanity bounds in ``config/ci.yaml``.

Checks per tool:

* the run completes and writes valid predictions,
* the uncalibrated rank correlation reaches ``min_raw_rho`` for the listed
  modes (the flows carry signal),
* coverage (share of crosswalked sites with a flow above 0) is at least
  ``min_coverage`` in every checked mode,
* the wall time is within ``mini_case_time_limit_s`` (``config/limits.yaml``).

Exit code 0 on pass. Non-zero on a failed check. If the case id is the
placeholder or its assets are missing from the release, the smoke step emits a
GitHub warning annotation and exits 0 (it degrades, it does not fail).
Results go to a temporary directory, never to the repository ``results/``.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from benchmark import baselines as bl
from benchmark.case import BENCHMARK_VERSION, load_case
from benchmark.fetch import FetchError
from benchmark.run_all import (BASELINE_TIER, blind_copy, harness_hash, run_baseline, run_dir_for,
                               score_run)
from benchmark.scoring import site_table

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "ci.yaml"
PLACEHOLDER = "PLACEHOLDER"


def warn(msg: str) -> None:
    """A GitHub warning annotation (plain text elsewhere)."""
    print(f"::warning title=AADTBench smoke test::{msg}", flush=True)


def load_config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(Path(path).read_text())


def tool_settings(cfg: dict, tool: str) -> dict:
    if tool not in (cfg.get("tools") or {}):
        raise KeyError(f"tool {tool} is not in config/ci.yaml")
    return {**cfg.get("defaults", {}), **(cfg["tools"][tool] or {})}


def run_in_docker(image: str, blind: Path, run_dir: Path, tier: str, modes: list[str],
                  variant: str, threads: int) -> dict:
    """Run the tool image on a real (not symlinked) copy of the blind case."""
    run_dir.mkdir(parents=True, exist_ok=True)
    real = blind.parent / "_blind_real"
    if real.exists():
        shutil.rmtree(real)
    shutil.copytree(blind, real, symlinks=False)
    digest = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                            capture_output=True, text=True).stdout.strip() or "unknown"
    cmd = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
           "-e", f"AADTBENCH_IMAGE_DIGEST={digest}", "-e", "HOME=/tmp",
           "-v", f"{real}:/case:ro", "-v", f"{run_dir}:/out", image,
           "--case", "/case", "--tier", tier, "--modes", ",".join(modes),
           "--variant", variant, "--threads", str(threads), "--out", "/out"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print((res.stdout or "")[-800:])
        print((res.stderr or "")[-1500:], file=sys.stderr)
    return read_json(run_dir / "run.json") or {"status": "failed", "message": (res.stderr or "")[-400:]}


def run_in_process(tool: str, blind: Path, run_dir: Path, tier: str, modes: list[str],
                   variant: str, threads: int) -> dict:
    from adapters._base import Adapter, run_adapter
    mod = importlib.import_module(f"adapters.{tool}")
    cls = next(v for v in vars(mod).values()
               if isinstance(v, type) and issubclass(v, Adapter) and v is not Adapter
               and v.__module__ == mod.__name__)
    try:
        return run_adapter(cls(), blind, tier, modes, run_dir, variant, None, threads)
    except Exception as exc:
        return read_json(run_dir / "run.json") or {"status": "failed", "message": f"{type(exc).__name__}: {exc}"}


def read_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def coverage(case, pred: pd.DataFrame, mode: str) -> tuple[float, int]:
    """Share of crosswalked sites with a flow above 0, and the number of sites."""
    t, _ = site_table(case.sites, case.crosswalk, pred, mode)
    return (float((t["flow"] > 0).mean()) if len(t) else float("nan")), int(len(t))


def evaluate(case, rec: dict, run_dir: Path, rows: list[dict], settings: dict, tool: str,
             variant: str) -> tuple[list[dict], list[str]]:
    """Apply the sanity bounds. Returns (table rows, failure messages)."""
    fails: list[str] = []
    if rec.get("status") != "complete":
        return [], [f"run status is {rec.get('status')}: {str(rec.get('message', ''))[:200]}"]
    pred = pd.read_parquet(run_dir / "predictions.parquet")
    if pred.empty or not (pred["flow"] > 0).any():
        fails.append("predictions are empty or all zero")
    rho = {r["mode"]: r["rho"] for r in rows
           if r["tool"] == tool and r["variant"] == variant and r["track"] == "uncalibrated"
           and r["split"] == "group_out_pooled"}
    for mode, floor in (settings.get("min_raw_rho") or {}).items():
        v = rho.get(mode, np.nan)
        if mode in rec.get("modes", []) and not (np.isfinite(v) and v >= floor):
            fails.append(f"{mode}: uncalibrated rho {v:.2f} below {floor}")
    table = []
    for mode in rec.get("modes", []):
        cov, n = coverage(case, pred, mode)
        row = {"mode": mode, "n_sites": n, "coverage": cov, "rho": rho.get(mode, np.nan)}
        if n < settings["min_sites"]:
            row["note"] = f"skipped, fewer than {settings['min_sites']} sites"
        elif not np.isfinite(cov) or cov < settings["min_coverage"]:
            fails.append(f"{mode}: coverage {cov:.2f} below {settings['min_coverage']}")
        table.append(row)
    if not [r for r in table if "note" not in r]:
        fails.append("no mode had enough sites to check")
    wall = rec.get("wall_time_s")
    limit = yaml.safe_load((CONFIG.parent / "limits.yaml").read_text())["mini_case_time_limit_s"]
    if wall is not None and wall > limit:
        fails.append(f"wall time {wall:.0f} s above {limit} s")
    return table, fails


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CI smoke test for one tool on the mini case.")
    p.add_argument("--tool", required=True)
    p.add_argument("--image", default=None, help="Docker image to run the tool in")
    p.add_argument("--case", default=None, help="case id (default: mini_case in config/ci.yaml)")
    p.add_argument("--config", default=str(CONFIG))
    p.add_argument("--modes", default=None, help="comma separated, overrides the config")
    p.add_argument("--tier", default=None)
    p.add_argument("--release", default=None)
    p.add_argument("--from-dir", default=None, help="local mirror of release assets")
    p.add_argument("--cases-root", default=None)
    p.add_argument("--threads", type=int, default=int(yaml.safe_load((CONFIG.parent / "limits.yaml").read_text())["mini_case_threads"]))
    p.add_argument("--results-dir", default=None, help="default: a new temporary directory")
    a = p.parse_args(argv)

    cfg = load_config(Path(a.config))
    settings = tool_settings(cfg, a.tool)
    case_id = a.case or cfg.get("mini_case", PLACEHOLDER)
    release = a.release or cfg.get("release", BENCHMARK_VERSION)
    tier = a.tier or settings["tier"]
    variant = settings.get("variant", "default")
    if case_id == PLACEHOLDER:
        warn(f"mini case is still the placeholder in config/ci.yaml, smoke test for {a.tool} skipped")
        return 0
    try:
        case = load_case(case_id, a.cases_root, release, a.from_dir)
    except (FetchError, FileNotFoundError) as exc:
        warn(f"mini case {case_id} is not available from release {release} ({exc}), "
             f"smoke test for {a.tool} skipped")
        return 0

    modes = (a.modes.split(",") if a.modes else settings["modes"])
    modes = [m for m in modes if m in case.modes]
    results = Path(a.results_dir) if a.results_dir else Path(tempfile.mkdtemp(prefix="aadtbench-smoke-"))
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    commit = "smoke"
    print(f"smoke: tool {a.tool}, case {case.case_id}, tier {tier}, modes {modes}, "
          f"{'image ' + a.image if a.image else 'in process'}, results {results}", flush=True)

    site_class = case.site_road_class()
    blind = blind_copy(case, results)

    # Baselines first: class_only is the comparison. Others need covariates.
    rows: list[dict] = []
    covs = bl.segment_covariates(case)
    for name in bl.BASELINES:
        rd = run_dir_for(results, case.case_id, "baseline", name, BASELINE_TIER)
        h = harness_hash(case, "baseline", name, BASELINE_TIER, modes, {}, bl.BASELINE_VERSION)
        rec = run_baseline(case, name, modes, rd, h, covs)
        rows += score_run(case, rec, rd, site_class, commit, stamp)

    rd = run_dir_for(results, case.case_id, a.tool, variant, tier)
    t0 = time.perf_counter()
    if a.image:
        rec = run_in_docker(a.image, blind, rd, tier, modes, variant, a.threads)
    else:
        rec = run_in_process(a.tool, blind, rd, tier, modes, variant, a.threads)
    wall = time.perf_counter() - t0
    rec.setdefault("case_id", case.case_id)
    rec.setdefault("case_version", case.version)
    rec.setdefault("tool", a.tool)
    rec.setdefault("variant", variant)
    rec.setdefault("input_tier", tier)
    rec.setdefault("modes", modes)
    rec.setdefault("run_id", f"{a.tool}-{variant}-smoke")
    if rec.get("status") == "unsupported":
        print(f"FAIL: tool reports unsupported: {rec.get('message')}")
        return 1
    if rec.get("status") == "complete":
        rows += score_run(case, rec, rd, site_class, commit, stamp)
    table, fails = evaluate(case, rec, rd, rows, settings, a.tool, variant)

    if table:
        print(pd.DataFrame(table).round(3).to_string(index=False))
    print(f"run: status {rec.get('status')}, tool wall {rec.get('wall_time_s')} s, "
          f"total {wall:.1f} s, peak memory {rec.get('peak_memory_mb')} MB")
    if fails:
        for f in fails:
            print(f"::error title=AADTBench smoke test::{a.tool}: {f}")
        return 1
    print(f"PASS: {a.tool} on {case.case_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
