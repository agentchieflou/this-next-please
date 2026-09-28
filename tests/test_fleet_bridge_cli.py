"""`ad-fleet mobile status | init | export | apply` (#552): the bridge's verbs, driven through `cli_fleet.main`.

What is tested is what a script and the flow builder (#557) lean on: every verb prints TOON, the two dry runs leave the
bridge folder byte-identical and record no nonce, and `init` makes the tree and `pairing.json` once, never inside a
checkout. The loop and `watch` are #550's, in `tests/test_fleet_bridge.py` "Thread and watch".
"""
from __future__ import annotations
import hashlib
import json
import os
import time

import pytest

from agentdata import cli_fleet, config as C, textio, toon
from agentdata.fleet import approval, bridge, registry
from agentdata.fleet import serve as S

from test_fleet_board_desk import a_project
from test_fleet_bridge import UPN, _cfg, _drop, _phone, _request
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name
import mobile_contract
from mobile_contract import contract_checked                     # noqa: F401 - autouse: every record written validates

# `contract/examples/inbox-decision-9f2c4b7e.json` (#598): the file FleetDecide writes, adapted in the test to a live
# request's id and digest and to `issued` and `expires` around now. The mobile contract validates it as it stands.
with open(os.path.join(mobile_contract.EXAMPLES, "inbox-decision-9f2c4b7e.json"), encoding="utf-8") as _f:
    FLEET_DECIDE_SAMPLE = json.load(_f)


def _run(argv, capsys) -> tuple[int, str]:
    code = cli_fleet.main(argv)
    return code, capsys.readouterr().out


def _toon_ok(out: str) -> str:
    assert toon.validate(out) == [], out
    return out


def _digest_tree(root: str) -> dict:
    """Every file under `root`, by relative path, to the sha256 of its bytes (and every directory, to None)."""
    found: dict = {}
    for dirpath, dirs, names in os.walk(root):
        for d in dirs:
            found[os.path.relpath(os.path.join(dirpath, d), root)] = None
        for n in names:
            with open(os.path.join(dirpath, n), "rb") as f:
                found[os.path.relpath(os.path.join(dirpath, n), root)] = hashlib.sha256(f.read()).hexdigest()
    return found


def _state_bytes() -> bytes | None:
    try:
        with open(os.path.join(registry.fleet_dir(), bridge.STATE_FILE), "rb") as f:
            return f.read()
    except OSError:
        return None


@pytest.fixture()
def no_desk(monkeypatch):
    """No desk: the export reads a snapshot with no repos, and `serve.json` names no live pid."""
    monkeypatch.setattr(S, "fleet_snapshot", lambda: {"repos": [], "approvals": approval.pending()})


def test_mobile_status_prints_valid_toon_with_the_folder_facts(fleet_home, tmp_path, capsys, no_desk):  # noqa: F811
    # The folder holds a `:` on every OS, as a Windows drive letter does, so TOON quotes it here too.
    cfg = _cfg(tmp_path if os.name == "nt" else tmp_path / "C:")
    C.save(cfg)
    code, out = _run(["mobile", "status"], capsys)
    assert code == 0 and "ok: true" in _toon_ok(out) and "enabled: true" in out and "bridge_running: false" in out
    assert "outbox[5]{kind,files,newest}:" in out and "rejected[0]{at,file,code}:" in out
    assert not os.path.exists(os.path.join(registry.fleet_dir(), bridge.STATE_FILE)), "status wrote the state file"

    assert _run(["mobile", "init"], capsys)[0] == 0
    _request()
    assert _run(["mobile", "export"], capsys)[0] == 0
    _drop(cfg, raw=b"not json", name="decision-broken.json")
    assert _run(["mobile", "apply"], capsys)[0] == 0

    code, out = _run(["mobile", "status"], capsys)
    meta = dict(line.split(": ", 1) for line in _toon_ok(out).splitlines()
                if line.startswith("  ") and ": " in line and not line.startswith("   "))
    meta = {k.strip(): toon.read_cell(v) for k, v in meta.items()}  # each value as TOON encoded it, read back
    assert meta["folder"].endswith("OneDrive/FleetAgent") and meta["operator"] == UPN
    assert meta["expire_s"] == "900" and meta["notify"] == "true" and meta["serve_up"] == "false"
    assert meta["last_export"] and meta["last_inbox"] and meta["bridge_running"] == "true"
    assert "sync_root" in meta and "pinned" in meta and meta["folder_refused"] in ("", '""')
    assert "  approvals,1," in out and "  heartbeat,1," in out and "  attention,0," in out
    assert "rejected[1]{at,file,code}:" in out and "decision-broken.json,mobile_bad_json" in out

    C.save(_cfg(tmp_path, mobile={"enabled": False, "folder": cfg["fleet"]["mobile"]["folder"]}))
    code, out = _run(["mobile", "status"], capsys)
    assert code == 0 and "ok: true" in _toon_ok(out) and "enabled: false" in out
    assert "\n  refused: " not in out and "bridge_running: false" in out

    C.save({"fleet": {"mobile": {"enabled": False}}})
    code, out = _run(["mobile", "status"], capsys)
    assert code == 0 and "folder_refused: mobile_folder_unset" in _toon_ok(out) and "outbox[0]" in out


