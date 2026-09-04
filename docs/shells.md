# Shells: where each command runs, and how to quote it

The same command line means different things in different shells. Every rule below was run before it
was written down — `python -m agentdata argv -- <anything>` prints the argv Python actually received,
plus the shell and host it came from, and `tests/test_shell_argv.py` asserts each row.

Supported: **PowerShell 7 (`pwsh`)**, **Git Bash (bash 4.4+, MSYS)**, **cmd.exe**.
**Windows PowerShell 5.1 is not supported** — `ad-doctor` prints a `console/shell` warn row saying
so. Install pwsh (`winget install Microsoft.PowerShell`) or use Git Bash.

## Which command runs where

| Command | Where it runs |
|---|---|
| `ad-*` (every console script) | any shell |
| `python -m agentdata <command>` | any shell — identical arguments, and the form to use when `ad-*` is "not recognized" |
| `gh skill install …` | any shell |
| `pip install …` | the shell whose `python` you mean, and it must be **3.12 or newer** (0.6.0 refuses older with *"requires a different Python"*). `ad-update --check` lists every `python` on PATH with its version |
| `/plugin`, `/skill`, `/agent`, `/model` | **the Copilot chat window only.** A terminal answers `bash: /plugin: No such file or directory`, which reads like a missing tool rather than a wrong window. `ad-help /plugin` says so |

## Quoting and variables

| | pwsh 7 | Git Bash 4.4 | cmd.exe |
|---|---|---|---|
| Literal string | `'a >= b'` | `'a >= b'` | `"a >= b"` |
| Interpolating | `"project = $env:KEY"` | `"project = $KEY"` | `"project = %KEY%"` |
| `$` stays literal | single quotes | single quotes | always literal |
| `%VAR%` | literal text | literal text | **expanded** |
| Set an env var | `$env:X = 'v'` | `export X=v` | `set X=v` |
| Call a quoted path | `& "C:\Tools\te2.exe" …` | `"C:/Tools/te2.exe" …` | `"C:\Tools\te2.exe" …` |
| Stop parsing the rest | `--%` | n/a | n/a |
| `>` in an argument | quote it, or it redirects | quote it | quote it |

**The one that bites.** `--jql "project = $KEY"` in pwsh interpolates `$KEY`; if it is unset the JQL
silently becomes `project = ` and Jira returns an unhelpful error. Use single quotes for literal
text, and `$env:NAME` when you do mean a variable. `ad-sql-check --sql` refuses text still containing
`$env:X`, `%X%` or `${X}` rather than sending it to a database that will report a syntax error a
hundred lines later.

**cmd expands at parse time.** `set X=v && something %X%` passes the literal `%X%`: cmd
substitutes the whole line before `set` runs. Set the variable on a previous line, or in the
environment, or use `setlocal enabledelayedexpansion` and `!X!`.

**Embedded quotes in pwsh.** pwsh 7.3+ sets `$PSNativeCommandArgumentPassing` to `Standard` on
Windows and stops re-quoting arguments to native commands, so `'say "hi"'` arrives with its quotes
intact. Windows PowerShell 5.1 strips them — one more reason it is unsupported. On an older 7.x
where the setting is `Legacy`, set it in your `$PROFILE`:
`$PSNativeCommandArgumentPassing = 'Standard'`.

## Git Bash rewrites paths before Python starts

MSYS converts any argument that looks like a POSIX path, in both directions:

```
python -m agentdata argv --raw -- /c/Users        ->  C:/Users        # the useful half
python -m agentdata argv --raw -- -s /nope        ->  -s  C:/Program Files/Git/nope
```

The second is data being mangled into a path. It happens *before* the process starts, so no Python
code can undo it. Two ways round it:

```bash
MSYS_NO_PATHCONV=1 ad-pbip check /c/reports    # this command only
MSYS2_ARG_CONV_EXCL='*' ad-pbip check /c/reports   # exclude everything
```

Two things are already handled for you:

- **Subprocesses this package spawns** set `MSYS_NO_PATHCONV=1` (`agentdata/proc.py:child_env`). An
  argv *we* built is data we already know is not a path, so it arrives intact.
- **`/c/...` in a config file, an `AGENTS.md` fact or an answers file** is accepted everywhere a path
  is read (`config.expand`). Nothing converted it there, because no shell was involved.

## Non-ASCII and empty arguments

`é`, `→` and an empty `''` survive all three shells (asserted per shell). Output encoding is a
separate matter — see `docs/setup.md` §Colour and glyphs, per host.

## Writing files

That is its own table, per shell, in `docs/setup.md` §Windows notes. In short: under pwsh 7, `>`,
`Out-File` and `Set-Content` all produce UTF-8 without a BOM, and for `.agent/state.json` always use
`ad-state set`, which is its only sanctioned writer.
