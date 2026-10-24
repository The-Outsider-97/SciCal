// Worksheets: open, create, rename, delete, import; export and hand-off to other SLAI applications; search across worksheets.
import type { Json, SessionMeta } from '../../core/types.js';
import { fileSafe, timeLabel } from '../../core/util.js';
import { ApiError, api } from '../api.js';
import { h, replace } from '../dom.js';
import { store } from '../store.js';
import { confirmDialog, dialog, glyph, iconButton, promptDialog, readFileText, saveBlob, toast } from '../ui.js';

const FORMATS: Array<[string, string, string]> = [
  ['md', 'Markdown', 'Readable text with the results in LaTeX'],
  ['txt', 'Plain text', 'Inputs and results as lines of text'],
  ['csv', 'CSV', 'One row per entry, for a spreadsheet'],
  ['json', 'SciCal file', 'The whole worksheet, to re-open or share'],
  ['sldc', 'SLDC document', 'For Reader and Documaster'],
];

const fail = (e: unknown, fallback: string): void => toast(e instanceof ApiError ? e.message + (e.hint ? ' ' + e.hint : '') : fallback, 'error');

export async function openWorksheets(): Promise<void> {
  await store.refreshSessions().catch(() => undefined);
  const list = h('div', { class: 'sheet-list' });
  const exportBox = h('div', { class: 'chips' });
  const handoffNote = h('div');
  const file = h('input', { type: 'file', accept: '.json,application/json', class: 'visually-hidden', 'aria-label': 'Choose a SciCal file to import' });

  const drawList = (): void => {
    const sessions = store.sessions;
    replace(list, sessions.length ? sessions.map((s: SessionMeta) => {
      const current = s.id === store.session?.id;
      return h('div', { class: 'sheet-item' + (current ? ' current' : '') },
        h('span', { class: 'kindmark' }, glyph('sheet')),
        h('div', null, h('div', { class: 't', text: s.name + (current ? ' (open)' : '') }), h('div', { class: 's', text: `${s.entries} entries · ${timeLabel(s.updated)}` })),
        h('div', { class: 'row' },
          current ? null : h('button', { class: 'btn small', type: 'button', text: 'Open', on: { click: () => void store.openSession(s.id).then(() => { d.close(); toast(`Opened “${s.name}”`, 'ok', 2200); }).catch((e) => fail(e, 'Could not open the worksheet.')) } }),
          iconButton('sheet', 'Rename', async () => {
            const name = await promptDialog('Rename the worksheet', 'Name', s.name, 'Rename');
            if (!name) return;
            try {
              if (current) await store.renameSession(name);
              else { await api.saveSession(s.id, { name }); await store.refreshSessions(); }
              drawList();
            } catch (e) { fail(e, 'Could not rename the worksheet.'); }
          }),
          iconButton('trash', 'Delete', async () => {
            if (!(await confirmDialog('Delete this worksheet?', `“${s.name}” and everything in it will be deleted from this computer.`))) return;
            try { await store.deleteSession(s.id); drawList(); } catch (e) { fail(e, 'Could not delete the worksheet.'); }
          }, 'danger')));
    }) : h('p', { class: 'empty', text: 'No worksheets yet.' }));
  };

  const doExport = async (fmt: string, label: string): Promise<void> => {
    const s = store.session;
    if (!s) return;
    try {
      await store.flush();
      const { blob, filename } = await api.exportSession(s.id, fmt);
      saveBlob(blob, filename || `${fileSafe(s.name)}.${fmt}`);
      toast(`${label} saved to your downloads`, 'ok');
    } catch (e) { fail(e, `The ${label} export failed.`); }
  };
  replace(exportBox, FORMATS.map(([fmt, label, tip]) => h('button', { class: 'btn small', type: 'button', title: tip, text: label, on: { click: () => void doExport(fmt, label) } })));

  const doHandoff = async (target: string): Promise<void> => {
    const s = store.session;
    if (!s) return;
    try {
      await store.flush();
      const r = await api.handoff(s.id, target);
      replace(handoffNote, h('div', { class: 'notes' },
        h('div', { class: 'note-line', text: `Wrote ${r.document}` }), h('div', { class: 'note-line', text: r.note })));
    } catch (e) { replace(handoffNote, h('div', { class: 'note-line error', text: e instanceof ApiError ? e.message + (e.hint ? ' ' + e.hint : '') : 'The hand-off failed.' })); }
  };

  file.addEventListener('change', async () => {
    const f = file.files?.[0];
    file.value = '';
    if (!f) return;
    try {
      const doc = JSON.parse(await readFileText(f)) as Json;
      const s = await api.importSession(doc);
      await store.refreshSessions();
      await store.openSession(s.id);
      toast(`Imported “${s.name}”`, 'ok');
      drawList();
    } catch (e) { fail(e, 'That file could not be imported.'); }
  });

  const apps = store.status.slai.apps;
  const d = dialog('Worksheets', [
    h('section', null, h('div', { class: 'card-head' }, h('h3', { text: 'Your worksheets' }),
      h('div', { class: 'row' },
        h('button', { class: 'btn small primary', type: 'button', text: 'New worksheet', on: { click: async () => {
          const name = await promptDialog('New worksheet', 'Name', `Worksheet ${store.sessions.length + 1}`, 'Create');
          if (!name) return;
          try { await store.newSession(name); drawList(); toast('New worksheet created', 'ok', 2000); } catch (e) { fail(e, 'Could not create the worksheet.'); }
        } } }),
        h('button', { class: 'btn small', type: 'button', text: 'Import…', on: { click: () => file.click() } }), file)), list),
    h('section', null, h('div', { class: 'card-head' }, h('h3', { text: `Export “${store.session?.name ?? ''}”` })), exportBox),
    h('section', null, h('div', { class: 'card-head' }, h('h3', { text: 'Send to another SLAI application' })),
      h('div', { class: 'chips' },
        h('button', { class: 'btn small', type: 'button', text: 'Open in Reader', title: apps.reader?.running ? 'Reader is running' : 'Reader is not running', on: { click: () => void doHandoff('reader') } }),
        h('button', { class: 'btn small', type: 'button', text: 'Send to Documaster', title: apps.documaster?.running ? 'Documaster is running' : 'Documaster is not running', on: { click: () => void doHandoff('documaster') } })),
      handoffNote),
  ], { wide: true });
  drawList();
}

