"""The request layer of the Jira client: what is worth retrying, how long to wait, and when to stop.

`Jira.request()` used to decide all of this inline, and it decided it wrong in three ways that cost whole runs.
It retried 429 and 503 only, so a 502 from the tenant's proxy or a socket timeout on page 40 of 80 raised
immediately and threw away every page already fetched. Its backoff had no jitter, so the fleet's tiles -- several
agents sharing one human's token -- retried in lockstep and hit the next limit together. And nothing counted:
a bulkfetch that silently fell back to one request per issue made 3,000 requests where the operator expected 3,
with no ceiling to stop it before the tenant throttled the human's account.

So the decisions live here, as pure functions and small dataclasses with a clock passed in: `classify()` names a
failure once, `backoff_seconds()` spaces the retries out, `RateLimit` reads Atlassian's headers so the client can
slow down *before* it is refused, and `RequestBudget` makes a runaway run stop with an error a human can act on
rather than running until someone notices. Nothing here opens a socket -- that is what makes it testable without
a network, and it is why `jira_api` imports this module and never the other way round.

Stdlib only, no state beyond what the caller holds, and no credential ever reaches a message here: the only
server text quoted is the first 200 bytes of an error body, exactly as before.
"""
from __future__ import annotations
import email.utils
import http.client
import socket
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

USER_AGENT = "agentdata/0.1"

# Hints tell the human what to DO. 429 no longer says "wait a minute and rerun": by the time this is raised the
# client has already waited -- it retried with jittered backoff and honoured every Retry-After it was given --
# so repeating the same command changes nothing. What is left is asking for less, or being allowed to take longer.
HINTS = {
    401: "token rejected; re-run ad-setup --only pncli, or set JIRA_TOKEN / JIRA_EMAIL",
    403: "no permission on this project or issue",
    404: "not found (issue key, endpoint, or wrong Jira flavor); try ad-jira whoami --redetect",
    429: "still rate limited after the client's own retries and Retry-After waits; narrow the JQL to fewer "
         "issues, or rerun with a larger --max-requests / --max-seconds",
}

# What a status means for a retry. Split three ways because 500 is not like the others: Jira answers 500 for a
# transient backend hiccup on a changelog page often enough to be worth one more try, but a *second* 500 on the
# same page is a real server-side error and retrying it six times only delays the report.
RETRYABLE = frozenset({429, 502, 503, 504})
RETRY_ONCE = frozenset({500})
NEVER = frozenset({400, 401, 403, 404, 405, 409, 413})

# A pause computed from a server header is still a number this client chose to trust. Clamp it: a Reset value in
# the wrong frame (an epoch compared against a monotonic clock) would otherwise sleep for decades, and a run that
# looks hung is indistinguishable from one that is. Past this, take the 429 and retry reactively.
MAX_PAUSE_SECONDS = 300.0

# Below this, an X-RateLimit-Reset is seconds-from-now rather than an epoch. Atlassian sends both shapes; the
# boundary is arbitrary but unambiguous -- 10,000,000 epoch seconds was April 1970, and no reset window is
# four months long.
_EPOCH_FLOOR = 10_000_000


class JiraError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


class JiraHTTPError(JiraError):
    def __init__(self, status: int, path: str, body: str = ""):
        super().__init__(f"HTTP {status} on {path}: {body[:200]}", hint=HINTS.get(status, ""))
        self.status, self.path = status, path


class JiraPartialError(JiraError):
    """The answer that arrived is knowingly short, and the caller must not treat it as whole.

    Data Center without the paged changelog endpoint hands back `?expand=changelog` with `total: 412` and a
    hundred histories in the body, and a hundred entries that look like a whole history produce a
    `committed_points` that looks right and is wrong. A `search` stopped at its `max_results` ceiling and a
    cache read that died half way through one issue are the same lie in a different place, which is why they
    raise this too rather than returning what they happened to have.

    It lives here, beside the other two, because `jira_cache` has to raise it and importing the whole REST
    client to name an exception would be the wrong dependency. `jira_api` re-exports it, so every existing
    `J.JiraPartialError` still resolves to this class.

    `reason` is in exactly the spelling the CLI prints as `partial: true`, so one code path renders every
    incomplete outcome -- budget, interruption, an unrecoverable HTTP error and these -- instead of any of them
    escaping as a bare exception nobody catches.
    """

    def __init__(self, msg: str, reason: str, key: str | None = None, have: int = 0, total: int = 0,
                 hint: str = ""):
        super().__init__(msg, hint=hint)
        self.reason, self.key, self.have, self.total = reason, key, have, total


