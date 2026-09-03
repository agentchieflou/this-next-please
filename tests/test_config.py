import json, os
import pytest
from agentdata import config as C


def test_get_put_flatten_mask():
    cfg = {}
    C.put(cfg, "a.b.c", 1)
    C.put(cfg, "a.list", [{"x": "y"}])
    assert C.get(cfg, "a.b.c") == 1 and C.get(cfg, "a.list.0.x") == "y" and C.get(cfg, "a.nope", 5) == 5
    assert C.flatten(cfg) == {"a.b.c": 1, "a.list.0.x": "y"}
    assert C.mask("abcdefghijkl") == "ab********kl" and C.mask("short") == "*****" and C.mask(None) == ""
    assert C.looks_secret("jira.api_token") and C.looks_secret("PASSWORD") and not C.looks_secret("jira.url")


def test_get_put_leaf_do_not_split_a_dotted_key():
    """Real bug: a Teradata DSN or hostname used as the env name (`TPRDDB.pncint.net`) routinely contains dots.
    put(cfg, f"sources.teradata.envs.{env}", e) treats every dot in `env` as a path separator, shredding one
    env into nested dicts under the wrong keys -- and the caller's own "drop envs no longer typed" cleanup
    then deletes the leftover top-level fragment because it doesn't match the full name, leaving `envs` empty
    with no error at all. put_leaf()/get_leaf() use the last segment verbatim, so this must not happen."""
    cfg = {}
    C.put(cfg, "sources.teradata.envs.TPRDDB.pncint.net", {"dsn": "x"})
    assert cfg["sources"]["teradata"]["envs"] == {"TPRDDB": {"pncint": {"net": {"dsn": "x"}}}}   # the bug, pinned

    cfg2 = {}
    C.put_leaf(cfg2, "sources.teradata.envs", "TPRDDB.pncint.net", {"dsn": "x", "logmech": "LDAP"})
    assert cfg2["sources"]["teradata"]["envs"] == {"TPRDDB.pncint.net": {"dsn": "x", "logmech": "LDAP"}}
    assert C.get_leaf(cfg2, "sources.teradata.envs", "TPRDDB.pncint.net") == {"dsn": "x", "logmech": "LDAP"}
    assert C.get_leaf(cfg2, "sources.teradata.envs", "nope", "default") == "default"
    assert C.get_leaf(cfg2, "sources.teradata.envs.nope", "x", "default") == "default"   # not a dict at all

    # the cleanup loop in sources.py's ask() compares list(envs_cfg) against the typed names -- with put_leaf
    # the top-level key IS the full name, so a same-named re-save is a no-op, not a silent deletion
    envs_cfg = C.get(cfg2, "sources.teradata.envs")
    assert list(envs_cfg) == ["TPRDDB.pncint.net"]


def test_load_missing_and_bad_json(tmp_path, monkeypatch):
    p = tmp_path / "cfg.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    assert C.path() == str(p) and C.load() == {"version": C.VERSION}
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(C.ConfigError) as ei:
        C.load()
    assert "ad-setup" in ei.value.hint


def test_save_atomic_and_refuses_secrets(tmp_path, monkeypatch):
    p = tmp_path / "sub" / "cfg.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    cfg = {"pncli": {"keys": {"jira_token": "jira.token"}}, "jira": {"base_url": "https://x.atlassian.net"}}
    out = C.save(cfg)
    assert out.endswith("cfg.json") and not (tmp_path / "sub" / "cfg.json.tmp").exists()
    assert json.loads(p.read_text())["jira"]["base_url"] == "https://x.atlassian.net"
    with pytest.raises(C.ConfigError):
        C.save({"jira": {"token": "abc123secret"}})
    with pytest.raises(C.ConfigError):
        C.save({"sources": {"teradata": {"envs": {"prod": {"password": "pw"}}}}})
    C.save({"sources": {"teradata": {"envs": {"prod": {"password": ""}}}}})  # empty is fine


def test_project_facts(tmp_path):
    md = tmp_path / "AGENTS.md"
    md.write_text("# P\n- env: prod              # ad-td --env\n- te2_exe: C:/Tools/TE/TabularEditor.exe\n"
                  "- pbi_workspace: <Workspace Name>\n- empty:\n- Jira_Project: RDSD\nnot a fact\n", encoding="utf-8")
    f = C.project_facts(str(md))
    assert f == {"env": "prod", "te2_exe": "C:/Tools/TE/TabularEditor.exe", "jira_project": "RDSD"}
    assert C.project_facts(str(tmp_path / "missing.md")) == {}


