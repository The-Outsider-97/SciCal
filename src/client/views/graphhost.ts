// The Graphing workspace is two views of the same idea: the flat graph (2D) and the 3D graph. This host shows one at a time and sends a worksheet
// entry to the right one, so the tab, the saved-entry list and "open this again" keep working for both.
import { isRecord } from '../../core/util.js';
import { h, replace } from '../dom.js';
import type { NavRequest, WorkspaceView } from '../shell.js';

type Mode = '2d' | '3d';

export function createGraphHost(): WorkspaceView {
  const views: Partial<Record<Mode, WorkspaceView>> = {};
  const pending: Partial<Record<Mode, Promise<WorkspaceView>>> = {};
  let mode: Mode = '2d';
  const body = h('div', { class: 'graph-body' });
  const buttons = {
    '2d': h('button', { type: 'button', class: 'seg', role: 'tab', text: '2D' }),
    '3d': h('button', { type: 'button', class: 'seg', role: 'tab', text: '3D' }),
  };
  const bar = h('div', { class: 'seg-bar', role: 'tablist', 'aria-label': 'Kind of graph' }, buttons['2d'], buttons['3d']);

  const load = (m: Mode): Promise<WorkspaceView> => {
    const have = views[m];
    if (have) return Promise.resolve(have);
    pending[m] ??= (async () => {
      const v = m === '2d' ? (await import('./graph.js')).createGraphView() : (await import('./graph3d.js')).createGraph3DView();
      views[m] = v;
      return v;
    })();
    return pending[m] as Promise<WorkspaceView>;
  };

  const use = async (m: Mode): Promise<WorkspaceView> => {
    mode = m;
    for (const k of ['2d', '3d'] as const) { buttons[k].setAttribute('aria-selected', String(k === m)); buttons[k].classList.toggle('on', k === m); }
    const v = await load(m);
    if (mode === m) { replace(body, v.el); }
    return v;
  };
  buttons['2d'].addEventListener('click', () => void use('2d').then((v) => v.focus()));
  buttons['3d'].addEventListener('click', () => void use('3d').then((v) => v.focus()));
  void use('2d');

  return {
    el: h('div', { class: 'graph-host' }, bar, body),
    focus: () => views[mode]?.focus(),
    open: (req: NavRequest) => {
      const spec = isRecord(req.payload.spec) ? req.payload.spec : null;
      const m: Mode = spec && spec.mode === '3d' ? '3d' : mode === '3d' && !spec ? '3d' : '2d';
      void use(m).then((v) => v.open?.(req));
    },
  };
}
