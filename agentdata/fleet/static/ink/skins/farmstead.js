const SHEET = "/static/skins/farmstead/sprites.svg";
const RASTER = 1;
const CROPS = ["crop-seed", "crop-sprout", "crop-sun", "crop-bloom", "crop-wilted"];
const PROPS = ["produce", "cloud", "hen-a", "hen-b", "cat-sleep", "cat-stretch", "crow"];
const SPRITES = ["soil", "plank"].concat(CROPS, PROPS);
const SIZE = { plank: [16, 8], produce: [8, 8], cloud: [16, 8], "hen-a": [12, 12], "hen-b": [12, 12],
               "cat-sleep": [16, 8], "cat-stretch": [16, 8], crow: [8, 8] };
const GROWS = ["crop-seed", "crop-sprout", "crop-bloom"];
const ROWS_PER_S = 60;
const SCALE = { soil: 2, band: 2, board: 1, crop: 2 };
const CROP_ART = [2, 14];
const CROP_BOX = 24;
const SHADOW = 3;
const ORDER = { shadow: -13, paper: -12, board: -11, crop: -10 };

export function marks() {
  return [
    { selector: ".tile.needs-human .head .repo", tool: "highlighter", shape: "lines" },
    { selector: ".tile.state-running .head .repo", tool: "pen", shape: "underline" },
    { selector: ".tile.state-error", tool: "marker", shape: "loop", pad: -7 },
    { selector: ".tile:is(.state-done, .is-done)", tool: "green", shape: "check" },
    { selector: ".tile .oldsession:not([hidden])", tool: "pencil", shape: "outline", pad: 0, dash: true },
    { selector: ".tile .asks:not([hidden]) .ask-choice[aria-pressed=\"true\"]", tool: "pen", shape: "loop", pad: 2 },
    { selector: ".tile .transcript li.friction", tool: "red", shape: "ellipse", pad: 2 },
  ];
}

export const options = { hand: true, speed: 1 };

export const sampleGround = false;

let sheet = null;
let made = 0, freed = 0;
let lastApi = null;
let U = null;
let look = "";
let bands = [];
const recs = new Map();
const waited = new WeakSet();

function commonest(px) {
  const n = new Map();
  let best = "", most = 0;
  for (let i = 0; i < px.length; i += 4) {
    if (px[i + 3] < 128) continue;
    const k = px[i] + "," + px[i + 1] + "," + px[i + 2];
    const c = (n.get(k) || 0) + 1;
    n.set(k, c);
    if (c > most) { most = c; best = k; }
  }
  return best ? best.split(",").map(v => Number(v) / 255) : [0.5, 0.5, 0.5];
}

function pixels(doc, id, s) {
  const node = doc.getElementById(id) || doc.querySelector("[id=\"" + id + "\"]");
  if (!node) throw new Error("sprites.svg has no #" + id);
  const [w, h] = s.sizes[id];
  const px = s.data[id];
  px.fill(0);
  for (const r of node.getElementsByTagName("rect")) {
    const hex = /^#([0-9a-f]{6})$/i.exec(r.getAttribute("fill") || "");
    if (!hex) throw new Error("#" + id + ": a rect whose fill is not #rrggbb");
    const n = parseInt(hex[1], 16), rgb = [n >> 16 & 255, n >> 8 & 255, n & 255];
    const x0 = Number(r.getAttribute("x") || 0), y0 = Number(r.getAttribute("y") || 0);
    const x1 = Math.min(w, x0 + Number(r.getAttribute("width") || 0));
    const y1 = Math.min(h, y0 + Number(r.getAttribute("height") || 0));
    for (let y = Math.max(0, y0); y < y1; y++) {
      for (let x = Math.max(0, x0); x < x1; x++) {
        const i = (y * w + x) * 4;
        px[i] = rgb[0]; px[i + 1] = rgb[1]; px[i + 2] = rgb[2]; px[i + 3] = 255;
      }
    }
  }
  s.base[id] = commonest(px);
}

