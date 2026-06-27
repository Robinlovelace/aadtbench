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
  - [3.2 cityseer Centrality
    Performance](#32-cityseer-centrality-performance)
  - [3.3 madina Centrality
    Performance](#33-madina-centrality-performance)
  - [3.4 sfnetworks Performance](#34-sfnetworks-performance)
  - [3.5 Gravity / Demand Model
    Performance](#35-gravity--demand-model-performance)
  - [3.6 Performance](#36-performance)
- [5. Discussion](#5-discussion)
  - [5.1 Limitations](#51-limitations)
- [6. Conclusion](#6-conclusion)
- [7. Next Steps](#7-next-steps)
- [Appendix](#appendix)
  - [Reproducibility](#reproducibility)
  - [Software Versions](#software-versions)

## Abstract

This study benchmarks tools for pedestrian flow modelling.

xxx

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

![Leuven input datasets: (a) walk network, (b) Telraam sensor locations
with daily pedestrian counts, (c) WorldPop population grid, (d) POI
attractors by category, (e) Telraam road segments, (f) composite
overlay](results/leuven_input_datasets.png)

**Figure 1** visualises all six datasets. The Telraam sensor
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

![Leuven R² comparison across all methods](results/fig1_barplot.png)

### 3.2 cityseer Centrality Performance

| Variant        | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s  | Matched |
|----------------|-------|-----------|----------|----------|--------|---------|
| shortest_3200m | 0.008 | -0.091    | 0.6      | 380      | 31382  | 22      |
| shortest_800m  | 0.004 | -0.064    | 0.1      | 380      | 159299 | 22      |
| shortest_1600m | 0.004 | -0.064    | 0.3      | 380      | 59309  | 22      |
| shortest_200m  | 0.000 | -0.012    | 0.1      | 380      | 169385 | 22      |
| shortest_400m  | 0.000 | -0.008    | 0.1      | 380      | 155816 | 22      |

xxx

### 3.3 madina Centrality Performance

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------|-------|-----------|----------|----------|-------|---------|
| btw_weighted_100 | 0.025 | -0.160    | 1.6      | 420      | 11687 | 22      |
| btw_weighted_500 | 0.018 | -0.133    | 6.7      | 420      | 2870  | 22      |
| btw_weighted_200 | 0.016 | -0.127    | 2.9      | 420      | 6662  | 22      |
| degree           | 0.005 | -0.074    | 1.3      | 400      | 14749 | 22      |

xxx

### 3.4 sfnetworks Performance

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------|-------|-----------|----------|----------|-------|---------|
| edge_betweenness | 0.466 | 0.682     | 5.0      | 450      | 3808  | 22      |

xxx

### 3.5 Gravity / Demand Model Performance

| Variant                      | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------------------|-------|-----------|----------|----------|-------|---------|
| wp_r2000_beta002_all         | 0.676 | 0.822     | 29.5     | 310      | 649   | 22      |
| wp_r1600_beta002_all         | 0.647 | 0.804     | 22.1     | 310      | 863   | 22      |
| wp_r1200_beta002_all         | 0.615 | 0.784     | 16.2     | 310      | 1181  | 22      |
| wp_r1600_beta002_all_pedcost | 0.571 | 0.756     | 36.3     | 310      | 526   | 22      |
| wp_r1200_beta002_all_nodecay | 0.566 | 0.752     | 16.2     | 310      | 1181  | 22      |
| wp_r1200_beta002_all_pedcost | 0.561 | 0.749     | 28.1     | 310      | 681   | 22      |
| wp_r1200_beta001_all         | 0.558 | 0.747     | 16.7     | 310      | 1146  | 22      |
| wp_r1200_beta004_all         | 0.229 | 0.478     | 16.2     | 310      | 1176  | 22      |
| wp_r800_beta002_all          | 0.224 | 0.473     | 11.2     | 310      | 1712  | 22      |
| wp_r1200_beta002_closest     | 0.063 | 0.251     | 12.4     | 310      | 1536  | 22      |

| Variant | R² | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|----|----|----|----|----|----|----|
| cs_demand_r800_beta002_all | 0.543 | 0.737 | 0.1 | 420 | 274944 | 22 |
| cs_demand_r1200_beta001_all | 0.526 | 0.725 | 0.1 | 420 | 283865 | 22 |
| cs_demand_r1200_beta002_all | 0.515 | 0.717 | 0.1 | 420 | 283955 | 22 |
| cs_demand_r1200_beta004_all | 0.468 | 0.684 | 0.1 | 420 | 280081 | 22 |
| cs_demand_r2000_beta001_all | 0.455 | 0.675 | 0.1 | 420 | 219997 | 22 |
| cs_demand_r2000_beta002_all | 0.437 | 0.661 | 0.1 | 420 | 218078 | 22 |
| cs_demand_r1600_beta002_all | 0.420 | 0.648 | 0.1 | 420 | 237138 | 22 |
| cs_demand_r2000_beta004_all | 0.401 | 0.633 | 0.1 | 420 | 219056 | 22 |
| cs_demand_r1200_beta002_closest | 0.050 | -0.224 | 0.1 | 420 | 285622 | 22 |
| cs_demand_r2000_beta002_closest | 0.050 | -0.224 | 0.1 | 420 | 216427 | 22 |

xxx

### 3.6 Performance

![Performance: throughput (left) and memory use
(right)](results/fig2_performance.png)

xxx

## 5. Discussion

xxx

### 5.1 Limitations

1.  **Matching uncertainty**: Sensor-to-network matching introduces
    spatial uncertainty.
2.  **Missing covariates**: No land use, population density, or POI
    data.
3.  **Single study area**: Results may not generalise.

## 6. Conclusion

xxx

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
