// The 3D side of the Graphing workspace: surfaces z = f(x, y), parametric surfaces, space curves and point sets, drawn on a canvas that can be
// orbited, panned and zoomed. The service samples the geometry once; moving the camera only projects and paints it again.
import { formatNumber, formatTick, paletteColor, ticks } from '../../core/graphmath.js';
import { contextFor, newEntryId } from '../../core/session.js';
import { DEFAULT_CAMERA, clampCamera, cloneCamera, colormap, hexToRgb, makeProjector, normalizer, orbit, panBy, rgbCss, shade, zoomBy, } from '../../core/scene3d.js';
import { clamp, debounce, isRecord, splitPairs } from '../../core/util.js';
import { ApiError, api } from '../api.js';
import { h, replace } from '../dom.js';
import { store } from '../store.js';
import { iconButton, saveBlob, toast } from '../ui.js';
import { exportControls } from './spatial-export.js';
import { savedList } from './saved.js';
import { missingName, paintSliderBox } from './sliders.js';
const LAYER_TYPES = [
    ['surface', 'Surface z = f(x, y)'], ['psurface', 'Parametric surface (x, y, z of u, v)'], ['curve3d', 'Space curve (x, y, z of t)'], ['points3d', 'Points (x y z per line)'],
];
const START = [{ type: 'surface', expr: 'sin(x)*cos(y)' }];
const DEG = Math.PI / 180;
const VIEWS = [
    ['Isometric', { azimuth: DEFAULT_CAMERA.azimuth, elevation: DEFAULT_CAMERA.elevation }],
    ['Top', { azimuth: -Math.PI / 2, elevation: 89 * DEG }],
    ['Front', { azimuth: -Math.PI / 2, elevation: 0 }],
    ['Side', { azimuth: 0, elevation: 0 }],
];
const EXAMPLES = [
    { title: 'sin(x)·cos(y)', layers: [{ type: 'surface', expr: 'sin(x)*cos(y)' }], domain: { xmin: '-5', xmax: '5', ymin: '-5', ymax: '5' } },
    { title: 'Paraboloid', layers: [{ type: 'surface', expr: 'x^2 + y^2' }], domain: { xmin: '-2', xmax: '2', ymin: '-2', ymax: '2' } },
    { title: 'Saddle', layers: [{ type: 'surface', expr: 'x^2 - y^2' }], domain: { xmin: '-2', xmax: '2', ymin: '-2', ymax: '2' } },
    { title: 'Ripple', layers: [{ type: 'surface', expr: 'sin(sqrt(x^2 + y^2))' }], domain: { xmin: '-8', xmax: '8', ymin: '-8', ymax: '8' } },
    { title: 'Slider: a·sin(x)·cos(y)', layers: [{ type: 'surface', expr: 'a*sin(x)*cos(y)' }], domain: { xmin: '-5', xmax: '5', ymin: '-5', ymax: '5' } },
    { title: 'Pole: 1/(x²+y²)', layers: [{ type: 'surface', expr: '1/(x^2 + y^2)' }], domain: { xmin: '-3', xmax: '3', ymin: '-3', ymax: '3' } },
    { title: 'Square root (gaps)', layers: [{ type: 'surface', expr: 'sqrt(1 - x^2 - y^2)' }], domain: { xmin: '-2', xmax: '2', ymin: '-2', ymax: '2' } },
    { title: 'Sphere (parametric)', layers: [{ type: 'psurface', x: 'cos(u)*sin(v)', y: 'sin(u)*sin(v)', z: 'cos(v)', umin: '0', umax: '2*pi', vmin: '0', vmax: 'pi', colorBy: 'height' }] },
    { title: 'Torus', layers: [{ type: 'psurface', x: '(2 + cos(v))*cos(u)', y: '(2 + cos(v))*sin(u)', z: 'sin(v)', umin: '0', umax: '2*pi', vmin: '0', vmax: '2*pi', colorBy: 'height' }] },
    { title: 'Helix (curve)', layers: [{ type: 'curve3d', x: 'cos(t)', y: 'sin(t)', z: 't/4', tmin: '0', tmax: '6*pi' }] },
    { title: 'Surface and curve', layers: [{ type: 'surface', expr: 'x*y/4', opacity: 0.8 }, { type: 'curve3d', x: 't', y: 't', z: 't^2/4', tmin: '-2.5', tmax: '2.5' }], domain: { xmin: '-3', xmax: '3', ymin: '-3', ymax: '3' } },
];
const DEFAULT_DOMAIN = { xmin: '-5', xmax: '5', ymin: '-5', ymax: '5', zmin: '', zmax: '' };
const DEFAULT_OPTIONS = { aspect: 'auto', axes: true, grid: true, legend: true };
const DEFAULT_SAMPLES = 48;
const LUT = Array.from({ length: 256 }, (_, i) => colormap(i / 255));
const CONTRACT = 'scical-graph/1';
export function createGraph3DView() {
    let layers = [];
    let params = [];
    let dismissed = new Set();
    let domain = { ...DEFAULT_DOMAIN };
    let samples = DEFAULT_SAMPLES;
    let cam = cloneCamera(DEFAULT_CAMERA);
    let opts = { ...DEFAULT_OPTIONS };
    let result = null;
    let inflight = null;
    let renderSeq = 0;
    let dragging = false;
    let hoverPt = null;
    let pinned = null;
    let lastPreps = [];
    const canvas = h('canvas', { tabindex: '0', role: 'img', 'aria-label': '3D graph. Drag to rotate, shift-drag to move, scroll to zoom, arrow keys rotate, plus and minus zoom, 0 resets the view.' });
    const readout = h('div', { class: 'plot-readout', hidden: true });
    const note = h('div', { class: 'plot-note', hidden: true });
    const wrap = h('div', { class: 'plot-wrap' }, canvas, readout, note);
    const layersBox = h('div', { class: 'graph-layers', style: { display: 'grid', gap: '.7rem' } });
    const slidersBox = h('div', { class: 'sliders' });
    const live = h('div', { class: 'visually-hidden', 'aria-live': 'polite' });
    const statsBox = h('div', { class: 'muted', style: { 'font-size': '.82rem' } });
    const domainInputs = Object.fromEntries(['xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax'].map((k) => [k, h('input', { type: 'text', class: 'mono', spellcheck: 'false', autocomplete: 'off', 'aria-label': `${k[0]} ${k.slice(1) === 'min' ? 'minimum' : 'maximum'}` })]));
    const samplesRange = h('input', { type: 'range', min: '8', max: '160', step: '2', value: String(samples), 'aria-label': 'Samples along each axis' });
    const samplesLabel = h('span', { class: 'mono' });
    // ------------------------------------------------------------------------------------------------ the scene model
    const addLayer = (init = {}) => {
        const l = { id: 'L' + newEntryId().slice(0, 6), type: 'surface', color: paletteColor(layers.length), visible: true, ...init };
        if (l.colorBy === undefined && (l.type === 'surface' || l.type === 'psurface'))
            l.colorBy = 'height';
        layers.push(l);
        return l;
    };
    const hasContent = (l) => {
        switch (l.type) {
            case 'psurface':
            case 'curve3d': return !!(l.x?.trim() && l.y?.trim() && l.z?.trim());
            case 'points3d': return splitPairs(l.data ?? '').some((p) => p.length >= 3);
            default: return !!l.expr?.trim();
        }
    };
    const specLayer = (l) => {
        const base = { id: l.id, type: l.type, visible: l.visible !== false, color: l.color };
        if (l.opacity !== undefined && l.opacity < 1)
            base.opacity = l.opacity;
        if (l.wireframe)
            base.wireframe = true;
        if (l.colorBy)
            base.colorBy = l.colorBy;
        const put = (k) => { const v = l[k]; if (typeof v === 'string' && v.trim())
            base[k] = v.trim(); };
        switch (l.type) {
            case 'surface':
                base.expr = l.expr;
                if (domain.zmin.trim())
                    base.zmin = domain.zmin.trim();
                if (domain.zmax.trim())
                    base.zmax = domain.zmax.trim();
                break;
            case 'psurface':
                put('x');
                put('y');
                put('z');
                put('umin');
                put('umax');
                put('vmin');
                put('vmax');
                break;
            case 'curve3d':
                put('x');
                put('y');
                put('z');
                put('tmin');
                put('tmax');
                break;
            case 'points3d': {
                const rows = splitPairs(l.data ?? '').filter((p) => p.length >= 3);
                base.x = rows.map((r) => r[0]);
                base.y = rows.map((r) => r[1]);
                base.z = rows.map((r) => r[2]);
                base.data = l.data ?? '';
                base.label = l.label || 'points';
                break;
            }
        }
        return base;
    };
    const paramValues = () => Object.fromEntries(params.map((p) => [p.name, p.value]));
    const buildSpec = () => {
        const dom = {};
        for (const k of ['xmin', 'xmax', 'ymin', 'ymax'])
            if (domain[k].trim())
                dom[k] = domain[k].trim();
        return { mode: '3d', contract: CONTRACT, domain: dom, samples: { u: samples, v: samples }, params: paramValues(),
            axes: { x: { label: 'x', unit: '' }, y: { label: 'y', unit: '' }, z: { label: 'z', unit: '' } },
            layers: layers.filter(hasContent).map(specLayer) };
    };
    /** Everything needed to open this scene again: the service spec plus the view the person had. */
    const fullSpec = () => ({
        ...buildSpec(),
        view3d: { camera: cloneCamera(cam), options: { ...opts }, sliders: params.map((p) => ({ ...p })), zwindow: { zmin: domain.zmin, zmax: domain.zmax } },
    });
    // ------------------------------------------------------------------------------------------------ requests
    const requestRender = async () => {
        const seq = ++renderSeq;
        inflight?.abort();
        if (!layers.some(hasContent)) {
            result = null;
            note.hidden = true;
            paintLayerInfo();
            draw();
            return;
        }
        const ctl = new AbortController();
        inflight = ctl;
        note.hidden = false;
        note.textContent = 'Computing…';
        try {
            const res = await api.graph('render3d', buildSpec(), store.settings, contextFor(store.entries, ''), ctl.signal);
            if (seq !== renderSeq)
                return;
            if (!res.ok) {
                note.hidden = false;
                note.textContent = res.error?.message ?? 'The graph could not be drawn.';
                result = null;
                paintLayerInfo();
                draw();
                return;
            }
            note.hidden = true;
            result = res;
            pinned = null;
            hoverPt = null;
            readout.hidden = true;
            paintLayerInfo();
            paintStats();
            saveControls.refresh();
            draw();
            void autoSliders(res);
        }
        catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError')
                return;
            note.hidden = false;
            note.textContent = e instanceof ApiError ? e.message : 'The graph could not be drawn.';
        }
    };
    const scheduleRender = debounce(() => void requestRender(), 220);
    const autoSliders = async (res) => {
        let added = false;
        for (const lr of res.layers) {
            if (lr.ok || !lr.error)
                continue;
            const name = missingName(lr.error.message);
            if (!name || params.some((p) => p.name === name) || dismissed.has(name))
                continue;
            params.push({ name, value: 1, min: -5, max: 5, step: 0.05 });
            added = true;
        }
        if (added) {
            paintSliders();
            await requestRender();
        }
    };
    // ------------------------------------------------------------------------------------------------ painting
    const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const screenInk = () => ({ bg: css('--plot-bg') || '#fff', grid: css('--plot-grid') || '#ccc', axis: css('--plot-axis') || '#333', text: css('--text') || '#000', accent: css('--accent-ink') || '#b89b00', halo: css('--plot-bg') || '#fff' });
    // The worksheet picture has no background; a middle grey stays legible on white, sepia and dark pages.
    const EXPORT_INK = { bg: null, grid: 'rgba(118,128,142,.30)', axis: '#76808e', text: '#76808e', accent: '#a07f00', halo: 'rgba(255,255,255,0)' };
    /** 'Automatic' keeps true proportions for parametric surfaces and curves (a sphere must look round) and fits explicit surfaces z = f(x, y) to the box. */
    const effectiveAspect = () => {
        if (opts.aspect !== 'auto')
            return opts.aspect;
        const geometric = result?.layers.some((lr) => lr.ok && (lr.type === 'psurface' || lr.type === 'curve3d') && layers.find((l) => l.id === lr.id)?.visible !== false);
        return geometric ? 'equal' : 'box';
    };
    const draw = () => {
        const dpr = window.devicePixelRatio || 1;
        const w = Math.max(1, Math.round(canvas.clientWidth));
        const hgt = Math.max(1, Math.round(canvas.clientHeight));
        if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(hgt * dpr)) {
            canvas.width = Math.round(w * dpr);
            canvas.height = Math.round(hgt * dpr);
        }
        const ctx = canvas.getContext('2d');
        if (!ctx)
            return;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const labels = paint(ctx, w, hgt, { ink: screenInk(), hover: true, fontPx: 12, fast: dragging });
        canvas.setAttribute('aria-label', labels.length ? `3D graph of ${labels.join('; ')}. Drag to rotate, shift-drag to move, scroll to zoom, arrow keys rotate, plus and minus zoom, 0 resets the view.` : 'Empty 3D graph. Enter a formula on the left.');
    };
    let queued = false;
    const queueDraw = () => { if (queued)
        return; queued = true; requestAnimationFrame(() => { queued = false; draw(); }); };
    const paint = (ctx, w, hgt, pass) => {
        const { ink, fontPx: fs } = pass;
        if (ink.bg) {
            ctx.fillStyle = ink.bg;
            ctx.fillRect(0, 0, w, hgt);
        }
        else
            ctx.clearRect(0, 0, w, hgt);
        ctx.font = `${fs}px system-ui, sans-serif`;
        const res = result;
        if (pass.hover)
            lastPreps = [];
        if (!res || !res.bounds) {
            ctx.fillStyle = ink.text;
            ctx.globalAlpha = 0.7;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(res ? 'Nothing is defined on this domain.' : layers.some(hasContent) ? 'Computing…' : 'Enter a formula on the left.', w / 2, hgt / 2);
            ctx.globalAlpha = 1;
            return [];
        }
        const b = res.bounds;
        const norm = normalizer(b, effectiveAspect());
        const proj = makeProjector(cam, w, hgt);
        const [cx, cy, cz] = norm.center;
        const [sx, sy, sz] = norm.scale;
        const P = (x, y, z) => proj.project([(x - cx) * sx, (y - cy) * sy, (z - cz) * sz]);
        const mid = { x: (b.xmin + b.xmax) / 2, y: (b.ymin + b.ymax) / 2, z: (b.zmin + b.zmax) / 2 };
        const zspan = b.zmax - b.zmin || 1;
        const xt = ticks(b.xmin, b.xmax, 5);
        const yt = ticks(b.ymin, b.ymax, 5);
        const zt = ticks(b.zmin, b.zmax, 5);
        const line = (a, c) => { const p = P(a[0], a[1], a[2]); const q = P(c[0], c[1], c[2]); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); };
        // the far walls and the floor carry the grid; the nearest edges carry the axes
        const xWall = P(b.xmin, mid.y, mid.z).depth > P(b.xmax, mid.y, mid.z).depth ? b.xmin : b.xmax;
        const yWall = P(mid.x, b.ymin, mid.z).depth > P(mid.x, b.ymax, mid.z).depth ? b.ymin : b.ymax;
        if (opts.axes && opts.grid) {
            ctx.lineWidth = 1;
            ctx.strokeStyle = ink.grid;
            ctx.beginPath();
            for (const x of xt.values) {
                line([x, b.ymin, b.zmin], [x, b.ymax, b.zmin]);
                line([x, yWall, b.zmin], [x, yWall, b.zmax]);
            }
            for (const y of yt.values) {
                line([b.xmin, y, b.zmin], [b.xmax, y, b.zmin]);
                line([xWall, y, b.zmin], [xWall, y, b.zmax]);
            }
            for (const z of zt.values) {
                line([xWall, b.ymin, z], [xWall, b.ymax, z]);
                line([b.xmin, yWall, z], [b.xmax, yWall, z]);
            }
            ctx.stroke();
        }
        if (opts.axes) {
            ctx.lineWidth = 1.2;
            ctx.strokeStyle = ink.axis;
            ctx.globalAlpha = 0.55;
            ctx.beginPath();
            line([b.xmin, b.ymin, b.zmin], [b.xmax, b.ymin, b.zmin]);
            line([b.xmax, b.ymin, b.zmin], [b.xmax, b.ymax, b.zmin]);
            line([b.xmax, b.ymax, b.zmin], [b.xmin, b.ymax, b.zmin]);
            line([b.xmin, b.ymax, b.zmin], [b.xmin, b.ymin, b.zmin]);
            ctx.stroke();
            ctx.globalAlpha = 1;
        }
        // ---- layers: project once, then paint far to near
        const items = [];
        const preps = [];
        const drawn = [];
        res.layers.forEach((lr) => {
            const ui = layers.find((l) => l.id === lr.id);
            if (!ui || !lr.ok || lr.type === 'hidden' || ui.visible === false)
                return;
            drawn.push({ ui, lr });
        });
        const meshExtra = new Map();
        drawn.forEach(({ ui, lr }, p) => {
            const prep = { ui, lr, blocks: [] };
            preps.push(prep);
            if (lr.vertices && lr.cells) {
                const V = lr.vertices;
                const n = V.length / 3;
                const px = new Float64Array(n);
                const py = new Float64Array(n);
                const pd = new Float64Array(n);
                const shadeV = new Float32Array(n);
                const tV = new Float32Array(n);
                const N = lr.normals;
                for (let i = 0; i < n; i++) {
                    const s = P(V[3 * i], V[3 * i + 1], V[3 * i + 2]);
                    px[i] = s.x;
                    py[i] = s.y;
                    pd[i] = s.depth;
                    tV[i] = (V[3 * i + 2] - b.zmin) / zspan;
                    if (N) {
                        const nx = N[3 * i] / sx;
                        const ny = N[3 * i + 1] / sy;
                        const nz = N[3 * i + 2] / sz;
                        const len = Math.hypot(nx, ny, nz) || 1;
                        shadeV[i] = shade([nx / len, ny / len, nz / len], proj);
                    }
                    else
                        shadeV[i] = 0.8;
                }
                prep.blocks.push({ px, py, src: V });
                meshExtra.set(p, { shadeV, tV, cells: lr.cells });
                const C = lr.cells;
                for (let k = 0; k < C.length / 4; k++) {
                    const a = C[4 * k];
                    const bb = C[4 * k + 1];
                    const d = C[4 * k + 2];
                    const c = C[4 * k + 3];
                    items.push({ d: (pd[a] + pd[bb] + pd[d]) / 3, t: 0, p, i: k, j: 0 });
                    items.push({ d: (pd[a] + pd[d] + pd[c]) / 3, t: 0, p, i: k, j: 1 });
                }
            }
            else if (lr.segments) {
                lr.segments.forEach((seg, si) => {
                    const n = seg.length / 3;
                    const px = new Float64Array(n);
                    const py = new Float64Array(n);
                    const pd = new Float64Array(n);
                    for (let i = 0; i < n; i++) {
                        const s = P(seg[3 * i], seg[3 * i + 1], seg[3 * i + 2]);
                        px[i] = s.x;
                        py[i] = s.y;
                        pd[i] = s.depth;
                    }
                    prep.blocks.push({ px, py, src: seg });
                    for (let i = 0; i + 1 < n; i++)
                        items.push({ d: (pd[i] + pd[i + 1]) / 2 - 0.03, t: 1, p, i: si, j: i });
                });
            }
            else if (lr.points) {
                const V = lr.points;
                const n = V.length / 3;
                const px = new Float64Array(n);
                const py = new Float64Array(n);
                for (let i = 0; i < n; i++) {
                    const s = P(V[3 * i], V[3 * i + 1], V[3 * i + 2]);
                    px[i] = s.x;
                    py[i] = s.y;
                    items.push({ d: s.depth - 0.03, t: 2, p, i, j: 0 });
                }
                prep.blocks.push({ px, py, src: V });
            }
        });
        items.sort((a, c) => c.d - a.d);
        const wireFill = ink.bg;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        for (const it of items) {
            const prep = preps[it.p];
            const ui = prep.ui;
            if (it.t === 0) {
                const ex = meshExtra.get(it.p);
                if (!ex)
                    continue;
                const { px, py } = prep.blocks[0];
                const C = ex.cells;
                const a = C[4 * it.i];
                const bb = C[4 * it.i + 1];
                const d = C[4 * it.i + 2];
                const c = C[4 * it.i + 3];
                const [i0, i1, i2] = it.j === 0 ? [a, bb, d] : [a, d, c];
                const sh = (ex.shadeV[i0] + ex.shadeV[i1] + ex.shadeV[i2]) / 3;
                const rgb = ui.colorBy === 'solid' ? hexToRgb(ui.color) : LUT[clamp(Math.round(((ex.tV[i0] + ex.tV[i1] + ex.tV[i2]) / 3) * 255), 0, 255)];
                const col = rgbCss(rgb, 0.55 + 0.55 * sh);
                const alpha = ui.opacity ?? 1;
                ctx.beginPath();
                ctx.moveTo(px[i0], py[i0]);
                ctx.lineTo(px[i1], py[i1]);
                ctx.lineTo(px[i2], py[i2]);
                ctx.closePath();
                if (ui.wireframe) {
                    if (wireFill) {
                        ctx.fillStyle = wireFill;
                        ctx.fill();
                    }
                    ctx.beginPath();
                    if (it.j === 0) {
                        ctx.moveTo(px[a], py[a]);
                        ctx.lineTo(px[bb], py[bb]);
                        ctx.lineTo(px[d], py[d]);
                    }
                    else {
                        ctx.moveTo(px[d], py[d]);
                        ctx.lineTo(px[c], py[c]);
                        ctx.lineTo(px[a], py[a]);
                    }
                    ctx.strokeStyle = col;
                    ctx.lineWidth = 1;
                    ctx.stroke();
                }
                else {
                    ctx.globalAlpha = alpha;
                    ctx.fillStyle = col;
                    ctx.fill();
                    if (alpha >= 1 && !pass.fast) {
                        ctx.strokeStyle = col;
                        ctx.lineWidth = 0.7;
                        ctx.stroke();
                    }
                    ctx.globalAlpha = 1;
                }
            }
            else if (it.t === 1) {
                const blk = prep.blocks[it.i];
                ctx.beginPath();
                ctx.moveTo(blk.px[it.j], blk.py[it.j]);
                ctx.lineTo(blk.px[it.j + 1], blk.py[it.j + 1]);
                ctx.strokeStyle = ui.color;
                ctx.lineWidth = 2.4 * (fs / 12) ** 0.5;
                ctx.globalAlpha = ui.opacity ?? 1;
                ctx.stroke();
                ctx.globalAlpha = 1;
            }
            else {
                const blk = prep.blocks[0];
                ctx.beginPath();
                ctx.arc(blk.px[it.i], blk.py[it.i], 3.4 * (fs / 12), 0, Math.PI * 2);
                ctx.fillStyle = ui.color;
                ctx.fill();
                ctx.strokeStyle = ink.halo;
                ctx.lineWidth = 1;
                ctx.stroke();
            }
        }
        if (pass.hover)
            lastPreps = preps;
        // ---- axes, tick labels and titles, on top of the surfaces
        if (opts.axes) {
            const center = P(mid.x, mid.y, mid.z);
            const outward = (p, dist) => {
                const dx = p.x - center.x;
                const dy = p.y - center.y;
                const len = Math.hypot(dx, dy) || 1;
                return [p.x + (dx / len) * dist, p.y + (dy / len) * dist];
            };
            const yFront = P(mid.x, b.ymin, b.zmin).y > P(mid.x, b.ymax, b.zmin).y ? b.ymin : b.ymax;
            const xSide = P(b.xmin, mid.y, b.zmin).y > P(b.xmax, mid.y, b.zmin).y ? b.xmin : b.xmax;
            const corners = [[b.xmin, b.ymin], [b.xmax, b.ymin], [b.xmin, b.ymax], [b.xmax, b.ymax]];
            const left = corners.reduce((best, c) => (P(c[0], c[1], b.zmin).x < P(best[0], best[1], b.zmin).x ? c : best), corners[0]);
            // seen from straight above (or below) the z axis is a point: there is nothing to label
            const zLen = Math.hypot(P(left[0], left[1], b.zmax).x - P(left[0], left[1], b.zmin).x, P(left[0], left[1], b.zmax).y - P(left[0], left[1], b.zmin).y);
            const showZ = zLen > fs * 3;
            ctx.strokeStyle = ink.axis;
            ctx.lineWidth = 1.6;
            ctx.beginPath();
            line([b.xmin, yFront, b.zmin], [b.xmax, yFront, b.zmin]);
            line([xSide, b.ymin, b.zmin], [xSide, b.ymax, b.zmin]);
            if (showZ)
                line([left[0], left[1], b.zmin], [left[0], left[1], b.zmax]);
            ctx.stroke();
            ctx.fillStyle = ink.text;
            ctx.textBaseline = 'middle';
            ctx.textAlign = 'center';
            const small = `${Math.max(9, Math.round(fs * 0.92))}px system-ui, sans-serif`;
            const place = (text, p, dist, bold = false) => {
                const [tx, ty] = outward(p, dist);
                ctx.font = bold ? `600 ${fs}px system-ui, sans-serif` : small;
                ctx.globalAlpha = bold ? 1 : 0.85;
                ctx.fillText(text, clamp(tx, 6 + text.length * fs * 0.3, w - 6 - text.length * fs * 0.3), clamp(ty, fs, hgt - fs));
                ctx.globalAlpha = 1;
            };
            for (const x of xt.values)
                place(formatTick(x, xt.step), P(x, yFront, b.zmin), fs * 1.3);
            for (const y of yt.values)
                if (y !== yFront)
                    place(formatTick(y, yt.step), P(xSide, y, b.zmin), fs * 1.3); // the corner already has the x label
            const cornerHasXY = left[1] === yFront || left[0] === xSide; // the floor corner already carries an x or y label
            if (showZ)
                for (const z of zt.values)
                    if (!(cornerHasXY && z - b.zmin < zt.step * 0.5))
                        place(formatTick(z, zt.step), P(left[0], left[1], z), fs * 1.5);
            const title = (k) => { const a = res.axes[k]; return a.unit ? `${a.label} (${a.unit})` : a.label; };
            place(title('x'), P(mid.x, yFront, b.zmin), fs * 3.2, true);
            place(title('y'), P(xSide, mid.y, b.zmin), fs * 3.2, true);
            if (showZ) {
                const top = P(left[0], left[1], b.zmax);
                ctx.font = `600 ${fs}px system-ui, sans-serif`;
                ctx.fillText(title('z'), clamp(top.x, 12, w - 12), clamp(top.y - fs * 1.6, fs, hgt - fs));
            }
        }
        // ---- legend and colour bar
        const labels = drawn.map((d) => d.lr.label ?? '').filter(Boolean);
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        if (opts.legend && drawn.length) {
            let y = fs + 6;
            ctx.font = `${fs}px system-ui, sans-serif`;
            for (const { ui, lr } of drawn) {
                const text = (lr.label ?? '').length > 52 ? (lr.label ?? '').slice(0, 51) + '…' : lr.label ?? '';
                if (ui.colorBy === 'height' && lr.vertices) {
                    const g = ctx.createLinearGradient(8, 0, 8 + fs * 1.4, 0);
                    g.addColorStop(0, rgbCss(LUT[20]));
                    g.addColorStop(0.5, rgbCss(LUT[128]));
                    g.addColorStop(1, rgbCss(LUT[235]));
                    ctx.fillStyle = g;
                }
                else
                    ctx.fillStyle = ui.color;
                ctx.fillRect(8, y - fs * 0.4, fs * 1.4, fs * 0.8);
                ctx.fillStyle = ink.text;
                ctx.fillText(text, 8 + fs * 1.4 + 6, y);
                y += fs * 1.5;
            }
        }
        if (drawn.some((d) => d.ui.colorBy === 'height' && d.lr.vertices)) {
            const bw = fs;
            const bh = Math.min(hgt * 0.4, 160 * (fs / 12));
            const x0 = w - fs * 5.6;
            const y0 = (hgt - bh) / 2;
            const g = ctx.createLinearGradient(0, y0 + bh, 0, y0);
            for (let i = 0; i <= 8; i++)
                g.addColorStop(i / 8, rgbCss(LUT[Math.round((i / 8) * 255)]));
            ctx.fillStyle = g;
            ctx.fillRect(x0, y0, bw, bh);
            ctx.strokeStyle = ink.axis;
            ctx.globalAlpha = 0.6;
            ctx.lineWidth = 1;
            ctx.strokeRect(x0 + 0.5, y0 + 0.5, bw, bh);
            ctx.globalAlpha = 1;
            ctx.fillStyle = ink.text;
            ctx.font = `${Math.max(9, Math.round(fs * 0.92))}px system-ui, sans-serif`;
            const ct = ticks(b.zmin, b.zmax, 4);
            for (const v of ct.values) {
                const yy = y0 + bh - ((v - b.zmin) / zspan) * bh;
                ctx.fillText(formatTick(v, ct.step), x0 + bw + 5, yy);
            }
            ctx.font = `600 ${fs}px system-ui, sans-serif`;
            ctx.textAlign = 'center';
            ctx.fillText(res.axes.z.label, x0 + bw / 2, y0 - fs);
            ctx.textAlign = 'left';
        }
        // ---- marks
        const mark = (pt, strong) => {
            const s = P(pt.x, pt.y, pt.z);
            ctx.strokeStyle = ink.accent;
            ctx.fillStyle = ink.bg ?? 'rgba(0,0,0,0)';
            ctx.lineWidth = 2.4;
            ctx.beginPath();
            ctx.arc(s.x, s.y, 5.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.stroke();
            if (strong) {
                ctx.fillStyle = ink.text;
                ctx.font = `600 ${fs}px system-ui, sans-serif`;
                const right = s.x > w - 190;
                ctx.textAlign = right ? 'right' : 'left';
                ctx.textBaseline = 'bottom';
                ctx.fillText(pt.label, s.x + (right ? -9 : 9), s.y - 7);
            }
        };
        if (pinned)
            mark(pinned, true);
        if (pass.hover && hoverPt && !dragging)
            mark(hoverPt, false);
        return labels;
    };
    // ------------------------------------------------------------------------------------------------ pointer and keyboard
    const rectOf = () => canvas.getBoundingClientRect();
    const nearestPoint = (mx, my) => {
        let best = null;
        let bd = 15 * 15;
        for (const prep of lastPreps) {
            for (const blk of prep.blocks) {
                const n = blk.px.length;
                for (let i = 0; i < n; i++) {
                    const dx = blk.px[i] - mx;
                    const dy = blk.py[i] - my;
                    const d2 = dx * dx + dy * dy;
                    if (d2 < bd) {
                        bd = d2;
                        best = { x: blk.src[3 * i], y: blk.src[3 * i + 1], z: blk.src[3 * i + 2], label: '' };
                    }
                }
            }
        }
        if (best)
            best.label = `(${formatNumber(best.x, 5)}, ${formatNumber(best.y, 5)}, ${formatNumber(best.z, 5)})`;
        return best;
    };
    const pointers = new Map();
    let moved = 0;
    let panMode = false;
    let pinch = 0;
    canvas.addEventListener('contextmenu', (ev) => ev.preventDefault());
    canvas.addEventListener('pointerdown', (ev) => {
        canvas.setPointerCapture(ev.pointerId);
        pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
        moved = 0;
        panMode = ev.button === 2 || ev.button === 1 || ev.shiftKey;
        pinch = 0;
        canvas.classList.add('dragging');
        canvas.focus();
    });
    canvas.addEventListener('pointermove', (ev) => {
        const r = rectOf();
        const prev = pointers.get(ev.pointerId);
        if (!prev) {
            const hit = nearestPoint(ev.clientX - r.left, ev.clientY - r.top);
            if ((hit?.label ?? '') !== (hoverPt?.label ?? '')) {
                hoverPt = hit;
                readout.hidden = !hit;
                if (hit)
                    readout.textContent = hit.label;
                queueDraw();
            }
            return;
        }
        const dx = ev.clientX - prev.x;
        const dy = ev.clientY - prev.y;
        moved += Math.abs(dx) + Math.abs(dy);
        pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
        dragging = true;
        hoverPt = null;
        readout.hidden = true;
        const size = Math.min(r.width, r.height);
        if (pointers.size >= 2) {
            const [a, c] = [...pointers.values()];
            const dist = Math.hypot(a.x - c.x, a.y - c.y);
            if (pinch > 0 && dist > 0)
                cam = zoomBy(cam, dist / pinch);
            pinch = dist;
            cam = panBy(cam, dx / 2, dy / 2, size);
        }
        else if (panMode)
            cam = panBy(cam, dx, dy, size);
        else
            cam = orbit(cam, dx, dy, size);
        queueDraw();
    });
    const endPointer = (ev) => {
        if (!pointers.delete(ev.pointerId))
            return;
        if (pointers.size === 0) {
            canvas.classList.remove('dragging');
            const wasDrag = dragging;
            dragging = false;
            if (moved < 5) {
                const r = rectOf();
                const hit = nearestPoint(ev.clientX - r.left, ev.clientY - r.top);
                pinned = hit;
                live.textContent = hit ? `Point ${hit.label}` : '';
            }
            if (wasDrag || moved < 5)
                queueDraw();
        }
    };
    canvas.addEventListener('pointerup', endPointer);
    canvas.addEventListener('pointercancel', endPointer);
    canvas.addEventListener('pointerleave', () => { if (!pointers.size && hoverPt) {
        hoverPt = null;
        readout.hidden = true;
        queueDraw();
    } });
    canvas.addEventListener('wheel', (ev) => { ev.preventDefault(); cam = zoomBy(cam, ev.deltaY < 0 ? 1.12 : 1 / 1.12); queueDraw(); }, { passive: false });
    canvas.addEventListener('dblclick', () => { cam = cloneCamera(DEFAULT_CAMERA); queueDraw(); });
    canvas.addEventListener('keydown', (ev) => {
        const size = Math.min(canvas.clientWidth, canvas.clientHeight);
        const step = ev.shiftKey ? 60 : 22;
        let handled = true;
        if (ev.key === 'ArrowLeft')
            cam = orbit(cam, -step, 0, size);
        else if (ev.key === 'ArrowRight')
            cam = orbit(cam, step, 0, size);
        else if (ev.key === 'ArrowUp')
            cam = orbit(cam, 0, step, size);
        else if (ev.key === 'ArrowDown')
            cam = orbit(cam, 0, -step, size);
        else if (ev.key === '+' || ev.key === '=')
            cam = zoomBy(cam, 1.2);
        else if (ev.key === '-' || ev.key === '_')
            cam = zoomBy(cam, 1 / 1.2);
        else if (ev.key === '0')
            cam = cloneCamera(DEFAULT_CAMERA);
        else
            handled = false;
        if (handled) {
            ev.preventDefault();
            queueDraw();
        }
    });
    // ------------------------------------------------------------------------------------------------ left column
    const field = (label, input, cls = '') => h('label', { class: `field ${cls}` }, h('span', { class: 'label', text: label }), input);
    const textInput = (value, onInput, label, placeholder = '', mono = true) => {
        const i = h('input', { type: 'text', value: value ?? '', placeholder, 'aria-label': label, spellcheck: 'false', autocomplete: 'off', class: mono ? 'mono' : '' });
        i.addEventListener('input', () => onInput(i.value));
        return i;
    };
    const layerCard = (l, index) => {
        const changed = () => scheduleRender();
        const typeSel = h('select', { 'aria-label': 'Kind of layer' }, LAYER_TYPES.map(([v, t]) => h('option', { value: v, text: t, selected: l.type === v })));
        typeSel.addEventListener('change', () => { l.type = typeSel.value; if (l.type === 'curve3d' || l.type === 'points3d')
            l.colorBy = 'solid';
        else
            l.colorBy ??= 'height'; paintLayers(); changed(); });
        const body = [];
        const triple = (k, arg, ph) => field(`${k}(${arg}) =`, textInput(l[k], (v) => { l[k] = v; changed(); }, `${k} of ${arg}`, ph));
        const range = (a, z, name, lo, hi) => h('div', { class: 'sub' }, field(`${name} from`, textInput(l[a], (v) => { l[a] = v; changed(); }, `${name} minimum`, lo)), field(`${name} to`, textInput(l[z], (v) => { l[z] = v; changed(); }, `${name} maximum`, hi)));
        switch (l.type) {
            case 'psurface':
                body.push(triple('x', 'u, v', 'cos(u)*sin(v)'), triple('y', 'u, v', 'sin(u)*sin(v)'), triple('z', 'u, v', 'cos(v)'), range('umin', 'umax', 'u', '0', '2*pi'), range('vmin', 'vmax', 'v', '0', '2*pi'));
                break;
            case 'curve3d':
                body.push(triple('x', 't', 'cos(t)'), triple('y', 't', 'sin(t)'), triple('z', 't', 't/4'), range('tmin', 'tmax', 't', '0', '2*pi'));
                break;
            case 'points3d': {
                const ta = h('textarea', { rows: '6', class: 'mono', 'aria-label': 'Points, one x y z triple per line', placeholder: '0 0 0\n1 0 0.5\n1 1 1\n0 1 1.5', spellcheck: 'false' });
                ta.value = l.data ?? '';
                ta.addEventListener('input', () => { l.data = ta.value; changed(); });
                body.push(field('Points (x y z per line)', ta), field('Name', textInput(l.label, (v) => { l.label = v; changed(); }, 'Name of the point set', 'points', false)));
                break;
            }
            default: break;
        }
        if (l.type === 'surface' || l.type === 'psurface') {
            const mode = h('select', { 'aria-label': 'Colour' }, h('option', { value: 'height', text: 'Colour by height (z)', selected: l.colorBy !== 'solid' }), h('option', { value: 'solid', text: 'One colour', selected: l.colorBy === 'solid' }));
            mode.addEventListener('change', () => { l.colorBy = mode.value; draw(); });
            const wire = h('input', { type: 'checkbox', checked: !!l.wireframe, 'aria-label': 'Wireframe' });
            wire.addEventListener('change', () => { l.wireframe = wire.checked; draw(); });
            const op = h('input', { type: 'range', min: '0.15', max: '1', step: '0.05', value: String(l.opacity ?? 1), 'aria-label': 'Opacity' });
            op.addEventListener('input', () => { l.opacity = Number(op.value); queueDraw(); });
            body.push(mode, h('div', { class: 'sub' }, h('label', { class: 'check' }, wire, h('span', { text: 'Wireframe' })), h('label', { class: 'field' }, h('span', { class: 'label', text: 'Opacity' }), op)));
        }
        const top = h('div', { class: 'top' }, h('input', { type: 'color', value: l.color, 'aria-label': 'Colour of this layer', on: { input: (ev) => { l.color = ev.target.value; card.style.setProperty('--lc', l.color); draw(); } } }), l.type === 'surface' ? textInput(l.expr, (v) => { l.expr = v; changed(); }, `Surface ${index + 1}`, 'z = sin(x)*cos(y)') : h('span', { class: 'grow muted', text: LAYER_TYPES.find((t) => t[0] === l.type)?.[1] ?? l.type }), iconButton(l.visible === false ? 'eyeoff' : 'eye', l.visible === false ? 'Show this layer' : 'Hide this layer', () => { l.visible = l.visible === false; paintLayers(); draw(); }, 'tiny'), iconButton('trash', 'Remove this layer', () => { layers = layers.filter((x) => x !== l); paintLayers(); changed(); }, 'tiny'));
        const card = h('div', { class: 'layer', data: { layer: l.id } }, top, typeSel, ...body, h('div', { class: 'err', hidden: true, role: 'alert' }), h('div', { class: 'info', hidden: true }));
        card.style.setProperty('--lc', l.color);
        return card;
    };
    const paintLayers = () => { replace(layersBox, layers.map(layerCard)); paintLayerInfo(); };
    const paintLayerInfo = () => {
        for (const l of layers) {
            const card = layersBox.querySelector(`[data-layer="${l.id}"]`);
            if (!card)
                continue;
            const err = card.querySelector('.err');
            const info = card.querySelector('.info');
            const lr = result?.layers.find((r) => r.id === l.id);
            if (err) {
                const bad = lr && !lr.ok && lr.error;
                err.hidden = !bad;
                err.textContent = bad ? lr.error.message + (lr.error.hint ? ' ' + lr.error.hint : '') : '';
            }
            if (info) {
                const bits = [];
                if (lr?.ok && lr.stats) {
                    if (lr.vertices)
                        bits.push(`${(lr.vertices.length / 3).toLocaleString('en')} vertices, ${(lr.stats.triangles ?? (lr.stats.cells ?? 0) * 2).toLocaleString('en')} triangles`);
                    if (lr.zrange)
                        bits.push(`z from ${formatNumber(lr.zrange[0], 5)} to ${formatNumber(lr.zrange[1], 5)}`);
                    if (lr.segments)
                        bits.push(`${lr.segments.length} piece${lr.segments.length === 1 ? '' : 's'}`);
                    if (lr.points)
                        bits.push(`${lr.points.length / 3} points`);
                }
                for (const wn of lr?.warnings ?? [])
                    bits.push(wn);
                info.hidden = bits.length === 0;
                info.textContent = bits.join(' · ');
            }
        }
    };
    const paintStats = () => {
        const b = result?.bounds;
        statsBox.textContent = b ? `Sampled range: x ${formatNumber(b.xmin, 5)} to ${formatNumber(b.xmax, 5)}, y ${formatNumber(b.ymin, 5)} to ${formatNumber(b.ymax, 5)}, z ${formatNumber(b.zmin, 5)} to ${formatNumber(b.zmax, 5)}. ${result?.numeric ?? ''}` : '';
    };
    const paintSliders = () => paintSliderBox(slidersBox, params, {
        change: () => scheduleRender(),
        remove: (p) => { params = params.filter((x) => x !== p); dismissed.add(p.name); paintSliders(); scheduleRender(); },
        repaint: () => paintSliders(),
    });
    // ------------------------------------------------------------------------------------------------ domain and view controls
    const paintDomain = () => {
        for (const k of Object.keys(domainInputs))
            if (document.activeElement !== domainInputs[k])
                domainInputs[k].value = domain[k];
        samplesRange.value = String(samples);
        samplesLabel.textContent = `${samples} × ${samples} = ${(samples * samples).toLocaleString('en')} points per surface`;
    };
    for (const k of Object.keys(domainInputs)) {
        domainInputs[k].placeholder = k.startsWith('z') ? 'automatic' : DEFAULT_DOMAIN[k];
        domainInputs[k].addEventListener('input', () => { domain[k] = domainInputs[k].value; scheduleRender(); });
    }
    samplesRange.addEventListener('input', () => { samples = Number(samplesRange.value); paintDomain(); scheduleRender(); });
    const setCamera = (patch) => { cam = clampCamera({ ...cam, ...patch }); draw(); };
    const projSel = h('select', { 'aria-label': 'Projection' }, h('option', { value: 'perspective', text: 'Perspective' }), h('option', { value: 'orthographic', text: 'Orthographic' }));
    projSel.addEventListener('change', () => setCamera({ projection: projSel.value }));
    const aspectSel = h('select', { 'aria-label': 'Proportions of the plot box' }, h('option', { value: 'auto', text: 'Proportions: automatic' }), h('option', { value: 'box', text: 'Fit to box' }), h('option', { value: 'equal', text: 'Equal scale on all axes' }));
    aspectSel.addEventListener('change', () => { opts.aspect = aspectSel.value; draw(); });
    const toggle = (label, key) => {
        const c = h('input', { type: 'checkbox', checked: opts[key], 'aria-label': label });
        c.addEventListener('change', () => { opts[key] = c.checked; draw(); });
        c.dataset.opt = key;
        return h('label', { class: 'check' }, c, h('span', { text: label }));
    };
    const paintViewControls = () => {
        projSel.value = cam.projection;
        aspectSel.value = opts.aspect;
        for (const c of Array.from(el.querySelectorAll('input[data-opt]')))
            c.checked = opts[c.dataset.opt];
    };
    // ------------------------------------------------------------------------------------------------ exports
    const EXPORT_WIDTH = 900;
    const MAX_PICTURE_BYTES = 900_000;
    const pictureCanvas = (width, scale) => {
        const aspect = clamp((canvas.clientHeight || 500) / (canvas.clientWidth || 800), 0.5, 1.1);
        const hgt = Math.round(width * aspect);
        const c = document.createElement('canvas');
        c.width = width * scale;
        c.height = hgt * scale;
        const ctx = c.getContext('2d');
        if (!ctx)
            return null;
        ctx.setTransform(scale, 0, 0, scale, 0, 0);
        paint(ctx, width, hgt, { ink: EXPORT_INK, hover: false, fontPx: Math.round(width / 52), fast: false });
        return c;
    };
    const hasDrawing = () => !!result?.layers.some((lr) => lr.ok && lr.type !== 'hidden' && layers.find((l) => l.id === lr.id)?.visible !== false);
    /** The scene as it is on screen, drawn again for a document: no background, neutral ink. */
    const renderPicture = async () => {
        if (!hasDrawing())
            return null;
        for (const scale of [2, 1]) {
            const c = pictureCanvas(EXPORT_WIDTH, scale);
            if (!c)
                return null;
            const blob = await new Promise((ok) => c.toBlob(ok, 'image/png'));
            if (!blob || (blob.size > MAX_PICTURE_BYTES && scale > 1))
                continue;
            if (blob.size > MAX_PICTURE_BYTES)
                return null;
            const bytes = new Uint8Array(await blob.arrayBuffer());
            let bin = '';
            for (let i = 0; i < bytes.length; i += 0x8000)
                bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
            const shown = (result?.layers ?? []).filter((lr) => lr.ok && lr.type !== 'hidden');
            return { mediaType: 'image/png', data: btoa(bin), width: c.width, height: c.height, transparent: true,
                series: shown.map((lr) => ({ id: lr.id, color: layers.find((l) => l.id === lr.id)?.color ?? null, dash: 'solid' })) };
        }
        return null;
    };
    const exportPng = async () => {
        if (!hasDrawing()) {
            toast('Draw something first.', 'info');
            return;
        }
        const c = pictureCanvas(1600, 1);
        const blob = c ? await new Promise((ok) => c.toBlob(ok, 'image/png')) : null;
        if (blob)
            saveBlob(blob, 'scical-graph-3d.png');
        else
            toast('The picture could not be created.', 'error');
    };
    const headline = () => `3D graph of ${(result?.layers ?? []).filter((lr) => lr.ok && lr.label).map((lr) => lr.label).join('; ')}`;
    const saveToWorksheet = async () => {
        if (!hasDrawing()) {
            toast('Draw something first.', 'info');
            return;
        }
        let figure = null;
        try {
            figure = await renderPicture();
        }
        catch {
            figure = null;
        }
        store.addEntry({ kind: 'graph', workspace: 'graph', title: '3D graph', spec: fullSpec(), summary: { ok: true, headline: headline() }, ok: true, ...(figure ? { figure } : {}) });
        toast(figure ? 'Graph added to the worksheet' : 'Graph added to the worksheet (without its picture)', figure ? 'ok' : 'info', 2200);
    };
    // ------------------------------------------------------------------------------------------------ examples and loading
    const resetScene = () => { layers = []; params = []; dismissed = new Set(); pinned = null; hoverPt = null; domain = { ...DEFAULT_DOMAIN }; samples = DEFAULT_SAMPLES; };
    const setExample = (ex) => {
        resetScene();
        for (const l of ex.layers)
            addLayer(l);
        domain = { ...DEFAULT_DOMAIN, ...(ex.domain ?? {}) };
        cam = cloneCamera(DEFAULT_CAMERA);
        paintLayers();
        paintSliders();
        paintDomain();
        paintViewControls();
        void requestRender();
    };
    const KINDS = new Set(LAYER_TYPES.map((t) => t[0]));
    const loadSpec = (spec) => {
        resetScene();
        const ls = Array.isArray(spec.layers) ? spec.layers.filter(isRecord) : [];
        ls.forEach((raw, i) => {
            const type = typeof raw.type === 'string' && KINDS.has(raw.type) ? raw.type : 'surface';
            const str = (k) => (typeof raw[k] === 'string' ? raw[k] : undefined);
            const l = addLayer({ id: str('id') ?? undefined, type, color: str('color') ?? paletteColor(i), visible: raw.visible !== false, expr: str('expr'), umin: str('umin'), umax: str('umax'), vmin: str('vmin'), vmax: str('vmax'), tmin: str('tmin'), tmax: str('tmax'),
                label: str('label'), colorBy: raw.colorBy === 'solid' ? 'solid' : raw.colorBy === 'height' ? 'height' : undefined, wireframe: raw.wireframe === true, opacity: typeof raw.opacity === 'number' ? raw.opacity : undefined });
            if (type === 'psurface' || type === 'curve3d') {
                l.x = str('x');
                l.y = str('y');
                l.z = str('z');
            }
            if (type === 'points3d')
                l.data = str('data') ?? (Array.isArray(raw.x) && Array.isArray(raw.y) && Array.isArray(raw.z) ? raw.x.map((v, k) => `${String(v)} ${String(raw.y[k])} ${String(raw.z[k])}`).join('\n') : '');
        });
        const dom = isRecord(spec.domain) ? spec.domain : {};
        for (const k of ['xmin', 'xmax', 'ymin', 'ymax'])
            if (dom[k] !== undefined)
                domain[k] = String(dom[k]);
        const sm = isRecord(spec.samples) ? Number(spec.samples.u) : NaN;
        if (Number.isFinite(sm))
            samples = clamp(Math.round(sm), 8, 160);
        const view = isRecord(spec.view3d) ? spec.view3d : {};
        if (isRecord(view.camera)) {
            const c = view.camera;
            cam = clampCamera({ ...DEFAULT_CAMERA, ...['azimuth', 'elevation', 'zoom', 'panX', 'panY'].reduce((o, k) => (Number.isFinite(c[k]) ? { ...o, [k]: Number(c[k]) } : o), {}), projection: c.projection === 'orthographic' ? 'orthographic' : 'perspective' });
        }
        else
            cam = cloneCamera(DEFAULT_CAMERA);
        if (isRecord(view.options))
            opts = { aspect: view.options.aspect === 'equal' ? 'equal' : view.options.aspect === 'box' ? 'box' : 'auto', axes: view.options.axes !== false, grid: view.options.grid !== false, legend: view.options.legend !== false };
        if (isRecord(view.zwindow)) {
            domain.zmin = String(view.zwindow.zmin ?? '');
            domain.zmax = String(view.zwindow.zmax ?? '');
        }
        const sl = Array.isArray(view.sliders) ? view.sliders : [];
        params = sl.filter(isRecord).filter((p) => typeof p.name === 'string').map((p) => ({ name: String(p.name), value: Number(p.value), min: Number(p.min), max: Number(p.max), step: Number(p.step) || 0.05 }));
        if (!params.length && isRecord(spec.params))
            params = Object.entries(spec.params).filter(([, v]) => Number.isFinite(Number(v))).map(([name, v]) => ({ name, value: Number(v), min: -5, max: 5, step: 0.05 }));
        paintLayers();
        paintSliders();
        paintDomain();
        paintViewControls();
        void requestRender();
    };
    // ------------------------------------------------------------------------------------------------ assembly
    const saveControls = exportControls({
        defaultUnit: 'm',
        unitHint: 'A graph has no unit of its own: one graph unit is saved as one of these.',
        items: [
            { label: 'SGEO model', title: 'The 3D geometry as an SGEO file (surfaces as meshes, curves as curves, points as points), with each formula stored beside it', format: 'sgeo', source: '3d' },
            { label: 'SDRW wireframe', title: 'A 2D drawing of the grid lines as seen from the current camera (orthographic, hidden lines not removed). Derived, not the model.', format: 'sdrw', source: '3d-wireframe' },
            { label: 'SDRW contours', title: 'A 2D contour map (lines of equal z) of the explicit surfaces z = f(x, y). Derived, not the model.', format: 'sdrw', source: '3d-contours',
                enabled: () => (result?.layers ?? []).some((lr) => lr.ok && lr.type === 'surface') },
        ],
        prepare: (item) => {
            if (!hasDrawing())
                return null;
            return { spec: buildSpec(), settings: store.settings, context: contextFor(store.entries, ''), name: 'scical-graph',
                colors: Object.fromEntries(layers.map((l) => [l.id, l.color])),
                ...(item.source === '3d' ? {} : { view: { azimuth: cam.azimuth, elevation: cam.elevation, aspect: effectiveAspect() } }) };
        },
    });
    const exportRow = saveControls.el;
    const el = h('div', { class: 'graph graph3d' }, h('div', { class: 'graph-side' }, h('section', { class: 'card', 'aria-label': 'Layers' }, h('div', { class: 'card-head' }, h('h2', { text: '3D graph' }), h('div', { class: 'row' }, h('button', { class: 'btn small primary', type: 'button', text: 'Add', on: { click: () => { addLayer({ type: 'surface', expr: '' }); paintLayers(); layersBox.querySelector('.layer:last-child input.mono')?.focus(); } } }), h('select', { 'aria-label': 'Add another kind of layer', style: { width: 'auto' }, on: { change: (ev) => { const s = ev.target; if (s.value) {
                const t = s.value;
                addLayer({ type: t, ...(t === 'curve3d' || t === 'points3d' ? { colorBy: 'solid' } : {}) });
                paintLayers();
            } s.value = ''; } } }, h('option', { value: '', text: 'More…' }), LAYER_TYPES.slice(1).map(([v, t]) => h('option', { value: v, text: t }))))), layersBox), h('section', { class: 'card', 'aria-label': 'Domain and sampling' }, h('div', { class: 'card-head' }, h('h3', { text: 'Domain and sampling' })), h('div', { class: 'domain-grid' }, field('x from', domainInputs.xmin), field('x to', domainInputs.xmax), field('y from', domainInputs.ymin), field('y to', domainInputs.ymax), field('z window from', domainInputs.zmin), field('z window to', domainInputs.zmax)), h('label', { class: 'field' }, h('span', { class: 'label', text: 'Samples per axis' }), samplesRange), samplesLabel, h('p', { class: 'muted', style: { 'font-size': '.8rem', margin: '0' }, text: 'Points where the formula is not a real number (a pole, a negative square root) are left out and show as gaps. The z window cuts off very tall parts; leave it empty for an automatic window.' })), h('section', { class: 'card', 'aria-label': 'Sliders' }, h('div', { class: 'card-head' }, h('h3', { text: 'Sliders' })), slidersBox), h('section', { class: 'card', 'aria-label': 'View' }, h('div', { class: 'card-head' }, h('h3', { text: 'View' })), h('div', { class: 'sub', style: { display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '.45rem' } }, projSel, aspectSel), h('div', { class: 'row' }, toggle('Axes', 'axes'), toggle('Grid', 'grid'), toggle('Legend', 'legend')), h('div', { class: 'chips' }, VIEWS.map(([name, patch]) => h('button', { class: 'chip', type: 'button', text: name, on: { click: () => setCamera({ ...patch, panX: 0, panY: 0 }) } })))), h('section', { class: 'card', 'aria-label': 'Examples' }, h('div', { class: 'card-head' }, h('h3', { text: 'Examples' })), h('div', { class: 'chips' }, EXAMPLES.map((ex) => h('button', { class: 'chip', type: 'button', text: ex.title, on: { click: () => setExample(ex) } }))))), h('div', { class: 'graph-main', style: { display: 'grid', gap: '1rem', 'min-width': '0' } }, h('section', { class: 'card plot-card', 'aria-label': '3D plot' }, h('div', { class: 'plot-tools' }, iconButton('plus', 'Zoom in', () => { cam = zoomBy(cam, 1.25); draw(); }), h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Zoom out', title: 'Zoom out', on: { click: () => { cam = zoomBy(cam, 0.8); draw(); } } }, h('span', { text: '−', style: { 'font-size': '1.3rem' } })), h('button', { class: 'btn small', type: 'button', text: 'Reset view', on: { click: () => { cam = cloneCamera(DEFAULT_CAMERA); paintViewControls(); draw(); } } }), h('button', { class: 'btn small', type: 'button', text: 'Clear mark', on: { click: () => { pinned = null; draw(); } } }), h('span', { class: 'grow' }), h('button', { class: 'btn small', type: 'button', text: 'Save PNG', title: 'A picture with a transparent background', on: { click: () => void exportPng() } }), h('button', { class: 'btn small', type: 'button', text: 'Add to worksheet', on: { click: () => void saveToWorksheet() } })), exportRow, wrap, h('p', { class: 'muted', style: { margin: '0', 'font-size': '.82rem' }, text: 'Drag to rotate · shift-drag or right-drag to move · scroll or pinch to zoom · double-click to reset · click a point to mark it · arrow keys, + and − work when the plot is focused.' }), statsBox, live), savedList('Saved 3D graphs in this worksheet', (e) => e.kind === 'graph' && isRecord(e.spec) && e.spec.mode === '3d', (e) => { if (e.spec)
        loadSpec(e.spec); })));
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => queueDraw()) : null;
    ro?.observe(wrap);
    store.on('prefs', () => draw());
    new MutationObserver(() => draw()).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    store.on('session', () => {
        const last = [...store.entries].reverse().find((e) => e.kind === 'graph' && isRecord(e.spec) && e.spec.mode === '3d');
        if (last?.spec)
            loadSpec(last.spec);
        else
            setExample({ title: '', layers: START });
    });
    const last = [...store.entries].reverse().find((e) => e.kind === 'graph' && isRecord(e.spec) && e.spec.mode === '3d');
    if (last?.spec)
        loadSpec(last.spec);
    else {
        for (const l of START)
            addLayer(l);
        paintLayers();
        paintSliders();
        paintDomain();
        paintViewControls();
        setTimeout(() => void requestRender(), 0);
    }
    return {
        el,
        focus: () => canvas.focus(),
        open: (req) => {
            const spec = isRecord(req.payload.spec) ? req.payload.spec : null;
            if (spec)
                loadSpec(spec);
            else
                void requestRender();
        },
    };
}
//# sourceMappingURL=graph3d.js.map