"""Copilot's own settings, global and per repository, on the fleet screen (operator, 2026-10-02).

"When a user does /config in an individual repository in regular copilot cli, they're first setting
global permissions. What we're trying to do is have the repo permissions be accessible from the fleet
screen in addition to the global settings." Chosen with the operator: the global section edits
`~/.copilot/settings.json` (what `/config` writes), a repository's permissions are the approvals
Copilot keeps for its Git root in `~/.copilot/permissions-config.json`, and `--allow-all-tools` stays
on by default but a repository can turn it off (`fleet.permissions: repo`), which runs that agent on
exactly those approvals.

Every test here points `COPILOT_HOME` at a temporary directory: nothing touches a real `~/.copilot`.
"""
from __future__ import annotations
import json
import os
import subprocess

import pytest

from agentdata import config as C
from agentdata.fleet import copilot_files as CF, launch as L, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project


@pytest.fixture()
def copilot(tmp_path, monkeypatch):
    home = tmp_path / "copilot-home"
    monkeypatch.setenv("COPILOT_HOME", str(home))
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    return home


def _git_repo(path) -> str:
    path = str(path)
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", path], check=True)
    return path


def _json(path):
    return json.load(open(path, encoding="utf-8"))


# ------------------------------------------------------------------------------------ global


def test_the_global_section_is_the_file_config_writes_and_keeps_what_it_does_not_know(copilot):
    copilot.mkdir()
    (copilot / "settings.json").write_text(json.dumps({"theme": "dark", "someFutureKey": {"x": 1}}), encoding="utf-8")
    got = CF.global_settings()
    assert got["path"].endswith("copilot-home/settings.json")
    rows = {r["key"]: r for r in got["rows"]}
    assert rows["theme"]["value"] == "dark" and rows["theme"]["set"]
    assert rows["askUser"]["value"] is None and not rows["askUser"]["set"], "every documented key is a row"
    assert rows["someFutureKey.x"]["value"] == 1, "an unknown key is shown, by its dotted name"

    CF.set_global("askUser", "false")
    CF.set_global("footer.showBranch", True)
    CF.set_global("allowedUrls", "github.com, docs.github.com")
    saved = _json(copilot / "settings.json")
    assert saved["askUser"] is False and saved["footer"] == {"showBranch": True}
    assert saved["allowedUrls"] == ["github.com", "docs.github.com"]
    assert saved["theme"] == "dark" and saved["someFutureKey"] == {"x": 1}, "nothing else touched"
    backup = _json(str(copilot / "settings.json") + ".bak")
    assert backup["footer"] == {"showBranch": True} and "allowedUrls" not in backup, "the previous content is kept"

    CF.unset_global("footer.showBranch")
    assert _json(copilot / "settings.json")["footer"] == {}
    with pytest.raises(CF.CopilotFileError) as e:
        CF.set_global("askUser", "maybe")
    assert e.value.code == "bad_value"
    with pytest.raises(CF.CopilotFileError):
        CF.set_global("bad key!", 1)


def test_a_file_that_is_not_json_is_never_written_over(copilot):
    copilot.mkdir()
    (copilot / "settings.json").write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(CF.CopilotFileError) as e:
        CF.set_global("askUser", True)
    assert e.value.code == "copilot_file_unreadable"
    assert (copilot / "settings.json").read_text(encoding="utf-8") == "{ this is not json"


