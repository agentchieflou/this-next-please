"""What the settings page may change, and what happens when it does.

One enumerated table, and an allow-list rather than a deny-list. A configuration file grows keys
nobody has seen -- a future version's, a hand-edited one, a typo -- and a page that wrote "whatever
came back" would hand a browser a way to set any of them. So a key not named here is refused by
name, and the refusal says so rather than quietly dropping the write.

Three things travel with every key, because all three are answers the operator needs and none of
them is guessable from the value:

* **type**, so a typo is refused rather than coerced. `fleet.budget_per_agent` was the cautionary
  tale this page was built around: a non-numeric value there silently became `0.0`, which turns the
  cap off. It is on the page now (#213) precisely because this table refuses what that reader
  swallowed.
* **scope**, because a config file is read at different moments by different things and "why did
  nothing happen" is the obvious next question. An argv is fixed when the process starts, so a model
  changed now reaches the agent on its *next* turn and not this one.
* **why**, one line, so the page is readable without the docs open beside it.

What is missing is missing on purpose, and the reasons are not the same:

* `fleet.budget_per_agent` **is** on the page since #213, and the reason it was kept off is the
  reason it is safe there now: its reader turned a typo into `0.0`, which turns the cap OFF -- the
  exact opposite of what somebody typing in that box intends. The table's own rule refuses `""`,
  `"ten"` and `-1` with `bad_type` and writes nothing, and a non-numeric value already in the file
  is now `budget_invalid`: still off, because a budget nobody can read cannot be enforced, but said
  out loud by `ad-doctor`, by `ad-fleet status` and on the tile instead of swallowed.
* `fleet.allow_tools` / `fleet.deny_tools` are shown on the page and are not editable from it. The
  allow-list is the boundary (see `launch.py`) and configuration *replaces* it rather than adding to
  it, so a list saved from a page becomes the whole boundary -- including on a partial render -- and
  an operator who saved one would silently stop receiving any command a later version adds. The file
  and `ad-setup` are where the whole list is in front of you.
* `fleet.console.helper` names a program the fleet spawns. `fleet.prompt_template` is injected into
  an agent running under that allow-list, and a malformed one is deliberately swallowed, so there is
  no natural place to refuse it. `fleet.preflight` off means a drop starts an agent with no
  confirmation card. Each of those moves a human checkpoint, which is not a thing to do from a
  dropdown.
* `fleet.mobile.*`: who may approve from outside the laptop, and where records leave it: the register's
  own rule; `config.json` and `ad-setup` only (#545, `bridge.py`).
* `fleet.poll.*` and `fleet.inbox.folders` are read once, into a poller cached per process, so a
  control for them would appear to do nothing until the server restarted.

A key marked `agent` can also be set for one agent (`fleet.agents.<repo>`, `overrides.py`), because
its reader acts for one agent and reads it through `overrides.for_agent`. The rest are one value for
the desk: they are read where no agent is in hand, so a per-agent value of one would never be read,
and `apply_agent` refuses it (`not_per_agent`). `LISTS` are the three list settings that *add* to an
agent's launch -- extra allowed and denied tool patterns, extra directories -- the editable part of
"what an agent may run" beside the read-only base list.

`tests/test_fleet_settings_api.py` asserts that every key here has a real `C.get` call site in
`agentdata/`, which is what stops this table from growing a knob that does nothing -- the state
`fleet.console.idle_s` is in today: documented, defaulted, and read by nobody.
"""
from __future__ import annotations

from .. import config as C
from . import launch as LAUNCH
from . import overrides as OV

# When a change takes effect. The page prints this verbatim beside the control.
NOW = "in effect now"
NEXT_TURN = "from the agent's next turn"
RESTART = "when `ad-fleet serve` restarts"

CONSOLE_HOSTS = ("cmd", "wt", "terminal", "fake")

