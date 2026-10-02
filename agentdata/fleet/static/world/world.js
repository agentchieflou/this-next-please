"use strict";

var W_NAME = PARAMS.get("w") || "world";
var V_THREE = "/static/vendor/three/three.module.min.js";
var V_GLYPHS = {
  running: "▶", waiting_approval: "‖", needs_human: "!", blocked: "■",
  error: "✕", done: "✓", idle: "○", starting: "◌"
};
var V_STATE = {
  running: 0x3c8fe8, starting: 0x3c8fe8, waiting_approval: 0xe2a12a, needs_human: 0xe8485c,
  blocked: 0xe8485c, error: 0xe8485c, done: 0x3db874, idle: 0x8c99a6
};
var V_DAY = { top: 0xc3cbd2, horizon: 0x9aa5ae, ground: 0x2b3136, fog: 0x9aa5ae, rain: 0xd5dde4 };
var V_NIGHT = { top: 0x03060b, horizon: 0x101a26, ground: 0x0d1216, fog: 0x0c141d, rain: 0x7f99b8 };
var V_REACH = 3.2;
var V_FACING = 0.55;
var V_WALK = 4.5;
var V_RUN = 8;
var V_EYE = 1.6;
var V_TURN = 2.2;
var V_LOOK = 0.0022;
var V_DEAD = 0.18;
var V_BUDGET_MS = 10;
var V_RAIN = 6000;
var V_SPLASH = 160;
var V_LAMPS = 8;
var V_CAP = 64;
var V_REDUCED = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
var V_LOOK_KEY = "fleet.world.look";
var V_STRIDE = 3.4;

/**
 * @typedef {Object} Agent
 * @property {string} repo
 * @property {number} i
 * @property {number} x
 * @property {number} z
 * @property {number} yaw
 * @property {string} state
 * @property {boolean} needs
 */

/** @type {{T: any, renderer: any, scene: any, camera: any, parts: Object<string, any>, mats: Object<string, any>, lights: Object<string, any>, agents: Map<string, Agent>, rows: Array<Object>, approvals: Array<Object>, player: {x: number, z: number, yaw: number, pitch: number}, keys: Object<string, boolean>, look: {dx: number, dy: number}, pad: Array<boolean>, padWas: Array<boolean>, padAxes: Array<number>, near: string, open: string, hour: number|null, daylight: number, held: boolean, time: number, last: number, frames: number, intervals: Array<number>, work: Array<number>, scale: number, maxScale: number, refresh: number, lastTune: number, ready: boolean, why: string, record: Object, pmrem: any, hero: Object, avatar: Object, view: string, who: boolean, walk: number, speed: number, talk: number, rolled: number, source: EventSource, cursors: Object<string, number>, timer: any, live: string, refreshes: number, reading: number, radius: number, repeat: number}} */
var vState = {
  T: null, renderer: null, scene: null, camera: null, parts: {}, mats: {}, lights: {},
  agents: new Map(), rows: [], approvals: [],
  player: { x: 0, z: 0, yaw: 0, pitch: 0 }, keys: {}, look: { dx: 0, dy: 0 }, pad: [], padWas: [], padAxes: [0, 0, 0, 0],
  near: "", open: "", hour: null, daylight: 1, held: false, time: 0, last: 0,
  frames: 0, intervals: [], work: [], scale: 1, maxScale: 1, refresh: 0, lastTune: 0,
  ready: false, why: "", record: null, pmrem: null,
  hero: null, avatar: null, view: "third", who: false, walk: 0, speed: 0, talk: 0, rolled: 0,
  source: null, cursors: {}, timer: null, live: "", refreshes: 0, reading: 0, radius: 8, repeat: 0
};

attr(document.getElementById("todesk"), "href", pageUrl("/"));
attr(document.getElementById("tochat"), "href", pageUrl("/chat"));
attr(document.getElementById("todesk2"), "href", pageUrl("/"));
attr(document.getElementById("tochat2"), "href", pageUrl("/chat"));

/** @param {number} a @param {number} b @param {number} t @returns {number} */
function vSmooth(a, b, t) {
  var x = Math.min(1, Math.max(0, (t - a) / (b - a)));
  return x * x * (3 - 2 * x);
}

/** @returns {number} */
function vHour() {
  var forced = PARAMS.get("hour");
  if (forced !== null && forced !== "" && isFinite(Number(forced))) return ((Number(forced) % 24) + 24) % 24;
  var d = new Date();
  return d.getHours() + d.getMinutes() / 60;
}

/** @param {number} h @returns {number} */
function vDaylight(h) {
  return Math.min(vSmooth(6, 7.5, h), 1 - vSmooth(18.5, 20, h));
}

/** @returns {boolean} */
function vReduced() {
  return !!(V_REDUCED && V_REDUCED.matches);
}

/** @param {string} repo @returns {Object} */
function vRow(repo) {
  return vState.rows.filter(function (r) { return r.repo === repo; })[0] || null;
}

/** @param {Object} row @returns {string} */
function vStateOf(row) {
  var s = String((row && row.state) || "idle");
  return V_STATE[s] ? s : "idle";
}

function vContext() {
  var canvas = document.createElement("canvas");
  var gl = null, opts = { antialias: false, powerPreference: "high-performance", alpha: false };
  ["webgl2", "webgl"].forEach(function (kind) {
    if (gl) return;
    try { gl = canvas.getContext(kind, opts); } catch (e) { vState.why = String((e && e.message) || e); }
  });
  if (!gl) throw new Error("no WebGL context" + (vState.why ? ": " + vState.why : ""));
  return { canvas: canvas, gl: gl };
}

/** @param {any} T @returns {any} */
function vSky(T) {
  var mat = new T.ShaderMaterial({
    uniforms: { uTop: { value: new T.Color() }, uHorizon: { value: new T.Color() } },
    vertexShader: "varying float vY; void main() { vY = normalize(position).y;"
      + " gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: "uniform vec3 uTop; uniform vec3 uHorizon; varying float vY;"
      + " void main() { gl_FragColor = vec4(mix(uHorizon, uTop, smoothstep(-0.05, 0.6, vY)), 1.0); }",
    side: T.BackSide, depthWrite: false, fog: false
  });
  var sky = new T.Mesh(new T.SphereGeometry(320, 24, 12), mat);
  sky.renderOrder = -1;
  sky.frustumCulled = false;
  return sky;
}

