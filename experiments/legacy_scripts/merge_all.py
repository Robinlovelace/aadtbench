#!/usr/bin/env python3
"""Merge all independent tool centrality and gravity model benchmark results.

Each benchmark script writes a per-tool CSV (results/<city>_<tool>_results.csv)
containing one or more modes (distinguished by the `mode` column). This script
concatenates them, de-duplicates on (tool, mode, variant), computes the shared
`efficiency_score` composite (scripts/csv_utils.add_efficiency_score, applied
identically to every tool), and writes the combined results/<city>_results.csv
consumed by the report.

Usage:  PYTHONPATH=. python scripts/merge_all.py --city leuven
        PYTHONPATH=. python scripts/merge_all.py --city leeds
"""
import argparse
import glob
import os
import pandas as pd

from scripts.csv_utils import add_efficiency_score

RESULTS_DIR = "results"
CSV_COLUMNS = [
    "tool", "mode", "variant", "r_squared", "pearson_r", "spearman_r",
    "compute_time_s", "n_matched", "n_obs", "peak_memory_mb", "segments_per_sec",
    "efficiency_score",
]

# Per-tool result file suffixes (order doesn't matter; merged by concat + de-dup).
# "{city}_" is prepended; sdna/cityseer_demand/etc. all follow the same convention.
TOOL_FILE_SUFFIXES = [
    "centrality_results.csv",
    "cityseer_demand_results.csv",
    "cityseer_od_results.csv",
    "madina_worldpop_results.csv",
    "flownet_results.csv",
    "sdna_results.csv",
    "aequilibrae_results.csv",
]


def main():
    parser = argparse.ArgumentParser(description="Merge all per-tool result CSVs for a city.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven, leeds)")
    args = parser.parse_args()
    city = args.city

    dfs = []
    for suffix in TOOL_FILE_SUFFIXES:
        f = os.path.join(RESULTS_DIR, f"{city}_{suffix}")
        if os.path.exists(f):
            try:
                df = pd.read_csv(f)
                if len(df) > 0:
                    # Backfill mode column for legacy single-mode files.
                    if "mode" not in df.columns:
                        df["mode"] = "walk"
                    dfs.append(df)
                    print(f"Read {len(df)} rows from {f}")
            except Exception as e:
                print(f"Warning: could not read {f}: {e}")

    if not dfs:
        print(f"No results files found to merge for city={city}")
        return

    df_all = pd.concat(dfs, ignore_index=True)
    df_all = add_efficiency_score(df_all)
    cols = [c for c in CSV_COLUMNS if c in df_all.columns]
    df_all = df_all[cols]
    # De-duplicate based on tool + mode + variant (keep last = most recent run).
    dedup_keys = [c for c in ["tool", "mode", "variant"] if c in df_all.columns]
    df_all = df_all.drop_duplicates(subset=dedup_keys, keep="last")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"{city}_results.csv")
    df_all.to_csv(out, index=False)
    print(f"Merged {len(df_all)} variants into {out}")
    if "mode" in df_all.columns:
        print("Modes present:", sorted(df_all["mode"].dropna().unique().tolist()))
    print("Tools present:", sorted(df_all["tool"].unique().tolist()))


if __name__ == "__main__":
    main()
