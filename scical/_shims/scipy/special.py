"""``betainc``, ``gammainc`` and ``gammaln`` for scalar arguments, with mpmath (pure Python, 30 digits internally), as SciPy defines them:
the *regularised* incomplete beta and lower incomplete gamma functions, and ln|Gamma(x)|."""
from __future__ import annotations

import math

import mpmath as mp

mp.mp.dps = 30


def betainc(a: float, b: float, x: float) -> float:
    x = float(x)
    if math.isnan(x) or not 0.0 <= x <= 1.0 or a <= 0 or b <= 0:
        return math.nan
    return float(mp.betainc(a, b, 0, x, regularized=True))


def gammainc(a: float, x: float) -> float:
    x = float(x)
    if math.isnan(x) or x < 0 or a < 0:
        return math.nan
    if a == 0:
        return 1.0
    if x == 0:
        return 0.0
    return float(mp.gammainc(a, 0, x, regularized=True))


def gammaln(x: float) -> float:
    x = float(x)
    if x <= 0 and x == math.floor(x):
        return math.inf
    return float(mp.log(abs(mp.gamma(x))))
