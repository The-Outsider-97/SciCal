// Small pure helpers shared by the client and its tests.

export function uid(prefix = ''): string {
  const bytes = new Uint8Array(8);
  const c = (globalThis as { crypto?: { getRandomValues(a: Uint8Array): Uint8Array } }).crypto;
  if (c) c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return prefix + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}

export function debounce<A extends unknown[]>(fn: (...a: A) => void, ms: number): ((...a: A) => void) & { cancel(): void; flush(): void } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let last: A | undefined;
  const run = (...a: A): void => {
    last = a;
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => { timer = undefined; fn(...(last as A)); }, ms);
  };
  run.cancel = (): void => { if (timer !== undefined) clearTimeout(timer); timer = undefined; };
  run.flush = (): void => { if (timer !== undefined) { clearTimeout(timer); timer = undefined; fn(...(last as A)); } };
  return run;
}

/** "specificHeat1" -> "Specific heat 1", "pH" -> "pH", "mean" -> "Mean". */
export function words(key: string): string {
  if (/^[a-z]{1,2}[A-Z][A-Za-z]?$/.test(key) && key.length <= 4) return key;                   // pH, pKa, pOH
  const spaced = key.replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/([A-Za-z])(\d)/g, '$1 $2');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

/** Split numbers separated by spaces, commas, semicolons or line breaks. */
export function splitList(text: string): string[] {
  return text.split(/[\s,;]+/).map((t) => t.trim()).filter((t) => t.length > 0);
}

/** One pair per line ("x y", "x, y" or "x;y"). */
export function splitPairs(text: string): string[][] {
  return text.split(/\r?\n/).map((line) => splitList(line)).filter((p) => p.length > 0);
}

export function lines(text: string): string[] {
  return text.split(/\r?\n/).map((t) => t.trim()).filter((t) => t.length > 0);
}

export function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function timeLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x);
}

export function fileSafe(name: string): string {
  return name.replace(/[^\w.\- ]+/g, '_').replace(/\s+/g, ' ').trim().slice(0, 80) || 'worksheet';
}
