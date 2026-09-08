# PYTHON_ARGCOMPLETE_OK
"""ad-jira: Jira REST reusing pncli's token. whoami · fields · statuses · transitions · transition · sprints · changelog · sprint-replay · cache.
Never shells out to pncli; the token is read from pncli's config file by key name at call time.

Epic #121 changed how a changelog pull is *run*; it never changed what a row means. Four operator-facing
consequences live in this file.

**Nothing is held in memory that does not have to be.** `cmd_changelog` used to build one list of every row,
sort it, and hand it to `policy.render`, so a five-thousand-issue JQL with deep histories built hundreds of
thousands of dicts before the first byte reached `.agent/out/` -- and a 502 at minute fourteen threw all of them
away. Rows now go to a `jira_stream.TsvWriter` as the pages arrive. The one thing that must not change is the
*output*: a small result still renders exactly as it did, byte for byte, because rows are buffered up to
`policy.MEDIUM_ROWS + 1` and a run that ends inside that buffer builds an `AgentTable` and calls `policy.render`
just as before. Only a result that overflows the buffer switches to the streamed path. See `_Sink`.

**The final sort is gone, and the order is not.** Sorting a hundred thousand rows at the end requires having
them all, which is the thing streaming exists to avoid. The key *list* is sorted before fetching instead, and
`Jira.iter_changelog` guarantees each key's rows arrive together and ascending -- so the file comes out in
exactly the order `rows.sort(key=(key, created_utc, changelog_id))` used to produce, with no second pass.

**A short result says so.** A budget exhaustion, a Ctrl-C, an unrecoverable HTTP error after the first page and
Data Center's truncated `?expand=changelog` all now end the same way: what was fetched stays on disk, the TOON
carries `partial: true` with the reason, the counts and the literal command to rerun, and the exit code is not
zero. `sprint-replay` refuses such an input outright unless `--allow-partial` is passed, because a
`committed_points` computed over forty of a hundred histories looks exactly like a real number.

**The second run is cheap.** With `--jql`, the one `search(jql, ["key", "updated"])` that finds the issues also
decides which of them changed: an issue's changelog cannot move without its `updated` stamp moving, so an
unchanged issue is served from `jira_cache.ChangelogCache` and never requested. The cache is also the checkpoint
-- an issue is marked complete only after its last row -- which is what makes the resume hint real: rerunning
the same command is the resume.
"""
from __future__ import annotations
import argparse
import os
import re
import sys
from typing import Callable, Iterator

from . import completion
from . import config as C
from . import model
from . import toon
from . import jira_stream as ST
from . import jira_workflow as W
from .connectors import jira_api as J
from .console import utf8_stdout
from .jira_cache import ChangelogCache
from .model import AgentTable
from . import policy, ui
from .policy import error, render
from .uat import sprint as SP

CHANGELOG_COLUMNS = ["key", "changelog_id", "created_utc", "author", "field", "field_id", "field_type",
                     "from_id", "from_str", "to_id", "to_str"]

# The budget an operator gets without asking. Two thousand requests and fifteen minutes is comfortably more than
# any sane pull and far less than what it takes to get a shared token throttled. `jira.budget.*` in config moves
# them for a tenant that needs it; the flags move them for one run.
DEFAULT_MAX_REQUESTS = 2000
DEFAULT_MAX_SECONDS = 900.0

# Progress cadence: a line every this many pages, or this many seconds, whichever comes first. A pull that says
# nothing for fourteen minutes is indistinguishable from a hung one, and the operator's only recourse then is the
# Ctrl-C that used to throw the whole run away.
PROGRESS_PAGES = 25
PROGRESS_SECONDS = 5.0

# Rows held for one issue before they are handed to the cache. One issue's history is the client's own memory
# bound, and an INSERT per row would make the cache slower than the network it saves.
CACHE_FLUSH = 1000

# How many incomplete keys the meta names before it just counts them. Twenty is enough to see a pattern (one
# project, one range of keys) and short enough not to bury the rest of the meta.
INCOMPLETE_SHOWN = 20


# ---------------------------------------------------------------------------------- stderr, budget, client
def _stderr(msg: str) -> None:
    """Everything that is not the result. TOON owns stdout; one progress line on it corrupts the parse."""
    print(msg, file=sys.stderr, flush=True)


def _sayer(a) -> Callable[[str], None]:
    """The progress channel for this run: stderr, or nothing at all under `--quiet`."""
    return (lambda msg: None) if getattr(a, "quiet", False) else _stderr


def _budget(a, cfg: dict) -> J.RequestBudget:
    """`--max-requests` / `--max-seconds`, with `jira.budget.*` under them and the defaults under that.

    The argparse defaults are None on purpose. A flag defaulting to 2000 is indistinguishable from an operator
    typing 2000, so the config value could never win -- and a tenant that has to run with 6,000 requests would
    have to type it every time.
    """
    req = getattr(a, "max_requests", None)
    sec = getattr(a, "max_seconds", None)
    if req is None:
        req = C.get(cfg, "jira.budget.max_requests") or DEFAULT_MAX_REQUESTS
    if sec is None:
        sec = C.get(cfg, "jira.budget.max_seconds") or DEFAULT_MAX_SECONDS
    return J.RequestBudget(max_requests=int(req), max_seconds=float(sec))


def _client(redetect: bool = False, a=None):
    """The client, and for the two long commands the run budget and the stderr log it talks through."""
    cfg = C.load()
    creds = J.load_credentials(cfg)
    kw: dict = {}
    if a is not None and hasattr(a, "max_requests"):
        kw = {"budget": _budget(a, cfg), "log": None if getattr(a, "quiet", False) else _stderr}
    j, me = J.detect_flavor(creds, cfg, redetect=redetect, **kw)
    if redetect or not C.get(cfg, "verified.jira"):
        J.remember_flavor(cfg, j)
        C.save(cfg)
    return cfg, j, me


def _name_map(fields_json: list[dict]) -> dict:
    return {str(f.get("name") or "").lower(): f.get("id") for f in fields_json}


