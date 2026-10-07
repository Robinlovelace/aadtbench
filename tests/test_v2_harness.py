"""Tests for the v0.2 harness: calibrator, scoring, fetch and run_all."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from benchmark import baselines as bl
from benchmark.calibrator import fit_calibrator, fit_scale_factor
from benchmark.case import BENCHMARK_VERSION, load_case
from benchmark.fetch import FetchError, fetch
from benchmark.scoring import group_out_pooled, leave_one_city_out, site_table
from tests.synthetic_case import build_case, write_release


class CalibratorTest(unittest.TestCase):
    def test_recovers_coefficients(self):
        rng = np.random.RandomState(0)
        n = 4000
        flow = rng.uniform(1, 1000, n)
        cls = rng.choice(["a", "b", "c"], n)
        eff = {"a": 0.0, "b": 0.7, "c": -0.4}
        y = 1.0 + 0.6 * np.log1p(flow) + np.array([eff[c] for c in cls]) + rng.normal(0, 0.1, n)
        cal = fit_calibrator(flow, cls, np.expm1(y))
        self.assertAlmostEqual(cal.slope, 0.6, places=2)
        d = cal.class_effects
        ref = cal.coefficients()["reference_class"]
        for c in "abc":
            self.assertAlmostEqual(d[c] - d[ref], eff[c] - eff[ref], places=1)

    def test_smearing_is_mean_exp_residual(self):
        rng = np.random.RandomState(1)
        flow = rng.uniform(1, 100, 500)
        cls = np.array(["a"] * 500)
        y = 2 + 0.5 * np.log1p(flow) + rng.normal(0, 0.5, 500)
        cal = fit_calibrator(flow, cls, np.expm1(y))
        self.assertGreater(cal.smearing, 1.0)
        self.assertAlmostEqual(cal.smearing, np.exp(0.5**2 / 2), delta=0.08)
        # mean prediction is close to the mean count on the training data
        self.assertAlmostEqual(cal.predict(flow, cls).mean() / np.expm1(y).mean(), 1.0, delta=0.1)

    def test_rare_classes_merge_into_other(self):
        flow = np.arange(1, 31, dtype=float)
        cls = np.array(["a"] * 20 + ["b"] * 6 + ["rare"] * 4)
        cal = fit_calibrator(flow, cls, flow * 10)
        self.assertEqual(cal.merged_classes, ["rare"])
        # Four sites in "other" is still under five, so they join the reference class "a".
        self.assertNotIn("other", cal.class_effects)
        self.assertEqual(cal.coefficients()["reference_class"], "a")
        self.assertEqual(len(cal.predict([5.0], ["never_seen"])), 1)
        # Two rare classes of three make an "other" of six, which keeps its own effect.
        cls5 = np.array(["a"] * 18 + ["b"] * 6 + ["r1"] * 3 + ["r2"] * 3)
        self.assertIn("other", fit_calibrator(flow, cls5, flow * 10).class_effects)

    def test_class_only_has_no_slope(self):
        cal = fit_calibrator(np.ones(20), ["a"] * 10 + ["b"] * 10, np.r_[np.ones(10) * 10, np.ones(10) * 100],
                             covariate=False)
        self.assertIsNone(cal.slope)
        p = cal.predict([1.0, 1.0], ["a", "b"])
        self.assertLess(p[0], p[1])

    def test_scale_factor_zero_rule(self):
        sf = fit_scale_factor([0.0, 10.0, 20.0], [5.0, 100.0, 200.0])
        self.assertAlmostEqual(sf.factor, 10.0)
        self.assertEqual(sf.predict([0.0])[0], 0.0)
        self.assertEqual(fit_scale_factor([0.0], [5.0]).factor, 1.0)


class ScoringTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.case = load_case(build_case(self.tmp))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _table(self, flow_fn=lambda f: f, mode="car"):
        pred = bl.baseline_predictions(self.case, "attractor_density", [mode])
        pred["flow"] = flow_fn(pred["flow"])
        t, info = site_table(self.case.sites, self.case.crosswalk, pred, mode, self.case.site_road_class())
        return t, pred, info

    def test_pair_summing(self):
        pred = pd.DataFrame({"segment_id": ["pairA", "pairB"], "mode": "car", "flow": [100.0, 250.0]})
        t, info = site_table(self.case.sites, self.case.crosswalk, pred, "car", self.case.site_road_class())
        pair_sites = self.case.crosswalk.groupby("site_id").size()
        sid = pair_sites[pair_sites == 2].index[0]
        self.assertEqual(float(t.set_index("site_id").loc[sid, "flow"]), 350.0)

    def test_no_leak_across_folds(self):
        t, _, _ = self._table()
        for track in ("calibrated", "raw"):
            _, base, _ = group_out_pooled(t, track)
            i = 3
            t2 = t.copy()
            t2.loc[i, "value"] = t2.loc[i, "value"] * 50 + 1000
            _, alt, _ = group_out_pooled(t2, track)
            same_fold = t["fold"] == t.loc[i, "fold"]
            # held-out predictions of the site's own fold are fitted without it
            self.assertAlmostEqual(base.loc[i, "oof"], alt.loc[i, "oof"], places=8)
            # other folds trained on it do change
            self.assertFalse(np.allclose(base.loc[~same_fold, "oof"], alt.loc[~same_fold, "oof"]))

    def test_metrics_and_ranking_gate(self):
        t, _, _ = self._table()
        m, _, _ = group_out_pooled(t, "calibrated")
        self.assertEqual(m["n_sites"], len(t))
        self.assertTrue(m["ranked"])
        self.assertAlmostEqual(m["q"], (m["rho"] + m["log_r2"]) / 2)
        m2, _, _ = group_out_pooled(t.head(15), "calibrated")
        self.assertFalse(m2["ranked"])

    def test_loco(self):
        t, _, _ = self._table()
        out = leave_one_city_out({"a": t, "b": t.assign(value=t["value"] * 1.1)}, "calibrated")
        self.assertEqual(set(out), {"a", "b"})
        self.assertGreater(out["a"][0]["rho"], 0.0)
        with self.assertRaises(ValueError):
            leave_one_city_out({"a": t}, "raw")

    def test_baselines_shapes(self):
        for name in bl.BASELINES:
            p = bl.baseline_predictions(self.case, name, ["car", "walking"])
            self.assertEqual(set(p["mode"]), {"car", "walking"})
            self.assertTrue((p["flow"] >= 0).all())
        heavy = bl.baseline_predictions(self.case, "centre_distance", ["heavy"])
        prim = self.case.network.query("allow_heavy")["segment_id"]
        self.assertEqual(set(heavy["segment_id"]), set(prim))


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = build_case(self.tmp / "src")
        self.mirror = write_release([self.src], self.tmp / "mirror")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fetch_ok_and_corruption_fails(self):
        root = self.tmp / "cases"
        got = fetch(BENCHMARK_VERSION, "synth-v1", root, self.mirror)
        self.assertTrue((root / "synth-v1" / "inputs" / "pois.parquet").exists())
        self.assertEqual(len(got), len(list(self.src.rglob("*.*"))))
        bad = self.mirror / "synth-v1__sites.csv"
        bad.write_bytes(bad.read_bytes() + b"x")
        root2 = self.tmp / "cases2"
        with self.assertRaises(FetchError):
            fetch(BENCHMARK_VERSION, "synth-v1", root2, self.mirror)
        self.assertFalse((root2 / "synth-v1" / "sites.csv").exists())

    def test_load_case_fetches_missing(self):
        root = self.tmp / "cases"
        case = load_case("synth-v1", cases_root=root, from_dir=self.mirror)
        self.assertEqual(case.case_id, "synth-v1")
        self.assertGreater(len(case.pois), 0)


class RunAllTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        build_case(self.tmp / "cases", "synth-a", seed=1)
        build_case(self.tmp / "cases", "synth-b", seed=2)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_end_to_end(self):
        from benchmark.run_all import blind_copy, main

        res = self.tmp / "results"
        args = ["--cases", "synth-a", "synth-b", "--tools", "baselines",
                "--cases-root", str(self.tmp / "cases"), "--results-dir", str(res)]
        self.assertEqual(main(args), 0)
        lb = pd.read_csv(res / "leaderboard.csv")
        self.assertEqual(set(lb["split"]), {"group_out_pooled", "leave_one_city_out"})
        self.assertEqual(set(lb["family"]), {"baseline"})
        self.assertEqual(set(lb["track"]), {"calibrated"})
        self.assertEqual(len(lb), 2 * 2 * 4 * 2)  # cases x modes x baselines x splits
        self.assertTrue((res / "leaderboards" / "synth-a__car__calibrated.csv").exists())
        self.assertIn("baseline", (res / "LEADERBOARD.md").read_text())
        q = lb[(lb["split"] == "group_out_pooled") & (lb["mode"] == "car") & (lb["case_id"] == "synth-a")].set_index("variant")["q"]
        self.assertGreater(q["centre_distance"], q["class_only"] - 0.2)
        # second run reuses the cache and appends to the log
        n_log = len(pd.read_csv(res / "log.csv"))
        self.assertEqual(main(args), 0)
        self.assertEqual(len(pd.read_csv(res / "log.csv")), 2 * n_log)
        rec = json.loads((res / "runs" / "synth-a" / "baseline" / "class_only__T1" / "run.json").read_text())
        self.assertEqual(rec["family"], "baseline")
        # adapters get a blind copy
        case = load_case("synth-a", cases_root=self.tmp / "cases")
        blind = blind_copy(case, res)
        names = {p.name for p in blind.iterdir()}
        self.assertEqual(names, {"case.yaml", "network.parquet", "inputs"})

    def test_time_limit_records_timeout_as_na(self):
        from benchmark.run_all import main
        res = self.tmp / "results"
        args = ["--cases", "synth-a", "--tools", "_echo", "--tier", "T0_network", "--params", '{"sleep": 5}',
                "--time-limit", "1", "--cases-root", str(self.tmp / "cases"), "--results-dir", str(res)]
        self.assertEqual(main(args), 0)
        lb = pd.read_csv(res / "leaderboard.csv")
        self.assertEqual(set(lb["status"]), {"timeout"})
        self.assertTrue(lb["q"].isna().all())
        self.assertEqual(set(lb["time_limit_s"]), {1.0})

    def test_tool_calibrated_cannot_see_held_out_counts(self):
        from benchmark.run_all import main
        res = self.tmp / "results"
        args = ["--cases", "synth-a", "--tools", "_echo", "--tier", "T0_network", "--tool-calibrated",
                "--cases-root", str(self.tmp / "cases"), "--results-dir", str(res)]
        self.assertEqual(main(args), 0)
        case = load_case("synth-a", cases_root=self.tmp / "cases")
        run = res / "runs" / "synth-a" / "_echo" / "default-toolcal__T0"
        for k in sorted(case.sites["fold"].unique()):
            train = pd.read_csv(run / f"fold{k}" / "_train" / "training_sites.csv", dtype={"site_id": str})
            held = case.sites[case.sites["fold"] == k]
            self.assertEqual(len(train.merge(held[["site_id", "mode"]])), 0)
            self.assertFalse((train["fold"] == k).any())
        # The echo tool copies any count it is given. On held-out sites whose links
        # carry no training site it can only return 0: the held-out count never leaks.
        t = pd.read_csv(run / "sites_car__tool_calibrated.csv", dtype={"site_id": str})
        xw = case.crosswalk[case.crosswalk["mode"] == "car"].merge(case.sites[["site_id", "mode", "fold"]])
        shared = set()
        for k in sorted(case.sites["fold"].unique()):
            shared |= set(xw[xw.fold == k].segment_id) & set(xw[xw.fold != k].segment_id)
        alone = set(xw.groupby("site_id").filter(lambda g: not set(g.segment_id) & shared).site_id)
        self.assertTrue(len(alone) > 0)
        self.assertTrue((t[t["site_id"].isin(alone)]["oof"] == 0).all())
        lb = pd.read_csv(res / "leaderboard.csv")
        self.assertEqual(set(lb["track"]), {"tool_calibrated"})
        self.assertEqual(set(lb["split"]), {"group_out_pooled"})


if __name__ == "__main__":
    unittest.main()
