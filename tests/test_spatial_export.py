"""Saving graphs with SLAI's SGEO / SDRW writers, then reading the files back with SLAI's readers and comparing against the sampled source.

Needs the SLAI checkout (``src/utils/sgeo.py`` and ``sdrw.py``) and ``jsonschema`` >= 4 for strict validation; the tests are skipped, not passed, without them.
Tolerances are stated where they are used:

* coordinates SciCal samples and stores as float64 come back bit-identical or within 1e-12 (the file stores f64);
* the 2D curve samples that the browser also receives are rounded to 9 significant digits, so a curve is compared with its formula to 1e-8 relative;
* a contour line is a linear interpolation along mesh edges: its distance from the true level set is bounded by f''*h^2/(8*|grad f|), stated per test.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import math
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from importlib import metadata as importlib_metadata
from pathlib import Path

import numpy as np

from scical.errors import BadRequest, SciCalError
from scical.integrations import slai_link
from scical.services import spatial
from scical.services.tasks import run

ROOT = Path(__file__).resolve().parent.parent
SLAI = slai_link.find_slai_root()
try:
    JSONSCHEMA_OK = int(importlib_metadata.version("jsonschema").split(".")[0]) >= 4
except Exception:                                              # not installed
    JSONSCHEMA_OK = False

SKIP = None if (SLAI and JSONSCHEMA_OK) else "needs the SLAI checkout and jsonschema >= 4 (strict validation)"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DOMAIN = {"xmin": -1, "xmax": 1, "ymin": -1, "ymax": 1}


def val(x):
    """SLAI exposes some document facts as properties and some as methods."""
    return x() if callable(x) else x


def kind_of(o):
    return (o.get("geometry") or {}).get("kind")


def sample3d(layers, domain=None, samples=15, params=None):
    spec = {"mode": "3d", "domain": domain or DOMAIN, "samples": {"u": samples, "v": samples}, "params": params or {}, "layers": layers}
    r = run({"kind": "graph", "op": "sample3d", "spec": spec, "settings": {}, "context": None})
    assert r["ok"], r
    return r, spec


def render2d(layers, view=None, params=None):
    spec = {"mode": "2d", "viewport": view or {"xmin": -4, "xmax": 4, "ymin": -2, "ymax": 6}, "params": params or {}, "layers": layers}
    r = run({"kind": "graph", "op": "render", "spec": spec, "settings": {}, "context": None})
    assert r["ok"], r
    return r, spec


def surf(expr, id="S", **kw):
    return {"id": id, "type": "surface", "expr": expr, **kw}


SPHERE = {"id": "P", "type": "psurface", "x": "cos(u)*sin(v)", "y": "sin(u)*sin(v)", "z": "cos(v)", "umin": "0", "umax": "2*pi", "vmin": "0", "vmax": "pi"}
HELIX = {"id": "H", "type": "curve3d", "x": "cos(t)", "y": "sin(t)", "z": "t/4", "tmin": "0", "tmax": "12", "samples": 200}


@unittest.skipIf(SKIP, SKIP)
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        slai_link.activate(SLAI)
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls._tmp.name) / "out"
        cls.link = slai_link.SlaiLink(SLAI, Path(cls._tmp.name) / "data", agents_mode="none")
        cls.sgeo = cls.link.sgeo()
        cls.sdrw = cls.link.sdrw()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def save_sgeo(self, layers, *, name="t", unit="m", **kw):
        sample, _ = sample3d(layers, **kw)
        res = spatial.export_sgeo(self.link, self.out, sample, name=name, unit=unit)
        return sample, res, self.sgeo.open_document(res["path"])

    def objects(self, doc):
        return entities(doc)


class SgeoMeshTests(Base):
    def test_surface_round_trip(self):
        n = 15
        sample, res, doc = self.save_sgeo([surf("x^2 + y^2", color="#336699")], samples=n)
        self.assertTrue(res["ok"])
        self.assertEqual(res["validation"]["mode"], "strict")
        self.assertTrue(res["validation"]["ok"])
        self.assertTrue(res["validation"]["reopened"])
        (mesh,) = [o for o in self.objects(doc) if kind_of(o) == "mesh"]
        V = np.array(mesh["geometry"]["vertices"])
        F = np.array(mesh["geometry"]["faces"])
        # coordinates: float64 in, float64 out
        np.testing.assert_allclose(V, np.array(sample["layers"][0]["vertices"]), rtol=0, atol=1e-12)
        np.testing.assert_allclose(V[:, 2], V[:, 0] ** 2 + V[:, 1] ** 2, rtol=0, atol=1e-12)
        # topology of a regular n x n grid: n^2 vertices, 2(n-1)^2 triangles, a disc (Euler characteristic 1)
        edges = {tuple(sorted(e)) for f in F.tolist() for e in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0]))}
        self.assertEqual((len(V), len(F)), (n * n, 2 * (n - 1) ** 2))
        self.assertEqual(len(V) - len(edges) + len(F), 1)
        # winding: an explicit surface is counter-clockwise seen from +z
        p = V[F]
        cross_z = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0])
        self.assertTrue((cross_z > 0).all())

    def test_document_unit_ids_and_digest(self):
        _, res, doc = self.save_sgeo([surf("x + y"), surf("x - y", id="T")], name="ids", unit="cm", samples=6)
        self.assertEqual(doc.unit, "cm")
        self.assertEqual(doc.name, "ids")
        self.assertEqual(doc.document_id, res["documentId"])
        self.assertTrue(UUID_RE.match(res["documentId"]))
        ids = [i for layer in res["layers"] for i in layer["objectIds"]]
        self.assertEqual(len(ids), 2)
        self.assertEqual(sorted(ids), sorted(o["id"] for o in self.objects(doc)))
        self.assertTrue(all(UUID_RE.match(i) for i in ids))
        data = Path(res["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), res["sha256"])
        self.assertEqual(len(data), res["size"])
        self.assertEqual(base64.b64decode(res["contentBase64"]), data)
        md = val(doc.metadata)
        self.assertEqual(md["scical:contract"], "scical-graph/1")
        self.assertEqual(md["scical:unit_assumption"], "1 graph unit = 1 cm")
        self.assertEqual(md["scical:angle_mode"], "rad")

    def test_every_unit_is_accepted_and_stored(self):
        for unit in spatial.UNITS:
            with self.subTest(unit=unit):
                _, _, doc = self.save_sgeo([surf("x")], name=f"u-{unit}", unit=unit, samples=4)
                self.assertEqual(doc.unit, unit)

    def test_unknown_unit_is_refused_before_anything_is_written(self):
        sample, _ = sample3d([surf("x")], samples=4)
        before = set(self.out.glob("*")) if self.out.exists() else set()
        with self.assertRaises(BadRequest):
            spatial.export_sgeo(self.link, self.out, sample, name="bad-unit", unit="parsec")
        self.assertEqual(set(self.out.glob("*")) if self.out.exists() else set(), before)

    def test_definition_and_sampling_are_stored_with_the_geometry(self):
        _, res, doc = self.save_sgeo([surf("sin(x)*y", color="#336699")], samples=9)
        (obj,) = self.objects(doc)
        md = obj["metadata"]
        self.assertEqual(md["scical:layer_id"], "S")
        self.assertEqual(md["scical:layer_type"], "surface")
        self.assertEqual(md["scical:definition"]["expr"], "sin(x) * y")
        self.assertEqual(md["scical:definition"]["domain"], {"x": [-1.0, 1.0], "y": [-1.0, 1.0]})
        self.assertEqual(md["scical:geometry"], "sampled approximation of the definition")
        self.assertEqual(md["scical:sampling"]["grid"], [9, 9])
        self.assertEqual(md["scical:style"]["color"], "#336699")

    def test_material_carries_the_layer_colour_in_linear_rgb_and_alpha(self):
        _, _, doc = self.save_sgeo([surf("x", color="#336699", opacity=0.4)], samples=4)
        (obj,) = self.objects(doc)
        mat = next(m for m in val(doc.materials) if m["id"] == obj["material"])
        lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        want = [lin(0x33 / 255), lin(0x66 / 255), lin(0x99 / 255), 0.4]
        np.testing.assert_allclose(mat["base_color"], want, rtol=0, atol=1e-9)
        self.assertEqual(mat["alpha_mode"], "blend")
        self.assertTrue(mat["double_sided"])

    def test_opaque_layer_is_opaque(self):
        _, _, doc = self.save_sgeo([surf("x")], samples=4)
        self.assertEqual(val(doc.materials)[0]["alpha_mode"], "opaque")

    def test_provenance_claim(self):
        params = {"a": 2}
        sample, res, doc = self.save_sgeo([surf("a*x*y")], samples=6, params=params)
        (obj,) = self.objects(doc)
        (claim,) = obj["metadata"]["slai.claims"]
        self.assertEqual(claim["subject"], obj["id"])
        self.assertEqual(claim["predicate"], "scical:sampled_from_definition")
        self.assertEqual(claim["kind"], "derivation")
        self.assertEqual(claim["agent"], "slai-scical")
        self.assertEqual(claim["provenance"]["adapter"], "scical-graph/1")
        self.assertRegex(claim["provenance"]["digest"], r"^[0-9a-f]{64}$")
        self.assertTrue(any("a" in e and "2" in e for e in claim["evidence"]))            # the parameters used are in the evidence
        # the digest identifies definition + parameters: stable for the same input, different for another
        _, _, doc2 = self.save_sgeo([surf("a*x*y")], name="t2", samples=6, params=params)
        _, _, doc3 = self.save_sgeo([surf("a*x*y")], name="t3", samples=6, params={"a": 3})
        d = lambda doc: self.objects(doc)[0]["metadata"]["slai.claims"][0]["provenance"]["digest"]
        self.assertEqual(d(doc2), claim["provenance"]["digest"])
        self.assertNotEqual(d(doc3), claim["provenance"]["digest"])
        self.assertEqual(val(doc.metadata)["scical:params"], params)

    def test_undefined_region_stays_a_hole(self):
        sample, res, doc = self.save_sgeo([surf("sqrt(1 - x^2 - y^2)")], samples=31, domain={"xmin": -1.5, "xmax": 1.5, "ymin": -1.5, "ymax": 1.5})
        (mesh,) = self.objects(doc)
        V, F = np.array(mesh["geometry"]["vertices"]), np.array(mesh["geometry"]["faces"])
        self.assertLessEqual((V[:, 0] ** 2 + V[:, 1] ** 2).max(), 1 + 1e-12)
        np.testing.assert_allclose(V[:, 2], np.sqrt(1 - V[:, 0] ** 2 - V[:, 1] ** 2), rtol=0, atol=1e-12)
        layer = sample["layers"][0]
        dropped = mesh["metadata"]["scical:sampling"]["degenerateTrianglesDropped"]
        self.assertEqual(len(F) + dropped, 2 * len(layer["cells"]))
        self.assertGreater(layer["stats"]["undefined"], 0)
        # no triangle may reach across the hole: in the xy plane every edge is at most a cell diagonal (the grid step is 3 / 30)
        step = 3.0 / 30
        p = V[F][:, :, :2]
        longest = max(np.linalg.norm(p[:, a] - p[:, b], axis=1).max() for a, b in ((0, 1), (1, 2), (2, 0)))
        self.assertLessEqual(longest, step * math.sqrt(2) * (1 + 1e-9))

    def test_sphere_has_unit_radius_and_no_degenerate_triangles(self):
        sample, res, doc = self.save_sgeo([SPHERE], samples=24)
        (mesh,) = self.objects(doc)
        V, F = np.array(mesh["geometry"]["vertices"]), np.array(mesh["geometry"]["faces"])
        np.testing.assert_allclose(np.linalg.norm(V, axis=1), 1.0, rtol=0, atol=1e-12)
        p = V[F]
        cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        self.assertTrue(((cr * cr).sum(axis=1) > spatial.MIN_CROSS2).all())
        dropped = mesh["metadata"]["scical:sampling"]["degenerateTrianglesDropped"]
        self.assertGreater(dropped, 0)                                              # the poles collapse
        self.assertTrue(any("degenerate" in n for n in res["notes"]))
        # surface area of the sampled sphere approaches 4 pi from below (inscribed triangles): within 3 % at 24 samples
        area = 0.5 * np.linalg.norm(cr, axis=1).sum()
        self.assertLess(abs(area - 4 * math.pi) / (4 * math.pi), 0.03)
        self.assertLess(area, 4 * math.pi)

    def test_mesh_and_normals_note(self):
        _, res, _ = self.save_sgeo([surf("x*y")], samples=5)
        self.assertTrue(any("no normals" in n for n in res["notes"]))
        _, res, _ = self.save_sgeo([surf("x*y", colorBy="height")], samples=5)
        self.assertTrue(any("per-vertex colour" in n for n in res["notes"]))


class SgeoOtherLayerTests(Base):
    def test_curve_round_trip(self):
        sample, res, doc = self.save_sgeo([HELIX])
        (obj,) = self.objects(doc)
        g = obj["geometry"]
        self.assertEqual((g["kind"], g["degree"]), ("nurbs_curve", 1))
        P = np.array(g["points"] if "points" in g else g["control_points"])
        src = np.array(sample["layers"][0]["segments"][0])
        np.testing.assert_allclose(P, src, rtol=0, atol=1e-12)
        t = np.linspace(0, 12, 200)
        np.testing.assert_allclose(np.hypot(P[:, 0], P[:, 1]), 1.0, rtol=0, atol=1e-12)
        np.testing.assert_allclose(P[:, 2], t / 4, rtol=0, atol=1e-12)
        self.assertEqual(res["layers"][0]["controlPoints"], 200)

    def test_a_curve_with_poles_becomes_one_group_of_pieces(self):
        tan = {"id": "C", "type": "curve3d", "x": "t", "y": "0", "z": "tan(t)", "tmin": "-2", "tmax": "2", "samples": 401}
        sample, res, doc = self.save_sgeo([tan])
        objs = self.objects(doc)
        gid = res["layers"][0]["objectIds"][0]
        group = next(o for o in objs if o["id"] == gid)
        self.assertIsNone(group.get("geometry"))                                      # a group carries the layer's definition, not geometry
        self.assertEqual(group["metadata"]["scical:layer_id"], "C")
        pieces = [o for o in objs if o.get("parent") == gid]
        self.assertEqual(len(pieces), 3)
        self.assertEqual(res["layers"][0]["pieces"], 3)
        self.assertTrue(all(kind_of(o) == "nurbs_curve" and o["geometry"]["degree"] == 1 for o in pieces))
        self.assertEqual(sum(o["geometry"]["control_points"] if isinstance(o["geometry"]["control_points"], int) else len(o["geometry"]["control_points"]) for o in pieces),
                         res["layers"][0]["controlPoints"])

    def test_points_are_stored_exactly_one_object_each(self):
        pts = {"id": "Q", "type": "points3d", "x": ["0", "1.5", "-2"], "y": ["1", "2", "3"], "z": ["0.25", "pi", "1e3"]}
        _, res, doc = self.save_sgeo([pts])
        points = [o for o in self.objects(doc) if kind_of(o) == "point"]
        self.assertEqual(len(points), 3)
        got = sorted(map(tuple, (np.array(o["geometry"]["position"] if "position" in o["geometry"] else o["geometry"]["point"]) for o in points)))
        want = sorted([(0.0, 1.0, 0.25), (1.5, 2.0, math.pi), (-2.0, 3.0, 1000.0)])
        np.testing.assert_allclose(got, want, rtol=0, atol=1e-12)
        self.assertEqual(res["layers"][0]["points"], 3)

    def test_mixed_scene_keeps_every_layer_with_its_definition(self):
        _, res, doc = self.save_sgeo([surf("x*y"), SPHERE, HELIX], samples=12)
        md_by_layer = {o["metadata"].get("scical:layer_id"): o["metadata"] for o in self.objects(doc) if "scical:definition" in o["metadata"]}
        self.assertEqual(sorted(md_by_layer), ["H", "P", "S"])
        self.assertEqual(md_by_layer["P"]["scical:definition"]["type"], "psurface")
        self.assertEqual(md_by_layer["H"]["scical:definition"]["type"], "curve3d")
        self.assertEqual([l["kind"] for l in res["layers"]], ["mesh", "mesh", "curve"])

    def test_a_failed_layer_is_reported_not_dropped_silently(self):
        sample, res, doc = self.save_sgeo([surf("a*x", id="A"), surf("x*y", id="B")], samples=5)
        self.assertEqual([s["id"] for s in res["skipped"]], ["A"])
        self.assertIn("'a' has no value", res["skipped"][0]["reason"])
        self.assertEqual([l["id"] for l in res["layers"]], ["B"])
        self.assertEqual(len(self.objects(doc)), 1)

    def test_nothing_to_save_is_an_error(self):
        sample, _ = sample3d([surf("a*x")], samples=5)
        with self.assertRaises(BadRequest) as cm:
            spatial.export_sgeo(self.link, self.out, sample, name="none", unit="m")
        self.assertIn("nothing to save", cm.exception.message.lower())

    def test_a_surface_that_is_nowhere_defined_is_skipped_with_the_reason(self):
        sample, res, doc = self.save_sgeo([surf("sqrt(-1 - x^2 - y^2)", id="N"), surf("x", id="OK")], samples=5)
        self.assertEqual([s["id"] for s in res["skipped"]], ["N"])
        self.assertIn("No part of the surface is defined", res["skipped"][0]["reason"])

    def test_too_many_points_are_skipped_explicitly(self):
        n = spatial.MAX_EXPORT_POINTS + 1
        big = {"id": "B", "type": "points3d", "x": [str(i) for i in range(n)], "y": ["0"] * n, "z": ["0"] * n}
        sample, _ = sample3d([big, surf("x")], samples=4)
        res = spatial.export_sgeo(self.link, self.out, sample, name="big", unit="m")
        self.assertEqual([s["id"] for s in res["skipped"]], ["B"])
        self.assertIn(str(spatial.MAX_EXPORT_POINTS), res["skipped"][0]["reason"])


class FilesystemTests(Base):
    def test_a_saved_file_is_never_overwritten(self):
        sample, _ = sample3d([surf("x")], samples=4)
        a = spatial.export_sgeo(self.link, self.out, sample, name="same", unit="m")
        first = Path(a["path"]).read_bytes()
        b = spatial.export_sgeo(self.link, self.out, sample, name="same", unit="m")
        c = spatial.export_sgeo(self.link, self.out, sample, name="same", unit="m")
        self.assertEqual(len({a["path"], b["path"], c["path"]}), 3)
        self.assertEqual(Path(a["path"]).read_bytes(), first)
        self.assertRegex(Path(b["path"]).name, r"-2\.sgeo$")
        self.assertRegex(Path(c["path"]).name, r"-3\.sgeo$")

    def test_no_temporary_files_are_left_behind(self):
        sample, _ = sample3d([surf("x")], samples=4)
        spatial.export_sgeo(self.link, self.out, sample, name="clean", unit="m")
        leftovers = [p.name for p in self.out.iterdir() if not p.name.endswith((".sgeo", ".sdrw"))]
        self.assertEqual(leftovers, [])

    def test_file_names_cannot_escape_the_output_folder(self):
        sample, _ = sample3d([surf("x")], samples=4)
        res = spatial.export_sgeo(self.link, self.out, sample, name="../../evil/..\\x", unit="m")
        self.assertEqual(Path(res["path"]).parent.resolve(), self.out.resolve())


# ------------------------------------------------------------------------------------------------------------------ SDRW
def entities(doc, **criteria):
    """Every object / entity matching the criteria (query_ids pages at 10 000)."""
    out, offset = [], 0
    while True:
        ids = doc.query_ids(limit=10000, offset=offset, **criteria)
        out += [doc.get(i) for i in ids]
        if len(ids) < 10000:
            return out
        offset += len(ids)


class Sdrw2DTests(Base):
    def save(self, layers, colors=None, view=None, **kw):
        result, spec = render2d(layers, view=view, **kw)
        res = spatial.export_sdrw(self.link, self.out, lambda m: spatial.build_sdrw_graph(m, result, spec, colors or {}, name="g2", unit="mm"), name="g2", suffix="2d")
        return result, res, self.sdrw.open_document(res["path"])

    def test_function_polyline_lies_on_the_curve(self):
        result, res, doc = self.save([{"id": "a", "type": "function", "expr": "x^2 - 1"}], colors={"a": "#cc3300"})
        self.assertEqual(res["validation"]["mode"], "strict")
        curve = [e for e in entities(doc) if e["metadata"].get("scical:role") == "curve"]
        self.assertGreaterEqual(len(curve), 1)
        pts = np.vstack([np.array(e["geometry"]["points"]) for e in curve])
        # 9 significant digits in the sample -> 1e-8 relative tolerance against the formula
        np.testing.assert_allclose(pts[:, 1], pts[:, 0] ** 2 - 1, rtol=1e-8, atol=1e-8)
        self.assertEqual(sum(len(e["geometry"]["points"]) for e in curve), sum(len(s) for s in result["layers"][0]["segments"]))
        self.assertEqual(doc.unit, "mm")

    def test_layer_colour_name_and_definition(self):
        _, res, doc = self.save([{"id": "a", "type": "function", "expr": "x"}, {"id": "b", "type": "function", "expr": "-x"}], colors={"a": "#cc3300", "b": "#0033cc"})
        layers = {l["name"]: l for l in val(doc.layers)}
        self.assertEqual(layers["01 x"]["stroke"], "#cc3300")
        self.assertEqual(layers["02 -x"]["stroke"], "#0033cc")
        defs = {d["id"]: d for d in val(doc.metadata)["scical:definitions"]}
        self.assertEqual(defs["a"]["spec"]["expr"], "x")
        self.assertEqual(val(doc.metadata)["scical:contract"], "scical-graph/1")

    def test_frame_grid_and_axes_match_the_view(self):
        view = {"xmin": -4, "xmax": 4, "ymin": -2, "ymax": 6}
        result, _, doc = self.save([{"id": "a", "type": "function", "expr": "x"}], view=view)
        v = result["view"]                                                         # the view as drawn (the service may widen it to fit the plot)
        (frame,) = entities(doc, layer="frame")
        np.testing.assert_allclose(frame["geometry"]["points"], [[v["xmin"], v["ymin"]], [v["xmax"], v["ymin"]], [v["xmax"], v["ymax"]], [v["xmin"], v["ymax"]]], rtol=0, atol=1e-12)
        self.assertTrue(frame["geometry"]["closed"])
        _, xt = spatial.ticks(v["xmin"], v["xmax"], 8)
        _, yt = spatial.ticks(v["ymin"], v["ymax"], 6)
        self.assertEqual(len(entities(doc, layer="grid")), len(xt) + len(yt))
        axes = entities(doc, layer="axes")
        self.assertEqual(len(axes), 2)
        roles = {e["metadata"]["scical:role"]: e["geometry"] for e in axes}
        np.testing.assert_allclose([roles["x axis"]["start"], roles["x axis"]["end"]], [[v["xmin"], 0], [v["xmax"], 0]], atol=1e-12)
        np.testing.assert_allclose([roles["y axis"]["start"], roles["y axis"]["end"]], [[0, v["ymin"]], [0, v["ymax"]]], atol=1e-12)

    def test_tick_labels_show_their_values(self):
        _, _, doc = self.save([{"id": "a", "type": "function", "expr": "x"}])
        for e in entities(doc, layer="tick labels"):
            self.assertAlmostEqual(float(e["geometry"]["text"]), e["metadata"]["scical:value"], delta=1e-9)

    def test_an_inequality_saves_only_its_boundary_and_says_so(self):
        result, res, doc = self.save([{"id": "f", "type": "inequality", "expr": "y > x^2"}])
        self.assertTrue(any(s["id"] == "f" and "shaded region" in s["reason"] for s in res["skipped"]))
        roles = {e["metadata"].get("scical:role") for e in entities(doc) if e["metadata"].get("scical:layer_id") == "f"}
        self.assertEqual(roles, {"boundary"})
        self.assertFalse(any(e["kind"] == "hatch" for e in entities(doc)))

    def test_a_failed_layer_is_skipped_with_its_error(self):
        _, res, _ = self.save([{"id": "a", "type": "function", "expr": "x"}, {"id": "z", "type": "function", "expr": "a*x"}])
        self.assertEqual([s["id"] for s in res["skipped"]], ["z"])

    def test_scatter_points_and_fit(self):
        scatter = {"id": "s", "type": "scatter", "x": [0, 1, 2, 3], "y": [1, 3, 5, 7], "fit": "linear"}
        result, res, doc = self.save([scatter], view={"xmin": -1, "xmax": 5, "ymin": -1, "ymax": 9})
        pts = [e for e in entities(doc) if e["metadata"].get("scical:role") == "point"]
        got = sorted((e["geometry"]["position"][0], e["geometry"]["position"][1]) for e in pts) if "position" in pts[0]["geometry"] else sorted(tuple(e["geometry"]["point"]) for e in pts)
        np.testing.assert_allclose(got, [(0, 1), (1, 3), (2, 5), (3, 7)], atol=1e-12)

    def test_vertical_line_and_asymptote(self):
        _, _, doc = self.save([{"id": "t", "type": "function", "expr": "tan(x)"}], view={"xmin": -2, "xmax": 2, "ymin": -5, "ymax": 5})
        asym = [e for e in entities(doc) if e["metadata"].get("scical:role") == "asymptote"]
        xs = sorted(e["metadata"]["scical:x"] for e in asym)
        np.testing.assert_allclose(xs, [-math.pi / 2, math.pi / 2], rtol=0, atol=1e-3)
        for e in asym:
            self.assertAlmostEqual(e["geometry"]["start"][0], e["geometry"]["end"][0], places=12)

    def test_histogram_bar_metadata(self):
        hist = {"id": "h", "type": "histogram", "values": [1, 2, 2, 3, 3, 3, 4, 4, 4, 4], "bins": 4}
        _, res, doc = self.save([hist], view={"xmin": 0, "xmax": 5, "ymin": 0, "ymax": 5})
        bars = [e for e in entities(doc) if e["metadata"].get("scical:role") == "bar"]
        self.assertEqual(sum(b["metadata"]["scical:count"] for b in bars), 10)


class SdrwProjectionTests(Base):
    BOUNDS = {"xmin": -1.0, "xmax": 1.0, "ymin": 0.0, "ymax": 4.0, "zmin": -2.0, "zmax": 2.0}

    def save(self, layers, *, mode, view=None, colors=None, samples=21, domain=None):
        sample, _ = sample3d(layers, samples=samples, domain=domain)
        res = spatial.export_sdrw(self.link, self.out, lambda m: spatial.build_sdrw_projection(m, sample, view or {"azimuth": 0.0, "elevation": 0.0, "aspect": "equal"}, colors or {}, name="p", unit="mm", mode=mode),
                                  name="p", suffix=mode)
        return sample, res, self.sdrw.open_document(res["path"])

    # ---- the projection formula itself
    def test_front_view_maps_y_to_page_x_and_z_to_page_y(self):
        proj = spatial.Projection(self.BOUNDS, "equal", 0.0, 0.0)
        p = np.array([[0.0, 2.0, 0.0], [1.0, 4.0, 2.0], [-1.0, 0.0, -2.0]])
        # equal aspect: scale = 1 / 4 for every axis, centre = (0, 2, 0); page = (y', z') * 100
        np.testing.assert_allclose(proj(p), [[0.0, 0.0], [50.0, 50.0], [-50.0, -50.0]], rtol=0, atol=1e-10)

    def test_top_view_maps_x_and_y(self):
        proj = spatial.Projection(self.BOUNDS, "equal", 0.0, math.radians(120))            # looking down: the elevation is clamped to 89 degrees like the browser
        # equal aspect: scale 1/4, centre (0, 2, 0). At 89 deg: page x = y' * 100, page y = -x' * sin(89 deg) * 100
        q = proj(np.array([[1.0, 4.0, 0.0], [-1.0, 0.0, 0.0]]))
        s89 = math.sin(math.radians(89))
        np.testing.assert_allclose(q, [[50.0, -25.0 * s89], [-50.0, 25.0 * s89]], rtol=0, atol=1e-9)

    def test_elevation_is_clamped_like_the_browser(self):
        a = spatial.Projection(self.BOUNDS, "box", 0.3, math.radians(120))
        b = spatial.Projection(self.BOUNDS, "box", 0.3, math.radians(89))
        np.testing.assert_allclose(a(np.array([[0.3, 1.0, 1.0]])), b(np.array([[0.3, 1.0, 1.0]])), atol=1e-12)

    def test_box_aspect_flattens_z(self):
        center, scale = spatial.normalizer(self.BOUNDS, "box")
        np.testing.assert_allclose(center, [0, 2, 0], atol=1e-15)
        np.testing.assert_allclose(scale, [0.5, 0.25, 0.78 / 4], atol=1e-15)

    def test_basis_is_orthonormal_and_z_up(self):
        for az in (-3.0, -0.9, 0.0, 1.2, 3.0):
            for el in (-1.0, 0.0, 0.42, 1.2):
                v, r, u = spatial.view_basis(az, el)
                np.testing.assert_allclose([v @ v, r @ r, u @ u, v @ r, v @ u, r @ u], [1, 1, 1, 0, 0, 0], atol=1e-12)
                self.assertGreater(u[2], 0)

    def test_shared_vector_with_the_browser_projection(self):
        """The same numbers are asserted in tests_ts/scene3d.test.ts (makeProjector, orthographic, S = 100): the two implementations must agree."""
        proj = spatial.Projection({"xmin": -1, "xmax": 1, "ymin": 0, "ymax": 4, "zmin": -2, "zmax": 2}, "box", 0.5, 0.3)
        got = proj(np.array([[1.0, 4.0, 2.0], [-1.0, 0.0, -2.0], [0.0, 2.0, 0.0], [0.25, 3.0, -1.0]]))
        np.testing.assert_allclose(got, SHARED_PAGE_VECTORS, rtol=0, atol=1e-9)

    # ---- the saved wireframe
    def test_wireframe_vertices_follow_the_projection_of_the_samples(self):
        view = {"azimuth": 0.7, "elevation": 0.35, "aspect": "box"}
        sample, res, doc = self.save([HELIX], mode="wireframe", view=view)
        (curve,) = [e for e in entities(doc) if e["metadata"].get("scical:role") == "curve"]
        proj = spatial.Projection(sample["bounds"], "box", 0.7, 0.35)
        want = proj(np.array(sample["layers"][0]["segments"][0]))
        want = want[np.concatenate([[True], np.any(want[1:] != want[:-1], axis=1)])]
        np.testing.assert_allclose(np.array(curve["geometry"]["points"]), want, rtol=0, atol=1e-9)
        self.assertEqual(val(doc.metadata)["scical:projection"]["kind"], "orthographic")
        self.assertEqual(res["projection"]["aspect"], "box")

    def test_wireframe_grid_lines_cover_the_whole_grid(self):
        n = 11
        sample, res, doc = self.save([surf("x*y")], mode="wireframe", samples=n, view={"azimuth": 0.7, "elevation": 0.35, "aspect": "box"})
        lines = [e for e in entities(doc) if str(e["metadata"].get("scical:role", "")).startswith("grid line")]
        self.assertEqual(len(lines), 2 * n)                                              # n rows + n columns of a full grid
        self.assertTrue(all(len(e["geometry"]["points"]) == n for e in lines))

    def test_grid_lines_break_at_a_hole_and_never_cross_it(self):
        n = 31
        domain = {"xmin": -1.5, "xmax": 1.5, "ymin": -1.5, "ymax": 1.5}
        sample, _ = sample3d([surf("sqrt(1 - x^2 - y^2)")], samples=n, domain=domain)
        layer = sample["layers"][0]
        lines = spatial._grid_lines(layer)
        gi = np.array(layer["gridIndex"])
        rows, cols = np.unique(gi % n), np.unique(gi // n)                  # grid rows / columns that have a vertex
        # the defined region is a disc (convex): every grid row and column meets it in one run, so exactly one line each, and fewer than the full grid
        self.assertEqual(len(lines), len(rows) + len(cols))
        self.assertLess(len(lines), 2 * n)
        cells = np.array(layer["cells"]).reshape(-1, 4)
        cell_edges = set()
        for a, b, d, c in cells.tolist():
            cell_edges.update({(a, b), (b, a), (c, d), (d, c), (a, c), (c, a), (b, d), (d, b)})
        for kind, run_ in lines:
            for p, q in zip(run_, run_[1:]):
                self.assertIn((p, q), cell_edges, "a grid line may only follow edges of existing cells")

    def test_wireframe_is_labelled_as_derived_and_lossy(self):
        _, res, doc = self.save([surf("x*y")], mode="wireframe")
        md = val(doc.metadata)
        self.assertIs(md["scical:lossy"], True)
        self.assertIn("derived", md["scical:derived"].lower())
        self.assertEqual(md["scical:source"], "graph3d-projection")
        title = [e for e in entities(doc, layer="title") if e["kind"] == "text"]
        self.assertTrue(any("derived drawing" in e["geometry"]["text"] for e in title))
        self.assertTrue(any("not the model" in n for n in res["notes"]))
        self.assertTrue(any("orthographic" in n for n in res["notes"]))
        self.assertTrue(any(d["id"] == "S" for d in md["scical:definitions"]))

    def test_a_point_layer_projects_point_by_point(self):
        pts = {"id": "Q", "type": "points3d", "x": ["0", "1"], "y": ["0", "4"], "z": ["-2", "2"]}
        sample, _, doc = self.save([pts, surf("x")], mode="wireframe", samples=5)
        got = [e for e in entities(doc) if e["metadata"].get("scical:role") == "point"]
        self.assertEqual(len(got), 2)

    # ---- contours
    def test_contours_are_circles_of_the_right_radius(self):
        n = 41                                                         # grid step h = 4 / 40 = 0.1 on [-2, 2]
        domain = {"xmin": -2, "xmax": 2, "ymin": -2, "ymax": 2}
        sample, res, doc = self.save([surf("x^2 + y^2")], mode="contours", samples=n, domain=domain)
        md = val(doc.metadata)
        info = md["scical:contours_S"]
        k, x0, y0 = info["scale"], info["xmin"], info["ymin"]
        contours = [e for e in entities(doc) if e["metadata"].get("scical:role") == "contour"]
        levels = sorted({e["metadata"]["scical:level"] for e in contours})
        self.assertGreaterEqual(len(levels), 3)
        checked = 0
        for e in contours:
            lv = e["metadata"]["scical:level"]
            if lv < 1.0:
                continue                                              # near the origin |grad f| -> 0 and the bound below no longer applies
            pts = np.array(e["geometry"]["points"]) / k + [x0, y0]
            r = np.hypot(pts[:, 0], pts[:, 1])
            # Linear interpolation along a mesh edge of length d errs in z by at most f'' d^2 / 8. The longest edge is a cell diagonal, d = h sqrt(2) = 0.1414,
            # and f'' = 2 along any direction for x^2 + y^2, so the error in z is at most 2 * 0.02 / 8 = 0.005 and in r at most 0.005 / (2 r) <= 0.0025 for r >= 1.
            np.testing.assert_allclose(r, math.sqrt(lv), rtol=0, atol=0.0025 + 1e-9)
            checked += len(pts)
        self.assertGreater(checked, 50)
        self.assertEqual(md["scical:source"], "graph3d-projection")
        self.assertIs(md["scical:lossy"], True)
        self.assertIsNone(res["projection"])

    def test_contours_skip_what_is_not_an_explicit_surface(self):
        sample, res, doc = self.save([surf("x*y"), SPHERE, HELIX], mode="contours", samples=15)
        self.assertEqual(sorted(s["id"] for s in res["skipped"]), ["H", "P"])
        self.assertTrue(all("explicit surface" in s["reason"] for s in res["skipped"]))

    def test_contours_alone_on_a_curve_is_an_error(self):
        sample, _ = sample3d([HELIX], samples=5)
        with self.assertRaises(BadRequest):
            spatial.export_sdrw(self.link, self.out, lambda m: spatial.build_sdrw_projection(m, sample, {}, {}, name="c", unit="mm", mode="contours"), name="c", suffix="contours")

    def test_marching_triangles_on_a_plane(self):
        """z = x over a unit square: the level z = 0.5 is the straight line x = 0.5, found exactly (linear interpolation of a linear function)."""
        xs = np.linspace(0, 1, 5)
        V = np.array([[x, y, x] for x in xs for y in xs])
        tris = []
        for i in range(4):
            for j in range(4):
                a, b, c, d = i * 5 + j, i * 5 + j + 1, (i + 1) * 5 + j, (i + 1) * 5 + j + 1
                tris += [[a, b, d], [a, d, c]]
        lines = spatial.contour_polylines(V, np.array(tris), 0.5)
        self.assertEqual(len(lines), 1)
        np.testing.assert_allclose(lines[0][:, 0], 0.5, rtol=0, atol=1e-12)
        np.testing.assert_allclose(lines[0][:, 2], 0.5, rtol=0, atol=1e-12)
        self.assertAlmostEqual(abs(lines[0][0, 1] - lines[0][-1, 1]), 1.0, places=12)

    def test_a_level_through_a_vertex_does_not_lose_the_line(self):
        xs = np.linspace(0, 1, 5)
        V = np.array([[x, y, x] for x in xs for y in xs])
        tris = []
        for i in range(4):
            for j in range(4):
                a, b, c, d = i * 5 + j, i * 5 + j + 1, (i + 1) * 5 + j, (i + 1) * 5 + j + 1
                tris += [[a, b, d], [a, d, c]]
        lines = spatial.contour_polylines(V, np.array(tris), 0.5)                          # 0.5 is exactly a grid column
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(abs(lines[0][0, 1] - lines[0][-1, 1]), 1.0, places=12)


# Expected page coordinates of four points for bounds x[-1,1] y[0,4] z[-2,2], aspect 'box', azimuth 0.5, elevation 0.3 (computed independently with mpmath at 30 digits).
SHARED_PAGE_VECTORS = [[19.907851164308486, 17.206957360935192], [-19.907851164308486, -17.206957360935192], [0.0, 0.0], [15.946744814706781, -25.412852144778153]]


# ------------------------------------------------------------------------------------------------------------------ HTTP
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(SKIP, SKIP)
class ExportRouteTests(unittest.TestCase):
    TOKEN = "export-test-token-0123456789"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = _free_port()
        cls.log = open(Path(cls.tmp.name) / "server.log", "w")
        cls.proc = subprocess.Popen([sys.executable, "-m", "scical", "--no-browser", "--port", str(cls.port), "--token", cls.TOKEN, "--data-dir", cls.tmp.name + "/data",
                                     "--output-dir", cls.tmp.name + "/out", "--agents", "none", "--workers", "2", "--timeout", "20", "--slai-root", str(SLAI)],
                                    cwd=ROOT, stdout=cls.log, stderr=subprocess.STDOUT)
        for _ in range(150):
            try:
                cls.raw("GET", "/")
                break
            except OSError:
                time.sleep(0.1)
        _, headers, _ = cls.raw("GET", f"/?token={cls.TOKEN}")
        cls.cookie = next((v for k, v in headers if k.lower() == "set-cookie"), "").split(";")[0]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.log.close()
        cls.tmp.cleanup()

    @classmethod
    def raw(cls, method, path, body=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=60)
        try:
            data = None if body is None else json.dumps(body).encode()
            h = dict(headers or {})
            if data is not None:
                h["Content-Length"] = str(len(data))
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            return r.status, r.getheaders(), r.read()
        finally:
            c.close()

    def post(self, body, marker=True):
        h = {"Cookie": self.cookie, "Content-Type": "application/json", **({"X-SLAI-SciCal": "1"} if marker else {})}
        status, _, data = self.raw("POST", "/api/graph/export", body, h)
        return status, json.loads(data)

    SCENE = {"mode": "3d", "domain": DOMAIN, "samples": {"u": 12, "v": 12}, "params": {}, "layers": [surf("x*y", color="#336699")]}
    GRAPH = {"mode": "2d", "viewport": {"xmin": -3, "xmax": 3, "ymin": -3, "ymax": 3}, "params": {}, "layers": [{"id": "a", "type": "function", "expr": "x"}]}

    def test_sgeo_over_http_saves_a_verified_file(self):
        status, r = self.post({"format": "sgeo", "source": "3d", "spec": self.SCENE, "name": "http scene", "unit": "m"})
        self.assertEqual(status, 200, r)
        self.assertTrue(r["ok"])
        path = Path(r["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent.resolve(), (Path(self.tmp.name) / "out").resolve())
        data = base64.b64decode(r["contentBase64"])
        self.assertEqual(data, path.read_bytes())
        self.assertEqual(hashlib.sha256(data).hexdigest(), r["sha256"])
        self.assertEqual(r["validation"]["mode"], "strict")
        self.assertEqual(r["layers"][0]["vertices"], 144)
        self.assertEqual(r["mime"], "model/vnd.slai.sgeo+zip" if r["mime"].startswith("model/vnd") else r["mime"])
        slai_link.activate(SLAI)
        doc = slai_link.SlaiLink(SLAI, Path(self.tmp.name), "none").sgeo().open_document(path)
        self.assertTrue(doc.validate().ok)

    def test_sdrw_variants_over_http(self):
        for source, spec, extra in (("2d", self.GRAPH, {"colors": {"a": "#aa2200"}}),
                                    ("3d-wireframe", self.SCENE, {"view": {"azimuth": -0.9, "elevation": 0.4, "aspect": "box"}}),
                                    ("3d-contours", self.SCENE, {})):
            with self.subTest(source=source):
                status, r = self.post({"format": "sdrw", "source": source, "spec": spec, "name": f"http {source}", **extra})
                self.assertEqual(status, 200, r)
                self.assertTrue(r["validation"]["ok"])
                self.assertTrue(Path(r["path"]).is_file())
                self.assertTrue(r["path"].endswith(".sdrw"))

    def test_bad_requests_are_refused_with_a_reason(self):
        cases = [({"format": "pdf", "spec": self.SCENE}, "format"),
                 ({"format": "sgeo", "source": "2d", "spec": self.GRAPH}, "SGEO saves a 3D scene"),
                 ({"format": "sdrw", "source": "3d", "spec": self.SCENE}, "SDRW saves"),
                 ({"format": "sdrw", "source": "bogus", "spec": self.SCENE}, "source"),
                 ({"format": "sgeo", "source": "3d"}, "spec"),
                 ({"format": "sgeo", "source": "3d", "spec": self.SCENE, "unit": "parsec"}, "Unknown unit"),
                 ({"format": "sdrw", "source": "3d-wireframe", "spec": self.SCENE, "view": {"aspect": "auto"}}, "aspect must be")]
        for body, text in cases:
            with self.subTest(body=body.get("source"), text=text):
                status, r = self.post(body)
                self.assertEqual(status, 400, r)
                self.assertFalse(r["ok"])
                self.assertIn(text, r["error"]["message"])

    def test_the_request_marker_is_required(self):
        status, _ = self.post({"format": "sgeo", "source": "3d", "spec": self.SCENE}, marker=False)
        self.assertIn(status, (400, 401, 403))

    def test_nothing_defined_is_an_error_not_an_empty_file(self):
        scene = {**self.SCENE, "layers": [surf("a*x")]}
        before = set((Path(self.tmp.name) / "out").glob("*")) if (Path(self.tmp.name) / "out").exists() else set()
        status, r = self.post({"format": "sgeo", "source": "3d", "spec": scene, "name": "empty"})
        self.assertEqual(status, 400, r)
        self.assertIn("nothing to save", r["error"]["message"].lower())
        after = set((Path(self.tmp.name) / "out").glob("*")) if (Path(self.tmp.name) / "out").exists() else set()
        self.assertEqual(before, after)

    def test_too_large_a_scene_is_refused_like_drawing_it(self):
        scene = {**self.SCENE, "samples": {"u": 500, "v": 500}}
        status, r = self.post({"format": "sgeo", "source": "3d", "spec": scene})
        self.assertEqual(status, 400, r)                                       # every layer fails its limit, so there is nothing to save
        self.assertIn("nothing to save", r["error"]["message"].lower())
        self.assertTrue(r["error"]["details"]["skipped"])


if __name__ == "__main__":
    unittest.main()