# key -> label, type, default, scope, why. `choices` only for an enum; `min`/`max` (with `range`,
# the hint a refusal carries) only for a number that has bounds; `section` where the page puts it,
# when that is not the Copilot block.
EDITABLE: dict[str, dict] = {
    "fleet.approval_timeout": {
        "agent": True,
        "label": "approval window", "type": "int", "default": 30 * 60, "scope": NOW,
        "why": "seconds a write waits for your click before it is refused"},
    "fleet.max_restarts": {
        "agent": True,
        "label": "restarts per session", "type": "int", "default": 1, "scope": NOW,
        "why": "an agent that fails twice the same way will fail a third time"},
    "fleet.log_mb": {
        "label": "log size (MB)", "type": "int", "default": 20, "scope": NOW,
        "why": "how large one agent's log grows before it is rotated"},
    "fleet.log_keep": {
        "label": "logs kept", "type": "int", "default": 5, "scope": NOW,
        "why": "how many rotated logs are kept per agent"},
    "fleet.board_ttl": {
        "label": "board cache (s)", "type": "int", "default": 120, "scope": NOW,
        "why": "how long the Jira board is reused before it is fetched again"},
    "fleet.branches.warn": {
        "agent": True,
        "label": "branch warning at", "type": "int", "default": 6, "scope": NOW,
        "why": "how many local branches before a checkout is flagged as cluttered"},
    "fleet.skills.source": {
        "label": "skills marketplace", "type": "str", "default": "agentchieflou/this-next-please",
        "scope": NOW,
        "why": "the marketplace the skills are synced from: a GitHub `owner/repo`, a git URL, or a "
               "local folder holding `skills/*/SKILL.md`"},
    "fleet.onenote.notebook": {
        "label": "OneNote notebook", "type": "str", "default": "", "scope": NOW,
        "why": "the notebook the fleet's worklog pages go to, as its OneNote web URL; blank keeps the worklog "
               "local only (docs/fleet-worklog.md)"},
    "fleet.attach.max_mb": {
        "label": "attachment cap (MB)", "type": "int", "default": 10, "scope": NOW,
        "why": "the largest file the tray will copy into a checkout"},
    "fleet.console.palette": {
        "agent": True,
        "label": "colour the console", "type": "bool", "default": True, "scope": NEXT_TURN,
        "why": "run `ad-theme apply` inside a console the fleet opens"},
    "fleet.console.host": {
        "agent": True,
        "label": "console window", "type": "enum", "default": "", "scope": NEXT_TURN,
        "choices": list(CONSOLE_HOSTS),
        "why": "which terminal a console opens in; blank picks per platform"},
    "fleet.notify.dashboard": {
        "label": "notify on the page", "type": "bool", "default": True, "scope": NOW,
        "why": "raise notifications in the dashboard itself"},
    "fleet.notify.toast": {
        "label": "notify on the desktop", "type": "bool", "default": True, "scope": NOW,
        "why": "raise a system notification"},
    "fleet.notify.chime": {
        "label": "chime", "type": "bool", "default": False, "scope": NOW,
        "why": "make a sound with a notification"},
    "fleet.notify.cooldown": {
        "label": "notify cooldown (s)", "type": "int", "default": 300, "scope": NOW,
        "why": "how long the same notification is suppressed for"},
    "fleet.notify.idle_minutes": {
        "label": "away after (min)", "type": "int", "default": 20, "scope": NOW,
        "why": "how long until you count as away, which is what the away strip sums up"},
    "fleet.notify.quiet_hours": {
        "label": "quiet hours", "type": "str", "default": "", "scope": NOW,
        "why": 'no notifications in this window, e.g. "18:00-08:00"; it may wrap midnight'},
    "fleet.budget_per_agent": {
        "agent": True,
        "label": "budget per agent", "type": "int", "default": 0, "scope": NOW,
        "why": "premium requests an agent may spend before its next reply is refused; 0 is off"},
    # How an agent's Copilot is launched (friction: fleet settings mashing up with Copilot's). Each is
    # a flag on the agent's own command line, never a write to `~/.copilot/config.json`, which the
    # operator's own chats share; so each can differ per agent. The model and effort have their own
    # block on the page (`fleet.models`), and the permission lists theirs (`LISTS` below).
    # The operator's defaults of 2026-10-02: an agent has what a Copilot CLI window has, runs on
    # autopilot, and lets Copilot's `auto` pick the model -- on its balance tier since 2026-10-03,
    # when the allowance went to 50,000 credits a month (`fleet/launch.py`, `fleet/credits.py`).
    "fleet.permissions": {
        "agent": True, "label": "tool access", "type": "enum", "default": LAUNCH.DEFAULT_PERMISSIONS,
        "scope": NEXT_TURN, "choices": list(LAUNCH.PERMISSIONS),
        "why": "all: every tool a Copilot window would ask about is allowed (`--allow-all-tools`); "
               "repo: only what this repository's Copilot approvals allow (set below, per repository); "
               "strict: only the fleet's enumerated list, with its deny floor"},
    "fleet.copilot.autopilot": {
        "agent": True, "label": "autopilot", "type": "bool", "default": True, "scope": NEXT_TURN,
        "why": "Copilot's `--autopilot`: it works the task through instead of stopping after each step"},
    "fleet.copilot.autopilot_max": {
        "agent": True, "label": "autopilot continues", "type": "int", "default": 0, "scope": NEXT_TURN,
        "why": "`--max-autopilot-continues`; 0 leaves the limit to Copilot"},
    "fleet.copilot.auto_tier": {
        "agent": True, "label": "auto tier", "type": "enum", "default": LAUNCH.DEFAULT_AUTO_TIER,
        "scope": NEXT_TURN, "choices": ["", *LAUNCH.AUTO_TIERS],
        "why": "how `--model auto` weighs cost and quality; passed only when your Copilot CLI's `--help` "
               "names the option for it, never guessed"},
    # The month's allowance and its reserve (`fleet/credits.py`). Fleet-wide on purpose: one
    # enterprise allowance is drawn on by every agent, so a per-agent share would be a number
    # nobody is given. Read at every launch, so the step-down reaches the agent's next turn.
    "fleet.credits.allowance": {
        "label": "credits per month", "type": "int", "default": 0, "scope": NEXT_TURN,
        "why": "the enterprise AI-credit allowance (premium requests) the fleet draws on this calendar "
               "month; 0 records none, and then no reserve applies"},
    "fleet.credits.reserve": {
        "label": "reserve (%)", "type": "int", "default": 20, "scope": NEXT_TURN, "min": 0, "max": 100,
        "why": "inside the last this-much percent of the allowance, every new launch steps `auto` down "
               "to its efficiency tier; the per-agent budget is still the only stop"},
    "fleet.copilot.context": {
        "agent": True, "label": "context tier", "type": "enum", "default": "", "scope": NEXT_TURN,
        "choices": list(LAUNCH.CONTEXT_TIERS),
        "why": "Copilot's `/model` context picker as `--context`; blank leaves it to Copilot"},
    "fleet.copilot.log_level": {
        "agent": True, "label": "Copilot log level", "type": "enum", "default": "error",
        "scope": NEXT_TURN, "choices": list(LAUNCH.LOG_LEVELS),
        "why": "`--log-level` for the agent's own Copilot log, under its fleet folder"},
    "fleet.copilot.agent": {
        "agent": True, "label": "custom agent", "type": "str", "default": "", "scope": NEXT_TURN,
        "why": "run as this Copilot custom agent (`--agent`, Copilot's `/agent`); blank is the default agent"},
    "fleet.port": {
        "label": "port", "type": "int", "default": 8765, "scope": RESTART,
        "why": "the loopback port this page is served on"},
    # The pane's three widths (#235). On the page under Appearance, beside the palette, because
    # they are how the desk is drawn; `min`/`max` are refusals (`out_of_range`), and `tiers()`
    # below holds the four to each other.
    "fleet.tiers.rail_px": {
        "label": "rail (px)", "type": "int", "default": 48, "scope": NOW,
        "min": 32, "max": 96, "section": "appearance",
        "range": "under 32px a rail is no longer a thing to press; over 96px it is a narrow pane",
        "why": "how wide a pane is while it is a rail: its name, its state and its count"},
    "fleet.tiers.compact_px": {
        "label": "compact from (px)", "type": "int", "default": 160, "scope": NOW,
        "min": 120, "max": 720, "section": "appearance",
        "range": "a pane pulled under 120px by its gutter settles back to the rail, so a compact "
                 "tier narrower than that could never be landed on",
        "why": "the narrowest a pane with a width may be: its head, its three tools, the cards "
               "that ask you something, and the reply box"},
    "fleet.tiers.full_px": {
        "label": "full from (px)", "type": "int", "default": 360, "scope": NOW,
        "min": 200, "max": 1600, "section": "appearance",
        "range": "past 1600px no pane on one monitor would ever be full",
        "why": "from this width a pane shows everything a tile has"},
    "fleet.tiers.slack_px": {
        "label": "tier slack (px)", "type": "int", "default": 8, "scope": NOW,
        "min": 0, "max": 24, "section": "appearance",
        "range": "wider than 24px and a pane draws the tier it was in for a hand's breadth past "
                 "the boundary",
        "why": "how far past the compact/full boundary a pane goes before it changes tier, so one "
               "sitting on it does not flicker"},
}


