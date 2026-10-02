const VENDOR = "/static/vendor/three/three.module.min.js";
const LAYOUT = "/static/map/layout.js";
const KEYS = ["islands", "lanes", "nodes"];
const TREE = ["class", "data-on", "data-node", "data-default", "data-name"];
const PAGE = ["style", "data-theme", "class"];
const SKIN = ["data-skin", "data-skin-variant"];
const SHADE = [0.82, 0.82, 1, 0.68, 0.68, 0.68];
const LIFT = 0.0625;
const PAD = 1.08;
const WORDS = ".say, .branch, button";
const plugins = [];
let late = null;

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

function parseColour(css, THREE) {
  const s = String(css || "").trim().toLowerCase();
  const m = /^rgba?\(([^)]*)\)$/.exec(s);
  if (m) {
    const v = m[1].split(/[\s,/]+/).filter(Boolean);
    const a = v.length > 3 ? parseFloat(v[3]) / (v[3].endsWith("%") ? 100 : 1) : 1;
    return [v[0] / 255, v[1] / 255, v[2] / 255, a].map(x => clamp(Number(x) || 0, 0, 1));
  }
  if (!s || s === "transparent" || !THREE) return [0, 0, 0, s === "transparent" ? 0 : 1];
  const out = { r: 0, g: 0, b: 0 };
  new THREE.Color().setStyle(s, THREE.SRGBColorSpace).getRGB(out, THREE.SRGBColorSpace);
  return [out.r, out.g, out.b, 1];
}

function context(canvas) {
  const attrs = { antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: "high-performance" };
  let gl = null, why = "";
  try { gl = canvas.getContext("webgl2", attrs); } catch (e) { why = String((e && e.message) || e); }
  if (!gl) {
    try { gl = canvas.getContext("webgl", attrs); } catch (e) { why = String((e && e.message) || e); }
  }
  if (!gl) throw new Error("no WebGL context" + (why ? ": " + why : ""));
  return gl;
}

/** @param {number[]} c @returns {number} */
function luminance(c) {
  const f = v => (v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}

/** @param {number[]} a @param {number[]} b @returns {number} */
function contrast(a, b) {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/** @param {number[]} text @param {number[]} bg @returns {number[]} */
function structural(text, bg) {
  for (let step = 100; step >= 0; step--) {
    const c = text.map((v, i) => Math.round((v + (bg[i] - v) * step / 100) * 255) / 255);
    if (contrast(c, bg) >= 3) return c;
  }
  return text.slice(0, 3);
}

/** @param {number[]} c @returns {string} */
function hex(c) {
  return "#" + c.slice(0, 3).map(v => Math.round(clamp(v, 0, 1) * 255).toString(16).padStart(2, "0")).join("");
}

function tokens(THREE) {
  const cs = getComputedStyle(document.body);
  /** @param {string} name @returns {string} */
  const css = name => cs.getPropertyValue(name.startsWith("--") ? name : "--" + name).trim();
  /** @param {string} name @returns {number[]} */
  const rgb = name => parseColour(css(name), THREE).slice(0, 3);
  const t = { css, rgb };
  for (const k of ["bg", "panel", "line", "accent", "muted", "text"]) t[k] = rgb(k);
  t.ink = structural(t.text, t.bg);
  return t;
}

/** @param {Element} li @returns {string} */
const idOf = li => (li && li.getAttribute("data-node")) || "";

/** @param {Element} tree */
function outlineOf(tree) {
  const kids = (el, sel) => Array.from(el.querySelectorAll(":scope > ul > " + sel));
  const projects = Array.from(tree.querySelectorAll(':scope > [data-node^="p:"]'), p => {
    const id = idOf(p), name = p.getAttribute("data-name") || id.slice(2), def = p.getAttribute("data-default") || "";
    const branches = [];
    for (const group of kids(p, '[data-node^="bs:"]')) {
      for (const b of kids(group, '[data-node^="b:"]')) branches.push({ id: idOf(b), unmerged: b.classList.contains("unmerged") });
    }
    const checkouts = kids(p, '[data-node^="c:"]').map(c => ({
      id: idOf(c), main: c.classList.contains("main"), on: c.getAttribute("data-on") || "",
      agent: idOf(kids(c, '[data-node^="a:"]')[0])
    }));
    return { id, default: def ? "b:" + name + ":" + def : "", branches, checkouts };
  });
  const net = tree.querySelector(':scope > [data-node="n:network"]');
  if (!net) return { projects };
  const ids = kids(net, "[data-node]").map(idOf);
  const one = id => (ids.includes(id) ? id : "");
  return { projects, network: {
    server: one("n:server"), install: one("n:install"), approvals: one("n:approvals"),
    windows: ids.filter(id => id.startsWith("w:")), sources: ids.filter(id => id.startsWith("s:")),
    stale: Array.from(tree.querySelectorAll('[data-node^="a:"].stale'), idOf) } };
}

function block(THREE) {
  const g = new THREE.BoxGeometry(1, 1, 1);
  g.clearGroups();
  const n = g.attributes.position.count, shade = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) shade.fill(SHADE[Math.floor(i / 4)], i * 3, i * 3 + 3);
  g.setAttribute("color", new THREE.BufferAttribute(shade, 3));
  return g;
}

function instanced(THREE, geometry, material, cap, from) {
  const m = new THREE.InstancedMesh(geometry, material, cap);
  m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(cap * 3), 3);
  if (from) {
    m.instanceMatrix.array.set(from.instanceMatrix.array);
    m.instanceColor.array.set(from.instanceColor.array);
  }
  m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  m.instanceColor.setUsage(THREE.DynamicDrawUsage);
  m.frustumCulled = false;
  m.count = from ? from.count : 0;
  m.visible = m.count > 0;
  return m;
}

