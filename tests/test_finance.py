"""Finance: every number is checked against a computation that does not share code with the operation (Decimal closed forms, brute-force sums, round trips)."""
import json
import math
import unittest
from decimal import Decimal, getcontext
from fractions import Fraction

from scical.core.numerical.context import Settings
from scical.domains.finance import OPS
from scical.domains.finance import core as C
from scical.domains.finance.investment import irr_roots, mirr_of, npv_of, sign_changes
from scical.errors import BadRequest
from scical.services.tasks import run

S = Settings()
getcontext().prec = 60


def call(op, **p):
    res = OPS[op](p, S)
    json.dumps(res, allow_nan=False)
    return res


def value(res, key):
    return Decimal(str(res[key]["value"])) if "value" in res[key] else None


def exact(res, key):
    """The carried (unrounded) value of a result as a Decimal, from its text when it is exact."""
    return Decimal(res[key]["exact"].rstrip("…").split(" ")[0])


class Rounding(unittest.TestCase):
    def test_half_up_on_the_exact_decimal_not_the_float(self):
        self.assertEqual(C.fmt_decimal(Fraction("2.675"), 2), "2.68")             # a float would give 2.67
        self.assertEqual(C.fmt_decimal(Fraction("0.125"), 2), "0.13")
        self.assertEqual(C.fmt_decimal(Fraction("-0.125"), 2), "-0.13")
        self.assertEqual(C.fmt_decimal(Fraction("-0.001"), 2), "0.00")
        self.assertEqual(C.fmt_decimal(Fraction(1234567, 100), 2, group=True), "12,345.67")

    def test_currency_places_and_symbols(self):
        r = call("interest", mode="compound", pv="1000", rate="5", years="10", freq=12, currency="JPY")
        self.assertEqual(r["futureValue"]["text"], "¥1,647")
        r = call("interest", mode="compound", pv="1000", rate="5", years="10", freq=12, currency="EUR", places=3)
        self.assertEqual(r["futureValue"]["text"], "€1,647.009")

    def test_display_rounding_never_feeds_a_later_step(self):
        r = call("interest", mode="compound", pv="1000", rate="5", years="10", freq=12, places=0)
        self.assertEqual(r["futureValue"]["text"], "1,647")
        self.assertEqual(r["interestEarned"]["text"], "647")
        self.assertTrue(r["futureValue"]["exact"].startswith("1647.00949769"))