class JiraBudgetError(JiraError):
    """The run hit its own ceiling, not Jira's.

    This is deliberately not a failure of the server: it is the client refusing to keep going, so the message
    says what was spent and where it stopped. The streaming slice turns it into `partial: true` plus a resume
    hint; on its own it is still an error a human can act on, which is the whole point of stopping instead of
    running for an hour against someone else's token.
    """

    _WHAT = {
        "requests": "rerun with a larger --max-requests, or narrow the JQL to fewer issues",
        "seconds": "rerun with a larger --max-seconds, or narrow the JQL to fewer issues",
        "retries": "Jira kept failing rather than answering; check its status page and rerun later, "
                   "or raise jira.budget.max_retries",
    }

    def __init__(self, limit: str, requests_made: int, elapsed: float, last_path: str):
        super().__init__(f"request budget exhausted ({limit}): {requests_made} requests in {elapsed:.1f}s, "
                         f"stopped at {last_path}", hint=self._WHAT.get(limit, ""))
        self.limit, self.requests_made, self.elapsed, self.last_path = limit, requests_made, elapsed, last_path


def classify(status: int | None = None, exc: BaseException | None = None) -> str:
    """Name a failure once: "retry", "retry_once" or "fatal".

    The exception list looks redundant on purpose. One socket timeout reaches `urlopen`'s caller under three
    different names depending on the platform and on where in the request it fired: as `socket.timeout` (an alias
    of `TimeoutError`, itself an `OSError`) when the read times out, as `urllib.error.URLError` wrapping that same
    timeout when the connect times out, and as `http.client.RemoteDisconnected` when a keep-alive connection the
    proxy already closed is reused. `IncompleteRead` is the fourth face of the same event: the response started
    and the connection died mid-body. Matching only one of them is why a timeout on page 40 used to kill the run.

    The `URLError` split matters as much as the list: a URLError whose reason is one of those transients is worth
    retrying, and a URLError with any other reason -- a DNS failure from a typo'd base URL, a refused connection,
    a certificate the CA bundle does not cover -- is fatal. Retrying a bad hostname six times just makes the
    operator wait 30 seconds to be told what was already known at attempt one.

    An unlisted status is fatal, not retryable: this client only replays failures it has a reason to believe are
    transient. A new status code is a thing to read about, not to hammer.
    """
    if isinstance(exc, urllib.error.HTTPError):     # an HTTPError *is* a URLError; judge it by its code
        status = exc.code if status is None else status
        exc = None
    if status is not None:
        if status in NEVER:
            return "fatal"
        if status in RETRYABLE:
            return "retry"
        if status in RETRY_ONCE:
            return "retry_once"
        return "fatal"
    if exc is None:
        return "fatal"
    if _is_transient(exc):
        return "retry"
    if isinstance(exc, urllib.error.URLError):
        return "retry" if _is_transient(exc.reason) else "fatal"
    return "fatal"


# socket.timeout is TimeoutError on 3.10+; both are named so the tuple reads as the list of failures it covers
# rather than as a fact about one Python version.
_TRANSIENT = (socket.timeout, TimeoutError, ConnectionResetError,
              http.client.RemoteDisconnected, http.client.IncompleteRead)


def _is_transient(obj: Any) -> bool:
    return isinstance(obj, _TRANSIENT)


def _header(headers: Any, name: str) -> str | None:
    """Case-insensitive header lookup that works for a dict and for the `email.message.Message` an HTTPError carries."""
    if not headers:
        return None
    get = getattr(headers, "get", None)
    if get is not None:
        v = get(name)
        if v is not None:
            return str(v)
    try:
        items = headers.items()
    except AttributeError:
        return None
    low = name.lower()
    for k, v in items:
        if str(k).lower() == low:
            return None if v is None else str(v)
    return None


