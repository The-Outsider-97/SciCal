"""Least-squares fits for scatter data. Linear-in-the-parameters models use exact normal equations in NumPy; the nonlinear ones use a
damped Gauss-Newton (Levenberg-Marquardt) iteration started from a transformed fit. R² is always computed on the data as entered."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np

from ...errors import DomainError, EvaluationError, NotConvergedError

MODELS = ("linear", "quadratic", "cubic", "quartic", "exponential", "logarithmic", "power", "logistic")


def _r2(y: np.ndarray, yhat: np.ndarray) -> float:
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    return 1.0 if ss_tot == 0 and ss_res == 0 else (float("nan") if ss_tot == 0 else 1 - ss_res / ss_tot)


def _lm(fn: Callable, p0: np.ndarray, x: np.ndarray, y: np.ndarray, iters: int = 300) -> np.ndarray:
    p = p0.astype(float).copy()
    lam = 1e-3

    def resid(q):
        with np.errstate(all="ignore"):
            return y - fn(x, *q)
    r = resid(p)
    cost = float(r @ r)
    for _ in range(iters):
        J = np.empty((len(x), len(p)))
        for j in range(len(p)):
            h = 1e-7 * max(1.0, abs(p[j]))
            q = p.copy()
            q[j] += h
            J[:, j] = (resid(p) - resid(q)) / h
        A = J.T @ J
        g = J.T @ r
        try:
            step = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-12), g)
        except np.linalg.LinAlgError:
            lam *= 10
            continue
        q = p + step
        rq = resid(q)
        cq = float(rq @ rq)
        if np.isfinite(cq) and cq < cost:
            conv = abs(cost - cq) <= 1e-14 * max(cost, 1e-300)
            p, r, cost = q, rq, cq
            lam = max(lam / 3, 1e-12)
            if conv:
                break
        else:
            lam *= 4
            if lam > 1e12:
                break
    return p


def fit(model: str, x: np.ndarray, y: np.ndarray) -> dict:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(x) != len(y):
        raise DomainError(f"x and y need the same number of values ({len(x)} and {len(y)})")
    if len(x) < 2:
        raise DomainError("A fit needs at least 2 points")
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise DomainError("The data contains values that are not finite numbers")
    if model not in MODELS:
        raise EvaluationError(f"Unknown model '{model}'")
    degree = {"linear": 1, "quadratic": 2, "cubic": 3, "quartic": 4}.get(model)
    if degree:
        if len(np.unique(x)) <= degree:
            raise DomainError(f"A {model} fit needs at least {degree + 1} different x values")
        V = np.vander(x, degree + 1)
        coef, *_ = np.linalg.lstsq(V, y, rcond=None)
        f = lambda t, c=coef: np.polyval(c, t)                                   # noqa: E731
        params = dict(zip(["a", "b", "c", "d", "e"][:degree + 1], map(float, coef)))
        eq = _poly_text(coef)
        return _result(model, "y = " + eq, params, f, x, y)
    if model == "exponential":
        if np.any(y <= 0):
            raise DomainError("An exponential fit y = a·e^(bx) needs all y values to be positive")
        b0, a0 = np.polyfit(x, np.log(y), 1)
        p = _lm(lambda t, a, b: a * np.exp(b * t), np.array([math.exp(a0), b0]), x, y)
        f = lambda t, p=p: p[0] * np.exp(p[1] * t)                              # noqa: E731
        return _result(model, f"y = {_g(p[0])}·e^({_g(p[1])}x)", {"a": float(p[0]), "b": float(p[1])}, f, x, y)
    if model == "logarithmic":
        if np.any(x <= 0):
            raise DomainError("A logarithmic fit y = a + b·ln(x) needs all x values to be positive")
        b, a = np.polyfit(np.log(x), y, 1)
        f = lambda t, a=a, b=b: a + b * np.log(t)                               # noqa: E731
        return _result(model, f"y = {_g(a)} + {_g(b)}·ln(x)".replace("+ -", "- "), {"a": float(a), "b": float(b)}, f, x, y)
    if model == "power":
        if np.any(x <= 0) or np.any(y <= 0):
            raise DomainError("A power fit y = a·x^b needs all x and y values to be positive")
        b0, a0 = np.polyfit(np.log(x), np.log(y), 1)
        p = _lm(lambda t, a, b: a * np.power(t, b), np.array([math.exp(a0), b0]), x, y)
        f = lambda t, p=p: p[0] * np.power(t, p[1])                             # noqa: E731
        return _result(model, f"y = {_g(p[0])}·x^({_g(p[1])})", {"a": float(p[0]), "b": float(p[1])}, f, x, y)
    if model == "logistic":
        if len(x) < 4:
            raise DomainError("A logistic fit needs at least 4 points")
        L0 = float(np.max(y) * 1.1) if np.max(y) > 0 else float(np.max(y) + 1)
        x00 = float(np.median(x))
        span = float(np.ptp(x)) or 1.0
        p = _lm(lambda t, L, k, x0: L / (1 + np.exp(-k * (t - x0))), np.array([L0, 4 / span, x00]), x, y, 600)
        f = lambda t, p=p: p[0] / (1 + np.exp(-p[1] * (t - p[2])))              # noqa: E731
        res = _result(model, f"y = {_g(p[0])} / (1 + e^(-{_g(p[1])}(x - {_g(p[2])})))", {"L": float(p[0]), "k": float(p[1]), "x0": float(p[2])}, f, x, y)
        if not np.isfinite(res["r2"]) or res["r2"] < 0:
            raise NotConvergedError("The logistic fit did not converge for this data")
        return res
    raise EvaluationError(f"Unknown model '{model}'")


def _poly_text(coef) -> str:
    deg = len(coef) - 1
    out = ""
    for k, c in enumerate(coef):
        p = deg - k
        mag = _g(abs(c))
        term = mag if p == 0 else ("x" if p == 1 and mag == "1" else f"{'' if mag == '1' else mag}x" if p == 1 else (f"x^{p}" if mag == "1" else f"{mag}x^{p}"))
        if k == 0:
            out = ("-" if c < 0 else "") + term
        else:
            out += (" - " if c < 0 else " + ") + term
    return out


def _g(v: float) -> str:
    return f"{float(v):.6g}"


def _result(model: str, equation: str, params: dict, f: Callable, x: np.ndarray, y: np.ndarray) -> dict:
    yhat = f(x)
    return {"model": model, "equation": equation, "params": params, "r2": _r2(y, yhat), "n": int(len(x)),
            "rmse": float(math.sqrt(np.mean((y - yhat) ** 2))), "fn": f}
