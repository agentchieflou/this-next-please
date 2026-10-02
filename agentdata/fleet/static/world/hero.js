"use strict";

var WorldHero = (function () {
  var SKIN = ["#3b2219", "#5c3a26", "#7b4a2d", "#9c6643", "#b98058", "#d39d74", "#e8bd98", "#f5d9c2"];
  var HAIR = ["#1c1a22", "#3b2a20", "#6b4528", "#a5512b", "#d7b26a", "#c9c6c2", "#3b5bb5"];
  var TOP = ["#c9ccd3", "#2f8f8a", "#d6a23a", "#e07a62", "#34446b", "#f2f2ee", "#4f8a4b", "#7a59b0"];
  var BOTTOM = ["#2e3450", "#1f2124", "#b29a72", "#4a6d9c", "#6b7078"];
  var SCARF = ["#2f8f8a", "#7a2f4f", "#d6a23a", "#34446b", "#e07a62", "#f2f2ee"];
  var STYLES = ["part", "curls", "coils", "long", "bun", "locs", "buzz", "none", "scarf", "wrap"];
  var FACES = ["none", "beard", "moustache"];
  var GLASSES = ["none", "round", "square"];
  var BUILDS = ["slim", "regular", "broad"];
  var MOVES = ["walk", "wheelchair"];
  var OPTIONS = [
    { key: "skin", label: "skin", values: SKIN, swatch: true },
    { key: "hair", label: "hair", values: STYLES },
    { key: "hairColour", label: "hair colour", values: HAIR, swatch: true },
    { key: "scarf", label: "scarf or wrap", values: SCARF, swatch: true },
    { key: "face", label: "face", values: FACES },
    { key: "glasses", label: "glasses", values: GLASSES },
    { key: "top", label: "shirt", values: TOP, swatch: true },
    { key: "bottom", label: "trousers", values: BOTTOM, swatch: true },
    { key: "build", label: "build", values: BUILDS },
    { key: "move", label: "moves by", values: MOVES }
  ];
  var BASE = { skin: SKIN[5], hair: "part", hairColour: HAIR[0], scarf: SCARF[0], face: "none", glasses: "none",
               top: TOP[0], bottom: BOTTOM[0], build: "regular", move: "walk" };
  var PRESETS = [
    { name: "side part", look: {} },
    { name: "curls", look: { skin: SKIN[2], hair: "curls", hairColour: HAIR[0], top: TOP[1], bottom: BOTTOM[1] } },
    { name: "headscarf", look: { skin: SKIN[4], hair: "scarf", scarf: SCARF[1], top: TOP[5], bottom: BOTTOM[3], glasses: "round" } },
    { name: "locs", look: { skin: SKIN[0], hair: "locs", hairColour: HAIR[1], top: TOP[2], bottom: BOTTOM[0], build: "broad" } },
    { name: "silver bun", look: { skin: SKIN[6], hair: "bun", hairColour: HAIR[5], top: TOP[7], bottom: BOTTOM[4], glasses: "square" } },
    { name: "beard", look: { skin: SKIN[3], hair: "buzz", hairColour: HAIR[1], face: "beard", top: TOP[4], bottom: BOTTOM[2] } },
    { name: "wheelchair", look: { skin: SKIN[1], hair: "coils", hairColour: HAIR[0], top: TOP[3], bottom: BOTTOM[1], move: "wheelchair" } },
    { name: "long hair", look: { skin: SKIN[7], hair: "long", hairColour: HAIR[3], top: TOP[6], bottom: BOTTOM[3], build: "slim" } },
    { name: "wrap", look: { skin: SKIN[0], hair: "wrap", scarf: SCARF[2], top: TOP[1], bottom: BOTTOM[0] } },
    { name: "bald", look: { skin: SKIN[5], hair: "none", face: "moustache", top: TOP[4], bottom: BOTTOM[4], build: "broad", glasses: "round" } }
  ];
  var EYE = "#241a16";
  var MOUTH = "#8e2c35";
  var SHOE = "#3a4466";
  var SOLE = "#f4f1ea";
  var CHAIR = "#2b2f36";
  var TYRE = "#15181c";
  var shared = { T: null, mat: null };

  /** @param {any} T @returns {any} */
  function material(T) {
    if (shared.T !== T || !shared.mat) {
      shared.T = T;
      shared.mat = new T.MeshStandardMaterial({ vertexColors: true, roughness: 0.62, metalness: 0 });
    }
    return shared.mat;
  }

  /** @param {Object} look @returns {Object} */
  function normal(look) {
    var out = Object.assign({}, BASE);
    OPTIONS.forEach(function (o) {
      var v = look && look[o.key];
      if (o.values.indexOf(v) >= 0) out[o.key] = v;
    });
    return out;
  }

  /** @param {number} i @returns {Object} */
  function preset(i) {
    var p = PRESETS[((i % PRESETS.length) + PRESETS.length) % PRESETS.length];
    return normal(Object.assign({}, BASE, p.look));
  }

  /** @param {any} T @param {any} geo @param {string} hex @param {Array<number>} at @param {Array<number>} [scale] @param {Array<number>} [turn] @returns {any} */
  function piece(T, geo, hex, at, scale, turn) {
    var g = geo.index ? geo.toNonIndexed() : geo;
    var s = scale || [1, 1, 1], r = turn || [0, 0, 0];
    var m = new T.Matrix4().compose(new T.Vector3(at[0], at[1], at[2]),
                                    new T.Quaternion().setFromEuler(new T.Euler(r[0], r[1], r[2])),
                                    new T.Vector3(s[0], s[1], s[2]));
    g.applyMatrix4(m);
    var c = new T.Color(hex), n = g.attributes.position.count, col = new Float32Array(n * 3);
    for (var i = 0; i < n; i++) { col[i * 3] = c.r; col[i * 3 + 1] = c.g; col[i * 3 + 2] = c.b; }
    g.setAttribute("color", new T.BufferAttribute(col, 3));
    return g;
  }

  /** @param {any} T @param {Array<any>} list @param {any} mat @returns {any} */
  function mesh(T, list, mat) {
    var total = 0;
    list.forEach(function (g) { total += g.attributes.position.count; });
    var pos = new Float32Array(total * 3), nor = new Float32Array(total * 3), col = new Float32Array(total * 3), at = 0;
    list.forEach(function (g) {
      pos.set(g.attributes.position.array, at * 3);
      nor.set(g.attributes.normal.array, at * 3);
      col.set(g.attributes.color.array, at * 3);
      at += g.attributes.position.count;
      g.dispose();
    });
    var out = new T.BufferGeometry();
    out.setAttribute("position", new T.BufferAttribute(pos, 3));
    out.setAttribute("normal", new T.BufferAttribute(nor, 3));
    out.setAttribute("color", new T.BufferAttribute(col, 3));
    out.computeBoundingSphere();
    var m = new T.Mesh(out, mat);
    m.frustumCulled = false;
    return m;
  }

  /** @param {any} T @param {Object} L @param {Array<any>} out */
  function hair(T, L, out) {
    var h = L.hairColour, sc = L.scarf;
    var cap = function (k) { out.push(piece(T, new T.SphereGeometry(0.222, 18, 12), h, [0, 0.225, 0.055], [0.99, k || 0.72, 1])); };
    if (L.hair === "part") {
      cap();
      out.push(piece(T, new T.CapsuleGeometry(0.07, 0.2, 4, 10), h, [0.03, 0.31, -0.1], [1, 0.8, 1], [0, 0.3, Math.PI / 2]));
      out.push(piece(T, new T.SphereGeometry(0.09, 10, 8), h, [-0.1, 0.3, -0.07]));
    } else if (L.hair === "curls" || L.hair === "coils") {
      var big = L.hair === "coils" ? 0.3 : 0.26;
      out.push(piece(T, new T.SphereGeometry(big, 18, 12), h, [0, 0.27, 0.1], [1.05, 0.85, 1]));
      for (var i = 0; i < 8; i++) {
        var a = i / 8 * Math.PI * 2;
        out.push(piece(T, new T.SphereGeometry(big * 0.36, 8, 6), h,
                       [Math.cos(a) * big * 0.8, 0.33 + (i % 2) * 0.05, 0.1 + Math.sin(a) * big * 0.75]));
      }
    } else if (L.hair === "long") {
      cap();
      out.push(piece(T, new T.CapsuleGeometry(0.12, 0.28, 4, 12), h, [0, -0.04, 0.12], [1.6, 1, 0.6]));
      [-1, 1].forEach(function (s) {
        out.push(piece(T, new T.CapsuleGeometry(0.05, 0.26, 4, 8), h, [s * 0.19, 0.02, 0.0]));
      });
    } else if (L.hair === "bun") {
      cap(0.7);
      out.push(piece(T, new T.SphereGeometry(0.1, 12, 10), h, [0, 0.38, 0.13]));
    } else if (L.hair === "locs") {
      cap();
      for (var j = 0; j < 11; j++) {
        var b = Math.PI * (0.28 + j / 10 * 1.44);
        out.push(piece(T, new T.CapsuleGeometry(0.03, 0.3, 3, 6), h,
                       [Math.cos(b) * 0.2, -0.02, Math.sin(b) * 0.2 + 0.03], [1, 1, 1], [Math.sin(b) * 0.2, 0, -Math.cos(b) * 0.2]));
      }
    } else if (L.hair === "buzz") {
      out.push(piece(T, new T.SphereGeometry(0.216, 18, 12), h, [0, 0.2, 0.06], [1, 0.7, 1]));
    } else if (L.hair === "scarf") {
      out.push(piece(T, new T.SphereGeometry(0.245, 18, 14), sc, [0, 0.19, 0.08], [1.04, 0.92, 1.04]));
      out.push(piece(T, new T.CylinderGeometry(0.15, 0.24, 0.2, 18, 1), sc, [0, -0.08, 0.03]));
    } else if (L.hair === "wrap") {
      out.push(piece(T, new T.SphereGeometry(0.235, 18, 12), sc, [0, 0.24, 0.06], [1.05, 0.8, 1.04]));
      out.push(piece(T, new T.SphereGeometry(0.16, 14, 10), sc, [0, 0.42, 0.06], [1.2, 0.8, 1.05]));
      out.push(piece(T, new T.TorusGeometry(0.2, 0.04, 8, 20), sc, [0, 0.3, 0.06], [1.05, 1, 1], [Math.PI / 2, 0, 0]));
    }
  }

  /** @param {any} T @param {Object} L @param {Array<any>} out */
  function face(T, L, out) {
    var dark = L.hair === "none" || L.hair === "scarf" || L.hair === "wrap" ? "#3b2a20" : L.hairColour;
    [-1, 1].forEach(function (s) {
      out.push(piece(T, new T.SphereGeometry(0.03, 10, 8), EYE, [s * 0.075, 0.17, -0.183]));
      out.push(piece(T, new T.CapsuleGeometry(0.012, 0.05, 3, 6), dark, [s * 0.075, 0.24, -0.186], [1, 1, 1], [0, 0, Math.PI / 2 + s * 0.12]));
    });
    out.push(piece(T, new T.SphereGeometry(1, 14, 10), MOUTH, [0, 0.04, -0.19], [0.062, 0.03, 0.02]));
    out.push(piece(T, new T.SphereGeometry(1, 12, 8), "#ffffff", [0, 0.053, -0.2], [0.046, 0.012, 0.012]));
    if (L.face === "beard") {
      out.push(piece(T, new T.SphereGeometry(0.17, 16, 12), L.hairColour, [0, -0.04, -0.06], [1.05, 0.85, 0.9]));
      out.push(piece(T, new T.CapsuleGeometry(0.016, 0.07, 3, 6), L.hairColour, [0, 0.078, -0.2], [1, 1, 1], [0, 0, Math.PI / 2]));
    } else if (L.face === "moustache") {
      out.push(piece(T, new T.CapsuleGeometry(0.018, 0.08, 3, 6), L.hairColour, [0, 0.078, -0.2], [1, 1, 1], [0, 0, Math.PI / 2]));
    }
    if (L.glasses !== "none") {
      var seg = L.glasses === "square" ? 4 : 18, spin = L.glasses === "square" ? Math.PI / 4 : 0;
      [-1, 1].forEach(function (s) {
        out.push(piece(T, new T.TorusGeometry(0.047, 0.008, 6, seg), "#202226", [s * 0.077, 0.17, -0.205], [1, 1, 1], [0, 0, spin]));
      });
      out.push(piece(T, new T.CapsuleGeometry(0.006, 0.04, 2, 4), "#202226", [0, 0.18, -0.21], [1, 1, 1], [0, 0, Math.PI / 2]));
    }
  }

  /** @param {any} T @param {Object} look @returns {Object} */
  function build(T, look) {
    var L = normal(look);
    var bw = L.build === "slim" ? 0.86 : L.build === "broad" ? 1.2 : 1;
    var mat = material(T);
    var root = new T.Group(), hips = new T.Group(), head = new T.Group();
    hips.position.set(0, 0.86, 0);
    root.add(hips);
    hips.add(mesh(T, [
      piece(T, new T.CapsuleGeometry(0.2, 0.22, 6, 18), L.top, [0, 0.3, 0], [bw, 1, 0.78 * (0.85 + bw * 0.15)]),
      piece(T, new T.CylinderGeometry(0.17, 0.16, 0.1, 18), L.bottom, [0, 0.02, 0], [bw, 1, 0.78 * (0.85 + bw * 0.15)]),
      piece(T, new T.BoxGeometry(0.1, 0.05, 0.02), L.top, [-0.05, 0.6, -0.14], [1, 1, 1], [0.5, 0, 0.35]),
      piece(T, new T.BoxGeometry(0.1, 0.05, 0.02), L.top, [0.05, 0.6, -0.14], [1, 1, 1], [0.5, 0, -0.35]),
      piece(T, new T.SphereGeometry(0.012, 6, 4), "#2a3040", [0, 0.16, -0.165 * (0.85 + bw * 0.15)]),
      piece(T, new T.SphereGeometry(0.012, 6, 4), "#2a3040", [0, 0.29, -0.168 * (0.85 + bw * 0.15)]),
      piece(T, new T.SphereGeometry(0.012, 6, 4), "#2a3040", [0, 0.42, -0.165 * (0.85 + bw * 0.15)]),
      piece(T, new T.CylinderGeometry(0.065, 0.07, 0.14, 12), L.skin, [0, 0.64, 0])
    ], mat));
    head.position.set(0, 0.7, 0);
    hips.add(head);
    var hp = [
      piece(T, new T.SphereGeometry(0.21, 24, 18), L.skin, [0, 0.14, 0], [1, 1.04, 0.96]),
      piece(T, new T.SphereGeometry(0.055, 10, 8), L.skin, [-0.205, 0.12, 0.01], [0.6, 1, 0.8]),
      piece(T, new T.SphereGeometry(0.055, 10, 8), L.skin, [0.205, 0.12, 0.01], [0.6, 1, 0.8]),
      piece(T, new T.SphereGeometry(0.03, 10, 8), L.skin, [0, 0.1, -0.2])
    ];
    face(T, L, hp);
    hair(T, L, hp);
    head.add(mesh(T, hp, mat));
    var limbs = {};
    [-1, 1].forEach(function (s) {
      var side = s < 0 ? "L" : "R";
      var arm = new T.Group(), fore = new T.Group(), leg = new T.Group(), shin = new T.Group();
      arm.position.set(s * 0.25 * bw, 0.52, 0);
      arm.add(mesh(T, [piece(T, new T.CapsuleGeometry(0.068 * (0.8 + bw * 0.2), 0.17, 4, 12), L.top, [0, -0.12, 0])], mat));
      fore.position.set(0, -0.26, 0);
      fore.add(mesh(T, [
        piece(T, new T.CapsuleGeometry(0.062 * (0.8 + bw * 0.2), 0.12, 4, 12), L.top, [0, -0.08, 0]),
        piece(T, new T.SphereGeometry(0.065, 12, 10), L.skin, [0, -0.22, -0.01], [0.85, 1, 0.62]),
        piece(T, new T.SphereGeometry(0.025, 8, 6), L.skin, [-s * 0.045, -0.19, -0.03])
      ], mat));
      arm.add(fore);
      hips.add(arm);
      leg.position.set(s * 0.1 * bw, 0, 0);
      leg.add(mesh(T, [piece(T, new T.CapsuleGeometry(0.09 * (0.8 + bw * 0.2), 0.2, 4, 12), L.bottom, [0, -0.19, 0])], mat));
      shin.position.set(0, -0.4, 0);
      shin.add(mesh(T, [
        piece(T, new T.CapsuleGeometry(0.08 * (0.8 + bw * 0.2), 0.2, 4, 12), L.bottom, [0, -0.17, 0]),
        piece(T, new T.SphereGeometry(1, 14, 10), SHOE, [0, -0.375, -0.045], [0.068, 0.055, 0.135]),
        piece(T, new T.BoxGeometry(0.13, 0.03, 0.27), SOLE, [0, -0.42, -0.045]),
        piece(T, new T.BoxGeometry(0.07, 0.012, 0.05), SOLE, [0, -0.33, -0.1])
      ], mat));
      leg.add(shin);
      hips.add(leg);
      limbs["arm" + side] = arm;
      limbs["fore" + side] = fore;
      limbs["leg" + side] = leg;
      limbs["shin" + side] = shin;
    });
    var chair = null, wheels = null;
    if (L.move === "wheelchair") {
      chair = mesh(T, [
        piece(T, new T.BoxGeometry(0.48, 0.06, 0.46), "#3a3f47", [0, 0.5, 0]),
        piece(T, new T.BoxGeometry(0.46, 0.44, 0.05), "#3a3f47", [0, 0.78, 0.23]),
        piece(T, new T.CylinderGeometry(0.018, 0.018, 0.5, 6), CHAIR, [-0.24, 0.52, 0.12], [1, 1, 1], [0.2, 0, 0]),
        piece(T, new T.CylinderGeometry(0.018, 0.018, 0.5, 6), CHAIR, [0.24, 0.52, 0.12], [1, 1, 1], [0.2, 0, 0]),
        piece(T, new T.BoxGeometry(0.36, 0.03, 0.14), CHAIR, [0, 0.1, -0.32]),
        piece(T, new T.CylinderGeometry(0.015, 0.015, 0.42, 6), CHAIR, [-0.17, 0.3, -0.26], [1, 1, 1], [0.35, 0, 0]),
        piece(T, new T.CylinderGeometry(0.015, 0.015, 0.42, 6), CHAIR, [0.17, 0.3, -0.26], [1, 1, 1], [0.35, 0, 0]),
        piece(T, new T.SphereGeometry(0.05, 8, 6), TYRE, [-0.2, 0.05, -0.3]),
        piece(T, new T.SphereGeometry(0.05, 8, 6), TYRE, [0.2, 0.05, -0.3])
      ], mat);
      root.add(chair);
      wheels = new T.Group();
      wheels.position.set(0, 0.3, 0.05);
      wheels.add(mesh(T, [
        piece(T, new T.TorusGeometry(0.29, 0.028, 8, 28), TYRE, [-0.29, 0, 0], [1, 1, 1], [0, Math.PI / 2, 0]),
        piece(T, new T.TorusGeometry(0.29, 0.028, 8, 28), TYRE, [0.29, 0, 0], [1, 1, 1], [0, Math.PI / 2, 0]),
        piece(T, new T.TorusGeometry(0.25, 0.008, 4, 24), "#9aa3ad", [-0.32, 0, 0], [1, 1, 1], [0, Math.PI / 2, 0]),
        piece(T, new T.TorusGeometry(0.25, 0.008, 4, 24), "#9aa3ad", [0.32, 0, 0], [1, 1, 1], [0, Math.PI / 2, 0]),
        piece(T, new T.BoxGeometry(0.01, 0.5, 0.02), "#9aa3ad", [-0.29, 0, 0]),
        piece(T, new T.BoxGeometry(0.01, 0.02, 0.5), "#9aa3ad", [-0.29, 0, 0]),
        piece(T, new T.BoxGeometry(0.01, 0.5, 0.02), "#9aa3ad", [0.29, 0, 0]),
        piece(T, new T.BoxGeometry(0.01, 0.02, 0.5), "#9aa3ad", [0.29, 0, 0])
      ], mat));
      root.add(wheels);
    }
    return { group: root, hips: hips, head: head, limbs: limbs, chair: chair, wheels: wheels, look: L, mat: mat,
             seated: L.move === "wheelchair" };
  }

  /** @param {number} a @param {number} b @param {number} t @returns {number} */
  function mix(a, b, t) { return a + (b - a) * t; }

  /** @param {Object} h @param {{phase: number, speed: number, talk: number, t: number, reduced: boolean, rolled: number}} s */
  function pose(h, s) {
    var b = h.limbs, sw = Math.sin(s.phase), k = Math.min(1, s.speed), tk = s.talk;
    var breathe = s.reduced ? 0 : Math.sin(s.t * 1.7) * 0.006;
    if (h.seated) {
      h.hips.position.y = 0.55 + breathe;
      b.legL.rotation.set(1.45, 0, 0.04);
      b.legR.rotation.set(1.45, 0, -0.04);
      b.shinL.rotation.set(-1.45, 0, 0);
      b.shinR.rotation.set(-1.45, 0, 0);
      var push = 0.35 + sw * 0.3 * k;
      b.armL.rotation.set(mix(push, 0.5, tk), 0, mix(-0.28, -0.1, tk));
      b.armR.rotation.set(mix(push, 0.3, tk), 0, mix(0.28, 1.1, tk));
      b.foreL.rotation.set(mix(0.5, 1.2, tk), 0, 0);
      b.foreR.rotation.set(mix(0.5, 0.1, tk), 0, mix(0, 0.35, tk));
      if (h.wheels) h.wheels.rotation.x = -s.rolled / 0.31;
    } else {
      h.hips.position.y = 0.86 + Math.abs(sw) * 0.035 * k + breathe;
      b.legL.rotation.set(sw * 0.55 * k, 0, 0.02);
      b.legR.rotation.set(-sw * 0.55 * k, 0, -0.02);
      b.shinL.rotation.set(-Math.max(0, -sw) * 0.75 * k, 0, 0);
      b.shinR.rotation.set(-Math.max(0, sw) * 0.75 * k, 0, 0);
      b.armL.rotation.set(mix(-sw * 0.5 * k, 0.5, tk), 0, mix(-0.1, -0.1, tk));
      b.armR.rotation.set(mix(sw * 0.5 * k, 0.3, tk), 0, mix(0.1, 1.1, tk));
      b.foreL.rotation.set(mix(0.15 + 0.2 * k, 1.25, tk), 0, 0);
      b.foreR.rotation.set(mix(0.15 + 0.2 * k, 0.1, tk), 0, mix(0, 0.35, tk));
    }
    h.head.rotation.set(0, 0, tk * 0.08);
  }

  /** @param {Object} h */
  function dispose(h) {
    if (!h) return;
    h.group.traverse(function (o) { if (o.geometry) o.geometry.dispose(); });
    if (h.group.parent) h.group.parent.remove(h.group);
  }

  return Object.freeze({ OPTIONS: OPTIONS, PRESETS: PRESETS, normal: normal, preset: preset, build: build, pose: pose,
                         dispose: dispose });
})();
