"""The `fleet` step: can an agent actually be started, and how may it interrupt you.

`session-bootstrap` runs `ad-doctor` every session, so this is where a broken fleet gets caught
before four agents are launched into it rather than after. Each row proves something *starts* --
`copilot --version`, `copilot` reporting a user -- because `which` finding a file has said nothing
useful in this repository before (`pncli.cmd` was on PATH and the connector still could not launch
it).

It never fails the doctor. A fleet nobody has configured is not a broken install, and a `fail` here
would push the rows that *are* broken off the top of the report.

**Skipped entirely when there is no fleet.** `ad-doctor --quiet` runs on every session start, and
probing a CLI nobody has installed costs a subprocess launch for an answer nobody wants. A registry
with repositories in it, or `fleet.enabled`, is what turns this on.
"""
from __future__ import annotations
import os

from ..wizard import Context, Step
from ... import config as C

YES_NO = ["yes", "no"]

# The build the #92 spike measured every flag and event shape against. Older is not refused --
# it is reported, because "your CLI predates what this was built on" is a fact an operator can act
# on and a guess about compatibility is not.
MEASURED_AGAINST = "1.0.81"


def _yes(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


def _int(value, fallback: int) -> int:
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return fallback


class FleetStep(Step):
    key = "fleet"
    title = "fleet (agents, notifications)"

    def detect(self, ctx: Context) -> dict:
        from ...fleet import notify as N
        from ...fleet.registry import Registry, RegistryError

        try:
            repos = Registry().sorted()
        except RegistryError:
            repos = []
        enabled = bool(repos) or _yes(C.get(ctx.cfg, "fleet.enabled"), False)
        found = {"enabled": enabled, "repos": repos, "toast": N.toast_status(ctx.cfg),
                 "settings": N.settings(ctx.cfg)}
        if not enabled:
            return found

        found.update(self._probe(ctx))
        return found

    def _probe(self, ctx: Context) -> dict:
        """The three answers that need a subprocess. Only reached when a fleet exists."""
        from ... import proc
        from ...fleet import serve as S

        version, login, why = "", "", ""
        try:
            rc, out, err, _el = proc.run(["copilot", "--version"], timeout=60)
            text = (out or err or "").strip()
            version = text.split()[-1] if rc == 0 and text else ""
            why = "" if rc == 0 else (text[:160] or f"exit {rc}")
        except Exception as e:                       # noqa: BLE001 - not found, shim broken, refused
            why = str(e)[:160]

        if version:
            # `--version` proves the launcher resolves; it says nothing about the token. A separate
            # probe, because "installed" and "logged in" fail differently and are fixed differently.
            try:
                rc, out, err, _el = proc.run(["copilot", "--help"], timeout=60)
                text = (out or "") + (err or "")
                from ...fleet import lifecycle

                login = "expired" if lifecycle.looks_like_auth_trouble(text) else "ok"
            except Exception:                        # noqa: BLE001
                login = "unknown"

        port = int(C.get(ctx.cfg, "fleet.port", 8765) or 8765)
        return {"version": version, "why": why, "login": login, "port": port,
                "port_free": self._port_free(port), "ours": bool(S and _ping(port))}

    @staticmethod
    def _port_free(port: int) -> bool:
        import socket

        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    def check(self, ctx: Context, found: dict) -> None:
        if not found["enabled"]:
            # One row, so the report says the fleet was considered rather than silently absent.
            ctx.add(self.key, "fleet", "skip", "no repositories registered",
                    "`ad-fleet repo add <path>` to start using it", keys=())
            return

        self._check_copilot(ctx, found)
        self._check_skills(ctx, found)
        self._check_port(ctx, found)
        self._check_repos(ctx, found)
        self._check_notifications(ctx, found)

    def _check_copilot(self, ctx: Context, found: dict) -> None:
        version = found.get("version") or ""
        if not version:
            ctx.add(self.key, "copilot", "fail", found.get("why") or "`copilot` would not start",
                    "install it with `npm install -g @github/copilot`, then `copilot login`",
                    keys=())
            return
        detail = version
        if _older(version, MEASURED_AGAINST):
            detail += f" (this fleet was measured against {MEASURED_AGAINST})"
        ctx.add(self.key, "copilot", "ok", detail, keys=())

        if found.get("login") == "expired":
            ctx.add(self.key, "login", "fail", "the Copilot CLI is not logged in",
                    "run `copilot login`; agents launched now would each fail their first turn",
                    keys=())
        elif found.get("login") == "ok":
            ctx.add(self.key, "login", "ok", "authenticated", keys=())

    def _check_skills(self, ctx: Context, found: dict) -> None:
        from ... import update as U

        skills = U.skills_state()
        if not skills["installed"]:
            ctx.add(self.key, "skills", "fail", f"no skills in {skills['dir']}",
                    "an agent with no skills has no router and will improvise: "
                    + " ".join(U.SKILLS_CMD), keys=())
        elif U.stale(skills):
            ctx.add(self.key, "skills", "warn",
                    f"{skills['installed']} skills, newest {skills['newest']}",
                    "the CLI is newer than the skills: agents would run last month's instructions. "
                    "`ad-update --skills`", keys=())
        else:
            ctx.add(self.key, "skills", "ok", f"{skills['installed']} in {skills['dir']}", keys=())

    def _check_port(self, ctx: Context, found: dict) -> None:
        port = found.get("port", 8765)
        if found.get("port_free"):
            ctx.add(self.key, "dashboard", "ok", f"port {port} is free", keys=("fleet.port",))
        elif found.get("ours"):
            ctx.add(self.key, "dashboard", "ok", f"already serving on {port}", keys=("fleet.port",))
        else:
            ctx.add(self.key, "dashboard", "warn", f"port {port} is taken by something else",
                    "`ad-fleet serve --port 0` picks a free one, or set `fleet.port`",
                    keys=("fleet.port",))

    def _check_repos(self, ctx: Context, found: dict) -> None:
        broken = [r.name for r in found["repos"]
                  if not (os.path.isfile(os.path.join(r.path, "AGENTS.md"))
                          and os.path.isfile(os.path.join(r.path, ".agent", "state.json")))]
        if broken:
            ctx.add(self.key, "repos", "warn",
                    f"{len(broken)} registered repo(s) no longer look like projects: "
                    + ", ".join(sorted(broken)[:4]),
                    "the checkout moved or was cleaned: `ad-setup --project .` there, or "
                    "`ad-fleet repo rm <name>`", keys=())
        else:
            ctx.add(self.key, "repos", "ok", f"{len(found['repos'])} registered", keys=())

    def _check_notifications(self, ctx: Context, found: dict) -> None:
        s = found["settings"]
        toast = found["toast"]
        if toast == "ready":
            ctx.add(self.key, "toast", "ok", "Windows Action Center", keys=("fleet.notify.toast",))
        elif toast == "off":
            ctx.add(self.key, "toast", "ok", "turned off; the dashboard still badges",
                    keys=("fleet.notify.toast",))
        else:
            ctx.add(self.key, "toast", "warn", toast,
                    'the fleet works without it -- the dashboard badges and the tab title still '
                    'count. `pip install "agentdata[fleet-win]"` adds Action Center toasts.',
                    keys=("fleet.notify.toast",))

        rules = f"cooldown {s['cooldown']}s, idle {s['idle_minutes']}m"
        if s["quiet_hours"]:
            rules += f", quiet {s['quiet_hours']}"
        ctx.add(self.key, "rules", "ok", rules,
                keys=("fleet.notify.cooldown", "fleet.notify.idle_minutes",
                      "fleet.notify.quiet_hours"))

    def ask(self, ctx: Context, found: dict) -> None:
        s = found["settings"]
        ctx.say("The fleet notifies on agent state changes only -- never on a tool call. "
                "Four agents working normally should produce nothing.")

        answer = ctx.ask.ask("fleet.notify.toast", "Windows toasts when an agent needs you?",
                             default="yes" if s["toast"] else "no", choices=YES_NO)
        C.put(ctx.cfg, "fleet.notify.toast", _yes(answer, s["toast"]))

        answer = ctx.ask.ask("fleet.notify.quiet_hours",
                             "Quiet hours (toasts held back, badges still recorded), e.g. 18:00-08:00",
                             default=s["quiet_hours"] or "")
        C.put(ctx.cfg, "fleet.notify.quiet_hours", answer.strip())

        answer = ctx.ask.ask("fleet.notify.idle_minutes",
                             "Minutes an agent may sit idle on an open ticket before it is reported",
                             default=str(s["idle_minutes"]))
        C.put(ctx.cfg, "fleet.notify.idle_minutes", _int(answer, s["idle_minutes"]))

        answer = ctx.ask.ask("fleet.notify.cooldown",
                             "Seconds before the same agent may raise the same notification again",
                             default=str(s["cooldown"]))
        C.put(ctx.cfg, "fleet.notify.cooldown", _int(answer, s["cooldown"]))

        answer = ctx.ask.ask("fleet.port", "Port for the dashboard (`ad-fleet serve`)",
                             default=str(found.get("port", 8765)))
        C.put(ctx.cfg, "fleet.port", _int(answer, 8765))


def _ping(port: int) -> bool:
    from ...fleet import opener

    return opener.ping(port, timeout=1.0)


def _older(found: str, floor: str) -> bool:
    """Version comparison that never raises on a build string nobody anticipated."""
    def parts(v):
        out = []
        for chunk in str(v).split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            out.append(int(digits) if digits else 0)
        return out

    try:
        a, b = parts(found), parts(floor)
        return a[:len(b)] < b
    except Exception:                                # noqa: BLE001 - a report must not crash
        return False
