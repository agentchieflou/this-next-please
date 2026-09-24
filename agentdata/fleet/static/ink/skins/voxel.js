/* Voxel on three.js (#256, slice J of the ink epic #246): the depth the CSS skin (#156) faked with
   inset shadows and an SVG sprite, made real. `docs/skin-voxel.md` is the page this implements;
   `static/skins/voxel/skin.css` keeps the surfaces this reads and the room the page leaves for what it
   draws; under `body.ink-off` voxel is the one plain look every skin shares (#257).

   WHAT IS DRAWN. Three materials, and so three draw calls, however many agents there are:

   * the ground -- the dirt (netherrack, endstone) as a floor of 32px voxels, one instance each;
   * the slabs -- each pane's frame: the panel block the text is read on (its face is exactly the
     variant's composited panel, `--voxel-panel`, so theme.check's pair is the rendered colour),
     its drop shadow, the accent strip down its left edge as a column of cubes, and the three
     sockets at the top of that strip the status stack sits in;
   * the stacks -- per pane, a stack of up to three blocks in those sockets, showing the pane's
     state (§the grammar in docs/skin-voxel.md): running turns the top block a quarter at a time,
     needs you raises it, an error cracks it, done sets the stack full. A stale session leaves a
     pebble on top, and a finding in the transcript an ore fleck in the bottom block.

   ONE DRAW CALL PER MATERIAL. Every voxel of a material is an instance of one InstancedMesh. A
   pane's voxels are built in the pane's own coordinates and carry the pane's slot; where the pane
   is now is a uniform (`uPane[slot]`), written in the mesh's `onBeforeRender` from the group the
   layer put at the pane's top-left. So a gutter drag moves every slab by rewriting a few
   uniforms, inside the frame the browser laid out (the layer's ResizeObserver path), and only a
   pane that changes size rebuilds its instances -- in `frame`, which the layer calls then.

   THE DOM IS THE TRUTH. The stack is read from classes `app.js` already sets: `state-<state>`
   and `needs-human` on the pane, `.oldsession` not hidden, `.transcript li.friction` /
   `li.denied`. Nothing here sets a class or writes the page.

   DRAWN, NEVER FADED. Marks come from the table below and the layer draws them. The materials may
   animate -- a block turning, rising, settling -- and under reduced motion they are simply where
   they end up. An idle desk with no agent running asks for no frame at all.

   No static import (the run token), no hex in this file (colours are `tokens`, or the skin's own
   custom properties read through `tokens.css`), no markup. */

/* ------------------------------------------------------------------------------ the mark table

   The state grammar's marks. Each row's selector is a class or attribute the page already sets. */
