"""Saving graphs as SGEO (3D) and SDRW (2D) through SLAI's own document classes.

SciCal does not write these formats itself. It builds an ``SGEODocument`` or ``SDRWDocument`` from ``src.utils.sgeo`` / ``src.utils.sdrw`` (the stable
facades over ``spatial_formats``), saves it with the facade's atomic, verified writer, opens the file again and validates it.

What is stored, and what is not
-------------------------------
* A graph has a **definition** (the formula, domain, parameters) and **sampled geometry** (what was computed from it). Both are kept: the geometry is the
  SGEO mesh / curve / SDRW polyline, the definition is metadata under ``scical:*`` on the same object, with a ``slai.claims`` provenance claim that says
  the geometry was derived from that definition and how. The sampled geometry is an approximation of the definition; the file says so.
* SGEO has no normals field and no per-vertex colour: normals are recomputed by whoever reads the file, and a surface coloured by height is exported with
  its base colour (the height range is in the metadata). Both are reported in ``notes``.
* A 3D scene saved as SDRW is a **derived, lossy** drawing (an orthographic wireframe or a contour map). It is labelled as such in the drawing, in its
  metadata and in the result; it is never presented as the 3D model.
* Things that cannot be represented are listed in ``skipped``, never dropped silently.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import __version__
from ..core.graphing.space import CONTRACT, triangulate
from ..errors import BadRequest, SciCalError
from .exports import safe_name

UNITS = ("mm", "cm", "m", "km", "in", "ft")
BOX_HEIGHT = 0.78                 # the height of the plot box relative to its width in "fit to box" mode; keep equal to BOX_HEIGHT in src/core/scene3d.ts
PAGE_WIDTH = 100.0                # a projected drawing is scaled so that the (normalised) plot box is this wide, in drawing units
MAX_EXPORT_POINTS = 5_000         # a point set becomes one SGEO point object per point
MAX_INLINE_BYTES = 24 * 1024 * 1024
MIN_CROSS2 = 1e-27                # SGEO rejects triangles whose squared cross product is below 1e-30; stay clear of it
AGENT = "slai-scical"


class SpatialExportError(SciCalError):
    code, status = "export_failed", 422


# ------------------------------------------------------------------------------------------------------------------ small helpers
def _rgb(hex_color: str | None, default: tuple[float, float, float] = (0.72, 0.6, 0.0)) -> tuple[float, float, float]:
    if isinstance(hex_color, str) and len(hex_color) == 7 and hex_color[0] == "#":
        try:
            return tuple(int(hex_color[i:i + 2], 16) / 255.0 for i in (1, 3, 5))     # type: ignore[return-value]
        except ValueError:
            pass
    return default


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _hex(c: str | None, default: str = "#b89b00") -> str:
    return c.lower() if isinstance(c, str) and len(c) == 7 and c[0] == "#" else default


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00"


def _name(text: Any, limit: int = 120) -> str:
    s = " ".join(str(text or "").split())
    return (s[: limit - 1] + "…") if len(s) > limit else s


def _claim(subject: str, predicate: str, evidence: list[str], digest: str, kind: str = "derivation") -> dict[str, Any]:
    return {"subject": subject, "predicate": predicate, "evidence": evidence, "confidence": 1.0, "kind": kind, "agent": AGENT, "timestamp": _now(),
            "provenance": {"source": AGENT, "adapter": CONTRACT, "adapter_version": __version__, "digest": digest}}


def _unit(unit: Any) -> str:
    u = str(unit or "m")
    if u not in UNITS:
        raise BadRequest(f"Unknown unit '{u}'", hint="Units: " + ", ".join(UNITS))
    return u


def _issues(report: Any, limit: int = 12) -> list[dict[str, Any]]:
    out = []
    for i in list(getattr(report, "issues", ()))[:limit]:
        out.append({"severity": getattr(i, "severity", ""), "code": getattr(i, "code", ""), "message": getattr(i, "message", str(i))})
    return out


def _wrap(fmt: str, fn: Callable[[], Any], spatial_error: type[BaseException]) -> Any:
    """Run SLAI's writer; turn its typed errors into a message SciCal can show."""
    try:
        return fn()
    except SciCalError:
        raise
    except spatial_error as exc:
        raise SpatialExportError(f"SLAI's {fmt} writer rejected the graph: {exc}") from exc


