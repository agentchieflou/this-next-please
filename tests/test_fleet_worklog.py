"""The fleet's worklog (W-1 and W-2 of docs/plan-onenote-worklog.md): one page per checkout per day, folded from
the event stream, laid out like the fleet map, mirrored under the fleet directory, and previewed by the wrap-up.

Every stream here is built from `events.event` so the shapes are the contract's (docs/fleet-events.md), and the
fold is tested as the pure function it is before anything touches a registry.
"""
from __future__ import annotations

import os

import pytest

from agentdata import cli_fleet
from agentdata import config as C, textio
from agentdata.fleet import events as E, registry, worklog as WL, wrapup as WRAP
from agentdata.fleet.registry import Registry

from test_fleet import make_project

DAY = "2026-09-15"      # a fixed past day: `events.refresh` folds state.json into a phase event stamped *now*


def _set_notebook(url: str) -> None:
    cfg = C.load()
    cfg.setdefault("fleet", {}).setdefault("onenote", {})["notebook"] = url
    C.save(cfg)


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.delenv(registry.AGENT_ENV, raising=False)
    return tmp_path / "fleet"


def _ev(kind, data=None, *, at="09:00:00", day=DAY, ticket="RDSD-7", seq=0):
    return E.event("luna", kind, data or {}, ticket=ticket, seq=seq, ts=f"{day}T{at}")


def a_day() -> list[dict]:
    """A ticketed morning: a phase, a model, a question, an artifact, an approval, a denial, a cost, a turn."""
    evs = [
        _ev("started", {"summary": "do it"}, at="09:00:00"),
        _ev("phase_changed", {"from": "triaged", "to": "building"}, at="09:01:00"),
        _ev("assistant_text", {"text": "hi", "model": "claude-haiku-4.5"}, at="09:02:00"),
        _ev("question_opened", {"id": "q1", "question": "Cover UAT <too>?"}, at="09:03:00"),
        _ev("artifact", {"artifact": {"path": ".agent/out/x.md", "what": "unused measures"}}, at="09:04:00"),
        _ev("needs_approval", {"id": "a1", "kind": "git-push", "summary": "push 3"}, at="09:05:00"),
        _ev("approval_resolved", {"id": "a1", "kind": "git-push", "decision": "approved", "by": "operator"},
            at="09:06:00"),
        _ev("denied", {"id": "t2", "message": "no"}, at="09:07:00"),
        _ev("cost", {"premium_requests": 1.5}, at="09:08:00"),
        _ev("turn_ended", {}, at="09:09:00"),
        _ev("exited", {"exit_code": 0}, at="09:10:00"),
    ]
    for i, ev in enumerate(evs, 1):
        ev["seq"] = i
    return evs


# ------------------------------------------------------------------------------------------ names and layout


def test_a_name_graph_refuses_is_rewritten_the_same_way_every_time():
    assert WL.onenote_name("luna") == "luna"
    assert WL.onenote_name("a/b:c?d*e") == "a-b-c-d-e"
    for ch in WL.FORBIDDEN:
        assert ch not in WL.onenote_name(f"x{ch}y")
    long = "p" * 80
    cut = WL.onenote_name(long)
    assert len(cut) == WL.MAX_NAME and cut == WL.onenote_name(long), "stable, and exactly at the cap"
    assert cut[:43] == "p" * 43 and cut[43] == "-"
    assert WL.onenote_name("p" * 80) != WL.onenote_name("p" * 79 + "q"), "two long names never collide"


def test_the_layout_is_the_fleet_map_with_time_at_the_leaves_and_one_path_string():
    lay = WL.layout("luna", "luna-velocity", DAY)
    assert lay["path"] == "luna/luna-velocity/2026-09/2026-09-15"
    assert lay["groups"] == ["luna", "luna-velocity"] and lay["section"] == "2026-09"
    assert lay["title"] == "2026-09-15 · luna-velocity" and lay["journal_title"] == "2026-09-15 · luna"
    assert lay["journal_section"] == "Journal 2026-09"
    flat = WL.layout("luna", "luna-velocity", DAY, nested=False)
    assert flat["path"] == lay["path"], "the connector's flat layout keeps the same address string"
    assert flat["groups"] == [] and flat["section"] == "luna · 2026-09" and flat["journal_section"] == flat["section"]
    with pytest.raises(WL.WorklogError) as e:
        WL.layout("luna", "luna", "10/10/2026")
    assert e.value.code == "bad_day"