def cmd_whoami(a) -> int:
    cfg, j, me = _client(a.redetect)
    J.remember_flavor(cfg, j)
    C.save(cfg)
    rec = {"base_url": j.creds.base_url, "flavor": j.flavor.kind, "auth": j.flavor.auth, "api": j.flavor.api,
           "token_source": j.creds.source, "display_name": me.get("displayName"),
           "account": me.get("accountId") or me.get("name"), "email": me.get("emailAddress"), "timezone": me.get("timeZone")}
    print(render(AgentTable.from_records([rec], name="whoami", source="ad-jira whoami"), raw=a.raw))
    return 0


def cmd_fields(a) -> int:
    cfg, j, _ = _client()
    fj = j.fields()
    recs = []
    for f in fj:
        name = str(f.get("name") or "")
        if a.like and a.like.lower() not in name.lower():
            continue
        sch = f.get("schema") or {}
        recs.append({"id": f.get("id"), "name": name, "custom": bool(f.get("custom")), "type": sch.get("type"),
                     "custom_type": (sch.get("custom") or "").rsplit(":", 1)[-1] or None})
    extra = None
    if a.pin:
        pins = J.pin_fields(fj)
        C.put(cfg, "jira.fields.sprint", pins["sprint"])
        C.put(cfg, "jira.fields.story_points", pins["story_points"])
        C.save(cfg)
        extra = {"pinned_sprint": pins["sprint"] or "", "pinned_story_points": pins["story_points"]}
    print(render(AgentTable.from_records(recs, name="fields", source="ad-jira fields"), raw=a.raw, extra=extra))
    return 0


def cmd_statuses(a) -> int:
    _, j, _ = _client()
    recs = [{"id": s.get("id"), "name": s.get("name"), "category": (s.get("statusCategory") or {}).get("key")}
            for s in j.get(f"{j.api}/status") or []]
    print(render(AgentTable.from_records(recs, name="statuses", source="ad-jira statuses"), raw=a.raw))
    return 0


def _issue_state(j: J.Jira, key: str) -> tuple[str, str, str]:
    """(issue type, status name, status category) -- the three facts that decide which transitions exist."""
    f = (j.issue(key, ["issuetype", "status", "summary"]) or {}).get("fields") or {}
    st = f.get("status") or {}
    return ((f.get("issuetype") or {}).get("name") or "", st.get("name") or "",
            ((st.get("statusCategory") or {}).get("key") or "").lower())


def cmd_transitions(a) -> int:
    _, j, _ = _client()
    itype, status, cat = _issue_state(j, a.key)
    rows = W.normalize(j.transitions(a.key))
    for r in rows:
        r["requires"] = ",".join(r["requires"])
    print(render(AgentTable.from_records(rows, name="transitions", source=f"ad-jira transitions {a.key}"), raw=a.raw,
                 extra={"key": a.key, "issue_type": itype, "status": status, "status_category": cat,
                        "note": "this list is the issue TYPE's workflow: a Task and a Story in the same project differ"}))
    return 0


def cmd_transition(a) -> int:
    cfg, j, _ = _client()
    itype, status, _ = _issue_state(j, a.key)
    tkey, intent = W.type_key(itype), W.intent_of(a.to)
    src = f"ad-jira transition {a.key} --to {a.to}"
    if not a.force and W.already_there(status, a.to):
        print(toon.encode({"meta": {"ok": True, "source": src, "key": a.key, "issue_type": itype, "status": status,
                                    "already": True, "note": "no transition run: the issue is already there"}}))
        return 0
    pinned = C.get(cfg, f"jira.workflow.{tkey}.{intent}") if intent else None
    rows = W.normalize(j.transitions(a.key))
    try:
        t, why = W.resolve(rows, a.to, itype, pinned or "")
    except W.WorkflowError as e:
        print(toon.encode({"meta": {"ok": False, "source": src, "key": a.key, "issue_type": itype, "status": status,
                                    "error": str(e), "hint": e.hint},
                           "available": [{**r, "requires": ",".join(r["requires"])} for r in e.available]}))
        return 2
    bad = [x for x in a.field or [] if "=" not in x]
    if bad:
        print(error(f"--field expects NAME=VALUE, got {bad[0]!r}", 'example: --field \'resolution={"name":"Done"}\'', "ad-jira"))
        return 2
    fields = {k.strip(): W.field_value(v) for k, v in (x.split("=", 1) for x in a.field or []) if k.strip()}
    if a.resolution:
        fields["resolution"] = {"name": a.resolution}
    missing = [f for f in t["requires"] if f.lower() not in {k.lower() for k in fields}]
    meta = {"ok": True, "source": src, "key": a.key, "issue_type": itype, "status": status,
            "transition": f"{t['id']} {t['name']}", "to": t["to_status"], "matched": why,
            "fields": ",".join(sorted(fields)) or None, "requires": ",".join(t["requires"]) or None}
    if missing:
        meta.update({"ok": False, "error": f"transition {t['name']!r} has a screen requiring {', '.join(missing)}",
                     "hint": "supply them: " + " ".join(f'--field "{m}=<value>"' for m in missing)
                             + (" (or --resolution <name>)" if any(m.lower() == "resolution" for m in missing) else "")})
        print(toon.encode({"meta": {k: v for k, v in meta.items() if v is not None}}))
        return 2
    if a.dry_run:
        meta["dry_run"] = True
        print(toon.encode({"meta": {k: v for k, v in meta.items() if v is not None}}))
        return 0

    # The write. Unattended, this blocks for one operator click; in PyCharm it returns at once.
    # `meta` is the dry-run result, so what is approved is exactly what is about to be sent.
    from .fleet import approval

    decision = approval.require("jira-transition", f"{a.key}: {status} -> {t['to_status']}",
                                {k: v for k, v in meta.items() if v is not None},
                                ticket=a.key, cfg=cfg)
    if not decision.ok:
        print(toon.encode({"meta": approval.refusal(decision, src)}))
        return 2

    j.transition(a.key, t["id"], fields or None, a.comment)
    _, now, _ = _issue_state(j, a.key)                    # read it back: a post-function can move it somewhere else
    meta["status"], meta["moved"] = now, now.lower() != status.lower()
    if not meta["moved"]:
        meta.update({"ok": False, "error": f"Jira accepted the transition but {a.key} is still {now!r}",
                     "hint": "a looped transition or a workflow post-function put it back; ad-jira transitions "
                             f"{a.key} shows what is on offer now"})
    elif a.pin and intent:
        C.put(cfg, f"jira.workflow.{tkey}.{intent}", t["to_status"] or t["name"])
        C.save(cfg)
        meta["pinned"] = f"jira.workflow.{tkey}.{intent}={t['to_status'] or t['name']}"
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if v is not None], title=f"ad-jira transition {a.key}")
    else:
        print(toon.encode({"meta": {k: v for k, v in meta.items() if v is not None}}))
    return 0 if meta["moved"] else 1


