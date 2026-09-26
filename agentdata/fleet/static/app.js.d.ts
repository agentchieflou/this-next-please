// The types `app.js` used to carry as JSDoc, moved here by #523 (decision 18 on #429): the served
// file keeps only its inline `/** @type {X} */ (expr)` casts. `tsconfig.json` checks this file with
// `app.js` in one program; a `declare function` here is the signature callers are checked against.
// The reasoning is in `app.js.md`.

/**
 * The desk every window on this server agrees on: `desk_state()` in serve.py. It reaches the page
 *  four ways -- the stream's `desk` frame, `/api/fleet`, `/api/desk` and a window write's own answer
 *  -- and all four come in through `acceptDesk`. Optional throughout, because the page also holds
 *  desks that are not the server's: the one it starts with, and the snapshot it draws while the
 *  first answer loads (#219), whose version is taken off so that answer wins.
 */
type DeskRecord = {
  /** 2 since #232 */
  schema?: number;
  /** the project every window's inspector follows (#133) */
  selected?: string;
  /** only ever rises; anything lower is dropped at the door */
  version?: number;
  /** when it last changed, UTC */
  at?: string;
  /** one for the whole desk (#232) */
  arrangement?: Arrangement;
  /** each window's own record, by its `?w=` */
  windows?: Record<string, WindowRecord>;
  /** `ad-fleet probe` asking a window to measure (#247) */
  measure?: Record<string, number>;
};

/**
 * The one arrangement (#232): the same agents in the same order on every screen. `size` is #217's
 *  footprint as an older build wrote it -- a bare number in an older file still -- read as the
 *  starting widths of a window that has none of its own, and never written (#234).
 */
type Arrangement = {
  order?: string[];
  size?: Record<string, {cols: number, rows: number} | number>;
  pinned?: string[];
  hidden?: string[];
};

/**
 * One window's own record: `WINDOW_FIELDS` in serve.py (#172). `focus` and `held` are an older
 *  page's -- the needs-only filter the *needs me* preset replaced (#234) -- which the server keeps
 *  for it; this page neither reads nor writes them.
 */
type WindowRecord = {
  /** the one pane the keys and the composer address (#230) */
  open?: string;
  focus?: boolean;
  /** the last event read, by repository */
  read?: Record<string, number>;
  /** when this window last looked; the away strip reads it */
  seen?: string;
  held?: string[];
  /** the sidebar's open section (#148) */
  section?: string;
  widths?: Widths;
  /** the desk version the widths were written at: a write of widths heard before it is refused (`widths_stale`) */
  widths_at?: number;
};

/**
 * A window's widths (#234): each pane's weight, by repository. 0 is a 48px rail, and a positive
 *  number that pane's share of what the rails leave.
 */
type Widths = Record<string, number>;

/**
 * What this page writes to its own record -- not the whole record. A field one arrangement wrote
 *  and another read was the snap-back (plan-panes ground rule 2), so writing `zoomed`, or the
 *  retired `focus`, is a type error here before it is a bug on the glass.
 */
type WindowWrite = {
  open?: string;
  widths?: Widths;
  read?: Record<string, number>;
  seen?: string;
  section?: string;
};

/**
 * A desk as it arrives: the record, and on an action's answer the envelope every POST carries,
 *  which `acceptDesk` takes off. A refusal is the envelope alone, with the server's words (#163).
 */
type DeskAnswer = DeskRecord & {ok?: boolean, action?: string, error?: string, hint?: string, code?: string};

/**
 * One agent's row, as `/api/fleet` sends it. Typed in the fields the typed part reads -- `project` is
 *  the project the checkout is one of (#175), `why` what it asks when it needs a person, `recent`
 *  the last events of its run -- and open for the rest, which the rest of the page reads as it
 *  always has. Open means a field this list does not name reads as `any`, not as an error: closing
 *  it is the widening's to do, not this slice's.
 */
type Row = { repo?: string, project?: string, path?: string, state?: string, needs_human?: boolean, why?: string, last_said?: string, last_event_age_s?: number, spend?: {total?: number, [field: string]: any}, recent?: Array<{seq: number}>, as_of?: {run: string, n: number}, [field: string]: any };

/**
 * Which of the three widths a pane is drawing (plan-panes §The pane). `setTier` alone writes it.
 */
type Tier = "rail" | "compact" | "full";

/**
 * The widths the tiers change at, in CSS pixels (#235): `fleet.tiers.*` as `settings.tiers()` reads
 *  them, on the theme payload. CI's numbers when the file sets none -- or sets four that do not go
 *  together, when `invalid` says why.
 */
type Tiers = {
  /** the rail's width */
  rail: number;
  /** compact from */
  compact: number;
  /** full from */
  full: number;
  /** how far past compact/full a pane goes before it changes */
  slack: number;
  /** why the file's four were not drawn, or "" */
  invalid: string;
};

/**
 * A pane: one agent in the row, and its entry in `tiles` (#233). `el` is its `.tile`, made once by
 *  `makeTile` and patched after (#215), carrying `data-repo` and `data-tier`; `seq` is the last event
 *  drawn into its transcript, and `row` what it was last drawn from. `restored` marks a pane drawn
 *  from the window's snapshot, whose transcript its first real row brings (#347).
 */
type Pane = {
  el: HTMLElement;
  seq: number;
  row?: Row;
  restored?: boolean;
};

/**
 * @returns the server's answer, or null when the post failed
 */
declare function saveWindow(patch: WindowWrite): Promise<DeskAnswer | null | void>;

/**
 * @returns whether it was taken
 */
declare function acceptDesk(payload: DeskAnswer): boolean;

declare function makeTile(row: Row, index: number): HTMLElement;

declare function paneShows(el: HTMLElement): {wide: boolean, full: boolean};

