"""Unit tests for the Jira request layer: classification, backoff, Retry-After, budget, rate-limit headers.

Everything under test is pure -- no socket, no sleep, no wall clock unless it is passed in -- so these run in
milliseconds and prove the decisions rather than the plumbing. The cases that matter are the ones that used to
cost whole runs: a socket timeout arriving under four different names, a bad hostname retried six times, a
Retry-After of 300 obeyed literally, a Data Center response with no rate-limit headers being read as "no quota
left", and a fallback that makes 3,000 requests with nothing to stop it.
"""
from __future__ import annotations
import email.utils
import http.client
import socket
import urllib.error
from datetime import datetime, timedelta, timezone

import pytest

from agentdata.connectors import jira_http as H


def _err(status, headers=None):
    import io
    return urllib.error.HTTPError("https://acme.atlassian.net/x", status, "err", headers or {}, io.BytesIO(b"{}"))


# ------------------------------------------------------------------------------------ classify


@pytest.mark.parametrize("status", sorted(H.RETRYABLE))
def test_retryable_statuses_are_retried(status):
    assert H.classify(status=status) == "retry"


@pytest.mark.parametrize("status", sorted(H.RETRY_ONCE))
def test_500_is_retried_once_not_forever(status):
    """Jira answers 500 for a transient backend hiccup on a changelog page; a second one is real."""
    assert H.classify(status=status) == "retry_once"


@pytest.mark.parametrize("status", sorted(H.NEVER))
def test_client_errors_are_never_retried(status):
    assert H.classify(status=status) == "fatal"


@pytest.mark.parametrize("status", [418, 451, 507, 200])
def test_an_unlisted_status_is_fatal(status):
    """A status this client has no reason to believe is transient must not be hammered."""
    assert H.classify(status=status) == "fatal"


def test_the_three_classes_do_not_overlap():
    assert not (H.RETRYABLE & H.RETRY_ONCE) and not (H.RETRYABLE & H.NEVER) and not (H.RETRY_ONCE & H.NEVER)


def test_classify_with_nothing_to_go_on_is_fatal():
    assert H.classify() == "fatal"
    assert H.classify(status=None, exc=None) == "fatal"


@pytest.mark.parametrize("exc", [
    socket.timeout("timed out"),
    TimeoutError("timed out"),
    ConnectionResetError(104, "Connection reset by peer"),
    http.client.RemoteDisconnected("Remote end closed connection without response"),
    http.client.IncompleteRead(b"partial"),
])
def test_every_face_of_a_dropped_connection_is_retryable(exc):
    """The same event reaches urlopen's caller under all of these names depending on platform and timing."""
    assert H.classify(exc=exc) == "retry"


@pytest.mark.parametrize("reason", [
    socket.timeout("timed out"),
    ConnectionResetError(104, "Connection reset by peer"),
    http.client.RemoteDisconnected("closed"),
    http.client.IncompleteRead(b"partial"),
])
def test_urlerror_wrapping_a_transient_is_retryable(reason):
    assert H.classify(exc=urllib.error.URLError(reason)) == "retry"


@pytest.mark.parametrize("reason", [
    socket.gaierror(-2, "Name or service not known"),
    ConnectionRefusedError(111, "Connection refused"),
    OSError("certificate verify failed"),
    "unknown url type",
])
def test_urlerror_with_any_other_reason_is_fatal(reason):
    """A typo'd base URL must not be retried six times to tell the operator what attempt one already knew."""
    assert H.classify(exc=urllib.error.URLError(reason)) == "fatal"


def test_an_httperror_passed_as_an_exception_is_judged_by_its_code():
    """HTTPError is a URLError subclass; without this it would fall into the reason branch and read as fatal."""
    assert H.classify(exc=_err(503)) == "retry"
    assert H.classify(exc=_err(500)) == "retry_once"
    assert H.classify(exc=_err(404)) == "fatal"


def test_an_unrelated_exception_is_fatal():
    assert H.classify(exc=ValueError("nope")) == "fatal"


# ------------------------------------------------------------------------------------- backoff


@pytest.mark.parametrize("attempt", range(6))
def test_backoff_stays_inside_its_band(attempt):
    base, cap = 1.0, 30.0
    lo = min(cap, base * 2 ** attempt)
    for r in (0.0, 0.5, 0.999):
        v = H.backoff_seconds(attempt, base, cap, lambda: r)
        assert lo <= v < lo + base, f"attempt {attempt} rand {r} -> {v}"


