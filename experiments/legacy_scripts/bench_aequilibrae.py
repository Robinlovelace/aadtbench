#!/usr/bin/env python3
"""
aequilibrae first-look benchmark for Leeds, validated against real DfT AADT
counts (drive mode) using the same real 2011 Census journey-to-work
(car_driver) OD flows used by scripts/bench_cityseer_od.py.

This is a FIRST LOOK at genuine multi-path/capacity-restrained traffic
assignment (the one thing none of cityseer/madina/sDNA+/flownet do): all-or-
nothing (AoN, single shortest path -- the same paradigm as the other tools)
vs Frank-Wolfe-family user-equilibrium (UE, iterative capacity-restrained
rebalancing across multiple paths) vs aequilibrae's stochastic route-choice
module (link-penalisation, a proxy for SUE: multiple randomised paths per OD
pair rather than one).

aequilibrae's Project/spatialite machinery is NOT used here -- TrafficClass /
TrafficAssignment / Graph all work standalone against a plain pandas
DataFrame network (aequilibrae.paths.Graph.network), which is far lighter for
a first look than building a full spatialite project from the existing .gpkg.

Caveats (explicitly first-look, not deep-tuned):
  - No real lane-count or capacity data is available for Leeds, so per-class
    free-flow speed and capacity are approximated from OSM `highway` class
    (same style of lookup as the cityseer imp_factor fix). This is a rough
    assumption, not measured capacity -- flagged in the README.
  - Demand injection uses zone centroids only (no K-point dispersion sweep,
    unlike bench_cityseer_od.py) -- a first look, not a parameter sweep.

Usage:  PYTHONPATH=. .venv/bin/python scripts/bench_aequilibrae.py --city leeds
Output: results/leeds_aequilibrae_results.csv
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

from aequilibrae.matrix import AequilibraeMatrix
from aequilibrae.paths import Graph, TrafficAssignment, TrafficClass

from scripts.config import get_path, get_city_config, get_mode_config
from scripts.csv_utils import merge_to_csv
from scripts.utils.helpers import compute_metrics_loglog

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)
MATCH_DIST = 200.0
MAX_SNAP_DIST = 500.0
_process = psutil.Process()

# Free-flow mph and rough one-lane-equivalent capacity (veh/hour) by OSM
# highway class -- approximations in the absence of real lane/capacity data
# for Leeds (see module docstring caveat).
CLASS_SPEED_MPH = {
    "motorway": 65, "motorway_link": 40, "trunk": 55, "trunk_link": 35,
    "primary": 35, "primary_link": 25, "secondary": 30, "secondary_link": 25,
    "tertiary": 25, "tertiary_link": 20, "unclassified": 22,
    "residential": 18, "living_street": 10, "busway": 20,
}
CLASS_CAPACITY_VPH = {
    "motorway": 2200, "motorway_link": 1500, "trunk": 1800, "trunk_link": 1200,
    "primary": 900, "primary_link": 700, "secondary": 600, "secondary_link": 500,
    "tertiary": 400, "tertiary_link": 350, "unclassified": 300,
    "residential": 200, "living_street": 100, "busway": 400,
}
DEFAULT_MPH = 20
DEFAULT_CAPACITY = 300
MPH_TO_MS = 0.44704


def first_class(highway):
    if isinstance(highway, list):
        return highway[0] if highway else "unclassified"
    s = str(highway)
    if s.startswith("["):
        s = s.strip("[]").split(",")[0].strip().strip("'\"")
    return s


def mem_mb():
    return _process.memory_info().rss / (1024 * 1024)


def build_node_map(edges):
    """Map raw OSM node ids to compact sequential int64 ids (1..N).

    aequilibrae's Graph.prepare_graph() allocates arrays indexed by the
    maximum node id, so raw OSM ids (up to ~1.4e10 for Leuven) trigger a
    ~100GB mmap and an OOM kill (exit 137). Compact ids keep every
    allocation proportional to the actual number of distinct nodes.
    """
    raw = np.unique(
        np.concatenate([
            edges["u"].astype(np.int64).values,
            edges["v"].astype(np.int64).values,
        ])
    )
    return {int(r): i + 1 for i, r in enumerate(raw)}


def build_graph(edges, node_map, cap_scale=1.0):
    """Build an aequilibrae Graph directly from a plain edge DataFrame
    (bypassing the spatialite Project entirely -- see module docstring).

    a_node/b_node are the compact renumbered ids from build_node_map() --
    raw OSM ids are far too large for aequilibrae's node-indexed arrays.
    cap_scale multiplies the per-class capacity (capacity calibration sweep).
    """
    cls = edges["highway"].map(first_class)
    speed_ms = cls.map(CLASS_SPEED_MPH).fillna(DEFAULT_MPH).astype(float) * MPH_TO_MS
    capacity = cls.map(CLASS_CAPACITY_VPH).fillna(DEFAULT_CAPACITY).astype(float) * cap_scale

    network = pd.DataFrame({
        "link_id": np.arange(1, len(edges) + 1, dtype=np.int64),
        "a_node": edges["u"].map(node_map).astype(np.int64).values,
        "b_node": edges["v"].map(node_map).astype(np.int64).values,
        "direction": np.int8(1),
        "distance": edges.geometry.length.values.astype(float),
        "free_flow_time": (edges.geometry.length.values.astype(float) / speed_ms.values),
        "capacity": capacity.values,
    })
    graph = Graph()
    graph.network = network
    graph.mode = "c"
    return graph


def node_coords_from_edges(edges, node_map):
    coords = {}
    for row in edges.itertuples():
        c = list(row.geometry.coords)
        u, v = node_map[int(row.u)], node_map[int(row.v)]
        if u not in coords:
            coords[u] = c[0]
        if v not in coords:
            coords[v] = c[-1]
    return coords


def build_demand_matrix(od, weight_col, zones, node_xy_lookup, node_tree, node_ids,
                        demand_scale=1.0):
    """Snap zone centroids to nearest network node and aggregate car_driver
    OD flow into a square AequilibraeMatrix keyed by network node id.
    demand_scale multiplies all flows (e.g. /10 for an ~hourly approximation
    of the daily census OD, since capacities are per-hour)."""
    centroid_xy = np.array([(g.x, g.y) for g in zones.geometry.centroid])
    d, i = node_tree.query(centroid_xy)
    zone_to_node = {
        zid: int(node_ids[i[j]])
        for j, zid in enumerate(zones.index)
        if d[j] <= MAX_SNAP_DIST
    }
    flows = {}
    for r in od.itertuples(index=False):
        n1, n2 = zone_to_node.get(getattr(r, "geo_code1")), zone_to_node.get(getattr(r, "geo_code2"))
        if n1 is None or n2 is None or n1 == n2:
            continue
        w = float(getattr(r, weight_col)) * demand_scale
        flows[(n1, n2)] = flows.get((n1, n2), 0.0) + w

    used_nodes = sorted({n for pair in flows for n in pair})
    pos = {n: k for k, n in enumerate(used_nodes)}
    z = len(used_nodes)
    data = np.zeros((z, z), dtype=np.float64)
    for (n1, n2), w in flows.items():
        data[pos[n1], pos[n2]] = w

    mat = AequilibraeMatrix()
    mat.create_empty(zones=z, matrix_names=["demand"], index_names=["node_id"], memory_only=True)
    mat.index[:] = np.array(used_nodes, dtype=np.int64)
    mat.matrix["demand"][:, :] = data
    mat.computational_view(["demand"])
    return mat, np.array(used_nodes, dtype=np.int64), int((data > 0).sum()), float(data.sum())


def run_assignment(graph, matrix, algorithm, vdf_params=None, max_iter=20, rgap=0.001,
                   cores=1):
    # aequilibrae requires VDF/capacity/time_field to be set even for AoN
    # (LinearApproximation validates all of them regardless of algorithm) --
    # they are simply unused by the AoN iteration itself.
    tc = TrafficClass("cars", graph, matrix)
    tc.set_pce(1.0)
    assig = TrafficAssignment()
    assig.set_classes([tc])
    assig.set_vdf("BPR")
    assig.set_vdf_parameters(vdf_params or {"alpha": 0.15, "beta": 4.0})
    assig.set_capacity_field("capacity")
    assig.set_time_field("free_flow_time")
    assig.max_iter = max_iter
    assig.rgap_target = rgap
    assig.set_algorithm(algorithm)
    try:
        if cores > 1:
            assig.set_cores(cores)
    except Exception:
        pass
    assig.execute(log_specification=False)
    return assig.results()


def main():
    parser = argparse.ArgumentParser(description="aequilibrae first-look traffic assignment benchmark.")
    parser.add_argument("--city", default="leeds", help="City name (e.g. leeds)")
    parser.add_argument("--modes", nargs="*", default=None, help="Subset of modes; default: drive")
    args = parser.parse_args()

    city = args.city
    cfg = get_city_config(city)
    crs_project = cfg["crs_project"]
    od_file = cfg.get("od_file")
    zones_file = cfg.get("zones_file")
    if not od_file or not os.path.exists(od_file) or not os.path.exists(zones_file):
        print(f"[skip] aequilibrae: od_file/zones_file not configured or missing for {city}")
        return

    modes = args.modes or ["drive"]
    od_df = pd.read_csv(od_file)
    zones = gpd.read_file(zones_file).to_crs(crs_project).set_index("geo_code")

    results = []
    for mode in modes:
        mc = get_mode_config(city, mode)
        sensors_file = get_path(mc["sensors_file"])
        edges_file = get_path(mc["network_file"])
        sensors_value = mc.get("sensors_value")
        if not os.path.exists(sensors_file):
            print(f"[skip] aequilibrae {mode}: sensors {sensors_file} not found (validation pending)")
            continue

        print(f"=== aequilibrae / {city} / {mode} ===", flush=True)
        sensors = gpd.read_file(sensors_file).to_crs(crs_project)
        sens_xy = np.array([(g.x, g.y) for g in sensors.geometry])
        sens_val = sensors[sensors_value].values.astype(float)

        edges = gpd.read_file(edges_file).to_crs(crs_project).reset_index(drop=True)
        print(f"  Network: {len(edges)} directed links", flush=True)

        weight_col = "car_driver" if "car_driver" in od_df.columns else "all"
        od = od_df[(od_df["geo_code1"].isin(zones.index)) & (od_df["geo_code2"].isin(zones.index)) & (od_df[weight_col] > 0)]
        print(f"  OD pairs (both zones matched, {weight_col}>0): {len(od)}", flush=True)

        node_map = build_node_map(edges)
        node_coords = node_coords_from_edges(edges, node_map)
        node_ids = np.array(list(node_coords.keys()), dtype=np.int64)
        node_xy = np.array(list(node_coords.values()))
        node_tree = cKDTree(node_xy)

        matrix, centroids, n_od_pairs, total_flow = build_demand_matrix(
            od, weight_col, zones, node_coords, node_tree, node_ids
        )
        print(f"  Demand matrix: {len(centroids)} centroids, {n_od_pairs} nonzero pairs, "
              f"total flow={total_flow:.0f}", flush=True)
        if len(centroids) < 3:
            print(f"  [skip] too few zone centroids snapped to network for {mode}", flush=True)
            continue

        # Edge <-> sensor matching (by edge centroid, shared across variants
        # since the network/link_id ordering is identical for every algorithm).
        ec = np.array([(g.x, g.y) for g in edges.geometry.centroid])
        e_tree = cKDTree(ec)
        e_d, e_i = e_tree.query(sens_xy)
        e_m = e_d <= MATCH_DIST
        print(f"  Matched {int(e_m.sum())}/{len(sensors)} sensors to links", flush=True)
        if e_m.sum() < 3:
            print(f"  [skip] too few matched sensors for {mode}", flush=True)
            continue

        graph = build_graph(edges, node_map)
        graph.prepare_graph(centroids=centroids)
        graph.set_blocked_centroid_flows(False)
        graph.set_graph("free_flow_time")

        variants = [
            # (name, algorithm, vdf_params, max_iter, rgap, cap_scale, demand_scale)
            ("aon", "all-or-nothing", None, 20, 0.001, 1.0, 1.0),
            ("ue_bfw", "bfw", {"alpha": 0.15, "beta": 4.0}, 20, 0.001, 1.0, 1.0),
            ("ue_fw", "frank-wolfe", {"alpha": 0.15, "beta": 4.0}, 20, 0.001, 1.0, 1.0),
            ("ue_msa", "msa", {"alpha": 0.15, "beta": 4.0}, 20, 0.001, 1.0, 1.0),
            # Follow-ups on the best UE variant: tighter convergence, higher
            # congestion BPR parameterisation (alpha=0.5).
            ("ue_bfw_tight", "bfw", {"alpha": 0.15, "beta": 4.0}, 60, 1e-4, 1.0, 1.0),
            ("ue_bfw_a05", "bfw", {"alpha": 0.5, "beta": 4.0}, 20, 0.001, 1.0, 1.0),
            # ── NEW: deeper convergence (RGap was never reached at 20 iters) ──
            ("ue_bfw_iter100", "bfw", {"alpha": 0.15, "beta": 4.0}, 100, 1e-5, 1.0, 1.0),
            # ── NEW: capacity calibration (crude per-class defaults) ──
            ("ue_bfw_cap05", "bfw", {"alpha": 0.15, "beta": 4.0}, 40, 1e-3, 0.5, 1.0),
            ("ue_bfw_cap2", "bfw", {"alpha": 0.15, "beta": 4.0}, 40, 1e-3, 2.0, 1.0),
            # ── NEW: BPR alpha/beta sweeps ──
            ("ue_bfw_bpr_a0.15_b1", "bfw", {"alpha": 0.15, "beta": 1.0}, 40, 1e-3, 1.0, 1.0),
            ("ue_bfw_bpr_a0.3_b2", "bfw", {"alpha": 0.3, "beta": 2.0}, 40, 1e-3, 1.0, 1.0),
            ("ue_bfw_bpr_a0.1_b6", "bfw", {"alpha": 0.1, "beta": 6.0}, 40, 1e-3, 1.0, 1.0),
            # ── NEW: demand scaled to ~hourly (daily OD vs per-hour capacity
            #    gave astronomically high v/c ratios and non-convergence) ──
            ("ue_bfw_d10", "bfw", {"alpha": 0.15, "beta": 4.0}, 40, 1e-3, 1.0, 0.1),
        ]
        for variant_name, algo, vdf_params, max_iter, rgap, cap_scale, demand_scale in variants:
            t0 = time.time()
            mem0 = mem_mb()
            try:
                # Fresh graph per variant: capacity scaling needs a rebuilt
                # network, and aequilibrae's assignment mutates graph state.
                g = build_graph(edges, node_map, cap_scale=cap_scale)
                g.prepare_graph(centroids=centroids)
                g.set_blocked_centroid_flows(False)
                g.set_graph("free_flow_time")
                mat, _, _, _ = build_demand_matrix(od, weight_col, zones, node_coords,
                                                   node_tree, node_ids,
                                                   demand_scale=demand_scale)
                res = run_assignment(g, mat, algo, vdf_params, max_iter, rgap, cores=8)
            except Exception as e:
                print(f"  {variant_name}: FAILED -> {e}", flush=True)
                continue
            elapsed = time.time() - t0
            # Per-class flow columns are named "{matrix_core_name}_tot" (our
            # matrix core is named "demand") -- not "matrix_tot".
            flow_col = "demand_tot"
            # res is indexed by link_id (1-based, matching our `network.link_id`).
            flow_by_link = res[flow_col].reindex(np.arange(1, len(edges) + 1)).values.astype(float)
            pred = flow_by_link[e_i[e_m]]
            m = compute_metrics_loglog(sens_val[e_m], pred)
            peak_mem = max(mem_mb(), mem0)
            row = {
                "tool": "aequilibrae", "mode": mode, "variant": variant_name,
                "r_squared": m["r_squared"], "pearson_r": m["pearson_r"], "spearman_r": m["spearman_r"],
                "compute_time_s": round(elapsed, 2), "n_matched": int(e_m.sum()), "n_obs": m["n"],
                "peak_memory_mb": round(peak_mem, 1),
                "segments_per_sec": round(len(edges) / elapsed, 1) if elapsed > 0 else 0.0,
            }
            results.append(row)
            r2s = f"{m['r_squared']:.4f}" if not np.isnan(m["r_squared"]) else "nan"
            print(f"  {variant_name}: log-log R2={r2s} n={m['n']} t={elapsed:.1f}s", flush=True)

        # ── Stochastic route choice (link-penalisation): a proxy for SUE --
        # multiple randomised paths per OD pair rather than one, unlike AoN. ──
        try:
            from aequilibrae.paths.route_choice import RouteChoice

            for rc_name, max_routes, penalty in [("route_choice_lp", 5, 1.1),
                                                 ("route_choice_lp10", 10, 1.05)]:
                t0 = time.time()
                mem0 = mem_mb()
                rc_graph = build_graph(edges, node_map)
                rc_graph.prepare_graph(centroids=centroids)
                rc_graph.set_blocked_centroid_flows(False)
                rc_graph.set_graph("free_flow_time")
                # A fresh matrix, not the one reused across the TrafficAssignment
                # runs above -- aequilibrae's assignment internals mutate
                # matrix.matrix_view's shape as a side effect, which breaks
                # RouteChoice.add_demand() if the same matrix object is reused.
                rc_matrix, _, _, _ = build_demand_matrix(od, weight_col, zones, node_coords, node_tree, node_ids)
                rc = RouteChoice(rc_graph)
                rc.set_choice_set_generation("link-penalisation", max_routes=max_routes, penalty=penalty)
                rc.add_demand(rc_matrix)
                rc.execute(perform_assignment=True)
                link_loads = rc.get_load_results()
                flow_col = "demand_tot" if "demand_tot" in link_loads.columns else link_loads.columns[-1]
                flow_by_link = link_loads[flow_col].reindex(np.arange(1, len(edges) + 1)).fillna(0.0).values.astype(float)
                elapsed = time.time() - t0
                pred = flow_by_link[e_i[e_m]]
                m = compute_metrics_loglog(sens_val[e_m], pred)
                peak_mem = max(mem_mb(), mem0)
                row = {
                    "tool": "aequilibrae", "mode": mode, "variant": rc_name,
                    "r_squared": m["r_squared"], "pearson_r": m["pearson_r"], "spearman_r": m["spearman_r"],
                    "compute_time_s": round(elapsed, 2), "n_matched": int(e_m.sum()), "n_obs": m["n"],
                    "peak_memory_mb": round(peak_mem, 1),
                    "segments_per_sec": round(len(edges) / elapsed, 1) if elapsed > 0 else 0.0,
                }
                results.append(row)
                r2s = f"{m['r_squared']:.4f}" if not np.isnan(m["r_squared"]) else "nan"
                print(f"  {rc_name}: log-log R2={r2s} n={m['n']} t={elapsed:.1f}s", flush=True)
        except Exception as e:
            print(f"  route_choice_lp: FAILED/unsupported -> {e}", flush=True)

    if not results:
        print("No aequilibrae results produced (check network/sensor/OD availability).", flush=True)
        return

    df = pd.DataFrame(results)
    out_path = os.path.join(RESULTS_DIR, f"{city}_aequilibrae_results.csv")
    merge_to_csv("aequilibrae", df, out_path)
    best_row = df.loc[df["r_squared"].idxmax()]
    print(f"\n  BEST: {best_row['variant']}  log-log R2={best_row['r_squared']:.4f}  "
          f"t={best_row['compute_time_s']:.1f}s", flush=True)
    print(f"  Saved {len(df)} variants -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
