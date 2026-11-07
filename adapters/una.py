"""Urban Network Analysis (UNA) flow adapter."""
from __future__ import annotations

import importlib.metadata
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from adapters._base import Adapter, RunContext, Unsupported, run_cli

RADIUS_M = {"walking": 2000, "cycling": 6000, "car": 12000, "heavy": 15000, "motor": 12000}
BETA = {"walking": 1.0 / 1000.0, "cycling": 1.0 / 3000.0, "car": 1.0 / 6000.0,
        "heavy": 1.0 / 12000.0, "motor": 1.0 / 6000.0}
CELL_M = {"walking": 500.0, "cycling": 750.0, "car": 1500.0, "heavy": 1500.0, "motor": 1500.0}
MAX_ORIGINS = {"walking": 1500, "cycling": 1200, "car": 300, "heavy": 300, "motor": 300}
POI_ORIGIN_SHARE = {"walking": 0.25, "cycling": 0.5, "car": 0.0, "heavy": 0.0, "motor": 0.0}
COLLECTOR_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary"}
REF_KMH = 30.0
POP_ATTRACTOR_SHARE = 0.1


def _snap_to_collectors(gdf: gpd.GeoDataFrame, seg: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    from scipy.spatial import cKDTree
    coll = seg[seg["road_class"].isin(COLLECTOR_CLASSES)]
    if len(coll) < 20:
        return gdf
    pts = coll.geometry.interpolate(0.5, normalized=True)
    xy = np.c_[pts.x.values, pts.y.values]
    _, idx = cKDTree(xy).query(np.c_[gdf.geometry.x.values, gdf.geometry.y.values])
    s = pd.DataFrame({"x": xy[idx, 0], "y": xy[idx, 1], "weight": gdf["weight"].values})
    s = s.groupby(["x", "y"], as_index=False)["weight"].sum()
    return gpd.GeoDataFrame(s[["weight"]], geometry=gpd.points_from_xy(s["x"], s["y"]), crs=gdf.crs)


def _grid_points(df: pd.DataFrame, cell_m: float, max_pts: int, crs) -> gpd.GeoDataFrame:
    c = float(cell_m)
    gx = (np.floor(df["x"].values / c) + 0.5) * c
    gy = (np.floor(df["y"].values / c) + 0.5) * c
    g = (pd.DataFrame({"x": gx, "y": gy, "weight": df["weight"].values})
         .groupby(["x", "y"], as_index=False)["weight"].sum())
    g = g[g["weight"] > 0]
    if len(g) > max_pts:
        g = g.nlargest(max_pts, "weight")
    return gpd.GeoDataFrame(g[["weight"]].reset_index(drop=True),
                            geometry=gpd.points_from_xy(g["x"], g["y"]), crs=crs)


def _od_points_for(ctx: RunContext, mode: str, crs, seg: gpd.GeoDataFrame | None = None) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    cell_m = float(ctx.params.get("cell_m", CELL_M)[mode])
    max_pts = int(ctx.params.get("max_origins", MAX_ORIGINS)[mode])
    if seg is not None and len(seg) > 200_000:
        max_pts = min(max_pts, max(250, int(250_000_000 // len(seg))))
    poi_sh = float(ctx.params.get("poi_origin_share", POI_ORIGIN_SHARE).get(mode, 0.0))
    if ctx.tier == "T1_open_covariates":
        pop, pois = ctx.population(), ctx.pois()
        if pop.empty or pois.empty:
            raise Unsupported(f"empty T1 population or POIs for {mode}")
        orig = (pd.concat([pop[["x", "y", "weight"]],
                           pois[["x", "y"]].assign(weight=pois["weight"].values * poi_sh)], ignore_index=True)
                if poi_sh > 0 else pop[["x", "y", "weight"]])
        attr = pd.concat([
            pois[["x", "y", "weight"]],
            pop[["x", "y"]].assign(weight=pop["weight"].values * POP_ATTRACTOR_SHARE),
        ], ignore_index=True)
        o_gdf, d_gdf = _grid_points(orig, cell_m, max_pts, crs), _grid_points(attr, cell_m, max_pts, crs)
        if seg is not None and mode in ("car", "heavy", "motor"):
            o_gdf, d_gdf = _snap_to_collectors(o_gdf, seg), _snap_to_collectors(d_gdf, seg)
        return o_gdf, d_gdf

    zones = ctx.zones()
    pts = zones.geometry.representative_point()
    if "population" in zones.columns and "attractors" in zones.columns:
        o_w = zones["population"].astype(float).values
        d_w = zones["attractors"].astype(float).values + POP_ATTRACTOR_SHARE * o_w
    else:
        od = ctx.od(mode)
        o_w = zones["zone_id"].map(od.groupby("o_zone")["trips"].sum()).fillna(0.0).astype(float).values
        d_w = zones["zone_id"].map(od.groupby("d_zone")["trips"].sum()).fillna(0.0).astype(float).values
    o_df = pd.DataFrame({"x": pts.x.values, "y": pts.y.values, "weight": o_w}).query("weight > 0")
    d_df = pd.DataFrame({"x": pts.x.values, "y": pts.y.values, "weight": d_w}).query("weight > 0")
    if o_df.empty or d_df.empty:
        raise Unsupported(f"no positive zone weights for {mode}")
    to_gdf = lambda d: (gpd.GeoDataFrame(d[["weight"]].reset_index(drop=True),
                                         geometry=gpd.points_from_xy(d["x"], d["y"]), crs=crs)
                        if len(d) <= max_pts else _grid_points(d, cell_m, max_pts, crs))
    return to_gdf(o_df), to_gdf(d_df)


class UNAFlow(Adapter):
    tool = "una"
    family = "flow"
    options = {
        "distance": "metric (motor modes: class speed weighted)",
        "radius_or_decay": "radius + exp gravity (gravity_cap p95, 5% detour envelope)",
        "weighting": "population to POIs (T1) or zone weights (T2)",
        "congestion": "none",
    }
    tiers = ("T1_open_covariates", "T2_synthetic_od")
    modes = ("walking", "cycling", "car", "heavy", "motor")
    variants = {
        "default": {
            "radius_m": RADIUS_M, "beta": BETA, "cell_m": CELL_M,
            "max_origins": MAX_ORIGINS, "detour_ratio": 1.05,
        },
        "shortest": {
            "radius_m": RADIUS_M, "beta": BETA, "cell_m": CELL_M,
            "max_origins": MAX_ORIGINS, "detour_ratio": 1.0,
            "options": {"radius_or_decay": "radius + exp gravity (gravity_cap p95, shortest path)"},
        },
    }

    def tool_version(self) -> str:
        return importlib.metadata.version("urban-network-analysis")

    def predict(self, ctx: RunContext) -> pd.DataFrame:
        import urban_network_analysis as una_pkg
        net = ctx.network
        threads = max(1, int(ctx.threads))

        def one_mode(mode: str) -> pd.DataFrame:
            edges = ctx.directed_edges(mode)
            seg = net[net["segment_id"].isin(set(edges["segment_id"]))][
                ["segment_id", "road_class", "length_m", "geometry"]
            ].reset_index(drop=True)
            if seg.empty:
                raise Unsupported(f"no network segments open to {mode}")
            orig_gdf, dest_gdf = _od_points_for(ctx, mode, net.crs, seg=seg)
            if orig_gdf.empty or dest_gdf.empty:
                raise Unsupported(f"no origins or destinations for {mode}")

            if mode in ("car", "heavy", "motor"):
                kmh = edges.drop_duplicates("segment_id").set_index("segment_id").eval("length_m / time_s * 3.6")
                imp = (REF_KMH / seg["segment_id"].map(kmh)).fillna(1.0).values
                seg["cost_m"] = np.maximum(seg["length_m"].values * imp, 1e-3)
                weight_col, net_cols = "cost_m", ["segment_id", "cost_m", "geometry"]
            else:
                weight_col, net_cols = "Geometric", ["segment_id", "geometry"]

            with tempfile.TemporaryDirectory(prefix="aadtbench-una-") as tmp:
                tdir = Path(tmp)
                seg[net_cols].to_feather(tdir / "net.feather")
                orig_gdf.to_feather(tdir / "orig.feather")
                dest_gdf.to_feather(tdir / "dest.feather")
                u = una_pkg.UNA(verbosity=0)
                u.topology.num_threads = threads
                s = u.settings
                s.data_folder = str(tdir)
                s.network_file, s.network_weight_column = "net.feather", weight_col
                s.origins_file, s.destinations_file = "orig.feather", "dest.feather"
                s.origin_weight_column = s.destination_weight_column = "weight"
                s.search_radius = int(ctx.params["radius_m"][mode])
                s.gravity_beta = float(ctx.params["beta"][mode])
                s.flow_engine = "aggregate_flow"
                s.flow_decay = True
                s.flow_decay_method, s.flow_gravity_cap = "gravity_cap", "p95"
                s.flow_detour_ratio = float(ctx.params.get("detour_ratio", 1.05))
                s.output_geojson = s.output_feather = s.output_csv = s.progressbar = False
                s.logger_verbosity = 0
                u.RunFlow()
                flow = np.maximum(np.asarray(u.flow.edge_flow, dtype=float), 0.0)
                if (flow > 0).any():
                    med = float(np.median(flow[flow > 0]))
                    flow = np.where(flow > 0, np.maximum(flow, 1e-2 * med), 0.0)

            return pd.DataFrame({"segment_id": seg["segment_id"].values, "mode": mode, "flow": flow})

        return ctx.map_modes(one_mode)


if __name__ == "__main__":
    run_cli(UNAFlow)
