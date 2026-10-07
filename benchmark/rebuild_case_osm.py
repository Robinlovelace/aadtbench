#!/usr/bin/env python3
"""Build a case version on the raw OSM network (benchmark v0.3).

Sites, folds and inputs (population, POIs, zones, OD) do not depend on the
network. They are taken from the previous release (v0.2.0, built by the export
scripts at that tag) and filtered by the licence table. The network is built
from a dated Geofabrik extract by ``benchmark/build_osm_network.py`` and the
crosswalk is re-run with the documented rules. ``case.yaml`` and the case
README are rewritten.

Usage:
  OSMIUM="pixi exec --spec osmium-tool osmium" PYTHONPATH=. \\
  python benchmark/rebuild_case_osm.py --case oxford-v1 \\
      --source <geofabrik extract .osm.pbf> --out build/cases/v0.3.0/oxford-v1
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml

from benchmark.crosswalk import build_crosswalk
from benchmark.fetch import fetch
from benchmark.licences import NON_COMMERCIAL_SOURCES, REVIEWED_SOURCES, reviewed_licence

BENCHMARK_VERSION = "0.3.0"
PREVIOUS_RELEASE = "v0.2.0"
# Per-source crosswalk rules. Sources not listed are point counts at 30 m.
SOURCE_RULES = {"telraam": {"kind": "point", "radius_m": 50.0}, "toronto_tmc": {"kind": "junction"}}
PAIR_SENSOR_M = 30.0
# Sources that report one direction per sensor. Published two-way counts (DfT
# AADF) and footpath counters are not paired.
DIRECTIONAL_SOURCES = {"oxflow", "vic_dtp_aadt", "stadt_zuerich_miv", "stadt_zuerich_fuss_velo",
                       "toronto_svc", "toronto_bike"}


def pair_directional(sites: pd.DataFrame, radius: float = PAIR_SENSOR_M) -> pd.DataFrame:
    """Sum opposite-direction sensors into one two-way site.

    For sources in ``DIRECTIONAL_SOURCES``, two sites of the same source and mode that are each other's nearest
    neighbour within ``radius`` m are one location counted per direction. They
    become one site: values summed, ids joined with ``+``, position averaged,
    group and fold of the first. Other sources and junction arms are left alone.
    """
    from scipy.spatial import cKDTree
    arm = sites["bearing"].notna() if "bearing" in sites else pd.Series(False, index=sites.index)
    arm |= ~sites["source"].isin(DIRECTIONAL_SOURCES)
    out, done = [], set()
    for _, g in sites[~arm].groupby(["source", "mode"]):
        if len(g) < 2:
            out.append(g)
            continue
        d, j = cKDTree(g[["x", "y"]].values).query(g[["x", "y"]].values, k=2)
        own = np.arange(len(g))
        self_first = j[:, 0] == own  # with ties at distance 0 the point itself may come second
        nn = np.where(self_first, j[:, 1], j[:, 0])
        dist = np.where(self_first, d[:, 1], d[:, 0])
        rows = []
        for i in range(len(g)):
            k = nn[i]
            if i in done:
                continue
            if dist[i] <= radius and nn[k] == i and k not in done:
                a, b = g.iloc[i].copy(), g.iloc[k]
                a["site_id"] = f"{a.site_id}+{b.site_id}"
                a["value"] = a["value"] + b["value"]
                a["x"], a["y"] = (a.x + b.x) / 2, (a.y + b.y) / 2
                a["lon"], a["lat"] = (a.lon + b.lon) / 2, (a.lat + b.lat) / 2
                a["n_days"] = min(a.n_days, b.n_days)
                rows.append(a)
                done.update((i, k))
            else:
                rows.append(g.iloc[i])
        done.clear()
        out.append(pd.DataFrame(rows))
    return pd.concat(out + [sites[arm]], ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a case on the raw OSM network")
    ap.add_argument("--case", required=True, help="case id (cases/<id>/case.yaml is rewritten)")
    ap.add_argument("--source", type=Path, help="dated Geofabrik extract (.osm.pbf)")
    ap.add_argument("--clipped", type=Path, help="existing clipped source.osm.pbf")
    ap.add_argument("--out", required=True, type=Path, help="case data dir")
    ap.add_argument("--sites-from", type=Path, help="dir with sites.csv and inputs/ (default: previous release)")
    a = ap.parse_args()

    case_dir = Path("cases") / a.case
    cfg = yaml.safe_load((case_dir / "case.yaml").read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "benchmark/build_osm_network.py", "--case", str(case_dir), "--out", str(a.out)]
    cmd += ["--clipped", str(a.clipped)] if a.clipped else ["--source", str(a.source)]
    subprocess.run(cmd, check=True)
    build = json.loads((a.out / "network_build.json").read_text())

    # Sites and inputs from the previous release. Licences from the reviewed table only.
    allowed = dict(REVIEWED_SOURCES)
    if cfg.get("licence_class") == "non_commercial":
        allowed.update(NON_COMMERCIAL_SOURCES)
    with tempfile.TemporaryDirectory() as tmp:
        if a.sites_from:
            prev = a.sites_from
        else:
            fetch(PREVIOUS_RELEASE, a.case, tmp)
            prev = Path(tmp) / a.case
        sites = pd.read_csv(prev / "sites.csv", dtype={"site_id": str})
        if prev.resolve() != a.out.resolve():
            if (a.out / "inputs").exists():
                shutil.rmtree(a.out / "inputs")
            shutil.copytree(prev / "inputs", a.out / "inputs")
    n_before = sites.groupby("mode").size().to_dict()
    sites = pair_directional(sites)
    keep = sites["source"].isin(allowed)
    dropped = {f"{s} {m}": int(n) for (s, m), n in sites[~keep].groupby(["source", "mode"]).size().items()}
    sites = sites[keep].copy()
    sites["licence"] = sites["source"].map(lambda s: allowed[s]["licence"])
    sites.to_csv(a.out / "sites.csv", index=False)

    net = gpd.read_parquet(a.out / "network.parquet")
    cw = build_crosswalk(net, sites, SOURCE_RULES)
    cw.to_csv(a.out / "crosswalk.csv", index=False)
    n_sites = sites.groupby("mode").size().to_dict()
    matched = cw[cw.rule != "pair"].groupby("mode").size().to_dict()
    pairs = cw[cw.rule == "pair"].groupby("mode").size().to_dict()
    (a.out / "build_stats.json").write_text(json.dumps(
        {"network": build, "sites_before_pairing": n_before, "sites": n_sites, "matched": matched, "pair_rows": pairs, "dropped": dropped}, indent=1) + "\n")

    major = int(str(cfg["version"]).split(".")[0])
    cfg["version"] = f"{major + 1}.0.0"
    cfg["benchmark_version"] = BENCHMARK_VERSION
    cfg["modes"] = [m for m in cfg["modes"] if n_sites.get(m)]
    srcs = sorted(sites["source"].unique())
    cfg["sources"] = [{"source": s, "licence": allowed[s]["licence"], "url": allowed[s]["url"],
                       "reviewed": allowed[s]["reviewed"], "n_rows": int((sites.source == s).sum())} for s in srcs]
    cfg["excluded_sources"] = {s: reviewed_licence(s)[1] for s in sorted({k.split()[0] for k in dropped})}
    cfg["network"] = {k: build.get(k) for k in ("source_extract", "source_timestamp", "clipped_sha256",
                                                "links", "km", "components", "largest_component_share")}
    cfg["network"]["build"] = "benchmark/build_osm_network.py: raw OSM, split at shared nodes, no cleaning"
    for k in ("network_build", "legacy_v01", "legacy_v01_files", "excluded"):
        cfg.pop(k, None)
    files = sorted(str(p.relative_to(a.out)) for p in a.out.rglob("*")
                   if p.is_file() and p.name not in ("build_stats.json", "network_build.json"))
    cfg["files"] = files
    cfg["data_size_bytes"] = int(sum((a.out / f).stat().st_size for f in files))
    (case_dir / "case.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))

    rows = "\n".join(f"| {m} | {n_sites[m]} | {matched.get(m, 0)} | {pairs.get(m, 0)} |" for m in cfg["modes"])
    lic = "\n".join(f"- `{s['source']}`: {s['licence']} ({s['url']})" for s in cfg["sources"])
    exc = "\n".join(f"- `{s}`: {r}" for s, r in cfg["excluded_sources"].items()) or "- none"
    note = ("\n**Non-commercial case.** " + cfg.get("attribution", "") + "\n") if cfg.get("licence_class") == "non_commercial" else ""
    (case_dir / "README.md").write_text(f"""# {a.case} (case version {cfg['version']}, benchmark v{BENCHMARK_VERSION})

