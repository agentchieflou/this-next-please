export const expresses = {
  "*": { "needs_name": "flag", "needs_q": "flag", "needs_card": "flag", "running": "drive",
         "error_bang": "fumble", "error_box": "fumble", "done": "touchdown" }
};

const EXPRESSED = [
  { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline", grow: ".transcript > li", step: 12, cap: "arrow" },
  { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves: "erased" },
  { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-q", tool: "highlighter", shape: "lines" },
  { selector: ".tile.needs-human .approval:not([hidden]) .summary", tool: "highlighter", shape: "lines" },
  { selector: ".tile.needs-human .asks:not([hidden])", tool: "marker", shape: "loop", pad: -3 },
  { selector: ".tile.state-error .why", tool: "marker", shape: "loop", pad: 0 },
  { selector: ".tile.state-error", tool: "marker", shape: "bang" },
  { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
];

export function marks() {
  const rows = [
    { selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" },
    { selector: ".tile.state-waiting_approval .head .repo", tool: "pen", shape: "underline", dash: true, cap: "arrow" },
    { selector: ".tile.state-blocked .head .repo", tool: "red", shape: "underline", cap: "bar" },
    { selector: ".tile.state-blocked", tool: "red", shape: "cross" },
    { selector: ".tile.needs-human .ask:not([hidden]):not(.is-answered) .ask-choice", tool: "pencil", shape: "loop" },
    { selector: ".ask.is-answered .ask-q", tool: "pen", shape: "strike" },
    { selector: ".ask.is-answered .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "ellipse" },
    { selector: ".ask.is-answered:not(:has(.ask-choice[aria-pressed=\"true\"])) .ask-answer", tool: "pen", shape: "ellipse" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "write" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "arrow", to: ".runline" },
    { selector: ".tile:has(.oldsession:not([hidden]))", tool: "pencil", shape: "outline", dash: true, pad: -8 },
    { selector: ".tile .transcript > li.friction", tool: "red", shape: "ellipse", pad: -6 },
    { selector: ".tile .transcript > li.friction > .k", tool: "highlighter", shape: "lines" },
    { selector: ".tile .transcript > li.friction > .v", tool: "pencil", shape: "write" },
    { selector: "#bellcount", tool: "pen", shape: "write", rewrite: true },
  ];
  return document.body.matches(".ink-off") ? rows.concat(EXPRESSED) : rows;
}

const EVEN = { press: 1, pvar: 0, wob: 0.2, bow: 0, tin: 0, tout: 0 };

export const options = { paper: "--paper", hand: false, speed: 1.2,
                         tools: { pencil: { ...EVEN, w: 1.6 }, pen: { ...EVEN, w: 1.8 }, red: { ...EVEN, w: 1.8 },
                                  green: { ...EVEN, w: 2.4 } } };

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

const PAPER_FS = `
uniform vec3 uPaper; uniform vec3 uMax; uniform vec3 uYard; uniform vec3 uLo; uniform vec3 uHi;
uniform float uDpr; uniform vec2 uView; uniform float uTop;
float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
void main(){
  vec2 p = vec2(gl_FragCoord.x, uView.y * uDpr - gl_FragCoord.y) / uDpr;
  float below = step(uTop, p.y);
  float stripe = mod(floor((p.y - uTop) / ${YARD}.0), 2.0) * below;
  float blade = (h21(floor(vec2(p.x * 0.9, p.y * 0.35))) - 0.5) * 0.35;
  vec3 c = mix(uPaper, uMax, clamp(stripe * 0.85 + 0.15 + blade, 0.0, 1.0));
  float yd = mod(p.y - uTop, ${YARD}.0);
  float yard = below * (1.0 - smoothstep(0.6, 1.2, min(yd, ${YARD}.0 - yd)));
  float hd = mod(p.y - uTop, ${PITCH}.0);
  float tick = below * (1.0 - step(0.75, min(hd, ${PITCH}.0 - hd)));
  float hash = tick * max(1.0 - step(${HASH / 2}.0, abs(p.x - uView.x / 3.0)),
                          1.0 - step(${HASH / 2}.0, abs(p.x - uView.x * 2.0 / 3.0)));
  c = mix(c, uYard, max(yard, hash));
  gl_FragColor = vec4(clamp(c, uLo, uHi), 1.0);
}`;

let builds = 0;
let field = { top: 0 };

export function paper({ THREE, scene, tokens, api }) {
  builds += 1;
  const { w, h, dpr } = api.viewport;
  const head = document.querySelector("header");
  const top = Math.ceil(((head ? head.getBoundingClientRect().bottom : 0) + 4) / PITCH) * PITCH;
  field = { top };
  const paperC = rgbOf(tokens, "--paper", tokens.bg), maxC = rgbOf(tokens, "--turf-max", tokens.panel);
  const lo = paperC.map((v, i) => Math.min(v, maxC[i])), hi = paperC.map((v, i) => Math.max(v, maxC[i]));
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.ShaderMaterial({
    vertexShader: "void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: PAPER_FS, depthTest: false, depthWrite: false,
    uniforms: {
      uPaper: { value: new THREE.Vector3(...paperC) },
      uMax: { value: new THREE.Vector3(...maxC) },
      uYard: { value: new THREE.Vector3(...rgbOf(tokens, "--yard", tokens.line)) },
      uLo: { value: new THREE.Vector3(...lo) },
      uHi: { value: new THREE.Vector3(...hi) },
      uDpr: { value: dpr },
      uView: { value: new THREE.Vector2(w, h) },
      uTop: { value: top },
    },
  }));
  mesh.frustumCulled = false;
  mesh.position.set(w / 2, -h / 2, 0);
  mesh.renderOrder = api.order.paper;
  scene.add(mesh);
}

const RAIL_BELOW = 90;
const DRAW = 900;
const ADVANCE = 240;
const THROW = 0.3;
const PICK = 0.18;
const HOPS = [[0.18, 8], [0.12, 3]];
const LINE = 2;
const FLAG = { w: 14, h: 10, x: 11, y: 48 };
const POSTS = [[[7, 38], [7, 48], [21, 48], [21, 38]], [[14, 48], [14, 62]]];
const HATCH = { top: 66, len: 84, gap: 6, x0: 5, x1: 31, rise: 10 };
const BALL = { x: 19, y: 34, w: 10, h: 7, from: [4, -14], mid: [1.5, 0] };

const recs = new Map();
let lastApi = null;

function flagOf(el) { return el.matches(".needs-human"); }
function doneOf(el) { return el.matches(".is-done, .state-done"); }
function errorOf(el) { return el.matches(".state-error"); }
function liveOf(el) { return el.matches(".state-running, .state-waiting_approval, .needs-human"); }
function linesOf(el) { return el.querySelectorAll(".transcript > li").length; }
function stale() { return document.body.matches(".is-stale"); }

function scrimmageOf(rec) {
  const h = rec.el.querySelector(".head"), p = rec.el.getBoundingClientRect(), r = h && h.getBoundingClientRect();
  const y = r ? Math.round(r.bottom - p.top) + 6 : PITCH;
  return Math.min(y, Math.max(PITCH, rec.box.h - 8));
}

function hatchPaths(h) {
  const out = [];
  for (let y = HATCH.top; y <= HATCH.top + HATCH.len && y + HATCH.rise <= h - 8; y += HATCH.gap) {
    out.push({ pts: [[HATCH.x0, y + HATCH.rise], [HATCH.x1, y]], nobow: true });
  }
  return out;
}

function ballPaths() {
  const rx = BALL.w / 2, ry = BALL.h / 2, cx = rx, cy = ry, pts = [];
  for (let i = 0; i <= 28; i++) {
    const a = i / 28 * 2 * Math.PI;
    pts.push([cx + Math.cos(a) * rx, cy + Math.sin(a) * ry]);
  }
  const out = [{ pts, nobow: true, wob: 0.2 }, { pts: [[cx - rx * 0.6, cy], [cx + rx * 0.6, cy]], nobow: true, wob: 0 }];
  for (const dx of [-2, 0, 2]) out.push({ pts: [[cx + dx, cy - 1.4], [cx + dx, cy + 1.4]], nobow: true, wob: 0 });
  return out;
}

function lengthOf(hs) {
  return hs.reduce((a, h) => a + (h.dead ? 0 : h.len), 0);
}

function lay(hs, px) {
  let left = px;
  for (const h of hs) {
    if (h.dead) continue;
    h.head(Math.max(0, Math.min(h.len, left)));
    left -= h.len;
  }
}

function wipe(hs, px) {
  for (const h of hs) if (!h.dead) h.erase(px > 0 ? Math.max(-1, h.len - px) : Infinity);
}

function fresh(el) {
  return { el, repo: el.dataset.repo || "", group: null, box: null, rail: true,
           flag: { state: "none", t: 0, from: [0, 0], mesh: null }, throws: 0,
           done: { on: false, at: 0, out: 0, posts: [], hatch: [] },
           ball: { state: "none", t: 0, at: 0, out: 0, strokes: [], group: null }, hops: 0,
           drive: { live: false, lines: 0, at: 0, to: 0, scrimmage: null, first: null, side: null },
           seen: { flag: flagOf(el), done: doneOf(el), error: errorOf(el), live: liveOf(el), lines: linesOf(el) } };
}

function settle(rec) {
  rec.flag.state = rec.seen.flag ? "resting" : "none";
  rec.flag.t = 0;
  rec.done.on = rec.seen.done;
  rec.done.at = rec.seen.done ? Infinity : 0;
  rec.done.out = 0;
  rec.ball.state = rec.seen.error ? "resting" : "none";
  rec.ball.at = rec.seen.error ? Infinity : 0;
  rec.ball.out = 0;
  rec.drive.live = rec.seen.live;
  rec.drive.lines = rec.seen.lines;
  rec.drive.at = rec.drive.to = 0;
}

function bar(THREE, api, rgb, w, h, order) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({
    color: new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace), depthTest: false, depthWrite: false }));
  mesh.renderOrder = api.order.frame + order;
  mesh.visible = false;
  return mesh;
}

function build(THREE, tokens, api, rec) {
  const g = rec.group;
  if (!g || rec.rail) return;
  const c = tokens.waiting || [0.9, 0.7, 0.25];
  const cloth = new THREE.Mesh(new THREE.PlaneGeometry(FLAG.w, FLAG.h), new THREE.MeshBasicMaterial({
    color: new THREE.Color().setRGB(c[0], c[1], c[2], THREE.SRGBColorSpace), depthTest: false, depthWrite: false }));
  const knot = new THREE.Mesh(new THREE.CircleGeometry(2.4, 10), cloth.material);
  knot.position.set(-FLAG.w / 2, FLAG.h / 2, 0);
  const flag = new THREE.Group();
  flag.add(cloth, knot);
  flag.renderOrder = api.order.frame + 3;
  cloth.renderOrder = knot.renderOrder = api.order.frame + 3;
  flag.visible = false;
  g.add(flag);
  rec.flag.mesh = flag;
  rec.done.posts = POSTS.map((path, i) => api.stroke(g, { pts: path, nobow: true }, "pencil", { ink: "green", seed: 7 + i }));
  rec.done.hatch = hatchPaths(rec.box.h).map((path, i) => api.stroke(g, path, "pencil", { seed: 31 + i }));
  const ball = new THREE.Group();
  g.add(ball);
  rec.ball.group = ball;
  rec.ball.strokes = ballPaths().map((path, i) => api.stroke(ball, path, "pencil", { seed: 61 + i }));
  const d = rec.drive, w = rec.box.w;
  d.side = bar(THREE, api, rgbOf(tokens, "--yard", tokens.line), 1, rec.box.h, 1);
  d.side.position.set(0.5, -rec.box.h / 2, 0);
  d.scrimmage = bar(THREE, api, rgbOf(tokens, "--gi-scrimmage", tokens.line), w, LINE, 2);
  d.first = bar(THREE, api, rgbOf(tokens, "--gi-first", tokens.waiting || tokens.line), w, LINE, 2);
  g.add(d.side, d.scrimmage, d.first);
  show(rec);
}

function arc(from, to, k, lift) {
  return [from[0] + (to[0] - from[0]) * k, from[1] + (to[1] - from[1]) * k - lift * 4 * k * (1 - k)];
}

function flagAt(rec) {
  const f = rec.flag, rest = [FLAG.x + FLAG.w / 2, FLAG.y + FLAG.h / 2];
  if (f.state === "resting") return { p: rest, turn: 0 };
  if (f.state === "flying") { const k = Math.min(1, f.t / THROW); return { p: arc(f.from, rest, k, 60), turn: (1 - k) * 3 * Math.PI }; }
  if (f.state === "leaving") { const k = Math.min(1, f.t / PICK); return { p: arc(rest, f.from, k, 60), turn: k * 3 * Math.PI }; }
  return null;
}

function ballAt(rec) {
  const b = rec.ball;
  if (b.state === "none") return null;
  if (b.state === "drawing") return BALL.from;
  if (b.state === "hopping") {
    const [[d1, l1], [d2, l2]] = HOPS;
    if (b.t <= d1) return arc(BALL.from, BALL.mid, b.t / d1, l1);
    return arc(BALL.mid, [0, 0], Math.min(1, (b.t - d1) / d2), l2);
  }
  return [0, 0];
}

function goal(rec) {
  const y0 = scrimmageOf(rec), room = Math.max(0, Math.floor((rec.box.h - 8 - y0) / PITCH));
  return { y0, y1: y0 + Math.min(rec.drive.lines, room) * PITCH };
}

function show(rec) {
  const at = flagAt(rec), m = rec.flag.mesh;
  if (m) {
    m.visible = !!at;
    if (at) { m.position.set(at.p[0], -at.p[1], 0); m.rotation.z = at.turn; }
  }
  const d = rec.done, pl = lengthOf(d.posts), hl = lengthOf(d.hatch);
  lay(d.posts, Math.min(d.at, pl));
  lay(d.hatch, Math.max(0, Math.min(d.at, pl + hl) - pl));
  wipe(d.posts.concat(d.hatch), d.out);
  const b = rec.ball;
  if (b.group) {
    const p = ballAt(rec) || [0, 0];
    b.group.position.set(BALL.x + p[0], -(BALL.y + p[1]), 0);
    lay(b.strokes, b.state === "none" ? 0 : b.at);
    wipe(b.strokes, b.out);
  }
  const v = rec.drive;
  if (v.scrimmage) {
    const { y0 } = goal(rec), w = rec.box.w;
    v.side.visible = true;
    v.scrimmage.visible = v.live;
    v.scrimmage.position.set(w / 2, -y0, 0);
    v.first.visible = v.live && rec.el.matches(".state-running");
    v.first.position.set(w / 2, -(y0 + v.at), 0);
  }
}

export function frame({ THREE, scene, tokens, api }, el, box) {
  lastApi = api;
  const rec = recs.get(el) || fresh(el);
  if (!recs.has(el)) { settle(rec); recs.set(el, rec); }
  rec.group = scene;
  rec.box = { w: box.w, h: box.h };
  rec.rail = box.w < RAIL_BELOW;
  rec.flag.mesh = null;
  rec.ball.group = null;
  rec.drive.scrimmage = rec.drive.first = rec.drive.side = null;
  rec.done.posts = rec.done.hatch = rec.ball.strokes = [];
  build(THREE, tokens, api, rec);
  api.request();
}

function start(rec, api) {
  const el = rec.el, instant = api.reduced || stale() || rec.rail;
  const now = { flag: flagOf(el), done: doneOf(el), error: errorOf(el), live: liveOf(el), lines: linesOf(el) };
  const f = rec.flag;
  if (now.flag !== rec.seen.flag) {
    if (instant) f.state = now.flag ? "resting" : "none";
    else if (now.flag) {
      const h = el.querySelector(".head"), p = el.getBoundingClientRect(), r = h && h.getBoundingClientRect();
      f.from = r ? [r.right - p.left - FLAG.w, r.top - p.top + r.height / 2] : [rec.box.w - 20, 14];
      f.state = "flying"; f.t = 0; rec.throws += 1;
    } else if (f.state !== "none") {
      f.state = "leaving"; f.t = 0;
    }
  }
  const d = rec.done;
  if (now.done !== rec.seen.done) {
    d.on = now.done;
    if (now.done) { d.at = instant ? Infinity : 0; d.out = 0; }
    else d.out = instant ? Infinity : 0;
  }
  const b = rec.ball;
  if (now.error !== rec.seen.error) {
    if (now.error) { b.state = instant ? "resting" : "drawing"; b.at = instant ? Infinity : 0; b.out = 0; b.t = 0; }
    else b.out = instant ? Infinity : 0;
  }
  const v = rec.drive;
  v.live = now.live;
  v.lines = now.lines;
  if (rec.box) {
    const { y0, y1 } = goal(rec);
    v.to = now.live ? y1 - y0 : 0;
    if (instant || !now.live) v.at = v.to;
  }
  rec.seen = now;
}

function advance(rec, dt) {
  let more = false;
  const f = rec.flag;
  if (f.state === "flying") { f.t += dt; if (f.t >= THROW) f.state = "resting"; else more = true; }
  if (f.state === "leaving") { f.t += dt; if (f.t >= PICK) f.state = "none"; else more = true; }
  const d = rec.done, all = lengthOf(d.posts) + lengthOf(d.hatch);
  if (d.on && d.at < all) { d.at = Math.min(all, d.at + DRAW * dt); more = more || d.at < all; }
  if (!d.on && d.at > 0) {
    d.out += DRAW * dt;
    if (d.out >= Math.max(...d.posts.concat(d.hatch).map(h => h.len), 0)) { d.at = 0; d.out = 0; } else more = true;
  }
  const b = rec.ball, bl = lengthOf(b.strokes);
  if (b.state === "drawing") {
    b.at = Math.min(bl, b.at + DRAW * dt);
    if (b.at >= bl) { b.state = "hopping"; b.t = 0; rec.hops += 1; }
    more = true;
  } else if (b.state === "hopping") {
    b.t += dt;
    if (b.t >= HOPS[0][0] + HOPS[1][0]) b.state = "resting"; else more = true;
  }
  if (!rec.seen.error && b.state !== "none") {
    b.out += DRAW * dt;
    if (b.out >= Math.max(...b.strokes.map(h => h.len), 0)) { b.state = "none"; b.at = 0; b.out = 0; b.t = 0; } else more = true;
  }
  const v = rec.drive;
  if (v.at !== v.to) {
    const step = ADVANCE * dt;
    v.at = v.at < v.to ? Math.min(v.to, v.at + step) : Math.max(v.to, v.at - step);
    more = more || v.at !== v.to;
  }
  return more;
}

export function tick({ api }, dt) {
  lastApi = api;
  let more = false;
  for (const [el, rec] of Array.from(recs)) {
    if (!el.isConnected) { recs.delete(el); continue; }
    start(rec, api);
    if (api.reduced || rec.rail) {
      if (rec.flag.state === "flying") rec.flag.state = "resting";
      if (rec.flag.state === "leaving") rec.flag.state = "none";
      if (rec.done.on) rec.done.at = Infinity; else if (rec.done.at > 0) { rec.done.at = 0; rec.done.out = 0; }
      if (rec.ball.state === "drawing" || rec.ball.state === "hopping") { rec.ball.state = "resting"; rec.ball.at = Infinity; }
      if (!rec.seen.error) { rec.ball.state = "none"; rec.ball.at = 0; rec.ball.out = 0; }
      rec.drive.at = rec.drive.to;
    } else if (advance(rec, Math.min(dt, 0.05))) {
      more = true;
    }
    show(rec);
  }
  return more;
}

export function dispose() {
  recs.clear();
}

function viewBox(rec, x, y, r, b) {
  const p = rec.el.getBoundingClientRect();
  return { x: p.left + x, y: p.top + y, r: p.left + r, b: p.top + b };
}

export function inspect() {
  const panes = {};
  let strokes = 0;
  for (const rec of recs.values()) {
    const d = rec.done, b = rec.ball, v = rec.drive, pl = lengthOf(d.posts), hl = lengthOf(d.hatch);
    const on = !rec.rail;
    const shown = h => !h.dead;
    strokes += d.posts.concat(d.hatch, b.strokes).filter(shown).length;
    const at = on ? flagAt(rec) : null;
    const posts = on && pl ? Math.max(0, Math.min(1, Math.min(d.at, pl) / pl)) : 0;
    const hatch = on && hl ? Math.max(0, Math.min(1, (Math.min(d.at, pl + hl) - pl) / hl)) : 0;
    const bp = on ? ballAt(rec) : null;
    const y0 = on && rec.box ? goal(rec).y0 : null;
    panes[rec.repo] = {
      flag: on ? rec.flag.state : "none", posts, hatch, ball: on ? b.state : "none",
      throws: rec.throws, hops: rec.hops, rail: rec.rail,
      scrimmage: on && v.scrimmage && v.scrimmage.visible ? y0 : null,
      first: on && v.first && v.first.visible ? y0 + v.at : null,
      drive: { lines: v.lines, at: v.at, to: v.to, live: v.live },
      flagBox: at ? viewBox(rec, at.p[0] - FLAG.w / 2, at.p[1] - FLAG.h / 2, at.p[0] + FLAG.w / 2, at.p[1] + FLAG.h / 2) : null,
      postsBox: on && posts > 0 ? viewBox(rec, 5, 36, 23, 64) : null,
      hatchBoxes: on && hatch > 0 ? hatchPaths(rec.box.h).map(p => viewBox(rec, HATCH.x0 - 2, p.pts[1][1] - 2, HATCH.x1 + 2, p.pts[0][1] + 2)) : [],
      ballBox: bp && b.state !== "none" ? viewBox(rec, BALL.x + bp[0] - 1.5, BALL.y + bp[1] - 1.5, BALL.x + bp[0] + BALL.w + 1.5, BALL.y + bp[1] + BALL.h + 1.5) : null,
    };
  }
  return { builds, top: field.top, panes, strokes,
           geometries: lastApi && lastApi.renderer ? lastApi.renderer.info.memory.geometries : null };
}
