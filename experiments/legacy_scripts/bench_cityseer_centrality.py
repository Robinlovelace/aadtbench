#!/usr/bin/env python3
"""
cityseer structural-centrality benchmark extension: betweenness_shortest
(distance & beta sweeps), segment_centrality (edge-based), node_centrality
(simplest/shortest heuristics) -- validated against ground-truth counts.

Extends the classic centrality benchmark (scripts/bench_centrality.py) with
the cityseer 4.24.1 API surface that was previously unexplored. Writes into
the same results/{city}_centrality_results.csv file (merge_to_csv on the
"cityseer" tool name) so merge_all.py picks the rows up unchanged.

Metrics: log-log R2 (compute_metrics_loglog) for drive mode (DfT AADT spans
~100 to ~150,000 veh/day; the classic centrality rows used linear R2, which
is not comparable). Variant names carry a `_ll` suffix where log-log metrics
are used.

Usage:  PYTHONPATH=. .venv/bin/python scripts/bench_cityseer_centrality.py --city leeds
Output: results/leeds_centrality_results.csv (cityseer rows replaced)
"""
import argparse
import os
import time
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import psutil
from scipy.spatial import cKDTree

warnings.filterwarnings("ignore")

from cityseer.metrics import networks as cs_networks

from scripts.config import get_path, get_city_config, get_mode_config
from scripts.csv_utils import merge_to_csv
from scripts.utils.helpers import compute_metrics, compute_metrics_loglog
from scripts.bench_cityseer_od import build_network_structure

RESULTS_DIR = "results"
MATCH_DIST = 200.0
_process = psutil.Process()

# (variant, kind, imp, params) where kind in {shortest, simplest, segment}
# params is a dict of kwargs for the cityseer call.
VARIANTS = [
    # ── betweenness_shortest: distance sweeps (plain + dimensionless_imp) ──
    ("bs_dist400_plain", "shortest", False, {"distances": [400]}),
    ("bs_dist1600_plain", "shortest", False, {"distances": [1600]}),
    ("bs_dist8000_plain", "shortest", False, {"distances": [8000]}),
    ("bs_dist20000_plain", "shortest", False, {"distances": [20000]}),
    ("bs_dist20000_dimimp", "shortest", True, {"distances": [20000]}),
    # ── betweenness_shortest: distance-decay beta sweeps (plain) ──
    ("bs_beta0.001_plain", "shortest", False, {"betas": [0.001]}),
    ("bs_beta0.002_plain", "shortest", False, {"betas": [0.002]}),
    ("bs_beta0.004_plain", "shortest", False, {"betas": [0.004]}),
    # ── segment_centrality (edge-based): may match AADT better ──
    ("seg_dist800_plain", "segment", False, {"distances": [800]}),
    ("seg_dist3200_plain", "segment", False, {"distances": [3200]}),
    ("seg_dist8000_plain", "segment", False, {"distances": [8000]}),
    ("seg_dist20000_plain", "segment", False, {"distances": [20000]}),
    ("seg_dist20000_dimimp", "segment", True, {"distances": [20000]}),
    # NOTE: node_centrality_simplest (topological) variants are intentionally
    # omitted: cityseer raises ValueError("node_centrality_simplest requires a
    # dual graph for angular analysis") on the primal network, and building a
    # dual graph for Leeds (64k edges) is 20-30x slower than the primal build
    # for a heuristic that is unlikely to match AADT better than the
    # betweenness/segment variants already covered.
]


def mem_mb():
    return _process.memory_info().rss / (1024 * 1024)


