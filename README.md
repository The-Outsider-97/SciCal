# SciCal

A scientific calculator and STEM workbench that runs on your own computer, part of SLAI v2.4.

* **Mathematics** – exact-first arithmetic, algebra, calculus, linear algebra, statistics, units, complex numbers.
* **Graphing** – interactive 2D plots (functions, implicit curves, inequalities, parametric, polar, sequences, vector fields, scatter with fits, histograms), sliders, roots/extrema/integrals/intersections/tangents.
* **3D graphing** – surfaces z = f(x, y), parametric surfaces, space curves and point sets that you can rotate, pan and zoom; sliders, layers, colour by height, transparent PNG export.
* **Save as SGEO / SDRW** – a 3D scene becomes an SGEO model (or a clearly labelled, lossy SDRW wireframe or contour drawing); a 2D graph becomes an SDRW drawing. Files are written by SLAI's own writers, validated and re-opened.
* **Finance** – 24 calculators (interest, loans and amortisation, annuities, NPV/IRR, break-even, supply and demand, growth, sensitivity tables…), each with its formula, assumptions and a working you can check.
* **Constants** – 85 physical constants (CODATA 2022 where applicable) with sources and uncertainties, insertable into any calculation.
* **Chemistry, Biology, Measurement, Formulas** – calculators for each subject, each showing its working.
* **Worksheets** – every calculation is kept in a worksheet you can search, re-open and export (Markdown, text, CSV, JSON, and SLDC when SLAI is present).
* Light, dark and high-contrast themes. Nothing is sent over the internet.

![Mathematics](docs/screenshots/math.png)

## Run it

```
pip install -r requirements.txt          # sympy, mpmath, numpy (Python 3.10 or newer)
python -m scical                         # from this folder; opens your browser
```

`python run_scical.py` does the same. The web client is shipped prebuilt in `dist/`, so Node is only needed if you change `src/`.
SciCal listens on `127.0.0.1:8768` only and opens the page with a one-time access token.

| Option | Meaning |
| --- | --- |
| `--port 8768` | Port to listen on (Documaster uses 8766, Reader 8767). |
| `--host` | Loopback addresses only; anything else is refused. |
| `--data-dir` | Worksheets and preferences. Default `%LOCALAPPDATA%\SLAI\SciCal` (Windows) or `~/.local/share/slai/scical`. |
| `--output-dir` | Exports. Default `Documents\SLAI SciCal`. |
| `--slai-root` | Path to the SLAI checkout. Found automatically from this folder when possible. |
| `--assets-dir` | Folder with the SLAI icons. Default `applications/assets`. |
| `--agents auto\|none\|strict` | Optional SLAI assistant. `none` never calls an agent; `strict` refuses to answer without one. |
| `--workers N` | Calculation worker processes (default up to 4). |
| `--timeout S` | Seconds one calculation may run (default 30). |
| `--no-browser` | Do not open a browser window. |
| `--token T` | Fixed access token (for tests; random otherwise). |
| `--client-dir` | Use a different build of the web client. |

## Where things are

```
scical/core/units          dimensions, exact unit conversion, constants with sources
scical/core/expressions    lexer, parser, AST, text and LaTeX printers (nothing is ever eval'd)
scical/core/numerical      evaluator, statistics, linear algebra, SymPy algebra/calculus (funcs_symbolic)
scical/core/graphing       sampling, analysis, regression, 3D sampling (space.py)
scical/domains             chemistry, biology, measurement, formulas, finance, constants, and the form catalogue (forms.py)
scical/services            worksheets, exports, SGEO/SDRW export (spatial.py), figure records (figures.py), worker pool and cancellation
scical/integrations        optional links to SLAI (assistant, SLDC, STEM cross-check)
scical/server              loopback HTTP service, security checks, routes
src/client, src/core       TypeScript client (strict, no innerHTML) -> dist/
tests, tests_ts, tests_e2e Python, TypeScript and browser tests
docs/                      USER_GUIDE.md, REPORTS.md, screenshots/
```

## Tests

```
PYTHONPATH=. python -m unittest discover -s tests          # 332 engine, domain, finance, constants, 3D, export and server tests
PYTHONPATH=. python -m unittest discover -s tests_e2e      # 11 browser tests (needs Playwright + Chromium)
npm install && npm test && npm run typecheck               # 40 TypeScript tests, strict type check
npm run build                                              # rebuild dist/
```

The SGEO/SDRW export tests need the SLAI checkout and `jsonschema` 4 or newer (for strict validation); without them they are skipped, not passed.

See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for how to use it and [docs/REPORTS.md](docs/REPORTS.md) for the security model, integration status, test results and known limits.
