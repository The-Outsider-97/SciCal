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
  selectionDescription?(selection: SceneSelection): string;
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
  let pickedGroup = '';
  let lastSelection: SceneSelection | null = null;
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
  const focusButton = button('Focus selection', () => { if (lastSelection) focusOn(lastSelection.position, 2.8); });
  focusButton.disabled = true;
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
  controls.append(reset, focusButton, exportBtn);
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
          if (picked === selection.id || (pickedGroup && shape.group === pickedGroup)) {
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
        if ((picked && picked === (shape.id ?? shape.label)) || (pickedGroup && shape.group === pickedGroup)) {
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
        pickedGroup = choice.selection.group ?? '';
        lastSelection = choice.selection;
        focusButton.disabled = false;
        info.textContent = (spec.selectionDescription?.(choice.selection) ??
          ('Selected ' + choice.selection.label + (pickedGroup ? ' · group: ' + pickedGroup : ''))) +
          ' · ' + spec.description;
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
/**
 * Close-packed FCC lattice. Centre-to-centre nearest distance = 2r exactly, so schematic
 * nucleons cannot interpenetrate. The finite cluster is centred by its geometric centroid.
 * The lattice is NOT a wavefunction, measured nuclear distribution or shell-model solution.
 */
export const NUCLEON_RADIUS = .115;
export const EDUCATIONAL_ELECTRON_RADIUS = .055 * .8; // requested 20% reduction
const nucleusCache = new Map<number, V3[]>();
export function packedNucleus(count: number, radius = NUCLEON_RADIUS): V3[] {
  if (!Number.isInteger(count) || count < 0 || count > 400) throw new RangeError('Nuclear visualization supports 0–400 nucleons');
  if (count === 0) return [];
  if (count === 1) return [[0, 0, 0]];
  const existing = nucleusCache.get(count);
  if (existing && radius === NUCLEON_RADIUS) return existing;
  const half = Math.max(3, Math.ceil(Math.cbrt(count) * 1.65));
  const candidates: Array<{ x: number; y: number; z: number; norm: number }> = [];
  for (let x = -half; x <= half; x++)
    for (let y = -half; y <= half; y++)
      for (let z = -half; z <= half; z++)
        if (Math.abs(x + y + z) % 2 === 0)
          candidates.push({ x, y, z, norm: x * x + y * y + z * z });
  candidates.sort((a, b) => a.norm - b.norm || a.z - b.z || a.y - b.y || a.x - b.x);
  const selected = candidates.slice(0, count);
  const scale = radius * Math.SQRT2;
  const centroid = [
    selected.reduce((sum, p) => sum + p.x, 0) / count,
    selected.reduce((sum, p) => sum + p.y, 0) / count,
    selected.reduce((sum, p) => sum + p.z, 0) / count,
  ];
  const positions = selected.map((p): V3 => [
    (p.x - centroid[0]) * scale,
    (p.y - centroid[1]) * scale,
    (p.z - centroid[2]) * scale,
  ]);
  if (radius === NUCLEON_RADIUS) nucleusCache.set(count, positions);
  return positions;
}
const norm3 = (p: V3): number => Math.hypot(p[0], p[1], p[2]);
const add3 = (a: V3, b: V3): V3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const multiply3 = (p: V3, scale: number): V3 => [p[0] * scale, p[1] * scale, p[2] * scale];
const cross3 = (a: V3, b: V3): V3 => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
];
const unit3 = (p: V3): V3 => multiply3(p, 1 / Math.max(1e-12, norm3(p)));
export function nucleusParticles(z: number, mass: number | null): SciencePrimitive[] {
  const total = mass ?? z; // missing isotope is *never* replaced by rounded atomic weight
  const positions = packedNucleus(total);
  return positions.map((p, i) => {
    const proton = mass === null || Math.floor((i + 1) * z / total) > Math.floor(i * z / total);
    const serial = proton ? Math.floor((i + 1) * z / total) : i + 1 - Math.floor((i + 1) * z / total);
    return { kind: 'ball', p, r: NUCLEON_RADIUS, color: proton ? '#d94b51' : '#8c959f',
      label: proton ? 'p+' : 'n', id: (proton ? 'proton-' : 'neutron-') + serial, group: 'nucleus' };
  });
}
export interface ElectronOrbit { shell: number; index: number; radius: number; phase: number; u: V3; v: V3; id: string }
export function electronOrbits(shells: number[], nuclearEnvelope: number): ElectronOrbit[] {
  const result: ElectronOrbit[] = [];
  const base = Math.max(.70, nuclearEnvelope + .42);
  let serial = 0;
  const total = shells.reduce((sum, n) => sum + n, 0);
  shells.forEach((count, shell) => {
    for (let i = 0; i < count; i++) {
      const azimuth = (serial + 1) * 2.399963229728653;
      const inclination = Math.acos(1 - 2 * (serial + .5) / Math.max(1, total));
      const normal: V3 = [Math.sin(inclination) * Math.cos(azimuth),
        Math.sin(inclination) * Math.sin(azimuth), Math.cos(inclination)];
      const reference: V3 = Math.abs(normal[2]) > .95 ? [0, 1, 0] : [0, 0, 1];
      const u = unit3(cross3(normal, reference));
      const v = unit3(cross3(normal, u));
      result.push({ shell: shell + 1, index: i, radius: base + shell * .46 + i * .012,
        phase: (i / Math.max(1, count)) * 2 * Math.PI + serial * .19, u, v,
        id: 'electron-' + (serial + 1) });
      serial++;
    }
  });
  return result;
}
export function atomScene(z: number, mass: number | null, charge: number, configuration: string): SceneSpec {
  const eCount = z - charge;
  const shells = electronShells(configuration, eCount);
  const core = nucleusParticles(z, mass);
  const envelope = core.reduce((max, p) => p.kind === 'ball' ? Math.max(max, norm3(p.p) + p.r) : max, 0);
  const orbits = electronOrbits(shells, envelope);
  const maxOrbit = orbits.reduce((max, p) => Math.max(max, p.radius), envelope);
  const countNote = mass === null ? 'Isotope not available: neutron count and complete nucleus are unknown.' :
    z + ' protons, ' + (mass - z) + ' neutrons';
  const paths: SciencePrimitive[] = [];
  for (const o of orbits) {
    const samples = 48;
    let last: V3 = add3(multiply3(o.u, Math.cos(o.phase) * o.radius), multiply3(o.v, Math.sin(o.phase) * o.radius));
    for (let j = 1; j <= samples; j++) {
      const angle = o.phase + j * 2 * Math.PI / samples;
      const next = add3(multiply3(o.u, Math.cos(angle) * o.radius), multiply3(o.v, Math.sin(angle) * o.radius));
      paths.push({ kind: 'line', a: last, b: next, color: '#71889f', width: .9, group: o.id });
      last = next;
    }
  }
  return {
    description: 'Educational individualized electron paths, NOT quantum-mechanical trajectories. ' + countNote +
      '. ' + eCount + ' electrons; ionic shell assignment is illustrative.',
    frames: 90, extent: Math.max(2.35, maxOrbit + .4),
    at(frame) {
      const parts: SciencePrimitive[] = [...paths, ...core];
      for (const o of orbits) {
        const angle = o.phase + frame / 90 * 2 * Math.PI * (.5 + o.shell * .08);
        const p = add3(multiply3(o.u, Math.cos(angle) * o.radius), multiply3(o.v, Math.sin(angle) * o.radius));
        parts.push({ kind: 'ball', p, color: '#287cce', r: EDUCATIONAL_ELECTRON_RADIUS,
          label: 'e−', id: o.id, group: 'shell-' + o.shell });
      }
      return parts;
    },
    frameLabel: (f) => 'Schematic electron-path phase ' + (f + 1) + '/90',
  };
}
// B-form DNA is an approximate **geometric reference**, not a nucleotide-resolved atomistic model.
// Rise 0.34 nm and about 10.5 bp / turn (sequence and environmental conditions vary).
export const DNA_HELIX = Object.freeze({ riseNm: .34, bpPerTurn: 10.5, radiusNm: 1.0, strandAngularOffset: Math.PI * .80 });
const rod = (a: V3, b: V3, color: string, r: number, label?: string, id?: string, group?: string): SciencePrimitive =>
  ({ kind: 'cylinder', a, b, color, r, label, id, group });
const blend3 = (a: V3, b: V3, t: number): V3 =>
  [a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t, a[2] * (1 - t) + b[2] * t];
const dnaComplement: Record<string, string> = { A: 'T', T: 'A', C: 'G', G: 'C', N: 'N' };
export function dnaHelixPosition(i: number, size: number, strand: 1 | -1 = 1, bubbleIndex = -1000): V3 {
  const x = (i - (size - 1) / 2) * DNA_HELIX.riseNm;
  const theta = (i / DNA_HELIX.bpPerTurn) * 2 * Math.PI +
    (strand < 0 ? DNA_HELIX.strandAngularOffset : 0);
  const bubble = 1 + .65 * Math.max(0, 1 - Math.abs(i - bubbleIndex) / 2.4);
  const rad = DNA_HELIX.radiusNm * bubble;
  return [x, Math.cos(theta) * rad, Math.sin(theta) * rad];
}
/** Generates continuous round-capped sugar–phosphate tubes and color-coded base rods. */
export function dnaPrimitives(sequence: string, mode = 'full', bubble = -1000): SciencePrimitive[] {
  const size = sequence.length;
  const withBackbone = mode !== 'bases';
  const withBases = mode !== 'backbone';
  const showHydrogen = mode === 'hydrogen';
  const parts: SciencePrimitive[] = [];
  if (withBackbone && size > 1) {
    const samples = (size - 1) * 8;
    for (let j = 1; j <= samples; j++) {
      const i0 = (j - 1) / 8, i1 = j / 8;
      for (const strand of [1, -1] as const)
        parts.push(rod(dnaHelixPosition(i0, size, strand, bubble), dnaHelixPosition(i1, size, strand, bubble),
          strand === 1 ? '#7da79e' : '#a8a1be', .082, undefined, undefined, strand === 1 ? 'coding' : 'template'));
    }
  }
  if (withBases) {
    for (let i = 0; i < size; i++) {
      const a = dnaHelixPosition(i, size, 1, bubble);
      const b = dnaHelixPosition(i, size, -1, bubble);
      const open = Math.abs(i - bubble) < 2.5;
      const codon = 'codon-' + (Math.floor(i / 3) + 1);
      // Deliberately leave a short inter-base gap for schematic noncovalent H bonds.
      const innerA = blend3(a, b, open ? .28 : .455);
      const innerB = blend3(b, a, open ? .28 : .455);
      parts.push(rod(a, innerA, nucleotideColor(sequence[i]), .12,
        sequence[i] + ' · coding · position ' + (i + 1), 'dna-coding-' + (i + 1), codon));
      const complement = dnaComplement[sequence[i]] ?? 'N';
      parts.push(rod(b, innerB, nucleotideColor(complement), .12,
        complement + ' · template · position ' + (i + 1), 'dna-template-' + (i + 1), codon));
      if (showHydrogen && !open && complement !== 'N') {
        const pairs = sequence[i] === 'C' || sequence[i] === 'G' ? 3 : 2;
        const centre = blend3(innerA, innerB, .5);
        for (let k = 0; k < pairs; k++) {
          const dx = (k - (pairs - 1) / 2) * .09;
          const p: V3 = [innerA[0] + dx, innerA[1], innerA[2]];
          const q: V3 = [innerB[0] + dx, innerB[1], innerB[2]];
          void centre;
          parts.push({ kind: 'line', a: p, b: q, color: '#cbd4df', width: 1, group: codon });
        }
      }
    }
  }
  return parts;
}
export function dnaScene(sequence: string): SceneSpec {
  const seq = sequence.slice(0, 80);
  return {
    description: 'Educational right-handed B-DNA: ~0.34 nm rise and 10.5 bp/turn. Coding 5′→3′ left–right; complementary template 3′→5′. ' +
      'Continuous sugar–phosphate tubes and separate cylindrical nucleobases. Showing ' + seq.length + ' base pairs.',
    extent: Math.max(2.45, seq.length * DNA_HELIX.riseNm * .35),
    modes: [{ id: 'full', label: 'Backbones + bases' }, { id: 'hydrogen', label: '+ schematic hydrogen bonds' },
      { id: 'backbone', label: 'Backbones only' }, { id: 'bases', label: 'Cylindrical bases only' }],
    at: (_frame, mode = 'full') => dnaPrimitives(seq, mode),
  };
}
export function rnaBackbonePosition(i: number, size: number): V3 {
  // Single-strand pedagogical helix, *not* an inferred RNA secondary structure.
  const x = (i - (size - 1) / 2) * .34;
  const theta = i * .50;
  return [x, .72 * Math.cos(theta), .72 * Math.sin(theta)];
}
export function rnaPrimitives(sequence: string, mode = 'full'): SciencePrimitive[] {
  const parts: SciencePrimitive[] = [];
  const size = sequence.length;
  if (mode !== 'bases' && size > 1) {
    for (let j = 1; j <= (size - 1) * 8; j++) {
      const p = rnaBackbonePosition((j - 1) / 8, size), q = rnaBackbonePosition(j / 8, size);
      parts.push(rod(p, q, '#ad9cce', .09, undefined, undefined, 'rna-backbone'));
    }
  }
  if (mode !== 'backbone') for (let i = 0; i < size; i++) {
    const backbone = rnaBackbonePosition(i, size);
    const radial: V3 = [0, Math.cos(i * .50), Math.sin(i * .50)];
    const end = add3(backbone, multiply3(radial, .52));
    parts.push(rod(backbone, end, nucleotideColor(sequence[i]), .115,
      sequence[i] + ' · RNA · position ' + (i + 1), 'rna-' + (i + 1), 'codon-' + (Math.floor(i / 3) + 1)));
  }
  return parts;
}
export function rnaScene(sequence: string): SceneSpec {
  const seq = sequence.slice(0, 80);
  return {
    description: 'RNA single strand with continuous sugar–phosphate tube and cylindrical nucleobases; 5′→3′ left to right. ' +
      'Illustrative helical path, NOT a predicted RNA fold. Showing ' + seq.length + ' bases.',
    extent: Math.max(2.20, seq.length * .34 * .35),
    modes: [{ id: 'full', label: 'Backbone + bases' }, { id: 'backbone', label: 'Backbone only' },
      { id: 'bases', label: 'Bases only' }],
    at: (_frame, mode = 'full') => rnaPrimitives(seq, mode),
  };
}
export function transcriptionScene(coding: string, transcript: string): SceneSpec {
  const size = Math.min(80, coding.length);
  const displayCoding = coding.slice(0, size), displayRna = transcript.slice(0, size);
  return {
    description: 'Schematic RNA polymerase moves along DNA template 3′→5′ and synthesizes RNA 5′→3′. ' +
      'DNA strands open locally and reanneal. This does not simulate enzyme kinetics or promoters.',
    frames: size + 1, extent: Math.max(2.6, size * DNA_HELIX.riseNm * .35),
    frameLabel: (f) => f + '/' + size + ' nucleotides transcribed' + (coding.length > size ? ' (preview capped)' : ''),
    at(step) {
      const parts = dnaPrimitives(displayCoding, 'full', step < size ? step : -1000);
      for (let i = 0; i < step; i++) {
        const x = (i - (size - 1) / 2) * DNA_HELIX.riseNm;
        const current: V3 = [x, -1.6, -1.15];
        const end: V3 = [x, -1.98, -1.15 + .12 * Math.sin(i * .5)];
        parts.push(rod(current, end, nucleotideColor(displayRna[i]), .09,
          displayRna[i] + ' · transcript · position ' + (i + 1), 'transcript-' + i, 'mrna'));
        if (i) {
          const prev: V3 = [(i - 1 - (size - 1) / 2) * DNA_HELIX.riseNm, -1.6, -1.15];
          parts.push(rod(prev, current, '#b1a167', .075, undefined, undefined, 'mrna-backbone'));
        }
      }
      if (step < size) {
        const position: V3 = [(step - (size - 1) / 2) * DNA_HELIX.riseNm, -0.3, -.1];
        parts.push({ kind: 'ball', p: position, r: .32, color: '#8197a7',
          label: 'Pol', id: 'rna-polymerase', group: 'enzyme' });
      }
      return parts;
    },
  };
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
export type MoleculeDisplay = 'ball-stick' | 'space' | 'wire';
const vdwRadii: Record<string, number> = { H: 1.2, C: 1.7, N: 1.55, O: 1.52, F: 1.47, S: 1.80, Cl: 1.75 };
const ballStickRadii: Record<string, number> = { H: .16, C: .23, N: .22, O: .21, F: .20, S: .26, Cl: .25 };
const sub3 = (a: V3, b: V3): V3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
function moleculeCenter(molecule: MolecularStructure): V3 {
  const count = molecule.atoms.length;
  return [
    molecule.atoms.reduce((s, a) => s + a.xyz[0], 0) / count,
    molecule.atoms.reduce((s, a) => s + a.xyz[1], 0) / count,
    molecule.atoms.reduce((s, a) => s + a.xyz[2], 0) / count,
  ];
}
function moleculeBound(molecule: MolecularStructure): number {
  const center = moleculeCenter(molecule);
  return Math.max(.5, ...molecule.atoms.map((atom) =>
    norm3(sub3(atom.xyz, center)) + (vdwRadii[atom.element] ?? 1.7)));
}
export interface MoleculePlacement {
  molecule: MolecularStructure;
  id: string;
  species: string;
  index: number;
  origin: V3;
  radius: number;
}
/** Deterministic 2D row packing of enclosing 3D van-der-Waals bounding spheres. */
export function layoutMoleculeInstances(species: StructuredReactionSpecies[]): MoleculePlacement[] {
  const list: MoleculePlacement[] = [];
  for (const sp of species) {
    if (!sp.structure) continue;
    for (let i = 0; i < sp.coefficient; i++) {
      const molecule = sp.structure;
      list.push({ molecule, id: sp.species + '-' + (i + 1), species: sp.species,
        index: i + 1, origin: [0, 0, 0], radius: moleculeBound(molecule) });
    }
  }
  if (!list.length) return list;
  const columns = Math.max(1, Math.ceil(Math.sqrt(list.length)));
  const rows: MoleculePlacement[][] = [];
  for (let i = 0; i < list.length; i += columns) rows.push(list.slice(i, i + columns));
  const gap = .60;
  const rowRadii = rows.map((row) => Math.max(...row.map((m) => m.radius)));
  const rowHeights = rowRadii.map((r) => r * 2);
  const totalHeight = rowHeights.reduce((a, b) => a + b, 0) + gap * (rows.length - 1);
  let cursorY = -totalHeight / 2;
  rows.forEach((row, j) => {
    const width = row.reduce((s, m) => s + 2 * m.radius, 0) + gap * (row.length - 1);
    let cursorX = -width / 2;
    for (const item of row) {
      item.origin = [cursorX + item.radius, cursorY + rowRadii[j], 0];
      cursorX += item.radius * 2 + gap;
    }
    cursorY += rowHeights[j] + gap;
  });
  return list;
}
export function placementsDoNotOverlap(places: MoleculePlacement[], clearance = 0): boolean {
  for (let i = 0; i < places.length; i++) for (let j = i + 1; j < places.length; j++)
    if (norm3(sub3(places[i].origin, places[j].origin)) + 1e-8 <
      places[i].radius + places[j].radius + clearance) return false;
  return true;
}
function moleculePrimitives(molecule: MolecularStructure, location: V3, mode: MoleculeDisplay, group: string): SciencePrimitive[] {
  const parts: SciencePrimitive[] = [];
  const center = moleculeCenter(molecule);
  const placed = (p: V3): V3 => add3(sub3(p, center), location);
  const bonds = molecule.bonds;
  if (mode !== 'space') for (let j = 0; j < bonds.length; j++) {
    const bond = bonds[j];
    const a = molecule.atoms[bond.a], b = molecule.atoms[bond.b];
    if (!a || !b) continue;
    const start = placed(a.xyz), end = placed(b.xyz);
    const tangent = unit3(sub3(end, start));
    const basis: V3 = Math.abs(tangent[2]) > .95 ? [0, 1, 0] : [0, 0, 1];
    const perpendicular = unit3(cross3(tangent, basis));
    const repetitions = Math.min(3, Math.max(1, bond.order));
    for (let k = 0; k < repetitions; k++) {
      const offset = multiply3(perpendicular, (k - (repetitions - 1) / 2) * .13);
      const p = add3(start, offset), q = add3(end, offset);
      parts.push(mode === 'wire' ? { kind: 'line', a: p, b: q, color: '#adbac9', width: 1.3, group } :
        rod(p, q, '#7b8fa5', .053, undefined, undefined, group));
    }
  }
  molecule.atoms.forEach((atom, i) => {
    const radius = mode === 'space' ? vdwRadii[atom.element] ?? 1.7 :
      mode === 'wire' ? .065 : ballStickRadii[atom.element] ?? .24;
    parts.push({ kind: 'ball', p: placed(atom.xyz), r: radius,
      color: elementColor(atom.element), label: atom.element + (i + 1),
      id: group + '-atom-' + (i + 1), group });
  });
  return parts;
}
const moleculeModes = [
  { id: 'ball-stick', label: 'Ball-and-stick' }, { id: 'space', label: 'Space-filling (van der Waals)' },
  { id: 'wire', label: 'Wireframe' },
];
/** Only explicit, externally sourced geometry is ever rendered as a connected molecule. */
export function moleculeScene(molecule: MolecularStructure): SceneSpec {
  const bound = moleculeBound(molecule);
  return {
    description: molecule.name + ' (' + molecule.formula + '). Explicit NIST-sourced fixed coordinates and bond topology in Å. ' +
      'Space-filling van der Waals volumes may overlap by design. Source: ' + molecule.source,
    extent: Math.max(2.4, bound + .35), modes: moleculeModes,
    at: (_frame, mode = 'ball-stick') => moleculePrimitives(molecule, [0, 0, 0], mode as MoleculeDisplay, molecule.formula + '-1'),
  };
}
export interface StructuredReactionSpecies extends StoichSpecies { structure: MolecularStructure | null }
export function molecularReactionScene(reactants: StructuredReactionSpecies[], products: StructuredReactionSpecies[]): SceneSpec {
  const layouts = [layoutMoleculeInstances(reactants), layoutMoleculeInstances(products)];
  const extent = Math.max(2.5, ...layouts.flatMap((layout) =>
    layout.map((p) => norm3(p.origin) + p.radius + .4)));
  return {
    description: 'Molecules are separate, deterministic, collision-free bounding-sphere instances with explicit bonds and verified atomic inventories. ' +
      'Before/after views are NOT reaction trajectories, intermediates or mechanisms. Select an atom for molecule identity.',
    frames: 2, extent, modes: moleculeModes,
    frameLabel: (f) => (f ? 'Products: ' : 'Reactants: ') + layouts[f].length + ' distinct molecules',
    at(frame, mode = 'ball-stick') {
      return layouts[frame].flatMap((place) => moleculePrimitives(place.molecule, place.origin, mode as MoleculeDisplay,
        (frame ? 'product-' : 'reactant-') + place.id));
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
  void configuration;
  return {
    description: 'Schematic nuclear composition. ' + (mass === null ? 'Neutron count is unavailable: only known protons shown.' :
      z + ' protons and ' + (mass - z) + ' neutrons. Spatial nucleon positions are not measured nuclear states.'),
    extent: 1.2,
    at: () => nucleusParticles(z, mass),
  };
}


/** Valence-quark-only schematic, not a spatial/QCD wavefunction or gluon trajectory. */
export function valenceQuarkScene(kind: 'proton' | 'neutron'): SceneSpec {
  const flavors: Array<'u' | 'd'> = kind === 'proton' ? ['u', 'u', 'd'] : ['u', 'd', 'd'];
  const positions: V3[] = [[-.45, -.25, 0], [.45, -.25, 0], [0, .5, 0]];
  return {
    description: (kind === 'proton' ? 'Proton (uud)' : 'Neutron (udd)') +
      ' valence quarks. Quarks are confined; QCD also contains gluons and sea-quark pairs. ' +
      'Distances and gluon connections are conceptual, NOT measured classical trajectories.',
    extent: 1.65,
    at: () => {
      const particles: SciencePrimitive[] = [];
      for (let i = 0; i < positions.length; i++) for (let j = i + 1; j < positions.length; j++)
        particles.push({ kind: 'line', a: positions[i], b: positions[j],
          color: '#d7ba59', width: 3, group: 'strong-interaction' });
      positions.forEach((p, i) => particles.push({
        kind: 'ball', p, r: .26, color: flavors[i] === 'u' ? '#aa70dd' : '#67b5a4',
        label: flavors[i], id: 'quark-' + (i + 1), group: 'valence-quarks',
      }));
      return particles;
    },
  };
}
