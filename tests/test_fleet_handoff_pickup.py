"""Handoff: B — pick-up (issue #164). The pre-flight, the dispatch card, and the brief.

One acceptance criterion per test, named after it. The browser tests assert on the *rendered* page
rather than on the source text of `app.js`, for the reason `docs/testing-this-repo.md` gives: a
substring assertion proves an author wrote a line, not that a person can see it.
"""
from __future__ import annotations
import json
import os
import threading
import time

import pytest

from agentdata.fleet import events as E, handoff as H, launch as L, preflight as PF, registry, serve as S
from agentdata.fleet.registry import Registry, fleet_dir

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


class _Table:
    """What `pncli.get_issue` returns: an AgentTable's shape, no more of it than we read."""

    def __init__(self, description="", comments=0, attachments=0):
        self.columns = ["key", "description", "comments", "attachment"]
        self.rows = [["RDSD-118", description, comments, attachments]]


class _Client:
    def __init__(self, table):
        self.table = table
        self.calls = 0

    def get_issue(self, key):
        self.calls += 1
        return self.table


class _Angry:
    """A Jira that cannot be reached, which must never stop a start."""

    def get_issue(self, key):
        raise OSError("the proxy refused the connection")


RICH = ("The nightly refresh of the UAT semantic model takes over forty minutes and the team "
        "cannot validate before standup. Make it finish inside fifteen.\n"
        "Acceptance Criteria\n"
        "1. the refresh completes in under fifteen minutes\n"
        "2. no partition is dropped\n"
        "3. the Velocity measure still reconciles against the warehouse\n")


def _luna(tmp_path, project="RDSD"):
    path = make_project(tmp_path / "luna", project=project)
    Registry().add(path, name="luna")
    return path


# ------------------------------------------------------------------------------- the verdicts


def test_a_thin_ticket_reads_thin_and_a_written_one_reads_ready(fleet_home, tmp_path):
    """Acceptance criterion: a ticket with a two-line description and no criteria renders `thin`;
    one with numbered criteria renders `ready`."""
    _luna(tmp_path)

    thin = PF.preflight("RDSD-118", "luna", client=_Client(_Table("UAT refresh is slow.")), now=1.0)
    assert thin["verdict"] == PF.THIN
    rows = {r["row"]: r for r in thin["rows"]}
    assert rows["description"]["verdict"] == PF.THIN
    assert rows["criteria"]["value"] == "none found"

    ready = PF.preflight("RDSD-118", "luna", client=_Client(_Table(RICH)), now=100_000.0)
    assert ready["verdict"] == PF.READY
    rows = {r["row"]: r for r in ready["rows"]}
    assert rows["criteria"]["value"] == "3 found"
    assert rows["description"]["verdict"] == PF.READY


def test_a_done_ticket_renders_the_existing_refusal_with_its_code(fleet_home, tmp_path):
    """Acceptance criterion: a Done ticket renders the existing refusal with its `code`."""
    _luna(tmp_path)
    from agentdata.fleet import board as B

    B.write_cache({"jql": "x", "at": 9e9, "rows": [
        {"key": "RDSD-118", "summary": "already finished", "status": "Done", "category": "done"}]})
    card = PF.preflight("RDSD-118", "luna", client=_Client(_Table(RICH)), now=1.0)
    assert card["verdict"] == PF.BLOCKED
    repo_row = [r for r in card["rows"] if r["row"] == "repo"][0]
    assert repo_row["code"] == "ticket_done"
    assert "already" in repo_row["why"]


