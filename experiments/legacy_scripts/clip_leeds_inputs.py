"""Clip Leeds benchmark inputs to a 10 km buffer around central Leeds.

User directive (2026-08-07): the full West Yorkshire networks (754k walk
edges) are too heavy; clip all Leeds inputs so they only cover a 10 km
buffer around central Leeds. Files are clipped IN PLACE (same names, same
formats) so config/cities.yaml and the bench scripts keep working.

Central Leeds reference: Leeds city centre, WGS84 (-1.5491, 53.8008).
"""
import geopandas as gpd
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Point
from shapely.ops import transform as shp_transform

CENTRE_WGS84 = Point(-1.5491, 53.8008)  # Leeds city centre
BUFFER_M = 10_000  # 10 km

_t = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
CENTRE_27700 = shp_transform(_t.transform, CENTRE_WGS84)
BUFFER_27700 = CENTRE_27700.buffer(BUFFER_M)
BUFFER_4326 = shp_transform(
    Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True).transform,
    BUFFER_27700,
)


def clip_edges(path: str) -> None:
    g = gpd.read_file(path)
    print(f"{path}: {len(g)} edges, crs={g.crs}", flush=True)
    g277 = g.to_crs("EPSG:27700")
    keep = g277.geometry.centroid.within(BUFFER_27700)
    g_clip = g[keep.values].copy()
    g_clip.to_file(path, driver="GPKG")
    print(f"  -> clipped to {len(g_clip)} edges", flush=True)


def clip_points(path: str) -> None:
    g = gpd.read_file(path)
    print(f"{path}: {len(g)} points, crs={g.crs}", flush=True)
    g277 = g.to_crs("EPSG:27700")
    keep = g277.geometry.within(BUFFER_27700)
    g_clip = g[keep.values].copy()
    g_clip.to_file(path, driver="GeoJSON")
    print(f"  -> clipped to {len(g_clip)} points", flush=True)


def clip_zones_and_od(zones_path: str, od_path: str) -> None:
    z = gpd.read_file(zones_path)
    print(f"{zones_path}: {len(z)} zones, crs={z.crs}", flush=True)
    z277 = z.to_crs("EPSG:27700")
    keep = z277.geometry.intersects(BUFFER_27700)
    z_clip = z[keep.values].copy()
    z_clip.to_file(zones_path, driver="GeoJSON")
    keep_codes = list(z_clip["geo_code"].astype(str))
    print(f"  -> {len(keep_codes)} zones kept", flush=True)

    od = pd.read_csv(od_path)
    n0 = len(od)
    od["geo_code1"] = od["geo_code1"].astype(str)
    od["geo_code2"] = od["geo_code2"].astype(str)
    od = od[od["geo_code1"].isin(keep_codes) & od["geo_code2"].isin(keep_codes)]
    od.to_csv(od_path, index=False)
    print(f"{od_path}: {n0} OD pairs -> {len(od)} (both zones in buffer)", flush=True)


if __name__ == "__main__":
    import sys
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data"
    clip_edges(f"{data_dir}/leeds_walk_edges.gpkg")
    clip_edges(f"{data_dir}/leeds_cycle_edges.gpkg")
    clip_edges(f"{data_dir}/leeds_drive_edges.gpkg")
    clip_points(f"{data_dir}/leeds_dft_aadt_27700.geojson")
    clip_zones_and_od(
        f"{data_dir}/leeds_pct_zones_msoa.geojson",
        f"{data_dir}/leeds_pct_od.csv",
    )
    print(f"\nBuffer (27700): {BUFFER_27700.bounds}", flush=True)
    print("Buffer (WGS84):", [round(b, 6) for b in BUFFER_4326.bounds], flush=True)
