"""STEM Lab: calculations SciCal's own engine does not do, carried out by SLAI's STEM agent.

Every operation here sends structured requests to the STEM agent (``StemBridge.call``): ODE integrators, root finders, quadrature rules,
interpolation, linear-algebra diagnostics, seeded Monte-Carlo and bootstrap. The expressions the person types are read by SciCal's parser
(never by ``eval``), printed in the small grammar STEM's parametric evaluator accepts, and every value of the user's function is then
computed by the agent. Where SciCal has an exact answer (an integral, a linear system) it is shown next to the agent's floating-point one,
so the *error* of each numerical method is visible.

Runs in the server process, bounded by a time limit and an evaluation budget, because the agent's callbacks cannot be sent to a worker.
Results use the same vocabulary as the other workspaces (numbers, rows, ``plot`` charts, steps, warnings), so one renderer shows them.
"""
from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ..core.numerical.context import Settings
from ..domains import common as C
from ..errors import BadRequest, SciCalError
from .stem_bridge import StemBridge, StemFailed, StemUnavailable
from .stem_checks import P, Translator, Unsupported, matrix_of, nums_of, pname, to_stem

MAX_EVALS = 60_000
TIME_LIMIT_S = 25.0
MAX_POINTS = 400


class Budget:
    """A cap on how many times a STEM request may be made for one operation, and how long it may take."""

    def __init__(self, max_calls: int | None = None, seconds: float | None = None) -> None:
        max_calls = MAX_EVALS if max_calls is None else max_calls
        seconds = TIME_LIMIT_S if seconds is None else seconds
        self.max_calls = max_calls
        self.calls = 0
        self.deadline = time.monotonic() + seconds
        self.seconds = seconds

    def tick(self, n: int = 1) -> None:
        self.calls += n
        if self.calls > self.max_calls:
            raise StemFailed(f"Stopped after {self.max_calls:,} evaluations of your function. Use a larger step, fewer samples or a looser tolerance.")
        if time.monotonic() > self.deadline:
            raise StemFailed(f"Stopped after {self.seconds:.0f} seconds. Use a larger step, fewer samples or a looser tolerance.")


class Lab:
    """What an operation may use."""

    def __init__(self, stem: StemBridge, settings: Settings, evaluate: Callable[[str, list[str], dict[str, Any]], dict[str, Any]] | None = None) -> None:
        self.stem = stem
        self.s = settings
        self.out = C.Out(settings)
        self.budget = Budget()
        self.evaluate = evaluate

    @property
    def angle(self) -> str:
        return self.s.angle

    # ------------------------------------------------------------------ inputs
    def real(self, params: Mapping[str, Any], key: str, default: Any = None, **kw: Any) -> float:
        v = C.number(dict(params), key, default=default, **kw)
        return float(v)

    def reals(self, params: Mapping[str, Any], key: str, minimum: int = 1, maximum: int = 2000) -> list[float]:
        raw = params.get(key)
        if isinstance(raw, str):
            raw = [t for t in re.split(r"[\s,;]+", raw.strip()) if t]
        if not isinstance(raw, list) or len(raw) < minimum:
            raise C.field_error(key, f"Give at least {minimum} number{'s' if minimum != 1 else ''}")
        if len(raw) > maximum:
            raise C.field_error(key, f"At most {maximum} values")
        return [float(C.number({"v": v}, "v")) for v in raw]

    def table(self, params: Mapping[str, Any], key: str, what: str, required: bool = True) -> dict[str, Any]:
        raw = params.get(key)
        if raw in (None, "", {}, []):
            if required:
                raise C.field_error(key, f"Give at least one {what}")
            return {}
        if isinstance(raw, list):                                                      # a table sent as rows of objects
            out = {}
            for r in raw:
                if isinstance(r, Mapping) and r.get("name") is not None:
                    out[str(r["name"])] = r
            raw = out
        if not isinstance(raw, Mapping) or len(raw) > 30:
            raise C.field_error(key, f"'{key}' must be a short list of names and values")
        return dict(raw)

    def value_of(self, spec: Any, field: str) -> float:
        v = spec.get("value") if isinstance(spec, Mapping) else spec
        return float(C.number({"v": v}, "v"))

    # ------------------------------------------------------------------ expressions
    def expression(self, text: Any, field: str, variables: Sequence[str] = ()) -> tuple[str, set[str]]:
        if not isinstance(text, str) or not text.strip():
            raise C.field_error(field, f"'{field}' is required")
        if len(text) > 500:
            raise C.field_error(field, "The expression is too long")
        try:
            return to_stem(text.replace("**", "^"), self.angle, frozenset(variables))
        except Unsupported as exc:
            raise C.field_error(field, f"STEM cannot take this expression: {exc}.") from exc

    def function(self, text: Any, field: str, variable: str, constants: Mapping[str, float] | None = None) -> Callable[..., float]:
        """A Python callable of one variable, whose every value is computed by the agent's parametric evaluator."""
        expr, names = self.expression(text, field, [variable])
        consts = dict(constants or {})
        missing = sorted(names - {variable} - set(consts))
        if missing:
            raise C.field_error(field, f"'{missing[0]}' has no value", hint="Add it under Constants, or use a number.")
        stem, budget = self.stem, self.budget

        def f(x: float) -> float:
            budget.tick()
            return stem.number("parametric", "evaluate_expression", expr, P({**consts, variable: float(x)}))
        return f

    def one_variable(self, text: Any, field: str, constants: Mapping[str, float], wanted: str | None) -> str:
        """The unknown of ``text``: the name the person gave, else the only name that is not a constant."""
        if wanted:
            return wanted
        _, names = self.expression(text, field)
        free = sorted(names - set(constants))
        if len(free) != 1:
            raise C.field_error(field, "Say which variable the expression is a function of" if free else "The expression has no variable", hint="Write it as a function of one letter, for example x.")
        return free[0]

    def constants(self, params: Mapping[str, Any], key: str = "constants") -> dict[str, float]:
        out: dict[str, float] = {}
        for name, spec in self.table(params, key, "constant", required=False).items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,23}", name) or name in ("pi", "e"):
                raise C.field_error(key, f"'{name}' is not a usable name for a constant")
            out[name] = self.value_of(spec, key)
        return out

    # ------------------------------------------------------------------ outputs
    def num(self, x: float, unit: str | None = None) -> dict[str, Any]:
        return self.out.num(x, unit)

    def reference_scical(self, text: str) -> float | None:
        """SciCal's own value of ``text`` (an exact calculation, shown to 17 digits), or None when it cannot give one."""
        if self.evaluate is None:
            return None
        from .stem_checks import num_of
        r = self.evaluate(text, [], {**self.s.to_dict(), "digits": 17, "notation": "auto", "decimals": None, "result": "auto", "thousands": False})
        return num_of(r.get("value")) if r.get("ok") else None


