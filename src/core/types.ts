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

export type Workspace = 'math' | 'graph' | 'chemistry' | 'biology' | 'measurement' | 'formulas' | 'finance' | 'constants';
export type EntryKind = 'calc' | 'domain' | 'graph' | 'formula' | 'note';

/** The picture a graph entry was drawn as (what the person saw), kept with the entry so an SLDC export shows it. */
export interface GraphFigure {
  mediaType: 'image/png';
  data: string;                                    // base64
  width?: number;
  height?: number;
  transparent: boolean;
  series: Array<{ id: string; color: string | null; dash: 'solid' | 'dash' | 'dot' | 'dashdot' }>;
}

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
  figure?: GraphFigure;
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
  /** The person's own financial assumptions (defaults for the Finance forms; not constants). null removes one. */
  finCurrency?: string | null;
  finPlaces?: number | null;
  finDiscountRate?: number | null;
  finInflation?: number | null;
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

// ------------------------------------------------------------------------------------------------------------------ 3D graphing (scical-graph/1)
export interface Bounds3D { xmin: number; xmax: number; ymin: number; ymax: number; zmin: number; zmax: number }
export interface Axis3D { label: string; unit: string }

/** One layer of a 3D scene as sampled by the service: the definition (what the person wrote) and the sampled geometry (what is drawn). */
export interface Layer3Result {
  id: string;
  ok: boolean;
  type?: string;                                   // surface | psurface | curve3d | points3d | hidden
  label?: string;
  error?: ApiErrorBody;
  definition?: Record<string, unknown>;
  style?: { color?: string; opacity?: number; wireframe?: boolean; mesh?: boolean; colorBy?: string };
  grid?: { nu: number; nv: number };
  vertices?: number[];                             // x, y, z of every vertex, flat
  cells?: number[];                                // four vertex indices per cell: a, b, d, c
  normals?: number[];                              // area-weighted vertex normals, flat
  segments?: number[][];                           // curves: one flat x, y, z list per unbroken piece
  points?: number[];
  stats?: Record<string, number>;
  zrange?: [number, number] | null;
  warnings?: string[];
}

export interface Scene3Result {
  ok: boolean;
  mode: '3d';
  contract: string;
  layers: Layer3Result[];
  bounds: Bounds3D | null;
  angle?: string;
  axes: Record<'x' | 'y' | 'z', Axis3D>;
  numeric?: string;
  triangulation?: string;
  error?: ApiErrorBody;
}
