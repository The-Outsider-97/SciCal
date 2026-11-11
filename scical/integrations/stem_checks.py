"""STEM checks: an independent second computation, by SLAI's STEM agent, of a result SciCal already produced.

A check never changes a result. It asks the agent for the same quantity by a *different route* and reports one of

* ``agree``    the two numbers match within the stated tolerance,
* ``differ``   they do not (both values are shown; SciCal's stays the answer, and the difference is the thing to look into),
* ``skipped``  the agent has no operation for this, or does not know a unit, or the input is outside what it accepts (the reason says which),
* ``failed``   the agent was reached but raised an error (the message is shown).

Where possible the two routes really are different: SciCal's symbolic derivative is compared with STEM's numerical differentiation of the
original expression, SciCal's exact integral with STEM's adaptive quadrature, SciCal's roots with the residual STEM computes at each root,
SciCal's propagated uncertainty with STEM's Jacobian propagation of sensitivities STEM itself estimated. Closed-form quantities (a mean, a
normal probability) are simply computed again by STEM's own routines.

Tolerances are stated on every check: 1e-9 relative for closed forms, looser (and named) for numerical methods.

Nothing here evaluates text as Python: SciCal's parser makes the expression tree, which is printed in the small grammar STEM's parametric
evaluator accepts.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from ..core.expressions import ast as A
from ..core.expressions.parser import ParseOptions, parse
from ..errors import SciCalError
from .stem_bridge import StemBridge, StemFailed, StemUnavailable

CLOSED = (1e-9, 1e-12)                  # relative, absolute tolerance for closed-form quantities
NUMERIC_DERIVATIVE = (1e-6, 1e-9)
NUMERIC_QUADRATURE = (1e-7, 1e-10)
ROOT_RESIDUAL = 1e-9                    # |f(root)| allowed, scaled by the size of the terms


class Unsupported(Exception):
    """This input cannot be handed to STEM (the message is shown as the reason for skipping)."""


# ------------------------------------------------------------------------------------------------------------------ results
def _fmt(x: float | None) -> str | None:
    if x is None:
        return None
    return f"{x:.12g}"


def _close(a: float, b: float, rtol: float, atol: float) -> bool:
    return abs(a - b) <= atol + rtol * max(abs(a), abs(b))


def compare(title: str, ours: float, theirs: float, via: str, tol: tuple[float, float] = CLOSED, *, note: str | None = None, unit: str | None = None) -> dict[str, Any]:
    ok = _close(ours, theirs, *tol)
    return {"title": title, "status": "agree" if ok else "differ", "scical": _fmt(ours), "stem": _fmt(theirs), "difference": abs(ours - theirs),
            "tolerance": f"relative {tol[0]:g}, absolute {tol[1]:g}", "via": via, "note": note, "unit": unit}


def equal(title: str, ours: Any, theirs: Any, via: str, *, note: str | None = None) -> dict[str, Any]:
    ok = ours == theirs
    return {"title": title, "status": "agree" if ok else "differ", "scical": str(ours), "stem": str(theirs), "difference": None if ok else abs(float(ours) - float(theirs)) if _isnum(ours) and _isnum(theirs) else None,
            "tolerance": "exact", "via": via, "note": note, "unit": None}


def skipped(title: str, reason: str) -> dict[str, Any]:
    return {"title": title, "status": "skipped", "scical": None, "stem": None, "difference": None, "tolerance": None, "via": None, "note": reason, "unit": None}


def failed(title: str, reason: str, via: str | None = None) -> dict[str, Any]:
    return {"title": title, "status": "failed", "scical": None, "stem": None, "difference": None, "tolerance": None, "via": via, "note": reason, "unit": None}


def _isnum(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ------------------------------------------------------------------------------------------------------------------ reading SciCal's results
_REAL = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def parse_real(text: Any) -> float | None:
    """A real number from SciCal's text: ``3``, ``-1 / 5``, ``3.3333e-9``. Anything symbolic, complex or unit-carrying gives ``None``."""
    if not isinstance(text, str):
        return None
    t = text.strip().replace("−", "-").replace(" ", "")
    try:
        if "/" in t:
            a, b = t.split("/", 1)
            if _REAL.match(a) and _REAL.match(b) and float(b) != 0:
                return float(Fraction(a) / Fraction(b))
            return None
        if _REAL.match(t):
            return float(t)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return None


def num_of(node: Any) -> float | None:
    """The real value of a result node (``number`` or ``quantity``), or ``None`` when it is symbolic."""
    if not isinstance(node, Mapping):
        return None
    t = node.get("t")
    if t == "number":
        if node.get("symbolic"):
            return None
        approx = node.get("approx")
        if isinstance(approx, Mapping) and approx.get("text") is not None:
            v = parse_real(approx["text"])
            if v is not None:
                return v
        ex = node.get("exact")
        if isinstance(ex, Mapping):
            return parse_real(ex.get("text"))
        return None
    if t == "quantity":
        return num_of(node.get("mag"))
    if "value" in node and _isnum(node["value"]):                                    # a domain NUM dict
        return float(node["value"])
    return None


def nums_of(items: Any) -> list[float] | None:
    if not isinstance(items, list):
        return None
    out = []
    for it in items:
        v = num_of(it)
        if v is None:
            return None
        out.append(v)
    return out


def matrix_of(node: Any) -> list[list[float]] | None:
    if not isinstance(node, Mapping) or node.get("t") != "matrix":
        return None
    rows = []
    for r in node.get("rows", []):
        v = nums_of(r)
        if v is None:
            return None
        rows.append(v)
    return rows


# ------------------------------------------------------------------------------------------------------------------ the environment
@dataclass
class CheckEnv:
    """What a check may use: the STEM bridge, a way to ask SciCal's own engine a question, and the worksheet context."""
    stem: StemBridge
    evaluate: Callable[[str, list[str], dict[str, Any]], dict[str, Any]]      # (input, context lines, settings overrides) -> calc result
    context: list[str]
    settings: dict[str, Any]

    PRECISE = {"digits": 17, "notation": "auto", "decimals": None, "thousands": False, "result": "auto"}

    def sc(self, text: str, **override: Any) -> dict[str, Any]:
        s = {**self.settings, **self.PRECISE, **override}
        return self.evaluate(text, self.context, s)

    def sc_number(self, text: str, **override: Any) -> float | None:
        r = self.sc(text, **override)
        return num_of(r.get("value")) if r.get("ok") else None

    @property
    def angle(self) -> str:
        return str(self.settings.get("angle", "rad"))


