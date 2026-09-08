"""Section 3: Jira changelog and sprint replay.

Field ids differ per Jira instance, so pinning them is the step that makes the rest reproducible.

The long-history case at the bottom is the one thing epic #121 could not prove on CI. `tests/fakes/jira.py`
serves any corpus asked of it, and every fault it injects is one somebody wrote down; a real tenant is where the
undocumented behaviour lives — the page size it silently caps, the rate limit it actually enforces on the
human's shared token, the epic with 1,400 changelog entries because an automation rule has been editing it
nightly for two years. So the operator names one such issue and one JQL wide enough to take minutes, and this
runs the real pull once and writes what it cost into the evidence file. That record is the answer to "is the
budget in `jira_http.RequestBudget` the right size for this tenant", which nothing else can answer.

The two keys live in `laptop.toml` beside the checkout rather than in `AGENTS.md` or `~/.agentdata/config.json`,
because they are facts about *this laptop's* verification run and not about the project: a different operator
verifying against a different tenant names a different issue. Absent keys skip; they never fail. Both steps go
through the `run` fixture, so the same file runs from pwsh 7 and from Git Bash with no second copy (epic #63).
"""
from __future__ import annotations
import os
import re
import shutil

import pytest

pytestmark = pytest.mark.laptop

# Where the operator writes the two facts this section needs. `AGENTDATA_LAPTOP_TOML` moves it, for a laptop
# that verifies against two tenants and keeps a file per tenant.
LAPTOP_TOML = "laptop.toml"
TOML_ENV = "AGENTDATA_LAPTOP_TOML"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# What #127 means by "long": the issue the operator names must be past the point where a single Cloud page (100
# entries) or a Data Center `?expand=changelog` (also 100) could serve it whole. Used only when the instance
# will not say how long the history really is.
LONG_HISTORY_FLOOR = 1000

SAMPLE = """[jira]
long_issue = "PROJ-1234"      # one issue with more than 1,000 changelog entries
long_jql = "project = PROJ AND updated >= -365d"   # a JQL returning more than 500 issues"""


def _configured():
    from agentdata import config

    return bool(config.project_facts().get("jira_project")) and shutil.which("pncli")


def _laptop_toml() -> dict:
    """`laptop.toml` as a dict, or an empty one when there is no such file.

    A file that will not parse is not treated as "absent": it is reported as a skip that names the parse error,
    because a typo'd table would otherwise look exactly like a laptop that never opted in.
    """
    import tomllib

    path = os.environ.get(TOML_ENV) or os.path.join(REPO_ROOT, LAPTOP_TOML)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as e:
        pytest.skip(f"{path} cannot be read ({e}); fix it or remove it")


def _long_fact(name: str) -> str:
    """`jira.<name>` from laptop.toml, or a skip whose reason is the file to write and what to put in it."""
    value = str((_laptop_toml().get("jira") or {}).get(name) or "").strip()
    if not value:
        path = os.environ.get(TOML_ENV) or os.path.join(REPO_ROOT, LAPTOP_TOML)
        pytest.skip(f"no jira.{name} in {path}; add it to run the long-history case:\n{SAMPLE}")
    return value


def _meta(out: str) -> dict:
    """The TOON meta block as a dict of strings. Enough to assert on without a parser, as elsewhere in the suite."""
    got: dict[str, str] = {}
    for line in out.splitlines():
        m = re.match(r"^  ([a-z_]+)(?:\[\d+\])?: ?(.*)$", line)
        if m and not got.get("__rows"):
            got[m.group(1)] = m.group(2)
        if re.match(r"^\S+\[\d+\]", line):
            got["__rows"] = "1"
    return got


def _stat_row(meta: dict) -> dict:
    """The five `--stats` numbers plus the two that say whether the pull was whole, for the evidence file.

    These are the numbers #127 asks the runbook to record: how many requests the tenant was asked for, how many
    of those were second tries, how long the client sat waiting on a rate limit, and how long the whole thing
    took. A missing key becomes an empty string rather than a KeyError, so a failing pull still records what it
    did manage to report.
    """
    keys = ("rows", "requests", "retries", "rate_limit_waits", "waited_seconds", "elapsed_seconds",
            "partial", "reason")
    return {k: meta.get(k, "") for k in keys}


