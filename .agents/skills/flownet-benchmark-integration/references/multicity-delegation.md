# Multi-city benchmark expansion + delegation (cenbench, 2026-08-08)

Proven recipe for adding walk/cycle/drive results for a new city, and for splitting
benchmark runs between subagents and parent background jobs.

## Ground truth data sources (UK cities)

| City | Mode | Source | License | Prep script | Result |
|---|---|---|---|---|---|
| Leeds | drive | DfT AADT (roadtraffic.dft.gov.uk AADF zip) | OGL | prepare_leeds_ground_truth.py | leeds_dft_aadt_27700.geojson (aadt_all_motor_vehicles) |
| Leeds | walk/cycle | WYCA TAM, `~/github/robinlovelace/countswyca/data/tam_aadt.geojson` (404 sites, AADT by mode) | © WYCA (flag in paper) | prepare_leeds_tam_ground_truth.py | leeds_tam_pedestrians/cyclists_4326.geojson, 197 sites in 10 km bbox |
| Oxford | walk/cycle/drive | oxflow `~/github/robinlovelace/oxflow/data/counters.duckdb` (179 ATC + 91 Telraam, Jan–Jun 2026) | oxflow project data | prepare_oxford_ground_truth.py | oxford_telraam_{pedestrians,cyclists,cars}_27700.geojson (49/77/99 sites) |

Notes:
- Telraam API: token in `~/.srt/gemini.env` (`TELRAAM_TOKEN=`), used by fetch_telraam_modes.py
  against `/v1/reports/traffic`. The `/v1/segments` endpoint returned 403 even with the token —
  don't plan around it. Telraam has no Leeds sensors (counterflow telraam.duckdb = 12k segments
  UK-wide, 0 in the Leeds bbox).
- ATC sensors report pedestrian=0 — the Oxford walk layer must be Telraam-only.
- Sensor value column names must be EXACTLY `avg_daily_pedestrians` / `avg_daily_cyclists` /
  `avg_daily_cars` — bench scripts do `tel[sensors_value]`, a mismatch is a KeyError.

## Network prep (graphml → gpkg)

Bench scripts load networks with `gpd.read_file()` — they CANNOT read the shipped osmnx
graphmls. Convert with osmnx, then clip all modes to a common box.

**CRITICAL: export networks in EPSG:4326, NOT the projected CRS.** flownet's
`nodes_from_graph(gr, sf=TRUE)` returns nodes hard-coded to EPSG:4326 regardless of the
network's CRS, so `st_nearest_feature(zones$centroid, nodes)` crashes with
`st_crs(x) == st_crs(y) is not TRUE` for a 27700 network (only zones get transformed to
net CRS, never nodes). The repo convention (verified: all leeds_*_edges.gpkg) is to store
networks in 4326 — the Python bench scripts reproject internally so they don't care;
only the R flownet script is CRS-sensitive. Clip using the projected CRS for box math,
then re-export 4326:

```python
import osmnx as ox
G = ox.load_graphml("data/oxford_walk.graphml")          # EPSG:4326 osmnx graphml
nodes, edges = ox.graph_to_gdfs(G, nodes=True, edges=True)
edges = edges[["geometry", "length", "highway"]]
edges = edges.to_crs("EPSG:27700").cx[446285:456424, 201152:211197]  # clip in projected CRS
edges.to_crs("EPSG:4326").to_file("data/oxford_walk_edges.gpkg", driver="GPKG")
```

Cycle network: filter a full mixed OSM network (oxflow's oxford_network.graphml is BNG 27700
with cycleways) by a highway allowlist:
`{"cycleway","path","footway","residential","service","tertiary","secondary","primary","unclassified","track","living_street","pedestrian","steps","bridleway"}`.

## Config traps (config/cities.yaml)

- `prepare_demand.py` reads CITY-LEVEL `origins_file`/`destinations_file` (not per-mode).
  Oxford's original block (only crs_project + modes) crashed: `KeyError: 'origins_file'`.
- cityseer_od + aequilibrae silently `[skip]` if `od_file`/`zones_file` are missing.
- New city needs: bbox, overpass_bbox, worldpop_url, worldpop_local_tif, city-level
  origins/destinations, od_file/zones_file, and per-mode network/sensors/origins/destinations.
- OD for a city without census OD: prepare_oxford_od.py (mirror of prepare_leuven_od.py) —
  400 m grid over WorldPop origins + OSM attractors, gravity flow(o,d) = pop_o * weight_d.
  Oxford: 673 zones, 93.5k OD pairs.
- Verify with a config-check script before running: get_mode_config(city, mode) for each mode,
  assert network_file/sensors_file/origins/destinations/od/zones all exist.

## Delegation split (subagent cap = 600 s)

`delegation.child_timeout_seconds: 600` in ~/.hermes/config.yaml → subagents die at 10 min.
Real Leeds per-mode runtimes: sDNA ~93 s × 21 variants = 32 min; flownet ~11 min;
madina_worldpop ~6 min; centrality ~3 min; aequilibrae ~40 s; cityseer_od ~5 s.

- **Delegate** (fast 4, each subagent owns disjoint per-tool CSVs):
  `bench_cityseer_od.py`, `bench_aequilibrae.py`, `bench_centrality.py`, `run_cityseer_demand_experiments.py`
- **Run yourself in background** (slow 3): `run_madina_demand_experiments.py`, `bench_flownet.py`,
  `bench_sdna.py` — via `terminal(background=true, notify_on_complete=true)`.