# ------------------------------------------------------------------------------------------------------------------ expression -> STEM grammar
_TRIG = {"sin", "cos", "tan"}
_DIRECT = {"sin", "cos", "tan", "sinh", "cosh", "tanh", "exp", "sqrt", "abs"}
_NAME = re.compile(r"^[A-Za-z_][A-Za-z_0-9]*$")


def pname(name: str) -> str:
    """The name under which STEM sees one of SciCal's variables. STEM refuses names that are unit symbols (m, s, g, N, C, K, V, ...), so every
    variable is prefixed; the prefix cannot collide with a unit or a function."""
    return "v_" + name


def P(values: Mapping[str, float]) -> dict[str, float]:
    return {pname(k): v for k, v in values.items()}


class Translator:
    """SciCal expression tree -> the Python-syntax arithmetic STEM's parametric evaluator reads. Collects the names that need values."""

    def __init__(self, angle: str = "rad") -> None:
        self.angle = angle
        self.names: set[str] = set()
        self.nodes = 0

    def tr(self, n: A.Node) -> str:
        self.nodes += 1
        if self.nodes > 200:
            raise Unsupported("the expression is too large for the STEM evaluator")
        if isinstance(n, A.Num):
            return repr(float(n.text))
        if isinstance(n, A.Var):
            if n.name in ("pi", "e"):
                return n.name
            if not _NAME.match(n.name):
                raise Unsupported(f"'{n.name}' is not a name STEM can use")
            self.names.add(n.name)
            return pname(n.name)
        if isinstance(n, A.Unary):
            inner = self.tr(n.arg)
            return f"(-{inner})" if n.op == "-" else inner
        if isinstance(n, A.Postfix):
            if n.op == "%":
                return f"({self.tr(n.arg)} / 100.0)"
            if n.op == "°":
                return f"({self.tr(n.arg)} * pi / 180.0)"
            raise Unsupported("a factorial inside an expression")
        if isinstance(n, A.Binary):
            l, r = self.tr(n.left), self.tr(n.right)
            if n.op in ("+", "-", "*", "/"):
                return f"({l} {n.op} {r})"
            if n.op == "^":
                return f"({l} ** {r})"
            raise Unsupported(f"the operator '{n.op}'")
        if isinstance(n, A.Call):
            return self._call(n)
        raise Unsupported(f"a {n.kind} inside an expression")

    def _call(self, n: A.Call) -> str:
        name = n.name
        if len(n.args) not in (1, 2):
            raise Unsupported(f"{name} with {len(n.args)} arguments")
        args = [self.tr(a) for a in n.args]
        if name in _TRIG:
            arg = args[0]
            if self.angle == "deg":
                arg = f"({arg} * pi / 180.0)"
            elif self.angle == "grad":
                arg = f"({arg} * pi / 200.0)"
            out = f"{name}({arg})"
        elif name in _DIRECT and len(args) == 1:
            out = f"{name}({args[0]})"
        elif name == "ln" and len(args) == 1:
            out = f"log({args[0]})"
        elif name in ("log", "log10") and len(args) == 1:
            out = f"(log({args[0]}) / log(10.0))"
        elif name == "log2" and len(args) == 1:
            out = f"(log({args[0]}) / log(2.0))"
        elif name == "root" and len(args) == 2:
            out = f"({args[0]} ** (1.0 / {args[1]}))"
        else:
            raise Unsupported(f"the function {name}")
        if n.power is not None:
            out = f"({out} ** {self.tr(n.power)})"
        return out


def to_stem(text_or_node: str | A.Node, angle: str = "rad", variables: frozenset[str] = frozenset()) -> tuple[str, set[str]]:
    node = text_or_node if isinstance(text_or_node, A.Node) else parse(text_or_node, ParseOptions(variables=variables)).node
    t = Translator(angle)
    return t.tr(node), t.names


# ------------------------------------------------------------------------------------------------------------------ STEM-side helpers
class StemFunction:
    """A one-variable function made from an expression and evaluated by STEM's own parametric evaluator (so STEM, not SciCal, supplies each value)."""

    MAX_CALLS = 60000

    def __init__(self, env: CheckEnv, expr: str, var: str, params: Mapping[str, float]) -> None:
        self.env, self.expr, self.var, self.params = env, expr, var, dict(params)
        self.calls = 0

    def __call__(self, x: float) -> float:
        self.calls += 1
        if self.calls > self.MAX_CALLS:
            raise StemFailed("The STEM check stopped: the expression needed too many evaluations.")
        p = dict(self.params)
        p[self.var] = float(x)
        return self.env.stem.number("parametric", "evaluate_expression", self.expr, P(p))


def _free_values(env: CheckEnv, names: set[str], exclude: set[str], defaults: Mapping[str, float] | None = None) -> dict[str, float]:
    """Numbers for the names an expression uses besides its variable (worksheet definitions like ``a := 5``), asked from SciCal's engine."""
    out: dict[str, float] = {}
    for nm in sorted(names - exclude):
        v = env.sc_number(nm)
        if v is None and defaults and nm in defaults:
            v = defaults[nm]
        if v is None:
            raise Unsupported(f"'{nm}' has no numeric value in this worksheet")
        out[nm] = v
    return out


