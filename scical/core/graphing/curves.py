"""Sampling curves into polylines the client can draw: adaptive in pixel space, with honest handling of gaps, jumps and asymptotes."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

MAX_POINTS = 24_000


@dataclass(frozen=True)
class View:
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    width: int = 800
    height: int = 500

    @property
    def w(self) -> float:
        return self.xmax - self.xmin

    @property
    def h(self) -> float:
        return self.ymax - self.ymin

    def px(self, x, y):
        return (np.asarray(x) - self.xmin) / self.w * self.width, (np.asarray(y) - self.ymin) / self.h * self.height


Segments = list[list[tuple[float, float]]]


def _eval(f: Callable, x: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        y = np.asarray(f(x))
    if np.iscomplexobj(y):
        y = np.where(np.abs(y.imag) <= 1e-12 * (1 + np.abs(y.real)), y.real, np.nan)
    y = y.astype(float, copy=True)
    if y.shape != x.shape:
        y = np.broadcast_to(y, x.shape).copy()
    y[~np.isfinite(y)] = np.nan
    return y


def _bisect_edges(f: Callable, xl: np.ndarray, xr: np.ndarray, yl: np.ndarray, yr: np.ndarray, iters: int = 48):
    """Narrow each interval (xl, xr) to where the function stops being defined or jumps. Returns the final bracket values."""
    xl, xr, yl, yr = xl.copy(), xr.copy(), yl.copy(), yr.copy()
    for _ in range(iters):
        xm = (xl + xr) / 2
        ym = _eval(f, xm)
        left_def, right_def = np.isfinite(yl), np.isfinite(yr)
        mid_def = np.isfinite(ym)
        # domain edge: exactly one end defined -> keep the sub-interval that still contains the edge
        edge = left_def ^ right_def
        go_right = np.where(edge, mid_def == left_def, np.abs(ym - yl) < np.abs(yr - ym))
        go_right = np.where(~mid_def & ~edge, False, go_right)
        xl = np.where(go_right, xm, xl)
        yl = np.where(go_right, ym, yl)
        xr = np.where(go_right, xr, xm)
        yr = np.where(go_right, yr, ym)
    return xl, xr, yl, yr


def sample_function(f: Callable, view: View, xrange: tuple[float, float] | None = None) -> tuple[Segments, list[float]]:
    """Polyline segments of y = f(x) over the view, plus the x positions of vertical asymptotes."""
    pad = 0.04 * view.w
    x0, x1 = (view.xmin - pad, view.xmax + pad) if xrange is None else xrange
    n = int(min(3000, max(400, view.width * 1.5)))
    xs = np.linspace(x0, x1, n)
    ys = _eval(f, xs)
    asymptotes: list[float] = []
    breaks: set[float] = set()
    for _ in range(7):
        if len(xs) > MAX_POINTS:
            break
        px, py = view.px(xs, np.where(np.isfinite(ys), np.clip(ys, view.ymin - 50 * view.h, view.ymax + 50 * view.h), 0))
        fin = np.isfinite(ys)
        dx, dy = np.diff(px), np.diff(py)
        seglen = np.hypot(dx, dy)
        both = fin[:-1] & fin[1:]
        flag = np.zeros(len(xs) - 1, dtype=bool)
        flag |= (fin[:-1] != fin[1:])                                                 # edge of the domain
        # curvature: turning angle at interior points
        if len(xs) > 2:
            a1 = np.arctan2(dy[:-1], dx[:-1])
            a2 = np.arctan2(dy[1:], dx[1:])
            turn = np.abs(np.arctan2(np.sin(a2 - a1), np.cos(a2 - a1)))
            bad = (turn > 0.06) & both[:-1] & both[1:] & ((seglen[:-1] > 0.4) | (seglen[1:] > 0.4))
            flag[:-1] |= bad
            flag[1:] |= bad
        flag |= both & (seglen > 6.0)                                                 # long chords
        flag &= (np.abs(np.diff(xs)) > 1e-13 * max(1.0, abs(x1)))
        if not flag.any():
            break
        idx = np.nonzero(flag)[0]
        mids = (xs[idx] + xs[idx + 1]) / 2
        ym = _eval(f, mids)
        xs = np.insert(xs, idx + 1, mids)
        ys = np.insert(ys, idx + 1, ym)
    # locate the exact edges of the domain and jumps
    fin = np.isfinite(ys)
    dxp, dyp = view.px(xs, np.where(fin, ys, 0))
    cand = np.nonzero((fin[:-1] != fin[1:]) | (fin[:-1] & fin[1:] & (np.abs(np.diff(dyp)) > 0.35 * view.height)))[0]
    extra_x: list[float] = []
    extra_y: list[float] = []
    cuts: list[float] = []
    if len(cand):
        bl, br, byl, byr = _bisect_edges(f, xs[cand], xs[cand + 1], ys[cand], ys[cand + 1])
        for k, i in enumerate(cand):
            l_def, r_def = np.isfinite(byl[k]), np.isfinite(byr[k])
            if l_def and r_def:
                jump = abs(byr[k] - byl[k])
                if jump > 0.25 * view.h:
                    cuts.append(float((bl[k] + br[k]) / 2))
                    if max(abs(byl[k]), abs(byr[k])) > 20 * view.h or not np.isfinite(jump):
                        asymptotes.append(float((bl[k] + br[k]) / 2))
                    extra_x += [float(bl[k]), float(br[k])]
                    extra_y += [float(byl[k]), float(byr[k])]
                # else: steep but continuous -> keep the original polyline
            elif l_def:
                extra_x.append(float(bl[k]))
                extra_y.append(float(byl[k]))
                if abs(byl[k]) > 50 * view.h:
                    asymptotes.append(float(bl[k]))
            elif r_def:
                extra_x.append(float(br[k]))
                extra_y.append(float(byr[k]))
                if abs(byr[k]) > 50 * view.h:
                    asymptotes.append(float(br[k]))
    if extra_x:
        xs = np.concatenate([xs, extra_x])
        ys = np.concatenate([ys, extra_y])
        order = np.argsort(xs, kind="stable")
        xs, ys = xs[order], ys[order]
        # cuts are recomputed below from the jump test, so positions need not be tracked through the sort
    return _to_segments(xs, ys, view, np.array(sorted(cuts))), sorted(set(round(a, 9) + 0.0 for a in asymptotes))


def _to_segments(xs: np.ndarray, ys: np.ndarray, view: View, cuts: np.ndarray) -> Segments:
    segs: Segments = []
    cur: list[tuple[float, float]] = []
    top, bot = view.ymax + 2 * view.h, view.ymin - 2 * view.h
    mid = (view.ymin + view.ymax) / 2
    clamp = 1e3 * view.h
    zone = np.searchsorted(cuts, xs, side="right") if len(cuts) else np.zeros(len(xs), dtype=int)
    last_zone = None
    for i in range(len(xs)):
        y = ys[i]
        if not np.isfinite(y):
            if cur:
                segs.append(cur)
            cur, last_zone = [], None
            continue
        if cur and zone[i] != last_zone:
            segs.append(cur)
            cur = []
        yc = float(np.clip(y, mid - clamp, mid + clamp))
        if cur and ((cur[-1][1] > top and yc > top) or (cur[-1][1] < bot and yc < bot)):
            segs.append(cur)
            cur = []
        cur.append((float(xs[i]), yc))
        last_zone = zone[i]
    if cur:
        segs.append(cur)
    return [s for s in segs if len(s) >= 2]


def sample_parametric(fx: Callable, fy: Callable, t0: float, t1: float, view: View) -> Segments:
    n = 1200
    ts = np.linspace(t0, t1, n)
    xs, ys = _eval(fx, ts), _eval(fy, ts)
    for _ in range(6):
        if len(ts) > MAX_POINTS:
            break
        px, py = view.px(np.where(np.isfinite(xs), xs, 0), np.where(np.isfinite(ys), ys, 0))
        fin = np.isfinite(xs) & np.isfinite(ys)
        d = np.hypot(np.diff(px), np.diff(py))
        flag = (fin[:-1] & fin[1:] & (d > 3.0)) | (fin[:-1] != fin[1:]) & (np.abs(np.diff(ts)) > 1e-12)
        flag &= d < 1e5
        if not flag.any():
            break
        idx = np.nonzero(flag)[0]
        mids = (ts[idx] + ts[idx + 1]) / 2
        ts = np.insert(ts, idx + 1, mids)
        xs = np.insert(xs, idx + 1, _eval(fx, mids))
        ys = np.insert(ys, idx + 1, _eval(fy, mids))
    fin = np.isfinite(xs) & np.isfinite(ys)
    segs: Segments = []
    cur: list[tuple[float, float]] = []
    big = 1e3 * max(view.w, view.h)
    for x, y, ok in zip(xs, ys, fin):
        if not ok or abs(x) > big or abs(y) > big:
            if len(cur) > 1:
                segs.append(cur)
            cur = []
            continue
        cur.append((float(x), float(y)))
    if len(cur) > 1:
        segs.append(cur)
    return segs


def sample_polar(fr: Callable, t0: float, t1: float, view: View, k: float) -> Segments:
    """Polar curve r(θ); θ is given in the angle unit of the session (k converts it to radians)."""
    def fx(t):
        return fr(t) * np.cos(np.asarray(t) * k)

    def fy(t):
        return fr(t) * np.sin(np.asarray(t) * k)
    return sample_parametric(fx, fy, t0, t1, view)


# ----------------------------------------------------------------------------------------------------------------- implicit curves
def _grid(view: View, cell_px: float):
    nx = int(min(420, max(20, view.width / cell_px)))
    ny = int(min(320, max(20, view.height / cell_px)))
    xs = np.linspace(view.xmin, view.xmax, nx + 1)
    ys = np.linspace(view.ymin, view.ymax, ny + 1)
    return xs, ys


def implicit_segments(F: Callable, view: View, cell_px: float = 3.0) -> Segments:
    """Marching squares for F(x, y) = 0 with edge-exact stitching and a pole test (so tan(y) = x is not drawn through its poles)."""
    xs, ys = _grid(view, cell_px)
    X, Y = np.meshgrid(xs, ys)
    with np.errstate(all="ignore"):
        Z = np.asarray(F(X, Y), dtype=float)
    if Z.shape != X.shape:
        Z = np.broadcast_to(Z, X.shape).copy()
    Z = np.where(np.isfinite(Z), Z, np.nan)
    ny, nx = Z.shape[0] - 1, Z.shape[1] - 1
    s = np.sign(Z)
    # crossings on horizontal edges (between (i,j) and (i,j+1)) and vertical edges
    hx = np.zeros((ny + 1, nx)) * np.nan
    hy = np.zeros((ny + 1, nx)) * np.nan
    hmask = (s[:, :-1] * s[:, 1:] < 0) | ((Z[:, :-1] == 0) & (Z[:, 1:] != 0))
    a, b = Z[:, :-1], Z[:, 1:]
    with np.errstate(all="ignore"):
        t = a / (a - b)
    px = xs[:-1][None, :] + t * (xs[1:] - xs[:-1])[None, :]
    hx = np.where(hmask, px, np.nan)
    hy = np.where(hmask, np.broadcast_to(ys[:, None], hx.shape), np.nan)
    vmask = (s[:-1, :] * s[1:, :] < 0) | ((Z[:-1, :] == 0) & (Z[1:, :] != 0))
    a2, b2 = Z[:-1, :], Z[1:, :]
    with np.errstate(all="ignore"):
        t2 = a2 / (a2 - b2)
    vy = np.where(vmask, ys[:-1][:, None] + t2 * (ys[1:] - ys[:-1])[:, None], np.nan)
    vx = np.where(vmask, np.broadcast_to(xs[None, :], vy.shape), np.nan)
    # reject poles: F at the crossing must be smaller than at both ends of the edge
    def keep_h():
        idx = np.nonzero(hmask)
        with np.errstate(all="ignore"):
            fv = np.abs(np.asarray(F(hx[idx], hy[idx]), dtype=float))
        bound = np.maximum(np.abs(a[idx]), np.abs(b[idx]))
        ok = np.isfinite(fv) & (fv <= bound)
        m = np.zeros_like(hmask)
        m[idx[0][ok], idx[1][ok]] = True
        return m
    def keep_v():
        idx = np.nonzero(vmask)
        with np.errstate(all="ignore"):
            fv = np.abs(np.asarray(F(vx[idx], vy[idx]), dtype=float))
        bound = np.maximum(np.abs(a2[idx]), np.abs(b2[idx]))
        ok = np.isfinite(fv) & (fv <= bound)
        m = np.zeros_like(vmask)
        m[idx[0][ok], idx[1][ok]] = True
        return m
    hmask, vmask = keep_h(), keep_v()
    # cell segments
    adj: dict[tuple, list[tuple]] = {}
    pts: dict[tuple, tuple[float, float]] = {}
    def hid(i, j):
        k = ("h", i, j)
        pts[k] = (float(hx[i, j]), float(hy[i, j]))
        return k
    def vid(i, j):
        k = ("v", i, j)
        pts[k] = (float(vx[i, j]), float(vy[i, j]))
        return k
    segs_edges: list[tuple[tuple, tuple]] = []
    for i in range(ny):
        for j in range(nx):
            e = []
            if hmask[i, j]:
                e.append(("h", i, j))
            if hmask[i + 1, j]:
                e.append(("h", i + 1, j))
            if vmask[i, j]:
                e.append(("v", i, j))
            if vmask[i, j + 1]:
                e.append(("v", i, j + 1))
            if len(e) == 2:
                segs_edges.append((e[0], e[1]))
            elif len(e) == 4:                               # saddle: pair by the sign at the cell centre
                c = np.nanmean([Z[i, j], Z[i, j + 1], Z[i + 1, j], Z[i + 1, j + 1]])
                if (c > 0) == (Z[i, j] > 0):
                    segs_edges += [(e[0], e[2]), (e[1], e[3])]
                else:
                    segs_edges += [(e[0], e[3]), (e[1], e[2])]
    for k in {k for s in segs_edges for k in s}:
        if k[0] == "h":
            hid(k[1], k[2])
        else:
            vid(k[1], k[2])
    for a_, b_ in segs_edges:
        adj.setdefault(a_, []).append(b_)
        adj.setdefault(b_, []).append(a_)
    used: set[tuple] = set()
    polylines: Segments = []
    def walk(start):
        line = [start]
        prev, cur = None, start
        while True:
            nxt = [n for n in adj[cur] if n != prev and (cur, n) not in used and (n, cur) not in used]
            if not nxt:
                break
            n = nxt[0]
            used.add((cur, n))
            line.append(n)
            prev, cur = cur, n
            if cur == start:
                break
        return line
    ends = [k for k, v in adj.items() if len(v) == 1]
    for k in ends + list(adj):
        if any(((k, n) in used or (n, k) in used) for n in adj[k]) and k not in ends:
            continue
        line = walk(k)
        if len(line) >= 2:
            polylines.append([pts[p] for p in line])
    return polylines


def inequality_runs(G: Callable, view: View, cell_px: float = 4.0) -> dict:
    """Region where a boolean condition G(x, y) holds, as horizontal runs of grid cells."""
    xs, ys = _grid(view, cell_px)
    xc, yc = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2
    X, Y = np.meshgrid(xc, yc)
    with np.errstate(all="ignore"):
        M = np.asarray(G(X, Y), dtype=bool)
    if M.shape != X.shape:
        M = np.broadcast_to(M, X.shape).copy()
    runs = []
    for i in range(M.shape[0]):
        row = M[i]
        if not row.any():
            continue
        d = np.diff(np.concatenate([[0], row.astype(int), [0]]))
        starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        for s0, e0 in zip(starts, ends):
            runs.append([round(float(ys[i]), 9), round(float(ys[i + 1]), 9), round(float(xs[s0]), 9), round(float(xs[e0]), 9)])
    return {"runs": runs, "cell": [float(xs[1] - xs[0]), float(ys[1] - ys[0])]}


def vector_field(fx: Callable, fy: Callable, view: View, nx: int = 22) -> list[list[float]]:
    ny = max(6, int(round(nx * view.height / view.width)))
    xs = np.linspace(view.xmin, view.xmax, nx + 2)[1:-1]
    ys = np.linspace(view.ymin, view.ymax, ny + 2)[1:-1]
    X, Y = np.meshgrid(xs, ys)
    with np.errstate(all="ignore"):
        U = np.broadcast_to(np.asarray(fx(X, Y), dtype=float), X.shape)
        V = np.broadcast_to(np.asarray(fy(X, Y), dtype=float), X.shape)
    mag = np.hypot(U, V)
    ok = np.isfinite(mag) & (mag > 0)
    out = []
    cell = min(view.w / (nx + 1), view.h / (ny + 1)) * 0.8
    for x, y, u, v, m, good in zip(X.ravel(), Y.ravel(), U.ravel(), V.ravel(), mag.ravel(), ok.ravel()):
        if good:
            out.append([float(x), float(y), float(u / m * cell), float(v / m * cell), float(m)])
    return out
