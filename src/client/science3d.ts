// Scientific representations share the validated camera/projection mathematics of graphing.
// The Canvas2D primitives are deliberately schematic: they do not claim quantum trajectories,
// measured nuclear geometry, molecular bonds, or atomistic reaction dynamics.
import { DEFAULT_CAMERA, cloneCamera, makeProjector, orbit, panBy, zoomBy, type Camera, type V3 } from '../core/scene3d.js';
import { advancePlayback, depthFade, easeInOut, frameBlend, releaseVelocity } from '../core/motion.js';
import { CameraMotion, reducedMotion } from './motion.js';
import { saveBlob } from './ui.js';

export type SciencePrimitive =
  | { kind: 'ball'; p: V3; r: number; color: string; label?: string }
  /** A cylinder from `a` to `b` of radius `r`: a nucleobase, drawn with a shaded body and elliptical end caps that follow the viewing angle. */
  | { kind: 'rod'; a: V3; b: V3; r: number; color: string; label?: string }
  /** `lanes` draws a double or triple bond as parallel strokes (spread sideways on the screen, so they stay separate from every angle);
   *  `color2` colours the second half of the stroke, which is how a bond between two elements shows both. */
  | { kind: 'line'; a: V3; b: V3; color: string; width?: number; color2?: string; lanes?: number };
export interface ScienceScene {
  el: HTMLElement;
  setFrame(frame: number): void;
  destroy(): void;
}
/**
 * How the frames are played.
 *  steps       whole frames, one after the other (a transcription: one nucleotide per step)
 *  continuous  `at(frame)` is called with fractional frames and loops (an atom's electrons keep circling)
 *  blend       two states; playing cross-fades between them
 */
export type SceneMode = 'steps' | 'continuous' | 'blend';
export interface SceneSpec {
  description: string;
  frames?: number;
  extent?: number;
  mode?: SceneMode;
  /** Text drawn on the picture itself (so it is in the saved PNG too), e.g. the particle counts of an atom. */
  caption?: string;
  /** Frames per second at 1x for continuous and blend scenes. */
  rate?: number;
  at(frame: number): SciencePrimitive[];
  frameLabel?(frame: number): string;
}
const BASE: Record<string, string> = {
  A: '#f0b400', T: '#e3498a', U: '#a86f4c', C: '#2aa3e0', G: '#5dba4b', N: '#7d8794',      // adenine yellow, thymine pink, uracil brown, cytosine blue, guanine green
};
export const nucleotideColor = (base: string): string => BASE[base] ?? BASE.N;
const clamp = (n: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, n));
const node = <K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  return el;
};
function button(label: string, cb: () => void): HTMLButtonElement {
  const el = node('button', label);
  el.type = 'button';
  el.className = 'btn small';
  el.addEventListener('click', cb);
  return el;
}
/** The mode a spec is played in: what it says, else a cross-fade for two states and steps for more. */
export const modeOf = (spec: SceneSpec): SceneMode => spec.mode ?? ((spec.frames ?? 1) === 2 ? 'blend' : 'steps');
/** Offsets, in pixels, of the parallel strokes of a bond of `lanes` strokes, spread around the bond's axis. */
export function laneOffsets(lanes: number, gap: number): number[] {
  const n = Math.max(1, Math.min(3, Math.trunc(lanes)));
  return Array.from({ length: n }, (_, i) => (i - (n - 1) / 2) * gap);
}

interface Item { part: SciencePrimitive; alpha: number; depth: number; p?: { x: number; y: number }; q?: { x: number; y: number }; r?: number }

/** How much of a cylinder's end cap shows: 1 when its axis points at the viewer, near 0 when seen from the side. */
export const capOpening = (axis: V3, toViewer: V3): number => {
  const n = Math.hypot(axis[0], axis[1], axis[2]) || 1;
  return clamp(Math.abs((axis[0] * toViewer[0] + axis[1] * toViewer[1] + axis[2] * toViewer[2]) / n), .1, 1);
};

