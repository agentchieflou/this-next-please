const MARKS = [
  { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines" },
  { selector: ".tile.needs-human .asks:not([hidden]) .ask:not([hidden]) .ask-q", tool: "highlighter", shape: "lines" },
  { selector: ".tile.needs-human .asks:not([hidden])", tool: "marker", shape: "loop", pad: -3 },
  { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" },
  { selector: ".tile.state-error .why", tool: "marker", shape: "loop", pad: 0 },
  { selector: ".tile.state-error", tool: "red", shape: "bang" },
  { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
  { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", dash: true, pad: 0 },
  { selector: ".tile .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "loop", pad: 2 },
  { selector: ".tile .transcript li.friction .v, .tile .transcript li.denied .v", tool: "red", shape: "underline" },
];

export function marks() {
  return MARKS.map(r => Object.assign({}, r));
}

export const options = { hand: true, speed: 1 };

const GROUND = 32;
const STRIP = 10;
const CELL = 10;
const SOCKETS = 3;
const EDGE = 2;
const DROP = 4;
const LIFT = 5;
const TURN_EVERY = 3;
const TURN_FOR = 0.6;
const SLOTS = 64;
const PER_STACK = 6;
const FX_CAP = 192;
const FRAME = 1 / 60;
const FX_LIFE = 0.8;
const BREAK_LIFE = 0.5;
const PLACE_FLY = 0.24;
const PLACE_GAP = 0.01;
const SWELL_FRAMES = 2;
const SWELL = 1.04;
const HOME_AT = 0.18;
const SHRINK_FRAMES = 3;
const POP_FRAMES = 2;
const OMEGA = 14;
const FALL = 1800;
const NEAR = 8;
const LANDED = 12;
const CHIP = 6;
const BLASTS = 2;
const FLASH_UP = 1.25;
const FLASH_DOWN = 0.6;
const FLASH_FRAMES = 2;
const CHUNKS = 140;
const RAIL = 90;
const BLINK = 0.09;
const KNOCK = 3;
const KNOCK_FOR = 0.15;
const GRAZE_EVERY = 5000;
const GRAZE_NEAR = 16;
const GRAZE_FALL = 30;
const GRAZE_LIFE = 0.36;
const ORBS = 5;
const ORB = 4;
const ORB_GAP = 0.06;
const ORB_CLIMB = 0.25;
const HEART_AT = [0.46, 0.5, 0.54];
const HEART_END = 0.72;
const HEART_RISE = 12;
const HEART = [".x.x.", "xxxxx", ".xxx.", "..x.."];

const LIGHT = (() => {
  const v = [-0.45, 0.55, 0.9], n = Math.hypot(v[0], v[1], v[2]);
  return v.map(x => x / n);
})();

const VERT = `
attribute vec3 aSize;
attribute float aBevel;
attribute vec3 aColor;
attribute float aPane;
uniform vec4 uPane[${SLOTS}];
uniform vec3 uLight;
varying vec3 vColor;
varying float vLit;
void main() {
  vec4 at = uPane[int(aPane + 0.5)];
  vec3 h = aSize * 0.5;
  float k = position.z;
  vec3 p = vec3(position.x * (h.x - (k < 0.5 ? aBevel : 0.0)),
                position.y * (h.y - (k < 0.5 ? aBevel : 0.0)),
                k < 0.5 ? h.z : (k < 1.5 ? h.z - aBevel : -h.z));
  vec4 local = instanceMatrix * vec4(p, 1.0);
  vec3 n = normalize(mat3(instanceMatrix) * normal);
  vLit = dot(n, uLight) - uLight.z;
  vColor = aColor;
  gl_Position = projectionMatrix * viewMatrix * vec4(local.x + at.x, local.y + at.y, local.z, 1.0);
  if (at.z < 0.5 || aSize.x <= 0.0) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}`;

const FRAG = `
varying vec3 vColor;
varying float vLit;
void main() {
  float s = 1.0 + 1.3 * vLit;
  vec3 c = vColor * clamp(s, 0.0, 1.0);
  c = mix(c, vec3(1.0), clamp((s - 1.0) * 1.6, 0.0, 0.5));
  gl_FragColor = vec4(c, 1.0);
}`;

function template(THREE) {
  const ref = (x, y, k) => [x * (1 - (k === 0 ? 0.25 : 0)), y * (1 - (k === 0 ? 0.25 : 0)),
                            k === 0 ? 1 : k === 1 ? 0.75 : -1];
  const pos = [], nor = [];
  const quad = (corners, n) => {
    const p = corners.map(c => ref(c[0], c[1], c[2]));
    const e1 = p[1].map((v, i) => v - p[0][i]), e2 = p[2].map((v, i) => v - p[0][i]);
    const cr = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    if (cr[0] * n[0] + cr[1] * n[1] + cr[2] * n[2] < 0) corners = corners.slice().reverse();
    for (const i of [0, 1, 2, 0, 2, 3]) { pos.push(...corners[i]); nor.push(...n); }
  };
  const r2 = Math.SQRT1_2;
  quad([[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]], [0, 0, 1]);
  quad([[-1, -1, 2], [-1, 1, 2], [1, 1, 2], [1, -1, 2]], [0, 0, -1]);
  const sides = [[[1, 0], [0, 1]], [[-1, 0], [0, 1]], [[0, 1], [1, 0]], [[0, -1], [1, 0]]];
  for (const [[ax, ay], [bx, by]] of sides) {
    const c = (s, k) => [ax + bx * s, ay + by * s, k];
    quad([c(-1, 0), c(1, 0), c(1, 1), c(-1, 1)], [ax * r2, ay * r2, r2]);
    quad([c(-1, 1), c(1, 1), c(1, 2), c(-1, 2)], [ax, ay, 0]);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  return g;
}

function parse(s) {
  s = String(s || "").trim();
  let m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (m) {
    const h = m[1].length === 3 ? m[1].replace(/./g, c => c + c) : m[1];
    return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
  }
  m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(s);
  return m ? [+m[1] / 255, +m[2] / 255, +m[3] / 255] : null;
}

const shade = (c, f) => [Math.min(1, c[0] * f), Math.min(1, c[1] * f), Math.min(1, c[2] * f)];

function surfaces(tokens) {
  const own = (name, fallback) => parse(tokens.css(name)) || fallback;
  return {
    ground: own("--voxel-ground", tokens.bg),
    panel: own("--voxel-panel", tokens.panel),
    edge: own("--voxel-edge", shade(tokens.bg, 0.4)),
    accent: tokens.accent,
  };
}

function jitter(i, j) {
  let h = Math.imul(i * 374761393 + j * 668265263, 1274126177);
  h ^= h >>> 13;
  return [0.84, 0.92, 1, 1, 1.08][(h >>> 0) % 5];
}

const S = {
  THREE: null, api: null, tokens: null, renderer: null,
  ground: null, slabs: null, stacks: null,
  panes: new Map(),
  slots: new Array(SLOTS).fill(null),
  uPane: [],
  dirty: false,
  timer: 0, turnAt: 0,
  drawCalls: 0,
  builds: 0,
  grid: null,
  fx: null,
};

function fxState() {
  return { pieces: [], flashes: [], blasts: [], seq: 0, wrote: false, dest: null,
           played: { blast: 0, break: 0, place: 0, hurt: 0, graze: 0, reward: 0 }, shook: 0,
           ends: { near: 0, far: 0 } };
}
S.fx = fxState();

function vec4s(THREE) {
  const a = [];
  for (let i = 0; i < SLOTS; i++) a.push(new THREE.Vector4(0, 0, i === 0 ? 1 : 0, 0));
  return a;
}

function material(THREE) {
  return new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG,
    uniforms: { uPane: { value: S.uPane }, uLight: { value: new THREE.Vector3(...LIGHT) } },
    depthTest: false, depthWrite: false, side: THREE.FrontSide,
  });
}

function mesh(THREE, n, order) {
  const g = template(THREE);
  g.setAttribute("aSize", new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3));
  g.setAttribute("aBevel", new THREE.InstancedBufferAttribute(new Float32Array(n), 1));
  g.setAttribute("aColor", new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3));
  g.setAttribute("aPane", new THREE.InstancedBufferAttribute(new Float32Array(n), 1));
  const m = new THREE.InstancedMesh(g, material(THREE), n);
  m.count = 0;
  m.frustumCulled = false;
  m.renderOrder = order;
  return m;
}

function writer(THREE, m) {
  const g = m.geometry, M = new THREE.Matrix4();
  const size = g.getAttribute("aSize"), bev = g.getAttribute("aBevel");
  const col = g.getAttribute("aColor"), pane = g.getAttribute("aPane");
  let i = 0;
  return {
    get n() { return i; },
    put(slot, x, y, w, h, d, bevel, c, turn = 0, tilt = 0) {
      if (i >= m.instanceMatrix.count) return -1;
      M.makeRotationFromEuler(new THREE.Euler(0, turn, tilt));
      M.setPosition(x, -y, d / 2);
      m.setMatrixAt(i, M);
      size.setXYZ(i, w, h, d);
      bev.setX(i, bevel);
      col.setXYZ(i, c[0], c[1], c[2]);
      pane.setX(i, slot);
      return i++;
    },
    done() {
      m.count = i;
      m.instanceMatrix.needsUpdate = true;
      for (const a of [size, bev, col, pane]) a.needsUpdate = true;
    },
  };
}

function remember({ THREE, tokens, api }) {
  S.THREE = THREE;
  S.tokens = tokens;
  S.api = api;
  S.renderer = api.renderer;
  if (!S.uPane.length) S.uPane = vec4s(THREE);
}

export function ground(ctx) {
  remember(ctx);
  const { THREE, scene, tokens, api } = ctx;
  const { w, h } = api.viewport;
  const cols = Math.ceil(w / GROUND), rows = Math.ceil(h / GROUND);
  if (S.ground) S.ground.dispose();
  S.ground = mesh(THREE, cols * rows, api.order.ground);
  S.fx.flashes = [];
  const base = surfaces(tokens).ground, put = writer(THREE, S.ground);
  S.grid = { cols, rows, base };
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      put.put(0, i * GROUND + GROUND / 2, j * GROUND + GROUND / 2, GROUND, GROUND, GROUND, 3,
              shade(base, jitter(i, j)));
    }
  }
  put.done();
  scene.add(S.ground);
}

