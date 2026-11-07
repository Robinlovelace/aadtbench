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

RADIUS_M = {"walking": 1000, "cycling": 2000, "car": 2500, "heavy": 2500, "motor": 2500}
METRIC_LETTER = {"ANGULAR": "A", "EUCLIDEAN": "E", "HYBRID": "H"}


class SDNA(Adapter):
    tool = "sdna"
    family = "flow"
    options = {"distance": "angular", "radius_or_decay": "radius per mode (Euclidean, m)",
               "weighting": "link count (unweighted)", "congestion": "none"}
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
            seg = net[net["segment_id"].isin(set(ctx.directed_edges(mode)["segment_id"]))][
                ["segment_id", "geometry"]
            ].reset_index(drop=True)
            if seg.empty:
                raise Unsupported(f"no {mode} segments")
            radius = int(ctx.params["radius_m"][mode])
            with tempfile.TemporaryDirectory(dir=ctx.out_dir) as tmp:
                tmp = Path(tmp)
                shp = seg[["geometry"]].assign(sid=np.arange(len(seg)))[["sid", "geometry"]]
                shp.to_file(tmp / "in.shp")
                config = (f"radii={radius};metric={metric};weight_type=Link;"
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
            flow = out[col].astype(float).fillna(0).clip(lower=0).values
            return pd.DataFrame({"segment_id": seg["segment_id"].values, "mode": mode, "flow": flow})

        return ctx.map_modes(one_mode)


if __name__ == "__main__":
    run_cli(SDNA)
