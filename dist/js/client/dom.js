const BOOLEAN = new Set(['disabled', 'checked', 'hidden', 'readonly', 'required', 'selected', 'open', 'multiple', 'autofocus']);
const PROPS = new Set(['value', 'checked', 'disabled', 'selected', 'indeterminate']);
function apply(el, attrs) {
    if (!attrs)
        return;
    for (const [key, val] of Object.entries(attrs)) {
        if (val === undefined || val === null || val === false)
            continue;
        if (key === 'class')
            el.setAttribute('class', String(val));
        else if (key === 'text')
            el.textContent = String(val);
        else if (key === 'style')
            for (const [k, v] of Object.entries(val))
                el.style.setProperty(k, v);
        else if (key === 'on')
            for (const [ev, fn] of Object.entries(val))
                el.addEventListener(ev, fn);
        else if (key === 'data')
            for (const [k, v] of Object.entries(val))
                el.dataset[k] = v;
        else if (PROPS.has(key) && key in el)
            el[key] = val;
        else if (BOOLEAN.has(key))
            el.setAttribute(key, '');
        else
            el.setAttribute(key, String(val));
    }
}
function append(parent, children) {
    for (const c of children) {
        if (c === null || c === undefined || c === false)
            continue;
        if (Array.isArray(c))
            append(parent, c);
        else if (typeof c === 'string' || typeof c === 'number')
            parent.appendChild(document.createTextNode(String(c)));
        else
            parent.appendChild(c);
    }
}
export function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    apply(el, attrs);
    append(el, children);
    return el;
}
const SVG_NS = 'http://www.w3.org/2000/svg';
export function s(tag, attrs, ...children) {
    const el = document.createElementNS(SVG_NS, tag);
    apply(el, attrs);
    append(el, children);
    return el;
}
export function clear(el) {
    while (el.firstChild)
        el.removeChild(el.firstChild);
}
export function replace(el, ...children) {
    clear(el);
    append(el, children);
}
export function $(sel, root = document) {
    const el = root.querySelector(sel);
    if (!el)
        throw new Error(`Missing element ${sel}`);
    return el;
}
//# sourceMappingURL=dom.js.map