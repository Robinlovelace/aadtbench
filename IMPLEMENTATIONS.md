# Adding a tool to AADTBench

A tool never sees the counts. Its adapter writes flows. The harness matches,
calibrates and scores them (`BENCHMARK.md`).

## The contract

In: a blind copy of the case (`case.yaml`, `network.parquet`, `inputs/`, no
counts), an input tier, a list of modes, a named variant and a thread count.

Out, in the run directory: `predictions.parquet` (`segment_id`, `mode`,
`flow`, non-negative, any scale, missing rows count as 0) plus `run.json` and
`system.json`. `adapters/_base.py` writes all three. A tool only writes
`predict`.

```python
# adapters/my_tool.py  (module name = tool name)
import pandas as pd
from adapters._base import Adapter, RunContext, directed_to_segments, run_cli


class MyTool(Adapter):
    tool = "my_tool"
    family = "flow"            # reach, flow, assignment, statistical or other
    options = {"distance": "time", "radius_or_decay": "none",
               "weighting": "od", "congestion": "none"}
    tiers = ("T2_synthetic_od", "T3_observed_od")
    modes = ("walking", "cycling", "car", "heavy", "motor")
    variants = {"default": {}}  # fixed before any scoring

    def tool_version(self) -> str:
        import my_tool
        return my_tool.__version__

    def predict(self, ctx: RunContext) -> pd.DataFrame:
        def one_mode(mode):
            edges = ctx.directed_edges(mode)   # segment_id, u, v, length_m, road_class, time_s
            od = ctx.od_nodes(mode)            # o_node, d_node, trips
            flow = my_tool.assign(edges, od, **ctx.params)   # one value per directed edge
            return directed_to_segments(edges, flow, mode)
        return ctx.map_modes(one_mode)        # a mode raising Unsupported is recorded, not fatal


if __name__ == "__main__":
    run_cli(MyTool)
```

`RunContext` gives only what the tier allows: `network`, `directed_edges`,
`node_xy` (T0), `population`, `pois` (T1), `zones`, `od`, `od_nodes` (T2, T3).
Shared defaults for assignment tools: `CLASS_CAPACITY_VPH` and
`PEAK_HOUR_FACTOR` (OD tables are daily trips). Raise `Unsupported` for a tier
or mode the tool cannot handle.

Variants are fixed before scoring and are not chosen by looking at the board.
Tools that need calibration leave it to the calibrated track, or use the
tool-calibrated track: run with `run_all --tool-calibrated`, and in `predict`
call `ctx.training_counts()` for `(sites, crosswalk)` of the training folds of
this call. The harness calls `predict` once per fold. Return calibrated flows.
Each run is killed after `--time-limit` seconds (default 300) and shown as NA.

## Run it

```bash
pip install -r requirements.txt my_tool
python -m benchmark.fetch --version v0.3.0
python -m benchmark.run_all --cases oxford-v1 --tools my_tool --tier T2_synthetic_od
python -m benchmark.smoke --tool my_tool          # what CI runs, on oxford-mini-v1
```

## Add it to CI

1. Copy `containers/cityseer_od/Dockerfile` and its `.dockerignore` to
   `containers/<tool>/`. Install only the pinned tool. The entry point is
   `python -m adapters.<tool>`. The ignore file is an allow list, so case data
   never enters an image.
2. Add a block under `tools` in `config/ci.yaml` (variant, optional overrides).
3. Add the tool to `matrix.tool` in `.github/workflows/smoke.yml`.
4. Add a test in `tests/` that runs the adapter on the synthetic fixture.

CI runs the unit tests, `python -m benchmark.contract_check` (declarations
plus a run on the fixture) and the smoke matrix. Open a pull request with the
adapter and its summary rows.
