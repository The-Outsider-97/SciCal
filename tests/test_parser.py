import unittest

from scical.core.expressions import ParseOptions, parse
from scical.core.expressions import ast as A
from scical.core.expressions.printer import to_latex, to_text
from scical.errors import ParseError

ROUND_TRIP = [
    "-2^2", "(-2)^2", "1/2x", "2^3^2", "(2^3)^2", "2^-3", "2^(a+b)", "sin^2(x)", "3(x+1)", "|x-1|+2", "sqrt2 x" if False else "√2 x",
    "[1,2;3,4]", "f(x,y):=x^2+y", "a:=3", "x<=3 and y>1", "1<x<5", "2e3", "n!", "(n+1)!", "50%", "sin(30°)", "x(3)", "2pi",
    "a-(b-c)", "a-b-c", "a/(b/c)", "a/b/c", "(a+b)*c", "not (x>1)", "x>1 or y<2 and z=3", "(x>1 or y<2) and z=3", "-(a+b)",
    "a mod b", "x^y^z", "2x^2", "(-x)^2", "-x^2", "diff(x^2,x)", "integrate(sin(x),x,0,pi)", "x²+y³", "a/-b", "alpha_1 x",
]


class ParserTests(unittest.TestCase):
    def test_round_trip(self):
        for s in ROUND_TRIP:
            with self.subTest(s=s):
                node = parse(s).node
                self.assertEqual(parse(to_text(node)).node, node)

    def test_precedence(self):
        n = parse("-2^2").node
        self.assertIsInstance(n, A.Unary)
        self.assertEqual(n.arg.op, "^")
        n = parse("2^3^2").node
        self.assertEqual(n.right.op, "^")                       # right associative
        n = parse("1/2x").node
        self.assertEqual((n.op, n.left.op), ("*", "/"))         # (1/2)x
        self.assertTrue(parse("1/2x").warnings)
        self.assertFalse(parse("1/(2x)").warnings)

    def test_scientific_notation_is_one_number(self):
        self.assertEqual(parse("2e3").node, A.Num(text="2e3"))
        n = parse("2 e^3").node                                  # Euler's number, not 2000
        self.assertIsInstance(n, A.Binary)

    def test_chained_comparison(self):
        n = parse("1<x<5").node
        self.assertIsInstance(n, A.Logic)
        self.assertEqual(len(n.args), 2)

    def test_matrix_shape_checked(self):
        with self.assertRaises(ParseError):
            parse("[1,2;3]")

    def test_errors_carry_spans(self):
        for text, span in (("3 +", (3, 3)), ("(1+2", (4, 4)), ("1+)", (2, 3)), ("@", (0, 1))):
            with self.subTest(text=text):
                with self.assertRaises(ParseError) as cm:
                    parse(text)
                self.assertEqual(tuple(cm.exception.span), span)

    def test_no_eval_of_python(self):
        for bad in ("__import__('os')", "().__class__", "open('x')", "lambda: 1", "a.b"):
            with self.subTest(bad=bad):
                with self.assertRaises(ParseError):
                    parse(bad)

    def test_depth_limit(self):
        with self.assertRaises(ParseError):
            parse("(" * 500 + "1" + ")" * 500)

    def test_length_limit(self):
        with self.assertRaises(ParseError):
            parse("1+" * 6000 + "1")

    def test_units(self):
        n = parse("5 m/s -> km/h", ParseOptions(units=True)).node
        self.assertIsInstance(n, A.Convert)
        self.assertIsInstance(n.expr, A.Qty)
        n = parse("9.81 m/s^2 * 2 s", ParseOptions(units=True)).node
        self.assertIn("*", n.op)

    def test_variable_beats_unit(self):
        n = parse("5 m", ParseOptions(units=True, variables=frozenset({"m"}))).node
        self.assertIsInstance(n, A.Binary)

    def test_latex(self):
        self.assertEqual(to_latex(parse("a/b").node), r"\frac{a}{b}")
        self.assertEqual(to_latex(parse("sqrt(x)").node), r"\sqrt{x}")


if __name__ == "__main__":
    unittest.main()
