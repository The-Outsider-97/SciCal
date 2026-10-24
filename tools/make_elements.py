"""Builds scical/data/elements.json. Atomic weights: CIAAW "Standard Atomic Weights 2024" (based on the 2021 report; Gd, Lu, Zr revised in 2024).

Elements whose weight is a range in that table use the IUPAC *conventional* value (marked ``weightKind = "conventional"``); elements with
no standard weight carry the mass number of their longest-lived known isotope in brackets (``weightKind = "none"``; not a standard weight).
"""
import json
from pathlib import Path

# Z, symbol, name, weight, uncertainty (last digits) or None, kind
W = """
1 H Hydrogen 1.008 - conventional
2 He Helium 4.002602 2 standard
3 Li Lithium 6.94 - conventional
4 Be Beryllium 9.0121831 5 standard
5 B Boron 10.81 - conventional
6 C Carbon 12.011 - conventional
7 N Nitrogen 14.007 - conventional
8 O Oxygen 15.999 - conventional
9 F Fluorine 18.998403162 5 standard
10 Ne Neon 20.1797 6 standard
11 Na Sodium 22.98976928 2 standard
12 Mg Magnesium 24.305 - conventional
13 Al Aluminium 26.9815384 3 standard
14 Si Silicon 28.085 - conventional
15 P Phosphorus 30.973761998 5 standard
16 S Sulfur 32.06 - conventional
17 Cl Chlorine 35.45 - conventional
18 Ar Argon 39.95 - conventional
19 K Potassium 39.0983 1 standard
20 Ca Calcium 40.078 4 standard
21 Sc Scandium 44.955907 4 standard
22 Ti Titanium 47.867 1 standard
23 V Vanadium 50.9415 1 standard
24 Cr Chromium 51.9961 6 standard
25 Mn Manganese 54.938043 2 standard
26 Fe Iron 55.845 2 standard
27 Co Cobalt 58.933194 3 standard
28 Ni Nickel 58.6934 4 standard
29 Cu Copper 63.546 3 standard
30 Zn Zinc 65.38 2 standard
31 Ga Gallium 69.723 1 standard
32 Ge Germanium 72.630 8 standard
33 As Arsenic 74.921595 6 standard
34 Se Selenium 78.971 8 standard
35 Br Bromine 79.904 - conventional
36 Kr Krypton 83.798 2 standard
37 Rb Rubidium 85.4678 3 standard
38 Sr Strontium 87.62 1 standard
39 Y Yttrium 88.905838 2 standard
40 Zr Zirconium 91.222 3 standard
41 Nb Niobium 92.90637 1 standard
42 Mo Molybdenum 95.95 1 standard
43 Tc Technetium [98] - none
44 Ru Ruthenium 101.07 2 standard
45 Rh Rhodium 102.90549 2 standard
46 Pd Palladium 106.42 1 standard
47 Ag Silver 107.8682 2 standard
48 Cd Cadmium 112.414 4 standard
49 In Indium 114.818 1 standard
50 Sn Tin 118.710 7 standard
51 Sb Antimony 121.760 1 standard
52 Te Tellurium 127.60 3 standard
53 I Iodine 126.90447 3 standard
54 Xe Xenon 131.293 6 standard
55 Cs Caesium 132.90545196 6 standard
56 Ba Barium 137.327 7 standard
57 La Lanthanum 138.90547 7 standard
58 Ce Cerium 140.116 1 standard
59 Pr Praseodymium 140.90766 1 standard
60 Nd Neodymium 144.242 3 standard
61 Pm Promethium [145] - none
62 Sm Samarium 150.36 2 standard
63 Eu Europium 151.964 1 standard
64 Gd Gadolinium 157.249 2 standard
65 Tb Terbium 158.925354 7 standard
66 Dy Dysprosium 162.500 1 standard
67 Ho Holmium 164.930329 5 standard
68 Er Erbium 167.259 3 standard
69 Tm Thulium 168.934219 5 standard
70 Yb Ytterbium 173.045 10 standard
71 Lu Lutetium 174.96669 5 standard
72 Hf Hafnium 178.486 6 standard
73 Ta Tantalum 180.94788 2 standard
74 W Tungsten 183.84 1 standard
75 Re Rhenium 186.207 1 standard
76 Os Osmium 190.23 3 standard
77 Ir Iridium 192.217 2 standard
78 Pt Platinum 195.084 9 standard
79 Au Gold 196.966570 4 standard
80 Hg Mercury 200.592 3 standard
81 Tl Thallium 204.38 - conventional
82 Pb Lead 207.2 - conventional
83 Bi Bismuth 208.98040 1 standard
84 Po Polonium [209] - none
85 At Astatine [210] - none
86 Rn Radon [222] - none
87 Fr Francium [223] - none
88 Ra Radium [226] - none
89 Ac Actinium [227] - none
90 Th Thorium 232.0377 4 standard
91 Pa Protactinium 231.03588 1 standard
92 U Uranium 238.02891 3 standard
93 Np Neptunium [237] - none
94 Pu Plutonium [244] - none
95 Am Americium [243] - none
96 Cm Curium [247] - none
97 Bk Berkelium [247] - none
98 Cf Californium [251] - none
99 Es Einsteinium [252] - none
100 Fm Fermium [257] - none
101 Md Mendelevium [258] - none
102 No Nobelium [259] - none
103 Lr Lawrencium [266] - none
104 Rf Rutherfordium [267] - none
105 Db Dubnium [268] - none
106 Sg Seaborgium [269] - none
107 Bh Bohrium [270] - none
108 Hs Hassium [269] - none
109 Mt Meitnerium [278] - none
110 Ds Darmstadtium [281] - none
111 Rg Roentgenium [282] - none
112 Cn Copernicium [285] - none
113 Nh Nihonium [286] - none
114 Fl Flerovium [289] - none
115 Mc Moscovium [290] - none
116 Lv Livermorium [293] - none
117 Ts Tennessine [294] - none
118 Og Oganesson [294] - none
"""

