"""The fleet's worklog: one page per checkout per day, folded from the event stream and laid out like the fleet map.

`docs/plan-onenote-worklog.md` is the design and `docs/fleet-worklog.md` the contract. The operator's words
(2026-10-09): *fleet agents write worklogs to OneNote in structured locations that resemble the fleet's
Monorepository nature.* The structure is the fleet map's (`docs/fleet-map.md`) with time added at the leaves:

    <project> / <repo> / <yyyy-mm> / <yyyy-mm-dd>

and that one string is both the OneNote address (project section group, checkout section group, month section,
day page) and the local mirror's path under `<fleet dir>/worklog/`. `layout` is the only place the shape lives.

**No model turn and no new authority.** A page is a view of `events.norm.jsonl` for one repo between two `seq`
values (`docs/fleet-events.md`): facts only -- phases, artifacts, PRs, questions, approvals, denials, friction, cost
-- never `assistant_text`, tool calls or tool results (W-D3). The one piece of prose is the wrap-up comment the
operator already read and approved, quoted as written.

This module is W-1 of the plan: the fold, the two emitters (one model, Markdown and OneNote HTML), the names and
the local mirror. It writes nothing anywhere but under the fleet directory, and nothing to OneNote: the writers are
W-3 (Graph) and W-4 (the connector), and until one lands the wrap-up's `onenote` row says so (`wrapup.py`).
"""
from __future__ import annotations

import hashlib
import json
import os
import re

from .. import config as C
from .. import textio
from ..confluence import esc
from . import agentstate, events as E, spend as SPEND
from .registry import Registry, agent_dir, fleet_dir

#: The setting that names the notebook (its OneNote web URL). Blank keeps the worklog local only.
NOTEBOOK_KEY = "fleet.onenote.notebook"
FOLDER = "worklog"
CURSOR = "worklog.cursor.json"
#: Graph refuses these in a section or section group name, and caps a name at 50 characters.
FORBIDDEN = set("?*/\\:<>|&#'%~")
MAX_NAME = 50
ROOT_ID = "wl-root"
#: OneNote's note tags (`data-tag`); custom tags are not supported, so these are the only ones used.
TAG_OPEN, TAG_DONE, TAG_IMPORTANT, TAG_QUESTION = "to-do", "to-do:completed", "important", "question"
#: The states whose line on the page carries a tag.
STATE_TAGS = {"blocked": TAG_IMPORTANT, "error": TAG_IMPORTANT, "needs_human": TAG_QUESTION,
              "waiting_approval": TAG_QUESTION}
#: Kinds the fold reads. Everything else in the stream is the model's working and stays there.
KINDS = ("phase_changed", "artifact", "pr_open", "question_opened", "question_answered", "question_cleared",
         "needs_approval", "approval_resolved", "denied", "friction", "cost", "turn_ended", "assistant_text",
         "started", "session_id", "exited", "error")


class WorklogError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg, self.hint, self.code = msg, hint, code


# ------------------------------------------------------------------------------------------ names and layout


def onenote_name(name: str) -> str:
    """A section or section-group name Graph accepts, from any string, the same way every time.

    Each forbidden character becomes `-`; a name over 50 characters is cut to 43, a dash and six hex digits of
    the full name's digest, so the next day finds the same group and two long names never collide."""
    cleaned = "".join("-" if ch in FORBIDDEN else ch for ch in str(name or "")).strip() or "-"
    if len(cleaned) <= MAX_NAME:
        return cleaned
    digest = hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:6]
    return cleaned[:MAX_NAME - 7].rstrip() + "-" + digest


