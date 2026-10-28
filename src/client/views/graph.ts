// The Graphing workspace: layers of curves and data on a canvas that can be panned, zoomed and traced, with analysis tools.
import { formatNumber, formatTick, mapper, nearest, pan, paletteColor, PRESETS, sane, square, ticks, traceAt, zoomAt, type Mapper } from '../../core/graphmath.js';
import { newEntryId } from '../../core/session.js';
import type { Entry, GraphFigure, GraphResult, LayerResult, LayerSpec, Pt, View } from '../../core/types.js';
import { clamp, debounce, isRecord, splitList, splitPairs } from '../../core/util.js';
import { ApiError, api } from '../api.js';
import { h, replace } from '../dom.js';
import { math } from '../math-dom.js';
import { contextFor } from '../../core/session.js';
import { store } from '../store.js';
import { dialog, glyph, iconButton, saveBlob, toast } from '../ui.js';
import type { NavRequest, WorkspaceView } from '../shell.js';
import { savedList } from './saved.js';
import { missingName, paintSliderBox, type Param } from './sliders.js';
import { exportControls } from './spatial-export.js';

interface LayerUI extends LayerSpec { color: string; data?: string; fitModel?: string; info?: string }
const is3d = (e: Entry): boolean => isRecord(e.spec) && e.spec.mode === '3d';
interface Marker { x: number; y: number; label: string }
interface Tangent { slope: number; intercept: number; x: number; y: number; latex?: string; equation?: string }

const LAYER_TYPES: Array<[string, string]> = [
  ['auto', 'y = f(x), equation or inequality'], ['parametric', 'Parametric (x(t), y(t))'], ['polar', 'Polar r(t)'], ['sequence', 'Sequence a(n)'],
  ['vectorfield', 'Vector field'], ['scatter', 'Data points (with fit)'], ['histogram', 'Histogram'],
];
const FITS = ['', 'linear', 'quadratic', 'cubic', 'quartic', 'exponential', 'logarithmic', 'power', 'logistic'];
const START: Array<Partial<LayerUI>> = [{ type: 'auto', expr: 'sin(x)' }];
const EXAMPLES: Array<{ title: string; layers: Array<Partial<LayerUI>>; view?: View }> = [
  { title: 'sin(x) and cos(x)', layers: [{ type: 'auto', expr: 'sin(x)' }, { type: 'auto', expr: 'cos(x)' }], view: PRESETS.trig },
  { title: 'Parabola and line', layers: [{ type: 'auto', expr: 'x^2 - 2' }, { type: 'auto', expr: '0.5*x + 1' }] },
  { title: 'Circle', layers: [{ type: 'auto', expr: 'x^2 + y^2 = 9' }] },
  { title: 'Slider: a·sin(b·x)', layers: [{ type: 'auto', expr: 'a*sin(b*x)' }] },
  { title: 'Inequality', layers: [{ type: 'auto', expr: 'y > x^2 - 4' }, { type: 'auto', expr: 'y < 4 - x' }] },
  { title: 'Cardioid (polar)', layers: [{ type: 'polar', r: '1 + cos(t)', tmin: '0', tmax: '2*pi' }], view: { xmin: -3, xmax: 3, ymin: -2.2, ymax: 2.2 } },
  { title: 'Lissajous (parametric)', layers: [{ type: 'parametric', x: 'sin(3*t)', y: 'sin(2*t)', tmin: '0', tmax: '2*pi' }], view: { xmin: -1.6, xmax: 1.6, ymin: -1.2, ymax: 1.2 } },
  { title: 'Vector field', layers: [{ type: 'vectorfield', fx: 'y', fy: '-x' }] },
];