export function use(plugin) {
  if (!plugin || typeof plugin !== "object" || plugins.includes(plugin)) return false;
  plugins.push(plugin);
  if (late) late(plugin);
  return true;
}

export async function start(host) {
  const canvas = document.createElement("canvas");
  const gl = context(canvas);
  const onLost = () => host.off("the WebGL context was lost");
  canvas.addEventListener("webglcontextlost", onLost);
  const [THREE, L] = await Promise.all([import(q(VENDOR)), import(q(LAYOUT))]);
  const renderer = new THREE.WebGLRenderer({ canvas, context: gl, antialias: true, alpha: true, premultipliedAlpha: true });
  const scene = new THREE.Scene(), camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const box = block(THREE), ink = new THREE.Color(), m4 = new THREE.Matrix4(), v3 = new THREE.Vector3();
  const meshes = {}, reserved = { islands: 0, lanes: 0, nodes: 0 };
  for (const key of KEYS) {
    meshes[key] = instanced(THREE, box, new THREE.MeshBasicMaterial({ vertexColors: true }), 64, null);
    scene.add(meshes[key]);
  }
  meshes.links = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial());
  meshes.links.frustumCulled = false;
  meshes.links.visible = false;
  scene.add(meshes.links);

  const dirty = { outline: true, colours: true, size: true };
  let T = null, laid = null, outline = null, placed = new Map(), tops = new Map(), shapes = [];
  let raf = 0, last = 0, frames = 0, samples = 0, calls = 0, triangles = 0, first = 0, busy = false;
  let W = 0, H = 0, DPR = 0, stopped = false;

  const kick = () => { if (!raf && !stopped) raf = requestAnimationFrame(draw); };
  const invalidate = () => { dirty.outline = true; kick(); };
  const paint = () => { dirty.colours = true; kick(); };
  const call = (p, name, ...args) => {
    if (typeof p[name] !== "function") return undefined;
    try { return p[name](...args); } catch (e) {
      console.error("map: a plugin's " + name + ": " + String((e && e.message) || e));
      return undefined;
    }
  };

  function grow(key, need) {
    const old = meshes[key], cap = old.instanceMatrix.count;
    if (need <= cap) return old;
    const m = instanced(THREE, box, old.material, Math.max(need, cap * 2), old);
    scene.remove(old);
    old.dispose();
    scene.add(m);
    meshes[key] = m;
    return m;
  }

  function reserve(mesh, n) {
    const key = typeof mesh === "string" ? mesh : KEYS.find(k => meshes[k] === mesh);
    if (!KEYS.includes(key) || !(n > 0)) return null;
    const from = reserved[key];
    reserved[key] += n;
    const m = grow(key, meshes[key].count + n);
    m4.makeScale(0, 0, 0);
    for (let i = from; i < from + n; i++) m.setMatrixAt(i, m4);
    m.instanceMatrix.needsUpdate = true;
    invalidate();
    return { key, start: from, count: n };
  }

  function wire() {
    const pts = [];
    for (const [a, b] of laid.links) {
      const p = laid.nodes[a], r = laid.nodes[b];
      pts.push(p.x, p.y, p.z, r.x, r.y, r.z);
    }
    const line = meshes.links;
    let at = line.geometry.getAttribute("position");
    if (!at || at.array.length < pts.length) {
      const cap = Math.max(pts.length, at ? at.array.length * 2 : 96);
      line.geometry.dispose();
      line.geometry = new THREE.BufferGeometry();
      at = new THREE.BufferAttribute(new Float32Array(cap), 3);
      at.setUsage(THREE.DynamicDrawUsage);
      line.geometry.setAttribute("position", at);
    }
    at.array.set(pts);
    at.needsUpdate = true;
    line.geometry.setDrawRange(0, pts.length / 3);
    line.visible = pts.length > 0;
  }

  function rebuild() {
    const was = outline, next = outlineOf(host.tree), D = L.DIMS;
    laid = L.layout(next);
    const lists = { islands: [], lanes: [], nodes: [] };
    tops = new Map();
    shapes = [];
    for (const [id, n] of Object.entries(laid.nodes)) {
      tops.set(id, [n.x, n.y + n.h / 2, n.z]);
      shapes.push([n.x, n.y, n.z, n.w, n.h, n.d]);
      if (n.kind === "island") lists.islands.push([id, n]);
      else if (n.kind !== "agent") lists.nodes.push([id, n]);
    }
    for (const l of laid.lanes) {
      const w = l.trunk ? D.trunkW : l.unmerged ? D.laneW : D.stubW;
      const dx = Math.abs(l.to[0] - l.from[0]), dz = Math.abs(l.to[1] - l.from[1]), along = dx >= dz;
      const b = { x: (l.from[0] + l.to[0]) / 2, y: LIFT / 2, z: (l.from[1] + l.to[1]) / 2,
                  w: along ? dx : w, h: LIFT, d: along ? w : dz };
      lists.lanes.push([l.id, b]);
      tops.set(l.id, [b.x, LIFT, b.z]);
      shapes.push([b.x, b.y, b.z, b.w, b.h, b.d]);
    }
    placed = new Map();
    for (const key of KEYS) {
      const list = lists[key], base = reserved[key], m = grow(key, base + list.length);
      list.forEach(([id, b], i) => {
        m.setMatrixAt(base + i, m4.makeScale(b.w, b.h, b.d).setPosition(b.x, b.y, b.z));
        m.setColorAt(base + i, ink);
        placed.set(id, { mesh: m, key, index: base + i });
      });
      m.count = base + list.length;
      m.visible = m.count > 0;
      m.instanceMatrix.needsUpdate = true;
      m.instanceColor.needsUpdate = true;
    }
    wire();
    outline = next;
    for (const p of plugins) call(p, "rebuilt", was, next, placed, laid);
  }

  function recolour() {
    T = tokens(THREE);
    ink.setRGB(T.ink[0], T.ink[1], T.ink[2], THREE.SRGBColorSpace);
    for (const key of KEYS) {
      const m = meshes[key];
      for (let i = reserved[key]; i < m.count; i++) m.setColorAt(i, ink);
      m.instanceColor.needsUpdate = true;
    }
    meshes.links.material.color.copy(ink);
    for (const p of plugins) call(p, "recoloured", T);
  }

  function resize() {
    const w = Math.max(1, host.stage.clientWidth), h = Math.max(1, host.stage.clientHeight);
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (w === W && h === H && dpr === DPR) return false;
    W = w;
    H = h;
    DPR = dpr;
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    return true;
  }

  function fit() {
    const b = laid ? laid.bounds : { minX: 0, maxX: 0, minZ: 0, maxZ: 0 };
    const cx = (b.minX + b.maxX) / 2, cz = (b.minZ + b.maxZ) / 2;
    const far = 2 * (b.maxX - b.minX + b.maxZ - b.minZ) + 20;
    camera.position.set(cx + far, far, cz + far);
    camera.lookAt(cx, 0, cz);
    camera.updateMatrixWorld();
    const e = camera.matrixWorldInverse.elements, lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
    for (const [x, y, z, w, h, d] of shapes.length ? shapes : [[cx, 0.5, cz, 2, 1, 2]]) {
      for (let a = 0; a < 3; a++) {
        const c = e[a] * x + e[a + 4] * y + e[a + 8] * z + e[a + 12];
        const r = (Math.abs(e[a]) * w + Math.abs(e[a + 4]) * h + Math.abs(e[a + 8]) * d) / 2;
        lo[a] = Math.min(lo[a], c - r);
        hi[a] = Math.max(hi[a], c + r);
      }
    }
    const aspect = (W || 1) / (H || 1);
    let w = Math.max(hi[0] - lo[0], 2) * PAD, h = Math.max(hi[1] - lo[1], 2) * PAD;
    if (w / h > aspect) h = w / aspect;
    else w = h * aspect;
    const mx = (lo[0] + hi[0]) / 2, my = (lo[1] + hi[1]) / 2;
    camera.left = mx - w / 2;
    camera.right = mx + w / 2;
    camera.top = my + h / 2;
    camera.bottom = my - h / 2;
    camera.near = -hi[2] - 1;
    camera.far = -lo[2] + 1;
    camera.updateProjectionMatrix();
  }

  function prepare() {
    let refit = false;
    if (dirty.size) { dirty.size = false; refit = resize(); }
    if (dirty.colours) { dirty.colours = false; recolour(); }
    if (dirty.outline) { dirty.outline = false; rebuild(); refit = true; }
    if (refit) fit();
  }

  function render() {
    renderer.render(scene, camera);
    calls = renderer.info.render.calls;
    triangles = renderer.info.render.triangles;
  }

  function draw(now) {
    raf = 0;
    if (stopped) return;
    const dt = last ? clamp((now - last) / 1000, 0, 0.1) : 1 / 60;
    last = now;
    prepare();
    busy = false;
    for (const p of plugins) if (call(p, "frame", dt) === true) busy = true;
    render();
    frames += 1;
    if (frames === 1) {
      first = Math.round(performance.now());
      try { performance.mark("map:first-draw"); } catch (e) {}
    }
    if (busy) kick();
    else last = 0;
  }

  /** @param {Node} n @returns {boolean} */
  const words = n => {
    const el = n && (n.nodeType === 1 ? /** @type {Element} */ (n) : n.parentElement);
    return !!(el && el.closest(WORDS));
  };
  const treeMo = new MutationObserver(rs => { if (rs.some(r => !words(r.target))) invalidate(); });
  const watchTree = () => {
    const attrs = new Set(TREE);
    for (const p of plugins) for (const a of Array.isArray(p.attrs) ? p.attrs : []) if (typeof a === "string" && a) attrs.add(a);
    treeMo.disconnect();
    treeMo.observe(host.tree, { childList: true, subtree: true, attributes: true, attributeFilter: Array.from(attrs) });
  };
  const pageMo = new MutationObserver(paint);
  const ro = new ResizeObserver(() => { dirty.size = true; kick(); });
  const scheme = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;
  const onSheet = e => {
    const el = /** @type {Element} */ (e.target);
    if (el && el.tagName === "LINK" && /\bstylesheet\b/i.test(el.getAttribute("rel") || "")) paint();
  };
  const onResize = () => { if (Math.min(2, window.devicePixelRatio || 1) !== DPR) { dirty.size = true; kick(); } };
  const ctx = { THREE, scene, camera, renderer, meshes, get tokens() { return T; }, kick, invalidate, reserve,
                stage: host.stage, tree: host.tree };
  const attach = p => { call(p, "attach", ctx); watchTree(); invalidate(); };

  function inspect() {
    const out = {};
    for (const p of plugins) {
      const o = call(p, "inspect");
      if (o && typeof o === "object") Object.assign(out, o);
    }
    return Object.assign(out, {
      frames, samples, calls, triangles, nodes: placed.size, busy: !!raf || busy, first_draw_ms: first,
      colours: T ? { ink: hex(T.ink), bg: hex(T.bg) } : null, size: { w: W, h: H, dpr: DPR },
      canvas: canvas.isConnected, reserved: Object.assign({}, reserved), plugins: plugins.length });
  }

  function sample(points) {
    if (stopped) return null;
    prepare();
    render();
    samples += 1;
    if (!Array.isArray(points)) return null;
    const r = canvas.getBoundingClientRect(), k = canvas.width / Math.max(1, r.width), px = new Uint8Array(4);
    return points.map(p => {
      gl.readPixels(Math.floor((p.x - r.left) * k), canvas.height - 1 - Math.floor((p.y - r.top) * k), 1, 1,
                    gl.RGBA, gl.UNSIGNED_BYTE, px);
      return Array.from(px);
    });
  }

  function screen(id) {
    const at = tops.get(id);
    if (!at) return null;
    v3.set(at[0], at[1], at[2]).project(camera);
    const r = canvas.getBoundingClientRect();
    return { x: r.left + (v3.x + 1) / 2 * r.width, y: r.top + (1 - v3.y) / 2 * r.height };
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    if (late === attach) late = null;
    treeMo.disconnect();
    pageMo.disconnect();
    ro.disconnect();
    if (scheme && scheme.removeEventListener) scheme.removeEventListener("change", paint);
    document.removeEventListener("load", onSheet, true);
    removeEventListener("resize", onResize);
    canvas.removeEventListener("webglcontextlost", onLost);
    try {
      renderer.dispose();
      renderer.forceContextLoss();
    } catch (e) {
    }
    canvas.remove();
  }

  await host.ready;
  host.stage.appendChild(canvas);
  for (const p of plugins) call(p, "attach", ctx);
  late = attach;
  watchTree();
  pageMo.observe(document.documentElement, { attributes: true, attributeFilter: PAGE });
  pageMo.observe(document.body, { attributes: true, attributeFilter: SKIN });
  ro.observe(host.stage);
  if (scheme && scheme.addEventListener) scheme.addEventListener("change", paint);
  document.addEventListener("load", onSheet, true);
  addEventListener("resize", onResize);
  kick();
  return { inspect, sample, screen, stop };
}
