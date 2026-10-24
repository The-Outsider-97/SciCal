// Shared interface pieces: toasts, modal dialogs, icons, clipboard and file download.
import { h, s, clear } from './dom.js';
// ------------------------------------------------------------------------------------------------------------------ icons
const ASSET_ICONS = { math: 'SciCal.png', chemistry: 'chemistry.png', biology: 'Biology.png', measurement: 'measurment.png', logo: 'logo.png' };
/** Gold icons from the SLAI-wide assets folder, drawn as masks so they follow the theme colour. */
export function assetIcon(name, cls = '') {
    const file = ASSET_ICONS[name];
    const el = h('span', { class: `icon asset ${cls}`, 'aria-hidden': 'true' });
    if (file)
        el.style.setProperty('--icon', `url(/assets/${file})`);
    return el;
}
const GLYPHS = {
    graph: ['M4 3v18h18', 'M6 17c3-9 6-9 8-3s4 5 6-6'],
    formulas: ['M8 4c-2 0-3 1-3.4 3L3 15c-.3 1.6-1 2-2 2', 'M5 10h6', 'M13 11l7 7', 'M20 11l-7 7'],
    search: ['M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z', 'M16.5 16.5L21 21'],
    gear: ['M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z', 'M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1'],
    sheet: ['M6 3h9l4 4v14H6z', 'M14 3v5h5', 'M9 12h7M9 15h7M9 18h5'],
    assistant: ['M12 3l1.8 4.6L18.5 9l-4.7 1.4L12 15l-1.8-4.6L5.5 9l4.7-1.4z', 'M18 15l.8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8z'],
    copy: ['M8 8h11v13H8z', 'M5 16V3h11'],
    trash: ['M4 7h16', 'M9 7V4h6v3', 'M6 7l1 14h10l1-14', 'M10 11v6M14 11v6'],
    plus: ['M12 5v14M5 12h14'],
    close: ['M6 6l12 12M18 6L6 18'],
    chevron: ['M7 10l5 5 5-5'],
    download: ['M12 4v11', 'M7 11l5 5 5-5', 'M5 20h14'],
    steps: ['M5 6h14M5 12h10M5 18h6'],
    reuse: ['M4 12a8 8 0 1 0 3-6.2', 'M4 4v5h5'],
    pin: ['M9 3h6l-1 6 3 3H7l3-3z', 'M12 12v8'],
    info: ['M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z', 'M12 11v6', 'M12 7.5v.5'],
    keypad: ['M5 5h3v3H5zM10.5 5h3v3h-3zM16 5h3v3h-3zM5 10.5h3v3H5zM10.5 10.5h3v3h-3zM16 10.5h3v3h-3zM5 16h3v3H5zM10.5 16h3v3h-3zM16 16h3v3h-3z'],
    eye: ['M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z', 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z'],
    eyeoff: ['M3 3l18 18', 'M10 6.2A9 9 0 0 1 12 6c6 0 10 6 10 6a17 17 0 0 1-3.2 3.6', 'M6.2 7.4A17 17 0 0 0 2 12s4 6 10 6c1.4 0 2.7-.3 3.8-.8'],
    play: ['M7 5l12 7-12 7z'],
    link: ['M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1', 'M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1'],
};
export function glyph(name, cls = '') {
    const svg = s('svg', { class: `glyph ${cls}`, viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false' });
    for (const d of GLYPHS[name] ?? [])
        svg.appendChild(s('path', { d }));
    return svg;
}
export function icon(name, cls = '') {
    return name in ASSET_ICONS ? assetIcon(name, cls) : glyph(name, cls);
}
export function iconButton(name, label, onClick, cls = '') {
    return h('button', { class: `iconbtn ${cls}`, type: 'button', 'aria-label': label, title: label, on: { click: onClick } }, glyph(name));
}
// ------------------------------------------------------------------------------------------------------------------ toasts
let toastHost = null;
export function toast(message, kind = 'info', ms = 0) {
    if (!toastHost) {
        toastHost = h('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' });
        document.body.appendChild(toastHost);
    }
    const host = toastHost;
    const t = h('div', { class: `toast ${kind}` }, h('span', { text: message }), h('button', { class: 'iconbtn tiny', type: 'button', 'aria-label': 'Dismiss', on: { click: () => t.remove() } }, glyph('close')));
    if (kind === 'error')
        t.setAttribute('role', 'alert');
    host.appendChild(t);
    while (host.children.length > 4)
        host.firstElementChild?.remove();
    setTimeout(() => t.remove(), ms || (kind === 'error' ? 9000 : 4500));
}
export function dialog(title, content, opts = {}) {
    const body = h('div', { class: 'dialog-body' }, content);
    const el = h('dialog', { class: `dialog ${opts.wide ? 'wide' : ''} ${opts.cls ?? ''}`, 'aria-label': title });
    const close = () => { if (el.open)
        el.close(); };
    el.append(h('header', { class: 'dialog-head' }, h('h2', { text: title }), iconButton('close', 'Close', close)), body, opts.actions ? h('footer', { class: 'dialog-actions' }, opts.actions) : '');
    el.addEventListener('close', () => { opts.onClose?.(); el.remove(); });
    el.addEventListener('click', (ev) => { if (ev.target === el)
        close(); }); // click on the backdrop
    document.body.appendChild(el);
    el.showModal();
    return { el, body, close };
}
export function confirmDialog(title, message, confirmLabel = 'Delete', danger = true) {
    return new Promise((resolve) => {
        let answer = false;
        const d = dialog(title, h('p', { text: message }), {
            onClose: () => resolve(answer),
            actions: [
                h('button', { class: 'btn', type: 'button', text: 'Cancel', on: { click: () => d.close() } }),
                h('button', { class: `btn ${danger ? 'danger' : 'primary'}`, type: 'button', text: confirmLabel, on: { click: () => { answer = true; d.close(); } } }),
            ],
        });
        d.el.querySelector('.btn')?.focus();
    });
}
export function promptDialog(title, label, value = '', okLabel = 'OK') {
    return new Promise((resolve) => {
        let answer = null;
        const input = h('input', { type: 'text', value, maxlength: '120', 'aria-label': label });
        const submit = () => { answer = input.value.trim(); d.close(); };
        input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') {
            ev.preventDefault();
            submit();
        } });
        const d = dialog(title, h('label', { class: 'field' }, h('span', { text: label }), input), {
            onClose: () => resolve(answer),
            actions: [h('button', { class: 'btn', type: 'button', text: 'Cancel', on: { click: () => { answer = null; d.close(); } } }), h('button', { class: 'btn primary', type: 'button', text: okLabel, on: { click: submit } })],
        });
        input.focus();
        input.select();
    });
}
// ------------------------------------------------------------------------------------------------------------------ files
export async function copyText(text, what = 'Copied') {
    try {
        await navigator.clipboard.writeText(text);
        toast(what, 'ok', 1800);
    }
    catch {
        const ta = h('textarea', { 'aria-hidden': 'true', readonly: true });
        ta.value = text;
        ta.style.setProperty('position', 'fixed');
        ta.style.setProperty('left', '-9999px');
        document.body.appendChild(ta);
        ta.select();
        try {
            document.execCommand('copy');
            toast(what, 'ok', 1800);
        }
        catch {
            toast('Copying is not allowed in this browser window.', 'error');
        }
        ta.remove();
    }
}
export function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
}
export function readFileText(file, limit = 8 * 1024 * 1024) {
    return new Promise((resolve, reject) => {
        if (file.size > limit) {
            reject(new Error('That file is too large.'));
            return;
        }
        const r = new FileReader();
        r.onload = () => resolve(String(r.result));
        r.onerror = () => reject(new Error('The file could not be read.'));
        r.readAsText(file);
    });
}
export function emptyNote(text) {
    return h('p', { class: 'empty', text });
}
export function setBusy(el, busy) {
    el.setAttribute('aria-busy', busy ? 'true' : 'false');
    el.classList.toggle('busy', busy);
}
export function replaceChildren(el, ...children) {
    clear(el);
    for (const c of children)
        if (c !== null && c !== undefined && c !== false)
            el.append(c);
}
//# sourceMappingURL=ui.js.map