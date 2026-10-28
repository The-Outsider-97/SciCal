"""The constants library, checked against values typed in independently from the published tables (NIST CODATA 2022, IAU, SP 811) and against
the identities that link the constants to each other. Nothing here reads the values back from the generator."""
import hashlib
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import mpmath as mp
from sympy import Rational

from scical.core.units import constants as K
from scical.core.units import parse_unit
from scical.errors import SciCalError
from scical.server.app import Prefs
from scical.services.tasks import run

mp.mp.dps = 80
DATA = Path(__file__).resolve().parent.parent / "scical" / "data"


def dom(op, **params):
    return run({"kind": "domain", "domain": "constants", "op": op, "params": params, "settings": {}})


def calc(text, **settings):
    return run({"kind": "calc", "input": text, "settings": settings, "context": None, "explain": False})


def _m(x):
    return mp.mpf(str(x)) if isinstance(x, Decimal) else mp.mpf(x)


def mpf(key):
    return _m(Decimal(K.get(key).text))


def rel(a, b):
    return abs(_m(a) - _m(b)) / abs(_m(b))


# CODATA 2022 (NIST SRD 121, release 9.0), typed from the published table: key -> (value, standard uncertainty or None for exact)
CODATA_2022 = {
    "c": ("299792458", None), "h": ("6.62607015e-34", None), "e": ("1.602176634e-19", None), "kB": ("1.380649e-23", None), "NA": ("6.02214076e23", None),
    "G": ("6.6743e-11", "1.5e-15"), "me": ("9.1093837139e-31", "2.8e-40"), "mp": ("1.67262192595e-27", "5.2e-37"), "mn": ("1.67492750056e-27", "8.5e-37"),
    "mu": ("1.66053906892e-27", "5.2e-37"), "alpha": ("7.2973525643e-3", "1.1e-12"), "Rinf": ("10973731.568157", "1.2e-5"),
    "a0": ("5.29177210544e-11", "8.2e-21"), "mu0": ("1.25663706127e-6", "2.0e-16"), "eps0": ("8.8541878188e-12", "1.4e-21"),
    "muB": ("9.2740100657e-24", "2.9e-33"), "muN": ("5.0507837393e-27", "1.6e-36"), "Z0": ("376.730313412", "5.9e-8"),
    "lambdaC": ("2.42631023538e-12", "7.6e-22"), "re": ("2.8179403205e-15", "1.3e-24"),
}
# exact values that are not finite decimals, to the digits NIST prints
CODATA_EXACT_DERIVED = {"hbar": "1.054571817646156e-34", "sigma": "5.670374419184429e-8", "b": "2.897771955185172e-3", "Vm": "2.241396954501413e-2",
                        "KJ": "483597848416983.6", "RK": "25812.80745930451", "G0": "7.748091729863649e-5", "Phi0": "2.067833848461929e-15",
                        "c1": "3.741771852192758e-16", "c2": "1.438776877503933e-2"}


