import { uid } from '../core/util.js';
export class ApiError extends Error {
    status;
    code;
    hint;
    details;
    constructor(message, status, code, hint, details) {
        super(message);
        this.status = status;
        this.code = code;
        this.hint = hint;
        this.details = details;
    }
}
const MARKER = { 'X-SLAI-SciCal': '1' };
export class Api {
    async send(method, path, body, signal) {
        const headers = { Accept: 'application/json' };
        let payload;
        if (method !== 'GET') {
            Object.assign(headers, MARKER);
            if (body !== undefined) {
                headers['Content-Type'] = 'application/json';
                payload = JSON.stringify(body);
            }
        }
        let res;
        try {
            res = await fetch(path, { method, headers, body: payload, credentials: 'same-origin', signal });
        }
        catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError')
                throw e;
            throw new ApiError('Cannot reach the SciCal service. Is it still running?', 0, 'network');
        }
        return res;
    }
    async fail(res) {
        let err;
        try {
            err = (await res.json()).error;
        }
        catch { /* not JSON */ }
        throw new ApiError(err?.message ?? `The service answered ${res.status}`, res.status, err?.code ?? 'http_' + res.status, err?.hint, err?.details);
    }
    /** Endpoints that answer {"ok": true, "data": ...}. */
    async data(method, path, body) {
        const res = await this.send(method, path, body);
        if (!res.ok)
            return this.fail(res);
        const env = (await res.json());
        if (!env.ok)
            throw new ApiError(env.error?.message ?? 'The request failed', res.status, env.error?.code ?? 'error', env.error?.hint);
        return env.data;
    }
    async dataWith(method, path, body) {
        const res = await this.send(method, path, body);
        if (!res.ok)
            return this.fail(res);
        return (await res.json());
    }
    /** Compute endpoints answer with the result itself; a mathematical error is data, only transport problems throw. */
    async compute(path, body, signal) {
        const res = await this.send('POST', path, body, signal);
        if (!res.ok) {
            // A stopped calculation (timeout, cancel) is an answer the page shows on the entry, not a broken request.
            if (res.status === 408 || res.status === 499) {
                try {
                    const data = (await res.clone().json());
                    if (data && data.ok === false)
                        return data;
                }
                catch { /* fall through to the generic failure */ }
            }
            return this.fail(res);
        }
        return (await res.json());
    }
    newJob() { return uid('j'); }
    async cancel(jobId) {
        try {
            await this.send('POST', '/api/cancel', { jobId });
        }
        catch { /* the job may already be finished */ }
    }
    async download(path, body) {
        const res = await this.send('POST', path, body);
        if (!res.ok)
            return this.fail(res);
        const cd = res.headers.get('Content-Disposition') ?? '';
        const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
        return { blob: await res.blob(), filename: m ? decodeURIComponent(m[1]) : 'download' };
    }
    // ---- typed shortcuts
    status() { return this.data('GET', '/api/status'); }
    forms() { return this.data('GET', '/api/forms'); }
    prefs() { return this.data('GET', '/api/prefs'); }
    savePrefs(p) { return this.data('PUT', '/api/prefs', p); }
    calc(input, settings, context, explain, jobId) {
        return this.compute('/api/calc', { input, settings, context, explain, jobId });
    }
    domain(domain, op, params, settings, jobId) {
        return this.compute('/api/domain', { domain, op, params, settings, jobId });
    }
    graph(op, spec, settings, context, signal) {
        return this.compute('/api/graph', { op, spec, settings, context }, signal);
    }
    /** Save the graph as an SGEO or SDRW file with SLAI's own writers. Failures (nothing to save, a bad unit) throw an ApiError with the service's reason. */
    async exportGraph(body) {
        const res = await this.send('POST', '/api/graph/export', body);
        if (!res.ok)
            return this.fail(res);
        return (await res.json());
    }
    sessions() { return this.data('GET', '/api/sessions'); }
    createSession(name, workspace = 'math', settings) { return this.data('POST', '/api/sessions', { name, workspace, settings }); }
    importSession(doc) { return this.data('POST', '/api/sessions', { import: doc }); }
    async getSession(id) {
        const env = await this.dataWith('GET', '/api/sessions/' + encodeURIComponent(id));
        return { session: env.data, context: env.context ?? [] };
    }
    saveSession(id, body) {
        return this.data('PUT', '/api/sessions/' + encodeURIComponent(id), body);
    }
    deleteSession(id) { return this.data('DELETE', '/api/sessions/' + encodeURIComponent(id)); }
    search(q) { return this.data('GET', '/api/history/search?q=' + encodeURIComponent(q)); }
    exportSession(sessionId, format) { return this.download('/api/export', { sessionId, format }); }
    exportTable(name, columns, rows) { return this.download('/api/export/table', { name, columns, rows }); }
    handoff(sessionId, target) {
        return this.data('POST', '/api/handoff', { sessionId, target });
    }
    interpret(text, sessionId) {
        return this.data('POST', '/api/interpret', { text, sessionId });
    }
    assistStatus() { return this.data('GET', '/api/assist/status'); }
    assistProbe() { return this.data('POST', '/api/assist/probe', {}); }
    assistConsent(sessionId, allow) { return this.data('POST', '/api/assist/consent', { sessionId, allow }); }
    assistExplain(sessionId, entry) { return this.data('POST', '/api/assist/explain', { sessionId, entry }); }
    assistCrosscheck(values) { return this.data('POST', '/api/assist/crosscheck', { values }); }
}
export const api = new Api();
//# sourceMappingURL=api.js.map