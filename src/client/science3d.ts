// Scientific representations share the validated camera/projection mathematics of graphing.
// The Canvas2D primitives are deliberately schematic: they do not claim quantum trajectories,
// measured nuclear geometry, molecular bonds, or atomistic reaction dynamics.
import { DEFAULT_CAMERA, cloneCamera, makeProjector, orbit, panBy, zoomBy, type Camera, type V3 } from '../core/scene3d.js';

export type SciencePrimitive =
  | { kind: 'ball'; p: V3; r: number; color: string; label?: string; id?: string; group?: string }
  | { kind: 'line'; a: V3; b: V3; color: string; width?: number; label?: string; group?: string }
  | { kind: 'cylinder'; a: V3; b: V3; r: number; color: string; label?: string; id?: string; group?: string };
export interface SceneSelection {
  id: string;
  label: string;
  type: 'ball' | 'line' | 'cylinder';
  position: V3;
  group?: string;
}
export interface ScienceScene {
  el: HTMLElement;
  setFrame(frame: number): void;
  focusOn(position: V3, zoom?: number): void;
  resetCamera(): void;
  destroy(): void;
}
export interface SceneSpec {
  description: string;
  frames?: number;
  extent?: number;
  modes?: Array<{ id: string; label: string }>;
  at(frame: number, mode?: string): SciencePrimitive[];
  onPick?(selection: SceneSelection): void;
  frameLabel?(frame: number): string;
}
const BASE: Record<string, string> = {
  A: '#218b56', T: '#8a55ac', U: '#d54e55', C: '#287cce', G: '#d3a71b', N: '#7d8794',
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
export function scientificScene(spec: SceneSpec): ScienceScene {
  const total = Math.max(1, Math.min(1200, Math.trunc(spec.frames ?? 1)));
  const extent = Math.max(.1, spec.extent ?? 1.5);
  let frame = 0;
  let running = false;
  let raf = 0;
  let previous = 0;
  let accumulated = 0;
  let cam: Camera = cloneCamera(DEFAULT_CAMERA);
  let speed = 2;
  let picked = '';
  let mode = spec.modes?.[0]?.id ?? 'default';
  let focusPoint: V3 = [0, 0, 0];
  let focusAnimation = 0;
  const reducedMotion = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  let pointer: { x: number; y: number; startX: number; startY: number; moved: boolean; id: number } | null = null;
  let lastPick: Array<{ x: number; y: number; r: number; depth: number; selection: SceneSelection }> = [];
  let cacheFrame = -1;
  let cacheMode = '';
  let cacheParts: SciencePrimitive[] = [];
  const el = node('div');
  el.className = 'science-scene';
  const canvas = node('canvas');
  canvas.tabIndex = 0;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', spec.description + '. Drag to orbit, shift-drag to pan, wheel to zoom. Arrow keys rotate; plus/minus zoom.');
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
  const reset = button('Reset view', () => resetCamera());
  const exportBtn = button('PNG', () => {
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = node('a');
      a.href = url;
      a.download = 'scical-scientific-scene.png';
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    }, 'image/png');
  });
  controls.append(reset, exportBtn);
  const play = button('Play', () => toggle());
  const back = button('◀', () => setFrame(frame - 1));
  const forward = button('▶', () => setFrame(frame + 1));
  const timeline = node('input');
  timeline.type = 'range';
  timeline.min = '0';
  timeline.max = String(total - 1);
  timeline.value = '0';
  timeline.step = '1';
  timeline.setAttribute('aria-label', 'Animation timeline');
  timeline.addEventListener('input', () => setFrame(Number(timeline.value)));
  const rate = node('select');
  rate.setAttribute('aria-label', 'Animation speed');
  for (const s of [1, 2, 5, 10, 24]) {
    const o = node('option', s + ' steps/s');
    o.value = String(s);
    o.selected = s === speed;
    rate.append(o);
  }
  rate.addEventListener('change', () => { speed = Number(rate.value); });
  const transport = node('div');
  transport.className = 'science-controls';
  if (spec.modes?.length) {
    const display = node('select');
    display.setAttribute('aria-label', 'Scientific visualization mode');
    for (const m of spec.modes) {
      const option = node('option', m.label);
      option.value = m.id;
      display.append(option);
    }
    display.addEventListener('change', () => { mode = display.value; cacheFrame = -1; draw(); });
    controls.append(display);
  }
  if (total > 1) transport.append(play, back, timeline, forward, rate, status, button('Restart', () => {
    if (running) toggle();
    setFrame(0);
  }));
  el.append(wrap, controls, transport, info);
  function resetCamera(): void {
    cancelAnimationFrame(focusAnimation);
    focusPoint = [0, 0, 0];
    cam = cloneCamera(DEFAULT_CAMERA);
    draw();
  }
  function focusOn(position: V3, zoom = 3): void {
    cancelAnimationFrame(focusAnimation);
    const start = focusPoint;
    const beginZoom = cam.zoom;
    const targetZoom = clamp(zoom, .2, 15);
    const startTime = performance.now();
    const duration = reducedMotion ? 0 : 280;
    const animate = (time: number): void => {
      const t = duration ? clamp((time - startTime) / duration, 0, 1) : 1;
      const eased = t * t * (3 - 2 * t);
      focusPoint = start.map((x, i) => x + (position[i] - x) * eased) as V3;
      cam = { ...cam, zoom: beginZoom + (targetZoom - beginZoom) * eased };
      draw();
      if (t < 1) focusAnimation = requestAnimationFrame(animate);
    };
    if (reducedMotion) animate(performance.now());
    else focusAnimation = requestAnimationFrame(animate);
  }
  function setFrame(f: number): void {
    frame = clamp(Math.trunc(f), 0, total - 1);
    timeline.value = String(frame);
    status.textContent = spec.frameLabel?.(frame) ?? ('Step ' + frame + '/' + (total - 1));
    if (frame === total - 1 && running) toggle();
    draw();
  }
  function toggle(): void {
    running = !running;
    play.textContent = running ? 'Pause' : 'Play';
    previous = 0;
    accumulated = 0;
    if (running) raf = requestAnimationFrame(tick);
    else cancelAnimationFrame(raf);
  }
  function tick(t: number): void {
    if (!running) return;
    if (!el.isConnected) { toggle(); return; }
    if (previous) {
      accumulated += Math.min(100, t - previous);
      const interval = 1000 / speed;
      if (accumulated >= interval) {
        const frames = Math.floor(accumulated / interval);
        accumulated -= frames * interval;
        setFrame(frame + frames);
      }
    }
    previous = t;
    if (running) raf = requestAnimationFrame(tick);
  }
  function draw(): void {
    const box = canvas.getBoundingClientRect();
    const w = Math.max(10, Math.round(box.width || 700));
    const h = Math.max(10, Math.round(box.height || 320));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const pw = Math.round(w * dpr), ph = Math.round(h * dpr);
    if (canvas.width !== pw || canvas.height !== ph) { canvas.width = pw; canvas.height = ph; }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const bg = getComputedStyle(document.documentElement).getPropertyValue('--plot-bg').trim() || '#ffffff';
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);
    const projection = makeProjector(cam, w, h);
    const project = (p: V3) => projection.project([(p[0] - focusPoint[0]) / extent, (p[1] - focusPoint[1]) / extent, (p[2] - focusPoint[2]) / extent]);
    if (cacheFrame !== frame || cacheMode !== mode) {
      cacheParts = spec.at(frame, mode);
      cacheFrame = frame;
      cacheMode = mode;
    }
    const objects = cacheParts;
    lastPick = [];
    const radiusPx = (radius: number, depth: number): number =>
      Math.max(1.6, radius / extent * .46 * Math.min(w, h) * cam.zoom *
        (cam.projection === 'perspective' ? 3.2 / Math.max(.2, depth) : 1));
    const drawn = objects.map((part) => ({
      part,
      depth: part.kind === 'ball' ? project(part.p).depth :
        (project(part.a).depth + project(part.b).depth) / 2,
    })).sort((a, b) => b.depth - a.depth);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    for (const item of drawn) {
      const shape = item.part;
      if (shape.kind === 'line' || shape.kind === 'cylinder') {
        const a = project(shape.a), b = project(shape.b);
        ctx.lineWidth = shape.kind === 'cylinder' ?
          Math.max(2.4, radiusPx(shape.r, item.depth) * 2) : (shape.width ?? 2);
        if (shape.kind === 'cylinder') {
          // Projected solid rod with a subtle axial highlight; capped endpoints meet adjoining tubes.
          const shade = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
          shade.addColorStop(0, shape.color);
          shade.addColorStop(.5, shape.color);
          shade.addColorStop(1, shape.color);
          ctx.strokeStyle = shade;
        } else ctx.strokeStyle = shape.color;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        if (shape.kind === 'cylinder' && shape.label) {
          const x = (a.x + b.x) / 2, y = (a.y + b.y) / 2;
          const position: V3 = [
            (shape.a[0] + shape.b[0]) / 2,
            (shape.a[1] + shape.b[1]) / 2,
            (shape.a[2] + shape.b[2]) / 2,
          ];
          const selection: SceneSelection = {
            id: shape.id ?? shape.label, label: shape.label, type: shape.kind, position, group: shape.group,
          };
          lastPick.push({ x, y, r: Math.max(8, ctx.lineWidth), depth: item.depth, selection });
          if (picked === selection.id) {
            ctx.lineWidth += 2;
            ctx.strokeStyle = '#ffffff';
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
      } else {
        const p = project(shape.p);
        const r = radiusPx(shape.r, p.depth);
        const grad = ctx.createRadialGradient(p.x - r * .28, p.y - r * .32, r * .05, p.x, p.y, r);
        grad.addColorStop(0, '#f6f9fe');
        grad.addColorStop(.24, shape.color);
        grad.addColorStop(1, '#263747');
        ctx.fillStyle = grad;
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
        if (picked && picked === (shape.id ?? shape.label)) {
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        if (shape.label) {
          if (r >= 6.5) {
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold ' + clamp(r * .9, 9, 15) + 'px system-ui';
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText(shape.label.slice(0, 3), p.x, p.y);
          }
          lastPick.push({ x: p.x, y: p.y, r: Math.max(7, r), depth: p.depth,
            selection: { id: shape.id ?? shape.label, label: shape.label, type: shape.kind, position: shape.p, group: shape.group } });
        }
      }
    }
  }
  canvas.addEventListener('pointerdown', (e) => {
    cancelAnimationFrame(focusAnimation);
    pointer = { x: e.clientX, y: e.clientY, startX: e.clientX, startY: e.clientY, moved: false, id: e.pointerId };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!pointer || pointer.id !== e.pointerId) return;
    const dx = e.clientX - pointer.x, dy = e.clientY - pointer.y;
    if (e.shiftKey) cam = panBy(cam, dx, dy, Math.min(canvas.clientWidth, canvas.clientHeight));
    else cam = orbit(cam, dx, dy, Math.min(canvas.clientWidth, canvas.clientHeight));
    pointer = { ...pointer, x: e.clientX, y: e.clientY, moved: pointer.moved || Math.hypot(e.clientX - pointer.startX, e.clientY - pointer.startY) > 4 };
    draw();
  });
  canvas.addEventListener('pointerup', (e) => {
    if (pointer && !pointer.moved && Math.hypot(pointer.startX - e.clientX, pointer.startY - e.clientY) < 4) {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left, y = e.clientY - rect.top;
      const choice = lastPick.filter((p) => Math.hypot(p.x - x, p.y - y) <= p.r).sort((a, b) => a.depth - b.depth)[0];
      if (choice) {
        picked = choice.selection.id;
        info.textContent = spec.description + ' · selected: ' + choice.selection.label;
        spec.onPick?.(choice.selection);
        draw();
      }
    }
    pointer = null;
  });
  canvas.addEventListener('pointercancel', () => { pointer = null; });
  canvas.addEventListener('wheel', (e) => { e.preventDefault(); cam = zoomBy(cam, e.deltaY < 0 ? 1.12 : 1 / 1.12); draw(); }, { passive: false });
  canvas.addEventListener('keydown', (e) => {
    let handled = true;
    if (e.key === 'ArrowLeft') cam = orbit(cam, -25, 0, 300);
    else if (e.key === 'ArrowRight') cam = orbit(cam, 25, 0, 300);
    else if (e.key === 'ArrowUp') cam = orbit(cam, 0, 25, 300);
    else if (e.key === 'ArrowDown') cam = orbit(cam, 0, -25, 300);
    else if (e.key === '+') cam = zoomBy(cam, 1.15);
    else if (e.key === '-') cam = zoomBy(cam, 1 / 1.15);
    else if (e.key === '0') { resetCamera(); return; }
    else handled = false;
    if (handled) { e.preventDefault(); draw(); }
  });
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => draw());
  observer?.observe(wrap);
  setFrame(0);
  return { el, setFrame, focusOn, resetCamera, destroy: () => {
    running = false;
    cancelAnimationFrame(raf);
    cancelAnimationFrame(focusAnimation);
    observer?.disconnect();
    el.remove();
  } };
}
const point = (x: number, y: number, z: number): V3 => [x, y, z];
const ball = (p: V3, color: string, r = .07, label?: string): SciencePrimitive => ({ kind: 'ball', p, r, color, label });
const line = (a: V3, b: V3, color: string, width = 2): SciencePrimitive => ({ kind: 'line', a, b, color, width });
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
export function atomScene(z: number, mass: number | null, charge: number, configuration: string): SceneSpec {
  const eCount = z - charge;
  const shells = electronShells(configuration, eCount);
  const nucleons = mass ?? z;
  const countNote = mass === null ? 'Isotope not available: neutron count and full nucleus are unknown.' : z + ' protons, ' + (mass - z) + ' neutrons';
  return {
    description: 'Educational shell model, not a quantum-mechanical electron trajectory. ' + countNote + '. ' + eCount + ' electrons; ion shell placement is schematic.',
    frames: 90, extent: 3,
    at(frame) {
      const parts: SciencePrimitive[] = [];
      const n = Math.min(320, nucleons);
      for (let i = 0; i < n; i++) {
        const k = (i + .5) / n;
        const a = 2.3999632297 * i;
        const zz = 1 - 2 * k;
        const rr = Math.sqrt(1 - zz * zz) * Math.cbrt(k);
        const p = point(Math.cos(a) * rr * .48, Math.sin(a) * rr * .48, zz * Math.cbrt(k) * .48);
        parts.push(ball(p, i < z ? '#d94b51' : '#8c959f', .09, i < z ? 'p+' : 'n'));
      }
      shells.forEach((electrons, shell) => {
        if (!electrons) return;
        const rad = .67 + shell * .32;
        const ring = Array.from({ length: 65 }, (_, i) => {
          const t = i / 64 * 2 * Math.PI;
          return point(rad * Math.cos(t), rad * Math.sin(t) * Math.cos(shell * .67), rad * Math.sin(t) * Math.sin(shell * .67));
        });
        for (let i = 1; i < ring.length; i++) parts.push(line(ring[i - 1], ring[i], '#77899b', 1));
        for (let i = 0; i < electrons; i++) {
          const t = (i / electrons + frame / 90) * 2 * Math.PI;
          parts.push(ball(point(rad * Math.cos(t), rad * Math.sin(t) * Math.cos(shell * .67), rad * Math.sin(t) * Math.sin(shell * .67)), '#287cce', .055, 'e−'));
        }
      });
      return parts;
    },
    frameLabel: (f) => 'Schematic shell phase ' + (f + 1) + '/90',
  };
}
function basesPosition(i: number, size: number, strand = 1): V3 {
  const x = (i - (size - 1) / 2) * (2.1 / Math.max(size - 1, 1));
  const a = i * .62 + (strand < 0 ? Math.PI : 0);
  return point(x, .37 * Math.cos(a), .37 * Math.sin(a));
}
export function dnaScene(sequence: string): SceneSpec {
  const seq = sequence.slice(0, 80);
  const comp = (b: string): string => ({ A: 'T', T: 'A', C: 'G', G: 'C', N: 'N' } as Record<string, string>)[b] ?? 'N';
  return { description: 'DNA double helix, coding 5′→3′ left to right; complementary template 3′→5′. Schematic geometry; showing ' + seq.length + ' nt.',
    extent: 1.8,
    at: () => {
      const parts: SciencePrimitive[] = [];
      for (let i = 0; i < seq.length; i++) {
        const a = basesPosition(i, seq.length), b = basesPosition(i, seq.length, -1);
        parts.push(ball(a, nucleotideColor(seq[i]), .078, seq[i] + ' · ' + (i + 1)));
        parts.push(ball(b, nucleotideColor(comp(seq[i])), .078, comp(seq[i]) + ' · template'));
        parts.push(line(a, b, '#a3b0b8', 1));
        if (i) { parts.push(line(basesPosition(i - 1, seq.length), a, '#7ca981', 3), line(basesPosition(i - 1, seq.length, -1), b, '#a49cba', 3)); }
      }
      return parts;
    } };
}
export function rnaScene(sequence: string): SceneSpec {
  const seq = sequence.slice(0, 80);
  return { description: 'RNA single strand, 5′→3′ left to right; illustrative path, not predicted secondary structure. Showing ' + seq.length + ' nt.',
    extent: 1.8, at: () => {
      const parts: SciencePrimitive[] = [];
      for (let i = 0; i < seq.length; i++) {
        const p = point((i - (seq.length - 1) / 2) * (2.1 / Math.max(1, seq.length - 1)), .23 * Math.sin(i * .65), .2 * Math.cos(i * .65));
        parts.push(ball(p, nucleotideColor(seq[i]), .075, seq[i] + ' · ' + (i + 1)));
        if (i) {
          const prev = point((i - 1 - (seq.length - 1) / 2) * (2.1 / Math.max(1, seq.length - 1)), .23 * Math.sin((i - 1) * .65), .2 * Math.cos((i - 1) * .65));
          parts.push(line(prev, p, '#a58d4b', 3));
        }
      }
      return parts;
    } };
}
export function transcriptionScene(coding: string, transcript: string): SceneSpec {
  const size = Math.min(80, coding.length);
  return { description: 'Schematic transcription: polymerase advances along template 3′→5′ while RNA grows 5′→3′. No promoter or processing is simulated.',
    frames: size + 1, extent: 1.8,
    frameLabel: (f) => f + '/' + size + ' nucleotides transcribed' + (coding.length > size ? ' (preview capped)' : ''),
    at(step) {
      // Draw a small, local transcription bubble. The opened region closes behind the
      // schematic polymerase rather than leaving the entire helix permanently separated.
      const parts: SciencePrimitive[] = [];
      const pair: Record<string, string> = { A: 'T', T: 'A', G: 'C', C: 'G', N: 'N' };
      let lastCoding: V3 | null = null;
      let lastTemplate: V3 | null = null;
      for (let i = 0; i < size; i++) {
        const opened = step < size && Math.abs(i - step) <= 2;
        const scale = opened ? 1 + .8 * (1 - Math.abs(i - step) / 3) : 1;
        const c = basesPosition(i, size);
        const t = basesPosition(i, size, -1);
        const a: V3 = [c[0], c[1] * scale, c[2] * scale];
        const b: V3 = [t[0], t[1] * scale, t[2] * scale];
        parts.push(ball(a, nucleotideColor(coding[i]), .07, coding[i]));
        parts.push(ball(b, nucleotideColor(pair[coding[i]]), .07, pair[coding[i]]));
        if (!opened) parts.push(line(a, b, '#a4b4bd', 1));
        if (lastCoding && lastTemplate) {
          parts.push(line(lastCoding, a, '#7ca981', 3));
          parts.push(line(lastTemplate, b, '#a49cba', 3));
        }
        lastCoding = a; lastTemplate = b;
      }
      for (let i = 0; i < step; i++) {
        const x = (i - (size - 1) / 2) * (2.1 / Math.max(size - 1, 1));
        const p = point(x, -.68, -.48);
        parts.push(ball(p, nucleotideColor(transcript[i]), .075, transcript[i]));
        if (i) {
          const px = (i - 1 - (size - 1) / 2) * (2.1 / Math.max(size - 1, 1));
          parts.push(line(point(px, -.68, -.48), p, '#c2a261', 3));
        }
      }
      if (step < size) parts.push(ball(point((step - (size - 1) / 2) * (2.1 / Math.max(size - 1, 1)), 0, -.15), '#667e90', .22, 'Pol'));
      return parts;
    } };
}
export interface TranslationStep { codon: string; aa: string; anticodon?: string }
export function translationScene(mrna: string, codons: TranslationStep[], start: number): SceneSpec {
  const steps = codons.slice(0, 65);
  const size = steps.length;
  return { description: 'Schematic ribosomal translation: codons pair with tRNA anticodons (3′→5′); stop uses a release factor, not tRNA. No protein folding is inferred.',
    frames: size + 1, extent: 2,
    frameLabel: (f) => f === 0 ? 'Initiation at AUG' : 'Codon ' + f + '/' + size + ': ' + steps[f - 1]?.codon + ' → ' + (steps[f - 1]?.aa === '*' ? 'Stop' : steps[f - 1]?.aa),
    at(frame) {
      const parts: SciencePrimitive[] = [];
      for (let i = 0; i < size * 3; i++) {
        const nt = mrna[start + i] ?? 'N';
        const p = point((i - (size * 3 - 1) / 2) * (2.3 / Math.max(1, size * 3 - 1)), -.35, 0);
        parts.push(ball(p, nucleotideColor(nt), .06, nt));
        if (i) parts.push(line(point((i - 1 - (size * 3 - 1) / 2) * (2.3 / Math.max(1, size * 3 - 1)), -.35, 0), p, '#b6a16b', 2));
      }
      const k = Math.min(size - 1, frame);
      if (size) {
        const x = ((k * 3 + 1) - (size * 3 - 1) / 2) * (2.3 / Math.max(1, size * 3 - 1));
        parts.push(ball(point(x, -.2, .2), '#b1a6b0', .32, 'R'));
        if (frame < size && steps[k].aa !== '*') {
          const anti = steps[k].anticodon ?? '';
          for (let j = 0; j < 3; j++) parts.push(ball(point(x + (j - 1) * .115, -.05, .57), nucleotideColor(anti[j] ?? 'N'), .08, anti[j]));
        }
      }
      const amino = steps.slice(0, frame).filter((s) => s.aa !== '*');
      for (let i = 0; i < amino.length; i++) {
        const a = point(-.9 + i * (1.8 / Math.max(1, amino.length)), .45, .55 + .12 * Math.sin(i));
        parts.push(ball(a, '#38a9a4', .095, amino[i].aa));
        if (i) parts.push(line(point(-.9 + (i - 1) * (1.8 / Math.max(1, amino.length)), .45, .55 + .12 * Math.sin(i - 1)), a, '#578c8b', 3));
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


export interface MolecularAtom { element: string; xyz: V3 }
export interface MolecularBond { a: number; b: number; order: number }
export interface MolecularStructure {
  formula: string; name: string; charge: number; source: string;
  atoms: MolecularAtom[]; bonds: MolecularBond[];
}
/** Molecules have explicit NIST-sourced atom coordinates and connectivity, never inferred from formulas. */
export function moleculeScene(molecule: MolecularStructure): SceneSpec {
  return {
    description: molecule.name + ' (' + molecule.formula + ') · fixed NIST CCCBDB reference geometry in Å. Select atoms to inspect; display is not a trajectory. Source: ' + molecule.source,
    extent: 2.6, frames: 2,
    frameLabel: (f) => f ? 'Space-filling representation (illustrative relative radii)' : 'Ball-and-stick, bonds from explicit source topology',
    at(frame) {
      const parts: SciencePrimitive[] = [];
      if (frame === 0) for (const bond of molecule.bonds) {
        const a = molecule.atoms[bond.a]?.xyz;
        const b = molecule.atoms[bond.b]?.xyz;
        if (!a || !b) continue;
        const repetitions = Math.max(1, Math.min(3, Math.trunc(bond.order)));
        for (let i = 0; i < repetitions; i++) {
          const delta = (i - (repetitions - 1) / 2) * .065;
          const va: V3 = [a[0] + delta, a[1] + delta, a[2]];
          const vb: V3 = [b[0] + delta, b[1] + delta, b[2]];
          parts.push(line(va, vb, '#73889c', 3));
        }
      }
      molecule.atoms.forEach((atom, i) => {
        const radius = frame ? ({ H: .26, C: .36, N: .34, O: .32, S: .44 } as Record<string, number>)[atom.element] ?? .33 : .16;
        parts.push(ball(atom.xyz, elementColor(atom.element), radius, atom.element + (i + 1)));
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
        const offset = (p: V3): V3 => [p[0] + cx, p[1] + cy, p[2]];
        for (const bond of structure.bonds) {
          const a = structure.atoms[bond.a], b = structure.atoms[bond.b];
          if (a && b) result.push(line(offset(a.xyz), offset(b.xyz), '#748aa0', 3));
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
      const count = 1100;
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
export function nucleusScene(z: number, mass: number | null, configuration: string): SceneSpec {
  const full = atomScene(z, mass, 0, configuration);
  return {
    description: 'Schematic nuclear composition. ' + (mass === null ? 'Neutron count is unavailable: only known protons shown.' :
      z + ' protons and ' + (mass - z) + ' neutrons. Spatial nucleon positions are not measured nuclear states.'),
    extent: 1.2,
    at: () => full.at(0).filter((primitive) =>
      primitive.kind === 'ball' && (primitive.color === '#d94b51' || primitive.color === '#8c959f')),
  };
}
