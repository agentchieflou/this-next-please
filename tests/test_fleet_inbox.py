"""The Downloads tray: what it offers, what it refuses, what it never opens, and the one write.

The fixture is the operator's desk from #132 -- a temporary Downloads holding
`RDSD-22449-export.md`, `velocity (3).json`, `setup.exe` and `notes.md`, with a `.env` and a
half-written `.crdownload` planted beside them -- and a two-repository fleet whose `velocity` repo
is working RDSD-22449.

The load-bearing test is `test_a_look_opens_nothing_at_all`: `look()` decides everything from names
and `os.stat`, and the open-recording fixture is what keeps that true the first time somebody adds
a convenience that peeks inside a JSON file to be helpful.
"""
from __future__ import annotations
import builtins
import json
import os
import time

import pytest

from agentdata import cli_state
from agentdata import textio
from agentdata.fleet import events as E
from agentdata.fleet import inbox as I
from agentdata.fleet.inbox import Inbox, InboxError, Offer
from agentdata.fleet.registry import Registry


# ------------------------------------------------------------------------------- the fixtures


DESK = {
    "RDSD-22449-export.md": "# export\n",
    "velocity (3).json": '{"sprint": 41}\n',
    "setup.exe": "MZ\x00\x00not really\n",
    "notes.md": "reminder\n",
}
PLANTED = {
    ".env": "JIRA_TOKEN=notarealtokenatall000000\n",
    "statement.pdf.crdownload": "half a file\n",
    "bank.pdf.partial": "half a file\n",
}


def _write(path: str, text: str, *, mtime: float | None = None) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def make_repo(root, name: str, *, jira_project: str, active_ticket=None) -> str:
    path = os.path.join(str(root), name)
    _write(os.path.join(path, "AGENTS.md"),
           f"# Project: {name}\n\n## Project facts\n- jira_project: {jira_project}\n")
    _write(os.path.join(path, ".agent", "state.json"),
           json.dumps({"project": name, "phase": "querying", "active_ticket": active_ticket,
                       "open_questions": [], "artifacts": []}))
    return path


@pytest.fixture()
def downloads(tmp_path):
    """A Downloads folder with the four files from the issue, plus the traps."""
    folder = tmp_path / "Downloads"
    folder.mkdir()
    now = time.time()
    for i, (name, body) in enumerate(DESK.items()):
        _write(str(folder / name), body, mtime=now - 60 * (i + 1))
    for name, body in PLANTED.items():
        _write(str(folder / name), body, mtime=now - 30)
    return str(folder)


@pytest.fixture()
def fleet(tmp_path):
    """Two registered repositories: `velocity` (RDSD, on RDSD-22449) and `billing` (BILL)."""
    root = tmp_path / "projects"
    make_repo(root, "velocity", jira_project="RDSD", active_ticket="RDSD-22449")
    make_repo(root, "billing", jira_project="BILL")
    reg = Registry()
    reg.add(str(root / "velocity"))
    reg.add(str(root / "billing"))
    return reg


@pytest.fixture()
def inbox(downloads, fleet):
    return Inbox(folders=[downloads], registry=fleet)


@pytest.fixture()
def opened(monkeypatch):
    """Every path handed to `builtins.open`, so a test can assert on what was *not* read."""
    seen: list[str] = []
    real = builtins.open

    def recording(file, *a, **kw):
        try:
            seen.append(os.path.abspath(os.fspath(file)))
        except TypeError:                        # a file descriptor, not a path
            pass
        return real(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", recording)
    return seen


def link_or_skip(target: str, link: str) -> str:
    """A symlink, or a skipped test: Windows makes one only in Developer Mode or an elevated shell,
    and a runner that cannot is not a runner that should fail."""
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError) as e:
        pytest.skip(f"this machine will not create a symlink: {e}")
    return link


def by_name(offers: list[Offer]) -> dict[str, Offer]:
    return {o.name: o for o in offers}


