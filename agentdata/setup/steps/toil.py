"""Step: toil, required -- its launcher, and the connections the `ad-*` extensions go through.

toil is the service backend for Jira, Confluence and Bitbucket (`docs/toil-parts.md`), so a missing launcher, or one
that cannot start (toil needs Node 24.14+), fails. Its connections are toil's own: a person sets one up in toil
(`toil connections add <name> --area jira`, or the menu a bare `toil` opens), the token goes to the OS credential
store, and nothing of it is copied here -- `toil connections list` names a connection, its area, host and whether
writes are on, never a secret. This step pins the launcher it proved starts, picks the connection per area when
there are several, and removes the retired `pncli` section from the config.

Writes need `writes: true` on a connection, which only a person sets. The `ad-*` write extensions still ask first
(their `--dry-run` and the approval gate) and add `--allow-write` only to the run that was approved; a connection
with writes on is reported, because an MCP server a person registers with toil is outside that gate."""
from __future__ import annotations
from ... import config as C
from ...connectors import toil as T
from ..wizard import Context, Step
from ... import textio

# (row name, toil areas that serve it, what a missing one costs)
SERVICES = (("jira", ("jira", "jira-cloud"), "`ad-jira`, the fleet's Jira cells and the UAT live side"),
            ("confluence", ("confluence", "confluence-cloud"), "`ad-confluence publish`"),
            ("bitbucket", ("bitbucket", "bitbucket-cloud"), "`ad-git pr` and the fleet's PR cell"),
            ("github", ("github",), "`ad-git pr` on a GitHub remote"))
# A service a machine may simply not use: its missing connection is `info` (quiet hides it), never a warning.
OPTIONAL = ("github",)


def chosen(found: dict, areas: tuple[str, ...], cfg: dict) -> dict | None:
    for area in areas:
        c = T.connection_for(area, found.get("connections") or [], cfg)
        if c:
            return c
    return None


