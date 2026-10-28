"""Three-dimensional graph generation: explicit surfaces z = f(x, y), parametric curves r(t), parametric surfaces r(u, v) and 3D point sets.

Everything is sampled with NumPy float64 through the same expression compiler as the 2D graphs (no second maths engine). A sample that is not a finite
real number (a pole, a negative square root, a complex intermediate result, an overflow) is *undefined*: it is never replaced by a number, and no face or
line segment touches it, so the picture shows a hole rather than a misleading bridge. The same holds across a jump discontinuity.

A surface is kept as the grid it was sampled on: ``cells`` are the grid quads whose four corners are defined and not separated by a jump, listed as
``[a, b, d, c]`` = (i, j), (i+1, j), (i+1, j+1), (i, j+1). Every consumer triangulates a cell the same way (``triangulate``): (a, b, d) and (a, d, c),
which for z = f(x, y) is counter-clockwise seen from +z, so the face normal is (-f_x, -f_y, 1) up to scale. For a parametric surface the front side
is the one the cross product (dr/du) x (dr/dv) points to. Triangles that collapse to a point or a line (the poles of a sphere, say) are dropped.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ...errors import BadRequest, MissingVariableError, SciCalError
from ..expressions import ast as A
from ..expressions.printer import to_text
from .plot import Plotter, _num, _r

CONTRACT = "scical-graph/1"
MAX_LAYERS_3D = 12
MAX_AXIS_SAMPLES = 160
MIN_AXIS_SAMPLES = 2
MAX_GRID_VERTICES = 25_600
MAX_CURVE_POINTS = 20_000
MAX_SCATTER_POINTS = 20_000
DEFAULT_SURFACE_SAMPLES = 48
DEFAULT_CURVE_SAMPLES = 400
BIG = 1e12                    # magnitudes beyond this are treated as overflow, not as data
JUMP_FRACTION = 0.5           # a step between neighbouring samples larger than this share of the plotted range is a discontinuity
CLIP_MARGIN = 0.75            # automatic z window: the central 98 % of the values, widened by this share of their span on each side
SURFACE_TYPES = ("surface", "curve3d", "psurface", "points3d")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


# ---------------------------------------------------------------------------------------------------------------------- geometry
def triangulate(cells: np.ndarray, vertices: np.ndarray | None = None) -> np.ndarray:
    """Triangles (T, 3) from grid cells [a, b, d, c]: (a, b, d) then (a, d, c) per cell. With ``vertices`` given, triangles with (almost) no area are removed."""
    if len(cells) == 0:
        return np.zeros((0, 3), dtype=np.int64)
    a, b, d, c = cells[:, 0], cells[:, 1], cells[:, 2], cells[:, 3]
    tri = np.empty((2 * len(cells), 3), dtype=np.int64)
    tri[0::2] = np.stack([a, b, d], axis=1)
    tri[1::2] = np.stack([a, d, c], axis=1)
    if vertices is not None and len(tri):
        p = vertices[tri]
        area2 = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
        scale = float(np.max(np.ptp(vertices, axis=0))) if len(vertices) else 1.0
        tri = tri[area2 > 1e-12 * max(scale, 1e-300) ** 2]
    return tri


def vertex_normals(vertices: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Area-weighted vertex normals (unit length; (0, 0, 1) where a vertex has no area)."""
    acc = np.zeros_like(vertices)
    if len(triangles):
        p = vertices[triangles]
        fn = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])           # length = 2 x area, so larger faces weigh more
        for k in range(3):
            np.add.at(acc, triangles[:, k], fn)
    n = np.linalg.norm(acc, axis=1)
    out = np.zeros_like(acc)
    ok = n > 1e-300
    out[ok] = acc[ok] / n[ok, None]
    out[~ok] = (0.0, 0.0, 1.0)
    return out


