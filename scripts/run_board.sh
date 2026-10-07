#!/usr/bin/env bash
# Run every tool on the default case set and rebuild results/leaderboard.csv.
# Open cases share one call per tool, so leave-one-city-out uses only open
# cases. Leuven (non-commercial) runs on its own. Cached runs are reused.
# bristol-v1 is in the release but not in the default set: pass it in OPEN to add it.
set -euo pipefail
export PYTHONPATH=.
OPEN=${OPEN:-"oxford-v1 leeds-v1 melbourne-v1 zurich-v1 toronto-v1"}
EXTRA=("$@")   # for example --force or --threads 8
for cases in "$OPEN" "leuven-v1"; do
  python -m benchmark.run_all --cases $cases --tools baselines "${EXTRA[@]}"
  python -m benchmark.run_all --cases $cases --tools cityseer_od --tier T2_synthetic_od --variants default dispersed "${EXTRA[@]}"
  python -m benchmark.run_all --cases $cases --tools aequilibrae --tier T2_synthetic_od --variants aon ue_bfw "${EXTRA[@]}"
done
cp results/summary.csv leaderboard-summary.csv
