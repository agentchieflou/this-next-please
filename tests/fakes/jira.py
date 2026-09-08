"""A deterministic fake Jira behind the `opener` seam: long histories, both flavors, scripted faults.

Every question epic #121 asks was unanswerable on CI. `tests/test_jira_api.py` drives the client with an in-memory
opener over three short, well-formed pages, so nothing in this repository has ever seen a 429 on page 40 of 80, a
500 that clears on retry, a socket timeout, a page that forgot `isLast`, a server that capped `maxResults` at 100
when 1,000 was asked, a bulkfetch page that repeats a history (JRACLOUD-94906), or a 100,000-row pull. Four
behaviours of today's client are the reason this fake exists, and each of them is reproducible here in one line of
fault script:

* **a 500 on page 3 loses the run.** `Jira.request` retries 429 and 503 only; a 500, 502, 504, a reset or a socket
  timeout on a middle page raises, and every page already fetched is thrown away (#123).
* **a 400 on `/changelog/bulkfetch` multiplies requests.** `bulk_changelog` falls back to one `changelog()` per
  issue without saying so, so a 3,000-issue JQL makes 3,000+ requests where the operator budgeted 3 — the exact
  shape that gets the human's shared token throttled (#126).
* **memory is unbounded.** Every caller does `list(...)` and nothing reaches disk until the very end (#124).
* **a short Data Center history is not marked partial.** `?expand=changelog` hands back 100 of 1,000 entries and
  only `changelog()` itself notices; nothing the operator reads says `partial: true` (#124).

This is not a mock. Response shapes are copied from the real API, honouring the rule in `tests/fakes/__init__.py`
that a fake which invents output is worth less than no fake — it would only prove the code handles a shape nobody
has ever seen. What *is* invented is the content: keys, authors, timestamps. That content is generated on demand
rather than typed out, so a 500 x 200 corpus costs nothing until somebody asks for a page (`Corpus`); a budget test
measures the peak, and the fake must never be the thing that blows it.

Unlike the rest of the harness this fake materialises no executable and touches no PATH. It plugs into the
`opener` argument `agentdata/connectors/jira_api.py` already takes, so the whole wiring is::

    fake = FakeJira(issues=50, histories=300)
    j = fake.client()                                   # or Jira(creds, flavor, opener=fake.opener)
    rows = j.changelog("RDSD-1")

No network, no sockets, no clock. `fake.sleep` is the injected sleeper: it records the seconds and advances the
fake's own clock, so a run that would have waited eleven minutes finishes instantly and a test can assert the wait.

## Fault scripts

A fault script is an ordered list of `(match, nth, fault)` triples, read left to right; the first entry that fires
on a request wins.

* `match` is a plain substring of `"<METHOD> <path>?<query>"`. Substring means substring: `"changelog"` also
  matches `POST /rest/api/3/changelog/bulkfetch`, so say `"issue/"` or `"bulkfetch"` when you mean one of them.
  `""`, `"any"` and `"*"` match every request.
* `nth` selects which matching occurrence fires, counted 1-based per entry: an `int` fires once, a tuple or list of
  ints fires on each of those, and `"every"` (or `None`) fires on every one.
* `fault` is one of:

  ===========================  ===========================================================================
  `500` (any int)              that HTTP status, with Jira's `errorMessages` body
  `429`                        429 with a numeric `Retry-After`
  `"429 date"`                 429 with an HTTP-date `Retry-After`, the form `email.utils` has to parse
  `"400 invalid key NOPE-1"`   400 whose body names the key, as a bad `key in (...)` JQL really does
  `"timeout"`                  `socket.timeout` — the failure that loses a run today
  `"reset"`                    `ConnectionResetError`
  `"interrupt"`                `KeyboardInterrupt`, for the streaming slice's checkpoint
  `"drop isLast"`              the page comes back without `isLast`
  `"cap maxResults 100"`       the server ignores the asked-for page size and echoes its own
  `"duplicate histories"`      the page repeats its first entry at the end
  `"shuffle pages"`            the page's values come back in the wrong order
  ===========================  ===========================================================================

So `("issue/", 3, 500)` reads "the third per-issue request answers 500", `("bulkfetch", 2, "timeout")` reads "the
second bulkfetch times out", and `("", 30, 429)` reads "the thirtieth request of any kind is rate limited". A
constructor flag, `bulk_duplicate=True`, reproduces the *cross-page* duplicate of JRACLOUD-94906, which no
single-page fault can express.

`fake.requests` records every request — method, path, query, parsed body, headers. The `Authorization` header is
recorded as `"REDACTED"`: even a fake token must never be written into a fixture, a log or a failure message.
"""
from __future__ import annotations

import email.message
import email.utils
import io
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

# A dummy that is obviously not a credential. Nothing here ever holds a real one.
FAKE_TOKEN = "fake-token-not-a-secret"
FAKE_EMAIL = "luna@example.invalid"

SPRINT_FIELD = "customfield_10020"
POINTS_FIELD = "customfield_10026"
POINTS_ESTIMATE_FIELD = "customfield_10016"

