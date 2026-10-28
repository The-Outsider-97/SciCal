"""Regenerate ``scical/data/constants.json`` (development tool, not needed at run time).

One store feeds everything: ``const(name)`` in expressions, the Measurement "Physical constants" card and the Constants page.

Sources, by category
    physical / chemical / engineering(part)  CODATA 2022 as published in ``scipy.constants`` (scipy >= 1.15), a transcription of NIST SRD 121 /
                                              Mohr, Newell, Taylor, Tiesinga, Rev. Mod. Phys. 97, 025002 (2025). Verified as the newest edition NIST
                                              lists (release 9.0, 9 May 2024) before this file was written.
    mathematical                              the definitions themselves; digits computed with mpmath at 80 digits and stored to 50.
    astronomical                              IAU 2012 Resolution B2 (astronomical unit), IAU 2015 Resolution B3 (nominal solar and planetary
                                              conversion constants), the Julian year; derived values are computed here from those and CODATA 2022 G.
    engineering                               NIST SP 811 (conversion factors), ISO 2533:1975 (standard atmosphere), CGPM 1901 (standard gravity).
Run:  python tools/make_constants.py  (needs scipy and mpmath)
"""
import json
import math
import pathlib
from decimal import Decimal, getcontext

import mpmath as mp
import scipy
import scipy.constants as sc

getcontext().prec = 80
D = Decimal
mp.mp.dps = 80

CODATA = "CODATA 2022 (NIST SRD 121; Mohr, Newell, Taylor, Tiesinga, Rev. Mod. Phys. 97, 025002 (2025))"
IAU12 = "IAU 2012 Resolution B2"
IAU15 = "IAU 2015 Resolution B3 (nominal conversion constants)"
SP811 = "NIST SP 811, Guide for the Use of the International System of Units (conversion factors)"

CATEGORIES = {
    "mathematical": {"title": "Mathematical", "description": "Defined by mathematics, not measured. Irrational numbers are shown to 50 digits."},
    "physical": {"title": "Physical", "description": "Fundamental physical constants: the SI defining constants (exact) and measured CODATA 2022 values with their standard uncertainties."},
    "chemical": {"title": "Chemical", "description": "Constants used in chemistry and thermodynamics."},
    "astronomical": {"title": "Astronomical", "description": "IAU definitions and nominal values (exact conventions) are kept apart from derived, measured-dependent quantities."},
    "engineering": {"title": "Engineering reference", "description": "Standard gravity, standard atmosphere and exact unit-conversion factors. No material properties: those depend on the material and conditions."},
}

