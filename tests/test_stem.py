"""SciCal's use of SLAI's STEM agent: the bridge, the checks (a second computation by another route), and the STEM Lab.

Most tests use ``fake_stem.FakeSTEM`` (plain Python, follows the agent's request contract) so they run anywhere. ``LiveStemTests`` run against the
real agent and are skipped when it cannot be created (it needs NumPy and SciPy in the environment that runs SciCal)."""
import json
import math
import unittest

from scical.core.numerical.context import Settings
from scical.integrations import stem_checks as K
from scical.integrations import stem_lab
from scical.integrations.stem_bridge import StemBridge, StemFailed, StemUnavailable, plain
from scical.services import tasks

try:                                                  # run as a package (-m unittest tests.test_stem) or by discovery (-s tests)
    from .fake_stem import FakeSTEM, Quantity, SolverResult
except ImportError:
    from fake_stem import FakeSTEM, Quantity, SolverResult


def evaluate(text, ctx, settings):
    return tasks.run({"kind": "calc", "input": text, "context": ctx, "settings": settings})


def bridge(**tamper):
    return StemBridge(None, provider=lambda: FakeSTEM(tamper))


def env(b=None, settings=None, context=None):
    return K.CheckEnv(b or bridge(), evaluate, context or [], settings or {"angle": "rad"})


def verify(text, b=None, **kw):
    return K.verify_entry(env(b, **kw), {"kind": "calc", "input": text})


class BridgeTests(unittest.TestCase):
    def test_switched_off_says_why(self):
        b = StemBridge(None, "none")
        st = b.status()
        self.assertFalse(st["available"])
        self.assertIn("--agents none", st["reason"])
        with self.assertRaises(StemUnavailable):
            b.call("statistics", "mean", [1, 2])

    def test_no_slai_checkout_is_reported_not_imitated(self):
        st = StemBridge(None).status()
        self.assertFalse(st["available"])
        self.assertIn("SLAI", st["reason"])

    def test_creation_failure_hints_at_scipy(self):
        def boom():
            raise ImportError("No module named 'scipy'")
        st = StemBridge(None, provider=boom).status()
        self.assertFalse(st["available"])
        self.assertIn("pip install scipy", st["reason"])

    def test_status_lists_domains(self):
        st = bridge().status()
        self.assertTrue(st["available"])
        self.assertIn("statistics", st["domains"])
        self.assertGreater(st["operationCount"], 20)

    def test_results_become_plain_json(self):
        self.assertEqual(plain(Quantity(2.5, "m")), {"magnitude": 2.5, "unit": "m"})
        self.assertEqual(plain(SolverResult(1.0, 0.0, 3))["iterations"], 3)
        self.assertIsNone(plain(float("nan")))
        self.assertEqual(plain((1, [2.0, float("inf")])), [1, [2.0, None]])
        self.assertEqual(plain(complex(1, 2)), {"re": 1.0, "im": 2.0})
        json.dumps(plain(Quantity(1.0)), allow_nan=False)

    def test_agent_errors_become_stem_failed_with_the_message(self):
        with self.assertRaises(StemFailed) as cm:
            bridge().call("numerical_methods", "solve_linear_system", [[1, 1], [1, 1]], [1, 2])
        self.assertIn("singular", cm.exception.message)
        with self.assertRaises(StemFailed):
            bridge().call("statistics", "no_such_operation")

    def test_number_reads_quantities_and_refuses_the_rest(self):
        b = bridge()
        self.assertEqual(b.number("parametric", "evaluate_expression", "2 * x", {"v": 1.0} if False else {"x": 4.0}), 8.0)
        with self.assertRaises(StemFailed):
            b.number("numerical_methods", "condition_numbers", [[1, 0], [0, 1]])          # a mapping without a number

    def test_deadline_stops_requests(self):
        view = bridge().scoped(-1.0)
        with self.assertRaises(StemFailed) as cm:
            view.number("statistics", "mean", [1, 2])
        self.assertIn("time limit", cm.exception.message)

    def test_a_limit_raised_inside_a_callback_survives_the_agent(self):
        def f(x):
            raise StemFailed("Stopped after 5 evaluations.")
        with self.assertRaises(StemFailed) as cm:
            bridge().call("numerical_methods", "bisection", f, 0.0, 1.0)
        self.assertIn("Stopped after 5", cm.exception.message)


