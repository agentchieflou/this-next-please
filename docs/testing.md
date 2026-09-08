# Testing: runner detection and execution (`ad-test`)

`ad-test` detects a repository's test runner, executes it under a bounded timeout with process tree termination, and returns a normalized TOON result so agents and CI tools can inspect pass/fail counts and failures without parsing arbitrary console logs.

## Commands

| Command | Purpose | Output |
|---|---|---|
| `ad-test detect [<root>] [--all]` | Detect the primary test runner (or list all candidates) | TOON record / table |
| `ad-test run [<root>] [--runner <name>] [--timeout <s>] [--select <id>] [--junit <path>]` | Execute tests under timeout and normalize results | TOON summary + failures table |

## Detection order (first hit wins)

When running `ad-test detect` or `ad-test run` without an explicit `--runner`, the test runner is detected by inspecting `<root>` in the following order:

1. **Configured command (`AGENTS.md` / config / env / CLI)**:
   - CLI flag `--test-cmd <cmd>`
   - Environment variable `AGENTDATA_TEST_CMD`
   - Global config key `project.test_cmd`
   - Project fact `- test_cmd: <cmd>` in `AGENTS.md`
   - `runner`: `configured`, `cmd`: `<cmd>`
2. **Pytest configuration**:
   - `pyproject.toml` containing `[tool.pytest.ini_options]` (or `[tool.pytest]`)
   - `pytest.ini`
   - `tox.ini` containing `[pytest]`
   - `setup.cfg` containing `[tool:pytest]`
   - `runner`: `pytest`, `cmd`: `python -m pytest`
3. **Unittest test directory**:
   - `tests/` or `test/` directory containing `test_*.py` or `*_test.py` with no pytest configuration
   - `runner`: `unittest`, `cmd`: `python -m unittest discover`
4. **Node / npm test script**:
   - `package.json` with a non-empty `scripts.test` property
   - `runner`: `npm`, `cmd`: `npm test`
5. **.NET SDK test project**:
   - `*.csproj` or `*.sln` referencing `Microsoft.NET.Test.Sdk`
   - `runner`: `dotnet`, `cmd`: `dotnet test`
6. **Makefile test target**:
   - `Makefile` containing a `test:` target
   - `runner`: `make`, `cmd`: `make test`
7. **None detected**:
   - Returns `meta.ok: false`, with hint `set test_cmd in AGENTS.md`

Passing `--all` to `ad-test detect` evaluates every candidate rule and lists all matched runners in the priority table.

## Result contract (`ad-test run`)

The command stdout is always formatted as TOON. Full console logs are captured and written to disk at `.agent/out/test-<timestamp>.log`.

### Metadata fields

| Field | Type | Description |
|---|---|---|
| `ok` | boolean | `true` if all tests passed and exit code is 0; `false` on failures or errors |
| `source` | string | Always `"ad-test run"` |
| `runner` | string | Detected or requested runner name (`pytest`, `unittest`, `npm`, `dotnet`, `make`, `configured`) |
| `cmd` | string | The full command line executed |
| `duration_s` | float | Execution duration in seconds |
| `passed` | integer \| string | Count of passed tests (or `"unknown"` if output format unparsable) |
| `failed` | integer \| string | Count of failed tests (or `"unknown"`) |
| `skipped` | integer | Count of skipped tests |
| `errors` | integer | Count of errored tests |
| `log` | string | Path to captured stdout/stderr log under `.agent/out/` |
| `fail` | string | Failure kind when applicable (e.g. `"timeout"`) |
| `hint` | string | Actionable suggestion on failure |

### Failures table

When test failures occur, the tabular output contains one row per failure:

| Column | Description |
|---|---|
| `test` | Test identifier (e.g. `tests.test_app::test_function`) |
| `where` | Source location when available (`path/to/file.py:line`) |
| `message` | First line of the failure message or assertion error |

When all tests pass, the failures table has 0 rows.

## Timeouts and process trees

