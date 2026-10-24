"""Turns a plot request (a list of layers and a viewport) into drawable data, and answers analysis questions about a layer."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import sympy as sp

from ...errors import BadRequest, EvaluationError, MissingVariableError, SciCalError, UnsupportedOperation
from ..expressions import ParseOptions, parse
from ..expressions import ast as A
from ..expressions.printer import to_text
from ..numerical.context import Context
from . import curves, features, regression
from .curves import View
from .numeric import CONSTS, Compiled, compile_expr

MAX_LAYERS = 24
LAYER_TYPES = ("function", "parametric", "polar", "implicit", "inequality", "sequence", "vectorfield", "scatter", "histogram", "points", "auto")


def _r(v: float) -> float:
    return float(f"{v:.9g}") if math.isfinite(v) else v


def _num(v: Any, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise BadRequest(f"{what} must be a number") from None
    if not math.isfinite(x):
        raise BadRequest(f"{what} must be a finite number")
    return x


def parse_view(d: dict) -> View:
    v = d.get("viewport") or {}
    xmin, xmax = _num(v.get("xmin", -10), "xmin"), _num(v.get("xmax", 10), "xmax")
    ymin, ymax = _num(v.get("ymin", -6), "ymin"), _num(v.get("ymax", 6), "ymax")
    if not (xmin < xmax and ymin < ymax):
        raise BadRequest("The viewport must have xmin < xmax and ymin < ymax")
    if (xmax - xmin) < 1e-12 or (ymax - ymin) < 1e-12 or max(abs(xmin), abs(xmax), abs(ymin), abs(ymax)) > 1e15:
        raise BadRequest("The viewport is too small or too large to draw")
    w = int(_num(d.get("width", 800), "width"))
    h = int(_num(d.get("height", 500), "height"))
    if not (100 <= w <= 4000 and 100 <= h <= 4000):
        raise BadRequest("width and height must be between 100 and 4000 pixels")
    return View(xmin, xmax, ymin, ymax, w, h)


def build_env(ctx: Context, params: dict | None) -> dict[str, float]:
    env: dict[str, float] = {}
    for k, v in ctx.variables.items():
        if isinstance(v, sp.Expr) and not isinstance(v, sp.MatrixBase) and v.is_number and v.is_real:
            env[k] = float(sp.N(v, 20))
    for k, v in (params or {}).items():
        if not isinstance(k, str) or not k.isidentifier():
            raise BadRequest("Slider names must be identifiers")
        env[k] = _num(v, f"The value of {k}")
    return env


class Plotter:
    def __init__(self, ctx: Context, spec: dict) -> None:
        self.ctx = ctx
        self.spec = spec
        self.view = parse_view(spec)
        self.env = build_env(ctx, spec.get("params"))
        self.angle = ctx.settings.angle
        self.k = {"rad": 1.0, "deg": math.pi / 180, "grad": math.pi / 200}[self.angle]
        self.funcs = dict(ctx.functions)
        self.popts = ParseOptions(variables=frozenset(self.env), functions=frozenset(self.funcs), allow_statements=False)

    # ------------------------------------------------------------------------------------------------------------- helpers
    def parse(self, text: Any, what: str = "expression") -> A.Node:
        if not isinstance(text, str) or not text.strip():
            raise BadRequest(f"The {what} is empty")
        return parse(text, self.popts).node

    def comp(self, text_or_node: Any, vars_: tuple[str, ...]) -> Compiled:
        node = text_or_node if isinstance(text_or_node, A.Node) else self.parse(text_or_node)
        return compile_expr(node, vars_, self.env, self.angle, self.funcs)

    def const(self, text: Any, what: str) -> float:
        if isinstance(text, (int, float)):
            return _num(text, what)
        c = self.comp(text, ())
        with np.errstate(all="ignore"):
            v = float(np.asarray(c()))
        if not math.isfinite(v):
            raise BadRequest(f"{what} is not a finite number")
        return v

    def free(self, node: A.Node) -> set[str]:
        names = A.free_names(node)
        return {n for n in names if n not in self.env and n not in CONSTS and n not in ("e",)}

    # ------------------------------------------------------------------------------------------------------------- layers
    def render(self) -> dict:
        layers = self.spec.get("layers")
        if not isinstance(layers, list) or len(layers) > MAX_LAYERS:
            raise BadRequest(f"layers must be a list of at most {MAX_LAYERS} layers")
        out = []
        for i, layer in enumerate(layers):
            lid = str(layer.get("id", f"layer{i}"))
            try:
                if not isinstance(layer, dict):
                    raise BadRequest("Each layer must be an object")
                if layer.get("visible", True) is False:
                    out.append({"id": lid, "ok": True, "type": "hidden"})
                    continue
                res = self.layer(layer)
                res.update(id=lid, ok=True)
                out.append(res)
            except SciCalError as exc:
                out.append({"id": lid, "ok": False, "error": exc.to_dict()})
        v = self.view
        return {"ok": True, "view": {"xmin": v.xmin, "xmax": v.xmax, "ymin": v.ymin, "ymax": v.ymax}, "layers": out,
                "angle": self.angle, "numeric": "float64 (NumPy); results on this page are approximations"}

    def layer(self, layer: dict) -> dict:
        t = layer.get("type", "auto")
        if t not in LAYER_TYPES:
            raise BadRequest(f"Unknown layer type '{t}'")
        if t == "auto":
            t = "implicit_or_function"
        fn = getattr(self, "l_" + t)
        return fn(layer)

    def l_implicit_or_function(self, layer: dict) -> dict:
        node = self.parse(layer.get("expr"), "equation")
        if isinstance(node, A.Rel):
            if node.op != "=":
                return self.inequality_node(node, layer)
            return self.relation_layer(node, layer)
        if isinstance(node, A.Logic):
            return self.inequality_node(node, layer)
        return self.function_layer(node, layer)

    def relation_layer(self, node: A.Rel, layer: dict) -> dict:
        l, r = node.left, node.right
        if isinstance(l, A.Var) and l.name == "y" and "y" not in self.free(r):
            return self.function_layer(r, layer, label=to_text(node))
        if isinstance(r, A.Var) and r.name == "y" and "y" not in self.free(l):
            return self.function_layer(l, layer, label=to_text(node))
        if isinstance(l, A.Var) and l.name == "x" and "x" not in self.free(r) and not (self.free(r) - {"y"}):
            # x = constant is a vertical line; x = g(y) is a curve
            if not self.free(r):
                x0 = float(np.asarray(self.comp(r, ())()))
                return {"type": "vline", "x": _r(x0), "label": to_text(node)}
        F = A.Binary(op="-", left=l, right=r)
        names = self.free(F)
        if names - {"x", "y"}:
            raise MissingVariableError(f"'{sorted(names - {'x', 'y'})[0]}' has no value", hint="Give it a value or add a slider for it.")
        c = self.comp(F, ("x", "y"))
        pls = curves.implicit_segments(c.fn, self.view)
        return {"type": "implicit", "label": to_text(node), "polylines": [[[_r(x), _r(y)] for x, y in pl] for pl in pls]}

    def function_layer(self, node: A.Node, layer: dict, label: str | None = None) -> dict:
        if isinstance(node, A.Var) and node.name in self.funcs and len(self.funcs[node.name].params) == 1:
            node = A.Call(name=node.name, args=[A.Var(name=self.funcs[node.name].params[0])])
            label = label or node.name
        names = self.free(node)
        var = layer.get("var") or "x"
        if var not in names and len(names) == 1 and "x" not in names:
            var = next(iter(names))
        extra = names - {var}
        if extra:
            nm = sorted(extra)[0]
            raise MissingVariableError(f"'{nm}' has no value", hint=f"Give it a value (for example {nm} := 2) or add a slider for it.")
        c = self.comp(node, (var,))
        rng = None
        if layer.get("xmin") is not None or layer.get("xmax") is not None:
            lo = self.const(layer.get("xmin", self.view.xmin), "xmin")
            hi = self.const(layer.get("xmax", self.view.xmax), "xmax")
            if lo >= hi:
                raise BadRequest("The domain of a curve needs xmin < xmax")
            rng = (lo, hi)
        segs, asy = curves.sample_function(c.fn, self.view, rng)
        y0 = None
        with np.errstate(all="ignore"):
            yv = np.asarray(c.fn(np.array([0.0])), dtype=float)
        if yv.size and math.isfinite(float(yv.ravel()[0])):
            y0 = _r(float(yv.ravel()[0]))
        return {"type": "function", "label": label or to_text(node), "var": var, "segments": [[[_r(x), _r(y)] for x, y in s] for s in segs],
                "asymptotes": [_r(a) for a in asy], "yIntercept": y0}

    def l_function(self, layer: dict) -> dict:
        node = self.parse(layer.get("expr"), "function")
        if isinstance(node, A.Rel) and node.op == "=":
            return self.relation_layer(node, layer)
        return self.function_layer(node, layer)

    def l_implicit(self, layer: dict) -> dict:
        node = self.parse(layer.get("expr"), "equation")
        if not (isinstance(node, A.Rel) and node.op == "="):
            raise BadRequest("An implicit curve needs an equation such as x^2 + y^2 = 4")
        return self.relation_layer(node, layer)

    def l_inequality(self, layer: dict) -> dict:
        node = self.parse(layer.get("expr"), "inequality")
        return self.inequality_node(node, layer)

    def inequality_node(self, node: A.Node, layer: dict) -> dict:
        names = self.free(node)
        if names - {"x", "y"}:
            raise MissingVariableError(f"'{sorted(names - {'x', 'y'})[0]}' has no value", hint="Give it a value or add a slider for it.")
        c = self.comp(node, ("x", "y"))
        region = curves.inequality_runs(c.fn, self.view)
        bounds = []
        for rel in [n for n in node.walk() if isinstance(n, A.Rel)]:
            try:
                res = self.relation_layer(A.Rel(op="=", left=rel.left, right=rel.right), {})
            except SciCalError:
                continue
            if res.get("type") == "implicit":
                bounds += res["polylines"]
            elif res.get("type") == "function":
                bounds += res["segments"]
            elif res.get("type") == "vline":
                bounds.append([[res["x"], self.view.ymin], [res["x"], self.view.ymax]])
        return {"type": "inequality", "label": to_text(node), "region": region, "boundary": bounds,
                "strict": any(isinstance(n, A.Rel) and n.op in ("<", ">", "!=") for n in node.walk())}

    def l_parametric(self, layer: dict) -> dict:
        fx, fy = self.comp(layer.get("x"), ("t",)), self.comp(layer.get("y"), ("t",))
        t0, t1 = self.const(layer.get("tmin", 0), "tmin"), self.const(layer.get("tmax", "2*pi" if self.angle == "rad" else 360), "tmax")
        if t0 >= t1:
            raise BadRequest("tmin must be smaller than tmax")
        segs = curves.sample_parametric(fx.fn, fy.fn, t0, t1, self.view)
        return {"type": "parametric", "label": f"({layer.get('x')}, {layer.get('y')})", "segments": [[[_r(x), _r(y)] for x, y in s] for s in segs]}

    def l_polar(self, layer: dict) -> dict:
        fr = self.comp(layer.get("r"), ("t",))
        t0 = self.const(layer.get("tmin", 0), "tmin")
        t1 = self.const(layer.get("tmax", "2*pi" if self.angle == "rad" else 360), "tmax")
        if t0 >= t1:
            raise BadRequest("tmin must be smaller than tmax")
        segs = curves.sample_polar(fr.fn, t0, t1, self.view, self.k)
        return {"type": "polar", "label": f"r = {layer.get('r')}", "segments": [[[_r(x), _r(y)] for x, y in s] for s in segs]}

    def l_sequence(self, layer: dict) -> dict:
        n0, n1 = int(self.const(layer.get("nmin", 1), "nmin")), int(self.const(layer.get("nmax", 20), "nmax"))
        if n1 < n0 or n1 - n0 > 5000:
            raise BadRequest("A sequence needs nmin <= nmax and at most 5000 terms")
        pts = []
        if layer.get("recursive"):
            rec = layer["recursive"]
            first = [self.const(v, "initial term") for v in rec.get("first", [])]
            if not first or len(first) > 2:
                raise BadRequest("A recursive sequence needs one or two initial terms")
            c = self.comp(rec.get("expr"), ("n", "prev", "prev2"))
            vals = list(first)
            for n in range(n0 + len(first), n1 + 1):
                prev = vals[-1]
                prev2 = vals[-2] if len(vals) > 1 else float("nan")
                with np.errstate(all="ignore"):
                    vals.append(float(np.asarray(c.fn(np.float64(n), np.float64(prev), np.float64(prev2)))))
            pts = [(n0 + i, v) for i, v in enumerate(vals)]
        else:
            c = self.comp(layer.get("expr"), ("n",))
            ns = np.arange(n0, n1 + 1, dtype=float)
            with np.errstate(all="ignore"):
                vs = np.broadcast_to(np.asarray(c.fn(ns), dtype=float), ns.shape)
            pts = list(zip(ns.tolist(), vs.tolist()))
        return {"type": "sequence", "label": str(layer.get("expr") or "sequence"), "points": [[_r(a), _r(b)] for a, b in pts if math.isfinite(b)]}

    def l_vectorfield(self, layer: dict) -> dict:
        fx, fy = self.comp(layer.get("fx"), ("x", "y")), self.comp(layer.get("fy"), ("x", "y"))
        return {"type": "vectorfield", "label": f"({layer.get('fx')}, {layer.get('fy')})", "arrows": [[_r(v) for v in a] for a in curves.vector_field(fx.fn, fy.fn, self.view)]}

    def _data(self, values: Any, what: str) -> np.ndarray:
        if not isinstance(values, list) or not values or len(values) > 100_000:
            raise BadRequest(f"{what} must be a non-empty list of numbers (at most 100,000)")
        return np.array([self.const(v, what) for v in values], dtype=float)

    def l_points(self, layer: dict) -> dict:
        return self.l_scatter(layer)

    def l_scatter(self, layer: dict) -> dict:
        x, y = self._data(layer.get("x"), "x values"), self._data(layer.get("y"), "y values")
        if len(x) != len(y):
            raise BadRequest(f"x and y need the same number of values ({len(x)} and {len(y)})")
        out: dict[str, Any] = {"type": "scatter", "label": layer.get("label") or "data", "points": [[_r(a), _r(b)] for a, b in zip(x, y)]}
        model = layer.get("fit")
        if model:
            res = regression.fit(str(model), x, y)
            fx = np.linspace(self.view.xmin, self.view.xmax, 400)
            with np.errstate(all="ignore"):
                fy = np.asarray(res["fn"](fx), dtype=float)
            segs, _ = curves.sample_function(res["fn"], self.view)
            out["fit"] = {"model": res["model"], "equation": res["equation"], "params": {k: _r(v) for k, v in res["params"].items()},
                          "r2": _r(res["r2"]), "rmse": _r(res["rmse"]), "n": res["n"], "segments": [[[_r(a), _r(b)] for a, b in s] for s in segs],
                          "method": "least squares" + ("" if model in ("linear", "quadratic", "cubic", "quartic") else " (Levenberg–Marquardt)")}
        return out

    def l_histogram(self, layer: dict) -> dict:
        v = self._data(layer.get("values"), "values")
        bins = layer.get("bins")
        nb = int(self.const(bins, "bins")) if bins else int(math.ceil(math.log2(len(v)) + 1))
        if not (1 <= nb <= 500):
            raise BadRequest("bins must be between 1 and 500")
        counts, edges = np.histogram(v, bins=nb)
        width = np.diff(edges)
        return {"type": "histogram", "label": "histogram", "bars": [{"x0": _r(edges[i]), "x1": _r(edges[i + 1]), "count": int(counts[i]),
                                                                    "density": _r(counts[i] / (len(v) * width[i]) if width[i] else 0.0)} for i in range(len(counts))],
                "n": int(len(v))}


def render(ctx: Context, spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise BadRequest("The plot request must be an object")
    return Plotter(ctx, spec).render()


# ------------------------------------------------------------------------------------------------------------------ analysis
def _layer_fn(p: Plotter, layer: dict) -> tuple[Compiled, str, A.Node]:
    t = layer.get("type", "function")
    if t not in ("function", "auto"):
        raise BadRequest("Analysis works on function layers")
    node = p.parse(layer.get("expr"), "function")
    if isinstance(node, A.Rel) and node.op == "=":
        if isinstance(node.left, A.Var) and node.left.name == "y":
            node = node.right
        else:
            raise BadRequest("Analysis needs a function y = f(x)")
    if isinstance(node, A.Var) and node.name in p.funcs and len(p.funcs[node.name].params) == 1:
        node = A.Call(name=node.name, args=[A.Var(name=p.funcs[node.name].params[0])])
    names = p.free(node)
    var = layer.get("var") or "x"
    if var not in names and len(names) == 1:
        var = next(iter(names))
    if names - {var}:
        raise MissingVariableError(f"'{sorted(names - {var})[0]}' has no value")
    return p.comp(node, (var,)), var, node


def _snap(x: float, scale: float) -> float:
    """Numerical refinement of extrema is good to about 1e-8; show exact-looking zeros as zero."""
    return 0.0 if abs(x) < 1e-7 * max(1.0, scale) else x


def analyze(ctx: Context, spec: dict) -> dict:
    """spec: {viewport, params, kind, layer, [layer2], [a, b], [x]} -> {points: [...]}"""
    p = Plotter(ctx, spec)
    kind = spec.get("kind")
    layers = {str(l.get("id")): l for l in spec.get("layers", []) if isinstance(l, dict)}
    def get(key: str) -> dict:
        lid = str(spec.get(key))
        if lid not in layers:
            raise BadRequest(f"Unknown layer '{lid}'")
        return layers[lid]
    v = p.view
    lo = p.const(spec.get("a", v.xmin), "a")
    hi = p.const(spec.get("b", v.xmax), "b")
    if lo >= hi and kind in ("roots", "extrema", "intersection", "integral"):
        raise BadRequest("The interval needs a < b")
    f, var, node = _layer_fn(p, get("layer"))
    res: dict[str, Any] = {"ok": True, "kind": kind, "approximate": True, "method": "float64 sampling with bisection / golden-section refinement"}
    if kind == "roots":
        res["points"] = [{"x": _r(r), "y": 0.0} for r in features.find_roots(f.fn, lo, hi)]
    elif kind == "extrema":
        sc = max(abs(lo), abs(hi))
        res["points"] = [{"x": _r(_snap(e["x"], sc)), "y": _r(e["y"]), "kind": e["kind"]} for e in features.find_extrema(f.fn, lo, hi)]
    elif kind == "intersection":
        g, _, _ = _layer_fn(p, get("layer2"))
        res["points"] = [{"x": _r(q["x"]), "y": _r(q["y"])} for q in features.intersections(f.fn, g.fn, lo, hi)]
    elif kind == "integral":
        try:
            val, err = features.integrate(f.fn, lo, hi)
        except ValueError as exc:
            raise EvaluationError(str(exc), hint="The function is undefined somewhere in the interval; choose an interval inside its domain.") from None
        res.update(value=_r(val), error=float(f"{err:.2g}"), a=_r(lo), b=_r(hi), method="adaptive Gauss–Kronrod (7,15)")
    elif kind == "value":
        x0 = p.const(spec.get("x"), "x")
        with np.errstate(all="ignore"):
            y0 = float(np.asarray(f.fn(np.array([x0])), dtype=float).ravel()[0])
        res.update(x=_r(x0), y=_r(y0) if math.isfinite(y0) else None)
    elif kind == "tangent":
        res.update(_tangent(p, ctx, node, var, spec))
    else:
        raise BadRequest("Unknown analysis kind")
    return res


def _tangent(p: Plotter, ctx: Context, node: A.Node, var: str, spec: dict) -> dict:
    """The tangent line at x0 from the exact derivative (so slopes such as 1/2 or sqrt(3) stay exact)."""
    from ..numerical.convert import to_ast
    from ..numerical.evaluator import Evaluator
    from ..expressions.printer import to_latex
    x0 = p.parse(str(spec.get("x")), "x") if isinstance(spec.get("x"), str) else A.Num(text=repr(float(spec.get("x"))).replace("e+", "e"))
    ev = Evaluator(Context(settings=ctx.settings, variables=dict(ctx.variables), functions=dict(ctx.functions)))
    x = sp.Symbol(var)
    ev.shadow.append({var: x})
    expr = ev.ev(node)
    ev.shadow.pop()
    a = ev.ev(x0)
    if not (isinstance(expr, sp.Expr)):
        raise EvaluationError("The tangent needs a number-valued function")
    d = sp.diff(expr, x)
    slope = sp.nsimplify(d.subs(x, a)) if False else d.subs(x, a)
    y0 = expr.subs(x, a)
    if not (slope.is_number and y0.is_number) or slope.has(sp.zoo, sp.nan, sp.oo, -sp.oo) or y0.has(sp.zoo, sp.nan, sp.oo, -sp.oo):
        raise EvaluationError("The function is not differentiable at this point")
    intercept = sp.simplify(y0 - slope * a)
    line = slope * x + intercept
    return {"x": float(sp.N(a)), "y": float(sp.N(y0)), "slope": float(sp.N(slope)), "intercept": float(sp.N(intercept)),
            "exact": {"slope": to_text(to_ast(slope)), "intercept": to_text(to_ast(intercept)), "equation": "y = " + to_text(to_ast(sp.expand(line))),
                      "latex": "y = " + to_latex(to_ast(sp.expand(line)))}, "approximate": False, "method": "exact derivative"}
