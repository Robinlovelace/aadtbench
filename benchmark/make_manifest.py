#!/usr/bin/env python3
"""Write manifest-<version>.json and flat release assets for built cases."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from benchmark.fetch import sha256_file


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="build/cases")
    ap.add_argument("--version", default="v0.1.0")
    a = ap.parse_args()
    vdir = Path(a.root) / a.version
    assets = vdir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    entries = []
    for case in sorted(p for p in vdir.iterdir() if p.is_dir() and p.name != "assets"):
        for f in sorted(p for p in case.rglob("*") if p.is_file()):
            rel = f.relative_to(case).as_posix()
            asset = f"{case.name}__{rel.replace('/', '__')}"
            dest = assets / asset
            dest.unlink(missing_ok=True)
            try:
                os.link(f, dest)
            except OSError:
                shutil.copy2(f, dest)
            entries.append({"case": case.name, "file": rel, "asset": asset,
                            "size": f.stat().st_size, "sha256": sha256_file(f)})
    out = vdir / f"manifest-{a.version}.json"
    out.write_text(json.dumps({"version": a.version, "files": entries}, indent=1))
    print(f"{len(entries)} files, {sum(e['size'] for e in entries) / 1e6:.1f} MB, manifest {out}")


if __name__ == "__main__":
    main()
