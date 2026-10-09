"""The skills marketplace (operator request, 2026-10): what is installed, how each skill has been used,
and the page and route that show it (`agentdata/fleet/skills.py`, `/skills`, `GET /api/skills`).

The facts were all on disk and nothing folded them: every skills directory, the `skill` tool calls in
every agent's stream and in Copilot's own session files. What is held here is that the fold is right
(a call, its result, the repository and the ticket), that it survives the stream rolling the way
spend does (#210), that a rebuild from the files equals the incremental ledger, that a shadowed copy
and a missing skill are both said, and that the page is served the way every page is.
"""
from __future__ import annotations
import json
import os
import re
import threading
import urllib.error
import urllib.request

import pytest

from agentdata import config as C, update as U
from agentdata.fleet import events as E, lifecycle, registry, serve as S, skills as SK
from agentdata.fleet.registry import Registry, agent_dir

from test_fleet import make_project

STATIC = S.STATIC


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "copilot" / "session-state"))
    return tmp_path / "fleet"


@pytest.fixture()
def two_dirs(tmp_path, monkeypatch):
    """Two skills directories, the first winning on a clash, the way the CLI reads them."""
    first, second = tmp_path / "skills-a", tmp_path / "skills-b"
    _skill(first, "triage", "sort the inbox")
    _skill(second, "triage", "an older copy")
    _skill(second, "publish", ">\n  push the\n  report")
    monkeypatch.setattr(U, "SKILL_DIRS", (str(first), str(tmp_path / "nowhere"), str(second)))
    return first, second


def _skill(root, name: str, description: str, body: str = "do the thing\n") -> str:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}", encoding="utf-8")
    return str(path)


def _call(repo: str, skill: str, call_id: str, *, ticket: str, ts: str) -> dict:
    return E.event(repo, "tool_call", {"tool": "skill", "id": call_id, "arguments": {"skill": skill}},
                   ticket=ticket, ts=ts)


def _result(repo: str, call_id: str, ok: bool, *, ticket: str, ts: str) -> dict:
    return E.event(repo, "tool_result", {"id": call_id, "ok": ok, "error": "" if ok else "failed",
                                         "message": "" if ok else "no such file"}, ticket=ticket, ts=ts)


def _three_calls(tmp_path, name="alpha"):
    """One agent with three skill calls -- two ok, one failed -- across two repositories' worth of
    envelope (an agent's stream carries the repo it ran in), and one other tool's call in between."""
    path = make_project(tmp_path / name, ticket="RDSD-1")
    Registry().add(path, name=name)
    E.append(name, [
        E.event(name, "started", {"pid": 1, "session": "sess-fleet-1"}, ticket="RDSD-1"),
        _call(name, "triage", "c1", ticket="RDSD-1", ts="2026-10-08T09:00:00"),
        E.event(name, "tool_call", {"tool": "shell", "id": "x1", "arguments": {"command": "ls"}}, ticket="RDSD-1"),
        _result(name, "c1", True, ticket="RDSD-1", ts="2026-10-08T09:00:05"),
        E.event(name, "tool_result", {"id": "x1", "ok": True}, ticket="RDSD-1"),
        _call(name, "triage", "c2", ticket="RDSD-2", ts="2026-10-08T10:00:00"),
        _result(name, "c2", False, ticket="RDSD-2", ts="2026-10-08T10:00:03"),
        _call("alpha-wt", "publish", "c3", ticket="RDSD-2", ts="2026-10-08T11:00:00"),
        _result("alpha-wt", "c3", True, ticket="RDSD-2", ts="2026-10-08T11:00:09"),
    ])
    return path


def _serve():
    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, token, server.server_address[1]


def _stop(server):
    server.stopping.set()
    server.shutdown()
    server.server_close()


# ------------------------------------------------------------------------------- what is installed


