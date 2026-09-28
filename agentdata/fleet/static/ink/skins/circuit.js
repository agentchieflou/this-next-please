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
const count = { delivered: 0, arrived: 0, skipped: 0 };
const PULSE_S = 0.32;
const IN_FLIGHT = 3;
const LED = 3;
const HALO = 6;
const DOT = 2.5;
const SOOT = { press: 0.35, pvar: 0.2 };
const SPEED = 900;

function boardOf(el) {
  let b = boards.get(el);
  if (!b) {
    b = { el, scene: null, box: null, rail: true, pad: null, trace: null, seen: null, flight: [],
          delivered: 0, led: "none", lamp: [], scorch: null };
    boards.set(el, b);
  }
  return b;
}

function free(o) {
  if (!o) return;
  if (o.parent) o.parent.remove(o);
  if (o.geometry) o.geometry.dispose();
  if (o.material) o.material.dispose();
}

function colourOf(THREE, rgb) {
  return new THREE.Color().setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
}

export function frame(ctx, el, box) {
  const { THREE, scene, tokens, api } = ctx;
  builds += 1;
  const b = boardOf(el);
  b.scene = scene;
  b.box = box;
  b.rail = box.w < RAIL_BELOW;
  b.pad = b.trace = null;
  b.lamp = [];
  b.led = "none";
  for (const p of b.flight) p.mesh = null;
  if (b.scorch && (b.scorch.going || !el.matches(".state-error"))) b.scorch = null;
  else if (b.scorch) b.scorch.strokes = [];
  if (b.rail) {
    b.flight = [];
    b.scorch = null;
    return;
  }
  const [r, g, bl] = rgbOf(tokens, "--copper", tokens.line);
  const copper = new THREE.MeshBasicMaterial({ color: new THREE.Color().setRGB(r, g, bl, THREE.SRGBColorSpace),
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
  b.pad = [px, py, PAD, PAD];
  b.trace = [x0, TRACE_Y - TRACE_W / 2, x1 - x0, TRACE_W];
  signals(ctx, b, true);
}

function lamp(ctx, b) {
  const { THREE, tokens, api } = ctx, el = b.el;
  const want = b.rail ? "none" : el.matches(".needs-human") ? "amber"
    : el.matches(".is-done") || el.matches(".state-done") ? "green" : "none";
  if (want === b.led && (want === "none" || (b.lamp[0] && b.lamp[0].parent === b.scene))) return;
  for (const o of b.lamp) free(o);
  b.lamp = [];
  b.led = want;
  if (want === "none") return;
  const c = colourOf(THREE, want === "amber" ? tokens.waiting : tokens.done);
  const at = [14, b.box.h - 14];
  const halo = new THREE.Mesh(new THREE.CircleGeometry(HALO, 24),
                              new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: 0.28,
                                                            depthTest: false, depthWrite: false }));
  const led = new THREE.Mesh(new THREE.CircleGeometry(LED, 16),
                             new THREE.MeshBasicMaterial({ color: c, depthTest: false, depthWrite: false }));
  halo.renderOrder = api.order.frame + 1;
  led.renderOrder = api.order.frame + 2;
  for (const o of [halo, led]) {
    o.position.set(at[0], -at[1], 0);
    b.scene.add(o);
    b.lamp.push(o);
  }
}

function soot(ctx, b) {
  const el = b.el, why = el.querySelector(".why");
  const p = el.getBoundingClientRect(), r = why ? why.getBoundingClientRect() : null;
  const x = r && r.width ? r.left - p.left : 14, y = r && r.height ? r.bottom - p.top : 40;
  const w = Math.max(24, Math.min(r && r.width ? r.width : 60, 90));
  return [[[x + 2, y + 1.5], [x + w * 0.9, y + 2.5]], [[x + 8, y + 4.5], [x + w * 0.6, y + 5]]].map((pts, i) =>
    ctx.api.stroke(b.scene, { pts, nobow: true }, "marker", { seed: i + 3, tune: SOOT }));
}

