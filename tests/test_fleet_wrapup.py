"""`ad-fleet wrapup <repo>`: preview every write for one agent, then write exactly the ticked ones, in order (#503).

Most cases replace `wrapup.RUN` with an in-process recorder. It answers `git push` through `cli_git.push` itself
against a real tmp repository and a bare `origin`, `jira comment` through `cli_jira` against the fake Jira, and
`pncli bitbucket pr` / `confluence publish` through their real parsers -- which do not have those verbs yet, so
they answer argparse's *invalid choice* and the rows read `not_pinned`, as they will until #506 and #507 land.
Transitions are canned per test: the fake Jira's workflow has only *Done*.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from agentdata import cli_fleet, cli_git, cli_jira
from agentdata.fleet import approval, registry, serve as S, supervisor, wrapup as WRAP
from agentdata.fleet.registry import Registry
from tests.fakes import jira as FJ

from test_fleet import make_project

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def git(cwd, *args) -> str:
    return subprocess.run([*GIT, *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def commit(cwd, subject: str) -> None:
    git(cwd, "commit", "-q", "--allow-empty", "-m", subject)


class Recorder:
    """`RUN`, in process. `canned[step]` overrides an adapter's answer: `{"dry": meta, "real": meta}`."""

    def __init__(self, fake: FJ.FakeJira, status: str = "To Do", delay: float = 0.0):
        self.fake, self.status, self.delay = fake, status, delay
        self.calls: list[tuple[list[str], str, dict]] = []
        self.canned: dict = {}
        self.lock = threading.Lock()

    @property
    def writes(self) -> list[list[str]]:
        return [a for a, _, _ in self.calls if "--dry-run" not in a]

    def __call__(self, argv, cwd, env=None):
        with self.lock:
            self.calls.append((list(argv), cwd, dict(env or {})))
            if self.delay:
                time.sleep(self.delay)
                self.delay = 0.0
            return self._answer(list(argv[3:]), cwd)

    def _answer(self, args, cwd):
        dry = "--dry-run" in args
        step = {"git": "push", "pncli": "pr", "confluence": "page"}.get(args[0]) or \
            ("comment" if args[1] == "comment" else "transition")
        if step in self.canned:
            meta = self.canned[step]["dry" if dry else "real"]
            return {"code": 0 if meta.get("ok") else 2, "meta": dict(meta), "tables": {}, "stderr": ""}
        if step == "push":
            rc, meta = cli_git.push(cwd, dry_run=dry)
            return {"code": rc, "meta": meta, "tables": {}, "stderr": ""}
        if step in ("pr", "page"):
            from agentdata import cli, cli_confluence

            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                saved, sys.argv = sys.argv, [f"ad-{args[0]}", *args[1:]]   # ad-pncli reads sys.argv itself
                try:
                    rc = cli.main_pncli() if step == "pr" else cli_confluence.main(args[1:])
                except SystemExit as e:
                    rc = e.code
                finally:
                    sys.argv = saved
            return {"code": rc, "meta": {}, "tables": {}, "stderr": err.getvalue()}
        if step == "comment":
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli_jira.main(args[1:])
            blocks = WRAP.read_toon(out.getvalue())
            return {"code": rc, "meta": blocks.pop("meta", {}), "tables": blocks, "stderr": ""}
        to = args[args.index("--to") + 1]
        name = {"in-progress": "In Progress", "review": "In Review", "done": "Done"}.get(to, to)
        meta = {"ok": True, "key": args[2], "status": self.status, "transition": f"21 {name}", "to": name}
        return {"code": 0, "meta": {**meta, "dry_run": True} if dry else {**meta, "moved": True},
                "tables": {}, "stderr": ""}


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.delenv(registry.AGENT_ENV, raising=False)
    return tmp_path / "fleet"


@pytest.fixture()
def luna(fleet_home, tmp_path, monkeypatch):
    """A ticketed checkout on `feature/RDSD-1-thing` with 3 commits nobody pushed, and no PR."""
    bare = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    path = make_project(tmp_path / "luna", phase="building", ticket="RDSD-1")
    git(path, "init", "-q")
    git(path, "remote", "add", "origin", str(bare))
    git(path, "add", "AGENTS.md")
    git(path, "commit", "-q", "-m", "chore: start")
    git(path, "push", "-q", "origin", "main")
    git(path, "remote", "set-head", "origin", "main")
    git(path, "checkout", "-q", "-b", "feature/RDSD-1-thing")
    for s in ("feat: one", "fix: two", "docs: three"):
        commit(path, s)
    Registry().add(path, name="luna")
    fake = FJ.FakeJira(issues=3, histories=1)
    client = fake.client()
    monkeypatch.setattr(cli_jira, "_client", lambda redetect=False, a=None: ({}, client, {}))
    rec = Recorder(fake)
    monkeypatch.setattr(WRAP, "RUN", rec)
    return {"path": path, "bare": bare, "fake": fake, "rec": rec}


