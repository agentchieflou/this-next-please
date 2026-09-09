# CLI Theming — Terminal Palettes, Prompt Theming, and Project Colours

_The terminal a human opens tells them where they are._

## The Gallery

| Theme | Ground | Text | Accent | Dashboard | `why` |
|---|---|---|---|---|---|
| `greens` | `#0B1F14` | `#CDE6D2` | `#3FB950` | leaf-green panels, emerald accent stripe | calm and go; a leaf-green desk |
| `reds` | `#400000` | `#F2D9D9` | `#FF5C5C` | deep maroon panels, coral accent stripe | the loud desk; a red ground where errors cannot hide behind the ground |
| `eye-relief` | `#2B2A27` | `#D6CDB8` | `#C9A227` | warm charcoal panels, gold accent stripe | for hour six; low blue, low glare, nothing pure white |
| `eye-relief-day` | `#F2ECDC` | `#3B3A34` | `#8A6D1F` | warm cream parchment, brass accent stripe | the same idea for a bright room (light theme) |
| `nfl-browns` | `#311D00` | `#F2E8D9` | `#FF3C00` | brown leather panels, orange accent stripe | Cleveland Browns: brown, orange, white |
| `dark` | `#14171A` | `#E3E7EA` | `#58A6FF` | slate panels, blue accent stripe | the neutral dark the page already had, now a name the terminal can share |
| `vanta-black` | `#000000` | `#C8C8C8` | `#E6E6E6` | true black ground, high-contrast monochrome panels | the true-black panel for OLED and pitch rooms |
| `matrix` | `#020A03` | `#3DF07A` | `#00FF41` | black ground, glowing phosphor borders and accents | phosphor on black; the falling code screen |
| `blues` | `#0B1B33` | `#D6E4F7` | `#4DA3FF` | midnight navy panels, cobalt accent stripe | deep ocean navy and slate |
| `sand` | `#EFE6D2` | `#3A3126` | `#B9631E` | desert sand panels, copper accent stripe | warm desert solarized parchment (light theme) |
| `random` | generated | generated | generated | seeded per project | a fresh, stable colour per project or per day; seeded |
| `none` | — | — | — | follows `prefers-color-scheme` | the terminal exactly as you had it (the default) |

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

### The Skin Contract
- **DOM Stability**: A skin may only alter CSS custom properties, backgrounds, borders, and decorative sprites. It must never require HTML markup changes or alter interactive element IDs.
- **Pixel-Art Invariant**: Textures and sprites are 100% original, hand-authored SVG `<rect>` pixel art committed directly to the repo. Zero raster images or base64 bitmaps are allowed.
- **Size Budget**: Each skin directory must remain under 150 KB (including any font and license files).
- **Accessibility Fallbacks**: A skin that makes panels translucent must render them opaque under `@media (prefers-reduced-transparency: reduce)`, and a skin that introduces movement must stop it under `@media (prefers-reduced-motion: reduce)`. A skin that introduces no movement needs no rule of its own: `app.css` carries a global reduced-motion rule that covers everything the page draws, and a per-skin copy would be boilerplate asserting itself.

  Reduced motion is testable and tested. **Reduced transparency is not, on any engine we have**: Chromium did not ship `prefers-reduced-transparency` until well after the build the browser tests drive, so the query never matches and the fallback never fires there — and it will not fire in an older Edge or JCEF either. The rule is written and asserted to exist, and a viewer whose browser does not know the query gets the translucent panels regardless of their OS setting. That is a limitation of the mechanism, not something the skins can work around; it is written down here rather than assumed away, and `glass` is the only skin it applies to.
- **Asset URLs carry the token.** A relative `url()` inside a stylesheet does not inherit the query string the stylesheet was fetched with, and everything but `/api/ping` needs this run's token — so a skin asking for its own `sprites.svg` was refused with a 403, silently, and the chips simply had no sprite. `serve._static` puts the token on every relative `url()` it serves in a stylesheet (before the fragment). A skin references its art relatively and does not think about it.
- **Composited Contrast**: The effective composited panel contrast must pass WCAG floors (text ≥ 4.5:1, status roles ≥ 3:1).

### Available Skins

| Skin | Base Palette | Inspiration & Materials | HIG Rule Applied |
|---|---|---|---|
| `none` | system | Default clean HIG interface | Clean baseline |
| `glass` | `dark` | Translucent frosted acrylic `backdrop-filter: blur(16px)` panels over soft project-accent radial washes. Solid status chips and focus rings. | *Materials*: translucent material blurs what is behind it and adapts to light and dark while keeping content legible. |
| `voxel` | `matrix` | Tiled 8×8 `<rect>` dirt/stone textures, 2px bevelled slab controls, 10px accent borders, and 12px status blocks before glyphs. Inspired by block-building games; zero copied assets. | *Visual Design*: bold tactile geometry and unmistakable state indicators across a room. |
| `farmstead` | `sand` | Warm cream paper `#FBF3E0`, 4px wooden frames `#6E4A28`, tan controls with 3px press shadows, journal-style inspector, and 5 crop-stage sprites (seed, sprout, sun, bloom, wilted) carrying state. Inspired by pixel farming games; zero copied assets. | *Color & Redundancy*: never colour alone; crop stages provide a second redundant carrier for agent status. |

## An Agent Never Sees This

CLI theming is strictly for human awareness. An agent (such as Luna or an autonomous subagent) never receives escape bytes or palette noise:
- Every terminal recolouring command checks `color.enabled()`. When `stdout` is piped or redirected, all escape sequences are suppressed.
- `ad-theme list`, `show`, `gallery`, and all doctor rows output pure TOON on `stdout` when piped, adhering strictly to the contract of Issue #71.
- Directory hooks write escapes directly to the interactive terminal console and never pollute tool call outputs or piped subprocess stdout.



