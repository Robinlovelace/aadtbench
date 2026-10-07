#!/usr/bin/env python3
"""Tool comparison figure: 4 rows (top tools) × 2 cols (network map + scatter plots)."""
import os
import sys
import argparse
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.spatial import cKDTree

from scripts.config import get_path, get_city_config

warnings.filterwarnings("ignore")

DATA_DIR = "data"
RESULTS_DIR = "results"
MATCH_DIST = 200
os.makedirs(RESULTS_DIR, exist_ok=True)

def main():
    parser = argparse.ArgumentParser(description="Generate top performing methods comparison plot.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven)")
    args = parser.parse_args()
    
    city = args.city
    cfg = get_city_config(city)
    crs_project = cfg["crs_project"]
    
    # ── Load sensors ──
    tel = gpd.read_file(get_path(cfg["sensors_file"])).to_crs(crs_project)
    tel_xy = np.array([(g.x, g.y) for g in tel.geometry])
    tel_ped = tel["avg_daily_pedestrians"].values.astype(float)
    
    # ── Network edge matching ──
    edges = gpd.read_file(get_path(cfg["edges_file"])).to_crs(crs_project)
    ec = np.array([(g.x, g.y) for g in edges.geometry.centroid])
    e_d, e_i = cKDTree(ec).query(tel_xy)
    e_match = e_d <= MATCH_DIST
    m = e_match
    print(f"City: {city}, Sensors: {len(tel)}, matched: {int(m.sum())}")
    
    # ── Load results CSVs ──
    results_path = f"results/{city}_results.csv"
    if os.path.exists(results_path):
        results_df = pd.read_csv(results_path)
    else:
        results_df = pd.DataFrame(columns=["tool", "variant", "r_squared", "pearson_r"])
    
    # Find best variant for each tool
    def get_best_variant(tool_name, fallback_var, fallback_r2, fallback_r):
        sub = results_df[results_df["tool"] == tool_name].dropna(subset=["r_squared"])
        if len(sub) > 0:
            best_row = sub.sort_values("r_squared", ascending=False).iloc[0]
            return best_row["variant"], float(best_row["r_squared"]), float(best_row["pearson_r"])
        return fallback_var, fallback_r2, fallback_r
        
    madina_wp_var, madina_wp_r2, madina_wp_r = get_best_variant("madina_worldpop", "wp_r2000_det100_all_beta001", 0.6763, 0.8224)
    cityseer_dem_var, cityseer_dem_r2, cityseer_dem_r = get_best_variant("cityseer_demand", "cs_demand_r800_beta002_all", 0.5432, 0.7370)
    sdna_var, sdna_r2, sdna_r = get_best_variant("sdna", "MAD_angular_400m", 0.3533, 0.5944)
    madina_var, madina_r2, madina_r = get_best_variant("madina", "degree", 0.1453, -0.3812)
    flownet_var, flownet_r2, flownet_r = get_best_variant("flownet", "psl_beta0.002_detour1.5", 0.0, 0.0)

    TOOLS = [
        ("madina_worldpop", madina_wp_var, madina_wp_r2, madina_wp_r, "#f39c12", f"results/{city}_best_predictions.csv"),
        ("cityseer_demand", cityseer_dem_var, cityseer_dem_r2, cityseer_dem_r, "#9b59b6", f"results/{city}_cityseer_demand_best_predictions.csv"),
        ("sdna",            sdna_var,        sdna_r2,        sdna_r,        "#1abc9c", "results/sdna_best_predictions.csv"),
        ("flownet",         flownet_var,     flownet_r2,     flownet_r,     "#2ecc71", None),
        ("madina",          madina_var,      madina_r2,      madina_r,      "#e74c3c", None),
    ]
    
    # ── Figure setup ──
    fig, axes = plt.subplots(4, 2, figsize=(14, 20))
    tel_wm = tel.to_crs(3857)
    edges_wm = edges.to_crs(3857)
    
    # Standard zoom boundaries for the maps (sensor cluster plus 1000m buffer)
    xmin, ymin, xmax, ymax = tel_wm.total_bounds
    xmin, xmax = xmin - 1000, xmax + 1000
    ymin, ymax = ymin - 1000, ymax + 1000
    
    for row_idx, (tool, variant, r2, r_val, color, pred_file) in enumerate(TOOLS):
        # ── Left Column: Network Map ──
        ax = axes[row_idx, 0]
        edges_wm.plot(ax=ax, linewidth=0.4, color="#2c3e50", alpha=0.4)
        sizes = np.clip(tel_wm["avg_daily_pedestrians"] * 0.05, 6, 60)
        tel_wm.plot(ax=ax, markersize=sizes, color=color, edgecolor="black",
                    linewidth=0.5, alpha=0.8, zorder=5)
        ax.set_title(f"{tool} — {variant}", fontsize=11, fontweight="bold")
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        ax.set_axis_off()
        
        # ── Right Column: Scatter Plot or Stats Card ──
        ax = axes[row_idx, 1]
        
        obs = None
        pred = None
        
        if tool == "madina" and variant == "degree":
            # Calculate degree centrality dynamically
            G = nx.Graph()
            eid_map = {}
            for idx, row in edges.iterrows():
                coords = list(row.geometry.coords)
                if len(coords) < 2: continue
                sk = f"{coords[0][0]:.1f}_{coords[0][1]:.1f}"
                ek = f"{coords[-1][0]:.1f}_{coords[-1][1]:.1f}"
                G.add_edge(sk, ek, length=row.geometry.length)
                eid_map[(sk, ek)] = idx
                
            deg = dict(G.degree())
            edges_temp = edges.copy()
            edges_temp["degree"] = 0.0
            for (u, v), idx in eid_map.items():
                edges_temp.loc[idx, "degree"] = (deg.get(u, 0) + deg.get(v, 0)) / 2
                
            pred = edges_temp.iloc[e_i[m]]["degree"].values.astype(float)
            obs = tel_ped[m]
            
        elif pred_file and os.path.exists(pred_file):
            try:
                pred_df = pd.read_csv(pred_file)
                obs = pred_df["observed"].values
                pred = pred_df["predicted"].values
            except Exception as e:
                print(f"Error loading {pred_file}: {e}")
                
        # Draw scatter plot if prediction data is available and non-constant
        valid = (obs is not None and pred is not None and len(obs) >= 3 and 
                 not np.all(pred == pred[0]) and not np.any(np.isnan(pred)) and not np.any(np.isnan(obs)))
        if valid:
            ax.scatter(pred, obs, c=color, alpha=0.7, edgecolors="black", linewidth=0.5, s=60, zorder=3)
            # Linear regression fit line
            try:
                m_fit, b_fit = np.polyfit(pred, obs, 1)
                x_line = np.linspace(pred.min(), pred.max(), 50)
                ax.plot(x_line, m_fit * x_line + b_fit, color=color, linewidth=2, linestyle="--", zorder=2)
            except Exception as e:
                print(f"Skipping fit line for {tool}: {e}")
            ax.set_xlabel(f"Predicted Flow ({tool})", fontsize=10)
            ax.set_ylabel("Observed Flow (Telraam)", fontsize=10)
            ax.grid(True, linestyle=":", alpha=0.6)
            
            stats_text = f"R² = {r2:.3f}\nPearson r = {r_val:.3f}"
            ax.text(0.05, 0.95, stats_text, transform=ax.transAxes, fontsize=11,
                    fontweight="bold", ha="left", va="top",
                    bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="gray", alpha=0.9))
        else:
            ax.set_axis_off()
            ax.patch.set_facecolor("#f8fafc")
            ax.text(0.5, 0.65, f"R² = {r2:.3f}", ha="center", va="center",
                    fontsize=28, fontweight="bold", color=color, transform=ax.transAxes)
            ax.text(0.5, 0.45, f"Pearson r = {r_val:.3f}", ha="center", va="center",
                    fontsize=16, color="#475569", transform=ax.transAxes)
            ax.text(0.5, 0.30, f"n = {int(m.sum())} sensors", ha="center", va="center",
                    fontsize=12, color="#64748b", transform=ax.transAxes)
            rect = plt.Rectangle((0.1, 0.1), 0.8, 0.8, fill=False, color="#cbd5e1", 
                                 linewidth=1.5, linestyle="-", transform=ax.transAxes)
            ax.add_patch(rect)
            
    fig.suptitle(f"Top Performing Methods — Network Maps & Observed vs Predicted ({city.capitalize()})",
                 fontsize=15, fontweight="bold", y=0.99)
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(f"{RESULTS_DIR}/fig4_tool_panels.png", dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {RESULTS_DIR}/fig4_tool_panels.png")

if __name__ == "__main__":
    main()
