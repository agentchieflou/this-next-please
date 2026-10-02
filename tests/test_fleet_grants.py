"""A refused tool, named, and the desk's one-click *yes* (operator report, 2026-10-02).

"In the chrome browser we can't perform actions like Jira to Power BI UAT. Currently I have to close
the fleet and open the session in copilot cli locally to get a valid execution context." A headless
turn has nobody to ask: a command its allow-list does not cover is refused, the turn ends 0, and the
tile said only "Permission denied and could not request permission from user". In a terminal of
their own the operator answers that prompt with *yes*. These tests hold the desk's version of it:
the tile names what was refused and the narrowest entry that would allow it, a press adds that entry
to the agent's own extras (or every agent's) and retries, and nothing on the deny floor is offered.
"""
from __future__ import annotations
import json
import os

import pytest

import fakes
from agentdata import config as C
from agentdata.fleet import agentstate, events as E, grants as G, launch as L, overrides as OV
from agentdata.fleet import serve as S, supervisor
from agentdata.fleet.registry import Registry

from test_fleet_e2e import _project, _settle


def _events(*pairs):
    return [{"seq": i, "kind": k, "data": d} for i, (k, d) in enumerate(pairs, 1)]


def _refused(tool, arguments):
    return agentstate.derive(_events(("turn_started", {}),
                                     ("tool_call", {"tool": tool, "id": "t1", "arguments": arguments}),
                                     ("denied", {"id": "t1", "message": "Permission denied and could not "
                                                                        "request permission from user"}),
                                     ("turn_ended", {})))


# ------------------------------------------------------------------------------ what was refused


def test_the_tile_names_the_refused_command_and_the_entry_that_would_allow_it():
    got = _refused("powershell", {"command": "dscmd.exe csv .agent/out/q.csv -s localhost:5123"})
    assert got["state"] == "needs_human"
    assert got["why"] == ("refused powershell: dscmd.exe csv .agent/out/q.csv -s localhost:5123"
                          " — allow shell(dscmd.exe)?")
    (row,) = got["refused_tools"]
    assert row["patterns"] == ["shell(dscmd.exe)"] and row["grantable"] and not row["broad"]


def test_a_file_edit_is_the_write_tool_and_says_how_wide_that_is():
    (row,) = _refused("apply_patch", {"path": ".agent/dax/RDSD-1-check.dax"})["refused_tools"]
    assert row["patterns"] == ["write"] and row["broad"] and ".git/hooks" in row["why_broad"]
    assert row["what"] == "apply_patch: .agent/dax/RDSD-1-check.dax"


def test_an_interpreter_is_broad_and_a_module_form_is_not():
    (script,) = _refused("bash", {"command": "python .agent/rollup.py"})["refused_tools"]
    assert script["patterns"] == ["shell(python)"] and script["broad"]
    (module,) = _refused("bash", {"command": "python -m agentdata.csv2toon out.csv"})["refused_tools"]
    assert module["patterns"] == ["shell(python -m agentdata.csv2toon)"] and not module["broad"]


def test_git_is_granted_one_verb_at_a_time():
    (row,) = _refused("bash", {"command": "git stash list"})["refused_tools"]
    assert row["patterns"] == ["shell(git stash)"]


def test_a_chain_asks_only_for_what_the_shipped_list_lacks():
    (row,) = _refused("bash", {"command": "cd .agent && git status && dscmd.exe csv x.csv"})["refused_tools"]
    assert row["patterns"] == ["shell(cd)", "shell(dscmd.exe)"], "git status is already allowed"


@pytest.mark.parametrize("command, instead", [
    ("pncli bitbucket --help", "ad-pncli help"),
    ("pncli jira get-issue --key RDSD-1", "ad-pncli"),
    ("git push -u origin HEAD", "ad-git push"),
    ("curl -X POST https://jira.example.test/rest/api/2/issue", "ad-*"),
    ("rm -rf .agent/out", "cleanup guide"),
    ("cd x && pncli confluence create-page --title t", "ad-pncli"),
])
def test_the_deny_floor_is_never_offered_and_says_what_to_use_instead(command, instead):
    got = _refused("bash", {"command": command})
    (row,) = got["refused_tools"]
    assert not row["grantable"] and row["patterns"] == [] and row["floor"], row
    assert instead in row["instead"] and instead in got["why"], got["why"]


