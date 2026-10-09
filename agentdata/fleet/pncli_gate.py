"""The fleet's pncli: reads run, writes are refused and the gated extension is named.

pncli is used directly (`docs/pncli-parts.md`), so a fleet agent types `pncli jira search --jql ...` like anyone
else. A deny pattern cannot gate that: a deny is a PREFIX match, so a list of write verbs misses every write
nobody listed, and pncli's verbs are not all pinned. So the gate is a program instead. `launch.child_env` writes
a `pncli` shim into `<fleet_dir>/bin/` and puts that directory first on the agent's PATH; the shim runs this
module with the agent's argv.

* A read, a `--dry-run`, `--help` / `-h` or `--version` (`pncli.is_write` says no) runs the REAL pncli with the
  same argv, its stdout, stderr and exit code passed through untouched. The real launcher is resolved with the
  shim's directory left out of PATH (`pncli.search_path`, `pncli.exe`), so the shim never runs itself.
* Anything else is a write to a system of record, and is refused with one TOON `meta` naming the extension that
  does it behind the approval gate (`ad-confluence publish`, `ad-git pr`, `ad-jira comment|transition|create`).
  Exit 2. The classification fails safe: a verb missing from `pncli.READ_VERBS` is a write.

Outside a fleet (no agent marker in the environment) everything passes through: the shim is only ever on a fleet
agent's PATH, and a person's own terminal is the operator's.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .. import config as C
from .. import proc, toon
from ..connectors import pncli as P
from .registry import AGENT_ENV

REFUSED = "pncli_write_in_fleet"
# Set on the real pncli's environment: a shim that finds it set has resolved itself, and stops.
GUARD_ENV = "AGENTDATA_PNCLI_GATE"
EXTENSION = {
    "confluence": "ad-confluence publish <file.md> --dry-run, then the same without --dry-run (the operator approves)",
    "bitbucket": "ad-git pr --dry-run, then the same without --dry-run (the operator approves)",
    "jira": ("ad-jira comment | ad-jira transition | ad-jira create, each --dry-run first, then without "
             "(the operator approves)"),
}
ASK = "ask the operator: no extension writes this, and pncli writes are refused in a fleet"


def refusal(argv: list[str]) -> dict:
    path = P.verb(argv)
    product = path[0] if path else ""
    what = " ".join(["pncli", *path]) if path else "pncli"
    return {"ok": False, "source": "pncli (fleet gate)", "refused": REFUSED,
            "error": f"{what} writes to a system of record; in a fleet, writes go through a gated extension",
            "hint": EXTENSION.get(product, ASK)}


def _say(text: str) -> None:
    sys.stderr.write(text.rstrip("\n") + "\n")
    sys.stderr.flush()


def passthrough(argv: list[str]) -> int:
    """Run the real pncli with `argv`, stdio inherited: what it prints is what the caller reads."""
    if os.environ.get(GUARD_ENV):
        _say("pncli (fleet gate): the shim resolved itself; pin the real launcher with PNCLI_EXE or "
             "`ad-setup --patch` (pncli.exe)")
        return 127
    try:
        cfg = C.load()
    except (C.ConfigError, OSError, ValueError):
        cfg = {}
    try:
        real, _info = proc.prepare(["pncli", *argv], exe=P.exe(cfg), path=P.search_path(),
                                   hint=P.install_hint(cfg))
    except proc.ProcError as e:
        _say(f"pncli (fleet gate): {e.msg} -- {e.hint}")
        return 127
    env = proc.child_env()
    env[GUARD_ENV] = "1"
    try:
        return subprocess.call(real, env=env)
    except OSError as e:
        _say(f"pncli (fleet gate): cannot start pncli ({e}) -- {P.install_hint(cfg)}")
        return 127


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not os.environ.get(AGENT_ENV) or not P.is_write(argv):
        return passthrough(argv)
    print(toon.encode({"meta": refusal(argv)}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
