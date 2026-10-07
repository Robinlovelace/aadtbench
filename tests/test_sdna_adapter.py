"""Test the sDNA adapter on the synthetic grid case, for every variant."""
import tempfile
import unittest
from pathlib import Path

from adapters._base import run_adapter
from adapters.sdna import SDNA
from tests.synthetic_case import build_case

try:
    import sDNA  # noqa: F401  (availability check)
    HAVE_SDNA = True
except ImportError:  # the CI unit job does not install tools
    HAVE_SDNA = False


@unittest.skipUnless(HAVE_SDNA, "sdna-plus not installed")
class SdnaAdapterTest(unittest.TestCase):
    def test_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = build_case(Path(tmp))
            for variant, family in [("betweenness_angular", "flow"), ("betweenness_euclidean", "flow"),
                                    ("nqpd_euclidean", "reach"), ("nqpd_angular", "reach")]:
                with self.subTest(variant=variant):
                    out = Path(tmp) / variant
                    rec = run_adapter(SDNA(), case, "T0_network", ["walking", "car"], out, variant)
                    self.assertEqual(rec["status"], "complete")
                    self.assertEqual(rec["family"], family)
                    self.assertGreater(rec["n_predictions"], 0)


if __name__ == "__main__":
    unittest.main()
