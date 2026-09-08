r"""The handoff without the ribbon: which window, which catalog, and which transport said so.

Everything here runs on Linux CI through the same injected seams the rest of `desktop.py` uses -- a
`Runner` that answers the two PowerShell scripts `discover()` sends, a fake filesystem tree holding
`msmdsrv.port.txt`, and a monkeypatched `dmv.catalogs`. Two of those seams carry the whole point of
#116, so they are worth naming:

* **The window rows are the Z-order.** On Windows `EnumWindows` returns top-level windows top-first;
  off Windows `winui._from_runner` preserves the order the runner gave. So `zorder=[...]` in these
  fakes *is* "which window the human clicked last", and a test can move the top window without
  touching anything else.
* **A refusal is a result.** With two documents open and no flag the wanted behaviour is an error
  with both names in it, not a handoff to whichever instance the process table happened to list
  first -- so the assertions are on the hint text a human reads, not only on `ok`.

The capability ladder (#117.1) is exercised on real temporary folders. The one thing a Linux CI
cannot produce is the `PermissionError` a managed laptop gives for `%CommonProgramFiles%` -- this
container runs as root, where `chmod 0500` means nothing -- so that one case injects the failure at
`desktop._probe_write`, which exists for exactly that reason. Every other case is a real create,
a real delete, and a real assertion that nothing was left behind.
"""
import json
import os

import pytest

from agentdata.pbip import desktop as DT
from agentdata.pbip import dmv as DMV
from agentdata.pbip import external_tool as ET

TITLE_A = "Sales - Power BI Desktop"
TITLE_B = "Costs - Power BI Desktop"


# --------------------------------------------------------------------------------- the fake machine


def make_ws(tmp_path, name: str, port: int) -> str:
    """One Desktop workspace folder: the UTF-16 `msmdsrv.port.txt` `read_port()` looks for."""
    ws = tmp_path / "workspaces" / name / "Data"
    ws.mkdir(parents=True)
    (ws / "msmdsrv.port.txt").write_bytes(str(port).encode("utf-16"))
    return str(ws)


def fake_machine(instances, zorder=None, registry=None):
    """A Runner answering `discover()`'s two scripts, plus registry reads for the kill-switch.

    `instances` is `[{"pid", "ws", "title"}]` in process-table order; `zorder` is the list of pids
    in window order (default: the same), which is the seam that stands in for `EnumWindows`.
    `registry` maps a substring of the key path to the JSON PowerShell would print for it.
    """
    order = list(zorder) if zorder is not None else [i["pid"] for i in instances]
    by_pid = {i["pid"]: i for i in instances}

    def run(args, timeout=30):
        script = args[-1]
        if "msmdsrv.exe" in script:
            return 0, json.dumps([
                {"ProcessId": 9000 + n, "ParentProcessId": inst["pid"],
                 "CommandLine": f'"C:\\PBI\\msmdsrv.exe" -s "{inst["ws"]}" -n "AnalysisServicesWorkspace_{n}" -c 1'}
                for n, inst in enumerate(instances)]), ""
        if "PBIDesktop" in script:
            return 0, json.dumps([
                {"Id": pid, "MainWindowTitle": by_pid[pid]["title"],
                 "Path": "C:\\Program Files\\Microsoft Power BI Desktop\\bin\\PBIDesktop.exe",
                 "Version": "2.138.1004.0"} for pid in order]), ""
        if "Get-ItemProperty" in script:
            for fragment, payload in (registry or {}).items():
                if fragment in script:
                    return 0, json.dumps(payload), ""
            return 0, "", ""
        return 0, "", ""

    return run


def one_instance(tmp_path, title=TITLE_A, pid=1111, port=54321):
    ws = make_ws(tmp_path, "guid-a", port)
    return fake_machine([{"pid": pid, "ws": ws, "title": title}])


def two_instances(tmp_path, zorder=None):
    ws_a = make_ws(tmp_path, "guid-a", 54321)
    ws_b = make_ws(tmp_path, "guid-b", 54322)
    return fake_machine([{"pid": 1111, "ws": ws_a, "title": TITLE_A},
                         {"pid": 2222, "ws": ws_b, "title": TITLE_B}], zorder=zorder)


