/* The ink layer's shapes (#248): where a mark's strokes go, computed from the page's own boxes.

   Pure geometry. Nothing here reads the page or touches three.js: `layer.js` measures the anchor
   (`getBoundingClientRect`, and a Range over its text for `lines`) and hands each function a box
   in the anchor's OWN coordinates -- its top-left corner is 0,0 -- so a pane that moves under a
   gutter drag moves its marks by moving their meshes, and only a pane that changes size rebuilds
   them. Every function answers a list of paths, `{pts: [[x, y], ...]}` plus what the pen should
   know about each (`w` a width of its own, `smooth` to curve through the points, `nobow` for a
   stroke that must not sag, `wob` to scale the tool's wobble). An empty list means "nothing to
   draw here", never an error: a box with no size is an element that is not on the glass.

   The shapes are the prototype's (the operator-approved `notebook-three.html`), with the desk's
   one special case written down rather than assumed: a box narrower than 90px is a pane's 48px
   rail, and a margin mark goes down its middle rather than into a margin it has not got.

   `PAGE_SHAPES` are the page's own (#257): a series drawn from its element's data rather than its
   box alone, for the layer's own rows. A skin's table cannot name them. */

const RAIL_BELOW = 90;

/* A seeded generator, so the same element's outline wobbles the same way on every redraw -- a mark
   that re-rolled its hand on every resize would visibly crawl. */
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

/* One continuous stroke round a box, rounded at the corners and run a little past where it began,
   the way a hand closes a loop. */
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

/* The margin a check or a bang is written in: the left padding of a pane, or the middle of a rail. */
function margin(r) {
  const rail = r.w < RAIL_BELOW;
  return { x: rail ? r.x + r.w / 2 : r.x + 14, top: r.y + (rail ? 16 : 14), rail };
}

/* Each shape: `(m) => paths`, where `m` is what `layer.js` measured -- `m.box` the anchor in its
   own coordinates, `m.lines` its text's line boxes (for `lines`), `m.to` the target of an arrow,
   `m.pad` the row's own padding, and `m.seed` this mark's seed. */
export const SHAPES = {
  /* Four pencil lines round the box, each overshooting its corner a little. */
  outline(m) {
    const r = box(m.box), rnd = rng(m.seed), o = m.pad || 0;
    const j = () => (rnd() - 0.5) * 2.4, ov = () => 3 + rnd() * 6;
    const L = r.x - o, T = r.y - o, R = r.r + o, B = r.b + o;
    return [{ pts: [[L - ov(), T + j()], [R + ov(), T + j()]] },
            { pts: [[R + j(), T - ov()], [R + j(), B + ov()]] },
            { pts: [[R + ov(), B + j()], [L - ov(), B + j()]] },
            { pts: [[L + j(), B + ov()], [L + j(), T - ov()]] }];
  },
  /* A rule across the foot of the box, stopping short of either side. */
  divider(m) {
    const r = box(m.box), y = r.b - 1 + (m.pad || 0);
    if (r.w < 24) return [];
    return [{ pts: [[r.x + 10, y], [r.r - 10, y + 0.8]] }];
  },
  /* A line under the text, a hair past both ends of it. `m.grow` px more on the right when the row
     grows (#249: the running agent's line lengthens with its turn), never past `m.limit`, and with
     `m.tip` a pen-tip dot sitting at its end, or with `m.cap` an arrowhead or a bar (#385). It
     sits 2px under `m.base`, the foot of the tallest box on its text's line (a chip beside a name),
     so a line past the text's end passes under its neighbours' words; and never lower than 2px over
     `m.floor`, the top of the next row (#331). */
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
  /* A highlighter pass along every line the text wraps to, as wide as the line is tall. */
  lines(m) {
    const ls = (m.lines && m.lines.length) ? m.lines : [box(m.box)];
    return ls.map(l => {
      const cy = l.y + l.h / 2;
      return { pts: [[l.x - 5, cy + 0.8], [l.x + l.w + 6, cy - 0.6]],
               w: Math.max(12, Math.min(26, l.h * 1.05)) };
    });
  },
  /* One rounded stroke round the box, closed past its start. */
  loop(m) {
    return [loopPath(box(m.box), 3 + (m.pad || 0), 7, 12)];
  },
  /* A loose ellipse round the box, drawn a little more than once round. */
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
  /* A line through the box: across the middle of a line of text, corner to corner of a tall box,
     a short slash through a small one. Also how an ink mark leaves (`strikeOver`). */
  strike(m) {
    return strikeBox(box(m.box), rng(m.seed));
  },
  /* A tick in the margin. */
  check(m) {
    const g = margin(box(m.box));
    return [{ pts: [[g.x - 9, g.top + 12], [g.x - 3.5, g.top + 19], [g.x + 10, g.top + 1]],
              smooth: true, nobow: true }];
  },
  /* An exclamation mark in the margin: a stroke and a dot. */
  bang(m) {
    const g = margin(box(m.box)), y0 = g.top - 2, h = 22;
    return [{ pts: [[g.x - 0.5, y0], [g.x + 0.6, y0 + h]], wob: 0.3, nobow: true },
            { pts: [[g.x + 0.4, y0 + h + 7], [g.x + 0.9, y0 + h + 8.8]], nobow: true }];
  },
  /* From the left of the box to the foot of its target (`to` in the row), curving on the way. */
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
  /* The handwriting reveal is not strokes: `layer.js` uncovers the element's own text left to
     right, with the pen travelling along it. It has no paths of its own. */
  write() {
    return [];
  },
};

