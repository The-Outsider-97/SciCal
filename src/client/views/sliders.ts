// Parameter sliders shared by the 2D and 3D graph views: a free letter in a formula (the a in a*sin(x)) becomes a slider with editable bounds.
import { formatNumber } from '../../core/graphmath.js';
import { clamp } from '../../core/util.js';
import { h, replace } from '../dom.js';
import { iconButton } from '../ui.js';

export interface Param { name: string; value: number; min: number; max: number; step: number }

export interface SliderHooks {
  /** A value changed: draw again (the caller debounces the request to the service). */
  change(): void;
  /** The person removed this slider. */
  remove(p: Param): void;
  /** Bounds were edited: the list must be painted again. */
  repaint(): void;
}

export const NO_SLIDERS_HINT = 'Use a letter such as a in an expression (a*sin(x)) and a slider appears.';

export function paintSliderBox(box: HTMLElement, params: Param[], hooks: SliderHooks, hint = NO_SLIDERS_HINT): void {
  replace(box, params.length ? params.map((p) => {
    const range = h('input', { type: 'range', min: String(p.min), max: String(p.max), step: String(p.step), value: String(p.value), 'aria-label': `Value of ${p.name}` });
    const val = h('span', { text: formatNumber(p.value, 5) });
    range.addEventListener('input', () => { p.value = Number(range.value); val.textContent = formatNumber(p.value, 5); hooks.change(); });
    const bound = (key: 'min' | 'max'): HTMLInputElement => {
      const i = h('input', { type: 'text', value: String(p[key]), 'aria-label': `${p.name} ${key === 'min' ? 'minimum' : 'maximum'}` });
      i.addEventListener('change', () => {
        const v = Number(i.value);
        if (!Number.isFinite(v)) { i.value = String(p[key]); return; }
        p[key] = v;
        if (p.min >= p.max) { p.min = Math.min(p.min, p.max - 1); }
        p.value = clamp(p.value, p.min, p.max);
        p.step = Math.max((p.max - p.min) / 200, 1e-6);
        hooks.repaint();
        hooks.change();
      });
      return i;
    };
    return h('div', { class: 'slider' },
      h('div', { class: 'head' }, h('span', { text: `${p.name} =` }), val, iconButton('trash', `Remove the slider ${p.name}`, () => hooks.remove(p), 'tiny')),
      range, h('div', { class: 'bounds' }, bound('min'), h('span', { class: 'muted', text: 'to' }), bound('max')));
  }) : h('p', { class: 'muted', text: hint }));
}

/** Names that an error such as "'a' has no value" asks for. */
export function missingName(message: string): string | null {
  const m = /^'([A-Za-z_]\w*)' has no value/.exec(message);
  return m ? m[1] : null;
}
