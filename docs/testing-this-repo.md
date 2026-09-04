# Testing this repository

How `agentdata` and the skills are proven before a commit lands. This is about *our* suite;
`docs/testing.md` is the agent-facing `ad-test` documentation for other repositories.

Every bug in `HANDOFF.md`'s "do not regress" list was found on the laptop, after CI was green. The
point of everything below is that the next one is found by CI.

## Layout

| Path | What lives there |
|---|---|
| `tests/` | the ordinary suite: units, seams, and the static guards |
| `tests/test_props_*.py` | the generated inputs; hypothesis, from the `dev` extra |
| `tests/test_lifecycle.py` | install, update, shadow, uninstall, in real venvs (`slow`) |
| `tests/conftest.py` | isolation and the shared fixtures |
| `tests/fixtures/` | inputs, byte-exact (`-text` in `.gitattributes`) |
| `tests/fakes/<tool>/transcripts/` | real tool output, captured, replayed by tests |
| `tests/regressions/` | one file per failure seen on a real machine |
| `tests/laptop/` | the verification runbook, gated on `AGENTDATA_LAPTOP=1` |

## Running it

```bash
python -m pytest -q                       # the whole suite; laptop tests skip themselves
python -m pytest -q -m "not slow"         # skip the wheel/venv build
python -m pytest -q --shuffle-seed 1      # catch order dependence
HYPOTHESIS_PROFILE=ci python -m pytest -q # the property tests at CI's example count
AGENTDATA_LAPTOP=1 python -m pytest -m laptop     # the laptop runbook (needs real tools)
```

```powershell
$env:AGENTDATA_LAPTOP = '1'; python -m pytest -m laptop     # the same from pwsh 7
```

`pytest -q -m "not slow"` takes **just under three minutes** on this laptop (Windows, Python 3.12,
~900 tests) and comfortably under two on CI's Linux runners — process spawning is the difference, and
the contract slice spawns one per command per case. The budget is **two minutes on Linux**; the two
contract cases that run three subprocesses per command carry `slow` for exactly that reason, and
anything else that would push past it should too.

## Markers

Declared in `pyproject.toml`, and `--strict-markers` is on, so a typo fails collection rather than
silently selecting nothing.

| Marker | Meaning |
|---|---|
| `slow` | builds a wheel in a fresh venv |
| `laptop` | needs real tools and a real machine; gated on `AGENTDATA_LAPTOP=1` |
| `windows` / `posix` | only meaningful on that OS |
| `real_home` | opts out of the isolated home, for tests *about* the real checkout |
| `network` | reaches the network. Nothing carries it today — it exists so adding one is a decision |

## Isolation

`tests/conftest.py` gives every test a temporary `HOME`/`USERPROFILE`, a temporary
`AGENTDATA_CONFIG`, `NO_COLOR=1` and `AGENTDATA_UI=plain`. A test that happens to pass because the
developer has pncli installed is not a test, and one that writes to the developer's own config is
worse.

`PIP_CACHE_DIR` points into that temporary home too. Without it, redirecting the profile makes pip
fall back to a *relative* cache directory, and the slow tests -- which really do run `pip wheel` and
`pip install` -- wrote 3.8 MB of HTTP cache into `<repo>/pip/cache`, inside the checkout under test,
where the next `git add -A` would have committed it.

**`APPDATA` and `LOCALAPPDATA` are deliberately left alone.** On Windows they hold per-user
*installed packages*, so redirecting them makes every subprocess answer `No module named pytest` on
a machine with a `--user` install. Tests that are about the npm global prefix opt in with the
`appdata_isolation` fixture.

Other fixtures: `run_cmd` (an `ad-*` command as a real subprocess — the only way to catch a bare
`sys.exit`, an import-time crash, or an escape sequence that appears only when stdout is a pipe),
`state_file`, `pbip`, `fakes_dir`, `isolated_path`.

## The black-box contract

`tests/test_contract.py` spawns every `ad-*` command as a **real subprocess**, parametrised over
`[project.scripts]`. In-process `main()` calls cannot catch what actually goes wrong in the field:
an import-time crash, a bare `sys.exit`, a traceback on stderr, or an escape sequence that only
appears when stdout is a pipe.

Per command: `--help` exits 0, `--version` prints something, an unknown flag is a usage error and
not a crash, no arguments is help or usage and not a crash, and one **canned safe invocation** keeps
the whole contract — TOON on stdout with a `meta.ok`, a `hint` whenever `ok` is false, no ANSI when
piped, and output byte-identical under `AGENTDATA_COLOR=never`, `NO_COLOR=1` and the default.

### Adding a case

Every entry in `[project.scripts]` must appear in `tests/contract_cases.py`; a command without one
fails the suite with a message naming it, so coverage is by construction rather than by memory.

