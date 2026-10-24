import type { ApiErrorBody, CalcResult, FormCatalogue, GraphResult, Json, Prefs, Session, SessionMeta, Settings } from '../core/types.js';
import { uid } from '../core/util.js';

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string, readonly hint?: string, readonly details?: Record<string, unknown>) {
    super(message);
  }
}

interface Envelope<T> { ok: boolean; data?: T; error?: ApiErrorBody; [k: string]: unknown }

export interface ComputeFailure { ok: false; error: ApiErrorBody }
export type Compute<T> = (T & { ok: true }) | ComputeFailure;

export interface Status {
  app: string;
  version: string;
  platform: string;
  settings: Record<string, unknown>;
  pool: Record<string, unknown>;
  slai: { slaiRoot: string | null; sldc: Record<string, unknown>; agentGateway: { available: boolean; reason?: string | null }; apps: Record<string, { running?: boolean; [k: string]: unknown }> };
  dataDir: string;
  startupNotes: string[];
  prefs: Prefs;
}

export interface AssistStatus {
  mode: string;
  gateway: boolean;
  reason: string | null;
  roles: Record<string, { state?: string; class?: string | null; error?: string | null; tested?: unknown }>;
  notUsed?: Record<string, string>;
  stem?: string;
  [k: string]: unknown;
}

export interface Download { blob: Blob; filename: string }

const MARKER = { 'X-SLAI-SciCal': '1' };

export class Api {
  private async send(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    let payload: string | undefined;
    if (method !== 'GET') {
      Object.assign(headers, MARKER);
      if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
    }
    let res: Response;
    try {
      res = await fetch(path, { method, headers, body: payload, credentials: 'same-origin', signal });
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') throw e;
      throw new ApiError('Cannot reach the SciCal service. Is it still running?', 0, 'network');
    }
    return res;
  }

  private async fail(res: Response): Promise<never> {
    let err: ApiErrorBody | undefined;
    try { err = ((await res.json()) as Envelope<unknown>).error; } catch { /* not JSON */ }
    throw new ApiError(err?.message ?? `The service answered ${res.status}`, res.status, err?.code ?? 'http_' + res.status, err?.hint, err?.details);
  }