def cmd_sprints(a) -> int:
    _, j, _ = _client()
    recs = [{"id": s.get("id"), "name": s.get("name"), "state": s.get("state"), "start": s.get("startDate"),
             "end": s.get("endDate"), "complete": s.get("completeDate")} for s in j.board_sprints(a.board, a.state)]
    print(render(AgentTable.from_records(recs, name="sprints", source=f"ad-jira sprints --board {a.board}"), raw=a.raw))
    return 0


def _utc(s: str | None) -> str | None:
    return J.parse_ts(s).strftime("%Y-%m-%dT%H:%M:%SZ") if s else None


# ------------------------------------------------------------------------------------- streaming a pull
class _Sink:
    """Rows in memory up to `policy.MEDIUM_ROWS + 1`, then a file for everything after that.

    This buffer is the whole compatibility story. Every changelog result this repository has ever rendered was a
    materialised `AgentTable`, and the tests that matter compare that output character for character. So a small
    result must not merely *look* the same, it must go through the same code: the rows stay in the buffer, an
    `AgentTable` is built from them and `policy.render` decides the rule exactly as before. Only when the buffer
    overflows -- past the largest result any rule renders in full -- does the writer open, take the buffered rows
    and every row after them, and the run switch to `policy.render_stream`.

    Peak memory is therefore one page from the client plus this buffer, never the result.

    `--raw` is honoured while the result fits the buffer. Past it the answer is the file, and rule 6 renders it:
    re-materialising a hundred thousand rows as JSON to satisfy a debugging flag would give back exactly the
    memory this class exists to bound.
    """

    def __init__(self, name: str, columns: list[str]):
        self.name, self.columns = name, list(columns)
        self.buf: list[dict] = []
        self.writer: ST.TsvWriter | None = None
        self.n = 0

    def add(self, row: dict) -> None:
        self.n += 1
        if self.writer is not None:
            self.writer.write(row)
            return
        self.buf.append(row)
        if len(self.buf) > policy.MEDIUM_ROWS:
            self.writer = ST.TsvWriter(ST.out_path(self.name), self.columns)
            for r in self.buf:
                self.writer.write(r)
            self.buf = []

    @property
    def path(self) -> str | None:
        """The file, once there is one. Below the buffer there is no file until `render` writes it."""
        return None if self.writer is None else self.writer.path

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()

    def render(self, source: str, raw: bool = False, extra: dict | None = None) -> str:
        if self.writer is None:
            t = AgentTable.from_records(self.buf, name=self.name, source=source, fields=self.columns)
            return policy.render(t, raw=raw, extra=extra)
        self.close()
        return policy.render_stream(self.name, source, self.columns, self.writer.path, self.writer.n,
                                    self.writer.head, extra=extra)


def _hms(seconds: float) -> str:
    s = int(max(0.0, seconds))
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    if s >= 60:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s}s"


class _Progress:
    """One stderr line per `PROGRESS_PAGES` pages or `PROGRESS_SECONDS` seconds, whichever comes first.

    Deliberately counted from the client's own events rather than from the rows the CLI keeps: a `--since` filter
    can drop nine rows in ten, and a progress line that reported the survivors would say a busy pull was doing
    nothing. Never on stdout -- that is the result.
    """

    def __init__(self, label: str, clock: Callable[[], float], say: Callable[[str], None]):
        self.label, self.clock, self.say = label, clock, say
        self.issues = self.rows = self.pages = 0
        self.started = self.last = clock()
        self._at_pages = 0

    def event(self, kind: str, payload: dict) -> None:
        if kind == "page":
            self.pages += 1
            self.rows += int(payload.get("rows") or 0)
        elif kind == "issue_done":
            self.issues += 1
        self.tick()

    def cached_issue(self, rows: int) -> None:
        """An issue the cache answered. It costs no request, and it is still progress the operator wants."""
        self.issues += 1
        self.rows += rows
        self.tick()

    def tick(self, force: bool = False) -> None:
        now = self.clock()
        if not force and self.pages - self._at_pages < PROGRESS_PAGES and now - self.last < PROGRESS_SECONDS:
            return
        self._at_pages, self.last = self.pages, now
        self.say(f"{self.label}: {self.issues:,} issues, {self.rows:,} rows, page {self.pages:,}, "
                 f"{_hms(now - self.started)}")