```python
"mycmd": {"args": ["subcommand", "@tsv"], "needs": ["tsv"], "toon": True},
```

`@name` is replaced by a fixture from `prepare()`. "Safe" means no network, no writes outside the
temp directory, and no dependence on an installed tool. A command whose real work needs a network or
a licensed tool contributes `--help` — which still proves the parser builds, the module imports and
the exit code is right, which is most of what breaks.

**Two bugs this found on its first run:**

- `ad-help` given a mistyped flag printed the catalog and exited **0**, so the typo looked like success.
- `ad-setup` with no stdin exited **130** — the SIGINT convention — telling a caller a person pressed
  Ctrl-C when in fact there was simply nothing to read. It is exit 2 now, with a hint naming
  `--non-interactive --set`.
- and one divergence: `python -m agentdata help pbip` printed the catalog while `ad-help pbip`
  printed pbip's help, though the two forms are documented as identical.


## Property tests

`tests/test_props_*.py` generate inputs with [hypothesis] rather than listing them. They cover the
seams that lose data *silently* — a byte decoded as the wrong character, a cell that swallows its
own delimiter, a path that stops matching itself — where an example-based test only ever proves the
examples someone already thought of.

```bash
python -m pytest -q tests/test_props_textio.py             # 50 examples per property
HYPOTHESIS_PROFILE=ci python -m pytest -q                  # 200, what CI runs
python -m pytest -q --hypothesis-seed 12345                # replay a reported failure exactly
```

| Module | Seam |
|---|---|
| `test_props_textio.py` | decoding any bytes, writing atomically, output file names |
| `test_props_toon.py` | the wire format: any table, any cell, any stdout code page, `csv2toon` |
| `test_props_paths.py` | `textio.norm_path()`, and the guard that keeps it the only canonicaliser |
| `test_props_tmdl_pbir.py` | TMDL parse -> serialise as a fixed point; the PBIR reference walk |

Two profiles, shared through `tests/props_profiles.py`: `dev` (50 examples, the default) keeps a
local run to a couple of seconds, `ci` (200)
does the searching. Deadlines are off — Windows runners are slow enough that a per-example deadline
produces flakes rather than findings. hypothesis is in the `dev` extra, and the module
`importorskip`s it so a bare checkout still runs everything else.

**A counter-example worth keeping is pinned with `@example`**, so it runs first on every future run
instead of waiting for the generator to rediscover it.

Two rules the generator will find for you if you break them:

- Pass strategies **by keyword** — `@given(text=TEXT)`, not `@given(TEXT)`. Positional strategies
  fill the *rightmost* parameters, so with a `tmp_path` on the end the text goes to the fixture and
  pytest then fails looking for a `text` fixture.
- **Do not `@given` a test that patches through a function-scoped fixture.** `monkeypatch` is not
  undone between examples, so a patch made by example one is still in force during example two's
  setup. A fixed list of inputs wants `parametrize` anyway.

### What it found on the first run

- A **form feed** in a cell was left unquoted. `str.splitlines()` breaks on `\v \f \x1c \x1d \x1e
  \x85 U+2028 U+2029` as well as `\n` and `\r`, so a one-line value became two rows to every reader
  downstream. `toon.LINE_BREAKS` is now the full set, and a test scans the BMP to keep it that way.
- **Keys, column names and table names were never quoted** — a key of `:` encoded as `:: 0` and a
  column of `"` broke the header. They go through `toon._name()` now, and the validator accepts a
  quoted name.
- A **quoted value containing a newline** — which the encoder has always emitted — was rejected by
  `toon.validate()`, which read line by line. It re-joins quoted runs first.
- A one-column row holding a **null** encodes as an indented empty line, and the validator was
  skipping it as blank and then reporting the row count as short.
- `import agentdata.csv2toon` **raised IndexError**: the module read `sys.argv[1]` at import time,
  so any importer hit it, and `python -m agentdata.csv2toon` with no file printed a traceback
  instead of usage. It also skipped the `Table[Column]` header transform that `ad-pbip`'s own DAX
  path applies, so the same query gave two different TSV headers depending on which command wrote
  it. `test_every_module_imports_without_doing_anything` is the general form of the first half.

### One canonicaliser

`.replace("\\", "/")` was written out by hand in **142 places**. It is correct in all 142 -- until
one of them forgets, and then two `meta.path` values for the same file stop comparing equal, on
Windows only, in output an agent is supposed to be able to diff. They all call `textio.norm_path()`
now, which also folds `/c/Users` and the drive-letter case, and
`test_no_hand_written_path_canonicaliser` fails on the 143rd. It parses rather than greps, so it can
tell the call from the sentence about the call in `norm_path`'s own docstring.

[hypothesis]: https://hypothesis.readthedocs.io/

