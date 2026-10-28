// Showing what a subject operation returned. The server's answers share a small vocabulary (numbers with units, lists of rows,
// worked steps, warnings), so one renderer covers all of them and the few charts are chosen by the operation's `chart` tag.
import { formatNumber } from '../core/graphmath.js';
import { isNum, isPoints, isRowList, labelOf, messageOf } from '../core/results.js';
import { isRecord } from '../core/util.js';
import { chart } from './charts.js';
import { h, replace } from './dom.js';
import { math } from './math-dom.js';
import { navigate } from './shell.js';
const SKIP = new Set(['headline', 'plot', 'plot2', 'graph', 'graph2', 'assumptions', 'ok', 'steps', 'warnings', 'notes', 'meta', 'mode', 'pretty', 'latex', 'curve', 'line', 'residuals', 'catalogue', 'molecularPretty', 'solveFor']);
const LEAD = ['balanced', 'empirical', 'formula', 'equation'];
const MATH_COLS = new Set(['partial']);
const HIDE_COLS = new Set(['pretty', 'latex', 'exact', 'valueExact', 'valueNumber', 'weightNote', 'configurationNote']);
// ------------------------------------------------------------------------------------------------------------------ values
export function cellText(v) {
    if (v === null || v === undefined)
        return '';
    if (isNum(v))
        return v.text;
    if (typeof v === 'number')
        return Number.isInteger(v) ? String(v) : formatNumber(v, 8);
    if (typeof v === 'boolean')
        return v ? 'yes' : 'no';
    if (typeof v === 'string')
        return v;
    if (Array.isArray(v))
        return v.map(cellText).join(', ');
    if (isRecord(v))
        return Object.entries(v).filter(([k]) => !HIDE_COLS.has(k)).map(([k, x]) => `${k}: ${cellText(x)}`).join('; ');
    return String(v);
}
function numNode(n) {
    const wrap = h('span', { class: 'm' });
    try {
        wrap.appendChild(math(n.latex));
    }
    catch {
        wrap.textContent = n.text;
    }
    if (!wrap.firstChild)
        wrap.textContent = n.text;
    wrap.setAttribute('aria-label', n.text);
    return wrap;
}
function kv(label, value, extra, cls = '') {
    return h('div', { class: `kv ${cls}`.trim() }, h('div', { class: 'k', text: label }), h('div', { class: 'v' }, value), extra ? h('div', { class: 'x', text: extra }) : null);
}
function numExtra(n) {
    const bits = [];
    if (typeof n.exact === 'string' && n.exact !== n.text)
        bits.push(`exact ${n.exact}`);
    else if (n.approximate)
        bits.push('approximate');
    const note = n.note;
    if (typeof note === 'string')
        bits.push(note);
    return bits.length ? bits.join(' · ') : undefined;
}
// ------------------------------------------------------------------------------------------------------------------ tables
function tableOf(rows, key, ctx) {
    const keys = [];
    for (const r of rows)
        for (const k of Object.keys(r))
            if (!keys.includes(k) && !HIDE_COLS.has(k))
                keys.push(k);
    const display = (r, k) => (k === 'species' && typeof r.pretty === 'string' ? r.pretty : k === 'molecular' && typeof r.molecularPretty === 'string' ? r.molecularPretty : r[k]);
    const head = h('tr', null, keys.map((k) => h('th', { text: labelOf(k) })));
    const body = rows.map((r) => h('tr', null, keys.map((k) => {
        const v = display(r, k);
        if (MATH_COLS.has(k) && typeof v === 'string') {
            const td = h('td');
            td.appendChild(math(v));
            return td;
        }
        const numeric = typeof v === 'number' || isNum(v);
        return h('td', { class: numeric ? 'num' : '', text: cellText(v) });
    })));
    const flat = rows.map((r) => keys.map((k) => cellText(display(r, k))));
    return h('div', { class: 'tablebox' }, h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', null, head), h('tbody', null, body))), rows.length > 3 ? h('button', { class: 'btn small', type: 'button', text: 'Export as CSV', on: { click: () => ctx.exportTable(`${ctx.op.id}-${key}`, keys.map(labelOf), flat) } }) : null);
}
// ------------------------------------------------------------------------------------------------------------------ sections
function nestedGrid(obj) {
    const cards = [];
    for (const [k, v] of Object.entries(obj)) {
        if (HIDE_COLS.has(k))
            continue;
        if (isNum(v))
            cards.push(kv(labelOf(k), numNode(v), numExtra(v)));
        else if (Array.isArray(v) && v.every((x) => typeof x === 'string'))
            cards.push(kv(labelOf(k), v.join(',  ')));
        else if (isRecord(v))
            cards.push(kv(labelOf(k), cellText(v)));
        else
            cards.push(kv(labelOf(k), cellText(v)));
    }
    return h('div', { class: 'kvs' }, cards);
}
function stepsList(steps) {
    return h('ol', { class: 'workings' }, steps.filter(isRecord).map((st) => h('li', null, h('div', { class: 't', text: String(st.title ?? '') }), typeof st.latex === 'string' ? h('div', null, math(st.latex)) : null, st.detail ? h('div', { class: 'd', text: String(st.detail) }) : null)));
}
function chartsFor(res, ctx) {
    const out = [];
    const num = (x) => (isNum(x) && typeof x.value === 'number' ? x.value : NaN);
    switch (ctx.op.chart) {
        case 'titration': {
            if (!isPoints(res.curve))
                break;
            const eq = num(res.equivalenceVolume);
            const pheq = num(res.pHAtEquivalence);
            out.push(chart({ title: 'Titration curve', xLabel: 'Volume of base added (mL)', yLabel: 'pH', series: [{ label: 'pH', points: res.curve }],
                markers: Number.isFinite(eq) && Number.isFinite(pheq) ? [{ x: eq, y: pheq, label: `equivalence ${formatNumber(eq, 5)} mL, pH ${formatNumber(pheq, 4)}` }] : [],
                description: 'pH against the volume of base added, with the equivalence point marked.',
                onExport: () => ctx.exportTable('titration-curve', ['volume_mL', 'pH'], res.curve) }));
            break;
        }
        case 'michaelis': {
            if (!isPoints(res.curve))
                break;
            const data = pairsFrom(ctx.params.data);
            out.push(chart({ title: 'Enzyme kinetics', xLabel: 'Substrate concentration [S]', yLabel: 'Rate v',
                series: [{ label: 'Fitted curve', points: res.curve, kind: 'line' }, ...(data.length ? [{ label: 'Data', points: data, kind: 'scatter' }] : [])],
                description: 'Measured rates and the fitted Michaelis–Menten curve.', onExport: () => ctx.exportTable('michaelis-curve', ['S', 'v'], res.curve) }));
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
            if (isPoints(res.residuals))
                out.push(chart({ title: 'Residuals', xLabel: 'Standard', yLabel: 'Residual', zeroLine: true, series: [{ label: 'Residual', points: res.residuals, kind: 'scatter' }], description: 'Distance of each point from the fitted line; a pattern here means a straight line is not the right model.' }));
            break;
        }
        default: break;
    }
    return out;
}
// Charts and Graphing hand-offs that any operation may attach: `plot` / `plot2` are small result charts, `graph` / `graph2` are specs for the Graphing workspace.
function plotOf(v, name, ctx) {
    if (!isRecord(v) || !Array.isArray(v.series))
        return null;
    const series = [];
    for (const s of v.series) {
        if (!isRecord(s) || !Array.isArray(s.points))
            continue;
        const pts = s.points.filter((p) => Array.isArray(p) && p.length === 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]));
        if (pts.length)
            series.push({ label: String(s.label ?? ''), points: pts, kind: s.kind === 'scatter' ? 'scatter' : 'line', dashed: s.dashed === true });
    }
    if (!series.length)
        return null;
    const markers = (Array.isArray(v.markers) ? v.markers : []).filter(isRecord).map((m) => ({ x: Number(m.x), y: Number(m.y), label: String(m.label ?? '') })).filter((m) => Number.isFinite(m.x) && Number.isFinite(m.y));
    return chart({ title: String(v.title ?? 'Chart'), xLabel: String(v.xLabel ?? ''), yLabel: String(v.yLabel ?? ''), series, markers, zeroLine: v.zeroLine === true,
        description: typeof v.description === 'string' ? v.description : undefined,
        onExport: () => ctx.exportTable(`${ctx.op.id}-${name}`, ['series', 'x', 'y'], series.flatMap((s) => s.points.map((p) => [s.label, p[0], p[1]]))) });
}
function graphButton(spec, label) {
    if (!isRecord(spec) || !Array.isArray(spec.layers) || !spec.layers.length)
        return null;
    return h('button', { class: 'btn small', type: 'button', text: label, title: 'Opens this in the Graphing workspace with its sliders, so you can change the values and zoom.',
        on: { click: () => void navigate({ workspace: 'graph', kind: 'graph', payload: { spec } }) } });
}
function pairsFrom(v) {
    if (!Array.isArray(v))
        return [];
    const out = [];
    for (const p of v) {
        if (Array.isArray(p) && p.length >= 2) {
            const a = Number(p[0]);
            const b = Number(p[1]);
            if (Number.isFinite(a) && Number.isFinite(b))
                out.push([a, b]);
        }
    }
    return out;
}
// ------------------------------------------------------------------------------------------------------------------ the renderer
export function renderResult(res, ctx, skip = new Set()) {
    const root = h('div', { class: 'result' });
    if (res.ok === false) {
        const e = isRecord(res.error) ? res.error : {};
        root.appendChild(h('div', { class: 'note-line error', role: 'alert', text: `${String(e.message ?? 'The calculation failed.')}${e.hint ? ' ' + String(e.hint) : ''}` }));
        return root;
    }
    const cards = [];
    const sections = [];
    const leadKey = LEAD.find((k) => typeof res[k] === 'string');
    if (typeof res.latex === 'string' && leadKey)
        cards.push(kv(labelOf(leadKey === 'balanced' ? 'balancedEquation' : leadKey), math(res.latex, { display: false }), undefined, 'big'));
    let first = true;
    for (const [key, v] of Object.entries(res)) {
        if (SKIP.has(key) || skip.has(key) || HIDE_COLS.has(key))
            continue;
        if (key === leadKey && typeof res.latex === 'string')
            continue;
        if (isNum(v)) {
            cards.push(kv(labelOf(key), numNode(v), numExtra(v), first ? 'key' : ''));
            first = false;
            continue;
        }
        if (typeof v === 'string') {
            cards.push(kv(labelOf(key), h('span', { class: v.length > 40 ? 'seq' : '', text: v }), undefined, v.length > 28 ? 'big' : ''));
            continue;
        }
        if (typeof v === 'number' || typeof v === 'boolean') {
            cards.push(kv(labelOf(key), cellText(v)));
            continue;
        }
        if (Array.isArray(v) && v.length && v.every(isNum)) {
            cards.push(kv(labelOf(key), v.map((x) => x.text).join('  to  ')));
            continue;
        }
        if (Array.isArray(v) && v.length && v.every((x) => typeof x === 'string')) {
            sections.push(h('div', null, h('div', { class: 'sectitle', text: labelOf(key) }), h('div', { class: 'chips' }, v.map((x) => h('span', { class: 'chip', text: x })))));
            continue;
        }
        if (isRowList(v)) {
            sections.push(h('div', { class: 'section' }, h('div', { class: 'sectitle', text: labelOf(key) }), tableOf(v, key, ctx)));
            continue;
        }
        if (isRecord(v)) {
            const flatNums = Object.values(v).every((x) => isNum(x) || typeof x !== 'object' || x === null || (Array.isArray(x) && x.every((y) => typeof y === 'string')));
            if (flatNums)
                sections.push(h('div', { class: 'section' }, h('div', { class: 'sectitle', text: labelOf(key) }), nestedGrid(v)));
            else
                sections.push(h('div', { class: 'section' }, h('div', { class: 'sectitle', text: labelOf(key) }), h('div', { class: 'kvs' }, kv(labelOf(key), cellText(v), undefined, 'big'))));
        }
    }
    if (cards.length)
        root.appendChild(h('div', { class: 'kvs' }, cards));
    for (const c of chartsFor(res, ctx))
        root.appendChild(c);
    const plots = [plotOf(res.plot, 'chart', ctx), plotOf(res.plot2, 'chart2', ctx)].filter((x) => x !== null);
    for (const c of plots)
        root.appendChild(c);
    const hands = [graphButton(res.graph, 'Open in Graphing'), graphButton(res.graph2, 'Open the second chart in Graphing')].filter((x) => x !== null);
    if (hands.length)
        root.appendChild(h('div', { class: 'row graph-hand' }, hands));
    for (const s of sections)
        root.appendChild(s);
    const assumptions = (Array.isArray(res.assumptions) ? res.assumptions : []).filter((x) => typeof x === 'string');
    if (assumptions.length)
        root.appendChild(h('div', { class: 'section assumptions' }, h('div', { class: 'sectitle', text: 'Assumptions and conventions' }), h('ul', { class: 'assume' }, assumptions.map((a) => h('li', { text: a })))));
    const warnings = (Array.isArray(res.warnings) ? res.warnings : []).map(messageOf).filter(Boolean);
    const notes = (Array.isArray(res.notes) ? res.notes : []).map(messageOf).filter(Boolean);
    if (warnings.length || notes.length)
        root.appendChild(h('div', { class: 'notes' }, [...warnings, ...notes].map((w) => h('div', { class: 'note-line', text: w }))));
    if (Array.isArray(res.steps) && res.steps.length) {
        root.appendChild(h('details', { class: 'working-box' }, h('summary', { text: `Working (${res.steps.length} step${res.steps.length === 1 ? '' : 's'})` }), stepsList(res.steps)));
    }
    if (isRecord(res.meta) && typeof res.meta.source === 'string')
        root.appendChild(h('p', { class: 'muted source', text: `Data: ${res.meta.source}` }));
    return root;
}
export function showInto(target, node) {
    if (node === null)
        replace(target);
    else
        replace(target, ...(Array.isArray(node) ? node : [node]));
}
//# sourceMappingURL=domain-results.js.map