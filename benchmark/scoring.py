"""Scoring: site tables, raw and calibrated tracks, group-out and leave-one-city-out.

This module knows nothing about individual tools. It joins predictions to the
case crosswalk and calculates every published metric.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from benchmark.calibrator import fit_calibrator, fit_scale_factor

MIN_RANKED_SITES = 20
TRACKS = ("raw", "calibrated")
METRIC_COLUMNS = ["n_sites", "rho", "log_r2", "raw_r2", "calibration_ratio", "q"]


def site_table(sites: pd.DataFrame, crosswalk: pd.DataFrame, predictions: pd.DataFrame,
               mode: str, site_class: pd.Series | None = None) -> tuple[pd.DataFrame, dict]:
    """Build the scored site table for one mode.

    A site's flow is the weighted sum of segment flows over its crosswalk
    rows. A segment with no prediction counts as 0 flow. Sites with no
    crosswalk row are left out and counted in the returned info.

    ``site_class`` maps (site_id, mode) to a road class (see
    ``Case.site_road_class``). Without it every site gets ``other``.
    """
    s = sites[sites["mode"] == mode].copy()
    s["site_id"] = s["site_id"].astype(str)
    xw = crosswalk[crosswalk["mode"] == mode].copy()
    xw["site_id"] = xw["site_id"].astype(str)
    xw["segment_id"] = xw["segment_id"].astype(str)
    pr = predictions[predictions["mode"] == mode][["segment_id", "flow"]].copy()
    pr["segment_id"] = pr["segment_id"].astype(str)
    pr = pr.groupby("segment_id", as_index=False)["flow"].sum()
    xw = xw.merge(pr, on="segment_id", how="left")
    n_missing = int(xw["flow"].isna().sum())
    xw["flow"] = xw["flow"].fillna(0.0).clip(lower=0.0)
    xw["wflow"] = xw["flow"] * xw["weight"].astype(float)
    agg = xw.groupby("site_id", as_index=False)["wflow"].sum().rename(columns={"wflow": "flow"})
    t = s.merge(agg, on="site_id", how="inner")
    if site_class is not None:
        cls = site_class.xs(mode, level="mode") if "mode" in site_class.index.names else site_class
        t["road_class"] = t["site_id"].map(cls).fillna("other")
    else:
        t["road_class"] = "other"
    keep = ["site_id", "value", "flow", "road_class", "fold", "group_id"]
    t = t[[c for c in keep if c in t.columns]].reset_index(drop=True)
    info = {"n_sites_total": int(len(s)), "n_sites_matched": int(len(t)),
            "n_unmatched": int(len(s) - len(t)), "n_missing_segment_preds": n_missing}
    return t, info


def metrics_from(obs, pred, unscaled_flow) -> dict:
    """Metrics on pooled out-of-fold predictions."""
    obs = np.asarray(obs, float)
    pred = np.asarray(pred, float)
    flow = np.asarray(unscaled_flow, float)
    ok = np.isfinite(obs) & np.isfinite(pred)
    obs, pred, flow = obs[ok], pred[ok], flow[ok]
    out = {"n_sites": int(len(obs)), "rho": np.nan, "log_r2": np.nan, "raw_r2": np.nan,
           "calibration_ratio": np.nan, "q": np.nan}
    if len(obs) < 3:
        return out

    def r2(o, p):
        sst = float(np.sum((o - o.mean()) ** 2))
        return np.nan if sst == 0 else float(1 - np.sum((o - p) ** 2) / sst)

    if np.ptp(pred) > 0 and np.ptp(obs) > 0:
        out["rho"] = float(stats.spearmanr(obs, pred).statistic)
    out["log_r2"] = r2(np.log1p(obs), np.log1p(np.maximum(pred, 0)))
    out["raw_r2"] = r2(obs, pred)
    if flow.sum() > 0:
        out["calibration_ratio"] = float(obs.sum() / flow.sum())
    out["q"] = float((out["rho"] + out["log_r2"]) / 2)
    return out


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame, track: str, covariate: bool,
                 scale: bool) -> tuple[np.ndarray, dict]:
    if track == "calibrated":
        cal = fit_calibrator(train["flow"], train["road_class"], train["value"], covariate=covariate)
        return cal.predict(test["flow"], test["road_class"]), cal.coefficients()
    if track == "raw":
        if not scale:
            return np.maximum(test["flow"].to_numpy(float), 0.0), {"scale_factor": 1.0}
        sf = fit_scale_factor(train["flow"], train["value"])
        return sf.predict(test["flow"]), sf.coefficients()
    raise ValueError(f"unknown track {track}")


def group_out_pooled(table: pd.DataFrame, track: str, covariate: bool = True,
                     scale: bool = True) -> tuple[dict, pd.DataFrame, list[dict]]:
    """Spatial group-out scoring on the pre-assigned folds.

    For each fold the calibrator (or scale factor) is fitted on the other
    folds and predicts the held-out fold. Predictions are pooled and scored
    once. Returns (metrics, table with an ``oof`` column, per-fold coefficients).
    ``scale=False`` on the raw track uses the flow as submitted (for
    self-calibrated flows).
    """
    t = table.dropna(subset=["fold", "value", "flow"]).copy()
    t["oof"] = np.nan
    coefs = []
    for f in sorted(t["fold"].unique()):
        test = t["fold"] == f
        train = t[~test]
        if len(train) < 3:
            continue
        pred, c = _fit_predict(train, t[test], track, covariate, scale)
        t.loc[test, "oof"] = pred
        coefs.append({"fold": f, **c})
    m = metrics_from(t["value"], t["oof"], t["flow"])
    m["ranked"] = bool(m["n_sites"] >= MIN_RANKED_SITES)
    return m, t, coefs


def leave_one_city_out(tables: dict[str, pd.DataFrame], track: str, covariate: bool = True,
                       scale: bool = True) -> dict[str, tuple[dict, pd.DataFrame, dict]]:
    """For one mode: fit on every other case's sites, score the held-out case.

    ``tables`` maps case id to its site table (all folds are used). Needs at
    least two cases. Returns {case_id: (metrics, table with oof, coefficients)}.
    """
    if len(tables) < 2:
        raise ValueError("leave-one-city-out needs at least two cases")
    out = {}
    for cid, test in tables.items():
        train = pd.concat([t for k, t in tables.items() if k != cid], ignore_index=True)
        test = test.dropna(subset=["value", "flow"]).copy()
        pred, c = _fit_predict(train, test, track, covariate, scale)
        test["oof"] = pred
        m = metrics_from(test["value"], test["oof"], test["flow"])
        m["ranked"] = bool(m["n_sites"] >= MIN_RANKED_SITES)
        out[cid] = (m, test, c)
    return out
