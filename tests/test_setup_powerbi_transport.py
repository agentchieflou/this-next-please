r"""The doctor rows that stop telling a user who cannot elevate to run elevated (#117 item 2).

The failure this file guards is not a crash. It is a sentence: `powerbi/external_tool  warn  not
registered -> run elevated`, printed on a laptop where the handoff worked perfectly well and where
the reader's account is not in the local Administrators group. Everything below exists to make that
sentence impossible to print again by accident, and `test_run_elevated_never_appears_*` is the
acceptance criterion of the whole slice: it walks every combination of writable / TE2 present /
action installed / our file present / kill-switch and asserts the word `elevat` is nowhere in the
report unless an elevation avenue was actually measured.

Everything runs on Linux through the seams the rest of the package already uses: the injected
`Runner` answers the PowerShell registry reads, the `Get-Process` window list and `whoami /groups`;
`external_tools_dir` and `custom_actions_path` point at `tmp_path`; and `external_tools_writable` --
the one probe no chmod can fake on a CI that runs as root -- is injected the same way
`tests/test_external_tool.py` injects its own.
"""
import json
import os

import pytest

from agentdata import config as C
from agentdata.pbip import desktop as DT
from agentdata.pbip import external_tool as EXT
from agentdata.setup import wizard as W
from agentdata.setup.steps.powerbi import PowerBIStep, elevation_avenue, next_cheapest_step

WINDOW_JSON = json.dumps([{"Id": 4242, "MainWindowTitle": "Sales - Power BI Desktop",
                           "Path": "C:/Program Files/Microsoft Power BI Desktop/bin/PBIDesktop.exe"}])
ADMIN_CSV = '"BUILTIN\\Administrators","Alias","S-1-5-32-544","Mandatory group, Enabled by default"\n'
USER_CSV = '"Everyone","Well-known group","S-1-1-0","Mandatory group, Enabled by default"\n'


class FakeDet(W.Detectors):
    """The machine, as a dict. Nothing here touches a real registry, process table or Common Files."""

    def __init__(self, *, windows=False, killswitch_off=False, admin=False, whoami_rc=0, is_windows=True):
        self.windows, self.killswitch_off, self.admin = windows, killswitch_off, admin
        self.whoami_rc, self._is_windows = whoami_rc, is_windows
        self.runs: list = []

    def is_windows(self):
        return self._is_windows

    def which(self, name):
        return None

    def exists(self, p):
        return bool(p) and os.path.exists(C.expand(p or ""))

    def run(self, args, timeout=120):
        self.runs.append(list(args))
        if args[:1] == ["whoami"]:
            if self.whoami_rc:
                return self.whoami_rc, "", "whoami: unrecognized option '/groups'"
            return 0, (ADMIN_CSV if self.admin else USER_CSV), ""
        script = args[-1] if args else ""
        if "Get-Process PBIDesktop" in script:
            return (0, WINDOW_JSON, "") if self.windows else (0, "", "")
        if "Get-ItemProperty" in script:
            if self.killswitch_off and "Policies" in script and "HKLM" in script:
                return 0, json.dumps({"EnableExternalTools": 0}), ""
            return 0, "", ""
        return 0, "", ""


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "agentdata.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    monkeypatch.chdir(tmp_path)
    return p