@pytest.fixture(autouse=True)
def never_really_run_ad_state(monkeypatch):
    """No subprocess in the suite by default. The ask is tested where it is the subject."""
    monkeypatch.setattr(Inbox, "_ask_ad_state", staticmethod(lambda *a, **kw: ""))


# --------------------------------------------------------------- the contract other slices read


def test_the_offered_types_and_the_cap_are_the_ones_the_epic_fixed():
    assert I.OFFER_TYPES == frozenset({"md", "json", "csv", "tsv", "xlsx", "docx", "pdf", "txt"})
    assert I.SIZE_CAP == 25 * 1024 * 1024
    assert I.TICKET_RE.pattern == r"\b[A-Z][A-Z0-9]+-\d+\b"
    assert I.ATTACHED == "inbox.attached"


def test_an_offer_carries_only_what_a_directory_listing_knows():
    fields = list(Offer.__dataclass_fields__)
    assert fields == ["path", "name", "size", "ext", "age_s", "project", "ticket", "offered",
                      "reason"]


# ------------------------------------------------------------------------- the four-file desk


def test_the_four_files_land_where_the_issue_says_they_do(inbox):
    rows = by_name(inbox.look())

    export = rows["RDSD-22449-export.md"]
    assert (export.project, export.ticket, export.offered) == ("velocity", "RDSD-22449", True)
    assert "active ticket" in export.reason

    velocity = rows["velocity (3).json"]
    assert (velocity.project, velocity.offered) == ("velocity", True)
    assert "project name" in velocity.reason

    setup = rows["setup.exe"]
    assert setup.offered is False and setup.reason == "not offered: executable"

    notes = rows["notes.md"]
    assert (notes.project, notes.ticket, notes.offered) == ("", "", True)
    assert notes.reason.startswith("unsorted:")


def test_a_project_name_that_matches_nothing_leaves_the_file_unsorted(downloads, tmp_path):
    """The issue's own alternative: rename the repo and `velocity (3).json` has nowhere to go."""
    make_repo(tmp_path / "other", "reporting", jira_project="RDSD", active_ticket="RDSD-22449")
    reg = Registry()
    reg.add(str(tmp_path / "other" / "reporting"))
    rows = by_name(Inbox(folders=[downloads], registry=reg).look())

    assert rows["velocity (3).json"].project == ""
    assert rows["velocity (3).json"].reason.startswith("unsorted:")
    assert rows["RDSD-22449-export.md"].project == "reporting"    # the ticket key still routes


def test_a_ticket_key_nobody_is_working_falls_back_to_the_jira_project(downloads, inbox):
    _write(os.path.join(downloads, "RDSD-90001-triage.md"), "x\n")
    row = by_name(inbox.look())["RDSD-90001-triage.md"]
    assert (row.project, row.ticket) == ("velocity", "RDSD-90001")
    assert row.reason == "RDSD is velocity's jira_project"


def test_a_ticket_key_for_a_project_nobody_registered_is_unsorted(downloads, inbox):
    _write(os.path.join(downloads, "ZZZ-1-export.md"), "x\n")
    row = by_name(inbox.look())["ZZZ-1-export.md"]
    assert (row.project, row.ticket, row.offered) == ("", "ZZZ-1", True)


def test_two_projects_that_match_equally_well_are_never_guessed_between(downloads, tmp_path):
    root = tmp_path / "twins"
    make_repo(root, "alpha", jira_project="AAA")
    make_repo(root, "gamma", jira_project="BBB")
    reg = Registry()
    reg.add(str(root / "alpha"))
    reg.add(str(root / "gamma"))
    _write(os.path.join(downloads, "alpha-gamma-handover.json"), "{}\n")

    row = by_name(Inbox(folders=[downloads], registry=reg).look())["alpha-gamma-handover.json"]
    assert row.project == "" and "both match the name" in row.reason


