"""Protein analysis: mass, isoelectric point, hydropathy, extinction coefficient."""
from __future__ import annotations

import re

from ...errors import BiologyError, BadRequest
from .sequence import AA_NAMES, MAX_SEQ

# Average residue masses (Da), as used by ExPASy ProtParam
RESIDUE = {"G": 57.0519, "A": 71.0788, "S": 87.0782, "P": 97.1167, "V": 99.1326, "T": 101.1051, "C": 103.1388, "L": 113.1594, "I": 113.1594,
           "N": 114.1038, "D": 115.0886, "Q": 128.1307, "K": 128.1741, "E": 129.1155, "M": 131.1926, "H": 137.1411, "F": 147.1766,
           "R": 156.1875, "Y": 163.1760, "W": 186.2132}
WATER = 18.01524
KYTE_DOOLITTLE = {"A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8,
                  "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2}
# side-chain and terminal pK values (EMBOSS set)
PK = {"Nterm": 8.6, "Cterm": 3.6, "K": 10.8, "R": 12.5, "H": 6.5, "D": 3.9, "E": 4.1, "C": 8.5, "Y": 10.1}
POSITIVE = ("K", "R", "H")
NEGATIVE = ("D", "E", "C", "Y")


def clean(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BadRequest("'sequence' is required", details={"field": "sequence"})
    lines = raw.splitlines()
    if lines and lines[0].lstrip().startswith(">"):
        body = []
        for ln in lines[1:]:
            if ln.lstrip().startswith(">"):
                break
            body.append(ln)
        lines = body
    seq = re.sub(r"[\s\d\-\*]", "", "".join(lines)).upper()
    if not seq:
        raise BadRequest("'sequence' contains no residues", details={"field": "sequence"})
    if len(seq) > MAX_SEQ:
        raise BadRequest("The protein is too long", details={"field": "sequence"})
    bad = sorted(set(seq) - set(RESIDUE))
    if bad:
        raise BiologyError(f"Unsupported residue letter(s): {' '.join(bad)}", details={"field": "sequence", "characters": bad},
                           hint="Use the 20 standard one-letter amino-acid codes (B, J, O, U, X and Z are not supported).")
    return seq


def mass(seq: str) -> float:
    return sum(RESIDUE[a] for a in seq) + WATER


def net_charge(seq: str, ph: float) -> float:
    def pos(pk): return 1 / (1 + 10 ** (ph - pk))
    def neg(pk): return -1 / (1 + 10 ** (pk - ph))
    q = pos(PK["Nterm"]) + neg(PK["Cterm"])
    for a in seq:
        if a in POSITIVE:
            q += pos(PK[a])
        elif a in NEGATIVE:
            q += neg(PK[a])
    return q


def isoelectric_point(seq: str) -> float:
    lo, hi = 0.0, 14.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if net_charge(seq, mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def gravy(seq: str) -> float:
    return sum(KYTE_DOOLITTLE[a] for a in seq) / len(seq)


def extinction(seq: str) -> tuple[int, int]:
    """Pace et al.: ε280 in M⁻¹cm⁻¹ with all cysteines as cystines (pairs), and with none."""
    w, y, c = seq.count("W"), seq.count("Y"), seq.count("C")
    no_cystine = 5500 * w + 1490 * y
    return no_cystine + 125 * (c // 2), no_cystine


def composition(seq: str) -> list[dict]:
    return [{"residue": a, "name": AA_NAMES[a], "count": seq.count(a), "percent": 100 * seq.count(a) / len(seq)} for a in sorted(set(seq), key=lambda x: -seq.count(x))]
