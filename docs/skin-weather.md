# Weather: a sky over the desk, and weather that moves

_The weather genre ([themes.md](themes.md) §Genres). A skin that draws with the ink layer
([desk-ink.md](desk-ink.md)). Chosen like any look: `theme.look` is `weather:rain`, `weather:clear`
or `weather:cloud` with `theme.mode` the side, resolving to `theme.skin` `weather:<variant>`, from
the settings page or `POST /api/theme {look}`. Each weather is drawn on the palette that is its light: the rain on `slate`
and the cloud cover on `overcast`, two grey palettes brought for it; the sun on `sand`; the night on
`vanta-black`._

The operator's ask, which this page answers: *when I select rainy day, I want it to feel like a rainy
day, not a basic blue with the notebook's animations.* So the rain falls, across the panes, all the
time the look is on; the sun's rays turn; the clouds drift; the stars twinkle. What the notebook does
with a hand, the weather does with a sky.

| File | Is |
| --- | --- |
| `agentdata/fleet/static/ink/skins/weather.js` | the mark table (the grammar, drawn without a hand), the sky shader with a weather per kind, the rain shader, each pane's sheet, the two cues, the rain's own signs (`expresses`) and the tick |
| `agentdata/fleet/static/skins/weather/skin.css` | each weather's colours and numbers as custom properties, and the stand-aside; nothing it paints (#257) |
| `agentdata/fleet/skins.py` (`weather`, `GENRES["weather"]`) | the four variants, their palettes, each paper and the rain's pair, the inks `theme.check` holds |
| `agentdata/theme.py` (`SLATE`, `OVERCAST`) | the two palettes, greyer than `blues` by `theme.saturation` |
| `tests/test_fleet_ink_weather.py` | everything on this page |

## The sky

With ink on, three.js shades one quad the size of the viewport behind everything (`ground`), a
gradient from `--wx-sky-top` to `--wx-sky-bottom` and, by `--wx-kind`, the weather in it. The
noise the sky is made of is a 256px tileable texture built once on the CPU and sampled, not
computed per pixel, so a frame is cheap on a machine without a GPU (CI's software GL renders one
in about the time a farm frame takes):

| Kind | Look | Palette | What the sky does |
| --- | --- | --- | --- |
| 0 | Rainy day *(default)* | `slate` | a heavier band of cloud drifts through the grey; the rain (below) falls across everything |
| 1 | Sunny day | `sand` | the sun at the top right in `--wx-sun`, and rays in `--wx-ray` at `--wx-ray-alpha` that turn slowly about it |
| 2 | Cloudy | `overcast` | cloud cover in `--wx-cloud` at `--wx-cloud-alpha`, shaded underneath in `--wx-cloud-shade`, drifting left to right at nine pixels a second |
| 3 | Starry night | `vanta-black` | stars in `--wx-star`, one in about every fourth 22px cell, each twinkling at its own rate; a meteor in `--wx-meteor` every nine seconds, gone in 0.7 |
| 0 | Showers | `overcast` | the rainy day's light side: the same rain in daylight greys, the streak darkening the pale paper |
| 2 | Dusk | `slate` | the cloudy look's dark side: cloud cover at dusk over the rainy day's greys |

The picker offers three looks, each with a light and a dark side (themes.md §Genres): *Rainy day*
(Showers by day, Rainy day by night), *Clear sky* (Sunny day, Starry night) and *Cloudy* (Cloudy,
Dusk); the side toggle picks, and *Auto* follows the system's appearance (#342).

## The paper

Each pane is a sheet of `--paper` laid on the sky (`frame`), with a one-pixel rim in `--wx-rim`
behind it. The sheet is opaque, so the sun, the cloud and the stars never show through a pane and
its panel is one colour, checked by `theme.check` on every ink. The rain is the exception.

## The rain

The rain is drawn twice by one shader with one set of uniforms: a sheet between the panes (`paper`)
and a quad over each pane's sheet (`frame`), because the layer paints every frame after the paper.
Two sheets of streaks fall at two speeds, the nearer faster and longer, each column of each sheet
with its own phase and gap, at `--wx-drop` and at most `--wx-drop-alpha` at a streak's core.
The canvas is behind the page, so the rain falls under the words and over the sheet: weather on the
desk, not a tint of it.

