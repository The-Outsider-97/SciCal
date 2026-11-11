import test from 'node:test';
import assert from 'node:assert/strict';
import {
  atomScene, electronShells, dnaScene, rnaScene, nucleotideColor, transcriptionScene,
  translationScene, reactionScene, moleculeScene, molecularReactionScene,
  orbitalAngularScene, nucleusScene, rnaProcessingScene, packedNucleus, nucleusParticles,
  electronOrbits, NUCLEON_RADIUS, EDUCATIONAL_ELECTRON_RADIUS,
  ELECTRON_TRACK_GAP, animationFrameIndex,
  DNA_HELIX, dnaHelixPosition, layoutMoleculeInstances, placementsDoNotOverlap,
  valenceQuarkScene, type SciencePrimitive, type MolecularStructure,
  type StructuredReactionSpecies,
} from '../src/client/science3d.js';

const balls = (parts: SciencePrimitive[]) => parts.filter((p) => p.kind === 'ball');
const rods = (parts: SciencePrimitive[]) => parts.filter((p) => p.kind === 'cylinder');
const near = (a: number, b: number, delta = 1e-7) => assert.ok(Math.abs(a - b) <= delta, String(a) + ' != ' + String(b));

test('central nucleotide mapping has 5 distinct colors', () => {
  assert.equal(new Set(['A', 'U', 'C', 'G', 'T'].map(nucleotideColor)).size, 5);
  assert.equal(new Set(['A', 'U', 'C', 'G', 'T'].map((base) => nucleotideColor(base, 'accessible'))).size, 5);
  assert.notEqual(nucleotideColor('C', 'default'), nucleotideColor('C', 'accessible'));
});

test('electron shell occupation respects noble-gas core, with identified ionic limitation', () => {
  assert.deepEqual(electronShells('[Ar] 3d6 4s2', 26), [2, 8, 14, 2, 0, 0, 0]);
  assert.equal(electronShells('[Ar] 3d6 4s2', 25).reduce((x, y) => x + y, 0), 25);
  assert.equal(electronShells('[Ar] 3d6 4s2', 27).reduce((x, y) => x + y, 0), 27);
  assert.deepEqual(electronShells('', 0), []);
});

test('FCC nucleus has exact non-overlapping, connected centered nucleon packing', () => {
  for (const count of [1, 2, 4, 8, 16, 56, 208, 294]) {
    const p = packedNucleus(count);
    assert.equal(p.length, count);
    for (let axis = 0; axis < 3; axis++)
      near(p.reduce((s, x) => s + x[axis], 0) / count, 0, 1e-10);
    const distance = (i: number, j: number) => Math.hypot(
      p[i][0] - p[j][0], p[i][1] - p[j][1], p[i][2] - p[j][2]);
    for (let i = 0; i < count; i++) for (let j = i + 1; j < count; j++)
      assert.ok(distance(i, j) >= 2 * NUCLEON_RADIUS - 1e-9, 'nucleons penetrate');
    const reached = new Set<number>([0]);
    let changed = true;
    while (changed) {
      changed = false;
      for (let i = 0; i < count; i++) for (let j = 0; j < count; j++) {
        if (reached.has(i) && !reached.has(j) && distance(i, j) <= 2 * NUCLEON_RADIUS + 1e-8) {
          reached.add(j); changed = true;
        }
      }
    }
    assert.equal(reached.size, count, 'packing must be one connected cluster');
  }
  assert.deepEqual(packedNucleus(1), [[0, 0, 0]]);
});

test('nucleon species counts are correct for hydrogen, oxygen and heavy isotopes', () => {
  for (const [z, a] of [[1, 1], [8, 16], [26, 56], [82, 208]]) {
    const body = nucleusParticles(z, a);
    assert.equal(body.length, a);
    assert.equal(body.filter((p) => p.kind === 'ball' && p.label === 'p+').length, z);
    assert.equal(body.filter((p) => p.kind === 'ball' && p.label === 'n').length, a - z);
  }
  const helium = atomScene(2, null, 0, '1s2');
  assert.match(helium.description, /neutron count.*unknown/i);
});

