"""Which tier runs where in CI: a matrix generated from .github/workflows/tests.yml (#315).

    python tests/tier_matrix.py            # print the block
    python tests/tier_matrix.py --write    # rewrite it in docs/testing-this-repo.md §What CI runs

Every job is expanded per matrix row the way Actions expands it, and every step's `if:` is evaluated
against the row. Each shell command in a step that runs pytest (`python -m pytest`,
`coverage run -m pytest`) is read for its marker expression (only a `-m` after the `pytest` token;
the `-m` of `python -m pytest` is not one), `--shard`, `-n`, `--shuffle-seed` and the test files it
names. A command with `--collect-only` runs nothing and counts for nothing. The expression is
evaluated with pytest's own marker grammar against every combination of tier markers a test in this
suite carries (`COMBINATIONS`; the `scale` test in tests/test_suite_hygiene.py fails when the real
collection holds one that is missing). A command that names files selects the combinations those
files hold in tests/durations.json. A combination with `browser` selected in a job that installs no
Chromium renders `SKIPS`: a skip nobody sees. tests/test_hygiene_tier_matrix.py keeps the block in the
doc equal to this output and every tier on both OSes.

Loaded as a plugin (`-p tier_matrix`), it prints one `tier-matrix-combination: <markers>` line per
distinct combination of tier markers among the collected tests.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows", "tests.yml")
DOC = os.path.join(REPO_ROOT, "docs", "testing-this-repo.md")
DURATIONS = os.path.join(REPO_ROOT, "tests", "durations.json")
START, END = "<!-- tier-matrix:start -->", "<!-- tier-matrix:end -->"
REFRESH = "python tests/tier_matrix.py --write"

#: The markers that make a tier. `windows`, `posix`, `real_home` and `network` say where or how a test
#: runs, not which step selects it, and no step's `-m` names them.
TIERS = ("browser", "measured", "scale", "slow", "laptop")

#: Every combination of tier markers a test here carries; `frozenset()` is the default tier.
COMBINATIONS: tuple[frozenset[str], ...] = tuple(frozenset(c) for c in (
    (), ("browser",), ("measured",), ("scale",), ("slow",), ("laptop",),
    ("browser", "slow"), ("browser", "measured"), ("measured", "scale"), ("laptop", "measured"),
))

#: Combinations allowed to run on one OS only: {combination: why}. `laptop` is never CI's.
EXCEPTIONS: dict[frozenset[str], str] = {}

_TERM = re.compile(r"^(?:always\(\)|matrix\.(\w+) (==|!=) '([^']*)')$")
_EXPR = re.compile(r"\$\{\{\s*matrix\.(\w+)\s*\}\}")
_OPERATORS = {"|", "||", "&&", ";", "&"}
_VALUED = {"-m", "-n", "-p", "-k", "-c", "--shard", "--shuffle-seed", "--junitxml", "--durations",
           "--capture", "--numprocesses", "--dist", "--maxfail", "--rootdir", "--hypothesis-seed"}


class TierMatrixError(Exception):
    pass


def label(combo) -> str:
    return "+".join(sorted(combo)) or "default"


# ------------------------------------------------------------------------------------------ the workflow


def load(path: str = WORKFLOW) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)  # `on:` loads as the key True; nothing here reads it


def matrix_rows(job: dict) -> list[dict]:
    """The rows as Actions expands them: the product of the list-valued keys, then each `include`
    row extends every row it matches or else is added as a row of its own."""
    matrix = (job.get("strategy") or {}).get("matrix") or {}
    axes = {k: v for k, v in matrix.items() if k not in ("include", "exclude")}
    rows = [dict(zip(axes, combo)) for combo in itertools.product(*axes.values())] if axes else []
    for extra in matrix.get("include") or []:
        hits = [r for r in rows if all(r.get(k, v) == v for k, v in extra.items() if k in axes)]
        if axes and hits:
            for r in hits:
                r.update(extra)
        else:
            rows.append(dict(extra))
    for gone in matrix.get("exclude") or []:
        rows = [r for r in rows if not all(r.get(k) == v for k, v in gone.items())]
    return rows or [{}]


def holds(condition, row: dict) -> bool:
    """A step's `if:` against one row: `always()` and `matrix.<k> ==|!= '<v>'` joined by `&&`.
    Anything else is an error rather than a guess."""
    if condition is None:
        return True
    result = True
    for term in str(condition).split("&&"):
        m = _TERM.match(term.strip())
        if not m:
            raise TierMatrixError(f"an `if:` the tier matrix cannot evaluate: {condition!r}")
        if m.group(1):
            value = str(row.get(m.group(1), ""))
            result &= (value == m.group(3)) if m.group(2) == "==" else (value != m.group(3))
    return result


def render(text, row: dict) -> str:
    def sub(m):
        if m.group(1) not in row:
            raise TierMatrixError(f"${{{{ matrix.{m.group(1)} }}}} is not a field of {row}")
        return str(row[m.group(1)])
    return _EXPR.sub(sub, str(text if text is not None else ""))


# ------------------------------------------------------------------------------------------ the commands


@dataclass
class Command:
    expr: str = ""                 # the marker expression; "" selects every tier
    workers: str = ""              # `-n` value, "" when serial
    shard: tuple[int, int] | None = None
    seed: str = ""
    files: list[str] = field(default_factory=list)


def commands(run: str) -> list[Command]:
    """The pytest commands of a `run:` block: `\\`-continued lines joined, each line split with shlex
    and cut at `|`, `&&`, `||` and `;`. `--collect-only` commands are dropped: they run nothing."""
    out = []
    for line in re.sub(r"\\\n\s*", " ", run or "").splitlines():
        if not re.search(r"(^|\s)pytest(\s|$)", line):
            continue
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        words, part = [], []
        for tok in lexer:
            if tok in _OPERATORS:
                words.append(part)
                part = []
            else:
                part.append(tok)
        words.append(part)
        for w in words:
            if "pytest" not in w:
                continue
            args = w[w.index("pytest") + 1:]
            if "--collect-only" in args or "--co" in args:
                continue
            out.append(_parse(args))
    return out


def _parse(args: list[str]) -> Command:
    cmd, i = Command(), 0
    while i < len(args):
        a = args[i]
        name, eq, value = a.partition("=")
        if a.startswith("-") and not eq and a in _VALUED:
            value = args[i + 1] if i + 1 < len(args) else ""
            i += 1
        elif not (a.startswith("--") and eq):
            name = a
        if name == "-m":
            cmd.expr = value.strip()
        elif name in ("-n", "--numprocesses"):
            cmd.workers = value
        elif name == "--shard":
            k, _, n = value.partition("/")
            cmd.shard = (int(k), int(n))
        elif name == "--shuffle-seed":
            cmd.seed = value
        elif not a.startswith("-") and (a.startswith(("tests/", "tests\\")) or a.endswith(".py") or "::" in a):
            cmd.files.append(a)
        i += 1
    return cmd


def evaluate(expr: str, combo) -> bool:
    """pytest's own marker grammar, and only tier markers: an expression naming anything else is an
    error, since COMBINATIONS says nothing about it."""
    if not expr:
        return True
    stray = sorted(set(re.findall(r"[^\s()]+", expr)) - {"and", "or", "not"} - set(TIERS))
    if stray:
        raise TierMatrixError(f"-m {expr!r} names {stray}, which are not tier markers ({', '.join(TIERS)})")
    try:
        from _pytest.mark.expression import Expression
    except ImportError:  # pragma: no cover - a pytest that moved its private module
        return _evaluate_by_collection(expr, combo)
    result = Expression.compile(expr).evaluate(lambda name, **_: name in combo)
    return result


def _evaluate_by_collection(expr: str, combo) -> bool:  # pragma: no cover - see evaluate()
    """The fallback: one synthetic test carrying `combo`, collected under `-m expr`."""
    with tempfile.TemporaryDirectory() as tmp:
        marks = "".join(f"@pytest.mark.{m}\n" for m in sorted(combo))
        with open(os.path.join(tmp, "test_combo.py"), "w", encoding="utf-8") as f:
            f.write(f"import pytest\n{marks}def test_combo():\n    pass\n")
        with open(os.path.join(tmp, "pytest.ini"), "w", encoding="utf-8") as f:
            f.write("[pytest]\nmarkers =\n" + "".join(f"    {m}: tier\n" for m in TIERS))
        out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                              "--collect-only", "-m", expr, tmp], capture_output=True, text=True, cwd=tmp)
        return "test_combo" in out.stdout


# ------------------------------------------------------------------------------------------ the runs


@dataclass
class Run:
    job_id: str
    job: str                       # the job's name as the check shows it
    os: str                        # "ubuntu" / "windows"
    python: str
    step: int                      # the step's index in the job, the same on every row
    name: str
    command: Command
    chromium: bool                 # an earlier step on this row installs it
    require_browser: str
    combos: tuple[frozenset[str], ...]


def _durations() -> dict:
    with open(DURATIONS, encoding="utf-8") as f:
        return json.load(f)


def _file_combos(files: list[str], os_name: str, durations: dict) -> set[frozenset[str]]:
    table = durations.get("windows" if os_name == "windows" else "linux", {})
    found = set()
    for path in files:
        if path not in table:
            raise TierMatrixError(
                f"{path} is named by a CI step and is not in tests/durations.json, so its tiers are "
                "unknown: refresh the table (docs/testing-this-repo.md §Step budgets)")
        found |= {frozenset() if t == "default" else frozenset(t.split("+")) for t in table[path]}
    return found


def runs(workflow: dict | None = None, durations: dict | None = None) -> list[Run]:
    workflow = load() if workflow is None else workflow
    durations = _durations() if durations is None else durations
    out = []
    for job_id, job in workflow["jobs"].items():
        for row in matrix_rows(job):
            runs_on = render(job.get("runs-on"), row)
            os_name = "windows" if "windows" in runs_on else "ubuntu" if "ubuntu" in runs_on else runs_on
            steps = [(i, s) for i, s in enumerate(job.get("steps") or []) if holds(s.get("if"), row)]
            python = next((render(s["with"].get("python-version"), row) for _, s in reversed(steps)
                           if str(s.get("uses", "")).startswith("actions/setup-python")), "")
            chromium = False
            for i, s in steps:
                text = render(s.get("run"), row)
                if "playwright install" in text and "chromium" in text:
                    chromium = True
                env = {**(job.get("env") or {}), **(s.get("env") or {})}
                for cmd in commands(text):
                    if cmd.files:
                        pool = _file_combos(cmd.files, os_name, durations)
                        unknown = pool - set(COMBINATIONS)
                        if unknown:
                            raise TierMatrixError(f"{cmd.files} hold {sorted(map(label, unknown))}: add it to COMBINATIONS")
                    else:
                        pool = set(COMBINATIONS)
                    out.append(Run(job_id, render(job.get("name", job_id), row), os_name, python, i,
                                   render(s.get("name") or "", row) or text.strip().splitlines()[0], cmd, chromium,
                                   render(env.get("AGENTDATA_REQUIRE_BROWSER", ""), row),
                                   tuple(c for c in COMBINATIONS if c in pool and evaluate(cmd.expr, c))))
    return out


# ------------------------------------------------------------------------------------------ the cells


def _mode(run: Run) -> str:
    c = run.command
    if c.seed:
        return "shuffled"
    if c.workers:
        return "parallel" if c.workers == "auto" else f"{c.workers} workers"
    return "serial"


def cell_word(run: Run, combo) -> str:
    if "laptop" in combo:
        return "gated"
    if "browser" in combo and not run.chromium:
        return "SKIPS"
    return _mode(run) + (", named files" if run.command.files else "")


def columns(all_runs: list[Run]) -> list[tuple[str, str]]:
    return sorted({(r.os, r.python) for r in all_runs}, key=lambda c: (c[0], [int(p) for p in c[1].split(".")]))


def summary_cell(all_runs: list[Run], column, combo) -> str:
    groups: dict[tuple[str, int], list[Run]] = {}
    for r in all_runs:
        if (r.os, r.python) == column and combo in r.combos:
            groups.setdefault((r.job_id, r.step), []).append(r)
    words = set()
    for group in groups.values():
        word = cell_word(group[0], combo)
        if word in ("gated", "SKIPS"):
            words.add(word)
            continue
        shards = {r.command.shard for r in group if r.command.shard}
        seeds = {r.command.seed for r in group if r.command.seed}
        if shards:
            n = {s[1] for s in shards}
            whole = len(n) == 1 and {s[0] for s in shards} == set(range(1, next(iter(n)) + 1))
            prefix = f"{next(iter(n))} shards" if whole else " ".join(f"shard {k}/{m}" for k, m in sorted(shards))
            word = f"{prefix}, {word}"
        if len(seeds) > 1:
            word = word.replace("shuffled", f"shuffled ({len(seeds)} seeds)")
        words.add(word)
    return " + ".join(sorted(words)) or "—"


def job_cell(job_runs: list[Run], combo) -> str:
    words = [cell_word(r, combo) for r in job_runs if combo in r.combos]
    return " + ".join(dict.fromkeys(words)) or "—"


def jobs(all_runs: list[Run]) -> list[list[Run]]:
    """The expanded jobs that run pytest, in the workflow's order."""
    grouped: dict[str, list[Run]] = {}
    for r in all_runs:
        grouped.setdefault(r.job, []).append(r)
    return list(grouped.values())


