"""Consolidated contract and adapter tests on the synthetic grid case."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd

from adapters._base import run_adapter, validate_predictions
from benchmark.contract_check import adapter_names, check_all
from tests.synthetic_case import build_case

try:
    import aequilibrae  # noqa: F401
    HAVE_AEQ = True
except ImportError:
    HAVE_AEQ = False

try:
    import cityseer  # noqa: F401
    HAVE_CITYSEER = True
except ImportError:
    HAVE_CITYSEER = False

try:
    import urban_network_analysis  # noqa: F401
    HAVE_UNA = True
except ImportError:
    HAVE_UNA = False

try:
    import sDNA  # noqa: F401
    HAVE_SDNA = True
except ImportError:
    HAVE_SDNA = False


class ContractTest(unittest.TestCase):
    def test_all_adapters_pass_or_skip(self):
        results = check_all(verbose=False)
        self.assertEqual(set(results), set(adapter_names()))
        for name, (status, msg) in results.items():
            self.assertIn(status, ("ok", "skipped"), f"{name}: {msg}")


class AdapterVariantsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="aadtbench-adapters-"))
        cls.case = build_case(cls.tmp)
        cls.net = gpd.read_parquet(cls.case / "network.parquet")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @unittest.skipUnless(HAVE_AEQ, "aequilibrae is not installed")
    def test_aequilibrae_variants(self):
        from adapters.aequilibrae import AequilibraEAssign
        totals = {}
        for variant, modes in (("aon", ["car", "walking"]), ("ue_bfw", ["car"])):
            out = self.tmp / f"aeq_{variant}"
            rec = run_adapter(AequilibraEAssign(), self.case, "T2_synthetic_od", modes,
                              out, variant=variant, threads=1)
            self.assertEqual(rec["status"], "complete")
            pred = validate_predictions(pd.read_parquet(out / "predictions.parquet"), self.net["segment_id"])
            self.assertEqual(set(pred["mode"]), set(modes))
            self.assertGreater((pred["flow"] > 0).sum(), 0.5 * len(pred))
            totals[variant] = pred[pred["mode"] == "car"]["flow"].sum()
        self.assertGreaterEqual(totals["ue_bfw"], 0.99 * totals["aon"])
        rec_w = run_adapter(AequilibraEAssign(), self.case, "T2_synthetic_od", ["walking"],
                            self.tmp / "aeq_walk", variant="ue_bfw", threads=1)
        self.assertEqual(rec_w["status"], "unsupported")

    @unittest.skipUnless(HAVE_CITYSEER, "cityseer is not installed")
    def test_cityseer_variants(self):
        from adapters.cityseer_od import CityseerOD
        flows = {}
        for variant in ("default", "dispersed"):
            out = self.tmp / f"cs_{variant}"
            rec = run_adapter(CityseerOD(), self.case, "T2_synthetic_od", ["car", "walking"],
                              out, variant=variant, threads=1)
            self.assertEqual(rec["status"], "complete")
            pred = validate_predictions(pd.read_parquet(out / "predictions.parquet"), self.net["segment_id"])
            self.assertEqual(set(pred["mode"]), {"car", "walking"})
            self.assertGreater((pred["flow"] > 0).sum(), 0.5 * len(pred))
            flows[variant] = pred[pred["mode"] == "car"].set_index("segment_id")["flow"]
        self.assertFalse(flows["default"].equals(flows["dispersed"]))

    @unittest.skipUnless(HAVE_UNA, "urban_network_analysis is not installed")
    def test_una_variants(self):
        from adapters.una import UNAFlow
        for variant in ("default", "shortest"):
            out = self.tmp / f"una_{variant}"
            rec = run_adapter(UNAFlow(), self.case, "T1_open_covariates", ["car", "walking"],
                              out, variant=variant, threads=1)
            self.assertEqual(rec["status"], "complete")
            pred = validate_predictions(pd.read_parquet(out / "predictions.parquet"), self.net["segment_id"])
            self.assertEqual(set(pred["mode"]), {"car", "walking"})
            self.assertGreater((pred["flow"] > 0).sum(), 0.5 * len(pred))

    @unittest.skipUnless(HAVE_SDNA, "sdna-plus is not installed")
    def test_sdna_variants(self):
        from adapters.sdna import SDNA
        for variant, family in [("betweenness_angular", "flow"), ("betweenness_euclidean", "flow"),
                                ("nqpd_euclidean", "reach"), ("nqpd_angular", "reach")]:
            out = self.tmp / f"sdna_{variant}"
            rec = run_adapter(SDNA(), self.case, "T0_network", ["walking", "car"], out, variant=variant, threads=1)
            self.assertEqual(rec["status"], "complete")
            self.assertEqual(rec["family"], family)
            self.assertGreater(rec["n_predictions"], 0)


if __name__ == "__main__":
    unittest.main()
