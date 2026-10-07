# oxford-mini-v1 (case version 2.0.0, benchmark v0.3.0)

Oxford multimode annual average daily flow. Centre -1.2578, 51.7519, radius 3000 m, margin 2000 m, EPSG:27700.
Data files are assets of release v0.3.0 (`python -m benchmark.fetch --version v0.3.0 --case oxford-mini-v1`).

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`None` (OSM timestamp None). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `4eeef62fc3f74714a27d374d9b61f1e950b95243b6c0c42e73d3414615010f2c`).
36340 links, 1474.3 km, 140 components (largest holds
99.1 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| walking | 60 | 60 | 0 |
| cycling | 90 | 90 | 6 |
| car | 96 | 95 | 9 |
| heavy | 96 | 95 | 9 |

Sources (licences from `benchmark/licences.py`):

- `dft_manual`: OGL-UK-3.0 (https://roadtraffic.dft.gov.uk/downloads)
- `oxflow`: OGL-UK-3.0 (https://www.oxfordshire.gov.uk (open data, OGL v3))

Excluded:

- none

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release v0.2.0. Rebuild:
`python benchmark/rebuild_case_osm.py --case oxford-mini-v1 --source <extract> --out <dir>`.
