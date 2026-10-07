#!/usr/bin/env python3
"""Build a v0.2 AADTBench case from frozen multimode city data.

Example:
    PYTHONPATH=. python benchmark/export_multimode_case.py --city oxford \
        --run-dir <source-data>/runs/oxford/<run> \
        --out build/cases/v0.2.0/oxford-v1 --version 0.2.0

Data files go to --out (not in git). case.yaml and README.md go to --case-dir
(default cases/<case_id>).
"""
from __future__ import annotations

import argparse
import os
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
from benchmark.licences import reviewed_licence

DEFAULT_DATA_ROOT = os.environ.get("AADTBENCH_SOURCE_DATA", "source-data")
MODES = ["walking", "cycling", "car", "heavy"]
DISC_RADIUS_M = 15000.0
GROUP_CELL_M = 3000.0
N_FOLDS = 5
SEED = 42

# City centres (lon, lat), name and country.
CITIES = {
    "oxford": dict(lon=-1.2578499, lat=51.7520131, title="Oxford", country="GBR"),
    "leeds": dict(lon=-1.5437941, lat=53.7974185, title="Leeds", country="GBR"),
    "bristol": dict(lon=-2.5972985, lat=51.4538022, title="Bristol", country="GBR"),
    "melbourne": dict(lon=144.9631732, lat=-37.8142454, title="Melbourne", country="AUS"),
}

# ---- Licence rules (BENCHMARK.md, "Licence rules") --------------------------
# A row is kept only if its source is in the reviewed table in
# benchmark/licences.py. Its licence comes from that table.

# Per-source crosswalk rules. Telraam would be a segment source with line_wkt.
SOURCE_RULES = {
    "telraam": {"kind": "segment"},
}

# Network road class vocabulary, from the OSM highway tag.
HIGHWAY_TO_CLASS = {
    "motorway": "motorway", "motorway_link": "motorway",
    "trunk": "trunk", "trunk_link": "trunk",
    "primary": "primary", "primary_link": "primary",
    "secondary": "secondary", "secondary_link": "secondary",
    "tertiary": "tertiary", "tertiary_link": "tertiary",
    "unclassified": "minor", "residential": "minor", "living_street": "minor",
    "service": "service",
    "cycleway": "cycleway",
    "footway": "footway", "pedestrian": "footway", "steps": "footway",
    "path": "footway", "bridleway": "footway", "track": "footway",
}  # anything else (for example synthetic connectors) becomes "other"
DIR_CODE = {0: "both", 1: "forward", -1: "backward"}


def case_crs(lon: float, lat: float, country: str) -> int:
    if country == "GBR":
        return 27700
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def licence_decision(source: str, licence: str):
    """Return (licence id or None, drop reason or None) from the reviewed table only."""
    return reviewed_licence(source)


def build_network(run_dir: Path, crs: int, clip=None):
    """clip = (cx, cy, radius_m): keep links that touch the disc."""
    net = pd.read_parquet(run_dir / "network.parquet")
    pairs = pd.read_parquet(run_dir / "model" / "links.parquet", columns=["link_id", "pair_link"])
    net = net.merge(pairs, on="link_id", how="left")
    geom = shapely.from_wkb(net["geom"].values)
    gdf = gpd.GeoDataFrame(net.drop(columns="geom"), geometry=geom, crs=4326).to_crs(crs)
    if clip is not None:
        cx_, cy_, r_ = clip
        keep = shapely.intersects(gdf.geometry.values, shapely.Point(cx_, cy_).buffer(r_, 64))
        gdf = gdf[keep].reset_index(drop=True)
        ids = set(gdf["link_id"].astype(str))
        gdf["pair_link"] = gdf["pair_link"].where(gdf["pair_link"].astype(str).isin(ids))
    xy0 = shapely.get_coordinates(shapely.get_point(gdf.geometry.values, 0))
    xy1 = shapely.get_coordinates(shapely.get_point(gdf.geometry.values, -1))
    keys = np.round(np.vstack([xy0, xy1]) * 2).astype("int64")  # 0.5 m snap
    codes, _ = pd.factorize(pd.Series(list(map(tuple, keys))))
    n = len(gdf)
    u, v = codes[:n], codes[n:]
    nn = codes.max() + 1
    adj = coo_matrix((np.ones(n), (u, v)), shape=(nn, nn))
    ncomp, lab = connected_components(adj, directed=False)
    sizes = np.bincount(lab[u])  # links per component
    out = gpd.GeoDataFrame({
        "segment_id": gdf["link_id"].astype(str),
        "u": u.astype("int64"), "v": v.astype("int64"),
        "length_m": gdf.geometry.length.round(2),
        "road_class": gdf["highway"].map(HIGHWAY_TO_CLASS).fillna("other"),
        "highway": gdf["highway"],
        "name": gdf["road_name"],
        "ref": gdf["road_ref"],
        "allow_walking": gdf["access_foot"].astype(bool),
        "allow_cycling": gdf["access_bicycle"].astype(bool),
        "allow_car": gdf["access_motor"].astype(bool),
        "allow_heavy": gdf["access_hgv"].astype(bool),
        "dir_car": gdf["dir_motor"].map(DIR_CODE),
        "dir_cycling": gdf["dir_bicycle"].map(DIR_CODE),
        "pair_segment": gdf["pair_link"].fillna("").astype(str),
    }, geometry=gdf.geometry.values, crs=crs)
    stats = dict(n_links=int(n), n_nodes=int(nn), components=int(ncomp),
                 largest_component_links=int(sizes.max()),
                 largest_component_share=round(float(sizes.max() / n), 4),
                 km=round(float(out.length_m.sum() / 1000), 1),
                 n_pairs=int((out.pair_segment != "").sum()),
                 classes={k: int(v) for k, v in out.road_class.value_counts().items()})
    return out, stats


