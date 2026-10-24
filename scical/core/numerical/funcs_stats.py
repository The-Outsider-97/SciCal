"""Descriptive statistics, regression, series (sum/prod) and probability distributions.

Descriptive statistics and regression are computed exactly. Distributions that have no closed form use mpmath with 40 working digits and are
labelled as numerical approximations; binomial probabilities with rational p are exact.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

import mpmath as mp
import sympy as sp

from ...errors import DimensionError, DomainError, EvaluationError, LimitExceeded, NotConvergedError, UndefinedError, UnsupportedOperation
from ..expressions import ast as A
from ..units import Quantity
from ..units import quantity as Q
from . import ops
from .funcs_linalg import as_vec
from .registry import handler
from .values import Vec

mp.mp.dps = 40


# ------------------------------------------------------------------------------------------------------------------ helpers
def data(v: Any, name: str, minimum: int = 1) -> list:
    vec = as_vec(v, name)
    items = [ops.plain(x, f"{name}()") for x in vec.items]
    if len(items) < minimum:
        raise DomainError(f"{name}() needs at least {minimum} value{'s' if minimum != 1 else ''} (got {len(items)})")
    if any(getattr(x, "free_symbols", None) for x in items):
        raise EvaluationError(f"{name}() needs numbers, but the data contains unknowns")
    return items


def key(x: sp.Expr) -> sp.Expr:
    return sp.N(x, 50)


def sorted_data(items: list) -> list:
    return sorted(items, key=lambda x: (sp.re(key(x)), sp.im(key(x))))


def FLOAT(x) -> sp.Float:
    return sp.Float(mp.nstr(x, 40, min_fixed=-1000, max_fixed=1000, strip_zeros=False), 40) if not isinstance(x, sp.Basic) else x


def mfloat(x) -> mp.mpf:
    return mp.mpf(str(sp.N(x, 45)))


def _mean(items: list) -> sp.Expr:
    return sp.Add(*items) / len(items)


def _ssq(items: list, center: sp.Expr) -> sp.Expr:
    return sp.Add(*[(x - center) ** 2 for x in items])


def _median_of(sorted_items: list) -> sp.Expr:
    n = len(sorted_items)
    mid = n // 2
    return sorted_items[mid] if n % 2 else (sorted_items[mid - 1] + sorted_items[mid]) / 2


# ------------------------------------------------------------------------------------------------------------------ descriptive
@handler("mean")
def f_mean(ev, v):
    return _mean(data(v, "mean"))


@handler("median")
def f_median(ev, v):
    return _median_of(sorted_data(data(v, "median")))


@handler("mode")
def f_mode(ev, v):
    items = data(v, "mode")
    counts = Counter(items)
    top = max(counts.values())
    if top == 1:
        ev.warn("No value occurs more than once, so every value is a mode.")
    return Vec(tuple(sorted_data([k for k, c in counts.items() if c == top])))


@handler("sumsq")
def f_sumsq(ev, v):
    return sp.Add(*[x ** 2 for x in data(v, "sumsq")])


@handler("var")
def f_var(ev, v):
    items = data(v, "var", 2)
    return _ssq(items, _mean(items)) / (len(items) - 1)


@handler("varp")
def f_varp(ev, v):
    items = data(v, "varp")
    return _ssq(items, _mean(items)) / len(items)


@handler("std")
def f_std(ev, v):
    return sp.sqrt(f_var(ev, v))


@handler("stdp")
def f_stdp(ev, v):
    return sp.sqrt(f_varp(ev, v))


@handler("stderr")
def f_stderr(ev, v):
    items = data(v, "stderr", 2)
    return sp.sqrt(f_var(ev, v) / len(items))


@handler("range")
def f_range(ev, v):
    s = sorted_data(data(v, "range"))
    return s[-1] - s[0]


def _quartile(items: list, which: int) -> sp.Expr:
    s = sorted_data(items)
    n = len(s)
    if n < 2:
        raise DomainError("Quartiles need at least 2 values")
    half = n // 2
    lower, upper = s[:half], s[half + (n % 2):]
    return _median_of(lower if which == 1 else upper)


@handler("q1")
def f_q1(ev, v):
    return _quartile(data(v, "q1"), 1)


@handler("q3")
def f_q3(ev, v):
    return _quartile(data(v, "q3"), 3)


@handler("iqr")
def f_iqr(ev, v):
    items = data(v, "iqr")
    return _quartile(items, 3) - _quartile(items, 1)


@handler("percentile")
def f_percentile(ev, v, p):
    s = sorted_data(data(v, "percentile"))
    p = ops.plain(p, "percentile()")
    if not (0 <= p <= 100):
        raise DomainError("The percentile must be between 0 and 100")
    pos = p / 100 * (len(s) - 1)
    lo = int(sp.floor(pos))
    frac = pos - lo
    return s[lo] if frac == 0 else s[lo] + frac * (s[lo + 1] - s[lo])


@handler("sort")
def f_sort(ev, v):
    return Vec(tuple(sorted_data(data(v, "sort"))))


@handler("count")
def f_count(ev, v):
    return sp.Integer(len(as_vec(v, "count").items))


@handler("zscore")
def f_zscore(ev, v, x):
    items = data(v, "zscore", 2)
    sd = sp.sqrt(_ssq(items, _mean(items)) / (len(items) - 1))
    if sd == 0:
        raise UndefinedError("All values are equal, so the z-score is undefined")
    return (ops.plain(x, "zscore()") - _mean(items)) / sd


# ------------------------------------------------------------------------------------------------------------------ two variables
def _pair(x: Any, y: Any, name: str) -> tuple[list, list]:
    a, b = data(x, name, 2), data(y, name, 2)
    if len(a) != len(b):
        raise DimensionError(f"{name}() needs lists of equal length ({len(a)} and {len(b)})")
    return a, b


def _sxy(a, b):
    ma, mb = _mean(a), _mean(b)
    return sp.Add(*[(x - ma) * (y - mb) for x, y in zip(a, b)]), _ssq(a, ma), _ssq(b, mb), ma, mb


@handler("cov")
def f_cov(ev, x, y):
    a, b = _pair(x, y, "cov")
    return _sxy(a, b)[0] / (len(a) - 1)


@handler("covp")
def f_covp(ev, x, y):
    a, b = _pair(x, y, "covp")
    return _sxy(a, b)[0] / len(a)


@handler("corr")
def f_corr(ev, x, y):
    a, b = _pair(x, y, "corr")
    sxy, sxx, syy, _, _ = _sxy(a, b)
    if sxx == 0 or syy == 0:
        raise UndefinedError("The correlation is undefined when one of the lists has no spread")
    return sxy / sp.sqrt(sxx * syy)


@handler("slope")
def f_slope(ev, x, y):
    a, b = _pair(x, y, "slope")
    sxy, sxx, _, _, _ = _sxy(a, b)
    if sxx == 0:
        raise UndefinedError("The slope is undefined when all x values are equal")
    return sxy / sxx


@handler("intercept")
def f_intercept(ev, x, y):
    a, b = _pair(x, y, "intercept")
    sxy, sxx, _, ma, mb = _sxy(a, b)
    if sxx == 0:
        raise UndefinedError("The intercept is undefined when all x values are equal")
    return mb - sxy / sxx * ma


@handler("rsq")
def f_rsq(ev, x, y):
    a, b = _pair(x, y, "rsq")
    sxy, sxx, syy, _, _ = _sxy(a, b)
    if sxx == 0 or syy == 0:
        raise UndefinedError("R² is undefined when one of the lists has no spread")
    return sxy ** 2 / (sxx * syy)


# ------------------------------------------------------------------------------------------------------------------ sum / prod
@handler("sum", "prod", raw=True)
def f_series(ev, node, series):
    name = ev_name(node)
    if not series:
        vals = []
        for a in node.args:
            v = ev.ev(a)
            vals.extend(v.items if isinstance(v, Vec) else list(v) if ops.is_matrix(v) else [v])
        if name == "sum":
            acc: Any = vals[0]
            for x in vals[1:]:
                acc = ops.add(acc, x, 1)
            return acc
        acc = vals[0]
        for x in vals[1:]:
            acc = ops.mul(acc, x)
        return acc
    kvar = node.args[1]
    if not isinstance(kvar, A.Var):
        raise EvaluationError(f"The second argument of {name}() must be the index variable, for example k", span=kvar.span)    # type: ignore[attr-defined]
    k = sp.Symbol(kvar.name)
    lo, hi = ops.plain(ev.ev(node.args[2]), f"{name}() start"), ops.plain(ev.ev(node.args[3]), f"{name}() end")
    ev.shadow.append({kvar.name: k})
    try:
        expr = ops.plain(ev.ev(node.args[0]), f"{name}() term")
    finally:
        ev.shadow.pop()
    finite = lo.is_integer and hi.is_integer and lo.is_finite and hi.is_finite
    if finite:
        a, b = int(lo), int(hi)
        if b - a + 1 > 200_000:
            raise LimitExceeded("The sum has too many terms (limit 200,000)")
        if b < a:
            return sp.Integer(0 if name == "sum" else 1)
        if b - a + 1 <= 3000 or not (expr.free_symbols - {k}) == set():
            terms = []
            for i in range(a, b + 1):
                t = expr.subs(k, i)
                ev.check(t)
                terms.append(t)
            return sp.Add(*terms) if name == "sum" else sp.Mul(*terms)
    if not ((lo.is_integer or lo in (sp.oo, -sp.oo)) and (hi.is_integer or hi in (sp.oo, -sp.oo))):
        raise DomainError(f"The limits of {name}() must be whole numbers or ∞")
    fn = sp.summation if name == "sum" else sp.product
    res = fn(expr, (k, lo, hi))
    if res.has(sp.Sum) or res.has(sp.Product):
        raise UnsupportedOperation(f"No closed form for this {'series' if name == 'sum' else 'product'} was found",
                                   hint="Use a finite range (for example 1 to 100) to get a number.")
    return res


def ev_name(node: A.Call) -> str:
    from ..expressions.functions import canonical
    return canonical(node.name) or node.name


# ------------------------------------------------------------------------------------------------------------------ distributions
def _approx(ev, x) -> sp.Float:
    ev.numeric_method = "mpmath, 40 working digits"
    return sp.Float(mp.nstr(x, 35, min_fixed=-1000, max_fixed=1000), 35)


def _num(v: Any, name: str) -> mp.mpf:
    x = ops.plain(v, f"{name}()")
    if x == sp.oo:
        return mp.inf
    if x == -sp.oo:
        return -mp.inf
    if getattr(x, "free_symbols", None) or not x.is_real:
        raise EvaluationError(f"{name}() needs real numbers")
    return mfloat(x)


def _sigma(v: Any, name: str) -> mp.mpf:
    s = _num(v, name)
    if s <= 0:
        raise DomainError("The standard deviation must be positive")
    return s


def _ncdf(z):
    return mp.erfc(-z / mp.sqrt(2)) / 2


@handler("normalpdf")
def f_normalpdf(ev, x, mu=None, sigma=None):
    x, m, s = _num(x, "normalpdf"), _num(mu if mu is not None else sp.Integer(0), "normalpdf"), _sigma(sigma if sigma is not None else sp.Integer(1), "normalpdf")
    return _approx(ev, mp.exp(-((x - m) / s) ** 2 / 2) / (s * mp.sqrt(2 * mp.pi)))


@handler("normalcdf")
def f_normalcdf(ev, x, mu=None, sigma=None):
    x, m, s = _num(x, "normalcdf"), _num(mu if mu is not None else sp.Integer(0), "normalcdf"), _sigma(sigma if sigma is not None else sp.Integer(1), "normalcdf")
    return _approx(ev, _ncdf((x - m) / s))


@handler("normalprob")
def f_normalprob(ev, a, b, mu=None, sigma=None):
    a, b = _num(a, "normalprob"), _num(b, "normalprob")
    m, s = _num(mu if mu is not None else sp.Integer(0), "normalprob"), _sigma(sigma if sigma is not None else sp.Integer(1), "normalprob")
    if a > b:
        raise DomainError("The lower limit must not exceed the upper limit")
    return _approx(ev, _ncdf((b - m) / s) - _ncdf((a - m) / s))


@handler("invnorm")
def f_invnorm(ev, p, mu=None, sigma=None):
    p = _num(p, "invnorm")
    if not (0 < p < 1):
        raise DomainError("The probability must be strictly between 0 and 1")
    m, s = _num(mu if mu is not None else sp.Integer(0), "invnorm"), _sigma(sigma if sigma is not None else sp.Integer(1), "invnorm")
    return _approx(ev, m + s * mp.sqrt(2) * mp.erfinv(2 * p - 1))


def _prob(p: Any) -> sp.Expr:
    p = ops.plain(p, "The probability")
    if not (p.is_number and p.is_real and 0 <= p <= 1):
        raise DomainError("A probability must be between 0 and 1")
    return p


@handler("binompdf")
def f_binompdf(ev, n, p, k):
    n, k, p = ops.as_int(n, "n", 0, 100_000), ops.as_int(k, "k"), _prob(p)
    if k < 0 or k > n:
        return sp.Integer(0)
    if n <= 2000 and p.is_Rational:
        return sp.binomial(n, k) * p ** k * (1 - p) ** (n - k)
    return _approx(ev, mp.binomial(n, k) * mfloat(p) ** k * (1 - mfloat(p)) ** (n - k))


@handler("binomcdf")
def f_binomcdf(ev, n, p, k):
    n, k, p = ops.as_int(n, "n", 0, 100_000), ops.as_int(k, "k"), _prob(p)
    if k < 0:
        return sp.Integer(0)
    if k >= n:
        return sp.Integer(1)
    if n <= 2000 and p.is_Rational:
        return sp.Add(*[sp.binomial(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1)])
    pf = mfloat(p)
    return _approx(ev, mp.fsum(mp.binomial(n, i) * pf ** i * (1 - pf) ** (n - i) for i in range(k + 1)))


@handler("poissonpdf")
def f_poissonpdf(ev, lam, k):
    lam, k = _num(lam, "poissonpdf"), ops.as_int(k, "k")
    if lam <= 0:
        raise DomainError("The Poisson mean must be positive")
    if k < 0:
        return sp.Integer(0)
    return _approx(ev, mp.exp(-lam) * lam ** k / mp.factorial(k))


@handler("poissoncdf")
def f_poissoncdf(ev, lam, k):
    lam, k = _num(lam, "poissoncdf"), ops.as_int(k, "k")
    if lam <= 0:
        raise DomainError("The Poisson mean must be positive")
    if k < 0:
        return sp.Integer(0)
    return _approx(ev, mp.gammainc(k + 1, lam, mp.inf, regularized=True))


def _df(v: Any, name: str) -> mp.mpf:
    d = _num(v, name)
    if d <= 0:
        raise DomainError("The degrees of freedom must be positive")
    return d


def _tcdf(x, d):
    if x == 0:
        return mp.mpf(1) / 2
    z = d / (d + x * x)
    tail = mp.betainc(d / 2, mp.mpf(1) / 2, 0, z, regularized=True) / 2
    return 1 - tail if x > 0 else tail


@handler("tpdf")
def f_tpdf(ev, x, df):
    x, d = _num(x, "tpdf"), _df(df, "tpdf")
    return _approx(ev, mp.gamma((d + 1) / 2) / (mp.sqrt(d * mp.pi) * mp.gamma(d / 2)) * (1 + x * x / d) ** (-(d + 1) / 2))


@handler("tcdf")
def f_tcdf(ev, x, df):
    return _approx(ev, _tcdf(_num(x, "tcdf"), _df(df, "tcdf")))


def _invt(p, d):
    if p == mp.mpf(1) / 2:
        return mp.mpf(0)
    lo, hi = mp.mpf(-1), mp.mpf(1)
    while _tcdf(lo, d) > p:
        lo *= 2
        if lo < -mp.mpf(10) ** 30:
            raise NotConvergedError("The quantile is too extreme to compute")
    while _tcdf(hi, d) < p:
        hi *= 2
        if hi > mp.mpf(10) ** 30:
            raise NotConvergedError("The quantile is too extreme to compute")
    for _ in range(300):
        mid = (lo + hi) / 2
        if _tcdf(mid, d) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < mp.mpf(10) ** -35 * max(1, abs(mid)):
            break
    return (lo + hi) / 2


@handler("invt")
def f_invt(ev, p, df):
    p, d = _num(p, "invt"), _df(df, "invt")
    if not (0 < p < 1):
        raise DomainError("The probability must be strictly between 0 and 1")
    return _approx(ev, _invt(p, d))


@handler("chi2pdf")
def f_chi2pdf(ev, x, df):
    x, d = _num(x, "chi2pdf"), _df(df, "chi2pdf")
    if x < 0:
        return sp.Integer(0)
    if x == 0:
        return sp.Integer(1) / 2 if d == 2 else (sp.Integer(0) if d > 2 else _undefined_density())
    return _approx(ev, x ** (d / 2 - 1) * mp.exp(-x / 2) / (2 ** (d / 2) * mp.gamma(d / 2)))


def _undefined_density():
    raise UndefinedError("The density is infinite at 0 for fewer than 2 degrees of freedom")


@handler("chi2cdf")
def f_chi2cdf(ev, x, df):
    x, d = _num(x, "chi2cdf"), _df(df, "chi2cdf")
    if x <= 0:
        return sp.Integer(0)
    return _approx(ev, mp.gammainc(d / 2, 0, x / 2, regularized=True))


@handler("tinterval")
def f_tinterval(ev, v, level=None):
    items = data(v, "tinterval", 2)
    lv = mfloat(ops.plain(level, "level")) if level is not None else mp.mpf("0.95")
    if not (0 < lv < 1):
        raise DomainError("The confidence level must be between 0 and 1")
    n = len(items)
    m = mfloat(_mean(items))
    s = mp.sqrt(mfloat(_ssq(items, _mean(items)) / (n - 1)))
    t = _invt((1 + lv) / 2, mp.mpf(n - 1))
    h = t * s / mp.sqrt(n)
    return Vec((_approx(ev, m - h), _approx(ev, m + h)))


@handler("zinterval")
def f_zinterval(ev, v, sigma, level=None):
    items = data(v, "zinterval")
    lv = mfloat(ops.plain(level, "level")) if level is not None else mp.mpf("0.95")
    if not (0 < lv < 1):
        raise DomainError("The confidence level must be between 0 and 1")
    sg = _sigma(sigma, "zinterval")
    z = mp.sqrt(2) * mp.erfinv(lv)
    m = mfloat(_mean(items))
    h = z * sg / mp.sqrt(len(items))
    return Vec((_approx(ev, m - h), _approx(ev, m + h)))


@handler("propinterval")
def f_propinterval(ev, x, n, level=None):
    x, n = ops.as_int(x, "x", 0), ops.as_int(n, "n", 1)
    if x > n:
        raise DomainError("x cannot exceed n")
    lv = mfloat(ops.plain(level, "level")) if level is not None else mp.mpf("0.95")
    if not (0 < lv < 1):
        raise DomainError("The confidence level must be between 0 and 1")
    z = mp.sqrt(2) * mp.erfinv(lv)
    p = mp.mpf(x) / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * mp.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Vec((_approx(ev, centre - half), _approx(ev, centre + half)))