class Interest(unittest.TestCase):
    def test_compound_matches_decimal_closed_form(self):
        r = call("interest", mode="compound", pv="1000", rate="5", years="10", freq=12)
        want = Decimal(1000) * (1 + Decimal("0.05") / 12) ** 120
        self.assertAlmostEqual(float(exact(r, "futureValue") - want), 0, places=18)          # the shown exact text has 20 decimals

    def test_continuous_and_simple(self):
        r = call("interest", mode="continuous", pv="1000", rate="5", years="10")
        self.assertAlmostEqual(r["futureValue"]["value"], 1000 * math.exp(0.5), places=9)
        r = call("interest", mode="simple", pv="1000", rate="5", years="10")
        self.assertEqual(r["futureValue"]["text"], "1,500.00")

    def test_percent_sign_and_plain_percent_agree(self):
        a = call("interest", mode="compound", pv="1000", rate="5%", years="3", freq=1)
        b = call("interest", mode="compound", pv="1000", rate="5", years="3", freq=1)
        self.assertEqual(a["futureValue"]["text"], b["futureValue"]["text"])
        self.assertEqual(b["futureValue"]["text"], "1,157.63")

    def test_small_typed_rate_is_flagged_as_percent(self):
        r = call("interest", mode="compound", pv="1000", rate="0.05", years="1", freq=1)
        self.assertTrue(any("read as 0.05 %" in w for w in r["warnings"]))

    def test_every_unknown_round_trips(self):
        base = dict(mode="compound", freq=4)
        fv = call("interest", pv="2500", rate="3.7", years="6.25", **base)["futureValue"]["value"]
        self.assertAlmostEqual(call("interest", fv=str(fv), rate="3.7", years="6.25", **base)["principal"]["value"], 2500, places=4)
        self.assertAlmostEqual(call("interest", pv="2500", fv=str(fv), years="6.25", **base)["rate"]["value"], 3.7, places=5)
        self.assertAlmostEqual(call("interest", pv="2500", fv=str(fv), rate="3.7", **base)["years"]["value"], 6.25, places=4)

    def test_zero_rate_and_boundaries(self):
        r = call("interest", mode="compound", pv="1000", rate="0", years="5", freq=12)
        self.assertEqual(r["futureValue"]["text"], "1,000.00")
        with self.assertRaises(BadRequest):
            call("interest", mode="compound", pv="1000", fv="1000", rate="0", freq=12)          # time cannot be found at 0 %
        with self.assertRaises(BadRequest):
            call("interest", mode="compound", pv="1000", rate="5", years="10", freq=0)          # invalid compounding frequency
        with self.assertRaises(BadRequest):
            call("interest", mode="compound", pv="-5", rate="5", years="1", freq=1)             # negative principal
        with self.assertRaises(BadRequest):
            call("interest", mode="compound", pv="1000", rate="-2400", years="0.55", freq=12)   # base 1 + r/n < 0 with a fractional power

    def test_rate_conversion_against_decimal(self):
        r = call("rate_conversion", mode="nominal", rate="12", freq=12)
        want = (1 + Decimal("0.12") / 12) ** 12 - 1
        self.assertAlmostEqual(float(Decimal(r["effectiveAnnualRate"]["exact"].split(" ")[0].rstrip("…")) - want), 0, places=30)
        monthly = next(x for x in r["equivalents"] if x["perYear"] == 12)
        self.assertEqual(monthly["nominalRate"]["text"], "12.00 %")
        self.assertAlmostEqual(next(x for x in r["equivalents"] if x["perYear"] == 1)["nominalRate"]["value"], float(want) * 100, places=9)

    def test_fisher(self):
        r = call("real_rate", nominal="5", inflation="2")
        self.assertAlmostEqual(r["realRate"]["value"], (1.05 / 1.02 - 1) * 100, places=10)
        self.assertAlmostEqual(r["shortcutError"]["value"], (3 - (1.05 / 1.02 - 1) * 100), places=9)


class Annuities(unittest.TestCase):
    def test_pv_and_fv_equal_the_sum_of_the_payments(self):
        i = Fraction(6, 1200)
        pv = sum(Fraction(100) / (1 + i) ** k for k in range(1, 61))
        fv = sum(Fraction(100) * (1 + i) ** (60 - k) for k in range(1, 61))
        self.assertAlmostEqual(call("annuity", mode="pv", pmt="100", rate="6", periods=60, perYear=12)["presentValue"]["value"], float(pv), places=9)
        self.assertAlmostEqual(call("annuity", mode="fv", pmt="100", rate="6", periods=60, perYear=12)["futureValue"]["value"], float(fv), places=9)

    def test_annuity_due_is_one_period_later(self):
        a = call("annuity", mode="pv", pmt="100", rate="6", periods=60, perYear=12)["presentValue"]["value"]
        d = call("annuity", mode="pv", pmt="100", rate="6", periods=60, perYear=12, timing="begin")["presentValue"]["value"]
        self.assertAlmostEqual(d, a * 1.005, places=8)

    def test_solving_for_the_rate_round_trips(self):
        pv = call("annuity", mode="pv", pmt="250", rate="7.3", periods=48, perYear=12)["presentValue"]["exact"].split(" ")[0].rstrip("…")
        r = call("annuity", mode="rate_for_pv", pmt="250", pv=pv, periods=48, perYear=12)
        self.assertAlmostEqual(r["rate"]["value"], 7.3, places=6)

    def test_periods_and_payment(self):
        n = call("annuity", mode="periods_for_pv", pmt="500", pv="10000", rate="6", perYear=12)
        i = 0.005
        self.assertAlmostEqual(n["periods"]["value"], -math.log(1 - 10000 * i / 500) / math.log(1 + i), places=8)
        with self.assertRaises(BadRequest):                                                   # payment below the interest: never repaid
            call("annuity", mode="periods_for_pv", pmt="40", pv="10000", rate="6", perYear=12)
        p = call("annuity", mode="payment_for_fv", pv="0", fv="10000", rate="5", periods=120, perYear=12)
        j = 0.05 / 12
        self.assertAlmostEqual(p["payment"]["value"], 10000 * j / ((1 + j) ** 120 - 1), places=8)

    def test_perpetuity(self):
        self.assertEqual(call("perpetuity", mode="pv", payment="100", rate="5")["presentValue"]["text"], "2,000.00")
        self.assertEqual(call("perpetuity", mode="pv", payment="100", rate="8", growth="3")["presentValue"]["text"], "2,000.00")
        with self.assertRaises(BadRequest):
            call("perpetuity", mode="pv", payment="100", rate="3", growth="3")


