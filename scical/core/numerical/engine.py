"""One calculation, start to finish: text -> parse -> evaluate -> format -> JSON-ready result."""
from __future__ import annotations

from typing import Any

import sympy as sp

from ...errors import ParseError, SciCalError
from ..expressions import ParseOptions, parse
from ..expressions import ast as A
from ..expressions.printer import to_latex, to_text
from ..units import Quantity
from . import ops
from .context import Context
from .evaluator import Evaluator
from .format import Formatter
from .values import Equation, SolutionSet, Table, Text, Vec

MAX_INPUT = 10_000


class TracingEvaluator(Evaluator):
    """Records the value of every compound sub-expression in evaluation order (the 'show the work' view)."""

    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx)
        self.trace: list[tuple[A.Node, Any]] = []

    def ev(self, node: A.Node) -> Any:
        v = super().ev(node)
        if node.kind in ("bin", "unary", "postfix", "call", "convert", "qty") and len(self.trace) < 60:
            self.trace.append((node, v))
        return v


def parse_options(ctx: Context) -> ParseOptions:
    return ParseOptions(units=ctx.settings.units, variables=frozenset(ctx.variables), functions=frozenset(ctx.functions))


def calculate(text: str, ctx: Context, *, explain: bool = False) -> dict[str, Any]:
    """Run one input line against ``ctx`` (which is updated by assignments). Never raises for bad input: errors come back as data."""
    try:
        if not isinstance(text, str):
            raise ParseError("The input must be text")
        if len(text) > MAX_INPUT:
            raise ParseError(f"The input is too long ({len(text)} characters; the limit is {MAX_INPUT})")
        parsed = parse(text, parse_options(ctx))
        ev: Evaluator = TracingEvaluator(ctx) if explain else Evaluator(ctx)
        value = ev.run(parsed.node)
        if isinstance(value, Equation):
            from .funcs_symbolic import solve_equation
            value = solve_equation(ev, value)
        return build_result(text, parsed.node, value, ev, parsed.warnings, ctx, explain)
    except SciCalError as exc:
        return {"ok": False, "input": text, "error": exc.to_dict()}
    except RecursionError:
        return {"ok": False, "input": text, "error": {"code": "limit_exceeded", "message": "The calculation is nested too deeply"}}


def build_result(text: str, node: A.Node, value: Any, ev: Evaluator, parse_warnings: list, ctx: Context, explain: bool) -> dict[str, Any]:
    fmt = Formatter(ctx.settings, ev.decimal_input, ev.numeric_method)
    out: dict[str, Any] = {"ok": True, "input": text}
    out["normalized"] = to_text(node)
    out["inputLatex"] = to_latex(node)
    kind = node.kind
    if kind == "funcdef":
        out.update(kind="definition", value=fmt.value(value), name=node.name, params=list(node.params))        # type: ignore[attr-defined]
    else:
        out["value"] = fmt.value(value)
        out["kind"] = "assignment" if kind == "assign" else out["value"]["t"]
        if kind == "assign":
            out["name"] = node.name                                                                          # type: ignore[attr-defined]
        if not isinstance(value, (Text, Equation)):
            ctx.ans = value
    out["flags"] = flags_for(value, ev)
    warnings = [w.to_dict() for w in parse_warnings] + [{"kind": "note", "message": m} for m in ev.warnings]
    if warnings:
        out["warnings"] = warnings
    if ev.numeric_method:
        out["numeric"] = {"method": ev.numeric_method, **{k: v for k, v in ev.numeric_info.items()}}
    if isinstance(value, Quantity):
        out["unit"] = out["value"]["unit"]
    if explain and isinstance(ev, TracingEvaluator):
        out["steps"] = steps_for(ev, fmt)
    return out


def flags_for(value: Any, ev: Evaluator) -> dict[str, bool]:
    approx = ev.numeric_method is not None or ops.has_float(value)
    symbolic = False
    if isinstance(value, sp.Expr) and not isinstance(value, sp.MatrixBase):
        symbolic = bool(value.free_symbols)
    elif isinstance(value, Vec):
        symbolic = any(getattr(x, "free_symbols", None) for x in value.items)
    elif ops.is_matrix(value):
        symbolic = any(x.free_symbols for x in value)
    elif isinstance(value, Quantity):
        symbolic = bool(value.mag.free_symbols)
    cplx = isinstance(value, sp.Expr) and not isinstance(value, sp.MatrixBase) and value.has(sp.I)
    return {"exact": not approx and not isinstance(value, (bool, Text)), "approximate": approx, "symbolic": symbolic, "complex": bool(cplx)}


def steps_for(ev: TracingEvaluator, fmt: Formatter) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    seen: set[str] = set()
    for node, v in ev.trace:
        expr = to_text(node)
        if expr in seen:
            continue
        seen.add(expr)
        try:
            val = fmt.value(v)
        except Exception:
            continue
        if val["text"] == expr:
            continue
        steps.append({"expr": expr, "exprLatex": to_latex(node), "value": val["text"], "valueLatex": val["latex"]})
    return steps
