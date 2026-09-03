import json, os
import pytest
from agentdata import config as C
from agentdata.setup import wizard as W
from agentdata.setup.steps import pncli_import, powerbi, project, sources

PNCLI = {"jira": {"url": "https://acme.atlassian.net", "email": "me@acme.com", "token": "tok_1234567890abcdef"},
         "bitbucket": {"token": "bb_secret_value_123"}}
PKG_DIR = os.path.normcase(os.path.dirname(os.path.abspath(__import__("agentdata").__file__)))


class FakeDet(W.Detectors):
    """No machine or network access. Tunable per test."""

    def __init__(self, pncli=PNCLI, tools=None, modules=(), dsns=None, whoami_error=None, smoke_error=None,
                 pncli_bin="C:/Users/me/AppData/Roaming/npm/pncli.cmd", pncli_rc=0, set_password_error=None):
        self.pncli, self.tools, self.modules = pncli, tools or {}, set(modules)
        self.pncli_bin, self.pncli_rc = pncli_bin, pncli_rc
        self.dsns = dsns or {}
        self.whoami_error, self.smoke_error = whoami_error, smoke_error
        self.set_password_error = set_password_error   # simulates a broken keyring backend (see secrets._guard)
        self.passwords: dict = {}
        self.runs: list = []
        self.files: dict = {}

    def which(self, name):
        return self.tools.get(name)

    def launcher(self, name, exe=None):
        """pncli is an npm command shim on Windows (pncli.cmd -> node cli.js); never an .exe."""
        p = exe or self.pncli_bin if name == "pncli" else self.tools.get(name)
        if not p:
            return {"found": False, "name": name, "kind": "", "path": "", "tried": ["pncli on PATH + PATHEXT", "npm global prefix"]}
        return {"found": True, "name": name, "path": p, "kind": "npm shim", "tried": [], "rc": self.pncli_rc,
                "version": "pncli/1.4.0", "node": "C:/Program Files/nodejs/node.exe",
                "script": "C:/Users/me/AppData/Roaming/npm/node_modules/@kolatts/pncli/bin/cli.js"}

    def exists(self, p):
        """Only what a test registered, plus data packaged inside agentdata/ (that ships with the code and is not
        machine state). Never the rest of the real filesystem: this class stands in for the machine, and a Windows
        CI runner really does have `C:/Program Files/Microsoft SDKs/Azure/CLI2/wbin/az.cmd` — one of the az
        candidates — so falling through made a tool "found" there and missing everywhere else."""
        p = C.expand(p or "")
        if p.endswith("config.json"):
            return self.pncli is not None
        if os.path.normcase(os.path.abspath(p)).startswith(PKG_DIR):
            return os.path.exists(p)
        return p in self.tools.values() or p in self.files

    def read_json(self, p):
        if self.pncli is None:
            raise FileNotFoundError(p)
        if self.pncli == "bad":
            raise json.JSONDecodeError("bad", "x", 0)
        return self.pncli

    def read_text(self, p):
        return self.files.get(C.expand(p)) or open(C.expand(p), encoding="utf-8").read()

    def write_text(self, p, text):
        self.files[C.expand(p)] = text

    def glob(self, pattern, root="."):
        return [k for k in self.files if k.endswith(".pbip")]

    def run(self, args, timeout=120):
        self.runs.append(args)
        # the steps pass the RESOLVED path now (C:/az.cmd), because the bare name cannot be started on Windows
        tool = os.path.basename(str(args[0])).split(".")[0].lower()
        if [tool, args[1]] == ["az", "account"]:
            return 0, json.dumps({"tenantId": "tenant-1"}), ""
        if [tool, args[1]] == ["az", "rest"]:
            return 0, json.dumps({"value": [{"id": "ws-1", "name": "Sales Workspace"}, {"id": "ws-2", "name": "Ops"}]}), ""
        if args[1:3] == ["csv", "--help"]:
            return 0, "Usage: dscmd csv <output> -s --server -d --database -f --file", ""
        return 0, "tables=3", ""

    def module(self, name):
        return name in self.modules

    def odbc_drivers(self):
        return ["Teradata Database ODBC Driver 20.00"]

    def odbc_dsns(self):
        return dict(self.dsns)

    def keyring_backend(self):
        return "FakeKeyring"

    def has_password(self, source, env, user):
        return (source, env, user) in self.passwords

    def set_password(self, source, env, user, password):
        if self.set_password_error:
            raise C.ConfigError(self.set_password_error, hint="ad-doctor's keyring row names the backend")
        self.passwords[(source, env, user)] = password

    def smoke(self, source, env, cfg):
        if self.smoke_error:
            raise RuntimeError(self.smoke_error)
        return {"ok": True, "elapsed_s": 0.1, "capabilities": {"trunc_date": True, "tmode": "ANSI"}}

    def jira_whoami(self, cfg, redetect=False):
        if self.whoami_error:
            raise RuntimeError(self.whoami_error)
        C.put(cfg, "jira.flavor", "cloud"); C.put(cfg, "jira.auth", "basic"); C.put(cfg, "jira.api", "3")
        C.stamp(cfg, "jira")
        return {"base_url": "https://acme.atlassian.net", "flavor": "cloud", "auth": "basic", "api": "3",
                "token_source": "pncli:jira.token", "display_name": "Me", "account": "acc"}

    def getuser(self):
        return "luna"

    def python_bits(self):
        return 64


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "agentdata.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    monkeypatch.chdir(tmp_path)
    return p


def test_propose_keys_and_masking():
    prop = pncli_import.propose(C.flatten(PNCLI))
    assert prop == {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}


