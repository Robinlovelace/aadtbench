# Changelog

All notable changes to AADTBench are documented here. Changes to case data or
scoring rules increment the benchmark data release version so earlier
leaderboards remain comparable.

## Unreleased

### Benchmark & paper simplification
- Streamlined the benchmark to **5 high-signal, 100% open & commercially
  reusable cities across 3 continents** (`bristol-v1`, `london-v1`,
  `melbourne-v1`, `toronto-v1`, `zurich-v1`), plus `london-mini-v1` for CI
  smoke tests — cutting total 11-variant suite runtime and energy by ~35%.
- Removed non-open Oxford sensor feeds, `leuven-v1` (non-commercial CC BY-NC),
  `paris-v1` (lowest signal-to-runtime ratio), and `leeds-v1`, and pruned all
  stale assets from release `v0.1.0`.
- Consolidated the paper leaderboard into a single compact summary table
  (`@tbl-leaderboard`) alongside `@fig-main`, `@fig-matrix`, `@tbl-resources`,
  and `@fig-horses`; tightened the abstract and discussion; removed standalone
  `leaderboard.qmd`, README results duplication, and 421 lines of dead scripts.

### Tool & adapter improvements
- **sDNA (`sdna-plus` 5.2.0, #31):** Fixed link/polyline weighting consistency,
  added in-memory `sdnapy` execution, and introduced `mode_hybrid`
  (`PEDESTRIAN` dispersed, `CYCLE_ROUNDTRIP`, `VEHICLE` two-phase betweenness),
  reaching car median Spearman ρ = **0.794** ($\log R^2 = +0.528$) and heavy
  ρ = **0.737** ($\log R^2 = +0.541$).
- **UNA, cityseer, AequilibraE (#32):** Good-faith tuning across ≥5 experiments
  per tool — 5% detour envelope + p95 gravity cap in `UNA`, mode-specific
  dispersal (8% walk / 3% other) + freight conductance in `cityseer` (leading
  cycling at median ρ = **0.610**, $\log R^2 = +0.124$), and soft BPR
  multi-path dispersion in `AequilibraE ue_bfw` (top cycling $\log R^2 = +0.205$).
- Added CPU thread-time and TDP-proportional electricity reporting (`Wh/city`)
  in `paper/index.qmd`.

## `v0.1.0` — 2026-11-08

- Initial public benchmark harness, containerised adapters and GHCR images for
  `sDNA`, `UNA`, `cityseer`, and `AequilibraE`, spatial group-out and
  leave-one-city-out scoring, Quarto site, and paper draft.
