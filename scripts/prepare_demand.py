#!/usr/bin/env python3
"""
Download WorldPop population data and fetch OSM POI attractors for a city
to create research-backed trip origins and destinations.
"""
import os
import sys
import argparse
import requests
import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from shapely.geometry import Point

from scripts.config import get_path, get_city_config, TEST_MODE

DATA_DIR = "data"
CACHE_DIR = "cache"
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

def download_worldpop(url, local_filename):
    local_path = os.path.join(CACHE_DIR, local_filename)
    if os.path.exists(local_path):
        print(f"WorldPop file already exists at {local_path}")
        return local_path
    
    print(f"Downloading WorldPop population grid from {url}...")
    r = requests.get(url, stream=True)
    r.raise_for_status()
    total_size = int(r.headers.get('content-length', 0))
    
    block_size = 1024 * 1024  # 1MB
    downloaded = 0
    with open(local_path, "wb") as f:
        for data in r.iter_content(block_size):
            f.write(data)
            downloaded += len(data)
            if total_size > 0:
                percent = (downloaded / total_size) * 100
                print(f"  Downloaded: {downloaded / (1024*1024):.1f} MB / {total_size / (1024*1024):.1f} MB ({percent:.1f}%)", end="\r")
    print("\nDownload complete.")
    return local_path

def process_origins(tif_path, bbox, output_path, agg_factor=1):
    """Extract non-zero WorldPop population cells within bbox as points.

    agg_factor > 1 sums population over agg_factor x agg_factor blocks of
    raw ~100m WorldPop cells before emitting a point per block (at the block
    centroid) -- a standard resolution-coarsening step for bounding boxes
    large enough that per-cell (~100m) origin injection is intractable for
    the downstream gravity-model tools (e.g. Leeds' 10km-buffer bbox is ~25x
    the area of Leuven's, so the raw cell count would be ~25x higher too).
    """
    print("Processing WorldPop population origins...")

    with rasterio.open(tif_path) as src:
        left, bottom, right, top = bbox
        window = from_bounds(left, bottom, right, top, transform=src.transform)
        data = src.read(1, window=window)
        win_transform = src.window_transform(window)
        nodata = src.nodata

        if agg_factor > 1:
            rows, cols = data.shape
            pad_r = (-rows) % agg_factor
            pad_c = (-cols) % agg_factor
            valid = (data != nodata) & (data > 0)
            data_clean = np.where(valid, data, 0.0)
            data_pad = np.pad(data_clean, ((0, pad_r), (0, pad_c)))
            block_sum = data_pad.reshape(
                data_pad.shape[0] // agg_factor, agg_factor,
                data_pad.shape[1] // agg_factor, agg_factor,
            ).sum(axis=(1, 3))
            data = block_sum
            nodata = 0.0
            # Block (r, c) covers raw cells [r*f:(r+1)*f, c*f:(c+1)*f]; use its
            # centroid (r*f + f/2, c*f + f/2) as the representative point.

        points = []
        rows, cols = data.shape
        for r in range(rows):
            for c in range(cols):
                val = data[r, c]
                if val > 0 and val != nodata:
                    if agg_factor > 1:
                        lon, lat = win_transform * (c * agg_factor + agg_factor / 2, r * agg_factor + agg_factor / 2)
                    else:
                        lon, lat = win_transform * (c + 0.5, r + 0.5)
                    points.append({
                        "geometry": Point(lon, lat),
                        "properties": {"population": float(val)}
                    })

        if not points:
            print("ERROR: No population points extracted!")
            sys.exit(1)

        gdf = gpd.GeoDataFrame(
            [p["properties"] for p in points],
            geometry=[p["geometry"] for p in points],
            crs="EPSG:4326"
        )

        gdf.to_file(output_path, driver="GeoJSON")
        print(f"Saved {len(gdf)} population origin cells to {output_path}"
              + (f" (aggregated {agg_factor}x{agg_factor})" if agg_factor > 1 else ""))

