"""Wrap up one agent: preview every write, then write exactly the ticked ones, in order (#503, epic #496).

The operator's words: *update jira tickets, bitbucket repos, and confluence pages both on an individual agent basis
and in a clean sweep (think end of project task vs end of day clean up)*. This is the individual half, and the
sweep (#505) runs it per agent.

**No model turn.** Everything here is read from the checkout and the fleet directory, and the Jira comment is a
template (WRAP-D2), shown in full and editable.

**Every write is an adapter, previewed.** `plan` runs each step's own `ad-*` adapter with `--dry-run` -- `git push`
(#502), `pncli bitbucket pr` (#506), `confluence publish` (#507), `jira comment` (#501) and `jira transition` --
as `[sys.executable, "-m", "agentdata", ...]`, never a raw `git` or `pncli`, so each adapter's own refusals always
run. The child's environment drops both fleet markers, so the adapter's `approval.require` is the outside-a-fleet
pass-through: the operator's confirm is the approval (WRAP-D4), and `run` records it, `by: operator`,
`via: wrapup`, one record per written step.

**`run` never trusts an earlier plan.** It plans again, and a step runs only when its id was asked for, its fresh
dry-run is `ok` and its fresh id equals the one asked for. An id hashes the repo, the step and the payload's
stable fields, so a new commit, a new comment text or a moved page changes it and the step answers `changed`.
Nothing is retried and nothing is queued: a busy agent gets every row `skipped`.

The fleet never writes the checkout. Results go to `agent_dir(name)/wrapup.jsonl`; the comment text to
`agent_dir(name)/wrapup/comment.md`; the desk's job state to `agent_dir(name)/wrapup/job.json`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time

from .. import config as C
from .. import proc, textio
from .registry import AGENT_ENV, FLEET_DIR_ENV, Registry, agent_dir

MODES = ("day", "project")
LABEL = {"day": "End of day", "project": "End of project"}
ORDER = ("push", "pr", "page", "comment", "transition")
DEFAULT_TIMEOUT_S = 180
READ_TIMEOUT_S = 30
SUBJECTS = 10
ARTIFACTS = 5
RESULTS = "wrapup.jsonl"
JOB = "job.json"
COMMENT = "comment.md"
TERMINAL = ("pr_open", "done", "closed", "merged")
NOT_ON_A_BRANCH = ("default_branch", "detached_head")
KIND = {"push": "git-push", "pr": "bitbucket-pr", "page": "confluence-publish", "comment": "jira-comment",
        "transition": "jira-transition"}
NOT_PINNED_HINT = {
    "pr": "the PR verb is not pinned yet (HANDOFF.md:16) — run `ad-pncli capture-help` on the laptop (WRAP-D6)",
    "page": "the page verbs are not pinned yet (HANDOFF.md:16) — run `ad-pncli capture-help` on the laptop (WRAP-D6)",
}
# The payload fields that say *what* a step would write. Ages, timestamps and counters are left out, so two
# previews of an unchanged checkout hash alike and the confirm can prove it is writing what was previewed.
STABLE = {
    "push": ("branch", "remote", "target", "head", "ahead"),
    "pr": ("action", "pr_id", "title", "draft", "source", "target", "description", "live_hash"),
    "page": ("action", "page_id", "title", "space", "parent", "version", "edited"),
    "comment": ("key", "chars", "body_sha"),
    "transition": ("key", "transition", "to", "status"),
}


class WrapupError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg, self.hint, self.code = msg, hint, code


# ------------------------------------------------------------------------------------------ the seam


def child_env() -> dict:
    """What every adapter child runs with, laid over this process's environment by `proc.run`.

    Both fleet markers removed: the child's `approval.require` then passes through, because the operator's confirm
    is the approval. Git never prompts, so a credential helper cannot hang a desk thread."""
    return {AGENT_ENV: None, FLEET_DIR_ENV: None, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def _timeout() -> int:
    try:
        return max(1, int(C.get(C.load(), "fleet.wrapup_timeout_s") or DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError, C.ConfigError, OSError):
        return DEFAULT_TIMEOUT_S


def _run(argv: list[str], cwd: str, env: dict | None = None) -> dict:
    """Run one adapter: `{code, meta, tables, stderr}`. A start failure or a timeout is a failed step, not a raise."""
    try:
        code, out, err, _ = proc.run(argv, cwd=cwd, timeout=_timeout(), env=env)
    except proc.ProcError as e:
        return {"code": 1, "meta": {"ok": False, "error": e.msg, "hint": e.hint, "refused": e.code},
                "tables": {}, "stderr": ""}
    blocks = read_toon(out)
    return {"code": code, "meta": blocks.pop("meta", {}) or {}, "tables": blocks, "stderr": err}


RUN = _run                                     # tests replace this: RUN(argv, cwd, env=...) -> dict


def adapter(*args: str) -> list[str]:
    return [sys.executable, "-m", "agentdata", *args]


# ------------------------------------------------------------------------------------------ TOON back in


def _cell(raw: str):
    s = raw.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1].replace('""', '"')
    if s in ("true", "false"):
        return s == "true"
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s if s else None


def _cells(line: str) -> list[str]:
    cells, cell, quoted, i = [], [], False, 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            if quoted and i + 1 < len(line) and line[i + 1] == '"':
                cell.append('""')
                i += 2
                continue
            quoted = not quoted
            cell.append(ch)
        elif ch == "," and not quoted:
            cells.append("".join(cell))
            cell = []
        else:
            cell.append(ch)
        i += 1
    cells.append("".join(cell))
    return cells


_HEAD = re.compile(r'^(?P<name>"(?:[^"]|"")*"|[^\s:\[\]{}]+)(?:\[(?P<n>\d+)\](?:\{(?P<cols>[^}]*)\})?)?:(?P<rest>.*)$')


def read_toon(text: str) -> dict:
    """The two shapes an adapter prints, read back: top-level blocks of `key: value` (lists as `key[n]: a,b`) and
    tables `name[n]{cols}:` with one row per line. Enough for `meta` and `available`; nothing more is needed."""
    lines, out, i = (text or "").splitlines(), {}, 0
    # A value quoted across lines is one value: join until the quotes balance.
    joined: list[str] = []
    for line in lines:
        if joined and joined[-1].count('"') % 2 == 1:
            joined[-1] += "\n" + line
        else:
            joined.append(line)
    block, table, cols = None, None, []
    for line in joined:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if indent == 0:
            m = _HEAD.match(body)
            if not m:
                continue
            name = _cell(m.group("name"))
            if m.group("cols") is not None:
                table, cols, block = name, [str(_cell(c)) for c in _cells(m.group("cols"))], None
                out[table] = []
            else:
                block, table = name, None
                out[block] = {}
            continue
        if table is not None:
            out[table].append(dict(zip(cols, (_cell(c) for c in _cells(body)))))
            continue
        if block is None:
            continue
        m = _HEAD.match(body)
        if not m:
            continue
        key, rest = str(_cell(m.group("name"))), m.group("rest")
        if m.group("n") is not None:
            out[block][key] = [_cell(c) for c in _cells(rest.strip())] if rest.strip() else []
        else:
            out[block][key] = _cell(rest)
    return out


# ------------------------------------------------------------------------------------------ the checkout


def _git(path: str, *args: str) -> str:
    try:
        code, out, _, _ = proc.run(["git", "--no-optional-locks", *args], cwd=path, timeout=READ_TIMEOUT_S,
                                   env={"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"})
    except proc.ProcError:
        return ""
    return out.strip() if code == 0 else ""


def _results_path(name: str) -> str:
    return os.path.join(agent_dir(name), RESULTS)


def _dir(name: str) -> str:
    return os.path.join(agent_dir(name), "wrapup")


def comment_path(name: str) -> str:
    return os.path.join(_dir(name), COMMENT)


def results(name: str) -> list[dict]:
    try:
        with open(_results_path(name), encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except (OSError, ValueError):
        return []


def recorded_urls(name: str) -> dict:
    """The newest URL each written step reported: what the rail opens when `state.json` has none (Build 6)."""
    out: dict = {}
    for rec in results(name):
        if rec.get("ok") and rec.get("url") and rec.get("step") in ("pr", "page"):
            out["pr_url" if rec["step"] == "pr" else "confluence_url"] = rec["url"]
    return out


def state_with_recorded(name: str, state: dict) -> dict:
    """`state` with `pr_url` / `confluence_url` filled from the last wrap-up where the agent has not written one."""
    urls = recorded_urls(name)
    filled = dict(state or {})
    for key, url in urls.items():
        if not str(filled.get(key) or "").strip():
            filled[key] = url
    return filled


def _last_comment(name: str) -> dict:
    return next((r for r in reversed(results(name)) if r.get("step") == "comment" and r.get("ok")), {})


def _since(path: str, last: dict) -> tuple[str, str]:
    """(ref, words): the last wrap-up's head when it is still an ancestor, else the branch point."""
    head = str(last.get("head") or "")
    if head:
        try:
            code, _, _, _ = proc.run(["git", "merge-base", "--is-ancestor", head, "HEAD"], cwd=path,
                                     timeout=READ_TIMEOUT_S, env={"GIT_TERMINAL_PROMPT": "0"})
        except proc.ProcError:
            code = 1
        if code == 0:                                     # the exit code is the answer; it prints nothing
            return head, "the last wrap-up"
    remote_head = _git(path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    for ref in ([remote_head] if remote_head else []) + ["origin/main", "origin/master", "main", "master"]:
        if _git(path, "rev-parse", "--verify", "--quiet", ref):
            return ref, "the branch point"
    return "", "the first commit"


def checkout_facts(repo, st: dict, last: dict) -> dict:
    path = repo.path
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD") or "?"
    head = _git(path, "rev-parse", "HEAD")
    ref, since_words = _since(path, last)
    span = ["HEAD", "--not", ref] if ref and branch != ref.rsplit("/", 1)[-1] else ["HEAD"]
    count = int(_git(path, "rev-list", "--count", "--max-count=1000", *span) or 0) if head else 0
    subjects = _git(path, "log", f"--max-count={SUBJECTS}", "--format=%s", *span).splitlines() if count else []
    out_dir = os.path.join(path, ".agent", "out")
    after = _stamp(last.get("ts"))
    artifacts = []
    try:
        for entry in sorted(os.scandir(out_dir), key=lambda e: -e.stat().st_mtime):
            if entry.is_file() and entry.stat().st_mtime > after:
                artifacts.append(f".agent/out/{entry.name}")
    except OSError:
        pass
    questions = [q for q in (st.get("open_questions") or []) if not _answered(q)]
    return {"branch": branch, "head": head, "count": count, "subjects": subjects, "since": since_words,
            "artifacts": artifacts[:ARTIFACTS], "questions": questions}


def _answered(q) -> bool:
    from .. import state as STATE

    try:
        return STATE.is_answered(q)
    except Exception:  # noqa: BLE001 - an odd question shape is still an open question
        return False


def _stamp(ts) -> float:
    try:
        return time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return 0.0


def comment_text(repo, mode: str, st: dict, seen: dict, *, pr_url: str = "", page_url: str = "") -> str:
    """The Jira comment, from the checkout alone (WRAP-D2). One line per clause, so it reads on both flavors."""
    from .. import state as STATE

    q = seen["questions"]
    first = STATE.question_text(q[0]) if q else ""
    subjects = "; ".join(seen["subjects"]) if seen["subjects"] else "none"
    lines = [
        f"{LABEL[mode]}, {time.strftime('%Y-%m-%d')} — {repo.name} on {seen['branch']}",
        f"phase: {st.get('phase') or 'unknown'}",
        f"{seen['count']} commit{'s' if seen['count'] != 1 else ''} since {seen['since']}: {subjects}",
        f"PR: {pr_url or 'none'}",
        f"page: {page_url or 'none'}",
        f"{len(q)} open question{'s' if len(q) != 1 else ''}" + (f": {first}" if first else ""),
        "artifacts: " + (", ".join(seen["artifacts"]) or "none"),
    ]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------ the rows


def _sha(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _row(repo: str, step: str, *, ok: bool, ticked: bool, summary: str, payload: dict | None = None,
         hint: str = "", code: str = "", key: str = "", **extra) -> dict:
    payload = dict(payload or {})
    stable = {k: payload.get(k) for k in STABLE.get(step, ())}
    ident = f"{key or step}:{_sha([repo, key or step, stable, ok, code])[:12]}"
    return {"id": ident, "step": step, "ok": bool(ok), "ticked": bool(ticked and ok), "summary": summary,
            "payload": payload, "hint": hint, "needs": [], "code": code, **extra}


def _failed(res: dict) -> tuple[bool, str, str, str]:
    """(ok, code, error, hint) of one adapter answer."""
    meta = res.get("meta") or {}
    ok = res.get("code") == 0 and meta.get("ok") is True
    code = str(meta.get("refused") or meta.get("code") or ("" if ok else "failed"))
    return ok, code, str(meta.get("error") or ""), str(meta.get("hint") or "")


def _not_pinned(res: dict) -> bool:
    meta = res.get("meta") or {}
    return (meta.get("code") == "not_pinned" or meta.get("refused") == "not_pinned"
            or "invalid choice" in str(res.get("stderr") or ""))


def _busy(name: str) -> str:
    from . import supervisor

    lock = supervisor.live(name)
    if not lock:
        return ""
    if lock.get("kind") == "console":
        return "a console is yours"
    if lock.get("external"):
        return "your own chat"
    return "press wrap up when this turn ends"


def _skeleton(name: str, ticket: str, why: str) -> list[dict]:
    steps = ["push", "pr"] + (["comment", "transition"] if ticket else [])
    return [_row(name, s, ok=False, ticked=False, summary=f"{s}: skipped", code="busy", hint=why) for s in steps]


def plan(name: str, mode: str = "day", *, comment: str | None = None, to: str | None = None,
         overwrite: dict | None = None, registry: Registry | None = None) -> dict:
    """Every write this agent's wrap-up would make, each previewed with its adapter's `--dry-run`. Writes to no
    system; the only file it writes is the comment text under the fleet directory."""
    if mode not in MODES:
        raise WrapupError(f"{mode!r} is not a preset", "day | project", code="bad_mode")
    repo = (registry or Registry()).get(name)
    st = repo.state()
    ticket = str(st.get("active_ticket") or "").strip()
    phase = str(st.get("phase") or "")
    overwrite = dict(overwrite or {})
    notes: list[str] = []
    busy = _busy(name)
    if busy:
        rows = _skeleton(name, ticket, busy)
        return _finish(name, mode, rows, notes + [f"busy: {busy}; nothing is queued"], ticket=ticket)

    env = child_env()
    cwd = repo.path
    last = _last_comment(name)
    seen = checkout_facts(repo, st, last)
    rows: list[dict] = []

    # push
    res = RUN(adapter("git", "push", "--dry-run"), cwd, env=env)
    ok, code, err, hint = _failed(res)
    meta = res.get("meta") or {}
    on_branch = code not in NOT_ON_A_BRANCH
    ahead = int(meta.get("ahead") or 0) if ok else 0
    payload = {k: meta.get(k) for k in ("branch", "remote", "target", "upstream", "ahead", "behind", "subjects",
                                        "protected", "note")}
    payload["head"] = seen["head"]
    if not on_branch:
        rows.append(_row(name, "push", ok=False, ticked=False, summary="push: the work is not on a branch",
                         payload=payload, code=code, hint=f"{err} — the work is not on a branch (AGENTS.md rule 16)"))
    elif ok:
        rows.append(_row(name, "push", ok=True, ticked=ahead > 0, payload=payload,
                         summary=(f"push {ahead} commit{'s' if ahead != 1 else ''} to "
                                  f"{meta.get('remote')}/{meta.get('branch')}" if ahead else "push: nothing to push"),
                         hint=str(meta.get("note") or "")))
    else:
        rows.append(_row(name, "push", ok=False, ticked=False, summary=f"push: {code}", payload=payload,
                         code=code, hint=hint or err))

    # pr
    has_pr = bool(str(st.get("pr_url") or "").strip())
    if not on_branch:
        rows.append(_row(name, "pr", ok=False, ticked=False, summary="pr: the work is not on a branch",
                         code=code, hint="the work is not on a branch (AGENTS.md rule 16)"))
    else:
        title = f"{ticket}: {st.get('summary') or seen['branch']}" if ticket else str(st.get("summary") or seen["branch"])
        argv = ["pncli", "bitbucket", "pr", "--title", title, "--draft" if mode == "day" else "--ready"]
        if overwrite.get("pr"):
            argv += ["--overwrite", str(overwrite["pr"])]
        res = RUN(adapter(*argv, "--dry-run"), cwd, env=env)
        ok, pcode, err, hint = _failed(res)
        meta = res.get("meta") or {}
        if not ok and _not_pinned(res):
            rows.append(_row(name, "pr", ok=False, ticked=False, summary="pr: not pinned", code="not_pinned",
                             hint=NOT_PINNED_HINT["pr"]))
        elif ok:
            action = str(meta.get("action") or "")
            has_pr = has_pr or action == "update"
            wanted = (ahead > 0 or action == "update") if mode == "day" else True
            kept = meta.get("description") == "kept"
            rows.append(_row(name, "pr", ok=True, ticked=wanted, payload=dict(meta),
                             summary=f"pr: {action or 'create'} {'draft ' if mode == 'day' else ''}— {meta.get('title') or title}",
                             hint=("the description was edited since this tool wrote it: kept; replace it with a "
                                   "second preview (--overwrite-pr)" if kept else "")))
        else:
            rows.append(_row(name, "pr", ok=False, ticked=False, summary=f"pr: {pcode}", payload=dict(meta),
                             code=pcode, hint=hint or err, live=meta.get("live_hash")))

    # page
    source = os.path.join(cwd, ".agent", "out", f"{ticket}-confluence.md") if ticket else ""
    if ticket and not os.path.isfile(source):
        rows.append(_row(name, "page", ok=False, ticked=False, summary="page: skipped", code="no_source",
                         hint=f"no page source — confluence-publish writes `.agent/out/{ticket}-confluence.md`"))
    elif ticket:
        argv = ["confluence", "publish", f".agent/out/{ticket}-confluence.md"]
        if overwrite.get("page"):
            argv += ["--overwrite", str(overwrite["page"])]
        res = RUN(adapter(*argv, "--dry-run"), cwd, env=env)
        ok, gcode, err, hint = _failed(res)
        meta = res.get("meta") or {}
        if not ok and _not_pinned(res):
            rows.append(_row(name, "page", ok=False, ticked=False, summary="page: not pinned", code="not_pinned",
                             hint=NOT_PINNED_HINT["page"]))
        elif ok and mode == "day" and meta.get("action") == "create":
            rows.append(_row(name, "page", ok=False, ticked=False, summary="page: end of day never creates a page",
                             payload=dict(meta), code="day_never_creates",
                             hint="end of project creates it; end of day only updates a page this tool published"))
        elif ok:
            rows.append(_row(name, "page", ok=True, ticked=True, payload=dict(meta),
                             summary=f"page: {meta.get('action') or 'update'} — {meta.get('title') or ticket}"))
        else:
            rows.append(_row(name, "page", ok=False, ticked=False, summary=f"page: {gcode}", payload=dict(meta),
                             code=gcode, hint=hint or err, live=meta.get("version")))

    if not ticket:
        notes.append("untracked work: no ticket, so no Jira rows (AGENTS.md rule 17)")
        return _finish(name, mode, rows, notes, ticket=ticket)

    # comment
    terminal = phase in TERMINAL
    nothing_new = bool(last) and last.get("head") == seen["head"] and last.get("phase") == phase \
        and not seen["artifacts"]
    if mode == "day" and terminal:
        notes.append(f"no progress comment: the phase is {phase}")
    elif mode == "day" and nothing_new:
        notes.append("no progress comment: nothing new since the last wrap-up")
    else:
        text = comment if comment is not None else comment_text(repo, mode, st, seen,
                                                                pr_url=str(st.get("pr_url") or ""),
                                                                page_url=str(st.get("confluence_url") or ""))
        path = comment_path(name)
        textio.write_text(path, text)
        res = RUN(adapter("jira", "comment", ticket, "--body-file", path, "--dry-run"), cwd, env=env)
        ok, ccode, err, hint = _failed(res)
        meta = res.get("meta") or {}
        payload = {"key": ticket, "chars": meta.get("chars"), "first_line": meta.get("first_line"),
                   "body_sha": _sha(text)[:16], "body": text}
        rows.append(_row(name, "comment", ok=ok, ticked=True, payload=payload, code="" if ok else ccode,
                         summary=f"comment on {ticket}: {meta.get('first_line') or text.splitlines()[0]}",
                         hint="" if ok else (hint or err)))

    # transition
    targets: list[tuple[str, bool, str]] = []            # (intent or name, ticked, hint)
    pr_row = next((r for r in rows if r["step"] == "pr"), {})
    if to:
        targets.append((to, True, ""))
    elif mode == "day":
        if seen["count"] and not terminal:
            targets.append(("in-progress", True, ""))
    else:
        review = has_pr or bool(pr_row.get("ok") and pr_row.get("ticked"))
        targets.append(("review", review, "" if review else
                        "no PR yet — review usually follows one; tick to move it anyway"))
        targets.append(("done", False, "the operator's call: tick it to close the ticket (AGENTS.md rule 8)"))
    for want, ticked, why in targets:
        res = RUN(adapter("jira", "transition", ticket, "--to", want, "--dry-run"), cwd, env=env)
        ok, tcode, err, hint = _failed(res)
        meta = res.get("meta") or {}
        if ok and meta.get("already"):
            if mode == "day" and not to:
                continue                                  # already in progress: nothing to offer
            rows.append(_row(name, "transition", key=f"transition-{want}", ok=True, ticked=False,
                             payload={"key": ticket, "to": want, "status": meta.get("status")},
                             summary=f"{ticket}: already {meta.get('status')}", hint="nothing to move"))
            continue
        if ok and mode == "day" and not to:
            from .. import jira_workflow as W

            if not W.already_there(str(meta.get("status") or ""), "todo"):
                continue                                  # only *to do → in progress* at end of day
        available = [str(r.get("name") or r.get("to_status") or "") for r in (res.get("tables") or {}).get("available") or []]
        payload = {"key": ticket, "transition": meta.get("transition"), "to": meta.get("to"),
                   "status": meta.get("status"), "requires": meta.get("requires")}
        rows.append(_row(name, "transition", key=f"transition-{want}", ok=ok, ticked=ticked, payload=payload,
                         code="" if ok else tcode,
                         summary=(f"{ticket}: {meta.get('status')} → {meta.get('to')}" if ok
                                  else f"{ticket}: no {want} transition"),
                         hint=why if ok else (hint or err), available=[a for a in available if a]))
    return _finish(name, mode, rows, notes, ticket=ticket)


def _finish(name: str, mode: str, rows: list[dict], notes: list[str], *, ticket: str) -> dict:
    ticked = {r["step"] for r in rows if r["ticked"]}
    for r in rows:
        if not r["ticked"]:
            continue
        if r["step"] == "pr" and "push" in ticked:
            r["needs"] = ["push"]
        if r["step"] in ("comment", "transition"):
            r["needs"] = [s for s in ("pr", "page") if s in ticked]
    return {"repo": name, "mode": mode, "ticket": ticket, "plan_id": _sha([r["id"] for r in rows])[:12],
            "rows": rows, "writes": sum(r["ticked"] for r in rows), "notes": notes}


# ------------------------------------------------------------------------------------------ the run


def _real_argv(row: dict, name: str, mode: str, st: dict, overwrite: dict) -> list[str]:
    p, ticket = row["payload"], str(st.get("active_ticket") or "")
    if row["step"] == "push":
        return adapter("git", "push")
    if row["step"] == "pr":
        title = str(p.get("title") or "")
        argv = ["pncli", "bitbucket", "pr", "--title", title, "--draft" if mode == "day" else "--ready"]
        if overwrite.get("pr"):
            argv += ["--overwrite", str(overwrite["pr"])]
        return adapter(*argv)
    if row["step"] == "page":
        argv = ["confluence", "publish", f".agent/out/{ticket}-confluence.md"]
        if overwrite.get("page"):
            argv += ["--overwrite", str(overwrite["page"])]
        return adapter(*argv)
    if row["step"] == "comment":
        return adapter("jira", "comment", ticket, "--body-file", comment_path(name))
    want = row["id"].split(":", 1)[0].split("-", 1)[1]
    return adapter("jira", "transition", ticket, "--to", want)


def run(name: str, mode: str, steps: list[str], *, comment: str | None = None, to: str | None = None,
        overwrite: dict | None = None, registry: Registry | None = None) -> dict:
    """Plan again, then write exactly the asked steps whose fresh preview is `ok` and unchanged, in order."""
    from . import approval

    reg = registry or Registry()
    fresh = plan(name, mode, comment=comment, to=to, overwrite=overwrite, registry=reg)
    repo = reg.get(name)
    st = repo.state()
    asked = list(steps or [])
    by_slot = {r["id"].split(":", 1)[0]: r for r in fresh["rows"]}
    asked_slots = {a.split(":", 1)[0]: a for a in asked}
    out, failed = [], {}                                   # step -> the step whose failure it inherits
    facts_head = next((r["payload"].get("head") for r in fresh["rows"] if r["step"] == "push"), "")
    for slot, row in by_slot.items():
        if slot not in asked_slots:
            continue
        step = row["step"]
        needs = [s for s in (["push"] if step == "pr" else ["pr", "page"] if step in ("comment", "transition") else [])
                 if s in {k.split("-", 1)[0] for k in asked_slots}]
        blocked = next((failed[s] for s in needs if s in failed), "")
        res = {"id": row["id"], "step": step, "summary": row["summary"]}
        if row["code"] == "busy":
            out.append({**res, "done": "skipped", "ok": False, "code": "busy", "hint": row["hint"]})
            failed[step] = step
            continue
        if blocked:
            out.append({**res, "done": f"skipped: {blocked} failed", "ok": False})
            failed[step] = blocked
            continue
        if asked_slots[slot] != row["id"]:
            out.append({**res, "done": "changed", "ok": False,
                        "hint": "the preview changed since you looked: preview again and confirm the new one"})
            failed[step] = step
            continue
        if not row["ok"]:
            out.append({**res, "done": f"skipped: {step} failed", "ok": False, "code": row["code"],
                        "hint": row["hint"]})
            failed[step] = step
            continue
        approval.record(KIND[step], row["summary"], row["payload"], repo=name,
                        ticket=str(st.get("active_ticket") or ""), by="operator", via="wrapup")
        got = RUN(_real_argv(row, name, mode, st, dict(overwrite or {})), repo.path, env=child_env())
        ok, code, err, hint = _failed(got)
        meta = got.get("meta") or {}
        url = str(meta.get("url") or "")
        line = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": mode, "step": step, "id": row["id"], "ok": ok,
                "url": url, "error": "" if ok else (err or code), "hint": "" if ok else hint}
        if step == "comment":
            line.update({"head": facts_head, "phase": st.get("phase") or ""})
        _append(name, line)
        out.append({**res, "done": "written" if ok else "failed", "ok": ok, "url": url,
                    "error": line["error"], "hint": line["hint"]})
        if not ok:
            failed[step] = step
    for slot, want in asked_slots.items():
        if slot not in by_slot:
            out.append({"id": want, "step": slot.split("-", 1)[0], "summary": "", "done": "changed", "ok": False,
                        "hint": "this step is no longer offered: preview again"})
    return {**fresh, "results": out, "written": sum(r["done"] == "written" for r in out)}


def _append(name: str, line: dict) -> None:
    path = _results_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------------------------ the desk's job


_JOB_LOCK = threading.Lock()
_THREADS: dict[str, threading.Thread] = {}


def job_path(name: str) -> str:
    return os.path.join(_dir(name), JOB)


def job_state(name: str) -> dict:
    try:
        return textio.read_json(job_path(name), JOB)
    except (OSError, ValueError):
        return {}


def _write_job(name: str, data: dict) -> None:
    textio.write_json(job_path(name), {**data, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})


def start_plan(name: str, mode: str, *, comment=None, to=None, overwrite=None) -> dict:
    """Plan on a thread and answer at once. A second ask while one reads joins it."""
    Registry().get(name)                                    # an unknown repo is refused here, not on the thread
    if mode not in MODES:
        raise WrapupError(f"{mode!r} is not a preset", "day | project", code="bad_mode")
    with _JOB_LOCK:
        running = _THREADS.get(name)
        now = job_state(name)
        if running and running.is_alive() and now.get("state") == "reading":
            return {"job": now.get("job"), "repo": name, "reading": True, "joined": True}
        job = f"{name}-{secrets.token_hex(4)}"
        opts = {"comment": comment, "to": to, "overwrite": overwrite}
        _write_job(name, {"job": job, "repo": name, "mode": mode, "state": "reading", "opts": opts})

        def work():
            try:
                planned = plan(name, mode, comment=comment, to=to, overwrite=overwrite)
                _write_job(name, {"job": job, "repo": name, "mode": mode, "state": "planned", "opts": opts,
                                  "plan": planned})
            except Exception as e:  # noqa: BLE001 - the page must hear why, not wait forever
                _write_job(name, {"job": job, "repo": name, "mode": mode, "state": "done", "opts": opts,
                                  "error": str(getattr(e, "msg", e))[:300], "hint": getattr(e, "hint", "")})

        t = threading.Thread(target=work, name=f"wrapup-{name}", daemon=True)
        _THREADS[name] = t
        t.start()
    return {"job": job, "repo": name, "reading": True}


def start_run(job: str, steps: list[str], *, comment=None, to=None, overwrite=None) -> dict:
    """Write the ticked steps of this repo's latest plan, on a thread. Any other job is `plan_changed`."""
    name = job.rsplit("-", 1)[0]
    with _JOB_LOCK:
        now = job_state(name) if name else {}
        if not now or now.get("job") != job or now.get("state") != "planned":
            raise WrapupError("that preview is not this agent's latest", "preview again, then confirm what it shows",
                              code="plan_changed")
        mode, opts = now.get("mode") or "day", dict(now.get("opts") or {})
        comment = comment if comment is not None else opts.get("comment")
        to = to if to is not None else opts.get("to")
        overwrite = overwrite if overwrite is not None else opts.get("overwrite")
        _write_job(name, {**now, "state": "writing"})

        def work():
            try:
                done = run(name, mode, list(steps or []), comment=comment, to=to, overwrite=overwrite)
                _write_job(name, {"job": job, "repo": name, "mode": mode, "state": "done", "results": done["results"],
                                  "plan": {k: v for k, v in done.items() if k != "results"}})
            except Exception as e:  # noqa: BLE001
                _write_job(name, {"job": job, "repo": name, "mode": mode, "state": "done",
                                  "error": str(getattr(e, "msg", e))[:300], "hint": getattr(e, "hint", "")})

        t = threading.Thread(target=work, name=f"wrapup-{name}", daemon=True)
        _THREADS[name] = t
        t.start()
    return {"job": job, "repo": name, "writing": True}


def wait(name: str, timeout: float = 30.0) -> bool:
    """True once this repo's job thread has finished (tests, and a CLI that shares the process)."""
    t = _THREADS.get(name)
    if t is None:
        return True
    t.join(timeout)
    return not t.is_alive()
