"""Statistical and scenario analysis for financial data: growth-rate comparison, time-series trend (reusing the Graphing regression), sensitivity tables."""
from __future__ import annotations

import math
from fractions import Fraction
from typing import Any

import numpy as np

from ...core.graphing import regression
from ...core.numerical.context import Settings
from ...errors import BadRequest, DomainError, EvaluationError
from . import core as C
from .core import Result, frac, power, rate, to_float
from .interest import annuity_factors, freq
from .investment import irr_roots, npv_of, npv_profile
from .loans import cell, pay_exact


def approx(f: C.Fmt, v: float, places: int = 6) -> dict[str, Any]:
    """A number that came from floating-point (least-squares) arithmetic: shown rounded and marked approximate, with no false 'exact' digits."""
    from decimal import Decimal
    out = f.amount(Fraction(Decimal(repr(float(v)))), places=places)
    out.pop("exact", None)
    out["approximate"] = True
    return out

MAX_SERIES = 8
TREND_MODELS = ("linear", "exponential", "power", "logarithmic", "quadratic")


# ================================================================================================================ growth comparison
def op_growth_compare(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    raw = params.get("series")
    if not isinstance(raw, list) or len(raw) < 2:
        raise BadRequest("Add at least two series to compare (a name, a beginning value, an ending value and a number of years each).", details={"field": "series"})
    if len(raw) > MAX_SERIES:
        raise BadRequest(f"At most {MAX_SERIES} series can be compared.", details={"field": "series"})
    o.assume("Each series is summarised by its compound annual growth rate, (end/begin)^(1/years) − 1: the constant yearly rate with the same start and end. Different paths can share a CAGR.")
    rows, curves, graph_layers = [], [], []
    colors = ["#b89b00", "#2f6fdb", "#d6572b", "#2e9d6a", "#8a5cc2", "#c2557f", "#4f8f9d", "#7a7a7a"]
    parsed = []
    for k, sc in enumerate(raw):
        if not isinstance(sc, dict):
            raise BadRequest(f"Series {k + 1} must be a row of values", details={"field": "series"})
        name = str(sc.get("name") or f"Series {k + 1}")[:40]
        try:
            b = frac(sc, "begin", positive=True)
            e = frac(sc, "end", positive=True)
            t = frac(sc, "years", positive=True)
        except BadRequest as exc:
            exc.message = f"Series {k + 1} ('{name}'): {exc.message}"
            exc.args = (exc.message,)
            raise
        g = power(e / b, 1 / t, "years") - 1
        parsed.append((name, b, e, t, g))
    order = sorted(range(len(parsed)), key=lambda k: parsed[k][4], reverse=True)
    for k, (name, b, e, t, g) in enumerate(parsed):
        row = {"series": name, "begin": f.amount(b), "end": f.amount(e), "years": f.amount(t), "totalGrowth": f.percent(e / b - 1), "cagr": f.percent(g),
               "rank": order.index(k) + 1}
        if g > 0:
            row["doublingTime"] = f.amount(C.ln(Fraction(2)) / C.ln(1 + g), unit="years")
        else:
            row["doublingTime"] = "—"
        rows.append(row)
    horizon = max(p[3] for p in parsed)
    pts_all = []
    for k, (name, b, e, t, g) in enumerate(parsed):
        pts = [(float(horizon) * j / 40, 100.0 * float(power(1 + g, horizon * j / 40, "years"))) for j in range(41)]
        pts_all += pts
        curves.append({"label": f"{name} ({C.fmt_decimal(g * 100, 2)} %/yr)", "points": [[x, y] for x, y in pts], "kind": "line"})
        graph_layers.append({"type": "auto", "expr": f"100*(1+{float(g):.10g})^x", "color": colors[k % len(colors)], "label": name})
    plot = C.plot_block("Growth, each series indexed to 100", "Years", "Index (start = 100)", curves, description="Each series at its compound rate from a common starting index of 100, so rates can be compared directly.")
    graph = C.graph_spec(graph_layers, viewport=C.pad_view([0.0, float(horizon)], [y for _, y in pts_all]))
    out = {"fastest": parsed[order[0]][0], "slowest": parsed[order[-1]][0], "spreadInPercentagePoints": f.amount((parsed[order[0]][4] - parsed[order[-1]][4]) * 100, unit="percentage points")}
    return o.done(headline=f"Fastest: {out['fastest']} at {C.fmt_decimal(parsed[order[0]][4] * 100, 2)} % a year", **out, comparison=rows, plot=plot, graph=graph)


# ================================================================================================================ trend
def op_trend(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    ys = C.numbers_list(params, "values", minimum=3, maximum=C.MAX_FLOWS)
    model = C.choice(params, "model", TREND_MODELS, "linear")
    per = freq(params, "perYear", 1)
    ahead = C.count(params, "forecast", lo=0, hi=120, default=0, required=False) or 0
    window = C.count(params, "movingAverage", lo=2, hi=max(2, len(ys)), default=None, required=False)
    start = frac(params, "start", required=False) or Fraction(1)
    n = len(ys)
    xs = [start + k for k in range(n)]
    o.assume(f"The values are equally spaced observations, numbered {C.fmt_decimal(start, 2).rstrip('0').rstrip('.')}, {C.fmt_decimal(start + 1, 2).rstrip('0').rstrip('.')}, …; {per} observation{'s' if per != 1 else ''} per year.")
    o.assume("The trend is a least-squares fit (the same code as the Graphing workspace). It describes the data; it does not explain them, and extrapolating it is a projection, not a forecast.")
    x_arr, y_arr = np.array([float(x) for x in xs]), np.array([float(y) for y in ys])
    try:
        if model == "quadratic":
            res = regression.fit("quadratic", x_arr, y_arr)
        else:
            res = regression.fit(model, x_arr, y_arr)
    except (DomainError, EvaluationError) as exc:
        raise BadRequest(str(exc), details={"field": "values"}, hint="Choose a model that suits the data (exponential and power need positive values).") from exc
    fn = res["fn"]
    out: dict[str, Any] = {"model": model, "equation": res["equation"], "r2": approx(f, res["r2"], 4) if math.isfinite(res["r2"]) else "undefined (the values are all equal)",
                           "rmse": approx(f, res["rmse"], 6), "observations": n}
    p = res["params"]
    if model == "exponential":
        out["growthPerObservation"] = {**approx(f, math.expm1(p["b"]) * 100, 4), "text": f"{C.fmt_decimal(Fraction(repr(math.expm1(p['b']) * 100)), 4)} %", "unit": "%", "note": "y grows by this much each step on the fitted curve"}
        if per != 1:
            out["growthPerYear"] = {**approx(f, math.expm1(p["b"] * per) * 100, 4), "text": f"{C.fmt_decimal(Fraction(repr(math.expm1(p['b'] * per) * 100)), 4)} %", "unit": "%"}
    elif model == "linear":
        out["slopePerObservation"] = approx(f, p["a"], 6)
    if ys[0] > 0 and ys[-1] > 0 and n > 1:
        out["observedCagr"] = f.percent(power(ys[-1] / ys[0], Fraction(per, n - 1), "values") - 1, label="first to last value, compounded per year")
    changes = [(ys[k] - ys[k - 1]) / abs(ys[k - 1]) if ys[k - 1] != 0 else None for k in range(1, n)]
    valid = [c for c in changes if c is not None]
    if valid:
        mean = sum(valid, Fraction(0)) / len(valid)
        out["averagePeriodChange"] = f.percent(mean, label="arithmetic mean of the period-to-period changes")
        sd = math.sqrt(sum((float(c - mean)) ** 2 for c in valid) / max(1, len(valid) - 1))
        out["volatilityOfChanges"] = {**approx(f, sd * 100, 4), "text": f"{sd * 100:.4f} %", "unit": "%", "note": "standard deviation of the period-to-period changes"}
    if res["r2"] is not None and math.isfinite(res["r2"]) and res["r2"] < 0.5:
        o.warn("The fit explains less than half of the variation (R² < 0.5): this model is a poor description of the data.")
    if n < 8:
        o.warn("With so few observations a trend is fragile; treat the fitted numbers as descriptive only.")
    fitted = [(float(x), float(fn(np.array([float(x)]))[0])) for x in xs]
    proj = []
    if ahead:
        o.warn("The projection extends the fitted curve beyond the data. Nothing in the data says the pattern will continue.")
        last = xs[-1]
        proj = [(float(last + k), float(fn(np.array([float(last + k)]))[0])) for k in range(1, ahead + 1)]
        out["projection"] = [{"observation": C.fmt_decimal(last + k, 2).rstrip("0").rstrip("."), "value": approx(f, v, 4)} for k, (_, v) in enumerate(proj, 1)]
    series = [{"label": "Data", "points": [[float(x), to_float(y)] for x, y in zip(xs, ys)], "kind": "scatter"},
              {"label": f"{model} fit", "points": [[x, y] for x, y in fitted + proj], "kind": "line"}]
    if window:
        ma = []
        for k in range(window - 1, n):
            ma.append([float(xs[k]), to_float(sum(ys[k - window + 1:k + 1], Fraction(0)) / window)])
        series.append({"label": f"{window}-point moving average", "points": ma, "kind": "line", "dashed": True})
    plot = C.plot_block("Values and trend", "Observation", "Value", series)
    resid = [[float(x), to_float(y) - fy] for (x, y), (_, fy) in zip(zip(xs, ys), fitted)]
    plot2 = C.plot_block("Residuals", "Observation", "Value − fit", [{"label": "Residual", "points": resid, "kind": "scatter"}], zero_line=True,
                         description="A pattern here means the chosen model is missing something.")
    graph = C.graph_spec([{"type": "scatter", "data": C.points_text([(float(x), to_float(y)) for x, y in zip(xs, ys)]), "fitModel": model, "color": "#b89b00", "label": "Data"}],
                         viewport=C.pad_view([float(x) for x in xs] + [x for x, _ in proj], [to_float(y) for y in ys] + [y for _, y in proj]))
    return o.done(headline=f"{model.capitalize()} trend: {res['equation']}", **out, plot=plot, plot2=plot2, graph=graph)


# ================================================================================================================ sensitivity
def op_sensitivity(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    target = C.choice(params, "mode", ("npv", "loan_payment", "future_value"), "loan_payment")
    out: dict[str, Any] = {}
    plot = graph = None
    if target == "npv":
        flows = C.numbers_list(params, "flows", minimum=2)
        lo = rate(params, "rateFrom", default="0")
        hi = rate(params, "rateTo", default="20")
        steps = C.count(params, "steps", lo=2, hi=60, default=10, required=False) or 10
        C.require(hi > lo, "The upper rate must be above the lower rate", "rateTo")
        C.require(lo > -1, "The lower rate must be above −100 %", "rateFrom")
        o.assume("NPV is recomputed exactly at each discount rate (per period); the first flow is at time 0.")
        rows, pts = [], []
        prev = None
        for k in range(steps + 1):
            r = lo + (hi - lo) * k / steps
            v = npv_of(flows, r)
            rows.append({"rate": f.percent(r), "npv": cell(v, f.places)})
            pts.append((to_float(r) * 100, to_float(v)))
            if prev is not None and (prev > 0) != (v > 0):
                out["signChangeBetween"] = f"{C.fmt_decimal(r - (hi - lo) / steps, 4)} and {C.fmt_decimal(r, 4)} (as decimals): an IRR lies between"
            prev = v
        roots, _, _ = irr_roots(flows)
        out["internalRates"] = [f.percent(x)["text"] for x in roots]
        out["table"] = rows
        plot = C.plot_block("NPV against the discount rate", "Discount rate (%)", "NPV", [{"label": "NPV", "points": [[x, y] for x, y in pts], "kind": "line"}], zero_line=True,
                            markers=[{"x": float(x) * 100, "y": 0.0, "label": f"IRR {C.fmt_decimal(x * 100, 2)} %"} for x in roots[:4]])
        graph = C.graph_spec([{"type": "scatter", "data": C.points_text(pts), "color": "#b89b00", "label": "NPV"}], viewport=C.pad_view([x for x, _ in pts], [y for _, y in pts]))
    else:
        rates = [x / 100 for x in C.numbers_list(params, "rates", minimum=1, maximum=12)]
        years = C.numbers_list(params, "yearsList", minimum=1, maximum=12)
        per = freq(params, "perYear", 12 if target == "loan_payment" else 1)
        amount = frac(params, "amount", positive=True)
        contribution = frac(params, "contribution", nonneg=True, required=False) or Fraction(0)
        due = C.choice(params, "timing", ("end", "begin"), "end") == "begin"
        o.assume(f"Nominal annual rates compounded {per} time{'s' if per != 1 else ''} a year; payments at the {'beginning' if due else 'end'} of each period.")
        header = [f"{C.fmt_decimal(y, 2).rstrip('0').rstrip('.')} years" for y in years]
        table, curves = [], []
        for r in rates:
            i = r / per
            C.require(i > -1, "A rate of −100 % a year or less is not meaningful", "rates")
            row: dict[str, Any] = {"Rate": f.percent(r)}
            pts = []
            for k, y in enumerate(years):
                n = y * per
                C.require(n.denominator == 1 and 0 < n <= C.MAX_PERIODS, f"{C.fmt_decimal(y, 2)} years at {per} a year is not a whole number of periods (1 to {C.MAX_PERIODS})", "yearsList")
                n = int(n)
                if target == "loan_payment":
                    v = pay_exact(amount, i, n, due)
                else:
                    a, s = annuity_factors(i, n)
                    v = amount * (1 + i) ** n + contribution * s * ((1 + i) if due else 1)
                row[header[k]] = cell(v, f.places)
                pts.append((float(y), to_float(v)))
            table.append(row)
            curves.append({"label": f"{C.fmt_decimal(r * 100, 2).rstrip('0').rstrip('.')} %", "points": [[x, y] for x, y in pts], "kind": "line"})
        what = "Payment per period" if target == "loan_payment" else "Value at the end"
        o.assume("Each cell is exact arithmetic on the entered values; only the display is rounded." if target == "loan_payment" else "Future value of the starting amount plus regular contributions; exact arithmetic, display rounded.")
        out.update(table=table)
        plot = C.plot_block(f"{what} by term and rate", "Years", what, curves)
        graph = C.graph_spec([{"type": "scatter", "data": C.points_text([(p[0], p[1]) for p in c["points"]]), "color": col, "label": c["label"]}
                              for c, col in zip(curves, ["#b89b00", "#2f6fdb", "#d6572b", "#2e9d6a", "#8a5cc2", "#c2557f", "#4f8f9d", "#7a7a7a", "#444444", "#996633", "#339999", "#993366"])],
                             viewport=C.pad_view([p[0] for c in curves for p in c["points"]], [p[1] for c in curves for p in c["points"]]))
    return o.done(headline={"npv": "NPV across discount rates", "loan_payment": "Loan payment by rate and term", "future_value": "Future value by rate and term"}[target], mode=target, **out, plot=plot, graph=graph)
