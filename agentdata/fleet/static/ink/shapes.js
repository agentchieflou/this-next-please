const RAIL_BELOW = 90;

export function rng(seed) {
  let a = (seed >>> 0) || 1;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function box(b) {
  return { x: b.x, y: b.y, w: b.w, h: b.h, r: b.x + b.w, b: b.y + b.h };
}

function union(list) {
  const bs = list.filter(Boolean);
  if (!bs.length) return null;
  const x = Math.min(...bs.map(b => b.x)), y = Math.min(...bs.map(b => b.y));
  const r = Math.max(...bs.map(b => b.r)), bt = Math.max(...bs.map(b => b.b));
  return { x, y, r, b: bt, w: r - x, h: bt - y };
}

function loopPath(r, o, rad, over) {
  const L = r.x - o, T = r.y - o, R = r.r + o, B = r.b + o;
  rad = Math.max(1, Math.min(rad, (R - L) / 3, (B - T) / 3));
  const pts = [[L + rad + 4, T]];
  const arc = (cx, cy, a0) => {
    for (let i = 1; i <= 4; i++) {
      const a = a0 + i / 4 * Math.PI / 2;
      pts.push([cx + Math.cos(a) * rad, cy + Math.sin(a) * rad]);
    }
  };
  pts.push([R - rad, T]); arc(R - rad, T + rad, -Math.PI / 2);
  pts.push([R, B - rad]); arc(R - rad, B - rad, 0);
  pts.push([L + rad, B]); arc(L + rad, B - rad, Math.PI / 2);
  pts.push([L, T + rad]); arc(L + rad, T + rad, Math.PI);
  pts.push([L + rad + 4 + over, T + 1.6]);
  return { pts };
}

function margin(r) {
  const rail = r.w < RAIL_BELOW;
  return { x: rail ? r.x + r.w / 2 : r.x + 14, top: r.y + (rail ? 16 : 14), rail };
}

export const SHAPES = {
  outline(m) {
    const r = box(m.box), rnd = rng(m.seed), o = m.pad || 0;
    const j = () => (rnd() - 0.5) * 2.4, ov = () => 3 + rnd() * 6;
    const L = r.x - o, T = r.y - o, R = r.r + o, B = r.b + o;
    return [{ pts: [[L - ov(), T + j()], [R + ov(), T + j()]] },
            { pts: [[R + j(), T - ov()], [R + j(), B + ov()]] },
            { pts: [[R + ov(), B + j()], [L - ov(), B + j()]] },
            { pts: [[L + j(), B + ov()], [L + j(), T - ov()]] }];
  },
  divider(m) {
    const r = box(m.box), y = r.b - 1 + (m.pad || 0);
    if (r.w < 24) return [];
    return [{ pts: [[r.x + 10, y], [r.r - 10, y + 0.8]] }];
  },
  underline(m) {
    const r = box(m.box);
    let y = Math.max(r.b, m.base || 0) + 2 + (m.pad || 0);
    if (m.floor !== undefined) y = Math.min(y, m.floor - 3.4);
    let x1 = r.r + 8 + (m.grow || 0);
    if (Number.isFinite(m.limit)) x1 = Math.max(r.r + 8, Math.min(x1, m.limit));
    const out = [{ pts: [[r.x - 3, y], [x1, y + 1.2]], nobow: true }];
    if (m.tip) out.push({ pts: [[x1 + 2.2, y + 0.8], [x1 + 3.4, y + 1.4]], w: 4.4, nobow: true, wob: 0 });
    if (m.cap === "arrow") out.push({ pts: [[x1 - 7, y - 4.8], [x1, y + 1.2], [x1 - 7, y + 6.4]], nobow: true });
    if (m.cap === "bar") out.push({ pts: [[x1, y - 5], [x1 + 0.4, y + 6]], nobow: true });
    return out;
  },
  lines(m) {
    const ls = (m.lines && m.lines.length) ? m.lines : [box(m.box)];
    return ls.map(l => {
      const cy = l.y + l.h / 2;
      return { pts: [[l.x - 5, cy + 0.8], [l.x + l.w + 6, cy - 0.6]],
               w: Math.max(12, Math.min(26, l.h * 1.05)) };
    });
  },
  loop(m) {
    return [loopPath(box(m.box), 3 + (m.pad || 0), 7, 12)];
  },
  ellipse(m) {
    const r = box(m.box), rnd = rng(m.seed), pad = m.pad || 0;
    const cx = (r.x + r.r) / 2, cy = (r.y + r.b) / 2, rx = r.w / 2 + 12 + pad, ry = r.h / 2 + 7 + pad;
    const a0 = Math.PI * (0.92 + rnd() * 0.16), rot = (rnd() - 0.5) * 0.06, pts = [];
    for (let i = 0; i <= 72; i++) {
      const t = i / 72, a = a0 + t * 2.16 * Math.PI, k = 0.97 + 0.07 * t;
      const x = Math.cos(a) * rx * k, y = Math.sin(a) * ry * k;
      pts.push([cx + x * Math.cos(rot) - y * Math.sin(rot), cy + x * Math.sin(rot) + y * Math.cos(rot)]);
    }
    return [{ pts, nobow: true, wob: 0.8 }];
  },
  ring(m) {
    const r = box(m.box), rnd = rng(m.seed), R = Math.max(r.w, r.h) / 2 + 3 + (m.pad || 0);
    const cx = (r.x + r.r) / 2, cy = (r.y + r.b) / 2, a0 = rnd() * 2 * Math.PI, pts = [];
    for (let i = 0; i <= 48; i++) {
      const a = a0 + i / 48 * 2.2 * Math.PI, k = 1 + 0.05 * i / 48;
      pts.push([cx + Math.cos(a) * R * k, cy + Math.sin(a) * R * k]);
    }
    return [{ pts, nobow: true, wob: 0.5 }];
  },
  strike(m) {
    return strikeBox(box(m.box), rng(m.seed));
  },
  check(m) {
    const g = margin(box(m.box));
    return [{ pts: [[g.x - 9, g.top + 12], [g.x - 3.5, g.top + 19], [g.x + 10, g.top + 1]],
              smooth: true, nobow: true }];
  },
  bang(m) {
    const g = margin(box(m.box)), y0 = g.top - 2, h = 22;
    return [{ pts: [[g.x - 0.5, y0], [g.x + 0.6, y0 + h]], wob: 0.3, nobow: true },
            { pts: [[g.x + 0.4, y0 + h + 7], [g.x + 0.9, y0 + h + 8.8]], nobow: true }];
  },
  cross(m) {
    const g = margin(box(m.box)), y = g.top + 10;
    return [{ pts: [[g.x - 7, y - 7], [g.x + 7, y + 7]], nobow: true },
            { pts: [[g.x + 7, y - 7], [g.x - 7, y + 7]], nobow: true }];
  },
  arrow(m) {
    if (!m.to) return [];
    const n = box(m.box), v = box(m.to);
    const x0 = n.x - 5, y0 = n.y + n.h * 0.5;
    const x1 = Math.abs(v.x + v.w / 2 - x0) < 12 ? v.x + v.w / 2 : Math.min(Math.max(v.x + 8, x0 - 24), v.r - 4);
    const y1 = v.y > y0 ? v.y - 3 : v.b + 3;
    const mx = (x0 + x1) / 2 - 5, my = (y0 + y1) / 2 + 3, ang = Math.atan2(y1 - my, x1 - mx), bl = 7;
    const b1 = [x1 + Math.cos(ang + Math.PI - 0.5) * bl, y1 + Math.sin(ang + Math.PI - 0.5) * bl];
    const b2 = [x1 + Math.cos(ang + Math.PI + 0.5) * bl, y1 + Math.sin(ang + Math.PI + 0.5) * bl];
    return [{ pts: [[x0, y0], [mx, my], [x1, y1]], smooth: true, nobow: true },
            { pts: [b1, [x1, y1]], nobow: true }, { pts: [[x1, y1], b2], nobow: true }];
  },
  write() {
    return [];
  },
};

export const SHAPE_NAMES = Object.keys(SHAPES);

export const PAGE_SHAPES = {
  series(m) {
    const v = m.values || [];
    if (v.length < 2 || !v.some(x => x > 0)) return [];
    const r = box(m.box), slot = r.w / v.length, floor = r.b - 1.5, span = Math.max(1, r.h - 3);
    const pts = v.map((x, i) => [r.x + (i + 0.5) * slot, floor - (x > 0 ? Math.max(1, x * span) : 0)]);
    return [{ pts, nobow: true, wob: 0.15, w: 1.2 }];
  },
  ticks(m) {
    const n = (m.values || []).length;
    if (!n) return [];
    const r = box(m.box), slot = r.w / n;
    return (m.ticks || []).filter(i => i >= 0 && i < n).map(i => {
      const x = r.x + (i + 0.5) * slot;
      return { pts: [[x, r.b], [x, r.y]], nobow: true, wob: 0.2 };
    });
  },
};

export function snap(paths, shape, b, at, g, o = {}) {
  const near = v => Math.round(v / g) * g;
  const L = b.x + at.x, T = b.y + at.y, R = L + b.w, B = T + b.h, w = o.band || [0, 0, 0, 0];
  const edge = (e, d) => (Math.abs(d) < g ? e + d / 2 : near(e + d / 2));
  const sL = edge(L, w[0]), sT = edge(T, w[1]), sR = edge(R, -w[2]), sB = edge(B, -w[3]);
  const inX = x => Math.min(R, Math.max(L, x + (Math.abs(x - L) <= Math.abs(x - R) ? sL - L : sR - R)));
  const inY = y => Math.min(B, Math.max(T, y + (Math.abs(y - T) <= Math.abs(y - B) ? sT - T : sB - B)));
  const u = Math.ceil((at.y + (o.base ?? b.y + b.h) + 2) / g) * g;
  if (shape === "underline" && o.floor !== undefined && u > at.y + o.floor - 2) return paths;
  return paths.map(p => {
    const pts = p.pts.map(q => [q[0] + at.x, q[1] + at.y]);
    const a = pts[0], z = pts[pts.length - 1];
    const flat = Math.abs(z[0] - a[0]) >= Math.abs(z[1] - a[1]);
    const mid = pts.reduce((s, q) => s + q[flat ? 1 : 0], 0) / pts.length;
    let out;
    if (flat) {
      const y = shape === "underline" ? u : shape === "outline" ? (Math.abs(mid - T) <= Math.abs(mid - B) ? sT : sB) : near(mid);
      out = pts.map(q => [shape === "outline" ? inX(q[0]) : q[0], y]);
    } else {
      const x = shape === "outline" ? (Math.abs(mid - L) <= Math.abs(mid - R) ? sL : sR) : near(mid);
      out = pts.map(q => [x, shape === "outline" ? inY(q[1]) : q[1]]);
    }
    return Object.assign({}, p, { pts: out.map(q => [q[0] - at.x, q[1] - at.y]), nobow: true, wob: 0 });
  });
}

function strikeBox(b, rnd) {
  const cx = (b.x + b.r) / 2, cy = (b.y + b.b) / 2, t = (rnd() - 0.5) * 3;
  if (b.h > 90 && b.w > 30) return [{ pts: [[b.x + 8, b.y + 12], [b.r - 8, b.b - 12]] }];
  if (b.h < 10 || b.w < 12) {
    const hw = Math.min(28, Math.max(b.w, b.h) / 2 + 8);
    return [{ pts: [[cx - hw, cy + hw * 0.45], [cx + hw, cy - hw * 0.45]] }];
  }
  return [{ pts: [[b.x - 4, cy + t], [Math.max(b.r + 4, b.x + 24), cy - t]] }];
}

export function strikeOver(boxes, highlighter, seed) {
  const rnd = rng(seed);
  if (highlighter) {
    return boxes.filter(Boolean).map(b => {
      const cy = (b.y + b.b) / 2, t = (rnd() - 0.5) * 2.4;
      return { pts: [[b.x - 2, cy + t], [b.r + 2, cy - t]] };
    });
  }
  const b = union(boxes);
  return b ? strikeBox(b, rnd) : [];
}