class _Pull:
    """One changelog pull: the cache partition, the merge of cached and fetched rows, and what finished.

    The merge is why this is a class and not a loop. Rows have to reach the file in one global order -- keys
    ascending, and within a key ascending by `(created_utc, changelog_id)` -- while half of them come from the
    cache and the other half arrive from `iter_changelog` as pages are parsed. Both halves are subsequences of
    the same sorted key list, so walking that list and taking each key's rows from whichever side owns it
    produces the sorted file with no second pass and nothing in memory but the row in hand. That is what replaces
    the `rows.sort()` over the whole result.

    It is also where the cache becomes the checkpoint. An issue is opened at its first row and marked complete
    only when the client says the issue is done, so a run killed at minute fourteen leaves every finished issue
    complete and the one in flight incomplete -- and rerunning the same command asks Jira only for what is
    missing. An issue with no changelog at all is opened and closed by its `issue_done` alone, because "no rows"
    is a complete answer and refetching it every run would be a permanent tax on the quietest issues.

    Only keys whose `updated` the search reported are written. Without that stamp there is nothing a later run
    could compare against, so an explicitly named `KEY` argument (no `--jql`, no search, no stamp) is always
    fetched and never stored -- the alternative, storing it under an empty stamp, would either serve it forever
    or be refetched anyway.
    """

    def __init__(self, j: J.Jira, keys: list[str], *, cache: ChangelogCache | None = None,
                 stamps: dict | None = None, ids: dict | None = None, fresh=(), field_ids: list[str] | None = None,
                 name_to_id: dict | None = None, id_to_key: dict | None = None, use_bulk: bool = True,
                 bulk_issues: int = 200, bulk_page: int = 500, progress: _Progress | None = None):
        self.j, self.keys = j, list(keys)
        self.cache, self.stamps, self.ids = cache, dict(stamps or {}), dict(ids or {})
        self.fresh = set(fresh)
        self.stale = [k for k in self.keys if k not in self.fresh]
        self.writable = {k for k in self.stale if cache is not None and self.stamps.get(k)}
        self.field_ids, self.name_to_id, self.id_to_key = field_ids, name_to_id, id_to_key
        self.use_bulk, self.bulk_issues, self.bulk_page = use_bulk, bulk_issues, bulk_page
        self.progress = progress
        self.done: list[str] = []
        self._done: set[str] = set()
        self.pages_in_issue = 0
        self._open: str | None = None
        self._pending: list[dict] = []

    # ---- the row stream
    def rows(self) -> Iterator[dict]:
        it = (self.j.iter_changelog(self.stale, field_ids=self.field_ids, name_to_id=self.name_to_id,
                                    id_to_key=self.id_to_key, use_bulk=self.use_bulk,
                                    bulk_issues=self.bulk_issues, bulk_page=self.bulk_page,
                                    on_event=self._event)
              if self.stale else iter(()))
        ahead: dict | None = None
        for key in self.keys:
            if key in self.fresh:
                n = 0
                for row in self.cache.rows_for(key):
                    n += 1
                    yield row
                self._mark(key)
                if self.progress:
                    self.progress.cached_issue(n)
                continue
            while True:
                if ahead is None:
                    ahead = next(it, None)
                    if ahead is None:
                        break
                if ahead.get("key") != key:
                    break
                row, ahead = ahead, None
                self._store(row)
                yield row
        # Anything the key walk did not claim: a bulkfetch answer for an issue id no search could map back to a
        # key. The client refuses to drop those rows and so does this.
        while True:
            if ahead is None:
                ahead = next(it, None)
                if ahead is None:
                    return
            row, ahead = ahead, None
            self._store(row)
            yield row

    @property
    def incomplete(self) -> list[str]:
        """The keys whose rows are not all on disk, in the order they were to be fetched. The first of them is
        the issue the run died on."""
        return [k for k in self.keys if k not in self._done]

    # ---- the cache side
    def _event(self, kind: str, payload: dict) -> None:
        if kind == "page":
            self.pages_in_issue += 1
        elif kind == "issue_done":
            self._finish(str(payload.get("key") or ""))
        if self.progress:
            self.progress.event(kind, payload)

    def _finish(self, key: str) -> None:
        if key in self.writable:
            if self._open != key:
                self._begin(key)          # an issue with no changelog at all: still a complete answer
            self._flush()
            self.cache.finish_issue(key)
        self._open = None
        self.pages_in_issue = 0
        self._mark(key)

    def _mark(self, key: str) -> None:
        if key and key not in self._done:
            self._done.add(key)
            self.done.append(key)

    def _store(self, row: dict) -> None:
        key = str(row.get("key") or "")
        if key not in self.writable:
            return
        if self._open != key:
            self._begin(key)
        self._pending.append(row)
        if len(self._pending) >= CACHE_FLUSH:
            self._flush()

    def _begin(self, key: str) -> None:
        self._flush()
        self.cache.begin_issue(key, self.ids.get(key), self.stamps[key])
        self._open = key

    def _flush(self) -> None:
        if self._pending and self._open:
            self.cache.add_rows(self._open, self._pending)
        self._pending = []


def _open_cache(a, say: Callable[[str], None], fields_given: bool = False) -> ChangelogCache | None:
    """The cache, or None when it must not be used.

    `--no-cache` is the operator's word. `--fields` is ours: a field-filtered pull asks Jira for part of a
    history, and storing that part under the issue's `updated` stamp would make the next unfiltered run serve a
    fragment as the whole history. `--since` has no such problem and stays a client-side filter -- the cache is
    given the unfiltered rows and the filter is applied on the way to the file, which is the difference between
    a filter and a lie.

    A cache that cannot be opened is not a reason to fail a data pull. It disables itself, says so on stderr, and
    the run fetches everything exactly as it did before the cache existed.
    """
    if getattr(a, "no_cache", False):
        return None
    if fields_given:
        say("changelog cache off for this run: --fields fetches part of a history and the cache stores whole ones")
        return None
    cache = ChangelogCache.open(model.OUT_DIR)
    if cache.disabled:
        say(cache.error)
        say(cache.hint)
        cache.close()
        return None
    return cache


def _row_filter(wanted: list[str] | None, since: str | None, until: str | None) -> Callable[[dict], bool]:
    """`--fields` / `--since` / `--until`, applied on the way from the client to the file -- never before the
    cache, which is always given the whole history."""
    w = {str(x).lower() for x in wanted} if wanted else None

    def keep(r: dict) -> bool:
        if w and str(r.get("field_id") or "").lower() not in w and str(r.get("field") or "").lower() not in w:
            return False
        c = r.get("created_utc") or ""
        return (not since or c >= since) and (not until or c <= until)
    return keep


def _reason(exc: BaseException, pull: _Pull) -> str:
    """The `reason` an operator reads: one spelling per way a pull can end short.

    The fifth, `network on <key> page <n>`, is not in the epic's list and is here because leaving it out would
    have meant a timeout that survived six retries -- the exact failure that used to lose a run at minute
    fourteen -- falling through as a bare error with a full file on disk and nothing saying the file is short.
    """
    left = pull.incomplete
    where = f"{left[0] if left else '?'} page {pull.pages_in_issue + 1}"
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    if isinstance(exc, J.JiraPartialError):
        return exc.reason
    if isinstance(exc, J.JiraBudgetError):
        return "budget"
    if isinstance(exc, J.JiraHTTPError):
        return f"http {exc.status} on {where}"
    return f"network on {where}"


