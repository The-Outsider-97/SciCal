// Worksheet logic that does not need the browser: which lines define state, what the next calculation must replay.
import type { CalcResult, Entry } from './types.js';

const ANS = /\bans\b/;

export function definesOf(result: CalcResult): string[] | undefined {
  if (!result.ok || !result.name) return undefined;
  if (result.kind === 'assignment' || result.kind === 'definition') return [result.name];
  return undefined;
}

/** The lines the server replays before a new line: everything that defines a variable or function, plus the previous
 *  answer's line when the new input uses ``ans``. */
export function contextFor(entries: Entry[], input: string): string[] {
  const out = entries.filter((e) => e.kind === 'calc' && e.defines && e.defines.length > 0 && typeof e.input === 'string').map((e) => e.input as string);
  if (ANS.test(input)) {
    const calcs = entries.filter((e) => e.kind === 'calc' && e.ok !== false && typeof e.input === 'string' && e.result?.kind !== 'definition');
    const tail: string[] = [];
    for (let i = calcs.length - 1; i >= 0 && tail.length < 6; i--) {
      const line = calcs[i].input as string;
      tail.unshift(line);
      if (!ANS.test(line)) break;
    }
    out.push(...tail);
  }
  return out.slice(-400);
}

export function newEntryId(): string {
  const a = new Uint8Array(6);
  const c = (globalThis as { crypto?: { getRandomValues(a: Uint8Array): Uint8Array } }).crypto;
  if (c) c.getRandomValues(a); else for (let i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 256);
  return Array.from(a, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function nowIso(): string {
  return new Date().toISOString().replace(/\.\d+Z$/, 'Z');
}
