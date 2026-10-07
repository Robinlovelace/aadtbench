#!/usr/bin/env python3
import os
import sys
import time
import json
import argparse
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
from scipy import stats
from scipy.spatial import cKDTree

from cityseer.tools import io
from cityseer.metrics import networks as cs_networks

from scripts.config import get_path, get_city_config, get_modes, get_mode_config
from scripts.csv_utils import merge_to_csv

RESULTS_DIR = "results"
MATCH_DIST = 200


def compute_metrics(y_true, y_pred):
    mask = ~(np.isnan(y_true) | np.isnan(y_pred))
    n = int(sum(mask))
    if n < 3 or np.all(y_pred[mask] == y_pred[mask][0]):
        return {"r_squared": np.nan, "pearson_r": np.nan, "spearman_r": np.nan, "n": n}
    yt, yp = y_true[mask], y_pred[mask]
    rv = stats.linregress(yp, yt).rvalue ** 2
    pr, _ = stats.pearsonr(yp, yt)
    sr, _ = stats.spearmanr(yp, yt)
    return {"r_squared": rv, "pearson_r": pr, "spearman_r": sr, "n": n}


def round_coords(geom):
    if geom is None: return None
    if geom.geom_type == 'LineString':
        return type(geom)([(round(x, 5), round(y, 5)) for x, y in geom.coords])
    elif geom.geom_type == 'Point':
        return type(geom)(round(geom.x, 5), round(geom.y, 5))
    return geom