def _rendered_path(text: str) -> str | None:
    """The file the render just wrote, read back out of its own meta.

    A result small enough to stay in the buffer never learns its path: `AgentTable` chooses it inside
    `policy.render`, after the rows are handed over. The stderr line for an interrupted run has to name the file
    it kept, so it is read back from the one place that always has it rather than by second-guessing the naming
    rules the format policy owns.
    """
    m = re.search(r"^ *path: (.+)$", text, re.M)
    return m.group(1) if m else None


def _partial_meta(reason: str, rows_written: int, pull: _Pull, resume: str, hint: str = "") -> dict:
    """The shape every short pull renders. `hint` is the one thing the operator can DO about this one.

    It is carried rather than re-derived because the client already knows: `JiraBudgetError` names the flag that
    would have finished the run, the bulkfetch fallback names `--no-bulk` and `--bulk-issues`, the Data Center
    truncation names where the older events actually live, and a broken cache names `ad-jira cache --clear`.
    Those hints were being computed and thrown away, which left `partial: true` telling a human what happened
    and nothing about what to type next.
    """
    incomplete = pull.incomplete
    meta = {"ok": False, "partial": True, "reason": reason, "rows_written": rows_written,
            "issues_complete": len(pull.done), "issues_incomplete": incomplete[:INCOMPLETE_SHOWN],
            "issues_incomplete_count": len(incomplete), "resume": resume}
    if hint:
        meta["hint"] = hint
    return meta


def _arg(flag: str, value) -> list[str]:
    if value in (None, "", False):
        return []
    if value is True:
        return [flag]
    s = str(value)
    return [flag, s if s and all(ch.isalnum() or ch in "-_.:/=+" for ch in s) else '"%s"' % s.replace('"', '\\"')]


def _budget_flags(reason: str, a) -> tuple:
    """`--max-requests` / `--max-seconds` for the resume line -- unless they are what stopped the run.

    The skill tells the operator to run the printed line once and log friction if it is still short, so a resume
    that replays the ceiling it just hit turns a pull needing twelve runs into a friction log after one. It also
    contradicts the client's own hint, which says to rerun with a LARGER budget. Dropping them puts the run back
    on the default (or on `jira.budget.*`), and the cache means it starts where this one stopped -- the same
    reason `--no-cache` and `--refresh` are dropped below.
    """
    if reason == "budget":
        return ()
    return (("--max-requests", a.max_requests), ("--max-seconds", a.max_seconds))


def _resume_changelog(a, reason: str = "") -> str:
    """The literal command that resumes this pull.

    Rerunning IS the resume: every issue that finished is in the cache, so the second run's partition asks Jira
    only for what is missing. Which is why flags are deliberately dropped from the command printed here --
    `--no-cache` and `--refresh` both defeat the checkpoint the resume depends on, and echoing them back would
    hand the operator a command that starts the whole pull again; see `_budget_flags` for the other two.
    """
    parts = ["ad-jira", "changelog", *list(a.keys)]
    for flag, val in (("--jql", a.jql), ("--fields", a.fields), ("--since", a.since), ("--until", a.until),
                      ("--name", a.name), ("--no-bulk", a.no_bulk), *_budget_flags(reason, a)):
        parts += _arg(flag, val)
    if a.bulk_issues != 200:
        parts += _arg("--bulk-issues", a.bulk_issues)
    if a.bulk_page != 500:
        parts += _arg("--bulk-page", a.bulk_page)
    return " ".join(parts)


def _resume_replay(a, reason: str = "") -> str:
    parts = ["ad-jira", "sprint-replay"]
    for flag, val in (("--sprint", a.sprint), ("--board", a.board), ("--jql", a.jql), ("--name", a.name),
                      ("--no-bulk", a.no_bulk), *_budget_flags(reason, a)):
        parts += _arg(flag, val)
    return " ".join(parts)


def _bulk_extra(j: J.Jira, asked_page: int) -> dict:
    """What the bulkfetch path did that the operator would not have predicted.

    Only the surprises: a page that shrank because the server could not answer the one asked for, keys the server
    rejected as invalid, and a fallback to one request per issue. A `bulk_page_final` equal to the flag says
    nothing and would sit in every meta forever.
    """
    out: dict = {}
    m = j.bulk_meta or {}
    if m.get("bulk_page_final") is not None and int(m["bulk_page_final"]) != int(asked_page):
        out["bulk_page_final"] = int(m["bulk_page_final"])
    if m.get("skipped_keys"):
        out["skipped_keys"] = list(m["skipped_keys"])[:INCOMPLETE_SHOWN]
    if m.get("truncated_keys"):
        out["truncated_keys"] = list(m["truncated_keys"])[:INCOMPLETE_SHOWN]
    if m.get("fallback"):
        out["bulk_fallback"] = m.get("fallback_reason") or True
    return out


def _rejected(j: J.Jira) -> J.JiraPartialError | None:
    """A bulkfetch 400 that named real keys is a short result, not a footnote.

    `_invalid_keys` only ever drops keys THIS run asked for, so every entry here is an issue the operator
    requested and whose history is entirely absent from the output. It used to reach the meta as one
    `skipped_keys` line under `ok: true` -- a history short by one whole issue, looking complete, which is the
    failure the epic exists to kill. It ends the run the same way every other short result does.
    """
    keys = list((j.bulk_meta or {}).get("skipped_keys") or [])
    if not keys:
        return None
    shown = ", ".join(keys[:INCOMPLETE_SHOWN])
    return J.JiraPartialError(f"bulkfetch rejected {len(keys)} key(s): {shown}",
                              reason="keys rejected by bulkfetch",
                              hint=f"check that {shown} still exist (a moved or deleted issue is the usual "
                                   f"cause), or rerun with --no-bulk to fetch them one at a time")


