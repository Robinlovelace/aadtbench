# Tools for estimating pedestrian flows on the network
Robin Lovelace
2026-06-01

- [<span class="toc-section-number">1</span> Abstract](#abstract)
- [<span class="toc-section-number">2</span>
  Introduction](#introduction)
  - [<span class="toc-section-number">2.1</span> 1.1 Related
    Work](#11-related-work)
  - [<span class="toc-section-number">2.2</span> Input
    Datasets](#input-datasets)
- [<span class="toc-section-number">3</span> Methods](#methods)
  - [<span class="toc-section-number">3.1</span> Benchmark
    Design](#benchmark-design)
  - [<span class="toc-section-number">3.2</span> Metrics](#metrics)
- [<span class="toc-section-number">4</span> Results](#results)
  - [<span class="toc-section-number">4.1</span> Centrality
    Methods](#centrality-methods)
  - [<span class="toc-section-number">4.2</span> Gravity / Demand
    Models](#gravity--demand-models)
  - [<span class="toc-section-number">4.3</span>
    Performance](#performance)
- [<span class="toc-section-number">5</span> Next Steps](#next-steps)
- [Appendix](#appendix)
  - [<span class="toc-section-number">5.1</span> How to Run and Update
    Benchmarks](#how-to-run-and-update-benchmarks)
  - [<span class="toc-section-number">5.2</span> Project Structure &
    Reproducibility](#project-structure--reproducibility)

## Abstract

This study benchmarks five tools for pedestrian flow modelling using
Telraam sensor data in Leuven, Belgium. madina_worldpop gravity models
achieve the strongest predictive performance (R² up to 0.876), followed
by cityseer_demand (R²=0.543) and sDNA+ (Cooper and Chiaradia 2020) Mean
Angular Distance at 800m (R²=0.468). sDNA+ with OpenMP multi-threading
completes analyses in seconds rather than minutes (59.8s for 19K edges
at 800m vs 979s previously single-threaded).

> **⚠ Work in progress** — This manuscript is actively evolving.
> Contributions, issues, and forks are welcome at
> [github.com/Robinlovelace/cenbench](https://github.com/Robinlovelace/cenbench).

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

**sfnetworks** (van der Meer et al. 2024) provides a
tidyverse-compatible R interface for spatial network analysis.

### 1.1 Related Work

This study benchmarks network centrality and gravity-based pedestrian
flow models using Telraam validation data from Leuven, Belgium.

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
| shortest_3200m | 0.008 | -0.091    | 1.2      | 483      | 16400  | 22      |
| shortest_800m  | 0.004 | -0.064    | 0.1      | 438      | 157678 | 22      |
| shortest_200m  | 0.000 | -0.012    | 0.0      | 436      | 534414 | 22      |

</div>

#### madina

<div id="tbl-madina-results">

Table 6: Madina centrality results.

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------|-------|-----------|----------|----------|-------|---------|
| degree           | 0.145 | -0.381    | 1.0      | 489      | 19671 | 22      |
| btw_weighted_200 | 0.002 | -0.041    | 6.3      | 489      | 3048  | 22      |

</div>

#### sDNA+

<div id="tbl-sdna-results">

Table 7: sDNA+ centrality results.

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------|-------|-----------|----------|----------|-------|---------|
| MAD_angular_800m | 0.468 | 0.684     | 62.5     | 400      | 306   | 22      |
| MAD_angular_400m | 0.353 | 0.594     | 12.8     | 400      | 1498  | 22      |

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
| wp_r2000_beta002_all | 0.868 | 0.932     | 65.3     | 339      | 145   | 22      |
| wp_r1600_beta002_all | 0.862 | 0.928     | 33.6     | 339      | 281   | 22      |
| wp_r1200_beta002_all | 0.851 | 0.923     | 30.5     | 339      | 310   | 22      |
| wp_r3000_beta002_all | nan   | nan       | 75.0     | —        | —     | 38      |

</div>

<div id="tbl-gravity-cityseer-results">

Table 9: Cityseer Demand gravity results.

| Variant                     | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s  | Matched |
|-----------------------------|-------|-----------|----------|----------|--------|---------|
| cs_demand_r800_beta002_all  | 0.543 | 0.737     | 0.1      | 420      | 169345 | 22      |
| cs_demand_r1200_beta002_all | 0.515 | 0.718     | 0.2      | 420      | 107309 | 22      |
| cs_demand_r2000_beta002_all | 0.437 | 0.661     | 0.2      | 420      | 83872  | 22      |

</div>

### Performance

<div id="tbl-performance-summary">

Table 10: Runtime summary per tool: min, median, and max wall-clock
seconds across all variants.

min 0.0 median 0.1 max 1.2 Name: cityseer, dtype: float64 min 0.1 median
0.2 max 0.2 Name: cityseer_demand, dtype: float64 min 1.0 median 3.6 max
6.3 Name: madina, dtype: float64 min 30.5 median 49.5 max 75.0 Name:
madina_worldpop, dtype: float64 min 12.8 median 37.6 max 62.5 Name:
sdna, dtype: float64 \| tool \| min \| median \| max \|
\|:—————-\|——:\|———:\|——:\| \| cityseer \| 0 \| 0.1 \| 1.2 \| \|
cityseer_demand \| 0.1 \| 0.2 \| 0.2 \| \| madina \| 1 \| 3.6 \| 6.3 \|
\| madina_worldpop \| 30.5 \| 49.5 \| 75 \| \| sdna \| 12.8 \| 37.6 \|
62.5 \|

</div>

<div id="fig-performance">

![](results/fig3_performance.png)

Figure 4: Computational performance: throughput and memory usage

</div>

## Next Steps

1.  Expand validation with Vivacity pedestrian counts from oxflow
2.  Multi-city comparison (Leeds, Manchester, Edinburgh)
3.  K-fold spatial cross-validation
4.  Angular (simplest-path) analysis with cityseer `segment_centrality`
5.  Add covariates: POI density, population, transit stops

## Appendix

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
- **Madina gravity**: Edit `scripts/run_demand_experiments.py`.
- **Cityseer demand**: Edit
  `scripts/run_cityseer_demand_experiments.py`.
- **Centrality**: Edit `scripts/bench_city.py`.

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

<div id="ref-vandermeer2024sfnetworks" class="csl-entry">

van der Meer, Lucas, Lorena Abad, Andrea Gilardi, and Robin Lovelace.
2024. “Sfnetworks: Tidy Geospatial Networks.”
<https://doi.org/10.32614/CRAN.package.sfnetworks>.

</div>

</div>
