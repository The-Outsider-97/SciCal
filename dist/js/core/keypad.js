const k = (label, insert, title, cls = 'fn') => ({ label, insert, title, cls });
export const PAD_BASIC = [
    [k('(', '(', 'Opening bracket', 'op'), k(')', ')', 'Closing bracket', 'op'), k('xʸ', '^', 'Power', 'op'), k('√', 'sqrt(|)', 'Square root', 'fn'), { label: '⌫', action: 'back', title: 'Delete the character before the cursor', cls: 'ctl' }],
    [k('7', '7', '7', 'num'), k('8', '8', '8', 'num'), k('9', '9', '9', 'num'), k('÷', '/', 'Divide', 'op'), { label: 'AC', action: 'clear', title: 'Clear the input line', cls: 'ctl' }],
    [k('4', '4', '4', 'num'), k('5', '5', '5', 'num'), k('6', '6', '6', 'num'), k('×', '*', 'Multiply', 'op'), k('π', 'pi', 'Pi', 'fn')],
    [k('1', '1', '1', 'num'), k('2', '2', '2', 'num'), k('3', '3', '3', 'num'), k('−', '-', 'Subtract', 'op'), k('e', 'e', "Euler's number", 'fn')],
    [k('0', '0', '0', 'num'), k('.', '.', 'Decimal point', 'num'), k('Ans', 'ans', 'The previous answer', 'fn'), k('+', '+', 'Add', 'op'), { label: '=', action: 'enter', title: 'Calculate', cls: 'accent' }],
];
export const PAD_SCIENTIFIC = [
    [k('sin', 'sin(|)', 'Sine'), k('cos', 'cos(|)', 'Cosine'), k('tan', 'tan(|)', 'Tangent'), k('ln', 'ln(|)', 'Natural logarithm'), k('log', 'log10(|)', 'Base-10 logarithm')],
    [k('sin⁻¹', 'asin(|)', 'Inverse sine'), k('cos⁻¹', 'acos(|)', 'Inverse cosine'), k('tan⁻¹', 'atan(|)', 'Inverse tangent'), k('eˣ', 'exp(|)', 'e to the power'), k('10ˣ', '10^(|)', '10 to the power')],
    [k('sinh', 'sinh(|)', 'Hyperbolic sine'), k('cosh', 'cosh(|)', 'Hyperbolic cosine'), k('tanh', 'tanh(|)', 'Hyperbolic tangent'), k('x²', '^2', 'Square', 'op'), k('x³', '^3', 'Cube', 'op')],
    [k('|x|', 'abs(|)', 'Absolute value'), k('n!', '!', 'Factorial', 'op'), k('nCr', 'nCr(|, )', 'Combinations'), k('nPr', 'nPr(|, )', 'Permutations'), k('mod', 'mod(|, )', 'Remainder')],
    [k('∛', 'cbrt(|)', 'Cube root'), k('ⁿ√', 'root(|, )', 'n-th root'), k('floor', 'floor(|)', 'Round down'), k('round', 'round(|)', 'Round to the nearest integer'), k('i', 'i', 'Imaginary unit')],
    [k('1/x', '1/(|)', 'Reciprocal'), k('EE', 'e', 'Exponent: 1.5e3 means 1.5×10³', 'op'), k('%', '/100', 'Percent', 'op'), k('gcd', 'gcd(|, )', 'Greatest common divisor'), k('lcm', 'lcm(|, )', 'Least common multiple')],
];
export const PAD_FUNCTIONS = [
    [k('d/dx', 'diff(|, x)', 'Derivative'), k('∫', 'integral(|, x)', 'Integral (add limits a, b for a definite integral)'), k('lim', 'limit(|, x, 0)', 'Limit'), k('Σ', 'sum(|, k, 1, 10)', 'Sum over k'), k('Taylor', 'taylor(|, x, 0, 5)', 'Taylor series')],
    [k('solve', 'solve(|)', 'Solve an equation, e.g. solve(x^2 = 4)'), k('expand', 'expand(|)', 'Expand'), k('factor', 'factor(|)', 'Factor'), k('simplify', 'simplify(|)', 'Simplify'), k('subs', 'subs(|, x, )', 'Substitute a value')],
    [k('[ ]', '[|]', 'A list or vector: [1, 2, 3]'), k('matrix', '[[|, ], [, ]]', 'A 2×2 matrix: [[a, b], [c, d]]'), k('det', 'det(|)', 'Determinant'), k('inv', 'inv(|)', 'Inverse matrix'), k('Aᵀ', 'transpose(|)', 'Transpose')],
    [k('eig', 'eigenvals(|)', 'Eigenvalues'), k('rref', 'rref(|)', 'Row-reduced echelon form'), k('dot', 'dot(|, )', 'Dot product'), k('cross', 'cross(|, )', 'Cross product'), k('norm', 'norm(|)', 'Length of a vector')],
    [k('mean', 'mean(|)', 'Mean of a list'), k('median', 'median(|)', 'Median'), k('std', 'std(|)', 'Sample standard deviation'), k('normalcdf', 'normalcdf(|, 0, 1)', 'Normal cumulative probability'), k('binompdf', 'binompdf(|, , )', 'Binomial probability')],
];
export const PAD_UNITS = [
    [k('m', ' m', 'metre'), k('km', ' km', 'kilometre'), k('cm', ' cm', 'centimetre'), k('mm', ' mm', 'millimetre'), k('in', ' in', 'inch')],
    [k('kg', ' kg', 'kilogram'), k('g', ' g', 'gram'), k('mg', ' mg', 'milligram'), k('lb', ' lb', 'pound'), k('mol', ' mol', 'mole')],
    [k('s', ' s', 'second'), k('min', ' min', 'minute'), k('h', ' h', 'hour'), k('Hz', ' Hz', 'hertz'), k('m/s', ' m/s', 'metres per second')],
    [k('N', ' N', 'newton'), k('J', ' J', 'joule'), k('W', ' W', 'watt'), k('Pa', ' Pa', 'pascal'), k('atm', ' atm', 'atmosphere')],
    [k('L', ' L', 'litre'), k('mL', ' mL', 'millilitre'), k('K', ' K', 'kelvin'), k('°C', ' degC', 'degrees Celsius'), k('→', ' -> ', 'Convert to another unit', 'op')],
];
export const PADS = {
    basic: { title: 'Basic', rows: PAD_BASIC },
    scientific: { title: 'Scientific', rows: PAD_SCIENTIFIC },
    functions: { title: 'Algebra & calculus', rows: PAD_FUNCTIONS },
    units: { title: 'Units', rows: PAD_UNITS },
};
/** Apply a key's text at the cursor of ``value``: returns the new text and where the cursor goes.
 *  With a selection, a key such as sin(|) wraps it: "x" selected + sin(|) gives sin(x) with the cursor after it. */
export function applyInsert(value, start, end, insert) {
    const bar = insert.indexOf('|');
    if (bar < 0)
        return { value: value.slice(0, start) + insert + value.slice(end), cursor: start + insert.length };
    const before = insert.slice(0, bar);
    const after = insert.slice(bar + 1);
    const inner = value.slice(start, end);
    return {
        value: value.slice(0, start) + before + inner + after + value.slice(end),
        cursor: inner ? start + before.length + inner.length + after.length : start + before.length,
    };
}
//# sourceMappingURL=keypad.js.map