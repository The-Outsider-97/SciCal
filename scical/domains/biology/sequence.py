"""Nucleic acid and protein sequence analysis: pure functions on cleaned strings."""
from __future__ import annotations

import math
import re
from typing import Iterable

from ...errors import BadRequest, BiologyError

MAX_SEQ = 1_000_000

_COMP_DNA = str.maketrans("ACGTacgt", "TGCAtgca")
_COMP_RNA = str.maketrans("ACGUacgu", "UGCAugca")

# The standard genetic code (NCBI translation table 1), codons in TCAG order.
_BASES = "TCAG"
_AA = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
CODON_TABLE: dict[str, str] = {a + b + c: _AA[16 * i + 4 * j + k] for i, a in enumerate(_BASES) for j, b in enumerate(_BASES) for k, c in enumerate(_BASES)}
START_CODONS = {"TTG", "CTG", "ATG"}      # alternative starts are reported only when asked for

AA_NAMES = {"A": "Alanine", "R": "Arginine", "N": "Asparagine", "D": "Aspartate", "C": "Cysteine", "Q": "Glutamine", "E": "Glutamate",
            "G": "Glycine", "H": "Histidine", "I": "Isoleucine", "L": "Leucine", "K": "Lysine", "M": "Methionine", "F": "Phenylalanine",
            "P": "Proline", "S": "Serine", "T": "Threonine", "W": "Tryptophan", "Y": "Tyrosine", "V": "Valine"}

RESTRICTION = {  # name: (recognition site, cut offset on the top strand)
    "EcoRI": ("GAATTC", 1), "BamHI": ("GGATCC", 1), "HindIII": ("AAGCTT", 1), "NotI": ("GCGGCCGC", 2), "XhoI": ("CTCGAG", 1),
    "SalI": ("GTCGAC", 1), "NdeI": ("CATATG", 2), "XbaI": ("TCTAGA", 1), "PstI": ("CTGCAG", 5), "SmaI": ("CCCGGG", 3),
    "KpnI": ("GGTACC", 5), "SacI": ("GAGCTC", 5), "NcoI": ("CCATGG", 1), "EcoRV": ("GATATC", 3), "BglII": ("AGATCT", 1),
    "SpeI": ("ACTAGT", 1), "NheI": ("GCTAGC", 1), "ApaI": ("GGGCCC", 5), "ClaI": ("ATCGAT", 2), "HaeIII": ("GGCC", 2),
    "AluI": ("AGCT", 2), "TaqI": ("TCGA", 1),
}


def clean(raw: str, kind: str = "auto", field: str = "sequence") -> tuple[str, str]:
    """Strip FASTA header, whitespace and position numbers, upper-case, validate. Returns (sequence, 'dna' | 'rna')."""
    if not isinstance(raw, str) or not raw.strip():
        raise BadRequest(f"'{field}' is required", details={"field": field})
    lines = [ln for ln in raw.splitlines()]
    if lines and lines[0].lstrip().startswith(">"):
        body = []
        for ln in lines[1:]:
            if ln.lstrip().startswith(">"):
                break                       # only the first record is analysed
            body.append(ln)
        lines = body
    seq = re.sub(r"[\s\d\-\*]", "", "".join(lines)).upper()
    if not seq:
        raise BadRequest(f"'{field}' contains no sequence letters", details={"field": field})
    if len(seq) > MAX_SEQ:
        raise BadRequest(f"The sequence is longer than {MAX_SEQ:,} bases", details={"field": field})
    has_u, has_t = "U" in seq, "T" in seq
    if has_u and has_t:
        raise BiologyError("The sequence contains both T and U", details={"field": field}, hint="DNA uses T and RNA uses U; a sequence cannot have both.")
    k = kind if kind in ("dna", "rna") else ("rna" if has_u else "dna")
    if kind == "dna" and has_u:
        raise BiologyError("A DNA sequence cannot contain U", details={"field": field})
    if kind == "rna" and has_t:
        raise BiologyError("An RNA sequence cannot contain T", details={"field": field})
    allowed = set("ACGU" if k == "rna" else "ACGT") | {"N"}
    bad = sorted(set(seq) - allowed)
    if bad:
        raise BiologyError(f"Invalid {k.upper()} character(s): {' '.join(bad)}", details={"field": field, "characters": bad},
                           hint="Allowed letters: A C G " + ("U" if k == "rna" else "T") + " (and N for an unknown base).")
    return seq, k


def reverse_complement(seq: str, kind: str = "dna") -> str:
    return seq.translate(_COMP_RNA if kind == "rna" else _COMP_DNA)[::-1].replace("n", "N")


def complement(seq: str, kind: str = "dna") -> str:
    return seq.translate(_COMP_RNA if kind == "rna" else _COMP_DNA)