class SettingsError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg, self.hint, self.code = msg, hint, code


def coerce(key: str, spec: dict, value):
    """`value` as this key's type, or a refusal. Never a silent coercion of a typo.

    A number box that answered "" with 0 would turn a cap off; a checkbox that answered "false"
    with True would turn notifications on. Both are refusals here.
    """
    kind = spec["type"]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if str(value).strip().lower() in ("true", "1", "yes", "on"):
            return True
        if str(value).strip().lower() in ("false", "0", "no", "off"):
            return False
        raise SettingsError(f"{key} is a yes/no setting, got {value!r}", "send true or false",
                            code="bad_type")
    if kind in ("int", "float"):
        text = str(value).strip()
        if text == "":
            raise SettingsError(f"{key} needs a number", "clear it in the config file to go back "
                                                         "to the default", code="bad_type")
        try:
            number = float(text) if kind == "float" else int(text)
        except ValueError:
            raise SettingsError(f"{key} is a number, got {value!r}",
                                "a typo here would otherwise be stored as zero", code="bad_type") from None
        if number < 0:
            raise SettingsError(f"{key} cannot be negative, got {number}", "", code="bad_type")
        low, high = spec.get("min"), spec.get("max")
        if (low is not None and number < low) or (high is not None and number > high):
            raise SettingsError(f"{key} is {number}, outside {low}–{high}", spec.get("range", ""),
                                code="out_of_range")
        return number
    if kind == "enum":
        text = str(value or "").strip()
        if text and text not in (spec.get("choices") or []):
            raise SettingsError(f"{key} is not one of {', '.join(spec.get('choices') or [])}",
                                f"got {value!r}; these are the only spellings the code branches on",
                                code="bad_type")
        return text
    return str(value if value is not None else "")


