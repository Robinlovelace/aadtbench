"""Portable edge-weight formula registry shared across benchmark tools.

Why this module exists
----------------------
Each tool in the benchmark suite hardcodes its own edge-cost logic:

  - cityseer_od bakes a dimensionless highway-class "imp_factor" into the
    NetworkStructure (cost = length x imp_factor),
  - aequilibrae computes free_flow_time = length / class-speed and then applies
    its own BPR volume-delay function on top,
  - flownet assigns flows using a plain length cost column (optionally scaled),
  - centrality tools use raw geometric length.

That makes "did the edge-weight formula change the result?" impossible to ask
across tools: each tool's weight is computed in its own bespoke way, so a
"time-based" run in cityseer is not comparable with a "time-based" run in
flownet. This module defines the *formula* once, as a small registry entry, and
each tool adapter evaluates it with apply_formula() so every tool consumes the
same weight array.

Registry design
---------------
A formula is a small dict:

    {"expr": "<numpy expression over the columns below>",
     "params": {optional named constants},
     "desc": "human-readable description"}

Available expression variables (resolved by apply_formula from the edge
GeoDataFrame or explicit kwargs):

    length     edge geometric length (m), always taken from the geometry
    speed_ms   free-flow speed (m/s): explicit arg, a column, or the mode's
               travel_speed config
    imp        dimensionless impedance factor (baseline_speed / class_speed),
               computed from the OSM highway class lookup when not supplied
    flow       assigned/observed flow on the edge (optional; 0 if absent)
    capacity   edge capacity (optional; 1 if absent)
    alpha, beta, ...  named constants from "params"

Expressions are evaluated with pandas.eval() over a DataFrame built ONLY from
the variables above. Formulas come from this module's own registry (never from
untrusted input), so there is no arbitrary-code-eval risk; the variable
namespace is closed.

Variant naming convention
-------------------------
Benchmark variant names should record which formula was used. Use
formula_suffix(name) to get a short, stable, comparable suffix:

    "length"          -> ""            (plain length is the default everywhere)
    "time_freeflow"   -> "_wt_time"
    "time_imp_dimless"-> "_wt_imp"
    "bpr"             -> "_wt_bpr"

Tools
-----
- cityseer_od:  imp_factor = apply_formula(edges, name) / length, so cityseer's
  cost = length x imp_factor == the formula's weight.
- aequilibrae:  free_flow_time = apply_formula(edges, name, ...) (the VDF is
  then applied on top of that base time by the assignment algorithm).
- flownet:      the weight array is written into a temp gpkg as a cost column
  and passed through to the R assignment as the cost vector.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Free-flow mph by OSM highway class (mirrors scripts/bench_cityseer_od.py and
# scripts/bench_aequilibrae.py) -- used ONLY to build the dimensionless
# impedance factor imp = baseline_speed_ms / class_speed_ms.
CLASS_MPH = {
    "motorway": 65, "motorway_link": 40, "trunk": 55, "trunk_link": 35,
    "primary": 35, "primary_link": 25, "secondary": 30, "secondary_link": 25,
    "tertiary": 25, "tertiary_link": 20, "unclassified": 22,
    "residential": 18, "living_street": 10, "busway": 20,
}
DEFAULT_MPH = 20
MPH_TO_MS = 0.44704

# The registry. `params` provides named constants usable inside `expr`.
EDGE_WEIGHTS = {
    "length": {
        "expr": "length",
        "desc": "plain geometric length (m)",
    },
    "time_freeflow": {
        "expr": "length / speed_ms",
        "desc": "free-flow travel time (s)",
    },
    "time_imp_dimless": {
        "expr": "length / speed_ms * imp",
        "desc": "free-flow time scaled by dimensionless impedance "
                "(baseline_speed / class_speed)",
    },
    "bpr": {
        "expr": "length / speed_ms * (1 + alpha * (flow / capacity) ** beta)",
        "params": {"alpha": 0.15, "beta": 4.0},
        "desc": "BPR congestion travel time (s); flow=0 collapses to "
                "time_freeflow",
    },
}

# Short, stable variant suffixes per formula ("" = default everywhere).
_SUFFIX = {
    "length": "",
    "time_freeflow": "_wt_time",
    "time_imp_dimless": "_wt_imp",
    "bpr": "_wt_bpr",
}


def first_class(highway):
    """First OSM highway class of a (possibly list/array-ish) value."""
    if isinstance(highway, (list, tuple, np.ndarray)):
        return highway[0] if len(highway) else "unclassified"
    s = str(highway)
    if s.startswith("["):
        s = s.strip("[]").split(",")[0].strip().strip("'\"")
    return s


def impedance_from_highway(edges, baseline_speed_ms):
    """Dimensionless impedance imp = baseline_speed / class_speed per edge."""
    cls = edges["highway"].map(first_class)
    mph = cls.map(CLASS_MPH).fillna(DEFAULT_MPH).astype(float)
    class_speed = mph.values * MPH_TO_MS
    base = np.asarray(baseline_speed_ms, dtype=float)
    return base / class_speed


def register_formula(name, expr, desc, params=None):
    """Register (or override) a weight formula in the shared registry."""
    EDGE_WEIGHTS[name] = {"expr": expr, "desc": desc}
    if params:
        EDGE_WEIGHTS[name]["params"] = dict(params)
    if name not in _SUFFIX:
        _SUFFIX[name] = f"_wt_{name}"


def formula_suffix(name):
    """Variant-name suffix recording which formula was used."""
    return _SUFFIX.get(name, f"_wt_{name}" if name != "length" else "")


def _resolve_array(edges, value, col_hint, n):
    """Turn None | scalar | array | column-name into an (n,) float array."""
    if value is None:
        if col_hint and col_hint in edges.columns:
            return edges[col_hint].values.astype(float)
        return None
    if isinstance(value, str):
        if value in edges.columns:
            return edges[value].values.astype(float)
        raise KeyError(f"column '{value}' not found on edges")
    arr = np.asarray(value, dtype=float)
    if arr.ndim == 0:
        return np.full(n, float(arr))
    if arr.shape != (n,):
        raise ValueError(f"expected array of length {n}, got {arr.shape}")
    return arr


def apply_formula(edges, name, speed_ms=None, imp=None, flow=None,
                  capacity=None, params=None):
    """Evaluate registry formula `name` on an edge GeoDataFrame.

    Returns an (n,) float numpy array of edge weights.

    Parameters
    ----------
    edges : GeoDataFrame
        Edge table; `length` is ALWAYS taken from `edges.geometry.length`
        (the stored `length` column is ignored so the formula is
        geometry-true). `highway` is used to auto-build `imp` when needed.
    speed_ms : float | array | str | None
        Free-flow speed. Default: the edge `speed_ms` column if present,
        else a `travel_speed` column, else raise for formulas needing it.
    imp : array | str | None
        Dimensionless impedance. Default: built from the highway class
        lookup against `speed_ms` (or 1.0 if speed unknown).
    flow : array | str | None
        Assigned/observed flow (optional; defaults to 0).
    capacity : array | str | None
        Edge capacity (optional; defaults to 1).
    params : dict | None
        Overrides for the formula's named constants (e.g. alpha/beta).
    """
    if name not in EDGE_WEIGHTS:
        raise KeyError(f"unknown edge-weight formula '{name}'; "
                       f"registered: {sorted(EDGE_WEIGHTS)}")
    spec = EDGE_WEIGHTS[name]
    n = len(edges)

    length = np.asarray(edges.geometry.length.values, dtype=float)
    if speed_ms is None:
        speed_ms = edges["speed_ms"] if "speed_ms" in edges.columns else \
            edges["travel_speed"] if "travel_speed" in edges.columns else None
    speed_arr = _resolve_array(edges, speed_ms, None, n)
    if speed_arr is None and "speed_ms" in spec["expr"]:
        raise ValueError(f"formula '{name}' needs speed_ms; pass speed_ms="
                         f"or add a speed_ms/travel_speed column")

    if imp is None:
        imp_arr = impedance_from_highway(edges, speed_arr) if speed_arr is not None \
            else np.ones(n)
    else:
        imp_arr = _resolve_array(edges, imp, None, n)

    flow_arr = _resolve_array(edges, flow, "flow", n)
    if flow_arr is None:
        flow_arr = np.zeros(n)
    cap_arr = _resolve_array(edges, capacity, "capacity", n)
    if cap_arr is None:
        cap_arr = np.ones(n)

    ctx = {
        "length": length,
        "speed_ms": speed_arr if speed_arr is not None else np.ones(n),
        "imp": imp_arr,
        "flow": flow_arr,
        "capacity": cap_arr,
    }
    merged = dict(params or {})
    merged.update(spec.get("params", {}))
    ctx.update(merged)

    # DataFrame.eval over a closed namespace (the frame columns above) -- the
    # expr strings come from this module's own registry, never user input.
    frame = pd.DataFrame(ctx)
    return np.asarray(frame.eval(spec["expr"]), dtype=float)