def test_setup_non_interactive_writes_config_without_secrets(cfg_path, capsys):
    det = FakeDet(tools={"TabularEditor.exe": "C:/TE/TabularEditor.exe", "dscmd.exe": "C:/DS/dscmd.exe", "az": "C:/az.cmd"},
                  modules={"teradatasql", "keyring", "pyodbc"}, dsns={"TD_PROD": "Teradata"})
    det.passwords[("teradata", "uat", "luna")] = "pw"
    answers = {"sources.teradata.use": True, "sources.teradata.envs": "prod,uat",
               "sources.teradata.prod.mode": "native", "sources.teradata.prod.host": "td.acme", "sources.teradata.prod.logmech": "KRB5",
               "sources.teradata.uat.mode": "odbc", "sources.teradata.uat.dsn": "1", "sources.teradata.uat.logmech": "LDAP",
               "sources.hive.use": False, "sources.impala.use": False, "sources.oracle.use": False,
               "powerbi.use": True, "powerbi.workspaces.configure": True, "powerbi.workspaces.select": "1",
               "powerbi.workspace.Sales Workspace.models": "Sales Model", "project.generate": False}
    (cfg_path.parent / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    rc = W.run_setup(["--non-interactive", "--answers", str(cfg_path.parent / "answers.json")], det)
    out = capsys.readouterr()
    cfg = json.loads(cfg_path.read_text())
    assert rc == 0, out.out
    assert cfg["pncli"]["keys"] == {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}
    assert cfg["pncli"]["exe"].endswith("pncli.cmd")   # the shim we proved starts is pinned; PATH changes cannot break it
    assert cfg["jira"]["base_url"] == "https://acme.atlassian.net" and cfg["jira"]["flavor"] == "cloud"
    td = cfg["sources"]["teradata"]["envs"]
    assert td["prod"]["host"] == "td.acme" and td["prod"]["capabilities"]["tmode"] == "ANSI"
    assert td["uat"]["mode"] == "odbc" and td["uat"]["dsn"] == "TD_PROD" and td["uat"]["user"] == "luna"
    ws = cfg["powerbi"]["workspaces"][0]
    assert ws["xmla"] == "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace" and ws["id"] == "ws-1" and ws["models"] == ["Sales Model"]
    assert cfg["powerbi"]["tools"]["dscmd_caps"]["file_flag"] is True
    assert set(cfg["verified"]) >= {"jira", "teradata:prod", "teradata:uat", "powerbi:xmla:Sales Workspace"}
    text = json.dumps(cfg) + out.out + out.err
    assert "tok_1234567890abcdef" not in text and "bb_secret_value_123" not in text and "pw" not in json.dumps(cfg)
    assert "meta:" in out.out and "ok: true" in out.out
    # idempotent re-run
    assert W.run_setup(["--non-interactive", "--answers", str(cfg_path.parent / "answers.json")], det) == 0
    assert json.loads(cfg_path.read_text())["sources"] == cfg["sources"]


def test_answers_file_rejects_passwords(cfg_path):
    with pytest.raises(C.ConfigError):
        W.AnswerPrompter({"sources.teradata.prod.password": "x"})


def test_doctor_fails_without_pncli_config(cfg_path, capsys):
    rc = W.run_doctor(["--only", "pncli"], FakeDet(pncli=None))
    out = capsys.readouterr().out
    assert rc == 1 and "ok: false" in out and "pncli config init" in out


def test_doctor_ok_and_quiet(cfg_path, capsys):
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02"}})
    det = FakeDet(tools={"pncli": "/usr/bin/pncli"})
    assert W.run_doctor(["--only", "pncli"], det) == 0
    out = capsys.readouterr().out
    assert "ok: true" in out and "jira auth" in out
    assert W.run_doctor(["--only", "pncli", "--quiet"], det) == 0
    assert "checks[0]" in capsys.readouterr().out


def test_doctor_online_verifies_and_reports_failure(cfg_path, capsys):
    C.save({"pncli": {"keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}}})
    rc = W.run_doctor(["--only", "pncli", "--online"], FakeDet(whoami_error="401 nope"))
    out = capsys.readouterr().out
    assert rc == 1 and "401 nope" in out
    assert W.run_doctor(["--only", "pncli", "--online"], FakeDet()) == 0
    assert json.loads(cfg_path.read_text())["verified"]["jira"]


def test_sources_doctor_flags_missing_dsn_and_driver(cfg_path, capsys):
    C.save({"sources": {"teradata": {"envs": {"a": {"mode": "odbc", "dsn": "GONE"}, "b": {"mode": "native", "host": "h"}}}}})
    rc = W.run_doctor(["--only", "sources"], FakeDet(modules={"pyodbc"}))
    out = capsys.readouterr().out
    assert rc == 1
    assert "GONE" in out and "odbcad32" in out
    assert ".[teradata]" in out  # TOON escapes the double quotes in the hint


def test_unknown_step(cfg_path, capsys):
    assert W.run_doctor(["--only", "nope"], FakeDet()) == 2
    assert "unknown step" in capsys.readouterr().out


def test_project_stub_fill_and_generation(cfg_path, tmp_path):
    tpl = "# Project: <PROJECT_KEY>\n- env: <td_env_name>              # ad-td --env\n- pbi_xmla: <x>\n- keep: <k>\n"
    filled = project.fill(tpl, {"env": "prod", "pbi_xmla": "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace"})
    assert "- env: prod              # ad-td --env" in filled and "- keep: <k>" in filled and "powerbi://" in filled
    C.save({"sources": {"teradata": {"envs": {"prod": {"host": "h"}}}},
            "powerbi": {"tools": {"te2_exe": "C:/TE/TabularEditor.exe"},
                        "workspaces": [{"name": "Sales Workspace", "id": "ws-1", "xmla": powerbi.xmla_url("Sales Workspace"), "models": ["Sales"]}]}})
    det = FakeDet()
    proj = tmp_path / "proj"
    det.files[str(proj / "reports" / "Sales.pbip")] = "{}"
    rc = W.run_setup(["--non-interactive", "--project", str(proj), "--offline", "--answers",
                      str(_answers(tmp_path, {"project.jira_project": "RDSD"}))], det)
    assert rc == 0
    agents = det.files[str(proj / "AGENTS.md")]
    assert "- jira_project: RDSD" in agents and "- env: prod" in agents and "- pbi_model: Sales" in agents
    assert "- pbip_path: reports/Sales.pbip" in agents and "Sales%20Workspace" in agents and "- ws_id: ws-1" in agents
    assert json.loads(det.files[str(proj / ".agent" / "state.json")])["project"] == "RDSD"
    assert ".agent/out/" in det.files[str(proj / ".gitignore")]


def _answers(tmp_path, d):
    p = tmp_path / "ans.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def test_xmla_url_percent_encodes():
    assert powerbi.xmla_url("Sales Workspace/EMEA") == "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace%2FEMEA"


def test_answers_file_with_bom_and_set_flags(cfg_path, tmp_path, capsys):
    """2026-09-02 laptop friction: Windows PowerShell 5.1 `Set-Content -Encoding utf8` adds a BOM; the loader crashed."""
    det = FakeDet()
    proj = tmp_path / "proj2"
    ans = tmp_path / "bom.json"
    ans.write_bytes(json.dumps({"project.jira_project": "BOMD"}).encode("utf-8-sig"))
    rc = W.run_setup(["--only", "project", "--non-interactive", "--offline", "--project", str(proj), "--answers", str(ans),
                      "--set", "project.confluence_space=SPC"], det)
    assert rc == 0
    agents = det.files[str(proj / "AGENTS.md")]
    assert "- jira_project: BOMD" in agents and "- confluence_space: SPC" in agents
    proj3 = tmp_path / "proj3"
    rc = W.run_setup(["--only", "project", "--non-interactive", "--offline", "--project", str(proj3), "--set", "project.jira_project=RDSD"], det)
    assert rc == 0 and "- jira_project: RDSD" in det.files[str(proj3 / "AGENTS.md")]
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xef\xbb\xbf{not json")
    capsys.readouterr()
    rc = W.run_setup(["--only", "project", "--non-interactive", "--offline", "--project", str(tmp_path / "p4"), "--answers", str(bad)], det)
    out = capsys.readouterr().out
    assert rc == 2 and "ok: false" in out and "not valid JSON" in out and "--set" in out
    rc = W.run_setup(["--only", "project", "--non-interactive", "--offline", "--project", str(tmp_path / "p5"), "--set", "project.jira_project"], det)
    assert rc == 2 and "key=value" in capsys.readouterr().out
    assert W.load_answers(None, ["a=true", "b=False", "c=x=y", " d = 1 "]) == {"a": True, "b": False, "c": "x=y", "d": "1"}
    assert W.load_answers(str(ans), ["project.jira_project=OVR"]) == {"project.jira_project": "OVR"}


def test_doctor_fails_when_pncli_launcher_is_missing_or_broken(cfg_path, capsys):
    """2026-09-02 laptop friction: ad-pncli died with [WinError 2] while setup called pncli 'ok' — there is no pncli.exe."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_token": "jira.token"}}})
    assert W.run_doctor(["--only", "pncli"], FakeDet(pncli_bin=None)) == 1
    out = capsys.readouterr().out
    assert "pncli launcher" in out and "npm install -g @kolatts/pncli" in out and "there is no pncli.exe" in out
    assert W.run_doctor(["--only", "pncli"], FakeDet(pncli_rc=9)) == 1
    out = capsys.readouterr().out
    assert "exits 9 on --version" in out
    assert W.run_doctor(["--only", "pncli"], FakeDet()) == 0
    assert "pncli.cmd (npm shim) · pncli/1.4.0" in capsys.readouterr().out


def _patch(det, extra=None, cfg=None):
    if cfg is not None:
        C.save(cfg)
    return W.run_setup(["--patch", "--non-interactive", "--offline", *(extra or [])], det)


def test_patch_reasks_only_the_failing_setting(cfg_path, capsys):
    """One wrong DSN must cost one env's questions, not the whole wizard."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02", "teradata:prod": "2026-09-02"},
            "sources": {"teradata": {"envs": {"prod": {"mode": "odbc", "dsn": "TD_PROD", "logmech": "KRB5"},
                                              "uat": {"mode": "odbc", "dsn": "GONE", "logmech": "KRB5"}}}}})
    det = FakeDet(modules={"pyodbc", "teradatasql", "keyring"}, dsns={"TD_PROD": "Teradata"})
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "sources",
                      "--set", "sources.teradata.uat.dsn=TD_PROD"], det)
    out, _err = capsys.readouterr()
    assert rc == 0, out
    cfg = json.loads(cfg_path.read_text())
    envs = cfg["sources"]["teradata"]["envs"]
    assert envs["uat"]["dsn"] == "TD_PROD"                                          # repaired
    assert envs["prod"] == {"mode": "odbc", "dsn": "TD_PROD", "logmech": "KRB5"}    # untouched
    assert cfg["verified"]["teradata:prod"] == "2026-09-02"                         # a working env is not disturbed
    assert "was_failing: 1" in out
    asked = out.split("asked[")[1].split("\n")[0]
    assert "sources.teradata.uat." in asked and "teradata.prod" not in asked
    assert "GONE" in out and "sources/teradata:uat" in out                          # why it was re-asked, in the output


def test_patch_with_nothing_broken_asks_nothing(cfg_path, capsys):
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02"}})
    assert W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "pncli"], FakeDet()) == 0
    out = capsys.readouterr().out
    assert "repaired: 0" in out and "nothing to repair" in out
    assert "--include-warnings" not in out              # no warn rows: do not advertise a flag that finds nothing
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_token": "jira.token"}}})
    assert W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "pncli"], FakeDet()) == 0
    out = capsys.readouterr().out                       # jira never verified is a warn row
    assert "nothing to repair" in out and "--include-warnings covers warn rows" in out


