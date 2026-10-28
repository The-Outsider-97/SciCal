// Application state: preferences, the open worksheet and its entries, with debounced saving to the service.
import { debounce } from '../core/util.js';
import { newEntryId, nowIso } from '../core/session.js';
import { DEFAULT_SETTINGS } from '../core/types.js';
import { api, ApiError } from './api.js';
export class Store {
    prefs = {};
    status;
    forms = {};
    session = null;
    sessions = [];
    workspace = 'math';
    saveState = 'saved';
    saveError = '';
    listeners = new Map();
    prefsDirty = {};
    on(event, fn) {
        let set = this.listeners.get(event);
        if (!set) {
            set = new Set();
            this.listeners.set(event, set);
        }
        set.add(fn);
        return () => { set?.delete(fn); };
    }
    emit(event) {
        for (const fn of this.listeners.get(event) ?? []) {
            try {
                fn();
            }
            catch (e) {
                console.error(e);
            }
        }
    }
    // ---------------------------------------------------------------------------------------------------------- start-up
    async init() {
        const [status, forms] = await Promise.all([api.status(), api.forms()]);
        this.status = status;
        this.prefs = status.prefs ?? {};
        this.forms = forms.domains;
        const ws = this.prefs.workspace;
        if (ws === 'math' || ws === 'chemistry' || ws === 'biology' || ws === 'measurement' || ws === 'finance' || ws === 'constants')
            this.workspace = ws;
        await this.openInitialSession();
    }
    async openInitialSession() {
        const list = await api.sessions();
        this.sessions = list.sessions;
        const last = this.prefs.lastSession;
        if (last && this.sessions.some((s) => s.id === last)) {
            try {
                await this.openSession(last);
                return;
            }
            catch { /* fall through to a new worksheet */ }
        }
        if (this.sessions.length > 0) {
            try {
                await this.openSession(this.sessions[0].id);
                return;
            }
            catch { /* fall through */ }
        }
        await this.newSession('Worksheet 1');
    }
    // ---------------------------------------------------------------------------------------------------------- settings
    get settings() {
        const p = this.prefs;
        return {
            ...DEFAULT_SETTINGS,
            angle: p.angle ?? DEFAULT_SETTINGS.angle, digits: p.digits ?? DEFAULT_SETTINGS.digits, notation: p.notation ?? DEFAULT_SETTINGS.notation,
            result: p.result ?? DEFAULT_SETTINGS.result, thousands: p.thousands ?? false, units: p.units ?? false, complex: p.complex ?? false,
        };
    }
    setPrefs(patch) {
        this.prefs = { ...this.prefs, ...patch };
        for (const [k, v] of Object.entries(patch))
            if (v === null)
                delete this.prefs[k]; // null = removed
        this.prefsDirty = { ...this.prefsDirty, ...patch };
        this.flushPrefs();
        this.emit('prefs');
    }
    flushPrefs = debounce(() => {
        const body = this.prefsDirty;
        this.prefsDirty = {};
        api.savePrefs(body).catch(() => { });
    }, 500);
    // ---------------------------------------------------------------------------------------------------------- worksheets
    get entries() { return this.session?.entries ?? []; }
    async refreshSessions() {
        this.sessions = (await api.sessions()).sessions;
        this.emit('sessions');
    }
    async openSession(id) {
        await this.flush();
        const { session } = await api.getSession(id);
        this.session = session;
        this.setPrefs({ lastSession: id });
        this.saveState = 'saved';
        this.emit('session');
        this.emit('entries');
    }
    async newSession(name) {
        await this.flush();
        const s = await api.createSession(name, this.workspace === 'math' ? 'math' : this.workspace, this.settings);
        this.session = s;
        this.setPrefs({ lastSession: s.id });
        await this.refreshSessions();
        this.emit('session');
        this.emit('entries');
    }
    async renameSession(name) {
        if (!this.session)
            return;
        const r = await api.saveSession(this.session.id, { name });
        this.session.name = r.name;
        await this.refreshSessions();
        this.emit('session');
    }
    async deleteSession(id) {
        await api.deleteSession(id);
        await this.refreshSessions();
        if (this.session?.id === id) {
            if (this.sessions.length)
                await this.openSession(this.sessions[0].id);
            else
                await this.newSession('Worksheet 1');
        }
    }
    async setAgentsAllowed(allow) {
        if (!this.session)
            return;
        await api.assistConsent(this.session.id, allow);
        this.session.agentsAllowed = allow;
        this.emit('session');
    }
    // ---------------------------------------------------------------------------------------------------------- entries
    addEntry(partial) {
        if (!this.session)
            throw new Error('No worksheet is open');
        const e = { id: newEntryId(), time: nowIso(), ...partial };
        this.session.entries.push(e);
        this.changed();
        return e;
    }
    removeEntry(id) {
        if (!this.session)
            return;
        this.session.entries = this.session.entries.filter((e) => e.id !== id);
        this.changed();
    }
    clearEntries(kinds) {
        if (!this.session)
            return;
        this.session.entries = kinds ? this.session.entries.filter((e) => !kinds.includes(e.kind)) : [];
        this.changed();
    }
    updateEntry(id, patch) {
        const e = this.session?.entries.find((x) => x.id === id);
        if (!e)
            return;
        Object.assign(e, patch);
        this.changed();
    }
    changed() {
        this.saveState = 'saving';
        this.emit('entries');
        this.emit('save');
        this.save();
    }
    save = debounce(() => { void this.flushNow(); }, 700);
    async flush() {
        this.save.cancel();
        if (this.saveState === 'saving')
            await this.flushNow();
    }
    async flushNow() {
        const s = this.session;
        if (!s)
            return;
        try {
            await api.saveSession(s.id, { entries: s.entries });
            if (this.session === s) {
                this.saveState = 'saved';
                this.saveError = '';
            }
        }
        catch (e) {
            this.saveState = 'error';
            this.saveError = e instanceof ApiError ? e.message : 'The worksheet could not be saved.';
        }
        this.emit('save');
    }
    setWorkspace(ws) {
        this.workspace = ws;
        if (ws !== 'graph' && ws !== 'formulas')
            this.setPrefs({ workspace: ws });
        this.emit('workspace');
    }
}
export const store = new Store();
//# sourceMappingURL=store.js.map