/** @param {any} T @returns {any} */
function vRain(T) {
  var g = new T.BufferGeometry();
  var drop = new Float32Array(V_RAIN * 2 * 4);
  var pos = new Float32Array(V_RAIN * 2 * 3);
  for (var i = 0; i < V_RAIN; i++) {
    var x = Math.random(), z = Math.random(), y = Math.random();
    for (var e = 0; e < 2; e++) {
      var k = (i * 2 + e) * 4;
      drop[k] = x; drop[k + 1] = y; drop[k + 2] = z; drop[k + 3] = e;
    }
  }
  g.setAttribute("position", new T.BufferAttribute(pos, 3));
  g.setAttribute("aDrop", new T.BufferAttribute(drop, 4));
  var mat = new T.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uCam: { value: new T.Vector3() }, uColor: { value: new T.Color() },
                uAlpha: { value: 0.35 }, uSpeed: { value: 14 } },
    vertexShader: "uniform float uTime; uniform vec3 uCam; uniform float uSpeed; attribute vec4 aDrop; varying float vA;"
      + " void main() { float box = 44.0; float high = 22.0;"
      + " vec2 xz = uCam.xz + (fract(aDrop.xz - uCam.xz / box) - 0.5) * box;"
      + " float y = uCam.y - 6.0 + fract(aDrop.y - uTime * uSpeed / high) * high;"
      + " vec3 p = vec3(xz.x + aDrop.w * 0.08, y - aDrop.w * 0.55, xz.y + aDrop.w * 0.03);"
      + " vec4 mv = modelViewMatrix * vec4(p, 1.0); vA = (1.0 - smoothstep(6.0, 22.0, -mv.z)) * (0.4 + 0.6 * aDrop.w);"
      + " gl_Position = projectionMatrix * mv; }",
    fragmentShader: "uniform vec3 uColor; uniform float uAlpha; varying float vA;"
      + " void main() { gl_FragColor = vec4(uColor, uAlpha * vA); }",
    transparent: true, depthWrite: false, fog: false
  });
  var lines = new T.LineSegments(g, mat);
  lines.frustumCulled = false;
  lines.renderOrder = 2;
  return lines;
}

/** @param {any} T @returns {any} */
function vSplash(T) {
  var g = new T.RingGeometry(0.06, 0.1, 16);
  g.rotateX(-Math.PI / 2);
  var seed = new Float32Array(V_SPLASH * 3);
  for (var i = 0; i < V_SPLASH; i++) {
    seed[i * 3] = Math.random(); seed[i * 3 + 1] = Math.random(); seed[i * 3 + 2] = Math.random();
  }
  g.setAttribute("aSeed", new T.InstancedBufferAttribute(seed, 3));
  var mat = new T.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uCam: { value: new T.Vector3() }, uColor: { value: new T.Color() }, uAlpha: { value: 0.5 } },
    vertexShader: "uniform float uTime; uniform vec3 uCam; attribute vec3 aSeed; varying float vA;"
      + " void main() { float box = 16.0; float t = fract(uTime * 1.6 + aSeed.z); float cycle = floor(uTime * 1.6 + aSeed.z);"
      + " vec2 jitter = fract(aSeed.xy + cycle * vec2(0.618, 0.414));"
      + " vec2 xz = uCam.xz + (fract(jitter - uCam.xz / box) - 0.5) * box;"
      + " vec3 p = position * (0.3 + 2.4 * t) + vec3(xz.x, 0.03, xz.y); vA = 1.0 - t;"
      + " gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0); }",
    fragmentShader: "uniform vec3 uColor; uniform float uAlpha; varying float vA;"
      + " void main() { gl_FragColor = vec4(uColor, uAlpha * vA); }",
    transparent: true, depthWrite: false, fog: false
  });
  var mesh = new T.InstancedMesh(g, mat, V_SPLASH);
  mesh.frustumCulled = false;
  mesh.renderOrder = 1;
  return mesh;
}

