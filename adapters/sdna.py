"""sDNA adapter."""
from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from adapters._base import Adapter, RunContext, Unsupported, run_cli

RADIUS_M = {"walking": 2000, "cycling": 5000, "car": 5000, "heavy": 5000, "motor": 5000}
METRIC_LETTER = {"ANGULAR": "A", "EUCLIDEAN": "E", "HYBRID": "H"}
MAX_BT_ORIGINS = 1200


class SDNA(Adapter):
    tool = "sdna"
    family = "flow"
    options = {"distance": "angular", "radius_or_decay": "radius per mode (Euclidean, m)",
               "weighting": "link length (m)", "congestion": "none"}
    tiers = ("T0_network", "T1_open_covariates", "T2_synthetic_od", "T3_observed_od")
    modes = ("walking", "cycling", "car", "heavy", "motor")
    variants = {
        "betweenness_angular": {"metric": "ANGULAR", "measure": "Bt", "radius_m": RADIUS_M, "family": "flow"},
        "betweenness_euclidean": {"metric": "EUCLIDEAN", "measure": "Bt", "radius_m": RADIUS_M,
                                  "family": "flow", "options": {"distance": "Euclidean"}},
        "nqpd_euclidean": {"metric": "EUCLIDEAN", "measure": "NQPD", "radius_m": RADIUS_M,
                           "family": "reach",
                           "options": {"distance": "Euclidean",
                                       "radius_or_decay": "radius per mode, NQPD gravity (1/distance)"}},
        "nqpd_angular": {"metric": "ANGULAR", "measure": "NQPD", "radius_m": RADIUS_M,
                         "family": "reach",
                         "options": {"radius_or_decay": "radius per mode, NQPD gravity (angular)"}},
    }

    def tool_version(self) -> str:
        return importlib.metadata.version("sdna-plus")

    def predict(self, ctx: RunContext) -> pd.DataFrame:
        net = ctx.network
        metric, measure = ctx.params["metric"], ctx.params["measure"]
        letter = METRIC_LETTER[metric]

        def one_mode(mode: str) -> pd.DataFrame:
            edges = ctx.directed_edges(mode)
            seg = net[net["segment_id"].isin(set(edges["segment_id"]))][
                ["segment_id", "road_class", "length_m", "geometry"]
            ].reset_index(drop=True)
            if seg.empty:
                raise Unsupported(f"no {mode} segments")
            radius = int(ctx.params["radius_m"][mode])
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
            with tempfile.TemporaryDirectory(dir=ctx.out_dir) as tmp:
                tmp = Path(tmp)
                shp = seg[["geometry"]].assign(sid=np.arange(len(seg)), ow=ow, dw=dw)[["sid", "ow", "dw", "geometry"]]
                shp.to_file(tmp / "in.shp")
                config = (f"radii={radius};metric={metric};{cfg_w}"
                          "nojunctions;nohull" + (";nobetweenness" if measure != "Bt" else ""))
                proc = subprocess.run(
                    [sys.executable, "-c",
                     "import sys; from sDNA.bin.sdnaintegral import main; sys.exit(main())",
                     "-i", str(tmp / "in.shp"), "-o", str(tmp / "out.shp"), config],
                    capture_output=True, text=True,
                    env=dict(os.environ, OMP_NUM_THREADS=str(max(1, int(ctx.threads)))))
                if proc.returncode != 0:
                    raise RuntimeError(f"sdnaintegral failed: {(proc.stdout + proc.stderr)[-500:]}")
                import geopandas as gpd
                out = gpd.read_file(tmp / "out.shp", ignore_geometry=True)
            col = f"{measure}{letter}{radius}"
            if col not in out.columns:
                raise RuntimeError(f"sDNA output has no column {col}: {list(out.columns)}")
            raw = out[col].astype(float).fillna(0).clip(lower=0).values
            if interp_nqpd:
                vmap = pd.Series(raw[top["idx"].values], index=pd.MultiIndex.from_arrays([top["gx"], top["gy"]]))
                raw = vmap.loc[list(zip(gx, gy))].values
            flow = ctx.modulate_segment_flow(seg["segment_id"].values, raw * cond, mode)
            return pd.DataFrame({"segment_id": seg["segment_id"].values, "mode": mode, "flow": flow})

        return ctx.map_modes(one_mode)


if __name__ == "__main__":
    run_cli(SDNA)
