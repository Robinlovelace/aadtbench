# Tools for estimating pedestrian flows on the network
Robin Lovelace
2026-06-01

<!-- ## Abstract
&#10;This study benchmarks five tools for pedestrian flow modelling using Telraam sensor data in Leuven, Belgium. madina_worldpop gravity models achieve the strongest predictive performance (R² up to 0.876), followed by cityseer_demand (R²=0.543) and sDNA+ [@cooper2020sdna] Mean Angular Distance at 800m (R²=0.468). sDNA+ with OpenMP multi-threading completes analyses in seconds rather than minutes (59.8s for 19K edges at 800m vs 979s previously single-threaded). -->

<!-- ## Introduction
&#10;Pedestrian flow modelling is central to walkability analysis, transport planning, and urban design. Three approaches exist: network centrality (betweenness), gravity/flow models (origin-destination allocation with distance decay), and spatial network analysis (graph-based metrics within a GIS framework).
&#10;**cityseer** [@simons2022cityseer] implements high-performance centrality in Rust.
**madina** [@sevtsuk2025madina] implements Urban Network Analysis (UNA) with flow simulation.
**sDNA+** [@cooper2020sdna] provides 3-d spatial network analysis with hybrid and angular metrics.
&#10;-->

> **⚠ Work in progress** — This manuscript is actively evolving.
> Contributions, issues, and forks are welcome at
> [github.com/Robinlovelace/cenbench](https://github.com/Robinlovelace/cenbench).

[![](https://github.com/Robinlovelace/cenbench/actions/workflows/docker-build.yml/badge.svg)](https://github.com/Robinlovelace/cenbench/pkgs/container/cenbench)

[![](https://img.shields.io/badge/Open%20in%20Codespaces-2ea44f?logo=github.png)](https://codespaces.new/Robinlovelace/cenbench)

<details>

<summary>

<strong>Table of Contents</strong>
</summary>

- [Introduction](#introduction)
- [Input Datasets](#input-datasets)
- [Methods](#methods)
  - [Benchmark Design](#benchmark-design)
  - [Metrics](#metrics)
- [Results](#results)
  - [Centrality Methods](#centrality-methods)
  - [Gravity / Demand Models](#gravity--demand-models)
  - [Performance](#performance)
- [Next Steps](#next-steps)
- [Reproducibility](#reproducibility)

</details>

## Introduction

Pedestrian flow modelling is central to walkability analysis, transport
planning, and urban design. Three approaches exist:

1.  **Network Centrality** — Measures the structural importance of nodes
    or edges.
2.  **Gravity / Flow Models** — Trip distribution proportional to
    attractor weight and distance.
3.  **Spatial Network Analysis** — Graph-based metrics within a GIS
    framework.

**cityseer** (Simons 2022) implements high-performance centrality in
Rust, with shortest-path and angular analysis.

**madina** (Sevtsuk and Alhassan 2025) implements Urban Network Analysis
(UNA) with flow simulation, decay functions, and detour penalties.

**sDNA+** (Cooper and Chiaradia 2020) provides 3-d spatial network
analysis via a C++ library with Python, QGIS, and command-line
interfaces, supporting hybrid and angular metrics with OpenMP
multi-threading.

<!-- TODO: populate this section -->

<!-- ### Related Work
&#10;This study benchmarks network centrality and gravity-based pedestrian flow models using Telraam validation data from Leuven, Belgium. -->

### Input Datasets

Six datasets underpin the Leuven benchmark, all sourced from open data:

<div id="tbl-datasets">

Table 1: Leuven input datasets sourced from open data.

| Dataset | Description | Rows | Key variables | Source |
|----|----|----|----|----|
| Walk network | OSM pedestrian network (edges) | 19,118 | `u`, `v`, `highway`, `length` | OpenStreetMap |
| Walk nodes | Network nodes | 7,074 | `osmid`, `y`, `x`, `highway` | OpenStreetMap |
| Telraam sensors | Pedestrian counts (7-day avg) | 38 | `sensor_id`, `avg_daily_pedestrians` | Telraam API |
| Telraam segments | Road segments with monitoring | 798 | `oidn` | Telraam API |
| WorldPop origins | Population grid cells (100m) | 2,859 | `population` | WorldPop |
| POI attractors | Destinations by category | 801 | `name`, `category`, `attractor_weight` | OSM |

</div>

The Leuven walk network has 19,118 edges. The 38 Telraam sensors report
an average of 286 pedestrians per day (max 4,377), providing a
substantial validation signal.

WorldPop population data (100m grid, total population 171,574) serves as
origin weights for gravity models. POI attractors (800 points across 7
categories including universities, dining, shops, transit stations)
provide destination weights.

<div id="fig-input-datasets">

![](results/leuven_input_datasets.png)

Figure 1: Leuven input datasets: (a) walk network & monitored road
segments, (b) Telraam sensor locations with daily average pedestrian
counts, (c) WorldPop population grid (origins), (d) POI attractors by
category (destinations)

</div>

<a href="#fig-input-datasets" class="quarto-xref">Figure 1</a>
visualises these input datasets. The Telraam sensor distribution shows
high pedestrian volumes concentrated in the city centre (250–4,377/day)
with moderate volumes on arterial routes and suburban streets
(50–250/day).

## Methods

### Benchmark Design

**cityseer experiments**:

<div id="tbl-cityseer-design">

Table 2: Cityseer benchmark design configurations.

| Variant        | Method                   | Distance | Description            |
|----------------|--------------------------|----------|------------------------|
| shortest_200m  | node_centrality_shortest | 200m     | Very local catchment   |
| shortest_400m  | node_centrality_shortest | 400m     | 5-min walk radius      |
| shortest_800m  | node_centrality_shortest | 800m     | 10-min walk radius     |
| shortest_1600m | node_centrality_shortest | 1600m    | 20-min walk radius     |
| shortest_3200m | node_centrality_shortest | 3200m    | Extended walking range |

</div>

**madina experiments** (NetworkX-based):

<div id="tbl-madina-design">

Table 3: Madina centrality benchmark design configurations.

| Variant          | Method                             | Description         |
|------------------|------------------------------------|---------------------|
| degree           | Node degree                        | Simple connectivity |
| btw_weighted_100 | Edge betweenness (length-weighted) | 100-node OD sample  |
| btw_weighted_200 | Edge betweenness (length-weighted) | 200-node OD sample  |
| btw_weighted_500 | Edge betweenness (length-weighted) | 500-node OD sample  |

</div>

**Gravity / demand models**:

<div id="tbl-gravity-design">

Table 4: Gravity/demand model configurations.

| Variant | Tool | Configuration |
|----|----|----|
| wp_r800_beta002_all | madina_worldpop | 800m radius, β=0.002, all attractors |
| wp_r1200_beta002_all | madina_worldpop | 1200m radius, β=0.002, all attractors |
| wp_r1600_beta002_all | madina_worldpop | 1600m radius, β=0.002, all attractors |
| wp_r2000_beta002_all | madina_worldpop | 2000m radius, β=0.002, all attractors |
| cs_demand_r800_beta002_all | cityseer_demand | 800m radius, β=0.02, all attractors |
| cs_demand_r1200_beta002_all | cityseer_demand | 1200m radius, β=0.02, all attractors |

</div>

### Metrics

- **R²**: Coefficient of determination
- **Pearson r**: Correlation coefficient
- **Spearman r**: Rank correlation
- **Compute time**: Wall-clock seconds
- **Peak memory**: Maximum resident set size (MB)
- **Segments/sec**: Network edges processed per second
- **n_matched**: Number of matched sensor-model pairs

## Results

### Centrality Methods

Centrality methods measure the structural importance of each network
edge (or node) based purely on network geometry — how many shortest
paths pass through it (betweenness) or how quickly it can reach nearby
edges (closeness). They do not incorporate trip origins, destinations,
or land-use data. Results in this section use shortest-path or angular
routing with no origin/destination weighting.

<div id="fig-barplot-centrality">

![](results/fig1_barplot.png)

Figure 2: Leuven R² comparison across pure centrality methods (cityseer,
madina, sDNA+)

</div>

#### cityseer

<div id="tbl-cityseer-results">

Table 5: Cityseer centrality results.

| Variant        | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s  | Matched |
|----------------|-------|-----------|----------|----------|--------|---------|
| shortest_3200m | 0.008 | -0.091    | 0.7      | 483      | 29428  | 22      |
| shortest_800m  | 0.004 | -0.064    | 0.1      | 439      | 233663 | 22      |
| shortest_200m  | 0.000 | -0.012    | 0.0      | 436      | 675752 | 22      |

</div>

#### madina

<div id="tbl-madina-results">

Table 6: Madina centrality results.

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------|-------|-----------|----------|----------|-------|---------|
| degree           | 0.145 | -0.381    | 0.7      | 489      | 26592 | 22      |
| btw_weighted_200 | 0.002 | -0.041    | 2.9      | 489      | 6645  | 22      |

</div>

#### sDNA+

<div id="tbl-sdna-results">

Table 7: sDNA+ centrality results.

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------|-------|-----------|----------|----------|-------|---------|
| MAD_angular_800m | 0.468 | 0.684     | 64.6     | 400      | 296   | 22      |
| MAD_angular_400m | 0.353 | 0.594     | 10.8     | 400      | 1779  | 22      |

</div>

### Gravity / Demand Models

Gravity models estimate pedestrian flow by simulating trips from
population-weighted origins (WorldPop cells) to attractor destinations
(OSM points of interest) using a distance-decay function: flow =
attractor_weight × exp(-β × distance). Unlike centrality methods, they
incorporate real land-use data and trip distribution, making them
behavioural rather than purely structural.

<div id="fig-barplot-gravity">

![](results/fig_gravity_barplot.png)

Figure 3: Gravity and demand model R² comparison

</div>

<a href="#fig-barplot-gravity" class="quarto-xref">Figure 3</a> compares
gravity-based pedestrian flow models incorporating WorldPop population
origins and OSM POI attractor destinations with exponential distance
decay.

<div id="tbl-gravity-madina-results">

Table 8: Madina WorldPop gravity results.

| Variant              | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|----------------------|-------|-----------|----------|----------|-------|---------|
| wp_r3000_beta002_all | 0.876 | 0.936     | 57.3     | 344      | 165   | 22      |
| wp_r2000_beta002_all | 0.868 | 0.932     | 33.2     | 344      | 285   | 22      |
| wp_r1600_beta002_all | 0.862 | 0.928     | 25.0     | 344      | 378   | 22      |
| wp_r1200_beta002_all | 0.851 | 0.923     | 17.2     | 343      | 550   | 22      |

</div>

<div id="tbl-gravity-cityseer-results">

Table 9: Cityseer Demand gravity results.

| Variant                     | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|-----------------------------|-------|-----------|----------|----------|-------|---------|
| cs_demand_r2000_beta002_all | 0.632 | 0.795     | 2.5      | 420      | 7758  | 22      |
| cs_demand_r1200_beta002_all | 0.573 | 0.757     | 2.1      | 420      | 8895  | 22      |
| cs_demand_r800_beta002_all  | 0.426 | 0.653     | 2.0      | 420      | 9448  | 22      |

</div>

### Performance

<div id="tbl-performance-summary">

Table 10: Runtime summary per tool: min, median, and max wall-clock
seconds across all variants.

min 0.0 median 0.1 max 0.6 Name: cityseer, dtype: float64 min 2.0 median
2.1 max 2.5 Name: cityseer_demand, dtype: float64 min 0.7 median 1.8 max
2.9 Name: madina, dtype: float64 min 17.2 median 29.1 max 57.3 Name:
madina_worldpop, dtype: float64 min 10.8 median 37.7 max 64.6 Name:
sdna, dtype: float64 \| tool \| min \| median \| max \|
\|:—————-\|——:\|———:\|——:\| \| cityseer \| 0 \| 0.1 \| 0.6 \| \|
cityseer_demand \| 2 \| 2.1 \| 2.5 \| \| madina \| 0.7 \| 1.8 \| 2.9 \|
\| madina_worldpop \| 17.2 \| 29.1 \| 57.3 \| \| sdna \| 10.8 \| 37.7 \|
64.6 \|

</div>

<div id="fig-performance">

![](results/fig3_performance.png)

Figure 4: Computational performance: throughput and memory usage

</div>

## Next Steps

1.  Multi-city comparison (Leeds, Manchester, Edinburgh)
2.  K-fold spatial cross-validation
3.  Additional goodness-of-fit metrics and centrality measures
4.  Test adding covariates: e.g. POI density, population, transit stops

## Reproducibility

<details>

<summary>

Reproducibility: DVC pipeline, setup, and version details
</summary>

### How to Run and Update Benchmarks

The benchmark suite is fully orchestrated using
**[DVC](https://dvc.org/doc/command-reference/repro)** (Data Version
Control) to manage dependencies, execution caching, and outputs.

#### 1. Setup the Environment

``` bash
pip install -r requirements.txt
```

#### 2. Run the Pipeline

``` bash
dvc repro
```

#### 3. Rapid Testing Mode

1.  Open `scripts/config.py`.
2.  Toggle `TEST_MODE = True`.
3.  Run `dvc repro`.
4.  Flip `TEST_MODE = False` before committing.

#### 4. Add/Modify Experiments

- **sDNA+**: Edit `scripts/bench_sdna.py`.
- **Madina gravity**: Edit `scripts/run_madina_demand_experiments.py`.
- **Cityseer demand**: Edit
  `scripts/run_cityseer_demand_experiments.py`.
- **Centrality**: Edit `scripts/bench_centrality.py`.

### Project Structure & Reproducibility

- `dvc.yaml` — Stage orchestration and dependencies
- `dvc.lock` — Pipeline state and hash locks
- `scripts/` — All benchmark and analysis scripts (13 files)
- `config/cities.yaml` — City parameters
- `results/leuven_results.csv` — Compiled metrics output

| Package   | Version   |
|-----------|-----------|
| Python    | 3.13.11   |
| cityseer  | installed |
| networkx  | 3.6.1     |
| pandas    | 3.0.4     |
| geopandas | 1.1.4     |
| madina    | installed |
| sDNA+     | \(CLI\)   |

</details>

## References

<div id="refs" class="references csl-bib-body hanging-indent"
entry-spacing="0">

<div id="ref-cooper2020sdna" class="csl-entry">

Cooper, Crispin H. V., and Alain J. F. Chiaradia. 2020. “sDNA: 3-d
Spatial Network Analysis for GIS, CAD, Command Line & Python.”
*SoftwareX* 12 (July): 100525.
<https://doi.org/10.1016/j.softx.2020.100525>.

</div>

<div id="ref-sevtsuk2025madina" class="csl-entry">

Sevtsuk, Andres, and Abdulaziz Alhassan. 2025. “Madina Python Package:
Scalable Urban Network Analysis for Modeling Pedestrian and Bicycle
Trips in Cities.” *Journal of Transport Geography* 123 (February):
104130. <https://doi.org/10.1016/j.jtrangeo.2025.104130>.

</div>

<div id="ref-simons2022cityseer" class="csl-entry">

Simons, Gareth. 2022. “The Cityseer Python Package for Pedestrian-Scale
Network-Based Urban Analysis.” *Environment and Planning B: Urban
Analytics and City Science* 50 (5): 1328–44.
<https://doi.org/10.1177/23998083221133827>.

</div>

</div>
