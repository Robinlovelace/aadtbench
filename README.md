# AADTBench

An open benchmark and harness for estimating street-level flows of people and
vehicles. Any tool that writes one flow per link can be scored: centrality and
reach measures, betweenness and spatial interaction, traffic assignment, or
statistical models. The spec is [`BENCHMARK.md`](BENCHMARK.md). How to add a
tool is [`IMPLEMENTATIONS.md`](IMPLEMENTATIONS.md).

Code lives in git. Case data, run outputs and full leaderboards live in the
[v0.3.0 release](https://github.com/Robinlovelace/aadtbench/releases/tag/v0.3.0),
checked by sha256 on download.

## Quick start

```bash
pip install -r requirements.txt cityseer==4.24.1 aequilibrae==1.7.0
python -m benchmark.fetch --version v0.3.0
python -m benchmark.run_all --cases oxford-v1 --tools baselines
python -m benchmark.run_all --cases oxford-v1 --tools cityseer_od aequilibrae --tier T2_synthetic_od
cat results/LEADERBOARD.md
```

`scripts/run_board.sh` runs the default case set and writes
`leaderboard-summary.csv` (best variant per case, mode, track and tool), the
only result kept in git.

## Cases (v0.3.0)

All networks are raw OpenStreetMap (no cleaning), built by
`benchmark/build_osm_network.py`. Release v0.2.0 (cleaned networks) stays
available.

| Case | Modes (sites) | Counts licence | Default set |
|---|---|---|---|
| oxford-v1 | walking 124, cycling 241, car 294, heavy 292 | OGL v3 | yes |
| leeds-v1 | walking 8, cycling 362, car 417, heavy 415 | OGL v3 (DfT, Leeds City Council footfall) | yes |
| melbourne-v1 | walking 100, car 2165, heavy 1948 | CC BY 4.0 | yes |
| zurich-v1 | cycling 23, car 102 (all motor vehicles) | CC0 | yes |
| toronto-v1 | walking 11626, cycling 10778, car 11628, heavy 10724 | OGL Toronto | yes |
| leuven-v1 | walking 38, cycling 37, car 37 | CC BY-NC 4.0 (Telraam), non-commercial | yes, own board |
| bristol-v1 | cycling 200, car 230, heavy 229 | OGL v3 | no |
| oxford-mini-v1 | walking 60, cycling 90, car 96, heavy 96 | OGL v3 | CI only |

leeds-v1 in v0.3.0 is a new definition (DfT plus openly licensed camera data
on a raw OSM network). It replaces the v0.2.0 leeds-v1 (motor only) and
leeds-v2. Networks and POIs: OpenStreetMap (ODbL). Population: WorldPop (CC
BY 4.0). Licences come from the reviewed table in `benchmark/licences.py`.

## Current results

See `leaderboard-summary.csv` (uncalibrated, own-calibration and baseline tracks, spatial
group-out) and the `results__leaderboard.csv` asset of the release.

## Contributing

Tools, cases and rule changes are welcome through issues and pull requests.
Changes to cases or scoring rules create a new version, so old results stay
valid.
