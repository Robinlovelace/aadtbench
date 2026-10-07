"""Load a versioned AADTBench case (case.yaml in git, data from the release)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pandas as pd
import yaml

CASES_ROOT = Path(__file__).resolve().parents[1] / "cases"
BENCHMARK_VERSION = "v0.2.0"
V2_REQUIRED = ["case.yaml", "network.parquet", "sites.csv", "crosswalk.csv"]
ROAD_CLASSES = ["motorway", "trunk", "primary", "secondary", "tertiary", "minor",
                "service", "cycleway", "footway", "other"]
# Importance order used to break ties when a site has several segments.
CLASS_RANK = {c: i for i, c in enumerate(ROAD_CLASSES)}


def resolve_case_dir(case: str | Path, cases_root: str | Path | None = None,
                     version: str = BENCHMARK_VERSION,
                     from_dir: str | Path | None = None) -> Path:
    """Return the directory of a v0.2 case, fetching missing files first.

    ``case`` is a case id (looked up in ``cases/<id>/``) or a directory path.
    If any required file is missing, :func:`benchmark.fetch.fetch` is called.
    """
    p = Path(case)
    if p.is_absolute() or len(p.parts) > 1:
        root = p
    else:
        root = Path(cases_root or CASES_ROOT) / str(case)
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
    """A loaded v0.2 case. Inputs are read on first use."""

    case_dir: Path
    manifest: dict
    network: "pd.DataFrame"
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
        if m:
            return [x if isinstance(x, str) else x["id"] for x in m]
        return sorted(self.sites["mode"].unique())

    @property
    def crs(self) -> str:
        return str(self.manifest.get("crs") or self.manifest.get("network", {}).get("crs")
                   or self.network.crs)

    def centre_xy(self) -> tuple[float, float]:
        """Case centre in case CRS. Falls back to the network bounds centre."""
        m = self.manifest
        if "centre_x" in m and "centre_y" in m:
            return float(m["centre_x"]), float(m["centre_y"])
        c = m.get("centre", m.get("center"))
        if c is None and "centre_lon" in m:
            c = {"lon": m["centre_lon"], "lat": m["centre_lat"]}
        try:
            if isinstance(c, dict):
                if "x" in c and "y" in c:
                    return float(c["x"]), float(c["y"])
                lon, lat = c.get("lon", c.get("lng")), c.get("lat")
            elif c is not None and len(c) == 2:
                lon, lat = c[0], c[1]
            else:
                raise ValueError
            if abs(float(lon)) <= 180 and abs(float(lat)) <= 90 and self.network.crs is not None \
                    and not self.network.crs.is_geographic:
                from pyproj import Transformer

                t = Transformer.from_crs(4326, self.network.crs, always_xy=True)
                x, y = t.transform(float(lon), float(lat))
                return float(x), float(y)
            return float(lon), float(lat)
        except (TypeError, ValueError):
            minx, miny, maxx, maxy = self.network.total_bounds
            return (minx + maxx) / 2, (miny + maxy) / 2

    def _input(self, name: str, geo: bool = False):
        path = self.case_dir / "inputs" / f"{name}.parquet"
        if not path.exists():
            from benchmark.fetch import fetch

            fetch(self.benchmark_version, self.case_id, self.case_dir.parent,
                  files={f"inputs/{name}.parquet"})
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
        """Road class of each (site_id, mode): the class of its highest-weight segment."""
        net = self.network[["segment_id", "road_class"]].astype({"segment_id": str})
        xw = self.crosswalk.astype({"segment_id": str}).merge(net, on="segment_id", how="left")
        xw["road_class"] = xw["road_class"].fillna("other")
        xw["_rank"] = xw["road_class"].map(CLASS_RANK).fillna(len(CLASS_RANK))
        xw = xw.sort_values(["site_id", "mode", "weight", "_rank"], ascending=[True, True, False, True])
        first = xw.drop_duplicates(["site_id", "mode"])
        return first.set_index(["site_id", "mode"])["road_class"]


def load_case(case: str | Path, cases_root: str | Path | None = None,
                 version: str = BENCHMARK_VERSION, from_dir: str | Path | None = None) -> Case:
    """Load a v0.2 case by id or directory, fetching missing files."""
    import geopandas as gpd

    root = resolve_case_dir(case, cases_root, version, from_dir)
    manifest = yaml.safe_load((root / "case.yaml").read_text())
    network = gpd.read_parquet(root / "network.parquet")
    network["segment_id"] = network["segment_id"].astype(str)
    sites = pd.read_csv(root / "sites.csv", dtype={"site_id": str})
    xw = pd.read_csv(root / "crosswalk.csv", dtype={"site_id": str, "segment_id": str})
    return Case(case_dir=root, manifest=manifest, network=network, sites=sites, crosswalk=xw)
