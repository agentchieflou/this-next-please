const SNAP = { snap: 4 };

export function marks() {
  return [
    Object.assign({ selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -3 }, SNAP),
    { selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" },
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline",
      grow: ".transcript > li", step: 12, tip: true },
    { selector: ".tile:not([data-tier='rail']) .head .n", tool: "pencil", shape: "ring" },
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
    { selector: ".tile.state-blocked", tool: "red", shape: "cross" },
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".runline" },
    Object.assign({ selector: ".tile:has(.oldsession:not([hidden]))", tool: "pencil", shape: "outline",
                    dash: true, pad: -8 }, SNAP),
    { selector: ".tile .transcript > li.friction", tool: "red", shape: "ellipse", pad: -6 },
    { selector: ".tile .transcript > li.friction > .k", tool: "highlighter", shape: "lines" },
    { selector: ".tile .transcript > li.friction > .v", tool: "pencil", shape: "write" },
    { selector: "#bellcount", tool: "pen", shape: "write", rewrite: true },
  ];
}

export function options() {
  return {
    paper: "--paper",
    hand: true,
    speed: 1,
    tools: { pencil: { w: 1.05, press: 0.9, pvar: 0.04, wob: 0, bow: 0, wmin: 0.94, tin: 0, tout: 0 } },
  };
}

export const sampleGround = false;

const RAIL_BELOW = 90;
const PAD = 6;
const PAD_AT = [8, 2];
const TRACE_Y = 5;
const TRACE_W = 1.5;

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

const BOARD_FS = `
uniform vec3 uMask; uniform vec3 uWeave; uniform vec3 uMax; uniform float uDpr; uniform vec2 uView;
float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uDpr - gl_FragCoord.y) / uDpr;
  // Fibreglass: a plain weave, the warp and the weft over and under each other every 3px.
  vec2 cell = floor(p / 3.0);
  float over = mod(cell.x + cell.y, 2.0);
  vec2 f = fract(p / 3.0);
  float thread = over > 0.5 ? sin(f.y * 3.14159) : sin(f.x * 3.14159);
  float k = clamp(thread * (0.75 + 0.25 * h21(cell)), 0.0, 1.0);
  vec3 c = mix(uMask, uWeave, k);
  // At most 3% brighter than the mask, and never past the board's light end.
  gl_FragColor = vec4(min(min(c, uMask + vec3(0.03)), uMax), 1.0);
}`;

export function paper({ THREE, scene, tokens, api }) {
  const { w, h, dpr } = api.viewport;
  const mask = rgbOf(tokens, "--paper", tokens.bg);
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.ShaderMaterial({
    vertexShader: "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: BOARD_FS, depthTest: false, depthWrite: false,
    uniforms: {
      uMask: { value: new THREE.Vector3(...mask) },
      uWeave: { value: new THREE.Vector3(...rgbOf(tokens, "--weave", mask)) },
      uMax: { value: new THREE.Vector3(...rgbOf(tokens, "--board-max", mask)) },
      uDpr: { value: dpr },
      uView: { value: new THREE.Vector2(w, h) },
    },
  }));
  mesh.frustumCulled = false;
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = api.order.paper;
  scene.add(mesh);
}

let builds = 0;
const boards = new Map();

export function frame({ THREE, scene, tokens, api }, el, box) {
  builds += 1;
  boards.delete(el);
  if (box.w < RAIL_BELOW) return;
  const [r, g, b] = rgbOf(tokens, "--copper", tokens.line);
  const copper = new THREE.MeshBasicMaterial({ color: new THREE.Color().setRGB(r, g, b, THREE.SRGBColorSpace),
                                               depthTest: false, depthWrite: false });
  const [px, py] = PAD_AT;
  const pad = new THREE.Mesh(new THREE.PlaneGeometry(PAD, PAD), copper);
  pad.position.set(px + PAD / 2, -(py + PAD / 2), 0);
  const x0 = px + PAD, x1 = Math.max(x0, box.w - 10);
  const trace = new THREE.Mesh(new THREE.PlaneGeometry(Math.max(1, x1 - x0), TRACE_W), copper);
  trace.position.set((x0 + x1) / 2, -TRACE_Y, 0);
  for (const o of [pad, trace]) {
    o.renderOrder = api.order.frame;
    scene.add(o);
  }
  boards.set(el, { scene, box, pad: [px, py, PAD, PAD], trace: [x0, TRACE_Y - TRACE_W / 2, x1 - x0, TRACE_W] });
}

export function dispose() {
  boards.clear();
}

export function inspect() {
  const panes = {};
  for (const [el, f] of boards) {
    if (!el.isConnected || !f.scene.parent) continue;
    const ox = f.scene.position.x, oy = -f.scene.position.y;
    const at = ([x, y, w, h]) => ({ x: ox + x, y: oy + y, w, h });
    panes[el.dataset.repo] = { at: { x: ox, y: oy }, pad: at(f.pad), trace: at(f.trace) };
  }
  return { builds, panes };
}
