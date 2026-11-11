# SciCal v2.4 — Scientific visualization integration

## Implementation status (feature branch; verification required)

This branch adds a **scientifically constrained, schematic visualization layer**, not a validated molecular dynamics engine. It builds on the existing SciCal camera/projection utilities and calculators. Chemistry and biology still use the authoritative domain results, which are independent of the renderer.

### Implemented in this branch

- `src/client/science3d.ts`: one reusable Canvas2D scientific-scene interface with the existing `src/core/scene3d.ts` camera, selection, orbit/zoom/pan, export PNG, timeline, speed and pause.
- Chemistry: periodic-table element dialog integrates an atom shell/nucleus schematic; proton/electron counts and available isotope-specific neutron counts update. Elements without recorded isotope mass numbers state that neutron count is unknown. The existing balance operation provides exact stoichiometric atom inventories for an illustrative pre/post scene. Six offline source-backed molecules (H₂, O₂, H₂O, CO₂, NH₃, CH₄) are drawn with explicit NIST CCCBDB atom coordinates and bonds in Molar Mass and compatible balanced reaction results. No molecular connectivity or mechanistic pathway is inferred from a formula.
- Biology: DNA/RNA 3D nucleotide models (bounded visual preview), strand-oriented deterministic transcription, AUG-driven standard-code peptide synthesis, stop handling, and a frame-specific mutation operation for substitutions/insertions/deletions. Every simulation is based on calculated nucleotides and codons.
- Genetic-code explorer: the existing NCBI standard code table is presented as 64 **RNA** codons in searchable table and interactive circular forms with consistent base coloring.
- Existing domain form catalogue, worksheet result paths, explanation actions, and visual styles are reused; no parallel chemical equation solver or genetic code table was added.
- Regression tests were added for scientific data contracts and scene geometry. CI workflow added; results must be checked before claiming verification.

### Deliberate scientific limitations

- The circular diagram is a codon **lookup** aid; it is not a model of physical RNA geometry.
- Nucleus/nucleon positions and electron trajectories are not physical quantum states. Shell occupations for ions are illustrative, not computed self-consistent ionic configurations. Isotopes not in `scical/data/elements.json` are not fabricated.
- Molecular bonds and coordinates are displayed **only** for the six curated neutral reference structures. Unsupported molecules fall back to composition inventories, not invented geometry; no orbital density, reaction pathway, or molecular dynamics is generated from a formula.
- DNA/RNA paths, tRNA positions, ribosomes, amino-acid chain, and transcription polymerase are simplified depictions; promoter recognition, enzyme kinetics, RNA processing, folding and regulation are not simulated.
- The 3D painter/Canvas2D approach does not provide GPU molecular rendering or reliable transparency/occlusion for all geometry.
- 3D scene runtime state (camera, elapsed animation time, view style) and scene PNG are not yet saved as an editable scientific scene inside the worksheet. Numeric operation/results still save through existing worksheets. Manual PNG snapshot is available.
- Long sequences are capped visually; the renderer does not silently extend unknown bases or infer amino acids.
- SLAI integration currently reuses the app's **existing** consent-gated explanation and cross-check paths. Arbitrary new Spatial, Simulation, Verification and other agent calls have **not** been claimed as implemented.
- Protein folding prediction, population-specific genetic code, and quantum orbital electron density are not implemented.
- Existing isotopic coverage is sparse and must be extended with validated datasets before all elements can show isotope-dependent neutron counts. Curated molecular coordinates/bonds are stored in `scical/data/molecular_structures.json` with each NIST CCCBDB source link and Å units.
- User-supplied screenshots are visual references, not primary scientific evidence.

### Verification commands (SciCal checkout)

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
npm.cmd install --no-audit --no-fund
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
python -m scical
```

In the UI verify: periodic table → hydrogen/carbon → isotope and ion charge, biology → transcription, protein synthesis, mutation, genetic code search/wheel; chemistry → balance water equation; worksheet save/reopen; PNG snapshot; invalid inputs; dark mode and keyboard operation.

The new CI workflow runs unit tests, typecheck and build on GitHub Actions. Do not interpret a commit alone as test success.

## Architectural constraints and future acceptance criteria

Keep authoritative results in `scical/domains` and renderer/view state in `src/client`. Add genuine molecular structures only with source-backed structure identifiers/coordinates, units and provenance. Implement quantum orbital modes with clearly specified wavefunction assumptions. Require reproducible snapshots and bounded workloads; add browser-driven tests for animation and worksheet restore. Integrate SLAI agents only through actually present, consent-respecting gateway APIs with deterministic validation first. Avoid replacing the working 3D graph system with a duplicate engine.