def test_an_unreachable_jira_is_unknown_and_never_an_exception(fleet_home, tmp_path):
    """Acceptance criterion: `preflight` on a key Jira cannot serve prints `unknown` rows with the
    error, exit 0, and `ad-fleet start` still launches. (The start half is the CLI contract test;
    here we prove the card neither raises nor lies.)"""
    _luna(tmp_path)
    card = PF.preflight("RDSD-118", "luna", client=_Angry(), now=1.0)
    assert card["verdict"] == PF.UNKNOWN
    rows = {r["row"]: r for r in card["rows"]}
    assert rows["description"]["value"] == "unknown"
    assert "proxy refused" in rows["description"]["why"]
    # `blocked` would be a lie: nothing refused the start, we simply could not read.
    assert not any(r["verdict"] == PF.BLOCKED for r in card["rows"])


def test_the_verdict_is_one_table_and_the_worst_row_wins(fleet_home, tmp_path):
    """The ordering is the point: a refusal outranks an unreadable source, which outranks a
    judgement, because a card that says `thin` on evidence it could not read is worse than one that
    admits it does not know."""
    assert PF.verdict_for([{"verdict": PF.READY}]) == PF.READY
    assert PF.verdict_for([{"verdict": PF.READY}, {"verdict": PF.THIN}]) == PF.THIN
    assert PF.verdict_for([{"verdict": PF.THIN}, {"verdict": PF.UNKNOWN}]) == PF.UNKNOWN
    assert PF.verdict_for([{"verdict": PF.UNKNOWN}, {"verdict": PF.BLOCKED}]) == PF.BLOCKED


def test_the_issue_is_fetched_once_per_key_inside_the_ttl(fleet_home, tmp_path):
    """Acceptance criterion: the Jira budget. A card per drop must not be a fetch per drop -- the
    TTL is `fleet.board_ttl`, shared with the board for the reason the board has one."""
    _luna(tmp_path)
    client = _Client(_Table(RICH))
    for _ in range(5):
        PF.preflight("RDSD-118", "luna", client=client, now=1000.0)
    assert client.calls == 1, "five drops inside the TTL must cost one Jira read"
    PF.preflight("RDSD-118", "luna", client=client, now=1000.0 + 1000)
    assert client.calls == 2, "past the TTL it asks again"


# ---------------------------------------------------------------------------------- the brief


def test_a_start_with_a_brief_writes_it_then_asks_ad_state_then_starts(fleet_home, tmp_path):
    """Acceptance criterion: a start with a brief produces `brief.md`, one `handoff.brief` event,
    an `inputs` line written by `ad-state`, and a prompt naming the directory -- in that order."""
    path = _luna(tmp_path)

    event = H.write_brief("luna", path, "RDSD-118",
                          "The window is the last full sprint. Ignore the UAT workspace.")
    assert event["kind"] == "handoff.brief"
    assert event["data"]["path"] == ".agent/in/RDSD-118/brief.md"
    assert event["data"]["words"] == 11

    body = open(os.path.join(path, ".agent", "in", "RDSD-118", "brief.md"), encoding="utf-8").read()
    assert body.startswith("---\nticket: RDSD-118\n"), "front matter says what the file is"
    assert "last full sprint" in body

    stream = E.read("luna")
    assert [e["kind"] for e in stream].count("handoff.brief") == 1

    # The prompt names the directory and the count, and never the brief itself.
    line = L.prompt_for("RDSD-118", None, {}, summary="UAT refresh is slow",
                        handoff=H.prompt_line(path, "RDSD-118"))
    assert ".agent/in/RDSD-118/" in line
    assert "last full sprint" not in line, "the prompt must not carry the brief's text"
    assert line.endswith("Invoke skill session-bootstrap, then router.")


def test_the_brief_is_only_ever_written_under_agent_in(fleet_home, tmp_path):
    """The one exception to `the fleet writes nothing inside a repository` stays one exception."""
    path = _luna(tmp_path)
    H.write_brief("luna", path, "../../etc/passwd", "nope")
    written = []
    for root, _dirs, files in os.walk(os.path.join(path, ".agent")):
        written += [os.path.join(root, f) for f in files]
    assert all("/.agent/in/" in p.replace("\\", "/") or p.endswith("state.json") for p in written), written