test('electron paths are individual, outside the nucleus, with exactly 20% smaller spheres', () => {
  near(EDUCATIONAL_ELECTRON_RADIUS, .055 * .8);
  const atom = atomScene(8, 16, 0, '[He] 2s2 2p4');
  const parts = atom.at(0);
  const electrons = parts.filter((p) => p.kind === 'ball' && p.id?.startsWith('electron-'));
  assert.equal(electrons.length, 8);
  assert.equal(new Set(electrons.map((e) => e.id)).size, 8);
  assert.ok(electrons.every((e) => e.kind === 'ball' && e.r === EDUCATIONAL_ELECTRON_RADIUS));
  const paths = parts.filter((p) => p.kind === 'line' && p.group?.startsWith('electron-'));
  assert.equal(new Set(paths.map((p) => p.group)).size, 8);
  const envelope = Math.max(...nucleusParticles(8, 16).filter((p) => p.kind === 'ball').map((p) =>
    p.kind === 'ball' ? Math.hypot(...p.p) + p.r : 0));
  for (const p of paths) if (p.kind === 'line') {
    assert.ok(Math.hypot(...p.a) >= envelope + .35);
    assert.ok(Math.hypot(...p.b) >= envelope + .35);
  }
  const orbits = electronOrbits([2, 6], envelope);
  assert.equal(orbits.length, 8);
  assert.equal(new Set(orbits.map((o) => o.id)).size, 8);
});

test('each educational electron orbit is disjoint for every shell, including 118 electrons', () => {
  const shellPopulations = [2, 8, 18, 32, 32, 18, 8];
  const orbits = electronOrbits(shellPopulations, 1.4);
  assert.equal(orbits.length, 118);
  assert.ok(ELECTRON_TRACK_GAP > 2 * EDUCATIONAL_ELECTRON_RADIUS);
  for (let i = 0; i < orbits.length; i++) {
    assert.ok(orbits[i].radius > 1.4 + EDUCATIONAL_ELECTRON_RADIUS);
    near(Math.hypot(...orbits[i].u), 1);
    near(Math.hypot(...orbits[i].v), 1);
    near(orbits[i].u.reduce((s, n, j) => s + n * orbits[i].v[j], 0), 0);
    if (i > 0) {
      assert.ok(orbits[i].radius - orbits[i - 1].radius >= ELECTRON_TRACK_GAP - 1e-10,
        'electron paths must be disjoint and leave room for visible spheres');
      assert.deepEqual(orbits[i].u, orbits[0].u, 'shared plane prevents crossing circles');
      assert.deepEqual(orbits[i].v, orbits[0].v, 'shared plane prevents crossing circles');
    }
  }
  const sodium = atomScene(11, 23, 0, '[Ne] 3s1');
  assert.equal(sodium.at(0).filter((p) => p.kind === 'ball' && p.id?.startsWith('electron-')).length, 11);
  assert.match(sodium.description, /nonintersecting/);
});

test('once, Continue and infinite loop index correctly for all bounded scenes', () => {
  assert.equal(animationFrameIndex(90, 90, false), 89);
  assert.equal(animationFrameIndex(89, 90, false), 89);
  assert.equal(animationFrameIndex(90, 90, true), 0);
  assert.equal(animationFrameIndex(95, 90, true), 5);
  assert.equal(animationFrameIndex(180, 90, true), 0);
  assert.equal(animationFrameIndex(-1, 90, true), 89);
  assert.equal(animationFrameIndex(1, 1, true), 0);
  assert.equal(animationFrameIndex(Infinity, 90, true), 0);
});

test('B-DNA helix is right-handed with continuous antiparallel strands and rods (not spheres)', () => {
  near(DNA_HELIX.riseNm, .34);
  near(DNA_HELIX.bpPerTurn, 10.5);
  const seq = 'ATGCATGCATG';
  const scene = dnaScene(seq);
  const parts = scene.at(0);
  assert.equal(balls(parts).length, 0);
  assert.equal(rods(parts).filter((p) => p.kind === 'cylinder' && p.id?.startsWith('dna-')).length, seq.length * 2);
  assert.equal(rods(parts).filter((p) => p.kind === 'cylinder' && p.group === 'coding').length, (seq.length - 1) * 8);
  assert.equal(rods(parts).filter((p) => p.kind === 'cylinder' && p.group === 'template').length, (seq.length - 1) * 8);
  for (let i = 1; i < seq.length; i++) near(
    dnaHelixPosition(i, seq.length)[0] - dnaHelixPosition(i - 1, seq.length)[0], DNA_HELIX.riseNm);
  assert.match(scene.description, /5′→3′/);
  const hydrogen = scene.at(0, 'hydrogen').filter((p) => p.kind === 'line');
  assert.ok(hydrogen.length >= 2 * seq.length);
});