export function scientificScene(spec: SceneSpec): ScienceScene {
  const total = Math.max(1, Math.min(1200, Math.trunc(spec.frames ?? 1)));
  const mode = modeOf(spec);
  const extent = Math.max(.1, spec.extent ?? 1.5);
  const baseRate = spec.rate ?? (mode === 'continuous' ? 15 : mode === 'blend' ? 0.8 : 1);
  let pos = 0;                      // the playback position; fractional in continuous and blend scenes
  let running = false;
  let raf = 0;
  let last = 0;
  let stepClock = 0;
  let onScreen = true;
  let baseZoom = 1;                 // the zoom that makes the whole scene fit the canvas; "home" is the default angle at this zoom
  let fitKey = '';
  let touched = false;               // the person has moved the camera, so a resize must not change it
  const home = (): Camera => ({ ...cloneCamera(DEFAULT_CAMERA), zoom: baseZoom });
  let cam: Camera = home();
  let speed = mode === 'steps' ? 2 : 1;
  let picked = '';
  let lastPick: Array<{ x: number; y: number; r: number; depth: number; label: string }> = [];
  const pointers = new Map<number, { x: number; y: number }>();
  let samples: Array<{ t: number; x: number; y: number }> = [];
  let pinchDist = 0;
  let moved = 0;
  let panMode = false;

  const el = node('div');
  el.className = 'science-scene';
  const canvas = node('canvas');
  canvas.tabIndex = 0;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', spec.description + '. Drag to orbit, shift-drag or two fingers to pan, wheel or pinch to zoom. Arrow keys rotate; plus and minus zoom; space plays.');
  const wrap = node('div');
  wrap.className = 'science-canvas';
  wrap.append(canvas);
  const controls = node('div');
  controls.className = 'science-controls';
  const info = node('span', spec.description);
  info.className = 'muted';
  const status = node('span');
  status.className = 'muted';
  status.setAttribute('aria-live', 'polite');

  const motion = new CameraMotion({
    get: () => cam,
    set: (c) => { cam = c; },
    redraw: () => draw(),
    alive: () => el.isConnected,
  });
  const reset = button('Reset view', () => { touched = false; motion.animateTo(home()); });
  const spin = button('Spin', () => {
    const want = !motion.isSpinning;
    if (want && !motion.setSpin(true)) { status.textContent = 'Animation is switched off (reduce motion).'; return; }
    if (!want) motion.setSpin(false);
  });
  spin.setAttribute('aria-pressed', 'false');
  motion.onChange = () => { spin.setAttribute('aria-pressed', String(motion.isSpinning)); spin.classList.toggle('on', motion.isSpinning); };
  const exportBtn = button('PNG', () => {
    canvas.toBlob((blob) => {
      if (!blob) return;
      saveBlob(blob, 'scical-scientific-scene.png');
    }, 'image/png');
  });
  controls.append(reset, spin, exportBtn);
  const play = button('Play', () => toggle());
  play.setAttribute('aria-pressed', 'false');
  const back = button('◀', () => setFrame(Math.round(pos) - 1));
  back.setAttribute('aria-label', 'Previous step');
  const forward = button('▶', () => setFrame(Math.round(pos) + 1));
  forward.setAttribute('aria-label', 'Next step');
  const timeline = node('input');
  timeline.type = 'range';
  timeline.min = '0';
  timeline.max = String(total - 1);
  timeline.value = '0';
  timeline.step = mode === 'steps' ? '1' : '0.01';
  timeline.setAttribute('aria-label', 'Animation timeline');
  timeline.addEventListener('input', () => { pos = clamp(Number(timeline.value), 0, total - 1); sync(); draw(); });
  const rate = node('select');
  rate.setAttribute('aria-label', 'Animation speed');
  const speeds = mode === 'steps' ? [1, 2, 5, 10] : [0.5, 1, 2, 4];
  for (const s of speeds) {
    const o = node('option', mode === 'steps' ? s + ' steps/s' : s + '×');
    o.value = String(s);
    o.selected = s === speed;
    rate.append(o);
  }
  rate.addEventListener('change', () => { speed = Number(rate.value); });
  const transport = node('div');
  transport.className = 'science-controls';
  if (total > 1) transport.append(play, back, timeline, forward, rate, status);
  else transport.append(status);
  el.append(wrap, controls, transport, info);

  /** Show the position in the timeline and the label; cheap enough to call on every frame. */
  function sync(): void {
    timeline.value = String(pos);
    const whole = clamp(Math.round(pos), 0, total - 1);
    const text = spec.frameLabel?.(whole) ?? (total > 1 ? 'Step ' + whole + '/' + (total - 1) : '');
    if (status.textContent !== text) status.textContent = text;
  }
  function setFrame(f: number): void {
    pos = clamp(Math.trunc(f), 0, total - 1);
    if (running && pos >= total - 1 && mode !== 'continuous') toggle();
    sync();
    draw();
  }
  function toggle(): void {
    running = !running;
    play.textContent = running ? 'Pause' : 'Play';
    play.setAttribute('aria-pressed', String(running));
    last = 0; stepClock = 0;
    if (running && mode !== 'continuous' && pos >= total - 1) pos = 0;     // Play after the end starts again
    if (running) schedule(); else if (raf) { cancelAnimationFrame(raf); raf = 0; }
  }
  function schedule(): void { if (running && onScreen && !raf) raf = requestAnimationFrame(tick); }
  function tick(t: number): void {
    raf = 0;
    if (!running) return;
    if (!el.isConnected) { toggle(); return; }
    const dt = last ? t - last : 0;
    last = t;
    const smooth = !reducedMotion();
    const before = Math.round(pos);
    if (smooth) {
      const r = advancePlayback(pos, dt, baseRate * speed, total, mode === 'continuous');
      pos = r.frame;
      if (r.ended) { sync(); draw(); toggle(); return; }
      if (mode === 'steps') { if (Math.round(pos) !== before) { sync(); draw(); } }
      else { sync(); draw(); }
    } else {
      // reduced motion: whole steps at a gentle pace, no tweening
      stepClock += dt;
      const interval = 1000 / (mode === 'steps' ? speed : 2 * speed);
      if (stepClock >= interval) {
        stepClock = 0;
        const next = Math.round(pos) + 1;
        if (next > total - 1 && mode === 'continuous') pos = 0; else if (next > total - 1) { toggle(); return; } else pos = next;
        sync(); draw();
      }
    }
    schedule();
  }

  const parts = (frame: number): SciencePrimitive[] => spec.at(frame);
  function collect(): Array<{ part: SciencePrimitive; alpha: number }> {
    const f = clamp(pos, 0, total - 1);
    if (mode === 'blend' && !reducedMotion() && f !== Math.round(f)) {
      const b = frameBlend(f, total);
      const t = easeInOut(b.t);
      return [...parts(b.a).map((part) => ({ part, alpha: 1 - t })), ...parts(b.b).map((part) => ({ part, alpha: t }))];
    }
    const whole = mode === 'continuous' ? f : Math.round(f);
    return parts(whole).map((part) => ({ part, alpha: 1 }));
  }

  /** Zoom so the whole scene (at the start, the middle and the end of its playback) fits the canvas with a margin. */
  function fitZoom(w: number, h: number): number {
    const probe = makeProjector({ ...cloneCamera(DEFAULT_CAMERA), zoom: 1 }, w, h);
    const frames = [...new Set([0, Math.floor((total - 1) / 2), total - 1])];
    let ex = 0, ey = 0;
    for (const f of frames) for (const part of parts(f)) {
      const pts = part.kind === 'ball' ? [part.p] : [part.a, part.b];
      const rad = part.kind === 'line' ? 0 : part.r / extent * .46 * Math.min(w, h) * 1.15;
      for (const q of pts) {
        const sp = probe.project([q[0] / extent, q[1] / extent, q[2] / extent]);
        ex = Math.max(ex, Math.abs(sp.x - w / 2) + rad); ey = Math.max(ey, Math.abs(sp.y - h / 2) + rad);
      }
    }
    if (ex <= 0 || ey <= 0) return 1;
    return clamp(Math.min((w / 2 * .88) / ex, (h / 2 * .88) / ey), .4, 4);
  }

  function draw(): void {
    const box = canvas.getBoundingClientRect();
    const w = Math.max(10, Math.round(box.width || 700));
    const h = Math.max(10, Math.round(box.height || 320));
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    const pw = Math.round(w * dpr), ph = Math.round(h * dpr);
    if (canvas.width !== pw || canvas.height !== ph) { canvas.width = pw; canvas.height = ph; }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    if (fitKey !== w + 'x' + h) {                        // only when the canvas size changes: the fit looks at the whole animation
      fitKey = w + 'x' + h;
      baseZoom = fitZoom(w, h);
      if (!touched) cam = { ...cam, zoom: baseZoom };
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const bg = getComputedStyle(document.documentElement).getPropertyValue('--plot-bg').trim() || '#ffffff';
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);
    const projection = makeProjector(cam, w, h);
    const project = (p: V3) => projection.project([p[0] / extent, p[1] / extent, p[2] / extent]);
    const persp = cam.projection === 'perspective';
    const scaleAt = (depth: number): number => (persp ? 3.2 / Math.max(.2, depth) : 1);
    const pxPerUnit = .46 * Math.min(w, h) * cam.zoom;
    lastPick = [];
    const items: Item[] = [];
    let near = Infinity, far = -Infinity;
    for (const { part, alpha } of collect()) {
      if (part.kind === 'ball') {
        const p = project(part.p);
        const r = Math.max(1.2, part.r / extent * pxPerUnit * scaleAt(p.depth));
        items.push({ part, alpha, depth: p.depth, p, r });
        near = Math.min(near, p.depth); far = Math.max(far, p.depth);
      } else {
        const a = project(part.a), b = project(part.b);
        const r = part.kind === 'rod' ? Math.max(1.2, part.r / extent * pxPerUnit * scaleAt((a.depth + b.depth) / 2)) : undefined;
        items.push({ part, alpha, depth: (a.depth + b.depth) / 2, p: a, q: b, r });
        near = Math.min(near, a.depth, b.depth); far = Math.max(far, a.depth, b.depth);
      }
    }
    items.sort((a, b) => b.depth - a.depth);
    ctx.lineCap = 'round';
    for (const item of items) {
      const shape = item.part;
      // depth cue relative to a minimum span, so a small molecule is not faded as if it were a large scene
      const fade = item.alpha * depthFade(item.depth, near, near + Math.max(far - near, 1.4), .5);
      if (fade <= 0.01) continue;
      if (shape.kind === 'rod' && item.p && item.q && item.r) {
        const axis: V3 = [shape.b[0] - shape.a[0], shape.b[1] - shape.a[1], shape.b[2] - shape.a[2]];
        const open = capOpening(axis, projection.toViewer);
        const towardViewer = axis[0] * projection.toViewer[0] + axis[1] * projection.toViewer[1] + axis[2] * projection.toViewer[2] > 0;
        drawRod(ctx, item.p, item.q, item.r, shape.color, fade, open, towardViewer);
        if (shape.label && item.alpha > .5) lastPick.push({ x: (item.p.x + item.q.x) / 2, y: (item.p.y + item.q.y) / 2, r: Math.max(item.r * 1.4, 6), depth: item.depth, label: shape.label });
        if (shape.label && picked && shape.label === picked) {
          ctx.globalAlpha = 1;
          ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#b89b00';
          ctx.lineWidth = 2.2; ctx.lineCap = 'round';
          ctx.beginPath(); ctx.moveTo(item.p.x, item.p.y); ctx.lineTo(item.q.x, item.q.y); ctx.stroke();
          ctx.lineCap = 'round';
        }
      } else if (shape.kind === 'line' && item.p && item.q) {
        const width = Math.max(.8, (shape.width ?? 2) * (persp ? Math.min(1.6, scaleAt(item.depth) * .9) : 1));
        strokeBond(ctx, item.p, item.q, shape, width, fade);
      } else if (shape.kind === 'ball' && item.p && item.r) {
        const { x, y } = item.p, r = item.r;
        ctx.globalAlpha = fade;
        ctx.fillStyle = shape.color;
        ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
        if (r >= 3) {
          // light from the upper left: a soft highlight, a darker far edge, and a thin outline so touching atoms stay separate
          const g = ctx.createRadialGradient(x - r * .32, y - r * .36, 0, x - r * .1, y - r * .12, r * 1.2);
          g.addColorStop(0, 'rgba(255,255,255,.62)');
          g.addColorStop(.3, 'rgba(255,255,255,0)');
          g.addColorStop(.72, 'rgba(8,16,30,.06)');
          g.addColorStop(1, 'rgba(8,16,30,.5)');
          ctx.fillStyle = g;
          ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill();
          if (r >= 5) { ctx.strokeStyle = 'rgba(8,16,30,.35)'; ctx.lineWidth = .8; ctx.stroke(); }
        }
        if (shape.label && picked && shape.label === picked) {
          ctx.globalAlpha = 1;
          ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#b89b00';
          ctx.lineWidth = 2.2;
          ctx.beginPath(); ctx.arc(x, y, r + 3.5, 0, Math.PI * 2); ctx.stroke();
        }
        if (shape.label && r >= 6.5 && item.alpha > .6) {
          ctx.globalAlpha = Math.min(1, fade + .25);
          ctx.fillStyle = '#fff';
          ctx.strokeStyle = 'rgba(8,16,30,.55)';
          ctx.lineWidth = 2.4;
          ctx.font = 'bold ' + clamp(r * .9, 9, 15) + 'px system-ui';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          const text = shape.label.split(' ')[0].slice(0, 3);        // 'A · 12' shows as 'A'; the full label stays in the selection line
          ctx.strokeText(text, x, y); ctx.fillText(text, x, y);
        }
        ctx.globalAlpha = 1;
        if (shape.label && r >= 4 && item.alpha > .5) lastPick.push({ x, y, r, depth: item.depth, label: shape.label });
      }
    }
    ctx.globalAlpha = 1;
    if (spec.caption) {
      ctx.font = '600 13px system-ui';
      ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#222';
      ctx.fillStyle = textColor; ctx.globalAlpha = .88;
      ctx.fillText(spec.caption, 12, 10);
      ctx.globalAlpha = 1;
    }
  }

  /** A cylinder: flat shaded body between the two end centres, and an elliptical cap at each end (the near one lighter). */
  function drawRod(ctx: CanvasRenderingContext2D, a: { x: number; y: number }, b: { x: number; y: number }, width: number, color: string, alpha: number, open: number, nearIsB: boolean): void {
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = Math.hypot(dx, dy);
    const ux = len > 1e-6 ? dx / len : 1, uy = len > 1e-6 ? dy / len : 0;
    const nx = -uy, ny = ux;
    const angle = Math.atan2(uy, ux);
    const cap = (c: { x: number; y: number }, light: boolean): void => {
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.ellipse(c.x, c.y, Math.max(.6, width * open), width, angle, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = light ? 'rgba(255,255,255,.34)' : 'rgba(8,16,30,.30)';
      ctx.beginPath(); ctx.ellipse(c.x, c.y, Math.max(.6, width * open), width, angle, 0, Math.PI * 2); ctx.fill();
      if (width >= 3) { ctx.strokeStyle = 'rgba(8,16,30,.38)'; ctx.lineWidth = .8; ctx.stroke(); }
    };
    ctx.globalAlpha = alpha;
    cap(nearIsB ? a : b, false);                                     // the far end shows only its outer rim
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(a.x + nx * width, a.y + ny * width); ctx.lineTo(b.x + nx * width, b.y + ny * width);
    ctx.lineTo(b.x - nx * width, b.y - ny * width); ctx.lineTo(a.x - nx * width, a.y - ny * width); ctx.closePath(); ctx.fill();
    if (width >= 2) {
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const g = ctx.createLinearGradient(mx - nx * width, my - ny * width, mx + nx * width, my + ny * width);
      g.addColorStop(0, 'rgba(8,16,30,.36)'); g.addColorStop(.3, 'rgba(255,255,255,.34)'); g.addColorStop(.6, 'rgba(255,255,255,0)'); g.addColorStop(1, 'rgba(8,16,30,.4)');
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.moveTo(a.x + nx * width, a.y + ny * width); ctx.lineTo(b.x + nx * width, b.y + ny * width);
      ctx.lineTo(b.x - nx * width, b.y - ny * width); ctx.lineTo(a.x - nx * width, a.y - ny * width); ctx.closePath(); ctx.fill();
    }
    cap(nearIsB ? b : a, true);
    ctx.globalAlpha = 1;
  }

  /** A stick: a dark outline under the colour so a bond reads against the atoms; `lanes` spreads a double or triple bond sideways. */
  function strokeBond(ctx: CanvasRenderingContext2D, a: { x: number; y: number }, b: { x: number; y: number }, shape: Extract<SciencePrimitive, { kind: 'line' }>, width: number, alpha: number): void {
    const dx = b.x - a.x, dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len;
    const offsets = laneOffsets(shape.lanes ?? 1, Math.max(3.2, width * 1.5));
    const lane = offsets.length > 1 ? width * .62 : width;
    const stick = lane >= 2.2;
    ctx.globalAlpha = alpha;
    for (const pass of stick ? [1, 0] : [0]) {
      for (const o of offsets) {
        const ax = a.x + nx * o, ay = a.y + ny * o, bx = b.x + nx * o, by = b.y + ny * o;
        if (pass === 1) {
          ctx.strokeStyle = 'rgba(8,16,30,.38)'; ctx.lineWidth = lane + 1.8;
          ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
        } else if (shape.color2 && shape.color2 !== shape.color) {
          const mx = (ax + bx) / 2, my = (ay + by) / 2;
          ctx.lineWidth = lane;
          ctx.strokeStyle = shape.color; ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(mx, my); ctx.stroke();
          ctx.strokeStyle = shape.color2; ctx.beginPath(); ctx.moveTo(mx, my); ctx.lineTo(bx, by); ctx.stroke();
        } else {
          ctx.strokeStyle = shape.color; ctx.lineWidth = lane;
          ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
        }
      }
    }
    ctx.globalAlpha = 1;
  }

  // ---------------------------------------------------------------------------------------------------------------- gestures
  const sizeOf = (): number => Math.min(canvas.clientWidth, canvas.clientHeight);
  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    motion.interrupt();
    touched = true;
    samples = [];
    moved = 0;
    pinchDist = 0;
    panMode = e.button === 1 || e.button === 2 || e.shiftKey;
  });
  canvas.addEventListener('pointermove', (e) => {
    const prev = pointers.get(e.pointerId);
    if (!prev) return;
    const dx = e.clientX - prev.x, dy = e.clientY - prev.y;
    moved += Math.abs(dx) + Math.abs(dy);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size >= 2) {
      const [a, c] = [...pointers.values()];
      const dist = Math.hypot(a.x - c.x, a.y - c.y);
      if (pinchDist > 0 && dist > 0) cam = zoomBy(cam, dist / pinchDist);
      pinchDist = dist;
      cam = panBy(cam, dx / 2, dy / 2, sizeOf());                  // two fingers also move the scene
    } else {
      samples.push({ t: performance.now(), x: e.clientX, y: e.clientY });
      if (samples.length > 12) samples.shift();
      cam = panMode ? panBy(cam, dx, dy, sizeOf()) : orbit(cam, dx, dy, sizeOf());
    }
    draw();
  });
  const release = (e: PointerEvent): void => {
    if (!pointers.delete(e.pointerId)) return;
    if (pointers.size > 0) return;
    if (e.type === 'pointerup') {
      if (moved < 6) {
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left, y = e.clientY - rect.top;
        const reach = (p: { r: number }): number => Math.max(p.r, e.pointerType === 'touch' ? 16 : 8);
        const choice = lastPick.filter((p) => Math.hypot(p.x - x, p.y - y) <= reach(p)).sort((a, b) => a.depth - b.depth)[0];
        picked = choice ? choice.label : '';
        info.textContent = picked ? spec.description + ' · selected: ' + picked : spec.description;
        draw();
      } else if (!panMode) {
        motion.fling(releaseVelocity(samples, sizeOf(), performance.now()));
      }
    }
    motion.resume();
  };
  canvas.addEventListener('pointerup', release);
  canvas.addEventListener('pointercancel', release);
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); motion.interrupt(); touched = true; cam = zoomBy(cam, e.deltaY < 0 ? 1.12 : 1 / 1.12); draw(); }, { passive: false });
  canvas.addEventListener('dblclick', () => { touched = false; motion.animateTo(home()); });
  canvas.addEventListener('keydown', (e) => {
    let handled = true;
    motion.interrupt();
    touched = true;
    if (e.key === 'ArrowLeft') cam = orbit(cam, -25, 0, 300);
    else if (e.key === 'ArrowRight') cam = orbit(cam, 25, 0, 300);
    else if (e.key === 'ArrowUp') cam = orbit(cam, 0, 25, 300);
    else if (e.key === 'ArrowDown') cam = orbit(cam, 0, -25, 300);
    else if (e.key === '+' || e.key === '=') cam = zoomBy(cam, 1.15);
    else if (e.key === '-') cam = zoomBy(cam, 1 / 1.15);
    else if (e.key === '0') { touched = false; motion.animateTo(home()); e.preventDefault(); return; }
    else if (e.key === ' ' && total > 1) toggle();
    else handled = false;
    if (handled) { e.preventDefault(); draw(); }
  });
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => draw());
  observer?.observe(wrap);
  // nothing moves while the scene is scrolled out of view or the tab is hidden
  const visibility = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver((entries) => {
    onScreen = entries.some((en) => en.isIntersecting);
    if (onScreen) { last = 0; schedule(); }
  });
  visibility?.observe(wrap);
  const onHidden = (): void => { if (!document.hidden) { last = 0; schedule(); } };
  document.addEventListener('visibilitychange', onHidden);
  sync();
  draw();
  return {
    el, setFrame,
    destroy: () => {
      running = false; cancelAnimationFrame(raf); raf = 0; motion.stop();
      observer?.disconnect(); visibility?.disconnect(); document.removeEventListener('visibilitychange', onHidden);
      el.remove();
    },
  };
}
function centroidOf(points: V3[]): V3 { return [0, 1, 2].map((k) => points.reduce((sum, p) => sum + p[k], 0) / Math.max(1, points.length)) as V3; }
const point = (x: number, y: number, z: number): V3 => [x, y, z];
const ball = (p: V3, color: string, r = .07, label?: string): SciencePrimitive => ({ kind: 'ball', p, r, color, label });
const line = (a: V3, b: V3, color: string, width = 2, color2?: string, lanes?: number): SciencePrimitive => ({ kind: 'line', a, b, color, width, ...(color2 ? { color2 } : {}), ...(lanes ? { lanes } : {}) });
const coreShells: Record<string, number[]> = {
  He: [2], Ne: [2, 8], Ar: [2, 8, 8], Kr: [2, 8, 18, 8],
  Xe: [2, 8, 18, 18, 8], Rn: [2, 8, 18, 32, 18, 8],
};
export function electronShells(config: string, electrons: number): number[] {
  const shell = Array(7).fill(0) as number[];
  const core = /\[([A-Za-z]+)\]/.exec(config);
  if (core && coreShells[core[1]]) for (let i = 0; i < coreShells[core[1]].length; i++) shell[i] = coreShells[core[1]][i];
  for (const match of config.matchAll(/([1-7])[spdf](\d{1,2})/g)) shell[Number(match[1]) - 1] += Number(match[2]);
  const actual = shell.reduce((a, b) => a + b, 0);
  if (!actual || !Number.isInteger(electrons) || electrons < 0) return [];
  // Ionic orbital reconfiguration is not inferred: remove/add schematic outer electrons only.
  let delta = electrons - actual;
  for (let i = 6; i >= 0 && delta < 0; i--) { const drop = Math.min(shell[i], -delta); shell[i] -= drop; delta += drop; }
  if (delta > 0) {
    let outer = 0;
    for (let i = 0; i < shell.length; i++) if (shell[i] > 0) outer = i;
    shell[outer] += delta;
  }
  return shell;
}
/**
 * Nucleons packed like spheres in contact: the `count` face-centred-cubic lattice points nearest the middle, which is the densest way to
 * pack equal spheres. Neighbouring nucleons touch exactly and none overlaps. The result is centred on its centroid.
 */