The default timeout is 600 seconds, configurable via `--timeout <s>`.
When a timeout expires:
- The entire process tree is terminated (`taskkill /F /T` on Windows; process group `SIGKILL` on POSIX).
- The command returns `ok: false`, `fail: timeout`, and hint `raise --timeout or narrow --select`.
- Partial console output is preserved in the log file.

## Selective test execution (`--select`)

The `--select` flag accepts test node IDs, file paths, or code graph node IDs:
```bash
ad-test run --select agentdata/cli_graph.py::cmd_build
```
When `.agent/graph/graph.json` is present, `ad-test` queries the graph for `tests` edges and maps the code symbol to its corresponding test IDs before running the test runner.

## Coverage collection and import (`ad-test coverage`)

`ad-test coverage` measures or imports test execution coverage and attaches line and branch coverage to code graph nodes.

### Commands

| Command | Purpose |
|---|---|
| `ad-test coverage [<root>] [--branch] [--contexts]` | Run suite under coverage.py and attach results to code graph |
| `ad-test coverage [<root>] --import <lcov\|cobertura> <file>` | Import external coverage file into the code graph |
| `ad-test coverage [<root>] --node <node-id>` | Show statement and branch coverage details for a single node |
| `ad-test coverage [<root>] --diff <base-coverage.json>` | Compare node-by-node coverage changes against a baseline |

### Output file format (`.agent/graph/coverage.json`)

```json
{
  "graph_sha256": "4a1b...",
  "source": "coverage.py",
  "collected_at": "2026-09-04T00:00:00.000000",
  "files": {
    "src/calculator.py": {
      "lines_executed": [1, 2, 5],
      "lines_missing": [6],
      "branches": {
        "branch_executed": [[2, 3]],
        "branch_missing": [[2, 5]]
      }
    }
  },
  "nodes": {
    "src/calculator.py::add": {
      "pct": 100.0,
      "executed": [2],
      "missing": [],
      "branch_pct": 100.0,
      "tests": ["test_calculator.test_add"]
    }
  },
  "unmatched": []
}
```

### Staleness and graph integrity

`coverage.json` records `graph_sha256`. If the code graph is rebuilt and its hash changes, `ad-graph status` and `ad-graph guard` flag coverage data as stale, requiring `ad-test coverage` to be re-run.

### Import formats

- **LCOV (`--import lcov <file>`)**: Standard tracefiles produced by Jest/Istanbul, `dotnet-coverage`, and gcov.
- **Cobertura (`--import cobertura <file>`)**: XML format emitted by `coverlet` and `pytest-cov --cov-report xml`.
- File paths are normalized to forward-slash relative paths against the repository root; unmatched files are listed in `unmatched[]`.

### The threshold (`graph_min_coverage`)

The per-node coverage a change must clear is read in exactly one place, `agentdata/config.py`, and
used by `ad-graph findings` (the `covered` column) and `ad-graph guard` (the refusal). Precedence:

1. `- graph_min_coverage: 0.9` in the project's own `AGENTS.md` — the project wins, because the
   threshold is a property of the codebase being worked on, not of the laptop doing the work.
   `ad-setup --only project` asks for it and writes it into the stub.
2. `graph.min_coverage` in `~/.agentdata/config.json`.
3. `0.8`.

A node at or above the threshold is `covered: true`; below it with data present is `false`; with no
coverage file at all it is `unknown` — and the guard treats `unknown` as `false`, because no data is
not evidence of safety.

## Characterization tests (`test-cover`)

`ad-graph guard` refuses changes to code no test covers, so the only legal route to optimizing an
uncovered hub is to cover it first. That is what the `test-cover` skill does, and it writes **test
files only** — `ad-graph guard --tests-only` proves it mechanically rather than trusting the skill.

A characterization test pins behavior **as it is today**. It is not a claim that the behavior is
correct; it is a tripwire. So:

- **When one fails, behavior changed.** That is the signal. The first question is "what did I change
  and did I mean to?", not "is this test wrong?". Only after confirming the new behavior is
  deliberate should the golden value be updated, and the update belongs in the same commit as the
  change that caused it, so review sees both halves together.
