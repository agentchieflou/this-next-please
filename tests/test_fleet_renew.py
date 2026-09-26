"""Fresh sessions (#238): what every session began on, whether that is still installed, and renewing
the stale ones -- stale only, when idle, previewed first (#239, #240, #241).

The failure this exists for: 0.13.2 changed three skills, and every agent already running kept the
old text, because skills are read when a session begins. Nothing could say which agents those were.
"""
from __future__ import annotations
import json
import os
import threading
import time

import pytest

from agentdata.fleet import events as E, fingerprint as FP, registry, renew as RENEW, serve as S
from agentdata.fleet import supervisor
from agentdata.fleet.registry import Registry, agent_dir

from test_fleet import make_project
from test_fleet_ink import IDLE_LOOP

OLD = {"version": "0.13.1", "commit": "aaaaaaaaaaaa", "skills": "111111111111"}
NOW = {"version": "0.13.2", "commit": "bbbbbbbbbbbb", "skills": "222222222222"}


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    FP.forget()
    yield tmp_path / "fleet"
    FP.forget()


def started(install=..., *, resumed=False, session="", **extra):
    """A `started` event; `install=...` leaves the key out, as every start before #239 did."""
    data = {"pid": 1, "resumed": resumed, "new": not resumed, "session": session, **extra}
    if install is not ...:
        data["install"] = install
    return E.event("luna", "started", data, ticket="RDSD-1")


def turn_ended():
    return E.event("luna", "turn_ended", {"turn": "0"}, ticket="RDSD-1")


# ------------------------------------------------------------------------------- the fingerprint


