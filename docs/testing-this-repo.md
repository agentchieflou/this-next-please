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

- `ad-help --anything` printed the catalog and exited **0**, so a mistyped flag looked like success.
- `ad-setup` with no stdin exited **130** — the SIGINT convention — telling a caller a person pressed
  Ctrl-C when in fact there was simply nothing to read. It is exit 2 now, with a hint naming
  `--non-interactive --set`.
- and one divergence: `python -m agentdata help pbip` printed the catalog while `ad-help pbip`
  printed pbip's help, though the two forms are documented as identical.


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