def test_patch_repairs_a_missing_pncli_launcher(cfg_path, capsys, tmp_path):
    """Laptop case: pncli is not on PATH at all (npm shim, no pncli.exe). --patch asks for the one path."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02"}})
    shim = tmp_path / "pncli.cmd"
    shim.write_text("@echo off\n", encoding="utf-8")
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "pncli", "--set", f"pncli.exe={shim}"],
                     FakeDet(pncli_bin=None))
    out, _err = capsys.readouterr()
    assert "pncli/pncli launcher" in out and "not found on PATH" in out
    assert json.loads(cfg_path.read_text())["pncli"]["exe"] == str(shim).replace("\\", "/")
    assert rc == 0 and "ok: true" in out and "was_failing: 1" in out


def test_patch_repairs_a_wrong_az_path(cfg_path, capsys, tmp_path, monkeypatch):
    """Laptop case: a configured az path that is not there (the real one is
    C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\wbin\\az.cmd).

    The candidate below really exists on this machine, which is the condition that broke this test on the GitHub
    Windows runner: it ships the Azure CLI at the canonical candidate path, so a FakeDet that fell through to the
    real filesystem "found" it, the check passed, and --patch had nothing to repair."""
    installed = tmp_path / "really-installed-az.cmd"
    installed.write_text("@echo off", encoding="utf-8")
    monkeypatch.setitem(powerbi.TOOLS, "az_exe", ("az", [str(installed)]))
    az = str(tmp_path / "Azure" / "CLI2" / "wbin" / "az.cmd").replace("\\", "/")
    C.save({"powerbi": {"tools": {"az_exe": str(tmp_path / "wrong" / "az.cmd").replace("\\", "/")}}})
    det = FakeDet(tools={"az": None})
    det.files[C.expand(az)] = "@echo off"
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "powerbi", "--set", f"powerbi.az_exe={az}"], det)
    out, _err = capsys.readouterr()
    assert "powerbi/az_exe" in out and "wrong/az.cmd" in out
    assert json.loads(cfg_path.read_text())["powerbi"]["tools"]["az_exe"] == az
    assert rc == 0 and "was_failing: 1" in out and "asked[1]: powerbi.az_exe" in out


def test_scoped_prompter_only_prompts_in_scope():
    inner = W.AnswerPrompter({"a.x": "asked", "b.y": "asked"})
    p = W.ScopedPrompter(inner, ["a."], {"a.": "a.x is wrong"})
    assert p.ask("a.x", "?", "current") == "asked" and p.asked == ["a.x"]
    assert p.ask("b.y", "?", "current") == "current"          # out of scope keeps the stored value
    assert p.confirm("b.z", "?", True) is True and p.confirm("b.z", "?", False) is False
    assert p.ask("b.w", "?", None, ["one", "two"]) == "one"
    assert p.asked == ["a.x"]


def test_launcher_probes_the_pinned_path_not_the_bare_name(tmp_path, monkeypatch):
    """A pinned launcher is usually NOT on PATH — probing the bare name reported a working pin as broken."""
    if os.name == "nt":
        pytest.skip("POSIX stand-in for a pinned launcher")
    exe = tmp_path / "pncli"
    exe.write_text("#!/bin/sh\necho pncli/1.4.0\n", encoding="utf-8", newline="\n")
    os.chmod(exe, 0o755)
    info = W.Detectors().launcher("pncli", str(exe))
    assert info["found"] and info["rc"] == 0 and info["version"] == "pncli/1.4.0"
    assert W.Detectors().launcher("pncli", str(tmp_path / "gone"))["found"] is False


def test_pncli_step_honours_PNCLI_EXE(cfg_path, monkeypatch):
    """ad-pncli honours PNCLI_EXE and the check's own hint recommends it; the doctor must resolve it the same way."""
    seen = {}

    class Det(FakeDet):
        def launcher(self, name, exe=None):
            seen["exe"] = exe
            return super().launcher(name, exe)

    monkeypatch.setenv("PNCLI_EXE", "C:/tools/pncli/pncli.cmd")
    ctx = W.Context(cfg=C.load(), det=Det(), ask=W.AnswerPrompter({}), facts={})
    pncli_import.PncliStep().detect(ctx)
    assert seen["exe"] == "C:/tools/pncli/pncli.cmd"
    monkeypatch.delenv("PNCLI_EXE")
    C.save({"pncli": {"exe": "C:/from/config/pncli.cmd"}})
    ctx = W.Context(cfg=C.load(), det=Det(), ask=W.AnswerPrompter({}), facts={})
    pncli_import.PncliStep().detect(ctx)
    assert seen["exe"] == "C:/from/config/pncli.cmd"