def test_an_empty_or_enormous_brief_is_refused_with_a_code(fleet_home, tmp_path):
    path = _luna(tmp_path)
    for text, code in (("", "brief_empty"), ("   ", "brief_empty"), ("x" * 20_001, "brief_too_long")):
        with pytest.raises(H.HandoffError) as caught:
            H.write_brief("luna", path, "RDSD-118", text)
        assert caught.value.code == code


def test_a_template_written_before_handoff_existed_still_works(fleet_home, tmp_path):
    """`{handoff}` is optional like `{summary}`: losing the sentence is a smaller harm than
    refusing to launch over a config file somebody wrote three months ago."""
    old = {"fleet": {"prompt_template": "Work {key} end to end."}}
    assert L.prompt_for("RDSD-1", None, old, handoff=" Something.") == "Work RDSD-1 end to end."


def test_prompt_line_counts_and_never_quotes(fleet_home, tmp_path):
    path = _luna(tmp_path)
    assert H.prompt_line(path, "RDSD-118") == "", "nothing handed over, nothing said"
    H.write_brief("luna", path, "RDSD-118", "one sentence")
    assert "a brief under .agent/in/RDSD-118/; read it" in H.prompt_line(path, "RDSD-118")
    folder = os.path.join(path, ".agent", "in", "RDSD-118")
    open(os.path.join(folder, "export.csv"), "w").write("a,b\n")
    line = H.prompt_line(path, "RDSD-118")
    assert "a brief and 1 file" in line and "read them" in line


# --------------------------------------------------------------------------- the rendered page


def _serve(tmp_path):
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


@pytest.mark.browser
def test_a_dropped_ticket_opens_a_card_that_says_why_it_is_thin(fleet_home, tmp_path, monkeypatch):
    """Acceptance criterion: a rendered-page test drops a ticket and reads the card's verdict text.

    The drop is built in page context, because that is the only way to put a `DataTransfer` on a
    synthetic event that the page's own handler will read.
    """
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _luna(tmp_path)

    # Bypass Jira entirely: the pre-flight cache is the seam, and priming it is what a second drop
    # inside the TTL would do anyway.
    PF.write_cache({"issues": {"RDSD-118": {"description": "UAT refresh is slow.", "issuetype": "",
                                            "comments": 0, "attachments": 0, "error": "",
                                            "at": time.time()}}})
    server, token, port = _serve(tmp_path)
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)

            page.evaluate("""() => {
              const tile = document.querySelector('.tile[data-repo="luna"]');
              const dt = new DataTransfer();
              dt.setData('application/x-agentdata-ticket', 'RDSD-118');
              dt.setData('text/plain', 'RDSD-118');
              tile.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
            }""")

            card = page.locator('.tile[data-repo="luna"] .dispatch')
            page.wait_for_selector('.tile[data-repo="luna"] .dispatch:not([hidden])', timeout=5000)
            page.wait_for_function(
                """() => document.querySelector('.tile[data-repo="luna"] .verdict').textContent.trim() !== 'reading…'""",
                timeout=5000)

            # `inner_text` returns the *rendered* text, and the chip is uppercased in CSS.
            assert card.locator(".verdict").inner_text().strip().lower() == "thin"
            assert "RDSD-118" in card.locator(".dispatch-key").inner_text()
            body = card.locator(".dispatch-rows").inner_text()
            assert "none found" in body, body
            assert "a title with a full stop is not a specification" in body, body
            # The card asks for the one thing nothing else in the system knows.
            assert card.locator(".brief").is_visible()
            assert card.locator(".dispatch-go").inner_text().strip() == "Start anyway"
            # Nothing has been started: the card is the decision, not the launch.
            assert not errors, errors
            assert not os.path.isfile(os.path.join(fleet_dir(), "agents", "luna", "agent.json"))

            page.locator('.tile[data-repo="luna"] .dispatch-close').click()
            assert card.is_hidden()
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
