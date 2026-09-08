"""The desk's verbs, driven the way an operator drives them: `ad-fleet <verb>`, TOON back.

Epic #122 is five modules and one command line, and this file is about the command line. The
modules have their own suites (`test_fleet_scan.py`, `test_fleet_catalogue.py`,
`test_fleet_links.py`, `test_fleet_poll.py`, `test_fleet_inbox.py`) and prove what may be read,
what is refused and what is never opened. What is left, and what an operator at 5pm actually meets,
is the half this file covers: whether the confirmation really asks before it writes, whether `q`
stops, whether `--only` naming a folder that is not there says so instead of doing nothing,
whether a second `quickstart` is a refresh, and whether the summary carries the six numbers the
epic promised.

Nothing is mocked inside the fleet. The repositories are real folders, the registry is the real
registry, the catalogue is a real sqlite file in a temporary fleet directory, and the confirmation
reads a real `sys.stdin`.
"""
from __future__ import annotations
import io
import json
import os
import re
import sys

import pytest

from agentdata import cli_fleet
from agentdata.fleet import registry
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    """A fleet directory of our own: registry, catalogue, poll counters and dismissals."""
    home = tmp_path / "fleet"
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(home))
    return home


def a_repo(root, name, *, project="RDSD", ticket="", git=True, state=True, facts=None) -> str:
    """A folder shaped like `ad-setup --project` left it, with a branch the scan can read."""
    path = str(root / name)
    os.makedirs(os.path.join(path, ".agent"), exist_ok=True)
    lines = [f"# {name}", "", f"- jira_project: {project}"]
    for key, value in (facts or {}).items():
        lines.append(f"- {key}: {value}")
    with open(os.path.join(path, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    if state:
        with open(os.path.join(path, ".agent", "state.json"), "w", encoding="utf-8",
                  newline="\n") as f:
            json.dump({"project": project, "phase": "idle", "active_ticket": ticket or None}, f)
    if git:
        os.makedirs(os.path.join(path, ".git"), exist_ok=True)
        with open(os.path.join(path, ".git", "HEAD"), "w", encoding="utf-8", newline="\n") as f:
            f.write("ref: refs/heads/main\n")
    return path


@pytest.fixture()
def tree(tmp_path):
    """One parent folder: two projects, one half-set-up folder, and two decoys.

    The decoys are the two that cost an evening on a real laptop -- a checkout with no `AGENTS.md`
    yet, and a `node_modules` deep enough to make an unbounded walk look hung.
    """
    root = tmp_path / "PycharmProjects"
    root.mkdir()
    a_repo(root, "alpha", project="RDSD", ticket="RDSD-22449",
           facts={"jira_url": "https://acme.atlassian.net", "jira_board_id": "42"})
    a_repo(root, "bravo", project="DATAENG")
    a_repo(root, "half", project="RDSD", state=False)          # no .agent/state.json yet
    (root / "notes").mkdir()                                   # no .git: not a candidate
    os.makedirs(str(root / "node_modules" / "pkg" / ".git"), exist_ok=True)
    return root


def run(argv, capsys) -> tuple[int, str]:
    code = cli_fleet.main(argv)
    return code, capsys.readouterr().out


SCALAR = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*): (.*)$")


def keys(text: str) -> dict:
    """The scalar `key: value` lines of a TOON document, last one wins.

    Table rows are `  a,b,c` with no `key: ` at the front, so they fall out here -- which is what
    makes this readable enough to assert on the meta block without parsing TOON properly.
    """
    out = {}
    for line in text.splitlines():
        m = SCALAR.match(line)
        if m and "," not in line.split(":")[0]:
            out[m.group(1)] = m.group(2).strip()
    return out


def answers(monkeypatch, *replies: str) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(r + "\n" for r in replies)))


# ------------------------------------------------------------------- repo add --scan (#129)


