import test from 'node:test';
import assert from 'node:assert/strict';
import { BOX_HEIGHT, DEFAULT_CAMERA, clampCamera, colormap, hexToRgb, makeProjector, normalizer, orbit, panBy, triangulateCell, zoomBy, MAX_ZOOM, MIN_ZOOM, type Camera, type V3 } from '../src/core/scene3d.js';

const near = (a: number, b: number, tol = 1e-9): void => assert.ok(Math.abs(a - b) <= tol, `${a} != ${b} (tol ${tol})`);

test('normalizer maps the data box to the unit box and back', () => {
  const b = { xmin: -2, xmax: 6, ymin: 0, ymax: 4, zmin: -10, zmax: 30 };
  const n = normalizer(b, 'box');
  assert.deepEqual(n.toUnit([2, 2, 10]), [0, 0, 0]);
  near(n.toUnit([6, 4, 30])[0], 0.5); near(n.toUnit([-2, 0, -10])[2], -BOX_HEIGHT / 2);
  const p: V3 = [1.25, 3.5, -7];
  const q = n.fromUnit(n.toUnit(p));
  [0, 1, 2].forEach((i) => near(q[i], p[i], 1e-12));
});

test('equal aspect keeps true proportions, box aspect stretches', () => {
  const b = { xmin: 0, xmax: 10, ymin: 0, ymax: 10, zmin: 0, zmax: 1 };
  const eq = normalizer(b, 'equal');
  near(eq.toUnit([10, 0, 0])[0] - eq.toUnit([0, 0, 0])[0], 1);
  near(eq.toUnit([0, 0, 1])[2] - eq.toUnit([0, 0, 0])[2], 0.1);
  const bx = normalizer(b, 'box');
  near(bx.toUnit([0, 0, 1])[2] - bx.toUnit([0, 0, 0])[2], BOX_HEIGHT);
});

test('a degenerate (flat) axis does not divide by zero', () => {
  const n = normalizer({ xmin: 0, xmax: 1, ymin: 0, ymax: 1, zmin: 3, zmax: 3 }, 'box');
  const u = n.toUnit([0.5, 0.5, 3]);
  assert.ok(u.every(Number.isFinite));
});

test('the target maps to the viewport centre and +z is up on screen', () => {
  const p = makeProjector(DEFAULT_CAMERA, 800, 600);
  const o = p.project([0, 0, 0]);
  near(o.x, 400, 1e-6); near(o.y, 300, 1e-6);
  assert.ok(p.project([0, 0, 0.5]).y < o.y, 'higher z is higher on screen (smaller y)');
});

test('azimuth 0, elevation 0 looks along -x: +y is to the right', () => {
  const cam: Camera = { ...DEFAULT_CAMERA, azimuth: 0, elevation: 0 };
  const p = makeProjector(cam, 500, 500);
  assert.ok(p.project([0, 0.5, 0]).x > p.project([0, 0, 0]).x);
  near(p.project([0.5, 0, 0]).x, 250, 1e-9);   // along the line of sight
});

test('looking straight down puts +x up the screen for azimuth -90 degrees', () => {
  const cam: Camera = { ...DEFAULT_CAMERA, azimuth: -Math.PI / 2, elevation: (89 * Math.PI) / 180, projection: 'orthographic' };
  const p = makeProjector(cam, 500, 500);
  const o = p.project([0, 0, 0]);
  assert.ok(p.project([0.5, 0, 0]).x > o.x);
});

test('perspective makes nearer points larger; orthographic does not', () => {
  const persp = makeProjector({ ...DEFAULT_CAMERA, azimuth: 0, elevation: 0 }, 600, 600);
  const ortho = makeProjector({ ...DEFAULT_CAMERA, azimuth: 0, elevation: 0, projection: 'orthographic' }, 600, 600);
  const spread = (pr: ReturnType<typeof makeProjector>, x: number): number => pr.project([x, 0.3, 0]).x - pr.project([x, -0.3, 0]).x;
  assert.ok(spread(persp, 0.5) > spread(persp, -0.5));
  near(spread(ortho, 0.5), spread(ortho, -0.5), 1e-9);
  near(spread(ortho, 0), spread(persp, 0), 1e-9);   // both agree on the target plane
});