def test_copilots_layers_decide_the_model_and_the_fleet_does_not_override_them(copilot, tmp_path):
    repo = make_project(tmp_path / "luna")
    Registry().add(repo, name="luna")
    assert L.model_for("luna", {}) == ("auto", "", "default"), "no setting anywhere: the operator's default"
    CF.set_global("model", "claude-sonnet-5")
    assert CF.setting("model", repo) == "claude-sonnet-5"
    assert L.model_for("luna", {}) == ("", "", "copilot settings"), "Copilot's /config applies: no flag over it"
    os.makedirs(os.path.join(repo, ".github", "copilot"))
    with open(os.path.join(repo, ".github", "copilot", "settings.local.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "claude-opus-5"}, f)
    assert CF.setting("model", repo) == "claude-opus-5", "the repository's local file wins over the user's"
    assert L.model_for("luna", {"fleet": {"model": "gpt-5.5"}})[0] == "gpt-5.5", "a fleet choice is a flag, and wins"


# ------------------------------------------------------------------------------- per repository


def test_a_repositorys_permissions_are_its_git_roots_location(copilot, tmp_path):
    repo = _git_repo(tmp_path / "luna")
    os.makedirs(os.path.join(repo, "src"))
    copilot.mkdir()
    other = {"locations": {"/elsewhere": {"tool_approvals": [{"kind": "mcp", "server": "x"}]}}, "version": 3}
    (copilot / "permissions-config.json").write_text(json.dumps(other), encoding="utf-8")

    got = CF.add_approval(os.path.join(repo, "src"), CF.approval("commands", "git:*, npm:*"))
    root = os.path.normpath(subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"],
                                           capture_output=True, text=True).stdout.strip())
    assert got["location"] == root, "a subdirectory is scoped by its Git root, as Copilot scopes it"
    assert got["tool_approvals"] == [{"kind": "commands", "commandIdentifiers": ["git:*", "npm:*"]}]
    CF.add_approval(repo, CF.approval("commands", "git:*, npm:*"))
    CF.add_approval(repo, CF.approval("write"))
    saved = _json(copilot / "permissions-config.json")
    assert saved["locations"]["/elsewhere"] == other["locations"]["/elsewhere"] and saved["version"] == 3
    assert saved["locations"][root]["tool_approvals"] == [
        {"kind": "commands", "commandIdentifiers": ["git:*", "npm:*"]}, {"kind": "write"}], "added once"

    CF.remove_approval(repo, {"kind": "write"})
    CF.set_directories(repo, ["/data/shared", "/data/shared", ""])
    got = CF.repo_permissions(repo)
    assert got["tool_approvals"] == [{"kind": "commands", "commandIdentifiers": ["git:*", "npm:*"]}]
    assert got["allowed_directories"] == ["/data/shared"]
    with pytest.raises(CF.CopilotFileError) as e:
        CF.set_directories(repo, ["relative/path"])
    assert e.value.code == "bad_value"
    with pytest.raises(CF.CopilotFileError) as e:
        CF.approval("mcp")
    assert e.value.code == "kind_unsupported" and "window" in e.value.hint


def test_an_existing_location_spelled_differently_is_reused_not_doubled(copilot, tmp_path):
    repo = _git_repo(tmp_path / "luna")
    root = os.path.normpath(subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"],
                                           capture_output=True, text=True).stdout.strip())
    copilot.mkdir()
    (copilot / "permissions-config.json").write_text(
        json.dumps({"locations": {root + os.sep: {"tool_approvals": [{"kind": "read"}]}}}), encoding="utf-8")
    CF.add_approval(repo, CF.approval("write"))
    locations = _json(copilot / "permissions-config.json")["locations"]
    assert list(locations) == [root + os.sep]
    assert locations[root + os.sep]["tool_approvals"] == [{"kind": "read"}, {"kind": "write"}]


# ------------------------------------------------------------------------- tool access per repository


def test_allow_all_is_on_by_default_and_a_repository_can_turn_it_off():
    """"--allow-all-tools is a global allow. We should still be able to turn it off from repo configs,
    but it should default to on." Off (`repo`) is no flag of the fleet's own: the agent has what
    Copilot grants in that checkout, and the fleet still denies only its own commands."""
    cfg = {"fleet": {"agents": {"rdsd.pbi": {"fleet.permissions": "repo"}}}}
    from agentdata.fleet import overrides as OV

    on = L.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=OV.for_agent(cfg, "luna"))
    off = L.launch_command("copilot", "C:/repo", "x", log_dir="C:/logs", cfg=OV.for_agent(cfg, "rdsd.pbi"))
    assert "--allow-all-tools" in on and "--allow-all-tools" not in off
    assert "--allow-tool" not in off, "no fleet list either: the repository's own approvals decide"
    assert [off[i + 1] for i, a in enumerate(off) if a == "--deny-tool"] == L.FLEET_SELF
    assert "--disable-builtin-mcps" not in off and "--autopilot" in off


# --------------------------------------------------------------------------------- through the page


def test_the_page_reads_and_writes_both_through_one_action(copilot, tmp_path):
    repo = _git_repo(tmp_path / "luna")
    with open(os.path.join(repo, "AGENTS.md"), "w", encoding="utf-8") as f:
        f.write("# Project\n\n- jira_project: RDSD\n")
    os.makedirs(os.path.join(repo, ".agent"))
    with open(os.path.join(repo, ".agent", "state.json"), "w", encoding="utf-8") as f:
        json.dump({"project": "RDSD", "phase": "idle"}, f)
    Registry().add(repo, name="luna")

    S.act("copilot", {"scope": "global", "key": "askUser", "value": False})
    S.act("copilot", {"repo": "luna", "scope": "repo", "add": {"kind": "commands", "identifiers": "dscmd.exe:*"}})
    snap = S.settings_snapshot()
    rows = {r["key"]: r for r in snap["copilot_global"]["rows"]}
    assert rows["askUser"]["value"] is False
    assert snap["copilot_repos"]["luna"]["tool_approvals"] == [
        {"kind": "commands", "commandIdentifiers": ["dscmd.exe:*"]}]
    S.act("copilot", {"repo": "luna", "scope": "repo",
                      "remove": {"kind": "commands", "commandIdentifiers": ["dscmd.exe:*"]}})
    assert S.settings_snapshot()["copilot_repos"]["luna"]["tool_approvals"] == []
    with pytest.raises(S.ServeError) as e:
        S.act("copilot", {"repo": "luna", "scope": "repo", "add": {"kind": "memory"}})
    assert e.value.code == "kind_unsupported"


