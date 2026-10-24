"""The exact evaluator: AST -> value. User text never reaches ``eval`` or ``sympify``; SymPy objects are built from the parsed tree.

Rules worth knowing (all tested):
* numbers typed with a decimal point are exact decimals (0.1 + 0.2 = 3/10); a numerical method (nsolve, nintegral, a distribution)
  returns a floating-point value that is labelled approximate;
* in real mode a result that is not a real number is an error, never a silently complex answer; (-8)^(1/3) is -2;
* division by zero, 0^0 and indeterminate forms are errors;
* names that are not defined stay symbols, so algebra works (x + x = 2x).
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

import sympy as sp

from ...errors import (ArityError, BadRequest, ComplexResultError, DimensionError, EvaluationError, LimitExceeded, ParseError,
                       SciCalError, UndefinedError, UnitError, UnknownNameError)
from ..expressions import ast as A
from ..expressions.functions import CONSTANT_NAMES, FUNCTIONS, KEYWORDS, canonical, spec_letters
from ..expressions.printer import to_text
from ..units import Quantity, Unit, convert, parse_unit
from ..units import quantity as Q
from ..units.constants import get as get_constant
from . import ops
from .context import Context
from .values import Equation, Text, Vec

_CONSTS = {"pi": sp.pi, "π": sp.pi, "tau": 2 * sp.pi, "τ": 2 * sp.pi, "e": sp.E, "inf": sp.oo, "oo": sp.oo, "∞": sp.oo}
RESERVED = set(_CONSTS) | {"i", "ans"} | KEYWORDS | {"true", "false"}


class Evaluator:
    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.settings = ctx.settings
        self.warnings: list[str] = []
        self.decimal_input = False
        self.numeric_method: str | None = None            # set by functions that return floating-point approximations
        self.numeric_info: dict[str, Any] = {}
        self.shadow: list[dict[str, Any]] = []
        self.depth = 0
        self.calls = 0

    # ------------------------------------------------------------------------------------------------------------------ driver
    def run(self, node: A.Node) -> Any:
        if A.node_count(node) > self.ctx.max_nodes:
            raise LimitExceeded(f"The expression is too large ({A.node_count(node)} elements; the limit is {self.ctx.max_nodes})")
        return self.ev(node)

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    @property
    def complex_mode(self) -> bool:
        return self.settings.complex

    def check(self, v: Any) -> Any:
        return ops.check_value(v, self.complex_mode)

    # ------------------------------------------------------------------------------------------------------------------ dispatch
    def ev(self, node: A.Node) -> Any:
        try:
            m = getattr(self, "n_" + node.kind)
            return m(node)
        except SciCalError as exc:
            if exc.span is None and getattr(node, "span", (-1, -1)) != (-1, -1):
                exc.span = node.span                     # type: ignore[attr-defined]
            raise
        except RecursionError:
            raise LimitExceeded("The calculation is nested too deeply") from None
        except (ZeroDivisionError,):
            raise UndefinedError("Division by zero") from None
        except OverflowError:
            raise LimitExceeded("The number is too large") from None

    # ------------------------------------------------------------------------------------------------------------------ leaves
    def n_num(self, n: A.Num) -> Any:
        text = n.text
        if "." in text or "e" in text:
            self.decimal_input = True
        if "e" in text:
            exp = int(text.split("e")[1])
            if abs(exp) > 100_000:
                raise LimitExceeded("The exponent is too large")
        return sp.Rational(text)

    def lookup(self, name: str) -> Any | None:
        for layer in reversed(self.shadow):
            if name in layer:
                return layer[name]
        if name in self.ctx.variables:
            return self.ctx.variables[name]
        return None

    def n_var(self, n: A.Var) -> Any:
        name = n.name
        v = self.lookup(name)
        if v is not None:
            return v
        if name in _CONSTS:
            return _CONSTS[name]
        if name == "i":
            if self.complex_mode:
                return sp.I
            self.warn("i is the imaginary unit only in complex mode; here it is an ordinary variable.")
            return sp.Symbol("i")
        if name == "ans":
            if self.ctx.ans is None:
                raise UnknownNameError("There is no previous answer yet", span=n.span)
            return self.ctx.ans
        if name in ("true", "false"):
            return name == "true"
        if canonical(name):
            raise EvaluationError(f"'{name}' is a function; write {name}(…) with its argument in parentheses")
        if len(name) <= 3 and name.isalpha() and name.isascii() and len(name) > 1:
            self.warn(f"'{name}' is read as one variable. Write {'*'.join(name)} to multiply {len(name)} variables.")
        return sp.Symbol(name)

    # ------------------------------------------------------------------------------------------------------------------ operators
    def n_unary(self, n: A.Unary) -> Any:
        v = self.ev(n.arg)
        return self.check(ops.neg(v)) if n.op == "-" else v

    def n_postfix(self, n: A.Postfix) -> Any:
        v = self.ev(n.arg)
        if n.op == "!":
            from .funcs_basic import factorial
            return factorial(self, ops.plain(v, "The factorial"))
        if n.op == "%":
            if isinstance(v, Quantity):
                return Q.div(v, sp.Integer(100))
            return ops.plain(v, "A percentage") / 100
        if n.op == "°":
            if isinstance(v, Quantity):
                raise UnitError("The degree sign cannot be applied to a value that already has a unit")
            return Q.make(ops.plain(v, "An angle in degrees"), parse_unit("deg"))
        raise ParseError(f"Unknown postfix operator {n.op}")

    def n_bin(self, n: A.Binary) -> Any:
        op = n.op
        a = self.ev(n.left)
        b = self.ev(n.right)
        if op == "+":
            r = ops.add(a, b, 1)
        elif op == "-":
            r = ops.add(a, b, -1)
        elif op == "*":
            r = ops.mul(a, b)
        elif op == "/":
            r = ops.div(a, b)
        elif op == "^":
            r = ops.power(a, b, self.complex_mode)
        elif op == "mod":
            x, y = ops.plain(a, "mod"), ops.plain(b, "mod")
            if y == 0:
                raise UndefinedError("mod by zero")
            r = sp.Mod(x, y)
        else:
            raise ParseError(f"Unknown operator {op}")
        return self.check(r)

    # ------------------------------------------------------------------------------------------------------------------ relations
    def n_rel(self, n: A.Rel) -> Any:
        a, b = self.ev(n.left), self.ev(n.right)
        return self.relation(n.op, a, b)

    def relation(self, op: str, a: Any, b: Any) -> Any:
        if isinstance(a, Vec) and isinstance(b, Vec) or (ops.is_matrix(a) and ops.is_matrix(b)):
            if op not in ("=", "!="):
                raise EvaluationError("Vectors and matrices can only be compared with = and !=")
            ia = list(a.items) if isinstance(a, Vec) else list(a)
            ib = list(b.items) if isinstance(b, Vec) else list(b)
            same = len(ia) == len(ib) and (not ops.is_matrix(a) or a.shape == b.shape) and all(ops.compare_numbers(x, y) == 0 for x, y in zip(ia, ib))
            return same if op == "=" else not same
        if isinstance(a, bool) or isinstance(b, bool):
            if op in ("=", "!=") and isinstance(a, bool) and isinstance(b, bool):
                return (a == b) if op == "=" else (a != b)
            raise EvaluationError("A true/false value can only be compared with another true/false value")
        syms = set()
        for v in (a, b):
            if isinstance(v, sp.Basic) and not isinstance(v, sp.MatrixBase):
                syms |= v.free_symbols
            elif not (isinstance(v, Quantity) or ops.is_scalar(v)):
                raise EvaluationError(f"Cannot compare {ops.kind_name(v)}")
        if syms:
            return Equation(a, b, op)
        c = ops.compare_numbers(a, b, self.settings.digits)
        return {"=": c == 0, "!=": c != 0, "<": c < 0, ">": c > 0, "<=": c <= 0, ">=": c >= 0}[op]

    def n_logic(self, n: A.Logic) -> Any:
        vals = [self.ev(a) for a in n.args]
        if all(isinstance(v, bool) for v in vals):
            if n.op == "and":
                return all(vals)
            if n.op == "or":
                return any(vals)
            return not vals[0]
        if all(isinstance(v, (Equation, bool)) for v in vals):
            from .funcs_symbolic import combine_conditions
            return combine_conditions(self, n.op, vals)
        raise EvaluationError(f"'{n.op}' needs true/false conditions", hint="For example: x > 1 and x < 5, or 2 < 3 or 4 < 1.")

    # ------------------------------------------------------------------------------------------------------------------ containers
    def n_vec(self, n: A.Vector) -> Any:
        items = []
        for it in n.items:
            v = self.ev(it)
            if isinstance(v, (Vec, bool)) or ops.is_matrix(v) or isinstance(v, (Equation, Text)):
                raise EvaluationError("A vector can only contain numbers, not vectors, matrices or conditions",
                                      hint="Write a matrix with semicolons: [1, 2; 3, 4].")
            items.append(v)
        if len(items) > 10_000:
            raise LimitExceeded("The vector is too long (limit 10,000 entries)")
        if any(isinstance(x, Quantity) for x in items):
            raise UnitError("Vectors of quantities with units are not supported; keep the unit outside: [1, 2, 3] * 1 m is not allowed, use a table of values instead")
        return Vec(tuple(items))

    def n_mat(self, n: A.Matrix) -> Any:
        rows = []
        for r in n.rows:
            row = []
            for it in r:
                v = self.ev(it)
                if not ops.is_scalar(v):
                    raise EvaluationError("A matrix can only contain numbers or expressions")
                row.append(v)
            rows.append(row)
        if len(rows) > ops.MAX_MATRIX or len(rows[0]) > ops.MAX_MATRIX:
            raise LimitExceeded(f"The matrix is too large (limit {ops.MAX_MATRIX}×{ops.MAX_MATRIX})")
        return sp.ImmutableMatrix(rows)

    # ------------------------------------------------------------------------------------------------------------------ units
    def unit_of(self, u: A.UnitExpr) -> Unit:
        return Unit([(s, Fraction(e)) for s, e in u.factors])

    def n_unit(self, n: A.UnitExpr) -> Any:
        return Quantity(sp.Integer(1), self.unit_of(n))

    def n_qty(self, n: A.Qty) -> Any:
        value = ops.plain(self.ev(n.value), "A quantity")
        try:
            return Q.make(value, self.unit_of(n.unit))
        except SciCalError as exc:
            exc.span = n.span
            raise

    def n_convert(self, n: A.Convert) -> Any:
        v = self.ev(n.expr)
        target = self.unit_of(n.unit)
        if isinstance(v, (Vec,)) or ops.is_matrix(v):
            raise UnitError("Only single values can be converted")
        if not isinstance(v, Quantity):
            if target.dim.is_dimensionless() and not target.is_empty():
                return Q.convert(Quantity(ops.plain(v), Unit(())), target)
            raise DimensionError(f"Cannot convert a plain number into {target.pretty}", hint="Give the value a unit first, for example 5 m -> ft.")
        return convert(v, target)

    # ------------------------------------------------------------------------------------------------------------------ statements
    def n_assign(self, n: A.Assign) -> Any:
        if n.name in RESERVED or canonical(n.name):
            raise EvaluationError(f"'{n.name}' is reserved and cannot be used as a variable name")
        v = self.ev(n.value)
        if isinstance(v, (Equation, Text)):
            raise EvaluationError("Only numbers, quantities, vectors and matrices can be stored in a variable")
        self.ctx.variables[n.name] = v
        return v

    def n_funcdef(self, n: A.FuncDef) -> Any:
        if n.name in RESERVED or canonical(n.name):
            raise EvaluationError(f"'{n.name}' is a built-in name and cannot be redefined")
        if len(n.params) > 8:
            raise EvaluationError("A function can have at most 8 parameters")
        for p in n.params:
            if p in RESERVED:
                raise EvaluationError(f"'{p}' cannot be used as a parameter name")
        self.ctx.functions[n.name] = n
        return Text(f"{n.name}({', '.join(n.params)}) defined", kind="definition")

    # ------------------------------------------------------------------------------------------------------------------ calls
    def n_call(self, n: A.Call) -> Any:
        name = n.name
        if name in self.ctx.functions:
            return self.call_user(n)
        canon = canonical(name)
        if canon is None:
            raise UnknownNameError(f"Unknown function '{name}'", span=n.span,
                                   hint="Check the spelling, or open the function menu for the list of functions.")
        self.calls += 1
        if self.calls > 20_000:
            raise LimitExceeded("Too many function calls in one calculation")
        result = self.apply(canon, n)
        if n.power is not None:
            p = self.ev(n.power)
            result = ops.power(result, p, self.complex_mode)
        return self.check(result)

    def apply(self, canon: str, n: A.Call) -> Any:
        from . import registry
        registry.load_all()
        fn = FUNCTIONS[canon]
        nargs = len(n.args)
        spec = fn.spec
        series = False
        if canon in ("sum", "prod") and nargs == 4:
            spec, series = "LSEE", True
        letters, repeat = spec_letters(spec)
        lo = sum(1 for _, opt in letters if not opt)
        hi = None if repeat else len(letters)
        if canon in ("sum", "prod") and not series:
            lo, hi = 1, None
        if nargs < lo or (hi is not None and nargs > hi):
            need = f"{lo}" if lo == hi else (f"{lo} or more" if hi is None else f"{lo} to {hi}")
            raise ArityError(f"{canon}() takes {need} argument{'s' if need != '1' else ''} but {nargs} {'was' if nargs == 1 else 'were'} given",
                             span=n.span, hint=fn.signature)
        handler = registry.HANDLERS.get(canon)
        if handler is None:
            raise EvaluationError(f"The function {canon}() is not available")
        if registry.RAW.get(canon):
            return handler(self, n, series)
        # evaluate arguments according to their letters
        kinds = [letters[min(i, len(letters) - 1)][0] if (i < len(letters) or repeat) else "E" for i in range(nargs)]
        shadow_names: dict[str, Any] = {}
        for i, k in enumerate(kinds):
            if k == "S":
                a = n.args[i]
                if not isinstance(a, A.Var):
                    raise EvaluationError(f"Argument {i + 1} of {canon}() must be a variable name such as x", span=a.span, hint=fn.signature)   # type: ignore[attr-defined]
                shadow_names[a.name] = sp.Symbol(a.name)
        args: list[Any] = []
        for i, k in enumerate(kinds):
            a = n.args[i]
            if k == "S":
                args.append(shadow_names[a.name])               # type: ignore[attr-defined]
            elif k == "L":
                self.shadow.append(dict(shadow_names))
                try:
                    args.append(self.ev(a))
                finally:
                    self.shadow.pop()
            else:
                args.append(self.ev(a))
        return handler(self, *args)

    def call_user(self, n: A.Call) -> Any:
        f = self.ctx.functions[n.name]
        if len(n.args) != len(f.params):
            raise ArityError(f"{n.name}() takes {len(f.params)} argument{'s' if len(f.params) != 1 else ''} but {len(n.args)} {'was' if len(n.args) == 1 else 'were'} given",
                             span=n.span, hint=f"{n.name}({', '.join(f.params)})")
        if n.power is not None:
            raise EvaluationError("A power on a user-defined function is not supported; write f(x)^2")
        vals = [self.ev(a) for a in n.args]
        self.depth += 1
        if self.depth > self.ctx.max_call_depth:
            raise LimitExceeded(f"{n.name}() calls itself too deeply (limit {self.ctx.max_call_depth})", hint="A recursive definition needs a base case: use if(n <= 1, 1, n*f(n-1)).")
        # the body sees only its parameters, the stored variables and the other functions
        self.shadow.append(dict(zip(f.params, vals)))
        try:
            return self.ev(f.body)
        finally:
            self.shadow.pop()
            self.depth -= 1

    # ------------------------------------------------------------------------------------------------------------------ helpers for handlers
    def angle_in(self, v: Any, what: str = "An angle") -> Any:
        """An angle as radians. A plain number follows the angle mode; a quantity in deg/rad/grad is converted."""
        if isinstance(v, Quantity):
            if v.unit.has_angle and v.unit.dim.is_dimensionless():
                return v.si_magnitude()
            if v.unit.dim.is_dimensionless():
                return v.si_magnitude()
            raise DimensionError(f"{what} must be a plain number or an angle, not {v.unit.pretty}")
        v = ops.plain(v, what)
        mode = self.settings.angle
        return v if mode == "rad" else v * sp.pi / 180 if mode == "deg" else v * sp.pi / 200

    def angle_out(self, rad: Any) -> Any:
        mode = self.settings.angle
        return rad if mode == "rad" else rad * 180 / sp.pi if mode == "deg" else rad * 200 / sp.pi

    def label(self, node: A.Node) -> str:
        return to_text(node)