@pytest.fixture
def catalog(monkeypatch):
    """Replace `dmv.catalogs` with a stub; `calls` records what the transport asked it."""
    calls = []

    def install(names):
        def fake(server, dscmd_exe=None, te2_exe=None, run=None):
            calls.append(server)
            return list(names)
        monkeypatch.setattr(DMV, "catalogs", fake)
        return calls

    return install


# ------------------------------------------------------------------------------ windows_zorder


def test_windows_zorder_is_the_wrapper_and_keeps_the_order(tmp_path):
    run = two_instances(tmp_path, zorder=[2222, 1111])
    assert DT.windows_zorder(run=run) == [(2222, TITLE_B), (1111, TITLE_A)]


def test_windows_zorder_ignores_a_window_that_only_mentions_desktop(tmp_path):
    ws = make_ws(tmp_path, "guid-a", 54321)
    run = fake_machine([{"pid": 1111, "ws": ws, "title": TITLE_A},
                        {"pid": 7777, "ws": ws, "title": "Power BI Desktop documentation - Google Chrome"}])
    assert DT.windows_zorder(run=run) == [(1111, TITLE_A)]


# ------------------------------------------------------------------------- the transport gate


def test_active_takes_the_window_on_top(tmp_path):
    run = two_instances(tmp_path, zorder=[2222, 1111])
    res = DT.resolve_transport(active=True, run=run)
    assert res["ok"] is True
    assert res["transport"] == "zorder"
    assert res["pid"] == 2222
    assert res["server"] == "localhost:54322"
    assert TITLE_B in res["why"]


def test_active_follows_the_window_the_human_touched_last(tmp_path):
    """The same machine, a different click: only the window order moves."""
    assert DT.resolve_transport(active=True, run=two_instances(tmp_path, zorder=[1111, 2222]))["pid"] == 1111


def test_active_with_no_window_refuses(tmp_path):
    res = DT.resolve_transport(active=True, run=fake_machine([]))
    assert res["ok"] is False and res["fail"] == "no_window"
    assert "click its window" in res["hint"]


def test_active_when_the_top_window_has_no_analysis_services_yet(tmp_path):
    ws = make_ws(tmp_path, "guid-a", 54321)
    run = fake_machine([{"pid": 1111, "ws": ws, "title": TITLE_A}], zorder=[1111])

    def half_loaded(args, timeout=30):
        if "msmdsrv.exe" in args[-1]:
            return 0, "", ""          # the window is up, its server is not
        return run(args, timeout)

    res = DT.resolve_transport(active=True, run=half_loaded)
    assert res["ok"] is False and res["fail"] == "no_instance"
    assert "still loading" in res["hint"] or "finish loading" in res["hint"]


def test_file_picks_the_named_document(tmp_path):
    res = DT.resolve_transport(file="Costs", run=two_instances(tmp_path))
    assert res["ok"] is True
    assert res["transport"] == "file"
    assert res["pid"] == 2222


def test_file_that_matches_nothing_refuses_and_lists_what_is_open(tmp_path):
    res = DT.resolve_transport(file="Margins", run=two_instances(tmp_path))
    assert res["ok"] is False and res["fail"] == "no_match"
    assert "Sales" in res["hint"] and "Costs" in res["hint"]


def test_one_instance_and_no_flags_uses_it_and_says_so(tmp_path):
    res = DT.resolve_transport(run=one_instance(tmp_path))
    assert res["ok"] is True
    assert res["transport"] == "file"
    assert res["pid"] == 1111
    assert "only Power BI Desktop instance" in res["why"]


def test_two_instances_and_no_flags_refuse_with_the_list_and_both_flags(tmp_path):
    res = DT.resolve_transport(run=two_instances(tmp_path, zorder=[2222, 1111]))
    assert res["ok"] is False and res["fail"] == "ambiguous"
    hint = res["hint"]
    assert "--active" in hint and "--file" in hint
    assert "Sales" in hint and "Costs" in hint
    assert "pid 1111" in hint and "pid 2222" in hint
    # the list is Z-ordered, so the window on top is the first thing a human reads
    assert [c["pid"] for c in res["choices"]] == [2222, 1111]
    assert res["choices"][0]["zorder"] == 0


