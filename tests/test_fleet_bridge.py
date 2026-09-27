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
