export function marks() {
  return [
    { selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -3 },
    { selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" },
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline",
      grow: ".transcript > li", step: 12, tip: true },
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves: "erased" },
    { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .approval:not([hidden]) .summary", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-choice", tool: "pencil", shape: "loop" },
    { selector: ".tile.needs-human .asks:not([hidden])", tool: "marker", shape: "loop", pad: -3 },
    { selector: ".ask.is-answered .ask-q", tool: "pen", shape: "strike" },
    { selector: ".ask.is-answered .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "ellipse" },
    { selector: ".ask.is-answered:not(:has(.ask-choice[aria-pressed=\"true\"])) .ask-answer",
      tool: "pen", shape: "ellipse" },
    { selector: ".tile.state-error .why", tool: "marker", shape: "loop", pad: 0 },
    { selector: ".tile.state-error", tool: "marker", shape: "bang" },
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".runline" },
    { selector: ".tile:has(.oldsession:not([hidden]))", tool: "pencil", shape: "outline", dash: true, pad: -8 },
    { selector: ".tile .transcript > li.friction", tool: "red", shape: "ellipse", pad: -6 },
    { selector: ".tile .transcript > li.friction > .k", tool: "highlighter", shape: "lines" },
    { selector: ".tile .transcript > li.friction > .v", tool: "pencil", shape: "write" },
    { selector: "#bellcount", tool: "pen", shape: "write", rewrite: true },
  ];
}

const T = { w: 1.3, press: 1, pvar: 0, wob: 0, bow: 0, tin: 0, tout: 0 };

export const options = { paper: "--paper", hand: false, speed: 1.5, tools: { pencil: T, pen: T, red: T, green: T } };

export const sampleGround = false;

function rgbOf(tokens, name, fallback) {
  const s = String(tokens.css(name) || "").trim();
  let m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (m) {
    let h = m[1];
    if (h.length === 3) h = h.split("").map(c => c + c).join("");
    const n = parseInt(h, 16);
    return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
  }
  m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(s);
  if (m) return [Number(m[1]) / 255, Number(m[2]) / 255, Number(m[3]) / 255];
  return fallback;
}

const GLASS_FS = `
uniform vec3 uPaper; uniform vec3 uScan; uniform vec3 uMax; uniform float uDpr; uniform vec2 uView;
float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uDpr - gl_FragCoord.y) / uDpr;
  float lit = mod(floor(p.y), 3.0) < 1.0 ? 1.0 : 0.0;
  vec3 c = mix(uPaper, uScan, lit);
  c += (h21(floor(gl_FragCoord.xy)) - 0.5) * 0.012;
  vec2 q = p / max(uView, vec2(1.0)) - 0.5;
  c *= 1.0 - 0.2 * smoothstep(0.35, 0.75, length(q));
  gl_FragColor = vec4(clamp(c, uPaper, max(uPaper, uMax)), 1.0);
}`;

const RAIL_BELOW = 90;
const GUTTER = 36;
const CELL_W = 7;
const CELL_H = 10;
const COL_X = (GUTTER - CELL_W) / 2;
const HEADROOM = 60;
const FOOT = 4;
const FALL_MIN = 900;
const SLOWEST = 0.32;
const TEAR_FOR = 0.12;
const TEAR = 4;
const BAND = 2;
const BAND_X = 4;
const SLOTS = 64;
const MAX = 2048;

const RAIN_VS = `
attribute vec4 aRect; attribute vec3 aColor; attribute float aPane; attribute float aSeed;
uniform vec4 uPane[${SLOTS}];
varying vec3 vColor; varying vec2 vUv; varying float vSeed;
void main(){
  vec4 at = uPane[int(aPane + 0.5)];
  vUv = vec2(position.x, 1.0 - position.y);
  vColor = aColor; vSeed = aSeed;
  vec2 p = aRect.xy + vUv * aRect.zw;
  gl_Position = projectionMatrix * viewMatrix * vec4(at.x + p.x, at.y - p.y, 0.0, 1.0);
  if (at.z < 0.5) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}`;

const RAIN_FS = `
varying vec3 vColor; varying vec2 vUv; varying float vSeed;
float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
void main(){
  if (vSeed >= 0.0) {
    vec2 d = floor(vUv * vec2(${CELL_W}.0, ${CELL_H}.0) - vec2(1.0, 1.5));
    if (d.x < 0.0 || d.x > 4.0 || d.y < 0.0 || d.y > 6.0) discard;
    if (h21(vec2(d.x + d.y * 5.0, vSeed)) > 0.4) discard;
  }
  gl_FragColor = vec4(vColor, 1.0);
}`;

const R = {
  mesh: null, tokens: null, reduced: false,
  panes: new Map(), slots: new Array(SLOTS).fill(null), uPane: [],
  before: 0, drawCalls: 0, papers: 0, quiet: new WeakSet(), watch: null,
};

