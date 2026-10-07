#!/usr/bin/env python3
"""Run a single madina demand estimation experiment for a city."""
import os
import sys
import argparse
import time
import warnings
import json
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import psutil

from madina.zonal import Zonal
from scripts.config import get_path, get_city_config, get_mode_config
from madina.una import parallel_betweenness
from scripts.utils.helpers import compute_metrics, filter_stubs, match_sensors_to_edges

warnings.filterwarnings('ignore')

MATCH_DIST = 200
_process = psutil.Process(os.getpid())

def mem_now_mb():
    return _process.memory_info().rss / (1024 * 1024)

def main():
    parser = argparse.ArgumentParser(description="Run a single betweenness experiment.")
    parser.add_argument("--city", default="leuven", help="City name")
    parser.add_argument("--mode", default="walk", help="Travel mode (walk/cycle/drive)")
    parser.add_argument("--name", required=True, help="Variant name")
    parser.add_argument("--search-radius", type=float, required=True, help="Search radius")
    parser.add_argument("--detour-ratio", type=float, required=True, help="Detour ratio")
    parser.add_argument("--closest-destination", action="store_true", help="Closest destination flag")
    parser.add_argument("--decay", action="store_true", help="Decay flag")
    parser.add_argument("--beta", type=float, required=True, help="Decay beta")
    args = parser.parse_args()

    cfg = get_city_config(args.city)
    mc = get_mode_config(args.city, args.mode)
    crs_project = cfg["crs_project"]
    sensors_value = mc.get("sensors_value", "avg_daily_pedestrians")

    # Load data layers
    edges = gpd.read_file(get_path(mc["network_file"])).to_crs(crs_project)
    telr = gpd.read_file(get_path(mc["sensors_file"])).to_crs(crs_project)
    origins = gpd.read_file(get_path(mc["origins_file"])).to_crs(crs_project)
    destinations = gpd.read_file(get_path(mc["destinations_file"])).to_crs(crs_project)

    # Keep only the largest weakly-connected component (by u/v node id): edge
    # clipping (e.g. Leeds' 10km-buffer clip, which keeps/drops edges purely
    # by centroid-in-buffer) can leave a handful of disconnected boundary
    # fragments, which otherwise surface as orphaned nodes in madina's own
    # topology builder and crash create_graph() with a KeyError.
    if "u" in edges.columns and "v" in edges.columns:
        comp_graph = nx.Graph()
        comp_graph.add_edges_from(zip(edges["u"].astype(int), edges["v"].astype(int)))
        largest_component = max(nx.connected_components(comp_graph), key=len)
        n0 = len(edges)
        edges = edges[edges["u"].astype(int).isin(largest_component)
                      & edges["v"].astype(int).isin(largest_component)].reset_index(drop=True)
        if len(edges) < n0:
            print(f"  Dropped {n0 - len(edges)} edges outside the largest connected component", flush=True)

    t0 = time.time()

    # Initialize Zonal and build network
    z = Zonal()
    z.load_layer(name='streets', source=edges)
    # node_snapping_tolerance handles sub-metre floating-point mismatches
    # between line endpoints that should coincide (same root cause as above).
    z.create_street_network(source_layer='streets', weight_attribute='length', node_snapping_tolerance=0.1)
    z.load_layer(name='origins', source=origins)
    z.load_layer(name='destinations', source=destinations)
    z.insert_node(layer_name='origins', label='origin', weight_attribute='population')
    z.insert_node(layer_name='destinations', label='destination', weight_attribute='attractor_weight')
    z.create_graph(light_graph=True)
    
    # Run betweenness flow simulation
    results = parallel_betweenness(
        z.network,
        search_radius=args.search_radius,
        detour_ratio=args.detour_ratio,
        decay=args.decay,
        decay_method='exponent',
        beta=args.beta,
        num_cores=8,
        origin_weights=True,
        origin_weight_attribute='weight',
        closest_destination=args.closest_destination,
        destination_weights=True,
        destination_weight_attribute='weight',
        light_graph=True,
        turn_penalty=False
    )
    edge_gdf = results['edge_gdf']
    elapsed = time.time() - t0
    
    # Filter stubs and snap sensors to edges using helpers
    non_stub_gdf = filter_stubs(edge_gdf, z.network.light_graph)
    matched, idxs, dists = match_sensors_to_edges(non_stub_gdf, telr, MATCH_DIST)
    nm = int(np.sum(matched))
    
    # Get observed and predicted values
    matched_idxs = non_stub_gdf.iloc[idxs[matched]].index
    obs = telr.iloc[matched][sensors_value].values.astype(float)
    pred = edge_gdf.loc[matched_idxs, 'betweenness'].values.astype(float)
    
    m = compute_metrics(obs, pred)
    peak_mem = mem_now_mb()
    
    res = {
        "tool": "madina_worldpop",
        "mode": args.mode,
        "variant": args.name,
        "r_squared": m["r_squared"],
        "pearson_r": m["pearson_r"],
        "spearman_r": m["spearman_r"],
        "compute_time_s": round(elapsed, 2),
        "n_matched": nm,
        "n_obs": m["n"],
        "peak_memory_mb": round(peak_mem, 1),
        "segments_per_sec": round(len(edge_gdf) / elapsed, 1) if elapsed > 0 else 0
    }
    
    # Print result JSON so parent process can parse it
    print(f"RESULT_JSON:{json.dumps(res)}")

if __name__ == "__main__":
    main()