# ------------------------------------------------------------------------------------------------------------------ writing
def _free_path(folder: Path, filename: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stem, dot, ext = filename.rpartition(".")
    path = folder / filename
    n = 2
    while path.exists():                                   # a saved file is never overwritten
        path = folder / f"{stem}-{n}.{ext}"
        n += 1
    return path


_INSPECT_DROP = {"path", "read_only", "closed", "dirty", "source_sha256"}      # what inspect() says about the handle, not about the document


def save_and_verify(doc: Any, module: Any, out_dir: Path, filename: str, fmt: str) -> dict[str, Any]:
    """Validate, save through SLAI's atomic writer, then open the file again and validate it. Returns what was verified."""
    report = _wrap(fmt, lambda: doc.validate(), module.SpatialFormatError)
    if not report.ok:
        first = report.errors[0]
        raise SpatialExportError(f"The {fmt} document did not validate: {getattr(first, 'message', first)}", details={"issues": _issues(report)})
    path = _free_path(out_dir, filename)
    saved = _wrap(fmt, lambda: doc.save(path), module.SpatialFormatError)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != saved.sha256:
        raise SpatialExportError(f"The saved {fmt} file does not match the digest the writer reported", details={"expected": saved.sha256, "actual": sha})
    back = _wrap(fmt, lambda: module.open_document(path), module.SpatialFormatError)
    try:
        again = back.validate()
        info = back.inspect()
        counts = {k: v for k, v in info.items() if k not in _INSPECT_DROP} if isinstance(info, dict) else None
    finally:
        back.close()
    if not again.ok:
        raise SpatialExportError(f"The saved {fmt} file did not validate when opened again", details={"issues": _issues(again)})
    out = {"path": str(path), "filename": path.name, "sha256": sha, "size": len(data), "documentId": saved.document_id, "revision": saved.revision,
           "validation": {"mode": again.mode, "ok": True, "errors": 0, "warnings": len(again.warnings), "issues": _issues(again), "reopened": True},
           "counts": counts}
    if len(data) <= MAX_INLINE_BYTES:
        out["contentBase64"] = base64.b64encode(data).decode("ascii")
    return out


# ------------------------------------------------------------------------------------------------------------------ SGEO
def build_sgeo(sgeo: Any, sample: dict[str, Any], *, name: str, unit: str) -> tuple[Any, dict[str, Any]]:
    """An SGEODocument from the full-precision sample of a 3D scene (``space.sample_export``)."""
    unit = _unit(unit)
    layers = [l for l in sample["layers"]]
    skipped: list[dict[str, Any]] = [{"id": l["id"], "reason": l["error"].get("message", "The layer could not be computed.")} for l in layers if not l.get("ok")]
    usable = [l for l in layers if l.get("ok")]
    if not usable:
        raise BadRequest("There is nothing to save: no layer of the scene produced geometry.", details={"skipped": skipped})
    notes = ["SGEO stores no normals: they are recomputed from the triangles by whoever opens the file.",
             "The geometry is the sampled approximation (float64) of each definition, not the exact surface. The definition is stored next to it as metadata.",
             f"Graph coordinates have no unit of their own; one graph unit is saved as 1 {unit}."]
    meta = {"scical:contract": CONTRACT, "scical:source": "graph3d", "scical:app": f"{AGENT} {__version__}", "scical:axes": sample["axes"], "scical:bounds": sample["bounds"],
            "scical:angle_mode": sample["angle"], "scical:params": sample["params"], "scical:unit_assumption": f"1 graph unit = 1 {unit}",
            "scical:triangulation": sample["triangulation"]}
    doc = sgeo.new(_name(name, 100) or "SciCal 3D graph", unit=unit, metadata=meta)
    exported: list[dict[str, Any]] = []
    for layer in usable:
        definition = layer["definition"]
        digest = _digest({"definition": definition, "params": sample["params"], "angle": sample["angle"]})
        style = layer.get("style", {})
        label = layer["label"]
        r, g, b = _rgb(style.get("color"))
        alpha = float(style.get("opacity", 1.0))
        common = {"scical:layer_id": layer["id"], "scical:layer_type": definition["type"], "scical:label": label, "scical:definition": definition,
                  "scical:geometry": "sampled approximation of the definition", "scical:style": style}
        mat = doc.add_material(_name(label, 60), base_color=[_linear(r), _linear(g), _linear(b), alpha], metallic=0.0, roughness=0.6, double_sided=True,
                               alpha_mode="blend" if alpha < 1.0 else "opaque", metadata={"scical:layer_id": layer["id"]})
        evidence = [f"scical-graph/1 definition {label}", f"sampled with NumPy float64; parameters {json.dumps(sample['params'], sort_keys=True)}"]
        if layer["kind"] == "mesh":
            exported.append(_sgeo_mesh(doc, layer, common, mat, evidence, digest, notes, skipped))
        elif layer["kind"] == "curve":
            exported.append(_sgeo_curve(doc, layer, common, mat, evidence, digest, skipped))
        else:
            exported.append(_sgeo_points(doc, layer, common, mat, evidence, digest, skipped))
    exported = [e for e in exported if e]
    if not exported:
        raise BadRequest("There is nothing to save: no layer produced usable geometry.", details={"skipped": skipped})
    if any(l.get("style", {}).get("colorBy") == "height" for l in usable if l["kind"] == "mesh"):
        notes.append("Surfaces coloured by height are saved with their base colour: SGEO has no per-vertex colour. The z range is in each object's metadata.")
    return doc, {"layers": exported, "skipped": skipped, "notes": notes}


def _sgeo_mesh(doc: Any, layer: dict, common: dict, mat: str, evidence: list[str], digest: str, notes: list[str], skipped: list[dict]) -> dict | None:
    V = np.asarray(layer["vertices"], dtype=float).reshape(-1, 3)
    C = np.asarray(layer["cells"], dtype=np.int64).reshape(-1, 4)
    tris = triangulate(C, V)
    if len(tris):
        p = V[tris]
        cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        tris = tris[(cr * cr).sum(axis=1) > MIN_CROSS2]
    dropped = int(2 * len(C) - len(tris))
    if len(tris) == 0:
        skipped.append({"id": layer["id"], "label": layer["label"], "reason": "No part of the surface is defined on the chosen domain, so there is no mesh."})
        return None
    used = np.unique(tris)
    remap = np.full(len(V), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    verts = V[used]
    faces = remap[tris]
    z = verts[:, 2]
    oid = str(uuid.uuid4())
    sampling = {"grid": layer["grid"], "vertices": int(len(verts)), "triangles": int(len(faces)), "degenerateTrianglesDropped": dropped, **layer["stats"],
                "zRange": [float(z.min()), float(z.max())]}
    meta = {**common, "scical:sampling": sampling, "slai.claims": [_claim(oid, "scical:sampled_from_definition", evidence, digest)]}
    doc.add_mesh(verts.tolist(), faces.tolist(), name=_name(layer["label"]), metadata=meta, material=mat, object_id=oid)
    if dropped:
        notes.append(f"{layer['label']}: {dropped} degenerate triangles (collapsed at a pole or a fold) were left out, as the sampler also does.")
    return {"id": layer["id"], "label": layer["label"], "kind": "mesh", "objects": 1, "vertices": int(len(verts)), "triangles": int(len(faces)), "objectIds": [oid]}


def _dedupe(points: np.ndarray) -> np.ndarray:
    if len(points) < 2:
        return points
    keep = np.concatenate([[True], np.any(points[1:] != points[:-1], axis=1)])
    return points[keep]


def _sgeo_curve(doc: Any, layer: dict, common: dict, mat: str, evidence: list[str], digest: str, skipped: list[dict]) -> dict | None:
    pieces = [_dedupe(np.asarray(s, dtype=float).reshape(-1, 3)) for s in layer["segments"]]
    pieces = [p for p in pieces if len(p) >= 2]
    if not pieces:
        skipped.append({"id": layer["id"], "label": layer["label"], "reason": "The curve has no defined piece on the chosen range."})
        return None
    total = int(sum(len(p) for p in pieces))
    sampling = {"pieces": len(pieces), "controlPoints": total, **layer["stats"]}
    ids: list[str] = []
    if len(pieces) == 1:
        oid = str(uuid.uuid4())
        meta = {**common, "scical:sampling": sampling, "scical:curve": "polyline of the sampled points, stored as a degree-1 NURBS curve", "slai.claims": [_claim(oid, "scical:sampled_from_definition", evidence, digest)]}
        doc.add_nurbs_curve(pieces[0].tolist(), degree=1, name=_name(layer["label"]), metadata=meta, material=mat, object_id=oid)
        ids.append(oid)
    else:
        gid = str(uuid.uuid4())
        meta = {**common, "scical:sampling": sampling, "scical:curve": "pieces of the sampled curve, each a degree-1 NURBS curve; the curve is cut where it is undefined or jumps",
                "slai.claims": [_claim(gid, "scical:sampled_from_definition", evidence, digest)]}
        doc.add_group(_name(layer["label"]), metadata=meta, object_id=gid)
        ids.append(gid)
        for i, piece in enumerate(pieces):
            cid = str(uuid.uuid4())
            doc.add_nurbs_curve(piece.tolist(), degree=1, name=_name(f"{layer['label']} piece {i + 1}"), parent=gid, material=mat, object_id=cid,
                                metadata={"scical:layer_id": layer["id"], "scical:piece": i})
            ids.append(cid)
    return {"id": layer["id"], "label": layer["label"], "kind": "curve", "objects": len(ids), "pieces": len(pieces), "controlPoints": total, "objectIds": ids}


def _sgeo_points(doc: Any, layer: dict, common: dict, mat: str, evidence: list[str], digest: str, skipped: list[dict]) -> dict | None:
    pts = np.asarray(layer["points"], dtype=float).reshape(-1, 3)
    if len(pts) > MAX_EXPORT_POINTS:
        skipped.append({"id": layer["id"], "label": layer["label"], "reason": f"{len(pts)} points: a point set is saved as one SGEO object per point, so it is limited to {MAX_EXPORT_POINTS}."})
        return None
    gid = str(uuid.uuid4())
    meta = {**common, "scical:sampling": {"points": int(len(pts))}, "scical:geometry": "the points as entered (exact)", "slai.claims": [_claim(gid, "scical:entered_by_user", [f"{len(pts)} points entered in SciCal"], digest, kind="observation")]}
    doc.add_group(_name(layer["label"]), metadata=meta, object_id=gid)
    ids = [gid]
    for i, p in enumerate(pts):
        ids.append(doc.add_point(p.tolist(), name=f"{_name(layer['label'], 60)} {i + 1}", parent=gid, material=mat, metadata={"scical:layer_id": layer["id"], "scical:index": i}))
    return {"id": layer["id"], "label": layer["label"], "kind": "points", "objects": len(ids), "points": int(len(pts)), "objectIds": ids}


# ------------------------------------------------------------------------------------------------------------------ projection maths
# These mirror src/core/scene3d.ts (normalizer and makeProjector); both are tested against the same numbers.
def normalizer(bounds: dict[str, float], aspect: str) -> tuple[np.ndarray, np.ndarray]:
    lo = np.array([bounds["xmin"], bounds["ymin"], bounds["zmin"]], dtype=float)
    hi = np.array([bounds["xmax"], bounds["ymax"], bounds["zmax"]], dtype=float)
    span = np.maximum(hi - lo, 1e-12 * np.maximum(1.0, np.maximum(np.abs(lo), np.abs(hi))))
    if aspect == "equal":
        scale = np.full(3, 1.0 / span.max())
    else:
        scale = np.array([1.0 / span[0], 1.0 / span[1], BOX_HEIGHT / span[2]])
    return (lo + hi) / 2.0, scale


def view_basis(azimuth: float, elevation: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(toViewer, right, up) for an orbit camera with +z up; elevation is clamped to +-89 degrees like the browser does."""
    el = max(-math.radians(89), min(math.radians(89), elevation))
    ce = math.cos(el)
    to_viewer = np.array([ce * math.cos(azimuth), ce * math.sin(azimuth), math.sin(el)])
    forward = -to_viewer
    right = np.cross(forward, [0.0, 0.0, 1.0])
    right = right / np.linalg.norm(right)
    up = np.cross(right, forward)
    return to_viewer, right, up


class Projection:
    """Orthographic projection of the displayed (normalised) scene onto the page; page x to the right, page y up, the box about PAGE_WIDTH wide."""

    def __init__(self, bounds: dict[str, float], aspect: str, azimuth: float, elevation: float) -> None:
        if aspect not in ("box", "equal"):
            raise BadRequest("aspect must be box or equal")
        self.bounds, self.aspect, self.azimuth, self.elevation = bounds, aspect, float(azimuth), float(elevation)
        self.center, self.scale = normalizer(bounds, aspect)
        self.to_viewer, self.right, self.up = view_basis(self.azimuth, self.elevation)

    def __call__(self, pts: np.ndarray) -> np.ndarray:
        u = (np.asarray(pts, dtype=float).reshape(-1, 3) - self.center) * self.scale
        return np.stack([u @ self.right, u @ self.up], axis=1) * PAGE_WIDTH

    def depth(self, pts: np.ndarray) -> np.ndarray:
        return ((np.asarray(pts, dtype=float).reshape(-1, 3) - self.center) * self.scale) @ self.to_viewer

    def describe(self) -> dict[str, Any]:
        return {"kind": "orthographic", "azimuthRad": self.azimuth, "elevationRad": self.elevation, "aspect": self.aspect, "pageWidth": PAGE_WIDTH,
                "center": self.center.tolist(), "scale": self.scale.tolist(), "right": self.right.tolist(), "up": self.up.tolist(),
                "formula": "page = ((p - center) * scale) . (right, up) * pageWidth; hidden lines are not removed"}


# ------------------------------------------------------------------------------------------------------------------ SDRW helpers
def _nice_step(span: float, target: float) -> float:
    raw = span / max(1.0, target)
    pw = 10 ** math.floor(math.log10(raw))
    f = raw / pw
    nice = 1 if f < 1.5 else 2 if f < 3.5 else 5 if f < 7.5 else 10
    return float(f"{nice * pw:.12g}")


def ticks(lo: float, hi: float, target: float) -> tuple[float, list[float]]:
    step = _nice_step(hi - lo, target)
    k = math.ceil(lo / step - 1e-9)
    vals: list[float] = []
    while k * step <= hi + step * 1e-9 and len(vals) < 400:
        v = k * step
        vals.append(0.0 if abs(v) < step * 1e-9 else float(f"{v:.12g}"))
        k += 1
    return step, vals


def _fmt(v: float) -> str:
    return "0" if v == 0 else f"{v:.10g}"


class Pen:
    """Adds entities to an SDRW document, one layer per purpose, skipping anything that is not a finite, non-degenerate shape."""

    def __init__(self, doc: Any, lw: float) -> None:
        self.doc, self.lw, self.count = doc, lw, 0
        self.known: set[str] = {"0"}
        self.lo = np.array([math.inf, math.inf])
        self.hi = np.array([-math.inf, -math.inf])

    def _grow(self, pts: Any) -> None:
        a = np.asarray(pts, dtype=float).reshape(-1, 2)
        self.lo = np.minimum(self.lo, a.min(axis=0))
        self.hi = np.maximum(self.hi, a.max(axis=0))

    def layer(self, name: str, stroke: str | None = None, width: float | None = None, linetype: str | None = None) -> str:
        name = _name(name, 60) or "layer"
        if name not in self.known:
            self.doc.add_layer(name, stroke=stroke, stroke_width=width if width is not None else self.lw, linetype=linetype)
            self.known.add(name)
        return name

    def poly(self, pts: Any, layer: str, *, closed: bool = False, meta: dict | None = None, linetype: str | None = None, color: str | None = None, width: float | None = None) -> str | None:
        a = np.asarray(pts, dtype=float).reshape(-1, 2)
        a = a[np.all(np.isfinite(a), axis=1)]
        a = a[np.concatenate([[True], np.any(a[1:] != a[:-1], axis=1)])] if len(a) > 1 else a
        if len(a) < 2 or (closed and len(a) < 3):
            return None
        style = {k: v for k, v in (("stroke", color), ("stroke_width", width), ("linetype", linetype)) if v is not None}
        self.count += 1
        self._grow(a)
        return self.doc.add_polyline(a.tolist(), closed=closed, layer=layer, metadata=meta, style=style or None)

    def line(self, a: Any, b: Any, layer: str, *, meta: dict | None = None, linetype: str | None = None, color: str | None = None) -> str | None:
        if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))) or (a[0] == b[0] and a[1] == b[1]):
            return None
        style = {k: v for k, v in (("stroke", color), ("linetype", linetype)) if v is not None}
        self.count += 1
        self._grow([a, b])
        return self.doc.add_line([float(a[0]), float(a[1])], [float(b[0]), float(b[1])], layer=layer, metadata=meta, style=style or None)

    def point(self, p: Any, layer: str, *, meta: dict | None = None, color: str | None = None) -> str | None:
        if not np.all(np.isfinite(p)):
            return None
        self.count += 1
        self._grow([p])
        return self.doc.add_point([float(p[0]), float(p[1])], layer=layer, metadata=meta, style={"stroke": color} if color else None)

    def text(self, p: Any, text: str, height: float, layer: str, *, halign: str = "left", valign: str = "middle", meta: dict | None = None, color: str | None = None) -> str | None:
        if not np.all(np.isfinite(p)) or not text:
            return None
        self.count += 1
        self._grow([p])
        return self.doc.add_text([float(p[0]), float(p[1])], text, height, halign=halign, valign=valign, layer=layer, metadata=meta, style={"stroke": color} if color else None)


def _finish(doc: Any, pen: Pen) -> None:
    doc.set_metadata({"scical:entities": int(pen.count)})


# ------------------------------------------------------------------------------------------------------------------ SDRW from a 2D graph
def build_sdrw_graph(sdrw: Any, result: dict[str, Any], spec: dict[str, Any], colors: dict[str, str], *, name: str, unit: str) -> tuple[Any, dict[str, Any]]:
    """The 2D graph as the person sees it: axes, grid, one SDRW layer per graph layer, the curves as polylines, labels as text."""
    unit = _unit(unit if unit else "mm")
    v = result["view"]
    xmin, xmax, ymin, ymax = (float(v[k]) for k in ("xmin", "xmax", "ymin", "ymax"))
    w, h = xmax - xmin, ymax - ymin
    big = max(w, h)
    lw, th = big / 700.0, big * 0.026
    spec_layers = {str(l.get("id")): l for l in spec.get("layers", []) if isinstance(l, dict)}
    definitions = []
    for lr in result["layers"]:
        sl = spec_layers.get(str(lr["id"]), {})
        definitions.append({"id": lr["id"], "type": lr.get("type"), "label": lr.get("label"),
                            "spec": {k: sl[k] for k in ("type", "expr", "x", "y", "r", "fx", "fy", "tmin", "tmax", "nmin", "nmax", "fit", "bins") if k in sl and len(json.dumps(sl[k])) < 2000}})
    meta = {"scical:contract": CONTRACT, "scical:source": "graph2d", "scical:app": f"{AGENT} {__version__}", "scical:view": v, "scical:params": spec.get("params") or {},
            "scical:angle_mode": result.get("angle"), "scical:definitions": definitions,
            "scical:geometry": "polylines sampled from the definitions inside the view; one graph unit is one drawing unit",
            "scical:unit_assumption": f"1 graph unit = 1 {unit}"}
    doc = sdrw.new(_name(name, 100) or "SciCal graph", unit=unit, metadata=meta)
    doc.define_linetype("dashed", [big * 0.012, -big * 0.007], description="dashed")
    pen = Pen(doc, lw)
    skipped: list[dict[str, Any]] = []
    notes: list[str] = ["Curves are saved as the polylines that were sampled for the current view; zooming out later does not extend them."]
    # ---- frame, grid, axes, ticks
    ink, faint = "#4a5360", "#c3c9d4"
    pen.layer("frame", ink, lw * 1.4)
    pen.poly([[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax]], "frame", closed=True, meta={"scical:role": "view frame"})
    xs, xt = ticks(xmin, xmax, 8)
    ys, yt = ticks(ymin, ymax, 6)
    pen.layer("grid", faint, lw * 0.6)
    for x in xt:
        pen.line([x, ymin], [x, ymax], "grid", meta={"scical:role": "grid", "scical:x": x})
    for y in yt:
        pen.line([xmin, y], [xmax, y], "grid", meta={"scical:role": "grid", "scical:y": y})
    pen.layer("axes", ink, lw * 1.6)
    ay, ax = min(max(0.0, ymin), ymax), min(max(0.0, xmin), xmax)
    pen.line([xmin, ay], [xmax, ay], "axes", meta={"scical:role": "x axis"})
    pen.line([ax, ymin], [ax, ymax], "axes", meta={"scical:role": "y axis"})
    pen.layer("tick labels", ink, lw)
    for x in xt:
        if x != 0:
            pen.text([x, ymin - th * 0.9], _fmt(x), th, "tick labels", halign="center", meta={"scical:role": "x tick", "scical:value": x})
    for y in yt:
        if y != 0:
            pen.text([xmin - th * 0.4, y], _fmt(y), th, "tick labels", halign="right", meta={"scical:role": "y tick", "scical:value": y})
    # ---- graph layers
    legend: list[tuple[str, str]] = []
    n = 0
    for lr in result["layers"]:
        if not lr.get("ok"):
            skipped.append({"id": lr["id"], "reason": (lr.get("error") or {}).get("message", "The layer could not be drawn.")})
            continue
        t = lr.get("type")
        if t == "hidden":
            continue
        n += 1
        color = _hex(colors.get(str(lr["id"])), "#b89b00")
        label = str(lr.get("label") or t)
        lname = pen.layer(f"{n:02d} {label}", color, lw * 2.2)
        base = {"scical:layer_id": lr["id"], "scical:layer_type": t, "scical:label": label}
        made = 0

        def add_lines(lines: Any, role: str, linetype: str | None = None) -> int:
            c = 0
            for seg in lines or []:
                if pen.poly(seg, lname, meta={**base, "scical:role": role}, linetype=linetype):
                    c += 1
            return c

        if t in ("function", "parametric", "polar"):
            made += add_lines(lr.get("segments"), "curve")
            for a in lr.get("asymptotes") or []:
                made += 1 if pen.line([a, ymin], [a, ymax], lname, meta={**base, "scical:role": "asymptote", "scical:x": a}, linetype="dashed") else 0
        elif t == "implicit":
            made += add_lines(lr.get("polylines"), "curve")
        elif t == "vline":
            made += 1 if pen.line([lr["x"], ymin], [lr["x"], ymax], lname, meta={**base, "scical:role": "vertical line", "scical:x": lr["x"]}) else 0
        elif t == "inequality":
            made += add_lines(lr.get("boundary"), "boundary", "dashed" if lr.get("strict") else None)
            skipped.append({"id": lr["id"], "label": label, "reason": "The shaded region of an inequality is not saved (only its boundary line)."})
        elif t in ("sequence", "scatter"):
            for p in lr.get("points") or []:
                made += 1 if pen.point(p, lname, meta={**base, "scical:role": "point", "scical:x": p[0], "scical:y": p[1]}, color=color) else 0
            fit = lr.get("fit")
            if isinstance(fit, dict):
                made += add_lines(fit.get("segments"), f"fit: {fit.get('equation', '')}", "dashed")
        elif t == "histogram":
            bars = lr.get("bars") or []
            top = max([1] + [b["count"] for b in bars])
            for b in bars:
                hgt = b["count"] / top * 0.7 * h
                if pen.poly([[b["x0"], 0.0], [b["x1"], 0.0], [b["x1"], hgt], [b["x0"], hgt]], lname, closed=True,
                            meta={**base, "scical:role": "bar", "scical:count": b["count"], "scical:density": b["density"], "scical:x0": b["x0"], "scical:x1": b["x1"]}):
                    made += 1
            notes.append("Histogram bar heights are drawn as on screen (count / largest count x 70 % of the view height); each bar carries its count and density in its metadata.")
        elif t == "vectorfield":
            for a in lr.get("arrows") or []:
                x, y, dx, dy = a[0], a[1], a[2], a[3]
                tail, head = np.array([x - dx / 2, y - dy / 2]), np.array([x + dx / 2, y + dy / 2])
                ang = math.atan2(dy, dx)
                size = math.hypot(dx, dy) * 0.3
                if pen.line(tail, head, lname, meta={**base, "scical:role": "arrow", "scical:x": x, "scical:y": y}):
                    made += 1
                    pen.poly([head, head - size * np.array([math.cos(ang - .4), math.sin(ang - .4)]), head - size * np.array([math.cos(ang + .4), math.sin(ang + .4)])], lname, closed=True,
                             meta={**base, "scical:role": "arrow head"})
        else:
            skipped.append({"id": lr["id"], "label": label, "reason": f"Layers of type '{t}' have no drawing representation yet."})
            continue
        if made == 0:
            skipped.append({"id": lr["id"], "label": label, "reason": "Nothing of this layer is inside the view."})
        legend.append((label, color))
    # ---- legend (text) inside the frame
    if legend:
        pen.layer("legend", ink, lw)
        y = ymax - th * 1.4
        for label, color in legend:
            pen.line([xmin + th * 0.5, y], [xmin + th * 2.2, y], "legend", color=color, meta={"scical:role": "legend swatch"})
            pen.text([xmin + th * 2.6, y], _name(label, 60), th, "legend", meta={"scical:role": "legend"})
            y -= th * 1.5
    _finish(doc, pen)
    shown = sum(1 for _ in legend)
    return doc, {"layers": [{"label": l, "color": c} for l, c in legend], "skipped": skipped, "notes": notes, "entities": pen.count, "drawn": shown}


# ------------------------------------------------------------------------------------------------------------------ SDRW from a 3D scene (derived)
def _grid_lines(layer: dict) -> list[tuple[str, list[int]]]:
    """Polylines (as vertex index lists) along the grid rows and columns of a surface, broken wherever a cell is missing."""
    nu, nv = layer["grid"]
    gi = np.asarray(layer["gridIndex"], dtype=np.int64)
    cells = np.asarray(layer["cells"], dtype=np.int64).reshape(-1, 4)
    I, J = gi // nv, gi % nv
    edges: dict[tuple[str, int], dict[int, tuple[int, int]]] = {}
    for a, b, d, c in cells.tolist():
        i, j = int(I[a]), int(J[a])
        edges.setdefault(("u", j), {})[i] = (a, b)
        edges.setdefault(("u", j + 1), {})[i] = (c, d)
        edges.setdefault(("v", i), {})[j] = (a, c)
        edges.setdefault(("v", i + 1), {})[j] = (b, d)
    out: list[tuple[str, list[int]]] = []
    for (kind, fixed), m in sorted(edges.items()):
        run: list[int] = []
        last = None
        for t in sorted(m):
            v0, v1 = m[t]
            if last is None or t != last + 1:
                if len(run) > 1:
                    out.append((kind, run))
                run = [v0]
            run.append(v1)
            last = t
        if len(run) > 1:
            out.append((kind, run))
    return out


def contour_polylines(V: np.ndarray, tris: np.ndarray, level: float) -> list[np.ndarray]:
    """Iso-lines z = level of a triangle mesh (marching triangles), joined into polylines through the mesh edges they cross. Returns (k, 3) arrays."""
    z = V[:, 2] - level
    z = np.where(z == 0.0, np.nextafter(0.0, 1.0), z)            # a vertex exactly on the level counts as slightly above it, so every crossing is on an edge
    segs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    pos: dict[tuple[int, int], np.ndarray] = {}
    for tri in tris.tolist():
        crossing = []
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            if (z[a] > 0) != (z[b] > 0):
                key = (a, b) if a < b else (b, a)
                if key not in pos:
                    t = z[a] / (z[a] - z[b])
                    pos[key] = V[a] + t * (V[b] - V[a])
                crossing.append(key)
        if len(crossing) == 2:
            segs.append((crossing[0], crossing[1]))
    adj: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for a, b in segs:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    seen: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    lines: list[np.ndarray] = []

    def walk(start: tuple[int, int], first: tuple[int, int]) -> list[tuple[int, int]]:
        path = [start, first]
        seen.add((start, first)); seen.add((first, start))
        cur, prev = first, start
        while True:
            nxt = [n for n in adj[cur] if n != prev and (cur, n) not in seen]
            if not nxt:
                return path
            seen.add((cur, nxt[0])); seen.add((nxt[0], cur))
            prev, cur = cur, nxt[0]
            path.append(cur)
            if cur == path[0]:
                return path
    ends = [k for k, v in adj.items() if len(v) == 1]
    for start in ends:
        for n in adj[start]:
            if (start, n) not in seen:
                lines.append(np.array([pos[k] for k in walk(start, n)]))
    for start in list(adj):                                        # what is left are closed loops
        for n in adj[start]:
            if (start, n) not in seen:
                lines.append(np.array([pos[k] for k in walk(start, n)]))
    return lines


def build_sdrw_projection(sdrw: Any, sample: dict[str, Any], view: dict[str, Any], colors: dict[str, str], *, name: str, unit: str, mode: str) -> tuple[Any, dict[str, Any]]:
    """A labelled 2D drawing derived from a 3D scene: ``wireframe`` (orthographic projection at the current camera) or ``contours`` (plan view of explicit surfaces)."""
    unit = _unit(unit if unit else "mm")
    if mode not in ("wireframe", "contours"):
        raise BadRequest("mode must be wireframe or contours")
    bounds = sample.get("bounds")
    usable = [l for l in sample["layers"] if l.get("ok")]
    skipped: list[dict[str, Any]] = [{"id": l["id"], "reason": l["error"].get("message", "The layer could not be computed.")} for l in sample["layers"] if not l.get("ok")]
    if not usable or not bounds:
        raise BadRequest("There is nothing to save: no layer of the scene produced geometry.", details={"skipped": skipped})
    aspect = view.get("aspect", "box")
    proj = Projection(bounds, aspect, float(view.get("azimuth", -0.9)), float(view.get("elevation", 0.42)))
    notes = ["This drawing is derived from the 3D scene and is not the model: depth and surface shading are lost" + (", hidden lines are not removed." if mode == "wireframe" else ".")]
    if mode == "wireframe":
        notes.append("The projection is orthographic at the camera's direction, even if the screen showed perspective; its parameters are in the document metadata (scical:projection).")
    title = ("Orthographic projection of the 3D scene (derived drawing, hidden lines not removed)" if mode == "wireframe"
             else "Contour map of the 3D scene (derived drawing: plan view, lines of equal z)")
    lw, th = PAGE_WIDTH / 520.0, PAGE_WIDTH * 0.03
    meta = {"scical:contract": CONTRACT, "scical:source": "graph3d-projection", "scical:app": f"{AGENT} {__version__}", "scical:derived": title, "scical:lossy": True,
            "scical:axes": sample["axes"], "scical:bounds": bounds, "scical:angle_mode": sample["angle"], "scical:params": sample["params"],
            "scical:definitions": [{"id": l["id"], "label": l["label"], "definition": l["definition"]} for l in usable], "scical:unit_assumption": f"1 page unit = 1 {unit}"}
    if mode == "wireframe":
        meta["scical:projection"] = proj.describe()
    doc = sdrw.new(_name(name, 100) or "SciCal 3D graph (drawing)", unit=unit, metadata=meta)
    if mode == "wireframe":                                   # only the bounding box uses it
        doc.define_linetype("dashed", [th * 0.8, -th * 0.5], description="dashed")
    pen = Pen(doc, lw)
    ink = "#4a5360"
    exported: list[dict[str, Any]] = []
    if mode == "wireframe":
        pen.layer("box", "#9aa3b2", lw * 0.7, "dashed")
        lo = np.array([bounds["xmin"], bounds["ymin"], bounds["zmin"]]); hi = np.array([bounds["xmax"], bounds["ymax"], bounds["zmax"]])
        corners = {(i, j, k): np.where([i, j, k], hi, lo) for i in (0, 1) for j in (0, 1) for k in (0, 1)}
        for (i, j, k), p in corners.items():
            for axis in range(3):
                idx = [i, j, k]
                if idx[axis] == 0:
                    idx[axis] = 1
                    q = corners[tuple(idx)]
                    a, b = proj(np.array([p, q]))
                    pen.line(a, b, "box", meta={"scical:role": "bounding box edge"})
        pen.layer("axis labels", ink, lw)
        for k, (p, q) in {"x": (lo, np.array([hi[0], lo[1], lo[2]])), "y": (lo, np.array([lo[0], hi[1], lo[2]])), "z": (lo, np.array([lo[0], lo[1], hi[2]]))}.items():
            a = proj(np.array([q]))[0]
            ax = sample["axes"][k]
            pen.text(a + np.array([th * 0.5, th * 0.5]), f"{ax['label']}" + (f" ({ax['unit']})" if ax["unit"] else "") + f" {_fmt(float(lo['xyz'.index(k)]))} .. {_fmt(float(hi['xyz'.index(k)]))}", th * 0.8,
                     "axis labels", meta={"scical:role": "axis label", "scical:axis": k})
    legend: list[tuple[str, str]] = []
    for n, layer in enumerate(usable, 1):
        color = _hex(colors.get(str(layer["id"])), _hex(layer.get("style", {}).get("color")))
        label = layer["label"]
        base = {"scical:layer_id": layer["id"], "scical:layer_type": layer["definition"]["type"], "scical:label": label}
        made = 0
        if mode == "wireframe":
            lname = pen.layer(f"{n:02d} {label}", color, lw * 1.4)
            if layer["kind"] == "mesh":
                V = np.asarray(layer["vertices"], dtype=float).reshape(-1, 3)
                P = proj(V)
                for kind, run in _grid_lines(layer):
                    if pen.poly(P[run], lname, meta={**base, "scical:role": f"grid line along {'i' if kind == 'u' else 'j'}"}):
                        made += 1
            elif layer["kind"] == "curve":
                for i, seg in enumerate(layer["segments"]):
                    if pen.poly(proj(np.asarray(seg, dtype=float)), lname, meta={**base, "scical:role": "curve", "scical:piece": i}, width=lw * 2.2):
                        made += 1
            else:
                for i, p in enumerate(proj(np.asarray(layer["points"], dtype=float))):
                    made += 1 if pen.point(p, lname, meta={**base, "scical:role": "point", "scical:index": i}, color=color) else 0
        else:
            if layer["definition"]["type"] != "surface":
                skipped.append({"id": layer["id"], "label": label, "reason": "A contour map needs an explicit surface z = f(x, y); this layer is not one."})
                continue
            V = np.asarray(layer["vertices"], dtype=float).reshape(-1, 3)
            tris = triangulate(np.asarray(layer["cells"], dtype=np.int64).reshape(-1, 4), V)
            z0, z1 = float(V[:, 2].min()), float(V[:, 2].max())
            _, levels = ticks(z0, z1, 10)
            levels = [v for v in levels if z0 < v < z1]
            span = max(bounds["xmax"] - bounds["xmin"], bounds["ymax"] - bounds["ymin"]) or 1.0
            k = PAGE_WIDTH / span
            lname = pen.layer(f"{n:02d} {label}", color, lw * 1.4)
            for lv in levels:
                lines = contour_polylines(V, tris, lv)
                longest = None
                for ln in lines:
                    pts = (ln[:, :2] - [bounds["xmin"], bounds["ymin"]]) * k
                    if pen.poly(pts, lname, meta={**base, "scical:role": "contour", "scical:level": lv}):
                        made += 1
                        if longest is None or len(pts) > len(longest):
                            longest = pts
                if longest is not None:
                    mid = longest[len(longest) // 2]
                    pen.text(mid, _fmt(lv), th * 0.7, lname, halign="center", meta={**base, "scical:role": "contour label", "scical:level": lv})
            meta_c = {"levels": levels, "mapping": "page = (xy - (xmin, ymin)) * pageWidth / max(xspan, yspan)", "xmin": bounds["xmin"], "ymin": bounds["ymin"], "scale": k}
            doc.set_metadata({"scical:contours_" + "".join(ch if ch.isalnum() else "_" for ch in str(layer["id"])): meta_c})
        if made == 0:
            skipped.append({"id": layer["id"], "label": label, "reason": "Nothing of this layer could be drawn."})
        else:
            legend.append((label, color))
            exported.append({"id": layer["id"], "label": label, "entities": made})
    if not legend:
        raise BadRequest("Nothing could be drawn from this scene in the chosen form.", details={"skipped": skipped})
    pen.layer("title", ink, lw)
    x0, y1 = float(pen.lo[0]), float(pen.hi[1])
    pen.text([x0, y1 + th * 2.2], title, th, "title", valign="middle", meta={"scical:role": "title"})
    y = y1 + th * 0.6
    for label, color in legend:
        pen.line([x0, y], [x0 + th * 1.6, y], "title", color=color, meta={"scical:role": "legend swatch"})
        pen.text([x0 + th * 2.0, y], _name(label, 70), th * 0.8, "title", meta={"scical:role": "legend"})
        y += th * 1.2
    _finish(doc, pen)
    return doc, {"layers": exported, "skipped": skipped, "notes": notes, "entities": pen.count, "mode": mode, "projection": proj.describe() if mode == "wireframe" else None}


# ------------------------------------------------------------------------------------------------------------------ entry points
def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def export_sgeo(link: Any, out_dir: Path, sample: dict[str, Any], *, name: str, unit: str) -> dict[str, Any]:
    sgeo = link.sgeo()
    doc, info = _wrap("SGEO", lambda: build_sgeo(sgeo, sample, name=name, unit=unit), sgeo.SpatialFormatError)
    saved = save_and_verify(doc, sgeo, out_dir, safe_name(f"{name or 'graph'}-3d", "sgeo"), "SGEO")
    return {"ok": True, "format": "sgeo", "unit": unit, **info, **saved, "mime": sgeo.MIMETYPE, "contract": CONTRACT}


def export_sdrw(link: Any, out_dir: Path, build: Callable[[Any], tuple[Any, dict[str, Any]]], *, name: str, suffix: str) -> dict[str, Any]:
    sdrw = link.sdrw()
    doc, info = _wrap("SDRW", lambda: build(sdrw), sdrw.SpatialFormatError)
    saved = save_and_verify(doc, sdrw, out_dir, safe_name(f"{name or 'graph'}-{suffix}", "sdrw"), "SDRW")
    return {"ok": True, "format": "sdrw", **info, **saved, "mime": sdrw.MIMETYPE, "contract": CONTRACT}