class Loans(unittest.TestCase):
    def test_payment_matches_decimal(self):
        r = call("loan", mode="payment", principal="200000", rate="6", years="30", perYear=12)
        i = Decimal("0.06") / 12
        want = 200000 * i / (1 - (1 + i) ** -360)
        self.assertAlmostEqual(float(exact(r, "payment") - want), 0, places=18)
        self.assertEqual(r["payment"]["text"], "1,199.10")
        self.assertEqual(r["totalInterest"]["text"], "231,676.38")

    def test_zero_rate_loan(self):
        r = call("loan", mode="payment", principal="12000", rate="0", years="1", perYear=12)
        self.assertEqual(r["payment"]["text"], "1,000.00")
        self.assertEqual(r["totalInterest"]["text"], "0.00")

    def test_term_borrow_and_balance_round_trip(self):
        pay = call("loan", mode="payment", principal="150000", rate="4.5", years="20", perYear=12)["payment"]["exact"].split(" ")[0].rstrip("…")
        back = call("loan", mode="borrow", payment=pay, rate="4.5", years="20", perYear=12)
        self.assertAlmostEqual(back["loanAmount"]["value"], 150000, places=6)
        bal = call("loan", mode="balance", principal="150000", rate="4.5", years="20", perYear=12, afterPayments=240)
        self.assertEqual(bal["outstandingPrincipal"]["text"], "0.00")
        i = Fraction(45, 12000)
        b = Fraction(150000)
        p = Fraction(pay) if "." not in pay else Fraction(Decimal(pay))
        for _ in range(100):
            b = b * (1 + i) - p
        got = call("loan", mode="balance", principal="150000", rate="4.5", years="20", perYear=12, afterPayments=100)["outstandingPrincipal"]["value"]
        self.assertAlmostEqual(got, float(b), delta=0.01)

    def test_term_mode_rejects_a_payment_below_the_interest(self):
        with self.assertRaises(BadRequest):
            call("loan", mode="term", principal="100000", rate="6", payment="400", perYear=12)

    def test_non_whole_number_of_payments_is_rejected(self):
        with self.assertRaises(BadRequest):
            call("loan", mode="payment", principal="1000", rate="5", years="0.35", perYear=12)

    def test_fee_apr_reproduces_the_net_proceeds(self):
        r = call("loan", mode="payment", principal="200000", rate="6", years="30", perYear=12, feeAmount="2000")
        apr = Fraction(Decimal(str(r["apr"]["value"])) / 100) / 12
        pmt = Fraction(Decimal(r["payment"]["exact"].split(" ")[0].rstrip("…")))
        pv = pmt * (1 - (1 + apr) ** -360) / apr
        self.assertAlmostEqual(float(pv), 198000, delta=0.5)
        self.assertGreater(r["apr"]["value"], 6)

    def test_annuity_schedule_closes_exactly(self):
        for rounding in ("cents", "none"):
            r = call("amortization", kind="annuity", principal="200000", rate="6", years="30", perYear=12, rounding=rounding)
            rows = r["schedule"]
            self.assertEqual(len(rows), 360)
            self.assertEqual(rows[-1]["balance"]["text"], "0.00")
            self.assertEqual(r["checks"]["principalRepaidEqualsLoan"], "yes")
        r = call("amortization", kind="annuity", principal="200000", rate="6", years="30", perYear=12, rounding="cents")
        tot = sum(Decimal(row["principal"]["text"].replace(",", "")) for row in r["schedule"])
        self.assertEqual(tot, Decimal(200000))                                                  # integer-cent arithmetic: no drift
        ti = sum(Decimal(row["interest"]["text"].replace(",", "")) for row in r["schedule"])
        self.assertEqual(f"{ti:,.2f}", r["totalInterest"]["text"])

    def test_cents_schedule_close_to_exact_one(self):
        c = call("amortization", kind="annuity", principal="200000", rate="6", years="30", perYear=12, rounding="cents")["totalInterest"]["value"]
        e = call("amortization", kind="annuity", principal="200000", rate="6", years="30", perYear=12, rounding="none")["totalInterest"]["value"]
        self.assertAlmostEqual(c, e, delta=2)

    def test_linear_loan_closed_form(self):
        r = call("amortization", kind="linear", principal="12000", rate="12", years="1", perYear=12, rounding="none")
        self.assertEqual(r["totalInterest"]["text"], "780.00")                                 # i·P·(n+1)/2 = 0.01·12000·6.5
        self.assertEqual(r["firstPayment"]["text"], "1,120.00")
        self.assertEqual(r["lastPayment"]["text"], "1,010.00")

    def test_extra_payments_shorten_the_loan_and_save_interest(self):
        r = call("amortization", kind="annuity", principal="10000", rate="6", years="2", perYear=12, extra="100", rounding="none")
        self.assertEqual(r["numberOfPayments"], 20)
        self.assertGreater(r["interestSaved"]["value"], 100)
        self.assertEqual(r["schedule"][-1]["balance"]["text"], "0.00")

    def test_annuity_due_schedule_first_payment_pays_no_interest(self):
        r = call("amortization", kind="annuity", principal="1200", rate="12", years="1", perYear=12, timing="begin", rounding="none")
        self.assertEqual(r["schedule"][0]["interest"]["text"], "0.00")
        self.assertEqual(r["schedule"][-1]["balance"]["text"], "0.00")

    def test_comparison_ranks_by_cost(self):
        r = call("loan_compare", principal="200000", perYear=12, scenarios=[{"name": "A", "rate": "6", "years": "30", "fee": "0"}, {"name": "B", "rate": "5.5", "years": "15", "fee": "1500"}])
        self.assertEqual(r["lowestCostOfBorrowing"], "B")
        with self.assertRaises(BadRequest):
            call("loan_compare", principal="200000", scenarios=[])
        with self.assertRaises(BadRequest):
            call("loan_compare", principal="200000", scenarios=[{"name": "A", "rate": "6"}])             # no term


