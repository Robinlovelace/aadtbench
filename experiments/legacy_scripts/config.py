import os
import yaml

# ONE-LINE SWITCH: Set to True for rapid testing (using cropped 5,900-edge test datasets), False for full runs
TEST_MODE = False

# Canonical travel modes supported across the benchmark suite.
ALL_MODES = ["walk", "cycle", "drive"]
# Typical free-flow travel speeds (m/s) used to translate radii into travel-time catchments.
MODE_SPEEDS = {"walk": 1.4, "cycle": 4.2, "drive": 8.3}

# Load central cities configuration
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "cities.yaml")
with open(CONFIG_PATH, "r") as f:
    _cities_config = yaml.safe_load(f)["cities"]


def get_city_config(city_name):
    """Get the city-level configuration dict (crs, bbox, and any mode-agnostic keys)."""
    if city_name not in _cities_config:
        raise ValueError(f"City '{city_name}' not configured in config/cities.yaml")
    return _cities_config[city_name]


def get_modes(city_name):
    """Return the list of travel modes configured for a city (defaults to ['walk'])."""
    cfg = get_city_config(city_name)
    if "modes" in cfg and cfg["modes"]:
        return list(cfg["modes"].keys())
    return ["walk"]


def get_mode_config(city_name, mode):
    """Get the per-mode configuration merged with city-level defaults.

    Returns a dict with at least: network_file, sensors_file, sensors_value,
    origins_file, destinations_file, crs_project, radii, betas, search_radii,
    travel_speed.
    """
    cfg = get_city_config(city_name)
    if "modes" not in cfg or mode not in cfg["modes"]:
        raise ValueError(f"Mode '{mode}' not configured for city '{city_name}' in config/cities.yaml")
    mc = dict(cfg["modes"][mode])
    # Inherit city-level fields that are not overridden at the mode level.
    for k in ("crs_project", "bbox", "overpass_bbox", "worldpop_url", "worldpop_local_tif"):
        if k not in mc and k in cfg:
            mc[k] = cfg[k]
    # Sensible defaults
    mc.setdefault("sensors_value", "avg_daily_pedestrians")
    mc.setdefault("travel_speed", MODE_SPEEDS.get(mode, 1.4))
    mc.setdefault("radii", [200, 400, 800, 1600, 3200])
    mc.setdefault("betas", [0.001, 0.002, 0.004])
    mc.setdefault("search_radii", [800, 1200, 1600, 2000])
    mc["mode"] = mode
    return mc


def get_path(filename):
    """Resolve correct path depending on whether TEST_MODE is active."""
    if TEST_MODE:
        dirname = os.path.dirname(filename)
        base = os.path.basename(filename)

        # Route sensor files to their respective projections
        if "pedestrians" in base:
            if "4326" in base:
                return os.path.join(dirname, "test_leuven_telraam_pedestrians_4326.geojson")
            else:
                return os.path.join(dirname, "test_leuven_telraam_pedestrians.geojson")

        new_base = f"test_{base}"
        return os.path.join(dirname, new_base) if dirname else new_base
    return filename


def resolve(city_name, mode, key):
    """Convenience: get a mode file path honouring TEST_MODE routing."""
    mc = get_mode_config(city_name, mode)
    return get_path(mc[key])
