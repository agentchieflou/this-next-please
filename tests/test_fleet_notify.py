"""When the fleet interrupts a person, and — mostly — when it does not.

The hard part of this slice is restraint, so most of what is asserted here is silence: four agents
working normally must produce nothing at all. A notifier that cries wolf is worse than none, because
the operator learns to dismiss without reading and then misses the one that mattered.
"""
from __future__ import annotations
import json
import os
import time

import pytest

from agentdata.fleet import agentstate, events as E, notify as N, registry
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, "docs", "fleet-notifications.md")


def ev(repo, kind, data=None, ticket="RDSD-1"):
    return E.event(repo, kind, data or {}, ticket=ticket)


def a_repo(tmp_path, name, **kw):
    path = make_project(tmp_path / name, **kw)
    Registry().add(path, name=name)
    return path


# A turn in which nothing needed anybody: the shape four agents produce all day.
def numbered(stream):
    """`seq` comes from `E.append`; a stream built by hand in a test has to supply it, or every
    event looks like seq 0 and `since_seq=0` skips the lot."""
    for i, e in enumerate(stream, 1):
        e["seq"] = i
    return stream


def working(repo="luna"):
    return numbered([ev(repo, "started", {"prompt": "work RDSD-1"}),
            ev(repo, "turn_started", {}),
            ev(repo, "tool_call", {"tool": "powershell", "arguments": {"command": "ad-graph unused"}}),
            ev(repo, "tool_result", {"ok": True}),
            ev(repo, "assistant_text", {"text": "Six measures are unused."}),
            ev(repo, "tool_call", {"tool": "powershell", "arguments": {"command": "git add -A"}}),
            ev(repo, "tool_result", {"ok": True}),
            ev(repo, "turn_ended", {}),
            ev(repo, "exited", {"exit_code": 0})])


# ------------------------------------------------------------------------------- the rules


def test_an_agent_working_normally_says_nothing_at_all():
    """The criterion the whole slice turns on. Every event here is the kind a busy agent emits by
    the hundred, and not one of them is worth a person's attention."""
    assert N.scan("luna", working()) == []


@pytest.mark.parametrize("tail,state,severity", [
    ([("needs_approval", {"summary": "transition RDSD-1"})], "waiting_approval", "action"),
    ([("denied", {"message": "no `git push`"})], "needs_human", "action"),
    ([("friction", {"unblock": "a decision on the UAT env"})], "blocked", "action"),
    ([("question_opened", {"question": "which workspace?"})], "needs_human", "action"),
    ([("error", {"exit_code": 1})], "error", "alert"),
    ([("phase_changed", {"to": "pr_open"})], "done", "info"),
])
def test_each_state_worth_interrupting_for_fires_once_with_its_severity(tail, state, severity):
    stream = numbered(working()[:-1] + [ev("luna", kind, data) for kind, data in tail]
                      + [ev("luna", "turn_ended", {})])
    found = N.scan("luna", stream)
    assert [f["state"] for f in found] == [state], [f["state"] for f in found]
    assert found[0]["severity"] == severity
    assert found[0]["repo"] == "luna" and found[0]["ticket"] == "RDSD-1"
    assert "luna" in found[0]["title"] and "RDSD-1" in found[0]["title"]


def test_a_state_that_persists_is_announced_once_not_every_time_it_is_looked_at():
    """A transition happens once. Notifying on the current state would mean a toast every tick for
    as long as the agent stayed stuck."""
    stream = numbered(working()[:-1] + [ev("luna", "denied", {"message": "no push"}),
                                       ev("luna", "turn_ended", {}),
                                       ev("luna", "assistant_text", {"text": "I could not push."})])
    assert len(N.scan("luna", stream)) == 1
    assert N.scan("luna", stream, since_seq=stream[-3]["seq"]) == []


def test_since_seq_is_what_stops_attaching_to_a_running_fleet_from_shouting():
    """Four agents that have been running for an hour must not produce an hour of toasts when the
    dashboard opens. The transitions are still computed -- the state machine needs them -- they are
    simply not announced."""
    stream = numbered(working()[:-1] + [ev("luna", "denied", {"message": "no push"}),
                                       ev("luna", "turn_ended", {})])
    assert N.scan("luna", stream) != []
    assert N.scan("luna", stream, since_seq=len(stream)) == []


