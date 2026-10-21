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

from agentdata.connectors import toil as T
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

    class NoWaiting:
        """The gate's own `time`, whose `sleep` -- the gate's only way to wait -- fails the test."""

        def __getattr__(self, name):
            return getattr(time, name)

        @staticmethod
        def sleep(seconds):
            raise AssertionError(f"the gate waited ({seconds}s) outside a fleet")

    # Not a clock (#602): a gate that waited at all, for a second or for the whole 999, fails here, and a loaded
    # runner cannot fail it.
    monkeypatch.setattr(approval, "time", NoWaiting())
    d = approval.require("jira-transition", "RDSD-1 -> In Review", {"key": "RDSD-1"}, timeout=999)
    assert d.ok and d.auto
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
        d = approval.require("confluence-publish", "create page \"Findings\" in RDSD", {}, timeout=20, poll=0.02)

    t = threading.Thread(target=agent)
    t.start()
    _answer(_wait_for_request(), approval.DENIED, reason="wrong space, this belongs in DATAENG")
    t.join(timeout=10)

    assert d.state == approval.DENIED
    meta = approval.refusal(d, "ad-confluence publish")
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
    assert "reason" in str(e.value) and e.value.code == "reason_required"
    with pytest.raises(approval.ApprovalError) as e:
        approval.decide(id, "maybe", reason="x")
    assert e.value.code == "bad_state"
    approval.decide(id, approval.DENIED, reason="not this ticket")


def test_an_approval_is_answered_once(as_agent):
    approval.require("jira-transition", "x", {}, timeout=0)
    id = _wait_for_request()
    approval.decide(id, approval.APPROVED)
    with pytest.raises(approval.ApprovalError) as e:
        approval.decide(id, approval.APPROVED)
    assert "already" in str(e.value) and e.value.code == "already_decided"


def test_an_unknown_id_names_what_is_actually_waiting(as_agent):
    approval.require("jira-transition", "x", {}, timeout=0)
    real = _wait_for_request()
    with pytest.raises(approval.ApprovalError) as e:
        approval.decide("no-such-approval", approval.APPROVED)
    assert real in e.value.hint and e.value.code == "not_waiting"


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
    ["jira", "issue", "search", "--jql", "key = RDSD-1"],
    ["jira", "issue", "get", "RDSD-1"],
    ["jira", "issue", "history", "RDSD-1"],
    ["jira", "api", "GET", "rest/api/2/myself"],
    ["confluence", "page", "get", "123"],
    ["bitbucket", "pr", "list"],
    ["confluence", "page", "create", "--help"],
    ["--help"],
    ["version"],
    ["connections", "list"],
    ["connections", "test", "corp-jira"],
    ["dossiers", "show"],
    ["wait", "--until", "result != null", "--", "jenkins", "run", "get", "x", "42"],
])
def test_reads_and_help_are_never_gated(args):
    assert not T.is_write(args), args


@pytest.mark.parametrize("args", [
    ["confluence", "page", "create", "--title", "x", "--allow-write"],
    ["confluence", "page", "update", "1", "--allow-write"],
    ["jira", "issue", "comment", "RDSD-1", "--body", "x", "--allow-write"],
    ["jira", "issue", "transition", "RDSD-1", "--to", "done", "--allow-write"],
    ["bitbucket", "pr", "create", "--title", "x", "--allow-write"],
    ["jira", "api", "POST", "rest/api/2/issue", "--allow-write"],
    ["--allow-write", "bitbucket", "pr", "merge", "42"],
    ["jira", "issue", "comment", "RDSD-1", "--body", "--allow-write"],    # as a value it still counts
    ["jira", "issue", "transition", "RDSD-1", "--allow-write=true"],
    ["wait", "--until", "x", "--", "jira", "issue", "transition", "RDSD-1", "--allow-write"],   # past `--` too
    ["connections", "add", "corp"], ["connections", "login", "corp"], ["connections"],
    ["dossiers", "init", "pay"], ["skill", "install"], ["skills", "marketplace", "add", "x"],
    ["setup", "alias"], ["feedback", "bug", "--consent"], ["mcp"],
])
def test_anything_that_can_write_is_a_write(args):
    """toil refuses a service write without `--allow-write`, so its presence anywhere is the write -- even as some
    option's value, because a false yes costs one refused read and a false no sends a write unattended. The
    commands that write toil's own setup without the flag are writes too."""
    assert T.is_write(args), args


