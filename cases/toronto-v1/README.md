# toronto-v1 (case version 1.0.0, benchmark v0.3.0)

Toronto annual average daily flow (City of Toronto counts). Centre -79.3839347, 43.6534817, radius 15000 m, EPSG:32617.
Data files are assets of release v0.3.0 (`python -m benchmark.fetch --version v0.3.0 --case toronto-v1`).

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`None` (OSM timestamp None). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `445391f0c24d42895d6be85eb2eb953a938e3c165db4c261446c028ac76d2f61`).
333673 links, 13597.5 km, 555 components (largest holds
99.4 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| walking | 11626 | 11310 | 0 |
| cycling | 10778 | 10299 | 1153 |
| car | 11628 | 11317 | 1432 |
| heavy | 10724 | 9076 | 1211 |

Sources (licences from `benchmark/licences.py`):

- `toronto_bike`: OGL-Toronto (https://open.toronto.ca)
- `toronto_svc`: OGL-Toronto (https://open.toronto.ca)
- `toronto_tmc`: OGL-Toronto (https://open.toronto.ca)

Excluded:

- none

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release v0.2.0. Rebuild:
`python benchmark/rebuild_case_osm.py --case toronto-v1 --source <extract> --out <dir>`.