def problems(all_runs: list[Run]) -> list[str]:
    """A browser combination selected where no Chromium is installed; a tier (other than `laptop`)
    that no Linux or no Windows job runs, unless EXCEPTIONS says why."""
    found = []
    for r in all_runs:
        for combo in r.combos:
            if cell_word(r, combo) == "SKIPS":
                found.append(f"{r.job} / {r.name}: selects {label(combo)} with no Chromium installed (SKIPS)")
    for combo in COMBINATIONS:
        if "laptop" in combo or combo in EXCEPTIONS:
            continue
        for os_name in ("ubuntu", "windows"):
            if not any(r.os == os_name and combo in r.combos and cell_word(r, combo) != "SKIPS" for r in all_runs):
                found.append(f"{label(combo)} runs on no {os_name} job")
    return found


def table(all_runs: list[Run] | None = None) -> str:
    all_runs = runs() if all_runs is None else all_runs
    cols = columns(all_runs)
    lines = [
        "Generated from `.github/workflows/tests.yml` by `tests/tier_matrix.py`; refresh with "
        f"`{REFRESH}`. A cell names how the tier runs there: `parallel` (`-n auto`), `2 workers` "
        "(`-n 2`), `serial`, `shuffled` (serial, `--shuffle-seed`), `N shards` (whole-file `--shard=K/N` "
        "jobs), `named files` (a step that names its test files runs only the tiers those files hold, "
        "per `tests/durations.json`), `gated` (selected, and skipped unless `AGENTDATA_LAPTOP=1`), "
        "`SKIPS` (a `browser` test selected where no Chromium is installed), or `—` (not selected). "
        "`+` joins two steps.",
        "",
        "| Tier | " + " | ".join(f"{o} · {p}" for o, p in cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for combo in COMBINATIONS:
        lines.append(f"| `{label(combo)}` | " + " | ".join(summary_cell(all_runs, c, combo) for c in cols) + " |")
    lines += ["", "Per job, as the checks are named:", "",
              "| Job | " + " | ".join(f"`{label(c)}`" for c in COMBINATIONS) + " |",
              "|---|" + "---|" * len(COMBINATIONS)]
    for job_runs in jobs(all_runs):
        lines.append(f"| `{job_runs[0].job}` | " + " | ".join(job_cell(job_runs, c) for c in COMBINATIONS) + " |")
    return "\n".join(lines) + "\n"


def block(doc: str) -> str:
    start, end = doc.find(START), doc.find(END)
    if start < 0 or end < start:
        raise TierMatrixError(f"docs/testing-this-repo.md has no {START} ... {END} block")
    return doc[start + len(START):end].strip("\n") + "\n"


def write(doc_path: str = DOC) -> bool:
    with open(doc_path, encoding="utf-8", newline="") as f:
        doc = f.read()
    block(doc)
    start, end = doc.index(START) + len(START), doc.index(END)
    new = doc[:start] + "\n" + table() + doc[end:]
    if new != doc:
        with open(doc_path, "w", encoding="utf-8", newline="") as f:
            f.write(new)
    return new != doc


# ------------------------------------------------------------------------------------------ the plugin


def pytest_collection_finish(session):
    combos = {frozenset(m.name for m in item.iter_markers() if m.name in TIERS) for item in session.items}
    for combo in sorted(combos, key=label):
        print(f"tier-matrix-combination: {label(combo)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Which tier runs where in CI, from tests.yml (#315).")
    p.add_argument("--write", action="store_true", help="rewrite the block in docs/testing-this-repo.md")
    args = p.parse_args(argv)
    if args.write:
        print("rewrote docs/testing-this-repo.md" if write() else "docs/testing-this-repo.md is current")
    else:
        sys.stdout.write(table())
    return 0


if __name__ == "__main__":
    sys.exit(main())
