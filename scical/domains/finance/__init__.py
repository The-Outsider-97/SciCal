"""Economics & Finance: interest, loans, investment appraisal, economics and growth analysis.

Money is exact (``Fraction``); transcendental steps use 60-digit mpmath; display rounding is separate from calculation.
Every op is ``fn(params, settings) -> dict`` like the other SciCal domains.
"""
from __future__ import annotations

from . import analysis, economics, interest, investment, loans

OPS = {
    "interest": interest.op_interest,
    "rate_conversion": interest.op_rate_conversion,
    "real_rate": interest.op_real_rate,
    "annuity": interest.op_annuity,
    "perpetuity": interest.op_perpetuity,
    "loan": loans.op_loan,
    "amortization": loans.op_amortization,
    "loan_compare": loans.op_loan_compare,
    "roi": investment.op_roi,
    "cagr": investment.op_cagr,
    "npv": investment.op_npv,
    "dcf": investment.op_dcf,
    "irr": investment.op_irr,
    "payback": investment.op_payback,
    "investment_growth": investment.op_investment_growth,
    "inflation": economics.op_inflation,
    "percent_change": economics.op_percent_change,
    "elasticity": economics.op_elasticity,
    "break_even": economics.op_break_even,
    "cost_revenue": economics.op_cost_revenue,
    "market_equilibrium": economics.op_market_equilibrium,
    "growth_compare": analysis.op_growth_compare,
    "trend": analysis.op_trend,
    "sensitivity": analysis.op_sensitivity,
}
