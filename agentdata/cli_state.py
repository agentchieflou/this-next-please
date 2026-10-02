# PYTHON_ARGCOMPLETE_OK
"""ad-state: show · set. The only writer of .agent/state.json (skill state-update). Keys and phases are validated, the
file is written UTF-8 without BOM, so no PowerShell JSON juggling is ever needed."""
from __future__ import annotations
import argparse
import os
import sys

from . import completion
from . import policy, ui
from . import state as S
from . import toon
from .console import utf8_stdout
from . import textio


def _kv(items: list[str], what: str) -> dict:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise S.StateError(f"{what} expects key=value, got {it!r}", hint="example: phase=querying active_ticket=RDSD-1234")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


# Lists that get a table of their own instead of one crushed cell in the facts panel.
LISTED = ("artifacts", "inputs")


def cmd_show(a) -> int:
    st = S.load(a.file)
    if policy.pretty():
        ui.facts([(k, v) for k, v in st.items() if k not in LISTED], title=f"ad-state show ({a.file.replace(chr(92), '/')})")
        if st.get("artifacts"):
            ui.table(["path", "what", "run_id"],
                     [[x.get("path", ""), x.get("what", ""), x.get("run_id", "")] for x in st["artifacts"]],
                     title="artifacts")
        if st.get("inputs"):
            ui.table(["path"], [[p] for p in st["inputs"]], title="inputs (attached under .agent/in/)")
        ui.note(S.line(st))
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-state show", "path": textio.norm_path(a.file)},
                           "state": {k: v for k, v in st.items() if k not in LISTED},
                           "artifacts": st.get("artifacts") or [], "inputs": st.get("inputs") or []}))
        print(S.line(st))
    return 0


def cmd_set(a) -> int:
    st = S.load(a.file)
    arts = []
    for item in a.artifact or []:
        path, _, what = item.partition("=")
        arts.append({"path": path.strip(), "what": what.strip(), "run_id": a.run_id or ""})
    S.apply(st, _kv(a.pairs, "set"), artifacts=arts, questions=a.question, clear_questions=a.clear_questions,
            tools=_kv(a.tool, "--tool"), inputs=a.input)
    path = S.save(st, a.file)
    if policy.pretty():
        ui.facts([("path", path), ("phase", st.get("phase")), ("active_ticket", st.get("active_ticket")),
                  ("open_questions", len(st.get("open_questions") or [])), ("artifacts", len(st.get("artifacts") or [])),
                  ("inputs", len(st.get("inputs") or [])), ("last_updated", st.get("last_updated"))], title="ad-state set")
        ui.note(S.line(st))
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-state set", "path": path, "phase": st.get("phase"), "active_ticket": st.get("active_ticket"),
                                    "open_questions": len(st.get("open_questions") or []), "artifacts": len(st.get("artifacts") or []),
                                    "inputs": len(st.get("inputs") or []),
                                    "last_updated": st.get("last_updated")}}))
        print(S.line(st))
    return 0


def _kind(st: dict, q: dict) -> str:
    """What this question does to the active ticket's work, in one word."""
    if q.get("kind") == "followup":
        return "followup"
    if not S.is_blocking(q):
        return "assumed"
    return "blocking" if S.blocks_scope(q, st.get("active_ticket")) else "parked"


def _questions_report(st: dict, source: str, path: str, questions: list | None = None) -> int:
    rows = [[q.get("id", ""), S.question_text(q),
             " | ".join(q.get("choices") or []) or "-",
             q.get("default") or "-", q.get("want") or "-",
             _kind(st, q), S.question_scope(q) if S.question_scope(q) is not None else "*"]
            for q in (st.get("open_questions") if questions is None else questions) or []
            if isinstance(q, dict)]
    head = ["id", "question", "choices", "default", "want", "kind", "ticket"]
    if policy.pretty():
        ui.facts([("path", path), ("phase", st.get("phase")),
                  ("open_questions", len(st.get("open_questions") or []))], title=source)
        if rows:
            ui.table(head, rows, title="open questions")
        ui.note(S.line(st))
    else:
        print(toon.encode({"meta": {"ok": True, "source": source, "path": path,
                                    "phase": st.get("phase"),
                                    "blocked_from": st.get("blocked_from") or "",
                                    "open_questions": len(st.get("open_questions") or []),
                                    "blocking": len(S.blocking_for(st))}}))
        if rows:
            print(toon.table("open_questions", head, rows))
        print(S.line(st))
    return 0