def test_patch_repairs_a_launcher_that_is_found_but_will_not_start(cfg_path, capsys, tmp_path):
    """`exits N on --version` is tagged with pncli.exe, so --patch must actually offer that prompt."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "exe": "C:/broken/pncli.cmd",
                      "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02"}})
    good = tmp_path / "pncli.cmd"
    good.write_text("@echo off\n", encoding="utf-8")
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "pncli", "--set", f"pncli.exe={good}"],
                     FakeDet(pncli_rc=9))
    out = capsys.readouterr().out
    assert "exits 9 on --version" in out and "asked[1]: pncli.exe" in out
    assert json.loads(cfg_path.read_text())["pncli"]["exe"] == str(good).replace("\\", "/")
    assert rc in (0, 1)


def test_the_fake_detector_never_consults_the_real_machine(tmp_path):
    """FakeDet stands in for everything that touches the machine; if it falls through, tests pass or fail by luck."""
    real = tmp_path / "really-here.exe"
    real.write_text("x", encoding="utf-8")
    det = FakeDet()
    assert det.exists(str(real)) is False
    det.files[str(real)] = "x"
    assert det.exists(str(real)) is True
    for candidate in powerbi.TOOLS["az_exe"][1]:            # the paths a Windows runner may really have
        assert det.exists(candidate) is False
    from agentdata.install import templates_dir            # packaged data is the one carve-out
    assert det.exists(os.path.join(templates_dir(), "AGENTS.md")) is True


def test_oracle_setup_asks_for_host_port_service_not_a_hand_built_string(cfg_path, capsys):
    """SQL Developer's Basic tab: Name, Hostname, Port, Service name. There is no ODBC DSN to point at."""
    det = FakeDet(modules={"oracledb", "keyring"})
    det.passwords[("oracle", "OIMPROD1_ROSVC", "luna")] = "pw"
    answers = {"sources.teradata.use": False, "sources.hive.use": False, "sources.impala.use": False,
               "sources.oracle.use": True, "sources.oracle.envs": "OIMPROD1_ROSVC",
               "sources.oracle.OIMPROD1_ROSVC.style": "basic",
               "sources.oracle.OIMPROD1_ROSVC.host": "exag1301-scan1.example.net",
               "sources.oracle.OIMPROD1_ROSVC.port": "1521",
               "sources.oracle.OIMPROD1_ROSVC.identifier": "service",
               "sources.oracle.OIMPROD1_ROSVC.service_name": "oimprod1_rosvc.prod.example.net",
               "powerbi.use": False, "project.generate": False}
    assert W.run_setup(["--only", "sources", "--non-interactive", "--offline",
                        *sum((["--set", f"{k}={v}"] for k, v in answers.items()), [])], det) == 0
    e = json.loads(cfg_path.read_text())["sources"]["oracle"]["envs"]["OIMPROD1_ROSVC"]
    assert e["host"] == "exag1301-scan1.example.net" and e["port"] == 1521
    assert e["service_name"] == "oimprod1_rosvc.prod.example.net" and "dsn" not in e
    assert e["mode"] == "native"                       # never ODBC: an ODBC DSN would be read as a TNS alias
    assert C.oracle_dsn(e) == "exag1301-scan1.example.net:1521/oimprod1_rosvc.prod.example.net"
    capsys.readouterr()
    W.run_doctor(["--only", "sources"], det)
    assert "exag1301-scan1.example.net:1521/oimprod1_rosvc" in capsys.readouterr().out   # visible in every doctor run


