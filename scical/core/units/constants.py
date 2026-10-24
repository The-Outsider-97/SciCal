"""Scientific constants with their source and version. Values are exact decimals, never rebuilt from floats."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sympy import Rational

from ...errors import UnknownNameError
from .quantity import Quantity, parse_unit

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "constants.json"


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

    def quantity(self) -> Quantity | Rational:
        return Quantity(self.value, parse_unit(self.unit)) if self.unit else self.value

    def public(self, meta: dict) -> dict:
        return {"key": self.key, "name": self.name, "symbol": self.symbol, "value": str(float(self.value)), "valueExact": str(self.value),
                "uncertainty": None if self.uncertainty is None else str(float(self.uncertainty)), "exact": self.exact, "unit": self.unit,
                "note": self.note, "source": meta["source"], "version": meta["version"]}


@lru_cache(maxsize=1)
def _load() -> tuple[dict, dict[str, Constant]]:
    raw = json.loads(_FILE.read_text(encoding="utf-8"))
    table = {}
    for key, c in raw["constants"].items():
        table[key] = Constant(key, c["name"], c["symbol"], Rational(c["value"]), None if c["uncertainty"] is None else Rational(c["uncertainty"]),
                              bool(c["exact"]), c["unit"], c.get("note", ""))
    return raw["meta"], table


def meta() -> dict:
    return dict(_load()[0])


def constants() -> dict[str, Constant]:
    return dict(_load()[1])


_ALIASES = {"g0": "gn", "g": "gn", "kb": "kB", "k_B": "kB", "n_a": "NA", "na": "NA", "N_A": "NA", "m_e": "me", "m_p": "mp", "m_n": "mn", "m_u": "mu",
            "epsilon0": "eps0", "ε0": "eps0", "mu_0": "mu0", "μ0": "mu0", "ħ": "hbar", "σ": "sigma", "α": "alpha", "a_0": "a0", "mu_B": "muB",
            "speed_of_light": "c", "planck": "h", "avogadro": "NA", "boltzmann": "kB", "faraday": "F", "gas_constant": "R", "gravitation": "G"}


def get(name: str) -> Constant:
    table = _load()[1]
    key = name if name in table else _ALIASES.get(name) or _ALIASES.get(name.lower())
    if key is None or key not in table:
        raise UnknownNameError(f"Unknown constant '{name}'", hint="Known constants: " + ", ".join(sorted(table)))
    return table[key]