export function createGraphView(): WorkspaceView {
  let layers: LayerUI[] = [];
  let params: Param[] = [];
  let view: View = { ...PRESETS.standard };
  let result: GraphResult | null = null;
  let markers: Marker[] = [];
  let tangent: Tangent | null = null;
  let hover: { px: number; py: number } | null = null;
  let pinned: Marker | null = null;
  let inflight: AbortController | null = null;
  let renderSeq = 0;
  let dismissedParams = new Set<string>();

  const canvas = h('canvas', { tabindex: '0', role: 'img', 'aria-label': 'Graph. Use the arrow keys to move, plus and minus to zoom, and 0 to reset the view.' });
  const readout = h('div', { class: 'plot-readout', hidden: true });
  const note = h('div', { class: 'plot-note', hidden: true });
  const wrap = h('div', { class: 'plot-wrap' }, canvas, readout, note);
  const layersBox = h('div', { class: 'graph-layers', style: { display: 'grid', gap: '.7rem' } });
  const slidersBox = h('div', { class: 'sliders' });
  const analysisOut = h('div', { class: 'results' });
  const live = h('div', { class: 'visually-hidden', 'aria-live': 'polite' });
  const valuesBox = h('details', { class: 'chart-data' });
  const viewInputs = { xmin: h('input', { type: 'text', 'aria-label': 'x minimum' }), xmax: h('input', { type: 'text', 'aria-label': 'x maximum' }), ymin: h('input', { type: 'text', 'aria-label': 'y minimum' }), ymax: h('input', { type: 'text', 'aria-label': 'y maximum' }) };

  // ------------------------------------------------------------------------------------------------ layer model
  const addLayer = (init: Partial<LayerUI> = {}): LayerUI => {
    const l: LayerUI = { id: 'L' + newEntryId().slice(0, 6), type: 'auto', color: paletteColor(layers.length), visible: true, ...init };
    layers.push(l);
    return l;
  };

  const specLayers = (): LayerSpec[] => layers.map((l) => {
    const base: LayerSpec = { id: l.id, type: l.type, visible: l.visible !== false };
    switch (l.type) {
      case 'parametric': return { ...base, x: l.x as string, y: l.y as string, tmin: l.tmin || '0', tmax: l.tmax || '2*pi' };
      case 'polar': return { ...base, r: l.r, tmin: l.tmin || '0', tmax: l.tmax || '2*pi' };
      case 'sequence': return { ...base, expr: l.expr, nmin: l.nmin || '1', nmax: l.nmax || '20' };
      case 'vectorfield': return { ...base, fx: l.fx, fy: l.fy };
      case 'scatter': {
        const pairs = splitPairs(l.data ?? '').filter((p) => p.length >= 2);
        return { ...base, x: pairs.map((p) => p[0]), y: pairs.map((p) => p[1]), fit: l.fitModel || undefined, label: l.label || 'data' };
      }
      case 'histogram': return { ...base, values: splitList(l.data ?? ''), bins: l.bins || undefined };
      default: return { ...base, expr: l.expr };
    }
  });

  const hasContent = (l: LayerUI): boolean => {
    switch (l.type) {
      case 'parametric': return !!(l.x && l.y);
      case 'polar': return !!l.r;
      case 'vectorfield': return !!(l.fx && l.fy);
      case 'scatter': case 'histogram': return !!(l.data && l.data.trim());
      default: return !!(l.expr && l.expr.trim());
    }
  };

  const paramValues = (): Record<string, number> => Object.fromEntries(params.map((p) => [p.name, p.value]));

  // ------------------------------------------------------------------------------------------------ rendering requests
  const requestRender = async (): Promise<void> => {
    const seq = ++renderSeq;
    inflight?.abort();
    const active = layers.filter(hasContent);
    if (!active.length) { result = null; draw(); paintLayerInfo(); return; }
    const ctl = new AbortController();
    inflight = ctl;
    const rect = canvas.getBoundingClientRect();
    const spec = { viewport: view, width: clamp(Math.round(rect.width) || 800, 100, 4000), height: clamp(Math.round(rect.height) || 500, 100, 4000), params: paramValues(), layers: specLayers().filter((_, i) => hasContent(layers[i])) };
    try {
      const res = await api.graph('render', spec, store.settings, contextFor(store.entries, ''), ctl.signal);
      if (seq !== renderSeq) return;
      if (!res.ok) { note.hidden = false; note.textContent = res.error?.message ?? 'The graph could not be drawn.'; result = null; draw(); return; }
      note.hidden = true;
      result = res;
      paintLayerInfo();
      draw();
      void autoSliders(res);
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return;
      note.hidden = false;
      note.textContent = e instanceof ApiError ? e.message : 'The graph could not be drawn.';
    }
  };
  const scheduleRender = debounce(() => void requestRender(), 140);

  /** A free letter in an expression ("a" in a*sin(x)) becomes a slider, the way graphing tools do it. */
  const autoSliders = async (res: GraphResult): Promise<void> => {
    let added = false;
    for (const lr of res.layers) {
      if (lr.ok || !lr.error) continue;
      const name = missingName(lr.error.message);
      if (!name) continue;
      if (params.some((p) => p.name === name) || dismissedParams.has(name)) continue;
      params.push({ name, value: 1, min: -10, max: 10, step: 0.1 });
      added = true;
    }
    if (added) { paintSliders(); await requestRender(); }
  };

  // ------------------------------------------------------------------------------------------------ drawing
  const css = (name: string): string => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  /** The colours a picture of the graph is drawn with. The screen uses the theme; the worksheet picture has no background and neutral ink. */
  interface Ink { bg: string | null; grid: string; axis: string; text: string; accent: string; halo: string }
  /** One drawing pass: which ink, whether the pointer's readout is drawn, and a dash pattern per layer (the export separates curves without colour). */
  interface Pass { ink: Ink; hover: boolean; dashes: Map<string, number[]>; fontPx: number }
  const screenInk = (): Ink => ({ bg: css('--plot-bg') || '#fff', grid: css('--plot-grid') || '#ccc', axis: css('--plot-axis') || '#333', text: css('--text') || '#000',
    accent: css('--accent-ink') || '#b89b00', halo: css('--plot-bg') || '#fff' });
  // A picture with no background is read on a white page, a sepia one and a dark one, so its ink is a middle grey that stays legible on all of them.
  const EXPORT_INK: Ink = { bg: null, grid: 'rgba(118,128,142,.30)', axis: '#76808e', text: '#76808e', accent: '#a07f00', halo: 'rgba(255,255,255,0)' };

  const draw = (): void => {
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(canvas.clientWidth));
    const hgt = Math.max(1, Math.round(canvas.clientHeight));
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(hgt * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(hgt * dpr); }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const live = paint(ctx, w, hgt, { ink: screenInk(), hover: true, dashes: new Map(), fontPx: 12 });
    canvas.setAttribute('aria-label', live.length ? `Graph of ${live.join('; ')}. Use the arrow keys to move, plus and minus to zoom, and 0 to reset the view.` : 'Empty graph. Enter an expression on the left.');
    paintViewInputs();
    paintValues();
  };

  /** Draws the graph (grid, axes, layers, marks) at a logical size w x hgt. Used by the screen and by the worksheet picture, so they cannot differ. */
  const paint = (ctx: CanvasRenderingContext2D, w: number, hgt: number, pass: Pass): string[] => {
    const { ink } = pass;
    const gridColor = ink.grid;
    const axisColor = ink.axis;
    const text = ink.text;
    const accent = ink.accent;
    if (ink.bg) { ctx.fillStyle = ink.bg; ctx.fillRect(0, 0, w, hgt); } else ctx.clearRect(0, 0, w, hgt);
    const m = mapper(view, w, hgt);
    ctx.font = `${pass.fontPx}px system-ui, sans-serif`;

    // grid, axes, labels
    const xt = ticks(view.xmin, view.xmax, Math.max(4, w / 90));
    const yt = ticks(view.ymin, view.ymax, Math.max(3, hgt / 70));
    ctx.lineWidth = 1;
    ctx.strokeStyle = gridColor;
    ctx.beginPath();
    for (const v of xt.values) { const x = Math.round(m.px(v)) + .5; ctx.moveTo(x, 0); ctx.lineTo(x, hgt); }
    for (const v of yt.values) { const y = Math.round(m.py(v)) + .5; ctx.moveTo(0, y); ctx.lineTo(w, y); }
    ctx.stroke();
    const ax = clamp(m.px(0), 0, w);
    const ay = clamp(m.py(0), 0, hgt);
    ctx.strokeStyle = axisColor;
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(0, Math.round(ay) + .5); ctx.lineTo(w, Math.round(ay) + .5);
    ctx.moveTo(Math.round(ax) + .5, 0); ctx.lineTo(Math.round(ax) + .5, hgt);
    ctx.stroke();
    ctx.fillStyle = text;
    ctx.globalAlpha = .85;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    const labelY = ay > hgt - 20 ? ay - 18 : ay + 4;
    for (const v of xt.values) if (v !== 0) ctx.fillText(formatTick(v, xt.step), clamp(m.px(v), 16, w - 16), labelY);
    ctx.textAlign = ax > w - 44 ? 'right' : 'left';
    ctx.textBaseline = 'middle';
    const labelX = ax > w - 44 ? ax - 6 : ax + 6;
    for (const v of yt.values) if (v !== 0) ctx.fillText(formatTick(v, yt.step), labelX, clamp(m.py(v), 8, hgt - 8));
    ctx.globalAlpha = 1;

    // layers
    const live: string[] = [];
    if (result) {
      result.layers.forEach((lr) => {
        const ui = layers.find((l) => l.id === lr.id);
        if (!ui || !lr.ok || lr.type === 'hidden') return;
        drawLayer(ctx, m, lr, ui.color, w, hgt, pass);
        if (lr.label) live.push(lr.label);
      });
    }
    if (tangent) {
      ctx.strokeStyle = accent;
      ctx.setLineDash([6, 4]);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(m.px(view.xmin), m.py(tangent.slope * view.xmin + tangent.intercept));
      ctx.lineTo(m.px(view.xmax), m.py(tangent.slope * view.xmax + tangent.intercept));
      ctx.stroke();
      ctx.setLineDash([]);
    }
    for (const mk of [...markers, ...(pinned ? [pinned] : [])]) {
      const x = m.px(mk.x);
      const y = m.py(mk.y);
      if (x < -20 || x > w + 20 || y < -20 || y > hgt + 20) continue;
      ctx.strokeStyle = accent;
      ctx.fillStyle = ink.bg ?? 'rgba(0,0,0,0)';
      ctx.lineWidth = 2.4;
      ctx.beginPath(); ctx.arc(x, y, 5.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.fillStyle = text;
      ctx.font = `600 ${pass.fontPx}px system-ui, sans-serif`;
      ctx.textAlign = x > w - 130 ? 'right' : 'left';
      ctx.textBaseline = 'bottom';
      ctx.fillText(mk.label, x + (x > w - 130 ? -9 : 9), y - 7);
    }
    if (pass.hover && hover) drawHover(ctx, m, w, hgt);
    return live;
  };

  const strokeLines = (ctx: CanvasRenderingContext2D, m: Mapper, lines: Pt[][], color: string, dash: number[] = [], lw = 2.4): void => {
    ctx.strokeStyle = color;
    ctx.lineWidth = lw;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.setLineDash(dash);
    ctx.beginPath();
    for (const seg of lines) {
      seg.forEach((p, i) => { if (i === 0) ctx.moveTo(m.px(p[0]), m.py(p[1])); else ctx.lineTo(m.px(p[0]), m.py(p[1])); });
    }
    ctx.stroke();
    ctx.setLineDash([]);
  };

  const drawLayer = (ctx: CanvasRenderingContext2D, m: Mapper, lr: LayerResult, color: string, w: number, hgt: number, pass: Pass): void => {
    const dash = pass.dashes.get(lr.id) ?? [];
    switch (lr.type) {
      case 'function': case 'parametric': case 'polar':
        for (const a of lr.asymptotes ?? []) { ctx.strokeStyle = color; ctx.globalAlpha = .35; ctx.setLineDash([4, 5]); ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(m.px(a), 0); ctx.lineTo(m.px(a), hgt); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1; }
        strokeLines(ctx, m, lr.segments ?? [], color, dash);
        break;
      case 'implicit': strokeLines(ctx, m, lr.polylines ?? [], color, dash); break;
      case 'vline': ctx.strokeStyle = color; ctx.lineWidth = 2.4; ctx.beginPath(); ctx.moveTo(m.px(lr.x ?? 0), 0); ctx.lineTo(m.px(lr.x ?? 0), hgt); ctx.stroke(); break;
      case 'inequality': {
        ctx.fillStyle = color;
        ctx.globalAlpha = .2;
        for (const run of lr.region?.runs ?? []) {
          const [y0, y1, x0, x1] = run;
          ctx.fillRect(m.px(x0), m.py(y1), Math.max(1, m.px(x1) - m.px(x0)), Math.max(1, m.py(y0) - m.py(y1)) + .5);
        }
        ctx.globalAlpha = 1;
        strokeLines(ctx, m, lr.boundary ?? [], color, lr.strict ? [8, 5] : [], 2);
        break;
      }
      case 'sequence': case 'scatter': {
        if (lr.fit) strokeLines(ctx, m, lr.fit.segments, color, [7, 5], 2.2);
        ctx.fillStyle = color;
        ctx.strokeStyle = pass.ink.halo;
        ctx.lineWidth = 1.5;
        for (const p of lr.points ?? []) { ctx.beginPath(); ctx.arc(m.px(p[0]), m.py(p[1]), 4.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke(); }
        break;
      }
      case 'histogram': {
        const maxCount = Math.max(1, ...(lr.bars ?? []).map((b) => b.count));
        const base = clamp(m.py(0), 0, hgt);
        ctx.fillStyle = color;
        for (const b of lr.bars ?? []) {
          const x0 = m.px(b.x0);
          const x1 = m.px(b.x1);
          const top = base - (b.count / maxCount) * (hgt * 0.7);
          ctx.globalAlpha = .55;
          ctx.fillRect(x0, top, Math.max(1, x1 - x0 - 1), base - top);
          ctx.globalAlpha = 1;
          ctx.strokeStyle = color;
          ctx.strokeRect(x0 + .5, top + .5, Math.max(1, x1 - x0 - 2), base - top);
        }
        break;
      }
      case 'vectorfield': {
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = 1.5;
        for (const a of lr.arrows ?? []) {
          const [x, y, dx, dy] = a;
          const x0 = m.px(x - dx / 2); const y0 = m.py(y - dy / 2); const x1 = m.px(x + dx / 2); const y1 = m.py(y + dy / 2);
          ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
          const ang = Math.atan2(y1 - y0, x1 - x0);
          ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x1 - 6 * Math.cos(ang - .4), y1 - 6 * Math.sin(ang - .4)); ctx.lineTo(x1 - 6 * Math.cos(ang + .4), y1 - 6 * Math.sin(ang + .4)); ctx.closePath(); ctx.fill();
        }
        break;
      }
      default: break;
    }
    void w;
  };

  const traceTargets = (): Array<{ lr: LayerResult; color: string }> => (result?.layers ?? []).filter((lr) => lr.ok && (lr.type === 'function' || lr.type === 'parametric' || lr.type === 'polar' || lr.type === 'implicit' || lr.type === 'scatter' || lr.type === 'sequence'))
    .map((lr) => ({ lr, color: layers.find((l) => l.id === lr.id)?.color ?? '#888' }));

  const tracePoint = (m: Mapper, px: number, py: number): { pt: Pt; lr: LayerResult; color: string } | null => {
    let best: { pt: Pt; lr: LayerResult; color: string; d: number } | null = null;
    for (const { lr, color } of traceTargets()) {
      let pt: Pt | null = null;
      let d = Infinity;
      if (lr.type === 'function' && lr.segments) {
        const y = traceAt(lr.segments, m.wx(px));
        if (y) { pt = y; d = Math.abs(m.py(y[1]) - py); }
      }
      if (!pt || d > 40) {
        const lines: Pt[][] = lr.segments ?? lr.polylines ?? (lr.points ? [lr.points] : []);
        const n = nearest(lines, m, px, py);
        if (n && n.dist < d) { pt = n.pt; d = n.dist; }
      }
      if (pt && (!best || d < best.d)) best = { pt, lr, color, d };
    }
    return best && best.d < 36 ? best : null;
  };

  const drawHover = (ctx: CanvasRenderingContext2D, m: Mapper, w: number, hgt: number): void => {
    if (!hover) return;
    const tp = tracePoint(m, hover.px, hover.py);
    if (tp) {
      ctx.fillStyle = tp.color;
      ctx.strokeStyle = css('--plot-bg') || '#fff';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(m.px(tp.pt[0]), m.py(tp.pt[1]), 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      readout.hidden = false;
      readout.textContent = `${tp.lr.label ?? ''}   x = ${formatNumber(tp.pt[0], 6)}, y = ${formatNumber(tp.pt[1], 6)}`;
    } else {
      readout.hidden = false;
      readout.textContent = `x = ${formatNumber(m.wx(hover.px), 5)}, y = ${formatNumber(m.wy(hover.py), 5)}`;
    }
    void w; void hgt;
  };

  // ------------------------------------------------------------------------------------------------ pointer interaction
  const pointers = new Map<number, { x: number; y: number }>();
  let dragStart: { x: number; y: number; view: View } | null = null;
  let pinch: { dist: number; view: View; cx: number; cy: number } | null = null;
  let moved = false;

  const rectOf = (): DOMRect => canvas.getBoundingClientRect();
  canvas.addEventListener('pointerdown', (ev) => {
    canvas.setPointerCapture(ev.pointerId);
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    moved = false;
    if (pointers.size === 1) dragStart = { x: ev.clientX, y: ev.clientY, view: { ...view } };
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const r = rectOf();
      pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y), view: { ...view }, cx: ((a.x + b.x) / 2 - r.left) / r.width, cy: ((a.y + b.y) / 2 - r.top) / r.height };
      dragStart = null;
    }
    canvas.classList.add('dragging');
  });
  canvas.addEventListener('pointermove', (ev) => {
    const r = rectOf();
    if (pointers.has(ev.pointerId)) pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pinch && pointers.size >= 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d > 0) { view = zoomAt(pinch.view, pinch.cx, pinch.cy, pinch.dist / d); moved = true; draw(); scheduleRender(); }
      return;
    }
    if (dragStart && pointers.size === 1) {
      const dx = ev.clientX - dragStart.x;
      const dy = ev.clientY - dragStart.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      view = pan(dragStart.view, dx / r.width, dy / r.height);
      hover = null;
      draw();
      scheduleRender();
      return;
    }
    hover = { px: ev.clientX - r.left, py: ev.clientY - r.top };
    draw();
  });
  const endPointer = (ev: PointerEvent): void => {
    const wasDrag = moved;
    pointers.delete(ev.pointerId);
    if (pointers.size < 2) pinch = null;
    if (pointers.size === 0) {
      dragStart = null;
      canvas.classList.remove('dragging');
      if (!wasDrag && ev.type === 'pointerup') pinHere(ev);
    } else if (pointers.size === 1) {
      const [p] = [...pointers.values()];
      dragStart = { x: p.x, y: p.y, view: { ...view } };
    }
  };
  canvas.addEventListener('pointerup', endPointer);
  canvas.addEventListener('pointercancel', endPointer);
  canvas.addEventListener('pointerleave', () => { if (!pointers.size) { hover = null; readout.hidden = true; draw(); } });
  canvas.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const r = rectOf();
    const factor = Math.exp(clamp(ev.deltaY, -240, 240) * 0.0016);
    view = zoomAt(view, (ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height, factor);
    draw();
    scheduleRender();
  }, { passive: false });
  canvas.addEventListener('dblclick', (ev) => {
    const r = rectOf();
    view = zoomAt(view, (ev.clientX - r.left) / r.width, (ev.clientY - r.top) / r.height, 0.5);
    draw();
    scheduleRender();
  });
  canvas.addEventListener('keydown', (ev) => {
    const step = ev.shiftKey ? 0.25 : 0.08;
    let handled = true;
    if (ev.key === 'ArrowLeft') view = pan(view, step, 0);
    else if (ev.key === 'ArrowRight') view = pan(view, -step, 0);
    else if (ev.key === 'ArrowUp') view = pan(view, 0, step);
    else if (ev.key === 'ArrowDown') view = pan(view, 0, -step);
    else if (ev.key === '+' || ev.key === '=') view = zoomAt(view, .5, .5, 0.8);
    else if (ev.key === '-' || ev.key === '_') view = zoomAt(view, .5, .5, 1.25);
    else if (ev.key === '0') view = { ...PRESETS.standard };
    else handled = false;
    if (handled) { ev.preventDefault(); draw(); scheduleRender(); }
  });

  const pinHere = (ev: PointerEvent): void => {
    const r = rectOf();
    const m = mapper(view, r.width, r.height);
    const px = ev.clientX - r.left;
    const py = ev.clientY - r.top;
    const tp = tracePoint(m, px, py);
    const pt: Pt = tp ? tp.pt : [m.wx(px), m.wy(py)];
    pinned = { x: pt[0], y: pt[1], label: `(${formatNumber(pt[0], 5)}, ${formatNumber(pt[1], 5)})` };
    live.textContent = `Point ${pinned.label}`;
    draw();
  };

  // ------------------------------------------------------------------------------------------------ left column
  const field = (label: string, input: HTMLElement, cls = ''): HTMLElement => h('label', { class: `field ${cls}` }, h('span', { class: 'label', text: label }), input);
  const textInput = (value: string | undefined, onInput: (v: string) => void, label: string, placeholder = '', mono = true): HTMLInputElement => {
    const i = h('input', { type: 'text', value: value ?? '', placeholder, 'aria-label': label, spellcheck: 'false', autocomplete: 'off', class: mono ? 'mono' : '' });
    i.addEventListener('input', () => onInput(i.value));
    return i;
  };

  const layerCard = (l: LayerUI, index: number): HTMLElement => {
    const changed = (): void => scheduleRender();
    const typeSel = h('select', { 'aria-label': 'Kind of layer' }, LAYER_TYPES.map(([v, t]) => h('option', { value: v, text: t, selected: l.type === v })));
    typeSel.addEventListener('change', () => { l.type = typeSel.value; paintLayers(); changed(); });
    const body: HTMLElement[] = [];
    switch (l.type) {
      case 'parametric':
        body.push(h('div', { class: 'sub' }, field('x(t) =', textInput(l.x as string, (v) => { l.x = v; changed(); }, 'x of t', 'cos(t)')), field('y(t) =', textInput(l.y as string, (v) => { l.y = v; changed(); }, 'y of t', 'sin(t)'))),
          h('div', { class: 'sub' }, field('t from', textInput(l.tmin, (v) => { l.tmin = v; changed(); }, 't minimum', '0')), field('t to', textInput(l.tmax, (v) => { l.tmax = v; changed(); }, 't maximum', '2*pi'))));
        break;
      case 'polar':
        body.push(field('r(t) =', textInput(l.r, (v) => { l.r = v; changed(); }, 'r of t', '1 + cos(t)')),
          h('div', { class: 'sub' }, field('t from', textInput(l.tmin, (v) => { l.tmin = v; changed(); }, 't minimum', '0')), field('t to', textInput(l.tmax, (v) => { l.tmax = v; changed(); }, 't maximum', '2*pi'))));
        break;
      case 'sequence':
        body.push(field('a(n) =', textInput(l.expr, (v) => { l.expr = v; changed(); }, 'sequence term', 'n^2')),
          h('div', { class: 'sub' }, field('n from', textInput(l.nmin, (v) => { l.nmin = v; changed(); }, 'first n', '1')), field('n to', textInput(l.nmax, (v) => { l.nmax = v; changed(); }, 'last n', '20'))));
        break;
      case 'vectorfield':
        body.push(h('div', { class: 'sub' }, field('dx = f(x, y)', textInput(l.fx, (v) => { l.fx = v; changed(); }, 'x component', 'y')), field('dy = g(x, y)', textInput(l.fy, (v) => { l.fy = v; changed(); }, 'y component', '-x'))));
        break;
      case 'scatter': {
        const ta = h('textarea', { rows: '5', class: 'mono', 'aria-label': 'Data points, one x y pair per line', placeholder: '1 2.1\n2 3.9\n3 6.2\n4 7.8', spellcheck: 'false' });
        ta.value = l.data ?? '';
        ta.addEventListener('input', () => { l.data = ta.value; changed(); });
        const fit = h('select', { 'aria-label': 'Regression model' }, FITS.map((f) => h('option', { value: f, text: f ? `Fit: ${f}` : 'No fit', selected: (l.fitModel ?? '') === f })));
        fit.addEventListener('change', () => { l.fitModel = fit.value; changed(); });
        body.push(field('Data (x y per line)', ta), fit);
        break;
      }
      case 'histogram': {
        const ta = h('textarea', { rows: '4', class: 'mono', 'aria-label': 'Values', placeholder: '1 2 2 3 3 3 4 4 5', spellcheck: 'false' });
        ta.value = l.data ?? '';
        ta.addEventListener('input', () => { l.data = ta.value; changed(); });
        body.push(field('Values', ta), field('Bins (optional)', textInput(l.bins, (v) => { l.bins = v; changed(); }, 'Number of bins', 'automatic')));
        break;
      }
      default: break;
    }
    const top = h('div', { class: 'top' },
      h('input', { type: 'color', value: l.color, 'aria-label': 'Colour of this layer', on: { input: (ev: Event) => { l.color = (ev.target as HTMLInputElement).value; card.style.setProperty('--lc', l.color); draw(); } } }),
      l.type === 'auto' ? textInput(l.expr, (v) => { l.expr = v; changed(); }, `Expression ${index + 1}`, 'y = x^2, x^2 + y^2 = 4 or y > x') : h('span', { class: 'grow muted', text: LAYER_TYPES.find((t) => t[0] === l.type)?.[1] ?? l.type }),
      iconButton(l.visible === false ? 'eyeoff' : 'eye', l.visible === false ? 'Show this layer' : 'Hide this layer', () => { l.visible = l.visible === false; paintLayers(); changed(); }, 'tiny'),
      iconButton('trash', 'Remove this layer', () => { layers = layers.filter((x) => x !== l); paintLayers(); changed(); }, 'tiny'));
    const card = h('div', { class: 'layer', data: { layer: l.id } }, top, typeSel, ...body, h('div', { class: 'err', hidden: true, role: 'alert' }), h('div', { class: 'info', hidden: true }));
    card.style.setProperty('--lc', l.color);
    return card;
  };

  const paintLayers = (): void => {
    replace(layersBox, layers.map(layerCard));
    paintLayerInfo();
  };

  const paintLayerInfo = (): void => {
    for (const l of layers) {
      const card = layersBox.querySelector<HTMLElement>(`[data-layer="${l.id}"]`);
      if (!card) continue;
      const err = card.querySelector<HTMLElement>('.err');
      const info = card.querySelector<HTMLElement>('.info');
      const lr = result?.layers.find((r) => r.id === l.id);
      if (err) { const bad = lr && !lr.ok && lr.error; err.hidden = !bad; err.textContent = bad ? lr.error!.message + (lr.error!.hint ? ' ' + lr.error!.hint : '') : ''; }
      if (info) {
        const bits: string[] = [];
        if (lr?.ok && lr.type === 'function' && lr.yIntercept !== undefined && lr.yIntercept !== null) bits.push(`y-intercept ${formatNumber(lr.yIntercept, 6)}`);
        if (lr?.ok && lr.fit) bits.push(`${lr.fit.equation}   R² = ${formatNumber(lr.fit.r2, 6)}   (${lr.fit.method})`);
        if (lr?.ok && lr.type === 'histogram') bits.push(`${lr.n} values`);
        info.hidden = bits.length === 0;
        info.textContent = bits.join(' · ');
      }
    }
  };

  const paintSliders = (): void => paintSliderBox(slidersBox, params, {
    change: () => scheduleRender(),
    remove: (p) => { params = params.filter((x) => x !== p); dismissedParams.add(p.name); paintSliders(); scheduleRender(); },
    repaint: () => paintSliders(),
  });

  // ------------------------------------------------------------------------------------------------ analysis
  const analysisLayerSel = h('select', { 'aria-label': 'Layer to analyse' });
  const analysisLayer2Sel = h('select', { 'aria-label': 'Second layer for intersections' });
  const aInput = h('input', { type: 'text', 'aria-label': 'Interval start (a)', placeholder: 'a (default: left edge)' });
  const bInput = h('input', { type: 'text', 'aria-label': 'Interval end (b)', placeholder: 'b (default: right edge)' });
  const xInput = h('input', { type: 'text', 'aria-label': 'x value', placeholder: 'x = …' });
  const funcLayers = (): LayerUI[] => layers.filter((l) => l.type === 'auto' && hasContent(l) && result?.layers.find((r) => r.id === l.id)?.type === 'function');

  const paintAnalysisSelects = (): void => {
    const fl = funcLayers();
    const ids = fl.map((l) => l.id);
    const c1 = analysisLayerSel.value;
    const c2 = analysisLayer2Sel.value;
    const opts = (): HTMLElement[] => fl.map((l) => h('option', { value: l.id, text: l.expr ?? '' }));
    replace(analysisLayerSel, opts());
    replace(analysisLayer2Sel, opts());
    const first = ids.includes(c1) ? c1 : ids[0] ?? '';
    analysisLayerSel.value = first;
    analysisLayer2Sel.value = ids.includes(c2) && c2 !== first ? c2 : ids.find((i) => i !== first) ?? first;
  };

  const runAnalysis = async (kind: string): Promise<void> => {
    const fl = funcLayers();
    if (!fl.length) { replace(analysisOut, h('div', { class: 'note-line', text: 'Add a function y = f(x) first.' })); return; }
    const layer = analysisLayerSel.value || fl[0].id;
    const spec: Record<string, unknown> = { kind, viewport: view, params: paramValues(), layers: specLayers().filter((_, i) => hasContent(layers[i])), layer };
    if (aInput.value.trim()) spec.a = aInput.value.trim();
    if (bInput.value.trim()) spec.b = bInput.value.trim();
    if (kind === 'intersection') spec.layer2 = analysisLayer2Sel.value || fl[1]?.id;
    if (kind === 'value' || kind === 'tangent') { if (!xInput.value.trim()) { replace(analysisOut, h('div', { class: 'note-line', text: 'Enter an x value first.' })); return; } spec.x = xInput.value.trim(); }
    replace(analysisOut, h('div', { class: 'muted', text: 'Working…' }));
    try {
      const r = await api.graph('analyze', spec, store.settings, contextFor(store.entries, '')) as unknown as Record<string, unknown> & { ok: boolean; error?: { message: string; hint?: string } };
      if (!r.ok) { replace(analysisOut, h('div', { class: 'note-line error', text: (r.error?.message ?? 'The analysis failed.') + (r.error?.hint ? ' ' + r.error.hint : '') })); return; }
      showAnalysis(kind, r);
    } catch (e) { replace(analysisOut, h('div', { class: 'note-line error', text: e instanceof ApiError ? e.message : 'The analysis failed.' })); }
  };

  const centreOn = (x: number, y: number): void => {
    const w = view.xmax - view.xmin; const hh = view.ymax - view.ymin;
    view = sane({ xmin: x - w / 2, xmax: x + w / 2, ymin: y - hh / 2, ymax: y + hh / 2 });
    draw(); scheduleRender();
  };

  const showAnalysis = (kind: string, r: Record<string, unknown>): void => {
    tangent = null;
    markers = [];
    const rows: HTMLElement[] = [];
    const method = typeof r.method === 'string' ? r.method : '';
    if (kind === 'roots' || kind === 'extrema' || kind === 'intersection') {
      const tiny = 1e-10 * Math.max(1, view.xmax - view.xmin, view.ymax - view.ymin);
      const snap = (v: number): number => (Math.abs(v) < tiny ? 0 : v);
      const pts = ((r.points as Array<{ x: number; y: number; kind?: string }>) ?? []).map((p) => ({ ...p, x: snap(p.x), y: snap(p.y) }));
      const word = kind === 'roots' ? 'Root' : kind === 'extrema' ? 'Extremum' : 'Intersection';
      for (const p of pts) {
        const label = kind === 'extrema' ? `${p.kind ?? 'extremum'}  (${formatNumber(p.x, 7)}, ${formatNumber(p.y, 7)})` : `(${formatNumber(p.x, 7)}, ${formatNumber(p.y, 7)})`;
        markers.push({ x: p.x, y: p.y, label: kind === 'roots' ? `x = ${formatNumber(p.x, 6)}` : label });
        rows.push(h('button', { class: 'pt', type: 'button', text: label, on: { click: () => centreOn(p.x, p.y) } }));
      }
      if (!pts.length) rows.push(h('div', { class: 'note-line', text: `No ${word.toLowerCase()}s were found between x = ${formatNumber(view.xmin, 5)} and ${formatNumber(view.xmax, 5)}. Widen the interval or the view.` }));
    } else if (kind === 'integral') {
      rows.push(h('div', { class: 'kv key' }, h('div', { class: 'k', text: `Integral from ${formatNumber(Number(r.a), 6)} to ${formatNumber(Number(r.b), 6)}` }), h('div', { class: 'v', text: formatNumber(Number(r.value), 10) }),
        h('div', { class: 'x', text: `estimated error ${String(r.error)}` })));
    } else if (kind === 'value') {
      rows.push(h('div', { class: 'kv key' }, h('div', { class: 'k', text: `f(${formatNumber(Number(r.x), 8)})` }), h('div', { class: 'v', text: r.y === null ? 'undefined here' : formatNumber(Number(r.y), 10) })));
      if (typeof r.y === 'number') markers.push({ x: Number(r.x), y: r.y, label: `(${formatNumber(Number(r.x), 5)}, ${formatNumber(r.y, 5)})` });
    } else if (kind === 'tangent') {
      const ex = isRecord(r.exact) ? r.exact : {};
      tangent = { slope: Number(r.slope), intercept: Number(r.intercept), x: Number(r.x), y: Number(r.y) };
      markers.push({ x: tangent.x, y: tangent.y, label: `(${formatNumber(tangent.x, 5)}, ${formatNumber(tangent.y, 5)})` });
      rows.push(h('div', { class: 'kv key' }, h('div', { class: 'k', text: 'Tangent line (exact)' }), h('div', { class: 'v' }, typeof ex.latex === 'string' ? math(ex.latex) : h('span', { text: String(ex.equation ?? '') })),
        h('div', { class: 'x', text: `slope ${formatNumber(tangent.slope, 8)}, intercept ${formatNumber(tangent.intercept, 8)}` })));
    }
    if (r.approximate === true && method) rows.push(h('div', { class: 'muted', style: { 'font-size': '.8rem' }, text: `Numerical (approximate): ${method}` }));
    else if (method) rows.push(h('div', { class: 'muted', style: { 'font-size': '.8rem' }, text: `Method: ${method}` }));
    replace(analysisOut, rows);
    draw();
  };

  const analysisBtn = (label: string, kind: string): HTMLElement => h('button', { class: 'btn small', type: 'button', text: label, on: { click: () => void runAnalysis(kind) } });

  // ------------------------------------------------------------------------------------------------ view controls
  const paintViewInputs = (): void => {
    for (const k of ['xmin', 'xmax', 'ymin', 'ymax'] as const) if (document.activeElement !== viewInputs[k]) viewInputs[k].value = formatNumber(view[k], 7);
  };
  for (const k of ['xmin', 'xmax', 'ymin', 'ymax'] as const) {
    viewInputs[k].addEventListener('change', () => {
      const v = Number(viewInputs[k].value);
      if (!Number.isFinite(v)) { paintViewInputs(); return; }
      const next = { ...view, [k]: v };
      if (next.xmin >= next.xmax || next.ymin >= next.ymax) { toast('The minimum must be smaller than the maximum.', 'error'); paintViewInputs(); return; }
      view = sane(next);
      draw(); scheduleRender();
    });
  }

  const fitView = (): void => {
    const ys: number[] = [];
    for (const lr of result?.layers ?? []) {
      if (!lr.ok) continue;
      for (const seg of lr.segments ?? []) for (const p of seg) if (p[0] >= view.xmin && p[0] <= view.xmax && Number.isFinite(p[1])) ys.push(p[1]);
      for (const p of lr.points ?? []) ys.push(p[1]);
    }
    if (ys.length < 2) { toast('There is nothing to fit yet.', 'info'); return; }
    ys.sort((a, b) => a - b);
    const lo = ys[Math.floor(ys.length * 0.02)];
    const hi = ys[Math.ceil(ys.length * 0.98) - 1];
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.12;
    view = sane({ ...view, ymin: lo - pad, ymax: hi + pad });
    draw(); scheduleRender();
  };

  const saveControls = exportControls({
    defaultUnit: 'mm',
    unitHint: 'A graph has no unit of its own: one graph unit is saved as one of these.',
    items: [{ label: 'SDRW drawing', title: 'The graph as a 2D SDRW drawing: axes, grid, and each curve as a polyline, one drawing layer per graph layer', format: 'sdrw', source: '2d' }],
    prepare: () => {
      const active = layers.filter(hasContent);
      if (!active.length || !result) return null;
      const rect = canvas.getBoundingClientRect();
      const spec = { viewport: view, width: clamp(Math.round(rect.width) || 800, 100, 4000), height: clamp(Math.round(rect.height) || 500, 100, 4000), params: paramValues(), layers: specLayers().filter((_, i) => hasContent(layers[i])) };
      return { spec, settings: store.settings, context: contextFor(store.entries, ''), name: 'scical-graph', colors: Object.fromEntries(layers.map((l) => [l.id, l.color])) };
    },
  });

  const exportPng = (): void => {
    canvas.toBlob((blob) => { if (blob) saveBlob(blob, 'scical-graph.png'); else toast('The picture could not be created.', 'error'); }, 'image/png');
  };

  // ------------------------------------------------------------------------------------------------ the worksheet picture
  const DASHES: Array<{ name: 'solid' | 'dash' | 'dot' | 'dashdot'; pattern: number[] }> = [
    { name: 'solid', pattern: [] }, { name: 'dash', pattern: [9, 5] }, { name: 'dot', pattern: [2, 5] }, { name: 'dashdot', pattern: [10, 4, 2, 4] },
  ];
  const EXPORT_WIDTH = 900;
  const MAX_PICTURE_BYTES = 900_000;

  /** The graph as it is on screen, drawn again for a document: transparent, neutral ink, and a line style per curve so it still reads in grayscale. */
  const renderPicture = async (): Promise<GraphFigure | null> => {
    const drawn = (result?.layers ?? []).filter((lr) => lr.ok && lr.type !== 'hidden' && layers.some((l) => l.id === lr.id));
    if (!drawn.length) return null;
    const aspect = clamp((canvas.clientHeight || 500) / (canvas.clientWidth || 800), 0.35, 1.1);
    const w = EXPORT_WIDTH;
    const hgt = Math.round(w * aspect);
    // dashes are given to the curves only (points and bars keep their fill), in drawing order
    const lined = drawn.filter((lr) => lr.type === 'function' || lr.type === 'parametric' || lr.type === 'polar' || lr.type === 'implicit');
    const dashes = new Map<string, number[]>();
    const names = new Map<string, 'solid' | 'dash' | 'dot' | 'dashdot'>();
    lined.forEach((lr, i) => { const d = DASHES[i % DASHES.length]; dashes.set(lr.id, d.pattern); names.set(lr.id, d.name); });
    for (const scale of [2, 1]) {
      const c = document.createElement('canvas');
      c.width = w * scale; c.height = hgt * scale;
      const ctx = c.getContext('2d');
      if (!ctx) return null;
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      paint(ctx, w, hgt, { ink: EXPORT_INK, hover: false, dashes, fontPx: 17 });
      const blob = await new Promise<Blob | null>((ok) => c.toBlob(ok, 'image/png'));
      if (!blob || (blob.size > MAX_PICTURE_BYTES && scale > 1)) continue;
      if (blob.size > MAX_PICTURE_BYTES) return null;
      const bytes = new Uint8Array(await blob.arrayBuffer());
      let bin = '';
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      return { mediaType: 'image/png', data: btoa(bin), width: c.width, height: c.height, transparent: true,
        series: drawn.map((lr) => ({ id: lr.id, color: layers.find((l) => l.id === lr.id)?.color ?? null, dash: names.get(lr.id) ?? 'solid' })) };
    }
    return null;
  };

  const saveToWorksheet = async (): Promise<void> => {
    const exprs = layers.filter(hasContent).map((l) => l.expr ?? l.r ?? (l.x ? `(${l.x}, ${l.y})` : l.fx ? `(${l.fx}, ${l.fy})` : l.type)).join('; ');
    if (!exprs) { toast('Draw something first.', 'info'); return; }
    let figure: GraphFigure | null = null;
    try { figure = await renderPicture(); } catch { figure = null; }       // without a picture the entry still stores the functions
    store.addEntry({ kind: 'graph', workspace: 'graph', title: 'Graph', spec: { layers: layers.map((l) => ({ ...l })), viewport: view, params: params.map((p) => ({ ...p })) } as unknown as Record<string, unknown>,
      summary: { ok: true, headline: `Graph of ${exprs}` }, ok: true, ...(figure ? { figure } : {}) });
    toast(figure ? 'Graph added to the worksheet' : 'Graph added to the worksheet (without its picture)', figure ? 'ok' : 'info', 2200);
  };

  const paintValues = (): void => {
    const first = (result?.layers ?? []).find((lr) => lr.ok && lr.type === 'function' && lr.segments);
    if (!first || !first.segments) { replace(valuesBox); valuesBox.hidden = true; return; }
    valuesBox.hidden = false;
    const rows: HTMLElement[] = [];
    for (let i = 0; i <= 10; i++) {
      const x = view.xmin + ((view.xmax - view.xmin) * i) / 10;
      const p = traceAt(first.segments, x);
      rows.push(h('tr', null, h('td', { class: 'num', text: formatNumber(x, 6) }), h('td', { class: 'num', text: p ? formatNumber(p[1], 6) : 'undefined' })));
    }
    if (valuesBox.open && valuesBox.querySelector('tbody')) { replace(valuesBox.querySelector('tbody') as HTMLElement, rows); return; }
    replace(valuesBox, h('summary', { text: `Table of values for ${first.label ?? 'the first function'}` }),
      h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', null, h('tr', null, h('th', { text: 'x' }), h('th', { text: 'y' }))), h('tbody', null, rows))));
  };

  // ------------------------------------------------------------------------------------------------ assembly
  const setExample = (ex: typeof EXAMPLES[number]): void => {
    layers = []; params = []; markers = []; tangent = null; pinned = null; dismissedParams = new Set();
    for (const l of ex.layers) addLayer(l);
    view = { ...(ex.view ?? PRESETS.standard) };
    paintLayers(); paintSliders(); void requestRender();
  };

  const loadSpec = (spec: Record<string, unknown>): void => {
    const ls = Array.isArray(spec.layers) ? spec.layers as Array<Partial<LayerUI>> : [];
    layers = [];
    ls.forEach((l, i) => addLayer({ ...l, color: l.color ?? paletteColor(i) }));
    const ps = Array.isArray(spec.params) ? spec.params as Param[] : [];
    params = ps.filter((p) => isRecord(p) && typeof p.name === 'string').map((p) => ({ name: p.name, value: Number(p.value), min: Number(p.min), max: Number(p.max), step: Number(p.step) || 0.1 }));
    const v = spec.viewport as View | undefined;
    view = v && Number.isFinite(v.xmin) ? sane(v) : { ...PRESETS.standard };
    markers = []; tangent = null; pinned = null;
    paintLayers(); paintSliders(); void requestRender();
  };

  const el = h('div', { class: 'graph' },
    h('div', { class: 'graph-side' },
      h('section', { class: 'card', 'aria-label': 'Layers' },
        h('div', { class: 'card-head' }, h('h2', { text: 'Graph' }),
          h('div', { class: 'row' }, h('button', { class: 'btn small primary', type: 'button', text: 'Add', on: { click: () => { addLayer({ expr: '' }); paintLayers(); layersBox.querySelector<HTMLInputElement>('.layer:last-child input.mono')?.focus(); } } }),
            h('select', { 'aria-label': 'Add another kind of layer', style: { width: 'auto' }, on: { change: (ev: Event) => { const s = ev.target as HTMLSelectElement; if (s.value) { addLayer({ type: s.value }); paintLayers(); } s.value = ''; } } },
              h('option', { value: '', text: 'More…' }), LAYER_TYPES.slice(1).map(([v, t]) => h('option', { value: v, text: t }))))),
        layersBox),
      h('section', { class: 'card', 'aria-label': 'Sliders' }, h('div', { class: 'card-head' }, h('h3', { text: 'Sliders' })), slidersBox),
      h('section', { class: 'card analysis', 'aria-label': 'Analysis' }, h('div', { class: 'card-head' }, h('h3', { text: 'Analyse' })),
        field('Function', analysisLayerSel), field('Second function (intersections)', analysisLayer2Sel),
        h('div', { class: 'sub', style: { display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '.45rem' } }, aInput, bInput), xInput,
        h('div', { class: 'row' }, analysisBtn('Roots', 'roots'), analysisBtn('Max / min', 'extrema'), analysisBtn('Intersections', 'intersection'), analysisBtn('Integral', 'integral'), analysisBtn('Value at x', 'value'), analysisBtn('Tangent', 'tangent')),
        analysisOut,
        h('p', { class: 'muted', style: { 'font-size': '.8rem', margin: '0' }, text: 'Roots, extrema, intersections and integrals are found numerically (approximate). The tangent line uses the exact derivative.' })),
      h('section', { class: 'card', 'aria-label': 'Examples' }, h('div', { class: 'card-head' }, h('h3', { text: 'Examples' })),
        h('div', { class: 'chips' }, EXAMPLES.map((ex) => h('button', { class: 'chip', type: 'button', text: ex.title, on: { click: () => setExample(ex) } }))))),
    h('div', { class: 'graph-main', style: { display: 'grid', gap: '1rem', 'min-width': '0' } },
      h('section', { class: 'card plot-card', 'aria-label': 'Plot' },
        h('div', { class: 'plot-tools' },
          iconButton('plus', 'Zoom in', () => { view = zoomAt(view, .5, .5, 0.7); draw(); scheduleRender(); }),
          h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Zoom out', title: 'Zoom out', on: { click: () => { view = zoomAt(view, .5, .5, 1.4); draw(); scheduleRender(); } } }, h('span', { text: '−', style: { 'font-size': '1.3rem' } })),
          h('button', { class: 'btn small', type: 'button', text: 'Standard', on: { click: () => { view = { ...PRESETS.standard }; draw(); scheduleRender(); } } }),
          h('button', { class: 'btn small', type: 'button', text: 'Trig', on: { click: () => { view = { ...PRESETS.trig }; draw(); scheduleRender(); } } }),
          h('button', { class: 'btn small', type: 'button', title: 'Same scale on both axes', text: 'Square', on: { click: () => { const r = rectOf(); view = square(view, r.width, r.height); draw(); scheduleRender(); } } }),
          h('button', { class: 'btn small', type: 'button', text: 'Fit', title: 'Fit the height to the curves', on: { click: fitView } }),
          h('button', { class: 'btn small', type: 'button', text: 'Clear marks', on: { click: () => { markers = []; tangent = null; pinned = null; replace(analysisOut); draw(); } } }),
          h('span', { class: 'grow' }),
          h('button', { class: 'btn small', type: 'button', text: 'Save PNG', on: { click: exportPng } }),
          h('button', { class: 'btn small', type: 'button', text: 'Add to worksheet', on: { click: () => void saveToWorksheet() } })),
        saveControls.el,
        wrap,
        h('div', { class: 'viewbox' }, ['xmin', 'xmax', 'ymin', 'ymax'].map((k) => h('label', null, k.replace('min', ' min').replace('max', ' max'), viewInputs[k as keyof typeof viewInputs]))),
        h('p', { class: 'muted', style: { margin: '0', 'font-size': '.82rem' }, text: 'Drag to move · scroll or pinch to zoom · double-click to zoom in · click a curve to mark a point · arrow keys, + and − work when the plot is focused.' }),
        valuesBox, live),
      savedList('Saved in this worksheet', (e) => e.kind === 'graph' && !!e.spec && !is3d(e), (e) => { if (e.spec) loadSpec(e.spec); })));

  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => { draw(); scheduleRender(); }) : null;
  ro?.observe(wrap);
  store.on('prefs', () => draw());
  new MutationObserver(() => draw()).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  store.on('session', () => {
    const last = [...store.entries].reverse().find((e: Entry) => e.kind === 'graph' && e.spec && !is3d(e));
    if (last?.spec) loadSpec(last.spec); else setExample({ title: '', layers: START });
  });

  // initial content
  const last = [...store.entries].reverse().find((e: Entry) => e.kind === 'graph' && e.spec && !is3d(e));
  if (last?.spec) loadSpec(last.spec); else { for (const l of START) addLayer(l); paintLayers(); paintSliders(); }
  paintAnalysisSelects();
  const origRender = requestRender;
  void origRender;
  const refreshSelects = (): void => paintAnalysisSelects();
  const wrapRender = async (): Promise<void> => { await requestRender(); refreshSelects(); };
  void wrapRender;
  setTimeout(() => { void requestRender().then(refreshSelects); }, 0);
  const rerender = debounce(() => refreshSelects(), 200);
  new MutationObserver(() => rerender()).observe(layersBox, { childList: true, subtree: true });
  void glyph;

  return {
    el,
    focus: () => canvas.focus(),
    open: (req: NavRequest) => {
      const pl = req.payload;
      const spec = (isRecord(pl.spec) ? pl.spec : null) as Record<string, unknown> | null;
      if (spec) loadSpec(spec);
      void requestRender().then(refreshSelects);
    },
  };
}
