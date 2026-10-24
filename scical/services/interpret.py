"""An offline reader for plain-English requests. It never calculates anything itself: it turns a sentence into one or more *proposals*
(exact calculator input, or the inputs of a workspace operation) that the person sees and chooses to run. Rules only: no model, no network.

    "convert 5 miles to km"             -> calculator:   5 mi -> km
    "molar mass of C6H12O6"             -> Chemistry:    molar mass
    "pH of 0.01 M HCl"                  -> Chemistry:    strong acid
    "derivative of x^2 sin(x)"          -> calculator:   diff(x^2 sin(x), x)
    "gc content of ATGGCC"              -> Biology:      sequence analysis

If nothing matches but the text is a valid expression, it is offered as plain calculator input. If nothing fits, the answer says so.
"""
from __future__ import annotations

import re
from typing import Any

from ..core.expressions import ParseOptions, parse
from ..errors import SciCalError

MAX_TEXT = 500

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_UNIT_WORDS = {"miles": "mi", "mile": "mi", "kilometers": "km", "kilometres": "km", "kilometer": "km", "kilometre": "km", "meters": "m", "metres": "m", "meter": "m",
               "metre": "m", "centimeters": "cm", "centimetres": "cm", "millimeters": "mm", "millimetres": "mm", "inches": "in", "inch": "in", "feet": "ft", "foot": "ft",
               "yards": "yd", "yard": "yd", "pounds": "lb", "pound": "lb", "ounces": "oz", "ounce": "oz", "kilograms": "kg", "kilogram": "kg", "grams": "g", "gram": "g",
               "milligrams": "mg", "liters": "L", "litres": "L", "liter": "L", "litre": "L", "milliliters": "mL", "millilitres": "mL", "gallons": "gal", "gallon": "gal",
               "celsius": "degC", "fahrenheit": "degF", "kelvin": "K", "seconds": "s", "second": "s", "minutes": "min", "minute": "min", "hours": "h", "hour": "h",
               "days": "day", "day": "day", "joules": "J", "kilojoules": "kJ", "calories": "cal", "kilocalories": "kcal", "newtons": "N", "pascals": "Pa", "atmospheres": "atm",
               "bar": "bar", "watts": "W", "kilowatts": "kW", "hertz": "Hz", "degrees": "deg", "radians": "rad", "moles": "mol", "molar": "M", "millimolar": "mM"}
STRONG_ACIDS = {"hcl": 1, "hbr": 1, "hi": 1, "hno3": 1, "hclo4": 1, "h2so4": 2}
STRONG_BASES = {"naoh": 1, "koh": 1, "lioh": 1, "ba(oh)2": 2, "ca(oh)2": 2}
WEAK_ACIDS = {"acetic acid": 1.8e-5, "ch3cooh": 1.8e-5, "hf": 6.8e-4, "hydrofluoric acid": 6.8e-4, "formic acid": 1.8e-4, "hcooh": 1.8e-4,
              "hocl": 3.0e-8, "hypochlorous acid": 3.0e-8, "hcn": 6.2e-10, "benzoic acid": 6.3e-5}
WEAK_BASES = {"ammonia": 1.8e-5, "nh3": 1.8e-5, "methylamine": 4.4e-4, "pyridine": 1.7e-9}
SEQ = re.compile(r"\b([ACGTUNacgtun]{6,})\b")


def _unit(u: str) -> str:
    u = u.strip().rstrip(".?,")
    parts = re.split(r"(\s+per\s+|/|\s+)", u)
    out = []
    for p in parts:
        w = p.strip()
        if not w:
            continue
        if re.fullmatch(r"\s*per\s*", p):
            out.append("/")
        elif p == "/":
            out.append("/")
        else:
            out.append(_UNIT_WORDS.get(w.lower(), w))
    s = "".join(x if x == "/" else (("*" if out and False else "") + x) for x in out)
    return re.sub(r"\s+", "", s) or u


def _proposal(label: str, workspace: str, kind: str, payload: dict[str, Any], confidence: str = "high", note: str | None = None) -> dict[str, Any]:
    p = {"label": label, "workspace": workspace, "kind": kind, "payload": payload, "confidence": confidence}
    if note:
        p["note"] = note
    return p


def _parses(text: str, units: bool = False) -> bool:
    try:
        parse(text, ParseOptions(units=units, allow_statements=True))
        return True
    except SciCalError:
        return False
    except RecursionError:
        return False


def _nums(text: str) -> list[str]:
    return re.findall(_NUM, text)