def test_the_more_specific_project_name_wins_over_the_shorter_one(downloads, tmp_path):
    root = tmp_path / "nested"
    make_repo(root, "velocity", jira_project="AAA")
    make_repo(root, "velocity-reports", jira_project="BBB")
    reg = Registry()
    reg.add(str(root / "velocity"))
    reg.add(str(root / "velocity-reports"))
    _write(os.path.join(downloads, "velocity-reports-export.json"), "{}\n")

    row = by_name(Inbox(folders=[downloads], registry=reg).look())["velocity-reports-export.json"]
    assert row.project == "velocity-reports"


def test_two_projects_sharing_a_jira_project_are_never_guessed_between(downloads, tmp_path):
    root = tmp_path / "shared"
    make_repo(root, "front", jira_project="RDSD")
    make_repo(root, "back", jira_project="RDSD")
    reg = Registry()
    reg.add(str(root / "front"))
    reg.add(str(root / "back"))

    row = by_name(Inbox(folders=[downloads], registry=reg).look())["RDSD-22449-export.md"]
    assert row.project == "" and "jira_project RDSD" in row.reason


# ------------------------------------------------------------- refusals, always with the reason


def test_an_oversized_file_is_listed_with_its_reason_not_hidden(downloads, inbox):
    big = os.path.join(downloads, "RDSD-22449-dump.csv")
    _write(big, "x")
    with open(big, "wb") as f:
        f.seek(I.SIZE_CAP + 1)
        f.write(b"\0")

    row = by_name(inbox.look())["RDSD-22449-dump.csv"]
    assert row.offered is False
    assert "over the 25 MB cap" in row.reason


@pytest.mark.parametrize("name,fragment", [
    ("installer.msi", "executable"),
    ("hook.ps1", "executable"),
    ("archive.zip", "archive"),
    ("model.pbix", "not an offered type"),
    ("README", "no extension"),
])
def test_everything_not_offered_says_why(downloads, inbox, name, fragment):
    _write(os.path.join(downloads, name), "x\n")
    row = by_name(inbox.look())[name]
    assert row.offered is False and fragment in row.reason


def test_a_link_that_leads_out_of_the_folder_is_listed_with_where_it_goes_and_not_offered(
        downloads, inbox, tmp_path):
    """The row that lied to the person clicking it. `os.stat` follows a link, so the size and age
    described the file the link pointed at -- outside Downloads, outside everything the operator
    asked to be watched -- under the name of the link, and one click copied that file into a
    repository. Refused, and refused *visibly*: the row keeps its place and says where it goes."""
    outside = _write(str(tmp_path / "elsewhere" / "tax-2025.md"),
                     "the operator's own business, and a good many more bytes of it\n")
    link = link_or_skip(outside, os.path.join(downloads, "RDSD-22449-report.md"))

    row = by_name(inbox.look())["RDSD-22449-report.md"]
    assert row.offered is False
    assert "leads out of the watched folder" in row.reason
    assert textio.norm_path(outside) in row.reason
    assert row.size == os.lstat(link).st_size != os.path.getsize(outside)


def test_attaching_a_link_that_leads_out_copies_nothing(downloads, inbox, fleet, tmp_path):
    outside = _write(str(tmp_path / "elsewhere" / "secret.md"), "outside\n")
    link_or_skip(outside, os.path.join(downloads, "RDSD-22449-secret.md"))

    with pytest.raises(InboxError) as e:
        inbox.attach(by_name(inbox.look())["RDSD-22449-secret.md"], "velocity")
    assert "leads out of the watched folder" in e.value.msg and e.value.hint
    assert not os.path.exists(os.path.join(fleet.get("velocity").path, ".agent", "in",
                                           "RDSD-22449", "RDSD-22449-secret.md"))