export function nucleonLayout(count: number, radius: number): V3[] {
  const n = Math.max(0, Math.trunc(count));
  if (n === 0) return [];
  const unit = radius * Math.SQRT2;                                  // lattice spacing that makes nearest neighbours 2*radius apart
  const reach = Math.ceil(Math.cbrt(n / .74) / Math.SQRT2) + 2;
  const sites: Array<{ i: number; j: number; k: number; d: number }> = [];
  for (let i = -reach; i <= reach; i++) for (let j = -reach; j <= reach; j++) for (let k = -reach; k <= reach; k++) {
    if ((i + j + k) % 2 !== 0) continue;                             // face-centred cubic: the sum of the indices is even
    sites.push({ i, j, k, d: i * i + j * j + k * k });
  }
  sites.sort((x, y) => x.d - y.d || x.k - y.k || x.j - y.j || x.i - y.i);        // a fixed order: the same nucleus every time
  const chosen = sites.slice(0, n).map((q) => [q.i * unit, q.j * unit, q.k * unit] as V3);
  const mid = centroidOf(chosen);
  return chosen.map((q) => [q[0] - mid[0], q[1] - mid[1], q[2] - mid[2]] as V3);
}
/** Which of the nucleons are protons: spread evenly through the nucleus (Bresenham), so protons and neutrons are mixed, in exact numbers. */
export function protonMask(count: number, protons: number): boolean[] {
  const n = Math.max(0, Math.trunc(count));
  const z = Math.max(0, Math.min(n, Math.trunc(protons)));
  return Array.from({ length: n }, (_, i) => Math.floor(((i + 1) * z) / Math.max(1, n)) > Math.floor((i * z) / Math.max(1, n)));
}
const nucleonRadius = (count: number): number => clamp(.4 / (Math.cbrt(Math.max(1, count) / .74) + 1), .045, .16);
export const ELECTRON_RADIUS = .044;                                  // a fifth smaller than the first version's .055

