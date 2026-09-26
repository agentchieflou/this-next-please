const FOUND = ".tile .transcript li:is(.denied, .friction)";

export function marks() {
  return [
    { selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -5 },
    { selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" },
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" },
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves: "erased" },
    { selector: ".tile .asks:not([hidden]) .ask:not([hidden]) .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile .asks:not([hidden]) .ask:not([hidden]) .ask-choice:not([aria-pressed=\"true\"])",
      tool: "pencil", shape: "loop" },
    { selector: ".tile .ask:not([hidden]) .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "ellipse" },
    { selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },
    { selector: ".tile.state-error", tool: "red", shape: "bang" },
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".runline" },
    { selector: ".tile:has(.oldsession:not([hidden]))", tool: "pencil", shape: "outline", pad: -8, dash: true },
    { selector: FOUND, tool: "red", shape: "ellipse", pad: -4 },
    { selector: FOUND + " .k", tool: "highlighter", shape: "lines" },
    { selector: FOUND + " .v", tool: "pencil", shape: "write" },
    { selector: "#bellcount", tool: "pen", shape: "write" },
  ];
}

export const options = { paper: "--paper", hand: true, speed: 1 };

export const sampleGround = false;

const IDLE = ".tile.state-idle";
const AGED = ".chip.stale";

const ERROR_ROW = ".tile.state-error";
const RUNNING_ROW = ".tile.state-running .head .repo";

const SOAK_PX = 180;
const SOAK_S = 0.7;

const RAIL_BELOW = 90;

function parse(css, fallback) {
  const s = String(css || "").trim();
  let m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s);
  if (m) {
    const h = m[1].length === 3 ? m[1].replace(/./g, c => c + c) : m[1];
    return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255).concat(1);
  }
  m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+))?\s*\)$/i.exec(s);
  if (m) return [m[1] / 255, m[2] / 255, m[3] / 255, m[4] === undefined ? 1 : Number(m[4])];
  return fallback;
}

function read(tokens, name, fallback) {
  return parse(tokens.css(name), fallback.length === 4 ? fallback : fallback.concat(1));
}

const QUILT = `
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
const float QS = 26.0;
/* 0 on a seam, 0.5 in the middle of a pillow. */
float toSeam(vec2 p) {
  vec2 q = vec2(p.x + p.y, p.x - p.y) / QS;
  vec2 f = abs(fract(q) - 0.5);
  return 0.5 - max(f.x, f.y);
}
/* How pressed-in the paper is here: 1 in a seam, 0 on a pillow. */
float seam(vec2 p) { return 1.0 - smoothstep(0.0, 0.075, toSeam(p)); }
/* The paper's height: pillows puffed between the seams, a fine dot emboss on each, and fibre. */
float quilt(vec2 p) {
  float pillow = smoothstep(0.0, 0.24, toSeam(p));
  vec2 d = fract(p / 5.0) - 0.5;
  float dots = 1.0 - smoothstep(0.12, 0.3, length(d));
  return pillow * 0.9 + dots * pillow * 0.12 + vnoise(p * 0.7) * 0.05;
}`;