def test_the_scan_proposes_and_registers_nothing_by_itself(fleet_home, tree, capsys, monkeypatch):
    """The scan's whole safety story: it hands the human a list, never the registry a row."""
    answers(monkeypatch)                                        # stdin closed: every answer is EOF
    code, out = run(["repo", "add", "--scan", str(tree)], capsys)

    assert code == 0
    for column in cli_fleet.SCAN_COLUMNS:
        assert column in out, f"the proposal must carry {column}"
    assert "alpha" in out and "bravo" in out and "half" in out
    assert "notes" not in out, "a folder with no .git is not a candidate"
    assert "node_modules" not in out.split("skipped")[0], "node_modules is never proposed"
    assert "nothing is registered yet" in out
    assert list(Registry().repos) == [], "the scan wrote to the registry"


def test_one_yes_one_no_registers_one(fleet_home, tree, capsys, monkeypatch):
    answers(monkeypatch, "y", "n")
    code, out = run(["repo", "add", "--scan", str(tree)], capsys)

    assert code == 0
    assert list(Registry().repos) == ["alpha"], out
    assert "registered: 1" in out


def test_a_for_all_remaining_takes_the_rest(fleet_home, tree, capsys, monkeypatch):
    answers(monkeypatch, "a")
    run(["repo", "add", "--scan", str(tree)], capsys)
    assert list(Registry().repos) == ["alpha", "bravo"]


def test_q_stops_and_keeps_what_was_already_said_yes_to(fleet_home, tree, capsys, monkeypatch):
    answers(monkeypatch, "y", "q")
    code, out = run(["repo", "add", "--scan", str(tree)], capsys)

    assert code == 0
    assert list(Registry().repos) == ["alpha"]
    assert "quit at bravo" in out


def test_a_closed_stdin_registers_nothing_and_names_the_flag(fleet_home, tree, capsys, monkeypatch):
    """A scan run from a script must not read "no answer" as "yes to everything"."""
    answers(monkeypatch)
    _code, out = run(["repo", "add", "--scan", str(tree)], capsys)

    assert list(Registry().repos) == []
    assert "--yes" in out and "nothing on stdin" in out


def test_yes_registers_the_ready_ones_and_reports_the_half_set_up_one(fleet_home, tree, capsys):
    """`Registry.add` refuses a folder without `.agent/state.json`; under --yes that must be a row.

    The bug this prevents: a run that dies halfway with the first half already written, leaving the
    operator to work out which repositories made it in.
    """
    code, out = run(["repo", "add", "--scan", str(tree), "--yes"], capsys)

    assert code == 0
    assert list(Registry().repos) == ["alpha", "bravo"]
    assert "half" in out and "ad-setup --project" in out


def test_only_picks_by_name_and_an_unknown_name_is_refused(fleet_home, tree, capsys):
    code, out = run(["repo", "add", "--scan", str(tree), "--yes", "--only", "bravo"], capsys)
    assert code == 0 and list(Registry().repos) == ["bravo"], out

    code, out = run(["repo", "add", "--scan", str(tree), "--yes", "--only", "charlie"], capsys)
    assert code == 2 and "ok: false" in out
    assert "charlie" in out and "alpha" in out, "the refusal must name what was proposed"


def test_a_rerun_proposes_nothing_new_and_a_deleted_folder_is_drift_not_a_removal(
        fleet_home, tree, capsys):
    """Rerunning is the ordinary case: the operator adds a project and scans the folder again."""
    run(["repo", "add", "--scan", str(tree), "--yes"], capsys)

    _code, out = run(["repo", "add", "--scan", str(tree), "--yes"], capsys)
    assert "drift: 0" in out
    assert "already registered as alpha" in out
    assert "new: 1" in out, "only `half` is still new: it has no .agent/state.json to register"

    import shutil

    shutil.rmtree(str(tree / "bravo"))
    _code, out = run(["repo", "add", "--scan", str(tree), "--yes"], capsys)
    assert "drift: 1" in out and "missing" in out
    assert "bravo" in list(Registry().repos), "drift must never remove a registration"
    assert "ad-fleet repo remove bravo" in out


def test_repo_add_with_neither_a_path_nor_a_scan_says_what_to_type(fleet_home, capsys):
    code, out = run(["repo", "add"], capsys)
    assert code == 2 and "--scan" in out


