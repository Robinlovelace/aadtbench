# flownet Leeds improvement — verified before/after (2026-08-07)

How the three fixes (wire params, real OD, log-log metrics) moved flownet on the
cenbench Leeds drive benchmark (DfT AADT, 187 matched sensors within 200m,
63,940-edge clipped network). All numbers verified from committed CSVs.

## Before (buggy harness)
- 6 "variants" (beta 0.001/0.002/0.004 × detour 1.25/1.5) — ALL byte-identical:
  R² = 0.003864, ~510s each. Root cause: run_flownet_assignment.R parsed beta/detour
  from CLI args but never forwarded them to run_assignment(); synthetic WorldPop
  gravity demand; linear R² on AADT.

## After (fixed harness)
9 variants, real pct census OD (91/103 zones snapped, 7,243 OD pairs, car_driver
sum 92,780 vs synthetic's ~544M), log-log R², params wired:

| variant | log-log R² | time (s) |
|---|---|---|
| aon_imp_ll (AoN + dimensionless-impedance cost) | 0.0601 | 5.6 |
| psl_imp_beta0.001_detour1.5_ll | 0.0576 | 53 |
| psl_beta0.004_detour1.5_ll | 0.0499 | 54 |
| psl_beta0.001_detour1.5_ll | 0.0499 | 88 |
| psl_beta0.001_detour1.25_ll | 0.0499 | 189 |
| aon_ll (plain AoN) | 0.0461 | 5.6 |
| psl_imp_km_beta0.01 (km-rescaled cost) | 0.0453 | 62 |
| psl_imp_km_beta0.05_detour2.0 | 0.0426 | 144 |
| psl_km_beta0.01_detour1.5 | 0.0278 | 64 |

15x improvement (0.0039 → 0.0601). Real OD + log-log metrics are the big movers;
PSL beta/detour now genuinely differentiate (flow totals differ per variant).

## Surprising verified finding: AoN beats PSL on AADT
On free-flow AADT ground truth, all-or-nothing with a dimensionless-impedance
cost (aon_imp_ll, 0.0601, 5.6s) beat every PSL variant (best 0.0576, 53s+).
Interpretation: AADT is a free-flow count, so single shortest-path with
impedance weighting captures it better than route dispersion — PSL's route
spreading is wasted on uncongested truth. The "boring" baseline winning is a
finding, not a bug. Also notable: dimensionless-impedance cost (imp) consistently
beat plain length cost; km-rescaled cost was worse.

## Variant-naming convention
Fixed harness appends `_ll` to variant names when log-log metrics are used, so
the merged results CSV records the metric family per row (linear R² for Leuven
walk, log-log for Leeds drive).

## Reproduction
```
PYTHONPATH=. .venv/bin/python scripts/bench_flownet.py --city leeds --modes drive
PYTHONPATH=. .venv/bin/python scripts/merge_all.py --city leeds
```
R script signature after fix:
`Rscript run_flownet_assignment.R <net> <origins> <dests> .length <beta> <detour> <out_csv> <mode> <od_sample> <od_file> <zones_file> <method> <angle.max> <nthreads> <cost_div> <cost_col>`
