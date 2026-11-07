# AADTBench

An open benchmark and harness for estimating street-level flows of people and
vehicles. Any tool that writes one flow per link can be scored: centrality and
reach measures, betweenness and spatial interaction, traffic assignment, or
statistical models. See [`BENCHMARK.md`](BENCHMARK.md) for the specification
and [`IMPLEMENTATIONS.md`](IMPLEMENTATIONS.md) for how to add a tool.

Code lives in git. Case data, run outputs and full leaderboards live in the
[v0.1.0 release](https://github.com/Robinlovelace/aadtbench/releases/tag/v0.1.0),
checked by sha256 on download.

## Quick start

```bash
pip install -r requirements.txt cityseer==5.8.0 aequilibrae==1.7.2 sdna-plus==5.2.0 "git+https://github.com/City-Form-Lab/urban_network_analysis.git@d270792"
python -m benchmark.fetch --version v0.1.0
python -m benchmark.run_all --cases oxford-v1 --tools baselines
python -m benchmark.run_all --cases oxford-v1 --tools cityseer_od aequilibrae --tier T2_synthetic_od
cat results/LEADERBOARD.md
```

`scripts/run_board.sh` runs the default case set from `config/benchmark.yaml` and writes
`leaderboard-summary.csv` (best variant per case, mode and tool), the only
result file kept in git.

## Cases (v0.1.0)

All networks are raw OpenStreetMap (no cleaning), built by
`benchmark/build_osm_network.py`.

| Case | Modes (sites) | Counts licence | Default set |
|---|---|---|---|
| oxford-v1 | walking 124, cycling 241, car 294, heavy 292 | OGL v3 | yes |
| leeds-v1 | walking 8, cycling 362, car 417, heavy 415 | OGL v3 (DfT, Leeds City Council footfall) | yes |
| bristol-v1 | cycling 200, car 230, heavy 229 | OGL v3 | yes |
| london-v1 | walking 1147, cycling 2875, car 1765, heavy 1762 | OGL v3 / OGL v2 (DfT, TfL Active Travel Counts) | yes |
| melbourne-v1 | walking 100, car 2165, heavy 1948 | CC BY 4.0 | yes |
| zurich-v1 | cycling 23, car 102 (all motor vehicles) | CC0 | yes |
| toronto-v1 | walking 11626, cycling 10778, car 11628, heavy 10724 | OGL Toronto | yes |
| leuven-v1 | walking 38, cycling 37, car 37 | CC BY-NC 4.0 (Telraam), non-commercial | yes, own board |
| oxford-mini-v1 | walking 60, cycling 90, car 96, heavy 96 | OGL v3 | CI only |

Networks and POIs: OpenStreetMap (ODbL). Population: WorldPop (CC BY 4.0).
Licences come from the reviewed table in `benchmark/licences.py`.

## Current results

- [Leaderboard summary (CSV)](leaderboard-summary.csv), kept in git
- [Full leaderboard (CSV)](https://github.com/Robinlovelace/aadtbench/releases/download/v0.1.0/results__leaderboard.csv), a release asset
- [Release v0.1.0 and all assets](https://github.com/Robinlovelace/aadtbench/releases/tag/v0.1.0)
- [Manifest (`manifest-v0.1.0.json`)](https://github.com/Robinlovelace/aadtbench/releases/download/v0.1.0/manifest-v0.1.0.json), with sha256 checksums

## Contributing

Tools, cases and rule changes are welcome through issues and pull requests.
Changes to cases or scoring rules create a new version, so old results stay
valid.