def test_a_denial_whose_call_was_never_seen_keeps_its_own_words():
    got = agentstate.derive(_events(("turn_started", {}), ("denied", {"message": "no `git push`"}),
                                    ("turn_ended", {})))
    assert got["why"] == "no `git push`"


def test_a_new_turn_forgets_what_the_last_one_was_refused():
    events = _events(("turn_started", {}),
                     ("tool_call", {"tool": "bash", "id": "t1", "arguments": {"command": "dscmd.exe x"}}),
                     ("denied", {"id": "t1", "message": "x"}), ("turn_ended", {}),
                     ("turn_started", {}), ("turn_ended", {}))
    got = agentstate.derive(events)
    assert got["refused_tools"] == [] and got["state"] != "needs_human"


# --------------------------------------------------------------------------------- the grant


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    # A refusal needs an allow-list to fall outside: `strict`. The default since 2026-10-02 is a
    # Copilot window's tools, where only the fleet's own commands are refused (the last test here).
    C.save({"fleet": {"permissions": "strict"}})
    for name in ("luna", "uat"):
        Registry().add(_project(str(tmp_path / name)), name=name)
    return tmp_path


def _allowed(cfg, repo):
    argv = L.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=OV.for_agent(cfg, repo))
    return [argv[i + 1] for i, a in enumerate(argv) if a == "--allow-tool"]


def test_a_grant_is_that_agents_and_reaches_its_next_launch_only(home):
    cfg = C.load()
    done = G.grant(cfg, "luna", ["shell(dscmd.exe)"], known={"luna", "uat"})
    assert done["now"] == ["shell(dscmd.exe)"] and done["scope"] == "agent"
    assert "shell(dscmd.exe)" in _allowed(cfg, "luna")
    assert "shell(dscmd.exe)" not in _allowed(cfg, "uat")
    G.grant(cfg, "luna", ["shell(dscmd.exe)", "write"], known={"luna", "uat"})
    assert OV.own(cfg, "luna")[G.KEY] == ["shell(dscmd.exe)", "write"], "added once, in order"


def test_a_grant_for_every_agent_is_the_fleets_list(home):
    cfg = C.load()
    G.grant(cfg, "luna", ["shell(git stash)"], scope="fleet", known={"luna", "uat"})
    assert C.get(cfg, G.KEY) == ["shell(git stash)"]
    assert "shell(git stash)" in _allowed(cfg, "uat")


def test_a_grant_never_reaches_past_a_denial(home):
    cfg = C.load()
    with pytest.raises(G.GrantError) as floor:
        G.grant(cfg, "luna", ["shell(pncli)"], known={"luna"})
    assert floor.value.code == "denied_by_floor" and "ad-pncli" in floor.value.hint
    C.put(cfg, "fleet.copilot.deny_extra", ["shell(dscmd.exe)"])
    with pytest.raises(G.GrantError) as mine:
        G.grant(cfg, "luna", ["shell(dscmd.exe)"], known={"luna"})
    assert mine.value.code == "denied_by_you" and "also denied" in mine.value.hint
    for bad in ("--allow-all-tools", "shell(rm) --yolo", ""):
        with pytest.raises(G.GrantError):
            G.grant(cfg, "luna", [bad], known={"luna"})
    assert not OV.own(cfg, "luna").get(G.KEY), "a refused grant writes nothing"


# ------------------------------------------------------------------- refused, granted, retried


