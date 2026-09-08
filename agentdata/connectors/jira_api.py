"""Jira REST client (stdlib only). Reuses pncli's Jira token: read at call time from pncli's own config by
dot-path (ad-setup --only pncli picks the keys); env JIRA_URL / JIRA_EMAIL / JIRA_TOKEN override.
Flavor is detected once and cached in agentdata config: Cloud = REST v3 + Basic(email:token),
Data Center = REST v2 + Bearer PAT (Basic as a fallback). The token never appears in output or errors.

What changed with epic #121 is not what a row means -- `history_rows` and the column set are untouched -- but how
rows are fetched and how the client behaves when the fetch goes wrong on request 1,900 of 2,000.

* **The request policy moved to `jira_http`.** `request()` used to retry 429 and 503 and nothing else, so a 502
  from the tenant's proxy or a socket timeout on page 40 of 80 raised on the spot and threw away every page
  already fetched. Now `classify()` names the failure, only idempotent calls are replayed (`transition()` posts
  with `idempotent=False`, because a replayed transition moves an issue twice), backoff is jittered so the fleet's
  tiles do not retry in lockstep, `Retry-After` wins up to a cap, and a per-run `RequestBudget` stops a runaway
  pull with an error naming what it spent instead of hammering the human's shared token until the tenant does.
  Atlassian's rate-limit headers are read on **every** response, error responses included -- a 429 carries them
  and that is exactly the moment they matter -- so the client can pause *before* it is refused.

* **`iter_changelog()` is the one fetch path.** `changelog()` and `bulk_changelog()` are thin wrappers that
  `list()` it, kept because their callers and tests predate this. The iterator yields rows instead of building a
  list, which is what lets the CLI stream a 100,000-row pull to disk with one chunk in memory.

* **The bulkfetch fallback announces its cost.** A 400 caused by one bad key used to turn three requests into
  three thousand, silently -- the single fastest way to get a shared token throttled. Now a 400 names the keys it
  rejects, they are dropped into `bulk_meta["skipped_keys"]` and the chunk is retried; a 404/405 falls back once
  for the whole run and says how many requests that implies; and a fallback that cannot fit in the budget raises
  `JiraBudgetError` *before* starting a run that cannot finish.

* **Ordering is a guarantee, not a final sort.** See `iter_changelog`.
"""
from __future__ import annotations
import base64
import getpass
import http.client
import json
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
from .. import textio
from .. import config as C
from .jira_http import (USER_AGENT, HINTS, JiraError, JiraHTTPError, JiraBudgetError, RateLimit, RequestBudget,
                        Stats, backoff_seconds, classify, retry_after_seconds)

__all__ = ["USER_AGENT", "HINTS", "JiraError", "JiraHTTPError", "JiraBudgetError", "JiraPartialError",
           "Flavor", "CLOUD", "DC_BEARER", "DC_BASIC", "Creds", "Jira", "load_credentials", "detect_flavor",
           "remember_flavor", "history_rows", "pin_fields", "resolve_field_ids", "parse_ts",
           "RequestBudget", "RateLimit", "Stats"]

_HINTS = HINTS          # the old spelling, kept so nothing that reads it has to move

# Atlassian's own ceilings, and one floor of ours. 1,000 issues x 1,000 changes is the largest page the API
# allows and is precisely the page that times out on deep histories, so the defaults (200 / 500, in
# `iter_changelog`) sit well under them; 50 is the smallest page worth asking for once the shrink has halved a
# few times -- below that the per-request overhead costs more than the big page ever did.
MAX_BULK_ISSUES = 1000
MAX_BULK_PAGE = 10000
MIN_BULK_PAGE = 50
MAX_FIELD_IDS = 10      # per bulkfetch call; more than this is a second call, not a truncation

# `key in (...)` batching for id -> key resolution. 200 keys is roughly 2,400 characters of JQL, comfortably
# inside every documented limit, and halves the number of searches the old 100 needed.
ID_BATCH = 200

# The unit of backoff. `backoff_seconds` turns it into 1, 2, 4, 8, 16, 32 seconds plus up to one second of jitter.
BACKOFF_BASE = 1.0


class JiraPartialError(JiraError):
    """The server answered, and its answer is knowingly short.

    Data Center without the paged changelog endpoint hands back `?expand=changelog` with `total: 412` and a
    hundred histories in the body, and a hundred entries that look like a whole history produce a `committed_points`
    that looks right and is wrong. That refusal predates this epic and stays; what changes is its shape. It now
    carries `reason` in exactly the spelling the CLI prints as `partial: true`, so one code path renders every
    incomplete outcome -- budget, interruption, an unrecoverable HTTP error and this one -- instead of this being
    the single case that escapes as a bare exception nobody catches.
    """

    def __init__(self, msg: str, reason: str, key: str | None = None, have: int = 0, total: int = 0,
                 hint: str = ""):
        super().__init__(msg, hint=hint)
        self.reason, self.key, self.have, self.total = reason, key, have, total


@dataclass(frozen=True)
class Flavor:
    kind: str  # cloud | dc
    auth: str  # basic | bearer
    api: str   # 3 | 2

    @property
    def api_base(self) -> str:
        return f"/rest/api/{self.api}"