def _state(path, **sets):
    f = os.path.join(path, ".agent", "state.json")
    with open(f, encoding="utf-8") as fh:
        st = json.load(fh)
    st.update(sets)
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(st, fh)


def _rows(plan) -> dict:
    return {r["id"].split(":", 1)[0]: r for r in plan["rows"]}


def _tree(path) -> dict:
    out = {}
    for d, dirs, files in os.walk(path):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in files:
            p = os.path.join(d, f)
            out[p] = (os.stat(p).st_mtime_ns, os.stat(p).st_size)
    return out


def _refs(bare) -> str:
    return git(bare, "for-each-ref", "--format=%(refname) %(objectname)")


# ------------------------------------------------------------------------------------------ the preview


def test_plan_runs_only_dry_runs_of_the_module_form_and_writes_nothing_in_the_checkout(luna, monkeypatch):
    monkeypatch.setenv(registry.AGENT_ENV, "whoever")         # a desk started from inside a fleet agent
    before = _tree(luna["path"])
    plan = WRAP.plan("luna", "day")
    assert luna["rec"].calls, "no adapter was run"
    for argv, cwd, env in luna["rec"].calls:
        assert argv[:3] == [sys.executable, "-m", "agentdata"], argv
        assert "--dry-run" in argv, argv
        assert os.path.samefile(cwd, luna["path"])
        assert env[registry.AGENT_ENV] is None and env[registry.FLEET_DIR_ENV] is None, \
            "the child would be gated as an agent: the operator's confirm is the approval"
        assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GCM_INTERACTIVE"] == "never"
    assert _tree(luna["path"]) == before, "the plan wrote inside the checkout"
    assert plan["repo"] == "luna" and plan["mode"] == "day"


def test_end_of_day_on_a_ticketed_branch_with_three_unpushed_commits(luna):
    rows = _rows(WRAP.plan("luna", "day"))
    assert list(rows) == ["push", "pr", "page", "comment", "transition-in-progress"]
    push = rows["push"]
    assert push["ok"] and push["ticked"] and push["payload"]["ahead"] == 3
    assert rows["pr"]["code"] == "not_pinned" and not rows["pr"]["ticked"]
    assert "ad-pncli capture-help" in rows["pr"]["hint"] and "WRAP-D6" in rows["pr"]["hint"]
    assert rows["page"]["code"] == "no_source" and "RDSD-1-confluence.md" in rows["page"]["hint"]
    comment = rows["comment"]
    assert comment["ok"] and comment["ticked"]
    body = open(WRAP.comment_path("luna"), encoding="utf-8").read()
    assert body.startswith("End of day, ") and "luna on feature/RDSD-1-thing" in body
    assert "3 commits since the branch point: docs: three; fix: two; feat: one" in body
    assert "phase: building" in body and "PR: none" in body and "page: none" in body
    assert rows["transition-in-progress"]["ticked"], "to do → in progress when commits exist"
    assert not any(r["step"] == "merge" for r in rows.values())
    assert not any(k in rows for k in ("transition-review", "transition-done")), "end of day offers neither"
    assert rows["comment"]["needs"] == [] and rows["pr"]["needs"] == []


def test_end_of_project_offers_review_only_with_a_pr_and_done_unticked(luna):
    rows = _rows(WRAP.plan("luna", "project"))
    review, done = rows["transition-review"], rows["transition-done"]
    assert review["ok"] and not review["ticked"] and "no PR yet" in review["hint"]
    assert done["ok"] and not done["ticked"] and "operator" in done["hint"]
    assert rows["comment"]["ticked"] and open(WRAP.comment_path("luna"), encoding="utf-8").read().startswith(
        "End of project, ")
    assert not any(r["step"] == "merge" for r in rows.values())

    _state(luna["path"], pr_url="https://bitbucket.example/projects/X/repos/y/pull-requests/7")
    rows = _rows(WRAP.plan("luna", "project"))
    assert rows["transition-review"]["ticked"], "an open PR makes review the default"
    assert not rows["transition-done"]["ticked"]


def test_untracked_work_gets_push_and_pr_rows_and_no_jira_rows(luna):
    _state(luna["path"], active_ticket="")
    plan = WRAP.plan("luna", "day")
    assert [r["step"] for r in plan["rows"]] == ["push", "pr"]
    assert any("untracked" in n and "rule 17" in n for n in plan["notes"])
    assert not any(a[3] == "jira" for a, _, _ in luna["rec"].calls)


