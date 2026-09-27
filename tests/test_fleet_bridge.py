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


def test_a_version_number_is_not_a_host_but_an_address_still_is(site):
    """`_HOST` took any three dotted labels for a host, so the phone read `released <host>` for
    `released 0.17.0` (#546's `says` and approval summaries). No DNS name ends in a numeric label
    and a three-part number is no IPv4 address: `v?N.N.N` is kept. A four-part address is not."""
    s = bridge.Scrubber()
    out = s.scrub("bumped to 0.17.0, pandas 2.2.3 and v1.4.10 on python 3.12.3; db at 10.20.30.40, "
                  "ip-10.0.0.1 and etl-07.dc2.corp.example; build 0.17.0.1 and 1.2.3.corp.example", 1000)
    for kept in ("0.17.0", "2.2.3", "v1.4.10", "3.12.3"):
        assert kept in out, (kept, out)
    for leaked in ("10.20.30.40", "10.0.0.1", "etl-07", "corp.example", "0.17.0.1"):
        assert leaked not in out, (leaked, out)


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


# ------------------------------------------------------------------------------------------- Exporter
#
# Hand-built snapshots (the shape `serve.fleet_snapshot()` answers) and `fleet_home`: no server, no process.

import threading
import time

from agentdata.fleet import events as E

# Everything a snapshot row carries that must never reach the phone (#546), with a value that would be seen.
LEAKY = {"path": "/home/lwinters/src/luna", "pid": 48213, "console": {"pid": 48214, "session": "s", "host": "LT"},
         "recent": [{"kind": "assistant_text", "data": {"text": "rows: 1,2,3"}}], "trace": [0] * 60,
         "scope_report": {"outside": ["secret.tmdl"]}, "adoptable": {"pid": 9}, "not_supervised_sentence": "n",
         "earlier": [{"n": 1}], "sessions_n": 2, "polls": {"jira": {"ok": True}}, "stale": {"stale": False},
         "accent": "#3FB950", "jira_project": "RDSD", "worktree_of": "", "as_of": 7, "last_seq": 42,
         "model_source": "config", "effort_source": "config", "external_how": "", "fleet_model": "gpt-5",
         "fleet_effort": "high"}


def _row(repo, **over):
    row = {"repo": repo, "project": repo, "state": "running", "why": "a turn is in flight",
           "last_said": "reading the ticket", "ticket": "RDSD-118", "at": "2026-09-26T09:14:05",
           "last_event_age_s": 12, "needs_human": False, "supervised": True, "external": False,
           "asked": [], "model": "claude-sonnet-4.5", "actual": "", "effort": "",
           "spend": {"total": 4.3, "today": 1.2, "budget": 10.0, "turns": 12, "session": 1.0, "rate": 0.3,
                     "sessions": 1},
           "run": {"n": 3, "origin": "fleet", "live": True, "since_start": True, "resumed": False, "events": None,
                   "events_n": 40, "session": "abc"},
           **LEAKY}
    row.update(over)
    return row


def _request(repo="luna", payload=None, kind="jira-transition", created=None):
    """A pending request on disk, as `approval.require()` writes one (digest included)."""
    id = approval.new_id(repo, kind)
    record = {"id": id, "repo": repo, "ticket": "RDSD-131", "kind": kind, "summary": "Transition RDSD-131",
              "payload": {"key": "RDSD-131", "transition": "In Review"} if payload is None else payload,
              "created": created or time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "pid": 48213}
    record["digest"] = approval.digest(record)
    os.makedirs(approval.approvals_dir(), exist_ok=True)
    textio.write_json(os.path.join(approval.approvals_dir(), f"{id}.json"), record)
    return record


def _cfg(tmp_path, **fleet):
    return {"fleet": {"mobile": {"enabled": True, "folder": str(tmp_path / "OneDrive" / "FleetAgent"),
                                 "operator": "operator@example.com"}, **fleet}}


def _outbox(cfg):
    root = bridge.outbox_dir(bridge.check_folder(cfg))
    return sorted(os.path.relpath(os.path.join(d, n), root).replace("\\", "/")
                  for d, _, names in os.walk(root) for n in names)


def _load(cfg, rel):
    return textio.read_json(os.path.join(bridge.outbox_dir(bridge.check_folder(cfg)), rel), rel)


def _exported(repo):
    return [e for e in E.read(repo) if e["kind"] == "mobile.exported"]


def test_the_attention_row_has_exactly_the_allow_listed_keys_and_nothing_from_the_snapshot_row_leaks(site, tmp_path):
    cfg = _cfg(tmp_path)
    request = _request("luna")
    snap = {"repos": [_row("luna", state="waiting_approval", needs_human=True, why="waiting on an approval"),
                      _row("uat", ticket="not a ticket", actual="gpt-5.1")],
            "approvals": approval.pending(), "fleet_dir": registry.fleet_dir(), "server": {"token": TOKEN},
            "desk": {"w": "main"}, "theme": {"name": "graph"}}
    now = time.time()
    got = bridge.export_once(cfg, snap, now=now)

    stamp = time.strftime("%Y%m%d-%H%M", time.gmtime(now))
    assert _outbox(cfg) == sorted(["attention/luna-1.json", "attention/uat-1.json",
                                   f"approvals/{request['id']}.json", f"heartbeat/{stamp}.json"])
    assert len(got["written"]) == 4 and got["how"] == ["atomic"]

    for name in ("attention/luna-1.json", "attention/uat-1.json"):
        row = _load(cfg, name)
        assert set(row) == bridge.ATTENTION_KEYS, set(row) ^ bridge.ATTENTION_KEYS
        for key in LEAKY:
            assert key not in row
        text = json.dumps(row)
        for leaked in ("/home/lwinters", "48213", "48214", "secret.tmdl", "rows: 1,2,3", TOKEN, "fleet_dir",
                       registry.fleet_dir(), "#3FB950", '"gpt-5"', '"config"', '"high"'):
            assert leaked not in text, (leaked, name)

    luna, uat = _load(cfg, "attention/luna-1.json"), _load(cfg, "attention/uat-1.json")
    assert luna["approvals"] == [request["id"]] and luna["approval_id"] == request["id"]
    assert (luna["state"], luna["role"], luna["needs_human"]) == ("waiting_approval", "waiting", True)
    assert luna["seq"] == 1 and luna["ticket"] == "RDSD-118" and uat["ticket"] == ""
    assert uat["approvals"] == [] and uat["approval_id"] == "" and uat["model"] == "gpt-5.1"
    assert luna["model"] == "claude-sonnet-4.5"
    assert luna["spend"] == {"total": 4.3, "today": 1.2, "budget": 10.0, "turns": 12,
                             "line": "4.3 premium · of 10.0 · 12 turns"}
    assert luna["run"] == {"n": 3, "origin": "fleet", "live": True, "since_start": True, "resumed": False}
    assert luna["digest"] == bridge.attention_digest(luna)

    # A second pass within the minute writes nothing; the approval was announced on luna's stream once.
    again = bridge.export_once(cfg, snap, now=now + 30)
    assert again["written"] == [] and again["unchanged"] == 3
    assert [e["data"]["id"] for e in _exported("luna")] == [request["id"]] and _exported("uat") == []


