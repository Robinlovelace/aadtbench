# AADTBench specification (v0.3)

AADTBench scores methods that estimate **two-way annual average daily flow**
on the links of a street network: routing and assignment engines, centrality
and reach measures, spatial interaction or statistical models. The benchmark
fixes the inputs, the counts, the count-to-link crosswalk, the splits and the
scoring. A tool joins through a thin adapter (`IMPLEMENTATIONS.md`).

Code is in git. Data is not: case data, results and leaderboards are assets of
a versioned GitHub release, listed with sha256 in `manifest-<version>.json`.
Git holds only `case.yaml` and a README per case, and one small results
summary (`leaderboard-summary.csv`).

## Concepts

```text
case   = place x count sources x network version x input tiers
target = case x mode
result = target x tool x variant x input tier x track
```

**Modes.** `walking` (people), `cycling`, `car` (motor vehicles other than
heavy), `heavy` (goods vehicles, buses and coaches) and `motor` (all motor
vehicles, for cases that do not split them). All are two-way daily flows. Each
site records how counts were expanded to an annual average (`method`).

**Input tiers.** Every run declares one. Results are compared within a tier.

| Tier | Inputs |
|---|---|
| `T0_network` | the case network only |
| `T1_open_covariates` | T0 plus population and point-of-interest layers |
| `T2_synthetic_od` | T1 plus the benchmark's synthetic gravity OD per mode |
| `T3_observed_od` | T1 plus an observed OD table, where the case has one |

**Model families.** Centrality, betweenness and gravity overlap: betweenness
is a flow model, gravity is reach with a continuous decay in place of a step
at a radius. So methods are grouped by family, not tool: `reach` (closeness,
gravity, sDNA NQPD), `flow` (betweenness, demand weighted betweenness, spatial
interaction), `assignment` (OD assignment with route choice or congestion),
`baseline`, `statistical` and `other`. Each run declares its options: distance
(metric, angular or time), radius or decay, weighting (none, population, land
use or OD) and congestion. Boards group rows by family.

## Tracks and baselines

Every result is scored on two tracks, plus a third for tools that calibrate themselves:

- `raw`: the flow times one scale factor, the geometric mean ratio of counts
  to flows on the training folds.
- `calibrated`: the flow through the shared reference calibrator, fitted on
  the training folds:

  ```text
  log(count + 1) = a + b * log(flow + 1) + road class effects + error
  ```

  OLS, Duan smearing on back-transform. Road classes with fewer than five
  training sites merge into `other`, which joins the most common class if it
  is still under five. This track asks what a tool adds beyond road class.
- `tool_calibrated` (opt in, `run_all --tool-calibrated`): the tool's own
  calibrated flows, with any terms it likes. The harness calls the adapter
  once per fold `k` and passes only the counts of the other folds
  (`training_sites.csv`, `training_crosswalk.csv`). Fold `k`'s sites are
  scored only from that call's predictions, then pooled. A held-out count is
  never in the tool's input, so it cannot leak. Same folds, metrics and
  baselines as the other tracks. These rows sit on their own board and are
  never ranked against the reference-calibrated track without saying so.
  They are not on the leave-one-city-out board.

Four mandatory baselines go through the calibrated track with a covariate in
place of `log(flow + 1)`: `class_only` (none), `centre_distance` (distance to
the case centre), `attractor_density` (POI weight within 500 m of the link
midpoint) and `population_density` (population within 1 km). They are T1.

## Splits

- **Spatial group-out (main board).** Sites are grouped into square cells
  (3 km, or as set in `case.yaml`), cells into five folds (seed 42). Each fold
  is predicted by a calibrator fitted on the other four. Pooled out-of-fold
  predictions are scored once.
- **Leave-one-city-out.** For each mode the calibrator is fitted on all other
  open cases and scored on the held-out one. No per-city tuning.
- **Legacy.** The v0.1 Leeds board (49 held-out links) is a release asset.

## Metrics

Per target: `n_sites`, Spearman `rho`, `log_r2` (predictive R squared on
`log(1 + value)`), `raw_r2`, `calibration_ratio` (sum of counts over sum of
unscaled flow) and `q = (rho + log_r2) / 2`. Targets with fewer than 20 sites
are shown, not ranked.

## Case format

| File | Contents |
|---|---|
| `case.yaml` (git) | id, version, place, CRS, centre, radius, modes, sources with reviewed licences, split, tiers, file list |
| `README.md` (git) | provenance, licences, caveats |
| `network.parquet` | GeoParquet, one row per link: `segment_id`, `u`, `v`, `length_m`, `road_class`, `highway`, `name`, `ref`, `allow_{walking,cycling,car,heavy}`, `dir_car`, `dir_cycling` (`both`, `forward` = u to v, `backward`), `pair_segment`, geometry (u to v) |
| `sites.csv` | `site_id`, `mode`, `value`, `source`, `licence`, `method`, `n_days`, `x`, `y`, `lon`, `lat`, `group_id`, `fold` |
| `crosswalk.csv` | `site_id`, `mode`, `segment_id`, `weight`, `dist_m`, `rule`. A site's prediction is the weighted sum of its links' flows. |
| `inputs/` | T1 `population.parquet`, `pois.parquet`. T2 `zones.parquet`, `od_synthetic.parquet`. T3 `od_observed.parquet`, `zones_observed.parquet` |