def test_a_checkout_on_master_has_no_push_or_pr_that_can_run(luna):
    git(luna["path"], "checkout", "-q", "-b", "master")
    rows = _rows(WRAP.plan("luna", "day"))
    for step in ("push", "pr"):
        assert not rows[step]["ok"] and not rows[step]["ticked"], step
        assert "not on a branch" in rows[step]["hint"] and "rule 16" in rows[step]["hint"], step
    assert rows["push"]["code"] == "default_branch"


def test_a_terminal_phase_gets_no_progress_comment_at_end_of_day(luna):
    _state(luna["path"], phase="pr_open")
    plan = WRAP.plan("luna", "day")
    assert "comment" not in _rows(plan) and not any(k.startswith("transition") for k in _rows(plan))
    assert any("pr_open" in n for n in plan["notes"])


def test_nothing_new_since_the_last_wrap_up_means_no_comment_at_end_of_day(luna):
    head = git(luna["path"], "rev-parse", "HEAD")
    WRAP._append("luna", {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 5)),
                          "mode": "day", "step": "comment", "ok": True, "head": head, "phase": "building"})
    plan = WRAP.plan("luna", "day")
    assert "comment" not in _rows(plan)
    assert any("nothing new" in n for n in plan["notes"])


def test_two_plans_of_an_unchanged_checkout_match_and_a_new_commit_moves_the_push_id(luna):
    a, b = WRAP.plan("luna", "day"), WRAP.plan("luna", "day")
    assert a["plan_id"] == b["plan_id"] and [r["id"] for r in a["rows"]] == [r["id"] for r in b["rows"]]
    commit(luna["path"], "feat: four")
    c = WRAP.plan("luna", "day")
    assert _rows(c)["push"]["id"] != _rows(a)["push"]["id"] and c["plan_id"] != a["plan_id"]


# ------------------------------------------------------------------------------------------ the run


PR_OK = {"dry": {"ok": True, "action": "create", "title": "RDSD-1: x", "draft": True, "source": "feature/RDSD-1-thing",
                 "target": "main"},
         "real": {"ok": True, "action": "create", "pr_id": 7, "url": "bitbucket.example/projects/X/repos/y/pull-requests/7"}}
PAGE_OK = {"dry": {"ok": True, "action": "update", "page_id": 5, "title": "RDSD-1", "version": 3},
           "real": {"ok": True, "page_id": 5, "version": 4, "url": "https://wiki.example/pages/5"}}


def test_run_writes_push_pr_page_comment_transition_in_that_order(luna):
    rec = luna["rec"]
    rec.canned.update(pr=PR_OK, page=PAGE_OK)
    os.makedirs(os.path.join(luna["path"], ".agent", "out"), exist_ok=True)
    open(os.path.join(luna["path"], ".agent", "out", "RDSD-1-confluence.md"), "w").close()
    plan = WRAP.plan("luna", "day")
    ticked = [r["id"] for r in plan["rows"] if r["ticked"]]
    assert [i.split(":")[0] for i in ticked] == ["push", "pr", "page", "comment", "transition-in-progress"]
    rows = _rows(plan)
    assert rows["pr"]["needs"] == ["push"] and rows["comment"]["needs"] == ["pr", "page"]
    rec.calls.clear()
    done = WRAP.run("luna", "day", ticked)
    assert [r["done"] for r in done["results"]] == ["written"] * 5, done["results"]
    order = [a[3] + (" " + a[4] if a[3] == "jira" else "") for a in rec.writes]
    assert order == ["git", "pncli", "confluence", "jira comment", "jira transition"]
    assert "refs/heads/feature/RDSD-1-thing" in _refs(luna["bare"])
    assert len(luna["fake"].comments) == 1


def test_a_failed_push_skips_pr_and_everything_waiting_on_it(luna):
    rec = luna["rec"]
    rec.canned.update(pr=PR_OK, push={"dry": {"ok": True, "branch": "feature/RDSD-1-thing", "remote": "origin",
                                              "target": "refs/heads/feature/RDSD-1-thing", "ahead": 3},
                                      "real": {"ok": False, "refused": "push_failed", "error": "rejected",
                                               "hint": "fetch and look"}})
    plan = WRAP.plan("luna", "day")
    ticked = [r["id"] for r in plan["rows"] if r["ticked"]]
    done = {r["step"]: r for r in WRAP.run("luna", "day", ticked)["results"]}
    assert done["push"]["done"] == "failed"
    assert done["pr"]["done"] == "skipped: push failed"
    assert done["comment"]["done"] == "skipped: push failed"
    assert done["transition"]["done"] == "skipped: push failed"
    assert [a[3] for a in rec.writes] == ["git"], "nothing after the failed push was written"


