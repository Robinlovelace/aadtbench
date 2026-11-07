"""Download AADTBench case data from a GitHub release and verify checksums."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = "Robinlovelace/aadtbench"
DEFAULT_VERSION = "v0.1.0"
CASES_ROOT = Path(__file__).resolve().parents[1] / "cases"


class FetchError(RuntimeError):
    """A download or integrity failure."""


def asset_name(case: str, rel: str) -> str:
    return f"{case}__{rel.replace('/', '__')}"


def manifest_name(version: str) -> str:
    return f"manifest-{version}.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_file(path: Path, entry: dict) -> bool:
    return path.is_file() and path.stat().st_size == int(entry["size"]) and sha256_file(path) == entry["sha256"]


def read_manifest(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):
        data = data.get("files", [])
    for e in data:
        for key in ("case", "file", "size", "sha256"):
            if key not in e:
                raise FetchError(f"manifest entry lacks '{key}': {e}")
    return data


def _get_asset(name: str, dest_dir: Path, version: str, from_dir: Path | None, repo: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / name
    if from_dir is not None:
        src = next((q for q in (Path(from_dir) / name, Path(from_dir) / "assets" / name) if q.is_file()),
                   Path(from_dir) / name)
        if not src.is_file():
            raise FetchError(f"asset not found in mirror: {src}")
        shutil.copyfile(src, out)
        return out
    if shutil.which("gh"):
        res = subprocess.run(["gh", "release", "download", version, "-R", repo, "-p", name,
                              "-D", str(dest_dir), "--clobber"], capture_output=True, text=True)
        if res.returncode == 0 and out.is_file():
            return out
        err = res.stderr.strip()[:300]
    else:
        err = "gh not installed"
    url = f"https://github.com/{repo}/releases/download/{version}/{name}"
    try:
        with urllib.request.urlopen(url, timeout=120) as r, open(out, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as exc:
        raise FetchError(f"download failed for {name} ({err}; {url}: {exc})") from exc
    return out


def fetch_result(name: str, version: str = DEFAULT_VERSION, dest: Path | str = "results",
                 repo: str = REPO) -> Path:
    out = Path(dest) / name
    if not out.exists():
        with tempfile.TemporaryDirectory() as tmp:
            got = fetch(version, "results", tmp, repo=repo, files={name})[0]
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(got), str(out))
    return out


def fetch(version: str = DEFAULT_VERSION, case: str | None = None,
          cases_root: Path | str | None = None, from_dir: Path | str | None = None,
          repo: str = REPO, files: set[str] | None = None) -> list[Path]:
    root = Path(cases_root) if cases_root else CASES_ROOT
    from_dir = Path(from_dir) if from_dir else None
    with tempfile.TemporaryDirectory(prefix="aadtbench-fetch-") as tmp:
        tmp = Path(tmp)
        entries = read_manifest(_get_asset(manifest_name(version), tmp, version, from_dir, repo))
        entries = [e for e in entries if (e["case"] == case if case else e["case"] != "results")]
        if not entries:
            raise FetchError(f"case {case} not in manifest {version}")
        if files:
            entries = [e for e in entries if e["file"] in files]
        done: list[Path] = []
        for e in entries:
            dest = root / e["case"] / e["file"]
            if check_file(dest, e):
                done.append(dest)
                continue
            got = _get_asset(e.get("asset") or asset_name(e["case"], e["file"]), tmp / "dl", version, from_dir, repo)
            if not check_file(got, e):
                actual = sha256_file(got)[:12]
                got.unlink()
                raise FetchError(f"checksum mismatch for {e['case']}/{e['file']} "
                                 f"(expected {e['sha256'][:12]}..., got {actual}...)")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(got), str(dest))
            done.append(dest)
    return done


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Download AADTBench case data.")
    p.add_argument("--version", default=DEFAULT_VERSION)
    p.add_argument("--case", default=None)
    p.add_argument("--from-dir", default=None)
    p.add_argument("--cases-root", default=None)
    p.add_argument("--repo", default=REPO)
    a = p.parse_args(argv)
    try:
        got = fetch(a.version, a.case, a.cases_root, a.from_dir, a.repo)
    except FetchError as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1
    print(f"verified {len(got)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
