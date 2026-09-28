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
| `tests/test_fleet_ink_cues.py` | the cue contract for every ink skin that ships cues (#373): read from the sources, no browser, under 2 s |
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

**4,203 tests, about two minutes on four cores** (116 s on 27 Sep 2026, on a container whose four
cores three builders shared). This is the one to run while you are working, and it is what almost
every change is actually tested by: four tiers are held out, and between them they are 411 tests,
8.9% of the suite. Its 23 `laptop` tests are selected and skip (§Markers).

### The rest

```bash
python -m pytest -q -n auto -m "not measured and not scale"   # + the browser tests: ~25 min of test time
python -m pytest -q -m "(measured or scale) and not slow"     # the two that need the machine, 2m27
python -m pytest -q                                           # everything, serially: ~34 min of test time
python -m pytest -q --shuffle-seed 1                          # catch order dependence
HYPOTHESIS_PROFILE=ci python -m pytest -q                     # properties at CI's example count
AGENTDATA_LAPTOP=1 python -m pytest -m laptop                 # the laptop runbook (real tools)
```

```powershell
$env:AGENTDATA_LAPTOP = '1'; python -m pytest -m laptop     # the same from pwsh 7
```

## The tiers, and why they exist

There are 4,614 tests (`--collect-only`, 27 Sep 2026), and the whole suite serially takes **about 34
minutes of test time** on CI's Linux runners, three quarters of it the browser tier
(`tests/durations.json`, one green run; §Step budgets). That number is not a complaint about any one
test; it is what happens when thousands of tests arrive in weeks and nobody asks what the expensive
parts have in common. The counts are by tier marker, so a test in two tiers counts in both (8 are
`browser` and `measured`, 1 is `browser` and `slow`, 2 are `measured` and `scale`):

| Tier | Tests | Cost | What makes it cost |
| --- | --- | --- | --- |
| the inner loop | 4,203 | 374 s of test time on CI's Linux; **116 s on 4 shared cores** here | nothing in particular |
| `browser` | 349 | about 1,525 s of test time on CI's Linux: two whole-file shards per run (#312) | each one launches Chromium and binds a server |
| `measured` + `scale` | 19 (15 and 6) | **147 s here, and it must stay serial** | a duration is asserted, or the data is large |
| `slow` | 52 | about 67 s on CI's Linux, 138 s on Windows | builds a wheel in a fresh venv, or spawns three subprocesses per command |
| `laptop` | 23 | — | needs real tools; gated on `AGENTDATA_LAPTOP=1` |

The "here" times are this container's on 27 Sep 2026, each tier on its own, while other builders
shared its four cores; the rest are the summed test times in `tests/durations.json`. Which job runs
each tier, and how, is the generated matrix in *What CI runs*.

**349 browser tests are three quarters of the test time and 8% of the suite.** That is the whole finding, and
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

**A clock read inline counts, and so does a browser nobody marked** (#602). The scan sees
`time.monotonic() - t0 < 0.2` and `time.time() - start < 5`, the shape the wrap-up sweep's 0.2 s
bound had when a Windows runner took 0.735 s (#590), and it opens `regressions/` and `laptop/` as
well as `tests/`. The same file fails a module that imports Playwright or the desk harness
(`test_fleet_desk_browser`) with no `browser` marker in it, and each of its tests that starts
Chromium, itself or through the module's own fixtures, without one: an unmarked Chromium test runs
in the default tier, gets none of the page diagnostics and escapes the browser shards.

**A `measured` result means something only when the test ran serially** (#473, operator ruling
(a)). `test_a_gesture_keeps_its_budget_while_the_ink_draws` went over its 50 ms budget under
`-n auto` on two branches, and a diagnostic ran its six gestures with the ink drawing, at rest and
off (`?ink=off`) beside six concurrent `test_fleet_ink_glass.py` runs. The ink made no difference:
it breached with the ink drawing (114 ms) and with it off alike (126 and 81 ms). Every breach was
`arrange:move`, the gesture with the most layout, and it came from other Chromium renderers
competing for the cores, which six plain CPU spinners did not reproduce. The ink draws in `requestAnimationFrame`, after the
synchronous task a gesture's mark closes in, so it cannot land inside a mark. CI runs the tier in
its own step after the bulk, `python -m pytest -q -rs -m "(measured or scale) and not slow"`, with
no `-n`. So read a breach under `-n` or next to another browser as contention, not as evidence
against a branch, and re-run the test on its own before calling it a regression. The budget stays
at 50 ms.

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
hoped for: the `suite · shuffled · seed <n>` jobs run two seeded orders on every pull request (and
`suite · shuffled · browser · shard K/2` shuffles the browser tier, #312), `isolated_home`
is autouse and hangs every home off the test's own `tmp_path`, and every server the suite starts is
built on port 0.

**Windows runs serially, and that is a finding rather than a preference.** Under `-n auto` the
Windows legs failed on three tries out of four — a *different* fleet test each time, never the same
one twice, never on Linux. Order-independence is not concurrency-independence: `--dist load`
interleaves tests from different modules in one worker, and modules like `tests/test_fleet_console.py`
keep process-level state in `serve` that only a per-module autouse fixture resets. Serially every
test in a file runs contiguously and that reset holds; interleaved it does not. That is the suite's
own weakness, surfaced rather than caused by the tiers, and it is #227. **The cause is fixed at its
root** (#298): the desk's process state now has one owner that resets all of it for every test
(§Isolation), and a test that leaves a desk server thread running fails where it did it. Windows
stays serial **within each shard** (#311: whole files per job, below) until #313 tries `-n auto` inside them.

**Shards** (#310). `--shard=K/N` (1-based; `tests/shard.py`, listed in conftest's `pytest_plugins`) keeps
the K-th of N shards of whatever the rest of the command line selected, and prints
`shard K/N: <files> files, <tests> tests, ~<s> s estimated`. A shard is made of **whole files**, never single
tests, so a module still runs contiguously in one process, as the serial Windows run relies on. Its hook runs
last, after the `--shuffle-seed` shuffle and after `-m`/`-k`, so it sees only selected tests and keeps their
order: a shuffled shard stays shuffled. Files are packed greedily, longest first, ties by path, by their time
in `tests/durations.json` (#309, `{os: {file: {tier: seconds}}}`), counting only the **tiers of the file's
selected tests**: a file whose browser tests `-m "not browser"` dropped weighs only its `default` seconds. The
current OS's entry is used first (`windows` on nt, else `linux`), then the other OS's, then the median of the
known files; with no table every file weighs the same and the shards split by count. Every process that
collects the same selection computes the same shards, so `-n` works too (each xdist worker keeps the same
files; the estimate line is printed only by a serial run). **The union guarantee**: the N shards' node ids are
pairwise disjoint and add up to exactly the selection. `tests/test_hygiene_shards.py` checks the packing, the
weighting and the plugin in a throwaway project serially and under `-n 2`; the `scale` test
`test_the_expensive_tiers_are_a_small_part_of_the_suite` checks the real suite's `--shard=K/3`, with and without
`-m`, under `--shuffle-seed`. Windows runs in shards (#311, *What CI runs*); Linux is #312.

**The Windows shards** (#311). The one serial Windows 3.14 job outgrew every cap it was given (its pytest step
took 28-32 minutes of 35), so Windows is four parallel jobs on 3.14, each capped at 20 minutes: three
`--shard=K/3` jobs that select exactly what the old step did (`not slow and not measured and not scale`), checked
out with `core.autocrlf true` (Git for Windows' default), and a `packaging and shells` job with `core.autocrlf
false` (#591: 3.14 is the only Python). A shard is whole files, so each module still runs
contiguously in one process, which is what #227 needs. The `windows` times in `tests/durations.json` put each
shard near 9.3 minutes; a file the table does not know weighs the median, so a
new or renamed file can unbalance the shards until the table is refreshed (§Step budgets). What each job runs is
decided by its matrix row and each step's `if:`, and `tests/test_hygiene_windows_shards.py` checks that locally:
it expands the rows as Actions does, evaluates every `if:`, and checks that every shard K/3 exists once, that
every job is 3.14 and installs and requires Chromium, that the shards check out with `autocrlf true` and
packaging and shells with `false`, that each shell, encoding and floor step runs in exactly one job, and that each
job reports its own junit
files against its caps into an artifact of its own name. How long a shard takes, and whether the job names still
match any required status check, only a run shows.

**The Linux browser shards** (#312). The page does not depend on the Python version, so Linux runs the browser
tier (`browser and not slow and not measured and not scale`) once per run, in two `--shard=K/2` jobs
(`ubuntu · python 3.14 · browser · shard K/2`, under `-n 2`), and once more shuffled on seed 1 in two serial
`suite · shuffled · browser · shard K/2` jobs, where it had never run: the old `suite · shuffled` job installed no
browser and every browser test skipped. The one ubuntu leg (#591: 3.14 only) deselects `browser` from its
parallel step and keeps Chromium for the browser tests that are also `measured` or `slow`, the desk's
measurements and the demo. `suite · shuffled` is one job per seed
(`suite · shuffled · seed 1`, `suite · shuffled · seed 20260904`), each the whole non-browser suite, serially,
and `coverage` deselects `browser` rather than relying on its skip. `tests/test_hygiene_linux_shards.py`
expands every ubuntu job and evaluates each step's `-m` with pytest's own marker grammar: the tier runs in
exactly those four jobs, each shard once, every job that installs Chromium requires it, and no job that does
not selects a browser test.

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
start). CI installs chromium on the ubuntu leg, the Linux browser jobs and every Windows job (the matrix in
*What CI runs* says which tier runs in each), so these run there
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

#### Writing a browser test (#299)

Write it on the harness, `tests/desk_harness.py` (a plugin `tests/conftest.py` lists in
`pytest_plugins`). Each xdist worker, or the one serial process, starts **one** Playwright driver
and **one** Chromium, lazily, for the first test that asks for `desk_browser`, and keeps them to the
end; every page is a fresh context, closed when its test ends. A worker that runs no browser test
starts no Node. Starting a driver and a browser per test cost about 0.65 s each time; a context on a
browser that is up costs under 0.1 s.

| Fixture | Gives |
| --- | --- |
| `desk_server` | a desk served on a daemon thread: `.url(extra="")`, `.token`, `.port`, `.base`, `.server`; stopped at teardown |
| `desk_browser` | the worker's Chromium (from `launch_chromium`, relaunched if a test closed it); the contexts the test made are closed at teardown |
| `new_desk_page` | `open(desk, extra="", *, width=1400, height=900, reduced=False, init_scripts=())` → `(page, record)`: a fresh context with `COUNT_FETCHES` and `desk_waits.COUNT_TIMERS` installed (as on every `desk_page`); `record` keeps page errors, console errors and warnings, failed requests and non-2xx answers |
| `no_desk_driver` | no shared driver in this thread, for a test that needs `asyncio.run` |
| `desk_chromium_with` | `launch(args)`: a Chromium of the test's own on the worker's driver, started with extra switches (a Blink flag), closed at teardown |

```python
@pytest.mark.browser
def test_the_open_pane_is_full(fleet_home, tmp_path, desk_server, new_desk_page):
    _desk_of(tmp_path)                       # the agents, before the page asks for them
    page, record = new_desk_page(desk_server, width=1400, height=900)
    page.wait_for_selector('.tile.is-solo[data-tier="full"]', timeout=15000)
    assert page.evaluate("() => openName()") == "alpha"
    assert not record["errors"], record
```

No `pytest.importorskip("playwright.sync_api")` of its own and no `browser.close()`: the harness does
both. `with sync_playwright()` is gone from the tests (#303): every browser test is on the harness,
and `tests/test_hygiene_harness.py` fails on a `sync_playwright(` anywhere under `tests/` but the
harness, or a `launch_chromium(` outside it, and says to use `desk_server`/`new_desk_page` instead.
A module `browser` fixture is `desk_browser` under its old name. `tests/test_fleet_desk_browser.py` and
`tests/test_fleet_ink.py` are the pattern; `test_fleet_ink`'s `_serve`, `_stop` and `_open` are thin
wrappers over the harness, so the modules that import them keep working.

#### Settle, then assert (#304)

A browser test waits for the desk one way: `tests/desk_waits.py`. `settle(page, also=...)` waits
until six frames in a row pass with nothing moving -- no fetch in flight, no `setTimeout` of 1000 ms
or less pending, no DOM write, the fonts loaded, no animation but the live `.dot`, the ink layer off
or at rest and not rendering (`allow_ground=True` lets a moving ground draw) -- and `also`, a JS
expression that holds a skin's or a test's own condition, true. When nothing has moved it on for
`DESK_WAIT_MS` (30 s; a frame the ink layer draws is moving on, a pen that never lifts is not) it
prints the page and raises `the desk never settled: <what was still moving>`. There is no other
ceiling, and no pause "to let it settle".

A negative assertion is observed over page work, never over a duration. `assert_idle(page)` settles,
replays `/api/fleet` byte for byte, and drives `refresh(); place(); redrawAll(); bell();` eight times
under one observer over the whole document: zero writes, and zero ink frames unless the ground
moves (`ground_moves=True`). Each pass ends when the work it started is done -- no fetch in flight,
no short timer pending -- plus two frames, so a write a timer makes 300 ms later is inside the
window. `observe_quiet(page, passes=, drive=False)` leaves the page alone and counts its own work (a
refresh it starts itself, a retry it arms) as the passes. An observer that records what an action
writes is `record_mutations(page, ...)` (or `WATCH`'s `__deskWaits.watch(node)` inside page code);
`new MutationObserver` appears under `tests/` only in `desk_waits.py`, and `tests/test_desk_waits.py`
keeps it so. `AGENTDATA_DESK_WAIT_SCALE` scales the ceiling for a local throttled run; CI never sets
it.

No fixed waits is enforced (#306): `tests/test_hygiene_ratchet.py::test_no_flat_waits` fails on any
`.wait_for_timeout(...)` under `tests/`, on a `time.sleep` in a browser file outside a polling loop
that fails at its deadline, and on page code that awaits a fixed `setTimeout` promise. What counts, and
the baseline, are in [Flat waits, skips, xfail and deselection are ratcheted](#flat-waits-skips-xfail-and-deselection-are-ratcheted).

#### The guards that measure rather than read (#202)

Five of the browser tests assert a *number* rather than a fact, which is how a page stays quick
after the change that makes it slow. Each prints what it measured, and the CI browser leg tees
that into the job summary and uploads the recorded demo beside it.

They share the worker's browser like every other browser test (#303), and it starts at fixture
setup, so no timed window includes a driver or a Chromium starting.

| Guard | Asserts | In |
| --- | --- | --- |
| idempotence | `draw(el, row)` twice with the same row records **zero** DOM mutations, per component and for the whole page together | `test_fleet_components.py` |
| the motion budget | no duration in `static/` over 320 ms, nothing repeating for ever but `.dot`, and the reduced-motion block reaching the `::view-transition-*` pseudo-elements `*` never matches | `test_fleet_motion.py` |
| frame time | a layout swap of five tiles at 1080p records no `longtask` and hands the main thread back inside 50 ms | `test_fleet_motion.py` |
| the ground | a repaint under 4 ms, and the drift timer off under reduced motion | `test_fleet_trace.py` |
| latency | every marked local gesture under 50 ms, hiding a tile painted against a server held for two seconds, and one round trip per action | `test_fleet_instant.py` |

The payload budgets are plain tests. Each measures what the server sends (`serve.static_body`, gzip level 6), and
none is raised by a card (decisions 18 and 19 on #429):

| Budget | Holds | In |
| --- | --- | --- |
| the static payload | every file in `static/` and `static/ink/` under 200 KiB, `m.html` and `m.css` included | `test_fleet_serve.py` |
| `MAP_BUDGET` | `static/map/**/*.js` outside `map/skins/` under 32 KiB; `map.html` + `map.css` under 4 KiB of the 200 | `test_fleet_serve.py` |
| `M_BUDGET` | `static/m/**/*.js` under 4 KiB (P-15; `m/m.js` was 2,746 B at #581); `m.html` + `m.css` under 4 KiB of the 200 | `test_fleet_serve.py` |
| `INK_BUDGET`, `FX_BUDGET` | the ink layer's modules, and `fx.js` on its own ([desk-ink.md](desk-ink.md) §Budgets) | `test_fleet_ink.py` |

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

**The desk's process state is reset for every test** (#298). `agentdata/fleet` keeps state in
module globals -- the desk's selection and handles in `serve` (`_desk`, `_selection`,
`_desk_loaded`), the refresh floor, the measure asks, `_desk_written`, `_read_order`, `LOADED`,
`_SERVING`, and the caches in `fingerprint`, `poll` and `trace` -- which is right for one
long-running `ad-fleet serve` and wrong for a suite where every test has its own fleet directory.
Thirty-five modules used to reset parts of it by hand, eight different ways, and none reset all of
it: sixteen left the refresh floor, thirty-four carried the last test's `last_renew` forward. They
are gone. `FLEET_PROCESS_STATE` in `tests/conftest.py` names every such global; its import-time
value is deep-copied once per process in `pytest_sessionstart`, and the autouse
`_fresh_fleet_process_state` hands each test a fresh copy (and `_read_order` a new run id), which
monkeypatch puts back afterwards. A test that needs a particular desk sets it up itself.
`tests/test_hygiene_process_state.py` scans `agentdata/fleet/*.py` for module-level mutable values
and names rebound through `global`, and fails naming any that is neither in the table nor
allow-listed there with its reason; add a new cache to the table, not a fixture to your module.
Beside it, `_a_test_leaves_no_server_thread_running` records the threads alive when a test starts
and, at teardown, waits up to ten seconds for any `(serve_forever)`, `(process_request_thread)` or
`adopt-listing` thread the test started; one still alive fails the test with its name and stack.
The same file proves that on an inner session that forgets to shut its server down.

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
and with `-n 2`. Its sleeper says `ready` before the test goes on. `Popen` can return while the child
is still inside `execve`, and until that finishes `/proc/<pid>/cmdline` shows the parent's command
line, or nothing. On a loaded runner the guard read it in that window (#459).

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

## Flat waits, skips, xfail and deselection are ratcheted

`tests/test_hygiene_ratchet.py` (#306) reads every file under `tests/` once with `ast` -- no test
module is imported -- through `.github/scripts/hygiene_baseline.py`, and holds the tree to
`tests/hygiene_baseline.json`:

- **Flat waits: none.** A call to an attribute named `wait_for_timeout`; a `time.sleep` in a file
  that imports playwright, `desk_harness` or `desk_waits` (or takes `desk_browser`/`new_desk_page`),
  unless it is inside a `while` loop that fails at its deadline -- an `assert` or `raise` in the loop,
  in its `else`, or as the statement right after it; and a string outside `tests/desk_waits.py` with
  `new Promise(go => setTimeout(go, <ms>))` in it. A delayed stub (`setTimeout(() => go(...), 1500)`)
  is not a wait. The fix is a condition: `page.wait_for_function`, `settle`, `observe_quiet`.
- **Fall-through loops: per file, down only.** A polling `while` around a `time.sleep` in a browser
  file that runs out its deadline and carries on. Give it its `assert` or `raise` and lower the count.
- **Skips: per file, down only.** `pytest.skip(`, `pytest.mark.skip`, `pytest.mark.skipif` and
  `pytest.importorskip(`; 0 for a file the baseline does not list. A `skipif` whose condition is only
  an `os.name`/`sys.platform` comparison, on a function marked `windows` or `posix`, is the platform's
  label and is not counted.
- **xfail: none.** `pytest.xfail(` or `pytest.mark.xfail`.
- **Deselection: none.** No `--deselect`, `-k`, `--ignore` or `--ignore-glob` in a `tests.yml` pytest
  command or in pyproject's `addopts`, and no `collect_ignore` in a conftest.
- **Tests: per file, up only.** The `def test_*` in each file.

Each failure names the file and line and the fix. After removing a skip or fixing a loop:

```bash
python .github/scripts/hygiene_baseline.py --update   # lowers skips and loops, raises tests
```

It never moves a count the other way: it prints the file and exits 2. A platform-only test keeps its
`windows`/`posix` marker and its `skipif`; raising the skip baseline for anything else, or lowering a
test count for a test that was merged into another, is a hand edit of the baseline with the reason in
the commit message, as with coverage floors. `test_the_baseline_is_the_tree_as_counted` keeps the
file current, so a count that fell cannot quietly rise again.

## The agent PR check

The lanes of docs/developing-with-agents.md §7 are data in `.github/agent-lanes.json`, and
`.github/scripts/agent_pr_check.py` checks a branch against them before anyone reviews it (#324). It is a gate in the
handover note, not a CI job:

```bash
python .github/scripts/agent_pr_check.py --base origin/main                  # every lane the branch touched
python .github/scripts/agent_pr_check.py --base origin/main --lane serve     # and nothing sequenced beyond serve
python .github/scripts/agent_pr_check.py --base origin/main --allow ci       # the operator approved the ci lane
```

It diffs from `git merge-base <base> HEAD`, so what `main` did after the branch point, merged in, is never the
branch's. It prints one `lane | kind | file` row per touched file (`-` for a file no lane owns; `pyproject.toml` is
split by the dotted keys a lane names, `tool.pytest.ini_options` in `ci` and `project.version` in `version`), then
`violations: N`.

- **Refused (exit 1):** a `frozen` lane (`ci`, `relay`) or the `release-only` `version` lane touched; with `--lane`,
  an `exclusive` or `sequenced` lane touched that the branch did not declare.
- **`--allow <lane>`** lists that lane's violations under `allowed:` instead. The PR links the operator's approving
  comment.
- **Warnings only:** a `shared-docs` file that lost lines (append your row, never rewrite another's), two `exclusive`
  lanes in one branch, and uncommitted changes.
- **Cannot run (exit 2):** an unknown `--base` says to run `git fetch origin`.

Globs match with `fnmatch.fnmatchcase` on the posix path, so `*` crosses `/`. Every glob and toml key must match
a tracked file or an existing key (`tests/test_agent_pr_check.py` holds the map to the checkout), except those under
`planned`: files an open card will create, such as `ink/fx.js`, which move to `paths` once they exist.
`skin:<name>` expands to one lane per `static/ink/skins/*.js` module (`skin:voxel`).

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
   deterministic trick the cause needs (a late real answer patched in after a stub, as commit a42e0df did), or
   the two tools in *Reproducing a CI-only failure* below: `--desk-cpu-throttle` and
   `.github/scripts/stress_one.py` (#307). Paste the reproduction in the issue.
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

## Reproducing a CI-only failure

A runner is 1.5 to 3 times slower than a laptop, and Windows-only failures were fixed by guessing because
nobody could make a laptop that slow (#307). Two tools do it, and both are local: CI runs neither, and neither
is a reason to raise a ceiling.

| Tool | What it slows | What it does not slow |
| --- | --- | --- |
| `--desk-cpu-throttle=RATE` (or `AGENTDATA_DESK_THROTTLE=RATE`; default 1) | the main thread of every desk page the harness opens (`tests/desk_harness.py` `desk_page`, so `new_desk_page` and every helper on it): CDP `Emulation.setCPUThrottlingRate`, sent again whenever the page's main frame navigates, because a navigation to another site starts a new renderer process unthrottled | the Python server, the Playwright driver, and Chromium's GPU process |
| `python .github/scripts/stress_one.py NODEID [--copies 8] [--rounds 2] [--throttle 1] [--timeout 600]` | everything, by contention: `--copies` processes of the one test fight for the CPU at once, as the tests on a loaded runner do; `--throttle` passes the option above to each copy | nothing in particular: it is the whole machine that is slow, not one thread |

```
python -m pytest -q -m browser tests/test_fleet_ink_glass.py --desk-cpu-throttle=4
python .github/scripts/stress_one.py tests/test_fleet_ink_glass.py::test_the_ground_drifts_only_when_motion_is_allowed_and_the_idle_desk_writes_nothing
```

The numbers they were chosen on, in this suite's headless Chromium: a fixed JS loop took 43 ms at rate 1 and
171 ms at rate 4; 8 copies over 2 rounds of
`test_fleet_ink_glass.py::test_the_ground_drifts_only_when_motion_is_allowed_and_the_idle_desk_writes_nothing`
took about 115 s each, about 11x slower than under `-n 4`, and all 16 passed.

**Where the throttle does nothing.** CDP CPU throttling is Chromium's, and on Windows it suspends the page's
main thread from a second thread every 200 µs. On most hosts that works: on 18 of 20 Windows runners sampled in
run 36349924909 (AMD EPYC 7763 and 9V74, Xeon Platinum 8370C and 8573C) a CPU-bound loop ran 3.5 to 5.5 times
slower at rate 4, and on Linux 4 to 4.7 times, whatever the loop's length (15, 60 or 250 ms). On the other two,
both **AMD EPYC 9V45** hosts, it ran 1.04 to 1.23 times slower at rates 2, 4 and 8 alike: the throttle has no
effect there, and that is what failed train 20 (`{1: 15, 4: 17.4}`, run 36346175771). The loop's length is not
the cause, and neither is Windows' 15.6 ms timer. So:

- the option measures before it trusts: with `--desk-cpu-throttle` over 1, `desk_browser` times the fixed loop
  on a page at rate 4 against one at rate 1, once per process, and when it is under 2x slower every test that
  asks for the browser fails with the measured figure and the machine's CPU, instead of running unthrottled;
- the check in `test_a_gesture_keeps_its_budget_while_the_ink_draws` holds the 3x bar everywhere except on
  Windows on a host in `THROTTLE_HAS_NO_EFFECT_ON` (the EPYC 9V45), where it asserts that the throttle still
  does nothing and that the option is refused. A CI job that lands on such a host checks that; the day the
  throttle starts working there, it fails and the host comes off the list.

On a macOS runner (Apple M1, virtual) the throttle is partial: 3.3 to 4.9x at rate 4 in some probes, 2.2 to
2.8x in others, so the 3x check can fail on a Mac; CI runs no macOS browser job.

`stress_one.py` prints a TOON table, `round, copy, outcome, seconds`, and exits 1 when any copy did not pass.
An outcome is `passed` (exit 0), `failed` (any other exit) or `timeout`. Every copy is started with
`agentdata.proc.run`, which on POSIX gives it a session of its own and on a timeout kills the whole tree, so a
copy that ran out of time leaves no driver or Chromium behind. `tests/test_stress_one.py` drives it with the
node ids in `tests/fixtures/stress_one/target.py`, and
`test_fleet_ink.py::test_a_gesture_keeps_its_budget_while_the_ink_draws` checks the throttle (a loop at rate 4
takes at least three times as long, before and after a navigation to another site, except on the one host
where it is measured to do nothing, above).

## What CI runs

A red job is handled as *When CI is red* says: a flake issue and a reproduction first, never a re-run into green.

### Which tier runs where

<!-- tier-matrix:start -->
Generated from `.github/workflows/tests.yml` by `tests/tier_matrix.py`; refresh with `python tests/tier_matrix.py --write`. A cell names how the tier runs there: `parallel` (`-n auto`), `2 workers` (`-n 2`), `serial`, `shuffled` (serial, `--shuffle-seed`), `N shards` (whole-file `--shard=K/N` jobs), `named files` (a step that names its test files runs only the tiers those files hold, per `tests/durations.json`), `gated` (selected, and skipped unless `AGENTDATA_LAPTOP=1`), `SKIPS` (a `browser` test selected where no Chromium is installed), or `—` (not selected). `+` joins two steps.

| Tier | ubuntu · 3.14 | windows · 3.14 |
|---|---|---|
| `default` | parallel + parallel, named files + serial + serial, named files + shuffled + shuffled (2 seeds) | 3 shards, serial |
| `browser` | 2 shards, 2 workers + 2 shards, shuffled + serial, named files | 3 shards, serial |
| `measured` | serial + shuffled + shuffled (2 seeds) | serial |
| `scale` | serial + shuffled + shuffled (2 seeds) | serial |
| `slow` | serial + shuffled + shuffled (2 seeds) | serial |
| `laptop` | gated | gated |
| `browser+slow` | serial | serial |
| `browser+measured` | serial + serial, named files | serial |
| `measured+scale` | serial + serial, named files + shuffled + shuffled (2 seeds) | serial |
| `laptop+measured` | gated | gated |

Per job, as the checks are named:

| Job | `default` | `browser` | `measured` | `scale` | `slow` | `laptop` | `browser+slow` | `browser+measured` | `measured+scale` | `laptop+measured` |
|---|---|---|---|---|---|---|---|---|---|---|
| `smoke · install, doctor, entry points and hygiene` | parallel, named files | — | — | — | — | — | — | — | — | — |
| `ubuntu-latest · python 3.14` | parallel + serial, named files | serial, named files | serial | serial | serial | gated | serial | serial + serial, named files | serial + serial, named files | gated |
| `ubuntu · python 3.14 · browser · shard 1/2` | — | 2 workers | — | — | — | — | — | — | — | — |
| `ubuntu · python 3.14 · browser · shard 2/2` | — | 2 workers | — | — | — | — | — | — | — | — |
| `windows · python 3.14 · shard 1/3` | serial | serial | — | — | — | gated | — | — | — | — |
| `windows · python 3.14 · shard 2/3` | serial | serial | — | — | — | gated | — | — | — | — |
| `windows · python 3.14 · shard 3/3` | serial | serial | — | — | — | gated | — | — | — | — |
| `windows · python 3.14 · packaging and shells` | — | — | serial | serial | serial | — | serial | serial | serial | gated |
| `lint · bash 4.4 and pwsh 7 floors` | serial, named files | — | — | — | — | — | — | — | — | — |
| `coverage · per-module floors` | serial | — | serial | serial | serial | gated | — | — | serial | gated |
| `suite · shuffled · seed 1` | shuffled | — | shuffled | shuffled | shuffled | gated | — | — | shuffled | gated |
| `suite · shuffled · seed 20260904` | shuffled | — | shuffled | shuffled | shuffled | gated | — | — | shuffled | gated |
| `suite · shuffled · browser · shard 1/2` | — | shuffled | — | — | — | — | — | — | — | — |
| `suite · shuffled · browser · shard 2/2` | — | shuffled | — | — | — | — | — | — | — | — |
| `suite · shuffled · seed of the day` | shuffled | — | shuffled | shuffled | shuffled | gated | — | — | shuffled | gated |
<!-- tier-matrix:end -->

`tests/test_hygiene_tier_matrix.py` keeps the block equal to the workflow (its failure names the refresh
command), every tier but `laptop` on at least one Linux and one Windows job, and no `SKIPS` cell anywhere; the
`scale` test `test_the_expensive_tiers_are_a_small_part_of_the_suite` fails when a test carries a combination of
tier markers the matrix does not list (#315). The table below is the prose per job.

### What each job proves


| Job | What it proves |
|---|---|
| `changes · which groups a filter would run (report only)` | which groups of `.github/ci-paths.json` the PR's diff (or the push's range) touches, and in its job summary which jobs a path filter *would* skip (#593). Report only: every job `needs:` it and none reads its outputs, so nothing is skipped until #596. A path no group names, a push, a dispatch and an empty diff all mean everything |
| `ubuntu-latest · python 3.14` | the suite on the floor, which is also the laptop's Python (#591): the bulk on every core without the browser tier, then `measured` + `scale` with the machine to themselves, then `slow` serially. It first type-checks the desk, `tsc --noEmit` with a pinned compiler ([desk-types.md](desk-types.md), #236), and keeps Chromium for the `browser` tests that are also `measured` or `slow`, the measurements and the demo (#312) |
| `ubuntu · python 3.14 · browser · shard K/2` (K = 1, 2) | the browser tier (`browser and not slow and not measured and not scale`), once per run, in two whole-file shards under `-n 2`, with Chromium (#312) |
| `windows · python 3.14 · shard K/3` (K = 1..3) | the tiers the ubuntu legs run in parallel, as three whole-file shards (#311), each **serially** (see *Parallelism* — #227), with Chromium, `core.autocrlf true` (Git for Windows' default; #591) |
| `windows · python 3.14 · packaging and shells` | `measured` + `scale` with the machine to themselves, the `slow` tier, and the pwsh 7 / Git Bash / cmd smoke, completion, encoding and 5.1-refusal steps, `core.autocrlf false` |
| `floor · pip refuses the wheel on 3.13` | `Requires-Python: >=3.14` really stops an older interpreter, in the words the user sees |
| `lint · shellcheck + PSScriptAnalyzer` | the shipped scripts parse and target the right floors |
| `lint · bash 4.4 and pwsh 7 floors` | no post-4.4 construct in anything we ship or emit; the laptop suite never executes here |
| `coverage · per-module floors` | the seven Windows-critical modules stay covered; report uploaded as an artifact. No browser is installed, so `-m "not browser"` (#312) |
| `suite · shuffled · seed <n>` (n = 1, 20260904) | one seeded shuffle of the whole non-browser suite per job (`-m "not browser"`), to catch fixture leakage. Serial on purpose: under `-n` the order a test runs in is the scheduler's, not the seed's, and the job would stop proving anything (#312: one job per seed, so the two run side by side) |
| `suite · shuffled · browser · shard K/2` (K = 1, 2) | the browser tier shuffled on seed 1, serially, in two whole-file shards, with Chromium (#312): the tier with the most process-global state had never run in a shuffled order |
| `windows · python 3.14 · packaging and shells` (the `slow` marker) | the install/update lifecycle, in real venvs, on the OS where packaging goes wrong |
| every job | `HYPOTHESIS_PROFILE=ci`, so the property tests search 200 examples rather than 50 |
| every pytest step that installed Chromium | `AGENTDATA_REQUIRE_BROWSER=1` and `-rs` (#296): the ubuntu leg, both `browser` jobs, both `suite · shuffled · browser` jobs and every Windows job (a `require_browser` matrix field). A skipped `browser` test fails there, and every other skip prints its reason |
| every pytest step | its own `timeout-minutes` and a `--junitxml=junit/<job>-<step>.xml` (#309); every job with one has a job cap and ends with the `if: always()` step *durations · the per-step table* |

### Step budgets and the durations table

Every CI step that runs pytest has its own cap: about 1.5x its last green time, rounded up to 5 minutes, with
the run and the times in a comment above the step. A job that had no cap got the sum of its step caps plus 5, at
most 20. The Windows jobs are capped at 20 since #311 split them into shards. **A cap is never raised to make a run green**
(*When CI is red*): a step that outgrows its cap is a finding, and the table below names the file that grew.
`tests/test_hygiene_ci_budgets.py` fails a pytest step with no `timeout-minutes` or no `--junitxml`, a job with no
cap or no summary step, and a step cap above its job's cap. The `--collect-only` laptop check is out of its scope.

`tests/conftest.py` records each test's `file` and `markers` as junit properties, because the default
`junit_family` (xunit2) writes no `file` attribute. `.github/scripts/durations.py summarize` turns each junit file
into a table in the job summary: the step's wall time against its cap, the summed test time per tier (`default`,
or the tier markers joined with `+`, such as `browser+measured`), and the 15 most expensive files and tests.
`durations.py job` prints one line for the job: its pytest steps, summed, against the job's cap. **Above 75% of a
cap** either one prints `::warning title=<step> near its cap::`, which shows on the run's page and never fails the
build. The junit files are uploaded as `junit-*` artifacts, kept for 14 days. `workflow_dispatch` runs the workflow
on demand, so a series of green runs needs no pushes.

`tests/durations.json` is `{os: {file: {tier: seconds}}}`, from one green run. To refresh it, download the `junit-*`
artifacts of a green run and run:

```bash
gh run download <run-id> --pattern 'junit-*' --dir junit-run
python .github/scripts/durations.py update junit-run/junit-ubuntu-latest-*/*.xml --os linux --out tests/durations.json
python .github/scripts/durations.py update junit-run/junit-windows-*/*.xml --os windows --out tests/durations.json
```

Within one junit file a file's tests are summed per tier; across junit files the max is taken, not the sum, since
both legs of an OS run the same files. The other OS's key is kept and the output is byte-stable.