def test_repo_remove_is_spelled_both_ways(fleet_home, tmp_path, capsys):
    """`scan.drift` tells the operator to run `repo remove`; that has to be a command."""
    Registry().add(make_project(tmp_path / "solo"), name="solo")
    code, _out = run(["repo", "remove", "solo"], capsys)
    assert code == 0 and list(Registry().repos) == []


# ------------------------------------------------------------- index / where / show (#130)


def pbip_report(path: str, name: str, text: str) -> None:
    folder = os.path.join(path, ".agent", "pbip", name)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "REPORT.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


@pytest.fixture()
def indexed(fleet_home, tree, capsys):
    """Two registered repositories, one of which owns the Velocity page."""
    pbip_report(str(tree / "alpha"), "sales", "# Velocity\n\nThe velocity page, by month.\n")
    run(["repo", "add", "--scan", str(tree), "--yes"], capsys)
    run(["index"], capsys)
    capsys.readouterr()
    return tree


def test_index_reports_what_it_read_and_is_incremental(fleet_home, tree, capsys):
    run(["repo", "add", "--scan", str(tree), "--yes"], capsys)
    capsys.readouterr()

    code, out = run(["index"], capsys)
    assert code == 0
    first = keys(out)
    assert first["projects"] == "2" and int(first["read"]) > 0
    assert first["search"].startswith("fts5") or first["search"].startswith("like")

    _code, out = run(["index"], capsys)
    again = keys(out)
    assert again["read"] == "0", "a second index with nothing changed must read nothing"
    assert again["docs"] == first["docs"]

    _code, out = run(["index", "--rebuild"], capsys)
    assert int(keys(out)["read"]) > 0

    _code, out = run(["index", "--repo", "alpha"], capsys)
    assert keys(out)["projects"] == "1"

    code, out = run(["index", "--repo", "nope"], capsys)
    assert code == 2 and "alpha" in out


def test_a_doc_that_carries_a_credential_is_refused_and_the_row_says_where(fleet_home, tree,
                                                                          capsys):
    """The catalogue refuses the doc; this asserts the operator is *told*, with the file named.

    A silent refusal would be the worst of both: the search quietly misses that repository and
    nobody ever learns why, which is how a token stays in an AGENTS.md for a year.
    """
    with open(os.path.join(str(tree / "bravo"), "AGENTS.md"), "a", encoding="utf-8",
              newline="\n") as f:
        f.write("\nCall it with `Authorization: Bearer abc123def456`.\n")
    run(["repo", "add", "--scan", str(tree), "--yes"], capsys)
    capsys.readouterr()

    code, out = run(["index"], capsys)
    assert code == 0
    assert "refused" in out and "bearer" in out
    assert "AGENTS.md" in out and "bravo" in out
    assert "abc123def456" not in out, "the refusal must never quote the value"


def test_where_finds_the_project_that_owns_the_word(indexed, capsys):
    code, out = run(["where", "velocity"], capsys)
    assert code == 0
    assert "matches: 1" in out and "alpha" in out
    assert "pbip_report" in out

    _code, out = run(["where", "nothing-mentions-this"], capsys)
    assert "matches: 0" in out and "try a word" in out


def test_where_before_an_index_says_to_index(fleet_home, capsys):
    _code, out = run(["where", "velocity"], capsys)
    assert "ad-fleet index" in out


def test_show_prints_the_facts_the_state_and_the_link_rail(indexed, capsys):
    code, out = run(["show", "alpha"], capsys)
    assert code == 0
    assert "ticket: RDSD-22449" in out
    assert "https://acme.atlassian.net/browse/RDSD-22449" in out, "the ticket link"
    assert "file:///" in out, "the folder link"
    assert "report_id" in out, "the keys a missing link needs are named"

    code, out = run(["show", "nope"], capsys)
    assert code == 2 and "ad-fleet index" in out


# --------------------------------------------------------------------------- inbox (#132)