/** @param {any} T @param {any} scene */
function vProps(T, scene) {
  var m = new T.Matrix4();
  var ground = new T.Mesh(new T.PlaneGeometry(600, 600), new T.MeshStandardMaterial({ color: 0x3a4249, roughness: 0.32, metalness: 0.2 }));
  ground.rotation.x = -Math.PI / 2;
  scene.add(ground);
  var plaza = new T.Mesh(new T.RingGeometry(1, 1.035, 96, 1), new T.MeshLambertMaterial({
    color: 0x5d666f, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
  plaza.rotation.x = -Math.PI / 2;
  plaza.position.y = 0.02;
  scene.add(plaza);
  var towers = new T.InstancedMesh(new T.BoxGeometry(1, 1, 1), new T.MeshLambertMaterial({ color: 0x1c2228 }), 36);
  for (var i = 0; i < 36; i++) {
    var a = i / 36 * Math.PI * 2 + (i % 3) * 0.05, r = 85 + (i * 37 % 60), h = 14 + (i * 53 % 38), w = 10 + (i * 29 % 14);
    m.makeScale(w, h, w).setPosition(Math.cos(a) * r, h / 2, Math.sin(a) * r);
    towers.setMatrixAt(i, m);
  }
  scene.add(towers);
  var posts = new T.InstancedMesh(new T.CylinderGeometry(0.07, 0.09, 4, 8), new T.MeshLambertMaterial({ color: 0x1b2126 }), V_LAMPS);
  var heads = new T.InstancedMesh(new T.SphereGeometry(0.22, 12, 8), new T.MeshBasicMaterial({ color: 0xffd9a0 }), V_LAMPS);
  scene.add(posts, heads);
  var bulbs = [];
  for (var j = 0; j < 4; j++) {
    var bulb = new T.PointLight(0xffc98a, 0, 34, 1.2);
    scene.add(bulb);
    bulbs.push(bulb);
  }
  vState.parts.plaza = plaza;
  vState.parts.posts = posts;
  vState.parts.heads = heads;
  vState.lights.bulbs = bulbs;
}

/** @param {any} T @param {any} scene */
function vFigures(T, scene) {
  var p = vState.parts;
  p.base = new T.InstancedMesh(new T.CylinderGeometry(0.62, 0.7, 0.22, 20), new T.MeshLambertMaterial({ color: 0x4a525a }), V_CAP);
  p.body = new T.InstancedMesh(new T.CapsuleGeometry(0.34, 0.9, 6, 14), new T.MeshLambertMaterial({ color: 0xffffff }), V_CAP);
  p.ring = new T.InstancedMesh(new T.TorusGeometry(0.55, 0.05, 8, 32), new T.MeshBasicMaterial({ color: 0xffffff }), V_CAP);
  p.visor = new T.InstancedMesh(new T.BoxGeometry(0.46, 0.12, 0.08), new T.MeshBasicMaterial({ color: 0xffffff }), V_CAP);
  vState.mats.beacon = new T.MeshBasicMaterial({ color: V_STATE.needs_human, transparent: true, opacity: 0.28, depthWrite: false, fog: false });
  p.beacon = new T.InstancedMesh(new T.CylinderGeometry(0.22, 0.22, 40, 10, 1, true), vState.mats.beacon, V_CAP);
  p.beacon.renderOrder = 3;
  ["base", "body", "ring", "visor", "beacon"].forEach(function (k) {
    p[k].count = 0;
    p[k].frustumCulled = false;
    scene.add(p[k]);
  });
}

function vLayout() {
  var names = vState.rows.map(function (r) { return String(r.repo); }).sort();
  var n = names.length;
  var radius = Math.max(7, n * 1.5);
  vState.radius = radius;
  var seen = {};
  names.forEach(function (repo, i) {
    seen[repo] = true;
    var row = vRow(repo);
    var state = vStateOf(row);
    var needs = !!(row && row.needs_human);
    var a = n === 1 ? -Math.PI / 2 : i / n * Math.PI * 2 - Math.PI / 2;
    var x = Math.cos(a) * radius, z = Math.sin(a) * radius;
    var ag = vState.agents.get(repo);
    if (!ag) {
      ag = { repo: repo, i: i, x: x, z: z, yaw: Math.atan2(-x, -z), state: state, needs: needs };
      vState.agents.set(repo, ag);
    }
    ag.i = i; ag.x = x; ag.z = z; ag.yaw = Math.atan2(-x, -z); ag.state = state; ag.needs = needs;
  });
  vState.agents.forEach(function (ag, repo) {
    if (!seen[repo]) vState.agents.delete(repo);
  });
  vPlace();
  drawList();
  drawLabels();
}

function vPlace() {
  var T = vState.T, p = vState.parts, m = new T.Matrix4(), c = new T.Color(), q = new T.Quaternion();
  var up = new T.Vector3(0, 1, 0), one = new T.Vector3(1, 1, 1), at = new T.Vector3();
  var list = Array.from(vState.agents.values()).slice(0, V_CAP);
  var beacons = 0;
  list.forEach(function (ag, k) {
    q.setFromAxisAngle(up, ag.yaw);
    m.compose(at.set(ag.x, 0.11, ag.z), q, one);
    p.base.setMatrixAt(k, m);
    m.compose(at.set(ag.x, 0.92, ag.z), q, one);
    p.body.setMatrixAt(k, m);
    c.setHex(V_STATE[ag.state] || V_STATE.idle).lerp(new T.Color(0xffffff), 0.35);
    p.body.setColorAt(k, c);
    c.setHex(V_STATE[ag.state] || V_STATE.idle);
    p.ring.setColorAt(k, c);
    p.visor.setColorAt(k, c);
    m.compose(at.set(ag.x + Math.sin(ag.yaw) * 0.31, 1.42, ag.z + Math.cos(ag.yaw) * 0.31), q, one);
    p.visor.setMatrixAt(k, m);
    if (ag.needs) {
      m.compose(at.set(ag.x, 20, ag.z), new T.Quaternion(), one);
      p.beacon.setMatrixAt(beacons++, m);
    }
  });
  p.base.count = p.body.count = p.ring.count = p.visor.count = list.length;
  p.beacon.count = beacons;
  ["base", "body", "ring", "visor", "beacon"].forEach(function (k) {
    p[k].instanceMatrix.needsUpdate = true;
    if (p[k].instanceColor) p[k].instanceColor.needsUpdate = true;
  });
  vSpinRings(0);
  var r = vState.radius + 3.5;
  p.plaza.scale.set(r, r, 1);
  var lm = new T.Matrix4();
  for (var i = 0; i < V_LAMPS; i++) {
    var a = (i + 0.5) / V_LAMPS * Math.PI * 2, lx = Math.cos(a) * (r + 1.5), lz = Math.sin(a) * (r + 1.5);
    lm.makeTranslation(lx, 2, lz);
    p.posts.setMatrixAt(i, lm);
    lm.makeTranslation(lx, 4.05, lz);
    p.heads.setMatrixAt(i, lm);
    if (i % 2 === 0) vState.lights.bulbs[i / 2].position.set(lx, 3.9, lz);
  }
  p.posts.instanceMatrix.needsUpdate = true;
  p.heads.instanceMatrix.needsUpdate = true;
}

/** @param {number} t */
function vSpinRings(t) {
  var T = vState.T, p = vState.parts, m = new T.Matrix4(), q = new T.Quaternion(), e = new T.Euler();
  var at = new T.Vector3(), one = new T.Vector3(1, 1, 1);
  var k = 0;
  vState.agents.forEach(function (ag) {
    if (k >= V_CAP) return;
    var spin = ag.state === "running" || ag.state === "starting" ? t * 1.8 : 0;
    e.set(Math.PI / 2, 0, spin + ag.i);
    q.setFromEuler(e);
    m.compose(at.set(ag.x, 2.1 + (ag.needs ? Math.sin(t * 2.4) * 0.08 : 0), ag.z), q, one);
    p.ring.setMatrixAt(k++, m);
  });
  p.ring.instanceMatrix.needsUpdate = true;
}

function vWeather() {
  var T = vState.T, d = vDaylight(vState.hour == null ? vHour() : vState.hour);
  vState.daylight = d;
  var mix = function (a, b) { return new T.Color(a).lerp(new T.Color(b), d); };
  var sky = vState.parts.sky.material.uniforms;
  sky.uTop.value.copy(mix(V_NIGHT.top, V_DAY.top));
  sky.uHorizon.value.copy(mix(V_NIGHT.horizon, V_DAY.horizon));
  vState.scene.fog.color.copy(mix(V_NIGHT.fog, V_DAY.fog));
  vState.scene.fog.density = 0.014 + (1 - d) * 0.01;
  vReflect();
  vState.renderer.setClearColor(vState.scene.fog.color);
  vState.lights.hemi.intensity = 0.12 + 0.95 * d;
  vState.lights.sun.intensity = 0.55 * d;
  var night = 1 - d;
  vState.lights.bulbs.forEach(function (b) { b.intensity = 18 * night; });
  vState.parts.heads.material.color.setHex(night > 0.5 ? 0xffd9a0 : 0x8f8a80);
  vState.mats.beacon.opacity = 0.2 + 0.25 * night;
  var rain = vState.parts.rain.material.uniforms, splash = vState.parts.splash.material.uniforms;
  rain.uColor.value.copy(mix(V_NIGHT.rain, V_DAY.rain));
  rain.uAlpha.value = 0.3 + 0.15 * night;
  rain.uSpeed.value = vReduced() ? 5 : 14;
  splash.uColor.value.copy(rain.uColor.value);
}

function vReflect() {
  var T = vState.T;
  if (!vState.pmrem) vState.pmrem = new T.PMREMGenerator(vState.renderer);
  var room = new T.Scene();
  room.add(new T.Mesh(vState.parts.sky.geometry, vState.parts.sky.material));
  var made = vState.pmrem.fromScene(room, 0.02);
  if (vState.scene.environment) vState.scene.environment.dispose();
  vState.scene.environment = made.texture;
}

function vBuild() {
  var T = vState.T;
  var ctx = vContext();
  var renderer = new T.WebGLRenderer({ canvas: ctx.canvas, context: ctx.gl, antialias: false, powerPreference: "high-performance" });
  renderer.outputColorSpace = T.SRGBColorSpace;
  vState.maxScale = Math.min(window.devicePixelRatio || 1, 1.5);
  vState.scale = vState.maxScale;
  renderer.setPixelRatio(vState.scale);
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  document.getElementById("world").appendChild(ctx.canvas);
  ctx.canvas.tabIndex = 0;
  var scene = new T.Scene();
  scene.fog = new T.FogExp2(V_DAY.fog, 0.022);
  var camera = new T.PerspectiveCamera(70, window.innerWidth / window.innerHeight, 0.1, 400);
  camera.rotation.order = "YXZ";
  vState.renderer = renderer;
  vState.scene = scene;
  vState.camera = camera;
  vState.lights.hemi = new T.HemisphereLight(0xc4ccd4, 0x20262b, 1);
  vState.lights.sun = new T.DirectionalLight(0xdfe6ec, 0.5);
  vState.lights.sun.position.set(-30, 60, 20);
  scene.add(vState.lights.hemi, vState.lights.sun);
  vState.parts.sky = vSky(T);
  vState.parts.rain = vRain(T);
  vState.parts.splash = vSplash(T);
  scene.add(vState.parts.sky, vState.parts.rain, vState.parts.splash);
  vProps(T, scene);
  vFigures(T, scene);
  vState.hour = PARAMS.get("hour") !== null && PARAMS.get("hour") !== "" ? vHour() : null;
  vWeather();
  window.addEventListener("resize", function () {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight, false);
  });
  ctx.canvas.addEventListener("click", function () {
    if (!vState.open && ctx.canvas.requestPointerLock) {
      try { ctx.canvas.requestPointerLock(); } catch (e) {}
    }
    ctx.canvas.focus();
  });
  document.addEventListener("mousemove", function (e) {
    if (document.pointerLockElement !== ctx.canvas) return;
    vState.look.dx += e.movementX || 0;
    vState.look.dy += e.movementY || 0;
  });
  setInterval(function () { if (vState.hour == null) vWeather(); }, 60000);
  renderer.setAnimationLoop(vFrame);
}

/** @param {number} v @returns {number} */
function vDead(v) {
  return Math.abs(v) < V_DEAD ? 0 : (v - Math.sign(v) * V_DEAD) / (1 - V_DEAD);
}

/** @returns {{axes: Array<number>, buttons: Array<boolean>}|null} */
function vPad() {
  var pads = navigator.getGamepads ? navigator.getGamepads() : [];
  for (var i = 0; i < (pads ? pads.length : 0); i++) {
    var p = pads[i];
    if (p && p.connected !== false) {
      return { axes: Array.prototype.slice.call(p.axes || []).map(Number),
               buttons: Array.prototype.map.call(p.buttons || [], function (b) { return !!(b && (b.pressed || b.value > 0.5)); }) };
    }
  }
  return null;
}

/** @param {number} n @returns {boolean} */
function vPressed(n) {
  return !!vState.pad[n] && !vState.padWas[n];
}

/** @param {number} dt */
function vStep(dt) {
  var pad = vPad();
  vState.padWas = vState.pad;
  vState.pad = pad ? pad.buttons : [];
  vState.padAxes = pad ? pad.axes : [0, 0, 0, 0];
  if (vPressed(9)) { vWho(!vState.who); return; }
  if (vState.who) { vState.speed = 0; vWhoPad(dt); return; }
  if (vState.open) { vState.speed = 0; vPanelPad(dt); return; }
  if (vPressed(3)) vView(vState.view === "third" ? "first" : "third");
  var k = vState.keys, P = vState.player, ax = vState.padAxes;
  var fwd = (k.KeyW || k.ArrowUp ? 1 : 0) - (k.KeyS || k.ArrowDown ? 1 : 0) - vDead(ax[1] || 0);
  var side = (k.KeyD ? 1 : 0) - (k.KeyA ? 1 : 0) + vDead(ax[0] || 0);
  var turn = (k.ArrowLeft || k.KeyQ ? 1 : 0) - (k.ArrowRight ? 1 : 0) - vDead(ax[2] || 0);
  var tilt = -vDead(ax[3] || 0);
  P.yaw += turn * V_TURN * dt - vState.look.dx * V_LOOK;
  P.pitch = Math.max(-1.2, Math.min(1.2, P.pitch + tilt * V_TURN * 0.7 * dt - vState.look.dy * V_LOOK));
  vState.look.dx = vState.look.dy = 0;
  var len = Math.hypot(fwd, side);
  if (len > 1) { fwd /= len; side /= len; }
  var run = k.ShiftLeft || k.ShiftRight || vState.pad[7] || vState.pad[10];
  var speed = (run ? V_RUN : V_WALK) * dt;
  var sy = Math.sin(P.yaw), cy = Math.cos(P.yaw), x0 = P.x, z0 = P.z;
  P.x += (-sy * fwd + cy * side) * speed;
  P.z += (-cy * fwd - sy * side) * speed;
  vState.agents.forEach(function (ag) {
    var dx = P.x - ag.x, dz = P.z - ag.z, d = Math.hypot(dx, dz);
    if (d < 1.05 && d > 0.0001) { P.x = ag.x + dx / d * 1.05; P.z = ag.z + dz / d * 1.05; }
  });
  var lim = vState.radius + 20, r = Math.hypot(P.x, P.z);
  if (r > lim) { P.x *= lim / r; P.z *= lim / r; }
  var went = Math.hypot(P.x - x0, P.z - z0);
  vState.walk += went * V_STRIDE * (fwd < 0 ? -1 : 1);
  vState.rolled += went * (fwd < 0 ? -1 : 1);
  vState.speed = dt > 0 ? went / dt / V_WALK : 0;
  vNearest();
  if (vPressed(0) && vState.near) vTalk(vState.near);
}

/** @param {{x: number, z: number, yaw: number, pitch: number}} P @param {any} cam */
function vCamera(P, cam) {
  var fx = -Math.sin(P.yaw), fz = -Math.cos(P.yaw);
  if (vState.who && vState.hero) {
    cam.position.set(P.x + fx * 2.5, 1.3, P.z + fz * 2.5);
    cam.lookAt(P.x, vState.hero.seated ? 0.95 : 1.15, P.z);
  } else if (vState.view === "third" && vState.hero) {
    var up = Math.sin(P.pitch), d = 3.4, side = 1.3 * vState.talk;
    cam.position.set(P.x - fx * d - fz * side, Math.max(0.45, 2.0 - up * d), P.z - fz * d + fx * side);
    cam.lookAt(P.x + fx * 2.6, 1.35 + up * 2.6, P.z + fz * 2.6);
  } else {
    cam.position.set(P.x, V_EYE, P.z);
    cam.rotation.set(P.pitch, P.yaw, 0);
  }
}

/** @param {number} dt */
function vHeroFrame(dt) {
  var h = vState.hero;
  if (!h) return;
  var P = vState.player;
  h.group.visible = vState.view === "third" || vState.who;
  h.group.position.set(P.x, 0, P.z);
  h.group.rotation.y = P.yaw;
  var want = vState.open ? 1 : 0;
  vState.talk = vReduced() ? want : vState.talk + (want - vState.talk) * Math.min(1, dt * 8);
  if (vState.speed < 0.05 && !vReduced()) vState.walk += (Math.round(vState.walk / Math.PI) * Math.PI - vState.walk) * Math.min(1, dt * 10);
  WorldHero.pose(h, { phase: vState.walk, speed: vState.speed, talk: vState.talk, t: vState.time, reduced: vReduced(),
                      rolled: vState.rolled });
}

/** @returns {Object} */
function vLoadLook() {
  var forced = PARAMS.get("who");
  if (forced !== null && forced !== "" && isFinite(Number(forced))) return WorldHero.preset(Number(forced));
  try {
    var kept = localStorage.getItem(V_LOOK_KEY);
    if (kept) return WorldHero.normal(JSON.parse(kept));
  } catch (e) {}
  return null;
}

/** @param {Object} look */
function vLook(look) {
  vState.avatar = WorldHero.normal(look);
  try { localStorage.setItem(V_LOOK_KEY, JSON.stringify(vState.avatar)); } catch (e) {}
  if (!vState.T) return;
  WorldHero.dispose(vState.hero);
  vState.hero = WorldHero.build(vState.T, vState.avatar);
  vState.scene.add(vState.hero.group);
  drawWho();
}

/** @param {string} view */
function vView(view) {
  vState.view = view === "first" ? "first" : "third";
  setData(document.body, "view", vState.view);
}

/** @param {boolean} on */
function vWho(on) {
  vState.who = !!on;
  vState.keys = {};
  if (vState.who && document.pointerLockElement && document.exitPointerLock) document.exitPointerLock();
  if (vState.who && vState.open) vStepBack();
  drawWho();
  if (vState.who) {
    var first = /** @type {HTMLElement} */ (document.querySelector("#wpresets .ww-choice[aria-checked='true']")
      || document.querySelector("#wpresets .ww-choice"));
    if (first) first.focus();
  } else {
    var canvas = document.querySelector("#world canvas");
    if (canvas) /** @type {HTMLElement} */ (canvas).focus();
  }
}

/** @param {Object} look @returns {string} */
function vLookKey(look) {
  return JSON.stringify(WorldHero.normal(look));
}

function drawWho() {
  hide(document.getElementById("wwho"), !vState.who);
  if (!vState.who) return;
  var L = vState.avatar || WorldHero.preset(0), now = vLookKey(L);
  patchList(document.getElementById("wpresets"), WorldHero.PRESETS, function (p) { return p.name; }, function (p, key, i) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "ww-choice ww-preset";
    attr(b, "role", "radio");
    b.addEventListener("click", function () { vLook(WorldHero.preset(i)); });
    return b;
  }, function (b, p, i) {
    text(b, p.name);
    attr(b, "aria-checked", String(vLookKey(WorldHero.preset(i)) === now));
  });
  patchList(document.getElementById("wopts"), WorldHero.OPTIONS, function (o) { return o.key; }, function (o) {
    var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("wwrow"));
    var row = /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
    attr(row, "aria-label", o.label);
    return row;
  }, function (row, o) {
    text(row.querySelector(".ww-label"), o.label);
    hide(row, o.key === "scarf" && L.hair !== "scarf" && L.hair !== "wrap");
    patchList(row.querySelector(".ww-choices"), o.values, function (v) { return v; }, function (v) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "ww-choice" + (o.swatch ? " ww-swatch" : "");
      attr(b, "role", "radio");
      b.addEventListener("click", function () {
        var next = Object.assign({}, vState.avatar || WorldHero.preset(0));
        next[o.key] = v;
        vLook(next);
      });
      return b;
    }, function (b, v, i) {
      if (o.swatch) {
        style(b, "--swatch", v);
        attr(b, "aria-label", o.label + " " + (i + 1) + " of " + o.values.length);
      } else {
        text(b, v);
      }
      attr(b, "aria-checked", String(L[o.key] === v));
    });
  });
}

