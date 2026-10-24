"""Vectors and matrices. Exact wherever the entries are exact; singular and inconsistent systems are reported, not patched."""
from __future__ import annotations

from typing import Any

import sympy as sp

from ...errors import DimensionError, DomainError, EvaluationError, LimitExceeded, SingularMatrixError, UndefinedError, UnsupportedOperation
from . import ops
from .registry import handler
from .values import Table, Vec


def as_vec(v: Any, name: str) -> Vec:
    if isinstance(v, Vec):
        return v
    if ops.is_matrix(v) and (v.rows == 1 or v.cols == 1):
        return Vec(tuple(v))
    raise EvaluationError(f"{name}() needs a vector such as [1, 2, 3]", hint="Write vectors in square brackets.")


def as_mat(v: Any, name: str, square: bool = False) -> sp.MatrixBase:
    if isinstance(v, Vec):
        m = sp.ImmutableMatrix(list(v.items))
    elif ops.is_matrix(v):
        m = v
    else:
        raise EvaluationError(f"{name}() needs a matrix such as [1, 2; 3, 4]", hint="Separate rows with semicolons.")
    if square and m.rows != m.cols:
        raise DimensionError(f"{name}() needs a square matrix (this one is {m.rows}×{m.cols})")
    return m


def _singular(m: sp.MatrixBase) -> bool:
    d = m.det()
    if ops.has_float(m):
        scale = max([abs(x) for x in m] + [sp.Integer(1)])
        return abs(d) <= sp.Float(1e-12) * scale ** m.rows
    return d == 0


@handler("dot")
def f_dot(ev, u, v):
    u, v = as_vec(u, "dot"), as_vec(v, "dot")
    if len(u) != len(v):
        raise DimensionError(f"dot() needs vectors of equal length ({len(u)} and {len(v)})")
    return sp.Add(*[a * b for a, b in zip(u.items, v.items)])


@handler("cross")
def f_cross(ev, u, v):
    u, v = as_vec(u, "cross"), as_vec(v, "cross")
    if len(u) != 3 or len(v) != 3:
        raise DimensionError("cross() needs two vectors with 3 entries each")
    a, b = u.items, v.items
    return Vec((a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]))


@handler("norm")
def f_norm(ev, v):
    items = v.items if isinstance(v, Vec) else list(as_mat(v, "norm"))
    return sp.sqrt(sp.Add(*[sp.Abs(x) ** 2 for x in items]))


@handler("unit")
def f_unit(ev, v):
    v = as_vec(v, "unit")
    n = f_norm(ev, v)
    if n == 0:
        raise UndefinedError("The zero vector has no direction")
    return Vec(tuple(x / n for x in v.items))


@handler("angle")
def f_angle(ev, u, v):
    u, v = as_vec(u, "angle"), as_vec(v, "angle")
    nu, nv = f_norm(ev, u), f_norm(ev, v)
    if nu == 0 or nv == 0:
        raise UndefinedError("The angle with a zero vector is undefined")
    c = sp.simplify(f_dot(ev, u, v) / (nu * nv))
    return ev.angle_out(sp.acos(c))


@handler("det")
def f_det(ev, a):
    m = as_mat(a, "det", True)
    return m.det()


@handler("inv")
def f_inv(ev, a):
    m = as_mat(a, "inv", True)
    if _singular(m):
        raise SingularMatrixError("The matrix is singular (its determinant is 0), so it has no inverse",
                                  hint="A singular matrix has dependent rows or columns.")
    return sp.ImmutableMatrix(m.inv())


@handler("transpose")
def f_transpose(ev, a):
    if isinstance(a, Vec):
        return sp.ImmutableMatrix([list(a.items)])
    return as_mat(a, "transpose").T


@handler("rank")
def f_rank(ev, a):
    return sp.Integer(as_mat(a, "rank").rank())


@handler("trace")
def f_trace(ev, a):
    return as_mat(a, "trace", True).trace()


@handler("rref")
def f_rref(ev, a):
    m, _ = as_mat(a, "rref").rref()
    return sp.ImmutableMatrix(m)


@handler("eigenvals")
def f_eigenvals(ev, a):
    m = as_mat(a, "eigenvals", True)
    if m.rows > 8:
        raise LimitExceeded("Exact eigenvalues are limited to matrices up to 8×8")
    vals = m.eigenvals()
    if sum(vals.values()) != m.rows:
        raise UnsupportedOperation("The eigenvalues have no closed form", hint="Use a numerical method (not part of this calculator) for large symmetric problems.")
    rows = []
    for val, mult in sorted(vals.items(), key=lambda kv: (sp.N(sp.re(kv[0])), sp.N(sp.im(kv[0])))):
        if not ev.complex_mode and (val.has(sp.I) or val.is_real is False):
            raise DomainError("This matrix has complex eigenvalues", hint="Switch to complex mode to see them.")
        rows.append((val, sp.Integer(mult)))
    return Table(("eigenvalue", "multiplicity"), tuple(rows), title="Eigenvalues")


