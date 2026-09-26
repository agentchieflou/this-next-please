export const GRID = 28;
export const MAJOR = 5;

const RULED = { snap: GRID };

export function marks() {
  const stale = ".oldsession:not([hidden])";
  const open = ".asks:not([hidden]) .ask:not([hidden])";
  return [
    Object.assign({ selector: `.tile.state-idle:not(:has(${stale}))`, tool: "pencil", shape: "outline" }, RULED),
    Object.assign({ selector: ".tile.state-idle .head .repo", tool: "pencil", shape: "underline" }, RULED),
    Object.assign({ selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" }, RULED),
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines", leaves: "erased" },
    { selector: `.tile ${open}:not(:has(.ask-choice[aria-pressed="true"])) .ask-q`, tool: "highlighter", shape: "lines" },
    { selector: `.tile ${open} .ask-choice[aria-pressed="false"]`, tool: "pencil", shape: "loop" },
    { selector: `.tile ${open} .ask-choice[aria-pressed="true"]`, tool: "pen", shape: "ellipse" },
    Object.assign({ selector: ".tile.state-error", tool: "marker", shape: "outline" }, RULED),
    { selector: ".tile.state-error", tool: "red", shape: "bang" },
    { selector: ".tile.is-done", tool: "green", shape: "check" },
    { selector: `.tile ${stale}`, tool: "pencil", shape: "write" },
    { selector: `.tile ${stale}`, tool: "pencil", shape: "arrow", to: ".runline" },
    Object.assign({ selector: `.tile:has(${stale})`, tool: "pencil", shape: "outline", dash: true }, RULED),
    { selector: ".tile .transcript li.friction", tool: "red", shape: "ellipse" },
    { selector: ".tile .transcript li.friction .k", tool: "highlighter", shape: "lines" },
    { selector: ".tile .transcript li.friction .v", tool: "red", shape: "write" },
    { selector: "footer #counts", tool: "pen", shape: "write" },
    Object.assign({ selector: ".tile .head .trace[data-trace]", tool: "pencil", shape: "divider" }, RULED),
  ];
}

export function options() {
  return {
    paper: "--paper",
    hand: true,
    speed: 1,
    tools: { pencil: { w: 1.05, press: 0.9, pvar: 0.04, wob: 0, bow: 0, wmin: 0.94, tin: 0, tout: 0 } },
    series: false,
  };
}

function colour(THREE, tokens, name, fallback) {
  const css = tokens.css(name) || fallback;
  const c = new THREE.Color();
  if (css) return c.setStyle(css, THREE.SRGBColorSpace);
  const m = tokens.muted;
  return c.setRGB(m[0], m[1], m[2], THREE.SRGBColorSpace);
}

function rules(THREE, w, h, every, skip) {
  const pts = [];
  for (let i = 1, x = every; x < w; i++, x += every) {
    if (skip && i % skip === 0) continue;
    pts.push(new THREE.Vector3(x + 0.5, 0, 0), new THREE.Vector3(x + 0.5, -h, 0));
  }
  for (let i = 1, y = every; y < h; i++, y += every) {
    if (skip && i % skip === 0) continue;
    pts.push(new THREE.Vector3(0, -(y + 0.5), 0), new THREE.Vector3(w, -(y + 0.5), 0));
  }
  return new THREE.BufferGeometry().setFromPoints(pts);
}

export function paper({ THREE, scene, tokens, api }) {
  const { w, h } = api.viewport;
  const stock = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
                               new THREE.MeshBasicMaterial({ color: colour(THREE, tokens, "--paper") }));
  stock.position.set(w / 2, -h / 2, 0);
  stock.renderOrder = api.order.paper;
  const minor = new THREE.LineSegments(rules(THREE, w, h, GRID, MAJOR),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens, "--grid") }));
  minor.renderOrder = api.order.paper + 1;
  const major = new THREE.LineSegments(rules(THREE, w, h, GRID * MAJOR, 0),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens, "--grid-major") }));
  major.renderOrder = api.order.paper + 2;
  scene.add(stock, minor, major);
}

const plots = new Map();

function hourOf(canvas) {
  const raw = canvas && canvas.dataset ? canvas.dataset.trace : "";
  if (!raw) return null;
  const [peak, list] = raw.split("|");
  const minutes = (list || "").split(" ").filter(Boolean).map(s => ({ n: parseFloat(s) || 0, needs: s.endsWith("!") }));
  return { peak: Math.max(1, parseFloat(peak) || 1), minutes };
}

function unplot(p) {
  for (const o of p.objs) {
    p.group.remove(o);
    if (o.geometry) o.geometry.dispose();
    if (o.material) o.material.dispose();
  }
  p.objs = [];
}

function plot(THREE, tokens, p) {
  const el = p.el;
  const canvas = el.querySelector(".head .trace");
  const hour = hourOf(canvas);
  const pr = el.getBoundingClientRect();
  const cr = canvas ? canvas.getBoundingClientRect() : null;
  const sig = !hour || !cr || !cr.width || !cr.height ? "none"
    : [canvas.dataset.trace, (cr.left - pr.left).toFixed(1), (cr.top - pr.top).toFixed(1), cr.width.toFixed(1),
       cr.height.toFixed(1), ((pr.left % GRID) + GRID) % GRID, ((pr.top % GRID) + GRID) % GRID,
       tokens.css("--ink-trace"), tokens.css("--ink-red")].join("|");
  if (sig === p.sig) return false;
  p.sig = sig;
  unplot(p);
  p.at = null;
  if (sig === "none" || !hour.minutes.length) return true;
  const base = Math.round(cr.bottom / GRID) * GRID - pr.top;
  const x0 = cr.left - pr.left, step = cr.width / hour.minutes.length, tall = cr.height;
  const line = [], needs = [];
  hour.minutes.forEach((m, i) => {
    const x = x0 + (i + 0.5) * step;
    line.push(new THREE.Vector3(x, -(base - Math.min(1, m.n / hour.peak) * tall), 0));
    if (m.needs) needs.push(new THREE.Vector3(x, -base, 0), new THREE.Vector3(x, -(base - tall), 0));
  });
  const trace = new THREE.Line(new THREE.BufferGeometry().setFromPoints(line),
                               new THREE.LineBasicMaterial({ color: colour(THREE, tokens, "--ink-trace", tokens.css("--ink-pen")) }));
  p.objs.push(trace);
  if (needs.length) {
    p.objs.push(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(needs),
                                       new THREE.LineBasicMaterial({ color: colour(THREE, tokens, "--ink-red") })));
  }
  for (const o of p.objs) {
    o.renderOrder = p.order;
    p.group.add(o);
  }
  p.at = { trace: canvas.dataset.trace, base: base + pr.top, points: line.map(v => [v.x + pr.left, pr.top - v.y]),
           needs: needs.length / 2 };
  return true;
}

export function plotted() {
  return Array.from(plots.values()).filter(p => p.at && p.el.isConnected)
    .map(p => Object.assign({ repo: p.el.dataset.repo }, p.at));
}

export function frame({ THREE, scene, tokens, api }, el) {
  const p = { el, group: scene, objs: [], sig: "", order: api.order.frame, at: null };
  plots.set(el, p);
  plot(THREE, tokens, p);
}

export function tick({ THREE, tokens }) {
  for (const [el, p] of Array.from(plots)) {
    if (!el.isConnected || !p.group.parent) {
      plots.delete(el);
      continue;
    }
    plot(THREE, tokens, p);
  }
  return false;
}

export function dispose() {
  plots.clear();
}
