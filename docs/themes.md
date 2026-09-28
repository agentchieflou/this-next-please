# CLI Theming — Terminal Palettes, Prompt Theming, and Project Colours

_The terminal a human opens tells them where they are._

## The Gallery

| Theme | Ground | Text | Muted | Accent | Dashboard | `why` |
|---|---|---|---|---|---|---|
| `greens` | `#0B1F14` | `#CDE6D2` | `#8DA493` | `#3FB950` | leaf-green panels, emerald accent stripe | calm and go; a leaf-green desk |
| `reds` | `#400000` | `#F2D9D9` | `#B79191` | `#FF5C5C` | deep maroon panels, coral accent stripe | the loud desk; a red ground where errors cannot hide behind the ground |
| `eye-relief` | `#2B2A27` | `#D6CDB8` | `#B6AE9C` | `#C9A227` | warm charcoal panels, gold accent stripe | for hour six; low blue, low glare, nothing pure white |
| `eye-relief-day` | `#F2ECDC` | `#3B3A34` | `#5C5A52` | `#8A6D1F` | warm cream parchment, brass accent stripe | the same idea for a bright room (light theme) |
| `nfl-browns` | `#311D00` | `#F2E8D9` | `#A79984` | `#FF3C00` | brown leather panels, orange accent stripe | Cleveland Browns: brown, orange, white |
| `dark` | `#14171A` | `#E3E7EA` | `#A5A9AC` | `#58A6FF` | slate panels, blue accent stripe | the neutral dark the page already had, now a name the terminal can share |
| `vanta-black` | `#000000` | `#C8C8C8` | `#929292` | `#E6E6E6` | true black ground, high-contrast monochrome panels | the true-black panel for OLED and pitch rooms |
| `matrix` | `#020A03` | `#3DF07A` | `#2CAD57` | `#00FF41` | black ground, glowing phosphor borders and accents | phosphor on black; the falling code screen |
| `blues` | `#0B1B33` | `#D6E4F7` | `#9BAABE` | `#4DA3FF` | midnight navy panels, cobalt accent stripe | deep ocean navy and slate |
| `sand` | `#EFE6D2` | `#3A3126` | `#60574A` | `#B9631E` | desert sand panels, copper accent stripe | warm desert solarized parchment (light theme) |
| `random` | generated | generated | derived | generated | seeded per project | a fresh, stable colour per project or per day; seeded |
| `none` | — | — | — | — | follows `prefers-color-scheme` | the terminal exactly as you had it (the default) |

### Secondary Text (`--muted`)

Secondary text (ticket, pane number, why line, footer counts, placeholders) is painted with `--muted`, and it
reads at 4.5:1 (WCAG 1.4.3) wherever it is drawn. `--muted` is no longer the terminal's bright black (`ansi[8]`,
which stays as it was in the terminal):

- **Built-ins** set `muted=` on the `Theme`: the values in the gallery, measured to hold 4.6:1 or better on
  `--bg`, `--panel`, `--select` and every composited panel of every skin variant drawn on that palette.
- **`random` and any other palette** without one derive it (`theme._muted`): `text` mixed toward `ground` at the
  largest weight, in steps of 0.01, that keeps 4.6:1 on `--bg`, `--panel` and `--select`.

`theme.check` rule 6 refuses a palette whose `--muted` falls under 4.5:1 on the ground or skin paper it is checked
against, and names the skin and both colours.

### The word on a state colour (`--on-*`)

A chip, a badge, a ticket's status and a rail's glyph write their word on a state colour (`--running`,
`--waiting`, `--human`, `--done`, `--idle`). The state colours are shared with the terminal and never change, so the
word's colour is chosen instead (#327): `theme.to_css` adds `--on-running`, `--on-waiting`, `--on-human`, `--on-done`
and `--on-idle`, each the first of `--text`, `--bg`, `#FFFFFF` and `#111111` that reads at 4.5:1 on its state colour,
or, if none does, the one that reads best. The `none` palette's values are written in `app.css :root` by the same
rule; white on its `--done` is 3.57:1, so none of them is white. A chip's age is lighter by weight, never faded.
The group glyph sits on `--muted` and writes in `--panel`, as the unsupervised chip does (rule 6 holds that pair).

`theme.check` rule 7 refuses a palette whose `--on-<role>` falls under 4.5:1 on its state colour, and names both.
A skin reads the five tokens and never sets them (`tests/test_fleet_skin_guard.py`).

