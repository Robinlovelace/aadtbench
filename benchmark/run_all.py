"""Run tools on cases, score every run, write the leaderboards.

    python -m benchmark.run_all --cases oxford-v1 leeds-v1 --tools baselines \
        [other adapters] --tier T1_open_covariates

Tools:

* ``baselines`` runs the four mandatory baselines in process.
* Any other name is an adapter ``adapters.<name>`` run as a subprocess:
  ``python -m adapters.<name> --case <blind dir> --tier T --modes m,m
  --variant V --params JSON --threads N --out <run dir>``.

Adapters get a blind copy of the case (``case.yaml``, ``network.parquet`` and
``inputs/`` only, as symlinks). They never see ``sites.csv`` or
``crosswalk.csv``.

Run directories are ``results/runs/<case>/<tool>/<variant>__<tier prefix>/``.
They hold ``predictions.parquet``, ``run.json``, ``scores.json``,
``scores_loco.json`` and ``sites_<mode>__<track>.csv``. Only the small json files are
tracked by git (see ``.gitignore``).

A run is reused when ``harness_hash`` in ``run.json`` matches. The hash covers
the case file, tool, adapter source, variant, parameters, tier and modes.
Scoring always runs again because it is cheap.

Scoring rows are written to ``results/leaderboard.csv`` and appended to
``results/log.csv`` with the git commit and a timestamp.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from benchmark import baselines as bl
from benchmark.case import BENCHMARK_VERSION, Case, load_case
from benchmark.leaderboard import RECORD_COLUMNS, assemble
from benchmark.scoring import MIN_RANKED_SITES, group_out_pooled, leave_one_city_out, metrics_from, site_table
from benchmark.system import write_system

REPO = Path(__file__).resolve().parents[1]
BASELINE_TIER = "T1_open_covariates"
NAN_METRICS = {"n_sites": 0, "rho": np.nan, "log_r2": np.nan, "raw_r2": np.nan,
               "calibration_ratio": np.nan, "coverage": np.nan, "ranked": False}


def git_commit() -> str:
    try:
        c = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                           check=True, cwd=REPO).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, cwd=REPO).stdout.strip()
        return c + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def run_dir_for(results: Path, case_id: str, tool: str, variant: str, tier: str) -> Path:
    return results / "runs" / case_id / tool / f"{variant}__{tier[:2]}"


def case_hash(case: Case) -> str:
    return hashlib.sha256((case.case_dir / "case.yaml").read_bytes()).hexdigest()[:16]


def harness_hash(case: Case, tool: str, variant: str, tier: str, modes: list[str],
                 params: dict, extra: str = "") -> str:
    key = json.dumps({"case": case_hash(case), "tool": tool, "variant": variant, "tier": tier,
                      "modes": sorted(modes), "params": params, "extra": extra}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def adapter_source_hash(tool: str) -> str:
    """Hash of the adapter file and the shared contract it builds on."""
    h = hashlib.sha256()
    for f in (REPO / "adapters" / f"{tool}.py", REPO / "adapters" / "_base.py"):
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def blind_copy(case: Case, results: Path) -> Path:
    """A directory of symlinks to the files a tool may see. No counts."""
    d = results / "runs" / case.case_id / "_blind"
    d.mkdir(parents=True, exist_ok=True)
    for name in ("case.yaml", "network.parquet", "inputs"):
        src = (case.case_dir / name).resolve()
        dst = d / name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        if src.exists():
            dst.symlink_to(src)
    return d


def read_run(run_dir: Path) -> dict | None:
    f = run_dir / "run.json"
    return json.loads(f.read_text()) if f.exists() else None


def cached(run_dir: Path, h: str) -> bool:
    rec = read_run(run_dir)
    return bool(rec and rec.get("harness_hash") == h and rec.get("status") in ("complete", "unsupported")
                and (rec["status"] == "unsupported" or rec.get("tool_calibrated")
                     or (run_dir / "predictions.parquet").exists()))


# -- running -----------------------------------------------------------------

def run_baseline(case: Case, name: str, modes: list[str], run_dir: Path, h: str,
                 covariates: pd.DataFrame | None) -> dict:
    from benchmark.system import cpu_time_s, write_system
    run_dir.mkdir(parents=True, exist_ok=True)
    t0, c0 = time.perf_counter(), cpu_time_s()
    pred = bl.baseline_predictions(case, name, modes, covariates)
    pred.to_parquet(run_dir / "predictions.parquet", index=False)
    rec = {
        "case_id": case.case_id, "case_version": case.version, "tool": "baseline",
        "tool_version": bl.BASELINE_VERSION, "variant": name, "family": "baseline",
        "options": {"distance": "n/a", "radius_or_decay": "n/a", "weighting": "n/a",
                    "congestion": "n/a", "covariate": name},
        "input_tier": BASELINE_TIER, "modes": modes, "parameters": {},
        "class_lookup": name == "class_only",
        "wall_time_s": round(time.perf_counter() - t0, 3),
        "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "status": "complete", "n_predictions": int(len(pred)), "harness_hash": h,
        "run_id": f"baseline-{name}-{h}",
    }
    (run_dir / "run.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    write_system(run_dir, tool="baseline", tool_version=bl.BASELINE_VERSION,
                 harness_commit=git_commit(), data_release=f"v{case.benchmark_version}",
                 wall_time_s=rec["wall_time_s"], cpu_s=cpu_time_s() - c0,
                 peak_memory_mb=rec["peak_memory_mb"], threads=1)
    return rec


DEFAULT_TIME_LIMIT_S = 300.0


def run_adapter_cli(case: Case, blind: Path, tool: str, variant: str | None, tier: str,
                    modes: list[str], params: dict, threads: int, run_dir: Path, h: str,
                    time_limit_s: float = DEFAULT_TIME_LIMIT_S, train_dir: Path | None = None) -> dict:
    """Run one adapter process. All modes of a case run in one process, so the
    time limit is per tool, variant and case (per fold on the tool-calibrated
    track). On expiry the process is killed and the run is recorded as timeout."""
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", f"adapters.{tool}", "--case", str(blind), "--tier", tier,
           "--modes", ",".join(modes), "--params", json.dumps(params), "--threads", str(threads),
           "--out", str(run_dir)]
    if variant:
        cmd += ["--variant", variant]
    if train_dir:
        cmd += ["--train", str(train_dir)]
    env = dict(os.environ, PYTHONPATH=str(REPO) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    t0 = time.perf_counter()
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, env=env,
                             timeout=time_limit_s if time_limit_s and time_limit_s > 0 else None)
        rec = read_run(run_dir) or {}
        if res.returncode != 0 and rec.get("status") not in ("failed",):
            rec.update(status="failed", message=(res.stderr or "")[-400:])
        rec.setdefault("status", "complete" if res.returncode == 0 else "failed")
    except subprocess.TimeoutExpired:
        rec = {"status": "timeout", "message": f"killed after {time_limit_s} s"}
        (run_dir / "predictions.parquet").unlink(missing_ok=True)
        write_system(run_dir, tool=tool, tool_version="unknown", harness_commit=git_commit(),
                     data_release=f"v{case.benchmark_version}", wall_time_s=time.perf_counter() - t0,
                     cpu_s=0.0, peak_memory_mb=float("nan"), threads=threads)
    rec["time_limit_s"] = time_limit_s
    rec.setdefault("case_id", case.case_id)
    rec.setdefault("case_version", case.version)
    rec.setdefault("tool", tool)
    rec.setdefault("variant", variant or "default")
    if "family" not in rec:  # the adapter wrote no record (timeout or crash): take its declaration
        try:
            import importlib
            from adapters._base import Adapter
            mod = importlib.import_module(f"adapters.{tool}")
            cls = next(c for c in vars(mod).values() if isinstance(c, type) and issubclass(c, Adapter) and c is not Adapter)
            rec["family"] = cls.variants.get(variant or next(iter(cls.variants)), {}).get("family", cls.family)
        except Exception:
            rec["family"] = "other"
    rec.setdefault("input_tier", tier)
    rec.setdefault("wall_time_s", round(time.perf_counter() - t0, 3))
    rec["harness_hash"] = h
    rec.setdefault("run_id", f"{tool}-{rec['variant']}-{h}")
    (run_dir / "run.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec


def run_tool_calibrated(case: Case, blind: Path, tool: str, variant: str | None, tier: str,
                        modes: list[str], params: dict, threads: int, run_dir: Path, h: str,
                        time_limit_s: float) -> dict:
    """Tool-calibrated track: one adapter call per fold, given only the other folds' counts.

    Fold ``k``'s call writes ``fold<k>/predictions.parquet``. Only its fold-k
    sites are scored from it, so a held-out count is never in the tool's input.
    """
    sites, xw = case.sites, case.crosswalk
    recs, wall = [], 0.0
    for k in sorted(sites["fold"].dropna().unique().astype(int)):
        train = run_dir / f"fold{k}" / "_train"
        train.mkdir(parents=True, exist_ok=True)
        ts = sites[sites["fold"] != k][["site_id", "mode", "value", "x", "y", "fold"]]
        if ts.merge(sites[sites["fold"] == k][["site_id", "mode"]]).shape[0]:
            raise RuntimeError("held-out site in training counts")
        ts.to_csv(train / "training_sites.csv", index=False)
        xw.merge(ts[["site_id", "mode"]]).to_csv(train / "training_crosswalk.csv", index=False)
        r = run_adapter_cli(case, blind, tool, variant, tier, modes, params, threads, run_dir / f"fold{k}",
                            h, time_limit_s, train)
        recs.append(r)
        wall += float(r.get("wall_time_s") or 0)
        if r.get("status") != "complete":
            break
    rec = {k: v for k, v in recs[-1].items() if k not in ("wall_time_s", "status", "message")}
    bad = [r for r in recs if r.get("status") != "complete"]
    rec.update(status=bad[0]["status"] if bad else "complete", tool_calibrated=True, folds=len(recs),
               wall_time_s=round(wall, 3), time_limit_s=time_limit_s, harness_hash=h,
               run_id=f"{tool}-{variant or 'default'}-toolcal-{h}")
    if bad:
        rec["message"] = bad[0].get("message", "")
    (run_dir / "run.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    write_system(run_dir, tool=tool, tool_version=str(rec.get("tool_version", "unknown")),
                 harness_commit=git_commit(), data_release=f"v{case.benchmark_version}",
                 wall_time_s=wall, cpu_s=0.0, peak_memory_mb=max(float(r.get("peak_memory_mb") or 0) for r in recs),
                 threads=threads)
    return rec


# -- scoring -----------------------------------------------------------------

def _row(case: Case, rec: dict, mode: str, track: str, split: str, metrics: dict,
         status: str, commit: str, stamp: str) -> dict:
    opts = rec.get("options", {})
    return {
        "benchmark_version": case.benchmark_version, "case_id": case.case_id,
        "case_version": case.version, "mode": mode, "tool": rec["tool"],
        "tool_version": rec.get("tool_version", ""), "variant": rec["variant"],
        "family": rec.get("family", "other"),
        "options": json.dumps(opts, sort_keys=True) if not isinstance(opts, str) else opts,
        "input_tier": rec["input_tier"], "track": track, "split": split,
        **{k: metrics[k] for k in ("n_sites", "rho", "log_r2", "raw_r2", "calibration_ratio", "coverage", "ranked")},
        "wall_time_s": rec.get("wall_time_s", np.nan), "peak_memory_mb": rec.get("peak_memory_mb", np.nan),
        "time_limit_s": rec.get("time_limit_s", np.nan),
        "run_id": rec["run_id"], "git_commit": commit, "timestamp": stamp, "status": status,
    }


def tracks_for(rec: dict) -> list[tuple[str, bool]]:
    """(track, scale) pairs to score: own calibration as submitted, else one scale factor."""
    if rec.get("tool_calibrated"):
        return [("own_calibration", False)]
    return [("uncalibrated", True)]


def score_run(case: Case, rec: dict, run_dir: Path, site_class: pd.Series, commit: str,
              stamp: str) -> list[dict]:
    """Score one run. Writes sites_<mode>.csv and scores.json. Returns the rows."""
    rows, info_all = [], {}
    modes = rec.get("modes") or case.modes
    # Modes the adapter declared unsupported are not scored (a missing flow is
    # not a zero flow).
    modes = [m for m in modes if m not in (rec.get("modes_unsupported") or {})]
    status = rec.get("status", "failed")
    by_class = bool(rec.get("class_lookup"))
    pred = None
    if status == "complete" and (run_dir / "predictions.parquet").exists():
        pred = pd.read_parquet(run_dir / "predictions.parquet")
    if status == "complete" and rec.get("tool_calibrated"):
        pred = {int(f.parent.name[4:]): pd.read_parquet(f) for f in run_dir.glob("fold*/predictions.parquet")}
    for mode in modes:
        for track, scale in tracks_for(rec):
            if pred is None:
                rows.append(_row(case, rec, mode, track, "group_out_pooled", NAN_METRICS,
                                 status, commit, stamp))
                continue
            if track == "own_calibration":
                m, scored = tool_calibrated_pooled(case, pred, mode, site_class)
                scored.to_csv(run_dir / f"sites_{mode}__{track}.csv", index=False)
                rows.append(_row(case, rec, mode, track, "group_out_pooled", m, "complete", commit, stamp))
                continue
            t, info = site_table(case.sites, case.crosswalk, pred, mode, site_class)
            info_all[mode] = info
            m, scored, coefs = group_out_pooled(t, scale, by_class)
            scored.to_csv(run_dir / f"sites_{mode}__{track}.csv", index=False)
            rows.append(_row(case, rec, mode, track, "group_out_pooled", m, "complete", commit, stamp))
            info_all[f"{mode}__{track}__coefficients"] = coefs
    (run_dir / "scores.json").write_text(json.dumps(rows, indent=1, default=_json_default) + "\n")
    (run_dir / "scores_info.json").write_text(json.dumps(info_all, indent=1, default=_json_default) + "\n")
    return rows


def tool_calibrated_pooled(case: Case, preds: dict[int, pd.DataFrame], mode: str,
                           site_class: pd.Series) -> tuple[dict, pd.DataFrame]:
    """Score each fold's held-out sites with the predictions of the call that did not see them."""
    parts = []
    for k, pred in preds.items():
        t, _ = site_table(case.sites, case.crosswalk, pred, mode, site_class)
        parts.append(t[t["fold"] == k].assign(oof=lambda d: d["flow"]))
    t = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["value", "oof", "flow"])
    m = metrics_from(t["value"], t["oof"], t["flow"])
    m["ranked"] = m["n_sites"] >= MIN_RANKED_SITES
    return m, t


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)