class ReferenceValues(unittest.TestCase):
    def test_codata_2022_values_and_uncertainties(self):
        for key, (value, unc) in CODATA_2022.items():
            c = K.get(key)
            self.assertEqual(c.value, Rational(value), key)
            if unc is None:
                self.assertTrue(c.exact, key)
                self.assertIsNone(c.uncertainty, key)
            else:
                self.assertFalse(c.exact, key)
                self.assertEqual(c.uncertainty, Rational(unc), key)
                self.assertEqual(c.kind, "measured", key)
            self.assertEqual(c.edition, "CODATA 2022", key)

    def test_exact_but_not_finite_values(self):
        for key, text in CODATA_EXACT_DERIVED.items():
            c = K.get(key)
            self.assertTrue(c.exact, key)
            self.assertIsNone(c.uncertainty, key)
            self.assertEqual(c.kind, "exact_derived", key)
            self.assertLess(rel(Decimal(c.text), Decimal(text)), mp.mpf("1e-14"), key)

    def test_conventions_and_exact_conversions(self):
        self.assertEqual(K.get("gn").value, Rational("9.80665"))
        self.assertEqual(K.get("atm").value, Rational(101325))
        self.assertEqual(K.get("p0").value, Rational(100000))
        self.assertEqual(K.get("T0C").value, Rational("273.15"))
        self.assertEqual(K.get("inch").value, Rational("0.0254"))
        self.assertEqual(K.get("foot").value, Rational("0.3048"))
        self.assertEqual(K.get("lb").value, Rational("0.45359237"))
        self.assertEqual(K.get("cal_th").value, Rational("4.184"))
        self.assertEqual(K.get("cal_IT").value, Rational("4.1868"))
        self.assertEqual(K.get("kWh").value, Rational(3600000))
        self.assertEqual(K.get("hp").value, Rational("0.3048") * 550 * Rational("0.45359237") * Rational("9.80665"))
        self.assertEqual(K.get("eV").value, K.get("e").value)
        self.assertEqual(K.get("mmHg").value, Rational("13595.1") * Rational("9.80665") / 1000)

    def test_astronomical_definitions(self):
        self.assertEqual(K.get("au").value, Rational(149597870700))
        self.assertEqual(K.get("jyear").value, Rational(365.25) * 86400)
        self.assertEqual(K.get("ly").value, K.get("c").value * K.get("jyear").value)
        self.assertLess(rel(Decimal(K.get("pc").text), mp.mpf(648000) / mp.pi * 149597870700), mp.mpf("1e-38"))
        self.assertEqual(K.get("GMsun").value, Rational("1.3271244e20"))
        self.assertEqual(K.get("Rsun").value, Rational("6.957e8"))
        self.assertEqual(K.get("Lsun").value, Rational("3.828e26"))
        self.assertEqual(K.get("GMearth").value, Rational("3.986004e14"))
        self.assertEqual(K.get("Rjup_eq").value, Rational("7.1492e7"))
        for key in ("GMsun", "Rsun", "Lsun", "Tsun", "GMearth", "GMjup"):
            self.assertEqual(K.get(key).kind, "nominal", key)
            self.assertEqual(K.get(key).edition, "IAU 2015 B3", key)

    def test_derived_masses_carry_only_the_uncertainty_of_G(self):
        msun = K.get("Msun")
        self.assertEqual(msun.kind, "derived")
        self.assertLess(rel(Decimal(msun.text), mpf("GMsun") / mpf("G")), mp.mpf("1e-6"))
        self.assertLess(rel(_m(Decimal(msun.uncertainty_text)) / _m(Decimal(msun.text)), _m(Decimal(K.get("G").uncertainty_text)) / mpf("G")), mp.mpf("1e-1"))
        mearth = K.get("Mearth")
        self.assertLess(rel(Decimal(mearth.text), mpf("GMearth") / mpf("G")), mp.mpf("1e-6"))

    def test_mathematical_constants_against_mpmath(self):
        want = {"pi": mp.pi, "euler_e": mp.e, "tau": 2 * mp.pi, "phi": (1 + mp.sqrt(5)) / 2, "sqrt2": mp.sqrt(2), "ln2": mp.log(2), "ln10": mp.log(10),
                "gammaE": mp.euler, "catalan": mp.catalan, "zeta3": mp.zeta(3), "khinchin": mp.khinchin, "glaisher": mp.glaisher}
        for key, value in want.items():
            c = K.get(key)
            self.assertEqual(c.category, "mathematical", key)
            self.assertTrue(c.exact, key)
            self.assertLess(rel(Decimal(c.text), value), mp.mpf("1e-49"), key)
            self.assertEqual(c.sigfigs, 50, key)
            self.assertEqual(c.unit, "", key)