def test_no_instance_at_all_refuses(tmp_path):
    res = DT.resolve_transport(run=fake_machine([]))
    assert res["ok"] is False and res["fail"] == "no_instance"
    assert "ad-pbip launch" in res["hint"]


def test_a_document_whose_port_file_is_missing_refuses_instead_of_guessing(tmp_path):
    ws = str(tmp_path / "workspaces" / "gone" / "Data")
    run = fake_machine([{"pid": 1111, "ws": ws, "title": TITLE_A}])
    res = DT.resolve_transport(run=run)
    assert res["ok"] is False and res["fail"] == "no_port"


# --------------------------------------------------------------------------- %database% from the DMV


def test_database_comes_from_the_dmv_catalog(tmp_path, catalog):
    calls = catalog(["a1b2c3d4-0000-1111-2222-333344445555"])
    database, source = DT.resolve_database("localhost:54321")
    assert database == "a1b2c3d4-0000-1111-2222-333344445555"
    assert source == "dmv"
    assert calls == ["localhost:54321"]


def test_no_executor_means_an_empty_database_and_not_a_failure(catalog):
    catalog([])
    assert DT.resolve_database("localhost:54321") == ("", "none")


def test_handoff_records_transport_and_database_source(tmp_path, catalog, capsys):
    catalog(["guid-of-the-open-model"])
    project = tmp_path / "project"
    project.mkdir()
    res = DT.handoff(active=True, project_dir=str(project), run=two_instances(tmp_path, zorder=[2222, 1111]))

    assert res["ok"] is True
    assert res["transport"] == "zorder"
    assert res["database_source"] == "dmv"
    assert res["database"] == "guid-of-the-open-model"
    assert res["server"] == "localhost:54322"

    written = json.loads((project / ".agent" / "desktop.json").read_text(encoding="utf-8"))
    assert written["transport"] == "zorder"
    assert written["database_source"] == "dmv"
    assert written["server"] == "localhost:54322"
    assert written["database"] == "guid-of-the-open-model"
    assert capsys.readouterr().err == ""


def test_handoff_without_an_executor_warns_exactly_once(tmp_path, catalog, capsys):
    catalog([])
    project = tmp_path / "project"
    project.mkdir()
    res = DT.handoff(project_dir=str(project), run=one_instance(tmp_path))

    assert res["ok"] is True
    assert res["transport"] == "file"
    assert res["database"] == ""
    assert res["database_source"] == "none"
    warn_lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(warn_lines) == 1
    assert "database_source: none" in warn_lines[0]

    written = json.loads((project / ".agent" / "desktop.json").read_text(encoding="utf-8"))
    assert written["database"] == ""
    assert written["database_source"] == "none"


def test_handoff_refuses_before_it_writes_anything(tmp_path, catalog):
    catalog(["guid"])
    project = tmp_path / "project"
    project.mkdir()
    res = DT.handoff(project_dir=str(project), run=two_instances(tmp_path))
    assert res["ok"] is False and res["fail"] == "ambiguous"
    assert not (project / ".agent" / "desktop.json").exists()


# -------------------------------------------------------------------- the file stays backwards-readable


def test_a_desktop_json_written_before_the_new_fields_still_reads(tmp_path):
    """`.agent/desktop.json` gained two keys and lost none: yesterday's file is still a handoff."""
    agent = tmp_path / ".agent"
    agent.mkdir()
    (agent / "desktop.json").write_text(json.dumps({
        "server": "localhost:54321",
        "database": "guid",
        "pid": None,
        "file": None,
        "handed_off_at": "2026-09-08T09:00:00+00:00",
    }), encoding="utf-8")

    data = ET.read_handoff(project_dir=str(tmp_path))
    assert data is not None
    assert data["server"] == "localhost:54321"
    assert "transport" not in data
    assert data.get("database_source") is None


def test_a_desktop_json_the_transport_wrote_reads_the_same_way(tmp_path, catalog, monkeypatch):
    catalog(["guid"])
    project = tmp_path / "project"
    project.mkdir()
    DT.handoff(project_dir=str(project), run=one_instance(tmp_path))
    monkeypatch.setattr(ET, "is_pid_alive", lambda pid: True)  # the fake machine's pid 1111 is not this box's
    data = ET.read_handoff(project_dir=str(project))
    assert data is not None
    assert data["server"] == "localhost:54321"
    assert data["transport"] == "file"
    assert data["database_source"] == "dmv"


