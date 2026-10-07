# melbourne-v1 (case version 2.0.0, benchmark v0.3.0)

Melbourne multimode annual average daily flow. Centre 144.9631732, -37.8142454, radius 15000 m, EPSG:32755.
Data files are assets of release v0.3.0 (`python -m benchmark.fetch --version v0.3.0 --case melbourne-v1`).

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`None` (OSM timestamp None). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `14d339fe47b789f5a9b95db90538c9c0f9baec596172857ba1350f2766ba0b00`).
484294 links, 21438.4 km, 971 components (largest holds
99.6 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| walking | 100 | 100 | 0 |
| car | 2165 | 2120 | 1060 |
| heavy | 1948 | 1902 | 973 |

Sources (licences from `benchmark/licences.py`):

- `melbourne_ped`: CC-BY-4.0 (https://data.melbourne.vic.gov.au)
- `vic_dtp_aadt`: CC-BY-4.0 (https://discover.data.vic.gov.au)

Excluded:

- none

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release v0.2.0. Rebuild:
`python benchmark/rebuild_case_osm.py --case melbourne-v1 --source <extract> --out <dir>`.