def test_an_agent_that_stalls_on_an_open_ticket_is_reported_and_a_free_one_is_not():
    """The one rule that is not a transition: nothing happened, which is exactly why nothing would
    otherwise be said."""
    stream = working()
    long_ago = time.time() + 3600            # as though the last event were an hour old

    stalled = N.scan("luna", stream, since_seq=0, idle_minutes=20, now=long_ago)
    assert [f["state"] for f in stalled] == ["idle_stalled"]
    assert "60 minutes" in stalled[0]["body"]

    assert N.scan("luna", stream, since_seq=0, idle_minutes=20) == [], "reported before it had stalled"
    assert N.scan("luna", stream, since_seq=0, idle_minutes=20, now=long_ago, live=True) == [], \
        "a running agent is not stalled"

    no_ticket = [dict(e, ticket="") for e in stream]
    assert N.scan("luna", no_ticket, since_seq=0, idle_minutes=20, now=long_ago) == [], \
        "an agent with nothing assigned is idle, not stalled"


def test_the_states_that_notify_are_a_subset_of_the_states_that_exist():
    """A rule keyed on a state the fold can never return is a rule that never fires, and nobody
    finds out for months."""
    real = set(agentstate.STATES) | {"idle_stalled"}
    assert set(N.RULES) <= real, sorted(set(N.RULES) - real)
    assert all(sev in N.SEVERITIES for sev, _phrase in N.RULES.values())
    for quiet in ("running", "starting", "idle"):
        assert quiet not in N.RULES, f"{quiet} would interrupt someone for nothing"


# -------------------------------------------------------------------------------- dedupe


def test_the_same_thing_is_not_said_twice_inside_the_cooldown():
    items = [N.notification("luna", "needs_human", "no push", ticket="RDSD-1")]
    state: dict = {}
    now = 1_000_000.0

    assert N.suppress(list(items), state, cooldown=300, now=now)
    assert not N.suppress(list(items), state, cooldown=300, now=now + 299)
    assert N.suppress(list(items), state, cooldown=300, now=now + 301)


def test_two_agents_in_the_same_state_are_two_notifications():
    """The dedupe key is per agent. Suppressing `luna`'s denial because `other` had one would hide
    exactly the thing the fleet exists to surface."""
    state: dict = {}
    both = [N.notification("luna", "needs_human", "x"), N.notification("other", "needs_human", "x")]
    assert len(N.suppress(both, state, cooldown=300, now=1.0)) == 2


# --------------------------------------------------------------------------- quiet hours


@pytest.mark.parametrize("spec,hour,expected", [
    ("18:00-08:00", 20, True),               # the case anyone actually wants: it wraps midnight
    ("18:00-08:00", 3, True),
    ("18:00-08:00", 12, False),
    ("09:00-17:00", 12, True),
    ("09:00-17:00", 20, False),
    ("", 3, False),
    ("nonsense", 3, False),
])
def test_quiet_hours_including_the_wrap_around_midnight(spec, hour, expected):
    when = time.struct_time((2026, 1, 4, hour, 30, 0, 6, 4, 0))
    assert N.in_quiet_hours(spec, when) is expected


def test_quiet_hours_hold_the_toast_and_keep_the_badge(fleet_home, monkeypatch):  # noqa: F811
    """Downgrade, never suppress: the morning must show what happened rather than hiding it."""
    monkeypatch.setattr(N, "send_toast", lambda *a, **k: pytest.fail("a toast went out in quiet hours"))
    cfg = {"fleet": {"notify": {"quiet_hours": "18:00-08:00", "toast": True}}}
    night = time.struct_time((2026, 1, 4, 23, 0, 0, 6, 4, 0))

    out = N.deliver([N.notification("luna", "needs_human", "no push")], cfg=cfg, when=night)
    assert out[0]["quiet"] is True and out[0]["toasted"] is False
    assert [i["title"] for i in N.read_log()] == [out[0]["title"]], "the badge was lost too"


# ------------------------------------------------------------------------------ the sweep


def test_a_fleet_seen_for_the_first_time_announces_nothing(fleet_home, tmp_path):  # noqa: F811
    a_repo(tmp_path, "luna")
    E.append("luna", working())
    assert N.sweep(cfg={}) == [], "attaching to a running agent announced its history"
    assert N.read_state()["seen"]["luna"] == len(working())