class Identities(unittest.TestCase):
    """The constants are not independent: each relation below must hold to within the stated uncertainties (or exactly)."""
    def test_exact_relations(self):
        self.assertEqual(K.get("R").value, K.get("NA").value * K.get("kB").value)
        self.assertEqual(K.get("F").value, K.get("NA").value * K.get("e").value)
        tol = mp.mpf("1e-38")
        h, c, e, k = mpf("h"), mpf("c"), mpf("e"), mpf("kB")
        self.assertLess(rel(mpf("hbar"), h / (2 * mp.pi)), tol)
        self.assertLess(rel(mpf("sigma"), 2 * mp.pi ** 5 * k ** 4 / (15 * h ** 3 * c ** 2)), tol)
        self.assertLess(rel(mpf("KJ"), 2 * e / h), tol)
        self.assertLess(rel(mpf("RK"), h / e ** 2), tol)
        self.assertLess(rel(mpf("G0"), 2 * e ** 2 / h), tol)
        self.assertLess(rel(mpf("Phi0"), h / (2 * e)), tol)
        self.assertLess(rel(mpf("c1"), 2 * mp.pi * h * c ** 2), tol)
        self.assertLess(rel(mpf("c2"), h * c / k), tol)
        self.assertLess(rel(mpf("Vm"), mpf("R") * mp.mpf("273.15") / 101325), tol)
        self.assertLess(rel(mpf("b"), mpf("c2") / mp.mpf("4.965114231744276303698759")), mp.mpf("1e-20"))

    def test_relations_within_measurement_uncertainty(self):
        c, h, e, me = mpf("c"), mpf("h"), mpf("e"), mpf("me")
        alpha, eps0, mu0, hbar = mpf("alpha"), mpf("eps0"), mpf("mu0"), mpf("hbar")
        self.assertLess(abs(eps0 * mu0 * c ** 2 - 1), mp.mpf("2e-9"))
        self.assertLess(rel(mpf("Z0"), mu0 * c), mp.mpf("2e-9"))
        self.assertLess(rel(alpha, e ** 2 / (4 * mp.pi * eps0 * hbar * c)), mp.mpf("2e-9"))
        self.assertLess(rel(mpf("Rinf"), alpha ** 2 * me * c / (2 * h)), mp.mpf("2e-9"))
        self.assertLess(rel(mpf("a0"), hbar / (alpha * me * c)), mp.mpf("2e-9"))
        self.assertLess(rel(mpf("mpme"), mpf("mp") / me), mp.mpf("2e-9"))
        self.assertLess(rel(mpf("muB"), e * hbar / (2 * me)), mp.mpf("2e-9"))
        self.assertLess(rel(mpf("lambdaC"), h / (me * c)), mp.mpf("2e-9"))
        self.assertLess(rel(mpf("Eh"), 2 * mpf("Rinf") * h * c), mp.mpf("2e-9"))


