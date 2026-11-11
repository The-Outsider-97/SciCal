import test from 'node:test';
import assert from 'node:assert/strict';
import { atomScene, electronOrbits, electronShells, dnaScene, rnaScene, nucleotideColor, transcriptionScene, translationScene, reactionScene, moleculeScene, molecularReactionScene, orbitalAngularScene, nucleusScene, rnaProcessingScene } from '../src/client/science3d.js';

test('scientific color mapping distinguishes all RNA bases and DNA thymine', () => {
  const bases = ['A', 'U', 'C', 'G', 'T'];
  assert.equal(new Set(bases.map(nucleotideColor)).size, bases.length);
  assert.equal(nucleotideColor('N').startsWith('#'), true);
});

test('electron counts use element configuration including noble-gas core', () => {
  assert.deepEqual(electronShells('[Ar] 3d6 4s2', 26), [2, 8, 14, 2, 0, 0, 0]);
  assert.equal(electronShells('[Ar] 3d6 4s2', 25).reduce((x, y) => x + y, 0), 25);
  assert.equal(electronShells('[Ar] 3d6 4s2', 27).reduce((x, y) => x + y, 0), 27);
  assert.deepEqual(electronShells('', 0), []);
});

test('atomic models never fill in unknown isotopes', () => {
  const helium = atomScene(2, null, 0, '1s2');
  assert.match(helium.description, /neutron count.*unknown/i);
  const deuterium = atomScene(1, 2, 0, '1s1');
  const objects = deuterium.at(0);
  assert.equal(objects.filter((s) => s.kind === 'ball' && s.color === '#d94b51').length, 1);
  assert.equal(objects.filter((s) => s.kind === 'ball' && s.color === '#8c959f').length, 1);
});

test('DNA model has exactly one complementary pair per shown base', () => {
  const dna = dnaScene('ATGC');
  const bases = dna.at(0).filter((s) => s.kind === 'rod');
  assert.equal(bases.length, 8);
  const rna = rnaScene('AUG');
  assert.equal(rna.at(0).filter((s) => s.kind === 'rod').length, 3);
});

test('transcription model adds exactly one RNA nucleotide per step', () => {
  const scene = transcriptionScene('ATGC', 'AUGC');
  assert.equal(scene.frames, 5);
  const n = (frame: number) => scene.at(frame).filter((s) => s.kind === 'rod').length;
  assert.equal(n(3) - n(0), 3);
});

test('translation uses the validated codon list and does not add an amino acid for stop', () => {
  const scene = translationScene('AUGCCAUAA', [
    { codon: 'AUG', aa: 'M', anticodon: 'UAC' },
    { codon: 'CCA', aa: 'P', anticodon: 'GGU' },
    { codon: 'UAA', aa: '*' },
  ], 0);
  assert.equal(scene.frames, 4);
  assert.match(scene.frameLabel?.(3) ?? '', /Stop/);
  const final = scene.at(3).filter((s) => s.kind === 'ball' && s.color === '#38a9a4');
  assert.equal(final.length, 2);
});

test('stoichiometric atom totals are represented exactly for supported small scenes', () => {
  const scene = reactionScene(
    [{ species: 'H2', coefficient: 2, atoms: { H: 2 } }, { species: 'O2', coefficient: 1, atoms: { O: 2 } }],
    [{ species: 'H2O', coefficient: 2, atoms: { H: 2, O: 1 } }],
  );
  const count = (f: number) => scene.at(f).filter((p) => p.kind === 'ball').length;
  assert.equal(count(0), 6);
  assert.equal(count(1), 6);
});


test('source-backed molecules show explicit bond topology without inventing bonds', () => {
  const water = {
    formula: 'H2O', name: 'Water', charge: 0,
    source: 'https://cccbdb.nist.gov/', atoms: [
      { element: 'O', xyz: [0, 0, .1173] as [number, number, number] },
      { element: 'H', xyz: [0, .7572, -.4692] as [number, number, number] },
      { element: 'H', xyz: [0, -.7572, -.4692] as [number, number, number] },
    ], bonds: [{ a: 0, b: 1, order: 1 }, { a: 0, b: 2, order: 1 }],
  };
  const render = moleculeScene(water);
  assert.equal(render.frames, 2);
  assert.equal(render.at(0).filter((p) => p.kind === 'ball').length, 3);
  assert.equal(render.at(0).filter((p) => p.kind === 'line').length, 2);
  assert.equal(render.at(1).filter((p) => p.kind === 'line').length, 0);
  assert.match(render.description, /reference geometry/i);
  const reaction = molecularReactionScene(
    [{ species: 'H2O', coefficient: 1, atoms: { H: 2, O: 1 }, structure: water }],
    [{ species: 'H2O', coefficient: 1, atoms: { H: 2, O: 1 }, structure: water }],
  );
  assert.equal(reaction.at(0).filter((p) => p.kind === 'ball').length, 3);
  assert.equal(reaction.at(1).filter((p) => p.kind === 'ball').length, 3);
});


