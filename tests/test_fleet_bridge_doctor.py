"""The bridge's doctor rows and its setup questions (#553): `fleet/mobile`, `fleet/mobile traffic`, `--patch fleet.mobile`.

The rows are read from disk, file attributes and `winreg` only, so every case here is a folder, an environment
variable or a monkeypatched `os.stat`: Files On-Demand's attributes do not exist on Linux, and the attribute
literals are the MS-FSCC ones the step names. The pattern is `tests/test_setup.py`'s `--patch` tests and
`tests/test_fleet_notify.py`'s "the rows name the settings that change them".
"""
from __future__ import annotations
import json
import os
import time
import types

import pytest

from agentdata import config as C
from agentdata.fleet import bridge
from agentdata.fleet.registry import Registry
from agentdata.setup import wizard as W
from agentdata.setup.steps import fleet as F
from agentdata.setup.steps.fleet import FleetStep

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

UPN = "luna@example.com"
PROBE = {"version": "1.0.81", "why": "", "login": "ok", "port": 8765, "port_free": True, "ours": False,
         "models": {}}
_REAL_PROBE = FleetStep._probe
_REAL_STAT = os.stat


@pytest.fixture()
def home(fleet_home, tmp_path, monkeypatch):                    # noqa: F811 - the fixture is the argument
    """A fleet with no CLI to start, and no OneDrive anywhere the step could find one."""
    monkeypatch.setenv(C.CONFIG_ENV, str(tmp_path / "agentdata.json"))
    monkeypatch.chdir(tmp_path)
    for var in ("OneDriveCommercial", "OneDrive"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(FleetStep, "_probe", lambda self, ctx: dict(PROBE))
    return tmp_path


def _synced(tmp_path, *, inbox=True) -> str:
    """`<tmp>/OneDrive - Contoso/FleetAgent`, with `inbox/`, and `%OneDriveCommercial%` pointing at its root."""
    root = tmp_path / "OneDrive - Contoso"
    folder = root / "FleetAgent"
    os.makedirs(folder / "inbox" if inbox else folder, exist_ok=True)
    os.environ["OneDriveCommercial"] = str(root)
    return str(folder)


def _mobile(**keys) -> dict:
    return {"fleet": {"enabled": True, "mobile": keys}}


def _rows(cfg: dict) -> dict:
    """detect, then check, as `ad-doctor --only fleet` runs them. The fleet rows by name."""
    ctx = W.Context(cfg=cfg, det=W.Detectors(), ask=W.Prompter(), interactive=False)
    step = FleetStep()
    step.check(ctx, step.detect(ctx))
    rows: dict = {}
    for c in ctx.checks:
        assert c.name not in rows, f"two {c.name} rows"
        rows[c.name] = c
    return rows


def _stat_with(attributes: dict):
    """`os.stat` that answers `st_file_attributes` for the paths named, as Windows does, and is the real one
    everywhere else."""
    real = _REAL_STAT

    def fake(path, *a, **kw):
        for suffix, attrs in attributes.items():
            if os.path.normpath(str(path)).endswith(os.path.normpath(suffix)):
                st = real(path, *a, **kw)
                return types.SimpleNamespace(st_mode=st.st_mode, st_mtime=st.st_mtime, st_size=st.st_size,
                                             st_file_attributes=attrs)
        return real(path, *a, **kw)
    return fake


def test_the_row_is_skip_when_the_bridge_is_off_and_names_the_enabled_key(home):
    rows = _rows({"fleet": {"enabled": True}})
    mobile = [r for name, r in rows.items() if name.startswith("mobile")]
    assert len(mobile) == 1, "off is one row, and no traffic row"
    row = mobile[0]
    assert (row.step, row.name, row.status, row.detail) == ("fleet", "mobile", "skip", "off")
    assert row.keys == ("fleet.mobile.enabled",)
    assert "ad-setup --patch fleet.mobile" in row.hint

    # "false" as the file says it is off too, and a configured folder does not make it a check.
    rows = _rows(_mobile(enabled="false", folder=str(home / "nowhere")))
    assert rows["mobile"].status == "skip" and "mobile traffic" not in rows


def test_the_row_fails_when_the_folder_is_missing_or_online_only_and_names_the_fix(home, monkeypatch):
    unset = _rows(_mobile(enabled=True, operator=UPN))["mobile"]
    assert unset.status == "fail" and unset.keys == ("fleet.mobile.folder",)
    assert "no bridge folder" in unset.detail and "%OneDriveCommercial%" in unset.hint

    missing = _rows(_mobile(enabled=True, folder=str(home / "OneDrive - Contoso" / "gone"), operator=UPN))["mobile"]
    assert missing.status == "fail" and missing.keys == ("fleet.mobile.folder",)
    assert "does not exist" in missing.detail

    checkout = make_project(home / "luna")
    Registry().add(checkout, name="luna")
    os.makedirs(os.path.join(checkout, "bridge", "inbox"))
    inside = _rows(_mobile(enabled=True, folder=os.path.join(checkout, "bridge"), operator=UPN))["mobile"]
    assert inside.status == "fail" and inside.keys == ("fleet.mobile.folder",)
    assert "inside the checkout of luna" in inside.detail

    folder = _synced(home)
    cfg = _mobile(enabled=True, folder=folder, operator=UPN)
    with monkeypatch.context() as m:
        m.setattr(os, "stat", _stat_with({"FleetAgent/inbox": F.FILE_ATTRIBUTE_UNPINNED}))
        online = _rows(cfg)["mobile"]
    assert online.status == "fail" and online.keys == (), "no answer pins a folder: --patch lists it under manual"
    assert "online-only" in online.detail and "inbox" in online.detail
    assert 'attrib +p "' in online.hint and "/s /d" in online.hint and "Always keep on this device" in online.hint

    # A placeholder (fetched on read) is online-only as well; a pinned inbox is what MOB-D4 asks for.
    with monkeypatch.context() as m:
        m.setattr(os, "stat", _stat_with({"FleetAgent/inbox": F.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS}))
        assert _rows(cfg)["mobile"].status == "fail"
        m.setattr(os, "stat", _stat_with({"FleetAgent/inbox": F.FILE_ATTRIBUTE_PINNED,
                                          "FleetAgent": F.FILE_ATTRIBUTE_UNPINNED}))
        tree = _rows(cfg)["mobile"]
        assert tree.status == "warn" and "online-only (its inbox is not)" in tree.detail and "attrib +p" in tree.hint
        m.setattr(os, "stat", _stat_with({"FleetAgent/inbox": F.FILE_ATTRIBUTE_PINNED}))
        ok = _rows(cfg)["mobile"]
    assert ok.status == "ok", ok
    shown = bridge.settings(cfg)["folder"]
    assert ok.detail == f"{shown} · synced (env:OneDriveCommercial) · pinned · operator {UPN}"


def test_the_row_warns_when_it_cannot_tell_the_folder_syncs(home):
    plain = home / "Documents" / "FleetAgent"
    os.makedirs(plain / "inbox")
    row = _rows(_mobile(enabled=True, folder=str(plain), operator=UPN))["mobile"]
    assert row.status == "warn", row
    assert "cannot tell that this folder syncs; the phone will not see it unless it does" in row.detail
    assert row.keys == ("fleet.mobile.folder",)

    # Each source of evidence is enough on its own: the variable, or a parent named as the client names its roots.
    os.environ["OneDriveCommercial"] = str(home / "Documents")
    assert "synced (env:OneDriveCommercial)" in _rows(_mobile(enabled=True, folder=str(plain), operator=UPN))[
        "mobile"].detail
    del os.environ["OneDriveCommercial"]
    os.environ["OneDrive"] = str(home / "Documents")
    assert "synced (env:OneDrive)" in _rows(_mobile(enabled=True, folder=str(plain), operator=UPN))["mobile"].detail
    del os.environ["OneDrive"]
    folder = _synced(home)
    del os.environ["OneDriveCommercial"]
    assert "synced (parent)" in _rows(_mobile(enabled=True, folder=folder, operator=UPN))["mobile"].detail

    # The other warnings name the key that fixes each, and never fail the doctor.
    long = os.path.join(folder, *(["d" * 60] * 5))
    os.makedirs(os.path.join(long, "inbox"))
    rows = _rows(_mobile(enabled=True, folder=long, operator="luna", expire_s="soon"))
    row = rows["mobile"]
    assert row.status == "warn"
    assert "is not a UPN" in row.detail and "is not a number" in row.detail and "over 300" in row.detail
    assert set(row.keys) == {"fleet.mobile.folder", "fleet.mobile.operator", "fleet.mobile.expire_s"}
    assert "no operator is set" in _rows(_mobile(enabled=True, folder=folder))["mobile"].detail


def test_the_mobile_rows_name_the_settings_that_change_them_and_patch_reasks_only_those(home, capsys, monkeypatch):
    monkeypatch.setattr("agentdata.proc.run", lambda *a, **k: (127, "", "not found", 0.0))
    folder = _synced(home)
    rows = _rows(_mobile(enabled=True, folder=folder, operator=UPN))
    assert rows["mobile"].status == "ok" and set(rows["mobile"].keys) == set(F.MOBILE_KEYS)
    assert all(k.startswith("fleet.mobile.") for r in rows.values() if r.name.startswith("mobile") for k in r.keys)
    traffic = rows["mobile traffic"]
    assert (traffic.status, traffic.keys) == ("ok", ()) and traffic.detail == (
        "last export never · last inbox never · 0 rejected in 24h")

    # The traffic row: the state file's times, `rejected/` over a day and its newest code, and serve up with no export.
    now = time.time()
    os.makedirs(str(home / "fleet"), exist_ok=True)
    with open(home / "fleet" / bridge.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_export": bridge._utc(now - 12), "last_inbox_seen": bridge._utc(now - 240)}, f)
    os.makedirs(os.path.join(folder, "rejected"))
    for age, code in ((3 * 86400, "mobile_old"), (600, "mobile_replay"), (60, "mobile_expired")):
        path = os.path.join(folder, "rejected", f"{code}.json.why.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"code": code}, f)
        os.utime(path, (now - age, now - age))
    traffic = _rows(_mobile(enabled=True, folder=folder, operator=UPN))["mobile traffic"]
    assert traffic.status == "warn" and traffic.keys == ()
    assert traffic.detail == "last export 12s · last inbox 4m · 2 rejected in 24h", traffic.detail
    assert "mobile_expired" in traffic.hint and "refusals.md" in traffic.hint
    monkeypatch.setattr(FleetStep, "_probe", lambda self, ctx: dict(PROBE, ours=True))
    with open(home / "fleet" / bridge.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_export": bridge._utc(now - 600)}, f)
    assert "serve is up but the bridge is not writing" in _rows(_mobile(
        enabled=True, folder=folder, operator=UPN))["mobile traffic"].hint
    monkeypatch.setattr(FleetStep, "_probe", lambda self, ctx: dict(PROBE))

    # `ad-setup --patch fleet.mobile` asks exactly the five keys, and writes what was answered.
    C.save({"fleet": {"enabled": True, "notify": {"cooldown": 77}}})
    rc = W.run_setup(["--patch", "fleet.mobile", "--non-interactive", "--offline",
                      "--set", "fleet.mobile.enabled=yes", "--set", f"fleet.mobile.folder={folder}",
                      "--set", f"fleet.mobile.operator={UPN}", "--set", "fleet.mobile.expire_s=600"], W.Detectors())
    out = capsys.readouterr().out
    asked = out.split("asked[")[1].split("\n")[0]
    assert asked.startswith("5]"), asked
    assert [k for k in asked.split(":", 1)[1].replace(",", " ").split()] == list(F.MOBILE_KEYS), asked
    mobile = C.load()["fleet"]["mobile"]
    assert mobile == {"enabled": True, "folder": folder, "operator": UPN, "expire_s": 600, "notify": True}
    assert C.load()["fleet"]["notify"]["cooldown"] == 77, "an answer outside fleet.mobile kept its value"
    assert rc in (0, 1), out            # `copilot` is not installed here: its own fail row

    # The online-only inbox is a fail that no answer fixes: --patch lists it under manual and asks it nothing.
    with monkeypatch.context() as m:
        m.setattr(os, "stat", _stat_with({"FleetAgent/inbox": F.FILE_ATTRIBUTE_UNPINNED}))
        W.run_setup(["--patch", "--non-interactive", "--offline", "--only", "fleet"], W.Detectors())
    out = capsys.readouterr().out
    assert "fleet/mobile: " in out.split("manual[")[1] and "attrib +p" in out
    assert "fleet.mobile" not in (out.split("asked[")[1].split("\n")[0] if "asked[" in out else "")


def test_the_doctor_starts_no_new_process_for_the_bridge(home, capsys, monkeypatch):
    """`ad-doctor --quiet` runs on every session start: the bridge rows cost it nothing (no `attrib`, no `reg
    query`, no `tasklist` behind `bridge._serve_up`)."""
    import subprocess

    calls: list = []
    monkeypatch.setattr("agentdata.proc.run", lambda argv, *a, **k: calls.append(list(argv)) or (127, "", "", 0.0))
    real_popen = subprocess.Popen

    class Recorder(real_popen):                                  # type: ignore[misc, valid-type]
        def __init__(self, argv, *a, **k):
            calls.append(list(argv) if isinstance(argv, (list, tuple)) else [argv])
            super().__init__(argv, *a, **k)
    monkeypatch.setattr(subprocess, "Popen", Recorder)
    monkeypatch.setattr(FleetStep, "_probe", _REAL_PROBE)       # the real one: its `copilot` calls are recorded

    C.save({"fleet": {"enabled": True}})
    W.run_doctor(["--quiet", "--only", "fleet"], W.Detectors())
    before, calls[:] = list(calls), []
    folder = _synced(home)
    C.save(_mobile(enabled=True, folder=folder, operator=UPN))
    W.run_doctor(["--quiet", "--only", "fleet"], W.Detectors())
    out = capsys.readouterr().out
    assert calls == before, (before, calls)
    assert "mobile" in out or "fleet" in out

