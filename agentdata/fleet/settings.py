"""What the settings page may change, and what happens when it does.

One enumerated table, and an allow-list rather than a deny-list. A configuration file grows keys
nobody has seen -- a future version's, a hand-edited one, a typo -- and a page that wrote "whatever
came back" would hand a browser a way to set any of them. So a key not named here is refused by
name, and the refusal says so rather than quietly dropping the write.

Three things travel with every key, because all three are answers the operator needs and none of
them is guessable from the value:

* **type**, so a typo is refused rather than coerced. `fleet.budget_per_agent` is the cautionary
  tale that is deliberately *not* on this page: a non-numeric value there silently becomes `0.0`,
  which turns the cap off -- the exact opposite of what somebody typing in that box intends.
* **scope**, because a config file is read at different moments by different things and "why did
  nothing happen" is the obvious next question. An argv is fixed when the process starts, so a model
  changed now reaches the agent on its *next* turn and not this one.
* **why**, one line, so the page is readable without the docs open beside it.

What is missing is missing on purpose, and the reasons are not the same:

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
* `fleet.poll.*` and `fleet.inbox.folders` are read once, into a poller cached per process, so a
  control for them would appear to do nothing until the server restarted.

`tests/test_fleet_settings_api.py` asserts that every key here has a real `C.get` call site in
`agentdata/`, which is what stops this table from growing a knob that does nothing -- the state
`fleet.console.idle_s` is in today: documented, defaulted, and read by nobody.
"""
from __future__ import annotations

from .. import config as C
from . import launch as LAUNCH

# When a change takes effect. The page prints this verbatim beside the control.
NOW = "in effect now"
NEXT_TURN = "from the agent's next turn"
RESTART = "when `ad-fleet serve` restarts"

CONSOLE_HOSTS = ("cmd", "wt", "terminal", "fake")

# key -> label, type, default, scope, why. `choices` only for an enum.
EDITABLE: dict[str, dict] = {
    "fleet.approval_timeout": {
        "label": "approval window", "type": "int", "default": 30 * 60, "scope": NOW,
        "why": "seconds a write waits for your click before it is refused"},
    "fleet.max_restarts": {
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
        "label": "branch warning at", "type": "int", "default": 6, "scope": NOW,
        "why": "how many local branches before a checkout is flagged as cluttered"},
    "fleet.attach.max_mb": {
        "label": "attachment cap (MB)", "type": "int", "default": 10, "scope": NOW,
        "why": "the largest file the tray will copy into a checkout"},
    "fleet.console.palette": {
        "label": "colour the console", "type": "bool", "default": True, "scope": NEXT_TURN,
        "why": "run `ad-theme apply` inside a console the fleet opens"},
    "fleet.console.host": {
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
    "fleet.port": {
        "label": "port", "type": "int", "default": 8765, "scope": RESTART,
        "why": "the loopback port this page is served on"},
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
               "why": spec["why"], "default": spec["default"]}
        if spec.get("choices"):
            row["choices"] = list(spec["choices"])
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
    """Validate and write one key into `cfg`. The caller saves."""
    spec = EDITABLE.get(key)
    if spec is None:
        raise SettingsError(f"{key} is not a setting this page may change",
                            "the page writes only the keys it lists; edit "
                            "`~/.agentdata/config.json` for anything else", code="unknown_key")
    C.put(cfg, key, coerce(key, spec, value))


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


def tools(cfg: dict) -> dict:
    """The resolved allow and deny lists, each pattern labelled with where it came from.

    Read-only on the page, and this is the shape that makes that useful rather than merely safe:
    "what may this agent run" is answerable at a glance, and a pattern the operator added is
    distinguishable from one that shipped.
    """
    configured_allow = C.get(cfg, "fleet.allow_tools")
    allow = LAUNCH.allow_tools(cfg)
    deny = LAUNCH.deny_tools(cfg)
    default_allow = set(LAUNCH.DEFAULT_ALLOW)
    default_deny = set(LAUNCH.DEFAULT_DENY)
    return {
        "allow": [{"pattern": p,
                   "source": "default" if (configured_allow is None and p in default_allow) else "configured"}
                  for p in allow],
        "deny": [{"pattern": p, "source": "default" if p in default_deny else "configured"}
                 for p in deny],
        "allow_is_configured": configured_allow is not None,
    }