def _thin(xs: Sequence[float], limit: int = MAX_POINTS) -> list[int]:
    n = len(xs)
    if n <= limit:
        return list(range(n))
    step = (n - 1) / (limit - 1)
    return sorted({round(i * step) for i in range(limit)})


def _g(x: float) -> str:
    return f"{x:.10g}"


def _plot(title: str, x_label: str, y_label: str, series: list[dict[str, Any]], *, markers: list[dict[str, Any]] | None = None, description: str | None = None, zero: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"title": title, "xLabel": x_label, "yLabel": y_label, "series": series}
    if markers:
        out["markers"] = markers
    if description:
        out["description"] = description
    if zero:
        out["zeroLine"] = True
    return out


# ------------------------------------------------------------------------------------------------------------------ ODE
_EQ_DD = re.compile(r"^\s*d\s*([A-Za-z_]\w*)\s*/\s*d\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
_EQ_PRIME = re.compile(r"^\s*([A-Za-z_]\w*)\s*['′]\s*(?:\(\s*[A-Za-z_]\w*\s*\))?\s*=\s*(.+?)\s*$")


def _parse_equations(text: Any, tvar: str) -> list[tuple[str, str]]:
    lines = text if isinstance(text, list) else str(text or "").splitlines()
    eqs: list[tuple[str, str]] = []
    for raw in lines:
        line = str(raw).strip()
        if not line:
            continue
        m = _EQ_DD.match(line)
        if m:
            if m.group(2) != tvar:
                raise C.field_error("equations", f"'{line}' differentiates by {m.group(2)}, but the independent variable is {tvar}")
            eqs.append((m.group(1), m.group(3)))
            continue
        m = _EQ_PRIME.match(line)
        if m:
            eqs.append((m.group(1), m.group(2)))
            continue
        raise C.field_error("equations", f"Cannot read '{line}'", hint="Write one equation per line, such as  x' = v  or  dv/dt = -k*x")
    if not eqs:
        raise C.field_error("equations", "Give at least one equation")
    if len(eqs) > 8:
        raise C.field_error("equations", "At most 8 equations")
    names = [n for n, _ in eqs]
    if len(set(names)) != len(names):
        raise C.field_error("equations", "Each variable can have only one equation")
    return eqs


def ode(lab: Lab, params: Mapping[str, Any]) -> dict[str, Any]:
    tvar = str(params.get("variable") or "t").strip() or "t"
    if not re.fullmatch(r"[A-Za-z_]\w{0,15}", tvar):
        raise C.field_error("variable", "The independent variable must be a name such as t")
    eqs = _parse_equations(params.get("equations"), tvar)
    names = [n for n, _ in eqs]
    consts = lab.constants(params, "constants")
    init = lab.table(params, "initial", "initial value")
    y0 = []
    for n in names:
        if n not in init:
            raise C.field_error("initial", f"'{n}' needs an initial value")
        y0.append(lab.value_of(init[n], "initial"))
    t0, t1 = lab.real(params, "t0", 0), lab.real(params, "t1")
    if not t1 > t0:
        raise C.field_error("t1", "The end must be later than the start")
    method = str(params.get("method") or "rk4")
    if method not in ("rk4", "rk45", "euler"):
        raise C.field_error("method", "Method must be rk4, rk45 or euler")
    h = lab.real(params, "step", (t1 - t0) / 200, positive=True)
    rtol = lab.real(params, "rtol", 1e-6, positive=True)
    steps_needed = math.ceil((t1 - t0) / h)
    if method != "rk45" and steps_needed > 5000:
        raise C.field_error("step", f"That is {steps_needed:,} steps. Use a step of at least {(t1 - t0) / 5000:.3g}.")
    compiled: list[str] = []
    for n, rhs in eqs:
        expr, used = lab.expression(rhs, "equations", [tvar, *names])
        unknown = sorted(used - set(names) - {tvar} - set(consts))
        if unknown:
            raise C.field_error("equations", f"'{unknown[0]}' is not a variable of the system and has no value", hint="Give it under Constants.")
        compiled.append(expr)
    stem, budget = lab.stem, lab.budget

    def rhs(t: float, y: Sequence[float]) -> list[float]:
        env = P({**consts, tvar: float(t), **dict(zip(names, (float(v) for v in y)))})
        budget.tick(len(compiled))
        return [stem.number("parametric", "evaluate_expression", e, env) for e in compiled]

    def run(m: str, **kw: Any) -> Mapping[str, Any]:
        before = budget.calls
        if m == "rk45":
            r = stem.call_raw("numerical_methods", "rk45_adaptive", rhs, y0, t0, t1, rtol=kw.get("rtol", rtol), atol=kw.get("atol", 1e-9))
        else:
            r = stem.call_raw("numerical_methods", m, rhs, y0, t0, t1, h)
        r = dict(r)
        r["evaluations"] = budget.calls - before
        return r

    main = run(method)
    ts, ys = list(main["t"]), list(main["y"])
    o = lab.out
    o.step("Equations", detail="; ".join(f"d{n}/d{tvar} = {r}" for n, r in eqs))
    o.step("Method", detail={"rk4": "Classical fourth-order Runge–Kutta, fixed step", "rk45": "Dormand–Prince 5(4), adaptive step", "euler": "Forward Euler, fixed step"}[method]
           + (f" with relative tolerance {rtol:g}" if method == "rk45" else f", step {h:g}"))
    idx = _thin(ts)
    series = [{"label": n, "points": [[ts[i], ys[i][k]] for i in idx], "kind": "line"} for k, n in enumerate(names)]
    result: dict[str, Any] = {"method": {"rk4": "RK4", "rk45": "RK45 (adaptive)", "euler": "Euler"}[method], "steps": int(main.get("steps", len(ts) - 1)),
                              "evaluations": int(main["evaluations"]), "finalState": {n: lab.num(ys[-1][k]) for k, n in enumerate(names)}}
    if main.get("rejected_steps"):
        result["rejectedSteps"] = int(main["rejected_steps"])
    if len(names) == 2:
        result["plot2"] = _plot("Phase portrait", names[0], names[1], [{"label": "path", "points": [[ys[i][0], ys[i][1]] for i in idx], "kind": "line"}],
                                markers=[{"x": ys[0][0], "y": ys[0][1], "label": "start"}, {"x": ys[-1][0], "y": ys[-1][1], "label": "end"}], description=f"{names[1]} against {names[0]}.")
    result["plot"] = _plot("Solution", tvar, "value", series, description="Each variable against " + tvar + ".")
    want = _thin(ts, 12)
    result["samples"] = [{tvar: float(ts[i]), **{n: float(ys[i][k]) for k, n in enumerate(names)}} for i in want]
    if params.get("compare"):
        ref = None
        try:
            ref = run("rk45", rtol=1e-10, atol=1e-12)
        except StemFailed as exc:
            lab.out.warn("The reference run could not finish: " + exc.message)
        rows = []
        for m in ("euler", "rk4", "rk45"):
            try:
                r = main if m == method else run(m)
            except StemFailed as exc:
                rows.append({"method": m, "steps": None, "evaluations": None, "note": exc.message})
                continue
            row = {"method": m, "steps": int(r.get("steps", 0)), "evaluations": int(r["evaluations"])}
            if ref is not None:
                end, rend = list(r["y"][-1]), list(ref["y"][-1])
                err = max(abs(a - b) for a, b in zip(end, rend))
                row["error at the end"] = float(f"{err:.3g}")
            rows.append(row)
        result["methods"] = rows
        o.step("Comparison", detail="Each method run on the same problem; the error is measured against RK45 at relative tolerance 1e-10.")
        if ref is None:
            o.warn("No reference solution, so the methods are listed without errors.")
    if method == "euler":
        o.warn("Euler's method is first order: halve the step and the error halves. RK4 is usually far more accurate for the same effort.")
    return o.done(**result)


# ------------------------------------------------------------------------------------------------------------------ Monte Carlo
DISTRIBUTIONS = ("normal", "rectangular", "triangular", "u_shaped")


def monte_carlo(lab: Lab, params: Mapping[str, Any]) -> dict[str, Any]:
    vars_ = lab.table(params, "variables", "variable")
    order = list(vars_)
    expr, used = lab.expression(params.get("expression"), "expression", order)
    unknown = sorted(used - set(order))
    if unknown:
        raise C.field_error("expression", f"'{unknown[0]}' has no value or uncertainty", hint="Add it to the variables table.")
    means, us, dists = [], [], []
    for n in order:
        spec = vars_[n]
        if not isinstance(spec, Mapping):
            raise C.field_error("variables", f"'{n}' needs a value and an uncertainty")
        means.append(lab.value_of(spec.get("value"), "variables"))
        u = float(C.number({"u": spec.get("uncertainty")}, "u", nonneg=True))
        us.append(u)
        d = str(spec.get("distribution") or "normal").strip().lower().replace("-", "_")
        if d not in DISTRIBUTIONS:
            raise C.field_error("variables", f"'{d}' is not a distribution STEM offers", hint="Use normal, rectangular, triangular or u_shaped.")
        dists.append(d)
    samples = int(lab.real(params, "samples", 10000, integer=True, lo=100, hi=20000))
    seed = int(lab.real(params, "seed", 1, integer=True, lo=0, hi=2 ** 31 - 1))
    k = lab.real(params, "coverageFactor", 2, positive=True)
    stem, budget = lab.stem, lab.budget
    budget.max_calls = max(budget.max_calls, samples + 200)

    def model(*vals: float) -> float:
        budget.tick()
        return stem.number("parametric", "evaluate_expression", expr, P(dict(zip(order, (float(v) for v in vals)))))

    centre = model(*means)
    sens = stem.call("uncertainty", "sensitivity_coefficients", model, means)
    first = stem.number("uncertainty", "jacobian_propagation", [float(s) for s in sens], [u * (1.0 if d == "normal" else 1.0) for u, d in zip(us, dists)])
    mc = stem.call("uncertainty", "monte_carlo_propagation", model, means, us, distributions=dists, samples=samples, _seed=seed)
    su = float(mc["standard_uncertainty"])
    lo, hi = mc["coverage_interval_95"]
    o = lab.out
    o.step("Method", detail=f"{samples:,} draws from the stated distributions with seed {seed}; each draw's value of the formula is computed by STEM. The seed makes the run repeatable.")
    res: dict[str, Any] = {"valueAtMeans": lab.num(centre), "firstOrderUncertainty": lab.num(first), "monteCarloMean": lab.num(float(mc["mean"])), "monteCarloUncertainty": lab.num(su),
                           "interval95": [lab.num(float(lo)), lab.num(float(hi))],
                           "expandedUncertaintyFirstOrder": lab.num(first * k), "seed": seed, "samples": samples}
    res["sensitivities"] = [{"variable": n, "sensitivity": float(f"{float(s):.8g}"), "standardUncertainty": float(f"{u:.8g}"),
                             "contribution": float(f"{abs(float(s)) * u:.6g}"), "distribution": d} for n, s, u, d in zip(order, sens, us, dists)]
    bias = abs(float(mc["mean"]) - centre)
    if first > 0 and abs(su - first) / first > 0.05:
        o.warn(f"The Monte-Carlo uncertainty ({su:.4g}) differs from the first-order one ({first:.4g}) by more than 5 %: the formula is not linear over this uncertainty, so prefer the Monte-Carlo figure.")
    if first > 0 and bias > 0.1 * first:
        o.warn(f"The mean of the draws is {bias:.3g} away from the value at the means: the formula is curved here, so the value at the means is biased.")
    return o.done(**res)


# ------------------------------------------------------------------------------------------------------------------ quadrature
def quadrature(lab: Lab, params: Mapping[str, Any]) -> dict[str, Any]:
    consts = lab.constants(params)
    text = params.get("expression")
    var = lab.one_variable(text, "expression", consts, (str(params.get("variable") or "").strip() or None))
    f = lab.function(text, "expression", var, consts)
    a, b = lab.real(params, "a"), lab.real(params, "b")
    if not a < b:
        raise C.field_error("b", "The upper limit must be larger than the lower limit")
    n = int(lab.real(params, "n", 100, integer=True, lo=2, hi=5000))
    gl = int(lab.real(params, "points", 8, integer=True, lo=1, hi=64))
    seed = int(lab.real(params, "seed", 1, integer=True, lo=0, hi=2 ** 31 - 1))
    stem, budget = lab.stem, lab.budget
    rows: list[dict[str, Any]] = []
    vals: dict[str, float] = {}

    def run(name: str, op: tuple[str, str], *args: Any, **kw: Any) -> None:
        before = budget.calls
        try:
            v = stem.call(op[0], op[1], f, a, b, *args, **kw)
            v = float(v["estimate"]) if isinstance(v, Mapping) else float(v)
        except StemFailed as exc:
            rows.append({"method": name, "value": None, "evaluations": budget.calls - before, "note": exc.message})
            return
        vals[name] = v
        rows.append({"method": name, "value": v, "evaluations": budget.calls - before})

    run(f"Trapezoid ({n} intervals)", ("numerical_methods", "trapezoidal"), n)
    run(f"Simpson ({n} intervals)", ("numerical_methods", "simpson"), n)
    run("Romberg", ("numerical_methods", "romberg"))
    run(f"Gauss–Legendre ({gl} points)", ("numerical_methods", "gauss_legendre"), gl)
    run("Adaptive Simpson (tol 1e-10)", ("numerical_methods", "adaptive_quadrature"), tol=1e-10)
    mc_n = min(4000, max(500, n * 20))
    run(f"Monte Carlo ({mc_n} draws, seed {seed})", ("statistics", "monte_carlo_integrate"), mc_n, _seed=seed)
    # reference: SciCal's exact integral when it has a numeric one, otherwise the adaptive rule
    node_text = f"integral({str(text).strip()}, {var}, {_lit(a)}, {_lit(b)})"
    exact = lab.reference_scical(node_text) if not consts else None
    ref_name = "SciCal's exact integral"
    ref = exact
    if ref is None:
        ref = vals.get("Adaptive Simpson (tol 1e-10)")
        ref_name = "adaptive Simpson (no exact integral available)"
    o = lab.out
    for r in rows:
        if r.get("value") is not None and ref is not None:
            r["error"] = float(f"{abs(r['value'] - ref):.3g}")
            r["value"] = float(f"{r['value']:.12g}")
    xs = [a + (b - a) * i / 120 for i in range(121)]
    try:
        curve = [[x, f(x)] for x in xs]
    except StemFailed:
        curve = []
    res: dict[str, Any] = {"integral": f"from {_g(a)} to {_g(b)} of {str(text).strip()} d{var}", "methods": rows}
    if ref is not None:
        res["reference"] = lab.num(ref)
        res["referenceIs"] = ref_name
    if curve:
        res["plot"] = _plot("Integrand", var, "f", [{"label": "f", "points": curve, "kind": "line"}], zero=True, description=f"The function between {_g(a)} and {_g(b)}.")
    o.step("Reference", detail=f"Errors are measured against {ref_name}.")
    o.step("Evaluations", detail="Every value of your function is computed by STEM; the evaluation count shows what each rule costs.")
    return o.done(**res)


def _lit(x: float) -> str:
    return repr(float(x)) if not float(x).is_integer() else str(int(x))


# ------------------------------------------------------------------------------------------------------------------ roots
def roots(lab: Lab, params: Mapping[str, Any]) -> dict[str, Any]:
    consts = lab.constants(params)
    text = params.get("expression")
    if isinstance(text, str) and "=" in text and not re.search(r"[<>!]=|==", text):
        left, right = text.split("=", 1)
        text = f"({left.strip()}) - ({right.strip()})"
    var = lab.one_variable(text, "expression", consts, (str(params.get("variable") or "").strip() or None))
    expr, names = lab.expression(text, "expression", [var])
    f = lab.function(text, "expression", var, consts)
    a, b = lab.real(params, "a"), lab.real(params, "b")
    if not a < b:
        raise C.field_error("b", "The right end of the bracket must be larger than the left")
    x0 = lab.real(params, "x0", (a + b) / 2)
    tol = lab.real(params, "tol", 1e-12, positive=True)
    stem, budget = lab.stem, lab.budget

    def df(x: float) -> float:
        budget.tick()
        d = stem.call("parametric", "derivative", expr, P({**consts, var: float(x)}), pname(var))
        v = d.get("value") if isinstance(d, Mapping) else d
        return float(v)

    rows: list[dict[str, Any]] = []
    found: list[tuple[str, float]] = []

    def go(name: str, op: str, *args: Any, **kw: Any) -> None:
        before = budget.calls
        try:
            r = stem.call("numerical_methods", op, *args, tol=tol, **kw)
        except StemFailed as exc:
            rows.append({"method": name, "root": None, "iterations": None, "residual": None, "status": "failed", "note": exc.message})
            return
        sol = r.get("solution")
        rows.append({"method": name, "root": float(f"{sol:.15g}") if isinstance(sol, (int, float)) else None, "iterations": r.get("iterations"),
                     "residual": float(f"{r['residual']:.3g}") if isinstance(r.get("residual"), (int, float)) else None, "status": r.get("status"),
                     "evaluations": budget.calls - before})
        if r.get("converged") and isinstance(sol, (int, float)):
            found.append((name, float(sol)))

    go("Bisection", "bisection", f, a, b)
    go("Secant", "secant", f, a, b)
    go("Newton–Raphson", "newton_raphson", f, df, x0)
    o = lab.out
    res: dict[str, Any] = {"methods": rows}
    if found:
        best = found[0][1]
        res["root"] = lab.num(best)
        spread = max(abs(r - best) for _, r in found)
        res["agreement"] = lab.num(spread)
        if spread > 1e-8 * max(1.0, abs(best)):
            o.warn("The methods found different roots: the function has more than one root, or one method wandered off. Check the plot and narrow the bracket.")
    else:
        o.warn("No method converged. Bisection needs the function to change sign between the ends of the bracket.")
    xs = [a + (b - a) * i / 160 for i in range(161)]
    try:
        curve = [[x, f(x)] for x in xs]
        res["plot"] = _plot("Function and roots", var, "f", [{"label": "f", "points": curve, "kind": "line"}],
                            markers=[{"x": r, "y": 0.0, "label": n} for n, r in found[:3]], zero=True, description="The function on the bracket, with the roots each method found.")
    except StemFailed:
        pass
    o.step("Methods", detail="Bisection halves a bracket that changes sign (slow, certain); the secant method uses two points (fast, no derivative); Newton–Raphson uses the derivative, which STEM estimates numerically here.")
    return o.done(**res)


# ------------------------------------------------------------------------------------------------------------------ linear systems
def _matrix(params: Mapping[str, Any]) -> list[list[float]]:
    raw = params.get("matrix")
    if isinstance(raw, str):
        raw = raw.strip().splitlines()
    if isinstance(raw, list):
        raw = [[t for t in re.split(r"[\s,;]+", r.strip()) if t] if isinstance(r, str) else r for r in raw if not (isinstance(r, str) and not r.strip())]
    if not isinstance(raw, list) or not raw:
        raise C.field_error("matrix", "Give the matrix, one row per line")
    if len(raw) > 12:
        raise C.field_error("matrix", "At most 12 rows")
    rows = [[float(C.number({"v": v}, "v")) for v in r] for r in raw]
    if any(len(r) != len(rows) for r in rows):
        raise C.field_error("matrix", "The matrix must be square (as many columns as rows)")
    return rows


def linear(lab: Lab, params: Mapping[str, Any]) -> dict[str, Any]:
    A = _matrix(params)
    n = len(A)
    b = lab.reals(params, "rhs", n, 12)
    if len(b) != n:
        raise C.field_error("rhs", f"The right-hand side needs {n} numbers")
    stem = lab.stem
    o = lab.out
    cond = stem.call("numerical_methods", "condition_numbers", A)
    x = [float(v) for v in stem.call("numerical_methods", "solve_linear_system", A, b)]
    resid = stem.call("numerical_methods", "residuals", A, x, b)
    res: dict[str, Any] = {"solution": {f"x{i + 1}": lab.num(v) for i, v in enumerate(x)}, "conditionNumber2": lab.num(cond["2_norm"]), "conditionNumber1": lab.num(cond["1_norm"]),
                           "conditionNumberInf": lab.num(cond["inf_norm"]), "residualMax": lab.num(resid["linf"]), "residualL2": lab.num(resid["l2"])}
    try:
        res["backwardError"] = lab.num(stem.number("numerical_methods", "backward_error", A, x, b))
    except StemFailed:
        pass
    c2 = float(cond["2_norm"])
    if math.isfinite(c2) and c2 > 1:
        lost = math.log10(c2)
        res["digitsLost"] = lab.num(round(lost, 2))
        if lost > 8:
            o.warn(f"This matrix is ill-conditioned (condition number {c2:.3g}): about {lost:.0f} of the 16 digits of a double are lost, so the solution may be good to only ~{max(0, 16 - lost):.0f} digits even though the residual is tiny.")
    if n <= 6:
        try:
            inv = stem.call("numerical_methods", "matrix_inverse", A)
            res["inverse"] = [[float(f"{v:.10g}") for v in r] for r in inv]
        except StemFailed as exc:
            o.warn(exc.message)
    # SciCal's exact rational solution: the forward error of the floating-point one
    if lab.evaluate is not None and n <= 8:
        mat = "[" + ",".join("[" + ",".join(_lit(v) for v in r) + "]" for r in A) + "]"
        vec = "[" + ",".join(_lit(v) for v in b) + "]"
        r = lab.evaluate(f"linsolve({mat}, {vec})", [], {**lab.s.to_dict(), "digits": 17, "result": "auto", "notation": "auto", "decimals": None, "thousands": False})
        exact = nums_of((r.get("value") or {}).get("items")) if r.get("ok") and isinstance(r.get("value"), Mapping) else None
        if exact and len(exact) == n:
            err = max(abs(u - v) for u, v in zip(exact, x))
            res["exactSolution"] = {f"x{i + 1}": lab.num(v) for i, v in enumerate(exact)}
            res["forwardErrorVsExact"] = lab.num(err)
            o.step("Exact solution", detail="SciCal solved the same system in exact rational arithmetic; the difference is the rounding error of the floating-point solve.")
    o.step("Solve", detail="LU decomposition with partial pivoting (STEM numerical_methods.solve_linear_system).")
    o.step("Diagnostics", detail="Condition numbers measure how much the solution can change for a small change in the data; the residual only says whether A·x equals b.")
    return o.done(**res)


# ------------------------------------------------------------------------------------------------------------------ interpolation
def interpolate(lab: Lab, params: Mapping[str, Any]) -> dict[str, Any]:
    raw = params.get("data")
    if isinstance(raw, str):
        raw = [re.split(r"[\s,;]+", line.strip()) for line in raw.strip().splitlines() if line.strip()]
    if not isinstance(raw, list) or len(raw) < 3:
        raise C.field_error("data", "Give at least 3 points, one 'x y' pair per line")
    if len(raw) > 200:
        raise C.field_error("data", "At most 200 points")
    pts = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise C.field_error("data", "Each line must hold an x and a y")
        pts.append((float(C.number({"v": p[0]}, "v")), float(C.number({"v": p[1]}, "v"))))
    pts.sort()
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if any(b <= a for a, b in zip(xs, xs[1:])):
        raise C.field_error("data", "The x values must all be different")
    queries = lab.reals(params, "queries", 0, 50) if params.get("queries") not in (None, "", []) else []
    stem = lab.stem
    methods = [("Linear", "linear_interpolation"), ("Polynomial", "polynomial_interpolation"), ("Cubic spline", "cubic_spline")]
    fns: dict[str, Callable[[float], float]] = {}
    o = lab.out
    for label, op in methods:
        try:
            fns[label] = stem.call_raw("numerical_methods", op, xs, ys)
        except StemFailed as exc:
            o.warn(f"{label}: {exc.message}")

    def at(label: str, x: float) -> float | None:
        try:
            return float(fns[label](x))
        except Exception:                                                              # noqa: BLE001 - outside the data range or a numerical failure
            return None

    rows = []
    for q in queries:
        row: dict[str, Any] = {"x": q}
        for label in fns:
            v = at(label, q)
            row[label] = float(f"{v:.10g}") if v is not None else None
        rows.append(row)
    lo, hi = xs[0], xs[-1]
    grid = [lo + (hi - lo) * i / 160 for i in range(161)]
    series = [{"label": "Data", "points": [[x, y] for x, y in pts], "kind": "scatter"}]
    for label in fns:
        curve = [[x, v] for x in grid if (v := at(label, x)) is not None and math.isfinite(v)]
        if curve:
            series.append({"label": label, "points": curve, "kind": "line", "dashed": label == "Polynomial"})
    res: dict[str, Any] = {"points": len(pts), "range": f"{_g(lo)} to {_g(hi)}", "plot": _plot("Interpolation", "x", "y", series, description="The data and each interpolant between the first and last x.")}
    if rows:
        res["values"] = rows
    if len(pts) > 8 and "Polynomial" in fns:
        o.warn("With this many points the single polynomial can swing wildly between them (Runge's phenomenon); the cubic spline is usually safer.")
    if any(q < lo or q > hi for q in queries):
        o.warn("Some queries lie outside the data. STEM does not extrapolate: those cells are empty.")
    return o.done(**res)


# ------------------------------------------------------------------------------------------------------------------ bootstrap
def bootstrap(lab: Lab, params: Mapping[str, Any]) -> dict[str, Any]:
    xs = lab.reals(params, "values", 3, 2000)
    stat = str(params.get("statistic") or "mean")
    if stat not in ("mean", "median", "std"):
        raise C.field_error("statistic", "The statistic must be mean, median or std")
    resamples = int(lab.real(params, "resamples", 2000, integer=True, lo=100, hi=20000))
    conf = lab.real(params, "confidence", 0.95)
    if not 0.5 <= conf < 1:
        raise C.field_error("confidence", "The confidence level must be from 0.5 to below 1")
    seed = int(lab.real(params, "seed", 1, integer=True, lo=0, hi=2 ** 31 - 1))
    stem = lab.stem
    if stat == "mean":
        def statistic(s: Sequence[float]) -> float:
            return math.fsum(s) / len(s)
    elif stat == "median":
        def statistic(s: Sequence[float]) -> float:
            t = sorted(s)
            m = len(t) // 2
            return t[m] if len(t) % 2 else (t[m - 1] + t[m]) / 2
    else:
        def statistic(s: Sequence[float]) -> float:
            mu = math.fsum(s) / len(s)
            return math.sqrt(math.fsum((v - mu) ** 2 for v in s) / (len(s) - 1))
    r = stem.call("statistics", "bootstrap_ci", xs, statistic, resamples, conf, _seed=seed)
    o = lab.out
    res: dict[str, Any] = {"statistic": stat, "estimate": lab.num(float(r["estimate"])), "lower": lab.num(float(r["lower"])), "upper": lab.num(float(r["upper"])),
                           "confidence": f"{conf:.0%}", "resamples": resamples, "seed": seed, "n": len(xs)}
    if stat == "mean":
        from ..domains.measurement.ops import _t_crit
        mu = stem.number("statistics", "mean", xs)
        sd = stem.number("statistics", "standard_deviation", xs, ddof=1)
        half = _t_crit(1 - (1 - conf) / 2, len(xs) - 1) * sd / math.sqrt(len(xs))
        res["tInterval"] = [lab.num(mu - half), lab.num(mu + half)]
        o.step("Comparison", detail="The Student-t interval assumes the data are roughly normal; the bootstrap does not. A large difference means the data are skewed or the sample is small.")
    o.step("Method", detail=f"Percentile bootstrap: {resamples:,} resamples with replacement, seed {seed}.")
    if len(xs) < 10:
        o.warn("With fewer than about 10 values a bootstrap interval is usually too narrow.")
    return o.done(**res)


# ------------------------------------------------------------------------------------------------------------------ catalogue
def catalogue(lab: Lab, params: Mapping[str, Any]) -> dict[str, Any]:
    ops = lab.stem.operations()
    rows = [{"domain": d, "operations": len(v), "available": ", ".join(v)} for d, v in sorted(ops.items())]
    st = lab.stem.status()
    return lab.out.done(agent="SLAI STEM agent", operationCount=st.get("operationCount"), domains=rows,
                        notes=["SciCal uses these operations for its STEM checks (the shield button on results) and for the Lab operations on this page."])


OPS: dict[str, Callable[[Lab, Mapping[str, Any]], dict[str, Any]]] = {
    "ode": ode, "monte_carlo": monte_carlo, "quadrature": quadrature, "roots": roots, "linear": linear,
    "interpolate": interpolate, "bootstrap": bootstrap, "catalogue": catalogue,
}


def run(stem: StemBridge, settings: Settings, op: str, params: Mapping[str, Any], evaluate: Callable[..., dict[str, Any]] | None = None) -> dict[str, Any]:
    """One STEM Lab operation. Always returns a result dict: errors are ``{"ok": False, "error": ...}`` like every other workspace."""
    fn = OPS.get(op)
    if fn is None:
        return {"ok": False, "error": {"code": "not_found", "message": f"Unknown STEM Lab operation '{op}'", "hint": "Available: " + ", ".join(sorted(OPS))}}
    try:
        stem.operations()                                                              # raises StemUnavailable with the reason
        lab = Lab(stem.scoped(TIME_LIMIT_S + 5), settings, evaluate)
        return fn(lab, params)
    except (StemUnavailable, StemFailed, SciCalError) as exc:
        return {"ok": False, "error": exc.to_dict()}
    except RecursionError:
        return {"ok": False, "error": {"code": "limit_exceeded", "message": "The expression is nested too deeply"}}
    except (ValueError, OverflowError, ZeroDivisionError) as exc:
        return {"ok": False, "error": {"code": "bad_request", "message": f"{type(exc).__name__}: {exc}"}}


__all__ = ["OPS", "run", "Lab", "Budget", "BadRequest"]