def test_backoff_is_capped():
    """Without the cap, attempt 10 on a base of 1s is a seventeen-minute sleep nobody asked for."""
    assert H.backoff_seconds(10, 1.0, 30.0, lambda: 0.0) == 30.0
    assert H.backoff_seconds(20, 2.0, 120.0, lambda: 0.0) == 120.0


def test_backoff_grows_exponentially_without_jitter():
    assert [H.backoff_seconds(n, 1.0, 1000.0, lambda: 0.0) for n in range(5)] == [1.0, 2.0, 4.0, 8.0, 16.0]


def test_two_seeds_do_not_retry_in_lockstep():
    """The whole point of the jitter: N fleet agents on one token must not wake up in the same second."""
    import random
    a = random.Random(1).random
    b = random.Random(2).random
    left = [H.backoff_seconds(n, 1.0, 30.0, a) for n in range(6)]
    right = [H.backoff_seconds(n, 1.0, 30.0, b) for n in range(6)]
    assert left != right
    assert all(x != y for x, y in zip(left, right))


# --------------------------------------------------------------------------------- Retry-After


def test_retry_after_integer_seconds():
    assert H.retry_after_seconds({"Retry-After": "7"}, 120.0) == 7.0


def test_retry_after_is_clamped_to_the_cap():
    """`Retry-After: 300` on a 900s budget would spend a third of the run asleep."""
    assert H.retry_after_seconds({"Retry-After": "300"}, 120.0) == 120.0


def test_retry_after_reads_a_message_case_insensitively():
    msg = _err(429, {"retry-after": "5"}).headers
    assert H.retry_after_seconds(msg, 120.0) == 5.0
    assert H.retry_after_seconds({"RETRY-AFTER": "5"}, 120.0) == 5.0


def test_retry_after_http_date():
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    when = email.utils.format_datetime(now + timedelta(seconds=45))
    assert H.retry_after_seconds({"Retry-After": when}, 120.0, now=now) == pytest.approx(45.0, abs=1.0)


def test_retry_after_http_date_over_the_cap_is_clamped():
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    when = email.utils.format_datetime(now + timedelta(seconds=600))
    assert H.retry_after_seconds({"Retry-After": when}, 120.0, now=now) == 120.0


def test_retry_after_in_the_past_is_zero_not_negative():
    now = datetime(2026, 9, 8, 12, 0, 0, tzinfo=timezone.utc)
    when = email.utils.format_datetime(now - timedelta(seconds=90))
    assert H.retry_after_seconds({"Retry-After": when}, 120.0, now=now) == 0.0


@pytest.mark.parametrize("headers", [None, {}, {"Retry-After": ""}, {"Retry-After": "soon"}, {"X-Other": "1"}])
def test_retry_after_absent_or_unparseable_is_none(headers):
    """None means "the server did not say", which is what makes the caller fall back to its own backoff."""
    assert H.retry_after_seconds(headers, 120.0) is None


def test_retry_after_uses_real_now_when_none_is_given():
    when = email.utils.format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30))
    v = H.retry_after_seconds({"Retry-After": when}, 120.0)
    assert 20.0 < v <= 30.0


# -------------------------------------------------------------------------------------- budget


def test_the_request_budget_stops_at_the_number_the_operator_typed():
    b = H.RequestBudget(max_requests=50)
    b.start(0.0)
    for i in range(50):
        b.spend_request("/rest/api/3/search/jql", float(i))
    with pytest.raises(H.JiraBudgetError) as e:
        b.spend_request("/rest/api/3/search/jql", 50.0)
    assert e.value.limit == "requests"
    assert e.value.requests_made == 50, "the count must match the flag, not the attempt that failed"
    assert e.value.last_path == "/rest/api/3/search/jql"
    assert e.value.elapsed == pytest.approx(50.0)
    assert "--max-requests" in e.value.hint


def test_the_seconds_budget_stops_a_slow_run():
    b = H.RequestBudget(max_requests=10_000, max_seconds=1.0)
    b.start(100.0)
    b.spend_request("/a", 100.5)
    with pytest.raises(H.JiraBudgetError) as e:
        b.spend_request("/rest/api/3/issue/RDSD-1/changelog", 101.0)
    assert e.value.limit == "seconds" and e.value.requests_made == 1
    assert e.value.elapsed == pytest.approx(1.0) and "--max-seconds" in e.value.hint


