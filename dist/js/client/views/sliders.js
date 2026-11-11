// Parameter sliders shared by the 2D and 3D graph views: a free letter in a formula (the a in a*sin(x)) becomes a slider with editable bounds.
import { formatNumber } from '../../core/graphmath.js';
import { clamp } from '../../core/util.js';
import { snapToStep, sweepStart, sweepValue } from '../../core/motion.js';
import { reducedMotion } from '../motion.js';
import { h, replace } from '../dom.js';
import { iconButton } from '../ui.js';
/** Sliders that are being played, so only one animation runs per slider and a repaint of the list stops it. */
const playing = new Set();
export const NO_SLIDERS_HINT = 'Use a letter such as a in an expression (a*sin(x)) and a slider appears.';
export function paintSliderBox(box, params, hooks, hint = NO_SLIDERS_HINT) {
    playing.clear(); // the old buttons are about to be replaced; their loops end when their range input leaves the page
    replace(box, params.length ? params.map((p) => {
        const range = h('input', { type: 'range', min: String(p.min), max: String(p.max), step: String(p.step), value: String(p.value), 'aria-label': `Value of ${p.name}` });
        const val = h('span', { text: formatNumber(p.value, 5) });
        range.addEventListener('input', () => { p.value = Number(range.value); val.textContent = formatNumber(p.value, 5); hooks.change(); });
        const bound = (key) => {
            const i = h('input', { type: 'text', value: String(p[key]), 'aria-label': `${p.name} ${key === 'min' ? 'minimum' : 'maximum'}` });
            i.addEventListener('change', () => {
                const v = Number(i.value);
                if (!Number.isFinite(v)) {
                    i.value = String(p[key]);
                    return;
                }
                p[key] = v;
                if (p.min >= p.max) {
                    p.min = Math.min(p.min, p.max - 1);
                }
                p.value = clamp(p.value, p.min, p.max);
                p.step = Math.max((p.max - p.min) / 200, 1e-6);
                hooks.repaint();
                hooks.change();
            });
            return i;
        };
        const playBtn = h('button', { class: 'btn small', type: 'button', text: 'Play', 'aria-pressed': 'false', title: `Sweep ${p.name} from ${formatNumber(p.min, 4)} to ${formatNumber(p.max, 4)} and back`, disabled: reducedMotion() });
        if (reducedMotion())
            playBtn.title = 'Animation is switched off (reduce motion).';
        let stopPlaying = () => undefined;
        playBtn.addEventListener('click', () => {
            if (playing.has(p.name)) {
                stopPlaying();
                return;
            }
            playing.add(p.name);
            playBtn.textContent = 'Pause';
            playBtn.setAttribute('aria-pressed', 'true');
            const startedAt = performance.now();
            const phaseOffset = sweepStart(p.min, p.max, p.value); // begin where the slider already is
            let alive = true;
            stopPlaying = () => { alive = false; playing.delete(p.name); playBtn.textContent = 'Play'; playBtn.setAttribute('aria-pressed', 'false'); };
            const tick = async () => {
                if (!alive)
                    return;
                if (!range.isConnected || reducedMotion()) {
                    stopPlaying();
                    return;
                }
                const value = snapToStep(sweepValue(p.min, p.max, performance.now() - startedAt + phaseOffset), p.min, p.max, p.step);
                p.value = value;
                range.value = String(value);
                val.textContent = formatNumber(value, 5);
                if (hooks.immediate)
                    await hooks.immediate();
                else
                    hooks.change();
                if (alive)
                    requestAnimationFrame(() => void tick());
            };
            void tick();
        });
        return h('div', { class: 'slider' }, h('div', { class: 'head' }, h('span', { text: `${p.name} =` }), val, playBtn, iconButton('trash', `Remove the slider ${p.name}`, () => { stopPlaying(); hooks.remove(p); }, 'tiny')), range, h('div', { class: 'bounds' }, bound('min'), h('span', { class: 'muted', text: 'to' }), bound('max')));
    }) : h('p', { class: 'muted', text: hint }));
}
/** Names that an error such as "'a' has no value" asks for. */
export function missingName(message) {
    const m = /^'([A-Za-z_]\w*)' has no value/.exec(message);
    return m ? m[1] : null;
}
//# sourceMappingURL=sliders.js.map