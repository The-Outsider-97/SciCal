// The Mathematics workspace: a history of calculations with exact and decimal results, a keypad and a command line.
import { applyInsert, PADS, type Key } from '../../core/keypad.js';
import { definesOf, contextFor } from '../../core/session.js';
import type { CalcResult, Entry, FormattedValue, Settings, Warning } from '../../core/types.js';
import { messageOf } from '../../core/results.js';
import { isRecord } from '../../core/util.js';
import type { NavRequest } from '../shell.js';
import { ApiError, api } from '../api.js';
import { h, replace } from '../dom.js';
import { math } from '../math-dom.js';
import { store } from '../store.js';
import { copyText, dialog, confirmDialog, emptyNote, glyph, iconButton, toast } from '../ui.js';
import { askExplain } from './assistant.js';

interface Suggestion { label: string; workspace: string; kind: string; payload: Record<string, unknown>; confidence?: string; note?: string }
type Shown = 'primary' | 'exact' | 'approx';

const EXAMPLES: Array<{ text: string; settings?: Partial<Settings> }> = [
  { text: '1/3 + 1/6' }, { text: 'sqrt(50)' }, { text: 'diff(sin(x)*x, x)' }, { text: 'integral(x^2, x, 0, 3)' }, { text: 'solve(x^2 - 5*x + 6 = 0)' },
  { text: '[[1,2],[3,4]]^-1' }, { text: '12 in -> cm', settings: { units: true } }, { text: 'normalprob(-1.96, 1.96, 0, 1)' },
];

export interface MathView { el: HTMLElement; focus(): void; open(req: NavRequest): void; run(text: string, settings?: Partial<Settings>): Promise<void>; setInput(text: string): void }

