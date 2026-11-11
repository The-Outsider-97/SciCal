import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT_CAMERA, type Camera } from '../src/core/scene3d.js';
import {
  advancePlayback, coast, depthFade, easeInOut, frameBlend, INERTIA_MAX_SPEED, releaseVelocity, shortestTurn, snapToStep, spinStep, sweepStart, sweepValue, tweenCamera, tweenDuration,
} from '../src/core/motion.js';
import { laneOffsets, modeOf, atomScene, dnaScene, moleculeScene, orbitalAngularScene } from '../src/client/science3d.js';

const close = (a: number, b: number, eps = 1e-9): void => assert.ok(Math.abs(a - b) <= eps, `${a} vs ${b}`);
const cam = (over: Partial<Camera> = {}): Camera => ({ ...DEFAULT_CAMERA, ...over });

test('easing starts and ends at rest and never leaves 0..1', () => {
  close(easeInOut(0), 0); close(easeInOut(1), 1); close(easeInOut(0.5), 0.5);
  assert.ok(easeInOut(0.1) < 0.1, 'slow at the start');
  assert.ok(easeInOut(-3) === 0 && easeInOut(7) === 1);
});

test('shortestTurn goes the short way round the circle', () => {
  close(shortestTurn(0, Math.PI / 2), Math.PI / 2);
  close(shortestTurn(Math.PI * 0.9, -Math.PI * 0.9), Math.PI * 0.2);
  close(shortestTurn(-Math.PI * 0.9, Math.PI * 0.9), -Math.PI * 0.2);
  assert.ok(Math.abs(shortestTurn(0.3, 0.3 + 2 * Math.PI)) < 1e-9);
});

test('tweenCamera reaches both ends exactly, takes the short azimuth path and zooms in proportion', () => {
  const a = cam({ azimuth: 3, zoom: 1, panX: 0 });
  const b = cam({ azimuth: -3, zoom: 4, panX: 1, elevation: 0.2, projection: 'orthographic' });
  assert.deepEqual(tweenCamera(a, b, 0), { ...a });
  const end = tweenCamera(a, b, 1);
  close(end.azimuth, b.azimuth); close(end.zoom, 4); assert.equal(end.projection, 'orthographic');
  const mid = tweenCamera(a, b, 0.5);
  close(mid.zoom, 2, 1e-9);                                    // 1 -> 4 passes 2, not 2.5
  assert.ok(Math.abs(shortestTurn(a.azimuth, mid.azimuth)) < Math.abs(shortestTurn(a.azimuth, b.azimuth)) + 1e-9);
  assert.ok(Math.abs(mid.azimuth) > 2.9, 'went over the back of the circle (about 3.14), not through zero');
  assert.equal(tweenCamera(a, b, 0.4).projection, 'perspective');
});

test('tween duration is short for small moves and capped for big ones', () => {
  const d1 = tweenDuration(cam(), cam({ azimuth: DEFAULT_CAMERA.azimuth + 0.05 }));
  const d2 = tweenDuration(cam(), cam({ azimuth: DEFAULT_CAMERA.azimuth + 3, elevation: 1 }));
  assert.ok(d1 >= 260 && d1 < d2 && d2 <= 700);
});

test('releaseVelocity reads a flick, ignores a stopped hand and is capped', () => {
  const now = 1000;
  const flick = [{ t: 950, x: 100, y: 200 }, { t: 975, x: 130, y: 200 }, { t: 1000, x: 160, y: 200 }];
  const v = releaseVelocity(flick, 300, now);
  assert.ok(v.az < 0, 'dragging right turns the scene the way orbit does (azimuth falls)');
  close(v.el, 0);
  assert.ok(Math.abs(v.az) <= INERTIA_MAX_SPEED);
  assert.deepEqual(releaseVelocity([{ t: 800, x: 0, y: 0 }, { t: 820, x: 90, y: 0 }], 300, now), { az: 0, el: 0 });      // too old: the hand had stopped
  assert.deepEqual(releaseVelocity([{ t: 990, x: 0, y: 0 }], 300, now), { az: 0, el: 0 });
  const wild = releaseVelocity([{ t: 990, x: 0, y: 0 }, { t: 1000, x: 4000, y: 0 }], 300, now);
  assert.equal(Math.abs(wild.az), INERTIA_MAX_SPEED);
});

test('coast slows down, stops, and never flings after a long pause or past straight up', () => {
  let c = cam(); let v = { az: 2, el: 0.5 }; let done = false; let frames = 0;
  while (!done && frames < 2000) { const r = coast(c, v, 16); c = r.cam; v = r.v; done = r.done; frames++; }
  assert.ok(done && frames > 20 && frames < 600, `stopped after ${frames} frames`);
  const jump = coast(cam(), { az: 2, el: 0 }, 5000);
  close(jump.cam.azimuth - cam().azimuth, 2 * 0.1, 1e-6);       // a 5 s hiccup counts as 100 ms
  let up = cam({ elevation: 1.5 }); let vv = { az: 0, el: 3 };
  for (let i = 0; i < 60; i++) { const r = coast(up, vv, 16); up = r.cam; vv = r.v; }
  assert.ok(up.elevation <= (89 * Math.PI) / 180 + 1e-9);
  assert.equal(vv.el, 0);
});

