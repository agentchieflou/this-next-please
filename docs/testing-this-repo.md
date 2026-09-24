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

Agent tools' scratch trees (`.gemini/`, the product's own `.agent/`) are neither committed nor scanned: the guards that walk the checkout (`tests/test_entrypoints.py`, `tests/test_bash_floor.py`) skip every dot-directory except `.github`. How agents build and review here is [developing-with-agents.md](developing-with-agents.md).

## Running it

One install command, and nothing runs without it:

```bash
python -m pip install -e ".[dev]"
```

**A missing declared dependency stops the session in one line** (#297). `tests/conftest.py`'s
`pytest_configure` imports each name in `DECLARED_DEPENDENCIES` (`rich`, `yaml`: the ones whose
absence failed tests rather than skipping them by name) and, if any is missing, exits with code 4:
`the suite runs against its declared dependencies; missing: rich. Run: python -m pip install -e ".[dev]"`.
It imports rather than `find_spec`s, because a shadow package is found without being run. Before
this, a sandbox without `rich` got fourteen assertion failures in `test_ui.py` and `test_progress.py`
that read as "terminal-dependent" and were not. That the *product* works without `rich` is its own
test, `test_ui.py::test_every_command_still_works_without_rich`.

### The inner loop

```bash
python -m pytest -q -n auto -m "not browser and not measured and not scale and not slow"
```

**43 seconds, 3,174 tests.** This is the one to run while you are working, and it is what almost
every change is actually tested by: four tiers are held out, and between them they are 5% of the
suite. The same selection takes 2 minutes 27 serially, so the four cores are most of the win and
the tiers are the rest.

### The rest

```bash
python -m pytest -q -n auto -m "not measured and not scale"   # + the browser tests, 2m21
python -m pytest -q -m "measured or scale"                    # the two that need the machine, 1m18
python -m pytest -q                                           # everything, serially: about 7m30
python -m pytest -q --shuffle-seed 1                          # catch order dependence
HYPOTHESIS_PROFILE=ci python -m pytest -q                     # properties at CI's example count
AGENTDATA_LAPTOP=1 python -m pytest -m laptop                 # the laptop runbook (real tools)
```

```powershell
$env:AGENTDATA_LAPTOP = '1'; python -m pytest -m laptop     # the same from pwsh 7
```

## The tiers, and why they exist

There are 3,443 tests and the whole suite serially takes **about seven and a half minutes** — the
tiers below, one after another. That number is not a complaint about any one test; it is what
happens when 3,400 tests arrive in three weeks and nobody asks what the expensive parts have in
common. Measured on this container, four cores, each tier timed on its own:

| Tier | Tests | Cost | What makes it cost |
| --- | --- | --- | --- |
| the inner loop | 3,174 | 147 s serial, **43 s on 4 cores** | nothing in particular |
| `browser` | 108 | 229 s serial; with the inner loop on 4 cores the two together are 142 s | each one launches Chromium and binds a server |
| `measured` + `scale` | 13 | **78 s, and it must stay serial** | a duration is asserted, or the data is large |
| `slow` | 51 | minutes | builds a wheel in a fresh venv, or spawns three subprocesses per command |
| `laptop` | 23 | — | needs real tools; gated on `AGENTDATA_LAPTOP=1` |

Everything but the last two, in the two passes CI runs on Linux: **3 minutes 40**, against about
7m30 serial. On CI's own hardware the win is larger than this container's: the ubuntu suite step
went from **5m14 to 85 s**.

**108 browser tests are half the wall clock and 3% of the suite.** That is the whole finding, and
the tiers follow from it: the expensive things are expensive for four distinct reasons, and each
reason wants a different treatment.

### `measured` is a scheduling instruction, not a taxonomy

A test that asserts *"this gesture paints inside 50 ms"* passes serially and fails on four workers,
because on four workers it is measuring the contention. That is not a flaky test; it is a test being
asked the wrong question. So `measured` runs last, alone, in CI and locally — and
`tests/test_suite_hygiene.py` reads every assertion in every test file and will not let one that
compares a clock to a ceiling be added without the marker or an entry in `NOT_A_BUDGET` saying why
it is a ceiling on a hang rather than a budget. It scans whole statements rather than lines, and
helpers as well as tests — a budget had already moved into a helper, where a scan of `test_*`
could never have seen it. It is a backstop for the common shape and it says so: a test that builds
its own list of over-budget gestures and asserts the list is empty has no clock and no ceiling for
any pattern to find, and carries the marker because its author put it there.

A verdict on real timings counts as a duration too. `row["verdict"] == "faster"` has no clock and no
ceiling on its line, but when the row came from `bench_node(` it judges two measured runs, and on a
busy runner it judges the contention: the perf loop saw 8.3 ms against 1.2 ms called `same` (#314).
So the scan flags a `["verdict"]` compared to `"faster"`, `"slower"` or `"same"` in any function
that calls `bench_node(`, and leaves alone the verdict tests that run `compare_bench` on fixture
TSVs or on TSVs they write themselves: those measure nothing. The two that do measure,
`test_the_full_loop_on_a_covered_node` and `test_a_genuine_optimisation_passes_the_gate_and_a_slower_one_fails`,
carry the marker, and bench a fixture whose slow version is about 80 times its fast one: the change
is 98-99%, far above the floor that a noisy baseline's wall-time spread lifts.

`scale` keeps it company for a related reason: a 40,000-event fold sharing four cores with three
thousand other tests is the same mistake one layer up.

`slow` predates both and keeps its old job: a test that builds a wheel in a fresh venv, or that
spawns three subprocesses per command the way the two black-box contract cases do, belongs there
rather than in anyone's inner loop. Anything new that would push the inner loop past a minute
should carry one of the three.

### Parallelism

`pytest-xdist` is in the dev extra, and `-n auto` is what the inner loop and CI's **Linux** legs
run for everything outside those two tiers. Three things make that safe, each checked rather than
hoped for: the `suite · shuffled` job runs two seeded orders on every pull request, `isolated_home`
is autouse and hangs every home off the test's own `tmp_path`, and every server the suite starts is
built on port 0.

**Windows runs serially, and that is a finding rather than a preference.** Under `-n auto` the
Windows legs failed on three tries out of four — a *different* fleet test each time, never the same
one twice, never on Linux. Order-independence is not concurrency-independence: `--dist load`
interleaves tests from different modules in one worker, and modules like `tests/test_fleet_console.py`
keep process-level state in `serve` that only a per-module autouse fixture resets. Serially every
test in a file runs contiguously and that reset holds; interleaved it does not. That is the suite's
own weakness, surfaced rather than caused by the tiers, and it is #227. Until it is fixed Windows
runs the way it always has, so the leg costs nothing against what it did before.

The coverage job stays serial on purpose: `coverage run -m pytest -n auto` measures the controller
process and none of the workers, which would quietly report a fraction of the truth.

## Markers

Declared in `pyproject.toml`, and `--strict-markers` is on, so a typo fails collection rather than
silently selecting nothing.

| Marker | Meaning |
|---|---|
| `slow` | builds a wheel in a fresh venv |
| `laptop` | needs real tools and a real machine; gated on `AGENTDATA_LAPTOP=1` |
| `windows` / `posix` | only meaningful on that OS |
| `real_home` | opts out of the isolated home, for tests *about* the real checkout |
| `network` | reaches the network. One test carries it: `tests/test_desk_types.py`'s `tsc`, whose `npx` fetches the pinned compiler until it is cached (#236). `AGENTDATA_OFFLINE=1` skips it without trying; a machine with no Node skips it as well. Adding a second is still a decision |
| `browser` | loads the fleet dashboard in Chromium and asserts on the rendered page |
| `measured` | asserts a duration. Runs with the machine to itself — see *The tiers* above |
| `scale` | cost grows with the repository or the data; correct, and not what an inner loop is for |

### The browser tests, and why they are not optional

The dashboard is HTML that four embedders have to render — Edge, PyCharm's JCEF tool window, VS
Code's Simple Browser, and whatever the operator has on the fourth monitor. Three page-breaking
defects once shipped with a green suite because every test that covered them read the *source text*
of `app.js` and asserted a substring was present. That proves an author wrote a line. It cannot
know that an id selector outranks the user agent's `[hidden]` rule, which is what left five panels
permanently on the glass, swallowing the clicks meant for the grid underneath.

So `tests/test_fleet_desk_regressions.py` asserts on the **rendered page**: computed styles,
hit-testing, and the text a person would read. Chromium is the engine under all three hosts, so one
browser covers the matrix.

```bash
pip install -e ".[dev]"      # playwright is in the dev extra
playwright install chromium  # once per machine
python -m pytest -m browser  # or just `pytest`; they run with everything else
```

They **skip with the reason named** when there is no browser, and never fail for its absence:
`AGENTDATA_CHROMIUM` points at one you already have, which is what a machine that ships a browser
separately from the wheel needs (Playwright pins a build to its own version and otherwise refuses to
start). CI installs chromium on the Linux legs and on the Windows 3.14 leg, so these run there
rather than skipping — a browser test that skips everywhere is the harness that let the defects
through in the first place.

That last sentence was false for days (#296). The isolated home (*Isolation* below) moves `HOME`,
and on Linux and macOS Playwright looks for its browsers under the home (`~/.cache/ms-playwright`,
or `$XDG_CACHE_HOME/ms-playwright`; `~/Library/Caches/ms-playwright`), so every browser test on
both ubuntu legs skipped with `no chromium to drive the page with` and only Windows, whose browsers
live under the untouched `%LOCALAPPDATA%`, ran them. `tests/conftest.py` now resolves the real
browsers directory once, before any test moves `~` (`playwright_browsers_dir`, kept only if it
exists), and `isolated_home` hands it to every test as `PLAYWRIGHT_BROWSERS_PATH` unless that is
already set. A laptop with no Chromium still skips with the reason named, and the reason now says
which `PLAYWRIGHT_BROWSERS_PATH` and `HOME` it looked under.

**In a job that installed a browser, a browser test may fail but never skip.** Such a job sets
`AGENTDATA_REQUIRE_BROWSER=1`, and a `browser`-marked test that skips under it — `launch_chromium`'s
skip, or a `pytest.importorskip("playwright.sync_api")` — is reported as a failure:
`a browser test may not skip in a job that installed a browser: <the skip reason>`
(`browser_skip_is_a_failure`, pinned by
`tests/regressions/test_20260923_any_linux_ci_skipped_every_browser_test.py`). Without the variable
nothing changes.

#### The guards that measure rather than read (#202)

Five of the browser tests assert a *number* rather than a fact, which is how a page stays quick
after the change that makes it slow. Each prints what it measured, and the CI browser leg tees
that into the job summary and uploads the recorded demo beside it.

| Guard | Asserts | In |
| --- | --- | --- |
| idempotence | `draw(el, row)` twice with the same row records **zero** DOM mutations, per component and for the whole page together | `test_fleet_components.py` |
| the motion budget | no duration in `static/` over 320 ms, nothing repeating for ever but `.dot`, and the reduced-motion block reaching the `::view-transition-*` pseudo-elements `*` never matches | `test_fleet_motion.py` |
| frame time | a layout swap of five tiles at 1080p records no `longtask` and hands the main thread back inside 50 ms | `test_fleet_motion.py` |
| the ground | a repaint under 4 ms, and the drift timer off under reduced motion | `test_fleet_trace.py` |
| latency | every marked local gesture under 50 ms, hiding a tile painted against a server held for two seconds, and one round trip per action | `test_fleet_instant.py` |

Two of those deserve their reasoning repeated here, because the obvious version of each is wrong:

* **Frame time is measured as long tasks, not as frame gaps.** A headless runner throttles
  `requestAnimationFrame` to whatever it likes — sixty-six millisecond gaps with the page doing
  nothing at all — so a floor asserted on frame gaps would be a measurement of the runner. What
  the page owns is how long it holds the main thread, and `PerformanceObserver` reports that
  directly. The gaps are printed alongside, because the number is worth having even where it
  cannot be asserted.
* **Round trips are counted with the stream closed and its timers drained.** `refreshSoon` arms a
  timer 400 ms out; with it live, the count is the server's heartbeat rather than the gesture's
  decision.

`tests/test_fleet_engines.py` measures the Chromium column of
[desk-engines.md](desk-engines.md) rather than trusting it, and takes **every** fallback at once —
no view transitions, no pointer capture, no `linear()`, no container queries — which is the worst
engine anybody will meet.

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

**The home moves; Playwright's browsers do not** (#296). On Linux and macOS Playwright finds its
browsers relative to `HOME`, so a temporary home hid them and every browser test skipped. The real
directory is resolved at import, before any test runs, and `isolated_home` sets
`PLAYWRIGHT_BROWSERS_PATH` to it when the machine has one and the variable is not already set.
`HOME` itself stays redirected, and `real_home` tests are untouched.

**No test lists the machine's processes.** The desk's adopt offers come from
`adopt.agent_processes`, which on Windows is a PowerShell `Get-CimInstance Win32_Process` --
seconds to start, more than ten on a loaded runner. Every desk a test served started one each time
the ten-second memo went stale, so the serial Windows browser leg ran a PowerShell and a CIM query
every ten seconds for its whole length, and `adopt`, `start` and a resume ran one synchronously
inside the request a test was waiting on. `_no_process_listing_in_tests` gives every test an empty
process table and a fresh memo; a test about the listing patches `_windows_processes`,
`_posix_processes`, `_list_now` or `agent_processes` itself, and its patch wins.

**A test closes the desk catalogue it opened.** `serve` keeps its sqlite catalogue in a module
global, and a desk fixture that did not swap `_desk` for its own left it open; the next test's
first desk request then closed it in `_fresh()` -- a WAL checkpoint under the desk lock, on that
test's clock, which on the Windows leg was still running three seconds into a five-second wait.
`_a_test_closes_the_catalogue_it_opened` closes it at teardown instead.

**Subprocesses import the checkout** (#297). A test that spawns `python -m agentdata...` with
`cwd=tmp_path` imports `agentdata` only if it is installed or on `PYTHONPATH`: an uninstalled
checkout failed 73 tests with `No module named agentdata`, and an older non-editable install in
site-packages was quietly tested instead of the checkout. Every such spawn passes
`env=agentdata_env(...)` or calls `run_agentdata` (`tests/subproc.py`), which put the checkout first
on the child's `PYTHONPATH`. `tests/test_hygiene_checkout.py` scans `tests/` for an
`sys.executable, "-m", "agentdata..."` argv outside a function that uses one of them; the fake-tool
runner (a standalone script with its own prepend), `test_lifecycle.py` (real venvs) and `tests/laptop/`
are allow-listed with their reasons.

**No test process leaves a child behind** (#317). Every failing Windows job sampled, and a failing
ubuntu one, ended with the runner's cleanup terminating an orphaned `python`. It was a fleet agent:
the fleet tests start the fake `copilot` (`tests/fakes/runner.py`) through the real
`supervisor._spawn`, a passing test waits for it to exit, and a failing one stopped at its assert
with the agent still running. `_a_test_ends_the_agents_it_started` (in `tests/orphans.py`) now
records every agent `_spawn` starts during a test and, at teardown, ends its group with
`proc.kill_tree` and waits on it, bounded; a test that patches `_spawn` itself starts nothing and
replaces the recording. Behind that, `_no_orphans_at_session_end`, a session-scoped autouse fixture
in the same plugin (listed in `pytest_plugins` in `tests/conftest.py`), lists the direct children of
the process that ran the tests when its session ends (`/proc/<pid>/task/*/children`, else a `/proc`
scan, `ps` on macOS, `CreateToolhelp32Snapshot` on Windows, CIM as its fallback) and fails naming the
pid, name and command line of any live `python`, `node`, `chrome` or `headless_shell`. Under xdist
it runs in each worker, because a process a test leaks is the worker's child and the controller's
only children are the workers; the failure is a teardown error on that worker's last test. Being set
up first, it is torn down last, so a session-scoped fixture that starts a browser or a driver must
leave nothing either. A child that is meant to outlive a test is not a thing this suite has: kill
it and wait on it. `tests/test_hygiene_orphans.py` provokes an orphan in an inner session, serially
and with `-n 2`.

Other fixtures: `run_cmd` (an `ad-*` command as a real subprocess — the only way to catch a bare
`sys.exit`, an import-time crash, or an escape sequence that appears only when stdout is a pipe),
`state_file`, `pbip`, `fakes_dir`, `isolated_path`.

## The black-box contract

`tests/test_contract.py` spawns every `ad-*` command as a **real subprocess**, parametrised over
`[project.scripts]`. In-process `main()` calls cannot catch what actually goes wrong in the field:
an import-time crash, a bare `sys.exit`, a traceback on stderr, or an escape sequence that only
appears when stdout is a pipe. Its `run` spawns through `agentdata_env`, so it tests the checkout it
sits in whether or not that checkout is installed (#297).

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

### Nothing here may hang

Three CI runs were killed at their step cap with no failure and no timeline. Two things compounded:

- **A call that structurally could not time out.** On Windows `subprocess.run(capture_output=True,
  timeout=N)` kills the direct child and then re-joins the pipe reader thread *without* a timeout, so
  a surviving grandchild holds it open indefinitely. Measured: a middle process spawning a 40-second
  grandchild, run with `timeout=3`, raised after **40.2 seconds** — the grandchild's lifetime, not
  the timeout. `run_bounded` writes to real files instead, and `agentdata/proc.py` had the identical
  bug in shipped code.
- **A shallow origin repository.** `actions/checkout` clones with `fetch-depth: 1`, a `git clone` of
  the checkout inherits that, and pip's `git clone --filter=blob:none file://<shallow>` then
  registers a promisor remote that can never serve the fetches it promises. The origin is built from
  `git archive` now, and the fixture asserts `--is-shallow-repository` is false so a future clone
  says why instead of hanging.

Three rules follow, and they are what keep it impossible rather than unlikely:

1. **One wall-clock budget, not a timeout per command.** The per-call timeouts sum to hours against a
   ten-minute step, so bounding each call individually could never bound the test. `AGENTDATA_LIFECYCLE_BUDGET_S`
   (default 540) makes the test lose to itself, with a named command, before it can lose to CI.
2. **Every command announces itself before it waits**, on stderr, flushed. Printed afterwards it says
   nothing about the one command that never returned.
3. **The inner timeout must be smaller than the outer one.** `ad-update`'s own `--timeout` defaulted
   to 600 inside a 420-second bound, so the product's timeout path could never fire; the test passes
   240.

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

## When CI is red

A red check becomes a reproduced cause, never a re-run into green (#316). On 23 Sep, 5 of the 9 pushes to
`main` were red or cancelled, all on `windows · python 3.14`, and the answers were re-runs, per-test wait tweaks
and cap raises. None of them named a cause.

1. **Record it before any re-run.** A red check that passes on re-run is a finding, never "a flake": "flake" is
   not a root cause. Before any re-run, open an issue from the flake template
   ([`.github/ISSUE_TEMPLATE/flake.md`](../.github/ISSUE_TEMPLATE/flake.md)) with the job URL, the node id, the
   full failure output (including what `_explain_the_page` printed), the commit, and the runner OS and Python.
2. **Reproduce before fixing.** Run `-n 8` on 4 cores, several concurrent copies of the one test, or the
   deterministic trick the cause needs (a late real answer patched in after a stub, as commit a42e0df did). #307
   adds a CPU throttle and a stress script to this list. Paste the reproduction in the issue.
3. **Fix the cause**: a missing condition, a stub race, a leaked global, a product defect. A product defect gets
   a regression file, `tests/regressions/test_<yyyymmdd>_<any|shell>_<short>.py`, quoting what the runner
   printed (see *The regression convention*).
4. **Never** skip, xfail, quarantine or deselect a test; add a fixed wait; raise a ceiling or a cap without a
   reproduction showing the ceiling is the only problem; re-run until green and merge.

**Every pytest job is required in practice**, `windows · python 3.14` included, before and after #311 splits
that job: the operator waived 3.14 for K (PR #275) only, and no job is advisory. **Merging over red is the
operator's call, one PR at a time**: it happens only at the operator's word for that PR, and its merge message
names the check and links its flake issue. Branch protection is the operator's setting and is not changed here;
the `flake` label the template applies is created by the operator. `tests/test_hygiene_flake_policy.py` keeps
this section, the template and the rule together.

## What CI runs

A red job is handled as *When CI is red* says: a flake issue and a reproduction first, never a re-run into green.

| Job | What it proves |
|---|---|
| `ubuntu · 3.12 / 3.14` | the suite on the floor and on the laptop's Python: the bulk on every core, then `measured` + `scale` with the machine to themselves, then `slow` serially. The 3.12 leg first type-checks the desk, `tsc --noEmit` with a pinned compiler ([desk-types.md](desk-types.md), #236) |
| `windows · 3.12 / 3.14` | the same tiers but **serially** (see *Parallelism* — #227), plus pwsh 7 / Git Bash / cmd smoke steps, under both `core.autocrlf` settings |
| `floor · pip refuses the wheel on 3.11` | `Requires-Python` really stops an older interpreter, in the words the user sees |
| `lint · shellcheck + PSScriptAnalyzer` | the shipped scripts parse and target the right floors |
| `lint · bash 4.4 and pwsh 7 floors` | no post-4.4 construct in anything we ship or emit; the laptop suite never executes here |
| `coverage · per-module floors` | the seven Windows-critical modules stay covered; report uploaded as an artifact |
| `suite · shuffled` | two seeded shuffles, to catch fixture leakage. Serial on purpose: under `-n` the order a test runs in is the scheduler's, not the seed's, and the job would stop proving anything |
| `windows · 3.14` (the `slow` marker) | the install/update lifecycle, in real venvs, on the OS where packaging goes wrong |
| every job | `HYPOTHESIS_PROFILE=ci`, so the property tests search 200 examples rather than 50 |
| every pytest step that installed Chromium | `AGENTDATA_REQUIRE_BROWSER=1` and `-rs` (#296): both ubuntu legs and the Windows 3.14 leg (a `require_browser` matrix field; the 3.12 leg installs no browser and leaves it empty). A skipped `browser` test fails there, and every other skip prints its reason |
