import { $ } from './dom.js';
import { mount, registerView } from './shell.js';
import { initTheme } from './settings.js';
import { store } from './store.js';
import { ApiError } from './api.js';
import { h, replace } from './dom.js';
registerView('math', async () => (await import('./views/math.js')).createMathView());
registerView('graph', async () => (await import('./views/graph.js')).createGraphView());
registerView('chemistry', async () => (await import('./views/domain.js')).createDomainView('chemistry'));
registerView('biology', async () => (await import('./views/domain.js')).createDomainView('biology'));
registerView('measurement', async () => (await import('./views/domain.js')).createDomainView('measurement'));
registerView('formulas', async () => (await import('./views/domain.js')).createDomainView('formulas'));
async function start() {
    const root = $('#app');
    try {
        await store.init();
    }
    catch (e) {
        const msg = e instanceof ApiError && e.status === 401 ? 'SciCal is locked. Open it from the link printed when it started (it contains a one-time token).' : e instanceof Error ? e.message : 'SciCal could not start.';
        replace(root, h('p', { class: 'boot', role: 'alert', text: msg }));
        return;
    }
    initTheme();
    mount(root);
}
void start();
//# sourceMappingURL=main.js.map