#!/usr/bin/env python3
"""Uniform CSV merge helper for all benchmark scripts.
Usage:
    from scripts.csv_utils import merge_to_csv
    merge_to_csv("cityseer", new_rows, "results/leuven_results.csv")
"""
import math

import pandas as pd
import os

CSV_COLUMNS = [
    "tool", "mode", "variant", "r_squared", "pearson_r", "spearman_r",
    "compute_time_s", "n_matched", "n_obs", "peak_memory_mb", "segments_per_sec"
]

# Minimum value substituted for compute_time_s/peak_memory_mb when missing or
# zero, so log10(1 + x) stays finite (see efficiency_score docstring).
_MIN_POSITIVE = 1e-9


def efficiency_score(r_squared, compute_time_s, peak_memory_mb):
    """Composite headline measure combining accuracy, speed, and memory.

    efficiency_score = max(r_squared, 0) / (log10(1 + time_s) * log10(1 + mem_mb))

    Higher is better. R^2 <= 0 (no better than random) scores 0. Time and
    memory are log-scaled so the fastest/lightest tool doesn't trivially
    dominate, and so runtime/memory don't swamp accuracy on a multiplicative
    scale. compute_time_s/peak_memory_mb of 0 or NaN are floored at
    _MIN_POSITIVE so the score stays finite rather than becoming inf/NaN.
    """
    if pd.isna(r_squared):
        return 0.0
    r2 = max(float(r_squared), 0.0)
    t = compute_time_s if pd.notna(compute_time_s) and compute_time_s > 0 else _MIN_POSITIVE
    m = peak_memory_mb if pd.notna(peak_memory_mb) and peak_memory_mb > 0 else _MIN_POSITIVE
    denom = math.log10(1 + t) * math.log10(1 + m)
    if denom <= 0:
        return 0.0
    return r2 / denom


def add_efficiency_score(df):
    """Add/overwrite the `efficiency_score` column on a results DataFrame,
    applying the shared efficiency_score() formula identically to every row
    (i.e. every tool) so tools are comparable on a single number."""
    if df.empty:
        df["efficiency_score"] = pd.Series(dtype=float)
        return df
    df = df.copy()
    df["efficiency_score"] = [
        efficiency_score(row.r_squared, row.compute_time_s, row.peak_memory_mb)
        for row in df.itertuples()
    ]
    return df


def merge_to_csv(tool_name, new_df, results_path="results/leuven_results.csv"):
    """Remove old rows for tool_name, append new_df, save."""
    os.makedirs(os.path.dirname(results_path), exist_ok=True)

    if os.path.exists(results_path):
        try:
            df_old = pd.read_csv(results_path)
        except (pd.errors.EmptyDataError, pd.errors.ParserError):
            df_old = pd.DataFrame(columns=CSV_COLUMNS)
        df_old = df_old[df_old["tool"] != tool_name]
        df_all = pd.concat([df_old, new_df], ignore_index=True)
    else:
        df_all = new_df

    df_all.to_csv(results_path, index=False)
    return df_all
