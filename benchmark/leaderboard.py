"""Assemble leaderboards from the scores stored in run directories."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RECORD_COLUMNS = [
    "benchmark_version", "case_id", "case_version", "mode", "tool", "tool_version", "variant",
    "family", "options", "input_tier", "track", "split", "n_sites", "rho", "log_r2", "raw_r2",
    "calibration_ratio", "coverage", "ranked", "time_limit_s", "wall_time_s", "cpu_time_s", "speed_index",
    "peak_memory_mb", "cpu_model", "container_image_digest", "data_release", "run_id",
    "git_commit", "timestamp", "status",
]
SYSTEM_FIELDS = ("cpu_time_s", "speed_index", "cpu_model", "container_image_digest", "data_release")
SPLIT_ORDER = {"group_out_pooled": 0, "leave_one_city_out": 1}


def load_rows(results_dir: Path) -> pd.DataFrame:
    rows = []
    for name in ("scores.json", "scores_loco.json"):
        for f in sorted((Path(results_dir) / "runs").glob(f"*/*/*/{name}")):
            sysf = f.parent / "system.json"
            if not sysf.exists():
                continue
            sysrec = json.loads(sysf.read_text())
            for r in json.loads(f.read_text()):
                r.update({k: sysrec.get(k) for k in SYSTEM_FIELDS})
                rows.append(r)
    df = pd.DataFrame(rows)
    for c in RECORD_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    return df[RECORD_COLUMNS]


def add_rank(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_s"] = df["split"].map(SPLIT_ORDER).fillna(9)
    df["_r"] = df["rho"].fillna(-np.inf)
    df = df.sort_values(["case_id", "mode", "track", "_s", "family", "input_tier", "_r"],
                        ascending=[True, True, True, True, True, True, False])
    keys = ["case_id", "mode", "track", "split", "family", "input_tier"]
    ok = df["ranked"].fillna(False).astype(bool) & df["rho"].notna() & (df["status"] == "complete")
    df["rank"] = np.nan
    df.loc[ok, "rank"] = df[ok].groupby(keys).cumcount() + 1
    return df.drop(columns=["_s", "_r"])


def _fmt(v, nd=3):
    return "" if pd.isna(v) else f"{v:.{nd}f}"


def markdown(df: pd.DataFrame) -> str:
    out = ["# AADTBench leaderboard", "",
           "Ranked by Spearman `rho`. `log_r2` and `coverage` (share of sites with flow > 0) are secondary. "
           "Targets with fewer than 20 sites are shown but not ranked.", ""]
    if df.empty:
        return "\n".join(out + ["No results yet.", ""])
    for (case, mode, track), g in df.groupby(["case_id", "mode", "track"], sort=True):
        out += [f"## {case} / {mode} / {track}", ""]
        for (split, fam), h in g.groupby(["split", "family"], sort=True):
            out += [f"### {split}, family {fam}", "",
                    "| rank | tool | variant | tier | options | n | rho | log_r2 | coverage | time s | status |",
                    "|---|---|---|---|---|---|---|---|---|---|---|"]
            for _, r in h.sort_values(["input_tier", "rank", "rho"], ascending=[True, True, False]).iterrows():
                rk = "" if pd.isna(r["rank"]) else int(r["rank"])
                opts = r["options"] if isinstance(r["options"], str) else ""
                out.append(f"| {rk} | {r['tool']} | {r['variant']} | {r['input_tier']} | `{opts}` | "
                           f"{'' if pd.isna(r['n_sites']) else int(r['n_sites'])} | {_fmt(r['rho'])} | "
                           f"{_fmt(r['log_r2'])} | {_fmt(r['coverage'])} | "
                           f"{_fmt(r['wall_time_s'], 1)} | {r['status']} |")
            out.append("")
    return "\n".join(out)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    d = df[(df["split"] == "group_out_pooled") & (df["status"] == "complete") & df["rho"].notna()]
    d = d.sort_values("rho", ascending=False).drop_duplicates(["case_id", "mode", "track", "tool"])
    cols = ["case_id", "mode", "track", "tool", "variant", "input_tier", "n_sites", "rho", "log_r2", "coverage"]
    return d[cols].sort_values(["case_id", "mode", "track", "rho"],
                               ascending=[True, True, True, False]).round({"rho": 3, "log_r2": 3, "coverage": 3})


def assemble(results_dir: str | Path = "results") -> pd.DataFrame:
    rd = Path(results_dir)
    df = add_rank(load_rows(rd))
    rd.mkdir(parents=True, exist_ok=True)
    df.to_csv(rd / "leaderboard.csv", index=False)
    (rd / "LEADERBOARD.md").write_text(markdown(df) + "\n")
    summary(df).to_csv(rd / "summary.csv", index=False)
    return df
