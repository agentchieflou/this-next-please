"""The exact command line an agent is started with, and why each flag is on it.

Every flag was chosen from something measured in `docs/fleet-spike.md` (#92), not from the
documentation. The command line is a value, not a side effect: `ad-fleet status --show-launch`
prints it, allow-list and all, because "what may this agent do" should be answerable without
reading the supervisor.

**The allow-list is the boundary. The deny-list is not, and cannot be.** Two measurements say so:

* `--allow-tool 'shell(git)'` is a PREFIX match, so it permits `git` and everything that can follow
  it. A deny is a prefix too -- `shell(git push --force)` does not match
  `git push -u origin HEAD --force` -- so a deny can never be a safety net for a loose allow.
* Run with no allow-list and asked to write a file, the CLI *denied* its own `apply_patch` tool
  and denied `Set-Content`, then *allowed* a .NET file-write call made from inside PowerShell, and
  the file was written. The model tried four spellings before one passed. See docs/fleet-spike.md.

So the allow-list is an enumerated whitelist, narrow enough that no dangerous continuation can be
appended, and the denies below are a second line against near-miss spellings -- never the boundary.
Anything that must be *refused* rather than merely un-allowed belongs in the `ad-*` command that
performs it, where a refusal is a return value rather than a guess about a command string.
"""
from __future__ import annotations
import os

from .. import config as C
from .. import textio

# Shell commands the agent may run without being asked.
#
# NOT `shell(ad-)`. That prefix covers every console script this package installs, which now
# includes `ad-fleet` -- so the agent could run `ad-fleet status` and read every *other* registered
# repository's `.agent/state.json` (AGENTS.md rule 3, broken from inside an agent), or
# `ad-fleet stop --all`. The commands are enumerated instead, and the supervisor is not among them.
DEFAULT_ALLOW = [
    "shell(ad-state)",               # the agent's own state; ad-state is its only writer
    "shell(ad-doctor)",
    "shell(ad-help)",
    "shell(ad-jira)",
    "shell(ad-pncli)",
    "shell(ad-sql-check)",
    "shell(ad-graph)",
    "shell(ad-test)",
    "shell(ad-pbip)",
    "shell(ad-pbi)",
    "shell(ad-uat)",
    "shell(ad-dpm)",
    "shell(ad-confluence)",
    "shell(ad-td)", "shell(ad-ora)", "shell(ad-hive)", "shell(ad-impala)",
    "shell(ad-view)", "shell(ad-diff)",
    "shell(git status)",
    "shell(git diff)",
    "shell(git log)",
    "shell(git checkout -b)",
    "shell(git add)",
    # `-m` deliberately: `shell(git commit)` would also permit `git commit --no-verify`, and this
    # repo's own pre-commit hook (agentdata/graph/guard.py) is what --no-verify skips.
    "shell(git commit -m)",
    "skill",                         # the skill tool itself; without it the router cannot run
]

# A floor, not a default: `deny_tools()` always includes these, whatever configuration adds.
DEFAULT_DENY = [
    # The agent must not drive the fleet, reinstall the CLI, or rewrite the operator's config.
    "shell(ad-fleet)",
    "shell(ad-update)",
    "shell(ad-setup)",
    "shell(python -m agentdata fleet)",
    "shell(python -m agentdata update)",
    "shell(python -m agentdata setup)",
    # History it must not rewrite. Each spelling is listed because a deny is a PREFIX: blocking
    # `git push --force` does nothing about `git push -u origin HEAD --force`, which is why the
    # allow-list above stops at `git commit -m` and does not offer a push at all.
    "shell(git push)",
    "shell(git merge)",
    "shell(git rebase)",
    "shell(git reset --hard)",
    "shell(git clean)",
    "shell(git commit --no-verify)",
    "shell(git commit -n)",
    "shell(pip install)",
    "shell(npm install)",
    "shell(rm)",
    "shell(del)",
    # Anything that could reach Jira, Confluence or Bitbucket without passing the approval gate
    # (#95). None of these is on the allow-list, so this is the second line and not the boundary --
    # but the boundary here is a model's own classifier, which the spike measured letting a .NET
    # file-write through after refusing three plainer spellings of the same act.
    "shell(pncli)",                  # AGENTS.md rule 4 already forbids it; the gate is in ad-pncli
    "shell(curl)",
    "shell(wget)",
    "shell(Invoke-RestMethod)",
    "shell(Invoke-WebRequest)",
    "shell(iwr)", "shell(irm)",      # the PowerShell aliases, which are a different command string
]

# Never acceptable in config, whatever a hurry says. These are the flags that turn an approval gate
# into a formality.
FORBIDDEN_FLAGS = ("--allow-all", "--allow-all-tools", "--allow-all-paths", "--allow-all-urls",
                   "--yolo")

# `{summary}` is filled from the board when the fleet knows it and left empty otherwise, so the
# template works either way. Deliberately nothing more than the key and one line: `jira-triage` does
# the reading through `ad-pncli`, as its SKILL.md says, and a fleet that pasted acceptance criteria
# into the prompt would be a second, staler copy of the ticket for the agent to trust.
DEFAULT_PROMPT = "Ticket {key}{summary}. Invoke skill session-bootstrap, then router."


