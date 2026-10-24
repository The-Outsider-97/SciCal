"""Solutions, acids and bases, gases, thermochemistry and chemical equilibrium."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import mpmath as mp
import sympy as sp

from ...core.numerical.context import Settings
from ...core.units import Quantity, convert, parse_unit
from ...core.units.constants import get as constant
from ...errors import BadRequest, ChemistryError, DomainError, NotConvergedError, UndefinedError
from .. import common as C
from .formula import molar_mass, parse_formula
from .ops import D

mp.mp.dps = 40
KW_25 = sp.Rational(1, 10 ** 14)


def _mf(x: Any) -> mp.mpf:
    return mp.mpf(str(sp.N(x, 45)))


def _flt(x: mp.mpf) -> sp.Float:
    return sp.Float(mp.nstr(x, 35, min_fixed=-1000, max_fixed=1000), 35)


def _molar_mass_of(params: dict, key: str = "formula") -> sp.Rational | None:
    f = params.get(key)
    if f in (None, ""):
        return None
    m, _, _ = molar_mass(parse_formula(str(f)))
    return D(m)


# ------------------------------------------------------------------------------------------------------------------ solutions
def solution(params: dict, s: Settings) -> dict:
    mode = C.get(params, "mode", "molarity")
    out = C.Out(s)
    if mode == "dilution":
        return _dilution(params, out)
    if mode == "prepare":
        c = C.quantity(params, "concentration", "mol/L", positive=True)
        v = C.quantity(params, "volume", "L", positive=True)
        M = _molar_mass_of(params) or (_ for _ in ()).throw(C.field_error("formula", "'formula' is required"))
        n = c.mag * v.mag
        m = n * M
        out.step("Moles of solute needed", f"n = c × V = {out.num(c.mag)['text']} mol/L × {out.num(v.mag)['text']} L = {out.num(n)['text']} mol")
        out.step("Mass of solute", f"m = n × M = {out.num(n)['text']} mol × {out.num(M)['text']} g/mol")
        return out.done(mode=mode, moles=out.num(n, "mol"), mass=out.num(m, "g"), molarMass=out.num(M, "g/mol"),
                        instructions=f"Dissolve {out.num(m)['text']} g in a little solvent, then make up to {out.num(v.mag)['text']} L.")
    if mode == "molarity":
        n = C.quantity(params, "moles", "mol", required=False, nonneg=True)
        m = C.quantity(params, "mass", "g", required=False, nonneg=True)
        v = C.quantity(params, "volume", "L", required=False, positive=True)
        c = C.quantity(params, "concentration", "mol/L", required=False, nonneg=True)
        M = _molar_mass_of(params)
        if n is None and m is not None:
            if M is None:
                raise C.field_error("formula", "A formula (or molar mass) is needed to convert mass to moles")
            n = Quantity(m.mag / M, parse_unit("mol"))
            out.step("Moles from mass", f"n = m / M = {out.num(m.mag)['text']} g / {out.num(M)['text']} g/mol")
        have = [x is not None for x in (n, v, c)]
        if sum(have) != 2:
            raise BadRequest("Give exactly two of: amount (moles or mass), volume, concentration; the third is calculated")
        if c is None:
            c = Quantity(n.mag / v.mag, parse_unit("mol/L"))
            out.step("Molarity", f"c = n / V = {out.num(n.mag)['text']} / {out.num(v.mag)['text']}")
        elif v is None:
            v = Quantity(n.mag / c.mag, parse_unit("L"))
            out.step("Volume", f"V = n / c = {out.num(n.mag)['text']} / {out.num(c.mag)['text']}")
        else:
            n = Quantity(c.mag * v.mag, parse_unit("mol"))
            out.step("Moles", f"n = c × V")
        data = {"mode": mode, "concentration": out.num(c.mag, "mol/L"), "volume": out.num(v.mag, "L"), "moles": out.num(n.mag, "mol")}
        if M is not None:
            data["mass"] = out.num(n.mag * M, "g")
        return out.done(**data)
    if mode == "mass_percent":
        solute = C.quantity(params, "soluteMass", "g", positive=True)
        total = C.quantity(params, "solutionMass", "g", required=False, positive=True)
        solvent = C.quantity(params, "solventMass", "g", required=False, positive=True)
        if (total is None) == (solvent is None):
            raise BadRequest("Give either the mass of the solution or the mass of the solvent")
        tot = total.mag if total is not None else solute.mag + solvent.mag
        pct = solute.mag / tot * 100
        out.step("Mass percent", f"{out.num(solute.mag)['text']} g ÷ {out.num(tot)['text']} g × 100")
        data = {"mode": mode, "massPercent": out.num(pct, "%"), "solutionMass": out.num(tot, "g"), "ppm": out.num(pct * 10000, "ppm")}
        M = _molar_mass_of(params)
        dens = C.quantity(params, "density", "g/mL", required=False, positive=True)
        if M is not None and dens is not None:
            molarity = pct / 100 * dens.mag * 1000 / M
            data["molarity"] = out.num(molarity, "mol/L")
            out.step("Molarity from mass percent", "c = (w × ρ × 1000) / M")
        return out.done(**data)
    if mode == "molality":
        n = C.quantity(params, "moles", "mol", required=False, nonneg=True)
        m = C.quantity(params, "soluteMass", "g", required=False, nonneg=True)
        M = _molar_mass_of(params)
        kg = C.quantity(params, "solventMass", "kg", positive=True)
        if n is None and m is not None and M is not None:
            n = Quantity(m.mag / M, parse_unit("mol"))
        if n is None:
            raise BadRequest("Give the moles of solute, or its mass and formula")
        mol = n.mag / kg.mag
        out.step("Molality", f"b = n(solute) / m(solvent) = {out.num(n.mag)['text']} mol / {out.num(kg.mag)['text']} kg")
        return out.done(mode=mode, molality=out.num(mol, "mol/kg"))
    if mode == "serial":
        c0 = C.quantity(params, "concentration", "mol/L", positive=True)
        factor = C.number(params, "factor", positive=True, lo=1)
        steps = int(C.number(params, "steps", integer=True, lo=1, hi=30))
        rows, cur = [], c0.mag
        for i in range(1, steps + 1):
            cur = cur / factor
            rows.append({"step": i, "concentration": out.num(cur, "mol/L"), "cumulativeFactor": out.num(factor ** i)})
        out.step("Each step divides the concentration by the dilution factor", f"c_n = c_0 / {out.num(factor)['text']}^n")
        return out.done(mode=mode, series=rows)
    raise BadRequest(f"Unknown solution mode '{mode}'")


def _dilution(params: dict, out: C.Out) -> dict:
    c1 = C.quantity(params, "c1", "mol/L", required=False, positive=True)
    v1 = C.quantity(params, "v1", "L", required=False, positive=True)
    c2 = C.quantity(params, "c2", "mol/L", required=False, positive=True)
    v2 = C.quantity(params, "v2", "L", required=False, positive=True)
    missing = [k for k, v in (("c1", c1), ("v1", v1), ("c2", c2), ("v2", v2)) if v is None]
    if len(missing) != 1:
        raise BadRequest("Give three of c1, v1, c2, v2; the fourth is calculated", details={"field": "c1"})
    m = missing[0]
    if m == "c1":
        r = c2.mag * v2.mag / v1.mag
        unit = "mol/L"
    elif m == "v1":
        r = c2.mag * v2.mag / c1.mag
        unit = "L"
    elif m == "c2":
        r = c1.mag * v1.mag / v2.mag
        unit = "mol/L"
    else:
        r = c1.mag * v1.mag / c2.mag
        unit = "L"
    out.step("C₁V₁ = C₂V₂ (moles of solute are conserved)", f"solve for {m}")
    data: dict[str, Any] = {"mode": "dilution", m: out.num(r, unit)}
    if m in ("v2", "c2") and v1 is not None and c1 is not None:
        v2m = r if m == "v2" else v2.mag
        data["solventToAdd"] = out.num(v2m - v1.mag, "L")
        if v2m < v1.mag:
            out.warn("The final volume is smaller than the starting volume: this is a concentration (evaporation), not a dilution.")
    return out.done(**data)


# ------------------------------------------------------------------------------------------------------------------ acids and bases
def _pk(params: dict, k_key: str, pk_key: str, label: str) -> mp.mpf:
    k = C.number(params, k_key, positive=True, required=False)
    pk = C.number(params, pk_key, required=False)
    if (k is None) == (pk is None):
        raise BadRequest(f"Give either {label} or p{label}", details={"field": k_key})
    return _mf(k) if k is not None else mp.mpf(10) ** (-_mf(pk))


def acid_base(params: dict, s: Settings) -> dict:
    mode = C.get(params, "mode", "weak_acid")
    out = C.Out(s)
    kw = _mf(C.number(params, "kw", default="1e-14", positive=True))
    if kw != mp.mpf(10) ** -14:
        out.warn("A non-default Kw (temperature other than 25 °C) is in use.")
    else:
        out.warn("Calculated at 25 °C with Kw = 1.0×10⁻¹⁴. Activity coefficients are ignored (ideal dilute solution).")
    pkw = -mp.log10(kw)

    def ph_data(h: mp.mpf) -> dict:
        ph = -mp.log10(h)
        oh = kw / h
        return {"pH": out.num(_flt(ph)), "pOH": out.num(_flt(pkw - ph)), "hydronium": out.num(_flt(h), "mol/L"), "hydroxide": out.num(_flt(oh), "mol/L")}

    if mode in ("strong_acid", "strong_base"):
        c = _mf(C.number(params, "concentration", positive=True))
        n = int(C.number(params, "protons" if mode == "strong_acid" else "hydroxides", default=1, integer=True, lo=1, hi=4))
        cc = c * n
        if mode == "strong_acid":
            h = (cc + mp.sqrt(cc * cc + 4 * kw)) / 2
            out.step("Strong acid: complete dissociation", f"[H₃O⁺] = {n} × c, corrected for water autoionisation: [H⁺]² − {n}c[H⁺] − Kw = 0")
        else:
            oh = (cc + mp.sqrt(cc * cc + 4 * kw)) / 2
            h = kw / oh
            out.step("Strong base: complete dissociation", f"[OH⁻] = {n} × c, corrected for water autoionisation")
        return out.done(mode=mode, **ph_data(h))
    if mode in ("weak_acid", "weak_base"):
        c = _mf(C.number(params, "concentration", positive=True))
        if mode == "weak_acid":
            K = _pk(params, "ka", "pka", "Ka")
        else:
            K = _pk(params, "kb", "pkb", "Kb")
        # exact quadratic x^2/(c-x) = K  (water autoionisation neglected unless the acid is extremely weak/dilute)
        x = (-K + mp.sqrt(K * K + 4 * c * K)) / 2
        out.step("Equilibrium expression", f"K = x² / (c − x), with x the amount that reacts: x² + Kx − Kc = 0")
        out.step("Solve the quadratic exactly", f"x = (−K + √(K² + 4Kc)) / 2 = {mp.nstr(x, 6)} mol/L")
        if mode == "weak_acid":
            h = x
            if x < mp.mpf(10) ** -6:
                out.warn("The acid is so weak or dilute that water's own ionisation matters; the result is only approximate.")
                h = (x + mp.sqrt(x * x + 4 * kw)) / 2
        else:
            oh = x
            if x < mp.mpf(10) ** -6:
                out.warn("The base is so weak or dilute that water's own ionisation matters; the result is only approximate.")
                oh = (x + mp.sqrt(x * x + 4 * kw)) / 2
            h = kw / oh
        data = ph_data(h)
        data["percentIonization"] = out.num(_flt(x / c * 100), "%")
        if x / c > mp.mpf("0.05"):
            out.warn("More than 5 % ionises, so the usual shortcut x ≈ √(Kc) would be inaccurate; this result uses the exact quadratic.")
        return out.done(mode=mode, **data)
    if mode == "buffer":
        pka = C.number(params, "pka", required=False)
        ka = C.number(params, "ka", required=False, positive=True)
        if (pka is None) == (ka is None):
            raise BadRequest("Give either Ka or pKa", details={"field": "pka"})
        pk = _mf(pka) if pka is not None else -mp.log10(_mf(ka))
        ha = _mf(C.number(params, "acid", nonneg=True))
        a = _mf(C.number(params, "base", nonneg=True))
        add_acid = _mf(C.number(params, "addStrongAcid", default=0, nonneg=True))
        add_base = _mf(C.number(params, "addStrongBase", default=0, nonneg=True))
        ha2, a2 = ha - add_base + add_acid, a + add_base - add_acid
        if ha2 < 0 or a2 < 0:
            raise DomainError("The added strong acid or base exceeds the buffer capacity: it is no longer a buffer",
                              hint="Treat the leftover strong acid or base as a strong acid/base solution.")
        if ha2 == 0 or a2 == 0:
            raise DomainError("One buffer component is used up, so the Henderson–Hasselbalch equation does not apply")
        ph = pk + mp.log10(a2 / ha2)
        out.step("Henderson–Hasselbalch", f"pH = pKa + log([A⁻]/[HA]) = {mp.nstr(pk, 6)} + log({mp.nstr(a2, 6)}/{mp.nstr(ha2, 6)})")
        data = {"mode": mode, "pH": out.num(_flt(ph)), "pKa": out.num(_flt(pk)), "ratio": out.num(_flt(a2 / ha2))}
        if not (mp.mpf("0.1") <= a2 / ha2 <= 10):
            out.warn("The ratio [A⁻]/[HA] is outside 0.1–10, where the buffer is weak and the Henderson–Hasselbalch estimate is poorer.")
        return out.done(**data)
    if mode == "convert":
        given = {k: params.get(k) for k in ("pH", "pOH", "hydronium", "hydroxide") if params.get(k) not in (None, "")}
        if len(given) != 1:
            raise BadRequest("Give exactly one of pH, pOH, hydronium, hydroxide")
        (k, v), = given.items()
        x = _mf(C.number({"v": v}, "v"))
        if k == "pH":
            h = mp.mpf(10) ** -x
        elif k == "pOH":
            h = mp.mpf(10) ** -(pkw - x)
        elif k == "hydronium":
            if x <= 0:
                raise DomainError("A concentration must be positive")
            h = x
        else:
            if x <= 0:
                raise DomainError("A concentration must be positive")
            h = kw / x
        data = ph_data(h)
        data["character"] = "acidic" if h > mp.sqrt(kw) * (1 + mp.mpf(10) ** -12) else "basic" if h < mp.sqrt(kw) * (1 - mp.mpf(10) ** -12) else "neutral"
        return out.done(mode=mode, **data)
    if mode == "titration":
        return _titration(params, out, kw)
    raise BadRequest(f"Unknown acid/base mode '{mode}'")


def _titration(params: dict, out: C.Out, kw: mp.mpf) -> dict:
    """Titration of a monoprotic acid with a strong base: pH from the exact charge balance, solved numerically."""
    ca = _mf(C.number(params, "acidConcentration", positive=True))
    va = _mf(C.quantity(params, "acidVolume", "mL", positive=True).mag)
    cb = _mf(C.number(params, "baseConcentration", positive=True))
    strong = bool(params.get("strongAcid", False))
    K = None if strong else _pk(params, "ka", "pka", "Ka")
    veq = ca * va / cb
    vmax = veq * 2
    npts = int(C.number(params, "points", default=120, integer=True, lo=20, hi=400))

    def ph_at(vb: mp.mpf) -> mp.mpf:
        tot = va + vb
        na = cb * vb / tot
        ct = ca * va / tot
        def f(h):
            a_minus = ct if strong else ct * K / (K + h)
            return h + na - kw / h - a_minus
        lo, hi = mp.mpf(10) ** -15, mp.mpf(2)
        flo, fhi = f(lo), f(hi)
        for _ in range(200):
            mid = mp.sqrt(lo * hi)
            fm = f(mid)
            if fm > 0:
                hi = mid
            else:
                lo = mid
            if hi / lo < 1 + mp.mpf(10) ** -25:
                break
        return -mp.log10(mp.sqrt(lo * hi))

    pts = []
    vols = [vmax * i / npts for i in range(npts + 1)]
    for e in (veq * f for f in (mp.mpf("0.5") if not strong else mp.mpf("0.5"), mp.mpf(1))):
        vols.append(e)
    vols = sorted(set(vols))
    for v in vols:
        pts.append([float(v), float(ph_at(v))])
    data: dict[str, Any] = {"mode": "titration", "equivalenceVolume": out.num(_flt(veq), "mL"), "pHAtEquivalence": out.num(_flt(ph_at(veq))),
                            "curve": pts, "initialPH": out.num(_flt(ph_at(mp.mpf(0))))}
    if not strong:
        data["halfEquivalence"] = {"volume": out.num(_flt(veq / 2), "mL"), "pH": out.num(_flt(ph_at(veq / 2))), "pKa": out.num(_flt(-mp.log10(K)))}
        out.step("At half-equivalence pH ≈ pKa", "[HA] = [A⁻] there")
    out.step("Equivalence volume", f"V = c(acid) × V(acid) / c(base) = {mp.nstr(veq, 6)} mL")
    out.step("pH along the curve", "solved from the charge balance [H⁺] + [Na⁺] = [OH⁻] + [A⁻] for every volume")
    return out.done(**data)


# ------------------------------------------------------------------------------------------------------------------ gases
R_SI = constant("R").value


def _T(params: dict, key: str, required: bool = True) -> Quantity | None:
    return C.quantity(params, key, "K", required=required, positive=True)


def gas(params: dict, s: Settings) -> dict:
    mode = C.get(params, "mode", "ideal")
    out = C.Out(s)
    if mode == "ideal":
        P = C.quantity(params, "P", "kPa", required=False, positive=True)
        V = C.quantity(params, "V", "L", required=False, positive=True)
        n = C.quantity(params, "n", "mol", required=False, positive=True)
        T = _T(params, "T", required=False)
        have = {"P": P, "V": V, "n": n, "T": T}
        missing = [k for k, v in have.items() if v is None]
        if len(missing) != 1:
            raise BadRequest("Give three of P, V, n, T; the fourth is calculated")
        R = R_SI                 # kPa·L/(mol·K) is the same unit as J/(mol·K), so the number is unchanged
        out.step("Ideal gas law", f"PV = nRT with R = {out.num(R)['text']} kPa·L/(mol·K) (CODATA 2022, exact)")
        m = missing[0]
        if m == "P":
            r, u = n.mag * R * T.mag / V.mag, "kPa"
        elif m == "V":
            r, u = n.mag * R * T.mag / P.mag, "L"
        elif m == "n":
            r, u = P.mag * V.mag / (R * T.mag), "mol"
        else:
            r, u = P.mag * V.mag / (n.mag * R), "K"
        data = {"mode": mode, "solvedFor": m, "result": out.num(r, u)}
        if m == "P":
            data["pressures"] = {"atm": out.num(r / sp.Rational("101.325"), "atm"), "bar": out.num(r / 100, "bar"), "mmHg": out.num(r * sp.Rational(760) / sp.Rational("101.325"), "mmHg")}
        if m == "T":
            data["celsius"] = out.num(r - sp.Rational("273.15"), "°C")
        molar = _molar_mass_of(params)
        if molar is not None and None not in (P, T):
            data["density"] = out.num(P.mag * molar / (R * T.mag), "g/L")
            out.step("Density of the gas", "ρ = PM/(RT)")
        return out.done(**data)
    if mode == "molar_mass":
        m = C.quantity(params, "mass", "g", positive=True)
        P = C.quantity(params, "P", "kPa", positive=True)
        V = C.quantity(params, "V", "L", positive=True)
        T = _T(params, "T")
        R = R_SI
        M = m.mag * R * T.mag / (P.mag * V.mag)
        out.step("From PV = nRT with n = m/M", "M = mRT / (PV)")
        return out.done(mode=mode, molarMass=out.num(M, "g/mol"))
    if mode == "combined":
        vals = {k: C.quantity(params, k, u, required=False, positive=True) for k, u in (("P1", "kPa"), ("V1", "L"), ("T1", "K"), ("P2", "kPa"), ("V2", "L"), ("T2", "K"))}
        missing = [k for k, v in vals.items() if v is None]
        if len(missing) != 1:
            raise BadRequest("Give five of P1, V1, T1, P2, V2, T2; the sixth is calculated")
        mk = missing[0]
        g = {k: (v.mag if v is not None else None) for k, v in vals.items()}
        # P1V1/T1 = P2V2/T2
        if mk == "P1": r = g["P2"] * g["V2"] / g["T2"] * g["T1"] / g["V1"]
        elif mk == "V1": r = g["P2"] * g["V2"] / g["T2"] * g["T1"] / g["P1"]
        elif mk == "T1": r = g["P1"] * g["V1"] * g["T2"] / (g["P2"] * g["V2"])
        elif mk == "P2": r = g["P1"] * g["V1"] / g["T1"] * g["T2"] / g["V2"]
        elif mk == "V2": r = g["P1"] * g["V1"] / g["T1"] * g["T2"] / g["P2"]
        else: r = g["P2"] * g["V2"] * g["T1"] / (g["P1"] * g["V1"])
        out.step("Combined gas law (amount of gas constant)", "P₁V₁/T₁ = P₂V₂/T₂, temperatures in kelvin")
        return out.done(mode=mode, solvedFor=mk, result=out.num(r, {"P": "kPa", "V": "L", "T": "K"}[mk[0]]))
    if mode == "dalton":
        gases = params.get("gases")
        if not isinstance(gases, list) or len(gases) < 2:
            raise BadRequest("Give at least two gases with their amounts (mol)")
        P = C.quantity(params, "totalPressure", "kPa", required=False, positive=True)
        ns = [(str(g.get("name", f"gas {i + 1}")), C.number({"n": g.get("moles")}, "n", positive=True)) for i, g in enumerate(gases)]
        tot = sum(n for _, n in ns)
        rows = []
        for name, n in ns:
            x = n / tot
            row = {"gas": name, "moles": out.num(n, "mol"), "moleFraction": out.num(x)}
            if P is not None:
                row["partialPressure"] = out.num(x * P.mag, "kPa")
            rows.append(row)
        out.step("Mole fractions", "xᵢ = nᵢ / n_total;  Pᵢ = xᵢ P_total")
        return out.done(mode=mode, gases=rows, totalMoles=out.num(tot, "mol"))
    if mode == "graham":
        m1 = _molar_mass_of(params, "formula1") or C.number(params, "M1", positive=True)
        m2 = _molar_mass_of(params, "formula2") or C.number(params, "M2", positive=True)
        ratio = sp.sqrt(m2 / m1)
        out.step("Graham's law", "rate₁ / rate₂ = √(M₂ / M₁)")
        return out.done(mode=mode, rateRatio=out.num(sp.N(ratio, 20)), M1=out.num(m1, "g/mol"), M2=out.num(m2, "g/mol"))
    if mode == "van_der_waals":
        n = C.quantity(params, "n", "mol", positive=True)
        V = C.quantity(params, "V", "L", positive=True)
        T = _T(params, "T")
        a = C.number(params, "a", nonneg=True)
        b = C.number(params, "b", nonneg=True)
        R = R_SI
        P = n.mag * R * T.mag / (V.mag - n.mag * b) - a * n.mag ** 2 / V.mag ** 2
        P_id = n.mag * R * T.mag / V.mag
        if V.mag <= n.mag * b:
            raise DomainError("The volume must exceed nb (the volume the molecules occupy themselves)")
        out.step("van der Waals equation", "(P + a n²/V²)(V − nb) = nRT, a in L²·kPa/mol², b in L/mol")
        return out.done(mode=mode, pressure=out.num(P, "kPa"), idealPressure=out.num(P_id, "kPa"), difference=out.num((P - P_id) / P_id * 100, "%"))
    raise BadRequest(f"Unknown gas mode '{mode}'")


# ------------------------------------------------------------------------------------------------------------------ thermochemistry
def thermo(params: dict, s: Settings) -> dict:
    mode = C.get(params, "mode", "calorimetry")
    out = C.Out(s)
    if mode == "calorimetry":
        m = C.quantity(params, "mass", "g", positive=True)
        c = C.quantity(params, "specificHeat", "J/(g*K)", default="4.184 J/(g*K)", positive=True)
        t1 = C.quantity(params, "T1", "K", required=False)
        t2 = C.quantity(params, "T2", "K", required=False)
        dt = C.quantity(params, "deltaT", "delta_degC", required=False, to="K")
        q = C.quantity(params, "heat", "J", required=False)
        have = [x is not None for x in (q, dt)] + [t1 is not None and t2 is not None]
        if dt is None and t1 is not None and t2 is not None:
            dt = Quantity(t2.mag - t1.mag, parse_unit("K"))
        if q is None and dt is not None:
            res = m.mag * c.mag * dt.mag
            out.step("Heat", f"q = m c ΔT = {out.num(m.mag)['text']} g × {out.num(c.mag)['text']} J/(g·K) × {out.num(dt.mag)['text']} K")
            return out.done(mode=mode, heat=out.num(res, "J"), heatKJ=out.num(res / 1000, "kJ"), sign="absorbed by the sample" if res > 0 else "released by the sample")
        if q is not None and dt is None:
            res = q.mag / (m.mag * c.mag)
            out.step("Temperature change", "ΔT = q / (m c)")
            return out.done(mode=mode, deltaT=out.num(res, "K"))
        raise BadRequest("Give the heat, or the temperature change (or both temperatures), and the mass")
    if mode == "mixing":
        m1, m2 = C.quantity(params, "mass1", "g", positive=True), C.quantity(params, "mass2", "g", positive=True)
        c1 = C.quantity(params, "specificHeat1", "J/(g*K)", default="4.184 J/(g*K)", positive=True)
        c2 = C.quantity(params, "specificHeat2", "J/(g*K)", default="4.184 J/(g*K)", positive=True)
        t1, t2 = C.quantity(params, "T1", "K", positive=True), C.quantity(params, "T2", "K", positive=True)
        tf = (m1.mag * c1.mag * t1.mag + m2.mag * c2.mag * t2.mag) / (m1.mag * c1.mag + m2.mag * c2.mag)
        out.step("Heat lost = heat gained (no losses to the surroundings)", "m₁c₁(T₁ − Tf) = m₂c₂(Tf − T₂)")
        return out.done(mode=mode, finalTemperature=out.num(tf, "K"), finalCelsius=out.num(tf - sp.Rational("273.15"), "°C"))
    if mode == "hess":
        from .balance import balance as bal, parse_equation
        res = bal(C.text(params, "equation"))
        hf = params.get("formationEnthalpies")
        if not isinstance(hf, dict):
            raise C.field_error("formationEnthalpies", "Give ΔHf° (kJ/mol) for every species, e.g. {\"CH4\": \"-74.8\", \"CO2\": \"-393.5\", \"H2O\": \"-285.8\", \"O2\": \"0\"}")
        total = sp.Integer(0)
        rows = []
        for key, sign in (("products", 1), ("reactants", -1)):
            for sp_ in res[key]:
                name = sp_["species"]
                if name not in hf:
                    raise C.field_error("formationEnthalpies", f"ΔHf° of {name} is missing", hint="Elements in their standard state have ΔHf° = 0.")
                v = C.number({"v": hf[name]}, "v")
                total += sign * sp_["coefficient"] * v
                rows.append({"species": name, "coefficient": sp_["coefficient"], "dHf": out.num(v, "kJ/mol"), "side": key})
        out.step("Hess's law", "ΔH° = Σ n ΔHf°(products) − Σ n ΔHf°(reactants)")
        return out.done(mode=mode, balanced=res["balanced"], enthalpy=out.num(total, "kJ"), kind="exothermic" if total < 0 else "endothermic" if total > 0 else "thermoneutral", species=rows,
                        note="Per mole of reaction as written (the balanced equation).")
    if mode == "gibbs":
        dh = C.quantity(params, "deltaH", "kJ/mol", required=True)
        ds = C.quantity(params, "deltaS", "J/(mol*K)", required=True)
        T = _T(params, "T")
        dg = dh.mag - T.mag * ds.mag / 1000
        out.step("Gibbs energy", f"ΔG = ΔH − TΔS = {out.num(dh.mag)['text']} − {out.num(T.mag)['text']} × {out.num(ds.mag / 1000)['text']} kJ/(mol·K)")
        R = R_SI / 1000
        lnK = -dg / (R * T.mag)
        K = sp.exp(sp.N(lnK, 30))
        data = {"mode": mode, "deltaG": out.num(dg, "kJ/mol"), "spontaneous": bool(dg < 0), "equilibriumConstant": out.num(sp.N(K, 15))}
        if ds.mag != 0:
            data["crossoverTemperature"] = out.num(dh.mag * 1000 / ds.mag, "K")
        out.step("Equilibrium constant", "K = exp(−ΔG / RT)")
        return out.done(**data)
    raise BadRequest(f"Unknown thermochemistry mode '{mode}'")


# ------------------------------------------------------------------------------------------------------------------ equilibrium
def equilibrium(params: dict, s: Settings) -> dict:
    """ICE table: all species start at the given concentrations; the reaction runs to equilibrium for the equilibrium constant K."""
    from .balance import parse_equation
    out = C.Out(s)
    left, right = parse_equation(C.text(params, "reaction"))
    K = C.number(params, "K", positive=True)
    init_raw = params.get("initial")
    if not isinstance(init_raw, dict):
        raise C.field_error("initial", "Give the initial concentrations (mol/L) of the species, e.g. {\"N2O4\": \"0.10\"}")
    species = [(sp_.text, (sp_.given_coef or 1), -1) for sp_ in left] + [(sp_.text, (sp_.given_coef or 1), 1) for sp_ in right]
    init = {}
    for name, _, _ in species:
        init[name] = C.number({"v": init_raw.get(name, 0)}, "v", nonneg=True)
    if not any(v > 0 for v in init.values()):
        raise C.field_error("initial", "At least one species needs a positive starting concentration")
    x = sp.Symbol("x")
    conc = {name: init[name] + sign * coef * x for name, coef, sign in species}
    num = sp.Integer(1)
    den = sp.Integer(1)
    for name, coef, sign in species:
        if sign > 0:
            num *= conc[name] ** coef
        else:
            den *= conc[name] ** coef
    Q0 = None
    try:
        q_num = sp.Integer(1)
        q_den = sp.Integer(1)
        for name, coef, sign in species:
            (q_num if sign > 0 else q_den).__class__
        q_num = sp.prod([init[n] ** c for n, c, sg in species if sg > 0])
        q_den = sp.prod([init[n] ** c for n, c, sg in species if sg < 0])
        Q0 = q_num / q_den if q_den != 0 else None
    except Exception:
        Q0 = None
    if Q0 is not None:
        direction = "forward (towards products)" if Q0 < K else "reverse (towards reactants)" if Q0 > K else "none: already at equilibrium"
    else:
        direction = "forward (towards products)" if all(init[n] == 0 for n, c, sg in species if sg > 0) else "reverse (towards reactants)"
    out.step("Reaction quotient vs K", f"Q = {out.num(Q0)['text'] if Q0 is not None else 'undefined (a product is absent)'}, K = {out.num(K)['text']}: shifts {direction}")
    poly = sp.expand(num - K * den)
    out.step("Equilibrium condition", f"Π[products] = K Π[reactants]  →  polynomial in x of degree {sp.degree(poly, x)}")
    roots = sp.Poly(poly, x).nroots(n=30, maxsteps=500) if sp.degree(poly, x) > 0 else []
    valid = []
    for r in roots:
        if abs(sp.im(r)) > sp.Float(10) ** -20:
            continue
        r = sp.re(r)
        if all(sp.N(conc[n].subs(x, r)) >= -sp.Float(10) ** -20 for n, _, _ in species):
            valid.append(r)
    if not valid:
        raise NotConvergedError("No physically meaningful equilibrium was found", hint="Check K and the starting concentrations.")
    if len(valid) > 1:
        # the correct root lies on the side the reaction actually moves
        valid = [r for r in valid if (r >= 0) == (direction.startswith("forward"))] or valid
    xv = valid[0] if direction.startswith("forward") else valid[0]
    rows = []
    for name, coef, sign in species:
        eq = conc[name].subs(x, xv)
        eq = sp.Integer(0) if abs(eq) < sp.Float(10) ** -25 else eq
        rows.append({"species": name, "initial": out.num(init[name], "mol/L"), "change": out.num(sign * coef * xv, "mol/L"), "equilibrium": out.num(eq, "mol/L")})
    out.step("Physically meaningful root", f"x = {out.num(xv)['text']} mol/L (all concentrations stay non-negative)")
    return out.done(table=rows, x=out.num(xv, "mol/L"), K=out.num(K), reactionQuotient=out.num(Q0) if Q0 is not None else None, direction=direction)


OPS = {"solution": solution, "acid_base": acid_base, "gas": gas, "thermo": thermo, "equilibrium": equilibrium}