class ParsingTests(unittest.TestCase):
    def test_parse_real(self):
        for text, want in [("3", 3.0), ("-1 / 5", -0.2), ("3.3333333333333333e-9", 3.3333333333333333e-9), ("−2.5", -2.5), ("1/3", 1 / 3)]:
            self.assertAlmostEqual(K.parse_real(text), want, msg=text)
        for text in ("sqrt(2)", "1 + 2i", "x", "", None, "5 m", "1/0"):
            self.assertIsNone(K.parse_real(text), text)

    def test_names_that_are_unit_symbols_are_renamed(self):
        expr, names = K.to_stem("m*g*h + C", "rad")
        self.assertEqual(names, {"m", "g", "h", "C"})
        self.assertNotIn("(m", expr)
        self.assertIn("v_m", expr)

    def test_angle_mode_is_honoured(self):
        expr, _ = K.to_stem("sin(30)", "deg")
        self.assertAlmostEqual(bridge().number("parametric", "evaluate_expression", expr, {}), 0.5)

    def test_unsupported_things_say_what(self):
        for text in ("gamma(2)", "[1,2]", "x > 1"):
            with self.assertRaises(K.Unsupported):
                K.to_stem(text)


class CalcCheckTests(unittest.TestCase):
    AGREE = ["sqrt(2)*3", "1/3 + 1/6", "mean([1,2,3,4,10])", "std([2,4,4,4,5,5,7,9])", "normalcdf(1.96,0,1)", "binompdf(10,0.3,3)", "gcd(12,18)", "nCr(10,3)", "7!",
             "diff(x^3*sin(x), x)", "integral(x^2, x, 0, 3)", "integral(sin(x), x)", "solve(x^2 - 5*x + 6 = 0, x)", "[[1,2],[3,4]]^-1", "linsolve([[2,1],[1,3]],[3,5])",
             "corr([1,2,3,4],[2,4,5,9])", "slope([1,2,3,4],[2,4,5,9])", "tcdf(1.5,8)", "5 m -> cm", "sin(30)"]

    def test_these_agree(self):
        for text in self.AGREE:
            with self.subTest(text):
                r = verify(text)
                self.assertEqual(r["verdict"], "agree", (text, r))
                self.assertGreaterEqual(r["counts"]["agree"], 1)
                for c in r["checks"]:
                    self.assertIsNotNone(c["via"], c)
                    self.assertIsNotNone(c["tolerance"], c)
                json.dumps(r, allow_nan=False)

    def test_a_wrong_stem_answer_is_reported_as_a_difference(self):
        r = verify("mean([1,2,3,4,10])", bridge(**{"statistics.mean": lambda v: v + 0.001}))
        self.assertEqual(r["verdict"], "differ")
        c = r["checks"][0]
        self.assertEqual(c["status"], "differ")
        self.assertEqual((c["scical"], c["stem"]), ("4", "4.001"))
        self.assertIn("still the one shown", r["summary"])

    def test_the_derivative_check_notices_a_wrong_derivative(self):
        r = verify("diff(x^3*sin(x), x)", bridge(**{"parametric.derivative": lambda v: {"value": v["value"] * 1.001}}))
        self.assertEqual(r["verdict"], "differ")

    def test_roots_are_checked_by_substitution(self):
        r = verify("solve(x^2 - 5*x + 6 = 0, x)")
        self.assertIn("Residual", r["checks"][0]["title"])
        self.assertEqual(r["checks"][0]["via"].split(" ")[0], "parametric.evaluate_expression")

    def test_the_integration_constant_is_not_an_error(self):
        self.assertEqual(verify("integral(sin(x), x)")["verdict"], "agree")

    def test_worksheet_definitions_are_used(self):
        r = verify("a*sqrt(4)", context=["a := 5"])
        self.assertEqual(r["verdict"], "agree")
        self.assertEqual(r["checks"][0]["scical"], "10")

    def test_variables_named_like_units_work(self):
        r = verify("m*g", context=["m := 2", "g := 9.81"])
        self.assertEqual(r["verdict"], "agree", r)

    def test_angle_mode_matters(self):
        self.assertEqual(verify("sin(30)", settings={"angle": "deg"})["verdict"], "agree")
        self.assertEqual(verify("sin(30)", settings={"angle": "rad"})["verdict"], "agree")

    def test_skipped_with_a_reason(self):
        for text, why in [("a := 5", "definition"), ("12 in -> cm", "unit"), ("sqrt(-4)", "real number"), ("x + 1", "no numeric value"), ("[1,2,3]", "")]:
            with self.subTest(text):
                r = verify(text)
                self.assertEqual(r["verdict"], "none", r)
                self.assertTrue(r["checks"] and r["checks"][0]["status"] == "skipped")
                self.assertIn(why.lower(), r["checks"][0]["note"].lower())

    def test_a_malformed_input_is_skipped_not_raised(self):
        r = verify("2 +")
        self.assertEqual(r["verdict"], "none")

    def test_unavailable_agent_raises_for_the_caller_to_report(self):
        with self.assertRaises(StemUnavailable):
            K.verify_entry(K.CheckEnv(StemBridge(None, "none"), evaluate, [], {}), {"kind": "calc", "input": "1+1"})

    def test_verdict_text_counts(self):
        r = verify("mean([1,2,3])")
        self.assertIn("agrees on 1 of 1 check", r["summary"])
        self.assertIn("different route", r["label"])

    def test_notes_and_graphs_have_nothing_to_check(self):
        r = K.verify_entry(env(), {"kind": "note", "text": "hello"})
        self.assertEqual(r["verdict"], "none")