export function paper(ctx) {
  remember(ctx);
  const { THREE, scene, api } = ctx;
  if (S.slabs) S.slabs.dispose();
  if (S.stacks) S.stacks.dispose();
  S.slabs = mesh(THREE, capacity(), api.order.paper);
  S.stacks = mesh(THREE, SLOTS * PER_STACK + FX_CAP, api.order.paper + 1);
  S.slabs.onBeforeRender = place;
  S.stacks.onAfterRender = renderer => { S.drawCalls = renderer.info.render.calls; };
  scene.add(S.slabs, S.stacks);
  build();
  stacks(0, true);
}

export function frame(ctx, el, box) {
  remember(ctx);
  let p = S.panes.get(el);
  if (!p) {
    const slot = S.slots.indexOf(null, 1);
    if (slot < 0) return;
    p = { el, group: ctx.scene, slot, w: 0, h: 0, stack: fresh(), blink: null, knock: -1, grazed: -Infinity };
    S.slots[slot] = el;
    S.panes.set(el, p);
  }
  p.group = ctx.scene;
  p.w = box.w;
  p.h = box.h;
  build();
  read(p);
  stacks(0, true);
}

export function tick(ctx, dt) {
  remember(ctx);
  if (forget()) build();
  let moved = false;
  for (const p of S.panes.values()) if (read(p)) moved = true;
  const step = Math.max(dt, FRAME);
  const flying = pieces(step), flashing = flash(step), hitting = hits(step);
  const more = stacks(dt, moved || flying || S.fx.wrote || hitting);
  schedule();
  return more || flying || flashing || hitting;
}