def score_loco(cases: dict[str, Case], results: Path, run_keys: list[tuple], commit: str,
               stamp: str) -> list[dict]:
    """Leave-one-city-out rows for tool/variant/tier that exist on two or more cases."""
    rows = []
    by_key: dict[tuple, dict[str, Path]] = {}
    for cid, tool, variant, tier in run_keys:
        by_key.setdefault((tool, variant, tier), {})[cid] = run_dir_for(results, cid, tool, variant, tier)
    for (tool, variant, tier), dirs in by_key.items():
        if len(dirs) < 2:
            continue
        recs = {cid: read_run(d) for cid, d in dirs.items()}
        if any(r is None or r.get("status") != "complete" for r in recs.values()):
            continue
        rec0 = next(iter(recs.values()))
        by_class = bool(rec0.get("class_lookup"))
        for track, scale in tracks_for(rec0):
            if track == "own_calibration":
                continue  # the tool's own calibration is not refitted across cities
            # Every mode scored in two or more cases (cases without it sit out).
            modes = sorted(set().union(*[set(r.get("modes", [])) - set(r.get("modes_unsupported") or {})
                                         for r in recs.values()]))
            for mode in modes:
                tables = {}
                for cid, d in dirs.items():
                    ff = d / f"sites_{mode}__{track}.csv"
                    if ff.exists():
                        tables[cid] = pd.read_csv(ff, dtype={"site_id": str})[
                            ["site_id", "value", "flow", "road_class"]]
                if len(tables) < 2:
                    continue
                for cid, (m, _, _) in leave_one_city_out(tables, scale, by_class).items():
                    rows.append(_row(cases[cid], recs[cid], mode, track, "leave_one_city_out", m,
                                     "complete", commit, stamp))
        for cid, d in dirs.items():
            mine = [r for r in rows if r["case_id"] == cid and r["tool"] == recs[cid]["tool"]
                    and r["variant"] == recs[cid]["variant"] and r["input_tier"] == recs[cid]["input_tier"]]
            (d / "scores_loco.json").write_text(json.dumps(mine, indent=1, default=_json_default) + "\n")
    return rows