@pytest.fixture
def machine(tmp_path, monkeypatch, cfg_path):
    """A machine whose External Tools folder, TE2 install and custom-action store are all in tmp_path."""

    class Machine:
        root = str(tmp_path)
        ext_dir = str(tmp_path / "CommonFiles" / "External Tools")
        actions = str(tmp_path / "LocalAppData" / "TabularEditor" / "CustomActions.json")
        te2_exe = str(tmp_path / "Enforce" / "TabularEditor.exe")

        def __init__(self):
            os.makedirs(self.ext_dir, exist_ok=True)
            self.writable = (False, "PermissionError: Access is denied")

        def lock(self):
            self.writable = (False, "PermissionError: Access is denied")

        def unlock(self):
            self.writable = (True, "created and deleted zz-probe.pbitool.json")

        def no_folder(self):
            os.rmdir(self.ext_dir)

        def register(self):
            with open(os.path.join(self.ext_dir, EXT.TOOL_FILENAME), "w", encoding="utf-8") as f:
                f.write("{}")

        def install_te2(self):
            os.makedirs(os.path.dirname(self.te2_exe), exist_ok=True)
            open(self.te2_exe, "w").close()
            C.save({"powerbi": {"tools": {"te2_exe": self.te2_exe}}})

        def write_actions(self, payload):
            os.makedirs(os.path.dirname(self.actions), exist_ok=True)
            with open(self.actions, "w", encoding="utf-8") as f:
                f.write(payload if isinstance(payload, str) else json.dumps(payload))

        def install_action(self, extra=()):
            self.write_actions([*extra, {"Name": EXT.TE2_ACTION_NAME, "Enabled": True,
                                         "Execute": "//", "ValidContexts": "Model"}])

    m = Machine()
    monkeypatch.setattr(EXT, "external_tools_dir", lambda: m.ext_dir)
    monkeypatch.setattr(EXT, "custom_actions_path", lambda: m.actions)
    monkeypatch.setattr(DT, "external_tools_writable", lambda ext_dir: m.writable)
    return m


def rows(det):
    """The two transport rows, by name, as produced by the step itself."""
    ctx = W.Context(cfg=C.load(), det=det, ask=W.AnswerPrompter())
    PowerBIStep()._transport_rows(ctx, [])
    return {c.name: c for c in ctx.checks}


def advice(det, machine):
    """Every word the two rows put in front of a human, minus the paths.

    `tmp_path` is named after the running test, and these tests are named after the word they are
    hunting -- so the temporary folder itself would match. A file path is a location, not advice;
    scrubbing the root is what keeps the assertion about the sentence it is actually about.
    """
    text = " ".join(f"{c.detail} {c.hint}" for c in rows(det).values())
    return text.replace(machine.root, "<tmp>").lower()


# ------------------------------------------------------------------ the row names the live transport

def test_zorder_is_ok_and_the_ribbon_is_a_separate_info_line(machine):
    """The reporter's laptop: a window is open, the folder refuses a write. Both facts, two rows."""
    r = rows(FakeDet(windows=True))
    assert r["powerbi/external_tool"].status == "ok"
    assert r["powerbi/external_tool"].detail.startswith("zorder · ")
    assert "`ad-pbip handoff --active`" in r["powerbi/external_tool"].detail

    ribbon = r["powerbi/ribbon"]
    assert ribbon.status == "info"                       # never a warn: a missing button is not a broken install
    assert ribbon.detail.startswith(DT.RIBBON_NEEDS_IT + " · ")
    assert ".agent/out/external-tool" in ribbon.hint     # the package path, as a fact
    assert "register-tool --package" in ribbon.hint


def test_ribbon_registered_wins_the_ladder(machine):
    machine.register()
    r = rows(FakeDet(windows=True))
    assert r["powerbi/external_tool"].detail.startswith("ribbon:machine · ")
    assert "External Tools -> agentdata" in r["powerbi/external_tool"].detail
    assert r["powerbi/external_tool"].hint == ""         # nothing left to upgrade to
    assert r["powerbi/ribbon"].detail.startswith(DT.RIBBON_REGISTERED + " · ")
    assert r["powerbi/ribbon"].hint == ""


def test_te2_local_when_the_action_is_installed(machine):
    machine.install_te2()
    machine.install_action()
    r = rows(FakeDet(windows=True))
    assert r["powerbi/external_tool"].detail.startswith("te2:local · ")
    assert "Hand off to agentdata" in r["powerbi/external_tool"].detail
    assert r["powerbi/ribbon"].status == "info"