function load(THREE, api) {
  if (sheet) return sheet;
  const s = sheet = { textures: {}, data: {}, sizes: {}, base: {}, loaded: false, failed: "",
                      nearest: THREE.NearestFilter };
  for (const id of SPRITES) {
    const [w, h] = (SIZE[id] || [16, 16]).map(n => n * RASTER);
    s.sizes[id] = [w, h];
    s.data[id] = new Uint8Array(w * h * 4);
    const t = new THREE.DataTexture(s.data[id], w, h, THREE.RGBAFormat);
    t.magFilter = THREE.NearestFilter;
    t.minFilter = THREE.NearestFilter;
    t.generateMipmaps = false;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.flipY = false;
    t.colorSpace = THREE.NoColorSpace;
    s.textures[id] = t;
    made += 1;
  }
  fetch(q(SHEET)).then(r => {
    if (!r.ok) throw new Error("sprites.svg answered " + r.status);
    return r.text();
  }).then(text => {
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error("sprites.svg does not parse");
    for (const id of SPRITES) pixels(doc, id, s);
    if (sheet !== s) return;
    for (const t of Object.values(s.textures)) t.needsUpdate = true;
    s.loaded = true;
    if (U) {
      U.uSoilRef.value.fromArray(s.base.soil);
      U.uWoodRef.value.fromArray(s.base.plank);
    }
    api.request();
  }).catch(e => {
    s.failed = String((e && e.message) || e);
    console.error("ink: the farmstead skin: " + s.failed);
  });
  return s;
}

const GLSL_COMMON = `
  vec3 toLin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }
  vec3 toSrgb(vec3 c) { c = max(c, 0.0);
    return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }
  float lum(vec3 lin) { return dot(lin, vec3(0.2126, 0.7152, 0.0722)); }
  // One texel of a sprite, at its centre: the texture is NearestFilter too, so this is the pixel
  // of the art and nothing between two. A weather recolours it by its brightness against the
  // sprite's commonest colour, which is how skin.css's cave and rain were drawn from daylight.
  vec3 art(sampler2D map, vec2 grid, vec2 texel, float recolour, vec3 base, vec3 ref) {
    vec2 t = mod(floor(texel), grid);
    vec3 c = toLin(texture2D(map, (t + 0.5) / grid).rgb);
    if (recolour > 0.5) c = toLin(base) * lum(c) / max(lum(toLin(ref)), 1e-4);
    return c;
  }`;