export interface ElectronOrbit { shell: number; radius: number; u: V3; v: V3; normal: V3 }
const cross3 = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit3 = (a: V3): V3 => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
/**
 * One orbit per electron. Every orbit is a circle about the nucleus, so two orbits of different radius can never meet (a circle of
 * radius r lies wholly on the sphere of radius r). The radii are all different, grouped by shell, and the orbit planes are spread
 * evenly over the sphere (a Fibonacci spiral of plane normals), so every electron travels in its own plane.
 */
export function electronOrbits(shells: number[], firstShell: number): ElectronOrbit[] {
  const total = shells.reduce((s, n) => s + n, 0);
  const gap = clamp(1.6 / Math.max(1, total), .035, .09);
  const out: ElectronOrbit[] = [];
  let radius = firstShell;
  let k = 0;
  shells.forEach((count, shell) => {
    for (let i = 0; i < count; i++) {
      const y = 1 - 2 * (k + .5) / Math.max(1, total);                       // Fibonacci sphere: evenly spread plane normals
      const rr = Math.sqrt(Math.max(0, 1 - y * y));
      const phi = k * Math.PI * (3 - Math.sqrt(5));
      const normal = unit3([rr * Math.cos(phi), y, rr * Math.sin(phi)]);
      const helper: V3 = Math.abs(normal[1]) < .9 ? [0, 1, 0] : [1, 0, 0];
      const u = unit3(cross3(normal, helper));
      const v = cross3(normal, u);
      out.push({ shell, radius, u, v, normal });
      radius += gap;
      k++;
    }
    radius += .1;                                                           // a little more room between shells
  });
  return out;
}

