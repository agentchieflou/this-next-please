"""The Windows jobs run as whole-file shards, each under a 20-minute cap (#311).

Only CI can say how long a Windows shard takes. What a job *runs* is decided before any runner starts,
by the matrix rows and each step's `if:`, and that is checked here: every row is expanded the way
Actions expands it, every `if:` is evaluated against the row, and the steps that would run are
compared with what the old two-leg job ran. The step-budget rules themselves are
tests/test_hygiene_ci_budgets.py's (#309); the union of the shards is #310's `scale` test.
"""
from __future__ import annotations
import os
import re
import shlex

import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml")

#: What the old serial 3.14 `pytest` step selected; every shard selects this, sharded.
LAPTOP = "not slow and not measured and not scale"
#: #591: the one Python, which is the floor and what the laptop runs (decision 23 on #429).
PYTHON = "3.14"
#: The steps other than pytest that run once per run, in the packaging and shells job: the shells, the
#: code pages, and the pwsh-redirection and 5.1-refusal steps the old job ran on 3.14 only.
SHELLS = {"smoke · pwsh 7", "smoke · Git Bash", "smoke · cmd", "completion · Git Bash", "completion · pwsh 7",
          "encoding · code page 437 falls back to ASCII", "encoding · code page 65001 keeps the glyphs",
          "encoding · pwsh redirection is UTF-8 without a BOM, and byte-identical to Linux",
          "floor · Windows PowerShell 5.1 is refused, and the doctor says why"}
PACKAGING = f"windows · python {PYTHON} · packaging and shells"

_TERM = re.compile(r"^(?:always\(\)|matrix\.(\w+) (==|!=) '([^']*)')$")
_EXPR = re.compile(r"\$\{\{\s*matrix\.(\w+)\s*\}\}")


def _job() -> dict:
    with open(WORKFLOW, encoding="utf-8") as f:
        return yaml.safe_load(f)["jobs"]["windows"]


def holds(condition, row: dict) -> bool:
    """A step's `if:` against one matrix row. Only `always()` and `matrix.<k> ==|!= '<v>'` joined by
    `&&` are understood; anything else fails here rather than being guessed at."""
    if condition is None:
        return True
    result = True
    for term in str(condition).split("&&"):
        m = _TERM.match(term.strip())
        assert m, f"an `if:` this test cannot evaluate: {condition!r}"
        if m.group(1):
            value = str(row.get(m.group(1), ""))
            result &= (value == m.group(3)) if m.group(2) == "==" else (value != m.group(3))
    return result


def render(text, row: dict) -> str:
    def sub(m):
        assert m.group(1) in row, f"${{{{ matrix.{m.group(1)} }}}} is not a field of {row}"
        return str(row[m.group(1)])
    return _EXPR.sub(sub, str(text or ""))


def expand(job: dict) -> list[dict]:
    """One dict per row: the row, the job name and the steps that run, rendered."""
    rows = []
    for row in job["strategy"]["matrix"]["include"]:
        steps = []
        for s in job["steps"]:
            if holds(s.get("if"), row):
                steps.append({**s, "name": render(s.get("name") or s.get("uses") or s.get("run", ""), row),
                              "run": render(s.get("run"), row),
                              "env": {k: render(v, row) for k, v in (s.get("env") or {}).items()},
                              "with": {k: render(v, row) for k, v in (s.get("with") or {}).items()}})
        rows.append({"row": row, "name": render(job["name"], row), "steps": steps})
    return rows


def pytest_runs(expanded: dict) -> list[dict]:
    return [s for s in expanded["steps"] if "-m pytest" in s["run"]]


def selection(run: str) -> str:
    """The marker expression of a `python -m pytest ...` line (its first `-m` after `pytest`)."""
    args = shlex.split(run.splitlines()[0] if run else "")
    args = args[args.index("pytest") + 1:] if "pytest" in args else []
    return args[args.index("-m") + 1] if "-m" in args else ""


def shard_of(run: str):
    m = re.search(r"--shard=(\d+)/(\d+)", run)
    return (int(m.group(1)), int(m.group(2))) if m else None


def test_the_windows_rows_are_four_shards_and_a_packaging_job_all_on_3_14():
    job = _job()
    assert job["timeout-minutes"] <= 20, "the Windows caps came back down to 20 minutes"
    for s in job["steps"]:
        assert s.get("timeout-minutes", 0) <= 20, s.get("name")
    expanded = expand(job)
    names = [e["name"] for e in expanded]
    assert len(names) == len(set(names)), f"two Windows jobs share a name: {names}"
    assert {e["row"]["python"] for e in expanded} == {PYTHON}, "#591: no Windows job runs another Python"
    for s in job["steps"]:
        if str(s.get("uses", "")).startswith("actions/setup-python"):
            assert s["with"]["python-version"] == "${{ matrix.python }}", s

    shards = []
    for e in expanded:
        runs = pytest_runs(e)
        sharded = [shard_of(s["run"]) for s in runs if shard_of(s["run"])]
        assert len(sharded) <= 1, f"{e['name']}: more than one sharded step"
        if sharded:
            shards.append(sharded[0])
            assert e["name"] == f"windows · python {PYTHON} · shard {sharded[0][0]}/{sharded[0][1]}"
    assert sorted(shards) == [(k, 4) for k in range(1, 5)], f"every shard K/4 exactly once, and nothing else: {shards}"

    packaging = [e for e in expanded if not any(shard_of(s["run"]) for s in pytest_runs(e))]
    assert [e["name"] for e in packaging] == [PACKAGING]


