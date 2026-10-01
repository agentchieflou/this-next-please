# The gridiron

The field itself. Choosing **Gridiron** on /settings (the Football genre, [themes.md](themes.md) §Genres) puts the
desk on turf: mown stripes, yard lines and hash marks across the page, every pane a stretch of it, and the football
genre's states signalled the way a field signals them rather than with the notebook's pen and highlighter -- the
operator's ask that relaxed the state grammar ([desk-ink.md](desk-ink.md) §The state grammar across skins,
`expresses`). The playbook is the coach's board for the same game; this is the game.

| File | Holds |
| --- | --- |
| `agentdata/fleet/skins.py` `SKINS["gridiron"]`, `GENRES["football"]` | the skin, its two sides, their palettes, the turf's pair and the inks `theme.check` holds |
| `agentdata/fleet/static/ink/skins/gridiron.js` | `expresses`, the mark table, the turf shader and each pane's lines and moments |
| `agentdata/fleet/static/skins/gridiron/skin.css` | the field's colours as custom properties, the margin and the pitch; nothing it paints (#257) |
| `tests/test_fleet_ink_gridiron.py` | the checks below |

## Variants

| Variant | Palette | Turf (darkest … lightest) | Why |
| --- | --- | --- | --- |
| `gridiron:nightgame` *(default, the dark side)* | `greens` | `#0E3418` (`--paper`) … `#183D1F` (`--turf-max` = `--yard`) | turf under the lights: chalk lines, a yellow first-down line |
| `gridiron:daygame` *(the light side)* | `eye-relief-day` | `#C2DDB5` (`--turf-max` = `--yard`) … `#D6EACB` (`--paper`) | a pale field by day: graphite and an amber pen |

The turf is a pair (`composited_panel`): the darker mown stripe and the lighter, and every word, the muted text,
each state colour and each ink is held by `theme.check` at both ends. The yard line is the pair's lighter end on the
night field and its darker end by day, so a line under a word costs the word nothing, and every pixel the shader
paints is clamped per channel to the pair.

| Pair (night game) | at `#0E3418` | at `#183D1F` |
| --- | --- | --- |
| text `#CDE6D2` | 10.40:1 | 9.18:1 |
| `--muted` `#8DA493` (#325) | 5.16:1 | 4.56:1 |
| pencil `#D6E0D3` (chalk) | 10.15:1 | 8.96:1 |
| pen `#FFD54A` | 9.76:1 | 8.61:1 |
| red and marker `#F85149` | 4.11:1 | 3.63:1 |
| green `#7EE787` | 8.97:1 | 7.92:1 |

| Pair (day game) | at `#C2DDB5` | at `#D6EACB` |
| --- | --- | --- |
| text `#3B3A34` | 7.77:1 | 8.96:1 |
| `--muted` `#5C5A52` | 4.71:1 | 5.43:1 |
| pencil `#5C5A52` | 4.71:1 | 5.43:1 |
| pen `#8A6D1F` | 3.34:1 | 3.85:1 |
| red and marker `#A82D2D` | 4.65:1 | 5.36:1 |
| green `#2A733E` | 3.95:1 | 4.56:1 |

The lines are decoration, not inks: `--gi-first` (`#FFD54A` by night, `#8A6D1F` by day) and `--gi-scrimmage`
(`#6FB3FF`, `#2F5F9E`) lie between the transcript's 28px rows, never under a word. No word is written in the pen or
the red: the finding's words and the header's count are in the pencil's chalk.

## The field's signs

What the module `expresses` (both sides), each a class the page already sets and each a shape as well as a colour,
beside the page's own chip and word:

| Sign | Entries | On | What the field does |
| --- | --- | --- | --- |
| `drive` | `running` | `.state-running` | the line of scrimmage, 2px in `--gi-scrimmage` across the pane 6px under its head, and the first-down line in `--gi-first` that advances one row (28px, a yard line) per transcript line at 240 px/s, capped by the pane's height; a waiting-approval or needs-you pane keeps the scrimmage line (the play is live) with no first-down line |
| `flag` | `needs_name`, `needs_q`, `needs_card` | `.needs-human` | the penalty flag: a 14x10px cloth with a knot in `tokens.waiting` thrown from the head's right end along an arc with 1.5 turns, landing in the pane's 36px gutter in at most 300 ms, picked up in 180 ms when the class goes |
| `fumble` | `error_bang`, `error_box` | `.state-error` | the ball: an ellipse, a seam and three laces drawn in the gutter at 900 px/s, then two decaying hops to rest; erased when the error goes |
| `touchdown` | `done` | `.is-done`, `.state-done` | goalposts about 24px tall in the green ink under the pane's number, then end-zone hatching every 6px for 84px under them, at 900 px/s; erased at the same speed when done goes |

The rows the notebook would draw for those entries are handed to the plain page only: under `body.ink-off` `marks`
returns the whole grammar, since there is no field to sign with. What stays a mark with the ink on: the idle name
underlined in pencil, the option route (waiting approval) dashed in the pen, a blocked name's bar and red cross, the
answered choice's pen ellipse and strike, the stale note, a finding's ellipse and words, the header's count.

- **At rest, never replayed.** A record starts at its pane's state with every material at rest; while `body.is-stale`
  holds, changes go straight to rest. A rail (under 90px wide) gets no lines and no moments.
- **Reduced motion.** The first-down line sits at its goal, the flag lands at once, the strokes are complete.
- **The rules.** No colour literal, no page write, no `MutationObserver`. The line count is read off the pane each
  tick (`.transcript > li`), never kept.
- `inspect()` gives, per pane, `{flag, posts, hatch, ball, throws, hops, rail, scrimmage, first, drive: {lines, at,
  to, live}, flagBox, postsBox, hatchBoxes, ballBox}` with `scrimmage` and `first` the lines' y within the pane or
  null when hidden; and `builds`, `top` (the first row under the header), `strokes`, `geometries`.

## The turf

The `paper` hook draws the page as one full-viewport quad at `api.order.paper`, built when the skin arrives, on a
resize and on a palette change: stripes every 140px (five rows) alternating `--paper` and `--turf-max` with a
blade-level grain, a yard line in `--yard` at each stripe's edge, 10px hash marks every 28px at a third and two
thirds of the width, from the first row under the header. No yard numbers, no words, no logos, nothing moves.

## Names

The skin's own strings and art name neither team nor league (#318): no logos, helmets, wordmarks, mascots, league
shield, jersey stripes or team typefaces. `gridiron.js`, `skins/gridiron/skin.css`, and the skin's and each
variant's title and why are checked for `nfl`, `browns`, `cleveland`, `logo`, `helmet` and `dawg`.

## The plain look

Under `body.ink-off` the gridiron is the plain look every skin shares, with the whole grammar drawn as CSS by the
layer's fallback: the running name underlined in the pen, the needs-you name tinted, the question card outlined in
the marker, the check and the bang plain. No canvas, and three.js is never fetched.
