// Reading domain results: a one-line summary for the worksheet and the helpers the generic result view uses.
import type { NumText } from './types.js';
import { isRecord } from './util.js';

export function isNum(x: unknown): x is NumText {
  return isRecord(x) && typeof x.text === 'string' && typeof x.latex === 'string';
}

const PREFERRED: Array<[string, string]> = [
  ['result', ''], ['molarMass', 'M = '], ['balanced', ''], ['empirical', 'Empirical formula '], ['pH', 'pH = '], ['pressure', 'P = '], ['enthalpy', 'ΔH = '], ['deltaG', 'ΔG = '],
  ['mean', 'mean = '], ['uncertainty', '± '], ['reported', ''], ['percentError', 'error = '], ['concentration', 'c = '], ['molarity', 'c = '], ['slope', 'slope = '],
  ['vmax', 'Vmax = '], ['gcContent', 'GC = '], ['phenotypeRatio', 'phenotype ratio '], ['verdict', ''], ['limiting', 'limiting reagent: '], ['p', 'p = '], ['protein', ''], ['velocity', 'v = '], ['count', ''], ['value', ''],
];

/** One line that says what a result is, for the worksheet and for exports. */
export function headlineOf(result: Record<string, unknown>): string {
  if (result.ok === false && isRecord(result.error)) return 'Error: ' + String(result.error.message ?? '');
  for (const [key, prefix] of PREFERRED) {
    const v = result[key];
    if (isNum(v)) return prefix + v.text;
    if (typeof v === 'string' && v && v.length < 140) return prefix + v;
  }
  for (const [key, v] of Object.entries(result)) {
    if (isNum(v) && key !== 'ok') return `${labelOf(key)} = ${v.text}`;
  }
  const rows = result.species ?? result.genotypes ?? result.enzymes ?? result.elements ?? result.items;
  if (Array.isArray(rows)) return `${rows.length} row${rows.length === 1 ? '' : 's'}`;
  return 'Done';
}

const ACRONYMS: Record<string, string> = { gc: 'GC', od: 'OD', cfu: 'CFU', dna: 'DNA', rna: 'RNA', orf: 'ORF', si: 'SI', std: 'std', gravy: 'GRAVY', pi: 'pI', ice: 'ICE' };

/** "molarMass" -> "Molar mass", "pH" -> "pH", "gcContent" -> "GC content". */
export function labelOf(key: string): string {
  if (/^p[A-Z][A-Za-z]?$/.test(key)) return key;                       // pH, pOH, pKa, pKb
  if (/^[A-Z][A-Za-z]?\d?$/.test(key)) return key;                      // Ka, Kw, K, P1, T2
  const words = key.replace(/pOH/g, ' @POH ').replace(/pH/g, ' @PH ').replace(/([a-z])(?=[A-Z])/g, '$1 ').replace(/_/g, ' ').split(' ').filter(Boolean).map((w) => (w === '@PH' ? 'pH' : w === '@POH' ? 'pOH' : w));
  const out = words.map((w, i) => {
    const lower = w.toLowerCase();
    if (w === 'pH' || w === 'pOH') return w;
    if (ACRONYMS[lower]) return ACRONYMS[lower];
    if (i === 0 && w.length === 1) return w === 'r' ? 'R' : w;
    if (/^p[A-Z]/.test(w) && w.length <= 3) return w;
    return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
  });
  return out.join(' ').replace(/\bph\b/gi, 'pH').replace(/\bpoh\b/gi, 'pOH');
}

export type PtList = Array<[number, number]>;
export function isPoints(x: unknown): x is PtList {
  return Array.isArray(x) && x.length >= 2 && x.every((p) => Array.isArray(p) && p.length === 2 && typeof p[0] === 'number' && typeof p[1] === 'number');
}

export function isRowList(x: unknown): x is Array<Record<string, unknown>> {
  return Array.isArray(x) && x.length > 0 && x.every(isRecord);
}

/** Warnings and notes may arrive as strings or as {message}. */
export function messageOf(w: unknown): string {
  if (typeof w === 'string') return w;
  if (isRecord(w) && typeof w.message === 'string') return w.message;
  return '';
}

/** One readable line for the answer of /api/assist/crosscheck: what the STEM agent said, or why it did not run. */
export function crossCheckSummary(r: Record<string, unknown>): string {
  if (r.ran !== true) return `Cross-check not run: ${typeof r.reason === 'string' && r.reason ? r.reason : 'the SLAI STEM agent is not available.'}`;
  const rows = Array.isArray(r.rows) ? r.rows.filter((x): x is Record<string, unknown> => typeof x === 'object' && x !== null) : [];
  if (!rows.length) return 'Cross-check: the STEM agent returned nothing to compare.';
  const parts = rows.map((x) => {
    const name = labelOf(String(x.statistic ?? '')).toLowerCase();
    if (x.agree === true) return `${name} agrees`;
    if (x.agree === false) return `${name} differs (SciCal ${String(x.scical)}, STEM agent ${String(x.stemAgent)})`;
    return `${name}: ${String(x.status ?? 'no answer')}${x.reason ? ` (${String(x.reason)})` : ''}`;
  });
  return `Cross-check with the SLAI STEM agent: ${parts.join('; ')}. SciCal's own value is the one shown.`;
}
