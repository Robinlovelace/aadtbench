"""Open count-to-link crosswalk for AADTBench v0.2 (see BENCHMARK.md).

Rules, applied in order:

1. Mode access: a count can only match a link that allows its mode.
2. Point counts: links within 30 m (or the per-source radius). Name or ref
   match preferred. For motor modes the most important road class within 10 m
   of the nearest candidate wins. Walking and cycling take the nearest. Ties
   within 1 m go to a name or ref match, then the longest link.
3. Direction pairing: if the matched link has a `pair_segment`, the partner is
   added with weight 1. If it has none and the matched link is one way for the
   count's mode, the partner is searched per count: the nearest link within
   50 m of the count that allows the mode, is one way for it, runs the
   opposite way (travel directions more than 135 degrees apart, measured at the
   points nearest the count) and shares a name or ref (or, if the matched link
   has neither, the road class).
4. Junction arms: the count has the junction point and the arm's compass
   bearing. Candidates are links within 30 m of the junction, open to the
   mode, whose direction away from the junction (over its first 20 m) is
   within 45 degrees of the arm bearing. Motor counts take the most
   important class, then the nearest.
5. Segment counts: line overlap with a 15 m buffer. The largest overlap wins,
   but the most important class wins among overlaps within 20 percent.
6. Unmatched counts get no row.

Inputs are in one projected CRS (metres).

    network_gdf: segment_id, road_class, name, ref (optional), allow_walking,
        allow_cycling, allow_car, allow_heavy, pair_segment, geometry.
    sites_df: site_id, mode, source, x, y, optionally road_name and line_wkt.
    source_rules: {source: {"kind": "point" | "segment" | "junction",
        "radius_m": 30}}. Sources not listed are point counts at 30 m.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import shapely
from shapely import STRtree

CLASS_RANK = {
    "motorway": 9, "trunk": 8, "primary": 7, "secondary": 6, "tertiary": 5,
    "minor": 4, "service": 3, "cycleway": 2, "footway": 1, "other": 0,
}
MODE_COLUMN = {
    "walking": "allow_walking", "cycling": "allow_cycling",
    "car": "allow_car", "heavy": "allow_heavy", "motor": "allow_car",
}
POINT_RADIUS_M = 30.0
CLASS_WINDOW_M = 10.0
TIE_M = 1.0
MOTOR_MODES = {"car", "heavy", "motor"}
SEGMENT_BUFFER_M = 15.0
SEGMENT_TIE_SHARE = 0.20
PAIR_RADIUS_M = 50.0
PAIR_MIN_ANGLE = 135.0
DIR_COLUMN = {"cycling": "dir_cycling", "car": "dir_car", "heavy": "dir_car", "motor": "dir_car"}


def _norm(s) -> str:
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _name_keys(row_name, row_ref) -> set:
    keys = {_norm(row_name)}
    for part in re.split(r"[;,]", str(row_ref) if row_ref is not None else ""):
        keys.add(_norm(part))
    keys.discard("")
    return keys


def build_crosswalk(network_gdf, sites_df, source_rules=None) -> pd.DataFrame:
    """Return crosswalk rows: site_id, mode, segment_id, weight, dist_m, rule."""
    source_rules = source_rules or {}
    net = network_gdf.reset_index(drop=True)
    geoms = net.geometry.values
    tree = STRtree(geoms)
    seg_ids = net["segment_id"].astype(str).values
    rank = net["road_class"].map(CLASS_RANK).fillna(0).astype(int).values
    name_keys = [
        _name_keys(n, r)
        for n, r in zip(net["name"], net["ref"] if "ref" in net else [None] * len(net))
    ]
    allow = {m: net[c].fillna(False).astype(bool).values for m, c in MODE_COLUMN.items()
             if c in net}
    index_of = {s: i for i, s in enumerate(seg_ids)}
    pair_idx = np.full(len(net), -1)
    if "pair_segment" in net:
        for i, p in enumerate(net["pair_segment"].values):
            if isinstance(p, str) and p in index_of:
                pair_idx[i] = index_of[p]

    dirs = {m: net[c].fillna("both").astype(str).values for m, c in DIR_COLUMN.items() if c in net}
    rows = []
    for rec in sites_df.itertuples(index=False):
        rule = source_rules.get(rec.source, {})
        kind = rule.get("kind", "point")
        mode_ok = allow.get(rec.mode)
        if mode_ok is None:
            continue
        if kind == "junction":
            hit = _match_junction(rec, tree, geoms, rank, mode_ok)
            label = "junction"
        elif kind == "segment":
            hit = _match_segment(rec, tree, geoms, rank, mode_ok)
            label = "segment"
        else:
            hit = _match_point(rec, rule.get("radius_m", POINT_RADIUS_M), tree,
                               geoms, rank, mode_ok, name_keys)
            label = "point"
        if hit is None:
            continue
        i, dist = hit
        rows.append((rec.site_id, rec.mode, seg_ids[i], 1.0, round(float(dist), 2), label))
        j = pair_idx[i]
        if j < 0:
            j = _find_partner(rec, i, tree, geoms, rank, mode_ok, name_keys,
                              dirs.get(rec.mode))
        if j >= 0:
            rows.append((rec.site_id, rec.mode, seg_ids[j], 1.0,
                         round(float(shapely.distance(geoms[j], shapely.points(rec.x, rec.y))), 2),
                         "pair"))
    return pd.DataFrame(rows, columns=["site_id", "mode", "segment_id", "weight", "dist_m", "rule"])


def _match_point(rec, radius, tree, geoms, rank, mode_ok, name_keys):
    pt = shapely.points(rec.x, rec.y)
    cand = tree.query(pt, predicate="dwithin", distance=radius)
    cand = cand[mode_ok[cand]]
    if len(cand) == 0:
        return None
    dist = shapely.distance(geoms[cand], pt)
    site_name = _norm(getattr(rec, "road_name", None))
    is_named = np.zeros(len(cand), bool)
    if site_name:
        is_named = np.array([site_name in name_keys[c] for c in cand])
        if is_named.any():
            cand, dist, is_named = cand[is_named], dist[is_named], is_named[is_named]
    if rec.mode in MOTOR_MODES:
        # most important class within 10 m of the nearest candidate
        window = dist <= dist.min() + CLASS_WINDOW_M
        cand, dist, is_named = cand[window], dist[window], is_named[window]
        top = rank[cand] == rank[cand].max()
        cand, dist, is_named = cand[top], dist[top], is_named[top]
    # exact or near ties (within 1 m): name or ref match first, then the longest link
    tied = dist <= dist.min() + TIE_M
    cand, dist, is_named = cand[tied], dist[tied], is_named[tied]
    length = shapely.length(geoms[cand])
    order = np.lexsort((dist, -length, -is_named.astype(int)))
    k = int(order[0])
    return int(cand[k]), float(dist[k])


def _match_segment(rec, tree, geoms, rank, mode_ok):
    line_wkt = getattr(rec, "line_wkt", None)
    if not isinstance(line_wkt, str):
        return None
    line = shapely.from_wkt(line_wkt)
    buf = shapely.buffer(line, SEGMENT_BUFFER_M)
    cand = tree.query(buf, predicate="intersects")
    cand = cand[mode_ok[cand]]
    if len(cand) == 0:
        return None
    overlap = shapely.length(shapely.intersection(geoms[cand], buf))
    keep = overlap > 0
    cand, overlap = cand[keep], overlap[keep]
    if len(cand) == 0:
        return None
    close = overlap >= overlap.max() * (1 - SEGMENT_TIE_SHARE)
    cand, overlap = cand[close], overlap[close]
    top = rank[cand] == rank[cand].max()
    cand, overlap = cand[top], overlap[top]
    k = int(np.argmax(overlap))
    return int(cand[k]), float(shapely.distance(geoms[cand[k]], line))


def _travel_bearing(geom, pt, direction: str) -> float:
    """Bearing (degrees) of travel along a link at the point nearest ``pt``."""
    d = shapely.line_locate_point(geom, pt)
    L = shapely.length(geom)
    a = shapely.line_interpolate_point(geom, max(d - 5.0, 0.0))
    b = shapely.line_interpolate_point(geom, min(d + 5.0, L))
    dx, dy = shapely.get_x(b) - shapely.get_x(a), shapely.get_y(b) - shapely.get_y(a)
    ang = np.degrees(np.arctan2(dy, dx))
    return ang + 180.0 if direction == "backward" else ang


def _find_partner(rec, i, tree, geoms, rank, mode_ok, name_keys, dirs) -> int:
    """Opposite carriageway of a one-way matched link, or -1 (rule 3)."""
    if dirs is None or dirs[i] == "both":
        return -1
    pt = shapely.points(rec.x, rec.y)
    cand = tree.query(pt, predicate="dwithin", distance=PAIR_RADIUS_M)
    cand = cand[(cand != i) & mode_ok[cand]]
    cand = cand[dirs[cand] != "both"]
    if len(cand) == 0:
        return -1
    if name_keys[i]:
        cand = cand[[bool(name_keys[i] & name_keys[c]) for c in cand]]
    else:
        cand = cand[rank[cand] == rank[i]]
    if len(cand) == 0:
        return -1
    b0 = _travel_bearing(geoms[i], pt, dirs[i])
    ok = []
    for c in cand:
        diff = abs((_travel_bearing(geoms[c], pt, dirs[c]) - b0 + 180.0) % 360.0 - 180.0)
        ok.append(diff > PAIR_MIN_ANGLE)
    cand = cand[np.array(ok, bool)]
    if len(cand) == 0:
        return -1
    return int(cand[np.argmin(shapely.distance(geoms[cand], pt))])


ARM_RADIUS_M = 30.0
ARM_MAX_ANGLE = 45.0


def _match_junction(rec, tree, geoms, rank, mode_ok):
    """Rule 4: the approach link of a junction arm, by bearing."""
    pt = shapely.points(rec.x, rec.y)
    cand = tree.query(pt, predicate="dwithin", distance=ARM_RADIUS_M)
    cand = cand[mode_ok[cand]]
    if len(cand) == 0 or not np.isfinite(getattr(rec, "bearing", np.nan)):
        return None
    ok, dist = [], []
    for c in cand:
        g = geoms[c]
        L = shapely.length(g)
        start = shapely.get_point(g, 0)
        from_start = shapely.distance(start, pt) <= shapely.distance(shapely.get_point(g, -1), pt)
        a = start if from_start else shapely.get_point(g, -1)
        b = shapely.line_interpolate_point(g, min(20.0, L) if from_start else max(L - 20.0, 0.0))
        brg = np.degrees(np.arctan2(shapely.get_x(b) - shapely.get_x(a), shapely.get_y(b) - shapely.get_y(a))) % 360
        diff = abs((brg - rec.bearing + 180.0) % 360.0 - 180.0)
        ok.append(diff <= ARM_MAX_ANGLE)
        dist.append(float(shapely.distance(a, pt)))
    ok, dist = np.array(ok, bool), np.array(dist)
    cand, dist = cand[ok], dist[ok]
    if len(cand) == 0:
        return None
    if rec.mode in MOTOR_MODES:
        top = rank[cand] == rank[cand].max()
        cand, dist = cand[top], dist[top]
    k = int(np.argmin(dist))
    return int(cand[k]), float(dist[k])
