"""The project's own state, gathered on a timer, so a browser tab is opened to act and never to check.

Most visits to those eight bookmarks are *checks*: did the overnight refresh finish, is the PR still
open, did the ticket move, is the working tree dirty. Every one of them costs a window switch, a
bookmark hunt and a page load to learn a single word -- and the answer is usually "no change". This
module gets those four words onto the tile so the operator reads them all at once, and opens a tab
only when there is something to do on the other side of it.

Five rules, each of which is a way this has gone wrong on a real desk.

**One JQL, not one call per tile.** Four tiles asking Jira separately is four searches a minute
against one human's token, which is how a shared tenant starts rate-limiting a whole team. The Jira
poll collects every registered repo's `active_ticket` and asks once, whatever the tile count.

**The poll caps its own spend, and only its own.** It carries epic #121's `RequestBudget` as a
ceiling on *its* requests for the day; when it is down to the last `BUDGET_FLOOR` the poll stands
down and says so in the cell, because a ticket status that is an hour stale costs nothing.

What that budget is *not* -- and what every docstring in this module claimed until #122's review --
is a counter shared with a running `ad-jira changelog`. That command is a separate **process** with
its own `RequestBudget` object, so nothing in here can hold requests back for it and no wording can
make it so. Believing otherwise was worse than knowing there is no protection: it is why nobody
built any. What actually stops N tiles from starving one human's token is the rule above this one --
one search per interval however many tiles there are -- and the tenant's own rate limiter, which
`jira_http.RateLimit` reads on every response. A genuinely cross-process reservation would be a
spend file under `fleet_dir()` that the client wrote too, and that is a change to epic #121's client,
not to this module.

**A ceiling that bounds one command must not be left bounding a process.** `RequestBudget` also
carries `max_seconds` and `max_retries`, and `Jira.__init__` starts the seconds clock on the first
client and deliberately never restarts it. One budget for the life of `ad-fleet serve` therefore
died fifteen minutes after it started -- every later search raising "request budget exhausted
(seconds)", every ticket cell grey until somebody restarted the process. So each tick gets its own
budget for its own errand (`_tick_budget`), and only the request count is carried across ticks, on
a day's allowance that rolls over with the counters.

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

# The tail of its own day's allowance the poll stops before spending. A margin, not a reservation
# for anyone else (see the module docstring): one tick can cost more than one request once a retry
# is in play, and a poll that stopped exactly on its ceiling would find that out mid-search and grey
# four tiles instead of standing down cleanly with a sentence saying why.
BUDGET_FLOOR = 50

# How long one tick's Jira errand may take, in the client's own clock frame. It bounds *one search*,
# its 60 s timeout and its retries -- generous enough that a tenant pausing us on `Retry-After` still
# answers, short enough that a wedged connection cannot hold the dashboard's loop for the afternoon.
# It is deliberately not `RequestBudget`'s 900 s default: that number bounds a whole `ad-jira
# changelog` run, and applying a run's ceiling to a process that runs all day is #122's defect 3.
TICK_SECONDS = 240.0

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
    `jira_client` is handed a budget rather than making its own, so no substitute can poll on an
    unbounded one -- and what it is handed is the *tick's* budget, not `self.budget`; `_tick_budget`
    says why the difference is the whole of #122's defect 3.
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
        self.branch_reader: Callable[..., dict] = read_branches     # the cheap read, per tick (#184)

        self.polls: dict[str, dict[str, Poll]] = {}
        self._seen: dict[str, dict[str, str]] = {}
        self._counts: dict[str, dict[str, int]] = {"requests": {}, "errors": {}, "stood_down": {}}
        self._day = ""
        self._last_tick_time = self.now()
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
        from . import lifecycle
        if lifecycle.slept(self._last_tick_time, now):
            lifecycle.reap_all(registry=self.registry, slept=True)
        self._last_tick_time = now

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
        tick = self._tick_budget()
        try:
            client = self.jira_client(tick)
            issues = client.search(jql, list(JIRA_FIELDS), max_results=len(keys))
        except JiraBudgetError as e:
            # A budget ran out mid-search rather than before it -- and *which* budget decides what
            # the operator is told. Spending the day's allowance is a stand-down; running past this
            # tick's own seconds or retries is the poll's errand failing, and saying "standing down"
            # about it sent the operator to `fleet.poll.jira.interval`, which fixes neither.
            stood_down, why = _budget_words(e, self.budget)
            for repo, _key in active:
                (self._stand_down if stood_down else self._fail)(repo.name, "jira", now, why)
            return []
        except Exception as e:                    # noqa: BLE001 - any failure greys, none is fatal
            for repo, _key in active:
                self._fail(repo.name, "jira", now, _why(e))
            return []
        finally:
            # The tick budget's counter, not `client.stats.requests` and not a difference measured
            # on the allowance: `stats` mirrors whatever budget the client was handed, and the
            # allowance is a running total for the whole day, so neither is this tick's cost. What
            # the tick spent is charged to the day here, in one place, and a search that failed
            # still spent what it spent -- hence `finally`.
            self.budget.requests += tick.requests
            self._spent("jira", tick.requests)

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
            # The count beside the branch (#184): two more local reads, no `rev-list`. The full
            # read -- how far each branch is from the default, the last twenty commits -- is
            # `branches()`, on the click, because twenty `rev-list`s a minute across five
            # checkouts is a cost the poll cannot spend.
        except Exception as e:                    # noqa: BLE001
            self._fail(repo.name, "git", now, _why(e))
            return []
        try:
            answer = {**answer, **(self.branch_reader(repo, full=False) or {})}
        except Exception:                         # noqa: BLE001 - the branch stays; the count is absent
            pass
        self._ok(repo.name, "git", now, _git_value(answer, warn=warn_at(self.cfg)))
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

    def _tick_budget(self) -> RequestBudget:
        """A fresh budget for this one tick, drawn against the day's remaining allowance.

        The obvious thing -- one `RequestBudget` for the life of `ad-fleet serve` -- is what this
        replaces, and it did not survive contact with a dashboard left open (#122 defect 3).
        `max_seconds` is 900 and `Jira.__init__` starts that clock on the first client and
        deliberately never restarts it, so fifteen minutes after the server started every search
        raised "request budget exhausted (seconds)", every ticket cell greyed with a budget message
        that named the wrong cause, and nothing but a restart brought them back. `max_retries`
        accumulated the same way, a 429 at a time, and would have misreported the next transient
        retry as a stand-down. Both of those ceilings exist to bound *one command*; a poll is one
        command a minute for as long as the window is open, so the errand gets its own pair.

        The request count is the one thing that must not reset per tick -- it is the allowance whose
        whole point is to accumulate -- so only that is carried, on `self.budget`, and `_roll_day`
        turns it over with the counters the operator reads beside it.
        """
        return RequestBudget(max_requests=max(1, self.budget.remaining_requests()),
                             max_seconds=TICK_SECONDS, max_retries=self.budget.max_retries)

    def _budget_short(self) -> str:
        """The stand-down sentence, or "" when there is room. Says the numbers, because "the budget
        is short" is not something an operator can do anything with.

        Its own spend against its own ceiling: this cannot see, and does not claim to see, what an
        `ad-jira changelog` in another process is spending on the same token.
        """
        left = self.budget.remaining_requests()
        if left > BUDGET_FLOOR:
            return ""
        return (f"standing down: {left} of {self.budget.max_requests} requests left in the poll's "
                f"own allowance for today; polling resumes tomorrow, and a longer "
                f"`fleet.poll.jira.interval` makes the allowance last")

    def _spent(self, source: str, n: int) -> None:
        self._counts["requests"][source] = self._counts["requests"].get(source, 0) + max(0, int(n))

    # ---- the counters and fingerprints on disk ---------------------------------------------------

    def _roll_day(self, now: float) -> None:
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        if self._day and self._day != today:
            self._counts = {"requests": {}, "errors": {}, "stood_down": {}}
            # The allowance rolls with the counters, for the same reason the tick gets its own
            # seconds: `max_requests` bounds one command, and a dashboard open since Monday would
            # otherwise spend Monday's ceiling by Tuesday lunchtime and stand down for ever after.
            self.budget.requests = self.budget.retries = 0
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
    """A `Jira` on the token pncli already stores, bounded by `budget`, and costing nothing to build.

    `budget` is this tick's, not the process's, and a fresh client per tick is what makes that work:
    `Jira.__init__` starts the seconds clock only on a budget nobody has started, so a client handed
    a budget that has been running since the server started never gets its clock back (#122's
    defect 3). Building one is a constructor and a config read -- no request, no connection.

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


# ----------------------------------------------------------------------- the branches (#184)

BRANCH_WARN_DEFAULT = 6         # local branches at which the git cell goes amber
BRANCH_COUNT_LIMIT = 20         # `rev-list` calls per read, and commits of history shown
_KEY_IN_NAME = re.compile(r"([A-Za-z][A-Za-z0-9]+-\d+)")
_branches_cache: dict[str, tuple[float, dict]] = {}


def warn_at(cfg: dict | None = None) -> int:
    """`fleet.branches.warn`: the local-branch count at which the cell goes amber. Default 6, the
    operator's own number. Never below 1; a typo falls back rather than raising."""
    try:
        return max(1, int(C.get(cfg if cfg is not None else C.load(), "fleet.branches.warn",
                                BRANCH_WARN_DEFAULT)))
    except (TypeError, ValueError, C.ConfigError, OSError):
        return BRANCH_WARN_DEFAULT


def _git(repo_path: str, *args: str, timeout: int = 30) -> str:
    """One read-only git call in the checkout. `--no-optional-locks` for the reason `read_git`
    gives. A non-zero exit is an OSError with git's own last line, never a made-up answer."""
    from .. import proc

    code, out, err, _elapsed = proc.run(["git", "--no-optional-locks", *args], cwd=repo_path,
                                        timeout=timeout)
    if code != 0:
        raise OSError((err or out or f"git exited {code}").strip().splitlines()[-1][:200])
    return out


def default_branch(repo_path: str) -> str:
    """What `origin/HEAD` points at, else `main`, else `master`, else the current branch: a
    checkout that has never been pushed has no `origin/HEAD` and still has a default."""
    try:
        head = _git(repo_path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        if head:
            return head.split("/", 1)[1] if head.startswith("origin/") else head
    except OSError:
        pass
    for name in ("main", "master"):
        try:
            if _git(repo_path, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}").strip():
                return name
        except OSError:
            continue
    try:
        return _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except OSError:
        return "main"


def ticket_in(name: str) -> str:
    """The Jira key a branch name carries -- `feature/RDSD-22490-velocity` carries RDSD-22490 --
    or "" when it carries none. Upper-cased, because Jira keys are and branch names need not be."""
    m = _KEY_IN_NAME.search(name or "")
    key = m.group(1).upper() if m else ""
    return key if TICKET.match(key) else ""


def read_branches(repo, *, full: bool = True, limit: int = BRANCH_COUNT_LIMIT,
                  now: float | None = None) -> dict:
    """Every local branch of a checkout, and which of them never reached the default branch.

    Three local calls for the cheap read the git tick makes: the default branch, `for-each-ref`
    for the list, `branch --no-merged` for the ones whose work has not reached the default. The
    full read -- `rev-list --count` per unmerged branch, bounded at `limit` because a checkout
    with forty unmerged branches is the finding rather than a reason to make forty calls, and
    the last twenty commits of the current branch -- is what the click and `ad-fleet branches`
    ask for. Read-only throughout; nothing here is a write verb.

    Unmerged rows first, newest first within each half. `carrying` names the branches that carry
    the checkout's active ticket: a second one is how work gets stranded, and the pane says so.
    """
    path = repo.path
    now = time.time() if now is None else float(now)
    default = default_branch(path)
    current = _git(path, "rev-parse", "--abbrev-ref", "HEAD").strip()
    fmt = "%(refname:short)%09%(objectname:short)%09%(committerdate:unix)%09%(upstream:short)%09%(upstream:track)"
    rows: list[dict] = []
    for line in _git(path, "for-each-ref", "refs/heads", f"--format={fmt}").splitlines():
        parts = (line.rstrip("\n").split("\t") + ["", "", "", "", ""])[:5]
        name, sha, when, upstream, track = parts
        try:
            at = float(when)
        except ValueError:
            at = 0.0
        rows.append({"name": name, "sha": sha, "at": at, "age_s": max(0.0, now - at) if at else 0.0,
                     "upstream": upstream, "track": track.strip("[]"), "ticket": ticket_in(name),
                     "current": name == current, "unmerged": False, "ahead": None})
    unmerged = set()
    if rows:
        out = _git(path, "branch", "--no-merged", default, "--format=%(refname:short)")
        unmerged = {ln.strip() for ln in out.splitlines() if ln.strip()}
    for row in rows:
        row["unmerged"] = row["name"] in unmerged and row["name"] != default
    rows.sort(key=lambda r: (not r["unmerged"], -r["at"], r["name"]))

    more = False
    commits: list[str] = []
    if full:
        counted = 0
        for row in rows:
            if not row["unmerged"]:
                continue
            if counted >= limit:
                more = True
                break
            counted += 1
            try:
                row["ahead"] = int(_git(path, "rev-list", "--count", f"{default}..{row['name']}").strip() or 0)
            except (OSError, ValueError):
                row["ahead"] = None
        try:
            commits = [ln for ln in _git(path, "log", "--oneline", f"-n{limit}", "--decorate=short",
                                         "--no-color").splitlines() if ln.strip()]
        except OSError:
            commits = []

    ticket = _active_ticket(repo)
    carrying = [r["name"] for r in rows if ticket and r["ticket"] == ticket]
    return {"default": default, "current": current, "branches": rows, "count": len(rows),
            "unmerged": sum(1 for r in rows if r["unmerged"]), "more": more, "commits": commits,
            "ticket": ticket, "carrying": carrying, "full": full, "at": now}


def branches(repo, *, cfg: dict | None = None, force: bool = False, now: float | None = None) -> dict:
    """`read_branches(full=True)`, cached per checkout for the git cell's own interval. The page,
    the API and `ad-fleet branches` all come through here, so they show one answer."""
    now = time.time() if now is None else float(now)
    ttl = settings(cfg)["git"]["interval"]
    hit = _branches_cache.get(repo.path)
    if hit and not force and now - hit[0] < ttl:
        return {**hit[1], "cached": True, "age_s": round(now - hit[0], 1)}
    answer = read_branches(repo, full=True, now=now)
    answer["warn"] = len(answer["branches"]) >= warn_at(cfg)
    answer["warn_at"] = warn_at(cfg)
    answer["carry_line"] = carry_line(answer)
    _branches_cache[repo.path] = (now, answer)
    return {**answer, "cached": False, "age_s": 0.0}


def carry_line(answer: dict) -> str:
    """The one sentence the pane says when the smell is there: *two branches carry RDSD-22490;
    only one can merge*. Empty when there is nothing to say."""
    carrying, ticket = answer.get("carrying") or [], answer.get("ticket") or ""
    if len(carrying) < 2 or not ticket:
        return ""
    words = {2: "two", 3: "three", 4: "four", 5: "five"}.get(len(carrying), str(len(carrying)))
    return f"{words} branches carry {ticket} ({', '.join(carrying)}); only one can merge"


def branch_line(count: int, unmerged: int, default: str) -> str:
    """The git cell's second line: `7 branches · 3 never reached main`."""
    noun = "branch" if count == 1 else "branches"
    reach = f"{unmerged} never reached {default or 'main'}" if unmerged else f"all reached {default or 'main'}"
    return f"{count} {noun} · {reach}"


# ------------------------------------------------------------------------------- small helpers


def _active_ticket(repo) -> str:
    key = str((repo.state() or {}).get("active_ticket") or "").strip().upper()
    return key if TICKET.match(key) else ""


def _facts(repo) -> dict:
    """The repo's own AGENTS.md, or nothing. A registered path on a mapped drive that is not
    connected this morning is #129's drift case, and it must not stop the other tiles polling."""
    try:
        return C.project_facts(os.path.join(repo.path, "AGENTS.md"))
    except OSError:
        return {}


def _guid(value) -> str:
    text = str(value or "").strip()
    return text if GUID.match(text) else ""


def _budget_words(e: JiraBudgetError, allowance: RequestBudget) -> tuple[bool, str]:
    """`(is_a_stand_down, the sentence for the cell)` for a budget that ran out mid-search.

    Only `requests` is a stand-down: the poll has spent its allowance and is choosing not to spend
    more. `seconds` and `retries` are this tick's own errand failing -- one search that outran
    `TICK_SECONDS`, or a Jira that kept erroring -- and they belong in the error count, greyed with
    what actually happened. Filing them as stand-downs is what made `ad-doctor` warn that the token
    budget was nearly spent and tell the operator to raise `fleet.poll.jira.interval`, when Jira was
    slow and the budget was untouched.

    `JiraBudgetError`'s own hint is not used for the same reason: "rerun with a larger --max-seconds"
    is good advice to somebody running `ad-jira changelog` and no advice at all to somebody looking
    at a tile.
    """
    if e.limit == "requests":
        left = max(0, allowance.remaining_requests() - e.requests_made)
        return True, (f"standing down: {left} of {allowance.max_requests} requests left in the "
                      f"poll's own allowance for today; polling resumes tomorrow")
    if e.limit == "seconds":
        return False, (f"Jira did not answer one search within the poll's {int(TICK_SECONDS)}s "
                       f"ceiling ({e.elapsed:.0f}s, {e.requests_made} request(s)): this tile is "
                       f"stale because Jira is slow, not because the token budget is spent")
    return False, (f"Jira kept failing rather than answering ({e.requests_made} request(s) in "
                   f"{e.elapsed:.0f}s): check its status page; the next tick tries again")


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


def _git_value(answer: dict, warn: int = BRANCH_WARN_DEFAULT) -> dict:
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
    value = {"text": " ".join(bits), "branch": branch, "ahead": ahead, "behind": behind,
             "dirty": dirty}
    # The second line (#184), when the read counted: the number on the tile is the number in the
    # agent's transcript, because both read the same refs. Amber at `fleet.branches.warn`, and
    # never a toast -- the count changes when a person types `git checkout -b`.
    if "count" in answer:
        count, unmerged = int(answer.get("count") or 0), int(answer.get("unmerged") or 0)
        default = str(answer.get("default") or "")
        value.update({"count": count, "unmerged": unmerged, "default": default,
                      "line2": branch_line(count, unmerged, default), "warn": count >= warn,
                      "warn_at": warn, "carrying": list(answer.get("carrying") or [])})
    return value


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