@handler("eigenvecs")
def f_eigenvecs(ev, a):
    m = as_mat(a, "eigenvecs", True)
    if m.rows > 6:
        raise LimitExceeded("Exact eigenvectors are limited to matrices up to 6×6")
    rows = []
    for val, mult, vecs in sorted(m.eigenvects(), key=lambda t: (sp.N(sp.re(t[0])), sp.N(sp.im(t[0])))):
        if not ev.complex_mode and (val.has(sp.I) or val.is_real is False):
            raise DomainError("This matrix has complex eigenvalues", hint="Switch to complex mode to see them.")
        rows.append((val, sp.Integer(mult), tuple(Vec(tuple(x)) for x in vecs)))
    return Table(("eigenvalue", "multiplicity", "eigenvectors"), tuple(rows), title="Eigenvalues and eigenvectors")


@handler("cond")
def f_cond(ev, a):
    import mpmath as mp
    m = as_mat(a, "cond")
    mp.mp.dps = 40
    mm = mp.matrix([[mp.mpmathify(sp.N(x, 45)) for x in m.row(i)] for i in range(m.rows)])
    s = mp.svd_r(mm, compute_uv=False) if not any(isinstance(x, mp.mpc) for x in mm) else None
    if s is None:
        raise UnsupportedOperation("The condition number is only available for real matrices")
    smax, smin = max(s), min(s)
    if smin == 0:
        raise SingularMatrixError("The matrix is singular, so its condition number is infinite")
    ev.numeric_method = "singular values (mpmath, 40 digits)"
    return sp.Float(str(smax / smin), 30)


@handler("nullspace")
def f_nullspace(ev, a):
    basis = as_mat(a, "nullspace").nullspace()
    if not basis:
        return Table(("basis vector",), (), title="The null space contains only the zero vector")
    return Table(("basis vector",), tuple((Vec(tuple(b)),) for b in basis), title="Basis of the null space")


@handler("linsolve")
def f_linsolve(ev, a, b):
    A_ = as_mat(a, "linsolve")
    bv = as_vec(b, "linsolve").column()
    if A_.rows != bv.rows:
        raise DimensionError(f"A has {A_.rows} rows but b has {bv.rows} entries")
    xs = sp.symbols(f"x1:{A_.cols + 1}")
    sol = sp.linsolve((A_, bv), *xs)
    if sol == sp.EmptySet:
        raise SingularMatrixError("The system is inconsistent: it has no solution")
    (tup,) = list(sol)
    if any(t.free_symbols for t in tup):
        free = sorted({s for t in tup for s in t.free_symbols}, key=str)
        raise SingularMatrixError(f"The system has infinitely many solutions ({len(free)} free parameter{'s' if len(free) != 1 else ''})",
                                  hint="The matrix is singular. rref([A | b]) shows the parametric solution.",
                                  details={"general solution": [str(t) for t in tup]})
    return Vec(tuple(tup))


def _size(v: Any, name: str) -> int:
    n = ops.as_int(v, f"The size in {name}()", 1)
    if n > ops.MAX_MATRIX:
        raise LimitExceeded(f"The matrix is too large (limit {ops.MAX_MATRIX}×{ops.MAX_MATRIX})")
    return n


@handler("identity")
def f_identity(ev, n):
    return sp.ImmutableMatrix(sp.eye(_size(n, "identity")))


@handler("zeros")
def f_zeros(ev, r, c=None):
    r = _size(r, "zeros")
    return sp.ImmutableMatrix(sp.zeros(r, r if c is None else _size(c, "zeros")))


@handler("ones")
def f_ones(ev, r, c=None):
    r = _size(r, "ones")
    return sp.ImmutableMatrix(sp.ones(r, r if c is None else _size(c, "ones")))


@handler("diag")
def f_diag(ev, *args):
    vals = []
    for a in args:
        vals.extend(a.items if isinstance(a, Vec) else [ops.plain(a, "diag()")])
    if len(vals) > ops.MAX_MATRIX:
        raise LimitExceeded("Too many diagonal entries")
    return sp.ImmutableMatrix(sp.diag(*vals))