export const cues = [
  { selector: "#grid > .tile:not(.is-hidden)", on: "leave", cue: "blast" },
  { selector: "#grid > .tile:not(.is-hidden)", on: "arrive", cue: "place" },
  { selector: "#modelcard:not([hidden]), #dispatch:not([hidden]), #keymap:not([hidden]), #side:not([hidden]), .tile .scope:not([hidden])",
    on: "leave", cue: "break" },
  { selector: "#grid > .tile.state-error", on: "arrive", cue: "hurt" },
  { selector: ".tile .transcript li.denied, .tile .transcript li.friction, .tile .transcript li.error, .tile .err:not([hidden])",
    on: "arrive", cue: "graze" },
  { selector: "#grid > .tile:is(.state-done, .is-done)", on: "arrive", cue: "reward" },
];

export function cue(ctx, name, el, box, how) {
  remember(ctx);
  if (!S.stacks || !S.tokens || ctx.api.reduced || !box.w || !box.h) return;
  const grouped = el.classList.contains("is-grouped");
  if (name === "blast" && !grouped) {
    S.fx.blasts = S.fx.blasts.filter(b => b.pieces.some(q => S.fx.pieces.includes(q)));
    if (S.fx.blasts.length >= BLASTS) chips(box);
    else blast(box, how, el.dataset.repo || "");
  } else if (name === "place" && !grouped) {
    homing(box);
  } else if (name === "break") {
    chips(box);
  } else if (name === "hurt" || name === "graze" || name === "reward") {
    hit(ctx, name, el, box);
  }
  ctx.api.request();
}