@pytest.fixture()
def downloads(tmp_path):
    folder = tmp_path / "Downloads"
    folder.mkdir()
    for name, body in (("RDSD-22449-export.md", "# export\n"),
                       ("notes.md", "just notes\n"),
                       ("setup.exe", "MZ")):
        (folder / name).write_text(body, encoding="utf-8")
    return folder


def test_the_tray_matches_on_the_name_and_says_why_for_the_rest(indexed, downloads, capsys):
    code, out = run(["inbox", "--folder", str(downloads)], capsys)
    assert code == 0
    assert "RDSD-22449-export.md" in out and "alpha" in out
    assert "notes.md" in out and "unsorted" in out
    assert "setup.exe" in out and "executable" in out
    assert "no file here was opened" in out


def _id_of(out: str, name: str) -> str:
    for line in out.splitlines():
        if name in line:
            return line.strip().split(",")[0]
    raise AssertionError(f"{name} is not in the tray:\n{out}")


def test_attach_copies_into_agent_in_and_leaves_the_original(indexed, downloads, capsys):
    """The one write the fleet makes inside a repository, and only on this flag."""
    _code, out = run(["inbox", "--folder", str(downloads)], capsys)
    ident = _id_of(out, "RDSD-22449-export.md")

    code, out = run(["inbox", "--folder", str(downloads), "--attach", ident, "--repo", "alpha"],
                    capsys)
    assert code == 0, out
    landed = os.path.join(str(indexed / "alpha"), ".agent", "in", "RDSD-22449",
                          "RDSD-22449-export.md")
    assert os.path.isfile(landed), out
    assert os.path.isfile(str(downloads / "RDSD-22449-export.md")), "the original must stay"
    assert "still in Downloads" in out

    code, out = run(["inbox", "--folder", str(downloads), "--attach", ident, "--repo", "alpha"],
                    capsys)
    assert code == 0 and "already attached" in out


def test_attach_without_a_repo_names_the_flag(indexed, downloads, capsys):
    _code, out = run(["inbox", "--folder", str(downloads)], capsys)
    ident = _id_of(out, "RDSD-22449-export.md")
    code, out = run(["inbox", "--folder", str(downloads), "--attach", ident], capsys)
    assert code == 2 and "--repo" in out


def test_an_unknown_id_lists_what_is_there(indexed, downloads, capsys):
    code, out = run(["inbox", "--folder", str(downloads), "--attach", "zzzzzz", "--repo", "alpha"],
                    capsys)
    assert code == 2 and "RDSD-22449-export.md" in out


def test_dismiss_hides_a_file_from_the_next_look(indexed, downloads, capsys):
    _code, out = run(["inbox", "--folder", str(downloads)], capsys)
    ident = _id_of(out, "notes.md")

    code, out = run(["inbox", "--folder", str(downloads), "--dismiss", ident], capsys)
    assert code == 0 and "hidden until" in out

    _code, out = run(["inbox", "--folder", str(downloads)], capsys)
    assert "notes.md" not in out and "dismissed: 1" in out


def test_attach_and_dismiss_together_are_refused(indexed, downloads, capsys):
    code, out = run(["inbox", "--folder", str(downloads), "--attach", "a1", "--dismiss", "a1"],
                    capsys)
    assert code == 2 and "one at a time" in out


# ------------------------------------------------------------------- status --polls (#131)


def test_status_polls_prints_one_row_per_source(indexed, capsys):
    code, out = run(["status", "--polls"], capsys)
    assert code == 0
    for source in ("jira", "pr", "powerbi", "git"):
        assert source in out
    assert "interval_s" in out and "stood_down" in out
    assert "day: " in out
    assert "searches" in out, "the operator has to know jira counts searches, not tickets"


def test_a_source_turned_off_in_the_config_says_so(indexed, capsys, monkeypatch):
    from agentdata import config as C

    cfg = C.load()
    C.put(cfg, "fleet.poll.powerbi", False)
    C.save(cfg)
    _code, out = run(["status", "--polls"], capsys)
    row = [line for line in out.splitlines() if line.strip().startswith("powerbi")][0]
    assert "false" in row


# ---------------------------------------------------------------------- quickstart (#134)