def test_a_step_whose_payload_changed_since_the_preview_is_not_written(luna):
    rec = luna["rec"]
    plan = WRAP.plan("luna", "day")
    ticked = [r["id"] for r in plan["rows"] if r["ticked"]]
    commit(luna["path"], "feat: after the preview")
    before = _refs(luna["bare"])
    done = {r["step"]: r for r in WRAP.run("luna", "day", ticked)["results"]}
    assert done["push"]["done"] == "changed" and "preview again" in done["push"]["hint"]
    assert _refs(luna["bare"]) == before
    assert not any(a[3] == "git" for a in rec.writes)


def test_each_written_step_leaves_one_operator_record_and_one_result_line(luna, monkeypatch):
    seen_pending = []
    real_write = approval.textio.write_json

    def spying(path, data, *a, **kw):
        out = real_write(path, data, *a, **kw)
        seen_pending.append(len(approval.pending()))           # between the two writes, and after each
        return out

    monkeypatch.setattr(approval.textio, "write_json", spying)
    plan = WRAP.plan("luna", "day")
    ticked = [r["id"] for r in plan["rows"] if r["ticked"]]
    done = WRAP.run("luna", "day", ticked)
    written = [r for r in done["results"] if r["done"] == "written"]
    assert len(written) == 3                                    # push, comment, transition
    history = approval.history(limit=0)
    assert len(history) == 3
    assert all(h["by"] == "operator" and h["via"] == "wrapup" and h["decision"] == "approved" for h in history)
    assert sorted(h["kind"] for h in history) == ["git-push", "jira-comment", "jira-transition"]
    assert approval.pending() == [] and seen_pending and max(seen_pending) == 0, \
        "a record was listed as pending: a pane could have offered it to the a key"
    lines = WRAP.results("luna")
    assert [line["step"] for line in lines] == ["push", "comment", "transition"]
    assert all({"ts", "mode", "step", "ok", "url", "error", "hint"} <= set(line) for line in lines)


def test_the_rail_opens_the_recorded_pr_when_state_has_none(luna):
    WRAP._append("luna", {"ts": "2026-09-25T10:00:00", "mode": "day", "step": "pr", "ok": True,
                          "url": "bitbucket.example/projects/X/repos/y/pull-requests/7", "error": "", "hint": ""})
    shown = S.show_for("luna")
    pr = next(link for link in shown["links"] if link["name"] == "pr")
    assert pr["url"] == "https://bitbucket.example/projects/X/repos/y/pull-requests/7"
    _state(luna["path"], pr_url="https://bitbucket.example/pull-requests/9")
    pr = next(link for link in S.show_for("luna")["links"] if link["name"] == "pr")
    assert pr["url"].endswith("/pull-requests/9"), "the agent's own URL wins"


def test_a_mid_turn_agent_gets_every_row_skipped_and_nothing_runs(luna):
    supervisor.write_lock("luna", {"pid": os.getpid(), "ticket": "RDSD-1"})
    plan = WRAP.plan("luna", "day")
    assert plan["rows"] and all(r["code"] == "busy" and not r["ticked"] for r in plan["rows"])
    assert all("when this turn ends" in r["hint"] for r in plan["rows"])
    assert luna["rec"].calls == []
    done = WRAP.run("luna", "day", [r["id"] for r in plan["rows"]])
    assert all(r["done"] == "skipped" and r["code"] == "busy" for r in done["results"])
    assert luna["rec"].calls == []
    supervisor.write_lock("luna", {"pid": os.getpid(), "kind": "console"})
    assert "a console is yours" in WRAP.plan("luna", "day")["rows"][0]["hint"]


# ------------------------------------------------------------------------------------------ the desk and the CLI


def test_the_desk_answers_at_once_and_the_rows_arrive_later(luna):
    luna["rec"].delay = 2.0
    t0 = time.monotonic()
    ans = S.act("wrapup", {"repo": "luna", "mode": "day", "dry_run": True})
    assert time.monotonic() - t0 < 0.2 and ans["reading"] is True and ans["job"]
    again = S.act("wrapup", {"repo": "luna", "mode": "day", "dry_run": True})
    assert again["job"] == ans["job"], "a second ask while one reads joins it"
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/wrapup?repo=luna&t={token}"
        deadline, got = time.time() + 15, {}
        while time.time() < deadline:
            with urllib.request.urlopen(url, timeout=10) as r:
                got = json.loads(r.read())
            if got.get("state") == "planned":
                break
            time.sleep(0.05)
        assert got["state"] == "planned" and got["job"] == ans["job"]
        direct = WRAP.plan("luna", "day")
        assert [r["id"] for r in got["plan"]["rows"]] == [r["id"] for r in direct["rows"]]

        with pytest.raises(S.ServeError) as e:
            S.act("wrapup", {"job": "luna-00000000", "steps": []})
        assert e.value.code == "plan_changed"
        ans = S.act("wrapup", {"job": got["job"], "steps": []})
        assert ans["writing"] is True
        assert WRAP.wait("luna", 15) and WRAP.job_state("luna")["state"] == "done"
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