def main():
    parser = argparse.ArgumentParser(description="cityseer structural centrality benchmark.")
    parser.add_argument("--city", default="leeds", help="City name (e.g. leeds)")
    parser.add_argument("--modes", nargs="*", default=None, help="Subset of modes; default: drive")
    parser.add_argument("--variants", nargs="*", default=None,
                        help="Variant names to run (subset); default: all.")
    args = parser.parse_args()

    city = args.city
    cfg = get_city_config(city)
    crs_project = cfg["crs_project"]
    modes = args.modes or ["drive"]
    variants = [v for v in VARIANTS if v[0] in args.variants] if args.variants else VARIANTS

    for mode in modes:
        mc = get_mode_config(city, mode)
        sensors_file = get_path(mc["sensors_file"])
        edges_file = get_path(mc["network_file"])
        sensors_value = mc.get("sensors_value")
        if not os.path.exists(sensors_file):
            print(f"[skip] centrality {mode}: sensors {sensors_file} not found", flush=True)
            continue

        print(f"=== cityseer centrality / {city} / {mode} ===", flush=True)
        sensors = gpd.read_file(sensors_file).to_crs(crs_project)
        sens_xy = np.array([(g.x, g.y) for g in sensors.geometry])
        sens_val = sensors[sensors_value].values.astype(float)

        edges = gpd.read_file(edges_file).to_crs(crs_project)
        edges = edges[edges["reversed"].astype(str) != "True"].reset_index(drop=True)
        edges["baseline_speed_ms"] = float(mc["travel_speed"])
        print(f"  Network (deduplicated, primal): {len(edges)} edges", flush=True)

        use_loglog = mode == "drive"

        variants_net = {}
        for imp_name, use_imp in [("plain", False), ("dimensionless_imp", True)]:
            t0 = time.time()
            nodes_df, edges_df, net_struct = build_network_structure(edges, use_imp)
            print(f"  Built '{imp_name}' NetworkStructure: {len(nodes_df)} nodes, "
                  f"{len(edges_df)} edges ({time.time()-t0:.1f}s)", flush=True)
            variants_net[imp_name] = (nodes_df, edges_df, net_struct)

        # Sensor <-> node matching (node-based, same convention as bench_centrality.py)
        matched = {}
        for imp_name, (nodes_df, edges_df, net_struct) in variants_net.items():
            node_xy = np.array([(nodes_df.loc[k, "x"], nodes_df.loc[k, "y"]) for k in nodes_df.index])
            tree = cKDTree(node_xy)
            d, i = tree.query(sens_xy)
            m = d <= MATCH_DIST
            matched[imp_name] = (node_xy, i, m)
            print(f"  '{imp_name}': matched {int(m.sum())}/{len(sensors)} sensors to nodes", flush=True)

        results = []

        def run_variant(name, kind, imp_name, params):
            nodes_df, edges_df, net_struct = variants_net[imp_name]
            node_xy, sens_i, sens_m = matched[imp_name]
            if sens_m.sum() < 3:
                return
            t0 = time.time()
            mem0 = mem_mb()
            if kind == "shortest":
                res = cs_networks.betweenness_shortest(
                    network_structure=net_struct, nodes_gdf=nodes_df.copy(), **params)
                col = None
            elif kind == "segment":
                res = cs_networks.segment_centrality(
                    network_structure=net_struct, nodes_gdf=nodes_df.copy(), **params)
                col = None
            else:  # nc_simplest
                res = cs_networks.node_centrality_simplest(
                    network_structure=net_struct, nodes_gdf=nodes_df.copy(), **params)
                col = None
            elapsed = time.time() - t0

            # pick the betweenness column (first matching measure key)
            bcols = [c for c in res.columns if "betweenness" in c.lower()]
            if not bcols:
                print(f"  {name}: no betweenness column in result ({list(res.columns)[:5]})", flush=True)
                return
            col = bcols[0]
            # map node values -> edge midpoint values (avg of endpoint nodes)
            edges_df2 = edges_df.copy()
            edges_df2["cent"] = (
                res.loc[edges_df2["nx_start_node_key"], col].values
                + res.loc[edges_df2["nx_end_node_key"], col].values
            ) / 2.0
            pred = edges_df2.iloc[sens_i[sens_m]]["cent"].values.astype(float)
            m = compute_metrics_loglog(sens_val[sens_m], pred) if use_loglog \
                else compute_metrics(sens_val[sens_m], pred)
            peak_mem = max(mem_mb(), mem0)
            row = {
                "tool": "cityseer", "mode": mode, "variant": name + ("_ll" if use_loglog else ""),
                "r_squared": m["r_squared"], "pearson_r": m["pearson_r"], "spearman_r": m["spearman_r"],
                "compute_time_s": round(elapsed, 2), "n_matched": int(sens_m.sum()), "n_obs": m["n"],
                "peak_memory_mb": round(peak_mem, 1),
                "segments_per_sec": round(len(edges_df2) / elapsed, 1) if elapsed > 0 else 0.0,
            }
            results.append(row)
            r2s = f"{m['r_squared']:.4f}" if not np.isnan(m["r_squared"]) else "nan"
            print(f"  {row['variant']}: log-log R2={r2s} n={m['n']} t={elapsed:.1f}s", flush=True)

        for name, kind, use_imp, params in variants:
            imp_name = "dimensionless_imp" if use_imp else "plain"
            run_variant(name, kind, imp_name, params)

        if results:
            df = pd.DataFrame(results)
            out_path = os.path.join(RESULTS_DIR, f"{city}_centrality_results.csv")
            merge_to_csv("cityseer", df, out_path)
            best = df.loc[df["r_squared"].idxmax()]
            print(f"\n  BEST cityseer centrality: {best['variant']}  R2={best['r_squared']:.4f}  "
                  f"t={best['compute_time_s']:.1f}s", flush=True)
            print(f"  Saved {len(df)} variants -> {out_path}", flush=True)
        else:
            print("  No cityseer centrality results produced.", flush=True)


if __name__ == "__main__":
    main()
