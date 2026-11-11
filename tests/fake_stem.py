"""A small stand-in for SLAI's STEM agent, used by the tests so they run without SLAI, NumPy or SciPy.

It follows the agent's request contract (``perform_task({domain, operation, args, kwargs, seed, ...})`` -> ``{"result": ...}``, ``available_operations()``)
and returns what the real operations return in shape (``Quantity``-like objects, ``SolverResult``-like objects, dictionaries). It computes with plain
Python, independently of SciCal's own engine, which is what makes it a useful second opinion in the checks. Operations outside its table raise like the
real agent does for an unsupported operation."""
from __future__ import annotations

import ast
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

_F1 = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh, "exp": math.exp, "sqrt": math.sqrt, "abs": abs, "log": math.log}


class FakeError(Exception):
    pass


@dataclass
class Quantity:
    magnitude: float
    unit: str = "1"


@dataclass
class SolverResult:
    solution: float
    residual: float
    iterations: int
    converged: bool = True
    status: str = "converged"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"solution": self.solution, "residual": self.residual, "iterations": self.iterations, "converged": self.converged, "status": self.status, "message": self.message}


def _eval(node: ast.AST, env: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return math.pi
        if node.id == "e":
            return math.e
        if node.id not in env:
            raise FakeError(f"unknown name {node.id}")
        return float(env[node.id])
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
        if isinstance(node.op, ast.Pow):
            return a ** b
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _F1 and len(node.args) == 1:
        return _F1[node.func.id](_eval(node.args[0], env))
    raise FakeError("unsupported expression")


def _check_names(env: dict[str, float]) -> None:
    for k in env:
        if k in _F1 or k in ("pi", "e") or (len(k) == 1 and k in "mgsAKNJWVLC" and k != "T"):          # unit symbols are refused, like the real evaluator
            raise FakeError("Invalid or reserved parameter name")


def _mean(xs): return math.fsum(xs) / len(xs)


def _sd(xs, ddof=1):
    m = _mean(xs)
    return math.sqrt(math.fsum((x - m) ** 2 for x in xs) / (len(xs) - ddof))


def _simpson(f, a, b, n):
    n += n % 2
    h = (b - a) / n
    return h / 3 * (f(a) + f(b) + 4 * math.fsum(f(a + i * h) for i in range(1, n, 2)) + 2 * math.fsum(f(a + i * h) for i in range(2, n, 2)))


def _ncdf(x, mu, sigma): return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))


def _t_pdf(x, v): return math.gamma((v + 1) / 2) / (math.sqrt(v * math.pi) * math.gamma(v / 2)) * (1 + x * x / v) ** (-(v + 1) / 2)


def _t_cdf(x, v):
    if x == 0:
        return 0.5
    area = _simpson(lambda u: _t_pdf(u, v), 0.0, abs(x), 2000)
    return 0.5 + math.copysign(area, x)


def _solve(A, b):
    n = len(A)
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[p][c]) < 1e-300:
            raise FakeError("Matrix is singular")
        M[c], M[p] = M[p], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (M[i][n] - math.fsum(M[i][k] * x[k] for k in range(i + 1, n))) / M[i][i]
    return x