def layout(project: str, repo: str, day: str, *, nested: bool = True) -> dict:
    """Where a day page lives, in both spellings.

    `path` is the one string shared with the local mirror: `<project>/<repo>/<yyyy-mm>/<yyyy-mm-dd>`. `groups` is
    the section-group chain (the direct Graph writer can nest; the connector cannot, so `nested=False` flattens to
    one section `<project> · <yyyy-mm>` at the notebook's top level and the names still read as the tree)."""
    _day(day)
    month = day[:7]
    out = {"path": f"{project}/{repo}/{month}/{day}", "project": project, "repo": repo, "day": day,
           "month": month, "title": f"{day} · {repo}", "journal_title": f"{day} · {project}", "nested": nested}
    if nested:
        out["groups"] = [onenote_name(project), onenote_name(repo)]
        out["section"] = month
        out["journal_section"] = f"Journal {month}"
    else:
        out["groups"] = []
        out["section"] = onenote_name(f"{project} · {month}")
        out["journal_section"] = out["section"]
    return out


def _day(day: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day or "")):
        raise WorklogError(f"{day!r} is not a day", "YYYY-MM-DD", code="bad_day")
    return day


def local_dir() -> str:
    return textio.norm_path(os.path.join(fleet_dir(), FOLDER))


def local_path(project: str, repo: str, day: str) -> str:
    """`<fleet dir>/worklog/<project>/<repo>/<yyyy-mm>/<yyyy-mm-dd>.md`: the mirror the notebook copies."""
    _day(day)
    return textio.norm_path(os.path.join(local_dir(), textio.safe_name(project), textio.safe_name(repo),
                                         day[:7], f"{day}.md"))


# ------------------------------------------------------------------------------------------ the fold


def _hhmm(ts: str) -> str:
    return str(ts or "")[11:16]


def _ticket(model: dict, key: str) -> dict:
    return model["tickets"].setdefault(key or "(no ticket)", {
        "key": key or "(no ticket)", "phases": [], "artifacts": [], "prs": [], "questions": {}, "approvals": [],
        "friction": [], "denied": 0})


def fold(events: list[dict], *, repo: str, project: str, day: str, since: int = 0) -> dict:
    """The day model: what happened to `repo` on `day`, after `seq` `since`, from the normalized stream.

    Pure: no I/O, no clock. The day is the stream's own date (`ts[:10]`, UTC like every `ts`); W-D2 asks whether
    the operator's local day should replace it and is open. Events of other days and at or before `since` are
    ignored, which is what makes a second wrap-up on the same day an append rather than a repeat."""
    _day(day)
    picked = [ev for ev in events if str(ev.get("ts") or "")[:10] == day and int(ev.get("seq") or 0) > since]
    model: dict = {"repo": repo, "project": project, "day": day, "since": since,
                   "seq_from": min((int(e["seq"]) for e in picked), default=0),
                   "seq_to": max((int(e["seq"]) for e in picked), default=0),
                   "events": len(picked), "model": "", "tickets": {}, "state": "", "role": ""}
    for ev in picked:
        kind, data, t = ev.get("kind"), ev.get("data") or {}, _ticket(model, str(ev.get("ticket") or ""))
        at = _hhmm(ev.get("ts"))
        if kind == "phase_changed":
            t["phases"].append({"at": at, "from": str(data.get("from") or ""), "to": str(data.get("to") or "")})
        elif kind == "artifact":
            art = data.get("artifact") or {}
            t["artifacts"].append({"at": at, "path": str(art.get("path") or ""), "what": str(art.get("what") or "")})
        elif kind == "pr_open":
            t["prs"].append({"at": at, "url": str(data.get("url") or "")})
        elif kind in ("question_opened", "question_answered", "question_cleared"):
            qid = str(data.get("id") or data.get("question") or "")
            q = t["questions"].setdefault(qid, {"id": qid, "text": "", "status": "open", "answer": "", "at": at})
            q["text"] = str(data.get("question") or q["text"])
            if kind == "question_answered":
                q["status"], q["answer"] = "answered", str(data.get("answer") or "")
            elif kind == "question_cleared":
                q["status"] = "cleared"
            elif data.get("assume"):
                q["status"], q["answer"] = "assumed", str(data.get("assume") or "")
        elif kind == "needs_approval":
            t["approvals"].append({"at": at, "id": str(data.get("id") or ""), "kind": str(data.get("kind") or ""),
                                   "summary": str(data.get("summary") or ""), "decision": "pending", "by": ""})
        elif kind == "approval_resolved":
            rid = str(data.get("id") or "")
            row = next((a for a in t["approvals"] if a["id"] == rid), None)
            if row is None:
                row = {"at": at, "id": rid, "kind": str(data.get("kind") or ""), "summary": "", "decision": "", "by": ""}
                t["approvals"].append(row)
            row["decision"], row["by"], row["resolved"] = str(data.get("decision") or ""), str(data.get("by") or ""), at
        elif kind == "denied":
            t["denied"] += 1
        elif kind == "friction":
            t["friction"].append({"at": at, "skill": str(data.get("skill") or ""),
                                  "unblock": str(data.get("unblock") or ""),
                                  "severity": str(data.get("severity") or "")})
        elif kind == "assistant_text" and data.get("model"):
            model["model"] = str(data.get("model") or "")
    folded = SPEND.fold(picked)
    model["premium"] = SPEND.on_day(folded, day)
    model["turns"] = int(((folded.get("days") or {}).get(day) or {}).get("turns") or 0)
    model["denied"] = sum(t["denied"] for t in model["tickets"].values())
    if picked:
        derived = agentstate.derive(picked)
        model["state"] = str(derived.get("state") or "")
        model["role"] = agentstate.STATE_ROLES.get(model["state"], "")
    # a day with nothing but a cost line or a turn end is still a day the agent worked
    model["empty"] = not picked
    model["tickets"] = {k: v for k, v in model["tickets"].items()
                        if any(v[f] for f in ("phases", "artifacts", "prs", "questions", "approvals", "friction"))
                        or v["denied"]}
    return model