def _search_keys(j: J.Jira, jql: str, fields: list[str]) -> tuple[dict, dict, dict]:
    """One search, three answers: the issues, each one's `updated` stamp, and the id -> key map.

    The same call already had to happen to find the issues; taking the stamp and the id out of it is what makes
    the cache free and removes the `key in (...)` searches bulkfetch would otherwise run to resolve its
    `issueId`s. An issue whose `updated` the server did not return simply has no stamp and is always fetched.
    """
    issues, stamps, ids = {}, {}, {}
    for iss in j.search(jql, fields):
        k = iss.get("key")
        if not k:
            continue
        issues.setdefault(k, iss)
        up = (iss.get("fields") or {}).get("updated")
        if up:
            stamps[k] = str(up)
        if iss.get("id") is not None:
            ids[k] = str(iss["id"])
    return issues, stamps, ids


def cmd_changelog(a) -> int:
    _, j, _ = _client(a=a)
    say = _sayer(a)
    keys = list(dict.fromkeys(a.keys))
    stamps: dict = {}
    ids: dict = {}
    if a.jql:
        found, stamps, ids = _search_keys(j, a.jql, ["key", "updated"])
        keys += [k for k in found if k not in keys]
    if not keys:
        print(error("no issue keys", "pass KEY... or --jql", "ad-jira"))
        return 2
    fj = j.fields()
    name_to_id = _name_map(fj)
    wanted = J.resolve_field_ids(a.fields.split(","), fj) if a.fields else None

    # No `--jql` means no search, and no search means no `updated` stamp for anything: there would be nothing for
    # the cache to decide with and nothing worth writing, so it is not even opened.
    cache = _open_cache(a, say, fields_given=bool(a.fields)) if a.jql else None
    # Sorted here, once, instead of sorting the rows at the end: the iterator's ordering guarantee turns a sorted
    # key list into a globally sorted file. `keys` keeps the given order for the source line, which is what the
    # meta has always shown.
    order = sorted(keys)
    fresh: list[str] = []
    if cache is not None and not a.refresh:
        fresh, _stale = cache.partition({k: stamps[k] for k in order if k in stamps})
    pull = _Pull(j, order, cache=cache, stamps=stamps, ids=ids, fresh=fresh, field_ids=wanted,
                 name_to_id=name_to_id, id_to_key={v: k for k, v in ids.items()}, use_bulk=not a.no_bulk,
                 bulk_issues=a.bulk_issues, bulk_page=a.bulk_page,
                 progress=_Progress("changelog", j.clock, say))
    if cache is not None:
        say(f"changelog: {len(fresh):,} issues from cache, {len(pull.stale):,} to fetch")

    keep = _row_filter(wanted, _utc(a.since), _utc(a.until))
    sink = _Sink(a.name or "changelog", CHANGELOG_COLUMNS)
    src = "ad-jira changelog " + " ".join(keys[:3]) + (" …" if len(keys) > 3 else "")
    failure: BaseException | None = None
    try:
        try:
            for row in pull.rows():
                if keep(row):
                    sink.add(row)
        except (KeyboardInterrupt, J.JiraError) as e:
            # A failure before anything arrived is just a failed command: there is no partial result to report
            # and the operator is better served by the plain error `main` prints. Two exceptions. A budget
            # exhaustion is the client refusing to start, and the resume hint is the answer to it. A Data Center
            # truncation is a *server* answer that is knowingly short -- the one case where zero rows still has
            # to render as `partial`, because that refusal is the whole reason the shape exists.
            if not isinstance(e, (J.JiraBudgetError, J.JiraPartialError)) and not sink.n and not pull.done:
                raise
            failure = e
    finally:
        sink.close()

    # A chunk the server rejected costs whole histories and raises nothing, so it is turned into the same
    # failure every other short result already is -- one rendering path, one exit code.
    failure = failure or _rejected(j)

    extra: dict = {}
    if failure is not None:
        reason = _reason(failure, pull)
        extra.update(_partial_meta(reason, sink.n, pull, _resume_changelog(a, reason),
                                   hint=getattr(failure, "hint", "")))
    if cache is not None:
        extra.update({"cached": len(fresh), "fetched": len(pull.stale),
                      "resumed": bool(fresh) and bool(pull.stale)})
    extra.update(_bulk_extra(j, a.bulk_page))
    if a.stats:
        extra.update(j.stats.as_dict())
    out = sink.render(src, raw=a.raw, extra=extra or None)
    if cache is not None:
        # A cache that broke DURING the run never had its message read: `_open_cache` looks once, at the start.
        if cache.disabled and cache.error:
            say(cache.error)
            say(cache.hint)
        cache.close()
    print(out)
    if failure is not None:
        kept = sink.path or _rendered_path(out)
        where = f" kept in {kept}" if kept else ""
        say(f"changelog partial ({extra['reason']}): {sink.n:,} rows{where}, "
            f"{len(pull.done):,} of {len(order):,} issues complete")
        if extra.get("hint"):
            say(f"hint: {extra['hint']}")
        say(f"resume: {extra['resume']}")
    if a.stats:
        say("changelog: " + j.stats.line())
    return 1 if failure is not None else 0


def cmd_cache(a) -> int:
    """`ad-jira cache --stats | --clear`: a sub-verb of this entry point, never a console script of its own."""
    cache = ChangelogCache.open(model.OUT_DIR)
    if a.clear:
        path = cache.path
        cache.clear()
        cache.close()
        print(toon.encode({"meta": {"ok": True, "source": "ad-jira cache --clear", "path": path, "cleared": True}}))
        return 0
    st = cache.stats()
    cache.close()
    print(render(AgentTable.from_records([st], name="cache", source="ad-jira cache --stats"), raw=a.raw))
    return 0


def _resolve_sprint(j: J.Jira, spec: str, board: int | None) -> dict:
    if spec.isdigit():
        return j.sprint(int(spec))
    if not board:
        raise J.JiraError(f"--sprint '{spec}' is a name; --board is required to resolve it", hint="ad-jira sprints --board <jira_board_id>")
    cands = j.board_sprints(board)
    exact = [s for s in cands if str(s.get("name", "")).lower() == spec.lower()]
    subs = [s for s in cands if spec.lower() in str(s.get("name", "")).lower()]
    hit = exact or subs
    if len(hit) != 1:
        names = ", ".join(f"{s.get('id')}={s.get('name')}" for s in (hit or cands)[:15])
        raise J.JiraError(f"sprint '{spec}' matched {len(hit)} sprints on board {board}", hint=f"use the id: {names}")
    return hit[0]


