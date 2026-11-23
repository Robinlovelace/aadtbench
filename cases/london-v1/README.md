# london-v1 (case version 1.0.0, benchmark v0.1.0)

London multimode annual average daily flow (DfT Road Traffic Statistics and Transport for London Active Travel Counts Programme). Centre -0.1276, 51.5072, radius 15000 m, EPSG:27700.
Data files are assets of release v0.1.0 (`python -m benchmark.fetch --version v0.1.0 --case london-v1`).

## Network

Raw OpenStreetMap (ODbL-1.0), built by `benchmark/build_osm_network.py` from
`geofabrik_great-britain-261025.osm.pbf` (`2026-10-25T21:21:21Z`). Ways with a
routable `highway` tag, split at shared nodes, no cleaning. The clipped highway
extract is published as `source.osm.pbf` (sha256
`6b4c25232090348ee3a2261f2c5556ee89778d3f327a53f200e72f7d3991ac72`).
681,498 links, 21,559.8 km, 1,620 components (largest holds 99.4 percent of
links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---:|---:|---:|
| walking | 1146 | 1146 | 0 |
| cycling | 2876 | 2872 | 356 |
| car | 1769 | 1765 | 318 |
| heavy | 1758 | 1751 | 318 |

Sources (licences from `benchmark/licences.py`):

- `dft_manual`: OGL-UK-3.0 (https://roadtraffic.dft.gov.uk/downloads)
- `tfl`: TfL Open Data terms — OGL-UK-2.0 with TfL amendments (https://cycling.data.tfl.gov.uk; terms: https://tfl.gov.uk/corporate/terms-and-conditions/transport-data-service)

## Attributions and inputs

- Powered by TfL Open Data.
- Contains OS data © Crown copyright and database rights 2026.
- Contains public sector information licensed under the Open Government Licence v3.0 (Department for Transport; Office for National Statistics).
- Inputs: Population from ONS Census 2021 Output Area centroids (OGL-UK-3.0; 17,736 points covering the 15 km disc), POIs from OpenStreetMap (ODbL-1.0), 1 km zones, synthetic OD.
