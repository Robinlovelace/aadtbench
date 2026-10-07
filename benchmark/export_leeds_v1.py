#!/usr/bin/env python3
"""Convert the legacy leeds-v1 case (v0.1 tables) to the v0.2 layout.

Reads cases/leeds-v1 (observations, observation_crosswalk, segments) and the
v0.1 data files. Writes network.parquet, sites.csv, crosswalk.csv and inputs/.
The v0.1 matches are kept with rule `legacy_v01_nearest`. Mode is `motor`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import yaml

from benchmark.export_multimode_case import (
    CITIES, DISC_RADIUS_M, HIGHWAY_TO_CLASS, assign_folds,
)

CRS = 27700
DEFAULT_DATA_DIR = "data"


def split_observations(crosswalk, held_out_fraction=0.25, seed=42):
    """The v0.1 legacy split: a seeded shuffle puts 25 percent of count points in held_out."""
    import numpy as np
    obs_ids = np.sort(crosswalk["observation_id"].astype(str).unique())
    shuffled = np.random.RandomState(seed).permutation(obs_ids)
    held = set(shuffled[:max(1, int(round(len(shuffled) * held_out_fraction)))])
    return pd.Series({o: ("held_out" if o in held else "dev") for o in obs_ids}, name="split")


def segment_id(u, v, key) -> str:
    return f"{min(int(u), int(v))}:{max(int(u), int(v))}:{int(key)}"


def orient_to_nodes(e: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reverse stored geometries so the first point is at node u.

    Some v0.1 edge geometries are stored against their u to v direction. Node
    positions are estimated as the median of the end points, and each edge is
    flipped if its ends fit the swapped assignment better. Repeats to converge.
    """
    g = e.geometry.values.copy()
    p0 = shapely.get_coordinates(shapely.get_point(g, 0))
    p1 = shapely.get_coordinates(shapely.get_point(g, -1))
    u, v = e["u"].values, e["v"].values
    flip = np.zeros(len(e), bool)
    for _ in range(10):
        a = np.where(flip[:, None], p1, p0)
        b = np.where(flip[:, None], p0, p1)
        df = pd.DataFrame({"n": np.r_[u, v], "x": np.r_[a[:, 0], b[:, 0]], "y": np.r_[a[:, 1], b[:, 1]]})
        med = df.groupby("n")[["x", "y"]].median()
        mu, mv = med.loc[u].values, med.loc[v].values
        keep = np.hypot(*(p0 - mu).T) + np.hypot(*(p1 - mv).T)
        swap = np.hypot(*(p1 - mu).T) + np.hypot(*(p0 - mv).T)
        new = swap < keep
        if (new == flip).all():
            break
        flip = new
    g[flip] = shapely.reverse(g[flip])
    e = e.copy()
    e["geometry"] = g
    return e


def build_network(data: Path, segments: pd.DataFrame) -> gpd.GeoDataFrame:
    e = gpd.read_file(data / "leeds_drive_edges.gpkg").to_crs(CRS)
    e = orient_to_nodes(e)
    e["segment_id"] = [segment_id(r.u, r.v, r.key) for r in e.itertuples()]
    e = e.reset_index(names="source_edge_index").sort_values("source_edge_index")
    first = e.drop_duplicates("segment_id").set_index("segment_id")
    seg = segments.set_index("segment_id").join(first[["highway", "u", "v", "geometry"]],
                                               rsuffix="_edge")
    # orient each geometry from u (smaller id) to v (larger id)
    flip = seg["u_edge"] > seg["v_edge"]
    geoms = seg["geometry"].values.copy()
    geoms[flip.values] = shapely.reverse(geoms[flip.values])
    # the legacy graph has no one-way edges: every non-loop segment has two directed edges
    # and the only single-edge segments are loops (u == v), so all are "both"
    two = (seg["directed_edge_count"] >= 2) | (seg["u_edge"] == seg["v_edge"])
    # a single directed edge runs u_edge to v_edge, forward if that is smaller to larger id
    one_dir = np.where(seg["u_edge"] <= seg["v_edge"], "forward", "backward")
    out = gpd.GeoDataFrame({
        "segment_id": seg.index.astype(str),
        "u": seg["u"].astype("int64").values, "v": seg["v"].astype("int64").values,
        "length_m": shapely.length(geoms).round(2),
        "road_class": seg["highway"].map(HIGHWAY_TO_CLASS).fillna("other").values,
        "highway": seg["highway"].values,
        "name": "",
        "allow_walking": False, "allow_cycling": False, "allow_car": True, "allow_heavy": True,
        "dir_car": np.where(two, "both", one_dir),
        "dir_cycling": "both",
        "pair_segment": "",
    }, geometry=geoms, crs=CRS)
    return out


