// The types `picker.js` used to carry as JSDoc, moved here by #523 (decision 18 on #429): the served
// file keeps only its inline `/** @type {X} */ (expr)` casts. `tsconfig.json` checks this file with
// `picker.js` in one program; a `declare function` here is the signature callers are checked against.
// The reasoning is in `picker.js.md`.

/**
 * One entry of `/api/models` (`models.catalogue`).
 */
type ModelEntry = {
  id: string;
  label?: string;
  group?: string;
  offered?: boolean;
  available?: boolean;
  why_unavailable?: string;
  multiplier?: number;
  efforts?: string[];
};

/**
 * What a press reports. `droppedEffort` is always "" since #493: an effort survives a model switch
 * (decision 15), and a model that lists efforts without it marks that pill ⊘ instead.
 */
type ModelPick = {
  model: string;
  effort: string;
  toolbar: "model" | "effort";
  droppedEffort: string;
};

type ModelPickerOptions = {
  variant?: "full" | "compact";
  label?: string;
  emptyLabel?: string;
  emptyTitle?: string;
  onPick?: (pick: ModelPick) => void;
  onMore?: (anchor: HTMLElement) => void;
};

type ModelPickerState = {
  catalogue: {models?: ModelEntry[], groups?: {key: string, title: string}[], efforts?: string[], meta?: {cli_version?: string}};
  current: {model: string, effort: string};
  inherited?: {model: string, effort: string, source?: string} | null;
  actual?: string;
  quick?: string[];
};

/**
 * One picker, built once and bound once.
 */
declare function createModelPicker(opts: ModelPickerOptions): HTMLElement;

/**
 * Draw `state` into a picker. An equal state makes no mutation.
 */
declare function drawModelPicker(el: HTMLElement, state: ModelPickerState): void;

/**
 * The functions inside `var mpImpl` that carried types, which no global names: their
 * signatures, as the JSDoc said them. Nothing ties the closure's code to this; it is the
 * record of what each takes and gives, checked for being a type.
 */
interface MpImplInner {
  make(tag: any, cls: any, words: any): HTMLElement;
  pickModel(me: any, id: any): ModelPick;
  build(opts: ModelPickerOptions): HTMLElement;
  draw(root: HTMLElement, state: ModelPickerState): void;
}
