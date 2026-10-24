// Turning what is typed into a form into the parameters an operation expects, and back (for loading an example or an old entry).
import type { FormField, FormOp } from './types.js';
import { lines, splitList, splitPairs } from './util.js';

export type FieldState = string | boolean | string[][];
export type FormState = Record<string, FieldState>;

export function visible(field: FormField, state: FormState): boolean {
  if (!field.when) return true;
  return Object.entries(field.when).every(([key, allowed]) => allowed.includes(String(state[key] ?? '')));
}

export function emptyState(op: FormOp): FormState {
  const st: FormState = {};
  for (const f of op.fields) {
    if (f.kind === 'bool') st[f.key] = f.default === true;
    else if (f.kind === 'select') st[f.key] = f.options && f.options.length ? (typeof f.default === 'string' ? f.default : f.options[0].value) : '';
    else if (f.kind === 'table') st[f.key] = [emptyRow(f), emptyRow(f)];
    else st[f.key] = '';
  }
  return st;
}

export function emptyRow(f: FormField): string[] {
  return (f.columns ?? []).map(() => '');
}

const blank = (v: unknown): boolean => v === undefined || v === null || (typeof v === 'string' && v.trim() === '');

export interface Collected { params: Record<string, unknown>; missing: string[] }

/** Parameters for the visible fields; empty fields are left out, so the backend can tell what was not given. */
export function collect(op: FormOp, state: FormState): Collected {
  const params: Record<string, unknown> = {};
  const missing: string[] = [];
  for (const f of op.fields) {
    if (!visible(f, state)) continue;
    const raw = state[f.key];
    let value: unknown;
    switch (f.kind) {
      case 'bool': value = raw === true; break;
      case 'list': value = typeof raw === 'string' && !blank(raw) ? splitList(raw) : undefined; break;
      case 'pairs': value = typeof raw === 'string' && !blank(raw) ? splitPairs(raw) : undefined; break;
      case 'textarea': value = typeof raw === 'string' && !blank(raw) ? (f.lines ? lines(raw) : raw) : undefined; break;
      case 'table': value = tableValue(f, Array.isArray(raw) ? raw : []); break;
      default: value = typeof raw === 'string' && !blank(raw) ? raw.trim() : undefined;
    }
    if (value === undefined || (Array.isArray(value) && value.length === 0) || (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0)) {
      if (f.required) missing.push(f.label);
      continue;
    }
    params[f.key] = value;
  }
  return { params, missing };
}

function tableValue(f: FormField, rows: string[][]): unknown {
  const cols = f.columns ?? [];
  const used = rows.filter((r) => r.some((c) => !blank(c)));
  if (f.shape === 'object') {
    const obj: Record<string, unknown> = {};
    for (const r of used) {
      const key = (r[0] ?? '').trim();
      if (!key) continue;
      if (cols.length === 2) obj[key] = (r[1] ?? '').trim();
      else {
        const inner: Record<string, string> = {};
        for (let i = 1; i < cols.length; i++) if (!blank(r[i])) inner[cols[i].key] = r[i].trim();
        obj[key] = inner;
      }
    }
    return Object.keys(obj).length ? obj : undefined;
  }
  const arr = used.map((r) => {
    const o: Record<string, string> = {};
    cols.forEach((c, i) => { if (!blank(r[i])) o[c.key] = r[i].trim(); });
    return o;
  }).filter((o) => Object.keys(o).length > 0);
  return arr.length ? arr : undefined;
}

/** The form state that produces ``params`` (the inverse of ``collect``). */
export function seed(op: FormOp, params: Record<string, unknown>): FormState {
  const st = emptyState(op);
  for (const f of op.fields) {
    const v = params[f.key];
    if (v === undefined || v === null) continue;
    switch (f.kind) {
      case 'bool': st[f.key] = v === true; break;
      case 'list': st[f.key] = Array.isArray(v) ? v.map(String).join(' ') : String(v); break;
      case 'pairs': st[f.key] = Array.isArray(v) ? v.map((p) => (Array.isArray(p) ? p.map(String).join(' ') : String(p))).join('\n') : String(v); break;
      case 'textarea': st[f.key] = Array.isArray(v) ? v.map(String).join('\n') : String(v); break;
      case 'table': st[f.key] = tableRows(f, v); break;
      default: st[f.key] = String(v);
    }
  }
  return st;
}

function tableRows(f: FormField, v: unknown): string[][] {
  const cols = f.columns ?? [];
  const rows: string[][] = [];
  if (f.shape === 'object' && v && typeof v === 'object' && !Array.isArray(v)) {
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      if (val && typeof val === 'object') rows.push([k, ...cols.slice(1).map((c) => String((val as Record<string, unknown>)[c.key] ?? ''))]);
      else rows.push([k, String(val ?? '')]);
    }
  } else if (Array.isArray(v)) {
    for (const item of v) {
      if (item && typeof item === 'object') rows.push(cols.map((c) => String((item as Record<string, unknown>)[c.key] ?? '')));
    }
  }
  rows.push(emptyRow(f));
  return rows;
}

/** A short title for a saved domain entry, e.g. "Molar mass: Ca(OH)2". */
export function describeInput(op: FormOp, params: Record<string, unknown>): string {
  for (const key of ['formula', 'equation', 'expression', 'sequence', 'reaction', 'element', 'parent1', 'solveFor', 'value']) {
    const v = params[key];
    if (typeof v === 'string' && v.trim()) return `${op.title}: ${v.trim().replace(/\s+/g, ' ').slice(0, 48)}`;
  }
  return op.title;
}
