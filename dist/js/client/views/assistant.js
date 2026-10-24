import { isRecord } from '../../core/util.js';
import { api, ApiError } from '../api.js';
import { h, replace } from '../dom.js';
import { store } from '../store.js';
import { dialog, toast } from '../ui.js';
const ROLE_TEXT = {
    privacy: 'Privacy agent: decides whether worksheet text may be passed on at all',
    safety: 'Safety agent: reviews text before it is shown',
    language: 'Language agent: writes explanations and orders suggestions',
};
function statusRows(st) {
    if (!st.gateway) {
        return h('div', { class: 'notes' }, h('div', { class: 'note-line', text: st.reason ?? 'The SLAI agents are not available.' }), h('p', { class: 'muted', text: 'SciCal works fully without them: every result comes from its own exact engine.' }));
    }
    return h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, h('thead', null, h('tr', null, h('th', { text: 'Role' }), h('th', { text: 'State' }), h('th', { text: 'Agent' }))), h('tbody', null, Object.entries(st.roles).map(([role, r]) => h('tr', null, h('td', { text: ROLE_TEXT[role] ?? role }), h('td', { text: r.state ?? '—' }), h('td', { text: r.class ?? r.error ?? '—' }))))));
}
export async function openAssistant() {
    const body = h('div', { class: 'dialog-body-inner', style: { display: 'grid', gap: '.9rem' } }, h('p', { class: 'muted', text: 'Checking the SLAI agents…' }));
    const d = dialog('SLAI assistant', body, { wide: true });
    const draw = async (probe) => {
        let st;
        try {
            st = probe ? await api.assistProbe() : await api.assistStatus();
        }
        catch (e) {
            replace(body, h('p', { class: 'note-line error', text: e instanceof ApiError ? e.message : 'Could not read the agent status.' }));
            return;
        }
        const s = store.session;
        const allow = h('input', { type: 'checkbox', checked: !!s?.agentsAllowed, disabled: !st.gateway || !s });
        allow.addEventListener('change', () => {
            store.setAgentsAllowed(allow.checked).then(() => toast(allow.checked ? 'Agents may now be used for this worksheet.' : 'Agents are off for this worksheet.', 'ok'))
                .catch((e) => { allow.checked = !allow.checked; toast(e instanceof ApiError ? e.message : 'Could not change the setting.', 'error'); });
        });
        replace(body, h('p', { text: 'SciCal calculates everything itself, exactly and the same way every time. The SLAI agents are an optional extra: they can put a worked result into words and put the most likely interpretation of a typed sentence first. They never decide a number.' }), statusRows(st), h('label', { class: 'switch' }, allow, h('span', { text: `Allow agents for “${s?.name ?? 'this worksheet'}”` })), h('p', { class: 'muted', text: 'When allowed, the text of the entry being explained is shown to SLAI’s Privacy agent first, and only passed to the language agent if the Privacy agent agrees. It stays on your computer unless your SLAI agents are configured to use an online model. You can switch this off at any time; it applies to this worksheet only.' }), h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', text: 'Test the agents again', on: { click: () => { replace(body, h('p', { class: 'muted', text: 'Testing…' })); void draw(true); } } })), st.stem ? h('p', { class: 'muted', text: 'Statistics cross-check: ' + st.stem }) : null);
    };
    await draw(false);
    d.el.focus();
}
export async function askExplain(entry) {
    const body = h('div', { style: { display: 'grid', gap: '.8rem' } }, h('p', { class: 'muted', text: 'Working out the explanation…' }));
    dialog('Explain this result', body, { wide: true });
    try {
        const r = await api.assistExplain(store.session?.id, entry);
        const local = (Array.isArray(r.local) ? r.local : []);
        const agent = isRecord(r.agent) ? r.agent : null;
        const skipped = typeof r.agentSkipped === 'string' ? r.agentSkipped : '';
        replace(body, h('p', { class: 'muted', text: String(r.label ?? 'Worked out by SciCal’s own engine.') }), local.length ? h('ol', { class: 'workings' }, local.map((s) => h('li', null, h('div', { class: 't', text: s.title }), s.detail ? h('div', { class: 'd', text: s.detail }) : null))) : h('p', { text: 'There is no further working to show for this entry.' }), agent ? h('div', { class: 'agent-note' }, h('div', { text: String(agent.text ?? '') }), h('span', { class: 'label', text: String(agent.label ?? '') })) : null, !agent && skipped ? h('div', { class: 'note-line', text: skipped }) : null, !agent && !skipped && !store.session?.agentsAllowed ? h('p', { class: 'muted', text: 'To get a plain-language explanation from a SLAI agent, allow agents for this worksheet in the assistant panel.' }) : null);
    }
    catch (e) {
        replace(body, h('p', { class: 'note-line error', text: e instanceof ApiError ? e.message : 'The explanation could not be produced.' }));
    }
}
//# sourceMappingURL=assistant.js.map