test('spinStep turns at the requested rate', () => {
  close(spinStep(cam({ azimuth: 0 }), 100, 2).azimuth, 0.2);
  close(spinStep(cam({ azimuth: 0 }), 100000, 2).azimuth, 0.2);
});

test('slider sweep goes min -> max -> min, and starts where the slider is', () => {
  close(sweepValue(0, 10, 0), 0); close(sweepValue(0, 10, 3000), 10); close(sweepValue(0, 10, 6000), 0, 1e-9);
  assert.ok(sweepValue(0, 10, 1500) > 4.9 && sweepValue(0, 10, 1500) < 5.1);
  for (const v of [0, 2.5, 5, 7.5, 10]) close(sweepValue(0, 10, sweepStart(0, 10, v)), v, 1e-6);
  close(sweepValue(-5, 5, sweepStart(-5, 5, -5)), -5, 1e-6);
  assert.equal(snapToStep(3.14, 0, 10, 0.5), 3);
  assert.equal(snapToStep(99, 0, 10, 0.5), 10);
  assert.equal(snapToStep(1.2, 0, 10, 0), 1.2);
});

test('playback advances, loops or ends, and a long stall does not skip the scene', () => {
  assert.deepEqual(advancePlayback(0, 200, 2, 10, false), { frame: 0.4, ended: false });
  assert.deepEqual(advancePlayback(8.8, 200, 2, 10, false), { frame: 9, ended: true });
  const wrap = advancePlayback(89.5, 100, 15, 90, true);
  assert.equal(wrap.ended, false); assert.ok(wrap.frame >= 0 && wrap.frame < 1.1);
  close(advancePlayback(0, 60000, 1, 100, false).frame, 0.25, 1e-9);        // capped at 250 ms
  assert.deepEqual(advancePlayback(0, 100, 1, 1, true), { frame: 0, ended: true });
});

test('frameBlend picks the two frames around a position', () => {
  assert.deepEqual(frameBlend(0.25, 2), { a: 0, b: 1, t: 0.25 });
  assert.deepEqual(frameBlend(1, 2), { a: 1, b: 1, t: 0 });
  assert.deepEqual(frameBlend(NaN, 2), { a: 0, b: 1, t: 0 });
  assert.deepEqual(frameBlend(9, 3), { a: 2, b: 2, t: 0 });
});

test('depthFade keeps the nearest at full strength and never goes below the floor', () => {
  close(depthFade(1, 1, 3), 1); close(depthFade(3, 1, 3), 0.45); close(depthFade(2, 1, 3), 0.725);
  close(depthFade(9, 1, 3), 0.45); close(depthFade(1, 2, 2), 1);
});

test('bond lanes are centred and limited to three', () => {
  assert.deepEqual(laneOffsets(1, 4), [0]);
  assert.deepEqual(laneOffsets(2, 4), [-2, 2]);
  assert.deepEqual(laneOffsets(3, 4), [-4, 0, 4]);
  assert.equal(laneOffsets(9, 4).length, 3);
  assert.equal(laneOffsets(0, 4).length, 1);
});

test('scenes declare how they play, and looping scenes close their loop', () => {
  assert.equal(modeOf({ description: '', frames: 2, at: () => [] }), 'blend');
  assert.equal(modeOf({ description: '', frames: 9, at: () => [] }), 'steps');
  assert.equal(modeOf({ description: '', at: () => [] }), 'steps');
  const atom = atomScene(11, 23, 0, '[Ne] 3s1');
  assert.equal(modeOf(atom), 'continuous');
  const key = (f: number) => JSON.stringify(atom.at(f).filter((p) => p.kind === 'ball' && p.label === 'e−').map((p) => (p.kind === 'ball' ? p.p.map((x) => Math.round(x * 1e6)) : [])));
  assert.equal(key(0), key(90), 'frame 90 is frame 0 again');
  assert.notEqual(key(0), key(7));
  const dna = dnaScene('ATGC');
  assert.equal(modeOf(dna), 'continuous');
  const pos = (f: number) => JSON.stringify(dna.at(f).filter((p) => p.kind === 'rod').map((p) => (p.kind === 'rod' ? p.a.map((x) => Math.round(x * 1e6)) : [])));
  assert.equal(pos(0), pos(120));
  assert.notEqual(pos(0), pos(30));
});

test('bonds are one stick each, with lanes for double and triple bonds and both atom colours', () => {
  const co2 = {
    formula: 'CO2', name: 'Carbon dioxide', charge: 0, source: 'test',
    atoms: [{ element: 'O', xyz: [-1.16, 0, 0] as [number, number, number] }, { element: 'C', xyz: [0, 0, 0] as [number, number, number] }, { element: 'O', xyz: [1.16, 0, 0] as [number, number, number] }],
    bonds: [{ a: 0, b: 1, order: 2 }, { a: 1, b: 2, order: 2 }],
  };
  const lines = moleculeScene(co2).at(0).filter((p) => p.kind === 'line');
  assert.equal(lines.length, 2);
  for (const l of lines) { assert.equal(l.kind === 'line' && l.lanes, 2); assert.ok(l.kind === 'line' && l.color2 && l.color2 !== l.color); }
});

test('orbital clouds are dense enough to read as a surface', () => {
  assert.ok(orbitalAngularScene('p').at(0).length > 1000);
});
