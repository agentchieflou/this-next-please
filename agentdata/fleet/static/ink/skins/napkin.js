/* Napkin notes (#252, slice F of the ink epic #246): the desk written on a paper napkin.

   The stock is quilted two-ply with no rules: a diamond quilting pressed into the paper, the second
   ply showing where the seams are pressed through, and a fine dot emboss on each pillow. It is
   drawn procedurally in the paper shader, so there is no texture to fetch. The felt tip (the
   `marker`, which draws the error box) bleeds along that emboss: where its stroke crosses a seam
   the ink wicks further into the paper than on a pillow, and it soaks in behind the pen as it goes.
   A pane that has been idle a long time has a coffee ring under it.

   The marks are the paper state grammar (plan-ink §The state grammar), and every row is a class
   the page already sets. docs/skin-napkin.md maps each row onto its selector and says what the
   page does not have yet (the turn's length, the count's old number).

   What is drawn where:
   * `paper` -- the quilted stock under the whole page. Its colours are `--paper` and
     `--paper-seam`, the darkest the shading ever goes (skins.py declares the pair, and the text's
     contrast is checked against it).
   * `frame` -- per pane: the coffee ring, the felt tip's bleed and the running pen's tip. Each is
     built once per size and shown or hidden in `tick` from the page's classes and the ink layer's
     own marks, so a pane that changes state needs no new geometry.
   * `tick` -- reads the page (never writes it) and `Ink.inspect()` (what is on the paper).

   Colours live in skin.css as custom properties and are read through `tokens.css()`. No hex
   is written here (docs/desk-ink.md §Writing a skin, rule 3). */

/* A finding: a transcript line the page marks `denied` or `friction`. */
const FOUND = ".tile .transcript li:is(.denied, .friction)";

/* The same rows for both variants: a variant changes the stock and the inks, not the grammar. */
export function marks() {
  return [
    // A mark round the pane keeps inside it (#332): a pad of 0 or less, so the stroke and half its
    // width are on the napkin, not over the pane's border and cut away by the layer's clip.
    // idle: a pencil outline, and the name underlined in pencil.
    { selector: ".tile.state-idle", tool: "pencil", shape: "outline", pad: -5 },
    { selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" },
    // running: the name underlined in pen. The pen's tip rests at the end of it (`frame`).
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" },
    // needs you: the name and the question highlighted, the choices looped in pencil. The name's
    // highlight is erased when it is no longer needed: a name struck through reads as an agent
    // that has gone.
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves: "erased" },
    { selector: ".tile .asks:not([hidden]) .ask:not([hidden]) .ask-q", tool: "highlighter", shape: "lines" },
    { selector: ".tile .asks:not([hidden]) .ask:not([hidden]) .ask-choice:not([aria-pressed=\"true\"])",
      tool: "pencil", shape: "loop" },
    // answered: the chosen answer circled in pen. Its pencil loop is erased as the choice is made,
    // and the question's highlight is struck through in pen when the question goes -- which is
    // how the layer takes back any ink. The question is struck, never the agent's name.
    { selector: ".tile .ask:not([hidden]) .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "ellipse" },
    // error: the felt tip's box round the pane, and a bang in the margin.
    { selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },
    { selector: ".tile.state-error", tool: "red", shape: "bang" },
    // done: a green check in the margin. A quiet agent's chip says idle, so the fold's own word
    // arrives as `is-done` (#253); `state-done` is the chip's, while one is supervised.
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    // stale (#240): the chip's own words written in pencil as a margin note, an arrow from it to
    // the run's line, and a dashed pencil outline round the pane.
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".runline" },
    { selector: ".tile:has(.oldsession:not([hidden]))", tool: "pencil", shape: "outline", pad: -8, dash: true },
    // a finding: a transcript line the agent was refused or stopped on -- the lines the page
    // already marks as a problem (the legal pad reads them the same way, #251). A red ellipse
    // round the line, the highlighter on its kind, and its own words as a pencil note.
    { selector: FOUND, tool: "red", shape: "ellipse", pad: -4 },
    { selector: FOUND + " .k", tool: "highlighter", shape: "lines" },
    { selector: FOUND + " .v", tool: "pencil", shape: "write" },
    // the header count, handwritten: the unread count on the bell.
    { selector: "#bellcount", tool: "pen", shape: "write" },
  ];
}

