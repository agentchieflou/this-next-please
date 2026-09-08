"""Section 11: the fifteen-minute quickstart on the real parent folder (#134).

The epic's condition was never "does the code work" -- CI proves that on fixture repositories in a
temp directory. It was the operator's own sentence: *I don't want to spend all night setting it up
when this-next-please works relatively well per project.* That is a wall-clock claim about one
laptop's real folder, and the things that break it are the things a fixture tree does not have: a
OneDrive placeholder, a mapped drive, twenty checkouts, a `node_modules` that turns a two-second
scan into a two-minute one, and a `where` that ranks the wrong repository first because two projects
both mention the word.

So this case runs the real command on the real folder, from whichever shell the operator started
pytest in (epic #63: the same file runs from pwsh 7 and Git Bash, and the evidence file's
environment bundle names which), and writes what it cost into
`.agent/out/verification-<ts>.toon`. That record is the answer to "is fifteen minutes the right
promise", which nothing on CI can answer.

**The budget is measured before it is asserted.** On the first, genuinely cold run -- the one whose
summary says `refresh: false` -- a breach is recorded and reported, not failed: a first number
nobody has ever measured is evidence, and turning it into a red test would only teach the operator
to pass `-k not quickstart`. Every later run asserts it hard, because by then the number is known
and a regression is a regression.

The two keys live in `laptop.toml` beside the checkout, like section 3's, because they are facts
about *this laptop's* verification run and not about any project: another operator verifies a
different folder against a different report. Absent keys skip with the file to write in the reason;
they never fail.
"""
from __future__ import annotations
import os
import re

import pytest

pytestmark = pytest.mark.laptop

# Same file and same override as section 3, on purpose: one place per laptop for the facts the
# verification suite needs, not one per section.
LAPTOP_TOML = "laptop.toml"
TOML_ENV = "AGENTDATA_LAPTOP_TOML"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# #134's promise, in seconds. Soft on the first run, hard afterwards -- see the module docstring.
BUDGET_S = 15 * 60

# The fields #134 fixes for the summary. Missing one is a contract change, and the tile that reads
# it would go blank without saying why, so they are asserted by name rather than eyeballed.
SUMMARY_FIELDS = ("refresh", "repos", "indexed_docs", "tiles_with_ticket", "tiles_missing_facts",
                  "inbox_offered", "elapsed")

SAMPLE = """[fleet]
parent_folder = "C:/Users/you/PycharmProjects"   # the folder your projects actually live under
where = { word = "velocity", repo = "rdsd-pbi-reporting" }   # a word from one repo's real
                                                             # .agent/pbip/<name>/REPORT.md, and
                                                             # the fleet name of that repo"""


def _toml_path() -> str:
    return os.environ.get(TOML_ENV) or os.path.join(REPO_ROOT, LAPTOP_TOML)


def _laptop_toml() -> dict:
    """`laptop.toml` as a dict, or an empty one when there is no such file.

    A file that will not parse is reported as a skip naming the parse error rather than treated as
    absent: a typo'd table would otherwise look exactly like a laptop that never opted in.
    """
    import tomllib

    path = _toml_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as e:
        pytest.skip(f"{path} cannot be read ({e}); fix it or remove it")


def _fleet_fact(name: str):
    """`fleet.<name>` from laptop.toml, or a skip whose reason is the file and what to put in it."""
    value = (_laptop_toml().get("fleet") or {}).get(name)
    if not value:
        pytest.skip(f"no fleet.{name} in {_toml_path()}; add it to run the quickstart case:\n{SAMPLE}")
    return value


def _meta(out: str) -> dict:
    """The TOON meta block as a dict of strings. Enough to assert on without a parser, as elsewhere
    in this suite -- and `quickstart` prints more than one block, so only the first is read."""
    got: dict[str, str] = {}
    for line in out.splitlines():
        if re.match(r"^\S+\[\d+\]", line):
            break
        m = re.match(r"^  ([a-z_]+): ?(.*)$", line)
        if m and m.group(1) not in got:
            got[m.group(1)] = m.group(2).strip().strip('"')
    return got


def _summary(out: str) -> dict:
    """The `ad-fleet quickstart` summary block, which is the *last* meta in its output.

    Quickstart prints the scan's proposal and what it registered before it prints the summary, so
    reading the first block would report the scan's counts as the run's.
    """
    blocks: list[dict] = []
    current: dict | None = None
    for line in out.splitlines():
        if line.startswith("meta:"):
            current = {}
            blocks.append(current)
            continue
        m = re.match(r"^  ([a-z_]+): ?(.*)$", line)
        if m and current is not None:
            current[m.group(1)] = m.group(2).strip().strip('"')
    for block in reversed(blocks):
        if "elapsed" in block:
            return block
    return blocks[-1] if blocks else {}


