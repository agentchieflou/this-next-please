# PYTHON_ARGCOMPLETE_OK
"""ad-confluence: html (Markdown -> storage format) · check (is this body publishable?).

The publish itself stays in `ad-pncli raw ... confluence create-page --body-file <html>`; this only builds and
proves the body, so a page is never posted as Markdown and never rejected for markup Confluence cannot parse.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import completion
from . import confluence as CF
from . import policy, ui
from . import toon
from .console import utf8_stdout
from .textio import read_text, write_text
from . import textio


def _meta(ok: bool, source: str, **kw) -> str:
    if policy.pretty():
        items = [(k, v) for k, v in kw.items() if v not in (None, "", [], {})]
        ui.facts(items, title=source, subtitle="ok" if ok else "fail")
        return ""
    return toon.encode({"meta": {"ok": ok, "source": source, **{k: v for k, v in kw.items() if v not in (None, "", [], {})}}})


def cmd_html(a) -> int:
    md = read_text(a.src)
    html, info = CF.to_storage(md, lift_title=not a.keep_title)
    title = a.title or info["title"]
    out = a.out or os.path.join(os.path.dirname(a.src) or ".", os.path.splitext(os.path.basename(a.src))[0] + ".html")
    if a.stdout:
        print(html)
        return 0
    write_text(out, html)
    msg = _meta(True, f"ad-confluence html {a.src}", path=textio.norm_path(out), title=title, chars=info["chars"],
                blocks=info["blocks"], warnings=info["warnings"],
                next=f'ad-pncli raw --body-file {textio.norm_path(out)} confluence create-page --title "{title}" --dry-run')
    if msg:
        print(msg)
    return 0


def cmd_check(a) -> int:
    CF.validate(read_text(a.path))
    msg = _meta(True, f"ad-confluence check {a.path}", path=textio.norm_path(a.path), well_formed=True)
    if msg:
        print(msg)
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-confluence", description=__doc__)
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("html", help="convert a Markdown file to a Confluence storage-format body")
    p.add_argument("src", help="the Markdown file, e.g. .agent/out/<KEY>-uat-findings.md")
    p.add_argument("--out", help="output path (default: the source with a .html suffix)")
    p.add_argument("--title", help="page title (default: the document's first H1, which is then not repeated in the body)")
    p.add_argument("--keep-title", action="store_true", help="keep the first H1 in the body instead of lifting it to the title")
    p.add_argument("--stdout", action="store_true", help="print the body instead of writing it (debugging; not for a skill)")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_html)
    p = sub.add_parser("check", help="is an existing body well-formed enough for Confluence to accept it?")
    p.add_argument("path")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(func=cmd_check)
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        return a.func(a)
    except CF.ConfluenceError as e:
        msg = _meta(False, f"ad-confluence {a.cmd}", error=str(e), hint=e.hint)
        if msg:
            print(msg)
        return 2
    except OSError as e:
        msg = _meta(False, f"ad-confluence {a.cmd}", error=str(e), hint="check the path; the source is written by the skill that produced the data")
        if msg:
            print(msg)
        return 2


if __name__ == "__main__":
    sys.exit(main())