def fetch_attractors(overpass_bbox, output_path, city_name):
    print(f"Fetching {city_name} trip attractors from OSM Overpass API...")
    
    # Overpass query to find key attractors
    lat_min, lon_min, lat_max, lon_max = overpass_bbox
    overpass_query = f"""
    [out:json][timeout:90];
    (
      node["amenity"~"university|hospital|school|cafe|restaurant|bar"]({lat_min}, {lon_min}, {lat_max}, {lon_max});
      way["amenity"~"university|hospital|school"]({lat_min}, {lon_min}, {lat_max}, {lon_max});
      node["shop"~"supermarket|mall|clothes|department_store|bakery"]({lat_min}, {lon_min}, {lat_max}, {lon_max});
      node["railway"="station"]({lat_min}, {lon_min}, {lat_max}, {lon_max});
    );
    out center;
    """
    
    endpoints = [
        "https://lz4.overpass-api.de/api/interpreter",
        "https://z.overpass-api.de/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"
    ]
    
    data = None
    headers = {"User-Agent": "Antigravity-CenBench-Research/1.0 (robin@example.com)"}
    
    for ep in endpoints:
        try:
            print(f"Trying Overpass endpoint: {ep}...")
            r = requests.post(ep, data={"data": overpass_query}, headers=headers, timeout=120)
            r.raise_for_status()
            data = r.json()
            print("Successfully fetched from Overpass.")
            break
        except Exception as e:
            print(f"Failed to fetch from {ep}: {e}")
            
    if data is None:
        print("Using fallback synthetic attractors...")
        create_synthetic_attractors(output_path)
        return

    elements = data.get("elements", [])
    print(f"Retrieved {len(elements)} elements from OSM.")
    
    features = []
    for el in elements:
        if el["type"] == "node":
            lon, lat = el["lon"], el["lat"]
        elif "center" in el:
            lon, lat = el["center"]["lon"], el["center"]["lat"]
        else:
            continue
            
        tags = el.get("tags", {})
        name = tags.get("name", "Unnamed Attractor")
        amenity = tags.get("amenity", "")
        shop = tags.get("shop", "")
        railway = tags.get("railway", "")
        
        weight = 5.0
        category = "retail_dining"
        
        if railway == "station":
            weight = 100.0
            category = "transit_hub"
        elif amenity == "hospital":
            weight = 50.0
            category = "hospital"
        elif amenity == "university":
            weight = 30.0
            category = "university"
        elif amenity == "school":
            weight = 20.0
            category = "school"
        elif shop == "supermarket" or shop == "mall":
            weight = 15.0
            category = "grocery_mall"
            
        features.append({
            "type": "Feature",
            "properties": {
                "name": name,
                "category": category,
                "attractor_weight": weight
            },
            "geometry": {"type": "Point", "coordinates": [lon, lat]}
        })
        
    if not features:
        print("No features extracted from OSM, creating synthetic fallbacks...")
        create_synthetic_attractors(output_path)
        return
        
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    gdf.to_file(output_path, driver="GeoJSON")
    print(f"Saved {len(gdf)} attractors to {output_path}")

def create_synthetic_attractors(output_path):
    synthetic = [
        {"name": "Leuven Train Station", "category": "transit_hub", "attractor_weight": 100.0, "lon": 4.7150, "lat": 50.8810},
        {"name": "KU Leuven Central Campus", "category": "university", "attractor_weight": 35.0, "lon": 4.7000, "lat": 50.8780},
        {"name": "KU Leuven Arenberg Campus", "category": "university", "attractor_weight": 35.0, "lon": 4.6850, "lat": 50.8630},
        {"name": "UZ Leuven Hospital", "category": "hospital", "attractor_weight": 50.0, "lon": 4.6780, "lat": 50.8870},
        {"name": "Oude Markt (Dining & Bars)", "category": "retail_dining", "attractor_weight": 25.0, "lon": 4.6980, "lat": 50.8790},
        {"name": "Stella Artois Brewery / Vaartkom", "category": "retail_dining", "attractor_weight": 15.0, "lon": 4.7060, "lat": 50.8880},
    ]
    features = []
    for s in synthetic:
        features.append({
            "type": "Feature",
            "properties": {"name": s["name"], "category": s["category"], "attractor_weight": s["attractor_weight"]},
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]}
        })
    gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
    gdf.to_file(output_path, driver="GeoJSON")
    print(f"Saved {len(gdf)} synthetic fallback attractors to {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Prepare demand datasets for a city.")
    parser.add_argument("--city", default="leuven", help="Name of the city to prepare (e.g. leuven)")
    args = parser.parse_args()
    
    city = args.city
    cfg = get_city_config(city)
    
    origins_file = get_path(cfg["origins_file"])
    destinations_file = get_path(cfg["destinations_file"])
    
    if TEST_MODE:
        import shutil
        print(f"TEST_MODE is active: copying pre-clipped test demand files for {city}...")
        raw_origins = cfg["origins_file"]
        raw_destinations = cfg["destinations_file"]
        
        test_origins = os.path.join(os.path.dirname(raw_origins), f"test_{os.path.basename(raw_origins)}")
        test_destinations = os.path.join(os.path.dirname(raw_destinations), f"test_{os.path.basename(raw_destinations)}")
        
        shutil.copy(test_origins, raw_origins)
        shutil.copy(test_destinations, raw_destinations)
        print("Done copying test demand files.")
        return

    # Check if WorldPop URL exists for this city
    if "worldpop_url" in cfg and "worldpop_local_tif" in cfg:
        tif_path = download_worldpop(cfg["worldpop_url"], cfg["worldpop_local_tif"])
        process_origins(tif_path, cfg["bbox"], origins_file, agg_factor=cfg.get("origins_agg_factor", 1))
    else:
        print(f"WorldPop URL not configured for {city}, skipping origins preparation.")
        
    if "overpass_bbox" in cfg:
        fetch_attractors(cfg["overpass_bbox"], destinations_file, city)
    else:
        print(f"Overpass BBOX not configured for {city}, skipping attractors preparation.")
        
    print(f"Demand data preparation for {city} completed successfully!")

if __name__ == "__main__":
    main()