## Fakes

`tests/fakes/` holds stand-ins for the external tools: pncli, pip, gh, az, TabularEditor, dscmd and
powershell. They exist because six tests in `test_proc.py` were `skipif(os.name == "nt")` with the
reason "POSIX shell stand-in" — so the Windows behaviour of the module that exists *because of*
Windows was skipped on Windows, which is where it breaks.

A fake materialises as an **npm-style `.cmd` shim** on Windows (the shape `proc.py` has to unwrap)
plus an extension-less `sh` shim, and as the `sh` shim alone on POSIX. Both run the same
`tests/fakes/runner.py`, so a test cannot pass on one OS for a reason that does not exist on the
other.

```python
import fakes

def test_something(monkeypatch, tmp_path):
    fakes.apply(monkeypatch, tmp_path, ["pncli"], case="positional_option")
    ...
```

### Transcripts

A fake replays real output. `tests/fakes/<tool>/transcripts/<case>.json` records `argv`, `match`,
`returncode`, `stdout`, `stderr`, when it was captured, and a `source`:

| `source` | Meaning |
|---|---|
| `captured` | a real run, recorded with `tests/fakes/record.py` |
| `photographed` | transcribed from a failure someone photographed or pasted |
| `synthesized` | written to pin one code path; real in shape, not captured |

Capture a new one on the machine where the interesting thing happens:

```bash
python tests/fakes/record.py pip --case winerror5 --note "all-users install" -- install --force-reinstall agentdata
```

**A fake that invents output is worth less than no fake** — it proves the code handles a shape
nobody has ever seen. The `source` field exists so a reader can tell which they are looking at, and
the aim is to replace `synthesized` entries with `captured` ones as the real failures turn up.

### Rules

- A fake never touches the network and never reads the real config.
- An argv no transcript matches exits **99** and echoes the argv. A silent zero would let a test
  pass while the code sent something quite different.
- **A Windows skip must name the test that covers Windows**, and that test must exist — enforced by
  `test_a_windows_skip_must_name_the_test_that_covers_windows`. The rule is not "never skip": a
  POSIX shell loop is sometimes the clearest way to write the POSIX half. The rule is that the gap
  cannot be left open by accident.
- The `powershell` transcript has a **drift detector**: on Windows CI the real CIM query runs and
  its shape is compared with the transcript, so a fake cannot quietly stop resembling the tool.


## The install and update lifecycle

`tests/test_lifecycle.py` (`slow`) is the only slice that proves how this package *reaches* a
laptop. Everything else about it is asserted from strings -- `install_cmd()` returns the right
text, `cli_command_text()` composes the right line -- and none of that shows whether `pip` did what
the text says.

### The `git+file://` trick

`ad-update` installs from `install.repo_url()`, which is GitHub. A test that used it would need the
network, would install whatever `main` happens to be, and could not create the interesting
transitions at all. So the working tree is cloned into a temp directory and `AGENTDATA_REPO_URL`
points at it as a `file://` URL. Same code path, same `pip`, same `--force-reinstall --no-deps`,
and a repository the test can commit to between steps. `AGENTDATA_REPO_URL` is not a test hook --
it is what a team running an internal mirror needs, and this is the first thing that used it.

Three details, each of which cost a run to find:

| Spelling | What breaks |
|---|---|
| `file://localhost/C:/...` | the only form PEP 508 accepts for a Windows path, and git reads `localhost` as a UNC host |
| `file:///C:/...` | git handles it -- until `MSYS_NO_PATHCONV=1`, which `proc.child_env()` sets for every child, stops Git for Windows folding `/C:/` back to `C:/` |
| `file://C:/...` | works in both, and on POSIX the same expression yields the standard `file:///path` |

PEP 508 still refuses the POSIX form (no authority), so `install.cli_spec()` falls back to a bare
URL for any URL without one -- which is also what an air-gapped mirror needs.

The clone carries **uncommitted work**: `git clone` copies HEAD, so a clone alone would test the
code you are about to change rather than the code you just changed. Modified and
untracked-but-not-ignored files are copied over it and committed on top.

### Adding a case

### What runs where

The full sequence runs on **Linux only**, and Windows runs a shorter, Windows-shaped sibling. That is
a budget decision made honestly: six pip builds is about ninety seconds on a laptop and roughly six
times that on a hosted Windows runner, which is more than the whole job's cap. Nothing between (c)
and (g) is platform-specific — an editable install, a `--pull`, a `--from-git` and a shadowing copy
behave the same everywhere, and proving them twice buys nothing but runner minutes.

