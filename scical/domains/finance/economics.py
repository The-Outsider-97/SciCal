"""Economics: inflation and purchasing power, percentage change, elasticity, break-even, cost/revenue/profit with marginals, and market equilibrium.

Each result separates what is *mathematics* (an identity or a derivative of the functions you typed) from what is a *model assumption*
(the functions themselves, linear costs, a constant price, ...). The assumptions are listed with every result.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any

import sympy as sp

from ...core.expressions import ParseOptions, parse
from ...core.numerical.context import Context, Settings
from ...core.numerical.evaluator import Evaluator
from ...errors import BadRequest, SciCalError
from . import core as C
from .core import Result, frac, power, rate, to_float
from .interest import one_empty
from .loans import cell

MAX_EXPR = 300


# ---------------------------------------------------------------------------------------------------------------------- expressions
def sym_expr(params: dict, key: str, allowed: tuple[str, ...]) -> tuple[sp.Expr, str]:
    """A formula typed by the person, as a SymPy expression in the allowed variables only. Returns the expression and the original text."""
    raw = params.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise C.field_error(key, f"'{key}' is required")
    if len(raw) > MAX_EXPR:
        raise C.field_error(key, f"The formula is too long (limit {MAX_EXPR} characters)")
    ctx = Context(settings=Settings(units=False))
    try:
        res = parse(raw, ParseOptions(units=False, allow_statements=False))
        v = Evaluator(ctx).run(res.node)
    except SciCalError as exc:
        exc.details = {**exc.details, "field": key}
        raise
    if not isinstance(v, sp.Expr):
        raise C.field_error(key, "The formula must give a number")
    names = {s.name for s in v.free_symbols}
    extra = names - set(allowed)
    if extra:
        raise C.field_error(key, f"The formula uses {', '.join(sorted(extra))}; only {' and '.join(allowed)} may appear.",
                            hint=f"Write the formula in terms of {allowed[0]}, for example 100 - 2*{allowed[0]}.")
    subs = {s: sp.Symbol(s.name, real=True) for s in v.free_symbols}
    return v.xreplace(subs), raw


def at(expr: sp.Expr, var: str, value: Fraction | sp.Expr) -> Fraction:
    v = sp.Symbol(var, real=True)
    val = sp.Rational(value.numerator, value.denominator) if isinstance(value, Fraction) else value
    out = sp.simplify(expr.subs(v, val))
    if out.is_real is False or out in (sp.zoo, sp.oo, -sp.oo) or out.has(sp.nan):
        raise BadRequest(f"The formula is not a finite real number at {var} = {value}", hint="Check for a division by zero or a logarithm of a non-positive number.")
    return C.to_fraction(out)


def graph_text(raw: str, var: str) -> str:
    return re.sub(rf"\b{var}\b", "x", raw)


def real_roots(expr: sp.Expr, var: str, lo: Fraction | None = None) -> list[Fraction]:
    """Real roots of ``expr`` in the variable, at or above ``lo``; polynomials exactly, other expressions by SymPy's solver (empty when it cannot)."""
    v = sp.Symbol(var, real=True)
    try:
        sols = sp.solve(sp.Eq(expr, 0), v)
    except (NotImplementedError, ValueError, TypeError, RecursionError):
        return []
    roots: list[Fraction] = []
    for s in sols:
        try:
            s = sp.nsimplify(s) if s.is_Float else s
            if s.is_real is False or s.has(sp.I):
                continue
            x = C.to_fraction(s)
        except (BadRequest, SciCalError, TypeError, ValueError):
            continue
        if lo is None or x >= lo:
            roots.append(x)
    return sorted(set(roots))


# ================================================================================================================ inflation
INFLATION_MODES = ("future_cost", "purchasing_power", "cpi", "average_rate")