def _skills(tmp_path, monkeypatch, **texts):
    d = tmp_path / "skills"
    for name, body in texts.items():
        (d / name).mkdir(parents=True, exist_ok=True)
        (d / name / "SKILL.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(FP, "_skills_dir", lambda: str(d))
    monkeypatch.setattr(FP, "_cli", lambda: ("0.13.2", "bbbbbbbbbbbb"))
    FP.forget()
    return d


def test_the_skills_hash_is_their_text_and_names_what_changed(fleet_home, tmp_path, monkeypatch):
    d = _skills(tmp_path, monkeypatch, router="route", **{"state-update": "use --question"})
    before = FP.current()
    assert before["version"] == "0.13.2" and len(before["skills"]) == 12

    # `ad-update` reinstalls every skill: every mtime moves, and no word does. Nothing is stale.
    for f in d.glob("*/SKILL.md"):
        os.utime(f, (f.stat().st_atime + 60, f.stat().st_mtime + 60))
    FP.forget()
    assert FP.current()["skills"] == before["skills"]

    (d / "state-update" / "SKILL.md").write_text("use ad-state ask", encoding="utf-8")
    FP.forget()
    after = FP.current()
    assert after["skills"] != before["skills"]
    assert FP.changed(before["skills"], after["skills"]) == ["state-update"]


# -------------------------------------------------------------------------------- the origin


def test_a_resumed_run_is_judged_by_the_session_it_resumed_not_by_its_own_start(fleet_home):
    stream = [started(OLD), E.event("luna", "session_id", {"session": "s1"}), turn_ended(),
              started(NOW, resumed=True, session="s1"), turn_ended()]
    assert FP.began_on(stream) == (OLD, "recorded")
    assert FP.staleness(stream, NOW)["stale"] is True


def test_the_origin_carried_forward_survives_the_stream_rolling_over(fleet_home):
    rolled = [started(NOW, resumed=True, session="s1", origin_install=OLD), turn_ended()]
    assert FP.began_on(rolled) == (OLD, "recorded")
    looked_and_found_none = [started(NOW, resumed=True, session="s1", origin_install=None)]
    assert FP.began_on(looked_and_found_none) == (None, "legacy")


def test_resuming_an_earlier_session_by_id_finds_that_sessions_own_start(fleet_home):
    stream = [started(OLD), E.event("luna", "session_id", {"session": "s1"}), turn_ended(),
              started(NOW), E.event("luna", "session_id", {"session": "s2"}), turn_ended(),
              started(NOW, resumed=True, session="s1")]
    assert FP.began_on(stream) == (OLD, "recorded")


def test_legacy_adopted_and_never_started(fleet_home):
    assert FP.staleness([started(...)], NOW)["stale"] is True, "a session before recording is older"
    assert "before the fleet recorded" in FP.staleness([started(...)], NOW)["reason"]
    adopted = [E.event("luna", "started", {"external": True, "adopted": True, "install": None})]
    verdict = FP.staleness(adopted, NOW)
    assert verdict["unknown"] is True and verdict["stale"] is False
    assert FP.staleness([], NOW) == {"stale": False, "unknown": False, "reason": "",
                                     "skills_changed": [], "began": None, "now": NOW}


def test_the_reason_names_the_version_and_the_skills(fleet_home):
    FP._remember(OLD["skills"], {"router": "r1", "state-update": "old"})
    FP._remember(NOW["skills"], {"router": "r1", "state-update": "new"})
    verdict = FP.staleness([started(OLD)], NOW)
    assert verdict["stale"] and verdict["skills_changed"] == ["state-update"]
    assert "started on 0.13.1 (aaaaaaa) · installed 0.13.2 (bbbbbbb)" in verdict["reason"]
    assert "skills changed: state-update" in verdict["reason"]
    assert FP.staleness([started(NOW)], NOW)["stale"] is False


def test_every_start_records_what_it_began_on(fleet_home, monkeypatch):
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    supervisor._emit_started("luna", {"pid": 3, "ticket": "RDSD-1"}, new=True)
    supervisor._emit_started("luna", {"pid": 4, "ticket": "RDSD-1", "session": "s1"}, resumed=True)
    first, second = [ev["data"] for ev in E.read("luna") if ev["kind"] == "started"]
    assert first["install"] == NOW and "origin_install" not in first
    assert second["install"] == NOW and second["origin_install"] == NOW


# ------------------------------------------------------------------------------- stale on the row


def _repo(tmp_path, name, *, phase="querying", ticket="RDSD-1", events=(), questions=None):
    path = make_project(tmp_path / name, phase=phase, ticket=ticket)
    if questions is not None:
        state_path = os.path.join(path, ".agent", "state.json")
        st = json.load(open(state_path, encoding="utf-8"))
        st["open_questions"] = questions
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(st, f)
    Registry().add(path, name=name)
    E.append(name, [dict(ev, repo=name) for ev in events])
    return path


def test_the_snapshot_marks_exactly_the_stale_sessions(fleet_home, tmp_path, monkeypatch):
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    _repo(tmp_path, "fresh", events=[started(NOW), turn_ended()])
    _repo(tmp_path, "old", events=[started(OLD), turn_ended()])
    _repo(tmp_path, "never")
    rows = {r["repo"]: r for r in S.fleet_snapshot()["repos"]}
    assert rows["fresh"]["stale"]["stale"] is False
    assert rows["old"]["stale"]["stale"] is True and "0.13.1" in rows["old"]["stale"]["reason"]
    assert rows["never"]["stale"]["stale"] is False
    assert rows["old"]["renew_queued"] is False


# ------------------------------------------------------------------------------------ renew


def _no_lock(monkeypatch, live=()):
    monkeypatch.setattr(supervisor, "live",
                        lambda name: {"pid": 9, "kind": "headless"} if name in live else {})


def test_every_verdict(fleet_home, tmp_path, monkeypatch):
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    _no_lock(monkeypatch, live=("running",))
    _repo(tmp_path, "idle", events=[started(OLD), turn_ended()])
    _repo(tmp_path, "running", events=[started(OLD)])
    _repo(tmp_path, "asking", phase="blocked", events=[started(OLD), turn_ended()],
          questions=[{"id": "q1", "q": "which workspace?"}])
    _repo(tmp_path, "consoled", events=[started(OLD, console=True), turn_ended()])
    _repo(tmp_path, "finished", phase="done", events=[started(OLD), turn_ended()])
    _repo(tmp_path, "untracked", ticket="", events=[started(OLD), turn_ended()])
    _repo(tmp_path, "current", events=[started(NOW), turn_ended()])
    _repo(tmp_path, "adopted", events=[E.event("adopted", "started",
                                               {"external": True, "adopted": True, "install": None})])
    got = {r["repo"]: (r["verdict"], r["why"]) for r in RENEW.plan()["rows"]}
    assert got["idle"][0] == "now"
    assert got["running"][0] == "at turn end"
    assert got["asking"] == ("skipped", got["asking"][1]) and got["asking"][1].startswith("needs you")
    assert got["consoled"][0] == "skipped" and "console" in got["consoled"][1]
    assert got["finished"][0] == "skipped" and got["finished"][1].startswith("done")
    assert got["untracked"][0] == "skipped" and "no ticket" in got["untracked"][1]
    assert got["current"] == ("skipped", "not stale")
    assert got["adopted"][0] == "skipped" and got["adopted"][1].startswith("adopted")
    assert "`ad-fleet fresh adopted`" in got["adopted"][1], "the skip names the verb that takes it (#488)"
    plan = RENEW.plan()
    assert (plan["now"], plan["at_turn_end"], plan["premium_turns"]) == (1, 1, 2)


def test_renew_starts_the_idle_ones_queues_the_running_ones_and_reports_a_refusal(
        fleet_home, tmp_path, monkeypatch):
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    _no_lock(monkeypatch, live=("running",))
    _repo(tmp_path, "idle", events=[started(OLD), turn_ended()])
    _repo(tmp_path, "broke", events=[started(OLD), turn_ended()])
    _repo(tmp_path, "running", events=[started(OLD)])
    calls = []

    def fake_start(name, **kw):
        calls.append((name, kw))
        if name == "broke":
            raise supervisor.SupervisorError("over budget", "raise fleet.budget_per_agent",
                                             code="over_budget")
        return {"pid": 42}

    monkeypatch.setattr(supervisor, "start", fake_start)
    out = {r["repo"]: r for r in RENEW.run(cfg={})["rows"]}
    assert out["idle"]["done"] == "started" and out["idle"]["pid"] == 42
    assert out["broke"]["done"] == "refused" and out["broke"]["error"] == "over budget"
    assert out["running"]["done"] == "queued"
    assert os.path.exists(os.path.join(agent_dir("running"), RENEW.RENEW_FILE))
    idle_call = dict(calls)["idle"]
    assert idle_call["new"] is True and idle_call["key"] == "RDSD-1"
    assert "fresh session" in idle_call["prompt"] and "0.13.1" in idle_call["prompt"]


def test_a_queued_renew_fires_once_when_the_turn_ends_and_never_over_a_question(
        fleet_home, tmp_path, monkeypatch):
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    live = {"a", "b"}
    monkeypatch.setattr(supervisor, "live",
                        lambda name: {"pid": 9, "kind": "headless"} if name in live else {})
    _repo(tmp_path, "a", events=[started(OLD)])
    _repo(tmp_path, "b", events=[started(OLD)])
    started_now = []
    monkeypatch.setattr(supervisor, "start",
                        lambda name, **kw: started_now.append(name) or {"pid": 1})
    RENEW.run(cfg={})
    assert RENEW.carry_out(cfg={}) == [], "still mid-turn: nothing happens"

    # a's turn ends quietly; b's turn ends on a question.
    live.clear()
    E.append("a", [dict(turn_ended(), repo="a")])
    state_b = os.path.join(Registry().get("b").path, ".agent", "state.json")
    st = json.load(open(state_b, encoding="utf-8"))
    st.update(phase="blocked", open_questions=[{"id": "q1", "q": "which workspace?"}])
    with open(state_b, "w", encoding="utf-8") as f:
        json.dump(st, f)
    E.append("b", [dict(turn_ended(), repo="b")])

    done = {r["repo"]: r["done"] for r in RENEW.carry_out(cfg={})}
    assert done == {"a": "started", "b": "cancelled"}
    assert started_now == ["a"]
    assert RENEW.carry_out(cfg={}) == [], "once, and the queue is gone"


def test_the_desk_carries_out_renews_with_polling_off_and_once_per_interval(fleet_home, monkeypatch):
    """A queued renew is the fleet's own work: a desk with project polling off must still do it, and
    four open windows must not do it four times."""
    calls = []
    monkeypatch.setattr(RENEW, "carry_out", lambda **kw: calls.append(kw) or [])
    S.stream_events({}, threading.Event(), lambda _: None, once=True, polls=False)
    assert len(calls) == 1
    t0 = time.time() + 100
    assert S.renew_tick(now=t0) == [] and len(calls) == 2
    assert S.renew_tick(now=t0 + 0.5) == [] and len(calls) == 2, "inside the interval: nothing"
    S.renew_tick(now=t0 + S.RENEW_EVERY_S)
    assert len(calls) == 3


def test_the_cli_previews_and_the_status_table_has_the_column(fleet_home, tmp_path, monkeypatch, capsys):
    from agentdata import cli_fleet

    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    _no_lock(monkeypatch)
    _repo(tmp_path, "old", events=[started(OLD), turn_ended()])
    monkeypatch.setattr(supervisor, "start", lambda *a, **k: pytest.fail("a dry run starts nothing"))
    assert cli_fleet.main(["renew", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry_run: true" in out and "old,now," in out.replace(" ", "")
    assert cli_fleet.main(["renew", "nope"]) != 0
    assert "no registered repository named nope" in capsys.readouterr().out
    assert "stale" in cli_fleet.COLUMNS


# ------------------------------------------------------------------------------- the rendered page


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


@pytest.mark.browser
def test_the_desk_says_which_sessions_are_stale_and_previews_before_it_renews(
        fleet_home, tmp_path, monkeypatch):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from test_fleet_desk_browser import launch_chromium

    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    _repo(tmp_path, "fresh", events=[started(NOW), turn_ended()])
    _repo(tmp_path, "old", events=[started(OLD), turn_ended()])
    # #511: the morning. One pane on yesterday's session, one on yesterday's with a Send made this
    # morning, one waiting on a question, and one with no ticket.
    yday = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 86400))
    last_night = [dict(started(NOW), ts=yday), dict(turn_ended(), ts=yday)]
    _repo(tmp_path, "yday", events=last_night)
    _repo(tmp_path, "sent", events=last_night + [started(NOW, resumed=True, session="s-sent"), turn_ended()])
    _repo(tmp_path, "asking", events=last_night, questions=[{"id": "q1", "q": "which workspace?"}])
    _repo(tmp_path, "free", phase="idle", ticket="", events=last_night)
    # #512: the sweep's adapters, recorded in process; `yday` has a page source, so its page row asks.
    from agentdata.fleet import wrapup as WRAP
    sweep_run = SweepRun()
    monkeypatch.setattr(WRAP, "RUN", sweep_run)
    os.makedirs(os.path.join(str(tmp_path / "yday"), ".agent", "out"), exist_ok=True)
    open(os.path.join(str(tmp_path / "yday"), ".agent", "out", "RDSD-1-confluence.md"), "w").close()
    posted = []
    real_act = S.act
    monkeypatch.setattr(S, "act", lambda what, body: posted.append((what, dict(body))) or real_act(what, body))
    monkeypatch.setattr(supervisor, "start", lambda *a, **k: pytest.fail("the preview starts nothing"))

    # The stale agent is the one open: the column shows one tile, and its chip is what is asked.
    S.update_window("main", open="old")
    server, token, port = _serve()
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector('.tile[data-repo="old"] .oldsession:not([hidden])', timeout=15000)
            # The chip's own attribute, not its visibility: the fresh agent's tile is behind the
            # open one in the column, so "not visible" would pass for the wrong reason.
            assert page.get_attribute('.tile[data-repo="fresh"] .oldsession', "hidden") is not None
            assert "0.13.1" in page.get_attribute('.tile[data-repo="old"] .oldsession', "title")
            assert "1 session began" in page.inner_text("#renew-strip .renew-sum")
            # #489: the stale pane's own door, on its head: what it starts, on which model. Only
            # presence and title here -- this test fails any start.
            fresh = '.tile[data-repo="old"] .freshtoggle'
            page.wait_for_selector(fresh + ":not([hidden])", timeout=10000)
            title = page.get_attribute(fresh, "title")
            assert "on RDSD-1" in title and "cli-auto" in title and "Alt+N" in title, title
            # #509: the button is drawn on every pane with a verdict, and offered (`is-offer`) only
            # where #489 offers it; off a compact pane, one that is not offered is not shown.
            assert page.evaluate("""() => { const b = document.querySelector('.tile[data-repo="fresh"] .freshtoggle');
                return !b.classList.contains('is-offer') && (b.closest('.tile').dataset.tier === 'compact'
                       || getComputedStyle(b).display === 'none'); }""")
            assert "start fresh (Alt+N)" in page.get_attribute('.tile[data-repo="old"] .oldsession', "title")

            page.click("#renew")
            page.wait_for_selector('#renew-strip .renew-row[data-rowkey="old"]', timeout=5000)
            assert "now" in page.inner_text('#renew-strip .renew-row[data-rowkey="old"] .renew-verdict')
            assert page.inner_text("#renewgo") == "renew 1"
            assert [w for w, b in posted if w == "renew"] == ["renew"]
            assert all(b.get("dry_run") for w, b in posted if w == "renew"), "only the preview was asked for"

            page.click("#renewcancel")
            page.wait_for_selector("#renew-strip .renew-rows", state="hidden", timeout=5000)

            # #511: a fresh day from the desk. The line counts the two idle panes with a ticket on
            # sessions that began before today -- the Send this morning does not make `sent` today's.
            page.wait_for_function("""() => !document.getElementById('day-strip').hidden
                && /^2 panes are on sessions that began before today/.test(
                     document.querySelector('#day-strip .day-offer-words').textContent)""", timeout=10000)
            page.keyboard.press("Shift+N")
            page.wait_for_function("""() => document.querySelectorAll('#day-strip .day-rows li:not(.day-pattern)').length === 6
                && !document.getElementById('daygo').disabled""", timeout=10000)
            day = {r["repo"]: r for r in page.evaluate(DAY_ROWS)}
            assert (day["yday"]["ticked"], day["sent"]["ticked"]) == (True, True), day
            assert (day["free"]["ticked"], day["free"]["disabled"], day["free"]["verdict"]) == (False, False, "keyless")
            assert (day["asking"]["disabled"], day["asking"]["verdict"]) == (True, "needs_you")
            assert day["asking"]["question"] == "“which workspace?”" and day["asking"]["answer"], day["asking"]
            assert day["asking"]["why"].startswith("answer it first")
            assert day["yday"]["model"] == "auto · cli-auto" and "no --model flag" in day["yday"]["model_title"]
            assert day["yday"]["began"].startswith("began yesterday"), day["yday"]
            assert page.is_visible("#day-strip .day-keyless")
            assert page.inner_text("#daygo") == "start 4 fresh — about 4 premium turns", "yday, sent, fresh, old"
            assert [b for w, b in posted if w == "fresh"] == [{"all": True, "dry_run": True}], posted
            # An idle desk with the strip open writes nothing.
            count = page.evaluate(IDLE_LOOP)
            assert count["n"] == 0, f"an idle desk wrote to the page: {count}"
            page.click("#daycancel")
            page.wait_for_selector("#day-strip .day-rows", state="hidden", timeout=5000)
            # The *day* menu's item opens the same preview, and Esc closes the strip.
            page.click("#daybtn")
            page.wait_for_selector("#daymenu:not([hidden])", timeout=5000)
            assert page.get_attribute("#daybtn", "aria-expanded") == "true"
            page.click("#dayfresh")
            page.wait_for_selector("#day-strip .day-rows:not([hidden])", timeout=5000)
            page.wait_for_function("() => !document.getElementById('daygo').disabled", timeout=10000)
            assert page.is_hidden("#daymenu")
            page.keyboard.press("Escape")
            page.wait_for_selector("#day-strip .day-rows", state="hidden", timeout=5000)
            assert [b for w, b in posted if w == "fresh"] == [{"all": True, "dry_run": True}] * 2, posted

            # `?fresh=1` only previews, from `/open` and from the tokened address, and comes off the
            # address. No parameter makes the page post `repos`.
            for url in (f"http://127.0.0.1:{port}/open?fresh=1",
                        f"http://127.0.0.1:{port}/?t={token}&fresh=1&repos=yday&all=1&confirm=1"):
                before = len(posted)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_function("""() => document.querySelectorAll('#day-strip .day-rows li:not(.day-pattern)').length === 6
                    && !document.getElementById('daygo').disabled""", timeout=15000)
                assert "fresh=1" not in page.url and "t=" in page.url, page.url
                assert [b for w, b in posted[before:] if w == "fresh"] == [{"all": True, "dry_run": True}]
            assert not [b for w, b in posted if "repos" in b], "no address confirms a fresh day"

            # #512: the end-of-day sweep from the *day* menu. #503's `RUN` is recorded; nothing starts.
            before = len(posted)
            page.click("#daybtn")
            page.wait_for_selector("#daymenu:not([hidden])", timeout=5000)
            page.click("#daywrapday")
            page.wait_for_function("""() => document.querySelectorAll('#day-strip .day-rows li.sweep-row:not(.day-pattern)').length === 6
                && !document.getElementById('daygo').disabled""", timeout=20000)
            swept = {r["repo"]: r for r in page.evaluate(SWEEP_ROWS)}
            job = WRAP.fleet_job_state()
            planned = {r["repo"]: [s["id"] for s in r["steps"] if s["ticked"]] for r in job["repos"]}
            assert {k: [c["id"] for c in r["cells"] if c["ticked"]] for k, r in swept.items()} == planned, swept
            assert [c["step"] for c in swept["yday"]["cells"]] == ["push", "pr", "page", "comment"], swept["yday"]
            assert [c["step"] for c in swept["free"]["cells"]] == ["push", "pr"], swept["free"]
            for repo, row in swept.items():
                pr = next(c for c in row["cells"] if c["step"] == "pr")
                assert "not_pinned" in pr["text"] and "capture-help" in pr["text"] and pr["disabled"], (repo, pr)
            page_cell = next(c for c in swept["yday"]["cells"] if c["step"] == "page")
            assert "not_pinned" in page_cell["text"], page_cell
            ticked = sum(len(v) for v in planned.values())
            assert page.inner_text("#daygo") == (f"write {ticked} — 6 pushes, 0 PRs, 0 pages, 5 comments, "
                                                 "0 transitions"), page.inner_text("#daygo")
            assert not any("merge" in c["text"].lower() for r in swept.values() for c in r["cells"])
            # An idle desk with the table open, and no job running, writes nothing.
            assert WRAP.wait_all(10)
            swept_idle = page.evaluate(IDLE_LOOP)
            assert swept_idle["n"] == 0, f"an idle desk with the sweep open wrote to the page: {swept_idle}"
            page.click("#daygo")
            page.wait_for_function("""() => [...document.querySelectorAll('#day-strip .sweep-row:not(.day-pattern) .wrap-row')]
                .filter(c => c.querySelector('.wrap-tick').checked).every(c => c.dataset.done)""", timeout=20000)
            wraps = [b for w, b in posted[before:] if w == "wrapup"]
            assert [b.get("dry_run") for b in wraps] == [True, None], wraps
            assert wraps[0] == {"all": True, "mode": "day", "dry_run": True}, wraps[0]
            assert wraps[1]["all"] is True and wraps[1]["job"] == job["job"] and wraps[1]["mode"] == "day"
            assert wraps[1]["steps"] == {k: v for k, v in planned.items() if v}, wraps[1]
            done = {r["repo"]: [c["done"] for c in r["cells"] if c["ticked"]] for r in page.evaluate(SWEEP_ROWS)}
            assert all(d == ["written"] * len(planned[k]) for k, d in done.items()), done
            assert len(sweep_run.writes) == ticked
            assert f"sweep: {ticked} written" in page.inner_text("#notice")
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


class SweepRun:
    """#503's `RUN` for #512, in process: a push of one commit, the pr and page verbs unknown (argparse's
    *invalid choice*, as on `main` before #506 and #507), a comment and a transition that answer `ok`."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls: list = []

    @property
    def writes(self):
        return [a for a, _ in self.calls if "--dry-run" not in a]

    def __call__(self, argv, cwd, env=None):
        args = list(argv[3:])
        with self.lock:
            self.calls.append((args, cwd))
        dry = "--dry-run" in args
        if args[0] in ("pncli", "confluence"):
            return {"code": 2, "meta": {}, "tables": {}, "stderr": f"ad-{args[0]}: error: argument: invalid choice"}
        if args[0] == "git":
            meta = {"ok": True, "branch": "feature/x", "remote": "origin", "target": "refs/heads/feature/x", "ahead": 1}
            return {"code": 0, "meta": meta if dry else {**meta, "pushed": True}, "tables": {}, "stderr": ""}
        if args[1] == "comment":
            meta = {"ok": True, "key": args[2], "chars": 40, "first_line": "End of day"}
            return {"code": 0, "meta": meta if dry else {**meta, "comment_id": "1"}, "tables": {}, "stderr": ""}
        return {"code": 0, "meta": {"ok": True, "key": args[2], "status": "In Progress", "already": True},
                "tables": {}, "stderr": ""}


#: #512: the sweep's rows, each with its cells as #510's cell function draws them.
SWEEP_ROWS = """() => [...document.querySelectorAll('#day-strip .day-rows li.sweep-row:not(.day-pattern)')].map(li => ({
  repo: li.dataset.rowkey, state: li.querySelector('.sweep-state').textContent,
  cells: [...li.querySelectorAll('.sweep-cells > .wrap-row')].map(c => ({
    id: c.dataset.id, step: c.dataset.step, done: c.dataset.done, text: c.textContent,
    ticked: c.querySelector('.wrap-tick').checked, disabled: c.querySelector('.wrap-tick').disabled })) }))"""


def test_the_day_menu_holds_the_sweeps_and_only_the_strip_posts_one():
    """#512: the *day* menu holds three items; the sweep's cells are #510's (`li.wrap-pattern` drawn by
    `wrapCell`); and app.js posts `wrapup` with `all` only from the strip's preview and its confirm."""
    import re

    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "agentdata", "fleet", "static")
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    html = open(os.path.join(static, "index.html"), encoding="utf-8").read()
    menu = html[html.index('<div id="daymenu"'):]
    menu = menu[:menu.index("</div>")]
    items = re.findall(r'<button type="button" role="menuitem" id="(\w+)"', menu)
    assert items == ["dayfresh", "daywrapday", "daywrapproject"], items
    assert "end of day…" in menu and "end of project…" in menu
    strip = html[html.index('<div id="day-strip"'):]
    assert '<li class="day-pattern sweep-row"' in strip[:strip.index("</ul>")]
    sweep = js[js.index("function drawSweepRow("):js.index("function countSweep(")]
    assert 'querySelector("#inspector .wrap-pattern")' in sweep and "wrapCell(" in sweep
    sites = [m.start() for m in re.finditer(r'post\("wrapup", \{ all: true', js)]
    assert len(sites) == 2, sites
    heads = [(m.start(), m.group(1)) for m in re.finditer(r"^function (\w+)\(", js, re.M)]
    owners = sorted(next(name for at, name in reversed(heads) if at < site) for site in sites)
    assert owners == ["previewSweep", "writeSweep"], owners
    assert "all: true" not in js[js.index("function previewWrap("):js.index("function loadWrap(")]
    assert "merge" not in sweep.lower()