def describe(cfg: dict) -> list[dict]:
    """The table the page renders: one row per editable key, with its spec."""
    rows = []
    for key, spec in EDITABLE.items():
        row = {"key": key, "label": spec["label"], "type": spec["type"], "scope": spec["scope"],
               "why": spec["why"], "default": spec["default"],
               "section": spec.get("section", "copilot"),
               "per_agent": bool(spec.get("agent")),
               # The agents that set this themselves, which a fleet-wide change does not reach.
               "overridden_by": OV.agents_with(cfg, key)}
        if spec.get("choices"):
            row["choices"] = list(spec["choices"])
        for bound in ("min", "max"):
            if spec.get(bound) is not None:
                row[bound] = spec[bound]
        rows.append(row)
    return rows


def current(cfg: dict) -> dict:
    """What each editable key is set to right now, falling back to its default."""
    out = {}
    for key, spec in EDITABLE.items():
        value = C.get(cfg, key)
        out[key] = spec["default"] if value is None else value
    return out


def apply(cfg: dict, key: str, value) -> None:
    """Validate and write one key into `cfg`. The caller runs `check` over the batch, then saves."""
    spec = EDITABLE.get(key)
    if spec is None:
        raise SettingsError(f"{key} is not a setting this page may change",
                            "the page writes only the keys it lists; edit "
                            "`~/.agentdata/config.json` for anything else", code="unknown_key")
    value = coerce(key, spec, value)
    if key == "fleet.copilot.agent":
        value = _launch_value("agent", value)
    C.put(cfg, key, value)


# ------------------------------------------------------------------------- one agent's own values


def _launch_value(what: str, value):
    try:
        return LAUNCH.check_model_value(what, value)
    except LAUNCH.LaunchError as e:
        raise SettingsError(str(e), e.hint, code="bad_type") from None


def _agent_name(cfg: dict, repo: str, known=None) -> str:
    name = str(repo or "").strip()
    if not name:
        raise SettingsError("no agent named", "pass the repo whose setting is changing", code="no_repo")
    if known is not None and name not in known:
        raise SettingsError(f"{name} is not a registered agent", "`ad-fleet repo add` it first",
                            code="no_repo")
    return name


