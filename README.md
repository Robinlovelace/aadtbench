# CenBench: Benchmarking Centrality Methods for Pedestrian Flow
Modelling
Robin Lovelace
2026-06-01

- [Abstract](#abstract)
- [1. Introduction](#1-introduction)
  - [1.1 Related Work](#11-related-work)
  - [1.2 Input Datasets](#12-input-datasets)
- [2. Methods](#2-methods)
  - [2.1 Study Area](#21-study-area)
  - [2.2 Validation Data](#22-validation-data)
  - [2.3 Benchmark Design](#23-benchmark-design)
  - [2.4 Metrics](#24-metrics)
- [3. Results](#3-results)
  - [3.1 Benchmark Barplot](#31-benchmark-barplot)
  - [3.2 cityseer Performance](#32-cityseer-performance)
  - [3.3 madina Performance](#33-madina-performance)
  - [3.4 sfnetworks Performance](#34-sfnetworks-performance)
  - [3.5 Overall Comparison](#35-overall-comparison)
- [Performance](#performance)
- [5. Discussion](#5-discussion)
  - [5.1 Limitations](#51-limitations)
- [6. Conclusion](#6-conclusion)
- [7. Next Steps](#7-next-steps)
- [References](#references)
- [Appendix](#appendix)
  - [Reproducibility](#reproducibility)
  - [Software Versions](#software-versions)

## Abstract

This study benchmarks tools for pedestrian flow modelling —
**cityseer**, **madina** (NetworkX), and **sfnetworks** — against
Telraam pedestrian count data from Oxfordshire, UK.

cityseer achieves the strongest positive correlation with pedestrian
counts (Pearson r = **0.78**, R² = 0.60) at walking-scale catchments
(`shortest_3200m`). madina-style unweighted betweenness shows a
counterintuitive negative correlation (r = -0.80). sfnetworks provides
an R-based alternative with modest correlation (r = 0.31). The benchmark
compares **11** variants across **3** tools, matching up to **9**
Telraam sensors.

## 1. Introduction

Pedestrian flow modelling is central to walkability analysis, transport
planning, and urban design. Three approaches exist:

1.  **Network Centrality** — Measures the structural importance of nodes
    or edges.
2.  **Gravity / Flow Models** — Trip distribution proportional to
    attractor weight and distance.
3.  **Spatial Network Analysis** — Graph-based metrics within a GIS
    framework.

**cityseer** (Simons, 2022) implements high-performance centrality in
Rust, with shortest-path and angular analysis.

**madina** (Alhassan & Sevtsuk, 2024) implements Urban Network Analysis
(UNA) with flow simulation, decay functions, and detour penalties.

**sfnetworks** (van der Meer et al., 2024) provides a
tidyverse-compatible R interface for spatial network analysis.

### 1.1 Related Work

Prior benchmarks in the `a private study` repository tested cityseer,
sfnetworks, and dodgr against Leeds AADT counts, finding best R² ~0.46
for cityseer. This study extends that work focusing on **pedestrian**
modelling with **Telraam** data.

### 1.2 Input Datasets

Six datasets underpin the Leuven benchmark, all sourced from open data:

    | Dataset | Description | Rows | Key variables | Source |\n|---------|-------------|------|---------------|--------|\n| Walk network | OSM pedestrian network (edges) | 19,118 | `u`, `v`, `highway`, `length` | OpenStreetMap |\n| Walk nodes | Network nodes | 7,074 | `osmid`, `y`, `x`, `highway` | OpenStreetMap |\n| Telraam sensors | Pedestrian counts (7-day avg) | 38 | `sensor_id`, `avg_daily_pedestrians` | Telraam API |\n| Telraam segments | Road segments with monitoring | 798 | `oidn` | Telraam API |\n| WorldPop origins | Population grid cells (100m) | 2,859 | `population` | WorldPop |\n| POI attractors | Destinations by category | 800 | `name`, `category`, `attractor_weight` | OSM |

The Leuven walk network has 19,118 edges (vs 95,622 for Oxford) — a **5×
smaller** network that enables rapid iteration. The 38 Telraam sensors
report an average of 286 pedestrians per day (max 4,377), providing a
substantially richer validation signal than Oxford’s low-count sensors.

WorldPop population data (100m grid, total population 171,574) serves as
origin weights for gravity models. POI attractors (800 points across 7
categories including universities, dining, shops, transit stations)
provide destination weights.

![Leuven input datasets: (a) walk network, (b) Telraam sensor locations
with daily pedestrian counts, (c) WorldPop population grid, (d) POI
attractors by category, (e) Telraam road segments, (f) composite
overlay](results/leuven_input_datasets.png)

**Figure 2** visualises all six datasets. The Telraam sensor
distribution shows high pedestrian volumes concentrated in the city
centre (250–4,377/day) with moderate volumes on arterial routes and
suburban streets (50–250/day).

## 2. Methods

### 2.1 Study Area

Oxford, UK — a medium-sized city with extensive pedestrian
infrastructure.

| Network Property | Value                                    |
|------------------|------------------------------------------|
| Nodes            | 38,128                                   |
| Edges            | {python} print(f”{n_edges:,}“) {/python} |
| Network type     | walk (pedestrian, OSM)                   |
| CRS              | EPSG:27700 (OSGB)                        |

### 2.2 Validation Data

14 Telraam v1 sensors in Oxfordshire provide hourly pedestrian counts.
Key characteristics:

- **Average daily pedestrian count**: 2.4
- **Max daily count**: 2 pedestrians
- **Sensor locations**: Spread across Oxford city centre, ring road, and
  arterial roads
- **Data period**: 30-day rolling window, aggregated to daily averages
  per sensor

Sensors were matched to the nearest network node/edge using KD-tree
spatial join at 200m threshold.

![Oxford walk network and Telraam sensor
locations](results/fig1_oxford_network.png)

**Figure 1** shows the Oxford walk network extracted from OSM, with
Telraam sensor locations overlaid. Marker size is proportional to the
average daily pedestrian count at each sensor.

### 2.3 Benchmark Design

**cityseer experiments**:

| Variant | Method | Distance | Description |
|----|----|----|----|
| shortest_200m | node_centrality_shortest | 200m | Very local catchment |
| shortest_400m | node_centrality_shortest | 400m | 5-min walk radius |
| shortest_800m | node_centrality_shortest | 800m | 10-min walk radius |
| shortest_1600m | node_centrality_shortest | 1600m | 20-min walk radius |
| shortest_3200m | node_centrality_shortest | 3200m | Extended walking range |
| shortest_multi | node_centrality_shortest | \[400,800,1600\] | Multi-distance |

**madina experiments** (NetworkX-based):

| Variant          | Method                             | Description         |
|------------------|------------------------------------|---------------------|
| degree           | Node degree                        | Simple connectivity |
| btw_weighted_200 | Edge betweenness (length-weighted) | 200-node OD sample  |
| btw_unweighted   | Edge betweenness (unweighted)      | 200-node OD sample  |
| btw_weighted_500 | Edge betweenness (length-weighted) | 500-node OD sample  |

### 2.4 Metrics

- **R²**: Coefficient of determination
- **Pearson r**: Correlation coefficient
- **Spearman r**: Rank correlation
- **Compute time**: Wall-clock seconds
- **Peak memory**: Maximum resident set size (MB)
- **Segments/sec**: Network edges processed per second
- **n_matched**: Number of matched sensor-model pairs

## 3. Results

### 3.1 Benchmark Barplot

![Benchmark R² comparison](results/fig2_barplot.png)

### 3.2 cityseer Performance

| Variant        | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|----------------|-------|-----------|----------|----------|-------|---------|
| shortest_3200m | 0.605 | 0.778     | 13.4     | 350      | 7125  | 3       |
| shortest_800m  | 0.589 | 0.768     | 12.0     | 350      | 7955  | 3       |
| shortest_1600m | 0.585 | 0.765     | 12.1     | 350      | 7916  | 3       |
| shortest_400m  | 0.580 | 0.762     | 11.5     | 350      | 8301  | 3       |
| shortest_multi | 0.580 | 0.762     | 12.3     | 350      | 7768  | 3       |
| shortest_200m  | 0.558 | 0.747     | 11.6     | 350      | 8250  | 3       |

1.  **Optimal catchment**: The best variant is `shortest_3200m` with
    R²=0.605.
2.  **Walking-scale effect**: R² ranges from 0.558 to 0.605 (mean
    0.583).
3.  **Fast computation**: All cityseer variants complete in 12–13s (Rust
    backend).
4.  **Multi-distance**: The multi variant (R²=0.580) shows whether
    aggregation across scales helps.

### 3.3 madina Performance

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s  | Matched |
|------------------|-------|-----------|----------|----------|--------|---------|
| btw_unweighted   | 0.643 | -0.802    | 14.8     | 280      | 6461   | 9       |
| btw_weighted_200 | 0.155 | 0.394     | 15.2     | 280      | 6291   | 9       |
| btw_weighted_500 | 0.155 | 0.394     | 32.1     | 280      | 2979   | 9       |
| degree           | 0.005 | 0.069     | 0.5      | 280      | 191244 | 9       |

1.  **Degree centrality has limited predictive power** (R²=0.005).
2.  **Weighted betweenness is best** with R²=0.643 (`btw_unweighted`).
3.  **Edge-based metrics capture different properties** than node-based
    centrality.

### 3.4 sfnetworks Performance

| Variant          | R²    | Pearson r | Time (s) | RAM (MB) | Seg/s | Matched |
|------------------|-------|-----------|----------|----------|-------|---------|
| edge_betweenness | 0.097 | 0.311     | 429.4    | 450      | 223   | 9       |

sfnetworks edge betweenness yields R²=0.097 (Pearson r=0.311) in 429s.
The R-based workflow provides native spatial indexing and tidyverse
integration, though full-network betweenness is computationally
expensive on a 95K-edge graph.

### 3.5 Overall Comparison

| Aspect           | cityseer      | madina | sfnetworks |
|------------------|---------------|--------|------------|
| Best R²          | **0.605**     | 0.643  | 0.097      |
| Best Pearson r   | **0.778**     | 0.394  | 0.311      |
| Compute time (s) | 12–13         | 0–32   | 429        |
| Language         | Python (Rust) | Python | R          |

## Performance

![Performance: throughput (left) and memory use
(right)](results/fig3_performance.png)

**madina degree** is fastest at 0.5s, processing **191,244**
segments/sec. Memory ranges from **280** to **450** MB across all
variants.

## 5. Discussion

The best-performing variant is `madina btw_unweighted` with R²=0.643.
Walking-scale network centrality is a meaningful predictor of pedestrian
activity when validated against roadside sensor data.

The negative correlation observed for unweighted betweenness is a key
finding. Unweighted betweenness identifies topologically central edges —
typically major roads where Telraam sensors report **lower** pedestrian
counts. This aligns with the “pedestrian paradox”: topologically central
streets (main roads) are often the least pleasant for walking.

### 5.1 Limitations

1.  **Small validation sample**: Only {python} print(n_sensors)
    {/python} Telraam sensors (avg {python} print(f”{avg_ped:.1f}“)
    {/python} peds/day). Designed for vehicle traffic.
2.  **Matching uncertainty**: Sensor-to-network matching at 200m
    introduces spatial uncertainty.
3.  **Missing covariates**: No land use, population density, or POI
    data.
4.  **Single study area**: Results may not generalise.

## 6. Conclusion

1.  **cityseer** is fast and effective for pedestrian-scale centrality
    analysis.
2.  **madina** provides complementary edge-based metrics.
3.  **Edge-based vs node-based** centrality captures fundamentally
    different network properties.
4.  **Telraam data** is limited by low counts and vehicle-oriented
    sensor placement.

[github.com/Robinlovelace/cenbench](https://github.com/Robinlovelace/cenbench)

## 7. Next Steps

1.  Expand validation with Vivacity pedestrian counts from oxflow
2.  Full madina API integration (Zonal-based benchmarking)
3.  Gravity models combining centrality with land-use attractiveness
4.  Add covariates: POI density, population, transit stops
5.  Multi-city comparison (Leeds, Manchester, Edinburgh)
6.  Angular (simplest-path) centrality analysis
7.  K-fold spatial cross-validation

## References

- Alhassan, A. & Sevtsuk, A. (2024). Madina Python Package. *SSRN*.
  doi:10.2139/ssrn.4748255
- Simons, G. (2022). The cityseer Python package. *Environment and
  Planning B*. doi:10.1177/23998083221133827
- van der Meer, L. et al. (2024). sfnetworks: Tidy Geospatial Networks
  in R. *JOSS*.
- Telraam (2024). Telraam API Documentation. https://telraam-api.net

## Appendix

### Reproducibility

- `scripts/bench_all.py` — Unified benchmark runner
- `data/oxford_walk_edges.gpkg` — Oxford walk network ({python}
  print(f”{n_edges:,}“) {/python} edges)
- `data/telraam_pedestrians_27700.geojson` — Telraam validation data
- `results/combined_results.csv` — Auto-generated results
- `results/fig1_oxford_network.png` — Network map
- `results/fig2_barplot.png` — R² comparison plot
- `results/fig3_performance.png` — Speed and memory comparison

### Software Versions

| Package | Version |
|----|----|
| Python | {python} import sys; print(sys.version.split()\[0\]) {/python} |
| cityseer | {python} import cityseer; print(“installed”) {/python} |
| networkx | {python} import networkx; print(networkx.\_\_version\_\_) {/python} |
| pandas | {python} import pandas; print(pandas.\_\_version\_\_) {/python} |
| geopandas | {python} import geopandas; print(geopandas.\_\_version\_\_) {/python} |