class Investment(unittest.TestCase):
    def test_npv_exact(self):
        flows = [Fraction(-1000), Fraction(300), Fraction(400), Fraction(500), Fraction(200)]
        r = call("npv", flows=["-1000", "300", "400", "500", "200"], rate="8")
        self.assertAlmostEqual(r["npv"]["value"], float(npv_of(flows, Fraction(8, 100))), places=9)
        self.assertEqual(r["npv"]["text"], "164.64")

    def test_irr_is_a_root_and_matches_known_values(self):
        flows = [Fraction(x) for x in (-1000, 300, 400, 500, 200)]
        roots, how, changes = irr_roots(flows)
        self.assertEqual((len(roots), how, changes), (1, "exact", 1))
        self.assertLess(abs(npv_of(flows, roots[0])), Fraction(1, 10 ** 40))
        self.assertAlmostEqual(float(roots[0]), 0.1532213, places=6)

    def test_multiple_irrs_are_all_found_and_never_called_unique(self):
        flows = [Fraction(-100), Fraction(230), Fraction(-132)]                                # NPV = 0 at 10 % and 20 %
        roots, _, changes = irr_roots(flows)
        self.assertEqual(changes, 2)
        self.assertEqual([round(float(x), 9) for x in roots], [0.1, 0.2])
        r = call("irr", flows=["-100", "230", "-132"])
        self.assertEqual(r["numberOfIrrs"], 2)
        self.assertNotIn("irr", r)
        self.assertIn("not unique", r["status"])
        self.assertTrue(r["warnings"])

    def test_three_roots_from_a_cubic(self):
        roots, _, changes = irr_roots([Fraction(-6), Fraction(11), Fraction(-6), Fraction(1)])      # x = 1/(1+r) with x = 1, 2, 3
        self.assertEqual(changes, 3)
        self.assertEqual([round(float(r), 9) for r in roots], [round(-2 / 3, 9), -0.5, 0.0])

    def test_no_irr_cases(self):
        r = call("irr", flows=["100", "200", "300"])
        self.assertEqual(r["numberOfIrrs"], 0)
        self.assertIn("no IRR", r["status"])
        r = call("irr", flows=["-100", "10", "-5"])                                           # sign changes, but NPV never reaches zero above −100 %
        self.assertEqual(r["numberOfIrrs"], 0)

    def test_double_root_is_found(self):
        # (x - 2)^2 = x^2 - 4x + 4 -> flows 4, -4, 1 : sign changes 2, double root x = 2 (r = -1/2)
        roots, _, _ = irr_roots([Fraction(4), Fraction(-4), Fraction(1)])
        self.assertEqual([round(float(r), 9) for r in roots], [-0.5])

    def test_long_flows_use_a_scan_and_say_so(self):
        r = call("irr", flows=["-1000"] + ["30"] * 100 + ["-5"])
        self.assertEqual(r["method"], "scan")
        self.assertTrue(any("scanning" in w for w in r["warnings"]))
        self.assertGreaterEqual(r["numberOfIrrs"], 1)

    def test_mirr_formula(self):
        flows = [Fraction(x) for x in (-1000, 300, 400, 500, 200)]
        m = mirr_of(flows, Fraction(6, 100), Fraction(8, 100))
        pos = sum(float(c) * 1.08 ** (4 - k) for k, c in enumerate(flows) if c > 0)
        self.assertAlmostEqual(float(m), (pos / 1000) ** 0.25 - 1, places=10)

    def test_roi_cagr(self):
        r = call("roi", cost="1000", value="1500", income="100", years="3")
        self.assertEqual(r["roi"]["text"], "60.00 %")
        self.assertAlmostEqual(r["annualizedRoi"]["value"], (1.6 ** (1 / 3) - 1) * 100, places=9)
        self.assertAlmostEqual(call("cagr", begin="100", end="200", years="5")["cagr"]["value"], (2 ** 0.2 - 1) * 100, places=9)
        self.assertAlmostEqual(call("cagr", begin="100", end="200", rate="10")["years"]["value"], math.log(2) / math.log(1.1), places=9)

    def test_dcf_matches_sum(self):
        r = call("dcf", mode="gordon", firstFlow="100", growth="5", years=5, rate="10", terminalGrowth="2")
        flows = [100 * 1.05 ** k for k in range(5)]
        pv = sum(c / 1.1 ** (k + 1) for k, c in enumerate(flows))
        tv = flows[-1] * 1.02 / 0.08 / 1.1 ** 5
        self.assertAlmostEqual(r["totalValue"]["value"], pv + tv, places=7)
        with self.assertRaises(BadRequest):
            call("dcf", mode="gordon", firstFlow="100", growth="5", years=5, rate="2", terminalGrowth="3")

    def test_payback_interpolation(self):
        r = call("payback", flows=["-1000", "300", "400", "500", "200"], rate="8")
        self.assertAlmostEqual(r["paybackPeriod"]["value"], 2.6, places=9)
        self.assertGreater(r["discountedPaybackPeriod"]["value"], 2.6)
        r = call("payback", flows=["-1000", "100", "100"])
        self.assertEqual(r["paybackPeriod"], "not within the cash flows given")

    def test_growth_scenarios(self):
        r = call("investment_growth", initial="1000", contribution="100", years="10", perYear=12, rates=["5"], inflation="2")
        i = Fraction(5, 1200)
        want = 1000 * (1 + i) ** 120 + 100 * ((1 + i) ** 120 - 1) / i
        self.assertEqual(r["scenarios"][0]["finalValue"]["text"], f"{Decimal(want.numerator) / Decimal(want.denominator):,.2f}")


