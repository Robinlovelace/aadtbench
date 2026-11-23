# oxford-v1 (case version 1.0.0, benchmark v0.1.0)

Oxford multimode annual average daily flow (DfT Road Traffic Statistics). Centre -1.2578499, 51.7520131, radius 15000 m, EPSG:27700.
Data files are assets of release v0.1.0 (`python -m benchmark.fetch --version v0.1.0 --case oxford-v1`).

## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py`. Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `b5efb6765e3efb53e4ce35a904caad8b5f020f6526b1b296ce57bc4298af94dd`).
83546 links, 5381.5 km, 319 components (largest holds
99.0 percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
| cycling | 76 | 76 | 12 |
| car | 96 | 96 | 33 |
| heavy | 94 | 94 | 33 |

Sources (licences from `benchmark/licences.py`):

- `dft_manual`: OGL-UK-3.0 (https://roadtraffic.dft.gov.uk/downloads)

Excluded:

- none

Inputs: WorldPop (CC BY 4.0), OSM POIs (ODbL), zones, synthetic OD. Rebuild:
`python benchmark/build_case.py --case oxford-v1 --source <extract> --out <dir>`.
