# Plan: ink — three.js draws every skin, starting with the notebook

_Status: PLANNED (2026-09-23) — epic #246 (slices #247–#257), under #91 (the fleet). It comes after fresh sessions
(#238), which the operator named its precondition, and after panes slice C (#232), whose layout the marks are drawn
from. The operator's answers are recorded in §Decisions._

## Why this exists

The operator compared two prototypes of a notebook theme, one on Canvas 2D and one on three.js, and chose three.js:
*"We'll [write] a basic notebook version (light mode), a dark mode, a yellow-page version, a "napkin notes" style,
and then a graph paper style. Then, we'll also want to upgrade all our existing themes and palettes to leverage
three.js so we're not supporting two separate UI platforms. three.js only is the goal now."*

The theme's rule, from the request before it: marks are **drawn on the fly** by a pencil, a pen, a highlighter or a
marker. They never transition. A mark that goes is erased if it was pencil, and struck through if it was ink.

| What the operator asked for | What the desk has today |
|---|---|
| one UI platform | three CSS skins (`glass`, `farmstead`, `voxel`), two 2D canvases (the ground and every agent's trace), and twelve palettes shared with the terminal |
| paper skins drawn live | no drawing layer. Motion is CSS transitions and view transitions (`desk-motion.md`) |
| three.js | `desk-engines.md`: WebGL is *"not used, and will not be until these rows say all four shells run it"*, and three of the four columns say *not yet measured* |

## The model

**The DOM keeps the words and the controls. three.js draws everything else.** Every label, transcript line, button
and reply box stays real page text: accessibility, typing a reply, IME, selection and every Playwright test depend on
it, and the render contract (`desk-components.md`) already owns it. What moves to three.js is everything that is
decoration today: paper, frames, marks, the ground, the traces, and the motion that belongs to them. That is what
"one platform" means here. There are no longer two ways to draw a skin, and no CSS skin that has to agree with a
WebGL one.

**The ink layer** (`static/ink/`, #248):

- **three.js r160, vendored** under `static/vendor/three/` with its MIT licence, and loaded by a
  `<script type="module">` beside the classic `app.js`. The desk has never fetched from a CDN, and it still has no
  build step.
- **One full-page canvas** behind the DOM, and `window.Ink` as the only surface `app.js` sees.
- **Lanes.** One queue of drawing per agent, plus one for the header, so two agents draw at once and one agent's
  marks never interleave.
- **Marks are derived from the DOM, not pushed.** A skin is a table: *when this selector matches, this tool draws
  this shape around it*, for example `.tile.needs-human .repo` → highlighter, `lines`. The layer watches the classes
  `app.js` already sets. So a tile's truth stays in one place, and no skin can show a state the page does not have.
- **Shapes are computed from `getBoundingClientRect`**: outline, divider, underline, highlight lines, loop box,
  ellipse, strike, check, bang, arrow, and the handwriting reveal. A resize or a panes drag redraws them in place.
- **Tools have their own physics**: pencil, pen, red pen, green pen, marker, highlighter and eraser, each with a
  width, pressure, wobble, taper and a shader (graphite tooth, ink bleed, the highlighter's multiply or screen).
- **Reduced motion draws at once**, with no travelling pen.

**A skin is a material set plus a mark table.** Paper, frames and the ground are materials. What each state looks like
is the mark table. **A palette colours the inks, and a skin chooses the paper.** The twelve palettes stay exactly what
they are, shared with the terminal, and `theme.check` gains every ink-on-paper and composited-pane pair.

**The plain fallback** (Decision 3). No WebGL, a software renderer, a lost context, or `?ink=off` adds
`body.ink-off`, and the *same* mark table is drawn as CSS borders and highlights. It is one look, shared by every
skin: a degraded mode of the one platform, not a second one.

## Slices

- **A #247 — WebGL, measured in all four shells.** A `/probe` page records WebGL1 or 2, the unmasked renderer,
  whether it is software, frame p50/p95 and first-stroke latency, and posts them to the desk
  (`~/.agentdata/fleet/probes.json`). `ad-fleet probe --open <shell>` and `ad-fleet engines` mean nothing is copied
  by hand. The WebGL rows of `desk-engines.md` are filled from the results. **This is the gate**: a shell that
  reports software or no WebGL gets the fallback.
- **B #248 — the ink layer.** Everything in §The model. Nothing visible changes until a skin uses it.
  - **Built (#248)**, in `static/ink/` and [desk-ink.md](desk-ink.md), tested by `tests/test_fleet_ink.py`. What
    building it decided, each undone by a sentence from the operator:
    - **The verdict is two words on `<body>`**, written by the server as it serves `/`: `data-ink-shell` and
      `data-ink-probe` (`probe.classify` of that shell's record, or `unmeasured`). It is not a field of
      `/api/fleet` or the desk frame. So the gate is decided when the module runs, with no second request, nothing
      drawn and taken back, and nothing added to `app.js`. The page turns ink on for `hardware` alone, which is
      `probe.works`.
    - **A window's shell is the name the probe filed it under**: `shell=`, else `w=`, else `browser`. A window opened
      under its own name reads its own record, or names one with `shell=`.
    - **`?ink=on` is the test override** (`Ink.verdict.source` is `override`, and nothing is written), and `?ink=off`
      forces the fallback.
    - **Lazy in two steps.** Every desk loads `ink/ink.js` (4.5 KB gzipped), which holds the gate, `window.Ink` and
      the fallback. `layer.js`, `shapes.js`, `pen.js` and three.js are fetched only when the gate is on **and** a
      skin sets a table. So until the notebook ships, no desk fetches three.js. The WebGL context is asked for
      before three.js is fetched.
    - **A lost context, no context, or three.js failing** turns ink off for the rest of the page. It is not brought
      back on `webglcontextrestored`.
    - **The fallback is a constructed stylesheet** generated from the same table, one rule per row under
      `body.ink-off :is(<selector>)`. It needs no DOM write and no observer. The plain look for each shape is the
      table in desk-ink.md: outline, tint, underline, line-through, a margin bar.
    - **Lanes are `.tile[data-repo]`**, and everything outside a pane is the header lane. Rows are queued in table
      order.
    - **Leaving:** pencil is erased and everything else is struck with the pen. One struck mark is kept per row and
      element, so the history shows without piling up. An element that leaves the page takes its marks with it. A
      match that returns before its eraser starts keeps its mark, and a mark that goes before its pen starts is
      never drawn. A mark on a hidden pane or a rail is finished at once.
    - **Geometry is in the anchor's own coordinates**, so a move moves meshes and only a resize rebuilds them. A
      `ResizeObserver` redraws in the frame the browser laid out, which is how marks follow a gutter drag with no
      DOM write. Each mark is clipped to its scrolling ancestors.
    - **The handwriting reveal is the layer's one page write**: `clip-path` on the element being written, while it
      is written. It is taken back when the table changes or the layer stops.
    - **A minimal paper material** (a colour with the tooth) exists so the highlighter can multiply into light
      paper and screen onto dark. With no paper, the highlighter is a translucent swipe. The notebook's rules and
      margin are C's.
    - **Inks come from `--ink-<tool>`, then a palette token**: pencil `--muted`, pen `--accent`, red and marker
      `--human`, green `--done`, highlighter `--waiting`.
    - **The prototype's lit hand is ported**, one per lane. It is off under reduced motion, and a table can turn it
      off with `hand: false`.
    - **`theme.check(..., inks=)`** is rule 5: each ink needs 3:1 on the paper, and text needs 4.5:1 through the
      highlighter's 38% tint. The pairs come with C–G's skins.
    - **A skin is one module**, `static/ink/skins/<name>.js`, named as in `skins.py`. It exports its `marks` (a
      function of the variant, or rows), its `options`, and the material hooks the layer calls: `ground`, `paper`,
      `frame(el, box)` per pane, `tick(dt)`, `dispose`, and `sampleGround` for a frosted pane. Each hook gets
      `{THREE, scene, camera, tokens, api}`. The server lists the modules on `<body>`. `ink.js` follows
      `body[data-skin]`, which `applySkin` writes when the config's skin changes, so the settings page chooses an
      ink skin the way it chooses glass. No skin patches the layer. `skins/example.js` is the pattern, and only
      the tests use it.
    - Not in B: the running pen's dot and its underline growing with the turn, the header count struck and
      rewritten, and the notebook's paper. All three are C's, and they need the state grammar.
- **C #249 — notebook (light).** The prototype on the real desk, with the state grammar below. An answered question
  strikes the *question*, never the agent's name, which fixes the flaw both prototypes had.
- **D #250 — notebook, dark.** Charcoal stock and gel inks. The highlighter screens instead of multiplying. Chosen
  by the palette's luminance or named `notebook-dark`.
- **E #251 — legal pad.** Canary stock, blue rules, a double red margin and a glued top edge. The highlighter shifts
  to orange-pink so it still reads on yellow.
  - **Built (#251)**, as `legalpad` in `skins.py` (`static/ink/skins/legalpad.js`, `skins/legalpad/skin.css`),
    in [desk-ink.md](desk-ink.md) §The legal pad, tested by `tests/test_fleet_ink_legalpad.py`. What building it
    decided, each undone by a sentence from the operator:
    - **Canary `#FCF3A6` on `eye-relief-day`**, the one light palette whose text and status colours all hold on it.
      The inks it overrides are pencil (graphite), pen (a blue ballpoint) and the **orange-pink highlighter
      `#FF8FA3`**; each of the six is in `skins.py` and held to the canary by `theme.check`.
    - **The grammar is a mark table over classes the page already sets.** *Answered* is `aria-pressed` on the chosen
      choice (the card has no answered class, and hides once the answer lands); *a finding* is a transcript line
      the page marks `denied` or `friction`; *stale* writes the chip's own words and points at the run line;
      *the header count* is the bell's.
    - **The running pen's tail and the struck header count are drawn by the skin**, in its `tick`, because the
      layer has no shape for them; the tail grows one step per transcript line of the turn. C builds the shared
      version and K consolidates. The new count is not written again by the reveal, which the layer would need
      to re-run on a change of text.
    - **No font is downloaded**: a local cursive stack.
    - **`state-done` is rare on today's desk** (unsupervised reads idle, supervised reads running); the row waits
      for the page to set it.
    - **A skinned desk was never idle** (every refresh rewrote the skin's attributes, and the glass ground's retry
      looped for other skins); `common.js` and `app.js` now write only what changed.
- **F #252 — napkin notes.** Quilted two-ply with no rules. A felt tip that bleeds along the emboss. A coffee ring
  under a pane that has been idle a long time.
- **G #253 — graph paper.** A grid on the page's own 28 px baseline, a mechanical pencil, ruled strokes snapped to the
  grid, and traces plotted on it.
- **H #254 — glass on three.js.** A real mesh ground, frosted panes that sample it through a blur pass, lit glints
  and shadows. The composited panel `theme.check` measures is read from the rendered frame.
- **I #255 — farmstead on three.js.** The original `sprites.svg` art as nearest-neighbour textures at integer scale,
  lit wooden frames, and crop glyphs that grow a stage when an agent's phase advances.
- **J #256 — voxel on three.js.** Real voxel slabs and status stacks, instanced, one draw call per material.
- **K #257 — one platform.** `drawGround` and `drawTrace` move to the ink layer and nothing calls
  `getContext("2d")`. Skin files keep only layout and typography (a guard refuses decoration in them). The fallback
  is the one CSS look left.

Build order: A and B first, in either order, because neither changes what anyone sees. Then C, whose marks are the
reference every later skin is measured against. D through G follow in any order, then H through J, and K last. A
skin ships switched on only for shells A measured as hardware WebGL. Until then it is selectable and falls back.

## The state grammar (paper skins)

| State | Mark |
|---|---|
| idle | pencil outline, pencil underline under the name |
| running | pen underline that grows with the turn, and the pen-tip dot at its end |
| needs you | highlighter on the name and on the question, pencil loops around the choices |
| answered | the question and its highlight struck through in pen, and the chosen answer circled |
| error | red marker box around the pane, and a bang in the margin |
| done | green check in the margin |
| stale (#240) | a pencil margin note, *stale — renew?*, with an arrow to the version line |
| a finding | red ellipse around the line, highlight on the token, and the finding's own text as a margin note |
| the header count | handwritten. When it changes, the old number is struck and the new one written beside it |

## Ground rules

1. **Drawn, never faded.** A mark arrives by being drawn and leaves by being erased or struck. The one exception is
   reduced motion, where it appears drawn.
2. **The DOM is the truth.** Marks are derived from classes the page already sets, and the ink layer never decides a
   state.
3. **No CDN, no build step.** three.js is vendored and loaded as a module, as the page has always worked.
4. **No `innerHTML` in `static/ink/`.** The page's ban holds for the new code too.
5. **Budgets stay honest.** A gesture keeps its DOM budget (`desk-instant.md`), because the ink draws after it.
   The ink's own test counts frames to catch up, not milliseconds, because CI renders in software (SwiftShader), and
   real-GPU numbers come from A's probe on the laptop.
6. **The fleet still writes only under `~/.agentdata/fleet/`.** The probe's record lives there.

## Decisions — the operator's, 23 September 2026

1. *"I choose the three.js version."* Chosen over Canvas 2D after the two prototypes, measured side by side:
   - Canvas 2D: no library and 38 KB inline; 16.7 ms frames; 25 ms to the first stroke.
   - three.js: 162 KB compressed and 62 KB inline; 117–150 ms frames under SwiftShader, which is software rendering
     and not representative; 131 ms to the first stroke.
2. *"three.js only is the goal now"*: every existing skin and palette moves onto it, and the desk stops supporting
   two UI platforms.
3. **No WebGL gets a plain fallback**: the same page with plain borders and highlights, and no animation. *Require
   WebGL* was offered and not chosen.
4. **"Yellow-page version" is a yellow legal pad.** A Yellow Pages directory look was offered and not chosen.