export function atomScene(z: number, mass: number | null, charge: number, configuration: string, isotopeNote = ''): SceneSpec {
  const eCount = z - charge;
  const shells = electronShells(configuration, eCount);
  const nucleons = mass ?? z;
  const neutrons = mass === null ? 0 : mass - z;
  const countNote = mass === null ? 'Isotope not available: neutron count and full nucleus are unknown.' : z + ' protons, ' + neutrons + ' neutrons';
  const rn = nucleonRadius(nucleons);
  const layout = nucleonLayout(nucleons, rn);
  const mask = protonMask(nucleons, z);
  const nucleusRadius = layout.reduce((m, q) => Math.max(m, Math.hypot(q[0], q[1], q[2])), 0) + rn;
  const firstShell = Math.max(.62, nucleusRadius + .24);
  const orbits = electronOrbits(shells, firstShell);
  const outer = orbits.length ? orbits[orbits.length - 1].radius : firstShell;
  const caption = mass === null ? z + ' p⁺ · neutron count unknown · ' + eCount + ' e⁻' : z + ' p⁺ · ' + neutrons + ' n⁰ · ' + eCount + ' e⁻' + (isotopeNote ? ' · ' + isotopeNote : '');
  const segments = orbits.length > 40 ? 36 : 64;
  // the orbit circles do not change from frame to frame
  const rings = orbits.map((o) => {
    const pts = Array.from({ length: segments + 1 }, (_, i) => { const t = i / segments * 2 * Math.PI; const c = Math.cos(t) * o.radius, s = Math.sin(t) * o.radius; return point(o.u[0] * c + o.v[0] * s, o.u[1] * c + o.v[1] * s, o.u[2] * c + o.v[2] * s); });
    return pts.slice(1).map((q, i) => line(pts[i], q, '#77899b', 1));
  });
  return {
    description: 'Educational individualized electron paths, not quantum-mechanical trajectories. ' + countNote + '. ' + eCount + ' electrons, each on its own circular orbit in its own plane; ion shell placement is schematic.' +
      ' Nucleons are drawn touching, never overlapping; the orbits share the nucleus as their centre and have different radii, so they never cross.',
    caption,
    frames: 90, extent: Math.max(3, outer + .4), mode: 'continuous', rate: 15,
    at(frame) {
      const parts: SciencePrimitive[] = [];
      layout.forEach((q, i) => parts.push(ball(q, mask[i] ? '#d94b51' : '#8c959f', rn, mask[i] ? 'p+' : 'n')));
      rings.forEach((r) => parts.push(...r));
      orbits.forEach((o, i) => {
        // inner shells turn faster, in whole numbers of turns per cycle, so the loop has no jump; each electron starts at its own angle
        const t = ((i * .381966) % 1 + frame / 90 * Math.max(1, 4 - o.shell)) * 2 * Math.PI;
        const c = Math.cos(t) * o.radius, s = Math.sin(t) * o.radius;
        parts.push(ball(point(o.u[0] * c + o.v[0] * s, o.u[1] * c + o.v[1] * s, o.u[2] * c + o.v[2] * s), '#287cce', ELECTRON_RADIUS, 'e−'));
      });
      return parts;
    },
    frameLabel: () => 'Electrons circle their orbits for illustration only',
  };
}

