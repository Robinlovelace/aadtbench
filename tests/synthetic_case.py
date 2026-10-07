"""A tiny synthetic v0.2 case for tests: a 10 by 10 grid network."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from shapely.geometry import LineString

X0, Y0, STEP, N = 400000.0, 400000.0, 500.0, 10


def build_case(root: Path, case_id: str = "synth-v1", seed: int = 1) -> Path:
    rng = np.random.RandomState(seed)
    root = Path(root) / case_id
    (root / "inputs").mkdir(parents=True, exist_ok=True)
    rows = []
    k = 0
    for i in range(N):
        for j in range(N):
            for di, dj in ((1, 0), (0, 1)):
                if i + di < N and j + dj < N:
                    a = (X0 + i * STEP, Y0 + j * STEP)
                    b = (X0 + (i + di) * STEP, Y0 + (j + dj) * STEP)
                    line = i if dj else j  # index of the street
                    cls = "primary" if line % 3 == 0 else ("service" if line == 7 else "minor")
                    rows.append(dict(segment_id=f"s{k:03d}", u=i * N + j, v=(i + di) * N + j + dj,
                                     length_m=STEP, road_class=cls, highway=cls, name="",
                                     allow_walking=True, allow_cycling=True, allow_car=True,
                                     allow_heavy=cls == "primary", dir_car="both", dir_cycling="both",
                                     pair_segment="", geometry=LineString([a, b])))
                    k += 1
    # a dual carriageway pair
    a = (X0 + 250, Y0 + 4750.0)
    b = (X0 + 750, Y0 + 4750.0)
    # own end nodes, so that node ids agree with the geometry (cityseer checks this)
    rows.append(dict(rows[0], segment_id="pairA", pair_segment="pairB", road_class="primary",
                     highway="primary", allow_heavy=True, u=1000, v=1001,
                     geometry=LineString([a, b])))
    rows.append(dict(rows[0], segment_id="pairB", pair_segment="pairA", road_class="primary",
                     highway="primary", allow_heavy=True, u=1002, v=1003,
                     geometry=LineString([(a[0], a[1] + 10), (b[0], b[1] + 10)])))
    net = gpd.GeoDataFrame(rows, crs=27700)
    net.to_parquet(root / "network.parquet")

    # true model: counts depend on class and distance to the centre
    cx, cy = X0 + 2250, Y0 + 2250
    mid = np.array([[g.interpolate(0.5, normalized=True).x, g.interpolate(0.5, normalized=True).y]
                    for g in net.geometry])
    dist = np.hypot(mid[:, 0] - cx, mid[:, 1] - cy)
    cls_eff = net["road_class"].map({"primary": 1.5, "minor": 0.0, "service": -0.5}).values
    true = np.exp(6 + cls_eff - 0.0004 * dist + rng.normal(0, 0.2, len(net)))

    site_rows, xw_rows = [], []
    for mode, n in (("car", 70), ("walking", 50)):
        pick = rng.choice(len(net), n, replace=False)
        if mode == "car":
            pick = np.unique(np.append(pick, len(net) - 2))  # include the pair
        for sid, idx in enumerate(pick):
            seg = net.iloc[idx]
            x, y = mid[idx]
            site = f"{mode[0]}{sid:03d}"
            val = true[idx] * (1 if mode == "car" else 0.4)
            site_rows.append(dict(site_id=site, mode=mode, value=val, source="synthetic",
                                  licence="CC0", method="continuous", n_days=365, x=x, y=y,
                                  lon=0.0, lat=0.0))
            segs = [seg["segment_id"]]
            if seg["pair_segment"]:
                segs.append(seg["pair_segment"])
            for sg in segs:
                xw_rows.append(dict(site_id=site, mode=mode, segment_id=sg, weight=1.0,
                                    dist_m=5.0, rule="point"))
    sites = pd.DataFrame(site_rows)
    gx = ((sites["x"] - X0) // 3000).astype(int)
    gy = ((sites["y"] - Y0) // 3000).astype(int)
    sites["group_id"] = gx.astype(str) + "_" + gy.astype(str)
    groups = np.sort(sites["group_id"].unique())
    order = np.random.RandomState(42).permutation(groups)
    fold_of = {g: i % 5 for i, g in enumerate(order)}
    sites["fold"] = sites["group_id"].map(fold_of)
    sites.to_csv(root / "sites.csv", index=False)
    pd.DataFrame(xw_rows).to_csv(root / "crosswalk.csv", index=False)

    pois = pd.DataFrame({"x": X0 + rng.uniform(0, 4500, 300), "y": Y0 + rng.uniform(0, 4500, 300),
                         "weight": rng.uniform(1, 5, 300), "type": "shop"})
    pois.to_parquet(root / "inputs" / "pois.parquet")
    pop = pd.DataFrame({"x": X0 + rng.uniform(0, 4500, 500), "y": Y0 + rng.uniform(0, 4500, 500),
                        "weight": rng.uniform(1, 50, 500)})
    pop.to_parquet(root / "inputs" / "population.parquet")
    manifest = {"id": case_id, "version": "1.0.0", "benchmark_version": "0.2.0", "crs": "EPSG:27700",
                "centre_x": cx, "centre_y": cy, "modes": ["car", "walking"],
                "input_tiers": ["T0_network", "T1_open_covariates"]}
    (root / "case.yaml").write_text(yaml.safe_dump(manifest))
    return root


def write_release(case_dirs: list[Path], mirror: Path, version: str = "v0.2.0") -> Path:
    """Write a local mirror of release assets with a manifest."""
    mirror.mkdir(parents=True, exist_ok=True)
    entries = []
    for cd in case_dirs:
        for f in sorted(p for p in cd.rglob("*") if p.is_file()):
            rel = f.relative_to(cd).as_posix()
            name = f"{cd.name}__{rel.replace('/', '__')}"
            data = f.read_bytes()
            (mirror / name).write_bytes(data)
            entries.append({"case": cd.name, "file": rel, "size": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
    (mirror / f"manifest-{version}.json").write_text(json.dumps(entries))
    return mirror