def test_a_link_that_appears_after_the_look_is_still_refused_at_the_click(downloads, inbox, fleet,
                                                                         tmp_path):
    """The row is from the last tick and the click is now; `copy2` would follow a link swapped in
    between, so the question is asked again at the one moment it can do harm."""
    offer = offered(inbox, "notes.md")
    outside = _write(str(tmp_path / "elsewhere" / "notes.md"), "somebody else's notes\n")
    os.remove(os.path.join(downloads, "notes.md"))
    link_or_skip(outside, os.path.join(downloads, "notes.md"))

    with pytest.raises(InboxError) as e:
        inbox.attach(offer, "billing")
    assert "leads out of the watched folder" in e.value.msg
    assert not os.path.exists(os.path.join(fleet.get("billing").path, ".agent", "in",
                                           I.UNSORTED_KEY, "notes.md"))


def test_a_link_inside_the_watched_folder_is_just_a_second_name_for_the_file(downloads, inbox):
    """The harmless case stays offered: the file is in the watched folder either way, and the size
    and the age on the row are the ones the operator would get."""
    link_or_skip(os.path.join(downloads, "RDSD-22449-export.md"),
                 os.path.join(downloads, "RDSD-22449-export-copy.md"))

    row = by_name(inbox.look())["RDSD-22449-export-copy.md"]
    assert (row.offered, row.project) == (True, "velocity")
    event = inbox.attach(row, "velocity")
    assert event["data"]["attached"] is True
    assert textio.read_text(event["data"]["file"]) == DESK["RDSD-22449-export.md"]


def test_a_link_out_row_can_be_dismissed_like_any_other(downloads, inbox, tmp_path):
    """The dismissal is keyed to the time the row showed, which for a refused link is the link's
    own. Keyed to the target's instead, the row would be back on the next tick and the operator
    would be clicking dismiss forever."""
    outside = _write(str(tmp_path / "elsewhere" / "old.md"), "x\n", mtime=time.time() - 3600)
    link_or_skip(outside, os.path.join(downloads, "old-report.md"))

    inbox.dismiss(by_name(inbox.look())["old-report.md"])
    assert "old-report.md" not in by_name(inbox.look())


def test_a_download_still_in_flight_is_not_offered_at_all(inbox):
    """A `.crdownload` is a browser mid-write; offering it attaches a truncated file."""
    listed = by_name(inbox.look())
    assert "statement.pdf.crdownload" not in listed
    assert "bank.pdf.partial" not in listed


def test_folders_are_ignored(downloads, inbox):
    os.makedirs(os.path.join(downloads, "RDSD-22449-report.pbip"), exist_ok=True)
    assert "RDSD-22449-report.pbip" not in by_name(inbox.look())


def test_a_hidden_windows_file_is_not_a_row(downloads, inbox, monkeypatch):
    """`desktop.ini` is in every Downloads folder on the laptop and nobody saved it on purpose."""
    _write(os.path.join(downloads, "desktop.ini"), "[.ShellClassInfo]\n")
    real = os.DirEntry.stat

    def with_attributes(self, *a, **kw):
        st = real(self, *a, **kw)
        if self.name == "desktop.ini":
            return type("S", (), {"st_size": st.st_size, "st_mtime": st.st_mtime,
                                  "st_file_attributes": I._HIDDEN or 2})()
        return st

    monkeypatch.setattr(os.DirEntry, "stat", with_attributes, raising=False)
    monkeypatch.setattr(I, "_HIDDEN", I._HIDDEN or 2)
    assert "desktop.ini" not in by_name(inbox.look())


def test_a_file_older_than_the_look_back_is_not_news(downloads, inbox):
    _write(os.path.join(downloads, "ancient.md"), "x\n",
           mtime=time.time() - I.LOOK_BACK_S - 3600)
    assert "ancient.md" not in by_name(inbox.look())


# ----------------------------------------------------------------------- never opening anything


def test_a_look_opens_nothing_at_all(downloads, inbox, opened):
    """The whole promise, as a test: names and `os.stat`, never a byte of a candidate."""
    inbox.look()
    touched = [p for p in opened
               if os.path.abspath(p).startswith(os.path.abspath(downloads) + os.sep)]
    assert touched == []


def test_a_planted_credential_file_is_never_opened_and_never_offered(downloads, inbox, opened):
    inbox.look()
    assert not [p for p in opened if p.replace("\\", "/").endswith("/.env")]
    assert ".env" not in by_name(inbox.look())


