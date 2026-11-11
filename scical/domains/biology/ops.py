"""Biology operations exposed by the API."""
from __future__ import annotations

import re

import itertools
import math
from collections import Counter
from fractions import Fraction
from typing import Any

import numpy as np
import sympy as sp

from ...core.numerical.context import Settings
from ...errors import BadRequest, BiologyError, DomainError, NotConvergedError
from .. import common as C
from . import protein as P
from . import sequence as S


def F(x: float) -> sp.Float:
    return sp.Float(x, 15)


def _seq(params: dict, key: str = "sequence") -> tuple[str, str]:
    return S.clean(C.text(params, key), C.get(params, "kind", "auto"), key)


def _preview(text: str, n: int = 120) -> str:
    return text if len(text) <= n else text[:n] + f"… ({len(text)} total)"


# ------------------------------------------------------------------------------------------------------------------ nucleic acids
def sequence_analysis(params: dict, s: Settings) -> dict:
    seq, kind = _seq(params)
    out = C.Out(s)
    gc, n = S.gc_fraction(seq)
    comp = S.composition(seq)
    data: dict[str, Any] = {"kind": kind.upper(), "length": len(seq), "sceneSequence": seq[:80], "sceneTruncated": len(seq) > 80, "composition": [{"base": b, "count": c, "percent": out.num(F(100 * c / len(seq)), "%")} for b, c in comp.items()]}
    if n:
        data["gcContent"] = out.num(F(100 * gc / n), "%")
        out.step("GC content", f"(G + C) / length = {gc} / {n}")
    if "N" in seq:
        out.warn("The sequence contains N (unknown) bases: they are excluded from GC content and the molecular weight is not calculated.")
    other = "rna" if kind == "dna" else "dna"
    data["complement"] = _preview(S.complement(seq, kind))
    data["reverseComplement"] = _preview(S.reverse_complement(seq, kind))
    data["transcript"] = _preview(S.to_dna(seq).replace("T", "U")) if kind == "dna" else None
    if kind == "dna":
        out.step("Transcript", "The mRNA has the same sequence as the coding strand with U in place of T")
    w = S.nucleic_weight(seq, kind)
    if w is not None:
        data["molecularWeight"] = out.num(F(w), "g/mol")
        out.step("Molecular weight (single strand, 5′-phosphate)", "Σ nucleotide monophosphate masses − (n − 1) × H₂O")
    na = C.number(params, "sodium", default="0.05", positive=True)
    tm = S.melting_temperature(seq, float(na))
    if tm["basic"] is not None:
        data["meltingTemperature"] = out.num(F(tm["basic"]), "°C")
        data["meltingMethod"] = tm["method"]
        if tm["salt"] is not None:
            data["meltingTemperatureSalt"] = out.num(F(tm["salt"]), "°C")
        out.warn("Melting temperatures are rough estimates; use a nearest-neighbour calculator for primer design.")
    return out.done(**data)


def translate_op(params: dict, s: Settings) -> dict:
    seq, kind = _seq(params)
    out = C.Out(s)
    frame = int(C.number(params, "frame", default=1, integer=True, lo=1, hi=3)) - 1
    strand = C.get(params, "strand", "+")
    if strand not in ("+", "-"):
        raise C.field_error("strand", "'strand' must be + or -")
    to_stop = bool(params.get("toStop", False))
    work = seq if strand == "+" else S.reverse_complement(seq, kind)
    prot = S.translate(work, to_stop=to_stop, frame=frame)
    codons = [S.to_dna(work)[i:i + 3] for i in range(frame, len(work) - 2, 3)]
    rows = [{"codon": c, "aa": S.CODON_TABLE.get(c, "X")} for c in codons[:len(prot)]]
    leftover = (len(work) - frame) % 3
    if leftover:
        out.warn(f"{leftover} trailing base(s) do not form a complete codon and were ignored.")
    if "N" in seq:
        out.warn("Codons that contain N are shown as X.")
    out.step("Genetic code", "Standard code (NCBI table 1); * marks a stop codon")
    return out.done(protein=_preview(prot, 400), proteinFull=prot if len(prot) <= 5000 else None, length=len(prot), sceneRna=work.replace("T", "U")[:80], codons=rows[:300],
                    startsWithMet=prot.startswith("M"), stopCodons=prot.count("*"))


