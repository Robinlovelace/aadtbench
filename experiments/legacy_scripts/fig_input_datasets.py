#!/usr/bin/env python3
"""Generate input datasets figure with 4 panels and a larger bounding box."""
import os
import sys
import argparse
import geopandas as gpd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from scripts.config import get_path, get_city_config

def main():
    parser = argparse.ArgumentParser(description="Generate input datasets plot for a city.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven)")
    args = parser.parse_args()
    
    city = args.city
    cfg = get_city_config(city)
    
    data_dir = "data"
    
    edges = gpd.read_file(get_path(cfg["edges_file"]))
    tel = gpd.read_file(get_path(cfg["sensors_file"]))
    wp = gpd.read_file(get_path(cfg["origins_file"]))
    att = gpd.read_file(get_path(cfg["destinations_file"]))
    
    # Check if optional segments file exists
    seg_file = get_path(f"{data_dir}/{city}_telraam_segments.geojson")
    if os.path.exists(seg_file):
        seg = gpd.read_file(seg_file)
    else:
        seg = gpd.GeoDataFrame()
        
    edges_wm = edges.to_crs(3857)
    tel_wm = tel.to_crs(3857)
    wp_wm = wp.to_crs(3857)
    att_wm = att.to_crs(3857)
    
    # Set bounding box to the entire walk network to show the full study area context
    xmin, ymin, xmax, ymax = edges_wm.total_bounds
    xmin, xmax = xmin - 500, xmax + 500
    ymin, ymax = ymin - 500, ymax + 500
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 14))
    axes = axes.flatten()
    
    # (a) Walk network & monitored segments
    edges_wm.plot(ax=axes[0], linewidth=0.4, color='#2c3e50', alpha=0.5)
    if len(seg) > 0:
        seg_wm = seg.to_crs(3857)
        seg_wm.plot(ax=axes[0], linewidth=1.2, color='#1f77b4', alpha=0.8)
    axes[0].set_title(f"(a) Walk network & monitored segments — {len(edges):,} edges", fontsize=12, fontweight='bold')
    axes[0].set_axis_off()
    
    # (b) Telraam validation sensors
    edges_wm.plot(ax=axes[1], linewidth=0.3, color='gray', alpha=0.4)
    tel_wm.plot(ax=axes[1], markersize=tel_wm['avg_daily_pedestrians'] / 15 + 10,
                color='#d62728', alpha=0.8, edgecolor='black', linewidth=0.5)
    for _, row in tel_wm.iterrows():
        axes[1].annotate(f"{row['avg_daily_pedestrians']:.0f}", (row.geometry.x, row.geometry.y),
                   fontsize=6, ha='left', va='bottom', alpha=0.7)
    axes[1].set_title(f"(b) Telraam sensors — {len(tel)} sensors, avg {tel['avg_daily_pedestrians'].mean():.0f}/day", fontsize=12, fontweight='bold')
    axes[1].set_axis_off()
    
    # (c) WorldPop origins
    edges_wm.plot(ax=axes[2], linewidth=0.3, color='gray', alpha=0.4)
    sc = axes[2].scatter(wp_wm.geometry.x, wp_wm.geometry.y, c=wp['population'],
                         cmap='viridis', s=8, alpha=0.7, edgecolors='none')
    plt.colorbar(sc, ax=axes[2], label='Population', shrink=0.7)
    axes[2].set_title(f"(c) WorldPop origins — {len(wp)} cells, total {wp['population'].sum():.0f}", fontsize=12, fontweight='bold')
    axes[2].set_axis_off()
    
    # (d) OSM Attractors
    edges_wm.plot(ax=axes[3], linewidth=0.3, color='gray', alpha=0.4)
    att_wm.plot(ax=axes[3], markersize=att_wm['attractor_weight'] * 0.8 + 8,
                color='#2ca02c', alpha=0.7, edgecolor='black', linewidth=0.4)
    axes[3].set_title(f"(d) OSM Attractors — {len(att)} POIs, weight sum {att['attractor_weight'].sum():.0f}", fontsize=12, fontweight='bold')
    axes[3].set_axis_off()
    
    for ax in axes:
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        
    plt.tight_layout()
    os.makedirs('results', exist_ok=True)
    out_img = f"results/{city}_input_datasets.png"
    plt.savefig(out_img, dpi=300, bbox_inches='tight')
    print(f"Saved {out_img}")

if __name__ == "__main__":
    main()