# `pin_fields` looks for schema.custom ending ':gh-sprint' and the two story-point names, in this order.
FIELDS: list[dict] = [
    {"id": "summary", "key": "summary", "name": "Summary", "custom": False, "navigable": True,
     "searchable": True, "schema": {"type": "string", "system": "summary"}},
    {"id": "created", "key": "created", "name": "Created", "custom": False, "navigable": True,
     "searchable": True, "schema": {"type": "datetime", "system": "created"}},
    {"id": "status", "key": "status", "name": "Status", "custom": False, "navigable": True,
     "searchable": True, "schema": {"type": "status", "system": "status"}},
    {"id": "assignee", "key": "assignee", "name": "Assignee", "custom": False, "navigable": True,
     "searchable": True, "schema": {"type": "user", "system": "assignee"}},
    {"id": "issuetype", "key": "issuetype", "name": "Issue Type", "custom": False, "navigable": True,
     "searchable": True, "schema": {"type": "issuetype", "system": "issuetype"}},
    {"id": SPRINT_FIELD, "key": SPRINT_FIELD, "name": "Sprint", "custom": True, "navigable": True,
     "searchable": True, "schema": {"type": "array", "items": "json",
                                    "custom": "com.pyxis.greenhopper.jira:gh-sprint", "customId": 10020}},
    {"id": POINTS_FIELD, "key": POINTS_FIELD, "name": "Story Points", "custom": True, "navigable": True,
     "searchable": True, "schema": {"type": "number",
                                    "custom": "com.atlassian.jira.plugin.system.customfieldtypes:float",
                                    "customId": 10026}},
    {"id": POINTS_ESTIMATE_FIELD, "key": POINTS_ESTIMATE_FIELD, "name": "Story point estimate", "custom": True,
     "navigable": True, "searchable": True,
     "schema": {"type": "number", "custom": "com.atlassian.jira.plugin.system.customfieldtypes:float",
                "customId": 10016}},
]

STATUSES: list[dict] = [
    {"id": "1", "name": "To Do", "statusCategory": {"id": 2, "key": "new", "name": "To Do"}},
    {"id": "3", "name": "In Progress", "statusCategory": {"id": 4, "key": "indeterminate", "name": "In Progress"}},
    {"id": "10001", "name": "Done", "statusCategory": {"id": 3, "key": "done", "name": "Done"}},
]

AUTHORS: tuple[dict | None, ...] = (
    {"accountId": "acct-1", "displayName": "Luna Fake", "active": True},
    {"accountId": "acct-2", "displayName": "Sam Fake", "active": True},
    {"accountId": "acct-3", "displayName": "Automation for Jira", "active": True},
    None,  # a real changelog entry can have no author; the client already tolerates it, so the fake produces it
)

# One item per menu slot, in the shape the real API returns. `fieldId` is Cloud-only for custom fields, which is
# exactly why `history_rows` takes a name -> id map at all; the server strips it for Data Center.
_MENU: tuple[dict, ...] = (
    {"field": "status", "fieldId": "status", "fieldtype": "jira",
     "from": "1", "fromString": "To Do", "to": "3", "toString": "In Progress"},
    {"field": "assignee", "fieldId": "assignee", "fieldtype": "jira",
     "from": None, "fromString": None, "to": "acct-2", "toString": "Sam Fake"},
    {"field": "Story Points", "fieldId": POINTS_FIELD, "fieldtype": "custom",
     "from": None, "fromString": "3", "to": None, "toString": "5"},
    {"field": "summary", "fieldId": "summary", "fieldtype": "jira",
     "from": None, "fromString": "Fake issue", "to": None, "toString": "Fake issue (edited)"},
    {"field": "description", "fieldId": "description", "fieldtype": "jira",
     "from": None, "fromString": None, "to": None, "toString": None},
)

SPRINT_START = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
SPRINT_END = SPRINT_START + timedelta(days=14)
CORPUS_START = SPRINT_START - timedelta(days=40)

_MASK = (1 << 64) - 1
_ISSUE_ID_BASE = 10000

_ISSUE_RE = re.compile(r"^/rest/api/(?P<api>\d)/issue/(?P<key>[^/]+?)(?P<tail>/changelog|/transitions)?$")
_AGILE_SPRINT_RE = re.compile(r"^/rest/agile/1\.0/sprint/(?P<id>\d+)(?P<tail>/issue)?$")
_AGILE_BOARD_RE = re.compile(r"^/rest/agile/1\.0/board/(?P<id>\d+)/sprint$")
_JQL_KEYS_RE = re.compile(r"key\s+in\s*\(([^)]*)\)", re.I)
_JQL_SPRINT_RE = re.compile(r"sprint\s*=\s*(\d+)", re.I)


def _hash64(*parts: int) -> int:
    """FNV-1a over the parts' bytes.

    A `random.Random(f"{seed}:{i}:{h}")` per history would be a SHA-512 per row; at 100,000 rows that is the fake
    itself becoming the thing the budget test measures. This is the same determinism for a few multiplications.
    """
    h = 0xCBF29CE484222325
    for part in parts:
        p = part & _MASK
        for _ in range(8):
            h = ((h ^ (p & 0xFF)) * 0x100000001B3) & _MASK
            p >>= 8
    return h