/** @returns {Array<Array<HTMLElement>>} */
function vWhoRows() {
  var rows = [Array.prototype.slice.call(document.querySelectorAll("#wwho .wp-head button"))];
  rows.push(Array.prototype.slice.call(document.querySelectorAll("#wpresets .ww-choice")));
  Array.prototype.forEach.call(document.querySelectorAll("#wopts .ww-row"), function (row) {
    if (!row.hidden) rows.push(Array.prototype.slice.call(row.querySelectorAll(".ww-choice")));
  });
  return rows.filter(function (r) { return r.length; });
}

/** @param {number} dt */
function vWhoPad(dt) {
  if (vPressed(1)) { vWho(false); return; }
  var ax = vState.padAxes, dx = vPressed(15) ? 1 : vPressed(14) ? -1 : 0, dy = vPressed(13) ? 1 : vPressed(12) ? -1 : 0;
  vState.repeat = Math.max(0, vState.repeat - dt);
  if (!dx && !dy && vState.repeat === 0) {
    var sx = vDead(ax[0] || 0), sy = vDead(ax[1] || 0);
    if (Math.abs(sx) > 0.6) { dx = sx > 0 ? 1 : -1; vState.repeat = 0.22; }
    else if (Math.abs(sy) > 0.6) { dy = sy > 0 ? 1 : -1; vState.repeat = 0.22; }
  }
  if (dx || dy) {
    var rows = vWhoRows(), el = /** @type {HTMLElement} */ (document.activeElement), r = -1, c = -1;
    rows.forEach(function (row, i) { var j = row.indexOf(el); if (j >= 0) { r = i; c = j; } });
    if (r < 0) { r = Math.min(1, rows.length - 1); c = 0; }
    else if (dy) { r = Math.max(0, Math.min(rows.length - 1, r + dy)); c = Math.min(c, rows[r].length - 1); }
    else c = (c + dx + rows[r].length) % rows[r].length;
    rows[r][c].focus();
  }
  if (vPressed(0)) {
    var b = /** @type {HTMLElement} */ (document.activeElement);
    if (b && b.tagName === "BUTTON" && b.closest("#wwho")) b.click();
  }
}