def test_the_retry_budget_stops_a_server_that_never_answers():
    b = H.RequestBudget(max_retries=3)
    b.start(0.0)
    for i in range(3):
        b.spend_retry("/x", float(i))
    with pytest.raises(H.JiraBudgetError) as e:
        b.spend_retry("/x", 3.0)
    assert e.value.limit == "retries" and b.retries == 3 and e.value.hint


def test_every_budget_error_says_what_to_do_and_where_it_stopped():
    for limit in ("requests", "seconds", "retries"):
        err = H.JiraBudgetError(limit, 42, 93.5, "/rest/api/3/changelog/bulkfetch")
        assert err.hint, f"{limit} has no hint"
        assert "42" in str(err) and "93.5" in str(err) and "bulkfetch" in str(err)


def test_a_budget_starts_itself_if_the_client_forgets():
    """Otherwise a client that never calls start() gets no seconds ceiling at all."""
    b = H.RequestBudget(max_seconds=5.0)
    b.spend_request("/a", 1000.0)
    assert b.started_at == 1000.0
    with pytest.raises(H.JiraBudgetError):
        b.spend_request("/a", 1005.0)


def test_start_zeroes_the_counters_for_a_second_run():
    b = H.RequestBudget()
    b.spend_request("/a", 0.0)
    b.spend_retry("/a", 0.0)
    b.start(10.0)
    assert (b.requests, b.retries, b.started_at) == (0, 0, 10.0)


def test_remaining_and_would_exceed_let_a_fallback_announce_its_cost():
    b = H.RequestBudget(max_requests=100)
    b.start(0.0)
    for i in range(10):
        b.spend_request("/a", 0.0)
    assert b.remaining_requests() == 90
    assert b.would_exceed(90) is False
    assert b.would_exceed(91) is True


def test_remaining_never_goes_negative():
    b = H.RequestBudget(max_requests=2)
    b.requests = 9
    assert b.remaining_requests() == 0


# ---------------------------------------------------------------------------------- rate limit


def test_cloud_headers_with_a_delta_reset():
    r = H.RateLimit.from_headers(
        {"X-RateLimit-Limit": "500", "X-RateLimit-Remaining": "5", "X-RateLimit-Reset": "7"}, now=1000.0)
    assert (r.limit, r.remaining, r.near_limit) == (500, 5, False)
    assert r.reset_at == 1007.0
    assert r.should_pause() is True
    assert r.pause_seconds(1000.0) == 7.0


def test_cloud_headers_with_an_epoch_reset():
    epoch = 1_788_000_000.0
    r = H.RateLimit.from_headers({"X-RateLimit-Limit": "500", "X-RateLimit-Remaining": "5",
                                 "X-RateLimit-Reset": str(int(epoch))}, now=epoch - 12.0)
    assert r.reset_at == epoch
    assert r.pause_seconds(epoch - 12.0) == 12.0


def test_near_limit_alone_is_enough_to_pause():
    r = H.RateLimit.from_headers({"X-RateLimit-NearLimit": "true"}, now=0.0)
    assert r.near_limit is True and r.should_pause() is True
    assert H.RateLimit.from_headers({"X-RateLimit-NearLimit": "false"}, now=0.0).should_pause() is False


def test_headers_are_case_insensitive():
    r = H.RateLimit.from_headers({"x-ratelimit-limit": "100", "X-RATELIMIT-REMAINING": "3",
                                  "x-RateLimit-NearLimit": "TRUE"}, now=0.0)
    assert (r.limit, r.remaining, r.near_limit) == (100, 3, True)


def test_plenty_of_quota_does_not_pause():
    r = H.RateLimit.from_headers({"X-RateLimit-Limit": "500", "X-RateLimit-Remaining": "400"}, now=0.0)
    assert r.should_pause() is False


def test_the_floor_ratio_is_the_boundary():
    r = H.RateLimit(limit=500, remaining=50)
    assert r.should_pause(0.10) is False, "exactly at the floor is not under it"
    assert H.RateLimit(limit=500, remaining=49).should_pause(0.10) is True
    assert r.should_pause(0.20) is True


def test_data_center_with_no_headers_at_all_is_reactive_only():
    """DC below 8.6 sends none of these. Absent must read as "unknown", never as "no quota left"."""
    r = H.RateLimit.from_headers({}, now=1000.0)
    assert (r.limit, r.remaining, r.reset_at, r.near_limit) == (None, None, None, False)
    assert r.should_pause() is False
    assert r.pause_seconds(1000.0) == 0.0
    assert H.RateLimit.from_headers(None, now=1000.0).should_pause() is False


