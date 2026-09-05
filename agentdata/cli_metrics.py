# PYTHON_ARGCOMPLETE_OK
"""ad-metrics: summary (what the format policy actually decided) · path · clear.

A diagnostic, and off by default. `docs/data-format-policy.md` has deferred revisiting its
thresholds three times for want of a number; this reads the file that finally has one.

Nothing here sends anything anywhere. The file it reads is local, holds only shape and size, and is
written only when `metrics.enabled` is true in `~/.agentdata/config.json`.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import completion
from . import config as C
from . import metrics, policy, toon, ui
from .console import utf8_stdout
from .model import AgentTable


def _off_note(cfg: dict) -> dict:
    return {"hint": 'recording is off; set `"metrics": {"enabled": true}` in '
                    f"{C.display_path(C.path())} to start collecting"}


def cmd_summary(a) -> int:
    cfg = C.load()
    dest = a.file or metrics.path(cfg)
    records = metrics.read(dest, cfg)
    rows = metrics.summary(records)

    extra = {"file": C.display_path(dest), "recording": metrics.enabled(cfg),
             **metrics.totals(records)}
    if not metrics.enabled(cfg) and not records:
        extra.update(_off_note(cfg))
    elif not records:
        extra["hint"] = "recording is on but nothing has been rendered yet"

    # Through the format policy like every other result, rather than a table this command draws
    # itself: the point of the file is to retune those rules, and a report that dodged them would
    # be the one output nobody could compare with the rest.
    table = AgentTable(name="usage", columns=metrics.SUMMARY_COLS, rows=rows,
                       source="ad-metrics summary")
    print(policy.render(table, extra=extra))
    return 0


def cmd_path(a) -> int:
    cfg = C.load()
    print(toon.encode({"meta": {"ok": True, "source": "ad-metrics path",
                                "path": C.display_path(metrics.path(cfg)),
                                "recording": metrics.enabled(cfg),
                                "exists": os.path.exists(metrics.path(cfg))}}))
    return 0


def cmd_clear(a) -> int:
    """Delete the collected file. Asks first, because it is somebody's only copy of the data the
    thresholds are supposed to be retuned from."""
    cfg = C.load()
    dest = metrics.path(cfg)
    if not os.path.exists(dest):
        print(toon.encode({"meta": {"ok": True, "source": "ad-metrics clear",
                                    "path": C.display_path(dest), "removed": 0,
                                    "note": "nothing to remove"}}))
        return 0
    count = len(metrics.read(dest, cfg))
    if not a.yes:
        print(toon.encode({"meta": {"ok": False, "source": "ad-metrics clear",
                                    "path": C.display_path(dest), "records": count,
                                    "error": "not removed",
                                    "hint": "pass --yes; this is the only copy of the usage data"}}))
        return 2
    os.remove(dest)
    print(toon.encode({"meta": {"ok": True, "source": "ad-metrics clear",
                                "path": C.display_path(dest), "removed": count}}))
    return 0


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-metrics", description=__doc__)
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("summary", help="how often each rule fired, and what it cost")
    p.add_argument("--file", help="read this file instead of the configured one")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("path", help="where the file is, and whether recording is on")
    p.set_defaults(func=cmd_path)

    p = sub.add_parser("clear", help="delete the collected file")
    p.add_argument("--yes", action="store_true", help="confirm: it is the only copy")
    p.set_defaults(func=cmd_clear)

    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        return a.func(a)
    except C.ConfigError as e:
        print(policy.error(str(e), getattr(e, "hint", ""), f"ad-metrics {a.cmd}"))
        return 2
    except OSError as e:
        print(policy.error(str(e), "check the path in `metrics.path`", f"ad-metrics {a.cmd}"))
        return 2


if __name__ == "__main__":
    sys.exit(main())
