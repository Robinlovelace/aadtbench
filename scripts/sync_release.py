#!/usr/bin/env python3
"""Synchronize case bundles, leaderboard CSVs, and manifest-v0.1.0.json with the GitHub release."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.fetch import DEFAULT_VERSION, REPO, asset_name, sha256_file

CASES = [
    "bristol-v1", "leeds-v1", "leuven-v1", "london-v1", "melbourne-v1",
    "oxford-mini-v1", "oxford-v1", "paris-v1", "toronto-v1", "zurich-v1",
]
CASE_FILES = [
    "build_stats.json", "crosswalk.csv",
    "inputs/od_synthetic.parquet", "inputs/pois.parquet",
    "inputs/population.parquet", "inputs/zones.parquet",
    "network.parquet", "network_build.json", "sites.csv", "source.osm.pbf",
]
RESULT_FILES = ["LEADERBOARD.md", "leaderboard.csv", "summary.csv"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default=DEFAULT_VERSION)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="aadtbench-rel-") as tmp_str:
        tmp = Path(tmp_str)
        mname = f"manifest-{args.version}.json"
        subprocess.run(
            ["gh", "release", "download", args.version, "-R", args.repo, "-p", mname, "-D", str(tmp)],
            check=True,
        )
        manifest = json.loads((tmp / mname).read_text())
        existing = {(e["case"], e["file"]): e for e in manifest["files"]}

        to_upload: list[Path] = []
        for c in CASES:
            cdir = Path("cases") / c
            for rf in CASE_FILES:
                p = cdir / rf
                if not p.is_file():
                    continue
                sz, sh = p.stat().st_size, sha256_file(p)
                aname = asset_name(c, rf)
                old = existing.get((c, rf))
                if not old or old.get("sha256") != sh or old.get("size") != sz:
                    dst = tmp / aname
                    shutil.copyfile(p, dst)
                    to_upload.append(dst)
                    existing[(c, rf)] = {"case": c, "file": rf, "asset": aname, "size": sz, "sha256": sh}
                    print(f"[stage] {aname} ({sz} bytes)")

        for rf in RESULT_FILES:
            p = Path("results") / rf
            if not p.is_file():
                continue
            sz, sh = p.stat().st_size, sha256_file(p)
            aname = f"results__{rf}"
            old = existing.get(("results", rf))
            if not old or old.get("sha256") != sh or old.get("size") != sz:
                dst = tmp / aname
                shutil.copyfile(p, dst)
                to_upload.append(dst)
                existing[("results", rf)] = {"case": "results", "file": rf, "asset": aname, "size": sz, "sha256": sh}
                print(f"[stage] {aname} ({sz} bytes)")

        if not to_upload:
            print("All release assets are already in sync.")
            return 0

        new_files = [existing[k] for k in sorted(existing.keys())]
        manifest_out = tmp / mname
        manifest_out.write_text(json.dumps({"version": args.version, "files": new_files}, indent=1) + "\n")
        to_upload.append(manifest_out)

        if args.dry_run:
            print(f"Dry run: would upload {len(to_upload)} assets.")
            return 0

        print(f"Uploading {len(to_upload)} assets to {args.version}...")
        subprocess.run(
            ["gh", "release", "upload", args.version, "-R", args.repo, "--clobber", *[str(x) for x in to_upload]],
            check=True,
        )
        print("Release sync complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
