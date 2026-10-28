"""A graph in a worksheet as a scientific figure: its picture, and the functions the picture plots.

SciCal draws graphs in the browser (one canvas, one drawing routine). When a graph is added to a worksheet the page also sends the
picture it just drew (a PNG with a transparent background) and says which layers are in it, in what colour and line style. This module
turns that entry into what an SLDC document needs:

* an SLDC ``figure`` block whose asset is that PNG (the existing SLDC schema: no new block type, no new file format), and
* a ``scical-graph/1`` record in the block's ``extensions["slai.scical"]["graph"]`` that lists every plotted function with the text the
  person typed, its LaTeX, its variable and domain, its colour and its dash pattern. Readers (SReader) typeset the formulas one per line
  directly beneath the picture. The record is inert data; nothing in it is ever run.

The formulas are made by SciCal's own parser and printer (``core.expressions``), never by a second implementation. What the person
typed is stored beside the LaTeX (``expression``) and is never rewritten.

An entry with no picture (a worksheet entry from before pictures were stored) is *not* written as if it had one. It becomes a notice
paragraph that says the picture is missing and carries the same record with ``image: null``, so a reader can show the missing-figure
state together with the functions, and the document tells the truth about what it contains.
"""
from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from ..core.expressions import ParseOptions, parse
from ..core.expressions import ast as A
from ..core.expressions.printer import to_latex, to_text
from ..core.graphing.numeric import CONSTS
from ..errors import BadRequest, SciCalError

SCHEMA = "scical-graph/1"
EXTENSION = "slai.scical"
DASHES = ("solid", "dash", "dot", "dashdot")
MAX_IMAGE_BYTES = 1024 * 1024
MAX_SIDE = 4096
MAX_SERIES = 24
_PNG = b"\x89PNG\r\n\x1a\n"
_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_OPTS = ParseOptions(variables=frozenset(), functions=frozenset(), allow_statements=False)


# --------------------------------------------------------------------------------------------------------- the stored picture
def clean_figure(raw: Any, index: int = 0) -> dict[str, Any]:
    """Check the picture sent with a graph entry (the worksheet stores it as sent: base64 PNG plus the layers it shows)."""
    where = f"Entry {index + 1}: the graph picture"
    if not isinstance(raw, dict):
        raise BadRequest(f"{where} must be an object")
    if raw.get("mediaType") != "image/png":
        raise BadRequest(f"{where} must be a PNG")
    data = raw.get("data")
    if not isinstance(data, str) or len(data) > MAX_IMAGE_BYTES * 4 // 3 + 8:
        raise BadRequest(f"{where} is missing or too large (at most {MAX_IMAGE_BYTES // 1024} KiB)")
    try:
        png = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise BadRequest(f"{where} is not valid base64") from None
    if not png.startswith(_PNG) or len(png) > MAX_IMAGE_BYTES or len(png) < 33:
        raise BadRequest(f"{where} is not a PNG image")
    width, height = png_size(png)
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise BadRequest(f"{where} must be between 1 and {MAX_SIDE} pixels on each side")
    series = raw.get("series", [])
    if not isinstance(series, list) or len(series) > MAX_SERIES:
        raise BadRequest(f"{where} lists at most {MAX_SERIES} layers")
    out_series = []
    for s in series:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not _ID.match(s["id"]):
            raise BadRequest(f"{where}: each layer needs an id")
        colour = s.get("color")
        dash = s.get("dash", "solid")
        if colour is not None and not (isinstance(colour, str) and _COLOUR.match(colour)):
            raise BadRequest(f"{where}: a layer colour must look like #b89b00")
        if dash not in DASHES:
            raise BadRequest(f"{where}: a line style must be one of {', '.join(DASHES)}")
        out_series.append({"id": s["id"], "color": colour, "dash": dash})
    return {"mediaType": "image/png", "data": data, "width": width, "height": height,
            "transparent": raw.get("transparent") is True, "series": out_series}


def png_size(png: bytes) -> tuple[int, int]:
    """Width and height from the IHDR chunk (the picture is never decoded here)."""
    if len(png) < 24 or png[12:16] != b"IHDR":
        raise BadRequest("The graph picture has no PNG header")
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


# --------------------------------------------------------------------------------------------------------- the plotted functions
def _tex(text: Any) -> tuple[str | None, A.Node | None]:
    """LaTeX for what was typed, by SciCal's own printer; (None, None) when it does not parse (it is then shown as typed)."""
    if not isinstance(text, str) or not text.strip():
        return None, None
    try:
        node = parse(text, _OPTS).node
        return to_latex(node), node
    except (SciCalError, ValueError, RecursionError):
        return None, None