def apply_agent(cfg: dict, repo: str, key: str, value, *, known=None) -> None:
    """One agent's own value for `key`: validated exactly as the fleet-wide one is."""
    name = _agent_name(cfg, repo, known)
    spec = EDITABLE.get(key)
    if spec is None and key not in LISTS:
        raise SettingsError(f"{key} is not a setting this page may change", "", code="unknown_key")
    if spec is not None and not spec.get("agent"):
        raise SettingsError(f"{key} is one value for the whole fleet",
                            "it is read where no single agent is in hand (the server, the page, "
                            "the notifier), so a per-agent value would never be read",
                            code="not_per_agent")
    if key in LISTS:
        OV.put(cfg, name, key, check_list(key, value))
        return
    value = coerce(key, spec, value)
    if key == "fleet.copilot.agent":
        value = _launch_value("agent", value)
    OV.put(cfg, name, key, value)


def inherit(cfg: dict, repo: str, keys, *, known=None) -> list[str]:
    """Drop the agent's own values for `keys`; it inherits the fleet's again."""
    name = _agent_name(cfg, repo, known)
    return [key for key in keys or [] if OV.drop(cfg, name, str(key))]


def describe_agent(cfg: dict, repo: str) -> dict:
    """One agent's effective value for every setting it can have of its own, and where each came
    from: `agent` (set for it), `fleet` (set for every agent) or `default`."""
    mine = OV.for_agent(cfg, repo)
    rows = []
    for key, spec in EDITABLE.items():
        if not spec.get("agent"):
            continue
        value = C.get(mine, key)
        rows.append({"key": key, "value": spec["default"] if value is None else value,
                     "source": OV.source(cfg, repo, key),
                     "fleet": C.get(cfg, key) if C.get(cfg, key) is not None else spec["default"]})
    lists = {key: list_rows(cfg, key, repo) for key in LISTS}
    return {"repo": repo, "rows": rows, "lists": lists, "tools": tools(mine, repo=repo, fleet_cfg=cfg)}


# ---------------------------------------------------------------- the permission and directory lists

#: Settings that are lists, edited an entry at a time. Each *adds* to what the agent is launched
#: with -- the allow-list's base stays `fleet.allow_tools` or the shipped default, and the deny floor
#: stays under everything -- and an agent's entries add to the fleet's (`overrides.LISTS`).
LISTS: dict[str, dict] = {
    "fleet.copilot.allow_extra": {
        "label": "also allowed", "item": "tool", "scope": NEXT_TURN,
        "why": "tool patterns added to the allow-list: `powershell` (every PowerShell command), "
               "`shell(Get-ChildItem)` (one command and what follows it)"},
    "fleet.copilot.deny_extra": {
        "label": "also denied", "item": "tool", "scope": NEXT_TURN,
        "why": "tool patterns added to the deny floor; a denial always wins over an allow"},
    "fleet.copilot.add_dirs": {
        "label": "extra directories", "item": "dir", "scope": NEXT_TURN,
        "why": "folders outside the checkout the agent may read and write (`--add-dir`, Copilot's `/add-dir`)"},
}
assert set(LISTS) == set(OV.LISTS)


def check_list(key: str, items) -> list[str]:
    """A list setting's entries, each validated, duplicates dropped, or a refusal naming the one."""
    if isinstance(items, str):
        items = [line for chunk in items.splitlines() for line in chunk.split(",")]
    out = []
    for item in items or []:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            text = (LAUNCH.check_tool_pattern(text) if LISTS[key]["item"] == "tool"
                    else LAUNCH.check_dir(text))
        except LAUNCH.LaunchError as e:
            raise SettingsError(str(e), e.hint, code="bad_pattern") from None
        if text not in out:
            out.append(text)
    return out


def set_list(cfg: dict, key: str, items) -> list[str]:
    """The fleet-wide value of a list setting; an empty list removes the key."""
    if key not in LISTS:
        raise SettingsError(f"{key} is not a list this page may change", "", code="unknown_key")
    value = check_list(key, items)
    if value:
        C.put(cfg, key, value)
    else:
        parent = C.get(cfg, key.rpartition(".")[0])
        if isinstance(parent, dict):
            parent.pop(key.rpartition(".")[2], None)
    return value


