#!/usr/bin/env python3
"""Build sites, folds and inputs for a new case from open, already processed tables.

In:  ``cases/<id>/case.yaml`` (centre, CRS, radius, modes, split, ``mode_map``),
     a counts table (``site_id, source, mode, lon, lat, aadt, n_days, method,
     kind``, optional ``bearing`` for junction arms) and a layers directory
     (``residents.parquet`` and ``poi_*.parquet``: points ``lon, lat, weight``).
Out: ``sites.csv`` and ``inputs/`` in ``--out``. Then run
     ``benchmark/rebuild_case_osm.py --sites-from <out>`` for the network and
     crosswalk.

Rules: sources and licences from ``benchmark/licences.py`` only. Sites inside
the disc. Junction arm counts (``kind`` junction_movement) give the flow
entering the junction from that arm, so the two-way value is twice that
(daily flows are taken as symmetric, a documented assumption). Groups are
square cells of ``split.group_cell_m``, assigned to folds by a seeded shuffle.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from benchmark.build_inputs import build_zones, synthetic_od
from benchmark.licences import NON_COMMERCIAL_SOURCES, REVIEWED_SOURCES

MODES = ("walking", "cycling", "car", "heavy", "motor")


def project(df: pd.DataFrame, crs: int) -> tuple[np.ndarray, np.ndarray]:
    g = gpd.GeoSeries(gpd.points_from_xy(df.lon, df.lat), crs=4326).to_crs(crs)
    return g.x.values, g.y.values


def assign_folds(sites: pd.DataFrame, cell_m: float, folds: int = 5, seed: int = 42) -> pd.DataFrame:
    gx, gy = np.floor(sites.x / cell_m).astype(int), np.floor(sites.y / cell_m).astype(int)
    sites["group_id"] = "g" + gx.astype(str) + "_" + gy.astype(str)
    groups = np.array(sorted(sites.group_id.unique()))
    order = np.random.default_rng(seed).permutation(len(groups))
    sites["fold"] = sites.group_id.map({groups[g]: int(r % folds) for r, g in enumerate(order)})
    return sites


def points(path: Path, crs: int, cx: float, cy: float, r: float) -> pd.DataFrame:
    d = pd.read_parquet(path)
    x, y = project(d, crs)
    out = pd.DataFrame({"x": x, "y": y, "weight": d["weight"].astype(float).values})
    return out[np.hypot(out.x - cx, out.y - cy) <= r].reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--case", required=True)
    ap.add_argument("--counts", required=True, type=Path)
    ap.add_argument("--layers", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    cfg = yaml.safe_load((Path("cases") / a.case / "case.yaml").read_text())
    crs = int(str(cfg["crs"]).split(":")[-1])
    cx, cy = (v[0] for v in project(pd.DataFrame({"lon": [cfg["centre_lon"]], "lat": [cfg["centre_lat"]]}), crs))
    r = float(cfg["radius_m"])
    allowed = {**REVIEWED_SOURCES, **(NON_COMMERCIAL_SOURCES if cfg.get("licence_class") == "non_commercial" else {})}

    c = pd.read_parquet(a.counts)
    c["mode"] = c["mode"].replace(cfg.get("mode_map", {}))
    c = c[c.source.isin(allowed) & c["mode"].isin(cfg["modes"]) & (c.aadt > 0)].copy()
    c["x"], c["y"] = project(c, crs)
    c = c[np.hypot(c.x - cx, c.y - cy) <= r]
    arm = c["kind"].eq("junction_movement")
    c.loc[arm, "aadt"] *= 2.0
    sites = pd.DataFrame({
        "site_id": c.site_id.astype(str), "mode": c["mode"], "value": c.aadt.round(3), "source": c.source,
        "licence": c.source.map(lambda s: allowed[s]["licence"]), "method": c.method, "n_days": c.n_days,
        "x": c.x.round(2), "y": c.y.round(2), "lon": c.lon, "lat": c.lat,
        "bearing": c["bearing"] if "bearing" in c else np.nan,
    })
    sites = assign_folds(sites.reset_index(drop=True), float(cfg["split"]["group_cell_m"]),
                         int(cfg["split"]["folds"]), int(cfg["split"]["seed"]))
    a.out.mkdir(parents=True, exist_ok=True)
    sites.to_csv(a.out / "sites.csv", index=False)

    inp = a.out / "inputs"
    inp.mkdir(exist_ok=True)
    extent = r + float(cfg.get("margin_m", 0) or 0)
    pop = points(a.layers / "residents.parquet", crs, cx, cy, extent)
    pois = pd.concat([points(f, crs, cx, cy, extent).assign(type=f.stem.removeprefix("poi_"))
                      for f in sorted(a.layers.glob("poi_*.parquet")) if f.stem != "poi_all"], ignore_index=True)
    pop.to_parquet(inp / "population.parquet", index=False)
    pois.to_parquet(inp / "pois.parquet", index=False)
    zone_m = float(cfg.get("zone_m", 1000.0) or 1000.0)
    zones = build_zones(pop, pois, cx, cy, extent, cell_m=zone_m)
    gpd.GeoDataFrame(zones[["zone_id", "population", "attractors"]], geometry=zones["geometry"].values,
                     crs=crs).to_parquet(inp / "zones.parquet", index=False)
    synthetic_od(zones, cfg["modes"], intrazonal_m=zone_m / 2).to_parquet(inp / "od_synthetic.parquet", index=False)
    print(sites.groupby(["source", "mode"]).size().to_dict(), "groups", sites.group_id.nunique())


if __name__ == "__main__":
    main()