def test_the_shards_check_out_as_git_for_windows_does_and_packaging_leaves_line_endings_alone():
    """#591: the old floor's two shards were the only `core.autocrlf=true` checkouts, the setting behind
    train 13's line-ending bug. The shards take it over; packaging and shells keeps `false`, so the
    matrix still runs both ways (tests/test_shell.py holds the pair)."""
    by_name = {e["name"]: e["row"]["autocrlf"] for e in expand(_job())}
    assert by_name.pop(PACKAGING) == "false"
    assert set(by_name.values()) == {"true"} and len(by_name) == 4, by_name
    first = _job()["steps"][0]
    assert first["run"] == "git config --global core.autocrlf ${{ matrix.autocrlf }}", "set before the checkout"


def test_each_shard_selects_what_the_old_step_did_serially_and_with_its_own_budget():
    for e in expand(_job()):
        for s in pytest_runs(e):
            if not shard_of(s["run"]):
                continue
            assert selection(s["run"]) == LAPTOP, f"{e['name']}: {s['run']}"
            assert " -n " not in f" {s['run']} ", "serial within a shard until #313"
            assert "-rs" in s["run"].split(), "every skip prints its reason"
            assert s["timeout-minutes"] <= 15, e["name"]


def test_a_browser_is_installed_and_required_on_every_windows_job():
    for e in expand(_job()):
        names = [s["name"] for s in e["steps"]]
        installs = [i for i, s in enumerate(e["steps"]) if "playwright install chromium" in s["run"]]
        runs = [i for i, s in enumerate(e["steps"]) if "-m pytest" in s["run"]]
        required = {s["env"].get("AGENTDATA_REQUIRE_BROWSER", "") for s in e["steps"] if "-m pytest" in s["run"]}
        assert len(installs) == 1 and installs[0] < min(runs), f"{e['name']}: {names}"
        assert required == {"1"}, f"{e['name']}: a browser test could skip for want of Chromium"


def test_the_other_steps_run_once_in_the_packaging_job():
    expanded = expand(_job())
    ran = {e["name"]: {s["name"] for s in e["steps"]} for e in expanded}
    assert shells_in(expanded, PACKAGING) >= SHELLS
    for name, steps in ran.items():
        extra = steps & SHELLS
        if name != PACKAGING:
            assert not extra, f"{name} runs {extra}, which another job already runs"

    def only(expr):
        return [e["name"] for e in expanded for s in pytest_runs(e) if selection(s["run"]) == expr]

    assert only("(measured or scale) and not slow") == [PACKAGING]
    slow = [(e["name"], s) for e in expanded for s in pytest_runs(e) if selection(s["run"]) == "slow"]
    assert [n for n, _ in slow] == [PACKAGING]
    step = slow[0][1]
    assert step["timeout-minutes"] == 10
    for flag in ("-v", "--durations=0", "--capture=tee-sys", "-rs"):
        assert flag in step["run"].split(), flag


def shells_in(expanded: list[dict], name: str) -> set[str]:
    return next({s["name"] for s in e["steps"]} for e in expanded if e["name"] == name)


def test_every_row_writes_its_own_junit_files_and_reports_each_against_its_cap():
    """upload-artifact@v4 refuses a second artifact of the same name in one run, and the durations
    table is refreshed from every `junit-windows-*` artifact at once, so both are unique per row."""
    artifacts, files = [], []
    for e in expand(_job()):
        written = {}
        for s in pytest_runs(e):
            m = re.search(r"--junitxml=junit/(\S+)\.xml", s["run"])
            assert m, f"{e['name']} / {s['name']}"
            written[m.group(1)] = s["timeout-minutes"]
        files += list(written)
        summary = [s for s in e["steps"] if "durations.py" in s["run"] and " summarize " in s["run"]]
        assert len(summary) == 1 and "always()" in str(summary[0].get("if")), e["name"]
        text = summary[0]["run"] + "\n" + "\n".join(f"{k}={v}" for k, v in summary[0]["env"].items())
        reported = dict(re.findall(r'^\s*report (\S+) "[^"]+" (\d+)\s*$', text, re.M))
        reported = {render(k.replace("$KEY", "${{ matrix.key }}"), e["row"]): int(v) for k, v in reported.items()}
        for stem, cap in written.items():
            assert reported.get(stem) == cap, f"{e['name']}: {stem} is not reported against its cap {cap}"
        assert summary[0]["env"].get("JOB_NAME") == e["name"], e["name"]
        assert f"--cap-minutes {_job()['timeout-minutes']}" in summary[0]["run"]
        upload = [s for s in e["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact")
                  and s["with"].get("path") == "junit/"]
        assert len(upload) == 1 and "always()" in str(upload[0].get("if")), e["name"]
        artifacts.append(upload[0]["with"]["name"])
        assert artifacts[-1].startswith("junit-windows-"), artifacts[-1]
    assert len(artifacts) == len(set(artifacts)), artifacts
    assert len(files) == len(set(files)), files


@pytest.mark.parametrize("condition, row, expected", [
    (None, {}, True), ("always()", {}, True),
    ("matrix.python == '3.14'", {"python": "3.14"}, True),
    ("matrix.python == '3.14' && matrix.shard != ''", {"python": "3.14", "shard": ""}, False),
    ("always() && matrix.extras != ''", {"extras": "3.14"}, True),
])
def test_the_condition_reader_reads_the_forms_the_job_uses(condition, row, expected):
    assert holds(condition, row) is expected


def test_the_condition_reader_refuses_what_it_cannot_read():
    with pytest.raises(AssertionError, match="cannot evaluate"):
        holds("matrix.python == '3.14' || matrix.shard == ''", {"python": "3.14"})
    with pytest.raises(AssertionError, match="cannot evaluate"):
        holds("startsWith(matrix.python, '3.1')", {"python": "3.14"})