def _iso(dt: datetime) -> str:
    """Jira's own timestamp spelling: milliseconds and a `+0000` offset with no colon."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}+0000"


def _message(pairs: dict[str, Any]) -> email.message.Message:
    """Headers as the client sees them from `urlopen`: case-insensitive `.get`, exactly like `HTTPMessage`."""
    m = email.message.Message()
    for k, v in pairs.items():
        if v is not None:
            m[k] = str(v)
    return m


class FakeResponse(io.BytesIO):
    """All `urlopen` has to be, as far as `Jira.request` is concerned: a context manager with `read()` and headers."""

    def __init__(self, payload: Any, headers: email.message.Message, status: int = 200, url: str = ""):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        super().__init__(raw)
        self.headers = headers
        self.status = status
        self.url = url

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *a) -> bool:
        return False


@dataclass(frozen=True)
class Recorded:
    """One request as it left the client. `headers["Authorization"]` is always `"REDACTED"`."""
    method: str
    path: str
    query: str
    params: dict[str, str]
    body: Any
    headers: dict[str, str]

    @property
    def target(self) -> str:
        return f"{self.method} {self.path}" + (f"?{self.query}" if self.query else "")

    def __str__(self) -> str:  # what a failing assertion prints
        return self.target


# ------------------------------------------------------------------------------------------ the corpus


@dataclass(frozen=True)
class Corpus:
    """N issues x H histories, generated on demand.

    Nothing is stored: `history(i, h)` is a pure function of `(seed, i, h)`, so asking for page 400 of issue 300
    costs one page. That is the property the budget test in the streaming slice depends on — if the fake
    materialised 100,000 dicts to serve the first page, the peak it measured would be the fake's, not the client's.
    """
    issues: int = 5
    histories: int = 4
    seed: int = 1
    project: str = "RDSD"
    sprint_id: int = 41
    items_per_history: int = 1

    # ---- identity
    def key(self, i: int) -> str:
        return f"{self.project}-{i + 1}"

    def issue_id(self, i: int) -> str:
        return str(_ISSUE_ID_BASE + i)

    def index_of(self, ref: Any) -> int | None:
        """Accepts a key (`RDSD-7`) or a numeric issue id, the two things `issueIdsOrKeys` may hold."""
        s = str(ref)
        if s.isdigit():
            i = int(s) - _ISSUE_ID_BASE
            return i if 0 <= i < self.issues else None
        if s.startswith(self.project + "-") and s[len(self.project) + 1:].isdigit():
            i = int(s[len(self.project) + 1:]) - 1
            return i if 0 <= i < self.issues else None
        return None

    def keys(self) -> list[str]:
        return [self.key(i) for i in range(self.issues)]

    # ---- issue shape
    def sprint_ids(self, i: int) -> list[int]:
        """Every fourth issue carried over from the previous sprint, so a replay has something to reconcile."""
        return [self.sprint_id - 1, self.sprint_id] if i % 4 == 3 else [self.sprint_id]

    def points(self, i: int) -> float:
        return float((1, 2, 3, 5, 8)[i % 5])

    def status(self, i: int) -> dict:
        return dict(STATUSES[2] if i % 3 != 2 else STATUSES[1])

    def created(self, i: int) -> datetime:
        return CORPUS_START + timedelta(days=i % 30, hours=i % 7)

    def issue_json(self, i: int, fields: list[str] | None = None, base_url: str = "") -> dict:
        """`fields` is what the caller asked for; Jira returns only those, with `id`/`key` always at the top."""
        all_fields: dict[str, Any] = {
            "summary": f"Fake issue {self.key(i)}",
            "created": _iso(self.created(i)),
            "issuetype": {"id": "10001", "name": "Sub-task" if i % 7 == 6 else "Story", "subtask": i % 7 == 6},
            "status": self.status(i),
            "assignee": AUTHORS[i % 3],
            SPRINT_FIELD: [{"id": s, "name": f"Sprint {s}", "state": "closed", "boardId": 3}
                           for s in self.sprint_ids(i)],
            POINTS_FIELD: self.points(i),
            POINTS_ESTIMATE_FIELD: None,
        }
        keep = all_fields if fields is None else {k: v for k, v in all_fields.items() if k in fields}
        return {"id": self.issue_id(i), "key": self.key(i),
                "self": f"{base_url}/rest/api/3/issue/{self.issue_id(i)}", "fields": keep}

    # ---- histories
    def history(self, i: int, h: int) -> dict:
        """One changelog entry.

        Ascending in `h` by both `created` and `id` — the ordering guarantee the replay depends on and #126 has to
        state. Entries are spread evenly from the issue's creation to ten days into the sprint, so the first one
        (which adds the issue to its sprint) lands before the sprint starts and the last one (which closes it)
        lands inside it: a replay run against this corpus gets sensible committed and completed numbers rather
        than a pile of issues that finished before the sprint existed. At very large `histories` the step falls
        below a second and several entries share a timestamp, which is realistic — automation does that — and is
        exactly the case the `(created_utc, changelog_id)` tiebreak exists for.
        """
        n = _hash64(self.seed, i, h)
        start = self.created(i)
        step = (SPRINT_START + timedelta(days=10) - start) / max(1, self.histories)
        created = start + step * (h + 1)
        items = [self._first_item() if h == 0 else
                 self._last_item() if h == self.histories - 1 else
                 dict(_MENU[n % len(_MENU)])]
        for extra in range(1, max(1, self.items_per_history)):
            items.append(dict(_MENU[(n >> (8 * extra)) % len(_MENU)]))
        return {"id": str(10000 + i * 100000 + h),
                "author": AUTHORS[(n >> 17) % len(AUTHORS)],
                "created": _iso(created),
                "items": items}

    def _first_item(self) -> dict:
        return {"field": "Sprint", "fieldId": SPRINT_FIELD, "fieldtype": "custom",
                "from": "", "fromString": "", "to": str(self.sprint_id), "toString": f"Sprint {self.sprint_id}"}

    def _last_item(self) -> dict:
        return {"field": "status", "fieldId": "status", "fieldtype": "jira",
                "from": "3", "fromString": "In Progress", "to": "10001", "toString": "Done"}

    def page(self, i: int, start: int, limit: int) -> list[dict]:
        """A window of one issue's history. Builds `limit` dicts, never `self.histories` of them."""
        stop = min(self.histories, start + max(0, limit))
        return [self.history(i, h) for h in range(max(0, start), stop)]

    def rows_per_issue(self) -> int:
        return self.histories * max(1, self.items_per_history)


