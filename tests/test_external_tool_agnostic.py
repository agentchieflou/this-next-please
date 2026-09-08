r"""The user-agnostic ribbon file (#114) and the Tabular Editor custom action (#115).

The one claim worth a privileged write is that the file is the same file for everyone, so most of
what is asserted here is sameness: two users, two interpreters, one byte-identical
`agentdata.pbitool.json`. The rest guards the two places a mistake would be expensive -- a quote
lost in the C# the custom action runs, and a rewrite of somebody else's `CustomActions.json`.
"""
from __future__ import annotations
import json
import os
import re

import pytest

from agentdata.pbip import external_tool as EXT

AGNOSTIC_ARGS = '/c python -m agentdata pbip handoff --server "%server%" --database "%database%"'


@pytest.fixture()
def stable_launcher(monkeypatch):
    """`python` is on PATH, as it is on the machine this was measured on."""
    monkeypatch.setattr(EXT.shutil, "which", lambda name, *a, **k: "/usr/bin/python" if name == "python" else None)


def become_user(monkeypatch, tmp_path, name: str, interpreter: str) -> None:
    """A different logged-in user, on a different Python, at a different place on disk."""
    home = tmp_path / name
    (home / "AppData" / "Local").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("USERNAME", name)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setattr(EXT.sys, "executable", interpreter)


def workspace_tree(tmp_path, ports: dict[str, int]) -> str:
    """`%LOCALAPPDATA%\\Microsoft\\Power BI Desktop\\AnalysisServicesWorkspaces\\*\\Data`, as Desktop leaves it."""
    root = tmp_path / "local"
    for folder, port in ports.items():
        data = root / "Microsoft" / "Power BI Desktop" / "AnalysisServicesWorkspaces" / folder / "Data"
        data.mkdir(parents=True)
        (data / "msmdsrv.port.txt").write_bytes(str(port).encode("utf-16"))
    return str(root)


# --------------------------------------------------------------------------- #114 the one file


def test_agnostic_is_byte_identical_for_two_users_on_two_interpreters(tmp_path, monkeypatch, stable_launcher):
    become_user(monkeypatch, tmp_path, "alice", r"C:\Python312\python.exe")
    first = EXT.render_tool_text(EXT.render_tool_json())
    alice = EXT.package(out_dir=str(tmp_path / "alice-out"))

    become_user(monkeypatch, tmp_path, "bob", r"D:\venvs\reporting\Scripts\python.exe")
    second = EXT.render_tool_text(EXT.render_tool_json())
    bob = EXT.package(out_dir=str(tmp_path / "bob-out"))

    assert first == second
    assert alice["sha256"] == bob["sha256"]
    with open(alice["tool_json"], "rb") as a, open(bob["tool_json"], "rb") as b:
        assert a.read() == b.read()


def test_agnostic_shape_names_cmd_and_nothing_personal(stable_launcher):
    data = EXT.render_tool_json()
    assert data["path"] == EXT.system_cmd_exe() == r"C:\Windows\System32\cmd.exe"
    assert data["arguments"] == AGNOSTIC_ARGS
    assert data["name"] == "agentdata"
    assert data["iconData"].startswith("data:image/png;base64,")

    blob = json.dumps(data)
    assert "--project" not in blob
    assert EXT.sys.executable not in blob
    # Desktop substitutes %server% and %database%; every other %VAR% would reach cmd.exe unexpanded
    assert sorted(set(re.findall(r"%[A-Za-z]\w*%", blob))) == ["%database%", "%server%"]


def test_system_cmd_exe_follows_systemroot(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"D:\Windows")
    assert EXT.system_cmd_exe() == r"D:\Windows\System32\cmd.exe"


def test_launcher_python_py_and_override(monkeypatch):
    monkeypatch.setattr(EXT.shutil, "which", lambda n, *a, **k: "/usr/bin/python" if n == "python" else None)
    assert EXT.render_arguments() == AGNOSTIC_ARGS

    # py present, python absent: the file says `py`, and it is still nobody's interpreter path
    monkeypatch.setattr(EXT.shutil, "which", lambda n, *a, **k: r"C:\Windows\py.exe" if n == "py" else None)
    assert EXT.render_arguments() == '/c py -m agentdata pbip handoff --server "%server%" --database "%database%"'

    # neither: the file still ships, naming the launcher the fleet is measured to have
    monkeypatch.setattr(EXT.shutil, "which", lambda n, *a, **k: None)
    assert EXT.render_arguments().startswith("/c python -m agentdata")


