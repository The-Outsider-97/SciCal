import test from 'node:test';
import assert from 'node:assert/strict';
import { plain, prettyNumber, prettyUnit, sciParts, toNumber } from '../src/core/numtext.js';

test('sciParts splits a decimal string exactly', () => {
  assert.deepEqual(sciParts('6.62607015e-34'), { sign: '', digits: '662607015', e10: -34 });
  assert.deepEqual(sciParts('299792458'), { sign: '', digits: '299792458', e10: 8 });
  assert.deepEqual(sciParts('0.0254'), { sign: '', digits: '254', e10: -2 });
  assert.deepEqual(sciParts('-1.5e+3'), { sign: '-', digits: '15', e10: 3 });
  assert.equal(sciParts('abc'), null);
  assert.equal(sciParts(''), null);
});

test('prettyNumber writes exponents and groups plain values', () => {
  assert.equal(prettyNumber('6.62607015e-34'), '6.62607015 × 10⁻³⁴');
  assert.equal(prettyNumber('299792458'), '2.99792458 × 10⁸');
  assert.equal(prettyNumber('101325'), '101 325');
  assert.equal(prettyNumber('9.80665'), '9.80665');
  assert.equal(prettyNumber('0.0254'), '0.0254');
  assert.equal(prettyNumber('3600000'), '3 600 000');
  assert.equal(prettyNumber('1e-4'), '1 × 10⁻⁴');
});

test('prettyNumber shortens very long strings and says so', () => {
  const pi = '3.1415926535897932384626433832795028841971693993751';
  assert.equal(prettyNumber(pi, 10), '3.141592653…');
  assert.ok(prettyNumber('1.054571817646156391262428003302280744723e-34').endsWith('… × 10⁻³⁴'));
});

test('toNumber and plain', () => {
  assert.equal(toNumber(sciParts('1.5e-15')!), 1.5e-15);
  assert.equal(plain('1.5e+20'), '1.5e20');
});

test('prettyUnit uses a middle dot and superscripts for display only', () => {
  assert.equal(prettyUnit('W*m^2'), 'W·m²');
  assert.equal(prettyUnit('m^3/(kg*s^2)'), 'm³/(kg·s²)');
  assert.equal(prettyUnit('length^2 · mass · time^-1'), 'length² · mass · time⁻¹');
});
