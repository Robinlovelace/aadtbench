#!/usr/bin/env python3
"""Multi-tool parameter sweep across all 9 benchmark cities (including paris-v1)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree

from benchmark.case import load_case
from benchmark.scoring import group_out_pooled, site_table

CASES = [
    "oxford-v1", "leeds-v1", "bristol-v1", "london-v1", "paris-v1",
    "melbourne-v1", "zurich-v1", "toronto-v1", "leuven-v1",
]

RUNS = [
    ("una", "default", "T1"),
    ("una", "shortest", "T1"),
    ("cityseer_od", "default", "T2"),
    ("cityseer_od", "dispersed", "T2"),
    ("aequilibrae", "aon", "T2"),
    ("aequilibrae", "ue_bfw", "T2"),
    ("sdna", "betweenness_angular", "T0"),
    ("sdna", "betweenness_euclidean", "T0"),
    ("sdna", "nqpd_euclidean", "T0"),
    ("sdna", "nqpd_angular", "T0"),
]

CYC_COND = {
    "cycleway": 2.5, "footway": 1.2, "minor": 1.0, "tertiary": 1.0,
    "secondary": 0.7, "primary": 0.5, "trunk": 0.25, "service": 0.5, "other": 0.8,
}
WALK_COND = {
    "footway": 1.4, "cycleway": 1.2, "minor": 1.0, "tertiary": 1.0,
    "secondary": 0.9, "primary": 0.8, "trunk": 0.3, "service": 0.6, "other": 0.8,
}
CAR_COND = {
    "motorway": 3.5, "trunk": 2.8, "primary": 1.8, "secondary": 1.4,
    "tertiary": 1.1, "minor": 0.6, "service": 0.2, "other": 0.6,
}
HVY_COND = {
    "motorway": 4.5, "trunk": 3.5, "primary": 2.0, "secondary": 1.3,
    "tertiary": 0.9, "minor": 0.4, "service": 0.1, "other": 0.4,
}


def grid_exp_kernel(mx, my, px, py, pw, cell_m=200.0, scale_m=600.0, radius_m=1800.0):
    gx = np.floor(px / cell_m).astype(np.int64)
    gy = np.floor(py / cell_m).astype(np.int64)
    df = pd.DataFrame({"gx": gx, "gy": gy, "w": pw}).groupby(["gx", "gy"], as_index=False)["w"].sum()
    cx, cy, cw = (df["gx"].values + 0.5) * cell_m, (df["gy"].values + 0.5) * cell_m, df["w"].values
    lgx, lgy = np.floor(mx / cell_m).astype(np.int64), np.floor(my / cell_m).astype(np.int64)
    l_cells, inv = np.unique(np.c_[lgx, lgy], axis=0, return_inverse=True)
    lcx, lcy = (l_cells[:, 0] + 0.5) * cell_m, (l_cells[:, 1] + 0.5) * cell_m
    pairs = cKDTree(np.c_[lcx, lcy]).sparse_distance_matrix(cKDTree(np.c_[cx, cy]), radius_m, output_type="ndarray")
    val = np.bincount(pairs["i"], cw[pairs["j"]] * np.exp(-pairs["v"] / scale_m), minlength=len(l_cells))
    return val[inv.ravel()]


def main():
    data = {}
    for cid in CASES:
        case = load_case(cid)
        net = case.network
        mid = shapely.line_interpolate_point(net.geometry.values, 0.5, normalized=True)
        mx, my = shapely.get_x(mid), shapely.get_y(mid)
        attr_t1 = grid_exp_kernel(mx, my, case.pois["x"].values, case.pois["y"].values, case.pois["weight"].values)
        sub = net["road_class"].isin({"footway", "cycleway", "service", "minor"}).values
        attr_t0 = grid_exp_kernel(mx, my, mx[sub], my[sub], np.ones(sub.sum()))
        data[cid] = (case, net, attr_t1, attr_t0)

    # Sweep grid per mode
    rows = []
    for tool, var, tier in RUNS:
        for mode in ("walking", "cycling", "car", "heavy"):
            if var == "ue_bfw" and mode in ("walking", "cycling"):
                continue
            # Parameter candidates: (bg_share, cond_exp, attr_exp)
            if mode in ("walking", "cycling"):
                cands = [
                    ("baseline", 0.0, 0.0, 0.0),
                    ("c1_bg02_a10", 0.02, 1.0, 1.0),
                    ("c1_bg05_a10", 0.05, 1.0, 1.0),
                    ("c1_bg08_a10", 0.08, 1.0, 1.0),
                    ("c07_bg05_a10", 0.05, 0.7, 1.0),
                    ("c1_bg05_a15", 0.05, 1.0, 1.5),
                ]
                cond_map = CYC_COND if mode == "cycling" else WALK_COND
            else:
                cands = [
                    ("baseline", 0.0, 0.0, 0.0),
                    ("c03_bg02", 0.02, 0.3, 0.0),
                    ("c05_bg02", 0.02, 0.5, 0.0),
                    ("c05_bg05", 0.05, 0.5, 0.0),
                    ("c07_bg03", 0.03, 0.7, 0.0),
                ]
                cond_map = HVY_COND if mode == "heavy" else CAR_COND

            for cfg_name, bg, c_exp, a_exp in cands:
                rhos, r2s, covs = [], [], []
                for cid in CASES:
                    case, net, attr_t1, attr_t0 = data[cid]
                    if mode not in case.modes:
                        continue
                    pred = pd.read_parquet(f"results/runs/{cid}/{tool}/{var}__{tier}/predictions.parquet")
                    if cfg_name == "baseline":
                        t, _ = site_table(case.sites, case.crosswalk, pred, mode, case.site_road_class())
                    else:
                        attr = attr_t0 if tier == "T0" else attr_t1
                        attr_norm = np.log1p(attr / max(np.median(attr[attr > 0]), 1.0))
                        p_sub = pred[pred["mode"] == mode].set_index("segment_id")["flow"]
                        fl = net["segment_id"].map(p_sub).fillna(0.0).values
                        med_fl = np.median(fl[fl > 0]) if (fl > 0).any() else 1.0
                        rc_cond = net["road_class"].map(cond_map).fillna(1.0).values ** c_exp
                        if a_exp > 0:
                            fl_new = (fl + bg * med_fl * np.maximum(attr_norm, 0.1)) * rc_cond * ((1.0 + attr_norm) ** a_exp)
                        else:
                            fl_new = (fl + bg * med_fl) * rc_cond
                        pred2 = pred.copy()
                        mask = pred2["mode"] == mode
                        pred2.loc[mask, "flow"] = pred2.loc[mask, "segment_id"].map(dict(zip(net["segment_id"], fl_new))).fillna(0.0)
                        t, _ = site_table(case.sites, case.crosswalk, pred2, mode, case.site_road_class())
                    m, _, _ = group_out_pooled(t, by_class=False)
                    if not m.get("ranked", False):
                        continue
                    rhos.append(m["rho"])
                    r2s.append(m["log_r2"])
                    covs.append(m["coverage"])
                rows.append({
                    "tool": tool, "variant": var, "mode": mode, "config": cfg_name,
                    "n_cities": len(rhos), "mean_rho": round(float(np.mean(rhos)), 4),
                    "mean_log_r2": round(float(np.mean(r2s)), 3),
                    "mean_coverage": round(float(np.mean(covs)), 4),
                })

    df_out = pd.DataFrame(rows)
    df_out.to_csv("notes/tool_sweep_9cities.csv", index=False)
    for (tool, var, mode), g in df_out.groupby(["tool", "variant", "mode"], sort=False):
        base = g[g["config"] == "baseline"].iloc[0]
        best = g.sort_values(["mean_rho", "mean_log_r2"], ascending=False).iloc[0]
        print(f"{tool:11s} {var:21s} {mode:7s}: {base['mean_rho']:.3f} ({base['mean_log_r2']:+6.2f}) -> {best['config']:14s} {best['mean_rho']:.3f} ({best['mean_log_r2']:+6.2f}) [d_rho={best['mean_rho']-base['mean_rho']:+.3f}, d_r2={best['mean_log_r2']-base['mean_log_r2']:+.2f}]")


if __name__ == "__main__":
    main()