export function dispose() {
  if (S.timer) clearTimeout(S.timer);
  for (const m of [S.ground, S.slabs, S.stacks]) if (m) m.dispose();
  S.timer = 0;
  S.ground = S.slabs = S.stacks = null;
  S.panes.clear();
  S.slots.fill(null);
  for (let i = 1; i < S.uPane.length; i++) S.uPane[i].set(0, 0, 0, 0);
  S.api = null;
  S.drawCalls = 0;
  S.grid = null;
  S.fx = fxState();
}

function stripCubes(h) {
  return Math.max(1, Math.round((h - SOCKETS * CELL) / CELL));
}

function capacity() {
  let n = 0;
  for (const p of S.panes.values()) n += 2 + SOCKETS + stripCubes(p.h);
  return Math.max(256, n * 2);
}

function forget() {
  let gone = false;
  for (const [el, p] of Array.from(S.panes)) {
    if (p.group.parent && el.isConnected) continue;
    S.slots[p.slot] = null;
    if (S.uPane[p.slot]) S.uPane[p.slot].set(0, 0, 0, 0);
    S.panes.delete(el);
    gone = true;
  }
  return gone;
}

function build() {
  if (!S.slabs || !S.tokens) return;
  const need = capacity();
  if (need > S.slabs.instanceMatrix.count) {
    const parent = S.slabs.parent, old = S.slabs;
    S.slabs = mesh(S.THREE, need, old.renderOrder);
    S.slabs.onBeforeRender = place;
    if (parent) { parent.remove(old); parent.add(S.slabs); }
    old.geometry.dispose();
    old.material.dispose();
    old.dispose();
  }
  const c = surfaces(S.tokens), put = writer(S.THREE, S.slabs);
  for (const p of S.panes.values()) {
    const { slot, w, h } = p;
    if (!w || !h) continue;
    const b = p.blink && blinkOn(p.blink) ? p.blink : null;
    const tint = (y, col) => (b && y >= b.lo && y <= b.hi ? S.tokens.human : col);
    put.put(slot, w / 2, h / 2 + DROP, w, h, 6, 0, c.edge);
    put.put(slot, STRIP + (w - STRIP) / 2, h / 2, w - STRIP, h, 12, EDGE, c.panel);
    for (let k = 0; k < SOCKETS; k++) {
      const y = k * CELL + CELL / 2;
      put.put(slot, STRIP / 2, y, STRIP, CELL, 4, 1, tint(y, shade(c.edge, 1.6)));
    }
    const n = stripCubes(h), top = SOCKETS * CELL, step = (h - top) / n;
    for (let k = 0; k < n; k++) {
      const y = top + k * step + step / 2;
      put.put(slot, STRIP / 2, y, STRIP, step, STRIP, 2, tint(y, shade(c.accent, jitter(slot, k) * 0.9)));
    }
  }
  put.done();
  S.builds += 1;
}

function place() {
  for (const p of S.panes.values()) {
    const g = p.group, on = !!(g.parent && g.visible && p.el.isConnected);
    S.uPane[p.slot].set(g.position.x, g.position.y, on ? 1 : 0, 0);
  }
}

const LEVEL = { idle: 1, starting: 1, done: 3 };
const TONE = { running: "running", waiting_approval: "waiting", needs_human: "human", blocked: "human",
               error: "human", done: "done", idle: "idle", starting: "idle" };

function fresh() {
  return { state: "", needs: false, stale: false, finding: false, lift: 0, turn: 0, turning: 0 };
}

function read(p) {
  const el = p.el, st = p.stack;
  let state = "idle";
  for (const c of el.classList) if (c.startsWith("state-")) state = c.slice(6);
  if (state === "idle" && el.classList.contains("is-done")) state = "done";
  const needs = el.classList.contains("needs-human");
  const old = el.querySelector(".oldsession");
  const stale = !!(old && !old.hidden);
  const finding = !!el.querySelector(".transcript li.friction, .transcript li.denied");
  if (state === st.state && needs === st.needs && stale === st.stale && finding === st.finding) return false;
  if (state !== "running") st.turning = 0;
  Object.assign(st, { state, needs, stale, finding });
  return true;
}