export function openSearch(): void {
  const q = h('input', { type: 'search', placeholder: 'Search inputs, notes and operations in every worksheet', 'aria-label': 'Search worksheets' });
  const out = h('div', { class: 'sheet-list' });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const go = async (): Promise<void> => {
    const text = q.value.trim();
    if (!text) { replace(out); return; }
    try {
      const r = await api.search(text);
      replace(out, r.hits.length ? r.hits.map((hit) => h('button', { class: 'sheet-item', type: 'button', style: { 'text-align': 'left', cursor: 'pointer', background: 'var(--bg)' }, on: { click: async () => {
        d.close();
        try { if (store.session?.id !== hit.session) await store.openSession(String(hit.session)); } catch (e) { fail(e, 'Could not open that worksheet.'); }
      } } },
        h('span', { class: 'kindmark' }, glyph('search')),
        h('div', null, h('div', { class: 't', text: String(hit.input ?? '').slice(0, 120) }), h('div', { class: 's', text: `${String(hit.name)} · ${String(hit.kind)}` })), h('span'))) : h('p', { class: 'empty', text: 'Nothing found.' }));
    } catch (e) { fail(e, 'The search failed.'); }
  };
  q.addEventListener('input', () => { if (timer) clearTimeout(timer); timer = setTimeout(() => void go(), 250); });
  const d = dialog('Search', [q, out], { wide: true });
  q.focus();
}