# ------------------------------------------------------------------------------------------ rate limiting


@dataclass
class TokenBucket:
    """`capacity` tokens, refilled at `refill` a second; a request with no token gets a real 429.

    Being told to slow down by a refusal is the only way today's client learns it is throttled — it never reads
    `X-RateLimit-Remaining` — so the fake has to be able to actually refuse, not just advertise.
    """
    capacity: int = 0            # 0 disables the bucket
    refill: float = 1.0
    retry_after: int = 5
    tokens: float = field(default=0.0, init=False)
    _last: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)

    @property
    def on(self) -> bool:
        return self.capacity > 0

    def take(self, now: float) -> bool:
        if not self.on:
            return True
        self.tokens = min(float(self.capacity), self.tokens + (now - self._last) * self.refill)
        self._last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False

    def seconds_to_token(self, now: float) -> float:
        if not self.on or self.refill <= 0:
            return float(self.retry_after)
        return max(0.0, (1.0 - self.tokens) / self.refill)


# ------------------------------------------------------------------------------------------ fault script


def parse_fault(fault: Any) -> tuple[str, Any, dict]:
    """`(kind, arg, extra)` for one entry of a fault script. Raises on a typo rather than quietly doing nothing."""
    if isinstance(fault, bool):
        raise ValueError(f"not a fault: {fault!r}")
    if isinstance(fault, int):
        return ("status", int(fault), {})
    s = str(fault).strip()
    low = s.lower()
    if low in ("timeout", "reset", "interrupt"):
        return (low, None, {})
    if low == "drop islast":
        return ("drop_islast", None, {})
    if low == "duplicate histories":
        return ("duplicate", None, {})
    if low == "shuffle pages":
        return ("shuffle", None, {})
    if low.startswith("cap maxresults"):
        return ("cap", int(s.split()[-1]), {})
    if low.startswith("429 date"):
        return ("status", 429, {"retry_after": "date"})
    if low.startswith("400 invalid key"):
        return ("status", 400, {"bad_key": s.split(None, 3)[3] if len(s.split(None, 3)) > 3 else "?"})
    if low.isdigit():
        return ("status", int(low), {})
    raise ValueError(f"unknown fault {fault!r}; see the fault table in tests/fakes/jira.py")


@dataclass
class Fault:
    """One `(match, nth, fault)` entry, with the counters a test asserts on."""
    match: str
    nth: Any
    fault: Any
    seen: int = 0        # requests this entry's `match` has matched
    fired: int = 0       # times it actually fired

    @classmethod
    def of(cls, entry: Any) -> "Fault":
        if isinstance(entry, Fault):
            return entry
        match, nth, fault = entry
        parse_fault(fault)  # fail at construction, where the traceback names the test
        return cls(str(match), nth, fault)

    def matches(self, target: str) -> bool:
        return self.match in ("", "any", "*") or self.match in target

    def due(self) -> bool:
        """`seen` has already been incremented for this request when this is asked."""
        if self.nth in (None, "every", "*", "any"):
            return True
        if isinstance(self.nth, int):
            return self.seen == self.nth
        return self.seen in set(self.nth)


# ------------------------------------------------------------------------------------------ the server


