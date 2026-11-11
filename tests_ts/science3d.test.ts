import test from 'node:test';
import assert from 'node:assert/strict';
import { atomScene, electronShells, dnaScene, rnaScene, nucleotideColor, transcriptionScene, translationScene, reactionScene } from '../src/client/science3d.js';

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
  const balls = dna.at(0).filter((s) => s.kind === 'ball');
  assert.equal(balls.length, 8);
  const rna = rnaScene('AUG');
  assert.equal(rna.at(0).filter((s) => s.kind === 'ball').length, 3);
});

test('transcription model adds exactly one RNA nucleotide per step', () => {
  const scene = transcriptionScene('ATGC', 'AUGC');
  assert.equal(scene.frames, 5);
  const n = (frame: number) => scene.at(frame).filter((s) => s.kind === 'ball' && s.label !== 'Pol').length;
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
