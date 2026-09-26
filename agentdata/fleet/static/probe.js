var DURATION_MS = 3000;
var ROWS = 12;
var PER_ROW = 40;
var WATCHDOG_MS = DURATION_MS + 12000;
var PAPER = 0xfaf8f2;
var PENCIL = 0x8a877d;
var INK = 0x1f3a93;

var SHELL = PARAMS.get("shell") || PARAMS.get("w") || "browser";
var posted = false;
var FEATURES = {};
var HIC_API = "";

function show(id, value) {
  text(document.getElementById(id), value);
}

function ms(value) {
  return value == null ? "—" : Math.round(value * 10) / 10 + " ms";
}

function contextOf(canvas) {
  var attrs = { antialias: true, alpha: false, powerPreference: "high-performance" };
  var out = { gl: null, kind: "none", why: "" };
  canvas.addEventListener("webglcontextcreationerror", function (e) {
    if (e && e.statusMessage) out.why = e.statusMessage;
  });
  try {
    out.gl = canvas.getContext("webgl2", attrs);
    if (out.gl) out.kind = "webgl2";
  } catch (e) {
    out.why = String((e && e.message) || e);
  }
  if (!out.gl) {
    try {
      out.gl = canvas.getContext("webgl", attrs);
      if (out.gl) out.kind = "webgl1";
    } catch (e) {
      out.why = String((e && e.message) || e);
    }
  }
  if (!out.gl && !out.why) out.why = "getContext answered null for webgl2 and for webgl";
  return out;
}

function named(gl) {
  var ext = null;
  try { ext = gl.getExtension("WEBGL_debug_renderer_info"); } catch (e) { ext = null; }
  if (!ext) return { renderer: "", vendor: "" };
  var renderer = "", vendor = "";
  try {
    renderer = String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "");
    vendor = String(gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) || "");
  } catch (e) {
    renderer = renderer || "";
  }
  return { renderer: renderer, vendor: vendor };
}

function caveat(kind) {
  var c = document.createElement("canvas");
  c.width = 1;
  c.height = 1;
  var gl = null;
  try {
    gl = c.getContext(kind === "webgl1" ? "webgl" : "webgl2", { failIfMajorPerformanceCaveat: true });
  } catch (e) {
    gl = null;
  }
  if (gl) {
    var lose = gl.getExtension("WEBGL_lose_context");
    if (lose) lose.loseContext();
  }
  return !gl;
}

function features() {
  var out = {};
  var ask = function (name, probe) {
    try { out[name] = !!probe(); } catch (e) { out[name] = false; }
  };
  ask("@starting-style", function () {
    return CSS.supports("selector(:not(*))") && typeof CSSStartingStyleRule !== "undefined";
  });
  ask("transition-behavior: allow-discrete", function () {
    return CSS.supports("transition-behavior", "allow-discrete");
  });
  ask("startViewTransition", function () { return typeof document.startViewTransition === "function"; });
  ask("linear() easing", function () {
    return CSS.supports("animation-timing-function", "linear(0, 1)");
  });
  ask("pointer capture", function () {
    return typeof Element.prototype.setPointerCapture === "function";
  });
  ask("ResizeObserver", function () { return typeof ResizeObserver === "function"; });
  ask("container queries", containerQueries);
  ask("OffscreenCanvas", function () { return typeof OffscreenCanvas !== "undefined"; });
  ask("HTML-in-canvas", htmlInCanvas);
  return out;
}

var HIC_NAMES = ["texElementImage2D", "texElementSubImage2D", "texElement2D"];
function htmlInCanvas() {
  if (typeof WebGL2RenderingContext === "undefined") return false;
  var proto = WebGL2RenderingContext.prototype;
  for (var i = 0; i < HIC_NAMES.length; i++) {
    if (typeof proto[HIC_NAMES[i]] === "function") {
      HIC_API = HIC_NAMES[i] + "/" + proto[HIC_NAMES[i]].length;
      return true;
    }
  }
  return false;
}

