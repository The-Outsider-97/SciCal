"""The calculator engine, checked against mathematical truth. Run through the same entry point the worker processes use."""
import math
import re
import unittest
from pathlib import Path

from scical.services.tasks import run


def calc(text, context=None, **settings):
    return run({"kind": "calc", "input": text, "settings": settings, "context": context, "explain": False})


def exact(text, **settings) -> str:
    r = calc(text, **settings)
    assert r["ok"], r
    return r["value"]["text"]


def approx(text, **settings) -> float:
    r = calc(text, **settings)
    assert r["ok"], r
    v = r["value"]
    return float((v.get("approx") or v)["text"].replace(" ", ""))


class ArithmeticTests(unittest.TestCase):
    def test_exact_rationals(self):
        self.assertEqual(exact("1/3 + 1/6"), "1 / 2")
        self.assertEqual(exact("2^10"), "1024")
        self.assertEqual(exact("10!"), "3628800")
        self.assertEqual(exact("nCr(10,3)"), "120")
        self.assertEqual(exact("gcd(12,18)"), "6")
        self.assertEqual(exact("7 mod 3"), "1")

    def test_no_binary_float_noise(self):
        r = calc("0.1 + 0.2")
        self.assertTrue(r["ok"])
        self.assertNotIn("0.30000000000000004", str(r["value"]))
        self.assertEqual(r["value"]["exact"]["text"], "3 / 10")

    def test_exact_versus_approximate_flags(self):
        self.assertTrue(calc("1/3")["flags"]["exact"])
        r = calc("sqrt(2)")
        self.assertFalse(r["flags"]["approximate"] and r["flags"]["exact"])
        self.assertAlmostEqual(approx("sqrt(2)"), math.sqrt(2), places=10)

    def test_irrational_constants(self):
        self.assertAlmostEqual(approx("pi"), math.pi, places=10)
        self.assertAlmostEqual(approx("e^1"), math.e, places=10)
        self.assertAlmostEqual(approx("ln(10)"), math.log(10), places=10)

    def test_big_integers_stay_exact(self):
        self.assertEqual(exact("2^200"), str(2 ** 200))
        self.assertEqual(exact("30!"), str(math.factorial(30)))

    def test_angle_modes(self):
        self.assertEqual(exact("sin(30°)", angle="rad"), "1 / 2")
        self.assertEqual(exact("sin(30)", angle="deg"), "1 / 2")
        self.assertAlmostEqual(approx("sin(pi/2)", angle="rad"), 1.0)
        self.assertAlmostEqual(approx("atan(1)", angle="deg"), 45.0)

    def test_precedence_matches_mathematics(self):
        self.assertEqual(exact("-2^2"), "-4")
        self.assertEqual(exact("(-2)^2"), "4")
        self.assertEqual(exact("2^3^2"), "512")
        self.assertEqual(exact("1/2x", ), calc("(1/2)*x")["value"]["text"])

    def test_complex_numbers(self):
        r = calc("(1+2i)*(3-i)", complex=True)
        self.assertTrue(r["ok"])
        self.assertEqual(r["value"]["text"].replace(" ", ""), "5+5i")


class AlgebraAndCalculusTests(unittest.TestCase):
    def test_derivative(self):
        # d/dx x^3 = 3x^2; check by evaluating the answer at several points
        r = calc("diff(x^3, x)")
        self.assertTrue(r["ok"])
        for x in (-2, 0.5, 3):
            self.assertAlmostEqual(approx(r["value"]["text"].replace("x", f"({x})")), 3 * x * x, places=9)

    def test_definite_integral(self):
        self.assertEqual(exact("integral(x^2, x, 0, 3)"), "9")
        self.assertAlmostEqual(approx("integral(sin(x), x, 0, pi)"), 2.0, places=12)
        self.assertAlmostEqual(approx("nintegral(exp(-x^2), x, -10, 10)"), math.sqrt(math.pi), places=8)

    def test_limits_and_sums(self):
        self.assertEqual(exact("limit(sin(x)/x, x, 0)"), "1")
        self.assertEqual(exact("sum(k, k, 1, 100)"), "5050")

    def test_solve_polynomial(self):
        r = calc("solve(x^2 - 5*x + 6 = 0)")
        self.assertTrue(r["ok"])
        text = r["value"]["text"]
        self.assertIn("2", text)
        self.assertIn("3", text)

    def test_taylor_series(self):
        r = calc("taylor(exp(x), x, 0, 3)")
        self.assertTrue(r["ok"])
        # 1 + x + x^2/2 + x^3/6 evaluated at x = 1 is 8/3
        self.assertAlmostEqual(approx(r["value"]["text"].replace("x", "(1)")), 8 / 3, places=9)


class LinearAlgebraTests(unittest.TestCase):
    def test_determinant_and_inverse(self):
        self.assertEqual(exact("det([[1,2],[3,4]])"), "-2")
        inv = calc("[[1,2],[3,4]]^-1")
        self.assertTrue(inv["ok"])
        prod = calc("[[1,2],[3,4]] * [[1,2],[3,4]]^-1")
        self.assertEqual(prod["value"]["text"].replace(" ", ""), "[1,0;0,1]")

    def test_singular_matrix_is_an_error(self):
        r = calc("[[1,2],[2,4]]^-1")
        self.assertFalse(r["ok"])


