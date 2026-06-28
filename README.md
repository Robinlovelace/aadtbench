# Tools for estimating pedestrian flows on the network
Robin Lovelace
2026-06-01

- [Abstract](#abstract)
- [1. Introduction](#1-introduction)
  - [1.1 Related Work](#11-related-work)
  - [1.2 Input Datasets](#12-input-datasets)
- [2. Methods](#2-methods)
  - [2.1 Benchmark Design](#21-benchmark-design)
  - [2.2 Metrics](#22-metrics)
- [3. Results](#3-results)
  - [3.1 Benchmark Barplot](#31-benchmark-barplot)
  - [3.2 Centrality Methods](#32-centrality-methods)
  - [3.3 Gravity / Demand Models](#33-gravity--demand-models)
  - [3.4 Performance](#34-performance)
- [5. Discussion](#5-discussion)
  - [5.1 Limitations](#51-limitations)
- [6. Conclusion](#6-conclusion)
- [7. Next Steps](#7-next-steps)
- [Appendix](#appendix)
  - [Reproducibility](#reproducibility)
  - [Software Versions](#software-versions)

`{r targets-dependencies, include = FALSE} #| eval: false #| echo: false library(targets) tar_load(leuven_results) tar_load(leuven_input_figure)`

## Abstract

This study benchmarks seven tools for pedestrian flow modelling using
Telraam sensor data in Leuven, Belgium. madina_worldpop gravity models
achieve the strongest predictive performance (R² up to 0.676), followed
by cityseer_demand (R²=0.543) and sDNA+ Mean Angular Distance at 800m
(R²=0.468). sDNA+ with OpenMP multi-threading completes analyses in
seconds rather than minutes (59.8s for 19K edges at 800m vs 979s
previously single-threaded).

## 1. Introduction

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

Prior benchmarks in the `a private study` repository tested cityseer,
sfnetworks, and dodgr against Leeds AADT counts, finding best R² ~0.46
for cityseer. This study extends that work focusing on **pedestrian**
modelling with **Telraam** data.

### 1.2 Input Datasets

Six datasets underpin the Leuven benchmark, all sourced from open data:

    | Dataset | Description | Rows | Key variables | Source |\n|---------|-------------|------|---------------|--------|\n| Walk network | OSM pedestrian network (edges) | 19,118 | `u`, `v`, `highway`, `length` | OpenStreetMap |\n| Walk nodes | Network nodes | 7,074 | `osmid`, `y`, `x`, `highway` | OpenStreetMap |\n| Telraam sensors | Pedestrian counts (7-day avg) | 38 | `sensor_id`, `avg_daily_pedestrians` | Telraam API |\n| Telraam segments | Road segments with monitoring | 798 | `oidn` | Telraam API |\n| WorldPop origins | Population grid cells (100m) | 2,859 | `population` | WorldPop |\n| POI attractors | Destinations by category | 801 | `name`, `category`, `attractor_weight` | OSM |

The Leuven walk network has 19,118 edges. The 38 Telraam sensors report
an average of 286 pedestrians per day (max 4,377), providing a
substantial validation signal.

WorldPop population data (100m grid, total population 171,574) serves as
origin weights for gravity models. POI attractors (800 points across 7
categories including universities, dining, shops, transit stations)
provide destination weights.

![Leuven input datasets: (a) walk network & monitored road segments, (b)
Telraam sensor locations with daily average pedestrian counts, (c)
WorldPop population grid (origins), (d) POI attractors by category
(destinations)](results/leuven_input_datasets.png)

**Figure 2** visualises these input datasets. The Telraam sensor
distribution shows high pedestrian volumes concentrated in the city
centre (250–4,377/day) with moderate volumes on arterial routes and
suburban streets (50–250/day).

## 2. Methods

### 2.1 Benchmark Design

**cityseer experiments**:

| Variant        | Method                   | Distance | Description            |
|----------------|--------------------------|----------|------------------------|
| shortest_200m  | node_centrality_shortest | 200m     | Very local catchment   |
| shortest_400m  | node_centrality_shortest | 400m     | 5-min walk radius      |
| shortest_800m  | node_centrality_shortest | 800m     | 10-min walk radius     |
| shortest_1600m | node_centrality_shortest | 1600m    | 20-min walk radius     |
| shortest_3200m | node_centrality_shortest | 3200m    | Extended walking range |

**madina experiments** (NetworkX-based):

| Variant          | Method                             | Description         |
|------------------|------------------------------------|---------------------|
| degree           | Node degree                        | Simple connectivity |
| btw_weighted_100 | Edge betweenness (length-weighted) | 100-node OD sample  |
| btw_weighted_200 | Edge betweenness (length-weighted) | 200-node OD sample  |
| btw_weighted_500 | Edge betweenness (length-weighted) | 500-node OD sample  |

**Gravity / demand models**:

| Variant | Tool | Configuration |
|----|----|----|
| wp_r800_beta002_all | madina_worldpop | 800m radius, β=0.02, all attractors |
| wp_r1200_beta002_all | madina_worldpop | 1200m radius, β=0.02, all attractors |
| wp_r1600_beta002_all | madina_worldpop | 1600m radius, β=0.02, all attractors |
| wp_r2000_beta002_all | madina_worldpop | 2000m radius, β=0.02, all attractors |
| cs_demand_r800_beta002_all | cityseer_demand | 800m radius, β=0.02, all attractors |
| cs_demand_r1200_beta002_all | cityseer_demand | 1200m radius, β=0.02, all attractors |

### 2.2 Metrics

- **R²**: Coefficient of determination
- **Pearson r**: Correlation coefficient
- **Spearman r**: Rank correlation
- **Compute time**: Wall-clock seconds
- **Peak memory**: Maximum resident set size (MB)
- **Segments/sec**: Network edges processed per second
- **n_matched**: Number of matched sensor-model pairs

## 3. Results

### 3.1 Benchmark Barplot

![Leuven R² comparison across all methods — centrality measures (left)
and gravity/demand models (right)](results/fig1_barplot.png)

### 3.2 Centrality Methods

#### 3.2.1 cityseer

| Variant        | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s  | Matched |
|----------------|-------|-----------|----------|----------|--------|---------|
| shortest_3200m | 0.008 | -0.091    | 1.0      | 418      | 18450  | 22      |
| shortest_800m  | 0.004 | -0.064    | 0.1      | 374      | 246766 | 22      |
| shortest_200m  | 0.000 | -0.012    | 0.0      | 371      | 670043 | 22      |

#### 3.2.2 madina

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------|-------|-----------|----------|----------|-------|---------|
| degree           | 0.145 | -0.381    | 0.7      | 428      | 26307 | 22      |
| btw_weighted_200 | 0.002 | -0.041    | 2.9      | 425      | 6595  | 22      |

#### 3.2.3 sDNA+

### 3.3 Gravity / Demand Models

![Gravity and demand model R²
comparison](results/fig_gravity_barplot.png)

**Figure X** compares gravity-based pedestrian flow models incorporating
WorldPop population origins and OSM POI attractor destinations with
exponential distance decay.

| Variant | R²  | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|---------|-----|-----------|----------|----------|-------|---------|

| Variant                     | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s  | Matched |
|-----------------------------|-------|-----------|----------|----------|--------|---------|
| cs_demand_r800_beta002_all  | 0.543 | 0.737     | 0.1      | 420      | 286749 | 22      |
| cs_demand_r1200_beta002_all | 0.515 | 0.718     | 0.1      | 420      | 285895 | 22      |
| cs_demand_r2000_beta002_all | 0.437 | 0.661     | 0.1      | 420      | 197175 | 22      |

### 3.4 Performance

![Performance: throughput (left) and memory use
(right)](results/fig3_performance.png)

## 5. Discussion

Three clear tiers emerge from the benchmarks:

1.  **Gravity/demand models** (R² 0.47–0.68): `madina_worldpop` with
    population-weighted origins and cost-decayed destination attraction
    achieves the top result (R²=0.676 at 2000m, β=0.002).
    `cityseer_demand` at 800m (R²=0.543) performs best at shorter
    ranges.
2.  **Spatial network measures** (R² 0.15–0.47): `sDNA+` Mean Angular
    Distance at 800m (R²=0.468) is the top purely structural network
    topology measure. At smaller radii, `sDNA+` MAD also captures a
    moderate signal (R²=0.264 at 200m, 0.353 at 400m). `madina` degree
    centrality explains a smaller fraction of variance (R²=0.145).
3.  **Raw betweenness centrality** (R² \< 0.02): `cityseer` shortest
    path betweenness, without attractor weights, shows negligible
    correlation with observed pedestrian counts.

Other tools (`sfnetworks` and `aperta`) were also evaluated and are
documented in [Appendix: Other Centrality & Flow Modelling
Tools](appendix-other-tools.md).

### 5.1 Limitations

1.  **Matching uncertainty**: Sensor-to-network matching introduces
    spatial uncertainty.
2.  **Missing covariates**: No land use, population density, or POI
    data.
3.  **Single study area**: Results may not generalise.

## 6. Conclusion

Gravity-based demand models (`madina_worldpop`, `cityseer_demand`)
outperform pure network centrality by over an order of magnitude for
pedestrian flow estimation. The top result (R²=0.676) comes from
`madina_worldpop` with population-weighted origins and distance-decayed
destination attraction. Among purely structural measures, `sDNA+` Mean
Angular Distance (R²=0.468 at 800m) provides the most informative
topological signal. The benchmark demonstrates that land-use attractor
weights and population origins are essential for meaningful pedestrian
flow prediction, and that raw network centrality alone is insufficient.

Future work should expand validation to larger, multi-city datasets and
explore hybrid models combining centrality with land-use covariates.

[github.com/Robinlovelace/cenbench](https://github.com/Robinlovelace/cenbench)

## 7. Next Steps

1.  Expand validation with Vivacity pedestrian counts from oxflow
2.  Full madina API integration (Zonal-based benchmarking)
3.  Gravity models combining centrality with land-use attractiveness
4.  Add covariates: POI density, population, transit stops
5.  Multi-city comparison (Leeds, Manchester, Edinburgh)
6.  Angular (simplest-path) centrality analysis
7.  K-fold spatial cross-validation

## Appendix

### Reproducibility

- `scripts/bench_all.py` — Unified benchmark runner
- `results/leuven_results.csv` — Auto-generated results
- `results/fig1_barplot.png` — R² comparison plot
- `results/fig2_performance.png` — Speed and memory comparison

### Software Versions

| Package | Version |
|----|----|
| Python | {python} import sys; print(sys.version.split()\[0\]) {/python} |
| cityseer | {python} import cityseer; print(“installed”) {/python} |
| networkx | {python} import networkx; print(networkx.\_\_version\_\_) {/python} |
| pandas | {python} import pandas; print(pandas.\_\_version\_\_) {/python} |
| geopandas | {python} import geopandas; print(geopandas.\_\_version\_\_) {/python} |

<div id="refs" class="references csl-bib-body hanging-indent"
entry-spacing="0">

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