CSV-safety rule (merge_to_csv deletes a tool's rows then appends): backup every target CSV
before each run; after each run verify old-mode rows survive; if clobbered, re-run all modes in
one invocation or recombine backup + new rows deduped on (tool, mode, variant).

**Script-level fix (better than backup/recombine)**: instead of calling `merge_to_csv` once per
mode inside the mode loop (which clobbers earlier modes' rows on multi-mode runs), accumulate
`all_results.extend(mode_rows)` across modes and call `merge_to_csv` ONCE after the loop. This
is what a subagent did to bench_cityseer_od.py and run_cityseer_demand_experiments.py — a
minimal, keep-worthy diff that removes the clobber hazard at the source. Check for it when
reviewing subagent diffs.

## run_slow_tools.sh — proven wrapper (parent background job)

```bash
#!/usr/bin/env bash
# Usage: bash run_slow_tools.sh CITY MODES...
set -uo pipefail
CITY=$1; shift
MODES="$*"
cd /home/robin/github/robinlovelace/cenbench

recombine() {
  local CSV=$1 BAK=$2
  if [ ! -f "$BAK" ]; then return; fi
  .venv/bin/python - "$CSV" "$BAK" <<'PYEOF'
import sys
import pandas as pd
csv, bak = sys.argv[1], sys.argv[2]
old = pd.read_csv(bak); new = pd.read_csv(csv)
keys = [c for c in ["tool", "mode", "variant"] if c in old.columns and c in new.columns]
pd.concat([old, new], ignore_index=True).drop_duplicates(subset=keys, keep="last").to_csv(csv, index=False)
print(f"recombined {csv}: {len(old)} old + {len(new)} new")
PYEOF
}

for TOOL_SCRIPT in \
  "madina_worldpop:scripts/run_madina_demand_experiments.py" \
  "flownet:scripts/bench_flownet.py" \
  "sdna:scripts/bench_sdna.py"; do
  TOOL="${TOOL_SCRIPT%%:*}"
  # sDNA binary lives in .venv/bin — add it to PATH or bench_sdna.py crashes
  # with FileNotFoundError: 'sdnaintegral' (see sDNA gotcha below).
  export PATH="$PWD/.venv/bin:$PATH"; SCRIPT="${TOOL_SCRIPT##*:}"
  CSV="results/${CITY}_${TOOL}_results.csv"
  BAK=""
  if [ -f "$CSV" ]; then BAK="/tmp/backup_${CITY}_${TOOL}.csv"; cp "$CSV" "$BAK"; fi
  # CRITICAL: env prefix must be literal. `PY=PYTHONPATH=.` then `$PY cmd` does NOT
  # set the var — bash treats "PYTHONPATH=." as a command name and the run silently no-ops.
  PYTHONPATH=. .venv/bin/python "$SCRIPT" --city "$CITY" --modes $MODES
  if [ -n "$BAK" ]; then recombine "$CSV" "$BAK"; fi
  grep -q "OUTPUT TRUNCATED" "$CSV" 2>/dev/null && { echo "ERROR: truncated marker"; exit 1; }
  echo "after: $(tail -n +2 "$CSV" | wc -l) rows"
done
echo "ALL SLOW TOOLS DONE FOR $CITY"
```

## Delegation prompt essentials (fast-tool subagents)

- State exact CSV ownership per subagent (no two agents touch the same per-tool CSV).
- Mandate: backup → run → verify mode rows survive (tail + cut -d, -f1,2 + sort | uniq -c) →
  recombine if clobbered.
- Ban `scripts/merge_all.py` and the merged `results/{city}_results.csv` (parent merges).
- Ban git commits/pushes; foreground runs only; after writing any file check it has no literal
  "OUTPUT TRUNCATED".
- Give variant grids explicitly (extract from leuven_results.csv) — script defaults may differ
  from committed rows.
- Ask for a summary file with exact commands, row counts per (tool,mode), top-3 variants by
  R² per new (tool,mode), git diff --stat, metric used (linear vs log-log), deviations.

## sDNA binary gotcha (bench_sdna.py, 2026-08-08)

`sdnaintegral` is installed in the project venv (`.venv/bin/sdnaintegral`), NOT on the
system PATH. `bench_sdna.py` has a resolution bug: `check_sdna()` returns True when the
venv binary exists (it checks `os.path.dirname(sys.executable)/sdnaintegral`), but the
script's `sdna_bin` variable stays the bare `"sdnaintegral"` — so the subprocess call
crashes with `FileNotFoundError: 'sdnaintegral'` even though the binary is present.

**Two-layer fix (do both):**
1. Runner scripts: `export PATH="$PWD/.venv/bin:$PATH"` before invoking bench_sdna.py.
2. Script-level (permanent): replace the check with
   `sdna_bin = shutil.which("sdnaintegral")` and only fall back to the venv path
   `os.path.join(os.path.dirname(sys.executable), "sdnaintegral")` when `which` returns
   None. (shutil is already imported in the script.)

Also note: sDNA installs single-threaded unless rebuilt with OpenMP
(install-sdna-multithreaded.sh); Leeds ~93 s/variant × 21 variants × 2 modes is why sDNA
belongs in the parent background job, not a 600 s subagent.

## Per-variant timeout traps in demand scripts

`run_madina_demand_experiments.py` runs each variant with a ~75 s per-variant timeout
(threshold in the script). On a bigger network (Leeds walk: 195 matched sensors vs Leuven's
22) variants time out and return NaN rows — the script then reports
"NO VALID R-SQUARED RESULTS (ALL EXPERIMENTS TIMED OUT OR RETURNED NA)". Check the
script's per-variant timeout threshold when scaling to a larger city; raise it or trim
the variant grid to keep runs under the cap.