def test_what_happens_after_that_is_announced(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    a_repo(tmp_path, "luna")
    E.append("luna", working())
    N.sweep(cfg={})                                              # first sight; nothing said

    E.append("luna", [ev("luna", "denied", {"message": "no `git push`"}), ev("luna", "turn_ended", {})])
    fresh = N.sweep(cfg={"fleet": {"notify": {"toast": False}}})
    assert [i["state"] for i in fresh] == ["needs_human"]
    assert "no `git push`" in fresh[0]["body"]
    assert [i["title"] for i in N.read_log()] == [fresh[0]["title"]]


def test_a_dry_run_changes_nothing(fleet_home, tmp_path):        # noqa: F811
    """`ad-fleet notify tail` is how a rule gets tuned without four agents and an afternoon. It must
    not spend the cooldown, or the real notification would then be suppressed."""
    a_repo(tmp_path, "luna")
    E.append("luna", working())
    N.sweep(cfg={})
    E.append("luna", [ev("luna", "denied", {"message": "no push"}), ev("luna", "turn_ended", {})])

    before = json.dumps(N.read_state(), sort_keys=True)
    would = N.sweep(cfg={}, dry_run=True)
    assert [i["state"] for i in would] == ["needs_human"]
    assert json.dumps(N.read_state(), sort_keys=True) == before, "a dry run moved the ledger"
    assert N.read_log() == [], "a dry run wrote to the drawer"
    assert [i["state"] for i in N.sweep(cfg={"fleet": {"notify": {"toast": False}}})] == ["needs_human"]


def test_four_busy_agents_produce_nothing_over_a_whole_shift(fleet_home, tmp_path):  # noqa: F811
    """The acceptance criterion, headless: four agents doing ordinary work, repeatedly, and not one
    notification. Asserted the way `ad-fleet notify tail` would report it."""
    for name in ("luna", "sol", "vega", "rigel"):
        a_repo(tmp_path, name)
        E.append(name, working(name))
    N.sweep(cfg={})

    for _round in range(10):
        for name in ("luna", "sol", "vega", "rigel"):
            E.append(name, working(name)[1:])
        assert N.sweep(cfg={"fleet": {"notify": {"toast": False}}}) == []
    assert N.read_log() == []


def test_the_drawer_does_not_grow_without_bound(fleet_home):     # noqa: F811
    N.deliver([N.notification("luna", "done", f"run {i}") for i in range(N.KEEP + 40)],
              cfg={"fleet": {"notify": {"toast": False}}})
    assert len(N.read_log(0)) == N.KEEP


# ---------------------------------------------------------------------------- the channels


def test_the_toast_channel_degrades_and_says_how_to_get_it_back(monkeypatch):
    assert N.toast_status({"fleet": {"notify": {"toast": False}}}) == "off"

    status = N.toast_status({})
    if os.name != "nt":
        assert "not Windows" in status
    else:
        assert status == "ready" or 'pip install "agentdata[fleet-win]"' in status


def test_a_toast_that_fails_never_takes_the_fleet_with_it(fleet_home, monkeypatch):  # noqa: F811
    """A notifier that can crash the fleet is worse than one that stays quiet: the dashboard carries
    the same information either way."""
    import sys
    import types

    module = types.ModuleType("windows_toasts")

    class Angry:
        def __init__(self, *_a, **_k):
            raise RuntimeError("WinRT said no")

    module.Toast = Angry
    module.WindowsToaster = Angry
    monkeypatch.setitem(sys.modules, "windows_toasts", module)
    monkeypatch.setattr(N, "toast_status", lambda *a, **k: "ready")

    item = N.notification("luna", "done", "finished")
    assert N.send_toast(item) is False, "a failure was reported as a sent toast"

    out = N.deliver([item], cfg={})
    assert out[0]["toasted"] is False
    assert N.read_log(), "a failed toast lost the badge as well"


def test_the_deep_link_names_the_tile(monkeypatch):
    """With four agents, "something needs you" without saying which is a notification that costs
    time rather than saving it."""
    seen = {}

    class Toast:
        text_fields: list = []
        launch_action = ""

    class Toaster:
        def __init__(self, _name):
            pass

        def show_toast(self, toast):
            seen["launch"] = toast.launch_action
            seen["text"] = list(toast.text_fields)

    import sys
    import types

    module = types.ModuleType("windows_toasts")
    module.Toast = Toast
    module.WindowsToaster = Toaster
    monkeypatch.setitem(sys.modules, "windows_toasts", module)

    item = N.notification("luna", "waiting_approval", "transition RDSD-1", ticket="RDSD-1")
    assert N.send_toast(item, "http://127.0.0.1:8765/?t=abc") is True
    assert seen["launch"] == "http://127.0.0.1:8765/?t=abc#tile=luna"
    assert seen["text"][0] == item["title"] and seen["text"][1] == item["body"]


# ----------------------------------------------------------------------------- the commands


def test_notify_test_fires_one_of_each_severity(fleet_home, capsys):    # noqa: F811
    from agentdata import cli_fleet

    assert cli_fleet.main(["notify", "test"]) == 0
    out = capsys.readouterr().out
    for severity in N.SEVERITIES:
        assert severity in out, f"{severity} was not rendered"
    assert "toast:" in out
    assert len(N.read_log()) == 3


def test_notify_tail_says_it_changed_nothing(fleet_home, tmp_path, capsys):     # noqa: F811
    from agentdata import cli_fleet

    a_repo(tmp_path, "luna")
    E.append("luna", working())
    assert cli_fleet.main(["notify", "tail"]) == 0
    out = capsys.readouterr().out
    assert "nothing was sent" in out and "would_fire: 0" in out
    assert N.read_state() == {}, "a dry run moved the ledger"


def test_status_says_whether_toasts_are_available(fleet_home, capsys):  # noqa: F811
    from agentdata import cli_fleet

    assert cli_fleet.main(["status"]) == 0
    assert "toast:" in capsys.readouterr().out


# ------------------------------------------------------------------------- page and contract


STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")


def test_the_page_synthesises_its_chime_rather_than_shipping_one():
    """A bundled .wav is payload, a file that can fail to install, and one more thing to fetch.
    WebAudio is in every browser this page has to run in."""
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "AudioContext" in js and "createOscillator" in js
    assert not [n for n in os.listdir(STATIC) if n.endswith((".wav", ".mp3", ".ogg"))]
    assert 'localStorage.getItem("fleet.chime")' in js, "the choice must survive a reload"
    assert 'chimeOn = localStorage.getItem("fleet.chime") === "1"' in js, "the chime must default to off"


def test_the_page_reads_the_deep_link_the_toast_sends():
    js = open(os.path.join(STATIC, "app.js"), encoding="utf-8").read()
    assert "#tile=" in js and "hashchange" in js


def test_the_contract_documents_every_rule_and_every_key():
    text = open(CONTRACT, encoding="utf-8").read()
    for state in N.RULES:
        assert f"`{state}`" in text, f"the {state} rule is not documented"
    for key in ("toast", "dashboard", "chime", "cooldown", "idle_minutes", "quiet_hours"):
        assert f"fleet.notify.{key}" in text, f"fleet.notify.{key} is not documented"
    assert 'agentdata[fleet-win]' in text
    assert "ad-fleet notify tail" in text and "ad-fleet notify test" in text


def test_the_notification_rows_name_the_settings_that_change_them():
    """HANDOFF.md rule: a check names the prompt keys that fix it, so `ad-setup --patch` is
    surgical. Empty keys are meaningful and not an omission -- they mean *no answer fixes this*
    (install a package, log in), and `--patch` then lists the row under `manual` with its hint
    rather than asking a pointless question. So the assertion is about the rows a setting really
    does control."""
    from agentdata.setup.steps.fleet import FleetStep
    from agentdata.setup.wizard import Context, Detectors, Prompter

    ctx = Context(cfg={"fleet": {"enabled": True}}, det=Detectors(), ask=Prompter(),
                  interactive=False)
    step = FleetStep()
    step._check_notifications(ctx, {"toast": "off", "settings": N.settings({})})

    by_name = {c.name: c for c in ctx.checks}
    assert set(by_name) == {"toast", "rules"}
    assert by_name["toast"].keys == ("fleet.notify.toast",)
    assert set(by_name["rules"].keys) == {"fleet.notify.cooldown", "fleet.notify.idle_minutes",
                                          "fleet.notify.quiet_hours"}
    for row in ctx.checks:
        assert all(k.startswith("fleet.notify.") for k in row.keys), row.keys
