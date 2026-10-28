// Number and unit text for the Constants page. Pure string functions (no floats for the digits), so they are unit-tested without a browser.
const SUP = { '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹', '-': '⁻' };
const sup = (n) => String(n).split('').map((c) => SUP[c] ?? c).join('');
/** A decimal string such as "6.62607015e-34" split into its digits and the power of ten of the first digit (exact: strings only, no floats). */
export function sciParts(text) {
    const m = /^(-?)(\d*)\.?(\d*)(?:e([+-]?\d+))?$/i.exec(text.trim());
    if (!m || (m[2] === '' && m[3] === ''))
        return null;
    let digits = m[2] + m[3];
    let point = m[2].length;
    let lead = 0;
    while (lead < digits.length - 1 && digits[lead] === '0')
        lead++;
    digits = digits.slice(lead);
    point -= lead;
    return { sign: m[1], digits, e10: point + parseInt(m[4] ?? '0', 10) - 1 };
}
/** "6.62607015 × 10⁻³⁴"; values near 1 stay plain. Very long strings are shortened (the full text is always one click away). */
export function prettyNumber(text, maxDigits = 16) {
    const p = sciParts(text);
    if (!p)
        return text;
    let digits = p.digits.replace(/0+$/, '') || '0';
    const cut = digits.length > maxDigits;
    if (cut)
        digits = digits.slice(0, maxDigits);
    const ell = cut ? '…' : '';
    if (p.e10 >= -3 && p.e10 <= 6) {
        const intLen = p.e10 + 1;
        let plain;
        if (intLen <= 0)
            plain = '0.' + '0'.repeat(-intLen) + digits;
        else if (digits.length <= intLen)
            plain = digits + '0'.repeat(intLen - digits.length);
        else
            plain = digits.slice(0, intLen) + '.' + digits.slice(intLen);
        const [whole, frac] = plain.split('.');
        const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
        return p.sign + grouped + (frac ? '.' + frac : '') + ell;
    }
    const mant = digits[0] + (digits.length > 1 ? '.' + digits.slice(1) : '');
    return `${p.sign}${mant}${ell} × 10${sup(p.e10)}`;
}
export const toNumber = (p) => Number(`${p.digits[0]}.${p.digits.slice(1) || '0'}e${p.e10}`);
/** Unit and dimension text for display: 'W*m^2' becomes 'W·m²'. The copied text keeps the parseable form. */
export const prettyUnit = (u) => u.replace(/\*/g, '·').replace(/\^(-?\d+)/g, (_m, n) => sup(Number(n)));
/** value as a plain machine-readable text (what Copy value puts on the clipboard). */
export const plain = (text) => text.replace(/e\+/i, 'e');
//# sourceMappingURL=numtext.js.map