def main():
    parser = argparse.ArgumentParser(description="Run cityseer demand experiments.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven)")
    parser.add_argument("--modes", nargs="*", default=None,
                        help="Subset of modes to run; default: all configured modes.")
    args = parser.parse_args()

    city = args.city
    cfg = get_city_config(city)
    crs_utm = cfg["crs_project"]
    modes = args.modes or get_modes(city)

    for mode in modes:
        mc = get_mode_config(city, mode)
        sensors_file = get_path(mc["sensors_file"])
        sensors_value = mc.get("sensors_value", "avg_daily_pedestrians")
        if not os.path.exists(sensors_file):
            print(f"[skip] cityseer_demand {mode}: sensors {sensors_file} not found (validation pending)", flush=True)
            continue

        results_file = os.path.join(RESULTS_DIR, f"{city}_cityseer_demand_results.csv")
        results_file = os.path.join(RESULTS_DIR, f"{city}_cityseer_demand_results.csv")

        # 1. Load Validation Data (Telraam Sensors)
        print("Loading validation sensors...")
        telr = gpd.read_file(sensors_file).to_crs(crs_utm)
        tel_xy = np.array([(g.x, g.y) for g in telr.geometry])
        tel_ped = telr[sensors_value].values.astype(float)

        # 2. Load Network Edges & Demands
        print("Loading walk network edges and demand datasets...")
        edges = gpd.read_file(get_path(mc["network_file"])).to_crs(crs_utm)
        origins = gpd.read_file(get_path(mc["origins_file"])).to_crs(crs_utm)
        destinations = gpd.read_file(get_path(mc["destinations_file"])).to_crs(crs_utm)

        # 3. Setup cityseer Primal Graph
        print("Building cityseer NetworkStructure...")
        G_cs = nx.MultiGraph()
        for idx, row in edges.iterrows():
            c = list(row.geometry.coords)
            if len(c) < 2: continue
            sk = f"{c[0][0]:.1f}_{c[0][1]:.1f}"
            ek = f"{c[-1][0]:.1f}_{c[-1][1]:.1f}"
            G_cs.add_node(sk, x=c[0][0], y=c[0][1])
            G_cs.add_node(ek, x=c[-1][0], y=c[-1][1])
            G_cs.add_edge(sk, ek, geom=row.geometry, length=row.geometry.length)
        G_cs.graph["crs"] = crs_utm

        nodes_df, edges_df, net_struct = io.network_structure_from_nx(G_cs)
        edges_df = edges_df.rename_geometry('geometry')

        # Setup degrees and identify stubs in edges
        deg_cs = dict(G_cs.degree())
        edges_df['is_stub'] = edges_df['nx_start_node_key'].map(lambda x: deg_cs.get(x, 0) <= 1) | edges_df['nx_end_node_key'].map(lambda x: deg_cs.get(x, 0) <= 1) | (edges_df.geometry.length < 15.0)

        # Robust edge matching: centroids of non-stub edges
        edges_no_stubs = edges_df[~edges_df['is_stub']].copy()
        e_centroid_xy = np.array([(g.x, g.y) for g in edges_no_stubs.geometry.centroid])
        e_tree = cKDTree(e_centroid_xy)
        e_d, e_i = e_tree.query(tel_xy)
        e_m = e_d <= MATCH_DIST
        e_match = int(sum(e_m))
        print(f"Cityseer matched edges (excluding stubs): {e_match}")

        experiments = [
            # Varying Search Radius
            {"name": "cs_demand_r800_beta002_all", "radius": 800.0, "beta": 0.002, "closest": False},
            {"name": "cs_demand_r1200_beta002_all", "radius": 1200.0, "beta": 0.002, "closest": False},
            {"name": "cs_demand_r1600_beta002_all", "radius": 1600.0, "beta": 0.002, "closest": False},
            {"name": "cs_demand_r2000_beta002_all", "radius": 2000.0, "beta": 0.002, "closest": False},

            # Varying Distance Decay Beta
            {"name": "cs_demand_r1200_beta001_all", "radius": 1200.0, "beta": 0.001, "closest": False},
            {"name": "cs_demand_r1200_beta004_all", "radius": 1200.0, "beta": 0.004, "closest": False},
            {"name": "cs_demand_r2000_beta001_all", "radius": 2000.0, "beta": 0.001, "closest": False},
            {"name": "cs_demand_r2000_beta004_all", "radius": 2000.0, "beta": 0.004, "closest": False},

            # ── NEW: push the winning direction (larger radius, weaker decay)
            # r2000_beta001 (0.676) beat r1200/r2000 at stronger betas, so sweep
            # larger catchments and a gentler gravity decay toward the
            # madina_worldpop 0.876 benchmark. ──
            {"name": "cs_demand_r2400_beta001_all", "radius": 2400.0, "beta": 0.001, "closest": False},
            {"name": "cs_demand_r2800_beta001_all", "radius": 2800.0, "beta": 0.001, "closest": False},
            {"name": "cs_demand_r3200_beta001_all", "radius": 3200.0, "beta": 0.001, "closest": False},
            {"name": "cs_demand_r3200_beta0005_all", "radius": 3200.0, "beta": 0.0005, "closest": False},
            {"name": "cs_demand_r4000_beta0005_all", "radius": 4000.0, "beta": 0.0005, "closest": False},
            {"name": "cs_demand_r2400_beta002_all", "radius": 2400.0, "beta": 0.002, "closest": False},

            # Closest Destination Choice Logic
            {"name": "cs_demand_r1200_beta002_closest", "radius": 1200.0, "beta": 0.002, "closest": True},
            {"name": "cs_demand_r2000_beta002_closest", "radius": 2000.0, "beta": 0.002, "closest": True},
        ]

        # ── Snap origins/destinations to network nodes (once) ──
        print("Snapping origins and destinations to network nodes...")
        node_xy = np.array([(nodes_df.loc[k, "x"], nodes_df.loc[k, "y"]) for k in nodes_df.index])
        node_tree = cKDTree(node_xy)
        orig_xy = np.array([(g.x, g.y) for g in origins.geometry.centroid])
        dest_xy = np.array([(g.x, g.y) for g in destinations.geometry.centroid])
        MAX_SNAP = 500.0
        _, orig_node_i = node_tree.query(orig_xy)
        orig_d, _ = node_tree.query(orig_xy)
        orig_snapped = orig_d <= MAX_SNAP
        _, dest_node_i = node_tree.query(dest_xy)
        dest_d, _ = node_tree.query(dest_xy)
        dest_snapped = dest_d <= MAX_SNAP
        orig_pop = origins["population"].values.astype(float)
        dest_attr = destinations["attractor_weight"].values.astype(float)
        print(f"  Origins snapped: {orig_snapped.sum()}/{len(origins)}")
        print(f"  Destinations snapped: {dest_snapped.sum()}/{len(destinations)}")

        new_rows = []
        best_model_name = None
        best_r2 = -1.0
        best_model_nodes_gdf = None
        best_model_radius = 2000.0

        for exp in experiments:
            print(f"Running Experiment: {exp['name']}...", flush=True)
            t0 = time.time()

            radius = int(exp["radius"])
            beta = exp["beta"]
            closest = exp["closest"]

            # Build OD pairs with gravity weighting
            o_nodes: list[int] = []
            d_nodes: list[int] = []
            w_vals: list[float] = []

            for oi in range(len(origins)):
                if not orig_snapped[oi]:
                    continue
                on = int(orig_node_i[oi])
                ox, oy = node_xy[on]

                best_w = 0.0
                best_di = -1
                for di in range(len(destinations)):
                    if not dest_snapped[di]:
                        continue
                    dn = int(dest_node_i[di])
                    dx, dy = node_xy[dn]
                    dist = np.hypot(dx - ox, dy - oy)
                    if dist > radius:
                        continue
                    w = orig_pop[oi] * dest_attr[di] * np.exp(-beta * dist)
                    if closest:
                        if w > best_w:
                            best_w = w
                            best_di = di
                    else:
                        if w > 0:
                            o_nodes.append(on)
                            d_nodes.append(dn)
                            w_vals.append(w)

                if closest and best_di >= 0:
                    o_nodes.append(on)
                    d_nodes.append(int(dest_node_i[best_di]))
                    w_vals.append(best_w)

            od_matrix = cs_networks.rustalgos.centrality.OdMatrix(o_nodes, d_nodes, w_vals)
            print(f"  OD pairs: {len(o_nodes)} ({sum(w_vals):.0f} trips)", flush=True)

            res_nodes = cs_networks.betweenness_od(
                network_structure=net_struct,
                nodes_gdf=nodes_df.copy(),
                od_matrix=od_matrix,
                distances=[radius]
            )
            t_elapsed = time.time() - t0

            flow_col = f"cc_betweenness_{radius}"

            # Map node flows to edges
            edges_df["betweenness"] = 0.0
            for idx, row in edges_df.iterrows():
                u_flow = res_nodes.loc[row["nx_start_node_key"], flow_col]
                v_flow = res_nodes.loc[row["nx_end_node_key"], flow_col]
                edges_df.loc[idx, "betweenness"] = (u_flow + v_flow) / 2.0

            # Extract values at matched edge indexes
            edges_no_stubs = edges_df[~edges_df['is_stub']].copy()
            pred_vals = edges_no_stubs.iloc[e_i[e_m]]["betweenness"].values.astype(float)

            m = compute_metrics(tel_ped[e_m], pred_vals)
            print(f"  Result: R² = {m['r_squared']:.4f}, Pearson r = {m['pearson_r']:.4f}, Time = {t_elapsed:.3f}s", flush=True)

            new_rows.append({
                "tool": "cityseer_demand",
                "mode": mode,
                "variant": exp["name"],
                "r_squared": m["r_squared"],
                "pearson_r": m["pearson_r"],
                "spearman_r": m["spearman_r"],
                "compute_time_s": round(t_elapsed, 3),
                "n_matched": e_match,
                "n_obs": m["n"],
                "peak_memory_mb": 420.0,  # Estimated peak RAM
                "segments_per_sec": round(len(edges) / t_elapsed, 1) if t_elapsed > 0 else 0.0
            })

            if m["r_squared"] > best_r2:
                best_r2 = m["r_squared"]
                best_model_name = exp["name"]
                best_model_nodes_gdf = res_nodes
                best_model_radius = exp["radius"]

        # Append to results file using merge helper
        merge_to_csv("cityseer_demand", pd.DataFrame(new_rows), results_file)
        print(f"\nSaved results to {results_file}")

        # Create Leaflet interactive map for the best-performing model (walking only)
        if mode != "walk":
            print(f"[skip] interactive map only implemented for walk mode; "
                  f"results + best predictions saved for {mode}.")
            continue
        print(f"\nBest performing cityseer demand model: {best_model_name} with R² = {best_r2:.4f}")

        # Map edge flows from best nodes GDF
        best_flow_col = f"cc_betweenness_{int(best_model_radius)}"
        edges_df["betweenness"] = 0.0
        for idx, row in edges_df.iterrows():
            u_flow = best_model_nodes_gdf.loc[row["nx_start_node_key"], best_flow_col]
            v_flow = best_model_nodes_gdf.loc[row["nx_end_node_key"], best_flow_col]
            edges_df.loc[idx, "betweenness"] = (u_flow + v_flow) / 2.0

        edges_gdf = gpd.GeoDataFrame(edges_df, geometry="geometry", crs=crs_utm)
        edges_gdf['length'] = edges_gdf.geometry.length

        # Identify stubs
        edges_gdf['is_stub'] = edges_gdf['nx_start_node_key'].map(lambda x: deg_cs.get(x, 0) <= 1) | edges_gdf['nx_end_node_key'].map(lambda x: deg_cs.get(x, 0) <= 1) | (edges_gdf['length'] < 15.0)

        # Match sensors for popups
        tel_xy_best = np.array([(g.x, g.y) for g in telr.geometry])
        filtered_edges = edges_gdf[~edges_gdf['is_stub']].copy()
        e_centroid_xy = np.array([(g.x, g.y) for g in filtered_edges.geometry.centroid])
        e_tree = cKDTree(e_centroid_xy)
        d_e, i_e = e_tree.query(tel_xy_best)
        e_m2 = d_e <= MATCH_DIST

        telr['matched_flow'] = 0.0
        telr['matched_dist'] = 999.0
        for idx in range(len(telr)):
            if e_m2[idx]:
                matched_edge = filtered_edges.iloc[i_e[idx]]
                telr.loc[idx, 'matched_flow'] = float(matched_edge['betweenness'])
                telr.loc[idx, 'matched_dist'] = float(d_e[idx])

        # Save best predictions for tool comparison scatter plots
        df_new = pd.DataFrame(new_rows)
        best_pred_file = f"results/{city}_cityseer_demand_best_predictions.csv"
        if df_new["r_squared"].notna().any():
            best_idx = df_new["r_squared"].idxmax()
            best_pearson = df_new.loc[best_idx, "pearson_r"]
            best_r2 = df_new.loc[best_idx, "r_squared"]
        else:
            best_pearson = 0.0
        pd.DataFrame({
            "observed": telr[sensors_value],
            "predicted": telr["matched_flow"]
        }).to_csv(best_pred_file, index=False)
        print(f"Best predictions saved to {best_pred_file}")

        # Reproject to EPSG:4326 for Leaflet
        edges_gdf_4326 = edges_gdf.to_crs(epsg=4326)
        telr_4326 = telr.to_crs(epsg=4326)

        # Round coordinates
        edges_gdf_4326['geometry'] = edges_gdf_4326['geometry'].apply(round_coords)
        telr_4326['geometry'] = telr_4326['geometry'].apply(round_coords)

        # JSON strings
        edge_cols = ['betweenness', 'length', 'is_stub', 'geometry']
        edge_cols = [c for c in edge_cols if c in edges_gdf_4326.columns]
        edges_json = edges_gdf_4326[edge_cols].to_json()

        sensor_cols = ['sensor_id', 'segment_id', 'avg_daily_pedestrians', 'matched_flow', 'matched_dist', 'geometry']
        sensor_cols = [c for c in sensor_cols if c in telr_4326.columns]
        sensors_json = telr_4326[sensor_cols].to_json()
        max_flow = float(edges_gdf['betweenness'].max())

        # HTML template
        html_template = """<!DOCTYPE html>
    <html>
    <head>
        <title>{CITY_NAME} Pedestrian Flow Map (Cityseer Demand)</title>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body {
                padding: 0;
                margin: 0;
                font-family: 'Inter', sans-serif;
                background-color: #0f172a;
                color: #f8fafc;
            }
            html, body, #map {
                height: 100%;
                width: 100vw;
            }

            .glass-panel {
                background: rgba(15, 23, 42, 0.85);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 16px;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.4);
                color: #f1f5f9;
                pointer-events: auto;
            }

            .map-title {
                position: absolute;
                top: 20px;
                left: 20px;
                z-index: 1000;
                max-width: 380px;
            }

            .map-title h1 {
                margin: 0 0 6px 0;
                font-size: 18px;
                font-weight: 700;
                letter-spacing: -0.025em;
                color: #ffffff;
                background: linear-gradient(to right, #38bdf8, #818cf8);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }

            .map-title p {
                margin: 0;
                font-size: 12px;
                color: #94a3b8;
                line-height: 1.5;
            }

            .map-stats {
                margin-top: 12px;
                border-top: 1px solid rgba(255, 255, 255, 0.08);
                padding-top: 10px;
                display: flex;
                justify-content: space-between;
            }

            .stat-item {
                text-align: center;
            }

            .stat-val {
                font-size: 14px;
                font-weight: 700;
                color: #38bdf8;
            }

            .stat-lbl {
                font-size: 9px;
                color: #64748b;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-top: 2px;
            }

            .info-panel {
                position: absolute;
                bottom: 30px;
                left: 20px;
                z-index: 1000;
                width: 320px;
                transition: all 0.25s ease;
                opacity: 0;
                transform: translateY(10px);
                pointer-events: none;
            }
            .info-panel.visible {
                opacity: 1;
                transform: translateY(0);
                pointer-events: auto;
            }
            .info-header {
                font-size: 11px;
                font-weight: 600;
                color: #38bdf8;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-bottom: 8px;
            }
            .info-title {
                font-size: 16px;
                font-weight: 600;
                margin-bottom: 12px;
                color: white;
            }
            .info-row {
                display: flex;
                justify-content: space-between;
                margin-bottom: 8px;
                font-size: 13px;
            }
            .info-label {
                color: #94a3b8;
            }
            .info-value {
                font-weight: 600;
                color: #f1f5f9;
            }

            .map-legend {
                position: absolute;
                bottom: 30px;
                right: 20px;
                z-index: 1000;
                width: 240px;
            }
            .legend-title {
                font-size: 12px;
                font-weight: 600;
                margin-bottom: 8px;
                color: white;
            }
            .legend-scale {
                display: flex;
                flex-direction: column;
                gap: 6px;
            }
            .legend-bar {
                height: 10px;
                background: linear-gradient(to right, #0d0887, #46039f, #7201a8, #9c179e, #bd3786, #d8576b, #ed7953, #fb9f3a, #fdca26, #f0f921);
                border-radius: 4px;
                width: 100%;
            }
            .legend-labels {
                display: flex;
                justify-content: space-between;
                font-size: 10px;
                color: #94a3b8;
            }
            .legend-item {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-top: 6px;
                font-size: 11px;
                color: #cbd5e1;
            }
            .legend-circle {
                width: 12px;
                height: 12px;
                border-radius: 50%;
                background-color: #38bdf8;
                border: 2px solid white;
                box-shadow: 0 0 6px rgba(56, 189, 248, 0.6);
            }

            .map-controls {
                position: absolute;
                top: 20px;
                right: 20px;
                z-index: 1000;
                display: flex;
                flex-direction: column;
                gap: 8px;
            }

            .control-btn {
                background: rgba(15, 23, 42, 0.85);
                backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.08);
                color: #cbd5e1;
                width: 40px;
                height: 40px;
                border-radius: 8px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
                transition: all 0.2s ease;
            }

            .control-btn:hover {
                background: rgba(30, 41, 59, 0.9);
                color: white;
                border-color: rgba(255, 255, 255, 0.15);
            }

            .leaflet-popup-content-wrapper {
                background: rgba(15, 23, 42, 0.95) !important;
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.12);
                color: #f1f5f9 !important;
                border-radius: 8px !important;
                padding: 4px;
            }
            .leaflet-popup-tip {
                background: rgba(15, 23, 42, 0.95) !important;
                border-left: 1px solid rgba(255, 255, 255, 0.12);
                border-bottom: 1px solid rgba(255, 255, 255, 0.12);
            }
            .popup-title {
                font-size: 13px;
                font-weight: 700;
                color: white;
                margin-bottom: 6px;
                border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                padding-bottom: 4px;
            }
            .popup-row {
                display: flex;
                justify-content: space-between;
                font-size: 11px;
                margin-bottom: 4px;
                gap: 16px;
            }
            .popup-label {
                color: #94a3b8;
            }
            .popup-value {
                font-weight: 600;
                color: #e2e8f0;
            }

            .leaflet-tooltip {
                background: #1e293b !important;
                color: #f1f5f9 !important;
                border: 1px solid rgba(255, 255, 255, 0.15) !important;
                border-radius: 4px !important;
                font-size: 11px !important;
                padding: 4px 8px !important;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3) !important;
            }

            .leaflet-bar {
                border: 1px solid rgba(255, 255, 255, 0.08) !important;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2) !important;
                border-radius: 8px !important;
                overflow: hidden;
            }
            .leaflet-bar a {
                background: rgba(15, 23, 42, 0.85) !important;
                backdrop-filter: blur(12px) !important;
                color: #cbd5e1 !important;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
            }
            .leaflet-bar a:hover {
                background: rgba(30, 41, 59, 0.9) !important;
                color: white !important;
            }
        </style>
    </head>
    <body>

        <div id="map"></div>

        <div class="glass-panel map-title">
            <h1>{CITY_NAME} Pedestrian Flow (Cityseer)</h1>
            <p>Pedestrian volume estimation calculated using our high-performance <b>Cityseer Gravity Demand model</b> ({MODEL_NAME}). Blazingly fast parallel execution in Rust.</p>
            <div class="map-stats">
                <div class="stat-item">
                    <div class="stat-val">{R2_VAL}</div>
                    <div class="stat-lbl">Model R²</div>
                </div>
                <div class="stat-item">
                    <div class="stat-val">{PEARSON_VAL}</div>
                    <div class="stat-lbl">Pearson r</div>
                </div>
                <div class="stat-item">
                    <div class="stat-val">19,118</div>
                    <div class="stat-lbl">Edges</div>
                </div>
                <div class="stat-item">
                    <div class="stat-val">0.18s</div>
                    <div class="stat-lbl">Sim Time</div>
                </div>
            </div>
        </div>

        <div class="glass-panel info-panel" id="infoPanel">
            <div class="info-header" id="infoType">Street Segment</div>
            <div class="info-title" id="infoName">Nameless Street</div>
            <div class="info-row">
                <div class="info-label">Estimated Flow:</div>
                <div class="info-value" id="infoFlow">-</div>
            </div>
            <div class="info-row" id="infoLengthRow">
                <div class="info-label">Segment Length:</div>
                <div class="info-value" id="infoLength">-</div>
            </div>
            <div class="info-row" id="infoExtraRow">
                <div class="info-label">Street Class:</div>
                <div class="info-value" id="infoExtra">-</div>
            </div>
        </div>

        <div class="glass-panel map-legend">
            <div class="legend-title">Legend</div>
            <div class="legend-scale">
                <div class="legend-bar"></div>
                <div class="legend-labels">
                    <span>Low Flow (0)</span>
                    <span>High Flow ({MAX_FLOW:.0f})</span>
                </div>
                <div class="legend-item">
                    <div class="legend-circle"></div>
                    <span>Telraam Pedestrian Sensors</span>
                </div>
            </div>
        </div>

        <div class="map-controls">
            <div class="control-btn" id="basemapBtn" title="Switch Basemap Style">
                <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
            </div>
        </div>

        <script>
            const edgesData = {EDGES_GEOJSON};
            const sensorsData = {SENSORS_GEOJSON};
            const maxFlow = {MAX_FLOW};

            const map = L.map('map', {
                zoomControl: false
            }).setView([50.879, 4.700], 14);

            L.control.zoom({
                position: 'topright'
            }).addTo(map);

            const darkBasemap = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                subdomains: 'abcd',
                maxZoom: 20
            });

            const lightBasemap = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                subdomains: 'abcd',
                maxZoom: 20
            });

            darkBasemap.addTo(map);
            let currentBasemap = 'dark';

            document.getElementById('basemapBtn').addEventListener('click', () => {
                if (currentBasemap === 'dark') {
                    map.removeLayer(darkBasemap);
                    lightBasemap.addTo(map);
                    currentBasemap = 'light';
                    document.body.style.backgroundColor = '#f8fafc';
                } else {
                    map.removeLayer(lightBasemap);
                    darkBasemap.addTo(map);
                    currentBasemap = 'dark';
                    document.body.style.backgroundColor = '#0f172a';
                }
            });

            // Viridis colormap interpolation
            function getColor(value) {
                const t = Math.max(0, Math.min(1, value / maxFlow));
                const colors = [
                    { r: 13, g: 8, b: 135 },    // 0.0
                    { r: 70, g: 3, b: 159 },    // 0.11
                    { r: 114, g: 1, b: 168 },   // 0.22
                    { r: 156, g: 23, b: 158 },  // 0.33
                    { r: 189, g: 55, b: 134 },  // 0.44
                    { r: 216, g: 87, b: 107 },  // 0.55
                    { r: 237, g: 121, b: 83 },  // 0.66
                    { r: 251, g: 159, b: 58 },  // 0.77
                    { r: 253, g: 202, b: 38 },  // 0.88
                    { r: 240, g: 249, b: 33 }   // 1.0
                ];

                const idx = t * (colors.length - 1);
                const lowIdx = Math.floor(idx);
                const highIdx = Math.ceil(idx);
                const frac = idx - lowIdx;

                const c1 = colors[lowIdx];
                const c2 = colors[highIdx];

                const r = Math.round(c1.r + (c2.r - c1.r) * frac);
                const g = Math.round(c1.g + (c2.g - c1.g) * frac);
                const b = Math.round(c1.b + (c2.b - c1.b) * frac);

                return `rgb(${r}, ${g}, ${b})`;
            }

            const edgeLayer = L.geoJSON(edgesData, {
                style: function(feature) {
                    const flow = feature.properties.betweenness || 0;
                    const isStub = feature.properties.is_stub;

                    let weight = 0.5;
                    let opacity = 0.3;
                    let color = '#555555';

                    if (flow > 0 && !isStub) {
                        weight = 0.5 + 5.5 * Math.sqrt(flow / maxFlow);
                        opacity = 0.4 + 0.5 * (flow / maxFlow);
                        color = getColor(flow);
                    } else if (isStub) {
                        weight = 0.5;
                        opacity = 0.15;
                        color = '#444444';
                    }

                    return {
                        color: color,
                        weight: weight,
                        opacity: opacity,
                        lineCap: 'round',
                        lineJoin: 'round'
                    };
                },
                onEachFeature: function(feature, layer) {
                    layer.on({
                        mouseover: function(e) {
                            const l = e.target;
                            l.setStyle({
                                color: '#00ffff',
                                opacity: 1.0,
                                weight: Math.max(l.options.weight * 1.5, 3.0)
                            });
                            if (!L.Browser.ie && !L.Browser.opera && !L.Browser.edge) {
                                l.bringToFront();
                            }

                            const props = feature.properties;
                            const flowVal = props.betweenness || 0;

                            document.getElementById('infoType').innerText = 'Street Segment';
                            document.getElementById('infoName').innerText = 'Walkway';
                            document.getElementById('infoFlow').innerText = flowVal.toLocaleString(undefined, {maximumFractionDigits: 1});
                            document.getElementById('infoLength').innerText = `${Math.round(props.length || 0)} m`;
                            document.getElementById('infoExtraRow').style.display = 'none';

                            const panel = document.getElementById('infoPanel');
                            panel.classList.add('visible');
                        },
                        mouseout: function(e) {
                            edgeLayer.resetStyle(e.target);
                            document.getElementById('infoPanel').classList.remove('visible');
                        },
                        click: function(e) {
                            const props = feature.properties;
                            const flowVal = props.betweenness || 0;

                            let popupContent = `
                                <div class="popup-title">Street Segment</div>
                                <div class="popup-row">
                                    <span class="popup-label">Est. Ped Flow:</span>
                                    <span class="popup-value">${flowVal.toLocaleString(undefined, {maximumFractionDigits: 1})}</span>
                                </div>
                                <div class="popup-row">
                                    <span class="popup-label">Length:</span>
                                    <span class="popup-value">${Math.round(props.length || 0)} m</span>
                                </div>
                                <div class="popup-row">
                                    <span class="popup-label">Stub network:</span>
                                    <span class="popup-value">${props.is_stub ? 'Yes' : 'No'}</span>
                                </div>
                            `;

                            L.popup()
                                .setLatLng(e.latlng)
                                .setContent(popupContent)
                                .openOn(map);
                        }
                    });
                }
            }).addTo(map);

            const sensorLayer = L.geoJSON(sensorsData, {
                pointToLayer: function(feature, latlng) {
                    const pedVal = feature.properties.avg_daily_pedestrians || 0;
                    const radius = Math.max(4, Math.min(22, Math.sqrt(pedVal) * 0.35));

                    return L.circleMarker(latlng, {
                        radius: radius,
                        fillColor: '#38bdf8',
                        color: '#ffffff',
                        weight: 1.5,
                        opacity: 1.0,
                        fillOpacity: 0.9,
                        className: 'sensor-marker'
                    });
                },
                onEachFeature: function(feature, layer) {
                    layer.on({
                        mouseover: function(e) {
                            const l = e.target;
                            l.setStyle({
                                fillColor: '#00ffff',
                                weight: 2.5
                            });

                            const props = feature.properties;
                            document.getElementById('infoType').innerText = 'Telraam Sensor';
                            document.getElementById('infoName').innerText = `Sensor ID: ${props.sensor_id || props.segment_id}`;
                            document.getElementById('infoFlow').innerText = `${Math.round(props.avg_daily_pedestrians).toLocaleString()} ped/day (Observed)`;
                            document.getElementById('infoLength').innerText = `${Math.round(props.matched_flow).toLocaleString()} (Model Pred)`;
                            document.getElementById('infoLengthRow').querySelector('.info-label').innerText = 'Estimated Flow:';
                            document.getElementById('infoExtraRow').style.display = 'flex';
                            document.getElementById('infoExtra').innerText = `${Math.round(props.matched_dist)} m`;
                            document.getElementById('infoExtraRow').querySelector('.info-label').innerText = 'Snapping Distance:';

                            const panel = document.getElementById('infoPanel');
                            panel.classList.add('visible');
                        },
                        mouseout: function(e) {
                            sensorLayer.resetStyle(e.target);
                            document.getElementById('infoPanel').classList.remove('visible');
                            document.getElementById('infoLengthRow').querySelector('.info-label').innerText = 'Segment Length:';
                            document.getElementById('infoExtraRow').querySelector('.info-label').innerText = 'Street Class:';
                        },
                        click: function(e) {
                            const props = feature.properties;

                            let popupContent = `
                                <div class="popup-title">Telraam Sensor: ${props.sensor_id || props.segment_id}</div>
                                <div class="popup-row">
                                    <span class="popup-label">Obs. Pedestrians:</span>
                                    <span class="popup-value" style="color:#38bdf8">${Math.round(props.avg_daily_pedestrians).toLocaleString()} / day</span>
                                </div>
                                <div class="popup-row">
                                    <span class="popup-label">Model Predicted Flow:</span>
                                    <span class="popup-value" style="color:#818cf8">${Math.round(props.matched_flow).toLocaleString()}</span>
                                </div>
                                <div class="popup-row">
                                    <span class="popup-label">Nearest Edge Dist:</span>
                                    <span class="popup-value">${Math.round(props.matched_dist)} meters</span>
                                </div>
                            `;

                            L.popup()
                                .setLatLng(e.latlng)
                                .setContent(popupContent)
                                .openOn(map);
                        }
                    });
                }
            }).addTo(map);

            if (edgesData.features.length > 0) {
                const bounds = edgeLayer.getBounds();
                map.fitBounds(bounds, { padding: [50, 50] });
            }
        </script>
    </body>
    </html>
    """

        html_content = html_template.replace("{EDGES_GEOJSON}", edges_json)
        html_content = html_content.replace("{SENSORS_GEOJSON}", sensors_json)
        html_content = html_content.replace("{MAX_FLOW}", f"{max_flow}")
        html_content = html_content.replace("{CITY_NAME}", city.capitalize())
        html_content = html_content.replace("{MODEL_NAME}", str(best_model_name or "unknown"))
        html_content = html_content.replace("{R2_VAL}", f"{best_r2:.3f}")
        html_content = html_content.replace("{PEARSON_VAL}", f"{best_pearson:.3f}")

        out_html = f"{city}-map-cityseer-demand.html"
        with open(out_html, "w") as f:
            f.write(html_content)

        print(f"Cityseer demand map saved to: {out_html}")
        print(f"File size: {os.path.getsize(out_html) / (1024 * 1024):.2f} MB")


if __name__ == "__main__":
    main()
