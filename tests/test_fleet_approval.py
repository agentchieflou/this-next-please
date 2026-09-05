"""The gate between an unattended agent and a write to a system of record.

The property that matters most is the boring one: **outside a fleet, nothing changes**. A person in
PyCharm, a CI job, and every other test in this suite run with the markers unset, and if the gate
were to touch the disk there it would be a new failure mode on the path that already worked.
"""
from __future__ import annotations
import json
import os
import threading
import time

import pytest

from agentdata.connectors import pncli as P
from agentdata.fleet import approval, events as E, launch, registry

from test_fleet import make_project
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT = os.path.join(ROOT, "docs", "fleet-approvals.md")


@pytest.fixture()
def as_agent(fleet_home, monkeypatch):                          # noqa: F811 - the fixture is the argument
    """A process that a supervisor launched: both markers set, as `child_env` sets them."""
    monkeypatch.setenv(registry.AGENT_ENV, "luna")
    return "luna"


def _answer(id: str, state: str, *, reason: str = "", after: float = 0.05) -> threading.Thread:
    """An operator in another shell, a moment later."""
    def run():
        time.sleep(after)
        approval.decide(id, state, reason=reason, by="operator")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _wait_for_request(timeout: float = 5.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        waiting = approval.pending()
        if waiting:
            return waiting[0]["id"]
        time.sleep(0.02)
    raise AssertionError("no approval request appeared")


# ----------------------------------------------------------------------- outside a fleet


def test_outside_a_fleet_nothing_is_written_and_nothing_waits(fleet_home, monkeypatch):  # noqa: F811
    """The path a person is on. If this ever blocks or writes, `ad-jira` has become unusable in
    PyCharm -- which is where it is used most."""
    monkeypatch.delenv(registry.AGENT_ENV, raising=False)
    before = time.time()
    d = approval.require("jira-transition", "RDSD-1 -> In Review", {"key": "RDSD-1"}, timeout=999)
    assert d.ok and d.auto
    assert time.time() - before < 1.0
    assert not os.path.exists(approval.approvals_dir()), "the gate wrote to disk outside a fleet"


def test_one_marker_is_not_a_fleet(fleet_home, monkeypatch):    # noqa: F811
    """Both markers or neither. A stale `AGENTDATA_FLEET_AGENT` in someone's shell profile must not
    turn their laptop into a machine that blocks on every Jira transition."""
    monkeypatch.setenv(registry.AGENT_ENV, "luna")
    monkeypatch.delenv(registry.FLEET_DIR_ENV, raising=False)
    assert approval.require("jira-transition", "x", {}).auto


# ---------------------------------------------------------------------------- the gate


def test_a_write_waits_and_one_click_releases_it(as_agent):
    d = None

    def agent():
        nonlocal d
        d = approval.require("jira-transition", "RDSD-1: In Progress -> In Review",
                             {"key": "RDSD-1", "transition": "31 In Review"},
                             ticket="RDSD-1", timeout=20, poll=0.02)

    t = threading.Thread(target=agent)
    t.start()
    id = _wait_for_request()
    record = approval.read_request(id)
    assert record["payload"] == {"key": "RDSD-1", "transition": "31 In Review"}, \
        "the operator must approve exactly what will be sent, not a description of it"
    assert record["ticket"] == "RDSD-1"

    approval.decide(id, approval.APPROVED, by="operator")
    t.join(timeout=10)
    assert d is not None and d.ok and d.by == "operator"
    assert [e["kind"] for e in E.read("luna")] == ["needs_approval", "approval_resolved"]


def test_a_denial_carries_the_reason_the_agent_will_quote(as_agent):
    d = None

    def agent():
        nonlocal d
        d = approval.require("pncli-write", "confluence create-page", {}, timeout=20, poll=0.02)

    t = threading.Thread(target=agent)
    t.start()
    _answer(_wait_for_request(), approval.DENIED, reason="wrong space, this belongs in DATAENG")
    t.join(timeout=10)

    assert d.state == approval.DENIED
    meta = approval.refusal(d, "ad-pncli raw")
    assert meta["refused"] == "approval_denied"
    assert meta["hint"] == "wrong space, this belongs in DATAENG"
    assert meta["approval"] == d.id


def test_a_timeout_says_how_to_release_it_and_that_re_running_is_safe(as_agent):
    d = approval.require("jira-transition", "RDSD-1 -> Done", {}, timeout=0, poll=0.01)
    assert d.state == approval.TIMEOUT
    meta = approval.refusal(d, "ad-jira transition")
    assert meta["refused"] == "approval_timeout"
    assert f"ad-fleet approve {d.id}" in meta["hint"]
    assert "re-run" in meta["hint"]


def test_the_gate_fails_closed_when_it_cannot_record_the_request(as_agent, monkeypatch):
    """A gate that fails open on a full disk is not a gate, it is a delay. Nobody saw this request,
    so nobody can have approved it."""
    def no(*_a, **_k):
        raise OSError("read-only file system")

    monkeypatch.setattr(approval.textio, "write_json", no)
    d = approval.require("jira-transition", "RDSD-1 -> Done", {}, timeout=0)
    assert not d.ok and d.state == approval.UNAVAILABLE
    assert approval.refusal(d, "x")["refused"] == "approval_unavailable"


def test_a_denial_without_a_reason_is_refused(as_agent):
    approval.require("jira-transition", "x", {}, timeout=0)
    id = _wait_for_request()
    with pytest.raises(approval.ApprovalError) as e:
        approval.decide(id, approval.DENIED)
    assert "reason" in str(e.value)
    approval.decide(id, approval.DENIED, reason="not this ticket")


def test_an_approval_is_answered_once(as_agent):
    approval.require("jira-transition", "x", {}, timeout=0)
    id = _wait_for_request()
    approval.decide(id, approval.APPROVED)
    with pytest.raises(approval.ApprovalError) as e:
        approval.decide(id, approval.APPROVED)
    assert "already" in str(e.value)


def test_an_unknown_id_names_what_is_actually_waiting(as_agent):
    approval.require("jira-transition", "x", {}, timeout=0)
    real = _wait_for_request()
    with pytest.raises(approval.ApprovalError) as e:
        approval.decide("no-such-approval", approval.APPROVED)
    assert real in e.value.hint


def test_pending_never_prunes_and_decided_eventually_does(as_agent):
    approval.require("jira-transition", "old and unanswered", {}, timeout=0)
    stale = _wait_for_request()
    old = time.time() - 400 * 86400
    os.utime(approval._request_path(stale), (old, old))

    approval.require("jira-transition", "answered long ago", {}, timeout=0)
    answered = [r["id"] for r in approval.pending() if r["id"] != stale][0]
    approval.decide(answered, approval.APPROVED)
    for path in (approval._request_path(answered), approval._decision_path(answered)):
        os.utime(path, (old, old))

    approval._prune()
    assert os.path.exists(approval._request_path(stale)), \
        "an unanswered write is not litter, however old"
    assert not os.path.exists(approval._decision_path(answered))


# ------------------------------------------------------------- what counts as a write


@pytest.mark.parametrize("args", [
    ["jira", "search", "--jql", "key = RDSD-1"],
    ["jira", "get", "--key", "RDSD-1"],
    ["jira", "get-issue", "--key", "RDSD-1"],
    ["confluence", "get-page", "--id", "123"],
    ["bitbucket", "list-prs"],
    ["confluence", "create-page", "--dry-run", "--title", "x"],   # a dry run sends nothing
    ["jira", "transition", "--dry-run"],
    ["--help"],
    ["where"],
])
def test_reads_and_dry_runs_are_never_gated(args):
    assert not P.is_write(args), args


@pytest.mark.parametrize("args", [
    ["confluence", "create-page", "--title", "x"],
    ["confluence", "update-page", "--id", "1"],
    ["jira", "comment", "--key", "RDSD-1", "--body", "x"],
    ["jira", "transition", "--key", "RDSD-1"],
    ["bitbucket", "create-pull-request", "--title", "x"],
    ["bitbucket", "pr-create"],                      # the verb is still TODO(HANDOFF); gated anyway
    ["jira", "some-verb-nobody-has-pinned"],
])
def test_anything_not_known_to_be_a_read_is_a_write(args):
    """The asymmetry is the design. A write verb missing from a write-list would be sent
    unattended; a read verb missing from the read-list costs one extra click."""
    assert P.is_write(args), args


def test_the_verb_is_read_from_the_bare_tokens_not_the_options():
    """pncli is commander.js: every argument is a named option, so nothing but the command path can
    look like a verb -- including a value that happens to read like one."""
    assert P.verb(["confluence", "create-page", "--title", "jira get"]) == ("confluence", "create-page")


# ----------------------------------------------------------- the commands that are gated


def _jira_transition(monkeypatch, capsys, argv, **kw):
    from test_jira_workflow import _run

    return _run(monkeypatch, capsys, argv, **kw)


STORY = [{"id": "31", "name": "In Review", "to": {"name": "In Review", "statusCategory": {"key": "indeterminate"}}}]


def test_ad_jira_transition_is_gated_only_when_it_would_write(as_agent, monkeypatch, capsys):
    rc, out, op, _ = _jira_transition(monkeypatch, capsys,
                                      ["transition", "RDSD-1", "--to", "review", "--dry-run"],
                                      itype="Story", status="In Progress", transitions=STORY)
    assert rc == 0 and "dry_run: true" in out
    assert approval.pending() == [], "a dry run asked for approval"


def test_ad_jira_transition_waits_for_the_click(as_agent, monkeypatch, capsys):
    result = {}

    def agent():
        result["rc"], result["out"], _, _ = _jira_transition(
            monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"],
            itype="Story", status="In Progress", transitions=STORY, after="In Review")

    t = threading.Thread(target=agent)
    t.start()
    id = _wait_for_request()
    assert approval.read_request(id)["payload"]["to"] == "In Review", \
        "the operator sees the resolved transition, not the intent word"
    approval.decide(id, approval.APPROVED)
    t.join(timeout=15)
    assert result["rc"] == 0 and "moved: true" in result["out"]


def test_ad_jira_transition_refuses_on_a_denial_and_never_posts(as_agent, monkeypatch, capsys):
    result = {}

    def agent():
        result["rc"], result["out"], result["op"], _ = _jira_transition(
            monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"],
            itype="Story", status="In Progress", transitions=STORY)

    t = threading.Thread(target=agent)
    t.start()
    _answer(_wait_for_request(), approval.DENIED, reason="RDSD-1 is not the ticket you are on")
    t.join(timeout=15)

    assert result["rc"] == 2
    assert "refused: approval_denied" in result["out"]
    assert "RDSD-1 is not the ticket you are on" in result["out"]
    posts = [c for c in result["op"].calls if c[0].startswith("POST")]
    assert posts == [], "a denied transition was posted to Jira anyway"


# --------------------------------------------------------------- the operator's commands


def test_the_operator_commands_round_trip(as_agent, capsys, monkeypatch):
    from agentdata import cli_fleet

    approval.require("jira-transition", "RDSD-1: In Progress -> In Review",
                     {"key": "RDSD-1"}, ticket="RDSD-1", timeout=0)
    id = _wait_for_request()

    assert cli_fleet.main(["approvals"]) == 0
    listed = capsys.readouterr().out
    assert id in listed and "pending: 1" in listed

    assert cli_fleet.main(["approval", id]) == 0
    assert "key: RDSD-1" in capsys.readouterr().out, "the payload is what the operator decides on"

    assert cli_fleet.main(["approve", id, "--comment", "yes"]) == 0
    assert "decision: approved" in capsys.readouterr().out

    assert cli_fleet.main(["approvals"]) == 0
    assert "pending: 0" in capsys.readouterr().out


def test_deny_needs_a_reason_at_the_command_line(as_agent, capsys):
    from agentdata import cli_fleet

    approval.require("jira-transition", "x", {}, timeout=0)
    id = _wait_for_request()
    with pytest.raises(SystemExit) as e:
        cli_fleet.main(["deny", id])
    assert e.value.code == 2                      # argparse: --reason is required
    assert cli_fleet.main(["deny", id, "--reason", "wrong ticket"]) == 0
    assert "decision: denied" in capsys.readouterr().out


# ------------------------------------------------------------------ the other layer, and the doc


@pytest.mark.parametrize("pattern", ["shell(pncli)", "shell(curl)", "shell(Invoke-RestMethod)",
                                     "shell(wget)", "shell(Invoke-WebRequest)"])
def test_the_launch_line_denies_every_way_round_the_gate(pattern):
    """Layer 1. None of these is on the allow-list either -- this is the second line, because the
    boundary otherwise is a model's own classifier, which the spike measured being talked around."""
    deny = launch.deny_tools({})
    assert pattern in deny
    assert not any(p.startswith(f"shell({pattern[6:-1].split()[0]}") for p in launch.allow_tools({}))


def test_the_contract_lists_every_refusal_code_and_every_gated_verb():
    text = open(CONTRACT, encoding="utf-8").read()
    for code in approval.REFUSALS.values():
        assert f"`{code}`" in text, f"{code} is not documented"
    for product, verb in sorted(P.READ_VERBS):
        assert f"{product} {verb}" in text, f"the read verb {product} {verb} is not documented"
    assert "ad-jira transition" in text and "ad-pncli raw" in text


def test_every_skill_that_writes_tells_the_agent_what_a_refusal_means():
    """A skill that does not carry this line leaves the agent retrying a blocked write until its
    turn budget runs out, which looks like a hang rather than a question."""
    for name in ("jira-transition", "bitbucket-pr", "confluence-publish"):
        body = open(os.path.join(ROOT, "skills", name, "SKILL.md"), encoding="utf-8").read()
        assert "approval_timeout" in body, f"{name} does not say what an approval refusal means"
        assert "friction-log" in body


def _pncli_env(monkeypatch, tmp_path, case="search_ok"):
    from tests import fakes                                    # noqa: F401 - registered by the harness
    import test_fakes

    return test_fakes._pncli_env(monkeypatch, tmp_path, case)


def test_ad_pncli_gates_a_write_and_leaves_a_read_alone(as_agent, monkeypatch, tmp_path, capsys):
    """The `raw` path is where a Confluence page or a Bitbucket PR is actually created, so it is the
    one that has to stop -- and `jira search` through the same binary must not."""
    from agentdata import cli

    _pncli_env(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["ad-pncli", "jira", "search", "--jql", "key = RDSD-1"])
    cli.main_pncli()
    assert "key: RDSD-1" in capsys.readouterr().out
    assert approval.pending() == [], "a read asked for approval"

    result = {}

    def agent():
        monkeypatch.setattr("sys.argv", ["ad-pncli", "raw", "confluence", "create-page",
                                         "--space", "RDSD", "--title", "Findings"])
        try:
            cli.main_pncli()
            result["code"] = 0
        except SystemExit as exit:
            result["code"] = exit.code

    t = threading.Thread(target=agent)
    t.start()
    id = _wait_for_request()
    assert "confluence create-page" in approval.read_request(id)["summary"]
    _answer(id, approval.DENIED, reason="publish to DATAENG, not RDSD")
    t.join(timeout=15)

    assert result["code"] == 2
    out = capsys.readouterr().out
    assert "refused: approval_denied" in out and "publish to DATAENG" in out


def test_the_gate_is_wired_into_exactly_the_commands_the_doc_names():
    """A doc that names a gated command the code does not gate is worse than no doc."""
    for module in ("cli_jira.py", "cli.py"):
        source = open(os.path.join(ROOT, "agentdata", module), encoding="utf-8").read()
        assert "approval.require(" in source, f"{module} names no gate"


def test_a_configured_timeout_is_honoured(as_agent):
    assert approval.timeout_seconds({"fleet": {"approval_timeout": 5}}) == 5
    assert approval.timeout_seconds({}) == approval.DEFAULT_TIMEOUT_S
    assert approval.timeout_seconds({"fleet": {"approval_timeout": "nonsense"}}) == approval.DEFAULT_TIMEOUT_S


def test_the_request_is_json_a_dashboard_can_read(as_agent):
    approval.require("jira-transition", "RDSD-1 -> Done", {"key": "RDSD-1"}, ticket="RDSD-1", timeout=0)
    id = _wait_for_request()
    record = json.loads(open(approval._request_path(id), encoding="utf-8").read())
    assert set(record) >= {"id", "repo", "ticket", "kind", "summary", "payload", "created"}
