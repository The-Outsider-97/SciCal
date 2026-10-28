# SciCal – engineering report (v2.4.0)

This is the honest state of SciCal: what was built, how it was checked, what could not be checked, and what is not there.

## 1. What is in the box

| Area | Status |
| --- | --- |
| Engine: exact-first arithmetic, rationals, radicals, complex, units with dimension checking, 143 functions in 14 groups | Done, tested |
| No `eval`: lexer → parser → AST → evaluator; SymPy is used for algebra and calculus only on parsed ASTs | Done |
| Mathematics: algebra, calculus (exact and numerical), linear algebra, statistics and distributions, number theory, number bases | Done, tested |
| 2D graphing: function / implicit / inequality / vertical line, parametric, polar, sequences, vector fields, scatter + fit, histogram; sliders; roots, extrema, integral, intersection, value, tangent; table of values; PNG export | Done, tested (unit + browser) |
| Chemistry (12 operations), Biology (11), Measurement (9), Formulas (3) | Done, tested |
| Worksheets: autosave, search, rename, import, export (Markdown, text, CSV, JSON, SLDC) | Done, tested |
| Themes: light, dark, high contrast, follows the system; text size; reduced motion | Done |
| Keyboard use, labelled controls, live regions for results and errors, visible focus | Done; checked by hand and by the browser tests, not by a screen-reader audit |
| Optional SLAI assistant | Partly verified, see §4 |
| 3D plotting: surfaces, parametric surfaces, space curves, point sets; rotate/pan/zoom, layers, sliders, transparent PNG | Done; sampling covered by unit tests, drawing checked in a real browser (light, dark, narrow) |
| Save as SGEO / SDRW through SLAI's writers (3D model; derived wireframe and contour drawings; 2D drawing) | Done; round-trip tests re-open each file with SLAI's reader and compare coordinates, topology, unit, ids, metadata, material and provenance with stated tolerances; clicked through in a real browser |
| Finance (24 calculators) and Constants (85) | Done, tested; see the v2.4 test results |
| Central SLAI launcher registration | **Not built**: SLAI has no registry to register with. Start with `python -m scical` or `run_scical.py` |

## 2. Security model

SciCal follows the pattern of the other SLAI applications (Reader was the template).

* **Loopback only.** The service binds to `127.0.0.1`/`::1`; any other `--host` is refused at start-up.
* **Access token.** A random token is placed in the URL once, exchanged for an `HttpOnly; SameSite=Strict` cookie (`slai_scical_token`) and then dropped from the address bar. Requests without the cookie get 403.
* **Host and Origin checks** against DNS-rebinding and cross-site requests; mutating requests also need the `X-SLAI-SciCal` header, which a cross-origin page cannot set without a pre-flight that is never granted.
* **Strict CSP**: no inline script or style, no `eval`, no third-party origins. The client never uses `innerHTML` (it builds DOM nodes), so a result containing markup is shown as text.
* **Input limits:** bodies over their route's limit get 413; expressions, matrix sizes, list lengths, plot points, exponents and factorials are capped; session ids must be 16 hex characters; worksheet entries are re-validated on the way in and out; preferences are checked against a schema and unknown or invalid values are rejected.
* **Isolation of heavy work.** Calculations run in a pool of worker processes with a timeout (default 30 s) and cancellation by job id; a worker that overruns is killed and replaced. The timeout is reported as an error card, never as a hang.
* **Exports.** File names are sanitised; CSV cells that begin with `=`, `+`, `-` or `@` are prefixed so a spreadsheet cannot run them.
* **Privacy.** Nothing leaves the computer. If SLAI agents are used, the text first goes to SLAI's Privacy agent, only per worksheet and only after the person allows it.

## 3. Test results

| Suite | Where it ran | Result |
| --- | --- | --- |
| Python: parser (12), forms (2), domains (35), engine (31), graph (15), server (22, starts the real service) | cloud, Python 3.13 | 117 / 117 pass |
| The same Python suite | **your computer's Linux VM, Python 3.10.12** (the target SLAI environment) | 117 / 117 pass |
| TypeScript: LaTeX renderer and shared client logic | cloud, Node | 20 / 20 pass; `tsc --noEmit` clean under `strict` |
| Browser (Playwright + Chromium): start-up and token, each workspace, graphing, forms, export, worksheets, themes, narrow layout | cloud | 11 / 11 pass |

The tests were written against ground truth rather than against the code: known chemistry (molar masses, balanced equations, pH, titration equivalence), genetics (Hardy–Weinberg, Punnett ratios, codon table), statistics, textbook integrals and limits, unit identities, and closed forms checked with independent arithmetic. They found real problems, all fixed:

