# SciCal user guide

## The window

Workspaces along the top – **Mathematics, Graphing, Chemistry, Biology, Measurement, Formulas, STEM Lab, Finance, Constants** – then your worksheet name, search, the SLAI assistant and settings. Arrow keys move between the tabs.
Everything you calculate is stored in the current **worksheet** and saved on this computer automatically (the dot beside the worksheet name shows the save state).

## Mathematics

Type in the box at the bottom and press **Enter** (Shift+Enter adds a line, ↑ recalls earlier input, Esc clears). The keypad has Basic, Scientific, Algebra & calculus and Units pages.

![Mathematics](screenshots/math.png)

* **Exact first.** `1/3 + 1/6` is `1/2`, `sqrt(8)+sqrt(2)` is `3√2`. Results that are rounded say *approximate*; use **Exact / Decimal** on a card or the global Result switch to change the view.
* **Algebra and calculus:** `solve(x^2 - 5*x + 6 = 0)`, `diff(x^3*sin(x), x)`, `integral(x^2, x, 0, 3)`, `limit`, `taylor`, `factor`, `expand`, `simplify`, `nsolve`.
* **Linear algebra:** `[[1,2],[3,4]]^-1`, `det`, `eigenvals`, `rref`, `linsolve`.
* **Statistics:** `mean([1,2,3])`, `std`, `corr`, `normalcdf(x,mu,sigma)`, `normalprob(a,b,mu,sigma)`, `invnorm(p,mu,sigma)`, `binompdf(n,p,k)`, `tinterval`.
* **Units:** switch *Units* on, then `12 in -> cm`, `60 mph -> m/s`. Adding incompatible units is an error, not a guess.
* **Variables and functions:** `a := 5`, `f(x) := x^2 + 1`. Definitions apply to the lines after them in the worksheet and to the graphs.
* **Angles** are radians, degrees or gradians (Angle switch). **Complex** mode allows `sqrt(-4)`.
* Each card has buttons to re-run, add to a note, copy, copy as LaTeX, show the normalized input, **explain** (SLAI assistant) and delete. Errors say what is wrong and where (the offending part is underlined).

* **Plain English.** Type a sentence such as `convert 5 miles to km` or `molar mass of C6H12O6` and SciCal offers one or more proposals (calculator input or a workspace operation). It never calculates from the sentence itself – you pick a proposal and the exact engine runs it. This reader is rule-based and offline.

There are 143 built-in functions in 14 groups (arithmetic, number theory, trigonometry, hyperbolic, complex, vectors, matrices, statistics, distributions, algebra, calculus, control, constants, number bases). The keypad pages cover the common ones; the rest are typed by name.

## Graphing

![Graph](screenshots/graph.png)

Add layers (a function, a curve, data…). Each layer accepts what you would write on paper: `y = sin(x)`, `x^2 + y^2 = 4`, `y > x^2`, `x = 2`, parametric `(cos(t), sin(t))`, polar `r = 1 + cos(theta)`, sequences, vector fields, scatter data with a fit, histograms.

* Free letters become **sliders** (`a*sin(b*x)`), and definitions from the worksheet are available.
* Drag to pan, wheel or pinch to zoom, arrow keys to move, hover or focus to **trace**.
* **Analyse:** roots, extrema, integral between bounds, intersections of two layers, value at x, tangent at x. Numerical results are labelled approximate; the tangent is exact.
* **Table of values**, **PNG export**, and **Add to worksheet** (the layers and window are stored and can be re-opened).

![Sliders](screenshots/graph-slider.png)

## Chemistry

![Titration](screenshots/chemistry-titration.png)

![Atom model](screenshots/chemistry-atom.png)

Periodic table with isotopes (opening an element shows a 3D atom: protons and neutrons as touching spheres in the nucleus with their totals, e.g. *26 p⁺ · 30 n⁰ · 26 e⁻ · Fe-56*, and each electron on its own orbit in its own plane; when no isotope is chosen it uses the most abundant natural isotope, or the longest-lived one, and says so) · molar mass and percent composition · equation balancing (exact) · stoichiometry with limiting reagent and yield · empirical formula · solutions and dilutions · pH, buffers and titration curves · gas laws · thermochemistry · ICE equilibrium tables.
Choose an operation on the left, fill in the form (or press **Load example**), then **Calculate**. Results show the numbers, the working steps and any assumptions (for example *25 °C, activity coefficients ignored*).
Charges on ions must be written unambiguously: `Cu^2+`, `NH4^+`. A bare `Cu2+` is refused with a hint, because it could mean two copper atoms.

## Biology

DNA/RNA sequence statistics, translation, open reading frames, restriction sites, protein properties, Hardy–Weinberg, Punnett squares, population growth, enzyme kinetics (Michaelis–Menten fit), colony counts and OD, and the standard genetic code. DNA and RNA are drawn as a double helix: two purple sugar–phosphate backbones joined by cylinder bases (A yellow, T pink, U brown, C blue, G green); *Play* turns it slowly, and the transcription and translation scenes step through the process.