function hushed() {
  const b = document.body.classList;
  return b.contains("is-stale") || b.contains("is-replaying");
}

function watch(el) {
  const list = el.querySelector(".transcript");
  if (!list || typeof MutationObserver !== "function") return;
  if (!R.watch) {
    R.watch = new MutationObserver(recs => {
      if (!hushed()) return;
      for (const r of recs) for (const n of r.addedNodes) R.quiet.add(n);
    });
  }
  R.watch.observe(list, { childList: true });
}

function remember({ THREE, tokens, api }) {
  if (tokens) R.tokens = tokens;
  if (api) R.reduced = api.reduced;
  if (THREE && !R.uPane.length) for (let i = 0; i < SLOTS; i++) R.uPane.push(new THREE.Vector4(0, 0, 0, 0));
}

function seedOf(p, n) {
  let h = 2166136261 ^ p.slot;
  for (const c of (p.el.dataset.repo || "") + ":" + n) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return (h >>> 0) % 997;
}

function capOf(p) {
  return p.w < RAIL_BELOW ? 0 : Math.max(0, Math.floor((p.h - HEADROOM) / CELL_H));
}

function slotY(p, k) {
  return p.h - FOOT - CELL_H * (k + 1);
}

function place() {
  for (const p of R.panes.values()) {
    const g = p.group, on = !!(g && g.parent && g.visible && p.el.isConnected);
    R.uPane[p.slot].set(on ? g.position.x : 0, on ? g.position.y : 0, on ? 1 : 0, 0);
  }
}

function fill() {
  const m = R.mesh, t = R.tokens;
  if (!m || !t) return;
  const g = m.geometry, rect = g.getAttribute("aRect"), col = g.getAttribute("aColor");
  const pane = g.getAttribute("aPane"), seed = g.getAttribute("aSeed");
  let i = 0;
  const put = (slot, x, y, w, h, c, s) => {
    if (i >= MAX) return;
    rect.setXYZW(i, x, y, w, h);
    col.setXYZ(i, c[0], c[1], c[2]);
    pane.setX(i, slot);
    seed.setX(i, s);
    i += 1;
  };
  for (const p of R.panes.values()) {
    if (p.w < RAIL_BELOW) continue;
    const x = COL_X + (p.tear ? p.tear.side * TEAR : 0), c = p.done ? t.done : t.accent;
    p.stack.forEach((q, k) => put(p.slot, x, q.landed ? slotY(p, k) : q.y, CELL_W, CELL_H, c, q.seed));
    if (p.error) put(p.slot, BAND_X, p.head, GUTTER - 2 * BAND_X, BAND, t.human, -1);
  }
  m.count = i;
  m.visible = i > 0;
  for (const a of [rect, col, pane, seed]) a.needsUpdate = true;
}

function rain(THREE, api) {
  const g = new THREE.BufferGeometry();
  const quad = new THREE.PlaneGeometry(1, 1).translate(0.5, 0.5, 0);
  g.index = quad.index;
  g.setAttribute("position", quad.getAttribute("position"));
  g.setAttribute("aRect", new THREE.InstancedBufferAttribute(new Float32Array(MAX * 4), 4));
  g.setAttribute("aColor", new THREE.InstancedBufferAttribute(new Float32Array(MAX * 3), 3));
  g.setAttribute("aPane", new THREE.InstancedBufferAttribute(new Float32Array(MAX), 1));
  g.setAttribute("aSeed", new THREE.InstancedBufferAttribute(new Float32Array(MAX), 1));
  const m = new THREE.InstancedMesh(g, new THREE.ShaderMaterial({
    vertexShader: RAIN_VS, fragmentShader: RAIN_FS, depthTest: false, depthWrite: false,
    uniforms: { uPane: { value: R.uPane } },
  }), MAX);
  m.count = 0;
  m.visible = false;
  m.frustumCulled = false;
  m.renderOrder = api.order.paper + 1;
  m.onBeforeRender = renderer => { place(); R.before = renderer.info.render.calls; };
  m.onAfterRender = renderer => { R.drawCalls = renderer.info.render.calls - R.before; };
  return m;
}

export function paper(ctx) {
  remember(ctx);
  const { THREE, scene, tokens, api } = ctx;
  const { w, h, dpr } = api.viewport;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.ShaderMaterial({
    vertexShader: "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: GLASS_FS, depthTest: false, depthWrite: false,
    uniforms: {
      uPaper: { value: new THREE.Vector3(...rgbOf(tokens, "--paper", tokens.bg)) },
      uScan: { value: new THREE.Vector3(...rgbOf(tokens, "--scan", tokens.panel)) },
      uMax: { value: new THREE.Vector3(...rgbOf(tokens, "--board-max", tokens.panel)) },
      uDpr: { value: dpr },
      uView: { value: new THREE.Vector2(w, h) },
    },
  }));
  mesh.frustumCulled = false;
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = api.order.paper;
  scene.add(mesh);
  R.mesh = rain(THREE, api);
  scene.add(R.mesh);
  R.papers += 1;
  fill();
}