SUMMARY = ("repos", "indexed_docs", "tiles_with_ticket", "tiles_missing_facts", "inbox_offered",
           "elapsed")


def test_quickstart_sets_the_desk_up_and_prints_the_six_numbers(fleet_home, tree, downloads,
                                                                capsys):
    code, out = run(["quickstart", str(tree), "--yes", "--no-serve",
                     "--folder-watch", str(downloads)], capsys)
    assert code == 0, out
    summary = keys(out)
    for field in SUMMARY:
        assert field in summary, f"the summary must carry {field}\n{out}"
    assert summary["repos"] == "2"
    assert int(summary["indexed_docs"]) > 0
    assert summary["tiles_with_ticket"] == "1", "only alpha has an active ticket"
    assert summary["tiles_missing_facts"] == "2", "neither repo has the Power BI keys"
    assert summary["inbox_offered"] == "2", "the export and the notes; not the .exe"
    assert summary["refresh"] == "false"
    assert list(Registry().repos) == ["alpha", "bravo"]


def test_a_second_quickstart_is_a_refresh_with_the_same_counts(fleet_home, tree, downloads, capsys):
    _code, first = run(["quickstart", str(tree), "--yes", "--no-serve",
                        "--folder-watch", str(downloads)], capsys)
    _code, second = run(["quickstart", str(tree), "--yes", "--no-serve",
                         "--folder-watch", str(downloads)], capsys)

    before, after = keys(first), keys(second)
    assert after["refresh"] == "true"
    for field in ("repos", "indexed_docs", "tiles_with_ticket", "tiles_missing_facts",
                  "inbox_offered"):
        assert after[field] == before[field], f"{field} moved on a refresh"


def test_quickstart_serves_last_and_hands_over_the_url_with_the_layout(fleet_home, tree, capsys,
                                                                       monkeypatch):
    """The summary is printed *before* the server blocks, or the operator would never see it."""
    from agentdata.fleet import serve as S

    served = []
    monkeypatch.setattr(S, "run", lambda server: served.append(server.server_close()))
    monkeypatch.setattr("webbrowser.open", lambda url: served.append(url) or True)

    code, out = run(["quickstart", str(tree), "--yes", "--port", "0", "--layout", "roles"], capsys)
    assert code == 0 and len(served) == 2, out
    assert "layout=roles" in out
    assert out.index("elapsed") < out.index("stop with Ctrl-C"), "the summary comes first"


def test_quickstart_refuses_a_folder_that_is_not_there(fleet_home, tmp_path, capsys):
    code, out = run(["quickstart", str(tmp_path / "nope"), "--yes", "--no-serve"], capsys)
    assert code == 2 and "no such folder" in out


# ------------------------------------------------------------------ serve --layout (#122)


@pytest.mark.parametrize("layout", ["grid", "roles", "screens"])
def test_the_layout_reaches_the_page_as_a_query_parameter(fleet_home, capsys, monkeypatch, layout):
    """The flag is this file's, the rendering is the dashboard's; the parameter name is the seam."""
    from agentdata.fleet import serve as S

    closed = []
    monkeypatch.setattr(S, "run", lambda server: closed.append(server.server_close()))
    code, out = run(["serve", "--port", "0", "--layout", layout], capsys)

    assert code == 0 and closed
    assert f"{cli_fleet.LAYOUT_PARAM}={layout}" in out
    assert "127.0.0.1" in out


def test_an_unknown_layout_is_refused_by_the_parser(fleet_home):
    with pytest.raises(SystemExit):
        cli_fleet.main(["serve", "--layout", "carousel"])


def test_the_layout_is_appended_after_the_token(fleet_home):
    """`url_for` already carries `?t=…`, so the layout has to join with `&` or the token is lost."""
    assert cli_fleet._layout_url("http://127.0.0.1:1/?t=abc", "roles") == \
        "http://127.0.0.1:1/?t=abc&layout=roles"
    assert cli_fleet._layout_url("http://127.0.0.1:1/", "grid") == "http://127.0.0.1:1/?layout=grid"