EN = {1: 2.20, 3: .98, 4: 1.57, 5: 2.04, 6: 2.55, 7: 3.04, 8: 3.44, 9: 3.98, 11: .93, 12: 1.31, 13: 1.61, 14: 1.90, 15: 2.19, 16: 2.58, 17: 3.16,
      19: .82, 20: 1.00, 21: 1.36, 22: 1.54, 23: 1.63, 24: 1.66, 25: 1.55, 26: 1.83, 27: 1.88, 28: 1.91, 29: 1.90, 30: 1.65, 31: 1.81, 32: 2.01,
      33: 2.18, 34: 2.55, 35: 2.96, 36: 3.00, 37: .82, 38: .95, 39: 1.22, 40: 1.33, 41: 1.6, 42: 2.16, 43: 1.9, 44: 2.2, 45: 2.28, 46: 2.20,
      47: 1.93, 48: 1.69, 49: 1.78, 50: 1.96, 51: 2.05, 52: 2.1, 53: 2.66, 54: 2.6, 55: .79, 56: .89, 57: 1.10, 58: 1.12, 59: 1.13, 60: 1.14,
      61: 1.13, 62: 1.17, 63: 1.2, 64: 1.2, 65: 1.1, 66: 1.22, 67: 1.23, 68: 1.24, 69: 1.25, 70: 1.1, 71: 1.27, 72: 1.3, 73: 1.5, 74: 2.36,
      75: 1.9, 76: 2.2, 77: 2.20, 78: 2.28, 79: 2.54, 80: 2.00, 81: 1.62, 82: 2.33, 83: 2.02, 84: 2.0, 85: 2.2, 86: 2.2, 88: .9, 89: 1.1,
      90: 1.3, 91: 1.5, 92: 1.38, 93: 1.36, 94: 1.28, 95: 1.13, 96: 1.28, 97: 1.3, 98: 1.3, 99: 1.3, 100: 1.3, 101: 1.3, 102: 1.3}
