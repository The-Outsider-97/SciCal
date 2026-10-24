import { clamp } from './util.js';
export const LIMIT = 1e12;
export const MIN_SPAN = 1e-9;
export function niceStep(span, target) {
    const raw = span / Math.max(1, target);
    const pow = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / pow;
    const nice = f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10;
    return +(nice * pow).toPrecision(12);
}
export function ticks(lo, hi, target) {
    const step = niceStep(hi - lo, target);
    const first = Math.ceil(lo / step - 1e-9);
    const values = [];
    for (let k = first; k * step <= hi + step * 1e-9 && values.length < 400; k++)
        values.push(Math.abs(k * step) < step * 1e-9 ? 0 : +(k * step).toPrecision(12));
    return { step, values };
}
export function formatTick(v, step) {
    if (v === 0)
        return '0';
    const a = Math.abs(v);
    if (a >= 1e6 || a < 1e-4)
        return v.toExponential(2).replace(/\.?0+e/, 'e').replace('e+', 'e');
    const decimals = Math.max(0, Math.min(10, -Math.floor(Math.log10(step) + 1e-9)));
    return v.toFixed(decimals);
}
export function sane(v) {
    let { xmin, xmax, ymin, ymax } = v;
    const fix = (lo, hi) => {
        if (!Number.isFinite(lo) || !Number.isFinite(hi))
            return [-10, 10];
        if (hi - lo < MIN_SPAN) {
            const m = (hi + lo) / 2;
            lo = m - MIN_SPAN / 2;
            hi = m + MIN_SPAN / 2;
        }
        return [clamp(lo, -LIMIT, LIMIT), clamp(hi, -LIMIT, LIMIT)];
    };
    [xmin, xmax] = fix(xmin, xmax);
    [ymin, ymax] = fix(ymin, ymax);
    return { xmin, xmax, ymin, ymax };
}
/** Zoom by ``factor`` (< 1 zooms in) about the point (fx, fy) given as fractions of the canvas, y measured from the top. */
export function zoomAt(v, fx, fy, factor) {
    const wx = v.xmin + (v.xmax - v.xmin) * fx;
    const wy = v.ymax - (v.ymax - v.ymin) * fy;
    return sane({ xmin: wx - (wx - v.xmin) * factor, xmax: wx + (v.xmax - wx) * factor, ymin: wy - (wy - v.ymin) * factor, ymax: wy + (v.ymax - wy) * factor });
}
/** Move the view by a fraction of its size (dx to the right, dy downwards on screen). */
export function pan(v, dx, dy) {
    const w = v.xmax - v.xmin;
    const h = v.ymax - v.ymin;
    return sane({ xmin: v.xmin - dx * w, xmax: v.xmax - dx * w, ymin: v.ymin + dy * h, ymax: v.ymax + dy * h });
}
/** Same scale on both axes for a canvas of w × h pixels, keeping the centre. */
export function square(v, w, h) {
    const cx = (v.xmin + v.xmax) / 2;
    const cy = (v.ymin + v.ymax) / 2;
    const span = Math.max((v.xmax - v.xmin) / w, (v.ymax - v.ymin) / h);
    return sane({ xmin: cx - span * w / 2, xmax: cx + span * w / 2, ymin: cy - span * h / 2, ymax: cy + span * h / 2 });
}
export function mapper(v, w, h) {
    const sx = w / (v.xmax - v.xmin);
    const sy = h / (v.ymax - v.ymin);
    return { px: (x) => (x - v.xmin) * sx, py: (y) => (v.ymax - y) * sy, wx: (p) => v.xmin + p / sx, wy: (p) => v.ymax - p / sy };
}
/** The curve point at x (linear interpolation inside the segment that contains x). */
export function traceAt(segments, x) {
    for (const seg of segments) {
        if (seg.length < 2 || x < seg[0][0] || x > seg[seg.length - 1][0])
            continue;
        let lo = 0;
        let hi = seg.length - 1;
        while (hi - lo > 1) {
            const mid = (lo + hi) >> 1;
            if (seg[mid][0] <= x)
                lo = mid;
            else
                hi = mid;
        }
        const [x0, y0] = seg[lo];
        const [x1, y1] = seg[hi];
        const t = x1 === x0 ? 0 : (x - x0) / (x1 - x0);
        return [x, y0 + (y1 - y0) * t];
    }
    return null;
}
/** The sample (over all polylines) nearest to a point, measured in pixels. */
export function nearest(lines, m, qx, qy) {
    let best = null;
    for (const line of lines) {
        for (const p of line) {
            const d = Math.hypot(m.px(p[0]) - qx, m.py(p[1]) - qy);
            if (!best || d < best.dist)
                best = { pt: p, dist: d };
        }
    }
    return best;
}
export const PALETTE = ['#2f6fdb', '#d6572b', '#2a9d6f', '#8e44c7', '#c79a00', '#c2366b', '#2b8fa3', '#6b7280'];
export const paletteColor = (i) => PALETTE[i % PALETTE.length];
export function formatNumber(v, digits = 6) {
    if (!Number.isFinite(v))
        return String(v);
    if (v === 0)
        return '0';
    const a = Math.abs(v);
    if (a >= 1e9 || a < 1e-5)
        return v.toExponential(digits - 1).replace(/\.?0+e/, 'e').replace('e+', 'e');
    return String(+v.toPrecision(digits));
}
export const PRESETS = {
    standard: { xmin: -10, xmax: 10, ymin: -6.5, ymax: 6.5 },
    trig: { xmin: -7, xmax: 7, ymin: -2.5, ymax: 2.5 },
    quadrant: { xmin: -1, xmax: 10, ymin: -1, ymax: 7 },
    wide: { xmin: -100, xmax: 100, ymin: -65, ymax: 65 },
};
//# sourceMappingURL=graphmath.js.map