class Structure(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads((DATA / "constants.json").read_text(encoding="utf-8"))
        self.table = K.constants()

    def test_every_entry_is_complete_and_consistent(self):
        cats = K.categories()
        self.assertEqual(set(cats), {"mathematical", "physical", "chemical", "astronomical", "engineering"})
        for key, c in self.table.items():
            for field in ("name", "symbol", "description", "source", "edition", "category", "kind"):
                self.assertTrue(getattr(c, field), f"{key}.{field}")
            self.assertIn(c.category, cats, key)
            self.assertIn(c.kind, K.KINDS, key)
            if c.exact:
                self.assertIsNone(c.uncertainty, key)
                self.assertIn(c.kind, ("exact", "exact_derived", "mathematical", "nominal", "convention"), key)
            else:
                self.assertIsNotNone(c.uncertainty, key)
                self.assertGreater(c.uncertainty, 0, key)
                self.assertLess(c.uncertainty / abs(c.value), Rational(1, 100), key)
                self.assertIn(c.kind, ("measured", "derived"), key)

    def test_units_parse_and_have_a_dimension(self):
        for key, c in self.table.items():
            if c.unit:
                self.assertEqual(c.dimension, parse_unit(c.unit).dim.name, key)
                self.assertNotEqual(c.dimension, "dimensionless", key)
            else:
                self.assertEqual(c.dimension, "dimensionless", key)
        self.assertEqual(self.table["c"].dimension, "speed")
        self.assertEqual(self.table["h"].dimension, "length^2 · mass · time^-1")
        self.assertEqual(self.table["gn"].dimension, "acceleration")
        self.assertEqual(self.table["atm"].dimension, "pressure")
        for key in ("alpha", "mpme", "ge"):
            self.assertEqual(self.table[key].dimension, "dimensionless")

    def test_significant_figures_recomputed(self):
        for key, c in self.table.items():
            v = Decimal(c.text)
            if c.kind == "measured" or c.kind == "derived":
                place = Decimal(c.uncertainty_text).adjusted() - 1
                self.assertEqual(c.sigfigs, max(1, v.adjusted() - place + 1), key)
            elif c.kind in ("exact", "nominal", "convention"):
                digits = v.as_tuple().digits
                n = len(digits)
                while n > 1 and digits[n - 1] == 0:
                    n -= 1
                self.assertEqual(c.sigfigs, n, key)
            elif c.kind == "exact_derived":
                self.assertEqual(c.sigfigs, 40, key)
                self.assertGreaterEqual(len(v.as_tuple().digits), 38, key)
            else:
                self.assertEqual(c.sigfigs, 50, key)

    def test_measured_values_do_not_claim_more_digits_than_their_uncertainty(self):
        for key, c in self.table.items():
            if c.kind == "measured":
                digits = len(Decimal(c.text).as_tuple().digits)
                self.assertLessEqual(digits - c.sigfigs, 1, key)          # CODATA publishes one guard digit at most

    def test_formula_applications_exist(self):
        raw = json.loads((DATA / "formulas.json").read_text(encoding="utf-8"))
        formulas = {f["id"] for f in (raw["formulas"] if isinstance(raw, dict) else raw)}
        for key, c in self.table.items():
            for fid in c.applications:
                self.assertIn(fid, formulas, f"{key} -> {fid}")

    def test_aliases_point_at_real_keys_and_keys_are_unique(self):
        for alias, key in K._ALIASES.items():
            self.assertIn(key, self.table, alias)
        self.assertEqual(len(self.raw["constants"]), len(self.table))
        self.assertEqual(K.get("ħ").key, "hbar")
        self.assertEqual(K.get("avogadro").key, "NA")
        self.assertEqual(K.get("euler").key, "euler_e")

    def test_unknown_constant_is_a_clear_error(self):
        with self.assertRaises(SciCalError) as ctx:
            K.get("nonsense")
        self.assertIn("Known constants", ctx.exception.hint)

    def test_financial_parameters_are_not_in_the_constants_store(self):
        for c in self.table.values():
            self.assertNotIn("discount", c.name.lower())
            self.assertNotIn("inflation", c.name.lower())
            self.assertNotIn("interest", c.name.lower())
        self.assertNotIn("financial", K.categories())

    def test_the_store_is_pinned(self):
        """A reference update must be a deliberate act: change a value and this fails until the pin (and the reference tests above) are updated."""
        rows = [[k, c["value"], c["uncertainty"], c["unit"], c["edition"]] for k, c in sorted(self.raw["constants"].items())]
        digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()
        self.assertEqual(digest, PIN, "constants.json changed: if this is a deliberate reference update, review every changed value and update PIN")
        self.assertEqual(self.raw["meta"]["version"], "CODATA 2022")


PIN = "c2f4cc8c07bfcc8692fd8d901bf272993b548e1d92c02be4330a4182d482b4ac"


class SearchAndCatalogue(unittest.TestCase):
    def keys(self, query="", category=""):
        return [c.key for c in K.search(query, category)]

    def test_search_by_name_symbol_key_and_alias(self):
        self.assertEqual(self.keys("planck")[0], "h")
        self.assertIn("hbar", self.keys("planck"))
        self.assertEqual(self.keys("k_B")[0], "kB")
        self.assertEqual(self.keys("kB")[0], "kB")
        self.assertEqual(self.keys("ħ")[0], "hbar")
        self.assertEqual(self.keys("avogadro")[0], "NA")
        self.assertEqual(self.keys("π")[0], "pi")
        self.assertEqual(self.keys("PARSEC")[0], "pc")
        self.assertEqual(self.keys("fine structure")[0], "alpha")
        self.assertEqual(self.keys("zzzz"), [])

    def test_category_filter(self):
        self.assertEqual(len(self.keys(category="mathematical")), 12)
        self.assertTrue(all(K.get(k).category == "astronomical" for k in self.keys(category="astronomical")))
        self.assertIn("au", self.keys("astronomical", "astronomical"))
        self.assertNotIn("h", self.keys(category="chemical"))
        self.assertIn("NA", self.keys(category="chemical"))

    def test_catalogue_operation(self):
        r = dom("catalogue", query="boltzmann")
        self.assertTrue(r["ok"])
        self.assertEqual(r["constants"][0]["key"], "kB")
        self.assertEqual(r["total"], len(K.constants()))
        self.assertEqual({c["id"] for c in r["categories"]}, set(K.categories()))
        self.assertEqual(sum(c["count"] for c in r["categories"]), r["total"])
        first = r["constants"][0]
        for field in ("name", "symbol", "valueExact", "unit", "dimension", "exact", "uncertaintyText", "sigfigs", "source", "edition", "description", "applications", "kind", "expression"):
            self.assertIn(field, first)
        self.assertEqual(r["meta"]["version"], "CODATA 2022")
        by_keys = dom("catalogue", keys=["h", "c", "nope"])
        self.assertEqual([c["key"] for c in by_keys["constants"]], ["h", "c"])        # order kept, unknown keys dropped
        self.assertFalse(dom("catalogue", category="bogus")["ok"])

    def test_measurement_constants_card_reads_the_same_store(self):
        r = run({"kind": "domain", "domain": "measurement", "op": "constants", "params": {"query": "gravitation"}, "settings": {}})
        self.assertTrue(r["ok"])
        self.assertEqual({c["key"] for c in r["constants"]}, {"G"})
        self.assertEqual(run({"kind": "domain", "domain": "measurement", "op": "constants", "params": {}, "settings": {}})["count"], len(K.constants()))


class Conversions(unittest.TestCase):
    def test_speed_of_light_in_km_per_s(self):
        r = dom("convert", key="c", to="km/s")
        self.assertTrue(r["ok"])
        self.assertEqual(Decimal(r["decimal"]), Decimal("299792.458"))
        self.assertEqual(r["dimension"], "speed")

    def test_planck_in_ev_seconds_matches_h_over_e(self):
        r = dom("convert", key="h", to="eV*s")
        want = Decimal("6.62607015e-34") / Decimal("1.602176634e-19")
        self.assertLess(abs(Decimal(r["decimal"]) - want) / want, Decimal("1e-25"))
        self.assertAlmostEqual(float(r["decimal"]), 4.135667696923859e-15, delta=1e-27)

    def test_uncertainty_scales_with_the_value(self):
        a = dom("convert", key="G", to="m^3/(kg*s^2)")
        b = dom("convert", key="G", to="cm^3/(g*s^2)")
        self.assertAlmostEqual(float(b["decimal"]) / float(a["decimal"]), 1000.0, places=9)
        self.assertAlmostEqual(float(b["uncertaintyDecimal"]) / float(a["uncertaintyDecimal"]), 1000.0, places=2)
        self.assertNotIn("uncertainty", dom("convert", key="c", to="m/s"))

    def test_other_units_of_the_same_dimension(self):
        self.assertAlmostEqual(float(dom("convert", key="au", to="km")["decimal"]), 149597870.7, places=6)
        self.assertAlmostEqual(float(dom("convert", key="atm", to="bar")["decimal"]), 1.01325, places=12)
        self.assertAlmostEqual(float(dom("convert", key="gn", to="ft/s^2")["decimal"]), 9.80665 / 0.3048, places=10)
        self.assertAlmostEqual(float(dom("convert", key="Rsun", to="km")["decimal"]), 695700.0, places=6)

    def test_incompatible_dimensions_and_dimensionless_are_refused(self):
        r = dom("convert", key="c", to="kg")
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"]["code"], "dimension_error")
        self.assertFalse(dom("convert", key="alpha", to="m")["ok"])
        self.assertFalse(dom("convert", key="c", to="parsecs-of-nonsense")["ok"])
        self.assertFalse(dom("convert", key="zz", to="m")["ok"])


class InsertionIntoCalculations(unittest.TestCase):
    def test_every_constant_can_be_inserted_in_both_modes(self):
        for key, c in K.constants().items():
            for units in (True, False):
                r = calc(c.expression, units=units)
                self.assertTrue(r["ok"], (key, units, r))

    def test_inserted_value_is_the_stored_value(self):
        r = calc("const(c)", units=True)
        self.assertEqual(r["value"]["mag"]["text"], "299792458")
        self.assertEqual(r["unit"]["dimension"], "speed")
        self.assertEqual(calc("const(sqrt2)^2")["value"]["text"], "2")
        self.assertEqual(K.get("pi").expression, "pi")
        self.assertEqual(K.get("euler_e").expression, "e")
        self.assertEqual(K.get("h").expression, "const(h)")

    def test_names_that_are_also_units_are_read_as_constants(self):
        for name, unit in (("h", "J*s"), ("bar", "Pa"), ("eV", "J"), ("F", "C/mol"), ("hp", "W")):
            r = calc(f"const({name})", units=True)
            self.assertTrue(r["ok"], (name, r))
            self.assertEqual(r["unit"]["text"], unit, name)

    def test_calculation_with_units_is_dimensionally_checked(self):
        r = calc("const(c) * 2 s", units=True)
        self.assertEqual(r["value"]["text"], "599584916 m")
        r = calc("const(au) / const(c)", units=True)
        self.assertEqual(r["unit"]["text"], "s")
        self.assertAlmostEqual(float(r["value"]["text"].split()[0]), 499.004783836, places=6)
        # E = m c^2 for one electron mass, in eV
        r = calc("const(me) * const(c)^2 -> eV", units=True)
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(float(r["value"]["text"].split()[0]), 510998.95, delta=0.01)
        self.assertFalse(calc("const(c) + const(h)", units=True)["ok"])

    def test_result_names_the_edition_so_reproducibility_is_visible(self):
        r = calc("const(G) * 2", units=True)
        notes = [w["message"] for w in r["warnings"]]
        self.assertTrue(any("CODATA 2022" in n and "uncertainty" in n for n in notes), notes)
        exact = [w["message"] for w in calc("const(c)", units=True)["warnings"]]
        self.assertTrue(any("CODATA 2022" in n and "uncertainty" not in n for n in exact), exact)
        self.assertFalse(calc("const(pi)", units=True).get("warnings"))               # a mathematical constant has no edition to report

    def test_argument_must_be_a_name(self):
        self.assertFalse(calc("const(2)")["ok"])
        self.assertFalse(calc("const(c, h)")["ok"])


class FinancialParameters(unittest.TestCase):
    """The financial parameters are the person's own preferences, validated like the rest, and never constants."""
    def prefs(self):
        return Prefs(Path(tempfile.mkdtemp()) / "prefs.json")

    def test_accepted_values_round_trip(self):
        p = self.prefs()
        p.update({"finCurrency": "EUR", "finPlaces": 2, "finDiscountRate": 7.5, "finInflation": 2.5})
        self.assertEqual(p.data["finCurrency"], "EUR")
        self.assertEqual(p.data["finPlaces"], 2)
        self.assertEqual(p.data["finDiscountRate"], 7.5)
        again = Prefs(p.path)
        self.assertEqual(again.data["finInflation"], 2.5)

    def test_invalid_values_are_refused(self):
        p = self.prefs()
        for bad in ({"finCurrency": "euro"}, {"finCurrency": "eur"}, {"finPlaces": 9}, {"finPlaces": "2"}, {"finDiscountRate": 5000}, {"finInflation": -99}, {"finDiscountRate": True}):
            with self.assertRaises(SciCalError, msg=str(bad)):
                p.update(bad)
        self.assertEqual(p.data, {})

    def test_null_removes_a_value(self):
        p = self.prefs()
        p.update({"finDiscountRate": 6.0, "finCurrency": "USD"})
        p.update({"finDiscountRate": None})
        self.assertNotIn("finDiscountRate", p.data)
        self.assertEqual(p.data["finCurrency"], "USD")
        p.update({"finCurrency": ""})
        self.assertEqual(p.data["finCurrency"], "")


if __name__ == "__main__":
    unittest.main()