def test_resolve_precedence(monkeypatch):
    cfg = {"x": {"y": "from_cfg"}}
    facts = {"name": "from_facts"}
    monkeypatch.delenv("AD_TEST_X", raising=False)
    assert C.resolve("name", flag="flag", env="AD_TEST_X", cfg=cfg, cfg_path="x.y", facts=facts) == "flag"
    monkeypatch.setenv("AD_TEST_X", "from_env")
    assert C.resolve("name", env="AD_TEST_X", cfg=cfg, cfg_path="x.y", facts=facts) == "from_env"
    monkeypatch.delenv("AD_TEST_X")
    assert C.resolve("name", env="AD_TEST_X", cfg=cfg, cfg_path="x.y", facts=facts) == "from_cfg"
    assert C.resolve("name", cfg=cfg, cfg_path="x.zz", facts=facts) == "from_facts"
    assert C.resolve("name", default="d") == "d"
    with pytest.raises(C.ConfigError):
        C.resolve("name")


def test_source_env_and_env_override(monkeypatch):
    cfg = {"sources": {"teradata": {"envs": {"prod": {"host": "td.example", "logmech": "KRB5",
                                                       "capabilities": {"trunc_date": True}}}}}}
    for v in ("TD_HOST_PROD", "TD_HOST", "TD_USER"):
        monkeypatch.delenv(v, raising=False)
    e = C.source_env(cfg, "teradata", "prod")
    assert e["host"] == "td.example" and e["mode"] == "native" and e["env"] == "prod"
    monkeypatch.setenv("TD_HOST_PROD", "override.example")
    assert C.source_env(cfg, "teradata", "prod")["host"] == "override.example"
    with pytest.raises(C.ConfigError) as ei:
        C.source_env(cfg, "teradata", "uat")
    assert "TD_HOST_UAT" in ei.value.hint and "ad-setup" in ei.value.hint
    assert C.capabilities(cfg, "teradata", "prod") == {"trunc_date": True}
    dsn_only = {"sources": {"hive": {"envs": {"p": {"dsn": "HiveDSN"}}}}}
    assert C.source_env(dsn_only, "hive", "p")["mode"] == "odbc"
    with pytest.raises(C.ConfigError):
        C.source_env(cfg, "spark", "prod")


def test_source_env_and_capabilities_with_a_dotted_env_name(monkeypatch):
    """A DSN or hostname used as the env name (common for Teradata) contains dots. ad-td and friends call
    source_env() with exactly that string at runtime -- it must find what ad-setup saved, not silently see
    an unconfigured env because the dots were misread as a nested path."""
    for v in ("TD_HOST_TPRDDB.PNCINT.NET", "TD_HOST"):
        monkeypatch.delenv(v, raising=False)
    cfg = {"sources": {"teradata": {"envs": {"TPRDDB.pncint.net": {
        "mode": "odbc", "dsn": "TPRDDB.pncint.net", "logmech": "LDAP", "user": "pk40484",
        "capabilities": {"tmode": "ANSI"}}}}}}
    e = C.source_env(cfg, "teradata", "TPRDDB.pncint.net")
    assert e["dsn"] == "TPRDDB.pncint.net" and e["logmech"] == "LDAP" and e["env"] == "TPRDDB.pncint.net"
    assert C.capabilities(cfg, "teradata", "TPRDDB.pncint.net") == {"tmode": "ANSI"}


def test_facts_and_config_tolerate_powershell_encodings(tmp_path, monkeypatch):
    p = tmp_path / "AGENTS.md"
    p.write_bytes("- jira_project: RDSD\r\n- env: prod   # ad-td --env\r\n- pbip_path: <x>\r\n".encode("utf-8-sig"))
    assert C.project_facts(str(p)) == {"jira_project": "RDSD", "env": "prod"}
    cfgp = tmp_path / "cfg.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(cfgp))
    cfgp.write_bytes(b"\xff\xfe" + json.dumps({"version": C.VERSION, "a": 1}).encode("utf-16-le"))
    assert C.load()["a"] == 1
    cfgp.write_bytes(b"\xef\xbb\xbf{not json")
    with pytest.raises(C.ConfigError) as ei:
        C.load()
    assert "not valid JSON" in str(ei.value)