  /** Endpoints that answer {"ok": true, "data": ...}. */
  async data<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await this.send(method, path, body);
    if (!res.ok) return this.fail(res);
    const env = (await res.json()) as Envelope<T>;
    if (!env.ok) throw new ApiError(env.error?.message ?? 'The request failed', res.status, env.error?.code ?? 'error', env.error?.hint);
    return env.data as T;
  }

  async dataWith<T>(method: string, path: string, body?: unknown): Promise<Envelope<T>> {
    const res = await this.send(method, path, body);
    if (!res.ok) return this.fail(res);
    return (await res.json()) as Envelope<T>;
  }

  /** Compute endpoints answer with the result itself; a mathematical error is data, only transport problems throw. */
  async compute<T extends { ok: boolean }>(path: string, body: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
    const res = await this.send('POST', path, body, signal);
    if (!res.ok) {
      // A stopped calculation (timeout, cancel) is an answer the page shows on the entry, not a broken request.
      if (res.status === 408 || res.status === 499) {
        try {
          const data = (await res.clone().json()) as T;
          if (data && data.ok === false) return data;
        } catch { /* fall through to the generic failure */ }
      }
      return this.fail(res);
    }
    return (await res.json()) as T;
  }

  newJob(): string { return uid('j'); }

  async cancel(jobId: string): Promise<void> {
    try { await this.send('POST', '/api/cancel', { jobId }); } catch { /* the job may already be finished */ }
  }

  async download(path: string, body: unknown): Promise<Download> {
    const res = await this.send('POST', path, body);
    if (!res.ok) return this.fail(res);
    const cd = res.headers.get('Content-Disposition') ?? '';
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
    return { blob: await res.blob(), filename: m ? decodeURIComponent(m[1]) : 'download' };
  }

  // ---- typed shortcuts
  status(): Promise<Status> { return this.data('GET', '/api/status'); }
  forms(): Promise<{ domains: FormCatalogue }> { return this.data('GET', '/api/forms'); }
  prefs(): Promise<Prefs> { return this.data('GET', '/api/prefs'); }
  savePrefs(p: Prefs): Promise<Prefs> { return this.data('PUT', '/api/prefs', p); }

  calc(input: string, settings: Settings, context: string[], explain: boolean, jobId: string): Promise<CalcResult> {
    return this.compute('/api/calc', { input, settings, context, explain, jobId });
  }
  domain(domain: string, op: string, params: Record<string, unknown>, settings: Settings, jobId: string): Promise<Record<string, unknown> & { ok: boolean; error?: ApiErrorBody }> {
    return this.compute('/api/domain', { domain, op, params, settings, jobId });
  }
  graph(op: 'render' | 'analyze', spec: Record<string, unknown>, settings: Settings, context: string[], signal?: AbortSignal): Promise<GraphResult & Record<string, unknown>> {
    return this.compute('/api/graph', { op, spec, settings, context }, signal);
  }

  sessions(): Promise<{ sessions: SessionMeta[] }> { return this.data('GET', '/api/sessions'); }
  createSession(name?: string, workspace = 'math', settings?: Record<string, unknown>): Promise<Session> { return this.data('POST', '/api/sessions', { name, workspace, settings }); }
  importSession(doc: Json): Promise<Session> { return this.data('POST', '/api/sessions', { import: doc }); }
  async getSession(id: string): Promise<{ session: Session; context: string[] }> {
    const env = await this.dataWith<Session>('GET', '/api/sessions/' + encodeURIComponent(id));
    return { session: env.data as Session, context: (env.context as string[] | undefined) ?? [] };
  }
  saveSession(id: string, body: Record<string, unknown>): Promise<{ id: string; name: string; updated: string; entries: number }> {
    return this.data('PUT', '/api/sessions/' + encodeURIComponent(id), body);
  }
  deleteSession(id: string): Promise<{ deleted: boolean }> { return this.data('DELETE', '/api/sessions/' + encodeURIComponent(id)); }
  search(q: string): Promise<{ hits: Array<Record<string, unknown>> }> { return this.data('GET', '/api/history/search?q=' + encodeURIComponent(q)); }

  exportSession(sessionId: string, format: string): Promise<Download> { return this.download('/api/export', { sessionId, format }); }
  exportTable(name: string, columns: string[], rows: unknown[][]): Promise<Download> { return this.download('/api/export/table', { name, columns, rows }); }
  handoff(sessionId: string, target: string): Promise<{ document: string; handoff: string; target: string; note: string; apps: Record<string, unknown> }> {
    return this.data('POST', '/api/handoff', { sessionId, target });
  }

  interpret(text: string, sessionId?: string): Promise<{ proposals: Array<Record<string, unknown>>; agent?: Record<string, unknown> }> {
    return this.data('POST', '/api/interpret', { text, sessionId });
  }
  assistStatus(): Promise<AssistStatus> { return this.data('GET', '/api/assist/status'); }
  assistProbe(): Promise<AssistStatus> { return this.data('POST', '/api/assist/probe', {}); }
  assistConsent(sessionId: string, allow: boolean): Promise<Record<string, unknown>> { return this.data('POST', '/api/assist/consent', { sessionId, allow }); }
  assistExplain(sessionId: string | undefined, entry: Record<string, unknown>): Promise<Record<string, unknown>> { return this.data('POST', '/api/assist/explain', { sessionId, entry }); }
  assistCrosscheck(values: unknown[]): Promise<Record<string, unknown>> { return this.data('POST', '/api/assist/crosscheck', { values }); }
}

export const api = new Api();