def test_an_attention_file_is_rewritten_only_when_its_digest_changes(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    now = time.time()
    bridge.export_once(cfg, {"repos": [_row("luna")], "approvals": []}, now=now)
    first = _load(cfg, "attention/luna-1.json")
    path = os.path.join(bridge.outbox_dir(bridge.check_folder(cfg)), "attention", "luna-1.json")
    before = (os.path.getmtime(path), open(path, "rb").read())

    # Only the age moved: the digest is the same, so nothing is written.
    assert bridge.export_once(cfg, {"repos": [_row("luna", last_event_age_s=95)], "approvals": []},
                              now=now + 60)["written"] == []

    # A new `why` is a new file, `-2`, and the old one is untouched.
    got = bridge.export_once(cfg, {"repos": [_row("luna", why="asked which date window to use")],
                                   "approvals": []}, now=now + 90)
    assert [os.path.basename(p) for p in got["written"]] == ["luna-2.json"]
    second = _load(cfg, "attention/luna-2.json")
    assert second["seq"] == 2 and second["digest"] != first["digest"]
    assert second["says"] == "asked which date window to use"
    assert (os.path.getmtime(path), open(path, "rb").read()) == before
    assert bridge.read_state()["attention_seq"] == {"luna": 2}


def test_a_pending_approval_is_mirrored_once_with_a_preview_and_a_decision_mirror_follows(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path, approval_timeout=600)
    request = _request("luna", created="2026-09-26T09:12:00")
    snap = {"repos": [_row("luna")], "approvals": approval.pending()}
    now = time.time()
    bridge.export_once(cfg, snap, now=now)

    mirror = _load(cfg, f"approvals/{request['id']}.json")
    assert mirror["digest"] == approval.digest(request) == request["digest"]
    assert (mirror["created"], mirror["expires"]) == ("2026-09-26T09:12:00Z", "2026-09-26T09:22:00Z")
    assert mirror["payload_preview"] == {"key": "RDSD-131", "transition": "In Review"}
    assert mirror["payload_truncated"] is False and mirror["payload_bytes"] == len(bridge.canonical(request["payload"]))
    assert "payload" not in mirror and "pid" not in mirror and "48213" not in json.dumps(mirror)
    assert mirror["approval_kind"] == "jira-transition" and mirror["kind"] == "approval"

    # The laptop decides; the next pass mirrors the decision (and luna's row, whose approvals emptied), and a pass
    # after that writes nothing.
    approval.decide(request["id"], approval.DENIED, reason="wrong column", by="operator")
    snap = {"repos": [_row("luna")], "approvals": approval.pending()}
    got = bridge.export_once(cfg, snap, now=now + 5)
    assert [os.path.basename(p) for p in got["written"]] == ["luna-2.json", f"{request['id']}.decision.json"]
    assert _load(cfg, "attention/luna-2.json")["approvals"] == []
    decided = _load(cfg, f"approvals/{request['id']}.decision.json")
    assert {k: decided[k] for k in ("id", "decision", "reason", "via", "digest", "late")} == {
        "id": request["id"], "decision": "denied", "reason": "wrong column", "via": "laptop",
        "digest": request["digest"], "late": False}
    assert "nonce" not in decided
    assert bridge.export_once(cfg, snap, now=now + 10)["written"] == []
    assert len(_exported("luna")) == 1


def test_a_payload_over_the_cap_is_truncated_and_says_so_while_the_digest_covers_all_of_it(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    big = {"key": "RDSD-131", "body": "é" * 6000}            # 12,000 bytes of UTF-8: over 8 KB canonical
    request = _request("luna", payload=big)
    bridge.export_once(cfg, {"repos": [], "approvals": approval.pending()}, now=time.time())
    mirror = _load(cfg, f"approvals/{request['id']}.json")
    size = len(bridge.canonical(big))
    assert size > bridge.LIMITS["preview_bytes"]
    assert mirror["payload_truncated"] is True and mirror["payload_bytes"] == size
    assert mirror["payload_preview"]["truncated"] is True and mirror["payload_preview"]["bytes"] == size
    head = mirror["payload_preview"]["head"]
    assert head and len(head.encode("utf-8")) <= bridge.LIMITS["preview_head"] and bridge.canonical(big).decode().startswith(head)
    assert set(mirror["payload_preview"]) == {"truncated", "bytes", "head"}
    # The digest is the whole request's, not the preview's: changing a byte past the head changes it.
    assert mirror["digest"] == approval.digest(request)
    assert approval.digest({**request, "payload": {**big, "body": big["body"][:-1] + "e"}}) != mirror["digest"]


def test_files_are_written_atomically_so_a_concurrent_reader_never_parses_a_partial_file(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    root = bridge.outbox_dir(bridge.check_folder(cfg))
    stop, seen, bad, staging = threading.Event(), set(), [], set()

    def reader():
        while not stop.is_set():
            for d, _, names in os.walk(root):
                for n in names:
                    path = os.path.join(d, n)
                    if n.endswith(".tmp"):
                        staging.add(n)             # textio's staging sibling: never a `.json` name
                        continue
                    try:
                        with open(path, encoding="utf-8") as f:
                            json.loads(f.read())
                        seen.add(n)
                    except FileNotFoundError:
                        pass
                    except ValueError as e:
                        bad.append((n, str(e)))

    t = threading.Thread(target=reader)
    t.start()
    hows = set()
    try:
        now = time.time()
        for i in range(200):
            got = bridge.export_once(cfg, {"repos": [_row("luna", why=f"step {i} " + "x" * 2000)], "approvals": []},
                                     now=now + i)
            hows.update(got["how"])
    finally:
        stop.set()
        t.join()
    assert bad == [], bad[:3]
    assert all(n.endswith(".json") for n in seen) and not any(n.endswith(".json") for n in staging)
    assert len([n for n in os.listdir(os.path.join(root, "attention"))]) == 200
    assert not [n for _, _, names in os.walk(root) for n in names if n.endswith(".tmp")], "a staging file was left"
    if os.name != "nt":
        assert hows == {"atomic"}


def test_the_heartbeat_names_no_hostname_and_no_pid(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    import socket

    monkeypatch.setenv("COMPUTERNAME", "LT-RDSD-0042")
    os.makedirs(str(fleet_home), exist_ok=True)
    with open(os.path.join(str(fleet_home), "serve.json"), "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "port": 8765, "token": TOKEN}, f)
    cfg = _cfg(tmp_path)
    now = time.time()
    first = bridge.export_once(cfg, {"repos": [_row("luna", needs_human=True)], "approvals": []}, now=now)
    beat_path = [p for p in first["written"] if "/heartbeat/" in p][0]
    beat = textio.read_json(beat_path, "heartbeat")
    assert set(beat) == {"schema", "kind", "at", "every_s", "expire_s", "contract", "operator", "bridge",
                         "laptop_id", "serve_up", "desk_streams", "counts", "inbox_last_seen"}
    assert beat["every_s"] == 300 and beat["contract"] == 1 and beat["serve_up"] is True
    assert beat["counts"] == {"repos": 1, "needs_human": 1, "approvals_pending": 0, "notifications_24h": 0,
                              "rejected_24h": 0}
    text = json.dumps(beat)
    for leaked in ("LT-RDSD-0042", socket.gethostname(), TOKEN, str(fleet_home)):
        assert leaked not in text, leaked
    assert "pid" not in beat and os.getpid() not in [v for v in beat.values() if isinstance(v, int)]
    assert len(beat["laptop_id"]) == 32 and int(beat["laptop_id"], 16) >= 0

    # Within 300 s there is no second beat; after it, the same laptop id, in a newly named file.
    assert not [p for p in bridge.export_once(cfg, {"repos": [], "approvals": []}, now=now + 200)["written"]]
    later = bridge.export_once(cfg, {"repos": [], "approvals": []}, now=now + 300)["written"]
    assert len(later) == 1 and later[0] != beat_path
    assert textio.read_json(later[0], "heartbeat")["laptop_id"] == beat["laptop_id"]
    assert bridge.read_state()["laptop_id"] == beat["laptop_id"] != os.environ["COMPUTERNAME"]


def test_decided_pairs_and_old_notifications_are_pruned_and_pending_requests_never_are(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    folder = bridge.check_folder(cfg)
    now = time.time()
    day, week = 24 * 3600, 7 * 24 * 3600

    def put(rel, age):
        path = os.path.join(folder, rel)
        textio.write_json(path, {"schema": 1})
        os.utime(path, (now - age, now - age))
        return rel

    old = {put("outbox/approvals/a-old.json", day + 60), put("outbox/approvals/a-old.decision.json", day + 60),
           put("outbox/notifications/20260925T0900Z-luna-needs_human-3.json", day + 60),
           put("outbox/results/n1.result.json", day + 60), put("outbox/heartbeat/20260925-0900.json", day + 60),
           put("outbox/attention/luna-1.json", day + 120), put("processed/decision-n1.json", week + 60),
           put("rejected/decision-n2.json", week + 60), put("rejected/decision-n2.json.why.json", week + 60)}
    kept = {put("outbox/approvals/a-new.json", 60), put("outbox/approvals/a-new.decision.json", 60),
            put("outbox/approvals/pending-ancient.json", 30 * day),   # no decision beside it: never pruned
            put("outbox/notifications/20260926T0900Z-luna-needs_human-4.json", 60),
            put("outbox/results/n2.result.json", 60), put("outbox/heartbeat/20260926-0900.json", 60),
            put("outbox/attention/luna-2.json", day + 60),            # the newest of its repo, however old
            put("outbox/attention/uat-7.json", day + 60),
            put("processed/decision-n3.json", 3 * day)}
    state = {"processed": {"n-old": {"at": bridge._utc(now - 2 * day)}, "n-new": {"at": bridge._utc(now - 60)}},
             "exported": {"a-old": {"decided": True}, "pending-ancient": {"decided": False}}}

    removed = bridge.prune(folder, state, now)
    assert {os.path.relpath(p, folder).replace("\\", "/") for p in removed} == old
    for rel in kept:
        assert os.path.exists(os.path.join(folder, rel)), rel
    assert set(state["processed"]) == {"n-new"} and set(state["exported"]) == {"pending-ancient"}
    assert bridge.prune(folder, state, now) == []


def test_a_result_names_its_decision_or_its_reply_and_says_applied_or_rejected(fleet_home, tmp_path):  # noqa: F811
    folder = bridge.check_folder(_cfg(tmp_path))
    ok = textio.read_json(bridge.write_result(folder, "9f2c4b7e", "decision", True, id="luna-x-1"), "result")
    assert {k: ok[k] for k in ("kind", "nonce", "kind_of", "id", "ok", "result", "code")} == {
        "kind": "result", "nonce": "9f2c4b7e", "kind_of": "decision", "id": "luna-x-1", "ok": True,
        "result": "applied", "code": ""}
    assert "repo" not in ok and "via" not in ok and "answered" not in ok
    no = textio.read_json(bridge.write_result(folder, "c0d3", "reply", False, repo="luna", code="mid_turn",
                                              error="a turn is in flight", hint="wait", via="send",
                                              answered=["q1"]), "result")
    assert (no["result"], no["repo"], no["via"], no["answered"], no["code"]) == (
        "rejected", "luna", "send", ["q1"], "mid_turn")
    assert sorted(os.listdir(bridge.outbox_dir(folder, "results"))) == ["9f2c4b7e.result.json", "c0d3.result.json"]
    with pytest.raises(bridge.BridgeError):
        bridge.write_result(folder, "n", "vote", True)


# --------------------------------------------------------------------------------- Applier: decisions
#
# A real `require()` on a thread (the `_answer` pattern of `test_fleet_approval.py`), the phone's file dropped into
# `inbox/` by hand, and one `apply_once` per tick: no server, no flow. Every refusal must leave no decision file.

import uuid

from agentdata.fleet import agentstate

from test_fleet_approval import _wait_for_request, as_agent  # noqa: F401 - a fixture, used by name

UPN = "operator@example.com"


def _folder(cfg):
    return bridge.check_folder(cfg)


def _phone(request, *, nonce=None, by=UPN, decision="approved", reason="", issued=None, expires=None, **over):
    """What `FleetDecide` writes: a GUID without dashes, `yyyy-MM-ddTHH:mm:ssZ` times, the invoker's UPN."""
    now = time.time()
    record = {"schema": 1, "kind": "decision", "nonce": nonce or uuid.uuid4().hex,
              "issued": bridge._utc(now if issued is None else issued),
              "expires": bridge._utc(now + 600 if expires is None else expires),
              "by": by, "id": request["id"], "digest": request["digest"], "decision": decision, "reason": reason,
              "device": "iOS"}
    record.update(over)
    return record


def _drop(cfg, record=None, name=None, *, raw=None) -> str:
    inbox = os.path.join(_folder(cfg), "inbox")
    os.makedirs(inbox, exist_ok=True)
    name = name or f"decision-{record['nonce']}.json"
    with open(os.path.join(inbox, name), "wb") as f:
        f.write(raw if raw is not None else json.dumps(record).encode("utf-8"))
    return name


def _why(cfg, name):
    return textio.read_json(os.path.join(_folder(cfg), "rejected", name + ".why.json"), "why")


def _result(cfg, nonce):
    return textio.read_json(bridge.outbox_dir(_folder(cfg), "results", f"{nonce}.result.json"), "result")


def _inbox_names(cfg):
    try:
        return sorted(os.listdir(os.path.join(_folder(cfg), "inbox")))
    except OSError:
        return []


def _events(repo, kind):
    return [e for e in E.read(repo) if e["kind"] == kind]


def _require(result: dict, **kw) -> threading.Thread:
    def agent():
        result["d"] = approval.require("jira-transition", "RDSD-131: In Progress -> In Review",
                                       {"key": "RDSD-131", "transition": "31 In Review"}, ticket="RDSD-131",
                                       poll=0.02, **kw)

    t = threading.Thread(target=agent, daemon=True)
    t.start()
    return t


def test_a_matching_decision_is_applied_with_by_mobile_upn_and_via_mobile_and_the_agent_is_released(as_agent, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    result: dict = {}
    t = _require(result, timeout=20)
    request = approval.read_request(_wait_for_request())
    record = _phone(request)
    name = _drop(cfg, record)

    assert bridge.apply_once(cfg) == {"applied": 1, "rejected": 0, "retried": 0}
    t.join(timeout=10)
    d = result["d"]
    assert d.ok and d.by == f"mobile:{UPN}" and d.via == "mobile" and d.id == request["id"]

    decided = approval.read_decision(request["id"])
    assert (decided["via"], decided["digest"], decided["nonce"]) == ("mobile", request["digest"], record["nonce"])
    assert decided["by"] == f"mobile:{UPN}" and decided["late"] is False

    folder = _folder(cfg)
    assert _inbox_names(cfg) == []
    assert os.path.isfile(os.path.join(folder, "processed", name))
    sidecar = textio.read_json(os.path.join(folder, "processed", name + ".result.json"), "sidecar")
    assert (sidecar["ok"], sidecar["result"], sidecar["kind_of"], sidecar["nonce"]) == (
        True, "applied", "decision", record["nonce"])
    res = _result(cfg, record["nonce"])
    assert (res["ok"], res["result"], res["id"], res["late"]) == (True, "applied", request["id"], False)

    mirror = _load(cfg, f"approvals/{request['id']}.decision.json")
    assert (mirror["via"], mirror["nonce"], mirror["decision"], mirror["late"]) == (
        "mobile", record["nonce"], "approved", False)

    [ev] = _events("luna", "mobile.decision")
    assert ev["data"] == {"id": request["id"], "kind": "decision", "decision": "approved", "by": f"mobile:{UPN}",
                          "nonce": record["nonce"], "late": False}
    assert bridge.read_state()["processed"][record["nonce"]]["code"] == ""
    # The next tick finds nothing to do.
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 0, "retried": 0}


def test_a_digest_mismatch_is_refused_and_no_decision_file_is_written(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    request = _request("luna")
    record = _phone(request, digest="0" * 64)
    name = _drop(cfg, record)
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 1, "retried": 0}
    assert _why(cfg, name)["code"] == "mobile_digest_mismatch"
    assert approval.read_decision(request["id"]) == {}
    assert os.path.isfile(os.path.join(_folder(cfg), "rejected", name)) and _inbox_names(cfg) == []
    res = _result(cfg, record["nonce"])
    assert (res["ok"], res["result"], res["code"]) == (False, "rejected", "mobile_digest_mismatch")
    assert approval.pending() and approval.pending()[0]["id"] == request["id"], "the request still waits"


def test_an_expired_decision_is_refused(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    request = _request("luna")
    now = time.time()
    past = _drop(cfg, _phone(request, issued=now - 1200, expires=now - 300))
    # Still in the future, but further from `issued` than `expire_s` (900) allows.
    too_far = _drop(cfg, _phone(request, issued=now, expires=now + 900 + 60))
    assert bridge.apply_once(cfg)["rejected"] == 2
    assert _why(cfg, past)["code"] == _why(cfg, too_far)["code"] == "mobile_expired"
    assert approval.read_decision(request["id"]) == {}

    # Inside the window, and with the configured `expire_s`, the same shape applies.
    assert bridge.apply_once(_cfg(tmp_path)) == {"applied": 0, "rejected": 0, "retried": 0}
    _drop(cfg, _phone(request, issued=now, expires=now + 900))
    assert bridge.apply_once(cfg)["applied"] == 1


def test_a_decision_from_the_wrong_operator_is_refused_case_insensitively_for_the_right_one(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    request = _request("luna")
    wrong = _drop(cfg, _phone(request, by="someone.else@example.com"))
    assert bridge.apply_once(cfg)["rejected"] == 1
    assert _why(cfg, wrong)["code"] == "mobile_wrong_operator"
    assert approval.read_decision(request["id"]) == {}

    # No operator configured: nobody may decide from the phone.
    unset = _cfg(tmp_path)
    unset["fleet"]["mobile"]["operator"] = ""
    nobody = _drop(unset, _phone(request))
    assert bridge.apply_once(unset)["rejected"] == 1 and _why(cfg, nobody)["code"] == "mobile_wrong_operator"
    assert approval.read_decision(request["id"]) == {}

    right = _phone(request, by="OPERATOR@Example.COM")
    _drop(cfg, right)
    assert bridge.apply_once(cfg)["applied"] == 1
    assert approval.read_decision(request["id"])["by"] == "mobile:OPERATOR@Example.COM"


def test_the_same_nonce_is_refused_the_second_time_even_under_a_conflict_copy_name(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    request, other = _request("luna"), _request("luna", kind="jira-comment")
    record = _phone(request)
    _drop(cfg, record)
    assert bridge.apply_once(cfg)["applied"] == 1

    # OneDrive's `<name>-<DEVICE>` copy of the same file: the nonce decides, never the name.
    copy = _drop(cfg, record, f"decision-{record['nonce']}-LT-RDSD-0042.json")
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 1, "retried": 0}
    assert _why(cfg, copy)["code"] == "mobile_replay"
    assert _result(cfg, record["nonce"])["result"] == "applied", "a replay never overwrites the verdict"

    # The same nonce naming another request is a replay too, and the sidecars remember it without the state file.
    bridge.update_state(lambda s: s["processed"].clear())
    again = _drop(cfg, {**_phone(other), "nonce": record["nonce"]}, "decision-resurrected.json")
    assert bridge.apply_once(cfg)["rejected"] == 1
    assert _why(cfg, again)["code"] == "mobile_replay"
    assert approval.read_decision(other["id"]) == {}


def test_a_dead_or_absent_inbox_yields_no_decision_and_the_agents_timeout_refuses_the_write(as_agent, tmp_path,  # noqa: F811
                                                                                           monkeypatch, capsys):
    from test_fleet_approval import STORY, _jira_transition

    cfg = _cfg(tmp_path)
    assert not os.path.exists(os.path.join(_folder(cfg), "inbox"))
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 0, "retried": 0}

    result: dict = {}
    t = _require(result, timeout=1)
    while t.is_alive():                                   # the bridge ticks against the missing inbox
        bridge.apply_once(cfg)
        time.sleep(0.05)
    assert result["d"].state == approval.TIMEOUT
    assert approval.read_decision(result["d"].id) == {}

    # An empty inbox, and the gated command the agent actually runs.
    os.makedirs(os.path.join(_folder(cfg), "inbox"))
    out: dict = {}

    def agent():
        out["rc"], out["out"], out["op"], _ = _jira_transition(
            monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"], itype="Story", status="In Progress",
            transitions=STORY, cfg={"fleet": {"approval_timeout": 1}})

    g = threading.Thread(target=agent, daemon=True)
    g.start()
    while g.is_alive():
        assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 0, "retried": 0}
        time.sleep(0.05)
    assert out["rc"] == 2 and "refused: approval_timeout" in out["out"]
    assert not [c for c in out["op"].calls if c[0].startswith("POST")]


def test_a_bom_and_a_utf16_inbox_file_are_read_as_the_same_decision(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    request = _request("luna")
    record = _phone(request)
    text = json.dumps(record)
    _drop(cfg, name=f"decision-{record['nonce']}.json", raw=b"\xef\xbb\xbf" + text.encode("utf-8"))
    _drop(cfg, name=f"decision-{record['nonce']}-PHONE.json", raw=("﻿" + text).encode("utf-16-le"))
    assert bridge.apply_once(cfg) == {"applied": 1, "rejected": 1, "retried": 0}
    [why] = [n for n in os.listdir(os.path.join(_folder(cfg), "rejected")) if n.endswith(".why.json")]
    assert _why(cfg, why[:-len(".why.json")])["code"] == "mobile_replay"
    assert approval.read_decision(request["id"])["nonce"] == record["nonce"]
    assert len(_events("luna", "mobile.decision")) == 1


def test_a_file_over_16kb_or_that_is_not_json_is_rejected_without_being_parsed_further(fleet_home, tmp_path,  # noqa: F811
                                                                                       monkeypatch):
    cfg = _cfg(tmp_path)
    request = _request("luna")
    big = _phone(request, reason="x" * (17 * 1024))
    big_name = _drop(cfg, big)
    assert os.path.getsize(os.path.join(_folder(cfg), "inbox", big_name)) > bridge.INBOX_MAX_BYTES
    bad_name = _drop(cfg, name="decision-garbled.json", raw=b'{"schema": 1, "kind": "decision", "nonce": ')
    schema2 = _drop(cfg, _phone(request, schema=2))
    listish = _drop(cfg, name="decision-list.json", raw=b"[1, 2, 3]")

    read = []
    real = textio.read_json
    monkeypatch.setattr(bridge.textio, "read_json", lambda path, what="file": read.append(path) or real(path, what))
    assert bridge.apply_once(cfg)["rejected"] == 4
    assert not [p for p in read if p.endswith(big_name)], "a file over the cap was opened"

    assert _why(cfg, big_name)["code"] == "mobile_too_large"
    assert _why(cfg, bad_name)["code"] == "mobile_bad_json"
    assert _why(cfg, schema2)["code"] == _why(cfg, listish)["code"] == "mobile_bad_schema"
    assert not os.path.exists(bridge.outbox_dir(_folder(cfg), "results", f"{big['nonce']}.result.json")), \
        "the nonce of an unread file is not known"
    assert approval.read_decision(request["id"]) == {}


def test_every_refusal_lands_in_rejected_with_a_sidecar_naming_its_code_and_emits_mobile_rejected(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path)
    now = time.time()
    request = _request("luna")
    done = _request("luna", kind="jira-comment")
    approval.decide(done["id"], approval.APPROVED, by="operator")
    E.append("luna", [E.event("luna", "started", {"pid": 1}, ticket="RDSD-131"),
                      E.event("luna", "turn_started", {}, ticket="RDSD-131")])
    before = E.read("luna")
    cases = {
        "mobile_digest_mismatch": _phone(request, digest="f" * 64),
        "mobile_expired": _phone(request, issued=now - 1200, expires=now - 300),
        "mobile_wrong_operator": _phone(request, by="intruder@example.com"),
        "mobile_already_decided": _phone(done),
        "mobile_bad_schema": _phone(request, decision="maybe"),
        "mobile_reason_required": _phone(request, decision="denied", reason=" "),
        "mobile_bad_time": _phone(request, issued=now + 3600, expires=now + 3900),
    }
    names = {code: _drop(cfg, record) for code, record in cases.items()}
    unknown = _phone({"id": "luna-jira-transition-20260101T000000-dead", "digest": "a" * 64})
    unknown_name = _drop(cfg, unknown)
    token = _phone(request, by="intruder@example.com", reason="token=ghp_abcdefghijklmnopqrstuvwxyz0123")
    token_name = _drop(cfg, token)

    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": len(cases) + 2, "retried": 0}
    assert _inbox_names(cfg) == []
    for code, name in names.items():
        why = _why(cfg, name)
        assert why["code"] == code and why["error"] and why["hint"] and why["at"], why
        assert os.path.isfile(os.path.join(_folder(cfg), "rejected", name))
        assert _result(cfg, cases[code]["nonce"])["code"] == code
    assert _why(cfg, unknown_name)["code"] == "mobile_unknown_id"
    assert _why(cfg, token_name)["code"] == "mobile_wrong_operator"
    assert approval.read_decision(request["id"]) == {}
    assert approval.read_decision(unknown["id"]) == {}
    assert approval.read_decision(done["id"])["by"] == "operator", "a refusal never touches another decision"

    rejected = _events("luna", "mobile.rejected")
    by_nonce = {e["data"]["nonce"]: e["data"] for e in rejected}
    assert set(by_nonce) == {r["nonce"] for r in cases.values()} | {token["nonce"]}, \
        "an id no approval knows names no repo, so it is kept in rejected/ and the state file only"
    for code, record in cases.items():
        data = by_nonce[record["nonce"]]
        assert set(data) == {"nonce", "kind", "code", "why"} and data["code"] == code and data["kind"] == "decision"
        assert data["why"] and len(data["why"]) <= 200
    assert "ghp_" not in json.dumps(rejected)
    assert bridge.read_state()["processed"][unknown["nonce"]]["code"] == "mobile_unknown_id"
    assert bridge.read_state()["rejected_24h"] == len(cases) + 2

    # Additive: the fold reads the stream with the refusals exactly as it read it without them.
    def folded(events):
        return {k: v for k, v in agentstate.derive(events).items() if k != "at"}   # `at` is the newest event's time

    assert folded(E.read("luna")) == folded(before) and folded(before)["state"] == "running"
    fold = agentstate.Fold()
    for ev in before:
        fold.add(ev)
    snapshot = {k: v for k, v in agentstate.classify(fold).items() if k != "at"}
    for ev in rejected:
        fold.add(ev)
    assert {k: v for k, v in agentstate.classify(fold).items() if k != "at"} == snapshot


def test_a_file_that_fails_unexpectedly_twice_is_rejected_as_unreadable(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    cfg = _cfg(tmp_path)
    request = _request("luna")
    record = _phone(request)
    name = _drop(cfg, record)

    def boom(_record):
        raise RuntimeError("the disk said no")

    monkeypatch.setattr(bridge, "_check_decision", boom)
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 0, "retried": 1}, "the first failure is retried"
    assert _inbox_names(cfg) == [name]
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 1, "retried": 0}
    assert _why(cfg, name)["code"] == "mobile_unreadable" and _inbox_names(cfg) == []
    assert approval.read_decision(request["id"]) == {}


def test_a_denial_without_a_reason_is_refused_before_decide_is_reached(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    cfg = _cfg(tmp_path)
    request = _request("luna")
    calls = []
    with monkeypatch.context() as m:
        m.setattr(approval, "decide", lambda *a, **k: calls.append((a, k)))
        for reason in ("", "   "):
            name = _drop(cfg, _phone(request, decision="denied", reason=reason))
            assert bridge.apply_once(cfg)["rejected"] == 1
            assert _why(cfg, name)["code"] == "mobile_reason_required"
    assert calls == [] and approval.read_decision(request["id"]) == {}

    _drop(cfg, _phone(request, decision="denied", reason="wrong column"))
    assert bridge.apply_once(cfg)["applied"] == 1
    assert approval.read_decision(request["id"])["reason"] == "wrong column"


def test_a_late_decision_on_a_timed_out_request_is_recorded_as_late(fleet_home, tmp_path):  # noqa: F811
    cfg = _cfg(tmp_path, approval_timeout=60)
    # Created ten minutes ago: its agent's `require()` returned TIMEOUT long since, and a re-run is a new id.
    request = _request("luna", created=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 600)))
    record = _phone(request)
    _drop(cfg, record)
    assert bridge.apply_once(cfg)["applied"] == 1
    assert approval.read_decision(request["id"])["late"] is True
    assert _result(cfg, record["nonce"])["late"] is True
    assert _load(cfg, f"approvals/{request['id']}.decision.json")["late"] is True
    assert _events("luna", "mobile.decision")[0]["data"]["late"] is True

    # One inside the window is not late.
    fresh = _request("luna", kind="jira-comment")
    on_time = _phone(fresh)
    _drop(cfg, on_time)
    assert bridge.apply_once(cfg)["applied"] == 1
    assert _result(cfg, on_time["nonce"])["late"] is False


def test_a_move_that_fails_is_retried_on_the_next_tick_and_the_decision_is_applied_once(fleet_home, tmp_path,  # noqa: F811
                                                                                        monkeypatch):
    cfg = _cfg(tmp_path)
    request = _request("luna")
    record = _phone(request)
    name = _drop(cfg, record)
    with monkeypatch.context() as m:
        m.setattr(bridge, "_move", lambda src, dest: False)          # the sync client holds the file
        assert bridge.apply_once(cfg)["applied"] == 1
    assert _inbox_names(cfg) == [name] and approval.read_decision(request["id"])["nonce"] == record["nonce"]
    assert bridge.read_state()["processed"][record["nonce"]]["moved"] is False

    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 0, "retried": 1}
    assert _inbox_names(cfg) == [] and os.path.isfile(os.path.join(_folder(cfg), "processed", name))
    assert bridge.read_state()["processed"][record["nonce"]]["moved"] is True
    assert _result(cfg, record["nonce"])["result"] == "applied" and len(_events("luna", "mobile.decision")) == 1


# ----------------------------------------------------------------------------------- Applier: replies
#
# A reply is the desk's `act("answer" | "say" | "send")`, verbatim. The real supervisor runs against a fake launcher
# (the `spawns` fixture of `test_fleet_desk_switcher.py`) and the fake console helper (`tests/fakes/say_helper.py`):
# what is asserted is the argv that would have run, and the line the helper was handed. No process, no console.

import sys

from agentdata.fleet import lifecycle, supervisor

from test_fleet_desk_switcher import spawns                  # noqa: F401 - a fixture, used by name
from test_fleet_console import SAY_HELPER
from test_fleet import make_project


def _reply_cfg(tmp_path, monkeypatch, **fleet):
    """The bridge's config plus the fake console helper, and a session-state folder inside tmp_path."""
    monkeypatch.setenv("COPILOT_SESSION_STATE", str(tmp_path / "copilot" / "session-state"))
    monkeypatch.setenv("AGENTDATA_FAKE_SAY_LOG", str(tmp_path / "helper.jsonl"))
    monkeypatch.setenv("AGENTDATA_FAKE_SAY_FILE", "")
    monkeypatch.setenv("AGENTDATA_FAKE_SAY_FAIL", "")
    return _cfg(tmp_path, console={"host": "fake", "helper": [sys.executable, SAY_HELPER]}, **fleet)


def _typed(tmp_path) -> list[list[str]]:
    log = tmp_path / "helper.jsonl"
    return [json.loads(line)["argv"] for line in log.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if log.exists() else []


def _headless(tmp_path, name, session="sess-h1"):
    """A registered checkout whose last headless session can be resumed."""
    Registry().add(make_project(tmp_path / name, ticket="RDSD-9"), name=name)
    E.append(name, [E.event(name, "started", {"pid": 1}, ticket="RDSD-9"),
                    E.event(name, "session_id", {"session": session}, ticket="RDSD-9"),
                    E.event(name, "turn_ended", {"turn": "0"}, ticket="RDSD-9")])


def _in_console(tmp_path, name, session="sess-c1"):
    """A registered checkout with a console the fleet opened (this process stands in for its pid)."""
    path = make_project(tmp_path / name, ticket="RDSD-7")
    Registry().add(path, name=name)
    supervisor.write_lock(name, {"pid": os.getpid(), "kind": "console", "session": session, "repo": name,
                                 "path": path, "ticket": "RDSD-7", "started": time.time(), "restarts": 0,
                                 "launch": []})
    return path


def _reply(repo, *, message=None, answers=None, nonce=None, by=UPN, issued=None, expires=None, **over):
    """What `FleetDecide` writes for a reply: `repo`, `message` and/or `answers` as `[{id, answer}]`, `device`."""
    now = time.time()
    record = {"schema": 1, "kind": "reply", "nonce": nonce or uuid.uuid4().hex,
              "issued": bridge._utc(now if issued is None else issued),
              "expires": bridge._utc(now + 600 if expires is None else expires),
              "by": by, "repo": repo, "device": "iOS"}
    if message is not None:
        record["message"] = message
    if answers is not None:
        record["answers"] = answers
    record.update(over)
    return record


def _drop_reply(cfg, record) -> str:
    return _drop(cfg, record, name=f"reply-{record['nonce']}.json")


def test_a_reply_to_a_console_session_is_typed_and_a_reply_to_a_headless_one_is_sent(fleet_home, tmp_path,  # noqa: F811
                                                                                    monkeypatch, spawns):
    cfg = _reply_cfg(tmp_path, monkeypatch)
    spawns["alive"].add(os.getpid())                        # the console window's pid, as the launcher sees it
    _in_console(tmp_path, "luna")
    _headless(tmp_path, "sol", session="sess-sol")
    typed = _reply("luna", message="use the staging\nconnection string")
    sent = _reply("sol", message="  carry on with the second table  ")
    typed_name, sent_name = _drop_reply(cfg, typed), _drop_reply(cfg, sent)

    assert bridge.apply_once(cfg) == {"applied": 2, "rejected": 0, "retried": 0}
    # The console: one line, typed into the window by pid, the newline collapsed as `console.one_line` does.
    assert _typed(tmp_path) == [["say-into", str(os.getpid()), "use the staging connection string"]]
    assert spawns["launched"] and len(spawns["launched"]) == 1, "the console reply spawned nothing"
    # The headless agent: one `copilot -p --resume <session>` carrying the text, stripped as the desk strips it.
    [argv] = spawns["launched"]
    assert "--resume" in argv and argv[argv.index("--resume") + 1] == "sess-sol"
    assert "carry on with the second table" in argv

    folder = _folder(cfg)
    assert _inbox_names(cfg) == []
    for record, name, via in ((typed, typed_name, "say"), (sent, sent_name, "send")):
        res = _result(cfg, record["nonce"])
        assert (res["ok"], res["result"], res["kind_of"], res["repo"], res["via"], res["answered"]) == (
            True, "applied", "reply", record["repo"], via, [])
        assert os.path.isfile(os.path.join(folder, "processed", name))
        assert textio.read_json(os.path.join(folder, "processed", name + ".result.json"), "sidecar")["via"] == via
        assert bridge.read_state()["processed"][record["nonce"]]["code"] == ""

    # `mobile.reply` on the repo's own stream: who, how, which questions and how many words; never the words.
    [ev] = _events("luna", "mobile.reply")
    assert ev["data"] == {"nonce": typed["nonce"], "by": f"mobile:{UPN}", "via": "say", "answered": [], "words": 5}
    [ev] = _events("sol", "mobile.reply")
    assert ev["data"] == {"nonce": sent["nonce"], "by": f"mobile:{UPN}", "via": "send", "answered": [], "words": 6}
    assert "staging" not in json.dumps(_events("luna", "mobile.reply") + _events("sol", "mobile.reply"))
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 0, "retried": 0}


def test_answers_travel_as_one_answers_prompt_exactly_as_the_desk_sends_them(fleet_home, tmp_path,  # noqa: F811
                                                                             monkeypatch):
    from agentdata.fleet import serve as S

    cfg = _reply_cfg(tmp_path, monkeypatch)
    _headless(tmp_path, "sol")
    answers = [{"id": "q1", "answer": "the staging workspace"}, {"id": "q2", "answer": "yes; both tables"}]
    sends: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(supervisor, "send", lambda name, message, *, cfg=None, force=False, **k:
                        sends.append((name, message, force)) or {"pid": 4242})

    record = _reply("sol", answers=answers, message="ignored when answers are given")
    _drop_reply(cfg, record)
    assert bridge.apply_once(cfg)["applied"] == 1
    S.act("answer", {"repo": "sol", "answers": answers})

    assert len(sends) == 2, "one answers_prompt per reply, however many answers it carries"
    assert sends[0] == sends[1] == (
        "sol", lifecycle.answers_prompt([("q1", "the staging workspace"), ("q2", "yes; both tables")]), False)
    res = _result(cfg, record["nonce"])
    assert (res["via"], res["answered"]) == ("send", ["q1", "q2"])
    [ev] = _events("sol", "mobile.reply")
    assert ev["data"]["answered"] == ["q1", "q2"] and ev["data"]["words"] == len(sends[0][1].split())
    assert "staging" not in json.dumps(ev)


def test_force_from_the_phone_is_never_honoured(fleet_home, tmp_path, monkeypatch, spawns):  # noqa: F811
    cfg = _reply_cfg(tmp_path, monkeypatch, budget_per_agent=2)
    _headless(tmp_path, "sol")
    E.append("sol", [E.event("sol", "cost", {"premium_requests": 9.0, "source": "checkpoint"}, ticket="RDSD-9")])
    record = _reply("sol", message="one more turn, please", force=True)
    name = _drop_reply(cfg, record)

    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 1, "retried": 0}
    assert spawns["launched"] == [], "nothing was spawned"
    assert _why(cfg, name)["code"] == "budget_exceeded"
    assert _result(cfg, record["nonce"])["code"] == "budget_exceeded"


def test_a_supervisor_refusal_is_written_in_its_own_words_and_the_file_is_rejected(fleet_home, tmp_path,  # noqa: F811
                                                                                   monkeypatch, spawns):
    cfg = _reply_cfg(tmp_path, monkeypatch, budget_per_agent=2)
    # external_session: a session the fleet adopted (this process stands in for it).
    path = make_project(tmp_path / "ext", ticket="RDSD-3")
    Registry().add(path, name="ext")
    spawns["alive"].add(os.getpid())
    supervisor.write_lock("ext", {"pid": os.getpid(), "external": True, "repo": "ext", "path": path,
                                  "started": time.time()})
    assert supervisor.live("ext"), "the adopted session is live"
    # budget_exceeded: spent 9 of 2.
    _headless(tmp_path, "spent")
    E.append("spent", [E.event("spent", "cost", {"premium_requests": 9.0, "source": "checkpoint"}, ticket="RDSD-9")])
    # no_session: registered, never started.
    Registry().add(make_project(tmp_path / "new", ticket="RDSD-4"), name="new")

    records = {repo: _reply(repo, message="status?") for repo in ("ext", "spent", "new")}
    names = {repo: _drop_reply(cfg, r) for repo, r in records.items()}
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": 3, "retried": 0}
    assert spawns["launched"] == []

    for repo, code in (("ext", "external_session"), ("spent", "budget_exceeded"), ("new", "no_session")):
        with pytest.raises(supervisor.SupervisorError) as refused:
            supervisor.send(repo, "status?", cfg=cfg)
        e = refused.value
        assert e.code == code
        why = _why(cfg, names[repo])
        assert (why["code"], why["error"], why["hint"]) == (e.code, e.msg, e.hint), repo
        res = _result(cfg, records[repo]["nonce"])
        assert (res["ok"], res["kind_of"], res["repo"], res["code"], res["error"], res["hint"]) == (
            False, "reply", repo, e.code, e.msg[:bridge.LIMITS["reason"]], e.hint[:bridge.LIMITS["reason"]]), repo
        assert os.path.isfile(os.path.join(_folder(cfg), "rejected", names[repo]))
        [ev] = _events(repo, "mobile.rejected")
        assert (ev["data"]["kind"], ev["data"]["code"]) == ("reply", code)
    assert _inbox_names(cfg) == []


def test_mid_turn_is_retried_until_expires_then_refused_as_mid_turn(fleet_home, tmp_path, monkeypatch,  # noqa: F811
                                                                     spawns):
    cfg = _reply_cfg(tmp_path, monkeypatch)
    _headless(tmp_path, "sol", session="sess-sol")
    spawns["alive"].add(os.getpid())
    turn = {"pid": os.getpid(), "repo": "sol", "session": "sess-sol", "started": time.time()}
    supervisor.write_lock("sol", turn)                      # a turn in flight: `send` refuses mid_turn
    now = time.time()
    record = _reply("sol", message="and then the report", issued=now, expires=now + 300)
    name = _drop_reply(cfg, record)

    assert bridge.apply_once(cfg, now=now) == {"applied": 0, "rejected": 0, "retried": 1}
    assert bridge.apply_once(cfg, now=now + 5) == {"applied": 0, "rejected": 0, "retried": 1}
    assert _inbox_names(cfg) == [name] and spawns["launched"] == []
    retrying = bridge.read_state()["retrying"][record["nonce"]]
    assert retrying["tries"] == 2 and retrying["first_seen"] == bridge._utc(now)
    assert not os.path.exists(bridge.outbox_dir(_folder(cfg), "results", f"{record['nonce']}.result.json"))

    os.remove(supervisor.lock_path("sol"))                  # the turn ends within `expires`
    assert bridge.apply_once(cfg, now=now + 10) == {"applied": 1, "rejected": 0, "retried": 0}
    [argv] = spawns["launched"]
    assert "and then the report" in argv and _result(cfg, record["nonce"])["via"] == "send"
    assert record["nonce"] not in bridge.read_state()["retrying"]

    # Past `expires` with the lock still held: refused as mid_turn, in the supervisor's words, with how long it tried.
    supervisor.write_lock("sol", turn)                      # the next turn
    late = _reply("sol", message="one more thing", issued=now, expires=now + 300)
    late_name = _drop_reply(cfg, late)
    assert bridge.apply_once(cfg, now=now + 20)["retried"] == 1
    assert bridge.apply_once(cfg, now=now + 301) == {"applied": 0, "rejected": 1, "retried": 0}
    with pytest.raises(supervisor.SupervisorError) as refused:
        supervisor.send("sol", "one more thing", cfg=cfg)
    why = _why(cfg, late_name)
    assert (why["code"], why["error"], why["hint"]) == ("mid_turn", refused.value.msg, refused.value.hint)
    assert why["retried_s"] == 281
    res = _result(cfg, late["nonce"])
    assert (res["ok"], res["code"], res["retried_s"]) == (False, "mid_turn", 281)
    assert late["nonce"] not in bridge.read_state()["retrying"] and len(spawns["launched"]) == 1


def test_a_reply_naming_an_unregistered_repo_is_refused_with_wrong_repo(fleet_home, tmp_path, monkeypatch,  # noqa: F811
                                                                        spawns):
    cfg = _reply_cfg(tmp_path, monkeypatch)
    _headless(tmp_path, "sol")
    cases = {
        "mobile_wrong_repo": [_reply("nowhere", message="hello"), _reply("", message="hello"),
                              _reply(["sol"], message="hello")],
        "mobile_bad_schema": [_reply("sol"), _reply("sol", message="   "), _reply("sol", message="", answers=[]),
                              _reply("sol", answers=[{"id": "q1", "answer": " "}]),
                              _reply("sol", message="x" * 4001),
                              _reply("sol", answers=[{"id": f"q{i}", "answer": "a"} for i in range(9)]),
                              _reply("sol", answers=[{"id": "q" * 33, "answer": "a"}]),
                              _reply("sol", answers=[{"id": "q1", "answer": "a" * 1001}]),
                              _reply("sol", answers="q1: yes"), _reply("sol", message=["hello"])],
    }
    names = {r["nonce"]: (code, _drop_reply(cfg, r)) for code, rs in cases.items() for r in rs}
    assert bridge.apply_once(cfg) == {"applied": 0, "rejected": len(names), "retried": 0}
    for nonce, (code, name) in names.items():
        assert _why(cfg, name)["code"] == code, name
        assert _result(cfg, nonce)["code"] == code
    assert spawns["launched"] == [] and _typed(tmp_path) == []
    assert not _events("nowhere", "mobile.rejected")


# ------------------------------------------------------------------------------------------ Thread and watch
#
# The loop's work is counted, not done: `export_once`, `apply_once` and the sweep are replaced by counters, so what is
# tested is who starts the thread, when it stops, and that one failing step never stops the next (#550).

from agentdata import cli_fleet, config as C, log as LOG
from agentdata.fleet import serve as S


@pytest.fixture()
def passes(monkeypatch):
    """Counters in place of the loop's three steps; `raise_export` makes the next export raise once."""
    seen = {"sweep": 0, "export": 0, "apply": 0, "raise_export": 0, "logged": []}

    def export_once(cfg=None, snapshot=None, *, now=None):
        seen["export"] += 1
        if seen["raise_export"]:
            seen["raise_export"] -= 1
            raise OSError("the outbox is not there today")
        return {"written": [], "unchanged": 0, "how": []}

    monkeypatch.setattr(bridge, "export_once", export_once)
    monkeypatch.setattr(bridge, "apply_once", lambda cfg=None, *, now=None: seen.__setitem__("apply", seen["apply"] + 1))
    monkeypatch.setattr(S, "sweep_if_due", lambda url, every=S.NOTIFY_EVERY_S: seen.__setitem__("sweep", seen["sweep"] + 1))
    monkeypatch.setattr(LOG, "debug_exc", lambda where, exc=None: seen["logged"].append(where))
    return seen


def _bridge_threads() -> list:
    return [t for t in threading.enumerate() if t.name == bridge.BRIDGE_THREAD and t.is_alive()]


def _until(check, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def test_build_never_starts_the_bridge_and_cmd_serve_starts_it_only_when_enabled(fleet_home, tmp_path,  # noqa: F811
                                                                                   monkeypatch, capsys, passes):
    C.save(_cfg(tmp_path))
    server, _token = S.build(0)
    try:
        assert not _bridge_threads(), "S.build started the bridge: every browser test would run it"
    finally:
        server.server_close()

    built: list = []
    monkeypatch.setattr(S, "run", built.append)
    empty = tmp_path / "checkouts"
    empty.mkdir()

    def started(argv) -> list:
        assert cli_fleet.main(argv) == 0, capsys.readouterr().out
        threads = _bridge_threads()
        built[-1].server_close()
        for t in threads:
            t.join(bridge.TICK_S + 1)
            assert not t.is_alive()
        return threads

    serve = ["serve", "--port", "0"]
    quick = ["quickstart", str(empty), "--yes", "--port", "0", "--folder-watch", str(empty)]
    assert len(started(serve)) == 1 and len(started(quick)) == 1
    assert passes["export"] >= 2 and passes["apply"] >= 2 and passes["sweep"] >= 2

    C.save(_cfg(tmp_path, mobile={"enabled": False, "folder": str(tmp_path / "OneDrive" / "FleetAgent")}))
    assert started(serve) == [] and started(quick) == [] and passes["logged"] == []

    C.save(_cfg(tmp_path, mobile={"enabled": True, "folder": str(fleet_home / "outbox")}))
    assert started(serve) == [] and passes["logged"] == ["bridge start"], "a refused folder is not logged"
    assert len(built) == 5, "a refused bridge stopped the desk from serving"


def test_the_bridge_thread_ends_with_the_server(fleet_home, tmp_path, passes):  # noqa: F811
    server, _token = S.build(0)
    try:
        thread = bridge.start(server.stopping, _cfg(tmp_path))
        assert thread is not None and thread.daemon and thread.name == bridge.BRIDGE_THREAD
        assert _until(lambda: passes["apply"] >= 1), "the first pass never ran"
    finally:
        server.server_close()
    thread.join(bridge.TICK_S + 1)
    assert not thread.is_alive(), "the bridge outlived its server"
    assert passes["sweep"] == passes["export"] == passes["apply"]


def test_a_step_that_raises_is_logged_and_the_next_step_and_the_next_pass_still_run(fleet_home, tmp_path,  # noqa: F811
                                                                                     passes):
    stop = threading.Event()
    passes["raise_export"] = 1
    thread = threading.Thread(target=bridge.run_loop, args=(stop, _cfg(tmp_path)), kwargs={"tick": 0.01})
    thread.start()
    try:
        assert _until(lambda: passes["export"] >= 2)
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()
    assert passes["logged"] == ["bridge export"]
    assert passes["apply"] >= 2, "the failed export's pass skipped apply_once"


def test_a_wall_clock_jump_writes_one_heartbeat_and_resets_the_prune_stamp(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """The laptop slept for an hour (or its clock was stepped back): one heartbeat on waking, never a burst, and a
    clock stepped back cannot hold the next beat off until the old stamp comes round again."""
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(S, "sweep_if_due", lambda url, every=S.NOTIFY_EVERY_S: [])
    monkeypatch.setattr(S, "fleet_snapshot", lambda: {"repos": [], "approvals": []})
    pruned: list = []
    real_prune = bridge.prune
    monkeypatch.setattr(bridge, "prune", lambda folder, state, now=None: pruned.append(now) or real_prune(folder, state, now))

    def beats() -> int:
        return len([n for n in _outbox(cfg) if n.startswith("heartbeat/")])

    stamps: dict = {"tick": bridge.TICK_S}
    t0 = 1_790_000_000.0
    bridge._one_pass(cfg, stamps, t0)
    assert beats() == 1 and pruned == [t0]
    bridge._one_pass(cfg, stamps, t0 + 5)
    assert beats() == 1 and pruned == [t0]

    bridge._one_pass(cfg, stamps, t0 + 3600)                 # slept an hour: one beat, not twelve
    assert beats() == 2 and pruned == [t0], "a wake pruned at once instead of a whole interval later"
    bridge._one_pass(cfg, stamps, t0 + 3605)
    assert beats() == 2

    bridge._one_pass(cfg, stamps, t0 + 1800)                 # stepped back half an hour: one beat now
    assert beats() == 3
    ticks = int(bridge.PRUNE_EVERY_S // bridge.TICK_S)
    for n in range(1, ticks + 1):                            # then a tick at a time: the next prune is due after one
        bridge._one_pass(cfg, stamps, t0 + 1800 + n * bridge.TICK_S)   # whole interval, counted from the jump
    assert pruned == [t0, t0 + 1800 + ticks * bridge.TICK_S]
    assert beats() == 3 + int(bridge.PRUNE_EVERY_S // bridge.HEARTBEAT_S), "the beat did not resume its cadence"


def test_watch_refuses_beside_a_live_serve_and_runs_when_none_is_up(fleet_home, tmp_path, monkeypatch,  # noqa: F811
                                                                    capsys, passes):
    C.save(_cfg(tmp_path))
    os.makedirs(str(fleet_home), exist_ok=True)
    record = os.path.join(str(fleet_home), "serve.json")
    with open(record, "w", encoding="utf-8") as f:
        json.dump({"url": "http://127.0.0.1:8765/?t=tok", "token": "tok", "pid": os.getpid()}, f)
    assert cli_fleet.main(["mobile", "watch"]) == 2
    out = capsys.readouterr().out
    assert "refused: mobile_serve_running" in out and f"pid {os.getpid()}" in out
    assert passes["export"] == 0

    loops: list = []
    real_loop = bridge.run_loop
    monkeypatch.setattr(bridge, "run_loop", lambda stop, cfg=None, *, tick=bridge.TICK_S, once=False:
                        loops.append(tick) or real_loop(stop, cfg, tick=tick, once=True))
    with open(record, "w", encoding="utf-8") as f:
        json.dump({"url": "http://127.0.0.1:8765/?t=tok", "token": "tok", "pid": 0}, f)
    assert cli_fleet.main(["mobile", "watch", "--every", "7"]) == 0
    out = capsys.readouterr().out
    assert "ok: true" in out and "operator: operator@example.com" in out and "every: 7" in out
    assert "FleetAgent" in out and loops == [7.0]
    assert (passes["sweep"], passes["export"], passes["apply"]) == (1, 1, 1)

    os.remove(record)
    assert cli_fleet.main(["mobile", "watch"]) == 0 and loops == [7.0, bridge.TICK_S]
