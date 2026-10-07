#!/usr/bin/env python3
import os
import sys
import argparse
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy.spatial import cKDTree

from scripts.config import get_path, get_city_config
from madina.zonal import Zonal
from madina.una import parallel_betweenness
from scripts.utils.helpers import filter_stubs, match_sensors_to_edges

DATA_DIR = "data"
RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)
MATCH_DIST = 200

def run_simulation_and_generate_html(city):
    cfg = get_city_config(city)
    crs_project = cfg["crs_project"]
    
    print(f"1. Loading validation sensors for {city}...", flush=True)
    telr = gpd.read_file(get_path(cfg["sensors_file"])).to_crs(crs_project)
    tel_xy = np.array([(g.x, g.y) for g in telr.geometry])
    tel_ped = telr['avg_daily_pedestrians'].values.astype(float)
    
    print("2. Loading walk network edges...", flush=True)
    edges = gpd.read_file(get_path(cfg["edges_file"])).to_crs(crs_project)
    
    print("3. Loading demand data...", flush=True)
    origins = gpd.read_file(get_path(cfg["origins_file"])).to_crs(crs_project)
    destinations = gpd.read_file(get_path(cfg["destinations_file"])).to_crs(crs_project)
    
    print("4. Running best gravity simulation (wp_r1500_beta002_all)...", flush=True)
    z = Zonal()
    z.load_layer(name='streets', source=edges)
    z.create_street_network(source_layer='streets', weight_attribute='length')
    z.load_layer(name='origins', source=origins)
    z.load_layer(name='destinations', source=destinations)
    z.insert_node(layer_name='origins', label='origin', weight_attribute='population')
    z.insert_node(layer_name='destinations', label='destination', weight_attribute='attractor_weight')
    z.create_graph(light_graph=True)
    
    results = parallel_betweenness(
        z.network,
        search_radius=1500,
        detour_ratio=1.0,
        decay=True,
        decay_method='exponent',
        beta=0.002,
        num_cores=2,
        origin_weights=True,
        origin_weight_attribute='weight',
        closest_destination=False,
        destination_weights=True,
        destination_weight_attribute='weight',
        light_graph=True,
        turn_penalty=False
    )
    edge_gdf = results['edge_gdf']
    
    # Identify and flag stubs in zonal network using helper
    non_stub_gdf = filter_stubs(edge_gdf, z.network.light_graph)
    
    # Associate each sensor with its matched flow value using helper
    m_filt, i_filt, d_filt = match_sensors_to_edges(non_stub_gdf, telr, MATCH_DIST)
    
    telr['matched_flow'] = 0.0
    telr['matched_dist'] = 999.0
    for idx in range(len(telr)):
        if m_filt[idx]:
            matched_edge = non_stub_gdf.iloc[i_filt[idx]]
            telr.loc[idx, 'matched_flow'] = float(matched_edge['betweenness'])
            telr.loc[idx, 'matched_dist'] = float(d_filt[idx])
            
    # Save best predictions for option A scatter plots
    pd.DataFrame({
        "observed": tel_ped,
        "predicted": telr["matched_flow"].values
    }).to_csv(os.path.join(RESULTS_DIR, f"{city}_best_predictions.csv"), index=False)
            
    # Reproject to WGS84 (EPSG:4326) for Leaflet
    print("5. Reprojecting layers to WGS84...", flush=True)
    edge_gdf_4326 = edge_gdf.to_crs(epsg=4326)
    telr_4326 = telr.to_crs(epsg=4326)
    
    # To keep file size small, let's round coordinates to 5 decimals and select key columns
    def round_coords(geom):
        if geom is None:
            return None
        if geom.geom_type == 'LineString':
            return type(geom)([(round(x, 5), round(y, 5)) for x, y in geom.coords])
        elif geom.geom_type == 'Point':
            return type(geom)(round(geom.x, 5), round(geom.y, 5))
        return geom
        
    print("6. Rounding coordinates to 5 decimal places...", flush=True)
    edge_gdf_4326['geometry'] = edge_gdf_4326['geometry'].apply(round_coords)
    telr_4326['geometry'] = telr_4326['geometry'].apply(round_coords)
    
    # Keep only columns we need for visualization to save space
    edge_cols = ['betweenness', 'length', 'highway', 'is_stub', 'geometry']
    edge_cols = [c for c in edge_cols if c in edge_gdf_4326.columns]
    edges_to_save = edge_gdf_4326[edge_cols].copy()
    
    sensor_cols = ['segment_id', 'avg_daily_pedestrians', 'matched_flow', 'matched_dist', 'geometry']
    sensor_cols = [c for c in sensor_cols if c in telr_4326.columns]
    sensors_to_save = telr_4326[sensor_cols].copy()
    
    print("7. Converting layers to GeoJSON...", flush=True)
    edges_geojson_str = edges_to_save.to_json()
    sensors_geojson_str = sensors_to_save.to_json()
    
    max_flow = float(edge_gdf['betweenness'].max())
    print(f"Max flow: {max_flow}", flush=True)
    
    # Read HTML template and write variables
    html_template = """<!DOCTYPE html>
<html>
<head>
    <title>{CITY_TITLE} Pedestrian Flow Map</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {
            padding: 0;
            margin: 0;
            font-family: 'Inter', sans-serif;
            background-color: #0f172a;
            color: #f8fafc;
        }
        html, body, #map {
            height: 100%;
            width: 100vw;
        }
        
        .glass-panel {
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 8px 10px -6px rgba(0, 0, 0, 0.4);
            color: #f1f5f9;
            pointer-events: auto;
        }
        
        .map-title {
            position: absolute;
            top: 20px;
            left: 20px;
            z-index: 1000;
            max-width: 380px;
        }
        
        .map-title h1 {
            margin: 0 0 6px 0;
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.025em;
            color: #ffffff;
            background: linear-gradient(to right, #ff7e5f, #feb47b);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .map-title p {
            margin: 0;
            font-size: 12px;
            color: #94a3b8;
            line-height: 1.5;
        }
        
        .map-stats {
            margin-top: 12px;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            padding-top: 10px;
            display: flex;
            justify-content: space-between;
        }
        
        .stat-item {
            text-align: center;
        }
        
        .stat-val {
            font-size: 14px;
            font-weight: 700;
            color: #38bdf8;
        }
        
        .stat-lbl {
            font-size: 9px;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-top: 2px;
        }

        .info-panel {
            position: absolute;
            bottom: 30px;
            left: 20px;
            z-index: 1000;
            width: 320px;
            transition: all 0.25s ease;
            opacity: 0;
            transform: translateY(10px);
            pointer-events: none;
        }
        .info-panel.visible {
            opacity: 1;
            transform: translateY(0);
            pointer-events: auto;
        }
        .info-header {
            font-size: 11px;
            font-weight: 600;
            color: #38bdf8;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 8px;
        }
        .info-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 12px;
            color: white;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 13px;
        }
        .info-label {
            color: #94a3b8;
        }
        .info-value {
            font-weight: 600;
            color: #f1f5f9;
        }
        
        .map-legend {
            position: absolute;
            bottom: 30px;
            right: 20px;
            z-index: 1000;
            width: 240px;
        }
        .legend-title {
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 8px;
            color: white;
        }
        .legend-scale {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .legend-bar {
            height: 10px;
            background: linear-gradient(to right, #0b0405, #3b0f70, #8c2981, #de4968, #fe9f6d, #fcfdbf);
            border-radius: 4px;
            width: 100%;
        }
        .legend-labels {
            display: flex;
            justify-content: space-between;
            font-size: 10px;
            color: #94a3b8;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 6px;
            font-size: 11px;
            color: #cbd5e1;
        }
        .legend-circle {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background-color: #ff3366;
            border: 2px solid white;
            box-shadow: 0 0 6px rgba(255, 51, 102, 0.6);
        }
        
        .map-controls {
            position: absolute;
            top: 20px;
            right: 20px;
            z-index: 1000;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .control-btn {
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: #cbd5e1;
            width: 40px;
            height: 40px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
            transition: all 0.2s ease;
        }
        
        .control-btn:hover {
            background: rgba(30, 41, 59, 0.9);
            color: white;
            border-color: rgba(255, 255, 255, 0.15);
        }
        
        .leaflet-popup-content-wrapper {
            background: rgba(15, 23, 42, 0.95) !important;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #f1f5f9 !important;
            border-radius: 8px !important;
            padding: 4px;
        }
        .leaflet-popup-tip {
            background: rgba(15, 23, 42, 0.95) !important;
            border-left: 1px solid rgba(255, 255, 255, 0.12);
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
        }
        .popup-title {
            font-size: 13px;
            font-weight: 700;
            color: white;
            margin-bottom: 6px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            padding-bottom: 4px;
        }
        .popup-row {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            margin-bottom: 4px;
            gap: 16px;
        }
        .popup-label {
            color: #94a3b8;
        }
        .popup-value {
            font-weight: 600;
            color: #e2e8f0;
        }

        .leaflet-tooltip {
            background: #1e293b !important;
            color: #f1f5f9 !important;
            border: 1px solid rgba(255, 255, 255, 0.15) !important;
            border-radius: 4px !important;
            font-size: 11px !important;
            padding: 4px 8px !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3) !important;
        }
        
        .leaflet-bar {
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2) !important;
            border-radius: 8px !important;
            overflow: hidden;
        }
        .leaflet-bar a {
            background: rgba(15, 23, 42, 0.85) !important;
            backdrop-filter: blur(12px) !important;
            color: #cbd5e1 !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
        }
        .leaflet-bar a:hover {
            background: rgba(30, 41, 59, 0.9) !important;
            color: white !important;
        }
    </style>
</head>
<body>

    <div id="map"></div>

    <div class="glass-panel map-title">
        <h1>{CITY_TITLE} Pedestrian Flow</h1>
        <p>Pedestrian volume estimation for {CITY_TITLE} walk network. Calculated using the best-performing Gravity Model (WorldPop demand origins to OSM attractors, radius 1500m, beta 0.002).</p>
        <div class="map-stats">
            <div class="stat-item">
                <div class="stat-val">0.676</div>
                <div class="stat-lbl">Model R²</div>
            </div>
            <div class="stat-item">
                <div class="stat-val">0.822</div>
                <div class="stat-lbl">Pearson r</div>
            </div>
            <div class="stat-item">
                <div class="stat-val">{NUM_EDGES}</div>
                <div class="stat-lbl">Edges</div>
            </div>
            <div class="stat-item">
                <div class="stat-val">{NUM_SENSORS}</div>
                <div class="stat-lbl">Sensors</div>
            </div>
        </div>
    </div>

    <div class="glass-panel info-panel" id="infoPanel">
        <div class="info-header" id="infoType">Street Segment</div>
        <div class="info-title" id="infoName">Nameless Street</div>
        <div class="info-row">
            <div class="info-label">Estimated Flow:</div>
            <div class="info-value" id="infoFlow">-</div>
        </div>
        <div class="info-row" id="infoLengthRow">
            <div class="info-label">Segment Length:</div>
            <div class="info-value" id="infoLength">-</div>
        </div>
        <div class="info-row" id="infoExtraRow">
            <div class="info-label">Street Class:</div>
            <div class="info-value" id="infoExtra">-</div>
        </div>
    </div>

    <div class="glass-panel map-legend">
        <div class="legend-title">Legend</div>
        <div class="legend-scale">
            <div class="legend-bar"></div>
            <div class="legend-labels">
                <span>Low Flow (0)</span>
                <span>High Flow ({MAX_FLOW:.0f})</span>
            </div>
            <div class="legend-item">
                <div class="legend-circle"></div>
                <span>Telraam Pedestrian Sensors</span>
            </div>
        </div>
    </div>

    <div class="map-controls">
        <div class="control-btn" id="basemapBtn" title="Switch Basemap Style">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
        </div>
    </div>

    <script>
        const edgesData = {EDGES_GEOJSON};
        const sensorsData = {SENSORS_GEOJSON};
        const maxFlow = {MAX_FLOW};

        const map = L.map('map', {
            zoomControl: false
        }).setView([50.879, 4.700], 14);

        L.control.zoom({
            position: 'topright'
        }).addTo(map);

        const darkBasemap = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 20
        });

        const lightBasemap = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 20
        });

        darkBasemap.addTo(map);
        let currentBasemap = 'dark';

        document.getElementById('basemapBtn').addEventListener('click', () => {
            if (currentBasemap === 'dark') {
                map.removeLayer(darkBasemap);
                lightBasemap.addTo(map);
                currentBasemap = 'light';
                document.body.style.backgroundColor = '#f8fafc';
            } else {
                map.removeLayer(lightBasemap);
                darkBasemap.addTo(map);
                currentBasemap = 'dark';
                document.body.style.backgroundColor = '#0f172a';
            }
        });

        function getColor(value) {
            const t = Math.max(0, Math.min(1, value / maxFlow));
            const colors = [
                { r: 11, g: 4, b: 5 },
                { r: 59, g: 15, b: 112 },
                { r: 140, g: 41, b: 129 },
                { r: 222, g: 73, b: 104 },
                { r: 254, g: 159, b: 109 },
                { r: 252, g: 253, b: 191 }
            ];

            const idx = t * (colors.length - 1);
            const lowIdx = Math.floor(idx);
            const highIdx = Math.ceil(idx);
            const frac = idx - lowIdx;

            const c1 = colors[lowIdx];
            const c2 = colors[highIdx];

            const r = Math.round(c1.r + (c2.r - c1.r) * frac);
            const g = Math.round(c1.g + (c2.g - c1.g) * frac);
            const b = Math.round(c1.b + (c2.b - c1.b) * frac);

            return `rgb(${r}, ${g}, ${b})`;
        }

        const edgeLayer = L.geoJSON(edgesData, {
            style: function(feature) {
                const flow = feature.properties.betweenness || 0;
                const isStub = feature.properties.is_stub;
                
                let weight = 0.5;
                let opacity = 0.3;
                let color = '#555555';

                if (flow > 0 && !isStub) {
                    weight = 0.5 + 5.5 * Math.sqrt(flow / maxFlow);
                    opacity = 0.4 + 0.5 * (flow / maxFlow);
                    color = getColor(flow);
                } else if (isStub) {
                    weight = 0.5;
                    opacity = 0.15;
                    color = '#444444';
                }

                return {
                    color: color,
                    weight: weight,
                    opacity: opacity,
                    lineCap: 'round',
                    lineJoin: 'round'
                };
            },
            onEachFeature: function(feature, layer) {
                layer.on({
                    mouseover: function(e) {
                        const l = e.target;
                        l.setStyle({
                            color: '#00ffff',
                            opacity: 1.0,
                            weight: Math.max(l.options.weight * 1.5, 3.0)
                        });
                        if (!L.Browser.ie && !L.Browser.opera && !L.Browser.edge) {
                            l.bringToFront();
                        }
                        
                        const props = feature.properties;
                        const flowVal = props.betweenness || 0;
                        
                        document.getElementById('infoType').innerText = 'Street Segment';
                        document.getElementById('infoName').innerText = props.highway ? (props.highway.charAt(0).toUpperCase() + props.highway.slice(1)) : 'Walkway';
                        document.getElementById('infoFlow').innerText = flowVal.toLocaleString(undefined, {maximumFractionDigits: 1});
                        document.getElementById('infoLength').innerText = `${Math.round(props.length || 0)} m`;
                        document.getElementById('infoExtraRow').style.display = 'flex';
                        document.getElementById('infoExtra').innerText = props.highway || 'unknown';
                        
                        const panel = document.getElementById('infoPanel');
                        panel.classList.add('visible');
                    },
                    mouseout: function(e) {
                        edgeLayer.resetStyle(e.target);
                        document.getElementById('infoPanel').classList.remove('visible');
                    },
                    click: function(e) {
                        const props = feature.properties;
                        const flowVal = props.betweenness || 0;
                        
                        let popupContent = `
                            <div class="popup-title">${props.highway ? (props.highway.charAt(0).toUpperCase() + props.highway.slice(1)) : 'Street Segment'}</div>
                            <div class="popup-row">
                                <span class="popup-label">Est. Ped Flow:</span>
                                <span class="popup-value">${flowVal.toLocaleString(undefined, {maximumFractionDigits: 1})}</span>
                            </div>
                            <div class="popup-row">
                                <span class="popup-label">Length:</span>
                                <span class="popup-value">${Math.round(props.length || 0)} m</span>
                            </div>
                            <div class="popup-row">
                                <span class="popup-label">Type:</span>
                                <span class="popup-value">${props.highway || 'unknown'}</span>
                            </div>
                            <div class="popup-row">
                                <span class="popup-label">Stub network:</span>
                                <span class="popup-value">${props.is_stub ? 'Yes' : 'No'}</span>
                            </div>
                        `;
                        
                        L.popup()
                            .setLatLng(e.latlng)
                            .setContent(popupContent)
                            .openOn(map);
                    }
                });
            }
        }).addTo(map);

        const sensorLayer = L.geoJSON(sensorsData, {
            pointToLayer: function(feature, latlng) {
                const pedVal = feature.properties.avg_daily_pedestrians || 0;
                const radius = Math.max(4, Math.min(22, Math.sqrt(pedVal) * 0.35));
                
                return L.circleMarker(latlng, {
                    radius: radius,
                    fillColor: '#ff3366',
                    color: '#ffffff',
                    weight: 1.5,
                    opacity: 1.0,
                    fillOpacity: 0.9,
                    className: 'sensor-marker'
                });
            },
            onEachFeature: function(feature, layer) {
                layer.on({
                    mouseover: function(e) {
                        const l = e.target;
                        l.setStyle({
                            fillColor: '#00ffff',
                            weight: 2.5
                        });
                        
                        const props = feature.properties;
                        document.getElementById('infoType').innerText = 'Telraam Sensor';
                        document.getElementById('infoName').innerText = `Sensor ID: ${props.segment_id}`;
                        document.getElementById('infoFlow').innerText = `${Math.round(props.avg_daily_pedestrians).toLocaleString()} ped/day (Observed)`;
                        document.getElementById('infoLength').innerText = `${Math.round(props.matched_flow).toLocaleString()} (Model Pred)`;
                        document.getElementById('infoLengthRow').querySelector('.info-label').innerText = 'Estimated Flow:';
                        document.getElementById('infoExtraRow').style.display = 'flex';
                        document.getElementById('infoExtra').innerText = `${Math.round(props.matched_dist)} m`;
                        document.getElementById('infoExtraRow').querySelector('.info-label').innerText = 'Snapping Distance:';
                        
                        const panel = document.getElementById('infoPanel');
                        panel.classList.add('visible');
                    },
                    mouseout: function(e) {
                        sensorLayer.resetStyle(e.target);
                        document.getElementById('infoPanel').classList.remove('visible');
                        document.getElementById('infoLengthRow').querySelector('.info-label').innerText = 'Segment Length:';
                        document.getElementById('infoExtraRow').querySelector('.info-label').innerText = 'Street Class:';
                    },
                    click: function(e) {
                        const props = feature.properties;
                        
                        let popupContent = `
                            <div class="popup-title">Telraam Sensor: ${props.segment_id}</div>
                            <div class="popup-row">
                                <span class="popup-label">Obs. Pedestrians:</span>
                                <span class="popup-value" style="color:#ff3366">${Math.round(props.avg_daily_pedestrians).toLocaleString()} / day</span>
                            </div>
                            <div class="popup-row">
                                <span class="popup-label">Model Predicted Flow:</span>
                                <span class="popup-value" style="color:#38bdf8">${Math.round(props.matched_flow).toLocaleString()}</span>
                            </div>
                            <div class="popup-row">
                                <span class="popup-label">Nearest Edge Dist:</span>
                                <span class="popup-value">${Math.round(props.matched_dist)} meters</span>
                            </div>
                        `;
                        
                        L.popup()
                            .setLatLng(e.latlng)
                            .setContent(popupContent)
                            .openOn(map);
                    }
                });
            }
        }).addTo(map);

        if (edgesData.features.length > 0) {
            const bounds = edgeLayer.getBounds();
            map.fitBounds(bounds, { padding: [50, 50] });
        }
    </script>
</body>
</html>
"""
    
    city_title = city.capitalize()
    html_content = html_template.replace("{CITY_TITLE}", city_title)
    html_content = html_content.replace("{NUM_EDGES}", f"{len(edges):,}")
    html_content = html_content.replace("{NUM_SENSORS}", f"{len(telr):,}")
    html_content = html_content.replace("{EDGES_GEOJSON}", edges_geojson_str)
    html_content = html_content.replace("{SENSORS_GEOJSON}", sensors_geojson_str)
    html_content = html_content.replace("{MAX_FLOW}", f"{max_flow}")
    
    out_html = f"{city}-map.html"
    with open(out_html, "w") as f:
        f.write(html_content)
        
    print(f"Interactive HTML map saved to: {out_html}", flush=True)
    print(f"File size: {os.path.getsize(out_html) / (1024 * 1024):.2f} MB", flush=True)

def main():
    parser = argparse.ArgumentParser(description="Generate interactive map for a specific city.")
    parser.add_argument("--city", default="leuven", help="City name (e.g. leuven)")
    args = parser.parse_args()
    run_simulation_and_generate_html(args.city)

if __name__ == '__main__':
    main()
