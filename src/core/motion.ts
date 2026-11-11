// The mathematics of motion in the 3D views and the animated scenes: easing, camera tweens, drag momentum, auto-spin, slider sweeps and
// fractional playback frames. Pure functions with no DOM and no clock; the caller supplies elapsed time, so every rule is testable.
import { clamp } from './util.js';
import { clampCamera, type Camera } from './scene3d.js';

export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/** Smooth start and stop (cubic in-out). */
export const easeInOut = (t: number): number => {
  const x = clamp(t, 0, 1);
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
};

/** The signed turn from one angle to another that goes the short way round (result in -pi..pi). */
export function shortestTurn(from: number, to: number): number {
  const d = ((to - from) % (2 * Math.PI) + 3 * Math.PI) % (2 * Math.PI) - Math.PI;
  return d;
}

/**
 * A camera part-way between two views (t = 0 gives `a`, t = 1 gives `b`). The azimuth takes the short way round, the zoom moves in
 * proportion (so zooming 1 -> 4 passes 2 halfway, not 2.5), and the projection switches at the half-way point.
 */
export function tweenCamera(a: Camera, b: Camera, t: number): Camera {
  const e = easeInOut(t);
  if (e >= 1) return clampCamera({ ...b });
  return clampCamera({
    azimuth: a.azimuth + shortestTurn(a.azimuth, b.azimuth) * e,
    elevation: lerp(a.elevation, b.elevation, e),
    zoom: Math.exp(lerp(Math.log(a.zoom), Math.log(b.zoom), e)),
    panX: lerp(a.panX, b.panX, e),
    panY: lerp(a.panY, b.panY, e),
    projection: e < 0.5 ? a.projection : b.projection,
  });
}

/** Duration of a camera move in ms: longer for bigger turns, but never slow. */
export function tweenDuration(a: Camera, b: Camera): number {
  const turn = Math.abs(shortestTurn(a.azimuth, b.azimuth)) + Math.abs(b.elevation - a.elevation);
  return clamp(260 + 180 * turn, 260, 700);
}

// ------------------------------------------------------------------------------------------------------------------ momentum
export interface Spin2 { az: number; el: number }          // radians per second
export const INERTIA_HALF_LIFE_MS = 220;                    // the speed halves every 220 ms
export const INERTIA_MIN_SPEED = 0.05;                      // rad/s below which the camera is considered still
export const INERTIA_MAX_SPEED = 6;                         // a flick never spins faster than about one turn a second

/** Estimate the release velocity from the last few pointer samples (time in ms, position in px), as radians per second. */
export function releaseVelocity(samples: ReadonlyArray<{ t: number; x: number; y: number }>, sizePx: number, now: number, windowMs = 90): Spin2 {
  const recent = samples.filter((s) => now - s.t <= windowMs);
  if (recent.length < 2) return { az: 0, el: 0 };
  const first = recent[0];
  const last = recent[recent.length - 1];
  const dt = (last.t - first.t) / 1000;
  if (dt <= 0.004) return { az: 0, el: 0 };
  const k = Math.PI / Math.max(1, sizePx);                  // the same scale as `orbit`: a drag across the view is half a turn
  const cap = (v: number): number => clamp(v, -INERTIA_MAX_SPEED, INERTIA_MAX_SPEED);
  return { az: cap(-((last.x - first.x) / dt) * k), el: cap(((last.y - first.y) / dt) * k) };
}

/** Advance a coasting camera by `dtMs`; the speed decays exponentially. `done` is true once it has effectively stopped. */
export function coast(cam: Camera, v: Spin2, dtMs: number): { cam: Camera; v: Spin2; done: boolean } {
  const dt = Math.max(0, Math.min(dtMs, 100)) / 1000;      // a long pause (a tab in the background) must not fling the scene
  const decay = Math.pow(0.5, (dt * 1000) / INERTIA_HALF_LIFE_MS);
  const next = clampCamera({ ...cam, azimuth: cam.azimuth + v.az * dt, elevation: cam.elevation + v.el * dt });
  const maxElevation = clampCamera({ ...cam, elevation: 10 }).elevation;       // the camera's own limit, just short of straight up
  const hitTop = Math.abs(next.elevation) >= maxElevation - 1e-9;
  const nv = { az: v.az * decay, el: hitTop ? 0 : v.el * decay };
  return { cam: next, v: nv, done: Math.hypot(nv.az, nv.el) < INERTIA_MIN_SPEED };
}

/** Turn about the vertical axis at `rate` radians per second (one revolution in about 30 s by default). */
export const AUTO_SPIN_RATE = (2 * Math.PI) / 30;
export function spinStep(cam: Camera, dtMs: number, rate = AUTO_SPIN_RATE): Camera {
  const dt = Math.max(0, Math.min(dtMs, 100)) / 1000;
  return clampCamera({ ...cam, azimuth: cam.azimuth + rate * dt });
}

// ------------------------------------------------------------------------------------------------------------------ sliders
/** A back-and-forth sweep: `phase` runs 0..1 over `periodMs`, and the value goes min -> max -> min as a triangle wave (smoothed at the ends). */
export function sweepValue(min: number, max: number, elapsedMs: number, periodMs = 6000): number {
  const phase = ((elapsedMs % periodMs) + periodMs) % periodMs / periodMs;
  const tri = phase < 0.5 ? phase * 2 : 2 - phase * 2;
  return lerp(min, max, easeInOut(tri));
}

/** The elapsed time at which `sweepValue` passes through `value` on its way up, so a sweep can start from where the slider already is. */
export function sweepStart(min: number, max: number, value: number, periodMs = 6000): number {
  const span = max - min;
  const f = span === 0 ? 0 : clamp((value - min) / span, 0, 1);
  let lo = 0;
  let hi = 1;
  for (let i = 0; i < 40; i++) { const mid = (lo + hi) / 2; if (easeInOut(mid) < f) lo = mid; else hi = mid; }
  return ((lo + hi) / 2) * (periodMs / 2);
}

/** Snap a value to the slider's step, inside its bounds. */
export function snapToStep(value: number, min: number, max: number, step: number): number {
  if (!(step > 0)) return clamp(value, min, max);
  return clamp(min + Math.round((value - min) / step) * step, min, max);
}

// ------------------------------------------------------------------------------------------------------------------ playback
/**
 * Advance a (fractional) playback position. `rate` is in frames per second. Returns the new position and whether playback reached the end
 * (when `loop` is on the position wraps and `ended` stays false).
 */
export function advancePlayback(frame: number, dtMs: number, rate: number, total: number, loop: boolean): { frame: number; ended: boolean } {
  const last = Math.max(0, total - 1);
  const dt = Math.max(0, Math.min(dtMs, 250)) / 1000;
  let f = frame + rate * dt;
  if (f < last) return { frame: f, ended: false };
  if (!loop || last === 0) return { frame: last, ended: true };
  f = f % (last + 1);
  return { frame: f, ended: false };
}

/** The two whole frames around a fractional position, and how far between them. */
export function frameBlend(frame: number, total: number): { a: number; b: number; t: number } {
  const last = Math.max(0, total - 1);
  const f = clamp(Number.isFinite(frame) ? frame : 0, 0, last);
  const a = Math.floor(f);
  return { a, b: Math.min(last, a + 1), t: f - a };
}

/** Depth cue: 1 for the nearest point of the scene and `floor` for the farthest, from the projected depths. */
export function depthFade(depth: number, near: number, far: number, floor = 0.45): number {
  if (!(far > near)) return 1;
  return lerp(1, floor, clamp((depth - near) / (far - near), 0, 1));
}
