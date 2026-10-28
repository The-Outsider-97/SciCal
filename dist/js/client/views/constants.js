// The Constants page: a searchable library over the one constants store (scical/data/constants.json, read through the server),
// plus the person's own financial parameters, which are assumptions kept apart from the constants.
import { plain, prettyNumber, prettyUnit, sciParts, toNumber } from '../../core/numtext.js';
import { debounce, isRecord, uid } from '../../core/util.js';
import { api, ApiError } from '../api.js';
import { h, replace } from '../dom.js';
import { navigate } from '../shell.js';
import { store } from '../store.js';
import { copyText, emptyNote, glyph, toast } from '../ui.js';
const str = (v) => (v === undefined || v === null ? '' : String(v));
const rows = (v) => (Array.isArray(v) ? v.filter(isRecord) : []);
const KIND_SHORT = { exact: 'exact', exact_derived: 'exact', mathematical: 'mathematical', measured: 'measured', derived: 'derived', nominal: 'nominal (IAU)', convention: 'convention' };
// ------------------------------------------------------------------------------------------------------------------ favourites and recents
// Per-viewer conveniences only; a browser that blocks storage simply starts empty.
const LS_FAV = 'scical.constants.favorites';
const LS_RECENT = 'scical.constants.recent';
function readList(key) {
    try {
        const v = JSON.parse(localStorage.getItem(key) ?? '[]');
        return Array.isArray(v) ? v.filter((x) => typeof x === 'string').slice(0, 100) : [];
    }
    catch {
        return [];
    }
}
function writeList(key, list) {
    try {
        localStorage.setItem(key, JSON.stringify(list.slice(0, 100)));
    }
    catch { /* storage unavailable: nothing is remembered */ }
}
// ------------------------------------------------------------------------------------------------------------------ the view
export function createConstantsView() {
    let query = '';
    let category = ''; // '' = all, a category id, 'favorites', 'recent' or 'financial'
    let data = null;
    let seq = 0;
    let favorites = readList(LS_FAV);
    let recents = readList(LS_RECENT);
    let formulaNames = null;
    const search = h('input', { type: 'search', 'aria-label': 'Search constants by name or symbol', placeholder: 'Search by name or symbol: planck, k_B, avogadro, π …', autocomplete: 'off', spellcheck: 'false' });
    const chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Category' });
    const intro = h('p', { class: 'muted' });
    const list = h('div', { class: 'const-list', 'aria-live': 'polite' });
    const finBox = h('section', { class: 'card', hidden: true, 'aria-label': 'Financial parameters' });
    const el = h('div', { class: 'consts' }, h('section', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', { text: 'Scientific constants' })), intro, h('div', { class: 'const-search' }, search), chips), list, finBox);
    const remember = (key) => {
        recents = [key, ...recents.filter((k) => k !== key)].slice(0, 12);
        writeList(LS_RECENT, recents);
    };
    const toggleFav = (key) => {
        favorites = favorites.includes(key) ? favorites.filter((k) => k !== key) : [key, ...favorites];
        writeList(LS_FAV, favorites);
        if (category === 'favorites')
            void load();
        else
            paint();
    };
    const load = async () => {
        const mine = ++seq;
        if (category === 'financial') {
            data = data ?? null;
            paint();
            return;
        }
        const params = category === 'favorites' ? { keys: favorites } : category === 'recent' ? { keys: recents } : { query, category };
        try {
            const res = await api.domain('constants', 'catalogue', params, store.settings, uid());
            if (mine !== seq)
                return;
            if (res.ok === false)
                throw new ApiError(res.error?.message ?? 'The constants could not be loaded.', 0, res.error?.code ?? 'error');
            data = res;
            paint();
        }
        catch (e) {
            if (mine !== seq)
                return;
            replace(list, h('div', { class: 'note-line error', role: 'alert', text: e instanceof ApiError ? e.message : 'The constants could not be loaded.' }));
        }
    };
    const loadSoon = debounce(() => void load(), 200);
    search.addEventListener('input', () => { query = search.value; if (category === 'favorites' || category === 'recent' || category === 'financial')
        category = ''; loadSoon(); });
    // ---------------------------------------------------------------------------------------------------------- a constant
    const copyBtn = (label, text, key, what) => h('button', { class: 'btn small', type: 'button', title: `Copy ${what}`, on: { click: () => { void copyText(text, `Copied ${what}`); remember(key); } } }, glyph('copy'), ' ', label);
    const names = async () => {
        if (formulaNames)
            return formulaNames;
        formulaNames = new Map();
        try {
            const res = await api.domain('formulas', 'formula_library', {}, store.settings, uid());
            for (const f of rows(res.formulas))
                formulaNames.set(str(f.id), str(f.name));
        }
        catch { /* ids are shown instead of names */ }
        return formulaNames;
    };
    const converter = (c) => {
        const unit = str(c.unit);
        if (!unit)
            return h('span');
        const input = h('input', { type: 'text', 'aria-label': `Convert ${str(c.name)} into this unit`, placeholder: `a unit of the same kind, e.g. ${unit}`, autocomplete: 'off', spellcheck: 'false' });
        const result = h('div', { class: 'const-conv', 'aria-live': 'polite' });
        const go = async () => {
            if (!input.value.trim())
                return;
            try {
                const res = await api.domain('constants', 'convert', { key: c.key, to: input.value.trim() }, store.settings, uid());
                if (res.ok === false) {
                    replace(result, h('span', { class: 'error', role: 'alert', text: res.error?.message ?? 'That conversion is not possible.' }));
                    return;
                }
                const val = isRecord(res.result) ? str(res.result.text) : '';
                const unc = isRecord(res.uncertainty) ? ` ± ${str(res.uncertainty.text)}` : '';
                remember(str(c.key));
                replace(result, h('strong', { text: val }), unc ? h('span', { class: 'muted', text: unc }) : null, ' ', h('button', { class: 'linkbtn', type: 'button', text: 'copy', title: 'Copy the converted value with its unit', on: { click: () => void copyText(`${plain(str(res.decimal))} ${input.value.trim()}`, 'Copied the converted value') } }));
            }
            catch (e) {
                replace(result, h('span', { class: 'error', role: 'alert', text: e instanceof ApiError ? e.message : 'The conversion failed.' }));
            }
        };
        input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') {
            ev.preventDefault();
            void go();
        } });
        return h('div', { class: 'const-convert' }, h('label', { class: 'label', text: 'Convert to' }), h('div', { class: 'row' }, input, h('button', { class: 'btn small', type: 'button', text: 'Convert', on: { click: () => void go() } })), result);
    };
    const details = (c) => {
        const apps = (Array.isArray(c.applications) ? c.applications : []).map(str);
        const appBox = h('div', { class: 'chips' });
        if (apps.length) {
            void names().then((nm) => replace(appBox, apps.map((id) => h('button', { class: 'chip', type: 'button', title: 'Open this formula in the Formulas workspace', text: nm.get(id) ?? id,
                on: { click: () => void navigate({ workspace: 'formulas', kind: 'formula', payload: { op: 'formula_solve', params: { formulaId: id }, go: false } }) } }))));
        }
        const kv = (k, v) => (v ? h('div', { class: 'kv' }, h('div', { class: 'k', text: k }), h('div', { class: 'v', text: v })) : null);
        const full = str(c.valueExact);
        return h('div', { class: 'const-details' }, h('p', { text: str(c.description) }), h('div', { class: 'kvs' }, kv('Type', str(c.kindLabel)), kv('Dimension', prettyUnit(str(c.dimension))), kv('Significant figures', c.sigfigs === null || c.sigfigs === undefined ? 'not limited (defined exactly)' : c.exact === true ? `not limited (exact); ${str(c.sigfigs)} digits stored` : str(c.sigfigs)), kv('Stored value', plain(full)), kv('Source', str(c.source)), kv('Edition', str(c.edition)), kv('Note', str(c.note)), c.uncertaintyText ? kv('Standard uncertainty', `${plain(str(c.uncertaintyText))} ${prettyUnit(str(c.unit))}`) : null), apps.length ? h('div', null, h('div', { class: 'sectitle', text: 'Used in formulas' }), appBox) : null, converter(c));
    };
    const card = (c) => {
        const key = str(c.key);
        const unit = str(c.unit);
        const unitShown = prettyUnit(unit);
        const text = str(c.valueExact);
        const exact = c.exact === true;
        const fav = favorites.includes(key);
        let unc = null;
        if (!exact && c.uncertaintyText) {
            const v = sciParts(text);
            const u = sciParts(str(c.uncertaintyText));
            const rel = v && u ? toNumber(u) / toNumber(v) : NaN;
            unc = h('div', { class: 'x', text: `standard uncertainty ${prettyNumber(str(c.uncertaintyText))}${unitShown ? ' ' + unitShown : ''}` + (Number.isFinite(rel) ? ` (relative ${prettyNumber(rel.toExponential(1), 3)})` : '') });
        }
        const badgeCls = exact ? 'badge' : 'badge plain';
        const expr = str(c.expression);
        return h('article', { class: 'const-card', 'aria-label': str(c.name) }, h('div', { class: 'const-head' }, h('div', null, h('h3', { text: str(c.name) }), h('span', { class: 'const-sym', text: str(c.symbol) })), h('span', { class: badgeCls, text: KIND_SHORT[str(c.kind)] ?? str(c.kind) }), h('button', { class: 'iconbtn', type: 'button', 'aria-pressed': String(fav), 'aria-label': fav ? `Remove ${str(c.name)} from favourites` : `Add ${str(c.name)} to favourites`, title: fav ? 'Remove from favourites' : 'Add to favourites', on: { click: () => toggleFav(key) } }, glyph(fav ? 'pin' : 'plus'))), h('div', { class: 'const-val' }, h('span', { class: 'num', title: plain(text), text: prettyNumber(text) }), unitShown ? h('span', { class: 'const-unit', text: ` ${unitShown}` }) : h('span', { class: 'muted', text: ' (dimensionless)' })), unc, h('div', { class: 'row const-actions' }, copyBtn('Value', plain(text), key, 'the value'), copyBtn('Symbol', str(c.symbol), key, 'the symbol'), copyBtn('Value + unit', unit ? `${plain(text)} ${unit}` : plain(text), key, 'the value with its unit'), h('button', { class: 'btn small primary', type: 'button', title: `Insert ${expr} into the SciCal expression`, on: { click: () => { remember(key); void navigate({ workspace: 'math', kind: 'insert', payload: { insert: expr } }); toast(`Inserted ${expr}`, 'ok', 1800); } } }, 'Insert ', h('code', { text: expr }))), h('details', { class: 'const-more' }, h('summary', { text: 'Source, precision and conversion' }), details(c)));
    };
    // ---------------------------------------------------------------------------------------------------------- categories
    const chipBtn = (id, label, count) => h('button', { class: 'chip' + (id === 'financial' ? ' fin' : ''), type: 'button', 'aria-pressed': String(category === id), text: count === undefined ? label : `${label} (${count})`,
        on: { click: () => { category = id; paintChips(); void load(); } } });
    const paintChips = () => {
        const cats = rows(data?.categories);
        replace(chips, chipBtn('', 'All', typeof data?.total === 'number' ? data.total : undefined), cats.map((c) => chipBtn(str(c.id), str(c.title), typeof c.count === 'number' ? c.count : undefined)), chipBtn('favorites', `Favourites (${favorites.length})`), chipBtn('recent', 'Recent'), chipBtn('financial', 'Financial parameters'));
    };
    const paint = () => {
        paintChips();
        const meta = isRecord(data?.meta) ? data.meta : {};
        const cats = rows(data?.categories);
        const cat = cats.find((c) => str(c.id) === category);
        replace(intro, [str(meta.version), str(meta.source)].filter(Boolean).join(' · '), cat ? h('span', { class: 'muted' }, ' — ', str(cat.description)) : null);
        finBox.hidden = category !== 'financial';
        list.hidden = category === 'financial';
        if (category === 'financial') {
            paintFinancial();
            return;
        }
        const items = rows(data?.constants);
        if (!items.length) {
            replace(list, emptyNote(category === 'favorites' ? 'No favourites yet. Use the + on a constant to keep it here.' : category === 'recent' ? 'Nothing here yet. Constants you copy, insert or convert are listed.' : 'No constant matches that search.'));
            return;
        }
        replace(list, h('p', { class: 'muted', text: `${items.length} ${items.length === 1 ? 'constant' : 'constants'}${query ? ` matching “${query}”` : ''}` }), items.map(card));
    };
    // ---------------------------------------------------------------------------------------------------------- financial parameters
    const currencies = () => {
        const f = store.forms.finance?.ops?.flatMap((o) => o.fields).find((x) => x.key === 'currency');
        return (f?.options ?? []).map((o) => [o.value, o.label]);
    };
    const paintFinancial = () => {
        const p = store.prefs;
        const num = (id, label, hint, value, key, lo, hi) => {
            const input = h('input', { type: 'text', inputmode: 'decimal', id, value: value === undefined || value === null ? '' : String(value), placeholder: 'not set', autocomplete: 'off' });
            input.addEventListener('change', () => {
                const t = input.value.trim().replace('%', '').replace(',', '.');
                if (t === '') {
                    store.setPrefs({ [key]: null });
                    toast('Cleared', 'ok', 1400);
                    return;
                }
                const n = Number(t);
                if (!Number.isFinite(n) || n < lo || n > hi || (key === 'finPlaces' && !Number.isInteger(n))) {
                    toast(`${label}: enter a number from ${lo} to ${hi}${key === 'finPlaces' ? ' (whole)' : ''}.`, 'error');
                    input.value = p[key] === undefined || p[key] === null ? '' : String(p[key]);
                    return;
                }
                store.setPrefs({ [key]: n });
                toast('Saved', 'ok', 1400);
            });
            return h('div', { class: 'field' }, h('label', { class: 'label', for: id, text: label }), input, h('span', { class: 'hint', text: hint }));
        };
        const cur = h('select', { id: 'fin-cur', 'aria-label': 'Currency' }, [['', 'none (plain numbers)'], ...currencies().filter(([v]) => v !== '')].map(([v, l]) => h('option', { value: v, text: l, selected: (p.finCurrency ?? '') === v })));
        cur.addEventListener('change', () => { store.setPrefs({ finCurrency: cur.value || null }); toast('Saved', 'ok', 1400); });
        replace(finBox, h('div', { class: 'card-head' }, h('h2', { text: 'Financial parameters' })), h('div', { class: 'note-line', role: 'note', text: 'These are your own assumptions, not constants of nature. They are not part of any reference edition and nothing here comes from a market feed. They only pre-fill empty fields in the Finance forms; you can overwrite any of them there.' }), h('div', { class: 'fields' }, h('div', { class: 'field' }, h('label', { class: 'label', for: 'fin-cur', text: 'Currency' }), cur, h('span', { class: 'hint', text: 'Only changes how amounts are written.' })), num('fin-places', 'Decimals shown for money', 'Display only, 0 to 8.', p.finPlaces, 'finPlaces', 0, 8), num('fin-disc', 'Discount rate (% a year)', 'Pre-fills the discount rate in NPV, DCF and payback (used as typed: per year when the cash flows are yearly).', p.finDiscountRate, 'finDiscountRate', -50, 1000), num('fin-infl', 'Inflation (% a year)', 'Pre-fills the inflation rate in Finance forms.', p.finInflation, 'finInflation', -50, 1000)), h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', text: 'Clear all', on: { click: () => { store.setPrefs({ finCurrency: null, finPlaces: null, finDiscountRate: null, finInflation: null }); paintFinancial(); toast('Financial parameters cleared', 'ok', 1600); } } }), h('button', { class: 'btn', type: 'button', text: 'Open Finance', on: { click: () => void navigate({ workspace: 'finance', kind: 'open', payload: {} }) } })), h('p', { class: 'muted', text: 'Stored on this computer with your other SciCal preferences.' }));
    };
    paintChips();
    void load();
    return {
        el,
        focus: () => search.focus(),
        open: (req) => {
            const p = req.payload;
            if (typeof p.query === 'string') {
                search.value = p.query;
                query = p.query;
            }
            if (typeof p.category === 'string')
                category = p.category;
            void load();
        },
    };
}
//# sourceMappingURL=constants.js.map