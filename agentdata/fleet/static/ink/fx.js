let live = 0;

export function attached() {
  return live;
}

const LANE = ".tile[data-repo]";
const NAME = /^[a-z][a-z0-9-]{0,23}$/;
const QUIET = /(^|\s)is-(stale|replaying)(\s|$)/;
const ROWS = 16, WAIT = 16, PER_FRAME = 4;
const REAP = 90;
const OBSERVED = ["class", "id", "hidden", "data-tier", "data-skin", "data-skin-variant", "open"];
const PANE = "#grid > .tile[data-repo]";
const MOVING = 4;
const X = px => ({ transform: "translateX(" + px + "px)" });
const S = n => ({ transform: "scale(" + n + ")" });
const F = on => ({ filter: on ? "drop-shadow(0 0 4px currentColor)" : "none" });
const GLYPHS = 128, GLYPHS_CAP = 256;
const BLANK = /\s/;

export const KINDS = Object.freeze({
  hit: Object.freeze({ ms: 240, easing: "ease-in-out", add: true, frames: [X(0), X(-3), X(3), X(-2), X(0)] }),
  pop: Object.freeze({ ms: 200, easing: "ease-out", add: true, frames: [S(1), S(1.015), S(1)] }),
  flash: Object.freeze({ ms: 320, easing: "linear", add: false, frames: [F(0), F(1), F(0), F(1), F(0)] }),
});

const attrs = sel => Array.from(String(sel || "").matchAll(/\[\s*([\w-]+)/g), m => m[1]);

function boxOf(el) {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}

/** @param {Element} el @returns {Array<{x: number, y: number, w: number, h: number}>} */
function linesIn(el) {
  const range = document.createRange(), out = [];
  range.selectNodeContents(el);
  for (const b of range.getClientRects()) {
    if (b.width < 2 || b.height < 2) continue;
    const cy = (b.top + b.bottom) / 2;
    const l = out.find(o => Math.abs(o.cy - cy) < Math.max(4, b.height * 0.45));
    if (l) {
      l.x0 = Math.min(l.x0, b.left); l.x1 = Math.max(l.x1, b.right);
      l.y0 = Math.min(l.y0, b.top); l.y1 = Math.max(l.y1, b.bottom); l.cy = (l.y0 + l.y1) / 2;
    } else {
      out.push({ x0: b.left, x1: b.right, y0: b.top, y1: b.bottom, cy });
    }
  }
  return out.sort((a, b) => a.y0 - b.y0)
    .map(o => Object.freeze({ x: o.x0, y: o.y0, w: o.x1 - o.x0, h: o.y1 - o.y0 }));
}

/** @param {Element} el @param {number} max @returns {Array<{x: number, y: number, w: number, h: number, ch: string}>} */
function glyphsIn(el, max) {
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), range = document.createRange(), out = [];
  for (let n = walk.nextNode(); n && out.length < max; n = walk.nextNode()) {
    const text = /** @type {Text} */ (n).data;
    for (let i = 0; i < text.length && out.length < max;) {
      const ch = String.fromCodePoint(/** @type {number} */ (text.codePointAt(i)));
      if (!BLANK.test(ch)) {
        range.setStart(n, i);
        range.setEnd(n, i + ch.length);
        const b = range.getBoundingClientRect();
        out.push(Object.freeze({ x: b.left, y: b.top, w: b.width, h: b.height, ch }));
      }
      i += ch.length;
    }
  }
  return out;
}