# key -> (category, description, applications = formula ids of the Formulas library)
INFO = {
    "c": ("physical", "Speed of light in vacuum. One of the seven SI defining constants; it defines the metre.", ["massenergy", "wave", "debroglie"]),
    "h": ("physical", "Planck constant, relating a photon's energy to its frequency. An SI defining constant; it defines the kilogram.", ["photon_f", "photon_l", "debroglie"]),
    "hbar": ("physical", "Reduced Planck constant, h/2π.", ["debroglie"]),
    "e": ("physical", "Elementary charge, the charge of a proton. An SI defining constant.", ["coulomb", "capacitor_q"]),
    "kB": ("physical", "Boltzmann constant, linking temperature to energy per particle. An SI defining constant; it defines the kelvin.", ["idealgas", "arrhenius"]),
    "NA": ("chemical", "Avogadro constant, the number of entities in one mole. An SI defining constant; it defines the mole.", ["moles"]),
    "R": ("chemical", "Molar gas constant, N_A·k_B. Exact because both factors are exact.", ["idealgas", "arrhenius", "nernst", "gibbs"]),
    "F": ("chemical", "Faraday constant, the charge of one mole of elementary charges, N_A·e. Exact.", ["nernst"]),
    "sigma": ("physical", "Stefan–Boltzmann constant, 2π⁵k_B⁴/(15h³c²). Exact in the SI but irrational.", ["stefan"]),
    "b": ("physical", "Wien wavelength displacement constant: λ_max·T = b for a black body.", ["stefan"]),
    "G": ("physical", "Newtonian constant of gravitation. The least precisely known fundamental constant.", ["gravitation", "escape"]),
    "gn": ("engineering", "Standard acceleration of gravity g_n, a conventional value adopted by the CGPM in 1901. Not the local value of g.", ["weight", "potential", "pendulum"]),
    "atm": ("engineering", "Standard atmosphere: the conventional sea-level pressure. Exact by definition.", ["pressure"]),
    "me": ("physical", "Electron mass.", ["kinetic", "debroglie"]),
    "mp": ("physical", "Proton mass.", ["kinetic"]),
    "mn": ("physical", "Neutron mass.", ["kinetic"]),
    "mu": ("chemical", "Atomic mass constant (unified atomic mass unit): one twelfth of the mass of a carbon-12 atom, as measured.", ["moles"]),
    "alpha": ("physical", "Fine-structure constant, the strength of the electromagnetic interaction (dimensionless).", ["coulomb"]),
    "eps0": ("physical", "Vacuum electric permittivity. Since the 2019 SI it is measured, not exact.", ["coulomb", "capacitor_q", "capacitor_e"]),
    "mu0": ("physical", "Vacuum magnetic permeability. Since the 2019 SI it is measured, not exactly 4π×10⁻⁷.", []),
    "Z0": ("physical", "Characteristic impedance of vacuum, μ₀c.", []),
    "Rinf": ("physical", "Rydberg constant, the scale of atomic spectral lines.", ["photon_l"]),
    "a0": ("physical", "Bohr radius, the most probable distance of the electron in hydrogen's ground state.", []),
    "muB": ("physical", "Bohr magneton, the natural unit of the electron's magnetic moment.", []),
    "muN": ("physical", "Nuclear magneton.", []),
    "re": ("physical", "Classical electron radius.", []),
    "lambdaC": ("physical", "Compton wavelength of the electron, h/(m_e c).", ["debroglie"]),
    "Vm": ("chemical", "Molar volume of an ideal gas at 273.15 K and 101.325 kPa, R·T/p.", ["idealgas"]),
    "KJ": ("physical", "Josephson constant, 2e/h, relating a voltage to a frequency.", []),
    "RK": ("physical", "von Klitzing constant, h/e², the quantum of resistance.", []),
}

# New CODATA 2022 rows: key, scipy name, symbol, display name, unit (SciCal syntax), category, description, applications
EXTRA = [
    ("mmu", "muon mass", "m_μ", "muon mass", "kg", "physical", "Muon mass.", []),
    ("mtau", "tau mass", "m_τ", "tau mass", "kg", "physical", "Tau lepton mass.", []),
    ("md", "deuteron mass", "m_d", "deuteron mass", "kg", "physical", "Deuteron mass.", []),
    ("mpme", "proton-electron mass ratio", "m_p/m_e", "proton-electron mass ratio", "", "physical", "Ratio of the proton mass to the electron mass (dimensionless).", []),
    ("ge", "electron g factor", "g_e", "electron g-factor", "", "physical", "Electron g-factor (dimensionless, negative by convention).", []),
    ("Eh", "Hartree energy", "E_h", "Hartree energy", "J", "physical", "Atomic unit of energy, 2R∞hc.", []),
    ("eV", "electron volt", "eV", "electron volt", "J", "physical", "Energy gained by an electron across one volt. Exact: it equals the elementary charge times 1 V.", ["photon_f", "kinetic"]),
    ("c1", "first radiation constant", "c₁", "first radiation constant", "W*m^2", "physical", "First radiation constant, 2πhc², in Planck's law of black-body radiation.", ["stefan"]),
    ("c2", "second radiation constant", "c₂", "second radiation constant", "m*K", "physical", "Second radiation constant, hc/k_B.", []),
    ("Phi0", "mag. flux quantum", "Φ₀", "magnetic flux quantum", "Wb", "physical", "Magnetic flux quantum, h/2e.", []),
    ("G0", "conductance quantum", "G₀", "conductance quantum", "S", "physical", "Conductance quantum, 2e²/h.", []),
    ("bprime", "Wien frequency displacement law constant", "b′", "Wien frequency displacement law constant", "Hz/K", "physical", "Wien frequency displacement constant: the peak frequency of black-body radiation is b′·T.", ["stefan"]),
    ("p0", "standard-state pressure", "p°", "standard-state pressure", "Pa", "chemical", "IUPAC standard-state pressure of 1 bar (the convention since 1982), used for tabulated thermochemical data.", ["gibbs"]),
]

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

