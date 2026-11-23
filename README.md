# AADTBench

An open benchmark for street-level multi-modal traffic estimation (walking, cycling, car, and heavy vehicles) across **8 cities on 3 continents** (7 open cases + Leuven non-commercial). Any tool that writes one flow per link can be scored on equal terms.

**[Leaderboard](https://robinlovelace.net/aadtbench/leaderboard.html)** · **[Paper](https://robinlovelace.net/aadtbench/paper/)** · **[Specification](BENCHMARK.md)** · **[Add a tool](IMPLEMENTATIONS.md)** · **[Full CSV](leaderboard-summary.csv)**

## Headline results

<!-- LEADERBOARD:START -->
| Tool | Tier | Car (8) | Heavy (6) | Cycling (7) | Walking (4) | Median wall* | Wh/city* |
| --- | :---: | :---: | :---: | :---: | :---: | ---: | ---: |
| **sDNA** | `T0` | **0.751** | **0.727** | 0.426 | 0.457 | 43 s–13.5 min | 0.46–13.5 |
| **cityseer** | `T2` | 0.717 | 0.670 | 0.525 | 0.464 | 90 s | 0.34 |
| **AequilibraE** | `T2` | 0.714 | 0.652 | 0.515 | 0.444 | 15 s–2.7 min | 0.08–2.0 |
| **UNA** | `T1` | 0.692 | 0.625 | **0.529** | **0.478** | 3.5 min | 0.45 |
| Best baseline | `T1` | 0.633 | 0.626 | 0.346 | 0.585 | <1 s | <0.01 |

_Median spatial group-out Spearman ρ across all cities with ≥ 20 sites (best fixed variant per tool; **bold** = top open tool per mode). Top variants: Car/Heavy = `sDNA mode_hybrid` (log R² = +0.44 / +0.48); Cycling = `UNA default` (0.529) & `cityseer dispersed` (0.525, mean 0.494); Walking = `baseline attractor_density` (0.585), `UNA shortest` (0.478), `cityseer dispersed` (mean 0.498), `sDNA nqpd_euclidean` (log R² = +0.20). *Per-city wall time and TDP-proportional CPU energy across variants (fastest to heaviest)._
<!-- LEADERBOARD:END -->

![AADTBench performance across modes, tools, speed, and CPU energy](assets/hero-benchmark.png)

> Results cover 4 open tools (11 fixed variants) and 4 mandatory baselines on raw OpenStreetMap networks (Leeds, Bristol, London, Paris, Melbourne, Zurich, Toronto, plus Leuven on its own non-commercial board). See the [interactive leaderboard](https://robinlovelace.net/aadtbench/leaderboard.html) or [paper](https://robinlovelace.net/aadtbench/paper/) for per-city scores, leave-one-city-out transfer, and variant ablations.

## Quick start

Every tool runs in its own GHCR container (`ghcr.io/robinlovelace/aadtbench-<tool>:latest`), so only the lightweight harness is needed on the host:

```bash
pip install -r requirements.txt
python -m benchmark.fetch --version v0.1.0 --case bristol-v1
python -m benchmark.run_all --cases bristol-v1 --tools baselines cityseer_od aequilibrae una sdna --docker
```

Smoke-test a single tool on the CI mini case:

```bash
python -m benchmark.smoke --tool aequilibrae --docker
```

Run `scripts/run_board.sh` for the full default suite and `scripts/update_readme_results.py` to refresh the headline table and hero figure above.

## Data, results, and contributing

- **Code & results:** Git holds the harness, adapters, and the complete scored leaderboard ([`leaderboard-summary.csv`](leaderboard-summary.csv), all variants and splits).
- **Case bundles:** Networks (OSM, ODbL-1.0), population (WorldPop CC BY 4.0; ONS Census 2021 Output Areas OGL-UK-3.0 for London), and reviewed open counts live in the [v0.1.0 release](https://github.com/Robinlovelace/aadtbench/releases/tag/v0.1.0), verified by SHA-256 on download. London active travel counts are Powered by TfL Open Data (Contains OS data © Crown copyright and database rights 2026).
- **Contribute:** New tools, cities, and rule proposals are welcome via issues and pull requests — see [`BENCHMARK.md`](BENCHMARK.md) for the rules and [`IMPLEMENTATIONS.md`](IMPLEMENTATIONS.md) for the adapter contract and container images.