#: #511: the fresh day's rows as the strip draws them.
DAY_ROWS = """() => [...document.querySelectorAll('#day-strip .day-rows li:not(.day-pattern)')].map(li => ({
  repo: li.dataset.rowkey, ticked: li.querySelector('.day-tick').checked,
  disabled: li.querySelector('.day-tick').disabled, verdict: li.querySelector('.day-verdict').textContent,
  why: li.querySelector('.day-why').textContent, question: li.querySelector('.day-question').textContent,
  answer: !li.querySelector('.day-answer').hidden, model: li.querySelector('.day-model').textContent,
  model_title: li.querySelector('.day-model').title, began: li.querySelector('.day-began').textContent }))"""


def test_only_the_confirm_posts_the_repos_of_a_fresh_day():
    """#511, DAY-D4: `#daygo` posts `fresh` with `all` and the ticked `repos`; nothing else on the page
    posts `repos`, so no address, key or load can confirm a launch. `?fresh=1` asks for the preview."""
    import re

    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "agentdata", "fleet", "static")
    js = open(os.path.join(static, "app.js"), encoding="utf-8").read()
    posts = re.findall(r'post\("fresh", ([^)]*)\)', js)
    assert sorted(posts) == sorted(['{ all: true, dry_run: true }', '{ all: true, repos: repos }',
                                    'closed ? { repo: repo, closed: true } : { repo: repo }']), posts
    run = js[js.index("function runDay()"):js.index("function previewFromAddress()")]
    assert 'post("fresh", { all: true, repos: repos })' in run
    assert js.count("repos: repos") == 1
    assert 'dayGo().addEventListener("click", runDay)' in js and js.count("runDay(") == 1
    address = js[js.index("function previewFromAddress()"):js.index("(function bindDay()")]
    assert "openDay()" in address and "runDay" not in address and "repos" not in address


