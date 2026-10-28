"""3D sampling (scical.core.graphing.space) against known mathematics: surfaces, parametric surfaces, curves and point sets.

Every check states its tolerance. The sampler works in float64; the browser result is rounded to 9 significant digits (relative error <= 5e-9) and
its normals to 5 digits, so tolerances below are chosen from that, not fitted to what happens to pass.
"""
import math
import unittest

import numpy as np

from scical.services.tasks import run

R9 = 1e-8          # a value rounded to 9 significant digits is within 5e-9 relative; allow 1e-8
R5 = 2e-5          # normals are rounded to 5 significant digits


def scene(layers, domain=None, samples=None, params=None, settings=None, op="render3d"):
    spec = {"mode": "3d", "domain": domain or {"xmin": -2, "xmax": 2, "ymin": -2, "ymax": 2}, "params": params or {}, "layers": layers}
    if samples is not None:
        spec["samples"] = {"u": samples, "v": samples}
    return run({"kind": "graph", "op": op, "spec": spec, "settings": settings or {}, "context": None})


def surf(expr, **kw):
    return {"id": "S", "type": "surface", "expr": expr, **kw}


def arr(layer, key="vertices"):
    return np.array(layer[key], dtype=float).reshape(-1, 3 if key != "cells" else 4)


def cell_triangles(layer):
    V = arr(layer)
    C = np.array(layer["cells"], dtype=int).reshape(-1, 4)
    tri = np.empty((2 * len(C), 3), dtype=int)
    tri[0::2] = C[:, [0, 1, 2]]
    tri[1::2] = C[:, [0, 2, 3]]
    return V, tri