function vNearest() {
  var P = vState.player, fx = -Math.sin(P.yaw), fz = -Math.cos(P.yaw), best = "", bestD = V_REACH;
  vState.agents.forEach(function (ag) {
    var dx = ag.x - P.x, dz = ag.z - P.z, d = Math.hypot(dx, dz);
    if (d <= bestD && d > 0 && (dx * fx + dz * fz) / d >= V_FACING) { best = ag.repo; bestD = d; }
  });
  vState.near = best;
}

/** @param {number} now */
function vFrame(now) {
  var t0 = performance.now();
  var dt = vState.last ? Math.min(0.05, (now - vState.last) / 1000) : 1 / 60;
  if (vState.last) vState.intervals.push(now - vState.last);
  vState.last = now;
  vState.time += vReduced() ? dt * 0.35 : dt;
  if (!vState.held) vStep(dt);
  var P = vState.player, cam = vState.camera;
  vCamera(P, cam);
  vHeroFrame(dt);
  var rain = vState.parts.rain.material.uniforms, splash = vState.parts.splash.material.uniforms;
  rain.uTime.value = splash.uTime.value = vState.time;
  rain.uCam.value.copy(cam.position);
  splash.uCam.value.copy(cam.position);
  if (!vReduced()) {
    vSpinRings(vState.time);
    vState.mats.beacon.opacity = (0.2 + 0.25 * (1 - vState.daylight)) * (0.75 + 0.25 * Math.sin(vState.time * 3));
  }
  drawHud();
  vState.renderer.render(vState.scene, cam);
  drawLabels();
  vState.frames += 1;
  vState.work.push(performance.now() - t0);
  if (vState.intervals.length > 240) vState.intervals.splice(0, vState.intervals.length - 240);
  if (vState.work.length > 240) vState.work.splice(0, vState.work.length - 240);
  if (now - vState.lastTune > 1000) vTune(now);
}