def load_sites(data_root: Path, run_dir: Path, city: str, crs: int, cx: float, cy: float,
               radius_m: float = DISC_RADIUS_M):
    s = pd.read_parquet(data_root / "counts" / city / "sites.parquet")
    n_raw = s.groupby(["source", "mode"]).size().rename("n").reset_index()
    s = s[s["mode"].isin(MODES)].copy()
    decisions = s.apply(lambda r: licence_decision(r["source"], r["licence"]), axis=1)
    s["licence_short"] = [d[0] for d in decisions]
    s["drop_reason"] = [d[1] for d in decisions]
    s.loc[s["aadt"].isna(), "drop_reason"] = "no value"
    xy = gpd.GeoSeries(gpd.points_from_xy(s.lon, s.lat), crs=4326).to_crs(crs)
    s["x"], s["y"] = xy.x.values, xy.y.values
    far = np.hypot(s.x - cx, s.y - cy) > radius_m
    s.loc[far & s.drop_reason.isna(), "drop_reason"] = f"outside {radius_m / 1000:g} km disc"
    # road names for the crosswalk, from the run's own counts table (names only)
    cp = run_dir / "counts.parquet"
    if cp.exists():
        names = pd.read_parquet(cp, columns=["site_id", "mode", "road_name", "line_wkt"])
        s = s.merge(names.drop_duplicates(["site_id", "mode"]), on=["site_id", "mode"], how="left")
    else:
        s["road_name"] = None
        s["line_wkt"] = None
    dropped = s[s.drop_reason.notna()]
    drop_table = (dropped.groupby(["source", "mode", "drop_reason"]).size().rename("n")
                  .reset_index().to_dict("records"))
    kept = s[s.drop_reason.isna()].copy()
    return kept, drop_table, n_raw


def assign_folds(sites: pd.DataFrame, cell_m: float = GROUP_CELL_M) -> pd.DataFrame:
    gx = np.floor(sites.x / cell_m).astype(int)
    gy = np.floor(sites.y / cell_m).astype(int)
    sites["group_id"] = "g" + gx.astype(str) + "_" + gy.astype(str)
    groups = np.array(sorted(sites.group_id.unique()))
    order = np.random.default_rng(SEED).permutation(len(groups))
    fold_of = {groups[g]: int(rank % N_FOLDS) for rank, g in enumerate(order)}
    sites["fold"] = sites.group_id.map(fold_of)
    return sites


def read_points(path: Path, crs: int, cx: float, cy: float, radius_m: float = DISC_RADIUS_M):
    d = pd.read_parquet(path)
    xy = gpd.GeoSeries(gpd.points_from_xy(d.lon, d.lat), crs=4326).to_crs(crs)
    out = pd.DataFrame({"x": xy.x.values, "y": xy.y.values, "weight": d["weight"].astype(float).values})
    return out[np.hypot(out.x - cx, out.y - cy) <= radius_m].reset_index(drop=True)