# -- main --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run tools on cases and write the AADTBench leaderboards.")
    p.add_argument("--cases", nargs="+", required=True)
    p.add_argument("--tools", nargs="+", default=["baselines"])
    p.add_argument("--tier", nargs="+", default=[BASELINE_TIER])
    p.add_argument("--modes", default=None, help="comma separated, default every case mode")
    p.add_argument("--variants", nargs="*", default=None, help="adapter variants (default: adapter's first)")
    p.add_argument("--params", default="{}", help="JSON overrides passed to adapters")
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--results-dir", default=str(REPO / "results"))
    p.add_argument("--cases-root", default=None)
    p.add_argument("--from-dir", default=None, help="local mirror of release assets for fetch")
    p.add_argument("--version", default=BENCHMARK_VERSION)
    p.add_argument("--force", action="store_true", help="ignore cached runs")
    p.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT_S,
                   help="wall time limit in s per tool, variant and case (0 for none)")
    p.add_argument("--tool-calibrated", action="store_true",
                   help="run adapters on the tool-calibrated track (one call per fold)")
    a = p.parse_args(argv)

    results = Path(a.results_dir)
    commit, stamp = git_commit(), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    params = json.loads(a.params)
    want_modes = a.modes.split(",") if a.modes else None
    cases = {}
    for c in a.cases:
        cs = load_case(c, a.cases_root, a.version, a.from_dir)
        cases[cs.case_id] = cs
    all_rows, run_keys = [], []
    for cid, case in cases.items():
        modes = [m for m in case.modes if not want_modes or m in want_modes]
        site_class = case.site_road_class()
        blind = None
        covs = None
        for tool in a.tools:
            jobs = []
            if tool == "baselines":
                jobs = [("baseline", n, BASELINE_TIER) for n in bl.BASELINES]
            else:
                jobs = [(tool, v, t) for v in (a.variants or [None]) for t in a.tier]
            for jtool, variant, tier in jobs:
                label = (variant or "default") + ("-toolcal" if a.tool_calibrated and jtool != "baseline" else "")
                rd = run_dir_for(results, cid, jtool, label, tier)
                h = harness_hash(case, jtool, label, tier, modes, params,
                                 bl.BASELINE_VERSION if jtool == "baseline" else adapter_source_hash(jtool))
                if a.force or not cached(rd, h):
                    print(f"[run] {cid} {jtool} {label} {tier}", flush=True)
                    if jtool == "baseline":
                        if covs is None and label != "class_only":
                            covs = bl.segment_covariates(case)
                        rec = run_baseline(case, label, modes, rd, h, covs)
                    else:
                        blind = blind or blind_copy(case, results)
                        run = run_tool_calibrated if a.tool_calibrated else run_adapter_cli
                        rec = run(case, blind, jtool, variant, tier, modes, params, a.threads, rd, h,
                                  a.time_limit)
                else:
                    print(f"[cached] {cid} {jtool} {label} {tier}", flush=True)
                    rec = read_run(rd)
                rows = score_run(case, rec, rd, site_class, commit, stamp)
                all_rows += rows
                run_keys.append((cid, jtool, label, tier))
    if len(cases) >= 2:
        all_rows += score_loco(cases, results, run_keys, commit, stamp)

    df = assemble(results)
    log = pd.DataFrame(all_rows)
    for c in RECORD_COLUMNS:
        if c not in log.columns:
            log[c] = np.nan
    log = log[RECORD_COLUMNS]
    logf = results / "log.csv"
    log.to_csv(logf, mode="a", header=not logf.exists(), index=False)
    print(f"scored {len(all_rows)} rows. leaderboard.csv has {len(df)} rows.")
    ok = log[(log["status"] == "complete")]
    if len(ok):
        print(ok[["case_id", "mode", "tool", "variant", "track", "split", "n_sites", "rho", "log_r2", "coverage"]]
              .round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
