"""Build the T1 and T2 input tables for a case."""
from __future__ import annotations

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import box

CELL_M = 1000.0
INTRAZONAL_M = 500.0
MIN_TRIPS = 0.01
TRIP_RATE = 1.0
GRAVITY = {
    "walking": (1000.0, 3000.0),
    "cycling": (3000.0, 10000.0),
    "car": (6000.0, None),
    "heavy": (12000.0, None),
}
POI_ATTRACTOR_POP_SHARE = 0.1


def build_zones(pop: pd.DataFrame, pois: pd.DataFrame, cx: float, cy: float,
                radius_m: float, cell_m: float = CELL_M) -> pd.DataFrame:
    i0, i1 = int(np.floor((cx - radius_m) / cell_m)), int(np.floor((cx + radius_m) / cell_m))
    j0, j1 = int(np.floor((cy - radius_m) / cell_m)), int(np.floor((cy + radius_m) / cell_m))
    disc = shapely.Point(cx, cy).buffer(radius_m, 64)
    recs = [(f"z{i}_{j}", i, j, box(i * cell_m, j * cell_m, (i + 1) * cell_m, (j + 1) * cell_m))
            for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)
            if box(i * cell_m, j * cell_m, (i + 1) * cell_m, (j + 1) * cell_m).intersects(disc)]
    z = pd.DataFrame(recs, columns=["zone_id", "ix", "iy", "geometry"])

    def sums(df):
        key = "z" + np.floor(df["x"] / cell_m).astype(int).astype(str) + "_" + np.floor(df["y"] / cell_m).astype(int).astype(str)
        return df.groupby(key)["weight"].sum()

    z["population"] = sums(pop).reindex(z["zone_id"]).fillna(0.0).values
    z["attractors"] = sums(pois).reindex(z["zone_id"]).fillna(0.0).values
    z["cx"] = (z["ix"] + 0.5) * cell_m
    z["cy"] = (z["iy"] + 0.5) * cell_m
    return z.drop(columns=["ix", "iy"])


def gravity_od(zones: pd.DataFrame, mode: str, intrazonal_m: float = INTRAZONAL_M) -> pd.DataFrame:
    scale, cap = GRAVITY[mode]
    xy = zones[["cx", "cy"]].to_numpy()
    d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2))
    np.fill_diagonal(d, intrazonal_m)
    pop = zones["population"].to_numpy()
    attr = zones["attractors"].to_numpy() + POI_ATTRACTOR_POP_SHARE * pop
    w = attr[None, :] * np.exp(-d / scale)
    if cap is not None:
        w = np.where(d <= cap, w, 0.0)
    tot = w.sum(axis=1, keepdims=True)
    tot[tot == 0] = 1.0
    trips = pop[:, None] * TRIP_RATE * w / tot
    oi, di = np.nonzero(trips >= MIN_TRIPS)
    ids = zones["zone_id"].to_numpy()
    return pd.DataFrame({"o_zone": ids[oi], "d_zone": ids[di], "mode": mode, "trips": trips[oi, di].astype("float32")})


def synthetic_od(zones: pd.DataFrame, modes, intrazonal_m: float = INTRAZONAL_M) -> pd.DataFrame:
    return pd.concat([gravity_od(zones, m, intrazonal_m) for m in modes if m in GRAVITY], ignore_index=True)
