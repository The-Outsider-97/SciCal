// The mathematics of the 3D view: scene normalisation, an orbit camera (z up) with perspective or orthographic projection, shading and a colour map.
// Pure functions, no DOM: a camera movement only calls these again; the sampled geometry is never recomputed.
import { clamp } from './util.js';

export type V3 = [number, number, number];
export interface Bounds3 { xmin: number; xmax: number; ymin: number; ymax: number; zmin: number; zmax: number }
export type Aspect = 'box' | 'equal';
export type Projection = 'perspective' | 'orthographic';

export interface Camera {
  azimuth: number;        // radians, rotation about +z; 0 looks from +x towards the origin
  elevation: number;      // radians above the xy plane
  zoom: number;
  panX: number;           // in view units (the plot box is about one unit wide)
  panY: number;
  projection: Projection;
}

export const DEFAULT_CAMERA: Camera = { azimuth: (-52 * Math.PI) / 180, elevation: (24 * Math.PI) / 180, zoom: 1, panX: 0, panY: 0, projection: 'perspective' };
export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 25;
/** In 'box' mode the plot box is a little lower than it is wide, which is how 3D plots are usually drawn and leaves room for the labels. */
export const BOX_HEIGHT = 0.78;
const MAX_ELEVATION = (89 * Math.PI) / 180;
const EYE_DISTANCE = 3.2;   // the unit box spans about 1.7 across its diagonal, so the eye sits roughly two diagonals away

export const cloneCamera = (c: Camera): Camera => ({ ...c });

