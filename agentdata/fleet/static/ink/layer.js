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
    this.table = t;
    this.rows = t ? t.marks.map(row => Object.assign({}, row, { live: new Map(), leaving: new Map(), history: new Map() })) : [];
    this.mo.disconnect();
    if (t) {
      // The attributes the table's selectors can depend on, and the few this layer itself reads
      // (a skin changing, a pane hidden). Not `style`: the page writes it on every frame of a drag,
      // and the ResizeObserver already follows what it moves.
      const attrs = new Set(["class", "id", "hidden", "data-tier", "data-skin", "data-skin-variant", "open"]);
      for (const row of t.marks) {
        for (const sel of [row.selector, row.to]) {
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
    }
    // Marks whose paper has gone: an element that left the page takes its marks, struck or not,
    // with it. Nothing is left to draw them on.
    for (const m of Array.from(this.marks)) {
      if (!m.el.isConnected) { this.drop(m); changed = true; }
    }
    return changed;
  }

  mark(o) {
    const m = {
      id: ++this.mid, row: o.row, el: o.el, tool: o.tool, shape: o.shape, strikeOf: o.strikeOf || null,
      lane: o.lane || this.laneOf(o.el), state: "queued", strokes: [], reveal: 0, strike: null,
      seed: seedOf((o.row ? o.row.index : "s") + ":" + this.idOf(o.el) + ":" + (o.strikeOf ? o.strikeOf.id : "")),
      x: 0, y: 0, w: 0, h: 0, visible: false, sig: "", scrollers: null, clip: [-1e5, -1e5, 1e5, 1e5],
      drawOp: null, leaveOp: null, dropped: false,
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
      if (m.shape === "arrow") {
        const t = this.targetOf(m), tr = t && t.getBoundingClientRect();
        shape.to = tr && (tr.width || tr.height) ? { x: tr.left - r.left, y: tr.top - r.top, w: tr.width, h: tr.height } : null;
      }
      let sig = r.width.toFixed(1) + "x" + r.height.toFixed(1);
      if (shape.lines) sig += "|" + shape.lines.map(l => [l.x, l.y, l.w, l.h].map(v => v.toFixed(1)).join(",")).join(";");
      if (shape.to) sig += "|" + [shape.to.x, shape.to.y, shape.to.w, shape.to.h].map(v => v.toFixed(1)).join(",");
      if (m.strikeOf) sig += "|" + m.strikeOf.sig;
      if (sig !== m.sig) {
        m.sig = sig;
        this.build(m, this.pathsOf(m, shape));
      }
      m.clip = this.clipOf(m);
    }
    for (const st of m.strokes) st.place(m.x, m.y, m.clip, m.visible);
    if (m.scuff) m.scuff.place(m.x, m.y, m.clip, m.visible);
    return was !== m.visible + "|" + m.x + "|" + m.y + "|" + m.sig + "|" + m.clip.join(",");
  }

  pathsOf(m, shape) {
    if (m.strikeOf) {
      const target = m.strikeOf;
      if (target.shape === "write") return this.S.SHAPES.strike(shape);
      return this.S.strikeOver(target.strokes.map(s => s.bbox()), target.tool === "highlighter", m.seed);
    }
    return (this.S.SHAPES[m.shape] || (() => []))(shape);
  }

  build(m, paths) {
    while (m.strokes.length > paths.length) m.strokes.pop().dispose(this.scene);
    paths.forEach((p, i) => {
      let st = m.strokes[i];
      if (!st) {
        st = m.strokes[i] = new this.pen.Stroke(m.tool, (m.seed * 31 + i * 7919) % 100003, m.row && m.row.dash);
        if (m.state !== "queued" && m.state !== "drawing") st.done = true;
      }
      st.build(p, this.scene, this.inks[m.tool] || [0.3, 0.3, 0.3], this.mode);
      // A mark already on the paper is redrawn whole at its new size; one not yet begun stays
      // blank until its turn.
      if (m.state === "queued") st.setHead(0);
    });
  }

  syncAll() {
    let changed = false;
    for (const m of this.marks) if (!m.strikeOf && this.sync(m)) changed = true;
    for (const m of this.marks) if (m.strikeOf && this.sync(m)) changed = true;
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
    this.mode = paperCss ? (this.dark ? 2 : 1) : 0;
    if (paperCss) {
      if (!this.paperMesh) {
        this.paperMesh = this.pen.paper(ground, this.dark);
        this.scene.add(this.paperMesh);
      }
      this.paperMesh.material.uniforms.uPaper.value.set(...ground);
      this.paperMesh.material.uniforms.uDark.value = this.dark ? 1 : 0;
    } else if (this.paperMesh) {
      this.scene.remove(this.paperMesh);
      this.paperMesh.material.dispose();
      this.paperMesh = null;
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
      m.state = "drawing";
      this.sync(m);
      if (m.shape === "write") {
        return [this.travel(L, () => this.handPoint(m, false), m.tool), this.writeSeg(L, m),
                once(() => { m.state = "drawn"; })];
      }
      const out = [];
      for (const st of m.strokes) {
        if (st.dead) continue;
        out.push(this.travel(L, () => this.world(m, st.pointAt(st.head)), m.tool), this.drawSeg(L, m, st));
      }
      out.push(once(() => { m.state = "drawn"; }));
      return out;
    }
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
    if (this.drew || busy) this.stale = true;
    if (this.stale) this.render();
    if (busy || lifting || following) this.kick();
    else this.last = 0;
  }

  render() {
    if (this.stopped) return;
    this.prepare();
    this.stale = false;
    const r = this.renderer;
    r.clear();
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
        drawn: m.shape === "write" ? m.reveal : (len ? Math.round(head / len * 1000) / 1000 : 0),
        erased, visible: m.visible,
        box: { x: m.x, y: m.y, w: m.w, h: m.h },
        clip: m.shape === "write" ? m.el.style.getPropertyValue("clip-path") : "",
      });
    }
    marks.sort((a, b) => a.id - b.id);
    return { lanes, marks, frames: this.frames, renders: this.renders, busy: this.busy(),
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
