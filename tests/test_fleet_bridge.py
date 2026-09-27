"""The bridge's foundations (#545): settings, the folder rule, OneDrive-safe names, canonical JSON, the scrubber.

Nothing here writes a record. What is tested is what every later bridge card stands on: a value that must
not leave the laptop does not, a name OneDrive refuses is never produced, and the folder is one somebody
chose, outside every checkout and outside the fleet's own directory.
"""
from __future__ import annotations
import json
import os

import pytest

from agentdata import textio
from agentdata.fleet import approval, bridge, registry
from agentdata.fleet.registry import Registry

from test_fleet_board_desk import a_project, site_facts
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

TOKEN = "Zq3v9Kx-run-token-8yP2mW4tL0aa"


@pytest.fixture()
def site(fleet_home, tmp_path, monkeypatch):                    # noqa: F811 - the fixture is the argument
    """One registered project carrying the four site facts, a running desk's token, and a known user and host."""
    monkeypatch.setenv("USERNAME", "lwinters")
    monkeypatch.setenv("COMPUTERNAME", "LT-RDSD-0042")
    path = site_facts(a_project(tmp_path, "luna"))
    os.makedirs(str(fleet_home), exist_ok=True)
    with open(os.path.join(str(fleet_home), "serve.json"), "w", encoding="utf-8") as f:
        json.dump({"url": f"http://127.0.0.1:8765/?t={TOKEN}", "token": TOKEN}, f)
    return path


# ------------------------------------------------------------------------ Scrubber, names, folder


def test_the_outbox_payload_never_contains_the_run_token_a_site_hostname_a_unc_path_or_a_raw_agent_out_path(site):
    text = ("Checked teradata-prod.corp.example as svc_rdsd_ro, wrote to \\\\share\\dpm\\runs, opened "
            "C:\\Program Files\\TabularEditor 3\\TabularEditor.exe; the desk is "
            f"http://127.0.0.1:8765/?t={TOKEN}. Rows in .agent/out/RDSD-1/rows.tsv, copy at "
            "\\\\fs01.corp.example\\team\\drop\\x.xlsx and D:/exports/rdsd/q3.csv, host "
            "etl-07.dc2.corp.example; lwinters on LT-RDSD-0042 in " + site + ".")
    out = bridge.Scrubber().scrub(text, 2000)
    for leaked in ("teradata-prod", "corp.example", "svc_rdsd_ro", "\\\\share", "share\\dpm", "TabularEditor",
                   "Program Files", TOKEN, "fs01", "D:/exports", "q3.csv", "etl-07", "RDSD-1/rows.tsv",
                   "lwinters", "LT-RDSD-0042", site, textio.norm_path(site)):
        assert leaked not in out, (leaked, out)
    assert ".agent/out/rows.tsv" in out, "the operator still learns which file an approval sends"
    assert "<fact:td_host>" in out and "<fact:sql_user>" in out
    assert "<unc>" in out and "<path>" in out and "<user>" in out and "<host>" in out

    # scrub_obj walks every string leaf, at any depth, and leaves the rest alone.
    obj = bridge.Scrubber().scrub_obj({"why": "ran on teradata-prod.corp.example", "n": 3,
                                       "qs": [{"q": f"token {TOKEN}?"}], "ok": True})
    assert obj == {"why": "ran on <fact:td_host>", "n": 3, "qs": [{"q": "token <redacted>?"}], "ok": True}

    # A credential shape goes first, through events.redact(); and the limit holds, with its ellipsis.
    assert "ghp_" not in bridge.Scrubber().scrub("key ghp_abcdefghijklmnopqrstuvwxyz0123", 300)
    cut = bridge.Scrubber().scrub("x" * 500, bridge.LIMITS["says"])
    assert len(cut) == bridge.LIMITS["says"] and cut.endswith("…")


def test_a_link_fact_host_is_kept_and_any_other_dotted_host_is_scrubbed(site):
    with open(os.path.join(site, "AGENTS.md"), "a", encoding="utf-8", newline="\n") as f:
        f.write("- bitbucket_url: https://bitbucket.corp.example/scm\n"
                "- confluence_base: https://wiki.corp.example/confluence\n")
    s = bridge.Scrubber()
    out = s.scrub("see https://example.atlassian.net/browse/RDSD-1, https://bitbucket.corp.example/scm/x "
                  "and https://wiki.corp.example/confluence/p, not https://build.other.example/job", 1000)
    assert "https://example.atlassian.net/browse/RDSD-1" in out
    assert "bitbucket.corp.example" in out and "wiki.corp.example" in out
    assert "build.other.example" not in out and "https://<host>/job" in out