declare function startFresh(el: HTMLElement, repo: string, button: HTMLElement|null): Promise<any>;

declare function applyWindow(win: WindowRecord): void;

declare function readBefore(shown: Row | undefined, row: Row): boolean;

declare function fillTranscript(entry: Pane, row: Row): void;

declare function patchRow(row: Row, index?: number): Pane | null;

declare function deskAsShown(fallback: DeskRecord | null): DeskRecord | null;

declare function servedTiers(): Tiers | null;

declare function registryChanged(order: string[]): boolean;

declare function mergeDesk(answer: DeskAnswer): void;

declare function choose(name: string): Promise<void>;

declare function getArrangement(): Arrangement;

declare function getEffectiveOrder(): string[];

declare function isHidden(name: string): boolean;

declare function visibleOrder(): string[];

/**
 * @param patch what to post
 * @param apply writes it into the page's arrangement, and answers with what puts the old one back
 * @param what the gesture's name, for its timing mark (#219)
 */
declare function arrangeNow(patch: Arrangement, apply: () => (() => void) | void, what?: string): Promise<DeskAnswer | void>;

declare function setHidden(name: string, hide: boolean): Promise<void | DeskAnswer>;

declare function openName(): string;

declare function markTile(name: string): void;

/**
 * @param skipPost the record already says so: draw it, write nothing
 * @param pressed a hand on its rail, which does ask for it wide
 */
declare function openPane(name: string, skipPost?: boolean, pressed?: boolean): void;

declare function backToPrevious(): boolean;

/**
 * How wide each pane on the glass is, in CSS pixels, by repository: what a gesture measures, and
 *  what `widthsFromPixels` turns back into weights.
 */
type Pixels = Record<string, number>;

/**
 * What a change of widths leaves behind to put back: the widths the window had -- null, none of
 *  its own -- and the pane that had the keys.
 */
type WidthsBefore = {widths: Widths | null, open: string};

declare function ownWidths(value: any): Widths | null;

declare function legacyShare(name: string): number;

declare function paneWeights(): Widths;

declare function wideNames(weights: Widths): string[];

declare function evenShares(weights: Widths, names: string[]): Widths;

declare function paintWidths(weights: Widths): void;

declare function widthsWith(changes: Widths): Widths;

declare function paneEdge(): number;

declare function weightOf(px: number, edge: number): number;

declare function widthsFromPixels(px: Pixels): Widths;

declare function measurePanes(): Pixels;

declare function swappedWidths(was: string, name: string): Widths | null;

declare function saveWidths(patch: WindowWrite, before?: WidthsBefore): Promise<DeskAnswer | null | void>;

/**
 * @param next null: none of its own, as before the gutters
 * @param what the gesture, which the undo names
 * @param open the pane the keys go to, in the same write
 * @param how "layout" for a change that goes through the one door for those (#216)
 */
declare function widthsNow(next: Widths | null, what: string, open?: string, how?: string): Promise<DeskAnswer | null | void>;

declare function offerUndo(before: WidthsBefore, what: string): void;

declare function undoWidths(): boolean;

declare function keyboardPane(): string;

declare function needsPerson(name: string): boolean;

/**
 * @param which "one", "all" or "needs"
 */
declare function applyPreset(which: string): boolean;

/**
 * A gutter under the hand: the two panes beside it, where the drag began (`x`, `a0`), the left
 *  pane's width now (`a`) and as last painted, what the two hold between them (`total`), every
 *  pane's width as the drag began (`px`), and the frame that will paint it.
 */
type GutterHold = {
  left: HTMLElement;
  right: HTMLElement;
  x: number;
  a0: number;
  total: number;
  a: number;
  painted: number;
  px: Pixels;
  /** what a wide pane's padding and borders take (`paneEdge`) */
  edge: number;
  /** the animation frame asked for, or 0 */
  frame: number;
  /** whether the other wide panes were pinned to their pixels yet */
  lifted: boolean;
};

declare function onGlass(el: HTMLElement): boolean;

declare function nextOnGlass(el: HTMLElement): HTMLElement | null;

declare function settlePair(a: number, total: number): number;

declare function snapPair(a: number, total: number): number;

declare function stepPair(a: number, total: number, dir: number): number;

declare function paintHeldWidth(el: HTMLElement, px: number, edge: number): void;

declare function bindGutter(gutter: HTMLElement, el: HTMLElement): void;

declare function evenGutter(el: HTMLElement): boolean;

declare function stepGutter(el: HTMLElement, dir: number): boolean;

declare function openBeside(name: string): void;

declare function ageOf(row: Row): number;

declare function applyTiers(t: Tiers | null | undefined): void;

declare function paneTier(width: number, was?: Tier | ""): Tier;

/**
 * @returns whether it changed
 */
declare function setTier(el: HTMLElement, width: number): boolean;

declare function entryWidth(entry: ResizeObserverEntry): number;

declare function onRowResize(entries: ResizeObserverEntry[]): void;

declare function watchPane(el: HTMLElement): void;

declare function forgetPane(el: HTMLElement): void;

declare function groupRails(shown: string[], open: string[]): void;

declare function groupedAway(name: string): boolean;

declare function railTarget(name: string): string;

declare function railLine(row: Row): string;

declare function drawPaneRail(el: HTMLElement, row: Row): void;

declare function paneStops(): HTMLElement[];

declare function stepRow(dir: number): void;

/**
 * The functions inside `function bindGutter` that carried types, which no global names: their
 * signatures, as the JSDoc said them. Nothing ties the closure's code to this; it is the
 * record of what each takes and gives, checked for being a type.
 */
interface BindGutterInner {
  onMove(ev: PointerEvent): void;
  onUp(ev: PointerEvent): void;
  onKey(ev: KeyboardEvent): void;
}