CLOUD = Flavor("cloud", "basic", "3")
DC_BEARER = Flavor("dc", "bearer", "2")
DC_BASIC = Flavor("dc", "basic", "2")


@dataclass
class Creds:
    base_url: str
    email: str | None
    token: str
    source: str  # "env" or "pncli:<dot.path>" - where the token came from, never the token

    def __repr__(self) -> str:
        return f"Creds(base_url={self.base_url!r}, email={self.email!r}, token='***', source={self.source!r})"


def load_credentials(cfg: dict | None = None) -> Creds:
    cfg = cfg if cfg is not None else C.load()
    url = os.environ.get("JIRA_URL") or C.get(cfg, "jira.base_url")
    email_ = os.environ.get("JIRA_EMAIL")
    token = os.environ.get("JIRA_TOKEN")
    source = "env"
    if not token:
        p = C.expand(C.get(cfg, "pncli.config_path") or "~/.pncli/config.json")
        keys = C.get(cfg, "pncli.keys", {}) or {}
        if not os.path.exists(p):
            raise JiraError(f"pncli config not found: {C.display_path(p)}",
                            hint="run `pncli config init`, then `ad-setup --only pncli`")
        try:
            pj = json.loads(textio.read_text(p))
        except json.JSONDecodeError:
            raise JiraError("pncli config is not valid JSON", hint="ad-setup --only pncli") from None
        tk = keys.get("jira_token")
        token = C.get(pj, tk) if tk else None
        if not token:
            raise JiraError("no Jira token key configured for the pncli import",
                            hint="ad-setup --only pncli (choose the token key) or set JIRA_TOKEN")
        if not email_ and keys.get("jira_email"):
            email_ = C.get(pj, keys["jira_email"])
        if not url and keys.get("jira_url"):
            url = C.get(pj, keys["jira_url"])
        source = f"pncli:{tk}"
    if not url:
        raise JiraError("no Jira base URL", hint="set JIRA_URL or run ad-setup --only pncli")
    url = str(url).strip()
    if not url.startswith("http"):
        url = "https://" + url
    return Creds(url.rstrip("/"), email_ or None, str(token), source)


def parse_ts(v: Any) -> datetime:
    """Jira timestamps: '2026-08-14T03:12:44.429+0000', '...+10:00', '...Z', epoch seconds or ms (bulkfetch)."""
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+0000"
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(s, fmt).astimezone(timezone.utc)
        except ValueError:
            pass
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


