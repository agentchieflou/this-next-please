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
PREFIX = [sys.executable, "-m", "agentdata"]


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
        assert argv[:3] == PREFIX, argv
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