const MARKS = [
  // needs you: the name underlined in marker. The stack's block rises too.
  { selector: ".tile.needs-human .head .repo", tool: "marker", shape: "underline" },
  // error: a bang in the pane's margin (#330). The stack's block cracks.
  { selector: ".tile.state-error", tool: "red", shape: "bang" },
  // done: a green check in the pane's margin (#330). The stack is set full. `is-done` is the fold's word
  // for a finished agent nothing supervises, whose chip says idle (#253, #333).
  { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
  // stale (#240): the old-session chip outlined in dashed pencil. A pebble on the stack.
  { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", dash: true, pad: 0 },
  // answered: the choice pressed in the question card, looped in green.
  { selector: ".tile .ask-choice[aria-pressed=\"true\"]", tool: "green", shape: "loop", pad: 2 },
  // a finding: the line where the agent stopped or was refused, underlined in red. Ore in the stack.
  { selector: ".tile .transcript li.friction .v, .tile .transcript li.denied .v", tool: "red", shape: "underline" },
];

/* Every variant draws the same grammar: a state means the same thing in every world (#4). */
export function marks() {
  return MARKS.map(r => Object.assign({}, r));
}

export const options = { hand: true, speed: 1 };

/* ---------------------------------------------------------------------------------- the sizes */

const GROUND = 32;            // one ground voxel, the CSS skin's 8px art at 4x
const STRIP = 10;             // the pane's left border, where the accent strip and the stack live
const CELL = 10;              // one stack block
const SOCKETS = 3;            // the stack's height, in blocks
const EDGE = 2;               // the pane's other borders: the slab's bevel
const DROP = 4;               // the drop shadow under a pane
const LIFT = 5;               // how far "needs you" raises the top block
const TURN_EVERY = 3;         // seconds between a running block's quarter turns
const TURN_FOR = 0.6;         // seconds a quarter turn takes
const SLOTS = 64;             // panes a desk can frame at once; slot 0 is the page itself
const PER_STACK = 6;          // blocks 0-2, the crack's other half, the pebble, the ore

/* The one light: from the top left and in front, the direction the layer's own sun comes from. */
const LIGHT = (() => {
  const v = [-0.45, 0.55, 0.9], n = Math.hypot(v[0], v[1], v[2]);
  return v.map(x => x / n);
})();

/* ------------------------------------------------------------------------------ the one shader

   A voxel is a box with a chamfered face: the face inset by `bevel`, four 45-degree bevels round
   it, the sides and the back. Its size is per instance (`aSize`, `aBevel`) and built here in the
   shader, so a bevel is the same number of pixels on a 10px cube and on a 900px panel. Shading is
   relative to the face: a face turned square to the camera is exactly its colour, so the panel's
   face is the colour theme.check measured; a bevel towards the light is lighter, one away darker.
   Colours are passed through as the page's sRGB -- no colour-space conversion -- for that reason. */
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

/* The template voxel: `position` is (x sign, y sign, ring) -- ring 0 the inset face, 1 the outer
   rim at the bevel's foot, 2 the back -- and each face its own flat normal. Wound by checking each
   quad against its normal on a reference box, so no face is culled by a slip of the pen. */
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
    // (ax, ay) is the side's outward direction, (bx, by) runs along it.
    const c = (s, k) => [ax + bx * s, ay + by * s, k];
    quad([c(-1, 0), c(1, 0), c(1, 1), c(-1, 1)], [ax * r2, ay * r2, r2]);      // the bevel
    quad([c(-1, 1), c(1, 1), c(1, 2), c(-1, 2)], [ax, ay, 0]);                // the side
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("normal", new THREE.Float32BufferAttribute(nor, 3));
  return g;
}

/* ------------------------------------------------------------------------------- colours */

/* A colour the page wrote, `#rgb`, `#rrggbb` or `rgb(...)`, as [r, g, b] in 0-1; null if none. */
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

/* The skin's own surfaces, from its stylesheet (`--voxel-*`), each falling back to a palette token
   so a variant that forgot one still draws. */
function surfaces(tokens) {
  const own = (name, fallback) => parse(tokens.css(name)) || fallback;
  return {
    ground: own("--voxel-ground", tokens.bg),
    panel: own("--voxel-panel", tokens.panel),
    edge: own("--voxel-edge", shade(tokens.bg, 0.4)),
    accent: tokens.accent,
  };
}

/* A voxel's shade among its neighbours: the texture the CSS art drew in four browns. */
function jitter(i, j) {
  let h = Math.imul(i * 374761393 + j * 668265263, 1274126177);
  h ^= h >>> 13;
  return [0.84, 0.92, 1, 1, 1.08][(h >>> 0) % 5];
}

/* ------------------------------------------------------------------------------ the state */

const S = {
  THREE: null, api: null, tokens: null, renderer: null,
  ground: null, slabs: null, stacks: null,
  panes: new Map(),                   // pane element -> {el, group, slot, w, h, stack}
  slots: new Array(SLOTS).fill(null), // slot -> pane element (slot 0 is the page)
  uPane: [],                          // the uniform array, shared by the three materials
  dirty: false,                       // the slabs' instances want building again
  timer: 0, turnAt: 0,
  drawCalls: 0,                       // what the renderer counted in the last back pass
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

/* One InstancedMesh with room for `n` voxels, its per-voxel attributes beside the matrix. */
function mesh(THREE, n, order) {
  const g = template(THREE);
  g.setAttribute("aSize", new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3));
  g.setAttribute("aBevel", new THREE.InstancedBufferAttribute(new Float32Array(n), 1));
  g.setAttribute("aColor", new THREE.InstancedBufferAttribute(new Float32Array(n * 3), 3));
  g.setAttribute("aPane", new THREE.InstancedBufferAttribute(new Float32Array(n), 1));
  const m = new THREE.InstancedMesh(g, material(THREE), n);
  m.count = 0;
  m.frustumCulled = false;          // the instances are placed in the shader
  m.renderOrder = order;
  return m;
}

/* A writer over a mesh's instances, from index 0. */
function writer(THREE, m) {
  const g = m.geometry, M = new THREE.Matrix4();
  const size = g.getAttribute("aSize"), bev = g.getAttribute("aBevel");
  const col = g.getAttribute("aColor"), pane = g.getAttribute("aPane");
  let i = 0;
  return {
    get n() { return i; },
    /* A voxel `w` x `h` x `d` centred on (x, y) px down the page -- y is drawn at -y. */
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

/* ------------------------------------------------------------------------------- the hooks */

function remember({ THREE, tokens, api }) {
  S.THREE = THREE;
  S.tokens = tokens;
  S.api = api;
  S.renderer = api.renderer;
  if (!S.uPane.length) S.uPane = vec4s(THREE);
}

/* The floor: a voxel every 32px over the whole viewport, rebuilt on a resize or a palette change. */
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

/* The slabs and the stacks: two meshes over the paper, filled from the panes the frames hook has
   met. Called on the skin's arrival, a resize and a palette change; the panes are kept across. */
export function paper(ctx) {
  remember(ctx);
  const { THREE, scene, api } = ctx;
  if (S.slabs) S.slabs.dispose();
  if (S.stacks) S.stacks.dispose();
  S.slabs = mesh(THREE, capacity(), api.order.paper);
  S.stacks = mesh(THREE, SLOTS * PER_STACK, api.order.paper + 1);
  // Where the panes are, written just before the slabs draw: the layer has put each pane's group
  // at its top-left by then, in this same frame.
  S.slabs.onBeforeRender = place;
  // The renderer's own count of this back pass, taken after its last draw: the test's
  // "one draw call per material" reads the renderer, not this file's opinion of itself.
  S.stacks.onAfterRender = renderer => { S.drawCalls = renderer.info.render.calls; };
  scene.add(S.slabs, S.stacks);
  build();
  stacks(0, true);
}

/* One pane's frame. Nothing is drawn into the pane's own group -- that would be a draw call per
   pane -- it is remembered, and its voxels are built into the shared slabs. */
export function frame(ctx, el, box) {
  remember(ctx);
  let p = S.panes.get(el);
  if (!p) {
    const slot = S.slots.indexOf(null, 1);
    if (slot < 0) return;            // more panes than slots: the rest are framed by CSS alone
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

/* Every frame the layer draws: the stacks follow the page's classes, and a block that is turning,
   rising or settling asks for the next frame. */
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

/* ------------------------------------------------------------------------------- the slabs */

function stripCubes(h) {
  return Math.max(1, Math.round((h - SOCKETS * CELL) / CELL));
}

function capacity() {
  let n = 0;
  for (const p of S.panes.values()) n += 2 + SOCKETS + stripCubes(p.h);
  return Math.max(256, n * 2);
}

/* Panes the layer has let go of: their groups are no longer on the paper. */
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

/* Every pane's frame, in its own coordinates: its shadow, its panel, its sockets and its strip. */
function build() {
  if (!S.slabs || !S.tokens) return;
  const need = capacity();
  if (need > S.slabs.instanceMatrix.count) {
    // A desk that grew past the room: a bigger mesh in the same place.
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
    put.put(slot, w / 2, h / 2 + DROP, w, h, 6, 0, c.edge);                       // the shadow
    put.put(slot, STRIP + (w - STRIP) / 2, h / 2, w - STRIP, h, 12, EDGE, c.panel);  // the panel
    for (let k = 0; k < SOCKETS; k++) {                                          // the sockets
      put.put(slot, STRIP / 2, k * CELL + CELL / 2, STRIP, CELL, 4, 1, shade(c.edge, 1.6));
    }
    const n = stripCubes(h), top = SOCKETS * CELL, step = (h - top) / n;
    for (let k = 0; k < n; k++) {                                               // the strip
      put.put(slot, STRIP / 2, top + k * step + step / 2, STRIP, step, STRIP, 2,
              shade(c.accent, jitter(slot, k) * 0.9));
    }
  }
  put.done();
  S.builds += 1;
}

/* The panes' offsets, from the groups the layer placed. Uniforms are uploaded after this, in the
   draw it precedes, so the slabs are where the panes are on the frame that shows the panes. */
function place() {
  for (const p of S.panes.values()) {
    const g = p.group, on = !!(g.parent && g.visible && p.el.isConnected);
    S.uPane[p.slot].set(g.position.x, g.position.y, on ? 1 : 0, 0);
  }
}

/* ------------------------------------------------------------------------------- the stacks

   A pane's stack, from its classes. `level` is how many blocks are in the sockets: one while it
   is idle, two while a turn is in hand, three when it is done. The top block wears the state's
   colour, and its response -- turned, raised, cracked -- is what reads at a glance. */

const LEVEL = { idle: 1, starting: 1, done: 3 };
const TONE = { running: "running", waiting_approval: "waiting", needs_human: "human", blocked: "human",
               error: "human", done: "done", idle: "idle", starting: "idle" };

function fresh() {
  return { state: "", needs: false, stale: false, finding: false, lift: 0, turn: 0, turning: 0 };
}

/* What the page says of this pane now. True when anything changed. */
function read(p) {
  const el = p.el, st = p.stack;
  let state = "idle";
  for (const c of el.classList) if (c.startsWith("state-")) state = c.slice(6);
  // A finished agent nothing supervises: the chip says idle, the fold says done (#333).
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

/* Every stack's voxels, moved on by `dt`. True while a block is still on its way. */
function stacks(dt, changed) {
  if (!S.stacks || !S.tokens) return false;
  const reduced = !!(S.api && S.api.reduced);
  let moving = false;
  for (const p of S.panes.values()) {
    const st = p.stack;
    const want = st.needs ? LIFT : 0;
    if (reduced) st.lift = want;
    else if (st.lift !== want) {
      const v = 40 * dt;                          // px a second: a block, not a jump
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
    const cy = k => (SOCKETS - 1 - k) * CELL + CELL / 2;     // block k from the bottom
    const x = STRIP / 2;
    for (let k = 0; k < SOCKETS; k++) {
      const top = k === level - 1;
      if (k >= level || !p.w) { put.put(slot, 0, 0, 0, 0, 0, 0, low); continue; }
      if (!top) { put.put(slot, x, cy(k), CELL, CELL, CELL, 2, low); continue; }
      const y = cy(k) - st.lift;
      const ease = st.turning > 0 ? 1 - st.turning / TURN_FOR : 0;
      const turn = ease * ease * (3 - 2 * ease) * Math.PI / 2;
      if (st.state === "error") {
        // Cracked: two halves, pulled a pixel apart and knocked off square.
        put.put(slot, x - 2.6, y, CELL / 2 - 0.6, CELL, CELL, 1, tone, 0, 0.14);
      } else {
        put.put(slot, x, y, CELL, CELL, CELL, 2, tone, turn);
      }
    }
    const topY = cy(level - 1) - st.lift;
    if (st.state === "error" && p.w) put.put(slot, x + 2.6, topY + 0.8, CELL / 2 - 0.6, CELL, CELL, 1, tone, 0, -0.18);
    else put.put(slot, 0, 0, 0, 0, 0, 0, tone);
    // Stale: a pebble on top. A finding: an ore fleck in the bottom block.
    put.put(slot, x + 1, topY - CELL / 2 - 1.5, st.stale && p.w ? 4 : 0, 3, 4, 0.5, S.tokens.muted);
    put.put(slot, x - 1.5, cy(0) + 1.5, st.finding && p.w ? 3 : 0, 3, CELL + 2, 0.5, S.tokens.human);
  }
  put.done();
  return moving;
}

/* A running block turns a quarter every few seconds. Between turns the desk draws nothing: the
   next turn is one timer, and a request for a frame when it comes -- never a loop. */
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

/* ------------------------------------------------------------------------------ for the tests

   What is on the paper, as the renderer and this module see it. The layer's `Ink.inspect()` shows
   the marks; this shows the materials. */
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
