"""Chemistry operations that the API exposes: periodic table, molar mass, balancing, stoichiometry, empirical formulas."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Any

import sympy as sp

from ...core.numerical.context import Settings
from ...core.units import Quantity, convert, parse_unit
from ...errors import BadRequest, ChemistryError, DimensionError
from .. import common as C
from . import elements as E
from .balance import balance as balance_equation
from .balance import parse_equation
from .formula import empirical_from_amounts, molar_mass, parse_formula, percent_composition


def D(x: Decimal | str | int) -> sp.Rational:
    return sp.Rational(str(x))


# ------------------------------------------------------------------------------------------------------------------ table
def periodic_table(params: dict, s: Settings) -> dict:
    q = C.text(params, "query", required=False, maxlen=60)
    items = [{k: e[k] for k in ("z", "symbol", "name", "weight", "uncertainty", "weightKind", "period", "group", "block", "category", "electronegativity", "state")}
             for e in E.search(q)]
    return {"ok": True, "elements": items, "meta": E.meta(), "count": len(items)}


def element_info(params: dict, s: Settings) -> dict:
    e = E.element(C.get(params, "element", required=True))
    w, u, kind = E.atomic_weight(e["symbol"])
    out = dict(e)
    out["weightValue"] = float(w)
    out["weightNote"] = {"standard": "Standard atomic weight (CIAAW 2024)",
                         "conventional": "Conventional atomic weight; the standard weight is an interval because natural abundances vary",
                         "none": "No standard atomic weight: the mass number of the longest-lived isotope, not an average"}[kind]
    if e["isotopes"]:
        out["isotopeNote"] = "Atomic masses from AME2020 (via NIST); abundances from IUPAC/NIST. Only a selection of isotopes is listed."
    return {"ok": True, "element": out, "meta": E.meta()}


# ------------------------------------------------------------------------------------------------------------------ molar mass
def molar_mass_op(params: dict, s: Settings) -> dict:
    f = parse_formula(C.text(params, "formula"))
    out = C.Out(s)
    total, u, notes = molar_mass(f)
    rows = []
    for r in percent_composition(f):
        w, wu, kind = E.atomic_weight(r["element"])
        out.step(f"{r['count']} × {r['element']}", f"{r['count']} × {w} = {r['mass']} g/mol")
        rows.append({"element": r["element"], "name": r["name"], "count": r["count"], "atomicWeight": str(w), "subtotal": out.num(D(r["mass"]), "g/mol"),
                     "percent": out.num(D(r["percent"]), "%")})
    out.step("Add the contributions", f"M = {total} g/mol")
    for n in notes:
        out.warn(n)
    data = {"formula": f.text, "pretty": f.pretty(), "latex": f.latex(), "hill": f.hill(), "charge": f.charge,
            "molarMass": out.num(D(total), "g/mol"), "composition": rows, "atoms": f.atoms()}
    if u is not None:
        data["uncertainty"] = out.num(D(u), "g/mol")
    if f.parts:
        data["parts"] = [{"coefficient": c, "formula": p.pretty()} for c, p in f.parts]
    if f.charge:
        out.warn("The mass of the electrons gained or lost is negligible (about 0.00055 g/mol per electron) and is not included.")
    return out.done(**data)


def balance_op(params: dict, s: Settings) -> dict:
    eq = C.text(params, "equation")
    res = balance_equation(eq)
    out = C.Out(s)
    left, right = parse_equation(eq)
    given = [x.given_coef for x in left + right]
    if any(g is not None for g in given):
        coefs = res["coefficients"]
        if all(g == c for g, c in zip(given, coefs)):
            out.step("Your coefficients are correct")
        else:
            out.warn("The coefficients you typed are not a balanced set; the balanced version is shown.")
    el = ", ".join(f"{k}: {v}" for k, v in res["verification"]["atomsLeft"].items())
    out.step("Atoms on each side", el)
    if res["verification"]["chargeLeft"] or res["verification"]["chargeRight"]:
        out.step("Charge on each side", f"{res['verification']['chargeLeft']:+d}")
    if res.get("ambiguous"):
        out.warn(res["note"])
    return out.done(**{k: v for k, v in res.items() if k != "ok"})


# ------------------------------------------------------------------------------------------------------------------ amounts
def _species_table(eq_result: dict) -> list[dict]:
    rows = []
    for side, key in (("reactant", "reactants"), ("product", "products")):
        for sp_ in eq_result[key]:
            if sp_["species"] in ("e⁻", "e-"):
                continue
            f = parse_formula(sp_["species"])
            m, _, _ = molar_mass(f)
            rows.append({"species": sp_["species"], "pretty": sp_["pretty"], "coef": sp_["coefficient"], "side": side, "M": D(m), "formula": f})
    return rows


def _moles_of(item: dict, M: sp.Rational, name: str, out: C.Out) -> sp.Expr:
    amt = item.get("amount")
    vol, conc = item.get("volume"), item.get("concentration")
    if conc is not None or vol is not None:
        v = C.quantity({"v": vol}, "v", "L", positive=True)
        c = C.quantity({"c": conc}, "c", "mol/L", positive=True)
        n = v.mag * c.mag
        out.step(f"{name}: moles from volume and concentration", f"n = V × c = {v.mag} L × {c.mag} mol/L")
        return n
    raw = amt
    if raw is None:
        raise C.field_error("amount", f"Give an amount for {name} (a mass such as '10 g' or an amount such as '0.5 mol')")
    q = C._eval_value(raw, True, "amount")
    if not isinstance(q, Quantity):
        raise C.field_error("amount", f"The amount of {name} needs a unit (g, mol, mg, kg ...)")
    if q.unit.dim == parse_unit("g").dim:
        m = convert(q, parse_unit("g")).mag
        out.step(f"{name}: moles from mass", f"n = m / M = {m} g / {M} g/mol")
        return m / M
    if q.unit.dim == parse_unit("mol").dim:
        return convert(q, parse_unit("mol")).mag
    raise DimensionError(f"The amount of {name} must be a mass or an amount of substance (mol), not {q.unit.pretty}")


def stoichiometry(params: dict, s: Settings) -> dict:
    res = balance_equation(C.text(params, "equation"))
    out = C.Out(s)
    out.step("Balanced equation", res["balanced"])
    table = _species_table(res)
    by_name = {r["species"]: r for r in table}
    pretty_to = {r["pretty"]: r["species"] for r in table}
    given = params.get("given")
    if not isinstance(given, list) or not given:
        raise C.field_error("given", "Give the amount of at least one reactant")
    moles: dict[str, sp.Expr] = {}
    for item in given:
        if not isinstance(item, dict):
            raise C.field_error("given", "Each given amount must be an object")
        name = str(item.get("species", "")).strip()
        name = pretty_to.get(name, name)
        if name not in by_name:
            raise C.field_error("given", f"'{name}' does not appear in the equation", hint="Use the formulas exactly as in the equation.")
        if by_name[name]["side"] != "reactant":
            raise C.field_error("given", f"'{name}' is a product; give amounts of reactants", hint="Use the yield option for products.")
        moles[name] = _moles_of(item, by_name[name]["M"], name, out)
    extents = {n: moles[n] / by_name[n]["coef"] for n in moles}
    limiting = min(extents, key=lambda n: sp.N(extents[n], 30))
    xi = extents[limiting]
    out.step("Extent of reaction for each reactant", "; ".join(f"{n}: {out.num(extents[n])['text']} mol ÷ {by_name[n]['coef']}" for n in extents))
    if len(moles) > 1:
        out.step("Limiting reagent", f"{limiting} runs out first (smallest n/coefficient)")
    rows = []
    for r in table:
        used = r["coef"] * xi
        row = {"species": r["species"], "pretty": r["pretty"], "side": r["side"], "coefficient": r["coef"], "molarMass": out.num(r["M"], "g/mol")}
        if r["side"] == "reactant":
            row["consumed"] = out.num(used, "mol")
            row["consumedMass"] = out.num(used * r["M"], "g")
            if r["species"] in moles:
                left = moles[r["species"]] - used
                row["given"] = out.num(moles[r["species"]], "mol")
                row["remaining"] = out.num(left, "mol")
                row["remainingMass"] = out.num(left * r["M"], "g")
            else:
                row["note"] = "assumed to be in excess"
        else:
            row["produced"] = out.num(used, "mol")
            row["producedMass"] = out.num(used * r["M"], "g")
        rows.append(row)
    data: dict[str, Any] = {"balanced": res["balanced"], "pretty": res["pretty"], "latex": res["latex"], "species": rows,
                            "limiting": limiting, "extent": out.num(xi, "mol")}
    target = params.get("target")
    if target:
        t = pretty_to.get(str(target), str(target))
        if t not in by_name or by_name[t]["side"] != "product":
            raise C.field_error("target", f"'{target}' is not a product of this reaction")
        theo = by_name[t]["coef"] * xi * by_name[t]["M"]
        data["theoreticalYield"] = out.num(theo, "g")
        out.step(f"Theoretical yield of {t}", f"{by_name[t]['coef']} × {out.num(xi)['text']} mol × {by_name[t]['M']} g/mol")
        actual = C.quantity(params, "actualYield", "g", required=False, nonneg=True)
        if actual is not None:
            pct = actual.mag / theo * 100
            data["percentYield"] = out.num(pct, "%")
            out.step("Percent yield", f"actual ÷ theoretical × 100 = {out.num(pct)['text']} %")
            if pct > 100:
                out.warn("The actual yield exceeds the theoretical yield: check for impurities, wet product, or a mistake in the data.")
    if len(moles) < sum(1 for r in table if r["side"] == "reactant"):
        out.warn("Reactants without a given amount are assumed to be in excess.")
    return out.done(**data)


def empirical(params: dict, s: Settings) -> dict:
    comp = params.get("composition")
    if not isinstance(comp, dict) or len(comp) < 2:
        raise C.field_error("composition", "Give at least two elements with their percentages or masses, e.g. {\"C\": \"40.0\", \"H\": \"6.7\", \"O\": \"53.3\"}")
    basis = params.get("basis", "percent")
    out = C.Out(s)
    amounts: dict[str, Fraction] = {}
    total_pct = sp.Integer(0)
    for el, v in comp.items():
        sym = E.element(el)["symbol"]
        x = C.number({"v": v}, "v", positive=True)
        total_pct += x
        w, _, _ = E.atomic_weight(sym)
        n = x / D(w)
        out.step(f"{sym}: moles per 100 g" if basis == "percent" else f"{sym}: moles", f"{x} ÷ {w} = {out.num(n)['text']} mol")
        amounts[sym] = Fraction(int(sp.numer(n)), int(sp.denom(n)))
    if basis == "percent" and abs(float(total_pct) - 100) > 1.5:
        out.warn(f"The percentages add up to {out.num(total_pct)['text']}, not 100.")
    counts, mult = empirical_from_amounts(amounts)
    from .formula import Formula
    f = Formula("", dict(counts))
    emp_txt = f.hill()
    ef = parse_formula(emp_txt)
    em, _, _ = molar_mass(ef)
    out.step("Divide by the smallest amount" + (f" and multiply by {mult}" if mult > 1 else ""), ", ".join(f"{k}: {v}" for k, v in counts.items()))
    data: dict[str, Any] = {"empirical": emp_txt, "pretty": ef.pretty(), "empiricalMass": out.num(D(em), "g/mol"), "counts": counts, "multiplier": mult}
    mm = C.quantity(params, "molarMass", "g/mol", required=False, positive=True)
    if mm is not None:
        ratio = mm.mag / D(em)
        n = int(round(float(ratio)))
        if n < 1 or abs(float(ratio) - n) > 0.08 * max(1, n):
            out.warn(f"The molar mass is not close to a whole multiple of the empirical formula mass (ratio {out.num(ratio)['text']}).")
        else:
            mol = Formula("", {k: v * n for k, v in counts.items()})
            mf = parse_formula(mol.hill())
            data["molecular"] = mol.hill()
            data["molecularPretty"] = mf.pretty()
            data["multiple"] = n
            out.step("Molecular formula", f"{out.num(mm.mag)['text']} ÷ {out.num(D(em))['text']} ≈ {n}, so multiply the empirical formula by {n}")
    return out.done(**data)


OPS = {"periodic_table": periodic_table, "element": element_info, "molar_mass": molar_mass_op, "balance": balance_op,
       "stoichiometry": stoichiometry, "empirical": empirical}
