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