export function frame(ctx, el, box) {
  remember(ctx);
  let p = R.panes.get(el);
  if (!p) {
    const slot = R.slots.indexOf(null);
    if (slot < 0) return;
    const cl = el.classList;
    p = { el, slot, group: null, w: 0, h: 0, head: 0, seen: new WeakSet(el.querySelectorAll(".transcript > li")),
          stack: [], n: 0, drain: null, tear: null, running: cl.contains("state-running"),
          error: cl.contains("state-error"), done: cl.contains("is-done") };
    R.slots[slot] = el;
    R.panes.set(el, p);
    watch(el);
  }
  p.group = ctx.scene;
  p.w = box.w;
  p.h = box.h;
  const head = el.querySelector(".head");
  p.head = head ? Math.round(head.getBoundingClientRect().bottom - el.getBoundingClientRect().top) + 2 : 0;
}

function forget() {
  let gone = false;
  for (const [el, p] of Array.from(R.panes)) {
    if (el.isConnected && (!p.group || p.group.parent)) continue;
    R.slots[p.slot] = null;
    R.uPane[p.slot].set(0, 0, 0, 0);
    R.panes.delete(el);
    gone = true;
  }
  return gone;
}

function step(p, dt, hush) {
  const cl = p.el.classList, now = R.reduced;
  const running = cl.contains("state-running"), error = cl.contains("state-error"), done = cl.contains("is-done");
  let changed = false;
  for (const li of p.el.querySelectorAll(".transcript > li")) {
    if (p.seen.has(li)) continue;
    p.seen.add(li);
    if (!running || p.w < RAIL_BELOW) continue;
    p.stack.push({ seed: seedOf(p, p.n++), y: 0, t: 0, landed: hush || now || R.quiet.has(li) });
    changed = true;
  }
  const cap = capOf(p);
  if (p.stack.length > cap) {
    p.stack.splice(0, p.stack.length - cap);
    changed = true;
  }
  p.stack.forEach((q, k) => {
    if (q.landed) return;
    changed = true;
    if (hush || now) { q.landed = true; return; }
    q.t += dt;
    const to = slotY(p, k), v = Math.max(FALL_MIN, to / SLOWEST);
    q.y = Math.min(to, v * q.t);
    if (q.y >= to) q.landed = true;
  });
  if (running || done) p.drain = null;
  else if (p.stack.length && !p.drain) {
    for (const q of p.stack) q.landed = true;
    p.drain = { n0: p.stack.length, t: 0 };
  }
  if (p.drain) {
    p.drain.t += dt;
    const left = now ? 0 : Math.ceil(p.drain.n0 * (1 - p.drain.t / SLOWEST));
    p.stack.length = Math.max(0, Math.min(p.stack.length - 1, left));
    if (!p.stack.length) p.drain = null;
    changed = true;
  }
  if (error && !p.error && !now && p.w >= RAIL_BELOW) p.tear = { t: 0, side: p.slot % 2 ? -1 : 1 };
  if (p.tear) {
    p.tear.t += dt;
    if (p.tear.t >= TEAR_FOR || now) p.tear = null;
    changed = true;
  }
  if (error !== p.error || done !== p.done) changed = true;
  p.running = running;
  p.error = error;
  p.done = done;
  return changed;
}

export function tick(ctx, dt) {
  remember(ctx);
  let changed = forget();
  const hush = hushed();
  let more = false;
  for (const p of R.panes.values()) {
    if (step(p, dt, hush)) changed = true;
    if (p.drain || p.tear || p.stack.some(q => !q.landed)) more = true;
  }
  if (changed) fill();
  return more;
}

export function dispose() {
  if (R.watch) R.watch.disconnect();
  R.watch = null;
  R.panes.clear();
  R.slots.fill(null);
  for (const u of R.uPane) u.set(0, 0, 0, 0);
  R.mesh = null;
  R.drawCalls = 0;
}

export function inspect() {
  const panes = {};
  for (const p of R.panes.values()) {
    panes[p.el.dataset.repo || ""] = { settled: p.stack.filter(q => q.landed).length,
                                       falling: p.stack.filter(q => !q.landed).length,
                                       draining: !!p.drain, tear: !!p.tear,
                                       band: p.error && p.w >= RAIL_BELOW };
  }
  return { panes, drawCalls: R.drawCalls, papers: R.papers };
}
