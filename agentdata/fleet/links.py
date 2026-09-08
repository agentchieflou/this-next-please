"""The tile's link rail: the eight browser tabs, rebuilt from facts the project already declares.

The centre monitor in the photo carries eight bookmarks and the right monitor a Jira ticket, and
multiplying that by N projects is the tab count the operator named as the friction. The links are
the cheap half of the fix -- a tile that carries the ticket, the board, the report, the workspace,
the repository, the PR, the Confluence page and the folder is a tile the operator can act from
without hunting through a bookmark bar for the right project's copy of each.

**A missing fact means the link is absent, never broken.** `https://app.powerbi.com/groups//reports/`
is worse than no link: it looks clickable, it opens, and it lands on an error page that says nothing
about the fact that was never filled in. So every builder here refuses to compose a URL from a hole,
the row comes back with an empty `url` and a `why_missing` sentence instead, and `MISSING_KEYS_HINT`
names the `AGENTS.md` key that would supply it so `ad-fleet doctor` can print the one line the human
has to add. **A row with no `url` is not a link and must not be rendered.**

**Facts, not credentials, and nothing from a second project.** Everything comes from the repo's own
`AGENTS.md` (through `config.project_facts`, which drops placeholders) and its own
`.agent/state.json`, both already read by the catalogue. Nothing here opens a socket, asks for a
token or looks at another repository -- `links_for` is a pure function of what it is handed, which
is also why the tile can build a rail for a project whose Jira is unreachable.

**Two shapes of Jira, two shapes of board URL.** Cloud puts a board at
`/jira/software/c/projects/<KEY>/boards/<id>`; Data Center answers that path with its dashboard and
wants `/secure/RapidBoard.jspa?rapidView=<id>`. Guessing wrong produces exactly the broken link this
module exists to prevent, so the flavour `ad-jira` already recorded in the config (`jira.flavor`,
written by `remember_flavor`) decides, and an unrecorded flavour is inferred from the host --
`*.atlassian.net` is Cloud and nothing else is assumed to be.
"""
from __future__ import annotations
import os
import re
import urllib.parse

from .. import config as C
from .. import textio

# Every link a tile can show, in the order the rail renders them: what the operator reaches for
# first is first. A name added here needs a builder below and, unless it comes from the repo's own
# state, an entry in MISSING_KEYS_HINT -- the three are asserted to agree.
NAMES = ("ticket", "board", "report", "dataset", "workspace", "repo", "pr", "confluence", "folder")

# What kind of thing is on the other end, so the tile can group and icon the rail without matching
# on names. `local` is the one that opens a file manager rather than a browser tab.
KINDS = {"ticket": "jira", "board": "jira", "report": "powerbi", "dataset": "powerbi",
         "workspace": "powerbi", "repo": "git", "pr": "git", "confluence": "confluence",
         "folder": "local"}

# link name -> the AGENTS.md key whose absence is why the link is missing. `ad-fleet doctor` prints
# this key per repo, so it must be the key the human actually types into the facts block.
#
# `ticket`, `pr` and `confluence` are not here on purpose: they are supplied by the *agent* through
# `.agent/state.json` (`active_ticket`, `pr_url`, `confluence_url`), and telling a human to add an
# active ticket to AGENTS.md would be telling them to hand-maintain machine state. Their
# `why_missing` says so instead.
MISSING_KEYS_HINT = {
    "board": "jira_board_id",
    "report": "report_id",
    "dataset": "ds_id",
    "workspace": "ws_id",
    "repo": "bitbucket_repo",
    "folder": "",            # the registry supplies the path; there is nothing to add to AGENTS.md
}

POWERBI_BASE = "https://app.powerbi.com"
BITBUCKET_BASE = "https://bitbucket.org"

# A Jira key is <PROJECT>-<number>. Anything else in `active_ticket` is a note somebody typed, and
# `/browse/refactor the query` is a broken link with a 200 status.
TICKET = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")

# A workspace or dataset id is a GUID. `ws_id: <workspace guid>` survives `project_facts` only when
# somebody replaced the placeholder with something -- and "TODO" is something. Checking the shape is
# what stops a tile linking to `app.powerbi.com/groups/TODO`.
GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def links_for(repo, facts: dict | None = None, state: dict | None = None, *,
              cfg: dict | None = None) -> list[dict]:
    """The whole rail for one project: `{name, url, kind, why_missing}` per link, in `NAMES` order.

    Rows with a `url` are links. Rows without one are the doctor's material: `why_missing` says what
    is absent in words a human can act on, and `MISSING_KEYS_HINT[name]` names the key. Nothing is
    dropped, because the tile needs the first list and `ad-fleet doctor` needs the second, and a
    function that returned only the links would make the doctor re-derive them and disagree.

    `repo` is anything with a `.path` and a `.name` -- a `registry.Repo`, or the dict
    `catalogue.show()` returns. `facts` and `state` default to empty, which is the honest answer for
    a repository that has been registered and never indexed: every row comes back missing.
    """
    facts = dict(facts or {})
    state = dict(state or {})
    cfg = C.load() if cfg is None else cfg
    base = jira_base(facts, cfg)
    out = [
        _ticket(state, base),
        _board(facts, base, cfg),
        _report(facts),
        _dataset(facts),
        _workspace(facts),
        _repo(facts),
        _pr(state),
        _confluence(facts, state, base),
        _folder(repo),
    ]
    return out