def test_the_stream_sends_a_wrapup_frame_when_the_job_moves(luna):
    frames: list[str] = []
    stop = threading.Event()
    t = threading.Thread(target=S.stream_events, args=({}, stop, frames.append),
                         kwargs={"tick": 0.05, "polls": False, "sweep": False, "agents": False}, daemon=True)
    t.start()
    try:
        deadline = time.time() + 10
        while not any("event: tick" in f for f in frames) and time.time() < deadline:
            time.sleep(0.02)
        assert not any("event: wrapup" in f for f in frames), "a fresh stream records, it does not announce"
        WRAP._write_job("luna", {"job": "luna-abc", "repo": "luna", "state": "reading"})
        while not any("event: wrapup" in f for f in frames) and time.time() < deadline:
            time.sleep(0.02)
        frame = next(f for f in frames if "event: wrapup" in f)
        assert json.loads(frame.split("data: ", 1)[1]) == {"repo": "luna", "job": "luna-abc", "state": "reading"}
    finally:
        stop.set()
        t.join(5)


def _cli(capsys, *argv):
    rc = cli_fleet.main(["wrapup", *argv])
    return rc, capsys.readouterr().out


def test_the_cli_previews_refuses_without_a_confirm_and_refuses_a_stale_one(luna, capsys):
    rc, out = _cli(capsys, "luna", "--dry-run")
    assert rc == 0 and "dry_run: true" in out and "steps[" in out and "plan_id:" in out
    plan_id = out.split("plan_id: ", 1)[1].split()[0]
    rc, out = _cli(capsys, "luna")
    assert rc == 2 and f"--confirm {plan_id}" in out and luna["rec"].writes == []
    commit(luna["path"], "feat: later")
    rc, out = _cli(capsys, "luna", "--confirm", plan_id)
    assert rc == 2 and "refused: plan_changed" in out and "steps[" in out and luna["rec"].writes == []
    rc, out = _cli(capsys)
    assert rc == 2 and "name a repo" in out


def test_the_cli_confirm_writes_the_ticked_steps(luna, capsys):
    rc, out = _cli(capsys, "luna", "--dry-run")
    plan_id = out.split("plan_id: ", 1)[1].split()[0]
    rc, out = _cli(capsys, "luna", "--confirm", plan_id)
    assert rc == 0, out
    assert "written: 3" in out and [a[3] for a in luna["rec"].writes] == ["git", "jira", "jira"]


def test_no_dry_run_wrote_to_the_remote_or_to_jira(luna):
    """The real adapters in process: `cli_git` against the bare origin, `cli_jira` against the fake Jira."""
    rec = luna["rec"]
    real_answer = rec._answer

    def through_jira(args, cwd):                               # transitions too, not canned
        if args[:2] == ["jira", "transition"]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = cli_jira.main(args[1:])
            blocks = WRAP.read_toon(out.getvalue())
            return {"code": rc, "meta": blocks.pop("meta", {}), "tables": blocks, "stderr": ""}
        return real_answer(args, cwd)

    rec._answer = through_jira
    before = _refs(luna["bare"])
    for mode in ("day", "project"):
        plan = WRAP.plan("luna", mode)
        assert plan["rows"]
    assert _refs(luna["bare"]) == before
    assert [r for r in luna["fake"].requests if r.method == "POST"] == []
    rows = _rows(WRAP.plan("luna", "project"))
    assert not rows["transition-review"]["ok"] and "Done" in rows["transition-review"]["available"], \
        "a transition the workflow does not have carries Jira's own names"


# ------------------------------------------------------------------------------------------ the sweep (#505)


def _checkout(tmp_path, name, *, ticket="", branch="", commits=("feat: one",), phase="building"):
    """A registered checkout with a bare `origin` holding `main`; on `branch` with `commits` unpushed."""
    bare = tmp_path / f"{name}.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    path = make_project(tmp_path / name, phase=phase, ticket=ticket)
    git(path, "init", "-q")
    git(path, "remote", "add", "origin", str(bare))
    git(path, "add", "AGENTS.md")
    git(path, "commit", "-q", "-m", "chore: start")
    git(path, "push", "-q", "origin", "main")
    git(path, "remote", "set-head", "origin", "main")
    if branch:
        git(path, "checkout", "-q", "-b", branch)
    for s in commits:
        commit(path, s)
    Registry().add(path, name=name)
    return path, bare


