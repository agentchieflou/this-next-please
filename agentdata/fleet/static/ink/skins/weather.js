export function marks() {
  return [
    { selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -3, dash: true },
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline",
      grow: ".transcript > li", step: 12, tip: true },
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves: "erased" },
    { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .approval:not([hidden]) .summary", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .asks:not([hidden])", tool: "marker", shape: "loop", pad: -3 },
    { selector: ".ask.is-answered .ask-q", tool: "pen", shape: "strike" },
    { selector: ".ask.is-answered .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "ellipse" },
    { selector: ".ask.is-answered:not(:has(.ask-choice[aria-pressed=\"true\"])) .ask-answer",
      tool: "pen", shape: "ellipse" },
    { selector: ".tile.state-error .why", tool: "marker", shape: "outline", pad: 2 },
    { selector: ".tile.state-error", tool: "red", shape: "bang" },
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile:has(.oldsession:not([hidden]))", tool: "pencil", shape: "outline", dash: true, pad: -8 },
    { selector: ".tile .transcript > li.friction", tool: "red", shape: "ellipse", pad: -6 },
    { selector: "#bellcount", tool: "pen", shape: "write", rewrite: true },
  ];
}

const EVEN = { press: 1, pvar: 0, wob: 0.15, bow: 0, tin: 0, tout: 0 };

export const options = { paper: "--paper", hand: false, speed: 1.4,
                         tools: { pencil: { ...EVEN, w: 1.4 }, pen: { ...EVEN, w: 1.5 }, red: { ...EVEN, w: 1.8 },
                                  green: { ...EVEN, w: 2.4 } } };

export const sampleGround = false;

export const cues = [
  { selector: "#grid > .tile.state-error", on: "arrive", cue: "lightning" },
  { selector: "#grid > .tile:is(.state-done, .is-done)", on: "arrive", cue: "clearing" },
];

const FLASH_S = 0.32;
const CLEAR_S = 0.32;
const METEOR_EVERY = 9.0;
const KINDS = ["rainy", "sunny", "cloudy", "starry"];

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

function numOf(tokens, name, fallback) {
  const n = parseFloat(tokens.css(name));
  return Number.isFinite(n) ? n : fallback;
}

const NOISE = `
float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vn(vec2 p){ vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1.0, 0.0)), u.x), mix(h21(i + vec2(0.0, 1.0)), h21(i + vec2(1.0, 1.0)), u.x), u.y); }
float fbm(vec2 p){ float a = 0.5, s = 0.0; for (int k = 0; k < 5; k++) { s += a * vn(p); p = p * 2.03 + 17.1; a *= 0.5; } return s; }
`;

const VERT = "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }";

