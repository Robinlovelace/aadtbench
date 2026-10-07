#!/usr/bin/env python3
"""Write manifest-<version>.json and flat release assets for built cases.

Walks <root>/<version>/<case_id>/ and lists every file with case, file, size
and sha256. Each file is also placed in <root>/<version>/assets/ as
`<case_id>__<relative path with / replaced by __>` (hard link, or copy if that
fails), ready to upload to the GitHub release for the version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

DEFAULT_ROOT = "build/cases"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--version", default="v0.2.0", help="directory name under root, also the release tag")
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
            if dest.exists():
                dest.unlink()
            try:
                os.link(f, dest)
            except OSError:
                shutil.copy2(f, dest)
            entries.append({"case": case.name, "file": rel, "asset": asset,
                            "size": f.stat().st_size, "sha256": sha256(f)})
    manifest = {"version": a.version, "files": entries}
    out = vdir / f"manifest-{a.version}.json"
    out.write_text(json.dumps(manifest, indent=1))
    total = sum(e["size"] for e in entries)
    print(f"{len(entries)} files, {total / 1e6:.1f} MB, manifest {out}")


if __name__ == "__main__":
    main()
