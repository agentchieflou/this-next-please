"""One agent's settings: the fleet's configuration with that agent's own values laid over it.

Every setting the settings page offers has a fleet-wide value (`fleet.<key>` in `config.json`, the
same place it always lived) and, where the setting means something per agent, an optional value for
one agent under `fleet.agents.<repo>`. Readers that act for one agent ask `for_agent(cfg, name)` and
read the answer exactly as they always read the fleet's, so a per-agent value needs no new code in
any reader -- only the agent's name, which every one of them already had in hand.

The layering is the whole point, and why it lives in the fleet's own file rather than anywhere
Copilot keeps its settings. `~/.copilot/config.json` is shared with the operator's own chats, and
the fleet never writes it: what one fleet agent may run, which model it runs and how it is launched
are this file's business, applied as flags on the agent's own command line at every launch. A
setting that kept "disabling itself" was a per-session approval in a Copilot window that the next
fleet launch -- carrying the fleet's own list -- did not have. A value set here is on every launch.

`fleet.agents.<repo>` is read with `get_leaf`, never as a dot-path: a repository is named after its
checkout's folder and those have dots in them (`C.put_leaf`'s docstring has the story).

List settings merge rather than replace: an agent's extra allowed commands are the fleet's extras
*plus* its own, and its extra denials likewise. An agent can be given more than the fleet, never
quietly less of a denial the fleet set.
"""
from __future__ import annotations

import copy

from .. import config as C

PARENT = "fleet.agents"

# The list-valued settings: merged, fleet first, rather than replaced.
LISTS = ("fleet.copilot.allow_extra", "fleet.copilot.deny_extra", "fleet.copilot.add_dirs")

AGENT, FLEET, DEFAULT = "agent", "fleet", "default"


def own(cfg: dict | None, repo: str | None) -> dict:
    """The values set for this one agent: `{key: value}`, empty when it inherits everything."""
    name = str(repo or "").strip()
    if not name or not isinstance(cfg, dict):
        return {}
    entry = C.get_leaf(cfg, PARENT, name, {}) or {}
    return dict(entry) if isinstance(entry, dict) else {}


def _merged(fleet_value, agent_value) -> list:
    out = []
    for item in list(fleet_value or []) + list(agent_value or []):
        if item not in out:
            out.append(item)
    return out


def for_agent(cfg: dict | None, repo: str | None) -> dict | None:
    """`cfg` as this agent sees it. `cfg` itself when the agent sets nothing of its own.

    A copy when it does: the caller's dict is the fleet's, and an agent's value written into it
    would become every agent's on the next save.
    """
    mine = own(cfg, repo)
    if not mine:
        return cfg
    out = copy.deepcopy(cfg)
    for key, value in mine.items():
        if key in LISTS:
            value = _merged(C.get(cfg, key), value)
        C.put(out, key, value)
    return out


def source(cfg: dict | None, repo: str | None, key: str) -> str:
    """Where this agent's value for `key` comes from: `agent`, `fleet` or `default`."""
    if key in own(cfg, repo):
        return AGENT
    return FLEET if C.get(cfg or {}, key) is not None else DEFAULT


def put(cfg: dict, repo: str, key: str, value) -> None:
    """Set one agent's value. The caller validated it."""
    entry = own(cfg, repo)
    entry[key] = value
    C.put_leaf(cfg, PARENT, str(repo).strip(), entry)


def drop(cfg: dict, repo: str, key: str) -> bool:
    """Back to inheriting `key`. The agent's entry goes entirely when it is left empty, because an
    empty object in the file reads as a setting somebody made."""
    entry = own(cfg, repo)
    if key not in entry:
        return False
    entry.pop(key)
    if entry:
        C.put_leaf(cfg, PARENT, str(repo).strip(), entry)
    else:
        agents = C.get(cfg, PARENT)
        if isinstance(agents, dict):
            agents.pop(str(repo).strip(), None)
    return True


def agents_with(cfg: dict | None, key: str) -> list[str]:
    """The agents that set `key` themselves, so the fleet-wide row can say who it does not reach."""
    agents = C.get(cfg or {}, PARENT)
    if not isinstance(agents, dict):
        return []
    return sorted(name for name, entry in agents.items() if isinstance(entry, dict) and key in entry)
