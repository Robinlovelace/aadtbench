# AADTBench

An open benchmark and harness for street-level multi-modal traffic estimation (walking, cycling, car, and heavy vehicles) across **5 open cities on 3 continents** (Bristol, London, Melbourne, Toronto, and Zurich). Any tool that writes one flow per link can be scored on equal terms.

**[Paper & Leaderboard](https://robinlovelace.net/aadtbench/paper/)** · **[Specification](BENCHMARK.md)** · **[Add a tool](IMPLEMENTATIONS.md)** · **[Full CSV](leaderboard-summary.csv)** · **[v0.1.0 Release](https://github.com/Robinlovelace/aadtbench/releases/tag/v0.1.0)**

## Quick start

Every tool runs inside its own container image (`ghcr.io/robinlovelace/aadtbench-<tool>:latest`), so only the lightweight harness is needed on the host:

```bash
pip install -r requirements.txt
python -m benchmark.fetch --version v0.1.0 --case bristol-v1
python -m benchmark.run_all --cases bristol-v1 --tools baselines cityseer_od aequilibrae una sdna --docker
```

Smoke-test a single tool on the CI mini case (`london-mini-v1`):

```bash
python -m benchmark.smoke --tool aequilibrae --docker
```

Run `scripts/run_board.sh` to execute the full 5-city suite from `config/benchmark.yaml`.

## Data, results, and contributing

- **Results:** See the [paper](https://robinlovelace.net/aadtbench/paper/) for the leaderboard, figures, and compute/energy analysis, or download [`leaderboard-summary.csv`](leaderboard-summary.csv) directly.
- **Case bundles:** 100% openly licensed networks (OSM, ODbL-1.0), WorldPop population (CC BY 4.0), and reviewed open counts live in the [v0.1.0 release](https://github.com/Robinlovelace/aadtbench/releases/tag/v0.1.0), verified by SHA-256 on download. London active travel counts are Powered by TfL Open Data (Contains OS data © Crown copyright and database rights 2026).
- **Contribute:** New tools, cities, and rule proposals are welcome via issues and pull requests — see [`BENCHMARK.md`](BENCHMARK.md) for the rules and [`IMPLEMENTATIONS.md`](IMPLEMENTATIONS.md) for the adapter contract and container images.
