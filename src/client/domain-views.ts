// The few results that are better shown as a picture of the thing than as a list: the periodic table, a Punnett square,
// the genetic code, the unit catalogue, the constants and the formula library.
import { isNum, labelOf } from '../core/results.js';
import { isRecord } from '../core/util.js';
import { h, replace } from './dom.js';
import { math } from './math-dom.js';
import { cellText } from './domain-results.js';
import { dialog } from './ui.js';

type R = Record<string, unknown>;
const rows = (v: unknown): R[] => (Array.isArray(v) ? v.filter(isRecord) : []);
const str = (v: unknown): string => (typeof v === 'string' ? v : v === null || v === undefined ? '' : String(v));

// ------------------------------------------------------------------------------------------------------------------ periodic table
const CATEGORY_LABELS: Array<[string, string]> = [
  ['alkali metal', 'Alkali metal'], ['alkaline earth metal', 'Alkaline earth'], ['transition metal', 'Transition metal'], ['post-transition metal', 'Post-transition'],
  ['metalloid', 'Metalloid'], ['nonmetal', 'Nonmetal'], ['halogen', 'Halogen'], ['noble gas', 'Noble gas'], ['lanthanide', 'Lanthanide'], ['actinide', 'Actinide'],
];
const slug = (c: string): string => 'cat-' + c.replace(/[^a-z]+/g, '-');

function position(e: R): [number, number] | null {
  const z = Number(e.z);
  if (z >= 57 && z <= 71) return [9, z - 57 + 3];
  if (z >= 89 && z <= 103) return [10, z - 89 + 3];
  const g = Number(e.group);
  const p = Number(e.period);
  return Number.isFinite(g) && Number.isFinite(p) && g > 0 ? [p, g] : null;
}

export function periodicTable(elements: R[], onPick: (e: R) => void): { el: HTMLElement; filter(q: string): void } {
  const cells = new Map<number, HTMLElement>();
  const grid = h('div', { class: 'ptable', role: 'group', 'aria-label': 'Periodic table of the elements' });
  const place = (el: HTMLElement, row: number, col: number): void => { el.style.setProperty('grid-row', String(row)); el.style.setProperty('grid-column', String(col)); };
  for (const e of elements) {
    const pos = position(e);
    if (!pos) continue;
    const z = Number(e.z);
    const cell = h('button', { class: `pt-cell ${slug(str(e.category))}`, type: 'button', 'aria-label': `${str(e.name)}, atomic number ${z}`, 'aria-pressed': 'false', title: `${str(e.name)} (${z})`, on: { click: () => onPick(e) } },
      h('span', { class: 'z', text: String(z) }), h('span', { class: 'sy', text: str(e.symbol) }), h('span', { class: 'nm', text: str(e.name) }));
    place(cell, pos[0] <= 7 ? pos[0] : pos[0] + 0.0, pos[1]);
    if (pos[0] >= 9) cell.style.setProperty('grid-row', String(pos[0] + 0)); // rows 9 and 10, row 8 is the gap
    cells.set(z, cell);
    grid.appendChild(cell);
  }
  const gap = h('div', { class: 'pt-spacer', 'aria-hidden': 'true' });
  place(gap, 8, 1);
  grid.appendChild(gap);
  const legend = h('ul', { class: 'legend' }, CATEGORY_LABELS.map(([c, label]) => h('li', null, h('span', { class: `swatch ${slug(c)}`, style: { background: 'var(--cat)' } }), label)));
  return {
    el: h('div', { class: 'periodic' }, grid, legend),
    filter(q: string) {
      const t = q.trim().toLowerCase();
      for (const e of elements) {
        const cell = cells.get(Number(e.z));
        if (!cell) continue;
        const hit = !t || [str(e.name), str(e.symbol), String(e.z), str(e.category), str(e.state), str(e.block)].some((x) => x.toLowerCase().includes(t));
        cell.classList.toggle('dim', !hit);
      }
    },
  };
}

