# oxford-mini-v1

Oxford multimode case for AADTBench 0.2.0. Built by `benchmark/export_multimode_case.py`.
Data files are release assets and are not in git. See `case.yaml` for the file list.

Centred on Carfax, central Oxford. Scored core 3 km, network, zones and OD extend 2 km beyond it. Used by CI smoke tests.

## Build

```text
PYTHONPATH=. python benchmark/export_multimode_case.py --city oxford --run-dir <run dir> --out <data dir> --version 0.2.0 --case-id oxford-mini-v1 --centre-lon -1.2578 --centre-lat 51.7519 --radius-m 3000 --margin-m 2000 --zone-m 500 --group-cell-m 1000
```

## Network

- OpenStreetMap derived links, cleaned (junctions consolidated, duplicates removed, one component kept) by a network preparation step run before export and frozen here as data, 14766 links, 1042.1 km, EPSG:27700.
- Node ids come from snapping link ends to 0.5 m. 11 connected components, the largest holds 99.9 percent of links.
- 190 links have a dual carriageway partner.
- Direction codes assume `forward` means along the stored geometry (checked on dual carriageway pairs: forward/forward pairs run in opposite geometry directions).
- Road class comes from the OSM `highway` tag. `ref` is an extra column used by the crosswalk.

## Counts and licences

| Source | Licence | Method | Sites kept |
|---|---|---|---|
| dft_manual | OGL-UK-3.0 (OGL v3 (DfT road traffic statistics AADF)) | short_period | 41 |
| oxflow | OGL-UK-3.0 (Oxfordshire County Council open data, OGL v3) | continuous | 335 |

Excluded sources:

- telraam: Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.

Sites kept, matched and unmatched per mode (unmatched sites stay in `sites.csv`, are not scored):

| Mode | Sites | Matched | Unmatched |
|---|---|---|---|
| walking | 66 | 66 | 0 |
| cycling | 98 | 98 | 0 |
| car | 106 | 106 | 0 |
| heavy | 106 | 106 | 0 |

Rows dropped by the export:

- dft_manual car: 83 (outside 3 km disc)
- dft_manual cycling: 64 (outside 3 km disc)
- dft_manual heavy: 81 (outside 3 km disc)
- oxflow car: 119 (outside 3 km disc)
- oxflow cycling: 89 (outside 3 km disc)
- oxflow heavy: 119 (outside 3 km disc)
- oxflow walking: 64 (outside 3 km disc)
- telraam car: 22 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam cycling: 22 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam heavy: 22 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam walking: 22 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)

## Crosswalk

Built by `benchmark/crosswalk.py`. Rule rows per mode: {"car": {"pair": 3, "point": 106}, "cycling": {"pair": 1, "point": 98}, "heavy": {"pair": 3, "point": 106}, "walking": {"pair": 0, "point": 66}}.

Check against the source model's own matches (342 shared sites): 92.1 percent share the same primary link, 92.1 percent have their link among our rows. This is a check only. The matches were not copied.

## Inputs

- `population.parquet`: WorldPop residents, CC BY 4.0, 10433 points, 172812 people within the extent.
- `pois.parquet`: OpenStreetMap POIs, ODbL 1.0, 2790 points, types {'services': 962, 'education': 508, 'retail': 503, 'food_drink': 342, 'health': 280, 'leisure': 195}.
- `zones.parquet`: 357 500 m cells covering the 5 km extent.
- `od_synthetic.parquet`: 227435 rows. Origin-constrained gravity per mode, attraction = POI weight + 0.1 times population, decay lengths walking 1 km (cap 3 km), cycling 3 km (cap 10 km), car 6 km, heavy 12 km. Trip rate 1 per person. It is a shape. The scale is arbitrary.

## Licence

The case contains OpenStreetMap derived data and is released under ODbL 1.0. Counts keep their own licence, shown per row in `sites.csv`.

## Caveats

- Flows are two-way annual averages. Short period sources (DfT manual counts) are expanded by their publisher.
- Counts that report one direction only are not handled. Sources in this case report two-way totals (assumed).
- The road class preference in crosswalk rule 2 applies to motor modes only. Walking and cycling take the nearest link. See the agreement check above.
- No heavy vehicle or walking site has an independent check beyond the shared crosswalk.
- The scored core is a 3 km disc around the centre. The network, population, POIs, zones and synthetic OD extend 2 km beyond it, so flows at core sites are complete. Sites are kept only inside the core.
- Fold groups use 1000 m cells (`split.group_cell_m` in `case.yaml`), because a 3 km cell would leave too few groups in a small core.
- No elevation layer is included. If one is added later it must be Copernicus GLO-30, not FABDEM (CC BY-NC-SA, not allowed in an open case).