export function createMathView(): MathView {
  const history = h('div', { class: 'history', role: 'log', 'aria-live': 'polite', 'aria-label': 'Calculation history', tabindex: '0' });
  const input = h('textarea', { rows: '1', spellcheck: 'false', autocomplete: 'off', autocapitalize: 'off', 'aria-label': 'Expression to calculate', placeholder: 'Type an expression, e.g. diff(sin(x)*x, x), then press Enter' });
  const runBtn = h('button', { class: 'btn primary', type: 'button', text: 'Calculate' });
  const status = h('div', { class: 'hints', 'aria-live': 'polite' });
  const shown = new Map<string, Shown>();
  const openSteps = new Set<string>();
  const suggestions = new Map<string, Suggestion[]>();
  let transient: { input: string; result: CalcResult; suggestions: Suggestion[] } | null = null;
  let busyJob: string | null = null;
  let recallIndex = -1;
  let draft = '';

  // ---------------------------------------------------------------------------------------------------- settings bar
  const seg = (label: string, options: Array<[string, string]>, get: () => string, set: (v: string) => void): HTMLElement => {
    const wrap = h('div', { class: 'group' }, h('span', { class: 'lab', text: label }));
    const box = h('div', { class: 'seg', role: 'group', 'aria-label': label });
    const paint = (): void => replace(box, options.map(([v, t]) => h('button', { type: 'button', 'aria-pressed': String(get() === v), text: t, on: { click: () => { set(v); paint(); } } })));
    paint();
    wrap.appendChild(box);
    return wrap;
  };
  const toggle = (label: string, get: () => boolean, set: (v: boolean) => void): HTMLElement => {
    const cb = h('input', { type: 'checkbox', checked: get() });
    cb.addEventListener('change', () => set(cb.checked));
    return h('label', { class: 'switch' }, cb, h('span', { text: label }));
  };
  const select = (label: string, options: Array<[string, string]>, get: () => string, set: (v: string) => void): HTMLElement => {
    const sel = h('select', { 'aria-label': label }, options.map(([v, t]) => h('option', { value: v, text: t, selected: get() === v })));
    sel.addEventListener('change', () => set(sel.value));
    return h('div', { class: 'group' }, h('span', { class: 'lab', text: label }), sel);
  };
  const setbar = h('div', { class: 'setbar card' },
    seg('Angle', [['rad', 'RAD'], ['deg', 'DEG'], ['grad', 'GRAD']], () => store.settings.angle, (v) => store.setPrefs({ angle: v as Settings['angle'] })),
    seg('Result', [['auto', 'Auto'], ['exact', 'Exact'], ['approx', 'Decimal']], () => store.settings.result, (v) => store.setPrefs({ result: v as Settings['result'] })),
    select('Digits', [6, 8, 10, 12, 15, 20, 30, 50].map((n) => [String(n), String(n)]), () => String(store.settings.digits), (v) => store.setPrefs({ digits: Number(v) })),
    select('Notation', [['auto', 'Auto'], ['fixed', 'Fixed'], ['sci', 'Scientific'], ['eng', 'Engineering']], () => store.settings.notation, (v) => store.setPrefs({ notation: v as Settings['notation'] })),
    toggle('Units', () => store.settings.units, (v) => store.setPrefs({ units: v })),
    toggle('Complex', () => store.settings.complex, (v) => store.setPrefs({ complex: v })),
    toggle('Group digits', () => store.settings.thousands, (v) => store.setPrefs({ thousands: v })),
  );

  // ---------------------------------------------------------------------------------------------------- rendering
  const valueRendering = (v: FormattedValue, mode: Shown): { latex?: string; text: string } => {
    const pick = mode === 'primary' ? (v.primary ?? 'exact') : mode;
    if (v.t === 'number' && pick === 'approx' && v.approx) return v.approx;
    if (v.t === 'number' && pick === 'exact' && v.exact) return v.exact;
    return { latex: v.latex, text: v.text };
  };

  const noteLines = (warnings: Array<Warning | string> | undefined): HTMLElement | null => {
    const msgs = (warnings ?? []).map(messageOf).filter(Boolean);
    return msgs.length ? h('div', { class: 'notes' }, msgs.map((m) => h('div', { class: 'note-line', text: m }))) : null;
  };

  const errorBox = (res: CalcResult, source: string): HTMLElement => {
    const err = res.error ?? { code: 'error', message: 'Something went wrong' };
    const mark = h('div', { class: 'src-mark' });
    const span = err.span;
    if (span && span[0] <= source.length) {
      const [a, b] = span;
      const end = Math.max(b, Math.min(source.length, a + 1));
      mark.append(source.slice(0, a), h('mark', { text: source.slice(a, end) || ' ' }), source.slice(end));
    } else mark.textContent = source;
    return h('div', { class: 'errbox', role: 'alert' }, h('strong', { text: err.message }), mark, err.hint ? h('span', { class: 'hint', text: err.hint }) : null);
  };

  const suggestionBox = (list: Suggestion[]): HTMLElement | null => {
    if (!list.length) return null;
    return h('div', { class: 'suggest' }, h('span', { class: 'lead', text: 'Did you mean one of these?' }),
      h('div', { class: 'chips' }, list.slice(0, 5).map((p) => h('button', { class: 'chip', type: 'button', title: p.note ?? '', on: { click: () => void useSuggestion(p) } }, glyph('play'), p.label))));
  };

  const stepsBox = (res: CalcResult): HTMLElement | null => {
    const steps = res.steps ?? [];
    if (!steps.length) return null;
    return h('ol', { class: 'steps-list', 'aria-label': 'Working' }, steps.map((s) => h('li', null,
      s.exprLatex ? math(s.exprLatex) : h('code', { text: s.expr ?? '' }), ' = ', s.valueLatex ? math(s.valueLatex) : h('code', { text: s.value ?? '' }))));
  };

  const calcCard = (e: Entry): HTMLElement => {
    const res = e.result as unknown as CalcResult;
    const v = res.value as FormattedValue;
    const mode = shown.get(e.id) ?? 'primary';
    const rendering = valueRendering(v, mode);
    const canToggle = v.t === 'number' && !!v.exact && !!v.approx && v.exact.text !== v.approx.text;
    const outNode = rendering.latex && v.t !== 'text' ? math(rendering.latex, { label: rendering.text }) : h('span', { class: 'plain-result', text: rendering.text });
    const badges: HTMLElement[] = [];
    const flags = res.flags;
    if (flags?.approximate) badges.push(h('span', { class: 'badge', title: 'This result is a decimal approximation', text: '≈ approximate' }));
    else if (flags?.exact && v.t === 'number') badges.push(h('span', { class: 'badge plain', title: 'Computed with exact arithmetic', text: 'exact' }));
    if (flags?.symbolic) badges.push(h('span', { class: 'badge plain', text: 'symbolic' }));
    if (flags?.complex) badges.push(h('span', { class: 'badge plain', text: 'complex' }));
    if (res.numeric && typeof res.numeric.method === 'string') badges.push(h('span', { class: 'badge plain', title: 'Numerical method used', text: res.numeric.method as string }));
    if (res.unit?.dimension) badges.push(h('span', { class: 'badge plain', text: res.unit.dimension }));

    const toggleBox = canToggle ? h('div', { class: 'seg', role: 'group', 'aria-label': 'Show the result as' },
      (['exact', 'approx'] as const).map((m) => h('button', {
        type: 'button', 'aria-pressed': String((mode === 'primary' ? v.primary ?? 'exact' : mode) === m), text: m === 'exact' ? 'Exact' : 'Decimal',
        on: { click: () => { shown.set(e.id, m); render(); } },
      }))) : null;

    const stepsOpen = openSteps.has(e.id);
    const tools = h('div', { class: 'tools' },
      iconButton('reuse', 'Use this input again', () => setInput(e.input ?? '')),
      iconButton('plus', 'Insert the result into the input', () => insertText(rendering.text)),
      iconButton('copy', 'Copy the result', () => void copyText(rendering.text, 'Result copied')),
      h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Copy the result as LaTeX', title: 'Copy as LaTeX', on: { click: () => void copyText(rendering.latex ?? rendering.text, 'LaTeX copied') } }, h('span', { text: 'TeX', style: { 'font-size': '.7rem', 'font-weight': '700' } })),
      res.steps?.length ? h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Show the working', title: 'Show the working', 'aria-pressed': String(stepsOpen), on: { click: () => { if (stepsOpen) openSteps.delete(e.id); else openSteps.add(e.id); render(); } } }, glyph('steps')) : null,
      iconButton('assistant', 'Explain this result', () => void askExplain(e)),
      iconButton('trash', 'Delete this line', () => store.removeEntry(e.id), 'danger'));

    const sug = suggestions.get(e.id);
    return h('article', { class: 'entry', data: { id: e.id } },
      h('div', { class: 'in' }, h('div', { class: 'src' }, res.inputLatex ? math(res.inputLatex, { label: e.input }) : h('code', { text: e.input ?? '' })), tools),
      h('div', { class: 'out' }, outNode),
      h('div', { class: 'meta' }, badges, toggleBox),
      noteLines(res.warnings),
      stepsOpen ? stepsBox(res) : null,
      sug ? suggestionBox(sug) : null);
  };

  const noteCard = (e: Entry): HTMLElement => h('article', { class: 'entry note', data: { id: e.id } },
    h('div', { class: 'in' }, h('div', { class: 'src', style: { color: 'var(--text)', 'white-space': 'pre-wrap' }, text: e.text ?? '' }),
      h('div', { class: 'tools' }, iconButton('trash', 'Delete this note', () => store.removeEntry(e.id), 'danger'))));

  const render = (): void => {
    const items = store.entries.filter((e) => e.kind === 'calc' || e.kind === 'note');
    const nodes: Array<HTMLElement | string> = [];
    if (items.length === 0 && !transient) nodes.push(emptyNote('Nothing calculated yet. Type below or choose an example.'));
    for (const e of items) nodes.push(e.kind === 'note' ? noteCard(e) : e.result ? calcCard(e) : h('div'));
    if (transient) {
      nodes.push(h('article', { class: 'entry error', role: 'group', 'aria-label': 'Error' },
        h('div', { class: 'in' }, h('code', { text: transient.input })),
        errorBox(transient.result, transient.input),
        suggestionBox(transient.suggestions)));
    }
    replace(history, nodes);
    history.scrollTop = history.scrollHeight;
  };

  // ---------------------------------------------------------------------------------------------------- actions
  const setInput = (text: string): void => {
    input.value = text;
    grow();
    input.focus();
    input.setSelectionRange(text.length, text.length);
  };

  const insertText = (text: string): void => {
    const r = applyInsert(input.value, input.selectionStart, input.selectionEnd, text);
    input.value = r.value;
    grow();
    input.focus();
    input.setSelectionRange(r.cursor, r.cursor);
  };

  const grow = (): void => {
    input.style.setProperty('height', 'auto');
    input.style.setProperty('height', Math.min(input.scrollHeight + 2, 150) + 'px');
  };

  const looksLikeSentence = (text: string): boolean => /[A-Za-z]{3,}\s+[A-Za-z]{2,}/.test(text) && !/[(=^]/.test(text.replace(/\bto\b|\bin\b|\bof\b/g, ''));

  const fetchSuggestions = async (text: string): Promise<Suggestion[]> => {
    try {
      const r = await api.interpret(text, store.session?.id);
      return (r.proposals as unknown as Suggestion[]).filter((p) => !(p.kind === 'calc' && (p.payload as { input?: string }).input === text));
    } catch { return []; }
  };

  const run = async (text: string, override: Partial<Settings> = {}): Promise<void> => {
    text = text.trim();
    if (!text || busyJob) return;
    const settings: Settings = { ...store.settings, ...override, ...(/->/.test(text) ? { units: true } : {}) };           // a unit conversion needs unit parsing
    const job = api.newJob();
    busyJob = job;
    runBtn.textContent = 'Cancel';
    runBtn.classList.remove('primary');
    status.textContent = 'Calculating…';
    let res: CalcResult;
    try {
      res = await api.calc(text, settings, contextFor(store.entries, text), true, job);
    } catch (e) {
      busyJob = null;
      runBtn.textContent = 'Calculate';
      runBtn.classList.add('primary');
      status.textContent = '';
      toast(e instanceof ApiError ? e.message : 'The calculation could not be started.', 'error');
      return;
    }
    busyJob = null;
    runBtn.textContent = 'Calculate';
    runBtn.classList.add('primary');
    status.textContent = '';
    recallIndex = -1;
    if (res.ok && res.value) {
      transient = null;
      const entry = store.addEntry({ kind: 'calc', workspace: 'math', input: text, result: res as unknown as Record<string, unknown>, ok: true, settings: settings as unknown as Record<string, unknown>, defines: definesOf(res) });
      input.value = '';
      grow();
      if (looksLikeSentence(text) && res.flags?.symbolic) {
        const list = await fetchSuggestions(text);
        if (list.length) { suggestions.set(entry.id, list); render(); }
      }
    } else {
      const list = res.error && (res.error.code === 'parse_error' || res.error.code === 'unknown_name' || res.error.code === 'dimension_error') ? await fetchSuggestions(text) : [];
      transient = { input: text, result: res, suggestions: list };
      render();
      if (res.error?.code === 'timeout') status.textContent = 'That took too long and was stopped. Try a simpler form or a numerical method (nintegral, nsolve).';
    }
    input.focus();
  };

  const useSuggestion = async (p: Suggestion): Promise<void> => {
    const pl = p.payload as Record<string, unknown>;
    if (p.kind === 'calc') {
      const settings = (pl.settings as Partial<Settings> | undefined) ?? {};
      transient = null;
      await run(String(pl.input ?? ''), settings);
    } else {
      const { navigate } = await import('../shell.js');
      navigate({ workspace: p.workspace, kind: p.kind, payload: pl });
    }
  };

  const cancelBusy = (): void => {
    if (busyJob) { void api.cancel(busyJob); status.textContent = 'Stopping…'; }
  };

  const submit = (): void => { if (busyJob) cancelBusy(); else void run(input.value); };
  runBtn.addEventListener('click', submit);

  input.addEventListener('input', () => { grow(); recallIndex = -1; });
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); submit(); return; }
    if (ev.key === 'Escape') { if (busyJob) cancelBusy(); else if (input.value) { input.value = ''; grow(); } return; }
    const past = store.entries.filter((e) => e.kind === 'calc' && e.input).map((e) => e.input as string);
    if (ev.key === 'ArrowUp' && input.selectionStart === 0 && input.selectionEnd === 0 && past.length) {
      ev.preventDefault();
      if (recallIndex === -1) { draft = input.value; recallIndex = past.length; }
      recallIndex = Math.max(0, recallIndex - 1);
      setInput(past[recallIndex]);
      input.setSelectionRange(0, 0);
    } else if (ev.key === 'ArrowDown' && recallIndex !== -1 && input.selectionStart === input.value.length) {
      ev.preventDefault();
      recallIndex++;
      if (recallIndex >= past.length) { recallIndex = -1; setInput(draft); } else setInput(past[recallIndex]);
    }
  });

  // ---------------------------------------------------------------------------------------------------- keypad
  const keysBox = h('div', { class: 'keys', role: 'group', 'aria-label': 'Keypad' });
  const padTabs = h('div', { class: 'seg', role: 'group', 'aria-label': 'Keypad pages' });
  const press = (key: Key): void => {
    if (key.action === 'enter') { submit(); return; }
    if (key.action === 'clear') { input.value = ''; grow(); input.focus(); return; }
    if (key.action === 'back') {
      const a = input.selectionStart;
      const b = input.selectionEnd;
      const [s, e] = a !== b ? [a, b] : [Math.max(0, a - 1), a];
      input.value = input.value.slice(0, s) + input.value.slice(e);
      input.focus();
      input.setSelectionRange(s, s);
      grow();
      return;
    }
    if (key.insert) insertText(key.insert);
  };
  const drawPad = (): void => {
    const page = store.prefs.keypad && store.prefs.keypad in PADS ? store.prefs.keypad : 'basic';
    replace(padTabs, Object.entries(PADS).map(([id, p]) => h('button', { type: 'button', 'aria-pressed': String(id === page), text: p.title, on: { click: () => { store.setPrefs({ keypad: id }); drawPad(); } } })));
    replace(keysBox, PADS[page].rows.flat().map((k) => h('button', { class: `key ${k.cls ?? 'fn'}`, type: 'button', title: k.title, 'aria-label': k.title === k.label ? k.label : `${k.label}: ${k.title}`, text: k.label, on: { click: () => press(k) } })));
  };
  drawPad();

  const addNote = (): void => {
    const ta = h('textarea', { rows: '4', 'aria-label': 'Note', placeholder: 'A note for this worksheet' });
    const d = dialog('Add a note', ta, { actions: [h('button', { class: 'btn', type: 'button', text: 'Cancel', on: { click: () => d.close() } }),
      h('button', { class: 'btn primary', type: 'button', text: 'Add note', on: { click: () => { if (ta.value.trim()) store.addEntry({ kind: 'note', workspace: 'math', text: ta.value.trim().slice(0, 4000) }); d.close(); } } })] });
    ta.focus();
  };

  const clearAll = async (): Promise<void> => {
    if (await confirmDialog('Clear the history?', 'This removes every calculation and note from this worksheet, including the variables and functions you defined.', 'Clear')) store.clearEntries(['calc', 'note']);
  };

  const el = h('div', { class: 'math' },
    h('div', { class: 'math-main' },
      setbar,
      h('section', { class: 'card', 'aria-label': 'History' },
        h('div', { class: 'card-head' }, h('h2', { text: 'Calculations' }),
          h('div', { class: 'row' }, h('button', { class: 'btn small', type: 'button', text: 'Add note', on: { click: addNote } }), h('button', { class: 'btn small', type: 'button', text: 'Clear', on: { click: () => void clearAll() } }))),
        history),
      h('section', { class: 'card composer', 'aria-label': 'Input' },
        h('div', { class: 'line' }, input, runBtn),
        status,
        h('div', { class: 'examples' }, EXAMPLES.map((x) => h('button', { class: 'chip', type: 'button', text: x.text, on: { click: () => { setInput(x.text); if (x.settings) store.setPrefs(x.settings as never); } } }))),
        h('div', { class: 'hints' }, h('span', { text: 'Enter calculates · Shift+Enter adds a line · ↑ recalls earlier input' }),
          h('span', { text: 'Define things with a := 5 or f(x) := x^2 + 1' })))),
    h('aside', { class: 'keypad-panel card', 'aria-label': 'Keypad' }, padTabs, keysBox));

  store.on('entries', render);
  store.on('session', () => { transient = null; suggestions.clear(); render(); });
  store.on('prefs', () => { /* settings controls manage their own state */ });
  render();
  const open = (req: NavRequest): void => {
    const pl = req.payload;
    if (typeof pl.input === 'string') void run(pl.input, (isRecord(pl.settings) ? pl.settings : {}) as Partial<Settings>);
    else if (typeof pl.insert === 'string') insertText(pl.insert);           // e.g. const(c) from the Constants page
  };

  return { el, focus: () => input.focus(), open, run, setInput };
}