function stacks(dt, changed) {
  if (!S.stacks || !S.tokens) return false;
  const reduced = !!(S.api && S.api.reduced);
  let moving = false;
  for (const p of S.panes.values()) {
    const st = p.stack;
    const want = st.needs ? LIFT : 0;
    if (reduced) st.lift = want;
    else if (st.lift !== want) {
      const v = 40 * dt;
      st.lift = Math.abs(want - st.lift) <= v ? want : st.lift + Math.sign(want - st.lift) * v;
    }
    if (st.lift !== want) moving = true;
    if (st.turning > 0) {
      if (reduced) st.turning = 0;
      else {
        st.turning = Math.max(0, st.turning - dt);
        moving = true;
      }
    }
  }
  if (!moving && !changed && dt > 0) return false;
  const c = surfaces(S.tokens), put = writer(S.THREE, S.stacks);
  for (const p of S.panes.values()) {
    const st = p.stack, slot = p.slot;
    const level = LEVEL[st.state] || 2;
    const tone = S.tokens[TONE[st.state] || "idle"] || S.tokens.idle;
    const low = shade(tone, 0.62);
    const cy = k => (SOCKETS - 1 - k) * CELL + CELL / 2;
    const x = STRIP / 2 - knockOf(p);
    for (let k = 0; k < SOCKETS; k++) {
      const top = k === level - 1;
      if (k >= level || !p.w) { put.put(slot, 0, 0, 0, 0, 0, 0, low); continue; }
      if (!top) { put.put(slot, x, cy(k), CELL, CELL, CELL, 2, low); continue; }
      const y = cy(k) - st.lift;
      const ease = st.turning > 0 ? 1 - st.turning / TURN_FOR : 0;
      const turn = ease * ease * (3 - 2 * ease) * Math.PI / 2;
      if (st.state === "error") {
        put.put(slot, x - 2.6, y, CELL / 2 - 0.6, CELL, CELL, 1, tone, 0, 0.14);
      } else {
        put.put(slot, x, y, CELL, CELL, CELL, 2, tone, turn);
      }
    }
    const topY = cy(level - 1) - st.lift;
    if (st.state === "error" && p.w) put.put(slot, x + 2.6, topY + 0.8, CELL / 2 - 0.6, CELL, CELL, 1, tone, 0, -0.18);
    else put.put(slot, 0, 0, 0, 0, 0, 0, tone);
    put.put(slot, x + 1, topY - CELL / 2 - 1.5, st.stale && p.w ? 4 : 0, 3, 4, 0.5, S.tokens.muted);
    put.put(slot, x - 1.5, cy(0) + 1.5, st.finding && p.w ? 3 : 0, 3, CELL + 2, 0.5, S.tokens.human);
  }
  for (const q of S.fx.pieces) {
    const k = scaleOf(q);
    if (k > 0) put.put(0, q.x, q.y, q.w * k, q.h * k, CHIP, 0, q.c, 0, q.rot);
  }
  S.fx.wrote = S.fx.pieces.length > 0;
  put.done();
  return moving;
}

function rnd(n) {
  let h = Math.imul(n ^ 2747636419, 2654435769);
  h ^= h >>> 16;
  h = Math.imul(h, 2246822507);
  h ^= h >>> 13;
  return (h >>> 0) / 4294967296;
}

function colourOf(c, i, j, ring) {
  return ring ? c.edge : shade(c.panel, Math.min(1, jitter(i, j)));
}

function add(list) {
  const all = S.fx.pieces;
  all.push(...list);
  if (all.length > FX_CAP) all.splice(0, all.length - FX_CAP);
}

function piece(kind, x, y, w, h, c, life, extra) {
  return Object.assign({ kind, x, y, w, h, vx: 0, vy: 0, rot: 0, vr: 0, c, t: 0, f: 0, life,
                         pop: -1 }, extra);
}

/** @param {HTMLElement | null} el */
function centre(el) {
  if (!el || el.hidden || !el.isConnected) return null;
  const r = el.getBoundingClientRect();
  return r.width && r.height ? [r.left + r.width / 2, r.top + r.height / 2] : null;
}

function destOf(how, repo) {
  if (how === "unmatched") return centre(document.getElementById("hiddencount"));
  if (how !== "removed") return null;
  const list = document.getElementById("gone");
  if (!list || list.hidden) return null;
  for (const li of Array.from(list.children)) {
    if (/** @type {HTMLElement} */ (li).dataset.repo === repo) return centre(/** @type {HTMLElement} */ (li));
  }
  return null;
}

function blast(box, how, repo) {
  const c = surfaces(S.tokens), seq = ++S.fx.seq;
  const k = Math.max(12, Math.ceil(Math.sqrt(box.w * box.h / CHUNKS)));
  const cols = Math.max(1, Math.floor(box.w / k)), rows = Math.max(1, Math.floor(box.h / k));
  const cw = box.w / cols, ch = box.h / rows, cx = box.x + box.w / 2, cy = box.y + box.h / 2;
  const b = { how, repo, dest: destOf(how, repo), pieces: [] };
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      const ring = i === 0 || j === 0 || i === cols - 1 || j === rows - 1;
      const n = seq * 4099 + j * 131 + i;
      b.pieces.push(piece("blast", box.x + (i + 0.5) * cw, box.y + (j + 0.5) * ch, cw, ch,
                          colourOf(c, i, j, ring), FX_LIFE,
                          { cx, cy, blast: b, speed: 260 + 360 * rnd(n),
                            vr: (rnd(n + 7) < 0.5 ? -1 : 1) * 6 * rnd(n + 3) }));
    }
  }
  S.fx.blasts.push(b);
  S.fx.dest = b.dest;
  S.fx.played.blast += 1;
  add(b.pieces);
  lit(box);
}