def _first_row(out: str, table: str) -> list[str]:
    """The first data row of a named TOON table, split on commas. `[]` when the table is empty."""
    rows, header = [], re.compile(rf"^{re.escape(table)}\[\d+\]\{{")
    inside = False
    for line in out.splitlines():
        if header.match(line):
            inside = True
            continue
        if inside:
            if not line.startswith("  "):
                break
            rows.append([c.strip().strip('"') for c in line.strip().split(",")])
            break
    return rows[0] if rows else []


def _shell() -> str:
    from agentdata import shell as SH

    return SH.detect()


def test_quickstart_sets_up_the_desk_from_the_real_parent_folder(run, recorder):
    """One command, the real folder, the clock running -- and the summary that says what answered.

    `--no-serve` because the dashboard blocks until Ctrl-C and nothing here can click it; the page
    is exercised by hand in the runbook. `--yes` because a prompt inside pytest has no terminal to
    read from: the interactive first run is the operator's own, timed by hand into the runbook's
    table, and this is the repeatable half.
    """
    folder = str(_fleet_fact("parent_folder"))
    if not os.path.isdir(folder):
        pytest.skip(f"fleet.parent_folder is {folder!r}, which is not a folder on this laptop")

    rc, out, _err = run("ad-fleet quickstart <parent_folder> --yes --no-serve",
                        ["fleet", "quickstart", folder, "--yes", "--no-serve"], timeout=1800)
    summary = _summary(out)
    elapsed = float(summary.get("elapsed") or 0)
    first_run = summary.get("refresh") == "false"
    recorder.step("test_11_fleet_quickstart", "quickstart on the real parent folder",
                  f"python -m agentdata fleet quickstart {folder} --yes --no-serve", rc,
                  shell=_shell(), folder=folder, budget_s=BUDGET_S,
                  within_budget=(bool(elapsed) and elapsed <= BUDGET_S),
                  **{k: summary.get(k, "") for k in SUMMARY_FIELDS})

    assert rc == 0, out
    for field in SUMMARY_FIELDS:
        assert field in summary, f"the quickstart summary has no {field}: {out}"
    assert int(summary.get("repos") or 0) >= 1, (
        f"nothing under {folder} was registered; the scan's `candidates` table says why: {out}")
    assert int(summary.get("indexed_docs") or 0) >= 1, (
        "the catalogue is empty: every registered repo failed to yield an allow-listed file. "
        f"The index's `problems` table names them: {out}")

    if elapsed > BUDGET_S and first_run:
        # Reported, not failed. The number is the finding; see the module docstring.
        print(f"\nfirst run took {elapsed:.0f}s against a {BUDGET_S}s budget -- recorded in the "
              f"evidence file. Paste it into #134 before this becomes a hard assertion.")
        return
    assert elapsed <= BUDGET_S, (
        f"a refresh run took {elapsed:.0f}s, over the {BUDGET_S}s budget. `ad-fleet index` is "
        f"incremental, so a slow refresh means it is re-reading everything: {out}")


def test_the_desk_answers_where_with_the_right_repo(run, recorder):
    """The first useful answer: a word from a real report, and the project that owns it.

    This is the whole epic in one assertion. Before it, "which project owns Velocity" cost a window
    switch, a bookmark and a page load; after it, it costs a word.
    """
    wanted = _fleet_fact("where")
    if not isinstance(wanted, dict):
        pytest.skip(f"fleet.where in {_toml_path()} must be a table:\n{SAMPLE}")
    word, repo = str(wanted.get("word") or "").strip(), str(wanted.get("repo") or "").strip()
    if not (word and repo):
        pytest.skip(f"fleet.where needs both `word` and `repo` in {_toml_path()}:\n{SAMPLE}")

    rc, out, _err = run(f"ad-fleet where {word}", ["fleet", "where", word])
    meta, top = _meta(out), _first_row(out, "matches")
    recorder.step("test_11_fleet_quickstart", "where answers with the right repo",
                  f"python -m agentdata fleet where {word}", rc, shell=_shell(),
                  query=word, expected=repo, answered=top[0] if top else "",
                  kind=top[1] if len(top) > 1 else "", search=meta.get("search", ""),
                  matches=meta.get("matches", ""))

    assert rc == 0, out
    if int(meta.get("indexed_projects") or 0) == 0:
        pytest.skip("the catalogue is empty; run this section whole, or `ad-fleet index` first")
    assert top, (f"nothing matched {word!r}. It has to be a word that is really in one repo's "
                 f".agent/pbip/<name>/REPORT.md -- `ad-fleet show {repo}` lists what is indexed "
                 f"for it: {out}")
    assert top[0] == repo, (
        f"{word!r} ranked {top[0]!r} above {repo!r}. Either the word is not distinctive enough on "
        f"this laptop -- pick one only that report uses -- or the ranking is wrong, which is the "
        f"finding: {out}")