def cmd_sprint_replay(a) -> int:
    cfg, j, _ = _client(a=a)
    say = _sayer(a)
    sj = _resolve_sprint(j, a.sprint, a.board)
    sprint = SP.SprintInfo.from_json(sj)
    board = a.board or sj.get("originBoardId")
    fj = j.fields()
    pins = J.pin_fields(fj)
    sprint_field = C.get(cfg, "jira.fields.sprint") or pins["sprint"]
    points_fields = list(C.get(cfg, "jira.fields.story_points") or pins["story_points"] or [])
    if not sprint_field or not points_fields:
        print(error("Sprint / Story Points field ids unknown", "run ad-jira fields --pin (or --like sprint / --like point)", "ad-jira"))
        return 2
    status_cat = j.statuses()
    fields = ["key", "issuetype", "created", "updated", "status", sprint_field, *points_fields]
    issues, stamps, ids = _search_keys(j, f"sprint = {sprint.id}", fields)
    if a.jql:
        wide, wide_stamps, wide_ids = _search_keys(j, a.jql, fields)
        for k, v in wide.items():
            issues.setdefault(k, v)
        stamps = {**wide_stamps, **stamps}
        ids = {**wide_ids, **ids}
    name_to_id = _name_map(fj)
    cache = _open_cache(a, say)
    order = sorted(issues)
    fresh: list[str] = []
    if cache is not None and not a.refresh:
        fresh, _stale = cache.partition({k: stamps[k] for k in order if k in stamps})
    # With the cache on, the replay asks for the whole history rather than the four fields it reads. The saving
    # was real but the stored history would have been a fragment marked complete, and the next `ad-jira changelog`
    # would have served it as the truth. `--no-cache` keeps the narrow fetch.
    field_ids = None if cache is not None else [sprint_field, "status", *points_fields]
    pull = _Pull(j, order, cache=cache, stamps=stamps, ids=ids, fresh=fresh, field_ids=field_ids,
                 name_to_id=name_to_id, id_to_key={v: k for k, v in ids.items()}, use_bulk=not a.no_bulk,
                 bulk_issues=a.bulk_issues, bulk_page=a.bulk_page,
                 progress=_Progress("sprint-replay", j.clock, say))
    src = f"ad-jira sprint-replay {sprint.id}"
    # The replay reads four fields of a history and ignores the rest, so only those rows are kept, bucketed by
    # the issue that owns them. Keeping the whole stream was the one place a `--jql` wide enough to see punted
    # issues still built every row of every history in memory -- and handing that flat list to
    # `build_issue_state` once per issue made the assembly quadratic: 2,000 issues x 400,000 rows is 800 million
    # comparisons for an answer that is one bucket lookup. `_changes()` filters on exactly this expression, so
    # dropping the other rows here changes nothing the replay could have read.
    wanted = {str(sprint_field), "status", *(str(f) for f in points_fields)}
    by_key: dict[str, list[dict]] = {}
    n_rows = 0
    failure: BaseException | None = None
    try:
        for row in pull.rows():
            n_rows += 1
            if str(row.get("field_id") or row.get("field") or "") in wanted:
                by_key.setdefault(str(row.get("key") or ""), []).append(row)
    except (KeyboardInterrupt, J.JiraError) as e:
        if not isinstance(e, (J.JiraBudgetError, J.JiraPartialError)) and not n_rows and not pull.done:
            raise
        failure = e
    failure = failure or _rejected(j)
    if cache is not None:
        if cache.disabled and cache.error:
            say(cache.error)
            say(cache.hint)
        cache.close()

    if failure is not None:
        reason = _reason(failure, pull)
        # The refusal. Replaying a short history is not a smaller answer, it is a different sprint: every issue
        # whose changelog stopped early keeps whatever sprint and points it had at the last row that arrived, and
        # `committed_points` comes out looking exactly like a real number.
        meta = _partial_meta(reason, n_rows, pull, _resume_replay(a, reason), hint=getattr(failure, "hint", ""))
        if not a.allow_partial:
            meta.update({"source": src, "error": f"changelog partial ({reason}): replay refuses a short history",
                         "hint": f"rerun to resume ({meta['resume']}), or pass --allow-partial to compute "
                                 f"over {len(pull.done)} of {len(order)} issues anyway"})
            print(toon.encode({"meta": meta}))
            say(f"sprint-replay refused: {reason}")
            return 2
        say(f"sprint-replay computing over a partial changelog ({reason}): "
            f"{len(pull.done)} of {len(order)} issues complete")

    # The states -- and therefore the output rows -- keep the order the search returned them in, which is the
    # order this command has always printed. `order` is sorted for the *fetch*, where it is what lets the cache
    # and the client interleave without a second pass; sorting the output too would have been a gratuitous
    # change to a table people read.
    states = [SP.build_issue_state(issues[k], by_key.get(k, ()), sprint_field, points_fields) for k in issues]
    try:
        rows, summary = SP.replay(states, sprint, status_cat, sprint_field, points_fields, points_at_mode=a.points_at,
                                  include_subtasks=a.include_subtasks, now=J.parse_ts(a.now) if a.now else None,
                                  partial=failure is not None, issues_incomplete=pull.incomplete)
    except ValueError as e:
        print(error(str(e), "pick a started sprint (ad-jira sprints --board ... --state closed)", "ad-jira"))
        return 2
    out: dict = {"summary": summary}
    if a.compare_sprintreport:
        if not board:
            print(error("--compare-sprintreport needs --board", "pass --board <jira_board_id>", "ad-jira"))
            return 2
        out["sprintreport_delta"] = SP.sprintreport_delta(j.sprintreport(board, sprint.id), rows, summary)
    name = a.name or f"sprint_{sprint.id}"
    extra: dict = {}
    if cache is not None:
        extra.update({"cached": len(fresh), "fetched": len(pull.stale),
                      "resumed": bool(fresh) and bool(pull.stale)})
    extra.update(_bulk_extra(j, a.bulk_page))
    if a.stats:
        extra.update(j.stats.as_dict())
    print(render(AgentTable.from_records(rows, name=name, source=src), raw=a.raw, extra=extra or None))
    if policy.pretty():
        ui.facts(list(summary.items()), title=f"sprint-replay {sprint.id} summary")
        if out.get("sprintreport_delta"):
            ui.facts(list(out["sprintreport_delta"].items()), title="sprintreport delta")
    else:
        print(toon.encode(out))
    if a.stats:
        say("sprint-replay: " + j.stats.line())
    return 0


