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

## Names

The skin's own strings and art name neither team nor league (#318's names decision): no logos, helmets, wordmarks,
mascots, league shield, jersey stripes or team typefaces. `playbook.js`, `skins/playbook/skin.css`, and the skin's
and each variant's title and why are checked for `nfl`, `browns`, `cleveland`, `logo`, `helmet` and `dawg`, comments
included. The palette keeps its shipped slug, title ('NFL Browns') and why.

## The plain look

Under `body.ink-off` (WebGL not measured as hardware, or `?ink=off`) the playbook is the one plain look every skin
shares, with the same table drawn as CSS by the layer's fallback: the running name underlined solid in the pen's
ink, the option route's underline dashed, the needs-you name tinted. No canvas, and three.js is never fetched.