GAS = {1, 2, 7, 8, 9, 10, 17, 18, 36, 54, 86}
LIQUID = {35, 80}
ALKALI, ALKALINE = {3, 11, 19, 37, 55, 87}, {4, 12, 20, 38, 56, 88}
METALLOID = {5, 14, 32, 33, 51, 52}
NONMETAL = {1, 6, 7, 8, 15, 16, 34}
HALOGEN = {9, 17, 35, 53, 85, 117}
NOBLE = {2, 10, 18, 36, 54, 86, 118}
POST = {13, 31, 49, 50, 81, 82, 83, 84, 113, 114, 115, 116}
EXCEPT = {24: "[Ar] 3d5 4s1", 29: "[Ar] 3d10 4s1", 41: "[Kr] 4d4 5s1", 42: "[Kr] 4d5 5s1", 44: "[Kr] 4d7 5s1", 45: "[Kr] 4d8 5s1",
          46: "[Kr] 4d10", 47: "[Kr] 4d10 5s1", 57: "[Xe] 5d1 6s2", 58: "[Xe] 4f1 5d1 6s2", 64: "[Xe] 4f7 5d1 6s2", 78: "[Xe] 4f14 5d9 6s1",
          79: "[Xe] 4f14 5d10 6s1", 89: "[Rn] 6d1 7s2", 90: "[Rn] 6d2 7s2", 91: "[Rn] 5f2 6d1 7s2", 92: "[Rn] 5f3 6d1 7s2",
          93: "[Rn] 5f4 6d1 7s2", 96: "[Rn] 5f7 6d1 7s2", 103: "[Rn] 5f14 7s2 7p1"}
NOBLE_CORE = [(2, "He"), (10, "Ne"), (18, "Ar"), (36, "Kr"), (54, "Xe"), (86, "Rn")]
ORDER = ["1s", "2s", "2p", "3s", "3p", "4s", "3d", "4p", "5s", "4d", "5p", "6s", "4f", "5d", "6p", "7s", "5f", "6d", "7p"]
CAP = {"s": 2, "p": 6, "d": 10, "f": 14}


def madelung(z):
    left, parts = z, []
    for sub in ORDER:
        if left <= 0:
            break
        n = min(left, CAP[sub[1]])
        parts.append((sub, n))
        left -= n
    return parts


def config(z):
    if z in EXCEPT:
        return EXCEPT[z], False
    parts = madelung(z)
    core = None
    for cz, sym in NOBLE_CORE:
        if cz < z:
            core = (cz, sym)
    if core is None:
        return " ".join(f"{s}{n}" for s, n in parts), True
    skip = madelung(core[0])
    rest = [(s, n) for (s, n) in parts]
    for (s, n) in skip:
        for i, (s2, n2) in enumerate(rest):
            if s2 == s:
                rest[i] = (s2, n2 - n)
    rest = [(s, n) for s, n in rest if n > 0]
    rest.sort(key=lambda t: (int(t[0][0]), "spdf".index(t[0][1])))
    return f"[{core[1]}] " + " ".join(f"{s}{n}" for s, n in rest), z <= 103


