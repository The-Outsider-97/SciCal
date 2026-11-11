# SciCal v2.4 — scientific 3D visualization and refinement

## Status and scope

The previous scientific-visualization work is present on **main**. The current refinement branch is `feature/science-visualization-refinement-v24`. This implementation is **committed but not production-verified**. Source changes and newly added tests are not evidence that tests passed. GitHub Actions for this branch reported failures; job logs were not accessible through the available GitHub connection. Check CI and run the Windows/browser validation below before merging.

Scientific calculations remain authoritative in `scical/domains`; the 3D viewer depicts them, never derives new chemical equations or gene sequences. Geometry is implemented by SciCal's existing `src/core/scene3d.ts` camera mathematics and the existing `src/client/science3d.ts` Canvas2D projection engine—no duplicate renderer or geometry pipeline.

## Implemented: Chemistry

The source-backed molecular catalogue now contains **seven** fixed neutral structures: H₂, O₂, H₂O, CO₂, NH₃, CH₄, and **C₃H₈ (propane)**. Propane uses the NIST CCCBDB optimized QCISD/6-311G** coordinates (11 atoms; 10 explicit single bonds), a calculated reference geometry, **not** an experimental molecular-dynamics trajectory. NIST source: https://cccbdb.nist.gov/geom3x.asp?basis=21&casno=2699798&method=5. Experimental bond lengths/angles are separately described at https://cccbdb.nist.gov/expgeom2.asp?casno=74986.

`scical/domains/chemistry/ops.py` validates each curated molecular graph before exposing it: exact formula/composition; neutral charge; connected bond graph; integer bond orders; finite, bounded coordinates; plausible bond lengths; no duplicate bonds; conventional closed-shell H/C/N/O valence for this limited catalogue; nonbonded atom near-collisions; and source link. Invalid/incomplete structures are not silently displayed as chemically connected molecules.

In `src/client/science3d.ts`, the renderer supports 3D balls and projected solid cylinders/rods as well as lines; selectable objects carry stable IDs/group IDs. The three molecule modes are ball-and-stick, van-der-Waals space filling, and wireframe. Multiple bonds use offset parallel rods. Fixed molecule centers are computed from the explicit atomic coordinates. Reaction viewers instantiate **each** molecule according to balanced stoichiometric coefficients; their positions are computed by deterministic 2D row packing using enclosing van-der-Waals bounding spheres plus clearance. This prevents unrelated molecules' enclosing volumes intersecting, without falsifying intramolecular van-der-Waals overlap in space-filling models. Selecting a molecular atom highlights its group and displays formula, instance and source.

For **C₃H₈ + 5O₂ → 3CO₂ + 4H₂O**, the 3D before/after state contains 1 propane + 5 oxygen molecules, then 3 carbon dioxide + 4 water molecules, with carbon=3, hydrogen=8, oxygen=10 on each side. The source-backed molecular viewer now supports these 6 and 7 separate instances (the prior 6-instance cutoff no longer hides the product side). Reactant/product frame transitions do not imply reaction trajectories, mechanisms or intermediates. Unsupported species retain a labeled composition-only fallback.

## Implemented: Atoms and quantum exploration

`packedNucleus` generates a deterministic face-centered-cubic (FCC) contact-point cluster with nearest-neighbor center distance 2r, exact proton/neutron count and centroid at the origin. It is **schematic sphere packing**, not a prediction of a nuclear wavefunction, density or measured nucleon positions. Missing isotope mass numbers remain unspecified; there is no inference from average atomic weight.

Each electron has a distinct identified educational circular path: individually oriented orthonormal planes, phase offsets, shell-dependent radii and a nuclear-clearance envelope. Correct electron count and the existing configuration parser remain authoritative; ionic shell placement is explicitly illustrative. Electron sphere radius is now **0.044 scene units = 80% of the previous 0.055**. These paths are not classical electron trajectories or a quantum wavefunction.

The shared scene adds **24 steps/s** alongside 1/2/5/10 steps/s, timer accumulation decoupled from individual rendering refreshes, restart, stable pause/scrub, selected-object highlighting, object-focus control, 280-ms focus interpolation (disabled under reduced-motion preference), and better segment picking. GPU acceleration and deterministic browser test evidence remain pending.

In the element dialog, selecting proton/neutron/electron displays NIST/PDG-backed classification, charge, spin, representative rest mass and relevant interaction properties, with particle targeting/zoom and breadcrumbs. Protons and neutrons can be explored as **uud/udd valence-quark schematics**; sea quarks and gluons are explicitly acknowledged, and geometric quark positions are **not** taken literally. The optional inline Standard Model table covers all six quark flavors, six leptons, gauge bosons and the Higgs boson; neutrino flavor masses are not falsely presented as exact. Source: Particle Data Group 2026 https://pdg.lbl.gov/2026/listings/particle_properties.html, and NIST CODATA 2022 https://physics.nist.gov/cuu/Constants/. Quark mass numbers are approximate and scheme/scale dependent.

## Implemented: Biology

