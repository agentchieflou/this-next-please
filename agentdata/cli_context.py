"""`ad-context`: what a repository is, read in seconds, for the first session that sees it.

    ad-context build [--root .] [--force]   read the tree, write .agent/context/{context.json, CONTEXT.md, meta.json}
    ad-context status [--root .]            present? stale? (the file list or HEAD moved since the build)
    ad-context show [--root .]              print CONTEXT.md

No model, no network, no credential: a file walk, a few regexes and three git calls, the same answer
for the same tree. The sentences a person needs -- what this is for, what each directory is, the
first three things to do -- are the `project-onboard` skill's one pass over CONTEXT.md.
"""
from __future__ import annotations
import argparse
import os
import sys

from . import completion, context as X, textio, toon, ui
from .console import utf8_stdout
from .policy import error


def cmd_build(a) -> int:
    try:
        out = X.build(a.root, force=a.force)
    except X.ContextError as e:
        print(toon.encode({"meta": {"ok": False, "source": "ad-context build", "refused": e.code, "error": e.msg, "hint": e.hint}}))
        return 2
    except OSError as e:
        print(error(f"cannot read {a.root}: {e.strerror or e}", "pass --root <a checkout>", "ad-context build"))
        return 1
    meta = {"ok": True, "source": "ad-context build", "path": textio.norm_path(out["path"]), "files": out["files"],
            "skipped": out["skipped"], "built": out["built"]}
    if not out["skipped"]:
        meta.update({"languages": ", ".join(out["languages"]) or "-", "tests": out["tests"] or "none detected",
                     "pbip": out["pbip"], "sql_files": out["sql_files"],
                     "facts_missing": ", ".join(out["facts_missing"]) or "-",
                     "next": "read the page; `project-onboard` writes the sentences between its model markers"})
    else:
        meta["why"] = out["why"]
    if ui.on():
        ui.facts(list(meta.items()), title="ad-context build")
    else:
        print(toon.encode({"meta": meta}))
    print(f"context: {out['files']} files · {textio.norm_path(out['path'])} · {'unchanged' if out['skipped'] else 'built'}")
    return 0


def cmd_status(a) -> int:
    st = X.status(a.root)
    meta = {"ok": True, "source": "ad-context status", "present": st["present"], "stale": st["stale"],
            "built": st.get("built") or "-", "why": st["why"],
            "next": "ad-context build" if st["stale"] else "continue"}
    if ui.on():
        ui.facts(list(meta.items()), title="ad-context status")
    else:
        print(toon.encode({"meta": meta}))
    return 0


def cmd_show(a) -> int:
    path = os.path.join(a.root, X.DIR, X.PAGE)
    if not os.path.isfile(path):
        print(error(f"{textio.norm_path(os.path.join(X.DIR, X.PAGE))} is not there", "run `ad-context build` first", "ad-context show"))
        return 3
    print(textio.read_text(path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ad-context", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    from . import version

    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, help_text in (("build", cmd_build, "read the tree and write .agent/context/ (skips when nothing moved)"),
                                ("status", cmd_status, "is the context present, and does it still describe this tree?"),
                                ("show", cmd_show, "print .agent/context/CONTEXT.md")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", default=".", help="the checkout (default: the current directory)")
        if name == "build":
            p.add_argument("--force", action="store_true", help="rebuild even when the file list and HEAD are unchanged")
        p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
        p.set_defaults(func=fn)
    return ap


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = build_parser()
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