def test_the_command_path_skips_global_option_values():
    """`toil --workspace jira connections list` is a listing, not a Jira call: the value of a global option is not
    the command."""
    assert T.verb(["--workspace", "jira", "connections", "list"]) == ("connections", "list")
    assert not T.is_write(["--workspace", "jira", "connections", "list"])
    assert T.verb(["jira", "issue", "get", "RDSD-1", "--select", "fields.status"]) == ("jira", "issue", "get")


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
    assert cli_fleet.main(["approve", id]) == 2
    assert "refused: already_decided" in capsys.readouterr().out, "the refusal names its code, not `refused`"

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


@pytest.mark.parametrize("pattern", ["shell(curl)", "shell(Invoke-RestMethod)",
                                     "shell(wget)", "shell(Invoke-WebRequest)"])
def test_the_launch_line_denies_every_way_round_the_gate(pattern):
    """Layer 1, for an agent set to `fleet.permissions: strict`. None of these is on the allow-list
    either -- this is the second line, because the boundary otherwise is a model's own classifier,
    which the spike measured being talked around. (The default since 2026-10-02 is a Copilot window's
    tools, where layer 2 -- the gate inside every `ad-*` write -- is the boundary.) toil is not here:
    it is allowed, and the fleet's shim refuses its writes (tests/test_fleet_toil_gate.py)."""
    strict = {"fleet": {"permissions": "strict"}}
    deny = launch.deny_tools(strict)
    assert pattern in deny
    assert not any(p.startswith(f"shell({pattern[6:-1].split()[0]}") for p in launch.allow_tools(strict))


def test_the_contract_lists_every_refusal_code_and_every_gated_verb():
    text = open(CONTRACT, encoding="utf-8").read()
    for code in approval.REFUSALS.values():
        assert f"`{code}`" in text, f"{code} is not documented"
    for group in sorted(T.LOCAL_WRITES):
        assert f"`{group}`" in text, f"the local-write group {group} is not documented"
    assert "ad-jira transition" in text and "ad-confluence publish" in text and "ad-git pr" in text
    assert "`toil_write_in_fleet`" in text and "fleet's toil shim" in text and "`--allow-write`" in text


def test_every_skill_that_writes_tells_the_agent_what_a_refusal_means():
    """A skill that does not carry this line leaves the agent retrying a blocked write until its
    turn budget runs out, which looks like a hang rather than a question."""
    for name in ("jira-transition", "jira-create", "bitbucket-pr", "confluence-publish"):
        body = open(os.path.join(ROOT, "skills", name, "SKILL.md"), encoding="utf-8").read()
        assert "approval_timeout" in body, f"{name} does not say what an approval refusal means"
        assert "friction-log" in body


def _toil_env(monkeypatch, tmp_path, case="search_ok"):
    from tests import fakes                                    # noqa: F401 - registered by the harness
    import test_fakes

    return test_fakes._toil_env(monkeypatch, tmp_path, case)


def _gate(argv, capsys):
    from agentdata.fleet import toil_gate

    code = toil_gate.main(list(argv))
    return code, capsys.readouterr().out


def test_the_fleet_shim_gates_a_write_and_leaves_a_read_alone(as_agent, monkeypatch, tmp_path, capfd):
    """toil is run directly, so the shim first on a fleet agent's PATH is where a Confluence page or a
    Bitbucket PR would be created -- it refuses, and names the extension. A Jira search through the
    same shim must reach the real toil untouched, and neither asks the operator anything."""
    from agentdata.fleet import toil_gate

    _toil_env(monkeypatch, tmp_path)
    assert toil_gate.main(["jira", "issue", "search", "--jql", "key = RDSD-22399"]) == 0
    assert '"key":"RDSD-22399"' in capfd.readouterr().out
    assert toil_gate.main(["confluence", "page", "create", "--space", "RDSD", "--title", "Findings",
                           "--allow-write"]) == 2
    out = capfd.readouterr().out
    assert "refused: toil_write_in_fleet" in out and "ad-confluence publish" in out
    assert approval.pending() == [], "the shim refuses; the extension is what asks"


def test_a_help_token_does_not_unlock_a_write(as_agent, monkeypatch, capsys):
    """#524, with toil: `--allow-write` decides before `--help` is looked at, so `-h` as a PR title -- or as a flag
    -- never lets a write through the shim."""
    from agentdata.fleet import toil_gate

    ran = []
    monkeypatch.setattr(toil_gate, "passthrough", lambda argv: ran.append(list(argv)) or 0)
    code, out = _gate(["bitbucket", "pr", "create", "--title", "-h", "--allow-write"], capsys)
    assert code == 2 and ran == [] and "refused: toil_write_in_fleet" in out and "ad-git pr" in out