def test_oracle_tns_style_and_incomplete_connections_are_caught(cfg_path, capsys):
    det = FakeDet(modules={"oracledb", "keyring"})
    det.passwords[("oracle", "prod", "luna")] = "pw"
    sets = ["--set", "sources.teradata.use=false", "--set", "sources.hive.use=false", "--set", "sources.impala.use=false",
            "--set", "sources.oracle.use=true", "--set", "sources.oracle.envs=prod", "--set", "sources.oracle.prod.style=tns",
            "--set", "sources.oracle.prod.dsn=MYALIAS", "--set", "powerbi.use=false", "--set", "project.generate=false"]
    assert W.run_setup(["--only", "sources", "--non-interactive", "--offline", *sets], det) == 0
    e = json.loads(cfg_path.read_text())["sources"]["oracle"]["envs"]["prod"]
    assert e["dsn"] == "MYALIAS" and "host" not in e and "service_name" not in e
    capsys.readouterr()
    C.save({"sources": {"oracle": {"envs": {"prod": {"mode": "native", "host": "h", "user": "luna"}}}}})
    assert W.run_doctor(["--only", "sources"], det) == 1
    out = capsys.readouterr().out
    assert "incomplete Oracle connection: no service name or SID" in out and "no ODBC DSN" in out


def test_patch_never_asks_questions_an_answer_cannot_fix(cfg_path, capsys):
    """`teradatasql not installed` is a pip install. Asking that env's questions repairs nothing and, with no stdin,
    dies on the first prompt — which is what a laptop run looked like."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_token": "jira.token"}},
            "verified": {"jira": "2026-09-02"},
            "sources": {"teradata": {"envs": {"prod": {"mode": "native", "host": "td.example.net", "logmech": "KRB5"}}}}})
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "sources"], FakeDet())   # no teradatasql
    out = capsys.readouterr().out
    assert rc == 1 and "repaired: 0" in out and "nothing to repair by answering a question" in out
    assert "manual[1]" in out and "teradatasql not installed" in out and "an install or an action, not an answer" in out
    assert "asked[" not in out                                    # nothing was asked


def test_patch_takes_explicit_targets(cfg_path, capsys, tmp_path):
    """`ad-setup --patch sources.oracle` re-asks that area on demand, without waiting for a check to fail."""
    C.save({"sources": {"oracle": {"envs": {"prod": {"mode": "native", "host": "old.example.net", "port": 1521,
                                                     "service_name": "old.svc", "auth": "password", "user": "luna"}}}},
            "pncli": {"keys": {"jira_url": "jira.url", "jira_token": "jira.token"}}})
    det = FakeDet(modules={"oracledb", "keyring"})
    det.passwords[("oracle", "prod", "luna")] = "pw"
    rc = W.run_setup(["--patch", "sources.oracle", "--non-interactive", "--offline",
                      "--set", "sources.oracle.prod.host=new.example.net",
                      "--set", "sources.oracle.prod.service_name=new.svc"], det)
    out = capsys.readouterr().out
    e = json.loads(cfg_path.read_text())["sources"]["oracle"]["envs"]["prod"]
    assert rc == 0 and e["host"] == "new.example.net" and e["service_name"] == "new.svc"
    assert "sources.oracle.prod.host" in out and "pncli" not in out.split("checks[")[0]   # only that step ran
    rc = W.run_setup(["--patch", "nope.thing", "--non-interactive", "--offline"], det)
    assert rc == 2 and "nothing to repair for: nope.thing" in capsys.readouterr().out


def test_oracle_thick_mode_still_asks_for_a_username_and_password(cfg_path, capsys):
    """A client_lib path used to mean 'external auth', so giving one made it impossible to authenticate at all."""
    det = FakeDet(modules={"oracledb", "keyring"})
    sets = ["--set", "sources.teradata.use=false", "--set", "sources.hive.use=false", "--set", "sources.impala.use=false",
            "--set", "sources.oracle.use=true", "--set", "sources.oracle.envs=prod", "--set", "sources.oracle.prod.style=basic",
            "--set", "sources.oracle.prod.host=db.example.net", "--set", "sources.oracle.prod.identifier=service",
            "--set", "sources.oracle.prod.service_name=svc.example.net",
            "--set", "sources.oracle.prod.auth=password",
            "--set", "sources.oracle.prod.client_lib=C:/Oracle/instantclient_21_13/bin",     # thick AND a password
            "--set", "sources.oracle.prod.user=pk40484",
            "--set", "powerbi.use=false", "--set", "project.generate=false"]
    assert W.run_setup(["--only", "sources", "--non-interactive", "--offline", *sets], det) == 0
    e = json.loads(cfg_path.read_text())["sources"]["oracle"]["envs"]["prod"]
    assert e["auth"] == "password" and e["client_lib"] == "C:/Oracle/instantclient_21_13/bin"
    assert e["user"] == "pk40484"                       # the credential prompts ran despite thick mode
    assert sources.needs_password("oracle", e) is True and sources.uses_kerberos("oracle", e) is False
    out = capsys.readouterr().out
    assert "no keyring entry" in out                    # non-interactive cannot store one; it says so


def test_oracle_auth_modes_and_the_missing_client_check(cfg_path, capsys):
    assert sources.ora_auth({"client_lib": "C:/oracle/bin"}) == "kerberos"      # written before `auth` existed
    assert sources.ora_auth({}) == "password" and sources.ora_auth({"auth": "WALLET"}) == "wallet"
    assert sources.needs_password("oracle", {"auth": "kerberos", "client_lib": "x"}) is False
    assert sources.needs_password("oracle", {"auth": "password", "client_lib": "x"}) is True
    C.save({"sources": {"oracle": {"envs": {"prod": {"mode": "native", "host": "h", "service_name": "s",
                                                     "auth": "kerberos"}}}}})   # kerberos without the client
    assert W.run_doctor(["--only", "sources"], FakeDet(modules={"oracledb", "keyring"})) == 1
    out = capsys.readouterr().out
    assert "kerberos auth needs the Oracle client (thick mode)" in out and "instantclient" in out


def test_patch_asks_only_the_missing_oracle_field(cfg_path, capsys):
    """A host with no service name is one question, not the whole connection."""
    C.save({"sources": {"oracle": {"envs": {"prod": {"mode": "native", "host": "db.example.net", "port": 1521,
                                                     "auth": "password", "user": "luna"}}}},
            "pncli": {"keys": {"jira_url": "jira.url", "jira_token": "jira.token"}}})
    det = FakeDet(modules={"oracledb", "keyring"})
    det.passwords[("oracle", "prod", "luna")] = "pw"
    rc = W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "sources",
                      "--set", "sources.oracle.prod.identifier=service",
                      "--set", "sources.oracle.prod.service_name=svc.example.net"], det)
    out = capsys.readouterr().out
    assert rc == 0 and "no service name or SID" in out
    asked = out.split("asked[")[1].split("\n")[0]
    assert "identifier" in asked and "service_name" in asked
    assert "prod.host" not in asked and "prod.port" not in asked and "prod.user" not in asked
    e = json.loads(cfg_path.read_text())["sources"]["oracle"]["envs"]["prod"]
    assert e["service_name"] == "svc.example.net" and e["host"] == "db.example.net"   # untouched


def test_patch_refuses_to_prompt_with_no_terminal(cfg_path, capsys, monkeypatch):
    """Piped (Luna's terminal, CI): dying on EOF at the first prompt taught nobody anything."""
    C.save({"pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_url": "jira.url", "jira_token": "jira.token"}}})
    monkeypatch.setattr(W, "has_tty", lambda: False)
    assert W.run_setup(["--patch", "--include-warnings", "--offline", "--only", "pncli"], FakeDet(pncli=None)) == 2
    out = capsys.readouterr().out
    assert "no terminal to ask on" in out and "needs_answers[" in out and "--set pncli.config_path=<value>" in out
    assert W.run_setup(["--offline", "--only", "pncli"], FakeDet()) == 2
    assert "no terminal to ask on" in capsys.readouterr().out