def test_launcher_override_shim_carries_the_verb_itself(stable_launcher):
    # `--launcher` is the venv escape hatch: a .cmd on the user's own PATH that already knows both
    # its interpreter and the verb, so `-m agentdata` must NOT be appended to it
    args = EXT.render_arguments(launcher="agentdata-handoff")
    assert args == '/c agentdata-handoff --server "%server%" --database "%database%"'
    assert "-m agentdata" not in args

    # an interpreter, though, still needs the module
    quoted = EXT.render_arguments(launcher=r"D:\Program Files\Python312\python.exe")
    assert quoted == ('/c "D:\\Program Files\\Python312\\python.exe" -m agentdata pbip handoff '
                      '--server "%server%" --database "%database%"')


def test_launcher_with_percent_is_refused(stable_launcher):
    with pytest.raises(ValueError) as e:
        EXT.render_arguments(launcher=r"%LOCALAPPDATA%\agentdata\bin\agentdata-handoff.cmd")
    assert "cmd.exe expands" in str(e.value)


def test_console_flash_switch_is_documented_and_off(stable_launcher):
    assert EXT.render_arguments().startswith("/c python")
    assert EXT.MINIMIZED_PREFIX not in EXT.render_arguments()
    assert EXT.render_arguments(minimized=True).startswith('/c start "" /min python -m agentdata')


def test_direct_mode_is_still_the_old_shape(stable_launcher):
    data = EXT.render_tool_json(mode="direct", python_exe="C:/Python312/python.exe")
    assert data["path"] == "C:/Python312/python.exe"
    assert data["arguments"] == '-m agentdata pbip handoff --server "%server%" --database "%database%"'
    assert EXT.render_tool_json(python_exe="C:/Python312/python.exe")["path"] == "C:/Python312/python.exe"


def test_unknown_mode_says_which_modes_exist(stable_launcher):
    with pytest.raises(ValueError) as e:
        EXT.render_tool_json(mode="ribbon")
    assert "agnostic" in str(e.value) and "direct" in str(e.value)


def test_package_writes_both_files_and_a_request_it_can_act_on(tmp_path, stable_launcher):
    out = str(tmp_path / "pkg")
    res = EXT.package(out_dir=out)

    assert os.path.exists(res["tool_json"]) and os.path.basename(res["tool_json"]) == "agentdata.pbitool.json"
    assert os.path.exists(res["request"]) and os.path.basename(res["request"]) == "REQUEST.md"
    with open(res["tool_json"], encoding="utf-8") as f:
        assert json.load(f)["arguments"] == AGNOSTIC_ARGS

    with open(res["request"], encoding="utf-8") as f:
        req = f.read()
    # the real destination, spelled the way the person acting on it will paste it
    assert r"Microsoft Shared\Power BI Desktop\External Tools\agentdata.pbitool.json" in req
    assert res["destination"].endswith("External Tools/agentdata.pbitool.json")
    assert "identical for every user and every Python version" in req
    assert "cmd.exe" in req and "PATH" in req
    assert "Copy-Item -LiteralPath" in req and "Remove-Item -LiteralPath" in req
    assert res["sha256"] in req
    # a request nobody has evidence for must not appear
    assert "run elevated" not in req.lower()
    assert "administrator" in req.lower()      # naming who owns the folder is not the same thing