def test_oracle_dsn_is_composed_from_the_parts_sql_developer_asks_for():
    """Oracle has no ODBC DSN registry: a connection is hostname + port + service name (or SID)."""
    assert C.oracle_dsn({"host": "exag1301-scan1.example.net", "service_name": "oimprod1_rosvc.prod.example.net"}) == \
        "exag1301-scan1.example.net:1521/oimprod1_rosvc.prod.example.net"
    assert C.oracle_dsn({"host": "h", "port": 1522, "service_name": "svc"}) == "h:1522/svc"
    assert C.oracle_dsn({"host": "h", "port": "1522", "sid": "ORCL"}) == \
        "(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=h)(PORT=1522))(CONNECT_DATA=(SID=ORCL)))"
    assert C.oracle_dsn({"dsn": " MYALIAS ", "host": "ignored"}) == "MYALIAS"   # an explicit alias always wins
    assert C.oracle_dsn({"host": "h"}) == "" and C.oracle_dsn({}) == ""         # incomplete stays empty


def test_source_env_composes_oracle_and_env_vars_override_each_part(tmp_path, monkeypatch):
    monkeypatch.setenv(C.CONFIG_ENV, str(tmp_path / "cfg.json"))
    C.save({"sources": {"oracle": {"envs": {"prod": {"host": "h1", "service_name": "svc1", "user": "me"}}}}})
    assert C.source_env(None, "oracle", "prod")["dsn"] == "h1:1521/svc1"
    monkeypatch.setenv("ORA_HOST_PROD", "h2")
    monkeypatch.setenv("ORA_PORT_PROD", "1600")
    monkeypatch.setenv("ORA_SERVICE_PROD", "svc2")
    e = C.source_env(None, "oracle", "prod")
    assert e["dsn"] == "h2:1600/svc2" and e["mode"] == "native"
    monkeypatch.setenv("ORA_DSN_PROD", "ALIAS")
    assert C.source_env(None, "oracle", "prod")["dsn"] == "ALIAS"


def test_source_env_says_which_oracle_field_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(C.CONFIG_ENV, str(tmp_path / "cfg.json"))
    C.save({"sources": {"oracle": {"envs": {"prod": {"host": "h1"}}}}})       # host but no service name / SID
    with pytest.raises(C.ConfigError) as ei:
        C.source_env(None, "oracle", "prod")
    assert "no service name or SID" in str(ei.value) and "SQL Developer" in ei.value.hint
    C.save({"sources": {"oracle": {"envs": {"prod": {}}}}})
    with pytest.raises(C.ConfigError) as ei:
        C.source_env(None, "oracle", "prod")
    assert "no oracle connection configured" in str(ei.value) and "ORA_HOST_PROD" in ei.value.hint


def test_merge_defaults_populates_missing_without_overwriting():
    target = {
        "pncli": {"config_path": "~/.pncli/config.json"},
        "sources": {"teradata": {"envs": {"prod": {"host": "my-td.corp", "logmech": "KRB5"}}}},
        "powerbi": {"tools": {"te2_exe": "C:/Custom/TE.exe"}}
    }
    defaults = {
        "pncli": {"config_path": "/other/path", "keys": {"jira_token": "token_key"}},
        "sources": {
            "teradata": {"envs": {"prod": {"host": "team-td.corp", "user": "team_user"}, "uat": {"host": "uat-td.corp"}}},
            "hive": {"envs": {"prod": {"host": "hive.corp"}}}
        },
        "powerbi": {
            "tools": {"te2_exe": "C:/Team/TE.exe", "dscmd_exe": "C:/Team/dscmd.exe"},
            "workspaces": [{"name": "Team WS"}]
        }
    }
    C.assert_no_secrets(defaults)
    C.merge_defaults(target, defaults)

    # Existing values preserved:
    assert target["pncli"]["config_path"] == "~/.pncli/config.json"
    assert target["sources"]["teradata"]["envs"]["prod"]["host"] == "my-td.corp"
    assert target["powerbi"]["tools"]["te2_exe"] == "C:/Custom/TE.exe"

    # Missing values filled in:
    assert target["pncli"]["keys"] == {"jira_token": "token_key"}
    assert target["sources"]["teradata"]["envs"]["prod"]["user"] == "team_user"
    assert target["sources"]["teradata"]["envs"]["uat"]["host"] == "uat-td.corp"
    assert target["sources"]["hive"]["envs"]["prod"]["host"] == "hive.corp"
    assert target["powerbi"]["tools"]["dscmd_exe"] == "C:/Team/dscmd.exe"
    assert target["powerbi"]["workspaces"] == [{"name": "Team WS"}]


def test_export_and_import_refuse_secrets():
    bad_defaults = {"sources": {"teradata": {"envs": {"prod": {"password": "secret_pw"}}}}}
    with pytest.raises(C.ConfigError):
        C.assert_no_secrets(bad_defaults)

