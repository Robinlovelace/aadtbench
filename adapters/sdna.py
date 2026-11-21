"""sDNA adapter (in-memory sdnapy, polyline weighting, and mode-specific hybrid metrics)."""
from __future__ import annotations

import ctypes
import importlib.metadata
import os
from typing import Any

import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree

from adapters._base import Adapter, RunContext, Unsupported, run_cli

RADIUS_M = {"walking": 2000, "cycling": 5000, "car": 5000, "heavy": 5000, "motor": 5000}
# Crispin Cooper (Issue #28): CYCLE_ROUNDTRIP uses round-trip traffic-adjusted radii -> 4x cycling radius.
CYCLE_ROUNDTRIP_RADIUS_M = 4 * RADIUS_M["cycling"]
METRIC_LETTER = {
    "ANGULAR": "A",
    "EUCLIDEAN": "E",
    "HYBRID": "H",
    "VEHICLE": "H",
    "PEDESTRIAN": "H",
    "CYCLE_ROUNDTRIP": "H",
}

# Road-class vehicle AADT priors for sDNA's CYCLE_ROUNDTRIP metric (T0_network only;
# kept well below ~88k where 32-bit exp(aadt/1000) would overflow).
CLASS_AADT = {
    "motorway": 45000.0,
    "trunk": 25000.0,
    "primary": 15000.0,
    "secondary": 8000.0,
    "tertiary": 3500.0,
    "minor": 1000.0,
    "service": 200.0,
    "cycleway": 0.0,
    "footway": 0.0,
    "other": 1000.0,
}

# Origin budgets keep runtime bounded on large metropolitan networks (London/Paris 680k-780k links).
MAX_ORIGINS = {"Bt": 900, "TPBt": 900, "NQPD": 1200}
MAX_ORIGINS_HYBRID = {"walking": 600, "cycling": 350, "car": 900, "heavy": 900, "motor": 900}
BASE_CELL_M = {"walking": 350.0, "cycling": 750.0, "car": 750.0, "heavy": 750.0, "motor": 750.0}
NQPD_CELL_M = 350.0