const SKY_FS = `
uniform float uKind; uniform float uTime; uniform float uDpr; uniform vec2 uView;
uniform vec3 uTop; uniform vec3 uBottom; uniform vec3 uCloud; uniform float uCloudA; uniform vec3 uShade;
uniform vec3 uSun; uniform vec3 uRay; uniform float uRayA; uniform vec3 uStar; uniform vec3 uMeteor;
uniform vec3 uFlashC; uniform float uFlash; uniform float uClear;
${NOISE}
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uDpr - gl_FragCoord.y) / uDpr;
  vec2 q = p / max(uView, vec2(1.0));
  vec3 c = mix(uTop, uBottom, smoothstep(0.0, 1.0, q.y));
  if (uKind < 0.5) {
    float band = fbm(vec2(p.x * 0.0015 + uTime * 0.01, p.y * 0.004));
    c = mix(c, uTop * 0.82, smoothstep(0.45, 0.75, band) * 0.6);
    c = mix(c, uFlashC, uFlash * (0.55 + 0.45 * (1.0 - q.y)));
  } else if (uKind < 1.5) {
    vec2 s = vec2(0.86, 0.14);
    vec2 d = (q - s) * vec2(uView.x / uView.y, 1.0);
    float r = length(d), a = atan(d.y, d.x);
    float rays = 0.5 + 0.5 * sin(a * 9.0 + uTime * 0.12) * sin(a * 5.0 - uTime * 0.07);
    float beam = smoothstep(0.85, 1.0, rays) * (1.0 - smoothstep(0.05, 1.3, r)) * uRayA;
    c = mix(c, uRay, beam * (1.0 + 0.6 * uClear));
    c = mix(c, uSun, (1.0 - smoothstep(0.0, 0.13, r)) * 0.9 + (1.0 - smoothstep(0.0, 0.45, r)) * 0.25);
  } else if (uKind < 2.5) {
    vec2 w = vec2(p.x + uTime * 9.0, p.y * 1.6) * 0.0022;
    float n = fbm(w);
    float cover = smoothstep(0.42, 0.62, n);
    float under = smoothstep(0.42, 0.62, fbm(w + vec2(0.0, 0.05)));
    c = mix(c, uShade, clamp(under - cover, 0.0, 1.0) * 0.5 * uCloudA);
    c = mix(c, uCloud, cover * uCloudA);
  } else {
    vec2 g = floor(p / 22.0);
    vec2 f = fract(p / 22.0) - 0.5;
    float h = h21(g);
    vec2 at = vec2(h21(g + 3.1), h21(g + 7.7)) - 0.5;
    float d = length(f - at * 0.8);
    float tw = 0.55 + 0.45 * sin(uTime * (0.8 + 2.4 * h21(g + 1.3)) + h * 6.28);
    float star = (1.0 - smoothstep(0.0, 0.028 + 0.03 * h, d)) * step(0.72, h) * tw;
    c = mix(c, uStar, star);
    float cycle = floor(uTime / ${METEOR_EVERY.toFixed(1)});
    float ph = fract(uTime / ${METEOR_EVERY.toFixed(1)}) * ${METEOR_EVERY.toFixed(1)};
    if (ph < 0.7) {
      vec2 from = vec2(0.15 + 0.6 * h21(vec2(cycle, 2.0)), 0.05 + 0.3 * h21(vec2(cycle, 5.0)));
      vec2 dir = normalize(vec2(1.0, 0.55));
      vec2 head = from + dir * ph * 0.7;
      vec2 rel = (q - head) * vec2(uView.x / uView.y, 1.0);
      float along = dot(rel, dir), across = abs(dot(rel, vec2(-dir.y, dir.x)));
      float tail = smoothstep(-0.16, 0.0, along) * step(along, 0.0);
      float m = tail * (1.0 - smoothstep(0.0, 0.0025, across)) * (1.0 - ph / 0.7);
      c = mix(c, uMeteor, m);
    }
  }
  gl_FragColor = vec4(c, 1.0);
}`;

const RAIN_FS = `
uniform float uTime; uniform float uDpr; uniform vec2 uView; uniform vec3 uDrop; uniform float uDropA;
uniform vec3 uFlashC; uniform float uFlash;
${NOISE}
float sheet(vec2 p, float col, float speed, float len, float lean, float seed){
  p.x += p.y * lean;
  float x = floor(p.x / col);
  float h = h21(vec2(x, seed));
  float y = p.y + uTime * speed * (0.8 + 0.4 * h) + h * 900.0;
  float gap = 140.0 + 260.0 * h21(vec2(x, seed + 2.0));
  float k = mod(y, gap);
  float core = 1.0 - smoothstep(0.0, col * 0.5, abs(fract(p.x / col) - 0.5) * col);
  float streak = smoothstep(0.0, len * 0.35, k) * (1.0 - smoothstep(len * 0.35, len, k));
  return streak * core * step(0.35, h21(vec2(x, seed + 9.0)));
}
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uDpr - gl_FragCoord.y) / uDpr;
  float a = sheet(p, 5.0, 620.0, 26.0, 0.10, 1.0) * 1.0
          + sheet(p, 7.0, 440.0, 18.0, 0.08, 4.0) * 0.6
          + sheet(p, 9.0, 300.0, 12.0, 0.06, 8.0) * 0.35;
  a = clamp(a, 0.0, 1.0) * uDropA;
  vec3 c = mix(uDrop, uFlashC, uFlash);
  gl_FragColor = vec4(c, a + uFlash * 0.12);
}`;

