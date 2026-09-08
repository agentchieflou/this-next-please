"""Epic #91's acceptance sentence, as a test: four repositories, four agents, one window.

Four real `copilot` processes -- the fake from `tests/fakes/`, launched by the real supervisor,
running the real `ad-state` against real files. Nothing here is stubbed inside the fleet: the
events are parsed from what the processes actually wrote, `state.json` changes because a subprocess
changed it, and the approvals are answered through the same HTTP endpoints the page's buttons call.

**Driven through the API, not a browser.** The page's buttons do exactly one thing each -- POST to
`/api/start|send|stop|approve|deny` -- so driving those is driving the page minus its CSS. What a
browser would add is whether the layout looks right, and that is a person's judgement, not an
assertion. It would also add a Chromium download to every CI run against this repository's
zero-dependency rule. `tests/test_fleet_serve.py` covers the wiring between the markup and the
script; `docs/windows-verification.md` covers the eyes.
"""
from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request

import pytest

import fakes
from agentdata.fleet import agentstate, approval, events as E, lifecycle, notify as N, serve as S, supervisor
from agentdata.fleet.registry import Registry

pytestmark = pytest.mark.slow

# One scenario per repository: the four things an operator actually has to tell apart.
FLEET = {
    "alpha": "triage-ok",          # finishes, needs nobody
    "bravo": "asks-question",      # stops on a question, the way a skill does: one `ad-state set
                                   # phase=blocked --question "…"`, so the state is `blocked` and
                                   # the *reason* is the question
    "charlie": "friction-stop",    # writes a friction log and stops
    "delta": "crash-mid-turn",     # dies mid-turn, leaving a lock over a dead pid
}
SETTLE_S = 90


