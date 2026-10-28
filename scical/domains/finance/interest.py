"""Interest and the time value of money: simple, compound and continuous interest, rate conversion, real rates, annuities, perpetuities.

Every formula here is a mathematical identity; nothing is a market assumption. The rate fields are percentages per year (``5`` = 5 %)
unless the field says "per period". All values are exact ``Fraction`` s; a step that is not rational (a power with a fractional
exponent, a logarithm, an exponential) is done with 60 digits and carried on as a 55-digit exact decimal (see ``core``).
"""
from __future__ import annotations

import math
from fractions import Fraction

import mpmath as mp

from ...core.numerical.context import Settings
from ...errors import BadRequest
from . import core as C
from .core import Result, exp_f, frac, from_mp, hp, ln, power, rate, to_float, to_mp

FREQUENCIES = (1, 2, 4, 12, 52, 365)
FREQ_NAMES = {1: "annually", 2: "semi-annually", 4: "quarterly", 12: "monthly", 52: "weekly", 365: "daily"}
MAX_FREQ = 8760
MAX_CURVE = 1200


def one_empty(params: dict, keys: list[tuple[str, str]], default: str | None = None) -> str:
    """Which of the named fields is empty (that is the one solved for). Exactly one must be; with none empty, ``default`` is solved for."""
    empty = [k for k, _ in keys if params.get(k) in (None, "") or (isinstance(params.get(k), str) and not params[k].strip())]
    if len(empty) == 1:
        return empty[0]
    if not empty and default:
        return default
    labels = ", ".join(label for _, label in keys)
    raise BadRequest(f"Leave exactly one of {labels} empty: that is the value to calculate.", hint="Fill in all the others.")


def freq(params: dict, key: str = "freq", default: int = 12) -> int:
    n = C.count(params, key, lo=1, hi=MAX_FREQ, default=default, required=False)
    return default if n is None else n


def growth_curve(pv: Fraction, r: Fraction, n: int | None, years: Fraction, kind: str, points: int = 48) -> list[tuple[float, float]]:
    """(year, balance) of a deposit for the small chart. ``n`` is None for simple and continuous interest."""
    out: list[tuple[float, float]] = []
    with hp():
        pv_m, r_m = to_mp(pv), to_mp(r)
        for k in range(points + 1):
            tm = to_mp(years) * k / points
            if kind == "simple":
                v = pv_m * (1 + r_m * tm)
            elif kind == "continuous":
                v = pv_m * mp.exp(r_m * tm)
            else:
                base = 1 + r_m / n                                                         # type: ignore[operator]
                v = pv_m * mp.power(base, n * tm) if base > 0 else mp.nan                   # type: ignore[operator]
            if mp.isfinite(v):                                                              # a negative growth factor has no real value at a fractional power
                out.append((float(tm), float(v)))
    return out


