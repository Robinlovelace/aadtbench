"""Check that every adapter in ``adapters/`` follows the v0.2 contract.

    python -m benchmark.contract_check

For each adapter module (names starting with ``_`` are
skipped) the check requires:

* one ``Adapter`` subclass with ``tool`` (equal to the module name), a
  ``family`` in ``FAMILIES``, ``options`` with every key of ``OPTION_KEYS``,
  non-empty ``tiers`` and ``modes`` drawn from the known sets, and at least one
  variant,
* a ``run_cli`` entry point (``if __name__ == "__main__"`` block).

If the adapter's dependencies import, it is also run on the synthetic fixture
(``tests/synthetic_case.py``, with a small zone grid and OD table added) at
its lowest supported tier. The run must write valid predictions. An adapter
whose dependencies are not installed is reported as skipped, not failed.
Exit code is 0 when no adapter fails.
"""
from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import adapters
from adapters._base import (FAMILIES, MODES, OPTION_KEYS, PREDICTION_COLUMNS, TIERS, Adapter,
                            run_adapter, validate_predictions)

REPO = Path(__file__).resolve().parents[1]
SKIP: set[str] = set()


def adapter_names() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(adapters.__path__)
                  if m.name not in SKIP and not m.name.startswith("_"))


def static_problems(name: str, cls: type) -> list[str]:
    """Declaration problems of an adapter class."""
    out = []
    if cls.tool in ("", "unnamed") or cls.tool != name:
        out.append(f"tool is '{cls.tool}', expected '{name}'")
    if cls.family not in FAMILIES:
        out.append(f"family '{cls.family}' is not one of {FAMILIES}")
    missing = [k for k in OPTION_KEYS if k not in cls.options]
    if missing:
        out.append(f"options lacks {missing}")
    if not cls.tiers or set(cls.tiers) - set(TIERS):
        out.append(f"tiers {cls.tiers} must be a non-empty subset of {TIERS}")
    if not cls.modes or set(cls.modes) - set(MODES):
        out.append(f"modes {cls.modes} must be a non-empty subset of {MODES}")
    if not cls.variants:
        out.append("no variants declared")
    src = (REPO / "adapters" / f"{name}.py").read_text()
    if "run_cli(" not in src or "__main__" not in src:
        out.append("no run_cli entry point under __main__")
    try:
        ast.parse(src)
    except SyntaxError as exc:
        out.append(f"syntax error: {exc}")
    return out


def add_od_inputs(case_dir: Path) -> None:
    """Add a 3 by 3 zone grid and an OD table to the synthetic fixture (T2 inputs)."""
    import geopandas as gpd
    from shapely.geometry import box
    from tests.synthetic_case import N, STEP, X0, Y0
    n, side = 3, N * STEP / 3
    zones = gpd.GeoDataFrame(
        {"zone_id": [f"z{i}{j}" for i in range(n) for j in range(n)]},
        geometry=[box(X0 + i * side - STEP / 2, Y0 + j * side - STEP / 2,
                      X0 + (i + 1) * side - STEP / 2, Y0 + (j + 1) * side - STEP / 2)
                  for i in range(n) for j in range(n)], crs=27700)
    zones.to_parquet(case_dir / "inputs" / "zones.parquet")
    ids = zones["zone_id"].tolist()
    rng = np.random.RandomState(0)
    od = pd.DataFrame([(o, d, m, float(rng.randint(10, 200))) for o in ids for d in ids if o != d
                       for m in ("car", "walking")], columns=["o_zone", "d_zone", "mode", "trips"])
    od.to_parquet(case_dir / "inputs" / "od_synthetic.parquet")
    od.to_parquet(case_dir / "inputs" / "od_observed.parquet")


def run_fixture(cls: type, case_dir: Path, out_dir: Path) -> tuple[str, str]:
    """Run an adapter on the fixture. Returns (status, message)."""
    tier = min(cls.tiers, key=TIERS.index)
    modes = [m for m in ("car", "walking") if m in cls.modes]
    if not modes:
        return "skipped", "adapter supports neither fixture mode"
    rec = run_adapter(cls(), case_dir, tier, modes, out_dir)
    if rec["status"] == "unsupported":
        return "skipped", f"unsupported on the fixture: {rec.get('message', '')[:120]}"
    pred = pd.read_parquet(out_dir / "predictions.parquet")
    net = pd.read_parquet(case_dir / "network.parquet", columns=["segment_id"])
    pred = validate_predictions(pred, net["segment_id"].values)
    if list(pred.columns) != PREDICTION_COLUMNS or pred.empty:
        return "failed", "predictions are empty or have the wrong columns"
    if not (out_dir / "run.json").exists():
        return "failed", "run.json missing"
    return "ok", f"{len(pred)} predictions at {tier}"


def check_all(verbose: bool = True) -> dict[str, tuple[str, str]]:
    """Return {adapter: (status, message)}. Status is ok, skipped or failed."""
    from tests.synthetic_case import build_case
    results: dict[str, tuple[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="aadtbench-contract-") as tmp:
        case_dir = build_case(Path(tmp))
        add_od_inputs(case_dir)
        for name in adapter_names():
            try:
                mod = importlib.import_module(f"adapters.{name}")
            except ImportError as exc:
                results[name] = ("skipped", f"dependencies missing: {exc}")
                continue
            classes = [v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Adapter)
                       and v is not Adapter and v.__module__ == mod.__name__]
            if len(classes) != 1:
                results[name] = ("failed", f"expected one Adapter subclass, found {len(classes)}")
                continue
            problems = static_problems(name, classes[0])
            if problems:
                results[name] = ("failed", "; ".join(problems))
                continue
            try:
                results[name] = run_fixture(classes[0], case_dir, Path(tmp) / "runs" / name)
            except ImportError as exc:
                results[name] = ("skipped", f"tool dependencies missing: {exc}")
            except Exception as exc:
                results[name] = ("failed", f"{type(exc).__name__}: {exc}")
    if verbose:
        for name, (status, msg) in results.items():
            print(f"{status:8s} {name}: {msg}")
    return results


def main() -> int:
    results = check_all()
    failed = [n for n, (s, _) in results.items() if s == "failed"]
    if failed:
        print(f"contract check failed for {failed}")
        return 1
    print("contract check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
