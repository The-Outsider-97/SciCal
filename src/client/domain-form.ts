// Building an input form from the server's catalogue entry for one operation.
import { emptyRow, visible, type FormState } from '../core/forms.js';
import type { FormField, FormOp } from '../core/types.js';
import { h, replace } from './dom.js';
import { iconButton } from './ui.js';

export interface FormHandle {
  el: HTMLElement;
  /** Rebuild all fields from `state` (after loading an example). */
  refresh(): void;
  focusFirst(): void;
}

let counter = 0;

export function buildForm(op: FormOp, state: FormState, onChange: () => void, onSubmit: () => void): FormHandle {
  const root = h('div', { class: 'form' });
  const basicBox = h('div', { class: 'fields' });
  const advBox = h('div', { class: 'fields' });
  const advanced = h('details', { class: 'advanced' }, h('summary', { text: 'More options' }), advBox);
  root.append(basicBox, advanced);

  const hasMode = op.fields.some((f) => f.key === 'mode');

  const labelFor = (f: FormField, control: HTMLElement, id: string): HTMLElement => h('div', { class: 'field' },
    h('label', { for: id, class: 'label', text: f.unit ? `${f.label} (${f.unit})` : f.label }), control,
    f.hint ? h('span', { class: 'hint muted', text: f.hint }) : null);

  const control = (f: FormField): HTMLElement => {
    const id = `f${++counter}`;
    const cls = f.mono || f.kind === 'textarea' || f.kind === 'pairs' ? 'mono' : '';
    const enter = (ev: KeyboardEvent): void => { if (ev.key === 'Enter' && !ev.shiftKey && (ev.target as HTMLElement).tagName === 'INPUT') { ev.preventDefault(); onSubmit(); } };
    switch (f.kind) {
      case 'select': {
        const sel = h('select', { id }, (f.options ?? []).map((o) => h('option', { value: o.value, text: o.label, selected: state[f.key] === o.value })));
        sel.addEventListener('change', () => { state[f.key] = sel.value; if (f.key === 'mode' || hasMode) render(); onChange(); });
        return labelFor(f, sel, id);
      }
      case 'bool': {
        const box = h('input', { type: 'checkbox', id, checked: state[f.key] === true });
        box.addEventListener('change', () => { state[f.key] = box.checked; onChange(); });
        return h('div', { class: 'field check' }, box, h('label', { for: id, text: f.label }), f.hint ? h('span', { class: 'hint muted', text: f.hint }) : null);
      }
      case 'textarea': case 'pairs': {
        const ta = h('textarea', { id, rows: String(f.rows ?? (f.kind === 'pairs' ? 6 : 3)), class: cls, placeholder: f.placeholder ?? (f.kind === 'pairs' ? 'one pair per line, e.g.  1  0.52' : ''), spellcheck: 'false', autocomplete: 'off' });
        ta.value = String(state[f.key] ?? '');
        ta.addEventListener('input', () => { state[f.key] = ta.value; onChange(); });
        return labelFor(f, ta, id);
      }
      case 'table': return tableEditor(f, state, onChange);
      default: {
        const inp = h('input', { id, type: 'text', class: cls, placeholder: f.placeholder ?? (f.kind === 'list' ? 'separate with spaces or commas' : f.kind === 'quantity' && f.unit ? `e.g. 12 ${f.unit}` : ''), spellcheck: 'false', autocomplete: 'off', inputmode: f.kind === 'number' ? 'decimal' : undefined });
        inp.value = String(state[f.key] ?? '');
        inp.addEventListener('input', () => { state[f.key] = inp.value; onChange(); });
        inp.addEventListener('keydown', enter);
        return labelFor(f, inp, id);
      }
    }
  };

  const render = (): void => {
    const basic: HTMLElement[] = [];
    const adv: HTMLElement[] = [];
    for (const f of op.fields) {
      if (!visible(f, state)) continue;
      (f.advanced ? adv : basic).push(control(f));
    }
    replace(basicBox, basic);
    replace(advBox, adv);
    advanced.hidden = adv.length === 0;
    basicBox.hidden = basic.length === 0;
  };
  render();

  return {
    el: root,
    refresh: render,
    focusFirst: () => root.querySelector<HTMLElement>('input:not([type=checkbox]), textarea, select')?.focus(),
  };
}

function tableEditor(f: FormField, state: FormState, onChange: () => void): HTMLElement {
  const cols = f.columns ?? [];
  const rows = (): string[][] => {
    let r = state[f.key];
    if (!Array.isArray(r)) { r = [emptyRow(f)]; state[f.key] = r; }
    return r as string[][];
  };
  const box = h('div', { class: 'field tedit' });
  const draw = (): void => {
    const data = rows();
    const head = h('tr', null, cols.map((c) => h('th', { text: c.label })), h('th', { class: 'visually-hidden', text: 'Remove row' }));
    const body = data.map((row, ri) => h('tr', null,
      cols.map((c, ci) => {
        const inp = h('input', { type: 'text', class: 'mono', placeholder: c.placeholder ?? '', 'aria-label': `${f.label}, row ${ri + 1}, ${c.label}`, spellcheck: 'false', autocomplete: 'off' });
        inp.value = row[ci] ?? '';
        inp.addEventListener('input', () => { row[ci] = inp.value; onChange(); });
        inp.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter' && ci === cols.length - 1 && ri === data.length - 1) { ev.preventDefault(); data.push(emptyRow(f)); draw(); box.querySelectorAll<HTMLInputElement>('tbody tr:last-child input')[0]?.focus(); }
        });
        return h('td', null, inp);
      }),
      h('td', null, iconButton('trash', `Remove row ${ri + 1}`, () => { data.splice(ri, 1); if (!data.length) data.push(emptyRow(f)); draw(); onChange(); }, 'tiny'))));
    replace(box, h('span', { class: 'label', text: f.label }),
      h('table', null, h('thead', null, head), h('tbody', null, body)),
      h('div', null, h('button', { class: 'btn small', type: 'button', text: 'Add row', on: { click: () => { data.push(emptyRow(f)); draw(); box.querySelectorAll<HTMLInputElement>('tbody tr:last-child input')[0]?.focus(); } } })),
      f.hint ? h('span', { class: 'hint muted', text: f.hint }) : null);
  };
  draw();
  return box;
}
