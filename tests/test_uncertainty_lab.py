"""Reference and invalid-input tests for the UncertaintyLab measurement extension."""
import math
import unittest

from scical.services.tasks import run


def calculate(operation, **params):
    return run({"kind": "domain", "domain": "measurement",
                "op": operation, "params": params, "settings": {}})


def amount(result, key):
    return float(result[key]["value"])


class UncertaintyLabTests(unittest.TestCase):
    def test_independent_uncertainty_budget(self):
        res = calculate("uncertainty_budget", components=[
            {"source": "a", "uncertainty": 0.3},
            {"source": "b", "uncertainty": 0.4}], coverageFactor=2)
        self.assertTrue(res["ok"], res)
        self.assertAlmostEqual(amount(res, "combinedUncertainty"), 0.5, places=12)
        self.assertAlmostEqual(amount(res, "expandedUncertainty"), 1.0, places=12)

    def test_correlated_formula(self):
        res = calculate("formula_uncertainty", expression="x + y",
                        variables={"x": {"value": 10, "uncertainty": 1},
                                   "y": {"value": 20, "uncertainty": 1}},
                        correlations=[[1, 0.5], [0.5, 1]])
        self.assertTrue(res["ok"], res)
        self.assertAlmostEqual(amount(res, "combinedUncertainty"), math.sqrt(3), places=12)
        self.assertAlmostEqual(amount(res, "value"), 30, places=12)

    def test_type_b_rectangular(self):
        res = calculate("uncertainty_budget", components=[
            {"source": "resolution", "uncertainty": 0.6,
             "distribution": "rectangular", "interpretation": "half_width"}])
        self.assertTrue(res["ok"], res)
        self.assertAlmostEqual(amount(res, "combinedUncertainty"), 0.6 / math.sqrt(3), places=12)

    def test_correlation_textarea(self):
        res = calculate("uncertainty_budget", components=[
            {"source": "a", "uncertainty": 1}, {"source": "b", "uncertainty": 1}],
            correlations="[[1,0.5],[0.5,1]]")
        self.assertTrue(res["ok"], res)
        self.assertAlmostEqual(amount(res, "combinedUncertainty"), math.sqrt(3), places=12)

    def test_invalid_covariance_rejected(self):
        res = calculate("uncertainty_budget", components=[
            {"source": "a", "uncertainty": 1}, {"source": "b", "uncertainty": 1}],
            correlations=[[1, 2], [2, 1]])
        self.assertFalse(res["ok"])

    def test_negative_uncertainty_rejected(self):
        res = calculate("uncertainty_budget", components=[
            {"source": "probe", "uncertainty": -1}])
        self.assertFalse(res["ok"])

    def test_legacy_operation_unchanged(self):
        res = calculate("uncertainty", expression="x + y",
                        variables={"x": {"value": 10, "uncertainty": 0.3},
                                   "y": {"value": 20, "uncertainty": 0.4}})
        self.assertTrue(res["ok"], res)
        self.assertAlmostEqual(amount(res, "uncertainty"), 0.5, places=12)


if __name__ == "__main__":
    unittest.main()
