# PYTHON_ARGCOMPLETE_OK
"""ad-confluence: html (Markdown -> storage format) · check (is this body publishable?) · publish (gated).

`publish` is the extension pncli does not have: it builds the storage-format body from Markdown (so a page is
never posted as Markdown and never rejected for markup Confluence cannot parse), resolves the space, the title and
the parent from the flags and the project's facts, and runs pncli's own page verb -- the template the operator
pinned in `pncli.verbs.page_create` / `pncli.verbs.page_update` -- with the body as ONE argv element, behind the
approval gate (`confluence-publish`). Reading a page is pncli's: `pncli confluence get-page`, then `ad-view`.
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
                next=f'ad-confluence publish {textio.norm_path(a.src)} --dry-run')
    if msg:
        print(msg)
    return 0


def cmd_check(a) -> int:
    CF.validate(read_text(a.path))
    msg = _meta(True, f"ad-confluence check {a.path}", path=textio.norm_path(a.path), well_formed=True)
    if msg:
        print(msg)
    return 0


PIN_HINT = {
    "page_create": ('pin it: run `pncli confluence create-page --help` and set the template: ad-setup --only pncli '
                    '--non-interactive --set pncli.verbs.page_create="confluence create-page --space {space} '
                    '--title {title} --body {body}"'),
    "page_update": ('pin it: run `pncli confluence --help` for the update verb and set the template: ad-setup '
                    '--only pncli --non-interactive --set pncli.verbs.page_update="confluence <verb> --id {page_id} '
                    '--title {title} --body {body}"'),
}
MARKDOWN_EXTS = (".md", ".markdown")


class Refused(Exception):
    def __init__(self, code: str, error: str, hint: str, exit_code: int = 2):
        super().__init__(error)
        self.code, self.error, self.hint, self.exit_code = code, error, hint, exit_code


def _active_ticket() -> str:
    from . import state as S
    try:
        return str(S.load(os.path.join(".agent", "state.json")).get("active_ticket") or "")
    except Exception:  # noqa: BLE001 - a label for the approval, never a reason to refuse
        return ""


def publish_plan(src: str, *, space: str | None = None, title: str | None = None, parent: str | None = None,
                 overwrite: str | None = None, cfg: dict | None = None, facts: dict | None = None) -> dict:
    """Everything a publish would send, worked out without sending anything. Raises `Refused`."""
    from . import config as C
    from .connectors import pncli as P
    cfg = C.load() if cfg is None else cfg
    facts = C.project_facts() if facts is None else facts
    action = "update" if overwrite else "create"
    verb = "page_update" if overwrite else "page_create"
    template = P.verb_template(verb, cfg)
    if not template:
        raise Refused("not_pinned", f"pncli's page {action} verb is not pinned (pncli.verbs.{verb} is unset)",
                      PIN_HINT[verb])
    if not src.lower().endswith(MARKDOWN_EXTS):
        raise Refused("not_markdown", f"{src} is not a Markdown file",
                      "publish takes the Markdown the skill wrote (.agent/out/<KEY>-confluence.md); the storage "
                      "format is built here")
    try:
        md = read_text(src)
    except OSError as e:
        raise Refused("no_source", f"cannot read {src}: {e.strerror or e}",
                      "write the page source first (skill confluence-publish)") from None
    if not md.strip():
        raise Refused("empty_source", f"{src} is empty", "write the page source first (skill confluence-publish)")
    if md.lstrip().startswith("<"):
        raise Refused("not_markdown", f"{src} starts with markup, not Markdown",
                      "publish converts Markdown itself; pass the .md source, not a storage-format body")
    html, info = CF.to_storage(md, lift_title=True)
    CF.validate(html)
    title = (title or info["title"] or "").strip()
    space = (space or facts.get("confluence_space") or "").strip()
    parent = (parent or facts.get("confluence_parent") or "").strip()
    if not title:
        raise Refused("no_title", f"{src} has no `# ` heading and no --title was given",
                      "start the page with `# <title>`, or pass --title")
    if action == "create" and not space:
        raise Refused("no_space", "no Confluence space: no --space and no `confluence_space` in AGENTS.md",
                      "pass --space <SPACE>, or add `- confluence_space: <SPACE>` to AGENTS.md")
    values = {"space": space, "title": title, "parent": parent, "body": html, "page_id": overwrite or "",
              "version": ""}
    try:
        argv = P.template_argv(template, {k: values[k] for k in P.VERBS[verb]})
    except ValueError as e:
        raise Refused("bad_template", f"pncli.verbs.{verb}: {e}", PIN_HINT[verb]) from None
    if P.verb(argv)[:1] != ("confluence",) or html not in argv:
        raise Refused("bad_template", f"pncli.verbs.{verb} must be a confluence verb that takes {{body}}: {template}",
                      PIN_HINT[verb])
    return {"action": action, "page_id": overwrite or "", "title": title, "space": space, "parent": parent,
            "version": "", "edited": "", "chars": len(html), "warnings": info["warnings"], "argv": argv,
            "command": P.shown_argv(argv, {"body": html})}


def cmd_publish(a) -> int:
    src = f"ad-confluence publish {a.src}"
    from . import config as C
    from . import proc
    from .connectors import pncli as P
    cfg = C.load()
    try:
        plan = publish_plan(a.src, space=a.space, title=a.title, parent=a.parent, overwrite=a.overwrite, cfg=cfg)
    except Refused as r:
        print(toon.encode({"meta": {"ok": False, "source": src, "refused": r.code, "error": r.error, "hint": r.hint}}))
        return r.exit_code
    meta = {"ok": True, "source": src, **{k: plan[k] for k in ("action", "page_id", "title", "space", "parent",
                                                                 "version", "edited", "chars")},
            "command": plan["command"]}
    if plan["warnings"]:
        meta["warnings"] = plan["warnings"]
    if a.dry_run:
        meta["dry_run"] = True
        meta["next"] = "read the plan, then run the same command without --dry-run (in a fleet it waits on the operator)"
        print(toon.encode({"meta": meta}))
        return 0
    from .fleet import approval

    payload = {k: plan[k] for k in ("action", "page_id", "title", "space", "parent", "version", "edited", "chars")}
    payload["command"] = plan["command"]
    decision = approval.require("confluence-publish", f"{plan['action']} page \"{plan['title']}\" in "
                                f"{plan['space'] or plan['page_id']} ({plan['chars']} chars)", payload,
                                ticket=_active_ticket(), cfg=cfg)
    if not decision.ok:
        print(toon.encode({"meta": approval.refusal(decision, src)}))
        return 2
    if decision.reason:
        meta["approval_note"] = decision.reason
    try:
        answer, elapsed = P.run(plan["argv"], timeout=300, cfg=cfg)
    except proc.ProcError as e:
        print(toon.encode({"meta": {"ok": False, "source": src, "refused": e.code, "error": e.msg,
                                    "hint": e.hint or "read pncli's message; nothing is retried"}}))
        return 1
    meta.update(page_id=plan["page_id"] or P.find(answer, "id", "pageId", "page_id"), url=P.url_of(answer),
                elapsed_ms=int(elapsed * 1000))
    print(toon.encode({"meta": {k: v for k, v in meta.items() if v not in (None,)}}))
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
    p = sub.add_parser("publish", help="publish a Markdown page through pncli's pinned page verb: --dry-run "
                       "prints the plan, a real run waits on the approval gate in a fleet")
    p.add_argument("src", help="the Markdown source, e.g. .agent/out/<KEY>-confluence.md")
    p.add_argument("--space", help="space key (default: `confluence_space` in AGENTS.md)")
    p.add_argument("--title", help="page title (default: the first `# ` heading)")
    p.add_argument("--parent", help="parent page id (default: `confluence_parent` in AGENTS.md)")
    p.add_argument("--overwrite", metavar="PAGE_ID", help="update this page instead of creating one")
    p.add_argument("--dry-run", action="store_true", help="resolve everything and print the plan; send nothing")
    p.set_defaults(func=cmd_publish)
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