class DomainCheckTests(unittest.TestCase):
    def run_domain(self, domain, op, params, b=None):
        res = tasks.run({"kind": "domain", "domain": domain, "op": op, "params": params, "settings": {}})
        self.assertTrue(res["ok"], res)
        return res, K.verify_entry(env(b), {"kind": "domain", "domain": domain, "op": op, "params": params, "result": res})

    def example(self, domain, op):
        from scical.domains import forms
        return next(o for o in forms.catalogue()[domain]["ops"] if o["id"] == op)["example"]

    def test_the_documented_examples_agree(self):
        for domain, op in [("measurement", "repeated"), ("measurement", "calibration"), ("measurement", "uncertainty_budget"), ("measurement", "formula_uncertainty"),
                           ("measurement", "uncertainty"), ("formulas", "formula_solve"), ("chemistry", "gas"), ("biology", "michaelis_menten")]:
            with self.subTest(f"{domain}.{op}"):
                _, r = self.run_domain(domain, op, self.example(domain, op))
                self.assertEqual(r["verdict"], "agree", r)

    def test_repeated_measurements_cover_mean_spread_and_t(self):
        _, r = self.run_domain("measurement", "repeated", {"values": [9.81, 9.79, 9.84, 9.8, 9.83]})
        titles = [c["title"] for c in r["checks"]]
        self.assertTrue(any("Mean" in t for t in titles) and any("t value" in t for t in titles) and any("Standard error" in t for t in titles))

    def test_formula_uncertainty_is_checked_three_ways(self):
        _, r = self.run_domain("measurement", "formula_uncertainty", {"expression": "m*g*h", "variables": {"m": {"value": "2", "uncertainty": "0.1"}, "g": {"value": "9.81", "uncertainty": "0.02"},
                                                                                                               "h": {"value": "3", "uncertainty": "0.05"}}})
        self.assertEqual([c["status"] for c in r["checks"]], ["agree"] * 3)
        self.assertIn("Monte Carlo", r["checks"][2]["title"])

    def test_a_wrong_budget_is_caught(self):
        res, r = self.run_domain("measurement", "uncertainty_budget", self.example("measurement", "uncertainty_budget"),
                                 bridge(**{"uncertainty.combined_standard_uncertainty": lambda v: v * 1.01}))
        self.assertEqual(r["verdict"], "differ")

    def test_gas_law_is_checked_whichever_quantity_was_solved(self):
        for params in [{"mode": "ideal", "P": "1 atm", "V": "10 L", "T": "300 K"}, {"mode": "ideal", "P": "101.325 kPa", "n": "1 mol", "T": "273.15 K"},
                       {"mode": "ideal", "n": "2 mol", "V": "5 L", "T": "300 K"}]:
            with self.subTest(params):
                _, r = self.run_domain("chemistry", "gas", params)
                self.assertEqual(r["verdict"], "agree", r)

    def test_correlated_budgets_are_not_compared(self):
        res, r = self.run_domain("measurement", "uncertainty_budget", {**self.example("measurement", "uncertainty_budget"), "correlations": [[1, 0.5], [0.5, 1]]})
        self.assertEqual(r["verdict"], "none")
        self.assertIn("correlated", r["checks"][0]["note"])

    def test_operations_without_a_check_say_so(self):
        _, r = self.run_domain("chemistry", "molar_mass", {"formula": "H2O"})
        self.assertEqual(r["verdict"], "none")
        self.assertIn("no independent check", r["summary"])


