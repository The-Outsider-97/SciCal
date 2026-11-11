// The STEM Lab workspace: operations only SLAI's STEM agent provides (differential equations, Monte-Carlo, numerical methods and their
// errors, conditioning, interpolation, bootstrap). The forms and results are the same machinery as the other subject workspaces.
import { h, replace } from '../dom.js';
import type { WorkspaceView, NavRequest } from '../shell.js';
import { stemStatus, stemStatusLine } from '../stem.js';
import { glyph } from '../ui.js';
import { createDomainView } from './domain.js';

export function createStemView(): WorkspaceView {
  const inner = createDomainView('stem');
  const banner = h('div', { class: 'stem-banner card', role: 'status' }, h('span', { class: 'muted', text: 'Looking for the SLAI STEM agent…' }));

  const draw = async (refresh: boolean): Promise<void> => {
    const st = await stemStatus(refresh);
    const retry = h('button', { class: 'btn small', type: 'button', text: 'Test again', on: { click: () => { replace(banner, h('span', { class: 'muted', text: 'Testing…' })); void draw(true); } } });
    replace(banner,
      glyph('stem', st.available ? 'ok' : 'warn'),
      h('div', { class: 'grow' },
        h('strong', { text: st.available ? 'STEM agent connected' : 'STEM agent not available' }),
        h('div', { class: 'muted', text: stemStatusLine(st) }),
        st.available ? h('div', { class: 'muted', text: 'Everything on this page is computed by the agent; SciCal reads your expressions and shows the results. Seeded runs repeat exactly.' })
          : h('div', { class: 'muted', text: 'SciCal itself works without it. The STEM Lab operations and the STEM checks need the agent (and NumPy and SciPy in the Python that runs SciCal).' })),
      retry);
  };
  void draw(false);

  return {
    el: h('div', { class: 'stem-view' }, banner, inner.el),
    focus: () => inner.focus(),
    open: (req: NavRequest) => inner.open?.(req),
  };
}