@dataclass
class SurfaceMesh:
    vertices: np.ndarray                  # (N, 3) float64, only vertices that a cell uses
    cells: np.ndarray                     # (M, 4) int, indices into ``vertices``
    normals: np.ndarray                   # (N, 3) unit vectors
    grid: tuple[int, int]
    stats: dict[str, Any] = field(default_factory=dict)
    grid_index: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))      # original flat grid index (i * nv + j) of each vertex

    def triangles(self) -> np.ndarray:
        return triangulate(self.cells, self.vertices)


@dataclass
class CurveSet:
    segments: list[np.ndarray]            # each (k, 3), k >= 2
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class PointSet:
    points: np.ndarray                    # (n, 3)
    stats: dict[str, Any] = field(default_factory=dict)


def _grid_to_mesh(P: np.ndarray, explicit: bool, zlimits: tuple[float | None, float | None]) -> SurfaceMesh:
    """P is (nu, nv, 3) with NaN for undefined samples."""
    nu, nv = P.shape[:2]
    finite = np.all(np.isfinite(P), axis=2) & np.all(np.abs(P) < BIG, axis=2)
    valid = finite.copy()
    undefined = int(finite.size - finite.sum())
    clipped = 0
    window: tuple[float, float] | None = None
    if explicit:
        z = np.where(valid, P[..., 2], np.nan)
        lo, hi = zlimits
        if lo is not None or hi is not None:
            window = (-math.inf if lo is None else lo, math.inf if hi is None else hi)
        elif int(valid.sum()) >= 16:
            p1, p99 = np.nanpercentile(z, [1, 99])
            span = float(p99 - p1)
            if span > 0:
                window = (float(p1) - CLIP_MARGIN * span, float(p99) + CLIP_MARGIN * span)
        if window is not None:
            inside = valid & (z >= window[0]) & (z <= window[1])
            clipped = int(valid.sum() - inside.sum())
            valid = inside
    Q = np.where(valid[..., None], P, 0.0)
    cv = valid[:-1, :-1] & valid[1:, :-1] & valid[1:, 1:] & valid[:-1, 1:]
    jump = np.zeros_like(cv)
    if cv.any():
        if explicit:
            zv = P[..., 2][valid]
            span = float(zv.max() - zv.min())
            thr = JUMP_FRACTION * span if span > 0 else math.inf
            zz = Q[..., 2]
            d = np.maximum.reduce([np.abs(zz[1:, :-1] - zz[:-1, :-1]), np.abs(zz[1:, 1:] - zz[1:, :-1]),
                                   np.abs(zz[1:, 1:] - zz[:-1, 1:]), np.abs(zz[:-1, 1:] - zz[:-1, :-1])])
        else:
            pts = P[valid]
            diag = float(np.linalg.norm(pts.max(axis=0) - pts.min(axis=0)))
            thr = JUMP_FRACTION * diag if diag > 0 else math.inf
            d = np.maximum.reduce([np.linalg.norm(Q[1:, :-1] - Q[:-1, :-1], axis=2), np.linalg.norm(Q[1:, 1:] - Q[1:, :-1], axis=2),
                                   np.linalg.norm(Q[1:, 1:] - Q[:-1, 1:], axis=2), np.linalg.norm(Q[:-1, 1:] - Q[:-1, :-1], axis=2)])
        jump = cv & (d > thr)
    keep = cv & ~jump
    I, J = np.nonzero(keep)
    a = I * nv + J
    cells_flat = np.stack([a, a + nv, a + nv + 1, a + 1], axis=1)
    used = np.unique(cells_flat)
    remap = np.full(nu * nv, -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    vertices = P.reshape(-1, 3)[used]
    cells = remap[cells_flat] if len(cells_flat) else np.zeros((0, 4), dtype=np.int64)
    mesh = SurfaceMesh(vertices, cells, np.zeros((len(vertices), 3)), (nu, nv),
                       grid_index=used.astype(np.int64), stats={"samples": int(nu * nv), "undefined": undefined, "clipped": clipped, "brokenCells": int(jump.sum()), "cells": int(len(cells)),
                        "zWindow": None if window is None or not all(math.isfinite(w) for w in window) else [_r(window[0]), _r(window[1])]})
    tris = mesh.triangles()
    mesh.normals = vertex_normals(vertices, tris)
    mesh.stats["triangles"] = int(len(tris))          # without the degenerate ones (the poles of a sphere)
    return mesh


def _polylines(P: np.ndarray, explicit_scale: float | None = None) -> CurveSet:
    """Split a sampled curve (n, 3) at undefined samples and at jumps."""
    ok = np.all(np.isfinite(P), axis=1) & np.all(np.abs(P) < BIG, axis=1)
    n = len(P)
    stats: dict[str, Any] = {"samples": int(n), "undefined": int(n - ok.sum()), "breaks": 0}
    if ok.sum() < 2:
        return CurveSet([], stats)
    good = P[ok]
    diag = float(np.linalg.norm(good.max(axis=0) - good.min(axis=0)))
    step = np.linalg.norm(np.diff(np.where(ok[:, None], P, 0.0), axis=0), axis=1)
    both = ok[:-1] & ok[1:]
    med = float(np.median(step[both])) if both.any() else 0.0
    far = both & (step > max(12.0 * med, 0.1 * diag))
    stats["breaks"] = int(far.sum())
    link = both & ~far                                    # segment i joins sample i and i + 1
    segments: list[np.ndarray] = []
    start = None
    for i in range(n - 1):
        if link[i]:
            if start is None:
                start = i
        elif start is not None:
            segments.append(P[start:i + 1])
            start = None
    if start is not None:
        segments.append(P[start:n])
    return CurveSet([s for s in segments if len(s) >= 2], stats)


# ---------------------------------------------------------------------------------------------------------------------- sampling
class Space(Plotter):
    """Samples the layers of a 3D scene. ``sample`` returns numpy structures (full precision, used by the exporters); ``render3d`` returns JSON."""

    # ---- inputs
    def _count(self, v: Any, default: int, what: str, lo: int, hi: int) -> int:
        n = int(self.const(v, what)) if v is not None else default
        if not lo <= n <= hi:
            raise BadRequest(f"{what} must be between {lo} and {hi}")
        return n

    def _range(self, layer: dict, lo_key: str, hi_key: str, default: tuple[float, float], what: str) -> tuple[float, float]:
        lo = self.const(layer.get(lo_key, default[0]), lo_key) if layer.get(lo_key) is not None else default[0]
        hi = self.const(layer.get(hi_key, default[1]), hi_key) if layer.get(hi_key) is not None else default[1]
        if not lo < hi:
            raise BadRequest(f"{what}: {lo_key} must be smaller than {hi_key}")
        if max(abs(lo), abs(hi)) > 1e9:
            raise BadRequest(f"{what}: the range is too large to draw")
        return lo, hi

    def default_domain(self) -> dict[str, tuple[float, float]]:
        d = self.spec.get("domain") if isinstance(self.spec.get("domain"), dict) else {}
        out = {}
        for k in ("x", "y"):
            lo = self.const(d.get(k + "min", -5), k + "min") if d.get(k + "min") is not None else -5.0
            hi = self.const(d.get(k + "max", 5), k + "max") if d.get(k + "max") is not None else 5.0
            if not lo < hi:
                raise BadRequest(f"The domain needs {k}min < {k}max")
            out[k] = (lo, hi)
        return out

    def _samples(self, layer: dict) -> tuple[int, int]:
        s = layer.get("samples")
        base = self.spec.get("samples") if isinstance(self.spec.get("samples"), dict) else {}
        nu = self._count(layer.get("usamples", (s or {}).get("u") if isinstance(s, dict) else s) if (layer.get("usamples") is not None or s is not None)
                         else base.get("u"), DEFAULT_SURFACE_SAMPLES, "samples", MIN_AXIS_SAMPLES, MAX_AXIS_SAMPLES)
        nv = self._count(layer.get("vsamples", (s or {}).get("v") if isinstance(s, dict) else s) if (layer.get("vsamples") is not None or s is not None)
                         else base.get("v"), DEFAULT_SURFACE_SAMPLES, "samples", MIN_AXIS_SAMPLES, MAX_AXIS_SAMPLES)
        if nu * nv > MAX_GRID_VERTICES:
            raise BadRequest(f"{nu} x {nv} samples is too many (the limit is {MAX_GRID_VERTICES} points per surface)")
        return nu, nv

    def _style(self, layer: dict) -> dict:
        out: dict[str, Any] = {}
        c = layer.get("color")
        if isinstance(c, str) and _COLOR.match(c):
            out["color"] = c.lower()
        op = layer.get("opacity")
        if op is not None:
            out["opacity"] = min(1.0, max(0.05, _num(op, "opacity")))
        for k in ("wireframe", "mesh", "colorBy"):
            if layer.get(k) is not None:
                out[k] = layer[k] if k == "colorBy" and layer[k] in ("height", "solid") else bool(layer[k]) if k != "colorBy" else "height"
        return out

    def _real(self, c: Any, *args: np.ndarray) -> np.ndarray:
        with np.errstate(all="ignore"):
            v = np.asarray(c.fn(*args))
        if np.iscomplexobj(v):                      # a complex intermediate result: undefined unless it is real to rounding
            v = np.where(np.abs(v.imag) <= 1e-12 * np.maximum(1.0, np.abs(v.real)), v.real, np.nan)
        return v.astype(float, copy=False)

    def _need_only(self, node: A.Node, allowed: set[str]) -> None:
        extra = self.free(node) - allowed
        if extra:
            nm = sorted(extra)[0]
            raise MissingVariableError(f"'{nm}' has no value", hint=f"Give it a value (for example {nm} := 2) or add a slider for it.")

    # ---- layer types
    def sample(self, layer: dict) -> dict[str, Any]:
        if not isinstance(layer, dict):
            raise BadRequest("Each layer must be an object")
        t = layer.get("type", "surface")
        if t not in SURFACE_TYPES:
            raise BadRequest(f"Unknown 3D layer type '{t}'", hint="3D layers: " + ", ".join(SURFACE_TYPES))
        return getattr(self, "s_" + t)(layer)

    def s_surface(self, layer: dict) -> dict:
        node = self.parse(layer.get("expr"), "surface formula")
        label = None
        if isinstance(node, A.Rel):
            if node.op != "=":
                raise BadRequest("A surface needs z = f(x, y), or just f(x, y)")
            if isinstance(node.left, A.Var) and node.left.name == "z":
                node = node.right
            elif isinstance(node.right, A.Var) and node.right.name == "z":
                node = node.left
            else:
                raise BadRequest("Write the surface as z = f(x, y)", hint="Implicit surfaces are not supported yet.")
        if isinstance(node, A.Var) and node.name in self.funcs and len(self.funcs[node.name].params) == 2:
            fd = self.funcs[node.name]
            node = A.Call(name=node.name, args=[A.Var(name=fd.params[0]), A.Var(name=fd.params[1])])
        self._need_only(node, {"x", "y"})
        dom = self.default_domain()
        xr = self._range(layer, "xmin", "xmax", dom["x"], "x domain")
        yr = self._range(layer, "ymin", "ymax", dom["y"], "y domain")
        nu, nv = self._samples(layer)
        c = self.comp(node, ("x", "y"))
        X, Y = np.meshgrid(np.linspace(*xr, nu), np.linspace(*yr, nv), indexing="ij")
        Z = np.broadcast_to(self._real(c, X, Y), X.shape)
        zlo = self.const(layer["zmin"], "zmin") if layer.get("zmin") is not None else None
        zhi = self.const(layer["zmax"], "zmax") if layer.get("zmax") is not None else None
        mesh = _grid_to_mesh(np.stack([X, Y, Z], axis=2), True, (zlo, zhi))
        label = label or "z = " + to_text(node)
        definition = {"type": "surface", "expr": to_text(node), "variables": ["x", "y"], "domain": {"x": list(xr), "y": list(yr)}, "samples": {"x": nu, "y": nv}}
        if zlo is not None or zhi is not None:
            definition["zLimits"] = [zlo, zhi]
        return {"kind": "mesh", "label": label, "definition": definition, "mesh": mesh, "style": self._style(layer)}

    def s_psurface(self, layer: dict) -> dict:
        nodes = [self.parse(layer.get(k), f"{k}(u, v)") for k in ("x", "y", "z")]
        for n in nodes:
            self._need_only(n, {"u", "v"})
        full = 2 * math.pi if self.angle == "rad" else 360.0
        ur = self._range(layer, "umin", "umax", (0.0, full), "u domain")
        vr = self._range(layer, "vmin", "vmax", (0.0, full), "v domain")
        nu, nv = self._samples(layer)
        U, V = np.meshgrid(np.linspace(*ur, nu), np.linspace(*vr, nv), indexing="ij")
        comps = [np.broadcast_to(self._real(self.comp(n, ("u", "v")), U, V), U.shape) for n in nodes]
        mesh = _grid_to_mesh(np.stack(comps, axis=2), False, (None, None))
        exprs = [to_text(n) for n in nodes]
        definition = {"type": "psurface", "expr": {"x": exprs[0], "y": exprs[1], "z": exprs[2]}, "variables": ["u", "v"],
                      "domain": {"u": list(ur), "v": list(vr)}, "samples": {"u": nu, "v": nv}}
        return {"kind": "mesh", "label": f"r(u, v) = ({', '.join(exprs)})", "definition": definition, "mesh": mesh, "style": self._style(layer)}

    def s_curve3d(self, layer: dict) -> dict:
        nodes = [self.parse(layer.get(k), f"{k}(t)") for k in ("x", "y", "z")]
        for n in nodes:
            self._need_only(n, {"t"})
        full = 2 * math.pi if self.angle == "rad" else 360.0
        tr = self._range(layer, "tmin", "tmax", (0.0, full), "t domain")
        n = self._count(layer.get("samples"), DEFAULT_CURVE_SAMPLES, "samples", 2, MAX_CURVE_POINTS)
        t = np.linspace(*tr, n)
        comps = [np.broadcast_to(self._real(self.comp(nd, ("t",)), t), t.shape) for nd in nodes]
        curves = _polylines(np.stack(comps, axis=1))
        exprs = [to_text(nd) for nd in nodes]
        definition = {"type": "curve3d", "expr": {"x": exprs[0], "y": exprs[1], "z": exprs[2]}, "variables": ["t"], "domain": {"t": list(tr)}, "samples": {"t": n}}
        return {"kind": "curve", "label": f"r(t) = ({', '.join(exprs)})", "definition": definition, "curves": curves, "style": self._style(layer)}

    def s_points3d(self, layer: dict) -> dict:
        cols = []
        for k in ("x", "y", "z"):
            v = layer.get(k)
            if not isinstance(v, list) or not v or len(v) > MAX_SCATTER_POINTS:
                raise BadRequest(f"{k} must be a list of 1 to {MAX_SCATTER_POINTS} numbers")
            cols.append([self.const(a, f"{k} value") for a in v])
        if not (len(cols[0]) == len(cols[1]) == len(cols[2])):
            raise BadRequest("x, y and z need the same number of values")
        pts = np.array(cols, dtype=float).T
        definition = {"type": "points3d", "count": int(len(pts))}
        return {"kind": "points", "label": layer.get("label") or "points", "definition": definition,
                "points": PointSet(pts, {"samples": int(len(pts))}), "style": self._style(layer)}

    # ---- whole scene
    def sample_all(self) -> list[dict[str, Any]]:
        layers = self.spec.get("layers")
        if not isinstance(layers, list) or len(layers) > MAX_LAYERS_3D:
            raise BadRequest(f"layers must be a list of at most {MAX_LAYERS_3D} layers")
        out = []
        for i, layer in enumerate(layers):
            lid = str(layer.get("id", f"layer{i}")) if isinstance(layer, dict) else f"layer{i}"
            try:
                if isinstance(layer, dict) and layer.get("visible", True) is False:
                    out.append({"id": lid, "ok": True, "kind": "hidden"})
                    continue
                res = self.sample(layer)
                res.update(id=lid, ok=True)
                out.append(res)
            except SciCalError as exc:
                out.append({"id": lid, "ok": False, "error": exc.to_dict()})
        return out

    def render3d(self) -> dict:
        sampled = self.sample_all()
        layers = [layer_json(s) for s in sampled]
        box = scene_bounds(sampled)
        return {"ok": True, "mode": "3d", "contract": CONTRACT, "layers": layers, "bounds": box, "angle": self.angle,
                "axes": axes_of(self.spec), "numeric": "float64 (NumPy); results on this page are approximations",
                "triangulation": "cells [a, b, d, c] -> (a, b, d) and (a, d, c)"}


# ---------------------------------------------------------------------------------------------------------------------- output
def axes_of(spec: dict) -> dict:
    """Axis labels and units as given (coordinate system metadata). Graph coordinates are dimensionless unless a unit is declared."""
    raw = spec.get("axes") if isinstance(spec.get("axes"), dict) else {}
    out = {}
    for k in ("x", "y", "z"):
        a = raw.get(k) if isinstance(raw.get(k), dict) else {}
        label = a.get("label") if isinstance(a.get("label"), str) and 0 < len(a["label"]) <= 40 else k
        unit = a.get("unit") if isinstance(a.get("unit"), str) and len(a["unit"]) <= 20 else ""
        out[k] = {"label": label, "unit": unit}
    return out


def _arrays(s: dict) -> list[np.ndarray]:
    if s["kind"] == "mesh":
        return [s["mesh"].vertices] if len(s["mesh"].vertices) else []
    if s["kind"] == "curve":
        return list(s["curves"].segments)
    if s["kind"] == "points":
        return [s["points"].points]
    return []


def scene_bounds(sampled: list[dict]) -> dict | None:
    pts = [a for s in sampled if s.get("ok") and s.get("kind") != "hidden" for a in _arrays(s)]
    if not pts:
        return None
    allp = np.concatenate(pts, axis=0)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    return {"xmin": _r(lo[0]), "xmax": _r(hi[0]), "ymin": _r(lo[1]), "ymax": _r(hi[1]), "zmin": _r(lo[2]), "zmax": _r(hi[2])}


def _flat(a: np.ndarray, digits: int = 9) -> list:
    return [float(f"{v:.{digits}g}") for v in a.ravel().tolist()]


def layer_json(s: dict) -> dict:
    if not s.get("ok"):
        return {"id": s["id"], "ok": False, "error": s["error"]}
    if s["kind"] == "hidden":
        return {"id": s["id"], "ok": True, "type": "hidden"}
    base = {"id": s["id"], "ok": True, "label": s["label"], "definition": s["definition"], "style": s["style"], "type": s["definition"]["type"]}
    if s["kind"] == "mesh":
        m: SurfaceMesh = s["mesh"]
        z = m.vertices[:, 2] if len(m.vertices) else np.zeros(0)
        base.update(grid={"nu": m.grid[0], "nv": m.grid[1]}, vertices=_flat(m.vertices), cells=m.cells.ravel().tolist(), normals=_flat(m.normals, 5),
                    stats=m.stats, zrange=[_r(float(z.min())), _r(float(z.max()))] if len(z) else None)
        if m.stats["cells"] == 0:
            base["warnings"] = ["No part of this surface is defined on the chosen domain."]
        elif m.stats["undefined"] or m.stats["clipped"] or m.stats["brokenCells"]:
            bits = []
            if m.stats["undefined"]:
                bits.append(f"{m.stats['undefined']} samples are undefined (shown as gaps)")
            if m.stats["clipped"]:
                bits.append(f"{m.stats['clipped']} samples lie outside the plotted z window and are cut off")
            if m.stats["brokenCells"]:
                bits.append(f"{m.stats['brokenCells']} cells across a jump are left open")
            base["warnings"] = ["; ".join(bits).capitalize() + "."]
    elif s["kind"] == "curve":
        cs: CurveSet = s["curves"]
        base.update(segments=[_flat(seg) for seg in cs.segments], stats=cs.stats)
        if cs.stats["undefined"] or cs.stats["breaks"]:
            base["warnings"] = [f"The curve is cut at {cs.stats['undefined']} undefined samples and {cs.stats['breaks']} jumps."]
    else:
        ps: PointSet = s["points"]
        base.update(points=_flat(ps.points), stats=ps.stats)
    return base


def render(ctx: Any, spec: dict) -> dict:
    return Space(ctx, spec).render3d()


def sample_export(ctx: Any, spec: dict) -> dict:
    """The sampled scene at full float64 precision, as plain lists, for the SGEO and SDRW exporters (``render`` rounds to 9 digits for the browser).

    Besides the triangulation inputs it keeps ``gridIndex`` (the original grid position of every kept vertex) so that a projection can rebuild the
    grid lines of a surface, and the numeric ``params`` that were in force. Hidden layers are not exported; a layer that failed is listed with its error."""
    sp = Space(ctx, spec)
    layers: list[dict] = []
    for s in sp.sample_all():
        if not s.get("ok"):
            layers.append({"id": s["id"], "ok": False, "error": s["error"]})
            continue
        if s["kind"] == "hidden":
            continue
        base = {"id": s["id"], "ok": True, "kind": s["kind"], "label": s["label"], "definition": s["definition"], "style": s["style"]}
        if s["kind"] == "mesh":
            m: SurfaceMesh = s["mesh"]
            base.update(vertices=m.vertices.tolist(), cells=m.cells.tolist(), grid=list(m.grid), stats=m.stats, gridIndex=m.grid_index.tolist())
        elif s["kind"] == "curve":
            base.update(segments=[seg.tolist() for seg in s["curves"].segments], stats=s["curves"].stats)
        else:
            base.update(points=s["points"].points.tolist(), stats=s["points"].stats)
        layers.append(base)
    raw = spec.get("params") if isinstance(spec.get("params"), dict) else {}
    params = {str(k): float(v) for k, v in raw.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
    return {"ok": True, "contract": CONTRACT, "layers": layers, "bounds": _bounds_of(layers),
            "angle": sp.angle, "axes": axes_of(spec), "params": params, "triangulation": "cells [a, b, d, c] -> (a, b, d) and (a, d, c)"}


def _bounds_of(layers: list[dict]) -> dict | None:
    arrays: list[np.ndarray] = []
    for l in layers:
        if not l.get("ok"):
            continue
        if "vertices" in l and l["vertices"]:
            arrays.append(np.asarray(l["vertices"], dtype=float))
        for seg in l.get("segments", []):
            arrays.append(np.asarray(seg, dtype=float))
        if l.get("points"):
            arrays.append(np.asarray(l["points"], dtype=float))
    if not arrays:
        return None
    allp = np.concatenate(arrays, axis=0)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    return {"xmin": float(lo[0]), "xmax": float(hi[0]), "ymin": float(lo[1]), "ymax": float(hi[1]), "zmin": float(lo[2]), "zmax": float(hi[2])}
