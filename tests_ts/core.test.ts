import test from 'node:test';
import assert from 'node:assert/strict';
import { collect, seed, emptyState, visible, describeInput } from '../src/core/forms.js';
import { crossCheckSummary, headlineOf, isPoints, labelOf } from '../src/core/results.js';
import { ticks, formatTick, zoomAt, pan, square, traceAt, mapper, sane } from '../src/core/graphmath.js';
import { contextFor, definesOf } from '../src/core/session.js';
import { applyInsert, PADS } from '../src/core/keypad.js';
import { splitList, splitPairs, words, debounce } from '../src/core/util.js';
import type { FormOp, Entry, CalcResult } from '../src/core/types.js';

const op: FormOp = {
  id: 't', title: 'Test', summary: '', example: {},
  fields: [
    { kind: 'select', key: 'mode', label: 'Mode', options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }] },
    { kind: 'quantity', key: 'm', label: 'Mass', unit: 'g', when: { mode: ['a'] }, required: true },
    { kind: 'list', key: 'vals', label: 'Values', when: { mode: ['b'] } },
    { kind: 'pairs', key: 'xy', label: 'XY' },
    { kind: 'bool', key: 'flag', label: 'Flag' },
    { kind: 'table', key: 'comp', label: 'Comp', shape: 'object', columns: [{ key: 'el', label: 'El' }, { key: 'v', label: 'V' }] },
    { kind: 'table', key: 'vars', label: 'Vars', shape: 'object', columns: [{ key: 'n', label: 'N' }, { key: 'value', label: 'Value' }, { key: 'uncertainty', label: 'U' }] },
    { kind: 'table', key: 'given', label: 'Given', shape: 'array', columns: [{ key: 'species', label: 'S' }, { key: 'amount', label: 'A' }] },
  ],
};

test('collect leaves out empty and hidden fields and shapes tables', () => {
  const st = emptyState(op);
  st.mode = 'a';
  st.m = ' 5 ';
  st.vals = '1 2 3';
  st.xy = '1 2\n3, 4\n\n';
  st.comp = [['C', '40'], ['H', '6.7'], ['', '']];
  st.vars = [['m', '2.5', '0.05']];
  st.given = [['N2', '28 g'], ['', '']];
  const { params, missing } = collect(op, st);
  assert.deepEqual(missing, []);
  assert.deepEqual(params, {
    mode: 'a', m: '5', xy: [['1', '2'], ['3', '4']], flag: false, comp: { C: '40', H: '6.7' },
    vars: { m: { value: '2.5', uncertainty: '0.05' } }, given: [{ species: 'N2', amount: '28 g' }],
  });
  st.mode = 'b';
  const r = collect(op, st);
  assert.deepEqual(r.params.vals, ['1', '2', '3']);
  assert.equal('m' in r.params, false);
});

test('required fields are reported', () => {
  const st = emptyState(op);
  st.mode = 'a';
  assert.deepEqual(collect(op, st).missing, ['Mass']);
});

test('seed is the inverse of collect', () => {
  const params = { mode: 'a', m: '5 g', xy: [[1, 2], [3, 4]], flag: true, comp: { C: '40', H: '6.7' }, vars: { m: { value: '2.5', uncertainty: '0.05' } }, given: [{ species: 'N2', amount: '28 g' }] };
  const back = collect(op, seed(op, params)).params;
  assert.deepEqual(back.comp, params.comp);
  assert.deepEqual(back.vars, params.vars);
  assert.deepEqual(back.given, params.given);
  assert.deepEqual(back.xy, [['1', '2'], ['3', '4']]);
  assert.equal(back.flag, true);
  assert.equal(visible(op.fields[1], { mode: 'b' }), false);
});

test('describeInput and headline', () => {
  assert.equal(describeInput({ ...op, title: 'Molar mass' }, { formula: 'Ca(OH)2' }), 'Molar mass: Ca(OH)2');
  assert.equal(describeInput(op, {}), 'Test');
  assert.equal(headlineOf({ ok: true, molarMass: { text: '74.09 g/mol', latex: '74.09' } }), 'M = 74.09 g/mol');
  assert.equal(headlineOf({ ok: false, error: { message: 'bad' } }), 'Error: bad');
  assert.equal(headlineOf({ ok: true, foo: { text: '1', latex: '1' } }), 'Foo = 1');
  assert.equal(labelOf('percentYield'), 'Percent yield');
  assert.equal(labelOf('pH'), 'pH');
  assert.equal(labelOf('rSquared'), 'R squared');
  assert.equal(labelOf('tValue'), 't value');
  assert.equal(labelOf('pValue'), 'p value');
  assert.equal(labelOf('chiSquare'), 'Chi square');
  assert.equal(labelOf('pOH'), 'pOH');
  assert.equal(labelOf('pHAtEquivalence'), 'pH at equivalence');
  assert.equal(labelOf('initialPH'), 'Initial pH');
  assert.equal(labelOf('slopeStdError'), 'Slope std error');
  assert.equal(labelOf('gcContent'), 'GC content');
  assert.equal(labelOf('molarMass'), 'Molar mass');
  assert.equal(labelOf('vmaxStdError'), 'Vmax std error');
  assert.equal(labelOf('slopeInterval95'), 'Slope interval95');
  assert.ok(isPoints([[0, 1], [1, 2]]));
  assert.ok(!isPoints([[0, 1]]));
});