/* `--paper` is what the layer reads to decide light or dark (the highlighter multiplies into a
   light napkin). The napkin's own `paper` hook draws the stock. */
export const options = { paper: "--paper", hand: true, speed: 1 };

export const sampleGround = false;

/* A pane idle a long time: idle, and its chip's age says a day or more (`ageChip` in app.js marks
   that `stale`). Both are classes the page already sets. */
const IDLE = ".tile.state-idle";
const AGED = ".chip.stale";

/* The felt tip's box and the running pen's line, as the mark table has them. */
const ERROR_ROW = ".tile.state-error";
const RUNNING_ROW = ".tile.state-running .head .repo";

/* How far behind the pen the felt tip's ink has soaked all the way in, in px of pen travel, and
   how long the last of it takes once the pen has lifted. */
const SOAK_PX = 180;
const SOAK_S = 0.7;

/* A pane narrower than this is a 48px rail (shapes.js says the same). */
const RAIL_BELOW = 90;

// ---------------------------------------------------------------------------------- colours

/* A custom property as [r, g, b, a] in 0-1 sRGB: `#rgb`, `#rrggbb`, `rgb()` or `rgba()`. */
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

// ---------------------------------------------------------------------------------- shaders

/* The quilt, shared by the paper and the felt tip's bleed so the ink runs down the very seams the
   paper shows. `p` is in page px, y down. The quilting is a diamond lattice whose seams are
   18.4px apart (26 / sqrt 2), the same spacing skin.css draws with `repeating-linear-gradient`. */
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

/* Every piece is a flat quad in the layer's camera (CSS px, y down drawn at -y). `vPage` is page
   px, whichever group the quad is in; `vLocal` is its own group's px. */