{cfg.get('title', '')}. Centre {cfg['centre_lon']}, {cfg['centre_lat']}, radius {cfg['radius_m']:.0f} m{', margin ' + str(int(cfg['margin_m'])) + ' m' if cfg.get('margin_m') else ''}, {cfg['crs']}.
Data files are assets of release v{BENCHMARK_VERSION} (`python -m benchmark.fetch --version v{BENCHMARK_VERSION} --case {a.case}`).
{note}
## Network

Raw OpenStreetMap (ODbL), built by `benchmark/build_osm_network.py` from
`{build.get('source_extract')}` (OSM timestamp {build.get('source_timestamp')}). Ways with a routable
`highway` tag, split at shared nodes, no cleaning. The clipped highway extract is
published as `source.osm.pbf` (sha256 `{build.get('clipped_sha256')}`).
{build['links']} links, {build['km']} km, {build['components']} components (largest holds
{100 * build['largest_component_share']:.1f} percent of links). `segment_id` is `<osm way id>-<k>`.

## Counts

| Mode | Sites | Matched | Dual carriageway partner rows |
|---|---|---|---|
{rows}

Sources (licences from `benchmark/licences.py`):

{lic}

Excluded:

{exc}

Sites, folds and inputs (WorldPop CC BY 4.0, OSM POIs ODbL, zones, synthetic OD)
are unchanged from release {PREVIOUS_RELEASE}. Rebuild:
`python benchmark/rebuild_case_osm.py --case {a.case} --source <extract> --out <dir>`.
""")
    print(json.dumps({"case": a.case, "sites_before_pairing": n_before, "sites": n_sites, "matched": matched, "pairs": pairs, "dropped": dropped,
                      "links": build["links"], "components": build["components"]}))


if __name__ == "__main__":
    main()