@pytest.fixture()
def fleet4(luna, tmp_path):
    """#505's four fixtures: `luna` (ticketed, three unpushed commits), `sol` (untracked, with commits),
    `terra` (ticketed, on its default branch) and `vega` (ticketed, mid-turn)."""
    sol, _ = _checkout(tmp_path, "sol", branch="feature/tidy", commits=("chore: tidy",))
    terra, _ = _checkout(tmp_path, "terra", ticket="RDSD-2", commits=("fix: on main",))
    vega, _ = _checkout(tmp_path, "vega", ticket="RDSD-3", branch="feature/RDSD-3-x")
    supervisor.write_lock("vega", {"pid": os.getpid(), "ticket": "RDSD-3"})
    return {**luna, "paths": {"luna": luna["path"], "sol": sol, "terra": terra, "vega": vega}}


def _repos(swept) -> dict:
    return {r["repo"]: r for r in swept["repos"]}


def _slots(row) -> dict:
    return {s["id"].split(":", 1)[0]: s for s in row["steps"]}


PR_DRY = {"dry": {"ok": True, "action": "create", "pr_id": None, "title": "RDSD-1: thing", "draft": True,
                  "source": "feature/RDSD-1-thing", "target": "main", "description": "replaced", "live_hash": ""},
          "real": {"ok": True, "action": "create", "pr_id": 7, "url": "https://bitbucket.example/pull-requests/7"}}
PAGE_DRY = {"dry": {"ok": True, "action": "update", "page_id": 5, "title": "RDSD-1", "space": "RDSD", "parent": "1",
                    "version": 3, "current_chars": 10, "new_chars": 12, "edited": False},
            "real": {"ok": True, "page_id": 5, "version": 4, "url": "https://wiki.example/pages/5"}}


def test_plan_all_writes_nothing_outside_the_fleet_dir_and_its_totals_match_its_rows(fleet4, fleet_home):
    before = {n: _tree(p) for n, p in fleet4["paths"].items()}
    refs = _refs(fleet4["bare"])
    swept = WRAP.plan_all("day")
    assert {n: _tree(p) for n, p in fleet4["paths"].items()} == before, "the sweep wrote inside a checkout"
    assert _refs(fleet4["bare"]) == refs and fleet4["rec"].writes == []
    assert [r for r in fleet4["fake"].requests if r.method == "POST"] == []
    assert swept["mode"] == "day" and [r["repo"] for r in swept["repos"]] == ["luna", "sol", "terra", "vega"]
    kinds = {"push": "pushes", "pr": "prs", "page": "pages", "comment": "comments", "transition": "transitions"}
    want = {k: 0 for k in kinds.values()}
    pinned = 0
    for row in swept["repos"]:
        for s in row["steps"]:
            want[kinds[s["step"]]] += bool(s["ticked"])
            pinned += s["code"] == "not_pinned"
    assert swept["totals"] == {**want, "not_pinned": pinned}, swept["totals"]
    assert swept["writes"] == sum(want.values()) and len(swept["plan_id"]) == 12
    assert WRAP.plan_all("day")["plan_id"] == swept["plan_id"], "an unchanged fleet previews alike"


def test_the_day_sweep_before_506_and_507_land(fleet4):
    """The recorder answers as `main` does before #506 and #507: the pr and page adapters are unknown."""
    os.makedirs(os.path.join(fleet4["path"], ".agent", "out"), exist_ok=True)
    open(os.path.join(fleet4["path"], ".agent", "out", "RDSD-1-confluence.md"), "w").close()
    repos = _repos(WRAP.plan_all("day"))
    luna = _slots(repos["luna"])
    assert luna["push"]["ok"] and luna["push"]["ticked"] and luna["comment"]["ticked"]
    for step in ("pr", "page"):
        assert luna[step]["code"] == "not_pinned" and "ad-pncli capture-help" in luna[step]["hint"], luna[step]
    sol = repos["sol"]
    assert [s["step"] for s in sol["steps"]] == ["push", "pr"] and _slots(sol)["push"]["ticked"]
    assert _slots(sol)["pr"]["code"] == "not_pinned"
    assert any("untracked" in n for n in sol["notes"]) and not sol["ticket"]
    terra = _slots(repos["terra"])
    for step in ("push", "pr"):
        assert not terra[step]["ok"] and "not on a branch" in terra[step]["hint"], terra[step]
    vega = repos["vega"]
    assert vega["state"] == "busy" and vega["steps"]
    assert all(s["code"] == "busy" and not s["ticked"] for s in vega["steps"])
    assert not any(s["step"] == "merge" for r in repos.values() for s in r["steps"])