- **Expected values are captured, never predicted.** The skill runs the node once through a probe
  test and pastes what it actually returned. A predicted value that happens to be wrong turns a
  characterization test into a bug report against working code.
- **A bug found while characterizing is a ticket, not a side effect.** It goes under
  `## Open questions` in `.agent/graph/understanding.md`, and the buggy behavior gets pinned as it
  is. Fixing it inside a coverage commit hides the fix in a diff nobody is reviewing for that.

Per-framework boilerplate — shape, stubbing I/O, the probe pattern, and the pitfalls that have
actually bitten this repo (time, randomness, dict ordering, float formatting, Windows path
separators, encodings) — lives in `skills/test-cover/references/characterization.md`, one section
per runner so the model reads only the one `ad-test detect` reported.

## Benchmarks (`ad-test bench`)

`ad-test bench --node <id>` times a node **through the tests that already exercise it** — no
hand-written harness, no invented inputs. A node with no linked tests is an error naming
`test-cover`, not a benchmark of nothing.

Each timed run is a fresh process, so `median_ms` includes runner startup. For pytest the command
also profiles the run with `cProfile` and reports `node_cum_ms`: the cumulative time inside the node
itself. **That is the number the comparison uses**, because startup dominates the wall clock — on
the `bench_project` fixture a genuine 5× speedup inside the node moves suite wall time by about 2%,
which would be reported as "no change" and would fail every optimisation that ever worked. Runners
with no profiler report `node_cum_ms: n/a` and are compared on wall time, which they say in `basis`.

`tests` edges come from coverage where they exist. Where they do not, the fallback is
`ad-graph build`'s `test_foo` ↔ `foo` name guess, and the command says so in a `warnings` row rather
than passing the guess off as measurement — run `ad-test coverage --contexts` for real edges.

### The noise floor

`ad-test bench --compare <before> <after>` calls a change `same` unless it clears

