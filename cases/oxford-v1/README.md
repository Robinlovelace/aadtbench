# oxford-v1

Oxford multimode case for AADTBench 0.2.0. Built by `benchmark/export_multimode_case.py`.
Data files are release assets and are not in git. See `case.yaml` for the file list.

## Build

```text
PYTHONPATH=. python benchmark/export_multimode_case.py --city oxford --run-dir <run dir> --out <data dir> --version 0.2.0 --case-id oxford-v1
```

## Network

- OpenStreetMap derived links, cleaned (junctions consolidated, duplicates removed, one component kept) by a network preparation step run before export and frozen here as data, 49320 links, 5188.8 km, EPSG:27700.
- Node ids come from snapping link ends to 0.5 m. 2 connected components, the largest holds 100.0 percent of links.
- 482 links have a dual carriageway partner.
- Direction codes assume `forward` means along the stored geometry (checked on dual carriageway pairs: forward/forward pairs run in opposite geometry directions).
- Road class comes from the OSM `highway` tag. `ref` is an extra column used by the crosswalk.

## Counts and licences

| Source | Licence | Method | Sites kept |
|---|---|---|---|
| dft_manual | OGL-UK-3.0 (OGL v3 (DfT road traffic statistics AADF)) | short_period | 266 |
| oxflow | OGL-UK-3.0 (Oxfordshire County Council open data, OGL v3) | continuous | 726 |

Excluded sources:

- telraam: Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.

Sites kept, matched and unmatched per mode (unmatched sites stay in `sites.csv`, are not scored):

| Mode | Sites | Matched | Unmatched |
|---|---|---|---|
| walking | 130 | 130 | 0 |
| cycling | 250 | 248 | 2 |
| car | 307 | 305 | 2 |
| heavy | 305 | 303 | 2 |

Rows dropped by the export:

- dft_manual car: 1 (outside 15 km disc)
- dft_manual cycling: 1 (outside 15 km disc)
- dft_manual heavy: 1 (outside 15 km disc)
- telraam car: 22 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam cycling: 22 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam heavy: 22 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam walking: 22 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)

## Crosswalk

Built by `benchmark/crosswalk.py`. Rule rows per mode: {"car": {"pair": 22, "point": 305}, "cycling": {"pair": 6, "point": 248}, "heavy": {"pair": 22, "point": 303}, "walking": {"pair": 0, "point": 130}}.

Check against the source model's own matches (936 shared sites): 95.8 percent share the same primary link, 95.8 percent have their link among our rows. This is a check only. The matches were not copied.

## Inputs

- `population.parquet`: WorldPop residents, CC BY 4.0, 58220 points, 331805 people within the extent.
- `pois.parquet`: OpenStreetMap POIs, ODbL 1.0, 6091 points, types {'services': 2508, 'retail': 1262, 'education': 811, 'food_drink': 678, 'health': 502, 'leisure': 330}.
- `zones.parquet`: 770 1000 m cells covering the 15 km extent.
- `od_synthetic.parquet`: 628005 rows. Origin-constrained gravity per mode, attraction = POI weight + 0.1 times population, decay lengths walking 1 km (cap 3 km), cycling 3 km (cap 10 km), car 6 km, heavy 12 km. Trip rate 1 per person. It is a shape. The scale is arbitrary.

## Licence

The case contains OpenStreetMap derived data and is released under ODbL 1.0. Counts keep their own licence, shown per row in `sites.csv`.

## Caveats

- Flows are two-way annual averages. Short period sources (DfT manual counts) are expanded by their publisher.
- Counts that report one direction only are not handled. Sources in this case report two-way totals (assumed).
- The road class preference in crosswalk rule 2 applies to motor modes only. Walking and cycling take the nearest link. See the agreement check above.
- No heavy vehicle or walking site has an independent check beyond the shared crosswalk.