def test_installed_merges_every_directory_and_the_first_copy_of_a_name_wins(fleet_home, two_dirs):
    first, second = two_dirs
    rows = SK.installed()
    assert [(r["name"], r["dir"]) for r in rows] == [
        ("triage", SK.short_dir(str(first))), ("publish", SK.short_dir(str(second))),
        ("triage", SK.short_dir(str(second)))]
    winner, publish, loser = rows
    assert winner["shadowed_by"] == "" and loser["shadowed_by"] == SK.short_dir(str(first))
    assert winner["description"] == "sort the inbox" and loser["description"] == "an older copy"
    assert publish["description"] == "push the report", "a folded description is joined"
    assert re.fullmatch(r"[0-9a-f]{12}", winner["version"]) and winner["version"] != loser["version"]
    assert winner["lines"] == 5 and winner["ours"] is True and winner["path"].endswith("triage/SKILL.md")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", winner["installed"])
    assert SK.dirs() == [str(first), str(second)], "a directory that does not exist is not listed"


def test_a_name_that_is_not_a_skill_folder_is_not_a_skill(fleet_home, two_dirs, tmp_path):
    (tmp_path / "skills-a" / "notes.txt").write_text("not a skill", encoding="utf-8")
    (tmp_path / "skills-a" / "empty").mkdir()
    assert [r["name"] for r in SK.installed()] == ["triage", "publish", "triage"]


# ------------------------------------------------------------------------------- the ledger


def test_the_ledger_folds_calls_results_repositories_and_tickets(fleet_home, tmp_path):
    _three_calls(tmp_path)
    state = SK.update("alpha")
    assert state["agents"]["alpha"]["cursor"]["seq"] == 9 and state["agents"]["alpha"]["open"] == {}
    triage, publish = state["skills"]["triage"], state["skills"]["publish"]
    assert (triage["uses"], triage["ok"], triage["failed"]) == (2, 1, 1)
    assert (publish["uses"], publish["ok"], publish["failed"]) == (1, 1, 0)
    assert triage["first"] == "2026-10-08T09:00:00" and triage["last"] == "2026-10-08T10:00:00"
    assert triage["repos"] == {"alpha": {"uses": 2, "last": "2026-10-08T10:00:00"}}
    assert publish["repos"] == {"alpha-wt": {"uses": 1, "last": "2026-10-08T11:00:00"}}
    assert triage["tickets"] == ["RDSD-1", "RDSD-2"] and triage["sources"] == {"fleet": 2, "copilot": 0}
    assert "shell" not in state["skills"], "another tool's call is not a skill"
    assert state["fleet_sessions"] == {"sess-fleet-1": "alpha"}

    # the file: schema 1, atomic, and read back as written
    on_disk = json.loads((fleet_home / "skills.json").read_text(encoding="utf-8"))
    assert on_disk["schema"] == 1 and on_disk["skills"]["triage"]["uses"] == 2
    assert not os.path.exists(str(fleet_home / "skills.json.tmp"))
    assert SK.update("alpha")["skills"] == state["skills"], "folding again past the cursor adds nothing"


def test_a_result_that_lands_after_the_fold_is_still_joined_to_its_call(fleet_home, tmp_path):
    path = make_project(tmp_path / "beta", ticket="RDSD-3")
    Registry().add(path, name="beta")
    E.append("beta", [_call("beta", "triage", "c9", ticket="RDSD-3", ts="2026-10-08T12:00:00")])
    state = SK.update("beta")
    assert state["skills"]["triage"] == dict(SK._blank_skill(), uses=1, first="2026-10-08T12:00:00",
                                             last="2026-10-08T12:00:00", tickets=["RDSD-3"],
                                             repos={"beta": {"uses": 1, "last": "2026-10-08T12:00:00"}},
                                             sources={"fleet": 1, "copilot": 0})
    assert state["agents"]["beta"]["open"] == {"c9": "triage"}
    E.append("beta", [_result("beta", "c9", False, ticket="RDSD-3", ts="2026-10-08T12:00:04")])
    state = SK.update("beta")
    assert state["skills"]["triage"]["failed"] == 1 and state["agents"]["beta"]["open"] == {}