const VS = `
varying vec2 vPage; varying vec2 vLocal;
void main() {
  vec4 w = modelMatrix * vec4(position, 1.0);
  vPage = vec2(w.x, -w.y);
  vLocal = vec2(position.x, -position.y);
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const PAPER_FS = `
uniform vec3 uPaper; uniform vec3 uSeam;
varying vec2 vPage; varying vec2 vLocal;
${QUILT}
void main() {
  vec2 p = vPage;
  float h = quilt(p);
  vec3 n = normalize(vec3((quilt(p - vec2(0.9, 0.0)) - quilt(p + vec2(0.9, 0.0))) * 1.6,
                          (quilt(p + vec2(0.0, 0.9)) - quilt(p - vec2(0.0, 0.9))) * 1.6, 1.0));
  vec3 L = normalize(vec3(-0.45, 0.55, 0.9));
  float lit = dot(n, L) - L.z;
  float dark = clamp(seam(p) * 0.8 + max(0.0, -lit) * 2.2 + (1.0 - h) * 0.12, 0.0, 1.0);
  vec3 c = mix(uPaper, uSeam, dark);
  c = mix(c, vec3(1.0), clamp(lit, 0.0, 1.0) * 0.35);
  gl_FragColor = vec4(c, 1.0);
}`;

const RING_FS = `
uniform vec4 uCoffee; uniform vec2 uC; uniform float uR; uniform float uSeed;
varying vec2 vPage; varying vec2 vLocal;
${QUILT}
void main() {
  vec2 d = vLocal - uC;
  float r = length(d), a = atan(d.y, d.x);
  float wob = (vnoise(vec2(a * 2.6 + uSeed, uSeed * 1.7)) - 0.5) * 3.2;
  float rim = 1.0 - smoothstep(0.5, 2.2, abs(r - uR - wob));
  rim *= 0.75 + 0.25 * vnoise(vec2(a * 9.0, uSeed));
  float inside = (1.0 - smoothstep(uR - 3.0, uR, r + wob)) * (0.16 + 0.14 * vnoise(vLocal / 11.0 + uSeed));
  vec2 d2 = d - vec2(uR * 0.16, -uR * 0.12);
  float arc = smoothstep(0.1, 0.7, sin(atan(d2.y, d2.x) + uSeed * 3.0));
  float rim2 = (1.0 - smoothstep(0.4, 1.6, abs(length(d2) - uR * 0.98))) * arc * 0.55;
  float k = clamp(max(rim, rim2) + inside, 0.0, 1.0);
  if (k < 0.004) discard;
  gl_FragColor = vec4(uCoffee.rgb, k * uCoffee.a);
}`;

const BLEED_FS = `
uniform vec3 uInk; uniform vec2 uSize; uniform float uO; uniform float uRad;
uniform float uHead; uniform float uTail; uniform float uLen;
varying vec2 vPage; varying vec2 vLocal;
${QUILT}
/* The nearest point of the loop to \`p\`: its distance, and how far along the loop it is. */
vec2 onLoop(vec2 p) {
  float L = -uO, T = -uO, R = uSize.x + uO, B = uSize.y + uO, rad = uRad;
  float wT = (R - L) - 2.0 * rad, hS = (B - T) - 2.0 * rad, q = 1.5707963 * rad;
  float s0 = 4.0;                                     // the loop begins 4px past the corner
  vec2 best = vec2(1e9, 0.0);
  float x, d, s;
  // top, left to right
  x = clamp(p.x, L + rad, R - rad); d = length(p - vec2(x, T)); s = x - (L + rad) - s0;
  if (d < best.x) best = vec2(d, s);
  // right, top to bottom
  x = clamp(p.y, T + rad, B - rad); d = length(p - vec2(R, x)); s = wT + q + (x - (T + rad)) - s0;
  if (d < best.x) best = vec2(d, s);
  // bottom, right to left
  x = clamp(p.x, L + rad, R - rad); d = length(p - vec2(x, B)); s = wT + 2.0 * q + hS + ((R - rad) - x) - s0;
  if (d < best.x) best = vec2(d, s);
  // left, bottom to top
  x = clamp(p.y, T + rad, B - rad); d = length(p - vec2(L, x)); s = 2.0 * wT + 3.0 * q + hS + ((B - rad) - x) - s0;
  if (d < best.x) best = vec2(d, s);
  // the four corners, each a quarter circle, in the order the pen goes round them
  vec2 cs[4]; cs[0] = vec2(R - rad, T + rad); cs[1] = vec2(R - rad, B - rad); cs[2] = vec2(L + rad, B - rad); cs[3] = vec2(L + rad, T + rad);
  float starts[4]; starts[0] = wT; starts[1] = wT + q + hS; starts[2] = 2.0 * wT + 2.0 * q + hS; starts[3] = 2.0 * wT + 3.0 * q + 2.0 * hS;
  float a0[4]; a0[0] = -1.5707963; a0[1] = 0.0; a0[2] = 1.5707963; a0[3] = 3.1415927;
  for (int i = 0; i < 4; i++) {
    vec2 v = p - cs[i];
    float a = atan(v.y, v.x) - a0[i];
    a = mod(a + 3.1415927, 6.2831853) - 3.1415927;
    float t = clamp(a, 0.0, 1.5707963);
    vec2 on = cs[i] + rad * vec2(cos(a0[i] + t), sin(a0[i] + t));
    d = length(p - on);
    s = starts[i] + t * rad - s0;
    if (d < best.x) best = vec2(d, s);
  }
  if (best.y < 0.0) best.y += uLen;                  // the few px before the start close the loop
  return best;
}
void main() {
  vec2 hit = onLoop(vLocal);
  float drawn = step(hit.y, uHead);
  if (drawn < 0.5) discard;
  float soak = clamp((uHead - hit.y) / ${SOAK_PX.toFixed(1)} + uTail, 0.0, 1.0);
  float sm = seam(vPage);
  float reach = 2.0 + soak * (1.5 + 11.0 * sm) * (0.75 + 0.5 * vnoise(vPage * 0.45));
  float a = (1.0 - smoothstep(2.0, reach, hit.x)) * (0.12 + 0.45 * sm) * soak;
  if (a < 0.004) discard;
  gl_FragColor = vec4(uInk, a);
}`;

const panes = new Map();
const soaks = new WeakMap();

function seedOf(repo) {
  let h = 2166136261;
  for (const c of String(repo || "")) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return ((h >>> 0) % 1000) / 1000;
}

function shader(THREE, fs, uniforms, transparent) {
  return new THREE.ShaderMaterial({
    vertexShader: VS, fragmentShader: fs, uniforms, transparent: !!transparent,
    depthTest: false, depthWrite: false,
  });
}

function quad(THREE, x0, y0, x1, y1, material, order) {
  const g = new THREE.PlaneGeometry(x1 - x0, y1 - y0);
  g.translate((x0 + x1) / 2, -(y0 + y1) / 2, 0);
  const m = new THREE.Mesh(g, material);
  m.renderOrder = order;
  m.frustumCulled = false;
  return m;
}

export function paper({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const p = read(tokens, "--paper", tokens.bg), s = read(tokens, "--paper-seam", tokens.line);
  const mat = shader(THREE, PAPER_FS, {
    uPaper: { value: new THREE.Vector3(p[0], p[1], p[2]) },
    uSeam: { value: new THREE.Vector3(s[0], s[1], s[2]) },
  });
  scene.add(quad(THREE, 0, 0, w, h, mat, api.order.paper));
}

function loopLength(w, h, o, rad) {
  const W = w + 2 * o, H = h + 2 * o;
  rad = Math.max(1, Math.min(rad, W / 3, H / 3));
  return { len: 2 * (W - 2 * rad) + 2 * (H - 2 * rad) + 2 * Math.PI * rad, rad };
}

export function frame({ THREE, scene, tokens, api }, el, box) {
  const rail = box.w < RAIL_BELOW;
  const seed = seedOf(el.dataset.repo);

  const coffee = read(tokens, "--coffee", tokens.muted.concat(0.14));
  const R = rail ? Math.max(12, box.w * 0.36) : Math.min(46, Math.max(24, Math.min(box.w, box.h) * 0.18));
  const c = rail ? [box.w * 0.5, box.h * 0.6]
                 : [box.w - R - 26 - seed * 40, Math.min(box.h - R - 90, box.h * 0.55 + seed * 60)];
  const ring = quad(THREE, c[0] - R - 8, c[1] - R - 8, c[0] + R + 8, c[1] + R + 8, shader(THREE, RING_FS, {
    uCoffee: { value: new THREE.Vector4(coffee[0], coffee[1], coffee[2], coffee[3]) },
    uC: { value: new THREE.Vector2(c[0], c[1]) }, uR: { value: R }, uSeed: { value: seed * 6.28 },
  }, true), api.order.frame);
  ring.name = "coffee";

  const o = 3 - 7, loop = loopLength(box.w, box.h, o, 7);
  const ink = tokens.inks.marker || tokens.human;
  const reach = o + 18;
  const bleed = quad(THREE, -reach, -reach, box.w + reach, box.h + reach, shader(THREE, BLEED_FS, {
    uInk: { value: new THREE.Vector3(ink[0], ink[1], ink[2]) },
    uSize: { value: new THREE.Vector2(box.w, box.h) }, uO: { value: o }, uRad: { value: loop.rad },
    uHead: { value: 0 }, uTail: { value: 0 }, uLen: { value: loop.len },
  }, true), api.order.frame + 1);
  bleed.name = "bleed";

  const pen = tokens.inks.pen || tokens.accent;
  const dot = new THREE.Mesh(new THREE.CircleGeometry(2.3, 14), new THREE.MeshBasicMaterial({
    color: new THREE.Color().setRGB(pen[0], pen[1], pen[2], THREE.SRGBColorSpace),
    transparent: true, depthTest: false, depthWrite: false,
  }));
  dot.renderOrder = api.order.frame + 2;
  dot.frustumCulled = false;
  dot.name = "pentip";

  for (const m of [ring, bleed, dot]) { m.visible = false; scene.add(m); }
  const rec = { el, group: scene, ring, bleed, dot, len: loop.len, centre: c, radius: R };
  panes.set(el, rec);
  show(rec, api, markOf(), 0);
}

function markOf() {
  const out = new Map();
  const ink = globalThis.Ink;
  const layer = ink && typeof ink.inspect === "function" ? ink.inspect().layer : null;
  if (!layer) return out;
  for (const m of layer.marks) {
    if (m.strikeOf || !m.lane.startsWith("pane:")) continue;
    const repo = m.lane.slice(5);
    const at = out.get(repo) || {};
    if (m.selector === ERROR_ROW && m.tool === "marker") at.loop = m;
    if (m.selector === RUNNING_ROW && m.tool === "pen") at.line = m;
    out.set(repo, at);
  }
  return out;
}

function show(rec, api, marks, dt) {
  const { el, ring, bleed, dot } = rec;
  const at = marks.get(el.dataset.repo) || {};

  ring.visible = el.matches(IDLE) && !!el.querySelector(AGED);

  let soaking = false;
  const loop = at.loop;
  if (loop && loop.drawn > 0) {
    const s = soaks.get(el) || { tail: 0 };
    const head = loop.drawn * loop.len;
    if (loop.drawn >= 1) s.tail = api.reduced ? 1 : Math.min(1, s.tail + dt / SOAK_S);
    soaks.set(el, s);
    bleed.material.uniforms.uHead.value = head;
    bleed.material.uniforms.uLen.value = rec.len;
    bleed.material.uniforms.uTail.value = s.tail;
    bleed.visible = true;
    soaking = s.tail < 1;
  } else {
    soaks.delete(el);
    bleed.visible = false;
  }

  const line = at.line;
  if (line && (line.drawn >= 1 || line.state === "struck")) {
    const r = el.getBoundingClientRect();
    dot.position.set(line.box.x - r.left + line.box.w + 8, -(line.box.y - r.top + line.box.h + 2.2), 0);
    dot.visible = true;
  } else {
    dot.visible = false;
  }
  return soaking;
}

export function tick({ api }, dt) {
  const marks = markOf();
  let more = false;
  for (const [el, rec] of Array.from(panes)) {
    if (!rec.group.parent || !el.isConnected || !rec.ring.parent) {
      panes.delete(el);
      continue;
    }
    if (show(rec, api, marks, dt)) more = true;
  }
  return more;
}

export function dispose() {
  panes.clear();
}

export function inspect() {
  const out = {};
  for (const [el, rec] of panes) {
    if (!rec.group.parent || !rec.ring.parent) continue;
    const u = rec.bleed.material.uniforms;
    out[el.dataset.repo] = {
      coffee: rec.ring.visible, ring: { x: rec.centre[0], y: rec.centre[1], r: rec.radius },
      bleed: rec.bleed.visible, head: u.uHead.value, tail: u.uTail.value, loop: rec.len,
      pentip: rec.dot.visible, tip: { x: rec.dot.position.x, y: -rec.dot.position.y },
    };
  }
  return out;
}
