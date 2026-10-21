# PYTHON_ARGCOMPLETE_OK
"""`tnp`: the this-next-please menu. A bare `tnp` opens it; `ad-setup` and `ad-doctor` stay the scriptable forms
of every screen (see agentdata/tnp/app.py and docs/tnp.md)."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    from .. import color, completion, version
    from .. import config as C
    from ..console import utf8_stdout
    ap = argparse.ArgumentParser(prog="tnp", description="The this-next-please menu: connections, Power BI, this "
                                 "repo's settings and a health check, each saying where it writes. Scripts and "
                                 "agents use ad-setup / ad-doctor, which ask the same questions.")
    ap.add_argument("--repo", metavar="NAME", help="open it for one repository in this folder (a name or a path)")
    ap.add_argument("--print", dest="print_home", action="store_true",
                    help="print the home screen once and exit (no keys read)")
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    version.add_version(ap)
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    utf8_stdout()
    color.from_flag(a.color)
    from .app import App
    try:
        app = App(repo=a.repo, keys=iter(["q"]) if a.print_home else None)
    except C.ConfigError as e:
        sys.stderr.write(f"tnp: {e}\n" + (f"  {e.hint}\n" if e.hint else ""))
        return 2
    return app.run()


def main_tnp() -> None:
    sys.exit(main())