# ------------------------------------------------------------------------------------------ the emitters


def _lines(model: dict) -> list[dict]:
    """The page as a flat list of `{text, tag, ticket, heading}` lines: what both emitters draw from.

    One model, two emitters, and this is the one place the words are chosen."""
    out: list[dict] = []
    head = [model["repo"]]
    if model.get("branch"):
        head.append(f"on {model['branch']}")
    if model.get("model"):
        head.append(model["model"])
    head.append(f"{model.get('turns', 0)} turn{'s' if model.get('turns', 0) != 1 else ''}")
    if model.get("premium"):
        head.append(f"{model['premium']:g} premium requests")
    if model.get("seq_to"):
        head.append(f"seq {model['seq_from']}–{model['seq_to']}")
    out.append({"text": " · ".join(head), "tag": "", "ticket": "", "heading": False})
    if model.get("empty"):
        out.append({"text": "nothing happened on this day", "tag": "", "ticket": "", "heading": False})
    for key, t in model["tickets"].items():
        out.append({"text": key, "tag": "", "ticket": key, "heading": True})
        if t["phases"]:
            chain = " → ".join([t["phases"][0]["from"] or "—"] + [f"{p['at']} {p['to']}" for p in t["phases"]])
            out.append({"text": f"phases: {chain}", "tag": "", "ticket": key, "heading": False})
        for a in t["artifacts"]:
            out.append({"text": f"{a['at']} made {a['path']}" + (f" — {a['what']}" if a["what"] else ""),
                        "tag": "", "ticket": key, "heading": False})
        for p in t["prs"]:
            out.append({"text": f"{p['at']} PR {p['url']}", "tag": "", "ticket": key, "heading": False})
        for q in t["questions"].values():
            if q["status"] == "answered":
                out.append({"text": f"asked: {q['text']} — answered: {q['answer']}", "tag": TAG_DONE,
                            "ticket": key, "heading": False})
            elif q["status"] == "assumed":
                out.append({"text": f"assumed: {q['text']} — {q['answer']}", "tag": "", "ticket": key,
                            "heading": False})
            elif q["status"] == "cleared":
                out.append({"text": f"asked, then cleared: {q['text']}", "tag": TAG_DONE, "ticket": key,
                            "heading": False})
            else:
                out.append({"text": f"asks: {q['text']}", "tag": TAG_OPEN, "ticket": key, "heading": False})
        for a in t["approvals"]:
            who = f" by {a['by']}" if a.get("by") else ""
            out.append({"text": f"{a['at']} {a['kind']}: {a['summary'] or a['id']} — {a['decision']}{who}",
                        "tag": "", "ticket": key, "heading": False})
        for f in t["friction"]:
            tag = TAG_IMPORTANT if f["severity"] in ("", "blocker", "friction") else ""
            out.append({"text": f"{f['at']} friction ({f['severity'] or 'friction'}) {f['skill']}: {f['unblock']}",
                        "tag": tag, "ticket": key, "heading": False})
        if t["denied"]:
            out.append({"text": f"{t['denied']} tool call{'s' if t['denied'] != 1 else ''} denied", "tag": "",
                        "ticket": key, "heading": False})
    if model.get("state"):
        out.append({"text": f"ended {model['state'].replace('_', ' ')}", "tag": STATE_TAGS.get(model["state"], ""),
                    "ticket": "", "heading": False})
    if model.get("comment"):
        out.append({"text": "wrap-up comment", "tag": "", "ticket": "", "heading": True})
        for line in str(model["comment"]).splitlines():
            out.append({"text": line, "tag": "", "ticket": "", "heading": False, "quote": True})
    return out


