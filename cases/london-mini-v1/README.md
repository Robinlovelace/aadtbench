# london-mini-v1 (case version 1.0.0, benchmark v0.1.0)

West London (Hammersmith & Fulham) mini case for CI smoke tests. Centre -0.215, 51.49, radius 2000 m (1000 m margin), EPSG:27700.
Data files are assets of release v0.1.0 (`python -m benchmark.fetch --version v0.1.0 --case london-mini-v1`).

## Network

Raw OpenStreetMap (ODbL-1.0), clipped from `london-v1/source.osm.pbf` by `benchmark/build_osm_network.py`.
31,001 links, 991.4 km, 85 components (largest holds 99.1 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---:|---:|---:|
| walking | 34 | 34 | 0 |
| cycling | 80 | 80 | 18 |
| car | 47 | 47 | 11 |
| heavy | 47 | 47 | 11 |

Sources (licences from `benchmark/licences.py`):

- `dft_manual`: OGL-UK-3.0 (https://roadtraffic.dft.gov.uk/downloads)
- `tfl`: TfL Open Data terms — OGL-UK-2.0 with TfL amendments (https://cycling.data.tfl.gov.uk; terms: https://tfl.gov.uk/corporate/terms-and-conditions/transport-data-service)

## Attributions and inputs

- Powered by TfL Open Data.
- Contains OS data © Crown copyright and database rights 2026.
- Contains public sector information licensed under the Open Government Licence v3.0 (Department for Transport; Office for National Statistics).
- Inputs: Population from ONS Census 2021 Output Area centroids (OGL-UK-3.0; subset of `london-v1`), POIs from OpenStreetMap (ODbL-1.0), 500 m zones, synthetic OD.
