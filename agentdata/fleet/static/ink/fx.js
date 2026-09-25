/* Ink effects (#370, epic #293): the seam every one-shot effect hangs on, and the cues (#372).
   docs/desk-ink.md §Effects, §The files and §Budgets.

   Its own module, fetched by the layer only for a table that has effects (a skin that exports
   `cues`, or `options.fx`), so the four modules every drawing desk loads stay inside `INK_BUDGET`
   and effect code is held to `FX_BUDGET` (§Budgets). It imports nothing: the layer hands it
   three.js, the scene and the draw order (`attach(layer, spec)`), and it writes nothing to the
   page. It reads the page: the rows' matches, their boxes, and the records of `<body>`'s class.

   DRAW ORDER. The group sits at `api.order.fx` (-5). three.js r160 sorts first by the innermost
   Group's `renderOrder`, and the pane groups `framePanes` makes keep 0, so an effect draws over
   the back pass (ground, paper) and under every pane's frame and every mark, whatever
   `api.order.frame` says. Within one list three.js draws every opaque object before any
   transparent one, so an effect's materials are `transparent: true`, like the skins' own. An
   effect that must sit on a pane's frame goes into that pane's frame group.

   THE CUES (#372, §Effects). A skin's `cues` rows, `{selector, on: "arrive" | "leave", cue}`, are
   matched with the table, and its `cue(ctx, name, el, box, how)` plays each new one. A cue is
   news, never history: nothing on a table's first match, while `body.is-stale` or
   `body.is-replaying` (#371) is set or on the first match after, for an arrival in a pane that
   only just arrived, without a skin, or under reduced motion.

   AT REST. `match` (after the table is matched), `measure` (after every mark is measured) and
   `deliver` (in each frame, after `prepare`) run only on frames the layer draws. `deliver` asks
   for the next while a cue waits or a child of the group lives: at rest, neither. */

let live = 0;

/* How many layers have effects attached: 0 after every detach path (a table without `fx`,
   `Ink.setSkin(null)`, `Ink.off()`). */
export function attached() {
  return live;
}

const LANE = ".tile[data-repo]";        // a pane, as the layer names one
const NAME = /^[a-z][a-z0-9-]{0,23}$/;
const QUIET = /(^|\s)is-(stale|replaying)(\s|$)/;
/* The caps: rows in a table, cues waiting, cues delivered a frame. */
const ROWS = 16, WAIT = 16, PER_FRAME = 4;
/* The net: a child of the group older than this is taken out. In frames, like every duration on
   the canvas (docs/desk-motion.md): 1.5 s at 60 Hz. No shipped skin relies on it. */
const REAP = 90;
/* What the layer observes for any table (layer.js `setTable`), besides what its mark rows name. */
const OBSERVED = ["class", "id", "hidden", "data-tier", "data-skin", "data-skin-variant", "open"];

