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
    # The look before the branch (#184, AGENTS.md rule 16): every local branch, and which never
    # reached the default. Read-only by construction -- `git branch --list -D x` and
    # `git branch --no-merged main -D x` are both refused by git itself (a filter and a delete
    # cannot be combined), and `for-each-ref` has no write. `shell(git branch)` would have
    # permitted `git branch -D`, which is why the two filters are listed and the verb is not.
    "shell(git branch --list)",
    "shell(git branch --no-merged)",
    "shell(git for-each-ref)",
    "shell(git rev-list --count)",
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
#
# `{handoff}` is the same shape: a sentence naming `.agent/in/<KEY>/` and what is in it when the
# operator left something there, and empty when they did not. It says a directory and a count and
# never the content, for the same reason -- a prompt carrying the brief would be a copy of it for
# the agent to trust instead of a file for the agent to read.
DEFAULT_PROMPT = "Ticket {key}{summary}.{handoff} Invoke skill session-bootstrap, then router."
# The default with no ticket (#488): `Ticket .` was the prompt a keyless start used to launch with.
KEYLESS_PROMPT = "{handoff} Invoke skill session-bootstrap, then router."


class _Blanks(dict):
    """`{whatever}` a template asks for and we do not have becomes empty rather than an exception.

    A `fleet.prompt_template` written before `{summary}` existed must keep working, and so must one
    with a typo in a field name -- the agent starting matters more than the operator's exact wording.
    """

    def __missing__(self, key):        # noqa: D105 - the class docstring says it
        return ""


# `--model` and `--effort` are on the measured list of flags this build really has
# (docs/fleet-spike.md, "Flags, as this build actually names them"). Which model NAMES it accepts
# is read from the installed CLI (`copilot help config`) into a cached list, `fleet/models.py`
# (#360), but that list is a suggestion for the pickers, never a gate: family aliases it omits are
# accepted, and builds differ. So nothing here validates a name against a table -- the CLI is the
# validator, at the next turn -- and the only refusal is the one that keeps a value from becoming a
# second flag.
MODEL_KEYS = ("model", "effort")


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


