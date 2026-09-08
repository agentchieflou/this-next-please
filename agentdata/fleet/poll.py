"""The project's own state, gathered on a timer, so a browser tab is opened to act and never to check.

Most visits to those eight bookmarks are *checks*: did the overnight refresh finish, is the PR still
open, did the ticket move, is the working tree dirty. Every one of them costs a window switch, a
bookmark hunt and a page load to learn a single word -- and the answer is usually "no change". This
module gets those four words onto the tile so the operator reads them all at once, and opens a tab
only when there is something to do on the other side of it.

Four rules, each of which is a way this could have gone wrong on a real desk.

**One JQL, not one call per tile.** Four tiles asking Jira separately is four searches a minute
against one human's token, which is how a shared tenant starts rate-limiting a whole team. The Jira
poll collects every registered repo's `active_ticket` and asks once, whatever the tile count.

**The poll gives way to the work.** It shares epic #121's `RequestBudget` with whatever else is
running on that token, so a poll can never be the reason an `ad-jira changelog` runs out of requests
halfway through a 3,000-issue pull. When the budget is down to its last `BUDGET_FLOOR` requests the
poll stands down and says so in the cell, because a stale ticket status costs nothing and a truncated
changelog costs the operator an hour.

**A failed poll greys the cell; it never invents one.** The last good value stays, `age_s` says how
old it is and `error` says what went wrong -- so a cell reading `Done · 40m` beside "Jira: HTTP 502"
is obviously stale, where a cell silently reading `Done` when the poll has been failing since
breakfast is a lie the operator would act on. A later poll that succeeds clears the error.

**A change is announced once.** Deltas become events on #94's contract -- `project.ticket_changed`,
`project.refresh_finished`, `project.pr_merged` -- and the fingerprint of what was announced is
written to disk, so the same change polled again, or polled after `ad-fleet serve` restarts,
produces nothing. The *first* observation of a repository announces nothing at all, for the reason
`notify.py` gives: attaching to four projects must not toast four things that happened last week.

Read-only throughout, through the paths that already exist: `jira_api` on the token pncli stores,
pncli's own `bitbucket get-pr` read verb (refused outright if `pncli.is_write` disagrees), the Power
BI REST refresh history `pbi-verify-service` reads, and `git status` in the repo's own directory.
Nothing here writes to a repository, and the only thing it writes at all is its own counters under
`~/.agentdata/fleet/`.
"""
from __future__ import annotations
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import config as C
from .. import textio
from ..connectors.jira_http import JiraBudgetError, RequestBudget
from . import events as E
from .links import GUID, TICKET
from .registry import fleet_dir

# Per-source seconds between polls. Jira is the ticket the operator is working *now*, so a minute;
# a PR does not change while nobody is reviewing it; a refresh that takes twenty minutes does not
# need asking about twice a minute; git is local, free, and the one that changes under your hands.
DEFAULT_INTERVALS = {"jira": 60, "pr": 120, "powerbi": 300, "git": 30}
SOURCES = tuple(DEFAULT_INTERVALS)

# Source -> the tile cell it fills. Two names because the source is *where the answer comes from*
# and the cell is *what the operator is looking at*: "powerbi" is a system, "refresh" is the
# question, and `state_for` is read by a renderer that cares about the question.
CELLS = {"jira": "ticket", "pr": "pr", "powerbi": "refresh", "git": "git"}

# The kinds this module emits, on #94's contract. They are listed in `events.KINDS` too -- that
# tuple is the contract and this one is what a caller filtering the stream can import by name.
TICKET_CHANGED = "project.ticket_changed"
REFRESH_FINISHED = "project.refresh_finished"
PR_MERGED = "project.pr_merged"
KINDS = (TICKET_CHANGED, REFRESH_FINISHED, PR_MERGED)

# Requests the poll refuses to eat into, so the budget it shares always has something left for the
# command a human is waiting on. Sized above one changelog page batch on purpose: standing down a
# minute early is invisible, and standing down a minute late turns somebody's pull into a partial.
BUDGET_FLOOR = 50

