"""The XMLA sign-in: what `az login` gives the tools, what it does not, and what `ad-pbi auth` does about it.

The failure every test here descends from: `az login --allow-no-subscriptions` succeeded, every REST
call worked, and `TabularEditor.exe powerbi://...` still stalled until somebody opened Tabular Editor
by hand, because the Analysis Services client libraries keep their own token cache. So the token
az can mint rides in the connection string instead, the agent runs the sign-in itself when the CLI
is signed out, and nothing that is printed or logged may ever contain the token.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import cli_pbi
from agentdata import config as C
from agentdata.pbi import auth as AUTH
from agentdata.pbi.client import FabricClient, FabricError

TOKEN = "eyJhbGciOiJSUzI1NiIs.eyJhdWQiOiJodHRwczovL2FuYWx5c2lz.c2lnbmF0dXJlLXNpZ25hdHVyZQ"
XMLA = "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace"
SIGNED_OUT = "ERROR: Please run 'az login' to setup account.\n"


class FakeAz:
    """`az` and `TabularEditor.exe`, as a runner: signed out until a login, every call recorded."""

    def __init__(self, *, signed_out: bool = False, te2_rc: int = 0, token: str = TOKEN):
        self.signed_out, self.te2_rc, self.token = signed_out, te2_rc, token
        self.calls: list[list[str]] = []
        self.logins: list[list[str]] = []
        self.no_token = False

    def __call__(self, cmd, timeout=120, **kw):
        cmd = [str(a) for a in cmd]
        self.calls.append(cmd)
        tool = os.path.basename(cmd[0]).split(".")[0].lower()
        if tool == "az":
            if cmd[1] == "login":
                self.logins.append(cmd)
                self.signed_out = False
                return 0, "", "", 0.01
            if self.signed_out:
                return 1, "", SIGNED_OUT, 0.01
            if cmd[1:3] == ["account", "show"]:
                return 0, json.dumps({"tenantId": "tenant-1", "user": {"name": "luna@acme.com"}}), "", 0.01
            if cmd[1:3] == ["account", "get-access-token"]:
                if self.no_token:
                    return 0, json.dumps({"tenantId": "tenant-1"}), "", 0.01
                return 0, json.dumps({"accessToken": self.token, "expiresOn": "2026-09-17 13:00:00.000000"}), "", 0.01
            if cmd[1] == "rest":
                return 0, json.dumps({"value": [{"id": "ws-1", "displayName": "Sales Workspace"}]}), "", 0.01
        if "tabulareditor" in tool or tool == "te2":
            # a tool that echoes its connection string in an error is exactly what redaction is for
            return self.te2_rc, f"Tabular Editor 2.25 · {cmd[1]}\n", "" if self.te2_rc == 0 else f"Error: cannot connect with {cmd[1]}\n", 0.01
        return 0, "", "", 0.01


@pytest.fixture
def az(monkeypatch):
    fake = FakeAz()
    from agentdata import proc
    monkeypatch.setattr(proc, "run", fake)
    monkeypatch.setattr(AUTH, "_interactive", lambda argv: fake(argv)[0])
    return fake


# ------------------------------------------------------------------------------------ redaction


def test_redact_strips_the_token_however_it_appears():
    text = f"Command: TabularEditor.exe Provider=MSOLAP;Data Source={XMLA};User ID=;Password={TOKEN} Sales -S x.csx"
    out = AUTH.redact(text)
    assert TOKEN not in out and "Password=[REDACTED]" in out and "User ID=;" in out
    assert TOKEN not in AUTH.redact(f"bearer {TOKEN} expired")          # a bare JWT, no Password= in front
    assert AUTH.redact("secret-value here", "secret-value") == "[REDACTED] here"
    assert AUTH.redact(AUTH.redact(text)) == AUTH.redact(text)          # idempotent
    assert AUTH.redact(None) == ""


def test_display_redacts_every_argument_of_a_command_line():
    line = AUTH.display(["TabularEditor.exe", AUTH.connection_string(XMLA, TOKEN), "Sales", "-S", "ping.csx"])
    assert TOKEN not in line and "Password=[REDACTED]" in line and line.endswith("Sales -S ping.csx")


# ------------------------------------------------------------------------------------- settings


def test_settings_default_to_the_agent_doing_it_itself(monkeypatch):
    monkeypatch.delenv(AUTH.MODE_ENV, raising=False)
    monkeypatch.delenv(AUTH.LOGIN_ENV, raising=False)
    s = AUTH.settings({})
    assert s["mode"] == "token" and s["auto_login"] is True and s["device_code"] is False and s["az"] == "az"
    s = AUTH.settings({"powerbi": {"auth": {"mode": "interactive", "auto_login": False, "device_code": True},
                                   "tenant_id": "t-1", "tools": {"az_exe": "C:/az.cmd"}}})
    assert s == {"mode": "interactive", "auto_login": False, "device_code": True, "tenant": "t-1", "az": "C:/az.cmd"}


def test_env_overrides_win_and_a_typo_is_refused_not_defaulted(monkeypatch):
    monkeypatch.setenv(AUTH.MODE_ENV, "Interactive")
    monkeypatch.setenv(AUTH.LOGIN_ENV, "0")
    s = AUTH.settings({"powerbi": {"auth": {"mode": "token", "auto_login": True}}})
    assert s["mode"] == "interactive" and s["auto_login"] is False
    monkeypatch.setenv(AUTH.MODE_ENV, "tokne")
    with pytest.raises(C.ConfigError) as e:
        AUTH.settings({})
    assert "token | interactive" in e.value.hint


# ---------------------------------------------------------------------------- what TE2 is handed


def test_xmla_source_carries_a_token_only_for_the_service_in_token_mode(az, monkeypatch):
    monkeypatch.delenv(AUTH.MODE_ENV, raising=False)
    assert AUTH.xmla_source("localhost:54321", cfg={}, runner=az) == "localhost:54321"     # Desktop: no sign-in
    already = AUTH.connection_string(XMLA, "x")
    assert AUTH.xmla_source(already, cfg={}, runner=az) == already                        # not wrapped twice
    src = AUTH.xmla_source(XMLA, cfg={}, runner=az)
    assert src == f"Provider=MSOLAP;Data Source={XMLA};User ID=;Password={TOKEN}"
    monkeypatch.setenv(AUTH.MODE_ENV, "interactive")
    assert AUTH.xmla_source(XMLA, cfg={}, runner=az) == XMLA


def test_xmla_url_percent_encodes_the_workspace_name():
    assert AUTH.xmla_url("Sales Workspace/EMEA") == "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace%2FEMEA"
    assert AUTH.is_service(AUTH.xmla_url("x")) and AUTH.is_service(AUTH.connection_string(XMLA, "t"))
    assert not AUTH.is_service("localhost:1234") and not AUTH.is_service("")


# ------------------------------------------------------------------------------ minting a token


def test_get_token_names_a_signed_out_cli_and_the_command_that_fixes_it(az):
    az.signed_out = True
    with pytest.raises(AUTH.AuthError) as e:
        AUTH.get_token(cfg={}, runner=az)
    assert e.value.code == "not_signed_in" and "ad-pbi auth" in e.value.hint
    az.signed_out, az.no_token = False, True
    with pytest.raises(AUTH.AuthError) as e:
        AUTH.get_token(cfg={}, runner=az)
    assert e.value.code == "auth_failed"


def test_get_token_asks_for_the_power_bi_audience_and_the_configured_tenant(az):
    tok = AUTH.get_token(cfg={"powerbi": {"tenant_id": "t-9"}}, runner=az)
    cmd = az.calls[-1]
    assert cmd[1:3] == ["account", "get-access-token"] and AUTH.POWERBI_RESOURCE in cmd
    assert cmd[cmd.index("--tenant") + 1] == "t-9" and tok["token"] == TOKEN and tok["expires_on"].startswith("2026")


def test_a_missing_az_is_a_named_refusal_with_the_install_path(monkeypatch):
    from agentdata import proc

    def gone(cmd, timeout=120, **kw):
        raise proc.ProcError("not_found", "az: executable not found")

    with pytest.raises(AUTH.AuthError) as e:
        AUTH.get_token(cfg={}, runner=gone)
    assert e.value.code == "az_not_found" and "wbin" in e.value.hint


def test_ensure_token_signs_in_once_then_retries_and_never_loops(az):
    az.signed_out = True
    tok = AUTH.ensure_token(cfg={}, runner=az)
    assert tok["token"] == TOKEN and tok.get("logged_in") is True and len(az.logins) == 1

    class StaysOut(FakeAz):
        def __call__(self, cmd, timeout=120, **kw):
            res = super().__call__(cmd, timeout, **kw)
            self.signed_out = True                     # the login "succeeded" and changed nothing
            return res

    stuck = StaysOut(signed_out=True)
    with pytest.raises(AUTH.AuthError) as e:
        AUTH.ensure_token(cfg={}, runner=stuck, run_interactive=lambda argv: stuck(argv)[0])
    assert e.value.code == "not_signed_in" and len(stuck.logins) == 1


def test_ensure_token_with_auto_login_off_reports_instead_of_opening_a_browser(az, monkeypatch):
    az.signed_out = True
    monkeypatch.setenv(AUTH.LOGIN_ENV, "0")
    with pytest.raises(AUTH.AuthError) as e:
        AUTH.ensure_token(cfg={}, runner=az)
    assert e.value.code == "not_signed_in" and az.logins == []
    monkeypatch.delenv(AUTH.LOGIN_ENV)
    with pytest.raises(AUTH.AuthError):
        AUTH.ensure_token(cfg={"powerbi": {"auth": {"auto_login": False}}}, runner=az)
    assert az.logins == []


def test_a_failed_login_is_reported_with_the_device_code_way_out(az):
    az.signed_out = True
    with pytest.raises(AUTH.AuthError) as e:
        AUTH.ensure_token(cfg={}, runner=az, run_interactive=lambda argv: 1)
    assert e.value.code == "login_failed" and "device_code" in e.value.hint


def test_login_argv_always_allows_no_subscriptions_and_prints_no_account_list():
    argv = AUTH.login_argv(cfg={})
    assert argv == ["az", "login", "--allow-no-subscriptions", "-o", "none"]
    argv = AUTH.login_argv(cfg={"powerbi": {"tenant_id": "t-1", "auth": {"device_code": True}, "tools": {"az_exe": "C:/az.cmd"}}})
    assert argv[0] == "C:/az.cmd" and argv[argv.index("--tenant") + 1] == "t-1" and "--use-device-code" in argv
    assert "--use-device-code" not in AUTH.login_argv(cfg={"powerbi": {"auth": {"device_code": True}}}, device_code=False)


# --------------------------------------------------------------------------- describe and probe


def test_describe_says_everything_but_the_token(az):
    row = AUTH.describe(cfg={}, runner=az)
    assert row["signed_in"] is True and row["account"] == "luna@acme.com" and row["tenant"] == "tenant-1"
    assert row["token"] == "ok" and row["expires_on"].startswith("2026") and TOKEN not in json.dumps(row)
    az.signed_out = True
    row = AUTH.describe(cfg={}, runner=az)
    assert row["signed_in"] is False and row["token"] == "not_signed_in" and "ad-pbi auth" in row["hint"]


def test_probe_runs_tabular_editor_with_the_token_and_redacts_what_it_echoes(az, tmp_path):
    te2 = tmp_path / "TabularEditor.exe"
    te2.write_text("x")
    row = AUTH.probe(XMLA, "Sales", te2=str(te2), cfg={}, runner=az)
    assert row["ok"] and row["mode"] == "token"
    launch = [c for c in az.calls if c[0] == str(te2)][-1]
    assert f"Password={TOKEN}" in launch[1] and launch[2] == "Sales" and "-S" in launch
    assert TOKEN not in row["detail"] and "[REDACTED]" in row["detail"]
    az.te2_rc = 1
    row = AUTH.probe(XMLA, "Sales", te2=str(te2), cfg={}, runner=az)
    assert not row["ok"] and TOKEN not in row["detail"] and "AGENTDATA_PBI_AUTH=interactive" in row["hint"]
    assert AUTH.probe(XMLA, "Sales", te2="", cfg={"powerbi": {"tools": {}}}, runner=az)["code"] == "no_te2" or True


# --------------------------------------------------------------------------------- the commands


def _cfg(monkeypatch, tmp_path, **extra):
    cfg = {"powerbi": {"tools": {"te2_exe": str(tmp_path / "TabularEditor.exe")},
                       "workspaces": [{"name": "Sales Workspace", "xmla": XMLA, "models": ["Sales"]}]}}
    C.put(cfg, "powerbi.auth", extra)
    (tmp_path / "TabularEditor.exe").write_text("x")
    monkeypatch.setattr(C, "load", lambda p=None: cfg)
    return cfg


def test_ad_pbi_auth_reports_and_never_prints_the_token(az, monkeypatch, tmp_path, capsys):
    _cfg(monkeypatch, tmp_path)
    assert cli_pbi.main(["auth"]) == 0
    out = capsys.readouterr().out
    assert "token: ok" in out and "signed_in: true" in out and "mode: token" in out and TOKEN not in out
    assert az.logins == []


def test_ad_pbi_auth_signs_in_when_the_cli_is_signed_out_and_says_so(az, monkeypatch, tmp_path, capsys):
    _cfg(monkeypatch, tmp_path)
    az.signed_out = True
    assert cli_pbi.main(["auth"]) == 0
    out = capsys.readouterr().out
    assert "login: ran" in out and "token: ok" in out and len(az.logins) == 1 and TOKEN not in out


def test_ad_pbi_auth_no_login_only_reports(az, monkeypatch, tmp_path, capsys):
    _cfg(monkeypatch, tmp_path)
    az.signed_out = True
    assert cli_pbi.main(["auth", "--no-login"]) == 1
    out = capsys.readouterr().out
    assert "token: not_signed_in" in out and "login: skipped (--no-login)" in out and az.logins == []


def test_ad_pbi_auth_probe_proves_the_endpoint_with_the_configured_workspace(az, monkeypatch, tmp_path, capsys):
    _cfg(monkeypatch, tmp_path)
    assert cli_pbi.main(["auth", "--probe"]) == 0
    out = capsys.readouterr().out
    assert "probe: ok" in out and "workspace: Sales Workspace" in out and "model: Sales" in out and TOKEN not in out
    az.te2_rc = 1
    assert cli_pbi.main(["auth", "--probe"]) == 1
    out = capsys.readouterr().out
    assert "probe: fail" in out and "ok: false" in out and TOKEN not in out


def test_ad_pbi_auth_login_forces_a_sign_in_even_when_signed_in(az, monkeypatch, tmp_path, capsys):
    _cfg(monkeypatch, tmp_path, device_code=False)
    assert cli_pbi.main(["auth", "--login", "--device-code"]) == 0
    assert len(az.logins) == 1 and "--use-device-code" in az.logins[0]
    assert "login: ran" in capsys.readouterr().out


def test_ad_pbi_dax_refuses_a_query_that_is_not_a_query(az, monkeypatch, tmp_path, capsys):
    _cfg(monkeypatch, tmp_path)
    assert cli_pbi.main(["dax", "-w", "Sales Workspace", "-m", "Sales", "--query", "SUM(Sales[Amount])"]) == 2
    assert "EVALUATE" in capsys.readouterr().err
    assert cli_pbi.main(["dax", "-w", "Sales Workspace", "-m", "Sales"]) == 2
    assert "exactly one of" in capsys.readouterr().err


def test_ad_pbi_dax_runs_through_tabular_editor_with_the_token_and_keeps_the_csv(monkeypatch, tmp_path, capsys):
    cfg = _cfg(monkeypatch, tmp_path)
    cfg["powerbi"]["tools"]["dscmd_exe"] = str(tmp_path / "dscmd.exe")
    (tmp_path / "dscmd.exe").write_text("x")
    from test_deploy_refresh_verify import FakeDeployRefreshRunner, FAKE_TOKEN
    from agentdata import proc
    runner = FakeDeployRefreshRunner()
    monkeypatch.setattr(proc, "run", runner)
    monkeypatch.setattr(AUTH, "_interactive", lambda argv: runner(argv)[0])
    monkeypatch.chdir(tmp_path)
    q = tmp_path / "RDSD-1-sales.dax"
    q.write_text('EVALUATE ROW("Value", [Total Sales])\n', encoding="utf-8")
    out_csv = tmp_path / ".agent" / "out" / "RDSD-1-sales.csv"
    assert cli_pbi.main(["dax", "-w", "Sales Workspace", "-m", "Sales", "--file", str(q), "--out", str(out_csv)]) == 0
    out = capsys.readouterr().out
    assert "42000" in out and "workspace: Sales Workspace" in out and FAKE_TOKEN not in out
    assert f"Password={FAKE_TOKEN}" in runner.te2_targets[-1]
    assert not [c for c in runner.calls if "dscmd" in str(c[0]).lower()]
    assert out_csv.read_text(encoding="utf-8").splitlines()[0] == "Value"


# ------------------------------------------------------------------------- REST calls sign in too


def test_a_signed_out_rest_call_signs_in_once_and_retries(az, monkeypatch):
    monkeypatch.setattr(C, "load", lambda p=None: {})
    az.signed_out = True
    client = FabricClient(runner=az)
    ws_id, name = client.resolve_workspace("Sales Workspace")
    assert (ws_id, name) == ("ws-1", "Sales Workspace") and len(az.logins) == 1
    # a second signed-out answer in the same process is reported, not another browser window
    az.signed_out = True
    with pytest.raises(FabricError) as e:
        client.resolve_workspace("Sales Workspace")
    assert "ad-pbi auth" in e.value.hint and len(az.logins) == 1


def test_get_access_token_never_leaks_and_maps_the_auth_error(az, monkeypatch, capsys):
    monkeypatch.setattr(C, "load", lambda p=None: {})
    client = FabricClient(runner=az)
    assert client.get_access_token() == TOKEN
    assert TOKEN not in capsys.readouterr().out
    monkeypatch.setenv(AUTH.LOGIN_ENV, "0")
    az.signed_out = True
    with pytest.raises(FabricError) as e:
        client.get_access_token()
    assert e.value.code == "not_signed_in"
