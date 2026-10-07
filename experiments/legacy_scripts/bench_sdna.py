#!/usr/bin/env python3
"""
sDNA+ Pedestrian Flow Benchmark.
Runs sDNA+ integrality/centrality on the walk network and
validates against Telraam pedestrian counts.

Installation: pipx install sdna_plus
Then re-run this script.

Usage: python scripts/bench_sdna.py --city leuven
Output: results/sdna_results.csv
"""
import os, sys, time, warnings, subprocess, tempfile, shutil, argparse
import numpy as np
import pandas as pd
import geopandas as gpd
import psutil
from scipy import stats
from scipy.spatial import cKDTree
warnings.filterwarnings("ignore")

from scripts.config import get_path, get_city_config, get_modes, get_mode_config
from scripts.csv_utils import merge_to_csv

_process = psutil.Process()
DATA_DIR = "data"; RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)
MATCH_DIST = 200
RADII = [100, 200, 400, 800]


def metrics(y, p):
    m = ~(np.isnan(y) | np.isnan(p)); n_m = int(sum(m))
    if n_m < 3 or np.all(p[m] == p[m][0]):
        return {"r_squared": np.nan, "pearson_r": np.nan, "spearman_r": np.nan, "n_matched": n_m}
    yt, yp = y[m], p[m]
    rv = stats.linregress(yp, yt).rvalue ** 2
    pr, _ = stats.pearsonr(yp, yt); sr, _ = stats.spearmanr(yp, yt)
    return {"r_squared": rv, "pearson_r": pr, "spearman_r": sr, "n_matched": n_m}


def compute_memory():
    return _process.memory_info().rss / (1024 * 1024)