![Punnett square](screenshots/biology-punnett.png)

![DNA double helix](screenshots/biology-dna.png)

## Measurement

Significant figures, error propagation (with the formula and each term's contribution), repeated measurements (mean, standard deviation, 95 % interval), with a STEM check on the results (see below), percent error, calibration curves with an unknown, unit conversion, dimensional analysis, the unit catalogue and physical constants (each with its source and uncertainty).

![Calibration](screenshots/measurement-calibration.png)

## Formulas

A library of scientific formulas with variables, units and dimensions. **Solve for a variable** rearranges exactly and checks dimensions; **Analyse an equation** reports its dimensional consistency.

## STEM Lab

![Differential equations](screenshots/stem-lab-ode.png)

The STEM Lab is where SLAI's STEM agent does the computing. SciCal reads your expressions, hands the agent numbers and functions, and shows what comes back, labelled as the agent's work. The agent runs on this computer, uses no language model, and seeded runs repeat exactly. Pick an operation on the left, fill in the form (or press **Load example**), then **Calculate**.

| Operation | What you get |
| --- | --- |
| **Differential equations** | A system such as `x' = v`, `v' = -k*x` solved with Euler, RK4 or adaptive RK45, optionally all three side by side; solution and phase-portrait plots |
| **Monte-Carlo uncertainty** | A formula with uncertain inputs sampled with a seed, next to the first-order result |
| **Numerical integration** | Six rules, each one's error measured against SciCal's exact integral |
| **Root finding** | Bisection, secant and Newton–Raphson, with iterations and residuals |
| **Linear systems and conditioning** | The solution, the condition number, the residual and the digits lost, next to SciCal's exact solution |
| **Interpolation** | Line, cubic spline and polynomial through your points, with values between them |
| **Bootstrap interval** | A confidence interval for the mean, median or standard deviation without assuming a normal distribution (seeded) |
| **What the agent offers** | Every domain and operation the connected agent provides |

Each run has limits (about 60 000 function evaluations and 25 seconds); an operation that exceeds them stops and says so.

## STEM checks

![A STEM check on an integral](screenshots/stem-check-math.png)

The **shield** button on a calculation (and **STEM check** on a workspace result) asks the STEM agent to compute the same thing again by a different route – for example it integrates `x^2` from 0 to 3 numerically while SciCal integrates it exactly – and compares the two. The result is a badge:

* **agrees** – both values match within the tolerance shown (closed forms 10⁻⁹ relative, numerical derivatives 10⁻⁶, quadrature 10⁻⁷);
* **differs** – they do not match; the difference is shown. SciCal's value is still the one displayed, and the badge is a reason to look closer;
* **skipped** – the agent has no way to check this (for example a unit its table does not know, such as `in`); the reason is given;
* **failed** – the agent could not run the check.

Checks are available for scalar values, statistics and distributions, derivatives and integrals, equation solutions, matrix inverses, eigenvalues and linear systems, unit conversions, and for repeated measurements, calibration, uncertainty budgets, formula uncertainty, formula solving, the ideal gas law and Michaelis–Menten fits. The badge is saved with the worksheet entry and appears in Markdown, text and SLDC exports (only when a check actually ran).

![A STEM check on a measurement](screenshots/stem-check-measurement.png)

In **Settings → SLAI STEM agent**, *STEM checks* can be **On request** (default, a button on each result), **After every calculation**, or **Off**, which hides the buttons. Unlike the explain and language agents, the STEM agent needs no per-worksheet permission, because it never reads your text: it receives numbers and expressions only. `--agents none` turns it off together with the other agents.

## Worksheets, search and export

Click the worksheet name to create, open, rename, delete, import and export worksheets. The search button looks through all of them. **Export** offers Markdown, plain text, CSV and JSON as downloads, and SLDC when SciCal can find a SLAI installation. In the SLDC file each calculation is stored as typeset equations (LaTeX), exactly as SciCal shows it, together with the text you typed, so Reader draws the formulas instead of showing `7*sqrt((5/8))`. **Send to another SLAI application** hands the worksheet to Reader or Documaster when they are running. Cells that start with `=`, `+`, `-` or `@` are neutralised in CSV so a spreadsheet cannot run them as formulas.

![Worksheets](screenshots/worksheets.png)

## 3D graphing

Graphing has a **2D | 3D** switch. In 3D, each layer is one of: a surface `z = f(x, y)` (type `sin(x)*cos(y)` or `z = x^2 - y^2`), a parametric surface `(x(u, v), y(u, v), z(u, v))`, a space curve `(x(t), y(t), z(t))`, or a set of points `x y z` (one per line).

* **Move:** drag to rotate, shift-drag or right-drag to move, scroll or pinch to zoom, double-click to reset; arrow keys, `+`, `-` and `0` work when the plot has focus. Click a point to mark it and read its coordinates.
* **Motion:** the view presets and *Reset view* glide to the new view instead of jumping; a quick flick keeps turning and slows to a stop (touch the scene to stop it at once); **Spin** turns the scene slowly about the vertical axis until you switch it off. On a slider, **Play** sweeps it back and forth from where it is, so you can watch a family of surfaces change; **Pause** stops it. With *Reduce motion* on (Settings, or your system's setting) none of this animates: views change at once, Spin and Play are off.
* **Layers:** colour, opacity, wireframe, and colour by height; a letter that has no value (the `a` in `a*sin(x)*cos(y)`) becomes a slider.
* **Domain and sampling:** x and y ranges, up to 160 samples per axis, and an optional z window that cuts off very tall parts. Where a formula is not a real number (a pole, the square root of a negative) the surface is left open: it is shown as a gap and never bridged.
* **View:** perspective or orthographic, proportions (automatic keeps a sphere round; *fit to box* stretches; *equal scale*), axes, grid, legend, and Isometric/Top/Front/Side presets.
* **Save PNG** makes a picture with a transparent background. **Add to worksheet** keeps the scene (formulas, sliders, camera) and its picture, so SReader can show it with its formulas.

### Saving as SGEO or SDRW

Under the plot, **Save as** writes a file with SLAI's own writers, checks it with SLAI's validator and opens it again before reporting success. The dialog that follows says what is in the file, what was left out and why, and what to know.

| Button | You get | Is it the model? |
| --- | --- | --- |
| **SGEO model** (3D) | meshes for surfaces, curves for curves, points for points; each formula, domain and the sampling are stored beside the geometry, with a provenance claim | The sampled approximation of the formulas (float64), not the exact surface |
| **SDRW wireframe** (3D) | a 2D drawing of the grid lines from the current camera, orthographic, hidden lines not removed | No: derived and lossy, labelled as such in the drawing and its metadata |
| **SDRW contours** (3D) | a contour map of explicit surfaces `z = f(x, y)` | No: derived and lossy; other layer kinds are listed as left out |
| **SDRW drawing** (2D) | axes, grid and every curve as polylines, one drawing layer per graph layer, in the layer's colour | The curves as sampled for the current view |

SGEO stores no normals and no per-vertex colour, so a surface coloured by height is saved in its base colour (the z range is kept in its metadata). A graph has no unit of its own: the **unit** choice says what one graph unit is in the file. A saved file is never overwritten; a second save gets `-2`, `-3`, and so on. A copy is kept in the SciCal output folder as well as being downloaded.

## Finance

The Finance workspace has 24 calculators in groups: interest and rates, annuities and loans (with amortisation schedules and loan comparison), investment appraisal (NPV, IRR, discounted cash flow, payback, ROI, CAGR), inflation, percentage change, elasticity, break-even and profit, supply and demand (equilibrium, surpluses, tax incidence), growth and trend, and sensitivity tables. Each result shows its formula, the assumptions it made, the working, and exact values where they exist. **Open in Graphing** (on results that have a curve) carries the formula and its sliders into the Graphing workspace.

## Constants

The Constants page lists 85 physical constants with their symbol, value, uncertainty, unit and source (CODATA 2022 where it applies). Click one to insert it into a calculation, or convert it to another unit. There is one store of constants; Finance preferences are separate.

## Settings

Theme (follow the system, light, dark, high contrast), text size, reduce motion, angle unit, significant digits (6–100), notation (automatic, fixed, scientific, engineering), digit grouping and STEM checks (off, on request, after every calculation). Units mode and complex mode are switches above the calculation list. All are saved on this computer.

| Light | Dark | High contrast |
| --- | --- | --- |
| ![](screenshots/graph.png) | ![](screenshots/theme-dark-graph.png) | ![](screenshots/theme-contrast-graph.png) |

## The SLAI assistant (optional)

The sparkle button shows which SLAI agents SciCal can reach. **Explain** on any result always gives a worked explanation built by SciCal itself; if you allow agents for the worksheet, an agent can add a plain-language version, after SLAI's Privacy agent has seen the text first. The panel also shows whether the STEM agent is connected. Agents never decide a number: every value comes from the deterministic engine, and the STEM agent only checks it. Agents are off per worksheet until you allow them, and off entirely with `--agents none`.

## Phone and narrow windows

On a narrow screen the workspace tabs become a **bar at the bottom** (with labels), the operation list is one row you can swipe, the input sits just above the bar, and the page respects the notch and home indicator. Text fields are large enough that iPhones do not zoom in when you tap them. The keypad moves under the input.

SciCal also runs as a Windows program and as Android and iOS apps; see [MOBILE_AND_DESKTOP.md](MOBILE_AND_DESKTOP.md).

![Mobile](screenshots/mobile-math.png)