function containerQueries() {
  if (!(window.CSS && CSS.supports("container-type", "inline-size"))) return false;
  var sheet = document.createElement("style");
  sheet.textContent = "#cq-probe{container-type:inline-size;width:150px;position:absolute;" +
                      "left:-9999px;top:0}#cq-probe>i{display:block;width:3px}" +
                      "@container (max-width: 200px){#cq-probe>i{width:7px}}";
  var box = document.createElement("div");
  box.id = "cq-probe";
  box.appendChild(document.createElement("i"));
  document.head.appendChild(sheet);
  document.body.appendChild(box);
  var applied = getComputedStyle(box.firstChild).width === "7px";
  box.remove();
  sheet.remove();
  return applied;
}

function strokes() {
  var pos = [];
  for (var r = 0; r < ROWS; r++) {
    var y0 = 0.12 + r * 0.066;
    var px = 0, py = 0;
    for (var i = 0; i <= PER_ROW; i++) {
      var x = 0.08 + 0.84 * i / PER_ROW;
      var y = y0 + 0.012 * Math.sin(i * 0.9 + r) + 0.005 * Math.sin(i * 2.3 + r * 1.7);
      if (i > 0) pos.push(px, py, 0, x, y, 0);
      px = x;
      py = y;
    }
  }
  return new Float32Array(pos);
}

function painted(gl) {
  var w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
  if (!w || !h) return false;
  var y0 = Math.max(0, Math.floor(h * 0.09));
  var rows = Math.max(1, Math.min(h - y0, Math.ceil(h * 0.06)));
  var px = new Uint8Array(w * rows * 4);
  gl.readPixels(0, y0, w, rows, gl.RGBA, gl.UNSIGNED_BYTE, px);
  var pr = (PAPER >> 16) & 255, pg = (PAPER >> 8) & 255, pb = PAPER & 255;
  for (var i = 0; i < px.length; i += 4) {
    if (Math.abs(px[i] - pr) + Math.abs(px[i + 1] - pg) + Math.abs(px[i + 2] - pb) > 48) return true;
  }
  return false;
}

function finish(facts) {
  if (posted) return;
  posted = true;
  backLink();
  var body = Object.assign({ shell: SHELL, ua: navigator.userAgent, webgl: "none", renderer: "",
                             vendor: "", caveat: false, three: "", intervals: [],
                             first_stroke_ms: null, load_ms: null, drawn: false, hidden: false,
                             error: "", features: FEATURES, hic_api: HIC_API },
                           facts || {});
  show("state", "saving…");
  post("probe", body).then(function (r) {
    if (!r || r.ok === false) {
      show("verdict", "not saved");
      show("state", ((r && r.error) || "the desk refused it") + (r && r.hint ? " — " + r.hint : ""));
      return goBackLater();
    }
    var rec = r.record || {};
    show("verdict", r.verdict + " (" + r["class"] + ")");
    var cells = r.features || {};
    var short = Object.keys(cells).filter(function (name) { return cells[name] !== "works"; });
    show("features", short.length
      ? short.map(function (name) { return name + ": " + cells[name]; }).join("; ")
      : "every row works");
    show("frames", ms(rec.p50_ms) + " / " + ms(rec.p95_ms) + " over " + rec.frames + " frames");
    show("stroke", ms(rec.first_stroke_ms));
    show("state", r.kept
      ? "saved as “" + r.shell + "”'s latest attempt only: the probe did not finish, so the " +
        r.kept_at + " measurement stands (" + r.kept_verdict + ")."
      : "saved as “" + r.shell + "” in " + r.file + ". `ad-fleet engines` prints it.");
    goBackLater();
  }).catch(function (e) {
    show("verdict", "not saved");
    show("state", "the desk did not answer: " + String((e && e.message) || e));
    goBackLater();
  });
}

function backLink() {
  var link = document.getElementById("back");
  var dest = new URL("/open", location.origin);
  PARAMS.forEach(function (value, key) {
    if (key !== "shell" && key !== "back" && key !== "t") dest.searchParams.set(key, value);
  });
  link.href = dest.toString();
  hide(link, false);
  return dest.toString();
}