def check_sdna():
    try:
        r = subprocess.run(["sdnaintegral"], capture_output=True, text=True, timeout=5)
        return True
    except FileNotFoundError:
        pass
    venv_sdna = os.path.join(os.path.dirname(sys.executable), "sdnaintegral")
    if os.path.exists(venv_sdna):
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="Run sDNA+ centrality benchmarks.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven)")
    parser.add_argument("--modes", nargs="*", default=None,
                        help="Subset of modes to run; default: all configured modes.")
    args = parser.parse_args()

    city = args.city
    cfg = get_city_config(city)
    crs_utm = cfg["crs_project"]
    modes = args.modes or get_modes(city)

    all_results = []
    for mode in modes:
        mc = get_mode_config(city, mode)
        edges_path = get_path(mc["network_file"])
        sensors_path = get_path(mc["sensors_file"])
        sensors_value = mc.get("sensors_value", "avg_daily_pedestrians")

        if not os.path.exists(edges_path):
            print(f"[skip] sDNA {mode}: network {edges_path} not found", flush=True)
            continue
        if not os.path.exists(sensors_path):
            print(f"[skip] sDNA {mode}: sensors {sensors_path} not found (validation pending)", flush=True)
            continue

        print(f"\n═══ sDNA+ / {mode} ═══", flush=True)

        # ── Sensors ──
        tel = gpd.read_file(sensors_path).to_crs(crs_utm)
        tel_xy = np.array([(g.x, g.y) for g in tel.geometry])
        tel_ped = tel[sensors_value].values.astype(float)
        print(f"Sensors: {len(tel)}", flush=True)

        # ── Network ──
        edges = gpd.read_file(edges_path)
        edges_u = edges.to_crs(crs_utm)
        edges_u["id"] = range(len(edges_u))
        print(f"Edges: {len(edges_u)}", flush=True)

        # ── Edge midpoint tree for sensor matching ──
        ec = np.array([(g.x, g.y) for g in edges_u.geometry.centroid])
        e_tree = cKDTree(ec); e_d, e_i = e_tree.query(tel_xy); e_match = e_d <= MATCH_DIST
        e_match_count = int(e_match.sum())
        print(f"Edge-matched sensors: {e_match_count}", flush=True)

        sdna_bin = "sdnaintegral"
        if not check_sdna():
            venv_sdna = os.path.join(os.path.dirname(sys.executable), "sdnaintegral")
            if os.path.exists(venv_sdna):
                sdna_bin = venv_sdna
            else:
                print("⚠  sDNA+ not available. Install: pipx install sdna_plus", flush=True)
                merge_to_csv("sdna", pd.DataFrame([{
                    "tool": "sdna", "mode": mode, "variant": "not_available",
                    "r_squared": None, "pearson_r": None, "spearman_r": None,
                    "compute_time_s": None, "n_matched": None,
                    "peak_memory_mb": None, "segments_per_sec": None,
                    "notes": "Install sDNA+: pipx install sdna_plus"
                }]), f"{RESULTS_DIR}/{city}_sdna_results.csv")
                sys.exit(0)

        print(f"sDNA+ binary: {sdna_bin}", flush=True)

        workdir = tempfile.mkdtemp(prefix="sdna_bench_")

        try:
            net_shp = os.path.join(workdir, f"{city}_{mode}_walk.shp")
            edges_out = edges_u[["id", "geometry"]].copy()
            edges_out["length"] = edges_out.geometry.length
            edges_out.to_file(net_shp)
            print(f"Exported {len(edges_out)} edges to shapefile", flush=True)

            # Run sDNA once per metric, passing all radii as comma-separated list.
            # ANGULAR with nobetweenness: MAD + NQPDA (closeness) are ~3× faster.
            # EUCLIDEAN without nobetweenness: MED + NQPDE + MCF + BtE + DivE.
            runs = [
                ("ANGULAR", f"radii={','.join(str(r) for r in RADII)};metric=ANGULAR;nohull;nobetweenness"),
                ("EUCLIDEAN", f"radii={','.join(str(r) for r in RADII)};metric=EUCLIDEAN;nohull"),
            ]

            # Per-metric column prefixes
            METRIC_PREFIXES = {
                "ANGULAR": ["MAD", "NQPDA", "MCF", "DivA"],
                "EUCLIDEAN": ["MED", "NQPDE", "MCF", "DivE", "BtE"],
            }

            for metric_label, config_str in runs:
                label_lower = metric_label.lower()
                print(f"\n── sDNA {metric_label} radii={RADII} ──", flush=True)
                out_shp = os.path.join(workdir, f"sdna_{mode}_{label_lower}.shp")

                mem_before = compute_memory()
                t0 = time.perf_counter()

                r = subprocess.run(
                    [sdna_bin, "-i", net_shp, "-o", out_shp, config_str],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600
                )

                elapsed = time.perf_counter() - t0
                mem_peak = compute_memory() - mem_before + 400

                if r.returncode != 0:
                    print(f"  sDNA failed (return code {r.returncode})", flush=True)
                    continue

                if not os.path.exists(out_shp):
                    print(f"  No output shapefile created", flush=True)
                    continue

                sdna_out = gpd.read_file(out_shp)

                # Parse all metric×radius columns from the output
                # sDNA appends the numeric radius to each metric name (e.g. MAD200, NQPDA400)
                prefixes = METRIC_PREFIXES[metric_label]
                for col in sdna_out.columns:
                    for prefix in prefixes:
                        if col.startswith(prefix):
                            radius_str = col[len(prefix):]
                            try:
                                radius_val = int(radius_str)
                            except ValueError:
                                continue
                            if radius_val not in RADII:
                                continue

                            variant_name = f"{prefix}_{label_lower}_{radius_val}m"
                            vals = sdna_out.iloc[e_i[e_match]][col].values.astype(float)
                            m = metrics(tel_ped[e_match], vals)
                            result = {
                                "tool": "sdna", "mode": mode,
                                "variant": variant_name,
                                "r_squared": m["r_squared"],
                                "pearson_r": m["pearson_r"],
                                "spearman_r": m["spearman_r"],
                                "compute_time_s": round(elapsed, 2),
                                "n_matched": m["n_matched"],
                                "peak_memory_mb": round(mem_peak, 1),
                                "segments_per_sec": round(len(edges_u)/elapsed, 1) if elapsed > 0 else 0,
                            }
                            all_results.append(result)

                            # Save best predictions (closeness at 400m angular)
                            if label_lower == "angular" and prefix == "MAD" and radius_val == 400:
                                pd.DataFrame({
                                    "observed": tel_ped[e_match],
                                    "predicted": vals
                                }).to_csv(f"{RESULTS_DIR}/{city}_sdna_best_predictions.csv", index=False)

                print(f"  Time: {elapsed:.1f}s", flush=True)

        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    df = pd.DataFrame(all_results)
    out_path = f"{RESULTS_DIR}/{city}_sdna_results.csv"
    merge_to_csv("sdna", df, out_path)
    print(f"\n── RESULTS ({len(df)} variants) ──", flush=True)
    for _, r in df.iterrows():
        r2 = f"{r['r_squared']:.4f}" if not pd.isna(r.get("r_squared")) else "nan"
        pr = f"{r['pearson_r']:.4f}" if not pd.isna(r.get("pearson_r")) else "nan"
        print(f"  {r['tool']} {r.get('mode','walk')} {r['variant']}: R²={r2} r={pr} time={r['compute_time_s']:.1f}s", flush=True)
    print(f"Saved to {out_path}", flush=True)


if __name__ == "__main__":
    main()
