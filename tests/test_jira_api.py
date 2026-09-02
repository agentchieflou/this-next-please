import io, json, urllib.error, urllib.parse
import pytest
from agentdata import config as C
from agentdata.connectors import jira_api as J

TOKEN = "tok_SECRET_1234567890"


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """Routes (METHOD, path?query) -> JSON or an HTTP status; records every request."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, req, timeout=None, context=None):
        url = urllib.parse.urlsplit(req.full_url)
        key = f"{req.get_method()} {url.path}" + (f"?{url.query}" if url.query else "")
        self.calls.append((key, req.headers, req.data))
        for pat, resp in self.routes:
            if key.startswith(pat) if pat.endswith("*") is False else key.startswith(pat[:-1]):
                pass
            if (pat.endswith("*") and key.startswith(pat[:-1])) or key == pat:
                if callable(resp):
                    resp = resp(key, req)
                if isinstance(resp, int):
                    raise urllib.error.HTTPError(req.full_url, resp, "err", {"Retry-After": "3"} if resp == 429 else {}, io.BytesIO(b"{}"))
                return FakeResp(json.dumps(resp).encode())
        raise urllib.error.HTTPError(req.full_url, 404, "not routed", {}, io.BytesIO(b"{}"))


def creds(url="https://acme.atlassian.net", email="me@acme.com"):
    return J.Creds(url, email, TOKEN, "pncli:jira.token")


def client(routes, url="https://acme.atlassian.net", flavor=J.CLOUD, sleeps=None):
    op = FakeOpener(routes)
    j = J.Jira(creds(url), flavor, opener=op, sleep=(sleeps.append if sleeps is not None else lambda s: None))
    return j, op


def test_token_never_leaks():
    j, _ = client([])
    assert TOKEN not in repr(j) and TOKEN not in repr(j.creds)
    e = J.JiraHTTPError(401, "/x", "body")
    assert TOKEN not in str(e) and "ad-setup" in e.hint


def test_headers_basic_vs_bearer():
    j, _ = client([])
    assert j._headers(False)["Authorization"].startswith("Basic ")
    j2 = J.Jira(creds("https://jira.corp.local", None), J.DC_BEARER, opener=FakeOpener([]))
    assert j2._headers(True)["Authorization"] == f"Bearer {TOKEN}" and j2._headers(True)["Content-Type"] == "application/json"


def test_detect_flavor_cloud_without_probing_dc():
    op = FakeOpener([("GET /rest/api/3/myself", {"displayName": "Me", "accountId": "a1"})])
    j, me = J.detect_flavor(creds(), {}, opener=op)
    assert j.flavor == J.CLOUD and me["displayName"] == "Me" and len(op.calls) == 1


def test_detect_flavor_dc_bearer_then_basic():
    calls = []
    def myself(key, req):
        calls.append(req.headers["Authorization"][:6])
        if req.headers["Authorization"].startswith("Bearer"):
            return 401
        return {"name": "luna", "displayName": "Luna"}
    op = FakeOpener([("GET /rest/api/2/myself", myself)])
    j, me = J.detect_flavor(creds("https://jira.corp.local", None), {}, opener=op)
    assert j.flavor == J.DC_BASIC and calls == ["Bearer", "Basic "] and me["name"] == "luna"


def test_detect_flavor_uses_cached():
    cfg = {"jira": {"flavor": "dc", "auth": "bearer", "api": "2"}}
    op = FakeOpener([("GET /rest/api/2/myself", {"name": "x"})])
    j, _ = J.detect_flavor(creds("https://jira.corp.local"), cfg, opener=op)
    assert j.flavor == J.DC_BEARER


def test_paged_uses_echoed_max_results():
    pages = {"0": {"values": [1, 2], "maxResults": 2, "startAt": 0, "total": 3, "isLast": False},
             "2": {"values": [3], "maxResults": 2, "startAt": 2, "total": 3, "isLast": True}}
    op = FakeOpener([("GET /rest/api/3/x*", lambda key, req: pages[urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)["startAt"][0]])])
    j = J.Jira(creds(), J.CLOUD, opener=op)
    assert list(j.paged("/rest/api/3/x", page_size=100)) == [1, 2, 3] and len(op.calls) == 2


def test_changelog_rows_and_name_map():
    hist = {"values": [{"id": "10001", "author": None, "created": "2026-08-14T03:12:44.429+0000",
                        "items": [{"field": "Sprint", "fieldtype": "custom", "from": "12, 15", "fromString": "S41, S42", "to": "15", "toString": "S42"},
                                  {"field": "status", "fieldId": "status", "from": "3", "fromString": "In Progress", "to": "10001", "toString": "Done"}]}],
            "maxResults": 100, "startAt": 0, "total": 1, "isLast": True}
    j, op = client([("GET /rest/api/3/issue/RDSD-12/changelog*", hist)])
    rows = j.changelog("RDSD-12", {"sprint": "customfield_10020"})
    assert [r["field_id"] for r in rows] == ["customfield_10020", "status"]
    assert rows[0]["created_utc"] == "2026-08-14T03:12:44Z" and rows[0]["author"] is None and rows[0]["changelog_id"] == 10001
    assert rows[1]["to_str"] == "Done" and rows[1]["from_id"] == "3" and rows[0]["key"] == "RDSD-12"


def test_dc_expand_fallback_and_truncation():
    full = {"changelog": {"total": 1, "histories": [{"id": "1", "created": "2026-01-01T00:00:00.000+0000", "items": [{"field": "status", "from": "1", "to": "2"}]}]}}
    j, _ = client([("GET /rest/api/2/issue/K-1/changelog*", 404), ("GET /rest/api/2/issue/K-1?*", full)], "https://jira.corp", J.DC_BEARER)
    assert len(j.changelog("K-1")) == 1
    trunc = {"changelog": {"total": 250, "histories": [{"id": "1", "created": "2026-01-01T00:00:00.000+0000", "items": []}]}}
    j2, _ = client([("GET /rest/api/2/issue/K-2/changelog*", 404), ("GET /rest/api/2/issue/K-2?*", trunc)], "https://jira.corp", J.DC_BEARER)
    with pytest.raises(J.JiraError) as ei:
        j2.changelog("K-2")
    assert "truncated" in str(ei.value)


def test_bulk_changelog_dedupes_and_maps_ids():
    page1 = {"issueChangeLogs": [{"issueId": "100", "changeHistories": [
        {"id": "7", "created": 1492070429, "items": [{"field": "status", "fieldId": "status", "fromString": "A", "toString": "B"}]}]}], "nextPageToken": "t2"}
    page2 = {"issueChangeLogs": [{"issueId": "100", "changeHistories": [
        {"id": "7", "created": 1492070429, "items": [{"field": "status", "fieldId": "status", "fromString": "A", "toString": "B"}]},
        {"id": "8", "created": 1492070500000, "items": [{"field": "Sprint", "fieldId": "customfield_10020", "from": "1", "to": "2"}]}]}]}
    def bulk(key, req):
        body = json.loads(req.data)
        assert body["issueIdsOrKeys"] == ["RDSD-1"] and body["fieldIds"] == ["status", "customfield_10020"]
        return page2 if body.get("nextPageToken") == "t2" else page1
    j, op = client([("GET /rest/api/3/search/jql*", {"issues": [{"id": "100", "key": "RDSD-1"}]}),
                    ("POST /rest/api/3/changelog/bulkfetch", bulk)])
    rows = j.bulk_changelog(["RDSD-1"], ["status", "customfield_10020"])
    assert [r["changelog_id"] for r in rows] == [7, 8] and rows[0]["key"] == "RDSD-1" and rows[0]["created_utc"] == "2017-04-13T08:00:29Z"
    assert rows[1]["created_utc"] == "2017-04-13T08:01:40Z"


def test_bulk_falls_back_on_404():
    hist = {"values": [{"id": "1", "created": "2026-01-01T00:00:00.000+0000", "items": [{"field": "status", "from": "1", "to": "2"}]}], "isLast": True, "maxResults": 100}
    j, _ = client([("GET /rest/api/3/search/jql*", {"issues": [{"id": "1", "key": "K-1"}]}), ("POST /rest/api/3/changelog/bulkfetch", 404),
                   ("GET /rest/api/3/issue/K-1/changelog*", hist)])
    assert len(j.bulk_changelog(["K-1"])) == 1


def test_search_cloud_jql_then_fallback():
    j, op = client([("GET /rest/api/3/search/jql*", lambda k, r: {"issues": [{"key": "A-1"}], "nextPageToken": None})])
    assert [i["key"] for i in j.search("project = A", ["key"])] == ["A-1"]
    assert "fields=key" in op.calls[0][0] and "maxResults=100" in op.calls[0][0]
    j2, op2 = client([("GET /rest/api/3/search/jql*", 410), ("GET /rest/api/3/search*", {"issues": [{"key": "A-2"}], "isLast": True, "maxResults": 50})])
    assert [i["key"] for i in j2.search("project = A", ["key"])] == ["A-2"]


def test_retry_after_then_success():
    n = {"c": 0}
    def flaky(key, req):
        n["c"] += 1
        return 429 if n["c"] == 1 else {"ok": 1}
    sleeps = []
    j, _ = client([("GET /rest/api/3/myself", flaky)], sleeps=sleeps)
    assert j.myself() == {"ok": 1} and sleeps == [3.0]


def test_statuses_and_pin_fields():
    sts = [{"id": "3", "name": "In Progress", "statusCategory": {"key": "indeterminate"}}, {"id": "10001", "name": "Done", "statusCategory": {"key": "done"}}]
    j, _ = client([("GET /rest/api/3/status", sts)])
    cat = j.statuses()
    assert cat["10001"] == "done" and cat["done"] == "done" and cat["3"] == "indeterminate"
    fields = [{"id": "customfield_10020", "name": "Sprint", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
              {"id": "customfield_10026", "name": "Story Points"}, {"id": "customfield_10016", "name": "Story point estimate"},
              {"id": "status", "name": "Status"}]
    pins = J.pin_fields(fields)
    assert pins["sprint"] == "customfield_10020" and pins["story_points"] == ["customfield_10026", "customfield_10016"]
    assert J.resolve_field_ids(["status", "Sprint", '"Story Points"', "customfield_9"], fields) == ["status", "customfield_10020", "customfield_10026", "customfield_9"]


def test_load_credentials_from_pncli_and_env(tmp_path, monkeypatch):
    p = tmp_path / "pncli.json"
    p.write_text(json.dumps({"jira": {"url": "acme.atlassian.net/", "email": "me@acme.com", "token": TOKEN}}), encoding="utf-8")
    for v in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    cfg = {"pncli": {"config_path": str(p), "keys": {"jira_url": "jira.url", "jira_email": "jira.email", "jira_token": "jira.token"}}}
    c = J.load_credentials(cfg)
    assert c.base_url == "https://acme.atlassian.net" and c.email == "me@acme.com" and c.token == TOKEN and c.source == "pncli:jira.token"
    monkeypatch.setenv("JIRA_TOKEN", "envtok"); monkeypatch.setenv("JIRA_URL", "https://other")
    assert J.load_credentials(cfg).source == "env" and J.load_credentials(cfg).base_url == "https://other"
    monkeypatch.delenv("JIRA_TOKEN"); monkeypatch.delenv("JIRA_URL")
    with pytest.raises(J.JiraError) as ei:
        J.load_credentials({"pncli": {"config_path": str(tmp_path / "missing.json")}})
    assert "pncli config init" in ei.value.hint
    with pytest.raises(J.JiraError):
        J.load_credentials({"pncli": {"config_path": str(p), "keys": {"jira_token": "nope.key"}}})


def test_parse_ts_forms():
    assert J.parse_ts("2026-08-14T03:12:44.429+0000").isoformat() == "2026-08-14T03:12:44.429000+00:00"
    assert J.parse_ts("2015-04-11T15:22:00.000+10:00").isoformat() == "2015-04-11T05:22:00+00:00"
    assert J.parse_ts("2026-01-01T00:00:00Z").isoformat() == "2026-01-01T00:00:00+00:00"
    assert J.parse_ts(1492070429).year == 2017 and J.parse_ts(1492070429000).year == 2017