def pos(z):
    periods = [(1, 2), (3, 10), (11, 18), (19, 36), (37, 54), (55, 86), (87, 118)]
    for p, (a, b) in enumerate(periods, 1):
        if a <= z <= b:
            period = p
            break
    if z == 1:
        return 1, 1, "s"
    if z == 2:
        return 1, 18, "s"
    if period in (2, 3):
        i = z - periods[period - 1][0]
        g = [1, 2, 13, 14, 15, 16, 17, 18][i]
        return period, g, "s" if g <= 2 else "p"
    if period in (4, 5):
        g = z - periods[period - 1][0] + 1
        return period, g, "s" if g <= 2 else ("d" if g <= 12 else "p")
    start = periods[period - 1][0]
    i = z - start
    if i < 2:
        return period, i + 1, "s"
    f0, f1 = (57, 71) if period == 6 else (89, 103)
    if f0 <= z <= f1:
        return period, None, "f"
    g = (z - f1) + 3 if z > f1 else None
    g = z - f1 + 3
    return period, g, "d" if g <= 12 else "p"


def category(z, grp):
    if z in ALKALI: return "alkali metal"
    if z in ALKALINE: return "alkaline earth metal"
    if z in METALLOID: return "metalloid"
    if z in HALOGEN: return "halogen"
    if z in NOBLE: return "noble gas"
    if z in NONMETAL: return "nonmetal"
    if 57 <= z <= 71: return "lanthanide"
    if 89 <= z <= 103: return "actinide"
    if z in POST: return "post-transition metal"
    return "transition metal"


ISOTOPES = {  # symbol: [(mass number, atomic mass u, natural abundance %)] ; AME2020 / NIST
    "H": [(1, "1.00782503223", "99.9885"), (2, "2.01410177812", "0.0115"), (3, "3.0160492779", None)],
    "C": [(12, "12", "98.93"), (13, "13.00335483507", "1.07"), (14, "14.0032419884", None)],
    "N": [(14, "14.00307400443", "99.636"), (15, "15.00010889888", "0.364")],
    "O": [(16, "15.99491461957", "99.757"), (17, "16.99913175650", "0.038"), (18, "17.99915961286", "0.205")],
    "Cl": [(35, "34.968852682", "75.76"), (37, "36.965902602", "24.24")],
    "Br": [(79, "78.9183376", "50.69"), (81, "80.9162897", "49.31")],
    "Na": [(23, "22.989769282", "100")], "P": [(31, "30.97376199842", "100")], "F": [(19, "18.99840316273", "100")],
    "S": [(32, "31.9720711744", "94.99"), (33, "32.9714589098", "0.75"), (34, "33.967867004", "4.25"), (36, "35.96708071", "0.01")],
    "U": [(235, "235.0439299", "0.7204"), (238, "238.05078826", "99.2745")],
}


def main():
    rows = []
    for line in W.strip().splitlines():
        z, sym, name, w, u, kind = line.split()
        z = int(z)
        period, grp, block = pos(z)
        cfg, reliable = config(z)
        state = "gas" if z in GAS else "liquid" if z in LIQUID else "solid" if z <= 99 else "unknown"
        rows.append({"z": z, "symbol": sym, "name": name, "weight": w, "uncertainty": None if u == "-" else int(u), "weightKind": kind,
                     "period": period, "group": grp, "block": block, "category": category(z, grp), "electronegativity": EN.get(z),
                     "state": state, "configuration": cfg, "configurationNote": "" if reliable else "predicted or irregular: see source",
                     "isotopes": [{"A": a, "mass": m, "abundance": ab} for a, m, ab in ISOTOPES.get(sym, [])]})
    out = {"meta": {"source": "CIAAW Standard Atomic Weights 2024 (based on Atomic Weights 2021; Gd, Lu, Zr revised 2024), https://ciaaw.org/atomic-weights.htm",
                    "conventional": "IUPAC conventional atomic weights are used for elements listed as intervals",
                    "isotopes": "Atomic masses: AME2020 via NIST; abundances: IUPAC/NIST",
                    "electronegativity": "Pauling scale, commonly tabulated values",
                    "configuration": "Ground-state configurations from the Madelung rule with the known irregular cases; Z > 103 are predictions"},
           "elements": rows}
    path = Path(__file__).resolve().parent.parent / "scical" / "data" / "elements.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", path, len(rows))


if __name__ == "__main__":
    main()
