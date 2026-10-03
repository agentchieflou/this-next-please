"use strict";

var WorldAssets = (function () {
  var DIR = "/static/world/cc0/";
  var TEX = {
    brick: ["brick_wall_001", 3, 3, 1], stucco: ["painted_plaster_wall", 2, 2, 1], concrete: ["concrete_slab_wall", 2.3, 2.3, 1],
    asphalt: ["asphalt_02", 3, 3, 0.6], sidewalk: ["concrete_pavement", 1.8, 1.8, 0.78]
  };
  var SKY = { day: ["potsdamer_platz", 1.15], night: ["hansaplatz", 0.05] };
  var PROPS = ["fire_hydrant", "metal_trash_can", "trashbag", "cardboard_box_01", "utility_box_01", "utility_box_02",
               "exterior_aircon_unit", "concrete_road_barrier", "covered_car"];

  /** @param {string} name @returns {Promise<any>} */
  function image(name) {
    var img = new Image();
    img.decoding = "async";
    img.src = q(DIR + name);
    return img.decode().then(function () { return img; }, function () { return null; });
  }

  /** @param {string} name @returns {Promise<{w: number, h: number, data: Uint8Array}|null>} */
  function rgbe(name) {
    return fetch(q(DIR + name)).then(function (r) { return r.ok ? r.arrayBuffer() : null; }).then(function (buf) {
      if (!buf) return null;
      var b = new Uint8Array(buf), at = 0, line = "", m = null;
      while (at < b.length && at < 1024 && !m) {
        var c = b[at++];
        if (c !== 10) { line += String.fromCharCode(c); continue; }
        m = /^-Y (\d+) \+X (\d+)$/.exec(line);
        line = "";
      }
      if (!m) return null;
      var h = +m[1], w = +m[2];
      return b.length - at === w * h * 4 ? { w: w, h: h, data: b.subarray(at) } : null;
    }).catch(function () { return null; });
  }

  /** @param {string} name @returns {Promise<Array<Object>|null>} */
  function glb(name) {
    return fetch(q(DIR + name)).then(function (r) { return r.ok ? r.arrayBuffer() : null; }).then(function (buf) {
      if (!buf) return null;
      var dv = new DataView(buf);
      if (dv.getUint32(0, true) !== 0x46546C67) return null;
      var jl = dv.getUint32(12, true), json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jl))), bin = 28 + jl;
      var span = function (/** @type {number} */ i) { var v = json.bufferViews[i]; return [bin + (v.byteOffset || 0), v.byteLength]; };
      var read = function (/** @type {number} */ i) {
        var a = json.accessors[i], at = span(a.bufferView), n = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 }[a.type];
        var K = { 5126: Float32Array, 5125: Uint32Array, 5123: Uint16Array, 5121: Uint8Array }[a.componentType];
        var start = at[0] + (a.byteOffset || 0), step = json.bufferViews[a.bufferView].byteStride || n * K.BYTES_PER_ELEMENT;
        if (step === n * K.BYTES_PER_ELEMENT) return { a: new K(buf, start, a.count * n), n: n };
        var out = new K(a.count * n);
        for (var j = 0; j < a.count; j++) out.set(new K(buf, start + j * step, n), j * n);
        return { a: out, n: n };
      };
      var pic = function (/** @type {Object} */ info) {
        var t = json.textures[info.index], src = t.source !== undefined ? t.source : t.extensions.EXT_texture_webp.source;
        var im = json.images[src], at = span(im.bufferView);
        return createImageBitmap(new Blob([new Uint8Array(buf, at[0], at[1])], { type: im.mimeType }),
          { premultiplyAlpha: "none", colorSpaceConversion: "none" });
      };
      var parts = [];
      json.meshes.forEach(function (/** @type {Object} */ m) {
        m.primitives.forEach(function (/** @type {Object} */ p) {
          var mt = json.materials[p.material], pbr = mt.pbrMetallicRoughness;
          parts.push(Promise.all([pic(pbr.baseColorTexture), pic(mt.normalTexture), pic(pbr.metallicRoughnessTexture)]).then(function (im) {
            return { pos: read(p.attributes.POSITION), nor: read(p.attributes.NORMAL), uv: read(p.attributes.TEXCOORD_0), idx: read(p.indices),
                     map: im[0], normal: im[1], orm: im[2] };
          }));
        });
      });
      return Promise.all(parts);
    }).catch(function () { return null; });
  }

  /** @returns {Promise<{tex: Object<string, Object>, sky: Object<string, Object>, props: Object<string, Array<Object>>}>} */
  function load() {
    var out = { tex: {}, sky: {}, props: {} }, jobs = [];
    Object.keys(TEX).forEach(function (k) {
      var id = TEX[k][0];
      jobs.push(Promise.all([image(id + "_diff.webp"), image(id + "_arm.webp"), image(id + "_nor.webp")]).then(function (im) {
        if (im[0] && im[1] && im[2]) out.tex[k] = { map: im[0], orm: im[1], normal: im[2], size: [TEX[k][1], TEX[k][2]], gain: TEX[k][3] };
      }));
    });
    PROPS.forEach(function (id) { jobs.push(glb(id + ".glb").then(function (parts) { if (parts) out.props[id] = parts; })); });
    Object.keys(SKY).forEach(function (k) {
      jobs.push(rgbe(SKY[k][0] + ".hdr").then(function (s) { if (s) out.sky[k] = Object.assign(s, { k: SKY[k][1] }); }));
    });
    return Promise.all(jobs).then(function () { return out; });
  }

  /** @param {any} T @param {any} img @param {boolean} srgb @param {Array<number>} size @param {number} aniso @returns {any} */
  function texture(T, img, srgb, size, aniso) {
    var t = new T.Texture(img);
    t.wrapS = t.wrapT = T.RepeatWrapping;
    t.anisotropy = aniso;
    t.colorSpace = srgb ? T.SRGBColorSpace : T.NoColorSpace;
    t.repeat.set(1 / size[0], 1 / size[1]);
    t.needsUpdate = true;
    return t;
  }

  /** @param {any} T @param {Object} s @returns {any} */
  function data(T, s) {
    var t = new T.DataTexture(s.data, s.w, s.h, T.RGBAFormat, T.UnsignedByteType);
    t.minFilter = t.magFilter = T.NearestFilter;
    t.wrapS = T.RepeatWrapping;
    t.generateMipmaps = false;
    t.needsUpdate = true;
    return t;
  }

  /** @param {any} T @param {Object<string, Object>} sky @returns {any} */
  function dome(T, sky) {
    if (!sky.day || !sky.night) return null;
    var mat = new T.ShaderMaterial({
      uniforms: {
        uDay: { value: data(T, sky.day) }, uNight: { value: data(T, sky.night) }, uSize: { value: new T.Vector2(sky.day.w, sky.day.h) },
        uMix: { value: 0 }, uDayK: { value: sky.day.k }, uNightK: { value: sky.night.k }, uTint: { value: new T.Color(1, 1, 1) }
      },
      vertexShader: "varying vec3 vDir; void main() { vDir = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: [
        "uniform sampler2D uDay; uniform sampler2D uNight; uniform vec2 uSize; uniform float uMix; uniform float uDayK; uniform float uNightK;",
        "uniform vec3 uTint; varying vec3 vDir;",
        "vec3 px(sampler2D t, vec2 i) { vec4 c = floor(texture2D(t, (vec2(mod(i.x, uSize.x), clamp(i.y, 0.0, uSize.y - 1.0)) + 0.5) / uSize) * 255.0 + 0.5);",
        "  return c.a > 0.0 ? (c.rgb + 0.5) * exp2(c.a - 136.0) : vec3(0.0); }",
        "vec3 tap(sampler2D t, vec2 uv) { vec2 p = uv * uSize - 0.5; vec2 i = floor(p); vec2 f = p - i;",
        "  return mix(mix(px(t, i), px(t, i + vec2(1.0, 0.0)), f.x), mix(px(t, i + vec2(0.0, 1.0)), px(t, i + vec2(1.0, 1.0)), f.x), f.y); }",
        "void main() { vec3 d = normalize(vDir);",
        "  vec2 uv = vec2(atan(d.z, d.x) / 6.2831853 + 0.5, 0.5 - asin(clamp(d.y, -1.0, 1.0)) / 3.1415927);",
        "  vec3 c = uMix < 0.999 ? tap(uDay, uv) * uDayK : vec3(0.0); vec3 n = uMix > 0.001 ? tap(uNight, uv) * uNightK : vec3(0.0);",
        "  gl_FragColor = vec4(min(mix(c, n, uMix) * uTint, vec3(40.0)), 1.0); }"
      ].join("\n"),
      side: T.BackSide, depthWrite: false, depthTest: false
    });
    var mesh = new T.Mesh(new T.SphereGeometry(50, 48, 24), mat);
    mesh.frustumCulled = false;
    return mesh;
  }

  /** @param {any} T @param {any} img @param {boolean} srgb @param {number} aniso @returns {any} */
  function bitmap(T, img, srgb, aniso) {
    var t = new T.Texture(img);
    t.flipY = false;
    t.anisotropy = aniso;
    t.colorSpace = srgb ? T.SRGBColorSpace : T.NoColorSpace;
    t.needsUpdate = true;
    return t;
  }

  /** @param {any} T @param {Object<string, Array<Object>>} props @param {number} aniso @returns {Object<string, Array<{geo: any, mat: any}>>} */
  function scans(T, props, aniso) {
    var out = {};
    Object.keys(props).forEach(function (id) {
      out[id] = props[id].map(function (/** @type {Object} */ p) {
        var g = new T.BufferGeometry();
        g.setAttribute("position", new T.BufferAttribute(p.pos.a, 3));
        g.setAttribute("normal", new T.BufferAttribute(p.nor.a, 3));
        g.setAttribute("uv", new T.BufferAttribute(p.uv.a, 2));
        g.setIndex(new T.BufferAttribute(p.idx.a, 1));
        g.computeBoundingSphere();
        var orm = bitmap(T, p.orm, false, aniso);
        var mat = new T.MeshStandardMaterial({
          map: bitmap(T, p.map, true, aniso), normalMap: bitmap(T, p.normal, false, aniso), roughnessMap: orm, metalnessMap: orm,
          roughness: 1, metalness: 1
        });
        return { geo: g, mat: WorldKit.lit(mat, "scan", { porous: 0.5 }) };
      });
    });
    return out;
  }

  return Object.freeze({ DIR: DIR, TEX: TEX, SKY: SKY, PROPS: PROPS, load: load, texture: texture, dome: dome, scans: scans });
})();
