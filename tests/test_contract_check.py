"""Run the adapter contract check as a unit test."""
import unittest

from benchmark.contract_check import adapter_names, check_all


class ContractCheckTest(unittest.TestCase):
    def test_every_adapter_follows_the_contract(self):
        results = check_all(verbose=False)
        self.assertEqual(sorted(results), adapter_names())
        failed = {n: m for n, (s, m) in results.items() if s == "failed"}
        self.assertEqual(failed, {})


if __name__ == "__main__":
    unittest.main()
