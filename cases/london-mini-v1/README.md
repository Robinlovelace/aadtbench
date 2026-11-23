# london-mini-v1 (case version 1.0.0, benchmark v0.1.0)

West London (Hammersmith & Fulham) mini case for CI smoke tests. Centre -0.215, 51.49, radius 2000 m (1000 m margin), EPSG:27700.
Data files are assets of release v0.1.0 (`python -m benchmark.fetch --version v0.1.0 --case london-mini-v1`).

## Network

Raw OpenStreetMap (ODbL), clipped from `london-v1/source.osm.pbf` by `benchmark/build_osm_network.py`.
31001 links, 991.4 km, 85 components (largest holds
99.1 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| walking | 34 | 34 | 0 |
| cycling | 80 | 80 | 11 |
| car | 47 | 47 | 9 |
| heavy | 47 | 47 | 9 |

Sources (licences from `benchmark/licences.py`):

- `dft_manual`: OGL-UK-3.0 (https://roadtraffic.dft.gov.uk/downloads)
- `tfl`: OGL-UK-2.0 (https://cycling.data.tfl.gov.uk)

Inputs: WorldPop (CC BY 4.0), OSM POIs (ODbL), zones (500 m), synthetic OD.
