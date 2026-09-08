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

The desk rows (#134) answer the four questions the operator would otherwise discover the hard way:
are the registered checkouts still on the disk, is the catalogue fresh enough for `ad-fleet where`
to be believed, which projects cannot build their tile links yet, and what four tiles polling one
Jira token costs per hour. Every one of them is read from disk -- a doctor that opened a socket
would make `session-bootstrap` wait on Jira -- and every one is wrapped, because a half-written
sqlite file must not cost the operator the eight rows that were fine.
"""
from __future__ import annotations
import os
import time

from ..wizard import Context, Step
from ... import config as C
from ... import textio

YES_NO = ["yes", "no"]

# The build the #92 spike measured every flag and event shape against. Older is not refused --
# it is reported, because "your CLI predates what this was built on" is a fact an operator can act
# on and a guess about compatibility is not.
MEASURED_AGAINST = "1.0.81"

# A catalogue older than this is reported. A day, because the work it indexes is a day's work: an
# `ad-fleet where` that answers out of yesterday's index is not obviously wrong, which is what
# makes it worth a row rather than a crash.
CATALOGUE_STALE_S = 24 * 3600

# Requests an hour the poll may cost before the row says so. The defaults with four tiles come to
# 228 -- one Jira search a minute for all of them (60), a PR read per tile every two minutes (120),
# a refresh read per tile every five (48) -- so a normal desk passes and it is the eighth tile, or
# a shortened interval, that makes the number visible. It is the *shape* of the load that matters
# here: Jira publishes no number this could be compared against, and the tenant's real limit is
# only ever seen by a live client in its `X-RateLimit-*` headers.
POLLS_PER_HOUR_WARN = 300


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
        found.update(self._desk(ctx, repos))
        return found

    def _desk(self, ctx: Context, repos: list) -> dict:
        """The four #122 facts, all from disk: the catalogue, the tile facts, the tray, the polls."""
        return {"catalogue": self._catalogue(), "facts": self._facts(ctx, repos),
                "inbox": self._inbox(), "polls": self._polls(ctx, repos)}

    @staticmethod
    def _catalogue() -> dict:
        """`catalogue.stats()`, or why it could not be read. Never builds one.

        A missing file is answered without opening it, because `Catalogue.open` *creates* the
        database, and a doctor that quietly produced an empty catalogue would turn "never indexed"
        into "indexed and empty" -- the same row, the wrong hint.

        When the file is there it is opened through `Catalogue`, not through a second sqlite reader
        of our own, so the row reports exactly what a search would find. That includes the one
        thing `Catalogue.open` does write: a database built on the `LIKE` fallback and opened on an
        interpreter that now has FTS5 has its docs emptied rather than searched with an empty
        index, and the row then says "0 docs" and asks for the re-index, which is the truth.
        """
        from ...fleet.catalogue import CATALOGUE, Catalogue
        from ...fleet.registry import fleet_dir

        path = textio.norm_path(os.path.join(fleet_dir(), CATALOGUE))
        if not os.path.isfile(path):
            return {"path": path, "exists": False}
        cat = None
        try:
            cat = Catalogue.open(path)
            return {"exists": True, **cat.stats()}
        except Exception as e:                       # noqa: BLE001 - a report must not crash
            return {"path": path, "exists": True, "error": str(e)[:160]}
        finally:
            if cat is not None:
                cat.close()

    @staticmethod
    def _facts(ctx: Context, repos: list) -> list[dict]:
        """Per repo, the `AGENTS.md` keys its tile links are missing -- `links.MISSING_KEYS_HINT`.

        Read through the same two files the catalogue's allow-list names, and nothing else.

        The repository's path travels with its keys because the row's whole repair is an edit to a
        named file, and "add `ws_id` to AGENTS.md" is not actionable on a desk with six checkouts
        of projects whose folders differ by a suffix. The path is what the hint spells out.
        """
        from ...fleet import links as L

        out = []
        for repo in repos:
            path = textio.norm_path(getattr(repo, "path", "") or "")
            try:
                facts = C.project_facts(os.path.join(repo.path, "AGENTS.md"))
                rows = L.links_for(repo, facts, repo.state(), cfg=ctx.cfg)
                out.append({"name": repo.name, "path": path, "keys": L.missing_keys(rows)})
            except Exception as e:                   # noqa: BLE001
                out.append({"name": getattr(repo, "name", "?"), "path": path, "keys": [],
                            "error": str(e)[:120]})
        return out

    @staticmethod
    def _inbox() -> dict:
        """Which folders the tray watches, and whether each can be listed. No file is opened.

        `os.scandir` and one entry is the same probe `inbox.look` makes, so a folder that answers
        here is a folder the tray will really list -- `os.access` on Windows answers about the
        permission bits and not about the folder redirected onto a disconnected OneDrive.
        """
        from ...fleet import inbox as IN

        rows = []
        for folder in IN.default_folders():
            why = ""
            try:
                with os.scandir(textio.longpath(folder)) as entries:
                    next(entries, None)
            except OSError as e:                     # noqa: PERF203 - one folder, one reason
                why = (e.strerror or str(e))[:120]
            rows.append({"path": folder, "why": why})
        return {"folders": rows}

    @staticmethod
    def _polls(ctx: Context, repos: list) -> dict:
        """The poll settings, and what polling has actually cost today.

        `Poller.counts()` is persisted under `~/.agentdata/fleet/`, so the number survives a
        dashboard restarted at lunchtime. Building a `Poller` opens nothing and asks nobody: the
        four read paths are attributes it does not call until `tick`.
        """
        from ...fleet import poll as P
        from ...fleet.registry import Registry, RegistryError

        found = {"settings": P.settings(ctx.cfg), "repos": len(repos), "counts": {}}
        try:
            found["counts"] = P.Poller(Registry(), cfg=ctx.cfg).counts()
        except (RegistryError, OSError, ValueError):
            pass
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
        self._check_parent(ctx, found)
        self._check_catalogue(ctx, found)
        self._check_facts(ctx, found)
        self._check_inbox(ctx, found)
        self._check_polls(ctx, found)
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

    def _check_parent(self, ctx: Context, found: dict) -> None:
        """Are the registered checkouts still on the disk, and is the folder they live under?

        A separate row from `repos`, which asks whether each one is still a *project*. This one
        asks whether the disk is there at all, and it exists because the two fail together and are
        fixed apart: on the laptop a mapped drive that is not connected this morning makes every
        repository under it vanish at once, and four rows saying "no AGENTS.md any more" send the
        operator to re-run `ad-setup --project` in four folders that are perfectly fine.

        Nothing is removed, here or anywhere: a renamed folder and a disconnected drive look
        identical from here, and `scan.drift` refuses to guess for the same reason.
        """
        repos = found.get("repos") or []
        if not repos:
            ctx.add(self.key, "parent folder", "skip", "nothing registered yet",
                    "`ad-fleet quickstart <folder>` proposes every project under one folder",
                    keys=())
            return

        gone = [r for r in repos if not os.path.isdir(textio.longpath(r.path))]
        parents = {textio.norm_path(os.path.dirname(r.path)) for r in repos}
        missing_parents = sorted(p for p in parents if p and not os.path.isdir(textio.longpath(p)))
        if missing_parents:
            orphaned = [r for r in repos
                        if textio.norm_path(os.path.dirname(r.path)) in set(missing_parents)]
            ctx.add(self.key, "parent folder", "warn",
                    f"{', '.join(missing_parents[:3])} is not there: "
                    f"{len(orphaned)} of {len(repos)} registered checkouts were under it",
                    "reconnect the drive or restore the folder, then `ad-doctor` again; nothing is "
                    "removed for you, so the names the tiles use survive", keys=())
        elif gone:
            ctx.add(self.key, "parent folder", "warn",
                    f"{len(gone)} registered checkout(s) are not where the registry says: "
                    + ", ".join(sorted(r.name for r in gone)[:4]),
                    "`ad-fleet repo add --scan <folder>` proposes them again from where they are "
                    "now, or `ad-fleet repo rm <name>` if one is really gone", keys=())
        else:
            where = parents.pop() if len(parents) == 1 else f"{len(parents)} folders"
            ctx.add(self.key, "parent folder", "ok", f"{len(repos)} under {where}", keys=())

    def _check_catalogue(self, ctx: Context, found: dict) -> None:
        """One row that has to say two things: is it fresh, and which search is answering.

        The mode is in the detail every time, never only when it is the fallback. "Search found
        nothing" and "search is running on the LIKE scan because this interpreter's SQLite has no
        FTS5" look identical from a result set, and only one of them is a bug worth chasing.
        """
        cat = found.get("catalogue") or {}
        hint = ("`ad-fleet index` reads the allow-listed files of every registered repo once; "
                "`ad-fleet where <text>` then answers without opening a tab")
        if not cat.get("exists"):
            ctx.add(self.key, "catalogue", "warn", "not built yet", hint, keys=())
            return
        if cat.get("error"):
            ctx.add(self.key, "catalogue", "warn", f"{cat['path']}: {cat['error']}",
                    "delete that file and run `ad-fleet index --rebuild`; it is a cache of files "
                    "that are all still on the disk, so nothing is lost with it", keys=())
            return

        mode = "FTS5" if cat.get("fts") else "the LIKE fallback (no FTS5 in this SQLite)"
        body = f"{cat.get('docs', 0)} docs across {cat.get('projects', 0)} projects, {mode}"
        age = _age_of(cat.get("last_indexed") or "")
        if not cat.get("docs"):
            ctx.add(self.key, "catalogue", "warn", f"empty, {mode}", hint, keys=())
        elif age is None:
            ctx.add(self.key, "catalogue", "ok", body, keys=())
        elif age > CATALOGUE_STALE_S:
            ctx.add(self.key, "catalogue", "warn",
                    f"{body}, last indexed {cat['last_indexed']} ({int(age // 3600)}h ago)",
                    "`ad-fleet index` -- a catalogue older than the work in it answers `ad-fleet "
                    "where` out of yesterday, which is worse than answering nothing", keys=())
        else:
            ctx.add(self.key, "catalogue", "ok",
                    f"{body}, indexed {int(age // 60)}m ago", keys=())

    def _check_facts(self, ctx: Context, found: dict) -> None:
        """Which projects cannot build every tile link, and the exact key each one is missing.

        **This row carries no keys, and #134's acceptance criterion saying `--patch` prompts for
        them is a criterion this slice deliberately does not meet.** The deviation is recorded in
        the issue; the argument for it is that `Check.keys` are *prompt* keys, every one of which
        `Step.ask` writes into `~/.agentdata/config.json` with `C.put`, while every key
        `links.missing_keys` reports (`jira_board_id`, `report_id`, `ds_id`, `ws_id`,
        `bitbucket_repo`) is read only from one repository's own `AGENTS.md` through
        `config.project_facts` -- the config is never consulted for any of them. So a prompt here
        could not fix a single one of these rows by saving an answer; it could only fix them by
        editing N *other* repositories' files, which is the one thing the fleet does not do
        (HANDOFF.md, and `test_fleet_e2e.test_nothing_but_the_agent_wrote_the_repositories`).

        What that costs the operator is a row that reports a problem and offers no action, so the
        hint pays it back: it names the file per repository, the lines to add, and the fact that
        `--patch` will list this under `manual` rather than ask.
        """
        rows = found.get("facts") or []
        if not rows:
            return
        short = [r for r in rows if r.get("keys")]
        if short:
            named = "; ".join(f"{r['name']} needs {_keys(r['keys'])}" for r in short[:3])
            if len(short) > 3:
                named += f"; and {len(short) - 3} more"
            ctx.add(self.key, "facts", "warn",
                    f"{len(short)} of {len(rows)} projects cannot build every tile link: {named}",
                    self._facts_hint(short), keys=())
        else:
            ctx.add(self.key, "facts", "ok",
                    f"{len(rows)} projects supply the facts their tile links need", keys=())

    @staticmethod
    def _facts_hint(short: list[dict]) -> str:
        """The whole repair, written out by hand and by repository, because no answer performs it.

        Two repositories are spelled out in full rather than all of them: the hint is one cell of a
        table an operator reads on every session start, and a desk with eight half-filled projects
        would push the other rows off the screen. The rest are counted, and `ad-fleet show` is the
        verb that lists any one of them.
        """
        edits = []
        for r in short[:2]:
            where = textio.norm_path(os.path.join(r.get("path") or r["name"], "AGENTS.md"))
            # Every key, never the detail's shortened list: a hint an operator follows to the letter
            # and finds the row still warning is a hint that cost them a second `ad-doctor` to learn
            # what it had left out. There are five keys in `links.MISSING_KEYS_HINT` in total.
            edits.append(f"{where} needs " + ", ".join(f"`- {k}: <value>`" for k in r["keys"]))
        rest = f"; then the other {len(short) - 2}" if len(short) > 2 else ""
        return ("`ad-setup --patch` cannot repair this row and lists it under `manual`: the fix is "
                "a line in another repository's own AGENTS.md facts block, and no setting this "
                "wizard saves is read for these keys. Add them by hand, per repository -- "
                + "; ".join(edits) + rest
                + " -- then `ad-doctor` again. `ad-fleet show <project>` lists what one tile is "
                  "still missing.")

    def _check_inbox(self, ctx: Context, found: dict) -> None:
        """Can the tray list the folder the browser saves into.

        The row says "names only" because that is the safety rule of #132 and the thing an operator
        asked to point this at a folder full of bank statements will want to read.
        """
        folders = (found.get("inbox") or {}).get("folders")
        if folders is None:
            return
        if not folders:
            ctx.add(self.key, "inbox", "warn", "no Downloads folder found",
                    "`ad-fleet inbox --folder <path>` names one; the tray is how an export the "
                    "browser saved reaches a project without a copy-paste", keys=())
            return
        refused = [f for f in folders if f["why"]]
        if refused:
            ctx.add(self.key, "inbox", "warn",
                    "; ".join(f"{f['path']} cannot be listed: {f['why']}" for f in refused[:2]),
                    "give this account read access to it, or `ad-fleet inbox --folder <path>` with "
                    "a folder it can list; no file in either is ever opened", keys=())
        else:
            ctx.add(self.key, "inbox", "ok",
                    ", ".join(f["path"] for f in folders) + " (names only; no file is opened)",
                    keys=())

    def _check_polls(self, ctx: Context, found: dict) -> None:
        """What N tiles polling one token costs an hour, and what it cost today.

        The numbers are the fleet's own counters. Jira's real ceiling is in the `X-RateLimit-*`
        headers epic #121's client reads on every response, and those are only ever seen by a live
        client mid-run -- a doctor that went and asked would spend a request to report on spending
        requests. So the row reports the load it can prove offline: the arithmetic of the intervals
        against the tile count, today's spend per source, and every time the poll stood down having
        nearly spent its allowance for the day.

        That allowance is the poll's ceiling on *itself*, and the row says so in those words. It is
        not shared with an `ad-jira changelog` the operator is waiting on: that runs in another
        process with its own `RequestBudget` object, and nothing here can hold requests back for it
        (`poll.py`'s module docstring records why, and why believing otherwise was worse than
        knowing there is no protection). What actually keeps N tiles off one human's token is the
        single Jira search per interval however many tiles there are, and the tenant's own rate
        limiter -- so those are what the detail names.
        """
        polls = found.get("polls") or {}
        settings = polls.get("settings") or {}
        if not settings:
            return
        keys = ("fleet.poll.enabled", "fleet.poll.jira.interval")
        live = [s for s, v in settings.items() if v["on"]]
        if not live:
            ctx.add(self.key, "token budget", "ok",
                    "polling is off; the ticket, PR and refresh cells stay empty", keys=keys)
            return

        # One search covers every tile, so Jira is charged once however many tiles there are; the
        # PR and refresh reads are per tile, which is where the tile count actually shows up.
        tiles = max(1, int(polls.get("repos") or 0))
        per_hour, pieces = 0, []
        for source, per_tile in (("jira", 1), ("pr", tiles), ("powerbi", tiles)):
            conf = settings.get(source) or {}
            if not conf.get("on"):
                continue
            each = per_tile * (3600 // max(1, int(conf.get("interval") or 1)))
            per_hour += each
            pieces.append(f"{source} {each}")
        detail = (f"{tiles} tile(s) ≈ {per_hour} requests/hour on one token "
                  f"({', '.join(pieces)}; one Jira search covers every tile, git is local "
                  f"and costs nothing)")

        counts = polls.get("counts") or {}
        spent = counts.get("requests") or {}
        if counts.get("total"):
            detail += (f"; today {counts['total']} "
                       + ", ".join(f"{n} {s}" for s, n in sorted(spent.items()) if n))
        stood_down = sum((counts.get("stood_down") or {}).values())
        slow_down = ("raise `fleet.poll.jira.interval`, or turn a source off with "
                     "`fleet.poll.<source>: false`; a longer interval makes the day's allowance "
                     "last, and it is the tenant's rate limiter, not this allowance, that a "
                     "command you are waiting on is really competing with")
        if stood_down:
            ctx.add(self.key, "token budget", "warn",
                    f"{detail}; the poll stood down {stood_down} time(s) today having nearly spent "
                    "its own allowance for the day (it reserves nothing for another process)",
                    slow_down, keys=keys)
        elif per_hour > POLLS_PER_HOUR_WARN:
            ctx.add(self.key, "token budget", "warn", detail,
                    f"over {POLLS_PER_HOUR_WARN} requests an hour against one human's token, and "
                    f"every tile added makes it worse: " + slow_down, keys=keys)
        else:
            ctx.add(self.key, "token budget", "ok", detail, keys=keys)

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

        self._ask_polls(ctx)

    def _ask_polls(self, ctx: Context) -> None:
        """The two answers behind the `token budget` row.

        Read from the config rather than from `found`, because `--patch` reaches this step through
        a failing row and the whole wizard reaches it with no fleet at all, and the current value
        has to be the default in both. One question for the whole poll and one for the interval
        that costs a Jira request: the other three sources are a config line away and asking four
        interval questions in the common path is how a wizard gets skipped.
        """
        from ...fleet import poll as P

        polls = P.settings(ctx.cfg)
        on = any(v["on"] for v in polls.values())
        ctx.say("Polling fills the ticket, PR and refresh cells on each tile, so a browser tab is "
                "opened to act rather than to check. One Jira search covers every tile.")

        answer = ctx.ask.ask("fleet.poll.enabled",
                             "Poll each project's own systems for the tile cells?",
                             default="yes" if on else "no", choices=YES_NO)
        C.put(ctx.cfg, "fleet.poll.enabled", _yes(answer, on))

        answer = ctx.ask.ask("fleet.poll.jira.interval",
                             "Seconds between Jira polls (one search, on your token, however many "
                             "tiles are open)", default=str(polls["jira"]["interval"]))
        C.put(ctx.cfg, "fleet.poll.jira.interval", _int(answer, polls["jira"]["interval"]))


def _keys(keys: list) -> str:
    """The detail's shortened key list. The full one is in the hint, which is what gets followed."""
    if len(keys) <= 4:
        return ", ".join(keys)
    return ", ".join(keys[:4]) + f", +{len(keys) - 4} more"


def _ping(port: int) -> bool:
    from ...fleet import opener

    return opener.ping(port, timeout=1.0)


def _age_of(when: str) -> float | None:
    """Seconds since a catalogue timestamp, or None when there is not one to measure.

    `catalogue.index` stamps `last_indexed` with `time.strftime` and no `gmtime`, so it is local
    time and `mktime` is what turns it back. Reading it as UTC would make a fresh index look an
    offset old -- an hour in Britain in summer, thirteen in Auckland -- and the row would ask for a
    re-index that had just happened.
    """
    try:
        parsed = time.strptime(str(when)[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None
    try:
        return max(0.0, time.time() - time.mktime(parsed))
    except (OverflowError, ValueError):
        return None


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
