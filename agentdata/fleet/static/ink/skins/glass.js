export const MESH = [
  { at: [0.16, 0.10], r: [0.60, 0.55] },
  { at: [0.84, 0.82], r: [0.55, 0.50] },
  { at: [0.58, 0.42], r: [0.45, 0.40] },
];
const BLOB_END = 1.0;
const DRIFT = 0.035;
const LAPS = [97, 131, 113];
const WAVE_H = 9;
const WAVE_L = [760, 540, 980];
const WAVE_T = [41, 53, 67];
const LIGHT = 0.3;
const GROUND_FPS = 30;
const GROUND_MAX_MS = 500;
const BLUR = 18;
const SATURATE = 1.4;
const MARGIN = 44;
const SHADOW_Y = 12;
const SHADOW_BLUR = 32;
const RIM_IN = 0.6;
const RIM_OUT = 0.45;
const RUN_LAP = 4.5;

export function marks() {
  return [
    { selector: ".tile.needs-human .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .asks:not([hidden]) .ask:not([hidden]) .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "loop", pad: 3 },
    { selector: ".tile.state-running .chip", tool: "pen", shape: "underline" },
    { selector: ".tile.state-error", tool: "marker", shape: "bang" },
    { selector: ".tile.state-blocked", tool: "marker", shape: "bang" },
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    { selector: ".tile .scopereport.outside:not([hidden])", tool: "red", shape: "ellipse", pad: 2 },
  ];
}

export const options = { hand: false, speed: 1 };

export const sampleGround = true;

let mesh = null;
const panes = new Map();
let timer = 0;
let gap = 1000 / GROUND_FPS;
let asked = 0;
let clock = 0;
let lastNow = 0;
let painted = "";
let frames = 0;
let requestFrame = null;
let renderer = null;

const PROPS = ["--glass-mesh-1", "--glass-mesh-2", "--glass-mesh-3", "--glass-fill", "--glass-edge",
               "--glass-glint", "--glass-shadow"];

export function rgba(text, fallback) {
  const s = String(text || "").trim();
  let m = s.match(/^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+)(%?))?\s*\)$/i);
  if (m) {
    let a = m[4] === undefined ? 1 : Number(m[4]);
    if (m[5]) a /= 100;
    return [Number(m[1]) / 255, Number(m[2]) / 255, Number(m[3]) / 255, a];
  }
  m = s.match(/^#([0-9a-f]{3,8})$/i);
  if (m) {
    let h = m[1];
    if (h.length <= 4) h = h.split("").map(c => c + c).join("");
    const n = [0, 2, 4, 6].map(i => (i < h.length ? parseInt(h.slice(i, i + 2), 16) / 255 : 1));
    return n;
  }
  return fallback;
}

function read(tokens) {
  const out = {};
  for (const name of PROPS) out[name] = tokens.css(name);
  return out;
}

function paint(tokens) {
  const v = read(tokens);
  painted = PROPS.map(n => v[n]).join("|") + "|" + tokens.bg.join(",");
  const none = [0, 0, 0, 0];
  if (mesh) {
    const u = mesh.u;
    u.uBg.value.set(tokens.bg[0], tokens.bg[1], tokens.bg[2]);
    for (let i = 0; i < 3; i++) u["uMesh" + (i + 1)].value.set(...rgba(v["--glass-mesh-" + (i + 1)], none));
    u.uGlint.value.set(...rgba(v["--glass-glint"], none));
  }
  for (const p of panes.values()) {
    const u = p.u;
    const fill = rgba(v["--glass-fill"], null) || tokens.panel.concat([0.4]);
    u.uFill.value.set(...fill);
    u.uEdge.value.set(...rgba(v["--glass-edge"], none));
    u.uGlint.value.set(...rgba(v["--glass-glint"], none));
    u.uShadow.value.set(...rgba(v["--glass-shadow"], none));
    u.uRun.value.set(...tokens.running);
  }
}

const GROUND_VS = `
uniform vec2 uView;
uniform float uTime;
uniform vec3 uWaveL;
uniform vec3 uWaveT;
uniform float uWaveH;
varying vec2 vP;
varying float vShade;
varying float vSpec;
const float TAU = 6.2831853;
float height(vec2 p) {
  float a = sin(TAU * (p.x / uWaveL.x + uTime / uWaveT.x) + 0.8 * sin(TAU * (p.y / uWaveL.z - uTime / uWaveT.z)));
  float b = cos(TAU * (p.y / uWaveL.y - uTime / uWaveT.y));
  float c = sin(TAU * ((p.x + p.y) / uWaveL.z + uTime / uWaveT.z));
  return uWaveH * (0.6 * a * b + 0.4 * c);
}
void main() {
  // The page's own coordinates: x right, y down, in CSS px.
  vec2 p = vec2(position.x + uView.x * 0.5, uView.y * 0.5 - position.y);
  vP = p;
  float h0 = height(p);
  vec3 n = normalize(vec3(-(height(p + vec2(4.0, 0.0)) - h0) / 4.0, -(height(p + vec2(0.0, 4.0)) - h0) / 4.0, 1.0));
  // The light is the pane glint's: up and to the left, towards the viewer.
  vec3 L = normalize(vec3(-0.45, -0.55, 0.9));
  vShade = dot(n, L) / L.z;
  vec3 H = normalize(L + vec3(0.0, 0.0, 1.0));
  vSpec = pow(max(dot(n, H), 0.0), 90.0);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position.xy, 0.0, 1.0);
}`;