/** @param {Array<number>} xs @param {number} p @returns {number} */
function vPct(xs, p) {
  if (!xs.length) return 0;
  var s = xs.slice().sort(function (a, b) { return a - b; });
  return s[Math.min(s.length - 1, Math.floor(p * s.length))];
}

/** @param {number} now */
function vTune(now) {
  vState.lastTune = now;
  var recent = vState.intervals.slice(-90);
  if (recent.length < 30) return;
  var floor = vPct(vState.intervals, 0.05);
  vState.refresh = floor;
  var target = Math.max(floor, Math.min(V_BUDGET_MS, floor * 1.5));
  var mid = vPct(recent, 0.5);
  var was = vState.scale;
  if (mid > target * 1.15 && vState.scale > 0.5) vState.scale = Math.max(0.5, vState.scale * 0.85);
  else if (mid < target * 1.03 && vState.scale < vState.maxScale) vState.scale = Math.min(vState.maxScale, vState.scale * 1.08);
  if (vState.scale !== was) {
    vState.renderer.setPixelRatio(vState.scale);
    vState.renderer.setSize(window.innerWidth, window.innerHeight, false);
  }
}

function drawLabels() {
  var host = document.getElementById("wlabels");
  if (!vState.camera) return;
  var T = vState.T, at = new T.Vector3(), P = vState.player, w = window.innerWidth, h = window.innerHeight;
  patchList(host, Array.from(vState.agents.values()), function (ag) { return ag.repo; }, function () {
    var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("wtag"));
    return /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  }, function (el, ag) {
    setClass(el, "wtag " + ag.state + (ag.needs ? " needs" : "") + (ag.repo === vState.near ? " near" : ""));
    text(el.querySelector(".wtag-name"), ag.repo);
    text(el.querySelector(".wtag-state"), (V_GLYPHS[ag.state] || "·") + " " + (ag.needs ? "needs you" : ag.state.replace(/_/g, " ")));
    var d = Math.hypot(ag.x - P.x, ag.z - P.z);
    at.set(ag.x, 2.75, ag.z).project(vState.camera);
    var shown = at.z < 1 && d < 48 && Math.abs(at.x) < 1.2 && Math.abs(at.y) < 1.2 && !vState.open && !vState.who;
    hide(el, !shown);
    if (!shown) return;
    var x = Math.round((at.x + 1) / 2 * w), y = Math.round((1 - at.y) / 2 * h);
    var k = Math.round(Math.max(0.5, Math.min(1.3, 7 / Math.max(d, 1))) * 20) / 20;
    style(el, "transform", "translate(" + x + "px, " + y + "px) translate(-50%, -100%) scale(" + k + ")");
  });
}

function drawHud() {
  var P = vState.player;
  var near = vState.near && vState.agents.get(vState.near);
  var prompt = document.getElementById("wprompt");
  hide(prompt, !near || !!vState.open || vState.who);
  if (near) text(prompt, "E or A — talk to " + near.repo + (near.needs ? " (it needs you)" : ""));
  var target = null, dist = Infinity;
  vState.agents.forEach(function (ag) {
    if (!ag.needs || ag.repo === vState.near) return;
    var d = Math.hypot(ag.x - P.x, ag.z - P.z);
    if (d < dist) { dist = d; target = ag; }
  });
  var compass = document.getElementById("wcompass");
  hide(compass, !target || !!vState.open || vState.who);
  if (target) {
    var bearing = Math.atan2(-(target.x - P.x), -(target.z - P.z)) - P.yaw;
    var deg = Math.round(((bearing * 180 / Math.PI) % 360 + 540) % 360 - 180);
    style(document.getElementById("warrow"), "transform", "rotate(" + (-Math.round(deg / 5) * 5) + "deg)");
    text(document.getElementById("wcompasswords"), target.repo + " needs you · " + Math.round(dist) + " m");
  }
  var stats = document.getElementById("wstats");
  if (!stats.hidden && vState.frames % 30 === 0) {
    var fi = vPct(vState.intervals.slice(-120), 0.5);
    text(stats, (fi ? Math.round(1000 / fi) : 0) + " fps · " + vPct(vState.work.slice(-120), 0.5).toFixed(1)
         + " ms · " + Math.round(vState.scale * 100) + "% · " + vState.renderer.info.render.calls + " draws");
  }
}

function drawList() {
  var list = document.getElementById("wlist");
  patchList(list, Array.from(vState.agents.values()), function (ag) { return ag.repo; }, function () {
    return document.createElement("li");
  }, function (li, ag) {
    text(li, ag.repo + ": " + (ag.needs ? "needs you, " : "") + ag.state.replace(/_/g, " "));
  });
  var n = vState.rows.filter(function (r) { return r.needs_human; }).length;
  text(document.getElementById("wneed"), n ? n + " need you — walk to the beacon" : "");
}

/** @param {string} repo */
function vTalk(repo) {
  vState.open = repo;
  var ag = vState.agents.get(repo), P = vState.player;
  if (ag) P.yaw = Math.atan2(-(ag.x - P.x), -(ag.z - P.z));
  vState.keys = {};
  if (document.pointerLockElement && document.exitPointerLock) document.exitPointerLock();
  text(document.getElementById("wsaid"), "");
  drawPanel();
  var items = vFocusables();
  var first = items.filter(function (el) { return el.classList.contains("ask-choice"); })[0]
    || items.filter(function (el) { return el.id === "wapprove" || el.id === "wmessage"; })[0];
  if (first) first.focus();
}

