"""The AADTBench v0.2 adapter contract.

An adapter wraps one tool. It gets a case directory, an input tier and a list
of modes. It returns one flow per network segment and mode. The harness does
everything else: counts, matching, calibration and scoring.

To add a tool, subclass :class:`Adapter`, fill in ``predict`` and end the file
with ``if __name__ == "__main__": run_cli(MyAdapter)``. See IMPLEMENTATIONS.md.

Contract
--------
In:  a case directory (``network.parquet`` and ``inputs/``), a tier, modes,
     a named variant and its parameters.
Out: ``predictions.parquet`` with columns ``segment_id``, ``mode``, ``flow``
     (two-way daily flow or any positive score, one row per segment and mode)
     and ``run.json`` (the run record, including wall time and peak memory).

Adapters must not read ``sites.csv`` or ``crosswalk.csv``. :class:`RunContext`
gives them only the network and the inputs allowed by their tier. The harness
also runs adapters on a blind copy of the case that holds no counts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

MODES = ("walking", "cycling", "car", "heavy", "motor")
TIERS = ("T0_network", "T1_open_covariates", "T2_synthetic_od", "T3_observed_od")
TIER_RANK = {t: i for i, t in enumerate(TIERS)}

# Mode access and direction columns in network.parquet. `motor` and `heavy`
# use the car direction column (heavy may also be barred by allow_heavy).
ACCESS_COLUMN = {"walking": "allow_walking", "cycling": "allow_cycling",
                 "car": "allow_car", "heavy": "allow_heavy", "motor": "allow_car"}
DIRECTION_COLUMN = {"walking": None, "cycling": "dir_cycling", "car": "dir_car",
                    "heavy": "dir_car", "motor": "dir_car"}

# Free-flow speeds (km/h) by road class, used only for a default travel time
# cost. Tools are free to build their own cost from the network attributes.
CLASS_SPEED_KMH = {"motorway": 100, "trunk": 80, "primary": 50, "secondary": 45,
                   "tertiary": 40, "minor": 30, "service": 15, "cycleway": 15,
                   "footway": 5, "other": 30}
MODE_SPEED_KMH = {"walking": 5.0, "cycling": 15.0}
# Default one-direction capacity (vehicles per hour) by road class, for tools
# with congestion. The network has no lane data, so every assignment tool uses
# this one table unless it declares otherwise in its options.
CLASS_CAPACITY_VPH = {"motorway": 2200, "trunk": 1800, "primary": 900, "secondary": 600,
                      "tertiary": 400, "minor": 250, "service": 100, "cycleway": 300,
                      "footway": 300, "other": 300}
# OD tables hold daily trips. Tools that need an hourly demand use this
# peak-hour share and scale flows back to daily.
PEAK_HOUR_FACTOR = 0.1

PREDICTION_COLUMNS = ["segment_id", "mode", "flow"]

# Model families. Results are grouped by family on the leaderboard, so a reach
# score is never ranked against a flow score without saying so.
#   reach       closeness, gravity or reach to destinations (step or decay)
#   flow        betweenness, demand weighted betweenness, spatial interaction
#   assignment  OD assignment with route choice or congestion
#   baseline    the benchmark's mandatory baselines
#   statistical models fitted to covariates (they must not see the counts)
#   other       anything else
FAMILIES = ("reach", "flow", "assignment", "baseline", "statistical", "other")
# Option keys every adapter declares, so like can be compared with like.
OPTION_KEYS = ("distance", "radius_or_decay", "weighting", "congestion")


class Unsupported(Exception):
    """Raise from ``predict`` when the tool cannot handle a tier or mode."""


@dataclass
class RunContext:
    """What an adapter may see: the network and the inputs of its tier."""

    case_dir: Path
    manifest: dict
    tier: str
    modes: list[str]
    params: dict
    threads: int
    out_dir: Path
    _cache: dict = field(default_factory=dict, repr=False)
    unsupported: dict = field(default_factory=dict)

    def map_modes(self, fn) -> pd.DataFrame:
        """Call ``fn(mode)`` for each run mode and stack the tables it returns.

        A mode that raises :class:`Unsupported` is recorded in
        ``run.json`` under ``modes_unsupported`` and the other modes go on.
        """
        out = []
        for mode in self.modes:
            try:
                out.append(fn(mode))
            except Unsupported as exc:
                self.unsupported[mode] = str(exc)
        if not out:
            raise Unsupported("; ".join(f"{m}: {r}" for m, r in self.unsupported.items()))
        return pd.concat(out, ignore_index=True)

    # -- network -----------------------------------------------------------
    @property
    def network(self):
        """The case network as a GeoDataFrame (one row per two-way segment)."""
        if "network" not in self._cache:
            import geopandas as gpd
            self._cache["network"] = gpd.read_parquet(self.case_dir / "network.parquet")
        return self._cache["network"]

    def directed_edges(self, mode: str) -> pd.DataFrame:
        """Directed edges open to ``mode``.

        Columns: ``segment_id``, ``u``, ``v`` (from and to node), ``length_m``,
        ``road_class``, ``time_s`` (a default free-flow travel time). Two-way
        segments give two rows, one-way segments one row.
        """
        net = self.network
        allow = net[ACCESS_COLUMN[mode]].fillna(False).astype(bool)
        seg = net.loc[allow, ["segment_id", "u", "v", "length_m", "road_class"]].copy()
        dcol = DIRECTION_COLUMN[mode]
        direction = (net.loc[allow, dcol].fillna("both").astype(str)
                     if dcol and dcol in net.columns else pd.Series("both", index=seg.index))
        fwd = seg[direction.isin(["both", "forward"])]
        bwd = seg[direction.isin(["both", "backward"])].rename(columns={"u": "v", "v": "u"})
        edges = pd.concat([fwd, bwd[fwd.columns]], ignore_index=True)
        if mode in MODE_SPEED_KMH:
            speed = MODE_SPEED_KMH[mode]
            edges["time_s"] = edges["length_m"] / (speed / 3.6)
        else:
            kmh = edges["road_class"].map(CLASS_SPEED_KMH).fillna(30.0)
            if mode == "heavy":
                kmh = kmh.clip(upper=90.0)
            edges["time_s"] = edges["length_m"] / (kmh / 3.6)
        return edges.reset_index(drop=True)

    def node_xy(self) -> pd.DataFrame:
        """Node coordinates (index ``node``, columns ``x``, ``y``) from segment ends."""
        if "nodes" not in self._cache:
            net = self.network
            import shapely
            first = shapely.get_point(net.geometry.values, 0)
            last = shapely.get_point(net.geometry.values, -1)
            a = pd.DataFrame({"node": net["u"].values, "x": shapely.get_x(first), "y": shapely.get_y(first)})
            b = pd.DataFrame({"node": net["v"].values, "x": shapely.get_x(last), "y": shapely.get_y(last)})
            self._cache["nodes"] = pd.concat([a, b]).drop_duplicates("node").set_index("node")
        return self._cache["nodes"]

    # -- inputs by tier ------------------------------------------------------
    def _need(self, tier: str, what: str) -> None:
        if TIER_RANK[self.tier] < TIER_RANK[tier]:
            raise PermissionError(f"{what} needs tier {tier} or above, run is {self.tier}")

    def _input(self, name: str) -> Path:
        path = self.case_dir / "inputs" / name
        if not path.exists():
            raise Unsupported(f"case has no input {name}")
        return path

    def population(self) -> pd.DataFrame:
        """T1: resident points ``x``, ``y``, ``weight`` in the case CRS."""
        self._need("T1_open_covariates", "population")
        return pd.read_parquet(self._input("population.parquet"))

    def pois(self) -> pd.DataFrame:
        """T1: point-of-interest points ``x``, ``y``, ``weight``, ``type``."""
        self._need("T1_open_covariates", "pois")
        return pd.read_parquet(self._input("pois.parquet"))

    def zones(self):
        """T2 and T3: zone polygons with ``zone_id`` (T3 uses ``zones_observed`` if the case has it)."""
        import geopandas as gpd
        self._need("T2_synthetic_od", "zones")
        if self.tier == "T3_observed_od" and (self.case_dir / "inputs" / "zones_observed.parquet").exists():
            return gpd.read_parquet(self._input("zones_observed.parquet"))
        return gpd.read_parquet(self._input("zones.parquet"))

    def od(self, mode: str) -> pd.DataFrame:
        """The OD table of this run's tier for ``mode``: ``o_zone``, ``d_zone``, ``trips``.

        T2 reads ``od_synthetic.parquet``. T3 reads ``od_observed.parquet``.
        """
        if self.tier == "T2_synthetic_od":
            od = pd.read_parquet(self._input("od_synthetic.parquet"))
        elif self.tier == "T3_observed_od":
            od = pd.read_parquet(self._input("od_observed.parquet"))
        else:
            raise PermissionError(f"OD needs tier T2 or T3, run is {self.tier}")
        if mode == "motor" and not (od["mode"] == "motor").any():
            # All motor traffic: car plus heavy trips where the case has no motor rows.
            od = od[od["mode"].isin(["car", "heavy"])].groupby(
                ["o_zone", "d_zone"], as_index=False)["trips"].sum().assign(mode="motor")
        od = od[(od["mode"] == mode) & (od["trips"] > 0)]
        if od.empty:
            raise Unsupported(f"no {self.tier} OD rows for mode {mode}")
        return od[["o_zone", "d_zone", "trips"]].reset_index(drop=True)

    def od_nodes(self, mode: str, max_snap_m: float = 500.0) -> pd.DataFrame:
        """OD snapped to network nodes open to ``mode``: ``o_node``, ``d_node``, ``trips``.

        Each zone goes to the node nearest its representative point. Zones
        further than ``max_snap_m`` from the mode's network are dropped, and
        intrazonal pairs (same node) are dropped.
        """
        from scipy.spatial import cKDTree
        zones = self.zones()
        edges = self.directed_edges(mode)
        nodes = self.node_xy().loc[np.unique(edges[["u", "v"]].values)]
        tree = cKDTree(nodes[["x", "y"]].values)
        pts = zones.geometry.representative_point()
        dist, idx = tree.query(np.c_[pts.x.values, pts.y.values])
        ok = dist <= max_snap_m
        node_of = pd.Series(nodes.index.values[idx[ok]], index=zones["zone_id"].values[ok])
        od = self.od(mode)
        od = od[od["o_zone"].isin(node_of.index) & od["d_zone"].isin(node_of.index)]
        out = pd.DataFrame({"o_node": od["o_zone"].map(node_of).values,
                            "d_node": od["d_zone"].map(node_of).values,
                            "trips": od["trips"].values})
        out = out[out["o_node"] != out["d_node"]]
        return out.groupby(["o_node", "d_node"], as_index=False)["trips"].sum()


def directed_to_segments(edges: pd.DataFrame, flow, mode: str) -> pd.DataFrame:
    """Sum flows on directed edges into two-way segment flows for one mode."""
    df = pd.DataFrame({"segment_id": edges["segment_id"].values,
                       "flow": np.asarray(flow, dtype=float)})
    out = df.groupby("segment_id", as_index=False)["flow"].sum()
    out["mode"] = mode
    return out[PREDICTION_COLUMNS]


def validate_predictions(pred: pd.DataFrame, network_ids=None) -> pd.DataFrame:
    """Check the predictions table against the contract and normalise types."""
    missing = set(PREDICTION_COLUMNS).difference(pred.columns)
    if missing:
        raise ValueError(f"predictions missing columns {sorted(missing)}")
    out = pred[PREDICTION_COLUMNS].copy()
    out["segment_id"] = out["segment_id"].astype(str)
    out["mode"] = out["mode"].astype(str)
    out["flow"] = pd.to_numeric(out["flow"], errors="coerce").astype(float)
    bad_mode = set(out["mode"]).difference(MODES)
    if bad_mode:
        raise ValueError(f"unknown modes {sorted(bad_mode)}")
    if out.duplicated(["segment_id", "mode"]).any():
        raise ValueError("duplicate (segment_id, mode) rows")
    if (~np.isfinite(out["flow"]) | (out["flow"] < 0)).any():
        raise ValueError("flows must be finite and non-negative")
    if network_ids is not None:
        unknown = set(out["segment_id"]).difference(map(str, network_ids))
        if unknown:
            raise ValueError(f"{len(unknown)} segment_id values are not in the network")
    return out


class Adapter:
    """Base class for a tool adapter. Subclasses set the class fields and ``predict``."""

    tool: str = "unnamed"
    family: str = "other"
    # Declared options, for example {"distance": "metric" or "angular" or
    # "time", "radius_or_decay": "radius 5000 m" or "exp decay 1 km",
    # "weighting": "none" or "population" or "land use" or "od",
    # "congestion": "none" or "user equilibrium"}. A variant may override them
    # through an "options" entry in its parameters.
    options: dict = {}
    tiers: tuple[str, ...] = TIERS
    modes: tuple[str, ...] = MODES
    # Named parameter sets. The first is the default. Variants are fixed
    # before any scoring, they are not chosen by looking at results.
    variants: dict[str, dict] = {"default": {}}

    def tool_version(self) -> str:
        return "unknown"

    def predict(self, ctx: RunContext) -> pd.DataFrame:
        """Return a table with columns ``segment_id``, ``mode``, ``flow``."""
        raise NotImplementedError


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def input_hash(case_manifest: dict, tool: str, variant: str, params: dict, tier: str,
               modes: list[str], tool_version: str) -> str:
    """Hash that identifies a run's inputs, used by the harness cache."""
    key = json.dumps({"case": case_manifest.get("id"), "case_version": str(case_manifest.get("version")),
                      "tool": tool, "tool_version": tool_version, "variant": variant,
                      "params": params, "tier": tier, "modes": sorted(modes)}, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def run_adapter(adapter: Adapter, case_dir: Path, tier: str, modes: list[str], out_dir: Path,
                variant: str | None = None, params: dict | None = None, threads: int = 1) -> dict:
    """Run one adapter and write ``predictions.parquet`` and ``run.json``.

    Returns the run record. Unsupported tiers or modes give a record with
    status ``unsupported`` and no predictions, so they show on the board.
    """
    import yaml
    case_dir, out_dir = Path(case_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = yaml.safe_load((case_dir / "case.yaml").read_text())
    variant = variant or next(iter(adapter.variants))
    p = dict(adapter.variants.get(variant, {}))
    p.update(params or {})
    case_modes = manifest.get("modes", list(MODES))
    run_modes = [m for m in modes if m in case_modes]
    for var in ("OMP_NUM_THREADS", "RAYON_NUM_THREADS", "NUMBA_NUM_THREADS"):
        os.environ.setdefault(var, str(threads))
    record = {
        "case_id": manifest["id"], "case_version": str(manifest["version"]),
        "tool": adapter.tool, "tool_version": adapter.tool_version(), "variant": variant,
        "family": adapter.family,
        "options": {**{k: "unspecified" for k in OPTION_KEYS}, **adapter.options,
                    **p.get("options", {})},
        "input_tier": tier, "modes": run_modes, "parameters": p, "threads": threads,
        "python": sys.version.split()[0], "platform": platform.platform(),
        "git_commit": _git_commit(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    record["input_hash"] = input_hash(manifest, adapter.tool, variant, p, tier, run_modes,
                                      record["tool_version"])
    record["run_id"] = f"{adapter.tool}-{variant}-{record['input_hash']}"
    ctx = RunContext(case_dir=case_dir, manifest=manifest, tier=tier, modes=run_modes,
                     params=p, threads=threads, out_dir=out_dir)
    from benchmark.system import cpu_time_s, write_system
    t0, c0 = time.perf_counter(), cpu_time_s()
    status, message, pred = "complete", "", None
    try:
        if tier not in adapter.tiers:
            raise Unsupported(f"{adapter.tool} does not support {tier}")
        if not run_modes:
            raise Unsupported("no requested mode is scored in this case")
        pred = adapter.predict(ctx)
        pred = validate_predictions(pred, ctx.network["segment_id"].values)
    except Unsupported as exc:
        status, message = "unsupported", str(exc)
    except Exception as exc:  # recorded, then re-raised so failures are loud
        record.update(status="failed", message=f"{type(exc).__name__}: {exc}",
                      wall_time_s=round(time.perf_counter() - t0, 3))
        (out_dir / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        raise
    record["wall_time_s"] = round(time.perf_counter() - t0, 3)
    # ru_maxrss is in KiB on Linux. It is the peak of the whole process.
    record["peak_memory_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    record["status"] = status
    if message:
        record["message"] = message
    if ctx.unsupported:
        record["modes_unsupported"] = ctx.unsupported
    if pred is not None:
        pred.to_parquet(out_dir / "predictions.parquet", index=False)
        record["n_predictions"] = int(len(pred))
    (out_dir / "run.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    write_system(out_dir, tool=adapter.tool, tool_version=record["tool_version"],
                 harness_commit=record["git_commit"],
                 data_release=f"v{manifest.get('benchmark_version', 'unknown')}",
                 wall_time_s=record["wall_time_s"], cpu_s=cpu_time_s() - c0,
                 peak_memory_mb=record["peak_memory_mb"], threads=threads)
    return record


def run_cli(adapter_cls: type[Adapter]) -> None:
    """Command line entry point shared by every adapter."""
    ap = argparse.ArgumentParser(description=f"AADTBench adapter for {adapter_cls.tool}")
    ap.add_argument("--case", required=True, type=Path, help="case directory")
    ap.add_argument("--tier", required=True, choices=TIERS)
    ap.add_argument("--modes", default=",".join(MODES), help="comma separated modes")
    ap.add_argument("--variant", default=None, help=f"one of {list(adapter_cls.variants)}")
    ap.add_argument("--params", default="{}", help="JSON overrides for the variant")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--out", required=True, type=Path, help="run directory")
    a = ap.parse_args()
    rec = run_adapter(adapter_cls(), a.case, a.tier, [m for m in a.modes.split(",") if m],
                      a.out, a.variant, json.loads(a.params), a.threads)
    print(json.dumps({k: rec.get(k) for k in ("run_id", "status", "wall_time_s",
                                              "peak_memory_mb", "n_predictions", "message")}))
