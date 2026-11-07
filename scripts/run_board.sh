#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=.
python -m benchmark.run_all "$@"