test('orbital displays are angular approximations and distinguish phase', () => {
  for (const symbol of ['s', 'p', 'd', 'f'] as const) {
    const scene = orbitalAngularScene(symbol);
    assert.match(scene.description, /radial wavefunction.*NOT calculated/i);
    const dots = scene.at(0).filter((p) => p.kind === 'ball');
    assert.ok(dots.length > 150, symbol);
    assert.ok(dots.every((p) => p.kind === 'ball' && p.r > 0));
  }
  const protonOnly = nucleusScene(1, null, '1s1');
  assert.equal(protonOnly.at(0).filter((p) => p.kind === 'ball').length, 1);
});

test('RNA processing viewer switches from precursor to spliced transcript', () => {
  const scene = rnaProcessingScene('AUGGAAUUUCCCUAA', 'AUGGAACCCUAA');
  assert.equal(scene.frames, 2);
  assert.equal(scene.at(0).filter((p) => p.kind === 'rod').length, 15);
  assert.equal(scene.at(1).filter((p) => p.kind === 'rod').length, 12);
  assert.match(scene.frameLabel?.(1) ?? '', /mature mRNA/);
});

// ---------------------------------------------------------------------------------------------------------------- atoms and nucleic acids
import * as fs from 'node:fs';
const readFileSync = (path: URL, enc: string): string => (fs as unknown as { readFileSync(p: URL, e: string): string }).readFileSync(path, enc);
import { referenceIsotope, ELEMENT_COUNT } from '../src/core/isotopes.js';
import { nucleonLayout, protonMask, ELECTRON_RADIUS, capOpening } from '../src/client/science3d.js';

const dist = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

test('nucleons touch and never overlap', () => {
  for (const n of [1, 2, 3, 12, 56, 118, 238, 294]) {
    const r = 0.05;
    const pts = nucleonLayout(n, r);
    assert.equal(pts.length, n);
    let touching = 0;
    for (let i = 0; i < n; i++) {
      let hasNeighbour = n === 1;
      for (let j = i + 1; j < n; j++) {
        const d = dist(pts[i], pts[j]);
        assert.ok(d >= 2 * r - 1e-9, `n=${n}: nucleons ${i} and ${j} overlap (${d} < ${2 * r})`);
        if (d <= 2 * r + 1e-9) { hasNeighbour = true; touching++; }
      }
      if (!hasNeighbour) { for (let j = 0; j < i; j++) if (dist(pts[i], pts[j]) <= 2 * r + 1e-9) hasNeighbour = true; }
      assert.ok(hasNeighbour, `n=${n}: nucleon ${i} touches no other`);
    }
    if (n > 3) assert.ok(touching >= n * 2, 'a packed cluster has many contacts');
  }
  assert.deepEqual(nucleonLayout(56, 0.05), nucleonLayout(56, 0.05), 'the same nucleus every time');
});

test('the nucleus is compact: close to a sphere, not a string or a plane', () => {
  const pts = nucleonLayout(120, 0.05);
  const ext = [0, 1, 2].map((k) => Math.max(...pts.map((p) => p[k])) - Math.min(...pts.map((p) => p[k])));
  assert.ok(Math.max(...ext) / Math.min(...ext) < 1.35, ext.join(','));
});

test('protons and neutrons are mixed in exact numbers', () => {
  for (const [n, z] of [[56, 26], [1, 1], [2, 1], [238, 92], [4, 2], [10, 0], [7, 7]]) {
    const m = protonMask(n, z);
    assert.equal(m.length, n);
    assert.equal(m.filter(Boolean).length, z);
  }
  const m = protonMask(40, 20);
  assert.ok(m.slice(0, 20).filter(Boolean).length > 5 && m.slice(20).filter(Boolean).length > 5, 'not all protons on one side');
});

test('every element has a reference isotope and its atom shows exactly that many protons and neutrons', () => {
  const data = JSON.parse(readFileSync(new URL('../scical/data/elements.json', import.meta.url), 'utf8')) as { elements: Array<{ z: number; symbol: string; weight: string; configuration: string }> };
  assert.equal(data.elements.length, ELEMENT_COUNT);
  for (const el of data.elements) {
    const iso = referenceIsotope(el.z);
    if (!iso) throw new Error('no reference isotope for ' + el.symbol);
    assert.ok(iso.neutrons >= 0 && iso.a >= el.z, el.symbol);
    if (iso.kind === 'most abundant natural isotope') assert.ok(Math.abs(iso.a - Number(el.weight)) < 4.6, `${el.symbol}: A=${iso.a} vs weight ${el.weight}`);
    const scene = atomScene(el.z, iso.a, 0, el.configuration);
    const balls = scene.at(0).filter((p) => p.kind === 'ball');
    assert.equal(balls.filter((p) => p.kind === 'ball' && p.label === 'p+').length, el.z, el.symbol + ' protons');
    assert.equal(balls.filter((p) => p.kind === 'ball' && p.label === 'n').length, iso.neutrons, el.symbol + ' neutrons');
    assert.match(scene.caption ?? '', new RegExp(`${el.z} p⁺ · ${iso.neutrons} n⁰`));
  }
  assert.equal(referenceIsotope(26)?.a, 56);
  assert.equal(referenceIsotope(92)?.kind, 'most abundant natural isotope');
  assert.equal(referenceIsotope(118)?.kind, 'long-lived isotope');
  assert.equal(referenceIsotope(0), null);
});