// ------------------------------------------------------------------------------------------------------------------ nucleic acids
const BACKBONE: [string, string] = ['#7e5cc4', '#a187de'];             // the sugar–phosphate backbones: two purple ribbons
const rod = (a: V3, b: V3, r: number, color: string, label?: string): SciencePrimitive => ({ kind: 'rod', a, b, r, color, label });
const lerp3 = (a: V3, b: V3, t: number): V3 => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
const SPAN = 2.1;                                                      // the length of a strand in the scene
const stepOf = (size: number): number => SPAN / Math.max(size - 1, 1);
/** A point on the double helix's strand at (fractional) base position u; the helix turns .62 rad per base (about 10 bases per turn). */
/** The helix radius that keeps the real proportion (about 3 bases' spacing per radius), within limits for very short and very long sequences. */
const helixRadius = (size: number): number => clamp(3 * stepOf(size), .12, .3);
function helixAt(u: number, size: number, strand: number, turn = 0, radius = helixRadius(size)): V3 {
  const a = u * .62 + (strand < 0 ? Math.PI : 0) + turn;
  return [(u - (size - 1) / 2) * stepOf(size), radius * Math.cos(a), radius * Math.sin(a)];
}
/** A backbone ribbon between base positions `from` and `to`, as short thick segments that follow the helix. */
function ribbon(path: (u: number) => V3, from: number, to: number, color: string, pieces = 4, width = 5): SciencePrimitive[] {
  const out: SciencePrimitive[] = [];
  let prev = path(from);
  const total = Math.max(1, Math.round((to - from) * pieces));
  for (let k = 1; k <= total; k++) { const cur = path(from + (to - from) * k / total); out.push(line(prev, cur, color, width)); prev = cur; }
  return out;
}
/** The two bases of one pair: a cylinder from each backbone towards the middle, each in its own colour, stopping `gap` short of meeting. */
function basePair(i: number, size: number, base: string, partner: string, turn: number, meet = .94, radius = helixRadius(size)): SciencePrimitive[] {
  const a = helixAt(i, size, 1, turn, radius), b = helixAt(i, size, -1, turn, radius);
  const axis: V3 = [a[0], 0, 0];
  const r = clamp(stepOf(size) * .3, .012, .04);
  return [rod(a, lerp3(a, axis, meet), r, nucleotideColor(base), base + ' · ' + (i + 1)), rod(b, lerp3(b, axis, meet), r, nucleotideColor(partner), partner + ' · template')];
}
const complementOf = (b: string): string => ({ A: 'T', T: 'A', C: 'G', G: 'C', N: 'N' } as Record<string, string>)[b] ?? 'N';

