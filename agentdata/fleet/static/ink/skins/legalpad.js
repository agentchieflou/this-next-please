/* The legal pad (#251, slice E of the ink epic #246): "the yellow-page version" the operator asked
   for, which is a yellow legal pad (plan-ink Decision 4). Canary stock, blue rules on the page's
   28px baseline, a double red margin down every pane, and the gummed band a pad is bound by across
   the top of the page. The highlighter is orange-pink, because the palette's amber highlighter
   vanishes into canary.

   docs/desk-ink.md §The legal pad is the page this implements, and §Writing a skin the contract it
   keeps: no static import (three.js is handed in), colours only from the page's custom properties
   (`--paper`, `--rule`, `--margin`, `--glue` and `--ink-<tool>`, all in this skin's own skin.css),
   and nothing written to the page. `skin.css` is also the look `body.ink-off` falls back to.

   THE STATE GRAMMAR (plan-ink §The state grammar) is the table in `marks`, one or more rows per
   state, every selector a class or attribute app.js already sets. Two of the grammar's marks are
   not rows, because the layer has no shape for them yet, and are drawn here instead, from the same
   classes (plan-ink says C builds them; this is the skin-local copy slice K consolidates):
   * the running pen's tail: the underline grows with the turn -- one step per transcript line the
     turn adds -- and the pen-tip dot sits at its end. When the turn ends it is struck, in pen, with
     the underline it grew from;
   * the header count: when the number changes, the old one is struck where it stood, beside the
     new one. */

const BASE = 28;                 // the page's baseline: one rule every 28px
const GLUE = 10;                 // the gummed band across the top of the page, in px
const MARGIN = [25, 29];         // the double red margin, px in from a pane's left edge
const RAIL = 90;                 // under this a pane is its 48px rail (shapes.js), with no margin
const GROW = 6;                  // px the running pen's tail grows by, for each line of the turn
const TAIL_MAX = 132;            // and the furthest it reaches past the name
const STRIKE_S = 0.22;           // seconds a strike through the tail or the count takes to draw
const RUNNING = ".tile.state-running .head .repo";

/* The selectors that read a pressed choice. `:has` is how "a choice was made" reaches the question
   above it; an engine without it keeps the question highlighted until the card goes. */
const HAS = (() => {
  try { return CSS.supports("selector(:has(a))"); } catch (e) { return false; }
})();
const OPEN = HAS ? ':not(:has(.ask-choice[aria-pressed="true"]))' : "";
const FOUND = ".tile .transcript li:is(.denied, .friction)";