def _guard(title: str, fn: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Run a check; turn the expected failure modes into a skipped/failed row instead of an error."""
    try:
        return fn()
    except Unsupported as exc:
        return [skipped(title, f"Not handed to STEM: {exc}.")]
    except StemUnavailable:
        raise
    except StemFailed as exc:
        return [failed(title, exc.message)]
    except SciCalError as exc:
        return [failed(title, exc.message)]
    except (ValueError, ZeroDivisionError, OverflowError) as exc:
        return [failed(title, f"{type(exc).__name__}: {exc}")]


# ------------------------------------------------------------------------------------------------------------------ calc checks
STAT_ONE = {"mean": ("mean", {}), "median": ("median", {}), "std": ("standard_deviation", {"ddof": 1}), "stdp": ("standard_deviation", {"ddof": 0}),
            "var": ("variance", {"ddof": 1}), "varp": ("variance", {"ddof": 0})}
STAT_TWO = {"corr": "correlation"}


def _literal_list(n: A.Node) -> list[float] | None:
    if isinstance(n, A.Vector):
        out = []
        for it in n.items:
            if isinstance(it, A.Num):
                out.append(float(it.text))
            elif isinstance(it, A.Unary) and it.op == "-" and isinstance(it.arg, A.Num):
                out.append(-float(it.arg.text))
            else:
                return None
        return out
    return None


def _literal_number(n: A.Node) -> float | None:
    if isinstance(n, A.Num):
        return float(n.text)
    if isinstance(n, A.Unary) and n.op in "+-" and isinstance(n.arg, A.Num):
        return -float(n.arg.text) if n.op == "-" else float(n.arg.text)
    return None


def check_calc(env: CheckEnv, text: str, result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    try:
        node = parse(text, ParseOptions(units=bool(env.settings.get("units")) or "->" in text)).node
    except SciCalError as exc:
        return [skipped("Input", f"SciCal could not read this input: {exc.message}")]
    except Exception:                                                                  # noqa: BLE001
        return [skipped("Input", "SciCal could not read this input.")]
    if isinstance(node, (A.Assign, A.FuncDef)):
        return [skipped("Definition", "A definition has no value to check.")]
    if isinstance(node, A.Convert):
        return _guard("Unit conversion", lambda: _check_convert(env, node))
    if isinstance(node, A.Postfix) and node.op == "!":
        return _guard("Factorial", lambda: _check_factorial(env, node))
    if isinstance(node, A.Call):
        name = node.name
        if name in STAT_ONE or name in STAT_TWO or name in ("slope", "intercept", "rsq"):
            return _guard("Statistic", lambda: _check_stat(env, node))
        if name in ("normalpdf", "normalcdf", "normalprob", "invnorm", "binompdf", "binomcdf", "tpdf", "tcdf", "chi2cdf"):
            return _guard("Distribution", lambda: _check_distribution(env, node))
        if name in ("gcd", "lcm", "nCr", "factorial"):
            return _guard("Number theory", lambda: _check_numbertheory(env, node))
        if name == "diff":
            return _guard("Derivative", lambda: _check_diff(env, node))
        if name in ("integral", "nintegral"):
            return _guard("Integral", lambda: _check_integral(env, node))
        if name in ("solve", "roots", "nsolve"):
            return _guard("Roots", lambda: _check_roots(env, node))
        if name in ("inv", "eigenvals", "linsolve"):
            return _guard("Matrix", lambda: _check_matrix(env, node))
    if isinstance(node, A.Binary) and node.op == "^" and isinstance(node.left, A.Matrix):
        return _guard("Matrix inverse", lambda: _check_matrix(env, node))
    return _guard("Value", lambda: _check_scalar(env, node))


def _check_scalar(env: CheckEnv, node: A.Node) -> list[dict[str, Any]]:
    if isinstance(node, (A.Vector, A.Matrix, A.Rel, A.Logic, A.Qty, A.UnitExpr)):
        raise Unsupported("it is not a single real number")
    expr, names = to_stem(node, env.angle)
    params = _free_values(env, names, set())
    ours = env.sc_number(_unparse(node))
    if ours is None:
        raise Unsupported("SciCal's result is not a real number (it is symbolic, complex or has units)")
    theirs = env.stem.number("parametric", "evaluate_expression", expr, P(params))
    return [compare("Value of the expression", ours, theirs, "parametric.evaluate_expression", note="STEM's own bounded evaluator, not SciCal's parser or evaluator.")]


def _unparse(node: A.Node) -> str:
    from ..core.expressions.printer import to_text
    return to_text(node)


def _check_stat(env: CheckEnv, node: A.Call) -> list[dict[str, Any]]:
    name = node.name
    if name in STAT_ONE:
        if len(node.args) != 1:
            raise Unsupported("expects one list")
        xs = _literal_list(node.args[0])
        if not xs or len(xs) < 2:
            raise Unsupported("it needs a literal list of at least two numbers")
        op, kw = STAT_ONE[name]
        ours = env.sc_number(_unparse(node))
        if ours is None:
            raise Unsupported("SciCal's result is not a real number")
        theirs = env.stem.number("statistics", op, xs, **kw)
        return [compare(f"{name} of {len(xs)} values", ours, theirs, f"statistics.{op}")]
    if len(node.args) != 2:
        raise Unsupported("expects two lists")
    xs, ys = _literal_list(node.args[0]), _literal_list(node.args[1])
    if not xs or not ys or len(xs) != len(ys) or len(xs) < 2:
        raise Unsupported("it needs two literal lists of equal length")
    ours = env.sc_number(_unparse(node))
    if ours is None:
        raise Unsupported("SciCal's result is not a real number")
    if name == "corr":
        return [compare("Pearson correlation", ours, env.stem.number("statistics", "correlation", xs, ys), "statistics.correlation")]
    fit = env.stem.call("statistics", "linear_regression", xs, ys)
    key = {"slope": "slope", "intercept": "intercept", "rsq": "r_squared"}[name]
    return [compare({"slope": "Regression slope", "intercept": "Regression intercept", "rsq": "R squared"}[name], ours, float(fit[key]), "statistics.linear_regression")]


def _check_distribution(env: CheckEnv, node: A.Call) -> list[dict[str, Any]]:
    name = node.name
    vals = [_literal_number(a) for a in node.args]
    if any(v is None for v in vals):
        raise Unsupported("it needs numeric arguments written as numbers")
    v = [float(x) for x in vals]                                                      # type: ignore[arg-type]
    ours = env.sc_number(_unparse(node))
    if ours is None:
        raise Unsupported("SciCal's result is not a real number")
    S = env.stem
    if name == "normalpdf" and len(v) == 3:
        return [compare("Normal density", ours, S.number("statistics", "normal_pdf", v[0], v[1], v[2]), "statistics.normal_pdf")]
    if name == "normalcdf" and len(v) == 3:
        return [compare("Normal cumulative probability", ours, S.number("statistics", "normal_cdf", v[0], v[1], v[2]), "statistics.normal_cdf")]
    if name == "normalprob" and len(v) == 4:
        hi = S.number("statistics", "normal_cdf", v[1], v[2], v[3])
        lo = S.number("statistics", "normal_cdf", v[0], v[2], v[3])
        return [compare("Normal probability between two values", ours, hi - lo, "statistics.normal_cdf (upper) - normal_cdf (lower)")]
    if name == "invnorm" and len(v) == 3:
        return [compare("Normal quantile", ours, S.number("statistics", "normal_ppf", v[0], v[1], v[2]), "statistics.normal_ppf")]
    if name == "binompdf" and len(v) == 3:
        n, p, k = v
        if n != int(n) or k != int(k):
            raise Unsupported("n and k must be whole numbers")
        return [compare("Binomial probability", ours, S.number("statistics", "binomial_pmf", int(k), int(n), p), "statistics.binomial_pmf")]
    if name == "binomcdf" and len(v) == 3:
        n, p, k = v
        if n != int(n) or k != int(k) or not 0 <= k <= 500:
            raise Unsupported("n and k must be whole numbers, k at most 500")
        total = math.fsum(S.number("statistics", "binomial_pmf", i, int(n), p) for i in range(int(k) + 1))
        return [compare("Binomial cumulative probability", ours, total, "statistics.binomial_pmf, summed")]
    if name == "tpdf" and len(v) == 2:
        return [compare("Student t density", ours, S.number("statistics", "t_pdf", v[0], v[1]), "statistics.t_pdf")]
    if name == "tcdf" and len(v) == 2:
        return [compare("Student t cumulative probability", ours, S.number("statistics", "t_cdf", v[0], v[1]), "statistics.t_cdf")]
    if name == "chi2cdf" and len(v) == 2:
        return [compare("Chi-square cumulative probability", ours, S.number("statistics", "chi_square_cdf", v[0], v[1]), "statistics.chi_square_cdf")]
    raise Unsupported(f"{name} with {len(v)} arguments")


def _check_numbertheory(env: CheckEnv, node: A.Call) -> list[dict[str, Any]]:
    vals = [_literal_number(a) for a in node.args]
    if any(v is None or v != int(v) or v < 0 for v in vals):
        raise Unsupported("it needs whole numbers written as numbers")
    v = [int(x) for x in vals]                                                        # type: ignore[arg-type]
    ours = env.sc_number(_unparse(node))
    if ours is None:
        raise Unsupported("SciCal's result is not a real number")
    op = {"gcd": ("gcd", 2), "lcm": ("lcm", 2), "nCr": ("binomial", 2), "factorial": ("factorial", 1)}[node.name]
    if len(v) != op[1]:
        raise Unsupported(f"{node.name} with {len(v)} arguments")
    if node.name == "factorial" and v[0] > 170:
        raise Unsupported("the number is too large to compare as a float")
    theirs = env.stem.call("computing", op[0], *v)
    return [equal(f"{node.name}{tuple(v)}", int(ours) if float(ours).is_integer() and abs(ours) < 2 ** 53 else ours, theirs, f"computing.{op[0]}",
                  note="Exact whole-number arithmetic on both sides.")]


def _check_factorial(env: CheckEnv, node: A.Postfix) -> list[dict[str, Any]]:
    n = _literal_number(node.arg)
    if n is None or n != int(n) or not 0 <= n <= 170:
        raise Unsupported("it needs a whole number from 0 to 170")
    ours = env.sc_number(_unparse(node))
    if ours is None:
        raise Unsupported("SciCal's result is not a real number")
    theirs = env.stem.call("computing", "factorial", int(n))
    return [compare(f"{int(n)}!", ours, float(theirs), "computing.factorial")]


def _sample_points(lo: float = 0.4, hi: float = 2.6, n: int = 5) -> list[float]:
    return [round(lo + (hi - lo) * i / (n - 1), 6) for i in range(n)]


def _calculus_args(node: A.Call) -> tuple[A.Node, str]:
    if len(node.args) < 2 or not isinstance(node.args[1], A.Var):
        raise Unsupported("it needs a function and a variable")
    return node.args[0], node.args[1].name


def _check_diff(env: CheckEnv, node: A.Call) -> list[dict[str, Any]]:
    f_node, var = _calculus_args(node)
    if len(node.args) > 2:
        raise Unsupported("only first derivatives are compared")
    expr, names = to_stem(f_node, env.angle, frozenset({var}))
    params = _free_values(env, names, {var})
    res = env.sc(_unparse(node))
    if not res.get("ok"):
        raise Unsupported("SciCal did not give a result to compare")
    exact = ((res.get("value") or {}).get("exact") or {}).get("text") if isinstance(res.get("value"), Mapping) else None
    if not exact:
        raise Unsupported("SciCal's result has no closed form to evaluate")
    rows, good = [], 0
    for p in _sample_points():
        ours = _eval_at(env, exact, var, p)
        if ours is None:
            continue
        try:
            d = env.stem.call("parametric", "derivative", expr, P({**params, var: p}), pname(var))
        except StemFailed:
            continue
        theirs = d.get("value") if isinstance(d, Mapping) else None
        if not _isnum(theirs):
            continue
        rows.append((p, ours, float(theirs)))
        good += 1
    if good < 2:
        raise Unsupported("the expression could not be evaluated at enough points")
    worst = max(rows, key=lambda r: abs(r[1] - r[2]) / (1e-9 + max(abs(r[1]), abs(r[2]))))
    out = compare(f"d/d{var} at {good} points ({rows[0][0]:g} to {rows[-1][0]:g})", worst[1], worst[2], "parametric.derivative (central difference)", NUMERIC_DERIVATIVE,
                  note=f"Worst of {good} sample points, at {var} = {worst[0]:g}. SciCal differentiates symbolically; STEM differentiates the original expression numerically.")
    for r in rows:
        if not _close(r[1], r[2], *NUMERIC_DERIVATIVE):
            out["status"] = "differ"
    return [out]


def _eval_at(env: CheckEnv, formula: str, var: str, x: float) -> float | None:
    r = env.evaluate(formula, [*env.context, f"{var} := {x!r}"], {**env.settings, **env.PRECISE})
    return num_of(r.get("value")) if r.get("ok") else None


def _check_integral(env: CheckEnv, node: A.Call) -> list[dict[str, Any]]:
    f_node, var = _calculus_args(node)
    expr, names = to_stem(f_node, env.angle, frozenset({var}))
    params = _free_values(env, names, {var})
    if len(node.args) == 4:
        a, b = env.sc_number(_unparse(node.args[2])), env.sc_number(_unparse(node.args[3]))
        if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)) or a == b:
            raise Unsupported("the limits must be finite, different numbers")
        ours = env.sc_number(_unparse(node))
        if ours is None:
            raise Unsupported("SciCal's result is not a real number")
        fn = StemFunction(env, expr, var, params)
        theirs = env.stem.number("numerical_methods", "adaptive_quadrature", fn, a, b)
        return [compare(f"Integral from {a:g} to {b:g}", ours, theirs, "numerical_methods.adaptive_quadrature", NUMERIC_QUADRATURE,
                        note=f"SciCal integrates exactly; STEM integrates numerically using its own evaluation of the integrand ({fn.calls} evaluations).")]
    if len(node.args) == 2:
        res = env.sc(_unparse(node))
        exact = ((res.get("value") or {}).get("exact") or {}).get("text") if res.get("ok") and isinstance(res.get("value"), Mapping) else None
        if not exact:
            raise Unsupported("SciCal's result has no closed form to evaluate")
        anti, anames = to_stem(exact, env.angle, frozenset({var}))
        aparams = _free_values(env, anames, {var}, {"C": 0.0})
        worst, good = None, 0
        for p in _sample_points():
            try:
                d = env.stem.call("parametric", "derivative", anti, P({**aparams, var: p}), pname(var))
                f = env.stem.number("parametric", "evaluate_expression", expr, P({**params, var: p}))
            except StemFailed:
                continue
            dv = d.get("value") if isinstance(d, Mapping) else None
            if not _isnum(dv):
                continue
            good += 1
            err = abs(float(dv) - f) / (1e-9 + max(abs(float(dv)), abs(f)))
            if worst is None or err > worst[0]:
                worst = (err, p, float(dv), f)
        if good < 2 or worst is None:
            raise Unsupported("the antiderivative could not be evaluated at enough points")
        row = compare(f"Derivative of the antiderivative at {good} points", worst[3], worst[2], "parametric.derivative of SciCal's antiderivative", NUMERIC_DERIVATIVE,
                      note=f"The derivative of SciCal's result (STEM, numerically) should equal the integrand; worst point {var} = {worst[1]:g}. An antiderivative is defined up to a constant.")
        return [row]
    raise Unsupported("only definite integrals and plain antiderivatives are compared")


def _roots_of(res: Mapping[str, Any]) -> list[float] | None:
    v = res.get("value")
    if not isinstance(v, Mapping):
        return None
    if v.get("t") == "solutions":
        return nums_of(v.get("items"))
    if v.get("t") == "table":
        rows = v.get("rows") or []
        return nums_of([r[0] for r in rows if r])
    return None


def _check_roots(env: CheckEnv, node: A.Call) -> list[dict[str, Any]]:
    res = env.sc(_unparse(node))
    if not res.get("ok"):
        raise Unsupported("SciCal did not give a result to compare")
    roots = _roots_of(res)
    if not roots:
        raise Unsupported("no real numeric solutions to check")
    first = node.args[0]
    if node.name == "solve":
        if isinstance(first, A.Rel) and first.op == "=":
            lhs, rhs = first.left, first.right
            body = A.Binary(op="-", left=lhs, right=rhs)
        else:
            body = first
        var = node.args[1].name if len(node.args) > 1 and isinstance(node.args[1], A.Var) else None
    else:                                                                              # roots(poly) / nsolve(f, x, x0)
        body = first.left if isinstance(first, A.Rel) else first
        var = node.args[1].name if len(node.args) > 1 and isinstance(node.args[1], A.Var) else None
    expr, names = to_stem(body, env.angle)
    if var is None:
        free = sorted(names)
        if len(free) != 1:
            raise Unsupported("the unknown could not be identified")
        var = free[0]
    params = _free_values(env, names, {var})
    rows = []
    for r in roots[:12]:
        resid = env.stem.number("parametric", "evaluate_expression", expr, P({**params, var: r}))
        scale = max(1.0, abs(r))
        rows.append((r, resid, abs(resid) / scale))
    worst = max(rows, key=lambda t: t[2])
    ok = worst[2] <= ROOT_RESIDUAL
    out = {"title": f"Residual at {len(rows)} root{'s' if len(rows) != 1 else ''}", "status": "agree" if ok else "differ", "scical": f"{var} = " + ", ".join(_fmt(r[0]) or "" for r in rows[:6]),
           "stem": f"largest residual {worst[1]:.3g} at {var} = {_fmt(worst[0])}", "difference": abs(worst[1]), "tolerance": f"|residual| <= {ROOT_RESIDUAL:g} x max(1, |root|)",
           "via": "parametric.evaluate_expression (f(root) evaluated by STEM)", "note": "STEM substitutes each root into the equation; a true root leaves a residual of zero.", "unit": None}
    return [out]


def _check_matrix(env: CheckEnv, node: A.Node) -> list[dict[str, Any]]:
    if isinstance(node, A.Binary):                                                    # M^-1
        if not (isinstance(node.right, A.Unary) and node.right.op == "-" and isinstance(node.right.arg, A.Num) and node.right.arg.text == "1"):
            raise Unsupported("only the inverse (^-1) of a matrix is compared")
        mat_node, kind = node.left, "inv"
    else:
        kind = node.name
        mat_node = node.args[0] if node.args else None
    if not isinstance(mat_node, A.Matrix):
        raise Unsupported("the matrix must be written out as numbers")
    M = []
    for row in mat_node.rows:
        r = [_literal_number(c) for c in row]
        if any(x is None for x in r):
            raise Unsupported("the matrix must contain only numbers")
        M.append([float(x) for x in r])                                               # type: ignore[arg-type]
    res = env.sc(_unparse(node))
    if not res.get("ok"):
        raise Unsupported("SciCal did not give a result to compare")
    v = res.get("value")
    if kind == "inv":
        ours = matrix_of(v)
        if ours is None:
            raise Unsupported("SciCal's result is not a numeric matrix")
        theirs = env.stem.call("numerical_methods", "matrix_inverse", M)
        diff = max(abs(a - b) for ra, rb in zip(ours, theirs) for a, b in zip(ra, rb))
        scale = max(abs(x) for r in ours for x in r) or 1.0
        out = compare("Matrix inverse (largest entry difference)", 0.0, diff / scale, "numerical_methods.matrix_inverse")
        out["scical"] = "entries " + _fmt(ours[0][0]) + ", …"
        out["stem"] = "same entries to " + f"{diff / scale:.2g}" + " (relative to the largest entry)"
        return [out]
    if kind == "eigenvals":
        n = len(M)
        if any(len(r) != n for r in M) or any(abs(M[i][j] - M[j][i]) > 1e-12 for i in range(n) for j in range(n)):
            raise Unsupported("STEM's eigenvalue routine takes symmetric matrices")
        rows = (v or {}).get("rows") or []
        flat = []
        for r in rows:
            val, m = num_of(r[0]), num_of(r[1]) if len(r) > 1 else 1
            if val is None:
                raise Unsupported("SciCal's eigenvalues are not all numeric")
            flat.extend([val] * int(m or 1))
        theirs = sorted(env.stem.call("numerical_methods", "eigenvalues_symmetric", M))
        flat.sort()
        if len(flat) != len(theirs):
            return [failed("Eigenvalues", f"SciCal lists {len(flat)} eigenvalues (with multiplicity), STEM {len(theirs)}.", "numerical_methods.eigenvalues_symmetric")]
        diff = max(abs(a - b) for a, b in zip(flat, theirs))
        scale = max(abs(x) for x in flat) or 1.0
        out = compare("Eigenvalues (largest difference)", 0.0, diff / scale, "numerical_methods.eigenvalues_symmetric", (1e-8, 1e-10))
        out["scical"] = ", ".join(_fmt(x) or "" for x in flat[:6])
        out["stem"] = ", ".join(_fmt(x) or "" for x in theirs[:6])
        return [out]
    if kind == "linsolve":
        b_node = node.args[1] if len(node.args) > 1 else None
        b = _literal_list(b_node) if b_node is not None else None
        if b is None:
            raise Unsupported("the right-hand side must be a list of numbers")
        ours = nums_of((v or {}).get("items"))
        if ours is None:
            raise Unsupported("SciCal's solution is not numeric")
        theirs = env.stem.call("numerical_methods", "solve_linear_system", M, b)
        diff = max(abs(a - c) for a, c in zip(ours, theirs))
        scale = max(abs(x) for x in ours) or 1.0
        out = compare("Solution of the linear system", 0.0, diff / scale, "numerical_methods.solve_linear_system", (1e-8, 1e-10))
        out["scical"] = ", ".join(_fmt(x) or "" for x in ours[:6])
        out["stem"] = ", ".join(_fmt(x) or "" for x in theirs[:6])
        return [out]
    raise Unsupported(f"{kind}")


_UNIT_TO_STEM = {"m": "m", "cm": "cm", "mm": "mm", "km": "km", "g": "g", "kg": "kg", "s": "s", "ms": "ms", "min": "min", "h": "h", "N": "N", "J": "J", "W": "W",
                 "Pa": "Pa", "kPa": "kPa", "K": "K", "L": "L", "mol": "mol", "V": "V", "A": "A", "Hz": "Hz"}


def _check_convert(env: CheckEnv, node: A.Convert) -> list[dict[str, Any]]:
    if not isinstance(node.expr, A.Qty):
        raise Unsupported("it needs a number with a unit on the left")
    mag = _literal_number(node.expr.value)
    if mag is None:
        raise Unsupported("the quantity must be a plain number")
    if len(node.expr.unit.factors) != 1 or len(node.unit.factors) != 1:
        raise Unsupported("only single units are compared (for example m to cm)")
    (src, se), (dst, de) = node.expr.unit.factors[0], node.unit.factors[0]
    if str(se) != "1" or str(de) != "1":
        raise Unsupported("only first powers are compared")
    res = env.sc(_unparse(node), units=True)
    ours = num_of((res.get("value") or {}).get("mag")) if res.get("ok") and isinstance(res.get("value"), Mapping) else None
    if ours is None:
        raise Unsupported("SciCal's result is not a number with a unit")
    try:
        theirs = env.stem.number("units", "convert", mag, _UNIT_TO_STEM.get(src, src), _UNIT_TO_STEM.get(dst, dst))
    except StemFailed as exc:
        if "unit" in exc.message.lower():
            raise Unsupported(f"STEM's unit table did not accept '{src}' to '{dst}' ({exc.message.split(': ', 1)[-1]})") from exc
        raise
    return [compare(f"{mag:g} {src} in {dst}", ours, theirs, "units.convert")]


# ------------------------------------------------------------------------------------------------------------------ domain checks
def _val(res: Mapping[str, Any], *path: str) -> float | None:
    cur: Any = res
    for p in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(p)
    if isinstance(cur, Mapping) and _isnum(cur.get("value")):
        return float(cur["value"])
    return float(cur) if _isnum(cur) else None


def check_domain(env: CheckEnv, domain: str, op: str, params: Mapping[str, Any], res: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(res, Mapping) or res.get("ok") is False:
        return [skipped("Result", "The calculation did not produce a result to check.")]
    fn = DOMAIN_CHECKS.get((domain, op))
    if fn is None:
        return []
    return _guard(f"{domain}.{op}", lambda: fn(env, params, res))


def _dom_repeated(env: CheckEnv, params: Mapping[str, Any], res: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = params.get("values")
    xs = [float(v) for v in values] if isinstance(values, list) and all(_isnum(v) or (isinstance(v, str) and parse_real(v) is not None) for v in values) else None
    if xs is None:
        raw = res.get("values")
        xs = nums_of(raw) if isinstance(raw, list) else None
    if not xs or len(xs) < 2:
        raise Unsupported("the data could not be read as numbers")
    S = env.stem
    rows = [compare("Mean", _val(res, "mean") or 0.0, S.number("statistics", "mean", xs), "statistics.mean"),
            compare("Standard deviation (n-1)", _val(res, "standardDeviation") or 0.0, S.number("statistics", "standard_deviation", xs, ddof=1), "statistics.standard_deviation"),
            compare("Median", _val(res, "median") or 0.0, S.number("statistics", "median", xs), "statistics.median")]
    sd = S.number("statistics", "standard_deviation", xs, ddof=1)
    se = _val(res, "standardError")
    if se is not None:
        rows.append(compare("Standard error of the mean", se, sd / math.sqrt(len(xs)), "statistics.standard_deviation / sqrt(n)"))
    t, level = _val(res, "tValue"), _val(res, "confidenceLevel")
    if t is not None and level is not None and len(xs) >= 2:
        upper = 0.5 + level / 2.0
        cdf = S.number("statistics", "t_cdf", t, len(xs) - 1)
        rows.append(compare(f"t value for {level:.0%} confidence, n-1 = {len(xs) - 1} degrees of freedom", upper, cdf, "statistics.t_cdf",
                            note="STEM evaluates the Student t distribution at SciCal's t value; the result must be (1 + confidence) / 2."))
    return rows


def _dom_calibration(env: CheckEnv, params: Mapping[str, Any], res: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = params.get("data")
    pts = []
    if isinstance(data, list):
        for row in data:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                a = float(row[0]) if _isnum(row[0]) else parse_real(row[0])
                b = float(row[1]) if _isnum(row[1]) else parse_real(row[1])
                if a is None or b is None:
                    raise Unsupported("the calibration data could not be read as numbers")
                pts.append((a, b))
    if len(pts) < 3:
        raise Unsupported("it needs at least three calibration points")
    fit = env.stem.call("statistics", "linear_regression", [p[0] for p in pts], [p[1] for p in pts])
    rows = [compare("Slope", _val(res, "slope") or 0.0, float(fit["slope"]), "statistics.linear_regression"),
            compare("Intercept", _val(res, "intercept") or 0.0, float(fit["intercept"]), "statistics.linear_regression", (1e-9, 1e-9)),
            compare("R squared", _val(res, "rSquared") or 0.0, float(fit["r_squared"]), "statistics.linear_regression")]
    n = len(pts)
    s = _val(res, "residualStdDev")
    if s is not None and n > 2:
        rows.append(compare("Residual standard deviation", s, math.sqrt(float(fit["residual_sum_squares"]) / (n - 2)), "statistics.linear_regression (residual sum of squares / (n-2))"))
    return rows


def _formula_pairs(res: Mapping[str, Any]) -> list[tuple[str, float, float]]:
    out = []
    for c in res.get("contributions") or []:
        if not isinstance(c, Mapping):
            continue
        u, s = _val(c, "standardUncertainty"), _val(c, "sensitivity")
        if u is not None and s is not None:
            out.append((str(c.get("source")), u, s))
    return out


def _dom_budget(env: CheckEnv, params: Mapping[str, Any], res: Mapping[str, Any]) -> list[dict[str, Any]]:
    pairs = _formula_pairs(res)
    if not pairs:
        raise Unsupported("the budget has no numeric contributions")
    if res.get("correlationsPresent"):
        raise Unsupported("correlated budgets are not compared (independent inputs only)")
    S = env.stem
    uc = S.number("uncertainty", "combined_standard_uncertainty", [p[1] for p in pairs], sensitivity=[p[2] for p in pairs])
    rows = [compare("Combined standard uncertainty", _val(res, "combinedUncertainty") or 0.0, uc, "uncertainty.combined_standard_uncertainty")]
    k = res.get("coverageFactor")
    if _isnum(k):
        rows.append(compare(f"Expanded uncertainty (k = {k:g})", _val(res, "expandedUncertainty") or 0.0, S.number("uncertainty", "expanded_uncertainty", uc, float(k)), "uncertainty.expanded_uncertainty"))
    return rows


def _dom_formula_uncertainty(env: CheckEnv, params: Mapping[str, Any], res: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Two independent STEM routes: sensitivities estimated by STEM from the expression, propagated by STEM, plus a seeded Monte-Carlo run."""
    expr_text = params.get("expression")
    variables = params.get("variables")
    if not isinstance(expr_text, str) or not isinstance(variables, Mapping) or not variables:
        raise Unsupported("the formula or its variables are missing")
    expr, names = to_stem(expr_text, env.angle, frozenset(variables))
    order = [str(k) for k in variables]
    if set(names) - set(order):
        raise Unsupported("the formula uses names that have no value or uncertainty")
    means, us = [], []
    for k in order:
        spec = variables[k]
        m = parse_real(str(spec.get("value"))) if isinstance(spec, Mapping) else None
        u = parse_real(str(spec.get("uncertainty"))) if isinstance(spec, Mapping) else None
        if m is None or u is None:
            raise Unsupported(f"'{k}' has no plain numeric value and uncertainty")
        means.append(m)
        us.append(u)
    if params.get("correlations"):
        raise Unsupported("correlated inputs are not compared")
    S = env.stem

    def model(*vals: float) -> float:
        return S.number("parametric", "evaluate_expression", expr, P(dict(zip(order, [float(v) for v in vals]))))

    rows = [compare("Value of the formula at the means", _val(res, "value") or 0.0, model(*means), "parametric.evaluate_expression")]
    sens = S.call("uncertainty", "sensitivity_coefficients", model, means)
    u_first = S.number("uncertainty", "jacobian_propagation", [float(s) for s in sens], us)
    ours_u = _val(res, "combinedUncertainty")
    if ours_u is None:
        ours_u = _val(res, "uncertainty")
    if params.get("method") == "worst_case":
        raise Unsupported("worst-case combination is not a quadrature sum, which is what STEM propagates")
    if ours_u is not None:
        rows.append(compare("Combined standard uncertainty (first-order)", ours_u, u_first, "uncertainty.sensitivity_coefficients + jacobian_propagation", (1e-6, 1e-9),
                            note="STEM estimates every sensitivity coefficient numerically from the expression, then propagates them; SciCal differentiates symbolically."))
        mc = S.call("uncertainty", "monte_carlo_propagation", model, means, us, samples=4000, _seed=20240601)
        if isinstance(mc, Mapping) and _isnum(mc.get("standard_uncertainty")):
            su = float(mc["standard_uncertainty"])
            rel = abs(su - ours_u) / max(ours_u, 1e-300)
            rows.append({"title": "Combined standard uncertainty (Monte Carlo, 4000 samples, seed 20240601)", "status": "agree" if rel <= 0.08 else "differ", "scical": _fmt(ours_u), "stem": _fmt(su),
                         "difference": abs(su - ours_u), "tolerance": "within 8 % (sampling noise; the Monte-Carlo estimate is not exact)", "via": "uncertainty.monte_carlo_propagation",
                         "note": "A third opinion that does not assume the model is linear. It differs from the first-order value when the model is strongly non-linear over the uncertainty.", "unit": None})
    return rows


def _dom_formula_solve(env: CheckEnv, params: Mapping[str, Any], res: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Substitute the solved value back into the equation, in SI, and let STEM evaluate left minus right."""
    eq = params.get("equation")
    var = res.get("solveFor") or params.get("solveFor")
    sol = (res.get("solutions") or [None])[0] if isinstance(res.get("solutions"), list) else None
    ours = _val({"v": sol}, "v") if sol is not None else _val(res, "result")
    if not isinstance(eq, str) or not var or ours is None:
        raise Unsupported("the equation or its solution is missing")
    node = parse(eq.replace("**", "^")).node
    if not (isinstance(node, A.Rel) and node.op == "="):
        raise Unsupported("it is not an equation")
    expr, names = to_stem(A.Binary(op="-", left=node.left, right=node.right), env.angle)
    values: dict[str, float] = {str(var): ours}
    for item in res.get("inputs") or []:
        if isinstance(item, Mapping):
            si = _val(item, "si")
            if si is None:
                raise Unsupported("an input has no numeric SI value")
            values[str(item.get("variable"))] = si
    missing = names - set(values)
    if missing:
        raise Unsupported("no value for " + ", ".join(sorted(missing)))
    resid = env.stem.number("parametric", "evaluate_expression", expr, P({k: values[k] for k in names}))
    left = env.stem.number("parametric", "evaluate_expression", to_stem(node.left, env.angle)[0], P({k: values[k] for k in to_stem(node.left, env.angle)[1]}))
    scale = max(abs(left), abs(ours), 1e-300)
    ok = abs(resid) <= 1e-9 * scale
    return [{"title": f"Equation holds with {var} = {_fmt(ours)} (SI)", "status": "agree" if ok else "differ", "scical": f"{var} = {_fmt(ours)}", "stem": f"left - right = {resid:.3g}", "difference": abs(resid),
             "tolerance": "|left - right| <= 1e-9 x size of the terms", "via": "parametric.evaluate_expression",
             "note": "STEM substitutes SciCal's solution and the inputs (converted to SI) into the equation and evaluates both sides.", "unit": None}]


_PRESSURE = {"Pa": 1.0, "kPa": 1e3, "MPa": 1e6, "bar": 1e5, "mbar": 1e2, "atm": 101325.0, "mmHg": 133.322387415, "torr": 101325.0 / 760.0}
_VOLUME = {"L": 1e-3, "mL": 1e-6, "dm3": 1e-3, "cm3": 1e-6, "m3": 1.0}
_AMOUNT = {"mol": 1.0, "mmol": 1e-3}


def _qty_si(value: Any, kind: str) -> float | None:
    """A gas-law quantity as SI (Pa, m3, mol, K) from text such as '101.325 kPa', or from a SciCal result dict with ``value`` and ``unit``."""
    if isinstance(value, Mapping):
        num, unit = value.get("value"), value.get("unit")
        if not _isnum(num):
            return None
    elif _isnum(value):
        num, unit = float(value), None
    elif isinstance(value, str):
        m = re.match(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z\u00b0\u00b3]*)\s*$", value)
        if not m:
            return None
        num, unit = float(m.group(1)), m.group(2) or None
    else:
        return None
    unit = (unit or "").replace("\u00b3", "3").replace("\u00b0", "")
    table = {"P": _PRESSURE, "V": _VOLUME, "n": _AMOUNT}.get(kind)
    if kind == "T":
        return num if unit in ("", "K") else num + 273.15 if unit in ("C", "degC") else None
    if table is None or unit not in table:
        return None
    return float(num) * table[unit]


def _dom_gas(env: CheckEnv, params: Mapping[str, Any], res: Mapping[str, Any]) -> list[dict[str, Any]]:
    """PV = nRT: STEM computes the pressure from the amount, temperature and volume and it must equal the pressure SciCal has (given or solved)."""
    if res.get("mode") != "ideal":
        raise Unsupported("only the ideal-gas law has a STEM counterpart")
    solved = res.get("solvedFor")
    values = {k: _qty_si(params.get(k), k) for k in ("P", "n", "T", "V") if k != solved}
    values[str(solved)] = _qty_si(res.get("result"), str(solved))
    if any(values.get(k) is None for k in ("P", "n", "T", "V")):
        raise Unsupported("the pressure, amount, temperature and volume could not all be read in Pa, mol, K and m3")
    pa = env.stem.number("physics", "ideal_gas_pressure", values["n"], values["T"], values["V"])
    return [compare("PV = nRT: pressure from the other three (Pa)", values["P"], pa, "physics.ideal_gas_pressure", (1e-6, 1e-9),
                    note=f"SciCal solved for {solved}. STEM computes P = nRT/V from the amount, temperature and volume, with its own gas constant; the pressure must match.")]


def _dom_michaelis(env: CheckEnv, params: Mapping[str, Any], res: Mapping[str, Any]) -> list[dict[str, Any]]:
    if res.get("mode") != "fit":
        raise Unsupported("only the fitting mode is checked")
    data = params.get("data")
    vmax, km, r2 = _val(res, "vmax"), _val(res, "km"), _val(res, "rSquared")
    if not isinstance(data, list) or vmax is None or km is None or r2 is None:
        raise Unsupported("the data or the fit is missing")
    pts = [(float(a), float(b)) for a, b in data]
    S = env.stem
    preds = [S.number("biology", "michaelis_menten", s, vmax, km) for s, _ in pts]
    ys = [y for _, y in pts]
    ybar = math.fsum(ys) / len(ys)
    ss_res = math.fsum((y - p) ** 2 for y, p in zip(ys, preds))
    ss_tot = math.fsum((y - ybar) ** 2 for y in ys)
    return [compare("R squared of the fitted curve", r2, 1.0 - ss_res / ss_tot, "biology.michaelis_menten (model values) + residuals", (1e-7, 1e-9),
                    note="STEM evaluates the Michaelis-Menten model at every substrate concentration with SciCal's fitted Vmax and Km; the goodness of fit is recomputed from those values.")]


DOMAIN_CHECKS: dict[tuple[str, str], Callable[[CheckEnv, Mapping[str, Any], Mapping[str, Any]], list[dict[str, Any]]]] = {
    ("measurement", "repeated"): _dom_repeated,
    ("measurement", "calibration"): _dom_calibration,
    ("measurement", "uncertainty_budget"): _dom_budget,
    ("measurement", "formula_uncertainty"): _dom_formula_uncertainty,
    ("measurement", "uncertainty"): _dom_formula_uncertainty,
    ("formulas", "formula_solve"): _dom_formula_solve,
    ("chemistry", "gas"): _dom_gas,
    ("biology", "michaelis_menten"): _dom_michaelis,
}


# ------------------------------------------------------------------------------------------------------------------ entry point
def verify_entry(env: CheckEnv, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Run every check that applies to one worksheet entry and summarise. Raises StemUnavailable when there is no agent."""
    env.stem.operations()                                                              # raises StemUnavailable early with the reason
    kind = entry.get("kind")
    if kind == "calc":
        text = entry.get("input")
        if not isinstance(text, str) or not text.strip():
            return _summary([], "There is no input to check.")
        checks = check_calc(env, text, entry.get("result") if isinstance(entry.get("result"), Mapping) else None)
    elif kind == "domain":
        params = entry.get("params") if isinstance(entry.get("params"), Mapping) else {}
        checks = check_domain(env, str(entry.get("domain")), str(entry.get("op")), params, entry.get("result") if isinstance(entry.get("result"), Mapping) else {})
    else:
        return _summary([], "This kind of entry has no numerical result to check.")
    return _summary(checks, None)


def _summary(checks: list[dict[str, Any]], reason: str | None) -> dict[str, Any]:
    n = {s: sum(1 for c in checks if c["status"] == s) for s in ("agree", "differ", "skipped", "failed")}
    ran = n["agree"] + n["differ"]
    if not checks:
        verdict, text = "none", reason or "STEM has no independent check for this kind of result yet."
    elif n["differ"]:
        verdict, text = "differ", f"STEM differs on {n['differ']} of {ran} check{'s' if ran != 1 else ''}. SciCal's value is still the one shown: look at the difference."
    elif n["agree"]:
        verdict, text = "agree", f"STEM agrees on {n['agree']} of {ran} check{'s' if ran != 1 else ''}" + (f" ({n['skipped'] + n['failed']} not run)." if n["skipped"] + n["failed"] else ".")
    else:
        verdict, text = "none", "STEM could not run a check on this: " + (checks[0].get("note") or "see the details.")
    return {"ran": True, "verdict": verdict, "summary": text, "checks": checks, "counts": n,
            "label": "Computed again by the SLAI STEM agent by a different route. It only checks: SciCal's value is the one shown."}
