"""Investment appraisal: ROI, CAGR, NPV, discounted cash flow, IRR (every root, not just one), payback, and growth scenarios.

Cash flows are numbered by period: flow 0 is *now*, flow k falls at the **end** of period k. A rate is the rate **per period**
unless a number of periods per year is given, in which case annual equivalents are shown as well.

IRR is the root of  Σ c_k·x^k = 0  with  x = 1/(1+r). That is a polynomial, so its real roots can be isolated exactly (sympy) and then
refined to 50+ digits; the number of sign changes in the cash flows (Descartes' rule) says how many roots to expect at most. An IRR is
never reported as "the" answer when more than one exists.
"""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

import mpmath as mp
import sympy as sp

from ...core.numerical.context import Settings
from ...errors import BadRequest
from . import core as C
from .core import Result, frac, from_mp, hp, power, rate, to_float, to_mp
from .interest import annuity_factors, freq, one_empty
from .loans import cell, term

EXACT_DEGREE = 80                                    # beyond this, IRR roots are found by scanning instead of exact isolation
SCAN_POINTS = 6000


# ---------------------------------------------------------------------------------------------------------------------- helpers
def flows_of(params: dict, key: str = "flows", minimum: int = 2) -> list[Fraction]:
    flows = C.numbers_list(params, key, minimum=minimum)
    if all(c == 0 for c in flows):
        raise BadRequest("All the cash flows are zero.", details={"field": key})
    return flows


def npv_of(flows: list[Fraction], r: Fraction) -> Fraction:
    """Exact net present value at the periodic rate ``r``."""
    C.require(r > -1, "The discount rate must be greater than −100 %", "rate")
    d = 1 + r
    total = Fraction(0)
    f = Fraction(1)
    for c in flows:
        total += c / f
        f *= d
    return total


def npv_float(flows: list[float], r: float) -> float:
    d = 1.0 + r
    return sum(c / d ** k for k, c in enumerate(flows))


def sign_changes(flows: list[Fraction]) -> int:
    signs = [1 if c > 0 else -1 for c in flows if c != 0]
    return sum(1 for a, b in zip(signs, signs[1:]) if a != b)


def flows_table(f: C.Fmt, flows: list[Fraction], r: Fraction | None) -> list[dict[str, Any]]:
    rows, cum, dcum = [], Fraction(0), Fraction(0)
    d = Fraction(1)
    show = f.places
    for k, c in enumerate(flows):
        pv = c / d if r is not None else None
        cum += c
        row: dict[str, Any] = {"period": k, "cashFlow": cell(c, show)}
        if r is not None:
            dcum += pv
            row.update(discountFactor={"text": C.fmt_decimal(1 / d, 6), "latex": ""}, presentValue=cell(pv, show), cumulative=cell(cum, show), discountedCumulative=cell(dcum, show))
        else:
            row["cumulative"] = cell(cum, show)
        rows.append(row)
        if r is not None:
            d *= 1 + r
    return rows


def per_year_rates(f: C.Fmt, r: Fraction, per: int) -> dict[str, Any]:
    if per == 1:
        return {}
    return {"annualEffective": f.percent(power(1 + r, Fraction(per)) - 1, label=f"(1 + periodic rate)^{per} − 1"), "annualNominal": f.percent(r * per, label=f"periodic rate × {per}")}