def test_export_dry_run_and_apply_dry_run_change_nothing_on_disk(fleet_home, tmp_path, capsys, no_desk):  # noqa: F811
    cfg = _cfg(tmp_path)
    C.save(cfg)
    assert _run(["mobile", "init"], capsys)[0] == 0
    live = _request()
    now = time.time()
    sample = dict(FLEET_DECIDE_SAMPLE, id=live["id"], digest=live["digest"],
                  issued=bridge._utc(now), expires=bridge._utc(now + 600))
    mobile_contract.check(sample, "inbox_decision")
    good = _drop(cfg, sample)
    stale = _drop(cfg, _phone(live, digest="0" * 64), name="decision-zz-stale.json")   # applied after the sample
    folder = bridge.check_folder(cfg)
    before, state_before = _digest_tree(folder), _state_bytes()

    code, out = _run(["mobile", "export", "--dry-run"], capsys)
    assert code == 0 and "dry_run: true" in _toon_ok(out) and "written: 2" in out
    assert f"approval,luna,outbox/approvals/{live['id']}.json" in out and 'heartbeat,"",outbox/heartbeat/' in out

    code, out = _run(["mobile", "apply", "--dry-run"], capsys)
    assert code == 0 and "would_apply: 1" in _toon_ok(out) and "would_reject: 1" in out and "applied: 0" in out
    assert f'{good},decision,luna,would_apply,""' in out, "the FleetDecide sample would not apply"
    assert f"{stale},decision,luna,would_reject,mobile_digest_mismatch" in out

    assert _digest_tree(folder) == before, "a dry run changed the bridge folder"
    assert _state_bytes() == state_before, "a dry run wrote the state file"
    state = bridge.read_state()
    assert sample["nonce"] not in state["processed"] and not approval.read_decision(live["id"])

    # The same two passes for real: the dry runs said what they do.
    code, out = _run(["mobile", "export"], capsys)
    assert code == 0 and "written: 2" in out and f"outbox/approvals/{live['id']}.json" in out
    code, out = _run(["mobile", "apply"], capsys)
    assert code == 0 and f'{good},decision,luna,applied,""' in out
    # One pass, in name order: the sample decided the request first, so the stale file now meets that decision.
    assert f"{stale},decision,luna,rejected,mobile_already_decided" in out
    assert approval.read_decision(live["id"])["decision"] == approval.APPROVED


def test_init_writes_pairing_and_the_tree_and_refuses_a_repo_folder(fleet_home, tmp_path, capsys):  # noqa: F811
    checkout = a_project(tmp_path, "luna")
    registry.Registry().add(checkout)
    inside = os.path.join(checkout, "FleetAgent")
    C.save({"fleet": {"mobile": {"enabled": True}}})
    saved = open(C.path(), "rb").read()

    code, out = _run(["mobile", "init", "--folder", inside, "--operator", UPN], capsys)
    assert code == 2 and "refused: mobile_folder_in_repo" in _toon_ok(out)
    assert not os.path.exists(inside) and open(C.path(), "rb").read() == saved, "a refused folder was remembered"

    folder = str(tmp_path / "OneDrive" / "FleetAgent")
    code, out = _run(["mobile", "init", "--folder", folder, "--operator", UPN], capsys)
    assert code == 0 and "wrote_pairing: true" in _toon_ok(out) and "made: 8" in out and "contract: 1" in out
    assert C.get(C.load(), "fleet.mobile.folder") == folder and C.get(C.load(), "fleet.mobile.operator") == UPN
    for rel in bridge.TREE:
        assert os.path.isdir(os.path.join(folder, *rel.split("/"))), rel
    pairing = textio.read_json(os.path.join(folder, "pairing.json"), "pairing")
    assert set(pairing) == {"schema", "kind", "contract", "operator", "laptop_id", "expire_s", "created"}
    assert (pairing["kind"], pairing["contract"], pairing["operator"]) == ("pairing", 1, UPN)
    assert pairing["laptop_id"] == bridge.read_state()["laptop_id"] and pairing["expire_s"] == 900
    assert "pairing.json" in out

    before = _digest_tree(folder)
    code, out = _run(["mobile", "init", "--operator", "someone.else@example.com"], capsys)
    assert code == 0 and "wrote_pairing: false" in _toon_ok(out) and "made: 0" in out
    assert _digest_tree(folder) == before, "a second init rewrote something"

    C.save({"fleet": {"mobile": {"enabled": False, "folder": folder}}})
    code, out = _run(["mobile", "init"], capsys)
    assert code == 2 and "refused: mobile_disabled" in _toon_ok(out)


def test_a_real_apply_refuses_beside_a_live_serve_and_a_dry_run_does_not(fleet_home, tmp_path, capsys):  # noqa: F811
    """Two appliers could both send one reply: a real `apply` beside a live desk refuses as `watch` does (#550)."""
    C.save(_cfg(tmp_path))
    os.makedirs(registry.fleet_dir(), exist_ok=True)
    with open(os.path.join(registry.fleet_dir(), "serve.json"), "w", encoding="utf-8") as f:
        json.dump({"url": "http://127.0.0.1:8765/?t=tok", "token": "tok", "pid": os.getpid()}, f)
    code, out = _run(["mobile", "apply"], capsys)
    assert code == 2 and "refused: mobile_serve_running" in _toon_ok(out)
    code, out = _run(["mobile", "apply", "--dry-run"], capsys)
    assert code == 0 and "inbox[0]" in _toon_ok(out)