def list_rows(cfg: dict, key: str, repo: str | None = None) -> list[dict]:
    """The entries of a list setting, each with where it came from and whether it is broad."""
    fleet = [str(v) for v in (C.get(cfg, key) or [])]
    mine = [str(v) for v in (OV.own(cfg, repo).get(key) or [])] if repo else []
    rows = [{"item": v, "source": OV.FLEET, "broad": LAUNCH.is_broad(v)} for v in fleet]
    rows += [{"item": v, "source": OV.AGENT, "broad": LAUNCH.is_broad(v)} for v in mine if v not in fleet]
    return rows


def describe_lists(cfg: dict) -> list[dict]:
    return [{"key": key, **spec, "rows": list_rows(cfg, key)} for key, spec in LISTS.items()]


SKILLS_SOURCE_KEY = "fleet.skills.source"


def check(cfg: dict, keys) -> None:
    """The rules that hold between keys, run once a batch has been applied and before it is saved,
    so two values that only go together can be written together. Today that is the tiers."""
    if any(key in TIER_KEYS.values() for key in keys):
        _values, msg, hint = _tier_values(cfg)
        if msg:
            raise SettingsError(msg, hint, code="bad_tiers")
    if SKILLS_SOURCE_KEY in keys:
        # The marketplace (docs/fleet-skills.md §The marketplace source): one of three shapes, or
        # a refusal that names them, so a typo is never stored as a source nothing can sync from.
        from . import skills as SKILLS

        value = str(C.get(cfg, SKILLS_SOURCE_KEY) or "")
        if value and not SKILLS.source_kind(value):
            raise SettingsError(f"{SKILLS_SOURCE_KEY} is not a marketplace: {value!r}",
                                "a GitHub owner/repo (optionally @ref), a git URL, or a folder that exists",
                                code="bad_source")


# ------------------------------------------------------------------------------ the tiers (#235)

#: What a pane draws is decided by how wide it is (plan-panes §The pane): a rail, compact from one
#: width, full from another, with some slack between the last two so a pane sitting on the
#: boundary does not flicker. CI's numbers are the defaults, and `docs/desk-window.md` §The tiers
#: records them beside the laptop's. The page reads them from the theme payload, so a change here
#: reaches every open desk on its next tick, with no reload.
TIER_KEYS = {"rail": "fleet.tiers.rail_px", "compact": "fleet.tiers.compact_px",
             "full": "fleet.tiers.full_px", "slack": "fleet.tiers.slack_px"}
TIER_DEFAULTS = {name: EDITABLE[key]["default"] for name, key in TIER_KEYS.items()}
#: How far apart the boundaries must stay. A compact pane is a head, three tools and a reply box,
#: which a rail's width plus 64px cannot hold. And the compact tier needs room to land in: a key
#: step is 40px, and the snaps take the hand within 8px of either boundary.
COMPACT_PAST_RAIL = 64
FULL_PAST_COMPACT = 80


def _tier_values(cfg: dict) -> tuple[dict, str, str]:
    """The four numbers `cfg` sets, CI's where it sets none, and what is wrong with them, if
    anything, with the hint that fixes it."""
    values = dict(TIER_DEFAULTS)
    for name, key in TIER_KEYS.items():
        raw = C.get(cfg, key)
        if raw is None:
            continue
        try:
            values[name] = coerce(key, EDITABLE[key], raw)
        except SettingsError as e:
            return values, e.msg, e.hint
    rail, compact, full = values["rail"], values["compact"], values["full"]
    if compact < rail + COMPACT_PAST_RAIL:
        return values, (f"compact from {compact}px is within {COMPACT_PAST_RAIL}px of the {rail}px "
                        f"rail"), (f"set it to {rail + COMPACT_PAST_RAIL}px or more, or narrow the "
                                   f"rail: a compact pane carries a head, three tools and a reply "
                                   f"box")
    if full < compact + FULL_PAST_COMPACT:
        return values, (f"full from {full}px is not {FULL_PAST_COMPACT}px past compact from "
                        f"{compact}px"), (f"set full from to {compact + FULL_PAST_COMPACT}px or "
                                          f"more first: the compact tier needs room to land in")
    return values, "", ""


