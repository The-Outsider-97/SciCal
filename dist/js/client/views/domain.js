// The subject workspaces (Chemistry, Biology, Measurement, Formulas). Every operation comes from the server's catalogue, so the
// forms, the example buttons and the backend cannot drift apart; this file only knows how to lay them out and run them.
import { collect, describeInput, emptyState, seed } from '../../core/forms.js';
import { headlineOf } from '../../core/results.js';
import { canCheck } from '../../core/stem.js';
import { nowIso, newEntryId } from '../../core/session.js';
import { debounce, isRecord } from '../../core/util.js';
import { api, ApiError } from '../api.js';
import { dnaScene, rnaScene, rnaProcessingScene, transcriptionScene, translationScene, mutationScene, moleculeScene, molecularReactionScene, reactionScene, scientificScene } from '../science3d.js';
import { h, replace } from '../dom.js';
import { buildForm } from '../domain-form.js';
import { renderResult } from '../domain-results.js';
import { constantsTable, elementDialog, formulaLibrary, geneticCode, periodicTable, punnettSquare, unitCatalogue } from '../domain-views.js';
import { store } from '../store.js';
import { copyText, emptyNote, saveBlob, setBusy, toast } from '../ui.js';
import { askExplain } from './assistant.js';
import { runCheck, stemAuto, stemBadge, stemButton, stemEnabled, stemStatus, verificationPanel } from '../stem.js';
import { savedList } from './saved.js';
/** Operations that show a browsable reference and so run by themselves, as soon as they are opened or their search changes. */
const LIVE = new Set(['periodic_table', 'genetic_code', 'units', 'constants', 'formula_library']);
/** Their results are large reference data, not a calculation worth keeping in a worksheet. */
const NO_SAVE = new Set(['periodic_table', 'genetic_code', 'units']);
/** Accept only finite bounded scientific structures from the trusted result payload. */
function readStructure(raw) {
    if (!isRecord(raw) || !Array.isArray(raw.atoms) || !Array.isArray(raw.bonds) || !raw.atoms.length || raw.atoms.length > 180)
        return null;
    const atoms = raw.atoms.filter(isRecord).map((atom) => ({
        element: String(atom.element ?? ''),
        xyz: Array.isArray(atom.xyz) && atom.xyz.length === 3 ? atom.xyz.map(Number) : [],
    }));
    const bonds = raw.bonds.filter(isRecord).map((b) => ({ a: Number(b.a), b: Number(b.b), order: Number(b.order) }));
    if (atoms.length !== raw.atoms.length || !atoms.every((a) => /^[A-Z][a-z]?$/.test(a.element) && a.xyz.length === 3 && a.xyz.every(Number.isFinite)) ||
        bonds.length !== raw.bonds.length || !bonds.every((b) => Number.isInteger(b.a) && Number.isInteger(b.b) && b.a >= 0 && b.b >= 0 &&
        b.a < atoms.length && b.b < atoms.length && b.a !== b.b && Number.isInteger(b.order) && b.order >= 1 && b.order <= 3))
        return null;
    return {
        formula: String(raw.formula ?? ''), name: String(raw.name ?? raw.formula ?? ''),
        charge: Number(raw.charge ?? 0), source: String(raw.source ?? ''),
        atoms: atoms.map((a) => ({ element: a.element, xyz: a.xyz })),
        bonds,
    };
}
/** Draw ONLY source-validated scientific data. Views never change the scientific calculation. */
function scientificView(domain, operation, result) {
    if (result.ok === false)
        return null;
    let spec;
    if (domain === 'biology') {
        if (operation === 'sequence' && typeof result.sceneSequence === 'string')
            spec = result.kind === 'RNA' ? rnaScene(result.sceneSequence) : dnaScene(result.sceneSequence);
        else if (operation === 'translate' && typeof result.sceneRna === 'string')
            spec = rnaScene(result.sceneRna);
        else if (operation === 'transcription' && typeof result.coding === 'string' && typeof result.mrna === 'string')
            spec = transcriptionScene(result.coding, result.mrna);
        else if (operation === 'rna_processing' && typeof result.preMrna === 'string' && typeof result.matureMrna === 'string')
            spec = rnaProcessingScene(result.preMrna, result.matureMrna);
        else if (operation === 'mutation' && typeof result.original === 'string' && typeof result.mutated === 'string')
            spec = mutationScene(result.original, result.mutated, result.kind === 'RNA' ? 'RNA' : 'DNA');
        else if (operation === 'protein_synthesis' && typeof result.mrna === 'string' && Array.isArray(result.codons)) {
            const cs = result.codons.filter(isRecord).map((c) => ({
                codon: String(c.codon ?? ''), aa: String(c.aa ?? 'X'), anticodon: typeof c.anticodon === 'string' ? c.anticodon : undefined,
            }));
            spec = translationScene(result.mrna, cs, Math.max(0, Number(result.start || 1) - 1));
        }
    }
    if (domain === 'chemistry' && operation === 'molar_mass') {
        const structure = readStructure(result.molecularStructure3d);
        if (structure)
            spec = moleculeScene(structure);
    }
    if (domain === 'chemistry' && operation === 'balance' && isRecord(result.atomInventory3d) && result.atomInventory3d.verified === true) {
        const inventory = result.atomInventory3d;
        const clean = (raw) => (Array.isArray(raw) ? raw.filter(isRecord) : []).map((s) => ({
            species: String(s.species ?? ''), coefficient: Math.max(0, Number(s.coefficient ?? 0)),
            atoms: Object.fromEntries(Object.entries(isRecord(s.atoms) ? s.atoms : {}).filter(([_, n]) => Number.isInteger(Number(n)) && Number(n) >= 0).map(([k, n]) => [k, Number(n)])),
            structure: readStructure(s.structure),
        }));
        const reactants = clean(inventory.reactants);
        const products = clean(inventory.products);
        const sides = [...reactants, ...products];
        const total = (rows) => rows.reduce((sum, sp) => sum + sp.coefficient * Object.values(sp.atoms).reduce((n, amount) => n + amount, 0), 0);
        // The primitive scene has a finite capacity: never show a truncated scene as an exact inventory.
        if (sides.every((sp) => Number.isInteger(sp.coefficient) && sp.coefficient >= 0 && sp.coefficient <= 12 &&
            Object.values(sp.atoms).every((n) => n <= 24)) &&
            total(reactants) <= 240 && total(products) <= 240) {
            const countMolecules = sides.reduce((sum, sp) => sum + sp.coefficient, 0);
            spec = countMolecules <= 6 && sides.every((sp) => sp.structure !== null) ?
                molecularReactionScene(reactants, products) : reactionScene(reactants, products);
        }
    }
    if (!spec)
        return null;
    return scientificScene(spec);
}
/** Fill empty Finance fields from the person's own financial parameters (Constants > Financial parameters). Returns the labels that were filled. */
function financeDefaults(domainId, op, state) {
    if (domainId !== 'finance')
        return [];
    const p = store.prefs;
    const wanted = [
        ['currency', p.finCurrency || undefined, 'currency'],
        ['places', p.finPlaces === undefined || p.finPlaces === null ? undefined : String(p.finPlaces), 'decimals'],
        ['inflation', p.finInflation === undefined || p.finInflation === null ? undefined : String(p.finInflation), 'inflation'],
    ];
    if (['npv', 'dcf', 'payback'].includes(op.id))
        wanted.push(['rate', p.finDiscountRate === undefined || p.finDiscountRate === null ? undefined : String(p.finDiscountRate), 'discount rate']);
    const done = [];
    for (const [key, value, label] of wanted) {
        const f = op.fields.find((x) => x.key === key);
        if (!f || value === undefined || (state[key] !== '' && state[key] !== undefined))
            continue;
        if (f.kind === 'select' && !(f.options ?? []).some((o) => o.value === value))
            continue;
        state[key] = value;
        done.push(label);
    }
    return done;
}
export function createDomainView(domainId) {
    const dom = store.forms[domainId];
    const ops = dom?.ops ?? [];
    let op = ops[0];
    let state = op ? emptyState(op) : {};
    let form = null;
    let job = null;
    let last = null;
    let periodicCache = null;
    let periodic = null;
    let activeScientificScene = null;
    const opList = h('nav', { class: 'oplist', 'aria-label': `${dom?.title ?? domainId} operations` });
    const title = h('h2');
    const summary = h('p', { class: 'muted' });
    const formBox = h('div');
    const buttons = h('div', { class: 'formfoot' });
    const out = h('div', { class: 'out', 'aria-live': 'polite' });
    const missingNote = h('div', { class: 'note-line', role: 'alert', hidden: true });
    const el = h('div', { class: 'domain' }, opList, h('div', { class: 'domain-main' }, h('section', { class: 'card' }, h('div', { class: 'card-head' }, title), summary, formBox, missingNote, buttons), h('section', { class: 'card', 'aria-label': 'Result' }, out), savedList('Saved in this worksheet', (e) => e.kind === 'domain' && e.domain === domainId, (e) => { if (e.op)
        choose(e.op, e.params, true); })));
    // ---------------------------------------------------------------------------------------------------------- exports and entries
    const ctxFor = (o, params) => ({
        op: o, params,
        exportTable: (name, columns, rows) => {
            api.exportTable(name, columns, rows).then((d) => saveBlob(d.blob, d.filename)).catch((e) => toast(e instanceof ApiError ? e.message : 'The table could not be exported.', 'error'));
        },
    });
    const entryFor = (l) => ({
        kind: 'domain', workspace: domainId, domain: domainId, op: l.op.id, params: l.params, settings: store.settings,
        title: describeInput(l.op, l.params), result: l.res, summary: { ok: l.res.ok !== false, headline: headlineOf(l.res) }, ok: l.res.ok !== false,
        ...(l.verification ? { verification: l.verification } : {}),
    });
    // ---------------------------------------------------------------------------------------------------------- running
    const showResult = async (res, params, o) => {
        activeScientificScene?.destroy();
        activeScientificScene = null;
        last = { res, params, op: o };
        const ctx = ctxFor(o, params);
        const nodes = [];
        const stemSlot = h('span', { class: 'stem-slot' });
        const stemBox = h('div', { class: 'stem-box' });
        const ok = res.ok !== false;
        if (ok && o.view === 'periodic') {
            await showPeriodic();
            return;
        }
        if (ok) {
            const head = h('div', { class: 'headline' }, h('h3', { text: headlineOf(res) === 'Done' ? o.title : headlineOf(res) }), h('div', { class: 'row' }, NO_SAVE.has(o.id) ? null : h('button', { class: 'btn small', type: 'button', text: 'Add to worksheet', on: { click: () => { if (last) {
                        store.addEntry(entryFor(last));
                        toast('Added to the worksheet', 'ok', 2200);
                    } } } }), NO_SAVE.has(o.id) ? null : h('button', { class: 'btn small', type: 'button', text: 'Explain', on: { click: () => { if (last)
                        void askExplain({ id: newEntryId(), time: nowIso(), ...entryFor(last) }); } } }), stemSlot));
            nodes.push(head, stemBox);
        }
        const skip = new Set();
        if (ok && o.view === 'punnett') {
            nodes.push(renderResult(res, ctx, new Set(['gametes1', 'gametes2', 'grid'])));
            nodes.splice(2, 0, punnettSquare(res));
        }
        else if (ok && o.view === 'code') {
            nodes.push(geneticCode(res));
            nodes.push(renderResult({ ok: true, enzymes: Object.entries(isRecord(res.enzymes) ? res.enzymes : {}).map(([name, v]) => ({ enzyme: name, ...(isRecord(v) ? v : {}) })) }, ctx, skip));
        }
        else if (ok && o.view === 'catalogue')
            nodes.push(unitCatalogue(res, (sym) => void copyText(sym, `Copied ${sym}`)));
        else if (ok && o.view === 'constants')
            nodes.push(constantsTable(res, (t) => void copyText(t, 'Value copied')));
        else if (ok && o.view === 'library')
            nodes.push(formulaLibrary(res, useFormula));
        else
            nodes.push(renderResult(res, ctx));
        const visual = scientificView(domainId, o.id, res);
        if (visual) {
            activeScientificScene = visual;
            nodes.splice(2, 0, h('div', { class: 'section' }, h('div', { class: 'sectitle', text: 'Interactive scientific visualization' }), visual.el));
        }
        replace(out, ...nodes);
        if (ok && domainId !== 'stem')
            void attachStem(o, res, params, stemSlot, stemBox);
    };
    /** The STEM check for a workspace result: a button (or, in automatic mode, the check itself) when the agent has a second route for this operation. */
    const attachStem = async (o, res, params, slot, box) => {
        if (!stemEnabled())
            return;
        const st = await stemStatus();
        if (!canCheck({ kind: 'domain', domain: domainId, op: o.id, result: res }, st.checkable?.domain) || last?.res !== res)
            return;
        const show = (v) => {
            replace(box, v.ran ? verificationPanel(v) : null);
            const badge = stemBadge(v, () => { if (box.firstChild)
                replace(box);
            else
                replace(box, verificationPanel(v)); });
            replace(slot, badge, button);
        };
        const check = async () => {
            replace(slot, h('span', { class: 'badge plain', text: 'STEM checking…' }));
            const v = await runCheck({ kind: 'domain', workspace: domainId, domain: domainId, op: o.id, params, result: res }, store.settings, []);
            if (last?.res !== res)
                return;
            if (!v.ran) {
                toast(v.summary, 'info', 9000);
                replace(slot, button);
                return;
            }
            last.verification = v;
            show(v);
        };
        const button = stemButton('STEM check', () => void check());
        replace(slot, button);
        if (st.available && stemAuto())
            void check();
    };
    const showPeriodic = async () => {
        if (!periodicCache) {
            const r = await api.domain('chemistry', 'periodic_table', {}, store.settings, api.newJob());
            if (r.ok === false) {
                replace(out, renderResult(r, ctxFor(op, {})));
                return;
            }
            periodicCache = (Array.isArray(r.elements) ? r.elements : []).filter(isRecord);
        }
        periodic = periodicTable(periodicCache, (e) => {
            api.domain('chemistry', 'element', { element: String(e.symbol) }, store.settings, api.newJob()).then((r) => { if (r.ok === false)
                toast(String(isRecord(r.error) ? r.error.message : 'Could not load the element'), 'error');
            else
                elementDialog(r); }).catch(() => toast('Could not load the element.', 'error'));
        });
        periodic.filter(String(state.query ?? ''));
        replace(out, h('div', { class: 'headline' }, h('h3', { text: 'Periodic table' }), h('span', { class: 'muted', text: 'Click an element for its properties and isotopes. The search above dims the elements that do not match.' })), periodic.el, h('p', { class: 'muted source', text: 'Atomic weights are conventional values; elements with no stable isotope show their most stable known isotope as stored in the data file.' }));
    };
    const run = async (quiet = false) => {
        if (!op)
            return;
        const { params, missing } = collect(op, state);
        if (missing.length) {
            if (!quiet) {
                missingNote.hidden = false;
                missingNote.textContent = `Please fill in: ${missing.join(', ')}.`;
            }
            return;
        }
        missingNote.hidden = true;
        if (job)
            void api.cancel(job);
        const mine = api.newJob();
        job = mine;
        setBusy(out, true);
        try {
            const res = await api.domain(domainId, op.id, params, store.settings, mine);
            if (job !== mine)
                return;
            await showResult(res, params, op);
        }
        catch (e) {
            if (job !== mine)
                return;
            replace(out, h('div', { class: 'note-line error', role: 'alert', text: e instanceof ApiError ? e.message : 'The calculation could not be completed.' }));
        }
        finally {
            if (job === mine) {
                setBusy(out, false);
                job = null;
            }
        }
    };
    const runSoon = debounce(() => void run(true), 280);
    // ---------------------------------------------------------------------------------------------------------- choosing an operation
    const choose = (id, params, go = false) => {
        const next = ops.find((o) => o.id === id);
        if (!next)
            return;
        activeScientificScene?.destroy();
        activeScientificScene = null;
        op = next;
        state = params ? seed(op, params) : emptyState(op);
        const prefilled = params ? [] : financeDefaults(domainId, op, state);
        last = null;
        missingNote.hidden = true;
        paintOps();
        replace(title, op.title);
        replace(summary, op.summary, prefilled.length ? h('span', { class: 'muted', text: ` Pre-filled from your financial parameters: ${prefilled.join(', ')}.` }) : null);
        form = buildForm(op, state, () => { if (LIVE.has(op.id))
            runSoon(); }, () => void run());
        replace(formBox, op.fields.length ? form.el : null);
        const buttonsRow = op.fields.length || !LIVE.has(op.id) ? [h('button', { class: 'btn primary', type: 'button', text: LIVE.has(op.id) ? 'Search' : 'Calculate', on: { click: () => void run() } })] : [];
        if (Object.keys(op.example ?? {}).length && !LIVE.has(op.id))
            buttonsRow.push(h('button', { class: 'btn', type: 'button', text: 'Load example', on: { click: () => loadExample() } }));
        if (op.fields.length && !LIVE.has(op.id))
            buttonsRow.push(h('button', { class: 'btn', type: 'button', text: 'Clear', on: { click: () => { choose(op.id); replace(out, emptyNote(`Fill in the form and press Calculate, or load the example to see how ${op.title.toLowerCase()} works.`)); } } }));
        replace(buttons, ...buttonsRow);
        if (go || LIVE.has(op.id))
            void run(true);
        else
            replace(out, emptyNote(`Fill in the form and press Calculate, or load the example to see how ${op.title.toLowerCase()} works.`));
    };
    const loadExample = () => {
        const fresh = seed(op, op.example);
        for (const k of Object.keys(state))
            delete state[k];
        Object.assign(state, fresh);
        form?.refresh();
        void run();
    };
    const useFormula = (f) => {
        const target = ops.find((o) => o.id === 'formula_solve');
        if (!target)
            return;
        choose('formula_solve', { formulaId: f.id }, false);
        form?.focusFirst();
    };
    const paintOps = () => {
        replace(opList, ops.map((o) => h('button', { class: 'opbtn', type: 'button', 'aria-current': String(o.id === op?.id), on: { click: () => choose(o.id) } }, h('strong', { text: o.title }), h('small', { text: o.summary }))));
    };
    if (op)
        choose(op.id);
    else
        replace(out, emptyNote('This workspace has no operations. The service did not send a catalogue.'));
    return {
        el,
        focus: () => { form?.focusFirst(); },
        open: (req) => {
            const p = req.payload;
            const id = typeof p.op === 'string' ? p.op : '';
            if (!id || !ops.some((o) => o.id === id))
                return;
            choose(id, isRecord(p.params) ? p.params : undefined, p.go !== false);
        },
    };
}
//# sourceMappingURL=domain.js.map