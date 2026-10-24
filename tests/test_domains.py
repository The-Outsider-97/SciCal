"""Subject calculations checked against values worked out independently (textbook figures or hand arithmetic), not against SciCal's own output."""
import math
import unittest

from scical.services.tasks import run


def op(domain: str, name: str, **params):
    r = run({"kind": "domain", "domain": domain, "op": name, "params": params, "settings": {}})
    return r


def ok(domain: str, name: str, **params):
    r = op(domain, name, **params)
    assert r.get("ok"), r
    return r


def v(x) -> float:
    return float(x["value"])


class ChemistryTests(unittest.TestCase):
    def test_molar_masses(self):
        for formula, expected in (("H2O", 18.015), ("NaCl", 58.443), ("Ca(OH)2", 74.092), ("C6H12O6", 180.156), ("CuSO4.5H2O", 249.685), ("Fe2(SO4)3", 399.858)):
            with self.subTest(formula):
                self.assertAlmostEqual(v(ok("chemistry", "molar_mass", formula=formula)["molarMass"]), expected, delta=0.01)

    def test_balancing(self):
        cases = {
            "C3H8 + O2 -> CO2 + H2O": [1, 5, 3, 4],
            "Fe + O2 -> Fe2O3": [4, 3, 2],
            "KMnO4 + HCl -> KCl + MnCl2 + H2O + Cl2": [2, 16, 2, 2, 8, 5],
            "Cu + Ag+ -> Cu^2+ + Ag": [1, 2, 1, 2],
        }
        for eq, coeffs in cases.items():
            with self.subTest(eq):
                r = ok("chemistry", "balance", equation=eq)
                self.assertEqual(r["coefficients"], coeffs)
                self.assertTrue(r["verification"]["balanced"])

    def test_ambiguous_charge_is_refused_not_guessed(self):
        r = op("chemistry", "balance", equation="Cu + Ag+ -> Cu2+ + Ag")
        self.assertFalse(r["ok"])

    def test_unbalanceable_is_reported(self):
        r = op("chemistry", "balance", equation="H2 -> O2")
        self.assertFalse(r["ok"])

    def test_stoichiometry_limiting_reagent(self):
        r = ok("chemistry", "stoichiometry", equation="2H2 + O2 -> 2H2O", given=[{"species": "H2", "amount": "2 g"}, {"species": "O2", "amount": "32 g"}], target="H2O")
        self.assertEqual(r["limiting"], "H2")
        self.assertAlmostEqual(v(r["theoreticalYield"]), 17.87, delta=0.05)     # 2.016 g H2 -> 2 * 18.015 g/mol * (2/2.016) mol

    def test_empirical_formula(self):
        r = ok("chemistry", "empirical", composition={"C": "40.0", "H": "6.7", "O": "53.3"}, basis="percent")
        self.assertEqual(r["empirical"], "CH2O")
        r = ok("chemistry", "empirical", composition={"C": "40.0", "H": "6.7", "O": "53.3"}, basis="percent", molarMass="180 g/mol")
        self.assertEqual(r["molecular"], "C6H12O6")

    def test_solutions(self):
        self.assertAlmostEqual(v(ok("chemistry", "solution", mode="molarity", formula="NaCl", mass="5.85 g", volume="250 mL")["concentration"]), 0.4004, delta=0.002)  # mol/L

    def test_ph(self):
        self.assertAlmostEqual(v(ok("chemistry", "acid_base", mode="strong_acid", concentration="0.01")["pH"]), 2.0, places=6)
        self.assertAlmostEqual(v(ok("chemistry", "acid_base", mode="strong_base", concentration="0.001")["pH"]), 11.0, places=6)
        # 0.10 M acetic acid, Ka 1.8e-5: x = (-Ka + sqrt(Ka^2 + 4 Ka c)) / 2
        x = (-1.8e-5 + math.sqrt(1.8e-5 ** 2 + 4 * 1.8e-5 * 0.10)) / 2
        self.assertAlmostEqual(v(ok("chemistry", "acid_base", mode="weak_acid", concentration="0.10", ka="1.8e-5")["pH"]), -math.log10(x), places=6)
        self.assertAlmostEqual(v(ok("chemistry", "acid_base", mode="buffer", pka="4.76", acid="0.1", base="0.1")["pH"]), 4.76, places=6)

    def test_titration_equivalence(self):
        r = ok("chemistry", "acid_base", mode="titration", acidConcentration="0.1", acidVolume="25 mL", baseConcentration="0.1", strongAcid=True)
        self.assertAlmostEqual(v(r["equivalenceVolume"]), 25.0, places=6)
        self.assertAlmostEqual(v(r["pHAtEquivalence"]), 7.0, places=3)

    def test_gas_laws(self):
        # one mole at 0 degC and 1 atm occupies 22.414 L
        self.assertAlmostEqual(v(ok("chemistry", "gas", mode="ideal", P="101.325 kPa", n="1 mol", T="273.15 K")["result"]), 22.414, places=3)
        self.assertAlmostEqual(v(ok("chemistry", "gas", mode="ideal", P="1 atm", n="1 mol", T="0 degC")["result"]), 22.414, places=3)
        self.assertAlmostEqual(v(ok("chemistry", "gas", mode="ideal", V="22.414 L", n="1 mol", T="273.15 K")["result"]), 101.325, delta=0.01)
        self.assertAlmostEqual(v(ok("chemistry", "gas", mode="ideal", P="101.325 kPa", V="22.414 L", T="273.15 K")["result"]), 1.0, places=3)
        # molar mass from density: M = dRT/P ~ 28 g/mol for nitrogen (1.25 g in 1 L at STP)
        self.assertAlmostEqual(v(ok("chemistry", "gas", mode="molar_mass", mass="1.25 g", P="101.325 kPa", V="1 L", T="273.15 K")["molarMass"]), 28.02, delta=0.05)

    def test_calorimetry_and_gibbs(self):
        q = ok("chemistry", "thermo", mode="calorimetry", mass="100 g", specificHeat="4.184 J/(g*K)", T1="20 degC", T2="30 degC")
        self.assertAlmostEqual(v(q["heat"]), 4184.0, places=3)
        g = ok("chemistry", "thermo", mode="gibbs", deltaH="-92 kJ/mol", deltaS="-199 J/(mol*K)", T="298 K")   # Haber process
        self.assertAlmostEqual(v(g["deltaG"]), -92 + 298 * 0.199, places=3)
        self.assertAlmostEqual(math.log(v(g["equilibriumConstant"])), -v(g["deltaG"]) * 1000 / (8.314462618 * 298), places=3)

    def test_ice_table(self):
        r = ok("chemistry", "equilibrium", reaction="N2O4 <-> 2NO2", K="0.36", initial={"N2O4": "0.10"})
        x = v(r["x"])
        self.assertAlmostEqual((2 * x) ** 2 / (0.10 - x), 0.36, places=6)

    def test_element_lookup(self):
        e = ok("chemistry", "element", element="Fe")["element"]
        self.assertEqual((e["z"], e["symbol"], e["name"]), (26, "Fe", "Iron"))
        self.assertEqual(ok("chemistry", "periodic_table")["count"], 118)


