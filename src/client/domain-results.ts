// Showing what a subject operation returned. The server's answers share a small vocabulary (numbers with units, lists of rows,
// worked steps, warnings), so one renderer covers all of them and the few charts are chosen by the operation's `chart` tag.
import { formatNumber } from '../core/graphmath.js';
import { isNum, isPoints, isRowList, labelOf, messageOf } from '../core/results.js';
import type { FormOp, NumText } from '../core/types.js';
import { isRecord } from '../core/util.js';
import { chart } from './charts.js';
import { h, replace } from './dom.js';
import { math } from './math-dom.js';

export interface ResultCtx {
  op: FormOp;
  params: Record<string, unknown>;
  exportTable(name: string, columns: string[], rows: unknown[][]): void;
}

type R = Record<string, unknown>;

const SKIP = new Set(['ok', 'steps', 'warnings', 'notes', 'meta', 'mode', 'pretty', 'latex', 'curve', 'line', 'residuals', 'catalogue', 'molecularPretty', 'solveFor']);
const LEAD = ['balanced', 'empirical', 'formula', 'equation'];
const MATH_COLS = new Set(['partial']);
const HIDE_COLS = new Set(['pretty', 'latex', 'exact', 'valueExact', 'valueNumber', 'weightNote', 'configurationNote']);

// ------------------------------------------------------------------------------------------------------------------ values
export function cellText(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (isNum(v)) return v.text;
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : formatNumber(v, 8);
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (typeof v === 'string') return v;
  if (Array.isArray(v)) return v.map(cellText).join(', ');
  if (isRecord(v)) return Object.entries(v).filter(([k]) => !HIDE_COLS.has(k)).map(([k, x]) => `${k}: ${cellText(x)}`).join('; ');
  return String(v);
}

function numNode(n: NumText): HTMLElement {
  const wrap = h('span', { class: 'm' });
  try { wrap.appendChild(math(n.latex)); } catch { wrap.textContent = n.text; }
  if (!wrap.firstChild) wrap.textContent = n.text;
  wrap.setAttribute('aria-label', n.text);
  return wrap;
}

function kv(label: string, value: Node | string, extra?: string, cls = ''): HTMLElement {
  return h('div', { class: `kv ${cls}`.trim() }, h('div', { class: 'k', text: label }), h('div', { class: 'v' }, value), extra ? h('div', { class: 'x', text: extra }) : null);
}

function numExtra(n: NumText): string | undefined {
  const bits: string[] = [];
  if (typeof n.exact === 'string' && n.exact !== n.text) bits.push(`exact ${n.exact}`);
  else if (n.approximate) bits.push('approximate');
  const note = (n as unknown as R).note;
  if (typeof note === 'string') bits.push(note);
  return bits.length ? bits.join(' · ') : undefined;
}

// ------------------------------------------------------------------------------------------------------------------ tables
function tableOf(rows: R[], key: string, ctx: ResultCtx): HTMLElement {
  const keys: string[] = [];
  for (const r of rows) for (const k of Object.keys(r)) if (!keys.includes(k) && !HIDE_COLS.has(k)) keys.push(k);
  const display = (r: R, k: string): unknown => (k === 'species' && typeof r.pretty === 'string' ? r.pretty : k === 'molecular' && typeof r.molecularPretty === 'string' ? r.molecularPretty : r[k]);
  const head = h('tr', null, keys.map((k) => h('th', { text: labelOf(k) })));
  const body = rows.map((r) => h('tr', null, keys.map((k) => {
    const v = display(r, k);
    if (MATH_COLS.has(k) && typeof v === 'string') { const td = h('td'); td.appendChild(math(v)); return td; }
    const numeric = typeof v === 'number' || isNum(v);
    return h('td', { class: numeric ? 'num' : '', text: cellText(v) });
  })));
  const flat = rows.map((r) => keys.map((k) => cellText(display(r, k))));
  return h('div', { class: 'tablebox' },
    h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', null, head), h('tbody', null, body))),
    rows.length > 3 ? h('button', { class: 'btn small', type: 'button', text: 'Export as CSV', on: { click: () => ctx.exportTable(`${ctx.op.id}-${key}`, keys.map(labelOf), flat) } }) : null);
}

