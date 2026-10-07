"""sDNA adapter (v0.2 contract).

sDNA (spatial Design Network Analysis, Cardiff University, Crispin Cooper) is
open source under AGPL v3. This adapter runs the ``sdnaintegral`` command line
tool from the ``sdna-plus`` package on a shapefile of the mode's segments and
reads one output column per segment. It needs only the network, so it works at
every tier and ignores the OD table and the covariates. Turn restrictions and
one-way rules are ignored, as sDNA integral analysis works on the links as drawn.

Variants (fixed before any scoring):
  betweenness_angular    family flow. Angular betweenness (``BtA``), Euclidean radius.
  betweenness_euclidean  family flow. Shortest path betweenness (``BtE``).
  nqpd_euclidean         family reach. Network quantity penalised by distance
                         (``NQPDE``), the gravity measure, Euclidean distance.
  nqpd_angular           family reach. NQPD with angular distance (``NQPDA``).

All four count links (``weight_type=Link``, no origin or destination weights),
so no population or land use enters. Radii are metres of Euclidean distance.

Usage:
  python -m adapters.sdna --case cases/oxford-v1 --tier T0_network \
      --modes car,cycling --out results/runs/oxford-v1/sdna/betweenness_angular
"""
from __future__ import annotations

import importlib.metadata
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from adapters._base import Adapter, RunContext, Unsupported, run_cli

# Radius (m) per mode, set from typical trip lengths and not tuned on counts.
RADIUS_M = {"walking": 2000, "cycling": 5000, "car": 10000, "heavy": 10000, "motor": 10000}
METRIC_LETTER = {"ANGULAR": "A", "EUCLIDEAN": "E", "HYBRID": "H"}


class SDNA(Adapter):
    tool = "sdna"
    family = "flow"
    options = {"distance": "angular", "radius_or_decay": "radius per mode (Euclidean, m)",
               "weighting": "link count (unweighted)", "congestion": "none"}
    tiers = ("T0_network", "T1_open_covariates", "T2_synthetic_od", "T3_observed_od")
    modes = ("walking", "cycling", "car", "heavy", "motor")
    variants = {
        "betweenness_angular": {"metric": "ANGULAR", "measure": "Bt", "radius_m": RADIUS_M,
                                "family": "flow"},
        "betweenness_euclidean": {"metric": "EUCLIDEAN", "measure": "Bt", "radius_m": RADIUS_M,
                                  "family": "flow",
                                  "options": {"distance": "Euclidean"}},
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
            seg_ids = set(ctx.directed_edges(mode)["segment_id"])
            seg = net[net["segment_id"].isin(seg_ids)][["segment_id", "geometry"]].reset_index(drop=True)
            if seg.empty:
                raise Unsupported(f"no {mode} segments")
            radius = int(ctx.params["radius_m"][mode])
            with tempfile.TemporaryDirectory(dir=ctx.out_dir) as tmp:
                tmp = Path(tmp)
                shp = seg[["geometry"]].copy()
                shp["sid"] = np.arange(len(seg))
                shp[["sid", "geometry"]].to_file(tmp / "in.shp")
                config = (f"radii={radius};metric={metric};weight_type=Link;"
                          "nojunctions;nohull" + (";nobetweenness" if measure != "Bt" else ""))
                proc = subprocess.run(
                    [sys.executable, "-c",
                     "import sys; from sDNA.bin.sdnaintegral import main; sys.exit(main())",
                     "-i", str(tmp / "in.shp"), "-o", str(tmp / "out.shp"), config],
                    capture_output=True, text=True)
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
