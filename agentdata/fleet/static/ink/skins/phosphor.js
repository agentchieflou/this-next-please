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

export function paper({ THREE, scene, tokens, api }) {
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
}
