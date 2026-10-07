# melbourne-v1

Melbourne multimode case for AADTBench 0.2.0. Built by `benchmark/export_multimode_case.py`.
Data files are release assets and are not in git. See `case.yaml` for the file list.

## Build

```text
PYTHONPATH=. python benchmark/export_multimode_case.py --city melbourne --run-dir <run dir> --out <data dir> --version 0.2.0 --case-id melbourne-v1
```

## Network

- OpenStreetMap derived links, cleaned (junctions consolidated, duplicates removed, one component kept) by a network preparation step run before export and frozen here as data, 147518 links, 10990.7 km, EPSG:32755.
- Node ids come from snapping link ends to 0.5 m. 4 connected components, the largest holds 99.8 percent of links.
- 16764 links have a dual carriageway partner.
- Direction codes assume `forward` means along the stored geometry (checked on dual carriageway pairs: forward/forward pairs run in opposite geometry directions).
- Road class comes from the OSM `highway` tag. `ref` is an extra column used by the crosswalk.

## Counts and licences

| Source | Licence | Method | Sites kept |
|---|---|---|---|
| melbourne_ped | CC-BY-4.0 (CC-BY-4.0) | continuous | 100 |
| vic_dtp_aadt | CC-BY-4.0 (CC-BY-4.0) | short_period | 7467 |

Excluded sources:


Sites kept, matched and unmatched per mode (unmatched sites stay in `sites.csv`, are not scored):

| Mode | Sites | Matched | Unmatched |
|---|---|---|---|
| walking | 100 | 98 | 2 |
| cycling | 0 | 0 | 0 |
| car | 3944 | 3852 | 92 |
| heavy | 3523 | 3424 | 99 |

Rows dropped by the export:

- vic_dtp_aadt car: 2 (outside 15 km disc)
- vic_dtp_aadt heavy: 2 (outside 15 km disc)

## Crosswalk

Built by `benchmark/crosswalk.py`. Rule rows per mode: {"car": {"pair": 624, "point": 3852}, "heavy": {"pair": 560, "point": 3424}, "walking": {"pair": 26, "point": 98}}.

Check against the source model's own matches (4156 shared sites): 44.2 percent share the same primary link, 46.7 percent have their link among our rows. This is a check only. The matches were not copied.

## Inputs

- `population.parquet`: WorldPop residents, CC BY 4.0, 83542 points, 1769534 people within the disc.
- `pois.parquet`: OpenStreetMap POIs, ODbL 1.0, 29479 points, types {'services': 9732, 'retail': 6598, 'food_drink': 4547, 'health': 3786, 'education': 2801, 'leisure': 2015}.
- `zones.parquet`: 769 1 km cells covering the 15 km disc.
- `od_synthetic.parquet`: 926148 rows. Origin-constrained gravity per mode, attraction = POI weight + 0.1 times population, decay lengths walking 1 km (cap 3 km), cycling 3 km (cap 10 km), car 6 km, heavy 12 km. Trip rate 1 per person. It is a shape. The scale is arbitrary.

## Licence

The case contains OpenStreetMap derived data and is released under ODbL 1.0. Counts keep their own licence, shown per row in `sites.csv`.

## Caveats

- Flows are two-way annual averages. Short period sources (DfT manual counts) are expanded by their publisher.
- Counts that report one direction only are not handled. Sources in this case report two-way totals (assumed).
- The class preference in crosswalk rule 2 can place a cycling or walking count on a parallel main road. See the agreement check above.
- No heavy vehicle or walking site has an independent check beyond the shared crosswalk.