_MD_TAG = {TAG_OPEN: "- [ ] ", TAG_DONE: "- [x] ", TAG_IMPORTANT: "- **!** ", TAG_QUESTION: "- **?** "}


def render_md(model: dict) -> str:
    lay = layout(model["project"], model["repo"], model["day"])
    out = [f"# {lay['title']}", "", f"_{lay['path']}_", ""]
    for line in _lines(model):
        if line["heading"]:
            out += ["", f"## {line['text']}", ""]
        elif line.get("quote"):
            out.append(f"> {line['text']}" if line["text"] else ">")
        else:
            out.append(_MD_TAG.get(line["tag"], "- ") + line["text"])
    return "\n".join(out).rstrip() + "\n"


def render_html(model: dict) -> str:
    """OneNote's input HTML: a `<title>`, one root `div` and one `div` per ticket, each with a `data-id` a later
    `append` can target, and OneNote's own note tags as `data-tag`. Escaped by `confluence.esc`, because the rule
    is one escaper for every page we write."""
    lay = layout(model["project"], model["repo"], model["day"])
    out = ["<!DOCTYPE html>", "<html>", "<head>", f"<title>{esc(lay['title'])}</title>", "</head>", "<body>",
           f'<div data-id="{ROOT_ID}">', f"<p>{esc(lay['path'])}</p>"]
    open_div = ""
    for line in _lines(model):
        if line["heading"] and line["ticket"]:
            if open_div:
                out.append("</div>")
            open_div = "wl-" + re.sub(r"[^A-Za-z0-9_-]", "-", line["ticket"])
            out.append(f'<div data-id="{esc(open_div, attr=True)}">')
            out.append(f"<h2>{esc(line['text'])}</h2>")
            continue
        if line["heading"]:
            if open_div:
                out.append("</div>")
                open_div = ""
            out.append(f"<h2>{esc(line['text'])}</h2>")
            continue
        tag = f' data-tag="{esc(line["tag"], attr=True)}"' if line["tag"] else ""
        if line.get("quote"):
            out.append(f"<p><cite>{esc(line['text'])}</cite></p>" if line["text"] else "<p></p>")
        else:
            out.append(f"<p{tag}>{esc(line['text'])}</p>")
    if open_div:
        out.append("</div>")
    out += ["</div>", "</body>", "</html>"]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------------------ reading and writing