def test_a_broken_keyring_backend_does_not_lose_the_rest_of_the_answers(cfg_path, capsys, monkeypatch):
    """Real bug, reported as 'the Teradata config is not saving': entering an LDAP/TD2 password crashed the
    whole step the moment the keyring backend failed for any reason OTHER than being uninstalled -- so host,
    mode, logmech and everything else just answered for that env was thrown away with it. Reproduced for real
    against a genuinely broken keyring install (a native-extension ABI panic, which is a BaseException and
    slips past a bare `except Exception`); this pins the same shape with a fake that raises ConfigError, which
    is what secrets.py now turns every such failure into before it ever reaches this step."""
    monkeypatch.setattr(W, "has_tty", lambda: True)
    answers = iter(["y", "prod", "native", "tdprod01.corp.example.com", "LDAP", "", "jsmith", "hunter2",
                    "n", "n", "n"])
    monkeypatch.setattr(W, "_console_prompt", lambda text, default=None, secret=False: next(answers))
    det = FakeDet(modules={"teradatasql"}, set_password_error="keyring backend failed on write (PanicException)")
    rc = W.run_setup(["--only", "sources", "--offline"], det)
    out = capsys.readouterr().out
    assert rc == 0, out                                  # a warning, same tier as "no keyring entry" -- not a failure
    assert "keyring backend failed on write" in out and "warn" in out   # named, not swallowed
    cfg = json.loads(cfg_path.read_text())
    env = cfg["sources"]["teradata"]["envs"]["prod"]      # everything else still landed
    assert env == {"mode": "native", "host": "tdprod01.corp.example.com", "logmech": "LDAP", "user": "jsmith"}
    assert ("teradata", "prod", "jsmith") not in det.passwords   # the password itself correctly did not land


