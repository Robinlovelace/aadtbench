# leuven-v1 (case version 2.0.0, benchmark v0.3.0)

Leuven multimode flow from Telraam sensors (non-commercial). Centre 4.701, 50.879, radius 15000 m, EPSG:31370.
Data files are assets of release v0.3.0 (`python -m benchmark.fetch --version v0.3.0 --case leuven-v1`).

**Non-commercial case.** Source: Telraam (telraam.net), CC BY-NC 4.0

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`None` (OSM timestamp None). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `903e1076897d7f69246364ba3f8d46204d6e43d49f355fd8b862b6d516cc6d88`).
110159 links, 7252.9 km, 247 components (largest holds
99.4 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| walking | 38 | 38 | 0 |
| cycling | 37 | 37 | 2 |
| car | 37 | 37 | 1 |

Sources (licences from `benchmark/licences.py`):

- `telraam`: CC-BY-NC-4.0 (https://faq.telraam.net/article/9/telraam-data-license-what-can-i-do-with-the-telraam-data)

Excluded:

- none

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release v0.2.0. Rebuild:
`python benchmark/rebuild_case_osm.py --case leuven-v1 --source <extract> --out <dir>`.
