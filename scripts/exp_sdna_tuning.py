"""Capped-radius sDNA parameter sweep and AequilibraE comparison on oxford-v1 and bristol-v1.

Radii are capped to mode-appropriate trip distances:
- walking: 800 - 2500 m
- cycling: 2000 - 5000 m
- car:     2500 - 5000 m
- heavy:   2500 - 5000 m
(The 12000 m radius that caused the super-quadratic betweenness bottleneck is removed.)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from adapters._base import RunContext, directed_to_segments
from adapters.aequilibrae import AequilibraEAssign, assign
from benchmark.case import load_case
from benchmark.scoring import group_out_pooled, site_table

RADII_SWEEP: dict[str, list[int]] = {
    "walking": [800, 1000, 1500, 2000, 2500],
    "cycling": [2000, 3000, 4000, 5000],
    "car": [2500, 3500, 5000],
    "heavy": [2500, 4000, 5000],
}

MAX_BT_ORIGINS = 1200


def run_sdna_multi_radii(
    case,
    sc: pd.Series,
    mode: str,
    metric: str,
    measure: str,
    radii: list[int],
    threads: int = 16,
) -> list[dict]:
    ctx = RunContext(case.case_dir, case.manifest, "T0_network", [mode], {}, threads, case.case_dir)
    edges = ctx.directed_edges(mode)
    seg = ctx.network[ctx.network["segment_id"].isin(set(edges["segment_id"]))][
        ["segment_id", "road_class", "length_m", "geometry"]
    ].reset_index(drop=True)
    letter = {"ANGULAR": "A", "EUCLIDEAN": "E"}[metric]
    is_motor = mode in ("car", "heavy", "motor")
    if is_motor:
        kmh = edges.drop_duplicates("segment_id").set_index("segment_id").eval("length_m / time_s * 3.6")
        cond = seg["segment_id"].map(kmh).fillna(30.0).values / 30.0
        dw = np.maximum(seg["length_m"].values.astype(float) * cond, 1.0)
    else:
        cond = np.ones(len(seg))
        dw = np.ones(len(seg))

    interp_nqpd = False
    if len(seg) > MAX_BT_ORIGINS:
        pts = seg.geometry.centroid
        cell = 750.0 if measure == "Bt" else 350.0
        gx = np.floor(pts.x.values / cell).astype(int)
        gy = np.floor(pts.y.values / cell).astype(int)
        df_g = pd.DataFrame({"idx": np.arange(len(seg)), "gx": gx, "gy": gy, "dw": dw})
        top = df_g.sort_values("dw", ascending=False).drop_duplicates(["gx", "gy"])
        ow = np.zeros(len(seg))
        if measure == "Bt":
            cell_sum = df_g.groupby(["gx", "gy"])["dw"].sum()
            ow[top["idx"].values] = cell_sum.loc[list(zip(top["gx"], top["gy"]))].values
        else:
            ow[top["idx"].values] = 1.0
            interp_nqpd = True
        cfg_w = "origweight=ow;destweight=dw;skipzeroweightorigins;"
    elif is_motor:
        ow = dw
        cfg_w = "origweight=ow;destweight=dw;"
    else:
        ow = dw
        cfg_w = ""

    radii_str = ",".join(str(r) for r in radii)
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        shp = seg[["geometry"]].assign(sid=np.arange(len(seg)), ow=ow, dw=dw)[["sid", "ow", "dw", "geometry"]]
        shp.to_file(tmp_path / "in.shp")
        config = f"radii={radii_str};metric={metric};{cfg_w}nojunctions;nohull" + (
            ";nobetweenness" if measure != "Bt" else ""
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from sDNA.bin.sdnaintegral import main; sys.exit(main())",
                "-i",
                str(tmp_path / "in.shp"),
                "-o",
                str(tmp_path / "out.shp"),
                config,
            ],
            capture_output=True,
            text=True,
            env=dict(os.environ, OMP_NUM_THREADS=str(threads)),
        )
        if proc.returncode != 0:
            raise RuntimeError(f"sdnaintegral failed: {(proc.stdout + proc.stderr)[-500:]}")
        out = gpd.read_file(tmp_path / "out.shp", ignore_geometry=True)
    dt = time.perf_counter() - t0

    vprefix = "nqpd" if measure == "NQPD" else "betweenness"
    variant = f"{vprefix}_{metric.lower()}"
    rows = []
    for r in radii:
        col = f"{measure}{letter}{r}"
        raw = out[col].astype(float).fillna(0).clip(lower=0).values
        if interp_nqpd:
            vmap = pd.Series(raw[top["idx"].values], index=pd.MultiIndex.from_arrays([top["gx"], top["gy"]]))
            raw = vmap.loc[list(zip(gx, gy))].values
        flow = raw * cond
        pred = pd.DataFrame({"segment_id": seg["segment_id"].values, "mode": mode, "flow": flow})
        t, _ = site_table(case.sites, case.crosswalk, pred, mode, sc)
        m, _, _ = group_out_pooled(t)
        rows.append(
            {
                "case_id": case.case_id,
                "tool": "sdna",
                "variant": variant,
                "measure": measure,
                "metric": metric,
                "mode": mode,
                "radius_m": r,
                "rho": m["rho"],
                "log_r2": m["log_r2"],
                "coverage": m["coverage"],
                "wall_s": round(dt, 2),
            }
        )
        print(
            f"  [sdna] {case.case_id:10s} {mode:8s} {variant:22s} r={r:4d}m ({dt:5.1f}s): "
            f"rho={m['rho']:6.3f} log_r2={m['log_r2']:6.2f} cov={m['coverage']:.3f}",
            flush=True,
        )
    return rows


def run_aequilibrae_modes(case, sc: pd.Series, threads: int = 16) -> list[dict]:
    rows = []
    for mode in case.modes:
        if mode not in ("walking", "cycling", "car", "heavy"):
            continue
        ctx = RunContext(
            case.case_dir,
            case.manifest,
            "T2_synthetic_od",
            [mode],
            AequilibraEAssign.variants["ue_bfw"],
            threads,
            case.case_dir,
        )
        edges = ctx.directed_edges(mode)
        od = ctx.od_nodes(mode)
        for vname in ("aon", "ue_bfw"):
            if vname == "ue_bfw" and mode in ("walking", "cycling"):
                continue
            t0 = time.perf_counter()
            flow = assign(edges, od, AequilibraEAssign.variants[vname], mode, threads)
            dt = time.perf_counter() - t0
            pred = directed_to_segments(edges, flow, mode)
            t, _ = site_table(case.sites, case.crosswalk, pred, mode, sc)
            m, _, _ = group_out_pooled(t)
            rows.append(
                {
                    "case_id": case.case_id,
                    "tool": "aequilibrae",
                    "variant": vname,
                    "measure": vname.upper(),
                    "metric": "TIME",
                    "mode": mode,
                    "radius_m": 0,
                    "rho": m["rho"],
                    "log_r2": m["log_r2"],
                    "coverage": m["coverage"],
                    "wall_s": round(dt, 2),
                }
            )
            print(
                f"  [aeq ] {case.case_id:10s} {mode:8s} {vname:22s}          ({dt:5.1f}s): "
                f"rho={m['rho']:6.3f} log_r2={m['log_r2']:6.2f} cov={m['coverage']:.3f}",
                flush=True,
            )
    return rows


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only-nqpd", action="store_true")
    args = p.parse_args(argv)

    out_csv = Path("notes/sdna_capped_radius_sweep.csv")
    existing_rows: list[dict] = []
    if args.only_nqpd and out_csv.exists():
        df_old = pd.read_csv(out_csv)
        existing_rows = df_old[df_old["measure"] != "NQPD"].to_dict("records")

    new_rows: list[dict] = []
    measures = ("NQPD",) if args.only_nqpd else ("NQPD", "Bt")
    for cid in ("oxford-v1", "bristol-v1"):
        case = load_case(cid)
        sc = case.site_road_class()
        print(f"=== {cid} ===", flush=True)
        if not args.only_nqpd:
            new_rows.extend(run_aequilibrae_modes(case, sc, threads=16))
        for mode in case.modes:
            if mode not in RADII_SWEEP:
                continue
            radii = RADII_SWEEP[mode]
            for measure in measures:
                for metric in ("EUCLIDEAN", "ANGULAR"):
                    new_rows.extend(run_sdna_multi_radii(case, sc, mode, metric, measure, radii, threads=16))

    df = pd.DataFrame(existing_rows + new_rows)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    print(f"\nSaved {len(df)} sweep rows to {out_csv}", flush=True)


if __name__ == "__main__":
    main()
