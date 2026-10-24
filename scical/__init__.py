"""SciCal - a scientific calculator and STEM workbench. Part of SLAI v2.4, in ``applications/scical``.

Layers (each depends only on the ones above it in this list):

* ``scical.core.units``        dimensional analysis, exact unit conversion, constants with provenance
* ``scical.core.expressions``  lexer, parser, AST, text/LaTeX printers (no evaluation)
* ``scical.core.numerical``    evaluator (exact first, rounded on display), statistics, linear algebra, numerical calculus,
                               and (in ``funcs_symbolic``) algebra and calculus on SymPy
* ``scical.core.graphing``     sampling, analysis and export of 2D graphs
* ``scical.domains``           chemistry, biology and measurement, built on the core
* ``scical.services``          sessions, history, formulas, exports, worker pool
* ``scical.integrations``      the optional links to SLAI (agents, SLDC, STEM cross-check)
* ``scical.server``            the loopback HTTP service that also serves the web client
"""
APP_NAME = "SciCal"
__version__ = "2.4.0"