class Jira:
    """One Jira instance, one run's budget, one set of stats.

    The client is deliberately single-threaded and holds no connection pool: the interesting state is the budget
    (`RequestBudget`), the last rate-limit reading (`RateLimit`) and what the run has cost so far (`Stats`), all
    of which the CLI reads after the pull to decide what to print.
    """

    def __init__(self, creds: Creds, flavor: Flavor, timeout: int = 60, ca_bundle: str | None = None,
                 sleep: Callable[[float], None] = time.sleep, opener: Callable | None = None,
                 budget: RequestBudget | None = None, rand: Callable[[], float] = random.random,
                 clock: Callable[[], float] = time.monotonic, max_attempts: int = 6,
                 retry_after_cap: float = 120.0, rate_floor: float = 0.10,
                 log: Callable[[str], None] | None = None):
        self.creds, self.flavor, self.timeout, self.sleep = creds, flavor, timeout, sleep
        self._open = opener or urllib.request.urlopen
        self.ssl_ctx = ssl.create_default_context(cafile=ca_bundle or os.environ.get("AGENTDATA_CA_BUNDLE") or None)
        self.rand, self.clock = rand, clock
        self.max_attempts, self.retry_after_cap, self.rate_floor = max_attempts, retry_after_cap, rate_floor
        self.log = log
        self.stats = Stats()
        self.rate = RateLimit()
        self.budget = budget or RequestBudget()
        # A budget already running belongs to somebody else -- the fleet shares one across tiles (#91) -- and
        # restarting it would hand every new client a fresh 2,000 requests against the same token.
        if self.budget.started_at is None:
            self.budget.start(self.clock())
        # `X-RateLimit-Reset` arrives as an epoch on some tenants, so the arithmetic that turns it into a wait has
        # to happen in the epoch's own frame -- `clock` is monotonic by default and comparing the two would ask
        # the client to sleep for fifty years. Wall time is not injectable through the constructor (the signature
        # is a contract other modules are written against); a test that needs to steer it replaces this attribute.
        self.wall: Callable[[], float] = time.time
        self._rate_paused = False
        self.last_retry_reason: str | None = None
        self.bulk_meta: dict = _fresh_bulk_meta()
        self._bulk_page = MAX_BULK_PAGE

    def __repr__(self) -> str:
        return f"Jira({self.creds.base_url}, {self.flavor.kind}/{self.flavor.auth}/v{self.flavor.api})"

    @property
    def api(self) -> str:
        return self.flavor.api_base

    def _headers(self, has_body: bool) -> dict:
        h = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if has_body:
            h["Content-Type"] = "application/json"
        if self.flavor.auth == "basic":
            raw = f"{self.creds.email or ''}:{self.creds.token}".encode()
            h["Authorization"] = "Basic " + base64.b64encode(raw).decode()
        else:
            h["Authorization"] = "Bearer " + self.creds.token
        return h

    # ---------- the request layer ----------
    def request(self, method: str, path: str, params: dict | None = None, body: Any = None,
                idempotent: bool = True) -> Any:
        """One HTTP call, with the retry policy `jira_http` describes.

        `idempotent` is a property of the *call*, not of the method: `POST /changelog/bulkfetch` asks a question
        and may be replayed, `POST /issue/K/transitions` moves an issue and must not. Marking it by method would
        either replay transitions or refuse to recover a bulkfetch page, and both are worse than one flag.

        The failing page names itself. A second 500 on the same page is a real server error rather than the
        transient one Jira hands out for changelog pages, and when that raises, the message carries the page's
        `startAt` or `nextPageToken` so a human reading the error knows where the pull died rather than only that
        it did.
        """
        url = self.creds.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        where = path + _page_marker(params, body)
        self.last_retry_reason = None
        spent_once = False
        attempt = 0
        while True:
            self._pause_for_rate_limit(where)
            self.budget.spend_request(where, self.clock())
            self.stats.requests = self.budget.requests
            req = urllib.request.Request(url, data=data, method=method, headers=self._headers(data is not None))
            try:
                with self._open(req, timeout=self.timeout, context=self.ssl_ctx) as r:
                    self._read_rate(getattr(r, "headers", None))
                    raw = r.read()
            except urllib.error.HTTPError as e:
                self._read_rate(e.headers)                     # a 429 carries them; that is when they matter
                verdict = classify(exc=e)
                if verdict == "retry_once":
                    verdict, spent_once = ("fatal" if spent_once else "retry"), True
                if verdict != "retry" or not idempotent or attempt + 1 >= self.max_attempts:
                    self._tick()
                    raise JiraHTTPError(e.code, where, _error_body(e)) from None
                wait = retry_after_seconds(e.headers, self.retry_after_cap)
                if wait is None:
                    wait = backoff_seconds(attempt, BACKOFF_BASE, self.retry_after_cap, self.rand)
                self._charge_retry(where, f"HTTP {e.code}", wait)
            except (OSError, http.client.HTTPException) as e:  # timeout, reset, remote disconnect, bad hostname
                if classify(exc=e) != "retry" or not idempotent or attempt + 1 >= self.max_attempts:
                    self._tick()
                    raise self._transport_error(e) from None
                self._charge_retry(where, _transport_reason(e),
                                   backoff_seconds(attempt, BACKOFF_BASE, self.retry_after_cap, self.rand))
            else:
                self._tick()
                return json.loads(raw) if raw.strip() else None
            attempt += 1

    def _charge_retry(self, where: str, reason: str, wait: float) -> None:
        self.budget.spend_retry(where, self.clock())
        self.stats.retries = self.budget.retries
        self.last_retry_reason = reason
        if wait > 0:
            self._say(f"{reason} on {where}: retrying in {wait:.1f}s")
            self.sleep(wait)
            self.stats.waited_seconds += wait
        self._tick()

    def _pause_for_rate_limit(self, where: str) -> None:
        """Slow down before being refused, once per rate-limit reading.

        Learning about a quota from a 429 means the request was already spent and already counted against the
        human's token. Cloud says how much is left on every response, so the last few requests before a limit
        become a pause instead of a rejection. Data Center below 8.6 sends no headers, `should_pause()` is then
        False, and such a run stays reactive exactly as it was.
        """
        if self._rate_paused or not self.rate.should_pause(self.rate_floor):
            return
        self._rate_paused = True                     # one pause per reading, or a stale header loops
        secs = self.rate.pause_seconds(self.wall())
        if secs <= 0:
            return
        self._say(f"rate limit: {self.rate.remaining} of {self.rate.limit} left, waiting {secs:.0f}s")
        self.sleep(secs)
        self.stats.rate_limit_waits += 1
        self.stats.waited_seconds += secs
        self._tick()

    def _read_rate(self, headers: Any) -> None:
        self.rate = RateLimit.from_headers(headers, self.wall())
        self._rate_paused = False

    def _tick(self) -> None:
        self.stats.elapsed_seconds = self.budget.elapsed(self.clock())

    def _transport_error(self, e: BaseException) -> JiraError:
        return JiraError(f"network error reaching {self.creds.base_url}: {getattr(e, 'reason', None) or e}",
                         hint="check VPN / proxy (HTTPS_PROXY) / AGENTDATA_CA_BUNDLE")

    def _say(self, msg: str) -> None:
        """Progress and warnings go to stderr -- which is what `log` is -- and stdout stays TOON only."""
        if self.log:
            self.log(msg)

    def get(self, path: str, params: dict | None = None) -> Any:
        return self.request("GET", path, params)

    def post(self, path: str, body: Any, params: dict | None = None, idempotent: bool = True) -> Any:
        return self.request("POST", path, params, body, idempotent=idempotent)

    def myself(self) -> dict:
        return self.get(f"{self.api}/myself")

    # ---------- pagination ----------
    def _pages(self, path: str, params: dict | None = None, values_key: str = "values",
               page_size: int = 100) -> Iterator[tuple[list, str]]:
        """`(values, marker)` per page, where the marker names the page for a progress line or an error."""
        start = 0
        while True:
            page = self.get(path, {**(params or {}), "startAt": start, "maxResults": page_size}) or {}
            values = page.get(values_key) or []
            yield values, f" startAt={start}"
            if not values or page.get("isLast") is True:
                return
            start += page.get("maxResults") or len(values)
            total = page.get("total")
            if total is not None and start >= int(total):
                return

    def paged(self, path: str, params: dict | None = None, values_key: str = "values", page_size: int = 100) -> Iterator[dict]:
        """startAt/maxResults paging. Uses the *echoed* maxResults (the server may cap the request)."""
        for values, _ in self._pages(path, params, values_key, page_size):
            yield from values

    def paged_token(self, path: str, params: dict | None = None, body: dict | None = None,
                    values_key: str = "issues") -> Iterator[dict]:
        """nextPageToken paging (cloud /search/jql and /changelog/bulkfetch); GET when body is None else POST."""
        token = None
        while True:
            extra = {"nextPageToken": token} if token else {}
            if body is not None:
                page = self.post(path, {**body, **extra}, params) or {}
            else:
                page = self.get(path, {**(params or {}), **extra}) or {}
            values = page.get(values_key) or []
            yield from values
            token = page.get("nextPageToken")
            if not token or not values or page.get("isLast") is True:
                return

    # ---------- metadata ----------
    def fields(self) -> list[dict]:
        return self.get(f"{self.api}/field") or []

    def statuses(self) -> dict[str, str]:
        """{status id: statusCategory key} plus {lower-case status name: key}. `done` is the category to test."""
        out: dict[str, str] = {}
        for st in self.get(f"{self.api}/status") or []:
            key = ((st.get("statusCategory") or {}).get("key") or "").lower()
            if st.get("id") is not None:
                out[str(st["id"])] = key
            if st.get("name"):
                out[str(st["name"]).lower()] = key
        return out

    # ---------- issues ----------
    def search(self, jql: str, fields: list[str], max_results: int = 5000) -> list[dict]:
        """Cloud: GET /rest/api/3/search/jql (token paging; /search was retired) with /search fallback. DC: /rest/api/2/search."""
        flds = ",".join(fields)
        out: list[dict] = []
        if self.flavor.kind == "cloud":
            try:
                it = self.paged_token(f"{self.api}/search/jql", {"jql": jql, "fields": flds, "maxResults": 100})
                for iss in it:
                    out.append(iss)
                    if len(out) >= max_results:
                        break
                return out
            except JiraHTTPError as e:
                if e.status not in (404, 410, 405):
                    raise
        for iss in self.paged(f"{self.api}/search", {"jql": jql, "fields": flds}, values_key="issues"):
            out.append(iss)
            if len(out) >= max_results:
                break
        return out

    def issue(self, key: str, fields: list[str] | None = None, expand: str | None = None) -> dict:
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        if expand:
            params["expand"] = expand
        return self.get(f"{self.api}/issue/{key}", params or None)

    # ---------- workflow ----------
    def transitions(self, key: str) -> list[dict]:
        """What this ONE issue can do next. The workflow belongs to the issue type, so a Story's answer says
        nothing about a Task's; `expand=transitions.fields` also reveals the screens that would 400 the POST."""
        data = self.get(f"{self.api}/issue/{key}/transitions", {"expand": "transitions.fields"}) or {}
        return data.get("transitions") or []

    def transition(self, key: str, transition_id: str, fields: dict | None = None, comment: str | None = None) -> None:
        """Never replayed. A transition that times out may well have been applied, and a second POST moves the
        issue twice or posts the comment twice -- so this is the one call that takes its 5xx and reports it."""
        body: dict = {"transition": {"id": str(transition_id)}}
        if fields:
            body["fields"] = fields
        if comment:
            from ..jira_workflow import adf
            body["update"] = {"comment": [{"add": {"body": adf(comment) if self.flavor.api == "3" else comment}}]}
        self.post(f"{self.api}/issue/{key}/transitions", body, idempotent=False)

    # ---------- changelog ----------
    def iter_changelog(self, keys: list[str], field_ids: list[str] | None = None, name_to_id: dict | None = None,
                       id_to_key: dict | None = None, use_bulk: bool = True, bulk_issues: int = 200,
                       bulk_page: int = 500, on_event: Callable[[str, dict], None] | None = None) -> Iterator[dict]:
        """Changelog rows for `keys`, yielded as they are parsed. The one fetch path; everything else wraps it.

        **Ordering guarantee.** Keys come out in the order they were given; within one key rows ascend by
        `(created_utc, changelog_id)`; and a key's rows are all emitted before the next key's first row. This is
        enforced at fetch time, not by sorting at the end, because the caller streams rows to disk as they arrive
        and can never re-read them. Bulkfetch groups histories by issue but states no order within an issue across
        pages, the per-issue Cloud endpoint is ascending by `created`, and Data Center's `?expand=changelog` is
        newest first -- so the pages of one *chunk* are collected per issue until that chunk is complete, then
        sorted per key and yielded.

        **The memory bound that follows from it** is one chunk: `bulk_issues` issues and their histories, not the
        run. That is the ceiling the streaming slice measures, and it is why `bulk_issues` defaults to 200 rather
        than the 1,000 the API allows.

        `on_event(kind, payload)` is the progress channel: `"page"` `{path, rows}`, `"issue_done"` `{key, rows}`,
        `"fallback"` `{reason, requests}`, `"shrink"` `{bulk_page}`, `"skipped"` `{keys}`, `"truncated"`
        `{key, have, total, reason}`. Anything the caller does not recognise it can ignore.
        """
        keys = list(keys)
        self.bulk_meta = _fresh_bulk_meta()
        if not keys:
            return
        if not use_bulk or self.flavor.kind != "cloud":
            yield from self._per_issue(keys, name_to_id, on_event)
            return
        yield from self._bulk(keys, field_ids, name_to_id, id_to_key, bulk_issues, bulk_page, on_event)

    def changelog(self, key: str, name_to_id: dict | None = None) -> list[dict]:
        """All change items of one issue as flat rows (see history_rows). DC without the paged endpoint falls back to
        ?expand=changelog and refuses to silently return a truncated history."""
        return list(self.iter_changelog([key], name_to_id=name_to_id, use_bulk=False))

    def bulk_changelog(self, keys: list[str], field_ids: list[str] | None = None, name_to_id: dict | None = None,
                       id_to_key: dict | None = None) -> list[dict]:
        """Cloud bulkfetch; falls back to per-issue when the endpoint is absent, and says what that costs."""
        return list(self.iter_changelog(keys, field_ids=field_ids, name_to_id=name_to_id, id_to_key=id_to_key))

    # ---------- changelog: the per-issue path ----------
    def _per_issue(self, keys: list[str], name_to_id: dict | None, on_event: Callable | None) -> Iterator[dict]:
        for key in keys:
            rows = self._issue_rows(key, name_to_id, on_event)
            rows.sort(key=_order)
            yield from rows
            _fire(on_event, "issue_done", {"key": key, "rows": len(rows)})

    def _issue_rows(self, key: str, name_to_id: dict | None, on_event: Callable | None) -> list[dict]:
        rows: list[dict] = []
        path = f"{self.api}/issue/{key}/changelog"
        try:
            for values, marker in self._pages(path):
                page = [r for h in values for r in history_rows(key, h, name_to_id)]
                rows.extend(page)
                _fire(on_event, "page", {"path": path + marker, "rows": len(page)})
        except JiraHTTPError as e:
            # A 404 on the *first* page means this Data Center has no paged changelog endpoint. A 404 after rows
            # have arrived means something else entirely, and re-fetching through ?expand would duplicate them.
            if e.status != 404 or self.flavor.kind == "cloud" or rows:
                raise
            rows = self._expand_rows(key, name_to_id, on_event)
        return rows

    def _expand_rows(self, key: str, name_to_id: dict | None, on_event: Callable | None) -> list[dict]:
        cl = (self.issue(key, ["summary"], expand="changelog") or {}).get("changelog") or {}
        hist = cl.get("histories") or []
        total = cl.get("total")
        rows = [r for h in hist for r in history_rows(key, h, name_to_id)]
        if total is not None and int(total) > len(hist):
            reason = f"expand=changelog truncated: {len(hist)} of {total}"
            _fire(on_event, "truncated", {"key": key, "have": len(hist), "total": int(total), "reason": reason})
            raise JiraPartialError(f"changelog truncated for {key}: {len(hist)} of {total} entries",
                                   reason=reason, key=key, have=len(hist), total=int(total),
                                   hint="this Jira lacks the paged changelog endpoint; use the Teradata history "
                                        "for older events") from None
        _fire(on_event, "page", {"path": f"{self.api}/issue/{key}?expand=changelog", "rows": len(rows)})
        return rows

    # ---------- changelog: the bulkfetch path ----------
    def _bulk(self, keys: list[str], field_ids: list[str] | None, name_to_id: dict | None,
              id_to_key: dict | None, bulk_issues: int, bulk_page: int,
              on_event: Callable | None) -> Iterator[dict]:
        chunk_size = max(1, min(int(bulk_issues), MAX_BULK_ISSUES))
        # MIN_BULK_PAGE is the floor the *shrink* stops at, not a floor on what the operator may ask for: a
        # deliberately tiny --bulk-page is how someone reproduces a paging bug, and overriding it would hide one.
        self._bulk_page = max(1, min(int(bulk_page), MAX_BULK_PAGE))
        self.bulk_meta["bulk_page_final"] = self._bulk_page
        batches = _field_batches(field_ids)
        id_map = self._resolve_ids(keys, id_to_key)
        fallback_all = False
        for start in range(0, len(keys), chunk_size):
            chunk = keys[start:start + chunk_size]
            if fallback_all:
                yield from self._per_issue(chunk, name_to_id, on_event)
                continue
            try:
                rows_by_ref, kept = self._bulk_chunk(chunk, batches, name_to_id, id_map, on_event)
            except _BulkUnavailable as u:
                self._announce_fallback(u.reason, keys[start:], on_event)
                fallback_all = True
                yield from self._per_issue(chunk, name_to_id, on_event)
                continue
            except _ChunkRejected as u:
                self._announce_fallback(u.reason, u.keys, on_event)
                yield from self._per_issue(u.keys, name_to_id, on_event)
                continue
            for ref in kept:
                rows = rows_by_ref.pop(ref, [])
                rows.sort(key=_order)
                yield from rows
                _fire(on_event, "issue_done", {"key": ref, "rows": len(rows)})
            for ref, rows in rows_by_ref.items():      # an issue id no search could map back to a key: never drop it
                rows.sort(key=_order)
                yield from rows
                _fire(on_event, "issue_done", {"key": ref, "rows": len(rows)})

    def _bulk_chunk(self, chunk: list[str], batches: list[list[str] | None], name_to_id: dict | None,
                    id_map: dict, on_event: Callable | None) -> tuple[dict[str, list[dict]], list[str]]:
        """One chunk, every field batch, de-duplicated and grouped by issue. Raises the two fallback signals."""
        keys = list(chunk)
        dropped = False
        while True:
            seen: set[tuple] = set()
            rows_by_ref: dict[str, list[dict]] = {}
            try:
                for batch in batches:
                    for values in self._bulk_pages(keys, batch, on_event):
                        self._collect(values, rows_by_ref, seen, id_map, name_to_id, on_event)
                return rows_by_ref, keys
            except JiraHTTPError as e:
                if e.status in (404, 405):
                    raise _BulkUnavailable(f"HTTP {e.status} on {e.path}") from None
                if e.status != 400:
                    raise
                bad = _invalid_keys(str(e), keys)
                if not bad or dropped:
                    raise _ChunkRejected(f"HTTP 400 on {e.path}", keys) from None
                keys = [k for k in keys if k not in bad]
                dropped = True
                self.bulk_meta["skipped_keys"].extend(sorted(bad))
                _fire(on_event, "skipped", {"keys": sorted(bad)})
                self._say(f"bulkfetch rejected {len(bad)} key(s) as invalid ({', '.join(sorted(bad))}); "
                          f"retrying the chunk without them")
                if not keys:
                    return {}, []

    def _bulk_pages(self, refs: list[str], field_ids: list[str] | None,
                    on_event: Callable | None) -> Iterator[list]:
        """Token-paged bulkfetch that shrinks its page when a page proves too heavy to answer.

        A timeout or a 5xx on a 1,000-change page is a size problem, not a server problem: the default 60-second
        timeout is per request and that page is exactly the one that hits it. So the page halves -- for the rest
        of the run, because the next chunk's histories are no shallower -- and the failing page is tried once more
        at the smaller size before the failure is reported. `bulk_page_final` in `bulk_meta` says where it landed.
        """
        path = f"{self.api}/changelog/bulkfetch"
        token = None
        while True:
            page: dict = {}
            for retry_smaller in (True, False):
                body: dict = {"issueIdsOrKeys": list(refs), "maxResults": self._bulk_page}
                if field_ids:
                    body["fieldIds"] = list(field_ids)
                if token:
                    body["nextPageToken"] = token
                before = self.stats.retries
                try:
                    page = self.post(path, body) or {}
                except JiraHTTPError as e:
                    if retry_smaller and e.status >= 500 and self._shrink(on_event):
                        continue
                    raise
                except JiraBudgetError:
                    raise
                except JiraError:
                    if retry_smaller and self._shrink(on_event):
                        continue
                    raise
                if self.stats.retries > before and _heavy(self.last_retry_reason):
                    self._shrink(on_event)             # the request layer recovered it; the next page is smaller
                break
            values = page.get("issueChangeLogs") or []
            yield values
            token = page.get("nextPageToken")
            if not token or not values or page.get("isLast") is True:
                return

    def _collect(self, values: list, rows_by_ref: dict[str, list[dict]], seen: set, id_map: dict,
                 name_to_id: dict | None, on_event: Callable | None) -> None:
        """Turn one bulkfetch page into rows, dropping the ones already seen in this chunk.

        The de-dup key is a *row*, not a history, for two reasons. Bulkfetch repeats a whole history across
        consecutive pages (JRACLOUD-94906), which a row key removes just as well; and more than ten field ids
        means a second call over the same issues, whose histories carry the same ids with different items -- a
        history key would throw the eleventh and twelfth fields away, which is the silent `[:10]` truncation this
        replaced. Tuples of four small values, one chunk's worth at a time.
        """
        n = 0
        for entry in values:
            iid = str(entry.get("issueId"))
            ref = id_map.get(iid) or iid
            bucket = rows_by_ref.setdefault(ref, [])
            for h in entry.get("changeHistories") or []:
                cid = str(h.get("id"))
                for pos, row in enumerate(history_rows(ref, h, name_to_id)):
                    sig = (iid, cid, str(row.get("field_id")), pos)
                    if sig in seen:
                        continue
                    seen.add(sig)
                    bucket.append(row)
                    n += 1
        _fire(on_event, "page", {"path": f"{self.api}/changelog/bulkfetch", "rows": n})

    def _shrink(self, on_event: Callable | None) -> bool:
        if self._bulk_page <= MIN_BULK_PAGE:
            return False
        self._bulk_page = max(MIN_BULK_PAGE, self._bulk_page // 2)
        self.bulk_meta["bulk_page_final"] = self._bulk_page
        _fire(on_event, "shrink", {"bulk_page": self._bulk_page})
        self._say(f"bulkfetch page too heavy; halving to maxResults {self._bulk_page} for the rest of the run")
        return True

    def _resolve_ids(self, keys: list[str], id_to_key: dict | None) -> dict:
        """id -> key, for the `issueId` bulkfetch answers with. Nothing is looked up twice.

        The caller usually already knows: `sprint-replay` has the search it ran to pick the issues, and the CLI's
        cache partition ran `search(jql, ["key", "updated"])` for its freshness check. Passing that map in makes
        these searches disappear on the common path; what is left batches at 200 keys per `key in (...)`.
        """
        id_map = dict(id_to_key or {})
        known = {str(v) for v in id_map.values()}
        missing = [k for k in keys if k not in known]
        for i in range(0, len(missing), ID_BATCH):
            batch = missing[i:i + ID_BATCH]
            for iss in self.search("key in (" + ",".join(batch) + ")", ["key"]):
                id_map[str(iss.get("id"))] = iss.get("key")
        return id_map

    def _announce_fallback(self, reason: str, pending: list[str], on_event: Callable | None) -> None:
        """Say what the fallback costs, and refuse to start one the budget cannot finish.

        One bulkfetch becoming one request per issue is the cheapest way there is to get a shared token throttled,
        and it used to happen without a word. Finding out 2,000 requests in that the run cannot finish is worse
        than being told before it starts, which is the only reason this checks the budget rather than letting
        `spend_request` discover it later.
        """
        n = len(pending)
        if self.budget.would_exceed(n):
            err = JiraBudgetError("requests", self.budget.requests, self.budget.elapsed(self.clock()), reason)
            err.hint = (f"the per-issue fallback needs about {n} more requests and only "
                        f"{self.budget.remaining_requests()} are left; rerun with "
                        f"--max-requests {self.budget.requests + n}, a narrower JQL, or --no-bulk / --bulk-issues")
            raise err
        self.bulk_meta["fallback"] = True
        self.bulk_meta["fallback_reason"] = reason
        _fire(on_event, "fallback", {"reason": reason, "requests": n})
        self._say(f"bulkfetch fell back to one request per issue ({reason}): about {n} more requests")

    # ---------- agile ----------
    def sprint(self, sprint_id: int) -> dict:
        return self.get(f"/rest/agile/1.0/sprint/{sprint_id}")

    def board_sprints(self, board_id: int, state: str | None = None) -> list[dict]:
        return list(self.paged(f"/rest/agile/1.0/board/{board_id}/sprint", {"state": state} if state else None, page_size=50))

    def sprint_issues(self, sprint_id: int, fields: list[str]) -> list[dict]:
        return list(self.paged(f"/rest/agile/1.0/sprint/{sprint_id}/issue", {"fields": ",".join(fields)}, values_key="issues"))

    def sprintreport(self, board_id: int, sprint_id: int) -> dict:
        """Undocumented GreenHopper endpoint behind the Sprint Report UI. Cross-check only, never truth."""
        return self.get("/rest/greenhopper/1.0/rapid/charts/sprintreport", {"rapidViewId": board_id, "sprintId": sprint_id})


class _BulkUnavailable(Exception):
    """bulkfetch is not on this instance (404/405): fall back once, for the whole run."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _ChunkRejected(Exception):
    """bulkfetch refused this chunk (400) and dropping the keys it named did not help: fall back for it alone."""

    def __init__(self, reason: str, keys: list[str]):
        super().__init__(reason)
        self.reason, self.keys = reason, list(keys)


def _fresh_bulk_meta() -> dict:
    return {"bulk_page_final": None, "skipped_keys": [], "fallback": False, "fallback_reason": None}


def _fire(on_event: Callable | None, kind: str, payload: dict) -> None:
    if on_event:
        on_event(kind, payload)


def _order(row: dict) -> tuple:
    """`(created_utc, changelog_id)`, without ever comparing an int to a string.

    `history_rows` turns a numeric changelog id into an int -- so 9 sorts before 10 rather than after it -- and
    passes a non-numeric one through unchanged. Both shapes can appear in one pull if a tenant ever answers with
    something else, and a `TypeError` mid-sort would lose the run for a cosmetic reason.
    """
    cid = row.get("changelog_id")
    return (row.get("created_utc") or "", (0, cid) if isinstance(cid, int) else (1, str(cid)))


def _field_batches(field_ids: list[str] | None) -> list[list[str] | None]:
    """Ten field ids per bulkfetch call, and the eleventh is a second call rather than a silent truncation."""
    ids: list[str] = []
    for f in field_ids or []:
        if f and f not in ids:
            ids.append(f)
    if not ids:
        return [None]
    return [ids[i:i + MAX_FIELD_IDS] for i in range(0, len(ids), MAX_FIELD_IDS)]


def _page_marker(params: dict | None, body: Any = None) -> str:
    """" startAt=200" or " nextPageToken=t7" -- which page of a long pull this request is, for an error message."""
    for src in (params, body):
        if not isinstance(src, dict):
            continue
        for k in ("startAt", "nextPageToken"):
            v = src.get(k)
            if v is not None and v != "":
                return f" {k}={v}"
    return ""


def _error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read()[:300].decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _invalid_keys(message: str, keys: list[str]) -> set[str]:
    """The keys a 400 names as invalid, intersected with the ones we asked for.

    Jira says `The issue key 'RDSD-9999' does not exist for the field 'key'.` and variations of it; rather than
    matching that sentence, take every key-shaped token in the message and keep only those this chunk actually
    sent. A message that names something else drops nothing, which is the safe direction: dropping a key the
    operator asked for would produce a short history that looks complete.
    """
    found = {t.upper() for t in re.findall(r"[A-Za-z][A-Za-z0-9_]*-\d+", message)}
    return {k for k in keys if str(k).upper() in found}


def _heavy(reason: str | None) -> bool:
    """Was the retry the request layer just did about a page too big to answer, rather than a rate limit?"""
    if not reason:
        return False
    return reason in ("timeout", "reset", "disconnected") or reason.startswith("HTTP 5")


def _transport_reason(e: BaseException) -> str:
    if isinstance(e, (TimeoutError,)) or isinstance(getattr(e, "reason", None), TimeoutError):
        return "timeout"
    if isinstance(e, ConnectionResetError) or isinstance(getattr(e, "reason", None), ConnectionResetError):
        return "reset"
    return "disconnected"


def detect_flavor(creds: Creds, cfg: dict | None = None, redetect: bool = False, **kw) -> tuple[Jira, dict]:
    """Return (client, /myself payload). Uses the cached flavor unless redetect."""
    cfg = cfg if cfg is not None else C.load()
    if not redetect and all(C.get(cfg, f"jira.{k}") for k in ("flavor", "auth", "api")):
        fl = Flavor(C.get(cfg, "jira.flavor"), C.get(cfg, "jira.auth"), str(C.get(cfg, "jira.api")))
        j = Jira(creds, fl, **kw)
        return j, j.myself()
    host = (urllib.parse.urlparse(creds.base_url).hostname or "").lower()
    candidates = [CLOUD] if host.endswith((".atlassian.net", ".jira.com")) else [DC_BEARER, DC_BASIC, CLOUD]
    errors: list[str] = []
    for fl in candidates:
        c = creds
        if fl.auth == "basic" and not creds.email:
            if fl.kind == "cloud":
                errors.append("cloud Basic auth needs an email (JIRA_EMAIL or the email key in ad-setup --only pncli)")
                continue
            c = Creds(creds.base_url, getpass.getuser(), creds.token, creds.source)
        j = Jira(c, fl, **kw)
        try:
            return j, j.myself()
        except JiraHTTPError as e:
            if e.status in (401, 403, 404, 400):
                errors.append(f"{fl.kind}/{fl.auth}/v{fl.api}: HTTP {e.status}")
                continue
            raise
    raise JiraError("could not authenticate to Jira with the configured token: " + "; ".join(errors),
                    hint="check the token key (ad-setup --only pncli) or set JIRA_TOKEN / JIRA_EMAIL")


def remember_flavor(cfg: dict, j: Jira) -> None:
    C.put(cfg, "jira.base_url", j.creds.base_url)
    C.put(cfg, "jira.flavor", j.flavor.kind)
    C.put(cfg, "jira.auth", j.flavor.auth)
    C.put(cfg, "jira.api", j.flavor.api)
    C.stamp(cfg, "jira")


def history_rows(key: str, h: dict, name_to_id: dict | None = None) -> list[dict]:
    """One row per change item. Snake-case columns; `toString` is read even though Atlassian's schema omits it."""
    created = parse_ts(h.get("created")).strftime("%Y-%m-%dT%H:%M:%SZ") if h.get("created") is not None else None
    author = (h.get("author") or {}).get("displayName")
    cid = h.get("id")
    cid = int(cid) if str(cid).isdigit() else cid
    rows = []
    nm = name_to_id or {}
    for it in h.get("items") or []:
        fname = it.get("field")
        fid = it.get("fieldId") or nm.get(fname) or nm.get(str(fname).lower()) or fname
        rows.append({"key": key, "changelog_id": cid, "created_utc": created, "author": author,
                     "field": fname, "field_id": fid,
                     "field_type": it.get("fieldtype"), "from_id": it.get("from"), "from_str": it.get("fromString"),
                     "to_id": it.get("to"), "to_str": it.get("toString")})
    return rows


def pin_fields(fields_json: list[dict]) -> dict:
    """Sprint = the field whose schema.custom ends with :gh-sprint (fallback: named Sprint); story points = the ids of
    'Story Points' (company-managed) then 'Story point estimate' (team-managed). Ids are per Jira instance."""
    sprint = None
    points: list[str] = []
    names = {}
    for f in fields_json:
        fid, name = f.get("id"), str(f.get("name") or "")
        names[name.lower()] = fid
        if str((f.get("schema") or {}).get("custom", "")).endswith(":gh-sprint"):
            sprint = fid
    sprint = sprint or names.get("sprint")
    for n in ("story points", "story point estimate"):
        if names.get(n) and names[n] not in points:
            points.append(names[n])
    return {"sprint": sprint, "story_points": points, "name_to_id": {n: i for n, i in names.items()}}


def resolve_field_ids(names: list[str], fields_json: list[dict]) -> list[str]:
    """User-typed field names (status, Sprint, "Story Points") -> field ids; system fields keep their name."""
    lookup = {str(f.get("name") or "").lower(): f.get("id") for f in fields_json}
    out = []
    for n in names:
        n = n.strip().strip('"')
        fid = lookup.get(n.lower()) or (n if n.startswith("customfield_") else n.lower())
        if fid not in out:
            out.append(fid)
    return out