def _add_run_flags(p, bulk: bool = True) -> None:
    """The flags every long pull shares: what it may spend, what it may keep, and how loud it is."""
    p.add_argument("--max-requests", type=int, help=f"stop after this many requests (default {DEFAULT_MAX_REQUESTS}, "
                                                    "or jira.budget.max_requests)")
    p.add_argument("--max-seconds", type=float, help=f"stop after this long (default {DEFAULT_MAX_SECONDS:.0f}s, "
                                                     "or jira.budget.max_seconds)")
    if bulk:
        p.add_argument("--bulk-issues", type=int, default=200, help="issues per bulkfetch call (max 1000)")
        p.add_argument("--bulk-page", type=int, default=500, help="changes per bulkfetch page (max 10000)")
    p.add_argument("--no-cache", action="store_true", help="neither read nor write the changelog cache")
    p.add_argument("--refresh", action="store_true", help="refetch every issue, ignoring the cached updated stamp")
    p.add_argument("--stats", action="store_true", help="print what the run cost on stderr and in the meta")
    p.add_argument("--quiet", action="store_true", help="no progress lines on stderr")


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-jira", description="Jira REST via pncli's token: history the current-state search cannot give.")
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("whoami", help="detect Cloud/DC flavor and auth; caches it in config")
    p.add_argument("--redetect", action="store_true"); p.add_argument("--raw", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)"); p.set_defaults(fn=cmd_whoami)
    p = sub.add_parser("fields", help="field name <-> id map; --pin stores Sprint / Story Points ids")
    p.add_argument("--like"); p.add_argument("--pin", action="store_true"); p.add_argument("--raw", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)"); p.set_defaults(fn=cmd_fields)
    p = sub.add_parser("statuses", help="status id, name, category (done|indeterminate|new)")
    p.add_argument("--raw", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)"); p.set_defaults(fn=cmd_statuses)
    p = sub.add_parser("transitions", help="what THIS issue can move to (a Task and a Story have different workflows)")
    p.add_argument("key", metavar="KEY"); p.add_argument("--raw", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)"); p.set_defaults(fn=cmd_transitions)
    p = sub.add_parser("transition", help='move an issue: --to takes an intent (review, done, in-progress, todo, blocked) '
                                          'or an exact transition/status name')
    p.add_argument("key", metavar="KEY"); p.add_argument("--to", required=True)
    p.add_argument("--dry-run", action="store_true", help="resolve and print the transition without running it")
    p.add_argument("--resolution", help='shorthand for --field \'resolution={"name":"<X>"}\'')
    p.add_argument("--field", action="append", metavar="NAME=VALUE", help="a transition-screen field (repeatable); JSON value if it parses")
    p.add_argument("--comment", help="comment to post with the transition")
    p.add_argument("--pin", action="store_true", help="remember the resolved status for this issue type (jira.workflow.<type>.<intent>)")
    p.add_argument("--force", action="store_true", help="run even if the issue already looks like it is there")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_transition)
    p = sub.add_parser("sprints", help="sprints of a board")
    p.add_argument("--board", type=int, required=True); p.add_argument("--state", choices=["active", "closed", "future"])
    p.add_argument("--raw", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)"); p.set_defaults(fn=cmd_sprints)
    p = sub.add_parser("changelog", help="field history rows for issues")
    p.add_argument("keys", nargs="*", metavar="KEY"); p.add_argument("--jql"); p.add_argument("--fields", help='e.g. status,Sprint,"Story Points"')
    p.add_argument("--since"); p.add_argument("--until"); p.add_argument("--no-bulk", action="store_true")
    p.add_argument("--name"); p.add_argument("--raw", action="store_true")
    _add_run_flags(p)
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)"); p.set_defaults(fn=cmd_changelog)
    p = sub.add_parser("cache", help="the changelog cache: --stats (default) or --clear")
    p.add_argument("--stats", action="store_true", help="issues, rows, size and the oldest fetch (the default)")
    p.add_argument("--clear", action="store_true", help="delete the cache file; the next pull recreates it")
    p.add_argument("--raw", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)"); p.set_defaults(fn=cmd_cache)
    p = sub.add_parser("sprint-replay", help="committed vs completed points by backward changelog replay")
    p.add_argument("--sprint", required=True, help="sprint id, or name (needs --board)"); p.add_argument("--board", type=int)
    p.add_argument("--jql", help="widen the candidate set, e.g. project = X AND updated >= '<start-1d>' (needed to see punted issues)")
    p.add_argument("--points-at", choices=["commit", "close"], default="close"); p.add_argument("--include-subtasks", action="store_true")
    p.add_argument("--compare-sprintreport", action="store_true"); p.add_argument("--now"); p.add_argument("--no-bulk", action="store_true")
    p.add_argument("--allow-partial", action="store_true", help="compute over a changelog that came back short, and say so in the summary")
    p.add_argument("--name"); p.add_argument("--raw", action="store_true")
    _add_run_flags(p)
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)"); p.set_defaults(fn=cmd_sprint_replay)
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        return a.fn(a)
    except J.JiraError as e:
        print(error(str(e), e.hint or "ad-jira whoami --redetect", "ad-jira")); return 1
    except C.ConfigError as e:
        print(error(str(e), e.hint or "ad-setup --only pncli", "ad-jira")); return 2


if __name__ == "__main__":
    sys.exit(main())