# --------------------------------------------------------------------------- a current desk (#242)


def test_the_desk_knows_whether_it_is_the_installed_code(fleet_home, monkeypatch):
    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    monkeypatch.setattr(S, "LOADED", None)
    assert S.desk_currency()["current"] is True, "not a server: nothing to be out of date"
    monkeypatch.setattr(S, "LOADED", dict(NOW))
    assert S.desk_currency() == {"loaded": NOW, "installed": NOW, "current": True, "reason": ""}
    monkeypatch.setattr(S, "LOADED", dict(OLD))
    got = S.desk_currency()
    assert got["current"] is False
    assert got["reason"].startswith("the desk is running 0.13.1 (aaaaaaa) · installed 0.13.2 (bbbbbbb)")
    # Skills are the agents' concern, not the desk's: a skills-only change is still a current desk.
    monkeypatch.setattr(S, "LOADED", dict(NOW, skills="999999999999"))
    assert S.desk_currency()["current"] is True


def test_a_launcher_reads_the_desks_own_answer(fleet_home):
    from agentdata.fleet import opener as O

    assert O.out_of_date({}) is False, "nothing answered: nothing to replace"
    assert O.out_of_date({"service": "ad-fleet", "loaded": "0.13.2", "current": True}) is False
    assert O.out_of_date({"service": "ad-fleet", "loaded": "0.13.1", "current": False}) is True
    assert O.out_of_date({"service": "ad-fleet", "version": "0.13.2"}) is True, \
        "a desk from before #242 cannot say what it loaded, and is older by definition"


