r"""The operator's three verbs of epic #112: `handoff`, `register-tool`, `probe`.

These are the commands a person actually types on the laptop the epic measured, so what is asserted
here is mostly *what they print*. That is not a stylistic preference. Three of the four transports
exist because the ribbon costs a privileged write nobody there can perform, and the whole value of
the work leaks away if the CLI still tells that person to elevate, still guesses which of two
Desktop windows they meant, or still says "registered" about a file it only wrote to a temp folder.

Every test runs on Linux CI through the seams the rest of the Power BI code already uses:

* `DT.default_run` -- one fake `Runner` answering the two PowerShell scripts `discover()` sends and
  the registry reads, driving `status()` and `windows_zorder()` at once, exactly as it does in
  `tests/test_handoff_transports.py`. Off Windows `winui` falls back to the process table, which has
  no Z-order of its own, so the order the fake lists pids in *is* the Z-order under test.
* `DMV.catalogs` -- a stub, because `%database%` comes from a DMV over `localhost:<port>` and there
  is no Analysis Services here.
* `CommonProgramFiles` and `LOCALAPPDATA` -- real temporary folders, so the External Tools write and
  the Tabular Editor custom action are real file operations against real JSON.
* `DT._probe_write` -- injected failure. This container runs as root, where no `chmod` produces the
  `PermissionError` a managed laptop gives for `%CommonProgramFiles%`; that seam exists so the
  refusal path is exercised rather than imagined.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata.cli_pbip import build_parser
from agentdata.pbip import desktop as DT
from agentdata.pbip import dmv as DMV
from agentdata.pbip import external_tool as ET
from agentdata.pbip import probe as PRB

TITLE_A = "Sales - Power BI Desktop"
TITLE_B = "Costs - Power BI Desktop"
# The sentence #112 forbids unless an elevation avenue was actually detected, and the near-misses
# that mean the same thing to the person reading them.
ELEVATION_WORDS = ("elevat", "administrator privileges", "as administrator", "run as admin")


# --------------------------------------------------------------------------------- the fake machine


def run_cli(capsys, *argv: str) -> tuple[int, str, str]:
    """Parse through the real register and dispatch, so the flags under test are the shipped ones."""
    ns = build_parser().parse_args(list(argv))
    rc = ns.fn(ns)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def make_ws(tmp_path, name: str, port: int) -> str:
    """One Desktop workspace folder: the UTF-16 `msmdsrv.port.txt` `read_port()` looks for."""
    ws = tmp_path / "workspaces" / name / "Data"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "msmdsrv.port.txt").write_bytes(str(port).encode("utf-16"))
    return str(ws)


def fake_machine(instances: list[dict], zorder: list[int] | None = None):
    """A Runner answering `discover()`'s two scripts. `zorder` is the window order, top first."""
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
        return 0, "", ""

    return run


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """Install a fake Desktop machine and a fake catalog; return the project folder to hand off into.

    `DT.default_run` is the one seam: `status()` and `windows_zorder()` both reach for it when no
    runner is passed, which is exactly what the CLI does.
    """
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    # `discover()` falls back to globbing %LOCALAPPDATA% when the process table is empty, and
    # `_click_transport` looks for the custom action there: point both at a folder that is not.
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    def install(instances, zorder=None, catalogs=("workspace-guid",)):
        monkeypatch.setattr(DT, "default_run", fake_machine(instances, zorder=zorder))
        monkeypatch.setattr(DMV, "catalogs", lambda server, **kw: list(catalogs))
        return str(project)

    return install


def one_instance(tmp_path, title=TITLE_A, pid=1111, port=54321) -> list[dict]:
    return [{"pid": pid, "ws": make_ws(tmp_path, "guid-a", port), "title": title}]


def two_instances(tmp_path) -> list[dict]:
    return [{"pid": 1111, "ws": make_ws(tmp_path, "guid-a", 54321), "title": TITLE_A},
            {"pid": 2222, "ws": make_ws(tmp_path, "guid-b", 54322), "title": TITLE_B}]