const GROUND_FS = `
uniform vec2 uView;
uniform vec3 uBg;
uniform vec4 uMesh1;
uniform vec4 uMesh2;
uniform vec4 uMesh3;
uniform vec2 uAt1;
uniform vec2 uAt2;
uniform vec2 uAt3;
uniform vec2 uR1;
uniform vec2 uR2;
uniform vec2 uR3;
uniform vec4 uGlint;
uniform float uLight;
uniform float uEnd;
varying vec2 vP;
varying float vShade;
varying float vSpec;
float blob(vec2 at, vec2 r) {
  return clamp(1.0 - length((vP / uView - at) / r) / uEnd, 0.0, 1.0);
}
void main() {
  // Painted as the CSS paints it: the ground, then the last blob, then the one before it on top.
  vec3 c = uBg;
  c = mix(c, uMesh3.rgb, uMesh3.a * blob(uAt3, uR3));
  c = mix(c, uMesh2.rgb, uMesh2.a * blob(uAt2, uR2));
  c = mix(c, uMesh1.rgb, uMesh1.a * blob(uAt1, uR1));
  c *= mix(1.0, vShade, uLight);
  c = mix(c, uGlint.rgb, clamp(uGlint.a * vSpec * 0.35, 0.0, 1.0));
  gl_FragColor = vec4(c, 1.0);
}`;

function drift(u, t) {
  MESH.forEach((b, i) => {
    const a = 6.2831853 * t / LAPS[i] + i * 2.1;
    u["uAt" + (i + 1)].value.set(b.at[0] + DRIFT * Math.sin(a), b.at[1] + DRIFT * Math.cos(a * 0.8));
  });
}

export function ground({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const sx = Math.min(64, Math.max(8, Math.ceil(w / 40)));
  const sy = Math.min(40, Math.max(6, Math.ceil(h / 40)));
  const u = {
    uView: { value: new THREE.Vector2(w, h) },
    uTime: { value: clock },
    uWaveL: { value: new THREE.Vector3(...WAVE_L) },
    uWaveT: { value: new THREE.Vector3(...WAVE_T) },
    uWaveH: { value: WAVE_H },
    uBg: { value: new THREE.Vector3() },
    uGlint: { value: new THREE.Vector4() },
    uLight: { value: LIGHT },
    uEnd: { value: BLOB_END },
  };
  MESH.forEach((b, i) => {
    u["uMesh" + (i + 1)] = { value: new THREE.Vector4() };
    u["uAt" + (i + 1)] = { value: new THREE.Vector2(...b.at) };
    u["uR" + (i + 1)] = { value: new THREE.Vector2(...b.r) };
  });
  drift(u, clock);
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(w, h, sx, sy),
                              new THREE.ShaderMaterial({ uniforms: u, vertexShader: GROUND_VS, fragmentShader: GROUND_FS,
                                                         depthTest: false, depthWrite: false }));
  plane.position.set(w / 2, -h / 2, 0);
  plane.renderOrder = api.order.ground;
  plane.frustumCulled = false;
  scene.add(plane);
  mesh = { u };
  requestFrame = api.request;
  renderer = api.renderer;
  paint(tokens);
  const link = document.head.querySelector("link[data-skin]");
  if (link && !tokens.css("--glass-mesh-1")) link.addEventListener("load", () => api.request(), { once: true });
}

const PANE_VS = `
uniform vec2 uSize;
varying vec2 vP;
void main() {
  // The pane's own coordinates: 0,0 at its top-left, y down, in CSS px.
  vP = vec2(position.x + uSize.x * 0.5, uSize.y * 0.5 - position.y);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const PANE_FS = `
uniform sampler2D uGround;
uniform vec2 uGroundSize;
uniform float uDpr;
uniform vec2 uSize;
uniform float uRadius;
uniform float uBlur;
uniform float uSat;
uniform vec4 uFill;
uniform vec4 uEdge;
uniform vec4 uGlint;
uniform vec4 uShadow;
uniform float uShadowY;
uniform float uShadowBlur;
uniform vec3 uRim;
uniform float uRimK;
uniform vec3 uRun;
uniform float uRunOn;
uniform float uRunX;
varying vec2 vP;

