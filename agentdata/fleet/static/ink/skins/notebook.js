/* The notebook (#249) and the night notebook (#250): the first skin drawn with ink, and the reference
   every later paper skin's marks are measured against (plan-ink §C). The operator chose it from the
   three.js prototype (`notebook-three.html`, epic #246 Decision 1); its tools and shaders are the
   layer's `pen.js`, and this file is the rest of it -- the mark table, which is the state grammar,
   and the paper.

   ONE MODULE, TWO VARIANTS. `notebook:light` is white stock with blue rules and a red margin;
   `notebook:dark` is charcoal stock with gel inks, and its highlighter is screened rather than
   multiplied. The table is the same for both: what changes is the paper and the inks, and those are
   custom properties in `static/skins/notebook/skin.css` (`--paper`, `--rule`, `--margin` and
   `--ink-<tool>`), read here through `tokens` at paint time. No colour is written in this file, so a
   variant, a palette or a scheme change repaints the page without it (desk-ink §Writing a skin, 3).

   THE DOM IS THE TRUTH. Every row is a class or an attribute `app.js` already sets: `state-<state>`
   and `needs-human` on the pane, the question card's rows and `aria-pressed` on its choices,
   `is-answered` on a question the server passed on, `.oldsession` shown for a session on old skills
   (#240), a transcript line's kind, and the header's unread count. Nothing here decides a state. */

/* The state grammar (plan-ink §The state grammar), a row per mark. Rows are drawn in table order
   within a pane, so the order below is the order a hand would work down a page. */
export function marks() {
  return [
    // idle: a pencil outline, and a pencil line under the name.
    { selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -3 },
    { selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" },
    // running: a pen line under the name that grows with the turn -- a step for every transcript
    // line that arrives while it works -- with the pen's tip resting at its end.
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline",
      grow: ".transcript > li", step: 12, tip: true },
    // needs you: the name and the question highlighted, pencil loops round the choices. The
    // approval card is the other way a pane asks, and its summary is its question.
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .approval:not([hidden]) .summary", tool: "highlighter", shape: "lines" },
    { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-choice", tool: "pencil", shape: "loop" },
    // answered: the question struck in pen (its highlight is struck by leaving, above), and the
    // answer circled -- the choice pressed, or the box when the answer was typed. Never the name.
    { selector: ".ask.is-answered .ask-q", tool: "pen", shape: "strike" },
    { selector: ".ask.is-answered .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "ellipse" },
    { selector: ".ask.is-answered:not(:has(.ask-choice[aria-pressed=\"true\"])) .ask-answer",
      tool: "pen", shape: "ellipse" },
    // error: a red marker box round the pane, and a bang in the margin.
    { selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },
    { selector: ".tile.state-error", tool: "marker", shape: "bang" },
    // done: a green check in the margin.
    { selector: ".tile.state-done", tool: "green", shape: "check" },
    // stale (#240): a pencil note in the margin -- the chip's own words, handwritten -- an arrow
    // from it to the run line that says which session this is, and a dashed pencil outline.
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".runline" },
    { selector: ".tile:has(.oldsession:not([hidden]))", tool: "pencil", shape: "outline", dash: true, pad: -8 },
    // a finding -- a friction the agent recorded: a red ellipse round the line, the highlighter on
    // its token, and its own text written in the margin.
    { selector: ".tile .transcript > li.friction", tool: "red", shape: "ellipse", pad: -6 },
    { selector: ".tile .transcript > li.friction > .k", tool: "highlighter", shape: "lines" },
    { selector: ".tile .transcript > li.friction > .v", tool: "pencil", shape: "write" },
    // the header's count, handwritten: when it changes the old number is struck and the new one
    // written beside it.
    { selector: "#bellcount", tool: "pen", shape: "write", rewrite: true },
  ];
}

/* The paper is the skin's own (the `paper` hook); `--paper` is named too, so the layer knows how
   light the stock is and multiplies the highlighter into it, or screens it onto the night page. */
export const options = { paper: "--paper", hand: true, speed: 1 };

export const sampleGround = false;

/* The rules' pitch: the page's 28px baseline, the one graph paper (#253) will share. */
const PITCH = 28;
/* Where a pane's margin line runs, from its left edge: the check and the bang are written left of it. */
const MARGIN = 28;
const RAIL_BELOW = 90;

/* A custom property's colour as [r, g, b] in 0-1 sRGB. The skin's colours are custom properties,
   and `tokens.css` answers them as written: a hex, or rgb(). */
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
uniform vec3 uPaper; uniform vec3 uRule; uniform float uDark; uniform float uDpr; uniform vec2 uView;
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
  c = mix(c, uRule, ink);
  // The light: brightest at the top left, falling off very slightly toward the far corner.
  vec2 q = p / max(uView, vec2(1.0));
  float fall = 1.0 - 0.045 * k * smoothstep(0.2, 1.4, length(q - vec2(0.15, 0.1)));
  gl_FragColor = vec4(c * fall, 1.0);
}`;

/* The stock behind the panes: the paper's colour, its rules, its fibre and its light. */
export function paper({ THREE, scene, tokens, api }) {
  const { w, h, dpr } = api.viewport;
  const stock = rgbOf(tokens, "--paper", tokens.bg);
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.ShaderMaterial({
    vertexShader: "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: PAPER_FS, depthTest: false, depthWrite: false,
    uniforms: {
      uPaper: { value: new THREE.Vector3(...stock) },
      uRule: { value: new THREE.Vector3(...rgbOf(tokens, "--rule", tokens.line)) },
      uDark: { value: tokens.dark ? 1 : 0 },
      uDpr: { value: dpr },
      uView: { value: new THREE.Vector2(w, h) },
    },
  }));
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.frustumCulled = false;
  mesh.renderOrder = api.order.paper;
  scene.add(mesh);
}

/* One pane's margin: a red line down it, a little in from its left edge. A rail has no margin to
   draw; its marks go down its middle. */
export function frame({ THREE, scene, tokens, api }, el, box) {
  if (box.w < RAIL_BELOW) return;
  const [r, g, b] = rgbOf(tokens, "--margin", tokens.human);
  const line = new THREE.Mesh(new THREE.PlaneGeometry(1.25, Math.max(1, box.h - 4)),
                              new THREE.MeshBasicMaterial({ color: new THREE.Color().setRGB(r, g, b, THREE.SRGBColorSpace),
                                                            depthTest: false, depthWrite: false }));
  line.position.set(MARGIN, -box.h / 2, 0);
  line.renderOrder = api.order.frame;
  scene.add(line);
}
