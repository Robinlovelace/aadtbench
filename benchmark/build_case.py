#!/usr/bin/env python3
"""Build or rebuild an AADTBench case (network, sites, inputs, crosswalk, manifest)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from scipy.spatial import cKDTree

from benchmark.build_inputs import build_zones, synthetic_od
from benchmark.crosswalk import build_crosswalk
from benchmark.licences import NON_COMMERCIAL_SOURCES, REVIEWED_SOURCES, reviewed_licence

BENCHMARK_VERSION = "0.1.0"
SOURCE_RULES = {"telraam": {"kind": "point", "radius_m": 50.0}, "toronto_tmc": {"kind": "junction"}}
PAIR_SENSOR_M = 30.0
DIRECTIONAL_SOURCES = {"oxflow", "vic_dtp_aadt", "stadt_zuerich_miv", "stadt_zuerich_fuss_velo",
                       "toronto_svc", "toronto_bike", "paris_road"}


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


def pair_directional(sites: pd.DataFrame, radius: float = PAIR_SENSOR_M) -> pd.DataFrame:
    arm = sites["bearing"].notna() if "bearing" in sites else pd.Series(False, index=sites.index)
    arm |= ~sites["source"].isin(DIRECTIONAL_SOURCES)
    out, done = [], set()
    for _, g in sites[~arm].groupby(["source", "mode"]):
        if len(g) < 2:
            out.append(g)
            continue
        d, j = cKDTree(g[["x", "y"]].values).query(g[["x", "y"]].values, k=2)
        own = np.arange(len(g))
        self_first = j[:, 0] == own
        nn = np.where(self_first, j[:, 1], j[:, 0])
        dist = np.where(self_first, d[:, 1], d[:, 0])
        rows = []
        for i in range(len(g)):
            k = nn[i]
            if i in done:
                continue
            if dist[i] <= radius and nn[k] == i and k not in done:
                a, b = g.iloc[i].copy(), g.iloc[k]
                a["site_id"] = f"{a.site_id}+{b.site_id}"
                a["value"] = a["value"] + b["value"]
                a["x"], a["y"] = (a.x + b.x) / 2, (a.y + b.y) / 2
                a["lon"], a["lat"] = (a.lon + b.lon) / 2, (a.lat + b.lat) / 2
                a["n_days"] = min(a.n_days, b.n_days)
                rows.append(a)
                done.update((i, k))
            else:
                rows.append(g.iloc[i])
        done.clear()
        out.append(pd.DataFrame(rows))
    return pd.concat(out + [sites[arm]], ignore_index=True)


def build_sites_and_inputs(cfg: dict, counts_path: Path, layers_dir: Path, out: Path, allowed: dict) -> pd.DataFrame:
    crs = int(str(cfg["crs"]).split(":")[-1])
    cx, cy = (v[0] for v in project(pd.DataFrame({"lon": [cfg["centre_lon"]], "lat": [cfg["centre_lat"]]}), crs))
    r = float(cfg["radius_m"])
    c = pd.read_parquet(counts_path)
    c["mode"] = c["mode"].replace(cfg.get("mode_map", {}))
    c = c[c.source.isin(allowed) & c["mode"].isin(cfg["modes"]) & (c.aadt > 0)].copy()
    c["x"], c["y"] = project(c, crs)
    c = c[np.hypot(c.x - cx, c.y - cy) <= r]
    if "kind" in c.columns:
        c.loc[c["kind"].eq("junction_movement"), "aadt"] *= 2.0
    sites = pd.DataFrame({
        "site_id": c.site_id.astype(str), "mode": c["mode"], "value": c.aadt.round(3), "source": c.source,
        "licence": c.source.map(lambda s: allowed[s]["licence"]),
        "method": c["method"] if "method" in c.columns else "short_period", "n_days": c.n_days,
        "x": c.x.round(2), "y": c.y.round(2), "lon": c.lon, "lat": c.lat,
        "bearing": c["bearing"] if "bearing" in c.columns else np.nan,
        **({"road_name": c["road_name"]} if "road_name" in c.columns else {}),
    })
    sites = assign_folds(sites.reset_index(drop=True), float(cfg["split"]["group_cell_m"]),
                         int(cfg["split"]["folds"]), int(cfg["split"]["seed"]))
    inp = out / "inputs"
    inp.mkdir(parents=True, exist_ok=True)
    extent = r + float(cfg.get("margin_m", 0) or 0)
    pop = points(layers_dir / "residents.parquet", crs, cx, cy, extent)
    pois = pd.concat([points(f, crs, cx, cy, extent).assign(type=f.stem.removeprefix("poi_"))
                      for f in sorted(layers_dir.glob("poi_*.parquet"))
                      if f.stem != "poi_all" and "@" not in f.stem], ignore_index=True)
    pop.to_parquet(inp / "population.parquet", index=False)
    pois.to_parquet(inp / "pois.parquet", index=False)
    zone_m = float(cfg.get("zone_m", 1000.0) or 1000.0)
    zones = build_zones(pop, pois, cx, cy, extent, cell_m=zone_m)
    gpd.GeoDataFrame(zones[["zone_id", "population", "attractors"]], geometry=zones["geometry"].values,
                     crs=crs).to_parquet(inp / "zones.parquet", index=False)
    synthetic_od(zones, cfg["modes"], intrazonal_m=zone_m / 2).to_parquet(inp / "od_synthetic.parquet", index=False)
    return sites


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True)
    ap.add_argument("--source", type=Path, help="dated Geofabrik extract (.osm.pbf)")
    ap.add_argument("--clipped", type=Path, help="existing clipped source.osm.pbf")
    ap.add_argument("--counts", type=Path, help="raw counts parquet (optional if sites.csv exists in --out)")
    ap.add_argument("--layers", type=Path, help="layers dir (optional if inputs/ exists in --out)")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    case_dir = Path("cases") / a.case
    cfg = yaml.safe_load((case_dir / "case.yaml").read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    allowed = {**REVIEWED_SOURCES, **(NON_COMMERCIAL_SOURCES if cfg.get("licence_class") == "non_commercial" else {})}

    if a.counts and a.layers:
        sites = build_sites_and_inputs(cfg, a.counts, a.layers, a.out, allowed)
    else:
        sites = pd.read_csv(a.out / "sites.csv", dtype={"site_id": str})

    cmd = [sys.executable, "benchmark/build_osm_network.py", "--case", str(case_dir), "--out", str(a.out)]
    cmd += ["--clipped", str(a.clipped)] if a.clipped else ["--source", str(a.source)]
    subprocess.run(cmd, check=True)
    build = json.loads((a.out / "network_build.json").read_text())

    sites = pair_directional(sites)
    keep = sites["source"].isin(allowed)
    dropped = {f"{s} {m}": int(n) for (s, m), n in sites[~keep].groupby(["source", "mode"]).size().items()}
    sites = sites[keep].copy()
    sites["licence"] = sites["source"].map(lambda s: allowed[s]["licence"])
    sites.to_csv(a.out / "sites.csv", index=False)

    net = gpd.read_parquet(a.out / "network.parquet")
    cw = build_crosswalk(net, sites, SOURCE_RULES)
    cw.to_csv(a.out / "crosswalk.csv", index=False)
    n_sites = sites.groupby("mode").size().to_dict()
    matched = cw[cw.rule != "pair"].groupby("mode").size().to_dict()
    pairs = cw[cw.rule == "pair"].groupby("mode").size().to_dict()

    cfg["benchmark_version"] = BENCHMARK_VERSION
    cfg["modes"] = [m for m in cfg["modes"] if n_sites.get(m)]
    cfg["sources"] = [{"source": s, "licence": allowed[s]["licence"], "url": allowed[s]["url"],
                       "reviewed": allowed[s]["reviewed"], "n_rows": int((sites.source == s).sum())}
                      for s in sorted(sites["source"].unique())]
    cfg["excluded_sources"] = {s: reviewed_licence(s)[1] for s in sorted({k.split()[0] for k in dropped})}
    cfg["network"] = {k: build.get(k) for k in ("source_extract", "source_timestamp", "clipped_sha256",
                                                "links", "km", "components", "largest_component_share")}
    cfg["network"]["build"] = "benchmark/build_osm_network.py: raw OSM, split at shared nodes, no cleaning"
    files = sorted(str(p.relative_to(a.out)) for p in a.out.rglob("*")
                   if p.is_file() and p.name not in ("build_stats.json", "network_build.json", "case.yaml"))
    cfg["files"] = files
    cfg["data_size_bytes"] = int(sum((a.out / f).stat().st_size for f in files))
    (case_dir / "case.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    print(json.dumps({"case": a.case, "sites": n_sites, "matched": matched, "pairs": pairs, "links": build["links"]}))


if __name__ == "__main__":
    main()
