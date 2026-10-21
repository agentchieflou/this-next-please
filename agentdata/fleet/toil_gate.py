"""The fleet's toil: reads run, writes are refused and the gated extension is named.

toil is used directly (`docs/toil-parts.md`), so a fleet agent types `toil jira issue search --jql ...` like anyone
else. A deny pattern cannot gate that: a deny is a PREFIX match, and `--allow-write` can sit anywhere on the line.
So the gate is a program instead. `launch.child_env` writes a `toil` shim into `<fleet_dir>/bin/` and puts that
directory first on the agent's PATH; the shim runs this module with the agent's argv.

* A read, `--help` / `-h` (`toil.is_write` says no) runs the REAL toil with the same argv, its stdout, stderr and
  exit code passed through untouched. The real launcher is resolved with the shim's directory left out of PATH
  (`toil.search_path`, `toil.exe`), so the shim never runs itself.
* Anything else -- every argv carrying `--allow-write`, and the commands that change toil's own config, dossiers or
  skills -- is refused with one TOON `meta` naming the extension that does it behind the approval gate
  (`ad-confluence publish`, `ad-git pr`, `ad-jira comment|transition|create`). Exit 2. toil itself refuses a write
  without `--allow-write`, so an argv without it cannot change a service: that is what makes the split safe.

Outside a fleet (no agent marker in the environment) everything passes through: the shim is only ever on a fleet
agent's PATH, and a person's own terminal is the operator's. The shim gates the command line only: toil's MCP door
(`toil mcp`) is refused here too, and an MCP server the operator registers for an agent is outside this gate, which
is why `ad-doctor --only toil` warns about a connection with writes on.
"""
from __future__ import annotations

import os
import subprocess
import sys

from .. import config as C
from .. import proc, toon
from ..connectors import toil as T
from .registry import AGENT_ENV

REFUSED = "toil_write_in_fleet"
# Set on the real toil's environment: a shim that finds it set has resolved itself, and stops.
GUARD_ENV = "AGENTDATA_TOIL_GATE"
EXTENSION = {
    "confluence": "ad-confluence publish <file.md> --dry-run, then the same without --dry-run (the operator approves)",
    "bitbucket": "ad-git pr --dry-run, then the same without --dry-run (the operator approves)",
    "jira": ("ad-jira comment | ad-jira transition | ad-jira create, each --dry-run first, then without "
             "(the operator approves)"),
}
ASK = "ask the operator: no extension writes this, and toil writes are refused in a fleet"


def refusal(argv: list[str]) -> dict:
    path = T.verb(argv)
    area = path[0] if path else ""
    what = " ".join(["toil", *path]) if path else "toil"
    return {"ok": False, "source": "toil (fleet gate)", "refused": REFUSED,
            "error": f"{what} writes (to a system of record, or to toil's own setup); in a fleet, writes go through "
                     "a gated extension",
            "hint": EXTENSION.get(area, ASK)}


def _say(text: str) -> None:
    sys.stderr.write(text.rstrip("\n") + "\n")
    sys.stderr.flush()


def passthrough(argv: list[str]) -> int:
    """Run the real toil with `argv`, stdio inherited: what it prints is what the caller reads."""
    if os.environ.get(GUARD_ENV):
        _say("toil (fleet gate): the shim resolved itself; pin the real launcher with TOIL_EXE or "
             "`ad-setup --patch` (toil.exe)")
        return 127
    try:
        cfg = C.load()
    except (C.ConfigError, OSError, ValueError):
        cfg = {}
    try:
        real, _info = proc.prepare(["toil", *argv], exe=T.exe(cfg), path=T.search_path(),
                                   hint=T.install_hint(cfg))
    except proc.ProcError as e:
        _say(f"toil (fleet gate): {e.msg} -- {e.hint}")
        return 127
    env = proc.child_env()
    env[GUARD_ENV] = "1"
    try:
        return subprocess.call(real, env=env)
    except OSError as e:
        _say(f"toil (fleet gate): cannot start toil ({e}) -- {T.install_hint(cfg)}")
        return 127


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not os.environ.get(AGENT_ENV) or not T.is_write(argv):
        return passthrough(argv)
    print(toon.encode({"meta": refusal(argv)}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
