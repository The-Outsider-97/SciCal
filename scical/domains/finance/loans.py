"""Loans and mortgages: payments, terms, balances, amortization schedules (annuity and linear), extra payments, and scenario comparison.

Assumptions that every loan result states:

* The nominal annual rate is compounded at the payment frequency, so the periodic rate is ``rate / paymentsPerYear``.
* Payments fall at the **end** of each period (an ordinary annuity) unless the timing is set to "beginning". A payment at the beginning of
  the first period pays down principal before any interest has accrued.
* An upfront fee is paid out of pocket at the start, so the borrower receives ``principal − fee``. The **APR** shown is the nominal annual
  rate, compounded at the payment frequency, at which those net proceeds equal the payments. It is a calculation, not a regulatory APR.
* With "round each period", every interest amount is rounded half away from zero to the currency's smallest unit and the *last* payment
  absorbs the rounding. The principal repaid then adds up to the loan exactly and the balance ends at exactly zero.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

import mpmath as mp

from ...core.numerical.context import Settings
from ...errors import BadRequest
from . import core as C
from .core import Result, frac, from_mp, hp, power, rate, to_float, to_mp
from .interest import annuity_factors, freq, one_empty, whole_up

MAX_ROWS = C.MAX_PERIODS


# ---------------------------------------------------------------------------------------------------------------------- shared reading
def term(params: dict, key_years: str = "years") -> tuple[int, int]:
    """(number of payments, payments per year) from a term in years and a payment frequency. The product must be a whole number."""
    per = freq(params, "perYear", 12)
    years = frac(params, key_years, positive=True)
    n = years * per
    if n.denominator != 1:
        raise BadRequest(f"{C.fmt_decimal(years, 6).rstrip('0').rstrip('.')} years at {per} payments a year is {C.fmt_decimal(n, 4).rstrip('0').rstrip('.')} payments; the term must be a whole number of payments.",
                         details={"field": key_years}, hint="Change the term or the payment frequency.")
    n = int(n)
    if n > MAX_ROWS:
        raise BadRequest(f"At most {MAX_ROWS} payments can be worked out (this term has {n}).", details={"field": key_years})
    return n, per


def pay_exact(principal: Fraction, i: Fraction, n: int, due: bool = False) -> Fraction:
    a, _ = annuity_factors(i, n)
    return principal / (a * ((1 + i) if due else 1))


def apr_for(net: Fraction, pmt: Fraction, n: int, per: int, due: bool) -> Fraction | None:
    """The periodic rate at which the payments are worth ``net`` today (60-digit bisection), or None when no rate between −100 % and 1000 % does."""
    p_m = to_mp(pmt)

    def pv_of(x: mp.mpf) -> mp.mpf:
        if abs(x) < mp.mpf(10) ** -40:
            return p_m * n
        return p_m * (1 - (1 + x) ** (-n)) / x * ((1 + x) if due else 1)

    with hp():
        root = C.bisect(lambda x: pv_of(x) - to_mp(net), mp.mpf("-0.999999"), mp.mpf(10))
    return None if root is None else from_mp(root)


def assumptions(o: Result, per: int, due: bool, fee: bool = False) -> None:
    o.assume(f"The nominal annual rate is compounded at the payment frequency ({per} payment{'s' if per != 1 else ''} a year), so the periodic rate is rate / {per}.")
    o.assume("Payments are made at the beginning of each period (the first one pays down principal before interest accrues)." if due
             else "Payments are made at the end of each period (an ordinary annuity).")
    if fee:
        o.assume("The fee is paid out of pocket at the start, so the borrower receives the principal minus the fee. The APR is the nominal annual rate (compounded at the payment frequency) at which that net amount equals the payments.")


def fees_of(params: dict, principal: Fraction) -> Fraction:
    amount = frac(params, "feeAmount", nonneg=True, required=False) or Fraction(0)
    pct = rate(params, "feePercent", required=False) or Fraction(0)
    if pct < 0:
        raise BadRequest("The fee percentage cannot be negative", details={"field": "feePercent"})
    return amount + principal * pct


# ================================================================================================================ loan
LOAN_MODES = ("payment", "linear", "term", "borrow", "balance")


def op_loan(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    mode = C.choice(params, "mode", LOAN_MODES, "payment")
    due = C.choice(params, "timing", ("end", "begin"), "end") == "begin"
    nominal = rate(params, "rate")
    per = freq(params, "perYear", 12)
    i = nominal / per
    note = C.rate_note(nominal * 100)
    if note:
        o.warn(note)
    assumptions(o, per, due, fee=mode == "payment")
    out: dict[str, Any] = {}
    plot = graph = None

    if mode in ("payment", "linear", "balance"):
        principal = frac(params, "principal", positive=True)
        n, per = term(params)
        i = nominal / per
        if mode == "payment":
            pmt = pay_exact(principal, i, n, due)
            o.step("Level payment", "PMT = P · i / [1 − (1+i)^−n]" + (" / (1+i)" if due else ""), r"PMT = P\,\frac{i}{1 - (1+i)^{-n}}")
            total = pmt * n
            fee = fees_of(params, principal)
            out.update(payment=f.money(pmt), numberOfPayments=n, totalRepayment=f.money(total), totalInterest=f.money(total - principal))
            if fee:
                out["fees"] = f.money(fee)
                out["costOfBorrowing"] = f.money(total - principal + fee)
                net = principal - fee
                C.require(net > 0, "The fees are as large as the loan, so nothing is received", "feeAmount")
                ir = apr_for(net, pmt, n, per, due)
                if ir is None:
                    o.warn("No rate between −100 % and 1000 % per period reproduces the net proceeds, so no APR is shown.")
                else:
                    out["apr"] = f.percent(ir * per, label=f"nominal annual rate including the fee, compounded {per} times a year")
                    out["effectiveAnnualCostRate"] = f.percent(power(1 + ir, Fraction(per)) - 1, label="the same cost as one year's effective rate")
                    o.step("APR including the fee", "The rate at which principal − fee equals the present value of the payments (solved numerically at 60 digits).")
            out["effectiveAnnualRate"] = f.percent(power(1 + i, Fraction(per)) - 1, label="what the contract rate is worth over one year")
        elif mode == "linear":
            base = principal / n
            first = base + principal * i
            last = base + base * i if n > 0 else Fraction(0)
            interest_total = i * principal * Fraction(n + 1, 2)
            o.step("Equal principal repayments", "Each payment repays P / n of principal plus interest on the balance left; payments fall steadily.", r"P_k = \frac{P}{n} + i\,B_{k-1}")
            out.update(principalPerPayment=f.money(base), firstPayment=f.money(first), lastPayment=f.money(last), numberOfPayments=n,
                       totalInterest=f.money(interest_total), totalRepayment=f.money(principal + interest_total))
        else:
            k = C.count(params, "afterPayments", lo=0, hi=n, default=0, required=False) or 0
            pmt = pay_exact(principal, i, n, due)
            if due:
                bal = _balance_due(principal, i, pmt, k)
            else:
                g = (1 + i) ** k
                bal = principal * g - pmt * ((g - 1) / i if i != 0 else k)
            paid_interest = pmt * k - (principal - bal)
            o.step("Outstanding principal", "B_k = P(1+i)^k − PMT · [(1+i)^k − 1] / i", r"B_k = P(1+i)^{k} - PMT\,\frac{(1+i)^{k}-1}{i}")
            out.update(outstandingPrincipal=f.money(bal), principalRepaid=f.money(principal - bal), interestPaid=f.money(paid_interest), paymentsMade=k,
                       paymentsRemaining=n - k, payment=f.money(pmt))
    elif mode == "term":
        principal = frac(params, "principal", positive=True)
        pmt = frac(params, "payment", positive=True)
        if i == 0:
            nn = principal / pmt
        else:
            d = (1 + i) if due else Fraction(1)
            x = 1 - principal * i / (pmt * d)
            if x <= 0:
                raise BadRequest("This payment never repays the loan: it does not cover the interest.", details={"field": "payment"},
                                 hint=f"The payment must exceed {f.money(principal * i / d)['text']} per period.")
            nn = -C.ln(x) / C.ln(1 + i)
        o.step("Number of payments", "n = −ln(1 − P·i/PMT) / ln(1+i)", r"n = -\frac{\ln\left(1 - P\,i / PMT\right)}{\ln(1+i)}")
        whole = whole_up(nn)
        out.update(numberOfPayments=f.amount(nn, places=4), wholePayments={"text": str(whole), "latex": str(whole), "value": whole, "note": "the last payment is smaller"},
                   years=f.amount(nn / per, places=4, unit="years"), totalRepayment=f.money(pmt * nn), totalInterest=f.money(pmt * nn - principal))
    else:                                                                                              # borrow
        pmt = frac(params, "payment", positive=True)
        n, per = term(params)
        i = nominal / per
        a, _ = annuity_factors(i, n)
        principal = pmt * a * ((1 + i) if due else 1)
        o.step("Largest loan this payment services", "P = PMT · [1 − (1+i)^−n] / i", r"P = PMT\,\frac{1-(1+i)^{-n}}{i}")
        out.update(loanAmount=f.money(principal), totalRepayment=f.money(pmt * n), totalInterest=f.money(pmt * n - principal), numberOfPayments=n)
    return o.done(mode=mode, **out, **({"plot": plot, "graph": graph} if plot else {}))


def _balance_due(principal: Fraction, i: Fraction, pmt: Fraction, k: int) -> Fraction:
    """Balance after ``k`` payments when payments are made at the start of each period (the first accrues no interest)."""
    b = principal
    for _ in range(k):
        b = (b - pmt) * (1 + i)
    return b


# ================================================================================================================ schedules
def _rounder(places: int | None):
    if places is None:
        return lambda x: x
    unit = Fraction(1, 10 ** places)

    def r(x: Fraction) -> Fraction:
        q = x / unit
        n = q.numerator // q.denominator if q >= 0 else -((-q.numerator) // q.denominator)
        frac_part = q - n
        if frac_part * 2 >= 1 if q >= 0 else frac_part * 2 <= -1:
            n += 1 if q >= 0 else -1
        return n * unit
    return r


def build_schedule(principal: Fraction, i: Fraction, n: int, kind: str, due: bool, extra: Fraction, lump: Fraction, lump_at: int, places: int | None) -> dict[str, Any]:
    """The rows of a loan schedule and its totals. ``places`` is None for exact arithmetic, or the number of decimals to round each period to."""
    rnd = _rounder(places)
    bal = rnd(principal)
    rows: list[dict[str, Fraction | int]] = []
    pmt = rnd(pay_exact(bal, i, n, due)) if kind == "annuity" else Fraction(0)
    base = rnd(bal / n) if kind == "linear" else Fraction(0)
    start = 0
    if due and kind == "annuity":
        first = min(pmt, bal)                                                                     # pays down principal before any interest accrues
        rows.append({"k": 1, "payment": first, "interest": Fraction(0), "principal": first, "extra": Fraction(0), "balance": bal - first})
        bal -= first
        start = 1
    k = start
    while bal > 0:
        k += 1
        if k > MAX_ROWS + 1:
            raise BadRequest("The schedule is longer than 1200 periods.")
        interest = rnd(bal * i)
        extra_k = extra + (lump if k == lump_at else Fraction(0))
        last_scheduled = k >= n
        if kind == "annuity":
            if last_scheduled:
                pay = bal + interest                                                              # the final payment absorbs the rounding
            else:
                pay = min(pmt + extra_k, bal + interest)
            principal_k = pay - interest
            if principal_k > bal:
                principal_k = bal
                pay = bal + interest
        else:
            if last_scheduled:
                principal_k = bal
            else:
                principal_k = min(base + extra_k, bal)
            pay = principal_k + interest
        bal -= principal_k
        rows.append({"k": k, "payment": pay, "interest": interest, "principal": principal_k, "extra": extra_k, "balance": bal})
    total_interest = sum((r["interest"] for r in rows), Fraction(0))
    total_paid = sum((r["payment"] for r in rows), Fraction(0))
    total_principal = sum((r["principal"] for r in rows), Fraction(0))
    return {"rows": rows, "totalInterest": total_interest, "totalPaid": total_paid, "totalPrincipal": total_principal, "payment": pmt, "periods": len(rows)}


def cell(x: Fraction, places: int) -> dict[str, str]:
    return {"text": C.fmt_decimal(x, places, group=True), "latex": ""}


def op_amortization(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    kind = C.choice(params, "kind", ("annuity", "linear"), "annuity")
    due = C.choice(params, "timing", ("end", "begin"), "end") == "begin" and kind == "annuity"
    principal = frac(params, "principal", positive=True)
    nominal = rate(params, "rate")
    n, per = term(params)
    i = nominal / per
    extra = frac(params, "extra", nonneg=True, required=False) or Fraction(0)
    lump = frac(params, "lumpAmount", nonneg=True, required=False) or Fraction(0)
    lump_at = C.count(params, "lumpAt", lo=1, hi=n, default=1, required=False) or 1
    rounding = C.choice(params, "rounding", ("cents", "none"), "cents")
    places = f.places if rounding == "cents" else None
    note = C.rate_note(nominal * 100)
    if note:
        o.warn(note)
    assumptions(o, per, due)
    o.assume("Interest for a period is the balance at the start of the period times the periodic rate. Extra payments reduce principal in the period they are paid, and the regular payment stays the same, so the loan ends sooner.")
    if rounding == "cents":
        unit = "1" if f.places == 0 else "0." + "0" * (f.places - 1) + "1"
        o.assume(f"Each period's interest is rounded half away from zero to the smallest unit ({unit}); the last payment is adjusted by the accumulated rounding, so the principal repaid equals the loan and the final balance is exactly zero.")
        if places is not None and principal != _rounder(places)(principal):
            o.warn(f"The principal has more decimals than the currency's smallest unit; it was rounded to {C.fmt_decimal(_rounder(places)(principal), places)}.")
    else:
        o.assume("No rounding: every amount is kept exact (60 significant digits where the arithmetic is not rational) and only the display is rounded.")
    if kind == "linear":
        o.assume("Linear repayment: the principal repaid each period is the loan divided by the number of payments; interest falls as the balance falls.")

    sch = build_schedule(principal, i, n, kind, due, extra, lump, lump_at, places)
    base = build_schedule(principal, i, n, kind, due, Fraction(0), Fraction(0), 1, places) if (extra or lump) else sch
    rows = sch["rows"]
    show = places if places is not None else max(f.places, 2)

    final_balance = rows[-1]["balance"]
    closes = final_balance == 0 and sch["totalPrincipal"] == (_rounder(places)(principal) if places is not None else principal)
    table = []
    for r in rows:
        row: dict[str, Any] = {"payment": r["k"], "paid": cell(r["payment"], show), "interest": cell(r["interest"], show), "principal": cell(r["principal"], show)}
        if extra or lump:
            row["extraIncluded"] = cell(r["extra"], show)
        row["balance"] = cell(r["balance"], show)
        table.append(row)
    for r in table:
        r["period"] = r.pop("payment")
    table = [{"period": r["period"], **{k: v for k, v in r.items() if k != "period"}} for r in table]

    yearly: list[dict[str, Any]] = []
    by_year: dict[int, dict[str, Fraction]] = {}
    for r in rows:
        y = (int(r["k"]) - 1) // per + 1
        e = by_year.setdefault(y, {"interest": Fraction(0), "principal": Fraction(0), "paid": Fraction(0), "balance": Fraction(0)})
        e["interest"] += r["interest"]
        e["principal"] += r["principal"]
        e["paid"] += r["payment"]
        e["balance"] = r["balance"]
    for y, e in by_year.items():
        yearly.append({"year": y, "paid": cell(e["paid"], show), "interest": cell(e["interest"], show), "principal": cell(e["principal"], show), "endBalance": cell(e["balance"], show)})

    res: dict[str, Any] = {}
    if kind == "annuity":
        res["regularPayment"] = f.money(sch["payment"])
    else:
        res["firstPayment"] = f.money(rows[0]["payment"])
        res["lastPayment"] = f.money(rows[-1]["payment"])
    res.update(numberOfPayments=sch["periods"], totalInterest=f.money(sch["totalInterest"]), totalPaid=f.money(sch["totalPaid"]), finalPayment=f.money(rows[-1]["payment"]))
    if extra or lump:
        res["interestSaved"] = f.money(base["totalInterest"] - sch["totalInterest"])
        res["paymentsSaved"] = base["periods"] - sch["periods"]
        res["withoutExtraPayments"] = {"totalInterest": f.money(base["totalInterest"]), "numberOfPayments": base["periods"]}
    res["checks"] = {"principalRepaidEqualsLoan": "yes" if closes else "NO", "finalBalance": f.money(final_balance)}
    if not closes:
        o.warn("The schedule did not close exactly; please report this input.")
    o.step("Each period", "interest = balance × i;  principal = payment − interest;  new balance = balance − principal", r"I_k = i\,B_{k-1},\quad B_k = B_{k-1} - (PMT - I_k)")

    pts_bal = [(0.0, to_float(principal))] + [(int(r["k"]) / per, to_float(r["balance"])) for r in rows]
    plot = C.plot_block("Loan balance", "Years", "Balance" + (f" ({f.code})" if f.has_currency else ""), [{"label": "Outstanding principal", "points": [[x, y] for x, y in pts_bal], "kind": "line"}],
                        description="The principal still owed after each payment.", zero_line=True)
    pts_int = [(y, to_float(e["interest"])) for y, e in by_year.items()]
    pts_pri = [(y, to_float(e["principal"])) for y, e in by_year.items()]
    plot2 = C.plot_block("Interest and principal paid each year", "Year", "Amount per year", [{"label": "Interest", "points": [[x, y] for x, y in pts_int], "kind": "line"},
                                                                                           {"label": "Principal", "points": [[x, y] for x, y in pts_pri], "kind": "line"}],
                         description="How each year's payments split between interest and principal.")
    graph = C.graph_spec([{"type": "scatter", "data": C.points_text(pts_bal), "color": "#b89b00", "label": "Balance"}], viewport=C.pad_view([x for x, _ in pts_bal], [y for _, y in pts_bal]))
    graph_split = C.graph_spec([{"type": "scatter", "data": C.points_text(pts_int), "color": "#d6572b", "label": "Interest"},
                                {"type": "scatter", "data": C.points_text(pts_pri), "color": "#2f6fdb", "label": "Principal"}],
                               viewport=C.pad_view([x for x, _ in pts_int], [y for _, y in pts_int + pts_pri]))
    return o.done(kind=kind, **res, schedule=table, yearlySummary=yearly, plot=plot, plot2=plot2, graph=graph, graph2=graph_split)


# ================================================================================================================ comparison
def op_loan_compare(params: dict, settings: Settings) -> dict:
    o = Result(settings, params)
    f = o.f
    raw = params.get("scenarios")
    if not isinstance(raw, list) or not raw:
        raise BadRequest("Add at least two loan scenarios to compare.", details={"field": "scenarios"})
    if len(raw) > 12:
        raise BadRequest("At most 12 scenarios can be compared.", details={"field": "scenarios"})
    due = C.choice(params, "timing", ("end", "begin"), "end") == "begin"
    o.assume("Each scenario is a fixed-rate loan. The nominal annual rate is compounded at that scenario's payment frequency; payments are at the "
             + ("beginning" if due else "end") + " of each period.")
    o.assume("The cost of borrowing is total interest plus fees. The APR is the nominal annual rate (compounded at the payment frequency) that equates the money received (principal − fees) with the payments.")
    rows = []
    for idx, sc in enumerate(raw):
        if not isinstance(sc, dict):
            raise BadRequest(f"Scenario {idx + 1} must be a row of values", details={"field": "scenarios"})
        name = str(sc.get("name") or f"Scenario {idx + 1}")[:60]
        try:
            p = {**params, **sc}
            principal = frac(p, "principal", positive=True)
            nominal = rate(p, "rate")
            n, per = term(p)
            fee = frac(p, "fee", nonneg=True, required=False) or Fraction(0)
        except BadRequest as exc:
            exc.details = {**exc.details, "field": "scenarios", "row": idx + 1}
            exc.args = (f"Scenario {idx + 1} ('{name}'): {exc.message}",)
            exc.message = exc.args[0]
            raise
        i = nominal / per
        pmt = pay_exact(principal, i, n, due)
        total = pmt * n
        net = principal - fee
        C.require(net > 0, f"Scenario {idx + 1}: the fee is as large as the loan", "scenarios")
        ir = apr_for(net, pmt, n, per, due)
        rows.append({"name": name, "principal": principal, "rate": nominal, "n": n, "per": per, "pmt": pmt, "interest": total - principal, "fee": fee, "cost": total - principal + fee,
                     "total": total + fee, "apr": None if ir is None else ir * per})
    cheapest = min(range(len(rows)), key=lambda k: rows[k]["cost"])
    best_apr = min((k for k in range(len(rows)) if rows[k]["apr"] is not None), key=lambda k: rows[k]["apr"], default=None)
    table = []
    for k, r in enumerate(rows):
        table.append({"scenario": r["name"], "loan": f.money(r["principal"], unit=False), "rate": f.percent(r["rate"]), "payments": r["n"], "payment": f.money(r["pmt"], unit=False),
                      "totalInterest": f.money(r["interest"], unit=False), "fees": f.money(r["fee"], unit=False), "costOfBorrowing": f.money(r["cost"], unit=False),
                      "apr": f.percent(r["apr"]) if r["apr"] is not None else "—", "vsFirst": f.money(r["cost"] - rows[0]["cost"], unit=False) if k else "—"})
    out = {"scenarios": table, "lowestCostOfBorrowing": rows[cheapest]["name"]}
    if best_apr is not None:
        out["lowestApr"] = rows[best_apr]["name"]
    if len({r["principal"] for r in rows}) > 1:
        o.warn("The scenarios borrow different amounts, so the cost of borrowing is not directly comparable; compare the APR instead.")
    labels = [r["name"] for r in rows]
    plot = C.plot_block("Cost of borrowing by scenario", "Scenario number", "Cost of borrowing", [{"label": "Interest + fees", "points": [[k + 1, to_float(r["cost"])] for k, r in enumerate(rows)], "kind": "scatter"}],
                        description="Total interest plus fees for each scenario (numbered in the order of the table: " + "; ".join(f"{k + 1} = {n}" for k, n in enumerate(labels)) + ").")
    return o.done(headline=f"Lowest cost of borrowing: {rows[cheapest]['name']}", **out, plot=plot)