def test_the_local_mirror_path_is_the_same_tree_under_the_fleet_directory(fleet_home):
    path = WL.local_path("luna", "luna-velocity", DAY)
    assert path.endswith("/fleet/worklog/luna/luna-velocity/2026-09/2026-09-15.md"), path


# ------------------------------------------------------------------------------------------ the fold


def test_the_fold_keeps_the_facts_of_one_day_and_nothing_the_model_said():
    evs = a_day() + [_ev("phase_changed", {"from": "a", "to": "b"}, day="2026-09-09", seq=99),
                     _ev("tool_call", {"tool": "powershell", "arguments": {"command": "rm -rf"}}, seq=12),
                     _ev("tool_result", {"id": "t1", "ok": True}, seq=13)]
    m = WL.fold(evs, repo="luna", project="luna", day=DAY)
    assert m["seq_from"] == 1 and m["seq_to"] == 13 and m["events"] == 13 and not m["empty"]
    assert m["model"] == "claude-haiku-4.5" and m["turns"] == 1 and m["premium"] == 1.5 and m["denied"] == 1
    assert list(m["tickets"]) == ["RDSD-7"]
    t = m["tickets"]["RDSD-7"]
    assert t["phases"] == [{"at": "09:01", "from": "triaged", "to": "building"}], "the other day's phase is not here"
    assert t["artifacts"][0]["path"] == ".agent/out/x.md" and t["questions"]["q1"]["status"] == "open"
    assert t["approvals"][0]["decision"] == "approved" and t["approvals"][0]["by"] == "operator"
    assert m["state"] == "needs_human" and m["role"] == "human"
    text = WL.render_md(m) + WL.render_html(m)
    assert "rm -rf" not in text and "powershell" not in text and '"text"' not in text


def test_an_answered_question_closes_its_tag_and_a_second_wrapup_appends_from_the_cursor():
    evs = a_day() + [_ev("question_answered", {"id": "q1", "question": "Cover UAT <too>?", "answer": "yes"},
                         at="10:00:00", seq=12)]
    whole = WL.fold(evs, repo="luna", project="luna", day=DAY)
    assert whole["tickets"]["RDSD-7"]["questions"]["q1"] == {
        "id": "q1", "text": "Cover UAT <too>?", "status": "answered", "answer": "yes", "at": "09:03"}
    assert "- [x] asked: Cover UAT <too>? — answered: yes" in WL.render_md(whole)
    later = WL.fold(evs, repo="luna", project="luna", day=DAY, since=11)
    assert later["seq_from"] == later["seq_to"] == 12 and later["events"] == 1
    assert later["tickets"]["RDSD-7"]["questions"]["q1"]["status"] == "answered"
    assert not later["tickets"]["RDSD-7"]["phases"], "an append carries only what came after the cursor"


def test_an_empty_day_is_said_to_be_empty():
    m = WL.fold(a_day(), repo="luna", project="luna", day="2026-09-16")
    assert m["empty"] and m["events"] == 0 and m["tickets"] == {} and m["state"] == ""
    assert "nothing happened on this day" in WL.render_md(m)


# ------------------------------------------------------------------------------------------ the emitters


def test_the_html_is_onenote_input_with_data_ids_note_tags_and_escaping():
    evs = a_day() + [_ev("friction", {"skill": "jira-triage", "unblock": "A decision & a date", "severity": "blocker"},
                         at="11:00:00", seq=12)]
    html = WL.render_html(WL.fold(evs, repo="luna", project="luna", day=DAY))
    assert html.startswith("<!DOCTYPE html>") and "<title>2026-09-15 · luna</title>" in html
    assert f'<div data-id="{WL.ROOT_ID}">' in html and '<div data-id="wl-RDSD-7">' in html
    assert '<p data-tag="to-do">asks: Cover UAT &lt;too&gt;?</p>' in html
    assert '<p data-tag="important">11:00 friction (blocker) jira-triage: A decision &amp; a date</p>' in html
    assert '<p data-tag="important">ended blocked</p>' in html, "a blocker outranks the open question (agentstate)"
    assert "<too>" not in html and "data-tag=\"custom" not in html
    assert html.count("<div") == html.count("</div>")


