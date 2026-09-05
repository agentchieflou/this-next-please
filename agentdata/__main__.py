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
    "pbi": ("agentdata.cli_pbi", "main", "Fabric REST item-definition transport (reports, models)"),
    "uat": ("agentdata.cli_uat", "main", "expected values, UAT plan, reconciliation"),
    "dpm": ("agentdata.cli_dpm", "main", "DPM run root -> consumer job manifest (handoff contract)"),
    "state": ("agentdata.cli_state", "main", "show / set .agent/state.json (its only writer)"),
    "confluence": ("agentdata.cli_confluence", "main", "Markdown -> Confluence storage format (the page body)"),
    "foundry": ("agentdata.cli_foundry", "main", "Azure AI Content Understanding: analyzers and field extraction"),
    "update": ("agentdata.update", "main", "reinstall the CLI + skills from GitHub; --check reports the commit"),
    "pncli": ("agentdata.cli", "main_pncli", "pncli reads through the format policy"),
    "td": ("agentdata.cli", "main_td", "Teradata query"),
    "ora": ("agentdata.cli", "main_ora", "Oracle query"),
    "hive": ("agentdata.cli", "main_hive", "Hive query"),
    "impala": ("agentdata.cli", "main_impala", "Impala query"),
    "view": ("agentdata.cli", "main_view", "re-render a TSV"),
    "diff": ("agentdata.cli", "main_diff", "compare two TSVs"),
    "help": ("agentdata.cli_help", "main", "command catalog and per-command help"),
    "pbiviz": ("agentdata.cli_pbiviz", "main", "Power BI custom visual development loop"),
    "graph": ("agentdata.cli_graph", "main", "code graph extraction, queries, approval, and guard"),
    "test": ("agentdata.cli_test", "main", "repository test runner detection, execution, and normalization"),
    "argv": ("agentdata.cli_argv", "main", "print the argv Python received, and the shell it came from"),
}
# diagnostics: real commands, deliberately absent from the catalog a person reads
HIDDEN = {"argv"}
USAGE = ("usage: python -m agentdata <command> [options]\n\nSame commands as the ad-* console scripts:\n"
         + "\n".join(f"  {name:<10} ad-{name:<10} {help}"
                     for name, (_m, _f, help) in COMMANDS.items() if name not in HIDDEN)
         + "\n\nExample: python -m agentdata pbip check  (identical to: ad-pbip check)\n")


def usage() -> None:
    """The front door. A table when a person is reading it, the same lines as plain text otherwise."""
    from . import ui
    if not ui.on():
        print(USAGE)
        return
    ui.commands([(name, f"ad-{name}", help) for name, (_m, _f, help) in COMMANDS.items()],
                title="agentdata",
                footer="usage: python -m agentdata <command> [options] — identical to the ad-* script, and it works "
                       "when the Scripts directory is not on PATH. Every command prints TOON.")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-v", "--version"):
        from .version import version_string
        print(version_string())
        return 0
    if not argv or argv[0] in ("-h", "--help", "help"):
        usage()
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
    # the command's exit code IS its contract (ad-dpm: 2 refused, 1 failed, 0 ok). Older mains call sys.exit
    # themselves; newer ones return an int, and returning 0 here would report every refusal as success.
    rc = getattr(sys.modules[module], func)()
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