def tiers(cfg: dict) -> dict:
    """`{rail, compact, full, slack, invalid}`: the widths the desk draws its tiers at.

    A four this module would refuse -- a hand edit, or a file from before a bound -- is not drawn.
    The desk gets CI's numbers and `invalid` says why, the way `budget_invalid` does: a boundary
    nobody can read is not one to guess at, and the page says so rather than drawing nonsense.
    """
    values, msg, _hint = _tier_values(cfg)
    if msg:
        return {**TIER_DEFAULTS, "invalid": msg}
    return {**values, "invalid": ""}


def set_model(cfg: dict, repo: str, *, model=None, effort=None) -> dict:
    """Write one repository's model/effort override, or clear it.

    `put_leaf`, never `C.put(cfg, f"fleet.models.{repo}")`: a repository is named after its
    checkout's folder and those have dots in them, which `C.put` would shred into nested keys --
    and the setting would vanish with no error at all.
    """
    name = str(repo or "").strip()
    if not name:
        raise SettingsError("no repository named", "pass the repo whose model is changing",
                            code="no_repo")
    entry = dict(C.get_leaf(cfg, "fleet.models", name, {}) or {})
    if model is not None:
        entry["model"] = LAUNCH.check_model_value("model", model)
    if effort is not None:
        entry["effort"] = LAUNCH.check_model_value("effort", effort)
    entry = {k: v for k, v in entry.items() if v}
    if entry:
        C.put_leaf(cfg, "fleet.models", name, entry)
    else:
        # Empty is how an operator says *inherit*, so the key goes rather than staying as `{}` --
        # an empty object reads in the file as a setting somebody made, which it is not.
        models = C.get(cfg, "fleet.models")
        if isinstance(models, dict):
            models.pop(name, None)
    return entry


def set_fleet_model(cfg: dict, *, model=None, effort=None) -> None:
    """The fleet-wide default. Empty means no flag at all, which is the measured CLI behaviour."""
    if model is not None:
        C.put(cfg, "fleet.model", LAUNCH.check_model_value("model", model))
    if effort is not None:
        C.put(cfg, "fleet.effort", LAUNCH.check_model_value("effort", effort))


def tools(cfg: dict, *, repo: str | None = None, fleet_cfg: dict | None = None) -> dict:
    """The resolved allow and deny lists, each pattern labelled with where it came from.

    Read-only on the page, and this is the shape that makes that useful rather than merely safe:
    "what may this agent run" is answerable at a glance, and a pattern the operator added is
    distinguishable from one that shipped. `added` is a `fleet.copilot.*_extra` entry for every
    agent, `agent` one for this agent alone (`cfg` is then that agent's view, `fleet_cfg` the
    fleet's).
    """
    configured_allow = C.get(cfg, "fleet.allow_tools")
    allow = LAUNCH.allow_tools(cfg)
    deny = LAUNCH.deny_tools(cfg)
    default_allow = set(LAUNCH.DEFAULT_ALLOW)
    default_deny = set(LAUNCH.DEFAULT_DENY)
    base_allow = set(LAUNCH._as_list(configured_allow)) if configured_allow is not None else default_allow
    base_deny = default_deny | set(LAUNCH._as_list(C.get(cfg, "fleet.deny_tools")))
    fleet = fleet_cfg if fleet_cfg is not None else cfg
    fleet_extra = set(LAUNCH._as_list(C.get(fleet, "fleet.copilot.allow_extra"))) | \
        set(LAUNCH._as_list(C.get(fleet, "fleet.copilot.deny_extra")))

    def origin(p: str, base: set, default: set, configured: bool) -> str:
        if p in base:
            return "default" if (not configured and p in default) else "configured"
        return "added" if p in fleet_extra else "agent"

    return {
        "allow": [{"pattern": p, "source": origin(p, base_allow, default_allow, configured_allow is not None),
                   "broad": LAUNCH.is_broad(p)} for p in allow],
        "deny": [{"pattern": p, "source": "default" if p in default_deny else
                  ("configured" if p in base_deny else ("added" if p in fleet_extra else "agent"))}
                 for p in deny],
        "allow_is_configured": configured_allow is not None,
        "permissions": LAUNCH.permissions(cfg),
    }