That is why the rainy day's panel is a pair (`skins.py`, `composited_panel`): `--paper` at the dark
end and, at the light end, the paper under a streak at its peak alpha,
`theme.mix(paper, --wx-drop, --wx-drop-alpha)`, which the test recomputes. The words, the muted
text, every state colour and every ink are held at both ends. The highlighter (`#635618`) is the
palette's amber darkened until the name keeps 4.5:1 through its screen on the wet end.

## The moments

Two cues (`cues`, [desk-ink.md](desk-ink.md) §Effects), each one-shot and done within 320 ms:

| Cue | On | Element | What happens |
| --- | --- | --- | --- |
| `lightning` | arrive | `#grid > .tile.state-error` | on the rainy day, the sky and the rain go `--wx-flash` at 0.7 and fall back over 320 ms; on any other weather nothing, since lightning belongs to the rain |
| `clearing` | arrive | `#grid > .tile:is(.state-done, .is-done)` | on the sunny day, the rays brighten by 60% and fall back over 320 ms; nothing elsewhere |

Under reduced motion neither plays (`api.reduced`), and the played count still rises, so a test can
see the cue arrived.

## The rain's own signs

On *Rainy day* and *Showers* the states are weather, not marks ([desk-ink.md](desk-ink.md) §The state
grammar across skins, `expresses`): the operator's ask, *animations in weather should be weather
related*. Each pane's rain quad has uniforms of its own, eased toward what the pane's classes want
over 320 ms (at once under reduced motion):

| Sign | Entries | On | What the rain does |
| --- | --- | --- | --- |
| `squall` | `needs_name`, `needs_q`, `needs_card` | `.needs-human` | the rain over that pane thickens: a third sheet of streaks, faster, longer and leaning harder, never past the streak alpha |
| `puddle` | `running` | `.state-running` | the pane runs with water: four rings spread from hashed points inside it and fade as they go, each on its own phase, in `--wx-drop` |
| `lightning` | `error_bang` | `.state-error` arrives | the cue above; and **thunder**, a 1.6 s roll of low noise, when the page's chime is on (`#chime` pressed, the operator's own switch for sound; `played.thunder` counts it). The reason stays outlined in marker, a mark |
| `drying` | `done` | `.is-done`, `.state-done` | the rain fades off that pane's sheet, and its puddles with it |

The sun, the cloud and the stars keep every row of the grammar. Under `body.ink-off` the rainy
variants hand the plain page the grammar's rows too, since there is no rain to speak with. The
squall and the puddles never pass `--wx-drop-alpha`, so the pair's wet end (`composited_panel`)
is the same and every word holds through them. `inspect().panes[repo]` gives `{squall, ripple,
dry}`, each 0 to 1.

## Motion

The weather is the one genre that moves while it is on ([themes.md](themes.md) §Genres): `tick`
advances the sky's clock by the frame's time, asks for a frame, and answers `true` for another. The
layer stops asking under `prefers-reduced-motion` (its `instant()`), and the module then holds the
clock at zero, asks for no frame unless the look itself changed, and draws the weather once and
still: streaks fixed in the air, the sun at rest, the
clouds parked, the stars lit. Under `body.ink-off` there is no canvas and no weather: the plain page
in the look's palette, with the mark table drawn as plain CSS.

## The marks

The state grammar ([desk-ink.md](desk-ink.md) §The state grammar across skins), drawn with no hand
(`hand: false`) at an even pressure, a shade quicker than the notebook: an idle pane's dashed
outline in pencil, the running name underlined in pen with the line growing per transcript line,
the needs-you name and question in highlighter with the card looped in marker, an error's reason
outlined in marker and its bang in red, a done check in green -- on the sun, the cloud and the
stars. On the rain those states are the rain's own signs (above), and only the reason's outline,
the answered choice, the stale note, a finding and the header's count stay marks.

## Names

The skin's own strings and art name no place, no season and no brand: a rainy day, a sunny day,
cloudy, a starry night (#318).
