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

| Variant | Palette | Board (`--paper` … `--board-max`) | Why |
| --- | --- | --- | --- |
| `playbook:chalkboard` *(default)* | `nfl-browns` | `#2B1B08` … `#40301D` | brown slate, cream and orange chalk |

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

## Names

The skin's own strings and art name neither team nor league (#318's names decision): no logos, helmets, wordmarks,
mascots, league shield, jersey stripes or team typefaces. `playbook.js`, `skins/playbook/skin.css`, and the skin's
and each variant's title and why are checked for `nfl`, `browns`, `cleveland`, `logo`, `helmet` and `dawg`, comments
included. The palette keeps its shipped slug, title ('NFL Browns') and why.

## The plain look

Under `body.ink-off` (WebGL not measured as hardware, or `?ink=off`) the playbook is the one plain look every skin
shares, with the same table drawn as CSS by the layer's fallback: the running name underlined solid in the pen's
ink, the option route's underline dashed, the needs-you name tinted. No canvas, and three.js is never fetched.