def present(rows: list[dict]) -> list[dict]:
    """Just the rows a tile renders. The rail is short; the missing half belongs to the doctor."""
    return [r for r in rows if r.get("url")]


def missing_keys(rows: list[dict]) -> list[str]:
    """The AGENTS.md keys this repo would have to add, deduplicated and in rail order.

    What `ad-fleet doctor` prints per repository. Links the agent supplies are not listed: there is
    no key to add for them, and telling a human to fill in `active_ticket` is telling them to write
    a file `ad-state` owns.
    """
    out = []
    for row in rows:
        if row.get("url"):
            continue
        key = MISSING_KEYS_HINT.get(row.get("name", ""), "")
        if key and key not in out:
            out.append(key)
    return out


# ------------------------------------------------------------------------------- the bases


def jira_base(facts: dict, cfg: dict | None = None) -> str:
    """The Jira site, without a trailing slash, or "".

    Precedence is the project's own `jira_url` fact, then the `jira.base_url` the Jira client
    recorded on this machine, then `$JIRA_URL`. The project wins because one operator can work two
    tenants -- a contractor with their own Data Center instance beside the corporate Cloud one --
    and the config holds whichever `ad-jira whoami` ran last, which is not a property of the repo.

    No token is read and none is needed: the base URL is a public fact about where the site lives.
    """
    cfg = C.load() if cfg is None else cfg
    raw = (facts.get("jira_url") or C.get(cfg, "jira.base_url") or os.environ.get("JIRA_URL") or "")
    return _https(raw)


def jira_flavor(base: str, cfg: dict | None = None) -> str:
    """`"cloud"` or `"dc"` -- what the board URL shape depends on.

    `jira.flavor` is written by `jira_api.remember_flavor` after a real detection, so it is used when
    it is there. Without it the host decides, and only `*.atlassian.net` counts as Cloud: assuming
    Cloud for an unknown host would build a board link that 404s on every Data Center in existence,
    whereas assuming Data Center for a Cloud site is at worst a redirect.
    """
    recorded = str(C.get(C.load() if cfg is None else cfg, "jira.flavor") or "").strip().lower()
    if recorded in ("cloud", "dc"):
        return recorded
    host = urllib.parse.urlsplit(base).netloc.lower()
    return "cloud" if host.endswith(".atlassian.net") else "dc"


def _https(raw) -> str:
    """A base URL with a scheme and no trailing slash, or "" when there is nothing usable.

    A bare host is the shape people paste (`jira.example.com`), and `urljoin` on it produces a
    relative link that resolves against the dashboard's own origin -- a link to the fleet server
    that looks like a link to Jira. So a schemeless value is given https rather than trusted.
    """
    text = str(raw or "").strip().rstrip("/")
    if not text or text.startswith("<"):
        return ""
    if not text.startswith(("http://", "https://")):
        if text.startswith("/") or " " in text:
            return ""                       # a path or a sentence, not a site
        text = "https://" + text
    return text.rstrip("/")


# ------------------------------------------------------------------------------ the builders


def _row(name: str, url: str = "", why: str = "") -> dict:
    return {"name": name, "url": url, "kind": KINDS[name], "why_missing": "" if url else why}


def _ticket(state: dict, base: str) -> dict:
    key = str(state.get("active_ticket") or "").strip().upper()
    if not key:
        return _row("ticket", why="no active ticket: `.agent/state.json` has no `active_ticket` yet")
    if not TICKET.match(key):
        return _row("ticket", why=f"`active_ticket` is {key!r}, which is not a Jira key like RDSD-101")
    if not base:
        return _row("ticket", why="no Jira site: add a `jira_url` fact, or run `ad-jira whoami` once")
    return _row("ticket", f"{base}/browse/{key}")


def _board(facts: dict, base: str, cfg: dict | None) -> dict:
    board = str(facts.get("jira_board_id") or "").strip()
    project = str(facts.get("jira_project") or "").strip().upper()
    if not board.isdigit():
        return _row("board", why="no board: add `jira_board_id` to AGENTS.md (`ad-jira sprints --board` lists them)")
    if not base:
        return _row("board", why="no Jira site: add a `jira_url` fact, or run `ad-jira whoami` once")
    if jira_flavor(base, cfg) == "cloud":
        if not project:
            return _row("board", why="no `jira_project` in AGENTS.md, and a Cloud board URL needs it")
        return _row("board", f"{base}/jira/software/c/projects/{project}/boards/{board}")
    return _row("board", f"{base}/secure/RapidBoard.jspa?rapidView={board}")


