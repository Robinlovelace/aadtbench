# leeds-v1 (case version 2.0.0, benchmark v0.3.0)

Leeds multimode annual average daily flow (DfT and Leeds City Council footfall cameras). Centre -1.5437941, 53.7974185, radius 15000 m, EPSG:27700.
Data files are assets of release v0.3.0 (`python -m benchmark.fetch --version v0.3.0 --case leeds-v1`).

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`None` (OSM timestamp None). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `475bfbcadd9cc3307d170c3ac47f690508df871e2fa1f10e3860c847ab3b6078`).
230330 links, 11038.8 km, 292 components (largest holds
99.7 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| walking | 8 | 8 | 0 |
| cycling | 362 | 360 | 122 |
| car | 417 | 417 | 180 |
| heavy | 415 | 415 | 180 |

Sources (licences from `benchmark/licences.py`):

- `dft_manual`: OGL-UK-3.0 (https://roadtraffic.dft.gov.uk/downloads)
- `leeds_footfall`: OGL-UK-3.0 (https://datamillnorth.org/dataset/leeds-city-centre-footfall-2kx4d)

Excluded:

- none

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release v0.2.0. Rebuild:
`python benchmark/rebuild_case_osm.py --case leeds-v1 --source <extract> --out <dir>`.