export function dnaScene(sequence: string): SceneSpec {
  const seq = sequence.slice(0, 80);
  const size = seq.length;
  const CYCLE = 120;
  return { description: 'DNA double helix, coding 5′→3′ left to right; complementary template 3′→5′. Bases are cylinders joining the two sugar–phosphate backbones. Schematic geometry (the slow turn is for viewing only); showing ' + size + ' nt.',
    extent: 1.8, frames: CYCLE, mode: 'continuous', rate: 10,
    frameLabel: () => 'Helix turning about its axis (display only)',
    at: (frame) => {
      const turn = (frame / CYCLE) * 2 * Math.PI;
      const parts: SciencePrimitive[] = [];
      for (let i = 0; i < size; i++) parts.push(...basePair(i, size, seq[i], complementOf(seq[i]), turn));
      if (size > 1) for (const strand of [1, -1]) parts.push(...ribbon((u) => helixAt(u, size, strand, turn), 0, size - 1, BACKBONE[strand > 0 ? 0 : 1]));
      return parts;
    } };
}
function rnaPoint(u: number, size: number, radius = helixRadius(size) * .8): V3 {
  return [(u - (size - 1) / 2) * stepOf(size), radius * Math.sin(u * .65), radius * Math.cos(u * .65)];
}
export function rnaScene(sequence: string): SceneSpec {
  const seq = sequence.slice(0, 80);
  const size = seq.length;
  return { description: 'RNA single strand, 5′→3′ left to right: a sugar–phosphate backbone with one cylinder per base; illustrative path, not predicted secondary structure. Showing ' + size + ' nt.',
    extent: 1.8, at: () => {
      const parts: SciencePrimitive[] = [];
      const r = clamp(stepOf(size) * .3, .012, .04);
      for (let i = 0; i < size; i++) {
        const p = rnaPoint(i, size);
        parts.push(rod(p, lerp3(p, [p[0], 0, 0], .9), r, nucleotideColor(seq[i]), seq[i] + ' · ' + (i + 1)));
      }
      if (size > 1) parts.push(...ribbon((u) => rnaPoint(u, size), 0, size - 1, BACKBONE[0]));
      return parts;
    } };
}
export function transcriptionScene(coding: string, transcript: string): SceneSpec {
  const size = Math.min(80, coding.length);
  return { description: 'Schematic transcription: polymerase advances along template 3′→5′ while RNA grows 5′→3′. No promoter or processing is simulated.',
    frames: size + 1, extent: 1.8,
    frameLabel: (f) => f + '/' + size + ' nucleotides transcribed' + (coding.length > size ? ' (preview capped)' : ''),
    at(step) {
      // A small transcription bubble: the pairs around the polymerase are open (the bases stop short of each other) and close behind it.
      const parts: SciencePrimitive[] = [];
      for (let i = 0; i < size; i++) {
        const opened = step < size && Math.abs(i - step) <= 2;
        parts.push(...basePair(i, size, coding[i], complementOf(coding[i]), 0, opened ? .5 : .94, helixRadius(size) * (opened ? 1 + .5 * (1 - Math.abs(i - step) / 3) : 1)));
      }
      if (size > 1) for (const strand of [1, -1]) parts.push(...ribbon((u) => helixAt(u, size, strand), 0, size - 1, BACKBONE[strand > 0 ? 0 : 1]));
      const x = (i: number): number => (i - (size - 1) / 2) * stepOf(size);
      const r = clamp(stepOf(size) * .3, .012, .04);
      for (let i = 0; i < step; i++) parts.push(rod(point(x(i), -.68, -.48), point(x(i), -.5, -.34), r, nucleotideColor(transcript[i]), transcript[i] + ' · RNA ' + (i + 1)));
      if (step > 1) parts.push(...ribbon((u) => point(x(u), -.68, -.48), 0, step - 1, BACKBONE[0], 1));
      if (step < size) parts.push(ball(point(x(step), 0, -.15), '#667e90', .22, 'Pol'));
      return parts;
    } };
}
export interface TranslationStep { codon: string; aa: string; anticodon?: string }
export function translationScene(mrna: string, codons: TranslationStep[], start: number): SceneSpec {
  const steps = codons.slice(0, 65);
  const size = steps.length;
  const bases = size * 3;
  const gap = 2.3 / Math.max(1, bases - 1);
  const xb = (i: number): number => (i - (bases - 1) / 2) * gap;
  return { description: 'Schematic ribosomal translation: codons pair with tRNA anticodons (3′→5′); stop uses a release factor, not tRNA. No protein folding is inferred.',
    frames: size + 1, extent: 2,
    frameLabel: (f) => f === 0 ? 'Initiation at AUG' : 'Codon ' + f + '/' + size + ': ' + steps[f - 1]?.codon + ' → ' + (steps[f - 1]?.aa === '*' ? 'Stop' : steps[f - 1]?.aa),
    at(frame) {
      const parts: SciencePrimitive[] = [];
      const r = clamp(gap * .32, .02, .045);
      for (let i = 0; i < bases; i++) {
        const nt = mrna[start + i] ?? 'N';
        parts.push(rod(point(xb(i), -.35, 0), point(xb(i), -.35, .17), r, nucleotideColor(nt), nt));       // each mRNA base is a cylinder standing on the backbone
      }
      if (bases > 1) parts.push(...ribbon((u) => point(xb(u), -.35, 0), 0, bases - 1, BACKBONE[0], 1, 4));
      const k = Math.min(size - 1, frame);
      if (size) {
        const x = xb(k * 3 + 1);
        parts.push(ball(point(x, -.2, .2), '#b1a6b0', .32, 'R'));
        if (frame < size && steps[k].aa !== '*') {
          const anti = steps[k].anticodon ?? '';
          for (let j = 0; j < 3; j++) parts.push(rod(point(x + (j - 1) * .115, -.05, .57), point(x + (j - 1) * .115, -.05, .4), .035, nucleotideColor(anti[j] ?? 'N'), anti[j]));
        }
      }
      const amino = steps.slice(0, frame).filter((q) => q.aa !== '*');
      for (let i = 0; i < amino.length; i++) {
        const q = point(-.9 + i * (1.8 / Math.max(1, amino.length)), .45, .55 + .12 * Math.sin(i));
        parts.push(ball(q, '#38a9a4', .095, amino[i].aa));
        if (i) parts.push(line(point(-.9 + (i - 1) * (1.8 / Math.max(1, amino.length)), .45, .55 + .12 * Math.sin(i - 1)), q, '#578c8b', 3));
      }
      return parts;
    } };
}
export interface StoichSpecies { species: string; coefficient: number; atoms: Record<string, number> }
function elementColor(symbol: string): string {
  const known: Record<string, string> = { H: '#d2d5dc', O: '#d94b51', N: '#4185d5', C: '#525a65', S: '#d8b138', Cl: '#3da56c', Fe: '#a97342' };
  if (known[symbol]) return known[symbol];
  const hash = [...symbol].reduce((h, c) => h * 31 + c.charCodeAt(0), 19);
  return 'hsl(' + (Math.abs(hash) % 360) + ' 52% 55%)';
}
export function reactionScene(reactants: StoichSpecies[], products: StoichSpecies[]): SceneSpec {
  const sides = [reactants, products];
  return { description: '3D stoichiometric atom inventory only. Positions and grouping are schematic; no molecular structure, bonds, pathway or reaction dynamics are implied.',
    frames: 2, extent: 2.4, frameLabel: (f) => f === 0 ? 'Reactants' : 'Products',
    at(f) {
      const species = sides[f];
      const parts: SciencePrimitive[] = [];
      species.forEach((s, idx) => {
        const atoms: string[] = [];
        for (let k = 0; k < Math.min(s.coefficient, 12); k++)
          for (const [sym, amount] of Object.entries(s.atoms))
            for (let j = 0; j < Math.min(amount, 24); j++) if (atoms.length < 280) atoms.push(sym);
        const x0 = (idx - (species.length - 1) / 2) * (3.6 / Math.max(1, species.length));
        atoms.forEach((sym, i) => {
          const angle = i * 2.3999632297, radial = Math.sqrt(i + .5) * .072;
          parts.push(ball(point(x0 + radial * Math.cos(angle), radial * Math.sin(angle), .22 * Math.sin(i * .74)), elementColor(sym), .07, sym));
        });
      });
      return parts;
    } };
}


export function mutationScene(original: string, mutated: string, kind: 'DNA' | 'RNA'): SceneSpec {
  const len = Math.max(original.length, mutated.length);
  const source = (seq: string): SceneSpec => kind === 'RNA' ? rnaScene(seq) : dnaScene(seq);
  return {
    description: 'Before/after ' + kind + ' nucleotide sequence comparison. Helix geometry is schematic; a mutation does not establish a phenotype.',
    frames: 2, extent: 1.8,
    frameLabel: (f) => f === 0 ? 'Original (' + original.length + ' bases)' : 'Mutated (' + mutated.length + ' bases)',
    at: (f) => source(f === 0 ? original : mutated).at(0).map((shape) => shape),
  };
}