class BiologyTests(unittest.TestCase):
    def test_sequence(self):
        r = ok("biology", "sequence", sequence="ATGCGC", kind="dna")
        self.assertAlmostEqual(v(r["gcContent"]), 100 * 4 / 6, places=6)
        self.assertEqual(r["reverseComplement"], "GCGCAT")
        self.assertEqual(r["complement"], "TACGCG")

    def test_translation(self):
        self.assertEqual(ok("biology", "translate", sequence="ATGGCCATTGTAATGGGCCGC", frame="1", strand="+")["protein"], "MAIVMGR")

    def test_restriction_sites(self):
        r = ok("biology", "restriction", sequence="GGATCCAAGCTTGAATTCGGATCC", enzymes="EcoRI BamHI")
        by = {e["enzyme"]: e for e in r["enzymes"]}
        self.assertEqual(by["EcoRI"]["count"], 1)
        self.assertEqual(by["BamHI"]["count"], 2)

    def test_hardy_weinberg(self):
        r = ok("biology", "hardy_weinberg", p="0.6")
        self.assertAlmostEqual(v(r["q"]), 0.4, places=9)
        self.assertAlmostEqual(v(r["expected"]["AA"]), 0.36, places=9)
        self.assertAlmostEqual(v(r["expected"]["Aa"]), 0.48, places=9)
        self.assertAlmostEqual(v(r["expected"]["aa"]), 0.16, places=9)
        obs = ok("biology", "hardy_weinberg", observed={"AA": "36", "Aa": "48", "aa": "16"})
        self.assertAlmostEqual(v(obs["chiSquare"]), 0.0, places=6)
        self.assertTrue(obs["inEquilibrium"])

    def test_punnett_dihybrid(self):
        r = ok("biology", "punnett", parent1="AaBb", parent2="AaBb")
        self.assertEqual(r["total"], 16)
        self.assertEqual(sorted((p["count"] for p in r["phenotypes"]), reverse=True), [9, 3, 3, 1])
        self.assertEqual(r["phenotypeRatio"], "9:3:3:1")

    def test_growth(self):
        r = ok("biology", "growth", mode="exponential", n0="1000", nt="64000", time="6 h")
        self.assertAlmostEqual(v(r["doublingTime"]), 1.0, places=6)                    # 64x in 6 h is 6 doublings
        self.assertAlmostEqual(v(r["rate"]), math.log(2), places=6)

    def test_michaelis_menten(self):
        r = ok("biology", "michaelis_menten", mode="velocity", vmax="10", km="2", substrate="2")
        self.assertAlmostEqual(v(r["velocity"]), 5.0, places=9)
        # exact data from Vmax 10, Km 2 must be recovered by the fit
        data = [[s, 10 * s / (2 + s)] for s in (0.5, 1, 2, 4, 8, 16)]
        fit = ok("biology", "michaelis_menten", mode="fit", data=data)
        self.assertAlmostEqual(v(fit["vmax"]), 10.0, places=4)
        self.assertAlmostEqual(v(fit["km"]), 2.0, places=4)

    def test_colony_count(self):
        r = ok("biology", "lab_dilution", mode="cfu", colonies="150", dilution="1e6", volumePlated="0.1 mL")
        self.assertAlmostEqual(v(r["cfuPerMl"]), 1.5e9, delta=1e3)

    def test_protein_mass(self):
        r = ok("biology", "protein", sequence="GGG")                                    # glycine residue 57.0215 each + water
        self.assertAlmostEqual(v(r["molecularWeight"]), 3 * 57.0519 + 18.0153, delta=0.05)