test('RNA consists of one continuous backbone with cylindrical nucleobases', () => {
  const seq = 'AUGGCCAAG';
  const scene = rnaScene(seq);
  assert.equal(balls(scene.at(0)).length, 0);
  assert.equal(rods(scene.at(0)).filter((p) => p.kind === 'cylinder' && p.id?.startsWith('rna-')).length, seq.length);
  assert.equal(rods(scene.at(0)).filter((p) => p.kind === 'cylinder' && p.group === 'rna-backbone').length, (seq.length - 1) * 8);
  assert.match(scene.description, /NOT a predicted RNA fold/i);
});

test('transcription grows transcript by one cylindrical base per step and reanneals', () => {
  const scene = transcriptionScene('ATGC', 'AUGC');
  assert.equal(scene.frames, 5);
  const count = (f: number) => rods(scene.at(f)).filter((p) => p.kind === 'cylinder' && p.id?.startsWith('transcript-')).length;
  assert.equal(count(0), 0);
  assert.equal(count(3), 3);
  assert.equal(count(4), 4);
  assert.equal(balls(scene.at(4)).length, 0); // polymerase no longer displayed
});

test('translation step recognizes stop without inserting stop as an amino acid', () => {
  const scene = translationScene('AUGCCAUAA', [
    { codon: 'AUG', aa: 'M', anticodon: 'UAC' },
    { codon: 'CCA', aa: 'P', anticodon: 'GGU' },
    { codon: 'UAA', aa: '*' },
  ], 0);
  assert.equal(scene.frames, 4);
  assert.match(scene.frameLabel?.(3) ?? '', /Stop/);
  assert.equal(rods(scene.at(1)).filter((p) => p.kind === 'cylinder' && p.id?.startsWith('mrna-')).length, 9);
  assert.equal(rods(scene.at(1)).filter((p) => p.kind === 'cylinder' && p.id?.startsWith('anticodon-')).length, 3);
  assert.equal(rods(scene.at(3)).filter((p) => p.kind === 'cylinder' && p.id?.startsWith('anticodon-')).length, 0);
  const final = scene.at(3).filter((s) => s.kind === 'ball' && s.color === '#38a9a4');
  assert.equal(final.length, 2);
});

test('composition-only fallback retains exact stoichiometric counts for small balanced cases', () => {
  const scene = reactionScene(
    [{ species: 'H2', coefficient: 2, atoms: { H: 2 } }, { species: 'O2', coefficient: 1, atoms: { O: 2 } }],
    [{ species: 'H2O', coefficient: 2, atoms: { H: 2, O: 1 } }],
  );
  assert.equal(balls(scene.at(0)).length, 6);
  assert.equal(balls(scene.at(1)).length, 6);
});

const water: MolecularStructure = {
  formula: 'H2O', name: 'Water', charge: 0, source: 'https://cccbdb.nist.gov/',
  atoms: [{ element: 'O', xyz: [0, 0, .1173] }, { element: 'H', xyz: [0, .7572, -.4692] },
    { element: 'H', xyz: [0, -.7572, -.4692] }],
  bonds: [{ a: 0, b: 1, order: 1 }, { a: 0, b: 2, order: 1 }],
};
const oxygen: MolecularStructure = {
  formula: 'O2', name: 'Oxygen', charge: 0, source: 'https://cccbdb.nist.gov/',
  atoms: [{ element: 'O', xyz: [0, 0, 0] }, { element: 'O', xyz: [0, 0, 1.2075] }],
  bonds: [{ a: 0, b: 1, order: 2 }],
};
const co2: MolecularStructure = {
  formula: 'CO2', name: 'Carbon dioxide', charge: 0, source: 'https://cccbdb.nist.gov/',
  atoms: [{ element: 'C', xyz: [0, 0, 0] }, { element: 'O', xyz: [0, 0, 1.1621] },
    { element: 'O', xyz: [0, 0, -1.1621] }],
  bonds: [{ a: 0, b: 1, order: 2 }, { a: 0, b: 2, order: 2 }],
};
const propane: MolecularStructure = {
  formula: 'C3H8', name: 'Propane', charge: 0,
  source: 'https://cccbdb.nist.gov/geom3x.asp?basis=21&casno=2699798&method=5',
  atoms: [
    { element: 'C', xyz: [0, 0, .5909] }, { element: 'C', xyz: [0, 1.2737, -.2614] },
    { element: 'C', xyz: [0, -1.2737, -.2614] }, { element: 'H', xyz: [.8802, 0, 1.2476] },
    { element: 'H', xyz: [-.8802, 0, 1.2476] }, { element: 'H', xyz: [0, 2.1744, .3634] },
    { element: 'H', xyz: [0, -2.1744, .3634] }, { element: 'H', xyz: [.8863, 1.3091, -.9074] },
    { element: 'H', xyz: [-.8863, 1.3091, -.9074] }, { element: 'H', xyz: [-.8863, -1.3091, -.9074] },
    { element: 'H', xyz: [.8863, -1.3091, -.9074] },
  ],
  bonds: [[0, 1], [0, 2], [0, 3], [0, 4], [1, 5], [2, 6], [1, 7], [1, 8], [2, 9], [2, 10]]
    .map(([a, b]) => ({ a, b, order: 1 })),
};
test('molecular view draws explicit connected atoms and supports three modes', () => {
  const scene = moleculeScene(water);
  assert.equal(scene.at(0, 'ball-stick').filter((p) => p.kind === 'cylinder').length, 2);
  assert.equal(scene.at(0, 'space').filter((p) => p.kind === 'cylinder').length, 0);
  assert.equal(scene.at(0, 'wire').filter((p) => p.kind === 'line').length, 2);
  assert.equal(balls(scene.at(0, 'ball-stick')).length, 3);
  assert.match(scene.description, /NIST-sourced/);
});