/** A view size that fits the farthest atom (plus its radius) with a margin: a small molecule fills the view instead of sitting in the middle of it. */
export function fitExtent(points: V3[], radius: number, min = 1.2): number {
  const centre = centroidOf(points);
  const reach = points.reduce((m, p) => Math.max(m, Math.hypot(p[0] - centre[0], p[1] - centre[1], p[2] - centre[2])), 0);
  return Math.max(min, (reach + radius) * 1.45);
}
export interface MolecularAtom { element: string; xyz: V3 }
export interface MolecularBond { a: number; b: number; order: number }
export interface MolecularStructure {
  formula: string; name: string; charge: number; source: string;
  atoms: MolecularAtom[]; bonds: MolecularBond[];
}
/** Molecules have explicit NIST-sourced atom coordinates and connectivity, never inferred from formulas. */
export function moleculeScene(molecule: MolecularStructure): SceneSpec {
  const middle = centroidOf(molecule.atoms.map((a) => a.xyz));        // turn the molecule about its middle; a translation, no atom moves relative to another
  const at3 = (a: MolecularAtom | undefined): V3 | undefined => a && [a.xyz[0] - middle[0], a.xyz[1] - middle[1], a.xyz[2] - middle[2]];
  return {
    description: molecule.name + ' (' + molecule.formula + ') · fixed NIST CCCBDB reference geometry in Å. Select atoms to inspect; display is not a trajectory. Source: ' + molecule.source,
    extent: fitExtent(molecule.atoms.map((a) => a.xyz), .42), frames: 2,
    frameLabel: (f) => f ? 'Space-filling representation (illustrative relative radii)' : 'Ball-and-stick, bonds from explicit source topology',
    at(frame) {
      const parts: SciencePrimitive[] = [];
      if (frame === 0) for (const bond of molecule.bonds) {
        const a = at3(molecule.atoms[bond.a]);
        const b = at3(molecule.atoms[bond.b]);
        if (!a || !b) continue;
        const ea = molecule.atoms[bond.a].element, eb = molecule.atoms[bond.b].element;
        // one stick per bond, drawn as parallel strokes for a double or triple bond, each half in the colour of its atom
        parts.push(line(a, b, elementColor(ea), 4, elementColor(eb), Math.max(1, Math.min(3, Math.trunc(bond.order)))));
      }
      molecule.atoms.forEach((atom, i) => {
        const radius = frame ? ({ H: .26, C: .36, N: .34, O: .32, S: .44 } as Record<string, number>)[atom.element] ?? .33 : .16;
        parts.push(ball(at3(atom) as V3, elementColor(atom.element), radius, atom.element + (i + 1)));
      });
      return parts;
    },
  };
}
export interface StructuredReactionSpecies extends StoichSpecies { structure: MolecularStructure | null }
/** A reaction overview of fixed molecules; does not imply an atom-mapped mechanism or intermediates. */
export function molecularReactionScene(reactants: StructuredReactionSpecies[], products: StructuredReactionSpecies[]): SceneSpec {
  return {
    description: 'Fixed NIST reference molecular structures before and after a balanced reaction. Arrangement and transition are schematic; this is not a chemical mechanism.',
    frames: 2, extent: 5,
    frameLabel: (f) => f ? 'Products (validated fixed molecular geometries)' : 'Reactants (validated fixed molecular geometries)',
    at(frame) {
      const side = frame ? products : reactants;
      const structures = side.flatMap((sp) => Array.from({ length: sp.coefficient }, () => sp.structure)).filter((x): x is MolecularStructure => x !== null);
      const result: SciencePrimitive[] = [];
      structures.forEach((structure, i) => {
        const cx = (i - (structures.length - 1) / 2) * 2.6;
        const cy = Math.sin(i * 2) * .12;
        const mid = centroidOf(structure.atoms.map((a) => a.xyz));
        const offset = (p: V3): V3 => [p[0] - mid[0] + cx, p[1] - mid[1] + cy, p[2] - mid[2]];
        for (const bond of structure.bonds) {
          const a = structure.atoms[bond.a], b = structure.atoms[bond.b];
          if (a && b) result.push(line(offset(a.xyz), offset(b.xyz), elementColor(a.element), 3, elementColor(b.element), Math.max(1, Math.min(3, Math.trunc(bond.order)))));
        }
        structure.atoms.forEach((a, j) => result.push(ball(offset(a.xyz), elementColor(a.element), .17, structure.formula + ' ' + a.element + (j + 1))));
      });
      return result;
    },
  };
}


export function rnaProcessingScene(preMrna: string, matureMrna: string): SceneSpec {
  return {
    description: 'User-selected exon splicing of RNA 5′→3′. This sequence transformation does not predict splice sites, spliceosome kinetics, 5′ capping or polyadenylation.',
    frames: 2, extent: 1.8,
    frameLabel: (f) => f ? 'Spliced mature mRNA: ' + matureMrna.length + ' nucleotides' :
      'Pre-mRNA: ' + preMrna.length + ' nucleotides',
    at: (f) => rnaScene(f ? matureMrna : preMrna).at(0),
  };
}


export type OrbitalShape = 's' | 'p' | 'd' | 'f';
/** Real zonal spherical harmonic angular-symmetry isosurfaces (m=0). Radial scale is illustrative. */
export function orbitalAngularScene(orbital: OrbitalShape): SceneSpec {
  const label: Record<OrbitalShape, string> = { s: 's (l=0, m=0)', p: 'p_z (l=1, m=0)', d: 'd_z² (l=2, m=0)', f: 'f_z³ (l=3, m=0)' };
  const angular = (z: number): number => {
    if (orbital === 's') return 1;
    if (orbital === 'p') return z;
    if (orbital === 'd') return (3 * z * z - 1) / 2;
    return (5 * z * z * z - 3 * z) / 2;
  };
  return {
    description: 'Qualitative real spherical-harmonic angular isosurface: ' + label[orbital] +
      '. Colors denote opposite wavefunction phase, not electric charge. Radial wavefunction, electron occupancy and actual multi-electron density are NOT calculated.',
    extent: 2.2,
    at: () => {
      const pts: SciencePrimitive[] = [];
      const count = 2400;
      for (let i = 0; i < count; i++) {
        const z = 1 - 2 * (i + .5) / count;
        const phi = i * 2.399963229728653;
        const xy = Math.sqrt(1 - z * z);
        const ang = angular(z);
        const radius = 1.5 * Math.sqrt(Math.abs(ang));
        if (radius < .07) continue;
        const p = point(radius * xy * Math.cos(phi), radius * xy * Math.sin(phi), radius * z);
        pts.push(ball(p, ang < 0 ? '#be557c' : '#448fd5', .025));
      }
      return pts;
    },
  };
}
export function nucleusScene(z: number, mass: number | null, configuration: string, isotopeNote = ''): SceneSpec {
  const full = atomScene(z, mass, 0, configuration, isotopeNote);
  const neutrons = mass === null ? 0 : mass - z;
  return {
    description: 'Schematic nuclear composition. ' + (mass === null ? 'Neutron count is unavailable: only known protons shown.' :
      z + ' protons and ' + neutrons + ' neutrons, drawn touching and never overlapping. Spatial nucleon positions are not measured nuclear states.'),
    caption: mass === null ? z + ' p⁺ · neutron count unknown' : z + ' p⁺ · ' + neutrons + ' n⁰' + (isotopeNote ? ' · ' + isotopeNote : ''),
    extent: 1.2,
    at: () => full.at(0).filter((primitive) =>
      primitive.kind === 'ball' && (primitive.color === '#d94b51' || primitive.color === '#8c959f')),
  };
}
