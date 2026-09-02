"""`python -m agentdata <command> …` — every ad-* command, without needing the Scripts directory on PATH.

`pip install --user` (the default when site-packages is not writeable, which is normal on a managed Windows laptop)
puts console scripts in a folder Windows does not add to PATH, so `ad-setup` reports "not recognized". The module
form always works because it goes through the interpreter that owns the install.
"""
from __future__ import annotations
import sys

COMMANDS = {
    "setup": ("agentdata.cli_setup", "main_setup", "guided setup wizard"),
    "doctor": ("agentdata.cli_setup", "main_doctor", "offline health check"),
    "sql-check": ("agentdata.cli_sqlcheck", "main", "lint SQL for a dialect"),
    "jira": ("agentdata.cli_jira", "main", "Jira changelog and sprint replay"),
    "pbip": ("agentdata.cli_pbip", "main", "PBIP projection, validation, TMDL edits"),
    "uat": ("agentdata.cli_uat", "main", "expected values, UAT plan, reconciliation"),
    "dpm": ("agentdata.cli_dpm", "main", "DPM run root -> consumer job manifest (handoff contract)"),
    "pncli": ("agentdata.cli", "main_pncli", "pncli reads through the format policy"),
    "td": ("agentdata.cli", "main_td", "Teradata query"),
    "ora": ("agentdata.cli", "main_ora", "Oracle query"),
    "hive": ("agentdata.cli", "main_hive", "Hive query"),
    "impala": ("agentdata.cli", "main_impala", "Impala query"),
    "view": ("agentdata.cli", "main_view", "re-render a TSV"),
    "diff": ("agentdata.cli", "main_diff", "compare two TSVs"),
}
USAGE = ("usage: python -m agentdata <command> [options]\n\nSame commands as the ad-* console scripts:\n"
         + "\n".join(f"  {name:<10} ad-{name:<10} {help}" for name, (_m, _f, help) in COMMANDS.items())
         + "\n\nExample: python -m agentdata pbip check  (identical to: ad-pbip check)\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    name, rest = argv[0], argv[1:]
    if name.startswith("ad-"):
        name = name[3:]
    if name not in COMMANDS:
        print(f"unknown command {argv[0]!r}\n\n{USAGE}", file=sys.stderr)
        return 2
    module, func, _help = COMMANDS[name]
    __import__(module)
    sys.argv = [f"ad-{name}", *rest]
    getattr(sys.modules[module], func)()
    return 0


if __name__ == "__main__":
    sys.exit(main())