# Exactly representable as finite decimals (the SI defining constants and exact products/conventions of them).
EXACT_VALUES = {"c": "299792458", "h": "6.62607015e-34", "e": "1.602176634e-19", "kB": "1.380649e-23", "NA": "6.02214076e23",
                "gn": "9.80665", "atm": "101325", "eV": "1.602176634e-19", "p0": "100000",
                "R": str(D("6.02214076e23") * D("1.380649e-23")), "F": str(D("6.02214076e23") * D("1.602176634e-19"))}


def _mp(x):
    return D(mp.nstr(x, 45, strip_zeros=False))


_h, _c, _e, _k = mp.mpf("6.62607015e-34"), mp.mpf(299792458), mp.mpf("1.602176634e-19"), mp.mpf("1.380649e-23")
_x_b = mp.findroot(lambda x: x - 5 * (1 - mp.exp(-x)), 4.965)
_x_f = mp.findroot(lambda x: x - 3 * (1 - mp.exp(-x)), 2.821)
# exact consequences of the SI defining constants, evaluated at 80 digits (so not the 17 digits of a float) and stored to 40
COMPUTED = {
    "hbar": _h / (2 * mp.pi),
    "sigma": 2 * mp.pi ** 5 * _k ** 4 / (15 * _h ** 3 * _c ** 2),
    "b": _h * _c / (_k * _x_b),
    "bprime": _k * _x_f / _h,
    "c1": 2 * mp.pi * _h * _c ** 2,
    "c2": _h * _c / _k,
    "Phi0": _h / (2 * _e),
    "G0": 2 * _e ** 2 / _h,
    "KJ": 2 * _e / _h,
    "RK": _h / _e ** 2,
    "Vm": mp.mpf("6.02214076e23") * _k * mp.mpf("273.15") / 101325,
}


def sigfigs_measured(value: str, unc: str) -> int:
    """Digits of the value that are meaningful: down to the place of the uncertainty's second significant digit (CODATA publishes two)."""
    v, u = D(value), D(unc)
    place = u.adjusted() - 1
    return max(1, v.adjusted() - place + 1)


def sigfigs_exact(value: str) -> int:
    digits = D(value).as_tuple().digits
    n = len(digits)
    while n > 1 and digits[n - 1] == 0:
        n -= 1
    return n


def clean(x: D) -> str:
    """A Decimal as a plain scientific-notation string without trailing zeros."""
    s = format(x.normalize(), "e") if x != 0 else "0"
    return s.replace("e+", "e")


def entry(name, symbol, value, uncertainty, exact, unit, category, kind, description, applications, source, edition, note=None, sigfigs=None, **extra):
    out = {"name": name, "symbol": symbol, "value": value, "uncertainty": uncertainty, "exact": exact, "unit": unit, "category": category, "kind": kind,
           "description": description, "applications": applications, "source": source, "edition": edition}
    if note:
        out["note"] = note
    out["sigfigs"] = sigfigs
    out.update(extra)
    return out


def codata_row(key, scipy_name, sym, disp, unit, category, description, apps):
    val, _u, unc = sc.physical_constants[scipy_name]
    if key in COMPUTED:
        unc = 0
    if key in EXACT_VALUES:
        v = EXACT_VALUES[key]
        return entry(disp, sym, v, None, True, unit, category, "exact", description, apps, CODATA, "CODATA 2022",
                     note="Exact by definition (an SI defining constant or an exact product of them)." if key in ("c", "h", "e", "kB", "NA") else "Exact by definition.",
                     sigfigs=sigfigs_exact(v), codata_name=scipy_name)
    if unc == 0:
        v = clean(_mp(COMPUTED[key]).quantize(D(1).scaleb(_mp(COMPUTED[key]).adjusted() - 39)))
        assert abs(float(v) / float(val) - 1) < 1e-14, (key, v, val)   # agrees with the scipy transcription
        return entry(disp, sym, v, None, True, unit, category, "exact_derived", description, apps, CODATA, "CODATA 2022",
                     note="An exact consequence of the SI defining constants; the number is not a finite decimal, so it is stored to 40 significant digits.", sigfigs=40, codata_name=scipy_name)
    v, u = repr(float(val)), repr(float(unc))
    return entry(disp, sym, v, u, False, unit, category, "measured", description, apps, CODATA, "CODATA 2022", sigfigs=sigfigs_measured(v, u), codata_name=scipy_name)


constants = {}
for key, name, sym, disp, unit in ROWS:
    category, description, apps = INFO[key]
    constants[key] = codata_row(key, name, sym, disp, unit, category, description, apps)
