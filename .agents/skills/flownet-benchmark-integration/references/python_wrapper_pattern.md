# Python wrapper pattern — flownet + sensor validation

Driven from a benchmark `main()` that loops modes. Snaps predicted edge flows to
observed sensor counts and computes R² / Pearson / Spearman.

```python
import os, argparse, subprocess, time
import numpy as np, pandas as pd, geopandas as gpd
from scipy.spatial import cKDTree
from scripts.config import get_path, get_city_config, get_modes, get_mode_config
from scripts.csv_utils import merge_to_csv

BETAS = [0.001, 0.002, 0.004]; DETOURS = [1.25, 1.5]; OD_SAMPLE = 150
R_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_flownet_assignment.R")

# inside main(), per mode:
edges = gpd.read_file(edges_path).to_crs(crs_utm).reset_index(drop=True)
edges.index.name = "edge_idx"
tel = gpd.read_file(sensors_path).to_crs(crs_utm)
tel_val = tel[sensors_value].values.astype(float)
tel_xy = np.array([(g.x, g.y) for g in tel.geometry])

ec = np.array([(g.x, g.y) for g in edges.geometry.centroid])
e_tree = cKDTree(ec)
e_d, e_i = e_tree.query(tel_xy)
e_m = e_d <= MATCH_DIST                       # e.g. 200 m
e_match = int(sum(e_m))

for beta in BETAS:
    for detour in DETOURS:
        variant = f"psl_beta{beta}_detour{detour}"
        flows_csv = os.path.join(RESULTS_DIR, f"_flownet_{city}_{mode}_{variant}.csv")  # UNIQUE name
        cmd = ["Rscript", R_SCRIPT, edges_path, origins_p, dests_p,
               ".length", str(beta), str(detour), flows_csv, mode, str(OD_SAMPLE)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if proc.returncode != 0:
            print(f"  {variant}: R ERROR -> {proc.stderr[:300]}"); continue
        if not os.path.exists(flows_csv):
            continue
        fl = pd.read_csv(flows_csv)
        flow_map = dict(zip(fl["edge_idx"].astype(int), fl["flow"]))
        pred = edges.index.map(lambda i: flow_map.get(int(i), np.nan)).values.astype(float)
        pred_matched = pred[e_i[e_m]]
        obs = tel_val[e_m]
        mask = ~(np.isnan(obs) | np.isnan(pred_matched))
        n = int(mask.sum())
        if n < 3 or np.all(pred_matched[mask] == pred_matched[mask][0]):
            r2 = pr = sr = np.nan
        else:
            from scipy import stats
            r2 = stats.linregress(pred_matched[mask], obs[mask]).rvalue ** 2
            pr, _ = stats.pearsonr(pred_matched[mask], obs[mask])
            sr, _ = stats.spearmanr(pred_matched[mask], obs[mask])
        all_rows.append({"tool": "flownet", "mode": mode, "variant": variant,
                          "r_squared": float(r2), "pearson_r": float(pr), "spearman_r": float(sr),
                          "n_matched": e_match, "n_obs": n, ...})
        os.remove(flows_csv)   # clean unique temp
```

Notes:
- `edges.index` (0-based, after `reset_index`) must equal the R `edge_idx` (0-based,
  `seq_len(nrow(net)) - 1`). This requires the DIRECTED graph in the R script so
  `nrow(gr)==nrow(net)`.
- `merge_to_csv("flownet", df, f"results/{city}_flownet_results.csv")` dedups on
  (tool, mode, variant).
- `mode` column is required by the combined-results schema (see `csv_utils.CSV_COLUMNS`).
