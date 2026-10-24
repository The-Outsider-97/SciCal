// Application state: preferences, the open worksheet and its entries, with debounced saving to the service.
import { debounce } from '../core/util.js';
import { newEntryId, nowIso } from '../core/session.js';
import { DEFAULT_SETTINGS, type Entry, type FormCatalogue, type Prefs, type Session, type SessionMeta, type Settings, type Workspace } from '../core/types.js';
import { api, ApiError, type Status } from './api.js';

export type SaveState = 'saved' | 'saving' | 'error';
type Listener = () => void;

export class Store {
  prefs: Prefs = {};
  status!: Status;
  forms: FormCatalogue = {};
  session: Session | null = null;
  sessions: SessionMeta[] = [];
  workspace: Workspace = 'math';
  saveState: SaveState = 'saved';
  saveError = '';
  private listeners = new Map<string, Set<Listener>>();
  private prefsDirty: Prefs = {};

  on(event: string, fn: Listener): () => void {
    let set = this.listeners.get(event);
    if (!set) { set = new Set(); this.listeners.set(event, set); }
    set.add(fn);
    return () => { set?.delete(fn); };
  }

  emit(event: string): void {
    for (const fn of this.listeners.get(event) ?? []) {
      try { fn(); } catch (e) { console.error(e); }
    }
  }

  // ---------------------------------------------------------------------------------------------------------- start-up
  async init(): Promise<void> {
    const [status, forms] = await Promise.all([api.status(), api.forms()]);
    this.status = status;
    this.prefs = status.prefs ?? {};
    this.forms = forms.domains;
    const ws = this.prefs.workspace;
    if (ws === 'math' || ws === 'chemistry' || ws === 'biology' || ws === 'measurement') this.workspace = ws;
    await this.openInitialSession();
  }

  private async openInitialSession(): Promise<void> {
    const list = await api.sessions();
    this.sessions = list.sessions;
    const last = this.prefs.lastSession;
    if (last && this.sessions.some((s) => s.id === last)) {
      try { await this.openSession(last); return; } catch { /* fall through to a new worksheet */ }
    }
    if (this.sessions.length > 0) {
      try { await this.openSession(this.sessions[0].id); return; } catch { /* fall through */ }
    }
    await this.newSession('Worksheet 1');
  }

  // ---------------------------------------------------------------------------------------------------------- settings
  get settings(): Settings {
    const p = this.prefs;
    return {
      ...DEFAULT_SETTINGS,
      angle: p.angle ?? DEFAULT_SETTINGS.angle, digits: p.digits ?? DEFAULT_SETTINGS.digits, notation: p.notation ?? DEFAULT_SETTINGS.notation,
      result: p.result ?? DEFAULT_SETTINGS.result, thousands: p.thousands ?? false, units: p.units ?? false, complex: p.complex ?? false,
    };
  }

  setPrefs(patch: Prefs): void {
    this.prefs = { ...this.prefs, ...patch };
    this.prefsDirty = { ...this.prefsDirty, ...patch };
    this.flushPrefs();
    this.emit('prefs');
  }

  private flushPrefs = debounce(() => {
    const body = this.prefsDirty;
    this.prefsDirty = {};
    api.savePrefs(body).catch(() => { /* preferences are a convenience; a failure must not interrupt work */ });
  }, 500);

  // ---------------------------------------------------------------------------------------------------------- worksheets
  get entries(): Entry[] { return this.session?.entries ?? []; }

  async refreshSessions(): Promise<void> {
    this.sessions = (await api.sessions()).sessions;
    this.emit('sessions');
  }

  async openSession(id: string): Promise<void> {
    await this.flush();
    const { session } = await api.getSession(id);
    this.session = session;
    this.setPrefs({ lastSession: id });
    this.saveState = 'saved';
    this.emit('session');
    this.emit('entries');
  }

  async newSession(name?: string): Promise<void> {
    await this.flush();
    const s = await api.createSession(name, this.workspace === 'math' ? 'math' : this.workspace, this.settings as unknown as Record<string, unknown>);
    this.session = s;
    this.setPrefs({ lastSession: s.id });
    await this.refreshSessions();
    this.emit('session');
    this.emit('entries');
  }

  async renameSession(name: string): Promise<void> {
    if (!this.session) return;
    const r = await api.saveSession(this.session.id, { name });
    this.session.name = r.name;
    await this.refreshSessions();
    this.emit('session');
  }

  async deleteSession(id: string): Promise<void> {
    await api.deleteSession(id);
    await this.refreshSessions();
    if (this.session?.id === id) {
      if (this.sessions.length) await this.openSession(this.sessions[0].id);
      else await this.newSession('Worksheet 1');
    }
  }

  async setAgentsAllowed(allow: boolean): Promise<void> {
    if (!this.session) return;
    await api.assistConsent(this.session.id, allow);
    this.session.agentsAllowed = allow;
    this.emit('session');
  }

  // ---------------------------------------------------------------------------------------------------------- entries
  addEntry(partial: Omit<Entry, 'id' | 'time'>): Entry {
    if (!this.session) throw new Error('No worksheet is open');
    const e: Entry = { id: newEntryId(), time: nowIso(), ...partial };
    this.session.entries.push(e);
    this.changed();
    return e;
  }

  removeEntry(id: string): void {
    if (!this.session) return;
    this.session.entries = this.session.entries.filter((e) => e.id !== id);
    this.changed();
  }

  clearEntries(kinds?: Entry['kind'][]): void {
    if (!this.session) return;
    this.session.entries = kinds ? this.session.entries.filter((e) => !kinds.includes(e.kind)) : [];
    this.changed();
  }

  updateEntry(id: string, patch: Partial<Entry>): void {
    const e = this.session?.entries.find((x) => x.id === id);
    if (!e) return;
    Object.assign(e, patch);
    this.changed();
  }

  private changed(): void {
    this.saveState = 'saving';
    this.emit('entries');
    this.emit('save');
    this.save();
  }

  private save = debounce(() => { void this.flushNow(); }, 700);

  async flush(): Promise<void> {
    this.save.cancel();
    if (this.saveState === 'saving') await this.flushNow();
  }

  private async flushNow(): Promise<void> {
    const s = this.session;
    if (!s) return;
    try {
      await api.saveSession(s.id, { entries: s.entries });
      if (this.session === s) { this.saveState = 'saved'; this.saveError = ''; }
    } catch (e) {
      this.saveState = 'error';
      this.saveError = e instanceof ApiError ? e.message : 'The worksheet could not be saved.';
    }
    this.emit('save');
  }

  setWorkspace(ws: Workspace): void {
    this.workspace = ws;
    if (ws !== 'graph' && ws !== 'formulas') this.setPrefs({ workspace: ws });
    this.emit('workspace');
  }
}

export const store = new Store();