for key, name, sym, disp, unit, category, description, apps in EXTRA:
    constants[key] = codata_row(key, name, sym, disp, unit, category, description, apps)

# the standard atmosphere and standard gravity are conventions rather than measurements
constants["gn"]["kind"] = "convention"
constants["gn"]["source"], constants["gn"]["edition"] = "CGPM 1901 (3rd CGPM, Resolution 2); listed in CODATA 2022", "CGPM 1901"
constants["atm"]["kind"] = "convention"
constants["atm"]["source"], constants["atm"]["edition"] = "CGPM 1954 (10th CGPM, Resolution 4); listed in CODATA 2022", "CGPM 1954"
constants["p0"]["kind"] = "convention"
constants["p0"]["source"], constants["p0"]["edition"] = "IUPAC 1982 (standard state pressure of 1 bar); listed in CODATA 2022", "IUPAC 1982"

# ---------------------------------------------------------------------------------------------------------------------- mathematical
MATH = [
    ("pi", "π", "pi", "Ratio of a circle's circumference to its diameter.", ["circle_area", "circle_circ", "sphere_vol", "sphere_area", "cyl_vol"], mp.mp.pi),
    ("euler_e", "e", "Euler's number", "Base of the natural logarithm, lim (1 + 1/n)ⁿ.", ["expgrowth", "firstorder"], mp.mp.e),
    ("tau", "τ", "tau", "The full-circle constant 2π.", ["circle_circ"], 2 * mp.mp.pi),
    ("phi", "φ", "golden ratio", "The positive root of x² = x + 1, (1 + √5)/2.", [], mp.mp.phi),
    ("sqrt2", "√2", "square root of 2", "Length of the diagonal of a unit square (Pythagoras).", ["pythag"], mp.sqrt(2)),
    ("ln2", "ln 2", "natural logarithm of 2", "Used for doubling times and half-lives.", ["doubling", "halflife"], mp.log(2)),
    ("ln10", "ln 10", "natural logarithm of 10", "Converts between natural and common logarithms.", ["ph"], mp.log(10)),
    ("gammaE", "γ", "Euler–Mascheroni constant", "Limit of the harmonic series minus ln n.", [], mp.euler),
    ("catalan", "G", "Catalan's constant", "Σ (−1)ᵏ/(2k+1)², about 0.9159…", [], mp.catalan),
    ("zeta3", "ζ(3)", "Apéry's constant", "The Riemann zeta function at 3; Roger Apéry proved it irrational.", [], mp.apery),
    ("khinchin", "K₀", "Khinchin's constant", "The geometric mean of continued-fraction coefficients of almost every real number.", [], mp.khinchin),
    ("glaisher", "A", "Glaisher–Kinkelin constant", "Appears in asymptotics of the hyperfactorial and in sums of k ln k.", [], mp.glaisher),
]
for key, sym, name, description, apps, val in MATH:
    s = mp.nstr(val, 50, strip_zeros=False)
    constants[key] = entry(name, sym, s, None, True, "", "mathematical", "mathematical", description, apps,
                           "Mathematical definition; digits computed with mpmath at 80 digits and stored to 50", "n/a",
                           note="Irrational (or not known to be rational): the number is defined exactly, and the value is shown to 50 significant digits.", sigfigs=50)

# ---------------------------------------------------------------------------------------------------------------------- astronomical
au = D("149597870700")
jyear = D("31557600")
ly = D("299792458") * jyear
parsec = D(mp.nstr(648000 / mp.mp.pi * 149597870700, 40, strip_zeros=False))
g_val, g_unc = D(str(sc.physical_constants["Newtonian constant of gravitation"][0])), D(str(sc.physical_constants["Newtonian constant of gravitation"][2]))
gm_sun, gm_earth = D("1.3271244e20"), D("3.986004e14")
msun, mearth = gm_sun / g_val, gm_earth / g_val
rel = g_unc / g_val

