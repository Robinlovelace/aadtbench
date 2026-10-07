# oxford-v1 (case version 2.0.0, benchmark v0.3.0)

Oxford multimode annual average daily flow. Centre -1.2578499, 51.7520131, radius 15000 m, EPSG:27700.
Data files are assets of release v0.3.0 (`python -m benchmark.fetch --version v0.3.0 --case oxford-v1`).

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`None` (OSM timestamp None). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `b5efb6765e3efb53e4ce35a904caad8b5f020f6526b1b296ce57bc4298af94dd`).
83546 links, 5381.5 km, 319 components (largest holds
99.0 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| walking | 124 | 124 | 0 |
| cycling | 241 | 240 | 22 |
| car | 294 | 292 | 52 |
| heavy | 292 | 290 | 52 |

Sources (licences from `benchmark/licences.py`):

- `dft_manual`: OGL-UK-3.0 (https://roadtraffic.dft.gov.uk/downloads)
- `oxflow`: OGL-UK-3.0 (https://www.oxfordshire.gov.uk (open data, OGL v3))

Excluded:

- none

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release v0.2.0. Rebuild:
`python benchmark/rebuild_case_osm.py --case oxford-v1 --source <extract> --out <dir>`.
