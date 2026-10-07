# leeds-v2

Leeds multimode case for AADTBench 0.2.0. Built by `benchmark/export_multimode_case.py`.
Data files are release assets and are not in git. See `case.yaml` for the file list.

## Build

```text
PYTHONPATH=. python benchmark/export_multimode_case.py --city leeds --run-dir <run dir> --out <data dir> --version 0.2.0 --case-id leeds-v2
```

## Network

- OpenStreetMap derived links, cleaned (junctions consolidated, duplicates removed, one component kept) by a network preparation step run before export and frozen here as data, 148924 links, 10727.9 km, EPSG:27700.
- Node ids come from snapping link ends to 0.5 m. 8 connected components, the largest holds 100.0 percent of links.
- 2408 links have a dual carriageway partner.
- Direction codes assume `forward` means along the stored geometry (checked on dual carriageway pairs: forward/forward pairs run in opposite geometry directions).
- Road class comes from the OSM `highway` tag. `ref` is an extra column used by the crosswalk.

## Counts and licences

| Source | Licence | Method | Sites kept |
|---|---|---|---|
| dft_manual | OGL-UK-3.0 (OGL v3 (DfT road traffic statistics AADF)) | short_period | 1194 |

Excluded sources (case version 1.1.0 removed WYCA TAM: 152 car, 154 cycling, 152 heavy, 154 walking sites, and Leeds footfall: 8 walking sites):

- wyca_tam: WYCA traffic and active mode counts are not open data.
- leeds_footfall: licence not confirmed as open with a source link.

- telraam: Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.
- vivacity: local authority terms, check per authority

Sites kept, matched and unmatched per mode (unmatched sites stay in `sites.csv`, are not scored):

| Mode | Sites | Matched | Unmatched |
|---|---|---|---|
| cycling | 362 | 360 | 2 |
| car | 417 | 416 | 1 |
| heavy | 415 | 413 | 2 |

Rows dropped by the export:

- dft_manual car: 9 (outside 15 km disc)
- dft_manual cycling: 9 (outside 15 km disc)
- dft_manual heavy: 9 (outside 15 km disc)
- telraam car: 10 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam cycling: 10 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam heavy: 10 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- telraam walking: 10 (Telraam data is CC BY-NC 4.0 (non-commercial), not allowed in open cases.)
- vivacity car: 138 (local authority terms, check per authority)
- vivacity cycling: 129 (local authority terms, check per authority)
- vivacity heavy: 138 (local authority terms, check per authority)
- vivacity walking: 71 (local authority terms, check per authority)

## Crosswalk

Built by `benchmark/crosswalk.py`. Rule rows per mode: {"car": {"point": 416, "pair": 80}, "cycling": {"point": 360, "pair": 38}, "heavy": {"point": 413, "pair": 80}}.

Check against the source model's own matches (1723 shared sites): 95.8 percent share the same primary link, 96.2 percent have their link among our rows. This is a check only. The matches were not copied.

## Inputs

- `population.parquet`: WorldPop residents, CC BY 4.0, 101867 points, 1304467 people within the disc.
- `pois.parquet`: OpenStreetMap POIs, ODbL 1.0, 21131 points, types {'services': 8583, 'retail': 5259, 'food_drink': 2928, 'education': 1920, 'health': 1520, 'leisure': 921}.
- `zones.parquet`: 768 1 km cells covering the 15 km disc.
- `od_synthetic.parquet`: 1019901 rows. Origin-constrained gravity per mode, attraction = POI weight + 0.1 times population, decay lengths walking 1 km (cap 3 km), cycling 3 km (cap 10 km), car 6 km, heavy 12 km. Trip rate 1 per person. It is a shape. The scale is arbitrary.

## Licence

The case contains OpenStreetMap derived data and is released under ODbL 1.0. Counts keep their own licence, shown per row in `sites.csv`.

## Caveats

- Flows are two-way annual averages. Short period sources (DfT manual counts) are expanded by their publisher.
- Counts that report one direction only are not handled. Sources in this case report two-way totals (assumed).
- The class preference in crosswalk rule 2 can place a cycling or walking count on a parallel main road. See the agreement check above.
- No heavy vehicle site has an independent check beyond the shared crosswalk.