const VERT = `
  attribute vec2 aArt;
  attribute float aSide;
  varying vec2 vArt;
  varying float vSide;
  void main() {
    vArt = aArt;
    vSide = aSide;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;

const FLAT_FRAG = GLSL_COMMON + `
  uniform sampler2D uMap; uniform vec2 uGrid; uniform float uRecolour; uniform vec3 uBase;
  uniform vec3 uRef; uniform float uLight; uniform vec3 uSun;
  varying vec2 vArt;
  void main() {
    vec3 c = art(uMap, uGrid, vArt, uRecolour, uBase, uRef) * uLight * toLin(uSun);
    gl_FragColor = vec4(toSrgb(c), 1.0);
  }`;

const BOARD_FRAG = GLSL_COMMON + `
  uniform sampler2D uMap; uniform vec2 uGrid; uniform float uRecolour; uniform vec3 uBase;
  uniform vec3 uRef; uniform vec3 uSun; uniform float uAmbient; uniform float uDiffuse;
  uniform vec3 uLightDir; uniform float uChar; uniform vec3 uEmber;
  varying vec2 vArt; varying float vSide;
  void main() {
    float row = clamp(floor(vArt.y), 0.0, uGrid.y - 1.0);
    vec3 c = art(uMap, uGrid, vec2(vArt.x, row), uRecolour, uBase, uRef);
    vec2 out2 = vSide < 0.5 ? vec2(0.0, 1.0) : vSide < 1.5 ? vec2(1.0, 0.0)
              : vSide < 2.5 ? vec2(0.0, -1.0) : vec2(-1.0, 0.0);
    float tilt = mix(0.55, -0.55, (row + 0.5) / uGrid.y);
    vec3 n = normalize(vec3(out2 * tilt, 1.0));
    float lit = uAmbient + uDiffuse * max(dot(n, normalize(uLightDir)), 0.0);
    c *= lit * toLin(uSun);
    c = mix(c, c * 0.22 + toLin(uEmber) * 0.05, uChar);
    gl_FragColor = vec4(toSrgb(c), 1.0);
  }`;

const CROP_FRAG = `
  uniform sampler2D uOld; uniform sampler2D uNew; uniform float uRows;
  varying vec2 vArt;
  void main() {
    vec2 t = floor(vArt);
    vec4 c = (15.0 - t.y) < uRows ? texture2D(uNew, (t + 0.5) / 16.0) : texture2D(uOld, (t + 0.5) / 16.0);
    if (c.a < 0.5) discard;
    gl_FragColor = vec4(c.rgb, 1.0);
  }`;

const FILL_FRAG = `
  uniform vec3 uColor; uniform float uAlpha;
  void main() { gl_FragColor = vec4(uColor, uAlpha); }`;

function uniforms(THREE) {
  if (U) return U;
  const v3 = () => ({ value: new THREE.Vector3(1, 1, 1) });
  U = {
    uSun: v3(), uEmber: v3(), uPaper: v3(), uShade: v3(),
    uSoilBase: v3(), uSoilRef: v3(), uSoilRecolour: { value: 0 },
    uWoodBase: v3(), uWoodRef: v3(), uWoodRecolour: { value: 0 },
    uBandLight: { value: 1 }, uAmbient: { value: 0.45 }, uDiffuse: { value: 0.62 },
    uLightDir: { value: new THREE.Vector3(-0.45, 0.55, 0.9) },
  };
  if (sheet && sheet.loaded) {
    U.uSoilRef.value.fromArray(sheet.base.soil);
    U.uWoodRef.value.fromArray(sheet.base.plank);
  }
  return U;
}

function rgbOf(THREE, text) {
  const s = String(text || "").trim();
  if (!s) return null;
  const c = new THREE.Color();
  try { c.setStyle(s, THREE.SRGBColorSpace); } catch (e) { return null; }
  const o = { r: 0, g: 0, b: 0 };
  c.getRGB(o, THREE.SRGBColorSpace);
  return [o.r, o.g, o.b];
}

function readLook(THREE, tokens) {
  const u = uniforms(THREE);
  const css = name => (tokens && typeof tokens.css === "function" ? tokens.css(name) : "");
  const sig = ["--farm-paper", "--farm-soil", "--farm-wood", "--farm-sun", "--farm-band-light",
               "--farm-ambient", "--farm-diffuse"].map(css).join("|") +
              "|" + String(tokens && tokens.human) + "|" + String(tokens && tokens.panel);
  if (sig === look) return false;
  look = sig;
  const paper = rgbOf(THREE, css("--farm-paper")) || (tokens && tokens.panel) || [1, 1, 1];
  u.uPaper.value.fromArray(paper);
  u.uSun.value.fromArray(rgbOf(THREE, css("--farm-sun")) || [1, 1, 1]);
  u.uEmber.value.fromArray((tokens && tokens.human) || [1, 0.3, 0.2]);
  const soil = rgbOf(THREE, css("--farm-soil"));
  u.uSoilRecolour.value = soil ? 1 : 0;
  if (soil) u.uSoilBase.value.fromArray(soil);
  const wood = rgbOf(THREE, css("--farm-wood"));
  u.uWoodRecolour.value = wood ? 1 : 0;
  if (wood) u.uWoodBase.value.fromArray(wood);
  const num = (name, dflt) => { const n = parseFloat(css(name)); return Number.isFinite(n) ? n : dflt; };
  u.uBandLight.value = num("--farm-band-light", 1);
  u.uAmbient.value = num("--farm-ambient", 0.45);
  u.uDiffuse.value = num("--farm-diffuse", 0.62);
  return true;
}

function awaitSheet() {
  const link = document.head && document.head.querySelector("link[data-skin]");
  if (!link || link.sheet || waited.has(link)) return;
  waited.add(link);
  link.addEventListener("load", () => { if (lastApi) lastApi.request(); }, { once: true });
}

function shader(THREE, frag, own) {
  return new THREE.ShaderMaterial({
    uniforms: Object.assign({}, U, own || {}), vertexShader: VERT, fragmentShader: frag,
    transparent: true, depthTest: false, depthWrite: false,
  });
}

function unitOf(api, css) {
  const dpr = (api && api.viewport && api.viewport.dpr) || 1;
  return Math.max(1, Math.floor(css * dpr + 1e-6)) / dpr;
}

function quadsGeometry(THREE, quads) {
  const pos = [], artc = [], side = [], idx = [];
  for (const [x0, y0, x1, y1, ax0, ay0, ax1, ay1, s, swap] of quads) {
    const base = pos.length / 3;
    const corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
    for (const [x, y] of corners) {
      pos.push(x, -y, 0);
      const fx = x1 === x0 ? 0 : (x - x0) / (x1 - x0), fy = y1 === y0 ? 0 : (y - y0) / (y1 - y0);
      if (swap) artc.push(ax0 + (ax1 - ax0) * fy, ay0 + (ay1 - ay0) * fx);
      else artc.push(ax0 + (ax1 - ax0) * fx, ay0 + (ay1 - ay0) * fy);
      side.push(s || 0);
    }
    idx.push(base, base + 2, base + 1, base, base + 3, base + 2);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("aArt", new THREE.Float32BufferAttribute(artc, 2));
  g.setAttribute("aSide", new THREE.Float32BufferAttribute(side, 1));
  g.setIndex(idx);
  return g;
}

function mesh(THREE, geometry, material, order) {
  const m = new THREE.Mesh(geometry, material);
  m.renderOrder = order;
  m.frustumCulled = false;
  return m;
}

export function ground({ THREE, scene, tokens, api }) {
  lastApi = api;
  const s = load(THREE, api);
  uniforms(THREE);
  readLook(THREE, tokens);
  awaitSheet();
  const { w, h } = api.viewport;
  const u = unitOf(api, SCALE.soil);
  const mat = shader(THREE, FLAT_FRAG, {
    uMap: { value: s.textures.soil }, uGrid: { value: new THREE.Vector2(16, 16) },
    uRecolour: U.uSoilRecolour, uBase: U.uSoilBase, uRef: U.uSoilRef, uLight: { value: 1 },
  });
  scene.add(mesh(THREE, quadsGeometry(THREE, [[0, 0, w, h, 0, 0, w / u, h / u, 0]]), mat, api.order.ground));
}

export function paper({ THREE, scene, tokens, api }) {
  lastApi = api;
  const s = load(THREE, api);
  uniforms(THREE);
  readLook(THREE, tokens);
  bands = [];
  for (const sel of ["body > header", "body > footer"]) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const mat = shader(THREE, FLAT_FRAG, {
      uMap: { value: s.textures.plank }, uGrid: { value: new THREE.Vector2(16, 8) },
      uRecolour: U.uWoodRecolour, uBase: U.uWoodBase, uRef: U.uWoodRef, uLight: U.uBandLight,
    });
    const m = mesh(THREE, quadsGeometry(THREE, [[0, 0, 1, 1, 0, 0, 1, 1, 0]]), mat, api.order.paper);
    scene.add(m);
    const band = { sel, el, mesh: m, sig: "" };
    bands.push(band);
    placeBand(THREE, api, band);
  }
}

function placeBand(THREE, api, band) {
  const r = band.el.getBoundingClientRect();
  const u = unitOf(api, SCALE.band);
  const sig = [r.left, r.top, r.width, r.height, u].map(v => v.toFixed(2)).join(",");
  if (sig === band.sig) return false;
  band.sig = sig;
  const g = band.mesh.geometry;
  const x0 = r.left, y0 = r.top, x1 = r.right, y1 = r.bottom;
  const p = g.getAttribute("position"), a = g.getAttribute("aArt");
  const corners = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
  corners.forEach(([x, y], i) => {
    p.setXYZ(i, x, -y, 0);
    a.setXY(i, x / u, (y - y0) / u);
  });
  p.needsUpdate = a.needsUpdate = true;
  band.mesh.visible = r.width > 0 && r.height > 0;
  return true;
}

export function frame({ THREE, scene, tokens, api }, el, box) {
  lastApi = api;
  const s = load(THREE, api);
  uniforms(THREE);
  readLook(THREE, tokens);
  const u = unitOf(api, SCALE.board);
  const T = 8 * u, half = Math.round(4 * u * api.viewport.dpr) / api.viewport.dpr;
  const x0 = -half, y0 = -half, x1 = box.w + half, y1 = box.h + half;
  const L = (x1 - x0) / u;

  const off = SHADOW * u;
  scene.add(mesh(THREE, quadsGeometry(THREE, [[x0 + off, y0 + off, x1 + off, y1 + off, 0, 0, 1, 1, 0]]),
                 shader(THREE, FILL_FRAG, { uColor: { value: new THREE.Vector3(0, 0, 0) }, uAlpha: { value: 0.32 } }),
                 ORDER.shadow));
  scene.add(mesh(THREE, quadsGeometry(THREE, [[0, 0, box.w, box.h, 0, 0, 1, 1, 0]]),
                 shader(THREE, FILL_FRAG, { uColor: U.uPaper, uAlpha: { value: 1 } }), ORDER.paper));
  const H = (y1 - y0 - 2 * T) / u;
  const boards = shader(THREE, BOARD_FRAG, {
    uMap: { value: s.textures.plank }, uGrid: { value: new THREE.Vector2(16, 8) },
    uRecolour: U.uWoodRecolour, uBase: U.uWoodBase, uRef: U.uWoodRef, uChar: { value: 0 },
  });
  scene.add(mesh(THREE, quadsGeometry(THREE, [
    [x0, y0, x1, y0 + T, 0, 0, L, 8, 0, false],
    [x1 - T, y0 + T, x1, y1 - T, 5, 8, 5 + H, 0, 1, true],
    [x0, y1 - T, x1, y1, 11, 8, 11 + L, 0, 2, false],
    [x0, y0 + T, x0 + T, y1 - T, 3, 0, 3 + H, 8, 3, true],
  ]), boards, ORDER.board));

  const rec = recs.get(el) || { el, repo: el.dataset.repo || "", shown: cropOf(el), queue: [], rows: 16,
                                 grows: 0, stage: GROWS.indexOf(cropOf(el)) };
  rec.repo = el.dataset.repo || rec.repo;
  const cu = unitOf(api, SCALE.crop);
  const crop = new THREE.ShaderMaterial({
    uniforms: { uOld: { value: s.textures[rec.shown] }, uNew: { value: s.textures[rec.shown] }, uRows: { value: 16 } },
    vertexShader: VERT, fragmentShader: CROP_FRAG, transparent: true, depthTest: false, depthWrite: false,
  });
  const [a0, a1] = CROP_ART, span = (a1 - a0) * cu;
  rec.crop = mesh(THREE, quadsGeometry(THREE, [[0, 0, span, span, a0, a0, a1, a1, 0]]), crop, ORDER.crop);
  rec.cropSize = span;
  rec.boards = boards;
  rec.box = { w: box.w, h: box.h };
  rec.frame = { x: x0, y: y0, w: x1 - x0, h: y1 - y0, thick: T };
  rec.at = "";
  scene.add(rec.crop);
  recs.set(el, rec);
  place(rec, api);
  paint(rec);
}

function cropOf(el) {
  const c = el.classList;
  if (c.contains("needs-human") || c.contains("state-needs_human") || c.contains("state-blocked") ||
      c.contains("state-error")) return "crop-wilted";
  if (c.contains("state-done") || c.contains("is-done")) return "crop-bloom";
  if (c.contains("state-waiting_approval")) return "crop-sun";
  if (c.contains("state-running")) return "crop-sprout";
  return "crop-seed";
}

function place(rec, api) {
  const chip = rec.el.querySelector(".head .chip");
  const m = rec.crop;
  if (!chip || !m) return false;
  const r = chip.getBoundingClientRect();
  const p = rec.el.getBoundingClientRect();
  const sig = [r.left, r.top, r.width, r.height, p.left, p.top].map(v => v.toFixed(2)).join(",");
  if (sig === rec.at) return false;
  rec.at = sig;
  const visible = r.width > 0 && r.height > 0 && p.width > 0;
  m.visible = visible;
  if (!visible) return true;
  const cs = getComputedStyle(chip);
  const px = n => parseFloat(n) || 0;
  const dpr = api.viewport.dpr || 1;
  const snap = v => Math.round(v * dpr) / dpr;
  const left = r.left + px(cs.borderLeftWidth) + px(cs.paddingLeft);
  const top = r.top + px(cs.borderTopWidth) + px(cs.paddingTop);
  const inner = r.height - px(cs.borderTopWidth) - px(cs.borderBottomWidth) - px(cs.paddingTop) - px(cs.paddingBottom);
  const x = snap(left + (CROP_BOX - rec.cropSize) / 2), y = snap(top + (inner - rec.cropSize) / 2);
  m.position.set(x - p.left, -(y - p.top), 0);
  rec.cropAt = { x, y, size: rec.cropSize };
  return true;
}

function paint(rec) {
  const s = sheet;
  if (!s || !rec.crop) return;
  const u = rec.crop.material.uniforms;
  const growing = rec.queue.length ? rec.queue[0] : rec.shown;
  u.uOld.value = s.textures[rec.shown];
  u.uNew.value = s.textures[growing];
  u.uRows.value = rec.queue.length ? Math.min(16, Math.floor(rec.rows)) : 16;
  rec.boards.uniforms.uChar.value = rec.el.classList.contains("state-error") ? 1 : 0;
}

function stepsTo(from, to) {
  const a = GROWS.indexOf(from), b = GROWS.indexOf(to);
  if (a >= 0 && b > a) return GROWS.slice(a + 1, b + 1);
  return [to];
}

export function tick({ THREE, tokens, api }, dt) {
  lastApi = api;
  if (!U) return false;
  let changed = readLook(THREE, tokens);
  for (const band of bands) if (band.el.isConnected && placeBand(THREE, api, band)) changed = true;
  let more = false;
  const instant = !!api.reduced;
  for (const [el, rec] of Array.from(recs)) {
    if (!el.isConnected) { recs.delete(el); continue; }
    const want = cropOf(el);
    const last = rec.queue.length ? rec.queue[rec.queue.length - 1] : rec.shown;
    if (want !== last) {
      if (!rec.queue.length) rec.rows = 0;
      let prev = last;
      for (const step of stepsTo(last, want)) {
        if (GROWS.indexOf(prev) >= 0 && GROWS.indexOf(step) > GROWS.indexOf(prev)) rec.grows += 1;
        rec.queue.push(step);
        prev = step;
      }
    }
    if (rec.queue.length) {
      rec.rows = instant ? 16 : rec.rows + Math.max(1, dt * ROWS_PER_S);
      while (rec.queue.length && rec.rows >= 16) {
        rec.shown = rec.queue.shift();
        rec.rows = rec.queue.length ? (instant ? 16 : 0) : 16;
      }
      if (rec.queue.length) more = true;
      changed = true;
    }
    rec.stage = GROWS.indexOf(rec.shown);
    if (place(rec, api)) changed = true;
    paint(rec);
  }
  if (changed) api.request();
  return more;
}

export function dispose() {
  if (sheet) {
    for (const t of Object.values(sheet.textures)) { t.dispose(); freed += 1; }
  }
  sheet = null;
  U = null;
  look = "";
  bands = [];
  recs.clear();
}

export function inspect() {
  const T = sheet && Object.values(sheet.textures);
  const panes = {};
  for (const rec of recs.values()) {
    panes[rec.repo] = {
      shown: rec.shown, growing: rec.queue.slice(), rows: rec.queue.length ? Math.floor(rec.rows) : 16,
      stage: GROWS.indexOf(rec.shown), grows: rec.grows, crop: rec.cropAt || null,
      visible: !!(rec.crop && rec.crop.visible), box: rec.box, frame: rec.frame,
      scorched: !!(rec.boards && rec.boards.uniforms.uChar.value),
    };
  }
  return {
    loaded: !!(sheet && sheet.loaded), failed: sheet ? sheet.failed : "", raster: RASTER,
    textures: made - freed, made, freed,
    nearest: !!T && T.every(t => t.magFilter === sheet.nearest && t.minFilter === sheet.nearest &&
                                 !t.generateMipmaps),
    sizes: T ? Object.fromEntries(SPRITES.map(id => [id, sheet.sizes[id].slice()])) : {},
    gpuTextures: lastApi && lastApi.renderer ? lastApi.renderer.info.memory.textures : null,
    units: lastApi ? { soil: unitOf(lastApi, SCALE.soil), board: unitOf(lastApi, SCALE.board),
                       crop: unitOf(lastApi, SCALE.crop), dpr: lastApi.viewport.dpr } : null,
    bands: bands.map(b => ({ sel: b.sel, sig: b.sig })),
    panes,
  };
}