def test_a_write_without_allow_write_runs_and_toil_itself_refuses_it(as_agent, monkeypatch, capsys):
    """Without `--allow-write` toil sends nothing (WRITE_DISABLED), so the shim has no reason to stop it: it runs at
    once, nothing waits, and toil's own refusal is what the agent reads."""
    from agentdata.fleet import toil_gate

    ran = []
    monkeypatch.setattr(toil_gate, "passthrough", lambda argv: ran.append(list(argv)) or 0)
    code, _out = _gate(["bitbucket", "pr", "create", "--title", "x"], capsys)
    assert code == 0 and ran == [["bitbucket", "pr", "create", "--title", "x"]]
    assert approval.pending() == []


def test_the_gate_is_wired_into_exactly_the_commands_the_doc_names():
    """A doc that names a gated command the code does not gate is worse than no doc."""
    for module in ("cli_jira.py", "cli_confluence.py", "cli_git.py"):
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


# ------------------------------------------------------------ the digest (#543, MOB-D1)


def _agent_waiting(kind="jira-transition", summary="RDSD-1: In Progress -> In Review", payload=None):
    """An agent blocked in `require()` on a thread; returns (thread, result dict, request id)."""
    result = {}

    def agent():
        result["d"] = approval.require(kind, summary, payload if payload is not None else {"key": "RDSD-1"},
                                       ticket="RDSD-1", timeout=20, poll=0.02)

    t = threading.Thread(target=agent)
    t.start()
    return t, result, _wait_for_request()


