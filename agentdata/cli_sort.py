# PYTHON_ARGCOMPLETE_OK
"""ad-sort: plan · apply · rules. Sorting a heap of *files into folders* -- not rows in a table.

`plan` reads a folder of documents, decides where each one would go under a rule set somebody supplied, and writes the
plan. It opens no candidate and copies nothing. `apply` is the second command, and it is a person's: it re-checks that
the heap is the one the plan describes, then copies -- never moves -- exactly the rows the plan marked `file`.

Refusals print `meta.refused` and exit 2. A plan with nothing to file exits 1, so a heap no rule covers is visible to a
script rather than looking like success."""
from __future__ import annotations
import argparse
import os
import sys

from . import completion
from . import policy, textio, toon, ui
from .console import utf8_stdout
from .policy import error
from .sorting import SortError
from .sorting import apply as A
from .sorting import plan as P
from .sorting import rules as R

SHOW = 60


def _out_dir(a) -> str:
    return a.out_dir or os.path.join(".agent", "out")


def _emit(meta: dict, cols, rows, *, title: str, table: str) -> None:
    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in meta.items() if k not in ("ok", "source")],
                 title=title, subtitle="ok" if meta.get("ok") else "fail")
        if rows:
            ui.table(list(cols), rows, title=table, status_col=0)
    else:
        print(toon.encode({"meta": meta}))
        print(toon.table(table, list(cols), rows))


def cmd_plan(a) -> int:
    """What would happen, written down, with nothing done."""
    rules = R.load(a.rules)
    plan = P.make(a.heap, rules, dest=a.dest)

    out_dir = _out_dir(a)
    os.makedirs(out_dir, exist_ok=True)
    stem = textio.safe_name(os.path.basename(os.path.abspath(a.heap)) or "heap")
    plan_path = textio.write_json(os.path.join(out_dir, f"{stem}-sort-plan.json"), plan)
    review = textio.write_text(os.path.join(out_dir, f"{stem}-sort-plan.md"), P.review_md(plan))

    counts = plan["counts"]
    # A plan that would file nothing is not a success. Either no rule covers this heap or the wrong folder was named,
    # and both are things the person who asked has to hear rather than read past.
    ok = counts["file"] > 0
    meta = {"ok": ok, "source": "ad-sort plan", "heap": plan["heap"], "dest": plan["dest"],
            "into": plan["into"], **counts, "plan": plan_path, "review": review,
            "next": f"read {textio.norm_path(review)}, then `ad-sort apply --plan {textio.norm_path(plan_path)}`"}
    if not ok:
        meta["hint"] = ("no rule claimed anything in this heap: check the rules file against the real names "
                        "(`ad-sort plan --heap <folder> --rules <file>` lists every one as unmatched)")
    if counts["collision"]:
        meta["note"] = (f"{counts['collision']} file(s) want a destination that is taken. Nothing is overwritten "
                        "and nothing is renamed for you: resolve them in the rules or by hand.")
    rows = [[r["verdict"], r["source"], r["destination"], r["rule"], r["why"]] for r in plan["rows"][:SHOW]]
    _emit(meta, P.PLAN_COLS, rows, title="ad-sort plan", table="plan")
    return 0 if ok else 1