def cmd_ask(a) -> int:
    """Ask the operator something, as a record rather than a sentence.

    Without `--assume` the question is blocking: the phase becomes `blocked` and the one it came
    from is kept, so answering can put it back. With `--assume` the agent has stated its default and
    carried on, and the tile shows the assumption for the operator to overturn at leisure.
    """
    st = S.load(a.file)
    if a.assume and a.followup:
        raise S.StateError("--assume and --followup are two different answers to 'do I stop?'",
                           "--assume: a default you continue on; --followup: optional, nothing assumed")
    record = {"q": a.question, "choices": list(a.choice or []), "default": a.default or "",
              "want": a.want or "", "about": a.about or "",
              "blocking": not (a.assume or a.followup)}
    if a.assume:
        record["assume"] = a.assume
    if a.followup:
        record["kind"] = "followup"
    if a.ticket is not None:
        scope = a.ticket.strip()
        if scope.lower() == "any":
            record["ticket"] = None
        else:
            record["ticket"] = "" if scope.lower() in ("untracked", "none", "") else scope
    S.apply(st, {}, asks=[record])
    path = S.save(st, a.file)
    return _questions_report(st, "ad-state ask", path)


def _known(st: dict, qid: str) -> None:
    known = {str(q.get("id") or "") for q in (st.get("open_questions") or []) if isinstance(q, dict)}
    if qid not in known:
        raise S.StateError(f"no open question with id {qid!r}",
                           "run `ad-state blocking` for the open questions and their ids"
                           + (f"; open now: {', '.join(sorted(known))}" if known else ""))


def cmd_answer(a) -> int:
    """Record the operator's answer, and leave `blocked` when nothing blocking is left."""
    st = S.load(a.file)
    _known(st, a.id)
    S.apply(st, {}, answers={a.id: a.answer})
    path = S.save(st, a.file)
    return _questions_report(st, "ad-state answer", path)


def cmd_supersede(a) -> int:
    """Close a question the operator's newer instruction made moot, quoting that instruction.

    Not an answer -- nobody answered it -- and not `--clear-questions`, which closes every question
    and says nothing about why. One question, one reason, and the phase comes back as an answer
    would bring it back.
    """
    st = S.load(a.file)
    _known(st, a.id)
    S.apply(st, {}, superseded={a.id: a.instruction})
    path = S.save(st, a.file)
    return _questions_report(st, "ad-state supersede", path)


