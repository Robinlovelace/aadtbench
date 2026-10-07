# AADTBench

An open benchmark and harness for estimating street-level flows of people and
vehicles. Any tool that writes one flow per link can be scored: centrality and
reach measures, betweenness and spatial interaction, traffic assignment, or
statistical models. The spec is [`BENCHMARK.md`](BENCHMARK.md). How to add a
tool is [`IMPLEMENTATIONS.md`](IMPLEMENTATIONS.md).

Code lives in git. Case data, run outputs and full leaderboards live in the
[v0.2.0 release](https://github.com/Robinlovelace/aadtbench/releases/tag/v0.2.0),
checked by sha256 on download.

## Quick start

```bash
pip install -r requirements.txt cityseer==4.24.1 aequilibrae==1.7.0
python -m benchmark.fetch --version v0.2.0
python -m benchmark.run_all --cases oxford-v1 --tools baselines
python -m benchmark.run_all --cases oxford-v1 --tools cityseer_od aequilibrae --tier T2_synthetic_od
cat results/LEADERBOARD.md
```

`scripts/run_board.sh` runs every case and writes `leaderboard-summary.csv`
(best variant per case, mode, track and tool), the only result kept in git.

## Cases (v0.2.0)

| Case | Modes | Counts licence |
|---|---|---|
| oxford-v1, oxford-mini-v1 (CI) | walking, cycling, car, heavy | OGL v3 |
| leeds-v2 | cycling, car, heavy | OGL v3 (DfT) |
| bristol-v1 | cycling, car, heavy | OGL v3 (DfT) |
| melbourne-v1 | walking, car, heavy | CC BY 4.0 |
| leeds-v1 | motor (legacy v0.1 case) | OGL v3 (DfT) |
| leuven-v1 | walking, cycling, car | CC BY-NC 4.0 (Telraam), non-commercial |

Networks and POIs: OpenStreetMap (ODbL). Population: WorldPop (CC BY 4.0).
Licences come from the reviewed table in `benchmark/licences.py`.

## Current results

Calibrated track, spatial group-out, q = (Spearman rho + log R2) / 2. Tools use
the T2 synthetic OD.

| Case | Mode | Class only | Best baseline | cityseer | AequilibraE AoN | AequilibraE UE |
|---|---|---|---|---|---|---|
| oxford-v1 | walking | -0.18 | 0.54 (attractor density) | -0.21 | -0.14 | |
| oxford-v1 | cycling | -0.33 | 0.35 (population density) | -0.12 | -0.18 | |
| oxford-v1 | car | 0.67 | 0.67 (attractor density) | 0.68 | 0.67 | 0.67 |
| oxford-v1 | heavy | 0.42 | 0.48 (centre distance) | 0.41 | 0.42 | 0.42 |
| leeds-v2 | cycling | -0.10 | 0.19 (centre distance) | 0.09 | -0.05 | |
| leeds-v2 | car | 0.55 | 0.60 (population density) | 0.57 | 0.59 | 0.58 |
| leeds-v2 | heavy | 0.49 | 0.52 (attractor density) | 0.49 | 0.51 | 0.51 |
| bristol-v1 | cycling | -0.13 | 0.30 (attractor density) | 0.14 | 0.05 | |
| bristol-v1 | car | 0.63 | 0.63 (class only) | 0.65 | 0.62 | 0.65 |
| bristol-v1 | heavy | 0.68 | 0.68 (attractor density) | 0.66 | 0.67 | 0.67 |
| melbourne-v1 | walking | -0.17 | 0.29 (population density) | -0.28 | -0.16 | |
| melbourne-v1 | car | 0.58 | 0.59 (population density) | 0.59 | 0.59 | 0.59 |
| melbourne-v1 | heavy | 0.49 | 0.49 (population density) | 0.49 | 0.49 | 0.49 |
| leeds-v1 | motor | 0.50 | 0.53 (population density) | 0.52 | 0.48 | 0.51 |

## Contributing

Tools, cases and rule changes are welcome through issues and pull requests.
Changes to cases or scoring rules create a new version, so old results stay
valid.
