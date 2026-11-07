"""Run tools on cases, score every run, and write the leaderboards."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from benchmark import baselines as bl
from benchmark.case import BENCHMARK_VERSION, Case, load_case
from benchmark.leaderboard import RECORD_COLUMNS, assemble
from benchmark.scoring import group_out_pooled, leave_one_city_out, site_table
from benchmark.system import cpu_time_s, write_system

REPO = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO / "config" / "benchmark.yaml"
BASELINE_TIER = "T1_open_covariates"
NAN_METRICS = {"n_sites": 0, "rho": np.nan, "log_r2": np.nan, "raw_r2": np.nan,
               "calibration_ratio": np.nan, "coverage": np.nan, "ranked": False}


def _limits() -> tuple[float, int]:
    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text()).get("limits", {})
        return float(cfg.get("full_case_time_limit_s", 600.0)), int(cfg.get("full_case_threads", 8))
    except Exception:
        return 600.0, 8


DEFAULT_TIME_LIMIT_S, DEFAULT_THREADS = _limits()


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


def harness_hash(case: Case, tool: str, variant: str, tier: str, modes: list[str],
                 params: dict, extra: str = "") -> str:
    ch = hashlib.sha256((case.case_dir / "case.yaml").read_bytes()).hexdigest()[:16]
    key = json.dumps({"case": ch, "tool": tool, "variant": variant, "tier": tier,
                      "modes": sorted(modes), "params": params, "extra": extra}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def adapter_source_hash(tool: str) -> str:
    h = hashlib.sha256()
    for f in (REPO / "adapters" / f"{tool}.py", REPO / "adapters" / "_base.py"):
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def blind_copy(case: Case, results: Path) -> Path:
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


def cached(run_dir: Path, h: str, case_version: str = "") -> bool:
    rec = read_run(run_dir)
    if not rec or rec.get("status") not in ("complete", "unsupported"):
        return False
    if rec["status"] != "unsupported" and not (run_dir / "predictions.parquet").exists():
        return False
    return rec.get("harness_hash") == h or (bool(case_version) and str(rec.get("case_version")) == str(case_version))


def run_baseline(case: Case, name: str, modes: list[str], run_dir: Path, h: str,
                 covariates: pd.DataFrame | None) -> dict:
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


def _declared_family(tool: str, variant: str | None) -> str:
    try:
        from adapters._base import Adapter
        mod = importlib.import_module(f"adapters.{tool}")
        cls = next(v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Adapter) and v is not Adapter)
        return (cls.variants.get(variant or "default") or {}).get("family", cls.family)
    except Exception:
        return "other"


def _image_digest(image: str) -> str:
    try:
        out = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                             capture_output=True, text=True, check=True).stdout.strip()
        return f"{image}@{out}" if out else image
    except Exception:
        return image


def run_adapter_cli(case: Case, blind: Path, tool: str, variant: str | None, tier: str,
                    modes: list[str], params: dict, threads: int, run_dir: Path, h: str,
                    time_limit_s: float = DEFAULT_TIME_LIMIT_S,
                    docker: bool = False, docker_tag: str = "ci") -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    cname = None
    if docker:
        image = f"aadtbench-{tool}:{docker_tag}"
        cname = f"aadtbench-{case.case_id}-{tool}-{variant or 'default'}-{os.getpid()}-{int(time.time() * 1000) % 100000}"
        mounts = [arg for p in sorted(blind.iterdir()) for arg in ("-v", f"{p.resolve()}:/case/{p.name}:ro")]
        cmd = ["docker", "run", "--rm", "--name", cname, "--user", f"{os.getuid()}:{os.getgid()}",
               "-e", f"AADTBENCH_IMAGE_DIGEST={_image_digest(image)}",
               "-e", "MPLCONFIGDIR=/tmp/matplotlib",
               *mounts, "-v", f"{run_dir.resolve()}:/out",
               "--entrypoint", "python", image, "-m", f"adapters.{tool}",
               "--case", "/case", "--tier", tier, "--modes", ",".join(modes),
               "--params", json.dumps(params), "--threads", str(threads), "--out", "/out"]
    else:
        cmd = [sys.executable, "-m", f"adapters.{tool}", "--case", str(blind), "--tier", tier,
               "--modes", ",".join(modes), "--params", json.dumps(params), "--threads", str(threads),
               "--out", str(run_dir)]
    if variant:
        cmd += ["--variant", variant]
    env = dict(os.environ, PYTHONPATH=str(REPO) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            cwd=REPO, env=env, start_new_session=True)
    try:
        _, stderr = proc.communicate(timeout=time_limit_s if time_limit_s and time_limit_s > 0 else None)
        rec = read_run(run_dir) or {}
        if proc.returncode != 0 and rec.get("status") != "failed":
            rec.update(status="failed", message=(stderr or "")[-400:])
        rec.setdefault("status", "complete" if proc.returncode == 0 else "failed")
    except subprocess.TimeoutExpired:
        if cname:
            subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                break
        proc.communicate()
        rec = {"status": "timeout", "message": f"killed after {time_limit_s} s"}
        (run_dir / "predictions.parquet").unlink(missing_ok=True)
        for p in run_dir.glob("tmp*"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        write_system(run_dir, tool=tool, tool_version="unknown", harness_commit=git_commit(),
                     data_release=f"v{case.benchmark_version}", wall_time_s=time.perf_counter() - t0,
                     cpu_s=0.0, peak_memory_mb=float("nan"), threads=threads)
    rec["time_limit_s"] = time_limit_s
    rec.setdefault("case_id", case.case_id)
    rec.setdefault("case_version", case.version)
    rec.setdefault("tool", tool)
    rec.setdefault("variant", variant or "default")
    rec.setdefault("family", _declared_family(tool, variant))
    rec.setdefault("input_tier", tier)
    rec.setdefault("wall_time_s", round(time.perf_counter() - t0, 3))
    rec["harness_hash"] = h
    rec.setdefault("run_id", f"{tool}-{rec['variant']}-{h}")
    (run_dir / "run.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec


def _json_default(o):
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)


def _row(case: Case, rec: dict, mode: str, split: str, metrics: dict,
         status: str, commit: str, stamp: str) -> dict:
    opts = rec.get("options", {})
    return {
        "benchmark_version": case.benchmark_version, "case_id": case.case_id,
        "case_version": case.version, "mode": mode, "tool": rec["tool"],
        "tool_version": rec.get("tool_version", ""), "variant": rec["variant"],
        "family": rec.get("family", "other"),
        "options": json.dumps(opts, sort_keys=True) if not isinstance(opts, str) else opts,
        "input_tier": rec["input_tier"], "track": "uncalibrated", "split": split,
        **{k: metrics[k] for k in ("n_sites", "rho", "log_r2", "raw_r2", "calibration_ratio", "coverage", "ranked")},
        "wall_time_s": rec.get("wall_time_s", np.nan), "peak_memory_mb": rec.get("peak_memory_mb", np.nan),
        "time_limit_s": rec.get("time_limit_s", np.nan),
        "run_id": rec["run_id"], "git_commit": commit, "timestamp": stamp, "status": status,
    }


def score_run(case: Case, rec: dict, run_dir: Path, site_class: pd.Series, commit: str,
              stamp: str) -> list[dict]:
    rows = []
    modes = [m for m in (rec.get("modes") or case.modes) if m not in (rec.get("modes_unsupported") or {})]
    status = rec.get("status", "failed")
    by_class = bool(rec.get("class_lookup"))
    pred = pd.read_parquet(run_dir / "predictions.parquet") if (status == "complete" and (run_dir / "predictions.parquet").exists()) else None
    for mode in modes:
        if pred is None:
            rows.append(_row(case, rec, mode, "group_out_pooled", NAN_METRICS, status, commit, stamp))
            continue
        t, _ = site_table(case.sites, case.crosswalk, pred, mode, site_class)
        m, scored, _ = group_out_pooled(t, True, by_class)
        scored.to_csv(run_dir / f"sites_{mode}__uncalibrated.csv", index=False)
        rows.append(_row(case, rec, mode, "group_out_pooled", m, "complete", commit, stamp))
    (run_dir / "scores.json").write_text(json.dumps(rows, indent=1, default=_json_default) + "\n")
    return rows


def score_loco(cases: dict[str, Case], results: Path, run_keys: list[tuple], commit: str,
               stamp: str) -> list[dict]:
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
        by_class = bool(next(iter(recs.values())).get("class_lookup"))
        modes = sorted(set().union(*[set(r.get("modes", [])) - set(r.get("modes_unsupported") or {})
                                     for r in recs.values()]))
        for mode in modes:
            tables = {cid: pd.read_csv(d / f"sites_{mode}__uncalibrated.csv", dtype={"site_id": str})[
                ["site_id", "value", "flow", "road_class"]]
                for cid, d in dirs.items() if (d / f"sites_{mode}__uncalibrated.csv").exists()}
            if len(tables) < 2:
                continue
            for cid, (m, _, _) in leave_one_city_out(tables, True, by_class).items():
                rows.append(_row(cases[cid], recs[cid], mode, "leave_one_city_out", m, "complete", commit, stamp))
        for cid, d in dirs.items():
            mine = [r for r in rows if r["case_id"] == cid and r["tool"] == recs[cid]["tool"]
                    and r["variant"] == recs[cid]["variant"] and r["input_tier"] == recs[cid]["input_tier"]]
            (d / "scores_loco.json").write_text(json.dumps(mine, indent=1, default=_json_default) + "\n")
    return rows


def main(argv: list[str] | None = None) -> int:
    from concurrent.futures import ThreadPoolExecutor
    p = argparse.ArgumentParser(description="Run tools on cases and write the AADTBench leaderboards.")
    p.add_argument("--cases", nargs="+", default=None)
    p.add_argument("--tools", nargs="+", default=["baselines"])
    p.add_argument("--tier", nargs="+", default=None)
    p.add_argument("--modes", default=None)
    p.add_argument("--variants", nargs="*", default=None)
    p.add_argument("--params", default="{}")
    p.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    p.add_argument("--jobs", "-j", type=int, default=1)
    p.add_argument("--docker", action="store_true")
    p.add_argument("--docker-tag", default="ci")
    p.add_argument("--results-dir", default=str(REPO / "results"))
    p.add_argument("--cases-root", default=None)
    p.add_argument("--from-dir", default=None)
    p.add_argument("--version", default=BENCHMARK_VERSION)
    p.add_argument("--force", action="store_true")
    p.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT_S)
    a = p.parse_args(argv)

    cfg = yaml.safe_load(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    tools_cfg = cfg.get("tools") or {}

    if a.cases is None:
        all_tools = ["baselines" if t == "baseline" else t for t in tools_cfg] or ["baselines"]
        run_tools = all_tools if a.tools == ["baselines"] and "--tools" not in (argv or sys.argv[1:]) else a.tools
        for group in (cfg["cases"]["open"], cfg["cases"].get("non_commercial", [])):
            if not group:
                continue
            cmd = ["--cases", *group, "--tools", *run_tools,
                   "--threads", str(a.threads), "--jobs", str(a.jobs),
                   "--time-limit", str(a.time_limit), "--results-dir", a.results_dir,
                   "--docker-tag", a.docker_tag]
            if a.docker:
                cmd.append("--docker")
            if a.force:
                cmd.append("--force")
            main(cmd)
        if Path(a.results_dir) == REPO / "results" and (REPO / "results" / "summary.csv").exists():
            shutil.copyfile(REPO / "results" / "summary.csv", REPO / "leaderboard-summary.csv")
        return 0

    results = Path(a.results_dir)
    commit, stamp = git_commit(), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    params = json.loads(a.params)
    want_modes = a.modes.split(",") if a.modes else None
    cases = {cs.case_id: cs for cs in (load_case(c, a.cases_root, a.version, a.from_dir) for c in a.cases)}
    blinds = {cid: blind_copy(case, results) for cid, case in cases.items()}
    site_classes = {cid: case.site_road_class() for cid, case in cases.items()}
    cov_cache: dict[str, pd.DataFrame] = {}

    tasks = []
    for cid, case in cases.items():
        modes = [m for m in case.modes if not want_modes or m in want_modes]
        for tool in a.tools:
            if tool in ("baselines", "baseline"):
                jobs = [("baseline", n, BASELINE_TIER) for n in (a.variants or bl.BASELINES)]
                if any(n != "class_only" for _, n, _ in jobs) and cid not in cov_cache:
                    cov_cache[cid] = bl.segment_covariates(case)
            else:
                tcfg = tools_cfg.get(tool) or {}
                tiers = a.tier or ([tcfg["tier"]] if "tier" in tcfg else [BASELINE_TIER])
                variants = a.variants or tcfg.get("variants") or [None]
                jobs = [(tool, v, t) for v in variants for t in tiers]
            for jtool, variant, tier in jobs:
                tasks.append((cid, case, modes, jtool, variant, tier))

    def _exec_one(item):
        cid, case, modes, jtool, variant, tier = item
        label = variant or "default"
        rd = run_dir_for(results, cid, jtool, label, tier)
        h = harness_hash(case, jtool, label, tier, modes, params,
                         bl.BASELINE_VERSION if jtool == "baseline" else adapter_source_hash(jtool))
        if a.force or not cached(rd, h, case.version if not params else ""):
            print(f"[run] {cid} {jtool} {label} {tier}", flush=True)
            if jtool == "baseline":
                rec = run_baseline(case, label, modes, rd, h, cov_cache.get(cid))
            else:
                rec = run_adapter_cli(case, blinds[cid], jtool, variant, tier, modes, params,
                                      a.threads, rd, h, a.time_limit, docker=a.docker, docker_tag=a.docker_tag)
        else:
            print(f"[cached] {cid} {jtool} {label} {tier}", flush=True)
            rec = read_run(rd)
        rows = score_run(case, rec, rd, site_classes[cid], commit, stamp)
        return rows, (cid, jtool, label, tier)

    all_rows, run_keys = [], []
    if a.jobs > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=a.jobs) as pool:
            for rows, rk in pool.map(_exec_one, tasks):
                all_rows += rows
                run_keys.append(rk)
    else:
        for item in tasks:
            rows, rk = _exec_one(item)
            all_rows += rows
            run_keys.append(rk)

    if len(cases) >= 2:
        all_rows += score_loco(cases, results, run_keys, commit, stamp)

    df = assemble(results)
    print(f"scored {len(all_rows)} rows. leaderboard.csv has {len(df)} rows.")
    ok = pd.DataFrame(all_rows)
    if len(ok) and "status" in ok:
        ok = ok[ok["status"] == "complete"]
        if len(ok):
            print(ok[["case_id", "mode", "tool", "variant", "split", "n_sites", "rho", "log_r2", "coverage"]]
                  .round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