def _inverse(A):
    n = len(A)
    cols = [_solve(A, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[cols[j][i] for j in range(n)] for i in range(n)]


def _norm1(A): return max(math.fsum(abs(A[i][j]) for i in range(len(A))) for j in range(len(A)))
def _norminf(A): return max(math.fsum(abs(v) for v in r) for r in A)


def _linreg(xs, ys):
    mx, my = _mean(xs), _mean(ys)
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    sxy = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = sxy / sxx
    icpt = my - slope * mx
    rss = math.fsum((y - (icpt + slope * x)) ** 2 for x, y in zip(xs, ys))
    tss = math.fsum((y - my) ** 2 for y in ys)
    return {"slope": slope, "intercept": icpt, "r_squared": 1 - rss / tss, "residual_sum_squares": rss}


class FakeSTEM:
    """``FakeSTEM(tamper={"statistics.mean": lambda v: v + 1})`` makes an operation give a wrong answer, to prove the checks notice."""

    def __init__(self, tamper: dict[str, Callable[[Any], Any]] | None = None) -> None:
        self.tamper = tamper or {}
        self.calls: list[tuple[str, str]] = []
        self.table: dict[str, dict[str, Callable[..., Any]]] = {
            "parametric": {"evaluate_expression": self._evaluate, "derivative": self._derivative},
            "statistics": {"mean": lambda xs: _mean(xs), "median": lambda xs: sorted(xs)[len(xs) // 2] if len(xs) % 2 else (sorted(xs)[len(xs) // 2 - 1] + sorted(xs)[len(xs) // 2]) / 2,
                           "standard_deviation": lambda xs, ddof=1: _sd(xs, ddof), "normal_cdf": _ncdf, "t_cdf": _t_cdf, "linear_regression": _linreg,
                           "binomial_pmf": lambda k, n, p: math.comb(n, k) * p ** k * (1 - p) ** (n - k),
                           "correlation": lambda xs, ys: _linreg(xs, ys)["slope"] * _sd(xs) / _sd(ys),
                           "bootstrap_ci": self._bootstrap},
            "numerical_methods": {"adaptive_quadrature": lambda f, a, b, tol=None, max_depth=20: _simpson(f, a, b, 2000), "trapezoidal": lambda f, a, b, n=100: (b - a) / n * (f(a) / 2 + math.fsum(f(a + i * (b - a) / n) for i in range(1, n)) + f(b) / 2),
                                  "simpson": lambda f, a, b, n=100: _simpson(f, a, b, n), "romberg": lambda f, a, b, tol=None, max_iter=8: _simpson(f, a, b, 1000),
                                  "gauss_legendre": lambda f, a, b, n=5: _simpson(f, a, b, 1000), "solve_linear_system": _solve, "matrix_inverse": _inverse,
                                  "condition_numbers": lambda A: {"2_norm": _norm1(A) * _norm1(_inverse(A)), "1_norm": _norm1(A) * _norm1(_inverse(A)), "inf_norm": _norminf(A) * _norminf(_inverse(A))},
                                  "residuals": lambda A, x, b: {"l1": 0.0, "l2": 0.0, "linf": max(abs(math.fsum(a * v for a, v in zip(r, x)) - bb) for r, bb in zip(A, b))},
                                  "backward_error": lambda A, x, b: 0.0, "bisection": self._bisection, "secant": self._secant, "newton_raphson": self._newton,
                                  "rk4": self._rk4, "euler": self._euler, "rk45_adaptive": lambda f, y0, t0, t1, rtol=1e-6, atol=1e-9, h0=None: self._rk4(f, y0, t0, t1, (t1 - t0) / 400),
                                  "linear_interpolation": self._linear_interp, "polynomial_interpolation": self._lagrange, "cubic_spline": self._linear_interp},
            "uncertainty": {"combined_standard_uncertainty": lambda us, sensitivity=None: math.sqrt(math.fsum((s * u) ** 2 for s, u in zip(sensitivity or [1.0] * len(us), us))),
                            "expanded_uncertainty": lambda u, k=2.0: u * k, "sensitivity_coefficients": self._sensitivity,
                            "jacobian_propagation": lambda J, us: math.sqrt(math.fsum((j * u) ** 2 for j, u in zip(J, us))), "monte_carlo_propagation": self._mc},
            "computing": {"gcd": math.gcd, "lcm": math.lcm, "factorial": math.factorial, "binomial": math.comb},
            "physics": {"ideal_gas_pressure": lambda n, T, V: n * 8.31446261815324 * T / V},
            "biology": {"michaelis_menten": lambda s, vmax, km: vmax * s / (km + s)},
            "units": {"convert": self._convert},
        }

    # ------------------------------------------------------------------ the agent's surface
    def available_operations(self) -> dict[str, tuple[str, ...]]:
        return {d: tuple(ops) for d, ops in self.table.items()}

    def perform_task(self, task: dict[str, Any]) -> dict[str, Any]:
        domain, op = str(task.get("domain")), task.get("operation")
        fn = self.table.get(domain, {}).get(op) if isinstance(op, str) else None
        if fn is None:
            raise FakeError("Unsupported STEM operation")
        self.calls.append((domain, op))
        kwargs = dict(task.get("kwargs") or {})
        if task.get("seed") is not None:
            kwargs["seed"] = task["seed"]
        try:
            result = fn(*task.get("args", ()), **{k: v for k, v in kwargs.items() if not (k == "seed" and domain != "uncertainty" and op != "bootstrap_ci")})
        except FakeError:
            raise
        except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            raise FakeError(f"STEM operation arguments are invalid ({exc})") from exc
        t = self.tamper.get(f"{domain}.{op}")
        if t:
            result = t(result)
        return {"status": "success", "domain": domain, "operation": op, "result": result, "cache_hit": False}

    # ------------------------------------------------------------------ operations
    def _evaluate(self, expression: str, parameters: dict[str, float] | None = None) -> Quantity:
        env = dict(parameters or {})
        _check_names(env)
        return Quantity(_eval(ast.parse(expression, mode="eval"), env))

    def _derivative(self, expression: str, parameters: dict[str, float], variable: str) -> dict[str, Any]:
        x = float(parameters[variable])
        h = 1e-5 * max(1.0, abs(x))
        f = lambda v: self._evaluate(expression, {**parameters, variable: v}).magnitude          # noqa: E731
        return {"value": (f(x + h) - f(x - h)) / (2 * h), "method": "central_difference"}

    def _sensitivity(self, model, values, steps=None):
        out = []
        for i, v in enumerate(values):
            h = 1e-6 * max(1.0, abs(v))
            up, dn = list(values), list(values)
            up[i], dn[i] = v + h, v - h
            out.append((model(*up) - model(*dn)) / (2 * h))
        return out

    def _mc(self, model, means, us, distributions=None, samples=10000, seed=0):
        rng = random.Random(int(seed))
        outs = sorted(model(*[rng.gauss(m, u) for m, u in zip(means, us)]) for _ in range(samples))
        return {"mean": _mean(outs), "standard_uncertainty": _sd(outs), "coverage_interval_95": (outs[int(0.025 * (samples - 1))], outs[int(0.975 * (samples - 1))]), "samples": samples, "seed": int(seed)}

    def _bootstrap(self, xs, statistic, n_resamples, confidence=0.95, rng=None, seed=None):
        r = random.Random(seed if seed is not None else 0)
        est = sorted(statistic([xs[r.randrange(len(xs))] for _ in xs]) for _ in range(n_resamples))
        a = (1 - confidence) / 2
        return {"estimate": statistic(xs), "lower": est[int(a * (n_resamples - 1))], "upper": est[int((1 - a) * (n_resamples - 1))], "confidence": confidence}

    def _bisection(self, f, a, b, tol=None, max_iter=None):
        fa = f(a)
        if fa * f(b) > 0:
            raise FakeError("Root is not bracketed")
        n = 0
        while b - a > (tol or 1e-12) and n < 200:
            m = (a + b) / 2
            if fa * f(m) <= 0:
                b = m
            else:
                a, fa = m, f(m)
            n += 1
        r = (a + b) / 2
        return SolverResult(r, abs(f(r)), n)

    def _secant(self, f, x0, x1, tol=None, max_iter=None):
        n = 0
        while abs(x1 - x0) > (tol or 1e-12) and n < 100:
            f0, f1 = f(x0), f(x1)
            if f1 == f0:
                break
            x0, x1 = x1, x1 - f1 * (x1 - x0) / (f1 - f0)
            n += 1
        return SolverResult(x1, abs(f(x1)), n)

    def _newton(self, f, df, x0, tol=None, max_iter=None):
        x, n = x0, 0
        while n < 100:
            step = f(x) / df(x)
            x -= step
            n += 1
            if abs(step) < (tol or 1e-12):
                break
        return SolverResult(x, abs(f(x)), n)

    def _rk4(self, f, y0, t0, t1, h=None):
        h = h or (t1 - t0) / 100
        t, y, ts, ys = t0, list(map(float, y0)), [t0], [list(map(float, y0))]
        while t < t1 - 1e-15:
            dt = min(h, t1 - t)
            k1 = f(t, y)
            k2 = f(t + dt / 2, [a + dt / 2 * k for a, k in zip(y, k1)])
            k3 = f(t + dt / 2, [a + dt / 2 * k for a, k in zip(y, k2)])
            k4 = f(t + dt, [a + dt * k for a, k in zip(y, k3)])
            y = [a + dt / 6 * (p + 2 * q + 2 * r + s) for a, p, q, r, s in zip(y, k1, k2, k3, k4)]
            t += dt
            ts.append(t)
            ys.append(list(y))
        return {"t": ts, "y": ys, "method": "rk4", "steps": len(ts) - 1, "converged": True}

    def _euler(self, f, y0, t0, t1, h=None):
        h = h or (t1 - t0) / 100
        t, y, ts, ys = t0, list(map(float, y0)), [t0], [list(map(float, y0))]
        while t < t1 - 1e-15:
            dt = min(h, t1 - t)
            y = [a + dt * k for a, k in zip(y, f(t, y))]
            t += dt
            ts.append(t)
            ys.append(list(y))
        return {"t": ts, "y": ys, "method": "euler", "steps": len(ts) - 1, "converged": True}

    def _linear_interp(self, xs, ys):
        def at(q):
            if q < xs[0] or q > xs[-1]:
                raise FakeError("Query outside interpolation domain")
            for i in range(len(xs) - 1):
                if xs[i] <= q <= xs[i + 1]:
                    return ys[i] + (ys[i + 1] - ys[i]) * (q - xs[i]) / (xs[i + 1] - xs[i])
            return ys[-1]
        return at

    def _lagrange(self, xs, ys):
        def at(q):
            return math.fsum(y * math.prod((q - xj) / (xi - xj) for j, xj in enumerate(xs) if j != i) for i, (xi, y) in enumerate(zip(xs, ys)))
        return at

    _TO_SI = {"m": 1.0, "cm": 0.01, "mm": 0.001, "km": 1000.0, "g": 0.001, "kg": 1.0, "s": 1.0, "ms": 0.001, "min": 60.0, "h": 3600.0}

    def _convert(self, value, src, dst):
        if src not in self._TO_SI or dst not in self._TO_SI:
            raise FakeError("Unknown unit")
        return Quantity(value * self._TO_SI[src] / self._TO_SI[dst], dst)


def make() -> FakeSTEM:
    """The ``SCICAL_STEM_PROVIDER=tests.fake_stem:make`` hook used by the server tests."""
    return FakeSTEM()
