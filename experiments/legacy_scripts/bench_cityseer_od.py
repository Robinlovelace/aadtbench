#!/usr/bin/env python3
"""
cityseer OD-betweenness benchmark for Leeds/West Yorkshire, validated against
real DfT AADT counts (drive mode) using real 2011 Census journey-to-work
(car_driver) OD flows from `pct::get_od()` / `pct::get_pct_zones(msoa)`.

Implements the findings from the sibling criticalissues project (see
/tmp/leeds_bench_task.md):
  - imp_factor is a DIMENSIONLESS cost multiplier (~1.0 at free-flow speed),
    never raw seconds -- tested as a variant against plain length-based cost.
  - `tolerance` (multi-predecessor DAG dispersal) swept on/off (0 vs ~3%),
    not fine-tuned as a continuous dial (it saturates almost immediately).
  - zone-injection dispersion: K=5 randomly-dispersed points per zone
    polygon vs a single centroid -- the single biggest lever found.
  - full network + full OD matrix (West Yorkshire-wide), not a clipped bbox.
  - primal graph (dual is 20-30x slower to build for a first look).
  - log-log R^2 vs real ground truth (DfT AADT spans ~100 to ~150,000
    veh/day), not rank correlation, not another tool's output.

Usage:  PYTHONPATH=. .venv/bin/python scripts/bench_cityseer_od.py --city leeds
Output: results/leeds_cityseer_od_results.csv
"""
import argparse
import os
import time
import warnings

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import psutil
from scipy.spatial import cKDTree
from shapely.geometry import Point

warnings.filterwarnings("ignore")

from cityseer.tools import io
from cityseer.metrics import networks as cs_networks

from scripts.config import get_path, get_city_config, get_mode_config
from scripts.csv_utils import merge_to_csv
from scripts.utils.edge_weights import apply_formula, formula_suffix
from scripts.utils.helpers import compute_metrics_loglog

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)
MATCH_DIST = 200.0
MAX_SNAP_DIST = 500.0
_process = psutil.Process()

# Free-flow mph by OSM highway class, used only to build a *dimensionless*
# imp_factor (class speed relative to the mode's uniform baseline speed) --
# never raw seconds, per the units-bug finding.
CLASS_MPH = {
    "motorway": 65, "motorway_link": 40, "trunk": 55, "trunk_link": 35,
    "primary": 35, "primary_link": 25, "secondary": 30, "secondary_link": 25,
    "tertiary": 25, "tertiary_link": 20, "unclassified": 22,
    "residential": 18, "living_street": 10,
}
DEFAULT_MPH = 20
MPH_TO_MS = 0.44704


def first_class(highway):
    if isinstance(highway, list):
        return highway[0] if highway else "unclassified"
    s = str(highway)
    if s.startswith("["):
        s = s.strip("[]").split(",")[0].strip().strip("'\"")
    return s


def sample_points_in_polygon(poly, k, rng, max_tries=200):
    minx, miny, maxx, maxy = poly.bounds
    pts = []
    tries = 0
    while len(pts) < k and tries < max_tries:
        x = rng.uniform(minx, maxx)
        y = rng.uniform(miny, maxy)
        p = Point(x, y)
        if poly.contains(p):
            pts.append(p)
        tries += 1
    while len(pts) < k:
        pts.append(poly.centroid)
    return pts


def mem_mb():
    return _process.memory_info().rss / (1024 * 1024)


def build_network_structure(edges_u, use_imp_factor=False, imp_values=None):
    """Build a cityseer primal NetworkStructure from deduplicated directed
    edges. use_imp_factor=True bakes in a dimensionless highway-class speed
    multiplier; False leaves imp_factor at cityseer's default of 1.0
    (plain length-based routing). imp_values (optional) overrides both: an
    explicit per-edge imp_factor array (e.g. weight/length from the portable
    edge-weight registry), so any formula's weight becomes the routing cost."""
    G = nx.MultiGraph()
    for i, row in enumerate(edges_u.itertuples()):
        u, v = str(int(row.u)), str(int(row.v))
        c = list(row.geometry.coords)
        if u not in G:
            G.add_node(u, x=c[0][0], y=c[0][1])
        if v not in G:
            G.add_node(v, x=c[-1][0], y=c[-1][1])
        edge_kwargs = {"geom": row.geometry, "length": row.geometry.length}
        if imp_values is not None:
            edge_kwargs["imp_factor"] = float(imp_values[i])
        elif use_imp_factor:
            cls = first_class(row.highway)
            mph = CLASS_MPH.get(cls, DEFAULT_MPH)
            class_speed_ms = mph * MPH_TO_MS
            edge_kwargs["imp_factor"] = float(row["baseline_speed_ms"] / class_speed_ms)
        G.add_edge(u, v, **edge_kwargs)
    G.graph["crs"] = edges_u.crs.to_epsg()
    nodes_df, edges_df, net_struct = io.network_structure_from_nx(G)
    deg = dict(G.degree())
    edges_df["is_stub"] = (
        edges_df["nx_start_node_key"].map(lambda x: deg.get(x, 0) <= 1)
        | edges_df["nx_end_node_key"].map(lambda x: deg.get(x, 0) <= 1)
        | (edges_df.geometry.length < 15.0)
    )
    return nodes_df, edges_df, net_struct