def test_onedrive_reserved_characters_and_a_leading_tilde_never_appear_in_a_file_name():
    names = ["RDSD#1", "50%-done", "~lock", "~~con", "con", "NUL.json", "aux.decision.json",
             'a<b>c:d"e/f\\g|h?i*j', "x" * 200, "", "~", "#%", "trailing. ", "lpt1"]
    for raw in names:
        got = bridge.safe_file_name(raw)
        assert got, raw
        assert len(got) <= bridge.NAME_MAX, (raw, got)
        assert not any(ch in got for ch in '#%<>:"/\\|?*'), (raw, got)
        assert not got.startswith("~"), (raw, got)
        assert got.split(".", 1)[0].lower() not in textio.RESERVED_NAMES, (raw, got)
        assert not got.endswith((" ", ".")), (raw, got)
    assert bridge.safe_file_name("luna-jira-transition-20260927T100000-ab12.json") == \
        "luna-jira-transition-20260927T100000-ab12.json", "an ordinary name passes through"


def test_a_folder_inside_a_registered_checkout_or_the_fleet_dir_is_refused_by_name(site, tmp_path):
    inside = os.path.join(site, "sub", "FleetAgent")
    with pytest.raises(bridge.BridgeError) as e:
        bridge.check_folder({"fleet": {"mobile": {"enabled": True, "folder": inside}}})
    assert e.value.code == "mobile_folder_in_repo" and "luna" in e.value.msg and e.value.hint
    with pytest.raises(bridge.BridgeError) as e:
        bridge.check_folder({"fleet": {"mobile": {"enabled": True, "folder": site}}})
    assert e.value.code == "mobile_folder_in_repo"

    under_fleet = os.path.join(registry.fleet_dir(), "mobile")
    with pytest.raises(bridge.BridgeError) as e:
        bridge.check_folder({"fleet": {"mobile": {"enabled": True, "folder": under_fleet}}})
    assert e.value.code == "mobile_folder_in_repo"
    assert not os.path.exists(inside) and not os.path.exists(under_fleet)

    # A sibling whose name only starts like the checkout's is not inside it.
    beside = site.rstrip("/\\") + "-mobile"
    got = bridge.check_folder({"fleet": {"mobile": {"enabled": True, "folder": beside}}})
    assert got == textio.norm_path(os.path.abspath(beside)) and not os.path.exists(beside)


def test_a_folder_that_is_not_configured_is_refused_and_nothing_is_created(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    Registry()
    with pytest.raises(bridge.BridgeError) as e:
        bridge.check_folder({"fleet": {"mobile": {"enabled": True}}})
    assert e.value.code == "mobile_folder_unset" and "fleet.mobile.folder" in e.value.hint
    with pytest.raises(bridge.BridgeError) as e:
        bridge.check_folder({"fleet": {"mobile": {"enabled": True, "folder": "   "}}})
    assert e.value.code == "mobile_folder_unset"

    chosen = tmp_path / "OneDrive - Contoso" / "FleetAgent"
    with pytest.raises(bridge.BridgeError) as e:
        bridge.check_folder({"fleet": {"mobile": {"folder": str(chosen)}}})
    assert e.value.code == "mobile_disabled"

    # The folder resolves through config.expand at read time, and is never made here.
    monkeypatch.setenv("OneDriveCommercial", str(tmp_path / "OneDrive - Contoso"))
    got = bridge.check_folder({"fleet": {"mobile": {"enabled": True, "folder": "%OneDriveCommercial%/FleetAgent"
                                                    if os.name == "nt" else "$OneDriveCommercial/FleetAgent"}}})
    assert got == textio.norm_path(str(chosen))
    assert not (tmp_path / "OneDrive - Contoso").exists(), "check_folder created a directory"


def test_settings_reads_the_five_keys_with_their_defaults_and_coercions():
    s = bridge.settings({})
    assert s == {"enabled": False, "folder": "", "operator": "", "expire_s": 900, "expire_invalid": False,
                 "notify": True}
    assert bridge.settings({"fleet": {"mobile": {"expire_s": "abc"}}})["expire_s"] == 900
    assert bridge.settings({"fleet": {"mobile": {"expire_s": "abc"}}})["expire_invalid"] is True
    assert bridge.settings({"fleet": {"mobile": {"expire_s": 5000}}})["expire_s"] == 3600
    assert bridge.settings({"fleet": {"mobile": {"expire_s": 10}}})["expire_s"] == 60
    assert bridge.settings({"fleet": {"mobile": {"expire_s": "120"}}})["expire_s"] == 120
    on = bridge.settings({"fleet": {"mobile": {"enabled": "yes", "notify": "off", "operator": " op@contoso.com "}}})
    assert on["enabled"] is True and on["notify"] is False and on["operator"] == "op@contoso.com"


def test_canonical_is_one_function_and_survives_a_pretty_round_trip(tmp_path):
    assert bridge.canonical is approval.canonical
    obj = {"z": [1, 2, {"b": "ü", "a": None}], "a": "RDSD-1 → In Review", "n": 1.5}
    path = tmp_path / "pretty.json"
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    assert bridge.canonical(json.loads(path.read_text(encoding="utf-8"))) == bridge.canonical(obj)
    assert bridge.MOBILE_SCHEMA == 1 and bridge.MOBILE_CONTRACT == 1
