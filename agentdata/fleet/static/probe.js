/* The WebGL probe (#247): what this shell really does with three.js, measured here and kept by the
   desk, so the four columns of `docs/desk-engines.md` are filled from the shells themselves.

   Loaded as a module after `common.js`, whose globals (`PARAMS`, `q`, `post`, `text`) it uses.
   three.js comes in through `import()` rather than a static `import` for one reason: every route
   on this server wants the run token, and a module specifier resolved against this file's URL does
   not inherit its query string -- `q()` puts the token on, exactly as it does for every fetch.

   It sends FACTS and decides nothing. Whether a renderer is hardware is `probe.classify` in
   Python; the verdict shown at the end is the server's answer. It posts exactly once, on every
   path -- a shell with no WebGL is an answer too, and the most important one to write down. */

var DURATION_MS = 3000;
var ROWS = 12;
var PER_ROW = 40;                     // 12 x 40 = 480 segments: a page of handwriting, roughly
var WATCHDOG_MS = DURATION_MS + 12000;
var PAPER = 0xfaf8f2;
var PENCIL = 0x8a877d;
var INK = 0x1f3a93;

var SHELL = PARAMS.get("shell") || PARAMS.get("w") || "browser";
var posted = false;

function show(id, value) {
  text(document.getElementById(id), value);
}

function ms(value) {
  return value == null ? "—" : Math.round(value * 10) / 10 + " ms";
}

/* The context, asked for the way the ink layer will ask: WebGL2 first, WebGL1 if not. The error
   the browser gives with a refusal is kept, because "no WebGL" with no reason is a row nobody can
   act on. */
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

/* The unmasked strings. The masked `RENDERER` is "WebKit WebGL" in every Chromium and says
   nothing about the machine. */
function named(gl) {
  var ext = null;
  try { ext = gl.getExtension("WEBGL_debug_renderer_info"); } catch (e) { ext = null; }
  var renderer = "", vendor = "";
  try {
    renderer = String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || "");
    vendor = String(gl.getParameter(ext ? ext.UNMASKED_VENDOR_WEBGL : gl.VENDOR) || "");
  } catch (e) {
    renderer = renderer || "";
  }
  return { renderer: renderer, vendor: vendor };
}

/* The browser's own opinion, as a second witness beside the string: a context asked for with
   `failIfMajorPerformanceCaveat` is refused when it would be software. Not every engine says so --
   headless Chromium on SwiftShader grants it -- which is why the string is the first witness. */
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

/* A fixed page of pencil strokes: the same 480 segments on every run in every shell, so two
   shells' numbers are two measurements of one scene. No randomness anywhere. */
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

/* Whether the frame just rendered really holds the scene: the drawing buffer is read back and
   any pixel that is not paper counts. Called once, straight after the first `render()`, while the
   buffer is still this frame's. `readPixels` waits for the GPU, so this is also the moment the
   first stroke is on the canvas rather than merely asked for. */
function painted(gl) {
  var w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
  if (!w || !h) return false;
  var px = new Uint8Array(w * h * 4);
  gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, px);
  var pr = (PAPER >> 16) & 255, pg = (PAPER >> 8) & 255, pb = PAPER & 255;
  for (var i = 0; i < px.length; i += 4) {
    if (Math.abs(px[i] - pr) + Math.abs(px[i + 1] - pg) + Math.abs(px[i + 2] - pb) > 48) return true;
  }
  return false;
}

/* The one way out. Every path -- no context, three.js not loading, a lost context, a hidden
   window whose frames stopped, or three good seconds -- ends here, and here posts once. */
function finish(facts) {
  if (posted) return;
  posted = true;
  var body = Object.assign({ shell: SHELL, ua: navigator.userAgent, webgl: "none", renderer: "",
                             vendor: "", caveat: false, three: "", intervals: [],
                             first_stroke_ms: null, load_ms: null, drawn: false, error: "" },
                           facts || {});
  show("state", "saving…");
  post("probe", body).then(function (r) {
    if (!r || r.ok === false) {
      show("verdict", "not saved");
      show("state", ((r && r.error) || "the desk refused it") + (r && r.hint ? " — " + r.hint : ""));
      return;
    }
    var rec = r.record || {};
    show("verdict", r.verdict + " (" + r["class"] + ")");
    show("frames", ms(rec.p50_ms) + " / " + ms(rec.p95_ms) + " over " + rec.frames + " frames");
    show("stroke", ms(rec.first_stroke_ms));
    show("state", "saved as “" + r.shell + "” in " + r.file + ". `ad-fleet engines` prints it.");
    goBackLater();
  }).catch(function (e) {
    show("verdict", "not saved");
    show("state", "the desk did not answer: " + String((e && e.message) || e));
  });
}

/* When the desk sent this window here (`ad-fleet probe --open pycharm`), it goes back by itself
   a few seconds after saving: a tool window left on a probe page is a desk the operator has lost.
   The link is there either way. */
function backLink() {
  var link = document.getElementById("back");
  var dest = new URL("/", location.origin);
  PARAMS.forEach(function (value, key) {
    if (key !== "shell" && key !== "back") dest.searchParams.set(key, value);
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

  var start = 0, last = 0, first = null, drawn = false;
  var intervals = [];

  function done(error) {
    if (posted) return;
    facts.intervals = intervals;
    facts.first_stroke_ms = first;
    facts.drawn = drawn;
    if (error) facts.error = error;
    finish(facts);
  }

  /* Every frame draws the whole pencil page and the ink traced over it so far -- the pen reaches
     the end of the page at three seconds. The first frame compiles the shaders and is read back,
     so it is `first_stroke_ms` and not one of the intervals; p50 and p95 are the frames after it. */
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
    } else {
      intervals.push(now - last);
    }
    last = now;
    if (now - start >= DURATION_MS) return done("");
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  /* A hidden window gets no animation frames at all, and a probe that never posts is a shell the
     table will call "not yet measured" forever. So: whatever arrived, after the watchdog. */
  setTimeout(function () {
    done("frames stopped arriving (was the window hidden?)");
  }, WATCHDOG_MS);
}

function main() {
  show("shell", SHELL);
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
  show("renderer", who.renderer || "(not named)");

  import(q("/static/vendor/three/three.module.min.js")).then(function (THREE) {
    facts.three = String(THREE.REVISION || "");
    facts.load_ms = performance.now();
    try {
      measure(THREE, canvas, ctx, facts);
    } catch (e) {
      facts.error = "three.js could not draw: " + String((e && e.message) || e);
      finish(facts);
    }
  }).catch(function (e) {
    facts.error = "three.js did not load: " + String((e && e.message) || e);
    finish(facts);
  });
}

main();