def main():
    parser = argparse.ArgumentParser(description="cityseer OD-betweenness benchmark.")
    parser.add_argument("--city", default="leeds", help="City name (e.g. leeds)")
    parser.add_argument("--modes", nargs="*", default=None, help="Subset of modes; default: drive")
    parser.add_argument("--k-dispersion", type=int, nargs="*", default=[3, 5, 10],
                         help="Points per zone to sweep for the dispersed injection variant")
    parser.add_argument("--weight", default=None,
                         help="Edge-weight formula from scripts/utils/edge_weights.py "
                              "(e.g. length, time_freeflow, time_imp_dimless). When set, "
                              "imp_factor = weight/length so cityseer routes on that weight, "
                              "and a full disp x tolerance x distance grid is run.")
    parser.add_argument("--distances", type=float, nargs="*", default=[2000.0, 10000.0],
                         help="Distances (radii, m) for the grid when --weight is set")
    parser.add_argument("--tolerances", type=float, nargs="*", default=[0.0, 0.1],
                         help="DAG dispersal tolerances to sweep")
    args = parser.parse_args()

    city = args.city
    cfg = get_city_config(city)
    crs_project = cfg["crs_project"]
    od_file = cfg.get("od_file")
    zones_file = cfg.get("zones_file")
    if not od_file or not os.path.exists(od_file) or not os.path.exists(zones_file):
        print(f"[skip] cityseer_od: od_file/zones_file not configured or missing for {city}")
        return

    modes = args.modes or ["drive"]
    K_VALUES = args.k_dispersion
    K_MAX = max(K_VALUES)
    rng = np.random.RandomState(42)

    od_df = pd.read_csv(od_file)
    zones = gpd.read_file(zones_file).to_crs(crs_project)
    zones = zones.set_index("geo_code")

    for mode in modes:
        mc = get_mode_config(city, mode)
        sensors_file = get_path(mc["sensors_file"])
        edges_file = get_path(mc["network_file"])
        sensors_value = mc.get("sensors_value")
        if not os.path.exists(sensors_file):
            print(f"[skip] cityseer_od {mode}: sensors {sensors_file} not found (validation pending)")
            continue

        print(f"=== cityseer OD / {city} / {mode} ===", flush=True)
        sensors = gpd.read_file(sensors_file).to_crs(crs_project)
        sens_xy = np.array([(g.x, g.y) for g in sensors.geometry])
        sens_val = sensors[sensors_value].values.astype(float)

        edges = gpd.read_file(edges_file).to_crs(crs_project)
        edges = edges[edges["reversed"].astype(str) != "True"].reset_index(drop=True)
        edges["baseline_speed_ms"] = float(mc["travel_speed"])
        print(f"  Network (deduplicated, primal): {len(edges)} edges", flush=True)

        # OD demand: car_driver flows between zones present in both od+zones
        weight_col = "car_driver" if "car_driver" in od_df.columns else "all"
        od = od_df[(od_df["geo_code1"].isin(zones.index)) & (od_df["geo_code2"].isin(zones.index)) & (od_df[weight_col] > 0)]
        print(f"  OD pairs (both zones matched, {weight_col}>0): {len(od)}  total flow={od[weight_col].sum():.0f}", flush=True)

        # Build the network structure(s): with --weight, ONE structure whose
        # imp_factor = weight/length (so cityseer's cost == the registry
        # formula's weight); without, the plain vs dimensionless_imp pair.
        variants_net = {}
        if args.weight:
            wt_label = f"wt{formula_suffix(args.weight)}"
            t0 = time.time()
            length = np.asarray(edges.geometry.length.values, dtype=float)
            wt = apply_formula(edges, args.weight, speed_ms=float(mc["travel_speed"]))
            imp = np.where(length > 0, wt / np.where(length > 0, length, 1.0), 1.0)
            nodes_df, edges_df, net_struct = build_network_structure(edges, imp_values=imp)
            print(f"  Built '{wt_label}' NetworkStructure ({args.weight}): "
                  f"{len(nodes_df)} nodes, {len(edges_df)} edges "
                  f"({time.time()-t0:.1f}s)", flush=True)
            variants_net[wt_label] = (nodes_df, edges_df, net_struct)
        else:
            for imp_name, use_imp in [("plain", False), ("dimensionless_imp", True)]:
                t0 = time.time()
                nodes_df, edges_df, net_struct = build_network_structure(edges, use_imp)
                print(f"  Built '{imp_name}' NetworkStructure: {len(nodes_df)} nodes, {len(edges_df)} edges "
                      f"({time.time()-t0:.1f}s)", flush=True)
                variants_net[imp_name] = (nodes_df, edges_df, net_struct)

        # Sensor <-> edge matching (shared across variants: same non-stub edge set/order per imp variant).
        matched = {}
        for imp_name, (nodes_df, edges_df, net_struct) in variants_net.items():
            non_stub = edges_df[~edges_df["is_stub"]].copy()
            centroids_xy = np.array([(g.x, g.y) for g in non_stub.geometry.centroid])
            tree = cKDTree(centroids_xy)
            d, i = tree.query(sens_xy)
            m = d <= MATCH_DIST
            matched[imp_name] = (non_stub, i, m)
            print(f"  '{imp_name}': matched {int(m.sum())}/{len(sensors)} sensors to non-stub edges", flush=True)

        # Node-snapping tree shared across imp variants -- node ids/coords are
        # identical regardless of imp_factor (only edge cost differs).
        # OdMatrix takes POSITIONAL integer node indices (matching the order of
        # network_structure.node_xys), not the original nx string node keys --
        # nodes_df.index order is verified 1:1 positional with node_xys, so the
        # cKDTree query result `i` (an array position) is itself the id to use.
        # (With --weight there is a single "wt{formula}" structure; without it
        # the first of plain/dimensionless_imp is used -- nodes are the same.)
        first_net = next(iter(variants_net.values()))
        nodes_df0 = first_net[0]
        node_xy = np.array([(nodes_df0.loc[k, "x"], nodes_df0.loc[k, "y"]) for k in nodes_df0.index])
        node_tree = cKDTree(node_xy)

        def snap(points):
            xy = np.array([(p.x, p.y) for p in points])
            d, i = node_tree.query(xy)
            return i.astype(int), d

        # ── Zone injection points: centroid (1) vs dispersed (K, swept) ──
        # Sample K_MAX points per zone once; smaller K variants just use a
        # prefix of that same sample so the K sweep is nested/comparable.
        print(f"  Building zone injection points (centroid vs K={K_VALUES} dispersed)...", flush=True)
        centroid_node = {}
        dispersed_nodes = {}
        for zid, row in zones.iterrows():
            poly = row.geometry
            if poly is None or poly.is_empty:
                continue
            cpt = poly.centroid
            cn, cd = snap([cpt])
            if cd[0] <= MAX_SNAP_DIST:
                centroid_node[zid] = int(cn[0])
            pts = sample_points_in_polygon(poly, K_MAX, rng)
            pn, pd_ = snap(pts)
            valid = [int(n) for n, dd in zip(pn, pd_) if dd <= MAX_SNAP_DIST]
            if valid:
                dispersed_nodes[zid] = valid

        def build_od_arrays(dispersion, k=None):
            o_nodes, d_nodes, w = [], [], []
            for _, r in od.iterrows():
                z1, z2, flow = r["geo_code1"], r["geo_code2"], float(r[weight_col])
                if dispersion == "centroid":
                    n1, n2 = centroid_node.get(z1), centroid_node.get(z2)
                    if n1 is None or n2 is None:
                        continue
                    o_nodes.append(n1); d_nodes.append(n2); w.append(flow)
                else:
                    p1_full, p2_full = dispersed_nodes.get(z1), dispersed_nodes.get(z2)
                    if not p1_full or not p2_full:
                        continue
                    p1, p2 = p1_full[:k], p2_full[:k]
                    kk = min(len(p1), len(p2))
                    share = flow / kk
                    for j in range(kk):
                        o_nodes.append(p1[j]); d_nodes.append(p2[j]); w.append(share)
            return o_nodes, d_nodes, w

        od_arrays = {}
        for disp in ["centroid"] + [f"k{k}" for k in K_VALUES]:
            o_nodes, d_nodes, w = build_od_arrays("centroid" if disp == "centroid" else "dispersed",
                                                    k=None if disp == "centroid" else int(disp[1:]))
            od_arrays[disp] = (o_nodes, d_nodes, w)
            print(f"  '{disp}': {len(o_nodes)} OD sub-pairs, {sum(w):.0f} total flow", flush=True)

        results = []

        def run_variant(variant_name, imp_name, disp, tolerance, radius):
            nodes_df, edges_df, net_struct = variants_net[imp_name]
            o_nodes, d_nodes, w = od_arrays[disp]
            non_stub, sens_i, sens_m = matched[imp_name]
            if sens_m.sum() < 3:
                return
            t0 = time.time()
            mem0 = mem_mb()
            od_matrix = cs_networks.rustalgos.centrality.OdMatrix(o_nodes, d_nodes, w)
            res_nodes = cs_networks.betweenness_od(
                network_structure=net_struct, nodes_gdf=nodes_df.copy(),
                od_matrix=od_matrix, distances=[radius],
                tolerance=tolerance if tolerance > 0 else None,
            )
            elapsed = time.time() - t0
            flow_col = f"cc_betweenness_{radius}"
            edges_df2 = edges_df.copy()
            edges_df2["od_flow"] = (
                res_nodes.loc[edges_df2["nx_start_node_key"], flow_col].values
                + res_nodes.loc[edges_df2["nx_end_node_key"], flow_col].values
            ) / 2.0
            non_stub2 = edges_df2[~edges_df2["is_stub"]]
            pred = non_stub2.iloc[sens_i[sens_m]]["od_flow"].values.astype(float)
            m = compute_metrics_loglog(sens_val[sens_m], pred)
            peak_mem = max(mem_mb(), mem0)
            row = {
                "tool": "cityseer_od", "mode": mode, "variant": variant_name,
                "r_squared": m["r_squared"], "pearson_r": m["pearson_r"], "spearman_r": m["spearman_r"],
                "compute_time_s": round(elapsed, 2), "n_matched": int(sens_m.sum()), "n_obs": m["n"],
                "peak_memory_mb": round(peak_mem, 1),
                "segments_per_sec": round(len(edges_df2) / elapsed, 1) if elapsed > 0 else 0.0,
            }
            results.append(row)
            r2s = f"{m['r_squared']:.4f}" if not np.isnan(m["r_squared"]) else "nan"
            print(f"  {variant_name}: log-log R2={r2s} n={m['n']} t={elapsed:.1f}s", flush=True)

        # ── Sweep 1: full factorial imp_factor x dispersion(centroid, k3/k5/k10) x
        #    tolerance(0/3%/5%) at radius=20km (network is clipped to a 10km
        #    buffer, i.e. ~20km diameter, so this radius already reaches most
        #    of the network -- radius is refined around the best combo below). ──
        # (With --weight there is a single "wt{formula}" structure; otherwise
        # the plain/dimensionless_imp pair -- iterate the actual keys.)
        RADIUS0 = 20000
        disp_names = ["centroid"] + [f"k{k}" for k in K_VALUES]
        imp_names = list(variants_net.keys())
        for imp_name in imp_names:
            for disp in disp_names:
                for tol in [0.0, 0.03, 0.05]:
                    name = f"od_{imp_name}_{disp}_tol{tol}_r{RADIUS0}"
                    run_variant(name, imp_name, disp, tol, RADIUS0)

        # ── Sweep 2: pick the best combo so far, sweep radius (small radii
        #    matter here since the whole network fits inside ~20-25km) ──
        df_so_far = pd.DataFrame(results)
        best = df_so_far.loc[df_so_far["r_squared"].idxmax()]
        best_imp = next(im for im in imp_names if f"_{im}_" in best["variant"])
        best_disp = next(d for d in disp_names if f"_{d}_" in best["variant"])
        best_tol = next(t for t in [0.0, 0.03, 0.05] if f"tol{t}_" in best["variant"])
        print(f"  Best so far: {best['variant']} (log-log R2={best['r_squared']:.4f}); sweeping radius around it", flush=True)
        for radius in [3000, 5000, 8000, 12000, 30000, 40000]:
            name = f"od_{best_imp}_{best_disp}_tol{best_tol}_r{radius}"
            run_variant(name, best_imp, best_disp, best_tol, radius)

        df = pd.DataFrame(results)
        out_path = os.path.join(RESULTS_DIR, f"{city}_cityseer_od_results.csv")
        merge_to_csv("cityseer_od", df, out_path)

        best_row = df.loc[df["r_squared"].idxmax()]
        print(f"\n  BEST: {best_row['variant']}  log-log R2={best_row['r_squared']:.4f}  "
              f"t={best_row['compute_time_s']:.1f}s", flush=True)
        print(f"  Saved {len(df)} variants -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