class ExplicitSurfaceTests(unittest.TestCase):
    def test_vertices_lie_on_the_surface(self):
        r = scene([surf("x^2 + y^2")], samples=30)
        self.assertTrue(r["ok"])
        lr = r["layers"][0]
        self.assertTrue(lr["ok"], lr)
        V = arr(lr)
        self.assertEqual(len(V), 30 * 30)
        np.testing.assert_allclose(V[:, 2], V[:, 0] ** 2 + V[:, 1] ** 2, rtol=R9, atol=R9)

    def test_z_equals_form_is_accepted_and_labelled(self):
        r = scene([surf("z = sin(x)*cos(y)")], samples=12)
        self.assertEqual(r["layers"][0]["label"], "z = sin(x) * cos(y)")
        self.assertEqual(r["layers"][0]["definition"]["type"], "surface")

    def test_domain_and_sample_counts_are_respected(self):
        r = scene([surf("x + y")], domain={"xmin": 1, "xmax": 3, "ymin": -4, "ymax": 4}, samples=9)
        lr = r["layers"][0]
        V = arr(lr)
        self.assertEqual((lr["grid"]["nu"], lr["grid"]["nv"]), (9, 9))
        self.assertAlmostEqual(V[:, 0].min(), 1.0, delta=R9)
        self.assertAlmostEqual(V[:, 0].max(), 3.0, delta=R9)
        self.assertAlmostEqual(V[:, 1].min(), -4.0, delta=R9)
        self.assertEqual(len(lr["cells"]), 8 * 8 * 4)

    def test_triangles_are_counter_clockwise_seen_from_plus_z(self):
        r = scene([surf("sin(x)*cos(y)")], samples=20)
        V, tri = cell_triangles(r["layers"][0])
        p = V[tri]
        cross_z = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0])
        self.assertTrue((cross_z > 0).all(), "an explicit surface must wind counter-clockwise when seen from +z")

    def test_normals_of_a_plane(self):
        r = scene([surf("x + 2*y")], samples=10)
        N = arr(r["layers"][0], "normals")
        expected = np.array([-1.0, -2.0, 1.0]) / math.sqrt(6)
        np.testing.assert_allclose(N, np.tile(expected, (len(N), 1)), atol=R5)

    def test_normals_are_unit_length_and_face_up_for_a_graph(self):
        r = scene([surf("sin(x)*cos(y)")], samples=25)
        N = arr(r["layers"][0], "normals")
        np.testing.assert_allclose(np.linalg.norm(N, axis=1), 1.0, atol=R5)
        self.assertTrue((N[:, 2] > 0).all())

    def test_normals_of_a_paraboloid_match_the_gradient(self):
        # interior vertices only: the area-weighted normal is a second-order approximation of (-f_x, -f_y, 1)
        n = 41
        r = scene([surf("x^2 + y^2")], domain={"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}, samples=n)
        lr = r["layers"][0]
        V, N = arr(lr), arr(lr, "normals")
        inner = (np.abs(V[:, 0]) < 0.9) & (np.abs(V[:, 1]) < 0.9)
        g = np.stack([-2 * V[:, 0], -2 * V[:, 1], np.ones(len(V))], axis=1)
        g /= np.linalg.norm(g, axis=1, keepdims=True)
        self.assertLess(np.linalg.norm(N[inner] - g[inner], axis=1).max(), 2e-3)

    def test_a_slider_value_is_used_and_a_missing_one_is_reported(self):
        missing = scene([surf("a*x")], samples=8)["layers"][0]
        self.assertFalse(missing["ok"])
        self.assertIn("'a' has no value", missing["error"]["message"])
        given = scene([surf("a*x")], samples=8, params={"a": 3})["layers"][0]
        V = arr(given)
        np.testing.assert_allclose(V[:, 2], 3 * V[:, 0], rtol=R9, atol=R9)

    def test_angle_mode_follows_the_settings(self):
        r = scene([surf("sin(x) + 0*y")], domain={"xmin": 0, "xmax": 90, "ymin": 0, "ymax": 1}, samples=4, settings={"angle": "deg"})
        V = arr(r["layers"][0])
        np.testing.assert_allclose(V[:, 2], np.sin(np.radians(V[:, 0])), atol=R9)
        self.assertEqual(r["angle"], "deg")

    def test_hidden_layers_are_not_computed_and_do_not_count_in_the_bounds(self):
        r = scene([surf("x + y", id="A"), {"id": "B", "type": "surface", "expr": "100*x", "visible": False}], samples=6)
        self.assertEqual(r["layers"][1], {"id": "B", "ok": True, "type": "hidden"})
        self.assertLess(r["bounds"]["zmax"], 10)

    def test_bounds_cover_all_layers(self):
        r = scene([surf("x + y", id="A"), {"id": "C", "type": "curve3d", "x": "0", "y": "0", "z": "t", "tmin": "-7", "tmax": "9"}], samples=6)
        b = r["bounds"]
        self.assertAlmostEqual(b["zmin"], -7.0, delta=1e-6)
        self.assertAlmostEqual(b["zmax"], 9.0, delta=1e-6)


class UndefinedRegionTests(unittest.TestCase):
    def test_square_root_of_a_negative_leaves_a_hole_not_a_bridge(self):
        r = scene([surf("sqrt(1 - x^2 - y^2)")], samples=41)
        lr = r["layers"][0]
        V = arr(lr)
        self.assertGreater(lr["stats"]["undefined"], 0)
        self.assertTrue(np.isfinite(V).all())
        self.assertLessEqual((V[:, 0] ** 2 + V[:, 1] ** 2).max(), 1 + 1e-9, "no vertex may lie where the formula is not real")
        self.assertTrue(any("undefined" in w for w in lr["warnings"]))
        # every face is made of defined corners only, so none can reach across the hole
        C = np.array(lr["cells"], dtype=int).reshape(-1, 4)
        self.assertGreater(len(C), 0)
        self.assertLess(len(C), 40 * 40)

    def test_a_pole_is_a_hole_and_nothing_overflows(self):
        r = scene([surf("1/(x^2 + y^2)")], domain={"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}, samples=21)   # odd count: a sample sits exactly on the pole
        lr = r["layers"][0]
        V = arr(lr)
        self.assertTrue(np.isfinite(V).all())
        self.assertLess(np.abs(V).max(), 1e12)
        self.assertGreaterEqual(lr["stats"]["undefined"], 1)
        self.assertFalse(np.any((np.abs(V[:, 0]) < 1e-12) & (np.abs(V[:, 1]) < 1e-12)), "the pole itself is not a vertex")

    def test_a_jump_discontinuity_is_not_bridged(self):
        r = scene([surf("1/x + 0*y")], domain={"xmin": -1, "xmax": 1, "ymin": 0, "ymax": 1}, samples=20)      # even count: no sample at x = 0
        lr = r["layers"][0]
        V, C = arr(lr), np.array(lr["cells"], dtype=int).reshape(-1, 4)
        xs = V[C][:, :, 0]
        self.assertTrue(((xs > 0).all(axis=1) | (xs < 0).all(axis=1)).all(), "no cell may join the two sides of x = 0")
        self.assertGreater(lr["stats"]["brokenCells"] + lr["stats"]["clipped"], 0)

    def test_a_complex_intermediate_is_undefined(self):
        r = scene([surf("sqrt(x) + 0*y")], domain={"xmin": -1, "xmax": 1, "ymin": 0, "ymax": 1}, samples=11)
        V = arr(r["layers"][0])
        self.assertGreaterEqual(V[:, 0].min(), -1e-12)

    def test_overflow_is_undefined(self):
        r = scene([surf("exp(x^2 + y^2)")], domain={"xmin": -40, "xmax": 40, "ymin": -40, "ymax": 40}, samples=9)
        V = arr(r["layers"][0]) if r["layers"][0]["ok"] and r["layers"][0].get("vertices") else np.zeros((0, 3))
        self.assertTrue(np.isfinite(V).all())
        self.assertTrue((np.abs(V) < 1e12).all())

    def test_nothing_defined_says_so(self):
        r = scene([surf("sqrt(-1 - x^2 - y^2)")], samples=8)
        lr = r["layers"][0]
        self.assertTrue(lr["ok"])
        self.assertEqual(lr["cells"], [])
        self.assertIn("No part of this surface is defined", lr["warnings"][0])

    def test_a_manual_z_window_cuts_off_what_is_outside(self):
        r = scene([surf("x^2 + y^2", zmin=0, zmax=2)], samples=21)
        V = arr(r["layers"][0])
        self.assertLessEqual(V[:, 2].max(), 2 + 1e-9)
        self.assertGreater(r["layers"][0]["stats"]["clipped"], 0)


class LimitTests(unittest.TestCase):
    def test_sample_counts_are_bounded(self):
        for bad in (1, 161, 0, -5):
            with self.subTest(samples=bad):
                lr = scene([surf("x + y")], samples=bad)["layers"][0]
                self.assertFalse(lr["ok"])
                self.assertEqual(lr["error"]["code"], "bad_request")
        self.assertTrue(scene([surf("x + y")], samples=160)["layers"][0]["ok"])

    def test_too_many_layers(self):
        r = scene([surf("x", id=f"L{i}") for i in range(13)], samples=4)
        self.assertFalse(r["ok"])
        self.assertIn("at most", r["error"]["message"])

    def test_a_reversed_domain_is_refused(self):
        lr = scene([surf("x")], domain={"xmin": 3, "xmax": 1, "ymin": 0, "ymax": 1}, samples=4)
        self.assertFalse(lr["ok"] and lr["layers"][0]["ok"])

    def test_an_unknown_layer_type_is_refused_per_layer(self):
        r = scene([{"id": "Z", "type": "implicit3d", "expr": "x"}], samples=4)
        self.assertFalse(r["layers"][0]["ok"])

    def test_an_implicit_surface_is_not_silently_turned_into_something_else(self):
        lr = scene([surf("x^2 + y^2 + z^2 = 1")], samples=6)["layers"][0]
        self.assertFalse(lr["ok"])
        self.assertIn("z = f(x, y)", lr["error"]["message"])


class ParametricTests(unittest.TestCase):
    SPHERE = {"id": "P", "type": "psurface", "x": "cos(u)*sin(v)", "y": "sin(u)*sin(v)", "z": "cos(v)", "umin": "0", "umax": "2*pi", "vmin": "0", "vmax": "pi"}

    def test_sphere_points_have_unit_radius(self):
        lr = scene([self.SPHERE], samples=24)["layers"][0]
        self.assertTrue(lr["ok"], lr)
        V = arr(lr)
        np.testing.assert_allclose(np.linalg.norm(V, axis=1), 1.0, atol=R9)

    def test_pole_triangles_are_dropped_and_counted(self):
        lr = scene([self.SPHERE], samples=24)["layers"][0]
        cells = lr["stats"]["cells"]
        self.assertLess(lr["stats"]["triangles"], 2 * cells, "the collapsed triangles at the poles must not be exported")
        self.assertGreaterEqual(lr["stats"]["triangles"], 2 * cells - 4 * 24)

    def test_front_side_is_the_cross_product_of_the_partial_derivatives(self):
        # for this parametrisation dr/du x dr/dv points INTO the sphere; the documented convention is that this is the front side
        lr = scene([self.SPHERE], samples=24)["layers"][0]
        V, N = arr(lr), arr(lr, "normals")
        dots = (V * N).sum(axis=1)
        mid = (np.abs(V[:, 2]) < 0.9)
        self.assertLess(dots[mid].max(), -0.99)

    def test_normals_of_a_torus_are_unit_and_consistent(self):
        torus = {"id": "T", "type": "psurface", "x": "(2 + cos(v))*cos(u)", "y": "(2 + cos(v))*sin(u)", "z": "sin(v)", "umin": "0", "umax": "2*pi", "vmin": "0", "vmax": "2*pi"}
        lr = scene([torus], samples=40)["layers"][0]
        V, N = arr(lr), arr(lr, "normals")
        np.testing.assert_allclose(np.linalg.norm(N, axis=1), 1.0, atol=R5)
        # the outward normal of a torus at (u, v) is (cos v cos u, cos v sin u, sin v); the parametrisation gives a consistent sign
        u = np.arctan2(V[:, 1], V[:, 0])
        rho = np.hypot(V[:, 0], V[:, 1]) - 2
        outward = np.stack([rho * np.cos(u), rho * np.sin(u), V[:, 2]], axis=1)
        outward /= np.linalg.norm(outward, axis=1, keepdims=True)
        d = (outward * N).sum(axis=1)
        seam = (np.abs(V[:, 1]) < 1e-6) | (np.abs(V[:, 2]) > 0.999999)
        self.assertTrue((np.abs(d[~seam]) > 0.97).all())
        self.assertTrue((d[~seam] > 0).all() or (d[~seam] < 0).all(), "one consistent side")

    def test_a_missing_parameter_range_defaults_to_a_full_turn(self):
        lr = scene([{"id": "P", "type": "psurface", "x": "cos(u)", "y": "sin(u)", "z": "v"}], samples=12)["layers"][0]
        self.assertTrue(lr["ok"])
        d = lr["definition"]["domain"]
        self.assertAlmostEqual(d["u"][1], 2 * math.pi, places=9)

    def test_psurface_rejects_the_wrong_variables(self):
        lr = scene([{"id": "P", "type": "psurface", "x": "x", "y": "u", "z": "v"}], samples=6)["layers"][0]
        self.assertFalse(lr["ok"])


class CurveTests(unittest.TestCase):
    def test_helix_points_lie_on_the_helix(self):
        h = {"id": "C", "type": "curve3d", "x": "cos(t)", "y": "sin(t)", "z": "t/4", "tmin": "0", "tmax": "6*pi", "samples": 200}
        lr = scene([h])["layers"][0]
        self.assertTrue(lr["ok"])
        self.assertEqual(len(lr["segments"]), 1)
        P = np.array(lr["segments"][0]).reshape(-1, 3)
        self.assertEqual(len(P), 200)
        np.testing.assert_allclose(np.hypot(P[:, 0], P[:, 1]), 1.0, atol=R9)
        t = np.linspace(0, 6 * math.pi, 200)
        np.testing.assert_allclose(P[:, 2], t / 4, atol=1e-7)

    def test_a_curve_is_cut_at_a_pole_not_joined_across_it(self):
        c = {"id": "C", "type": "curve3d", "x": "t", "y": "0", "z": "tan(t)", "tmin": "-2", "tmax": "2", "samples": 401}
        lr = scene([c])["layers"][0]
        self.assertEqual(len(lr["segments"]), 3, "poles at -pi/2 and +pi/2 inside [-2, 2] give three pieces")
        for seg in lr["segments"]:
            P = np.array(seg).reshape(-1, 3)
            z = P[:, 2]
            flips = (np.sign(z[:-1]) != np.sign(z[1:])) & (np.abs(z[:-1]) + np.abs(z[1:]) > 10)
            self.assertFalse(flips.any(), "a piece must not jump from +large to -large across a pole (the genuine zero at t = 0 has |z| < 1)")

    def test_undefined_samples_split_a_curve(self):
        c = {"id": "C", "type": "curve3d", "x": "t", "y": "sqrt(t)", "z": "0", "tmin": "-1", "tmax": "1", "samples": 101}
        lr = scene([c])["layers"][0]
        P = np.array(lr["segments"][0]).reshape(-1, 3)
        self.assertGreaterEqual(P[:, 0].min(), -1e-12)
        self.assertGreater(lr["stats"]["undefined"], 0)

    def test_curve_sample_bounds(self):
        bad = scene([{"id": "C", "type": "curve3d", "x": "t", "y": "t", "z": "t", "tmin": "0", "tmax": "1", "samples": 1}])["layers"][0]
        self.assertFalse(bad["ok"])


class PointTests(unittest.TestCase):
    def test_points_are_kept_exactly(self):
        pts = {"id": "Q", "type": "points3d", "x": ["0", "1.5", "-2"], "y": ["1", "2", "3"], "z": ["0.25", "pi", "1e3"]}
        lr = scene([pts])["layers"][0]
        P = np.array(lr["points"]).reshape(-1, 3)
        np.testing.assert_allclose(P, [[0, 1, 0.25], [1.5, 2, math.pi], [-2, 3, 1000]], atol=R9, rtol=R9)

    def test_columns_must_have_equal_length(self):
        lr = scene([{"id": "Q", "type": "points3d", "x": [1, 2], "y": [1], "z": [1, 2]}])["layers"][0]
        self.assertFalse(lr["ok"])

    def test_an_empty_set_is_refused(self):
        self.assertFalse(scene([{"id": "Q", "type": "points3d", "x": [], "y": [], "z": []}])["layers"][0]["ok"])


class FullPrecisionExportTests(unittest.TestCase):
    def test_export_sample_is_not_rounded_to_nine_digits(self):
        spec = {"id": "S", "type": "surface", "expr": "x^2 + y^2"}
        shown = scene([spec], domain={"xmin": 0, "xmax": 1, "ymin": 0, "ymax": 1}, samples=7)["layers"][0]
        full = scene([spec], domain={"xmin": 0, "xmax": 1, "ymin": 0, "ymax": 1}, samples=7, op="sample3d")
        self.assertTrue(full["ok"])
        L = full["layers"][0]
        V = np.array(L["vertices"])
        expected = np.linspace(0, 1, 7)
        self.assertEqual(V[:, 0].tolist()[:7], [expected[0]] * 7)           # full float64 values, not 9-digit approximations
        self.assertEqual(sorted(set(V[:, 0].tolist())), expected.tolist())
        self.assertEqual(len(L["gridIndex"]), len(V))
        np.testing.assert_allclose(V, arr(shown), rtol=R9, atol=R9)

    def test_export_sample_keeps_the_grid_index_of_every_vertex(self):
        L = scene([surf("sqrt(1 - x^2 - y^2)")], samples=15, op="sample3d")["layers"][0]
        gi = np.array(L["gridIndex"])
        nu, nv = L["grid"]
        V = np.array(L["vertices"])
        xs = np.linspace(-2, 2, nu)
        ys = np.linspace(-2, 2, nv)
        np.testing.assert_allclose(V[:, 0], xs[gi // nv], atol=0, rtol=0)
        np.testing.assert_allclose(V[:, 1], ys[gi % nv], atol=0, rtol=0)

    def test_failed_layers_are_listed_with_their_error(self):
        full = scene([surf("a*x", id="A"), surf("x", id="B")], samples=5, op="sample3d")
        self.assertFalse(full["layers"][0]["ok"])
        self.assertIn("has no value", full["layers"][0]["error"]["message"])
        self.assertTrue(full["layers"][1]["ok"])


if __name__ == "__main__":
    unittest.main()
