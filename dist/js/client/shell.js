import { h, replace } from './dom.js';
import { store } from './store.js';
import { glyph, icon, toast } from './ui.js';
import { openSettings } from './settings.js';
import { openAssistant } from './views/assistant.js';
import { openSearch, openWorksheets } from './views/sheets.js';
const TABS = [
    { id: 'math', title: 'Mathematics', icon: 'math' },
    { id: 'graph', title: 'Graphing', icon: 'graph' },
    { id: 'chemistry', title: 'Chemistry', icon: 'chemistry' },
    { id: 'biology', title: 'Biology', icon: 'biology' },
    { id: 'measurement', title: 'Measurement', icon: 'measurement' },
    { id: 'formulas', title: 'Formulas', icon: 'formulas' },
];
const factories = {};
const views = new Map();
let stage;
let tabEls = new Map();
export function registerView(id, factory) { factories[id] = factory; }
async function viewFor(id) {
    let v = views.get(id);
    if (!v) {
        const make = factories[id];
        if (!make)
            throw new Error(`No view for ${id}`);
        v = await make();
        views.set(id, v);
    }
    return v;
}
let showSeq = 0;
export async function show(id) {
    const mine = ++showSeq;
    store.setWorkspace(id);
    const v = await viewFor(id);
    if (mine !== showSeq)
        return v; // the person has already moved on to another tab while this one was loading
    replace(stage, v.el);
    for (const [tid, el] of tabEls)
        el.setAttribute('aria-selected', String(tid === id));
    stage.setAttribute('aria-labelledby', `tab-${id}`);
    document.title = `${TABS.find((t) => t.id === id)?.title ?? ''} · SciCal`;
    return v;
}
export async function navigate(req) {
    const ws = (req.workspace === 'formula' ? 'formulas' : req.workspace);
    if (!TABS.some((t) => t.id === ws)) {
        toast('That workspace does not exist.', 'error');
        return;
    }
    const v = await show(ws);
    v.open?.(req);
}
export function mount(root) {
    const saveDot = h('span', { class: 'save-dot', role: 'img', 'aria-label': 'Saved' });
    const chipName = h('span', { class: 'name' });
    const chip = h('button', { class: 'session-chip', type: 'button', title: 'Worksheets: open, create, export', on: { click: () => void openWorksheets() } }, saveDot, chipName);
    const status = h('div', { class: 'statusbar' });
    const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Workspaces' }, TABS.map((t) => {
        const el = h('button', { class: 'tab', type: 'button', role: 'tab', id: `tab-${t.id}`, 'aria-selected': 'false', 'aria-controls': 'stage', on: { click: () => void show(t.id) } }, icon(t.icon), h('span', { class: 'tt', text: t.title }));
        el.addEventListener('keydown', (ev) => {
            const i = TABS.findIndex((x) => x.id === t.id);
            const next = ev.key === 'ArrowRight' ? i + 1 : ev.key === 'ArrowLeft' ? i - 1 : -1;
            if (next >= 0) {
                ev.preventDefault();
                const target = TABS[(next + TABS.length) % TABS.length];
                void show(target.id).then(() => tabEls.get(target.id)?.focus());
            }
        });
        tabEls.set(t.id, el);
        return el;
    }));
    stage = h('main', { class: 'stage', id: 'stage', role: 'tabpanel', tabindex: '-1' });
    replace(root, h('header', { class: 'topbar' }, h('div', { class: 'brand' }, icon('logo'), h('div', null, 'SciCal', h('small', { text: 'SLAI scientific workbench' }))), tabs, h('div', { class: 'top-actions' }, chip, h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Search worksheets', title: 'Search', on: { click: () => openSearch() } }, glyph('search')), h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'SLAI assistant', title: 'SLAI assistant', on: { click: () => void openAssistant() } }, glyph('assistant')), h('button', { class: 'iconbtn', type: 'button', 'aria-label': 'Settings', title: 'Settings', on: { click: () => openSettings() } }, glyph('gear')))), stage, status);
    const paintSession = () => {
        chipName.textContent = store.session?.name ?? '…';
        const st = store.saveState;
        saveDot.className = 'save-dot ' + (st === 'saved' ? '' : st);
        saveDot.setAttribute('aria-label', st === 'saved' ? 'Saved' : st === 'saving' ? 'Saving' : 'Not saved: ' + store.saveError);
        chip.title = st === 'error' ? `Not saved: ${store.saveError}` : 'Worksheets: open, create, export';
        const n = store.entries.length;
        replace(status, h('span', { text: `SciCal ${store.status.version}` }), h('span', { class: 'sep', text: `${n} ${n === 1 ? 'entry' : 'entries'} in this worksheet` }), h('span', { class: 'sep', text: st === 'saved' ? 'Saved on this computer' : st === 'saving' ? 'Saving…' : 'Not saved: ' + store.saveError }), h('span', { class: 'sep', text: 'Results are computed on this computer; nothing is sent over the internet.' }));
    };
    store.on('session', paintSession);
    store.on('save', paintSession);
    store.on('entries', paintSession);
    paintSession();
    void show(store.workspace);
}
//# sourceMappingURL=shell.js.map