export function elementDialog(res: R): void {
  const e = isRecord(res.element) ? res.element : {};
  const unc = e.uncertainty === null || e.uncertainty === undefined ? '' : ` (±${str(e.uncertainty)})`;
  const facts: Array<[string, string]> = [
    ['Atomic number', str(e.z)], ['Atomic weight', `${str(e.weight)}${unc}`], ['Weight kind', str(e.weightKind)], ['Period', str(e.period)], ['Group', e.group === null ? 'f-block' : str(e.group)],
    ['Block', str(e.block)], ['Category', str(e.category)], ['State at 20 °C', str(e.state)], ['Electronegativity (Pauling)', e.electronegativity === null || e.electronegativity === undefined ? 'not defined' : str(e.electronegativity)],
    ['Electron configuration', str(e.configuration)],
  ];
  const iso = rows(e.isotopes);
  const body = h('div', { style: { display: 'grid', gap: '.9rem' } },
    h('div', { class: 'kvs' }, facts.filter(([, v]) => v).map(([k, v]) => h('div', { class: 'kv' }, h('div', { class: 'k', text: k }), h('div', { class: 'v', text: v })))),
    str(e.configurationNote) ? h('p', { class: 'muted', text: str(e.configurationNote) }) : null,
    str(e.weightNote) ? h('p', { class: 'muted', text: str(e.weightNote) }) : null,
    iso.length ? h('div', null, h('div', { class: 'sectitle', text: 'Isotopes' }), simpleTable(iso)) : h('p', { class: 'muted', text: 'No isotope data is stored for this element.' }));
  dialog(`${str(e.name)} (${str(e.symbol)})`, body, { wide: true });
}

export function simpleTable(data: R[], hide: string[] = []): HTMLElement {
  const keys: string[] = [];
  for (const r of data) for (const k of Object.keys(r)) if (!keys.includes(k) && !hide.includes(k)) keys.push(k);
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', null, h('tr', null, keys.map((k) => h('th', { text: labelOf(k) })))),
    h('tbody', null, data.map((r) => h('tr', null, keys.map((k) => h('td', { class: typeof r[k] === 'number' || isNum(r[k]) ? 'num' : '', text: cellText(r[k]) })))))));
}

// ------------------------------------------------------------------------------------------------------------------ Punnett square
export function punnettSquare(res: R): HTMLElement {
  const g1 = (Array.isArray(res.gametes1) ? res.gametes1 : []).map(str);
  const g2 = (Array.isArray(res.gametes2) ? res.gametes2 : []).map(str);
  const grid = (Array.isArray(res.grid) ? res.grid : []) as unknown[][];
  const dominance = (gt: string): string => (/[A-Z]/.test(gt) ? 'dom' : 'rec');
  const table = h('table', { class: 'punnett', 'aria-label': 'Punnett square: columns are gametes from parent 1, rows are gametes from parent 2' },
    h('thead', null, h('tr', null, h('th', { scope: 'col', 'aria-label': 'corner' }), g1.map((g) => h('th', { scope: 'col', text: g })))),
    h('tbody', null, g2.map((g, r) => h('tr', null, h('th', { scope: 'row', text: g }), (grid[r] ?? []).map((c) => h('td', { class: dominance(str(c)), text: str(c) }))))));
  return h('div', { class: 'section' }, h('div', { class: 'sectitle', text: 'Punnett square' }), h('div', { class: 'table-wrap' }, table),
    h('p', { class: 'muted', text: 'Columns: gametes of parent 1. Rows: gametes of parent 2.' }));
}

// ------------------------------------------------------------------------------------------------------------------ genetic code
const BASES = ['T', 'C', 'A', 'G'];
const THREE: Record<string, string> = { A: 'Ala', R: 'Arg', N: 'Asn', D: 'Asp', C: 'Cys', Q: 'Gln', E: 'Glu', G: 'Gly', H: 'His', I: 'Ile', L: 'Leu', K: 'Lys', M: 'Met', F: 'Phe', P: 'Pro', S: 'Ser', T: 'Thr', W: 'Trp', Y: 'Tyr', V: 'Val' };
export function geneticCode(res: R): HTMLElement {
  const code = new Map<string, R>();
  for (const c of rows(res.code)) code.set(str(c.codon), c);
  const head = h('tr', null, h('th', { scope: 'col', text: '1st base' }), BASES.map((b) => h('th', { scope: 'col', text: `2nd base: ${b}` })));
  const body = BASES.map((first) => h('tr', null, h('th', { scope: 'row', text: first }), BASES.map((second) => h('td', { class: 'codon' }, BASES.map((third) => {
    const codon = first + second + third;
    const c = code.get(codon);
    const sym = str(c?.aa);
    const stop = sym === '*' || /stop/i.test(str(c?.name));
    return h('div', { class: `cl ${stop ? 'stop' : ''}`, title: str(c?.name) },
      h('span', { class: 'cd', text: codon }), h('strong', { text: stop ? 'Stop' : sym }), h('span', { class: 'muted', text: stop ? '' : THREE[sym] ?? '' }));
  })))));
  return h('div', { class: 'section' }, h('div', { class: 'sectitle', text: 'Standard genetic code (DNA codons)' }), h('div', { class: 'table-wrap' }, h('table', { class: 'data code' }, h('thead', null, head), h('tbody', null, body))),
    str(res.table) ? h('p', { class: 'muted source', text: str(res.table) }) : null);
}