function vStepBack() {
  vState.open = "";
  drawPanel();
  var canvas = document.querySelector("#world canvas");
  if (canvas) /** @type {HTMLElement} */ (canvas).focus();
}

function drawPanel() {
  var panel = document.getElementById("wpanel");
  var row = vRow(vState.open);
  if (vState.open && !row) vState.open = "";
  hide(panel, !vState.open);
  if (!row) return;
  var state = vStateOf(row);
  text(document.getElementById("wname"), row.repo);
  var chip = document.getElementById("wstate");
  setClass(chip, "chip " + state);
  text(chip, (V_GLYPHS[state] || "·") + " " + state.replace(/_/g, " "));
  text(document.getElementById("wsays"), row.why || "");
  text(document.getElementById("wlast"), row.last_said || "");
  var a = vState.approvals.filter(function (x) { return x.repo === row.repo; })[0];
  hide(document.getElementById("wapproval"), !a);
  if (a) {
    setData(document.getElementById("wapproval"), "id", a.id);
    text(document.getElementById("wapprovalwhat"), [a.summary || a.kind || "a write", a.ticket].filter(Boolean).join(" · "));
  }
  drawAsks(row);
}

/** @param {Object} row */
function drawAsks(row) {
  var open = (row.asked || []).filter(function (x) { return x.blocking !== false && x.id; });
  hide(document.getElementById("wasks"), !open.length);
  text(document.getElementById("wasksn"), open.length === 1 ? "it asks" : "it asks " + open.length + " things");
  patchList(document.getElementById("wasklist"), open, function (x) { return x.id; }, function () {
    var tpl = /** @type {HTMLTemplateElement} */ (document.getElementById("wq"));
    return /** @type {HTMLElement} */ (tpl.content.firstElementChild.cloneNode(true));
  }, function (li, x) {
    setData(li, "qid", x.id);
    text(li.querySelector(".wq-q"), x.q || "");
    var input = /** @type {HTMLInputElement} */ (li.querySelector(".wq-answer"));
    attr(input, "placeholder", x["default"] ? "your answer (default: " + x["default"] + ")" : "your answer");
    patchList(li.querySelector(".wq-choices"), x.choices || [], function (c) { return c; }, function (c) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "ask-choice";
      b.addEventListener("click", function () {
        input.value = c;
        Array.prototype.forEach.call(b.parentNode.children, function (o) { attr(o, "aria-pressed", String(o === b)); });
      });
      return b;
    }, function (b, c) { text(b, c); attr(b, "aria-pressed", String(input.value === c)); });
  });
}

/** @returns {Array<HTMLElement>} */
function vFocusables() {
  return Array.prototype.filter.call(document.querySelectorAll("#wpanel button, #wpanel input"), function (el) {
    return !el.disabled && el.offsetParent !== null;
  });
}

/** @param {number} dt */
function vPanelPad(dt) {
  if (vPressed(1)) { vStepBack(); return; }
  var stick = vDead(vState.padAxes[1] || 0);
  var dir = vPressed(13) || vPressed(15) ? 1 : vPressed(12) || vPressed(14) ? -1 : 0;
  vState.repeat = Math.max(0, vState.repeat - dt);
  if (!dir && Math.abs(stick) > 0.6 && vState.repeat === 0) { dir = stick > 0 ? 1 : -1; vState.repeat = 0.22; }
  if (dir) {
    var items = vFocusables();
    if (items.length) {
      var at = items.indexOf(/** @type {HTMLElement} */ (document.activeElement));
      items[at < 0 ? 0 : (at + dir + items.length) % items.length].focus();
    }
  }
  if (vPressed(0)) {
    var el = /** @type {HTMLElement} */ (document.activeElement);
    if (el && el.tagName === "BUTTON" && el.closest("#wpanel")) el.click();
  }
}

/** @param {string} what @param {Object} body @returns {Promise<Object>} */
function vPost(what, body) {
  var said = document.getElementById("wsaid");
  text(said, what + "…");
  return post(what, body).then(function (r) {
    text(said, r && r.ok ? what + ": done" : ((r && r.error) || "refused") + (r && r.hint ? " — " + r.hint : ""));
    vSoon();
    return r || {};
  }, function (e) { text(said, String(e)); return {}; });
}

document.getElementById("wclose").addEventListener("click", vStepBack);
document.getElementById("wwhobtn").addEventListener("click", function () { vWho(true); });
document.getElementById("wwhodone").addEventListener("click", function () { vWho(false); });
document.getElementById("wapprove").addEventListener("click", function () {
  vPost("approve", { id: document.getElementById("wapproval").dataset.id,
                     reason: /** @type {HTMLInputElement} */ (document.getElementById("wreason")).value.trim() });
});
document.getElementById("wdeny").addEventListener("click", function () {
  vPost("deny", { id: document.getElementById("wapproval").dataset.id,
                  reason: /** @type {HTMLInputElement} */ (document.getElementById("wreason")).value.trim() });
});
document.getElementById("wanswer").addEventListener("click", function () {
  var answers = [];
  Array.prototype.forEach.call(document.getElementById("wasklist").children, function (li) {
    var v = /** @type {HTMLInputElement} */ (li.querySelector(".wq-answer")).value.trim();
    if (v && li.dataset.qid) answers.push({ id: li.dataset.qid, answer: v });
  });
  if (!answers.length) { text(document.getElementById("wsaid"), "pick a choice or type an answer first"); return; }
  vPost("answer", { repo: vState.open, answers: answers });
});
document.getElementById("wsend").addEventListener("click", function () {
  var box = /** @type {HTMLInputElement} */ (document.getElementById("wmessage"));
  if (!box.value.trim()) { text(document.getElementById("wsaid"), "type a message first"); return; }
  var row = vRow(vState.open);
  vPost(row && row.console ? "say" : "send", { repo: vState.open, message: box.value.trim() }).then(function (r) {
    if (r.ok) box.value = "";
  });
});
document.getElementById("wmessage").addEventListener("keydown", function (e) {
  if (e.key === "Enter") document.getElementById("wsend").click();
});