def build_inputs(data_root: Path, city: str, crs: int, cx: float, cy: float, out: Path,
                 extent_m: float = DISC_RADIUS_M, zone_m: float = 1000.0):
    layers = data_root / "inputs" / city / "layers"
    pop = read_points(layers / "residents.parquet", crs, cx, cy, extent_m)
    pois = []
    for f in sorted(layers.glob("poi_*.parquet")):
        if f.stem == "poi_all":
            continue  # union of the others, do not double count
        p = read_points(f, crs, cx, cy, extent_m)
        p["type"] = f.stem.removeprefix("poi_")
        pois.append(p)
    pois = pd.concat(pois, ignore_index=True)
    inp = out / "inputs"
    inp.mkdir(parents=True, exist_ok=True)
    pop.to_parquet(inp / "population.parquet", index=False)
    pois.to_parquet(inp / "pois.parquet", index=False)
    zones = build_zones(pop, pois, cx, cy, extent_m, cell_m=zone_m)
    zg = gpd.GeoDataFrame(zones[["zone_id", "population", "attractors"]],
                          geometry=zones["geometry"].values, crs=crs)
    zg.to_parquet(inp / "zones.parquet", index=False)
    od = synthetic_od(zones, MODES, intrazonal_m=zone_m / 2)
    od.to_parquet(inp / "od_synthetic.parquet", index=False)
    return dict(population_points=len(pop), population_total=round(float(pop.weight.sum())),
                poi_points=len(pois), poi_types=pois["type"].value_counts().to_dict(),
                zones=len(zg), od_rows=len(od))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True, choices=sorted(CITIES))
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--out", required=True, help="data directory (not in git)")
    ap.add_argument("--version", default="0.2.0", help="benchmark version")
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--case-version", default="1.0.0")
    ap.add_argument("--case-dir", default=None, help="small files for git, default cases/<case_id>")
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    ap.add_argument("--centre-lon", type=float, default=None, help="default: the city centre")
    ap.add_argument("--centre-lat", type=float, default=None)
    ap.add_argument("--radius-m", type=float, default=DISC_RADIUS_M, help="scored core radius")
    ap.add_argument("--margin-m", type=float, default=0.0,
                    help="network, zones and OD extend this far beyond the core (0 keeps the whole network)")
    ap.add_argument("--zone-m", type=float, default=1000.0, help="zone cell size")
    ap.add_argument("--group-cell-m", type=float, default=GROUP_CELL_M, help="fold group cell size")
    a = ap.parse_args()

    city = dict(CITIES[a.city])
    if a.centre_lon is not None:
        city["lon"] = a.centre_lon
    if a.centre_lat is not None:
        city["lat"] = a.centre_lat
    extent = a.radius_m + a.margin_m
    case_id = a.case_id or f"{a.city}-v1"
    run_dir, data_root, out = Path(a.run_dir), Path(a.data_root), Path(a.out)
    case_dir = Path(a.case_dir or f"cases/{case_id}")
    out.mkdir(parents=True, exist_ok=True)
    case_dir.mkdir(parents=True, exist_ok=True)
    crs = case_crs(CITIES[a.city]["lon"], CITIES[a.city]["lat"], city["country"])
    c = gpd.GeoSeries(gpd.points_from_xy([city["lon"]], [city["lat"]]), crs=4326).to_crs(crs)
    cx, cy = float(c.x.iloc[0]), float(c.y.iloc[0])

    net, nstats = build_network(run_dir, crs, clip=(cx, cy, extent) if a.margin_m > 0 else None)
    net.to_parquet(out / "network.parquet", index=False)
    print("network", nstats["n_links"], "links, components", nstats["components"])

    kept, drop_table, n_raw = load_sites(data_root, run_dir, a.city, crs, cx, cy, a.radius_m)
    kept = assign_folds(kept, a.group_cell_m)
    cw = build_crosswalk(net, kept, SOURCE_RULES)
    cw.to_csv(out / "crosswalk.csv", index=False)
    sites = pd.DataFrame({
        "site_id": kept.site_id, "mode": kept["mode"], "value": kept.aadt.round(3),
        "source": kept.source, "licence": kept.licence_short, "method": kept.method,
        "n_days": kept.n_days, "x": kept.x.round(2), "y": kept.y.round(2),
        "lon": kept.lon.round(6), "lat": kept.lat.round(6),
        "group_id": kept.group_id, "fold": kept.fold,
    })
    assert not sites.duplicated(["site_id", "mode"]).any(), "duplicate site and mode"
    sites.to_csv(out / "sites.csv", index=False)

    istats = build_inputs(data_root, a.city, crs, cx, cy, out, extent, a.zone_m)

    # Match statistics.
    key = ["site_id", "mode"]
    prim = cw[cw.rule.isin(["point", "segment"])].drop_duplicates(key)
    matched = sites.merge(prim[key + ["segment_id", "dist_m", "rule"]], on=key, how="left")
    per_mode = {}
    for m in MODES:
        sm = matched[matched["mode"] == m]
        per_mode[m] = dict(sites=int(len(sm)), matched=int(sm.segment_id.notna().sum()),
                           unmatched=int(sm.segment_id.isna().sum()))
    rule_counts = cw.groupby(["mode", "rule"]).size().unstack(fill_value=0).to_dict("index")
    source_counts = sites.groupby(["source", "mode"]).size().rename("n").reset_index().to_dict("records")
    agree = {}
    obs_path = run_dir / "model" / "observed.parquet"
    if obs_path.exists():
        obs = pd.read_parquet(obs_path, columns=["site_id", "mode", "link_id"]).rename(
            columns={"link_id": "theirs"})
        both = matched.dropna(subset=["segment_id"]).merge(obs, on=key)
        allrows = cw.groupby(key)["segment_id"].apply(set).rename("ours_all").reset_index()
        both = both.merge(allrows, on=key)
        both["same_primary"] = both.segment_id == both.theirs.astype(str)
        both["in_set"] = [t in s for t, s in zip(both.theirs.astype(str), both.ours_all)]
        agree = dict(n_compared=int(len(both)),
                     same_primary=round(float(both.same_primary.mean()), 4),
                     theirs_in_our_rows=round(float(both.in_set.mean()), 4),
                     by_mode={m: round(float(g.same_primary.mean()), 4) for m, g in both.groupby("mode")})

    stats = dict(network=nstats, inputs=istats, per_mode=per_mode, rule_counts=rule_counts,
                 dropped=drop_table, kept_by_source=source_counts, agreement=agree)
    (out / "build_stats.json").write_text(json.dumps(stats, indent=1, default=str))

    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*")
                   if p.is_file() and p.name != "build_stats.json")
    size = sum((out / f).stat().st_size for f in files)
    write_case_files(case_dir, case_id, a, city, crs, cx, cy, sites, stats, files, size)
    print(json.dumps({k: stats[k] for k in ["per_mode", "rule_counts", "agreement"]}, indent=1, default=str))
    print("data size MB", round(size / 1e6, 1))