def test_refused_then_granted_from_the_desk_then_retried(home, tmp_path, monkeypatch):
    """The whole loop through the real supervisor and the fake CLI that honours the flags: the first
    turn is refused `git version`, the desk's `grant` adds `shell(git version)` to luna's extras and
    sends the retry, and the second launch carries the entry and runs the command."""
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "refused-then-granted")
    supervisor.start("luna", key="RDSD-7", cfg={"fleet": {"permissions": "strict", "notify": {"toast": False}}})
    _settle(["luna"])
    E.refresh("luna", str(home / "luna"), repo_state=Registry().get("luna").state())
    got = agentstate.derive(E.read("luna"))
    assert got["state"] == "needs_human", got
    (row,) = got["refused_tools"]
    assert row["what"] == "shell: git version" and row["patterns"] == ["shell(git version)"]

    answer = S.act("grant", {"repo": "luna", "patterns": row["patterns"], "retry": True})
    assert answer["allowed"] == ["shell(git version)"] and answer["retried"] is True, answer
    _settle(["luna"])
    E.refresh("luna", str(home / "luna"), repo_state=Registry().get("luna").state())

    launches = [c for c in fakes.calls({"AGENTDATA_FAKE_LOG": os.environ["AGENTDATA_FAKE_LOG"]}, "copilot")
                if "-p" in c]
    assert len(launches) == 2, launches
    assert "shell(git version)" not in launches[0] and "shell(git version)" in launches[1]
    assert "The operator allowed `shell(git version)`" in launches[1][launches[1].index("-p") + 1]
    after = agentstate.derive(E.read("luna"))
    assert after["refused_tools"] == [] and after["state"] != "needs_human", after
    saved = json.load(open(os.environ["AGENTDATA_CONFIG"], encoding="utf-8"))
    assert saved["fleet"]["agents"]["luna"][G.KEY] == ["shell(git version)"]


# ------------------------------------------------------------------------------ the rendered card


@pytest.mark.browser
def test_the_refused_card_names_the_command_and_one_press_grants_and_retries(home, desk_browser):
    """On the rendered page: the refused command, the entry a press would add, the floor row with
    its alternative and no button, and the press posting exactly the grant the card showed."""
    import threading

    from desk_harness import close_pages

    E.append("luna", [
        E.event("luna", "started", {"pid": 1, "prompt": "Ticket RDSD-7."}, ticket="RDSD-7"),
        E.event("luna", "turn_started", {"turn": "0"}, ticket="RDSD-7"),
        E.event("luna", "tool_call", {"tool": "powershell", "id": "t1",
                                      "arguments": {"command": "dscmd.exe csv q.csv -s localhost:5123"}},
                ticket="RDSD-7"),
        E.event("luna", "denied", {"id": "t1", "message": "Permission denied"}, ticket="RDSD-7"),
        E.event("luna", "tool_call", {"tool": "powershell", "id": "t2",
                                      "arguments": {"command": "pncli bitbucket --help"}}, ticket="RDSD-7"),
        E.event("luna", "denied", {"id": "t2", "message": "Permission denied"}, ticket="RDSD-7"),
        E.event("luna", "turn_ended", {"turn": "0"}, ticket="RDSD-7"),
    ])
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    port = server.server_address[1]
    try:
        page = desk_browser.new_page(viewport={"width": 1280, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}/?t={token}&layout=grid", wait_until="domcontentloaded")
        page.wait_for_selector('.tile[data-repo="luna"] .refused:not([hidden])', timeout=15000)
        card = page.locator('.tile[data-repo="luna"] .refused')
        rows = card.locator(".refusal:not([hidden])")
        assert rows.count() == 2 and "2 commands" in card.locator(".refused-n").inner_text()
        first, floor = rows.nth(0), rows.nth(1)
        assert first.locator(".refusal-what").inner_text() == "powershell: dscmd.exe csv q.csv -s localhost:5123"
        assert first.locator(".refusal-allow").inner_text() == "allow shell(dscmd.exe) for luna, then retry"
        assert first.locator(".refusal-allow").is_visible() and first.locator(".refusal-all").is_visible()
        assert "ad-pncli help" in floor.locator(".refusal-note").inner_text()
        assert not floor.locator(".refusal-allow").is_visible(), "the deny floor is never offered"

        sent = []

        def grant(route):
            sent.append(json.loads(route.request.post_data or "{}"))
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"ok": True, "repo": "luna", "allowed": ["shell(dscmd.exe)"],
                                                  "scope": "agent", "retried": True}))

        page.route("**/api/grant*", grant)
        first.locator(".refusal-allow").click()
        page.wait_for_function("""() => document.querySelector('.tile[data-repo="luna"] .refusal.is-granted')""",
                               timeout=5000)
        assert sent == [{"repo": "luna", "patterns": ["shell(dscmd.exe)"], "scope": "agent", "retry": True}], sent
        assert "allowed shell(dscmd.exe) for luna — retrying" in first.locator(".refusal-note").inner_text()
        assert not errors, errors
        close_pages(desk_browser)
    finally:
        server.shutdown()
        server.server_close()