def test_unparseable_header_values_are_treated_as_absent():
    """A header this client cannot read must not be able to make it sleep."""
    r = H.RateLimit.from_headers({"X-RateLimit-Limit": "many", "X-RateLimit-Remaining": "",
                                  "X-RateLimit-Reset": "later"}, now=0.0)
    assert (r.limit, r.remaining, r.reset_at) == (None, None, None)
    assert r.should_pause() is False


def test_a_reset_in_the_past_does_not_pause():
    r = H.RateLimit(limit=500, remaining=1, reset_at=900.0)
    assert r.should_pause() is True and r.pause_seconds(1000.0) == 0.0


def test_a_pause_is_clamped_so_a_wrong_clock_frame_cannot_hang_the_run():
    r = H.RateLimit(reset_at=1_788_000_000.0)
    assert r.pause_seconds(12_345.0) == H.MAX_PAUSE_SECONDS


def test_rate_limit_reads_the_headers_of_a_real_httperror():
    r = H.RateLimit.from_headers(_err(429, {"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "500"}).headers,
                                 now=0.0)
    assert (r.limit, r.remaining) == (500, 0) and r.should_pause() is True


# --------------------------------------------------------------------------------------- stats


def test_stats_meta_has_exactly_the_five_keys():
    d = H.Stats(requests=42, retries=3, rate_limit_waits=1, waited_seconds=12.0, elapsed_seconds=94.238475).as_dict()
    assert set(d) == {"requests", "retries", "rate_limit_waits", "waited_seconds", "elapsed_seconds"}
    assert d["requests"] == 42 and d["retries"] == 3 and d["rate_limit_waits"] == 1
    assert d["elapsed_seconds"] == 94.24, "a 14-digit float in TOON meta is noise, not precision"


def test_a_fresh_stats_is_all_zero():
    assert H.Stats().as_dict() == {"requests": 0, "retries": 0, "rate_limit_waits": 0,
                                   "waited_seconds": 0.0, "elapsed_seconds": 0.0}


def test_the_stats_line_names_every_number():
    line = H.Stats(requests=42, retries=3, rate_limit_waits=2, waited_seconds=12.0, elapsed_seconds=94.2).line()
    assert line == "42 requests, 3 retries, 2 rate-limit waits, 12.0s waiting, 94.2s elapsed"


def test_the_stats_line_reads_as_english_for_one():
    assert H.Stats(requests=1, retries=1, rate_limit_waits=1).line().startswith(
        "1 request, 1 retry, 1 rate-limit wait,")


# --------------------------------------------------------------------------------- hints, shape


def test_the_429_hint_no_longer_tells_the_human_to_do_what_the_client_already_did():
    hint = H.HINTS[429]
    assert "wait a minute and rerun" not in hint
    assert "Retry-After" in hint and "--max-requests" in hint


def test_every_hint_says_what_to_do_next():
    for status, hint in H.HINTS.items():
        assert hint and hint == hint.strip(), status


def test_an_http_error_carries_its_hint_and_quotes_only_the_head_of_the_body():
    e = H.JiraHTTPError(401, "/rest/api/3/myself", "x" * 500)
    assert e.status == 401 and e.path == "/rest/api/3/myself" and "ad-setup" in e.hint
    assert len(str(e)) < 260, "an error message is not a place to paste a response body"


def test_a_budget_error_is_a_jira_error_so_the_cli_catches_it_the_same_way():
    assert issubclass(H.JiraBudgetError, H.JiraError) and issubclass(H.JiraHTTPError, H.JiraError)


def test_the_request_layer_imports_nothing_but_the_standard_library():
    """jira_api imports jira_http; the reverse would be a cycle, and this module must stay socket-free."""
    import ast
    import sys

    tree = ast.parse(open(H.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0] or ".")
    assert "agentdata" not in imported and "." not in imported, f"{H.__name__} reaches back into the package"
    outside = imported - set(sys.stdlib_module_names)
    assert not outside, f"new dependency: {sorted(outside)}"
    assert "urllib" in imported and "socket" in imported


def test_nothing_here_opens_a_socket():
    """The decision layer is pure so the tests can be exhaustive without a network or a sleep."""
    src = open(H.__file__, encoding="utf-8").read()
    for banned in ("urllib.request", "requests.", "asyncio", "time.sleep"):
        assert banned not in src, f"{banned} has no business in the decision layer"