def test_patch_explicit_teradata_target_sees_a_freshly_interactive_setup(cfg_path, monkeypatch):
    """Reported: `ad-setup --only sources` configures Teradata, then `ad-setup --patch sources.teradata` right
    after treats it as never configured -- 'Use Teradata? [y/N]' again, envs back to the 'prod' fallback, an
    empty envs dict in config.json. Both commands go through the real interactive Prompter here (not
    AnswerPrompter), which is the only path that ever showed this shape of data loss (see 7db3e07). A custom
    env name is used deliberately: the 'prod' fallback is also a valid answer, so only a name that is NOT the
    fallback proves the second run is reading what the first run wrote, not just landing on the same default."""
    monkeypatch.setattr(W, "has_tty", lambda: True)
    det = FakeDet(modules={"teradatasql"})

    setup_answers = iter(["y", "PRODTD1", "native", "tdprod01.corp.example.com", "KRB5", "", "n", "n", "n"])
    monkeypatch.setattr(W, "_console_prompt", lambda text, default=None, secret=False: next(setup_answers))
    rc1 = W.run_setup(["--only", "sources", "--offline"], det)
    assert rc1 == 0
    cfg1 = json.loads(cfg_path.read_text())
    assert cfg1["sources"]["teradata"]["envs"]["PRODTD1"]["host"] == "tdprod01.corp.example.com"

    patch_prompts = []

    def echo_defaults(text, default=None, secret=False):
        patch_prompts.append((text, default))
        return default or ""                     # accept whatever default the second run offers, every time

    monkeypatch.setattr(W, "_console_prompt", echo_defaults)
    rc2 = W.run_setup(["--patch", "sources.teradata", "--offline"], det)
    assert rc2 == 0

    use_prompt = next(text for text, _ in patch_prompts if text.startswith("Use Teradata?"))
    assert "[Y/n]" in use_prompt                  # remembered as already configured, not "[y/N]" from scratch
    envs_default = next(default for text, default in patch_prompts if "environment names" in text)
    assert envs_default == "PRODTD1"              # the env just typed, not the "prod" fallback

    cfg2 = json.loads(cfg_path.read_text())
    assert cfg2["sources"]["teradata"]["envs"] == cfg1["sources"]["teradata"]["envs"]   # untouched by the patch


