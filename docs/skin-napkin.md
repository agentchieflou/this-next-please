# Napkin notes: the desk written on a quilted paper napkin

_Slice F (#252) of the ink epic (#246, [plan-ink.md](plan-ink.md)). Drawn by the ink layer
([desk-ink.md](desk-ink.md)). Chosen in the settings as **Napkin notes · Diner** or **· Kraft**, `theme.skin`
`napkin`, `napkin:diner` or `napkin:kraft`._

The operator asked for *a "napkin notes" style* among the paper skins. The plan gave it three things: **quilted
two-ply with no rules, a felt tip that bleeds along the emboss, and a coffee ring under a pane that has been idle a
long time.** Its marks are the same paper state grammar as the notebook.

## The files

| File | Holds |
| --- | --- |
| `static/ink/skins/napkin.js` | the mark table, and the `paper`, `frame`, `tick` and `dispose` hooks. It writes no colour of its own, and reads the page but never writes it. It also exports `inspect()`, what it has on the paper per pane, for tests and the console |
| `static/skins/napkin/skin.css` | the colours as custom properties per variant (`--paper`, `--paper-seam`, `--coffee`, `--ink-<tool>`), the handwriting stack, the panes made transparent under ink, and the napkin under `body.ink-off` |
| `agentdata/fleet/skins.py` | the two variants, the palette each is drawn against, the panel pair `theme.check` reads, and the inks |

The module is 7.4 KB gzipped. Like every skin's module, only a desk that chose it fetches it, and it is outside the
desk's payload budget ([desk-engines.md](desk-engines.md)). It fetches nothing else, because the quilt is procedural
and there is no texture.

**The handwriting is a local cursive stack** (`Segoe Print`, `Bradley Hand`, `Comic Neue`, `Chalkboard SE`,
`Comic Sans MS`, `cursive`) on the agent's name, the header count and the stale note. No font is vendored or
fetched, so the payload is unchanged. A machine with none of these draws its own `cursive`.

## The stock

The paper hook draws one quad under the whole page. Its shader has three parts:

* **The quilting** is a diamond lattice pressed into the paper. Its seams run on both diagonals, 18.4 px apart
  (a 26 px lattice).
* **The pillows** between the seams are puffed, and each has a fine dot emboss.
* **The paper** is lit from the top left like the layer's own. It is never darker than `--paper-seam`.

"Two-ply" is the seam colour: the second ply shows through where the quilting presses the sheets together. There are
no rules and no margin. The seams are in page px, so they stay put while panes move across them. The felt tip's
bleed uses the same lattice, so its ink runs down the seams the paper shows.

Under ink the bars, the row and the panes are transparent, so the napkin shows through them. Cards on a pane
(the approval, the questions, menus) keep their own ground.

## The marks: the paper state grammar

Every row matches a class or attribute the page already sets (`test_fleet_napkin.py` holds the table to that), so
the skin shows no state the page does not have.

| State | Mark | The row(s) |
| --- | --- | --- |
| idle | pencil outline; the name underlined in pencil | `.tile.state-idle` outline, `.tile.state-idle .head .repo` underline |
| running | the name underlined in pen, and **the pen's tip** resting at the end of the line | `.tile.state-running .head .repo` underline. The tip is a material (`frame`/`tick`), shown when the line is drawn and kept when it is struck |
| needs you | highlighter on the name and on the question; pencil loops round the choices | `.tile.needs-human .head .repo` (`leaves: "erased"`), `.asks:not([hidden]) .ask:not([hidden]) .ask-q`, `… .ask-choice:not([aria-pressed="true"])` |
| answered | the chosen answer circled in pen, with its pencil loop erased. When the question goes, its highlight is struck in pen. **The name is erased, never struck** | `.ask:not([hidden]) .ask-choice[aria-pressed="true"]` ellipse. The strike is how the layer takes back any ink |
| error | the felt tip's box round the pane, with its bleed; a bang in the margin | `.tile.state-error` marker loop, `.tile.state-error .head` red bang |
| done | green check in the margin | `.tile.state-done .head` |
| stale (#240) | the chip's own words written in pencil as a margin note, an arrow from it to the run's line, a dashed pencil outline | `.oldsession:not([hidden])` write and arrow (`to: ".runline"`), `.tile:has(.oldsession:not([hidden]))` dashed outline |
| the header count | handwritten, in pen | `#counts` write |

An agent in error also carries `needs-human`, because an error needs you. So its name is highlighted too.

**What the page does not have yet, and so is not drawn:**

* **A finding.** The desk has no findings markup. `sqlcheck` findings are not on it, and the skin adds no class.
* **A line that grows with the turn.** The page does not carry the turn's length. The running pen's line is the
  name's length, and the tip sits at its end.
* **The old count struck and the new one written beside it.** When the count's text changes, the layer keeps its
  mark, and the old number has left the DOM. Both are the layer's to add, and plan-ink gives them to C (#249).
* **Done on the desk.** A pane is `state-done` only while a process is supervised, and a quiet agent shows as idle.
  The row is there for when the page says done.

**The name is erased, never struck.** The grammar strikes the question and never the agent's name: a name struck
through reads as an agent that has gone. The layer strikes every ink mark that leaves, so a row may now say
`leaves: "erased"` (desk-ink.md §A skin is a mark table, one general addition in its own commit). The name's
highlight uses it.

## The felt tip bleeds along the emboss

The felt tip is the `marker`, and it draws the error box. Under the loop, each error pane has a bleed quad in its
frame. The quad's shader finds the nearest point on the loop `shapes.js` draws, which is a rounded rectangle 5 px
out with 7 px corners, begun at the top left and drawn clockwise. It inks the paper round the loop:

* **only as far as the pen has drawn**, which it reads from the marker mark's `drawn` in `Ink.inspect()`;
* **further where the paper is pressed in**: up to about 14 px from the line in a seam, and under 4 px on a pillow;
* **more as it soaks**: the bleed is at full reach 180 px of pen travel behind the pen, and the last of it soaks in
  0.7 s after the pen lifts (`SOAK_PX`, `SOAK_S`).

Ink that has soaked in does not come back out. The bleed stays when the box is struck, and goes only when the mark
goes (the pane leaves the page). Under reduced motion it is soaked in at once. `tick` asks for frames only while it
soaks.

## A coffee ring under a pane idle a long time

**The signal is a class the page already sets.** The pane is `.tile.state-idle`, and its chip is `.chip.stale`,
which `ageChip` in app.js sets when the last event is a day old or more. No class was added.

The ring is a quad in the pane's frame, placed on the open paper below the transcript's first lines and clear of the
reply row. It is placed a little differently per repository, so two rings never line up. It has a darker rim where the
coffee dried, a faint wash inside, and part of a second rim where the cup was put down twice. **A cup is put down,
not drawn**, so the ring is there on the frame the pane has been idle a day, and gone on the frame the agent wakes. It
is a material under the marks, not a mark, so the grammar's *drawn, never faded* is about the ink on it.

Its alpha is `--coffee`'s. `skins.py` composites that over the seam for the darkest panel the text is ever read on.

## Colours, and `theme.check`

A palette colours the inks, and a skin chooses the paper. The module reads every colour through `tokens.css(name)`
at paint time, and a test holds it to having no hex of its own.

| Variant | Palette | Paper | Seam | Coffee | Darkest panel (the ring's rim over a seam) |
| --- | --- | --- | --- | --- | --- |
| `diner` (default) | `eye-relief-day` | `#FBF9F4` | `#F1EFEA` | `#8A5A2E` at 0.14 | `#E3DAD0` |
| `kraft` | `sand` | `#F2EADA` | `#EBE3D3` | `#7A4E2A` at 0.10 | `#E0D4C2` |

| Variant | pencil | pen | red | green | marker (the felt tip) | highlighter |
| --- | --- | --- | --- | --- | --- | --- |
| `diner` | `#5B5E66` | `#1E3A8A` | `#B42318` | `#256B45` | `#B3261E` | `#F4DC52` |
| `kraft` | `#57524A` | `#243F86` | `#A3271C` | `#2A6A3F` | `#9E2A1E` | `#F5D94A` |

The panel is a pair, the way glass's is. Its dark end is the ring's rim over the seam, and its light end is the
paper. `theme.check` holds the text (4.5:1), the status colours (3:1) and every ink (3:1, or 4.5:1 for the text through
the highlighter) at both ends. The pair is computed from the paper, seam and coffee, never typed, and the test reads
skin.css back to prove the stylesheet draws the numbers skins.py checks.

## Without ink

Every shell whose probe did not say `hardware` gets `body.ink-off` (plan-ink Decision 3). There the napkin is CSS:

* the same quilting as two `repeating-linear-gradient`s at the shader's spacing, on the page and on each pane;
* the ring as a `radial-gradient` under `.tile.state-idle:has(.chip.stale)`;
* the same mark table, drawn plain by the layer's own fallback: outlines, tints, underlines and margin bars.

No layer and no three.js is fetched.

## Tests

`tests/test_fleet_napkin.py` covers each of these. States come from agents' own streams (an error, an open question,
a live lock, events three days old), because the desk's redraw owns the state classes:

* skins.py and skin.css say the same numbers, and `theme.check` passes at both ends;
* the module has no colour of its own and matches only classes the page sets;
* each state's mark is drawn from the class, and the pen's tip is at the end of the running line;
* a state that goes is erased or struck, the name is never struck, and the chosen answer is circled;
* the coffee ring is under the long-idle pane only (read back from the canvas) and goes when the agent wakes;
* the felt tip inks the seams just outside its stroke and hardly any of the pillows between;
* reduced motion draws everything at once;
* the plain fallback draws the napkin, both variants;
* an idle napkin is zero DOM writes and zero WebGL frames, and it settles within the frames the pen needs plus the
  soak.

`tests/regressions/test_20260923_any_skin_desk_at_rest_writes.py` is the bug building this found. With any skin
chosen, every refresh rewrote `data-theme`, `data-skin` and `data-skin-variant`. For a skin with no ground mesh it
also toggled the stylesheet link's `data-waiting`, so an idle desk was never zero writes.