def build_inputs(data: Path, out: Path) -> dict:
    inp = out / "inputs"
    inp.mkdir(parents=True, exist_ok=True)
    pop = gpd.read_file(data / "leeds_worldpop_origins.geojson").to_crs(CRS)
    pd.DataFrame({"x": pop.geometry.x.round(1), "y": pop.geometry.y.round(1),
                  "weight": pop["population"].astype(float)}).to_parquet(inp / "population.parquet", index=False)
    poi = gpd.read_file(data / "leeds_attractors.geojson").to_crs(CRS)
    pd.DataFrame({"x": poi.geometry.x.round(1), "y": poi.geometry.y.round(1),
                  "weight": poi["attractor_weight"].astype(float),
                  "type": poi["category"].astype(str)}).to_parquet(inp / "pois.parquet", index=False)
    z = gpd.read_file(data / "leeds_gravity_zones.geojson").to_crs(CRS)
    zz = gpd.GeoDataFrame({"zone_id": z["geo_code"].astype(str), "population": z["population"],
                           "attractors": z["attractor_weight"]}, geometry=z.geometry.values, crs=CRS)
    zz.to_parquet(inp / "zones.parquet", index=False)
    od = pd.read_csv(data / "leeds_gravity_od.csv")
    pd.DataFrame({"o_zone": od["geo_code1"].astype(str), "d_zone": od["geo_code2"].astype(str),
                  "mode": "motor", "trips": od["all"].astype("float32")}).to_parquet(
        inp / "od_synthetic.parquet", index=False)
    pct = pd.read_csv(data / "leeds_pct_od.csv")
    pct = pct[pct["car_driver"] > 0]
    pd.DataFrame({"o_zone": pct["geo_code1"].astype(str), "d_zone": pct["geo_code2"].astype(str),
                  "mode": "motor", "trips": pct["car_driver"].astype("float32")}).to_parquet(
        inp / "od_observed.parquet", index=False)
    m = gpd.read_file(data / "leeds_pct_zones_msoa.geojson").to_crs(CRS)
    gpd.GeoDataFrame({"zone_id": m["geo_code"].astype(str), "name": m["geo_name"]},
                     geometry=m.geometry.values, crs=CRS).to_parquet(inp / "zones_observed.parquet", index=False)
    return dict(population_points=len(pop), poi_points=len(poi), zones=len(zz), od_synthetic=len(od),
                od_observed=len(pct), observed_zones=len(m))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-dir", default="cases/leeds-v1")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--out", default="build/cases/v0.2.0/leeds-v1")
    ap.add_argument("--version", default="0.2.0")
    a = ap.parse_args()
    legacy, data, out = Path(a.legacy_dir), Path(a.data_dir), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    segments = pd.read_csv(legacy / "segments.csv")
    obs = pd.read_csv(legacy / "observations.csv")
    xw = pd.read_csv(legacy / "observation_crosswalk.csv")

    net = build_network(data, segments)
    net.to_parquet(out / "network.parquet", index=False)

    pts = gpd.read_file(data / "leeds_dft_aadt_27700.geojson").to_crs(CRS)
    pts["site_id"] = pts["count_point_id"].astype(str)
    obs["site_id"] = obs["observation_id"].astype(str)
    s = obs.merge(pts[["site_id", "geometry", "longitude", "latitude"]], on="site_id", how="left")
    sites = pd.DataFrame({
        "site_id": s.site_id, "mode": "motor", "value": s.observed_aadt_two_way,
        "source": "dft_aadf", "licence": "OGL-UK-3.0", "method": "aadf_published", "n_days": "",
        "x": [g.x for g in s.geometry], "y": [g.y for g in s.geometry],
        "lon": s.longitude, "lat": s.latitude,
    })
    sites = assign_folds(sites)
    split = split_observations(xw.assign(observation_id=xw["observation_id"].astype(str)))
    sites["legacy_split"] = sites.site_id.map(split).fillna("")
    sites.to_csv(out / "sites.csv", index=False)

    cw = pd.DataFrame({"site_id": xw["observation_id"].astype(str), "mode": "motor",
                       "segment_id": xw["segment_id"], "weight": 1.0,
                       "dist_m": xw["match_distance_m"].round(2), "rule": "legacy_v01_nearest"})
    cw.to_csv(out / "crosswalk.csv", index=False)

    istats = build_inputs(data, out)
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    size = sum((out / f).stat().st_size for f in files)

    # Update the small case.yaml in git.
    cy = legacy / "case.yaml"
    meta = yaml.safe_load(cy.read_text())
    meta["version"] = "0.2.0"
    meta["benchmark_version"] = a.version
    meta["layout"] = "v0.2"
    c = CITIES["leeds"]
    meta.update({"crs": "EPSG:27700", "centre_lon": c["lon"], "centre_lat": c["lat"],
                 "radius_m": DISC_RADIUS_M, "modes": ["motor"],
                 "sources": [{"source": "dft_aadf", "licence": "OGL-UK-3.0",
                              "licence_text": "DfT road traffic statistics AADF, OGL v3",
                              "method": "aadf_published", "n_sites": int(len(sites))}],
                 "network_licence": "ODbL-1.0 (OpenStreetMap)",
                 "split": {"group_cell_m": 3000.0, "folds": 5, "seed": 42,
                           "legacy": "legacy_split column in sites.csv, 49 held out"},
                 "input_tiers": ["T0_network", "T1_open_covariates", "T2_synthetic_od", "T3_observed_od"],
                 "files": files, "data_size_bytes": size})
    cy.write_text(yaml.safe_dump(meta, sort_keys=False))
    print(json.dumps(dict(links=len(net), km=round(float(net.length_m.sum() / 1000), 1),
                          sites=len(sites), crosswalk=len(cw),
                          legacy_split=sites.legacy_split.value_counts().to_dict(),
                          dir_car=net.dir_car.value_counts().to_dict(), inputs=istats,
                          size_mb=round(size / 1e6, 1))))


if __name__ == "__main__":
    main()