def _bound(text: Any, default: str) -> tuple[str, str]:
    """(typed text, LaTeX) of a domain end such as ``2*pi``."""
    typed = text if isinstance(text, str) and text.strip() else default
    latex, _ = _tex(typed)
    return typed, latex or typed


def _number(v: Any) -> str:
    try:
        return format(float(v), ".10g")
    except (TypeError, ValueError):
        return str(v)


def _vars(*nodes: A.Node | None) -> set[str]:
    """Names used by the expressions that are not constants (``pi``, ``e``, ...)."""
    out: set[str] = set()
    for n in nodes:
        if n is not None:
            out |= {v for v in A.free_names(n) if v not in CONSTS}
    return out


def _function_variable(free: set[str]) -> str:
    """The independent variable of ``y = f(...)``: ``x`` when it is used, the only free name when there is one, otherwise ``x``."""
    if "x" in free or not free:
        return "x"
    return sorted(free)[0]


def describe_layer(layer: dict[str, Any], k: int, params: dict[str, Any]) -> dict[str, Any] | None:
    """One plotted layer as a series record (``None`` for a layer with nothing to list)."""
    t = layer.get("type", "auto")
    sub = f"_{{{k}}}"
    domain: dict[str, Any] | None = None
    variable: str | None = None
    names: set[str] = set()
    typed = ""
    latex: str | None = None
    kind = "function"
    if t in ("auto", "function", "implicit", "inequality"):
        typed = str(layer.get("expr") or "").strip()
        if not typed:
            return None
        tex, node = _tex(typed)
        if node is not None:
            names = _vars(node)
            if isinstance(node, (A.Rel, A.Logic)):
                kind = "relation"
                latex = tex                                  # an equation or inequality is shown as it was typed
            else:
                variable = _function_variable(names - set(params))
                latex = f"f{sub}({variable}) = {tex}"
    elif t == "parametric":
        kind = "parametric"
        fx, fy = str(layer.get("x") or "").strip(), str(layer.get("y") or "").strip()
        if not (fx and fy):
            return None
        typed = f"({fx}, {fy})"
        (tx, nx), (ty, ny) = _tex(fx), _tex(fy)
        names = _vars(nx, ny)
        lo, lo_tex = _bound(layer.get("tmin"), "0")
        hi, hi_tex = _bound(layer.get("tmax"), "2*pi")
        variable, domain = "t", {"variable": "t", "min": lo, "max": hi}
        if tx and ty:
            latex = rf"\mathbf{{r}}{sub}(t) = \left({tx},\ {ty}\right),\quad {lo_tex} \le t \le {hi_tex}"
    elif t == "polar":
        kind = "polar"
        typed = str(layer.get("r") or "").strip()
        if not typed:
            return None
        tex, node = _tex(typed)
        names = _vars(node)
        lo, lo_tex = _bound(layer.get("tmin"), "0")
        hi, hi_tex = _bound(layer.get("tmax"), "2*pi")
        variable, domain = "t", {"variable": "t", "min": lo, "max": hi}
        if tex:
            latex = rf"r{sub}(t) = {tex},\quad {lo_tex} \le t \le {hi_tex}"
    elif t == "surface":
        kind = "surface"
        typed = str(layer.get("expr") or "").strip()
        if not typed:
            return None
        tex, node = _tex(typed)
        if isinstance(node, A.Rel) and node.op == "=" and isinstance(node.left, A.Var) and node.left.name == "z":
            tex, node = to_latex(node.right), node.right                 # "z = f(x, y)" was typed: the left side is implied by the heading
        names = _vars(node)
        variable = "x, y"
        if tex:
            latex = rf"z{sub}(x, y) = {tex}" if not isinstance(node, (A.Rel, A.Logic)) else tex
    elif t in ("psurface", "curve3d"):
        kind = "parametric surface" if t == "psurface" else "space curve"
        parts = [str(layer.get(c) or "").strip() for c in "xyz"]
        if not all(parts):
            return None
        typed = f"({', '.join(parts)})"
        texs, nodes = zip(*(_tex(c) for c in parts))
        names = _vars(*nodes)
        names -= {"u", "v"} if t == "psurface" else {"t"}
        if t == "psurface":
            variable = "u, v"
            (ulo, ulo_t), (uhi, uhi_t) = _bound(layer.get("umin"), "0"), _bound(layer.get("umax"), "2*pi")
            (vlo, vlo_t), (vhi, vhi_t) = _bound(layer.get("vmin"), "0"), _bound(layer.get("vmax"), "2*pi")
            if all(texs):
                latex = rf"\mathbf{{r}}{sub}(u, v) = \left({texs[0]},\ {texs[1]},\ {texs[2]}\right),\quad {ulo_t} \le u \le {uhi_t},\ {vlo_t} \le v \le {vhi_t}"
        else:
            variable, (lo, lo_tex), (hi, hi_tex) = "t", _bound(layer.get("tmin"), "0"), _bound(layer.get("tmax"), "2*pi")
            domain = {"variable": "t", "min": lo, "max": hi}
            if all(texs):
                latex = rf"\mathbf{{r}}{sub}(t) = \left({texs[0]},\ {texs[1]},\ {texs[2]}\right),\quad {lo_tex} \le t \le {hi_tex}"
    elif t == "points3d":
        kind = "data"
        n = len(layer["x"]) if isinstance(layer.get("x"), list) else len([ln for ln in str(layer.get("data") or "").splitlines() if ln.strip()])
        typed = f"data points ({n})"
        latex = rf"\mathrm{{data}}{sub}\ \left({n}\ \mathrm{{points}}\right)"
    elif t == "sequence":
        kind = "sequence"
        typed = str(layer.get("expr") or "").strip()
        if not typed:
            return None
        tex, node = _tex(typed)
        names = _vars(node)
        lo, lo_tex = _bound(layer.get("nmin"), "1")
        hi, hi_tex = _bound(layer.get("nmax"), "20")
        variable, domain = "n", {"variable": "n", "min": lo, "max": hi}
        if tex:
            latex = rf"a{sub}(n) = {tex},\quad {lo_tex} \le n \le {hi_tex}"
    elif t == "vectorfield":
        kind = "vectorfield"
        fx, fy = str(layer.get("fx") or "").strip(), str(layer.get("fy") or "").strip()
        if not (fx and fy):
            return None
        typed = f"({fx}, {fy})"
        (tx, nx), (ty, ny) = _tex(fx), _tex(fy)
        names = _vars(nx, ny)
        variable = "x, y"
        if tx and ty:
            latex = rf"\mathbf{{F}}{sub}(x, y) = \left({tx},\ {ty}\right)"
    elif t in ("scatter", "points"):
        kind = "data"
        if isinstance(layer.get("x"), list):
            n = len(layer["x"])
        else:
            n = len([ln for ln in str(layer.get("data") or "").splitlines() if ln.strip()])
        fit = layer.get("fitModel") or layer.get("fit")
        fit = fit if isinstance(fit, str) and re.fullmatch(r"[A-Za-z]{1,24}", fit) else None
        typed = f"data points ({n})" + (f", {fit} fit" if fit else "")
        latex = rf"\mathrm{{data}}{sub}\ \left({n}\ \mathrm{{points}}" + (rf",\ \mathrm{{{fit}\ fit}}" if fit else "") + r"\right)"
    elif t == "histogram":
        kind = "data"
        raw = layer.get("values") if isinstance(layer.get("values"), list) else [v for v in re.split(r"[\s,;]+", str(layer.get("data") or "")) if v]
        typed = f"histogram ({len(raw)} values)"
        latex = rf"\mathrm{{histogram}}{sub}\ \left({len(raw)}\ \mathrm{{values}}\right)"
    else:
        return None
    used = sorted(n for n in names if n in params)
    if latex is not None and used:
        latex += r",\quad " + r",\ ".join(f"{_tex(n)[0] or n} = {_number(params[n])}" for n in used)
    colour = layer.get("color")
    return {"id": str(layer.get("id") or f"L{k}")[:40], "type": kind, "layerType": t, "expression": typed[:500], "latex": latex[:2000] if latex else None,
            "variable": variable, "domain": domain, "color": colour if isinstance(colour, str) and _COLOUR.match(colour) else None,
            "dash": "solid", "parameters": {n: params[n] for n in used} if used else None}


