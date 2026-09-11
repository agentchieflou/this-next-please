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


def _questions_report(st: dict, source: str, path: str) -> int:
    rows = [[q.get("id", ""), S.question_text(q),
             " | ".join(q.get("choices") or []) or "-",
             q.get("default") or "-", q.get("want") or "-",
             "blocking" if S.is_blocking(q) else "assumed"]
            for q in (st.get("open_questions") or []) if isinstance(q, dict)]
    if policy.pretty():
        ui.facts([("path", path), ("phase", st.get("phase")),
                  ("open_questions", len(st.get("open_questions") or []))], title=source)
        if rows:
            ui.table(["id", "question", "choices", "default", "want", "kind"], rows, title="open questions")
        ui.note(S.line(st))
    else:
        print(toon.encode({"meta": {"ok": True, "source": source, "path": path,
                                    "phase": st.get("phase"),
                                    "blocked_from": st.get("blocked_from") or "",
                                    "open_questions": len(st.get("open_questions") or [])}}))
        if rows:
            print(toon.table("open_questions", ["id", "question", "choices", "default", "want", "kind"], rows))
        print(S.line(st))
    return 0


def cmd_ask(a) -> int:
    """Ask the operator something, as a record rather than a sentence.

    Without `--assume` the question is blocking: the phase becomes `blocked` and the one it came
    from is kept, so answering can put it back. With `--assume` the agent has stated its default and
    carried on, and the tile shows the assumption for the operator to overturn at leisure.
    """
    st = S.load(a.file)
    record = {"q": a.question, "choices": list(a.choice or []), "default": a.default or "",
              "want": a.want or "", "about": a.about or "", "blocking": not a.assume}
    if a.assume:
        record["assume"] = a.assume
    S.apply(st, {}, asks=[record])
    path = S.save(st, a.file)
    return _questions_report(st, "ad-state ask", path)


def cmd_answer(a) -> int:
    """Record the operator's answer, and leave `blocked` when nothing blocking is left."""
    st = S.load(a.file)
    known = {str(q.get("id") or "") for q in (st.get("open_questions") or []) if isinstance(q, dict)}
    if a.id not in known:
        raise S.StateError(f"no open question with id {a.id!r}",
                           "run `ad-state show` for the open questions and their ids"
                           + (f"; open now: {', '.join(sorted(known))}" if known else ""))
    S.apply(st, {}, answers={a.id: a.answer})
    path = S.save(st, a.file)
    return _questions_report(st, "ad-state answer", path)


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
    p.add_argument("--want", choices=["decision", "file", "value"], default="decision",
                   help="what would answer this: a decision, a file, or a value")
    p.add_argument("--about", help="what this question is about (a path, a measure, a ticket)")
    p.add_argument("--assume", metavar="ASSUMPTION",
                   help="state a safe, reversible default and CONTINUE instead of blocking")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("answer", help="record the operator's answer to an open question")
    p.add_argument("id", help="the question's id, e.g. q1")
    p.add_argument("answer", help="what the operator said")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_answer)
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