# ------------------------------------------------------------------- surviving a locked file


def test_a_locked_file_does_not_break_the_tick(downloads, inbox, monkeypatch):
    """Antivirus holds a fresh download and `stat` answers PermissionError. Epic #63/#69: the file
    is left for the next tick and everything else still lists."""
    real = os.DirEntry.stat

    def refusing(self, *a, **kw):
        if self.name == "notes.md":
            raise PermissionError(13, "being scanned")
        return real(self, *a, **kw)

    monkeypatch.setattr(os.DirEntry, "stat", refusing, raising=False)
    rows = by_name(inbox.look())

    assert "notes.md" not in rows
    assert "RDSD-22449-export.md" in rows                     # the tick survived
    assert [r["name"] for r in inbox.retry] == ["notes.md"]

    monkeypatch.undo()
    assert "notes.md" in by_name(inbox.look())                # retried, not lost


def test_a_folder_that_cannot_be_listed_is_reported_not_raised(downloads, fleet, tmp_path):
    box = Inbox(folders=[downloads, str(tmp_path / "no-such-folder")], registry=fleet)
    assert len(box.look()) >= 4
    assert box.retry and box.retry[0]["name"] == "no-such-folder"


# ------------------------------------------------------------------------------- attaching


def offered(inbox, name: str) -> Offer:
    return by_name(inbox.look())[name]


def test_attach_copies_leaves_the_original_and_emits_the_event(inbox, fleet, downloads):
    offer = offered(inbox, "RDSD-22449-export.md")
    event = inbox.attach(offer, fleet.get("velocity"))

    dest = os.path.join(fleet.get("velocity").path, ".agent", "in", "RDSD-22449",
                        "RDSD-22449-export.md")
    assert os.path.isfile(dest)
    assert textio.read_text(dest) == DESK["RDSD-22449-export.md"]
    assert os.path.isfile(os.path.join(downloads, "RDSD-22449-export.md"))   # never moved

    assert event["kind"] == "inbox.attached"
    assert event["repo"] == "velocity" and event["ticket"] == "RDSD-22449"
    assert event["data"]["attached"] is True
    assert event["data"]["dir"] == ".agent/in/RDSD-22449"
    assert event["seq"] >= 1
    assert [e["kind"] for e in E.read("velocity")] == ["inbox.attached"]


def test_attach_takes_the_repo_by_name_too(inbox, fleet):
    event = inbox.attach(offered(inbox, "RDSD-22449-export.md"), "velocity")
    assert event["data"]["attached"] is True


def test_a_file_with_no_ticket_anywhere_lands_under_unsorted(inbox, fleet):
    event = inbox.attach(offered(inbox, "notes.md"), "billing")
    assert event["data"]["dir"] == f".agent/in/{I.UNSORTED_KEY}"
    assert os.path.isfile(os.path.join(fleet.get("billing").path, ".agent", "in",
                                       I.UNSORTED_KEY, "notes.md"))


def test_a_file_with_no_ticket_borrows_the_repos_active_ticket(inbox, fleet):
    """`velocity (3).json` has no key in its name, but velocity is working one."""
    event = inbox.attach(offered(inbox, "velocity (3).json"), "velocity")
    assert event["data"]["dir"] == ".agent/in/RDSD-22449"


def test_the_second_attach_of_the_same_file_is_a_no_op_with_a_message(inbox, fleet):
    offer = offered(inbox, "RDSD-22449-export.md")
    assert inbox.attach(offer, "velocity")["data"]["attached"] is True

    again = inbox.attach(offer, "velocity")
    assert again["data"]["attached"] is False
    assert "already attached" in again["data"]["why"]
    assert len(E.read("velocity")) == 1              # one write, one event, however many clicks


