"""Analysis of a plotted function: roots, extrema, intersections, area, value. All numerical (labelled approximate by the caller)."""
from __future__ import annotations

import math
from typing import Callable

import numpy as np


def _f(f: Callable, x):
    with np.errstate(all="ignore"):
        y = np.asarray(f(np.asarray(x, dtype=float)), dtype=float)
    return y


def refine_root(f: Callable, a: float, b: float, iters: int = 200) -> float:
    fa, fb = float(_f(f, a)), float(_f(f, b))
    if fa == 0:
        return a
    if fb == 0:
        return b
    for _ in range(iters):
        m = (a + b) / 2
        fm = float(_f(f, m))
        if not math.isfinite(fm):
            return float("nan")
        if fm == 0 or (b - a) < 4e-16 * max(1.0, abs(m)):
            return m
        if (fa < 0) == (fm < 0):
            a, fa = m, fm
        else:
            b, fb = m, fm
    return (a + b) / 2


def find_roots(f: Callable, a: float, b: float, n: int = 6000) -> list[float]:
    xs = np.linspace(a, b, n)
    ys = _f(f, xs)
    roots: list[float] = []
    scale = float(np.nanmax(np.abs(ys[np.isfinite(ys)]))) if np.isfinite(ys).any() else 1.0
    fin = np.isfinite(ys)
    for i in np.nonzero(fin[:-1] & fin[1:] & (np.sign(ys[:-1]) * np.sign(ys[1:]) <= 0))[0]:
        if ys[i] == 0 and ys[i + 1] == 0:
            continue
        r = refine_root(f, float(xs[i]), float(xs[i + 1]))
        if not math.isfinite(r):
            continue
        # a pole looks like a sign change; a root has a small value
        if abs(float(_f(f, r))) <= 1e-6 * max(1.0, scale) and abs(float(_f(f, r))) < 1e-3:
            if not roots or abs(roots[-1] - r) > 1e-9 * max(1, abs(r)):
                roots.append(r)
    # tangential roots (even multiplicity): local minima of |f| that touch zero
    ay = np.abs(ys)
    for i in range(1, n - 1):
        if fin[i - 1] and fin[i] and fin[i + 1] and ay[i] <= ay[i - 1] and ay[i] <= ay[i + 1] and ay[i] < 1e-5 * max(1.0, scale) and ys[i - 1] * ys[i + 1] > 0:
            m = _golden_min(lambda t: abs(float(_f(f, t))), float(xs[i - 1]), float(xs[i + 1]))
            if abs(float(_f(f, m))) < 1e-9 * max(1.0, scale) and not any(abs(m - r) < 1e-6 * max(1, abs(m)) for r in roots):
                roots.append(m)
    return sorted(roots)


def _golden_min(g: Callable[[float], float], a: float, b: float, iters: int = 120) -> float:
    gr = (math.sqrt(5) - 1) / 2
    c, d = b - gr * (b - a), a + gr * (b - a)
    gc, gd = g(c), g(d)
    for _ in range(iters):
        if gc < gd:
            b, d, gd = d, c, gc
            c = b - gr * (b - a)
            gc = g(c)
        else:
            a, c, gc = c, d, gd
            d = a + gr * (b - a)
            gd = g(d)
        if abs(b - a) < 1e-14 * max(1.0, abs(a)):
            break
    return (a + b) / 2


def find_extrema(f: Callable, a: float, b: float, n: int = 6000) -> list[dict]:
    xs = np.linspace(a, b, n)
    ys = _f(f, xs)
    fin = np.isfinite(ys)
    out: list[dict] = []
    for i in range(1, n - 1):
        if not (fin[i - 1] and fin[i] and fin[i + 1]):
            continue
        l, m, r = ys[i - 1], ys[i], ys[i + 1]
        if (m > l and m >= r) or (m < l and m <= r):
            kind = "maximum" if m > l else "minimum"
            sign = -1.0 if kind == "maximum" else 1.0
            x = _golden_min(lambda t: sign * float(_f(f, t)), float(xs[i - 1]), float(xs[i + 1]))
            y = float(_f(f, x))
            # plateaus and noise: require a real change of value compared to the neighbours at this scale
            if out and abs(out[-1]["x"] - x) < 1e-7 * max(1, abs(x)):
                continue
            if abs(m - l) < 1e-14 * max(1.0, abs(m)) and abs(m - r) < 1e-14 * max(1.0, abs(m)):
                continue
            out.append({"x": x, "y": y, "kind": kind})
    return out


def intersections(f: Callable, g: Callable, a: float, b: float) -> list[dict]:
    d = lambda x: _f(f, x) - _f(g, x)                                                      # noqa: E731
    return [{"x": r, "y": float(_f(f, r))} for r in find_roots(d, a, b)]


def integrate(f: Callable, a: float, b: float, tol: float = 1e-11) -> tuple[float, float]:
    """Adaptive Gauss-Kronrod (7-15) on [a, b]; returns (value, error estimate)."""
    xgk = np.array([0.991455371120813, 0.949107912342759, 0.864864423359769, 0.741531185599394, 0.586087235467691,
                    0.405845151377397, 0.207784955007898, 0.0])
    wgk = np.array([0.022935322010529, 0.063092092629979, 0.104790010322250, 0.140653259715525, 0.169004726639267,
                    0.190350578064785, 0.204432940075298, 0.209482141084728])
    wg = np.array([0.129484966168870, 0.279705391489277, 0.381830050505119, 0.417959183673469])

    def gk(lo, hi):
        c, h = (lo + hi) / 2, (hi - lo) / 2
        nodes = np.concatenate([c - h * xgk[:-1], [c], c + h * xgk[:-1][::-1]])
        w = np.concatenate([wgk[:-1], [wgk[-1]], wgk[:-1][::-1]])
        y = _f(f, nodes)
        if not np.isfinite(y).all():
            return float("nan"), float("nan")
        k = float(np.dot(w, y) * h)
        gnodes = np.concatenate([c - h * xgk[1::2][:-1 if False else 3], [c], c + h * xgk[1::2][:3][::-1]])
        gw = np.concatenate([wg[:3], [wg[3]], wg[:3][::-1]])
        gy = _f(f, gnodes)
        gval = float(np.dot(gw, gy) * h)
        return k, abs(k - gval)
    intervals = [(a, b)] + []
    total, err = 0.0, 0.0
    stack = [(a, b, 0)]
    while stack:
        lo, hi, depth = stack.pop()
        k, e = gk(lo, hi)
        if not math.isfinite(k):
            if depth < 30 and hi - lo > 1e-12:
                mid = (lo + hi) / 2
                stack += [(lo, mid, depth + 1), (mid, hi, depth + 1)]
                continue
            raise ValueError("The function is not defined on the whole interval")
        if e <= tol * max(1.0, abs(k)) * (hi - lo) / (b - a) or depth >= 24:
            total += k
            err += e
        else:
            mid = (lo + hi) / 2
            stack += [(lo, mid, depth + 1), (mid, hi, depth + 1)]
    return total, err