def test_no_transport_is_a_warn_that_names_the_settings_behind_it(machine):
    """Off Windows with no window open there is nothing to hand off -- and an answer can help."""
    r = rows(FakeDet(windows=False, is_windows=False))
    row = r["powerbi/external_tool"]
    assert row.status == "warn"
    assert "no handoff transport" in row.detail
    assert row.keys, "a row --patch could help with must name its keys"


def test_no_external_tools_folder_at_all_is_still_only_an_info_line(machine):
    """Desktop never installed for this machine: a fact about the folder, not a failing check."""
    machine.no_folder()
    r = rows(FakeDet(windows=True))
    assert r["powerbi/external_tool"].status == "ok"
    assert r["powerbi/ribbon"].status == "info"
    assert "does not exist" in r["powerbi/ribbon"].detail
    assert "elevat" not in advice(FakeDet(windows=True), machine)


def test_disabled_by_policy_is_a_fact_and_does_not_stop_the_handoff(machine):
    r = rows(FakeDet(windows=True, killswitch_off=True))
    assert r["powerbi/external_tool"].status == "ok"                 # zorder does not need the button
    assert r["powerbi/ribbon"].status == "info"
    assert r["powerbi/ribbon"].detail.startswith(DT.RIBBON_DISABLED + " · ")
    assert r["powerbi/ribbon"].keys == ()                            # no answer changes a Group Policy value


# ------------------------------------------------------------------------- the next cheapest step

def test_next_cheapest_step_is_te2_before_any_privileged_write(machine):
    machine.install_te2()
    r = rows(FakeDet(windows=True))
    assert "register-tool --te2" in r["powerbi/external_tool"].hint
    assert r["powerbi/external_tool"].keys == ("powerbi.te2_custom_action",)


def test_next_cheapest_step_is_register_tool_when_the_folder_is_writable(machine):
    machine.unlock()
    r = rows(FakeDet(windows=True))
    hint = r["powerbi/external_tool"].hint
    assert "`ad-pbip register-tool`" in hint and "--package" not in hint and "--te2" not in hint
    assert r["powerbi/external_tool"].keys == ("powerbi.external_tool",)


def test_next_cheapest_step_is_the_package_and_carries_no_keys(machine):
    """No answer to any ad-setup question writes into Common Files, so --patch must list it manually."""
    r = rows(FakeDet(windows=True))
    row = r["powerbi/external_tool"]
    assert "register-tool --package" in row.hint and ".agent/out/external-tool" in row.hint
    assert "whoever owns Common Files" in row.hint
    assert row.keys == ()


def test_next_cheapest_step_of_a_registered_ribbon_is_nothing(machine):
    assert next_cheapest_step({"state": DT.RIBBON_REGISTERED}, {"present": True, "installed": False}) == ("", ())


# --------------------------------------------------------------- "run elevated": the whole point

MATRIX = [
    dict(registered=r, te2=t, action=a, writable=w, killswitch_off=ks, windows=win)
    for r in (False, True) for t in (False, True) for a in (False, True)
    for w in (False, True) for ks in (False, True) for win in (False, True)
    if not (a and not t)                       # an installed action with no TE2 is not a machine
]


@pytest.mark.parametrize("combo", MATRIX, ids=lambda c: "".join(k[0] + str(int(v)) for k, v in c.items()))
def test_run_elevated_never_appears_without_a_measured_elevation_avenue(machine, combo):
    """The acceptance criterion of #117 item 2, over every state the machine can be in.

    The reported failure was a permission error followed by advice the reporter could not follow.
    Not one of these 48 machines is one where an avenue was measured, so not one of these reports
    may contain the word -- not in a detail, not in a hint, not in the evidence a probe wrote.
    """
    if combo["registered"]:
        machine.register()
    if combo["te2"]:
        machine.install_te2()
    if combo["action"]:
        machine.install_action()
    if combo["writable"]:
        machine.unlock()
    det = FakeDet(windows=combo["windows"], killswitch_off=combo["killswitch_off"], admin=False)
    assert "elevat" not in advice(det, machine)


