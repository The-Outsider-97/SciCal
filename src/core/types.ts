// Shapes of what the SciCal service sends. Compute results are kept loose on purpose: the backend adds fields over time and the
// generic result view shows whatever arrives.
export interface ApiErrorBody {
  code: string;
  message: string;
  hint?: string;
  span?: [number, number];
  details?: Record<string, unknown>;
}

export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

export interface NumText {
  text: string;
  latex: string;
  value?: number | null;
  exact?: string;
  approximate?: boolean;
  unit?: string;
}

export interface Rendering { text: string; latex: string }

export interface FormattedValue {
  t: string;
  text: string;
  latex?: string;
  primary?: 'exact' | 'approx';
  exact?: Rendering | null;
  approx?: Rendering | null;
  symbolic?: boolean;
  approximate?: boolean;
  mag?: FormattedValue;
  unit?: { text: string; pretty?: string; dimension?: string };
  rows?: FormattedValue[][];
  items?: FormattedValue[];
  symbol?: string;
  domain?: string;
  note?: string;
  [k: string]: unknown;
}

export interface Step { expr?: string; exprLatex?: string; value?: string; valueLatex?: string; title?: string; detail?: string; latex?: string }
export interface Warning { kind?: string; message: string }

export interface CalcResult {
  ok: boolean;
  input: string;
  normalized?: string;
  inputLatex?: string;
  value?: FormattedValue;
  kind?: string;
  name?: string;
  params?: string[];
  flags?: { exact: boolean; approximate: boolean; symbolic: boolean; complex: boolean };
  steps?: Step[];
  warnings?: Array<Warning | string>;
  numeric?: Record<string, unknown>;
  unit?: { text: string; pretty?: string; dimension?: string };
  error?: ApiErrorBody;
}

export interface Settings {
  angle: 'rad' | 'deg' | 'grad';
  complex: boolean;
  digits: number;
  notation: 'auto' | 'fixed' | 'sci' | 'eng';
  decimals?: number | null;
  result: 'auto' | 'exact' | 'approx';
  units: boolean;
  thousands: boolean;
}

export const DEFAULT_SETTINGS: Settings = { angle: 'rad', complex: false, digits: 12, notation: 'auto', result: 'auto', units: false, thousands: false };

export type Workspace = 'math' | 'graph' | 'chemistry' | 'biology' | 'measurement' | 'formulas';
export type EntryKind = 'calc' | 'domain' | 'graph' | 'formula' | 'note';

export interface Entry {
  id: string;
  kind: EntryKind;
  time: string;
  workspace?: string;
  input?: string;
  title?: string;
  text?: string;
  domain?: string;
  op?: string;
  params?: Record<string, unknown>;
  spec?: Record<string, unknown>;
  settings?: Record<string, unknown>;
  result?: Record<string, unknown>;
  summary?: Record<string, unknown>;
  defines?: string[];
  ok?: boolean;
}

export interface SessionMeta { id: string; name: string; updated: string; created?: string; workspace?: string; entries: number }

export interface Session extends Omit<SessionMeta, 'entries'> {
  schema: string;
  settings: Record<string, unknown>;
  entries: Entry[];
  agentsAllowed: boolean;
}

export interface Prefs {
  theme?: 'system' | 'light' | 'dark' | 'contrast';
  angle?: Settings['angle'];
  digits?: number;
  notation?: Settings['notation'];
  result?: Settings['result'];
  thousands?: boolean;
  units?: boolean;
  fontScale?: number;
  reducedMotion?: boolean;
  workspace?: string;
  lastSession?: string;
  complex?: boolean;
  keypad?: string;
}

// ------------------------------------------------------------------------------------------------------------------ forms
export interface FormColumn { key: string; label: string; placeholder?: string }
export interface FormField {
  kind: 'text' | 'textarea' | 'number' | 'quantity' | 'select' | 'bool' | 'list' | 'pairs' | 'table';
  key: string;
  label: string;
  unit?: string;
  placeholder?: string;
  hint?: string;
  required?: boolean;
  advanced?: boolean;
  mono?: boolean;
  rows?: number;
  lines?: boolean;
  default?: unknown;
  options?: Array<{ value: string; label: string }>;
  columns?: FormColumn[];
  shape?: 'array' | 'object';
  when?: Record<string, string[]>;
}
export interface FormOp {
  id: string;
  title: string;
  summary: string;
  fields: FormField[];
  example: Record<string, unknown>;
  view?: string;
  chart?: string;
}
export interface FormDomain { title: string; ops: FormOp[] }
export type FormCatalogue = Record<string, FormDomain>;

// ------------------------------------------------------------------------------------------------------------------ graphing
export type Pt = [number, number];
export interface View { xmin: number; xmax: number; ymin: number; ymax: number }

export interface LayerSpec {
  id: string;
  type: string;                  // auto | function | parametric | polar | inequality | implicit | sequence | vectorfield | scatter | histogram
  expr?: string;
  x?: string | string[];
  y?: string | string[];
  r?: string;
  fx?: string;
  fy?: string;
  tmin?: string;
  tmax?: string;
  nmin?: string;
  nmax?: string;
  values?: string[];
  bins?: string;
  fit?: string;
  label?: string;
  visible?: boolean;
  color?: string;
}

export interface LayerResult {
  id: string;
  ok: boolean;
  type?: string;
  label?: string;
  error?: ApiErrorBody;
  segments?: Pt[][];
  polylines?: Pt[][];
  asymptotes?: number[];
  yIntercept?: number | null;
  x?: number;
  region?: { runs: number[][]; cell: [number, number] };
  boundary?: Pt[][];
  strict?: boolean;
  points?: Pt[];
  arrows?: number[][];
  bars?: Array<{ x0: number; x1: number; count: number; density: number }>;
  n?: number;
  fit?: { model: string; equation: string; params: Record<string, number>; r2: number; rmse: number; n: number; segments: Pt[][]; method: string };
}

export interface GraphResult { ok: boolean; view: View; layers: LayerResult[]; angle?: string; numeric?: string; error?: ApiErrorBody }
