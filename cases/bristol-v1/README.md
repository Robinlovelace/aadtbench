# bristol-v1 (case version 2.0.0, benchmark v0.3.0)

Bristol multimode annual average daily flow. Centre -2.5972985, 51.4538022, radius 15000 m, EPSG:27700.
Data files are assets of release v0.3.0 (`python -m benchmark.fetch --version v0.3.0 --case bristol-v1`).

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`None` (OSM timestamp None). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `ebf3a224a5c7806d82d8cf8b2c0e13453a32b6058b132123d00f3233a63bd05d`).
163985 links, 8480.6 km, 275 components (largest holds
99.6 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| cycling | 200 | 200 | 56 |
| car | 230 | 230 | 88 |
| heavy | 229 | 229 | 88 |

Sources (licences from `benchmark/licences.py`):

- `dft_manual`: OGL-UK-3.0 (https://roadtraffic.dft.gov.uk/downloads)

Excluded:

- none

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release v0.2.0. Rebuild:
`python benchmark/rebuild_case_osm.py --case bristol-v1 --source <extract> --out <dir>`.