function chips(box) {
  const c = surfaces(S.tokens), seq = ++S.fx.seq, n = 12 + Math.floor(rnd(seq * 17) * 13);
  const list = [];
  for (let i = 0; i < n; i++) {
    const r = seq * 257 + i * 5, s = 6 + 4 * rnd(r);
    list.push(piece("break", box.x + box.w * rnd(r + 1), box.y + box.h * (0.5 + 0.5 * rnd(r + 2)), s, s,
                    colourOf(c, i, seq, rnd(r + 3) < 0.4), BREAK_LIFE,
                    { vx: (rnd(r + 4) - 0.5) * 240, vy: -120 * rnd(r + 5), vr: (rnd(r + 6) - 0.5) * 12 }));
  }
  S.fx.played.break += 1;
  add(list);
}

function homing(box) {
  const c = surfaces(S.tokens);
  const from = centre(document.getElementById("hiddencount")) || [box.x + box.w / 2, box.y + box.h / 2];
  const list = [];
  for (let i = 0; i < 8; i++) {
    const k = i % SOCKETS;
    list.push(piece("place", from[0], from[1], CHIP, CHIP, c.edge, PLACE_FLY,
                    { from, to: [box.x + STRIP / 2, box.y + k * CELL + CELL / 2], wait: i * PLACE_GAP }));
  }
  S.fx.played.place += 1;
  add(list);
}

function blinkOn(b) {
  return b.t < BLINK || (b.n === 2 && b.t >= 2 * BLINK && b.t < 3 * BLINK);
}

function knockOf(p) {
  if (p.knock < 0) return 0;
  const u = Math.min(1, p.knock / KNOCK_FOR);
  return KNOCK * (1 - u * u * (3 - 2 * u));
}

function hits(dt) {
  let busy = false, redraw = false;
  for (const p of S.panes.values()) {
    if (p.blink) {
      const was = blinkOn(p.blink);
      p.blink.t += dt;
      if (p.blink.t >= (2 * p.blink.n - 1) * BLINK) p.blink = null;
      if (was !== !!(p.blink && blinkOn(p.blink))) redraw = true;
      if (p.blink) busy = true;
    }
    if (p.knock >= 0) {
      p.knock += dt;
      if (p.knock >= KNOCK_FOR) p.knock = -1;
      busy = true;
    }
  }
  if (redraw) build();
  return busy || redraw;
}

/** @param {Element} pane */
function boxOf(pane) {
  const r = pane.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}

function hit(ctx, name, el, box) {
  const pane = name === "graze" ? el.closest("#grid > .tile") : el;
  const p = pane && S.panes.get(pane);
  if (!p || !p.w) return;
  const b = name === "graze" ? boxOf(pane) : box;
  if (b.w < RAIL || !b.h) return;
  const c = surfaces(S.tokens), done = S.tokens.done, list = [], x = b.x + STRIP / 2;
  if (name === "graze") {
    const now = performance.now();
    if (now - p.grazed < GRAZE_EVERY) return;
    p.grazed = now;
    const y = Math.min(b.y + b.h, Math.max(b.y, box.y + box.h / 2));
    p.blink = { n: 1, t: 0, lo: y - b.y - GRAZE_NEAR, hi: y - b.y + GRAZE_NEAR };
    for (let i = 0; i < 3; i++) {
      list.push(piece("graze", b.x + 2 + 3 * i, y, 4, 4, c.edge, GRAZE_LIFE, { y0: y, vr: (i - 1) * 8 }));
    }
  } else if (name === "hurt") {
    p.blink = { n: 2, t: 0, lo: -Infinity, hi: Infinity };
    p.knock = 0;
    const fx = ctx.api.fx;
    if (fx && fx.animate(el, "hit")) S.fx.shook += 1;
  } else {
    const socket = b.y + CELL / 2;
    for (let i = 0; i < ORBS; i++) {
      list.push(piece("orb", x, b.y + b.h * 0.875, ORB, ORB, done, ORB_CLIMB,
                      { from: [x, b.y + b.h * 0.875], to: [x, socket], wait: i * ORB_GAP, hide: true }));
    }
    HEART_AT.forEach((at, i) => {
      const hx = b.x + STRIP / 2 + 2 * i;
      HEART.forEach((row, j) => Array.from(row).forEach((m, k) => {
        if (m !== "x") return;
        const px = hx + (k - 2) * 2, py = socket + (j - 1.5) * 2;
        list.push(piece("heart", px, py, 2, 2, done, HEART_END - at,
                        { from: [px, py], to: [px, py - HEART_RISE], wait: at, hide: true }));
      }));
    });
  }
  const repo = /** @type {HTMLElement} */ (pane).dataset.repo || "";
  for (const q of list) q.repo = repo;
  S.fx.played[name] += 1;
  add(list);
  build();
}

