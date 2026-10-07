---
name: flownet-benchmark-integration
description: flownet PSL assignment + the cenbench multimodal traffic benchmark suite (flownet integration, multi-city setup, ground truth sourcing, subagent delegation of runs)
---

# flownet benchmark integration

flownet (https://sebkrantz.github.io/flownet/) is an R package for **path-sized-logit (PSL)**
stochastic traffic assignment on multimodal transport networks. A common pattern is to
drive it from a Python benchmark harness: a thin R script does the assignment and writes a
per-edge flow CSV, and a Python wrapper snaps flows to validation sensors and computes
goodness-of-fit (R² / Pearson / Spearman). This skill records the traps that are NOT in the
vignette.

## Canonical working call (flownet R)

```r
suppressMessages(library(flownet)); suppressMessages(library(sf)); suppressMessages(library(igraph))
net   <- st_read(network_gpkg, quiet = TRUE)              # LINESTRING layer, OSMnx-style (u,v,key,osmid,length,...)
gr    <- linestrings_to_graph(net)                        # DIRECTED, keeps 1:1 edge order with net
origins <- st_transform(st_read(origins_geojson), st_crs(net))
dest    <- st_transform(st_read(dest_geojson),    st_crs(net))
nodes <- nodes_from_graph(gr, sf = TRUE)
orig_near <- nodes$node[st_nearest_feature(origins, nodes)]
dest_near <- nodes$node[st_nearest_feature(destinations, nodes)]
# build OD matrix: weight = origin population x destination attractor_weight
od_matrix[as.character(o), as.character(d)] <- w_o * w_d
od_long <- melt_od_matrix(od_matrix, nodes = od_nodes)
res <- run_assignment(gr, od_long, cost.column = ".length")   # canonical minimal call
```

The exact, copy-ready R script (with the edge-order fix, OD-subsample cap, and error
handling) is in `references/run_flownet_recipe.md`.

## CRITICAL trap — graph consolidation breaks edge-order mapping

`linestrings_to_graph(net)` **followed by** `create_undirected_graph() |> normalize_graph()`
**consolidates** parallel/directed edges: a 19,118-edge OSMnx walk network collapses to
~9,464 graph edges. `run_assignment` then returns `final_flows` of length 9,464, which does
**NOT** align 1:1 with the original 19,118-row network GPKG. Every attempt to map flows back
by `attr(gr, "group.starts")` or by `(u,v)` join fails (you get ~18 edges matched, all ~0,
or "object 'group.starts' not found" because `gr` is flownet's `graph_df` S3 class, not a raw
igraph — `edge.attributes(gr)` / `E(gr)` throw "Must provide a graph object").

**Fix:** use the DIRECTED graph — `gr <- linestrings_to_graph(net)` and NOTHING else. Then
`nrow(gr) == nrow(net)` (19,118 == 19,118) and `res$final_flows` aligns 1:1 with `net` rows
(`net$u`/`net$v` match `gr$u`/`gr$v` 1:1). Assign directly:

```r
out_df <- data.frame(edge_idx = seq_len(nrow(net)) - 1, flow = res$final_flows)
write.csv(out_df, out_csv, row.names = FALSE)
```

The Python wrapper then matches `edge_idx` (0-based) to the geopandas edge frame's
`reset_index()` integer index. Verified working: directed gr → `len(final_flows)=19118`,
`sum≈9.1e8`.

## flownet quirks that waste time

- **You MUST `library(flownet)` inside the script.** A bare `Rscript script.R` with no
  `library(flownet)` fails with `could not find function "run_assignment"` (and the misleading
  secondary error `object 'flows' not found` during wrapup). Test invocations that pre-load
  flownet in the REPL mask this.
- **Cost-column check belongs on the GRAPH, not the GPKG.** The GPKG column is `length`;
  flownet expects `.length` which `linestrings_to_graph` adds to the graph. Checking
  `cost_col %in% names(net)` throws "Cost column .length not found in network layer". Drop the
  strict check and let `run_assignment` report a clear error if missing.
- **`run_assignment` signature (flownet 0.3.0, VERIFIED)**: `run_assignment(graph_df,
  od_matrix_long, directed=FALSE, cost.column="cost", method=c("PSL","AoN"), beta=1, ...,
  detour.max=1.5, angle.max=90, unique.cost=TRUE, npaths.max=Inf, dmat.max.size=10000^2,
  return.extra=NULL, verbose=TRUE, nthreads=1L)`. `method`, `beta`, `detour.max`,
  `angle.max` and `nthreads` (mirai daemon parallelism) are ALL supported. **WIRE THEM
  THROUGH** — an older note in this skill ("extra args trigger an undefined columns
  selected error, prefer the minimal call, leave beta/detour unused") predates 0.3.0 and
  caused a real benchmark bug: a wrapper that accepted beta/detour on the CLI but never
  passed them produced six IDENTICAL variants (same R² across all beta/detour combos).
  Retest the full signature on the installed version before trusting the minimal call.
  If a param still errors, wrap in tryCatch and write conditionMessage to
  /tmp/fn_real_err.txt (see error-handling note below), then fall back gracefully.
- **`run_assignment` result object**: `res` has `names(res)` = `c("call", "final_flows", "od_pairs_used")` — there is **NO `element_ids`** field (despite some flownet docs implying edge ids). `length(res$final_flows)` equals the number of graph edges (9,464 on a consolidated undirected graph, 19,118 on the directed graph). On the directed graph this equals `nrow(net)`, giving the 1:1 mapping above. `res$od_pairs_used` reports how many OD pairs were assigned (some are skipped as zero/non-finite).
- **R error-handler recursion MASKS the real error.** The tempting `options(error = function(e){ cat(conditionMessage(e)); quit() })` pattern is dangerous: when `run_assignment` errors, R's wrapup re-enters the handler ("no more error handlers available (recursive errors?); invoking 'abort' restart" / "Error during wrapup: argument 'e' is missing"), and the *actual* cause (e.g. `could not find function "run_assignment"` from a missing `library(flownet)`, or `object 'flows' not found`) is buried or replaced by a misleading secondary message. **Fix:** wrap the assignment in `tryCatch` and write the real `conditionMessage(e)` to a FILE (stdout is buffered and lost behind `| tail`):
  ```r
  res <- tryCatch(run_assignment(gr, od_long, cost.column = cost_col),
                  error = function(e) {
                    con <- file("/tmp/fn_real_err.txt", open = "wt")
                    writeLines(c("RUN_ASSIGNMENT ERROR:", conditionMessage(e)), con); close(con)
                    stop(conditionMessage(e))
                  })
  ```
  Then read `/tmp/fn_real_err.txt` to see the true root cause. (In one session the file revealed `could not find function "run_assignment"` — the missing `library(flownet)` — which the console only showed as `object 'flows' not found`.)
- **`od_long` columns** from `melt_od_matrix` are `from`, `to`, `flow`.
- **`linestrings_from_graph(gr)`** on a consolidated (undirected/normalized) graph returns the
  consolidated edge count, NOT the original net — don't use it to recover net order.

## OD-subsample for tractability

flownet's exhaustive path-size-logit on the FULL OD matrix (e.g. 861k pairs for Leuven
WorldPop×OSM attractors) is extremely heavy — easily 15+ min and can appear to hang. Cap the
OD matrix to the top-N zones by population (origins) and attractor_weight (destinations), e.g.
150. This covers the dense urban core where validation sensors sit, is a defensible benchmark
config, and finishes in seconds. Subset BEFORE snapping:

```r
if (nrow(origins) > od_sample) origins <- origins[order(-as.numeric(origins$population))[seq_len(od_sample)], ]
if (nrow(destinations) > od_sample) destinations <- destinations[order(-as.numeric(destinations$attractor_weight))[seq_len(od_sample)], ]
```

## Metric consistency across tools (linear vs log-log R²)

**Superseded by the canonical scorer (see CORRECTION above):** the shared scorer reports
BOTH raw- and log1p-scale predictive R² for every tool on the same held-out links, so
nothing in an individual wrapper should decide the transform. The rule below remains useful
for interpreting dev-stage sensor-level comparisons only.

When flownet is one tool among several in a benchmark, its R² is only comparable if the
SAME metric transform is used for all tools on the same ground truth. Leeds DfT AADT spans
~100 to ~150,000 vehicles/day: linear R² is dominated by the few largest counts, while the
other OD tools used log-log R² (compute_metrics_loglog, log1p transform). A flownet wrapper
computing plain linregress R² therefore looked far worse AND was not comparable. **Rule:**
order-of-magnitude ground truth (AADT, large counts) → log-log R² for EVERY tool on that
ground truth; near-uniform counts (Telraam walk) → linear R² everywhere. Mixing transforms
across tools on the same validation set silently breaks the comparison table.

## Demand realism dominates assignment algorithm

flownet fed the synthetic WorldPop×OSM-attractor gravity OD scored ~0.004 R² on Leeds
drive, while cityseer_od using the REAL 2011 Census journey-to-work OD (pct::get_od,
car_driver column; zones via get_pct_zones(geography="msoa")) scored 0.180 on the same
network and sensors. When a real OD matrix exists for the study area, flownet (and any
demand-driven tool) must be fed the SAME real OD as the other tools — not synthetic
gravity — or the comparison measures demand quality, not assignment method. Build the OD
from the city's od_file/zones_file config (snap zone centroids to graph nodes, melt to
long from/to/flow), capped by the OD-subsample rule above.