def test_the_digest_is_over_exactly_the_six_fields_and_is_stable_across_pretty_and_canonical_json(tmp_path):
    record = {"id": "luna-jira-transition-20260927T100000-ab12", "repo": "luna", "ticket": "RDSD-1",
              "kind": "jira-transition", "summary": "RDSD-1: In Progress → In Review",
              "payload": {"key": "RDSD-1", "to": "In Review", "fields": {"b": 2, "a": [1, "ü"]}},
              "created": "2026-09-27T10:00:00", "pid": 4242}
    six = ("id", "kind", "summary", "payload", "created", "pid")
    import hashlib

    want = hashlib.sha256(json.dumps({k: record[k] for k in six}, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()
    got = approval.digest(record)
    assert got == want and len(got) == 64 and all(c in "0123456789abcdef" for c in got)

    # Outside the six: repo, ticket, and the digest itself never move it.
    assert approval.digest({**record, "repo": "other", "ticket": "X-9", "digest": "f" * 64}) == got
    # Inside the six: every one of them does.
    for k in six:
        assert approval.digest({**record, k: "changed"}) != got, k

    # A request re-read from a pretty file hashes the same as the object it was written from.
    path = tmp_path / "pretty.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    again = json.loads(path.read_text(encoding="utf-8"))
    assert approval.canonical(again) == approval.canonical(record)
    assert approval.digest(again) == got
    assert approval.canonical({"b": 1, "a": "ü"}) == '{"a":"ü","b":1}'.encode("utf-8")


def test_require_writes_the_digest_into_the_request_and_the_phone_never_gets_the_pid(as_agent):
    t, result, id = _agent_waiting()
    on_disk = json.loads(open(approval._request_path(id), encoding="utf-8").read())
    assert on_disk["pid"] == os.getpid(), "the pid stays in the request file, inside the hash"
    assert on_disk["digest"] == approval.digest(on_disk)

    approval.decide(id, approval.APPROVED, by="operator")
    t.join(timeout=10)
    assert result["d"].ok

    decision = json.loads(open(approval._decision_path(id), encoding="utf-8").read())
    assert decision["digest"] == on_disk["digest"] and decision["via"] == "laptop"
    assert "pid" not in decision, "the decision file is what the bridge mirrors; it never carries the pid"
    for event in E.read("luna"):
        assert "pid" not in event["data"], event


def test_decide_refuses_a_digest_that_does_not_match_the_request_on_disk(as_agent):
    approval.require("jira-transition", "RDSD-1 -> Done", {"key": "RDSD-1"}, timeout=0)
    first = _wait_for_request()
    approval.require("jira-transition", "RDSD-2 -> Done", {"key": "RDSD-2"}, timeout=0)
    second = next(r["id"] for r in approval.pending() if r["id"] != first)
    other = approval.read_request(second)["digest"]

    with pytest.raises(approval.ApprovalError) as e:
        approval.decide(first, approval.APPROVED, digest=other, via="mobile", by="mobile:op@example.com")
    assert e.value.code == "digest_mismatch"
    assert "different request" in e.value.msg and e.value.hint
    assert approval.read_decision(first) == {}, "a refused decision wrote a file"
    assert not os.path.exists(approval._decision_path(first))

    # The matching digest is accepted, and what it says about itself is kept.
    done = approval.decide(first, approval.APPROVED, digest=approval.read_request(first)["digest"],
                           via="mobile", by="mobile:op@example.com")
    assert done["via"] == "mobile" and done["by"] == "mobile:op@example.com"
    assert approval.read_decision(first)["digest"] == approval.read_request(first)["digest"]


def test_require_refuses_a_decision_carrying_a_wrong_digest_and_the_agent_stops(as_agent, monkeypatch, capsys):
    result = {}

    def agent():
        result["rc"], result["out"], result["op"], _ = _jira_transition(
            monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"],
            itype="Story", status="In Progress", transitions=STORY)

    t = threading.Thread(target=agent)
    t.start()
    id = _wait_for_request()
    # A decision somebody made about something else: written straight to disk, the way a bridge or an
    # older process would, past decide()'s own check.
    approval.textio.write_json(approval._decision_path(id), {
        "id": id, "decision": approval.APPROVED, "reason": "", "by": "mobile:op@example.com",
        "via": "mobile", "decided": "2026-09-27T10:00:00", "digest": "0" * 64})
    t.join(timeout=15)

    assert result["rc"] == 2
    assert "refused: approval_denied" in result["out"]
    assert "the decision names a different request (digest mismatch)" in result["out"]
    posts = [c for c in result["op"].calls if c[0].startswith("POST")]
    assert posts == [], "a transition approved for another request was posted to Jira"
    resolved = [e for e in E.read("luna") if e["kind"] == "approval_resolved"]
    assert resolved and resolved[-1]["data"]["decision"] == approval.DENIED
    assert resolved[-1]["data"]["by"] == "mobile:op@example.com"
    assert resolved[-1]["data"]["reason"] == "the decision names a different request (digest mismatch)"


def test_a_decision_without_a_digest_is_still_accepted_so_the_desk_and_the_cli_are_unchanged(as_agent):
    # An older build's decision file: no digest, no via.
    t, result, id = _agent_waiting()
    approval.textio.write_json(approval._decision_path(id), {
        "id": id, "decision": approval.APPROVED, "reason": "", "by": "operator", "decided": "2026-09-27T10:00:00"})
    t.join(timeout=10)
    d = result["d"]
    assert d.ok and d.by == "operator" and d.via == ""

    # Today's laptop callers pass neither digest nor via, and get both written with today's values.
    t, result, id = _agent_waiting(summary="RDSD-2 -> Done")
    approval.decide(id, approval.APPROVED, by="operator")
    t.join(timeout=10)
    d = result["d"]
    assert d.ok and d.by == "operator" and d.via == "laptop"


def test_an_approve_comment_reaches_the_gated_commands_meta(as_agent, monkeypatch, capsys, tmp_path):
    from agentdata import cli_fleet

    # ad-jira transition, released by `ad-fleet approve --comment` from another shell.
    result = {}

    def agent():
        result["rc"], result["out"], _, _ = _jira_transition(
            monkeypatch, capsys, ["transition", "RDSD-1", "--to", "review"],
            itype="Story", status="In Progress", transitions=STORY, after="In Review")

    t = threading.Thread(target=agent)
    t.start()
    id = _wait_for_request()
    assert cli_fleet.main(["approve", id, "--comment", "fine, and say so on the ticket"]) == 0
    t.join(timeout=15)
    assert result["rc"] == 0 and "moved: true" in result["out"]
    assert "approval_note: \"fine, and say so on the ticket\"" in result["out"] or \
        "approval_note: fine, and say so on the ticket" in result["out"]

    approved = approval.Decision(approval.APPROVED, id="luna-x-1", reason="ship it before noon", by="operator")
    monkeypatch.setattr(approval, "require", lambda *a, **k: approved)

    # ad-jira create: the emitted record gains the note.
    from test_jira_create import _run as _create

    rc, out, _ = _create(monkeypatch, capsys, ["create", "--project", "RDSD", "--summary", "Fix the margin measure"])
    assert rc == 0 and "approval_note: ship it before noon" in out

    # ad-confluence publish: on the printed meta.
    from agentdata import cli_confluence

    _toil_env(monkeypatch, tmp_path, "page_created")
    from tests import fakes as F
    F.toil_connections(monkeypatch)
    page = tmp_path / "findings.md"
    page.write_text("# Findings\n\nTwo rows differ.\n", encoding="utf-8")
    assert cli_confluence.main(["publish", str(page), "--space", "RDSD"]) == 0
    assert "approval_note: ship it before noon" in capsys.readouterr().out