const attrs = sel => Array.from(String(sel || "").matchAll(/\[\s*([\w-]+)/g), m => m[1]);

function boxOf(el) {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}

function all(sel) {
  try { return document.querySelectorAll(sel); } catch (e) { return []; }
}

/* Why a cue table cannot be played, naming the row, or "" when it can. */
function refusal(cues, layer) {
  if (!Array.isArray(cues)) return "cues: an array of rows";
  if (cues.length > ROWS) return "cues: at most " + ROWS + " rows, not " + cues.length;
  const seen = new Set(OBSERVED);
  for (const row of layer.rows) for (const sel of [row.selector, row.to, row.grow]) attrs(sel).forEach(a => seen.add(a));
  for (let i = 0; i < cues.length; i++) {
    const c = cues[i] || {}, where = "cue " + i + (c.selector ? " (" + c.selector + ")" : "") + ": ";
    if (typeof c.selector !== "string" || !c.selector.trim()) return where + "no selector";
    try { document.querySelector(c.selector); } catch (e) { return where + "not a selector the page can match"; }
    if (c.on !== "arrive" && c.on !== "leave") return where + "`on` is \"arrive\" or \"leave\", not " + JSON.stringify(c.on);
    if (typeof c.cue !== "string" || !NAME.test(c.cue)) return where + "`cue` " + JSON.stringify(c.cue) + " is not a name like " + NAME;
    const odd = attrs(c.selector).find(a => !seen.has(a));
    if (odd) return where + "[" + odd + "] is not an attribute the layer observes (" + Array.from(seen).join(", ") + ")";
  }
  return "";
}

export function attach(layer, spec) {
  const L = layer, body = document.body, group = new L.THREE.Group();
  group.renderOrder = L.api.order.fx;
  L.scene.add(group);
  live += 1;
  const cues = spec && spec.cues != null ? spec.cues : [];
  // A lazily fetched module cannot throw from `Ink.setSkin`: a bad row refuses the whole table,
  // and the marks draw on.
  const refused = refusal(cues, L) || null;
  if (refused) console.error("ink: " + refused);
  const rows = refused ? [] : cues.map(c => ({ selector: c.selector, on: c.on, cue: c.cue, live: new Map() }));
  const born = new Map();              // a child of the group -> the frame it was first seen in
  let queue = [], known = new Set(), armed = false, gone = false, delivered = 0, dropped = 0, reaped = 0;
  // `match` reads the body once a frame and would miss a class set and cleared between two; the
  // records, read after both toggles, do not. A read, never a write.
  const mo = new MutationObserver(recs => {
    if (QUIET.test(body.className) || recs.some(r => QUIET.test(r.oldValue || ""))) armed = false;
  });
  mo.observe(body, { attributes: true, attributeFilter: ["class"], attributeOldValue: true });
  const push = (...cue) => { if (queue.length < WAIT) queue.push(cue); else dropped += 1; };
  return {
    /* The helpers a skin's hooks reach as `api.fx` (#375, #376 add to it). */
    api: Object.freeze({}),
    /* After the table is matched: what arrived and what left, since the last match. */
    match() {
      const quiet = QUIET.test(body.className);
      const go = armed && !quiet && !!L.skin && !L.instant();
      for (const c of rows) {
        const now = new Set(all(c.selector));
        for (const el of now) {
          if (c.live.has(el)) continue;
          const box = boxOf(el), pane = el.closest(LANE);
          c.live.set(el, { box, zeroAt: 0 });
          if (c.on === "arrive" && go && box.w && (!pane || known.has(pane))) push(c.cue, el, box, "arrived");
        }
        for (const [el, e] of Array.from(c.live)) {
          if (now.has(el)) continue;
          c.live.delete(el);
          // Empty for more than a frame (a grouped pane, `display: none` a while) is empty. A hide
          // still has its box: `frame()` matches before it measures.
          const old = e.zeroAt && L.frames - e.zeroAt > 1;
          if (c.on === "leave" && go && !old && e.box.w && e.box.h) {
            push(c.cue, el, e.box, el.isConnected ? "unmatched" : "removed");
          }
        }
      }
      known = new Set(all(LANE));
      armed = !quiet;
    },
    /* After the marks are measured: each leave row's match keeps its last non-empty box, and an
       empty measure (a pane the ResizeObserver sees just hidden, at 0x0) stamps it. Arrive rows
       are never measured again. */
    measure() {
      for (const c of rows) {
        if (c.on !== "leave") continue;
        for (const [el, e] of c.live) {
          const b = boxOf(el);
          if (b.w && b.h) { e.box = b; e.zeroAt = 0; } else if (!e.zeroAt) e.zeroAt = L.frames || 1;
        }
      }
    },
    /* In each frame: at most `PER_FRAME` cues to the skin, and the net. */
    deliver() {
      for (let n = 0; n < PER_FRAME && queue.length; n++) {
        const [name, el, box, how] = queue.shift();
        L.hook("cue", L.ctx(group), name, el, box, how);
        delivered += 1;
        L.stale = true;
      }
      for (const child of group.children) if (!born.has(child)) born.set(child, L.frames);
      for (const [child, at] of born) {
        if (child.parent !== group) born.delete(child);
        else if (L.frames - at > REAP) {
          const bin = new L.THREE.Group();
          bin.add(child);                // out of the group, and freed as the layer frees a group
          L.empty(bin);
          born.delete(child);
          reaped += 1;
          L.stale = true;
        }
      }
      if (queue.length || group.children.length) L.kick();
    },
    detach() {
      if (gone) return null;
      gone = true;
      mo.disconnect();
      queue = [];
      L.empty(group);
      L.scene.remove(group);
      live -= 1;
      return null;
    },
    inspect() {
      let zero = 0;
      for (const c of rows) if (c.on === "leave") for (const e of c.live.values()) if (e.zeroAt) zero += 1;
      return { loaded: true, rows: rows.length, delivered, queued: queue.length, dropped, armed, reaped, zero,
               children: group.children.length, refused };
    },
  };
}
