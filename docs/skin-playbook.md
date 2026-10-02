# The playbook

A coach's chalkboard (#389, epic #294). Choosing **Playbook** on /settings puts the desk on the `nfl-browns`
palette as a chalkboard: every agent an O, its turn a route in orange chalk, and the state grammar
([desk-ink.md](desk-ink.md) §The state grammar across skins) written in football notation.

| File | Holds |
| --- | --- |
| `agentdata/fleet/skins.py` `SKINS["playbook"]` | the skin, its variants, their palettes, composited panels and inks |
| `agentdata/fleet/static/ink/skins/playbook.js` | the mark table and the options (the chalk) |
| `agentdata/fleet/static/skins/playbook/skin.css` | the board's colours as custom properties, the margin and the hand |
| `tests/test_fleet_ink_playbook.py` | the checks below |

## Variants

| Variant | Palette | Board (darkest … lightest) | Why |
| --- | --- | --- | --- |
| `playbook:chalkboard` *(default)* | `nfl-browns` | `#2B1B08` … `#40301D` | brown slate, cream and orange chalk |
| `playbook:playsheet` | `sand` | `#E9DFC9` (`--yard`) … `#F7F1E3` (`--paper` = `--board-max`) | a printed play sheet: graphite and a burnt-orange pen |

**The play sheet (#392).** A bright-room playbook: a printed play sheet on cream stock, graphite and a burnt-orange pen,
chosen as "Playbook · Play sheet". Skins drive palettes, so a light playbook names a light palette: `sand` is the
closest warm light ground, and the Browns orange does not hold on a light one. No new palette is added. The stylesheet
maps a light variant the other way round: `--paper` and `--board-max` are the lighter end and `--yard` the darker
(the test reads the mapping off `theme.get(base).light`). `options` is a function of the variant: the sheet is drawn
with the default pencil and hand (no chalk), and `paper` branches on `tokens.dark`: print-paper fibre instead of
slate, the same yard lines and hash marks, no eraser ghosts, clamped per channel to [`--yard`, `--paper`]. The
highlighter multiplies, the layer's own choice on a light paper. The moments keep their tokens; the goalposts and the
hatch are drawn with the default pencil.

| Pair (play sheet) | at `#E9DFC9` | at `#F7F1E3` |
| --- | --- | --- |
| text `#3A3126` | 9.63:1 | 11.32:1 |
| `--muted` `#60574A` (#325) | 5.36:1 | 6.30:1 |
| pencil `#57524A` | 5.85:1 | 6.88:1 |
| pen `#9A4F12` | 4.53:1 | 5.33:1 |
| red and marker `#A01A4F` | 5.76:1 | 6.77:1 |
| green `#2A6A3F` | 4.91:1 | 5.77:1 |
| text through the highlighter `#F5D94A` (multiplied) | 7.73:1 | 9.04:1 |

The kraft napkin's red `#A3271C` and marker `#9E2A1E` are only 22.0° and 21.3° in hue from this pen, so an error would
read like a route; `#A01A4F` is 50.6° away. `#bellcount` and the finding's note stay in the pencil (5.85:1 at the
darker end).

## The grammar

Every row is a class the page already sets (`app.js` `setTileState`, `needs-human`, `is-done`).

| State | Reading | Rows |
| --- | --- | --- |
| open pane | the player, the line of scrimmage | a pencil `ring` round `.head .n`, a pencil `divider` under `.head`; neither on a rail |
| idle | in the huddle | the notebook's two idle rows, in pencil |
| running | the route | a pencil `underline` in the pen's ink under the name, growing a step per transcript line, ending in an `arrow` cap |
| waiting_approval | the option route | the same, `dash`ed |
| blocked | stopped at the line | a pencil `underline` in the red ink ending in a `bar`, and a red `cross` in the margin |
| needs you, answered | the flag, the call | the notebook's rows; its pen rows are the pencil's chalk in the pen's ink |
| error | the fumble | the notebook's marker `loop` round the why and its `bang` |
| done | touchdown | a green `check` |
| stale, a finding, the header's count | an audible, the film, the scoreboard | the notebook's rows; the count in the pen's ink |

The rows every skin carries (`GRAMMAR` in `tests/test_fleet_ink.py`) are matched on a row's `ink` when it names one, so
the running route drawn with the pencil's chalk in the pen's orange is the grammar's pen.

The chalk is `hand: "chalk"` (#387) and the pencil tuned as the research probe drew it on this ground:
`{w: 2.8, press: 0.8, pvar: 0.4, wob: 0.7, lam: 60, tin: 3, tout: 5}`. Chalk is erased when its state goes, never
struck.

## Colours and ratios

Held by `theme.check` at both ends of the board and plain (`tests/test_fleet_skin_guard.py`), and by the playbook's
own tests.

| Pair | at `#2B1B08` | at `#40301D` |
| --- | --- | --- |
| text `#F2E8D9` | 13.71:1 | 10.44:1 |
| `--muted` `#A79984` (#325) | 5.96:1 | 4.54:1 |
| pencil `#D9CBB3` | 10.41:1 | 7.92:1 |
| pen `#FF3C00` (the route) | 4.67:1 | 3.56:1 |
| red and marker `#FF5A8A` | 5.61:1 | 4.27:1 |
| green `#56D364` | 8.63:1 | 6.57:1 |
| text through the highlighter `#BF9637` (screened) | 5.93:1 | 4.70:1 |

- **The lightest end is a ceiling.** `#40301D` is the lightest the board may paint: with `--muted` at `#A79984` it
  gives 4.54:1 (`#42321F` would give 4.41:1). The muted colour is never recoloured to make room.
- **No word is written in the pen or the red.** The finding's words and the header's count are in the pencil's
  chalk, 7.92:1 at the light end, where the pen would be 3.56:1 and the red 4.27:1. A test holds every
  `color: var(--ink-<tool>)` in skin.css to 4.5:1 at both ends of every variant.
- **An error never reads as a route.** The error red `#FF5A8A` is 31.6° in hue from the orange pen; the test holds
  every variant to 30°.
- **The highlighter is `#BF9637`, not the issue's `#E3B341`.** Since #329, `theme.check` reads the text through the
  highlighter the layer actually screens onto a dark board; `#E3B341` there gives 4.06:1 at the light end.
  `#BF9637`, the same hue darkened, gives 4.70:1.

## The board

The `paper` hook (#390) draws the whole page as one full-viewport mesh at `api.order.paper`, a static shader built only
when the skin arrives, on a resize and on a palette change. Its colours are the stylesheet's `--paper`, `--yard` and
`--board-max`, read through `tokens`; the module writes no colour.

- **Slate.** `--paper` lifted 3%, with a fine grain (plus or minus 2.5% luminance) and a low-frequency chalk haze
  (plus or minus 2%).
- **Eraser ghosts.** Three to five large soft smudges toward `--board-max`: old plays, half-erased. They are seeded
  from the viewport's size, so every redraw at one size is the same board.
- **Yard lines.** 1.5px in `--yard` (`#3F2D19`, 1.27:1 on the board) every 140px, five of the page's 28px baselines,
  from the first baseline under the header.
- **Hash marks.** 10px ticks every 28px at one third and two thirds of the viewport's width.
- **The ceiling.** Every pixel is clamped per channel to [`--paper`, `--board-max`]. The text's contrast is declared at
  `#40301D` (text 10.44:1, `--muted` 4.54:1), so anything the board painted lighter would break those pairs silently;
  `tests/test_fleet_ink_playbook.py` reads every pixel of the board back at 1400x900 (all but the marks and the page's
  traces) and holds it to the range, plus or minus 1.
- **No words.** No yard numbers, logos or words on the board (desk-rendering rule 4), and nothing moves: no dust, no
  drift. No chalk tray is drawn (the issue's step 4 is optional).

`options.paper` stays `--paper`: it tells the layer the board is dark, so the highlighter screens. The module's
`inspect()` gives `{builds, ghosts, top}`: how many times `paper` has run, the ghosts' centres and radii, and the first
baseline under the header.

## The moments

Three one-shot moments (#391), each derived from a class the page already sets, drawn in the pane's own `frame`
group: one record per pane, its materials rebuilt at their current progress whenever `frame` is called again (a
resize or a palette change kills the old `api.stroke` handles). `tick` answers `true` only while something flies,
hops or draws.

| Trigger | Moment | Timing |
| --- | --- | --- |
| `needs-human` arrives | **The penalty flag**: a 14x10px cloth with a knot in `tokens.waiting` (the palette's warn, 8.5:1 on the board), thrown from the head's right end along an arc with 1.5 turns, landing flat in the pane's left margin (the 36px gutter) below the margin glyph | at most 300 ms; still while the class holds; picked up along the arc reversed in 180 ms when it goes |
| `is-done` or `state-done` arrives | **Touchdown**: chalk goalposts about 24px tall under the check, in the pencil's chalk in the green ink, then end-zone hatching, diagonal strokes every 6px for 84px under them, one after another | drawn at 900 px/s; erased at the same speed when done goes |
| `state-error` arrives | **The fumble**: a chalk ball about 10x7px (an ellipse, a seam, three laces), drawn in the margin, then two decaying hops to rest just right of the bang | drawn at 900 px/s, then 180 + 120 ms of hops; erased when the error goes |

- **At rest, never replayed.** A record starts at its pane's state with every material at rest, so nothing is thrown
  on load. While `body.is-stale` is set (a cached desk restored), changes go straight to rest.
- **The margin only.** The hatch is chalk at the pencil's chalk tuning, and every stroke lies within the pane's
  first 36px, stops 8px above its bottom and crosses no word. The margin carries no text, so the `--board-max`
  ceiling (which protects text) does not apply there: at that ceiling cream chalk would be about 1.3:1 and
  invisible.
- **Rails.** A rail (under 90px wide) gets no flag, posts, hatch or ball.
- **Reduced motion.** Every material at rest at once: no arc, no hop, the strokes complete, and leaving is
  instant. Reduced motion is the only off switch (the issue's default decision): there is no separate setting.
- **The rules.** No colour literal, no page write and no `MutationObserver`. Materials move, and are drawn and
  erased, but never fade. Under `body.ink-off` none of them is shown: the plain table already carries each state.
- `inspect()` gives, per pane, `{flag: 'none'|'flying'|'resting'|'leaving', posts: 0..1, hatch: 0..1,
  ball: 'none'|'drawing'|'hopping'|'resting', flagBox, postsBox, hatchBoxes, ballBox}` (boxes `{x, y, r, b}` in
  viewport px, or null), with `throws`, `hops` and `rail`; and `strokes`, the live material strokes, and
  `geometries`, the renderer's count.

## Names

The skin's own strings and art name neither team nor league (#318's names decision): no logos, helmets, wordmarks,
mascots, league shield, jersey stripes or team typefaces. `playbook.js`, `skins/playbook/skin.css`, and the skin's
and each variant's title and why are checked for `nfl`, `browns`, `cleveland`, `logo`, `helmet` and `dawg`, comments
included. The palette keeps its shipped slug, title ('NFL Browns') and why.

## The plain look

Under `body.ink-off` (WebGL not measured as hardware, or `?ink=off`) the playbook is the one plain look every skin
shares, with the same table drawn as CSS by the layer's fallback: the running name underlined solid in the pen's
ink, the option route's underline dashed, the needs-you name tinted. No canvas, and three.js is never fetched.

## Decisions

From the laptop sitting (#400). One verdict so far:

- **Which parked concept next** (2026-10-02). None of the parked palette concepts (zen garden,
  observatory, darkroom, sonar) for now. The operator: *"the next thing we're going to explore is the 3d
  space ... Just assume it is a rainy day. And that it can be day or night, depending on what the local
  time is."* Built as the world, `/world` (#626, [fleet-world.md](fleet-world.md)).

#400's other questions are still open: the palette's title beside the playbook, the play sheet on
`sand`, whether reduced motion is enough of an off switch, the stick of chalk, and anything that reads
badly.
