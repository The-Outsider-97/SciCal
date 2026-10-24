// "Saved in this worksheet": what was added from a workspace, with a way to open it again or take it out.
import type { Entry } from '../../core/types.js';
import { h, replace } from '../dom.js';
import { store } from '../store.js';
import { iconButton } from '../ui.js';

export function savedList(heading: string, pick: (e: Entry) => boolean, open: (e: Entry) => void): HTMLElement {
  const list = h('ul', { class: 'saved-list' });
  const box = h('details', { class: 'card saved', 'aria-label': heading }, h('summary', { text: heading }), list);
  const paint = (): void => {
    const items = store.entries.filter(pick).reverse();
    box.hidden = items.length === 0;
    const summary = box.querySelector('summary');
    if (summary) summary.textContent = `${heading} (${items.length})`;
    replace(list, items.map((e) => h('li', null,
      h('button', { class: 'saved-open', type: 'button', title: 'Open this again', on: { click: () => open(e) } },
        h('strong', { text: e.title || e.input || 'Entry' }),
        h('span', { class: 'muted', text: String((e.summary as { headline?: unknown } | undefined)?.headline ?? '') })),
      iconButton('trash', 'Remove from the worksheet', () => store.removeEntry(e.id), 'tiny'))));
  };
  store.on('entries', paint);
  store.on('session', paint);
  paint();
  return box;
}
