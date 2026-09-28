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
    c = mix(c, uMax, (0.34 + 0.08 * grain * 20.0) * (1.0 - smoothstep(0.3, 1.0, d)));
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

const RAIL_BELOW = 90;
const GUTTER = 36;
const DRAW = 900;
const THROW = 0.3;
const PICK = 0.18;
const HOPS = [[0.18, 8], [0.12, 3]];
const FLAG = { w: 14, h: 10, x: 11, y: 48 };
const POSTS = [[[7, 38], [7, 48], [21, 48], [21, 38]], [[14, 48], [14, 62]]];
const HATCH = { top: 66, len: 84, gap: 6, x0: 5, x1: 31, rise: 10 };
const BALL = { x: 19, y: 34, w: 10, h: 7, from: [4, -14], mid: [1.5, 0] };

const recs = new Map();
let lastApi = null;

function flagOf(el) { return el.matches(".needs-human"); }
function doneOf(el) { return el.matches(".is-done, .state-done"); }
function errorOf(el) { return el.matches(".state-error"); }
function stale() { return document.body.matches(".is-stale"); }

function chalk() {
  return options.tools.pencil;
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

function free(hs) {
  for (const h of hs) h.dispose();
  return [];
}

function fresh(el) {
  return { el, repo: el.dataset.repo || "", group: null, box: null, rail: true,
           flag: { state: "none", t: 0, from: [0, 0], mesh: null }, throws: 0,
           done: { on: false, at: 0, out: 0, posts: [], hatch: [] },
           ball: { state: "none", t: 0, at: 0, out: 0, strokes: [], group: null }, hops: 0,
           seen: { flag: flagOf(el), done: doneOf(el), error: errorOf(el) } };
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
  const tune = chalk();
  rec.done.posts = POSTS.map((path, i) => api.stroke(g, { pts: path, nobow: true }, "pencil", { ink: "green", seed: 7 + i, tune }));
  rec.done.hatch = hatchPaths(rec.box.h).map((path, i) => api.stroke(g, path, "pencil", { seed: 31 + i, tune }));
  const ball = new THREE.Group();
  g.add(ball);
  rec.ball.group = ball;
  rec.ball.strokes = ballPaths().map((path, i) => api.stroke(ball, path, "pencil", { seed: 61 + i, tune }));
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
  rec.done.posts = rec.done.hatch = rec.ball.strokes = [];
  build(THREE, tokens, api, rec);
  api.request();
}

function start(rec, api) {
  const el = rec.el, instant = api.reduced || stale() || rec.rail;
  const now = { flag: flagOf(el), done: doneOf(el), error: errorOf(el) };
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
    const d = rec.done, b = rec.ball, pl = lengthOf(d.posts), hl = lengthOf(d.hatch);
    const on = !rec.rail;
    const shown = h => !h.dead;
    strokes += d.posts.concat(d.hatch, b.strokes).filter(shown).length;
    const at = on ? flagAt(rec) : null;
    const posts = on && pl ? Math.max(0, Math.min(1, Math.min(d.at, pl) / pl)) : 0;
    const hatch = on && hl ? Math.max(0, Math.min(1, (Math.min(d.at, pl + hl) - pl) / hl)) : 0;
    const bp = on ? ballAt(rec) : null;
    panes[rec.repo] = {
      flag: on ? rec.flag.state : "none", posts, hatch, ball: on ? b.state : "none",
      throws: rec.throws, hops: rec.hops, rail: rec.rail,
      flagBox: at ? viewBox(rec, at.p[0] - FLAG.w / 2, at.p[1] - FLAG.h / 2, at.p[0] + FLAG.w / 2, at.p[1] + FLAG.h / 2) : null,
      postsBox: on && posts > 0 ? viewBox(rec, 5, 36, 23, 64) : null,
      hatchBoxes: on && hatch > 0 ? hatchPaths(rec.box.h).map(p => viewBox(rec, HATCH.x0 - 2, p.pts[1][1] - 2, HATCH.x1 + 2, p.pts[0][1] + 2)) : [],
      ballBox: bp && b.state !== "none" ? viewBox(rec, BALL.x + bp[0] - 1.5, BALL.y + bp[1] - 1.5, BALL.x + bp[0] + BALL.w + 1.5, BALL.y + bp[1] + BALL.h + 1.5) : null,
    };
  }
  return { builds, ghosts: board.ghosts.map(g => ({ ...g })), top: board.top, panes, strokes,
           geometries: lastApi && lastApi.renderer ? lastApi.renderer.info.memory.geometries : null };
}
