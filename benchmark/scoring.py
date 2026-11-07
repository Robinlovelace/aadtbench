"""Scoring: site tables, scale factor per mode and fold, group-out and leave-one-city-out."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

MIN_RANKED_SITES = 20
METRIC_COLUMNS = ["n_sites", "rho", "log_r2", "raw_r2", "calibration_ratio", "coverage"]


def site_table(sites: pd.DataFrame, crosswalk: pd.DataFrame, predictions: pd.DataFrame,
               mode: str, site_class: pd.Series | None = None) -> tuple[pd.DataFrame, dict]:
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
    xw["wflow"] = xw["flow"].fillna(0.0).clip(lower=0.0) * xw["weight"].astype(float)
    agg = xw.groupby("site_id", as_index=False)["wflow"].sum().rename(columns={"wflow": "flow"})
    t = s.merge(agg, on="site_id", how="inner")
    if site_class is not None:
        cls = site_class.xs(mode, level="mode") if "mode" in site_class.index.names else site_class
        t["road_class"] = t["site_id"].map(cls).fillna("other")
    else:
        t["road_class"] = "other"
    keep = [c for c in ("site_id", "value", "flow", "road_class", "fold", "group_id") if c in t.columns]
    info = {"n_sites_total": int(len(s)), "n_sites_matched": int(len(t)),
            "n_unmatched": int(len(s) - len(t)), "n_missing_segment_preds": n_missing}
    return t[keep].reset_index(drop=True), info


def metrics_from(obs, pred, unscaled_flow) -> dict:
    obs, pred, flow = np.asarray(obs, float), np.asarray(pred, float), np.asarray(unscaled_flow, float)
    ok = np.isfinite(obs) & np.isfinite(pred)
    obs, pred, flow = obs[ok], pred[ok], flow[ok]
    out = {"n_sites": int(len(obs)), "rho": np.nan, "log_r2": np.nan, "raw_r2": np.nan,
           "calibration_ratio": np.nan, "coverage": float(np.mean(flow > 0)) if len(flow) else np.nan}
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
    return out


def fit_scale_factor(flow, count) -> float:
    flow, count = np.asarray(flow, float), np.asarray(count, float)
    ok = np.isfinite(flow) & np.isfinite(count) & (flow > 0) & (count > 0)
    return float(np.exp(np.mean(np.log(count[ok] / flow[ok])))) if ok.any() else 1.0


def class_lookup(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    pos = train[train["value"] > 0]
    gm = np.exp(np.log(pos["value"]).groupby(pos["road_class"]).mean())
    overall = float(np.exp(np.log(pos["value"]).mean())) if len(pos) else 0.0
    return test["road_class"].map(gm).fillna(overall).to_numpy(float)


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame, scale: bool = True,
                 by_class: bool = False) -> tuple[np.ndarray, dict]:
    if by_class:
        return class_lookup(train, test), {"rule": "class geometric mean"}
    flow = np.maximum(test["flow"].to_numpy(float), 0.0)
    k = fit_scale_factor(train["flow"], train["value"]) if scale else 1.0
    return k * flow, {"scale_factor": k}


def group_out_pooled(table: pd.DataFrame, scale: bool = True, by_class: bool = False) -> tuple[dict, pd.DataFrame, list[dict]]:
    t = table.dropna(subset=["fold", "value", "flow"]).copy()
    t["oof"] = np.nan
    coefs = []
    for f in sorted(t["fold"].unique()):
        test = t["fold"] == f
        train = t[~test]
        if len(train) < 3:
            continue
        pred, c = _fit_predict(train, t[test], scale, by_class)
        t.loc[test, "oof"] = pred
        coefs.append({"fold": f, **c})
    m = metrics_from(t["value"], t["oof"], t["flow"])
    m["ranked"] = bool(m["n_sites"] >= MIN_RANKED_SITES)
    return m, t, coefs


def leave_one_city_out(tables: dict[str, pd.DataFrame], scale: bool = True, by_class: bool = False) -> dict[str, tuple[dict, pd.DataFrame, dict]]:
    if len(tables) < 2:
        raise ValueError("leave-one-city-out needs at least two cases")
    out = {}
    for cid, test in tables.items():
        train = pd.concat([t for k, t in tables.items() if k != cid], ignore_index=True)
        test = test.dropna(subset=["value", "flow"]).copy()
        pred, c = _fit_predict(train, test, scale, by_class)
        test["oof"] = pred
        m = metrics_from(test["value"], test["oof"], test["flow"])
        m["ranked"] = bool(m["n_sites"] >= MIN_RANKED_SITES)
        out[cid] = (m, test, c)
    return out