test('every electron has its own orbit in its own plane, and the orbits never cross; electrons are 20 % smaller', () => {
  assert.ok(Math.abs(ELECTRON_RADIUS - 0.055 * 0.8) < 1e-9);
  const scene = atomScene(26, 56, 0, '[Ar] 3d6 4s2');
  const parts = scene.at(0);
  const electrons = parts.filter((p) => p.kind === 'ball' && p.label === 'e−');
  assert.equal(electrons.length, 26);
  // each orbit ring is found from its drawn segments: the distance of every segment end from the nucleus is that orbit's radius
  const radiiOfLines = new Set<string>();
  for (const p of parts) if (p.kind === 'line') radiiOfLines.add(Math.hypot(p.a[0], p.a[1], p.a[2]).toFixed(4));
  const radii = [...radiiOfLines].map(Number).sort((a, b) => a - b);
  assert.equal(radii.length, 26, 'one orbit per electron');
  for (let i = 1; i < radii.length; i++) assert.ok(radii[i] - radii[i - 1] > 0.03, 'the radii differ, so no two circles about the nucleus can meet');
  for (const e of electrons) if (e.kind === 'ball') {
    assert.equal(e.r, ELECTRON_RADIUS);
    const d = Math.hypot(e.p[0], e.p[1], e.p[2]);
    assert.ok(radii.some((r) => Math.abs(d - r) < 1e-3), 'each electron is on an orbit');
  }
  const orbits = electronOrbits(electronShells('[Ar] 3d6 4s2', 26), .8);
  const planes = new Set(orbits.map((o) => o.normal.map((c) => c.toFixed(3)).join(',')));
  assert.equal(planes.size, 26, 'every orbit lies in a different plane');
  for (const o of orbits) assert.ok(Math.abs(o.u[0] * o.v[0] + o.u[1] * o.v[1] + o.u[2] * o.v[2]) < 1e-9 && Math.abs(o.u[0] * o.normal[0] + o.u[1] * o.normal[1] + o.u[2] * o.normal[2]) < 1e-9, 'a proper plane');
  const nucleons = parts.filter((p) => p.kind === 'ball' && (p.label === 'p+' || p.label === 'n'));
  const farthest = Math.max(...nucleons.map((p) => (p.kind === 'ball' ? Math.hypot(p.p[0], p.p[1], p.p[2]) + p.r : 0)));
  assert.ok(radii[0] > farthest + 0.1, 'the nucleus sits inside the innermost orbit');
});

test('nucleotides are cylinders joined by two purple backbones', () => {
  const dna = dnaScene('ATGCATGC').at(0);
  const rods = dna.filter((p) => p.kind === 'rod');
  assert.equal(rods.length, 16);
  assert.equal(dna.filter((p) => p.kind === 'ball').length, 0, 'no spheres');
  const colours = new Set(rods.map((r) => (r.kind === 'rod' ? r.color : '')));
  assert.ok(['A', 'T', 'G', 'C'].every((b) => colours.has(nucleotideColor(b))));
  const backbone = dna.filter((p) => p.kind === 'line');
  assert.ok(backbone.length >= 2 * 7 * 3, 'a continuous backbone on each strand');
  assert.equal(new Set(backbone.map((l) => (l.kind === 'line' ? l.color : ''))).size, 2, 'two ribbons');
  for (const p of rods) if (p.kind === 'rod') { assert.ok(p.r > 0); assert.ok(dist(p.a, p.b) > 0.05); }
  const rna = rnaScene('AUGGCU').at(0);
  assert.equal(rna.filter((p) => p.kind === 'rod').length, 6);
  assert.ok(rna.filter((p) => p.kind === 'line').length >= 5, 'the RNA has a backbone too');
  const transcription = transcriptionScene('ATGC', 'AUGC').at(2);
  assert.ok(transcription.some((p) => p.kind === 'line'), 'transcription keeps the backbones');
  assert.equal(transcription.filter((p) => p.kind === 'ball' && p.label === 'Pol').length, 1);
});

test('a cylinder end cap opens as the axis turns towards the viewer', () => {
  assert.equal(capOpening([0, 0, 1], [0, 0, 1]), 1);
  assert.ok(Math.abs(capOpening([1, 0, 0], [0, 0, 1]) - 0.1) < 1e-9, 'edge-on: only a sliver (never zero)');
  assert.ok(Math.abs(capOpening([1, 0, 1], [0, 0, 1]) - Math.SQRT1_2) < 1e-9);
  assert.equal(capOpening([0, 0, 0], [0, 0, 1]), 0.1);
});