def test_the_counts_survive_the_log_rolling_and_a_rebuild_agrees(fleet_home, tmp_path):
    """The bug spend had (#210): `rotate_all` moves `events.norm.jsonl` aside and `events.read`
    opens only the live file. The ledger is folded before the roll, and a rebuild from `.1` then the
    live file says the same."""
    _three_calls(tmp_path)
    E.append("alpha", [E.event("alpha", "raw", {"pad": "x" * (1200 * 1024)}, ticket="RDSD-1")])
    C.save({"fleet": {"log_mb": 1, "log_keep": 3}})
    rolled = lifecycle.rotate_all("alpha", cfg=C.load())
    assert E.NORMALIZED in rolled and os.path.isfile(os.path.join(agent_dir("alpha"), E.NORMALIZED + ".1"))
    assert SK.read_ledger()["skills"]["triage"]["uses"] == 2, "folded before the move"

    E.append("alpha", [_call("alpha", "publish", "c4", ticket="RDSD-4", ts="2026-10-08T13:00:00"),
                       _result("alpha", "c4", True, ticket="RDSD-4", ts="2026-10-08T13:00:02")])
    incremental = SK.update("alpha")
    assert incremental["skills"]["publish"]["uses"] == 2, "one from before the roll, one after"
    rebuilt = SK.rebuild()
    assert rebuilt["skills"] == incremental["skills"]
    assert rebuilt["agents"]["alpha"]["cursor"] == incremental["agents"]["alpha"]["cursor"]


