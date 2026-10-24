// Small static charts for results (titration curve, calibration line, residuals, enzyme fit, growth). SVG made with createElementNS.
import { formatTick, paletteColor, ticks } from '../core/graphmath.js';
import { h, s } from './dom.js';
const W = 640;
const H = 340;
const M = { l: 62, r: 18, t: 16, b: 48 };
function extent(values, pad) {
    let lo = Math.min(...values);
    let hi = Math.max(...values);
    if (!Number.isFinite(lo) || !Number.isFinite(hi))
        return [0, 1];
    if (lo === hi) {
        lo -= Math.abs(lo) * 0.1 || 0.5;
        hi += Math.abs(hi) * 0.1 || 0.5;
    }
    const d = (hi - lo) * pad;
    return [lo - d, hi + d];
}
export function chart(o) {
    const all = o.series.flatMap((x) => x.points).filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
    const [x0, x1] = extent(all.map((p) => p[0]), 0.03);
    let [y0, y1] = extent(all.map((p) => p[1]), 0.06);
    if (o.zeroLine) {
        y0 = Math.min(y0, 0);
        y1 = Math.max(y1, 0);
    }
    const px = (x) => M.l + ((x - x0) / (x1 - x0)) * (W - M.l - M.r);
    const py = (y) => H - M.b - ((y - y0) / (y1 - y0)) * (H - M.t - M.b);
    const xt = ticks(x0, x1, 7);
    const yt = ticks(y0, y1, 6);
    const svg = s('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img', 'aria-label': `${o.title}. ${o.description ?? ''}`.trim(), preserveAspectRatio: 'xMidYMid meet' });
    svg.appendChild(s('title', { text: o.title }));
    const g = s('g', { class: 'grid' });
    for (const v of xt.values)
        g.appendChild(s('line', { x1: px(v), x2: px(v), y1: M.t, y2: H - M.b }));
    for (const v of yt.values)
        g.appendChild(s('line', { x1: M.l, x2: W - M.r, y1: py(v), y2: py(v) }));
    svg.appendChild(g);
    if (o.zeroLine)
        svg.appendChild(s('line', { class: 'zero', x1: M.l, x2: W - M.r, y1: py(0), y2: py(0) }));
    svg.appendChild(s('rect', { class: 'frame', x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b }));
    const labels = s('g', { class: 'ticks' });
    for (const v of xt.values)
        labels.appendChild(s('text', { x: px(v), y: H - M.b + 16, 'text-anchor': 'middle', text: formatTick(v, xt.step) }));
    for (const v of yt.values)
        labels.appendChild(s('text', { x: M.l - 8, y: py(v) + 4, 'text-anchor': 'end', text: formatTick(v, yt.step) }));
    svg.appendChild(labels);
    svg.appendChild(s('text', { class: 'axis-label', x: (M.l + W - M.r) / 2, y: H - 8, 'text-anchor': 'middle', text: o.xLabel }));
    const yl = s('text', { class: 'axis-label', x: 14, y: (M.t + H - M.b) / 2, 'text-anchor': 'middle', text: o.yLabel });
    yl.setAttribute('transform', `rotate(-90 14 ${(M.t + H - M.b) / 2})`);
    svg.appendChild(yl);
    o.series.forEach((ser, i) => {
        const color = ser.color ?? paletteColor(i);
        const pts = ser.points.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
        if ((ser.kind ?? 'line') === 'line' && pts.length > 1) {
            svg.appendChild(s('polyline', { class: 'curve' + (ser.dashed ? ' dashed' : ''), points: pts.map((p) => `${px(p[0]).toFixed(1)},${py(p[1]).toFixed(1)}`).join(' '), stroke: color }));
        }
        else {
            for (const p of pts)
                svg.appendChild(s('circle', { class: 'dot', cx: px(p[0]), cy: py(p[1]), r: 4, fill: color }));
        }
    });
    for (const m of o.markers ?? []) {
        svg.appendChild(s('circle', { class: 'marker', cx: px(m.x), cy: py(m.y), r: 5 }));
        svg.appendChild(s('text', { class: 'marker-label', x: Math.min(px(m.x) + 8, W - 90), y: Math.max(py(m.y) - 8, 12), text: m.label }));
    }
    const legend = o.series.length > 1 ? h('ul', { class: 'legend' }, o.series.map((ser, i) => {
        const sw = h('span', { class: 'swatch' });
        sw.style.setProperty('background', ser.color ?? paletteColor(i));
        return h('li', null, sw, ser.label);
    })) : null;
    const rows = o.series.flatMap((ser) => ser.points.slice(0, 300).map((p) => [ser.label, p[0], p[1]]));
    const table = h('details', { class: 'chart-data' }, h('summary', { text: 'Show the numbers' }), h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', null, h('tr', null, h('th', { text: 'Series' }), h('th', { text: o.xLabel }), h('th', { text: o.yLabel }))), h('tbody', null, rows.map((r) => h('tr', null, h('td', { text: r[0] }), h('td', { text: String(+r[1].toPrecision(8)) }), h('td', { text: String(+r[2].toPrecision(8)) })))))), o.onExport ? h('button', { class: 'btn small', type: 'button', text: 'Download as CSV', on: { click: o.onExport } }) : null);
    return h('figure', { class: 'chart-card' }, h('figcaption', { text: o.title }), svg, legend, table);
}
//# sourceMappingURL=charts.js.map