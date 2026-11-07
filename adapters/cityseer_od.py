"""cityseer OD betweenness adapter."""
from __future__ import annotations

import importlib.metadata

import networkx as nx
import numpy as np
import pandas as pd

from adapters._base import Adapter, RunContext, Unsupported, run_cli

RADIUS_M = {"walking": 3000, "cycling": 8000, "car": 20000, "heavy": 30000, "motor": 20000}
REF_KMH = 30.0


class CityseerOD(Adapter):
    tool = "cityseer_od"
    family = "flow"
    options = {"distance": "metric (motor modes: class speed weighted)",
               "radius_or_decay": "radius per mode", "weighting": "od", "congestion": "none"}
    tiers = ("T2_synthetic_od", "T3_observed_od")
    modes = ("walking", "cycling", "car", "heavy", "motor")
    variants = {
        "default": {"radius_m": RADIUS_M, "tolerance": 0.0},
        "dispersed": {"radius_m": RADIUS_M, "tolerance": 3.0,
                      "options": {"radius_or_decay": "radius per mode, 3 percent path tolerance"}},
    }

    def tool_version(self) -> str:
        return importlib.metadata.version("cityseer")

    def predict(self, ctx: RunContext) -> pd.DataFrame:
        from cityseer import config
        from cityseer.metrics import networks as cs
        from cityseer.tools import io

        config.QUIET_MODE = True
        net = ctx.network

        def one_mode(mode: str) -> pd.DataFrame:
            edges = ctx.directed_edges(mode)
            seg = net[net["segment_id"].isin(set(edges["segment_id"]))]
            if mode in ("car", "heavy", "motor"):
                kmh = edges.drop_duplicates("segment_id").set_index("segment_id").eval("length_m / time_s * 3.6")
                imp = dict(zip(seg["segment_id"], (REF_KMH / seg["segment_id"].map(kmh)).fillna(1.0)))
            else:
                imp = dict.fromkeys(seg["segment_id"], 1.0)
            geom_map = dict(zip(seg["segment_id"], seg["geometry"]))
            G = nx.MultiDiGraph()
            nodes = ctx.node_xy()
            for u, v, sid in edges[["u", "v", "segment_id"]].itertuples(index=False):
                for n in (u, v):
                    if str(n) not in G:
                        G.add_node(str(n), x=float(nodes.at[n, "x"]), y=float(nodes.at[n, "y"]))
                if u != v:
                    G.add_edge(str(u), str(v), geom=geom_map[sid], imp_factor=float(imp[sid]), segment_id=sid)
            G.graph["crs"] = net.crs.to_epsg()
            nodes_df, _, structure = io.network_structure_from_nx(G)
            pos = pd.Series(np.arange(len(nodes_df)), index=nodes_df.index)
            od = ctx.od_nodes(mode)
            od["o_node"], od["d_node"] = od["o_node"].astype(str), od["d_node"].astype(str)
            od = od[od["o_node"].isin(pos.index) & od["d_node"].isin(pos.index)]
            if od.empty:
                raise Unsupported(f"no OD pairs snap to the {mode} network")
            radius = int(ctx.params["radius_m"][mode])
            matrix = cs.rustalgos.centrality.OdMatrix(
                pos[od["o_node"]].tolist(), pos[od["d_node"]].tolist(), od["trips"].astype(float).tolist())
            res = cs.betweenness_od(network_structure=structure, nodes_gdf=nodes_df.copy(),
                                    od_matrix=matrix, distances=[radius],
                                    tolerance=ctx.params.get("tolerance") or None,
                                    betweenness={"betweenness": "1"})
            node_flow = res[f"cc_betweenness_{radius}"].astype(float)
            node_flow.index = node_flow.index.astype(str)
            flow = (seg["u"].astype(str).map(node_flow).fillna(0).values
                    + seg["v"].astype(str).map(node_flow).fillna(0).values) / 2
            return pd.DataFrame({"segment_id": seg["segment_id"].values, "mode": mode, "flow": flow})

        return ctx.map_modes(one_mode)


if __name__ == "__main__":
    run_cli(CityseerOD)