const W = {
  sky: null, rain: null, rainU: null, over: [], tokens: null, api: null, kind: 0, time: 0, ticks: 0,
  flash: 0, clear: 0, frames: 0, played: {}, reduced: false,
};

function rainUniforms(THREE, api) {
  if (!W.rainU) {
    const { w, h, dpr } = api.viewport;
    W.rainU = { uTime: { value: 0 }, uDpr: { value: dpr }, uView: { value: new THREE.Vector2(w, h) },
                uFlashC: { value: new THREE.Vector3() }, uFlash: { value: 0 },
                uDrop: { value: new THREE.Vector3() }, uDropA: { value: 0.16 } };
  }
  return W.rainU;
}

function rainMaterial(THREE, api) {
  return new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: RAIN_FS, uniforms: rainUniforms(THREE, api),
                                    depthTest: false, depthWrite: false, transparent: true });
}

function remember({ tokens, api }) {
  if (tokens) W.tokens = tokens;
  if (api) { W.api = api; W.reduced = !!api.reduced; }
}

function kindOf(tokens) {
  const k = Math.round(numOf(tokens, "--wx-kind", 0));
  return k >= 0 && k < KINDS.length ? k : 0;
}

function look(THREE) {
  const t = W.tokens;
  if (!t || !W.sky) return;
  W.kind = kindOf(t);
  const u = W.sky.material.uniforms;
  u.uKind.value = W.kind;
  u.uTop.value.fromArray(rgbOf(t, "--wx-sky-top", t.bg));
  u.uBottom.value.fromArray(rgbOf(t, "--wx-sky-bottom", t.bg));
  u.uCloud.value.fromArray(rgbOf(t, "--wx-cloud", t.panel));
  u.uCloudA.value = numOf(t, "--wx-cloud-alpha", 0.6);
  u.uShade.value.fromArray(rgbOf(t, "--wx-cloud-shade", t.muted));
  u.uSun.value.fromArray(rgbOf(t, "--wx-sun", t.waiting));
  u.uRay.value.fromArray(rgbOf(t, "--wx-ray", t.waiting));
  u.uRayA.value = numOf(t, "--wx-ray-alpha", 0.3);
  u.uStar.value.fromArray(rgbOf(t, "--wx-star", t.text));
  u.uMeteor.value.fromArray(rgbOf(t, "--wx-meteor", t.text));
  u.uFlashC.value.fromArray(rgbOf(t, "--wx-flash", t.text));
  if (W.rainU) {
    const r = W.rainU;
    r.uDrop.value.fromArray(rgbOf(t, "--wx-drop", t.muted));
    r.uDropA.value = numOf(t, "--wx-drop-alpha", 0.16);
    r.uFlashC.value.fromArray(rgbOf(t, "--wx-flash", t.text));
  }
  if (W.rain) W.rain.visible = W.kind === 0;
  W.over = W.over.filter(m => m.parent);
  for (const m of W.over) m.visible = W.kind === 0;
  void THREE;
}

function timing() {
  if (W.sky) {
    const u = W.sky.material.uniforms;
    u.uTime.value = W.time;
    u.uFlash.value = W.flash;
    u.uClear.value = W.clear;
  }
  if (W.rainU) {
    W.rainU.uTime.value = W.time;
    W.rainU.uFlash.value = W.flash;
  }
}

function sheetOf(THREE, api, material, order) {
  const { w, h } = api.viewport;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), material);
  mesh.frustumCulled = false;
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = order;
  return mesh;
}