float box(vec2 p, vec2 b, float r) {
  vec2 q = abs(p) - b + r;
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

/* CSS saturate(): the filter's own matrix, applied to sRGB as the browser does. */
vec3 saturate3(vec3 c, float s) {
  return vec3((0.213 + 0.787 * s) * c.r + (0.715 - 0.715 * s) * c.g + (0.072 - 0.072 * s) * c.b,
              (0.213 - 0.213 * s) * c.r + (0.715 + 0.285 * s) * c.g + (0.072 - 0.072 * s) * c.b,
              (0.213 - 0.213 * s) * c.r + (0.715 - 0.715 * s) * c.g + (0.072 + 0.928 * s) * c.b);
}

/* The blur pass: the ground behind this fragment, a gaussian of sigma uBlur px, from a centre tap
   and two rings of taps (at one and two sigma) weighted by the gaussian. The ground is smooth --
   blobs and long waves -- so twenty-one taps is the gaussian, not an impression of it. */
vec3 frost() {
  vec2 uv = gl_FragCoord.xy / uGroundSize;
  vec2 s = vec2(uBlur * uDpr) / uGroundSize;
  vec3 acc = texture2D(uGround, uv).rgb;
  float wsum = 1.0;
  for (int i = 0; i < 8; i++) {
    float a = 6.2831853 * (float(i) + 0.5) / 8.0;
    acc += texture2D(uGround, uv + vec2(cos(a), sin(a)) * s).rgb * 0.6065;
    wsum += 0.6065;
  }
  for (int i = 0; i < 12; i++) {
    float a = 6.2831853 * float(i) / 12.0;
    acc += texture2D(uGround, uv + vec2(cos(a), sin(a)) * s * 2.0).rgb * 0.1353;
    wsum += 0.1353;
  }
  return saturate3(acc / wsum, uSat);
}

void main() {
  vec2 half_ = uSize * 0.5;
  vec2 c = vP - half_;
  float d = box(c, half_, uRadius);                 // < 0 inside the pane
  float inside = clamp(0.5 - d, 0.0, 1.0);

  // The pane: the frost with the fill over it, a sheen where the light falls, the edge, the glint.
  vec3 pane = mix(frost(), uFill.rgb, uFill.a);
  float sheen = 1.0 - smoothstep(0.0, 0.6, 0.8 * vP.y / uSize.y + 0.2 * vP.x / uSize.x);
  pane = mix(pane, uGlint.rgb, uGlint.a * 0.08 * sheen);
  float edge = 1.0 - smoothstep(0.0, 1.0, abs(d + 0.5));
  pane = mix(pane, uEdge.rgb, uEdge.a * edge);
  float top = (1.0 - smoothstep(0.0, 1.0, abs(vP.y - 1.5))) * step(d, 0.0);
  float lit = 0.55 + 0.45 * (1.0 - vP.x / uSize.x);
  pane = mix(pane, uGlint.rgb, uGlint.a * top * lit);
  // A running agent's glint runs along the top edge; held still (uRunX < 0) it tints it.
  float run = uRunX < 0.0 ? 0.6 : exp(-pow((vP.x - uRunX * uSize.x) / 48.0, 2.0));
  pane = mix(pane, uRun, uRunOn * top * run);

  // Outside the pane: its shadow, as CSS clips a box-shadow to outside the box.
  float ds = box(c - vec2(0.0, uShadowY), half_, uRadius);
  float sh = uShadow.a * (1.0 - smoothstep(-uShadowBlur * 0.5, uShadowBlur, ds)) * (1.0 - inside);
  vec4 o = vec4(uShadow.rgb * sh, sh);
  o = vec4(pane * inside, inside) + o * (1.0 - inside);

  // The rim, in the state's colour: drawn clockwise from the top middle as far as uRimK.
  float at = fract(atan(c.x, -c.y) / 6.2831853 + 1.0);
  float drawn = 1.0 - smoothstep(uRimK - 0.004, uRimK, at);
  float line = 1.0 - smoothstep(0.0, 1.2, abs(d + 0.25));
  float glow = d > 0.0 ? 0.45 * exp(-d / 5.0) : 0.0;
  float rim = uRimK > 0.0 ? clamp(drawn * max(line, glow), 0.0, 1.0) : 0.0;
  o = vec4(uRim * rim, rim) + o * (1.0 - rim);
  gl_FragColor = o;
}`;

export function frame({ THREE, scene, tokens, api }, el, box) {
  const radius = parseFloat(getComputedStyle(el).borderTopRightRadius) || 0;
  const u = {
    uGround: { value: api.groundTexture },
    uGroundSize: { value: api.groundSize },
    uDpr: { value: api.viewport.dpr },
    uSize: { value: new THREE.Vector2(box.w, box.h) },
    uRadius: { value: Math.min(radius, box.w / 2, box.h / 2) },
    uBlur: { value: BLUR },
    uSat: { value: SATURATE },
    uFill: { value: new THREE.Vector4() },
    uEdge: { value: new THREE.Vector4() },
    uGlint: { value: new THREE.Vector4() },
    uShadow: { value: new THREE.Vector4() },
    uShadowY: { value: SHADOW_Y },
    uShadowBlur: { value: SHADOW_BLUR },
    uRim: { value: new THREE.Vector3() },
    uRimK: { value: 0 },
    uRun: { value: new THREE.Vector3() },
    uRunOn: { value: 0 },
    uRunX: { value: -1 },
  };
  const pane = new THREE.Mesh(new THREE.PlaneGeometry(box.w + 2 * MARGIN, box.h + 2 * MARGIN),
                              new THREE.ShaderMaterial({ uniforms: u, vertexShader: PANE_VS, fragmentShader: PANE_FS,
                                                         transparent: true, premultipliedAlpha: true,
                                                         depthTest: false, depthWrite: false }));
  pane.position.set(box.w / 2, -box.h / 2, 0);
  pane.renderOrder = api.order.frame;
  pane.frustumCulled = false;
  scene.add(pane);
  const was = panes.get(el);
  panes.set(el, { el, u, rim: was ? was.rim : null, k: was ? was.k : 0 });
  requestFrame = api.request;
  paint(tokens);
  settle(panes.get(el), tokens, api.reduced, 0);
}

function rimOf(el) {
  const c = el.classList;
  if (c.contains("needs-human") || c.contains("state-error") || c.contains("state-blocked")) return "human";
  if (c.contains("state-done") || c.contains("is-done")) return "done";
  return null;
}

function settle(p, tokens, reduced, dt) {
  const want = rimOf(p.el);
  if (reduced) {
    p.rim = want;
    p.k = want ? 1 : 0;
  } else if (p.rim !== want) {
    if (p.rim && p.k > 0) p.k = Math.max(0, p.k - dt / RIM_OUT);
    if (!p.rim || p.k <= 0) { p.rim = want; p.k = 0; }
  } else if (want && p.k < 1) {
    p.k = Math.min(1, p.k + dt / RIM_IN);
  }
  const rgb = p.rim ? tokens[p.rim] : [0, 0, 0];
  p.u.uRim.value.set(rgb[0], rgb[1], rgb[2]);
  p.u.uRimK.value = p.rim ? p.k : 0;
  return p.rim !== want || (!!want && p.k < 1);
}

export function tick({ tokens, api }, dt, now) {
  const reduced = api.reduced;
  if (!reduced && lastNow) clock += Math.min(1, Math.max(0, (now - lastNow) / 1000));
  lastNow = now;
  frames += 1;
  if (mesh) {
    mesh.u.uTime.value = clock;
    drift(mesh.u, clock);
  }
  const sig = PROPS.map(n => tokens.css(n)).join("|") + "|" + tokens.bg.join(",");
  if (sig !== painted) paint(tokens);
  let moving = false;
  for (const [el, p] of Array.from(panes)) {
    if (!el.isConnected) { panes.delete(el); continue; }
    if (settle(p, tokens, reduced, dt)) moving = true;
    p.u.uDpr.value = api.viewport.dpr;
    const running = el.classList.contains("state-running");
    p.u.uRunOn.value = running ? 1 : 0;
    const phase = (el.dataset.repo || "").length * 0.137;
    p.u.uRunX.value = reduced ? -1 : ((clock / RUN_LAP + phase) % 1) * 1.2 - 0.1;
  }
  if (!reduced && !timer) {
    const late = asked ? Math.max(0, now - asked - gap) : 0;
    gap = Math.min(GROUND_MAX_MS, Math.max(1000 / GROUND_FPS, 4 * late));
    asked = now;
    timer = setTimeout(() => { timer = 0; if (requestFrame) requestFrame(); }, gap);
  }
  return moving;
}

export function dispose() {
  if (timer) clearTimeout(timer);
  timer = 0;
  asked = 0;
  lastNow = 0;
  gap = 1000 / GROUND_FPS;
  mesh = null;
  panes.clear();
  painted = "";
  requestFrame = null;
  renderer = null;
}

export function inspect() {
  return {
    ground: !!mesh, clock, frames, timer: !!timer, gap,
    textures: renderer ? renderer.info.memory.textures : 0,
    panes: Array.from(panes.values()).map(p => ({
      repo: p.el.dataset.repo || "", rim: p.rim, k: p.k, run: p.u.uRunOn.value, fill: Array.from(p.u.uFill.value.toArray()),
    })),
  };
}
