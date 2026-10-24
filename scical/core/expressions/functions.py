"""The catalogue of built-in functions: one table used by the parser (what is a function), the evaluator (argument handling), the web
client (function menus) and the documentation. The implementations live in ``core/numerical/funcs.py``.

Argument specs, one letter per argument:  E value | S symbol (a variable name, never evaluated) | L lazy expression (evaluated with
the symbols named by the S arguments left free) | R relation or expression | V vector/matrix | * the last letter repeats.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fn:
    name: str
    spec: str                 # argument letters; trailing '*' repeats the last letter; trailing '?' marks optional ones
    category: str
    signature: str
    doc: str
    latex: str = ""           # LaTeX command for plain-function rendering, e.g. \sin
    min_args: int = 0
    max_args: int | None = 0

    def check_arity(self, n: int) -> bool:
        return n >= self.min_args and (self.max_args is None or n <= self.max_args)


def spec_letters(spec: str) -> tuple[list[tuple[str, bool]], bool]:
    """``[(letter, optional), ...]`` and whether the last letter repeats."""
    var = spec.endswith("*")
    body = spec[:-1] if var else spec
    letters: list[tuple[str, bool]] = []
    i = 0
    while i < len(body):
        opt = i + 1 < len(body) and body[i + 1] == "?"
        letters.append((body[i], opt))
        i += 2 if opt else 1
    return letters, var


def _arity(spec: str) -> tuple[int, int | None]:
    letters, var = spec_letters(spec)
    required = sum(1 for _, opt in letters if not opt)
    return required, None if var else len(letters)


FUNCTIONS: dict[str, Fn] = {}
ALIASES: dict[str, str] = {}


def _add(names: str, spec: str, category: str, signature: str, doc: str, latex: str = "") -> None:
    first, *rest = names.split("|")
    lo, hi = _arity(spec)
    FUNCTIONS[first] = Fn(first, spec, category, signature, doc, latex or "\\operatorname{" + first + "}", lo, hi)
    for r in rest:
        ALIASES[r] = first


# ---- arithmetic -------------------------------------------------------------------------------------------------------------
_add("abs", "E", "arithmetic", "abs(x)", "Absolute value (modulus of a complex number).")
_add("sign|sgn", "E", "arithmetic", "sign(x)", "-1, 0 or 1.")
_add("sqrt", "E", "arithmetic", "sqrt(x)", "Square root. Negative arguments need complex mode.", "\\sqrt")
_add("cbrt", "E", "arithmetic", "cbrt(x)", "Real cube root.")
_add("root", "EE", "arithmetic", "root(x, n)", "The n-th root (real for odd n and negative x).")
_add("exp", "E", "arithmetic", "exp(x)", "e to the power x.", "\\exp")
_add("ln", "E", "arithmetic", "ln(x)", "Natural logarithm.", "\\ln")
_add("log", "EE?", "arithmetic", "log(x) or log(x, base)", "Common (base 10) logarithm, or the logarithm to the given base.", "\\log")
_add("log10", "E", "arithmetic", "log10(x)", "Base-10 logarithm.", "\\log_{10}")
_add("log2|lb", "E", "arithmetic", "log2(x)", "Base-2 logarithm.", "\\log_{2}")
_add("floor", "E", "arithmetic", "floor(x)", "Greatest integer not above x.", "\\lfloor")
_add("ceil", "E", "arithmetic", "ceil(x)", "Least integer not below x.", "\\lceil")
_add("round", "EE?", "arithmetic", "round(x) or round(x, digits)", "Round half away from zero.")
_add("trunc", "E", "arithmetic", "trunc(x)", "Integer part (towards zero).")
_add("frac", "E", "arithmetic", "frac(x)", "Fractional part x - trunc(x).")
_add("sig", "EE", "arithmetic", "sig(x, n)", "Round to n significant figures.")
_add("min", "E*", "arithmetic", "min(a, b, ...)", "Smallest of the arguments (or of a vector).")
_add("max", "E*", "arithmetic", "max(a, b, ...)", "Largest of the arguments (or of a vector).")
_add("mod", "EE", "arithmetic", "mod(a, b)", "Remainder with the sign of b (also written a mod b).")
_add("gcd", "EE*", "number theory", "gcd(a, b, ...)", "Greatest common divisor.")
_add("lcm", "EE*", "number theory", "lcm(a, b, ...)", "Least common multiple.")
_add("factorial|fact", "E", "number theory", "factorial(n) or n!", "n! for integers n >= 0 (gamma function for other reals).")
_add("nPr|perm|npr", "EE", "number theory", "nPr(n, r)", "Permutations n!/(n-r)!.")
_add("nCr|comb|ncr|binomial|choose", "EE", "number theory", "nCr(n, r)", "Combinations n!/(r!(n-r)!).")
_add("isprime", "E", "number theory", "isprime(n)", "True if n is prime.")
_add("factorint|primefactors", "E", "number theory", "factorint(n)", "Prime factorisation of an integer.")
_add("fib|fibonacci", "E", "number theory", "fib(n)", "The n-th Fibonacci number.")
# ---- trigonometry -----------------------------------------------------------------------------------------------------------
for _n in ("sin", "cos", "tan", "sec", "csc", "cot"):
    _add(_n, "E", "trigonometry", f"{_n}(x)", f"{_n.capitalize()} of an angle in the current angle mode (or of an angle with a unit).", "\\" + _n)
for _n, _d in (("asin|arcsin", "arcsine"), ("acos|arccos", "arccosine"), ("atan|arctan", "arctangent"), ("asec|arcsec", "arcsecant"),
               ("acsc|arccsc", "arccosecant"), ("acot|arccot", "arccotangent")):
    f0 = _n.split("|")[0]
    _add(_n, "E", "trigonometry", f"{f0}(x)", f"Inverse trigonometric function ({_d}); the result is in the current angle mode.",
         "\\arc" + f0[1:] if f0[1:] in ("sin", "cos", "tan") else "\\operatorname{" + f0 + "}")
_add("atan2", "EE", "trigonometry", "atan2(y, x)", "Angle of the point (x, y) in the current angle mode.", "\\operatorname{atan2}")
_add("todeg", "E", "trigonometry", "todeg(x)", "Radians to degrees.")
_add("torad", "E", "trigonometry", "torad(x)", "Degrees to radians.")
for _n in ("sinh", "cosh", "tanh", "sech", "csch", "coth"):
    _add(_n, "E", "hyperbolic", f"{_n}(x)", f"Hyperbolic {_n[:-1]}.", "\\" + _n if _n in ("sinh", "cosh", "tanh", "coth") else "\\operatorname{" + _n + "}")
for _n in ("asinh|arcsinh", "acosh|arccosh", "atanh|arctanh"):
    f0 = _n.split("|")[0]
    _add(_n, "E", "hyperbolic", f"{f0}(x)", "Inverse hyperbolic function.", "\\operatorname{" + f0 + "}")
# ---- complex ----------------------------------------------------------------------------------------------------------------
_add("re|real", "E", "complex", "re(z)", "Real part.", "\\operatorname{Re}")
_add("im|imag", "E", "complex", "im(z)", "Imaginary part.", "\\operatorname{Im}")
_add("conj", "E", "complex", "conj(z)", "Complex conjugate.", "\\overline")
_add("arg|phase", "E", "complex", "arg(z)", "Argument (angle) of a complex number in the current angle mode.", "\\arg")
_add("polar", "E", "complex", "polar(z)", "Magnitude and angle [r, θ] of z.")
_add("rect", "EE", "complex", "rect(r, theta)", "The complex number r∠θ in rectangular form.")
# ---- vectors and matrices ---------------------------------------------------------------------------------------------------
_add("dot", "VV", "vectors", "dot(u, v)", "Dot product.")
_add("cross", "VV", "vectors", "cross(u, v)", "Cross product of two 3-vectors.")
_add("norm|mag", "V", "vectors", "norm(v)", "Euclidean length of a vector (Frobenius norm of a matrix).")
_add("unit", "V", "vectors", "unit(v)", "The vector scaled to length 1.")
_add("angle", "VV", "vectors", "angle(u, v)", "Angle between two vectors in the current angle mode.")
_add("det", "V", "matrices", "det(A)", "Determinant.", "\\det")
_add("inv|inverse", "V", "matrices", "inv(A)", "Matrix inverse (an error for singular matrices).")
_add("transpose|tr_", "V", "matrices", "transpose(A)", "Transpose.")
_add("rank", "V", "matrices", "rank(A)", "Rank.", "\\operatorname{rank}")
_add("trace", "V", "matrices", "trace(A)", "Trace.", "\\operatorname{tr}")
_add("rref", "V", "matrices", "rref(A)", "Reduced row echelon form.")
_add("eigenvals|eig", "V", "matrices", "eigenvals(A)", "Eigenvalues with multiplicity.")
_add("eigenvecs", "V", "matrices", "eigenvecs(A)", "Eigenvalues and their eigenvectors.")
_add("cond", "V", "matrices", "cond(A)", "2-norm condition number (numerical).")
_add("nullspace", "V", "matrices", "nullspace(A)", "Basis of the null space.")
_add("linsolve", "VV", "matrices", "linsolve(A, b)", "Solve A x = b exactly; reports singular or inconsistent systems.")
_add("identity|eye", "E", "matrices", "identity(n)", "The n by n identity matrix.")
_add("zeros", "EE?", "matrices", "zeros(rows, cols)", "A matrix of zeros.")
_add("ones", "EE?", "matrices", "ones(rows, cols)", "A matrix of ones.")
_add("diag", "E*", "matrices", "diag(a, b, ...)", "A diagonal matrix.")
# ---- statistics -------------------------------------------------------------------------------------------------------------
_add("mean|avg", "V", "statistics", "mean(v)", "Arithmetic mean.", "\\bar{x}")
_add("median", "V", "statistics", "median(v)", "Median.")
_add("mode", "V", "statistics", "mode(v)", "Most frequent value(s).")
_add("sum", "E*", "statistics", "sum(v) or sum(f, k, a, b)", "Sum of the elements of a vector, or the series Σ f(k) for k = a..b.", "\\sum")
_add("prod|product", "E*", "statistics", "prod(v) or prod(f, k, a, b)", "Product of elements, or Π f(k) for k = a..b.", "\\prod")
_add("sumsq", "V", "statistics", "sumsq(v)", "Sum of squares.")
_add("var|variance", "V", "statistics", "var(v)", "Sample variance (divides by n - 1).")
_add("varp", "V", "statistics", "varp(v)", "Population variance (divides by n).")
_add("std|stdev", "V", "statistics", "std(v)", "Sample standard deviation (n - 1).")
_add("stdp", "V", "statistics", "stdp(v)", "Population standard deviation (n).")
_add("stderr", "V", "statistics", "stderr(v)", "Standard error of the mean, std/sqrt(n).")
_add("range", "V", "statistics", "range(v)", "Maximum minus minimum.")
_add("q1", "V", "statistics", "q1(v)", "First quartile (median of the lower half, median excluded).")
_add("q3", "V", "statistics", "q3(v)", "Third quartile (median of the upper half, median excluded).")
_add("iqr", "V", "statistics", "iqr(v)", "Interquartile range.")
_add("percentile", "VE", "statistics", "percentile(v, p)", "Percentile p (0-100), linear interpolation.")
_add("cov", "VV", "statistics", "cov(x, y)", "Sample covariance.")
_add("covp", "VV", "statistics", "covp(x, y)", "Population covariance.")
_add("corr|correlation", "VV", "statistics", "corr(x, y)", "Pearson correlation coefficient.")
_add("slope", "VV", "statistics", "slope(x, y)", "Slope of the least-squares line.")
_add("intercept", "VV", "statistics", "intercept(x, y)", "Intercept of the least-squares line.")
_add("rsq", "VV", "statistics", "rsq(x, y)", "Coefficient of determination of the least-squares line.")
_add("sort", "V", "statistics", "sort(v)", "Ascending order.")
_add("count|len", "V", "statistics", "count(v)", "Number of elements.")
_add("zscore", "VE", "statistics", "zscore(v, x)", "(x - mean)/std of the sample v.")
_add("normalpdf", "EE?E?", "distributions", "normalpdf(x, mu, sigma)", "Normal density (mu 0, sigma 1 by default).")
_add("normalcdf", "EE?E?", "distributions", "normalcdf(x, mu, sigma)", "P(X <= x) for a normal distribution.")
_add("normalprob", "EEE?E?", "distributions", "normalprob(a, b, mu, sigma)", "P(a <= X <= b) for a normal distribution.")
_add("invnorm", "EE?E?", "distributions", "invnorm(p, mu, sigma)", "Quantile of the normal distribution.")
_add("binompdf", "EEE", "distributions", "binompdf(n, p, k)", "P(X = k) for a binomial distribution.")
_add("binomcdf", "EEE", "distributions", "binomcdf(n, p, k)", "P(X <= k) for a binomial distribution.")
_add("poissonpdf", "EE", "distributions", "poissonpdf(lambda, k)", "P(X = k) for a Poisson distribution.")
_add("poissoncdf", "EE", "distributions", "poissoncdf(lambda, k)", "P(X <= k) for a Poisson distribution.")
_add("tpdf", "EE", "distributions", "tpdf(x, df)", "Student's t density.")
_add("tcdf", "EE", "distributions", "tcdf(x, df)", "P(T <= x) for Student's t.")
_add("invt", "EE", "distributions", "invt(p, df)", "Quantile of Student's t.")
_add("chi2pdf", "EE", "distributions", "chi2pdf(x, df)", "Chi-square density.")
_add("chi2cdf", "EE", "distributions", "chi2cdf(x, df)", "P(X <= x) for chi-square.")
_add("tinterval", "VE?", "distributions", "tinterval(v, level)", "Confidence interval [low, high] for the mean (t distribution, default level 0.95).")
_add("zinterval", "VEE?", "distributions", "zinterval(v, sigma, level)", "Confidence interval for the mean with known population sigma.")
_add("propinterval", "EEE?", "distributions", "propinterval(x, n, level)", "Wilson confidence interval for a proportion x/n.")
# ---- algebra and calculus (symbolic) ----------------------------------------------------------------------------------------
_add("simplify", "L", "algebra", "simplify(expr)", "Simplify an expression.")
_add("expand", "L", "algebra", "expand(expr)", "Expand products and powers.")
_add("factor", "L", "algebra", "factor(expr)", "Factor over the rationals.")
_add("apart", "LS?", "algebra", "apart(expr, x)", "Partial fractions.")
_add("together", "L", "algebra", "together(expr)", "Combine into a single fraction.")
_add("subs|substitute", "LSE", "algebra", "subs(expr, x, value)", "Substitute a value for a variable.")
_add("solve", "R*", "algebra", "solve(equation, x) or solve([eq1, eq2], [x, y])", "Solve equations, inequalities and linear or polynomial systems.")
_add("roots", "LS?", "algebra", "roots(polynomial, x)", "All roots of a polynomial with multiplicity.")
_add("coeffs", "LS?", "algebra", "coeffs(polynomial, x)", "Coefficients, highest power first.")
_add("degree", "LS?", "algebra", "degree(polynomial, x)", "Degree of a polynomial.")
_add("nsolve", "LSEE?", "algebra", "nsolve(f, x, guess) or nsolve(f, x, a, b)", "Numerical root near a guess, or in the interval [a, b].")
_add("diff|derivative|partial", "LSE?", "calculus", "diff(f, x) or diff(f, x, n)", "Symbolic derivative (partial when f has other variables).", "\\frac{d}{dx}")
_add("integral|integrate", "LSE?E?", "calculus", "integral(f, x) or integral(f, x, a, b)", "Indefinite or definite integral (exact).", "\\int")
_add("nintegral", "LSEE", "calculus", "nintegral(f, x, a, b)", "Numerical integral with an error estimate.")
_add("nderiv", "LSE", "calculus", "nderiv(f, x, a)", "Numerical derivative at a point with an error estimate.")
_add("limit", "LSEE?", "calculus", "limit(f, x, a) or limit(f, x, a, dir)", "Limit as x approaches a. dir = 1 means from the right, -1 from the left; without dir both sides must agree.", "\\lim")
_add("taylor", "LSEE", "calculus", "taylor(f, x, a, n)", "Taylor polynomial of degree n about a.")
_add("critical", "LS", "calculus", "critical(f, x)", "Critical points and their classification.")
# ---- control and misc ---------------------------------------------------------------------------------------------------------
_add("if", "REE", "control", "if(condition, then, else)", "Evaluates only the chosen branch.")
_add("piecewise", "R*", "control", "piecewise(cond1, value1, cond2, value2, ..., default)", "The value of the first true condition.")
_add("const", "S", "constants", "const(name)", "A CODATA 2022 constant, e.g. const(c), const(h), const(NA).")
_add("tobase", "EE", "number bases", "tobase(n, base)", "Integer n written in base 2 to 36.")
_add("hex", "E", "number bases", "hex(n)", "Integer in hexadecimal.")
_add("bin", "E", "number bases", "bin(n)", "Integer in binary.")
_add("oct", "E", "number bases", "oct(n)", "Integer in octal.")

TRIG_POWERABLE = frozenset({"sin", "cos", "tan", "sec", "csc", "cot", "sinh", "cosh", "tanh", "sech", "csch", "coth"})
CONSTANT_NAMES = frozenset({"pi", "π", "e", "i", "inf", "tau", "τ", "oo", "∞"})
KEYWORDS = frozenset({"to", "and", "or", "not", "mod"})


def canonical(name: str) -> str | None:
    """The canonical function name for ``name`` (resolving aliases), or None if it is not a built-in function."""
    if name in FUNCTIONS:
        return name
    return ALIASES.get(name)


def is_function(name: str) -> bool:
    return canonical(name) is not None


def catalogue() -> list[dict]:
    return [{"name": f.name, "category": f.category, "signature": f.signature, "doc": f.doc,
             "aliases": sorted(a for a, t in ALIASES.items() if t == f.name)} for f in FUNCTIONS.values()]