def test_the_markdown_and_the_html_say_the_same_things():
    m = WL.fold(a_day(), repo="luna", project="luna", day=DAY)
    md, html = WL.render_md(m), WL.render_html(m)
    for line in ("09:04 made .agent/out/x.md — unused measures", "09:05 git-push: push 3 — approved by operator",
                 "1 tool call denied", "luna · claude-haiku-4.5 · 1 turn · 1.5 premium requests · seq 1–11"):
        assert line in md and line in html.replace("&amp;", "&"), line
    assert md.startswith("# 2026-09-15 · luna\n\n_luna/luna/2026-09/2026-09-15_\n")


# ------------------------------------------------------------------------------------------ the agent and the CLI


@pytest.fixture()
def luna(fleet_home, tmp_path, monkeypatch):
    monkeypatch.setattr(WL, "today", lambda: DAY)             # the wrap-up previews "today": pin it to the fixture's day
    path = make_project(tmp_path / "luna", phase="building", ticket="RDSD-7")
    repo = Registry().add(path, name="luna")
    E.refresh("luna", path, repo_state=repo.state())        # state.json's own phase event lands first, dated today
    E.append("luna", a_day())
    return path


def test_build_folds_the_registered_agents_stream_and_write_local_mirrors_it(luna, fleet_home):
    m = WL.build("luna", day=DAY)
    assert m["project"] == "luna" and m["layout"]["path"] == "luna/luna/2026-09/2026-09-15"
    assert m["events"] >= 11 and m["tickets"]["RDSD-7"]["artifacts"], "the stream was read"
    assert m["notebook"] == "" and m["local"] == WL.local_path("luna", "luna", DAY)
    path = WL.write_local(m)
    assert os.path.isfile(path) and os.path.isfile(path[:-3] + ".html")
    assert open(path, encoding="utf-8").read() == WL.render_md(m)
    assert textio.norm_path(str(fleet_home)) in path and "worklog" in path
    assert WL.write_local(m) == path and open(path, encoding="utf-8").read() == WL.render_md(m), "idempotent"


def test_a_worktree_files_under_its_project(fleet_home, tmp_path):
    main = make_project(tmp_path / "luna", phase="idle")
    Registry().add(main, name="luna")
    wt = make_project(tmp_path / "luna-velocity", phase="building", ticket="RDSD-9")
    Registry().add(wt, name="luna-velocity", project="luna")
    E.append("luna-velocity", [E.event("luna-velocity", "phase_changed", {"from": "", "to": "building"},
                                       ticket="RDSD-9", seq=1, ts=f"{DAY}T09:00:00")])
    m = WL.build("luna-velocity", day=DAY)
    assert m["layout"]["path"] == "luna/luna-velocity/2026-09/2026-09-15"
    assert m["layout"]["groups"] == ["luna", "luna-velocity"]
    assert WL.local_path("luna", "luna-velocity", DAY) == m["local"]


def test_the_cli_prints_toon_and_writes_only_when_asked(luna, fleet_home, capsys):
    assert cli_fleet.main(["worklog", "luna", "--date", DAY]) == 0
    out = capsys.readouterr().out
    assert "source: ad-fleet worklog" in out and "path: luna/luna/2026-09/2026-09-15" in out
    assert "tickets[1]{ticket,phases,phase,artifacts,prs,asks,answered,approvals,friction,denied}:" in out
    assert "RDSD-7,1,building,1,0,1,0,1,0,1" in out, out
    assert not os.path.isfile(WL.local_path("luna", "luna", DAY)), "TOON alone writes nothing"
    assert cli_fleet.main(["worklog", "luna", "--date", DAY, "--write"]) == 0
    out = capsys.readouterr().out
    assert "local:" in out and os.path.isfile(WL.local_path("luna", "luna", DAY))
    assert cli_fleet.main(["worklog", "luna", "--date", DAY, "--markdown"]) == 0
    assert capsys.readouterr().out.startswith("# 2026-09-15 · luna")
    assert cli_fleet.main(["worklog", "luna", "--date", DAY, "--html"]) == 0
    assert capsys.readouterr().out.startswith("<!DOCTYPE html>")
    assert cli_fleet.main(["worklog", "nobody", "--date", DAY]) == 2
    assert "refused: wrong_repo" in capsys.readouterr().out
    assert cli_fleet.main(["worklog", "luna", "--date", "yesterday"]) == 2
    assert "refused: bad_day" in capsys.readouterr().out