def retry_after_seconds(headers: Any, cap: float, *, now: datetime | None = None) -> float | None:
    """`Retry-After` as seconds, clamped to `cap`, or None when the server did not say.

    Two shapes are legal and Jira sends both: an integer count of seconds, and an HTTP date. The cap exists
    because Atlassian will occasionally name a window longer than any run should sit idle for -- `Retry-After:
    300` on a 900-second budget spends a third of the run asleep. Waiting the cap and trying again is better
    behaved than either ignoring the header or obeying it literally.
    """
    raw = _header(headers, "Retry-After")
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return max(0.0, min(float(raw), float(cap)))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return max(0.0, min((when - ref).total_seconds(), float(cap)))


def backoff_seconds(attempt: int, base: float, cap: float, rand: Callable[[], float]) -> float:
    """`min(cap, base * 2 ** attempt) + rand() * base` -- exponential, capped, and jittered.

    The jitter is the reason `rand` is a parameter rather than a call to `random.random()` inside. Several agents
    in the fleet share one human's token and start their tiles from the same schedule; when they all meet the same
    429 they compute the same backoff and retry in the same second, which reproduces the burst that caused the
    limit. A uniform smear of up to one `base` over each wait is enough to break the lockstep, and injecting the
    source lets a test prove two different seeds really do produce different sleeps.
    """
    return min(float(cap), float(base) * (2 ** int(attempt))) + rand() * float(base)


@dataclass
class RequestBudget:
    """How much this one run is allowed to spend, in requests, seconds and retries.

    Without it a fallback that turns 3 requests into 3,000 just runs, and the first person to notice is whoever
    owns the throttled token. Exhausting any of the three raises `JiraBudgetError` carrying enough for the CLI to
    print a partial result with a resume hint, which is a far better outcome than either finishing an hour later
    or being cut off by the tenant.
    """

    max_requests: int = 2000
    max_seconds: float = 900.0
    max_retries: int = 200
    requests: int = 0
    retries: int = 0
    started_at: float | None = None

    def start(self, now: float) -> None:
        """Mark the beginning of a run and zero the counters. Called once; `spend_request` starts the clock
        itself if nobody did, so a client that forgets still gets its seconds enforced from the first request."""
        self.started_at = now
        self.requests = 0
        self.retries = 0

    def elapsed(self, now: float) -> float:
        return 0.0 if self.started_at is None else max(0.0, now - self.started_at)

    def spend_request(self, path: str, now: float) -> None:
        """Charge one request, or raise if this would be the one over the line.

        The check is before the increment so that `--max-requests 50` makes exactly 50 requests and then reports
        `requests_made=50` -- the number the operator can compare with the flag they typed.
        """
        if self.started_at is None:
            self.started_at = now
        if self.requests >= self.max_requests:
            raise JiraBudgetError("requests", self.requests, self.elapsed(now), path)
        self._check_seconds(path, now)
        self.requests += 1

    def spend_retry(self, path: str, now: float) -> None:
        """Charge one retry. Separate from requests because a run can be inside its request budget and still be
        stuck: 200 retries means the server is not answering, and more attempts will not change that."""
        if self.started_at is None:
            self.started_at = now
        if self.retries >= self.max_retries:
            raise JiraBudgetError("retries", self.requests, self.elapsed(now), path)
        self._check_seconds(path, now)
        self.retries += 1

    def _check_seconds(self, path: str, now: float) -> None:
        if self.started_at is not None and now - self.started_at >= self.max_seconds:
            raise JiraBudgetError("seconds", self.requests, self.elapsed(now), path)

    def remaining_requests(self) -> int:
        return max(0, self.max_requests - self.requests)

    def would_exceed(self, n_more: int) -> bool:
        """Would `n_more` requests overrun the budget? The point of asking first is #121's rule that a run says
        what it will cost before it spends it -- a per-issue fallback can announce 3,000 requests instead of
        discovering the ceiling 2,000 in."""
        return self.requests + int(n_more) > self.max_requests