class MeasurementTests(unittest.TestCase):
    def test_significant_figures(self):
        self.assertEqual(ok("measurement", "sig_figs", mode="count", value="0.00450")["sigFigs"], 3)
        self.assertEqual(ok("measurement", "sig_figs", mode="count", value="1200")["sigFigs"], 2)
        self.assertEqual(ok("measurement", "sig_figs", mode="count", value="1.200e3")["sigFigs"], 4)
        add = ok("measurement", "sig_figs", mode="arithmetic", operation="add", values=["12.11", "18.0", "1.013"])
        self.assertEqual(add["result"], "31.1")                                           # limited by 18.0 (one decimal place)

    def test_percent_error(self):
        r = ok("measurement", "percent_error", mode="error", experimental="9.52", accepted="9.81")
        self.assertAlmostEqual(v(r["percentError"]), abs(9.52 - 9.81) / 9.81 * 100, places=6)

    def test_repeated_measurements(self):
        r = ok("measurement", "repeated", values=[9.81, 9.79, 9.84, 9.8, 9.83])
        self.assertAlmostEqual(v(r["mean"]), 9.814, places=9)
        self.assertAlmostEqual(v(r["standardDeviation"]), 0.0207364, places=6)
        self.assertAlmostEqual(v(r["median"]), 9.81, places=9)

    def test_error_propagation(self):
        r = ok("measurement", "uncertainty", expression="m / V", variables={"m": {"value": "2.50", "uncertainty": "0.05"}, "V": {"value": "1.00", "uncertainty": "0.02"}}, method="quadrature")
        self.assertAlmostEqual(v(r["value"]), 2.5, places=9)
        self.assertAlmostEqual(v(r["uncertainty"]), 2.5 * math.sqrt(0.02 ** 2 + 0.02 ** 2), places=9)

    def test_calibration_recovers_a_line(self):
        r = ok("measurement", "calibration", data=[[0, 1], [1, 3], [2, 5], [3, 7]], unknownResponses=[6.0])
        self.assertAlmostEqual(v(r["slope"]), 2.0, places=9)
        self.assertAlmostEqual(v(r["intercept"]), 1.0, places=9)
        self.assertAlmostEqual(v(r["rSquared"]), 1.0, places=9)
        self.assertAlmostEqual(v(r["unknown"]["x"]), 2.5, places=9)

    def test_unit_conversion(self):
        self.assertAlmostEqual(v(ok("measurement", "convert", value="12", **{"from": "in", "to": "cm"})["result"]), 30.48, places=9)
        self.assertAlmostEqual(v(ok("measurement", "convert", value="100", **{"from": "degC", "to": "degF"})["result"]), 212.0, places=9)
        self.assertAlmostEqual(v(ok("measurement", "convert", value="0", **{"from": "K", "to": "degC"})["result"]), -273.15, places=9)
        self.assertAlmostEqual(v(ok("measurement", "convert", value="1", **{"from": "mi", "to": "km"})["result"]), 1.609344, places=9)

    def test_incompatible_units_are_refused(self):
        self.assertFalse(op("measurement", "convert", value="1", **{"from": "m", "to": "s"})["ok"])

    def test_dimensions(self):
        r = ok("measurement", "dimensions", expressions=["5 m/s * 2 s", "3 kg * 9.8 m/s^2"])
        self.assertEqual([e["dimension"] for e in r["expressions"]], ["length", "force"])