> **max(5%, 2 × the before run's own min-to-median spread)**

Five percent because two runs of identical code differ by more than that on any laptop. Twice the
observed spread because a benchmark that was unstable to begin with has to clear a higher bar: if
the baseline's own runs varied by 20%, a 25% "improvement" is not distinguishable from that noise.
The rule is written here so nobody has to argue about a 3% win — 3% is `same`.

`verdict` is `faster` / `same` / `slower`; `meets_min_speedup` additionally requires `speedup ≥
graph_min_speedup` (project `AGENTS.md`, then `graph.min_speedup` in config, default `1.10`).

## Regression gate (`test-regress`)

`ad-test run --snapshot <label>` writes every test's outcome, and `--compare <before> <after>`
diffs two snapshots. A test is a **regression** if it stopped passing *in any way* — failed, errored,
turned into a skip, or vanished from the run entirely. Deleting a failing test is not a fix, and a
quiet `@skip` is the same regression wearing a different hat. New passing tests are `added` and do
not fail the gate.

The `test-regress` skill runs three gates in order and prints one line:

1. `ad-test run --compare` is `ok: true` — no regression rows.
2. `ad-test coverage --diff` shows no node's `pct` dropped.
3. `ad-test bench --compare` is `faster` **and** meets `graph_min_speedup`. A `same` verdict is not
   a win; it is a no-op, and the change should be reverted rather than argued for.

`regress: ok speedup=1.8x tests=142/142`, or `regress: FAIL <reason>`. The skill never edits
anything and never re-runs a step to see if it passes this time — the same command twice with the
same arguments is `AGENTS.md` rule 11, a stop condition, not a retry.

## The fake Jira (`tests/fakes/jira.py`)

Every question epic #121 asks — what happens on a 429 on page 40 of 80, a 500 that clears on retry, a socket
timeout, a page that forgot `isLast`, a server that caps `maxResults`, a bulkfetch page that repeats a history, a
100,000-row pull — was unanswerable on CI, because the Jira tests drove the client with three short, well-formed
pages. `tests/fakes/jira.py` is the instance those questions are asked of. It is the fake every changelog slice
proves itself on: the request layer, the streamed partial, the cache, and bulkfetch discipline.

It materialises no executable and touches no PATH, unlike the rest of the harness. It plugs into the `opener`
argument `agentdata/connectors/jira_api.py` already takes, so the whole wiring is:

```python
from tests.fakes import jira as FJ

fake = FJ.FakeJira(issues=500, histories=200)     # Cloud by default
j = fake.client()                                 # a real Jira, pointed at the fake
rows = j.changelog("RDSD-1")
```

**Nothing is typed out.** `Corpus` generates keys, authors, timestamps, sprints and points on demand from a seed, so
a 500 × 200 corpus costs nothing until somebody asks for a page — which matters, because the budget tests measure
peak memory and the fake must never be the thing that blows it. Constructor knobs worth knowing:
`flavor="dc"` (v2 REST, `startAt` search, no bulkfetch, `?expand=changelog` capped at `expand_cap`),
`paged_changelog=False` (a Data Center without the paged endpoint), `bulk_duplicate=True` (JRACLOUD-94906's
*cross-page* duplicate, which no single-page fault can express), `bulk_cap`, `items_per_history`, `seed`, and
`rate_limit=N` for a token bucket that answers real 429s with a real `Retry-After`.

There is no clock and no socket. `fake.sleep` is the injected sleeper: it records the seconds and advances the
fake's own clock, so a run that would have waited eleven minutes finishes instantly and the test asserts the wait
(`fake.waited`). `fake.requests` records every request — method, path, query, parsed body, headers — with
`Authorization` stored as `"REDACTED"`, because even a fake token must never reach a fixture, a log or a failure
message. `fake.count("bulkfetch")`, `fake.matching("issue/")` and `fake.last("/search")` are the assertions;
`fake.unfired()` is the one to assert empty, since a fault that never fired is nearly always a typo in its `match`.

### Writing a fault script

A fault script is an ordered list of `(match, nth, fault)` triples passed as `faults=[…]`. On each request the list
is read left to right and the first entry that fires wins.

- **`match`** is a plain substring of `"<METHOD> <path>?<query>"`. Substring means substring: `"changelog"` also
  matches `POST /rest/api/3/changelog/bulkfetch`, so write `"issue/"` or `"bulkfetch"` when you mean one of them.
  `""`, `"any"` and `"*"` match every request.
- **`nth`** picks which matching occurrence fires, counted 1-based per entry: an `int` fires once, a tuple or list
  of ints fires on each of those, `"every"` (or `None`) fires on all of them.
- **`fault`** is one of: any int (that HTTP status, with Jira's `errorMessages` body) · `429` (numeric
  `Retry-After`) · `"429 date"` (an HTTP-date one, the form `email.utils` has to parse) · `"400 invalid key NOPE-1"`
  (a 400 whose body names the key, as a bad `key in (…)` really does) · `"timeout"` · `"reset"` · `"interrupt"`
  (a `KeyboardInterrupt`, for the checkpoint tests) · `"drop isLast"` · `"cap maxResults 100"` ·
  `"duplicate histories"` · `"shuffle pages"`. An unknown spelling raises at construction, where the traceback names
  the test, rather than quietly doing nothing.

```python
FJ.FakeJira(60, 40, faults=[
    ("issue/",    3,       500),          # the third per-issue request answers 500
    ("bulkfetch", 2,       "timeout"),    # the second bulkfetch times out
    ("bulkfetch", 4,       "interrupt"),  # Ctrl-C on the fourth chunk
    ("",          30,      429),          # the thirtieth request of any kind is rate limited
    ("/search",   "every", "drop isLast"),
])
```

Drive the fake directly with `fake.request("GET", path, params)` when the assertion is about the *fake's* contract
(whether it answered 502 on the third bulkfetch) rather than the client's policy (whether a 502 is retried) — the
second changes with the request layer, the first must not.

`tests/test_fake_jira.py` is the fake's own test; `tests/test_jira_cli.py`, `tests/test_jira_cache.py`,
`tests/test_jira_http.py` and `tests/test_jira_stream.py` are what it is for. Every laptop failure pasted back
becomes a fault script here first, then a regression test under `tests/regressions/`.
