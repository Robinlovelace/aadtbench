"""The four mandatory baselines, scored like any tool (uncalibrated track).

``class_only``
    No flow. The scorer predicts the geometric mean training count of the
    site's road class (``class_lookup`` in the run record).
``centre_distance``
    ``flow = 1000 / (1000 + d)``, d the distance in metres from the link
    midpoint to the case centre, so larger means closer and busier.
``attractor_density``
    ``flow`` is the point-of-interest weight within 500 m of the link midpoint.
``population_density``
    ``flow`` is the population within 1 km of the link midpoint.

The last three are multiplied by one scale factor per mode and fold, like a
tool's flow. The same value is written for every mode a segment allows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

BASELINES = ["class_only", "centre_distance", "attractor_density", "population_density"]
BASELINE_VERSION = "2"
POI_RADIUS_M = 500.0
POP_RADIUS_M = 1000.0


def midpoints(network) -> np.ndarray:
    """Midpoint (x, y) of every link, as an (n, 2) array in the network CRS."""
    pts = network.geometry.interpolate(0.5, normalized=True)
    return np.column_stack([pts.x.values, pts.y.values])


def weight_within(mid: np.ndarray, points: pd.DataFrame, radius: float) -> np.ndarray:
    """Sum of ``points.weight`` within ``radius`` of each midpoint (cKDTree)."""
    out = np.zeros(len(mid))
    if points is None or len(points) == 0:
        return out
    xy = np.column_stack([points["x"].to_numpy(float), points["y"].to_numpy(float)])
    w = points["weight"].to_numpy(float)
    pairs = cKDTree(mid).sparse_distance_matrix(cKDTree(xy), radius, output_type="ndarray")
    if len(pairs):
        np.add.at(out, pairs["i"], w[pairs["j"]])
    return out


def segment_covariates(case) -> pd.DataFrame:
    """One row per segment with the three covariates (class_only has none)."""
    net = case.network
    mid = midpoints(net)
    cx, cy = case.centre_xy()
    df = pd.DataFrame({"segment_id": net["segment_id"].astype(str).values})
    df["centre_distance"] = 1000.0 / (1000.0 + np.hypot(mid[:, 0] - cx, mid[:, 1] - cy))
    df["attractor_density"] = weight_within(mid, case.pois, POI_RADIUS_M)
    df["population_density"] = weight_within(mid, case.population, POP_RADIUS_M)
    return df


def allowed(network, mode: str) -> np.ndarray:
    """Boolean mask of links that allow the mode. ``motor`` is car or heavy."""
    def col(name):
        return network[name].fillna(False).astype(bool).to_numpy() if name in network else np.ones(len(network), bool)
    if mode == "motor":
        return col("allow_car") | col("allow_heavy")
    return col(f"allow_{mode}")


def baseline_predictions(case, name: str, modes: list[str], covariates: pd.DataFrame | None = None) -> pd.DataFrame:
    """Predictions table (segment_id, mode, flow) for one baseline."""
    if name not in BASELINES:
        raise ValueError(f"unknown baseline {name}")
    cov = segment_covariates(case) if covariates is None and name != "class_only" else covariates
    frames = []
    for mode in modes:
        mask = allowed(case.network, mode)
        seg = case.network["segment_id"].astype(str).to_numpy()[mask]
        if name == "class_only":
            flow = np.ones(len(seg))
        else:
            flow = cov.set_index("segment_id").loc[seg, name].to_numpy(float)
        frames.append(pd.DataFrame({"segment_id": seg, "mode": mode, "flow": flow}))
    return pd.concat(frames, ignore_index=True)