def test_a_newer_download_of_the_same_name_does_attach_again(inbox, fleet, downloads):
    inbox.attach(offered(inbox, "RDSD-22449-export.md"), "velocity")
    _write(os.path.join(downloads, "RDSD-22449-export.md"), "# a newer export\n",
           mtime=time.time() + 5)

    again = inbox.attach(offered(inbox, "RDSD-22449-export.md"), "velocity")
    assert again["data"]["attached"] is True
    dest = os.path.join(fleet.get("velocity").path, ".agent", "in", "RDSD-22449",
                        "RDSD-22449-export.md")
    assert textio.read_text(dest) == "# a newer export\n"


def test_attaching_a_file_that_is_not_offered_is_refused_with_a_hint(inbox, fleet):
    with pytest.raises(InboxError) as e:
        inbox.attach(offered(inbox, "setup.exe"), "velocity")
    assert "not offered" in e.value.msg and e.value.hint


def test_the_copy_can_never_escape_agent_in(inbox, fleet):
    """`safe_name` neutralises the separators; the check after it is the belt, not the braces."""
    hostile = Offer(path=os.path.join(str(fleet.get("velocity").path), "AGENTS.md"),
                    name="../../../AGENTS.md", size=4, ext="md", offered=True)
    event = inbox.attach(hostile, "velocity")
    assert event["data"]["file"].startswith(
        textio.norm_path(os.path.join(fleet.get("velocity").path, ".agent", "in")) + "/")


def test_the_fleet_still_never_writes_state_json(inbox, fleet):
    """The one exception is `.agent/in/`. `state.json` is `ad-state`'s, before and after an attach."""
    state = fleet.get("velocity").state_file
    before = (os.path.getmtime(state), textio.read_text(state))
    inbox.attach(offered(inbox, "RDSD-22449-export.md"), "velocity")
    assert (os.path.getmtime(state), textio.read_text(state)) == before


def test_the_input_is_asked_of_ad_state_never_written_here(inbox, fleet, monkeypatch):
    asked: list[tuple] = []
    monkeypatch.setattr(Inbox, "_ask_ad_state",
                        staticmethod(lambda repo, dest, key: asked.append((repo.name, dest, key)) or ""))
    event = inbox.attach(offered(inbox, "RDSD-22449-export.md"), "velocity")

    assert asked and asked[0][0] == "velocity" and asked[0][2] == "RDSD-22449"
    assert event["data"]["recorded"] is True


def test_ad_state_refusing_does_not_lose_the_attach(inbox, fleet, monkeypatch):
    """The copy is the contract; the `inputs` line is the courtesy. Losing the first because the
    second failed would be the wrong trade, and the row has to say so."""
    monkeypatch.setattr(Inbox, "_ask_ad_state",
                        staticmethod(lambda *a, **kw: "ad-state could not be run (not_found)"))
    event = inbox.attach(offered(inbox, "RDSD-22449-export.md"), "velocity")

    assert event["data"]["attached"] is True
    assert event["data"]["recorded"] is False
    assert "ad-state" in event["data"]["why"]
    assert os.path.isfile(event["data"]["file"])


def test_the_ask_is_a_request_to_ad_state_in_the_repos_own_directory(inbox, fleet, monkeypatch):
    seen: dict = {}

    def fake_run(argv, **kw):
        seen.update(argv=argv, cwd=kw.get("cwd"))
        return 0, "", "", 0.0

    monkeypatch.undo()                        # take back the autouse stub: this is the subject
    monkeypatch.setattr(I.proc, "run", fake_run)
    inbox.attach(offered(inbox, "RDSD-22449-export.md"), "velocity")

    assert seen["argv"][:2] == ["ad-state", "set"]
    assert seen["argv"][-1] == ".agent/in/RDSD-22449/RDSD-22449-export.md"
    assert seen["cwd"] == fleet.get("velocity").path