def check_model_value(what: str, value: str) -> str:
    """A model or effort value, or a refusal by name. Never a silently dropped one.

    The whole risk is that this string is appended to a command line. `--model` takes one argument,
    so a value carrying whitespace is either a typo or a second flag wearing a model's name --
    `--model "x --allow-all-tools"` is the case this exists for, and `check_no_blanket_permission`
    would not see it because it reads the allow and deny lists, not this. A leading `-` is refused
    for the same reason: it is how an argument becomes an option.

    Empty is not an error. It is how an operator says *let the CLI choose*, which is the only
    no-model behaviour anybody has measured.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if any(ch.isspace() for ch in text):
        raise LaunchError(f"fleet.{what} is {value!r}, which is more than one argument",
                          f"a {what} is a single token; a value with a space in it would reach the "
                          "Copilot CLI as a second flag")
    if text.startswith("-"):
        raise LaunchError(f"fleet.{what} is {value!r}, which starts with a dash",
                          f"that is how an argument becomes an option; give the {what} name alone")
    return text


def _halves(repo: str | None, cfg: dict) -> tuple[str, str, str, str]:
    """The repository's own `(model, effort)` and the fleet's, each checked as a flag value."""
    entry = C.get_leaf(cfg, "fleet.models", str(repo or ""), {}) or {}
    if not isinstance(entry, dict):
        entry = {}
    return (check_model_value("model", entry.get("model", "")),
            check_model_value("effort", entry.get("effort", "")),
            check_model_value("model", C.get(cfg, "fleet.model") or ""),
            check_model_value("effort", C.get(cfg, "fleet.effort") or ""))


def model_for(repo: str | None, cfg: dict | None = None) -> tuple[str, str, str]:
    """`(model, effort, source)` for one repository. Each half is inherited on its own (decision
    15, #493): the repository's model, else `fleet.model`, else none; its effort, else
    `fleet.effort`, else none. An entry that holds only an effort keeps the fleet's model, and one
    that holds only a model keeps the fleet's effort -- a pair read as one unit silently dropped
    the other half.

    `fleet.models.<repo>` is read with `get_leaf` and never as the dot-path
    `f"fleet.models.{repo}"`: a repository's name is the basename of its checkout and routinely has
    a dot in it, and `C.get` splits on every one of them -- the failure `put_leaf`'s own docstring
    was written about.

    The third element names where the **model** came from, and is what `--show-launch` and the
    settings page print, so an operator can see *why* an agent is on the model it is on rather than
    only that it is. `cli-auto` is printed explicitly rather than left blank: an unset model is a
    decision the CLI makes, not an absence. `effort_source` names the effort's.
    """
    cfg = cfg if cfg is not None else {}
    own_model, own_effort, fleet_model, fleet_effort = _halves(repo, cfg)
    source = f"fleet.models.{repo}" if own_model else ("fleet.model" if fleet_model else "cli-auto")
    return own_model or fleet_model, own_effort or fleet_effort, source


def effort_source(repo: str | None, cfg: dict | None = None) -> str:
    """Where `model_for`'s effort came from: `fleet.models.<repo>`, `fleet.effort` or `cli-auto`."""
    _own_model, own_effort, _fleet_model, fleet_effort = _halves(repo, cfg if cfg is not None else {})
    return f"fleet.models.{repo}" if own_effort else ("fleet.effort" if fleet_effort else "cli-auto")


def prompt_for(key: str | None, prompt: str | None, cfg: dict | None = None,
               summary: str = "", handoff: str = "") -> str:
    """The one turn's prompt. An explicit `--prompt` always wins; otherwise the template."""
    if prompt:
        return prompt
    configured = C.get(cfg or {}, "fleet.prompt_template")
    # A configured template is the operator's words and is left as it is; the default drops its
    # `Ticket {key}.` clause when there is no key rather than launching with `Ticket .`.
    template = configured or (DEFAULT_PROMPT if key else KEYLESS_PROMPT)
    tidy = " ".join((summary or "").split())[:200]
    fields = _Blanks(key=key or "", summary=f": {tidy}" if tidy else "",
                     handoff=handoff or "")
    try:
        return template.format_map(fields) if configured else template.format_map(fields).strip()
    except (IndexError, ValueError):
        # A positional `{}` or a malformed brace in a configured template. Falling back to the
        # default keeps the agent starting: refusing to launch over a config file somebody wrote
        # three months ago is a much larger harm than losing their wording for one turn.
        return (DEFAULT_PROMPT if key else KEYLESS_PROMPT).format_map(fields).strip()


def launch_command(copilot: str, repo_path: str, prompt: str, *, log_dir: str,
                   session: str | None = None, cfg: dict | None = None,
                   usage_file: str | None = None, model: str = "", effort: str = "") -> list[str]:
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
    # Empty means the flag is not there at all. Passing `--model ""` would be inventing a behaviour
    # nobody measured; the measured one is that with no flag the CLI selects a model itself.
    argv += model_flags(model, effort)
    for pattern in allow:
        argv += ["--allow-tool", pattern]
    for pattern in deny:
        argv += ["--deny-tool", pattern]
    return argv


def model_flags(model: str = "", effort: str = "") -> list[str]:
    """`--model`/`--effort`, or nothing. One function so a console and a headless turn cannot drift."""
    out: list[str] = []
    name = check_model_value("model", model)
    level = check_model_value("effort", effort)
    if name:
        out += ["--model", name]
    if level:
        out += ["--effort", level]
    return out


def console_command(copilot: str, repo_path: str, *, log_dir: str, session: str,
                    resume: bool = False, cfg: dict | None = None,
                    model: str = "", effort: str = "") -> list[str]:
    """The argv for a console the fleet opens (#189): the operator's own interactive session.

    `launch_command`'s argv without the three flags that make a turn headless -- no `-p` (the
    operator types the prompt), no `--output-format json` (the console renders the conversation;
    the tile reads the session's own file, #188), no `--no-ask-user` (there is somebody to ask, and
    that is the point of a console) -- plus the session id the fleet chose, so the tile knows the
    session before the first keystroke, and `-C <repo>` so the session's working directory is the
    checkout whatever directory the window was opened from. The same enumerated allow-list and the
    same floor of denials: a console is not an excuse for `--allow-all`, and `FORBIDDEN_FLAGS` is
    refused by name here as it is for a headless turn.
    """
    allow, deny = allow_tools(cfg), deny_tools(cfg)
    check_no_blanket_permission(allow + deny)
    if not str(session or "").strip():
        raise LaunchError("a console needs a session id",
                          "the fleet mints one (`ad-fleet console <repo>`) or resumes one (`--resume <id>`)")
    argv = [copilot,
            "--resume" if resume else "--session-id", session,
            "-C", textio.norm_path(repo_path),
            "--disable-builtin-mcps",
            "--add-dir", textio.norm_path(repo_path),
            "--log-dir", textio.norm_path(log_dir),
            "--log-level", "error"]
    argv += model_flags(model, effort)
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
