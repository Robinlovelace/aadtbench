"""Hardware and provenance record for every run (``system.json``).

Every run directory holds a ``system.json`` next to ``run.json``. The
leaderboard only accepts runs that have one. It records the machine (CPU
model, cores, threads, RAM, OS and kernel), the container image digest when
the tool ran in a container, the tool version, the harness commit, the data
release version, and the run's wall time, CPU time and peak memory.

Timings depend on the machine. So each machine also runs a fixed reference
workload once (cached per machine), and every run reports a speed index:

    speed_index = run wall time / reference workload wall time

A speed index of 20 means the run took as long as 20 reference workloads on
the same machine. It is comparable across machines to a first approximation,
the measured seconds are not. Both are reported.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import resource
import time
from pathlib import Path

import numpy as np

REFERENCE_VERSION = "ref-2"
CACHE_DIR = Path(os.environ.get("AADTBENCH_CACHE", Path.home() / ".cache" / "aadtbench"))


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def machine() -> dict:
    """Describe the machine. No host name or user name is recorded."""
    import psutil
    m = {
        "cpu_model": _cpu_model(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "ram_gb": round(psutil.virtual_memory().total / 1024**3, 1),
        "os": platform.platform(terse=True),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "python": platform.python_version(),
    }
    key = json.dumps({k: m[k] for k in ("cpu_model", "cpu_threads", "ram_gb", "arch")}, sort_keys=True)
    m["machine_id"] = hashlib.sha256(key.encode()).hexdigest()[:12]
    return m


def reference_workload() -> float:
    """Run the fixed reference workload once and return its wall time in seconds.

    Shortest paths from 80 sources on a 300 by 300 grid graph plus a least
    squares fit. It uses one thread and the same libraries as the harness.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    rng = np.random.default_rng(0)
    n = 300
    idx = np.arange(n * n).reshape(n, n)
    a = np.r_[idx[:, :-1].ravel(), idx[:-1, :].ravel()]
    b = np.r_[idx[:, 1:].ravel(), idx[1:, :].ravel()]
    w = rng.uniform(1, 2, len(a))
    g = coo_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(n * n, n * n)).tocsr()
    x = rng.normal(size=(20000, 30))
    y = x @ rng.normal(size=30)
    t0 = time.perf_counter()
    dijkstra(g, indices=rng.choice(n * n, 80, replace=False))
    for _ in range(5):
        np.linalg.lstsq(x, y, rcond=None)
    return time.perf_counter() - t0


def reference_seconds(m: dict | None = None) -> float:
    """Median of three reference runs, cached per machine and reference version."""
    m = m or machine()
    f = CACHE_DIR / f"reference_{REFERENCE_VERSION}_{m['machine_id']}.json"
    try:
        return float(json.loads(f.read_text())["seconds"])
    except (OSError, ValueError, KeyError):
        pass
    sec = float(np.median([reference_workload() for _ in range(3)]))
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"seconds": sec, "machine": m}, indent=1) + "\n")
    except OSError:
        pass
    return sec


def cpu_time_s() -> float:
    """User plus system CPU time of this process and its finished children."""
    s, c = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


def write_system(run_dir: Path, *, tool: str, tool_version: str, harness_commit: str,
                 data_release: str, wall_time_s: float, cpu_s: float, peak_memory_mb: float,
                 threads: int | None = None) -> dict:
    """Write ``system.json`` for one run and return it."""
    m = machine()
    ref = reference_seconds(m)
    rec = {
        **m,
        "container_image_digest": os.environ.get("AADTBENCH_IMAGE_DIGEST", "none (host)"),
        "tool": tool, "tool_version": tool_version, "harness_commit": harness_commit,
        "data_release": data_release, "threads": threads,
        "wall_time_s": round(float(wall_time_s), 3), "cpu_time_s": round(float(cpu_s), 3),
        "peak_memory_mb": round(float(peak_memory_mb), 1),
        "reference_version": REFERENCE_VERSION, "reference_s": round(ref, 4),
        "speed_index": round(float(wall_time_s) / ref, 2) if ref > 0 else None,
    }
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    (Path(run_dir) / "system.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return rec
