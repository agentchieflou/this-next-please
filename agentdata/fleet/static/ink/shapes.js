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
   rail, and a margin mark goes down its middle rather than into a margin it has not got. */

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
     `m.tip` a pen-tip dot sitting at its end. */
  underline(m) {
    const r = box(m.box), y = r.b + 1 + (m.pad || 0);
    let x1 = r.r + 8 + (m.grow || 0);
    if (Number.isFinite(m.limit)) x1 = Math.max(r.r + 8, Math.min(x1, m.limit));
    const out = [{ pts: [[r.x - 3, y], [x1, y + 1.2]], nobow: true }];
    if (m.tip) out.push({ pts: [[x1 + 2.2, y + 0.8], [x1 + 3.4, y + 1.4]], w: 4.4, nobow: true, wob: 0 });
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

/* Ruled strokes on a grid (#253, the graph paper): a row with `snap` has its straight strokes put
   on the grid's lines, which are every `g` px of the viewport, where the skin's paper draws them.
   `at` is where the anchor's top-left is on the viewport, so the paths -- in the anchor's own
   coordinates -- are moved there, ruled, and moved back.

   Each straight stroke keeps its length and moves across onto the nearest line. An outline's
   corners meet where its lines cross: every end moves with the box edge nearest it. An underline
   goes down to the first line at or below its text, never up through it. A box smaller than a
   square is still a square, so an outline never folds into a line. A ruled stroke does not sag
   or wander: it is drawn to a ruler. */
export function snap(paths, shape, b, at, g) {
  const near = v => Math.round(v / g) * g;
  const down = v => Math.ceil((v - 0.5) / g) * g;
  const L = b.x + at.x, T = b.y + at.y, R = L + b.w, B = T + b.h;
  const sL = near(L), sT = near(T);
  const sR = Math.max(near(R), sL + g), sB = Math.max(near(B), sT + g);
  const shiftX = x => x + (Math.abs(x - L) <= Math.abs(x - R) ? sL - L : sR - R);
  const shiftY = y => y + (Math.abs(y - T) <= Math.abs(y - B) ? sT - T : sB - B);
  return paths.map(p => {
    const pts = p.pts.map(q => [q[0] + at.x, q[1] + at.y]);
    const a = pts[0], z = pts[pts.length - 1];
    const flat = Math.abs(z[0] - a[0]) >= Math.abs(z[1] - a[1]);
    const mid = pts.reduce((s, q) => s + q[flat ? 1 : 0], 0) / pts.length;
    let out;
    if (flat) {
      const y = shape === "underline" ? down(mid) : shape === "outline" ? near(shiftY(mid)) : near(mid);
      out = pts.map(q => [shape === "outline" ? shiftX(q[0]) : q[0], y]);
    } else {
      const x = shape === "outline" ? near(shiftX(mid)) : near(mid);
      out = pts.map(q => [x, shape === "outline" ? shiftY(q[1]) : q[1]]);
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