def to_dna(seq: str) -> str:
    return seq.replace("U", "T")


def composition(seq: str) -> dict[str, int]:
    return {b: seq.count(b) for b in sorted(set(seq))}


def gc_fraction(seq: str) -> tuple[int, int]:
    """Returns (G+C count, informative length = bases other than N)."""
    n = len(seq) - seq.count("N")
    return seq.count("G") + seq.count("C"), n


def translate(seq: str, to_stop: bool = False, frame: int = 0) -> str:
    dna = to_dna(seq)
    out = []
    for i in range(frame, len(dna) - 2, 3):
        aa = CODON_TABLE.get(dna[i:i + 3], "X")
        if aa == "*" and to_stop:
            break
        out.append(aa)
    return "".join(out)


def find_orfs(seq: str, min_aa: int = 30, both: bool = True, limit: int = 500) -> tuple[list[dict], bool]:
    """ATG-to-stop open reading frames in the three frames of each strand (standard code; unterminated ORFs are not reported)."""
    dna = to_dna(seq)
    n = len(dna)
    found: list[dict] = []
    strands = [("+", dna)] + ([("-", reverse_complement(dna))] if both else [])
    for strand, s in strands:
        for frame in range(3):
            start, prot = None, []
            for i in range(frame, len(s) - 2, 3):
                codon = s[i:i + 3]
                if start is None:
                    if codon == "ATG":
                        start, prot = i, ["M"]
                    continue
                aa = CODON_TABLE.get(codon, "X")
                if aa == "*":
                    if len(prot) >= min_aa:
                        end = i + 3
                        a, b = (start + 1, end) if strand == "+" else (n - end + 1, n - start)
                        found.append({"strand": strand, "frame": frame + 1, "start": a, "end": b, "lengthNt": end - start,
                                      "lengthAa": len(prot), "protein": "".join(prot)})
                    start, prot = None, []
                else:
                    prot.append(aa)
    found.sort(key=lambda o: (-o["lengthNt"], o["start"]))
    return found[:limit], len(found) > limit


def restriction_sites(seq: str, enzymes: Iterable[str] | None = None, circular: bool = False) -> list[dict]:
    dna = to_dna(seq)
    n = len(dna)
    names = list(enzymes) if enzymes else list(RESTRICTION)
    res = []
    for name in names:
        if name not in RESTRICTION:
            raise BadRequest(f"Unknown enzyme '{name}'", details={"field": "enzymes"}, hint="Known: " + ", ".join(sorted(RESTRICTION)))
        site, off = RESTRICTION[name]
        text = dna + (dna[:len(site) - 1] if circular else "")
        pos = [m.start() for m in re.finditer(f"(?={site})", text) if m.start() < n]
        cuts = sorted(((p + off) % n if circular else p + off) for p in pos)
        if circular:
            frags = [(cuts[(i + 1) % len(cuts)] - c) % n or n for i, c in enumerate(cuts)] if len(cuts) > 1 else ([n] if cuts else [])
        else:
            edges = [0] + [c for c in cuts if 0 < c < n] + [n]
            frags = [b - a for a, b in zip(edges, edges[1:])]
        res.append({"enzyme": name, "site": site, "cutsAfter": off, "positions": [p + 1 for p in pos], "count": len(pos), "fragments": sorted(frags, reverse=True)})
    return res


# ---- masses and melting temperatures -----------------------------------------------------------------------------------------------
_W = 18.0153
_MW_DNA = {"A": 331.2218, "C": 307.1971, "G": 347.2212, "T": 322.2085}
_MW_RNA = {"A": 347.2212, "C": 323.1965, "G": 363.2206, "U": 324.1813}


def nucleic_weight(seq: str, kind: str) -> float | None:
    if "N" in seq:
        return None
    table = _MW_RNA if kind == "rna" else _MW_DNA
    return sum(table[b] for b in seq) - (len(seq) - 1) * _W


def melting_temperature(seq: str, na_molar: float = 0.05) -> dict:
    gc, n = gc_fraction(seq)
    at = n - gc
    out: dict = {"basic": None, "salt": None, "method": None}
    if n == 0:
        return out
    if n < 14:
        out["basic"] = 2 * at + 4 * gc
        out["method"] = "Wallace rule: 2(A+T) + 4(G+C), for sequences shorter than 14 nt"
    else:
        out["basic"] = 64.9 + 41 * (gc - 16.4) / n
        out["method"] = "64.9 + 41(G+C−16.4)/N, for sequences of 14 nt or more"
    if n >= 14 and na_molar > 0:
        out["salt"] = 81.5 + 16.6 * math.log10(na_molar) + 41 * gc / n - 675 / n
    return out
