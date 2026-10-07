"""Test the AequilibraE adapter on a tiny synthetic 6 by 6 grid case."""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import tempfile
import unittest
import yaml
from shapely.geometry import LineString, box


from adapters._base import run_adapter, validate_predictions  # noqa: E402
from adapters.aequilibrae import AequilibraEAssign  # noqa: E402

try:
    import aequilibrae  # noqa: F401  (availability check)
    HAVE_AEQ = True
except ImportError:  # the CI unit job does not install tools
    HAVE_AEQ = False

N, STEP, X0, Y0 = 6, 500.0, 400000.0, 400000.0


def build_case(root: Path) -> Path:
    (root / "inputs").mkdir(parents=True)
    rows, k = [], 0
    for i in range(N):
        for j in range(N):
            for di, dj in ((1, 0), (0, 1)):
                if i + di < N and j + dj < N:
                    a = (X0 + i * STEP, Y0 + j * STEP)
                    b = (X0 + (i + di) * STEP, Y0 + (j + dj) * STEP)
                    cls = "primary" if (i if dj else j) % 3 == 0 else "minor"
                    rows.append(dict(segment_id=f"s{k:03d}", u=i * N + j, v=(i + di) * N + j + dj,
                                     length_m=STEP, road_class=cls, highway=cls, name="",
                                     allow_walking=True, allow_cycling=True, allow_car=True,
                                     allow_heavy=True, dir_car="both", dir_cycling="both",
                                     pair_segment="", geometry=LineString([a, b])))
                    k += 1
    net = gpd.GeoDataFrame(rows, crs=27700)
    net.to_parquet(root / "network.parquet")
    # One zone per grid node, centred on the node.
    zones = gpd.GeoDataFrame(
        {"zone_id": [f"z{i * N + j}" for i in range(N) for j in range(N)],
         "geometry": [box(X0 + i * STEP - 50, Y0 + j * STEP - 50, X0 + i * STEP + 50, Y0 + j * STEP + 50)
                      for i in range(N) for j in range(N)]}, crs=27700)
    zones.to_parquet(root / "inputs" / "zones.parquet")
    rng = np.random.RandomState(3)
    ids = zones["zone_id"].tolist()
    od = pd.DataFrame([dict(o_zone=o, d_zone=d, mode=m, trips=float(rng.randint(50, 500)))
                       for o in ids for d in ids if o != d and rng.rand() < 0.4
                       for m in ("car", "heavy")])
    od.to_parquet(root / "inputs" / "od_synthetic.parquet")
    manifest = {"id": "grid-v1", "version": "1.0.0", "benchmark_version": "0.2.0",
                "crs": "EPSG:27700", "modes": ["car", "heavy", "walking"],
                "input_tiers": ["T0_network", "T2_synthetic_od"]}
    (root / "case.yaml").write_text(yaml.safe_dump(manifest))
    return root


@unittest.skipUnless(HAVE_AEQ, "aequilibrae is not installed")
class AequilibraEAdapterTest(unittest.TestCase):
    def run_variant(self, variant, modes=("car", "heavy")):
        tmp = Path(tempfile.mkdtemp())
        case = build_case(tmp / "grid-v1")
        out = tmp / "run"
        rec = run_adapter(AequilibraEAssign(), case, "T2_synthetic_od", list(modes), out,
                          variant=variant, threads=1)
        return case, out, rec

    def test_variants_run_and_validate(self):
        for variant in ("aon", "ue_bfw"):
            with self.subTest(variant=variant):
                case, out, rec = self.run_variant(variant)
                self.assertEqual(rec["status"], "complete")
                self.assertEqual(rec["family"], "assignment")
                self.assertEqual(rec["options"]["distance"], "time")
                expected = "none" if variant == "aon" else "user equilibrium (BPR)"
                self.assertEqual(rec["options"]["congestion"], expected)
                net = gpd.read_parquet(case / "network.parquet")
                pred = validate_predictions(pd.read_parquet(out / "predictions.parquet"),
                                            net["segment_id"])
                self.assertEqual(set(pred["mode"]), {"car", "heavy"})
                self.assertGreater((pred["flow"] > 0).sum(), 0.8 * len(pred))

    def test_ue_flow_total_close_to_aon(self):
        """Total vehicle-edge flow under UE is at least that of AoN (longer routes)."""
        _, out_a, _ = self.run_variant("aon", ("car",))
        _, out_u, _ = self.run_variant("ue_bfw", ("car",))
        a = pd.read_parquet(out_a / "predictions.parquet")["flow"].sum()
        u = pd.read_parquet(out_u / "predictions.parquet")["flow"].sum()
        self.assertGreaterEqual(u, 0.99 * a)

    def test_ue_unsupported_for_walking(self):
        _, out, rec = self.run_variant("ue_bfw", ("walking",))
        self.assertIn(rec["status"], ("unsupported",))


if __name__ == "__main__":
    unittest.main()