# ----------------------------------------------------------------------------- the capability ladder


POLICY_OFF = {"Policies": {"EnableExternalTools": 0}}
PRODUCT_OFF = {"Microsoft Power BI Desktop": {"EnableExternalTools": 0}}


def ext_tools_dir(tmp_path, registered=False):
    d = tmp_path / "Common Files" / "Microsoft Shared" / "Power BI Desktop" / "External Tools"
    d.mkdir(parents=True)
    if registered:
        (d / ET.TOOL_FILENAME).write_text(json.dumps(ET.render_tool_json()), encoding="utf-8")
    return str(d)


def te2_here(tmp_path, action=True, malformed=False):
    """(te2_exe, actions_path) for a machine with Tabular Editor 2 under `C:\\Enforce`."""
    exe = tmp_path / "Enforce" / "TabularEditor.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")
    actions = tmp_path / "TabularEditor" / "CustomActions.json"
    actions.parent.mkdir(parents=True, exist_ok=True)
    if malformed:
        actions.write_text("{ not json", encoding="utf-8")
    elif action:
        actions.write_text(json.dumps([{"Name": "Someone else's action"},
                                       ET.te2_custom_action()]), encoding="utf-8")
    else:
        actions.write_text(json.dumps([{"Name": "Someone else's action"}]), encoding="utf-8")
    return str(exe), str(actions)


NO_TE2 = "C:/nowhere/TabularEditor.exe"


def test_the_killswitch_is_read_in_the_policy_key_of_both_hives(tmp_path):
    for payload in ({"Policies": {"EnableExternalTools": 0}}, {"Microsoft Power BI Desktop": {"EnableExternalTools": 0}}):
        run = fake_machine([], registry=payload)
        enabled, why = DT.external_tools_killswitch(run=run)
        assert enabled is False
        assert "EnableExternalTools=0" in why
    enabled, why = DT.external_tools_killswitch(run=fake_machine([]))
    assert enabled is True


def test_ribbon_registered_when_our_file_is_there(tmp_path):
    state = DT.ribbon_state(ext_dir=ext_tools_dir(tmp_path, registered=True), run=fake_machine([]))
    assert state["state"] == DT.RIBBON_REGISTERED
    assert ET.TOOL_FILENAME in state["evidence"]


def test_ribbon_writable_probes_and_leaves_nothing_behind(tmp_path):
    d = ext_tools_dir(tmp_path)
    state = DT.ribbon_state(ext_dir=d, run=fake_machine([]))
    assert state["state"] == DT.RIBBON_WRITABLE
    assert state["writable"] is True
    assert os.listdir(d) == []


def test_ribbon_needs_it_file_when_the_probe_cannot_be_created(tmp_path, monkeypatch):
    """The managed laptop's answer: the failure to create the probe IS the answer, and it is final."""
    d = ext_tools_dir(tmp_path)
    attempts = []

    def denied(path):
        attempts.append(path)
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(DT, "_probe_write", denied)
    state = DT.ribbon_state(ext_dir=d, run=fake_machine([]))
    assert state["state"] == DT.RIBBON_NEEDS_IT
    assert state["writable"] is False
    assert "register-tool --package" in state["evidence"]
    assert len(attempts) == 1                     # never retried
    assert os.listdir(d) == []                    # never left behind


def test_ribbon_needs_it_file_when_the_folder_is_not_there_at_all(tmp_path):
    state = DT.ribbon_state(ext_dir=str(tmp_path / "no" / "such" / "folder"), run=fake_machine([]))
    assert state["state"] == DT.RIBBON_NEEDS_IT
    assert state["writable"] is False
    assert "does not exist" in state["evidence"]


def test_ribbon_disabled_by_policy_does_not_touch_the_folder(tmp_path):
    d = ext_tools_dir(tmp_path, registered=True)
    state = DT.ribbon_state(ext_dir=d, run=fake_machine([], registry=POLICY_OFF))
    assert state["state"] == DT.RIBBON_DISABLED
    assert state["writable"] is None
    assert os.listdir(d) == [ET.TOOL_FILENAME]


