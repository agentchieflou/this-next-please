"use strict";

var WorldScenery = (function () {
  var NOISE = WorldKit.NOISE;
  var WOOD = "#7a5236";
  var IRON = "#262c31";
  var STONE = "#8d9196";
  var SOIL = "#2e2620";
  var BARK = "#4a3528";
  var rnd = WorldKit.rnd, piece = WorldKit.piece, merge = WorldKit.merge;

  /** @param {any} T @param {any} g @param {number} x @param {number} z @returns {any} */
  function moved(T, g, x, z) {
    g.applyMatrix4(new T.Matrix4().makeTranslation(x, 0, z));
    return g;
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
  function tree(T, out, leaves, x, z, seed) {
    var at = function (/** @type {any} */ g) { return moved(T, g, x, z); };
    out.push(at(piece(T, new T.CylinderGeometry(0.72, 0.62, 0.5, 14), STONE, [0, 0.25, 0])));
    out.push(at(piece(T, new T.CylinderGeometry(0.64, 0.64, 0.04, 14), SOIL, [0, 0.49, 0])));
    out.push(at(piece(T, new T.CylinderGeometry(0.07, 0.12, 2.3, 7), BARK, [0, 1.6, 0], null, [0.04 * (seed - 0.5), 0, 0.05])));
    out.push(at(piece(T, new T.CylinderGeometry(0.03, 0.05, 0.8, 5), BARK, [0.22, 2.3, 0], null, [0, 0, -0.8])));
    WorldKit.canopy(T, leaves, x, 3.55, z, 1.45, seed * 31 + 7, 40);
  }

  /** @param {any} T @param {number} edge @param {Object} lib @returns {{props: any, glass: any, leaves: any, lamps: Array<Array<number>>, solids: Array<Array<number>>}} */
  function plaza(T, edge, lib) {
    var metal = [], glass = [], lamps = [], solids = [], leaves = [];
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
      tree(T, metal, leaves, tx, tz, rnd(i + 41));
      solids.push([tx, tz, 0.85]);
    }
    var mat = WorldKit.lit(new T.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.08 }), "plazaprops");
    var props = new T.Mesh(merge(T, metal), mat);
    props.frustumCulled = false;
    var gmat = new T.MeshBasicMaterial({ vertexColors: true, color: 0xffffff });
    var lights = new T.Mesh(merge(T, glass), gmat);
    lights.frustumCulled = false;
    var crowns = new T.Mesh(WorldKit.merge(T, leaves), WorldKit.foliage(T, lib));
    crowns.frustumCulled = false;
    return { props: props, glass: lights, leaves: crowns, lamps: lamps, solids: solids };
  }

  /** @param {any} T @param {number} [n] @returns {any} */
  function glows(T, n) {
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
    var mesh = new T.InstancedMesh(new T.PlaneGeometry(2, 2), mat, Math.max(1, n || 8));
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

  return Object.freeze({ sky: sky, plaza: plaza, glows: glows, placeGlows: placeGlows });
})();
