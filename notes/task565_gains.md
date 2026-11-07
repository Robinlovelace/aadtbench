# Task-565: Hybrid Collector + Subgrid Zone Connector Gains

## Overview

In `adapters/_base.py` (`RunContext.od_nodes`), single-centroid zone snapping (`k=1`, `max_snap_m=500m`) previously concentrated all zone demand onto a single arbitrary interior node (often a minor residential street or cul-de-sac), causing severe point-load artefacts on local streets and leaving parallel walking/cycling corridors and secondary/tertiary collectors unloaded.

Replacing single-centroid snapping with **multi-point subgrid zone connectors** (`2x2` / `3x3` bounding-box subgrid for active modes, and `2x2` subgrid snapped to primary/secondary/tertiary/trunk/motorway collector nodes for motor modes, capped to the top 300 highest-volume zones for scalability) produced large, consistent gains in Spearman $\rho$, $\log_{10} R^2$, and sensor coverage across tools and cities.

---

## 1. `oxford-v1` Connector Topology Sweep (`task-522` & `task-565`)

### Active & Motor Mode Subgrid / Collector Comparison (`aequilibrae aon`)

| Mode | Connector Config | $\rho$ | $\log_{10} R^2$ | Coverage |
|---|---|---:|---:|---:|
| `walking` | `k=1` centroid (baseline) | `-0.062` | `-7.26` | `0.573` |
| `walking` | `k=4` (`2x2` subgrid) | **`+0.270`** | `-3.13` | `0.774` |
| `walking` | `k=9` (`3x3` subgrid) | `+0.250` | **`-1.88`** | **`0.871`** |
| `cycling` | `k=1` centroid (baseline) | `0.443` | `-1.11` | `0.812` |
| `cycling` | `k=4` (`2x2` subgrid) | `0.464` | `-0.36` | `0.921` |
| `cycling` | `k=9` (`3x3` subgrid) | **`0.467`** | **`-0.18`** | **`0.950`** |
| `car` | `k=1` centroid (baseline) | `0.558` | `-3.73` | `0.764` |
| `car` | `k=4` (`2x2` all-nodes subgrid) | `0.556` | `-2.28` | `0.860` |
| `car` | `k=4` (`2x2` collector subgrid) | **`0.590`** | `-2.94` | `0.801` |
| `heavy` | `k=1` centroid (baseline) | `0.424` | `-1.62` | `0.772` |
| `heavy` | `k=4` (`2x2` all-nodes subgrid) | `0.445` | `-1.16` | `0.859` |
| `heavy` | `k=4` (`2x2` collector subgrid) | **`0.480`** | `-1.31` | `0.803` |

### Hybrid Collector + Local Subgrid Sweep (`aequilibrae aon` & `ue_bfw`, `task-565`)

| City | Mode | Variant | Local Share (`ls`) | $\rho$ | $\log_{10} R^2$ | Coverage |
|---|---|---|---:|---:|---:|---:|
| `oxford-v1` | `car` | `aon` | `0.00` | `0.590` | `-2.94` | `0.801` |
| `oxford-v1` | `car` | `ue_bfw` | `0.00` | **`0.594`** | `-2.76` | `0.812` |
| `oxford-v1` | `car` | `aon` | `0.02` | `0.579` | `-1.89` | `0.918` |
| `oxford-v1` | `car` | `ue_bfw` | `0.02` | `0.583` | `-1.79` | **`0.925`** |
| `oxford-v1` | `car` | `aon` | `0.05` | `0.576` | `-1.72` | `0.918` |
| `oxford-v1` | `car` | `ue_bfw` | `0.05` | `0.579` | **`-1.62`** | **`0.925`** |
| `oxford-v1` | `heavy` | `aon` | `0.00` | `0.480` | `-1.31` | `0.803` |
| `oxford-v1` | `heavy` | `ue_bfw` | `0.00` | **`0.481`** | `-1.25` | `0.814` |
| `oxford-v1` | `heavy` | `aon` | `0.02` | `0.467` | `-1.23` | `0.917` |
| `oxford-v1` | `heavy` | `ue_bfw` | `0.02` | `0.468` | `-1.19` | **`0.924`** |
| `oxford-v1` | `heavy` | `aon` | `0.05` | `0.464` | `-1.10` | `0.917` |
| `oxford-v1` | `heavy` | `ue_bfw` | `0.05` | `0.465` | **`-1.06`** | **`0.924`** |

---

## 2. Cross-Tool Gains on `oxford-v1` (`cityseer_od` & `una`)

| Tool | Mode | Baseline (`k=1`) $\rho$ / $\log_{10} R^2$ / Cov | Tuned (Subgrid + Collector) $\rho$ / $\log_{10} R^2$ / Cov |
|---|---|---|---|
| `cityseer_od` | `walking` | `-0.047` / `-6.37` / `0.621` | **`+0.256`** / **`-0.88`** / **`0.960`** (`mean`), **`+0.276`** (`min`) |
| `cityseer_od` | `cycling` | `0.498` / `-0.71` / `0.883` | **`0.553`** / **`+0.12`** / **`0.979`** |
| `cityseer_od` | `car` | `0.549` / `-3.32` / `0.795` | **`0.629`** / **`-2.71`** / **`0.815`** |
| `cityseer_od` | `heavy` | `0.417` / `-1.48` / `0.797` | **`0.518`** / **`-1.21`** / **`0.814`** |
| `una` (`default`) | `car` | `0.576` / `-5.09` / `0.863` | **`0.604`** / **`-4.26`** / **`0.887`** |
| `una` (`default`) | `heavy` | `0.446` / `-3.72` / `0.890` | **`0.450`** / **`-3.16`** / **`0.910`** |

---

## 3. Cross-City Generalization (`bristol-v1` & `leeds-v1`, `task-565`)

| City | Mode | Baseline (`k=1` `aon`) $\rho$ / $\log_{10} R^2$ / Cov | Collector Subgrid (`aon`) $\rho$ / $\log_{10} R^2$ / Cov | Collector Subgrid (`ue_bfw`) $\rho$ / $\log_{10} R^2$ / Cov |
|---|---|---|---|---|
| `bristol-v1` | `cycling` | `0.404` / `-1.06` / `0.910` | **`0.492`** / **`-0.28`** / **`0.975`** | — |
| `bristol-v1` | `car` | `0.590` / `-5.59` / `0.883` | `0.628` / `-3.91` / `0.917` | **`0.654`** / **`-3.21`** / **`0.930`** (`ls=0.00`), `0.650` / `-2.15` / `0.978` (`ls=0.02`) |
| `bristol-v1` | `heavy` | `0.497` / `-0.67` / `0.886` | `0.522` / `-0.39` / `0.913` | **`0.550`** / **`-0.23`** / **`0.930`** (`ls=0.00`), `0.548` / `-0.19` / `0.983` (`ls=0.02`) |
| `leeds-v1` | `cycling` | `0.339` / `-1.54` / `0.908` | **`0.353`** / **`-1.11`** / **`0.942`** | — |
| `leeds-v1` | `car` | `0.624` / `-6.48` / `0.923` | `0.653` / `-4.98` / `0.930` | **`0.656`** / **`-3.92`** / **`0.952`** |
| `leeds-v1` | `heavy` | `0.517` / `-1.30` / `0.928` | `0.543` / `-0.74` / `0.935` | **`0.564`** / **`-0.41`** / **`0.966`** |