function goBackLater() {
  var dest = backLink();
  if (PARAMS.get("back") !== "1") return;
  var left = 8;
  var tick = function () {
    if (left <= 0) {
      location.assign(dest);
      return;
    }
    show("back", "back to the desk (in " + left + " s)");
    left -= 1;
    setTimeout(tick, 1000);
  };
  tick();
}

function measure(THREE, canvas, ctx, facts) {
  var renderer = new THREE.WebGLRenderer({ canvas: canvas, context: ctx.gl, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  renderer.setClearColor(PAPER, 1);

  var scene = new THREE.Scene();
  var camera = new THREE.OrthographicCamera(0, 1, 1, 0, -1, 1);
  var positions = strokes();
  var pencilGeo = new THREE.BufferGeometry();
  pencilGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  var inkGeo = new THREE.BufferGeometry();
  inkGeo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  var pencil = new THREE.LineSegments(pencilGeo, new THREE.LineBasicMaterial({ color: PENCIL }));
  var ink = new THREE.LineSegments(inkGeo, new THREE.LineBasicMaterial({ color: INK }));
  ink.position.y = 0.004;
  ink.renderOrder = 1;
  scene.add(pencil);
  scene.add(ink);
  var vertices = positions.length / 3;

  var lost = false;
  canvas.addEventListener("webglcontextlost", function () { lost = true; });

  var start = 0, last = 0, first = null, drawn = false, settled = false;
  var intervals = [];

  function done(error, hidden) {
    if (posted) return;
    facts.intervals = intervals;
    facts.first_stroke_ms = first;
    facts.drawn = drawn;
    if (hidden) facts.hidden = true;
    if (error) facts.error = error;
    finish(facts);
  }

  function frame(now) {
    if (posted) return;
    if (lost) return done("the WebGL context was lost while drawing");
    if (!start) start = now;
    var t = Math.min(1, (now - start) / DURATION_MS);
    inkGeo.setDrawRange(0, Math.floor(t * vertices / 2) * 2);
    try {
      renderer.render(scene, camera);
    } catch (e) {
      return done("render threw: " + String((e && e.message) || e));
    }
    if (first === null) {
      drawn = painted(ctx.gl);
      first = performance.now();
      if (!drawn) return done("the first frame rendered and holds no stroke");
    } else if (settled) {
      intervals.push(now - last);
    } else {
      settled = true;
    }
    last = now;
    if (now - start >= DURATION_MS) return done("");
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) done("the window was hidden while it drew", true);
  });
  setTimeout(function () {
    done("frames stopped arriving", document.hidden);
  }, WATCHDOG_MS);
}

function whenVisible(go) {
  if (!document.hidden) return go();
  show("state", "waiting for this window to be shown…");
  var on = function () {
    if (document.hidden) return;
    document.removeEventListener("visibilitychange", on);
    go();
  };
  document.addEventListener("visibilitychange", on);
}

function main() {
  show("shell", SHELL);
  FEATURES = features();
  var canvas = document.getElementById("stage");
  var ctx = contextOf(canvas);
  var facts = { webgl: ctx.kind };
  if (!ctx.gl) {
    show("context", "none");
    show("renderer", "—");
    facts.error = "no WebGL: " + ctx.why;
    show("state", facts.error);
    return finish(facts);
  }
  var who = named(ctx.gl);
  facts.renderer = who.renderer;
  facts.vendor = who.vendor;
  facts.caveat = caveat(ctx.kind);
  show("context", ctx.kind === "webgl2" ? "WebGL2" : "WebGL1");
  show("renderer", who.renderer || "(not named — this browser will not unmask it)");

  import(q("/static/vendor/three/three.module.min.js")).then(function (THREE) {
    facts.three = String(THREE.REVISION || "");
    facts.load_ms = performance.now();
    whenVisible(function () {
      show("state", "drawing for three seconds…");
      try {
        measure(THREE, canvas, ctx, facts);
      } catch (e) {
        facts.error = "three.js could not draw: " + String((e && e.message) || e);
        finish(facts);
      }
    });
  }).catch(function (e) {
    facts.error = "three.js did not load: " + String((e && e.message) || e);
    finish(facts);
  });
}

main();