def test_setup_quick_mode_auto_accepts_unambiguous_defaults(cfg_path, capsys, monkeypatch):
    """ad-setup --quick accepts unambiguous detected facts without prompting stdin,
    while passwords and ambiguous cases still prompt."""
    monkeypatch.setattr(W, "has_tty", lambda: True)
    det = FakeDet(tools={"TabularEditor.exe": "C:/TE/TabularEditor.exe", "az": "C:/az.cmd"},
                  modules={"pyodbc"}, dsns={"TD_PROD": "Teradata"})
    det.passwords[("teradata", "prod", "luna")] = "pw"

    # Under quick mode:
    # 1. Sources: Use Teradata? (confirm) -> yes
    # 2. envs -> "prod"
    # 3. mode (only odbc found) -> auto-accepted!
    # 4. dsn (only 1 DSN TD_PROD) -> auto-accepted!
    # 5. logmech -> prompts
    # 6. user -> prompts
    # 7. keep_password -> auto-accepted!
    # 8. hive/impala/oracle use -> n, n, n
    # 9. powerbi use -> y
    # 10. tools (te2_exe found) -> auto-accepted!
    prompts_called = []

    def mock_prompt(text, default=None, secret=False):
        prompts_called.append((text, default, secret))
        if "Use Teradata" in text:
            return "y"
        if "environment names" in text:
            return "prod"
        if "logon mechanism" in text:
            return "KRB5"
        if "user" in text and "user" not in text.lower()[:4]:  # "user"
            return "luna"
        if "Use Hive" in text or "Use Impala" in text or "Use Oracle" in text:
            return "n"
        if "Use Power BI" in text:
            return "y"
        if "Configure Power BI" in text:
            return "n"
        if "Generate or update a project stub" in text:
            return "n"
        return default or ""

    monkeypatch.setattr(W, "_console_prompt", mock_prompt)
    rc = W.run_setup(["--quick", "--offline"], det)
    out = capsys.readouterr()
    assert rc == 0, out.out
    cfg = json.loads(cfg_path.read_text())
    assert cfg["sources"]["teradata"]["envs"]["prod"]["dsn"] == "TD_PROD"
    assert cfg["powerbi"]["tools"]["te2_exe"] == "C:/TE/TabularEditor.exe"
    # Verify auto-accepted lines appeared on stderr
    assert "[quick] auto-accepted" in out.err
    # Verify auto_accepted count in output
    assert "auto_accepted:" in out.out

    # Ambiguous test: when there are 2 DSNs, it must prompt for DSN
    det2 = FakeDet(modules={"pyodbc"}, dsns={"TD_PROD": "Teradata", "TD_UAT": "Teradata"})
    prompts_called2 = []

    def mock_prompt2(text, default=None, secret=False):
        prompts_called2.append(text)
        if "Use Teradata" in text:
            return "y"
        if "environment names" in text:
            return "prod"
        if "DSN name" in text:
            return "TD_PROD"
        if "logon mechanism" in text:
            return "KRB5"
        if "Use Hive" in text or "Use Impala" in text or "Use Oracle" in text:
            return "n"
        if "Use Power BI" in text:
            return "n"
        if "Generate or update a project stub" in text:
            return "n"
        return default or ""

    monkeypatch.setattr(W, "_console_prompt", mock_prompt2)
    rc2 = W.run_setup(["--quick", "--offline"], det2)
    assert rc2 == 0
    # DSN name prompt was asked because 2 DSNs were found
    assert any("DSN name" in p for p in prompts_called2)


def test_export_defaults_and_import_roundtrip(cfg_path, tmp_path, capsys):
    """ad-setup --export-defaults writes shareable non-secret json without verified stamps,
    and --import loads it as defaults without overwriting existing settings."""
    initial_cfg = {
        "version": 1,
        "pncli": {"config_path": "~/.pncli/config.json", "keys": {"jira_token": "jira.token", "jira_url": "jira.url"}},
        "sources": {
            "teradata": {
                "envs": {
                    "prod": {"host": "team-td.corp", "mode": "native", "logmech": "KRB5"}
                }
            }
        },
        "powerbi": {
            "tools": {"te2_exe": "C:/Team/TE.exe"},
            "workspaces": [{"name": "Sales", "models": ["Sales Model"]}]
        },
        "verified": {"jira": "2026-09-01", "teradata:prod": "2026-09-01"}
    }
    C.save(initial_cfg)

    export_file = tmp_path / "team-defaults.json"
    rc_export = W.run_setup(["--export-defaults", str(export_file)], FakeDet())
    assert rc_export == 0
    exported_text = export_file.read_text(encoding="utf-8")
    exported = json.loads(exported_text)
    assert "verified" not in exported
    assert exported["sources"]["teradata"]["envs"]["prod"]["host"] == "team-td.corp"
    assert exported["powerbi"]["tools"]["te2_exe"] == "C:/Team/TE.exe"

    # Now import on a fresh machine that already has a custom te2_exe configured
    fresh_cfg_path = tmp_path / "fresh_agentdata.json"
    C.save({"powerbi": {"tools": {"te2_exe": "C:/MyCustom/TE.exe"}}}, str(fresh_cfg_path))

    import agentdata.config as CFG
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv(CFG.CONFIG_ENV, str(fresh_cfg_path))
    try:
        det = FakeDet(tools={"TabularEditor.exe": "C:/MyCustom/TE.exe"})
        rc_import = W.run_setup(["--import", str(export_file), "--non-interactive", "--offline"], det)
        assert rc_import == 0
        imported_cfg = json.loads(fresh_cfg_path.read_text(encoding="utf-8"))
        # Custom setting was NOT overwritten:
        assert imported_cfg["powerbi"]["tools"]["te2_exe"] == "C:/MyCustom/TE.exe"
        # Shared defaults were imported:
        assert imported_cfg["sources"]["teradata"]["envs"]["prod"]["host"] == "team-td.corp"
        assert imported_cfg["pncli"]["keys"]["jira_token"] == "jira.token"
    finally:
        monkeypatch.undo()


def test_parallel_verification_wall_clock(cfg_path, capsys):
    """3 sources/environments verify concurrently, completing much faster than sequential sum."""
    import time
    C.save({
        "sources": {
            "teradata": {
                "envs": {
                    "prod": {"host": "td1.corp", "mode": "native"},
                    "uat": {"host": "td2.corp", "mode": "native"},
                    "dev": {"host": "td3.corp", "mode": "native"}
                }
            }
        }
    })

    class SlowDet(FakeDet):
        def smoke(self, source, env, cfg):
            time.sleep(0.1)
            return {"ok": True, "elapsed_s": 0.1, "capabilities": {"trunc_date": True}}

    det = SlowDet(modules={"teradatasql"})
    t0 = time.perf_counter()
    rc = W.run_doctor(["--only", "sources", "--online"], det)
    elapsed = time.perf_counter() - t0

    assert rc == 0
    # Sequential would take >= 0.3s; parallel should take well under 0.25s
    assert elapsed < 0.25, f"Expected parallel execution < 0.25s, got {elapsed:.2f}s"
    out = capsys.readouterr().out
    assert "teradata:prod" in out and "teradata:uat" in out and "teradata:dev" in out