def test_run_elevated_never_appears_when_whoami_cannot_answer(machine):
    """A probe that failed is not an avenue. Silence beats a guess the reader cannot act on."""
    assert "elevat" not in advice(FakeDet(windows=True, whoami_rc=1), machine)


def test_run_elevated_never_appears_off_windows(machine):
    """`is_windows()` gates the probe, so a Linux CI run costs no subprocess and prints no advice."""
    det = FakeDet(windows=True, admin=True, is_windows=False)
    assert "elevat" not in advice(det, machine)
    assert not [a for a in det.runs if a[:1] == ["whoami"]]


def test_run_elevated_appears_exactly_once_an_avenue_is_measured(machine):
    """Membership of the local Administrators group is the measurement, and the only one."""
    r = rows(FakeDet(windows=True, admin=True))
    hint = r["powerbi/ribbon"].hint
    assert "run elevated" in hint
    assert "S-1-5-32-544" in hint                       # the evidence travels with the advice
    assert "register-tool --package" in hint            # and never replaces the step that needs nobody


def test_the_writable_folder_never_asks_for_elevation(machine):
    """There is nothing to elevate for when the write already works, admin or not."""
    machine.unlock()
    assert "elevat" not in advice(FakeDet(windows=True, admin=True), machine)


# ------------------------------------------------------------------------ the avenue probe itself

def test_elevation_avenue_reads_the_sid_not_the_group_name():
    admin = elevation_avenue(lambda args, timeout=20: (0, ADMIN_CSV, ""))
    assert admin["available"] is True and "S-1-5-32-544" in admin["evidence"]

    plain = elevation_avenue(lambda args, timeout=20: (0, USER_CSV, ""))
    assert plain["available"] is False and "not in the local Administrators group" in plain["evidence"]


def test_elevation_avenue_treats_a_failed_probe_as_no_avenue():
    failed = elevation_avenue(lambda args, timeout=20: (1, "", "unrecognized option"))
    assert failed["available"] is False and "did not answer" in failed["evidence"]


def test_elevation_avenue_without_a_runner_is_never_an_avenue():
    assert elevation_avenue(None)["available"] is False


# ------------------------------------------------- the ad-setup offer to install the TE2 action

def _ask(machine, answers, det=None):
    ctx = W.Context(cfg=C.load(), det=det or FakeDet(), ask=W.AnswerPrompter(answers))
    PowerBIStep()._ask_te2_action(ctx, default=False)
    return ctx, {c.name: c for c in ctx.checks}


def test_te2_offer_is_silent_when_tabular_editor_is_not_here(machine):
    _ctx, r = _ask(machine, {"powerbi.te2_custom_action": True})
    assert "powerbi/te2_action" not in r


def test_te2_offer_merges_and_is_idempotent(machine):
    machine.install_te2()
    machine.write_actions([{"Name": "Someone else's action", "Execute": "// theirs"}])

    ctx, r = _ask(machine, {"powerbi.te2_custom_action": True})
    assert r["powerbi/te2_action"].status == "ok"
    assert r["powerbi/te2_action"].detail.startswith("added · ")
    assert C.get(ctx.cfg, "powerbi.te2_custom_action") is True

    stored = json.loads(open(machine.actions, encoding="utf-8").read())
    names = [a["Name"] for a in stored]
    assert names == ["Someone else's action", EXT.TE2_ACTION_NAME]   # theirs first, untouched
    assert stored[0]["Execute"] == "// theirs"
    assert '-m agentdata pbip handoff' in stored[1]["Execute"]

    _ctx2, r2 = _ask(machine, {"powerbi.te2_custom_action": True})
    assert r2["powerbi/te2_action"].detail.startswith("unchanged · ")
    assert json.loads(open(machine.actions, encoding="utf-8").read()) == stored