def cmd_apply(a) -> int:
    """Copy what the plan said. The heap must still be the heap the plan describes."""
    plan = textio.read_json(a.plan, "plan file")
    if a.dry_run:
        root = A.check_ready(plan, dest=a.dest)
        would = [r for r in plan.get("rows", []) if r.get("verdict") == "file"]
        meta = {"ok": True, "source": "ad-sort apply", "dry_run": True, "heap": plan.get("heap", ""),
                "dest": textio.norm_path(root), "would_copy": len(would),
                "next": "re-run without --dry-run to copy; the originals stay where they are either way"}
        rows = [["file", r["source"], r["destination"], r["rule"], ""] for r in would[:SHOW]]
        _emit(meta, P.PLAN_COLS, rows, title="ad-sort apply", table="would copy")
        return 0

    result = A.run(plan, dest=a.dest)
    out_dir = _out_dir(a)
    os.makedirs(out_dir, exist_ok=True)
    stem = textio.safe_name(os.path.basename(plan.get("heap", "") or "heap"))
    receipt = textio.write_text(os.path.join(out_dir, f"{stem}-sort-receipt.md"), A.receipt_md(plan, result))

    ok = result["failed"] == 0
    meta = {"ok": ok, "source": "ad-sort apply", "heap": plan.get("heap", ""), "dest": result["dest"],
            "copied": result["copied"], "already_there": result["existed"], "failed": result["failed"],
            "receipt": receipt, "note": "the originals are untouched: this copies and never moves"}
    if result["errors"]:
        meta["hint"] = f"first failure: {result['errors'][0]['error']}"
    rows = [["copied", "", d, "", ""] for d in result["files"][:SHOW]]
    _emit(meta, P.PLAN_COLS, rows, title="ad-sort apply", table="copied")
    return 0 if ok else 1


def cmd_rules(a) -> int:
    """Write a starter rule set to edit, or check the one you have."""
    if a.write:
        if os.path.exists(a.write) and not a.force:
            raise SortError("rules_exist", f"{textio.norm_path(a.write)} is already there",
                            "pass --force to replace it, or write to another path")
        path = textio.write_json(a.write, R.STARTER)
        meta = {"ok": True, "source": "ad-sort rules", "wrote": path, "rules": len(R.STARTER["rules"]),
                "next": "edit it against the real filenames in the heap, then `ad-sort plan --rules <this file>`"}
        _emit(meta, ("rule", "glob", "regex", "into", "rename"),
              [[r["name"], r["match"].get("glob", ""), r["match"].get("regex", ""), r["into"], r.get("rename", "")]
               for r in R.STARTER["rules"]], title="ad-sort rules", table="starter")
        return 0

    rules = R.load(a.rules)
    meta = {"ok": True, "source": "ad-sort rules", "rules": len(rules["rules"]), "into": rules["into"],
            "sha256": R.sha256(rules)}
    _emit(meta, ("rule", "glob", "regex", "into", "rename"),
          [[r["name"], r["match"].get("glob", ""), r["match"].get("regex", ""), r["into"], r["rename"]]
           for r in rules["rules"]], title="ad-sort rules", table="rules")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ad-sort", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="where every file in a heap would go, written down; nothing is copied")
    p.add_argument("--heap", required=True, help="the folder the documents arrived in")
    p.add_argument("--rules", required=True, help="the rule set (an input: `ad-sort rules --write` starts one)")
    p.add_argument("--dest", help="where the sorted tree would go (default: <heap>-sorted, beside the heap)")
    p.add_argument("--out-dir", dest="out_dir", help="where the plan and its review go (default .agent/out)")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("apply", help="copy what a plan says; a person's command, not an agent's")
    p.add_argument("--plan", required=True, help="the plan file `ad-sort plan` wrote")
    p.add_argument("--dest", help="override the destination the plan recorded")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="check the heap is unchanged and list what would be copied")
    p.add_argument("--out-dir", dest="out_dir", help="where the receipt goes (default .agent/out)")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("rules", help="write a starter rule set to edit, or check one")
    p.add_argument("--rules", help="an existing rule set to validate and print")
    p.add_argument("--write", help="write the starter rule set to this path")
    p.add_argument("--force", action="store_true", help="replace an existing file at --write")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_rules)
    return ap


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = build_parser()
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    if a.cmd == "rules" and not a.write and not a.rules:
        print(error("`ad-sort rules` needs --rules <file> to check or --write <path> to start one",
                    "the rule set is an input; nothing here invents one", "ad-sort rules"))
        return 2
    try:
        return a.func(a)
    except SortError as e:
        print(toon.encode({"meta": {"ok": False, "source": f"ad-sort {a.cmd}", "refused": e.code,
                                    "error": e.msg, "hint": e.hint}}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
