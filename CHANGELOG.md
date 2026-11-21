# Changelog

All notable changes to AADTBench are documented here. Changes to case data or
scoring rules increment the benchmark data release version so earlier
leaderboards remain comparable.

## Unreleased (ready for `v0.1.1` / `v0.2.0`)

### Tool & adapter improvements
- **sDNA (`sdna-plus` 5.2.0, #31):** Fixed link/polyline weighting consistency,
  added in-memory `sdnapy` execution, and introduced `mode_hybrid`
  (`PEDESTRIAN` dispersed, `CYCLE_ROUNDTRIP`, `VEHICLE` two-phase betweenness),
  lifting car median Spearman ρ to **0.794** ($\log R^2 = +0.504$) and heavy
  to **0.724** ($\log R^2 = +0.449$).
- **UNA, cityseer, AequilibraE (#32):** Good-faith tuning across ≥5 experiments
  per tool — 5% detour envelope + p95 gravity cap in `UNA`, mode-specific
  dispersal (8% walk / 3% other) + freight conductance in `cityseer`, and soft
  BPR multi-path dispersion for walking/cycling in `AequilibraE ue_bfw`
  (lifting Oxford walking to ρ = 0.689 and cycling median $\log R^2$ to +0.055).

### Compute reporting, website, and presentation
- Added CPU thread-time and TDP-proportional electricity reporting (`Wh/city`)
  in `paper/index.qmd` and `leaderboard.qmd`.
- Switched `paper/index.qmd` to read tracked `leaderboard-summary.csv` directly
  (falling back to release assets), preventing live website/paper drift.
- Rewrote `README.md` into a concise, results-first homepage with an
  auto-generated leaderboard table (`scripts/update_readme_results.py`) and hero
  figure (`assets/hero-benchmark.png`).
- Added a dedicated Quarto **Leaderboard** page (`leaderboard.qmd`) and updated
  website navigation and responsive CSS.
- Removed draft placeholders (`[refs]`, `[Discussion TBC]`, `TBC.`), fixed
  typos, updated paper prose to match PRs #31–#32, and synced thread/time limits
  in `BENCHMARK.md` and `IMPLEMENTATIONS.md`.

## `v0.1.0` — 2026-11-08

- Initial public release: 9 cities across 3 continents (8 open cases: Oxford,
  Leeds, Bristol, London, Paris, Melbourne, Zurich, Toronto; plus Leuven
  non-commercial CC BY-NC 4.0) and `oxford-mini-v1` for CI.
- Containerised adapters and GHCR images for `sDNA`, `UNA`, `cityseer`, and
  `AequilibraE`, plus 4 mandatory `T1` baselines.
- Spatial group-out (5-fold, 3 km cells) and leave-one-city-out scoring
  harness, Quarto site, and paper draft.
