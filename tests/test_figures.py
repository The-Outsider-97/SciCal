"""A graph in a worksheet: the plotted functions as a ``scical-graph/1`` record, the stored picture, and what an SLDC export makes of them.

Nothing here is mocked: the formulas come from SciCal's own parser and printer, the picture is a real PNG, and the SLDC package is written
and re-read by SLAI's own ``src.utils.sldc`` (those tests are skipped, and say so, when the SLAI checkout is not found).
"""
import base64
import json
import struct
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scical.errors import BadRequest  # noqa: E402
from scical.services import exports, figures, sessions  # noqa: E402


def slai_sldc():
    for base in (ROOT.parent.parent, Path("/home/claude/slai")):
        if (base / "src" / "utils" / "sldc.py").is_file():
            if str(base) not in sys.path:
                sys.path.append(str(base))
            from src.utils import sldc
            return sldc
    return None


def png(width: int = 320, height: int = 200, rgba: bytes = b"\xb8\x9b\x00\x80") -> bytes:
    """A real, valid PNG (RGBA, one flat colour, half transparent)."""
    raw = b"".join(b"\x00" + rgba * width for _ in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# The graph in the supplied SReader screenshot: five functions, each its own colour.
FIVE = ["x", "x^2", "x^3", "sin(x)", "a*cos(x)"]
COLOURS = ["#b89b00", "#2f7dd1", "#d1432f", "#118833", "#7a3fb0"]
DASHES = ["solid", "dash", "dot", "dashdot", "solid"]


def five_function_entry(with_picture: bool = True) -> dict:
    layers = [{"id": f"L{i}", "type": "auto", "expr": e, "color": COLOURS[i - 1], "visible": True} for i, e in enumerate(FIVE, 1)]
    entry = {"id": "g1", "kind": "graph", "workspace": "graph", "title": "Graph", "time": "2026-10-28T10:00:00Z",
             "spec": {"layers": layers, "viewport": {"xmin": -10, "xmax": 10, "ymin": -6, "ymax": 6}, "params": [{"name": "a", "value": 2, "min": -5, "max": 5, "step": 0.1}]},
             "summary": {"ok": True, "headline": "Graph of " + "; ".join(FIVE)}, "ok": True}
    if with_picture:
        entry["figure"] = {"mediaType": "image/png", "data": base64.b64encode(png()).decode(), "transparent": True,
                           "series": [{"id": f"L{i}", "color": COLOURS[i - 1], "dash": DASHES[i - 1]} for i in range(1, 6)]}
    return entry


class SeriesTests(unittest.TestCase):
    def test_every_function_is_listed_with_its_own_latex_in_order(self):
        series = figures.series_of(sessions.clean_entry(five_function_entry(), 0))
        self.assertEqual([s["expression"] for s in series], FIVE)
        self.assertEqual([s["latex"] for s in series][:4], ["f_{1}(x) = x", "f_{2}(x) = x^{2}", "f_{3}(x) = x^{3}", r"f_{4}(x) = \sin\left(x\right)"])
        self.assertEqual([s["color"] for s in series], COLOURS)
        self.assertEqual([s["dash"] for s in series], DASHES)

    def test_a_slider_value_is_part_of_the_formula_not_lost(self):
        s = figures.series_of(sessions.clean_entry(five_function_entry(), 0))[4]
        self.assertEqual(s["parameters"], {"a": 2})
        self.assertTrue(s["latex"].endswith("a = 2"))

    def test_the_formula_never_replaces_what_was_typed(self):
        for s in figures.series_of(five_function_entry()):
            self.assertTrue(s["expression"] and "\\" not in s["expression"])

    def test_other_layer_kinds(self):
        entry = {"id": "g2", "kind": "graph", "spec": {"layers": [
            {"id": "P", "type": "parametric", "x": "cos(t)", "y": "sin(t)", "tmin": "0", "tmax": "2*pi", "color": "#118833"},
            {"id": "R", "type": "polar", "r": "1 + cos(t)", "color": "#2f7dd1"},
            {"id": "E", "type": "auto", "expr": "y = x^2 + 1", "color": "#7a3fb0"},
            {"id": "S", "type": "sequence", "expr": "2^n", "nmin": "1", "nmax": "8"},
            {"id": "D", "type": "scatter", "data": "1,2\n2,4\n3,5", "fitModel": "linear"},
            {"id": "H", "type": "histogram", "data": "1 2 2 3 3 3"},
            {"id": "V", "type": "vectorfield", "fx": "y", "fy": "-x"},
            {"id": "X", "type": "auto", "expr": "   "}]}}
        got = {s["id"]: s for s in figures.series_of(entry)}
        self.assertEqual(list(got), ["P", "R", "E", "S", "D", "H", "V"])             # the empty layer is not listed
        self.assertEqual(got["P"]["type"], "parametric")
        self.assertIn(r"\mathbf{r}_{1}(t)", got["P"]["latex"])
        self.assertEqual(got["P"]["domain"], {"variable": "t", "min": "0", "max": "2*pi"})
        self.assertEqual(got["E"]["type"], "relation")
        self.assertEqual(got["E"]["latex"], "y = x^{2} + 1")
        self.assertEqual(got["D"]["expression"], "data points (3), linear fit")
        self.assertEqual(got["H"]["expression"], "histogram (6 values)")

    def test_text_that_does_not_parse_is_kept_as_typed_with_no_latex(self):
        entry = {"id": "g3", "kind": "graph", "spec": {"layers": [{"id": "B", "type": "auto", "expr": "3 +* x"}]}}
        s = figures.series_of(entry)[0]
        self.assertEqual(s["expression"], "3 +* x")
        self.assertIsNone(s["latex"])

    def test_a_hidden_layer_is_not_listed_when_there_is_no_picture(self):
        entry = five_function_entry(with_picture=False)
        entry["spec"]["layers"][2]["visible"] = False
        self.assertEqual([s["expression"] for s in figures.series_of(entry)], ["x", "x^2", "sin(x)", "a*cos(x)"])

    def test_the_picture_decides_which_layers_are_listed(self):
        entry = five_function_entry()
        entry["figure"]["series"] = entry["figure"]["series"][:2]                      # only two of the layers were drawn
        self.assertEqual([s["expression"] for s in figures.series_of(sessions.clean_entry(entry, 0))], ["x", "x^2"])


class PictureTests(unittest.TestCase):
    def good(self):
        return five_function_entry()["figure"]

    def test_a_valid_picture_is_kept_with_its_size_read_from_the_file(self):
        out = figures.clean_figure(self.good())
        self.assertEqual((out["width"], out["height"], out["transparent"]), (320, 200, True))
        self.assertEqual(len(out["series"]), 5)

    def test_what_is_not_a_png_is_refused(self):
        bad = [{**self.good(), "mediaType": "image/jpeg"},
               {**self.good(), "data": base64.b64encode(b"GIF89a" + b"\x00" * 60).decode()},
               {**self.good(), "data": "not base64 !!"},
               {**self.good(), "data": base64.b64encode(png(width=5000, height=2)).decode()},
               {**self.good(), "data": "A" * 2_000_000},
               {**self.good(), "series": [{"id": "L1", "color": "red", "dash": "solid"}]},
               {**self.good(), "series": [{"id": "L1", "color": "#112233", "dash": "wavy"}]},
               {**self.good(), "series": [{"id": "../x", "color": None, "dash": "solid"}]},
               {**self.good(), "series": [{"id": f"L{i}"} for i in range(40)]},
               "a string", None]
        for raw in bad:
            with self.subTest(str(raw)[:50]):
                with self.assertRaises(BadRequest):
                    figures.clean_figure(raw)

    def test_only_a_graph_entry_can_carry_a_picture(self):
        with self.assertRaises(BadRequest):
            sessions.clean_entry({"kind": "note", "text": "x", "figure": self.good()}, 0)

    def test_a_worksheet_entry_keeps_its_picture(self):
        e = sessions.clean_entry(five_function_entry(), 0)
        self.assertEqual(e["figure"]["mediaType"], "image/png")
        self.assertEqual(base64.b64decode(e["figure"]["data"])[:8], b"\x89PNG\r\n\x1a\n")


@unittest.skipIf(slai_sldc() is None, "the SLAI checkout (src/utils/sldc.py) was not found")
class SldcExportTests(unittest.TestCase):
    def package(self, entries):
        sldc = slai_sldc()
        doc = {"id": "abc123", "name": "Five functions", "entries": [sessions.clean_entry(e, i) for i, e in enumerate(entries)], "settings": {"angle": "rad"}}
        data = exports.to_sldc(doc, sldc)
        return sldc, sldc.loads_package(data), data

    def test_the_graph_is_a_figure_block_with_the_picture_and_the_record(self):
        sldc, pkg, _ = self.package([five_function_entry()])
        fig = [b for b in pkg.document["blocks"] if b["type"] == "figure"]
        self.assertEqual(len(fig), 1)
        asset = pkg.assets[fig[0]["figure"]["asset"]]
        self.assertEqual(asset.media_type, "image/png")
        self.assertEqual(asset.data[:8], b"\x89PNG\r\n\x1a\n")
        record = fig[0]["extensions"]["slai.scical"]["graph"]
        self.assertEqual(record["schema"], "scical-graph/1")
        self.assertEqual([s["expression"] for s in record["series"]], FIVE)
        self.assertEqual(record["image"], {"width": 320, "height": 200, "transparent": True})
        self.assertEqual(record["viewport"], {"xmin": -10, "xmax": 10, "ymin": -6, "ymax": 6})
        self.assertIn("x^2", fig[0]["figure"]["alt"])                                  # the alt text names the functions
        # the old behaviour is gone: no `graph: ...` code block and no "= Graph of ..." line standing in for the picture
        self.assertFalse([b for b in pkg.document["blocks"] if b["type"] == "code" and b["text"].startswith("graph:")])

    def test_the_picture_survives_unchanged(self):
        sldc, pkg, _ = self.package([five_function_entry()])
        asset = next(iter(pkg.assets.values()))
        self.assertEqual(asset.data, png())

    def test_a_graph_without_a_picture_says_so_and_still_lists_the_functions(self):
        sldc, pkg, _ = self.package([five_function_entry(with_picture=False)])
        self.assertFalse(pkg.assets)
        self.assertFalse([b for b in pkg.document["blocks"] if b["type"] == "figure"])
        note = next(b for b in pkg.document["blocks"] if b["type"] == "paragraph" and "picture" in b["text"])
        self.assertIn("not stored", note["text"])
        record = note["extensions"]["slai.scical"]["graph"]
        self.assertIsNone(record["image"])
        self.assertEqual(len(record["series"]), 5)

    def test_two_graphs_with_the_same_picture_share_one_asset(self):
        a, b = five_function_entry(), five_function_entry()
        b["id"] = "g9"
        _, pkg, _ = self.package([a, b])
        self.assertEqual(len(pkg.assets), 1)
        self.assertEqual(len([x for x in pkg.document["blocks"] if x["type"] == "figure"]), 2)

    def test_the_record_is_inert_json_only(self):
        _, pkg, _ = self.package([five_function_entry()])
        record = next(b for b in pkg.document["blocks"] if b["type"] == "figure")["extensions"]["slai.scical"]["graph"]
        json.dumps(record, allow_nan=False)                                            # no NaN, no non-JSON values
        self.assertLess(len(json.dumps(record)), 20_000)


class OtherExportsTests(unittest.TestCase):
    def test_text_exports_list_every_function_not_just_the_first_six_or_the_x_of_a_parametric(self):
        entry = {"id": "g", "kind": "graph", "spec": {"layers": [{"id": f"L{i}", "type": "auto", "expr": f"x+{i}"} for i in range(8)]
                                                      + [{"id": "P", "type": "parametric", "x": "cos(t)", "y": "sin(t)"}]}}
        label = exports.figures.to_text_label(sessions.clean_entry(entry, 0))
        self.assertIn("x+7", label)
        self.assertIn("(cos(t), sin(t))", label)


def scene_entry(with_picture: bool = True) -> dict:
    """A saved 3D graph as the browser stores it: the service spec (params as {name: value}) plus the view, and a transparent picture."""
    layers = [{"id": "A", "type": "surface", "expr": "a*sin(x)*cos(y)", "color": "#336699", "visible": True},
              {"id": "B", "type": "surface", "expr": "z = x^2 + y^2", "color": "#aa3300", "visible": True},
              {"id": "P", "type": "psurface", "x": "cos(u)*sin(v)", "y": "sin(u)*sin(v)", "z": "cos(v)", "umin": "0", "umax": "2*pi", "vmin": "0", "vmax": "pi", "color": "#00aa55", "visible": True},
              {"id": "H", "type": "curve3d", "x": "cos(t)", "y": "sin(t)", "z": "t/4", "tmin": "0", "tmax": "6*pi", "color": "#7a3fb0", "visible": True},
              {"id": "Q", "type": "points3d", "x": ["0", "1"], "y": ["0", "1"], "z": ["0", "1"], "color": "#118833", "visible": True},
              {"id": "E", "type": "surface", "expr": "", "visible": True}]
    entry = {"id": "g3", "kind": "graph", "workspace": "graph", "title": "3D graph", "time": "2026-10-28T10:00:00Z",
             "spec": {"mode": "3d", "contract": "scical-graph/1", "domain": {"xmin": "-5", "xmax": "5"}, "samples": {"u": 48, "v": 48}, "params": {"a": 2}, "layers": layers},
             "summary": {"ok": True, "headline": "3D graph"}, "ok": True}
    if with_picture:
        entry["figure"] = {"mediaType": "image/png", "data": base64.b64encode(png()).decode(), "transparent": True,
                           "series": [{"id": i, "color": c, "dash": "solid"} for i, c in (("A", "#336699"), ("B", "#aa3300"), ("P", "#00aa55"), ("H", "#7a3fb0"), ("Q", "#118833"))]}
    return entry


class Scene3DTests(unittest.TestCase):
    def test_every_3d_layer_is_one_formula_line_from_the_parser(self):
        series = figures.series_of(sessions.clean_entry(scene_entry(), 0))
        self.assertEqual([s["id"] for s in series], ["A", "B", "P", "H", "Q"])
        self.assertEqual(series[0]["latex"], r"z_{1}(x, y) = a \cdot \sin\left(x\right) \cdot \cos\left(y\right),\quad a = 2")
        self.assertEqual(series[1]["latex"], r"z_{2}(x, y) = x^{2} + y^{2}")                      # "z = ..." as typed: the left side is not doubled
        self.assertTrue(series[2]["latex"].startswith(r"\mathbf{r}_{3}(u, v) = \left(\cos"))
        self.assertIn(r"0 \le u \le 2 \cdot \pi,\ 0 \le v \le \pi", series[2]["latex"])
        self.assertIn(r"\frac{t}{4}", series[3]["latex"])
        self.assertIn(r"0 \le t \le 6 \cdot \pi", series[3]["latex"])
        self.assertEqual(series[4]["latex"], r"\mathrm{data}_{5}\ \left(2\ \mathrm{points}\right)")
        self.assertEqual([s["variable"] for s in series], ["x, y", "x, y", "u, v", "t", None])
        self.assertEqual([s["color"] for s in series], ["#336699", "#aa3300", "#00aa55", "#7a3fb0", "#118833"])

    def test_the_empty_layer_is_not_listed(self):
        ids = [s["id"] for s in figures.series_of(sessions.clean_entry(scene_entry(with_picture=False), 0))]
        self.assertNotIn("E", ids)

    def test_the_record_says_3d_and_keeps_the_parameters(self):
        entry = sessions.clean_entry(scene_entry(), 0)
        rec = figures.graph_record(entry, figures.series_of(entry), {"width": 320, "height": 200, "transparent": True})
        self.assertEqual(rec["kind"], "3d")
        self.assertEqual(rec["coordinates"], {"horizontal": "x", "vertical": "y", "depth": "z", "units": None})
        self.assertEqual(rec["parameters"], {"a": 2})
        self.assertEqual(rec["domain"], {"xmin": "-5", "xmax": "5"})
        self.assertNotIn("viewport", rec)

    def test_a_2d_record_is_unchanged(self):
        entry = sessions.clean_entry(five_function_entry(), 0)
        rec = figures.graph_record(entry, figures.series_of(entry), None)
        self.assertEqual(rec["kind"], "2d")
        self.assertEqual(rec["coordinates"], {"horizontal": "x", "vertical": "y", "units": None})

    def test_params_as_a_dict_or_a_list(self):
        self.assertEqual(figures._params({"params": {"a": 2, "b": True, "c": "x"}}), {"a": 2})
        self.assertEqual(figures._params({"params": [{"name": "a", "value": 2}]}), {"a": 2})


class Scene3DExportTests(unittest.TestCase):
    @unittest.skipIf(slai_sldc() is None, "needs the SLAI checkout (src/utils/sldc.py)")
    def test_a_3d_graph_reaches_sldc_and_reader_shows_one_formula_per_line(self):
        sldc = slai_sldc()
        doc = {"id": "abc123", "name": "Scene", "entries": [sessions.clean_entry(scene_entry(), 0)], "settings": {"angle": "rad"}}
        pkg = sldc.loads_package(exports.to_sldc(doc, sldc))
        (fig,) = [b for b in pkg.document["blocks"] if b["type"] == "figure"]
        asset = pkg.assets[fig["figure"]["asset"]]
        self.assertEqual(asset.data, png())
        rec = fig["extensions"]["slai.scical"]["graph"]
        self.assertEqual(rec["kind"], "3d")
        self.assertEqual(len(rec["series"]), 5)
        reader = ROOT.parent / "Reader"
        if not (reader / "slai_reader" / "documents" / "figures.py").is_file():
            self.skipTest("the Reader checkout is not beside SciCal")
        sys.path.insert(0, str(reader))
        try:
            from slai_reader.documents import figures as reader_figures
        finally:
            sys.path.remove(str(reader))
        view = reader_figures.graph_view(fig)
        self.assertEqual(view["kind"], "3d")
        self.assertEqual(len(view["series"]), 5)
        self.assertEqual(view["skipped"], 0)
        self.assertTrue(all(s["latex"] for s in view["series"]))
        self.assertEqual([s["color"] for s in view["series"]], ["#336699", "#aa3300", "#00aa55", "#7a3fb0", "#118833"])
        self.assertEqual(view["image"], {"width": 320, "height": 200, "transparent": True})


if __name__ == "__main__":
    unittest.main()