def written(project: str) -> dict:
    with open(os.path.join(project, ".agent", "desktop.json"), encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------------------- ad-pbip handoff


def test_one_open_instance_is_used_and_said(machine, tmp_path, capsys):
    """No flags and one document open: there is nothing to disambiguate, so it just works -- and
    `why` says which document it picked rather than leaving the human to assume."""
    project = machine(one_instance(tmp_path))
    rc, out, _err = run_cli(capsys, "handoff", "--project", project)

    assert rc == 0
    assert "ok: true" in out
    assert "transport: file" in out
    assert "database_source: dmv" in out
    assert "localhost:54321" in out
    assert TITLE_A in out                       # `why`: the only instance running, named
    assert written(project)["transport"] == "file"
    assert written(project)["database"] == "workspace-guid"


def test_two_instances_and_no_flag_is_a_refusal_that_prints_both_and_both_flags(machine, tmp_path, capsys):
    """#41's gate. A handoff writes a server address twenty later commands trust without
    re-checking, so picking the wrong window is a wrong answer all afternoon, not once."""
    project = machine(two_instances(tmp_path))
    rc, out, _err = run_cli(capsys, "handoff", "--project", project)

    assert rc == 2
    assert "ok: false" in out
    assert "ambiguous" in out
    assert TITLE_A in out and TITLE_B in out
    assert "--active" in out and "--file" in out
    assert "zorder" in out                      # the list is ordered, and says so
    assert not os.path.exists(os.path.join(project, ".agent", "desktop.json"))


def test_active_follows_the_window_the_human_touched_last(machine, tmp_path, capsys):
    """`--active` is `windows_zorder()[0]`: move the top window and the handoff moves with it."""
    project = machine(two_instances(tmp_path), zorder=[2222, 1111])
    rc, out, _err = run_cli(capsys, "handoff", "--active", "--project", project)

    assert rc == 0
    assert "transport: zorder" in out
    assert "localhost:54322" in out
    assert written(project)["pid"] == 2222

    machine(two_instances(tmp_path), zorder=[1111, 2222])
    rc, out, _err = run_cli(capsys, "handoff", "--active", "--project", project)
    assert rc == 0 and "localhost:54321" in out
    assert written(project)["pid"] == 1111


def test_file_names_the_document_without_switching_windows(machine, tmp_path, capsys):
    project = machine(two_instances(tmp_path))
    rc, out, _err = run_cli(capsys, "handoff", "--file", "Costs", "--project", project)

    assert rc == 0
    assert "transport: file" in out
    assert written(project)["server"] == "localhost:54322"


def test_a_file_that_matches_nothing_lists_what_is_open(machine, tmp_path, capsys):
    project = machine(two_instances(tmp_path))
    rc, out, _err = run_cli(capsys, "handoff", "--file", "Margins", "--project", project)

    assert rc == 2
    assert "no_match" in out
    assert TITLE_A in out and TITLE_B in out


def test_nothing_open_is_a_refusal_with_nothing_to_hand_off(machine, tmp_path, capsys):
    """Distinct exit code from the ambiguous case: the human cannot pick from an empty list, so
    this is a state to fix (open the report), not a question to answer."""
    project = machine([])
    rc, out, _err = run_cli(capsys, "handoff", "--active", "--project", project)

    assert rc == 1
    assert "no_window" in out
    assert "open the report" in out


def test_an_unreadable_catalog_is_a_warning_and_still_a_handoff(machine, tmp_path, capsys):
    """`database` is optional; a missing one must not cost the server address. The warn goes to
    stderr so a caller piping the TOON block still gets clean TOON."""
    project = machine(one_instance(tmp_path), catalogs=())
    rc, out, err = run_cli(capsys, "handoff", "--project", project)

    assert rc == 0
    assert "database_source: none" in out
    assert "dscmd" in err and "te2_exe" in err
    assert written(project)["database"] == ""


def test_the_two_directions_cannot_be_mixed(machine, tmp_path, capsys):
    """`--active` resolves the instance here; `--server` is what Desktop substituted there. Asking
    for both is a question with two answers, so it is refused rather than silently ranked."""
    project = machine(one_instance(tmp_path))
    rc, out, _err = run_cli(capsys, "handoff", "--active", "--server", "localhost:1", "--project", project)

    assert rc == 2
    assert "ok: false" in out
    assert not os.path.exists(os.path.join(project, ".agent", "desktop.json"))


def test_a_database_with_no_server_is_a_refusal(machine, tmp_path, capsys):
    project = machine(one_instance(tmp_path))
    rc, out, _err = run_cli(capsys, "handoff", "--database", "guid", "--project", project)

    assert rc == 2 and "--database without --server" in out


# ------------------------------------------------------- the click path: the ribbon and TE2 action


def test_the_click_path_still_writes_what_the_ribbon_always_wrote(machine, tmp_path, capsys):
    """`--server`/`--database` are Desktop's two substitutes. Nothing is resolved, nothing is
    probed, and the file the ribbon has always produced is the file that appears."""
    project = machine(one_instance(tmp_path))
    rc, out, _err = run_cli(capsys, "handoff", "--server", "localhost:54321",
                            "--database", "abc-guid", "--project", project)

    assert rc == 0
    assert "ok: true" in out
    data = written(project)
    assert data["server"] == "localhost:54321" and data["database"] == "abc-guid"


def test_a_click_labels_itself_from_what_is_installed_not_from_a_flag(machine, tmp_path, monkeypatch, capsys):
    """The ribbon and the Tabular Editor action launch the same command line, so the transport is
    read off the machine: the machine file is there, therefore the ribbon is what pressed it."""
    project = machine(one_instance(tmp_path))
    ext = tmp_path / "Common Files" / "Microsoft Shared" / "Power BI Desktop" / "External Tools"
    ext.mkdir(parents=True)
    (ext / ET.TOOL_FILENAME).write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CommonProgramFiles", str(tmp_path / "Common Files"))

    rc, out, _err = run_cli(capsys, "handoff", "--server", "localhost:54321",
                            "--database", "abc-guid", "--project", project)
    assert rc == 0
    assert 'transport: "ribbon:machine"' in out    # TOON quotes a value with a colon in it
    assert written(project)["transport"] == "ribbon:machine"


def test_a_click_stays_silent_about_a_transport_it_cannot_see(machine, tmp_path, monkeypatch, capsys):
    """With neither the machine file nor the custom action installed, the fields are absent. That is
    what `.agent/desktop.json` looked like before transports existed, and `read_handoff()` reads it
    -- an invented transport would have `ad-doctor` reporting a ribbon this machine does not have."""
    project = machine(one_instance(tmp_path))
    monkeypatch.setenv("CommonProgramFiles", str(tmp_path / "no-such-common-files"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "no-such-local"))

    rc, out, _err = run_cli(capsys, "handoff", "--server", "localhost:54321",
                            "--database", "abc-guid", "--project", project)
    assert rc == 0
    assert "transport:" not in out
    assert "transport" not in written(project)


# -------------------------------------------------------------------------- ad-pbip register-tool


@pytest.fixture
def common_files(tmp_path, monkeypatch):
    """A real, empty External Tools folder, and a cwd for `.agent/out/` to land in."""
    ext = tmp_path / "Common Files" / "Microsoft Shared" / "Power BI Desktop" / "External Tools"
    ext.mkdir(parents=True)
    monkeypatch.setenv("CommonProgramFiles", str(tmp_path / "Common Files"))
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return ext


def deny_writes(monkeypatch):
    """The `PermissionError` of a managed laptop, injected: root can write anywhere here."""
    def denied(path):
        raise PermissionError("Access is denied")
    monkeypatch.setattr(DT, "_probe_write", denied)


def test_no_flags_writes_directly_only_where_the_folder_accepts_a_file(common_files, capsys):
    rc, out, _err = run_cli(capsys, "register-tool")

    assert rc == 0
    assert "wrote: direct" in out
    assert "ribbon: writable" in out
    assert (common_files / ET.TOOL_FILENAME).exists()


def test_no_flags_packages_when_the_folder_refuses_and_writes_nothing_there(common_files, monkeypatch, capsys):
    """The machine #112 measured. `register-tool` does exactly what `--package` does, says where the
    file went, and leaves `%CommonProgramFiles%` untouched -- including the probe file."""
    deny_writes(monkeypatch)
    rc, out, _err = run_cli(capsys, "register-tool")

    assert rc == 0
    assert "ribbon: needs-it-file" in out
    assert ".agent/out/external-tool" in out
    assert os.path.exists(os.path.join(".agent", "out", "external-tool", ET.TOOL_FILENAME))
    assert os.path.exists(os.path.join(".agent", "out", "external-tool", "REQUEST.md"))
    assert os.listdir(common_files) == []


def test_no_flags_writes_nothing_when_the_file_is_already_on_the_ribbon(common_files, capsys):
    (common_files / ET.TOOL_FILENAME).write_text("{}", encoding="utf-8")
    rc, out, _err = run_cli(capsys, "register-tool")

    assert rc == 0
    assert "ribbon: registered" in out
    assert "wrote: nothing" in out
    assert (common_files / ET.TOOL_FILENAME).read_text(encoding="utf-8") == "{}"


def test_the_kill_switch_is_reported_as_a_fact_and_the_package_still_written(common_files, monkeypatch, capsys):
    """External Tools switched off is a state, not an error: the handoff never needed the ribbon."""
    monkeypatch.setattr(DT, "external_tools_killswitch",
                        lambda run=None: (False, "HKLM policy key: EnableExternalTools=0"))
    rc, out, _err = run_cli(capsys, "register-tool")

    assert rc == 0
    assert "ribbon: disabled-by-policy" in out
    assert "handoff --active" in out
    assert os.listdir(common_files) == []


def test_package_writes_both_files_and_out_moves_them(common_files, tmp_path, capsys):
    """The ticket attachment: the file, and the request that asks a stranger in IT to place it."""
    dest = tmp_path / "ticket"
    rc, out, _err = run_cli(capsys, "register-tool", "--package", "--out", str(dest))

    assert rc == 0
    tool = dest / ET.TOOL_FILENAME
    request = dest / "REQUEST.md"
    assert tool.exists() and request.exists()
    assert str(dest).replace("\\", "/") in out and "sha256" in out

    data = json.loads(tool.read_text(encoding="utf-8"))
    assert data["path"].lower().endswith("cmd.exe")          # never an interpreter path
    assert "%server%" in data["arguments"] and "%database%" in data["arguments"]
    assert str(dest) not in data["arguments"]                # and never a project path
    body = request.read_text(encoding="utf-8")
    assert "Copy-Item" in body and "Remove-Item" in body     # place it, and undo it
    assert os.listdir(common_files) == []


def test_the_launcher_flag_reaches_the_packaged_file(common_files, tmp_path, capsys):
    """A venv site: `ad-setup` writes a per-user shim and the file launches that instead of
    `python`. Still no interpreter path, still one file for every user of that site."""
    dest = tmp_path / "ticket"
    rc, _out, _err = run_cli(capsys, "register-tool", "--package", "--out", str(dest),
                             "--launcher", "agentdata-handoff.cmd")

    assert rc == 0
    data = json.loads((dest / ET.TOOL_FILENAME).read_text(encoding="utf-8"))
    assert "agentdata-handoff.cmd" in data["arguments"]
    assert "-m agentdata" not in data["arguments"]           # the shim already carries the verb


@pytest.mark.parametrize("argv", [
    ("register-tool",),
    ("register-tool", "--package"),
    ("register-tool", "--te2"),
])
def test_no_answer_ever_tells_this_user_to_elevate(common_files, appdata_isolation, monkeypatch,
                                                   capsys, argv):
    """The rule of #112, asserted on the text rather than trusted: "run elevated" belongs only to a
    machine where an elevation avenue was actually detected, and nothing here detects one. Told to a
    user who cannot elevate it is worse than saying nothing, because it ends the conversation."""
    deny_writes(monkeypatch)
    rc, out, err = run_cli(capsys, *argv)

    assert rc == 0
    lowered = (out + err).lower()
    for word in ELEVATION_WORDS:
        assert word not in lowered, f"{argv} said {word!r}"


def test_the_source_of_these_verbs_carries_no_elevation_sentence():
    """A phrase that is never printed cannot creep back in through a branch no test covers."""
    from agentdata import cli_pbip

    text = open(cli_pbip.__file__, encoding="utf-8").read().lower()
    for word in ("run elevated", "administrator privileges", "run as administrator"):
        assert word not in text, f"cli_pbip.py contains {word!r}"


# ----------------------------------------------------------- the per-user Tabular Editor action


def actions(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_te2_install_is_idempotent_and_leaves_other_actions_alone(appdata_isolation, capsys):
    """TE2's `CustomActions.json` is the user's own file. Ours goes in beside whatever is there."""
    path = ET.custom_actions_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mine = {"Name": "Someone else's action", "Execute": "Info(1);"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump([mine], f)

    rc, out, _err = run_cli(capsys, "register-tool", "--te2")
    assert rc == 0 and "changed: added" in out
    names = [a["Name"] for a in actions(path)]
    assert names == ["Someone else's action", ET.TE2_ACTION_NAME]

    rc, out, _err = run_cli(capsys, "register-tool", "--te2")
    assert rc == 0 and "changed: unchanged" in out
    assert [a["Name"] for a in actions(path)] == names


def test_te2_remove_is_a_true_undo(appdata_isolation, capsys):
    path = ET.custom_actions_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    before = [{"Name": "Someone else's action", "Execute": "Info(1);"}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(before, f)

    assert run_cli(capsys, "register-tool", "--te2")[0] == 0
    rc, out, _err = run_cli(capsys, "register-tool", "--te2", "--remove")

    assert rc == 0 and "changed: removed" in out
    assert actions(path) == before

    rc, out, _err = run_cli(capsys, "register-tool", "--te2", "--remove")
    assert rc == 0 and "changed: absent" in out
    assert actions(path) == before


def test_te2_refuses_a_malformed_actions_file_rather_than_rewriting_it(appdata_isolation, capsys):
    """Tabular Editor drops *every* custom action in a file it cannot parse, so replacing one would
    destroy work that has nothing to do with us. The refusal is the safe answer."""
    path = ET.custom_actions_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ not json at all")

    rc, out, _err = run_cli(capsys, "register-tool", "--te2")

    assert rc == 1
    assert "ok: false" in out
    assert "will not rewrite it" in out
    with open(path, encoding="utf-8") as f:
        assert f.read() == "{ not json at all"


def test_remove_without_te2_is_a_refusal(appdata_isolation, capsys):
    rc, out, _err = run_cli(capsys, "register-tool", "--remove")
    assert rc == 2 and "--te2 --remove" in out


# --------------------------------------------------------------------------------- ad-pbip probe


@pytest.fixture
def probe_machine(monkeypatch, tmp_path):
    """A fake `cmd.exe`/PowerShell for the S0 report. Nothing is launched and nothing is read from
    this box: what is under test is that the operator gets one complete block."""
    def run(args, timeout=30):
        script = args[-1]
        if script == "where python":
            return 0, "C:\\Python312\\python.exe", ""
        if script == "python -V":
            return 0, "Python 3.12.4", ""
        if "agentdata --help" in script:
            return 0, "usage: ad-pbip [-h]", ""
        if script.startswith("echo"):
            return 0, "C:\\Python312;C:\\Windows", ""
        if "PBIDesktop" in script:
            return 0, json.dumps([{"Id": 1111, "MainWindowTitle": TITLE_A}]), ""
        return 0, "", ""

    monkeypatch.setattr(PRB, "default_run", run)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_probe_renders_every_row_it_measured(probe_machine, capsys):
    """One command, one block, pasted whole into the issue. `policy.render` would sample a table
    this long down to twenty rows, and a sampled probe answers a question nobody asked."""
    rc, out, _err = run_cli(capsys, "probe")

    assert rc == 0
    header = [line for line in out.splitlines() if line.startswith("probe[")]
    assert len(header) == 1
    count = int(header[0].split("[")[1].split("]")[0])
    assert count >= 25
    assert out.count("\n  Q") == count            # every measured row is printed, not a sample
    assert "verdict.launcher" in out and "verdict.zorder" in out and "verdict.te2" in out
    assert "ask_a_human: 2" in out                # the two clicks no probe can make for a person


def test_probe_answers_the_launcher_question_the_machine_file_depends_on(probe_machine, capsys):
    """#114's file is worth one ticket only if a bare `python` from the user's own PATH reaches
    agentdata. This fake says it does, and the verdict has to say so too."""
    rc, out, _err = run_cli(capsys, "probe")

    assert rc == 0
    assert "verdict.launcher: cmd-python" in out


def test_probe_writes_nothing(probe_machine, capsys):
    """Read-only is the premise of the whole epic: a probe needing a privileged write would be
    arguing with its own argument."""
    before = sorted(os.listdir(probe_machine))
    assert run_cli(capsys, "probe")[0] == 0
    assert sorted(os.listdir(probe_machine)) == before


# ---------------------------------------------------------------------------- the register itself


@pytest.mark.parametrize("verb,needles", [
    ("handoff", ("--active", "--file")),
    ("register-tool", ("--package", "--te2", "--remove", "--out", "--launcher")),
    ("probe", ("--pretty",)),
])
def test_every_verb_and_flag_is_in_the_help(verb, needles, capsys):
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([verb, "--help"])
    out = capsys.readouterr().out
    for needle in needles:
        assert needle in out, f"ad-pbip {verb} --help does not mention {needle}"

    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    top = capsys.readouterr().out
    assert verb in top


def test_the_flags_that_answer_the_same_question_are_mutually_exclusive():
    parser = build_parser()
    for argv in (["handoff", "--active", "--file", "Sales"],
                 ["register-tool", "--package", "--te2"]):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