def test_te2_action_state_needs_both_halves(tmp_path):
    exe, actions = te2_here(tmp_path, action=True)
    installed = DT.te2_action_state(te2_exe=exe, actions_path=actions)
    assert installed["present"] is True and installed["installed"] is True

    exe2, actions2 = te2_here(tmp_path / "b", action=False)
    without = DT.te2_action_state(te2_exe=exe2, actions_path=actions2)
    assert without["present"] is True and without["installed"] is False
    assert "register-tool --te2" in without["evidence"]

    absent = DT.te2_action_state(te2_exe=NO_TE2, actions_path=actions)
    assert absent["present"] is False and absent["installed"] is False


def test_a_malformed_custom_actions_file_is_not_installed_and_is_not_rewritten(tmp_path):
    exe, actions = te2_here(tmp_path, malformed=True)
    before = open(actions, encoding="utf-8").read()
    state = DT.te2_action_state(te2_exe=exe, actions_path=actions)
    assert state["installed"] is False
    assert "does not parse" in state["evidence"]
    assert open(actions, encoding="utf-8").read() == before


@pytest.mark.parametrize(
    "registered,te2,action,killswitch,windows,via,ribbon,available",
    [
        # our file on the ribbon wins, whatever else is installed
        (True,  True,  True,  False, True,  "ribbon:machine", DT.RIBBON_REGISTERED, True),
        (True,  False, False, False, False, "ribbon:machine", DT.RIBBON_REGISTERED, True),
        # no ribbon file: TE2 with our action is the next rung
        (False, True,  True,  False, True,  "te2:local",      DT.RIBBON_WRITABLE,   True),
        (False, True,  True,  False, False, "te2:local",      DT.RIBBON_WRITABLE,   True),
        # TE2 present but our action is not in it: that is an install step, not a transport
        (False, True,  False, False, True,  "zorder",         DT.RIBBON_WRITABLE,   True),
        # nothing installed at all: the Z-order transport needs nothing and nobody
        (False, False, False, False, True,  "zorder",         DT.RIBBON_WRITABLE,   True),
        # the kill-switch turns off a button, not the handoff
        (True,  False, False, True,  True,  "zorder",         DT.RIBBON_DISABLED,   True),
        (False, True,  True,  True,  True,  "te2:local",      DT.RIBBON_DISABLED,   True),
        # no window, no Windows, nothing installed: the honest answer is that there is no transport
        (False, False, False, False, False, "none",           DT.RIBBON_WRITABLE,   False),
    ],
)
def test_the_transport_ladder(tmp_path, registered, te2, action, killswitch, windows, via, ribbon, available):
    ext_dir = ext_tools_dir(tmp_path, registered=registered)
    if te2:
        exe, actions = te2_here(tmp_path, action=action)
    else:
        exe, actions = NO_TE2, str(tmp_path / "TabularEditor" / "CustomActions.json")
    run = (one_instance(tmp_path) if windows else fake_machine([]))
    if killswitch:
        base = run

        def run(args, timeout=30, _base=base):  # noqa: F811 - the same machine, policy applied
            if "Get-ItemProperty" in args[-1] and "Policies" in args[-1]:
                return 0, json.dumps({"EnableExternalTools": 0}), ""
            return _base(args, timeout)

    row = DT.external_tools_row(run=run, ext_dir=ext_dir, actions_path=actions, te2_exe=exe)
    assert row["capability"] == "external_tools"
    assert row["via"] == via
    assert row["ribbon"] == ribbon
    assert row["available"] is available
    assert row["evidence"]
    assert ET.TOOL_FILENAME in os.listdir(ext_dir) or not registered
    assert DT.EXT_PROBE_FILENAME not in os.listdir(ext_dir)


def test_capabilities_still_has_its_nine_rows_and_the_row_gained_the_ribbon(tmp_path):
    run = one_instance(tmp_path)
    caps = DT.capabilities(pid=1111, run=run)
    assert [c["capability"] for c in caps] == [
        "as_port", "xmla_local", "external_tools", "uia", "printwindow",
        "bridge_pipe", "bridge_manifest", "developer_visual", "pbiviz"]
    row = next(c for c in caps if c["capability"] == "external_tools")
    assert set(row) == {"capability", "available", "via", "ribbon", "evidence"}
    assert row["available"] is True
    assert row["via"] == "zorder"
    assert TITLE_A in row["evidence"]