function all(sel) {
  try { return document.querySelectorAll(sel); } catch (e) { return []; }
}

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
  const refused = refusal(cues, L) || null;
  if (refused) console.error("ink: " + refused);
  const rows = refused ? [] : cues.map(c => ({ selector: c.selector, on: c.on, cue: c.cue, live: new Map() }));
  const born = new Map();
  let queue = [], known = new Set(), armed = false, gone = false, delivered = 0, dropped = 0, reaped = 0;
  const mo = new MutationObserver(recs => {
    if (QUIET.test(body.className) || recs.some(r => QUIET.test(r.oldValue || ""))) armed = false;
  });
  mo.observe(body, { attributes: true, attributeFilter: ["class"], attributeOldValue: true });
  const push = (...cue) => { if (queue.length < WAIT) queue.push(cue); else dropped += 1; };
  const moving = new Map(), animated = { hit: 0, pop: 0, flash: 0 }, told = new Set();
  let skipped = 0;
  const onFocus = e => { for (const el of Array.from(moving.keys())) if (el.contains(e.target)) still(el); };
  const onReduce = () => { if (L.instant()) stillAll(); };
  const listen = on => {
    const how = on ? "addEventListener" : "removeEventListener";
    document[how]("focusin", onFocus, true);
    if (L.reduce && L.reduce[how]) L.reduce[how]("change", onReduce);
  };
  function still(el) {
    const a = moving.get(el);
    if (!a) return;
    moving.delete(el);
    a.cancel();
    if (!moving.size) listen(false);
    L.onMove();
  }
  function stillAll() {
    for (const el of Array.from(moving.keys())) still(el);
  }
  /** @param {Element} el @param {string} kind @returns {boolean} */
  function animate(el, kind) {
    const k = Object.prototype.hasOwnProperty.call(KINDS, kind) ? KINDS[kind] : null;
    if (!k) {
      if (!told.has(kind)) { told.add(kind); console.error("ink: fx.animate: " + JSON.stringify(kind) + " is not hit, pop or flash"); }
      return false;
    }
    const r = el && el.isConnected && el.matches(PANE) ? el.getBoundingClientRect() : null;
    const sel = window.getSelection();
    if (gone || !r || !r.width || !r.height || L.stopped || !L.skin || L.instant() || document.hidden ||
        body.classList.contains("ink-off") || el.matches(":focus-within") ||
        (sel && !sel.isCollapsed && sel.containsNode(el, true)) || el.getAnimations().length || moving.size >= MOVING) {
      skipped += 1;
      return false;
    }
    const a = el.animate(k.frames, { duration: k.ms, easing: k.easing, fill: "none", composite: k.add ? "add" : "replace" });
    if (!moving.size) listen(true);
    moving.set(el, a);
    animated[kind] += 1;
    a.onfinish = a.oncancel = () => { if (moving.get(el) === a) still(el); };
    L.onMove();
    return true;
  }
  const read = new WeakMap();
  /** @param {Element} el @param {string} what @param {function(Element): Array<Object>} make @returns {Array<Object>} */
  function cached(el, what, make) {
    if (!el || !el.isConnected) return [];
    const r = el.getBoundingClientRect(), key = (el.textContent || "").length + "|" + r.width + "x" + r.height;
    let c = read.get(el);
    if (!c || c.key !== key) read.set(el, c = { key, got: new Map() });
    if (!c.got.has(what)) c.got.set(what, make(el));
    return c.got.get(what).slice();
  }
  /** @param {Element} el */
  const lines = el => cached(el, "lines", linesIn);
  /** @param {Element} el @param {number=} max */
  function glyphs(el, max = GLYPHS) {
    const n = Math.min(GLYPHS_CAP, Math.max(0, Math.floor(Number(max)) || 0));
    return cached(el, "glyphs " + n, e => glyphsIn(e, n));
  }
  const text = !!(spec && spec.use && spec.use.text === true);
  return {
    api: Object.freeze(text ? { animate, lines, glyphs } : { animate }),
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
          const old = e.zeroAt && L.frames - e.zeroAt > 1;
          if (c.on === "leave" && go && !old && e.box.w && e.box.h) {
            push(c.cue, el, e.box, el.isConnected ? "unmatched" : "removed");
          }
        }
      }
      known = new Set(all(LANE));
      armed = !quiet;
    },
    measure() {
      for (const c of rows) {
        if (c.on !== "leave") continue;
        for (const [el, e] of c.live) {
          const b = boxOf(el);
          if (b.w && b.h) { e.box = b; e.zeroAt = 0; } else if (!e.zeroAt) e.zeroAt = L.frames || 1;
        }
      }
    },
    deliver() {
      for (const el of Array.from(moving.keys())) if (!el.isConnected) still(el);
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
          bin.add(child);
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
      stillAll();
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
               children: group.children.length, refused, animating: moving.size, animated: Object.assign({}, animated),
               skipped };
    },
  };
}
