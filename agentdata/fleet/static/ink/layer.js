const PEN = 900;
const LANE = ".tile[data-repo]";
const HEADER = "header";
const VENDOR = "/static/vendor/three/three.module.min.js";
const DZ = 1600;
const DEG = Math.PI / 180;
const FOLLOW_MS = 400;
const REVEAL_BLEED = 14;
const TOKENS = ["bg", "panel", "text", "line", "select", "muted", "accent", "focus", "running",
                "waiting", "human", "done", "idle"];

const PAGE_ROWS = [
  { selector: "[data-ink-series]:not([data-ink-series=''])", tool: "pen", shape: "series" },
  { selector: "[data-ink-series][data-ink-ticks]:not([data-ink-ticks=''])", tool: "red", shape: "ticks" },
];
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

function parseColour(css, THREE) {
  const s = String(css || "").trim().toLowerCase();
  const m = /^rgba?\(([^)]*)\)$/.exec(s);
  if (m) {
    const v = m[1].split(/[\s,/]+/).filter(Boolean);
    const a = v.length > 3 ? parseFloat(v[3]) / (v[3].endsWith("%") ? 100 : 1) : 1;
    return [v[0] / 255, v[1] / 255, v[2] / 255, a].map(x => clamp(Number(x) || 0, 0, 1));
  }
  if (!s || s === "transparent" || !THREE) return [0, 0, 0, s === "transparent" ? 0 : 1];
  const out = { r: 0, g: 0, b: 0 };
  new THREE.Color().setStyle(s, THREE.SRGBColorSpace).getRGB(out, THREE.SRGBColorSpace);
  return [out.r, out.g, out.b, 1];
}

