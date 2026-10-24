// A tiny DOM builder. Text is always set with textContent / createTextNode, never innerHTML:
// whatever the server (or a worksheet file) contains can never become markup.
export type Child = Node | string | number | null | undefined | false | Child[];

export interface Attrs {
  class?: string;
  text?: string;
  style?: Record<string, string>;
  on?: Record<string, (ev: any) => void>;
  data?: Record<string, string>;
  [attr: string]: unknown;
}

const BOOLEAN = new Set(['disabled', 'checked', 'hidden', 'readonly', 'required', 'selected', 'open', 'multiple', 'autofocus']);
const PROPS = new Set(['value', 'checked', 'disabled', 'selected', 'indeterminate']);

function apply(el: Element, attrs: Attrs | null | undefined): void {
  if (!attrs) return;
  for (const [key, val] of Object.entries(attrs)) {
    if (val === undefined || val === null || val === false) continue;
    if (key === 'class') el.setAttribute('class', String(val));
    else if (key === 'text') el.textContent = String(val);
    else if (key === 'style') for (const [k, v] of Object.entries(val as Record<string, string>)) (el as HTMLElement).style.setProperty(k, v);
    else if (key === 'on') for (const [ev, fn] of Object.entries(val as Record<string, (e: Event) => void>)) el.addEventListener(ev, fn);
    else if (key === 'data') for (const [k, v] of Object.entries(val as Record<string, string>)) (el as HTMLElement).dataset[k] = v;
    else if (PROPS.has(key) && key in el) (el as unknown as Record<string, unknown>)[key] = val;
    else if (BOOLEAN.has(key)) el.setAttribute(key, '');
    else el.setAttribute(key, String(val));
  }
}

function append(parent: Node, children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(parent, c);
    else if (typeof c === 'string' || typeof c === 'number') parent.appendChild(document.createTextNode(String(c)));
    else parent.appendChild(c);
  }
}

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Attrs | null, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

const SVG_NS = 'http://www.w3.org/2000/svg';
export function s(tag: string, attrs?: Attrs | null, ...children: Child[]): SVGElement {
  const el = document.createElementNS(SVG_NS, tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

export function clear(el: Element): void {
  while (el.firstChild) el.removeChild(el.firstChild);
}

export function replace(el: Element, ...children: Child[]): void {
  clear(el);
  append(el, children);
}

export function $(sel: string, root: ParentNode = document): HTMLElement {
  const el = root.querySelector<HTMLElement>(sel);
  if (!el) throw new Error(`Missing element ${sel}`);
  return el;
}
