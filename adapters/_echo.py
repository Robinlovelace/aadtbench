"""A test adapter (not a benchmark tool, skipped by the contract check).

Flow on a segment is the mean training count on it when the harness gives
training counts (tool-calibrated track), else 1. ``sleep`` (s) delays it, to
test the time limit.
"""
from __future__ import annotations

import time

import pandas as pd

from adapters._base import Adapter, RunContext, run_cli


class Echo(Adapter):
    tool = "_echo"
    family = "other"
    options = {"distance": "none", "radius_or_decay": "none", "weighting": "none", "congestion": "none"}
    tiers = ("T0_network", "T1_open_covariates", "T2_synthetic_od")
    variants = {"default": {"sleep": 0}}

    def predict(self, ctx: RunContext) -> pd.DataFrame:
        if ctx.params.get("child"):  # a child process, as some tools start, to test the timeout kill
            import subprocess
            import sys
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            (ctx.out_dir / "child.pid").write_text(str(child.pid))
        time.sleep(float(ctx.params.get("sleep", 0)))
        seg = ctx.network["segment_id"].astype(str)
        known = pd.Series(dtype=float)
        if ctx.train_dir is not None:
            sites, xw = ctx.training_counts()
            known = xw.merge(sites, on=["site_id", "mode"]).groupby("segment_id")["value"].mean()
        out = []
        for mode in ctx.modes:
            flow = seg.map(known).fillna(0.0 if ctx.train_dir is not None else 1.0)
            out.append(pd.DataFrame({"segment_id": seg, "mode": mode, "flow": flow.values}))
        return pd.concat(out, ignore_index=True)


if __name__ == "__main__":
    run_cli(Echo)