function scorch(ctx, b, rest) {
  const { api } = ctx;
  const error = !b.rail && b.el.matches(".state-error");
  const s = b.scorch;
  if (error && (!s || s.going)) {
    if (s) for (const h of s.strokes) h.dispose();
    const strokes = soot(ctx, b);
    b.scorch = { strokes, len: strokes.reduce((n, h) => n + h.len, 0), at: 0, going: false };
    if (rest || api.reduced) scorchAt(b.scorch, b.scorch.len);
  } else if (error && !s.strokes.length) {
    s.strokes = soot(ctx, b);
    s.len = s.strokes.reduce((n, h) => n + h.len, 0);
    scorchAt(s, s.len);
  } else if (!error && s && !s.going) {
    s.going = true;
    s.at = 0;
    if (api.reduced) scorchOff(b);
  }
}

function scorchAt(s, at) {
  s.at = Math.min(s.len, at);
  let left = s.at;
  for (const h of s.strokes) {
    h.head(Math.min(h.len, Math.max(0, left)));
    left -= h.len;
  }
}

function scorchOff(b) {
  for (const h of b.scorch.strokes) h.dispose();
  b.scorch = null;
}

function signals(ctx, b, rest) {
  lamp(ctx, b);
  scorch(ctx, b, rest);
}

export function tick(ctx, dt) {
  const { THREE, tokens, api } = ctx;
  const quiet = document.body.matches(".is-stale, .is-replaying");
  let more = false;
  for (const [el, b] of Array.from(boards)) {
    if (!el.isConnected || !b.scene || !b.scene.parent) {
      boards.delete(el);
      continue;
    }
    const lines = el.querySelectorAll(".transcript > li");
    if (!b.seen) b.seen = new WeakSet(lines);
    for (const li of lines) {
      if (b.seen.has(li)) continue;
      b.seen.add(li);
      count.arrived += 1;
      if (b.rail || quiet || !el.matches(".state-running")) continue;
      if (api.reduced) count.skipped += 1;
      else if (b.flight.length < IN_FLIGHT) b.flight.push({ t: 0, mesh: null });
    }
    if (!b.box) continue;
    signals(ctx, b, false);
    const s = b.scorch;
    if (s && !s.going && s.at < s.len) {
      scorchAt(s, s.at + SPEED * dt);
      more = more || s.at < s.len;
    } else if (s && s.going) {
      s.at = Math.min(s.len, s.at + SPEED * dt);
      let left = s.at;
      for (const h of s.strokes) {
        h.erase(Math.min(h.len, Math.max(0, left)));
        left -= h.len;
      }
      if (s.at >= s.len) scorchOff(b);
      else more = true;
    }
    if (!b.trace) continue;
    const [x0, , w] = b.trace;
    b.flight = b.flight.filter(p => {
      p.t += dt;
      if (p.t >= PULSE_S) {
        free(p.mesh);
        count.delivered += 1;
        b.delivered += 1;
        return false;
      }
      if (!p.mesh || p.mesh.parent !== b.scene) {
        p.mesh = new THREE.Mesh(new THREE.CircleGeometry(DOT, 12),
                                new THREE.MeshBasicMaterial({ color: colourOf(THREE, tokens.accent),
                                                              depthTest: false, depthWrite: false }));
        p.mesh.renderOrder = api.order.frame + 1;
        b.scene.add(p.mesh);
      }
      p.mesh.position.set(x0 + w * (1 - p.t / PULSE_S), -TRACE_Y, 0);
      return true;
    });
    if (b.flight.length) more = true;
  }
  return more;
}

export function dispose() {
  boards.clear();
}

export function inspect() {
  const panes = {};
  let inFlight = 0;
  for (const [el, b] of boards) {
    if (!el.isConnected || !b.scene || !b.scene.parent) continue;
    inFlight += b.flight.length;
    const s = b.scorch;
    const pane = { led: b.led, pulses: b.delivered, scorch: !s || !s.len ? 0 : Math.round((s.going ? 1 - s.at / s.len : s.at / s.len) * 1000) / 1000 };
    if (b.trace) {
      const ox = b.scene.position.x, oy = -b.scene.position.y;
      const at = ([x, y, w, h]) => ({ x: ox + x, y: oy + y, w, h });
      Object.assign(pane, { at: { x: ox, y: oy }, pad: at(b.pad), trace: at(b.trace) });
    }
    panes[el.dataset.repo] = pane;
  }
  return { builds, pulses: { delivered: count.delivered, inFlight, arrived: count.arrived, skipped: count.skipped }, panes };
}