class Economics(unittest.TestCase):
    def test_inflation(self):
        self.assertEqual(call("inflation", mode="future_cost", amount="100", inflation="3", years="10")["futureCost"]["text"], f"{100 * Decimal('1.03') ** 10:,.2f}")
        self.assertEqual(call("inflation", mode="cpi", amount="100", cpiFrom="250", cpiTo="300")["adjustedAmount"]["text"], "120.00")
        a = call("inflation", mode="average_rate", cpiFrom="250", cpiTo="300", years="5")["averageInflation"]["value"]
        self.assertAlmostEqual(a, (1.2 ** 0.2 - 1) * 100, places=9)

    def test_percent_change(self):
        r = call("percent_change", mode="change", old="80", new="100")
        self.assertEqual(r["percentChange"]["text"], "25.00 %")
        self.assertEqual(r["changeNeededToReturn"]["text"], "-20.00 %")
        with self.assertRaises(BadRequest):
            call("percent_change", mode="change", old="0", new="5")
        r = call("percent_change", mode="successive", percents=["10", "-10", "20"])
        self.assertEqual(r["totalChange"]["text"], "18.8000 %")
        self.assertNotEqual(r["simpleSum"]["text"], r["totalChange"]["text"])

    def test_elasticity(self):
        r = call("elasticity", mode="midpoint", price1="10", quantity1="100", price2="12", quantity2="80")
        self.assertAlmostEqual(r["elasticity"]["value"], (-20 / 90) / (2 / 11), places=9)
        self.assertEqual(r["revenueEffectOfRaisingPrice"], "revenue falls")
        f = call("elasticity", mode="function", demand="100 - 2*P", price="20")
        self.assertAlmostEqual(f["elasticity"]["value"], -2 * 20 / 60, places=9)
        f = call("elasticity", mode="function", demand="100/P", price="5")
        self.assertAlmostEqual(f["elasticity"]["value"], -1, places=9)                          # unit elastic everywhere
        with self.assertRaises(BadRequest):
            call("elasticity", mode="function", demand="100 - 2*P", price="50")                # quantity zero: undefined
        with self.assertRaises(BadRequest):
            call("elasticity", mode="function", demand="100 - 2*x", price="5")                 # wrong variable

    def test_break_even(self):
        r = call("break_even", fixedCosts="10000", price="25", variableCost="15", expectedUnits="1500", targetProfit="2000")
        self.assertEqual(r["breakEvenUnits"]["text"], "1,000.0000")
        self.assertEqual(r["profitAtExpectedUnits"]["text"], "5,000.00")
        self.assertEqual(r["marginOfSafety"]["text"], "33.3333 %")
        with self.assertRaises(BadRequest):
            call("break_even", fixedCosts="10000", price="10", variableCost="15")

    def test_cost_revenue_optimum_and_marginals(self):
        r = call("cost_revenue", cost="100 + 2*q + 0.5*q^2", price="80 - q", quantity="10")
        self.assertEqual(r["profitMaximum"]["quantity"]["text"], "26.000000")
        self.assertEqual(r["profitMaximum"]["profit"]["text"], "914.00")                      # -1.5·26² + 78·26 − 100
        self.assertEqual(r["atQuantity"]["marginalCost"]["text"], "12.00")
        self.assertEqual(r["atQuantity"]["marginalRevenue"]["text"], "60.00")
        self.assertEqual(r["marginalCostFunction"]["text"], "q + 2")
        with self.assertRaises(BadRequest):
            call("cost_revenue", cost="q", price="80 - q", revenue="80*q")

    def test_equilibrium_surplus_and_tax(self):
        r = call("market_equilibrium", demand="100 - 2*P", supply="10 + 3*P", tax="5")
        self.assertEqual(r["equilibriumPrice"]["text"], "18.00")
        self.assertEqual(r["equilibriumQuantity"]["text"], "64.000000")
        self.assertEqual(r["consumerSurplus"]["text"], "1,024.00")                           # ½(50 − 18)·64
        self.assertEqual(r["producerSurplus"]["text"], "682.67")                              # ½(18 + 10/3)·64
        t = r["tax"]
        self.assertEqual((t["buyersPay"]["text"], t["sellersReceive"]["text"], t["quantity"]["text"]), ("21.00", "16.00", "58.000000"))
        self.assertEqual(t["deadweightLoss"]["text"], "15.00")                               # ½·5·(64 − 58)
        r = call("market_equilibrium", demand="100 - 2*P", supply="10 + 3*P", mode="ceiling", controlPrice="10")
        self.assertEqual(r["priceControl"]["shortage"]["text"], "40.000000")
        with self.assertRaises(BadRequest):
            call("market_equilibrium", demand="10 - P", supply="20 + P")