`test_the_windows_launcher_and_scripts` keeps the parts that *cannot* be proven anywhere else, at two
installs rather than six: the console scripts are real `.exe` launchers and they start;
`ad-update.exe` refuses the CLI half and still serves `--check`; uninstall takes the `.exe` files with
it. The skip on the long test names that sibling, which
`test_a_windows_skip_must_name_the_test_that_covers_windows` enforces.

### Adding a case, continued

The cases are transitions, so they are **one test function with the steps in order**, not several
sharing a fixture — several would pass only in collection order, and CI runs the suite shuffled on
purpose. Put a new case where its starting state already exists and label the assertion `(x)`; a
case that needs no venv at all (`store_alias`) belongs outside.

**One venv, not one per case**, and one shared pip cache. Creating a venv and installing into it is
the entire cost, and on a Windows runner that is minutes rather than seconds: four venvs took the
Windows job past an 18-minute cap, one runs in under two minutes locally.

### What it found on its first run

- **`ad-pbip` was dead on every real install.** `pyyaml` was in the `dev` extra, `cli_pbip` imports
  the module that imports it, so every subcommand -- `--version` included -- died with
  `ModuleNotFoundError: No module named 'yaml'`. It is a base dependency now *and* the import is
  lazy, because `ad-update --cli` installs with `--no-deps` and an upgrade would still arrive
  without it.
- **The `.exe` re-exec never fired.** A console-script launcher strips its own extension before
  handing over, so `sys.argv[0]` is `Scripts/ad-update` with no extension and `launcher_kind()` said
  `module`. The self-update kept dying with WinError 32, behind a hint that reads like advice rather
  than like a bug.
- **...and re-execing could not have worked either way round.** `subprocess.run` leaves the `.exe`
  running and a running executable's image is locked, so pip hits the same error one level down;
  `os.execv` on Windows does not overlay the process, it starts a new one and exits, so the shell
  gets its prompt back mid-update and the exit code is lost. It is a **refusal** now — exit 2,
  naming the module form — which is synchronous and cannot half-succeed.
- **`meta.hint` was one slot each check overwrote**, so a laptop with two installs *and* a PATH
  problem reported only whichever check ran last. There is a `problems` table now, and `hint` is
  the most blocking of them.

## Coverage floors

Per module, never repo-wide, and **per platform**. A single percentage invites padding and says
nothing about the files that actually go wrong on Windows. The seven that do are in
`.github/scripts/coverage-floors.json`; CI checks them with `.github/scripts/coverage_floors.py`.

The platform split is not bookkeeping: these are precisely the modules whose Windows branches — the
console API through ctypes, `msvcrt`, the long-path prefix, the MSYS pty probe — cannot execute on
Linux. `color.py` measures 84% on Windows and 62% on Linux for the same tests. One set of numbers
would fail on the other OS for nobody's fault, which is how a floor becomes a thing people turn off.

Floors **ratchet up only**. After adding tests:

```bash
python -m coverage run -m pytest -q -m "not slow" && python -m coverage json -o coverage.json
python .github/scripts/coverage_floors.py --update      # rounds down to the nearest 5, commits higher
```

Lowering one is an edit to that file with the reason in the commit message.

## The regression convention

A failure seen on a real machine becomes a file here, so it cannot come back quietly:

```
tests/regressions/test_<yyyymmdd>_<shell>_<short>.py
```

The module docstring quotes **what the machine actually printed** and links the issue;
`test_convention.py` enforces both, plus the filename shape. Template:

```python
"""<date>, <shell>: <one line saying what went wrong>.

Symptom:

    <the TOON row, or the pasted error, verbatim>

<why it happened, in a sentence or two>

Issue: https://github.com/agentchieflou/this-next-please/issues/<n>
"""
```

Reproduce it with fakes rather than the real tool — a fake that replays captured output is a test;
one that invents output is worth less than no test.

## What CI runs

| Job | What it proves |
|---|---|
| `ubuntu · 3.12 / 3.14` | the suite on the floor and on the laptop's Python |
| `windows · 3.12 / 3.14` | the same, plus pwsh 7 / Git Bash / cmd smoke steps, under both `core.autocrlf` settings |
| `floor · pip refuses the wheel on 3.11` | `Requires-Python` really stops an older interpreter, in the words the user sees |
| `lint · shellcheck + PSScriptAnalyzer` | the shipped scripts parse and target the right floors |
| `lint · bash 4.4 and pwsh 7 floors` | no post-4.4 construct in anything we ship or emit; the laptop suite never executes here |
| `coverage · per-module floors` | the seven Windows-critical modules stay covered; report uploaded as an artifact |
| `suite · shuffled` | two seeded shuffles, to catch fixture leakage |
| `windows · 3.14` (the `slow` marker) | the install/update lifecycle, in real venvs, on the OS where packaging goes wrong |
| every job | `HYPOTHESIS_PROFILE=ci`, so the property tests search 200 examples rather than 50 |
