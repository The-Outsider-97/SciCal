"""Graph rendering and analysis against known mathematics."""
import math
import unittest

from scical.services.tasks import run

VP = {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10}


def L(i, **kw):
    return {"id": i, "type": "auto", **kw}


def render(layers, viewport=VP, params=None):
    return run({"kind": "graph", "op": "render", "spec": {"viewport": viewport, "width": 800, "height": 600, "params": params or {}, "layers": layers}, "settings": {}, "context": None})


def analyze(kind, layers, viewport=VP, **extra):
    return run({"kind": "graph", "op": "analyze", "spec": {"kind": kind, "viewport": viewport, "params": {}, "layers": layers, **extra}, "settings": {}, "context": None})


class RenderTests(unittest.TestCase):
    def test_layer_types_are_recognised(self):
        r = render([L("a", expr="x^2-4"), L("b", expr="x^2+y^2=9"), L("c", expr="y > x"), L("d", expr="1/x")])
        self.assertTrue(r["ok"])
        self.assertEqual([l["type"] for l in r["layers"]], ["function", "implicit", "inequality", "function"])

    def test_curve_points_lie_on_the_curve(self):
        r = render([L("a", expr="x^2 - 4")])
        pts = [p for seg in r["layers"][0]["segments"] for p in seg]
        self.assertGreater(len(pts), 100)
        for x, y in pts:
            self.assertAlmostEqual(y, x * x - 4, places=6)

    def test_circle_points_have_radius_three(self):
        r = render([L("b", expr="x^2 + y^2 = 9")])
        pts = [p for line in r["layers"][0]["polylines"] for p in line]
        self.assertGreater(len(pts), 50)
        for x, y in pts:
            self.assertAlmostEqual(math.hypot(x, y), 3.0, delta=0.02)

    def test_asymptote_is_found_and_curve_is_broken_there(self):
        layer = render([L("d", expr="1/x")])["layers"][0]
        self.assertIn(0.0, layer["asymptotes"])
        self.assertGreaterEqual(len(layer["segments"]), 2)                       # two branches, no line drawn across x = 0

    def test_slider_parameter(self):
        r = render([L("a", expr="a*x")], params={"a": 3})
        pts = [p for seg in r["layers"][0]["segments"] for p in seg]
        for x, y in pts[::20]:
            self.assertAlmostEqual(y, 3 * x, places=6)

    def test_missing_parameter_is_reported_per_layer(self):
        r = render([L("a", expr="b*x"), L("ok", expr="x")])
        self.assertTrue(r["ok"])
        self.assertFalse(r["layers"][0]["ok"])
        self.assertTrue(r["layers"][1]["ok"])

    def test_parametric_and_polar(self):
        r = render([{"id": "p", "type": "parametric", "x": "cos(t)", "y": "sin(t)", "tmin": "0", "tmax": "2*pi"},
                    {"id": "q", "type": "polar", "r": "2", "tmin": "0", "tmax": "2*pi"}])
        for layer, radius in ((r["layers"][0], 1.0), (r["layers"][1], 2.0)):
            pts = [p for seg in layer["segments"] for p in seg]
            self.assertGreater(len(pts), 50)
            for x, y in pts:
                self.assertAlmostEqual(math.hypot(x, y), radius, places=6)

    def test_scatter_fit_recovers_a_line(self):
        r = render([{"id": "s", "type": "scatter", "x": ["0", "1", "2", "3"], "y": ["1", "3", "5", "7"], "fit": "linear"}])
        fit = r["layers"][0]["fit"]
        self.assertAlmostEqual(fit["r2"], 1.0, places=9)


class AnalysisTests(unittest.TestCase):
    def test_roots(self):
        r = analyze("roots", [L("a", expr="x^2-4")], layer="a")
        self.assertEqual([round(p["x"], 6) for p in r["points"]], [-2.0, 2.0])
        r = analyze("roots", [L("a", expr="sin(x)")], layer="a", viewport={"xmin": -7, "xmax": 7, "ymin": -2, "ymax": 2})
        xs = [round(p["x"], 6) for p in r["points"]]
        for k in (-2, -1, 0, 1, 2):
            self.assertTrue(any(abs(x - k * math.pi) < 1e-6 for x in xs), (k, xs))

    def test_extrema(self):
        r = analyze("extrema", [L("e", expr="x^3 - 3*x")], layer="e")
        by = {p["kind"]: p for p in r["points"]}
        self.assertAlmostEqual(by["maximum"]["x"], -1.0, delta=1e-6)
        self.assertAlmostEqual(by["maximum"]["y"], 2.0, delta=1e-9)
        self.assertAlmostEqual(by["minimum"]["x"], 1.0, delta=1e-6)

    def test_integral(self):
        self.assertAlmostEqual(analyze("integral", [L("a", expr="x^2")], layer="a", a="0", b="3")["value"], 9.0, places=10)
        self.assertAlmostEqual(analyze("integral", [L("a", expr="sin(x)")], layer="a", a="0", b="pi")["value"], 2.0, places=10)

    def test_intersections(self):
        r = analyze("intersection", [L("a", expr="x^2"), L("b", expr="2*x + 3")], layer="a", layer2="b")
        self.assertEqual([round(p["x"], 6) for p in r["points"]], [-1.0, 3.0])

    def test_tangent_is_exact(self):
        r = analyze("tangent", [L("a", expr="x^2 - 4")], layer="a", x="1")
        self.assertFalse(r["approximate"])
        self.assertEqual((r["slope"], r["intercept"]), (2.0, -5.0))
        self.assertEqual(r["exact"]["equation"], "y = 2x - 5")

    def test_analysis_marks_itself_approximate(self):
        self.assertTrue(analyze("roots", [L("a", expr="x^2-4")], layer="a")["approximate"])

    def test_bad_requests_are_answers(self):
        self.assertFalse(analyze("roots", [], layer="nope")["ok"])
        self.assertFalse(analyze("bogus", [L("a", expr="x")], layer="a")["ok"])


if __name__ == "__main__":
    unittest.main()