def write_case_files(case_dir, case_id, a, city, crs, cx, cy, sites, stats, files, size):
    srcs = sites.groupby("source").agg(licence=("licence", "first"), method=("method", "first"),
                                       n=("site_id", "size")).reset_index()
    raw_lic = pd.read_parquet(Path(a.data_root) / "counts" / a.city / "sites.parquet",
                              columns=["source", "licence"]).drop_duplicates("source")
    raw_lic = dict(zip(raw_lic.source, raw_lic.licence))
    meta = {
        "id": case_id,
        "version": a.case_version,
        "benchmark_version": a.version,
        "title": f"{city['title']} multimode annual average daily flow",
        "place": city["title"], "country": city["country"],
        "crs": f"EPSG:{crs}", "centre_lon": city["lon"], "centre_lat": city["lat"],
        "centre_x": round(cx, 1), "centre_y": round(cy, 1), "radius_m": a.radius_m,
        "margin_m": a.margin_m, "zone_m": a.zone_m,
        "modes": [m for m in MODES if m in set(sites["mode"])],
        "sources": [{"source": r.source, "licence": r.licence, "licence_text": raw_lic.get(r.source),
                     "method": r.method, "n_sites": int(r.n)} for r in srcs.itertuples()],
        "excluded_sources": {k: reviewed_licence(k)[1] for k in raw_lic if reviewed_licence(k)[0] is None},
        "network_licence": "ODbL-1.0 (OpenStreetMap)",
        "split": {"group_cell_m": a.group_cell_m, "folds": N_FOLDS, "seed": SEED},
        "input_tiers": ["T0_network", "T1_open_covariates", "T2_synthetic_od"],
        "files": files,
        "data_size_bytes": size,
    }
    (case_dir / "case.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))

    n = stats["network"]
    lines = [f"# {case_id}", "",
             f"{city['title']} multimode case for AADTBench {a.version}. Built by `benchmark/export_multimode_case.py`.",
             "Data files are release assets and are not in git. See `case.yaml` for the file list.", "",
             "## Build", "",
             "```text", f"PYTHONPATH=. python benchmark/export_multimode_case.py --city {a.city} "
             f"--run-dir <run dir> --out <data dir> --version {a.version} --case-id {case_id}", "```", "",
             "## Network", "",
             f"- OpenStreetMap derived links, cleaned (junctions consolidated, duplicates removed, one component kept) by a network preparation step run before export and frozen here as data, {n['n_links']} links, {n['km']} km, EPSG:{crs}.",
             f"- Node ids come from snapping link ends to 0.5 m. {n['components']} connected components, "
             f"the largest holds {n['largest_component_share']*100:.1f} percent of links.",
             f"- {n['n_pairs']} links have a dual carriageway partner.",
             "- Direction codes assume `forward` means along the stored geometry (checked on dual carriageway pairs: forward/forward pairs run in opposite geometry directions).",
             "- Road class comes from the OSM `highway` tag. `ref` is an extra column used by the crosswalk.", "",
             "## Counts and licences", "",
             "| Source | Licence | Method | Sites kept |", "|---|---|---|---|"]
    for r in meta["sources"]:
        lines.append(f"| {r['source']} | {r['licence']} ({r['licence_text']}) | {r['method']} | {r['n_sites']} |")
    lines += ["", "Excluded sources:", ""]
    for k, v in meta["excluded_sources"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "Sites kept, matched and unmatched per mode (unmatched sites stay in `sites.csv`, are not scored):", "",
              "| Mode | Sites | Matched | Unmatched |", "|---|---|---|---|"]
    for m, d in stats["per_mode"].items():
        lines.append(f"| {m} | {d['sites']} | {d['matched']} | {d['unmatched']} |")
    lines += ["", "Rows dropped by the export:", ""]
    for d in stats["dropped"]:
        lines.append(f"- {d['source']} {d['mode']}: {d['n']} ({d['drop_reason']})")
    lines += ["", "## Crosswalk", "",
              "Built by `benchmark/crosswalk.py`. Rule rows per mode: " + json.dumps(stats["rule_counts"]) + ".", ""]
    if stats["agreement"]:
        g = stats["agreement"]
        lines += [f"Check against the source model's own matches ({g['n_compared']} shared sites): "
                  f"{g['same_primary']*100:.1f} percent share the same primary link, "
                  f"{g['theirs_in_our_rows']*100:.1f} percent have their link among our rows. "
                  "This is a check only. The matches were not copied.", ""]
    i = stats["inputs"]
    lines += ["## Inputs", "",
              f"- `population.parquet`: WorldPop residents, CC BY 4.0, {i['population_points']} points, "
              f"{i['population_total']} people within the extent.",
              f"- `pois.parquet`: OpenStreetMap POIs, ODbL 1.0, {i['poi_points']} points, types {i['poi_types']}.",
              f"- `zones.parquet`: {i['zones']} {a.zone_m:g} m cells covering the {(a.radius_m + a.margin_m) / 1000:g} km extent.",
              f"- `od_synthetic.parquet`: {i['od_rows']} rows. Origin-constrained gravity per mode, "
              "attraction = POI weight + 0.1 times population, decay lengths walking 1 km (cap 3 km), "
              "cycling 3 km (cap 10 km), car 6 km, heavy 12 km. Trip rate 1 per person. "
              "It is a shape. The scale is arbitrary.", "",
              "## Licence", "",
              "The case contains OpenStreetMap derived data and is released under ODbL 1.0. "
              "Counts keep their own licence, shown per row in `sites.csv`.", "",
              "## Caveats", "",
              "- Flows are two-way annual averages. Short period sources (DfT manual counts) are expanded by their publisher.",
              "- Counts that report one direction only are not handled. Sources in this case report two-way totals (assumed).",
              "- The road class preference in crosswalk rule 2 applies to motor modes only. Walking and cycling "
              "take the nearest link. See the agreement check above.",
              "- No heavy vehicle or walking site has an independent check beyond the shared crosswalk.", ""]
    if a.margin_m > 0:
        lines[-1:-1] = [
            f"- The scored core is a {a.radius_m / 1000:g} km disc around the centre. The network, population, POIs, "
            f"zones and synthetic OD extend {a.margin_m / 1000:g} km beyond it, so flows at core sites are complete. "
            "Sites are kept only inside the core.",
            f"- Fold groups use {a.group_cell_m:g} m cells (`split.group_cell_m` in `case.yaml`), because a "
            "3 km cell would leave too few groups in a small core.",
            "- No elevation layer is included. If one is added later it must be Copernicus GLO-30, not FABDEM "
            "(CC BY-NC-SA, not allowed in an open case)."]
    (case_dir / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    main()