# What the Jira search asks for -- the four things the cell shows and nothing else. A wider field
# list is a bigger response on every tick for data no one reads.
JIRA_FIELDS = ("status", "assignee", "updated", "summary")

STATE_FILE = "poll.json"
STATE_VERSION = 1

# A refresh is *finished* only in these; "Unknown" and "InProgress" are the states the operator is
# waiting through, and toasting them would announce the wait rather than its end.
REFRESH_DONE = ("Completed", "Succeeded", "Failed", "Disabled", "Cancelled")
PR_MERGED_STATES = ("MERGED", "MERGE", "MERGED_BY_REVIEWER")

# `.../pull-requests/42` on Cloud and Server alike; `/pullrequests/42` is the older Server spelling.
_PR_ID = re.compile(r"/pull-?requests?/(\d+)", re.I)
_GIT_AB = re.compile(r"^# branch\.ab \+(\d+) -(\d+)")


@dataclass
class Poll:
    """One cell of one tile: what was last learned, how old it is, and why it is grey.

    `value` is a dict that always carries a `"text"` key -- the one line the cell shows -- beside the
    fields a renderer may want to lay out itself (`status`, `assignee`, `ahead`, ...). It is *kept*
    across a failure on purpose: the pair (`value`, `age_s`) is honest where a blanked cell would
    lose the last thing known and a silently retained cell would look current.
    """

    source: str
    interval: int = 0
    last_at: float = 0.0          # when a poll was last attempted, successful or not
    last_ok: float = 0.0          # when `value` was obtained; 0 means never
    value: dict = field(default_factory=dict)
    age_s: float = 0.0
    error: str = ""

    @property
    def cell(self) -> str:
        return CELLS.get(self.source, self.source)

    @property
    def grey(self) -> bool:
        return bool(self.error)

    def to_json(self) -> dict:
        return {"source": self.source, "interval": self.interval, "value": self.value,
                "age_s": round(self.age_s, 1), "error": self.error, "grey": self.grey}


# ------------------------------------------------------------------------------- configuration


def settings(cfg: dict | None = None) -> dict:
    """`{source: {"on": bool, "interval": int}}` from the `fleet.poll.*` block.

    Three spellings, because the operator reaches for whichever is shortest: `fleet.poll.enabled:
    false` turns everything off, `fleet.poll.jira: false` turns one source off, and
    `fleet.poll.jira: {"enabled": true, "interval": 300}` slows one down. An interval that is not a
    number falls back to the default rather than raising -- a typo in a config block must not stop
    the dashboard from starting.
    """
    block = C.get(C.load() if cfg is None else cfg, "fleet.poll") or {}
    if not isinstance(block, dict):
        block = {}
    every = block.get("enabled", True) is not False
    out = {}
    for source in SOURCES:
        raw = block.get(source)
        on, interval = True, None
        if isinstance(raw, dict):
            on, interval = raw.get("enabled", True) is not False, raw.get("interval")
        elif raw is not None:
            on = bool(raw)
        try:
            interval = max(1, int(interval))
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVALS[source]
        out[source] = {"on": bool(every and on), "interval": interval}
    return out


# ------------------------------------------------------------------------------- the poller


