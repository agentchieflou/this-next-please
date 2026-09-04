# Testing this repository

How `agentdata` and the skills are proven before a commit lands. This is about *our* suite;
`docs/testing.md` is the agent-facing `ad-test` documentation for other repositories.

Every bug in `HANDOFF.md`'s "do not regress" list was found on the laptop, after CI was green. The
point of everything below is that the next one is found by CI.

## Layout

| Path | What lives there |
|---|---|
| `tests/` | the ordinary suite: units, seams, and the static guards |
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
AGENTDATA_LAPTOP=1 python -m pytest -m laptop     # the laptop runbook (needs real tools)
```

```powershell
$env:AGENTDATA_LAPTOP = '1'; python -m pytest -m laptop     # the same from pwsh 7
```

`pytest -q -m "not slow"` takes **about two minutes** on this laptop (Windows, Python 3.12) and
rather less on CI's Linux runners. Anything that would push it past that carries `slow` or `laptop`
and runs in its own job.

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

**`APPDATA` and `LOCALAPPDATA` are deliberately left alone.** On Windows they hold per-user
*installed packages*, so redirecting them makes every subprocess answer `No module named pytest` on
a machine with a `--user` install. Tests that are about the npm global prefix opt in with the
`appdata_isolation` fixture.

Other fixtures: `run_cmd` (an `ad-*` command as a real subprocess — the only way to catch a bare
`sys.exit`, an import-time crash, or an escape sequence that appears only when stdout is a pipe),
`state_file`, `pbip`, `fakes_dir`, `isolated_path`.

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
