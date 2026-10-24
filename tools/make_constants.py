"""Regenerate ``scical/data/constants.json`` (development tool, not needed at run time).

The values are CODATA 2022 as published in ``scipy.constants`` (scipy >= 1.15), which is a transcription of NIST SRD 121 /
Mohr, Newell, Taylor, Tiesinga, Rev. Mod. Phys. 97, 025002 (2025). The unit strings are written in SciCal's own unit syntax.
Constants with zero uncertainty are exact (the seven SI defining constants and what follows from them exactly).
Run:  python tools/make_constants.py  (needs scipy)
"""
import json
import pathlib
import scipy
import scipy.constants as sc

# key, scipy name, symbol, display name, unit in SciCal syntax
ROWS = [
    ("c", "speed of light in vacuum", "c", "speed of light in vacuum", "m/s"),
    ("h", "Planck constant", "h", "Planck constant", "J*s"),
    ("hbar", "reduced Planck constant", "ħ", "reduced Planck constant", "J*s"),
    ("e", "elementary charge", "e", "elementary charge", "C"),
    ("kB", "Boltzmann constant", "k_B", "Boltzmann constant", "J/K"),
    ("NA", "Avogadro constant", "N_A", "Avogadro constant", "1/mol"),
    ("R", "molar gas constant", "R", "molar gas constant", "J/(mol*K)"),
    ("F", "Faraday constant", "F", "Faraday constant", "C/mol"),
    ("sigma", "Stefan-Boltzmann constant", "σ", "Stefan-Boltzmann constant", "W/(m^2*K^4)"),
    ("b", "Wien wavelength displacement law constant", "b", "Wien wavelength displacement law constant", "m*K"),
    ("G", "Newtonian constant of gravitation", "G", "Newtonian constant of gravitation", "m^3/(kg*s^2)"),
    ("gn", "standard acceleration of gravity", "g_n", "standard acceleration of gravity", "m/s^2"),
    ("atm", "standard atmosphere", "atm", "standard atmosphere", "Pa"),
    ("me", "electron mass", "m_e", "electron mass", "kg"),
    ("mp", "proton mass", "m_p", "proton mass", "kg"),
    ("mn", "neutron mass", "m_n", "neutron mass", "kg"),
    ("mu", "atomic mass constant", "m_u", "atomic mass constant", "kg"),
    ("alpha", "fine-structure constant", "α", "fine-structure constant", ""),
    ("eps0", "vacuum electric permittivity", "ε₀", "vacuum electric permittivity", "F/m"),
    ("mu0", "vacuum mag. permeability", "μ₀", "vacuum magnetic permeability", "N/A^2"),
    ("Z0", "characteristic impedance of vacuum", "Z₀", "characteristic impedance of vacuum", "ohm"),
    ("Rinf", "Rydberg constant", "R∞", "Rydberg constant", "1/m"),
    ("a0", "Bohr radius", "a₀", "Bohr radius", "m"),
    ("muB", "Bohr magneton", "μ_B", "Bohr magneton", "J/T"),
    ("muN", "nuclear magneton", "μ_N", "nuclear magneton", "J/T"),
    ("re", "classical electron radius", "r_e", "classical electron radius", "m"),
    ("lambdaC", "Compton wavelength", "λ_C", "Compton wavelength", "m"),
    ("Vm", "molar volume of ideal gas (273.15 K, 101.325 kPa)", "V_m", "molar volume of an ideal gas at 273.15 K and 101.325 kPa", "m^3/mol"),
    ("KJ", "Josephson constant", "K_J", "Josephson constant", "Hz/V"),
    ("RK", "von Klitzing constant", "R_K", "von Klitzing constant", "ohm"),
]

out = {"meta": {
    "name": "CODATA recommended values of the fundamental physical constants",
    "version": "CODATA 2022",
    "source": "NIST SRD 121; Mohr, Newell, Taylor, Tiesinga, Rev. Mod. Phys. 97, 025002 (2025)",
    "transcribed_from": f"scipy.constants (scipy {scipy.__version__})",
    "note": "Constants listed with no uncertainty are exact. Values are decimal strings; SciCal reads them as exact decimals.",
}, "constants": {}}
from decimal import Decimal, getcontext
getcontext().prec = 60
D = Decimal
# Exactly representable as finite decimals (the SI defining constants and exact products/conventions of them).
EXACT_VALUES = {"c": "299792458", "h": "6.62607015e-34", "e": "1.602176634e-19", "kB": "1.380649e-23", "NA": "6.02214076e23",
                "gn": "9.80665", "atm": "101325",
                "R": str(D("6.02214076e23") * D("1.380649e-23")), "F": str(D("6.02214076e23") * D("1.602176634e-19"))}
for key, name, sym, disp, unit in ROWS:
    val, u, unc = sc.physical_constants[name]
    if key in EXACT_VALUES:
        out["constants"][key] = {"name": disp, "symbol": sym, "value": EXACT_VALUES[key], "uncertainty": None, "exact": True,
                                 "unit": unit, "codata_name": name}
    elif unc == 0:
        out["constants"][key] = {"name": disp, "symbol": sym, "value": repr(float(val)), "uncertainty": None, "exact": False,
                                 "unit": unit, "codata_name": name,
                                 "note": "Fixed exactly by the SI defining constants, but not a finite decimal; the value is rounded to 17 digits."}
    else:
        out["constants"][key] = {"name": disp, "symbol": sym, "value": repr(float(val)), "uncertainty": repr(float(unc)),
                                 "exact": False, "unit": unit, "codata_name": name}
path = pathlib.Path(__file__).resolve().parent.parent / "scical" / "data" / "constants.json"
path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", path, len(out["constants"]))