function seedOf(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return (h >>> 0) % 99991;
}

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
    this.clipped = new Set();
    this.inks = {};
    this.dark = false;
    this.mode = 0;
    this.frames = 0;
    this.renders = 0;
    this.handModel = "";
    this.raf = 0;
    this.last = 0;
    this.followUntil = 0;
    this.dirty = { table: false, geom: false, colours: true, size: true };
    this.stale = true;
    this.stopped = false;
    this.fx = null;
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
    this.back = new THREE.Scene();
    this.skin = null;
    this.groundRT = null;
    this.groundSize = new THREE.Vector2(1, 1);
    this.backStale = true;
    this.tokens = {};
    this.api = this.makeApi();
    this.pageRows = PAGE_ROWS.map((row, i) => Object.assign({ index: "page" + i, to: "", pad: 0, dash: false,
                                                               leaves: "erased", page: true }, row,
                                                             { live: new Map(), leaving: new Map(), history: new Map() }));

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

  setTable(t) {
    this.clear(!t);
    this.unskin();
    this.table = t;
    if (t && t.hooks) this.enskin(t.hooks);
    if (t && t.fx) import(q("/static/ink/fx.js")).then(m => {
      if (this.table === t && !this.stopped) { this.fx = m.attach(this, t.fx); this.refresh(); }
    }, e => console.error("ink: fx.js: " + e));
    this.rows = t ? t.marks.map(row => Object.assign({}, row, { live: new Map(), leaving: new Map(), history: new Map() }))
      .concat(t.series ? this.pageRows : []) : [];
    if (t) this.canvas.setAttribute("data-skin", t.name);
    else this.canvas.removeAttribute("data-skin");
    this.mo.disconnect();
    const attrs = new Set(["class", "id", "hidden", "data-tier", "data-skin", "data-skin-variant", "open"]);
    for (const row of this.rows) {
      for (const sel of [row.selector, row.to, row.grow]) {
        for (const m of String(sel || "").matchAll(/\[\s*([\w-]+)/g)) attrs.add(m[1]);
      }
    }
    if (t) {
      this.mo.observe(document.body, { subtree: true, childList: true, characterData: true,
                                       attributes: true, attributeFilter: Array.from(attrs) });
      if (!this.canvas.isConnected) document.body.appendChild(this.canvas);
      this.dirty.table = this.dirty.geom = this.dirty.colours = true;
      if (this.raf) cancelAnimationFrame(this.raf);
      this.frame(performance.now());
    } else {
      this.render();
      this.canvas.remove();
    }
  }

  clear(all = true) {
    for (const m of Array.from(this.marks)) if (all || !this.own(m)) this.drop(m);
    for (const L of this.lanes.values()) {
      if (all || !L.op || !L.op.m || L.op.m.dropped) {
        L.segs = [];
        L.op = null;
      }
      if (all) L.q = [];
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
    for (const m of this.marks) {
      this.watch(m.el);
      if (m.lane.root) this.watch(m.lane.root);
    }
  }

  own(m) {
    return !!(m.row && m.row.page);
  }

  makeApi() {
    const self = this;
    return Object.freeze({
      get viewport() { return { w: self.W || window.innerWidth, h: self.H || window.innerHeight, dpr: self.dpr || 1 }; },
      get reduced() { return self.instant(); },
      get dark() { return self.dark; },
      get renderer() { return self.renderer; },
      get groundTexture() { return self.groundRT ? self.groundRT.texture : null; },
      get groundSize() { return self.groundSize; },
      order: Object.freeze({ ground: -30, paper: -20, frame: -10, fx: -5 }),
      get fx() { return self.fx && self.fx.api; },
      panes() {
        return Array.from(document.querySelectorAll(LANE)).map(el => {
          const r = el.getBoundingClientRect();
          return { el, repo: el.dataset.repo, box: { x: r.left, y: r.top, w: r.width, h: r.height } };
        });
      },
      request() { self.stale = true; self.backStale = true; self.kick(); },
      stroke(group, path, tool, opts = {}) {
        const s = self.skin, ink = opts.ink || tool, names = Object.keys(self.host.tools);
        for (const [k, v] of Object.entries({ tool, ink })) {
          if (!names.includes(v)) throw new TypeError("ink: api.stroke: `" + k + "` " + JSON.stringify(v) + " is no tool (" + names.join(", ") + ")");
        }
        const st = new self.pen.Stroke(tool, opts.seed || 1, opts.dash, opts.tune);
        st.build(path, group, self.inks[ink], self.mode);
        if (!st.dead) s.strokes.add(st);
        return Object.freeze({
          get len() { return st.len; }, get dead() { return st.dead; },
          head(h) { st.setHead(h); }, erase(e) { st.setErase(e); }, done(v) { st.setDone(v); },
          dispose() { if (s.strokes.delete(st)) st.dispose(group); },
        });
      },
    });
  }

  ctx(scene) {
    return { THREE: this.THREE, scene, camera: this.cam, tokens: this.tokens, api: this.api };
  }

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
                  frames: new Map(), framesRoot: group(this.api.order.frame), err: {}, dirty: true,
                  strokes: new Set() };
    this.back.add(this.skin.ground, this.skin.paper);
    this.scene.add(this.skin.framesRoot);
    if (hooks.sampleGround) {
      this.groundRT = new T.WebGLRenderTarget(1, 1, { depthBuffer: false, stencilBuffer: false });
      this.dirty.size = true;
      this.W = 0;
    }
    this.dirty.colours = true;
  }

  unskin() {
    if (this.fx) this.fx = this.fx.detach();
    const s = this.skin;
    if (!s) return;
    this.hook("dispose", this.ctx(null));
    this.kill();
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

  kill(g) {
    const s = this.skin;
    if (s) for (const st of s.strokes) if (!g || g.getObjectById(st.mesh.id)) { s.strokes.delete(st); st.dispose(st.mesh.parent); }
  }

  empty(g) {
    this.kill(g);
    for (const c of g.children.slice()) {
      c.traverse(o => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) [].concat(o.material).forEach(mt => mt.dispose());
      });
      g.remove(c);
    }
  }

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
      const t = f.el.querySelector(".transcript"), q = t && t.getBoundingClientRect();
      const sig = r.width.toFixed(1) + "x" + r.height.toFixed(1) + (q ? "@" + (q.top - r.top).toFixed(1) + "+" + q.height.toFixed(1) : "");
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
    for (const m of Array.from(this.marks)) {
      if (!m.el.isConnected) { this.drop(m); changed = true; }
    }
    if (this.framePanes()) changed = true;
    if (this.fx) this.fx.match();
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
    if (m.lane.root) {
      const r = m.lane.root.getBoundingClientRect();
      x0 = Math.max(x0, r.left + 1); y0 = Math.max(y0, r.top + 1); x1 = Math.min(x1, r.right - 1); y1 = Math.min(y1, r.bottom - 1);
    }
    return [x0, y0, x1, y1];
  }

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

  sync(m) {
    if (m.dropped) return false;
    const r = m.el.isConnected ? m.el.getBoundingClientRect() : null;
    const was = m.visible + "|" + m.x + "|" + m.y + "|" + m.sig + "|" + m.clip.join(",");
    m.visible = !!(r && (r.width || r.height));
    if (m.visible) {
      m.x = r.left; m.y = r.top; m.w = r.width; m.h = r.height;
      const shape = { box: { x: 0, y: 0, w: r.width, h: r.height }, pad: m.row ? m.row.pad : 0, seed: m.seed };
      if (m.shape === "lines") shape.lines = this.linesOf(m.el, r);
      if (m.shape === "underline") this.under(m, r, shape);
      if (m.row && m.row.grow) shape.grow = this.growth(m) * m.row.step;
      if (m.row && (m.row.grow || m.row.tip || m.row.cap)) {
        const pr = m.lane.root ? m.lane.root.getBoundingClientRect() : null;
        shape.limit = (pr ? pr.right : window.innerWidth) - r.left - 14;
        shape.tip = m.row.tip && m.state !== "leaving" && m.state !== "struck";
        shape.cap = m.row.cap || "";
      }
      if (m.shape === "arrow") {
        const t = this.targetOf(m), tr = t && t.getBoundingClientRect();
        shape.to = tr && (tr.width || tr.height) ? { x: tr.left - r.left, y: tr.top - r.top, w: tr.width, h: tr.height } : null;
      }
      let sig = r.width.toFixed(1) + "x" + r.height.toFixed(1);
      if (m.shape === "series" || m.shape === "ticks") {
        const series = m.el.getAttribute("data-ink-series") || "", ticks = m.el.getAttribute("data-ink-ticks") || "";
        shape.values = series.split(/\s+/).filter(Boolean).map(Number).map(v => (Number.isFinite(v) ? clamp(v, 0, 1) : 0));
        shape.ticks = m.shape === "ticks" ? ticks.split(/\s+/).filter(Boolean).map(Number).filter(Number.isInteger) : [];
        sig += "|" + series + "|" + (m.shape === "ticks" ? ticks : "");
      }
      if (shape.lines) sig += "|" + shape.lines.map(l => [l.x, l.y, l.w, l.h].map(v => v.toFixed(1)).join(",")).join(";");
      if (shape.to) sig += "|" + [shape.to.x, shape.to.y, shape.to.w, shape.to.h].map(v => v.toFixed(1)).join(",");
      if (m.strikeOf) sig += "|" + m.strikeOf.sig;
      if (shape.base !== undefined) sig += "|" + Math.round(shape.base) + "," + Math.round(shape.floor);
      if (shape.limit !== undefined) sig += "|" + Math.round(shape.grow || 0) + "," + Math.round(shape.limit) + (shape.tip ? "t" : "") + (shape.cap ? "c" + shape.cap : "");
      const g = m.row && !m.strikeOf ? m.row.snap : 0;
      if (g) {
        shape.snap = { g, at: { x: r.left, y: r.top } };
        if (m.shape === "outline") {
          const cs = getComputedStyle(m.el);
          shape.band = ["Left", "Top", "Right", "Bottom"].map(k => parseFloat(cs["border" + k + "Width"]) + parseFloat(cs["padding" + k]));
          sig += "|" + shape.band.join(",");
        }
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
    const paths = (this.S.SHAPES[m.shape] || this.S.PAGE_SHAPES[m.shape] || (() => []))(shape);
    return shape.snap ? this.S.snap(paths, m.shape, shape.box, shape.snap.at, shape.snap.g, shape) : paths;
  }

  under(m, r, s) {
    let b = r.bottom;
    for (const k of m.el.parentElement ? m.el.parentElement.children : []) {
      const q = k.getBoundingClientRect();
      if (q.height && q.top < r.bottom && q.bottom > r.top) b = Math.max(b, q.bottom);
    }
    s.base = b - r.top;
    const range = document.createRange();
    for (let a = m.el; m.lane.root && a && a !== m.lane.root; a = a.parentElement) {
      let f = Infinity;
      for (const n of a.parentElement ? a.parentElement.children : []) {
        if (n === a) continue;
        const q = n.getBoundingClientRect();
        if (!q.height || q.top <= r.bottom) continue;
        f = Math.min(f, q.top);
        range.selectNodeContents(n);
        for (const w of range.getClientRects()) if (w.height) f = Math.min(f, w.top);
      }
      if (f < Infinity) return void (s.floor = f - r.top);
    }
  }

  build(m, paths) {
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
      st.build(p, this.scene, this.inks[(m.row && m.row.ink) || m.tool] || [0.3, 0.3, 0.3], this.mode);
      if (m.state === "queued") st.setHead(0);
    });
    if (!grows) return;
    let more = false;
    m.strokes.forEach((st, i) => {
      const was = had[i];
      if (st.dead || (was && was.sig === st.sig)) return;
      const keep = was && st.len > was.len ? Math.min(was.head, st.len) : (i === 0 ? st.len : 0);
      if (keep < st.len - 0.01) {
        st.setHead(keep);
        st.setDone(false);
        more = true;
      }
    });
    if (more) this.push(m.lane, { t: "draw", m });
  }

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

  rewrite(m) {
    const now = m.el.textContent;
    if (m.text === null || now === m.text) return false;
    const was = m.text;
    m.text = now;
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

  ghostOf(m, text) {
    const T = this.THREE, cs = getComputedStyle(m.el), dpr = this.dpr || 1;
    const fs = parseFloat(cs.fontSize) || 14;
    const range = document.createRange();
    range.selectNodeContents(m.el);
    const now = (m.el.textContent || "").length, span = range.getBoundingClientRect().width;
    const per = now && span ? span / now : fs * 0.6;
    const w = Math.ceil(per * String(text).length) + 4, h = Math.ceil(fs * 1.4);
    const esc = v => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + Math.round(w * dpr) + '" height="' +
      Math.round(h * dpr) + '" viewBox="0 0 ' + w + " " + h + '"><text x="2" y="' + h / 2 +
      '" dominant-baseline="middle" font-style="' + esc(cs.fontStyle) + '" font-weight="' + esc(cs.fontWeight) +
      '" font-size="' + esc(cs.fontSize) + '" font-family="' + esc(cs.fontFamily) + '" fill="' + esc(cs.color) +
      '">' + esc(text) + "</text></svg>";
    const tex = new T.Texture();
    tex.colorSpace = T.SRGBColorSpace;
    const img = new Image();
    img.onload = () => {
      if (this.stopped || rec.mesh !== mesh) return;
      tex.image = img;
      tex.needsUpdate = true;
      this.stale = true;
      this.kick();
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    const mesh = new T.Mesh(new T.PlaneGeometry(w, h),
                            new T.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false }));
    mesh.renderOrder = 2;
    mesh.frustumCulled = false;
    this.scene.add(mesh);
    const r = m.el.getBoundingClientRect();
    const rec = { text, mesh, box: { x: -w - Math.max(4, fs * 0.35), y: (r.height - h) / 2, w, h } };
    return rec;
  }

  syncAll() {
    let changed = false;
    for (const m of this.marks) if (!m.strikeOf && this.sync(m)) changed = true;
    for (const m of this.marks) if (m.strikeOf && this.sync(m)) changed = true;
    if (this.syncFrames()) changed = true;
    if (this.fx) this.fx.measure();
    return changed;
  }

  rgb(css) {
    return parseColour(css, this.THREE).slice(0, 3);
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
    const tokens = { inks: this.inks, dark: this.dark, css: name => read(name) };
    for (const name of TOKENS) tokens[name] = this.rgb(read("--" + name) || "#888");
    this.tokens = tokens;
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
      this.skin.dirty = this.dirty.geom = true;
      for (const f of this.skin.frames.values()) f.sig = "";
    }
    for (const m of this.marks) {
      for (const st of m.strokes) st.colour(this.inks[(m.row && m.row.ink) || st.tool], this.mode);
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

  instant() {
    return !!(this.reduce && this.reduce.matches);
  }

  handOf(L) {
    if (!L.hand) {
      L.hand = new this.pen.Hand(this.toolScene, this.scene, this.inks);
      L.hand.dark = this.dark;
    }
    L.hand.chalk = this.table.hand === "chalk";
    return L.hand;
  }

  hands() {
    return this.table && this.table.hand && !this.instant();
  }

  speed() {
    return this.table ? this.table.speed : 1;
  }

  run(L, dt) {
    let t = dt;
    for (let guard = 0; guard < 5000; guard++) {
      if (!L.segs.length) {
        if (!L.q.length) return false;
        const op = L.q.shift();
        op.started = true;
        L.op = op;
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
    const once = fn => ({ step: dt => { if (!m.dropped) fn(); return dt; } });
    if (op.t === "draw") {
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
        const row = m.row, old = row.history.get(m.el);
        if (row.leaving.get(m.el) === m) row.leaving.delete(m.el);
        row.history.set(m.el, m);
        if (old && old !== m) this.drop(old);
      }));
      return out;
    }
    return [];
  }

  lift(m) {
    if (!m.row || !m.row.tip || m.state === "leaving") return;
    m.state = "leaving";
    m.sig = "";
    this.sync(m);
  }

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

  kick() {
    if (!this.raf && !this.stopped) this.raf = requestAnimationFrame(t => this.frame(t));
  }

  now() {
    this.prepare();
    if (this.stale) this.render();
    if (this.busy() || this.dirty.table) this.kick();
  }

  prepare() {
    if (this.dirty.size) { this.dirty.size = false; this.resize(); this.stale = true; }
    if (this.dirty.colours) { this.dirty.colours = false; this.colours(); this.stale = true; }
    if (this.skin && this.skin.dirty) {
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
    if (this.fx) this.fx.deliver();
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
        this.handModel = L.hand.key;
        this.stale = true;
        if (L.hand.vis) lifting = true;
      }
    }
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

  refresh() {
    this.dirty.table = this.dirty.geom = this.dirty.colours = true;
    this.kick();
  }

  inspect() {
    const lanes = {};
    for (const L of this.lanes.values()) {
      lanes[L.key] = { queued: L.q.length, busy: !!(L.segs.length || L.q.length), hand: !!(L.hand && L.hand.vis) };
    }
    const marks = [], series = [];
    for (const m of this.marks) {
      if (this.own(m)) {
        const len = m.strokes.reduce((a, s) => a + (s.dead ? 0 : s.len), 0);
        const head = m.strokes.reduce((a, s) => a + (s.dead ? 0 : Math.min(s.head, s.len)), 0);
        series.push({ id: m.id, lane: m.lane.key, tool: m.tool, shape: m.shape, state: m.state,
                      strokes: m.strokes.filter(s => !s.dead).length, len: Math.round(len * 10) / 10,
                      drawn: len ? Math.round(head / len * 1000) / 1000 : 0, visible: m.visible,
                      series: m.el.getAttribute("data-ink-series") || "", ticks: m.el.getAttribute("data-ink-ticks") || "",
                      box: { x: m.x, y: m.y, w: m.w, h: m.h } });
        continue;
      }
      const len = m.strokes.reduce((a, s) => a + (s.dead ? 0 : s.len), 0);
      const head = m.strokes.reduce((a, s) => a + (s.dead ? 0 : Math.min(s.head, s.len)), 0);
      const erased = m.strokes.some(s => s.erase !== Infinity);
      marks.push({
        id: m.id, lane: m.lane.key, selector: m.row ? m.row.selector : "", tool: m.tool,
        ink: (m.row && m.row.ink) || m.tool, cap: m.row ? (m.row.cap || "") : "", shape: m.shape,
        state: m.state, strikeOf: m.strikeOf ? m.strikeOf.id : null, strokes: m.strokes.length,
        len: Math.round(len * 10) / 10,
        drawn: m.shape === "write" ? m.reveal : m.ghost ? 1 : (len ? Math.round(head / len * 1000) / 1000 : 0),
        was: m.ghost ? m.ghost.text : undefined,
        erased, visible: m.visible,
        box: { x: m.x, y: m.y, w: m.w, h: m.h },
        bounds: m.strokes.filter(st => !st.dead).map(st => st.bbox()).filter(Boolean).map(b =>
          ({ x: Math.max(m.x + b.x, m.clip[0]), y: Math.max(m.y + b.y, m.clip[1]),
             r: Math.min(m.x + b.r, m.clip[2]), b: Math.min(m.y + b.b, m.clip[3]) })).filter(b => b.r >= b.x && b.b >= b.y),
        clip: m.shape === "write" ? m.el.style.getPropertyValue("clip-path") : "",
      });
    }
    marks.sort((a, b) => a.id - b.id);
    const s = this.skin;
    const skin = s ? {
      hooks: ["ground", "paper", "frame", "tick", "dispose"].filter(k => typeof s.hooks[k] === "function"),
      ground: s.ground.children.length, paper: s.paper.children.length,
      frames: Array.from(s.frames.values()).filter(f => f.group.children.length).length,
      sampleGround: !!this.groundRT, errors: Object.keys(s.err), strokes: s.strokes.size,
    } : null;
    return { lanes, marks, series, skin, fx: this.fx && this.fx.inspect(), frames: this.frames, renders: this.renders, busy: this.busy(),
             hands: this.hands(), handModel: this.handModel, reduced: this.instant(), canvas: this.canvas.isConnected,
             webgl2: !!this.renderer.capabilities.isWebGL2, mode: this.mode, dark: this.dark };
  }

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
    }
    this.canvas.remove();
  }
}
