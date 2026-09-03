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


def _kv(items: list[str], what: str) -> dict:
    out = {}
    for it in items or []:
        if "=" not in it:
            raise S.StateError(f"{what} expects key=value, got {it!r}", hint="example: phase=querying active_ticket=RDSD-1234")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def cmd_show(a) -> int:
    st = S.load(a.file)
    if policy.pretty():
        ui.facts([(k, v) for k, v in st.items() if k != "artifacts"], title=f"ad-state show ({a.file.replace(chr(92), '/')})")
        if st.get("artifacts"):
            ui.table(["path", "what", "run_id"],
                     [[x.get("path", ""), x.get("what", ""), x.get("run_id", "")] for x in st["artifacts"]],
                     title="artifacts")
        ui.note(S.line(st))
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-state show", "path": a.file.replace("\\", "/")},
                           "state": {k: v for k, v in st.items() if k != "artifacts"}, "artifacts": st.get("artifacts") or []}))
        print(S.line(st))
    return 0


def cmd_set(a) -> int:
    st = S.load(a.file)
    arts = []
    for item in a.artifact or []:
        path, _, what = item.partition("=")
        arts.append({"path": path.strip(), "what": what.strip(), "run_id": a.run_id or ""})
    S.apply(st, _kv(a.pairs, "set"), artifacts=arts, questions=a.question, clear_questions=a.clear_questions, tools=_kv(a.tool, "--tool"))
    path = S.save(st, a.file)
    if policy.pretty():
        ui.facts([("path", path), ("phase", st.get("phase")), ("active_ticket", st.get("active_ticket")),
                  ("open_questions", len(st.get("open_questions") or [])), ("artifacts", len(st.get("artifacts") or [])),
                  ("last_updated", st.get("last_updated"))], title="ad-state set")
        ui.note(S.line(st))
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-state set", "path": path, "phase": st.get("phase"), "active_ticket": st.get("active_ticket"),
                                    "open_questions": len(st.get("open_questions") or []), "artifacts": len(st.get("artifacts") or []),
                                    "last_updated": st.get("last_updated")}}))
        print(S.line(st))
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-state", description=__doc__)
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
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_set)
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
