"""The input forms of the subject workspaces, described as data.

The web client builds every Chemistry, Biology, Measurement and Formula form from this catalogue, so the page can never ask for a
parameter the backend does not read. Each operation carries a worked ``example``; ``tests/test_forms.py`` runs every example through the
real operation, which keeps this file and the operations in step.

Field kinds
    text, textarea, number (a number or an expression such as 1e-14 or 2/3), quantity (a number with a unit, ``unit`` is the default
    unit), select, bool, list (numbers separated by spaces, commas or lines), pairs (one "x y" pair per line), table (rows of cells;
    ``shape`` "array" gives a list of objects, "object" gives {first-column: {other columns}} or {first-column: value}).
``when`` limits a field to certain values of another field, normally ``mode``.
"""
from __future__ import annotations

from typing import Any


def _f(kind: str, key: str, label: str, **kw: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": kind, "key": key, "label": label}
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


def T(key, label, **kw): return _f("text", key, label, **kw)
def TA(key, label, **kw): return _f("textarea", key, label, **kw)
def N(key, label, **kw): return _f("number", key, label, **kw)
def Q(key, label, unit, **kw): return _f("quantity", key, label, unit=unit, **kw)
def B(key, label, **kw): return _f("bool", key, label, **kw)
def L(key, label, **kw): return _f("list", key, label, **kw)
def P(key, label, **kw): return _f("pairs", key, label, **kw)


def S(key, label, options, **kw):
    return _f("select", key, label, options=[{"value": v, "label": t} for v, t in options], **kw)


def TB(key, label, columns, shape="array", **kw):
    return _f("table", key, label, columns=[{"key": k, "label": t, **({"placeholder": p} if p else {})} for k, t, p in columns], shape=shape, **kw)


def op(oid: str, title: str, summary: str, fields: list, example: dict, **kw: Any) -> dict[str, Any]:
    return {"id": oid, "title": title, "summary": summary, "fields": fields, "example": example, **kw}


def w(*modes: str) -> dict[str, list[str]]:
    return {"mode": list(modes)}


# ---------------------------------------------------------------------------------------------------------------------- chemistry
CHEMISTRY = [
    op("periodic_table", "Periodic table", "Browse and search the elements; click one for its properties and isotopes.",
       [T("query", "Search", placeholder="name, symbol, number or category")], {"query": "carbon"}, view="periodic"),
    op("element", "Element", "Properties, atomic weight and isotopes of one element.",
       [T("element", "Element", placeholder="Fe, iron or 26", required=True)], {"element": "Fe"}),
    op("molar_mass", "Molar mass", "Molar mass and percent composition of a formula (hydrates, charges and brackets are understood).",
       [T("formula", "Formula", placeholder="Ca(OH)2 or CuSO4·5H2O", required=True)], {"formula": "Ca(OH)2"}),
    op("balance", "Balance an equation", "Balance a chemical equation with integer coefficients (exact rational algebra).",
       [T("equation", "Equation", placeholder="C3H8 + O2 -> CO2 + H2O", required=True)], {"equation": "C3H8 + O2 -> CO2 + H2O"}),
    op("stoichiometry", "Stoichiometry", "Limiting reagent, amounts used and produced, theoretical and percent yield.",
       [T("equation", "Equation", placeholder="N2 + H2 -> NH3", required=True),
        TB("given", "Amounts given", [("species", "Reactant", "N2"), ("amount", "Amount (g or mol)", "28 g"), ("volume", "or volume", "25 mL"), ("concentration", "and concentration", "0.5 mol/L")],
           shape="array", required=True, hint="Give a mass or amount of substance, or a volume together with a concentration."),
        T("target", "Product for the yield", placeholder="NH3"),
        Q("actualYield", "Actual yield", "g")],
       {"equation": "N2 + H2 -> NH3", "given": [{"species": "N2", "amount": "28 g"}, {"species": "H2", "amount": "5 g"}], "target": "NH3", "actualYield": "20 g"}),
    op("empirical", "Empirical formula", "Empirical (and molecular) formula from percent composition or masses.",
       [TB("composition", "Composition", [("element", "Element", "C"), ("value", "Percent or mass", "40.0")], shape="object", required=True),
        S("basis", "Values are", [("percent", "percent by mass"), ("mass", "masses")]),
        Q("molarMass", "Molar mass (optional)", "g/mol")],
       {"composition": {"C": "40.0", "H": "6.7", "O": "53.3"}, "basis": "percent", "molarMass": "180 g/mol"}),
    op("solution", "Solutions", "Molarity, dilution, mass percent, molality, preparation and serial dilutions.",
       [S("mode", "Calculation", [("molarity", "Molarity"), ("dilution", "Dilution C₁V₁ = C₂V₂"), ("prepare", "Prepare a solution"), ("mass_percent", "Mass percent"), ("molality", "Molality"), ("serial", "Serial dilution")]),
        T("formula", "Solute formula", placeholder="NaCl", when=w("molarity", "prepare", "molality"), hint="Needed to convert between mass and moles."),
        Q("moles", "Amount of solute", "mol", when=w("molarity", "molality")),
        Q("mass", "Mass of solute", "g", when=w("molarity")),
        Q("volume", "Volume of solution", "L", when=w("molarity", "prepare")),
        Q("concentration", "Concentration", "mol/L", when=w("molarity", "prepare", "serial")),
        Q("c1", "C₁", "mol/L", when=w("dilution")), Q("v1", "V₁", "mL", when=w("dilution")),
        Q("c2", "C₂", "mol/L", when=w("dilution")), Q("v2", "V₂", "mL", when=w("dilution"), hint="Leave exactly one of the four empty."),
        Q("soluteMass", "Mass of solute", "g", when=w("mass_percent", "molality")),
        Q("solutionMass", "Mass of solution", "g", when=w("mass_percent")),
        Q("solventMass", "Mass of solvent", "g", when=w("mass_percent")),
        Q("density", "Density (optional)", "g/mL", when=w("mass_percent")),
        N("factor", "Dilution factor per step", when=w("serial"), placeholder="10"),
        N("steps", "Number of steps", when=w("serial"), placeholder="6")],
       {"mode": "molarity", "formula": "NaCl", "mass": "5.85 g", "volume": "250 mL"}),
    op("acid_base", "Acids, bases and pH", "pH of strong and weak acids and bases, buffers, conversions and a titration curve.",
       [S("mode", "Calculation", [("strong_acid", "Strong acid"), ("strong_base", "Strong base"), ("weak_acid", "Weak acid"), ("weak_base", "Weak base"), ("buffer", "Buffer (Henderson–Hasselbalch)"),
                                  ("convert", "pH ↔ concentration"), ("titration", "Titration curve (acid + strong base)")]),
        N("concentration", "Concentration (mol/L)", when=w("strong_acid", "strong_base", "weak_acid", "weak_base"), placeholder="0.10"),
        N("protons", "Acidic protons released", when=w("strong_acid"), placeholder="1"),
        N("hydroxides", "Hydroxide ions released", when=w("strong_base"), placeholder="1"),
        N("ka", "Ka", when=w("weak_acid", "buffer", "titration"), placeholder="1.8e-5"), N("pka", "or pKa", when=w("weak_acid", "buffer", "titration"), placeholder="4.74"),
        N("kb", "Kb", when=w("weak_base"), placeholder="1.8e-5"), N("pkb", "or pKb", when=w("weak_base")),
        N("acid", "Acid form HA (mol/L)", when=w("buffer")), N("base", "Base form A⁻ (mol/L)", when=w("buffer")),
        N("addStrongAcid", "Strong acid added (mol/L)", when=w("buffer"), placeholder="0"), N("addStrongBase", "Strong base added (mol/L)", when=w("buffer"), placeholder="0"),
        N("pH", "pH", when=w("convert")), N("pOH", "pOH", when=w("convert")), N("hydronium", "[H₃O⁺] (mol/L)", when=w("convert")), N("hydroxide", "[OH⁻] (mol/L)", when=w("convert"),
                                                                                                                        hint="Give exactly one of the four."),
        N("acidConcentration", "Acid concentration (mol/L)", when=w("titration")), Q("acidVolume", "Acid volume", "mL", when=w("titration")),
        N("baseConcentration", "Base concentration (mol/L)", when=w("titration")), B("strongAcid", "The acid is strong", when=w("titration")),
        N("kw", "Kw (default 1e-14 at 25 °C)", placeholder="1e-14", advanced=True)],
       {"mode": "weak_acid", "concentration": "0.10", "ka": "1.8e-5"}, chart="titration"),
    op("gas", "Gases", "Ideal and van der Waals gas, combined gas law, Dalton, Graham and molar mass from gas data.",
       [S("mode", "Calculation", [("ideal", "Ideal gas PV = nRT"), ("combined", "Combined gas law"), ("dalton", "Dalton's law"), ("graham", "Graham's law"), ("van_der_waals", "van der Waals"), ("molar_mass", "Molar mass from a gas")]),
        Q("P", "Pressure P", "kPa", when=w("ideal", "molar_mass"), hint="For the ideal gas law leave exactly one of P, V, n, T empty."),
        Q("V", "Volume V", "L", when=w("ideal", "molar_mass", "van_der_waals")), Q("n", "Amount n", "mol", when=w("ideal", "van_der_waals")),
        Q("T", "Temperature T", "K", when=w("ideal", "molar_mass", "van_der_waals"), hint="Use K, or write e.g. 25 degC."),
        Q("mass", "Mass of gas", "g", when=w("molar_mass")),
        Q("P1", "P₁", "kPa", when=w("combined")), Q("V1", "V₁", "L", when=w("combined")), Q("T1", "T₁", "K", when=w("combined")),
        Q("P2", "P₂", "kPa", when=w("combined")), Q("V2", "V₂", "L", when=w("combined")), Q("T2", "T₂", "K", when=w("combined"), hint="Leave exactly one of the six empty."),
        TB("gases", "Gases in the mixture", [("name", "Gas", "N2"), ("moles", "Moles", "0.5")], shape="array", when=w("dalton")),
        Q("totalPressure", "Total pressure", "kPa", when=w("dalton")),
        T("formula1", "Gas 1 (formula)", when=w("graham"), placeholder="H2"), T("formula2", "Gas 2 (formula)", when=w("graham"), placeholder="O2"),
        N("M1", "or M₁ (g/mol)", when=w("graham")), N("M2", "or M₂ (g/mol)", when=w("graham")),
        N("a", "a (L²·kPa/mol²)", when=w("van_der_waals"), placeholder="365"), N("b", "b (L/mol)", when=w("van_der_waals"), placeholder="0.0427")],
       {"mode": "ideal", "P": "101.325 kPa", "n": "1 mol", "T": "273.15 K"}),
    op("thermo", "Thermochemistry", "Calorimetry, mixing, Hess's law with formation enthalpies, and Gibbs energy.",
       [S("mode", "Calculation", [("calorimetry", "Heat q = mcΔT"), ("mixing", "Mixing two samples"), ("hess", "Reaction enthalpy (Hess)"), ("gibbs", "Gibbs energy ΔG = ΔH − TΔS")]),
        Q("mass", "Mass", "g", when=w("calorimetry")), Q("specificHeat", "Specific heat", "J/(g*K)", when=w("calorimetry"), placeholder="4.184 J/(g*K)"),
        Q("T1", "Initial temperature", "K", when=w("calorimetry", "mixing", "gibbs"), hint="Write units such as 20 degC."), Q("T2", "Final temperature", "K", when=w("calorimetry")),
        Q("heat", "Heat q", "J", when=w("calorimetry"), hint="Leave one of heat, final temperature or mass empty to solve for it."),
        Q("mass1", "Mass 1", "g", when=w("mixing")), Q("specificHeat1", "Specific heat 1", "J/(g*K)", when=w("mixing")),
        Q("mass2", "Mass 2", "g", when=w("mixing")), Q("specificHeat2", "Specific heat 2", "J/(g*K)", when=w("mixing")),
        T("equation", "Equation", when=w("hess"), placeholder="CH4 + O2 -> CO2 + H2O"),
        TB("formationEnthalpies", "ΔHf° (kJ/mol)", [("species", "Species", "CO2"), ("value", "ΔHf°", "-393.5")], shape="object", when=w("hess"), hint="Elements in their standard state are 0."),
        Q("deltaH", "ΔH", "kJ/mol", when=w("gibbs")), Q("deltaS", "ΔS", "J/(mol*K)", when=w("gibbs")), Q("T", "Temperature", "K", when=w("gibbs"))],
       {"mode": "calorimetry", "mass": "50 g", "T1": "20 degC", "T2": "35 degC"}),
    op("equilibrium", "Equilibrium (ICE table)", "Equilibrium concentrations from K and the starting concentrations.",
       [T("reaction", "Reaction", placeholder="N2O4 <-> 2NO2", required=True), N("K", "K", required=True, placeholder="0.36"),
        TB("initial", "Initial concentrations (mol/L)", [("species", "Species", "N2O4"), ("value", "Concentration", "0.10")], shape="object", required=True)],
       {"reaction": "N2O4 <-> 2NO2", "K": "0.36", "initial": {"N2O4": "0.10"}}),
]

# ---------------------------------------------------------------------------------------------------------------------- biology
SEQ = TA("sequence", "Sequence", placeholder="ATGGCC… (FASTA accepted)", required=True, mono=True, rows=5)
BIOLOGY = [
    op("sequence", "DNA / RNA sequence", "Composition, GC content, complement, transcript, molecular weight and melting temperature.",
       [SEQ, S("kind", "Type", [("auto", "Detect"), ("dna", "DNA"), ("rna", "RNA")]), N("sodium", "Na⁺ (mol/L)", placeholder="0.05", advanced=True)],
       {"sequence": "ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG", "kind": "auto"}),
    op("translate", "Translate", "Translate in any reading frame or on the reverse strand with the standard genetic code.",
       [SEQ, S("frame", "Frame", [("1", "1"), ("2", "2"), ("3", "3")]), S("strand", "Strand", [("+", "Forward (+)"), ("-", "Reverse (−)")]), B("toStop", "Stop at the first stop codon")],
       {"sequence": "ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG", "frame": "1", "strand": "+"}),
    op("orfs", "Open reading frames", "Find ORFs (ATG … stop) on both strands.",
       [SEQ, N("minLength", "Minimum length (amino acids)", placeholder="30"), B("bothStrands", "Search both strands", default=True)],
       {"sequence": "ATGGCCATTGTAATGGGCCGCTGAAAGGGTGCCCGATAG", "minLength": 5, "bothStrands": True}),
    op("restriction", "Restriction sites", "Locate recognition sites of common restriction enzymes and the fragment sizes they give.",
       [SEQ, T("enzymes", "Enzymes (optional)", placeholder="EcoRI BamHI HindIII"), B("circular", "Circular DNA (plasmid)")],
       {"sequence": "GGATCCAAGCTTGAATTCGGATCC", "enzymes": "EcoRI BamHI"}),
    op("protein", "Protein properties", "Mass, isoelectric point, charge at a pH, GRAVY and extinction coefficient.",
       [TA("sequence", "Amino-acid sequence", placeholder="MKTAYIAKQR…", required=True, mono=True, rows=4), N("pH", "pH for the charge", placeholder="7.4")],
       {"sequence": "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ", "pH": "7.4"}),
    op("hardy_weinberg", "Hardy–Weinberg", "Allele and genotype frequencies from p, q, the recessive phenotype or observed counts (with a χ² test).",
       [N("p", "Allele frequency p"), N("q", "Allele frequency q"), N("recessivePhenotype", "Frequency of the recessive phenotype (q²)"),
        TB("observed", "Observed genotype counts", [("genotype", "Genotype", "AA"), ("count", "Count", "")], shape="object", hint="Genotypes AA, Aa and aa.")],
       {"observed": {"AA": "36", "Aa": "48", "aa": "16"}}),
    op("punnett", "Punnett square", "Offspring genotypes and phenotype ratios for up to three genes.",
       [T("parent1", "Parent 1 genotype", placeholder="AaBb", required=True), T("parent2", "Parent 2 genotype", placeholder="AaBb", required=True)],
       {"parent1": "AaBb", "parent2": "Aabb"}, view="punnett"),
    op("growth", "Population growth", "Exponential and logistic growth, doubling time and growth rate.",
       [S("mode", "Model", [("exponential", "Exponential"), ("logistic", "Logistic")]),
        N("n0", "Initial population N₀"), N("nt", "Population N(t)", when=w("exponential")), Q("time", "Time t", "h"),
        N("rate", "Growth rate (per hour)"), Q("doublingTime", "Doubling time", "h", when=w("exponential")), N("capacity", "Carrying capacity K", when=w("logistic"))],
       {"mode": "exponential", "n0": "1000", "nt": "64000", "time": "6 h"}),
    op("michaelis_menten", "Enzyme kinetics", "Reaction velocity with optional inhibition, or fit Vmax and Km to data.",
       [S("mode", "Calculation", [("velocity", "Velocity v([S])"), ("fit", "Fit Vmax and Km")]),
        N("vmax", "Vmax", when=w("velocity")), N("km", "Km", when=w("velocity")), N("substrate", "[S]", when=w("velocity")),
        S("inhibitor", "Inhibitor", [("none", "None"), ("competitive", "Competitive"), ("uncompetitive", "Uncompetitive"), ("noncompetitive", "Non-competitive")], when=w("velocity")),
        N("ki", "Ki", when=w("velocity")), N("inhibitorConcentration", "[I]", when=w("velocity")),
        P("data", "[S] and v (one pair per line)", when=w("fit"), placeholder="0.5 1.2\n1 2.0\n2 3.1\n5 4.4\n10 5.2")],
       {"mode": "fit", "data": [[0.5, 1.2], [1, 2.0], [2, 3.1], [5, 4.4], [10, 5.2]]}, chart="michaelis"),
    op("lab_dilution", "Colony counts and OD", "CFU/mL from plate counts, OD to cell density, serial dilution plans.",
       [S("mode", "Calculation", [("cfu", "CFU per mL"), ("od", "OD → cells/mL"), ("serial", "Serial dilution plan")]),
        N("colonies", "Colonies counted", when=w("cfu")), N("dilution", "Dilution factor", when=w("cfu", "od"), placeholder="1e6"), Q("volumePlated", "Volume plated", "mL", when=w("cfu")),
        N("od", "Optical density", when=w("od")), N("conversion", "Cells/mL per OD", when=w("od"), placeholder="8e8"),
        N("factor", "Dilution factor per step", when=w("serial"), placeholder="10"), N("steps", "Steps", when=w("serial"), placeholder="6"),
        Q("transferVolume", "Transfer volume", "mL", when=w("serial")), Q("finalVolume", "Final volume per tube", "mL", when=w("serial"))],
       {"mode": "cfu", "colonies": "152", "dilution": "1e6", "volumePlated": "0.1 mL"}),
    op("genetic_code", "Genetic code", "The standard codon table and the restriction enzymes known to SciCal.", [], {}, view="code"),
]

# ---------------------------------------------------------------------------------------------------------------------- measurement
MEASUREMENT = [
    op("sig_figs", "Significant figures", "Count, round, and combine measurements with the correct number of significant figures.",
       [S("mode", "Task", [("count", "Count significant figures"), ("round", "Round to n figures"), ("arithmetic", "Arithmetic with measurements")]),
        T("value", "Value", when=w("count", "round"), placeholder="0.004560", hint="Write trailing zeros: 1.20 and 1.2 differ."), N("figures", "Figures", when=w("round")),
        S("operation", "Operation", [("add", "Add"), ("subtract", "Subtract"), ("multiply", "Multiply"), ("divide", "Divide")], when=w("arithmetic")),
        L("values", "Measured values", when=w("arithmetic"), placeholder="12.11 18.0 1.013")],
       {"mode": "arithmetic", "operation": "add", "values": ["12.11", "18.0", "1.013"]}),
    op("uncertainty", "Error propagation", "Propagate measurement uncertainty through a formula (quadrature or worst case) with the contribution of each variable.",
       [T("expression", "Formula", placeholder="m / V", required=True),
        TB("variables", "Variables", [("name", "Name", "m"), ("value", "Value", "2.50"), ("uncertainty", "Uncertainty ±", "0.05")], shape="object", required=True),
        S("method", "Method", [("quadrature", "Quadrature (independent errors)"), ("worst_case", "Worst case")])],
       {"expression": "m / V", "variables": {"m": {"value": "2.50", "uncertainty": "0.05"}, "V": {"value": "1.00", "uncertainty": "0.02"}}, "method": "quadrature"}),
    op("repeated", "Repeated measurements", "Mean, standard deviation, standard error and a confidence interval; compares with an accepted value.",
       [L("values", "Measurements", required=True, placeholder="9.81 9.79 9.84 9.80 9.83"), N("confidence", "Confidence level", placeholder="0.95"), N("accepted", "Accepted value (optional)")],
       {"values": [9.81, 9.79, 9.84, 9.80, 9.83], "accepted": "9.80665"}),
    op("percent_error", "Percent error", "Percent error against an accepted value, or percent difference between two values.",
       [S("mode", "Task", [("error", "Percent error"), ("difference", "Percent difference")]),
        N("experimental", "Experimental value", when=w("error")), N("accepted", "Accepted value", when=w("error")), N("a", "Value A", when=w("difference")), N("b", "Value B", when=w("difference"))],
       {"mode": "error", "experimental": "9.52", "accepted": "9.81"}),
    op("calibration", "Calibration curve", "Least-squares line with uncertainties, R², and the concentration of unknowns with its confidence interval.",
       [P("data", "Standards: x (concentration) and y (response)", required=True, placeholder="0 0.002\n1 0.101\n2 0.198\n4 0.405\n8 0.795"),
        L("unknownResponses", "Responses of the unknown (optional)", placeholder="0.250 0.255 0.248")],
       {"data": [[0, 0.002], [1, 0.101], [2, 0.198], [4, 0.405], [8, 0.795]], "unknownResponses": [0.25, 0.255, 0.248]}, chart="calibration"),
    op("convert", "Convert units", "Convert a value between units of the same dimension (temperature scales handled correctly).",
       [N("value", "Value", required=True), T("from", "From", placeholder="in", required=True), T("to", "To", placeholder="cm", required=True)],
       {"value": "12", "from": "in", "to": "cm"}),
    op("dimensions", "Dimensional analysis", "Check that an expression is dimensionally consistent and reduce its units.",
       [TA("expressions", "Expressions with units (one per line)", placeholder="5 m/s * 2 s\n3 kg * 9.8 m/s^2", required=True, rows=4, lines=True)],
       {"expressions": ["5 m/s * 2 s", "3 kg * 9.8 m/s^2"]}),
    op("units", "Unit catalogue", "All units SciCal understands, by category.", [], {}, view="catalogue"),
    op("constants", "Physical constants", "CODATA 2022 constants with their uncertainties.", [T("query", "Search", placeholder="Planck, speed of light…")], {"query": "planck"}, view="constants"),
]

FORMULAS = [
    op("formula_library", "Formula library", "Search the library of physics, chemistry, biology and maths formulas.", [T("query", "Search"), T("category", "Category")], {"query": "kinetic"}, view="library"),
    op("formula_analyze", "Analyse an equation", "Rearrange an equation for every variable and check its dimensions.",
       [T("equation", "Equation", placeholder="F = m*a", required=True), TB("units", "Units (optional)", [("variable", "Variable", "F"), ("unit", "Unit", "N")], shape="object")],
       {"equation": "F = m*a", "units": {"F": "N", "m": "kg", "a": "m/s^2"}}),
    op("formula_solve", "Solve for a variable", "Solve a library formula or your own equation for one variable, with units.",
       [T("formulaId", "Library formula id", placeholder="kinetic_energy"), T("equation", "or your own equation", placeholder="E = m*c^2"), T("solveFor", "Solve for", required=True),
        TB("values", "Known values", [("variable", "Variable", "m"), ("value", "Value with unit", "2 kg")], shape="object"),
        TB("units", "Units of your equation", [("variable", "Variable", "E"), ("unit", "Unit", "J")], shape="object", advanced=True), T("outputUnit", "Show result in", placeholder="J")],
       {"equation": "E = m*c^2", "solveFor": "E", "values": {"m": "2 kg", "c": "299792458 m/s"}, "units": {"E": "J", "m": "kg", "c": "m/s"}, "outputUnit": "J"}),
]

CATALOGUE = {
    "chemistry": {"title": "Chemistry", "ops": CHEMISTRY},
    "biology": {"title": "Biology", "ops": BIOLOGY},
    "measurement": {"title": "Measurement", "ops": MEASUREMENT},
    "formulas": {"title": "Formulas", "ops": FORMULAS},
}


def catalogue() -> dict[str, Any]:
    return CATALOGUE