def orf_op(params: dict, s: Settings) -> dict:
    seq, _ = _seq(params)
    out = C.Out(s)
    min_aa = int(C.number(params, "minLength", default=30, integer=True, lo=1, hi=100000))
    orfs, trunc = S.find_orfs(seq, min_aa, both=bool(params.get("bothStrands", True)))
    if trunc:
        out.warn("Only the 500 longest open reading frames are shown.")
    out.step("Scan", f"ATG … stop in all three frames of both strands, at least {min_aa} amino acids")
    for o in orfs:
        o["protein"] = _preview(o["protein"], 200)
    return out.done(orfs=orfs, count=len(orfs))


def restriction_op(params: dict, s: Settings) -> dict:
    seq, _ = _seq(params)
    out = C.Out(s)
    enz = params.get("enzymes")
    if isinstance(enz, str):
        enz = [e.strip() for e in enz.replace(",", " ").split() if e.strip()]
    res = S.restriction_sites(seq, enz or None, bool(params.get("circular", False)))
    if not enz:
        res = [r for r in res if r["count"]]
    out.warn("Only the listed palindromic or common sites are searched; degenerate sites, Dam/Dcm methylation and star activity are not modelled.")
    out.step("Search", "Exact match of each recognition site on the top strand (all listed sites are palindromic, so one strand suffices)")
    return out.done(length=len(seq), enzymes=res, catalogue=sorted(S.RESTRICTION))


# ------------------------------------------------------------------------------------------------------------------ proteins
def protein_op(params: dict, s: Settings) -> dict:
    seq = P.clean(C.text(params, "sequence"))
    out = C.Out(s)
    ph = C.number(params, "pH", default="7.4")
    mw = P.mass(seq)
    pi = P.isoelectric_point(seq)
    e_ox, e_red = P.extinction(seq)
    data = {"length": len(seq), "molecularWeight": out.num(F(mw), "Da"), "isoelectricPoint": out.num(F(pi)),
            "chargeAtPH": {"pH": out.num(ph), "charge": out.num(F(P.net_charge(seq, float(ph))))},
            "gravy": out.num(F(P.gravy(seq))), "extinction280": {"cystines": e_ox, "reduced": e_red, "unit": "M⁻¹ cm⁻¹"},
            "composition": [{**r, "percent": out.num(F(r["percent"]), "%")} for r in P.composition(seq)]}
    if e_ox:
        data["absorbance01"] = out.num(F(e_ox / mw * 0.1), "AU")
    out.step("Molecular weight", "Σ average residue masses + H₂O")
    out.step("Isoelectric point", "pH at which the net charge is zero, from Henderson–Hasselbalch with the EMBOSS pK set (bisection)")
    out.step("GRAVY", "Mean Kyte–Doolittle hydropathy of all residues; positive = hydrophobic")
    out.warn("The isoelectric point and charge are estimates from a fixed pK table; they ignore the local environment and modifications.")
    if not e_ox and not e_red:
        out.warn("There is no tryptophan, tyrosine or cystine, so the protein hardly absorbs at 280 nm.")
    return out.done(**data)