def interpret(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        return {"ok": True, "proposals": [], "message": "Type what you want to do, for example: convert 5 miles to km, or molar mass of C6H12O6."}
    text = raw.strip()[:MAX_TEXT]
    low = text.lower().strip().rstrip("?.! ")
    out: list[dict[str, Any]] = []

    # ---- unit conversion
    m = re.match(rf"^(?:convert\s+|how many\s+.*?\bin\s+)?({_NUM}|[\d./ ()^*x×e-]+?)\s*([a-zµ°/^ ]+?)\s+(?:to|into|in|as)\s+([a-zµ°/^ ]+)$", low)
    if m and not low.startswith(("solve", "derivative", "integral", "plot", "graph")):
        v, a, b = m.group(1).strip().replace("×", "*").replace("x", "*") if "e" not in m.group(1) else m.group(1).strip(), _unit(m.group(2)), _unit(m.group(3))
        expr = f"{v} {a} -> {b}"
        if _parses(expr, True):
            out.append(_proposal(f"Convert {v} {a} to {b}", "math", "calc", {"input": expr, "settings": {"units": True}}))

    # ---- chemistry
    m = re.match(r"^(?:the\s+)?molar mass of\s+(.+)$", low) or re.match(r"^(?:what is the\s+)?molecular weight of\s+(.+)$", low)
    if m:
        f = re.search(r"[A-Za-z0-9()\[\]·.^+\-]+$", text.strip().rstrip("?.! "))
        if f:
            out.append(_proposal(f"Molar mass of {f.group(0)}", "chemistry", "domain", {"domain": "chemistry", "op": "molar_mass", "params": {"formula": f.group(0)}}))
    if low.startswith("balance "):
        eq = text.strip()[8:].strip().rstrip("?.! ")
        out.append(_proposal("Balance the equation", "chemistry", "domain", {"domain": "chemistry", "op": "balance", "params": {"equation": eq}}))
    m = re.match(rf"^(?:the\s+)?ph of\s+(?:a\s+)?({_NUM})\s*(?:m|molar|mol/l)?\s+(?:solution of\s+)?(.+)$", low)
    if m:
        c, sub = m.group(1), m.group(2).strip()
        key = sub.replace(" solution", "").strip()
        if key in STRONG_ACIDS:
            out.append(_proposal(f"pH of {c} M {sub} (strong acid)", "chemistry", "domain", {"domain": "chemistry", "op": "acid_base", "params": {"mode": "strong_acid", "concentration": c, "protons": STRONG_ACIDS[key]}}))
        elif key in STRONG_BASES:
            out.append(_proposal(f"pH of {c} M {sub} (strong base)", "chemistry", "domain", {"domain": "chemistry", "op": "acid_base", "params": {"mode": "strong_base", "concentration": c, "hydroxides": STRONG_BASES[key]}}))
        elif key in WEAK_ACIDS:
            out.append(_proposal(f"pH of {c} M {sub} (weak acid, Ka {WEAK_ACIDS[key]:g})", "chemistry", "domain", {"domain": "chemistry", "op": "acid_base", "params": {"mode": "weak_acid", "concentration": c, "ka": str(WEAK_ACIDS[key])}},
                                 note="Ka is a textbook value at 25 °C; change it in the Chemistry workspace if yours differs."))
        elif key in WEAK_BASES:
            out.append(_proposal(f"pH of {c} M {sub} (weak base, Kb {WEAK_BASES[key]:g})", "chemistry", "domain", {"domain": "chemistry", "op": "acid_base", "params": {"mode": "weak_base", "concentration": c, "kb": str(WEAK_BASES[key])}}))
        else:
            out.append(_proposal("pH of a weak acid or base: needs Ka or Kb", "chemistry", "domain", {"domain": "chemistry", "op": "acid_base", "params": {"mode": "weak_acid", "concentration": c}},
                                 "medium", f"I do not know '{sub}'. Open Acids & bases and enter its Ka."))

    # ---- calculus and algebra
    m = re.match(r"^(?:the\s+)?(?:derivative|differentiate)\s+(?:of\s+)?(.+?)(?:\s+(?:with respect to|wrt|w\.r\.t\.?)\s+([a-z]))?$", low)
    if m:
        f, var = m.group(1).strip(), m.group(2) or "x"
        expr = f"diff({f}, {var})"
        if _parses(expr):
            out.append(_proposal(f"Derivative of {f}", "math", "calc", {"input": expr}))
    m = re.match(r"^(?:the\s+)?integral of\s+(.+?)(?:\s+from\s+(\S+)\s+to\s+(\S+))?$", low) or re.match(r"^integrate\s+(.+?)(?:\s+from\s+(\S+)\s+to\s+(\S+))?$", low)
    if m:
        f = m.group(1).strip()
        f = re.sub(r"\s+d[xyt]$", "", f)
        expr = f"integrate({f}, x, {m.group(2)}, {m.group(3)})" if m.group(2) else f"integrate({f}, x)"
        if _parses(expr):
            out.append(_proposal(f"Integral of {f}" + (f" from {m.group(2)} to {m.group(3)}" if m.group(2) else ""), "math", "calc", {"input": expr}))
    m = re.match(r"^limit of\s+(.+?)\s+as\s+([a-z])\s*(?:->|→|approaches|tends to|to)\s*(\S+)$", low)
    if m:
        expr = f"limit({m.group(1)}, {m.group(2)}, {m.group(3).replace('infinity', 'oo').replace('∞', 'oo')})"
        if _parses(expr):
            out.append(_proposal(f"Limit of {m.group(1)}", "math", "calc", {"input": expr}))
    m = re.match(r"^solve\s+(.+?)(?:\s+for\s+([a-z]))?$", low)
    if m and "=" in m.group(1):
        expr = f"solve({m.group(1)}, {m.group(2)})" if m.group(2) else f"solve({m.group(1)})"
        if _parses(expr):
            out.append(_proposal(f"Solve {m.group(1)}", "math", "calc", {"input": expr}))
    elif m:
        out.append(_proposal(f"Solve {m.group(1)} = 0", "math", "calc", {"input": f"solve({m.group(1)} = 0)"}, "medium", "No '=' was given, so it is read as '… = 0'."))

    # ---- graphing
    m = re.match(r"^(?:plot|graph|draw)\s+(?:y\s*=\s*)?(.+)$", low)
    if m:
        fs = [x.strip() for x in re.split(r"\s+and\s+|;", m.group(1)) if x.strip()]
        layers = [{"type": "function", "expr": re.sub(r"^y\s*=\s*", "", f)} for f in fs[:6]]
        out.append(_proposal("Plot " + ", ".join(l["expr"] for l in layers), "graph", "graph", {"spec": {"layers": layers, "viewport": {"xmin": -10, "xmax": 10, "ymin": -6, "ymax": 6}}}))

    # ---- statistics
    m = re.match(r"^(mean|average|median|standard deviation|std|variance|sum|max|min|range)\s+of\s+(.+)$", low)
    if m:
        data = _nums(m.group(2))
        fn = {"average": "mean", "standard deviation": "stdev", "std": "stdev", "variance": "var"}.get(m.group(1), m.group(1))
        if len(data) >= 2:
            out.append(_proposal(f"{m.group(1).capitalize()} of {len(data)} values", "math", "calc", {"input": f"{fn}([{', '.join(data)}])"}))
            if len(data) >= 3 and fn in ("mean", "stdev"):
                out.append(_proposal("Full summary with standard error and confidence interval", "measurement", "domain",
                                     {"domain": "measurement", "op": "repeated", "params": {"values": data}}, "medium"))

    # ---- biology
    m = SEQ.search(text)
    if m and re.search(r"\b(gc|content|sequence|dna|rna|reverse complement|transcribe|melting|tm)\b", low):
        s = m.group(1)
        out.append(_proposal("Analyse the sequence (GC content, reverse complement, Tm)", "biology", "domain", {"domain": "biology", "op": "sequence", "params": {"sequence": s}}))
    if m and re.search(r"\btranslat", low):
        out.append(_proposal("Translate the sequence", "biology", "domain", {"domain": "biology", "op": "translate", "params": {"sequence": m.group(1)}}))
    if m and re.search(r"\borf", low):
        out.append(_proposal("Find open reading frames", "biology", "domain", {"domain": "biology", "op": "orfs", "params": {"sequence": m.group(1)}}))

    # ---- measurement
    m = re.match(rf"^(?:the\s+)?percent error (?:of|for)\s+({_NUM})\s+(?:vs\.?|versus|against|and|when the accepted value is)\s+({_NUM})$", low)
    if m:
        out.append(_proposal("Percent error", "measurement", "domain", {"domain": "measurement", "op": "percent_error", "params": {"mode": "error", "experimental": m.group(1), "accepted": m.group(2)}}))
    m = re.match(rf"^(?:how many )?(?:sig(?:nificant)? figs?|sig(?:nificant)? figures)\s+(?:in|of|does)\s+({_NUM})", low)
    if m:
        out.append(_proposal("Count significant figures", "measurement", "domain", {"domain": "measurement", "op": "sig_figs", "params": {"mode": "count", "value": m.group(1)}}))

    # ---- fallback: the text itself as calculator input (only when it looks like mathematics, not a sentence)
    looks_math = bool(re.search(r"[\d+\-*/^()=\[\]]", text)) and len(text.split()) <= 12
    if not out and looks_math:
        with_units = bool(re.search(r"\d\s*[A-Za-zµ°]", text)) and _parses(text, True)
        if with_units:
            out.append(_proposal("Calculate with units", "math", "calc", {"input": text, "settings": {"units": True}}, "medium"))
        if _parses(text):
            out.append(_proposal("Calculate", "math", "calc", {"input": text}, "medium"))
        if not with_units and not out and _parses(text, True):
            out.append(_proposal("Calculate with units", "math", "calc", {"input": text, "settings": {"units": True}}, "medium"))
    msg = None if out else ("I could not turn that into a calculation. Try a form like: convert 5 miles to km · molar mass of NaCl · pH of 0.01 M HCl · "
                            "derivative of x^2 sin(x) · solve x^2-4=0 · plot sin(x) · mean of 3, 4, 8 · gc content of ATGGCC.")
    return {"ok": True, "proposals": out[:6], "message": msg, "note": "Rules only: nothing is run until you choose a proposal. Check that it says what you meant."}