// ------------------------------------------------------------------------------------------------------------------ sections
function nestedGrid(obj: R): HTMLElement {
  const cards: HTMLElement[] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (HIDE_COLS.has(k)) continue;
    if (isNum(v)) cards.push(kv(labelOf(k), numNode(v), numExtra(v)));
    else if (Array.isArray(v) && v.every((x) => typeof x === 'string')) cards.push(kv(labelOf(k), v.join(',  ')));
    else if (isRecord(v)) cards.push(kv(labelOf(k), cellText(v)));
    else cards.push(kv(labelOf(k), cellText(v)));
  }
  return h('div', { class: 'kvs' }, cards);
}

function stepsList(steps: unknown[]): HTMLElement {
  return h('ol', { class: 'workings' }, steps.filter(isRecord).map((st) => h('li', null,
    h('div', { class: 't', text: String(st.title ?? '') }),
    typeof st.latex === 'string' ? h('div', null, math(st.latex)) : null,
    st.detail ? h('div', { class: 'd', text: String(st.detail) }) : null)));
}

function chartsFor(res: R, ctx: ResultCtx): HTMLElement[] {
  const out: HTMLElement[] = [];
  const num = (x: unknown): number => (isNum(x) && typeof x.value === 'number' ? x.value : NaN);
  switch (ctx.op.chart) {
    case 'titration': {
      if (!isPoints(res.curve)) break;
      const eq = num(res.equivalenceVolume);
      const pheq = num(res.pHAtEquivalence);
      out.push(chart({ title: 'Titration curve', xLabel: 'Volume of base added (mL)', yLabel: 'pH', series: [{ label: 'pH', points: res.curve }],
        markers: Number.isFinite(eq) && Number.isFinite(pheq) ? [{ x: eq, y: pheq, label: `equivalence ${formatNumber(eq, 5)} mL, pH ${formatNumber(pheq, 4)}` }] : [],
        description: 'pH against the volume of base added, with the equivalence point marked.',
        onExport: () => ctx.exportTable('titration-curve', ['volume_mL', 'pH'], res.curve as unknown[][]) }));
      break;
    }
    case 'michaelis': {
      if (!isPoints(res.curve)) break;
      const data = pairsFrom(ctx.params.data);
      out.push(chart({ title: 'Enzyme kinetics', xLabel: 'Substrate concentration [S]', yLabel: 'Rate v',
        series: [{ label: 'Fitted curve', points: res.curve, kind: 'line' }, ...(data.length ? [{ label: 'Data', points: data, kind: 'scatter' as const }] : [])],
        description: 'Measured rates and the fitted Michaelis–Menten curve.', onExport: () => ctx.exportTable('michaelis-curve', ['S', 'v'], res.curve as unknown[][]) }));
      break;
    }
    case 'calibration': {
      const data = pairsFrom(ctx.params.data);
      const unk = isRecord(res.unknown) ? res.unknown : null;
      const ux = unk ? num(unk.x) : NaN;
      const uy = unk ? num(unk.meanResponse) : NaN;
      if (data.length && isPoints(res.line)) {
        out.push(chart({ title: 'Calibration curve', xLabel: 'Standard', yLabel: 'Response',
          series: [{ label: 'Fit', points: res.line, kind: 'line' }, { label: 'Standards', points: data, kind: 'scatter' }],
          markers: Number.isFinite(ux) && Number.isFinite(uy) ? [{ x: ux, y: uy, label: 'unknown' }] : [],
          description: 'Standards, the least-squares line and the unknown sample.', onExport: () => ctx.exportTable('calibration', ['x', 'response'], data) }));
      }
      if (isPoints(res.residuals)) out.push(chart({ title: 'Residuals', xLabel: 'Standard', yLabel: 'Residual', zeroLine: true, series: [{ label: 'Residual', points: res.residuals, kind: 'scatter' }], description: 'Distance of each point from the fitted line; a pattern here means a straight line is not the right model.' }));
      break;
    }
    default: break;
  }
  return out;
}

function pairsFrom(v: unknown): Array<[number, number]> {
  if (!Array.isArray(v)) return [];
  const out: Array<[number, number]> = [];
  for (const p of v) {
    if (Array.isArray(p) && p.length >= 2) {
      const a = Number(p[0]);
      const b = Number(p[1]);
      if (Number.isFinite(a) && Number.isFinite(b)) out.push([a, b]);
    }
  }
  return out;
}

