"""CI smoke test for one tool on the small frozen mini case."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import yaml

from adapters._base import Adapter, run_adapter, validate_predictions
from benchmark.case import load_case
from benchmark.fetch import FetchError
from benchmark.run_all import CONFIG_PATH, blind_copy, run_dir_for, score_run

REPO = Path(__file__).resolve().parents[1]


def load_tool_settings(tool: str, cfg_path: Path = CONFIG_PATH) -> tuple[str, str, dict]:
    cfg = yaml.safe_load(cfg_path.read_text())
    lim = cfg.get("limits", {})
    settings = {
        **cfg.get("smoke", {}),
        "max_wall_time_s": lim.get("mini_case_time_limit_s", 300),
        "threads": lim.get("mini_case_threads", 2),
    }
    tcfg = (cfg.get("tools") or {}).get(tool) or {}
    if "tier" in tcfg:
        settings["tier"] = tcfg["tier"]
    if "smoke_modes" in tcfg:
        settings["modes"] = tcfg["smoke_modes"]
    settings["variant"] = tcfg.get("smoke_variant") or (tcfg.get("variants") or ["default"])[0]
    return str(cfg["mini_case"]), str(cfg.get("release", "v0.1.0")), settings


def run_in_process(tool: str, blind: Path, out: Path, tier: str, modes: list[str],
                   variant: str | None, threads: int) -> dict:
    mod = importlib.import_module(f"adapters.{tool}")
    cls = next(v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Adapter) and v is not Adapter)
    return run_adapter(cls(), blind, tier, modes, out, variant=variant, threads=threads)


def _image_digest(image: str) -> str:
    try:
        out = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                             capture_output=True, text=True, check=True).stdout.strip()
        return f"{image}@{out}" if out else image
    except Exception:
        return image


def run_in_docker(image: str, blind: Path, out: Path, tier: str, modes: list[str],
                  variant: str | None, threads: int, tool: str | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tname = tool or out.parent.name
    mounts = [arg for p in sorted(blind.iterdir()) for arg in ("-v", f"{p.resolve()}:/case/{p.name}:ro")]
    cmd = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}",
           "-e", f"AADTBENCH_IMAGE_DIGEST={_image_digest(image)}",
           "-e", "MPLCONFIGDIR=/tmp/matplotlib",
           *mounts, "-v", f"{out.resolve()}:/out",
           "--entrypoint", "python", image, "-m", f"adapters.{tname}",
           "--case", "/case", "--tier", tier, "--modes", ",".join(modes),
           "--threads", str(threads), "--out", "/out"]
    if variant:
        cmd += ["--variant", variant]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"docker run failed ({res.returncode}):\n{res.stderr[-800:]}")
    return json.loads((out / "run.json").read_text())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="CI smoke test for one AADTBench tool.")
    p.add_argument("--tool", required=True)
    p.add_argument("--image", default=None)
    p.add_argument("--case", default=None)
    p.add_argument("--cases-root", default=None)
    p.add_argument("--from-dir", default=None)
    p.add_argument("--threads", type=int, default=None)
    a = p.parse_args(argv)

    mini_case, release, settings = load_tool_settings(a.tool)
    case_id = a.case or mini_case
    threads = a.threads if a.threads is not None else int(settings.get("threads", 2))
    try:
        case = load_case(case_id, cases_root=a.cases_root, version=release, from_dir=a.from_dir)
    except (FetchError, FileNotFoundError) as exc:
        print(f"::warning title=AADTBench smoke test::could not fetch '{case_id}' ({exc}); skipping")
        return 0

    tier = settings["tier"]
    variant = settings.get("variant") or "default"
    modes = [m for m in settings["modes"] if m in case.modes]
    results = Path(tempfile.mkdtemp(prefix="aadtbench-smoke-"))
    blind = blind_copy(case, results)
    rd = run_dir_for(results, case.case_id, a.tool, variant, tier)
    t0 = time.perf_counter()
    rec = (run_in_docker(a.image, blind, rd, tier, modes, variant, threads, tool=a.tool)
           if a.image else run_in_process(a.tool, blind, rd, tier, modes, variant, threads))
    wall = time.perf_counter() - t0
    rec.setdefault("case_id", case.case_id)
    rec.setdefault("case_version", case.version)
    rec.setdefault("tool", a.tool)
    rec.setdefault("variant", variant)
    rec.setdefault("input_tier", tier)
    rec.setdefault("modes", modes)
    rec.setdefault("run_id", f"{a.tool}-{variant}-smoke")
    if rec.get("status") != "complete":
        print(f"FAIL: status is {rec.get('status')}: {rec.get('message', '')}")
        return 1

    validate_predictions(pd.read_parquet(rd / "predictions.parquet"), case.network["segment_id"].values)
    rows = score_run(case, rec, rd, case.site_road_class(), "smoke", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    fails, table = [], []
    max_wall = float(settings.get("max_wall_time_s", 300))
    if float(rec.get("wall_time_s", 0)) > max_wall:
        fails.append(f"wall_time_s {rec.get('wall_time_s')} > {max_wall}")
    min_sites = int(settings.get("min_sites", 20))
    min_cov = float(settings.get("min_coverage", 0.5))
    min_rho = settings.get("min_raw_rho") or {}
    for r in rows:
        m = r["mode"]
        if int(r["n_sites"]) < min_sites:
            continue
        table.append({"mode": m, "n_sites": int(r["n_sites"]), "coverage": r["coverage"], "rho": r["rho"]})
        if r["coverage"] < min_cov:
            fails.append(f"{m}: coverage {r['coverage']:.2f} < {min_cov}")
        if m in min_rho and (pd.isna(r["rho"]) or r["rho"] < float(min_rho[m])):
            fails.append(f"{m}: rho {r['rho']:.3f} < {min_rho[m]}")

    if table:
        print(pd.DataFrame(table).round(3).to_string(index=False))
    print(f"run: status {rec.get('status')}, tool wall {rec.get('wall_time_s')} s, total {wall:.1f} s")
    if fails:
        for f in fails:
            print(f"::error title=AADTBench smoke test::{a.tool}: {f}")
        return 1
    print(f"PASS: {a.tool} on {case.case_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
