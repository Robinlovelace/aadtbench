"""Build a synthetic gravity OD matrix + grid zones for Leuven.

cityseer_od and aequilibrae require an explicit OD matrix (geo_code1,
geo_code2, weight) and zone polygons (geo_code). Leuven has no census
journey-to-work OD, so we aggregate the WorldPop origins and OSM-POI
attractor destinations to a regular grid (400 m cells) and use a simple
production-attraction gravity weight: flow(o,d) = pop_o * weight_d.

This makes the demand IDENTICAL to what madina_worldpop/cityseer_demand/
flownet consume (same origins, same attractors), isolating the assignment
algorithm in the tool comparison.

Run:  PYTHONPATH=. .venv/bin/python scripts/prepare_leuven_od.py
"""
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

CRS = "EPSG:32631"
CELL = 400.0  # m — gives ~150 zones over the Leuven study area

origins = gpd.read_file("data/leuven_worldpop_origins.geojson").to_crs(CRS)
dests = gpd.read_file("data/leuven_attractors.geojson").to_crs(CRS)
print(f"origins={len(origins)} dests={len(dests)}", flush=True)

# Aggregate origins/dests onto a shared 400 m grid, weighted by pop / weight.
def grid_cells(gdf, weight_col):
    g = gdf.copy()
    g["_w"] = g[weight_col].astype(float)
    g["gx"] = (g.geometry.x // CELL).astype(int)
    g["gy"] = (g.geometry.y // CELL).astype(int)
    agg = g.groupby(["gx", "gy"])["_w"].sum().reset_index()
    return agg

agg_o = grid_cells(origins, "population").rename(columns={"_w": "pop"})
agg_d = grid_cells(dests, "attractor_weight").rename(columns={"_w": "weight"})
print(f"grid cells: origins={len(agg_o)} destinations={len(agg_d)}", flush=True)

# Zone polygons = union of origin and destination cells (geometry = cell box,
# zone id = "Zx_y" over the union; origin/dest cells share ids where they
# coincide, which the OD tools need for within-zone flows).
cells = pd.concat([
    agg_o[["gx", "gy"]], agg_d[["gx", "gy"]]
]).drop_duplicates().reset_index(drop=True)
cells["geo_code"] = [f"Z{r.gx}_{r.gy}" for r in cells.itertuples()]
zone_gdf = gpd.GeoDataFrame(
    cells[["geo_code"]],
    geometry=[box(r.gx * CELL, r.gy * CELL,
                  (r.gx + 1) * CELL, (r.gy + 1) * CELL)
              for r in cells.itertuples()],
    crs=CRS,
)
zone_gdf["geo_name"] = zone_gdf["geo_code"]
zone_gdf.to_file("data/leuven_gravity_zones.geojson", driver="GeoJSON")
print(f"zones written: {len(zone_gdf)}", flush=True)

pop_map = {(r.gx, r.gy): r.pop for r in agg_o.itertuples()}
w_map = {(r.gx, r.gy): r.weight for r in agg_d.itertuples()}
code_map = {(r.gx, r.gy): r.geo_code for r in cells.itertuples()}

rows = []
for (gx1, gy1), p in pop_map.items():
    for (gx2, gy2), w in w_map.items():
        if p > 0 and w > 0:
            rows.append((code_map[(gx1, gy1)], code_map[(gx2, gy2)], p * w))
od = pd.DataFrame(rows, columns=["geo_code1", "geo_code2", "all"])
od.to_csv("data/leuven_gravity_od.csv", index=False)
print(f"OD pairs: {len(od)}  total weight={od['all'].sum():.0f}", flush=True)