class Poller:
    """Holds one `Poll` per repo per source, and turns the deltas between ticks into events.

    The four read paths are attributes rather than constructor arguments, the same seam
    `jira_api.Jira.wall` uses and for the same reason: `__init__`'s signature is a contract other
    slices are written against, and a test that needs to steer a source replaces the attribute.
    `jira_client` is handed the shared budget so no substitute can accidentally forget to share it.
    """

    def __init__(self, registry, cfg: dict | None = None, now: Callable[[], float] = time.time,
                 budget: RequestBudget | None = None, *, state_path: str | None = None):
        self.registry = registry
        self.cfg = C.load() if cfg is None else cfg
        self.now = now
        self.budget = budget or RequestBudget()
        self.settings = settings(self.cfg)
        self.state_path = state_path or os.path.join(fleet_dir(), STATE_FILE)

        self.jira_client: Callable[[RequestBudget], Any] = default_jira_client
        self.pr_reader: Callable[..., dict] = read_pr
        self.refresh_reader: Callable[..., dict] = read_refresh
        self.git_reader: Callable[..., dict] = read_git

        self.polls: dict[str, dict[str, Poll]] = {}
        self._seen: dict[str, dict[str, str]] = {}
        self._counts: dict[str, dict[str, int]] = {"requests": {}, "errors": {}, "stood_down": {}}
        self._day = ""
        self._load()

    # ---- what the dashboard reads -------------------------------------------------------------

    def state_for(self, repo_name: str) -> dict:
        """`{ticket, pr, refresh, git}` for one tile, with `age_s` recomputed against now.

        Ages are recomputed here rather than trusted from the last tick: the page is refreshed far
        more often than the slowest source is polled, and a Power BI cell that stayed at "0s" for
        five minutes would be the exact wrong impression -- it is the *age* that tells the operator
        whether to believe the word beside it.
        """
        now = self.now()
        out = {}
        for source in SOURCES:
            poll = self._poll(repo_name, source)
            poll.age_s = max(0.0, now - poll.last_ok) if poll.last_ok else 0.0
            out[poll.cell] = poll
        return out

    def counts(self) -> dict:
        """What the polling cost today, for `ad-fleet status --polls`.

        Requests, failures and stand-downs per source, plus the day they belong to, so the number is
        never a running total from an unknown start. Persisted, because a dashboard restarted at
        lunchtime reporting "0 requests" would understate the morning by a few hundred.
        """
        self._roll_day(self.now())
        return {"day": self._day,
                "requests": {s: self._counts["requests"].get(s, 0) for s in SOURCES},
                "errors": {s: self._counts["errors"].get(s, 0) for s in SOURCES},
                "stood_down": {s: self._counts["stood_down"].get(s, 0) for s in SOURCES},
                "total": sum(self._counts["requests"].values())}

    # ---- the tick -----------------------------------------------------------------------------

    def tick(self, now: float | None = None) -> list[dict]:
        """Poll whatever is due, and return the events that produced. Never raises.

        A source that fails greys its cells and the tick carries on: one unreachable system must not
        stop the other three from answering, and the dashboard's loop has nothing useful to do with
        an exception except swallow it one level higher.
        """
        now = self.now() if now is None else float(now)
        self._roll_day(now)
        repos = list(self.registry.sorted())
        out: list[dict] = []
        out.extend(self._tick_jira(repos, now))
        for repo in repos:
            out.extend(self._tick_pr(repo, now))
            out.extend(self._tick_powerbi(repo, now))
            out.extend(self._tick_git(repo, now))
        self._save()
        return out

    # ---- Jira: one search for every tile -------------------------------------------------------

    def _tick_jira(self, repos: list, now: float) -> list[dict]:
        """One JQL over every active ticket, or none at all.

        The search covers *all* the active tickets whenever *any* repo is due, rather than only the
        due ones: the request costs the same either way, so narrowing it would buy nothing and make
        four tiles cost up to four searches on a tick where their timers had drifted apart.
        """
        conf = self.settings["jira"]
        if not conf["on"]:
            return []
        active = [(repo, key) for repo, key in ((r, _active_ticket(r)) for r in repos) if key]
        if not active or not any(self._due(r.name, "jira", now) for r, _ in active):
            return []

        short = self._budget_short()
        if short:
            for repo, _key in active:
                self._stand_down(repo.name, "jira", now, short)
            return []

        keys = sorted({key for _repo, key in active})
        jql = "key in (" + ", ".join(keys) + ")"
        spent_before = self.budget.requests
        try:
            client = self.jira_client(self.budget)
            issues = client.search(jql, list(JIRA_FIELDS), max_results=len(keys))
        except JiraBudgetError as e:
            # The budget ran out mid-search rather than before it. Same answer, same words: this is
            # a stand-down and not a Jira failure, and calling it one would send somebody to look at
            # a status page that is green.
            for repo, _key in active:
                self._stand_down(repo.name, "jira", now, f"standing down: {e}")
            return []
        except Exception as e:                    # noqa: BLE001 - any failure greys, none is fatal
            for repo, _key in active:
                self._fail(repo.name, "jira", now, _why(e))
            return []
        finally:
            # The budget's own counter, not `client.stats.requests`: `stats` mirrors the *shared*
            # budget's running total, so reading it as this poll's cost reported every request any
            # command had made today. A failed search still spent what it spent, hence `finally`.
            self._spent("jira", self.budget.requests - spent_before)

        found = {str(i.get("key") or "").upper(): i for i in issues or []}
        out: list[dict] = []
        for repo, key in active:
            issue = found.get(key)
            if issue is None:
                self._fail(repo.name, "jira", now,
                           f"Jira returned nothing for {key}: it may be deleted, moved, or not "
                           "visible to this token")
                continue
            value = _ticket_value(key, issue)
            self._ok(repo.name, "jira", now, value)
            out.extend(self._announce(repo, "jira", f"{value['status']}|{value['assignee']}",
                                      TICKET_CHANGED, key, lambda v=value: {
                                          "key": v["key"], "status": v["status"],
                                          "assignee": v["assignee"], "updated": v["updated"]}))
        return out

    # ---- the per-repo sources -------------------------------------------------------------------

    def _tick_pr(self, repo, now: float) -> list[dict]:
        if not self.settings["pr"]["on"] or not self._due(repo.name, "pr", now):
            return []
        state = repo.state()
        url = str(state.get("pr_url") or "").strip()
        if not url:
            self._idle(repo.name, "pr", now)
            return []
        try:
            answer = self.pr_reader(repo, state, self.cfg) or {}
            self._spent("pr", 1)
        except Exception as e:                    # noqa: BLE001 - grey, with the tool's own words
            self._fail(repo.name, "pr", now, _why(e))
            return []
        value = _pr_value(url, answer)
        self._ok(repo.name, "pr", now, value)
        if value["state"].upper() not in PR_MERGED_STATES:
            # Every other transition updates the cell and stays quiet: the contract has one PR kind,
            # and "opened" is already `pr_open` from `.agent/state.json`.
            self._remember(repo.name, "pr", value["state"])
            return []
        return self._announce(repo, "pr", value["state"], PR_MERGED, _active_ticket(repo),
                              lambda v=value: {"url": v["url"], "state": v["state"], "id": v["id"]})

    def _tick_powerbi(self, repo, now: float) -> list[dict]:
        if not self.settings["powerbi"]["on"] or not self._due(repo.name, "powerbi", now):
            return []
        facts = _facts(repo)
        ws, ds = _guid(facts.get("ws_id")), _guid(facts.get("ds_id"))
        if not ws or not ds:
            self._idle(repo.name, "powerbi", now)
            return []
        try:
            answer = self.refresh_reader(repo, facts, self.cfg) or {}
            self._spent("powerbi", 1)
        except Exception as e:                    # noqa: BLE001
            self._fail(repo.name, "powerbi", now, _why(e))
            return []
        value = _refresh_value(answer)
        self._ok(repo.name, "powerbi", now, value)
        if value["status"] not in REFRESH_DONE:
            self._remember(repo.name, "powerbi", f"{value['status']}|{value['end']}")
            return []
        return self._announce(repo, "powerbi", f"{value['status']}|{value['end']}",
                              REFRESH_FINISHED, _active_ticket(repo), lambda v=value: {
                                  "status": v["status"], "end": v["end"], "type": v["type"],
                                  "workspace": ws, "dataset": ds})

    def _tick_git(self, repo, now: float) -> list[dict]:
        """Local, free, and eventless: nothing in #94's contract announces a dirty tree, and a toast
        every time the operator saves a file is the notification they would turn off first."""
        if not self.settings["git"]["on"] or not self._due(repo.name, "git", now):
            return []
        try:
            answer = self.git_reader(repo) or {}
        except Exception as e:                    # noqa: BLE001
            self._fail(repo.name, "git", now, _why(e))
            return []
        self._ok(repo.name, "git", now, _git_value(answer))
        return []

    # ---- cells ---------------------------------------------------------------------------------

    def _poll(self, repo_name: str, source: str) -> Poll:
        cells = self.polls.setdefault(repo_name, {})
        if source not in cells:
            cells[source] = Poll(source=source, interval=self.settings[source]["interval"])
        return cells[source]

    def _due(self, repo_name: str, source: str, now: float) -> bool:
        poll = self._poll(repo_name, source)
        return not poll.last_at or (now - poll.last_at) >= poll.interval

    def _ok(self, repo_name: str, source: str, now: float, value: dict) -> None:
        poll = self._poll(repo_name, source)
        poll.last_at = poll.last_ok = now
        poll.value, poll.error, poll.age_s = value, "", 0.0

    def _fail(self, repo_name: str, source: str, now: float, error: str) -> None:
        """Grey the cell and keep the value. `last_ok` is untouched, so `age_s` keeps growing."""
        poll = self._poll(repo_name, source)
        poll.last_at, poll.error = now, error[:300]
        poll.age_s = max(0.0, now - poll.last_ok) if poll.last_ok else 0.0
        self._counts["errors"][source] = self._counts["errors"].get(source, 0) + 1

    def _stand_down(self, repo_name: str, source: str, now: float, why: str) -> None:
        """Not a failure: the poll chose not to spend. The cell greys with the reason and backs off
        for a full interval, so a busy budget is not re-tested on every pass of the loop."""
        poll = self._poll(repo_name, source)
        poll.last_at, poll.error = now, why[:300]
        poll.age_s = max(0.0, now - poll.last_ok) if poll.last_ok else 0.0
        self._counts["stood_down"][source] = self._counts["stood_down"].get(source, 0) + 1

    def _idle(self, repo_name: str, source: str, now: float) -> None:
        """There is nothing to ask about -- no PR yet, no dataset declared. An empty cell, not grey:
        a repository with no Power BI model is not a repository whose Power BI is broken."""
        poll = self._poll(repo_name, source)
        poll.last_at, poll.value, poll.error, poll.age_s = now, {"text": ""}, "", 0.0

    # ---- deltas and events -----------------------------------------------------------------------

    def _announce(self, repo, source: str, fingerprint: str, kind: str, ticket: str,
                  data: Callable[[], dict]) -> list[dict]:
        """One event per real change, and nothing on the first sighting.

        The fingerprint is recorded **after** the append succeeds. `events.append` refuses to write
        while `ad-state` holds the repo's stream lock, and remembering first would turn that
        ordinary contention into a change nobody is ever told about -- whereas re-announcing on the
        next tick is exactly what the retry is for.
        """
        seen = self._seen.setdefault(repo.name, {})
        if seen.get(source) == fingerprint:
            return []
        if source not in seen:
            seen[source] = fingerprint          # first sighting: the baseline, not news
            return []
        event = E.event(repo.name, kind, data(), ticket=ticket or "")
        try:
            E.append(repo.name, [event])
        except OSError:
            return []                            # the stream is held; try again next tick
        seen[source] = fingerprint
        return [event]

    def _remember(self, repo_name: str, source: str, fingerprint: str) -> None:
        """Record a state that is not worth an event, so the eventual change is measured from it."""
        self._seen.setdefault(repo_name, {})[source] = fingerprint

    # ---- budget --------------------------------------------------------------------------------

    def _budget_short(self) -> str:
        """The stand-down sentence, or "" when there is room. Says the numbers, because "the budget
        is short" is not something an operator can do anything with."""
        left = self.budget.remaining_requests()
        if left > BUDGET_FLOOR:
            return ""
        return (f"standing down: {left} of {self.budget.max_requests} requests left on the shared "
                f"budget, which is reserved for the command you are waiting on")

    def _spent(self, source: str, n: int) -> None:
        self._counts["requests"][source] = self._counts["requests"].get(source, 0) + max(0, int(n))

    # ---- the counters and fingerprints on disk ---------------------------------------------------

    def _roll_day(self, now: float) -> None:
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if self._day and self._day != today:
            self._counts = {"requests": {}, "errors": {}, "stood_down": {}}
        self._day = today

    def _load(self) -> None:
        try:
            saved = json.loads(textio.read_text(self.state_path))
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict) or saved.get("version") != STATE_VERSION:
            return
        self._day = str(saved.get("day") or "")
        for bucket in ("requests", "errors", "stood_down"):
            got = saved.get(bucket)
            if isinstance(got, dict):
                self._counts[bucket] = {k: int(v) for k, v in got.items() if str(v).lstrip("-").isdigit()}
        seen = saved.get("seen")
        if isinstance(seen, dict):
            self._seen = {str(r): {str(s): str(f) for s, f in (c or {}).items()}
                          for r, c in seen.items() if isinstance(c, dict)}

    def _save(self) -> None:
        payload = {"version": STATE_VERSION, "day": self._day, "seen": self._seen,
                   **{k: self._counts[k] for k in ("requests", "errors", "stood_down")}}
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            textio.write_text(self.state_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        except OSError:
            pass          # a dashboard that cannot write its counters still polls


# ---------------------------------------------------------------------- the default read paths


def default_jira_client(budget: RequestBudget):
    """A `Jira` on the token pncli already stores, sharing `budget`, and costing nothing to build.

    `detect_flavor` is deliberately not the first choice: it confirms the flavour with a `/myself`,
    which on a sixty-second timer is 1,440 requests a day spent asking who we are. The flavour
    `ad-jira whoami` recorded is used when it is there, and the detection runs -- once -- only when
    it is not.
    """
    from ..connectors import jira_api as J

    cfg = C.load()
    creds = J.load_credentials(cfg)
    kind, auth, api = (C.get(cfg, f"jira.{k}") for k in ("flavor", "auth", "api"))
    if kind and auth and api:
        return J.Jira(creds, J.Flavor(str(kind), str(auth), str(api)), budget=budget)
    client, _me = J.detect_flavor(creds, cfg, budget=budget)
    J.remember_flavor(cfg, client)
    C.save(cfg)
    return client


def read_pr(repo, state: dict, cfg: dict | None = None) -> dict:
    """The PR's state through pncli's `bitbucket get-pr`, refusing anything that is not a read.

    The option names are still `TODO(HANDOFF)` in `skills/bitbucket-pr`, so this can fail on a
    machine where they turn out to be spelled differently -- and that is survivable by design: the
    failure greys the cell and carries pncli's own usage error, which names the option it wanted,
    rather than putting a guessed PR state on the tile.

    `pncli.is_write` decides whether the call is allowed at all. A poll that could reach a write verb
    is a poll that could merge somebody's pull request on a timer.
    """
    from ..connectors import pncli

    url = str(state.get("pr_url") or "").strip()
    match = _PR_ID.search(url)
    if not match:
        raise ValueError(f"cannot tell the PR id from {url!r}; expected .../pull-requests/<n>")
    args = ["bitbucket", "get-pr", "--id", match.group(1)]
    slug = _repo_slug(url)
    if slug:
        args += ["--repo", slug]
    if pncli.is_write(args):
        raise ValueError(f"refusing to poll with a pncli write verb: {' '.join(args[:2])}")
    payload, _elapsed = pncli.run(args, timeout=60, cfg=cfg)
    records = pncli.extract_records(payload)
    return records[0] if records else {}


def read_refresh(repo, facts: dict, cfg: dict | None = None) -> dict:
    """The latest row of the dataset's refresh history -- the same REST read `pbi-verify-service` does.

    One row, not five: the tile answers "did it finish", and a history is what `ad-pbi refresh
    --history` is for.
    """
    from ..pbi.client import FabricClient
    from ..pbi.refresh import get_refresh_history

    rows = get_refresh_history(str(facts.get("ws_id")), str(facts.get("ds_id")),
                               FabricClient(), top=1)
    return rows[0] if rows else {}


def read_git(repo) -> dict:
    """Branch, ahead/behind and dirty, from one `git status` in the repo's own directory.

    `--porcelain=v2 --branch` rather than parsing `git status`'s prose: the prose is localised, and a
    laptop set to French reports "Votre branche est en avance de 2 commits" where the parser wanted
    "ahead". `--no-optional-locks` because a status on a repository PyCharm is indexing must not
    take the index lock out from under it.
    """
    from .. import proc

    argv = ["git", "--no-optional-locks", "status", "--porcelain=v2", "--branch"]
    code, out, err, _elapsed = proc.run(argv, cwd=repo.path, timeout=30)
    if code != 0:
        raise OSError((err or out or f"git exited {code}").strip().splitlines()[-1][:200])
    branch, ahead, behind, dirty = "", 0, 0, False
    for line in out.splitlines():
        if not line.startswith("#"):
            dirty = dirty or bool(line.strip())
            continue
        if line.startswith("# branch.head "):
            branch = line[len("# branch.head "):].strip()
        m = _GIT_AB.match(line)
        if m:
            ahead, behind = int(m.group(1)), int(m.group(2))
    return {"branch": branch, "ahead": ahead, "behind": behind, "dirty": dirty}


# ------------------------------------------------------------------------------- small helpers


def _active_ticket(repo) -> str:
    key = str((repo.state() or {}).get("active_ticket") or "").strip().upper()
    return key if TICKET.match(key) else ""


def _facts(repo) -> dict:
    return C.project_facts(os.path.join(repo.path, "AGENTS.md"))


def _guid(value) -> str:
    text = str(value or "").strip()
    return text if GUID.match(text) else ""


def _why(exc: BaseException) -> str:
    """One line for the cell: the message, and the hint when the error carries one.

    Every error in this codebase carries a hint saying what to do next, and a cell that says
    "HTTP 401" without "re-run ad-setup --only pncli" sends the operator to a search engine.
    """
    msg = str(exc).strip() or exc.__class__.__name__
    hint = str(getattr(exc, "hint", "") or "").strip()
    return f"{msg} -- {hint}" if hint else msg


def _ticket_value(key: str, issue: dict) -> dict:
    f = issue.get("fields") or {}
    status = str((f.get("status") or {}).get("name") or "")
    assignee = str((f.get("assignee") or {}).get("displayName") or "")
    return {"text": status or "(no status)", "key": key, "status": status, "assignee": assignee,
            "updated": str(f.get("updated") or "")[:19],
            "summary": str(f.get("summary") or "").strip()[:200]}


def _pr_value(url: str, answer: dict) -> dict:
    state = str(answer.get("state") or answer.get("status") or "").strip().upper()
    from_url = _PR_ID.search(url)
    ident = str(answer.get("id") or (from_url.group(1) if from_url else ""))
    return {"text": state or "(unknown)", "state": state, "id": ident, "url": url,
            "title": str(answer.get("title") or "").strip()[:200]}


def _refresh_value(answer: dict) -> dict:
    status = str(answer.get("status") or "").strip() or "Unknown"
    return {"text": status, "status": status, "end": str(answer.get("endTime") or "")[:19],
            "start": str(answer.get("startTime") or "")[:19],
            "type": str(answer.get("refreshType") or "")}


def _git_value(answer: dict) -> dict:
    branch = str(answer.get("branch") or "")
    ahead, behind = int(answer.get("ahead") or 0), int(answer.get("behind") or 0)
    dirty = bool(answer.get("dirty"))
    bits = [branch or "(no branch)"]
    if ahead:
        bits.append(f"+{ahead}")
    if behind:
        bits.append(f"-{behind}")
    if dirty:
        bits.append("dirty")
    return {"text": " ".join(bits), "branch": branch, "ahead": ahead, "behind": behind,
            "dirty": dirty}


def _repo_slug(url: str) -> str:
    """`<workspace>/<slug>` out of a Bitbucket PR URL, or "" when the shape is not the Cloud one.

    Server nests the repository under `/projects/<KEY>/repos/<slug>`, which is not the same two
    segments, so it returns "" and pncli falls back to whatever repository its own config names --
    better than passing a `--repo` that means something else.
    """
    parts = [p for p in str(url).split("://")[-1].split("/") if p]
    if len(parts) >= 4 and parts[3].lower().startswith("pull"):
        return f"{parts[1]}/{parts[2]}"
    return ""
