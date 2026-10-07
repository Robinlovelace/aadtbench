#!/usr/bin/env python3
"""Build the non-commercial `leuven-v1` case (Telraam sensors, CC BY-NC 4.0).

Example:
    PYTHONPATH=. python benchmark/export_leuven_case.py \
        --out build/cases/v0.2.0/leuven-v1

Network. The walk, cycle and drive graphs were simplified separately, so their
node ids and keys do not line up and a plain union would double count roads.
The case network is built by overlap instead:

1. Take the walk graph (reciprocal directed edges folded to one link).
2. Add cycle, then drive links that are less than 80 percent inside a 2 m
   buffer of what is already there (for example motorways).
3. `allow_<mode>` is true when at least 80 percent of a link lies inside a 2 m
   buffer of that mode's graph.
4. `dir_car` and `dir_cycling` come from the directed edges of that graph that
   run along the link. Only forward edges give `forward`, only backward edges
   give `backward`, otherwise `both`.
5. Node ids u and v come from snapping link ends to 0.5 m.
`allow_heavy` copies `allow_car` (the graphs carry no HGV access).
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
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from benchmark.build_inputs import build_zones, synthetic_od
from benchmark.crosswalk import build_crosswalk
from benchmark.export_multimode_case import (
    DISC_RADIUS_M, GROUP_CELL_M, HIGHWAY_TO_CLASS, N_FOLDS, SEED, assign_folds,
)

DEFAULT_DATA_DIR = "data"
CRS = 31370  # Belgian Lambert 72
CENTRE = (4.7010, 50.8790)  # Leuven Grote Markt, lon and lat
MODES = ["walking", "cycling", "car"]
COVER_BUFFER_M = 2.0
COVER_SHARE = 0.8
TELRAAM_LICENCE = "CC-BY-NC-4.0"
SOURCE_RULES = {"telraam": {"kind": "point", "radius_m": 50.0}}  # sensor coordinates are approximate
SENSOR_FILES = {
    "car": ("leuven_telraam_cars_4326.geojson", "avg_daily_cars"),
    "cycling": ("leuven_telraam_cyclists_4326.geojson", "avg_daily_cyclists"),
    "walking": ("leuven_telraam_pedestrians_4326.geojson", "avg_daily_pedestrians"),
}


def first_highway(h):
    s = str(h)
    if s.startswith("["):
        s = s.strip("[]").split(",")[0].strip(" '\"")
    return s


def read_graph(data: Path, mode: str) -> gpd.GeoDataFrame:
    e = gpd.read_file(data / f"leuven_{mode}_edges.gpkg").to_crs(CRS)
    e["highway"] = e["highway"].map(first_highway)
    return e


def fold_reciprocal(e: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    k = (np.minimum(e.u, e.v).astype(str) + ":" + np.maximum(e.u, e.v).astype(str) + ":" + e.key.astype(str))
    return e.assign(_k=k.values).drop_duplicates("_k").drop(columns="_k")


def coverage(lines: np.ndarray, zone) -> np.ndarray:
    """Share of each line inside the buffered union geometry `zone`."""
    inside = shapely.length(shapely.intersection(lines, zone))
    return inside / np.maximum(shapely.length(lines), 1e-9)


def direction_code(links: np.ndarray, directed: np.ndarray, tree_geoms) -> np.ndarray:
    """forward, backward or both, from directed edges that run along each link."""
    tree = shapely.STRtree(directed)
    mid = shapely.line_interpolate_point(links, 0.5, normalized=True)
    a = shapely.line_interpolate_point(links, 0.45, normalized=True)
    b = shapely.line_interpolate_point(links, 0.55, normalized=True)
    link_vec = shapely.get_coordinates(b) - shapely.get_coordinates(a)
    out = np.array(["both"] * len(links), dtype=object)
    li, ei = tree.query(mid, predicate="dwithin", distance=COVER_BUFFER_M)
    sign_fwd = np.zeros(len(links), bool)
    sign_bwd = np.zeros(len(links), bool)
    for l, ed in zip(li, ei):
        g = directed[ed]
        pos = shapely.line_locate_point(g, mid[l])
        p0 = shapely.line_interpolate_point(g, max(pos - 3.0, 0.0))
        p1 = shapely.line_interpolate_point(g, min(pos + 3.0, g.length))
        v = shapely.get_coordinates(p1)[0] - shapely.get_coordinates(p0)[0]
        n = np.linalg.norm(v) * np.linalg.norm(link_vec[l])
        if n == 0:
            continue
        cos = float(np.dot(v, link_vec[l]) / n)
        if cos > 0.7:
            sign_fwd[l] = True
        elif cos < -0.7:
            sign_bwd[l] = True
    out[sign_fwd & ~sign_bwd] = "forward"
    out[sign_bwd & ~sign_fwd] = "backward"
    return out


def build_network(data: Path):
    graphs = {m: read_graph(data, m) for m in ["walk", "cycle", "drive"]}
    base = fold_reciprocal(graphs["walk"])[["highway", "name", "ref", "geometry"]]
    parts = [base]
    union = shapely.union_all(shapely.buffer(base.geometry.values, COVER_BUFFER_M))
    for m in ["cycle", "drive"]:
        g = fold_reciprocal(graphs[m])[["highway", "name", "ref", "geometry"]]
        new = g[coverage(g.geometry.values, union) < COVER_SHARE]
        parts.append(new)
        union = shapely.union_all([union, shapely.union_all(shapely.buffer(new.geometry.values, COVER_BUFFER_M))])
    net = pd.concat(parts, ignore_index=True)
    net = gpd.GeoDataFrame(net, geometry="geometry", crs=CRS).reset_index(drop=True)
    lines = net.geometry.values
    allow = {}
    for m, col in [("walk", "allow_walking"), ("cycle", "allow_cycling"), ("drive", "allow_car")]:
        zone = shapely.union_all(shapely.buffer(graphs[m].geometry.values, COVER_BUFFER_M))
        allow[col] = coverage(lines, zone) >= COVER_SHARE
    dirs = {}
    for m, col in [("drive", "dir_car"), ("cycle", "dir_cycling")]:
        dirs[col] = direction_code(lines, graphs[m].geometry.values, None)
        dirs[col][~allow["allow_car" if m == "drive" else "allow_cycling"]] = "both"
    xy0 = shapely.get_coordinates(shapely.get_point(lines, 0))
    xy1 = shapely.get_coordinates(shapely.get_point(lines, -1))
    keys = np.round(np.vstack([xy0, xy1]) * 2).astype("int64")
    codes, _ = pd.factorize(pd.Series(list(map(tuple, keys))))
    n = len(net)
    u, v = codes[:n], codes[n:]
    nn = codes.max() + 1
    ncomp, lab = connected_components(coo_matrix((np.ones(n), (u, v)), shape=(nn, nn)), directed=False)
    sizes = np.bincount(lab[u])
    out = gpd.GeoDataFrame({
        "segment_id": [f"l{i}" for i in range(n)],
        "u": u.astype("int64"), "v": v.astype("int64"),
        "length_m": shapely.length(lines).round(2),
        "road_class": net["highway"].map(HIGHWAY_TO_CLASS).fillna("other").values,
        "highway": net["highway"].values,
        "name": net["name"].map(lambda s: s if isinstance(s, str) else "").values,
        "ref": net["ref"].map(lambda s: s if isinstance(s, str) else "").values,
        **allow, "allow_heavy": allow["allow_car"],
        **dirs, "pair_segment": "",
    }, geometry=lines, crs=CRS)
    cols = ["segment_id", "u", "v", "length_m", "road_class", "highway", "name", "ref", "allow_walking",
            "allow_cycling", "allow_car", "allow_heavy", "dir_car", "dir_cycling", "pair_segment", "geometry"]
    stats = dict(n_links=int(n), components=int(ncomp), largest_component_share=round(float(sizes.max() / n), 4),
                 km=round(float(out.length_m.sum() / 1000), 1),
                 from_walk=len(base), added_cycle_drive=int(n - len(base)),
                 allow={c: int(v.sum()) for c, v in allow.items()},
                 dir_car=pd.Series(dirs["dir_car"]).value_counts().to_dict(),
                 dir_cycling=pd.Series(dirs["dir_cycling"]).value_counts().to_dict(),
                 classes=out.road_class.value_counts().to_dict())
    return out[cols], stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", default="0.2.0")
    ap.add_argument("--case-id", default="leuven-v1")
    ap.add_argument("--case-version", default="1.0.0")
    ap.add_argument("--case-dir", default=None)
    a = ap.parse_args()
    data, out = Path(a.data_dir), Path(a.out)
    case_dir = Path(a.case_dir or f"cases/{a.case_id}")
    out.mkdir(parents=True, exist_ok=True)
    case_dir.mkdir(parents=True, exist_ok=True)
    c = gpd.GeoSeries(gpd.points_from_xy([CENTRE[0]], [CENTRE[1]]), crs=4326).to_crs(CRS)
    cx, cy = float(c.x.iloc[0]), float(c.y.iloc[0])

    net, nstats = build_network(data)
    net.to_parquet(out / "network.parquet", index=False)
    print("network", nstats["n_links"], "links, components", nstats["components"])

    rows = []
    for mode, (fname, col) in SENSOR_FILES.items():
        g = gpd.read_file(data / fname)
        p = g.to_crs(CRS)
        rows.append(pd.DataFrame({
            "site_id": g["sensor_id"].astype(str).values, "mode": mode, "aadt": g[col].astype(float).values,
            "lon": g.geometry.x.values, "lat": g.geometry.y.values,
            "x": p.geometry.x.values, "y": p.geometry.y.values}))
    s = pd.concat(rows, ignore_index=True)
    n_raw = s.groupby("mode").size().to_dict()
    s = s[np.hypot(s.x - cx, s.y - cy) <= DISC_RADIUS_M].copy()
    s["source"] = "telraam"
    s = assign_folds(s)
    cw = build_crosswalk(net, s, SOURCE_RULES)
    cw.to_csv(out / "crosswalk.csv", index=False)
    sites = pd.DataFrame({
        "site_id": s.site_id, "mode": s["mode"], "value": s.aadt.round(3), "source": "telraam",
        "licence": TELRAAM_LICENCE, "method": "short_period_7day", "n_days": 7,
        "x": s.x.round(2), "y": s.y.round(2), "lon": s.lon.round(6), "lat": s.lat.round(6),
        "group_id": s.group_id, "fold": s.fold})
    sites.to_csv(out / "sites.csv", index=False)

    # inputs
    inp = out / "inputs"
    inp.mkdir(exist_ok=True)

    def pts(path, wcol):
        g = gpd.read_file(path).to_crs(CRS)
        d = pd.DataFrame({"x": g.geometry.x.values, "y": g.geometry.y.values, "weight": g[wcol].astype(float).values})
        d["type"] = g["category"].astype(str).values if "category" in g else ""
        return d[np.hypot(d.x - cx, d.y - cy) <= DISC_RADIUS_M].reset_index(drop=True)

    pop = pts(data / "leuven_worldpop_origins.geojson", "population").drop(columns="type")
    poi = pts(data / "leuven_attractors.geojson", "attractor_weight")
    pop.to_parquet(inp / "population.parquet", index=False)
    poi.to_parquet(inp / "pois.parquet", index=False)
    zones = build_zones(pop, poi, cx, cy, DISC_RADIUS_M)
    gpd.GeoDataFrame(zones[["zone_id", "population", "attractors"]], geometry=zones["geometry"].values,
                     crs=CRS).to_parquet(inp / "zones.parquet", index=False)
    od = synthetic_od(zones, MODES)
    od.to_parquet(inp / "od_synthetic.parquet", index=False)

    key = ["site_id", "mode"]
    prim = cw[cw.rule.isin(["point", "segment"])].drop_duplicates(key)
    m = sites.merge(prim[key + ["segment_id"]], on=key, how="left")
    per_mode = {md: dict(sites=int((m["mode"] == md).sum()),
                         matched=int(m[(m["mode"] == md)].segment_id.notna().sum()),
                         raw_sensors=int(n_raw.get(md, 0))) for md in MODES}
    rule_counts = cw.groupby(["mode", "rule"]).size().unstack(fill_value=0).to_dict("index")
    stats = dict(network=nstats, per_mode=per_mode, rule_counts=rule_counts,
                 inputs=dict(population_points=len(pop), population_total=round(float(pop.weight.sum())),
                             poi_points=len(poi), zones=len(zones), od_rows=len(od)))
    (out / "build_stats.json").write_text(json.dumps(stats, indent=1, default=str))
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*")
                   if p.is_file() and p.name != "build_stats.json")
    size = sum((out / f).stat().st_size for f in files)
    write_case_files(case_dir, a, stats, files, size, cx, cy)
    print(json.dumps(stats, indent=1, default=str)[:3000])
    print("data size MB", round(size / 1e6, 1))


def write_case_files(case_dir, a, stats, files, size, cx, cy):
    meta = {
        "id": a.case_id, "version": a.case_version, "benchmark_version": a.version,
        "title": "Leuven multimode flow from Telraam sensors (non-commercial)",
        "place": "Leuven", "country": "BEL", "crs": f"EPSG:{CRS}",
        "centre_lon": CENTRE[0], "centre_lat": CENTRE[1], "centre_x": round(cx, 1), "centre_y": round(cy, 1),
        "radius_m": DISC_RADIUS_M, "modes": MODES,
        "licence_class": "non_commercial",
        "attribution": "Source: Telraam (telraam.net), CC BY-NC 4.0",
        "sources": [{"source": "telraam", "licence": TELRAAM_LICENCE, "licence_text": "CC BY-NC 4.0",
                     "method": "short_period_7day", "n_sites": sum(d["sites"] for d in stats["per_mode"].values())}],
        "network_licence": "ODbL-1.0 (OpenStreetMap)",
        "split": {"group_cell_m": GROUP_CELL_M, "folds": N_FOLDS, "seed": SEED},
        "input_tiers": ["T0_network", "T1_open_covariates", "T2_synthetic_od"],
        "files": files, "data_size_bytes": size,
    }
    (case_dir / "case.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    n, i = stats["network"], stats["inputs"]
    L = [f"# {a.case_id}", "",
         "Leuven multimode case for AADTBench. Non-commercial. Built by `benchmark/export_leuven_case.py`.",
         "Data files are release assets and are not in git. See `case.yaml` for the file list.", "",
         "## Licence and attribution", "",
         "- Counts: Source: Telraam (telraam.net), CC BY-NC 4.0. This case is `licence_class: non_commercial`. "
         "It is scored and shown but kept out of the pooled leave-one-city-out board.",
         "- Network and POIs: OpenStreetMap contributors, ODbL 1.0.",
         "- Population: WorldPop, CC BY 4.0.",
         "- Use of this case for commercial purposes is not permitted by the Telraam licence.", "",
         "## Counts", "",
         "Telraam sensors, the 7-day mean daily count per sensor. The counting period is unknown (not recorded in "
         "the source tables), so values are not seasonally adjusted and are not true annual averages. "
         "Method is `short_period_7day`. Sensors are points, matched with a 50 m radius because their "
         "coordinates are approximate.", "",
         "- `car`: Telraam 'cars'. This is all light motor vehicles and may include some heavy vehicles.",
         "- `cycling`: Telraam cyclists. `walking`: Telraam pedestrians.", "",
         "| Mode | Sensors in source | Sites kept | Matched |", "|---|---|---|---|"]
    for md, d in stats["per_mode"].items():
        L.append(f"| {md} | {d['raw_sensors']} | {d['sites']} | {d['matched']} |")
    L += ["", "Unmatched sensors lie outside the network extent. The OSM graphs cover about 5 km by 7 km around "
          "Leuven, and the nearest link allowing the mode is at least 96 m away for walking and over 800 m for cycling and car (checked), so no rule could place them.",
          "", "Rule rows: " + json.dumps(stats["rule_counts"]) + ".",
          "With fewer than about 40 sites per mode, a target is near or under the 20-site ranking threshold "
          "once folds are applied. Treat results as indicative.", "",
          "## Network", "",
          f"- {n['n_links']} links, {n['km']} km, EPSG:{CRS}. {n['components']} components, the largest holds "
          f"{n['largest_component_share']*100:.1f} percent of links.",
          "- The OSMnx walk, cycle and drive graphs were simplified separately. The case network starts from "
          f"the walk graph ({n['from_walk']} links) and adds {n['added_cycle_drive']} cycle or drive links "
          "that the walk graph does not cover. Access flags come from 80 percent overlap within 2 m of each "
          "mode's graph. Directions come from the directed edges that run along each link.",
          "- `allow_heavy` copies `allow_car`. The graphs carry no HGV access tags.",
          f"- Links allowing each mode: {n['allow']}. Car directions: {n['dir_car']}.", "",
          "## Inputs", "",
          f"- population: {i['population_points']} WorldPop points, {i['population_total']} people.",
          f"- pois: {i['poi_points']} OSM points.",
          f"- zones: {i['zones']} 1 km cells over the 15 km disc, most outside the data extent have zero mass.",
          f"- od_synthetic: {i['od_rows']} rows, origin-constrained gravity as in the other cases.", "",
          "## Caveats", "",
          "- No heavy mode. Telraam does not separate heavy vehicles here.",
          "- No independent check of the crosswalk (no other model matches exist for Leuven).", ""]
    (case_dir / "README.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
