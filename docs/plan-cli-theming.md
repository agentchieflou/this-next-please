# Plan: CLI theming — the terminal tells the human where they are

_Status: PLANNED (2026-09-08) — epic #135, slices #136–#141. Nothing below is built yet; the palettes are seeds
to be tuned in #136 against the contrast check, and every host row is to be measured on the laptop, not assumed._

## Why this exists

The operator runs several projects from one desk (#122). Every one of them is typed into a terminal, and today
every terminal looks the same — the desk photograph behind #122 shows a stock `cmd.exe` window, and the human is
the only thing that remembers which project it belongs to. This epic makes the console itself carry that
information. **The purpose is the human's attention, not decoration**: three questions a glance should answer,
and a palette that is still comfortable in hour six.

| Question | Answered by | Slice |
|---|---|---|
| *Where am I?* | the ground colour and accent of the window, the same hue on the prompt, the tab and the fleet tile | #136, #137, #139 |
| *What is running?* | the prompt (project · ticket · phase), the tab title, a progress state in the tab and taskbar | #138, #141 |
| *What needs me?* | a bell and a red tab for a fleet `needs_human` event, under #97's quiet hours | #141 |

The request, verbatim: *"introduced to lesser explored CLI themes … start with Oh My Posh designs, then more
next-gen stuff … at minimum a greens theme, a reds theme, an 'eye relief' theme, a 'random' theme, an 'NFL Browns'
theme, and finally the option to set themes per project."* The per-project option is what ties this to #122: #129
registers the projects, this epic gives each one a colour.

## What is reused

- `agentdata/color.py` / `agentdata/ui.py` decide **when** colour is allowed: never for a pipe, never with
  `NO_COLOR`, only for a human at a terminal. `console.host()` names the host. Every theme mechanism sits behind
  that gate — an agent (Luna) never sees an escape byte, SGR or OSC.
- `agentdata/fleet/static/app.css` already states the theming rule: surface colours change, **status colours never
  do**. The terminal adopts it.
- `themes/pycharm/Crimson Studio.icls` (`#400000` ground, errors underlined in yellow because red would vanish) is
  the seed of `reds` and the model for how a theme documents its one necessary exception.
- `ad-setup --print-completion <shell> --install` is the pattern for every startup-file write: one idempotent line,
  replaced not appended, reported by `ad-doctor`, removed by `uninstall`.
- `agentdata/shell.py`, `proc.py`, `textio.py` and epic #63 supply the shell facts; Oh My Posh, Clink, Nerd Fonts
  and Starship are external tools resolved like `pncli` and `az`, never required.

## The theme model (#136)

```
Theme
  name, title, why            # `why` is one sentence: what the theme is for, shown in the gallery
  ground, text, accent, cursor
  ansi[16]                    # black … bright_white, the slots OSC 4 and the conhost colour table set
  status: ok warn fail skip error
  light: bool
  layout: jandedobbeleer | atomic | night-owl   # which Oh My Posh design the prompt is generated from (#138)
```

One palette, rendered four ways by the slices that need it: SGR (8/16 colours, so a legacy console still renders),
truecolor, an Oh My Posh `.omp.json`, a Windows Terminal scheme. `theme.check(t)` is the invariant, computed, not
judged by eye:

| Rule | Floor | Why |
|---|---|---|
| `text` on `ground` | ≥ 4.5:1, and ≤ 19:1 | readable; pure white on pure black is refused — `eye-relief` sits near 7:1 on purpose |
| each status colour on `ground` | ≥ 3:1 | a `fail` must be visible on every ground |
| `ok` / `warn` / `fail` pairwise | a stated hue distance | distinguishable from each other, not just from the ground |
| glyph | always | `✓ ! ✗ –` (or `+ ! x -`) carry the meaning when colour cannot |

A theme that fails refuses to load with a `hint` naming the pair. `random` rolls are checked before use.

### Seed palettes

Starting points for #136, to be tuned against the check. Hex values are the ground, text and accent; the 16 slots
are derived from them in code and listed in `docs/themes.md` once tuned.

| Theme | Ground | Text | Accent | Status exception | `why` |
|---|---|---|---|---|---|
| `greens` | `#0B1F14` | `#CDE6D2` | `#3FB950` | `ok` is a lighter mint than the accent so it still reads as a status | calm and go; a leaf-green desk |
| `reds` | `#400000` (from Crimson Studio) | `#F2D9D9` | `#FF5C5C` | **`fail` is amber `#FFD166`, not red** — the rule's proof | the loud desk; a red ground where errors cannot hide behind the ground |
| `eye-relief` | `#2B2A27` warm grey | `#D6CDB8` warm off-white | `#C9A227` muted amber | no saturated blue anywhere; contrast capped near 7:1 | for hour six; low blue, low glare, nothing pure white |
| `eye-relief-day` | `#F2ECDC` sepia | `#3B3A34` | `#8A6D1F` | the light pair; `light: true` | the same idea for a bright room |
| `nfl-browns` | `#311D00` | `#F2E8D9` | `#FF3C00` | tab colour is the orange | Cleveland Browns: brown, orange, white |
| `dark` | `#14171A` | `#E3E7EA` | `#58A6FF` | neutral dark | the neutral dark the page already had, now a name the terminal can share |
| `vanta-black` | `#000000` | `#C8C8C8` | `#E6E6E6` | text contrast capped under 19:1 | the true-black panel for OLED and pitch rooms |
| `matrix` | `#020A03` | `#3DF07A` | `#00FF41` | `fail` is red `#FF3B3B`, contrasting with green text | phosphor on black; the falling code screen |
| `blues` | `#0B1B33` | `#D6E4F7` | `#4DA3FF` | `info` is cyan `#5EE1E6` so running never hides in navy ground | deep ocean navy and slate |
| `sand` | `#EFE6D2` | `#3A3126` | `#B9631E` | `light: true`, status colours darkened | warm desert solarized parchment |
| `random` | generated | generated | generated | status hues fixed; the roll is checked before use | a fresh, stable colour per project or per day; `pin` keeps one |
| `none` | — | — | — | — | the terminal exactly as you had it (the default) |

`random` seeds from `theme.random_seed` when pinned, else from the registry name of the project (stable for that
project), else from the day (stable for a session). **Never per prompt.** `ad-theme show random` prints the seed.

## Applying it: the host matrix (#137)

Every mechanism is gated by `color.enabled()`, so a pipe gets nothing. Each row is measured on the laptop and the
result written into `docs/themes.md`; a host that cannot do something is a documented row, not a silent no-op.

| Host (`console.host()`) | Live recolour | Persist | Notes |
|---|---|---|---|
| `windows-terminal` | OSC 4 / 10 / 11 / 12 | fragment (#139) | the good case; tab colour and title too |
| `conhost` (bare `cmd.exe`, legacy PowerShell window) | `SetConsoleScreenBufferInfoEx` via `ctypes` (the `color.py` pattern) | `HKCU\Console\<title>` only with `--persist`, shown and confirmed | conhost has no OSC; the console API sets the 16-colour table and the window repaints |
| `conpty` | OSC where the host renders it | — | measured |
| `mintty` (standalone Git Bash) | OSC 4 / 10 / 11 | live hook only | mintty renders ANSI though Python sees a pipe (`is_msys_pty`) |
| `vscode` | OSC 4 / 10 / 11 (xterm.js) | live hook only | workbench settings are the user's |
| `pycharm-terminal` | **to be measured** — JediTerm's OSC 10/11 support is the open question | — | the row says `partial` with what was seen |
| `pycharm-run` | SGR only | — | the run window is not a terminal |
| `tty` (Linux) | OSC | live hook only | CI proves the byte stream |
| `pipe` | nothing, ever | — | `ad-theme apply` answers `mechanism: none`, exit 0 |

## Oh My Posh first, then the rest (#138, #141)

Oh My Posh is the one prompt engine that runs in all three supported shells from one theme file — pwsh 7 and Git
Bash natively, `cmd.exe` through **Clink**. It is optional, resolved through `proc.py`, offered by `ad-theme
install --prompt omp` with the exact `winget` lines and never downloaded by agentdata itself.

`~/.agentdata/themes/omp/<theme>.omp.json` is generated per theme from the palette, from one of three stock designs
the operator compares in `ad-theme gallery --prompt` (`jandedobbeleer`, `atomic`, `night-owl`). The prompt shows
the project name in the accent, the branch, the venv, and `AGENTDATA_TICKET` / `AGENTDATA_PHASE` when the directory
hook (#139) has exported them — the prompt reads variables and **never runs a command**. `transient_prompt` is on
by default: past prompts collapse to one line so the screen holds work.

Startup lines, per shell, with the completion installer's idempotent pattern:

| Shell | Line | File |
|---|---|---|
| pwsh 7 | `oh-my-posh init pwsh --config <file> \| Invoke-Expression` | `$PROFILE` |
| Git Bash | `eval "$(oh-my-posh init bash --config <file>)"` | `~/.bashrc` |
| cmd.exe | a Clink Lua script: `load(io.popen('oh-my-posh init cmd --config <file>'):read("*a"))()` | Clink's scripts dir; `clink autorun install` offered if Clink is not yet autorun |

An existing Oh My Posh or Starship line is detected and the person is asked before it is replaced. A missing Nerd
Font is reported (`ad-doctor theme/nerd-font`) before the glyphs turn into boxes.

The "next-gen" signals (#141) are one function each, same gate, one doctor row each:

| Signal | Sequence | Wired into |
|---|---|---|
| progress in the tab and taskbar | OSC 9;4 (`pct` / indeterminate / error / done) | `ad-td` / `ad-ora` / `ad-hive` / `ad-impala` queries, `ad-pbi` refresh polling, `ad-jira changelog` paging, `ad-uat reconcile`, `ad-fleet` while an agent runs |
| tab title | OSC 2 | the directory hook: `<project> · <ticket> · <phase>` |
| bell / notification | BEL, OSC 9 / OSC 777 where honoured | fleet `needs_human`, under #97's quiet hours and dedupe |
| time-of-day schedule | none — the hook compares the clock | `ad-theme set eye-relief --after 18:00 --until 07:00` |
| Starship | a TOML generated from the same palette | a one-sitting comparison, decision recorded in #141 before any Starship code merges |

## One theme per project (#139)

Personal and local: `~/.agentdata/config.json`, never `AGENTS.md` (shared) and never `.agent/` (the agent's).

```
theme.default            greens
theme.projects.<name>    nfl-browns          # <name> is the fleet registry name (#93, #129), or a path when unregistered
theme.random_seed        <int>               # set by `ad-theme pin`
theme.prompt             omp | none
theme.transient          true
theme.schedule[]         {theme, after, until}
```

**Nothing runs Python at prompt time.** `ad-theme install --hook` generates `~/.agentdata/themes/hook.{ps1,sh,lua}`
with a *path prefix → escapes* table embedded, plus the `AGENTDATA_PROJECT` / `AGENTDATA_TICKET` /
`AGENTDATA_PHASE` exports read from `.agent/state.json` by the shell **once per directory change**. pwsh wraps
`prompt`, bash uses `PROMPT_COMMAND`, cmd uses a Clink `onbeginedit` handler (or a shown-and-confirmed `AutoRun`
chain without Clink). Every `ad-theme set` / `unset` regenerates the hook. A shell with the hook installed spawns no
Python across 50 prompts — a CI assertion, because an 80 ms prompt is the attention cost this epic removes.

Windows Terminal is never edited: a **fragment** at
`%LOCALAPPDATA%\Microsoft\Windows Terminal\Fragments\agentdata\agentdata.json` adds one scheme per theme and one
profile per registered repo (`startingDirectory`, `colorScheme`, `tabColor: <accent>`, `tabTitle`, the user's
shell). Opening a project from the tab dropdown is one click, in its colour, in its directory. `ad-fleet status`
gains an `accent` column from the same config and the dashboard tile (#96, #131) paints its border in it — the
accent says *which project*, the status chip says *what state*, and the chip's *role* never changes.

## Command surface

`ad-theme` needs the three things every command needs (`[project.scripts]`, `__main__.COMMANDS`, an int return).

| Command | Does | Writes |
|---|---|---|
| `ad-theme list` | TOON: `name, title, ground, accent, light, why` | — |
| `ad-theme show <name> \| --cwd` | the palette; with `--cwd`, which theme applies here and why | — |
| `ad-theme gallery [--prompt]` | one row per theme painted in its own colours; names only when piped | — |
| `ad-theme apply [<name>]` / `reset` | recolour the live window per the host matrix; `--persist` on conhost only | conhost registry value, only with `--persist` and a yes |
| `ad-theme set <name> [--project DIR \| --default] [--after HH:MM --until HH:MM]` / `unset` / `pin` | the mapping; regenerates the hook and the fragment | `~/.agentdata/config.json`, `~/.agentdata/themes/*` |
| `ad-theme install [--hook] [--prompt omp] [--terminal wt] [--shell pwsh\|bash\|cmd]` / `uninstall` | the startup lines, the Clink script, the fragment; every write listed first, needs a yes or `--yes` | startup files, Clink scripts dir, the fragment |

`ad-setup` gains a `theme` step after `console` (#140): the gallery, one `why` per theme, a pick with `none` as the
default answer, then the offers in order — apply now, hook, fragment, Oh My Posh. `--quick` accepts nothing here
(a theme is a taste, never an unambiguous default). `ad-doctor` rows: `theme/default`, `theme/hook`,
`theme/terminal`, `theme/oh-my-posh`, `theme/clink`, `theme/nerd-font` — `warn` at worst, never `fail`.

## Ground rules (from #135)

1. An agent never sees a theme: TOON on stdout is byte-identical with every theme; the #71 contract extends to OSC.
2. Status colours carry meaning and never move; the glyph is always there; `reds` is the proof.
3. The eyes are the user: no pure white on pure black; `eye-relief` caps contrast on purpose; `random` never rolls
   per prompt.
4. A theme is personal and local: home config only.
5. Nothing runs Python at prompt time.
6. Every write is listed, explicit and reversible; existing lines are chained after, never replaced.
7. Zero new required dependencies.
8. Proven per host and per shell, like #67; every laptop failure becomes a regression test with the host named.
9. Attention is the acceptance criterion: each slice names which of the three questions it answers, and its laptop
   demo is judged on that.

## Build order

#136 (model) → #137 (apply) → #138 (Oh My Posh) → #140 (onboarding) → #139 (per project, after #129 registers
projects) → #141 (signals, schedule, Starship comparison).

## Open questions, to be answered on the laptop and recorded in the slice

- PyCharm terminal: does JediTerm honour OSC 10/11 for a live recolour? (#137)
- Which of the three Oh My Posh designs reads best on the real screens at the real font size? (#138, the gallery)
- Is the Windows Terminal fragment picked up without a restart when regenerated? (#139)
- Starship vs Oh My Posh: prompt cost per keypress, measured, in all three shells. (#141)
