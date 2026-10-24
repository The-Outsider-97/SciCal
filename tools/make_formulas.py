"""Builds scical/data/formulas.json from the table below and validates every entry:
the equation must parse, the variables must match, both sides must have the same dimension for the declared units."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sympy as sp  # noqa: E402

from scical.domains.formulas import solver as V  # noqa: E402

# id | category | name | equation | variables | note
# variable spec: symbol:name:unit[:constant-key]   (unit "1" = dimensionless)
T = [
    # ---- physics
    ("newton2", "Physics", "Newton's second law", "F = m*a", "F:force:N m:mass:kg a:acceleration:m/s^2", "Net force on a body of constant mass."),
    ("weight", "Physics", "Weight", "W = m*g", "W:weight:N m:mass:kg g:gravitational acceleration:m/s^2:gn", "Uses standard gravity by default."),
    ("speed", "Physics", "Average speed", "v = d/t", "v:speed:m/s d:distance:m t:time:s", ""),
    ("kin1", "Physics", "Kinematics: v = u + at", "v = u + a*t", "v:final velocity:m/s u:initial velocity:m/s a:acceleration:m/s^2 t:time:s", "Constant acceleration."),
    ("kin2", "Physics", "Kinematics: s = ut + ½at²", "s = u*t + a*t^2/2", "s:displacement:m u:initial velocity:m/s a:acceleration:m/s^2 t:time:s", "Constant acceleration."),
    ("kin3", "Physics", "Kinematics: v² = u² + 2as", "v^2 = u^2 + 2*a*s", "v:final velocity:m/s u:initial velocity:m/s a:acceleration:m/s^2 s:displacement:m", "Constant acceleration; the speed squared hides the direction, so solving for v or u gives ± roots."),
    ("momentum", "Physics", "Momentum", "p = m*v", "p:momentum:kg*m/s m:mass:kg v:velocity:m/s", ""),
    ("kinetic", "Physics", "Kinetic energy", "E = m*v^2/2", "E:kinetic energy:J m:mass:kg v:speed:m/s", "Non-relativistic."),
    ("potential", "Physics", "Gravitational potential energy", "E = m*g*h", "E:potential energy:J m:mass:kg g:gravitational acceleration:m/s^2:gn h:height:m", "Near the Earth's surface."),
    ("work", "Physics", "Work", "W = F*d*cos(theta)", "W:work:J F:force:N d:displacement:m theta:angle between force and displacement:rad", "Enter the angle in rad or with deg, e.g. 30 deg."),
    ("power", "Physics", "Power", "P = E/t", "P:power:W E:energy:J t:time:s", ""),
    ("pressure", "Physics", "Pressure", "P = F/A", "P:pressure:Pa F:force:N A:area:m^2", ""),
    ("density", "Physics", "Density", "rho = m/V", "rho:density:kg/m^3 m:mass:kg V:volume:m^3", ""),
    ("hooke", "Physics", "Hooke's law", "F = k*x", "F:force:N k:spring constant:N/m x:extension:m", ""),
    ("spring_energy", "Physics", "Spring energy", "E = k*x^2/2", "E:stored energy:J k:spring constant:N/m x:extension:m", ""),
    ("centripetal", "Physics", "Centripetal acceleration", "a = v^2/r", "a:acceleration:m/s^2 v:speed:m/s r:radius:m", ""),
    ("pendulum", "Physics", "Simple pendulum period", "T = 2*pi*sqrt(L/g)", "T:period:s L:length:m g:gravitational acceleration:m/s^2:gn", "Small angles only."),
    ("wave", "Physics", "Wave speed", "v = f*lam", "v:wave speed:m/s f:frequency:Hz lam:wavelength:m", ""),
    ("photon_f", "Physics", "Photon energy (frequency)", "E = h*f", "E:photon energy:J h:Planck constant:J*s:h f:frequency:Hz", ""),
    ("photon_l", "Physics", "Photon energy (wavelength)", "E = h*c/lam", "E:photon energy:J h:Planck constant:J*s:h c:speed of light:m/s:c lam:wavelength:m", ""),
    ("debroglie", "Physics", "de Broglie wavelength", "lam = h/(m*v)", "lam:wavelength:m h:Planck constant:J*s:h m:mass:kg v:speed:m/s", "Non-relativistic."),
    ("massenergy", "Physics", "Mass–energy equivalence", "E = m*c^2", "E:energy:J m:mass:kg c:speed of light:m/s:c", ""),
    ("ohm", "Physics", "Ohm's law", "V = I*R", "V:voltage:V I:current:A R:resistance:ohm", ""),
    ("elec_power", "Physics", "Electrical power", "P = V*I", "P:power:W V:voltage:V I:current:A", ""),
    ("capacitor_q", "Physics", "Capacitor charge", "Q = C*V", "Q:charge:C C:capacitance:F V:voltage:V", ""),
    ("capacitor_e", "Physics", "Capacitor energy", "E = C*V^2/2", "E:stored energy:J C:capacitance:F V:voltage:V", ""),
    ("coulomb", "Physics", "Coulomb's law", "F = qa*qb/(4*pi*eps0*r^2)", "F:force:N qa:charge A:C qb:charge B:C eps0:vacuum permittivity:F/m:eps0 r:separation:m", "Positive F repels; negative F attracts."),
    ("gravitation", "Physics", "Newton's law of gravitation", "F = G*m1*m2/r^2", "F:force:N G:gravitational constant:m^3/(kg*s^2):G m1:mass 1:kg m2:mass 2:kg r:separation:m", ""),
    ("escape", "Physics", "Escape velocity", "v = sqrt(2*G*M/r)", "v:escape velocity:m/s G:gravitational constant:m^3/(kg*s^2):G M:mass of the body:kg r:distance from centre:m", ""),
    ("projectile", "Physics", "Projectile range", "R = v^2*sin(2*theta)/g", "R:range:m v:launch speed:m/s theta:launch angle:rad g:gravitational acceleration:m/s^2:gn", "Level ground, no air resistance."),
    ("snell", "Physics", "Snell's law", "n1*sin(t1) = n2*sin(t2)", "n1:index 1:1 t1:angle 1:rad n2:index 2:1 t2:angle 2:rad", ""),
    ("lens", "Physics", "Thin lens equation", "1/f = 1/do + 1/di", "f:focal length:m do:object distance:m di:image distance:m", "Real-is-positive convention."),
    ("heat", "Physics", "Heat transfer", "q = m*c*dT", "q:heat:J m:mass:kg c:specific heat:J/(kg*K) dT:temperature change:K", "Use K or delta_degC for the temperature change."),
    ("stefan", "Physics", "Stefan–Boltzmann law", "P = sigma*A*T^4", "P:radiated power:W sigma:Stefan–Boltzmann constant:W/(m^2*K^4):sigma A:area:m^2 T:temperature:K", "For an ideal black body."),
    # ---- chemistry
    ("moles", "Chemistry", "Amount of substance", "n = m/M", "n:amount:mol m:mass:g M:molar mass:g/mol", ""),
    ("molarity", "Chemistry", "Molarity", "c = n/V", "c:concentration:mol/L n:amount:mol V:volume:L", ""),
    ("dilution", "Chemistry", "Dilution", "c1*V1 = c2*V2", "c1:concentration 1:mol/L V1:volume 1:L c2:concentration 2:mol/L V2:volume 2:L", ""),
    ("idealgas", "Chemistry", "Ideal gas law", "P*V = n*R*T", "P:pressure:Pa V:volume:m^3 n:amount:mol R:gas constant:J/(mol*K):R T:temperature:K", "Enter temperatures in kelvin or with degC; the conversion is exact."),
    ("boyle", "Chemistry", "Boyle's law", "P1*V1 = P2*V2", "P1:pressure 1:Pa V1:volume 1:m^3 P2:pressure 2:Pa V2:volume 2:m^3", "Constant amount and temperature."),
    ("charles", "Chemistry", "Charles's law", "V1/T1 = V2/T2", "V1:volume 1:m^3 T1:temperature 1:K V2:volume 2:m^3 T2:temperature 2:K", "Constant amount and pressure; kelvin only."),
    ("combined", "Chemistry", "Combined gas law", "P1*V1/T1 = P2*V2/T2", "P1:pressure 1:Pa V1:volume 1:m^3 T1:temperature 1:K P2:pressure 2:Pa V2:volume 2:m^3 T2:temperature 2:K", ""),
    ("graham", "Chemistry", "Graham's law", "r1/r2 = sqrt(M2/M1)", "r1:rate 1:1 r2:rate 2:1 M1:molar mass 1:g/mol M2:molar mass 2:g/mol", "Rates only enter as a ratio."),
    ("ph", "Chemistry", "pH", "pH = -log(H)", "pH:pH:1 H:hydronium activity (mol/L, as a number):1", "[H₃O⁺] in mol/L as a plain number. log is base 10. Ideal-solution definition."),
    ("hh", "Chemistry", "Henderson–Hasselbalch", "pH = pKa + log(A/HA)", "pH:pH:1 pKa:pKa:1 A:conjugate base amount:1 HA:acid amount:1", "A and HA in the same unit; only their ratio matters."),
    ("arrhenius", "Chemistry", "Arrhenius equation", "k = A*exp(-Ea/(R*T))", "k:rate constant:1/s A:pre-exponential factor:1/s Ea:activation energy:J/mol R:gas constant:J/(mol*K):R T:temperature:K", ""),
    ("nernst", "Chemistry", "Nernst equation", "E = E0 - R*T/(n*F)*ln(Q)", "E:potential:V E0:standard potential:V R:gas constant:J/(mol*K):R T:temperature:K n:electrons transferred:1 F:Faraday constant:C/mol:F Q:reaction quotient:1", ""),
    ("gibbs", "Chemistry", "Gibbs free energy", "dG = dH - T*dS", "dG:Gibbs energy change:J/mol dH:enthalpy change:J/mol T:temperature:K dS:entropy change:J/(mol*K)", ""),
    ("firstorder", "Chemistry", "First-order decay", "A = A0*exp(-k*t)", "A:amount:1 A0:initial amount:1 k:rate constant:1/s t:time:s", "A and A0 in the same unit."),
    ("halflife", "Chemistry", "First-order half-life", "t12 = ln(2)/k", "t12:half-life:s k:rate constant:1/s", ""),
    ("beer", "Chemistry", "Beer–Lambert law", "A = eps*l*c", "A:absorbance:1 eps:molar absorptivity:L/(mol*cm) l:path length:cm c:concentration:mol/L", ""),
    ("fpd", "Chemistry", "Freezing-point depression", "dT = i*Kf*m", "dT:depression:K i:van 't Hoff factor:1 Kf:cryoscopic constant:K*kg/mol m:molality:mol/kg", ""),
    ("osmotic", "Chemistry", "Osmotic pressure", "Pi = i*c*R*T", "Pi:osmotic pressure:Pa i:van 't Hoff factor:1 c:concentration:mol/m^3 R:gas constant:J/(mol*K):R T:temperature:K", "Dilute solutions."),
    # ---- biology
    ("expgrowth", "Biology", "Exponential growth", "N = N0*exp(r*t)", "N:population:1 N0:initial population:1 r:growth rate:1/h t:time:h", ""),
    ("doubling", "Biology", "Doubling time", "td = ln(2)/r", "td:doubling time:h r:growth rate:1/h", ""),
    ("logistic", "Biology", "Logistic growth", "N = K/(1 + (K - N0)/N0*exp(-r*t))", "N:population:1 K:carrying capacity:1 N0:initial population:1 r:growth rate:1/h t:time:h", ""),
    ("mm", "Biology", "Michaelis–Menten", "v = Vmax*S/(Km + S)", "v:rate:mol/(L*s) Vmax:maximum rate:mol/(L*s) S:substrate:mol/L Km:Michaelis constant:mol/L", ""),
    ("hw", "Biology", "Hardy–Weinberg allele frequencies", "p + q = 1", "p:dominant allele frequency:1 q:recessive allele frequency:1", "Two alleles only."),
    ("bmi", "Biology", "Body mass index", "BMI = m/h^2", "BMI:body mass index:kg/m^2 m:mass:kg h:height:m", ""),
    ("cardiac", "Biology", "Cardiac output", "CO = HR*SV", "CO:cardiac output:L/min HR:heart rate:1/min SV:stroke volume:L", ""),
    # ---- mathematics
    ("pythag", "Mathematics", "Pythagorean theorem", "c^2 = a^2 + b^2", "c:hypotenuse:m a:leg:m b:leg:m", "Solving for a leg uses only the positive length."),
    ("quadratic", "Mathematics", "Quadratic equation", "a*x^2 + b*x + c = 0", "a:coefficient a:1 b:coefficient b:1 c:coefficient c:1 x:root:1", "Both real roots are shown."),
    ("circle_area", "Mathematics", "Circle area", "A = pi*r^2", "A:area:m^2 r:radius:m", ""),
    ("circle_circ", "Mathematics", "Circle circumference", "C = 2*pi*r", "C:circumference:m r:radius:m", ""),
    ("sphere_vol", "Mathematics", "Sphere volume", "V = 4/3*pi*r^3", "V:volume:m^3 r:radius:m", ""),
    ("sphere_area", "Mathematics", "Sphere surface area", "A = 4*pi*r^2", "A:surface area:m^2 r:radius:m", ""),
    ("cyl_vol", "Mathematics", "Cylinder volume", "V = pi*r^2*h", "V:volume:m^3 r:radius:m h:height:m", ""),
    ("cosines", "Mathematics", "Law of cosines", "c^2 = a^2 + b^2 - 2*a*b*cos(C)", "c:side:m a:side:m b:side:m C:angle opposite c:rad", ""),
    ("slope", "Mathematics", "Slope between two points", "m = (y2 - y1)/(x2 - x1)", "m:slope:1 y1:y₁:1 y2:y₂:1 x1:x₁:1 x2:x₂:1", ""),
    ("distance", "Mathematics", "Distance between two points", "d = sqrt((x2 - x1)^2 + (y2 - y1)^2)", "d:distance:1 x1:x₁:1 y1:y₁:1 x2:x₂:1 y2:y₂:1", ""),
    ("arith_sum", "Mathematics", "Arithmetic series sum", "S = n*(a1 + an)/2", "S:sum:1 n:number of terms:1 a1:first term:1 an:last term:1", ""),
    ("geom_sum", "Mathematics", "Geometric series sum", "S = a*(1 - r^n)/(1 - r)", "S:sum:1 a:first term:1 r:common ratio:1 n:number of terms:1", "r must not equal 1."),
    # ---- statistics
    ("zscore", "Statistics", "z-score", "z = (x - mu)/sigma", "z:z-score:1 x:value:1 mu:mean:1 sigma:standard deviation:1", ""),
    ("sem", "Statistics", "Standard error of the mean", "SE = s/sqrt(n)", "SE:standard error:1 s:sample standard deviation:1 n:sample size:1", ""),
]


def parse_vars(spec: str) -> list[dict]:
    import re
    pat = re.compile(r"\s*([A-Za-z_]\w*):([^:]+):([^\s:]+)(?::([A-Za-z0-9_]+))?")
    out, pos = [], 0
    while pos < len(spec):
        m = pat.match(spec, pos)
        if not m:
            raise ValueError(f"cannot parse variables near: {spec[pos:pos + 30]!r}")
        sym, name, unit, const = m.groups()
        v = {"symbol": sym, "name": name, "unit": "" if unit == "1" else unit}
        if const:
            v["constant"] = const
        out.append(v)
        pos = m.end()
    return out


def main() -> None:
    from scical.core.units import constants as K
    from scical.core.units import parse_unit

    items, seen = [], set()
    for fid, cat, name, eqtext, vspec, note in T:
        assert fid not in seen, fid
        seen.add(fid)
        eq = V.parse_equation(eqtext)
        vs = parse_vars(vspec)
        want = {str(x) for x in eq.symbols()}
        have = {v["symbol"] for v in vs}
        assert want == have, (fid, want ^ have)
        dims = {sp.Symbol(v["symbol"]): V.to_dim_unit(v["unit"]).dim for v in vs}
        ld, rd = V.dim_of(eq.lhs, dims), V.dim_of(eq.rhs, dims)
        assert ld == rd, (fid, ld.name, rd.name)
        for v in vs:
            if v.get("constant"):
                c = K.get(v["constant"])
                q = c.quantity()
                from scical.core.units import Quantity
                cd = q.unit.dim if isinstance(q, Quantity) else parse_unit("1").dim
                assert cd == dims[sp.Symbol(v["symbol"])], (fid, v["symbol"], "constant dimension")
        items.append({"id": fid, "category": cat, "name": name, "equation": eqtext, "latex": f"{sp.latex(eq.lhs)} = {sp.latex(eq.rhs)}", "variables": vs, "note": note})
    out = ROOT / "scical" / "data" / "formulas.json"
    out.write_text(json.dumps({"meta": {"count": len(items), "note": "Equations are written in SciCal syntax. Every entry is dimensionally checked when this file is built."}, "formulas": items},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", len(items), "formulas")


if __name__ == "__main__":
    main()