class LabTests(unittest.TestCase):
    def run_op(self, op, params, b=None):
        return stem_lab.run(b or bridge(), Settings(), op, params, evaluate)

    def test_every_form_example_runs(self):
        from scical.domains.stemdefs import STEM
        for o in STEM:
            with self.subTest(o["id"]):
                res = self.run_op(o["id"], o["example"])
                self.assertTrue(res.get("ok"), res)
                json.dumps(res, allow_nan=False)

    def test_ode_harmonic_oscillator_returns_to_its_start(self):
        r = self.run_op("ode", {"equations": "x' = v\nv' = -x", "initial": {"x": "1", "v": "0"}, "t1": "6.283185307179586", "method": "rk4"})
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["finalState"]["x"]["value"], 1.0, places=6)
        self.assertAlmostEqual(r["finalState"]["v"]["value"], 0.0, places=6)
        self.assertEqual(len(r["plot"]["series"]), 2)
        self.assertIn("plot2", r)                                                    # two variables give a phase portrait

    def test_ode_comparison_ranks_the_methods(self):
        r = self.run_op("ode", {"equations": "y' = -y", "initial": {"y": "1"}, "t1": "2", "method": "rk4", "step": "0.1", "compare": True})
        err = {row["method"]: row["error at the end"] for row in r["methods"]}
        self.assertGreater(err["euler"], err["rk4"] * 100)

    def test_ode_input_errors_are_readable(self):
        bad = [({"equations": "x = 1", "initial": {"x": "1"}, "t1": "1"}, "Cannot read"), ({"equations": "x' = k*x", "initial": {"x": "1"}, "t1": "1"}, "'k'"),
               ({"equations": "x' = x", "initial": {}, "t1": "1"}, "initial"), ({"equations": "x' = x", "initial": {"x": "1"}, "t1": "0"}, "later than"),
               ({"equations": "x' = x", "initial": {"x": "1"}, "t1": "100000", "step": "0.001"}, "steps")]
        for params, text in bad:
            with self.subTest(params):
                r = self.run_op("ode", params)
                self.assertFalse(r["ok"])
                self.assertIn(text, r["error"]["message"])

    def test_evaluation_budget_stops_runaway_work(self):
        b = bridge()
        old = stem_lab.MAX_EVALS
        stem_lab.MAX_EVALS = 300
        try:
            r = self.run_op("ode", {"equations": "x' = -x", "initial": {"x": "1"}, "t1": "50", "step": "0.02", "method": "rk4"}, b)
        finally:
            stem_lab.MAX_EVALS = old
        self.assertFalse(r["ok"])
        self.assertIn("Stopped after 300", r["error"]["message"])

    def test_quadrature_errors_are_measured_against_the_exact_integral(self):
        r = self.run_op("quadrature", {"expression": "sin(x)^2", "a": "0", "b": "3", "n": "10"})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["referenceIs"], "SciCal's exact integral")
        rows = {x["method"].split(" ")[0]: x for x in r["methods"]}
        self.assertGreater(rows["Trapezoid"]["error"], rows["Simpson"]["error"])
        self.assertTrue(any(x.get("note") for x in r["methods"]))                      # the fake lacks Monte Carlo: that row says so instead of vanishing

    def test_roots_methods_agree_and_report_residuals(self):
        r = self.run_op("roots", {"expression": "x^3 - 2*x - 5 = 0", "a": "2", "b": "3"})
        self.assertAlmostEqual(r["root"]["value"], 2.0945514815423265, places=9)
        self.assertEqual([m["status"] for m in r["methods"]], ["converged"] * 3)

    def test_roots_without_a_sign_change_explain(self):
        r = self.run_op("roots", {"expression": "x^2 + 1", "a": "-1", "b": "1"})
        self.assertTrue(r["ok"])
        self.assertTrue(r["methods"][0]["note"])

    def test_linear_system_shows_exact_vs_float_and_conditioning(self):
        r = self.run_op("linear", {"matrix": "1 2\n3 4", "rhs": "5 6"})
        self.assertAlmostEqual(r["solution"]["x1"]["value"], -4.0, places=9)
        self.assertIn("exactSolution", r)
        r2 = self.run_op("linear", {"matrix": "1 1\n1 1.0000000001", "rhs": "2 2"})
        self.assertIn("ill-conditioned", " ".join(r2.get("warnings", [])))

    def test_singular_system_is_an_error_card(self):
        r = self.run_op("linear", {"matrix": "1 1\n1 1", "rhs": "1 2"})
        self.assertFalse(r["ok"])

    def test_interpolation_values_and_extrapolation_warning(self):
        r = self.run_op("interpolate", {"data": "0 0\n1 1\n2 0\n3 1", "queries": "0.5 5"})
        self.assertAlmostEqual(r["values"][0]["Linear"], 0.5)
        self.assertIsNone(r["values"][1]["Linear"])
        self.assertIn("outside the data", " ".join(r["warnings"]))

    def test_bootstrap_is_repeatable_with_a_seed(self):
        p = {"values": "9.81 9.79 9.84 9.80 9.83 9.82 9.78 9.85", "resamples": "500", "seed": "11"}
        a, b = self.run_op("bootstrap", p), self.run_op("bootstrap", p)
        self.assertEqual(a["lower"]["value"], b["lower"]["value"])
        self.assertIn("tInterval", a)

    def test_monte_carlo_reports_first_order_and_sampled(self):
        r = self.run_op("monte_carlo", {"expression": "x*y", "variables": {"x": {"value": "10", "uncertainty": "0.5"}, "y": {"value": "4", "uncertainty": "0.2"}}, "samples": "2000", "seed": "5"})
        self.assertAlmostEqual(r["firstOrderUncertainty"]["value"], math.sqrt((4 * 0.5) ** 2 + (10 * 0.2) ** 2), places=6)
        self.assertAlmostEqual(r["monteCarloUncertainty"]["value"], r["firstOrderUncertainty"]["value"], delta=0.3)
        self.assertEqual(r["sensitivities"][0]["variable"], "x")

    def test_catalogue_lists_the_agents_domains(self):
        r = self.run_op("catalogue", {})
        self.assertIn("statistics", [d["domain"] for d in r["domains"]])

    def test_unavailable_agent_is_an_error_card_with_the_reason(self):
        r = stem_lab.run(StemBridge(None, "none"), Settings(), "ode", {}, evaluate)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "stem_unavailable")

    def test_unknown_operation(self):
        self.assertEqual(self.run_op("nope", {})["error"]["code"], "not_found")