def test_the_sweep_with_the_pr_and_page_shapes_506_and_507_will_print(fleet4):
    os.makedirs(os.path.join(fleet4["path"], ".agent", "out"), exist_ok=True)
    open(os.path.join(fleet4["path"], ".agent", "out", "RDSD-1-confluence.md"), "w").close()
    rec = fleet4["rec"]
    rec.canned.update(pr=PR_DRY, page=PAGE_DRY)
    luna = _slots(_repos(WRAP.plan_all("day"))["luna"])
    assert luna["push"]["ticked"] and luna["comment"]["ticked"]
    assert luna["pr"]["ok"] and luna["pr"]["ticked"] and luna["pr"]["payload"]["draft"] is True
    assert "draft" in luna["pr"]["summary"]
    project = _repos(WRAP.plan_all("project"))
    luna = _slots(project["luna"])
    assert luna["transition-review"]["ticked"] and not luna["transition-done"]["ticked"]
    rec.canned.pop("pr")
    luna = _slots(_repos(WRAP.plan_all("project"))["luna"])
    assert luna["pr"]["code"] == "not_pinned" and not luna["transition-review"]["ticked"]
    for mode in ("day", "project"):
        assert not any(s["step"] == "merge" or "merge" in s["summary"].lower()
                       for r in WRAP.plan_all(mode)["repos"] for s in r["steps"])


def test_run_all_writes_each_repos_ticked_steps_in_order_and_one_failure_leaves_the_others(fleet4):
    rec = fleet4["rec"]
    real_answer = rec._answer

    def luna_push_fails(args, cwd):
        if args[0] == "git" and "--dry-run" not in args and os.path.samefile(cwd, fleet4["path"]):
            return {"code": 1, "meta": {"ok": False, "refused": "push_failed", "error": "rejected",
                                        "hint": "fetch and look"}, "tables": {}, "stderr": ""}
        return real_answer(args, cwd)

    rec._answer = luna_push_fails
    swept = WRAP.plan_all("day")
    steps = {r["repo"]: [s["id"] for s in r["steps"] if s["ticked"]] for r in swept["repos"]}
    assert steps["luna"] and steps["sol"] and not steps["vega"]
    steps.pop("terra")                               # the operator unticked terra's comment and transition
    rec.calls.clear()
    done = WRAP.run_all("day", steps)
    by = {r["repo"]: {x["step"]: x["done"] for x in r["results"]} for r in done["repos"]}
    assert by["luna"] == {"push": "failed", "comment": "written", "transition": "written"}, by["luna"]
    assert by["sol"] == {"push": "written"}, "one repo's failure never stops another's"
    assert [(a[3], os.path.basename(c)) for a, c, _ in rec.calls if "--dry-run" not in a] == \
        [("git", "luna"), ("jira", "luna"), ("jira", "luna"), ("git", "sol")], "repo by repo, in #503's order"
    assert done["written"] == 3
    history = approval.history(limit=0)
    assert len(history) == 4 and all(h["by"] == "operator" and h["via"] == "wrapup" for h in history)
    assert WRAP.results("sol")[-1]["step"] == "push" and WRAP.results("sol")[-1]["ok"]


class Concurrent:
    """`RUN` that answers `ok` after a pause, counting how many repos are being read at once."""

    def __init__(self, pause=0.05):
        self.pause, self.lock = pause, threading.Lock()
        self.inflight: dict = {}
        self.most = 0

    def __call__(self, argv, cwd, env=None):
        with self.lock:
            self.inflight[cwd] = self.inflight.get(cwd, 0) + 1
            self.most = max(self.most, len([c for c, n in self.inflight.items() if n]))
        time.sleep(self.pause)
        with self.lock:
            self.inflight[cwd] -= 1
        return {"code": 0, "meta": {"ok": True, "ahead": 0}, "tables": {}, "stderr": ""}