**Network (v0.3).** Raw OpenStreetMap, built by
`benchmark/build_osm_network.py` from a dated Geofabrik extract with
osmium-tool and pyosmium. Ways with a routable `highway` tag are split at
every node shared by two or more ways. Nothing is merged, deduplicated or
dropped. `segment_id` is `<osm way id>-<k>`, `u` and `v` are OSM node ids.
Access and direction per mode come from OSM tags. The clipped highway
extract ships as `source.osm.pbf` so the network can be rebuilt exactly.
Adapters snap OD zones to the largest connected component of each mode's
network. Release v0.2.0 used cleaned networks and stays available.

**Sites.** Sources that report one direction per sensor (listed in
`benchmark/rebuild_case_osm.py`) are paired: two sensors of the same source
and mode that are each other's nearest within 30 m become one two-way site
with the summed value. Published two-way counts (DfT) are not paired.

Road classes: `motorway`, `trunk`, `primary`, `secondary`, `tertiary`, `minor`,
`service`, `cycleway`, `footway`, `other`. Any change to a file makes a new case
version.

## Crosswalk rules

Built once by `benchmark/crosswalk.py`. The `rule` column records which rule
placed each row.

1. **Mode access.** A count matches only links open to its mode.
2. **Point counts.** Links within 30 m (or a declared per-source radius). A
   road name or number match is preferred. Motor counts take the most
   important class within 10 m of the nearest candidate. Walking and cycling
   take the nearest. Ties within 1 m go to a name match, then the longest link.
3. **Direction pairing.** Two-way counts meet two-way flows. If the
   matched link has a `pair_segment`, the partner is added with weight 1. If
   not and the link is one way for the mode, the partner is the nearest link
   within 50 m that is one way for the mode, runs the opposite way (more than
   135 degrees apart at the points nearest the count) and shares a name or
   ref (or the road class if the matched link has neither).
4. **Junction arms.** A turning count gives, per arm, the flow entering the
   junction from that arm. The two-way value is twice that (daily flows taken
   as symmetric). The arm is placed on the link within 30 m of the junction,
   open to the mode, whose direction away from the junction is within 45
   degrees of the arm bearing (motor counts: most important class first).
5. **Segment counts.** Largest overlap within a 15 m buffer, the most
   important class among overlaps within 20 percent.
6. **Unmatched counts** stay in `sites.csv` and are reported, not scored.

## Licence rules

- A count source enters a case only if it is in the reviewed table in
  `benchmark/licences.py`, with publisher, link and review note. Its licence
  comes from that table, never from a default or from text shipped with the
  data. Rejected sources are listed there with the reason.
- Open cases: OGL, CC0, CC BY, ODbL (share-alike, stated).
- Non-commercial cases (for example Telraam, CC BY-NC 4.0) are released as
  separate cases with `licence_class: non_commercial` and kept off the
  leave-one-city-out board.
- Networks and POIs are OpenStreetMap (ODbL). Population is WorldPop (CC BY).

## Distribution

`python -m benchmark.fetch --version v0.3.0` downloads case assets
(`<case_id>__<path>`) into `cases/<case_id>/` and fails on any sha256
mismatch. Results are assets named `results__<file>` (full leaderboard, legacy
board). The paper reads them with `benchmark.fetch.fetch_result`.

## Runs, hardware and provenance

Every run writes `run.json` (tool, version, family, options, variant, tier,
parameters, status) and `system.json` (CPU model, cores, threads, RAM, OS,
kernel, container image digest, harness commit, data release, wall time, CPU
time, peak memory). The leaderboard accepts only runs with both. Each machine
times a fixed reference workload once, and each run reports a speed index:
wall time over reference time.

Leaderboard rows carry: `benchmark_version, case_id, case_version, mode, tool,
tool_version, variant, family, options, input_tier, track, split, n_sites,
rho, log_r2, raw_r2, calibration_ratio, q, ranked, time_limit_s, wall_time_s, cpu_time_s,
speed_index, peak_memory_mb, cpu_model, container_image_digest, data_release,
run_id, git_commit, timestamp, status`.

**Time limit.** Each adapter process has a wall time limit (`run_all
--time-limit`, default 60 s). All modes of a case run in one process, so the
limit is per tool, variant and case (per fold on the tool-calibrated track).
On expiry the process is killed and the run is recorded with status `timeout`
and the limit. Its metrics are NA, never a score.

## Continuous integration

On every pull request: unit tests, the adapter contract check, and a smoke
test per open tool in its own container on the `oxford-mini-v1` case from the
release (`config/ci.yaml`). The smoke test checks valid predictions, coverage,
a raw rank correlation floor and calibrated q close to the class-only
baseline. Full cases run locally (`scripts/run_board.sh`).

## Out of scope

Hourly and peak flows, directional flows, route flows and turning flows.