ASTRO = [
    ("au", "au", "astronomical unit", "m", str(au), None, "exact", IAU12, "IAU 2012 B2", "Exactly 149 597 870 700 m, by IAU definition (no longer a measured distance).", ["gravitation"], 12),
    ("jyear", "a", "Julian year", "s", str(jyear), None, "exact", "IAU (Julian year = 365.25 days of 86 400 s)", "IAU", "Exactly 365.25 days.", [], 8),
    ("ly", "ly", "light-year", "m", str(ly), None, "exact", "IAU: the distance light travels in one Julian year in vacuum, c × 1 a", "IAU", "Exactly 9 460 730 472 580 800 m.", ["wave"], 16),
    ("pc", "pc", "parsec", "m", clean(parsec), None, "exact_derived", IAU15, "IAU 2015 B2", "Exactly (648 000/π) au: irrational, shown to 40 digits.", [], 40),
    ("GMsun", "GM☉", "nominal solar mass parameter", "m^3/s^2", "1.3271244e20", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU: the best measured GM☉ is slightly different, and is known far better than G or M☉ alone.", ["gravitation", "escape"], 8),
    ("Rsun", "R☉", "nominal solar radius", "m", "6.957e8", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU, equal to 695 700 km.", [], 4),
    ("Lsun", "L☉", "nominal solar luminosity", "W", "3.828e26", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU.", ["stefan"], 4),
    ("Tsun", "T☉", "nominal solar effective temperature", "K", "5772", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU.", ["stefan"], 4),
    ("Ssun", "S☉", "nominal total solar irradiance", "W/m^2", "1361", None, "nominal", IAU15, "IAU 2015 B3", "Nominal irradiance at one au, a conversion constant defined by the IAU; the real value varies with the solar cycle.", ["stefan"], 4),
    ("GMearth", "GM⊕", "nominal terrestrial mass parameter", "m^3/s^2", "3.986004e14", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU.", ["gravitation", "escape"], 7),
    ("Rearth_eq", "R⊕e", "nominal equatorial radius of Earth", "m", "6.3781e6", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU, 6378.1 km.", [], 5),
    ("Rearth_pol", "R⊕p", "nominal polar radius of Earth", "m", "6.3568e6", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU, 6356.8 km.", [], 5),
    ("GMjup", "GMJ", "nominal Jovian mass parameter", "m^3/s^2", "1.2668653e17", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU.", ["gravitation"], 8),
    ("Rjup_eq", "RJe", "nominal equatorial radius of Jupiter", "m", "7.1492e7", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU, 71 492 km.", [], 5),
    ("Rjup_pol", "RJp", "nominal polar radius of Jupiter", "m", "6.6854e7", None, "nominal", IAU15, "IAU 2015 B3", "A conversion constant defined by the IAU, 66 854 km.", [], 5),
]
for key, sym, name, unit, value, unc, kind, source, edition, description, apps, sf in ASTRO:
    constants[key] = entry(name, sym, value, unc, True, unit, "astronomical", kind, description, apps, source, edition,
                           sigfigs=40 if kind == "exact_derived" else sigfigs_exact(value),
                           note=("Conventional definition, not a best estimate." if kind == "nominal" else None))
def _sci(x, n):
    return format(float(x), f".{n}e").replace("e+", "e")


_ms, _msu = _sci(msun, 6), _sci(msun * rel, 1)
_me, _meu = _sci(mearth, 6), _sci(mearth * rel, 1)
constants["Msun"] = entry("solar mass", "M☉", _ms, _msu, False, "kg", "astronomical", "derived",
                          "Derived as GM☉(nominal)/G. The uncertainty comes only from G, so it is far larger than the uncertainty of GM☉ itself.", ["gravitation"],
                          "Derived from IAU 2015 B3 (GM☉ nominal) and CODATA 2022 (G)", "IAU 2015 B3 + CODATA 2022", note="Model-dependent: changes whenever the accepted value of G changes.", sigfigs=sigfigs_measured(_ms, _msu))
constants["Mearth"] = entry("Earth mass", "M⊕", _me, _meu, False, "kg", "astronomical", "derived",
                            "Derived as GM⊕(nominal)/G. The uncertainty comes only from G.", ["gravitation"],
                            "Derived from IAU 2015 B3 (GM⊕ nominal) and CODATA 2022 (G)", "IAU 2015 B3 + CODATA 2022", note="Model-dependent: changes whenever the accepted value of G changes.", sigfigs=sigfigs_measured(_me, _meu))

# ---------------------------------------------------------------------------------------------------------------------- engineering reference
inch, foot, pound, g_n = D("0.0254"), D("0.3048"), D("0.45359237"), D("9.80665")
hp = foot * 550 * pound * g_n
ENG = [
    ("T0C", "0 °C", "zero of the Celsius scale", "K", "273.15", "convention", "SI Brochure (9th ed.), definition of the degree Celsius", "SI 2019", "Exactly 273.15 K. A temperature difference of 1 °C is exactly 1 K.", [], "Convention"),
    ("inch", "in", "inch", "m", str(inch), "exact", SP811, "NIST SP 811", "International inch, exactly 25.4 mm (1959 agreement).", [], None),
    ("foot", "ft", "foot", "m", str(foot), "exact", SP811, "NIST SP 811", "International foot, exactly 0.3048 m.", [], None),
    ("lb", "lb", "pound (avoirdupois)", "kg", str(pound), "exact", SP811, "NIST SP 811", "International avoirdupois pound, exactly 0.453 592 37 kg (1959 agreement).", ["weight"], None),
    ("cal_th", "cal_th", "thermochemical calorie", "J", "4.184", "exact", SP811, "NIST SP 811", "Exactly 4.184 J: the calorie of thermochemical tables.", ["heat"], None),
    ("cal_IT", "cal_IT", "International Table calorie", "J", "4.1868", "exact", SP811, "NIST SP 811", "Exactly 4.1868 J (International Steam Table calorie).", ["heat"], None),
    ("kWh", "kW·h", "kilowatt-hour", "J", "3.6e6", "exact", SP811, "NIST SP 811", "Exactly 3.6 MJ.", ["elec_power"], None),
    ("bar", "bar", "bar", "Pa", "1e5", "exact", SP811, "NIST SP 811", "Exactly 100 kPa.", ["pressure"], None),
    ("mmHg", "mmHg", "conventional millimetre of mercury", "Pa", "133.322387415", "convention", SP811, "NIST SP 811", "Exactly 13 595.1 kg/m³ × g_n × 1 mm.", ["pressure"], None),
    ("hp", "hp", "horsepower (mechanical)", "W", format(hp.normalize(), "f"), "exact", SP811, "NIST SP 811", "Exactly 550 ft·lbf/s, computed from the exact foot, pound and standard gravity.", ["power"], None),
    ("T_isa", "T₀", "ISA sea-level temperature", "K", "288.15", "convention", "ISO 2533:1975 Standard Atmosphere", "ISO 2533:1975", "Reference temperature of the International Standard Atmosphere at mean sea level (15 °C). A reference, not the weather.", [], None),
    ("rho_isa", "ρ₀", "ISA sea-level air density", "kg/m^3", "1.225", "convention", "ISO 2533:1975 Standard Atmosphere", "ISO 2533:1975", "Reference air density of the International Standard Atmosphere at mean sea level.", ["density"], None),
    ("lapse_isa", "L", "ISA temperature lapse rate", "K/m", "0.0065", "convention", "ISO 2533:1975 Standard Atmosphere", "ISO 2533:1975", "Temperature falls by 6.5 K per kilometre in the ISA troposphere.", [], None),
]
for key, sym, name, unit, value, kind, source, edition, description, apps, _ in ENG:
    constants[key] = entry(name, sym, value, None, True, unit, "engineering", kind, description, apps, source, edition,
                           note="Exact by definition or by an exact combination of defined values." if kind == "exact" else "Exact by convention: an agreed reference value, not a measurement.",
                           sigfigs=sigfigs_exact(value))

out = {"meta": {
    "name": "SciCal constants library",
    "version": "CODATA 2022",
    "source": "NIST SRD 121; Mohr, Newell, Taylor, Tiesinga, Rev. Mod. Phys. 97, 025002 (2025)",
    "transcribed_from": f"scipy.constants (scipy {scipy.__version__})",
    "verified_current": "CODATA 2022 (NIST release 9.0, 9 May 2024) is the newest edition listed at pml.nist.gov/cuu/Reference/versioncon.shtml; checked 2026-10-28.",
    "note": "Constants listed with no uncertainty are exact. Values are decimal strings; SciCal reads them as exact decimals. "
            "Changing an entry changes every calculation that uses it, so tests/test_constants.py pins the values: an update must be deliberate.",
    "categories": CATEGORIES,
    "editions": {"CODATA 2022": "Fundamental physical constants", "IAU 2012 B2": "Astronomical unit", "IAU 2015 B3": "Nominal solar and planetary conversion constants",
                 "NIST SP 811": "Conversion factors", "ISO 2533:1975": "Standard atmosphere"},
}, "constants": constants}
path = pathlib.Path(__file__).resolve().parent.parent / "scical" / "data" / "constants.json"
path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
print("wrote", path, len(constants))
