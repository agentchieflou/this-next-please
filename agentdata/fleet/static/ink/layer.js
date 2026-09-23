/* The ink layer (#248): one canvas behind the page, lanes of drawing, and marks derived from the
   classes the page already sets. `ink.js` starts it once the gate says on and a skin has handed it
   a mark table; `docs/desk-ink.md` is the page it implements.

   THE DOM IS THE TRUTH (plan-ink ground rule 2). Nothing pushes a mark. A skin is a table -- when
   this selector matches, this tool draws this shape -- and the layer watches the page: a
   MutationObserver says *something changed* (and does nothing else, so a gesture's own frame is not
   charged for the ink), and the next animation frame matches every row against the page. A match
   that is new is a mark to draw; a match that has gone is a mark to erase (pencil) or strike
   through (ink). The layer never decides a state and never writes one: its only write to the page
   is the handwriting reveal's `clip-path`, on the element being written, while it is written.

   DRAWN, NEVER FADED (ground rule 1). A mark arrives by being drawn, a stroke at a time at the
   speed of a hand, and leaves by being erased or struck. With reduced motion every mark is drawn at
   once and no hand travels.

   LANES. One queue of drawing per agent's pane (`.tile[data-repo]`) plus one for everything
   outside a pane (the header). Every lane advances on every frame, so two agents draw at once, and
   within a lane one mark is finished before the next is begun, so one agent's marks never
   interleave.

   GEOMETRY. Each mark's strokes are built in its anchor's own coordinates and the mesh is put where
   the anchor is. So a pane that moves -- a gutter drag, a scroll, a reorder -- moves its marks by
   moving meshes, and only an anchor that changes size (or whose text wraps differently) rebuilds
   its strokes. A ResizeObserver on every anchor and every lane's pane redraws inside the frame the
   browser laid out, so the marks follow the gutter without the layer adding a DOM write to the
   drag (plan-panes ground rule 4). */

const PEN = 900;                 // px a second at 1x: the prototype's pen speed
const LANE = ".tile[data-repo]";
const HEADER = "header";
const VENDOR = "/static/vendor/three/three.module.min.js";
const DZ = 1600;                 // the hand's camera distance, in CSS px
const DEG = Math.PI / 180;
const FOLLOW_MS = 400;           // how long a transition is followed: --motion-slow and a margin
const REVEAL_BLEED = 14;         // a written line's ascenders and descenders, uncovered too
/* The palette tokens a skin's hooks are handed, as [r, g, b] (the desk's thirteen, app.css). */
const TOKENS = ["bg", "panel", "text", "line", "select", "muted", "accent", "focus", "running",
                "waiting", "human", "done", "idle"];

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

function seedOf(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0) % 99991;
}

/* The context is asked for before three.js is fetched, the way the probe asks for it: a shell that
   will not give one falls back without spending 163 KB on a library it cannot use. */
function context(canvas) {
  const attrs = { antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: "high-performance" };
  let gl = null, why = "";
  try { gl = canvas.getContext("webgl2", attrs); } catch (e) { why = String((e && e.message) || e); }
  if (!gl) {
    try { gl = canvas.getContext("webgl", attrs); } catch (e) { why = String((e && e.message) || e); }
  }
  if (!gl) throw new Error("no WebGL context" + (why ? ": " + why : ""));
  return gl;
}

export async function start(host) {
  const canvas = document.createElement("canvas");
  canvas.id = "ink";
  canvas.setAttribute("aria-hidden", "true");
  const gl = context(canvas);
  const [THREE, shapes, pen] = await Promise.all([
    import(q(VENDOR)), import(q("/static/ink/shapes.js")), import(q("/static/ink/pen.js"))]);
  const missing = host.shapes.filter(s => !shapes.SHAPES[s]).concat(Object.keys(host.tools).filter(t => !pen.TOOLS[t]));
  if (missing.length) throw new Error("the layer cannot draw " + missing.join(", "));
  return new Layer(THREE, shapes, pen, canvas, gl, host);
}

class Layer {
  constructor(THREE, shapes, pen, canvas, gl, host) {
    this.THREE = THREE;
    this.S = shapes;
    this.host = host;
    this.canvas = canvas;
    this.table = null;
    this.rows = [];
    this.lanes = new Map();
    this.marks = new Set();
    this.clipped = new Set();          // elements whose clip-path this layer wrote
    this.inks = {};                    // tool -> [r, g, b], read from the page at paint time
    this.dark = false;
    this.mode = 0;                     // the highlighter's blend: 0 over nothing, 1 multiply, 2 screen
    this.frames = 0;
    this.renders = 0;
    this.raf = 0;
    this.last = 0;
    this.followUntil = 0;
    this.dirty = { table: false, geom: false, colours: true, size: true };
    this.stale = true;                 // something on the paper changed since it was last drawn
    this.stopped = false;
    this.ids = new WeakMap();
    this.observed = new WeakSet();
    this.nextId = 0;
    this.mid = 0;
    this.reduce = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

    this.renderer = new THREE.WebGLRenderer({ canvas, context: gl, antialias: true, alpha: true, premultipliedAlpha: true });
    this.renderer.autoClear = false;
    this.renderer.setClearColor(0x000000, 0);
    this.shared = { uDpr: { value: 1 }, uViewH: { value: 1 } };
    this.pen = pen.makePen(THREE, this.shared);
    this.scene = new THREE.Scene();
    this.toolScene = new THREE.Scene();
    this.cam = new THREE.OrthographicCamera(0, 1, 0, -1, -2000, 2000);
    this.pcam = new THREE.PerspectiveCamera(30, 1, 5, 6000);
    this.toolScene.add(new THREE.HemisphereLight(0xffffff, 0x9098a8, 1.5));
    const sun = new THREE.DirectionalLight(0xffffff, 2.4);
    sun.position.set(-0.45, 0.55, 0.9);
    this.toolScene.add(sun);
    this.paperMesh = null;
    this.parse = document.createElement("canvas").getContext("2d");
    // A skin's materials (docs/desk-ink.md §Writing a skin): its ground and paper live in `back`,
    // drawn first, and -- when the skin asks to sample it -- into a texture its frames can read.
    this.back = new THREE.Scene();
    this.skin = null;
    this.groundRT = null;
    this.groundSize = new THREE.Vector2(1, 1);
    this.backStale = true;
    this.tokens = {};
    this.api = this.makeApi();

    // On the page only while a table is set (`setTable`).
    this.onLost = () => this.host.off("the WebGL context was lost");
    canvas.addEventListener("webglcontextlost", this.onLost);

    this.mo = new MutationObserver(() => { this.dirty.table = true; this.dirty.geom = true; this.kick(); });
    this.themeMo = new MutationObserver(() => { this.dirty.colours = true; this.dirty.table = true; this.kick(); });
    this.themeMo.observe(document.documentElement, { attributes: true, attributeFilter: ["style", "data-theme", "class"] });
    this.ro = new ResizeObserver(() => { if (this.stopped) return; this.dirty.geom = true; this.now(); });
    this.onResize = () => { this.dirty.size = true; this.dirty.geom = true; this.kick(); };
    this.onScroll = () => { this.dirty.geom = true; this.kick(); };
    this.onMove = () => { this.followUntil = performance.now() + FOLLOW_MS; this.dirty.geom = true; this.kick(); };
    this.onScheme = () => { this.dirty.colours = true; this.kick(); };
    window.addEventListener("resize", this.onResize);
    document.addEventListener("scroll", this.onScroll, { capture: true, passive: true });
    for (const e of ["transitionrun", "transitionend", "transitioncancel", "animationstart", "animationend"]) {
      document.addEventListener(e, this.onMove, true);
    }
    this.scheme = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    if (this.scheme && this.scheme.addEventListener) this.scheme.addEventListener("change", this.onScheme);
    this.onFonts = () => { this.dirty.geom = true; this.kick(); };
    if (document.fonts && document.fonts.addEventListener) document.fonts.addEventListener("loadingdone", this.onFonts);
  }

