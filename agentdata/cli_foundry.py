# PYTHON_ARGCOMPLETE_OK
"""ad-foundry: analyze (run an analyzer over one document) · analyzers list|get (what the resource has).

The Microsoft Foundry / Azure AI Content Understanding side of field extraction. `ad-dpm
extract-fields --engine azure-content-understanding` is how a *run* uses it; this command is how a
person finds out what analyzers exist, what fields one declares, and what it actually returns for a
document -- the three questions you have to answer before pointing a job at it.

Everything here is read-only: it runs analyzers and reads their definitions. Creating or training
an analyzer happens in the portal, where the field schema is authored.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import completion
from . import config as C
from . import policy, toon, ui
from .connectors import content_understanding as CU
from .console import utf8_stdout

# How many rows a table prints before it is a file rather than a screen.
SHOW = 60

FIELD_COLS = ["field", "value", "type", "confidence", "content_index", "content_path"]
ANALYZER_COLS = ["analyzer_id", "description", "status", "created_at"]


def _out(meta: dict, table: tuple | None = None) -> None:
    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in meta.items() if k not in ("ok", "source") and v != ""],
                 title=meta.get("source", "ad-foundry"), subtitle="ok" if meta.get("ok") else "fail")
        if table:
            title, cols, rows = table
            ui.table(cols, rows, title=title)
        return
    print(toon.encode({"meta": {k: v for k, v in meta.items() if v not in (None, "", [], {})}}))
    if table:
        title, cols, rows = table
        print(toon.table(title, cols, rows))


def _analyzer(a) -> str:
    """The analyzer for this invocation: the flag, else the configured default, else a refusal.

    Refused rather than defaulted because there is no analyzer that is right for an unknown
    document, and a wrong one returns a confident empty result rather than an error.
    """
    chosen = a.analyzer or CU.settings(analyzer=a.analyzer).get("analyzer")
    if not chosen:
        raise CU.ContentUnderstandingError(
            "no analyzer given and none is configured",
            "--analyzer <id>, or set content_understanding.analyzer in AGENTS.md; "
            "`ad-foundry analyzers list` shows what this resource has")
    return chosen


def cmd_analyze(a) -> int:
    # What to analyze before which analyzer to use: "you did not say what to read" is the more
    # immediate problem, and a missing analyzer is a setup answer rather than a typing one.
    if bool(a.file) == bool(a.url):
        raise CU.ContentUnderstandingError(
            "give exactly one of --file and --url",
            "--file <path> for a local document, --url for one the service can fetch itself")
    analyzer = _analyzer(a)
    result = CU.analyze(analyzer=analyzer, path=a.file, url=a.url, timeout=a.timeout)
    info = CU.result_meta(result)
    rows_all = CU.fields_from_result(result)

    if a.out:
        from . import textio

        textio.write_text(a.out, json.dumps(result, indent=2, default=str, ensure_ascii=False) + "\n")

    meta = {"ok": True, "source": f"ad-foundry analyze {a.file or a.url}",
            "analyzer": info["analyzer"] or analyzer, "api_version": info["api_version"],
            "contents": info["contents"], "fields": len(rows_all),
            "raw": (a.out or "").replace(os.sep, "/")}
    if info["warnings"]:
        meta["warnings"] = info["warnings"]
        meta["warning"] = info["warning"]
    if not rows_all:
        # An analyzer that declares no fields is a content-only analyzer; that is a real thing, and
        # saying so beats an empty table the reader has to interpret.
        meta["note"] = ("the analyzer returned no fields -- a content-only analyzer extracts text "
                        "and layout but declares no field schema")

    rows = [[_cell(r[c]) for c in FIELD_COLS] for r in rows_all[:SHOW]]
    if len(rows_all) > SHOW:
        meta["shown"] = f"{SHOW} of {len(rows_all)}"
    _out(meta, ("fields", FIELD_COLS, rows))
    return 0


def _cell(value) -> str:
    return "" if value is None else str(value)


def cmd_analyzers_list(a) -> int:
    found = CU.list_analyzers()
    rows = [[_cell(x.get(c) or x.get(_camel(c))) for c in ANALYZER_COLS] for x in found[:SHOW]]
    meta = {"ok": True, "source": "ad-foundry analyzers list", "analyzers": len(found)}
    if not found:
        meta["hint"] = ("this resource has no analyzers; they are created in the Foundry portal, "
                        "where the field schema is authored")
    _out(meta, ("analyzers", ANALYZER_COLS, rows))
    return 0


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def cmd_analyzers_get(a) -> int:
    found = CU.get_analyzer(a.analyzer_id)
    schema = ((found.get("fieldSchema") or found.get("field_schema")) or {})
    fields = schema.get("fields") or {}
    cols = ["field", "type", "method", "description"]
    rows = [[name,
             _cell((spec or {}).get("type")),
             _cell((spec or {}).get("method")),
             _cell((spec or {}).get("description"))[:80]]
            for name, spec in sorted(fields.items())] if isinstance(fields, dict) else []
    meta = {"ok": True, "source": f"ad-foundry analyzers get {a.analyzer_id}",
            "analyzer": found.get("analyzerId") or found.get("analyzer_id") or a.analyzer_id,
            "status": _cell(found.get("status")),
            "description": _cell(found.get("description")),
            "base_analyzer": _cell(found.get("baseAnalyzerId") or found.get("base_analyzer_id")),
            "fields": len(rows)}
    if not rows:
        meta["note"] = ("no field schema: this analyzer extracts content only, so `ad-dpm "
                        "extract-fields` would find nothing to match a job schema against")
    _out(meta, ("schema", cols, rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-foundry", description=__doc__)
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("analyze", help="run an analyzer over one document and print its fields")
    p.add_argument("--file", help="a local document (PDF, image, office file)")
    p.add_argument("--url", help="a document the service can fetch itself")
    p.add_argument("--analyzer", help="analyzer id (default: content_understanding.analyzer)")
    p.add_argument("--out", help="also write the raw result JSON here (what a fixture is made of)")
    p.add_argument("--timeout", type=int, default=CU.DEFAULT_TIMEOUT_S,
                   help=f"seconds to wait for the analysis (default {CU.DEFAULT_TIMEOUT_S})")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("analyzers", help="what analyzers this resource has, and what one declares")
    asub = p.add_subparsers(dest="sub", required=True)
    q = asub.add_parser("list", help="every analyzer on the configured endpoint")
    q.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    q.set_defaults(func=cmd_analyzers_list)
    q = asub.add_parser("get", help="one analyzer's declared field schema")
    q.add_argument("analyzer_id")
    q.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    q.set_defaults(func=cmd_analyzers_get)

    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    where = f"ad-foundry {a.cmd}" + (f" {a.sub}" if getattr(a, "sub", None) else "")
    try:
        return a.func(a)
    except CU.ContentUnderstandingError as e:
        _out({"ok": False, "source": where, "error": e.msg, "hint": e.hint})
        return 2
    except C.ConfigError as e:
        _out({"ok": False, "source": where, "error": str(e), "hint": getattr(e, "hint", "")})
        return 2
    except OSError as e:
        _out({"ok": False, "source": where, "error": str(e),
              "hint": "check the path; --url is for a document the service fetches itself"})
        return 2


if __name__ == "__main__":
    sys.exit(main())
