#!/usr/bin/env python3
"""
Run different madina demand estimation sensitivity experiments on a city using subprocesses for timeout safety.
"""
import os
import sys
import time
import argparse
import subprocess
import json
import numpy as np
import pandas as pd
import geopandas as gpd

from scripts.config import get_path, get_city_config, get_modes, get_mode_config
from scripts.csv_utils import merge_to_csv

RESULTS_DIR = "results"
MAX_RUNTIME = 75 # 1.25 minutes timeout per experiment

def main():
    parser = argparse.ArgumentParser(description="Run demand estimation sensitivity experiments using subprocesses.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven)")
    parser.add_argument("--modes", nargs="*", default=None,
                        help="Subset of modes to run; default: all configured modes.")
    args = parser.parse_args()
    
    city = args.city
    cfg = get_city_config(city)
    modes = args.modes or get_modes(city)
    
    for mode in modes:
        mc = get_mode_config(city, mode)
        sensors_file = get_path(mc["sensors_file"])
        sensors_value = mc.get("sensors_value", "avg_daily_pedestrians")
        results_file = os.path.join(RESULTS_DIR, f"{city}_madina_worldpop_results.csv")
        if not os.path.exists(sensors_file):
            print(f"[skip] madina_worldpop {mode}: sensors {sensors_file} not found (validation pending)", flush=True)
            continue

        # Load sensors to count total observations for timeout fallback
        telr = gpd.read_file(sensors_file)
        num_sensors = len(telr)

        experiments = [
            {"name": "wp_r800_beta002_all",   "search_radius": 800,  "detour_ratio": 1.0, "closest_destination": False, "decay": True, "beta": 0.002},
            {"name": "wp_r1200_beta002_all",  "search_radius": 1200, "detour_ratio": 1.0, "closest_destination": False, "decay": True, "beta": 0.002},
            {"name": "wp_r1600_beta002_all",  "search_radius": 1600, "detour_ratio": 1.0, "closest_destination": False, "decay": True, "beta": 0.002},
            {"name": "wp_r2000_beta002_all",  "search_radius": 2000, "detour_ratio": 1.0, "closest_destination": False, "decay": True, "beta": 0.002},
            {"name": "wp_r1200_beta001_all",  "search_radius": 1200, "detour_ratio": 1.0, "closest_destination": False, "decay": True, "beta": 0.001},
            {"name": "wp_r1600_beta001_all",  "search_radius": 1600, "detour_ratio": 1.0, "closest_destination": False, "decay": True, "beta": 0.001},
            {"name": "wp_r2000_beta002_closest", "search_radius": 2000, "detour_ratio": 1.0, "closest_destination": True,  "decay": True, "beta": 0.002},
            {"name": "wp_r1200_beta002_nodecay", "search_radius": 1200, "detour_ratio": 1.0, "closest_destination": False, "decay": False, "beta": 0.002},
            {"name": "wp_r3000_beta002_all",  "search_radius": 3000, "detour_ratio": 1.0, "closest_destination": False, "decay": True, "beta": 0.002},
        ]
        
        new_results = []
        print(f"\n═══ madina_worldpop / {mode} ═══", flush=True)
        
        for exp in experiments:
            cmd = [
                sys.executable, "scripts/run_single_experiment.py",
                "--city", city,
                "--mode", mode,
                "--name", exp["name"],
                "--search-radius", str(exp["search_radius"]),
                "--detour-ratio", str(exp["detour_ratio"]),
                "--beta", str(exp["beta"])
            ]
            if exp["closest_destination"]:
                cmd.append("--closest-destination")
            if exp["decay"]:
                cmd.append("--decay")

            print(f"Running variant: {exp['name']} (Radius={exp['search_radius']}, Detour={exp['detour_ratio']}, Closest={exp['closest_destination']}, Decay={exp['decay']}, Beta={exp['beta']})")

            t0 = time.time()
            try:
                env = os.environ.copy()
                env["PYTHONPATH"] = "."
                proc = subprocess.run(
                    cmd,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=MAX_RUNTIME
                )
                elapsed = time.time() - t0

                if proc.returncode != 0:
                    print(f"  Process failed with return code {proc.returncode}")
                    print(proc.stderr)
                    res = None
                else:
                    res = None
                    for line in proc.stdout.splitlines():
                        if line.startswith("RESULT_JSON:"):
                            res = json.loads(line[len("RESULT_JSON:"):])
                            break
            except subprocess.TimeoutExpired:
                elapsed = time.time() - t0
                print(f"  Variant {exp['name']} timed out after {elapsed:.1f}s (threshold: {MAX_RUNTIME}s).")
                res = {
                    "tool": "madina_worldpop",
                    "variant": exp["name"],
                    "r_squared": np.nan,
                    "pearson_r": np.nan,
                    "spearman_r": np.nan,
                    "compute_time_s": round(elapsed, 2),
                    "n_matched": num_sensors,
                    "n_obs": num_sensors,
                    "peak_memory_mb": np.nan,
                    "segments_per_sec": np.nan
                }

            if res:
                new_results.append(res)
                print(f"  Result: R²={res['r_squared']:.4f}, Pearson r={res['pearson_r']:.4f}, Spearman r={res['spearman_r']:.4f}, Matched={res['n_matched']}, Time={res['compute_time_s']:.1f}s")
            else:
                new_results.append({
                    "tool": "madina_worldpop",
                    "variant": exp["name"],
                    "r_squared": np.nan,
                    "pearson_r": np.nan,
                    "spearman_r": np.nan,
                    "compute_time_s": round(elapsed, 2),
                    "n_matched": num_sensors,
                    "n_obs": num_sensors,
                    "peak_memory_mb": np.nan,
                    "segments_per_sec": np.nan
                })

    df_new = pd.DataFrame(new_results)
    merge_to_csv("madina_worldpop", df_new, results_file)
    print(f"\nSaved {len(df_new)} results to {results_file}")
    
    if df_new["r_squared"].notna().any():
        best_idx = df_new["r_squared"].idxmax()
        best_row = df_new.loc[best_idx]
        print("\n" + "="*50)
        print("BEST EXPERIMENT RESULTS:")
        print("="*50)
        print(f"Variant: {best_row['variant']}")
        print(f"R-squared: {best_row['r_squared']:.6f}")
        print(f"Pearson r: {best_row['pearson_r']:.6f}")
        print(f"Spearman r: {best_row['spearman_r']:.6f}")
        print(f"Matched: {best_row['n_matched']}")
        print("="*50 + "\n")
    else:
        print("\n" + "="*50)
        print("NO VALID R-SQUARED RESULTS (ALL EXPERIMENTS TIMED OUT OR RETURNED NA)")
        print("="*50 + "\n")

if __name__ == "__main__":
    main()
