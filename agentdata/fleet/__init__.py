"""The agent fleet: several headless Copilot agents, one per repository, supervised from here.

Epic #91's spine. A repository is registered, an agent is started in it, and everything the
supervisor knows lives under `~/.agentdata/fleet/` — never inside the repository, which belongs to
the agent (AGENTS.md rule 3, and `ad-state` stays the only writer of `state.json`).

The facts this is built on were measured, not assumed — `docs/fleet-spike.md` (#92) has the working:

* the CLI is **`copilot`**, an npm-installed command, so it is resolved through `proc.py` like
  `pncli` and `az` and never handed to `subprocess` as a bare name;
* `--output-format json` gives one JSON object per line, and the ones without `"ephemeral": true`
  are the durable narrative;
* `--allow-tool 'shell(<prefix>)'` is a **prefix** match, which is what makes an allow-list of
  `ad-*` commands expressible at all;
* there is no permission-request event: a tool the agent may not run comes back as
  `tool.execution_complete` with `error.code == "denied"`, and the turn still exits 0;
* the CLI ships a built-in MCP server, so "no MCP" is an argument (`--disable-builtin-mcps`), not
  an absence.
"""
from .registry import Registry, Repo, RegistryError
from .launch import launch_command, DEFAULT_ALLOW, DEFAULT_DENY, LaunchError

__all__ = ["Registry", "Repo", "RegistryError", "launch_command", "DEFAULT_ALLOW", "DEFAULT_DENY",
           "LaunchError"]
