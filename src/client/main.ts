import { $ } from './dom.js';
import { mount, registerView } from './shell.js';
import { initTheme } from './settings.js';
import { store } from './store.js';
import { ApiError } from './api.js';
import { h, replace } from './dom.js';

registerView('math', async () => (await import('./views/math.js')).createMathView());
registerView('graph', async () => (await import('./views/graphhost.js')).createGraphHost());
registerView('chemistry', async () => (await import('./views/domain.js')).createDomainView('chemistry'));
registerView('biology', async () => (await import('./views/domain.js')).createDomainView('biology'));
registerView('measurement', async () => (await import('./views/domain.js')).createDomainView('measurement'));
registerView('finance', async () => (await import('./views/domain.js')).createDomainView('finance'));
registerView('constants', async () => (await import('./views/constants.js')).createConstantsView());
registerView('formulas', async () => (await import('./views/domain.js')).createDomainView('formulas'));

async function start(): Promise<void> {
  const root = $('#app');
  try {
    await store.init();
  } catch (e) {
    const msg = e instanceof ApiError && e.status === 401 ? 'SciCal is locked. Open it from the link printed when it started (it contains a one-time token).' : e instanceof Error ? e.message : 'SciCal could not start.';
    replace(root, h('p', { class: 'boot', role: 'alert', text: msg }));
    return;
  }
  initTheme();
  mount(root);
}

void start();