class ExportTests(unittest.TestCase):
    def doc(self, verification):
        return {"name": "t", "id": "x", "entries": [{"id": "a", "kind": "calc", "input": "mean([1,2,3])", "result": {"ok": True, "value": {"text": "2", "latex": "2"}}, "verification": verification}]}

    def test_text_and_markdown_say_what_stem_found(self):
        from scical.services import exports
        v = {"ran": True, "verdict": "agree", "counts": {"agree": 2, "differ": 0}}
        self.assertIn("STEM check: the SLAI STEM agent agrees (2 of 2", exports.to_text(self.doc(v)))
        self.assertIn("STEM check", exports.to_markdown(self.doc(v)))
        d = {"ran": True, "verdict": "differ", "counts": {"agree": 1, "differ": 1}}
        self.assertIn("DIFFERS on 1 of 2", exports.to_text(self.doc(d)))

    def test_nothing_is_claimed_when_it_was_not_checked(self):
        from scical.services import exports
        for v in (None, {"ran": False, "verdict": "unavailable"}, {"ran": True, "verdict": "none", "counts": {}}):
            self.assertNotIn("STEM", exports.to_text(self.doc(v)))

    def test_a_worksheet_entry_may_carry_a_verification(self):
        from scical.services.sessions import clean_entry
        e = clean_entry({"kind": "calc", "input": "1+1", "verification": {"ran": True, "verdict": "agree", "checks": []}}, 0)
        self.assertEqual(e["verification"]["verdict"], "agree")


class LiveStemTests(unittest.TestCase):
    """Against the real agent (set up through SLAI, or SCICAL_STEM_PROVIDER). Skipped when it cannot be created."""

    @classmethod
    def setUpClass(cls):
        from scical.integrations.slai_link import SlaiLink, find_slai_root
        from pathlib import Path
        root = find_slai_root(None)
        cls.bridge = StemBridge(SlaiLink(root, Path("."), "auto", 20.0) if root else None)
        st = cls.bridge.status()
        if not st["available"]:
            raise unittest.SkipTest("STEM agent not available here: " + str(st["reason"]))

    def test_checks_agree_with_the_real_agent(self):
        for text in ["sqrt(2)*3", "mean([1,2,3,4,10])", "normalcdf(1.96,0,1)", "diff(x^3*sin(x), x)", "integral(x^2, x, 0, 3)", "solve(x^2 - 5*x + 6 = 0, x)", "[[1,2],[3,4]]^-1"]:
            with self.subTest(text):
                r = K.verify_entry(K.CheckEnv(self.bridge.scoped(30), evaluate, [], {"angle": "rad"}), {"kind": "calc", "input": text})
                self.assertEqual(r["verdict"], "agree", r)

    def test_lab_runs_with_the_real_agent(self):
        r = stem_lab.run(self.bridge, Settings(), "ode", {"equations": "y' = -y", "initial": {"y": "1"}, "t1": "1", "method": "rk45"}, evaluate)
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["finalState"]["y"]["value"], 0.36787944117, places=4)


if __name__ == "__main__":
    unittest.main()
