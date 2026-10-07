#!/usr/bin/env python3
"""
Prepare real ground-truth datasets for the Leeds/West Yorkshire case study:

1. DfT AADT (annual average daily traffic) counts for West Yorkshire local
   authorities (Leeds, Bradford, Wakefield, Kirklees, Calderdale), downloaded
   directly from the open DfT road traffic statistics dataset (OGL licensed,
   https://roadtraffic.dft.gov.uk/downloads) -> data/leeds_dft_aadt_27700.geojson
   This is standard open government data -- NOT the criticalissues IoT/WYCA
   sensor copy (that copy's reuse licensing was not verified, so it is
   deliberately not used here).

2. Real 2011 Census journey-to-work (car_driver) OD flows for West Yorkshire
   via the `pct` R package (pct::get_od + pct::get_pct_zones(geography="msoa"))
   -> data/leeds_pct_od.csv, data/leeds_pct_zones_msoa.geojson
   NOTE: geography MUST be "msoa" -- "lsoa" zone codes do not match get_od()
   output (0 matched OD pairs), a known bug documented in criticalissues.

Run:  PYTHONPATH=. .venv/bin/python scripts/prepare_leeds_ground_truth.py
"""
import os
import subprocess
import zipfile

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

CACHE_DIR = "cache"
DATA_DIR = "data"
DFT_AADF_URL = "https://storage.googleapis.com/dft-statistics/road-traffic/downloads/data-gov-uk/dft_traffic_counts_aadf.zip"
WY_LOCAL_AUTHORITIES = ["Leeds", "Bradford", "Wakefield", "Kirklees", "Calderdale"]


def download_dft_aadf():
    zip_path = os.path.join(CACHE_DIR, "dft_traffic_counts_aadf.zip")
    os.makedirs(CACHE_DIR, exist_ok=True)
    if os.path.exists(zip_path):
        print(f"[cache hit] {zip_path}")
        return zip_path
    print(f"Downloading DfT AADF counts from {DFT_AADF_URL} ...")
    r = requests.get(DFT_AADF_URL, stream=True, timeout=300)
    r.raise_for_status()
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            f.write(chunk)
    return zip_path


def prepare_aadt():
    out_path = os.path.join(DATA_DIR, "leeds_dft_aadt_27700.geojson")
    if os.path.exists(out_path):
        print(f"[skip] {out_path} already exists")
        return
    zip_path = download_dft_aadf()
    cols = ["count_point_id", "year", "local_authority_name", "road_name",
            "road_category", "road_type", "latitude", "longitude",
            "all_motor_vehicles", "pedal_cycles"]
    with zipfile.ZipFile(zip_path) as zf:
        csv_name = [n for n in zf.namelist() if n.endswith(".csv")][0]
        with zf.open(csv_name) as f:
            df = pd.read_csv(f, usecols=cols)

    df = df[df["local_authority_name"].isin(WY_LOCAL_AUTHORITIES)]
    latest_year = int(df["year"].max())
    df = df[df["year"] == latest_year]
    df = df.dropna(subset=["all_motor_vehicles", "latitude", "longitude"])
    df = df.rename(columns={"all_motor_vehicles": "aadt_all_motor_vehicles",
                             "pedal_cycles": "aadt_pedal_cycles"})

    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(xy) for xy in zip(df["longitude"], df["latitude"])],
        crs="EPSG:4326",
    ).to_crs(27700)
    os.makedirs(DATA_DIR, exist_ok=True)
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"Saved {len(gdf)} DfT AADT count points ({latest_year}, West Yorkshire) -> {out_path}")


PCT_R_SCRIPT = os.path.join(DATA_DIR, "..", "scripts", "fetch_pct_od.R")


def prepare_pct_od():
    od_out = os.path.join(DATA_DIR, "leeds_pct_od.csv")
    zones_out = os.path.join(DATA_DIR, "leeds_pct_zones_msoa.geojson")
    if os.path.exists(od_out) and os.path.exists(zones_out):
        print(f"[skip] {od_out} / {zones_out} already exist")
        return
    r_script = "scripts/fetch_pct_od.R"
    print(f"Running {r_script} to fetch pct::get_od + pct::get_pct_zones(msoa) ...")
    subprocess.run(["Rscript", r_script], check=True)


if __name__ == "__main__":
    prepare_aadt()
    prepare_pct_od()