def test_open_replaces_an_old_desk_and_keeps_a_current_one(fleet_home, monkeypatch):
    from agentdata.fleet import opener as O

    record = {"port": 8765, "token": "t", "pid": 0, "url": "http://127.0.0.1:8765/?t=t"}
    fresh = dict(record, token="t2")
    stopped, started_on = [], []
    monkeypatch.setattr(O, "running", lambda: dict(record))
    monkeypatch.setattr(O, "stop_server", lambda r, timeout=10.0: stopped.append(r["port"]) or True)
    monkeypatch.setattr(O, "start_server", lambda port=8765: started_on.append(port) or dict(fresh))

    monkeypatch.setattr(O, "ping_info", lambda port, timeout=2.0: {"service": "ad-fleet", "loaded": "0.13.2",
                                                                    "current": True})
    assert O.current_desk() == (record, "already up") and not stopped

    monkeypatch.setattr(O, "ping_info", lambda port, timeout=2.0: {"service": "ad-fleet", "loaded": "0.13.1",
                                                                    "current": False})
    assert O.current_desk() == (fresh, "replaced (was 0.13.1)")
    assert stopped == [8765] and started_on == [8765]


def test_a_desk_stops_when_asked_by_its_own_token_and_says_so_on_ping(fleet_home, monkeypatch):
    import urllib.request
    from agentdata.fleet import opener as O

    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    server, token = S.build(0)
    monkeypatch.setattr(S, "LOADED", dict(OLD))
    port = server.server_address[1]
    S.record(server, token)
    thread = threading.Thread(target=S.run, args=(server,), daemon=True)
    thread.start()
    try:
        info = O.ping_info(port)
        assert info["loaded"] == "0.13.1" and info["current"] is False
        assert O.stop_server({"port": port, "token": token, "pid": 0}, timeout=5.0) is True
        thread.join(timeout=5)
        assert not thread.is_alive() and O.ping_info(port) == {}
        assert O.serve_record() == {}, "a stopped desk forgets serve.json"
    finally:
        if thread.is_alive():
            server.shutdown()
    with pytest.raises(Exception):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1)


def test_both_shells_treat_an_out_of_date_desk_as_missing():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ts = open(os.path.join(root, "ide", "vscode", "src", "fleet.ts"), encoding="utf-8").read()
    kt = open(os.path.join(root, "ide", "jetbrains", "src", "main", "kotlin", "com", "agentdata", "fleet",
                           "Fleet.kt"), encoding="utf-8").read()
    assert "answer.current === false" in ts and "answer.loaded === undefined" in ts
    assert 'json.has("loaded")' in kt and "answer.current" in kt


@pytest.mark.browser
def test_the_page_says_when_the_desk_itself_is_out_of_date(fleet_home, tmp_path, monkeypatch):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    from test_fleet_desk_browser import launch_chromium

    monkeypatch.setattr(FP, "current", lambda: dict(NOW))
    _repo(tmp_path, "fresh", events=[started(NOW), turn_ended()])
    server, token, port = _serve()
    monkeypatch.setattr(S, "LOADED", dict(OLD))
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
            page.wait_for_selector("#renew-strip .renew-desk:not([hidden])", timeout=15000)
            assert "the desk is running 0.13.1" in page.inner_text("#renew-strip .renew-desk")
            assert page.locator("#renew").is_hidden(), "no stale session: nothing to preview"
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
