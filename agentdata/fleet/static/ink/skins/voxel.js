const MARKS = [
  { selector: ".tile.needs-human .head .repo", tool: "marker", shape: "underline" },
  { selector: ".tile.state-error", tool: "red", shape: "bang" },
  { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
  { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", dash: true, pad: 0 },
  { selector: ".tile .ask-choice[aria-pressed=\"true\"]", tool: "green", shape: "loop", pad: 2 },
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
};

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
  const base = surfaces(tokens).ground, put = writer(THREE, S.ground);
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
  S.stacks = mesh(THREE, SLOTS * PER_STACK, api.order.paper + 1);
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
    p = { el, group: ctx.scene, slot, w: 0, h: 0, stack: fresh() };
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
  const more = stacks(dt, moved);
  schedule();
  return more;
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
    put.put(slot, w / 2, h / 2 + DROP, w, h, 6, 0, c.edge);
    put.put(slot, STRIP + (w - STRIP) / 2, h / 2, w - STRIP, h, 12, EDGE, c.panel);
    for (let k = 0; k < SOCKETS; k++) {
      put.put(slot, STRIP / 2, k * CELL + CELL / 2, STRIP, CELL, 4, 1, shade(c.edge, 1.6));
    }
    const n = stripCubes(h), top = SOCKETS * CELL, step = (h - top) / n;
    for (let k = 0; k < n; k++) {
      put.put(slot, STRIP / 2, top + k * step + step / 2, STRIP, step, STRIP, 2,
              shade(c.accent, jitter(slot, k) * 0.9));
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
    const x = STRIP / 2;
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
  put.done();
  return moving;
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
    memory: S.renderer ? Object.assign({}, S.renderer.info.memory) : null,
    panes,
  };
}