### A word in a state colour (`-text`)

A word written *in* a state colour is text: the why line of a pane that errored or needs you, the transcript's
"exit 2", the question card's "it asked you:", a board cell's warning, farmstead's clear chips. Text reads at 4.5:1
(WCAG 1.4.3). The state colours are held to 3:1 (rule 2), the floor for a mark (WCAG 1.4.11), and they stay on
every border, outline, underline and disc, which are marks: a ring that changed colour because a word sits inside it
would be one more thing to translate. So the word gets its own colour (#328): `theme.to_css` adds `--running-text`,
`--waiting-text`, `--human-text`, `--done-text` and `--idle-text`. Each is the state colour itself where that
already reads at 4.5:1 on `--bg`, `--panel`, `--select` and every composited panel of every skin variant drawn on the
palette (`skins.panels_on`); otherwise it is the state moved toward `--text` in steps of 0.02 until it does
(`theme.role_text`), and `--text` itself if no step does. The server passes the panels, so a palette is served one
set of tokens, the same under every skin drawn on it. The move can be long where a ground is far from the text:
matrix's `--human` reads 3.87:1 on its green `--select`, and its word is `#9A995C`.

`app.css` writes every such word in its token, and a static test scans it and every skin's stylesheet for a bare
`color: var(--<state>)`, allowed only on the state's own `--on-<state>` disc (the needs-you rail). The plain page
(`none`) carries its tokens in `app.css :root`, chosen by the same rule on its grounds, and the OS dark scheme has
its own in the `prefers-color-scheme: dark` block: the light values read 2.3-3.2:1 on the dark grounds.

`theme.check` rule 8 refuses a palette whose `-text` token falls under 4.5:1 on the ground or a panel it is checked
against, and names both colours. Rule 9, **pressed ground**, refuses a palette whose `--text` falls under 4.5:1 on
`--select`, where a pressed control writes its word (the model picker's pill, the pressed tab, the pin); its hint
names the text, the select and the accent the select moved toward. A skin reads the ten `--on-*` and `-text` tokens
and never sets them.

### Focus, selection, pressed and "which project" (#339)

None of the four is ever a state colour. `--focus` is the palette's cursor when that reads at 3:1 on `--panel` and on
every panel the palette is drawn on, and is achromatic (HSV saturation up to 0.25) or at least 30 degrees of hue from
every chromatic state colour. Otherwise it is `--text` made neutral: the same value, saturation capped at 0.12.
Plain `--text` is not enough, because matrix's text is 4 degrees from its done green and sand's is 2 from its waiting
ochre. Of the built-ins only vanta-black keeps its cursor. The terminal's cursor is unchanged: this is the page's
token, and `theme.escapes` still paints `t.cursor`.

- **Keyboard focus** is a 2px `--focus` outline at offset 2 with a `--bg` halo out to 6px, a two-colour indicator. The
  ring then reads against its own halo whatever a skin draws beyond it: on farmstead daytime the wood is 1.5:1
  against sand's ring.
- **The selected pane** under ink wears three rings, `--bg`, `--focus` and `--bg`. The plain page keeps its 2px
  `--focus` ring.
- **A pressed control** (an open sidebar tab, the pressed pin and maximise) writes `--text` on `--select`, which rule
  9 holds at 4.5:1, with a 2px inset `--focus` ring. It is never an accent-coloured word. Under ink, notebook clears
  the fill, and the ring carries "pressed".
- **Which project.** A project's own accent (`theme.projects`) is used as chosen. With none, a pane is sent the
  palette's accent when it passes the `--focus` test on the palette the page is served on (a skin's variant base
  wins). Otherwise it gets the palette's `--muted` made neutral: matrix under voxel overworld #98AD9F, reds under
  Nether #B7A1A1, sand under farmstead daytime #605B54. On the plain page (`none`) no accent is sent at all. The
  tile's own left border paints the strip in `--focus`, `app.css :root` carries a `--focus` for light and one for
  dark, and no pane wears the done green `#3FB950` any more.

`theme.check` rule 10 refuses a palette whose `--focus` falls under 3:1 on the panel it is checked against, or sits
within 30 degrees of a chromatic state colour, and names the ring, the panel or the state.

## The Host Matrix

Every mechanism is gated by `color.enabled()`, so a pipe gets zero escape bytes and reports `mechanism: none`.

| Host (`console.host()`) | Live Recolour | Persist | Notes |
|---|---|---|---|
| `windows-terminal` | OSC 4 / 10 / 11 / 12 | Fragment (`agentdata.json`) | Full support: 16 ANSI slots, text, background, cursor |
| `conhost` (bare `cmd.exe`) | `SetConsoleScreenBufferInfoEx` via `ctypes` | `HKCU\Console` with `--persist` | Win32 console API updates the 16-colour table and repaints |
| `mintty` (Git Bash) | OSC 4 / 10 / 11 | Live hook only | Mintty renders ANSI though Python sees a pipe |
| `vscode` | OSC 4 / 10 / 11 | Live hook only | xterm.js supports standard dynamic colour escapes |
| `pycharm-terminal` | OSC 4 / 10 / 11 | Live hook only | JediTerm dynamic colour support |
| `tty` (Linux / macOS) | OSC 4 / 10 / 11 / 12 | Live hook only | Verified on CI |
| `pipe` | None | None | Byte-for-byte pure TOON without escape bytes |

## Commands

```bash
ad-theme list
ad-theme show greens
ad-theme gallery
ad-theme apply greens
ad-theme reset
ad-theme set greens --default
ad-theme set matrix --project C:/Users/you/repo
ad-theme unset --project C:/Users/you/repo
ad-theme install --hook
ad-theme install --prompt
ad-theme install --terminal
ad-theme uninstall --hook
ad-theme uninstall --prompt
ad-theme uninstall --terminal
```

## One Theme Per Project (Directory Hooks)

Zero-Python directory hooks let each repository on your machine display its own palette automatically:
- When you `cd` into a repo, the shell hook matches the directory prefix, applies the project's OSC palette escapes, and exports `AGENTDATA_PROJECT`, `AGENTDATA_TICKET`, and `AGENTDATA_PHASE`.
- Because the matching rules are pre-compiled into `hook.ps1`, `hook.sh`, and `hook.lua`, directory switching completes in under a single display frame without spawning `python.exe`.

## Startup Lines and Removal

Installing directory hooks or prompt integration adds a single marked line to your shell startup file:

| Shell | Startup File | Installed Marker | Removal Command |
|---|---|---|---|
| **PowerShell** (`pwsh`) | `$PROFILE` (`profile.ps1`) | `# agentdata directory theme hook` | `ad-theme uninstall --hook --shell pwsh` |
| **Git Bash / sh** | `~/.bashrc` | `# agentdata directory theme hook` | `ad-theme uninstall --hook --shell bash` |
| **cmd.exe** (Clink) | `%LOCALAPPDATA%\clink\oh-my-posh.lua` | `-- agentdata directory theme hook` | `ad-theme uninstall --hook --shell cmd` |
| **Oh My Posh** | (per shell profile) | `# agentdata theme prompt` | `ad-theme uninstall --prompt` |

Uninstall commands remove the marked line cleanly, leaving all user customizations untouched.

## Terminal Signals & Attention Management

CLI theming extends beyond colors to attention signals that notify humans without context switching:

- **OSC 9;4 Progress Indicator**: Long-running operations (`ui.progress`) emit standard OSC 9;4 progress bar escapes to `sys.stderr` for supported terminals (Windows Terminal, ConEmu). Standard output remains clean and pipe-safe.
- **Dynamic Tab Titles (OSC 2)**: Directory hooks update terminal tab titles to display `<project> · <ticket> · <phase>` so the human can tell multiple sessions apart at a glance.
- **Needs-Human Notifications**: Fleet notifications (`agentdata.fleet.notify`) emit terminal bell (`\x07`) and OSC 9 toast notifications when an agent reaches a human-intervention state (`needs_human` / `blocked`), respecting configured quiet hours.
- **Time-of-Day Scheduling**: Project themes support `--after HH:MM` and `--until HH:MM` time windows so projects can automatically switch between day (e.g. `eye-relief-day`) and night (e.g. `eye-relief`) palettes.

## Starship vs. Oh My Posh

While `agentdata` provides native Oh My Posh integration for high-fidelity prompt glyphs and palette inheritance, Starship is supported via `agentdata.starship.generate_config()`:
- Oh My Posh remains the primary recommendation on Windows due to direct Clink / ConHost support, native transient prompt support, and fine-grained palette-segment bindings.
- Starship provides cross-platform Rust speed and identical `AGENTDATA_PROJECT` / `AGENTDATA_TICKET` segment rendering.

## Skins (Desk on Windows)

A **skin** is one more stylesheet over the same DOM: the approved grid with CSS and hand-drawn SVG swapped in. A skin that needs a page change is not a skin.

**Served, not fetched (#345).** Every page but `/probe` is served wearing the chosen palette and skin: the palette's tokens as `<html data-theme="custom" style>`, the skin's stylesheet as a `<link data-skin>` in the head and `<body data-skin data-skin-variant>`, so the first frame is never the system palette or the skin just replaced. A skinned page is also served `body.ink-off`, the legible plain look, until the ink layer draws (desk-ink.md §Following the page); every skin's band text is keyed on `:not(.ink-off)`, which would read 1.30:1 on farmstead:daytime before the canvas is there.

### The Skin Contract
- **DOM Stability**: A skin may only alter CSS custom properties, backgrounds, borders, and decorative sprites. It must never require HTML markup changes or alter interactive element IDs.
- **Pixel-Art Invariant**: Textures and sprites are 100% original, hand-authored SVG `<rect>` pixel art committed directly to the repo. Zero raster images or base64 bitmaps are allowed.
- **Size Budget**: Each skin directory must remain under 150 KB (including any font and license files).
- **Accessibility Fallbacks**: A skin that makes panels translucent must render them opaque under `@media (prefers-reduced-transparency: reduce)`, and a skin that introduces movement must stop it under `@media (prefers-reduced-motion: reduce)`. A skin that introduces no movement needs no rule of its own: `app.css` carries a global reduced-motion rule that covers everything the page draws, and a per-skin copy would be boilerplate asserting itself.

  Reduced motion is testable and tested. **Reduced transparency is not, on any engine we have**: Chromium did not ship `prefers-reduced-transparency` until well after the build the browser tests drive, so the query never matches and the fallback never fires there — and it will not fire in an older Edge or JCEF either. The rule is written and asserted to exist, and a viewer whose browser does not know the query gets the translucent panels regardless of their OS setting. That is a limitation of the mechanism, not something the skins can work around; it is written down here rather than assumed away, and `glass` is the only skin it applies to.
- **Asset URLs carry the token.** A relative `url()` inside a stylesheet does not inherit the query string the stylesheet was fetched with, and everything but `/api/ping` needs this run's token — so a skin asking for its own `sprites.svg` was refused with a 403, silently, and the chips simply had no sprite. `serve._static` puts the token on every relative `url()` it serves in a stylesheet (before the fragment). A skin references its art relatively and does not think about it.
- **Composited Contrast**: The effective composited panel contrast must pass WCAG floors (text ≥ 4.5:1, status roles ≥ 3:1). A skin whose pane is not one colour — glass, over its mesh — declares the **darkest and lightest** colour the pane composites to (`skins.composited_range`, from the variant's own `mesh` and `fill`) and is checked at both; a test reads the stylesheet to prove the blobs and the fill it paints are the numbers it declared, and a browser test samples the rendered pane to prove the pixels stay inside that range and vary across it.
- **A skin that repaints a surface repaints its scrollbar** (#181). `app.css` draws every scrollbar from two custom properties mixed from the palette — `--scroll-thumb` and `--scroll-thumb-hover`, the track always the surface beneath — and writes them into both `scrollbar-color` and the legacy `::-webkit-scrollbar` rules, so the two mechanisms cannot disagree. A skin overrides the **thumb** on `body[data-skin]` and only recolours it (glass a pale or dark translucent thumb, voxel stone, farmstead wood); it never declares `scrollbar-color` of its own, and a test reads the stylesheets to make sure.

### Available Skins

| Skin | Inspiration & Materials | HIG Rule Applied |
|---|---|---|
| `none` | Default clean HIG interface | Clean baseline |
| `glass` | Drawn by the ink layer (#254): frosted panes over a lit **mesh** of three saturated blobs per variant, a one-pixel edge and a glint that catch the light, a second, more opaque layer for the cards on a pane ([skin-glass.md](skin-glass.md)). Plain CSS where WebGL is not measured as hardware (#257). | *Materials*: translucent material blurs what is behind it and adapts to light and dark while keeping content legible. |
| `voxel` | Drawn by the ink layer (#256): a ground of 32px voxels, every pane a lit slab with its accent strip as a column of cubes, and a status stack per pane ([skin-voxel.md](skin-voxel.md)). Plain CSS where WebGL is not measured as hardware (#257). Inspired by block-building games; zero copied assets. | *Visual Design*: bold tactile geometry and unmistakable state indicators across a room. |
| `farmstead` | Drawn by the ink layer (#255): warm cream paper, lit wooden frames and planks, and 5 crop-stage sprites (seed, sprout, sun, bloom, wilted) carrying state beside the chip's word. Plain CSS where WebGL is not measured as hardware (#257). Inspired by pixel farming games; zero copied assets. | *Color & Redundancy*: never colour alone; crop stages provide a second redundant carrier for agent status. |
| `graph` | Graph paper drawn by the ink layer (#253): a 28px grid on quad-ruled stock (Engineering) or white lines on a cyanotype (Blueprint), a mechanical pencil, ruled marks, and every agent's hour plotted on the grid ([skin-graph.md](skin-graph.md)). Plain CSS where WebGL is not measured as hardware. | *Charts*: the plotted hour is a chart with its axis on the grid, and text crosses a heavy line at 4.5:1. |
| `legalpad` | A yellow legal pad drawn by the ink layer (#251): canary stock, blue rules on the page's 28px baseline, a double red margin down every pane and a gummed band across the top; state is drawn on it in pencil, pen, marker and an orange-pink highlighter ([desk-ink.md](desk-ink.md) §The legal pad). Plain CSS where WebGL is not measured as hardware. | *Color & Redundancy*: every state is a shape as well as an ink -- an outline, a loop, a strike, a check, a bang. |
| `napkin` | Napkin notes drawn by the ink layer (#252): quilted two-ply stock, a felt tip that bleeds along the emboss, and a coffee ring under a pane idle a long time ([skin-napkin.md](skin-napkin.md)). Plain CSS where WebGL is not measured as hardware. | *Composited contrast*: the text is checked on the stock and on the coffee ring's rim, the darker end of its panel. |
| `notebook` | The first skin drawn with ink (#249, #250): white stock with blue rules and a red margin by day, charcoal stock and gel inks by night, and state drawn in pencil, pen, marker and highlighter ([skin-notebook.md](skin-notebook.md)). Plain CSS where WebGL is not measured as hardware. | *Color & Redundancy*: the highlighter is multiplied into the day page and screened onto the night one, and every state is a shape as well as an ink. |
| `playbook` | A coach's chalkboard drawn by the ink layer (#389): brown slate, every agent an O, its turn a route in orange chalk, and the state grammar in X's and O's ([skin-playbook.md](skin-playbook.md)). Plain CSS where WebGL is not measured as hardware. Names no team or league (#318). | *Color & Redundancy*: every state is a shape as well as an ink -- a route, a dashed option route, a bar and an X, a check. |

A variant re-colours the surfaces, and its palette colours the states: a chip's word and glyph, a crop
stage and every mark of the state grammar ([desk-ink.md](desk-ink.md) §The state grammar across skins)
mean the same thing in every world, but their colour is the world's, so Voxel Nether's needs-you and
error chips (and its error marks) are its palette's yellow `--human` while its pane accent is red (#334;
the accent is #339).

### Skins and their worlds

A skin has **variants**, and each variant names the palette it is drawn against. The asymmetry is
the model: every skin has palette variants, and no palette needs to know that any skin exists. A
texture is designed for a ground — Nether is red because the art is red — so **choosing a skin
chooses the palette with it**, in the same `~/.agentdata/config.json` the terminal reads. While a
skin is on, the palette picker shows what is being rendered and says why it is not taking
instructions; turning the skin off hands it back.

That binding is what makes the accessibility claim checkable. With the two pickers independent
there were eleven palettes against four skins of possible pairings and nothing had measured most of
them; bound, the set of reachable combinations *is* the set of variants below, and
`tests/test_fleet_skins.py` runs `theme.check` over every row — text ≥ 4.5:1 and ≤ 19:1, each status
role ≥ 3:1, `ok`/`fail` at least 30° apart in hue — against the **composited panel**, the colour the
text is actually read on once the frost or the texture has been painted, rather than against the
palette's own ground — and for glass, whose pane composites to a range over its mesh, at both ends
of that range (#182). A browser test then applies each variant for real and compares the panel
colour the engine computes with the one declared here, so a variant cannot be measured in Python and
missing from the stylesheet.

Selected as `<skin>` or `<skin>:<variant>`; a bare skin name means its default variant, and an
unknown variant falls back to the default rather than taking the page down.

**Auto: following the system's appearance (#342).** A skin with a light and a dark variant can also
be chosen as `<skin>:auto`, "Auto" in the settings picker, and the desk then follows the system's
light or dark appearance, switching live without a reload. Four skins can follow: `notebook`
(`light` / `dark`), `glass` (`frost` / `smoke`), `graph` (`engineering` / `blueprint`) and `farmstead`
(`daytime` / `cave`). Legalpad and napkin are light only and voxel is dark only, so their `auto`
means the default variant, as an unknown variant does, and is saved as that variant.

- **What is saved:** `theme.skin` is `<skin>:auto`, verbatim. Each side renders exactly what
  choosing that variant renders: the same tokens, `--on-*` and `-text` included.
- **What the terminal gets:** `theme.default` is the skin's default variant's palette, since a
  terminal cannot follow the system (`notebook:auto` saves `eye-relief-day`).
- **The first frame:** the served page carries both sides' tokens under `prefers-color-scheme`, and
  the variant is picked as `common.js` runs, so the page is right in either appearance before its
  first answer.
- **Which project, on either side:** the server cannot know the side, so a pane no project
  coloured is sent a mark only when it passes the `--focus` test on both sides' panels and states.
  None of the four default variants' marks does, so under `auto` such a pane is sent no accent, and
  the tile's own border paints the strip in the side's `--focus`. A project's own accent is used as
  chosen.

| Name | Variant | Base palette | Ground | Composited panel | Text contrast | Why |
|---|---|---|---|---|---|---|
| `glass:smoke` | Smoke *(default)* | `dark` | `#14171A` | `#181D24` … `#273D57` | 8.9:1 at the worse end | neutral graphite behind the frost |
| `glass:azure` | Azure | `blues` | `#0B1B33` | `#11213B` … `#1D3F56` | 8.6:1 at the worse end | cold blue depth, the darkest of the three |
| `glass:noir` | Noir | `vanta-black` | `#000000` | `#0A0A0A` … `#202020` | 9.7:1 at the worse end | near-black, for a room with the lights off |
| `glass:frost` | Frost | `eye-relief-day` | `#F2ECDC` | `#DED4B8` … `#F3EDDD` | 7.7:1 at the worse end | the light one: warm paper under the same frost |
| `voxel:overworld` | Overworld *(default)* | `matrix` | `#020A03` | `#1E221E` | 10.7:1 | grass, stone and daylight |
| `voxel:nether` | Nether | `reds` | `#400000` | `#2A1512` | 12.9:1 | netherrack and firelight |
| `voxel:end` | The End | `vanta-black` | `#000000` | `#16121C` | 11.0:1 | endstone and void |
| `farmstead:daytime` | Daytime *(default)* | `sand` | `#EFE6D2` | `#E8DDC3` | 9.4:1 | sunlight on paper and wood |
| `farmstead:cave` | Cave | `eye-relief` | `#2B2A27` | `#33302A` | 8.3:1 | lamplight underground |
| `farmstead:rainy` | Rainy day | `blues` | `#0B1B33` | `#16243D` | 12.0:1 | a wet afternoon indoors |
| `graph:engineering` | Engineering *(default)* | `eye-relief-day` | `#F2ECDC` | `#F3F6EC` | 10.4:1 | green quad-ruled pad, graphite and a blue pen |
| `graph:blueprint` | Blueprint | `blues` | `#0B1B33` | `#123A66` | 8.9:1 | white lines on a cyanotype |
| `legalpad:canary` | Canary *(default)* | `eye-relief-day` | `#F2ECDC` | `#FCF3A6` | 10.1:1 | canary stock, and an orange-pink highlighter that still reads on it |
| `napkin:diner` | Diner *(default)* | `eye-relief-day` | `#F2ECDC` | `#E3DAD0` … `#FBF9F4` | 8.3:1 at the worse end | a white napkin from the counter, and a blue ballpoint |
| `napkin:kraft` | Kraft | `sand` | `#EFE6D2` | `#E0D4C2` … `#F2EADA` | 8.7:1 at the worse end | an unbleached napkin, for a warmer page |
| `notebook:light` | Notebook *(default)* | `eye-relief-day` | `#F2ECDC` | `#FBFBF6` | 11.0:1 | white stock, blue rules, a red margin |
| `notebook:dark` | Night notebook | `dark` | `#14171A` | `#1B1E25` | 13.4:1 | charcoal stock and gel inks, the highlighter screened |
| `playbook:chalkboard` | Chalkboard *(default)* | `nfl-browns` | `#311D00` | `#2B1B08` … `#40301D` | 10.4:1 at the worse end | brown slate, cream and orange chalk |
| `playbook:playsheet` | Play sheet | `sand` | `#EFE6D2` | `#E9DFC9` … `#F7F1E3` | 9.6:1 at the worse end | a printed play sheet: graphite and a burnt-orange pen |

### Every palette's look

Which looks are drawn on each palette, the signature concept planned or parked for it, or why it stays a palette on
its own (#393's `skins.PALETTE_ONLY`; epic #294). **Skins drawn on it** lists the variants merged today (skin title ·
variant title), or `palette only` when there are none. **Status** is the concept's: `built`, `planned`, `parked`, or
`palette only`. A status says what has merged, never ahead of it: #391, #395, #397 and #398 set their palette's status
to `built`, and #389, #392, #394 and #396 add their variants, when they merge. `tests/test_fleet_skins.py` holds the
rows to `skins.py`: every built-in palette has one, a palette any variant is drawn on is never `palette only`, and
every `PALETTE_ONLY` palette is.

| Palette | Skins drawn on it | Signature concept | Status |
|---|---|---|---|
| `nfl-browns` | Playbook · Chalkboard | a coach's chalkboard: O's, routes, a flag (Playbook, #389-#392) | `built` |
| `matrix` | Voxel · Overworld | a screen whose code rain settles into the pane (Phosphor, #394, #395) | `planned` |
| `greens` | `palette only` | a circuit board: solder mask, silkscreen, a pulse per line (#396, #397) | `planned` |
| `eye-relief` | Farmstead · Cave | a lamp over charcoal stock (Notebook · Lamplight, #398) | `planned` |
| `sand` | Farmstead · Daytime, Napkin notes · Kraft, Playbook · Play sheet | a zen garden: raked sand, a stone per agent, one rake line per transcript line | `parked` |
| `vanta-black` | Glass · Noir, Voxel · The End | an observatory: a star field, a meteor per line, a constellation when done, at least 97% true-black pixels | `parked` |
| `reds` | Voxel · Nether | a darkroom: a safelight, prints in the tray, a print hung when done | `parked` |
| `blues` | Glass · Azure, Farmstead · Rainy day, Graph paper · Blueprint | sonar: one ping ring per line | `parked` |
| `dark` | Glass · Smoke, Notebook · Night notebook | none: the neutral ground the paper skins share | `built` |
| `eye-relief-day` | Glass · Frost, Graph paper · Engineering, Legal pad · Canary, Napkin notes · Diner, Notebook · Notebook | none: the neutral ground the paper skins share | `built` |
| `random` | `palette only` | none: generated per project, so no skin can be designed for an unknown ground | `palette only` |

Every concept keeps the same rules, whichever palette it is drawn on:

- **Motion only on an event**: one-shot, at most 320 ms, never looping. Reduced motion draws the end state.
- **The render contract**: a skin is drawn over the same DOM and never changes it ([desk-ink.md](desk-ink.md)).
- **`theme.check` pairs** at both ends of a composited panel and plain, and 4.5:1 for any ink that colours text or
  that text is read through.
- **The plain fallback**: `body.ink-off` draws the same mark table as CSS, legibly, wherever WebGL is not measured
  as hardware.
- **Names** (#318): a new skin's strings and art use names of our own. Names already shipped (the palette title
  'NFL Browns', the voxel worlds) stay, and the docs may name the inspiration.

## An Agent Never Sees This

CLI theming is strictly for human awareness. An agent (such as Luna or an autonomous subagent) never receives escape bytes or palette noise:
- Every terminal recolouring command checks `color.enabled()`. When `stdout` is piped or redirected, all escape sequences are suppressed.
- `ad-theme list`, `show`, `gallery`, and all doctor rows output pure TOON on `stdout` when piped, adhering strictly to the contract of Issue #71.
- Directory hooks write escapes directly to the interactive terminal console and never pollute tool call outputs or piped subprocess stdout.