export const SHAPE_NAMES = Object.keys(SHAPES);

/* The page's own shapes (#257), drawn by the layer's own rows and never named in a skin's table: a
   series read from its element's data. `m.values` are its heights, oldest first, each a fraction of
   the box (0 nothing, 1 the whole height); `m.ticks` are the slots a tick goes through. */
export const PAGE_SHAPES = {
  /* The hour as one line, left to right through every slot. A slot with anything in it is never
     flat: a pixel above the floor is "it was awake", which is the difference between a quiet hour
     and no hour at all (#218). No bow and little wobble, because this line is data. */
  series(m) {
    const v = m.values || [];
    if (v.length < 2 || !v.some(x => x > 0)) return [];
    const r = box(m.box), slot = r.w / v.length, floor = r.b - 1.5, span = Math.max(1, r.h - 3);
    const pts = v.map((x, i) => [r.x + (i + 0.5) * slot, floor - (x > 0 ? Math.max(1, x * span) : 0)]);
    return [{ pts, nobow: true, wob: 0.15, w: 1.2 }];
  },
  /* A stroke top to bottom through each slot that stopped for a person. */
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

/* Ruled strokes on a grid (#253, the graph paper): a row with `snap` has its straight strokes put
   on the grid's lines, which are every `g` px of the viewport, where the skin's paper draws them.
   `at` is where the anchor's top-left is on the viewport, so the paths -- in the anchor's own
   coordinates -- are moved there, ruled, and moved back.

   A divider moves across onto the nearest line. An outline keeps inside its box (#331): each edge
   goes onto a line in the box's padding band -- `o.band`, the px between its border box and its
   content box, left, top, right, bottom -- or, where that band is narrower than a square, down
   the band's middle, unruled; every end moves with the box edge nearest it and stops at the
   border box, so its corners still cross and nothing is drawn over the words or past the pane.
   An underline goes to the first line in [`o.base` + 2, `o.floor` - 2] (its text's foot and the
   next row's top, as `underline` has them), and stays where it is when there is none. A ruled
   stroke does not sag or wander: it is drawn to a ruler. */
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

/* How an ink mark leaves: struck through with one pen line. A highlighter's swipes are struck one
   by one, along each; anything else is struck across the box its strokes cover together. `boxes`
   are the strokes' own bounding boxes, in the anchor's coordinates. */
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