export function clampCamera(c: Camera): Camera {
  const az = ((c.azimuth + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;
  return { ...c, azimuth: az, elevation: clamp(c.elevation, -MAX_ELEVATION, MAX_ELEVATION), zoom: clamp(c.zoom, MIN_ZOOM, MAX_ZOOM), panX: clamp(c.panX, -3, 3), panY: clamp(c.panY, -3, 3) };
}

/** Orbit by screen-space drag distances (pixels). A drag across the whole viewport turns the scene by about 180 degrees. */
export function orbit(c: Camera, dxPx: number, dyPx: number, sizePx: number): Camera {
  const k = Math.PI / Math.max(1, sizePx);
  return clampCamera({ ...c, azimuth: c.azimuth - dxPx * k, elevation: c.elevation + dyPx * k });
}

export function panBy(c: Camera, dxPx: number, dyPx: number, sizePx: number): Camera {
  const k = 1 / (0.46 * Math.max(1, sizePx) * c.zoom);
  return clampCamera({ ...c, panX: c.panX + dxPx * k, panY: c.panY - dyPx * k });
}

export const zoomBy = (c: Camera, factor: number): Camera => clampCamera({ ...c, zoom: c.zoom * factor });

// ------------------------------------------------------------------------------------------------------------------ normalisation
export interface Normalizer { center: V3; scale: V3; toUnit(p: V3): V3; fromUnit(u: V3): V3 }

/** Map the data box into a unit box centred on the origin. 'box' stretches each axis to fit; 'equal' keeps true proportions. */
export function normalizer(b: Bounds3, aspect: Aspect): Normalizer {
  const lo: V3 = [b.xmin, b.ymin, b.zmin];
  const hi: V3 = [b.xmax, b.ymax, b.zmax];
  const span = lo.map((l, i) => Math.max(hi[i] - l, 1e-12 * Math.max(1, Math.abs(l), Math.abs(hi[i])))) as V3;
  const widest = Math.max(...span);
  const scale = (aspect === 'equal' ? span.map(() => 1 / widest) : span.map((s, i) => (i === 2 ? BOX_HEIGHT : 1) / s)) as V3;
  const center = lo.map((l, i) => (l + hi[i]) / 2) as V3;
  return {
    center, scale,
    toUnit: (p) => [(p[0] - center[0]) * scale[0], (p[1] - center[1]) * scale[1], (p[2] - center[2]) * scale[2]],
    fromUnit: (u) => [u[0] / scale[0] + center[0], u[1] / scale[1] + center[1], u[2] / scale[2] + center[2]],
  };
}

// ------------------------------------------------------------------------------------------------------------------ projection
export interface Screen { x: number; y: number; depth: number }
export interface Projector {
  project(p: V3): Screen;
  /** Unit vector pointing from the scene towards the viewer, and the camera's right and up axes, in scene coordinates. */
  toViewer: V3; right: V3; up: V3;
}

const dot = (a: V3, b: V3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: V3, b: V3): V3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const unit = (a: V3): V3 => { const n = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / n, a[1] / n, a[2] / n]; };

export function makeProjector(cam: Camera, width: number, height: number): Projector {
  const ce = Math.cos(cam.elevation);
  const toViewer: V3 = [ce * Math.cos(cam.azimuth), ce * Math.sin(cam.azimuth), Math.sin(cam.elevation)];
  const forward: V3 = [-toViewer[0], -toViewer[1], -toViewer[2]];
  const right = unit(cross(forward, [0, 0, 1]));
  const up = cross(right, forward);
  const eye: V3 = [toViewer[0] * EYE_DISTANCE, toViewer[1] * EYE_DISTANCE, toViewer[2] * EYE_DISTANCE];
  const S = 0.46 * Math.min(width, height) * cam.zoom;
  const cx = width / 2;
  const cy = height / 2;
  const persp = cam.projection === 'perspective';
  return {
    toViewer, right, up,
    project(p) {
      const v: V3 = [p[0] - eye[0], p[1] - eye[1], p[2] - eye[2]];
      const xc = dot(v, right);
      const yc = dot(v, up);
      const zf = dot(v, forward);
      // Perspective divides by depth; orthographic uses the scale of the target plane (zf == EYE_DISTANCE),
      // so switching projection does not make the picture jump. Pan is applied on the screen, after the division.
      const k = persp ? EYE_DISTANCE / Math.max(zf, 0.05) : 1;
      return { x: cx + (xc * k + cam.panX) * S, y: cy - (yc * k + cam.panY) * S, depth: zf };
    },
  };
}

// ------------------------------------------------------------------------------------------------------------------ colour
export type RGB = [number, number, number];
// A perceptually ordered ramp (blue-green-yellow, in the manner of viridis) so that colour carries the value of z.
const RAMP: RGB[] = [[68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142], [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37]];

export function colormap(t: number): RGB {
  const x = clamp(Number.isFinite(t) ? t : 0, 0, 1) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(x));
  const f = x - i;
  return [0, 1, 2].map((k) => Math.round(RAMP[i][k] + (RAMP[i + 1][k] - RAMP[i][k]) * f)) as RGB;
}

export function hexToRgb(hex: string): RGB {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return [160, 128, 0];
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** Two-sided diffuse shading with a light fixed to the camera (so the shading follows the view): 0.35 ambient + 0.65 diffuse. */
export function shade(normal: V3, proj: Projector): number {
  const toward = Math.abs(dot(normal, proj.toViewer)) * 0.75 + Math.abs(dot(normal, unit([proj.toViewer[0] + proj.up[0] * 0.8 - proj.right[0] * 0.5, proj.toViewer[1] + proj.up[1] * 0.8 - proj.right[1] * 0.5, proj.toViewer[2] + proj.up[2] * 0.8 - proj.right[2] * 0.5]))) * 0.25;
  return 0.35 + 0.65 * clamp(toward, 0, 1);
}

export const rgbCss = (c: RGB, k = 1, alpha = 1): string => `rgba(${Math.round(clamp(c[0] * k, 0, 255))},${Math.round(clamp(c[1] * k, 0, 255))},${Math.round(clamp(c[2] * k, 0, 255))},${alpha})`;

// ------------------------------------------------------------------------------------------------------------------ cells
/** The same triangulation the exporters use: a cell [a, b, d, c] is the triangles (a, b, d) and (a, d, c). */
export function triangulateCell(cell: [number, number, number, number]): Array<[number, number, number]> {
  const [a, b, d, c] = cell;
  return [[a, b, d], [a, d, c]];
}