/* The grammar, row by row. Rows are queued in this order in each pane's lane. */
export function marks() {
  return [
    // idle: a pencil outline round the pane and a pencil line under its name.
    { selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -5 },
    { selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" },
    // running: a pen line under the name (its tail and the pen-tip dot are `tick`'s).
    { selector: RUNNING, tool: "pen", shape: "underline" },
    // needs you: the name and the question highlighted, and a pencil loop round each choice.
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile .ask:not([hidden])" + OPEN + " .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile .ask:not([hidden])" + OPEN + " .ask-choice", tool: "pencil", shape: "loop", pad: -1 },
    // answered: the choice made is circled in pen. The question's highlight leaving is the layer's
    // strike, in pen, along each swipe -- the question struck, never the agent's name.
    { selector: '.tile .ask:not([hidden]) .ask-choice[aria-pressed="true"]', tool: "pen", shape: "ellipse" },
    // error: a red marker box inside the pane, and a bang in its margin.
    { selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },
    { selector: ".tile.state-error", tool: "red", shape: "bang" },
    // done: a green check in the margin. `is-done` is the fold's own word (#253): the chip shows a
    // finished, unsupervised agent as idle, so `state-done` alone is almost never on the page.
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    // stale (#240): the chip's own words as a pencil note, a dashed pencil outline round it, and an
    // arrow to the run line -- the line that says which session and run this transcript is.
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", dash: true, pad: 0 },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".runline" },
    // a finding: a transcript line the agent was refused or stopped on, ringed in red, its kind
    // highlighted, and its own text written out.
    { selector: FOUND, tool: "red", shape: "ellipse", pad: -4 },
    { selector: FOUND + " .k", tool: "highlighter", shape: "lines" },
    { selector: FOUND + " .v", tool: "pencil", shape: "write" },
    // the header count, handwritten (a change is struck and rewritten by `tick`).
    { selector: "#bellcount", tool: "pen", shape: "write" },
  ];
}

/* `--paper` is what the layer reads to know the stock is light, so the highlighter multiplies. */
export const options = { paper: "--paper", hand: true, speed: 1 };
export const sampleGround = false;

// ------------------------------------------------------------------------------ drawing kit

/* A seeded generator, so the glue's ragged edge is the same edge on every redraw. */
function rng(seed) {
  let a = seed >>> 0 || 1;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* One of this skin's custom properties as [r, g, b] in 0-1 sRGB, else a palette token (already
   that). Colours are read from the page at paint time, never written here (desk-ink.md rule 3). */
function srgb(THREE, tokens, name, fallback) {
  const css = (tokens.css(name) || "").trim();
  if (css) {
    try { return new THREE.Color().setStyle(css).getRGB({}, THREE.SRGBColorSpace); } catch (e) { /* below */ }
  }
  return { r: fallback[0], g: fallback[1], b: fallback[2] };
}

function colour(THREE, tokens, name, fallback) {
  const c = srgb(THREE, tokens, name, fallback);
  return new THREE.Color().setRGB(c.r, c.g, c.b, THREE.SRGBColorSpace);
}

/* Both sides: a ribbon's quads wind whichever way its polyline turns. */
function flat(THREE, c) {
  return new THREE.MeshBasicMaterial({ color: c, side: THREE.DoubleSide, depthTest: false, depthWrite: false });
}

/* A polyline as a ribbon of quads, `w` px wide, in page coordinates (y down) -- the layer's camera
   draws a point `y` px down the page at -y. */
function ribbon(THREE, pts, w) {
  const pos = [];
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
    const d = Math.hypot(x1 - x0, y1 - y0) || 1;
    const nx = -(y1 - y0) / d * w / 2, ny = (x1 - x0) / d * w / 2;
    const a = [x0 + nx, -(y0 + ny)], b = [x0 - nx, -(y0 - ny)], c = [x1 + nx, -(y1 + ny)], e = [x1 - nx, -(y1 - ny)];
    pos.push(...a, 0, ...b, 0, ...c, 0, ...c, 0, ...b, 0, ...e, 0);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  return g;
}

function rect(THREE, x, y, w, h) {
  const g = new THREE.PlaneGeometry(Math.max(0.01, w), Math.max(0.01, h));
  g.translate(x + w / 2, -(y + h / 2), 0);
  return g;
}

function add(THREE, scene, geom, mat, order) {
  const m = new THREE.Mesh(geom, mat);
  m.renderOrder = order;
  m.frustumCulled = false;
  scene.add(m);
  return m;
}

/* The stock: canary, with the tooth a pencil catches on. Colour in sRGB, written as it is read. */
const STOCK_VS = "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }";
const STOCK_FS = `
uniform vec3 uPaper;
float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h(i), h(i + vec2(1.0, 0.0)), f.x), mix(h(i + vec2(0.0, 1.0)), h(i + vec2(1.0, 1.0)), f.x), f.y); }
void main(){
  vec2 p = gl_FragCoord.xy;
  float t = n(p * 0.55) * 0.6 + n(p * 0.13) * 0.4;
  gl_FragColor = vec4(uPaper * (1.0 - (t - 0.5) * 0.035), 1.0);
}`;

// ------------------------------------------------------------------------------- the paper

let paperScene = null;           // kept for `tick`: the struck count is drawn on the paper

/* The page is the pad: canary stock, the gummed band across its top, and a blue rule every 28px
   below the header. Called when the skin arrives, on a resize and on a palette change. */
export function paper({ THREE, scene, tokens, api }) {
  paperScene = scene;
  count.mesh = null;
  const { w, h } = api.viewport;
  // The uniform is the property's sRGB, written as it is read: the shader does no conversion.
  const c = srgb(THREE, tokens, "--paper", tokens.bg);
  const stock = new THREE.ShaderMaterial({
    vertexShader: STOCK_VS, fragmentShader: STOCK_FS, depthTest: false, depthWrite: false,
    uniforms: { uPaper: { value: new THREE.Vector3(c.r, c.g, c.b) } },
  });
  add(THREE, scene, rect(THREE, 0, 0, w, h), stock, api.order.paper);

  // The gummed band, with the ragged foot glue has where it soaked into the top sheet.
  const r = rng(251), foot = [];
  for (let x = 0; x <= w + 12; x += 12) foot.push([x, GLUE + (r() - 0.35) * 2.2]);
  const pos = [];
  for (let i = 1; i < foot.length; i++) {
    const [x0, y0] = foot[i - 1], [x1, y1] = foot[i];
    pos.push(x0, 0, 0, x0, -y0, 0, x1, 0, 0, x1, 0, 0, x0, -y0, 0, x1, -y1, 0);
  }
  const band = new THREE.BufferGeometry();
  band.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  add(THREE, scene, band, flat(THREE, colour(THREE, tokens, "--glue", tokens.human)), api.order.paper + 2);

  // The rules, from the first baseline under the header to the foot of the page.
  const head = document.querySelector("header");
  const top = head ? head.getBoundingClientRect().bottom : GLUE;
  const rule = flat(THREE, colour(THREE, tokens, "--rule", tokens.running));
  const lines = [];
  for (let y = Math.ceil((top + 4) / BASE) * BASE; y < h; y += BASE) lines.push(rect(THREE, 0, y - 1, w, 1));
  for (const g of lines) add(THREE, scene, g, rule, api.order.paper + 1);

  // The skin's stylesheet can arrive after the module: the paper is drawn again when it does.
  if (!(tokens.css("--paper") || "").trim()) waitForSheet();
}

let waiting = false;
function waitForSheet() {
  const link = document.head.querySelector("link[data-skin]");
  if (!link || waiting) return;
  waiting = true;
  link.addEventListener("load", () => { waiting = false; if (window.Ink) window.Ink.refresh(); }, { once: true });
}

// ------------------------------------------------------------------------------- the panes

const panes = new Map();         // pane -> its group and its running pen, for `tick`

let builds = 0;                  // frames built so far, for `inspect`

/* One pane's sheet: a hairline where its edge is, and the double red margin down its left. Under
   the transcript the rules are the transcript's own (#338): the page's rules are covered with plain
   stock, and a rule is drawn every BASE up from the transcript's bottom edge, where its rows end. */
export function frame({ THREE, scene, tokens, api }, el, box) {
  builds += 1;
  const p = panes.get(el) || { run: null };
  p.group = scene;
  p.meshes = null;
  panes.set(el, p);
  const edge = flat(THREE, colour(THREE, tokens, "--rule", tokens.line));
  edge.transparent = true;
  edge.opacity = 0.55;
  for (const g of [rect(THREE, 0, 0, box.w, 1), rect(THREE, box.w - 1, 0, 1, box.h), rect(THREE, 0, box.h - 1, box.w, 1)]) {
    add(THREE, scene, g, edge, api.order.frame);
  }
  if (box.w < RAIL) return;
  const red = flat(THREE, colour(THREE, tokens, "--margin", tokens.human));
  for (const x of MARGIN) add(THREE, scene, rect(THREE, x, 0, 1, box.h), red, api.order.frame + 1);
  const list = el.querySelector(".transcript"), t = list && list.getBoundingClientRect();
  if (!t || !t.width || !t.height) return;
  const pr = el.getBoundingClientRect();
  const x = t.left - pr.left, top = t.top - pr.top + list.clientTop, bottom = t.bottom - pr.top;
  if (bottom - top < 1) return;
  const c = srgb(THREE, tokens, "--paper", tokens.bg);
  add(THREE, scene, rect(THREE, x, top, t.width, bottom - top), new THREE.ShaderMaterial({
    vertexShader: STOCK_VS, fragmentShader: STOCK_FS, depthTest: false, depthWrite: false,
    uniforms: { uPaper: { value: new THREE.Vector3(c.r, c.g, c.b) } },
  }), api.order.frame - 2);
  const rule = flat(THREE, colour(THREE, tokens, "--rule", tokens.running));
  for (let y = bottom; y - 1 >= top; y -= BASE) add(THREE, scene, rect(THREE, x, y - 1, t.width, 1), rule, api.order.frame - 1);
}

// ------------------------------------------------------------------------- the running pen

/* The last line of a pane's transcript: where the turn has got to. */
function lastLine(el) {
  const list = el.querySelector(".transcript");
  return list ? list.lastElementChild : null;
}

/* Lines added to the transcript since `since`, walking back from the end. */
function linesSince(el, since) {
  const list = el.querySelector(".transcript");
  if (!list) return 0;
  let n = 0;
  for (let li = list.lastElementChild; li && li !== since; li = li.previousElementSibling) n += 1;
  return since && !since.isConnected ? Math.min(n, 1) : n;
}

/* Whether the layer has drawn this pane's running underline yet: the tail begins where the pen
   finished it, never before. */
function underlined(repo) {
  const l = window.Ink && window.Ink.inspect().layer;
  return !!l && l.marks.some(m => m.lane === "pane:" + repo && m.selector === RUNNING && m.state === "drawn");
}

function freeAll(group, list) {
  for (const m of list || []) {
    group.remove(m);
    m.geometry.dispose();
    m.material.dispose();
  }
}

/* The height, on the viewport, of the layer's underline under the name (layer.js `under`, shapes.js
   `underline`, #331): 2px under the tallest box on the name's line, and never lower than 3.4px over
   the next row -- the first box below the name, or its words, which can stand higher. Read only. */
function tailY(repo, rr, pane) {
  let base = rr.bottom, floor = Infinity;
  for (const k of repo.parentElement.children) {
    const q = k.getBoundingClientRect();
    if (q.height && q.top < rr.bottom && q.bottom > rr.top) base = Math.max(base, q.bottom);
  }
  const range = document.createRange();
  for (let a = repo; a && a !== pane && floor === Infinity; a = a.parentElement) {
    for (let n = a.nextElementSibling; n; n = n.nextElementSibling) {
      const q = n.getBoundingClientRect();
      if (!q.height || q.top <= rr.bottom) continue;
      floor = Math.min(floor, q.top);
      range.selectNodeContents(n);
      for (const w of range.getClientRects()) if (w.height) floor = Math.min(floor, w.top);
    }
  }
  return Math.min(base + 2, floor - 3.4);
}

/* One pane's tail and pen-tip dot: answers whether it wants another frame. */
function runningPen(THREE, tokens, api, el, p, dt) {
  const on = el.classList.contains("state-running");
  let run = p.run;
  if (on && (!run || !run.on)) {
    if (run) freeAll(p.group, p.meshes);
    p.meshes = null;
    run = p.run = { on: true, since: lastLine(el), lines: 0, shown: false, waited: 0, strike: -1, sig: "" };
  }
  if (!run) return false;
  if (on) {
    const n = linesSince(el, run.since);
    if (n) { run.lines += n; run.since = lastLine(el); }
    // A pen that never arrives (a table changed under it) is not waited on for ever.
    run.waited += dt;
    if (!run.shown) run.shown = underlined(el.dataset.repo) || run.waited > 5;
  } else if (run.on) {
    run.on = false;
    run.strike = run.shown ? 0 : -1;
    if (!run.shown) { freeAll(p.group, p.meshes); p.meshes = null; p.run = null; return false; }
  }
  if (!run.shown) return on;                       // the pen is still on its way: look again
  if (run.strike >= 0 && run.strike < 1) run.strike = api.reduced ? 1 : Math.min(1, run.strike + dt / STRIKE_S);

  const repo = el.querySelector(".head .repo");
  const rr = repo ? repo.getBoundingClientRect() : null, pr = el.getBoundingClientRect();
  const visible = !!(rr && rr.width && pr.width);
  // Where the layer's underline ends (shapes.js `underline`, placed by #331): the tail goes on from
  // there, at that height, and stops where the layer stops a line that grows: 14px short of the
  // pane's right edge (#332). It used to sit 2.2px under the name's own box, through the chip.
  const y = visible ? tailY(repo, rr, el) - pr.top + 1.2 : 0;
  const x0 = visible ? rr.right - pr.left + 8 : 0;
  const len = Math.max(0, Math.min(TAIL_MAX, GROW * run.lines, pr.width - 14 - x0));
  run.len = len;
  // The ink's extent on the viewport: the line (1.45px wide) and the dot (r 1.9) at its end.
  run.box = visible ? { x: pr.left + x0 - 0.9, y: pr.top + y - 1.3, w: len + 3.8, h: 3.8 } : null;
  const sig = [visible, x0.toFixed(1), y.toFixed(1), len, run.strike.toFixed(3)].join("|");
  if (sig === run.sig && p.meshes && p.meshes.every(m => m.parent === p.group)) return run.strike >= 0 && run.strike < 1;
  run.sig = sig;
  freeAll(p.group, p.meshes);
  p.meshes = [];
  if (visible) {
    const ink = flat(THREE, new THREE.Color().setRGB(...tokens.inks.pen, THREE.SRGBColorSpace));
    if (len > 0.5) p.meshes.push(add(THREE, p.group, ribbon(THREE, [[x0, y], [x0 + len, y + 0.6]], 1.45), ink, 1));
    const dot = new THREE.CircleGeometry(1.9, 12);
    dot.translate(x0 + len + 1, -(y + 0.6), 0);
    p.meshes.push(add(THREE, p.group, dot, ink.clone(), 1));
    if (run.strike > 0) {
      const a = [x0 - 3, y + 3], b = [x0 + len + 6, y - 3];
      const e = [a[0] + (b[0] - a[0]) * run.strike, a[1] + (b[1] - a[1]) * run.strike];
      p.meshes.push(add(THREE, p.group, ribbon(THREE, [a, e], 1.45), ink.clone(), 2));
    }
  }
  return run.strike >= 0 && run.strike < 1;
}

// ------------------------------------------------------------------------ the header count

/* Digits as a hand writes them, in a 5 x 9 box: the struck count is drawn, not typeset. */
const DIGITS = {
  0: Array.from({ length: 17 }, (_, i) => [2.5 + 2.4 * Math.cos(i / 16 * 6.3 - 1.7), 4.5 + 4.4 * Math.sin(i / 16 * 6.3 - 1.7)]),
  1: [[1, 2], [3, 0], [3, 9]],
  2: [[0.2, 2], [1.3, 0.3], [3.6, 0.2], [4.6, 2], [3.8, 4], [0, 9], [5, 9]],
  3: [[0.2, 1], [2, 0], [4.5, 1.5], [2.4, 4.2], [4.8, 6.5], [2.6, 9], [0, 8.2]],
  4: [[3.6, 9], [3.6, 0], [0, 6], [5, 6]],
  5: [[4.6, 0], [0.8, 0], [0.4, 4], [3, 3.6], [4.8, 6], [3, 9], [0, 8.3]],
  6: [[4, 0.3], [1.5, 1.5], [0.2, 5.5], [1, 8.6], [3.5, 8.8], [4.8, 6.5], [3.2, 4.4], [0.5, 5.5]],
  7: [[0, 0], [5, 0], [1.8, 9]],
  8: [[2.5, 4.3], [0.6, 2.4], [1.4, 0.2], [3.6, 0.2], [4.4, 2.2], [2.5, 4.3], [0.3, 6.6], [1.4, 8.9],
      [3.8, 8.9], [4.7, 6.6], [2.5, 4.3]],
  9: [[4.5, 3.5], [2.5, 5], [0.4, 3.2], [1.3, 0.4], [3.6, 0.2], [4.6, 2.5], [4, 6.5], [1.5, 9]],
};

const count = { last: null, old: "", strike: -1, mesh: null, sig: "" };

/* The count in the header, watched: when it changes, the old number is kept where the hand wrote
   it, beside the new one, and struck through in pen. One struck number is kept, like one struck
   mark per element in the layer. */
function headerCount(THREE, tokens, api, dt) {
  const el = document.getElementById("bellcount");
  const now = el ? el.textContent.trim() : "";
  if (count.last === null) { count.last = now; return false; }
  if (now !== count.last) {
    count.old = count.last;
    count.last = now;
    count.strike = 0;
    count.sig = "";
  }
  if (count.strike < 0 || !paperScene) return false;
  if (count.strike < 1) count.strike = api.reduced ? 1 : Math.min(1, count.strike + dt / STRIKE_S);
  const r = el ? el.getBoundingClientRect() : null;
  const digits = count.old.replace(/[^0-9]/g, "").slice(-4);
  const s = r && r.height ? r.height * 0.62 / 9 : 0;
  const sig = [digits, r ? r.left.toFixed(1) : "", r ? r.top.toFixed(1) : "", s.toFixed(2), count.strike.toFixed(3)].join("|");
  if (sig === count.sig && count.mesh && count.mesh.every(m => m.parent === paperScene)) return count.strike < 1;
  count.sig = sig;
  freeAll(paperScene, count.mesh);
  count.mesh = [];
  if (!digits || !s) return count.strike < 1;
  const width = digits.length * 6.5 * s;
  const x = r.left - width - 5, y = r.top + (r.height - 9 * s) / 2;
  const ink = flat(THREE, new THREE.Color().setRGB(...tokens.inks.pen, THREE.SRGBColorSpace));
  [...digits].forEach((d, i) => {
    const pts = DIGITS[d].map(([u, v]) => [x + (i * 6.5 + u) * s, y + v * s]);
    count.mesh.push(add(THREE, paperScene, ribbon(THREE, pts, 1.3), ink, api.order.paper + 3));
  });
  if (count.strike > 0) {
    const a = [x - 2, y + 9 * s * 0.62], b = [x + width + 1, y + 9 * s * 0.4];
    const e = [a[0] + (b[0] - a[0]) * count.strike, a[1] + (b[1] - a[1]) * count.strike];
    count.mesh.push(add(THREE, paperScene, ribbon(THREE, [a, e], 1.45), ink.clone(), api.order.paper + 4));
  }
  return count.strike < 1;
}

// ------------------------------------------------------------------------------ the frame

/* Every frame the layer draws: the running pens and the header count follow the page. Another
   frame only while a strike is being drawn -- an idle desk draws nothing. */
export function tick({ THREE, tokens, api }, dt) {
  let more = false;
  for (const [el, p] of Array.from(panes)) {
    if (!el.isConnected) { panes.delete(el); continue; }
    if (p.group && runningPen(THREE, tokens, api, el, p, dt)) more = true;
  }
  if (headerCount(THREE, tokens, api, dt)) more = true;
  return more;
}

/* What this skin draws of its own, for tests and a curious console -- the same module the page
   loaded, imported again by its URL: each pane's running pen, and the struck header count. */
export function inspect() {
  return {
    panes: Array.from(panes, ([el, p]) => ({
      repo: el.dataset.repo, running: !!(p.run && p.run.on), shown: !!(p.run && p.run.shown),
      lines: p.run ? p.run.lines : 0, tail: p.run ? (p.run.len ?? Math.min(TAIL_MAX, GROW * p.run.lines)) : 0,
      // The tail and its dot on the viewport (#332), while the pen is on the page.
      tailBox: p.run && p.run.shown && p.run.box ? Object.assign({}, p.run.box) : null,
      strike: p.run ? p.run.strike : -1, pieces: p.meshes ? p.meshes.filter(m => m.parent).length : 0,
    })),
    count: { now: count.last, old: count.old, strike: count.strike,
             pieces: count.mesh ? count.mesh.filter(m => m.parent).length : 0 },
    builds,
  };
}

/* The skin is going: the layer frees what is in its scenes; forget what this module kept. */
export function dispose() {
  panes.clear();
  paperScene = null;
  count.last = null;
  count.old = "";
  count.strike = -1;
  count.mesh = null;
  count.sig = "";
}
