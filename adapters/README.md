# Tool adapters

One file per tool. Each subclasses `Adapter` from `_base.py`, declares its
model family, options, tiers, modes and fixed variants, and writes flows
(`segment_id`, `mode`, `flow`). It never reads counts and never scores.

| Adapter | Family | Tiers |
|---|---|---|
| `sdna.py` | flow / reach (`sdna-plus` betweenness and NQPD) | T0 |
| `una.py` | flow (UNA `aggregate_flow`, `urban_network_analysis`) | T1, T2 |
| `cityseer_od.py` | flow (OD betweenness) | T2, T3 |
| `aequilibrae.py` | assignment (all-or-nothing, user equilibrium) | T2, T3 |

The mandatory baselines live in `benchmark/baselines.py`. See
`IMPLEMENTATIONS.md` at the repository root for the contract and a minimal
example.
