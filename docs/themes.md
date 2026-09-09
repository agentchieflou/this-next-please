# CLI Theming — Terminal Palettes, Prompt Theming, and Project Colours

_The terminal a human opens tells them where they are._

## The Gallery

| Theme | Ground | Text | Accent | `why` |
|---|---|---|---|---|
| `greens` | `#0B1F14` | `#CDE6D2` | `#3FB950` | calm and go; a leaf-green desk |
| `reds` | `#400000` | `#F2D9D9` | `#FF5C5C` | the loud desk; a red ground where errors cannot hide behind the ground |
| `eye-relief` | `#2B2A27` | `#D6CDB8` | `#C9A227` | for hour six; low blue, low glare, nothing pure white |
| `eye-relief-day` | `#F2ECDC` | `#3B3A34` | `#8A6D1F` | the same idea for a bright room (light theme) |
| `nfl-browns` | `#311D00` | `#F2E8D9` | `#FF3C00` | Cleveland Browns: brown, orange, white |
| `dark` | `#14171A` | `#E3E7EA` | `#58A6FF` | the neutral dark the page already had, now a name the terminal can share |
| `vanta-black` | `#000000` | `#C8C8C8` | `#E6E6E6` | the true-black panel for OLED and pitch rooms |
| `matrix` | `#020A03` | `#3DF07A` | `#00FF41` | phosphor on black; the falling code screen |
| `blues` | `#0B1B33` | `#D6E4F7` | `#4DA3FF` | deep ocean navy and slate |
| `sand` | `#EFE6D2` | `#3A3126` | `#B9631E` | warm desert solarized parchment (light theme) |
| `random` | generated | generated | generated | a fresh, stable colour per project or per day; seeded |
| `none` | — | — | — | the terminal exactly as you had it (the default) |

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
```
