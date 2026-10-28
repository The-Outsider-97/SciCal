"""Constants: browse and convert the one constants store (``scical/data/constants.json``, read through ``core.units.constants``).

Nothing is stored here. Financial parameters are not constants and are not in this store: they are the person's own assumptions, kept as preferences.
"""
from __future__ import annotations

from decimal import Decimal, localcontext

from ...core.numerical.context import Settings
from ...core.units import Quantity, convert, parse_unit
from ...core.units import constants as K
from ...errors import SciCalError
from .. import common as C


def _decimal(x, digits: int = 30) -> str:
    """A rational as a decimal string of ``digits`` significant digits (a display of the exact value, not a float conversion)."""
    n, d = int(x.p), int(x.q)
    with localcontext() as ctx:
        ctx.prec = digits
        v = Decimal(n) / Decimal(d)
    s = format(v.normalize(), "e") if v != 0 else "0"
    return s.replace("e+", "e")


def catalogue(params: dict, s: Settings) -> dict:
    """Search the library. ``query`` (any words), ``category`` (one id), or ``keys`` (a list: favourites or recents, returned in that order)."""
    query = C.text(params, "query", required=False, maxlen=80).strip()
    category = C.text(params, "category", required=False, maxlen=40).strip()
    cats = K.categories()
    if category and category not in cats:
        raise C.field_error("category", f"Unknown category '{category}'", hint="Categories: " + ", ".join(cats))
    keys = params.get("keys")
    meta = K.meta()
    if isinstance(keys, list):
        table = K.constants()
        found = [table[k] for k in keys[:200] if isinstance(k, str) and k in table]
    else:
        found = K.search(query, category)
    counts = {cid: 0 for cid in cats}
    for c in K.constants().values():
        counts[c.category] = counts.get(c.category, 0) + 1
    return {"ok": True, "constants": [c.public(meta) for c in found], "count": len(found), "total": sum(counts.values()),
            "categories": [{"id": cid, "title": v["title"], "description": v["description"], "count": counts.get(cid, 0)} for cid, v in cats.items()],
            "editions": meta.get("editions", {}), "meta": {k: meta[k] for k in ("name", "version", "source", "verified_current", "note") if k in meta}}


def convert_constant(params: dict, s: Settings) -> dict:
    """Express one constant in another unit of the same dimension (exact rational arithmetic; a unit of another kind is refused)."""
    key = C.text(params, "key", maxlen=40).strip()
    to = C.text(params, "to", maxlen=60).strip()
    c = K.get(key)
    if not c.unit:
        raise C.field_error("to", f"{c.name} is dimensionless, so it has no unit to convert to")
    try:
        target = parse_unit(to)
    except SciCalError as exc:
        exc.details = {**exc.details, "field": "to"}
        raise
    out = C.Out(s)
    q = convert(Quantity(c.value, parse_unit(c.unit)), target)
    out.step("Convert through SI", f"{parse_unit(c.unit).pretty} → SI → {target.pretty}; the constant is an exact decimal and all unit factors are exact rationals")
    extra = {}
    if c.uncertainty is not None:
        u = convert(Quantity(c.uncertainty, parse_unit(c.unit)), target)
        extra["uncertainty"] = out.num(u.mag, target.pretty)
        extra["uncertaintyDecimal"] = _decimal(u.mag, 4)
        out.step("Uncertainty", "A standard uncertainty scales by the same factor as the value")
    return out.done(key=c.key, name=c.name, symbol=c.symbol, result=out.num(q.mag, target.pretty), decimal=_decimal(q.mag), unit=target.pretty,
                    dimension=c.dimension, exact=c.exact, edition=c.edition, source=c.source, **extra)


OPS = {"catalogue": catalogue, "convert": convert_constant}
__all__ = ["OPS"]