def _params(spec: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    raw = spec.get("params")
    if isinstance(raw, dict):                                           # the service spec: {name: value}
        return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)}
    for p in raw or []:
        if isinstance(p, dict) and isinstance(p.get("name"), str) and isinstance(p.get("value"), (int, float)) and not isinstance(p.get("value"), bool):
            out[p["name"]] = p["value"]
    return out


def listed_layers(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The layers a picture shows, in drawing order: the ones the picture was sent with, or (no picture) every visible layer."""
    spec = entry.get("spec") if isinstance(entry.get("spec"), dict) else {}
    layers = [l for l in (spec.get("layers") or []) if isinstance(l, dict)]
    figure = entry.get("figure") if isinstance(entry.get("figure"), dict) else None
    if figure is not None:
        by_id = {str(l.get("id")): l for l in layers}
        out = []
        for s in figure.get("series") or []:
            layer = by_id.get(s["id"])
            if layer is not None:
                out.append({**layer, "color": s.get("color") or layer.get("color"), "_dash": s.get("dash", "solid")})
        return out
    return [l for l in layers if l.get("visible", True) is not False]


def series_of(entry: dict[str, Any]) -> list[dict[str, Any]]:
    spec = entry.get("spec") if isinstance(entry.get("spec"), dict) else {}
    params = _params(spec)
    out: list[dict[str, Any]] = []
    for layer in listed_layers(entry):
        s = describe_layer(layer, len(out) + 1, params)
        if s is None:
            continue
        s["dash"] = layer.get("_dash", "solid") if layer.get("_dash") in DASHES else "solid"
        out.append(s)
    return out


def summary_text(entry: dict[str, Any]) -> str:
    """What the graph plots, as plain text, for text/Markdown/CSV exports and for picture descriptions."""
    return "; ".join(s["expression"] for s in series_of(entry))


def graph_record(entry: dict[str, Any], series: list[dict[str, Any]], image: dict[str, Any] | None, doc_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = entry.get("spec") if isinstance(entry.get("spec"), dict) else {}
    view = spec.get("viewport") if isinstance(spec.get("viewport"), dict) else {}
    three = spec.get("mode") == "3d"
    coords = {"horizontal": "x", "vertical": "y", "depth": "z", "units": None} if three else {"horizontal": "x", "vertical": "y", "units": None}
    record: dict[str, Any] = {"schema": SCHEMA, "id": f"scical.graph.{entry.get('id', 'x')}", "kind": "3d" if three else "2d", "series": series,
                              "image": image, "coordinates": coords,
                              "source": {"application": "SLAI SciCal", "entry": entry.get("id"), "time": entry.get("time")}}
    viewport = {k: view[k] for k in ("xmin", "xmax", "ymin", "ymax") if isinstance(view.get(k), (int, float)) and not isinstance(view.get(k), bool)}
    if len(viewport) == 4:
        record["viewport"] = viewport
    if three and isinstance(spec.get("domain"), dict):
        dom = {k: str(spec["domain"][k])[:40] for k in ("xmin", "xmax", "ymin", "ymax") if isinstance(spec["domain"].get(k), (str, int, float)) and not isinstance(spec["domain"].get(k), bool)}
        if dom:
            record["domain"] = dom
    params = _params(spec)
    if params:
        record["parameters"] = params
    angle = (entry.get("settings") or {}).get("angle") if isinstance(entry.get("settings"), dict) else None
    angle = angle or (doc_settings or {}).get("angle")
    if angle in ("rad", "deg", "grad"):
        record["angle"] = angle
    return record


# --------------------------------------------------------------------------------------------------------- SLDC blocks
def sldc_blocks(entry: dict[str, Any], sldc: Any, doc_settings: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[Any]]:
    """The SLDC blocks (and the picture assets they use) for one graph entry. Block ids are left for the caller to assign."""
    series = series_of(entry)
    figure = entry.get("figure") if isinstance(entry.get("figure"), dict) else None
    title = str(entry.get("title") or "Graph")[:200]
    plotted = "; ".join(s["expression"] for s in series) or "no functions"
    if figure is not None:
        png = base64.b64decode(figure["data"])
        asset = sldc.make_asset(png)
        image = {"width": figure["width"], "height": figure["height"], "transparent": bool(figure.get("transparent"))}
        block = sldc.make_figure(asset, alt=f"Graph of {plotted}"[:1900], caption=title, align="center")
        block["extensions"] = {EXTENSION: {"graph": graph_record(entry, series, image, doc_settings)}}
        return [block], [asset]
    note = (f"{title}: the picture of this graph was not stored with the worksheet entry, so it cannot be shown. "
            "Open the worksheet in SciCal and add the graph again to store its picture.")
    block = sldc.make_block("paragraph", note, extensions={EXTENSION: {"graph": graph_record(entry, series, None, doc_settings)}})
    return [block], []


def to_text_label(entry: dict[str, Any]) -> str:
    return "graph: " + (summary_text(entry) or "(empty)")
