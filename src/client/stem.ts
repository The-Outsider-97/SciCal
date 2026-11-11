// The SLAI STEM agent in the interface: the status it reports, the "STEM check" that computes a result again by another route,
// and the panel that shows what it found. The agent only checks; the number in the result is always SciCal's own.
import { entryForCheck, formatDifference, slim, statusMark, statusWord, verdictBadge } from '../core/stem.js';
import type { Entry, Settings, StemCheck, Verification } from '../core/types.js';
import { api, ApiError, type StemStatus } from './api.js';
import { h } from './dom.js';
import { store } from './store.js';
import { glyph } from './ui.js';

let cached: Promise<StemStatus> | null = null;

/** The agent's status, asked for once and remembered (``refresh`` asks again after "Test again"). */
export function stemStatus(refresh = false): Promise<StemStatus> {
  if (!cached || refresh) {
    cached = (refresh ? api.stemProbe() : api.stemStatus()).catch((e: unknown) => {
      cached = null;
      return { available: false, reason: e instanceof ApiError ? e.message : 'The STEM status could not be read.', mode: 'auto', domains: {}, operationCount: 0 } as StemStatus;
    });
  }
  return cached;
}

/** STEM checks are shown unless the person switched them off in Settings. */
export function stemEnabled(): boolean { return store.prefs.stemVerify !== 'off'; }
export function stemAuto(): boolean { return store.prefs.stemVerify === 'auto'; }

/** Ask the agent to compute this entry again. Never throws: a problem becomes a verification that says so. */
export async function runCheck(entry: Pick<Entry, 'kind' | 'workspace' | 'input' | 'domain' | 'op' | 'params' | 'result'>, settings: Settings, context: string[]): Promise<Verification> {
  try {
    const v = await api.stemVerify(entryForCheck(entry as Entry), settings, context);
    return slim(v);
  } catch (e) {
    return { ran: false, verdict: 'unavailable', summary: e instanceof ApiError ? e.message : 'The STEM check could not be run.', checks: [], counts: {} };
  }
}

/** The small label on a result. Clicking it opens the details. */
export function stemBadge(v: Verification | undefined, onClick?: () => void): HTMLElement | null {
  const b = verdictBadge(v);
  if (!b) return null;
  const cls = `badge stem-badge ${b.tone}`;
  return onClick ? h('button', { class: cls, type: 'button', title: b.title, 'aria-label': `${b.text}. Show details`, text: b.text, on: { click: onClick } }) : h('span', { class: cls, title: b.title, text: b.text });
}

export function stemButton(label: string, onClick: () => void, title = 'Ask the SLAI STEM agent to compute this again by a different route and compare'): HTMLElement {
  return h('button', { class: 'btn small stem-btn', type: 'button', title, on: { click: onClick } }, glyph('shield'), h('span', { text: label }));
}

function checkRow(c: StemCheck): HTMLElement {
  const ran = c.status === 'agree' || c.status === 'differ';
  const first = h('td', { class: `stem-state ${c.status}` }, h('span', { class: 'mark', 'aria-hidden': 'true', text: statusMark(c.status) }), ' ', h('span', { text: statusWord(c.status) }));
  const what = h('td', { class: 'stem-what' }, h('div', { text: c.title }), c.via ? h('div', { class: 'stem-via', text: `STEM: ${c.via}` }) : null,
    c.note ? h('div', { class: 'stem-note', text: c.note }) : null);
  if (!ran) return h('tr', { class: `stem-row ${c.status}` }, first, what, h('td', { colspan: '3', class: 'muted', text: '' }));
  return h('tr', { class: `stem-row ${c.status}` }, first, what,
    h('td', { class: 'num', text: c.scical ?? '' }), h('td', { class: 'num', text: c.stem ?? '' }),
    h('td', { class: 'num', title: c.tolerance ?? '', text: formatDifference(c.difference) }));
}

/** What the agent found, as a table: SciCal's value, STEM's value, the difference, the tolerance and which STEM operation made it. */
export function verificationPanel(v: Verification): HTMLElement {
  const tone = v.verdict === 'agree' ? 'ok' : v.verdict === 'differ' ? 'warn' : 'muted';
  const head = h('div', { class: `stem-head ${tone}` }, glyph('shield'), h('strong', { text: v.summary }));
  if (!v.ran || !v.checks.length) return h('div', { class: 'stem-panel', role: 'group', 'aria-label': 'STEM check' }, head);
  const table = h('div', { class: 'table-wrap' }, h('table', { class: 'data stem-table' },
    h('thead', null, h('tr', null, ['Result', 'What was computed again', 'SciCal', 'STEM', 'Difference'].map((t) => h('th', { text: t })))),
    h('tbody', null, v.checks.map(checkRow))));
  const tolerances = [...new Set(v.checks.map((c) => c.tolerance).filter((t): t is string => !!t))];
  return h('div', { class: 'stem-panel', role: 'group', 'aria-label': 'STEM check' }, head, table,
    tolerances.length ? h('p', { class: 'muted stem-foot', text: `Tolerance: ${tolerances.join('; ')}.` }) : null,
    v.label ? h('p', { class: 'muted stem-foot', text: v.label }) : null);
}

/** One line for the assistant panel and the STEM Lab banner. */
export function stemStatusLine(st: StemStatus): string {
  if (!st.available) return st.reason ?? 'The STEM agent is not available.';
  const domains = Object.keys(st.domains).length;
  return `Connected to the SLAI STEM agent: ${st.operationCount} operations in ${domains} domains.`;
}
