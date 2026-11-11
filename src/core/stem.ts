// Logic for the STEM checks that needs no browser: what a verdict is called, which entries can be checked, how a difference is written.
import type { Entry, StemCheck, Verification } from './types.js';

export type Tone = 'ok' | 'warn' | 'muted';

export interface Badge { text: string; tone: Tone; title: string }

/** The small label shown on a result once the STEM agent has been asked. Words as well as a symbol, so colour is never the only signal. */
export function verdictBadge(v: Verification | undefined): Badge | null {
  if (!v || !v.ran) return null;
  const c = v.counts ?? {};
  const run = (c.agree ?? 0) + (c.differ ?? 0);
  if (v.verdict === 'agree') return { text: `STEM ✓ agrees (${run}/${run})`, tone: 'ok', title: v.summary };
  if (v.verdict === 'differ') return { text: `STEM ≠ differs (${c.differ ?? 0}/${run})`, tone: 'warn', title: v.summary };
  if (v.verdict === 'none') return { text: 'STEM: no check for this', tone: 'muted', title: v.summary };
  return null;
}

export function statusWord(s: StemCheck['status']): string {
  return s === 'agree' ? 'agrees' : s === 'differ' ? 'differs' : s === 'skipped' ? 'not run' : 'failed';
}

export function statusMark(s: StemCheck['status']): string {
  return s === 'agree' ? '✓' : s === 'differ' ? '≠' : s === 'skipped' ? '–' : '!';
}

/** A difference for display: nothing, zero, or a short number with an exponent when it is tiny. */
export function formatDifference(d: number | null | undefined): string {
  if (d === null || d === undefined || !Number.isFinite(d)) return '';
  if (d === 0) return '0';
  const a = Math.abs(d);
  return a < 1e-3 || a >= 1e6 ? d.toExponential(2).replace('e+', 'e') : String(Number(d.toPrecision(3)));
}

/** Whether the STEM agent has anything to compute again for this entry (the server decides what to do with the rest). */
export function canCheck(entry: Pick<Entry, 'kind' | 'ok' | 'domain' | 'op' | 'result'>, checkable: Array<[string, string]> | undefined): boolean {
  if (entry.ok === false || entry.result?.ok === false) return false;
  if (entry.kind === 'calc') return true;
  if (entry.kind === 'domain') return !!entry.domain && !!entry.op && (checkable ?? []).some(([d, o]) => d === entry.domain && o === entry.op);
  return false;
}

/** The part of an entry the server needs to check it: what was asked, not the picture or the working. */
export function entryForCheck(e: Entry): Record<string, unknown> {
  const out: Record<string, unknown> = { kind: e.kind, workspace: e.workspace, input: e.input, domain: e.domain, op: e.op, params: e.params, result: e.result };
  for (const k of Object.keys(out)) if (out[k] === undefined) delete out[k];
  return out;
}

/** Keep a stored verification small: the check rows are kept, long free text is cut. */
export function slim(v: Verification): Verification {
  const cut = (s: string | null): string | null => (s && s.length > 400 ? s.slice(0, 399) + '…' : s);
  return { ...v, summary: cut(v.summary) ?? '', checks: v.checks.slice(0, 20).map((c) => ({ ...c, note: cut(c.note), scical: cut(c.scical), stem: cut(c.stem) })) };
}