const VS = `
varying vec2 vPage; varying vec2 vLocal;
void main() {
  vec4 w = modelMatrix * vec4(position, 1.0);
  vPage = vec2(w.x, -w.y);
  vLocal = vec2(position.x, -position.y);
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

/* The stock, lit from the top left like the layer's own paper. It never goes darker than
   `--paper-seam`, which is the darkest end of the panel the text is checked against. */
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

/* A cup set down on the napkin, twice: a ring with a darker rim where the coffee dried, a faint
   wash inside it, and part of a second rim a little off the first. Never more than `--coffee`'s
   own alpha, which skins.py composites over the seam for the darkest panel. */
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

/* The felt tip soaking into the quilt along the loop the marker draws round a pane: shapes.js
   \`loop\` at offset \`uO\` with corner radius \`uRad\`, begun at the top left and drawn clockwise.
   \`uHead\` is how far along it the pen has drawn (px), \`uTail\` how far the last of it has soaked
   once the pen lifted. Where the path crosses a seam the ink runs further. */
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

// ---------------------------------------------------------------------------------- the pieces

/* What each pane has, built by `frame` and shown by `tick`. Keyed by the pane, which the layer
   hands to `frame` and never replaces while the pane is on the page. */
const panes = new Map();
/* The felt tip's soak per pane, kept across rebuilds so a resize does not soak it in again. */
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

/* A quad over `[x0, y0]-[x1, y1]` in its group's px, y down. */
function quad(THREE, x0, y0, x1, y1, material, order) {
  const g = new THREE.PlaneGeometry(x1 - x0, y1 - y0);
  g.translate((x0 + x1) / 2, -(y0 + y1) / 2, 0);
  const m = new THREE.Mesh(g, material);
  m.renderOrder = order;
  m.frustumCulled = false;
  return m;
}

/* The quilted stock under the whole page. */
export function paper({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const p = read(tokens, "--paper", tokens.bg), s = read(tokens, "--paper-seam", tokens.line);
  const mat = shader(THREE, PAPER_FS, {
    uPaper: { value: new THREE.Vector3(p[0], p[1], p[2]) },
    uSeam: { value: new THREE.Vector3(s[0], s[1], s[2]) },
  });
  scene.add(quad(THREE, 0, 0, w, h, mat, api.order.paper));
}

/* The length of the loop shapes.js draws round a box of `w` x `h` at offset `o`. */
function loopLength(w, h, o, rad) {
  const W = w + 2 * o, H = h + 2 * o;
  rad = Math.max(1, Math.min(rad, W / 3, H / 3));
  return { len: 2 * (W - 2 * rad) + 2 * (H - 2 * rad) + 2 * Math.PI * rad, rad };
}

/* One pane's pieces: the coffee ring, the felt tip's bleed along the error loop, and the pen's
   tip. All hidden until `show` says the page has them. */
export function frame({ THREE, scene, tokens, api }, el, box) {
  const rail = box.w < RAIL_BELOW;
  const seed = seedOf(el.dataset.repo);

  const coffee = read(tokens, "--coffee", tokens.muted.concat(0.14));
  // Where a cup was put down: on the open paper below the transcript's first lines and clear of
  // the reply row at the foot, a little further in on each pane so no two rings line up.
  const R = rail ? Math.max(12, box.w * 0.36) : Math.min(46, Math.max(24, Math.min(box.w, box.h) * 0.18));
  const c = rail ? [box.w * 0.5, box.h * 0.6]
                 : [box.w - R - 26 - seed * 40, Math.min(box.h - R - 90, box.h * 0.55 + seed * 60)];
  const ring = quad(THREE, c[0] - R - 8, c[1] - R - 8, c[0] + R + 8, c[1] + R + 8, shader(THREE, RING_FS, {
    uCoffee: { value: new THREE.Vector4(coffee[0], coffee[1], coffee[2], coffee[3]) },
    uC: { value: new THREE.Vector2(c[0], c[1]) }, uR: { value: R }, uSeed: { value: seed * 6.28 },
  }, true), api.order.frame);
  ring.name = "coffee";

  // The error row's loop: pad -7, so shapes.js draws it 4px in with a 7px corner (#332).
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

/* What is on the paper now, by pane: the felt tip's loop and the running pen's underline. */
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

/* Each piece of one pane shown as the page and the paper have it. Answers whether it is still
   soaking. Reads the page; never writes it. */
function show(rec, api, marks, dt) {
  const { el, ring, bleed, dot } = rec;
  const at = marks.get(el.dataset.repo) || {};

  // A pane idle a long time has a coffee ring under it. A cup is set down, not drawn: it is there
  // the frame the pane has been idle a day, and gone the frame the agent wakes.
  ring.visible = el.matches(IDLE) && !!el.querySelector(AGED);

  // The felt tip's bleed follows its loop, and stays with it once it is struck: ink that soaked in
  // does not come back out. It goes only with the mark.
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

  // The running pen's tip rests at the end of its underline once the line is drawn, and stays when
  // the line is struck: it is ink.
  const line = at.line;
  if (line && (line.drawn >= 1 || line.state === "struck")) {
    const r = el.getBoundingClientRect();
    // shapes.js `underline`: from 3px before the text to 8px past it, 1px under it, rising 1.2px.
    dot.position.set(line.box.x - r.left + line.box.w + 8, -(line.box.y - r.top + line.box.h + 2.2), 0);
    dot.visible = true;
  } else {
    dot.visible = false;
  }
  return soaking;
}

/* On every frame the layer draws: the pieces follow the page's classes and the marks. Asks for
   another frame only while the felt tip is still soaking in. */
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

/* What this skin has on the paper, per pane, for tests and a curious console: which pieces show,
   where the ring is (in the pane's px) and how far the felt tip has soaked. Reads; changes nothing. */
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