def test_a_refused_tool_in_a_repo_mode_checkout_is_saved_to_its_copilot_approvals(copilot, tmp_path, monkeypatch):
    """The refused card's *yes*, for a repository whose tool access is off: it goes where a window's
    *always allow* goes, so the operator's own windows there get it too -- and the retry follows."""
    from agentdata.fleet import supervisor

    repo = _git_repo(tmp_path / "luna")
    with open(os.path.join(repo, "AGENTS.md"), "w", encoding="utf-8") as f:
        f.write("# Project\n\n- jira_project: RDSD\n")
    os.makedirs(os.path.join(repo, ".agent"))
    with open(os.path.join(repo, ".agent", "state.json"), "w", encoding="utf-8") as f:
        json.dump({"project": "RDSD", "phase": "idle"}, f)
    Registry().add(repo, name="luna")
    C.save({"fleet": {"agents": {"luna": {"fleet.permissions": "repo"}}}})
    sent = []
    monkeypatch.setattr(supervisor, "live", lambda name: {})
    monkeypatch.setattr(supervisor, "send", lambda name, text, cfg=None, force=False: sent.append(text) or {"pid": 1})
    out = S.act("grant", {"repo": "luna", "patterns": ["shell(dscmd.exe)", "write"], "retry": True})
    assert out["scope"] == "repo" and out["allowed"] == ["commands dscmd.exe:*", "write"] and out["retried"]
    assert CF.repo_permissions(repo)["tool_approvals"] == [
        {"kind": "commands", "commandIdentifiers": ["dscmd.exe:*"]}, {"kind": "write"}]
    assert not C.get(C.load(), "fleet.copilot.allow_extra"), "nothing went to the fleet's own list"
    assert sent and "commands dscmd.exe:*" in sent[0]


# ------------------------------------------------------------------------------- the rendered page


@pytest.mark.browser
def test_the_settings_page_edits_copilots_global_file_and_the_picked_repositorys_approvals(
        copilot, tmp_path, desk_browser):
    from desk_harness import close_pages
    from test_fleet_settings_page import _serve, _settings

    repo = _git_repo(tmp_path / "luna")
    with open(os.path.join(repo, "AGENTS.md"), "w", encoding="utf-8") as f:
        f.write("# Project\n\n- jira_project: RDSD\n")
    os.makedirs(os.path.join(repo, ".agent"))
    with open(os.path.join(repo, ".agent", "state.json"), "w", encoding="utf-8") as f:
        json.dump({"project": "RDSD", "phase": "idle"}, f)
    Registry().add(repo, name="luna")
    server, token, port = _serve()
    try:
        browser, page, errors = _settings(desk_browser, port, token)
        page.wait_for_selector("#cg-askUser", state="attached", timeout=10000)
        assert page.is_hidden("#crblock"), "a repository's section shows once an agent is picked"

        # global: a checkbox is /config askUser, written to the file /config writes
        assert not page.is_checked("#cg-askUser"), "unset: nothing in the file yet"
        with page.expect_response(lambda r: r.url.split("?")[0].endswith("/api/copilot")):
            page.check("#cg-askUser")
        page.wait_for_function("() => [...document.querySelectorAll('#cgrows tr')].some(tr => "
                               "tr.querySelector('code').textContent === 'askUser' && tr.querySelector('.dropone'))",
                               timeout=10000)
        assert _json(copilot / "settings.json")["askUser"] is True

        # the repository: its Git root's approvals, added and removed from here
        page.select_option("#scope", "luna")
        page.wait_for_selector("#crblock:not([hidden])", timeout=10000)
        assert "no approvals" in page.text_content("#crapprovals")
        page.fill("#crids", "git:*")
        with page.expect_response(lambda r: r.url.split("?")[0].endswith("/api/copilot")):
            page.click("#cradd")
        page.wait_for_function("() => document.querySelector('#crapprovals code') && "
                               "document.querySelector('#crapprovals code').textContent === 'commands git:*'",
                               timeout=10000)
        assert CF.repo_permissions(repo)["tool_approvals"] == [{"kind": "commands", "commandIdentifiers": ["git:*"]}]
        page.select_option("#crkind", "write")
        assert page.is_hidden("#crids"), "write takes no command names"
        page.click("#crapprovals li .dropone")
        page.wait_for_function("() => document.querySelector('#crapprovals').textContent.includes('no approvals')",
                               timeout=10000)
        assert CF.repo_permissions(repo)["tool_approvals"] == []
        assert not errors, errors
        close_pages(browser)
    finally:
        server.shutdown()
        server.server_close()
