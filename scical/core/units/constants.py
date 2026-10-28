"""Scientific constants with their category, source and edition. Values are exact decimals, never rebuilt from floats.

This is the only constants store: ``const(name)`` in expressions, the Measurement "constants" card, the formula library's auto-filled
constants and the Constants page all read ``data/constants.json`` through this module. ``tools/make_constants.py`` regenerates that file.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sympy import Rational

from ...errors import UnknownNameError
from .quantity import Quantity, parse_unit

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "constants.json"

# What a constant is. "exact" and "exact_derived" carry no uncertainty; "nominal" and "convention" are agreed values, not measurements.
KINDS = {
    "exact": "Exact by definition",
    "exact_derived": "Exact consequence of defined constants (not a finite decimal)",
    "mathematical": "Mathematical constant",
    "measured": "Measured; has a standard uncertainty",
    "derived": "Derived from other constants, uncertainty propagated",
    "nominal": "Nominal conversion constant defined by a standards body",
    "convention": "Agreed reference value (convention)",
}

# Native names the expression language already understands, so inserting them needs no const() wrapper.
_NATIVE = {"pi": "pi", "tau": "tau", "euler_e": "e"}


@dataclass(frozen=True)
class Constant:
    key: str
    name: str
    symbol: str
    value: Rational
    uncertainty: Rational | None
    exact: bool
    unit: str
    note: str = ""
    category: str = ""
    kind: str = ""
    description: str = ""
    applications: tuple[str, ...] = ()
    source: str = ""
    edition: str = ""
    sigfigs: int | None = None
    text: str = ""                  # the value exactly as stored (a decimal string)
    uncertainty_text: str | None = None

    def quantity(self) -> Quantity | Rational:
        return Quantity(self.value, parse_unit(self.unit)) if self.unit else self.value

    @property
    def dimension(self) -> str:
        return parse_unit(self.unit).dim.name if self.unit else "dimensionless"

    @property
    def expression(self) -> str:
        """The text that inserts this constant into a SciCal expression."""
        return _NATIVE.get(self.key) or f"const({self.key})"

    def public(self, meta: dict) -> dict:
        return {"key": self.key, "name": self.name, "symbol": self.symbol, "value": str(float(self.value)), "valueExact": self.text or str(self.value),
                "uncertainty": None if self.uncertainty is None else str(float(self.uncertainty)), "uncertaintyText": self.uncertainty_text,
                "exact": self.exact, "unit": self.unit, "note": self.note, "category": self.category, "kind": self.kind, "kindLabel": KINDS.get(self.kind, self.kind),
                "dimension": self.dimension, "description": self.description, "applications": list(self.applications),
                "source": self.source or meta["source"], "edition": self.edition or meta["version"], "sigfigs": self.sigfigs,
                "version": meta["version"], "expression": self.expression}


@lru_cache(maxsize=1)
def _load() -> tuple[dict, dict[str, Constant]]:
    raw = json.loads(_FILE.read_text(encoding="utf-8"))
    table = {}
    for key, c in raw["constants"].items():
        unc = c.get("uncertainty")
        table[key] = Constant(key, c["name"], c["symbol"], Rational(c["value"]), None if unc is None else Rational(unc), bool(c["exact"]), c["unit"],
                              c.get("note", ""), c.get("category", ""), c.get("kind", ""), c.get("description", ""), tuple(c.get("applications", ())),
                              c.get("source", ""), c.get("edition", ""), c.get("sigfigs"), str(c["value"]), None if unc is None else str(unc))
    return raw["meta"], table


def meta() -> dict:
    return dict(_load()[0])


def constants() -> dict[str, Constant]:
    return dict(_load()[1])


def categories() -> dict[str, dict]:
    return dict(_load()[0].get("categories", {}))


_ALIASES = {"g0": "gn", "g": "gn", "kb": "kB", "k_B": "kB", "n_a": "NA", "na": "NA", "N_A": "NA", "m_e": "me", "m_p": "mp", "m_n": "mn", "m_u": "mu",
            "epsilon0": "eps0", "ε0": "eps0", "mu_0": "mu0", "μ0": "mu0", "ħ": "hbar", "σ": "sigma", "α": "alpha", "a_0": "a0", "mu_B": "muB",
            "speed_of_light": "c", "planck": "h", "avogadro": "NA", "boltzmann": "kB", "faraday": "F", "gas_constant": "R", "gravitation": "G",
            "euler": "euler_e", "φ": "phi", "golden_ratio": "phi", "γ": "gammaE", "euler_gamma": "gammaE", "apery": "zeta3", "ζ3": "zeta3",
            "π": "pi", "τ": "tau", "astronomical_unit": "au", "light_year": "ly", "parsec": "pc", "julian_year": "jyear", "standard_gravity": "gn",
            "standard_atmosphere": "atm", "stefan_boltzmann": "sigma", "rydberg": "Rinf", "bohr_radius": "a0", "fine_structure": "alpha"}


def get(name: str) -> Constant:
    table = _load()[1]
    key = name if name in table else _ALIASES.get(name) or _ALIASES.get(name.lower())
    if key is None or key not in table:
        raise UnknownNameError(f"Unknown constant '{name}'", hint="Known constants: " + ", ".join(sorted(table)))
    return table[key]


# ---------------------------------------------------------------------------------------------------------------------------- search
_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _norm(text: str) -> str:
    """Case-, accent-, space- and underscore-insensitive form: 'k_B', 'kB' and 'K B' all become 'kb'."""
    t = unicodedata.normalize("NFKD", text.translate(_SUB)).lower()
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[\s_\-.,'’]+", "", t)


def search(query: str = "", category: str = "") -> list[Constant]:
    """Constants matching ``query`` (any word may match the key, symbol, name, description or an alias), optionally within one category."""
    table = _load()[1]
    words = [_norm(w) for w in query.split() if _norm(w)]
    by_key: dict[str, list[str]] = {}
    for alias, key in _ALIASES.items():
        by_key.setdefault(key, []).append(alias)
    found = []
    for c in table.values():
        if category and c.category != category:
            continue
        hay = [_norm(c.key), _norm(c.symbol), _norm(c.name), _norm(c.description)] + [_norm(a) for a in by_key.get(c.key, [])]
        if all(any(w in h for h in hay) for w in words):
            found.append(c)
    # symbol or key hits first, then name hits, then description-only hits
    q = _norm(query)

    def rank(c: Constant) -> tuple[int, str]:
        if q and q in (_norm(c.key), _norm(c.symbol)):
            return 0, c.name
        if q and q in _norm(c.name):
            return 1, c.name
        return 2, c.name
    return sorted(found, key=rank) if q else found