def test_ad_state_accepts_the_argv_the_fleet_sends_and_records_the_input(inbox, fleet, monkeypatch):
    """#132's "`ad-state show` lists the input", end to end and without a subprocess: the argv
    `_ask_ad_state` builds is handed to `ad-state`'s own parser, in the repository, and `ad-state`
    -- not the fleet -- writes it. Until `--input` existed that argv exited 2 with `unrecognized
    arguments: --input`, so every attach reported `recorded: false` and nothing was ever recorded;
    the suite missed it because the ask is stubbed in every other test here."""
    def in_process(argv, **kw):
        here = os.getcwd()
        os.chdir(kw["cwd"])
        try:
            return cli_state.main(list(argv[1:])), "", "", 0.0
        finally:
            os.chdir(here)

    monkeypatch.undo()                        # take back the autouse stub: this is the subject
    monkeypatch.setattr(I.proc, "run", in_process)
    event = inbox.attach(offered(inbox, "RDSD-22449-export.md"), "velocity")

    assert (event["data"]["recorded"], event["data"]["why"]) == (True, "")
    state = json.loads(textio.read_text(fleet.get("velocity").state_file))
    assert state["inputs"] == [".agent/in/RDSD-22449/RDSD-22449-export.md"]


# ------------------------------------------------------------------------------- dismissals


def test_dismiss_hides_the_file_and_survives_a_restart(inbox, downloads, fleet):
    inbox.dismiss(offered(inbox, "notes.md"))
    assert "notes.md" not in by_name(inbox.look())

    restarted = Inbox(folders=[downloads], registry=fleet)
    assert "notes.md" not in by_name(restarted.look())
    assert [d["name"] for d in restarted.dismissed()] == ["notes.md"]


def test_a_newer_file_with_the_same_name_is_offered_again(inbox, downloads):
    inbox.dismiss(offered(inbox, "notes.md"))
    assert "notes.md" not in by_name(inbox.look())

    _write(os.path.join(downloads, "notes.md"), "a second thought\n", mtime=time.time() + 10)
    assert "notes.md" in by_name(inbox.look())


def test_the_dismissal_file_lives_outside_every_repository(inbox, tmp_path, fleet):
    inbox.dismiss(offered(inbox, "notes.md"))
    written = textio.norm_path(inbox.state_path)
    assert written.endswith("/fleet/inbox.json")
    assert textio.norm_path(str(tmp_path / "home")) in written
    for repo in fleet.sorted():
        assert not written.startswith(textio.norm_path(repo.path))


def test_a_dismissal_remembers_a_name_and_a_time_and_nothing_else(inbox):
    inbox.dismiss(offered(inbox, "notes.md"))
    saved = json.loads(textio.read_text(inbox.state_path))
    assert saved["version"] == I.STATE_VERSION
    assert set(saved["dismissed"][0]) == {"name", "mtime", "at"}


def test_an_unreadable_dismissal_file_is_not_fatal(downloads, fleet, tmp_path):
    path = str(tmp_path / "broken.json")
    _write(path, "{not json at all\n")
    box = Inbox(folders=[downloads], registry=fleet, state_path=path)
    assert len(box.look()) >= 4 and box.dismissed() == []


# ------------------------------------------------------------------------------- the folders


def test_the_default_folder_is_the_users_downloads(tmp_path, monkeypatch):
    home = os.path.expanduser("~")
    os.makedirs(os.path.join(home, "Downloads"), exist_ok=True)
    assert I.default_folders() == [textio.norm_path(os.path.join(home, "Downloads"))]


def test_more_than_one_folder_may_be_watched(downloads, fleet, tmp_path):
    second = tmp_path / "Desktop"
    second.mkdir()
    _write(str(second / "RDSD-22449-notes.md"), "x\n")
    rows = by_name(Inbox(folders=[downloads, str(second)], registry=fleet).look())
    assert "RDSD-22449-notes.md" in rows and "RDSD-22449-export.md" in rows


def test_an_id_is_stable_between_looks_and_unique_between_files(inbox):
    first = {o.name: o.id for o in inbox.look()}
    second = {o.name: o.id for o in inbox.look()}
    assert first == second
    assert len(set(first.values())) == len(first)