# ================================================================================================================ interest
def op_interest(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    kind = C.choice(params, "mode", ("simple", "compound", "continuous"), "compound")
    solve = one_empty(params, [("pv", "principal"), ("fv", "future value"), ("rate", "rate"), ("years", "time")], default="fv")
    pv = frac(params, "pv", positive=True, required=False) if solve != "pv" else None
    fv = frac(params, "fv", positive=True, required=False) if solve != "fv" else None
    r = rate(params, "rate", required=False) if solve != "rate" else None
    t = frac(params, "years", positive=True, required=False) if solve != "years" else None
    for key, value in (("pv", pv), ("fv", fv), ("rate", r), ("years", t)):
        if key != solve and value is None:
            raise BadRequest(f"'{key}' is required", details={"field": key})
    n = freq(params) if kind == "compound" else None
    if r is not None:
        note = C.rate_note(r * 100)
        if note:
            o.warn(note)
    o.assume({"simple": "Simple interest: interest is paid on the original principal only and is never added to it.",
              "compound": f"Compound interest: the nominal annual rate is compounded {n} time{'s' if n != 1 else ''} per year; interest is added to the balance at the end of each period.",
              "continuous": "Continuous compounding: the limit of compounding infinitely often, FV = PV·e^(rt), at a continuously compounded annual rate."}[kind])
    o.assume("Time is in years. Rates are percentages per year: 5 means 5 %.")
    formula = {"simple": r"FV = PV\,(1 + r\,t)", "compound": r"FV = PV\left(1 + \frac{r}{n}\right)^{n t}", "continuous": r"FV = PV\,e^{r t}"}[kind]
    o.step("Formula", {"simple": "Simple interest", "compound": "Compound interest with nominal rate r compounded n times a year", "continuous": "Continuous compounding"}[kind], formula)

    same_sign = "The future value must be above the principal for a positive rate and below it for a negative rate."
    if kind == "simple":
        if solve == "fv":
            fv = pv * (1 + r * t)
        elif solve == "pv":
            C.require(1 + r * t > 0, "1 + rate·time must be positive for the principal to be recovered", "rate")
            pv = fv / (1 + r * t)
        elif solve == "rate":
            r = (fv / pv - 1) / t
        else:
            C.require(r != 0, "With a 0 % rate the amount never changes, so the time cannot be found.", "rate")
            t = (fv / pv - 1) / r
            C.require(t > 0, same_sign, "fv")
    elif kind == "continuous":
        if solve == "fv":
            fv = pv * exp_f(r * t)
        elif solve == "pv":
            pv = fv / exp_f(r * t)
        elif solve == "rate":
            r = ln(fv / pv, "fv") / t
        else:
            C.require(r != 0, "With a 0 % rate the amount never changes, so the time cannot be found.", "rate")
            t = ln(fv / pv, "fv") / r
            C.require(t > 0, same_sign, "fv")
    else:
        if r is not None and 1 + r / n <= 0:
            o.warn("The rate is so negative that the growth factor 1 + r/n is not positive; only whole numbers of periods can be calculated.")
        if solve == "fv":
            fv = pv * power(1 + r / n, n * t, "years")
        elif solve == "pv":
            pv = fv / power(1 + r / n, n * t, "years")
        elif solve == "rate":
            r = n * (power(fv / pv, 1 / (n * t), "fv") - 1)
        else:
            C.require(r != 0, "With a 0 % rate the amount never changes, so the time cannot be found.", "rate")
            C.require(1 + r / n > 0, "1 + rate/n must be positive to solve for the time", "rate")
            C.require(fv != pv, "The future value equals the principal, so no time has passed.", "fv")
            t = ln(fv / pv, "fv") / (n * ln(1 + r / n, "rate"))
            C.require(t > 0, same_sign, "fv")
    assert pv is not None and fv is not None and r is not None and t is not None
    o.step(f"Solve for the {({'pv': 'principal PV', 'fv': 'future value FV', 'rate': 'annual rate r', 'years': 'time t'})[solve]}",
           "The other values are as entered. The unrounded result is carried on; only the display is rounded.")

    shown = {"pv": f.money(pv), "fv": f.money(fv),
             "rate": f.percent(r, label={"simple": "simple annual rate", "compound": f"nominal annual rate, compounded {n} times a year", "continuous": "continuously compounded annual rate"}[kind]),
             "years": f.amount(t, unit="years")}
    names = {"pv": "principal", "fv": "futureValue", "rate": "rate", "years": "years"}
    out: dict[str, object] = {names[solve]: shown[solve]}
    for k in ("pv", "fv", "rate", "years"):
        if k != solve:
            out[names[k]] = shown[k]
    out["interestEarned"] = f.money(fv - pv)
    out["totalGrowth"] = f.percent(fv / pv - 1)
    if kind == "compound":
        base = 1 + r / n
        out["effectiveAnnualRate"] = f.percent(power(base, Fraction(n)) - 1, label="what the nominal rate is worth over one year")
        if r > 0:
            with hp():
                out["doublingTime"] = f.amount(from_mp(mp.log(2) / (n * mp.log(to_mp(base)))), unit="years")
    elif kind == "continuous":
        out["effectiveAnnualRate"] = f.percent(exp_f(r) - 1, label="what the continuous rate is worth over one year")
        if r > 0:
            with hp():
                out["doublingTime"] = f.amount(from_mp(mp.log(2) / to_mp(r)), unit="years")
    else:
        out["averageInterestPerYear"] = f.money((fv - pv) / t)

    curve = growth_curve(pv, r, n, t, kind)
    plot = C.plot_block("Balance over time", "Years", "Balance" + (f" ({f.code})" if f.has_currency else ""), [{"label": "Balance", "points": [[x, y] for x, y in curve], "kind": "line"}],
                        description="How the balance grows from the principal to the future value.")
    p_slider = C.slider("P", pv, 0, max(1.0, to_float(pv) * 5), max(0.01, to_float(pv) / 100))
    r_slider = C.slider("r", r, -0.2, 0.3, 0.001)
    if kind == "compound":
        expr, sliders = "P*(1+r/n)^(n*x)", [p_slider, r_slider, C.slider("n", Fraction(n), 1, 365, 1)]
    elif kind == "continuous":
        expr, sliders = "P*exp(r*x)", [p_slider, r_slider]
    else:
        expr, sliders = "P*(1+r*x)", [p_slider, r_slider]
    graph = C.graph_spec([{"type": "auto", "expr": expr, "color": "#b89b00"}], params=sliders, viewport=C.pad_view([0.0, to_float(t)], [y for _, y in curve]))
    return o.done(mode=kind, **out, plot=plot, graph=graph, latex=formula)


# ================================================================================================================ rate conversion
def op_rate_conversion(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    kind = C.choice(params, "mode", ("nominal", "effective", "periodic", "continuous"), "nominal")
    r = rate(params, "rate")
    assert r is not None
    n = freq(params, "freq", 12) if kind in ("nominal", "periodic") else None
    note = C.rate_note(r * 100)
    if note:
        o.warn(note)
    o.assume({"nominal": f"The rate is a nominal annual rate compounded {n} times per year (an 'APR' in the usual sense).",
              "effective": "The rate is an effective annual rate: what one year of growth actually adds (an 'APY').",
              "periodic": f"The rate is the rate for one period, with {n} periods in a year.",
              "continuous": "The rate is a continuously compounded annual rate."}[kind])
    if kind == "nominal":
        eff = power(1 + r / n, Fraction(n)) - 1
        o.step("Effective annual rate", "i = (1 + r/n)^n − 1", r"i = \left(1 + \frac{r}{n}\right)^{n} - 1")
    elif kind == "effective":
        eff = r
    elif kind == "periodic":
        eff = power(1 + r, Fraction(n)) - 1
        o.step("Effective annual rate", "i = (1 + periodic rate)^n − 1", r"i = (1 + r_p)^{n} - 1")
    else:
        eff = exp_f(r) - 1
        o.step("Effective annual rate", "i = e^r − 1", r"i = e^{r} - 1")
    C.require(eff > -1, "The effective annual rate must be greater than −100 %", "rate")
    rows = []
    for m in FREQUENCIES:
        nom = m * (power(1 + eff, Fraction(1, m)) - 1)
        rows.append({"compounding": FREQ_NAMES[m], "perYear": m, "nominalRate": f.percent(nom), "periodicRate": f.percent(nom / m)})
    cont = ln(1 + eff)
    rows.append({"compounding": "continuously", "perYear": "∞", "nominalRate": f.percent(cont), "periodicRate": "—"})
    o.step("Equivalent nominal rates", "r_n = n·[(1 + i)^(1/n) − 1]", r"r_n = n\left[(1+i)^{1/n} - 1\right]")
    return o.done(effectiveAnnualRate=f.percent(eff, label="the rate that gives the same growth over one year"), continuousRate=f.percent(cont, label="the equivalent continuously compounded rate"),
                  equivalents=rows, latex=r"1 + i = \left(1 + \frac{r}{n}\right)^{n} = e^{\rho}")


# ================================================================================================================ real vs nominal
def op_real_rate(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    solve = one_empty(params, [("nominal", "nominal rate"), ("inflation", "inflation rate"), ("real", "real rate")])
    nom = rate(params, "nominal", required=False) if solve != "nominal" else None
    inf = rate(params, "inflation", required=False) if solve != "inflation" else None
    real = rate(params, "real", required=False) if solve != "real" else None
    for key, v in (("nominal", nom), ("inflation", inf), ("real", real)):
        if key != solve and v is None:
            raise BadRequest(f"'{key}' is required", details={"field": key})
    o.assume("The exact Fisher relation 1 + nominal = (1 + real)(1 + inflation) is used. The common shortcut real ≈ nominal − inflation is shown for comparison.")
    o.assume("All three are annual rates, typed as percentages.")
    o.step("Fisher equation", "The nominal growth factor is the real growth factor times the inflation factor.", r"1 + i_{\mathrm{nom}} = (1 + i_{\mathrm{real}})(1 + \pi)")
    if solve == "real":
        C.require(inf > -1, "Inflation must be greater than −100 %", "inflation")
        real = (1 + nom) / (1 + inf) - 1
    elif solve == "nominal":
        nom = (1 + real) * (1 + inf) - 1
    else:
        C.require(real > -1, "The real rate must be greater than −100 %", "real")
        inf = (1 + nom) / (1 + real) - 1
    shown = {"nominal": f.percent(nom), "inflation": f.percent(inf), "real": f.percent(real)}
    keys = {"nominal": "nominalRate", "inflation": "inflationRate", "real": "realRate"}
    out: dict[str, object] = {keys[solve]: shown[solve]}
    out.update({keys[k]: shown[k] for k in shown if k != solve})
    approx = {"nominal": real + inf, "inflation": nom - real, "real": nom - inf}[solve]
    exact_v = {"nominal": nom, "inflation": inf, "real": real}[solve]
    out["shortcutApproximation"] = f.percent(approx, label="simple addition or subtraction of the other two")
    out["shortcutError"] = f.percent(approx - exact_v, label="the shortcut's error, in percentage points")
    return o.done(**out)


# ================================================================================================================ annuities
def annuity_factors(i: Fraction, n: int) -> tuple[Fraction, Fraction]:
    """(a, s): present and accumulated value of 1 paid at the end of each of ``n`` periods at periodic rate ``i``."""
    C.require(i > -1, "The periodic rate must be greater than −100 %", "rate")
    if i == 0:
        return Fraction(n), Fraction(n)
    g = (1 + i) ** n
    return (1 - 1 / g) / i, (g - 1) / i


ANNUITY_MODES = ("pv", "fv", "payment_for_pv", "payment_for_fv", "periods_for_pv", "periods_for_fv", "rate_for_pv", "rate_for_fv")


def whole_up(x: Fraction) -> int:
    return int(math.ceil(float(x) - 1e-12))


def op_annuity(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    mode = C.choice(params, "mode", ANNUITY_MODES, "pv")
    due = C.choice(params, "timing", ("end", "begin"), "end") == "begin"
    per = freq(params, "perYear", 12)
    solving_rate = mode.startswith("rate_")
    nominal = rate(params, "rate", required=not solving_rate)
    i = None if solving_rate else nominal / per                                                       # type: ignore[operator]
    if nominal is not None:
        note = C.rate_note(nominal * 100)
        if note:
            o.warn(note)
    pmt = frac(params, "pmt", required=not mode.startswith("payment_"))
    n = None if mode.startswith("periods_") else C.count(params, "periods")
    needs_pv = mode in ("payment_for_pv", "periods_for_pv", "rate_for_pv")
    needs_fv = mode in ("payment_for_fv", "periods_for_fv", "rate_for_fv")
    pv0 = (frac(params, "pv", required=needs_pv) if mode != "pv" else None) or Fraction(0)
    fv_t = frac(params, "fv", required=True) if needs_fv else None
    o.assume(f"Payments are made at the {'beginning' if due else 'end'} of each period ({'annuity due' if due else 'ordinary annuity'}).")
    o.assume(f"There are {per} payment periods per year. The nominal annual rate is compounded at the same frequency, so the periodic rate is rate / {per}.")
    d = (1 + i) if (due and i is not None) else Fraction(1)
    out: dict[str, object] = {}

    if mode == "pv":
        a, _ = annuity_factors(i, n)
        value = pmt * a * d
        o.step("Present value of the payments", "PV = PMT · [1 − (1+i)^−n] / i" + (" · (1+i)" if due else ""), r"PV = PMT\,\frac{1-(1+i)^{-n}}{i}" + (r"\,(1+i)" if due else ""))
        out.update(presentValue=f.money(value), totalPayments=f.money(pmt * n), interestComponent=f.money(pmt * n - value))
    elif mode == "fv":
        _, s = annuity_factors(i, n)
        value = pv0 * (1 + i) ** n + pmt * s * d
        o.step("Future value", "FV = PV·(1+i)^n + PMT · [(1+i)^n − 1] / i" + (" · (1+i)" if due else ""), r"FV = PV(1+i)^{n} + PMT\,\frac{(1+i)^{n}-1}{i}" + (r"\,(1+i)" if due else ""))
        contributed = pv0 + pmt * n
        out.update(futureValue=f.money(value), totalContributed=f.money(contributed), interestEarned=f.money(value - contributed))
    elif mode == "payment_for_pv":
        a, _ = annuity_factors(i, n)
        value = pv0 / (a * d)
        o.step("Level payment that repays the amount", "PMT = PV · i / [1 − (1+i)^−n]" + (" / (1+i)" if due else ""), r"PMT = PV\,\frac{i}{1-(1+i)^{-n}}")
        out.update(payment=f.money(value), totalPayments=f.money(value * n), totalInterest=f.money(value * n - pv0))
    elif mode == "payment_for_fv":
        _, s = annuity_factors(i, n)
        value = (fv_t - pv0 * (1 + i) ** n) / (s * d)
        o.step("Payment that reaches the target", "PMT = (FV − PV·(1+i)^n) / ([(1+i)^n − 1]/i)", r"PMT = \frac{FV - PV(1+i)^{n}}{\left[(1+i)^{n}-1\right]/i}")
        out.update(payment=f.money(value), totalContributed=f.money(pv0 + value * n))
        if value < 0:
            o.warn("The starting balance alone already grows beyond the target, so the payment is negative (a withdrawal).")
    elif mode == "periods_for_pv":
        C.require(pmt > 0, "The payment must be positive", "pmt")
        if i == 0:
            nn = pv0 / pmt
        else:
            x = 1 - pv0 * i / (pmt * d)
            if x <= 0:
                raise BadRequest("This payment never repays the amount: it does not even cover the interest.", details={"field": "pmt"},
                                 hint=f"The payment must exceed {f.money(pv0 * i / d)['text']} per period.")
            nn = -ln(x) / ln(1 + i)
        o.step("Number of payments", "n = −ln(1 − PV·i/PMT) / ln(1+i)", r"n = -\frac{\ln\left(1 - \frac{PV\,i}{PMT}\right)}{\ln(1+i)}")
        out.update(periods=f.amount(nn, places=4), years=f.amount(nn / per, places=4, unit="years"),
                   wholePayments={"text": str(whole_up(nn)), "latex": str(whole_up(nn)), "value": whole_up(nn), "note": "payments needed (the last one is smaller)"})
    elif mode == "periods_for_fv":
        C.require(pmt > 0 or pv0 > 0, "Give a payment or a starting balance", "pmt")
        if i == 0:
            C.require(pmt > 0, "With a 0 % rate only payments can grow the balance", "pmt")
            nn = (fv_t - pv0) / pmt
        else:
            c = pmt * d / i
            num, den = fv_t + c, pv0 + c
            if den == 0 or num / den <= 0:
                raise BadRequest("The target cannot be reached with these payments and this rate.", details={"field": "fv"})
            nn = Fraction(0) if num == den else ln(num / den) / ln(1 + i)
        if nn < 0:
            raise BadRequest("The target is not reached by these payments at this rate: the balance moves away from it.", details={"field": "fv"})
        o.step("Number of payments to reach the target", "n = ln[(FV + c)/(PV + c)] / ln(1+i), with c = PMT·(1+i)^timing / i", r"n = \frac{\ln\frac{FV + c}{PV + c}}{\ln(1+i)}")
        out.update(periods=f.amount(nn, places=4), years=f.amount(nn / per, places=4, unit="years"),
                   wholePayments={"text": str(whole_up(nn)), "latex": str(whole_up(nn)), "value": whole_up(nn), "note": "payments needed to reach the target"})
    else:                                                                                              # rate_for_pv / rate_for_fv
        C.require(pmt != 0, "A payment is needed to solve for the rate", "pmt")
        p_m, v_m = to_mp(pmt), to_mp(pv0)

        def pv_of(x: mp.mpf) -> mp.mpf:
            if abs(x) < mp.mpf(10) ** -40:
                return p_m * n
            return p_m * (1 - (1 + x) ** (-n)) / x * ((1 + x) if due else 1)

        def fv_of(x: mp.mpf) -> mp.mpf:
            if abs(x) < mp.mpf(10) ** -40:
                return v_m + p_m * n
            return v_m * (1 + x) ** n + p_m * ((1 + x) ** n - 1) / x * ((1 + x) if due else 1)

        with hp():
            target = to_mp(pv0) if mode == "rate_for_pv" else to_mp(fv_t)
            fn = (lambda x: pv_of(x) - target) if mode == "rate_for_pv" else (lambda x: fv_of(x) - target)
            root = C.bisect(fn, mp.mpf("-0.999999"), mp.mpf(10))
        if root is None:
            raise BadRequest("No periodic rate between −100 % and 1000 % per period fits these numbers.",
                             hint="The target must lie between what the payments give at a very low and at a very high rate.")
        ir = from_mp(root)
        o.step("Solve for the periodic rate numerically", "60-digit bisection on the annuity equation, converged to 45 digits.")
        out.update(rate=f.percent(ir * per, label=f"nominal annual rate (periodic rate × {per})"), periodicRate=f.percent(ir),
                   effectiveAnnualRate=f.percent(power(1 + ir, Fraction(per)) - 1))
    if i is not None:
        o.step("Periodic rate", f"i = r / {per}", r"i = \frac{r}{m}")
    plot = graph = None
    if mode in ("fv", "payment_for_fv") and i is not None and n is not None:
        pay = value if mode == "payment_for_fv" else pmt
        plot, graph = _saving_curves(i, per, pay, n, pv0, due)
    return o.done(mode=mode, **out, **({"plot": plot, "graph": graph} if plot else {}))


def _saving_curves(i: Fraction, per: int, pmt: Fraction, n: int, start: Fraction, due: bool):
    pts: list[tuple[float, float]] = [(0.0, float(start))]
    b = start
    for k in range(1, min(n, MAX_CURVE) + 1):
        b = (b + pmt) * (1 + i) if due else b * (1 + i) + pmt
        pts.append((k / per, to_float(b)))
    plot = C.plot_block("Balance with regular payments", "Years", "Balance", [{"label": "Balance", "points": [[x, y] for x, y in pts], "kind": "line"}],
                        description="The balance after each payment: interest on the balance plus the new payment.")
    graph = C.graph_spec([{"type": "scatter", "data": C.points_text(pts), "color": "#b89b00", "label": "Balance"}], viewport=C.pad_view([x for x, _ in pts], [y for _, y in pts]))
    return plot, graph


# ================================================================================================================ perpetuities
def op_perpetuity(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    mode = C.choice(params, "mode", ("pv", "payment", "rate"), "pv")
    due = C.choice(params, "timing", ("end", "begin"), "end") == "begin"
    g = rate(params, "growth", required=False) or Fraction(0)
    r = rate(params, "rate") if mode != "rate" else None
    c = frac(params, "payment") if mode != "payment" else None
    pv = frac(params, "pv", positive=True) if mode != "pv" else None
    o.assume(f"The first payment is made at the {'start' if due else 'end'} of the first period; payments then continue forever"
             + (f", growing by {C.fmt_decimal(g * 100, 4)} % each period." if g else "."))
    o.assume("Rates are per period, not per year. A perpetuity has a finite value only when the discount rate exceeds the growth rate.")
    o.step("Value of a growing perpetuity", "PV = C / (r − g)" + ("  × (1 + r)  for payments at the start of each period" if due else ""), r"PV = \frac{C}{r - g}" + (r"\,(1+r)" if due else ""))
    factor = (1 + r) if (due and r is not None) else Fraction(1)
    if mode == "pv":
        C.require(r > g, "The discount rate must be greater than the growth rate, otherwise the value is infinite.", "rate")
        res = {"presentValue": f.money(c / (r - g) * factor)}
    elif mode == "payment":
        C.require(r > g, "The discount rate must be greater than the growth rate.", "rate")
        res = {"payment": f.money(pv * (r - g) / factor)}
    else:
        if due:                                    # PV (r − g) = C (1 + r)  ->  r (PV − C) = C + PV·g
            C.require(pv != c, "No finite rate fits these numbers.")
            r_val = (c + pv * g) / (pv - c)
        else:
            r_val = c / pv + g
        C.require(r_val > g, "These numbers imply a rate at or below the growth rate.", "growth")
        res = {"rate": f.percent(r_val, label="per period")}
    return o.done(mode=mode, **res)