export function ground(ctx) {
  remember(ctx);
  const { THREE, scene, api } = ctx;
  const v3 = () => ({ value: new THREE.Vector3() });
  const { w, h, dpr } = api.viewport;
  W.sky = sheetOf(THREE, api, new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: SKY_FS, depthTest: false, depthWrite: false,
    uniforms: { uTime: { value: 0 }, uDpr: { value: dpr }, uView: { value: new THREE.Vector2(w, h) },
                uFlashC: v3(), uFlash: { value: 0 }, uKind: { value: 0 }, uTop: v3(), uBottom: v3(),
                uCloud: v3(), uCloudA: { value: 0.6 }, uShade: v3(), uSun: v3(), uRay: v3(),
                uRayA: { value: 0.3 }, uStar: v3(), uMeteor: v3(), uClear: { value: 0 } },
  }), api.order.ground);
  scene.add(W.sky);
  look(THREE);
  timing();
}

export function paper(ctx) {
  remember(ctx);
  const { THREE, scene, api } = ctx;
  W.rain = sheetOf(THREE, api, rainMaterial(THREE, api), api.order.fx);
  scene.add(W.rain);
  look(THREE);
  timing();
}

export function frame(ctx, el, box) {
  remember(ctx);
  const { THREE, scene, tokens, api } = ctx;
  W.frames += 1;
  const colour = rgb => new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
  const rim = new THREE.Mesh(new THREE.PlaneGeometry(box.w + 2, box.h + 2),
                             new THREE.MeshBasicMaterial({ color: colour(rgbOf(tokens, "--wx-rim", tokens.line)),
                                                           depthTest: false, depthWrite: false }));
  rim.position.set(box.w / 2, -box.h / 2, 0);
  rim.renderOrder = api.order.frame - 1;
  scene.add(rim);
  const sheet = new THREE.Mesh(new THREE.PlaneGeometry(box.w, box.h),
                               new THREE.MeshBasicMaterial({ color: colour(rgbOf(tokens, "--paper", tokens.panel)),
                                                             depthTest: false, depthWrite: false }));
  sheet.position.set(box.w / 2, -box.h / 2, 0);
  sheet.renderOrder = api.order.frame;
  scene.add(sheet);
  const over = new THREE.Mesh(new THREE.PlaneGeometry(box.w, box.h), rainMaterial(THREE, api));
  over.position.set(box.w / 2, -box.h / 2, 0);
  over.renderOrder = api.order.frame + 1;
  over.visible = W.kind === 0;
  scene.add(over);
  W.over.push(over);
  void el;
}

export function cue(ctx, name) {
  remember(ctx);
  W.played[name] = (W.played[name] || 0) + 1;
  if (W.reduced) return;
  if (name === "lightning" && W.kind === 0) W.flash = 0.7;
  if (name === "clearing" && W.kind === 1) W.clear = 1;
  if (W.api) W.api.request();
}

export function tick(ctx, dt) {
  remember(ctx);
  const { THREE } = ctx;
  if (!W.sky) return false;
  const step = Math.min(Math.max(dt, 0), 0.1);
  W.ticks += 1;
  if (!W.reduced) {
    W.time += step;
    if (W.flash > 0) W.flash = Math.max(0, W.flash - step / FLASH_S);
    if (W.clear > 0) W.clear = Math.max(0, W.clear - step / CLEAR_S);
  } else {
    W.flash = W.clear = 0;
  }
  look(THREE);
  timing();
  W.api.request();
  return !W.reduced;
}

export function dispose() {
  W.sky = W.rain = W.rainU = null;
  W.over = [];
  W.flash = W.clear = 0;
  W.frames = 0;
}

export function inspect() {
  return { kind: KINDS[W.kind], time: W.time, ticks: W.ticks, frames: W.frames, flash: W.flash, clear: W.clear,
           rain: !!(W.rain && W.rain.visible), over: W.over.filter(m => m.parent && m.visible).length,
           reduced: W.reduced, played: Object.assign({}, W.played) };
}