// ------------------------------------------------------------------------------------------------------------------ units and constants
export function unitCatalogue(res: R, onPick: (symbol: string) => void): HTMLElement {
  return h('div', { class: 'section', style: { display: 'grid', gap: '1rem' } }, rows(res.categories).map((cat) => h('div', null,
    h('div', { class: 'sectitle', text: str(cat.category) }),
    h('div', { class: 'chips' }, rows(cat.units).map((u) => h('button', { class: 'chip', type: 'button', title: `${str(u.name)}: click to copy the symbol`, text: str(u.symbol), on: { click: () => onPick(str(u.symbol)) } }))))));
}

export function constantsTable(res: R, onCopy: (text: string) => void): HTMLElement {
  const cs = rows(res.constants);
  const meta = isRecord(res.meta) ? res.meta : {};
  return h('div', { class: 'section', style: { display: 'grid', gap: '.6rem' } },
    h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, ['Name', 'Symbol', 'Value', 'Unit', 'Uncertainty'].map((t) => h('th', { text: t })))),
      h('tbody', null, cs.map((c) => h('tr', null,
        h('td', { text: str(c.name) }), h('td', { text: str(c.symbol) }),
        h('td', { class: 'num' }, h('button', { class: 'linkbtn', type: 'button', title: 'Copy the value', text: str(c.value), on: { click: () => onCopy(str(c.value)) } })),
        h('td', { text: str(c.unit).replace(/\*/g, '·') }), h('td', { class: 'num', text: c.exact === true ? 'exact' : c.uncertainty === null || c.uncertainty === undefined ? '' : str(c.uncertainty) })))))),
    cs.length ? null : h('p', { class: 'muted', text: 'No constant matches that search.' }),
    h('p', { class: 'muted source', text: [str(meta.version), str(meta.source), str(meta.note)].filter(Boolean).join(' · ') }));
}

// ------------------------------------------------------------------------------------------------------------------ formula library
export function formulaLibrary(res: R, onUse: (f: R) => void): HTMLElement {
  const fs = rows(res.formulas);
  const cats = (Array.isArray(res.categories) ? res.categories : []).map(str);
  const cards = fs.map((f) => h('article', { class: 'kv formula' },
    h('div', { class: 'k', text: `${str(f.category)} · ${str(f.name)}` }),
    h('div', { class: 'v' }, typeof f.latex === 'string' ? math(f.latex) : h('span', { text: str(f.equation) })),
    h('div', { class: 'x', text: rows(f.variables).map((v) => `${str(v.symbol)} = ${str(v.name)}${v.unit ? ` [${str(v.unit)}]` : ''}`).join(' · ') }),
    str(f.note) ? h('div', { class: 'x', text: str(f.note) }) : null,
    h('div', null, h('button', { class: 'btn small', type: 'button', text: 'Solve with this formula', on: { click: () => onUse(f) } }))));
  return h('div', { class: 'section', style: { display: 'grid', gap: '.8rem' } },
    cats.length ? h('p', { class: 'muted', text: `Categories: ${cats.join(', ')}` }) : null,
    cards.length ? h('div', { class: 'kvs wide' }, cards) : h('p', { class: 'muted', text: 'No formula matches that search.' }));
}

export function setText(el: HTMLElement, text: string): void { replace(el, text); }