# ------------------------------------------------------------------------------------------------------------------ genetics
def hardy_weinberg(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    p = C.number(params, "p", required=False, lo=0, hi=1)
    q = C.number(params, "q", required=False, lo=0, hi=1)
    rec = C.number(params, "recessivePhenotype", required=False, lo=0, hi=1)
    counts = params.get("observed")
    if counts:
        try:
            aa, ab, bb = (C.number({"v": counts.get(k)}, "v", nonneg=True) for k in ("AA", "Aa", "aa"))
        except AttributeError:
            raise C.field_error("observed", "Give observed genotype counts as {AA, Aa, aa}")
        n = aa + ab + bb
        if n <= 0:
            raise C.field_error("observed", "At least one individual is needed")
        p = (2 * aa + ab) / (2 * n)
        q = 1 - p
        out.step("Allele frequencies from counts", "p = (2·AA + Aa) / 2N,  q = 1 − p")
    elif rec is not None:
        q = sp.sqrt(rec)
        p = 1 - q
        out.step("From the recessive phenotype", "q² is the frequency of aa, so q = √(q²)")
        out.warn("This assumes the population is in Hardy–Weinberg equilibrium and the recessive allele is fully recessive.")
    elif p is not None and q is None:
        q = 1 - p
    elif q is not None and p is None:
        p = 1 - q
    elif p is not None and q is not None and p + q != 1:
        raise DomainError("p and q must add up to 1", details={"field": "q"})
    if p is None:
        raise BadRequest("Give p, q, the frequency of the recessive phenotype (q²), or observed genotype counts")
    exp = {"AA": p * p, "Aa": 2 * p * q, "aa": q * q}
    out.step("Expected genotype frequencies", "p² + 2pq + q² = 1")
    data: dict[str, Any] = {"p": out.num(p), "q": out.num(q), "expected": {k: out.num(v) for k, v in exp.items()},
                            "carrierFrequency": out.num(2 * p * q)}
    if counts:
        n = aa + ab + bb
        e = {k: v * n for k, v in exp.items()}
        obs = {"AA": aa, "Aa": ab, "aa": bb}
        chi = sum(((obs[k] - e[k]) ** 2 / e[k]) for k in e if e[k] != 0)
        data["expectedCounts"] = {k: out.num(v) for k, v in e.items()}
        data["chiSquare"] = out.num(sp.N(chi, 12))
        data["degreesOfFreedom"] = 1
        pval = float(1 - sp.N(sp.lowergamma(sp.Rational(1, 2), chi / 2) / sp.gamma(sp.Rational(1, 2)), 15)) if chi > 0 else 1.0
        data["pValue"] = out.num(F(pval))
        data["inEquilibrium"] = bool(pval >= 0.05)
        out.step("χ² test (1 degree of freedom)", "χ² = Σ (O − E)² / E; one degree of freedom because two parameters are fixed by the data")
        if any(v < 5 for v in e.values()):
            out.warn("An expected count is below 5, so the χ² approximation is unreliable.")
    return out.done(**data)


def _gametes(genotype: str) -> list[str]:
    loci = [genotype[i:i + 2] for i in range(0, len(genotype), 2)]
    return ["".join(c) for c in itertools.product(*loci)]


def punnett(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    g1, g2 = C.text(params, "parent1", maxlen=8).strip(), C.text(params, "parent2", maxlen=8).strip()
    for k, g in (("parent1", g1), ("parent2", g2)):
        if len(g) % 2 or not (2 <= len(g) <= 6) or not g.isalpha():
            raise C.field_error(k, "Write each parent's genotype as pairs of letters, e.g. Aa or AaBb (up to 3 genes)")
    if len(g1) != len(g2):
        raise BiologyError("Both parents need the same number of genes")
    loci = len(g1) // 2
    for i in range(loci):
        a1, a2 = g1[2 * i:2 * i + 2], g2[2 * i:2 * i + 2]
        letters = {c.lower() for c in a1 + a2}
        if len(letters) != 1:
            raise BiologyError(f"Gene {i + 1} uses different letters in the two parents ('{a1}' and '{a2}')", details={"field": "parent2"},
                               hint="Use the same letter for the same gene: capital for dominant, lower case for recessive.")
    gam1, gam2 = _gametes(g1), _gametes(g2)

    def norm(child: str) -> str:
        pairs = []
        for i in range(loci):
            a, b = sorted(child[2 * i:2 * i + 2], key=lambda c: (c.islower(), c))
            pairs.append(a + b)
        return "".join(pairs)

    grid = [[None] * len(gam2) for _ in gam1]
    geno: Counter = Counter()
    pheno: Counter = Counter()
    for i, a in enumerate(gam1):
        for j, b in enumerate(gam2):
            child = "".join(a[k] + b[k] for k in range(loci))
            child = norm(child)
            grid[i][j] = child
            geno[child] += 1
            traits = tuple("dominant" if any(c.isupper() for c in child[2 * k:2 * k + 2]) else "recessive" for k in range(loci))
            pheno[traits] += 1
    total = len(gam1) * len(gam2)

    def rows(counter, label):
        return [{label: k, "count": v, "fraction": out.num(sp.Rational(v, total)), "percent": out.num(sp.Rational(100 * v, total), "%")}
                for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))]

    pheno_rows = [{"phenotype": ", ".join(f"gene {k + 1} {t}" for k, t in enumerate(key)) if loci > 1 else key[0], "count": v,
                   "fraction": out.num(sp.Rational(v, total)), "percent": out.num(sp.Rational(100 * v, total), "%")}
                  for key, v in sorted(pheno.items(), key=lambda kv: (-kv[1], str(kv[0])))]
    ratio_counts = sorted(pheno.values(), reverse=True)
    g = math.gcd(*ratio_counts) if len(ratio_counts) > 1 else ratio_counts[0]
    out.step("Gametes", f"Parent 1: {', '.join(gam1)}; parent 2: {', '.join(gam2)}")
    out.step("Combine every gamete pair", f"{total} equally likely offspring")
    out.warn("Assumes complete dominance and independent assortment (unlinked genes).")
    return out.done(gametes1=gam1, gametes2=gam2, grid=grid, genotypes=rows(geno, "genotype"), phenotypes=pheno_rows,
                    phenotypeRatio=":".join(str(c // g) for c in ratio_counts), total=total)


# ------------------------------------------------------------------------------------------------------------------ growth and kinetics
def growth(params: dict, s: Settings) -> dict:
    mode = C.get(params, "mode", "exponential")
    out = C.Out(s)
    if mode == "exponential":
        n0 = C.number(params, "n0", positive=True, required=False)
        nt = C.number(params, "nt", positive=True, required=False)
        t = C.quantity(params, "time", "h", required=False, positive=True)
        mu = C.number(params, "rate", required=False)            # per hour
        td = C.quantity(params, "doublingTime", "h", required=False, positive=True)
        if mu is None and td is not None:
            mu = sp.log(2) / td.mag
        if mu is None and None not in (n0, nt, t):
            mu = sp.log(nt / n0) / t.mag
            out.step("Specific growth rate", "μ = ln(N/N₀) / t")
        if mu is None:
            raise BadRequest("Give the doubling time, the growth rate, or N₀, N and the elapsed time")
        data: dict[str, Any] = {"mode": mode, "rate": out.num(sp.N(mu, 15), "1/h")}
        if mu != 0:
            data["doublingTime"] = out.num(sp.N(sp.log(2) / mu, 15), "h")
        if n0 is not None and t is not None and nt is None:
            data["populationAfter"] = out.num(sp.N(n0 * sp.exp(mu * t.mag), 15))
            data["generations"] = out.num(sp.N(mu * t.mag / sp.log(2), 15))
            out.step("Exponential growth", "N = N₀ e^{μt}")
        if mu <= 0:
            out.warn("A zero or negative rate means no growth or decline.")
        out.warn("Exponential growth is only valid while resources are not limiting.")
        return out.done(**data)
    if mode == "logistic":
        n0 = C.number(params, "n0", positive=True)
        k = C.number(params, "capacity", positive=True)
        r = C.number(params, "rate")
        t = C.quantity(params, "time", "h", positive=False, nonneg=True)
        nt = k / (1 + (k - n0) / n0 * sp.exp(-r * t.mag))
        out.step("Logistic growth", "N(t) = K / (1 + ((K − N₀)/N₀) e^{−rt})")
        data = {"mode": mode, "population": out.num(sp.N(nt, 15)), "fractionOfCapacity": out.num(sp.N(nt / k, 15))}
        if r > 0 and 0 < n0 < k:
            data["inflectionTime"] = out.num(sp.N(sp.log((k - n0) / n0) / r, 15), "h")
            data["maximumGrowthRate"] = out.num(sp.N(r * k / 4, 15), "N/h")
        if n0 > k:
            out.warn("The starting population exceeds the carrying capacity, so it declines towards K.")
        return out.done(**data)
    raise BadRequest(f"Unknown growth mode '{mode}'")


def _fit_mm(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float, float, float, float]:
    # starting values from the Hanes–Woolf linearisation (S/v = S/Vmax + Km/Vmax)
    A = np.vstack([xs, np.ones_like(xs)]).T
    slope, icpt = np.linalg.lstsq(A, xs / ys, rcond=None)[0]
    vmax = 1 / slope if slope > 0 else float(ys.max() * 1.2)
    km = max(icpt * vmax, 1e-12)
    beta = np.array([vmax, km])
    for _ in range(200):
        v, k = beta
        f = v * xs / (k + xs)
        r = ys - f
        J = np.vstack([xs / (k + xs), -v * xs / (k + xs) ** 2]).T
        try:
            step = np.linalg.solve(J.T @ J, J.T @ r)
        except np.linalg.LinAlgError:
            break
        lam = 1.0
        base = float(r @ r)
        while lam > 1e-6:
            nb = beta + lam * step
            if nb[0] > 0 and nb[1] > 0 and float(((ys - nb[0] * xs / (nb[1] + xs)) ** 2).sum()) <= base:
                beta = nb
                break
            lam /= 2
        else:
            break
        if np.abs(lam * step).max() < 1e-12 * max(1.0, np.abs(beta).max()):
            break
    v, k = beta
    res = ys - v * xs / (k + xs)
    sse = float(res @ res)
    n = len(xs)
    J = np.vstack([xs / (k + xs), -v * xs / (k + xs) ** 2]).T
    se = (None, None)
    if n > 2:
        try:
            cov = np.linalg.inv(J.T @ J) * sse / (n - 2)
            se = tuple(float(math.sqrt(max(cov[i, i], 0))) for i in range(2))
        except np.linalg.LinAlgError:
            pass
    sst = float(((ys - ys.mean()) ** 2).sum())
    r2 = 1 - sse / sst if sst > 0 else float("nan")
    return float(v), float(k), r2, se[0], se[1]


def michaelis_menten(params: dict, s: Settings) -> dict:
    out = C.Out(s)
    mode = C.get(params, "mode", "velocity")
    if mode == "velocity":
        vmax = C.number(params, "vmax", positive=True)
        km = C.number(params, "km", positive=True)
        sub = C.number(params, "substrate", positive=True)
        inh = C.get(params, "inhibitor", "none")
        factor_a = sp.Integer(1)
        factor_b = sp.Integer(1)
        if inh != "none":
            ki = C.number(params, "ki", positive=True)
            i = C.number(params, "inhibitorConcentration", nonneg=True)
            alpha = 1 + i / ki
            if inh == "competitive":
                factor_a = alpha
            elif inh == "uncompetitive":
                factor_b = alpha
            elif inh == "noncompetitive":
                factor_b = alpha
            else:
                raise C.field_error("inhibitor", "Inhibitor type must be none, competitive, uncompetitive or noncompetitive")
        vm = vmax / factor_b if inh in ("uncompetitive", "noncompetitive") else vmax
        kmapp = km * factor_a if inh == "competitive" else km / factor_b if inh == "uncompetitive" else km
        v = vm * sub / (kmapp + sub)
        out.step("Michaelis–Menten equation", "v = Vmax [S] / (Km + [S])" + ("" if inh == "none" else f" with {inh} inhibition: apparent Vmax and Km are changed"))
        return out.done(mode=mode, velocity=out.num(sp.N(v, 15)), fractionOfVmax=out.num(sp.N(v / vmax, 15)), apparentVmax=out.num(sp.N(vm, 15)), apparentKm=out.num(sp.N(kmapp, 15)))
    if mode == "fit":
        pts = params.get("data")
        if not isinstance(pts, list) or len(pts) < 3:
            raise BadRequest("Give at least three [S], v data points", details={"field": "data"})
        if len(pts) > 5000:
            raise BadRequest("Too many data points", details={"field": "data"})
        try:
            xs = np.array([float(C.number({"v": p[0]}, "v", positive=True)) for p in pts])
            ys = np.array([float(C.number({"v": p[1]}, "v", positive=True)) for p in pts])
        except (TypeError, IndexError, KeyError):
            raise BadRequest("Each data point must be a pair [substrate, velocity]", details={"field": "data"})
        v, k, r2, sev, sek = _fit_mm(xs, ys)
        if not (np.isfinite(v) and np.isfinite(k)):
            raise NotConvergedError("The fit did not converge", hint="Check that the data show saturation.")
        out.step("Nonlinear least squares", "Gauss–Newton fit of v = Vmax[S]/(Km + [S]), started from the Hanes–Woolf line")
        if xs.max() < k:
            out.warn("The highest substrate concentration is below the fitted Km: Vmax is extrapolated and uncertain.")
        # Lineweaver–Burk, for comparison
        A = np.vstack([1 / xs, np.ones_like(xs)]).T
        sl, ic = np.linalg.lstsq(A, 1 / ys, rcond=None)[0]
        out.warn("Lineweaver–Burk is shown for reference only; it over-weights the lowest concentrations. Use the nonlinear fit.")
        return out.done(mode=mode, vmax=out.num(F(v)), km=out.num(F(k)), vmaxStdError=None if sev is None else out.num(F(sev)),
                        kmStdError=None if sek is None else out.num(F(sek)), rSquared=out.num(F(r2)),
                        lineweaverBurk={"vmax": out.num(F(1 / ic)) if ic > 0 else None, "km": out.num(F(sl / ic)) if ic > 0 else None},
                        curve=[[float(x), float(v * x / (k + x))] for x in np.linspace(0, xs.max() * 1.1, 80)])
    raise BadRequest(f"Unknown mode '{mode}'")


def lab_dilution(params: dict, s: Settings) -> dict:
    mode = C.get(params, "mode", "cfu")
    out = C.Out(s)
    if mode == "cfu":
        colonies = C.number(params, "colonies", nonneg=True)
        dil_exp = C.number(params, "dilution", positive=True)           # as a factor: 1e6 (i.e. 10^-6)
        vol = C.quantity(params, "volumePlated", "mL", positive=True)
        cfu = colonies * dil_exp / vol.mag
        out.step("Viable count", "CFU/mL = colonies × dilution factor / volume plated")
        if colonies < 30:
            out.warn("Fewer than 30 colonies: statistically unreliable (the usual countable range is 30–300).")
        elif colonies > 300:
            out.warn("More than 300 colonies: too crowded to count reliably; use a higher dilution.")
        return out.done(mode=mode, cfuPerMl=out.num(sp.N(cfu, 15), "CFU/mL"))
    if mode == "od":
        od = C.number(params, "od", nonneg=True)
        factor = C.number(params, "conversion", default="8e8", positive=True)
        dil = C.number(params, "dilution", default=1, positive=True)
        cells = od * dil * factor
        out.step("Cell density", "cells/mL = OD × dilution × conversion factor")
        out.warn("The OD-to-cells factor depends on organism, instrument and path length; 8×10⁸ cells/mL per OD600 is a common E. coli approximation. Calibrate your own.")
        if od > 1:
            out.warn("OD above ~1 is outside the linear range of most spectrophotometers; dilute the sample and re-measure.")
        return out.done(mode=mode, cellsPerMl=out.num(sp.N(cells, 15), "cells/mL"))
    if mode == "serial":
        factor = C.number(params, "factor", positive=True, lo=1)
        steps = int(C.number(params, "steps", integer=True, lo=1, hi=30))
        vol = C.quantity(params, "transferVolume", "mL", positive=True)
        total = C.quantity(params, "finalVolume", "mL", positive=True)
        if vol.mag > total.mag:
            raise DomainError("The transfer volume cannot exceed the final volume per tube")
        step_factor = total.mag / vol.mag
        out.step("Dilution per tube", "transfer volume ÷ final volume")
        rows = [{"tube": i, "dilution": out.num(step_factor ** i), "exponent": f"10^-{i}" if step_factor == 10 else None} for i in range(1, steps + 1)]
        return out.done(mode=mode, perTubeFactor=out.num(step_factor), diluentPerTube=out.num(total.mag - vol.mag, "mL"), tubes=rows)
    raise BadRequest(f"Unknown mode '{mode}'")


def genetic_code(params: dict, s: Settings) -> dict:
    rows = [{"codon": c, "aa": a, "name": S.AA_NAMES.get(a, "Stop")} for c, a in S.CODON_TABLE.items()]
    return {"ok": True, "code": rows, "table": "Standard genetic code (NCBI translation table 1)", "enzymes": {k: {"site": v[0], "cut": v[1]} for k, v in S.RESTRICTION.items()}}



# ------------------------------------------------------------------------------------------------------------------ sequence-driven teaching simulations
def transcription_op(params: dict, s: Settings) -> dict:
    """Transcribe an explicitly oriented DNA strand; orientation is never silently reversed."""
    dna, _ = S.clean(C.text(params, "sequence"), "dna")
    if len(dna) > 900:
        raise C.field_error("sequence", "The interactive transcription limit is 900 bases")
    strand = C.get(params, "strand", "coding")
    if strand not in ("coding", "template"):
        raise C.field_error("strand", "Choose coding or template")
    # The coding sequence is 5'→3'; its complementary template is aligned 3'→5'.
    # Input named template must be supplied 3'→5' in the direction of polymerase travel.
    coding = dna if strand == "coding" else S.complement(dna, "dna")
    template = S.complement(coding, "dna")
    mrna = coding.replace("T", "U")
    out = C.Out(s)
    if "N" in dna:
        out.warn("Unknown N bases remain N; their identities cannot be inferred.")
    out.step("Orientation", "Coding: 5′→3′; template: 3′→5′; mRNA is synthesized 5′→3′")
    out.step("Base pairing", "DNA template A→U, T→A, C→G, G→C")
    out.warn("Sequence-level educational model: promoter binding, kinetics and termination signals are not predicted.")
    return out.done(coding=coding, template=template, mrna=mrna, transcriptLength=len(mrna),
                    inputStrand=strand, orientation={"coding": "5to3", "template": "3to5", "mrna": "5to3"},
                    model="sequence-level, schematic")


def protein_synthesis_op(params: dict, s: Settings) -> dict:
    """Translation from AUG until the first in-frame stop, with an explicit incomplete result otherwise."""
    seq, kind = _seq(params)
    if len(seq) > 900:
        raise C.field_error("sequence", "The interactive translation limit is 900 bases")
    mrna = seq.replace("T", "U")
    start_one = int(C.number(params, "start", default=0, integer=True, lo=0, hi=900))
    if start_one:
        start = start_one - 1
        if mrna[start:start + 3] != "AUG":
            raise C.field_error("start", "The selected start position must point to AUG")
    else:
        start = mrna.find("AUG")
        if start < 0:
            raise BiologyError("No AUG initiation codon found",
                               hint="Supply a sequence containing AUG, or use Translate to examine arbitrary reading frames.")
    out = C.Out(s)
    translated: list[dict[str, Any]] = []
    protein: list[str] = []
    has_stop = False
    for pos in range(start, len(mrna) - 2, 3):
        codon = mrna[pos:pos + 3]
        aa = S.CODON_TABLE.get(codon.replace("U", "T"), "X")
        # Anticodons are reported aligned 3′→5′ opposite the 5′→3′ mRNA.
        anticodon = None if aa == "*" else S.complement(codon, "rna")
        translated.append({"index": len(translated) + 1, "position": pos + 1,
                           "codon": codon, "anticodon": anticodon,
                           "aa": aa, "aminoAcid": S.AA_NAMES.get(aa, "Stop" if aa == "*" else "Unknown")})
        if aa == "*":
            has_stop = True
            break
        protein.append(aa)
    if not has_stop:
        out.warn("No in-frame stop codon occurs after AUG; the displayed peptide is incomplete.")
    if "X" in protein:
        out.warn("At least one codon contains an unknown base (N); its amino acid is undetermined.")
    if (len(mrna) - start) % 3:
        out.warn("Trailing nucleotides not forming a full codon were not translated.")
    out.step("Initiation", f"AUG at 1-based position {start + 1} (standard genetic code)")
    out.step("Termination", "Stop codons use release factors, not tRNA" if has_stop else "Not reached")
    return out.done(mrna=mrna, start=start + 1, frame=start % 3 + 1, codons=translated,
                    protein="".join(protein), length=len(protein), complete=has_stop,
                    geneticCode="NCBI 1 (standard)", model="sequence-level, schematic")


def mutation_op(params: dict, s: Settings) -> dict:
    """Compare a single edit in an explicitly selected reading frame (not a clinical prediction)."""
    sequence, kind = _seq(params)
    if len(sequence) > 900:
        raise C.field_error("sequence", "The interactive mutation limit is 900 bases")
    mode = C.get(params, "mode", "substitute")
    if mode not in ("substitute", "insert", "delete"):
        raise C.field_error("mode", "Mutation must be substitute, insert or delete")
    pos = int(C.number(params, "position", integer=True, lo=1, hi=len(sequence) + (1 if mode == "insert" else 0)))
    frame = int(C.number(params, "frame", integer=True, default=1, lo=1, hi=3)) - 1
    letter = str(C.get(params, "base", "")).strip().upper()
    if mode != "delete" and (len(letter) != 1 or letter not in ("ACGU" if kind == "rna" else "ACGT")):
        raise C.field_error("base", "Choose one valid DNA or RNA nucleotide")
    if mode == "substitute" and sequence[pos - 1] == letter:
        raise C.field_error("base", "The replacement nucleotide must differ from the original")
    mutated = (sequence[:pos - 1] + ("" if mode == "delete" else letter) +
               sequence[pos:] if mode in ("delete", "substitute") else sequence[:pos - 1] + letter + sequence[pos - 1:])
    before = S.translate(sequence, to_stop=False, frame=frame)
    after = S.translate(mutated, to_stop=False, frame=frame)
    old_triplet = S.to_dna(sequence)[frame + ((pos - 1 - frame) // 3) * 3:][:3] if pos - 1 >= frame else ""
    new_triplet = S.to_dna(mutated)[frame + ((pos - 1 - frame) // 3) * 3:][:3] if pos - 1 >= frame else ""
    old_aa = S.CODON_TABLE.get(old_triplet, "X") if len(old_triplet) == 3 else None
    new_aa = S.CODON_TABLE.get(new_triplet, "X") if len(new_triplet) == 3 else None
    if mode in ("insert", "delete"):
        classification = "frameshift"
    elif old_aa == "X" or new_aa == "X" or not old_aa or not new_aa:
        classification = "indeterminate"
    elif old_aa == new_aa:
        classification = "synonymous"
    elif new_aa == "*":
        classification = "nonsense"
    elif old_aa == "*":
        classification = "stop-loss"
    else:
        classification = "missense"
    out = C.Out(s)
    if "N" in sequence:
        out.warn("Unknown N bases can prevent a unique interpretation of the amino-acid changes.")
    if mode == "substitute" and (old_triplet == "ATG" or new_triplet == "ATG"):
        out.warn("A start codon has changed; this frame-only comparison cannot establish biological initiation.")
    out.warn("A sequence edit alone does not establish phenotype, pathogenicity, protein folding or biological function.")
    out.step("Comparison", "Frame " + str(frame + 1) + " of the supplied 5′→3′ strand (standard genetic code)")
    out.step("Mutation", f"{mode} at 1-based nucleotide position {pos}: {classification}")
    return out.done(original=sequence, mutated=mutated, kind=kind.upper(), mode=mode, position=pos,
                    frame=frame + 1, base=letter if mode != "delete" else None,
                    originalCodon=old_triplet.replace("T", "U"), mutantCodon=new_triplet.replace("T", "U"),
                    originalAA=old_aa, mutantAA=new_aa, originalProtein=before, mutantProtein=after,
                    classification=classification, model="reading-frame comparison, not phenotype prediction")



def rna_processing_op(params: dict, s: Settings) -> dict:
    """Educational eukaryotic splicing with explicitly supplied exon intervals."""
    pre_rna, _ = S.clean(C.text(params, "sequence"), "rna")
    if len(pre_rna) > 2000:
        raise C.field_error("sequence", "RNA processing is limited to 2000 nucleotides")
    spec = C.text(params, "exons", maxlen=500)
    ranges: list[tuple[int, int]] = []
    for token in spec.split(","):
        match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", token)
        if not match:
            raise C.field_error("exons", "Specify 1-based inclusive exon intervals such as 1-6,10-15")
        a, b = map(int, match.groups())
        if a < 1 or b < a or b > len(pre_rna):
            raise C.field_error("exons", "Exon boundaries must be ordered and within the RNA sequence")
        ranges.append((a, b))
    if len(ranges) > 50:
        raise C.field_error("exons", "At most 50 explicitly selected exons are supported")
    ranges.sort()
    if any(x[0] <= prev[1] for prev, x in zip(ranges, ranges[1:])):
        raise C.field_error("exons", "Exons must not overlap")
    mature = "".join(pre_rna[a - 1:b] for a, b in ranges)
    introns = []
    previous = 1
    for a, b in ranges:
        if a > previous:
            introns.append({"start": previous, "end": a - 1, "length": a - previous})
        previous = b + 1
    if previous <= len(pre_rna):
        introns.append({"start": previous, "end": len(pre_rna), "length": len(pre_rna) - previous + 1})
    out = C.Out(s)
    out.step("Exon concatenation", ", ".join(f"{a}-{b}" for a, b in ranges))
    out.step("Spliced transcript", f"{len(pre_rna)} → {len(mature)} nucleotides")
    out.warn("User-supplied exon positions define this model; SciCal did not predict splice sites, promoters, the 5′ cap or a poly(A) tail.")
    return out.done(preMrna=pre_rna, matureMrna=mature,
                    exons=[{"start": a, "end": b, "length": b - a + 1} for a, b in ranges],
                    excludedRegions=introns, lengthBefore=len(pre_rna), lengthAfter=len(mature),
                    model="explicit-interval eukaryotic RNA processing")


OPS = {"sequence": sequence_analysis, "translate": translate_op, "orfs": orf_op, "restriction": restriction_op, "protein": protein_op,
       "hardy_weinberg": hardy_weinberg, "punnett": punnett, "growth": growth, "michaelis_menten": michaelis_menten, "lab_dilution": lab_dilution,
       "genetic_code": genetic_code, "transcription": transcription_op, "protein_synthesis": protein_synthesis_op, "mutation": mutation_op, "rna_processing": rna_processing_op}
