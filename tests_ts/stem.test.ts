import assert from 'node:assert/strict';
import test from 'node:test';
import { canCheck, entryForCheck, formatDifference, slim, statusMark, statusWord, verdictBadge } from '../src/core/stem.js';
import type { Verification } from '../src/core/types.js';

const v = (verdict: Verification['verdict'], counts: Verification['counts'], ran = true): Verification => ({ ran, verdict, summary: 's', checks: [], counts });

test('a verdict is written in words, not only a symbol', () => {
  assert.equal(verdictBadge(v('agree', { agree: 3 }))?.text, 'STEM ✓ agrees (3/3)');
  assert.equal(verdictBadge(v('differ', { agree: 2, differ: 1 }))?.text, 'STEM ≠ differs (1/3)');
  assert.equal(verdictBadge(v('differ', { agree: 2, differ: 1 }))?.tone, 'warn');
  assert.equal(verdictBadge(v('none', {}))?.tone, 'muted');
});

test('nothing is shown for a result that was not checked', () => {
  assert.equal(verdictBadge(undefined), null);
  assert.equal(verdictBadge(v('unavailable', {}, false)), null);
  assert.equal(verdictBadge(v('unavailable', {})), null);
});

test('status words and marks', () => {
  assert.deepEqual(['agree', 'differ', 'skipped', 'failed'].map((s) => statusWord(s as never)), ['agrees', 'differs', 'not run', 'failed']);
  assert.deepEqual(['agree', 'differ', 'skipped', 'failed'].map((s) => statusMark(s as never)), ['✓', '≠', '–', '!']);
});

test('differences are short', () => {
  assert.equal(formatDifference(0), '0');
  assert.equal(formatDifference(null), '');
  assert.equal(formatDifference(Number.NaN), '');
  assert.equal(formatDifference(2.2e-16), '2.20e-16');
  assert.equal(formatDifference(0.012345), '0.0123');
  assert.equal(formatDifference(12345678), '1.23e7');
});

test('which entries can be checked', () => {
  const list: Array<[string, string]> = [['measurement', 'repeated']];
  assert.equal(canCheck({ kind: 'calc' }, list), true);
  assert.equal(canCheck({ kind: 'calc', ok: false }, list), false);
  assert.equal(canCheck({ kind: 'calc', result: { ok: false } }, list), false);
  assert.equal(canCheck({ kind: 'domain', domain: 'measurement', op: 'repeated' }, list), true);
  assert.equal(canCheck({ kind: 'domain', domain: 'chemistry', op: 'molar_mass' }, list), false);
  assert.equal(canCheck({ kind: 'domain', domain: 'measurement', op: 'repeated' }, undefined), false);
  assert.equal(canCheck({ kind: 'note' }, list), false);
});

test('only what was asked is sent to be checked', () => {
  const e = { id: 'a', time: 't', kind: 'calc' as const, input: '1+1', result: { ok: true }, figure: { mediaType: 'image/png' as const, data: 'x', transparent: true, series: [] }, workspace: 'math' };
  const sent = entryForCheck(e);
  assert.deepEqual(Object.keys(sent).sort(), ['input', 'kind', 'result', 'workspace']);
});

test('a stored verification stays small', () => {
  const long = 'x'.repeat(2000);
  const s = slim({ ...v('agree', { agree: 1 }), summary: long, checks: Array.from({ length: 30 }, () => ({ title: 't', status: 'agree' as const, scical: '1', stem: '1', difference: 0, tolerance: 'x', via: 'y', note: long })) });
  assert.ok(s.summary.length <= 400);
  assert.equal(s.checks.length, 20);
  assert.ok((s.checks[0].note ?? '').length <= 400);
});