def _report(facts: dict) -> dict:
    ws, report = _guid(facts, "ws_id"), _guid(facts, "report_id")
    if not ws:
        return _row("report", why="no `ws_id` in AGENTS.md (the workspace GUID, from `ad-pbi ws`)")
    if not report:
        return _row("report", why="no `report_id` in AGENTS.md (the report GUID from its URL in the service)")
    return _row("report", f"{POWERBI_BASE}/groups/{ws}/reports/{report}")


def _dataset(facts: dict) -> dict:
    ws, ds = _guid(facts, "ws_id"), _guid(facts, "ds_id")
    if not ws or not ds:
        return _row("dataset", why="no `ws_id` and `ds_id` in AGENTS.md (the workspace and semantic model GUIDs)")
    return _row("dataset", f"{POWERBI_BASE}/groups/{ws}/datasets/{ds}/details")


def _workspace(facts: dict) -> dict:
    ws = _guid(facts, "ws_id")
    if not ws:
        name = str(facts.get("pbi_workspace") or "").strip()
        why = ("`pbi_workspace` names the workspace but the service addresses it by GUID: "
               "add `ws_id` to AGENTS.md" if name else "no `ws_id` in AGENTS.md (the workspace GUID)")
        return _row("workspace", why=why)
    return _row("workspace", f"{POWERBI_BASE}/groups/{ws}")


def _repo(facts: dict) -> dict:
    """The Bitbucket repository. `bitbucket_repo` may be a full URL or `<workspace>/<slug>`.

    Both spellings are in use -- a URL is what somebody pastes out of the browser, `owner/slug` is
    what the CLI wants -- and refusing either would mean the fact is filled in and the link is still
    missing, which is the most annoying possible outcome of a facts block.
    """
    raw = str(facts.get("bitbucket_repo") or "").strip().rstrip("/")
    if not raw:
        return _row("repo", why="no `bitbucket_repo` in AGENTS.md (a repo URL, or `<workspace>/<slug>`)")
    if raw.startswith(("http://", "https://")):
        return _row("repo", raw)
    parts = [p for p in raw.split("/") if p]
    if len(parts) != 2:
        return _row("repo", why=f"`bitbucket_repo` is {raw!r}; it wants a URL or `<workspace>/<slug>`")
    base = _https(facts.get("bitbucket_url")) or BITBUCKET_BASE
    return _row("repo", f"{base}/{parts[0]}/{parts[1]}")


def _pr(state: dict) -> dict:
    url = _https(state.get("pr_url"))
    if not url:
        return _row("pr", why="no open PR: the agent has not written `pr_url` to `.agent/state.json`")
    return _row("pr", url)


def _confluence(facts: dict, state: dict, jira: str) -> dict:
    """The page the agent published, else the parent page the space hangs work under.

    The published page wins because it is the thing a human wants to read; the parent is the fallback
    that at least lands in the right space. A Cloud Confluence lives under `/wiki` on the Jira site,
    which is why the Jira base is enough there and a `confluence_base` fact is required elsewhere.
    """
    published = _https(state.get("confluence_url"))
    if published:
        return _row("confluence", published)
    parent = str(facts.get("confluence_parent") or "").strip()
    if not parent.isdigit():
        return _row("confluence", why="no published page, and no numeric `confluence_parent` in AGENTS.md")
    base = _https(facts.get("confluence_base"))
    if not base and jira and urllib.parse.urlsplit(jira).netloc.lower().endswith(".atlassian.net"):
        base = jira + "/wiki"
    if not base:
        return _row("confluence", why="no `confluence_base` in AGENTS.md (the wiki's own base URL)")
    space = str(facts.get("confluence_space") or "").strip()
    if space:
        return _row("confluence", f"{base}/spaces/{space}/pages/{parent}")
    return _row("confluence", f"{base}/pages/viewpage.action?pageId={parent}")


def _folder(repo) -> dict:
    """`file://` for the checkout, so "open the folder" is a click rather than a paste.

    The path goes through `textio.norm_path` and then `pathname2url`, because a Windows path in a
    URL is the one that is always wrong by hand: `C:/Users/Luna/My Repos` needs `file:///C:/...` with
    three slashes and the space percent-encoded, and `file://C:/Users/...` reads `C:` as a hostname.
    """
    path = textio.norm_path(str(getattr(repo, "path", "") or (repo.get("path", "") if isinstance(repo, dict) else "")))
    if not path:
        return _row("folder", why="the registry has no path for this repository")
    quoted = urllib.parse.quote(path, safe="/:")
    return _row("folder", "file:///" + quoted.lstrip("/"))


def _guid(facts: dict, key: str) -> str:
    value = str(facts.get(key) or "").strip()
    return value if GUID.match(value) else ""