class FakeJira:
    """A Jira instance that lives entirely in this process. See the module docstring for the fault script."""

    def __init__(self, issues: int = 5, histories: int = 4, seed: int = 1, *,
                 flavor: str = "cloud", project: str = "RDSD", base_url: str | None = None,
                 sprint_id: int = 41, board_id: int = 3, items_per_history: int = 1,
                 bulk_duplicate: bool = False, bulk_cap: int = 1000, bulk_created: str = "iso",
                 expand_cap: int = 100, paged_changelog: bool = True,
                 bucket: TokenBucket | None = None, rate_headers: bool | None = None,
                 rate_limit: int = 0, reset_style: str = "epoch",   # rate_limit=N is shorthand for a bucket of N
                 faults: Any = (), wall_start: datetime | None = None):
        if flavor not in ("cloud", "dc"):
            raise ValueError("flavor is 'cloud' or 'dc'")
        self.flavor = flavor
        self.api = "/rest/api/3" if flavor == "cloud" else "/rest/api/2"
        self.base_url = base_url or ("https://fake.atlassian.net" if flavor == "cloud" else "https://jira.fake.local")
        self.corpus = Corpus(issues, histories, seed, project, sprint_id, items_per_history)
        self.board_id = board_id
        self.bulk_duplicate = bulk_duplicate
        self.bulk_cap = bulk_cap
        self.bulk_created = bulk_created
        self.expand_cap = expand_cap
        self.paged_changelog = paged_changelog
        self.reset_style = reset_style
        self.bucket = bucket or TokenBucket(capacity=rate_limit)
        self.rate_headers = self.bucket.on if rate_headers is None else rate_headers
        self.faults: list[Fault] = [Fault.of(f) for f in faults]
        self.requests: list[Recorded] = []

        # A virtual clock anchored to real wall time: an HTTP-date `Retry-After` is compared against
        # `datetime.now()` by the client, so a clock set in fictional 2026 would hand back a negative wait.
        self._wall0 = wall_start or datetime.now(timezone.utc)
        self.now = 0.0
        self.slept: list[float] = []

    def __repr__(self) -> str:
        c = self.corpus
        return (f"FakeJira({self.flavor}, {c.issues} issues x {c.histories} histories, "
                f"{len(self.requests)} requests)")

    # ---- clock ------------------------------------------------------------------------------------
    def sleep(self, seconds: float) -> None:
        """The injected sleeper: records the wait and advances the clock instead of spending it."""
        self.slept.append(float(seconds))
        self.now += float(seconds)

    @property
    def waited(self) -> float:
        return sum(self.slept)

    @property
    def wall(self) -> datetime:
        return self._wall0 + timedelta(seconds=self.now)

    # ---- wiring -----------------------------------------------------------------------------------
    def client(self, **kw):
        """`Jira` pointed at this fake, with the sleeper and (for Cloud) an email already wired."""
        from agentdata.connectors import jira_api as J

        flavor = J.CLOUD if self.flavor == "cloud" else J.DC_BEARER
        creds = J.Creds(self.base_url, FAKE_EMAIL if flavor.auth == "basic" else None, FAKE_TOKEN, "fake")
        kw.setdefault("sleep", self.sleep)
        return J.Jira(creds, flavor, opener=self.opener, **kw)

    def request(self, method: str, path: str, params: dict | None = None, body: Any = None) -> Any:
        """Drive the fake with no client in between.

        Fault tests use this deliberately: whether a 502 is retried is the *client's* policy and changes with #123,
        but whether the fake answered 502 on the third bulkfetch is this module's contract and must not.
        """
        url = self.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Accept": "application/json", "Authorization": "Basic redacted"})
        with self.opener(req) as r:
            raw = r.read()
        return json.loads(raw) if raw.strip() else None

    # ---- request records --------------------------------------------------------------------------
    def matching(self, needle: str = "") -> list[Recorded]:
        return [r for r in self.requests if needle in r.target]

    def count(self, needle: str = "") -> int:
        return len(self.matching(needle))

    def last(self, needle: str = "") -> Recorded:
        return self.matching(needle)[-1]

    def unfired(self) -> list[Fault]:
        """Scripted faults that never happened — usually a typo in `match`, and always worth asserting empty."""
        return [f for f in self.faults if not f.fired]

    # ---- the opener seam --------------------------------------------------------------------------
    def opener(self, req, timeout: float | None = None, context: Any = None) -> FakeResponse:
        split = urllib.parse.urlsplit(req.full_url)
        path, query = split.path, split.query
        params = dict(urllib.parse.parse_qsl(query, keep_blank_values=True))
        method = req.get_method()
        body = json.loads(req.data.decode()) if req.data else None
        headers = {k: ("REDACTED" if k.lower() == "authorization" else v) for k, v in dict(req.headers).items()}
        rec = Recorded(method, path, query, params, body, headers)
        self.requests.append(rec)

        kind, arg, extra = self._fire(rec.target)
        if kind == "timeout":
            raise socket.timeout("fake Jira: scripted timeout on " + path)
        if kind == "reset":
            raise ConnectionResetError("fake Jira: scripted connection reset on " + path)
        if kind == "interrupt":
            raise KeyboardInterrupt("fake Jira: scripted interrupt on " + path)
        if kind == "status":
            raise self._http_error(int(arg), path, **extra)
        if not self.bucket.take(self.now):
            raise self._http_error(429, path, retry_after=int(self.bucket.seconds_to_token(self.now)) + 1,
                                   throttled=True)

        payload = self._route(method, path, params, body, cap=arg if kind == "cap" else None)
        if isinstance(payload, dict):
            if kind == "drop_islast":
                payload.pop("isLast", None)
            elif kind == "duplicate":
                payload = self._duplicate_within_page(payload)
            elif kind == "shuffle":
                payload = self._shuffle_page(payload)
        if payload is None:
            return FakeResponse(b"", self._response_headers(), 204, req.full_url)
        return FakeResponse(payload, self._response_headers(), 200, req.full_url)

    def _fire(self, target: str) -> tuple[str | None, Any, dict]:
        for f in self.faults:
            if not f.matches(target):
                continue
            f.seen += 1
            if f.due():
                f.fired += 1
                return parse_fault(f.fault)
        return (None, None, {})

    # ---- responses --------------------------------------------------------------------------------
    def _response_headers(self) -> email.message.Message:
        h: dict[str, Any] = {"Content-Type": "application/json;charset=UTF-8"}
        if self.rate_headers and self.bucket.on:
            remaining = int(self.bucket.tokens)
            h["X-RateLimit-Limit"] = self.bucket.capacity
            h["X-RateLimit-Remaining"] = remaining
            h["X-RateLimit-Reset"] = self._reset_value()
            h["X-RateLimit-NearLimit"] = "true" if remaining <= max(1, self.bucket.capacity // 10) else "false"
        return _message(h)

    def _reset_value(self) -> int:
        wait = int(self.bucket.seconds_to_token(self.now)) + 1
        return wait if self.reset_style == "delta" else int(self.wall.timestamp()) + wait

    def _http_error(self, status: int, path: str, *, retry_after: Any = None, bad_key: str | None = None,
                    throttled: bool = False) -> urllib.error.HTTPError:
        if bad_key:
            msgs = [f"The issue key '{bad_key}' does not exist for the field 'key'."]
        elif status == 429:
            msgs = ["Rate limit exceeded."]
        else:
            msgs = [f"Fake Jira: scripted HTTP {status} on {path}"]
        hdrs: dict[str, Any] = {"Content-Type": "application/json;charset=UTF-8"}
        if status == 429:
            wait = self.bucket.retry_after if throttled else 3
            wait = retry_after if isinstance(retry_after, int) else wait
            if retry_after == "date":
                hdrs["Retry-After"] = email.utils.formatdate(
                    (self.wall + timedelta(seconds=wait)).timestamp(), usegmt=True)
            else:
                hdrs["Retry-After"] = wait
        if self.rate_headers and self.bucket.on:
            hdrs["X-RateLimit-Limit"] = self.bucket.capacity
            hdrs["X-RateLimit-Remaining"] = 0
            hdrs["X-RateLimit-Reset"] = self._reset_value()
            hdrs["X-RateLimit-NearLimit"] = "true"
        body = json.dumps({"errorMessages": msgs, "errors": {}}).encode()
        return urllib.error.HTTPError(self.base_url + path, status, f"Fake {status}",
                                      _message(hdrs), io.BytesIO(body))

    def _duplicate_within_page(self, page: dict) -> dict:
        for key in ("values", "issues", "issueChangeLogs"):
            vals = page.get(key)
            if vals:
                page[key] = list(vals) + [vals[0]]
                return page
        return page

    def _shuffle_page(self, page: dict) -> dict:
        for key in ("values", "issues", "issueChangeLogs"):
            vals = page.get(key)
            if vals:
                page[key] = list(reversed(vals))
                return page
        return page

    # ---- routing ----------------------------------------------------------------------------------
    def _route(self, method: str, path: str, params: dict, body: Any, cap: int | None) -> Any:
        api = self.api
        if path == f"{api}/myself":
            return ({"accountId": "acct-1", "displayName": "Luna Fake", "emailAddress": FAKE_EMAIL, "active": True}
                    if self.flavor == "cloud" else
                    {"name": "luna", "key": "luna", "displayName": "Luna Fake", "active": True})
        if path == f"{api}/field":
            return [dict(f) for f in FIELDS]
        if path == f"{api}/status":
            return [dict(s) for s in STATUSES]
        if path == f"{api}/search/jql":
            if self.flavor != "cloud":
                raise self._http_error(404, path)
            return self._search_token(params, cap)
        if path == f"{api}/search":
            if self.flavor == "cloud":
                # Cloud retired the endpoint; the client's fallback has to see the real answer.
                raise self._http_error(410, path)
            return self._search_startat(params, cap)
        if path == f"{api}/changelog/bulkfetch":
            if self.flavor != "cloud":
                raise self._http_error(404, path)
            return self._bulkfetch(body or {}, cap)

        m = _ISSUE_RE.match(path)
        if m:
            if m.group("api") != api[-1]:
                raise self._http_error(404, path)
            i = self.corpus.index_of(m.group("key"))
            if i is None:
                raise self._http_error(404, path)
            tail = m.group("tail")
            if tail == "/changelog":
                if not self.paged_changelog:
                    raise self._http_error(404, path)
                return self._changelog_page(i, params, cap)
            if tail == "/transitions":
                if method == "POST":
                    return None
                return {"expand": "transitions", "transitions": [
                    {"id": "31", "name": "Done", "hasScreen": False, "isAvailable": True, "fields": {},
                     "to": dict(STATUSES[2])}]}
            return self._issue(i, params)

        m = _AGILE_SPRINT_RE.match(path)
        if m:
            sid = int(m.group("id"))
            if m.group("tail") == "/issue":
                return self._sprint_issues(sid, params, cap)
            return self._sprint(sid)
        m = _AGILE_BOARD_RE.match(path)
        if m:
            return self._board_sprints(int(m.group("id")), params, cap)
        if path == "/rest/greenhopper/1.0/rapid/charts/sprintreport":
            return self._sprintreport(int(params.get("sprintId") or self.corpus.sprint_id))

        # Loud, like the harness's exit 99: a silent 404 would hide a typo'd path in the client.
        raise self._http_error(404, path, bad_key=None)

    # ---- search -----------------------------------------------------------------------------------
    def _jql_indexes(self, jql: str) -> list[int]:
        """The three JQL shapes this client actually sends; anything else means every issue."""
        m = _JQL_KEYS_RE.search(jql or "")
        if m:
            out = []
            for ref in m.group(1).split(","):
                i = self.corpus.index_of(ref.strip().strip('"').strip("'"))
                if i is not None:
                    out.append(i)
            return out
        m = _JQL_SPRINT_RE.search(jql or "")
        if m:
            sid = int(m.group(1))
            return [i for i in range(self.corpus.issues) if sid in self.corpus.sprint_ids(i)]
        return list(range(self.corpus.issues))

    def _fields_param(self, params: dict) -> list[str] | None:
        raw = params.get("fields")
        return [f.strip() for f in raw.split(",") if f.strip()] if raw else None

    def _page_size(self, params: dict, cap: int | None, default: int) -> int:
        asked = int(params.get("maxResults") or default)
        return min(asked, cap) if cap else asked

    def _search_token(self, params: dict, cap: int | None) -> dict:
        idx = self._jql_indexes(params.get("jql", ""))
        size = self._page_size(params, cap, 50)
        start = int(params.get("nextPageToken") or 0)
        window = idx[start:start + size]
        flds = self._fields_param(params)
        page: dict[str, Any] = {"issues": [self.corpus.issue_json(i, flds, self.base_url) for i in window],
                                "isLast": start + len(window) >= len(idx)}
        if start + len(window) < len(idx):
            page["nextPageToken"] = str(start + len(window))
        return page

    def _search_startat(self, params: dict, cap: int | None) -> dict:
        idx = self._jql_indexes(params.get("jql", ""))
        size = self._page_size(params, cap, 50)
        start = int(params.get("startAt") or 0)
        window = idx[start:start + size]
        flds = self._fields_param(params)
        return {"expand": "schema,names", "startAt": start, "maxResults": size, "total": len(idx),
                "issues": [self.corpus.issue_json(i, flds, self.base_url) for i in window]}

    # ---- issues and changelogs --------------------------------------------------------------------
    def _history(self, i: int, h: int, *, bulk: bool = False) -> dict:
        entry = self.corpus.history(i, h)
        if self.flavor == "dc":
            # Data Center omits `fieldId` on custom fields, which is why the client carries a name -> id map.
            for it in entry["items"]:
                if it.get("fieldtype") == "custom":
                    it.pop("fieldId", None)
        if bulk and self.bulk_created != "iso":
            ts = datetime.strptime(entry["created"], "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
            entry["created"] = int(ts * 1000) if self.bulk_created == "epoch_ms" else int(ts)
        return entry

    def _changelog_page(self, i: int, params: dict, cap: int | None) -> dict:
        total = self.corpus.histories
        size = self._page_size(params, cap, 100)
        start = int(params.get("startAt") or 0)
        values = [self._history(i, h) for h in range(min(start, total), min(total, start + size))]
        return {"self": f"{self.base_url}{self.api}/issue/{self.corpus.key(i)}/changelog",
                "maxResults": size, "startAt": start, "total": total,
                "isLast": start + len(values) >= total, "values": values}

    def _issue(self, i: int, params: dict) -> dict:
        out = self.corpus.issue_json(i, self._fields_param(params), self.base_url)
        if "changelog" in (params.get("expand") or ""):
            # Newest first and capped, the Data Center shape: `total` tells the truth, `histories` does not.
            total = self.corpus.histories
            top = [self._history(i, h) for h in range(total - 1, max(-1, total - 1 - self.expand_cap), -1)]
            out["changelog"] = {"startAt": 0, "maxResults": len(top), "total": total, "histories": top}
        return out

    def _bulkfetch(self, body: dict, cap: int | None) -> dict:
        """`maxResults` counts change histories, grouped by issue, which is how the client's page budget reads.

        `nextPageToken` is `"<issue offset>:<history offset>"` — opaque to the client, legible in a failure.
        """
        refs = list(body.get("issueIdsOrKeys") or [])
        size = int(body.get("maxResults") or 1000)
        size = min(size, cap or self.bulk_cap)
        token = body.get("nextPageToken")
        ii, hh = (int(x) for x in str(token).split(":")) if token else (0, 0)
        if self.bulk_duplicate and token and hh > 0 and size > 1:
            hh -= 1                      # JRACLOUD-94906: the page re-serves the previous page's last history
        budget = size
        groups: list[dict] = []
        total = self.corpus.histories
        while ii < len(refs) and budget > 0:
            idx = self.corpus.index_of(refs[ii])
            if idx is None:              # the real bulkfetch just omits an unknown issue
                ii, hh = ii + 1, 0
                continue
            take = min(budget, total - hh)
            if take > 0:
                groups.append({"issueId": self.corpus.issue_id(idx),
                               "changeHistories": [self._history(idx, h, bulk=True) for h in range(hh, hh + take)]})
            budget -= take
            hh += take
            if hh >= total:
                ii, hh = ii + 1, 0
        page: dict[str, Any] = {"issueChangeLogs": groups}
        if ii < len(refs):
            page["nextPageToken"] = f"{ii}:{hh}"
        return page

    # ---- agile ------------------------------------------------------------------------------------
    def _sprint_json(self, sid: int) -> dict:
        offset = timedelta(days=14 * (sid - self.corpus.sprint_id))
        state = "closed" if sid <= self.corpus.sprint_id else "future"
        out = {"id": sid, "self": f"{self.base_url}/rest/agile/1.0/sprint/{sid}", "state": state,
               "name": f"Sprint {sid}", "originBoardId": self.board_id, "goal": f"goal {sid}",
               "startDate": _iso(SPRINT_START + offset), "endDate": _iso(SPRINT_END + offset)}
        if state == "closed":
            out["completeDate"] = _iso(SPRINT_END + offset + timedelta(hours=2))
        return out

    def _sprint(self, sid: int) -> dict:
        if not (self.corpus.sprint_id - 1 <= sid <= self.corpus.sprint_id + 1):
            raise self._http_error(404, f"/rest/agile/1.0/sprint/{sid}")
        return self._sprint_json(sid)

    def _board_sprints(self, board: int, params: dict, cap: int | None) -> dict:
        if board != self.board_id:
            raise self._http_error(404, f"/rest/agile/1.0/board/{board}/sprint")
        base = self.corpus.sprint_id
        every = [self._sprint_json(s) for s in (base - 1, base, base + 1)]
        wanted = params.get("state")
        if wanted:
            every = [s for s in every if s["state"] == wanted]
        size = self._page_size(params, cap, 50)
        start = int(params.get("startAt") or 0)
        window = every[start:start + size]
        return {"maxResults": size, "startAt": start, "total": len(every),
                "isLast": start + len(window) >= len(every), "values": window}

    def _sprint_issues(self, sid: int, params: dict, cap: int | None) -> dict:
        idx = [i for i in range(self.corpus.issues) if sid in self.corpus.sprint_ids(i)]
        size = self._page_size(params, cap, 50)
        start = int(params.get("startAt") or 0)
        window = idx[start:start + size]
        flds = self._fields_param(params)
        return {"expand": "schema,names", "startAt": start, "maxResults": size, "total": len(idx),
                "issues": [self.corpus.issue_json(i, flds, self.base_url) for i in window]}

    def _sprintreport(self, sid: int) -> dict:
        """The undocumented GreenHopper payload `--compare-sprintreport` reads. Cross-check only, never truth."""
        members = [i for i in range(self.corpus.issues) if sid in self.corpus.sprint_ids(i)]
        done = [i for i in members if self.corpus.status(i)["id"] == "10001"]
        not_done = [i for i in members if i not in done]

        def stat(i: int) -> dict:
            return {"key": self.corpus.key(i), "typeName": "Story",
                    "estimateStatistic": {"statFieldValue": {"value": self.corpus.points(i)}}}

        return {"contents": {
            "completedIssues": [stat(i) for i in done],
            "issuesNotCompletedInCurrentSprint": [stat(i) for i in not_done],
            "puntedIssues": [],
            "issuesCompletedInAnotherSprint": [],
            "completedIssuesEstimateSum": {"value": sum(self.corpus.points(i) for i in done)},
            "issuesNotCompletedEstimateSum": {"value": sum(self.corpus.points(i) for i in not_done)},
            "puntedIssuesEstimateSum": {"value": 0.0},
            "issueKeysAddedDuringSprint": {}},
            "sprint": self._sprint_json(sid)}


def rows_of(fake: FakeJira, i: int) -> Iterator[dict]:
    """Every changelog row of one issue, in the order the ordering guarantee promises. What a test compares to."""
    from agentdata.connectors.jira_api import history_rows

    for h in range(fake.corpus.histories):
        yield from history_rows(fake.corpus.key(i), fake.corpus.history(i, h))
