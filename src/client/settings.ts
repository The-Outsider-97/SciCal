// Appearance and calculation preferences, and the theme itself.
import type { Prefs } from '../core/types.js';
import { h } from './dom.js';
import { store } from './store.js';
import { dialog } from './ui.js';

const dark = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)') : null;

export function applyPrefs(p: Prefs): void {
  const root = document.documentElement;
  const theme = p.theme ?? 'system';
  root.dataset.theme = theme === 'system' ? (dark?.matches ? 'dark' : 'light') : theme;
  root.style.setProperty('--font-scale', String(p.fontScale ?? 1));
  if (p.reducedMotion) root.dataset.motion = 'reduce'; else delete root.dataset.motion;
}

export function initTheme(): void {
  applyPrefs(store.prefs);
  store.on('prefs', () => applyPrefs(store.prefs));
  dark?.addEventListener('change', () => applyPrefs(store.prefs));
}

export function openSettings(): void {
  const p = store.prefs;
  const themeSel = h('select', { 'aria-label': 'Theme' }, ([['system', 'Follow the system'], ['light', 'Light'], ['dark', 'Dark'], ['contrast', 'High contrast']] as const).map(([v, t]) => h('option', { value: v, text: t, selected: (p.theme ?? 'system') === v })));
  themeSel.addEventListener('change', () => store.setPrefs({ theme: themeSel.value as Prefs['theme'] }));
  const scale = h('input', { type: 'range', min: '0.85', max: '1.5', step: '0.05', value: String(p.fontScale ?? 1), 'aria-label': 'Text size' });
  const scaleLabel = h('span', { class: 'muted', text: `${Math.round((p.fontScale ?? 1) * 100)} %` });
  scale.addEventListener('input', () => { scaleLabel.textContent = `${Math.round(Number(scale.value) * 100)} %`; store.setPrefs({ fontScale: Number(scale.value) }); });
  const motion = h('input', { type: 'checkbox', checked: !!p.reducedMotion });
  motion.addEventListener('change', () => store.setPrefs({ reducedMotion: motion.checked }));
  const digits = h('select', { 'aria-label': 'Significant digits' }, [6, 8, 10, 12, 15, 20, 30, 50, 100].map((n) => h('option', { value: String(n), text: String(n), selected: store.settings.digits === n })));
  digits.addEventListener('change', () => store.setPrefs({ digits: Number(digits.value) }));
  const notation = h('select', { 'aria-label': 'Number notation' }, ([['auto', 'Automatic'], ['fixed', 'Fixed decimals'], ['sci', 'Scientific'], ['eng', 'Engineering']] as const).map(([v, t]) => h('option', { value: v, text: t, selected: store.settings.notation === v })));
  notation.addEventListener('change', () => store.setPrefs({ notation: notation.value as Prefs['notation'] }));
  const angle = h('select', { 'aria-label': 'Angle unit' }, ([['rad', 'Radians'], ['deg', 'Degrees'], ['grad', 'Gradians']] as const).map(([v, t]) => h('option', { value: v, text: t, selected: store.settings.angle === v })));
  angle.addEventListener('change', () => store.setPrefs({ angle: angle.value as Prefs['angle'] }));
  const sw = (label: string, key: 'thousands' | 'units' | 'complex', checked: boolean): HTMLElement => {
    const cb = h('input', { type: 'checkbox', checked });
    cb.addEventListener('change', () => store.setPrefs({ [key]: cb.checked }));
    return h('label', { class: 'switch' }, cb, h('span', { text: label }));
  };
  dialog('Settings', [
    h('div', { class: 'fields' },
      h('label', { class: 'field' }, h('span', { class: 'label', text: 'Theme' }), themeSel),
      h('label', { class: 'field' }, h('span', { class: 'label', text: 'Text size' }), h('div', { class: 'row' }, scale, scaleLabel))),
    h('label', { class: 'switch' }, motion, h('span', { text: 'Reduce motion' })),
    h('h3', { text: 'Calculation' }),
    h('div', { class: 'fields' },
      h('label', { class: 'field' }, h('span', { class: 'label', text: 'Angle unit' }), angle),
      h('label', { class: 'field' }, h('span', { class: 'label', text: 'Significant digits' }), digits),
      h('label', { class: 'field' }, h('span', { class: 'label', text: 'Notation' }), notation)),
    sw('Read numbers followed by a unit as quantities (5 m, 3 kg)', 'units', store.settings.units),
    sw('Allow complex results', 'complex', store.settings.complex),
    sw('Group digits (1 234 567)', 'thousands', store.settings.thousands),
    h('p', { class: 'muted', text: 'Settings are saved on this computer, in the SciCal data folder.' }),
  ]);
}
