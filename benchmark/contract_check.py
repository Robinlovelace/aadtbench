"""Check that every adapter in ``adapters/`` follows the contract."""
from __future__ import annotations

import ast
import importlib
import pkgutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

import adapters
from adapters._base import (FAMILIES, MODES, OPTION_KEYS, PREDICTION_COLUMNS, TIERS, Adapter,
                            run_adapter, validate_predictions)

REPO = Path(__file__).resolve().parents[1]


def adapter_names() -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(adapters.__path__) if not m.name.startswith("_"))


def static_problems(name: str, cls: type) -> list[str]:
    out = []
    if cls.tool != name:
        out.append(f"tool is '{cls.tool}', expected '{name}'")
    if cls.family not in FAMILIES:
        out.append(f"family '{cls.family}' not in {FAMILIES}")
    missing_opts = set(OPTION_KEYS) - set(cls.options or {})
    if missing_opts:
        out.append(f"options missing keys {sorted(missing_opts)}")
    if not cls.tiers or not set(cls.tiers) <= set(TIERS):
        out.append(f"invalid tiers {cls.tiers}")
    if not cls.modes or not set(cls.modes) <= set(MODES):
        out.append(f"invalid modes {cls.modes}")
    if not cls.variants:
        out.append("variants is empty")
    tree = ast.parse((REPO / "adapters" / f"{name}.py").read_text())
    if not any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "run_cli" for n in ast.walk(tree)):
        out.append("no run_cli(...) call found")
    return out


def check_all(verbose: bool = True) -> dict[str, tuple[str, str]]:
    from tests.synthetic_case import build_case
    results: dict[str, tuple[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="aadtbench-contract-") as tmp:
        case_dir = build_case(Path(tmp))
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
                tier = classes[0].tiers[0]
                out = Path(tmp) / "runs" / name
                rec = run_adapter(classes[0](), case_dir, tier, ["car", "walking"], out)
                if rec.get("status") != "complete":
                    results[name] = ("failed", f"status={rec.get('status')}: {rec.get('message', '')}")
                else:
                    pred = validate_predictions(pd.read_parquet(out / "predictions.parquet"))
                    results[name] = ("ok", f"{len(pred)} predictions at {tier}")
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