def test_copilots_own_sessions_count_under_their_own_source_and_the_fleets_are_not_counted_twice(
        fleet_home, tmp_path):
    _three_calls(tmp_path)
    SK.update("alpha")
    state_dir = tmp_path / "copilot" / "session-state"

    def session(sid, cwd, *lines):
        d = state_dir / sid
        d.mkdir(parents=True)
        (d / "workspace.yaml").write_text(f"cwd: {cwd}\n", encoding="utf-8")
        (d / "events.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        return d

    def start(call_id, skill, ts="2026-10-07T08:00:00Z"):
        return {"type": "tool.execution_start", "id": "e", "timestamp": ts,
                "data": {"toolName": "skill", "toolCallId": call_id, "arguments": {"skill": skill}}}

    def done(call_id, ok=True):
        return {"type": "tool.execution_complete", "id": "e", "timestamp": "2026-10-07T08:00:01Z",
                "data": {"toolCallId": call_id, "success": ok, "error": None if ok else {"code": "x"}}}

    session("sess-own-1", str(tmp_path / "gamma"), start("k1", "triage"), done("k1"),
            start("k2", "review"), done("k2", ok=False))
    # the fleet's own session, written by Copilot too: its id is on alpha's stream
    session("sess-fleet-1", str(tmp_path / "alpha"), start("k3", "triage"), done("k3"))
    state = SK.fold_copilot_sessions()
    triage, review = state["skills"]["triage"], state["skills"]["review"]
    assert triage["uses"] == 3 and triage["sources"] == {"fleet": 2, "copilot": 1}, triage
    assert triage["repos"]["gamma"] == {"uses": 1, "last": "2026-10-07T08:00:00"}
    assert review == dict(SK._blank_skill(), uses=1, failed=1, first="2026-10-07T08:00:00",
                          last="2026-10-07T08:00:00", repos={"gamma": {"uses": 1, "last": "2026-10-07T08:00:00"}},
                          sources={"fleet": 0, "copilot": 1})
    assert "sess-fleet-1" not in state["copilot"] and state["copilot"]["sess-own-1"]["repo"] == "gamma"

    # only what Copilot appended is read next time, and a half-written line waits
    with open(state_dir / "sess-own-1" / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(start("k4", "triage", ts="2026-10-07T09:00:00Z")) + "\n" + '{"type": "tool.exe')
    again = SK.fold_copilot_sessions()
    assert again["skills"]["triage"]["sources"]["copilot"] == 2 and again["skills"]["triage"]["last"] == "2026-10-08T10:00:00"
    assert SK.fold_copilot_sessions()["skills"]["triage"]["uses"] == 4, "nothing moved: nothing counted twice"
    assert SK.rebuild()["skills"] == again["skills"]


# ------------------------------------------------------------------------------- the snapshot


def test_the_snapshot_joins_the_disk_and_the_ledger_sorted_by_uses_then_name(fleet_home, tmp_path, two_dirs):
    first, second = two_dirs
    _three_calls(tmp_path)
    E.append("alpha", [_call("alpha", "gone", "c7", ticket="RDSD-9", ts="2026-01-01T00:00:00"),
                       _result("alpha", "c7", True, ticket="RDSD-9", ts="2026-01-01T00:00:01")])
    snap = SK.snapshot()
    assert snap["dirs"] == [SK.short_dir(str(first)), SK.short_dir(str(second))]
    assert [(r["name"], r["uses"]) for r in snap["skills"]] == [
        ("triage", 2), ("gone", 1), ("publish", 1), ("triage", 0)]
    triage, gone, publish, shadow = snap["skills"]
    assert (triage["ok"], triage["failed"], triage["last"]) == (1, 1, "2026-10-08T10:00:00")
    assert triage["repos"] == [{"repo": "alpha", "uses": 2, "last": "2026-10-08T10:00:00"}]
    assert triage["tickets"] == ["RDSD-1", "RDSD-2"] and triage["sources"] == {"fleet": 2, "copilot": 0}
    assert not triage["unused"] and not triage["missing"] and triage["dir"] == SK.short_dir(str(first))
    assert gone["missing"] is True and gone["installed"] is None and gone["dir"] == "" and not gone["unused"]
    assert shadow["shadowed_by"] == SK.short_dir(str(first)) and shadow["uses"] == 0 and not shadow["unused"], \
        "a shadowed copy is neither used nor called unused: the call names the skill, not the copy"
    assert snap["totals"] == {"skills": 2, "used": 3, "unused": 0, "uses": 4, "used_recently": 2,
                              "recent_days": 30, "missing": 1}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", snap["ledger_updated"])

    _skill(first, "quiet", "never called")
    rows = {r["name"]: r for r in SK.snapshot()["skills"]}
    assert rows["quiet"]["unused"] is True and rows["quiet"]["uses"] == 0


def test_without_a_fleet_or_a_skill_the_snapshot_is_empty_and_never_raises(fleet_home, tmp_path, monkeypatch):
    monkeypatch.setattr(U, "SKILL_DIRS", (str(tmp_path / "none"),))
    snap = SK.snapshot()
    assert snap["skills"] == [] and snap["dirs"] == [] and snap["totals"]["skills"] == 0
    (fleet_home / "skills.json").parent.mkdir(parents=True, exist_ok=True)
    (fleet_home / "skills.json").write_text("{not json", encoding="utf-8")
    assert SK.read_ledger() == SK.blank(), "a ledger that cannot be read is an empty one, to be rebuilt"


# ------------------------------------------------------------------------------- the route and the page


def test_the_route_answers_the_snapshot_and_the_page_is_served_like_every_page(fleet_home, tmp_path, two_dirs):
    """`/api/skills` is the snapshot; `/skills` is served with its assets carrying the token, ink-off,
    and `/open?page=skills` lands on it; the settings page is the door."""
    _three_calls(tmp_path)
    assert S.PAGES["/skills"] == "skills.html"
    assert "skills.css" in S.ASSETS and "skills/skills.js" in S.ASSETS
    assert "skills.html" not in S.INKED_PAGES
    server, token, port = _serve()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/skills?t={token}", timeout=5) as r:
            data = json.loads(r.read())
        assert data["ok"] is True and data["totals"]["uses"] == 3
        assert [r["name"] for r in data["skills"]][:2] == ["triage", "publish"]
        assert data["skills"][0]["repos"][0]["repo"] == "alpha"

        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/skills?t={token}", timeout=5).read().decode()
        assert f'"/static/skills/skills.js?t={token}"' in html and f'"/static/skills.css?t={token}"' in html
        assert "ink-off" in html and 'id="backbtn"' in html and 'id="deskbtn"' in html and 'id="skillq"' in html

        class Stay(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None

        try:
            urllib.request.build_opener(Stay).open(f"http://127.0.0.1:{port}/open?page=skills", timeout=5)
            raise AssertionError("/open answered without a redirect")
        except urllib.error.HTTPError as e:
            assert e.code == 302 and e.headers["Location"].startswith(f"/skills?t={token}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/skills", timeout=5)
            raise AssertionError("the route answered without the token")
        except urllib.error.HTTPError as e:
            assert e.code == 403
    finally:
        _stop(server)

    settings = open(os.path.join(STATIC, "settings.html"), encoding="utf-8").read()
    js = open(os.path.join(STATIC, "settings.js"), encoding="utf-8").read()
    assert 'id="skillsblock"' in settings and 'id="skillsline"' in settings and 'id="skillsbtn"' in settings
    assert 'skillsLink.href = pageUrl("/skills")' in js
    assert 'text(line, "skills: unavailable")' in js, "a marketplace that cannot answer leaves the line, never throws"
