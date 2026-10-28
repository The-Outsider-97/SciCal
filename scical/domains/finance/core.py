"""The financial mathematics layer: how Economics & Finance numbers are read, calculated, rounded and shown.

SciCal already has a numerical engine (exact rationals with sympy, expressions, units, statistics). Finance adds no second engine; it
adds the *policies* money needs, on top of that engine's own number reading (``domains.common.number``):

* **Exact input.** What is typed is read as an exact decimal (``0.07`` is 7/100, never a binary float) and kept as a ``Fraction``.
* **Calculation precision is separate from display rounding.** Rational steps (a loan payment with a whole number of periods, a sum of
  discounted flows with whole periods) are exact. The few steps that are not rational (a fractional exponent, a logarithm, a root of a
  polynomial) are done with 60 significant digits. Only the *shown* amount is rounded, to ``places`` decimals (half away from zero);
  the unrounded value is kept beside it as ``exact`` so a saved record loses nothing.
* **Rates are percentages when typed** (``5`` means 5 % per year) and decimals inside (``Fraction(1, 20)``). Every rate field says which
  kind of rate it is (nominal per year, effective per year, periodic).
* **Schedules close.** A schedule that rounds each period to the cent keeps the cents as integers, so the principal repaid adds up to the
  loan exactly and the last payment is adjusted by the cents of rounding, not by a drift.
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from typing import Any, Callable, Iterator, Sequence

import mpmath as mp
import sympy as sp

from ...core.numerical.context import Settings
from ...errors import BadRequest, EvaluationError
from ..common import Out, field_error, number

DPS = 60                                   # significant digits for the steps that are not rational
MAX_PERIODS = 1200                         # longest schedule or annuity worked out period by period
MAX_FLOWS = 400                            # longest list of cash flows
Real = Fraction | mp.mpf


@contextmanager
def hp() -> Iterator[None]:
    """60-digit arithmetic for the block, without changing the precision anything else in the process sees."""
    with mp.workdps(DPS):
        yield


# ---------------------------------------------------------------------------------------------------------------------- reading input
def to_fraction(x: Any, key: str = "value") -> Fraction:
    """An exact ``Fraction`` from what the number reader gave. A value that is not rational (``pi``, ``sqrt(2)``) is taken to 40 digits."""
    x = sp.sympify(x)
    if x.is_Rational:
        return Fraction(int(x.p), int(x.q))
    if x.free_symbols or not x.is_real:
        raise field_error(key, f"'{key}' must be a real number")
    d = Decimal(str(sp.N(x, 45)))
    return Fraction(d)


def frac(params: dict, key: str, *, positive: bool = False, nonneg: bool = False, lo: Any = None, hi: Any = None, integer: bool = False,
         default: Any = None, required: bool = True) -> Fraction | None:
    v = number(params, key, default=default, positive=positive, nonneg=nonneg, lo=lo, hi=hi, integer=integer, required=required)
    return None if v is None else to_fraction(v, key)


def rate(params: dict, key: str, *, default: Any = None, required: bool = True, lo: Fraction | None = None, strict_lo: bool = False) -> Fraction | None:
    """A rate typed as a percentage (``5`` or ``5%``) and returned as a decimal fraction (``1/20``)."""
    raw = params.get(key, default)
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.endswith("%"):
            raw = raw[:-1].strip()
        params = {**params, key: raw}
    elif raw is not None:
        params = {**params, key: raw}
    v = frac(params, key, default=default, required=required)
    if v is None:
        return None
    r = v / 100
    if lo is not None and (r < lo or (strict_lo and r == lo)):
        raise field_error(key, f"'{key}' must be {'above' if strict_lo else 'at least'} {fmt_decimal(lo * 100, 6)} %")
    return r


def count(params: dict, key: str, *, lo: int = 1, hi: int = MAX_PERIODS, default: Any = None, required: bool = True) -> int | None:
    v = number(params, key, default=default, integer=True, required=required)
    if v is None:
        return None
    n = int(v)
    if n < lo or n > hi:
        raise field_error(key, f"'{key}' must be a whole number from {lo} to {hi}")
    return n


def choice(params: dict, key: str, options: Sequence[str], default: str) -> str:
    v = params.get(key, default)
    if v in (None, ""):
        return default
    if v not in options:
        raise field_error(key, f"'{key}' must be one of: {', '.join(options)}")
    return str(v)


def numbers_list(params: dict, key: str, *, minimum: int = 1, maximum: int = MAX_FLOWS) -> list[Fraction]:
    """A list of numbers typed as text (spaces, commas, semicolons or lines) or sent as a list."""
    raw = params.get(key)
    if isinstance(raw, str):
        items = [t for t in __import__("re").split(r"[\s,;]+", raw.strip()) if t]
    elif isinstance(raw, list):
        items = raw
    else:
        raise field_error(key, f"'{key}' is required")
    if len(items) < minimum:
        raise field_error(key, f"'{key}' needs at least {minimum} value{'s' if minimum != 1 else ''}")
    if len(items) > maximum:
        raise field_error(key, f"'{key}' has too many values (at most {maximum})")
    return [to_fraction(number({"v": it}, "v"), key) for it in items]


# ---------------------------------------------------------------------------------------------------------------------- arithmetic
def is_int(x: Real) -> bool:
    return isinstance(x, Fraction) and x.denominator == 1


def from_mp(x: mp.mpf) -> Fraction:
    """A 60-digit value carried on as an exact decimal of 55 significant digits, so every later step is plain ``Fraction`` arithmetic."""
    with hp():
        if mp.isnan(x) or mp.isinf(x):
            raise BadRequest("The result is not a finite number")
        return Fraction(Decimal(mp.nstr(x, 55, strip_zeros=False)))


def power(base: Fraction, exp: Fraction, key: str = "value") -> Fraction:
    """``base ** exp``: exact for a whole-number exponent, 55 digits otherwise (and then the base must be positive)."""
    if exp.denominator == 1 and abs(int(exp)) <= 20_000:
        e = int(exp)
        if base == 0 and e < 0:
            raise BadRequest("Division by zero: 0 raised to a negative power", details={"field": key})
        return base ** e
    if base <= 0:
        raise BadRequest("A non-positive base cannot be raised to a fractional power", details={"field": key},
                         hint="With a fractional exponent the growth factor 1 + rate/n must be greater than 0.")
    with hp():
        return from_mp(mp.power(to_mp(base), to_mp(exp)))


def exp_f(x: Fraction) -> Fraction:
    with hp():
        return from_mp(mp.exp(to_mp(x)))


def to_mp(x: Real) -> mp.mpf:
    with hp():
        return mp.mpf(x.numerator) / x.denominator if isinstance(x, Fraction) else mp.mpf(x)


def to_float(x: Real) -> float:
    return float(x.numerator) / x.denominator if isinstance(x, Fraction) and abs(x.numerator) < 10**300 and x.denominator < 10**300 else float(to_mp(x))


def ln(x: Fraction, key: str = "value") -> Fraction:
    if x <= 0:
        raise BadRequest("The logarithm of a non-positive number does not exist", details={"field": key})
    with hp():
        return from_mp(mp.log(to_mp(x)))


def bisect(f: Callable[[mp.mpf], mp.mpf], lo: mp.mpf, hi: mp.mpf, *, tol: int = 45, iters: int = 400) -> mp.mpf | None:
    """The root of ``f`` between ``lo`` and ``hi`` (60-digit bisection, converged to ``tol`` digits), or ``None`` if the signs do not differ."""
    with hp():
        flo, fhi = f(lo), f(hi)
        if flo == 0:
            return lo
        if fhi == 0:
            return hi
        if (flo > 0) == (fhi > 0):
            return None
        eps = mp.mpf(10) ** (-tol)
        for _ in range(iters):
            mid = (lo + hi) / 2
            fm = f(mid)
            if fm == 0 or (hi - lo) < eps * max(1, abs(mid)):
                return mid
            if (fm > 0) == (flo > 0):
                lo, flo = mid, fm
            else:
                hi = mid
        return (lo + hi) / 2


# ---------------------------------------------------------------------------------------------------------------------- display
def _to_decimal(x: Real) -> Decimal:
    if isinstance(x, Fraction):
        with localcontext() as c:
            c.prec = 120
            return Decimal(x.numerator) / Decimal(x.denominator)
    with hp():
        return Decimal(mp.nstr(x, 55, strip_zeros=False))


def fmt_decimal(x: Real, places: int = 2, group: bool = False) -> str:
    """``x`` rounded half away from zero to ``places`` decimals, optionally with thousands separators."""
    d = _to_decimal(x)
    with localcontext() as c:
        c.prec = 120
        q = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP) if places >= 0 else d
    s = format(q, f",.{places}f") if group else format(q, f".{places}f")
    return s[1:] if s.startswith("-") and set(s[1:]) <= set("0.,") else s                  # "-0.00" is "0.00"


def exact_text(x: Real, places: int = 20) -> str:
    """The unrounded value: an integer, a short fraction written as a decimal, or a 20-place decimal with a trailing ``…`` marker."""
    if isinstance(x, Fraction):
        den = x.denominator
        while den % 2 == 0:
            den //= 2
        while den % 5 == 0:
            den //= 5
        if den == 1:                                           # terminates: write it out in full
            places_needed = _terminating_places(x)
            if places_needed > 24:                                   # a 55-digit carried value, not a short exact decimal: show 20 places and say so
                return fmt_decimal(x, places).rstrip("0").rstrip(".") + "…"
            return fmt_decimal(x, max(0, places_needed))
        return fmt_decimal(x, places).rstrip("0").rstrip(".") + "…"
    return fmt_decimal(x, places).rstrip("0").rstrip(".") + "…"


def _terminating_places(x: Fraction) -> int:
    den, places = x.denominator, 0
    twos = fives = 0
    while den % 2 == 0:
        den //= 2
        twos += 1
    while den % 5 == 0:
        den //= 5
        fives += 1
    return max(twos, fives)


CURRENCIES = {"USD": ("$", 2), "EUR": ("€", 2), "GBP": ("£", 2), "JPY": ("¥", 0), "CHF": ("CHF ", 2), "CAD": ("CA$", 2), "AUD": ("A$", 2), "CNY": ("CN¥", 2),
              "INR": ("₹", 2), "SEK": ("", 2), "NOK": ("", 2), "DKK": ("", 2), "PLN": ("", 2), "BRL": ("R$", 2), "MXN": ("MX$", 2), "ZAR": ("R", 2),
              "KRW": ("₩", 0), "NZD": ("NZ$", 2), "SGD": ("S$", 2), "HKD": ("HK$", 2)}


class Fmt:
    """Currency and rate formatting for one calculation. It only ever *displays*: nothing it rounds is used in a later step."""

    def __init__(self, params: dict) -> None:
        cur = str(params.get("currency") or "").strip()
        if len(cur) > 8:
            raise field_error("currency", "'currency' must be a short code or symbol such as EUR or €")
        self.code = cur.upper() if cur.isalpha() else cur
        symbol, default_places = CURRENCIES.get(self.code, ("", 2))
        self.symbol = symbol
        raw = params.get("places")
        if raw in (None, ""):
            self.places = default_places
        else:
            p = number(params, "places", integer=True, lo=0, hi=8)
            self.places = int(p)
        self.has_currency = bool(cur)

    # amounts
    def money(self, x: Real, unit: bool = True) -> dict[str, Any]:
        s = fmt_decimal(x, self.places, group=True)
        neg = s.startswith("-")
        body = s[1:] if neg else s
        if self.symbol:
            text = f"{'-' if neg else ''}{self.symbol}{body}"
        elif self.has_currency and unit:
            text = f"{'-' if neg else ''}{body} {self.code}"
        else:
            text = s
        plain = fmt_decimal(x, self.places)
        latex = fmt_decimal(x, self.places, group=True).replace(",", r"\,") + (rf"\,\mathrm{{{self.code}}}" if self.has_currency and self.code.isalpha() else "")
        out: dict[str, Any] = {"text": text, "latex": latex, "value": to_float(x)}
        ex = exact_text(x)
        if ex.rstrip("…") != plain and ex != s:
            out["exact"] = ex
            out["approximate"] = ex.endswith("…")
        if self.has_currency:
            out["unit"] = self.code
        return out

    def amount(self, x: Real, places: int | None = None, unit: str | None = None) -> dict[str, Any]:
        """A plain (non-currency) number, rounded for display to ``places`` decimals (default: enough to read, up to 8)."""
        p = places if places is not None else _readable_places(x)
        plain = fmt_decimal(x, p)
        out: dict[str, Any] = {"text": fmt_decimal(x, p, group=True) + (f" {unit}" if unit else ""), "latex": fmt_decimal(x, p, group=True).replace(",", r"\,") + (rf"\,\mathrm{{{unit}}}" if unit else ""), "value": to_float(x)}
        ex = exact_text(x)
        if ex.rstrip("…") != plain:
            out["exact"] = ex
            out["approximate"] = ex.endswith("…")
        if unit:
            out["unit"] = unit
        return out

    def percent(self, r: Real, places: int | None = None, label: str | None = None) -> dict[str, Any]:
        """A rate held as a decimal (``0.05``) shown as a percentage (``5.00 %``), with the decimal form kept as ``exact``."""
        pct = r * 100
        p = places if places is not None else max(2, min(8, _readable_places(pct)))
        plain = fmt_decimal(pct, p)
        out: dict[str, Any] = {"text": f"{fmt_decimal(pct, p, group=True)} %", "latex": plain + r"\,\%", "value": to_float(pct), "unit": "%"}
        dec = exact_text(r)
        out["exact"] = f"{dec} as a decimal rate"
        if label:
            out["note"] = label
        return out


def _readable_places(x: Real) -> int:
    """How many decimals show a value usefully: 2 for most, more for small values, none for a whole number."""
    f = abs(to_float(x))
    if isinstance(x, Fraction) and x.denominator == 1:
        return 0
    if f == 0:
        return 2
    if f >= 100:
        return 2
    if f >= 1:
        return 4
    return min(8, 2 + int(-math.floor(math.log10(f))) + 1)


def rate_note(raw_percent: Fraction) -> str | None:
    """Rates are typed in percent; a small typed value is probably a decimal rate, so say what was understood."""
    if 0 < abs(raw_percent) < 1:
        return f"The rate was read as {fmt_decimal(raw_percent, 6).rstrip('0').rstrip('.')} % per year. Rates are entered in percent: type 5 for 5 %."
    return None


# ---------------------------------------------------------------------------------------------------------------------- results
class Result(Out):
    """A finance result: the shared ``Out`` plus a currency formatter, a list of stated assumptions, and graph data."""

    def __init__(self, settings: Settings, params: dict) -> None:
        super().__init__(settings)
        self.f = Fmt(params)
        self.assumptions: list[str] = []

    def assume(self, text: str) -> None:
        if text not in self.assumptions:
            self.assumptions.append(text)

    def done(self, **kw: Any) -> dict[str, Any]:                       # type: ignore[override]
        if self.assumptions:
            kw.setdefault("assumptions", self.assumptions)
        return super().done(**kw)


def graph_spec(layers: list[dict[str, Any]], *, params: list[dict[str, Any]] | None = None, viewport: dict[str, float] | None = None) -> dict[str, Any]:
    """A spec the Graphing workspace opens as it stands: expression layers (with sliders for the named parameters) or data layers."""
    spec: dict[str, Any] = {"layers": layers}
    if params:
        spec["params"] = params
    if viewport:
        spec["viewport"] = viewport
    return spec


def slider(name: str, value: Real, lo: float, hi: float, step: float) -> dict[str, Any]:
    return {"name": name, "value": to_float(value), "min": lo, "max": hi, "step": step}


def pad_view(xs: Sequence[float], ys: Sequence[float]) -> dict[str, float] | None:
    xs = [x for x in xs if math.isfinite(x)]
    ys = [y for y in ys if math.isfinite(y)]
    if not xs or not ys:
        return None
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dx = (x1 - x0) or 1.0
    dy = (y1 - y0) or max(1.0, abs(y1))
    return {"xmin": x0 - dx * 0.04, "xmax": x1 + dx * 0.04, "ymin": y0 - dy * 0.08, "ymax": y1 + dy * 0.08}


def points_text(points: Sequence[tuple[float, float]]) -> str:
    """The ``data`` text of a Graphing scatter layer: one ``x, y`` pair per line."""
    return "\n".join(f"{x:.10g}, {y:.10g}" for x, y in points)


def plot_block(title: str, x_label: str, y_label: str, series: list[dict[str, Any]], *, description: str = "", zero_line: bool = False,
               markers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The series of a small result chart (drawn by the same chart component as the other workspaces)."""
    return {"title": title, "xLabel": x_label, "yLabel": y_label, "series": series, "description": description, "zeroLine": zero_line, "markers": markers or []}


def finite(x: Real) -> bool:
    return not (isinstance(x, mp.mpf) and (mp.isnan(x) or mp.isinf(x)))


def require(cond: bool, message: str, field: str | None = None, hint: str | None = None) -> None:
    if not cond:
        raise BadRequest(message, details={"field": field} if field else {}, hint=hint)


def give_up(message: str, hint: str | None = None) -> EvaluationError:
    return EvaluationError(message, hint=hint)
