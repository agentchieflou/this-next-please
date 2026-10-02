"use strict";

var WorldScenery = (function () {
  var NOISE = "float wsH(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }\n"
    + "float wsN(vec2 p) { vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);"
    + " return mix(mix(wsH(i), wsH(i + vec2(1.0, 0.0)), f.x), mix(wsH(i + vec2(0.0, 1.0)), wsH(i + vec2(1.0, 1.0)), f.x), f.y); }\n"
    + "float wsF(vec2 p) { return wsN(p) * 0.55 + wsN(p * 2.03 + 7.1) * 0.3 + wsN(p * 4.1 + 3.3) * 0.15; }\n";
  var FACADES = ["#6e7378", "#7d7468", "#5f6a73", "#8a7a6a", "#6b5f5a", "#74808a", "#5a5f66", "#8d8579"];
  var WOOD = "#7a5236";
  var IRON = "#262c31";
  var STONE = "#8d9196";
  var SOIL = "#2e2620";
  var BARK = "#4a3528";
  var LEAVES = ["#3d6a3a", "#4a7a42", "#335b33", "#557f46"];
  var u = { time: { value: 0 }, night: { value: 0 }, wet: { value: 1 }, radius: { value: 10 }, lit: { value: 0.35 } };

  /** @param {number} n @returns {number} */
  function rnd(n) {
    var x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
    return x - Math.floor(x);
  }

  /** @param {any} T @param {any} geo @param {string} hex @param {Array<number>} at @param {Array<number>} [scale] @param {Array<number>} [turn] @param {number} [yaw] @returns {any} */
  function piece(T, geo, hex, at, scale, turn, yaw) {
    var g = geo.index ? geo.toNonIndexed() : geo;
    var s = scale || [1, 1, 1], r = turn || [0, 0, 0];
    g.applyMatrix4(new T.Matrix4().compose(new T.Vector3(at[0], at[1], at[2]),
      new T.Quaternion().setFromEuler(new T.Euler(r[0], r[1], r[2])), new T.Vector3(s[0], s[1], s[2])));
    if (yaw) g.applyMatrix4(new T.Matrix4().makeRotationY(yaw));
    var c = new T.Color(hex), n = g.attributes.position.count, col = new Float32Array(n * 3);
    for (var i = 0; i < n; i++) { col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b; }
    g.setAttribute("color", new T.BufferAttribute(col, 3));
    return g;
  }

  /** @param {any} T @param {any} g @param {number} x @param {number} z @returns {any} */
  function moved(T, g, x, z) {
    g.applyMatrix4(new T.Matrix4().makeTranslation(x, 0, z));
    return g;
  }

  /** @param {any} T @param {Array<any>} list @param {Array<string>} [extra] @returns {any} */
  function merge(T, list, extra) {
    var keys = ["position", "normal", "color"].concat(extra || []), total = 0;
    list.forEach(function (g) { total += g.attributes.position.count; });
    var out = new T.BufferGeometry();
    keys.forEach(function (k) {
      var size = list[0].attributes[k].itemSize, arr = new Float32Array(total * size), at = 0;
      list.forEach(function (g) { arr.set(g.attributes[k].array, at * size); at += g.attributes.position.count; });
      out.setAttribute(k, new T.BufferAttribute(arr, size));
    });
    list.forEach(function (g) { g.dispose(); });
    out.computeBoundingSphere();
    return out;
  }

  /** @param {any} T @returns {any} */
  function ground(T) {
    var mat = new T.MeshStandardMaterial({ color: 0xffffff, roughness: 0.5, metalness: 0, envMapIntensity: 0.7 });
    mat.onBeforeCompile = function (/** @type {any} */ sh) {
      sh.uniforms.uTime = u.time;
      sh.uniforms.uWet = u.wet;
      sh.uniforms.uR = u.radius;
      sh.vertexShader = "varying vec3 vWp;\n" + sh.vertexShader.replace("#include <begin_vertex>",
        "#include <begin_vertex>\nvWp = (modelMatrix * vec4(transformed, 1.0)).xyz;");
      sh.fragmentShader = "uniform float uTime; uniform float uWet; uniform float uR; varying vec3 vWp;\n" + NOISE
        + sh.fragmentShader
          .replace("#include <color_fragment>", [
            "#include <color_fragment>",
            "vec2 g = vWp.xz; float dist = length(g); float ang = atan(g.y, g.x) / 6.28318 + 0.5;",
            "float inPlaza = 1.0 - smoothstep(uR - 0.05, uR + 0.05, dist);",
            "float ringW = 1.25; float ri = floor(dist / ringW); float segs = 6.0 + ri * 6.0;",
            "float fr = fract(dist / ringW); float fa = fract(ang * segs + ri * 0.37);",
            "float joint = min(min(fr, 1.0 - fr) * ringW, min(fa, 1.0 - fa) * 6.28318 * max(dist, 0.6) / segs);",
            "float grout = (1.0 - smoothstep(0.015, 0.045, joint)) * step(2.2, dist);",
            "float stone = wsH(vec2(ri, floor(ang * segs + ri * 0.37)));",
            "vec3 pave = vec3(0.46, 0.46, 0.47) * (0.82 + 0.3 * stone);",
            "float inlay = smoothstep(1.62, 1.6, dist) - smoothstep(1.92, 1.9, dist);",
            "float star = step(dist, 1.45 * (0.18 + 0.82 * pow(abs(cos(ang * 6.28318 * 2.0)), 18.0)));",
            "float disc = step(dist, 2.2) * (1.0 - star) * (1.0 - inlay);",
            "pave = mix(pave, vec3(0.34, 0.36, 0.39), disc);",
            "pave = mix(pave, vec3(0.62, 0.5, 0.3), max(inlay, star));",
            "float n = wsF(g * 0.9);",
            "vec3 tar = vec3(0.16, 0.175, 0.19) * (0.78 + 0.44 * n);",
            "vec3 base = mix(tar, pave * (1.0 - 0.5 * grout), inPlaza);",
            "float pn = wsF(g * 0.17 + 11.0);",
            "float puddle = smoothstep(0.57, 0.63, pn + grout * 0.06) * uWet;",
            "diffuseColor.rgb = base * mix(1.0, 0.42, puddle);"
          ].join("\n"))
          .replace("#include <roughnessmap_fragment>",
            "#include <roughnessmap_fragment>\nroughnessFactor = mix(mix(0.58, 0.4, inPlaza) * (0.85 + 0.3 * n) + grout * 0.25,"
            + " 0.03, puddle) * mix(1.0, 0.75, max(inlay, star) * inPlaza);")
          .replace("#include <normal_fragment_maps>",
            "#include <normal_fragment_maps>\nvec2 rp = g * 3.1;"
            + " vec2 rip = vec2(sin(rp.x * 2.1 + uTime * 2.3 + sin(rp.y * 1.7)), cos(rp.y * 2.3 - uTime * 1.9 + sin(rp.x * 1.3)));"
            + " normal = normalize(normal + vec3(rip * (0.035 * puddle + 0.012), 0.0));");
    };
    var mesh = new T.Mesh(new T.PlaneGeometry(600, 600), mat);
    mesh.rotation.x = -Math.PI / 2;
    return mesh;
  }

  /** @param {any} T @param {Array<any>} list @param {number} cx @param {number} cz @param {number} w @param {number} d @param {number} y0 @param {number} h @param {string} hex @param {number} seed @param {number} yaw */
  function block(T, list, cx, cz, w, d, y0, h, hex, seed, yaw) {
    var c = new T.Color(hex), cos = Math.cos(yaw), sin = Math.sin(yaw);
    var corners = [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]].map(function (p) {
      return [cx + p[0] * cos + p[1] * sin, cz - p[0] * sin + p[1] * cos];
    });
    var pos = [], nor = [], col = [], win = [];
    for (var i = 0; i < 4; i++) {
      var p = corners[i], q = corners[(i + 1) % 4], len = Math.hypot(q[0] - p[0], q[1] - p[1]);
      var nx = (q[1] - p[1]) / len, nz = -(q[0] - p[0]) / len;
      var verts = [[p[0], y0, p[1], 0, y0], [q[0], y0 + h, q[1], len, y0 + h], [q[0], y0, q[1], len, y0],
                   [p[0], y0, p[1], 0, y0], [p[0], y0 + h, p[1], 0, y0 + h], [q[0], y0 + h, q[1], len, y0 + h]];
      var shade = 0.92 + 0.08 * Math.abs(nx);
      verts.forEach(function (v) {
        pos.push(v[0], v[1], v[2]); nor.push(nx, 0, nz);
        col.push(c.r * shade, c.g * shade, c.b * shade);
        win.push(v[3], v[4], seed + i * 0.17, 1);
      });
    }
    var top = [corners[0], corners[2], corners[1], corners[0], corners[3], corners[2]];
    top.forEach(function (t) {
      pos.push(t[0], y0 + h, t[1]); nor.push(0, 1, 0);
      col.push(c.r * 0.6, c.g * 0.6, c.b * 0.62);
      win.push(0, 0, seed, 0);
    });
    var g = new T.BufferGeometry();
    g.setAttribute("position", new T.BufferAttribute(new Float32Array(pos), 3));
    g.setAttribute("normal", new T.BufferAttribute(new Float32Array(nor), 3));
    g.setAttribute("color", new T.BufferAttribute(new Float32Array(col), 3));
    g.setAttribute("aWin", new T.BufferAttribute(new Float32Array(win), 4));
    list.push(g);
  }

  /** @param {any} T @returns {any} */
  function city(T) {
    var list = [];
    for (var i = 0; i < 44; i++) {
      var a = i / 44 * Math.PI * 2 + rnd(i) * 0.08, r = 62 + rnd(i + 3) * 58;
      var w = 9 + rnd(i + 7) * 10, d = 9 + rnd(i + 11) * 9, h = 14 + rnd(i + 13) * 40, yaw = -a + Math.PI / 2;
      var x = Math.cos(a) * r, z = Math.sin(a) * r, hex = FACADES[i % FACADES.length], seed = rnd(i + 17) * 100;
      block(T, list, x, z, w, d, 0, h, hex, seed, yaw);
      block(T, list, x, z, w + 0.6, d + 0.6, h, 0.9, hex, seed + 1, yaw);
      if (rnd(i + 19) > 0.45) {
        var h2 = 6 + rnd(i + 23) * 18;
        block(T, list, x, z, w * 0.62, d * 0.62, h + 0.9, h2, hex, seed + 2, yaw);
        block(T, list, x, z, w * 0.62 + 0.5, d * 0.62 + 0.5, h + 0.9 + h2, 0.7, hex, seed + 3, yaw);
      }
      if (rnd(i + 29) > 0.6) block(T, list, x + 1.5, z + 1.2, 2.4, 2.4, h + 0.9, 2.2, "#3a3f44", seed + 4, yaw);
    }
    var mat = new T.MeshLambertMaterial({ vertexColors: true });
    mat.extensions = { derivatives: true };
    mat.onBeforeCompile = function (/** @type {any} */ sh) {
      sh.uniforms.uNight = u.night;
      sh.uniforms.uLit = u.lit;
      sh.vertexShader = "attribute vec4 aWin; varying vec4 vWin;\n" + sh.vertexShader.replace("#include <begin_vertex>",
        "#include <begin_vertex>\nvWin = aWin;");
      sh.fragmentShader = "uniform float uNight; uniform float uLit; varying vec4 vWin;\n" + NOISE + sh.fragmentShader
        .replace("#include <color_fragment>", [
          "#include <color_fragment>",
          "vec2 cell = vec2(2.6, 3.3); vec2 c = vWin.xy / cell; vec2 id = floor(c); vec2 f = fract(c);",
          "float shop = 1.0 - step(1.0, id.y);",
          "vec2 fw = max(fwidth(c), vec2(0.0001)); float far = smoothstep(0.25, 0.6, max(fw.x, fw.y));",
          "vec2 lo = mix(vec2(0.2, 0.24), vec2(0.06, 0.08), shop); vec2 hi = mix(vec2(0.8, 0.76), vec2(0.94, 0.7), shop);",
          "vec2 w2 = smoothstep(lo - fw, lo + fw, f) * (1.0 - smoothstep(hi - fw, hi + fw, f));",
          "float win = vWin.w * mix(w2.x * w2.y, 0.33, far);",
          "float hw = mix(wsH(id + vWin.z * 17.0), 0.5, far);",
          "vec3 glass = mix(vec3(0.11, 0.13, 0.16), vec3(0.36, 0.42, 0.5), fract(hw * 7.0) * 0.7);",
          "diffuseColor.rgb = mix(diffuseColor.rgb * (0.94 + 0.06 * step(0.5, fract(vWin.y / cell.y))), glass, win);",
          "float lit = mix(step(1.0 - mix(uLit, 0.8, shop), fract(hw * 3.7 + 0.13)), uLit, far);",
          "vec3 lamp = mix(vec3(1.0, 0.76, 0.46), vec3(0.72, 0.84, 1.0), step(0.72, fract(hw * 13.0)));",
          "vec3 wsLit = win * lit * lamp * uNight * (0.55 + 0.45 * fract(hw * 29.0));"
        ].join("\n"))
        .replace("#include <emissivemap_fragment>", "#include <emissivemap_fragment>\ntotalEmissiveRadiance += wsLit;")
        .replace("#include <fog_fragment>", "#include <fog_fragment>\n#ifdef USE_FOG\ngl_FragColor.rgb += wsLit * fogFactor * 0.5;\n#endif");
    };
    var mesh = new T.Mesh(merge(T, list, ["aWin"]), mat);
    mesh.frustumCulled = false;
    return mesh;
  }

  /** @param {any} T @returns {any} */
  function sky(T) {
    var mat = new T.ShaderMaterial({
      uniforms: { uTop: { value: new T.Color() }, uHorizon: { value: new T.Color() }, uGlow: { value: new T.Color(0x000000) },
                  uCloud: { value: new T.Color() } },
      vertexShader: "varying vec3 vDir; void main() { vDir = normalize(position);"
        + " gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: "uniform vec3 uTop; uniform vec3 uHorizon; uniform vec3 uGlow; uniform vec3 uCloud; varying vec3 vDir;\n" + NOISE
        + "void main() { float y = vDir.y; vec3 c = mix(uHorizon, uTop, smoothstep(-0.05, 0.6, y));"
        + " vec2 p = vDir.xz / max(y + 0.12, 0.06) * 1.4; float cl = wsF(p) * 0.7 + wsF(p * 2.7 + 5.0) * 0.3;"
        + " c = mix(c, uCloud, smoothstep(0.38, 0.75, cl) * smoothstep(-0.02, 0.18, y) * 0.75);"
        + " c += uGlow * (1.0 - smoothstep(-0.05, 0.28, y));"
        + " gl_FragColor = vec4(c, 1.0); }",
      side: T.BackSide, depthWrite: false, fog: false
    });
    var mesh = new T.Mesh(new T.SphereGeometry(320, 32, 16), mat);
    mesh.renderOrder = -1;
    mesh.frustumCulled = false;
    return mesh;
  }

  /** @param {any} T @param {Array<any>} metal @param {Array<any>} glass @param {number} x @param {number} z @param {number} yaw */
  function lamp(T, metal, glass, x, z, yaw) {
    var at = function (/** @type {any} */ g) { return moved(T, g, x, z); };
    metal.push(at(piece(T, new T.CylinderGeometry(0.15, 0.2, 0.42, 10), IRON, [0, 0.21, 0], null, null, yaw)));
    metal.push(at(piece(T, new T.CylinderGeometry(0.055, 0.08, 4.1, 10), IRON, [0, 2.4, 0], null, null, yaw)));
    metal.push(at(piece(T, new T.TorusGeometry(0.09, 0.025, 6, 12), IRON, [0, 1.1, 0], null, [Math.PI / 2, 0, 0], yaw)));
    metal.push(at(piece(T, new T.CylinderGeometry(0.03, 0.035, 0.9, 6), IRON, [0.42, 4.38, 0], null, [0, 0, Math.PI / 2 - 0.18], yaw)));
    metal.push(at(piece(T, new T.TorusGeometry(0.22, 0.022, 6, 14, Math.PI * 0.9), IRON, [0.18, 4.2, 0], null, [0, 0, 0.3], yaw)));
    metal.push(at(piece(T, new T.CylinderGeometry(0.06, 0.34, 0.2, 6), IRON, [0.84, 4.4, 0], null, null, yaw)));
    metal.push(at(piece(T, new T.SphereGeometry(0.05, 8, 6), IRON, [0.84, 4.52, 0], null, null, yaw)));
    metal.push(at(piece(T, new T.CylinderGeometry(0.17, 0.12, 0.08, 6), IRON, [0.84, 3.88, 0], null, null, yaw)));
    glass.push(at(piece(T, new T.CylinderGeometry(0.25, 0.16, 0.42, 6), "#ffffff", [0.84, 4.1, 0], null, null, yaw)));
  }

  /** @param {any} T @param {Array<any>} out @param {number} x @param {number} z @param {number} yaw */
  function bench(T, out, x, z, yaw) {
    var at = function (/** @type {any} */ g) { return moved(T, g, x, z); };
    [-0.15, 0, 0.15].forEach(function (dz) {
      out.push(at(piece(T, new T.BoxGeometry(1.7, 0.045, 0.12), WOOD, [0, 0.46, dz], null, null, yaw)));
    });
    [0.66, 0.84].forEach(function (y) {
      out.push(at(piece(T, new T.BoxGeometry(1.7, 0.11, 0.04), WOOD, [0, y, -0.25 - (y - 0.66) * 0.25], null, [-0.22, 0, 0], yaw)));
    });
    [-0.74, 0.74].forEach(function (dx) {
      out.push(at(piece(T, new T.BoxGeometry(0.06, 0.44, 0.06), IRON, [dx, 0.22, 0.17], null, null, yaw)));
      out.push(at(piece(T, new T.BoxGeometry(0.06, 0.9, 0.06), IRON, [dx, 0.45, -0.24], null, [-0.18, 0, 0], yaw)));
      out.push(at(piece(T, new T.BoxGeometry(0.07, 0.05, 0.52), IRON, [dx, 0.62, -0.02], null, null, yaw)));
    });
  }

  /** @param {any} T @param {Array<any>} out @param {number} x @param {number} z @param {number} seed */
  function tree(T, out, x, z, seed) {
    var at = function (/** @type {any} */ g) { return moved(T, g, x, z); };
    out.push(at(piece(T, new T.CylinderGeometry(0.72, 0.62, 0.5, 14), STONE, [0, 0.25, 0])));
    out.push(at(piece(T, new T.CylinderGeometry(0.64, 0.64, 0.04, 14), SOIL, [0, 0.49, 0])));
    out.push(at(piece(T, new T.CylinderGeometry(0.07, 0.12, 2.3, 7), BARK, [0, 1.6, 0], null, [0.04 * (seed - 0.5), 0, 0.05])));
    out.push(at(piece(T, new T.CylinderGeometry(0.03, 0.05, 0.8, 5), BARK, [0.22, 2.3, 0], null, [0, 0, -0.8])));
    for (var k = 0; k < 4; k++) {
      var a = k * 2.1 + seed * 6, rr = k === 0 ? 0 : 0.55, s = 0.95 - k * 0.1 + rnd(seed * 10 + k) * 0.2;
      var leaf = new T.IcosahedronGeometry(1, 1);
      out.push(at(piece(T, leaf, LEAVES[(k + Math.floor(seed * 4)) % LEAVES.length],
        [Math.cos(a) * rr, 3.1 + (k === 0 ? 0.35 : rnd(seed + k) * 0.5), Math.sin(a) * rr], [s, s * 0.85, s])));
    }
  }

  /** @param {any} T @param {number} edge @returns {{props: any, glass: any, lamps: Array<Array<number>>, solids: Array<Array<number>>}} */
  function plaza(T, edge) {
    var metal = [], glass = [], lamps = [], solids = [];
    var kerb = new T.LatheGeometry([new T.Vector2(edge, 0), new T.Vector2(edge, 0.14), new T.Vector2(edge + 0.06, 0.16),
      new T.Vector2(edge + 0.4, 0.16), new T.Vector2(edge + 0.42, 0)], 120);
    metal.push(piece(T, kerb, "#9a9ea3", [0, 0, 0]));
    for (var i = 0; i < 8; i++) {
      var a = (i + 0.5) / 8 * Math.PI * 2, lx = Math.cos(a) * (edge + 1.5), lz = Math.sin(a) * (edge + 1.5);
      lamp(T, metal, glass, lx, lz, -a + Math.PI);
      lamps.push([lx - Math.cos(a) * 0.84, 4.1, lz - Math.sin(a) * 0.84]);
      solids.push([lx, lz, 0.3]);
      var b = i / 8 * Math.PI * 2, bx = Math.cos(b) * (edge + 1.1), bz = Math.sin(b) * (edge + 1.1);
      bench(T, metal, bx, bz, -b - Math.PI / 2);
      solids.push([bx, bz, 0.75]);
      var tx = Math.cos(b) * (edge + 3.9), tz = Math.sin(b) * (edge + 3.9);
      tree(T, metal, tx, tz, rnd(i + 41));
      solids.push([tx, tz, 0.85]);
    }
    var mat = new T.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.08 });
    var props = new T.Mesh(merge(T, metal), mat);
    props.frustumCulled = false;
    var gmat = new T.MeshBasicMaterial({ vertexColors: true, color: 0xffffff });
    var lights = new T.Mesh(merge(T, glass), gmat);
    lights.frustumCulled = false;
    return { props: props, glass: lights, lamps: lamps, solids: solids };
  }

  /** @param {any} T @returns {any} */
  function glows(T) {
    var mat = new T.ShaderMaterial({
      uniforms: { uOpacity: { value: 0 }, uColor: { value: new T.Color(0xffc98a) } },
      vertexShader: "varying vec2 vUv; void main() { vUv = position.xy;"
        + " vec4 mv = modelViewMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0); mv.xy += position.xy * 1.6;"
        + " gl_Position = projectionMatrix * mv; }",
      fragmentShader: "uniform float uOpacity; uniform vec3 uColor; varying vec2 vUv;"
        + " void main() { float r = length(vUv); float a = pow(max(0.0, 1.0 - r), 2.4) + 0.5 * pow(max(0.0, 1.0 - r * 3.0), 2.0);"
        + " gl_FragColor = vec4(uColor * a * uOpacity, 1.0); }",
      transparent: true, depthWrite: false, blending: T.AdditiveBlending, fog: false
    });
    var mesh = new T.InstancedMesh(new T.PlaneGeometry(2, 2), mat, 8);
    mesh.count = 0;
    mesh.frustumCulled = false;
    mesh.renderOrder = 4;
    return mesh;
  }

  /** @param {any} mesh @param {any} T @param {Array<Array<number>>} lamps */
  function placeGlows(mesh, T, lamps) {
    var m = new T.Matrix4();
    lamps.forEach(function (p, i) { mesh.setMatrixAt(i, m.makeTranslation(p[0], p[1], p[2])); });
    mesh.count = lamps.length;
    mesh.instanceMatrix.needsUpdate = true;
  }

  return Object.freeze({ uniforms: u, ground: ground, city: city, sky: sky, plaza: plaza, glows: glows,
                         placeGlows: placeGlows, rnd: rnd, piece: piece, merge: merge });
})();