class _Blanks(dict):
    """`{whatever}` a template asks for and we do not have becomes empty rather than an exception.

    A `fleet.prompt_template` written before `{summary}` existed must keep working, and so must one
    with a typo in a field name -- the agent starting matters more than the operator's exact wording.
    """

    def __missing__(self, key):        # noqa: D105 - the class docstring says it
        return ""


class LaunchError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


def _dedup(patterns: list[str]) -> list[str]:
    seen, out = set(), []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def allow_tools(cfg: dict | None = None) -> list[str]:
    """What the agent may run. Configuration *replaces* the default, so an operator can narrow it."""
    configured = C.get(cfg or {}, "fleet.allow_tools")
    return _dedup(_as_list(configured)) if configured is not None else list(DEFAULT_ALLOW)


def deny_tools(cfg: dict | None = None) -> list[str]:
    """What the agent may never run. Configuration *adds* to the default; it cannot remove one.

    The difference from `allow_tools` is deliberate. An operator narrowing the allow-list is making
    the agent safer; an operator who adds one deny should not silently lose the other fifteen,
    which is what "configuration replaces the default" would mean -- and `--show-launch` would have
    reported the loss as though it were the guarantee.
    """
    return _dedup(list(DEFAULT_DENY) + _as_list(C.get(cfg or {}, "fleet.deny_tools")))


def check_no_blanket_permission(patterns: list[str]) -> None:
    """A config that asks for `--allow-all` is refused by name.

    Not filtered out quietly: an operator who wrote it believes the fleet is running that way, and
    the gap between what they believe and what runs is the whole risk.
    """
    for pattern in patterns:
        low = str(pattern).strip().lower()
        for bad in FORBIDDEN_FLAGS:
            if low == bad or low.startswith(bad + " ") or low == bad.lstrip("-"):
                raise LaunchError(
                    f"fleet configuration asks for {pattern!r}",
                    "the fleet never runs an agent with blanket permission -- list the commands it "
                    "may run as `shell(<prefix>)` patterns in `fleet.allow_tools` instead")


def prompt_for(key: str | None, prompt: str | None, cfg: dict | None = None,
               summary: str = "") -> str:
    """The one turn's prompt. An explicit `--prompt` always wins; otherwise the template."""
    if prompt:
        return prompt
    template = C.get(cfg or {}, "fleet.prompt_template") or DEFAULT_PROMPT
    tidy = " ".join((summary or "").split())[:200]
    fields = _Blanks(key=key or "", summary=f": {tidy}" if tidy else "")
    try:
        return template.format_map(fields)
    except (IndexError, ValueError):
        # A positional `{}` or a malformed brace in a configured template. Falling back to the
        # default keeps the agent starting: refusing to launch over a config file somebody wrote
        # three months ago is a much larger harm than losing their wording for one turn.
        return DEFAULT_PROMPT.format_map(fields)


def launch_command(copilot: str, repo_path: str, prompt: str, *, log_dir: str,
                   session: str | None = None, cfg: dict | None = None,
                   usage_file: str | None = None) -> list[str]:
    """The argv for one turn.

    The **logical** argv, starting with the bare name. Resolving it is `proc.command()`'s job and
    the supervisor's: on Windows an npm-installed CLI is a `.cmd` shim, and `proc` returns either
    `node <entry point> ...` as a list or a whole cmd line as a string, depending on the shim. Doing
    that here would mean this function had to know which -- and handing a shim path straight to
    `Popen` is the WinError trap `proc.py` exists to avoid.

    `--no-ask-user` is deliberate and load-bearing: headless there is nobody to ask, and the spike
    showed the CLI does not emit a permission *request* anyway -- it denies the tool, reports
    `error.code == "denied"` on `tool.execution_complete`, and finishes the turn with exit 0. So the
    fleet's job is to notice the denial, not to answer a question that is never asked.
    """
    allow, deny = allow_tools(cfg), deny_tools(cfg)
    check_no_blanket_permission(allow + deny)

    argv = [copilot, "-p", prompt,
            "--output-format", "json",
            "--no-ask-user",
            # The CLI ships a built-in github-mcp-server. Epic #91's "no MCP anywhere" rule is
            # therefore an argument, not an absence.
            "--disable-builtin-mcps",
            "--add-dir", textio.norm_path(repo_path),
            "--log-dir", textio.norm_path(log_dir),
            "--log-level", "error"]
    if usage_file:
        # Simpler than parsing the stream for cost, and exact. #101 budgets from this.
        argv += ["--usage-output-file", textio.norm_path(usage_file)]
    if session:
        argv += ["--resume", session]
    for pattern in allow:
        argv += ["--allow-tool", pattern]
    for pattern in deny:
        argv += ["--deny-tool", pattern]
    return argv


def child_env(repo_name: str, fleet_dir_path: str) -> dict:
    """What the agent's process inherits.

    The two `AGENTDATA_FLEET_*` markers are how a gated `ad-*` command inside the agent knows it is
    running under a supervisor at all -- #95 keys its approval gate on them. They are not a grant:
    `ad-fleet` itself is on the deny-list, so an agent cannot use its own marker to drive the fleet.
    """
    from .registry import AGENT_ENV, FLEET_DIR_ENV

    env = dict(os.environ)
    env[AGENT_ENV] = repo_name
    env[FLEET_DIR_ENV] = textio.norm_path(fleet_dir_path)
    env["AGENTDATA_COLOR"] = "never"      # the events are read by a machine
    env["PYTHONUTF8"] = "1"
    env["NO_COLOR"] = "1"
    return env