def _history_total(key: str) -> int:
    """How many change histories Jira says the issue has, or 0 when it will not say.

    One extra request, on purpose and at `maxResults=1`. The failure this whole case exists to catch is a
    history that comes back short and looks whole, and nothing inside the pull can catch that: the only witness
    is the server's own `total`, asked for separately. A Data Center without the paged changelog endpoint has no
    such witness, answers 404, and the floor below stands in for it.
    """
    from agentdata import config
    from agentdata.connectors import jira_api as J

    try:
        cfg = config.load()
        j, _me = J.detect_flavor(J.load_credentials(cfg), cfg)
        page = j.get(f"{j.api}/issue/{key}/changelog", {"startAt": 0, "maxResults": 1}) or {}
        return int(page.get("total") or 0)
    except Exception:  # noqa: BLE001 - a probe that fails must not fail the pull it is only checking
        return 0


def test_fields_can_be_pinned(run):
    if not _configured():
        pytest.skip("no jira_project fact, or pncli is absent")
    rc, out, _err = run("ad-jira fields --pin", ["jira", "fields", "--pin"])
    assert rc == 0
    assert "pinned_sprint" in out


def test_sprints_list_for_the_board(run):
    from agentdata import config

    board = config.project_facts().get("jira_board_id")
    if not (_configured() and board):
        pytest.skip("no jira_board_id fact")
    rc, out, _err = run("ad-jira sprints", ["jira", "sprints", "--board", board, "--state", "closed"])
    assert rc == 0, out


def test_a_thousand_entry_history_comes_back_whole(run, recorder):
    """One real issue with a history no single page can hold, pulled whole, with what it cost recorded.

    `--refresh` because the cache would otherwise serve the second verification run from disk and the evidence
    would say the pull cost three requests, which is true and useless: the number the runbook is collecting is
    what a *cold* pull of this issue costs against this tenant.
    """
    if not _configured():
        pytest.skip("no jira_project fact, or pncli is absent")
    key = _long_fact("long_issue")

    total = _history_total(key)
    rc, out, _err = run(f"ad-jira changelog {key} --stats", ["jira", "changelog", key, "--refresh", "--stats"],
                        timeout=900)
    meta = _meta(out)
    recorder.step("test_03_jira_changelog", "long issue cost",
                  f"python -m agentdata jira changelog {key} --refresh --stats", rc,
                  history_total=total, **_stat_row(meta))

    assert rc == 0, out
    assert meta.get("ok") == "true", out
    assert meta.get("partial", "false") == "false", f"the history came back short: {meta.get('reason')}"
    rows = int(meta.get("rows") or 0)
    floor = total or LONG_HISTORY_FLOOR
    assert rows >= floor, (f"{key} has {floor} change histories and the pull produced {rows} rows; "
                           f"one history is one row or more, so fewer is a truncation")


def test_a_wide_jql_comes_back_whole(run, recorder):
    """The other half: hundreds of issues rather than one deep history, which is where the request budget and
    the tenant's rate limit meet each other.

    The default budget (2,000 requests, 900 seconds) is deliberately left alone. If this tenant needs more, the
    pull comes back `partial: true` with the resume hint, this fails, and the numbers in the evidence file are
    the argument for the `jira.budget.*` this laptop should be configured with — which is the finding, not a
    reason to widen the budget until the test passes.
    """
    if not _configured():
        pytest.skip("no jira_project fact, or pncli is absent")
    jql = _long_fact("long_jql")

    rc, out, _err = run("ad-jira changelog --jql <long_jql> --stats",
                        ["jira", "changelog", "--jql", jql, "--refresh", "--stats"], timeout=1800)
    meta = _meta(out)
    recorder.step("test_03_jira_changelog", "long jql cost",
                  "python -m agentdata jira changelog --jql <jira.long_jql> --refresh --stats", rc,
                  jql_issues=meta.get("fetched", ""), **_stat_row(meta))

    assert rc == 0, out
    assert meta.get("ok") == "true", out
    assert meta.get("partial", "false") == "false", f"the pull stopped early: {meta.get('reason')}"
    assert int(meta.get("rows") or 0) > 0, "a JQL that matches nothing proves nothing; name a wider one"
