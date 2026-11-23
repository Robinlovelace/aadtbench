# paris-v1 (case version 1.0.0, benchmark v0.1.0)

Paris multimode annual average daily flow (Ville de Paris Open Data). Centre 2.3483915, 48.8534951, radius 15000 m, EPSG:32631.
Data files are assets of release v0.1.0 (`python -m benchmark.fetch --version v0.1.0 --case paris-v1`).

## Network

Raw OpenStreetMap (ODbL-1.0), built by `benchmark/build_osm_network.py`. Ways
with a routable `highway` tag, split at shared nodes, no cleaning. The clipped
highway extract is published as `source.osm.pbf` (sha256
`f345cc0b409eae7706c4735735ae5099fcd9e960047825df68370672cc357885`).
782,493 links, 25,036.7 km, 2,835 components (largest holds 99.2 percent of
links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---:|---:|---:|
| cycling | 125 | 125 | 64 |
| car | 1297 | 1293 | 555 |
| heavy | 35 | 35 | 16 |

Sources (licences from `benchmark/licences.py`):

- `paris_multimodal`: ODbL-1.0 (https://opendata.paris.fr/explore/dataset/comptage-multimodal-comptages/)
- `paris_velo`: ODbL-1.0 (https://opendata.paris.fr/explore/dataset/comptage-velo-donnees-compteurs/)
- `paris_road`: ODbL-1.0 (https://opendata.paris.fr/explore/dataset/comptages-routiers-permanents/)

## Attributions and inputs

- Traffic and cycling counts: Direction de la Voirie et des Déplacements – Ville de Paris, licensed under ODbL-1.0 (`opendata.paris.fr`).
- Inputs: WorldPop (CC BY 4.0), OSM POIs (ODbL-1.0), 1 km zones, synthetic OD.