def _project(root: str, project: str = "RDSD") -> str:
    os.makedirs(os.path.join(root, ".agent"), exist_ok=True)
    with open(os.path.join(root, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"# Project\n\n- jira_project: {project}\n")
    with open(os.path.join(root, ".agent", "state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"project": project, "phase": "idle", "active_ticket": None,
                   "open_questions": [], "artifacts": []}, f)
    return root


@pytest.fixture()
def fleet(tmp_path, monkeypatch):
    """Four registered repositories, a fake `copilot` on PATH, and a fleet directory of our own."""
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    fakes.apply(monkeypatch, tmp_path, ["copilot"], npm=True)

    registry = Registry()
    paths = {}
    for name in FLEET:
        paths[name] = _project(str(tmp_path / name))
        registry.add(paths[name], name=name)
    return paths


def _start_all(monkeypatch, paths):
    """Start each agent with its own scenario. `AGENTDATA_FAKE_CASE` is per launch, so four agents
    can behave four different ways in one run."""
    for name, case in FLEET.items():
        monkeypatch.setenv("AGENTDATA_FAKE_CASE", case)
        supervisor.start(name, key=f"RDSD-{list(FLEET).index(name) + 1}",
                         cfg={"fleet": {"notify": {"toast": False}}})


def _settle(names, seconds: float = SETTLE_S) -> None:
    """Wait for every agent's process to be gone. A fake turn is fast; a loaded runner is not."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not any(supervisor.live(n) for n in names):
            return
        time.sleep(0.2)
    still = [n for n in names if supervisor.live(n)]
    raise AssertionError(f"agents still running after {seconds}s: {still}")


def _refresh(paths):
    for name in FLEET:
        try:
            E.refresh(name, paths[name], repo_state=Registry().get(name).state())
        except OSError:
            pass


# ------------------------------------------------------------------------- the whole thing


def test_four_agents_four_outcomes_one_window(fleet, monkeypatch):
    """The epic's acceptance criterion. Four repositories, four tickets, and the operator can tell
    at a glance which one needs them."""
    _start_all(monkeypatch, fleet)
    _settle(FLEET)
    lifecycle.reap_all()
    _refresh(fleet)

    derived = {name: agentstate.derive(E.read(name)) for name in FLEET}
    states = {name: d["state"] for name, d in derived.items()}
    assert states["alpha"] == "idle", "the agent that finished cleanly is asking for attention"
    assert states["bravo"] == "blocked"
    assert states["charlie"] == "blocked"
    assert states["delta"] == "error"

    # Two agents are blocked and the operator has to tell them apart at a glance, so the *reason*
    # has to be the specific one and not "something is blocked, go and look".
    assert "workspace" in derived["bravo"]["why"].lower(), derived["bravo"]["why"]
    assert "workspace" in derived["charlie"]["why"].lower(), derived["charlie"]["why"]
    assert derived["bravo"]["why"] != derived["charlie"]["why"]

    needing = [n for n, s in states.items() if agentstate.needs_the_human(s)]
    assert sorted(needing) == ["bravo", "charlie", "delta"]


def test_the_agents_really_changed_their_own_state_files(fleet, monkeypatch):
    """`ad-state` is the only writer of `state.json`, and here it really was one: a subprocess the
    fleet launched ran the real command against a real file."""
    _start_all(monkeypatch, fleet)
    _settle(FLEET)

    phases = {}
    for name, path in fleet.items():
        with open(os.path.join(path, ".agent", "state.json"), encoding="utf-8") as f:
            phases[name] = json.load(f)
    assert phases["alpha"]["phase"] == "documenting"
    assert phases["bravo"]["phase"] == "blocked"
    assert phases["bravo"]["open_questions"] == ["Which workspace is UAT?"]
    assert phases["charlie"]["phase"] == "blocked"


def test_nothing_but_the_agent_wrote_the_repositories(fleet, monkeypatch):
    """The supervisor writes only under the fleet directory. The repository belongs to the agent,
    and a fleet that edited it would be a second writer nobody could see."""
    before = {name: _tree(path) for name, path in fleet.items()}
    _start_all(monkeypatch, fleet)
    _settle(FLEET)
    after = {name: _tree(path) for name, path in fleet.items()}

    for name in FLEET:
        added = set(after[name]) - set(before[name])
        changed = {p for p in set(before[name]) & set(after[name])
                   if before[name][p] != after[name][p]}
        touched = added | changed
        # Everything an agent touches is under `.agent/`, and it got there through `ad-state` or
        # the friction log -- both of which the agent ran, not the fleet.
        assert all(p.startswith(".agent/") for p in touched), f"{name}: {sorted(touched)}"


def _tree(root: str) -> dict:
    out = {}
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            path = os.path.join(dirpath, name)
            try:
                out[os.path.relpath(path, root).replace("\\", "/")] = os.path.getmtime(path)
            except OSError:
                pass
    return out


def test_the_friction_log_reaches_the_tile_as_its_unblock_sentence(fleet, monkeypatch):
    _start_all(monkeypatch, fleet)
    _settle(FLEET)
    _refresh(fleet)

    derived = agentstate.derive(E.read("charlie"))
    assert derived["state"] == "blocked"
    assert "which workspace" in derived["why"].lower(), derived["why"]


def test_a_crashed_agent_is_noticed_and_can_be_resumed(fleet, monkeypatch):
    """The one that died mid-turn. Its lock names a pid that is gone, and until something reaps it
    the fleet would report a corpse as running."""
    _start_all(monkeypatch, fleet)
    _settle(FLEET)

    found = lifecycle.reap("delta")
    assert found and found[0]["kind"] == "error"
    assert "TypeError" in found[0]["data"].get("stderr", "")

    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "crash-mid-turn")
    lock = supervisor.restart("delta")
    assert "--resume" in lock["launch"]
    _settle(["delta"])
    _refresh(fleet)

    said = [e["data"]["text"] for e in E.read("delta") if e["kind"] == "assistant_text"]
    assert any("interrupted" in t for t in said), said


def test_a_question_is_answered_by_talking_to_the_agent(fleet, monkeypatch):
    """`ad-fleet send` continues the same session, which is what makes an answer an answer rather
    than a new conversation."""
    _start_all(monkeypatch, fleet)
    _settle(FLEET)
    _refresh(fleet)
    assert agentstate.derive(E.read("bravo"))["state"] == "blocked"

    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "asks-question")
    supervisor.send("bravo", "Use UAT.")
    _settle(["bravo"])
    _refresh(fleet)

    with open(os.path.join(fleet["bravo"], ".agent", "state.json"), encoding="utf-8") as f:
        state = json.load(f)
    assert state["phase"] == "optimizing" and state["open_questions"] == []


# --------------------------------------------------------------------- the allow-list is real


def test_a_denied_tool_is_refused_exactly_as_the_real_cli_refused_it(fleet, monkeypatch):
    """The fake reproduces the spike's measured behaviour: the tool is attempted, refused, reported
    on `tool.execution_complete`, and the turn still exits 0. A fake that were *safer* than the real
    thing would hide the reason the allow-list has to be an enumerated whitelist."""
    monkeypatch.setenv("AGENTDATA_FAKE_CASE", "denied-tool")
    supervisor.start("alpha", key="RDSD-9", cfg={"fleet": {"notify": {"toast": False}}})
    _settle(["alpha"])
    _refresh(fleet)

    stream = E.read("alpha")
    denied = [e for e in stream if e["kind"] == "denied"]
    assert denied, [e["kind"] for e in stream]
    assert "Permission denied" in denied[0]["data"]["message"]
    assert [e for e in stream if e["kind"] == "exited"], "the turn did not finish 0 after a denial"
    assert agentstate.derive(stream)["state"] == "needs_human"


# --------------------------------------------------------------- driving it as the page does


@pytest.fixture()
def serving(fleet):
    import threading

    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    S.record(server, token)
    try:
        yield server, token
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def _get(server, token, path):
    port = server.server_address[1]
    sep = "&" if "?" in path else "?"
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}{sep}t={token}", timeout=30) as r:
        return json.loads(r.read())


def _post(server, token, path, body):
    port = server.server_address[1]
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}?t={token}",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=60) as r:
        return json.loads(r.read())


def test_the_page_shows_four_tiles_and_says_which_need_you(serving, fleet, monkeypatch):
    server, token = serving
    _start_all(monkeypatch, fleet)
    _settle(FLEET)
    lifecycle.reap_all()

    data = _get(server, token, "/api/fleet")
    assert data["ok"] and len(data["repos"]) == 4
    by_name = {r["repo"]: r for r in data["repos"]}
    assert by_name["alpha"]["needs_human"] is False
    assert all(by_name[n]["needs_human"] for n in ("bravo", "charlie", "delta"))
    for row in data["repos"]:
        assert row["why"], f"{row['repo']} gives the operator no reason"


def test_an_approval_is_answered_from_the_page_and_the_agent_continues(serving, fleet, monkeypatch):
    """The one genuinely important button, driven the way the page drives it."""
    import threading

    server, token = serving
    monkeypatch.setenv("AGENTDATA_FLEET_AGENT", "alpha")
    got = {}

    def agent():
        got["d"] = approval.require("jira-transition", "RDSD-1: In Progress -> In Review",
                                    {"key": "RDSD-1"}, ticket="RDSD-1", timeout=60, poll=0.05)

    thread = threading.Thread(target=agent)
    thread.start()
    deadline = time.time() + 20
    while not approval.pending() and time.time() < deadline:
        time.sleep(0.05)

    page = _get(server, token, "/api/fleet")
    assert page["approvals"], "the waiting write never reached the page"
    assert page["approvals"][0]["payload"] == {"key": "RDSD-1"}

    answer = _post(server, token, "/api/approve", {"id": page["approvals"][0]["id"]})
    assert answer["ok"] and answer["decision"] == "approved"
    thread.join(timeout=30)
    assert got["d"].ok

    assert _get(server, token, "/api/fleet")["approvals"] == []


def test_the_drawer_lists_what_happened_and_only_that(serving, fleet, monkeypatch):
    """Four agents, three of which need a person: three notifications and no more. A notifier that
    also announced the one that worked would be training the operator to ignore it."""
    server, token = serving
    N.sweep(cfg={"fleet": {"notify": {"toast": False}}})       # first sight: records, says nothing

    _start_all(monkeypatch, fleet)
    _settle(FLEET)
    lifecycle.reap_all()
    _refresh(fleet)

    fresh = N.sweep(cfg={"fleet": {"notify": {"toast": False}}})
    raised = {i["repo"]: i["state"] for i in fresh}
    assert "alpha" not in raised, f"the agent that finished cleanly raised {raised.get('alpha')}"
    assert raised.get("bravo") == "blocked"
    assert raised.get("charlie") == "blocked"
    assert raised.get("delta") == "error"

    drawer = _get(server, token, "/api/notifications")
    assert {n["repo"] for n in drawer["notifications"]} == {"bravo", "charlie", "delta"}


def test_history_reports_the_four_dispatches(serving, fleet, monkeypatch):
    server, token = serving
    _start_all(monkeypatch, fleet)
    _settle(FLEET)
    _refresh(fleet)

    runs = _get(server, token, "/api/history")["runs"]
    assert sorted(r["repo"] for r in runs) == ["alpha", "bravo", "charlie", "delta"]
    assert all(r["ticket"].startswith("RDSD-") for r in runs)


def test_the_whole_run_never_reaches_the_network(fleet, monkeypatch):
    """A fake that quietly fell back to the real thing would make this suite a slow way of proving
    nothing. `copilot` resolves to the shim on PATH, and no transcript reaches out."""
    import socket

    def refuse(*a, **k):
        raise AssertionError("the end-to-end run tried to open a socket to somewhere")

    real = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", lambda self, address, *a: (
        real(self, address) if str(address[0]).startswith("127.") or address[0] == "::1"
        else refuse()))
    _start_all(monkeypatch, fleet)
    _settle(FLEET)
