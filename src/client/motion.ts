// Camera motion for the 3D views: eased moves between views, momentum after a flick, and slow auto-spin. One animation frame loop per view,
// started only while something moves, stopped as soon as the person touches the scene, and never started when reduced motion is requested.
import { cloneCamera, type Camera } from '../core/scene3d.js';
import { coast, spinStep, tweenCamera, tweenDuration, type Spin2 } from '../core/motion.js';

/** True when the person (or the system) asked for less motion: the setting in SciCal, or the operating system's switch. */
export function reducedMotion(): boolean {
  if (typeof document !== 'undefined' && document.documentElement.dataset.motion === 'reduce') return true;
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export interface MotionHost {
  get(): Camera;
  set(cam: Camera): void;
  /** Paint the scene with the camera as it is now; `moving` is true while the camera is animated (a cheaper pass may be used). */
  redraw(moving: boolean): void;
  /** False once the view has left the page, so the loop ends by itself. */
  alive(): boolean;
}

type Mode = 'idle' | 'tween' | 'coast' | 'spin';

export class CameraMotion {
  private mode: Mode = 'idle';
  private raf = 0;
  private last = 0;
  private from: Camera | null = null;
  private to: Camera | null = null;
  private started = 0;
  private duration = 0;
  private velocity: Spin2 = { az: 0, el: 0 };
  private spinning = false;
  onChange: (() => void) | null = null;

  constructor(private readonly host: MotionHost) {}

  get isSpinning(): boolean { return this.spinning; }
  get isMoving(): boolean { return this.mode !== 'idle'; }

  /** Move to `target` with an eased tween (or at once under reduced motion). */
  animateTo(target: Camera, ms?: number): void {
    this.cancelFrame();
    const now = this.host.get();
    if (reducedMotion()) { this.mode = 'idle'; this.host.set(cloneCamera(target)); this.host.redraw(false); return; }
    this.from = cloneCamera(now);
    this.to = cloneCamera(target);
    this.duration = ms ?? tweenDuration(now, target);
    this.started = 0;
    this.mode = 'tween';
    this.schedule();
  }

  /** Keep turning after a flick; `v` is in radians per second. Ignored under reduced motion or when the flick is too slow to matter. */
  fling(v: Spin2): void {
    if (reducedMotion() || Math.hypot(v.az, v.el) < 0.25) { this.stop(); return; }
    this.cancelFrame();
    this.velocity = { ...v };
    this.mode = 'coast';
    this.schedule();
  }

  /** Start or stop the slow turn about the vertical axis. Returns whether the spin is now on. */
  setSpin(on: boolean): boolean {
    const want = on && !reducedMotion();
    this.spinning = want;
    if (want) { this.cancelFrame(); this.mode = 'spin'; this.schedule(); } else if (this.mode === 'spin') this.stop();
    this.onChange?.();
    return want;
  }

  /** The person took hold of the scene: stop a tween or a coast. A spin the person asked for continues once they let go. */
  interrupt(): void {
    if (this.mode === 'tween' || this.mode === 'coast') { this.cancelFrame(); this.mode = 'idle'; this.host.redraw(false); }
    else if (this.mode === 'spin') { this.cancelFrame(); this.mode = 'idle'; }
  }

  /** After a drag ends: resume the spin if it was on. */
  resume(): void {
    if (this.spinning && this.mode === 'idle') { this.mode = 'spin'; this.schedule(); }
  }

  stop(): void {
    this.cancelFrame();
    const was = this.mode;
    this.mode = 'idle';
    if (this.spinning) { this.spinning = false; this.onChange?.(); }
    if (was !== 'idle') this.host.redraw(false);
  }

  private cancelFrame(): void { if (this.raf) cancelAnimationFrame(this.raf); this.raf = 0; this.last = 0; }
  private schedule(): void { if (!this.raf) this.raf = requestAnimationFrame((t) => this.frame(t)); }

  private frame(t: number): void {
    this.raf = 0;
    if (!this.host.alive()) { this.mode = 'idle'; this.spinning = false; return; }
    const dt = this.last ? t - this.last : 16;
    this.last = t;
    if (this.mode === 'tween' && this.from && this.to) {
      if (!this.started) this.started = t;
      const k = Math.min(1, (t - this.started) / Math.max(1, this.duration));
      this.host.set(tweenCamera(this.from, this.to, k));
      if (k >= 1) { this.mode = this.spinning ? 'spin' : 'idle'; this.last = 0; this.host.redraw(false); } else this.host.redraw(true);
    } else if (this.mode === 'coast') {
      const r = coast(this.host.get(), this.velocity, dt);
      this.velocity = r.v;
      this.host.set(r.cam);
      if (r.done) { this.mode = this.spinning ? 'spin' : 'idle'; this.last = 0; this.host.redraw(false); } else this.host.redraw(true);
    } else if (this.mode === 'spin') {
      this.host.set(spinStep(this.host.get(), dt));
      this.host.redraw(true);
    }
    if (this.mode !== 'idle') this.schedule();
  }
}
