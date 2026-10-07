import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial import cKDTree

def compute_metrics(observed, predicted):
    """Compute R2, Pearson r, Spearman r for observed and predicted values."""
    obs = np.array(observed, dtype=float)
    pred = np.array(predicted, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(pred))
    obs, pred = obs[mask], pred[mask]
    n = len(obs)
    if n < 3 or np.all(pred == pred[0]):
        return {"n": n, "r_squared": np.nan, "pearson_r": np.nan, "spearman_r": np.nan}
    
    r2 = stats.linregress(pred, obs).rvalue ** 2
    pr, _ = stats.pearsonr(obs, pred)
    sr, _ = stats.spearmanr(obs, pred)
    
    return {
        "n": n,
        "r_squared": float(r2),
        "pearson_r": float(pr),
        "spearman_r": float(sr)
    }

def compute_metrics_loglog(observed, predicted):
    """Log-log variant of compute_metrics: R2/Pearson/Spearman computed on
    log1p-transformed observed & predicted values. Appropriate for ground
    truth spanning orders of magnitude (e.g. DfT AADT: ~100 to ~150,000
    vehicles/day), where linear R2 is dominated by the handful of largest
    values. Spearman is rank-based so it is identical under a log transform
    and is included only for consistency with compute_metrics' output shape.
    """
    obs = np.array(observed, dtype=float)
    pred = np.array(predicted, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(pred)) & (obs >= 0) & (pred >= 0)
    obs, pred = obs[mask], pred[mask]
    n = len(obs)
    if n < 3 or np.all(pred == pred[0]):
        return {"n": n, "r_squared": np.nan, "pearson_r": np.nan, "spearman_r": np.nan}

    log_obs, log_pred = np.log1p(obs), np.log1p(pred)
    r2 = stats.linregress(log_pred, log_obs).rvalue ** 2
    pr, _ = stats.pearsonr(log_obs, log_pred)
    sr, _ = stats.spearmanr(obs, pred)

    return {
        "n": n,
        "r_squared": float(r2),
        "pearson_r": float(pr),
        "spearman_r": float(sr)
    }

def filter_stubs(edge_gdf, graph, length_col="length", start_col="start", end_col="end", min_length=15.0):
    """Identify and filter stubs (degree-1 nodes or short edges) in the network."""
    degree = dict(graph.degree())
    is_stub = []
    for idx, row in edge_gdf.iterrows():
        u_deg = degree.get(row[start_col], 0)
        v_deg = degree.get(row[end_col], 0)
        if u_deg <= 1 or v_deg <= 1 or row[length_col] < min_length:
            is_stub.append(True)
        else:
            is_stub.append(False)
    edge_gdf['is_stub'] = is_stub
    return edge_gdf[~edge_gdf['is_stub']].copy()

def match_sensors_to_edges(non_stub_gdf, tel_utm, match_dist=200):
    """Snap sensors to nearest edge centroids and return matched indices, distances, and mask."""
    if len(non_stub_gdf) == 0:
        matched = np.zeros(len(tel_utm), dtype=bool)
        idxs = np.zeros(len(tel_utm), dtype=int)
        dists = np.full(len(tel_utm), np.inf)
        return matched, idxs, dists

    edge_centroids = np.array([(g.x, g.y) for g in non_stub_gdf.geometry.centroid])
    tel_xy = np.array([(g.x, g.y) for g in tel_utm.geometry])
    
    tree = cKDTree(edge_centroids)
    dists, idxs = tree.query(tel_xy)
    matched = dists <= match_dist
    return matched, idxs, dists