def notebook(cfg: dict | None = None) -> str:
    try:
        return str(C.get(cfg if cfg is not None else C.load(), NOTEBOOK_KEY) or "").strip()
    except (C.ConfigError, OSError):
        return ""


def _cursor_path(name: str) -> str:
    return os.path.join(agent_dir(name), CURSOR)


def read_cursor(name: str) -> dict:
    try:
        return json.loads(textio.read_text(_cursor_path(name)))
    except (OSError, ValueError):
        return {}


def write_cursor(name: str, cursor: dict) -> None:
    os.makedirs(agent_dir(name), exist_ok=True)
    textio.write_text(_cursor_path(name), json.dumps(cursor, indent=2, sort_keys=True) + "\n")


def today() -> str:
    import time

    return time.strftime("%Y-%m-%d", time.gmtime())


def build(name: str, *, day: str | None = None, since: int | None = None, branch: str = "",
          registry: Registry | None = None) -> dict:
    """The day model for a registered agent: the stream brought up to date, folded, and the wrap-up comment
    quoted when the wrap-up wrote one. `since` defaults to the cursor's seq for that day (an append), 0 for a
    whole page."""
    repo = (registry or Registry()).get(name)
    day = _day(day or today())
    try:
        E.refresh(name, repo.path, repo_state=repo.state())
    except E.Busy:
        pass
    cursor = read_cursor(name)
    start = int(((cursor.get("days") or {}).get(day) or {}).get("seq") or 0) if since is None else int(since)
    model = fold(E.read(name), repo=name, project=repo.project, day=day, since=start)
    model["branch"] = branch
    comment = os.path.join(agent_dir(name), "wrapup", "comment.md")
    if os.path.isfile(comment):
        try:
            text = textio.read_text(comment).strip()
        except OSError:
            text = ""
        if text:
            model["comment"] = text
    model["layout"] = layout(repo.project, name, day)
    model["local"] = local_path(repo.project, name, day)
    model["notebook"] = notebook()
    return model


def write_local(model: dict) -> str:
    """The mirror: the whole day rewritten from the stream, so it is idempotent and never needs a cursor. The
    OneNote side appends from the cursor instead, because a page people annotate is not ours to rewrite."""
    path = model.get("local") or local_path(model["project"], model["repo"], model["day"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    textio.write_text(path, render_md(model))
    html = path[:-3] + ".html"
    textio.write_text(html, render_html(model))
    return path


def preview(name: str, *, day: str | None = None, branch: str = "", registry: Registry | None = None) -> dict:
    """What the wrap-up's `onenote` row shows: the address, the title, the seq range and the action -- `create`
    when no page of this day was written yet, `append` when the cursor says one was, `nothing` when no event
    came after it. Writes the mirror and the HTML the writer would send, both under the fleet directory."""
    model = build(name, day=day, branch=branch, registry=registry)
    cursor = read_cursor(name)
    written = (cursor.get("days") or {}).get(model["day"]) or {}
    action = "nothing" if model["empty"] else ("append" if written.get("seq") else "create")
    local = write_local(model)
    html = os.path.join(agent_dir(name), "wrapup", "onenote.html")
    os.makedirs(os.path.dirname(html), exist_ok=True)
    textio.write_text(html, render_html(model))
    return {"configured": bool(model["notebook"]), "notebook": model["notebook"], "path": model["layout"]["path"],
            "title": model["layout"]["title"], "section": model["layout"]["section"],
            "groups": model["layout"]["groups"], "seq_from": model["seq_from"], "seq_to": model["seq_to"],
            "events": model["events"], "action": action, "local": local, "html": textio.norm_path(html),
            "tickets": sorted(model["tickets"]), "state": model["state"]}