def test_te2_offer_refuses_a_malformed_actions_file_and_leaves_it_alone(machine):
    """TE2 drops ALL of a user's actions on a syntax error, so a rewrite would destroy their work."""
    machine.install_te2()
    machine.write_actions("{ this is not json")

    _ctx, r = _ask(machine, {"powerbi.te2_custom_action": True})
    row = r["powerbi/te2_action"]
    assert row.status == "warn"
    assert "not a Tabular Editor custom-action file" in row.detail
    assert row.hint and "will not rewrite" in row.hint
    assert row.keys == ("powerbi.te2_custom_action",)
    assert open(machine.actions, encoding="utf-8").read() == "{ this is not json"


def test_te2_offer_answered_no_never_removes_an_installed_action(machine):
    """--patch runs this prompt with a machine default when the key is out of scope, so a silent
    `no` is not evidence anybody asked for a removal. `--remove` is the verb that means it."""
    machine.install_te2()
    machine.install_action(extra=[{"Name": "Theirs"}])
    before = open(machine.actions, encoding="utf-8").read()

    ctx, r = _ask(machine, {"powerbi.te2_custom_action": False})
    assert open(machine.actions, encoding="utf-8").read() == before
    assert r["powerbi/te2_action"].status == "info"
    assert "register-tool --te2 --remove" in r["powerbi/te2_action"].hint
    assert C.get(ctx.cfg, "powerbi.te2_custom_action") is False


# ---------------------------------------------------- the ad-setup offer to reach the ribbon

def test_ribbon_offer_packages_instead_of_asking_for_elevation(machine, tmp_path):
    ctx = W.Context(cfg=C.load(), det=FakeDet(admin=True), ask=W.AnswerPrompter({"powerbi.external_tool": True}))
    PowerBIStep()._ask_ribbon(ctx, default=False)
    row = {c.name: c for c in ctx.checks}["powerbi/external_tool"]
    assert row.status == "info"
    assert "packaged at" in row.detail and ".agent/out/external-tool" in row.detail
    assert "REQUEST.md" in row.hint
    assert "elevat" not in (row.detail + row.hint).lower()
    assert os.path.exists(tmp_path / ".agent" / "out" / "external-tool" / EXT.TOOL_FILENAME)


def test_ribbon_offer_writes_directly_where_the_folder_was_measured_writable(machine):
    machine.unlock()
    ctx = W.Context(cfg=C.load(), det=FakeDet(), ask=W.AnswerPrompter({"powerbi.external_tool": True}))
    PowerBIStep()._ask_ribbon(ctx, default=False)
    row = {c.name: c for c in ctx.checks}["powerbi/external_tool"]
    assert row.status == "ok" and row.detail.startswith("registered · ")
    assert os.path.exists(os.path.join(machine.ext_dir, EXT.TOOL_FILENAME))
    assert C.get(ctx.cfg, "powerbi.external_tool") is True


def test_ribbon_offer_declined_writes_nothing(machine):
    ctx = W.Context(cfg=C.load(), det=FakeDet(), ask=W.AnswerPrompter({"powerbi.external_tool": False}))
    PowerBIStep()._ask_ribbon(ctx, default=False)
    assert ctx.checks == []
    assert not os.path.exists(os.path.join(machine.ext_dir, EXT.TOOL_FILENAME))


# ------------------------------------------------------------------------------ end to end

def test_ad_doctor_prints_both_rows_and_no_advice_to_elevate(machine, capsys):
    machine.install_te2()
    rc = W.run_doctor(["--only", "powerbi"], FakeDet(windows=True))
    out = capsys.readouterr().out
    assert "powerbi/external_tool" in out and "powerbi/ribbon" in out
    assert "zorder" in out
    assert "elevat" not in out.replace(machine.root, "<tmp>").lower()
    assert rc == 0, out          # a machine with no ribbon button is not a failing doctor


def test_package_dir_matches_the_one_register_tool_actually_writes():
    from agentdata.setup.steps.powerbi import package_dir
    from agentdata import textio
    assert package_dir() == textio.norm_path(EXT.DEFAULT_PACKAGE_DIR)
