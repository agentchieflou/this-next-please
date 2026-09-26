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

const attrs = sel => Array.from(String(sel || "").matchAll(/\[\s*([\w-]+)/g), m => m[1]);

function boxOf(el) {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
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
  return {
    api: Object.freeze({}),
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