def test_the_notebook_setting_exists_is_blank_by_default_and_is_read_by_the_preview(luna, fleet_home):
    from agentdata.fleet import settings as SET

    assert WL.NOTEBOOK_KEY in SET.EDITABLE and SET.EDITABLE[WL.NOTEBOOK_KEY]["default"] == ""
    assert not SET.EDITABLE[WL.NOTEBOOK_KEY].get("agent"), "one notebook for the fleet, never per agent"
    before = WL.preview("luna")
    assert not before["configured"] and before["action"] == "create" and before["events"] >= 11
    assert before["path"] == "luna/luna/2026-09/2026-09-15" and before["title"] == "2026-09-15 · luna"
    assert os.path.isfile(before["html"]) and os.path.isfile(before["local"])
    assert before["html"].endswith("/agents/luna/wrapup/onenote.html")
    _set_notebook("https://contoso-my.sharepoint.com/personal/x/_layouts/15/Doc.aspx?id=1")
    after = WL.preview("luna")
    assert after["configured"] and after["notebook"].startswith("https://contoso-my.sharepoint.com/")


def test_the_preview_says_append_once_the_cursor_says_a_page_was_written(luna):
    last = E.read("luna")[-1]["seq"]
    WL.write_cursor("luna", {"days": {DAY: {"seq": last}}})
    pre = WL.preview("luna")
    assert pre["action"] == "nothing" and pre["events"] == 0, "nothing came after the cursor"
    E.append("luna", [_ev("pr_open", {"url": "https://example/pr/1"}, at="12:00:00")])
    pre = WL.preview("luna")
    assert pre["action"] == "append" and pre["seq_from"] == pre["seq_to"] == last + 1
    assert pre["tickets"] == ["RDSD-7"] and WL.read_cursor("luna")["days"][DAY]["seq"] == last, "the preview moves no cursor"


# ------------------------------------------------------------------------------------------ the wrap-up row


def test_the_wrapup_offers_the_worklog_row_unticked_with_the_reason_in_its_code(luna, monkeypatch):
    def quiet(argv, cwd, env=None):
        return {"code": 2, "meta": {"ok": False, "code": "detached_head", "error": "x", "hint": ""}, "tables": {},
                "stderr": ""}

    monkeypatch.setattr(WRAP, "RUN", quiet)
    rows = {r["step"]: r for r in WRAP.plan("luna", "day")["rows"]}
    row = rows["onenote"]
    assert row["code"] == "not_configured" and not row["ok"] and not row["ticked"]
    assert WL.NOTEBOOK_KEY in row["hint"] and row["payload"]["path"] == "luna/luna/2026-09/2026-09-15"
    assert row["payload"]["action"] == "create" and row["payload"]["seq_to"] >= 11
    assert row["summary"].startswith("worklog: create luna/luna/2026-09/")
    assert "onenote" in WRAP.ORDER and WRAP.TOTALS["onenote"] == "worklogs"
    assert "not_configured" in WRAP.QUIET and "not_built" in WRAP.QUIET, "a quiet row never makes a repo 'planned'"

    _set_notebook("https://contoso-my.sharepoint.com/personal/x/_layouts/15/Doc.aspx?id=1")
    first = {r["step"]: r for r in WRAP.plan("luna", "day")["rows"]}["onenote"]
    assert first["code"] == "not_built" and "W-3" in first["hint"] and not first["ticked"]
    E.append("luna", [_ev("pr_open", {"url": "https://example/pr/1"}, at="12:00:00")])
    second = {r["step"]: r for r in WRAP.plan("luna", "day")["rows"]}["onenote"]
    assert second["id"] != first["id"], "a new event changes the preview's id, as every step's does"
    assert second["payload"]["seq_to"] == first["payload"]["seq_to"] + 1
