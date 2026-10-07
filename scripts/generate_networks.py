#!/usr/bin/env python3
"""
Generate per-mode transport networks for a city using OSMnx and save them as
GeoPackage edge layers (matching the existing leuven_walk_edges.gpkg schema).

The walking network is usually already provided. This script fills in the
cycling and driving networks required for the multi-mode benchmark:
    data/leuven_cycle_edges.gpkg
    data/leuven_drive_edges.gpkg

Cities configured with an `osm_gpkg` key (a locally-cached geofabrik/osmextract
"lines" export) build networks offline from that cache instead of querying the
Overpass API -- this is how Leeds/West Yorkshire is built (see
config/cities.yaml `leeds:`), reusing the cache at
/mnt/secondary/home/robin/github/robinlovelace/criticalissues/data/cache/osmextract/.

Run:  PYTHONPATH=. python scripts/generate_networks.py --city leuven
      PYTHONPATH=. python scripts/generate_networks.py --city leeds
"""
import argparse
import os

import geopandas as gpd
import networkx as nx
import osmnx as ox

from scripts.config import get_city_config, get_modes, get_mode_config, TEST_MODE

# OSMnx network_type per benchmark mode.
NETWORK_TYPE = {"walk": "walk", "cycle": "bike", "drive": "drive"}

# Radii (km) used to buffer the overpass bbox so we get a little context around
# the study area.
BBOX_PAD_KM = 0.5

# Highway classes excluded per mode when building from a local OSM extract
# (approximates osmnx's built-in walk/bike/drive Overpass filters).
_EXCLUDE_ALWAYS = {"proposed", "construction", "abandoned", "platform", "raceway",
                    "bus_guideway", "escape", "elevator", "corridor"}
HIGHWAY_EXCLUDE = {
    "walk": _EXCLUDE_ALWAYS | {"motorway", "motorway_link"},
    "cycle": _EXCLUDE_ALWAYS | {"motorway", "motorway_link", "steps"},
    "drive": _EXCLUDE_ALWAYS | {"footway", "path", "steps", "pedestrian", "track",
                                 "cycleway", "bridleway", "service", "corridor"},
}


def build_from_local_gpkg(gpkg_path, mode, out_path, crs_project, bbox=None):
    """Build a simplified, routable per-mode network from a locally-cached
    osmextract/geofabrik 'lines' GeoPackage layer, without hitting Overpass.

    Mirrors osmnx's own pipeline: explode ways into vertex-to-vertex segments
    (so the graph is correctly noded at real intersections), build a
    MultiDiGraph, then run osmnx's own simplify_graph to contract degree-2
    chains -- producing edges/columns compatible with ox.graph_to_gdfs output.
    """
    print(f"  Reading local OSM cache: {gpkg_path} (layer=lines)", flush=True)
    gdf = gpd.read_file(gpkg_path, layer="lines", where="highway IS NOT NULL",
                         columns=["highway", "name", "oneway", "maxspeed"])
    exclude = HIGHWAY_EXCLUDE.get(mode, set())
    gdf = gdf[~gdf["highway"].isin(exclude)]
    if bbox is not None:
        lon_min, lat_min, lon_max, lat_max = bbox
        gdf = gdf.cx[lon_min:lon_max, lat_min:lat_max]
    print(f"  {mode}: {len(gdf)} ways after highway-class + bbox filter", flush=True)

    G = nx.MultiDiGraph(crs="EPSG:4326")
    node_id_of = {}
    next_id = [0]

    def node_id(xy):
        key = (round(xy[0], 6), round(xy[1], 6))
        if key not in node_id_of:
            node_id_of[key] = next_id[0]
            G.add_node(next_id[0], x=key[0], y=key[1])
            next_id[0] += 1
        return node_id_of[key]

    from shapely.geometry import LineString
    osmid = 0
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.geom_type != "LineString":
            continue
        coords = list(geom.coords)
        if len(coords) < 2:
            continue
        oneway = str(row.get("oneway", "")).lower() in ("yes", "true", "1")
        for a, b in zip(coords[:-1], coords[1:]):
            u, v = node_id(a), node_id(b)
            if u == v:
                continue
            seg_geom = LineString([a, b])
            G.add_edge(u, v, osmid=osmid, highway=row["highway"], oneway=oneway,
                       reversed=False, geometry=seg_geom)
            if not oneway:
                G.add_edge(v, u, osmid=osmid, highway=row["highway"], oneway=oneway,
                           reversed=True, geometry=seg_geom)
        osmid += 1

    print(f"  Raw graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges", flush=True)
    G = ox.truncate.largest_component(G, strongly=False)
    G = ox.distance.add_edge_lengths(G)
    G = ox.simplification.simplify_graph(G)
    print(f"  Simplified: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges", flush=True)

    gdf_edges = ox.convert.graph_to_gdfs(G, nodes=False, edges=True)
    gdf_edges = gpd.GeoDataFrame(gdf_edges, crs="EPSG:4326").reset_index()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    gdf_edges.to_file(out_path, driver="GPKG")
    print(f"  Saved {len(gdf_edges)} edges -> {out_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Generate per-mode networks for a city.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven)")
    parser.add_argument("--modes", nargs="*", default=None,
                        help="Subset of modes to (re)generate; default: all configured modes.")
    args = parser.parse_args()

    city = args.city
    cfg = get_city_config(city)
    modes = args.modes or get_modes(city)
    osm_gpkg = cfg.get("osm_gpkg")

    if osm_gpkg is None and "overpass_bbox" not in cfg:
        print(f"Neither osm_gpkg nor overpass_bbox configured for {city}; cannot generate networks.")
        return

    for mode in modes:
        mc = get_mode_config(city, mode)
        out_path = mc["network_file"]
        if os.path.exists(out_path) and not TEST_MODE:
            print(f"[skip] {mode}: {out_path} already exists")
            continue
        print(f"Generating {mode} network for {city} ...", flush=True)
        try:
            if osm_gpkg is not None:
                build_from_local_gpkg(osm_gpkg, mode, out_path, cfg["crs_project"],
                                       bbox=cfg.get("network_bbox"))
            else:
                ntype = NETWORK_TYPE.get(mode, "drive")
                lat_min, lon_min, lat_max, lon_max = cfg["overpass_bbox"]
                G = ox.graph_from_bbox(
                    (lon_min, lat_min, lon_max, lat_max),
                    network_type=ntype, simplify=True, retain_all=False,
                )
                gdf = ox.graph_to_gdfs(G, nodes=False, edges=True)
                # Normalise column order to match the walking edges layer.
                gdf = gpd.GeoDataFrame(gdf, crs=gdf.crs)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                gdf.to_file(out_path, driver="GPKG")
                print(f"  Saved {len(gdf)} edges -> {out_path}", flush=True)
        except Exception as e:
            print(f"  FAILED {mode}: {e}", flush=True)


if __name__ == "__main__":
    main()