test('depth increases away from the viewer', () => {
  const p = makeProjector({ ...DEFAULT_CAMERA, azimuth: 0, elevation: 0 }, 400, 400);
  assert.ok(p.project([-0.5, 0, 0]).depth > p.project([0.5, 0, 0]).depth);
});

test('panning moves the picture with the drag', () => {
  const base = makeProjector(DEFAULT_CAMERA, 500, 500).project([0, 0, 0]);
  const moved = makeProjector(panBy(DEFAULT_CAMERA, 40, 25, 500), 500, 500).project([0, 0, 0]);
  assert.ok(moved.x > base.x && moved.y > base.y);
});

test('orbit and zoom stay inside their limits', () => {
  let c = DEFAULT_CAMERA;
  c = orbit(c, 0, 100000, 500);
  assert.ok(c.elevation <= (89 * Math.PI) / 180 + 1e-12);
  c = orbit(c, 0, -100000, 500);
  assert.ok(c.elevation >= -(89 * Math.PI) / 180 - 1e-12);
  for (let i = 0; i < 100; i++) c = zoomBy(c, 1.5);
  assert.equal(c.zoom, MAX_ZOOM);
  for (let i = 0; i < 100; i++) c = zoomBy(c, 0.5);
  assert.equal(c.zoom, MIN_ZOOM);
  const w = clampCamera({ ...DEFAULT_CAMERA, azimuth: 7 * Math.PI });
  assert.ok(w.azimuth >= -Math.PI && w.azimuth <= Math.PI);
});

test('dragging right turns the scene so that the near side moves right', () => {
  const c = orbit({ ...DEFAULT_CAMERA, azimuth: 0, elevation: 0 }, 100, 0, 500);
  assert.ok(c.azimuth < 0);
});

test('colormap is monotone in luminance-ish terms and clamps', () => {
  assert.deepEqual(colormap(-5), colormap(0));
  assert.deepEqual(colormap(9), colormap(1));
  assert.deepEqual(colormap(NaN), colormap(0));
  const lum = (t: number): number => { const [r, g, b] = colormap(t); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  for (let i = 1; i <= 20; i++) assert.ok(lum(i / 20) >= lum((i - 1) / 20) - 1e-9, `luminance dips at ${i / 20}`);
});

test('hexToRgb parses #rrggbb and falls back for junk', () => {
  assert.deepEqual(hexToRgb('#ff8000'), [255, 128, 0]);
  assert.deepEqual(hexToRgb('nonsense'), [160, 128, 0]);
});

test('cell triangulation matches the backend convention', () => {
  assert.deepEqual(triangulateCell([0, 1, 3, 2]), [[0, 1, 3], [0, 3, 2]]);
});

test('orthographic projection agrees with the Python exporter (shared vectors, services/spatial.py Projection)', () => {
  // The same four points and the same expected page coordinates are asserted in tests/test_spatial_export.py (test_shared_vector_with_the_browser_projection).
  // The expected numbers were computed independently with mpmath at 40 digits. With min(width, height) * 0.46 = 100 the screen scale S is 100, i.e. the page width.
  const size = 100 / 0.46;
  const cam: Camera = { azimuth: 0.5, elevation: 0.3, zoom: 1, panX: 0, panY: 0, projection: 'orthographic' };
  const n = normalizer({ xmin: -1, xmax: 1, ymin: 0, ymax: 4, zmin: -2, zmax: 2 }, 'box');
  const proj = makeProjector(cam, size, size);
  const cx = size / 2;
  const cases: Array<[V3, [number, number]]> = [
    [[1, 4, 2], [19.907851164308486, 17.206957360935192]],
    [[-1, 0, -2], [-19.907851164308486, -17.206957360935192]],
    [[0, 2, 0], [0, 0]],
    [[0.25, 3, -1], [15.946744814706781, -25.412852144778153]],
  ];
  for (const [p, [px, py]] of cases) {
    const s = proj.project(n.toUnit(p));
    near(s.x - cx, px, 1e-9);
    near(cx - s.y, py, 1e-9);
  }
});
