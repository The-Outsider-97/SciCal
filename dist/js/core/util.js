// Small pure helpers shared by the client and its tests.
export function uid(prefix = '') {
    const bytes = new Uint8Array(8);
    const c = globalThis.crypto;
    if (c)
        c.getRandomValues(bytes);
    else
        for (let i = 0; i < bytes.length; i++)
            bytes[i] = Math.floor(Math.random() * 256);
    return prefix + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}
export function clamp(x, lo, hi) {
    return Math.min(hi, Math.max(lo, x));
}
export function debounce(fn, ms) {
    let timer;
    let last;
    const run = (...a) => {
        last = a;
        if (timer !== undefined)
            clearTimeout(timer);
        timer = setTimeout(() => { timer = undefined; fn(...last); }, ms);
    };
    run.cancel = () => { if (timer !== undefined)
        clearTimeout(timer); timer = undefined; };
    run.flush = () => { if (timer !== undefined) {
        clearTimeout(timer);
        timer = undefined;
        fn(...last);
    } };
    return run;
}
/** "specificHeat1" -> "Specific heat 1", "pH" -> "pH", "mean" -> "Mean". */
export function words(key) {
    if (/^[a-z]{1,2}[A-Z][A-Za-z]?$/.test(key) && key.length <= 4)
        return key; // pH, pKa, pOH
    const spaced = key.replace(/_/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/([A-Za-z])(\d)/g, '$1 $2');
    return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}
/** Split numbers separated by spaces, commas, semicolons or line breaks. */
export function splitList(text) {
    return text.split(/[\s,;]+/).map((t) => t.trim()).filter((t) => t.length > 0);
}
/** One pair per line ("x y", "x, y" or "x;y"). */
export function splitPairs(text) {
    return text.split(/\r?\n/).map((line) => splitList(line)).filter((p) => p.length > 0);
}
export function lines(text) {
    return text.split(/\r?\n/).map((t) => t.trim()).filter((t) => t.length > 0);
}
export function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
export function timeLabel(iso) {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime()))
        return '';
    return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}
export function isRecord(x) {
    return typeof x === 'object' && x !== null && !Array.isArray(x);
}
export function fileSafe(name) {
    return name.replace(/[^\w.\- ]+/g, '_').replace(/\s+/g, ' ').trim().slice(0, 80) || 'worksheet';
}
//# sourceMappingURL=util.js.map