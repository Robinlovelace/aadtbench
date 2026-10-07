#!/usr/bin/env python3
"""Fetch Telraam cyclist + car ground truth for the 38 Leuven segments and
write data/leuven_telraam_cyclists_4326.geojson and
data/leuven_telraam_cars_4326.geojson, matching the convention of
data/leuven_telraam_pedestrians_4326.geojson:

  - same 38 sensor_ids (strip "LEUVEN_" prefix -> Telraam API segment id)
  - same geometry points (reused verbatim from the pedestrians file)
  - 7-day window ending today 00:00 UTC
  - avg_daily_X  = round(sum(hourly_X)/num_days, 2)  with num_days = num_hours/24
  - total_X_7d   = sum(hourly_X)  (full float precision, like the pedestrians file)

The Telraam per-hour report returns car/bike/pedestrian fields in one call, so
one request per segment serves both new files.

Usage:  PYTHONPATH=. .venv/bin/python scripts/fetch_telraam_modes.py --city leuven
"""
import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import geopandas as gpd
import pandas as pd
import requests

API_URL = "https://telraam-api.net/v1/reports/traffic"
ENV_FILE = os.path.expanduser("~/.srt/gemini.env")
OUT_FIELDS = {"cycle": ("avg_daily_cyclists", "total_cyclists_7d"),
              "drive": ("avg_daily_cars", "total_cars_7d")}


def get_token():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("TELRAAM_TOKEN="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(f"TELRAAM_TOKEN not found in {ENV_FILE}")


def fetch_segment(session, token, seg_id, time_start, time_end, max_retries=6):
    payload = {
        "id": seg_id,
        "time_start": time_start,
        "time_end": time_end,
        "level": "segments",
        "format": "per-hour",
    }
    headers = {"X-Api-Key": token, "Content-Type": "application/json"}
    for attempt in range(max_retries):
        try:
            r = session.post(API_URL, json=payload, headers=headers, timeout=30)
        except requests.RequestException as e:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code != 200:
            time.sleep(2 * (attempt + 1))
            continue
        data = r.json()
        if not data.get("report"):
            # Empty report: transient on Telraam's side -- retry with backoff.
            time.sleep(4 * (attempt + 1))
            continue
        return data
    raise RuntimeError(f"segment {seg_id}: API failed after {max_retries} attempts")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="leuven")
    parser.add_argument("--sensors", default="data/leuven_telraam_pedestrians_4326.geojson")
    args = parser.parse_args()

    token = get_token()
    ped = gpd.read_file(args.sensors)
    n = len(ped)
    # Reuse the pedestrians geometry so all three mode files share identical points.
    geoms = ped.geometry

    now = datetime.now(timezone.utc)
    time_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_start = time_end - timedelta(days=7)
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    rows_cycle, rows_drive = [], []
    skipped = []
    session = requests.Session()
    for i, row in ped.iterrows():
        sensor_id = row["sensor_id"]
        m = re.match(r"LEUVEN_(\d+)$", sensor_id)
        if not m:
            print(f"[skip] non-Leuven sensor id: {sensor_id}")
            skipped.append(sensor_id)
            continue
        api_id = int(m.group(1))
        try:
            data = fetch_segment(session, token, api_id,
                                 time_start.strftime(fmt), time_end.strftime(fmt))
        except RuntimeError as e:
            # e.g. retired segment: API returns empty reports for every window.
            print(f"[warn] {sensor_id}: {e}")
            skipped.append(sensor_id)
            continue
        entries = data.get("report", [])
        if not entries:
            print(f"[warn] {sensor_id}: empty report")
            continue
        df = pd.DataFrame(entries)
        num_hours = len(df)
        num_days = num_hours / 24.0
        bike_sum = float(df["bike"].sum())
        car_sum = float(df["car"].sum())
        rows_cycle.append({
            "sensor_id": sensor_id,
            "avg_daily_cyclists": round(bike_sum / num_days, 2),
            "total_cyclists_7d": bike_sum,
        })
        rows_drive.append({
            "sensor_id": sensor_id,
            "avg_daily_cars": round(car_sum / num_days, 2),
            "total_cars_7d": car_sum,
        })
        print(f"[{i+1}/{n}] {sensor_id}: hours={num_hours} "
              f"bike={bike_sum:.0f} car={car_sum:.0f}", flush=True)
        time.sleep(1.1)  # rate limit: 1 req/s

    for mode, rows, out in [
        ("cycle", rows_cycle, "data/leuven_telraam_cyclists_4326.geojson"),
        ("drive", rows_drive, "data/leuven_telraam_cars_4326.geojson"),
    ]:
        gdf = gpd.GeoDataFrame(rows, geometry=geoms[:len(rows)], crs="EPSG:4326")
        gdf.to_file(out, driver="GeoJSON")
        print(f"wrote {out}: {len(gdf)} rows")
    print(f"skipped (no API data): {skipped}")


if __name__ == "__main__":
    main()