test('ticks are nice and formatted without noise', () => {
  const t = ticks(-10, 10, 8);
  assert.equal(t.step, 2);
  assert.deepEqual(t.values.slice(0, 3), [-10, -8, -6]);
  assert.ok(t.values.includes(0));
  assert.equal(formatTick(0.30000000000000004, 0.1), '0.3');
  assert.equal(formatTick(2500000, 500000), '2.5e6');
  assert.equal(ticks(0, 1e-3, 5).step, 0.0002);
});

test('zoom keeps the point under the cursor fixed; pan moves with the pointer', () => {
  const v = { xmin: -10, xmax: 10, ymin: -5, ymax: 5 };
  const z = zoomAt(v, 0.75, 0.25, 0.5);
  const m0 = mapper(v, 400, 200);
  const m1 = mapper(z, 400, 200);
  assert.ok(Math.abs(m0.wx(300) - m1.wx(300)) < 1e-9);
  assert.ok(Math.abs(m0.wy(50) - m1.wy(50)) < 1e-9);
  assert.ok(z.xmax - z.xmin < 20 + 1e-9);
  const p = pan(v, 0.1, 0);
  assert.ok(Math.abs(p.xmin - (-12)) < 1e-9);          // dragging right reveals more to the left
  const q = square({ xmin: -10, xmax: 10, ymin: -1, ymax: 1 }, 400, 200);
  assert.ok(Math.abs((q.xmax - q.xmin) / 400 - (q.ymax - q.ymin) / 200) < 1e-9);
  const s = sane({ xmin: 1, xmax: 1, ymin: NaN, ymax: 2 });
  assert.ok(s.xmax > s.xmin && Number.isFinite(s.ymin));
});

test('trace interpolates inside a segment', () => {
  const segs: Array<Array<[number, number]>> = [[[0, 0], [2, 4]], [[3, 0], [4, 1]]];
  assert.deepEqual(traceAt(segs, 1), [1, 2]);
  assert.equal(traceAt(segs, 2.5), null);
  assert.deepEqual(traceAt(segs, 3.5), [3.5, 0.5]);
});

test('context replays definitions and, for ans, the previous lines', () => {
  const e = (input: string, defines?: string[], ok = true): Entry => ({ id: input, kind: 'calc', time: '', input, defines, ok, result: input.includes('(x) :=') ? { kind: 'definition' } : { kind: 'number' } });
  const entries = [e('a := 5', ['a']), e('2+2'), e('ans*3'), e('f(x) := x^2', ['f'])];
  assert.deepEqual(contextFor(entries, 'a + 1'), ['a := 5', 'f(x) := x^2']);
  assert.deepEqual(contextFor(entries, 'ans + 1'), ['a := 5', 'f(x) := x^2', '2+2', 'ans*3']);
  const r = { ok: true, input: 'a := 5', kind: 'assignment', name: 'a' } as CalcResult;
  assert.deepEqual(definesOf(r), ['a']);
  assert.equal(definesOf({ ok: true, input: '1', kind: 'number' } as CalcResult), undefined);
});

test('input splitting', () => {
  assert.deepEqual(splitList('1, 2;3\n4'), ['1', '2', '3', '4']);
  assert.deepEqual(splitPairs('1 2\n\n3,4'), [['1', '2'], ['3', '4']]);
  assert.equal(words('specificHeat1'), 'Specific heat 1');
  assert.equal(words('pH'), 'pH');
});

test('debounce runs once with the last arguments', async () => {
  const seen: number[] = [];
  const d = debounce((n: number) => seen.push(n), 10);
  d(1); d(2); d(3);
  await new Promise((r) => setTimeout(r, 40));
  assert.deepEqual(seen, [3]);
});

test('keypad insertion', () => {
  assert.deepEqual(applyInsert('2+', 2, 2, 'sin(|)'), { value: '2+sin()', cursor: 6 });
  assert.deepEqual(applyInsert('2+x', 2, 3, 'sin(|)'), { value: '2+sin(x)', cursor: 8 });
  assert.deepEqual(applyInsert('', 0, 0, 'pi'), { value: 'pi', cursor: 2 });
  assert.deepEqual(applyInsert('a b', 1, 2, ' -> '), { value: 'a -> b', cursor: 5 });
  for (const pad of Object.values(PADS)) for (const row of pad.rows) for (const key of row) assert.ok(key.insert || key.action, key.label);
});

test('crossCheckSummary says why it did not run, and reports each statistic when it did', () => {
  assert.match(crossCheckSummary({ ran: false, reason: 'No agent' }), /not run: No agent/);
  assert.match(crossCheckSummary({ ran: false }), /not available/);
  const text = crossCheckSummary({ ran: true, rows: [{ statistic: 'mean', agree: true }, { statistic: 'standardDeviation', agree: false, scical: 1, stemAgent: 2 }, { statistic: 'median', status: 'failed', reason: 'boom' }] });
  assert.match(text, /mean agrees/);
  assert.match(text, /standard deviation differs \(SciCal 1, STEM agent 2\)/);
  assert.match(text, /median: failed \(boom\)/);
  assert.match(crossCheckSummary({ ran: true, rows: [] }), /nothing to compare/);
});