class StatisticsTests(unittest.TestCase):
    def test_descriptive(self):
        self.assertEqual(exact("mean([2,4,4,4,5,5,7,9])"), "5")
        self.assertAlmostEqual(approx("stdp([2,4,4,4,5,5,7,9])"), 2.0, places=12)
        self.assertAlmostEqual(approx("std([2,4,4,4,5,5,7,9])"), math.sqrt(32 / 7), places=10)
        self.assertEqual(exact("median([3,1,2])"), "2")

    def test_normal_distribution(self):
        self.assertAlmostEqual(approx("normalcdf(0)"), 0.5, places=12)
        self.assertAlmostEqual(approx("normalprob(-1.96, 1.96, 0, 1)"), 0.9500042097, places=8)
        self.assertAlmostEqual(approx("invnorm(0.975)"), 1.959963985, places=8)

    def test_binomial(self):
        self.assertAlmostEqual(approx("binompdf(10, 0.5, 3)"), math.comb(10, 3) / 2 ** 10, places=12)


class UnitsTests(unittest.TestCase):
    def test_conversion_with_arrow(self):
        r = calc("12 in -> cm", units=True)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["value"]["text"], "762 / 25 cm")                          # 12 in = 30.48 cm exactly
        self.assertEqual(r["value"]["unit"]["text"], "cm")

    def test_dimension_mismatch(self):
        self.assertFalse(calc("3 m + 2 s", units=True)["ok"])

    def test_unit_arithmetic(self):
        r = calc("5 m/s * 2 s", units=True)
        self.assertTrue(r["ok"])
        self.assertIn("10", r["value"]["text"])


class SessionSemanticsTests(unittest.TestCase):
    def test_definitions_are_replayed_from_context(self):
        d = calc("a := 5")
        self.assertTrue(d["ok"])
        self.assertEqual(calc("a^2 + 1", context=["a := 5"])["value"]["text"], "26")

    def test_function_definition(self):
        r = calc("f(3)", context=["f(x) := x^2 + 1"])
        self.assertEqual(r["value"]["text"], "10")

    def test_undefined_name_explains_itself(self):
        r = calc("q + 1")
        self.assertTrue(r["ok"] and r["flags"]["symbolic"] or not r["ok"])


class ErrorTests(unittest.TestCase):
    def test_syntax_errors_carry_a_span(self):
        r = calc("x+")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "parse_error")
        self.assertIn("span", r["error"])

    def test_division_by_zero(self):
        r = calc("1/0")
        self.assertFalse(r["ok"])
        self.assertTrue(r["error"]["message"])

    def test_wrong_argument_count_gives_signature(self):
        r = calc("sin(1,2)")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "arity")
        self.assertIn("hint", r["error"])

    def test_no_code_execution(self):
        for evil in ("__import__('os').system('echo hi')", "open('/etc/passwd')", "().__class__", "exec('1')", "eval('1+1')", "import os"):
            with self.subTest(evil):
                r = calc(evil)
                self.assertNotIn("root:", str(r))
                if r["ok"]:
                    self.assertNotEqual(r["value"]["text"], "2")

    def test_huge_input_is_refused_not_hung(self):
        r = calc("9" * 100000)
        self.assertFalse(r["ok"])
        r = calc("(" * 5000 + "1" + ")" * 5000)
        self.assertFalse(r["ok"])

    def test_absurd_power_is_bounded(self):
        r = calc("9^9^9^9")
        self.assertFalse(r["ok"])


class ClientExamplesTests(unittest.TestCase):
    """Every example chip offered on the Math page must work as written."""
    def test_examples_run(self):
        src = (Path(__file__).resolve().parent.parent / "src" / "client" / "views" / "math.ts").read_text(encoding="utf-8")
        block = src[src.index("const EXAMPLES"):]
        block = block[: block.index("];")]
        texts = re.findall(r"text: '((?:[^'\\]|\\.)*)'", block)
        self.assertGreaterEqual(len(texts), 6)
        for t in texts:
            with self.subTest(t):
                self.assertTrue(calc(t, units=True)["ok"], calc(t, units=True))


if __name__ == "__main__":
    unittest.main()


class AtomicWriteTests(unittest.TestCase):
    """Saving must work even where the rename step fails (redirected AppData on Windows raised WinError 17 inside one folder)."""

    def setUp(self):
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_normal_write_replaces_the_file_and_leaves_no_temporary(self):
        from pathlib import Path
        from scical.services.fsutil import atomic_write
        p = Path(self.dir.name) / "a" / "x.json"
        atomic_write(p, b"one")
        atomic_write(p, b"two")
        self.assertEqual(p.read_bytes(), b"two")
        self.assertEqual([f.name for f in p.parent.iterdir()], ["x.json"])

    def test_falls_back_to_writing_in_place_when_rename_always_fails(self):
        import os
        from pathlib import Path
        from unittest import mock
        from scical.services import fsutil
        p = Path(self.dir.name) / "y.json"
        err = OSError(17, "cannot move the file to a different disk drive")
        with mock.patch.object(fsutil.os, "replace", side_effect=err), mock.patch.object(fsutil.time, "sleep"):
            fsutil.atomic_write(p, b"saved anyway")
        self.assertEqual(p.read_bytes(), b"saved anyway")
        self.assertEqual([f.name for f in p.parent.iterdir()], ["y.json"])

    def test_a_transient_failure_is_retried(self):
        from pathlib import Path
        from unittest import mock
        from scical.services import fsutil
        p = Path(self.dir.name) / "z.json"
        real = os_replace = fsutil.os.replace
        calls = {"n": 0}

        def flaky(a, b):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError(32, "in use")
            return real(a, b)
        with mock.patch.object(fsutil.os, "replace", side_effect=flaky), mock.patch.object(fsutil.time, "sleep"):
            fsutil.atomic_write(p, b"ok")
        self.assertEqual(calls["n"], 3)
        self.assertEqual(p.read_bytes(), b"ok")