function scaleOf(q) {
  if (q.hide && q.t < q.wait) return 0;
  const k = q.pop >= 0 ? Math.max(0, 1 - q.pop / POP_FRAMES) : 1;
  return q.kind === "blast" && q.f <= SWELL_FRAMES ? SWELL * k : k;
}

function pieces(dt) {
  const fx = S.fx;
  if (!fx.pieces.length) return false;
  const vh = S.api ? S.api.viewport.h : window.innerHeight;
  for (const b of fx.blasts) b.dest = destOf(b.how, b.repo);
  const out = [];
  for (const q of fx.pieces) {
    q.f += 1;
    if (q.pop >= 0) {
      q.pop += 1;
      if (q.pop < POP_FRAMES) out.push(q);
      else if (q.kind === "blast" && q.blast.dest) {
        const d = Math.hypot(q.x - q.blast.dest[0], q.y - q.blast.dest[1]);
        fx.ends[d <= LANDED ? "near" : "far"] += 1;
      }
      continue;
    }
    q.t += dt;
    if (q.kind === "blast") blastStep(q, dt);
    else if (q.kind === "break") fallStep(q, dt);
    else if (q.kind === "graze") grazeStep(q);
    else placeStep(q);
    if (q.y - Math.max(q.w, q.h) > vh && !(q.kind === "blast" && q.blast.dest)) continue;
    const due = q.wait !== undefined ? q.t >= q.wait + q.life : q.t >= q.life - POP_FRAMES * FRAME;
    if (due) q.pop = Math.max(q.pop, 0);
    out.push(q);
  }
  fx.pieces = out;
  if (!out.length) fx.blasts = [];
  return out.length > 0;
}

function blastStep(q, dt) {
  if (q.f <= SWELL_FRAMES) return;
  if (q.f === SWELL_FRAMES + 1) {
    const dx = q.x - q.cx, dy = q.y - q.cy, d = Math.hypot(dx, dy) || 1;
    q.vx = dx / d * q.speed;
    q.vy = dy / d * q.speed - 200;
  }
  q.rot += q.vr * dt;
  const dest = q.blast.dest;
  if (q.t < HOME_AT || !dest) {
    q.vy += FALL * dt;
    q.x += q.vx * dt;
    q.y += q.vy * dt;
    return;
  }
  if (q.home === undefined) q.home = q.f;
  const g = Math.min(1, (q.f - q.home + 1) / SHRINK_FRAMES);
  q.w += (CHIP - q.w) * g;
  q.h += (CHIP - q.h) * g;
  const fall = Math.exp(-OMEGA * dt);
  for (const [p, v, o] of [["x", "vx", 0], ["y", "vy", 1]]) {
    const e = q[p] - dest[o], a = q[v] + OMEGA * e;
    q[p] = dest[o] + (e + a * dt) * fall;
    q[v] = (q[v] - OMEGA * a * dt) * fall;
  }
  if (Math.hypot(q.x - dest[0], q.y - dest[1]) <= NEAR) q.pop = 0;
}

function fallStep(q, dt) {
  q.vy += FALL * dt;
  q.x += q.vx * dt;
  q.y += q.vy * dt;
  q.rot += q.vr * dt;
}

function grazeStep(q) {
  const u = Math.min(1, q.t / q.life);
  q.y = q.y0 + GRAZE_FALL * u * u;
  q.rot += q.vr * FRAME;
}

function placeStep(q) {
  const u = Math.max(0, Math.min(1, (q.t - q.wait) / q.life)), e = u * u * (3 - 2 * u);
  q.x = q.from[0] + (q.to[0] - q.from[0]) * e;
  q.y = q.from[1] + (q.to[1] - q.from[1]) * e;
}

function band(tag) {
  const el = document.querySelector(tag), r = el && el.getBoundingClientRect();
  return r && r.width && r.height ? r : null;
}

