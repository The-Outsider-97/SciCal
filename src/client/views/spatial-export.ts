// "Save as SGEO / SDRW": the buttons shared by the 2D and 3D graph views, and the dialog that says what was saved, what was verified and what was left out.
// SciCal does not write these formats: the service builds the document with SLAI's SGEO / SDRW classes, saves it with their atomic writer, opens it again and
// validates it. This module only asks for that and reports the answer without embellishing it.
import { api, ApiError, type SpatialExport, type SpatialExportRequest } from '../api.js';
import { h } from '../dom.js';
import { dialog, saveBlob, toast } from '../ui.js';

export const UNITS = ['mm', 'cm', 'm', 'km', 'in', 'ft'] as const;
export type Unit = (typeof UNITS)[number];

/** What a view supplies when a button is pressed; null means there is nothing to save yet. */
export type Prepared = Pick<SpatialExportRequest, 'spec' | 'settings' | 'context'> & Partial<Pick<SpatialExportRequest, 'colors' | 'view'>> & { name?: string };

export interface ExportItem {
  label: string;
  title: string;
  format: SpatialExportRequest['format'];
  source: SpatialExportRequest['source'];
  /** Return false to grey the button out (e.g. contour maps need an explicit surface). */
  enabled?: () => boolean;
}

export interface ExportConfig {
  items: ExportItem[];
  defaultUnit: Unit;
  unitHint: string;
  prepare(item: ExportItem): Prepared | null;
}

const bytes = (n: number): string => (n < 1024 ? `${n} bytes` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

function decode(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const kindWord = (r: SpatialExport): string => (r.format === 'sgeo' ? '3D model (SGEO)' : r.mode ? `derived ${r.mode} drawing (SDRW)` : '2D drawing (SDRW)');

function layerLine(l: SpatialExport['layers'][number]): string {
  const bits: string[] = [];
  if (l.vertices !== undefined) bits.push(`${l.vertices.toLocaleString('en')} vertices`);
  if (l.triangles !== undefined) bits.push(`${l.triangles.toLocaleString('en')} triangles`);
  if (l.pieces !== undefined) bits.push(`${l.pieces} piece${l.pieces === 1 ? '' : 's'}`);
  if (l.controlPoints !== undefined) bits.push(`${l.controlPoints.toLocaleString('en')} points on the curve`);
  if (l.points !== undefined) bits.push(`${l.points.toLocaleString('en')} points`);
  if (l.entities !== undefined) bits.push(`${l.entities.toLocaleString('en')} drawing objects`);
  return bits.length ? `${l.label} — ${bits.join(', ')}` : l.label;
}

function list(title: string, items: string[], cls = ''): HTMLElement | '' {
  if (!items.length) return '';
  return h('section', { class: `export-block ${cls}` }, h('h3', { text: title }), h('ul', null, items.map((t) => h('li', { text: t }))));
}

/** The dialog: facts only. Every sentence here is something the service did and reported. */
export function showExportResult(r: SpatialExport, downloaded: boolean): void {
  const v = r.validation;
  const derived = r.format === 'sdrw' && !!r.mode;
  const body = h('div', { class: 'export-summary' },
    derived ? h('p', { class: 'export-banner', role: 'note', text: 'This is a drawing derived from the 3D scene, not the model itself. Depth and surface shading are lost; use the SGEO file when you need the 3D geometry.' }) : '',
    h('dl', null,
      h('dt', { text: 'File' }), h('dd', { class: 'mono', text: `${r.filename} · ${bytes(r.size)}` }),
      h('dt', { text: 'Contents' }), h('dd', { text: kindWord(r) }),
      h('dt', { text: 'Checked' }),
      h('dd', { text: v.ok ? `SLAI's ${v.mode} validator found no errors (${v.warnings} warning${v.warnings === 1 ? '' : 's'}) and the file was opened again after saving.` : 'The validator reported errors.' }),
      h('dt', { text: 'Saved' }),
      h('dd', { text: downloaded ? 'The browser was asked to download it, and a copy is in the SciCal output folder.' : 'In the SciCal output folder (the file was too large to send back to the browser).' }),
      h('dt', { text: 'Fingerprint' }), h('dd', { class: 'mono', text: `SHA-256 ${r.sha256.slice(0, 16)}…` })),
    list('What is in the file', r.layers.map(layerLine)),
    list('Left out', r.skipped.map((s) => `${s.label ?? s.id ?? 'A layer'}: ${s.reason}`), 'left-out'),
    list('Things to know', r.notes));
  dialog(r.format === 'sgeo' ? 'Saved as SGEO' : 'Saved as SDRW', body, { wide: true });
}

export async function runExport(item: ExportItem, unit: Unit, prepared: Prepared): Promise<void> {
  const { name, ...rest } = prepared;
  const req: SpatialExportRequest = { format: item.format, source: item.source, name: name ?? 'scical-graph', unit, ...rest };
  let result: SpatialExport;
  try {
    result = await api.exportGraph(req);
  } catch (e) {
    toast(e instanceof ApiError ? e.message : 'The file could not be saved.', 'error');
    return;
  }
  let downloaded = false;
  if (result.contentBase64) {
    try {
      saveBlob(new Blob([decode(result.contentBase64) as BlobPart], { type: result.mime || 'application/octet-stream' }), result.filename);
      downloaded = true;
    } catch { /* the copy in the output folder is still there; the dialog says so */ }
  }
  showExportResult(result, downloaded);
}

/** A row with a unit selector and one button per item. Call refresh() when the scene changes so that conditional buttons follow it. */
export function exportControls(cfg: ExportConfig): { el: HTMLElement; refresh(): void } {
  const unitSel = h('select', { 'aria-label': 'Unit written into the file', title: cfg.unitHint, style: { width: 'auto' } }, UNITS.map((u) => h('option', { value: u, text: u, selected: u === cfg.defaultUnit })));
  unitSel.value = cfg.defaultUnit;
  const buttons = cfg.items.map((item) => {
    const b = h('button', { class: 'btn small', type: 'button', text: item.label, title: item.title });
    b.addEventListener('click', async () => {
      const prepared = cfg.prepare(item);
      if (!prepared) { toast('Draw something first.', 'info'); return; }
      b.disabled = true;
      b.setAttribute('aria-busy', 'true');
      try { await runExport(item, unitSel.value as Unit, prepared); } finally { b.disabled = item.enabled ? !item.enabled() : false; b.removeAttribute('aria-busy'); }
    });
    return { item, b };
  });
  const refresh = (): void => { for (const { item, b } of buttons) b.disabled = item.enabled ? !item.enabled() : false; };
  const el = h('div', { class: 'row export-row', role: 'group', 'aria-label': 'Save as an SLAI file' },
    h('span', { class: 'muted', text: 'Save as' }), buttons.map(({ b }) => b),
    h('label', { class: 'inline-unit' }, h('span', { class: 'muted', text: 'unit' }), unitSel));
  refresh();
  return { el, refresh };
}