* Ideal-gas results were 1000× too small (wrong gas constant unit in three branches).
* Ionic charges such as `Fe^3+` lost their `+` when an equation was split into species.
* Exported CSV could carry spreadsheet formulas.
* A timeout (HTTP 408) was not shown as an error card in the client.
* A fast tab switch could show the wrong workspace (race in the shell).
* Matrix brackets were not drawn (a CSS specificity bug) and a matrix exponent floated mid-height.
* Result labels such as `pHAtEquivalence` were shown as "Phatequivalence".
* Near-zero roots such as 4·10⁻¹⁷ were shown instead of 0.
* A `normalcdf` example chip used the wrong argument list.
* The *Cross-check* button read fields the server never sends, so it would have shown an empty message; it now reports what the STEM agent said or why it did not run.
* **A Python 3.10 incompatibility** (a backslash inside an f-string expression, legal only from 3.12) that stopped the whole engine from importing on your machine. Found only by running the suite there; the cloud ran 3.13.

## 4. Integration with SLAI – verified on your computer

Run in your Linux VM with Python 3.10.12 against the real repository at `G:\GAIA\AI\SLAI`:

| Feature | Result |
| --- | --- |
| SLAI root detection, `src.utils.sldc` found | Works (SLDC 1.0.0 available) |
| Export to SLDC with the real `dumps_sldc` | Works (HTTP 200, file produced); the file was read back with SLAI's own `loads_sldc` (heading, calculation and result blocks present) |
| Export to Markdown, text, CSV, JSON | Work |
| Hand-off file (`slai-handoff/1`) for Reader | Works; Reader and Documaster are detected as installed, not running; SciCal prints the exact command to open the hand-off |
| Documaster's agent gateway | Found; loads |
| Privacy agent | **Resolves and reports ready** |
| Safety and Language agents, STEM cross-check | **Not usable in that VM**: the VM lacks `torch` and `scipy`. SciCal reports exactly that ("could not be imported") and keeps working; the cross-check says it did not run. These need your normal Python environment (the one that has the agents' dependencies). |
| The VM's `colorama` 0.4.4 is older than the agents need (`just_fix_windows_console` is 0.4.6+) | Same graceful message until the newer package is present |

Not verified: an agent actually writing an explanation, the Reader actually opening a hand-off file, and anything that depends on the Windows Python environment. Those need one run on your side: start SciCal normally, open the sparkle panel, press *Test the agents again*.

SciCal's statistics cross-check (the *Cross-check* button on repeated measurements) is **experimental** and only works with the SLAI STEM agent. When the agent cannot be created it says so and why (as in the VM above); it does not substitute another method.

## 5. Known limits

* Numerical analysis on graphs (roots, extrema, integrals, intersections) is marked *approximate*; extrema positions are good to about 10⁻⁸. Tangents are exact.
* Ionic charges must be written with a caret (`Cu^2+`, `NH4^+`); `Cu2+` is refused on purpose because it is ambiguous.
* The math list in a worksheet shows calculation and note entries; chemistry, biology, measurement and graph entries are listed under *Saved in this worksheet* in their own workspaces and appear in exports.
* Calculations are capped (see §2); very large factorials, powers and matrices are refused with a message instead of running for minutes.
* Plain-English input is rule-based and offline: it recognises common phrasings and offers proposals; it does not understand arbitrary sentences.
* SLDC export and hand-off require a SLAI checkout; without one the other four export formats still work.
* 3D: no implicit surfaces `F(x, y, z) = 0`; the painter's algorithm can mis-order interpenetrating surfaces; the jump heuristic may add a vertical riser to a deliberately stepped function; more than 160 samples per axis, 12 layers or 25 600 grid vertices per surface are refused.
* SGEO has no normals or per-vertex colour; point sets above 5 000 points are not saved as SGEO; an SDRW wireframe is orthographic whatever the screen showed and does not remove hidden lines; an SDRW contour at a level the surface sits exactly on (z = 0 of sin x cos y) can zig-zag by up to one grid cell; inequality shading and some layer kinds are not drawn in a 2D SDRW and are listed as left out.
* SGEO/SDRW strict validation needs `jsonschema` 4 or newer; with an older one SLAI validates structurally only and the dialog names the mode it used.
* No computer-algebra-style assumptions system (`assume(x>0)`).
* The browser tests ran on Chromium only.
* Screenshots in `docs/screenshots/` are real captures of the running application (1440×1300 for the desktop shots, 390×844 for mobile).