class Analysis(unittest.TestCase):
    def test_growth_compare_ranks(self):
        r = call("growth_compare", series=[{"name": "A", "begin": "100", "end": "150", "years": "5"}, {"name": "B", "begin": "50", "end": "90", "years": "6"}])
        self.assertEqual(r["fastest"], "B")
        self.assertAlmostEqual(r["comparison"][1]["cagr"]["value"], ((90 / 50) ** (1 / 6) - 1) * 100, places=9)

    def test_trend_uses_least_squares(self):
        ys = [100, 108, 117, 126, 138, 149, 161, 175]
        r = call("trend", values=[str(y) for y in ys], model="linear")
        n = len(ys)
        xs = list(range(1, n + 1))
        mx, my = sum(xs) / n, sum(ys) / n
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        self.assertAlmostEqual(r["slopePerObservation"]["value"], slope, places=6)
        self.assertTrue(r["slopePerObservation"]["approximate"])
        r = call("trend", values=[str(y) for y in ys], model="linear", forecast=2)
        self.assertEqual(len(r["projection"]), 2)
        self.assertTrue(any("projection" in w.lower() for w in r["warnings"]))

    def test_sensitivity_tables_agree_with_the_loan_op(self):
        r = call("sensitivity", mode="loan_payment", amount="200000", rates=["6"], yearsList=["30"], perYear=12)
        self.assertEqual(r["table"][0]["30 years"]["text"], "1,199.10")
        r = call("sensitivity", mode="npv", flows=["-1000", "300", "400", "500", "200"], rateFrom="0", rateTo="30", steps=6)
        self.assertEqual(len(r["table"]), 7)
        self.assertTrue(r["internalRates"][0].startswith("15.3221"))


class Wiring(unittest.TestCase):
    def test_every_operation_is_reachable_through_the_task_runner(self):
        from scical.domains import forms
        ids = {o["id"] for o in forms.catalogue()["finance"]["ops"]}
        self.assertEqual(ids, set(OPS))
        for oid in OPS:
            o = next(o for o in forms.catalogue()["finance"]["ops"] if o["id"] == oid)
            res = run({"kind": "domain", "domain": "finance", "op": oid, "params": o["example"], "settings": {}})
            self.assertTrue(res["ok"], (oid, res))
            self.assertTrue(res.get("assumptions") or oid in ("percent_change",), oid)

    def test_errors_are_explained_not_raised_as_crashes(self):
        res = run({"kind": "domain", "domain": "finance", "op": "loan", "params": {"mode": "payment", "principal": "-5", "rate": "5", "years": "10"}, "settings": {}})
        self.assertFalse(res["ok"])
        self.assertIn("greater than 0", res["error"]["message"])


if __name__ == "__main__":
    unittest.main()
