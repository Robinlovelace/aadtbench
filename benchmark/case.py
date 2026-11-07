"""Load a versioned AADTBench case (case.yaml in git, data from the release)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pandas as pd
import yaml

CASES_ROOT = Path(__file__).resolve().parents[1] / "cases"
BENCHMARK_VERSION = "v0.1.0"
V2_REQUIRED = ["case.yaml", "network.parquet", "sites.csv", "crosswalk.csv"]
ROAD_CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "minor",
                "service", "cycleway", "footway", "other"]
CLASS_RANK = {c: i for i, c in enumerate(ROAD_CLASSES)}


def resolve_case_dir(case: str | Path, cases_root: str | Path | None = None,
                     version: str = BENCHMARK_VERSION,
                     from_dir: str | Path | None = None) -> Path:
    p = Path(case)
    root = p if (p.is_absolute() or len(p.parts) > 1) else Path(cases_root or CASES_ROOT) / str(case)
    if all((root / f).exists() for f in V2_REQUIRED):
        return root
    from benchmark.fetch import fetch
    fetch(version, root.name, root.parent, from_dir)
    missing = [f for f in V2_REQUIRED if not (root / f).exists()]
    if missing:
        raise FileNotFoundError(f"case {root} still lacks {missing} after fetch")
    return root


@dataclass
class Case:
    case_dir: Path
    manifest: dict
    network: pd.DataFrame
    sites: pd.DataFrame
    crosswalk: pd.DataFrame

    @property
    def case_id(self) -> str:
        return str(self.manifest["id"])

    @property
    def version(self) -> str:
        return str(self.manifest.get("version", ""))

    @property
    def benchmark_version(self) -> str:
        v = str(self.manifest.get("benchmark_version", BENCHMARK_VERSION))
        return v if v.startswith("v") else "v" + v

    @property
    def modes(self) -> list[str]:
        m = self.manifest.get("modes")
        return [x if isinstance(x, str) else x["id"] for x in m] if m else sorted(self.sites["mode"].unique())

    @property
    def crs(self) -> str:
        return str(self.manifest.get("crs") or self.network.crs)

    def centre_xy(self) -> tuple[float, float]:
        m = self.manifest
        if "centre_x" in m and "centre_y" in m:
            return float(m["centre_x"]), float(m["centre_y"])
        if "centre_lon" in m and "centre_lat" in m and self.network.crs is not None:
            from pyproj import Transformer
            t = Transformer.from_crs(4326, self.network.crs, always_xy=True)
            x, y = t.transform(float(m["centre_lon"]), float(m["centre_lat"]))
            return float(x), float(y)
        minx, miny, maxx, maxy = self.network.total_bounds
        return (minx + maxx) / 2, (miny + maxy) / 2

    def _input(self, name: str, geo: bool = False):
        path = self.case_dir / "inputs" / f"{name}.parquet"
        if not path.exists():
            from benchmark.fetch import fetch
            fetch(self.benchmark_version, self.case_id, self.case_dir.parent, files={f"inputs/{name}.parquet"})
        if not path.exists():
            return None
        if geo:
            import geopandas as gpd
            return gpd.read_parquet(path)
        return pd.read_parquet(path)

    @cached_property
    def population(self):
        return self._input("population")

    @cached_property
    def pois(self):
        return self._input("pois")

    @cached_property
    def zones(self):
        return self._input("zones", geo=True)

    @cached_property
    def od_synthetic(self):
        return self._input("od_synthetic")

    @cached_property
    def od_observed(self):
        return self._input("od_observed")

    def site_road_class(self) -> pd.Series:
        net = self.network[["segment_id", "road_class"]].astype({"segment_id": str})
        xw = self.crosswalk.astype({"segment_id": str}).merge(net, on="segment_id", how="left")
        xw["road_class"] = xw["road_class"].fillna("other")
        xw["_rank"] = xw["road_class"].map(CLASS_RANK).fillna(len(CLASS_RANK))
        xw = xw.sort_values(["site_id", "mode", "weight", "_rank"], ascending=[True, True, False, True])
        return xw.drop_duplicates(["site_id", "mode"]).set_index(["site_id", "mode"])["road_class"]


def load_case(case: str | Path, cases_root: str | Path | None = None,
              version: str = BENCHMARK_VERSION, from_dir: str | Path | None = None) -> Case:
    import geopandas as gpd
    root = resolve_case_dir(case, cases_root, version, from_dir)
    manifest = yaml.safe_load((root / "case.yaml").read_text())
    network = gpd.read_parquet(root / "network.parquet")
    network["segment_id"] = network["segment_id"].astype(str)
    sites = pd.read_csv(root / "sites.csv", dtype={"site_id": str})
    xw = pd.read_csv(root / "crosswalk.csv", dtype={"site_id": str, "segment_id": str})
    return Case(case_dir=root, manifest=manifest, network=network, sites=sites, crosswalk=xw)
