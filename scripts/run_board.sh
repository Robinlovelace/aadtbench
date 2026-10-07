#!/usr/bin/env bash
# Run every tool on every case and rebuild results/leaderboard.csv.
# Open cases share one call per tool, so leave-one-city-out uses only open
# cases. Leuven (non-commercial) runs on its own. Cached runs are reused.
set -euo pipefail
export PYTHONPATH=.
OPEN="oxford-v1 leeds-v2 bristol-v1 melbourne-v1 leeds-v1"
EXTRA=("$@")   # for example --force or --threads 8
python -m benchmark.run_all --cases $OPEN --tools baselines "${EXTRA[@]}"
python -m benchmark.run_all --cases $OPEN --tools cityseer_od --tier T2_synthetic_od --variants default dispersed "${EXTRA[@]}"
python -m benchmark.run_all --cases $OPEN --tools aequilibrae --tier T2_synthetic_od --variants aon ue_bfw "${EXTRA[@]}"
python -m benchmark.run_all --cases leeds-v1 --tools cityseer_od --tier T3_observed_od --variants default dispersed "${EXTRA[@]}"
python -m benchmark.run_all --cases leeds-v1 --tools aequilibrae --tier T3_observed_od --variants aon ue_bfw "${EXTRA[@]}"
python -m benchmark.run_all --cases leuven-v1 --tools baselines "${EXTRA[@]}"
python -m benchmark.run_all --cases leuven-v1 --tools cityseer_od --tier T2_synthetic_od --variants default dispersed "${EXTRA[@]}"
python -m benchmark.run_all --cases leuven-v1 --tools aequilibrae --tier T2_synthetic_od --variants aon ue_bfw "${EXTRA[@]}"
cp results/summary.csv leaderboard-summary.csv