## Identical-variants smoke test

If every variant of a tool returns the same R² (e.g. 6 flownet variants all 0.0039),
the harness is not actually varying what it claims — check the wrapper passes its CLI
args into the library call (see signature note above), and that the metric transform is
identical across variants. Identical results across "variants" is a harness bug signal,
not a finding. Cheap liveness check: `sum(res$final_flows)` should differ between
method="AoN" and method="PSL" runs — if the totals match exactly, the method arg is not
reaching run_assignment().

## CORRECTION (2026-08-10): the sensor-level R² values in this skill are NOT benchmark scores

All R² numbers recorded below (flownet 0.0601/0.165/0.506, cityseer_od 0.180, aequilibrae
0.096) are SENSOR-LEVEL scores: tool output matched to count points via KDTree and scored
with correlation² / log-log R² by each tool's own wrapper. The cenbench v1 canonical rework
(dev/held-out split + shared scorer, see `benchmark-integration` skill "Canonical evaluation
contract") showed those rankings were inflated and non-comparable:

- cityseer_od sensor-level "0.18" → **raw predictive R² 0.0005** held-out. Cause: `betweenness_od`
  only accumulates flow within its radius of OD zones — 83% of matched sensors got ZERO flow at
  5 km on the 10 km-clip network, and correlation² on near-zero-filled predictions is not a
  predictive score.
- flownet sensor-level "0.0601" → **-0.014** held-out (AoN best dev variant; PSL variants worse).
- aequilibrae UE sensor-level 0.096 → **0.166** held-out raw R² — the actual v1 leader, and its
  UE beat its own AoN (0.034 dev). T2 synthetic-gravity OD scored 0.111, close to T3 census OD.

**Rule:** for multi-tool comparisons, never trust sensor-level R² recorded by individual
wrappers. The tool-specific mechanics in this skill (directed-graph edge alignment, params
wiring, cost-formula levers, OD caps) remain valid — they are about producing correct flows —
but the NUMBERS must be re-scored through the canonical shared scorer on held-out links before
they mean anything. Treat the "verified results" sections below as development evidence, not
headline results.

## Verified results after the fixes (Leeds drive, 2026-08-07 — SENSOR-LEVEL, see correction above)

Fixing the three bugs (wire params through, real pct census OD instead of synthetic
gravity, log-log R² for AADT) took flownet from R²=0.0039 (all 6 variants identical,
~510s each) to R²=0.0601 in 5.6s — a 15x jump. **Surprising verified finding: AoN with
a dimensionless-impedance cost (0.0601) beat every PSL variant (best 0.0576)** — on
free-flow AADT ground truth, single-path assignment with impedance weighting captures
traffic better than route dispersion. Full before/after table, variant naming (`_ll`
suffix = log-log metrics) and reproduction commands:
`references/leeds-improvement-results.md`.

## Python wrapper pattern (Rscript + subprocess)

- Build the cmd: `["Rscript", R_SCRIPT, edges, origins, dests, ".length", str(beta), str(detour), out_csv, mode, str(OD_SAMPLE)]`.
- **Use a UNIQUE temp filename per invocation** (e.g. `_flownet_{city}_{mode}_{variant}.csv`,
  then `os.remove` after reading). If every run writes the same path, concurrent/orphaned
  R processes clobber each other's output.
- Read flows with `pd.read_csv(out_csv)`, map `edge_idx→flow`, then
  `edges.index.map(lambda i: flow_map.get(int(i), np.nan))`. Snap sensors with `scipy.spatial.cKDTree`
  on edge centroids; keep only matched (`dist <= MATCH_DIST`, e.g. 200 m).
- Compute metrics robustly: drop NaN pairs, require `n >= 3` and non-constant predictions
  before `linregress`/`pearsonr`/`spearmanr`.
- See `references/python_wrapper_pattern.md` for the snapped-metric snippet.

## Pitfalls — agent process discipline

- **Orphaned R subprocesses survive `process kill` of the parent bash.** When you launch
  `Rscript ...` via the terminal tool in background mode, killing the tracked session only
  kills the bash wrapper; the `/usr/lib/R/bin/exec/R` child keeps running at 100% CPU. Multiple
  such orphans peg all cores and make later runs look like hangs. Mitigations: (a) always use
  unique temp output paths, (b) prefer smaller OD subsamples so runs finish fast, (c) do NOT
  rely on `process kill` to clean up R children.
- **Never run `pkill`/broad destructive commands without explicit user consent.** In this
  session the user BLOCKED a `pkill -9 -f run_flownet_assignment.R`. Respect that: ask first,
  or work around it (unique temp files, smaller problem size) instead of killing.
- **Long Python refactors: avoid whole-file programmatic re-indent via `execute_code`.** It
  repeatedly tangled (double-indent, dropped `def main():`, "unexpected indent", mode loop not
  nested). Instead: (1) `patch` the import line; (2) insert the `for mode in modes:` header +
  mode-aware load block via a slice-based re-indent that keeps `def main():` in `head` (re-indent
  only `body = lines[main_idx+1:guard_idx]`, anchor replacements on the ORIGINAL 4-space
  indentation, `ast.parse` BEFORE writing); (3) `patch` the `new_rows.append` dict and gate the
  map section with `if mode != "walk": continue`. Verify with `ast.parse` + a TEST_MODE run.

## Cost-formula levers: the single biggest accuracy lever (Leuven, 2026-08-08 — SENSOR-LEVEL numbers, see correction above)

After wiring params + real OD + log-log metrics, the NEXT big lever is the edge-cost
formula passed as `cost.column`. flownet's PSL utility is `V = -cost + beta*ln(PS)`; with
cost in raw metres (~10^3) the logit is degenerate (all mass on the shortest path) and
`beta` has no visible effect. Two portable transforms, both passed as a precomputed cost
VECTOR (not a column name — `cost.column` accepts a numeric vector of length nrow(graph)):

- **cost_div rescale** (e.g. /1000 → km): keeps the logit sensitive to `beta`.
- **cost_type = "imp"** (dimensionless impedance): multiply length by a highway-class speed
  ratio `BASELINE_MS / (class_mph * 0.44704)` so major roads are relatively cheaper —
  the same lever that fixed cityseer_od vs DfT AADT on Leeds.

**Verified Leuven wide-boundary results (2026-08-08)**: flownet became the accuracy leader
on BOTH new modes with these formulas — cycle linear R² 0.506 (psl_imp_km_beta0.05_detour2.0),
drive log-log R² 0.165 (psl_km_beta0.01_detour1.5) — beating cityseer_od (0.065 drive) and
aequilibrae (0.051 drive). Weight formula > route dispersion: `aon_imp` (0.496) ≈
`psl_imp_km` (0.506) on cycle — AoN with the right cost captures nearly everything, PSL's
route dispersion adds little once the cost is right. So when a flownet run looks weak,
sweep the COST FORMULA (length / time / imp / imp_km) before the assignment method.

## R gotcha: tapply non-conformable arrays in the top-N zone cap

When the real-OD path caps zones by total flow, `tapply(flow, geo_code1, sum)` and
`tapply(flow, geo_code2, sum)` return arrays with DIFFERENT factor levels (origins and
destinations are different zone sets) and `zflow + zflow2` fails with
"Error: non-conformable arrays" — which the error-handler recursion then MASKS as
"object 'od_long' not found". Fix: add over a UNION of all zone codes:

```r
all_codes <- union(as.character(od_df$geo_code1), as.character(od_df$geo_code2))
zflow  <- tapply(od_df[[flow_col]], factor(od_df$geo_code1, levels = all_codes), sum)
zflow2 <- tapply(od_df[[flow_col]], factor(od_df$geo_code2, levels = all_codes), sum)
zflow[is.na(zflow)] <- 0; zflow2[is.na(zflow2)] <- 0
zflow <- zflow + zflow2
```

(Leeds was never hit because its 103 zones < the 150 cap; Leuven's 159 zones triggered it.)
Symptom to grep for: `non-conformable arrays` followed by the masked `od_long not found`.

## Multi-city expansion: ground truth, networks, config (Leeds + Oxford, 2026-08-08)

**NEW CITY CRS RULE: store network GPKGs in EPSG:4326, never the projected CRS** —
flownet's `nodes_from_graph()` returns 4326 nodes regardless of network CRS, so a 27700
network crashes `st_nearest_feature` (see "nodes_from_graph() ALWAYS returns EPSG:4326"
below). Full recipes: `references/multicity-delegation.md` (ground truth table, graphml→gpkg
conversion, sDNA binary gotcha, per-variant timeout trap).

The suite generalizes to a new city via config/cities.yaml plus 4 prep scripts. This is the
proven recipe for a UK city, with the exact traps.

**CRITICAL trap — nodes_from_graph() ALWAYS returns EPSG:4326, regardless of network CRS:**
`nodes_from_graph(gr, sf = TRUE)` returns nodes hard-coded to EPSG:4326 even when the
network GPKG is projected (e.g. BNG 27700), so `st_nearest_feature(zones$centroid, nodes)`
dies with `Error: st_crs(x) == st_crs(y) is not TRUE` — the script only transforms zones to
the network CRS, never nodes. The repo convention (verified: all leeds_*_edges.gpkg) is to
STORE networks in 4326; the Python bench scripts reproject internally so they don't care,
only the R flownet script is CRS-sensitive. Fix: re-export new-city networks as EPSG:4326
(`gdf.to_crs(4326)` before `to_file`), or patch the R script with
`nodes <- st_transform(nodes, net_crs)` before `st_nearest_feature`. Diagnosis probe: print
`st_crs(net)` vs `st_crs(nodes_from_graph(linestrings_to_graph(net), sf=TRUE))` — they
disagree for a projected network.

**Ground truth sourcing — check local repos BEFORE hitting APIs:**
- **Drive**: DfT AADT (OGL) via `scripts/prepare_leeds_ground_truth.py` (roadtraffic.dft.gov.uk
  AADF zip). Preferred over the WYCA/TAM copy because DfT is OGL; TAM is © WYCA.
- **Leeds walk/cycle**: WYCA TAM data already lives in `~/github/robinlovelace/countswyca/data/tam_aadt.geojson`
  (404 sites, AADT by mode: pedestrian/cycle/car/heavy). `scripts/prepare_leeds_tam_ground_truth.py`
  clips to the city bbox (`.cx[lon0:lon1, lat0:lat1]`), renames `pedestrian`→`avg_daily_pedestrians`,
  `cycle`→`avg_daily_cyclists`, writes EPSG:4326 geojson. Got 197 sites in the Leeds 10 km bbox.
  NOTE: Telraam has NO sensors in Leeds (counterflow telraam.duckdb has 12k segments UK-wide, 0 in
  Leeds bbox; the Telraam `/v1/segments` endpoint 403s even with the token). Config's original
  `leeds_telraam_*` sensor paths were never-populated placeholders — repoint at the TAM files.
- **Oxford walk/cycle/drive**: oxflow (`~/github/robinlovelace/oxflow/data/counters.duckdb`) has
  270 sensors (179 ATC + 91 Telraam, Jan–Jun 2026) with daily pedestrian/cycle/car counts.
  `scripts/prepare_oxford_ground_truth.py` aggregates `movements_daily` → mean daily per sensor,
  filters to the 10 km box, and writes EPSG:27700 geojson. Got 49 pedestrian (Telraam-only —
  ATC reports pedestrian=0), 77 cycle, 99 car sites. Sensor value columns must be named exactly
  `avg_daily_pedestrians` / `avg_daily_cyclists` / `avg_daily_cars` (the bench scripts do
  `tel[sensors_value]` — a mismatch is a KeyError).

**Network prep — bench scripts load via `gpd.read_file`, which CANNOT read graphml:**
`scripts/prepare_oxford_networks.py` uses `osmnx.load_graphml()` → `ox.graph_to_gdfs()` → write
GPKG, then clips ALL modes to a common box (`gdf.cx[...]`) so walk/cycle/drive are comparable
(the shipped oxford_walk.graphml spanned 51.62–51.90 lat while the cycle network only covered
51.71–51.80 — clipping fixed the mismatch). Cycle network: filter the oxflow mixed network
(BNG 27700, already has cycleways) by a CYCLE_HW allowlist.

**Config traps (config/cities.yaml):**
- Oxford's original block had only `crs_project` + modes → `prepare_demand.py` crashed with
  `KeyError: 'origins_file'` because it reads city-LEVEL `origins_file`/`destinations_file`
  keys (shared across modes), not per-mode ones. Add bbox, overpass_bbox, worldpop_url,
  worldpop_local_tif, city-level origins/destinations, AND od_file/zones_file (cityseer_od and
  aequilibrae `[skip]` silently if od_file/zones_file are missing).
- OD for a city without census OD: `scripts/prepare_oxford_od.py` mirrors prepare_leuven_od.py —
  aggregate WorldPop origins + attractors onto a 400 m grid, gravity weight flow(o,d)=pop_o*weight_d.
- Verify with a config-check script (get_mode_config for each city/mode, assert every file exists)
  before running anything.

## Delegating benchmark runs: subagent cap + tool-ownership split

`delegation.child_timeout_seconds: 600` in ~/.hermes/config.yaml kills subagents at 10 min —
Task B of the first Leuven delegation timed out mid-summary (its CSVs were still written, so
results survived; the summary didn't). Sizing rule of thumb from real Leeds runtimes (per mode):
sDNA ~93 s/variant × 21 = 32 min; flownet ~11 min; madina_worldpop ~6 min; centrality ~3 min;
aequilibrae ~40 s; cityseer_od ~5 s.

**Split: fast tools → subagents, slow tools → parent background jobs.**
- Delegate the fast 4 (cityseer_od, aequilibrae, centrality, cityseer_demand) to subagents
  (deepseek-v4-flash via opencode-go, pinned in config). Each subagent owns EXACT per-tool CSVs
  (`results/{city}_{tool}_results.csv`) — no two agents touch the same file.
- Run the slow 3 (madina_worldpop, flownet, sDNA) yourself with `terminal(background=true,
  notify_on_complete=true)` via a wrapper script — do NOT delegate them.
- **CRITICAL csv_utils.merge_to_csv() semantics**: it DELETES all rows for a tool then appends.
  A run for new modes only clobbers existing rows for other modes. Mandate: backup each CSV to
  /tmp before every run, verify pre-existing mode rows survive, and recombine
  (pandas concat + drop_duplicates on tool,mode,variant) if clobbered. A `run_slow_tools.sh`
  wrapper (backup → run → recombine → check for "OUTPUT TRUNCATED") is in
  `references/multicity-delegation.md`.
- **bash gotcha that silently no-ops a whole background job**: `PY=PYTHONPATH=.` then
  `$PY .venv/bin/python ...` does NOT set the env var — bash treats `PYTHONPATH=.` as a command
  name ("PYTHONPATH=.: command not found"), the script exits non-zero, and with `set -uo pipefail`
  (no `-e`) the wrapper just continues with an unchanged CSV. Always write the env prefix
  literally: `PYTHONPATH=. .venv/bin/python ...`.
- Variant grids for comparability: extract existing variant names per (tool, mode) from
  `results/leuven_results.csv` and mirror them in the new city's runs (the scripts' defaults may
  differ from what was committed).

## Validation checklist

- [ ] Script does `library(flownet)` (not just in REPL tests).
- [ ] Graph is DIRECTED (`linestrings_to_graph(net)` only) for 1:1 edge alignment.
- [ ] Output is `edge_idx, flow` with `edge_idx` 0-based = net read order.
- [ ] OD capped (od_sample) so runs finish in seconds, not appear to hang.
- [ ] Python wrapper uses unique temp CSV and matches `edge_idx` to `edges.index`.
- [ ] `ast.parse` passes and `TEST_MODE=True` run produces a results CSV.
