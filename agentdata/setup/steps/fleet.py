"""The `fleet` step: how the fleet is allowed to interrupt you.

Only the notification channels (#97). Registering repositories and starting agents are `ad-fleet`'s
job, and asking about them here would put a second way to do it in front of someone who has not
decided to run a fleet at all.

It never fails the doctor. Toasts being unavailable is a missing optional package on a machine that
may not even be Windows, not a broken install -- and a `fail` here would push the rows that *are*
broken off the top of the report.
"""
from __future__ import annotations

from ..wizard import Context, Step
from ... import config as C

YES_NO = ["yes", "no"]


def _yes(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


class FleetStep(Step):
    key = "fleet"
    title = "fleet (notifications)"

    def detect(self, ctx: Context) -> dict:
        from ...fleet import notify as N

        return {"toast": N.toast_status(ctx.cfg), "settings": N.settings(ctx.cfg)}

    def check(self, ctx: Context, found: dict) -> None:
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


def _int(value, fallback: int) -> int:
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return fallback