# ================================================================================================================ ROI
def op_roi(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    cost = frac(params, "cost", positive=True)
    value = frac(params, "value", nonneg=True)
    income = frac(params, "income", nonneg=True, required=False) or Fraction(0)
    years = frac(params, "years", positive=True, required=False)
    o.assume("ROI = (final value + income received − amount invested) / amount invested. It ignores when the money moves, so it says nothing about the time value of money.")
    gain = value + income - cost
    roi = gain / cost
    o.step("Return on investment", "ROI = (value + income − cost) / cost", r"\mathrm{ROI} = \frac{V + I - C}{C}")
    out: dict[str, Any] = {"netGain": f.money(gain), "roi": f.percent(roi), "multiple": f.amount(1 + roi, unit="× the amount invested"), "totalReturned": f.money(value + income)}
    if years is not None:
        if 1 + roi > 0:
            out["annualizedRoi"] = f.percent(power(1 + roi, 1 / years, "years") - 1, label="the constant yearly rate that gives the same total")
            o.assume("The annualized return assumes steady compound growth over the whole period (it is the CAGR of the total return).")
        else:
            o.warn("The whole amount was lost, so no annualized rate exists (it would be −100 %).")
            out["annualizedRoi"] = f.percent(Fraction(-1))
        out["simpleAnnualRoi"] = f.percent(roi / years, label="ROI divided by the number of years (no compounding)")
    if roi < -1:
        o.warn("A loss larger than the amount invested is possible only with leverage or short positions.")
    return o.done(**out)


# ================================================================================================================ CAGR
def op_cagr(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    solve = one_empty(params, [("begin", "beginning value"), ("end", "ending value"), ("rate", "growth rate"), ("years", "years")], default="rate")
    b = frac(params, "begin", positive=True, required=False) if solve != "begin" else None
    e = frac(params, "end", positive=True, required=False) if solve != "end" else None
    g = rate(params, "rate", required=False) if solve != "rate" else None
    t = frac(params, "years", positive=True, required=False) if solve != "years" else None
    for key, v in (("begin", b), ("end", e), ("rate", g), ("years", t)):
        if key != solve and v is None:
            raise BadRequest(f"'{key}' is required", details={"field": key})
    o.assume("CAGR is the constant yearly growth rate that takes the beginning value to the ending value: (end / begin)^(1/years) − 1. It smooths the path and says nothing about the years in between.")
    o.step("Compound annual growth rate", "CAGR = (end / begin)^(1/years) − 1", r"\mathrm{CAGR} = \left(\frac{V_{\mathrm{end}}}{V_{\mathrm{begin}}}\right)^{1/t} - 1")
    if solve == "rate":
        g = power(e / b, 1 / t, "end") - 1
    elif solve == "end":
        C.require(g > -1, "A growth rate of −100 % or less leaves nothing", "rate")
        e = b * power(1 + g, t, "years")
    elif solve == "begin":
        C.require(g > -1, "A growth rate of −100 % or less leaves nothing", "rate")
        b = e / power(1 + g, t, "years")
    else:
        C.require(g != 0, "With 0 % growth the value never changes, so the time cannot be found.", "rate")
        C.require(g > -1, "A growth rate of −100 % or less leaves nothing", "rate")
        C.require(e != b, "The ending value equals the beginning value, so no time has passed.", "end")
        t = C.ln(e / b) / C.ln(1 + g)
        C.require(t > 0, "At this rate the value moves away from the target.", "end")
    shown = {"begin": f.amount(b), "end": f.amount(e), "rate": f.percent(g, label="per year, compounded yearly"), "years": f.amount(t, unit="years")}
    names = {"begin": "beginningValue", "end": "endingValue", "rate": "cagr", "years": "years"}
    out: dict[str, Any] = {names[solve]: shown[solve]}
    out.update({names[k]: shown[k] for k in shown if k != solve})
    out["totalGrowth"] = f.percent(e / b - 1)
    out["simpleAverageGrowth"] = f.percent((e / b - 1) / t, label="total growth ÷ years: always above the CAGR for positive growth")
    pts = [(float(to_float(t) * k / 40), to_float(b * power(1 + g, t * k / 40, "years"))) for k in range(41)]
    plot = C.plot_block("Smoothed growth path", "Years", "Value", [{"label": "Constant-rate path", "points": [[x, y] for x, y in pts], "kind": "line"}],
                        description="The steady path at the compound rate. Actual values in between will differ.")
    graph = C.graph_spec([{"type": "auto", "expr": "B*(1+g)^x", "color": "#b89b00"}], params=[C.slider("B", b, 0, max(1.0, to_float(b) * 5), max(0.01, to_float(b) / 100)), C.slider("g", g, -0.5, 0.5, 0.001)],
                         viewport=C.pad_view([0.0, to_float(t)], [y for _, y in pts]))
    return o.done(**out, plot=plot, graph=graph)


# ================================================================================================================ NPV
def npv_profile(flows: list[Fraction], lo: float, hi: float, points: int = 90) -> list[tuple[float, float]]:
    fl = [to_float(c) for c in flows]
    out = []
    for k in range(points + 1):
        r = lo + (hi - lo) * k / points
        try:
            v = npv_float(fl, r)
        except (OverflowError, ZeroDivisionError):
            continue
        if math.isfinite(v):
            out.append((r * 100, v))
    return out


def op_npv(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    flows = flows_of(params)
    r = rate(params, "rate")
    per = freq(params, "perYear", 1)
    note = C.rate_note(r * 100)
    if note:
        o.warn(note)
    o.assume("The first cash flow is at time 0 (now, not discounted); flow k is at the end of period k. The discount rate is per period.")
    o.assume("Negative numbers are money paid out, positive numbers money received.")
    value = npv_of(flows, r)
    o.step("Net present value", "NPV = Σ c_k / (1 + r)^k", r"\mathrm{NPV} = \sum_{k=0}^{n} \frac{c_k}{(1+r)^{k}}")
    d = [(1 + r) ** k for k in range(len(flows))]
    pv_in = sum((c / d[k] for k, c in enumerate(flows) if c > 0), Fraction(0))
    pv_out = sum((c / d[k] for k, c in enumerate(flows) if c < 0), Fraction(0))
    out: dict[str, Any] = {"npv": f.money(value), "presentValueOfInflows": f.money(pv_in), "presentValueOfOutflows": f.money(pv_out)}
    if flows[0] < 0:
        later_in = sum((c / d[k] for k, c in enumerate(flows) if k > 0 and c > 0), Fraction(0))
        out["profitabilityIndex"] = f.amount(later_in / -flows[0], places=4)
    out["undiscountedSum"] = f.money(sum(flows, Fraction(0)))
    out["verdict"] = ("positive: at this discount rate the cash flows are worth more than zero today" if value > 0 else
                      "zero: the cash flows are exactly worth nothing at this rate (this rate is an IRR)" if value == 0 else
                      "negative: at this discount rate the cash flows are worth less than zero today")
    out.update(per_year_rates(f, r, per))
    roots, _, _ = irr_roots(flows)
    hi = max([0.3] + [min(5.0, float(x) * 1.3 + 0.05) for x in roots])
    lo = min([0.0] + [max(-0.9, float(x) - 0.1) for x in roots])
    prof = npv_profile(flows, lo, hi)
    markers = [{"x": float(x) * 100, "y": 0.0, "label": f"IRR {C.fmt_decimal(x * 100, 2)} %"} for x in roots[:4]]
    plot = C.plot_block("NPV against the discount rate", "Discount rate (% per period)", "NPV" + (f" ({f.code})" if f.has_currency else ""), [{"label": "NPV", "points": [[x, y] for x, y in prof], "kind": "line"}],
                        description="Net present value at each discount rate. Where the line crosses zero is an internal rate of return.", zero_line=True, markers=markers)
    graph = C.graph_spec([{"type": "scatter", "data": C.points_text(prof), "color": "#b89b00", "label": "NPV"}], viewport=C.pad_view([x for x, _ in prof], [y for _, y in prof]))
    plot2 = C.plot_block("Cash flows", "Period", "Cash flow", [{"label": "Cash flow", "points": [[k, to_float(c)] for k, c in enumerate(flows)], "kind": "scatter"},
                                                                 {"label": "Cumulative", "points": [[k, to_float(sum(flows[:k + 1], Fraction(0)))] for k in range(len(flows))], "kind": "line"}],
                         description="Each period's cash flow and the running total (undiscounted).", zero_line=True)
    return o.done(headline=f"NPV = {out['npv']['text']}", **out, table=flows_table(f, flows, r), plot=plot, plot2=plot2, graph=graph)


# ================================================================================================================ DCF
def op_dcf(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    r = rate(params, "rate")
    C.require(r > -1, "The discount rate must be greater than −100 %", "rate")
    if params.get("flows") not in (None, ""):
        flows = C.numbers_list(params, "flows", minimum=1)
        n = len(flows)
        o.assume("The forecast cash flows were entered by you, one per year, the first at the end of year 1.")
    else:
        first = frac(params, "firstFlow")
        growth = rate(params, "growth", required=False) or Fraction(0)
        n = C.count(params, "years", lo=1, hi=100)
        C.require(growth > -1, "The growth rate must be greater than −100 %", "growth")
        flows = [first * (1 + growth) ** k for k in range(n)]
        o.assume(f"The cash flow in year 1 is {f.money(first)['text']} and then grows by {C.fmt_decimal(growth * 100, 4)} % a year (an assumed model, not a forecast).")
    method = C.choice(params, "mode", ("none", "gordon", "multiple"), "none")
    net_debt = frac(params, "netDebt", required=False) or Fraction(0)
    o.assume("Every cash flow is at the end of its year; the terminal value, if any, is at the end of year " + str(n) + ".")
    tv = Fraction(0)
    if method == "gordon":
        g_t = rate(params, "terminalGrowth", default="2")
        C.require(r > g_t, "The discount rate must be greater than the terminal growth rate, otherwise the terminal value is infinite.", "terminalGrowth")
        tv = flows[-1] * (1 + g_t) / (r - g_t)
        o.assume(f"Terminal value by the Gordon growth formula: the last flow grows forever by {C.fmt_decimal(g_t * 100, 4)} % a year. This is an assumption about the distant future.")
        o.step("Terminal value", "TV = CF_n (1+g) / (r − g)", r"TV = \frac{CF_n (1+g)}{r - g}")
    elif method == "multiple":
        mult = frac(params, "exitMultiple", positive=True)
        tv = flows[-1] * mult
        o.assume(f"Terminal value = {C.fmt_decimal(mult, 4).rstrip('0').rstrip('.')} × the last year's cash flow (an assumed exit multiple).")
    d = [(1 + r) ** k for k in range(1, n + 1)]
    pv_flows = sum((c / d[k] for k, c in enumerate(flows)), Fraction(0))
    pv_tv = tv / d[-1]
    ev = pv_flows + pv_tv
    o.step("Discount each flow", "Value = Σ CF_t / (1+r)^t  +  TV / (1+r)^n", r"V = \sum_{t=1}^{n}\frac{CF_t}{(1+r)^t} + \frac{TV}{(1+r)^n}")
    out: dict[str, Any] = {"presentValueOfForecastFlows": f.money(pv_flows)}
    if method != "none":
        out.update(terminalValue=f.money(tv), presentValueOfTerminalValue=f.money(pv_tv))
    out["totalValue"] = f.money(ev)
    if net_debt:
        out["valueAfterNetDebt"] = f.money(ev - net_debt)
    if method != "none" and ev > 0:
        share = pv_tv / ev
        out["terminalShareOfValue"] = f.percent(share, label="how much of the value rests on the assumed terminal value")
        if share > Fraction(3, 4):
            o.warn("More than 75 % of the value comes from the terminal value, so the result is dominated by the long-run assumption.")
    rows = []
    for k, c in enumerate(flows):
        rows.append({"year": k + 1, "cashFlow": cell(c, f.places), "discountFactor": {"text": C.fmt_decimal(1 / d[k], 6), "latex": ""}, "presentValue": cell(c / d[k], f.places)})
    plot = C.plot_block("Forecast cash flows and their present values", "Year", "Amount", [{"label": "Cash flow", "points": [[k + 1, to_float(c)] for k, c in enumerate(flows)], "kind": "line"},
                                                                                       {"label": "Present value", "points": [[k + 1, to_float(c / d[k])] for k, c in enumerate(flows)], "kind": "line"}],
                        description="The cash flow each year and what it is worth today.", zero_line=True)
    return o.done(headline=f"Total value = {out['totalValue']['text']}", **out, method=method, table=rows, plot=plot)


# ================================================================================================================ IRR
def _poly_ints(flows: list[Fraction]) -> tuple[list[int], int]:
    """Integer coefficients of Σ c_k x^k with the factor x^m (m leading zero flows) and the highest zero flows removed."""
    lo = next(k for k, c in enumerate(flows) if c != 0)
    hi = max(k for k, c in enumerate(flows) if c != 0)
    core = flows[lo:hi + 1]
    lcm = 1
    for c in core:
        lcm = lcm * c.denominator // math.gcd(lcm, c.denominator)
    return [int(c * lcm) for c in core], lo


def irr_roots(flows: list[Fraction]) -> tuple[list[Fraction], str, int]:
    """(all rates above −100 % at which NPV is zero, ascending; how they were found; sign changes in the flows)."""
    changes = sign_changes(flows)
    if changes == 0:
        return [], "sign", 0
    ints, _ = _poly_ints(flows)
    degree = len(ints) - 1
    if degree < 1:
        return [], "exact", changes
    if degree <= EXACT_DEGREE:
        x = sp.Symbol("x")
        poly = sp.Poly(list(reversed(ints)), x, domain="ZZ")
        poly = poly.sqf_part()
        xs: list[Fraction] = []
        for (a, b), _ in poly.intervals(inf=0):
            a, b = Fraction(int(a.p), int(a.q)), Fraction(int(b.p), int(b.q))
            if a == b:
                root = a
            else:                                                                                     # refine the isolating interval to 1e-50 in x, exactly
                lo_r, hi_r = poly.refine_root(sp.Rational(a.numerator, a.denominator), sp.Rational(b.numerator, b.denominator), eps=sp.Rational(1, 10 ** 50))
                root = (Fraction(int(lo_r.p), int(lo_r.q)) + Fraction(int(hi_r.p), int(hi_r.q))) / 2
            if root > 0:
                xs.append(root)
        rates = sorted(1 / v - 1 for v in xs)
        return rates, "exact", changes
    return _scan_roots(flows), "scan", changes


def _scan_roots(flows: list[Fraction]) -> list[Fraction]:
    fl = [to_float(c) for c in flows]
    grid = [math.expm1(math.log(1e-3) + (math.log(1e3) - math.log(1e-3)) * k / SCAN_POINTS) for k in range(SCAN_POINTS + 1)]     # r from −99.9 % to ~100000 %
    grid = [r for r in grid if r > -0.999 and r < 1e3]
    found: list[Fraction] = []
    prev_r, prev_v = grid[0], npv_float(fl, grid[0])
    for r in grid[1:]:
        v = npv_float(fl, r)
        if prev_v == 0:
            found.append(Fraction(prev_r))
        elif (prev_v > 0) != (v > 0) and v != 0:
            with hp():
                root = C.bisect(lambda z: sum(to_mp(c) / (1 + z) ** k for k, c in enumerate(flows)), mp.mpf(prev_r), mp.mpf(r))
            if root is not None:
                found.append(from_mp(root))
        prev_r, prev_v = r, v
    return found


def mirr_of(flows: list[Fraction], finance: Fraction, reinvest: Fraction) -> Fraction | None:
    n = len(flows) - 1
    if n < 1:
        return None
    neg = sum((c / (1 + finance) ** k for k, c in enumerate(flows) if c < 0), Fraction(0))
    pos = sum((c * (1 + reinvest) ** (n - k) for k, c in enumerate(flows) if c > 0), Fraction(0))
    if neg == 0 or pos == 0:
        return None
    return power(pos / -neg, Fraction(1, n)) - 1


def op_irr(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    flows = flows_of(params)
    per = freq(params, "perYear", 1)
    o.assume("The first cash flow is at time 0; flow k is at the end of period k. The IRR is per period unless an annual form is shown.")
    o.assume("IRR is every rate above −100 % at which the net present value is zero. It implicitly assumes each flow can be reinvested at the IRR itself.")
    changes = sign_changes(flows)
    roots, how, _ = irr_roots(flows)
    o.step("Characteristic equation", "Σ c_k x^k = 0 with x = 1/(1+r): real roots x > 0 are internal rates of return.", r"\sum_{k=0}^{n} c_k\,x^{k} = 0,\quad x = \frac{1}{1+r}")
    o.step("How many roots to expect", f"The cash flows change sign {changes} time{'s' if changes != 1 else ''}. By Descartes' rule there are at most {changes} such rate{'s' if changes != 1 else ''}, and the number found differs from that by an even number.")
    out: dict[str, Any] = {"signChanges": changes, "numberOfIrrs": len(roots)}
    if how == "sign":
        o.warn("The cash flows never change sign (all are positive or all negative), so no IRR exists.")
        out["status"] = "no IRR exists: the cash flows have no sign change"
    elif how == "scan" and not roots:
        o.warn("No sign change of NPV was found between −99.9 % and 100 000 % by scanning (a double root, or one outside this range, would be missed).")
        out["status"] = "no IRR found by scanning"
    elif not roots:
        o.warn("The cash flows change sign, but NPV never reaches zero at a rate above −100 %, so there is no IRR.")
        out["status"] = "no IRR exists above −100 %"
    else:
        if how == "scan":
            o.warn(f"With {len(flows)} cash flows the roots were found by scanning 6000 rates from −99.9 % to 100 000 %, not by exact isolation. Two roots closer than the grid spacing, or a double root, could be missed.")
        else:
            o.assume("The roots were isolated exactly with Sturm sequences (sympy) and then refined to about 50 digits, so none is missed and none is spurious.")
        shown = [f.percent(x) for x in roots]
        if len(roots) == 1:
            out["status"] = "one IRR" + (" (the flows change sign more than once, but only one root is above −100 %)" if changes > 1 else "")
            out["irr"] = f.percent(roots[0], label="per period")
            out.update(per_year_rates(f, roots[0], per))
        else:
            out["status"] = f"{len(roots)} IRRs: the IRR is not unique for these cash flows, so no single IRR should be quoted"
            out["irrs"] = [x["text"] for x in shown]
            o.warn(f"The cash flows have {len(roots)} different internal rates of return. Any one of them taken alone would be misleading; compare the projects with NPV at a stated discount rate instead.")
            if per != 1:
                out["irrsAnnualEffective"] = [f.percent(power(1 + x, Fraction(per)) - 1)["text"] for x in roots]
        if changes > 1 and len(roots) == 1:
            o.warn(f"The cash flows change sign {changes} times, which can produce several IRRs. Exactly one exists here.")
        worst = Fraction(0)
        for x in roots:
            gross = sum((abs(c) / (1 + x) ** k for k, c in enumerate(flows)), Fraction(0))        # size of the terms that cancel
            worst = max(worst, abs(npv_of(flows, x)) / gross)
        out["largestRelativeResidual"] = f.amount(worst, places=2) if worst == 0 else {"text": f"{float(worst):.2e}", "latex": f"{float(worst):.2e}", "value": float(worst)}
        out["checkNpvAtIrr"] = ("NPV at each IRR is zero to within 1e-20 of the size of the cash flows being added" if worst < Fraction(1, 10**20)
                                else "NPV at an IRR is not zero to the expected precision: do not trust it")
    fin = rate(params, "financeRate", required=False)
    rei = rate(params, "reinvestRate", required=False)
    if fin is not None or rei is not None:
        fin = fin if fin is not None else (rei if rei is not None else Fraction(0))
        rei = rei if rei is not None else fin
        m = mirr_of(flows, fin, rei)
        if m is None:
            o.warn("The modified IRR needs both money paid out and money received.")
        else:
            out["modifiedIrr"] = f.percent(m, label=f"outflows discounted at {C.fmt_decimal(fin * 100, 4)} %, inflows compounded forward at {C.fmt_decimal(rei * 100, 4)} %")
            o.assume("The modified IRR (MIRR) discounts the outflows at the finance rate and compounds the inflows at the reinvestment rate to the end; it is always unique.")
    hi = max([0.3] + [min(5.0, float(x) * 1.3 + 0.05) for x in roots])
    lo = min([0.0] + [max(-0.9, float(x) - 0.1) for x in roots])
    prof = npv_profile(flows, lo, hi)
    markers = [{"x": float(x) * 100, "y": 0.0, "label": f"{C.fmt_decimal(x * 100, 2)} %"} for x in roots[:5]]
    plot = C.plot_block("NPV against the discount rate", "Discount rate (% per period)", "NPV", [{"label": "NPV", "points": [[x, y] for x, y in prof], "kind": "line"}],
                        description="The IRRs are where the line crosses zero (marked).", zero_line=True, markers=markers)
    graph = C.graph_spec([{"type": "scatter", "data": C.points_text(prof), "color": "#b89b00", "label": "NPV"}], viewport=C.pad_view([x for x, _ in prof], [y for _, y in prof]))
    if len(roots) == 1:
        head = f"IRR = {C.fmt_decimal(roots[0] * 100, 4)} % per period"
    elif roots:
        head = f"{len(roots)} IRRs (not unique): " + "; ".join(f"{C.fmt_decimal(x * 100, 4)} %" for x in roots[:4])
    else:
        head = out["status"]
    return o.done(headline=head, **out, method=how, plot=plot, graph=graph)


# ================================================================================================================ payback
def op_payback(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    flows = flows_of(params)
    r = rate(params, "rate", required=False)
    per = freq(params, "perYear", 1)
    C.require(flows[0] < 0, "The first cash flow should be an investment (negative); otherwise there is nothing to pay back.", "flows")
    o.assume("The first flow is at time 0; flow k is at the end of period k. Within a period, cash is assumed to arrive evenly, so the payback moment is found by straight-line interpolation.")

    def payback(series: list[Fraction]) -> tuple[Fraction | None, int]:
        cum = Fraction(0)
        crossings = 0
        first: Fraction | None = None
        for k, c in enumerate(series):
            prev = cum
            cum += c
            if k > 0 and prev < 0 <= cum:
                crossings += 1
                if first is None:
                    first = (k - 1) + (-prev) / c
        return first, crossings

    simple, cross = payback(flows)
    out: dict[str, Any] = {}
    unit_lbl = "periods"

    def put(key: str, v: Fraction | None) -> None:
        out[key] = f.amount(v, places=4, unit=unit_lbl) if v is not None else "not within the cash flows given"

    put("paybackPeriod", simple)
    if simple is not None and per != 1:
        out["paybackYears"] = f.amount(simple / per, places=4, unit="years")
    disc = None
    if r is not None:
        C.require(r > -1, "The discount rate must be greater than −100 %", "rate")
        pv = [c / (1 + r) ** k for k, c in enumerate(flows)]
        disc, _ = payback(pv)
        put("discountedPaybackPeriod", disc)
        if disc is not None and per != 1:
            out["discountedPaybackYears"] = f.amount(disc / per, places=4, unit="years")
        o.assume("Discounted payback uses each flow's present value at the given rate per period.")
        if simple is not None and disc is None:
            o.warn("The investment pays back in nominal terms but not once the flows are discounted.")
    if cross > 1:
        o.warn("The running total crosses zero more than once (it falls back below zero later); the first crossing is shown.")
    cum_last = sum(flows, Fraction(0))
    out["totalUndiscounted"] = f.money(cum_last)
    rows = flows_table(f, flows, r)
    cum, cum_d = [], []
    c_run = Fraction(0)
    d_run = Fraction(0)
    for k, c in enumerate(flows):
        c_run += c
        cum.append((float(k), to_float(c_run)))
        if r is not None:
            d_run += c / (1 + r) ** k
            cum_d.append((float(k), to_float(d_run)))
    series = [{"label": "Cumulative cash flow", "points": [[x, y] for x, y in cum], "kind": "line"}]
    if r is not None:
        series.append({"label": "Discounted cumulative", "points": [[x, y] for x, y in cum_d], "kind": "line"})
    markers = []
    if simple is not None:
        markers.append({"x": to_float(simple), "y": 0.0, "label": f"payback {C.fmt_decimal(simple, 2)}"})
    plot = C.plot_block("Cumulative cash flow", "Period", "Cumulative amount", series, description="Payback is where the running total reaches zero.", zero_line=True, markers=markers)
    pb = out["paybackPeriod"]
    return o.done(headline=("Payback after " + pb["text"]) if isinstance(pb, dict) else "No payback within the cash flows given", **out, table=rows, plot=plot)


# ================================================================================================================ growth scenarios
def op_investment_growth(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    initial = frac(params, "initial", nonneg=True)
    contribution = frac(params, "contribution", nonneg=True, required=False) or Fraction(0)
    n, per = term(params)
    years = Fraction(n, per)
    due = C.choice(params, "timing", ("end", "begin"), "end") == "begin"
    rates = C.numbers_list(params, "rates", maximum=8)
    rates = [x / 100 for x in rates]
    infl = rate(params, "inflation", required=False)
    C.require(initial > 0 or contribution > 0, "Give a starting amount or a regular contribution", "initial")
    o.assume(f"Each scenario is a constant nominal annual rate, compounded {per} times a year; contributions of {f.money(contribution)['text']} are made at the {'beginning' if due else 'end'} of each period.")
    o.assume("These are what-if scenarios with assumed constant rates, not forecasts. Real returns vary from year to year.")
    if infl is not None:
        C.require(infl > -1, "Inflation must be greater than −100 %", "inflation")
        o.assume(f"Real values are the nominal values divided by (1 + {C.fmt_decimal(infl * 100, 4)} %)^years: purchasing power in today's money.")
    contributed = initial + contribution * n
    rows, series, real_series = [], [], []
    for sc in rates:
        i = sc / per
        C.require(i > -1, "A rate of −100 % a year or less leaves nothing", "rates")
        pts, rpts = [], []
        for y in range(0, int(math.ceil(float(years))) + 1):
            k = min(n, y * per)
            a, s = annuity_factors(i, k) if k > 0 else (Fraction(0), Fraction(0))
            val = initial * (1 + i) ** k + contribution * s * ((1 + i) if due else 1)
            tt = Fraction(k, per)
            pts.append((float(tt), to_float(val)))
            if infl is not None:
                rpts.append((float(tt), to_float(val / power(1 + infl, tt, "inflation"))))
        end = pts[-1][1]
        a, s = annuity_factors(i, n)
        final = initial * (1 + i) ** n + contribution * s * ((1 + i) if due else 1)
        row: dict[str, Any] = {"annualRate": f.percent(sc), "finalValue": cell(final, f.places), "totalContributed": cell(contributed, f.places), "growth": cell(final - contributed, f.places)}
        if infl is not None:
            row["finalValueReal"] = cell(final / power(1 + infl, years, "inflation"), f.places)
        rows.append(row)
        label = f"{C.fmt_decimal(sc * 100, 2).rstrip('0').rstrip('.')} %"
        series.append({"label": label, "points": [[x, y] for x, y in pts], "kind": "line"})
        if infl is not None:
            real_series.append({"label": label + " (real)", "points": [[x, y] for x, y in rpts], "kind": "line", "dashed": True})
    o.step("Value of a lump sum plus regular contributions", "FV = P(1+i)^n + PMT · [(1+i)^n − 1]/i", r"FV = P(1+i)^{n} + PMT\,\frac{(1+i)^{n}-1}{i}")
    plot = C.plot_block("Growth by scenario", "Years", "Value" + (f" ({f.code})" if f.has_currency else ""), series + real_series, description="Balance at each year-end for each assumed rate" + ("; dashed lines are in today's money." if infl is not None else "."))
    graph = C.graph_spec([{"type": "scatter", "data": C.points_text([(x, y) for x, y in [(p[0], p[1]) for p in s["points"]]]), "color": c, "label": s["label"]}
                          for s, c in zip(series, ["#b89b00", "#2f6fdb", "#d6572b", "#2e9d6a", "#8a5cc2", "#c2557f", "#4f8f9d", "#7a7a7a"])],
                         viewport=C.pad_view([p[0] for s in series for p in s["points"]], [p[1] for s in series for p in s["points"]]))
    return o.done(headline="Final value: " + " · ".join(f"{C.fmt_decimal(sc * 100, 2).rstrip('0').rstrip('.')} % → {r['finalValue']['text']}" for sc, r in zip(rates, rows)), scenarios=rows, years=f.amount(years, unit="years"), plot=plot, graph=graph)