  // ------------------------------------------------------------------------ the table

  setTable(t) {
    this.clear();
    this.unskin();
    this.table = t;
    if (t && t.hooks) this.enskin(t.hooks);
    this.rows = t ? t.marks.map(row => Object.assign({}, row, { live: new Map(), leaving: new Map(), history: new Map() })) : [];
    this.mo.disconnect();
    if (t) {
      // The attributes the table's selectors can depend on, and the few this layer itself reads
      // (a skin changing, a pane hidden). Not `style`: the page writes it on every frame of a drag,
      // and the ResizeObserver already follows what it moves.
      const attrs = new Set(["class", "id", "hidden", "data-tier", "data-skin", "data-skin-variant", "open"]);
      for (const row of t.marks) {
        for (const sel of [row.selector, row.to, row.grow]) {
          for (const m of String(sel || "").matchAll(/\[\s*([\w-]+)/g)) attrs.add(m[1]);
        }
      }
      this.mo.observe(document.body, { subtree: true, childList: true, characterData: true,
                                       attributes: true, attributeFilter: Array.from(attrs) });
      if (!this.canvas.isConnected) document.body.appendChild(this.canvas);
      this.dirty.table = this.dirty.geom = this.dirty.colours = true;
      if (this.raf) cancelAnimationFrame(this.raf);
      this.frame(performance.now());
    } else {
      // No table, no canvas: the page is as it was before a skin drew on it. The context lives on
      // for the next table.
      this.render();
      this.canvas.remove();
    }
  }

  /* Every mark off the paper at once, with no animation: the table changed, or the layer is going.
     The page is left as it was found -- every clip this layer wrote is taken back. */
  clear() {
    for (const m of Array.from(this.marks)) this.drop(m);
    for (const L of this.lanes.values()) {
      L.q = [];
      L.segs = [];
      if (L.hand) L.hand.hide();
    }
    for (const el of this.clipped) {
      if (!el.style) continue;
      el.style.removeProperty("clip-path");
      if (!el.getAttribute("style")) el.removeAttribute("style");
    }
    this.clipped.clear();
    this.ro.disconnect();
    this.observed = new WeakSet();
  }

  // -------------------------------------------------------------- a skin's materials

  /* What a skin's hooks are handed besides three.js, the scene and the camera: the viewport, the
     page's state, and a way to ask for a frame. Read at call time, never kept stale. */
  makeApi() {
    const self = this;
    return Object.freeze({
      get viewport() { return { w: self.W || window.innerWidth, h: self.H || window.innerHeight, dpr: self.dpr || 1 }; },
      get reduced() { return self.instant(); },
      get dark() { return self.dark; },
      get renderer() { return self.renderer; },
      /* The ground and paper as a texture, for a skin that exports `sampleGround = true` -- a
         frosted pane reads it at `gl_FragCoord.xy / groundSize`. Null otherwise. */
      get groundTexture() { return self.groundRT ? self.groundRT.texture : null; },
      get groundSize() { return self.groundSize; },
      /* Where a skin's pieces go in the draw order: under every mark. */
      order: Object.freeze({ ground: -30, paper: -20, frame: -10 }),
      /* The panes, where they are now: `{el, repo, box: {x, y, w, h}}` in viewport CSS px. */
      panes() {
        return Array.from(document.querySelectorAll(LANE)).map(el => {
          const r = el.getBoundingClientRect();
          return { el, repo: el.dataset.repo, box: { x: r.left, y: r.top, w: r.width, h: r.height } };
        });
      },
      /* Draw another frame: a hook changed something outside a call the layer made. */
      request() { self.stale = true; self.backStale = true; self.kick(); },
    });
  }

  ctx(scene) {
    return { THREE: this.THREE, scene, camera: this.cam, tokens: this.tokens, api: this.api };
  }

  /* A skin's hook, called so that its mistake is the skin's: said once, where a skin author
     looks, and the desk carries on drawing its marks. */
  hook(name, ...args) {
    const s = this.skin;
    if (!s || typeof s.hooks[name] !== "function") return undefined;
    try {
      return s.hooks[name](...args);
    } catch (e) {
      if (!s.err[name]) console.error("ink: the skin's " + name + "() threw: " + String((e && e.stack) || e));
      s.err[name] = true;
      return undefined;
    }
  }

  enskin(hooks) {
    const T = this.THREE;
    const group = order => { const g = new T.Group(); g.renderOrder = order; return g; };
    this.skin = { hooks, ground: group(this.api.order.ground), paper: group(this.api.order.paper),
                  frames: new Map(), framesRoot: group(this.api.order.frame), err: {}, dirty: true };
    this.back.add(this.skin.ground, this.skin.paper);
    this.scene.add(this.skin.framesRoot);
    if (hooks.sampleGround) {
      this.groundRT = new T.WebGLRenderTarget(1, 1, { depthBuffer: false, stencilBuffer: false });
      this.dirty.size = true;
      this.W = 0;                      // so `resize` sizes the texture
    }
    this.dirty.colours = true;
  }

  unskin() {
    const s = this.skin;
    if (!s) return;
    this.hook("dispose", this.ctx(null));
    this.empty(s.ground);
    this.empty(s.paper);
    for (const f of s.frames.values()) this.empty(f.group);
    this.empty(s.framesRoot);
    this.back.remove(s.ground, s.paper);
    this.scene.remove(s.framesRoot);
    if (this.groundRT) { this.groundRT.dispose(); this.groundRT = null; }
    this.skin = null;
    this.stale = this.backStale = true;
  }

  /* Everything in a group taken out and its GPU memory freed: a hook's call begins empty. */
  empty(g) {
    for (const c of g.children.slice()) {
      c.traverse(o => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) [].concat(o.material).forEach(mt => mt.dispose());
      });
      g.remove(c);
    }
  }

  /* The panes a skin frames: one group each, at the pane's top-left, made when the pane appears
     and gone with it. Matched with the table, on the frame after the page changed. */
  framePanes() {
    const s = this.skin;
    if (!s || typeof s.hooks.frame !== "function") return false;
    let changed = false;
    const now = new Set(document.querySelectorAll(LANE));
    for (const el of now) {
      if (s.frames.has(el)) continue;
      const group = new this.THREE.Group();
      s.framesRoot.add(group);
      s.frames.set(el, { el, group, sig: "" });
      this.watch(el);
      changed = true;
    }
    for (const [el, f] of Array.from(s.frames)) {
      if (now.has(el) && el.isConnected) continue;
      this.empty(f.group);
      s.framesRoot.remove(f.group);
      s.frames.delete(el);
      changed = true;
    }
    return changed;
  }

  /* Each pane's frame where the pane is; built again only when its size changed. */
  syncFrames() {
    const s = this.skin;
    if (!s || !s.frames.size) return false;
    let changed = false;
    for (const f of s.frames.values()) {
      const r = f.el.getBoundingClientRect();
      const visible = !!(r.width || r.height);
      if (f.group.visible !== visible) { f.group.visible = visible; changed = true; }
      if (!visible) continue;
      if (f.group.position.x !== r.left || f.group.position.y !== -r.top) {
        f.group.position.set(r.left, -r.top, 0);
        changed = true;
      }
      const sig = r.width.toFixed(1) + "x" + r.height.toFixed(1);
      if (sig !== f.sig) {
        f.sig = sig;
        this.empty(f.group);
        this.hook("frame", this.ctx(f.group), f.el, { x: 0, y: 0, w: r.width, h: r.height });
        changed = true;
      }
    }
    return changed;
  }

  laneOf(el) {
    const pane = el.closest ? el.closest(LANE) : null;
    const key = pane ? "pane:" + pane.dataset.repo : HEADER;
    let L = this.lanes.get(key);
    if (!L) {
      L = { key, root: pane, q: [], segs: [], hand: null };
      this.lanes.set(key, L);
    }
    if (pane && L.root !== pane) L.root = pane;
    if (L.root) this.watch(L.root);
    return L;
  }

  /* Observed once each: observing an element again re-reports its size, which is a redraw for
     nothing. */
  watch(el) {
    if (this.observed.has(el)) return;
    this.observed.add(el);
    this.ro.observe(el);
  }

  idOf(el) {
    let id = this.ids.get(el);
    if (!id) { id = ++this.nextId; this.ids.set(el, id); }
    return id;
  }

  /* Match every row against the page: new matches are drawn, lost ones leave. */
  evaluate() {
    let changed = false;
    for (const row of this.rows) {
      let found = [];
      try { found = document.querySelectorAll(row.selector); } catch (e) { found = []; }
      const now = new Set(found);
      for (const el of now) {
        if (row.live.has(el)) continue;
        const leaving = row.leaving.get(el);
        if (leaving && this.unqueue(leaving, leaving.leaveOp)) {
          // Back before the eraser reached it: the mark simply stays.
          leaving.leaveOp = null;
          row.leaving.delete(el);
          row.live.set(el, leaving);
          continue;
        }
        const m = this.mark({ row, el, tool: row.tool, shape: row.shape });
        if (row.rewrite) m.text = el.textContent;
        row.live.set(el, m);
        if (m.shape === "write" && !this.instant()) this.clip(m, 0);
        this.push(m.lane, { t: "draw", m });
        changed = true;
      }
      for (const [el, m] of Array.from(row.live)) {
        if (now.has(el)) continue;
        row.live.delete(el);
        changed = true;
        if (!el.isConnected || (m.state === "queued" && this.unqueue(m, m.drawOp))) {
          this.drop(m);
          continue;
        }
        row.leaving.set(el, m);
        m.leaveOp = { t: row.leaves === "erased" ? (m.shape === "write" ? "unwrite" : "erase") : "strike", m };
        this.push(m.lane, m.leaveOp);
      }
      if (row.rewrite) for (const m of row.live.values()) if (this.rewrite(m)) changed = true;
    }
    // Marks whose paper has gone: an element that left the page takes its marks, struck or not,
    // with it. Nothing is left to draw them on.
    for (const m of Array.from(this.marks)) {
      if (!m.el.isConnected) { this.drop(m); changed = true; }
    }
    if (this.framePanes()) changed = true;
    return changed;
  }

  mark(o) {
    const m = {
      id: ++this.mid, row: o.row, el: o.el, tool: o.tool, shape: o.shape, strikeOf: o.strikeOf || null,
      lane: o.lane || this.laneOf(o.el), state: "queued", strokes: [], reveal: 0, strike: null,
      seed: seedOf((o.row ? o.row.index : "s") + ":" + this.idOf(o.el) + ":" + (o.strikeOf ? o.strikeOf.id : "")),
      x: 0, y: 0, w: 0, h: 0, visible: false, sig: "", scrollers: null, clip: [-1e5, -1e5, 1e5, 1e5],
      drawOp: null, leaveOp: null, dropped: false, seen: null, grown: 0, text: null, ghost: o.ghost || null,
    };
    this.marks.add(m);
    this.watch(m.el);
    this.sync(m);
    return m;
  }

  push(L, op) {
    if (op.t === "draw") op.m.drawOp = op;
    L.q.push(op);
    this.kick();
  }

  /* Take an op back out of its lane, if the pen has not started it. */
  unqueue(m, op) {
    if (!op || op.started) return false;
    const i = m.lane.q.indexOf(op);
    if (i < 0) return false;
    m.lane.q.splice(i, 1);
    return true;
  }

  drop(m) {
    if (m.dropped) return;
    m.dropped = true;
    this.stale = true;
    for (const st of m.strokes) st.dispose(this.scene);
    m.strokes = [];
    if (m.scuff) { m.scuff.dispose(this.scene); m.scuff = null; }
    if (m.ghost && m.ghost.mesh) {
      this.scene.remove(m.ghost.mesh);
      m.ghost.mesh.geometry.dispose();
      m.ghost.mesh.material.map.dispose();
      m.ghost.mesh.material.dispose();
      m.ghost.mesh = null;
    }
    if (m.strike) this.drop(m.strike);
    m.lane.q = m.lane.q.filter(op => op.m !== m);
    this.marks.delete(m);
    if (m.row) {
      if (m.row.live.get(m.el) === m) m.row.live.delete(m.el);
      if (m.row.leaving.get(m.el) === m) m.row.leaving.delete(m.el);
      if (m.row.history.get(m.el) === m) m.row.history.delete(m.el);
    }
    if (m.shape === "write" && !m.el.isConnected) this.clipped.delete(m.el);
  }

  // --------------------------------------------------------------------- the geometry

  /* The rectangle an anchor can be seen in: the viewport, cut down by every ancestor that scrolls.
     The ancestors are found once per mark; their boxes are read every time. */
  clipOf(m) {
    if (!m.scrollers) {
      m.scrollers = [];
      for (let a = m.el.parentElement; a && a !== document.body; a = a.parentElement) {
        const cs = getComputedStyle(a);
        if (/(auto|scroll)/.test(cs.overflowX + " " + cs.overflowY)) m.scrollers.push(a);
      }
    }
    let x0 = 0, y0 = 0, x1 = window.innerWidth, y1 = window.innerHeight;
    for (const a of m.scrollers) {
      const r = a.getBoundingClientRect();
      x0 = Math.max(x0, r.left); y0 = Math.max(y0, r.top); x1 = Math.min(x1, r.right); y1 = Math.min(y1, r.bottom);
    }
    return [x0, y0, x1, y1];
  }

  /* The text's line boxes, in the anchor's coordinates: one per line it wraps to. */
  linesOf(el, r) {
    const range = document.createRange();
    range.selectNodeContents(el);
    const out = [];
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
      .map(o => ({ x: o.x0 - r.left, y: o.y0 - r.top, w: o.x1 - o.x0, h: o.y1 - o.y0 }));
  }

  targetOf(m) {
    const sel = m.row && m.row.to;
    if (!sel) return null;
    let t = null;
    try {
      t = (m.lane.root && m.lane.root.querySelector(sel)) || document.querySelector(sel);
    } catch (e) {
      t = null;
    }
    return t;
  }

  /* Where the mark is now, and -- when its size or text changed -- its strokes built again.
     Answers whether anything about it changed, so a frame with nothing new draws nothing. */
  sync(m) {
    if (m.dropped) return false;
    const r = m.el.isConnected ? m.el.getBoundingClientRect() : null;
    const was = m.visible + "|" + m.x + "|" + m.y + "|" + m.sig + "|" + m.clip.join(",");
    m.visible = !!(r && (r.width || r.height));
    if (m.visible) {
      m.x = r.left; m.y = r.top; m.w = r.width; m.h = r.height;
      const shape = { box: { x: 0, y: 0, w: r.width, h: r.height }, pad: m.row ? m.row.pad : 0, seed: m.seed };
      if (m.shape === "lines") shape.lines = this.linesOf(m.el, r);
      if (m.row && m.row.grow) shape.grow = this.growth(m) * m.row.step;
      if (m.row && (m.row.grow || m.row.tip)) {
        const pr = m.lane.root ? m.lane.root.getBoundingClientRect() : null;
        shape.limit = (pr ? pr.right : window.innerWidth) - r.left - 14;
        // The pen's tip sits at the end while the mark is on the paper; a mark that is leaving has
        // had its pen lifted, and is struck or erased without it.
        shape.tip = m.row.tip && m.state !== "leaving" && m.state !== "struck";
      }
      if (m.shape === "arrow") {
        const t = this.targetOf(m), tr = t && t.getBoundingClientRect();
        shape.to = tr && (tr.width || tr.height) ? { x: tr.left - r.left, y: tr.top - r.top, w: tr.width, h: tr.height } : null;
      }
      let sig = r.width.toFixed(1) + "x" + r.height.toFixed(1);
      if (shape.lines) sig += "|" + shape.lines.map(l => [l.x, l.y, l.w, l.h].map(v => v.toFixed(1)).join(",")).join(";");
      if (shape.to) sig += "|" + [shape.to.x, shape.to.y, shape.to.w, shape.to.h].map(v => v.toFixed(1)).join(",");
      if (m.strikeOf) sig += "|" + m.strikeOf.sig;
      if (shape.limit !== undefined) sig += "|" + Math.round(shape.grow || 0) + "," + Math.round(shape.limit) + (shape.tip ? "t" : "");
      // A ruled mark sits on the viewport's grid, so where the anchor is against the grid is part
      // of its shape: a move by a whole square moves the mesh, anything else rules it again.
      const g = m.row && !m.strikeOf ? m.row.snap : 0;
      if (g) {
        shape.snap = { g, at: { x: r.left, y: r.top } };
        sig += "|" + (((r.left % g) + g) % g).toFixed(1) + "," + (((r.top % g) + g) % g).toFixed(1);
      }
      if (sig !== m.sig) {
        m.sig = sig;
        this.build(m, this.pathsOf(m, shape));
      }
      m.clip = this.clipOf(m);
    }
    for (const st of m.strokes) st.place(m.x, m.y, m.clip, m.visible);
    if (m.scuff) m.scuff.place(m.x, m.y, m.clip, m.visible);
    if (m.ghost && m.ghost.mesh) {
      const g = m.ghost;
      g.mesh.position.set(m.x + g.box.x + g.box.w / 2, -(m.y + g.box.y + g.box.h / 2), 0);
      g.mesh.visible = m.visible;
    }
    return was !== m.visible + "|" + m.x + "|" + m.y + "|" + m.sig + "|" + m.clip.join(",");
  }

  pathsOf(m, shape) {
    if (m.strikeOf) {
      const target = m.strikeOf;
      if (target.ghost) return this.S.SHAPES.strike({ box: target.ghost.box, seed: m.seed });
      if (target.shape === "write") return this.S.SHAPES.strike(shape);
      return this.S.strikeOver(target.strokes.map(s => s.bbox()), target.tool === "highlighter", m.seed);
    }
    const paths = (this.S.SHAPES[m.shape] || (() => []))(shape);
    return shape.snap ? this.S.snap(paths, m.shape, shape.box, shape.snap.at, shape.snap.g) : paths;
  }

  build(m, paths) {
    // A growing line keeps what the pen has drawn, in px rather than as a fraction of a length that
    // has changed, and the pen goes back to draw on from there (#249).
    // A mark whose match has gone is leaving: it is struck or erased at the length it had, and grows
    // no more -- the refresh that takes its class away often brings the line that would grow it.
    const grows = !!(m.row && m.row.grow) && !m.leaveOp && (m.state === "drawn" || m.state === "drawing");
    const had = grows ? m.strokes.map(st => ({ head: st.head, len: st.len, sig: st.sig })) : null;
    while (m.strokes.length > paths.length) m.strokes.pop().dispose(this.scene);
    paths.forEach((p, i) => {
      let st = m.strokes[i];
      if (!st) {
        const tune = this.table && this.table.tools ? this.table.tools[m.tool] : null;
        st = m.strokes[i] = new this.pen.Stroke(m.tool, (m.seed * 31 + i * 7919) % 100003, m.row && m.row.dash, tune);
        if (m.state !== "queued" && m.state !== "drawing") st.done = true;
      }
      st.build(p, this.scene, this.inks[m.tool] || [0.3, 0.3, 0.3], this.mode);
      // A mark already on the paper is redrawn whole at its new size; one not yet begun stays
      // blank until its turn.
      if (m.state === "queued") st.setHead(0);
    });
    if (!grows) return;
    let more = false;
    m.strokes.forEach((st, i) => {
      const was = had[i];
      if (st.dead || (was && was.sig === st.sig)) return;
      // Longer than it was: what was drawn stays drawn, the rest is the pen's to draw. A stroke that
      // is new or moved (the tip, at the new end) is drawn again from its start.
      const keep = was && st.len > was.len ? Math.min(was.head, st.len) : (i === 0 ? st.len : 0);
      if (keep < st.len - 0.01) {
        st.setHead(keep);
        st.setDone(false);
        more = true;
      }
    });
    // Drawn, or still drawing a stroke the pen has already left: the pen comes back for the rest.
    if (more) this.push(m.lane, { t: "draw", m });
  }

  /* How many of the row's `grow` matches have arrived in this mark's pane since it was made (#249).
     Counted once each, as they arrive, so a list that drops its oldest line as it takes a new one
     still counts the new one. The ones already there when the mark was made are its start. */
  growth(m) {
    const root = m.lane.root || document;
    let found = [];
    try { found = root.querySelectorAll(m.row.grow); } catch (e) { found = []; }
    if (!m.seen) {
      m.seen = new WeakSet(found);
      return 0;
    }
    for (const el of found) {
      if (m.seen.has(el)) continue;
      m.seen.add(el);
      m.grown += 1;
    }
    return m.grown;
  }

  /* A written word whose text changed after it was written (#249, the header's count): what it said
     is kept on the paper beside it, as it looked, and struck through in pen; the new text is written
     again by the reveal. One struck word is kept per row and element, like every struck mark. */
  rewrite(m) {
    const now = m.el.textContent;
    if (m.text === null || now === m.text) return false;
    const was = m.text;
    m.text = now;
    // Still being written, the reveal is uncovering the new text already.
    if (m.state !== "drawn") return false;
    if (was.trim()) {
      const g = this.mark({ row: m.row, el: m.el, lane: m.lane, tool: "pen", shape: "ghost",
                            ghost: this.ghostOf(m, was) });
      g.state = "drawn";
      this.sync(g);
      g.leaveOp = { t: "strike", m: g };
      this.push(m.lane, g.leaveOp);
    }
    m.reveal = 0;
    if (!this.instant()) this.clip(m, 0);
    m.state = "queued";
    this.push(m.lane, { t: "draw", m });
    return true;
  }

  /* The old text as it looked -- its own font and colour -- drawn once into a texture and set just
     to the left of the element, a little apart, where a hand would have left it. */
  ghostOf(m, text) {
    const T = this.THREE, cs = getComputedStyle(m.el), dpr = this.dpr || 1;
    const font = [cs.fontStyle, cs.fontWeight, cs.fontSize, cs.fontFamily].join(" ");
    const cv = document.createElement("canvas"), cx = cv.getContext("2d");
    cx.font = font;
    const fs = parseFloat(cs.fontSize) || 14;
    const w = Math.ceil(cx.measureText(text).width) + 4, h = Math.ceil(fs * 1.4);
    cv.width = Math.max(1, Math.round(w * dpr));
    cv.height = Math.max(1, Math.round(h * dpr));
    cx.scale(dpr, dpr);
    cx.font = font;
    cx.fillStyle = cs.color;
    cx.textBaseline = "middle";
    cx.fillText(text, 2, h / 2);
    const tex = new T.CanvasTexture(cv);
    tex.colorSpace = T.SRGBColorSpace;
    const mesh = new T.Mesh(new T.PlaneGeometry(w, h),
                            new T.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false }));
    mesh.renderOrder = 2;
    mesh.frustumCulled = false;
    this.scene.add(mesh);
    const r = m.el.getBoundingClientRect();
    return { text, mesh, box: { x: -w - Math.max(4, fs * 0.35), y: (r.height - h) / 2, w, h } };
  }

  syncAll() {
    let changed = false;
    for (const m of this.marks) if (!m.strikeOf && this.sync(m)) changed = true;
    for (const m of this.marks) if (m.strikeOf && this.sync(m)) changed = true;
    if (this.syncFrames()) changed = true;
    return changed;
  }

  // ----------------------------------------------------------------------- the palette

  rgb(css) {
    const cx = this.parse;
    cx.fillStyle = "#000";
    cx.fillStyle = String(css || "").trim() || "#000";
    const s = cx.fillStyle;
    if (s[0] === "#") {
      const n = parseInt(s.slice(1, 7), 16);
      return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
    }
    const v = (s.match(/[\d.]+/g) || [0, 0, 0]).map(Number);
    return [v[0] / 255, v[1] / 255, v[2] / 255];
  }

  colours() {
    const cs = getComputedStyle(document.body);
    const read = name => cs.getPropertyValue(name).trim();
    for (const tool of Object.keys(this.host.tools)) {
      this.inks[tool] = this.rgb(read("--ink-" + tool) || read(this.host.tools[tool]) || "#555");
    }
    this.inks.eraser = this.inks.pencil;
    const t = this.table;
    const paperCss = t && t.paper ? (t.paper.startsWith("--") ? read(t.paper) : t.paper) : "";
    const ground = this.rgb(paperCss || read("--bg") || cs.backgroundColor);
    this.dark = 0.2126 * ground[0] + 0.7152 * ground[1] + 0.0722 * ground[2] < 0.4;
    // The palette as a skin's hooks read it: every token as [r, g, b] in 0-1, the inks, and the
    // raw custom property by name for anything else.
    const tokens = { inks: this.inks, dark: this.dark, css: name => read(name) };
    for (const name of TOKENS) tokens[name] = this.rgb(read("--" + name) || "#888");
    this.tokens = tokens;
    // Something opaque under the marks -- a paper, the skin's or the table's -- and the
    // highlighter multiplies into it (screens onto it when dark); over nothing it is a swipe.
    const papered = !!(paperCss || (this.skin && (this.skin.hooks.paper || this.skin.hooks.ground)));
    this.mode = papered ? (this.dark ? 2 : 1) : 0;
    const flat = paperCss && !(this.skin && this.skin.hooks.paper);
    if (flat) {
      if (!this.paperMesh) {
        this.paperMesh = this.pen.paper(ground, this.dark);
        this.back.add(this.paperMesh);
      }
      this.paperMesh.material.uniforms.uPaper.value.set(...ground);
      this.paperMesh.material.uniforms.uDark.value = this.dark ? 1 : 0;
    } else if (this.paperMesh) {
      this.back.remove(this.paperMesh);
      this.paperMesh.material.dispose();
      this.paperMesh = null;
    }
    this.backStale = true;
    if (this.skin) {
      this.skin.dirty = true;
      for (const f of this.skin.frames.values()) f.sig = "";
    }
    for (const m of this.marks) {
      for (const st of m.strokes) st.colour(this.inks[st.tool] || this.inks[m.tool], this.mode);
      if (m.scuff) m.scuff.colour(this.inks.eraser, this.mode);
    }
    for (const L of this.lanes.values()) {
      if (L.hand) { L.hand.dark = this.dark; L.hand.tint(); }
    }
  }

  resize() {
    const W = window.innerWidth || 1, H = window.innerHeight || 1;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (this.W !== W || this.H !== H || this.dpr !== dpr) {
      this.W = W; this.H = H; this.dpr = dpr;
      this.renderer.setPixelRatio(dpr);
      this.renderer.setSize(W, H, false);
      this.shared.uDpr.value = dpr;
      this.shared.uViewH.value = H;
      this.cam.left = 0; this.cam.right = W; this.cam.top = 0; this.cam.bottom = -H;
      this.cam.updateProjectionMatrix();
      this.pcam.aspect = W / H;
      this.pcam.fov = 2 * Math.atan(H / 2 / DZ) / DEG;
      this.pcam.position.set(W / 2, -H / 2, DZ);
      this.pcam.updateProjectionMatrix();
      this.groundSize.set(Math.round(W * dpr), Math.round(H * dpr));
      if (this.groundRT) this.groundRT.setSize(this.groundSize.x, this.groundSize.y);
      this.backStale = true;
      if (this.skin) this.skin.dirty = true;
    }
  }

  // ------------------------------------------------------------------------- the lanes

  instant() {
    return !!(this.reduce && this.reduce.matches);
  }

  handOf(L) {
    if (!L.hand) {
      L.hand = new this.pen.Hand(this.toolScene, this.scene, this.inks);
      L.hand.dark = this.dark;
    }
    return L.hand;
  }

  hands() {
    return this.table && this.table.hand && !this.instant();
  }

  speed() {
    return this.table ? this.table.speed : 1;
  }

  /* A lane runs `dt` seconds of its queue: segments are consumed in order, and a segment that
     finishes early hands what is left of the frame to the next, so a fast hand is not slowed to
     one stroke a frame. */
  run(L, dt) {
    let t = dt;
    for (let guard = 0; guard < 5000; guard++) {
      if (!L.segs.length) {
        if (!L.q.length) return false;
        const op = L.q.shift();
        op.started = true;
        L.segs = this.compile(L, op);
        continue;
      }
      const r = L.segs[0].step(t);
      if (r < 0) return true;
      L.segs.shift();
      t = r;
    }
    return true;
  }

  compile(L, op) {
    const m = op.m;
    if (!m || m.dropped) return [];
    // A mark can leave the page while its op runs; what the op does at its end is then not done.
    const once = fn => ({ step: dt => { if (!m.dropped) fn(); return dt; } });
    if (op.t === "draw") {
      // A draw queued before the mark began to leave (a growing line's rest) is not drawn after it.
      if (m.leaveOp || m.state === "leaving" || m.state === "struck") return [];
      m.state = "drawing";
      this.sync(m);
      if (m.shape === "write") {
        return [this.travel(L, () => this.handPoint(m, false), m.tool), this.writeSeg(L, m),
                once(() => { m.state = "drawn"; })];
      }
      const out = [];
      for (const st of m.strokes) {
        if (st.dead || st.head >= st.len - 0.01) continue;
        out.push(this.travel(L, () => this.world(m, st.pointAt(st.head)), m.tool), this.drawSeg(L, m, st));
      }
      out.push(once(() => { m.state = "drawn"; }));
      return out;
    }
    if (op.t === "erase" || op.t === "unwrite" || op.t === "strike") this.lift(m);
    if (op.t === "erase" || op.t === "unwrite") {
      m.state = "leaving";
      if (op.t === "unwrite") {
        return [this.travel(L, () => this.handPoint(m, true), "eraser"), this.unwriteSeg(L, m),
                once(() => this.drop(m))];
      }
      const out = [];
      for (const st of m.strokes.slice().reverse()) {
        if (st.dead || st.head <= 0) continue;
        out.push(this.travel(L, () => this.world(m, st.pointAt(Math.min(st.head, st.erase))), "eraser"), this.eraseSeg(L, m, st));
      }
      out.push(once(() => this.drop(m)));
      return out;
    }
    if (op.t === "strike") {
      m.state = "leaving";
      const s = this.mark({ el: m.el, lane: L, tool: "pen", shape: "strike", strikeOf: m });
      m.strike = s;
      s.state = "drawing";
      const out = [];
      for (const st of s.strokes) {
        if (st.dead) continue;
        out.push(this.travel(L, () => this.world(s, st.pointAt(st.head)), "pen"), this.drawSeg(L, s, st));
      }
      out.push(once(() => {
        s.state = "drawn";
        m.state = "struck";
        // One struck mark kept per row and element: the history stays visible, and a state that
        // comes and goes all day does not stack a hundred strikes on one name.
        const row = m.row, old = row.history.get(m.el);
        if (row.leaving.get(m.el) === m) row.leaving.delete(m.el);
        row.history.set(m.el, m);
        if (old && old !== m) this.drop(old);
      }));
      return out;
    }
    return [];
  }

  /* A mark that is going stops being worked: its pen-tip dot (#249) is lifted before it is struck
     or erased. */
  lift(m) {
    if (!m.row || !m.row.tip || m.state === "leaving") return;
    m.state = "leaving";
    m.sig = "";
    this.sync(m);
  }

  /* A point of a mark's stroke on the viewport, or null for a mark that is not on the glass -- a
     hidden pane's marks are finished at once, and no hand travels to where it is not. */
  world(m, p) {
    return m.visible ? [m.x + p[0], m.y + p[1]] : null;
  }

  fast(m) {
    return this.instant() || !m.visible;
  }

  handPoint(m, end) {
    if (!m.visible) return null;
    return end ? [m.x + m.w, m.y + m.h * 0.55] : [m.x, m.y + m.h * 0.6];
  }

  travel(L, where, tool) {
    let from = null, to = null, dur = 0, t = 0, swap = false, d = 0;
    return {
      step: dt => {
        if (!this.hands()) return dt;
        const H = this.handOf(L);
        if (!from) {
          to = where();
          if (!to) return dt;
          if (!H.vis || (H.lift >= 0 && H.alpha < 0.15)) { H.appear(tool, to); return dt; }
          H.lift = -1;
          from = H.tip.slice();
          d = Math.hypot(to[0] - from[0], to[1] - from[1]);
          swap = H.cur !== tool;
          if (d < 1.5 && !swap) return dt;
          dur = (swap ? 0.26 : 0.07 + Math.min(0.35, d / 2600)) / Math.sqrt(this.speed());
        }
        t += dt;
        const k = Math.min(1, t / dur), e = k * k * (3 - 2 * k);
        H.tip = [from[0] + (to[0] - from[0]) * e, from[1] + (to[1] - from[1]) * e];
        H.zT = H.z = Math.sin(Math.PI * k) * (Math.min(28, 6 + d * 0.05) + (swap ? 30 : 0));
        if (swap) {
          H.aT = H.alpha = Math.abs(1 - 2 * k);
          if (k >= 0.5 && H.cur !== tool) H.model(tool);
        }
        return k >= 1 ? t - dur : -1;
      },
    };
  }

  drawSeg(L, m, st) {
    return {
      step: dt => {
        if (st.dead || m.dropped) return dt;
        const tgt = st.len;
        if (this.fast(m)) { st.setHead(tgt); st.setDone(true); this.drew = true; return dt; }
        if (st.head >= tgt - 0.01) { st.setDone(true); return dt; }
        const u = st.head / Math.max(1, tgt);
        const prof = tgt < 16 ? 0.7 : 0.42 + 0.9 * Math.pow(Math.sin(Math.PI * clamp(u, 0.02, 0.98)), 0.7);
        const v = PEN * this.speed() * prof, nh = Math.min(tgt, st.head + v * dt), used = (nh - st.head) / v;
        st.setHead(nh);
        this.drew = true;
        if (this.hands()) this.handOf(L).follow(this.world(m, st.pointAt(nh)) || this.handOf(L).tip);
        if (nh >= tgt - 0.01) { st.setDone(true); return Math.max(0, dt - used); }
        return -1;
      },
    };
  }

  eraseSeg(L, m, st) {
    let ph = 0;
    return {
      step: dt => {
        if (st.dead || m.dropped) return dt;
        if (st.erase === Infinity) st.setErase(st.head);
        if (this.fast(m)) { st.setErase(-1e5); this.drew = true; return dt; }
        const v = PEN * this.speed() * 1.7, end = -st.maxHalf, ne = Math.max(end, st.erase - v * dt);
        const used = (st.erase - ne) / v;
        st.setErase(ne);
        this.drew = true;
        ph += dt;
        const p = this.world(m, st.pointAt(Math.max(0, ne)));
        if (p && this.hands()) this.handOf(L).follow([p[0] + Math.sin(ph * 38) * 2.2, p[1] + Math.cos(ph * 38) * 1.4]);
        if (ne <= end) { st.setErase(-1e5); return Math.max(0, dt - used); }
        return -1;
      },
    };
  }

  /* The handwriting reveal: the element's own text uncovered left to right while the pen moves
     along it -- the text is the page's, only its `clip-path` is this layer's, and only until the
     line is written. */
  clip(m, f) {
    const el = m.el;
    let want = "";
    if (f <= 0) want = "inset(0 100% 0 0)";
    else if (f < 1) want = "inset(-" + REVEAL_BLEED + "px " + ((1 - f) * el.offsetWidth).toFixed(1) + "px -" +
                           REVEAL_BLEED + "px -" + REVEAL_BLEED + "px)";
    const have = el.style.getPropertyValue("clip-path");
    if (want) {
      if (have !== want) el.style.setProperty("clip-path", want);
      this.clipped.add(el);
    } else if (this.clipped.has(el)) {
      if (have) el.style.removeProperty("clip-path");
      if (!el.getAttribute("style")) el.removeAttribute("style");
      this.clipped.delete(el);
    }
  }

  writeSeg(L, m) {
    let total = 0, s = 0, fs = 14;
    return {
      step: dt => {
        if (m.dropped) return dt;
        if (!total) {
          if (!m.visible) { m.reveal = 1; this.clip(m, 1); return dt; }
          fs = parseFloat(getComputedStyle(m.el).fontSize) || 14;
          total = Math.max(24, m.w * 3);
          s = m.reveal * total;
        }
        if (this.fast(m)) { m.reveal = 1; this.clip(m, 1); this.drew = true; return dt; }
        const v = PEN * this.speed() * 0.85, need = (total - s) / v;
        if (dt >= need) s = total; else s += v * dt;
        m.reveal = s / total;
        this.clip(m, m.reveal);
        this.drew = true;
        if (this.hands()) {
          this.handOf(L).follow([m.x + m.reveal * m.w, m.y + m.h * 0.6 - fs * (0.1 + 0.2 * Math.sin(s * 0.32))]);
        }
        return s >= total ? dt - need : -1;
      },
    };
  }

  unwriteSeg(L, m) {
    let total = 0, s = 0;
    return {
      step: dt => {
        if (m.dropped) return dt;
        if (!total) {
          total = Math.max(20, m.w * 1.1);
          s = (1 - m.reveal) * total;
          if (m.visible && !m.scuff) {
            m.scuff = new this.pen.Stroke("eraser", m.seed + 101, false);
            const cy = m.h * 0.55;
            m.scuff.build({ pts: [[m.w + 2, cy], [-2, cy + 1]], w: m.h * 0.8, nobow: true }, this.scene,
                          this.inks.eraser || [0.4, 0.4, 0.4], this.mode);
            m.scuff.place(m.x, m.y, m.clip, true);
            m.scuff.setHead(0);
          }
        }
        if (this.fast(m)) {
          m.reveal = 0;
          this.clip(m, 0);
          if (m.scuff) m.scuff.setHead(m.scuff.len);
          this.drew = true;
          return dt;
        }
        const v = PEN * this.speed() * 1.6, need = (total - s) / v;
        if (dt >= need) s = total; else s += v * dt;
        const f = s / total;
        m.reveal = 1 - f;
        this.clip(m, m.reveal);
        if (m.scuff) m.scuff.setHead(f * m.scuff.len);
        this.drew = true;
        if (this.hands()) this.handOf(L).follow([m.x + m.reveal * m.w, m.y + m.h * (0.5 + 0.28 * Math.sin(s * 0.45))]);
        return s >= total ? dt - need : -1;
      },
    };
  }

  busy() {
    for (const L of this.lanes.values()) if (L.segs.length || L.q.length) return true;
    return false;
  }

  // ------------------------------------------------------------------------ the frame

  kick() {
    if (!this.raf && !this.stopped) this.raf = requestAnimationFrame(t => this.frame(t));
  }

  /* Inside the frame the browser just laid out (a ResizeObserver callback): measure and draw now,
     so the marks are where the panes are on the frame that shows the panes. */
  now() {
    // Geometry only. Matching the table can make a mark, and a mark observes its element; an
    // observation begun inside the observer's own callback is a loop the browser reports as an
    // error. The table is matched on the next animation frame instead.
    this.prepare();
    if (this.stale) this.render();
    if (this.busy() || this.dirty.table) this.kick();
  }

  /* Everything a frame needs measured before it is drawn. Anything that moved, was built again or
     changed colour makes the frame stale; a frame that is not stale is not drawn at all. */
  prepare() {
    if (this.dirty.size) { this.dirty.size = false; this.resize(); this.stale = true; }
    if (this.dirty.colours) { this.dirty.colours = false; this.colours(); this.stale = true; }
    if (this.skin && this.skin.dirty) {
      // The ground and the paper, made again from nothing: on the skin's arrival, a resize, or a
      // palette change. Frames are made in `syncFrames`, per pane.
      this.skin.dirty = false;
      this.empty(this.skin.ground);
      this.hook("ground", this.ctx(this.skin.ground));
      this.empty(this.skin.paper);
      this.hook("paper", this.ctx(this.skin.paper));
      this.stale = this.backStale = true;
    }
    if (this.dirty.geom) { this.dirty.geom = false; if (this.syncAll()) this.stale = true; }
  }

  frame(now) {
    this.raf = 0;
    if (this.stopped) return;
    this.frames += 1;
    const dt = this.last ? clamp((now - this.last) / 1000, 0, 0.1) : 1 / 60;
    this.last = now;
    if (this.dirty.table) {
      this.dirty.table = false;
      if (this.evaluate()) { this.dirty.geom = true; this.stale = true; }
    }
    const following = now < this.followUntil;
    if (following) this.dirty.geom = true;
    this.prepare();
    this.drew = false;
    let busy = false;
    for (const L of this.lanes.values()) {
      if (this.run(L, dt)) busy = true;
      const H = L.hand;
      if (H && H.vis) {
        if (!this.hands()) { H.hide(); this.stale = true; }
        else if (!L.segs.length && !L.q.length && H.lift < 0) H.startLift();
      }
    }
    let lifting = false;
    for (const L of this.lanes.values()) {
      if (L.hand && L.hand.vis) {
        L.hand.update(dt, now);
        this.stale = true;
        if (L.hand.vis) lifting = true;
      }
    }
    // A skin's own animation. It asks for the next frame by answering true; under reduced motion
    // it is still called on the frames the layer draws, and is never given a loop of its own.
    let ticking = false;
    if (this.skin && this.skin.hooks.tick) {
      const more = this.hook("tick", this.ctx(null), dt, now);
      this.stale = this.backStale = true;
      ticking = more === true && !this.instant();
    }
    if (this.drew || busy) this.stale = true;
    if (this.stale) this.render();
    if (busy || lifting || following || ticking) this.kick();
    else this.last = 0;
  }

  render() {
    if (this.stopped) return;
    this.prepare();
    this.stale = false;
    const r = this.renderer;
    if (this.groundRT && this.backStale) {
      r.setRenderTarget(this.groundRT);
      r.clear();
      r.render(this.back, this.cam);
      r.setRenderTarget(null);
    }
    this.backStale = false;
    r.clear();
    r.render(this.back, this.cam);
    r.render(this.scene, this.cam);
    let hand = false;
    for (const L of this.lanes.values()) if (L.hand && L.hand.vis) hand = true;
    if (hand) {
      r.clearDepth();
      r.render(this.toolScene, this.pcam);
    }
    this.renders += 1;
  }

  // ---------------------------------------------------------------- what tests can see

  refresh() {
    this.dirty.table = this.dirty.geom = this.dirty.colours = true;
    this.kick();
  }

  inspect() {
    const lanes = {};
    for (const L of this.lanes.values()) {
      lanes[L.key] = { queued: L.q.length, busy: !!(L.segs.length || L.q.length), hand: !!(L.hand && L.hand.vis) };
    }
    const marks = [];
    for (const m of this.marks) {
      const len = m.strokes.reduce((a, s) => a + (s.dead ? 0 : s.len), 0);
      const head = m.strokes.reduce((a, s) => a + (s.dead ? 0 : Math.min(s.head, s.len)), 0);
      const erased = m.strokes.some(s => s.erase !== Infinity);
      marks.push({
        id: m.id, lane: m.lane.key, selector: m.row ? m.row.selector : "", tool: m.tool, shape: m.shape,
        state: m.state, strikeOf: m.strikeOf ? m.strikeOf.id : null, strokes: m.strokes.length,
        len: Math.round(len * 10) / 10,
        drawn: m.shape === "write" ? m.reveal : m.ghost ? 1 : (len ? Math.round(head / len * 1000) / 1000 : 0),
        was: m.ghost ? m.ghost.text : undefined,
        erased, visible: m.visible,
        box: { x: m.x, y: m.y, w: m.w, h: m.h },
        // Each stroke's extent on the viewport, so a test can see where the ink is (#253).
        bounds: m.strokes.filter(st => !st.dead).map(st => st.bbox()).filter(Boolean).map(b =>
          ({ x: m.x + b.x, y: m.y + b.y, r: m.x + b.r, b: m.y + b.b })),
        clip: m.shape === "write" ? m.el.style.getPropertyValue("clip-path") : "",
      });
    }
    marks.sort((a, b) => a.id - b.id);
    const s = this.skin;
    const skin = s ? {
      hooks: ["ground", "paper", "frame", "tick", "dispose"].filter(k => typeof s.hooks[k] === "function"),
      ground: s.ground.children.length, paper: s.paper.children.length,
      frames: Array.from(s.frames.values()).filter(f => f.group.children.length).length,
      sampleGround: !!this.groundRT, errors: Object.keys(s.err),
    } : null;
    return { lanes, marks, skin, frames: this.frames, renders: this.renders, busy: this.busy(),
             hands: this.hands(), reduced: this.instant(), canvas: this.canvas.isConnected,
             webgl2: !!this.renderer.capabilities.isWebGL2, mode: this.mode, dark: this.dark };
  }

  /* How many pixels in a box of the viewport hold ink, read back from a frame drawn for the
     purpose -- the drawing buffer is not kept between frames. */
  sample(box) {
    if (this.stopped) return 0;
    this.render();
    const gl = this.renderer.getContext();
    const dpr = this.dpr || 1, H = this.H || window.innerHeight;
    const x = Math.max(0, Math.floor(box.x * dpr)), w = Math.max(1, Math.ceil(box.w * dpr));
    const h = Math.max(1, Math.ceil(box.h * dpr));
    const y = Math.max(0, Math.floor((H - box.y - box.h) * dpr));
    const px = new Uint8Array(w * h * 4);
    gl.readPixels(x, y, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
    let n = 0;
    const paper = this.paperMesh ? this.paperRgb() : null;
    for (let i = 0; i < px.length; i += 4) {
      if (paper) {
        if (Math.abs(px[i] - paper[0]) + Math.abs(px[i + 1] - paper[1]) + Math.abs(px[i + 2] - paper[2]) > 48) n += 1;
      } else if (px[i + 3] > 8) {
        n += 1;
      }
    }
    return n;
  }

  paperRgb() {
    const v = this.paperMesh.material.uniforms.uPaper.value;
    return [v.x * 255, v.y * 255, v.z * 255];
  }

  stop() {
    if (this.stopped) return;
    this.clear();
    this.unskin();
    this.stopped = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.mo.disconnect();
    this.themeMo.disconnect();
    this.ro.disconnect();
    window.removeEventListener("resize", this.onResize);
    document.removeEventListener("scroll", this.onScroll, { capture: true });
    for (const e of ["transitionrun", "transitionend", "transitioncancel", "animationstart", "animationend"]) {
      document.removeEventListener(e, this.onMove, true);
    }
    if (this.scheme && this.scheme.removeEventListener) this.scheme.removeEventListener("change", this.onScheme);
    if (document.fonts && document.fonts.removeEventListener) document.fonts.removeEventListener("loadingdone", this.onFonts);
    this.canvas.removeEventListener("webglcontextlost", this.onLost);
    try {
      this.renderer.dispose();
      this.renderer.forceContextLoss();
    } catch (e) {
      /* a lost context has nothing left to free */
    }
    this.canvas.remove();
  }
}