function lit(box) {
  const g = S.grid;
  if (!g) return;
  const bands = [band("header"), band("footer")].filter(Boolean);
  const i0 = Math.max(0, Math.floor(box.x / GROUND)), i1 = Math.min(g.cols - 1, Math.floor((box.x + box.w) / GROUND));
  const j0 = Math.max(0, Math.floor(box.y / GROUND)), j1 = Math.min(g.rows - 1, Math.floor((box.y + box.h) / GROUND));
  const cells = [];
  let rings = 0;
  for (let j = j0; j <= j1; j++) {
    for (let i = i0; i <= i1; i++) {
      const x = i * GROUND + GROUND / 2, y = j * GROUND + GROUND / 2;
      if (x < box.x || x > box.x + box.w || y < box.y || y > box.y + box.h) continue;
      if (bands.some(r => x >= r.left && x <= r.right && y >= r.top && y <= r.bottom)) continue;
      const ring = Math.min(i - i0, i1 - i, j - j0, j1 - j);
      rings = Math.max(rings, ring);
      cells.push([i, j, ring]);
    }
  }
  if (cells.length) S.fx.flashes.push({ cells, rings, t: 0, f: 0 });
}

function flash(dt) {
  const g = S.grid, fx = S.fx;
  if (!g || !S.ground || !fx.flashes.length) return false;
  const col = S.ground.geometry.getAttribute("aColor"), heal = FX_LIFE - FLASH_FRAMES * FRAME;
  const level = new Map();
  for (const f of fx.flashes) {
    f.f += 1;
    f.t += dt;
    for (const [i, j, ring] of f.cells) {
      const at = FLASH_FRAMES * FRAME + heal * (ring + 1) / (f.rings + 1);
      const k = f.f <= FLASH_FRAMES ? FLASH_UP : f.t < at ? FLASH_DOWN : 1;
      const n = j * g.cols + i;
      if (!level.has(n) || k !== 1) level.set(n, k);
    }
  }
  for (const [n, k] of level) {
    const c = shade(g.base, k === 1 ? jitter(n % g.cols, Math.floor(n / g.cols)) : k);
    col.setXYZ(n, c[0], c[1], c[2]);
  }
  col.needsUpdate = true;
  fx.flashes = fx.flashes.filter(f => f.t < FX_LIFE);
  return fx.flashes.length > 0;
}

function schedule() {
  const running = Array.from(S.panes.values()).some(p => p.stack.state === "running");
  if (!running || !S.api || S.api.reduced) {
    if (S.timer) clearTimeout(S.timer);
    S.timer = 0;
    return;
  }
  if (S.timer) return;
  S.timer = setTimeout(() => {
    S.timer = 0;
    if (!S.api) return;
    for (const p of S.panes.values()) if (p.stack.state === "running") p.stack.turning = TURN_FOR;
    S.api.request();
  }, TURN_EVERY * 1000);
}

export function inspect() {
  const count = m => (m ? m.count : 0);
  const panes = Array.from(S.panes.values()).map(p => ({
    repo: p.el.dataset.repo || "", slot: p.slot, w: p.w, h: p.h,
    at: S.uPane[p.slot] ? [S.uPane[p.slot].x, -S.uPane[p.slot].y, S.uPane[p.slot].z] : null,
    stack: Object.assign({ level: LEVEL[p.stack.state] || 2 }, p.stack),
    blink: p.blink ? p.blink.n : 0, knock: knockOf(p),
  }));
  const meshes = [S.ground, S.slabs, S.stacks].filter(Boolean);
  return {
    on: !!S.api,
    meshes: meshes.map(m => ({ instanced: !!m.isInstancedMesh, count: m.count, material: m.material.uuid })),
    materials: new Set(meshes.map(m => m.material.uuid)).size,
    instances: { ground: count(S.ground), slabs: count(S.slabs), stacks: count(S.stacks) },
    drawCalls: S.drawCalls,
    builds: S.builds,
    timer: !!S.timer,
    panel: S.tokens ? surfaces(S.tokens).panel : null,
    tones: S.tokens ? Object.fromEntries(["done", "human", "waiting", "idle"].map(k => [k, S.tokens[k]])) : null,
    memory: S.renderer ? Object.assign({}, S.renderer.info.memory) : null,
    panes,
    fx: {
      live: S.fx.pieces.length, played: Object.assign({}, S.fx.played), ends: Object.assign({}, S.fx.ends),
      shook: S.fx.shook,
      flashes: S.fx.flashes.length, dest: S.fx.dest ? S.fx.dest.slice() : null,
      pieces: S.fx.pieces.slice(0, 64).map(q => ({ kind: q.kind, repo: q.repo || "", x: q.x, y: q.y, s: Math.max(q.w, q.h) * scaleOf(q),
                                                   c: q.c.slice(), bevel: 0, spin: "z" })),
    },
  };
}
