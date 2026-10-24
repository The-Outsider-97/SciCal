"""Formula library browsing and the formula editor operations."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import sympy as sp

from ...core.numerical.context import Settings
from ...core.units import Dim, Quantity, convert, parse_unit
from ...core.units import constants as K
from ...errors import BadRequest, DimensionError, NotFound, SciCalError
from .. import common as C
from . import solver as V

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "formulas.json"
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,15}")


@lru_cache(maxsize=1)
def library() -> dict[str, dict]:
    raw = json.loads(_FILE.read_text(encoding="utf-8"))
    return {f["id"]: f for f in raw["formulas"]}


def _lib(fid: str) -> dict:
    f = library().get(fid)
    if f is None:
        raise NotFound(f"Unknown formula '{fid}'", details={"field": "formulaId"})
    return f


def _variable_table(eq, declared: dict[str, dict]) -> dict[str, dict]:
    return {str(x): declared.get(str(x), {"symbol": str(x), "name": str(x), "unit": ""}) for x in sorted(eq.symbols(), key=str)}


# ------------------------------------------------------------------------------------------------------------------ library
def formula_library(params: dict, s: Settings) -> dict:
    q = str(params.get("query", "")).strip().lower()
    cat = str(params.get("category", "")).strip().lower()
    items = []
    for f in library().values():
        if cat and f["category"].lower() != cat:
            continue
        hay = " ".join([f["id"], f["name"], f["category"], f.get("equation", ""), f.get("note", "")] + [v["name"] for v in f["variables"]]).lower()
        if q and q not in hay:
            continue
        items.append(f)
    cats = sorted({f["category"] for f in library().values()})
    return {"ok": True, "formulas": items, "categories": cats, "count": len(items)}


# ------------------------------------------------------------------------------------------------------------------ analyse
def formula_analyze(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    eq = V.parse_equation(C.text(params, "equation"))
    syms = sorted(eq.symbols(), key=str)
    if len(syms) > 12:
        raise BadRequest("At most 12 variables", details={"field": "equation"})
    data: dict[str, Any] = {"equation": f"{sp.sstr(eq.lhs)} = {sp.sstr(eq.rhs)}", "latex": f"{sp.latex(eq.lhs)} = {sp.latex(eq.rhs)}", "variables": [str(x) for x in syms]}
    solvable = {}
    for x in syms:
        try:
            sols = sp.solve(sp.Eq(eq.lhs, eq.rhs), x)
            solvable[str(x)] = [sp.latex(sp.simplify(z)) for z in sols][:4]
        except Exception:
            solvable[str(x)] = None
    data["rearranged"] = solvable
    units = params.get("units")
    if isinstance(units, dict) and units:
        dims = {}
        for x in syms:
            try:
                dims[x] = V.to_dim_unit(str(units.get(str(x), ""))).dim
            except SciCalError as exc:
                exc.details = {**exc.details, "field": "units", "variable": str(x)}
                raise
        ld, rd = V.dim_of(eq.lhs, dims), V.dim_of(eq.rhs, dims)
        ok = ld == rd
        data["dimensional"] = {"left": ld.name, "right": rd.name, "consistent": ok}
        if not ok:
            raise DimensionError(f"The two sides do not match: left is {ld.name}, right is {rd.name}", details={"left": ld.name, "right": rd.name},
                                 hint="Check the exponents and whether a constant is missing.")
        out.step("Dimensional check", f"Both sides are {ld.name}")
    else:
        out.warn("Give the unit of each variable to run a dimensional check.")
    return out.done(**data)


# ------------------------------------------------------------------------------------------------------------------ solve
def _value_for(name: str, raw: Any, declared_unit: str, sy: str) -> tuple[sp.Expr, Dim]:
    if isinstance(raw, dict):
        raw = f"{raw.get('value')} {raw.get('unit', '')}".strip()
    v = C._eval_value(raw, True, name)
    if isinstance(v, Quantity):
        return V.quantity_si(v)
    if not isinstance(v, sp.Expr) or v.free_symbols or not v.is_real:
        raise C.field_error(name, f"'{name}' must be a real number")
    u = V.to_dim_unit(declared_unit)
    return V.quantity_si(Quantity(v, u)) if not u.is_empty() else (v, Dim())


def formula_solve(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    fid = params.get("formulaId")
    declared: dict[str, dict] = {}
    if fid:
        f = _lib(str(fid))
        equation = f["equation"]
        declared = {v["symbol"]: v for v in f["variables"]}
        data: dict[str, Any] = {"formula": {"id": f["id"], "name": f["name"], "latex": f.get("latex")}}
    else:
        equation = C.text(params, "equation")
        data = {}
        custom_units = params.get("units") or {}
        if not isinstance(custom_units, dict):
            raise C.field_error("units", "'units' must map each variable to its unit")
        declared = {k: {"symbol": k, "name": k, "unit": str(u)} for k, u in custom_units.items()}
    eq = V.parse_equation(equation)
    names = {str(x): x for x in eq.symbols()}
    target_name = C.text(params, "solveFor")
    if target_name not in names:
        raise C.field_error("solveFor", f"'{target_name}' does not appear in the equation", hint="Variables: " + ", ".join(sorted(names)))
    target = names[target_name]
    values = params.get("values") or {}
    if not isinstance(values, dict):
        raise C.field_error("values", "'values' must map each variable to a value")
    known: dict[sp.Symbol, sp.Expr] = {}
    dims: dict[sp.Symbol, Dim] = {}
    shown = []
    for nm, x in names.items():
        if nm == target_name:
            dims[x] = V.to_dim_unit(declared.get(nm, {}).get("unit", "")).dim
            continue
        raw = values.get(nm)
        d = declared.get(nm, {})
        if raw in (None, "") and d.get("constant"):
            c = K.get(d["constant"])
            q = c.quantity()
            mag, dim = V.quantity_si(q)
            out.warn(f"{nm} = {c.name} (CODATA 2022) was filled in automatically.")
        elif raw in (None, ""):
            raise C.field_error(f"values.{nm}", f"A value for '{nm}' is required", hint="Every variable except the one you solve for needs a value.")
        else:
            mag, dim = _value_for(f"values.{nm}", raw, d.get("unit", ""), nm)
        known[x] = mag
        dims[x] = dim
        shown.append({"variable": nm, "name": d.get("name", nm), "si": out.num(mag, V.si_unit_for(dim).pretty if not dim.is_dimensionless() else None)})
    # dimensional consistency of the equation as a whole
    ld, rd = V.dim_of(eq.lhs, dims), V.dim_of(eq.rhs, dims)
    if ld != rd:
        raise DimensionError(f"The units do not balance: the left side is {ld.name} and the right side is {rd.name}",
                             hint="Check the units you entered; the equation is not dimensionally consistent with them.", details={"left": ld.name, "right": rd.name})
    out.step("Equation", f"{sp.sstr(eq.lhs)} = {sp.sstr(eq.rhs)}", latex=f"{sp.latex(eq.lhs)} = {sp.latex(eq.rhs)}")
    out.step("Dimensional check", f"Both sides are {ld.name}")
    # symbolic rearrangement (for display and for the dimension of the answer)
    sym_sols = []
    try:
        sym_sols = [sp.simplify(z) for z in sp.solve(sp.Eq(eq.lhs, eq.rhs), target)]
    except Exception:
        sym_sols = []
    if sym_sols:
        out.step(f"Solve for {target_name}", "; ".join(f"{target_name} = {sp.sstr(z)}" for z in sym_sols[:3]), latex=r"\quad\text{or}\quad ".join(f"{sp.latex(target)} = {sp.latex(z)}" for z in sym_sols[:3]))
        data["rearranged"] = [sp.latex(z) for z in sym_sols[:4]]
        try:
            tdim = V.dim_of(sym_sols[0], dims)
        except SciCalError:
            tdim = None
    else:
        tdim = None
    sols = V.solve_for(eq, target, known)
    if tdim is None:
        tdim = V.to_dim_unit(declared.get(target_name, {}).get("unit", "")).dim
    si_u = V.si_unit_for(tdim)
    out_unit_txt = params.get("outputUnit") or declared.get(target_name, {}).get("unit") or ""
    try:
        out_u = V.to_dim_unit(out_unit_txt) if out_unit_txt else si_u
    except SciCalError as exc:
        exc.details = {**exc.details, "field": "outputUnit"}
        raise
    if out_u.dim != tdim:
        raise DimensionError(f"{target_name} comes out as {tdim.name}, which cannot be shown in {out_u.pretty} ({out_u.dim.name})", details={"field": "outputUnit"})
    results = []
    for z in sols:
        q = Quantity(z, si_u) if not si_u.is_empty() else None
        mag = convert(q, out_u).mag if q is not None else z
        results.append(out.num(mag, out_u.pretty if not out_u.is_empty() else None))
    primary = 0
    if len(sols) > 1:
        pos = [i for i, z in enumerate(sols) if sp.N(z) > 0]
        if len(pos) == 1:
            primary = pos[0]
        out.warn(f"The equation has {len(sols)} real solutions for {target_name}; choose the one that makes physical sense.")
    data.update(solveFor=target_name, result=results[primary], solutions=results, ambiguous=len(sols) > 1, dimension=tdim.name, inputs=shown)
    return out.done(**data)


OPS = {"formula_library": formula_library, "formula_analyze": formula_analyze, "formula_solve": formula_solve}
