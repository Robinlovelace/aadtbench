"""AequilibraE traffic assignment adapter (v0.2 contract).

Family ``assignment``. Assigns the tier's OD table over the mode's directed
network with AequilibraE. Two variants are fixed before any scoring:

``aon``
    All-or-nothing on free-flow time. No congestion.
``ue_bfw``
    User equilibrium with the bi-conjugate Frank-Wolfe algorithm and BPR
    delay (alpha 0.15, beta 4). Capacity per directed edge comes from the shared road
    class table in ``adapters/_base.py``. The OD table holds daily trips, so demand is scaled to a peak hour
    with a fixed factor (0.1) and link flows are scaled back by 1 / 0.1.

Walking and cycling are only supported as all-or-nothing, because capacity
and delay are not defined for them here. The ``ue_bfw`` variant raises
``Unsupported`` for those modes.

Usage:
  python -m adapters.aequilibrae --case cases/oxford-v1 \
      --tier T2_synthetic_od --modes car,heavy --variant aon \
      --out results/runs/oxford-v1/aequilibrae/aon
"""
from __future__ import annotations

import contextlib
import importlib.metadata
import os

import numpy as np
import pandas as pd

from adapters._base import (CLASS_CAPACITY_VPH, PEAK_HOUR_FACTOR, Adapter, RunContext,
                            Unsupported, directed_to_segments, run_cli)

DEFAULT_CAPACITY_VPH = 300.0
MOTOR_MODES = ("car", "heavy", "motor")
ACTIVE_MODES = ("walking", "cycling")

AON_OPTIONS = {"distance": "time", "radius_or_decay": "none", "weighting": "od",
               "congestion": "none"}
UE_OPTIONS = {"distance": "time", "radius_or_decay": "none", "weighting": "od",
              "congestion": "user equilibrium (BPR)",
              "demand": "daily trips x 0.1 as peak hour, flows x 10 back"}


class AequilibraEAssign(Adapter):
    tool = "aequilibrae"
    family = "assignment"
    options = dict(AON_OPTIONS)
    tiers = ("T2_synthetic_od", "T3_observed_od")
    modes = ("walking", "cycling", "car", "heavy", "motor")
    variants = {
        "aon": {"algorithm": "all-or-nothing", "max_iter": 1, "rgap": 1e-3,
                "options": AON_OPTIONS},
        "ue_bfw": {"algorithm": "bfw", "max_iter": 50, "rgap": 1e-3,
                   "alpha": 0.15, "beta": 4.0, "peak_hour_factor": PEAK_HOUR_FACTOR,
                   "options": UE_OPTIONS},
    }

    def tool_version(self) -> str:
        return importlib.metadata.version("aequilibrae")

    def predict(self, ctx: RunContext) -> pd.DataFrame:
        ue = ctx.params.get("algorithm") != "all-or-nothing"

        def one_mode(mode: str) -> pd.DataFrame:
            if ue and mode in ACTIVE_MODES:
                raise Unsupported(f"ue_bfw is not defined for {mode}, use the aon variant")
            edges = ctx.directed_edges(mode)
            od = ctx.od_nodes(mode)
            flow = assign(edges, od, ctx.params, mode, ctx.threads)
            return directed_to_segments(edges, flow, mode)

        return ctx.map_modes(one_mode)


def assign(edges: pd.DataFrame, od: pd.DataFrame, params: dict, mode: str,
           threads: int = 1) -> np.ndarray:
    """Assign ``od`` over ``edges`` and return one flow per row of ``edges``."""
    from aequilibrae.matrix import AequilibraeMatrix
    from aequilibrae.paths import Graph, TrafficAssignment, TrafficClass

    ue = params.get("algorithm") != "all-or-nothing"
    scale = float(params.get("peak_hour_factor", 1.0)) if ue else 1.0

    # Compact node ids from 1, as AequilibraE expects.
    raw = np.unique(edges[["u", "v"]].values.astype(np.int64))
    node_map = pd.Series(np.arange(1, len(raw) + 1, dtype=np.int64), index=raw)
    cap = (edges["road_class"].map(CLASS_CAPACITY_VPH).fillna(DEFAULT_CAPACITY_VPH)
           if mode in MOTOR_MODES else pd.Series(DEFAULT_CAPACITY_VPH, index=edges.index))
    net = pd.DataFrame({
        "link_id": np.arange(1, len(edges) + 1, dtype=np.int64),
        "a_node": node_map.loc[edges["u"].values].values,
        "b_node": node_map.loc[edges["v"].values].values,
        "direction": np.int8(1),
        "distance": edges["length_m"].values.astype(float),
        "free_flow_time": np.maximum(edges["time_s"].values.astype(float), 1e-3),
        "capacity": cap.values.astype(float),
    })

    # Demand matrix over the used OD nodes (these are the centroids).
    o = node_map.loc[od["o_node"].values].values
    d = node_map.loc[od["d_node"].values].values
    used = np.unique(np.concatenate([o, d]))
    pos = pd.Series(np.arange(len(used)), index=used)
    data = np.zeros((len(used), len(used)))
    np.add.at(data, (pos.loc[o].values, pos.loc[d].values), od["trips"].values * scale)
    mat = AequilibraeMatrix()
    mat.create_empty(zones=len(used), matrix_names=["demand"], index_names=["node_id"],
                     memory_only=True)
    mat.index[:] = used
    mat.matrix["demand"][:, :] = data
    mat.computational_view(["demand"])

    graph = Graph()
    graph.network = net
    graph.mode = "c"
    graph.prepare_graph(centroids=used)
    graph.set_blocked_centroid_flows(False)
    graph.set_graph("free_flow_time")

    tc = TrafficClass("cars", graph, mat)
    tc.set_pce(1.0)
    assig = TrafficAssignment()
    assig.set_classes([tc])
    assig.set_vdf("BPR")
    assig.set_vdf_parameters({"alpha": params.get("alpha", 0.15), "beta": params.get("beta", 4.0)})
    assig.set_capacity_field("capacity")
    assig.set_time_field("free_flow_time")
    assig.max_iter = int(params.get("max_iter", 50))
    assig.rgap_target = float(params.get("rgap", 1e-3))
    assig.set_algorithm(params.get("algorithm", "all-or-nothing"))
    assig.set_cores(max(1, int(threads)))
    # AequilibraE draws tqdm bars on stderr. Keep them out of run logs.
    with open(os.devnull, "w") as sink, contextlib.redirect_stderr(sink):
        assig.execute(log_specification=False)
    res = assig.results()
    flow = res["demand_tot"].reindex(np.arange(1, len(edges) + 1)).fillna(0.0).values
    return np.maximum(flow, 0.0) / scale


if __name__ == "__main__":
    run_cli(AequilibraEAssign)
