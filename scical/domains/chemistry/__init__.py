"""Chemistry: periodic table, formulas and molar mass, equation balancing, stoichiometry, solutions, acids and bases, gases, thermochemistry
and equilibrium."""

from .ops import OPS as _BASE
from .solutions import OPS as _SOL

OPS = {**_BASE, **_SOL}
