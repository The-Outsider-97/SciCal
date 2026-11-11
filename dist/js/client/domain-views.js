// The few results that are better shown as a picture of the thing than as a list: the periodic table, a Punnett square,
// the genetic code, the unit catalogue, the constants and the formula library.
import { isNum, labelOf } from '../core/results.js';
import { isRecord } from '../core/util.js';
import { h, replace, s } from './dom.js';
import { math } from './math-dom.js';
import { cellText } from './domain-results.js';
import { dialog } from './ui.js';
import { atomScene, nucleusScene, orbitalAngularScene, scientificScene, nucleotideColor } from './science3d.js';
const rows = (v) => (Array.isArray(v) ? v.filter(isRecord) : []);
const str = (v) => (typeof v === 'string' ? v : v === null || v === undefined ? '' : String(v));
// ------------------------------------------------------------------------------------------------------------------ periodic table
const CATEGORY_LABELS = [
    ['alkali metal', 'Alkali metal'], ['alkaline earth metal', 'Alkaline earth'], ['transition metal', 'Transition metal'], ['post-transition metal', 'Post-transition'],
    ['metalloid', 'Metalloid'], ['nonmetal', 'Nonmetal'], ['halogen', 'Halogen'], ['noble gas', 'Noble gas'], ['lanthanide', 'Lanthanide'], ['actinide', 'Actinide'],
];
const slug = (c) => 'cat-' + c.replace(/[^a-z]+/g, '-');
function position(e) {
    const z = Number(e.z);
    if (z >= 57 && z <= 71)
        return [9, z - 57 + 3];
    if (z >= 89 && z <= 103)
        return [10, z - 89 + 3];
    const g = Number(e.group);
    const p = Number(e.period);
    return Number.isFinite(g) && Number.isFinite(p) && g > 0 ? [p, g] : null;
}
export function periodicTable(elements, onPick) {
    const cells = new Map();
    const grid = h('div', { class: 'ptable', role: 'group', 'aria-label': 'Periodic table of the elements' });
    const place = (el, row, col) => { el.style.setProperty('grid-row', String(row)); el.style.setProperty('grid-column', String(col)); };
    for (const e of elements) {
        const pos = position(e);
        if (!pos)
            continue;
        const z = Number(e.z);
        const cell = h('button', { class: `pt-cell ${slug(str(e.category))}`, type: 'button', 'aria-label': `${str(e.name)}, atomic number ${z}`, 'aria-pressed': 'false', title: `${str(e.name)} (${z})`, on: { click: () => onPick(e) } }, h('span', { class: 'z', text: String(z) }), h('span', { class: 'sy', text: str(e.symbol) }), h('span', { class: 'nm', text: str(e.name) }));
        place(cell, pos[0] <= 7 ? pos[0] : pos[0] + 0.0, pos[1]);
        if (pos[0] >= 9)
            cell.style.setProperty('grid-row', String(pos[0] + 0)); // rows 9 and 10, row 8 is the gap
        cells.set(z, cell);
        grid.appendChild(cell);
    }
    const gap = h('div', { class: 'pt-spacer', 'aria-hidden': 'true' });
    place(gap, 8, 1);
    grid.appendChild(gap);
    const legend = h('ul', { class: 'legend' }, CATEGORY_LABELS.map(([c, label]) => h('li', null, h('span', { class: `swatch ${slug(c)}`, style: { background: 'var(--cat)' } }), label)));
    return {
        el: h('div', { class: 'periodic' }, grid, legend),
        filter(q) {
            const t = q.trim().toLowerCase();
            for (const e of elements) {
                const cell = cells.get(Number(e.z));
                if (!cell)
                    continue;
                const hit = !t || [str(e.name), str(e.symbol), String(e.z), str(e.category), str(e.state), str(e.block)].some((x) => x.toLowerCase().includes(t));
                cell.classList.toggle('dim', !hit);
            }
        },
    };
}
export function elementDialog(res) {
    const e = isRecord(res.element) ? res.element : {};
    const unc = e.uncertainty === null || e.uncertainty === undefined ? '' : ` (±${str(e.uncertainty)})`;
    const facts = [
        ['Atomic number', str(e.z)], ['Atomic weight', `${str(e.weight)}${unc}`], ['Weight kind', str(e.weightKind)], ['Period', str(e.period)], ['Group', e.group === null ? 'f-block' : str(e.group)],
        ['Block', str(e.block)], ['Category', str(e.category)], ['State at 20 °C', str(e.state)], ['Electronegativity (Pauling)', e.electronegativity === null || e.electronegativity === undefined ? 'not defined' : str(e.electronegativity)],
        ['Electron configuration', str(e.configuration)],
    ];
    const iso = rows(e.isotopes);
    const body = h('div', { style: { display: 'grid', gap: '.9rem' } }, h('div', { class: 'kvs' }, facts.filter(([, v]) => v).map(([k, v]) => h('div', { class: 'kv' }, h('div', { class: 'k', text: k }), h('div', { class: 'v', text: v })))), str(e.configurationNote) ? h('p', { class: 'muted', text: str(e.configurationNote) }) : null, str(e.weightNote) ? h('p', { class: 'muted', text: str(e.weightNote) }) : null, iso.length ? h('div', null, h('div', { class: 'sectitle', text: 'Isotopes' }), simpleTable(iso)) : h('p', { class: 'muted', text: 'No isotope data is stored for this element.' }));
    const sceneHost = h('div');
    const isotope = h('select', { 'aria-label': 'Isotope' }, iso.length ? iso.map((item) => h('option', { value: String(item.A), text: String(e.symbol) + '-' + String(item.A) })) : h('option', { value: '', text: 'No validated isotope data in SciCal' }));
    // A missing mass number must NOT be substituted with a rounded average atomic weight.
    isotope.disabled = iso.length === 0;
    const charge = h('input', { type: 'number', min: '-3', max: String(Math.min(3, Number(e.z))), step: '1', value: '0', 'aria-label': 'Net ionic charge' });
    const mode = h('select', { 'aria-label': 'Atomic display mode' }, h('option', { value: 'shell', text: 'Educational electron shells' }), h('option', { value: 'nucleus', text: 'Nuclear composition' }), h('option', { value: 'orbital', text: 'Orbital angular symmetry (qualitative)' }));
    const orbital = h('select', { 'aria-label': 'Orbital shape' }, h('option', { value: 's', text: 's · spherical (l=0)' }), h('option', { value: 'p', text: 'pₓ/pᵧ/p_z · show p_z (l=1)' }), h('option', { value: 'd', text: 'd · show d_z² (l=2)' }), h('option', { value: 'f', text: 'f · show f_z³ (l=3)' }));
    const orbitalField = h('label', { class: 'field' }, h('span', { class: 'label', text: 'Orbital shape (illustrative)' }), orbital);
    orbitalField.hidden = true;
    const dataLine = h('p', { class: 'muted' });
    body.prepend(h('div', { class: 'section' }, h('div', { class: 'sectitle', text: 'Interactive atomic model' }), h('div', { class: 'row' }, h('label', { class: 'field' }, h('span', { class: 'label', text: 'Isotope' }), isotope), h('label', { class: 'field' }, h('span', { class: 'label', text: 'Ion charge (e)' }), charge), h('label', { class: 'field' }, h('span', { class: 'label', text: 'Display mode' }), mode), orbitalField), dataLine, sceneHost));
    let current = null;
    const update = () => {
        current?.destroy();
        const z = Number(e.z);
        const mass = iso.length ? Number(isotope.value) : null;
        const q = Math.trunc(Number(charge.value));
        if (!Number.isInteger(q) || q < -3 || q > Math.min(3, z)) {
            replace(sceneHost, h('p', { role: 'alert', text: 'Choose an integer charge between -3 and ' + Math.min(3, z) + '.' }));
            return;
        }
        dataLine.textContent = z + ' protons · ' + (mass === null ? 'neutrons unknown' : (mass - z) + ' neutrons') + ' · ' + (z - q) + ' electrons. ' +
            'Electron configuration shown in the details is the neutral ground state; ionic shell positions are illustrative.';
        orbitalField.hidden = mode.value !== 'orbital';
        if (mode.value === 'orbital' && z - q === 0) {
            replace(sceneHost, h('p', { role: 'alert', text: 'A fully ionized atom has no bound electrons to visualize.' }));
            return;
        }
        const selectedScene = mode.value === 'nucleus' ? nucleusScene(z, mass, str(e.configuration)) :
            mode.value === 'orbital' ? orbitalAngularScene(orbital.value) :
                atomScene(z, mass, q, str(e.configuration));
        current = scientificScene(selectedScene);
        replace(sceneHost, current.el);
    };
    isotope.addEventListener('change', update);
    charge.addEventListener('change', update);
    mode.addEventListener('change', update);
    orbital.addEventListener('change', update);
    const handle = dialog(`${str(e.name)} (${str(e.symbol)})`, body, { wide: true, onClose: () => current?.destroy() });
    void handle;
    update();
}
export function simpleTable(data, hide = []) {
    const keys = [];
    for (const r of data)
        for (const k of Object.keys(r))
            if (!keys.includes(k) && !hide.includes(k))
                keys.push(k);
    return h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', null, h('tr', null, keys.map((k) => h('th', { text: labelOf(k) })))), h('tbody', null, data.map((r) => h('tr', null, keys.map((k) => h('td', { class: typeof r[k] === 'number' || isNum(r[k]) ? 'num' : '', text: cellText(r[k]) })))))));
}
// ------------------------------------------------------------------------------------------------------------------ Punnett square
export function punnettSquare(res) {
    const g1 = (Array.isArray(res.gametes1) ? res.gametes1 : []).map(str);
    const g2 = (Array.isArray(res.gametes2) ? res.gametes2 : []).map(str);
    const grid = (Array.isArray(res.grid) ? res.grid : []);
    const dominance = (gt) => (/[A-Z]/.test(gt) ? 'dom' : 'rec');
    const table = h('table', { class: 'punnett', 'aria-label': 'Punnett square: columns are gametes from parent 1, rows are gametes from parent 2' }, h('thead', null, h('tr', null, h('th', { scope: 'col', 'aria-label': 'corner' }), g1.map((g) => h('th', { scope: 'col', text: g })))), h('tbody', null, g2.map((g, r) => h('tr', null, h('th', { scope: 'row', text: g }), (grid[r] ?? []).map((c) => h('td', { class: dominance(str(c)), text: str(c) }))))));
    return h('div', { class: 'section' }, h('div', { class: 'sectitle', text: 'Punnett square' }), h('div', { class: 'table-wrap' }, table), h('p', { class: 'muted', text: 'Columns: gametes of parent 1. Rows: gametes of parent 2.' }));
}
// ------------------------------------------------------------------------------------------------------------------ genetic code
const BASES = ['U', 'C', 'A', 'G'];
const THREE = { A: 'Ala', R: 'Arg', N: 'Asn', D: 'Asp', C: 'Cys', Q: 'Gln', E: 'Glu', G: 'Gly', H: 'His', I: 'Ile', L: 'Leu', K: 'Lys', M: 'Met', F: 'Phe', P: 'Pro', S: 'Ser', T: 'Thr', W: 'Trp', Y: 'Tyr', V: 'Val' };
export function geneticCode(res) {
    // The authoritative mapping stays in SciCal's NCBI table 1 dataset.
    const code = new Map();
    for (const entry of rows(res.code))
        code.set(str(entry.codon).replace(/T/g, 'U'), entry);
    const keys = BASES.flatMap((first) => BASES.flatMap((second) => BASES.map((third) => first + second + third)));
    const selectedInfo = h('p', { class: 'note-line', 'aria-live': 'polite' });
    const search = h('input', { type: 'search', placeholder: 'Search codon or amino acid (e.g. AUG, Met, leucine, Stop)', 'aria-label': 'Search the genetic code' });
    const matches = h('div', { class: 'science-controls', 'aria-live': 'polite' });
    const views = h('div');
    const tableButton = h('button', { class: 'btn small', type: 'button', text: 'Table' });
    const wheelButton = h('button', { class: 'btn small', type: 'button', text: 'Circular code' });
    const head = h('tr', null, h('th', { scope: 'col', text: '1st base' }), BASES.map((b) => h('th', { scope: 'col', text: '2nd base: ' + b })));
    let active = 'AUG';
    let mode = 'table';
    const cells = new Map();
    const label = (codon) => {
        const entry = code.get(codon);
        const symbol = str(entry?.aa);
        return codon + ' → ' + (symbol === '*' ? 'Stop' : str(entry?.name) + ' (' + (THREE[symbol] ?? symbol) + ')');
    };
    const update = (codon) => {
        if (!code.has(codon))
            return;
        active = codon;
        selectedInfo.textContent = label(codon) + (codon === 'AUG' ? ' · canonical initiation codon (context dependent)' : '') +
            ' · Complementary anticodon aligned 3′→5′: ' + (codon.replace(/[AUCG]/g, (base) => ({ A: 'U', U: 'A', C: 'G', G: 'C' }[base]))) +
            (str(code.get(codon)?.aa) === '*' ? ' (stop is recognized by a release factor, not tRNA)' : '');
        for (const [key, el] of cells) {
            el.setAttribute('aria-pressed', String(key === codon));
            el.classList.toggle('selected', key === codon);
        }
        const svg = views.querySelector('svg');
        if (svg)
            for (const sector of Array.from(svg.querySelectorAll('path[data-codon]'))) {
                const on = sector.dataset.codon === codon;
                sector.setAttribute('stroke-width', on ? '4' : '.75');
                sector.setAttribute('stroke', on ? '#111' : '#eee');
            }
    };
    const body = BASES.map((first) => h('tr', null, h('th', { scope: 'row', text: first }), BASES.map((second) => h('td', { class: 'codon' }, BASES.map((third) => {
        const codon = first + second + third;
        const entry = code.get(codon);
        const sym = str(entry?.aa);
        const stop = sym === '*';
        const cell = h('button', { type: 'button', class: 'cl science-codon-choice' + (stop ? ' stop' : ''), title: label(codon), 'aria-label': label(codon),
            on: { click: () => update(codon) } }, h('span', { class: 'cd' }, [...codon].map((base) => h('span', { class: 'base', text: base, style: { color: nucleotideColor(base) } }))), h('strong', { text: stop ? 'Stop' : sym }), h('span', { class: 'muted', text: stop ? '' : THREE[sym] ?? '' }));
        cells.set(codon, cell);
        return cell;
    })))));
    const table = h('div', { class: 'table-wrap' }, h('table', { class: 'data code' }, h('thead', null, head), h('tbody', null, body)));
    const polar = (r, degrees) => {
        const rad = (degrees - 90) * Math.PI / 180;
        return [260 + r * Math.cos(rad), 260 + r * Math.sin(rad)];
    };
    const wedge = (inner, outer, startAngle, endAngle) => {
        const a = polar(outer, startAngle), b = polar(outer, endAngle), c = polar(inner, endAngle), d = polar(inner, startAngle);
        const large = endAngle - startAngle > 180 ? 1 : 0;
        return `M${a[0]} ${a[1]} A ${outer} ${outer} 0 ${large} 1 ${b[0]} ${b[1]} L${c[0]} ${c[1]} A ${inner} ${inner} 0 ${large} 0 ${d[0]} ${d[1]} Z`;
    };
    const wheel = s('svg', { viewBox: '0 0 520 520', class: 'science-wheel', role: 'group', 'aria-label': 'Circular genetic code from the centre outward: first, second and third RNA bases' });
    for (let depth = 0; depth < 3; depth++) {
        const groups = Math.pow(4, depth + 1);
        const step = 360 / groups;
        const inner = [46, 109, 174][depth], outer = [104, 168, 237][depth];
        for (let i = 0; i < groups; i++) {
            const base = BASES[i % 4];
            const start = i * step, end = (i + 1) * step;
            const attrs = {
                d: wedge(inner, outer, start, end),
                fill: nucleotideColor(base),
                stroke: '#eee', 'stroke-width': '.75',
                opacity: depth === 2 ? '.86' : '.75',
            };
            if (depth === 2) {
                const codon = keys[i];
                attrs['data-codon'] = codon;
                attrs.role = 'button';
                attrs.tabindex = '0';
                attrs['aria-label'] = label(codon);
            }
            const sector = s('path', attrs);
            if (depth === 2) {
                const codon = keys[i];
                sector.addEventListener('click', () => update(codon));
                sector.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') {
                    ev.preventDefault();
                    update(codon);
                } });
                sector.append(s('title', null, label(codon)));
            }
            wheel.append(sector);
            if (depth < 2) {
                const mid = polar((inner + outer) / 2, (start + end) / 2);
                wheel.append(s('text', { x: String(mid[0]), y: String(mid[1]), 'text-anchor': 'middle', 'dominant-baseline': 'central', fill: '#101820',
                    'font-size': depth === 0 ? '24' : '12', 'font-weight': '700' }, base));
            }
        }
    }
    wheel.append(s('text', { x: '260', y: '258', 'text-anchor': 'middle', 'dominant-baseline': 'central', 'font-size': '17', fill: 'currentColor' }, '5′'));
    wheel.append(s('text', { x: '260', y: '280', 'text-anchor': 'middle', 'font-size': '12', fill: 'currentColor' }, '1 → 2 → 3'));
    const wheelWrap = h('div', null, wheel, h('p', { class: 'muted', text: 'Read center → outer edge: first, second and third mRNA nucleotide (5′→3′). Select an outer wedge for the resulting amino acid. Color and labels identify the bases.' }));
    const paint = () => {
        replace(views, mode === 'table' ? table : wheelWrap);
        tableButton.setAttribute('aria-pressed', String(mode === 'table'));
        wheelButton.setAttribute('aria-pressed', String(mode === 'wheel'));
        update(active);
    };
    tableButton.addEventListener('click', () => { mode = 'table'; paint(); });
    wheelButton.addEventListener('click', () => { mode = 'wheel'; paint(); });
    const filter = () => {
        const typed = search.value.trim().toUpperCase();
        const q = /^[ACGTU]{1,3}$/.test(typed) ? typed.replace(/T/g, 'U') : typed;
        const results = keys.filter((codon) => !q || codon.includes(q) || str(code.get(codon)?.name).toUpperCase().includes(q) ||
            str(code.get(codon)?.aa).toUpperCase() === q || (THREE[str(code.get(codon)?.aa)] ?? '').toUpperCase() === q);
        for (const [codon, cell] of cells)
            cell.hidden = Boolean(q) && !results.includes(codon);
        replace(matches, h('span', { class: 'muted', text: results.length + ' of 64 codons' }), results.length <= 24 ? results.map((codon) => h('button', { type: 'button', class: 'btn small', text: codon, title: label(codon), on: { click: () => update(codon) } })) : null);
        if (q.length === 3 && code.has(q))
            update(q);
    };
    search.addEventListener('input', filter);
    paint();
    filter();
    return h('div', { class: 'section science-code-explorer' }, h('div', { class: 'sectitle', text: 'Interactive standard genetic code · RNA 5′→3′' }), h('div', { class: 'science-controls' }, search, tableButton, wheelButton), matches, selectedInfo, views, h('p', { class: 'muted source', text: str(res.table) + '. 64 codons; 61 sense codons and three stops. Alternative initiation sites depend on organism and context.' }));
}
// ------------------------------------------------------------------------------------------------------------------ units and constants
export function unitCatalogue(res, onPick) {
    return h('div', { class: 'section', style: { display: 'grid', gap: '1rem' } }, rows(res.categories).map((cat) => h('div', null, h('div', { class: 'sectitle', text: str(cat.category) }), h('div', { class: 'chips' }, rows(cat.units).map((u) => h('button', { class: 'chip', type: 'button', title: `${str(u.name)}: click to copy the symbol`, text: str(u.symbol), on: { click: () => onPick(str(u.symbol)) } }))))));
}
export function constantsTable(res, onCopy) {
    const cs = rows(res.constants);
    const meta = isRecord(res.meta) ? res.meta : {};
    return h('div', { class: 'section', style: { display: 'grid', gap: '.6rem' } }, h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', null, h('tr', null, ['Name', 'Symbol', 'Value', 'Unit', 'Uncertainty'].map((t) => h('th', { text: t })))), h('tbody', null, cs.map((c) => h('tr', null, h('td', { text: str(c.name) }), h('td', { text: str(c.symbol) }), h('td', { class: 'num' }, h('button', { class: 'linkbtn', type: 'button', title: 'Copy the value', text: str(c.value), on: { click: () => onCopy(str(c.value)) } })), h('td', { text: str(c.unit).replace(/\*/g, '·') }), h('td', { class: 'num', text: c.exact === true ? 'exact' : c.uncertainty === null || c.uncertainty === undefined ? '' : str(c.uncertainty) })))))), cs.length ? null : h('p', { class: 'muted', text: 'No constant matches that search.' }), h('p', { class: 'muted source', text: [str(meta.version), str(meta.source), str(meta.note)].filter(Boolean).join(' · ') }));
}
// ------------------------------------------------------------------------------------------------------------------ formula library
export function formulaLibrary(res, onUse) {
    const fs = rows(res.formulas);
    const cats = (Array.isArray(res.categories) ? res.categories : []).map(str);
    const cards = fs.map((f) => h('article', { class: 'kv formula' }, h('div', { class: 'k', text: `${str(f.category)} · ${str(f.name)}` }), h('div', { class: 'v' }, typeof f.latex === 'string' ? math(f.latex) : h('span', { text: str(f.equation) })), h('div', { class: 'x', text: rows(f.variables).map((v) => `${str(v.symbol)} = ${str(v.name)}${v.unit ? ` [${str(v.unit)}]` : ''}`).join(' · ') }), str(f.note) ? h('div', { class: 'x', text: str(f.note) }) : null, h('div', null, h('button', { class: 'btn small', type: 'button', text: 'Solve with this formula', on: { click: () => onUse(f) } }))));
    return h('div', { class: 'section', style: { display: 'grid', gap: '.8rem' } }, cats.length ? h('p', { class: 'muted', text: `Categories: ${cats.join(', ')}` }) : null, cards.length ? h('div', { class: 'kvs wide' }, cards) : h('p', { class: 'muted', text: 'No formula matches that search.' }));
}
export function setText(el, text) { replace(el, text); }
//# sourceMappingURL=domain-views.js.map