def test_register_tool_hint_points_at_the_package_not_at_elevation(tmp_path, monkeypatch, stable_launcher):
    monkeypatch.setattr(EXT.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
    ok, dest, hint = EXT.register_tool(target_dir=str(tmp_path / "ext"))
    assert ok is False and dest.endswith("agentdata.pbitool.json")
    assert "--package" in hint and "Copy-Item" in hint
    assert "run elevated" not in hint.lower()


def test_handoff_pointer_is_where_the_project_went(tmp_path, monkeypatch):
    local = tmp_path / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert EXT.handoff_pointer_path().replace("\\", "/").endswith("agentdata/pbi-handoff.json")
    assert EXT.read_handoff_pointer() is None

    proj = tmp_path / "repo"
    proj.mkdir()
    p = local / "agentdata" / "pbi-handoff.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"project": str(proj), "argv": ["ad-pbip", "handoff"]}), encoding="utf-8")
    assert EXT.read_handoff_pointer()["project"] == str(proj)

    # the ribbon file names no project, so a click for a file in no known project lands here
    res = EXT.handoff(server="localhost:54321", database="db-guid", run=lambda *a, **k: (1, "", ""))
    assert os.path.abspath(res["project"]) == os.path.abspath(str(proj))
    assert os.path.exists(os.path.join(str(proj), ".agent", "desktop.json"))


# ---------------------------------------------------------------------- #115 the TE2 custom action


def test_te2_script_argument_string_survives_its_quotes():
    src = EXT.render_te2_script("process")
    m = re.search(r'var arguments = (?P<expr>.+?);\s*$', src, re.M)
    assert m, "the process body must build the argument string in one expression"

    values = {"Model.Database.ServerName": "localhost:54321",
              "Model.Database.Name": "b1e2c3d4-0000-4444-8888-999999999999"}
    parts = []
    for piece in re.split(r"\s\+\s", m.group("expr")):
        piece = piece.strip()
        if piece.startswith('"') and piece.endswith('"'):
            parts.append(piece[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            parts.append(values[piece])
    assert "".join(parts) == ('-m agentdata pbip handoff --server "localhost:54321" '
                              '--database "b1e2c3d4-0000-4444-8888-999999999999"')


def test_te2_script_launches_the_approved_python(stable_launcher):
    src = EXT.render_te2_script("process")
    assert "System.Diagnostics.Process.Start" in src
    assert 'ProcessStartInfo("python"' in src
    assert "{{launcher}}" not in src
    assert 'ProcessStartInfo("agentdata-handoff"' in EXT.render_te2_script("process", launcher="agentdata-handoff")


def test_te2_launcher_path_is_escaped_for_the_c_sharp_literal(stable_launcher):
    # a venv path lands inside a C# string, where \v and \S are not separators but invalid escapes
    src = EXT.render_te2_script("process", launcher=r"C:\venv\Scripts\python.exe")
    assert r'ProcessStartInfo("C:\\venv\\Scripts\\python.exe"' in src


def test_te2_fallback_body_uses_the_rule_desktop_already_uses():
    src = EXT.render_te2_script("file")
    assert "msmdsrv.port.txt" in src and "AnalysisServicesWorkspaces" in src
    assert "System.Text.Encoding.Unicode" in src          # the port file is UTF-16
    assert "pbi-handoff.json" in src                      # where the project comes from
    assert "te2:local" in src
    assert "database_source" in src
    assert "Process.Start" not in src                     # the whole point of the fallback


def test_te2_unknown_mode_names_the_two():
    with pytest.raises(ValueError) as e:
        EXT.render_te2_script("magic")
    assert "process" in str(e.value) and "file" in str(e.value)


def test_te2_custom_action_payload(stable_launcher):
    action = EXT.te2_custom_action()
    assert action["Name"] == EXT.TE2_ACTION_NAME == "Hand off to agentdata"
    assert action["ValidContexts"] == "Model"
    assert action["Enabled"] is True
    assert "pbip handoff" in action["Execute"]


def test_custom_actions_path_is_per_user(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert EXT.custom_actions_path().replace("\\", "/").endswith("TabularEditor/CustomActions.json")


def test_merge_keeps_other_actions_and_replaces_ours_by_name(tmp_path, stable_launcher):
    path = str(tmp_path / "CustomActions.json")
    theirs = {"Name": "Deploy to test", "Enabled": True, "Execute": "Info(\"mine\");", "ValidContexts": "Model"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump([theirs, {"Name": EXT.TE2_ACTION_NAME, "Execute": "old body", "ValidContexts": "Table"}], f)

    res = EXT.merge_custom_action(EXT.te2_custom_action(), path=path)
    assert res["ok"] is True and res["changed"] == "replaced" and res["count"] == 2

    with open(path, encoding="utf-8") as f:
        actions = json.load(f)
    assert actions[0] == theirs                                    # untouched, and still first
    assert actions[1]["ValidContexts"] == "Model"
    assert "pbip handoff" in actions[1]["Execute"]

    # a second run changes nothing at all
    again = EXT.merge_custom_action(EXT.te2_custom_action(), path=path)
    assert again["changed"] == "unchanged"


def test_merge_into_a_missing_file_creates_one_action(tmp_path, stable_launcher):
    path = str(tmp_path / "sub" / "CustomActions.json")
    res = EXT.merge_custom_action(EXT.te2_custom_action(), path=path)
    assert res["changed"] == "added" and res["count"] == 1
    with open(path, encoding="utf-8") as f:
        assert [a["Name"] for a in json.load(f)] == [EXT.TE2_ACTION_NAME]


def test_merge_refuses_a_malformed_file_rather_than_rewriting_it(tmp_path, stable_launcher):
    path = str(tmp_path / "CustomActions.json")
    broken = '[{"Name": "Deploy to test", "Execute": "Info(\\"mine\\");",}]'   # trailing comma
    with open(path, "w", encoding="utf-8") as f:
        f.write(broken)

    res = EXT.merge_custom_action(EXT.te2_custom_action(), path=path)
    assert res["ok"] is False and res["changed"] == "refused"
    assert "custom action" in res["hint"]
    with open(path, encoding="utf-8") as f:
        assert f.read() == broken          # every byte of their work still there

    rm = EXT.remove_custom_action(path=path)
    assert rm["ok"] is False and rm["changed"] == "refused"


def test_remove_takes_out_only_ours(tmp_path, stable_launcher):
    path = str(tmp_path / "CustomActions.json")
    theirs = {"Name": "Deploy to test", "Execute": "Info(\"mine\");"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump([theirs, EXT.te2_custom_action()], f)

    res = EXT.remove_custom_action(path=path)
    assert res["ok"] is True and res["changed"] == "removed" and res["count"] == 1
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == [theirs]

    assert EXT.remove_custom_action(path=path)["changed"] == "absent"
    assert EXT.remove_custom_action(path=str(tmp_path / "nothing.json"))["changed"] == "absent"


def test_merge_preserves_an_envelope_shape(tmp_path, stable_launcher):
    path = str(tmp_path / "CustomActions.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"Version": 2, "Actions": [{"Name": "Deploy to test"}]}, f)

    assert EXT.merge_custom_action(EXT.te2_custom_action(), path=path)["changed"] == "added"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["Version"] == 2
    assert [a["Name"] for a in data["Actions"]] == ["Deploy to test", EXT.TE2_ACTION_NAME]


def test_resolve_workspace_matches_the_port_a_te2_connection_reports(tmp_path):
    root = workspace_tree(tmp_path, {"AnalysisServicesWorkspace_aaa": 54321,
                                     "AnalysisServicesWorkspace_bbb": 60111})

    hit = EXT.resolve_workspace("localhost:60111", root=root)
    assert hit["port"] == 60111
    assert hit["workspace_name"] == "AnalysisServicesWorkspace_bbb"
    assert hit["workspace_dir"].endswith("AnalysisServicesWorkspace_bbb/Data")
    # the port file names the port and nothing else, so the pid is honestly unknown here
    assert hit["pid"] is None and hit["file"] is None

    assert EXT.resolve_workspace("localhost:54321", root=root)["workspace_name"] == "AnalysisServicesWorkspace_aaa"
    assert EXT.resolve_workspace("localhost:1", root=root) is None


def test_resolve_workspace_reads_localappdata_by_default(tmp_path, monkeypatch):
    root = workspace_tree(tmp_path, {"AnalysisServicesWorkspace_ccc": 12345})
    monkeypatch.setenv("LOCALAPPDATA", root)
    assert EXT.resolve_workspace("localhost:12345")["port"] == 12345