DNA defaults to an educational **right-handed B-DNA** helix with continuous, round-joined sugar–phosphate backbones and distinct color-coded **cylindrical base rods**. Parameter references are rise≈0.34 nm/base pair and twist≈360°/10.5 base pairs. The two geometrical strands are antiparallel, labeled coding 5′→3′ and template 3′→5′. The adjustable angular backbone offset makes their separation/groove geometry visually distinguishable; this is not an atomistic major/minor-groove measurement. The optional hydrogen-bond indicators show two A–T and three G–C schematic links.

RNA is a **single** continuous tubular backbone with individually identifiable cylindrical bases. Its illustrative helical/curved path is **not** inferred RNA secondary structure. DNA and RNA scenes provide layer display modes (backbones/bases, optional H bonds), stable 3D object identity and codon group IDs. The existing centrally defined base palette remains A green, U red, C blue, G yellow and T purple; an independent high-distinction accessible palette is now available for DNA/RNA/transcription and translation scenes.

Transcription uses the computed template-derived sequence, adding one cylindrical RNA base per step as DNA opens locally and reanneals. Translation uses cylindrical codons/anticodons, an illustrative ribosome and a calculated amino-acid chain; stop remains a release-factor event, not a tRNA anticodon. Mutation and explicit exon-splicing before/after viewers now reuse the same improved geometry and palettes. Where input sequences exceed 80 bases, interactive geometry previews are capped and labeled (full deterministic sequence results are not invented/truncated silently).

Nucleotide colors, codon segmentation, 5′/3′ orientation and animations are preserved from the existing Biology calculation methods; no new gene translator or RNA splicing predictor was invented.

## Modified files and reuse

- `src/client/science3d.ts` — shared Canvas scene, rods and picking, nucleus/electron geometry, molecules/layout, DNA/RNA, conceptual quark model, animation controls and accessible palette.
- `src/client/domain-views.ts` — element particle inspection, camera targets and Standard Model explorer.
- `src/client/views/domain.ts` — larger source-backed balanced reaction scenes and existing worksheet-result integration.
- `src/client/styles.css` — coherent SciCal controls, inspection panels and accessibility.
- `scical/data/molecular_structures.json` — curated propane optimized conformer and explicit bonding, provenance note.
- `scical/domains/chemistry/ops.py` — strengthened source structure validation, unchanged balancing engine.
- `tests_ts/science3d.test.ts` and `tests/test_domains.py` — deterministic geometry, scientific and integration regression cases.

All other math, workbook, viewer, and code-generation workflows are intended to remain unchanged; this is **not** a verified assertion of non-regression.

## Verification

Use the actual Windows SciCal checkout, from its repository root:

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
npm.cmd install --no-audit --no-fund
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
python -m scical
```

Acceptance scenarios:
1. Chemistry → Balance equation → `C3H8 + O2 -> CO2 + H2O`. Verify exactly 6 separate reactant and 7 separate product molecules, distinguishable bonded carbon/oxygen/water/propane structures, three display modes and no disconnected atoms.
2. Chemistry → Periodic table → H, He, O, C, Fe and a selected heavy isotope. Verify exact particle counts, FCC nucleus contact, electron paths, 0.044 radius, 24 steps/s, pause/restart/scrub, particle inspection and valence-quark drilldown.
3. Biology → DNA/RNA sequence → inspect 20–50 nucleotides, rotate the continuous backbones, select cylindrical bases and codon groups, toggle palette and display modes, verify B-DNA right-handedness and opposite template orientation.
4. Biology → Transcription, translation, mutation and RNA processing: verify nucleotide-by-nucleotide animation and result/geometry consistency.
5. Existing math 3D graphing, worksheet saved-entry reopening, desktop scaling, dark/light theme, mouse/keyboard accessibility, PNG export, reduced-motion preference, time/resource limits, agent consent and fallback.

**Automation status:** Tests have been authored, but passing type checks, test results, interactive Windows verification, performance measurements and an error-free release build have **not** been established in the current session. CI failure summaries were observable, but their diagnostic logs were unavailable; do not merge solely because the PR branch has commits.

## Remaining limitations / nonimplemented items

- The Canvas2D projected-rod painter is not GPU instanced 3D mesh rendering; exact polygonal cylinder lighting/occlusion and demanding large-scene performance are not yet validated. True physical collision analysis is applied to model-space molecule envelopes; projected view overlap can still occur due to camera angle.
- Exact atomic and nucleon quantum states, quantitative orbital radial density, QCD lattice simulation, baryon wavefunctions, full nucleic-acid atomistic geometry, RNA secondary-structure prediction, protein folding, enzymatic kinetics and reaction mechanisms are not simulated.
- Model-specific session scene state (camera, display style, animation time) is not serialized as a separately editable scientific object. Calculated worksheet results remain in the existing worksheet architecture.
- Only seven neutral molecular structures are in the curated offline catalogue. Runtime external structure lookup, other conformers and formal geometry uncertainty/provenance contracts require further implementation.
- Advanced SLAI Spatial, Simulation, Optimization, Observability, Verification and Provenance-agent invocation has not been added here. The existing deterministic calculations, STEM integration and consent-gated explanations remain authoritative. Integration requires inspecting and verifying the real agent interfaces rather than inventing them.
- Automated browser screenshots, memory/performance baselines, full cross-platform testing and independently validated accessibility remain pending.

The above limitations must remain visible; never conflate educational schematics with experimentally validated atomic, molecular, or biomolecular dynamics.