class ToilStep(Step):
    key = "toil"
    title = "toil (the service backend: its launcher and its Jira / Confluence / Bitbucket connections)"

    def detect(self, ctx: Context) -> dict:
        return ctx.det.toil(ctx.cfg)

    def check(self, ctx: Context, found: dict) -> None:
        from .jira import credentials
        k = self.key
        w = found.get("where") or {}
        hint = T.install_hint(ctx.cfg)
        if not w.get("found"):
            pinned = C.get(ctx.cfg, "toil.exe") or ""
            why = f"toil.exe = {pinned} does not resolve" if pinned else "toil not found on PATH, PATHEXT or the npm global prefix"
            ctx.add(k, "toil launcher", "fail", w.get("error") or why, hint, ("toil.exe",))
        elif w.get("rc") not in (0, None):
            ctx.add(k, "toil launcher", "fail", f"{w['path']} ({w.get('kind')}): {w.get('error') or 'did not start'}",
                    w.get("fix") or hint, ("toil.exe",))
        else:
            detail = f"{w['path']} ({w.get('kind')})" + (f" · {w['version']}" if w.get("version") else "")
            ctx.add(k, "toil launcher", "ok", detail + (f" · node {w['node_version']}" if w.get("node_version") else ""))
        if C.get(ctx.cfg, "pncli"):
            ctx.add(k, "retired pncli settings", "warn", "the config still has a `pncli` section (launcher, token key "
                    "names, verb templates); toil replaces all of it", "ad-setup --only toil removes it", ("pncli",))
        if found.get("error"):
            if w.get("found") and w.get("rc") in (0, None):
                ctx.add(k, "toil connections", "fail", found["error"], found.get("fix") or hint, ("toil.connections",))
            return
        jira_fallback = credentials(ctx)["token_source"] in ("env", "keyring")
        for name, areas, cost in SERVICES:
            c = chosen(found, areas, ctx.cfg)
            row = f"{name} connection"
            if c:
                where = f"{c.get('name')} ({c.get('area')}, {c.get('host') or 'no host'}, " \
                        f"writes {'on' if c.get('writes') else 'off'}, {c.get('definedIn') or 'file'})"
                ctx.add(k, row, "ok", where)
                if c.get("writes"):
                    ctx.add(k, f"{name} writes", "info", f"writes are on for {c.get('name')}: the ad-* extensions still "
                            "ask first; an MCP server registered with toil is not behind that gate")
                continue
            several = [x.get("name") for x in found.get("connections") or [] if x.get("area") in areas]
            pinned = next((f"toil.connections.{a} = {C.get(ctx.cfg, f'toil.connections.{a}')}" for a in areas
                           if C.get(ctx.cfg, f"toil.connections.{a}")), "")
            if pinned:
                ctx.add(k, row, "fail", f"{pinned}, which `toil connections list` does not name",
                        "ad-setup --only toil (pick a listed one)", (f"toil.connections.{areas[0]}",))
            elif len(several) > 1:
                ctx.add(k, row, "fail", f"several {name} connections and none is the default: {', '.join(several)}",
                        f"ad-setup --only toil (pick one), or `toil connections default <name>`",
                        (f"toil.connections.{areas[0]}",))
            elif name == "jira" and jira_fallback:
                ctx.add(k, row, "skip", "none in toil; JIRA_TOKEN or the jira step's keyring entry answers instead")
            elif name in OPTIONAL:
                ctx.add(k, row, "info", f"none in toil; {cost} needs one")
            else:
                ctx.add(k, row, "warn" if name != "jira" else "fail", f"no {name} connection in toil: {cost} cannot run",
                        f"`toil connections add <name> --area {areas[0]}` (a person, at a terminal: the token goes to "
                        "the OS credential store), then `ad-doctor --only toil`", (f"toil.connections.{areas[0]}",))

    def ask(self, ctx: Context, found: dict) -> None:
        cfg = ctx.cfg
        if C.get(cfg, "pncli"):
            cfg.pop("pncli", None)
            ctx.add(self.key, "retired pncli settings", "ok", "removed the `pncli` section from the config")
        w = found.get("where") or {}
        if not w.get("found") or w.get("rc") not in (0, None):     # missing OR present-but-will-not-start
            state = "was not found" if not w.get("found") else f"is at {w.get('path')} but does not start"
            ctx.say(f"  toil {state}. {T.install_hint(cfg)}")
            got = ctx.ask.ask("toil.exe", "full path to the toil launcher, or a clone's dist/toil.js (blank = not "
                              "installed yet)", C.get(cfg, "toil.exe") or "")
            if got:
                C.put(cfg, "toil.exe", textio.norm_path(got))
                found = self.detect(ctx)
                w = found.get("where") or {}
        if w.get("found") and w.get("rc") in (0, None) and w.get("kind") != "executable":
            C.put(cfg, "toil.exe", w["path"])      # pin the launcher we proved starts, so PATH changes cannot break it
        for name, areas, _cost in SERVICES:
            mine = [c for c in found.get("connections") or [] if c.get("area") in areas]
            if len(mine) < 2:
                continue
            current = C.get(cfg, f"toil.connections.{mine[0]['area']}") or next(
                (c["name"] for c in mine if c.get("isDefault")), "")
            got = ctx.ask.ask(f"toil.connections.{areas[0]}", f"which toil connection is {name}'s ("
                              + ", ".join(str(c.get("name")) for c in mine) + ")", current, confident=bool(current))
            pick = next((c for c in mine if c.get("name") == (got or "").strip()), None)
            if pick:
                C.put(cfg, f"toil.connections.{pick['area']}", pick["name"])
            elif got:
                ctx.add(self.key, f"{name} connection", "fail", f"{got} is not a {name} connection in toil",
                        "ad-setup --only toil and pick a listed one")

    def verify(self, ctx: Context) -> None:
        """Online only: `toil connections test <name>` for each connection the extensions use."""
        if not ctx.online:
            return
        found = self.detect(ctx)
        if found.get("error"):
            return
        for name, areas, _cost in SERVICES:
            c = chosen(found, areas, ctx.cfg)
            if not c:
                continue
            res = ctx.det.toil_test(str(c.get("name")), ctx.cfg)
            if res.get("ok"):
                ctx.add(self.key, f"{name} connection", "ok", f"{c.get('name')}: answered an authenticated read")
            else:
                ctx.add(self.key, f"{name} connection", "fail", f"{c.get('name')}: {res.get('error')}",
                        res.get("fix") or f"`toil connections login {c.get('name')}`", (f"toil.connections.{areas[0]}",))
