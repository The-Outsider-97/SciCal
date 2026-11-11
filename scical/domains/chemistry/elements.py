"""The periodic table (data/elements.json)."""
from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from ...errors import ChemistryError, NotFound

_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "elements.json"


@lru_cache(maxsize=1)
def _load() -> dict:
    raw = json.loads(_FILE.read_text(encoding="utf-8"))
    by_symbol = {e["symbol"]: e for e in raw["elements"]}
    by_name = {e["name"].lower(): e for e in raw["elements"]}
    by_name.update({"aluminum": by_symbol["Al"], "cesium": by_symbol["Cs"], "sulphur": by_symbol["S"]})
    return {"meta": raw["meta"], "list": raw["elements"], "sym": by_symbol, "name": by_name, "reference_mass_numbers": raw.get("referenceMassNumbers")}


def all_elements() -> list[dict]:
    return list(_load()["list"])


def meta() -> dict:
    return dict(_load()["meta"])


def symbols() -> set[str]:
    return set(_load()["sym"])


def element(key: str | int) -> dict:
    d = _load()
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        z = int(key)
        if not 1 <= z <= 118:
            raise NotFound(f"There is no element with atomic number {z}")
        return d["list"][z - 1]
    k = str(key).strip()
    if k in d["sym"]:
        return d["sym"][k]
    if k.lower() in d["name"]:
        return d["name"][k.lower()]
    cap = k[:1].upper() + k[1:].lower()
    if cap in d["sym"]:
        return d["sym"][cap]
    raise ChemistryError(f"Unknown element '{key}'", hint="Use the symbol (Fe) or name (iron).")



def reference_isotope_mass_number(z: int) -> int:
    """Return the explicitly provided educational isotope's A (not an atomic mass).

    Data provenance: user-supplied representative mass-number table, 2026-11-11.
    It is not AME-validated; never silently use it to calculate atomic masses or
    imply natural abundance, isotope stability, or individual isotope certainty.
    """
    values = _load().get("reference_mass_numbers")
    if not isinstance(values, list) or len(values) != 118 or not all(
        isinstance(a, int) and not isinstance(a, bool) and a >= index + 1
        and (index == 0 or a > index + 1)
        for index, a in enumerate(values)
    ):
        raise ChemistryError("The educational reference isotope mass-number table is incomplete")
    if not 1 <= z <= 118:
        raise NotFound(f"There is no element with atomic number {z}")
    return values[z - 1]


def atomic_weight(symbol: str) -> tuple[Decimal, Decimal | None, str]:
    """(weight, uncertainty or None, kind). For elements without a standard weight the mass number in brackets is used."""
    e = element(symbol)
    w = e["weight"]
    if w.startswith("["):
        return Decimal(w[1:-1]), None, "none"
    dec = Decimal(w)
    u = None
    if e["uncertainty"] is not None:
        decimals = -dec.as_tuple().exponent
        u = Decimal(e["uncertainty"]).scaleb(-decimals)
    return dec, u, e["weightKind"]


def search(q: str) -> list[dict]:
    q = q.strip().lower()
    if not q:
        return all_elements()
    out = []
    for e in _load()["list"]:
        if q in e["name"].lower() or q == e["symbol"].lower() or q == str(e["z"]) or q in e["category"]:
            out.append(e)
    return out