def op_inflation(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    mode = C.choice(params, "mode", INFLATION_MODES, "future_cost")
    out: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    pts: list[tuple[float, float]] = []
    title = "Price level"
    if mode in ("future_cost", "purchasing_power"):
        amount = frac(params, "amount", positive=True)
        pi = rate(params, "inflation")
        t = frac(params, "years", positive=True)
        C.require(pi > -1, "Inflation must be greater than −100 %", "inflation")
        note = C.rate_note(pi * 100)
        if note:
            o.warn(note)
        o.assume(f"Prices change by a constant {C.fmt_decimal(pi * 100, 4)} % a year, compounded yearly. Actual inflation varies from year to year; this is a what-if, not a forecast.")
        factor = power(1 + pi, t, "years")
        if mode == "future_cost":
            fut = amount * factor
            o.step("Cost in the future", "future cost = today's cost × (1 + inflation)^years", r"A_t = A_0\,(1+\pi)^{t}")
            out.update(futureCost=f.money(fut), increase=f.money(fut - amount), cumulativeInflation=f.percent(factor - 1))
            title = "Cost of the same goods"
            end = int(math.ceil(float(t)))
            for y in range(0, end + 1):
                yy = min(Fraction(y), t)
                v = amount * power(1 + pi, yy, "years")
                pts.append((float(yy), to_float(v)))
                rows.append({"year": y if yy == y else to_float(yy), "value": cell(v, f.places)})
        else:
            real = amount / factor
            o.step("Purchasing power", "value in today's money = amount / (1 + inflation)^years", r"A_0 = \frac{A_t}{(1+\pi)^{t}}")
            out.update(valueInTodaysMoney=f.money(real), lostPurchasingPower=f.money(amount - real), lossShare=f.percent(1 - 1 / factor, label="share of purchasing power gone"))
            title = "Purchasing power of the amount"
            end = int(math.ceil(float(t)))
            for y in range(0, end + 1):
                yy = min(Fraction(y), t)
                v = amount / power(1 + pi, yy, "years")
                pts.append((float(yy), to_float(v)))
                rows.append({"year": y if yy == y else to_float(yy), "value": cell(v, f.places)})
        if pi == 0:
            o.warn("With 0 % inflation nothing changes.")
    elif mode == "cpi":
        amount = frac(params, "amount", positive=True)
        a = frac(params, "cpiFrom", positive=True)
        b = frac(params, "cpiTo", positive=True)
        o.assume("The price index values are taken as entered, from the same index and base year. The result is the amount that has the same purchasing power in the later period.")
        ratio = b / a
        o.step("Index ratio", "adjusted = amount × (index later / index earlier)", r"A' = A\,\frac{\mathrm{CPI}_{\mathrm{later}}}{\mathrm{CPI}_{\mathrm{earlier}}}")
        out.update(adjustedAmount=f.money(amount * ratio), indexRatio=f.amount(ratio, places=6), cumulativeInflation=f.percent(ratio - 1))
    else:
        a = frac(params, "cpiFrom", positive=True)
        b = frac(params, "cpiTo", positive=True)
        t = frac(params, "years", positive=True)
        o.assume("The average rate is the constant yearly rate that takes the first index value to the second: the actual path in between is not described.")
        avg = power(b / a, 1 / t, "years") - 1
        o.step("Average inflation", "average = (index later / index earlier)^(1/years) − 1", r"\bar\pi = \left(\frac{\mathrm{CPI}_{t}}{\mathrm{CPI}_{0}}\right)^{1/t} - 1")
        out.update(averageInflation=f.percent(avg, label="per year, compounded"), cumulativeInflation=f.percent(b / a - 1),
                   priceDoublingTime=f.amount(C.ln(Fraction(2)) / C.ln(1 + avg), unit="years") if avg > 0 else "not applicable (prices are not rising)")
    plot = None
    if pts:
        plot = C.plot_block(title, "Years", "Amount" + (f" ({f.code})" if f.has_currency else ""), [{"label": title, "points": [[x, y] for x, y in pts], "kind": "line"}])
    return o.done(mode=mode, **out, **({"table": rows, "plot": plot} if plot else {}))


# ================================================================================================================ percentage change
def op_percent_change(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    mode = C.choice(params, "mode", ("change", "apply", "reverse", "successive", "points"), "change")
    out: dict[str, Any] = {}
    if mode == "change":
        old = frac(params, "old")
        new = frac(params, "new")
        C.require(old != 0, "The change relative to 0 is undefined: there is no base to take a percentage of.", "old", hint="Report the absolute change instead.")
        pct = (new - old) / abs(old)
        o.step("Percentage change", "(new − old) / |old|", r"\Delta\% = \frac{V_1 - V_0}{|V_0|}")
        if old < 0:
            o.warn("The old value is negative, so the percentage is taken relative to its size |old|; a rise to a less negative number counts as an increase.")
        out.update(percentChange=f.percent(pct), absoluteChange=f.amount(new - old), ratio=f.amount(new / old, places=6))
        if new != 0:
            out["changeNeededToReturn"] = f.percent((old - new) / abs(new), label="the opposite move that undoes it: not the same percentage")
        if old > 0 and new > 0:
            out["logChange"] = f.percent(C.ln(new / old), label="continuously compounded change ln(new/old): these add up over time, percentages do not")
        o.assume("Percentage change is measured relative to the starting value.")
    elif mode == "apply":
        v = frac(params, "value")
        p = rate(params, "percent")
        out.update(result=f.amount(v * (1 + p)), change=f.amount(v * p))
        o.step("Apply a percentage", "result = value × (1 + p)", r"V' = V\,(1+p)")
    elif mode == "reverse":
        v = frac(params, "value")
        p = rate(params, "percent")
        C.require(p != -1, "A change of −100 % leaves nothing, so the original value cannot be recovered.", "percent")
        out.update(originalValue=f.amount(v / (1 + p)), change=f.amount(v - v / (1 + p)))
        o.step("Undo a percentage", "original = result / (1 + p)", r"V = \frac{V'}{1+p}")
        o.assume("The percentage was applied to the original value (so the original is not 'result minus p %').")
    elif mode == "successive":
        ps = C.numbers_list(params, "percents", minimum=2)
        total = Fraction(1)
        rows = []
        for k, p in enumerate(ps, 1):
            C.require(p > -100, "Each change must be above −100 %", "percents")
            total *= 1 + p / 100
            rows.append({"step": k, "change": f.percent(p / 100), "cumulative": f.percent(total - 1)})
        n = len(ps)
        out.update(totalChange=f.percent(total - 1), averagePerStep=f.percent(power(total, Fraction(1, n)) - 1, label="the constant per-step change with the same total (geometric mean)"),
                   simpleSum=f.percent(sum(ps, Fraction(0)) / 100, label="adding the percentages is NOT the total change"), steps=rows)
        o.step("Successive changes", "total = Π(1 + pₖ) − 1", r"\prod_k (1+p_k) - 1")
    else:
        a = rate(params, "rateA")
        b = rate(params, "rateB")
        out.update(percentagePointDifference=f.amount((b - a) * 100, unit="percentage points"))
        if a != 0:
            out["relativeChange"] = f.percent((b - a) / abs(a), label="the second rate relative to the first")
        o.step("Percentage points vs percent", "A change from A % to B % is (B − A) percentage points, or (B − A)/A in relative terms.")
    return o.done(mode=mode, **out)


# ================================================================================================================ elasticity
def op_elasticity(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    mode = C.choice(params, "mode", ("midpoint", "endpoint", "function"), "midpoint")
    out: dict[str, Any] = {}
    plot = plot2 = None
    if mode == "function":
        q_expr, q_raw = sym_expr(params, "demand", ("P",))
        p0 = frac(params, "price", positive=True)
        P = sp.Symbol("P", real=True)
        q0 = at(q_expr, "P", p0)
        C.require(q0 != 0, "Demand is zero at this price, so the elasticity is undefined (the percentage change in quantity has no base).", "price")
        dq = at(sp.diff(q_expr, P), "P", p0)
        e = dq * p0 / q0
        o.assume("The demand function Q(P) is your model. The elasticity is its exact derivative-based (point) elasticity, E = (dQ/dP)·P/Q, at that price.")
        o.step("Point elasticity", "E = (dQ/dP) · P / Q", r"E = \frac{dQ}{dP}\cdot\frac{P}{Q}")
        out.update(quantityDemanded=f.amount(q0), slope=f.amount(dq), elasticity=f.amount(e, places=6))
        hi = float(p0) * 2
        grid = [hi * k / 60 for k in range(1, 61)]
        e_pts, r_pts = [], []
        for pv in grid:
            try:
                qv = float(q_expr.subs(P, sp.Float(pv, 30)))
                dv = float(sp.diff(q_expr, P).subs(P, sp.Float(pv, 30)))
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if not (math.isfinite(qv) and math.isfinite(dv)):
                continue
            r_pts.append((pv, pv * qv))
            if qv != 0:
                e_pts.append((pv, dv * pv / qv))
        marker = [{"x": to_float(p0), "y": to_float(e), "label": f"E = {C.fmt_decimal(e, 3)}"}]
        plot = C.plot_block("Elasticity along the demand curve", "Price", "Elasticity E", [{"label": "E", "points": [[x, y] for x, y in e_pts], "kind": "line"}], markers=marker, zero_line=True,
                            description="Where |E| passes 1 revenue stops rising with price.")
        plot2 = C.plot_block("Revenue P·Q(P)", "Price", "Revenue", [{"label": "Revenue", "points": [[x, y] for x, y in r_pts], "kind": "line"}], description="Total revenue at each price on your demand curve.")
        rev_slope = q0 * (1 + e)
    else:
        p1, p2 = frac(params, "price1", positive=True), frac(params, "price2", positive=True)
        q1, q2 = frac(params, "quantity1", nonneg=True), frac(params, "quantity2", nonneg=True)
        C.require(p1 != p2, "The two prices are equal, so the price change is zero and the elasticity is undefined.", "price2")
        if mode == "midpoint":
            C.require(q1 + q2 > 0, "Both quantities are zero", "quantity1")
            dq_pct = (q2 - q1) / ((q1 + q2) / 2)
            dp_pct = (p2 - p1) / ((p1 + p2) / 2)
            o.assume("The midpoint (arc) method divides each change by the average of its two values, so the answer is the same whichever point is called first.")
            o.step("Midpoint elasticity", "E = [ΔQ / avg(Q)] / [ΔP / avg(P)]", r"E = \frac{(Q_2-Q_1)/\bar Q}{(P_2-P_1)/\bar P}")
        else:
            C.require(q1 > 0, "The starting quantity must be positive for an endpoint calculation", "quantity1")
            dq_pct = (q2 - q1) / q1
            dp_pct = (p2 - p1) / p1
            o.assume("The endpoint method measures each change relative to the first point; swapping the points gives a different answer.")
            o.step("Endpoint elasticity", "E = (ΔQ / Q₁) / (ΔP / P₁)", r"E = \frac{(Q_2-Q_1)/Q_1}{(P_2-P_1)/P_1}")
        e = dq_pct / dp_pct
        out.update(percentChangeInQuantity=f.percent(dq_pct), percentChangeInPrice=f.percent(dp_pct), elasticity=f.amount(e, places=6))
        r1, r2 = p1 * q1, p2 * q2
        out.update(revenueBefore=f.money(r1), revenueAfter=f.money(r2), revenueChange=f.money(r2 - r1))
        rev_slope = 1 + e
        plot = C.plot_block("The two observed points", "Quantity", "Price", [{"label": "Demand between the points", "points": [[to_float(q1), to_float(p1)], [to_float(q2), to_float(p2)]], "kind": "line"}],
                            description="A straight line between the observations: the data say nothing about the curve beyond them.")
        o.assume("Only two observations are used; the elasticity applies between them.")
    a = abs(e)
    if e > 0:
        out["classification"] = "positive elasticity: quantity rises with price (a Giffen/Veblen good or a data issue)"
        o.warn("A positive price elasticity of demand is unusual; check the data.")
    elif a > 1:
        out["classification"] = "elastic (|E| > 1): quantity responds more than proportionally to price"
    elif a == 1:
        out["classification"] = "unit elastic (|E| = 1)"
    elif a == 0:
        out["classification"] = "perfectly inelastic (E = 0)"
    else:
        out["classification"] = "inelastic (|E| < 1): quantity responds less than proportionally to price"
    if e < 0:
        out["revenueEffectOfRaisingPrice"] = "revenue falls" if a > 1 else ("revenue rises" if a < 1 else "revenue is at its maximum (unchanged to first order)")
        o.assume("The revenue effect follows from E for small price changes: dR/dP = Q(1 + E).")
    return o.done(headline=f"E = {out['elasticity']['text']} ({out['classification'].split(' (')[0]})", mode=mode, **out, **({"plot": plot} if plot else {}), **({"plot2": plot2} if plot2 else {}))


# ================================================================================================================ break-even
def op_break_even(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    fixed = frac(params, "fixedCosts", nonneg=True)
    price = frac(params, "price", positive=True)
    var = frac(params, "variableCost", nonneg=True)
    target = frac(params, "targetProfit", required=False) or Fraction(0)
    expected = frac(params, "expectedUnits", nonneg=True, required=False)
    o.assume("The price per unit and the variable cost per unit are constant, and everything produced is sold. Fixed costs do not change with volume. These are modelling assumptions.")
    cm = price - var
    C.require(cm > 0, f"Each unit sells for less than it costs to make (contribution margin {f.money(cm)['text']}), so there is no break-even volume.",
              "price", hint="The price must exceed the variable cost per unit.")
    be = fixed / cm
    o.step("Break-even volume", "units = fixed costs / (price − variable cost)", r"q^{*} = \frac{F}{p - v}")
    out: dict[str, Any] = {"breakEvenUnits": f.amount(be, places=4), "wholeUnitsNeeded": {"text": str(math.ceil(be)), "latex": str(math.ceil(be)), "value": math.ceil(be), "note": "rounded up to the next whole unit"},
                           "breakEvenRevenue": f.money(be * price), "contributionMarginPerUnit": f.money(cm), "contributionMarginRatio": f.percent(cm / price)}
    if target:
        out["unitsForTargetProfit"] = f.amount((fixed + target) / cm, places=4)
        out["revenueForTargetProfit"] = f.money((fixed + target) / cm * price)
    if expected is not None:
        out["profitAtExpectedUnits"] = f.money(expected * cm - fixed)
        if expected > 0:
            out["marginOfSafety"] = f.percent((expected - be) / expected, label="how far sales can fall below expectation before losses begin")
        if expected < be:
            o.warn("Expected sales are below the break-even volume, so the plan makes a loss.")
    top = max(float(be) * 2, float(expected or 0) * 1.2, 10.0)
    xs = [top * k / 40 for k in range(41)]
    plot = C.plot_block("Revenue and total cost", "Units", "Amount" + (f" ({f.code})" if f.has_currency else ""),
                        [{"label": "Revenue", "points": [[x, x * float(price)] for x in xs], "kind": "line"}, {"label": "Total cost", "points": [[x, float(fixed) + x * float(var)] for x in xs], "kind": "line"}],
                        description="Where the lines cross, profit is zero.", markers=[{"x": float(be), "y": float(be * price), "label": f"break-even {C.fmt_decimal(be, 1)} units"}])
    graph = C.graph_spec([{"type": "auto", "expr": "p*x", "color": "#2e9d6a"}, {"type": "auto", "expr": "F+v*x", "color": "#d6572b"}],
                         params=[C.slider("p", price, 0, max(1.0, float(price) * 3), max(0.01, float(price) / 100)), C.slider("F", fixed, 0, max(1.0, float(fixed) * 3), max(0.01, float(fixed) / 100)),
                                 C.slider("v", var, 0, max(1.0, float(var) * 3), max(0.01, float(var) / 100))], viewport=C.pad_view([0.0, top], [0.0, top * float(price)]))
    return o.done(**out, plot=plot, graph=graph)


# ================================================================================================================ cost / revenue / profit
def op_cost_revenue(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    Q = sp.Symbol("q", real=True)
    cost, cost_raw = sym_expr(params, "cost", ("q",))
    has_rev = params.get("revenue") not in (None, "")
    has_price = params.get("price") not in (None, "")
    if has_rev == has_price:
        raise BadRequest("Give either a revenue function R(q) or a price function P(q) (the price at which q units sell), but not both.", details={"field": "revenue"})
    if has_rev:
        rev, rev_raw = sym_expr(params, "revenue", ("q",))
        o.assume("Revenue R(q) is the function you typed.")
    else:
        price_expr, rev_raw = sym_expr(params, "price", ("q",))
        rev = sp.expand(Q * price_expr)
        rev_raw = f"({rev_raw})*q"
        o.assume("The price function P(q) is your inverse demand curve (the price at which q units sell); revenue is q·P(q).")
    o.assume("Cost, revenue and profit are exactly the functions you typed: they are a model, and nothing in them is estimated from data.")
    profit = sp.expand(rev - cost)
    mc, mr, mp_ = sp.diff(cost, Q), sp.diff(rev, Q), sp.diff(profit, Q)
    q0 = frac(params, "quantity", nonneg=True, required=False)
    out: dict[str, Any] = {"fixedCost": f.money(at(cost, "q", Fraction(0)))}
    o.step("Profit and its marginals", "profit = R − C;  marginal cost = dC/dq;  marginal revenue = dR/dq;  the optimum satisfies MR = MC.", r"\pi(q) = R(q) - C(q),\quad MR = \frac{dR}{dq},\ MC = \frac{dC}{dq}")
    out["marginalCostFunction"] = {"text": sp.sstr(mc).replace("**", "^"), "latex": sp.latex(mc)}
    out["marginalRevenueFunction"] = {"text": sp.sstr(mr).replace("**", "^"), "latex": sp.latex(mr)}
    out["profitFunction"] = {"text": sp.sstr(profit).replace("**", "^"), "latex": sp.latex(profit)}
    if q0 is not None:
        c0, r0 = at(cost, "q", q0), at(rev, "q", q0)
        out["atQuantity"] = {"quantity": f.amount(q0), "cost": f.money(c0), "revenue": f.money(r0), "profit": f.money(r0 - c0),
                             "marginalCost": f.money(at(mc, "q", q0)), "marginalRevenue": f.money(at(mr, "q", q0))}
        if q0 > 0:
            out["atQuantity"]["averageCost"] = f.money(c0 / q0)
            out["atQuantity"]["averageRevenue"] = f.money(r0 / q0)
    cands = [x for x in real_roots(mp_, "q", Fraction(0))]
    best = None
    notes = []
    for x in cands:
        second = at(sp.diff(profit, Q, 2), "q", x)
        if second < 0:
            val = at(profit, "q", x)
            if best is None or val > best[1]:
                best = (x, val)
        else:
            notes.append(x)
    if best is not None:
        x, val = best
        out["profitMaximum"] = {"quantity": f.amount(x, places=6), "profit": f.money(val), "marginalCost": f.money(at(mc, "q", x)), "marginalRevenue": f.money(at(mr, "q", x)),
                                "secondDerivative": f.amount(at(sp.diff(profit, Q, 2), "q", x), places=6), "note": "MR = MC and the profit curve is concave here (second derivative < 0)"}
        o.assume("The maximum is a local maximum of profit for q ≥ 0 found from MR = MC with a negative second derivative; check the ends of the range if quantity is capped.")
    elif cands:
        o.warn("MR = MC at q = " + ", ".join(C.fmt_decimal(x, 4) for x in cands) + ", but profit is not at a maximum there (second derivative ≥ 0).")
    else:
        o.warn("MR = MC has no solution for q ≥ 0 that SymPy could find, so no interior profit maximum is reported.")
    be = [x for x in real_roots(profit, "q", Fraction(0)) if x > 0]
    if be:
        out["breakEvenQuantities"] = [f.amount(x, places=6)["text"] for x in be]
    top = float(max([best[0] if best else Fraction(0)] + [q0 or Fraction(0)] + be)) * 1.6 or 100.0
    top = max(top, 10.0)
    xs = [top * k / 60 for k in range(61)]

    def series(e: sp.Expr, label: str) -> dict[str, Any]:
        pts = []
        for xv in xs:
            try:
                yv = float(e.subs(Q, sp.Float(xv, 30)))
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if math.isfinite(yv):
                pts.append([xv, yv])
        return {"label": label, "points": pts, "kind": "line"}

    plot = C.plot_block("Cost, revenue and profit", "Quantity q", "Amount", [series(cost, "Cost"), series(rev, "Revenue"), series(profit, "Profit")], zero_line=True,
                        markers=[{"x": float(best[0]), "y": float(best[1]), "label": "profit maximum"}] if best else [])
    plot2 = C.plot_block("Marginal cost and marginal revenue", "Quantity q", "Amount per unit", [series(mc, "Marginal cost"), series(mr, "Marginal revenue")], description="Profit is largest where the lines cross (MR = MC) and MR is falling through MC.")
    graph = C.graph_spec([{"type": "auto", "expr": graph_text(cost_raw, "q"), "color": "#d6572b"}, {"type": "auto", "expr": graph_text(rev_raw, "q"), "color": "#2e9d6a"}],
                         viewport=C.pad_view([0.0, top], [y for s in (series(cost, ""), series(rev, "")) for _, y in s["points"]]))
    head = (f"Profit is largest at q = {out['profitMaximum']['quantity']['text']}: {out['profitMaximum']['profit']['text']}" if "profitMaximum" in out
            else "Cost, revenue and profit with marginals")
    return o.done(headline=head, **out, plot=plot, plot2=plot2, graph=graph)


# ================================================================================================================ market equilibrium
def op_market_equilibrium(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    P = sp.Symbol("P", real=True)
    demand, d_raw = sym_expr(params, "demand", ("P",))
    supply, s_raw = sym_expr(params, "supply", ("P",))
    tax = frac(params, "tax", nonneg=True, required=False) or Fraction(0)
    control = C.choice(params, "mode", ("none", "ceiling", "floor"), "none")
    o.assume("Quantity demanded Qd(P) and quantity supplied Qs(P) are the functions you typed (a model). Markets are assumed to clear at the price where they are equal.")
    o.assume("Consumer surplus is the area under the demand curve above the price, producer surplus the area above the supply curve below the price; both are exact integrals of your functions.")
    o.step("Market clearing", "Qd(P) = Qs(P)", r"Q_d(P) = Q_s(P)")
    cands = [p for p in real_roots(demand - supply, "P", Fraction(0))]
    good = [p for p in cands if at(demand, "P", p) >= 0 and p > 0]
    if not good:
        raise BadRequest("Demand and supply do not meet at a positive price and quantity.", details={"field": "supply"},
                         hint="Check the signs: demand should fall with price and supply rise with price.")
    if len(good) > 1:
        o.warn("Demand and supply meet at more than one positive price: " + ", ".join(C.fmt_decimal(p, 4) for p in good) + ". The first one is analysed; with several crossings the market may have unstable equilibria.")
    p_star = good[0]
    q_star = at(demand, "P", p_star)
    dP, sP = sp.diff(demand, P), sp.diff(supply, P)
    if at(dP, "P", p_star) >= 0:
        o.warn("Demand does not slope downward at the equilibrium (dQd/dP ≥ 0).")
    if at(sP, "P", p_star) <= 0:
        o.warn("Supply does not slope upward at the equilibrium (dQs/dP ≤ 0).")

    def choke_demand(above: Fraction) -> Fraction | None:
        r = [x for x in real_roots(demand, "P", above)]
        return min(r) if r else None

    def floor_supply(below: Fraction) -> Fraction:
        """The price at which supply falls to zero (it can be negative for a supply curve such as 10 + 3P); 0 when supply never reaches zero."""
        r = [x for x in real_roots(supply, "P") if x <= below]
        return max(r) if r else Fraction(0)

    def integral(expr: sp.Expr, lo: Fraction, hi: Fraction | None) -> Fraction | None:
        a = sp.Rational(lo.numerator, lo.denominator)
        b = sp.oo if hi is None else sp.Rational(hi.numerator, hi.denominator)
        try:
            v = sp.integrate(expr, (P, a, b))
        except (NotImplementedError, ValueError, TypeError):
            return None
        if v in (sp.oo, -sp.oo, sp.zoo) or v.has(sp.nan, sp.oo, sp.zoo) or not v.is_real:
            return None
        return C.to_fraction(v)

    p_max = choke_demand(p_star)
    cs = integral(demand, p_star, p_max)
    p_min = floor_supply(p_star)
    ps = integral(supply, p_min, p_star)
    if p_min < 0:
        o.assume(f"Supply reaches zero at a price of {C.fmt_decimal(p_min, 4)} (below zero), so producer surplus is measured from there: the area above the supply curve from zero quantity.")
    out: dict[str, Any] = {"equilibriumPrice": f.money(p_star), "equilibriumQuantity": f.amount(q_star, places=6),
                           "priceElasticityOfDemand": f.amount(at(dP, "P", p_star) * p_star / q_star, places=4) if q_star else "undefined",
                           "priceElasticityOfSupply": f.amount(at(sP, "P", p_star) * p_star / q_star, places=4) if q_star else "undefined"}
    if cs is not None:
        out["consumerSurplus"] = f.money(cs)
    else:
        o.warn("Consumer surplus is not finite for this demand curve (it has no price at which demand reaches zero and the area does not converge).")
    if ps is not None:
        out["producerSurplus"] = f.money(ps)
    if cs is not None and ps is not None:
        out["totalSurplus"] = f.money(cs + ps)
    if p_max is not None:
        out["priceAtWhichDemandIsZero"] = f.money(p_max)
    if control != "none":
        pc = frac(params, "controlPrice", positive=True)
        qd, qs = at(demand, "P", pc), at(supply, "P", pc)
        if control == "ceiling":
            if pc >= p_star:
                o.warn("The price ceiling is at or above the equilibrium price, so it has no effect.")
            else:
                out["priceControl"] = {"traded": f.amount(min(qd, qs), places=6), "shortage": f.amount(qd - qs, places=6), "note": "at the ceiling people want more than is supplied; the quantity traded is what suppliers offer"}
        else:
            if pc <= p_star:
                o.warn("The price floor is at or below the equilibrium price, so it has no effect.")
            else:
                out["priceControl"] = {"traded": f.amount(min(qd, qs), places=6), "surplus": f.amount(qs - qd, places=6), "note": "at the floor suppliers offer more than people buy; the quantity traded is what is demanded"}
        o.assume("With a price control, the quantity traded is the smaller of demand and supply at the controlled price; nothing is assumed about who gets the goods.")
    if tax:
        o.assume("The per-unit tax is paid by sellers: suppliers receive the price minus the tax. Buyers pay P_b and sellers keep P_b − tax.")
        diff = demand - supply.subs(P, P - sp.Rational(tax.numerator, tax.denominator))
        roots = [p for p in real_roots(diff, "P", Fraction(0)) if p > tax and at(demand, "P", p) >= 0]
        if not roots:
            out["tax"] = {"note": "The tax is so large that trade stops (no positive quantity clears the market)."}
        else:
            pb = min(roots, key=lambda r: abs(r - p_star))
            qt = at(demand, "P", pb)
            seller = pb - tax
            cs_t = integral(demand, pb, p_max)
            ps_t = integral(supply, p_min, seller)
            tx: dict[str, Any] = {"buyersPay": f.money(pb), "sellersReceive": f.money(seller), "quantity": f.amount(qt, places=6), "taxRevenue": f.money(tax * qt),
                                  "buyersBear": f.percent((pb - p_star) / tax, label="share of the tax that buyers carry"), "sellersBear": f.percent((p_star - seller) / tax, label="share of the tax that sellers carry")}
            if cs is not None and ps is not None and cs_t is not None and ps_t is not None:
                tx["deadweightLoss"] = f.money(cs + ps - (cs_t + ps_t + tax * qt))
            out["tax"] = tx
    hi = float(p_max) if p_max is not None else float(p_star) * 2
    hi = max(hi, float(p_star) * 1.5)

    def curve(e: sp.Expr, label: str) -> dict[str, Any]:
        pts = []
        for k in range(61):
            pv = hi * k / 60
            try:
                qv = float(e.subs(P, sp.Float(pv, 30)))
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            if math.isfinite(qv) and qv >= 0:
                pts.append([qv, pv])
        return {"label": label, "points": pts, "kind": "line"}

    plot = C.plot_block("Supply and demand", "Quantity", "Price", [curve(demand, "Demand"), curve(supply, "Supply")],
                        markers=[{"x": float(q_star), "y": float(p_star), "label": f"equilibrium ({C.fmt_decimal(q_star, 2)}, {C.fmt_decimal(p_star, 2)})"}])
    return o.done(**out, plot=plot)
