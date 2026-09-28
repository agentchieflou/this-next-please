export function marks() {
  return [
    { selector: ".tile:not([data-tier='rail']) .head .n", tool: "pencil", shape: "ring" },
    { selector: ".tile:not([data-tier='rail']) .head", tool: "pencil", shape: "divider" },
    { selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -3 },
    { selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" },
    { selector: ".tile.state-running .head .repo", tool: "pencil", ink: "pen", shape: "underline",
      grow: ".transcript > li", step: 12, cap: "arrow" },
    { selector: ".tile.state-waiting_approval .head .repo", tool: "pencil", ink: "pen", shape: "underline",
      dash: true, cap: "arrow" },
    { selector: ".tile.state-blocked .head .repo", tool: "pencil", ink: "red", shape: "underline", cap: "bar" },
    { selector: ".tile.state-blocked", tool: "red", shape: "cross" },
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves: "erased" },
    { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .approval:not([hidden]) .summary", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-choice", tool: "pencil", shape: "loop" },
    { selector: ".tile.needs-human .asks:not([hidden])", tool: "marker", shape: "loop", pad: -3 },
    { selector: ".ask.is-answered .ask-q", tool: "pencil", ink: "pen", shape: "strike" },
    { selector: ".ask.is-answered .ask-choice[aria-pressed=\"true\"]", tool: "pencil", ink: "pen", shape: "ellipse" },
    { selector: ".ask.is-answered:not(:has(.ask-choice[aria-pressed=\"true\"])) .ask-answer",
      tool: "pencil", ink: "pen", shape: "ellipse" },
    { selector: ".tile.state-error .why", tool: "marker", shape: "loop", pad: 0 },
    { selector: ".tile.state-error", tool: "marker", shape: "bang" },
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".runline" },
    { selector: ".tile:has(.oldsession:not([hidden]))", tool: "pencil", shape: "outline", dash: true, pad: -8 },
    { selector: ".tile .transcript > li.friction", tool: "red", shape: "ellipse", pad: -6 },
    { selector: ".tile .transcript > li.friction > .k", tool: "highlighter", shape: "lines" },
    { selector: ".tile .transcript > li.friction > .v", tool: "pencil", shape: "write" },
    { selector: "#bellcount", tool: "pencil", ink: "pen", shape: "write", rewrite: true },
  ];
}

export const options = {
  paper: "--paper", hand: "chalk", speed: 1,
  tools: { pencil: { w: 2.8, press: 0.8, pvar: 0.4, wob: 0.7, lam: 60, tin: 3, tout: 5 } },
};

export const sampleGround = false;

const PITCH = 28;
const YARD = PITCH * 5;
const HASH = 10;

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

function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (s + 0x6D2B79F5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const PAPER_FS = `
uniform vec3 uPaper; uniform vec3 uYard; uniform vec3 uMax; uniform float uDpr; uniform vec2 uView;
uniform float uTop; uniform vec3 uGhost[5]; uniform float uGhosts;
float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vn(vec2 p){ vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1.0, 0.0)), u.x), mix(h21(i + vec2(0.0, 1.0)), h21(i + vec2(1.0, 1.0)), u.x), u.y); }
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uDpr - gl_FragCoord.y) / uDpr;
  float grain = (h21(floor(p * 1.5)) - 0.5) * 0.05;
  float haze = (vn(p / 240.0) - 0.5) * 0.04;
  vec3 c = uPaper * (1.03 + grain + haze);
  for (int i = 0; i < 5; i++) {
    if (float(i) >= uGhosts) break;
    vec3 g = uGhost[i];
    float d = length((p - g.xy) / vec2(g.z, g.z * 0.55));
    float smear = 0.8 + 0.2 * vn(p / 18.0 + g.xy);
    c = mix(c, uMax, 0.42 * smear * (1.0 - smoothstep(0.3, 1.0, d)));
  }
  float below = step(uTop, p.y);
  float yd = mod(p.y - uTop, ${YARD}.0);
  float yard = below * (1.0 - smoothstep(0.5, 1.0, min(yd, ${YARD}.0 - yd)));
  float hd = mod(p.y - uTop, ${PITCH}.0);
  float tick = below * (1.0 - step(0.75, min(hd, ${PITCH}.0 - hd)));
  float hash = tick * max(1.0 - step(${HASH / 2}.0, abs(p.x - uView.x / 3.0)),
                          1.0 - step(${HASH / 2}.0, abs(p.x - uView.x * 2.0 / 3.0)));
  c = mix(c, uYard, max(yard, hash));
  gl_FragColor = vec4(clamp(c, uPaper, uMax), 1.0);
}`;

let builds = 0;
let board = { ghosts: [], top: 0 };

export function paper({ THREE, scene, tokens, api }) {
  builds += 1;
  const { w, h, dpr } = api.viewport;
  const head = document.querySelector("header");
  const top = Math.ceil(((head ? head.getBoundingClientRect().bottom : 0) + 4) / PITCH) * PITCH;
  const r = rng(Math.round(w) * 7919 + Math.round(h)), n = 3 + Math.floor(r() * 3), ghosts = [];
  for (let i = 0; i < 5; i++) {
    const g = { x: w * (0.1 + 0.8 * r()), y: top + (h - top) * (0.1 + 0.8 * r()), r: 90 + r() * 90 };
    if (i < n) ghosts.push(g);
  }
  board = { ghosts, top };
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.ShaderMaterial({
    vertexShader: "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: PAPER_FS, depthTest: false, depthWrite: false,
    uniforms: {
      uPaper: { value: new THREE.Vector3(...rgbOf(tokens, "--paper", tokens.bg)) },
      uYard: { value: new THREE.Vector3(...rgbOf(tokens, "--yard", tokens.line)) },
      uMax: { value: new THREE.Vector3(...rgbOf(tokens, "--board-max", tokens.panel)) },
      uDpr: { value: dpr },
      uView: { value: new THREE.Vector2(w, h) },
      uTop: { value: top },
      uGhost: { value: [0, 1, 2, 3, 4].map(i => ghosts[i] ? new THREE.Vector3(ghosts[i].x, ghosts[i].y, ghosts[i].r)
                                                        : new THREE.Vector3()) },
      uGhosts: { value: ghosts.length },
    },
  }));
  mesh.frustumCulled = false;
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = api.order.paper;
  scene.add(mesh);
}

export function inspect() {
  return { builds, ghosts: board.ghosts.map(g => ({ ...g })), top: board.top };
}