test('propane combustion scene places exactly 1+5 and 3+4 molecules without bounding collisions', () => {
  const reactants: StructuredReactionSpecies[] = [
    { species: 'C3H8', coefficient: 1, atoms: { C: 3, H: 8 }, structure: propane },
    { species: 'O2', coefficient: 5, atoms: { O: 2 }, structure: oxygen },
  ];
  const products: StructuredReactionSpecies[] = [
    { species: 'CO2', coefficient: 3, atoms: { C: 1, O: 2 }, structure: co2 },
    { species: 'H2O', coefficient: 4, atoms: { H: 2, O: 1 }, structure: water },
  ];
  const left = layoutMoleculeInstances(reactants), right = layoutMoleculeInstances(products);
  assert.equal(left.length, 6);
  assert.equal(right.length, 7);
  assert.ok(placementsDoNotOverlap(left), 'reactant molecular volumes must not intersect');
  assert.ok(placementsDoNotOverlap(right), 'product molecular volumes must not intersect');
  const view = molecularReactionScene(reactants, products);
  assert.equal(balls(view.at(0)).length, 21);
  assert.equal(balls(view.at(1)).length, 21);
  assert.equal(new Set(balls(view.at(0)).map((p) => p.group)).size, 6);
  assert.equal(new Set(balls(view.at(1)).map((p) => p.group)).size, 7);
  assert.equal(view.frames, 2);
  assert.match(view.description, /NOT reaction trajectories/i);
});

test('orbital harmonic displays remain explicitly angular approximations', () => {
  for (const symbol of ['s', 'p', 'd', 'f'] as const) {
    const scene = orbitalAngularScene(symbol);
    assert.match(scene.description, /radial wavefunction.*NOT calculated/i);
    assert.ok(balls(scene.at(0)).length > 150, symbol);
  }
  assert.equal(balls(nucleusScene(1, null, '1s1').at(0)).length, 1);
});

test('RNA splicing result is synchronized with nucleotide-cylinder scenes', () => {
  const scene = rnaProcessingScene('AUGGAAUUUCCCUAA', 'AUGGAACCCUAA');
  assert.equal(scene.frames, 2);
  assert.equal(rods(scene.at(0)).filter((p) => p.kind === 'cylinder' && p.id?.startsWith('rna-')).length, 15);
  assert.equal(rods(scene.at(1)).filter((p) => p.kind === 'cylinder' && p.id?.startsWith('rna-')).length, 12);
});

test('valence quark diagram is explicitly conceptual, not a QCD trajectory', () => {
  for (const kind of ['proton', 'neutron'] as const) {
    const scene = valenceQuarkScene(kind);
    assert.equal(balls(scene.at(0)).length, 3);
    assert.match(scene.description, /NOT measured classical trajectories/i);
    assert.match(scene.description, kind === 'proton' ? /uud/ : /udd/);
  }
});