def cmd_blocking(a) -> int:
    """Which open questions stop work on this ticket: the router's check, made mechanical.

    Prints only the questions that block `--ticket` (default: the active ticket), and the count of
    the ones parked on other tickets, so the decision "may I start?" is read from one number rather
    than judged by eye against a list that includes every ticket the checkout ever saw.
    """
    st = S.load(a.file)
    ticket = st.get("active_ticket") if a.ticket is None else (
        "" if a.ticket.strip().lower() in ("untracked", "none", "") else a.ticket.strip())
    stops = S.blocking_for(st, ticket, use_active=False)
    parked = S.parked_for(st, ticket)
    head = ["id", "question", "choices", "default", "want", "ticket"]
    rows = [[q.get("id", ""), S.question_text(q), " | ".join(q.get("choices") or []) or "-",
             q.get("default") or "-", q.get("want") or "-",
             S.question_scope(q) if S.question_scope(q) is not None else "*"]
            for q in stops if isinstance(q, dict)]
    meta = {"ok": True, "source": "ad-state blocking", "path": textio.norm_path(a.file),
            "ticket": ticket or "", "blocking": len(stops), "parked": len(parked),
            "next": ("answer, supersede or stop: see the router's step 2" if stops else "continue")}
    if policy.pretty():
        ui.facts(list(meta.items()), title="ad-state blocking")
        if rows:
            ui.table(head, rows, title="blocking this ticket")
    else:
        print(toon.encode({"meta": meta}))
        if rows:
            print(toon.table("blocking", head, rows))
    print(S.line(st))
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-state", description=__doc__)
    from . import version
    version.add_version(ap)
    ap.add_argument("--file", default=S.PATH, help="state file (default .agent/state.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", help="print the state and the one-line summary")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_show)
    p = sub.add_parser("set", help="set fields: phase=<phase> active_ticket=<KEY> branch=<name> pr_url=<url> confluence_url=<url>")
    p.add_argument("pairs", nargs="*", help="key=value (null/none clears a string field)")
    p.add_argument("--artifact", action="append", metavar="PATH=WHAT", help="append an artifact produced this step (repeatable)")
    p.add_argument("--run-id", help="run id recorded with --artifact entries")
    p.add_argument("--question", action="append", help="append an open question (repeatable); use with phase=blocked")
    p.add_argument("--clear-questions", action="store_true", help="empty open_questions (when unblocked)")
    p.add_argument("--tool", action="append", metavar="KEY=DATE", help="tools.<key>=<date>: doctor_verified, pncli_verified")
    # The fleet's Downloads tray (#132) copies a file into `<repo>/.agent/in/<KEY>/` on a click and then
    # runs `ad-state set --input <path>` here rather than writing state.json itself, which is what keeps
    # ad-state the only writer of that file. A person attaching a file by hand records it the same way.
    p.add_argument("--input", action="append", metavar="PATH",
                   help="record a file handed to this session, normally under .agent/in/<KEY>/ (repeatable)")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_set)

    # A question is a record, not a sentence (#165). Without --assume it blocks and remembers the
    # phase it interrupted; with --assume the agent states its default and keeps working.
    p = sub.add_parser("ask", help="ask the operator something and stop, or state an assumption and continue")
    p.add_argument("question", help="the question, in one sentence")
    p.add_argument("--choice", action="append", help="an answer to offer (repeatable); the operator picks one")
    p.add_argument("--default", help="the choice to take if nobody answers")
    p.add_argument("--want", choices=["decision", "file", "value", "access"], default="decision",
                   help="what would answer this: a decision, a file, a value, or access (a human fixes "
                        "the environment: a denied tool, a missing executable, a broken install)")
    p.add_argument("--about", help="what this question is about (a path, a measure, a ticket)")
    p.add_argument("--assume", metavar="ASSUMPTION",
                   help="state a safe, reversible default and CONTINUE instead of blocking")
    p.add_argument("--followup", action="store_true",
                   help="an optional follow-up: recorded for the operator, never a stop, nothing assumed")
    p.add_argument("--ticket", metavar="KEY",
                   help="the ticket this question belongs to (default: the active ticket); "
                        "`untracked` for work without one, `any` to block every ticket")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("answer", help="record the operator's answer to an open question")
    p.add_argument("id", help="the question's id, e.g. q1")
    p.add_argument("answer", help="what the operator said")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_answer)

    p = sub.add_parser("supersede", help="close a question the operator's newer instruction made moot")
    p.add_argument("id", help="the question's id, e.g. q1")
    p.add_argument("instruction", help="the operator's instruction that replaced it, in their words")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_supersede)

    p = sub.add_parser("blocking", help="the open questions that stop work on a ticket (default: the active one)")
    p.add_argument("--ticket", metavar="KEY", help="the ticket the request is about; `untracked` for none")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_blocking)
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        return a.func(a)
    except S.StateError as e:
        print(toon.encode({"meta": {"ok": False, "source": f"ad-state {a.cmd}", "error": str(e), "hint": e.hint}}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