def test_the_fleet_job_answers_at_once_and_never_reads_more_than_three_repos(fleet_home, tmp_path, monkeypatch):
    for n in ("a1", "a2", "a3", "a4", "a5", "a6"):
        Registry().add(make_project(tmp_path / n), name=n)
    run = Concurrent()
    monkeypatch.setattr(WRAP, "RUN", run)
    t0 = time.monotonic()
    ans = S.act("wrapup", {"all": True, "mode": "day", "dry_run": True})
    assert time.monotonic() - t0 < 0.2, "the desk waited on the sweep"
    assert ans["reading"] == ["a1", "a2", "a3", "a4", "a5", "a6"] and ans["job"]
    server, token = S.build(0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/api/wrapup?all=1&t={token}"
        deadline, got = time.time() + 20, {}
        while time.time() < deadline:
            t1 = time.monotonic()
            with urllib.request.urlopen(url, timeout=10) as r:
                got = json.loads(r.read())
            assert time.monotonic() - t1 < 0.2
            if got.get("state") == "planned":
                break
            time.sleep(0.05)
        assert got["state"] == "planned" and got["job"] == ans["job"] and got["all"] is True
        assert [r["repo"] for r in got["repos"]] == ["a1", "a2", "a3", "a4", "a5", "a6"]
        assert got["reading"] == [] and got["plan_id"] and "totals" in got
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
    assert 1 < run.most <= 3, f"{run.most} repos were read at once"


def test_the_stream_sends_a_wrapup_frame_when_the_fleet_job_moves(fleet_home):
    frames: list[str] = []
    stop = threading.Event()
    t = threading.Thread(target=S.stream_events, args=({}, stop, frames.append),
                         kwargs={"tick": 0.05, "polls": False, "sweep": False, "agents": False}, daemon=True)
    t.start()
    try:
        deadline = time.time() + 10
        while not any("event: tick" in f for f in frames) and time.time() < deadline:
            time.sleep(0.02)
        WRAP._write_fleet_job({"job": "fleet-abc", "all": True, "state": "reading", "reading": ["luna"]})
        while not any("event: wrapup" in f for f in frames) and time.time() < deadline:
            time.sleep(0.02)
        frame = json.loads(next(f for f in frames if "event: wrapup" in f).split("data: ", 1)[1])
        assert frame == {"all": True, "job": "fleet-abc", "state": "reading", "reading": ["luna"]}
    finally:
        stop.set()
        t.join(5)


def test_the_sweep_cli_and_api_answer_in_the_same_words_and_codes(fleet4, capsys):
    rc, out = _cli(capsys)
    assert rc == 2 and "name a repo, or pass --all" in out and "refused: no_repo" in out
    with pytest.raises(S.ServeError) as e:
        S.act("wrapup", {"mode": "day", "dry_run": True})
    assert e.value.code == "no_repo" and str(e.value) == "name a repo, or pass --all"

    rc, out = _cli(capsys, "--all", "--dry-run")
    assert rc == 0 and "dry_run: true" in out and "mode: day" in out and "repos[4]" in out, out
    plan_id = out.split("plan_id: ", 1)[1].split()[0]
    rc, out = _cli(capsys, "--all")
    assert rc == 2 and "refused: confirm_required" in out and f"--confirm {plan_id}" in out
    commit(fleet4["path"], "feat: later")
    rc, out = _cli(capsys, "--all", "--confirm", plan_id)
    assert rc == 2 and "refused: plan_changed" in out and fleet4["rec"].writes == []
    with pytest.raises(S.ServeError) as e:
        S.act("wrapup", {"all": True, "job": "fleet-00000000", "steps": {}})
    assert e.value.code == "plan_changed"

    rc, out = _cli(capsys, "luna", "sol", "--project", "--dry-run")
    assert rc == 0 and "mode: project" in out and "repos[2]" in out
    rc, out = _cli(capsys, "--all", "--dry-run")
    plan_id = out.split("plan_id: ", 1)[1].split()[0]
    rc, out = _cli(capsys, "--all", "--confirm", plan_id)
    assert rc == 0 and "written: 6" in out, out      # luna: push, comment, transition; sol: push; terra's Jira two
    assert [a[3] for a in fleet4["rec"].writes] == ["git", "jira", "jira", "git", "jira", "jira"]


def test_an_edited_sweep_comment_is_previewed_and_then_written_as_checked(luna):
    """#512: the desk's *edit* on a sweep's comment cell previews the sweep again with that text, so the
    confirm's id is the id of the text the operator read -- not `changed`."""
    plain = _slots(WRAP.plan_all("day")["repos"][0])["comment"]
    edited = WRAP.plan_all("day", comments={"luna": "my own words\n"})
    cell = _slots(edited["repos"][0])["comment"]
    assert cell["payload"]["body"] == "my own words\n" and cell["id"] != plain["id"]
    done = WRAP.run_all("day", {"luna": [cell["id"]]}, comments={"luna": "my own words\n"})
    assert [r["done"] for r in done["repos"][0]["results"]] == ["written"]
    assert luna["fake"].comments and "my own words" in json.dumps(luna["fake"].comments[-1])