@dataclass
class RateLimit:
    """Atlassian's rate-limit headers, read on every response so the client can slow down before it is refused.

    Learning about a limit from a 429 means the request was already spent and the tenant already counted it
    against the human's token. Cloud says how much is left on every response; reading it costs nothing and turns
    the last few requests before a limit into a pause rather than a rejection.

    Data Center below 8.6 sends none of these. That is not an error and must not become a guess: every field
    stays None, `should_pause()` is False, and such a run is reactive-only -- it learns from Retry-After and 429
    like it always did.

    All times are in the caller's clock frame and `now` must come from the same clock throughout; pass wall time
    (`time.time()`) if any tenant sends an epoch Reset, since converting one needs a frame an epoch shares.
    """

    limit: int | None = None
    remaining: int | None = None
    reset_at: float | None = None
    near_limit: bool = False

    @classmethod
    def from_headers(cls, headers: Any, now: float) -> RateLimit:
        """Parse X-RateLimit-Limit/-Remaining/-Reset/-NearLimit, case-insensitively, tolerating every absence.

        Reset arrives as an epoch on some tenants and as seconds-from-now on others, with nothing in the response
        to say which; a value below `_EPOCH_FLOOR` is a delta, because no epoch that small is this century and no
        window is that long. An unparseable value is treated as absent -- a header this client does not
        understand must not be able to make it sleep.
        """
        limit = _int_or_none(_header(headers, "X-RateLimit-Limit"))
        remaining = _int_or_none(_header(headers, "X-RateLimit-Remaining"))
        near = (_header(headers, "X-RateLimit-NearLimit") or "").strip().lower() in ("true", "1", "yes")
        reset_at = None
        raw = _header(headers, "X-RateLimit-Reset")
        if raw is not None and raw.strip():
            try:
                v = float(raw.strip())
                reset_at = now + v if v < _EPOCH_FLOOR else v
            except ValueError:
                try:
                    when = email.utils.parsedate_to_datetime(raw.strip())
                except (TypeError, ValueError):
                    when = None
                if when is not None:
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    reset_at = when.timestamp()
        return cls(limit=limit, remaining=remaining, reset_at=reset_at, near_limit=near)

    def should_pause(self, floor_ratio: float = 0.10) -> bool:
        """True when the tenant has said we are close: NearLimit set, or under `floor_ratio` of the quota left."""
        if self.near_limit:
            return True
        if self.limit and self.remaining is not None and self.limit > 0:
            return self.remaining < self.limit * floor_ratio
        return False

    def pause_seconds(self, now: float) -> float:
        """How long to wait for the window to roll over: never negative, never longer than `MAX_PAUSE_SECONDS`."""
        if self.reset_at is None:
            return 0.0
        return max(0.0, min(self.reset_at - now, MAX_PAUSE_SECONDS))


def _int_or_none(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(raw.strip()))
    except (ValueError, AttributeError):
        return None


@dataclass
class Stats:
    """What a run cost, for the TOON meta and for `--stats`.

    These five numbers are the ones that answer "why was that slow" and "am I about to get the token throttled"
    without anyone re-running with a debugger: how many requests, how many of those were second tries, how often
    the client paused for a rate limit, how much of the wall clock was spent asleep, and how long the whole thing
    took. `as_dict()` carries exactly those five keys because the meta shape is a contract other commands read.
    """

    requests: int = 0
    retries: int = 0
    rate_limit_waits: int = 0
    waited_seconds: float = 0.0
    elapsed_seconds: float = 0.0

    def as_dict(self) -> dict:
        # Rounded because these land in TOON meta a human reads: 94.23847599999 is noise, not precision.
        return {"requests": self.requests, "retries": self.retries, "rate_limit_waits": self.rate_limit_waits,
                "waited_seconds": round(self.waited_seconds, 2), "elapsed_seconds": round(self.elapsed_seconds, 2)}

    def line(self) -> str:
        """One stderr line for `--stats`. Plural forms because this is read by a person, not parsed."""
        return (f"{self.requests} request{'' if self.requests == 1 else 's'}, "
                f"{self.retries} retr{'y' if self.retries == 1 else 'ies'}, "
                f"{self.rate_limit_waits} rate-limit wait{'' if self.rate_limit_waits == 1 else 's'}, "
                f"{self.waited_seconds:.1f}s waiting, {self.elapsed_seconds:.1f}s elapsed")