// ------------------------------------------------------------------------------------------------------------------ the renderer
export function renderResult(res: R, ctx: ResultCtx, skip: Set<string> = new Set()): HTMLElement {
  const root = h('div', { class: 'result' });
  if (res.ok === false) {
    const e = isRecord(res.error) ? res.error : {};
    root.appendChild(h('div', { class: 'note-line error', role: 'alert', text: `${String(e.message ?? 'The calculation failed.')}${e.hint ? ' ' + String(e.hint) : ''}` }));
    return root;
  }
  const cards: HTMLElement[] = [];
  const sections: HTMLElement[] = [];
  const leadKey = LEAD.find((k) => typeof res[k] === 'string');
  if (typeof res.latex === 'string' && leadKey) cards.push(kv(labelOf(leadKey === 'balanced' ? 'balancedEquation' : leadKey), math(res.latex, { display: false }), undefined, 'big'));
  let first = true;
  for (const [key, v] of Object.entries(res)) {
    if (SKIP.has(key) || skip.has(key) || HIDE_COLS.has(key)) continue;
    if (key === leadKey && typeof res.latex === 'string') continue;
    if (isNum(v)) { cards.push(kv(labelOf(key), numNode(v), numExtra(v), first ? 'key' : '')); first = false; continue; }
    if (typeof v === 'string') { cards.push(kv(labelOf(key), h('span', { class: v.length > 40 ? 'seq' : '', text: v }), undefined, v.length > 28 ? 'big' : '')); continue; }
    if (typeof v === 'number' || typeof v === 'boolean') { cards.push(kv(labelOf(key), cellText(v))); continue; }
    if (Array.isArray(v) && v.length && v.every(isNum)) { cards.push(kv(labelOf(key), (v as NumText[]).map((x) => x.text).join('  to  '))); continue; }
    if (Array.isArray(v) && v.length && v.every((x) => typeof x === 'string')) { sections.push(h('div', null, h('div', { class: 'sectitle', text: labelOf(key) }), h('div', { class: 'chips' }, (v as string[]).map((x) => h('span', { class: 'chip', text: x }))))); continue; }
    if (isRowList(v)) { sections.push(h('div', { class: 'section' }, h('div', { class: 'sectitle', text: labelOf(key) }), tableOf(v, key, ctx))); continue; }
    if (isRecord(v)) {
      const flatNums = Object.values(v).every((x) => isNum(x) || typeof x !== 'object' || x === null || (Array.isArray(x) && x.every((y) => typeof y === 'string')));
      if (flatNums) sections.push(h('div', { class: 'section' }, h('div', { class: 'sectitle', text: labelOf(key) }), nestedGrid(v)));
      else sections.push(h('div', { class: 'section' }, h('div', { class: 'sectitle', text: labelOf(key) }), h('div', { class: 'kvs' }, kv(labelOf(key), cellText(v), undefined, 'big'))));
    }
  }
  if (cards.length) root.appendChild(h('div', { class: 'kvs' }, cards));
  for (const c of chartsFor(res, ctx)) root.appendChild(c);
  for (const s of sections) root.appendChild(s);
  const warnings = (Array.isArray(res.warnings) ? res.warnings : []).map(messageOf).filter(Boolean);
  const notes = (Array.isArray(res.notes) ? res.notes : []).map(messageOf).filter(Boolean);
  if (warnings.length || notes.length) root.appendChild(h('div', { class: 'notes' }, [...warnings, ...notes].map((w) => h('div', { class: 'note-line', text: w }))));
  if (Array.isArray(res.steps) && res.steps.length) {
    root.appendChild(h('details', { class: 'working-box' }, h('summary', { text: `Working (${res.steps.length} step${res.steps.length === 1 ? '' : 's'})` }), stepsList(res.steps)));
  }
  if (isRecord(res.meta) && typeof res.meta.source === 'string') root.appendChild(h('p', { class: 'muted source', text: `Data: ${res.meta.source}` }));
  return root;
}

export function showInto(target: HTMLElement, node: Node | Node[] | null): void {
  if (node === null) replace(target);
  else replace(target, ...(Array.isArray(node) ? node : [node]));
}
