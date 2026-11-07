#!/usr/bin/env python3
"""Build a raw OpenStreetMap network for a case."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import yaml
from pyproj import Transformer

NON_ROUTABLE = {
    "proposed", "construction", "abandoned", "disused", "razed", "planned", "no",
    "platform", "raceway", "rest_area", "services", "bus_stop", "elevator",
    "emergency_bay", "escape", "corridor", "via_ferrata", "bus_guideway",
    "emergency_access_point", "turning_circle", "turning_loop", "street_lamp",
}
MOTOR_HIGHWAY = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
    "residential", "living_street", "service", "road",
}
HIGHWAY_TO_CLASS = {
    "motorway": "motorway", "motorway_link": "motorway",
    "trunk": "trunk", "trunk_link": "trunk",
    "primary": "primary", "primary_link": "primary",
    "secondary": "secondary", "secondary_link": "secondary",
    "tertiary": "tertiary", "tertiary_link": "tertiary",
    "unclassified": "minor", "residential": "minor", "living_street": "minor",
    "road": "minor", "service": "service", "cycleway": "cycleway", "busway": "other",
    "footway": "footway", "pedestrian": "footway", "steps": "footway",
    "path": "footway", "bridleway": "footway", "track": "footway",
}
YES = {"yes", "designated", "permissive", "destination", "official", "customers", "delivery"}
NO = {"no", "private", "agricultural", "forestry", "discouraged_no"}
KEEP_TAGS = ("highway", "name", "ref", "oneway", "junction", "access", "motor_vehicle",
             "motorcar", "hgv", "bicycle", "foot", "motorroad", "oneway:bicycle", "area",
             "cycleway", "cycleway:left", "cycleway:right", "cycleway:both")


def osmium_cmd() -> list[str]:
    return shlex.split(os.environ.get("OSMIUM", "osmium"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def disc_bbox(lon: float, lat: float, radius_m: float) -> tuple[float, float, float, float]:
    r = radius_m * 1.1
    dlat = r / 111_320.0
    dlon = r / (111_320.0 * np.cos(np.radians(lat)))
    return lon - dlon, lat - dlat, lon + dlon, lat + dlat


def clip(source: Path, out: Path, bbox: tuple[float, float, float, float]) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".box.osm.pbf")
    b = ",".join(f"{v:.6f}" for v in bbox)
    subprocess.run(osmium_cmd() + ["extract", "-b", b, "--strategy", "complete_ways",
                                   "--overwrite", "-o", str(tmp), str(source)], check=True)
    subprocess.run(osmium_cmd() + ["tags-filter", "--overwrite", "-o", str(out), str(tmp), "w/highway"], check=True)
    tmp.unlink()
    info = subprocess.run(osmium_cmd() + ["fileinfo", "-g", "header.option.osmosis_replication_timestamp",
                                          str(source)], capture_output=True, text=True).stdout.strip()
    return {"source_extract": source.name, "source_timestamp": info or "unknown",
            "bbox": [round(v, 6) for v in bbox], "clipped_file": out.name,
            "clipped_sha256": sha256(out), "osmium": "osmium-tool extract --strategy complete_ways, tags-filter w/highway"}


def read_ways(pbf: Path) -> tuple[list, dict]:
    import osmium
    ways, coords = [], {}
    for obj in osmium.FileProcessor(str(pbf)).with_locations():
        if obj.is_way():
            hw = obj.tags.get("highway")
            if hw is None or hw in NON_ROUTABLE or obj.tags.get("area") == "yes":
                continue
            refs, ok = [], True
            for n in obj.nodes:
                if not n.location.valid():
                    ok = False
                    break
                refs.append(n.ref)
                coords[n.ref] = (n.location.lon, n.location.lat)
            if ok and len(refs) >= 2:
                ways.append((obj.id, refs, {k: obj.tags.get(k) for k in KEEP_TAGS if k in obj.tags}))
    return ways, coords


def split_ways(ways: list) -> list[tuple]:
    use: dict[int, int] = {}
    for _, refs, _ in ways:
        for n in refs:
            use[n] = use.get(n, 0) + 1
    out = []
    for wid, refs, tags in ways:
        k, start = 0, 0
        for i in range(1, len(refs)):
            if i == len(refs) - 1 or use[refs[i]] >= 2:
                out.append((f"{wid}-{k}", wid, refs[start:i + 1], tags))
                k, start = k + 1, i
    return out


def _yes(v) -> bool:
    return v in YES


def _no(v) -> bool:
    return v in NO


def car_access(t: dict) -> tuple[bool, bool]:
    hw = t.get("highway")
    base = hw in MOTOR_HIGHWAY or (hw == "track" and (_yes(t.get("motor_vehicle")) or _yes(t.get("motorcar"))))
    mv = t.get("motorcar") or t.get("motor_vehicle")
    if (_no(t.get("access")) and not _yes(mv)) or _no(mv):
        base = False
    return base, (base and not _no(t.get("hgv")))


def cycle_access(t: dict) -> bool:
    hw, b = t.get("highway"), t.get("bicycle")
    base = hw not in {"motorway", "motorway_link", "steps", "footway", "pedestrian"} and t.get("motorroad") != "yes"
    if (_no(t.get("access")) and not _yes(b)) or b in ("no", "private", "dismount", "use_sidepath"):
        base = False
    return True if _yes(b) else base


def foot_access(t: dict) -> bool:
    hw, f = t.get("highway"), t.get("foot")
    base = hw not in {"motorway", "motorway_link"} and t.get("motorroad") != "yes"
    if (_no(t.get("access")) and not _yes(f)) or f in ("no", "private", "use_sidepath"):
        base = False
    return True if _yes(f) else base


def directions(t: dict) -> tuple[str, str]:
    ow = t.get("oneway")
    if ow in ("yes", "true", "1"):
        d = "forward"
    elif ow in ("-1", "reverse"):
        d = "backward"
    elif ow == "no":
        d = "both"
    elif t.get("junction") in ("roundabout", "circular") or t.get("highway") == "motorway":
        d = "forward"
    else:
        d = "both"
    dc = d
    contra = {"opposite", "opposite_lane", "opposite_track", "opposite_share_busway"}
    if t.get("oneway:bicycle") == "no" or any(t.get(k) in contra for k in
                                               ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")):
        dc = "both"
    elif t.get("oneway:bicycle") in ("yes", "-1"):
        dc = "forward" if t["oneway:bicycle"] == "yes" else "backward"
    return d, dc


def build(pbf: Path, crs_epsg: int, centre_lon: float, centre_lat: float, keep_radius_m: float) -> gpd.GeoDataFrame:
    ways, coords = read_ways(pbf)
    segs = split_ways(ways)
    tf = Transformer.from_crs(4326, crs_epsg, always_xy=True)
    cx, cy = tf.transform(centre_lon, centre_lat)
    ids = np.fromiter(coords.keys(), dtype=np.int64)
    ll = np.array([coords[i] for i in ids])
    x, y = tf.transform(ll[:, 0], ll[:, 1])
    pos = pd.Series(np.arange(len(ids)), index=ids)
    xy = np.c_[x, y]
    geoms = [shapely.linestrings(xy[pos[refs].values]) for _, _, refs, _ in segs]
    rows = []
    for (sid, wid, refs, t) in segs:
        car, heavy = car_access(t)
        dcar, dcyc = directions(t)
        hw = t.get("highway")
        rows.append({
            "segment_id": sid, "osm_way_id": wid, "u": refs[0], "v": refs[-1],
            "road_class": HIGHWAY_TO_CLASS.get(hw, "other"), "highway": hw,
            "name": t.get("name"), "ref": t.get("ref"),
            "allow_walking": foot_access(t), "allow_cycling": cycle_access(t),
            "allow_car": car, "allow_heavy": heavy,
            "dir_car": dcar if car else "both", "dir_cycling": dcyc, "pair_segment": None,
        })
    net = gpd.GeoDataFrame(rows, geometry=geoms, crs=crs_epsg)
    net["length_m"] = net.geometry.length
    net = net[net.intersects(shapely.Point(cx, cy).buffer(keep_radius_m))].reset_index(drop=True)
    cols = ["segment_id", "osm_way_id", "u", "v", "length_m", "road_class", "highway", "name", "ref",
            "allow_walking", "allow_cycling", "allow_car", "allow_heavy", "dir_car", "dir_cycling",
            "pair_segment", "geometry"]
    return net[cols]


def components(net: gpd.GeoDataFrame) -> tuple[int, float]:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    nodes = pd.Index(np.unique(np.r_[net["u"].values, net["v"].values]))
    a, b = nodes.get_indexer(net["u"]), nodes.get_indexer(net["v"])
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(len(nodes), len(nodes)))
    n, lab = connected_components(g, directed=False)
    return int(n), float(np.bincount(lab[a]).max() / len(net))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True, type=Path)
    ap.add_argument("--source", type=Path)
    ap.add_argument("--clipped", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    cfg = yaml.safe_load((a.case / "case.yaml").read_text())
    lon, lat = float(cfg["centre_lon"]), float(cfg["centre_lat"])
    keep = float(cfg.get("radius_m", 15000)) + float(cfg.get("margin_m", 0) or 0)
    epsg = int(str(cfg["crs"]).split(":")[-1])
    a.out.mkdir(parents=True, exist_ok=True)
    pbf = a.out / "source.osm.pbf"
    if a.clipped:
        if a.clipped.resolve() != pbf.resolve():
            pbf.write_bytes(a.clipped.read_bytes())
        prov = {"clipped_file": pbf.name, "clipped_sha256": sha256(pbf)}
    else:
        prov = clip(a.source, pbf, disc_bbox(lon, lat, keep))
    net = build(pbf, epsg, lon, lat, keep)
    n_comp, share = components(net)
    net.to_parquet(a.out / "network.parquet", index=False)
    stats = {**prov, "links": int(len(net)), "km": round(float(net.length_m.sum()) / 1000, 1),
             "components": n_comp, "largest_component_share": round(share, 4),
             "allow": {m: int(net[f"allow_{m}"].sum()) for m in ("walking", "cycling", "car", "heavy")},
             "dir_car": net["dir_car"].value_counts().to_dict(), "keep_radius_m": keep}
    (a.out / "network_build.json").write_text(json.dumps(stats, indent=1) + "\n")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
