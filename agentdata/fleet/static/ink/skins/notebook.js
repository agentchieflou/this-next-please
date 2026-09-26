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
    { selector: ".ask.is-answered .ask-q", tool: "pen", shape: "strike" },
    { selector: ".ask.is-answered .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "ellipse" },
    { selector: ".ask.is-answered:not(:has(.ask-choice[aria-pressed=\"true\"])) .ask-answer",
      tool: "pen", shape: "ellipse" },
    { selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },
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

export const options = { paper: "--paper", hand: true, speed: 1 };

export const sampleGround = false;

const PITCH = 28;
const MARGIN = 28;
const RAIL_BELOW = 90;

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

const PAPER_FS = `
uniform vec3 uPaper; uniform vec3 uRule; uniform float uDark; uniform float uDpr; uniform vec2 uView; uniform float uRuled;
float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vn(vec2 p){ vec2 i = floor(p); vec2 f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(h21(i), h21(i + vec2(1.0, 0.0)), u.x), mix(h21(i + vec2(0.0, 1.0)), h21(i + vec2(1.0, 1.0)), u.x), u.y); }
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uDpr - gl_FragCoord.y) / uDpr;
  // Fibre: long, faint, mostly along the sheet, and a finer tooth under it.
  float fib = vn(vec2(p.x * 0.05, p.y * 0.9)) * 0.6 + vn(p * 0.7) * 0.4;
  float k = uDark > 0.5 ? 0.55 : 1.0;
  vec3 c = uPaper * (1.0 + (fib - 0.5) * 0.035 * k);
  // A rule every pitch, a hair wide, printed a little unevenly.
  float d = abs(mod(p.y - ${PITCH - 1}.0, ${PITCH}.0));
  d = min(d, ${PITCH}.0 - d);
  float ink = (1.0 - smoothstep(0.35, 0.95, d)) * (0.82 + 0.18 * vn(vec2(p.x * 0.02, floor(p.y / ${PITCH}.0))));
  c = mix(c, uRule, ink * uRuled);
  // The light: brightest at the top left, falling off very slightly toward the far corner.
  vec2 q = p / max(uView, vec2(1.0));
  float fall = 1.0 - 0.045 * k * smoothstep(0.2, 1.4, length(q - vec2(0.15, 0.1)));
  gl_FragColor = vec4(c * fall, 1.0);
}`;

function stock(THREE, tokens, api, ruled, w, h) {
  const { w: vw, h: vh, dpr } = api.viewport;
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.ShaderMaterial({
    vertexShader: "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: PAPER_FS, depthTest: false, depthWrite: false,
    uniforms: {
      uPaper: { value: new THREE.Vector3(...rgbOf(tokens, "--paper", tokens.bg)) },
      uRule: { value: new THREE.Vector3(...rgbOf(tokens, "--rule", tokens.line)) },
      uDark: { value: tokens.dark ? 1 : 0 },
      uDpr: { value: dpr },
      uView: { value: new THREE.Vector2(vw, vh) },
      uRuled: { value: ruled ? 1 : 0 },
    },
  }));
  mesh.frustumCulled = false;
  return mesh;
}

export function paper({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const mesh = stock(THREE, tokens, api, true, w, h);
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = api.order.paper;
  scene.add(mesh);
}

let builds = 0;

export function frame({ THREE, scene, tokens, api }, el, box) {
  builds += 1;
  if (box.w < RAIL_BELOW) return;
  const [r, g, b] = rgbOf(tokens, "--margin", tokens.human);
  const line = new THREE.Mesh(new THREE.PlaneGeometry(1.25, Math.max(1, box.h - 4)),
                              new THREE.MeshBasicMaterial({ color: new THREE.Color().setRGB(r, g, b, THREE.SRGBColorSpace),
                                                            depthTest: false, depthWrite: false }));
  line.position.set(MARGIN, -box.h / 2, 0);
  line.renderOrder = api.order.frame;
  scene.add(line);
  const list = el.querySelector(".transcript"), t = list && list.getBoundingClientRect();
  if (!t || !t.width || !t.height) return;
  const p = el.getBoundingClientRect();
  const x = t.left - p.left, top = t.top - p.top + list.clientTop, bottom = t.bottom - p.top;
  if (bottom - top < 1) return;
  const cover = stock(THREE, tokens, api, false, t.width, bottom - top);
  cover.position.set(x + t.width / 2, -(top + bottom) / 2, 0);
  cover.renderOrder = api.order.frame - 2;
  scene.add(cover);
  const ink = new THREE.MeshBasicMaterial({ depthTest: false, depthWrite: false,
                                            color: new THREE.Color().setRGB(...rgbOf(tokens, "--rule", tokens.line), THREE.SRGBColorSpace) });
  for (let y = bottom - 1; y >= top; y -= PITCH) {
    const rule = new THREE.Mesh(new THREE.PlaneGeometry(t.width, 1), ink);
    rule.position.set(x + t.width / 2, -(y + 0.5), 0);
    rule.renderOrder = api.order.frame - 1;
    scene.add(rule);
  }
}

export function inspect() {
  return { builds };
}
