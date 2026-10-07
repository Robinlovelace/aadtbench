# leuven-v1

Leuven multimode case for AADTBench. Non-commercial. Built by `benchmark/export_leuven_case.py`.
Data files are release assets and are not in git. See `case.yaml` for the file list.

## Licence and attribution

- Counts: Source: Telraam (telraam.net), CC BY-NC 4.0. This case is `licence_class: non_commercial`. It is scored and shown but kept out of the pooled leave-one-city-out board.
- Network and POIs: OpenStreetMap contributors, ODbL 1.0.
- Population: WorldPop, CC BY 4.0.
- Use of this case for commercial purposes is not permitted by the Telraam licence.

## Counts

Telraam sensors, the 7-day mean daily count per sensor. The counting period is unknown (not recorded in the source tables), so values are not seasonally adjusted and are not true annual averages. Method is `short_period_7day`. Sensors are points, matched with a 50 m radius because their coordinates are approximate.

- `car`: Telraam 'cars'. This is all light motor vehicles and may include some heavy vehicles.
- `cycling`: Telraam cyclists. `walking`: Telraam pedestrians.

| Mode | Sensors in source | Sites kept | Matched |
|---|---|---|---|
| walking | 38 | 38 | 21 |
| cycling | 37 | 37 | 23 |
| car | 37 | 37 | 23 |

Unmatched sensors lie outside the network extent. The OSM graphs cover about 5 km by 7 km around Leuven, and the nearest link allowing the mode is at least 96 m away for walking and over 800 m for cycling and car (checked), so no rule could place them.

Rule rows: {"car": {"point": 23}, "cycling": {"point": 23}, "walking": {"point": 21}}.
With fewer than about 40 sites per mode, a target is near or under the 20-site ranking threshold once folds are applied. Treat results as indicative.

## Network

- 15627 links, 785.4 km, EPSG:31370. 36 components, the largest holds 99.3 percent of links.
- The OSMnx walk, cycle and drive graphs were simplified separately. The case network starts from the walk graph (9568 links) and adds 6059 cycle or drive links that the walk graph does not cover. Access flags come from 80 percent overlap within 2 m of each mode's graph. Directions come from the directed edges that run along each link.
- `allow_heavy` copies `allow_car`. The graphs carry no HGV access tags.
- Links allowing each mode: {'allow_walking': 9568, 'allow_cycling': 11157, 'allow_car': 5128}. Car directions: {'both': 13763, 'forward': 1254, 'backward': 610}.

## Inputs

- population: 2859 WorldPop points, 54383 people.
- pois: 801 OSM points.
- zones: 769 1 km cells over the 15 km disc, most outside the data extent have zero mass.
- od_synthetic: 2418 rows, origin-constrained gravity as in the other cases.

## Caveats

- No heavy mode. Telraam does not separate heavy vehicles here.
- No independent check of the crosswalk (no other model matches exist for Leuven).
