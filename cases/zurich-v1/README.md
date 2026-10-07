# zurich-v1 (case version 1.0.0, benchmark v0.3.0)

Zurich annual average daily flow (Stadt Zuerich counts). Centre 8.5410422, 47.3744489, radius 15000 m, EPSG:32632.
Data files are assets of release v0.3.0 (`python -m benchmark.fetch --version v0.3.0 --case zurich-v1`).

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`None` (OSM timestamp None). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `fffca458f6933a319c0aa3dfcc3e8e4041cc68f73c18e83ed041ba64e9e0998a`).
362938 links, 14238.1 km, 676 components (largest holds
99.6 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| cycling | 23 | 23 | 2 |
| car | 102 | 102 | 42 |

Sources (licences from `benchmark/licences.py`):

- `stadt_zuerich_fuss_velo`: CC0-1.0 (https://data.stadt-zuerich.ch)
- `stadt_zuerich_miv`: CC0-1.0 (https://data.stadt-zuerich.ch)

Excluded:

- none

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release v0.2.0. Rebuild:
`python benchmark/rebuild_case_osm.py --case zurich-v1 --source <extract> --out <dir>`.
