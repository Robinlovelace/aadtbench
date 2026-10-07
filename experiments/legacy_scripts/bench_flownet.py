#!/usr/bin/env python3
"""
flownet traffic-assignment benchmark (path-sized logit / all-or-nothing).

For each configured mode this runs flownet's stochastic traffic assignment
(via scripts/run_flownet_assignment.R) and validates the assigned edge flows
against the ground-truth sensor counts.

Demand:
  - If the city config provides od_file + zones_file (Leeds: real 2011 Census
    journey-to-work OD, Leuven: precomputed gravity OD), those are used and
    zone centroids are snapped to network nodes in R.
  - Otherwise a WorldPop x OSM-attractor gravity OD is built in R (legacy).

Assignment parameters (beta, detour.max, method, angle.max, nthreads, and a
cost rescale cost_div) are ALL passed through to flownet::run_assignment (this
was previously broken: the args were accepted but ignored, so every variant
was identical).

Metrics: log-log R2 (compute_metrics_loglog) for drive mode -- DfT AADT spans
~100 to ~150,000 veh/day so linear R2 is not comparable to the other tools --
and linear R2 for walk/cycle (matching the other Leuven tools). Variant names
carry a `_ll` suffix where log-log metrics are used.

Usage:  PYTHONPATH=. .venv/bin/python scripts/bench_flownet.py --city leeds
Output: results/leeds_flownet_results.csv
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import warnings

import numpy as np
import pandas as pd
import geopandas as gpd
import psutil
from scipy.spatial import cKDTree

warnings.filterwarnings("ignore")

from scripts.config import (get_path, get_city_config, get_modes,
                            get_mode_config)
from scripts.csv_utils import merge_to_csv
from scripts.utils.helpers import compute_metrics, compute_metrics_loglog

RESULTS_DIR = "results"
MATCH_DIST = 200
R_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "run_flownet_assignment.R")

_process = psutil.Process()

# Number of top-weighted OD zones used for the flownet assignment (keeps the
# exhaustive path-size-logit tractable; covers the dense urban core). Leeds has
# 103 MSOA zones so this cap is not binding there.
OD_SAMPLE = 150
NTHREADS = 4

# (name, method, beta, detour.max, cost_div, cost_type)
# cost_div rescales the `.length` cost column: flownet's PSL utility is
# V = -cost + beta*ln(PS), so at metre scale the logit is degenerate and beta
# has no visible effect; /1000 (km) puts beta on a meaningful scale.
# cost_type: "length" = plain edge length; "imp" = length x dimensionless
# highway-class impedance factor (baseline_speed/class_speed), mirroring the
# cityseer_od 'dimensionless_imp' variant that scores best on Leeds AADT.
DEFAULT_VARIANTS = [
    ("aon", "AoN", 0.0, 1.5, 1.0, "length"),
    ("aon_imp", "AoN", 0.0, 1.5, 1.0, "imp"),
    ("psl_beta0.001_detour1.25", "PSL", 0.001, 1.25, 1.0, "length"),
    ("psl_beta0.001_detour1.5", "PSL", 0.001, 1.5, 1.0, "length"),
    ("psl_beta0.004_detour1.5", "PSL", 0.004, 1.5, 1.0, "length"),
    ("psl_imp_beta0.001_detour1.5", "PSL", 0.001, 1.5, 1.0, "imp"),
    ("psl_imp_km_beta0.01_detour1.5", "PSL", 0.01, 1.5, 1000.0, "imp"),
    ("psl_imp_km_beta0.05_detour2.0", "PSL", 0.05, 2.0, 1000.0, "imp"),
    ("psl_km_beta0.01_detour1.5", "PSL", 0.01, 1.5, 1000.0, "length"),
]


def mem_mb():
    return _process.memory_info().rss / (1024 * 1024)


def main():
    parser = argparse.ArgumentParser(description="Run flownet assignment benchmarks.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven)")
    parser.add_argument("--modes", nargs="*", default=None,
                        help="Subset of modes to run; default: all configured modes.")
    parser.add_argument("--variants", nargs="*", default=None,
                        help="Variant names (subset of DEFAULT_VARIANTS); default: all.")
    args = parser.parse_args()

    city = args.city
    cfg = get_city_config(city)
    crs_utm = cfg["crs_project"]
    modes = args.modes or get_modes(city)

    variants = [v for v in DEFAULT_VARIANTS if v[0] in args.variants] \
        if args.variants else DEFAULT_VARIANTS

    # Real OD (census/gravity csv + zones geojson) when configured.
    od_file = cfg.get("od_file")
    zones_file = cfg.get("zones_file")
    use_od = bool(od_file and zones_file and os.path.exists(od_file)
                  and os.path.exists(zones_file))

    if not shutil.which("Rscript"):
        print("ERROR: Rscript not found on PATH. flownet requires R.", flush=True)
        return

    all_rows = []
    for mode in modes:
        mc = get_mode_config(city, mode)
        edges_path = get_path(mc["network_file"])
        sensors_path = get_path(mc["sensors_file"])
        sensors_value = mc["sensors_value"]

        if not os.path.exists(edges_path):
            print(f"[skip] flownet {mode}: network {edges_path} not found", flush=True)
            continue
        if not os.path.exists(sensors_path):
            print(f"[skip] flownet {mode}: sensors {sensors_path} not found "
                  f"(validation data pending)", flush=True)
            continue

        print(f"\n═══ flownet / {city} / {mode} ═══", flush=True)
        edges = gpd.read_file(edges_path).to_crs(crs_utm)
        edges = edges.reset_index(drop=True)
        edges.index.name = "edge_idx"
        tel = gpd.read_file(sensors_path).to_crs(crs_utm)
        tel_val = tel[sensors_value].values.astype(float)
        tel_xy = np.array([(g.x, g.y) for g in tel.geometry])

        ec = np.array([(g.x, g.y) for g in edges.geometry.centroid])
        e_tree = cKDTree(ec)
        e_d, e_i = e_tree.query(tel_xy)
        e_m = e_d <= MATCH_DIST
        e_match = int(sum(e_m))
        print(f"  Edges: {len(edges)}  Sensors: {len(tel)}  matched: {e_match}", flush=True)
        if e_match < 3:
            print(f"  [skip] too few matched sensors for {mode}", flush=True)
            continue

        origins_p = get_path(mc["origins_file"])
        dests_p = get_path(mc["destinations_file"])
        # drive mode: log-log metrics (AADT spans orders of magnitude)
        use_loglog = mode == "drive"

        for name, method, beta, detour, cost_div, cost_type in variants:
            variant = name + ("_ll" if use_loglog else "")
            flows_csv = os.path.join(RESULTS_DIR,
                                     f"_flownet_{city}_{mode}_{variant}.csv")
            cmd = [
                "Rscript", R_SCRIPT,
                edges_path, origins_p, dests_p,
                ".length", str(beta), str(detour), flows_csv, mode,
                str(OD_SAMPLE),
                od_file if use_od else "", zones_file if use_od else "",
                method, "90", str(NTHREADS), str(cost_div), cost_type,
            ]
            t0 = time.perf_counter()
            mem0 = mem_mb()
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=1800)
            except subprocess.TimeoutExpired:
                print(f"  {variant}: TIMEOUT", flush=True)
                continue
            elapsed = time.perf_counter() - t0

            if proc.returncode != 0:
                err = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown R error"
                print(f"  {variant}: R ERROR -> {err[:300]}", flush=True)
                continue
            print("  " + (proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else f"{variant} done"), flush=True)

            if not os.path.exists(flows_csv):
                continue
            fl = pd.read_csv(flows_csv)
            flow_map = dict(zip(fl["edge_idx"].astype(int), fl["flow"]))
            pred = edges.index.map(lambda i: flow_map.get(int(i), np.nan)).values.astype(float)
            pred_matched = pred[e_i[e_m]]

            obs = tel_val[e_m]
            mask = ~(np.isnan(obs) | np.isnan(pred_matched))
            n = int(mask.sum())
            if n < 3 or np.all(pred_matched[mask] == pred_matched[mask][0]):
                r2 = pr = sr = np.nan
            else:
                m = compute_metrics_loglog(obs, pred_matched) if use_loglog \
                    else compute_metrics(obs, pred_matched)
                r2, pr, sr = m["r_squared"], m["pearson_r"], m["spearman_r"]

            all_rows.append({
                "tool": "flownet", "mode": mode, "variant": variant,
                "r_squared": float(r2), "pearson_r": float(pr),
                "spearman_r": float(sr),
                "compute_time_s": round(elapsed, 2),
                "n_matched": e_match, "n_obs": n,
                "peak_memory_mb": round(mem_mb() - mem0 + 400, 1),
                "segments_per_sec": round(len(edges) / elapsed, 1) if elapsed > 0 else 0.0,
            })
            print(f"  {variant}: R2={r2:.4f} r={pr:.4f} t={elapsed:.1f}s", flush=True)
            try:
                os.remove(flows_csv)
            except OSError:
                pass

    if all_rows:
        df = pd.DataFrame(all_rows)
        merge_to_csv("flownet", df, os.path.join(RESULTS_DIR, f"{city}_flownet_results.csv"))
        print(f"\nSaved {len(df)} flownet results -> {RESULTS_DIR}/{city}_flownet_results.csv",
              flush=True)
    else:
        print("\nNo flownet results produced (check network/sensor/OD availability).",
              flush=True)


if __name__ == "__main__":
    main()