def test_the_terminal_verb_is_the_same_action_and_refuses_the_floor_by_name(home, capsys):
    from agentdata import cli_fleet

    assert cli_fleet.main(["grant", "luna", "shell(pncli)"]) == 2
    out = capsys.readouterr().out
    assert "refused: denied_by_floor" in out and "ad-pncli" in out
    assert cli_fleet.main(["grant", "luna", "shell(dscmd.exe)"]) == 0
    out = capsys.readouterr().out
    assert "allowed: shell(dscmd.exe)" in out and "retried: false" in out
    assert OV.own(C.load(), "luna")[G.KEY] == ["shell(dscmd.exe)"]


def test_with_a_windows_tools_only_the_fleets_own_commands_are_refused_and_never_granted(home):
    cfg = {"fleet": {"permissions": "copilot"}}
    assert G.grant(cfg, "luna", ["shell(pncli)"], known={"luna"})["allowed"] == ["shell(pncli)"], \
        "nothing on the strict floor is denied here, so nothing stops it"
    with pytest.raises(G.GrantError) as e:
        G.grant(cfg, "luna", ["shell(ad-fleet)"], known={"luna"})
    assert e.value.code == "denied_by_floor" and "operator" in e.value.hint


# ------------------------------------------------------------------- the environment it starts in


def test_the_agent_gets_what_a_new_terminal_would_have_without_losing_the_desks_own(monkeypatch):
    """The desk runs for days; pncli or a proxy installed since were in every new terminal and
    missing from every agent. A launch tops the desk's environment up from a new login's: missing
    directories appended to PATH after its own, missing variables added, nothing replaced."""
    monkeypatch.setenv("PATH", os.pathsep.join(["/venv/bin", "/usr/bin"]))
    monkeypatch.setenv("HTTPS_PROXY", "http://the-desks-own:8080")
    monkeypatch.delenv("PNCLI_HOME", raising=False)
    fresh = {"Path": os.pathsep.join(["/usr/bin/", "/npm/global"]), "HTTPS_PROXY": "http://other:3128",
             "PNCLI_HOME": "/home/luna/.pncli"}
    env = L.child_env("luna", "/fleet", login=lambda: fresh)
    assert env["PATH"].split(os.pathsep) == ["/venv/bin", "/usr/bin", "/npm/global"], "theirs first, once each"
    assert env["HTTPS_PROXY"] == "http://the-desks-own:8080", "a value the desk was started with is kept"
    assert env["PNCLI_HOME"] == "/home/luna/.pncli"
    assert env["AGENTDATA_FLEET_AGENT"] == "luna"


def test_a_login_environment_that_cannot_be_read_never_stops_a_launch():
    def broken():
        raise OSError("the registry said no")

    env = L.child_env("luna", "/fleet", login=broken)
    assert env["AGENTDATA_FLEET_AGENT"] == "luna"
    assert L.login_env() == {} or os.name == "nt", "elsewhere a login shell cannot be read without running one"
