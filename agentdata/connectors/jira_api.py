"""Jira REST client (stdlib only). Reuses pncli's Jira token: read at call time from pncli's own config by
dot-path (ad-setup --only pncli picks the keys); env JIRA_URL / JIRA_EMAIL / JIRA_TOKEN override.
Flavor is detected once and cached in agentdata config: Cloud = REST v3 + Basic(email:token),
Data Center = REST v2 + Bearer PAT (Basic as a fallback). The token never appears in output or errors."""
from __future__ import annotations
import base64
import email.utils
import getpass
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterator
from .. import config as C

USER_AGENT = "agentdata/0.1"
_HINTS = {
    401: "token rejected; re-run ad-setup --only pncli, or set JIRA_TOKEN / JIRA_EMAIL",
    403: "no permission on this project or issue",
    404: "not found (issue key, endpoint, or wrong Jira flavor); try ad-jira whoami --redetect",
    429: "rate limited even after retries; wait a minute and rerun",
}


class JiraError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


class JiraHTTPError(JiraError):
    def __init__(self, status: int, path: str, body: str = ""):
        super().__init__(f"HTTP {status} on {path}: {body[:200]}", hint=_HINTS.get(status, ""))
        self.status, self.path = status, path


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
            with open(p, encoding="utf-8") as f:
                pj = json.load(f)
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


def _retry_after(headers, attempt: int) -> float:
    ra = headers.get("Retry-After") if headers else None
    if ra and str(ra).strip().isdigit():
        return min(int(ra), 60)
    if ra:
        try:
            dt = email.utils.parsedate_to_datetime(ra)
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
        except Exception:  # noqa: BLE001
            pass
    return float(2 ** attempt)  # 1, 2, 4, 8


class Jira:
    def __init__(self, creds: Creds, flavor: Flavor, timeout: int = 60, ca_bundle: str | None = None,
                 sleep: Callable[[float], None] = time.sleep, opener: Callable | None = None):
        self.creds, self.flavor, self.timeout, self.sleep = creds, flavor, timeout, sleep
        self._open = opener or urllib.request.urlopen
        self.ssl_ctx = ssl.create_default_context(cafile=ca_bundle or os.environ.get("AGENTDATA_CA_BUNDLE") or None)

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

    def request(self, method: str, path: str, params: dict | None = None, body: Any = None) -> Any:
        url = self.creds.base_url + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(5):
            req = urllib.request.Request(url, data=data, method=method, headers=self._headers(data is not None))
            try:
                with self._open(req, timeout=self.timeout, context=self.ssl_ctx) as r:
                    raw = r.read()
                    return json.loads(raw) if raw.strip() else None
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 4:
                    self.sleep(_retry_after(e.headers, attempt))
                    continue
                try:
                    body_txt = e.read()[:300].decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    body_txt = ""
                raise JiraHTTPError(e.code, path, body_txt) from None
            except urllib.error.URLError as e:
                raise JiraError(f"network error reaching {self.creds.base_url}: {e.reason}",
                                hint="check VPN / proxy (HTTPS_PROXY) / AGENTDATA_CA_BUNDLE") from None
        raise JiraError(f"gave up after retries on {path}")

    def get(self, path: str, params: dict | None = None) -> Any:
        return self.request("GET", path, params)

    def post(self, path: str, body: Any, params: dict | None = None) -> Any:
        return self.request("POST", path, params, body)

    def myself(self) -> dict:
        return self.get(f"{self.api}/myself")

    # ---------- pagination ----------
    def paged(self, path: str, params: dict | None = None, values_key: str = "values", page_size: int = 100) -> Iterator[dict]:
        """startAt/maxResults paging. Uses the *echoed* maxResults (the server may cap the request)."""
        start = 0
        while True:
            page = self.get(path, {**(params or {}), "startAt": start, "maxResults": page_size}) or {}
            values = page.get(values_key) or []
            yield from values
            if not values or page.get("isLast") is True:
                return
            start += page.get("maxResults") or len(values)
            total = page.get("total")
            if total is not None and start >= int(total):
                return

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

    # ---------- changelog ----------
    def changelog(self, key: str, name_to_id: dict | None = None) -> list[dict]:
        """All change items of one issue as flat rows (see history_rows). DC without the paged endpoint falls back to
        ?expand=changelog and refuses to silently return a truncated history."""
        try:
            hist = list(self.paged(f"{self.api}/issue/{key}/changelog"))
        except JiraHTTPError as e:
            if e.status != 404 or self.flavor.kind == "cloud":
                raise
            cl = (self.issue(key, ["summary"], expand="changelog") or {}).get("changelog") or {}
            hist = cl.get("histories") or []
            total = cl.get("total")
            if total is not None and int(total) > len(hist):
                raise JiraError(f"changelog truncated for {key}: {len(hist)} of {total} entries",
                                hint="this Jira lacks the paged changelog endpoint; use the Teradata history for older events") from None
        rows: list[dict] = []
        for h in hist:
            rows.extend(history_rows(key, h, name_to_id))
        return rows

    def bulk_changelog(self, keys: list[str], field_ids: list[str] | None = None, name_to_id: dict | None = None,
                       id_to_key: dict | None = None) -> list[dict]:
        """Cloud bulkfetch (<=1000 issues, <=10 field ids per call); falls back to per-issue on 404/405."""
        if self.flavor.kind != "cloud":
            return [r for k in keys for r in self.changelog(k, name_to_id)]
        id_to_key = dict(id_to_key or {})
        if not id_to_key:
            for i in range(0, len(keys), 100):
                chunk = keys[i:i + 100]
                for iss in self.search("key in (" + ",".join(chunk) + ")", ["key"]):
                    id_to_key[str(iss.get("id"))] = iss.get("key")
        rows: list[dict] = []
        seen: set[tuple] = set()
        for i in range(0, len(keys), 1000):
            body: dict = {"issueIdsOrKeys": keys[i:i + 1000], "maxResults": 1000}
            if field_ids:
                body["fieldIds"] = field_ids[:10]
            try:
                pages = list(self.paged_token(f"{self.api}/changelog/bulkfetch", body=body, values_key="issueChangeLogs"))
            except JiraHTTPError as e:
                if e.status in (404, 405, 400):
                    return [r for k in keys for r in self.changelog(k, name_to_id)]
                raise
            for entry in pages:
                iid = str(entry.get("issueId"))
                key = id_to_key.get(iid) or iid
                for h in entry.get("changeHistories") or []:
                    sig = (iid, str(h.get("id")))
                    if sig in seen:
                        continue
                    seen.add(sig)
                    rows.extend(history_rows(key, h, name_to_id))
        return rows

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