class FormulaTests(unittest.TestCase):
    def test_solve_mass_energy(self):
        r = ok("formulas", "formula_solve", equation="E = m*c^2", solveFor="E", values={"m": "2 kg", "c": "299792458 m/s"}, units={"E": "J", "m": "kg", "c": "m/s"}, outputUnit="J")
        self.assertAlmostEqual(v(r["result"]) / (2 * 299792458 ** 2), 1.0, places=12)

    def test_solve_for_another_variable(self):
        r = ok("formulas", "formula_solve", equation="F = m*a", solveFor="a", values={"F": "10 N", "m": "2 kg"}, units={"F": "N", "m": "kg", "a": "m/s^2"}, outputUnit="m/s^2")
        self.assertAlmostEqual(v(r["result"]), 5.0, places=9)

    def test_dimensional_check_catches_a_wrong_equation(self):
        good = ok("formulas", "formula_analyze", equation="F = m*a", units={"F": "N", "m": "kg", "a": "m/s^2"})
        self.assertTrue(good["dimensional"]["consistent"])
        bad = op("formulas", "formula_analyze", equation="F = m*v", units={"F": "N", "m": "kg", "v": "m/s"})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["error"]["code"], "dimension_error")

    def test_library_search(self):
        r = ok("formulas", "formula_library", query="kinetic")
        self.assertTrue(any(f["id"] == "kinetic" for f in r["formulas"]))


class ErrorsAreAnswersTests(unittest.TestCase):
    def test_bad_input_gives_a_message_not_a_crash(self):
        for domain, name, params in (("chemistry", "molar_mass", {"formula": "Xx2"}), ("chemistry", "molar_mass", {}), ("biology", "translate", {"sequence": "ATGZZZ"}),
                                     ("measurement", "repeated", {"values": []}), ("chemistry", "nope", {}), ("nope", "x", {})):
            with self.subTest((domain, name)):
                r = op(domain, name, **params)
                self.assertFalse(r["ok"])
                self.assertTrue(r["error"]["message"])


if __name__ == "__main__":
    unittest.main()