def _normalize_linestrings(geometries: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (valid_indices, 2D LineString geometries); splits MultiLineStrings by longest part."""
    valid_idx: list[int] = []
    lines: list[Any] = []
    for i, g in enumerate(geometries):
        if g is None or g.is_empty:
            continue
        if g.geom_type == "MultiLineString":
            parts = [p for p in g.geoms if not p.is_empty and shapely.get_num_coordinates(p) >= 2]
            if not parts:
                continue
            g = max(parts, key=lambda p: p.length)
        elif g.geom_type != "LineString" or shapely.get_num_coordinates(g) < 2:
            continue
        valid_idx.append(i)
        lines.append(g)
    return np.asarray(valid_idx, dtype=np.int64), np.asarray(lines, dtype=object)


def _run_sdna_integral(
    geometries: np.ndarray,
    config: str,
    fields: dict[str, np.ndarray],
    target_col: str,
    threads: int,
) -> np.ndarray:
    """Run sDNA Integral directly in memory via sdnapy (avoids shapefile I/O and 10-char DBF truncation)."""
    n_threads = max(1, int(threads))
    os.environ["OMP_NUM_THREADS"] = str(n_threads)
    from sDNA import sdnapy

    n = len(geometries)
    valid_idx, valid_geoms = _normalize_linestrings(geometries)
    if len(valid_idx) == 0:
        return np.zeros(n, dtype=float)

    snet = sdnapy.Net()
    dll = snet.dll
    # Configure OpenMP directly on the library linked into sdna_vs2008.so (e.g. auditwheel vendored libgomp).
    try:
        dll.omp_set_num_threads(ctypes.c_int(n_threads))
    except AttributeError:
        pass

    snet.reserve(len(valid_idx))
    coords, indices = shapely.get_coordinates(valid_geoms, return_index=True)
    splits = np.searchsorted(indices, np.arange(len(valid_idx) + 1))

    net_ptr = snet.net
    add_poly = dll.net_add_polyline_3d
    add_data = dll.net_add_polyline_data
    enc_fields = [(k.encode("ascii"), np.asarray(v, dtype=np.float32)) for k, v in fields.items()]

    xs, ys = coords[:, 0], coords[:, 1]
    for k_idx, seg_i in enumerate(valid_idx):
        s, e = int(splits[k_idx]), int(splits[k_idx + 1])
        m = e - s
        if m < 2:
            continue
        px = (ctypes.c_double * m)(*xs[s:e])
        py = (ctypes.c_double * m)(*ys[s:e])
        fid = ctypes.c_long(int(seg_i))
        if not add_poly(net_ptr, fid, ctypes.c_long(m), px, py, None):
            raise RuntimeError(f"sDNA net_add_polyline_3d failed at segment {seg_i}")
        for fname_b, arr in enc_fields:
            if not add_data(net_ptr, fid, ctypes.c_char_p(fname_b), ctypes.c_float(float(arr[seg_i]))):
                raise RuntimeError(f"sDNA net_add_polyline_data failed for '{fname_b.decode()}' at {seg_i}")

    msgs: list[str] = []
    try:
        calc = sdnapy.Calculation(
            "sdnaintegral",
            config,
            snet,
            lambda _p: 0,
            lambda m: (msgs.append(m), 0)[1],
        )
    except Exception as exc:
        raise RuntimeError(f"sDNA config failed ({exc}): {msgs[-10:]}") from exc

    try:
        if not calc.run():
            raise RuntimeError(f"sDNA calculation failed: {msgs[-10:]}")

        gl = next(calc.get_geom_outputs())
        short = gl.shortdatanames
        if target_col not in short:
            raise RuntimeError(f"sDNA output missing column '{target_col}': {short}")
        col_idx = short.index(target_col)
        id_idx = short.index("ID")

        class _SDNAOutputUnion(ctypes.Union):
            _fields_ = [("FLOAT", ctypes.c_float), ("STR", ctypes.c_char_p), ("INT", ctypes.c_long)]

        dll.geom_iterator_create.restype = sdnapy.my_void_p
        dll.geom_iterator_next.restype = ctypes.c_int
        it = dll.geom_iterator_create(gl.gc)
        num_parts = ctypes.c_long()
        data = ctypes.POINTER(_SDNAOutputUnion)()
        out = np.zeros(n, dtype=float)
        try:
            while dll.geom_iterator_next(it, ctypes.byref(num_parts), ctypes.byref(data)) == 1:
                fid = int(data[id_idx].INT)
                if 0 <= fid < n:
                    out[fid] = float(data[col_idx].FLOAT)
        finally:
            dll.geom_iterator_destroy(it)
    finally:
        # Ensure Calculation is destroyed before its non-owning Net pointer.
        del calc
    return np.clip(np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0), 0.0, None)


def _select_cell_representatives(
    px: np.ndarray,
    py: np.ndarray,
    dw: np.ndarray,
    base_cell: float,
    max_origins: int,
    pick_highest_weight: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Grid-aggregate origins while capping total cells <= max_origins via adaptive cell scaling."""
    cell = float(base_cell)
    for _ in range(20):
        gx = np.floor(px / cell).astype(np.int64)
        gy = np.floor(py / cell).astype(np.int64)
        n_cells = len(np.unique(np.c_[gx, gy], axis=0))
        if n_cells <= max_origins:
            break
        cell *= max(1.25, float(np.sqrt(n_cells / max_origins)))

    df = pd.DataFrame({"idx": np.arange(len(px)), "gx": gx, "gy": gy, "dw": dw, "px": px, "py": py})
    if pick_highest_weight:
        # Motor modes: anchor each cell on its highest-weight arterial/collector polyline.
        top = df.sort_values("dw", ascending=False, kind="mergesort").drop_duplicates(["gx", "gy"])
    else:
        # Active modes: anchor each cell on the polyline nearest the cell centroid (avoids arterial bias).
        cx = (gx + 0.5) * cell
        cy = (gy + 0.5) * cell
        df["d2"] = (px - cx) ** 2 + (py - cy) ** 2
        top = df.sort_values("d2", ascending=True, kind="mergesort").drop_duplicates(["gx", "gy"])

    cell_sum = df.groupby(["gx", "gy"])["dw"].sum()
    top_idx = top["idx"].to_numpy(dtype=np.int64)
    top_sum = cell_sum.loc[list(zip(top["gx"], top["gy"]))].to_numpy(dtype=float)
    return top_idx, top_sum, gx, gy


def _mode_hybrid_spec(mode: str, params: dict[str, Any]) -> dict[str, Any]:
    """Mode-specific sDNA formulation addressing Issue #28 recommendations."""
    radius_m = params.get("radius_m", RADIUS_M)
    if mode == "walking":
        # Crispin's PEDESTRIAN metric (angular+Euclidean blend + linerand=0.8 dispersal, oversample=4).
        # We use ped_a=0.1 (vs sDNA's default a=0.5) based on multi-city walking validation, and express
        # trunc(randnorm(...), 0.1, 10) via max(min(...)) because sdna-plus 5.2.0 Linux wheels guard
        # DefineFun("trunc", &truncate) behind #ifdef _WINDOWS (POSIX <unistd.h> truncate clash).
        ped_a = float(params.get("ped_a", 0.1))
        linerand = float(params.get("linerand", 0.8))
        oversample = int(params.get("oversample", 4))
        return {
            "metric": "HYBRID",
            "measure": "TPBt",
            "radius": int(radius_m["walking"]),
            "metric_cfg": (
                f"metric=HYBRID;"
                f"lineformula=max(min(randnorm(1,{linerand}),10),0.1)*(euc*(1-{ped_a})+ang*{ped_a});"
                f"juncformula={ped_a}*ang;ignorenonlinear;oversample={oversample};"
            ),
            "max_origins": int(params.get("max_origins_hybrid", MAX_ORIGINS_HYBRID)["walking"]),
        }
    if mode == "cycling":
        # Crispin's CYCLE_ROUNDTRIP metric with road-class AADT priors, MATCH_ANALYTICAL radius
        # (round-trip & traffic-adjusted, 4x cycling radius).
        cyc_radius = int(params.get("cycle_radius_m", 4 * int(radius_m["cycling"])))
        return {
            "metric": "CYCLE_ROUNDTRIP",
            "measure": "Bt",
            "radius": cyc_radius,
            "metric_cfg": "metric=CYCLE_ROUNDTRIP;radmetric=MATCH_ANALYTICAL;aadtfield=aadt;",
            "need_aadt": True,
            "max_origins": int(params.get("max_origins_hybrid", MAX_ORIGINS_HYBRID)["cycling"]),
        }
    # Motor modes (car, heavy, motor): sDNA VEHICLE metric (euc + a*ang) with Two-Phase Betweenness (TPBt).
    veh_a = float(params.get("vehicle_a", 1.0))
    return {
        "metric": "VEHICLE",
        "measure": "TPBt",
        "radius": int(radius_m[mode]),
        "metric_cfg": f"metric=VEHICLE;a={veh_a:g};jp=0;",
        "max_origins": int(params.get("max_origins_hybrid", MAX_ORIGINS_HYBRID)[mode]),
    }


class SDNA(Adapter):
    tool = "sdna"
    family = "flow"
    options = {
        "distance": "angular",
        "radius_or_decay": "radius per mode (Euclidean, m)",
        "weighting": "active: topological link (weight_type=link); motor: length x speed ratio (weight_type=polyline)",
        "congestion": "none",
    }
    tiers = ("T0_network", "T1_open_covariates", "T2_synthetic_od", "T3_observed_od")
    modes = ("walking", "cycling", "car", "heavy", "motor")
    variants = {
        "betweenness_angular": {
            "metric": "ANGULAR",
            "measure": "Bt",
            "radius_m": RADIUS_M,
            "family": "flow",
        },
        "betweenness_euclidean": {
            "metric": "EUCLIDEAN",
            "measure": "Bt",
            "radius_m": RADIUS_M,
            "family": "flow",
            "options": {"distance": "Euclidean"},
        },
        "mode_hybrid": {
            "mode_specific": True,
            "radius_m": RADIUS_M,
            "cycle_radius_m": CYCLE_ROUNDTRIP_RADIUS_M,
            "ped_a": 0.1,
            "linerand": 0.8,
            "oversample": 4,
            "vehicle_a": 1.0,
            "family": "flow",
            "options": {
                "distance": "mode-specific (PEDESTRIAN dispersed / CYCLE_ROUNDTRIP / VEHICLE)",
                "radius_or_decay": "mode radius (4x MATCH_ANALYTICAL for cycling), TPBt for walk/motor",
                "weighting": "active: topological link (weight_type=link); motor: length x speed ratio (weight_type=polyline)",
            },
        },
        "nqpd_euclidean": {
            "metric": "EUCLIDEAN",
            "measure": "NQPD",
            "radius_m": RADIUS_M,
            "family": "reach",
            "options": {
                "distance": "Euclidean",
                "radius_or_decay": "radius per mode, NQPD gravity (1/distance)",
            },
        },
        "nqpd_angular": {
            "metric": "ANGULAR",
            "measure": "NQPD",
            "radius_m": RADIUS_M,
            "family": "reach",
            "options": {
                "radius_or_decay": "radius per mode, NQPD gravity (angular)",
            },
        },
    }

    def tool_version(self) -> str:
        return importlib.metadata.version("sdna-plus")

    def predict(self, ctx: RunContext) -> pd.DataFrame:
        net = ctx.network
        mode_specific = bool(ctx.params.get("mode_specific", False))

        def one_mode(mode: str) -> pd.DataFrame:
            edges = ctx.directed_edges(mode)
            seg = net[net["segment_id"].isin(set(edges["segment_id"]))][
                ["segment_id", "road_class", "length_m", "geometry"]
            ].reset_index(drop=True)
            if seg.empty:
                raise Unsupported(f"no {mode} segments")

            is_motor = mode in ("car", "heavy", "motor")
            if is_motor:
                kmh = edges.drop_duplicates("segment_id").set_index("segment_id").eval("length_m / time_s * 3.6")
                cond = seg["segment_id"].map(kmh).fillna(30.0).to_numpy(dtype=float) / 30.0
            else:
                cond = np.ones(len(seg), dtype=float)

            if mode_specific:
                spec = _mode_hybrid_spec(mode, ctx.params)
                metric = spec["metric"]
                measure = spec["measure"]
                radius = int(spec["radius"])
                metric_cfg = spec["metric_cfg"]
                max_origins = int(ctx.params.get("max_origins", spec["max_origins"]))
                need_aadt = bool(spec.get("need_aadt", False))
            else:
                metric = ctx.params["metric"]
                measure = ctx.params["measure"]
                radius = int(ctx.params["radius_m"][mode])
                metric_cfg = f"metric={metric};"
                max_origins = int(ctx.params.get("max_origins", MAX_ORIGINS[measure]))
                need_aadt = False

            letter = METRIC_LETTER[metric]
            is_nqpd = measure == "NQPD"

            fields: dict[str, np.ndarray] = {}
            if need_aadt:
                fields["aadt"] = seg["road_class"].map(CLASS_AADT).fillna(1000.0).to_numpy(dtype=float)

            interp_idx: np.ndarray | None = None
            px = py = None
            if is_motor:
                # Motor modes: manual length x speed-ratio weights with explicit weight_type=polyline
                # (so sDNA uses ow/dw literally without link_fraction distortion, Issue #28).
                dw = np.maximum(seg["length_m"].to_numpy(dtype=float) * cond, 1.0)
                if len(seg) > max_origins:
                    pts = seg.geometry.centroid
                    px, py = pts.x.to_numpy(dtype=float), pts.y.to_numpy(dtype=float)
                    base_cell = NQPD_CELL_M if is_nqpd else BASE_CELL_M[mode]
                    top_idx, top_sum, _, _ = _select_cell_representatives(
                        px, py, dw, base_cell, max_origins, pick_highest_weight=True
                    )
                    ow = np.zeros(len(seg), dtype=float)
                    if is_nqpd:
                        ow[top_idx] = 1.0
                        interp_idx = top_idx
                    else:
                        ow[top_idx] = top_sum
                    cfg_w = "weight_type=polyline;origweight=ow;destweight=dw;skipzeroweightorigins;"
                else:
                    ow = dw
                    cfg_w = "weight_type=polyline;origweight=ow;destweight=dw;"
                fields["ow"] = ow
                fields["dw"] = dw
                wsuf = "Wp"
            else:
                # Active modes (walking, cycling): native sDNA weight_type=link (1.0 per topological
                # junction-to-junction link — pseudonode-invariant and preserves dense urban-core
                # link density over long suburban segments) with native skipfraction on large networks.
                sf = max(1, int(np.ceil(len(seg) / max_origins))) if len(seg) > max_origins else 1
                sf_cfg = f"skipfraction={sf};" if sf > 1 else ""
                cfg_w = f"weight_type=link;{sf_cfg}"
                wsuf = ""
                if is_nqpd and sf > 1:
                    pts = seg.geometry.centroid
                    px, py = pts.x.to_numpy(dtype=float), pts.y.to_numpy(dtype=float)
                    v_idx, _ = _normalize_linestrings(seg.geometry.values)
                    interp_idx = v_idx[::sf]

            nobt = ";nobetweenness" if is_nqpd else ""
            config = f"radii={radius};{metric_cfg}{cfg_w}nojunctions;nohull{nobt}"
            col = f"{measure}{letter}{wsuf}{radius:g}"
            raw = _run_sdna_integral(seg.geometry.values, config, fields, col, ctx.threads)

            if interp_idx is not None and px is not None and py is not None:
                k = min(4, len(interp_idx))
                dist, nn = cKDTree(np.c_[px[interp_idx], py[interp_idx]]).query(np.c_[px, py], k=k)
                tv = raw[interp_idx]
                if k == 1:
                    raw = tv[nn]
                else:
                    w = 1.0 / np.maximum(dist, 1.0)
                    raw = (w * tv[nn]).sum(axis=1) / w.sum(axis=1)

            flow = ctx.modulate_segment_flow(seg["segment_id"].to_numpy(), raw * cond, mode)
            return pd.DataFrame({"segment_id": seg["segment_id"].to_numpy(), "mode": mode, "flow": flow})

        return ctx.map_modes(one_mode)


if __name__ == "__main__":
    run_cli(SDNA)
