# bristol-v1

Bristol multimode case for AADTBench 0.2.0. Built by `benchmark/export_multimode_case.py`.
Data files are release assets and are not in git. See `case.yaml` for the file list.

## Build

```text
PYTHONPATH=. python benchmark/export_multimode_case.py --city bristol --run-dir <run dir> --out <data dir> --version 0.2.0 --case-id bristol-v1
```

## Network

- OpenStreetMap derived links, cleaned (junctions consolidated, duplicates removed, one component kept) by a network preparation step run before export and frozen here as data, 93464 links, 7697.5 km, EPSG:27700.
- Node ids come from snapping link ends to 0.5 m. 3 connected components, the largest holds 100.0 percent of links.
- 1730 links have a dual carriageway partner.
- Direction codes assume `forward` means along the stored geometry (checked on dual carriageway pairs: forward/forward pairs run in opposite geometry directions).
- Road class comes from the OSM `highway` tag. `ref` is an extra column used by the crosswalk.

## Counts and licences

| Source | Licence | Method | Sites kept |
|---|---|---|---|
| dft_manual | OGL-UK-3.0 (OGL v3 (DfT road traffic statistics AADF)) | short_period | 659 |

Excluded sources:

- telraam: Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.
- vivacity: local authority terms, check per authority

Sites kept, matched and unmatched per mode (unmatched sites stay in `sites.csv`, are not scored):

| Mode | Sites | Matched | Unmatched |
|---|---|---|---|
| walking | 0 | 0 | 0 |
| cycling | 200 | 199 | 1 |
| car | 230 | 229 | 1 |
| heavy | 229 | 228 | 1 |

Rows dropped by the export:

- telraam car: 1 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam cycling: 1 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam heavy: 1 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam walking: 1 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- vivacity car: 102 (local authority terms, check per authority)
- vivacity cycling: 103 (local authority terms, check per authority)
- vivacity heavy: 101 (local authority terms, check per authority)
- vivacity walking: 80 (local authority terms, check per authority)

## Crosswalk

Built by `benchmark/crosswalk.py`. Rule rows per mode: {"car": {"pair": 46, "point": 229}, "cycling": {"pair": 25, "point": 199}, "heavy": {"pair": 46, "point": 228}}.

Check against the source model's own matches (641 shared sites): 94.5 percent share the same primary link, 95.6 percent have their link among our rows. This is a check only. The matches were not copied.

## Inputs

- `population.parquet`: WorldPop residents, CC BY 4.0, 81894 points, 852353 people within the disc.
- `pois.parquet`: OpenStreetMap POIs, ODbL 1.0, 13285 points, types {'services': 5501, 'retail': 2991, 'food_drink': 1669, 'education': 1261, 'health': 1106, 'leisure': 757}.
- `zones.parquet`: 767 1 km cells covering the 15 km disc.
- `od_synthetic.parquet`: 758879 rows. Origin-constrained gravity per mode, attraction = POI weight + 0.1 times population, decay lengths walking 1 km (cap 3 km), cycling 3 km (cap 10 km), car 6 km, heavy 12 km. Trip rate 1 per person. It is a shape. The scale is arbitrary.

## Licence

The case contains OpenStreetMap derived data and is released under ODbL 1.0. Counts keep their own licence, shown per row in `sites.csv`.

## Caveats

- Flows are two-way annual averages. Short period sources (DfT manual counts) are expanded by their publisher.
- Counts that report one direction only are not handled. Sources in this case report two-way totals (assumed).
- The class preference in crosswalk rule 2 can place a cycling or walking count on a parallel main road. See the agreement check above.
- No heavy vehicle or walking site has an independent check beyond the shared crosswalk.