document.addEventListener("keydown", function (e) {
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(/** @type {HTMLElement} */ (document.activeElement).tagName);
  if (e.key === "Escape") {
    if (vState.who) { vWho(false); e.preventDefault(); } else if (vState.open) { vStepBack(); e.preventDefault(); }
    return;
  }
  if (e.code === "F3" || (e.key === "`" && !typing)) { var s = document.getElementById("wstats"); hide(s, !s.hidden); e.preventDefault(); return; }
  if (typing || vState.open || vState.who) return;
  if (e.code === "KeyC") { vWho(true); e.preventDefault(); return; }
  if (e.code === "KeyV") { vView(vState.view === "third" ? "first" : "third"); return; }
  if ((e.code === "KeyE" || e.key === "Enter") && vState.near) { vTalk(vState.near); e.preventDefault(); return; }
  vState.keys[e.code] = true;
  if (/^Arrow/.test(e.code) || e.code === "Space") e.preventDefault();
});
document.addEventListener("keyup", function (e) { vState.keys[e.code] = false; });
window.addEventListener("blur", function () { vState.keys = {}; });

function vRefresh() {
  vState.refreshes++;
  vState.reading++;
  var done = function () { vState.reading--; };
  return fetch(q("/api/fleet")).then(function (r) { return r.json(); }).then(function (f) {
    if (!f || !f.ok) return;
    vState.rows = f.repos || [];
    vState.approvals = f.approvals || [];
    vState.rows.forEach(function (row) {
      if (vState.cursors[row.repo] == null && row.last_seq) vState.cursors[row.repo] = Number(row.last_seq);
    });
    if (vState.ready) vLayout();
    if (vState.open) drawPanel();
  }).then(done, function (e) { done(); throw e; });
}

function vSoon() {
  if (vState.timer) return;
  vState.timer = setTimeout(function () {
    vState.timer = null;
    vRefresh().catch(function () {});
  }, 400);
}

/** @param {string} state */
function vLiveAs(state) {
  vState.live = state;
  var dot = document.getElementById("wlive");
  setClass(dot, state === "live" ? "dot live" : "dot lost");
  text(dot, state);
}

function vConnect() {
  if (vState.source) vState.source.close();
  var since = Object.keys(vState.cursors).map(function (k) { return k + ":" + vState.cursors[k]; }).join(",");
  var params = { since: since, w: W_NAME, page: "world", notify: "0" };
  if (PARAMS.get("shell")) params.shell = PARAMS.get("shell");
  var source = vState.source = new EventSource(q("/api/events", params));
  source.addEventListener("agent", function (m) {
    var at = String(/** @type {MessageEvent} */ (m).lastEventId || "").split(":");
    if (at.length === 2) vState.cursors[at[0]] = Number(at[1]);
    vSoon();
  });
  source.addEventListener("polls", vSoon);
  source.addEventListener("desk", vSoon);
  source.addEventListener("theme", function (m) {
    try { applyThemeState(JSON.parse(/** @type {MessageEvent} */ (m).data)); } catch (err) {}
  });
  source.addEventListener("tick", function () { vLiveAs("live"); });
  source.onopen = function () { vLiveAs("live"); };
  source.onerror = function () {
    vLiveAs("reconnecting");
    source.close();
    if (vState.source !== source) return;
    vState.source = null;
    setTimeout(function () {
      var again = function () { if (!vState.source && !document.hidden) vConnect(); };
      vRefresh().then(again, again);
    }, 2000);
  };
}

document.addEventListener("visibilitychange", function () {
  if (vState.source) { vState.source.close(); vState.source = null; }
  vState.last = 0;
  if (document.visibilityState === "visible") vRefresh().then(vConnect, vConnect);
});

function vStart() {
  hide(document.getElementById("wstats"), PARAMS.get("hud") !== "1");
  return Promise.all([import(q(V_THREE)), vRefresh()]).then(function (got) {
    vState.T = got[0];
    vBuild();
    vState.ready = true;
    vLayout();
    var kept = vLoadLook();
    vLook(kept || WorldHero.preset(0));
    vView(PARAMS.get("view") === "first" ? "first" : "third");
    if (!kept) vWho(true);
    var first = vState.rows.filter(function (r) { return r.needs_human; })[0] || vState.rows[0];
    var ag = first && vState.agents.get(first.repo);
    if (ag) vState.player.yaw = Math.atan2(-ag.x, -ag.z);
    vConnect();
  }).catch(function (e) {
    vState.why = String((e && e.message) || e);
    hide(document.getElementById("wnogl"), false);
    hide(document.getElementById("whelp"), true);
    text(document.getElementById("wnoglwhy"), vState.why);
    vRefresh().then(vConnect, vConnect);
  });
}

vStart();

window.FleetWorld = Object.freeze({
  get w() { return W_NAME; },
  inspect: function () {
    var r = vState.renderer;
    return {
      ready: vState.ready, why: vState.why, frames: vState.frames, held: vState.held,
      agents: Array.from(vState.agents.values()).map(function (a) {
        return { repo: a.repo, x: a.x, z: a.z, state: a.state, needs: a.needs };
      }),
      beacons: vState.parts.beacon ? vState.parts.beacon.count : 0,
      player: Object.assign({}, vState.player), near: vState.near, open: vState.open,
      daylight: vState.daylight, night: vState.daylight < 0.5,
      lamps: vState.lights.bulbs ? vState.lights.bulbs[0].intensity : 0,
      rain: V_RAIN, calls: r ? r.info.render.calls : 0, triangles: r ? r.info.render.triangles : 0,
      fps: vState.intervals.length ? Math.round(1000 / vPct(vState.intervals.slice(-120), 0.5)) : 0,
      frameMs: vPct(vState.intervals.slice(-120), 0.5), workMs: vPct(vState.work.slice(-120), 0.5),
      scale: vState.scale, refreshMs: vState.refresh, budgetMs: V_BUDGET_MS,
      view: vState.view, who: vState.who, look: vState.avatar && Object.assign({}, vState.avatar),
      hero: vState.hero ? { visible: vState.hero.group.visible, seated: vState.hero.seated, wheels: !!vState.hero.wheels,
                            x: vState.hero.group.position.x, z: vState.hero.group.position.z, yaw: vState.hero.group.rotation.y,
                            legL: vState.hero.limbs.legL.rotation.x, armR: vState.hero.limbs.armR.rotation.z,
                            hips: vState.hero.hips.position.y } : null
    };
  },
  hold: function (on) { vState.held = !!on; vState.keys = {}; },
  step: function (seconds) {
    var n = Math.max(1, Math.round(seconds * 60));
    for (var i = 0; i < n; i++) vStep(1 / 60);
    return Object.assign({}, vState.player);
  },
  teleport: function (repo, back) {
    var ag = vState.agents.get(repo);
    if (!ag) return false;
    var d = back == null ? 2 : back, len = Math.hypot(ag.x, ag.z) || 1;
    vState.player.x = ag.x - ag.x / len * d;
    vState.player.z = ag.z - ag.z / len * d;
    vState.player.yaw = Math.atan2(-(ag.x - vState.player.x), -(ag.z - vState.player.z));
    vState.player.pitch = 0;
    vNearest();
    return true;
  }
});
