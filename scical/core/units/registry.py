"""The unit registry: definitions, SI prefixes and the lookup of a symbol such as ``km``, ``mmol`` or ``degC``.

Every scale factor is an exact SymPy rational (or a rational multiple of pi for angles), so ``5 m + 25 cm`` is exactly ``21/4 m``.
Definitions follow the SI Brochure (9th ed., 2019) for SI units and prefixes, and the exact definitions in NIST SP 811 / NIST
Handbook 44 for the customary units (international inch, foot, yard, mile; avoirdupois pound; US liquid gallon; ...). Units that
are defined through a measured constant (the unified atomic mass unit) use the CODATA 2022 value and say so in ``note``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterable

from sympy import Rational, S, pi

from ...errors import UnitError
from .dimension import Dim

L, M, T, I, TH, N, J = (Dim(L=1), Dim(M=1), Dim(T=1), Dim(I=1), Dim(Th=1), Dim(N=1), Dim(J=1))
ONE = Dim()


def R(text: str | int):
    """An exact decimal, e.g. R('0.0254')."""
    return Rational(str(text))


@dataclass(frozen=True)
class UnitDef:
    symbol: str
    name: str
    dim: Dim
    scale: object                 # exact SymPy number: value in the coherent SI unit = value_in_this_unit * scale (+ offset)
    offset: object = 0            # only for absolute temperature scales (degC, degF)
    prefixable: bool = False
    kind: str = "linear"          # linear | affine (absolute temperature scale with an offset) | delta (temperature difference)
    keep: bool = False            # angle and ratio units are never folded away into a bare number
    angle: bool = False
    cyclic: bool = False          # Hz and rpm count cycles, not radians
    category: str = ""
    note: str = ""
    aliases: tuple[str, ...] = ()
    plural: str = ""

    def words(self) -> list[str]:
        out = {self.name.lower()}
        out.add((self.plural or self.name + "s").lower())
        return sorted(out)


PREFIXES: dict[str, tuple[str, object]] = {
    "q": ("quecto", R("1e-30")), "r": ("ronto", R("1e-27")), "y": ("yocto", R("1e-24")), "z": ("zepto", R("1e-21")),
    "a": ("atto", R("1e-18")), "f": ("femto", R("1e-15")), "p": ("pico", R("1e-12")), "n": ("nano", R("1e-9")),
    "µ": ("micro", R("1e-6")), "μ": ("micro", R("1e-6")), "u": ("micro", R("1e-6")), "m": ("milli", R("1e-3")),
    "c": ("centi", R("1e-2")), "d": ("deci", R("1e-1")), "da": ("deca", R(10)), "h": ("hecto", R(100)), "k": ("kilo", R(1000)),
    "M": ("mega", R("1e6")), "G": ("giga", R("1e9")), "T": ("tera", R("1e12")), "P": ("peta", R("1e15")), "E": ("exa", R("1e18")),
    "Z": ("zetta", R("1e21")), "Y": ("yotta", R("1e24")), "R": ("ronna", R("1e27")), "Q": ("quetta", R("1e30")),
}


class UnitRegistry:
    def __init__(self) -> None:
        self.defs: dict[str, UnitDef] = {}
        self.by_word: dict[str, str] = {}
        self.categories: dict[str, list[str]] = {}
        self._build()

    # ------------------------------------------------------------------ registration
    def add(self, d: UnitDef) -> UnitDef:
        for sym in (d.symbol, *d.aliases):
            if sym in self.defs:
                raise RuntimeError(f"duplicate unit symbol {sym}")
            self.defs[sym] = d
        for w in d.words():
            self.by_word.setdefault(w, d.symbol)
        for al in d.aliases:
            if al.isalpha() and len(al) > 2:
                self.by_word.setdefault(al.lower(), d.symbol)
                self.by_word.setdefault(al.lower() + "s", d.symbol)
        if d.category:
            self.categories.setdefault(d.category, []).append(d.symbol)
        return d

    def _lin(self, sym: str, name: str, dim: Dim, scale, **kw) -> UnitDef:
        return self.add(UnitDef(sym, name, dim, scale, **kw))

    def _from(self, sym: str, name: str, parts: list[tuple[str, int]], scale=1, **kw) -> UnitDef:
        """A unit defined as ``scale`` times a product of already registered units."""
        dim, total = ONE, S.One
        for s, e in parts:
            d, pre, _ = self.resolve(s)
            dim = dim * (d.dim ** e)
            total = total * (pre * d.scale) ** e
        return self.add(UnitDef(sym, name, dim, Rational(scale) * total if not hasattr(scale, "free_symbols") else scale * total, **kw))

    # ------------------------------------------------------------------ lookup
    def resolve(self, symbol: str) -> tuple[UnitDef, object, str]:
        """``(definition, prefix scale, prefix)`` for a unit symbol. Exact symbols win over prefix splits (``min`` is a minute)."""
        d = self.defs.get(symbol)
        if d is not None:
            return d, S.One, ""
        for plen in (2, 1):                       # 'da' is the only two-letter prefix
            if len(symbol) > plen and symbol[:plen] in PREFIXES:
                base = self.defs.get(symbol[plen:])
                if base is not None and base.prefixable:
                    return base, PREFIXES[symbol[:plen]][1], symbol[:plen]
        raise UnitError(f"Unknown unit '{symbol}'", hint="Check the spelling; unit symbols are case-sensitive (m = metre, M = molar, mM = millimolar).")

    def is_unit(self, symbol: str) -> bool:
        try:
            self.resolve(symbol)
            return True
        except UnitError:
            return False

    def lookup_word(self, word: str) -> str | None:
        """Map a name such as 'meters', 'litre' or 'kilometres per hour' parts to a symbol (used by the natural-language entry)."""
        w = word.strip().lower()
        if w in self.by_word:
            return self.by_word[w]
        for pname, (pw, _scale) in ((v[0], (v[0], v[1])) for v in PREFIXES.values()):
            if w.startswith(pname):
                rest = w[len(pname):]
                sym = self.by_word.get(rest) or self.by_word.get(rest.replace("metres", "meters"))
                if sym and self.defs[sym].prefixable:
                    psym = next(k for k, v in PREFIXES.items() if v[0] == pname and k not in ("μ", "u"))
                    return psym + sym
        alt = w.replace("metre", "meter").replace("litre", "liter")
        return self.by_word.get(alt)

    def category_of(self, dim: Dim) -> str:
        return dim.name

    # ------------------------------------------------------------------ the table
    def _build(self) -> None:
        a = self._lin
        # ---- SI base units ----------------------------------------------------------------------------------------
        a("m", "metre", L, S.One, prefixable=True, category="length", plural="metres", aliases=("meter",))
        a("g", "gram", M, R("0.001"), prefixable=True, category="mass")          # kg = k + g, scale exactly 1
        a("s", "second", T, S.One, prefixable=True, category="time")
        a("A", "ampere", I, S.One, prefixable=True, category="electric")
        a("K", "kelvin", TH, S.One, prefixable=True, category="temperature")
        a("mol", "mole", N, S.One, prefixable=True, category="amount")
        a("cd", "candela", J, S.One, prefixable=True, category="light")
        # ---- angles and ratios (dimension one, but kept visible) ------------------------------------------------------
        a("rad", "radian", ONE, S.One, prefixable=True, keep=True, angle=True, category="angle")
        a("sr", "steradian", ONE, S.One, prefixable=True, keep=True, category="angle")
        a("deg", "degree", ONE, pi / 180, keep=True, angle=True, category="angle", aliases=("arcdeg",))
        a("grad", "gradian", ONE, pi / 200, keep=True, angle=True, category="angle")
        a("turn", "turn", ONE, 2 * pi, keep=True, angle=True, category="angle", aliases=("rev",))
        a("arcmin", "arcminute", ONE, pi / 10800, keep=True, angle=True, category="angle")
        a("arcsec", "arcsecond", ONE, pi / 648000, keep=True, angle=True, category="angle")
        a("ppm", "part per million", ONE, R("1e-6"), keep=True, category="ratio")
        a("ppb", "part per billion", ONE, R("1e-9"), keep=True, category="ratio")
        # ---- coherent derived SI units ------------------------------------------------------------------------------
        f = self._from
        f("Hz", "hertz", [("s", -1)], prefixable=True, cyclic=True, category="frequency", plural="hertz")
        f("N", "newton", [("kg", 1), ("m", 1), ("s", -2)], prefixable=True, category="force")
        f("Pa", "pascal", [("N", 1), ("m", -2)], prefixable=True, category="pressure")
        f("J", "joule", [("N", 1), ("m", 1)], prefixable=True, category="energy")
        f("W", "watt", [("J", 1), ("s", -1)], prefixable=True, category="power")
        f("C", "coulomb", [("A", 1), ("s", 1)], prefixable=True, category="electric")
        f("V", "volt", [("W", 1), ("A", -1)], prefixable=True, category="electric")
        f("F", "farad", [("C", 1), ("V", -1)], prefixable=True, category="electric")
        f("ohm", "ohm", [("V", 1), ("A", -1)], prefixable=True, category="electric", aliases=("Ω",), plural="ohms")
        f("S", "siemens", [("ohm", -1)], prefixable=True, category="electric", plural="siemens")
        f("Wb", "weber", [("V", 1), ("s", 1)], prefixable=True, category="electric")
        f("T", "tesla", [("Wb", 1), ("m", -2)], prefixable=True, category="electric")
        f("H", "henry", [("Wb", 1), ("A", -1)], prefixable=True, category="electric", plural="henries")
        f("lm", "lumen", [("cd", 1)], prefixable=True, category="light")
        f("lx", "lux", [("lm", 1), ("m", -2)], prefixable=True, category="light", plural="lux")
        f("Bq", "becquerel", [("s", -1)], prefixable=True, category="radiation")
        f("Gy", "gray", [("J", 1), ("kg", -1)], prefixable=True, category="radiation")
        f("Sv", "sievert", [("J", 1), ("kg", -1)], prefixable=True, category="radiation")
        f("kat", "katal", [("mol", 1), ("s", -1)], prefixable=True, category="amount")
        # ---- length -----------------------------------------------------------------------------------------------------
        a("in", "inch", L, R("0.0254"), category="length", plural="inches")
        a("ft", "foot", L, R("0.3048"), category="length", plural="feet")
        a("yd", "yard", L, R("0.9144"), category="length")
        a("mi", "mile", L, R("1609.344"), category="length")
        a("nmi", "nautical mile", L, R(1852), category="length")
        a("mil", "mil (thousandth of an inch)", L, R("0.0000254"), category="length", aliases=("thou",))
        a("angstrom", "angstrom", L, R("1e-10"), category="length", aliases=("Å",))
        a("au", "astronomical unit", L, R(149597870700), category="length")
        a("ly", "light-year", L, R(9460730472580800), category="length")
        a("pc", "parsec", L, 648000 / pi * R(149597870700), category="length")
        # ---- area / volume ------------------------------------------------------------------------------------------------
        a("ha", "hectare", L ** 2, R(10000), category="area")
        a("acre", "acre", L ** 2, R("4046.8564224"), category="area")
        a("barn", "barn", L ** 2, R("1e-28"), prefixable=True, category="area")
        a("L", "litre", L ** 3, R("0.001"), prefixable=True, category="volume", aliases=("l", "liter"), plural="litres")
        f("cc", "cubic centimetre", [("cm", 3)], category="volume")
        a("gal", "US gallon", L ** 3, R("0.003785411784"), category="volume")
        a("qt", "US quart", L ** 3, R("0.003785411784") / 4, category="volume")
        a("pt", "US pint", L ** 3, R("0.003785411784") / 8, category="volume")
        a("cup", "US cup", L ** 3, R("0.003785411784") / 16, category="volume")
        a("floz", "US fluid ounce", L ** 3, R("0.003785411784") / 128, category="volume")
        a("tbsp", "US tablespoon", L ** 3, R("0.003785411784") / 256, category="volume")
        a("tsp", "US teaspoon", L ** 3, R("0.003785411784") / 768, category="volume")
        a("galUK", "imperial gallon", L ** 3, R("0.00454609"), category="volume", aliases=("gal_imp",))
        a("bbl", "oil barrel", L ** 3, R("0.003785411784") * 42, category="volume")
        # ---- mass -----------------------------------------------------------------------------------------------------------
        a("lb", "pound", M, R("0.45359237"), category="mass", plural="pounds", aliases=("lbm",))
        a("oz", "ounce", M, R("0.45359237") / 16, category="mass")
        a("st", "stone", M, R("0.45359237") * 14, category="mass")
        a("ton", "short ton", M, R("0.45359237") * 2000, category="mass")
        a("tonne", "tonne", M, R(1000), category="mass", prefixable=False)
        a("ct", "carat", M, R("0.0002"), category="mass")
        a("u", "unified atomic mass unit", M, R("1.66053906892e-27"), category="mass", aliases=("Da", "dalton"),
          note="Defined through the measured atomic mass constant, CODATA 2022 (1.66053906892(52)e-27 kg).")
        # ---- time -------------------------------------------------------------------------------------------------------------
        a("min", "minute", T, R(60), category="time")
        a("h", "hour", T, R(3600), category="time", aliases=("hr",))
        a("day", "day", T, R(86400), category="time", aliases=("d",))
        a("wk", "week", T, R(604800), category="time", aliases=("week",))
        a("yr", "year (Julian, 365.25 days)", T, R(31557600), category="time", aliases=("year",),
          note="The Julian year of 365.25 days of 86 400 s, as used in astronomy; calendar years differ.")
        # ---- temperature --------------------------------------------------------------------------------------------------------
        a("degC", "degree Celsius", TH, S.One, offset=R("273.15"), kind="affine", category="temperature", aliases=("°C", "celsius"),
          note="Absolute temperature on the Celsius scale (T/K = t/°C + 273.15).")
        a("degF", "degree Fahrenheit", TH, Rational(5, 9), offset=R("459.67") * Rational(5, 9), kind="affine", category="temperature",
          aliases=("°F", "fahrenheit"), note="Absolute temperature on the Fahrenheit scale (T/K = (t/°F + 459.67) x 5/9).")
        a("degR", "degree Rankine", TH, Rational(5, 9), category="temperature", aliases=("°R",))
        a("delta_degC", "Celsius degree (a difference)", TH, S.One, kind="delta", category="temperature", aliases=("Δ°C", "ΔdegC"))
        a("delta_degF", "Fahrenheit degree (a difference)", TH, Rational(5, 9), kind="delta", category="temperature", aliases=("Δ°F", "ΔdegF"))
        # ---- speed ---------------------------------------------------------------------------------------------------------------
        a("kn", "knot", L / T, R(1852) / 3600, category="speed", aliases=("knot",))
        f("mph", "mile per hour", [("mi", 1), ("h", -1)], category="speed")
        f("kph", "kilometre per hour", [("km", 1), ("h", -1)], category="speed", aliases=("kmh",))
        # ---- force / energy / power / pressure ---------------------------------------------------------------------------
        a("dyn", "dyne", M * L / T ** 2, R("1e-5"), category="force")
        a("kgf", "kilogram-force", M * L / T ** 2, R("9.80665"), category="force")
        a("lbf", "pound-force", M * L / T ** 2, R("0.45359237") * R("9.80665"), category="force")
        a("cal", "calorie (thermochemical)", M * L ** 2 / T ** 2, R("4.184"), prefixable=True, category="energy", plural="calories",
          note="Thermochemical calorie, exactly 4.184 J.")
        a("cal_IT", "calorie (International Table)", M * L ** 2 / T ** 2, R("4.1868"), prefixable=True, category="energy")
        a("eV", "electronvolt", M * L ** 2 / T ** 2, R("1.602176634e-19"), prefixable=True, category="energy",
          note="Exactly 1.602176634e-19 J (the elementary charge is exact in the 2019 SI).")
        a("Wh", "watt-hour", M * L ** 2 / T ** 2, R(3600), prefixable=True, category="energy")
        a("erg", "erg", M * L ** 2 / T ** 2, R("1e-7"), category="energy")
        a("BTU", "British thermal unit (IT)", M * L ** 2 / T ** 2, R("1055.05585262"), category="energy", aliases=("Btu",))
        a("hp", "horsepower (mechanical)", M * L ** 2 / T ** 3, R(550) * R("0.3048") * R("0.45359237") * R("9.80665"), category="power",
          note="550 foot-pounds-force per second.")
        a("PS", "metric horsepower", M * L ** 2 / T ** 3, R("735.49875"), category="power", aliases=("hp_metric",))
        a("bar", "bar", M / (L * T ** 2), R(100000), prefixable=True, category="pressure")
        a("atm", "standard atmosphere", M / (L * T ** 2), R(101325), category="pressure")
        a("torr", "torr", M / (L * T ** 2), R(101325) / 760, prefixable=True, category="pressure", aliases=("Torr",))
        a("mmHg", "millimetre of mercury", M / (L * T ** 2), R("133.322387415"), category="pressure",
          note="Conventional value, exactly 133.322387415 Pa.")
        a("psi", "pound-force per square inch", M / (L * T ** 2), R("0.45359237") * R("9.80665") / R("0.0254") ** 2, prefixable=True,
          category="pressure")
        # ---- frequency / concentration / radiation --------------------------------------------------------------------
        a("rpm", "revolution per minute", T ** -1, Rational(1, 60), cyclic=True, category="frequency")
        a("M", "molar (mol/L)", N / L ** 3, R(1000), prefixable=True, category="concentration", aliases=("molar",),
          note="1 M = 1 mol/L = 1000 mol/m^3.")
        a("Ci", "curie", T ** -1, R("3.7e10"), prefixable=True, category="radiation")
        a("Ah", "ampere-hour", T * I, R(3600), prefixable=True, category="electric")


REGISTRY = UnitRegistry()

# The categories the unit pickers offer, in order. Each is a list of unit symbols that are meant to be shown first.
PICKER: dict[str, list[str]] = {
    "length": ["m", "km", "cm", "mm", "µm", "nm", "in", "ft", "yd", "mi", "nmi", "angstrom", "au", "ly"],
    "area": ["m^2", "km^2", "cm^2", "mm^2", "ha", "acre", "ft^2", "in^2", "mi^2"],
    "volume": ["m^3", "L", "mL", "µL", "cm^3", "gal", "qt", "pt", "cup", "floz", "tbsp", "tsp", "galUK", "ft^3", "in^3"],
    "mass": ["kg", "g", "mg", "µg", "tonne", "lb", "oz", "st", "ton", "u"],
    "time": ["s", "ms", "µs", "ns", "min", "h", "day", "wk", "yr"],
    "temperature": ["K", "degC", "degF", "degR"],
    "speed": ["m/s", "km/h", "mph", "kn", "ft/s", "cm/s"],
    "acceleration": ["m/s^2", "cm/s^2", "ft/s^2"],
    "force": ["N", "kN", "mN", "dyn", "kgf", "lbf"],
    "energy": ["J", "kJ", "MJ", "cal", "kcal", "eV", "keV", "Wh", "kWh", "BTU", "erg"],
    "power": ["W", "kW", "MW", "mW", "hp", "PS"],
    "pressure": ["Pa", "kPa", "MPa", "bar", "mbar", "atm", "torr", "mmHg", "psi"],
    "frequency": ["Hz", "kHz", "MHz", "GHz", "rpm"],
    "density": ["kg/m^3", "g/cm^3", "g/mL", "g/L", "mg/mL", "lb/ft^3"],
    "concentration": ["M", "mM", "µM", "nM", "mol/L", "mol/m^3", "g/L", "mg/mL", "ppm"],
}
