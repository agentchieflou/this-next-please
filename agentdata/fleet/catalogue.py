"""A read-only catalogue over what every registered repository already publishes.

The operator's request was "all my projects live under one folder, so give an agent the folder and
build me a RAG". This module is the answer to that request, and the reason it is *not* a RAG is
worth stating here, because the obvious "improvement" to this file is to bolt an embedding index
onto it and that would undo all three of the constraints it was built under:

* **AGENTS.md rule 3** -- an agent never reads a second project's `.agent/`. A folder-wide agent
  breaks that on its first `ls`. The thing that may read across projects is the fleet supervisor, a
  plain Python process the human runs, never a model. Nothing here is reachable from an agent.
* **The corporate policy disables MCP.** A vector store only pays off if a model can query it, and
  the only query path a model has on this laptop is an `ad-*` command printing TOON. So the query
  path is `ad-fleet where`, typed by the human, and the leverage is the same.
* **What answers the real questions already exists per repo**, structured, small and credential-
  free: the `AGENTS.md` facts, `.agent/state.json`, the friction STOPs, and the PBIP projections.
  "Which project owns Velocity, what ticket is it on, which branch" is answered by indexing *that*.
  Indexing the source trees answers nothing more and is where the credential and volume risk lives.

Two things make "safe" mechanical rather than aspirational.

**The allow-list is a code path, not a policy.** `ALLOWED_KINDS` and `allows()` decide which
repo-relative names may be opened, every read in this module goes through `_read()`, and `_read()`
refuses a path `allows()` does not name. There is no directory walk and no config knob: a planted
`.env`, `localSettings.json` or `~/.pncli/config.json` is not skipped by a rule, it is never
constructed as a path in the first place. Adding a file kind is a change here plus a test.

A name, though, is not a location, so `_read()` also asks `_inside()` where the name actually leads.
A symlink or an NTFS junction spelled `.agent/friction/20260908T0900-notes.md` and pointing at
`~/.pncli/config.json` passes `allows()` on spelling alone, and `os.path.isfile()` follows it. That
is the one way the paragraph above was false, and it is refused by realpath, named in the index
report, and covered by a test.

**A doc that looks like it carries a credential is not indexed at all.** The sources are supposed to
be credential-free, but "supposed to" is how a token ends up in a searchable database that then gets
copied to another machine. `looks_like_a_credential()` reuses the patterns `config.save()` already
refuses; the refusal names the pattern and the file, never the line.

`sqlite3` with FTS5 where the interpreter's SQLite has it and a plain `LIKE` scan where it does not
-- `self.fts` records which is live so `ad-doctor` can state it, and the mode is stored in the file
so a catalogue built on the fallback is rebuilt rather than silently searched with an empty index.
"""
from __future__ import annotations
import json
import os
import re
import sqlite3
import threading
import time

from .. import config as C
from .. import textio
from .registry import fleet_dir

CATALOGUE = "catalogue.sqlite"
SCHEMA = 1

# Forcing the LIKE path on a machine whose SQLite has FTS5, so CI exercises the fallback the
# laptop will never take. A knob for tests and for `ad-doctor`, never for what is indexed.
NO_FTS_ENV = "AGENTDATA_FLEET_NO_FTS5"

# ------------------------------------------------------------------------------- the allow-list

ALLOWED_KINDS = ("agents", "state", "friction", "pbip_model", "pbip_report", "pbip_lineage",
                 "pbip_meta", "git")

# One exact repo-relative name each. These two are what makes a folder a project at all.
FIXED = {"agents": "AGENTS.md", "state": ".agent/state.json"}
FRICTION_DIR = ".agent/friction"
PBIP_DIR = ".agent/pbip"
# file name -> kind, inside `.agent/pbip/<name>/` and nowhere else
PBIP_FILES = {"MODEL.md": "pbip_model", "REPORT.md": "pbip_report",
              "LINEAGE.md": "pbip_lineage", "meta.json": "pbip_meta"}
GIT_HEAD = ".git/HEAD"
GIT_REFS = ".git/refs/heads/"

SNIPPET_CHARS = 160
TITLE_WEIGHT = 10.0     # a hit in a heading is worth ten in a paragraph, in both search paths


class CatalogueError(Exception):
    """Refused, with a hint saying what the human should do next."""

    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint


def allows(rel: str) -> str:
    """The kind `rel` may be read as, or `""`. This function *is* the allow-list.

    `rel` is a repo-relative path with forward slashes. Everything is refused by default, `..` and
    absolute paths are refused outright, and the four PBIP names are only allowed exactly one
    directory below `.agent/pbip/` -- so `.agent/pbip/../../.env` cannot spell its way in.
    """
    rel = textio.norm_path(rel or "")
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or rel.startswith("/") or ".." in rel.split("/") or ":" in rel:
        return ""
    for kind, name in FIXED.items():
        if rel == name:
            return kind
    if rel.startswith(FRICTION_DIR + "/"):
        tail = rel[len(FRICTION_DIR) + 1:]
        return "friction" if tail.endswith(".md") and "/" not in tail else ""
    if rel.startswith(PBIP_DIR + "/"):
        parts = rel[len(PBIP_DIR) + 1:].split("/")
        return PBIP_FILES.get(parts[1], "") if len(parts) == 2 and parts[0] else ""
    if rel == GIT_HEAD:
        return "git"
    if rel.startswith(GIT_REFS):
        tail = rel[len(GIT_REFS):]
        return "git" if tail and not tail.endswith("/") else ""
    return ""


def _inside(repo_path: str, rel: str) -> str:
    """`rel` as an absolute path, proven to still be inside `repo_path` once the links resolve.

    `allows()` reads a *name*, and a name is not a location. A symlink -- or an NTFS junction, which
    is what a Windows operator actually ends up with -- called `.agent/friction/20260908T0900.md`
    and pointing at `~/.pncli/config.json` is allow-listed by spelling and is a live Jira token by
    content: `os.path.isfile` in `_candidates` follows it and `open()` follows it again. Without
    this check the module docstring's claim that `~/.pncli/config.json` "is never constructed as a
    path" holds only for files that are where they say they are. `serve.verify_for` had the same
    hole closed first and this is deliberately the same guard in the same words.
    """
    full = os.path.join(repo_path, *rel.split("/"))
    root = textio.norm_path(os.path.realpath(repo_path))
    real = textio.norm_path(os.path.realpath(full))
    if real != root and not real.startswith(root + "/"):
        raise ValueError(f"the catalogue may not read {rel!r}: it resolves outside the repository")
    return full


def _read(repo_path: str, rel: str) -> str:
    """The only way this module opens a file in a repository.

    Through `textio`, because a friction file written by PowerShell 5.1 carries a UTF-8 BOM and an
    `AGENTS.md` someone saved from Notepad is cp1252; behind `allows()`, so a caller that grows a
    new source has to add the kind here rather than passing a path; and behind `_inside()`, so the
    allow-listed *name* has to also be an allow-listed *file*.
    """
    kind = allows(rel)
    if not kind:
        raise ValueError(f"the catalogue may not read {rel!r}: it is not on the allow-list")
    return textio.read_text(_inside(repo_path, rel))


# --------------------------------------------------------------------------- credential refusal

# The same shape `config.save()` refuses, applied to a *value* rather than a config key: a doc is
# arbitrary prose, so the offending thing is `key: value` or `key=value` written in it.
_ASSIGNMENT = re.compile(r"([A-Za-z_][\w.\-]{0,60})\s*[:=]\s*(\S[^\n]{0,200})")
# Deliberately strict, and it will occasionally refuse an AGENTS.md that merely *mentions* bearer
# auth. That is the trade the epic asked for: a refused doc costs one search result and says so in
# the report, a missed one puts a live token in a sqlite file that gets copied between machines.
_BEARER = re.compile(r"\bBearer\s+\S")
# a value nobody has filled in yet. The AGENTS.md stub ships `- jira_token: <set in pncli>`, and a
# catalogue that refused every freshly generated project would be uninstalled by lunchtime.
_PLACEHOLDER = re.compile(r"^(?:<.*>|\*+|x+|none|null|todo|tbd|\.\.\.)$", re.I)


def looks_like_a_credential(text: str) -> str | None:
    """The name of the credential pattern `text` carries, or None.

    Returns a *pattern name* ("token", "password", "bearer"), never the offending text: the whole
    point is that the value does not travel any further, and an error message is a place values
    travel to. The key shapes come from `config.py`'s own compiled pattern -- the one `save()`
    refuses on -- so there is one list in this repository to keep current, not two.
    """
    if not text:
        return None
    if _BEARER.search(text):
        return "bearer"
    for key, value in _ASSIGNMENT.findall(text):
        # `pncli.keys.jira_token: some.dot.path` names *where* the token is kept, which is exactly
        # what AGENTS.md is supposed to say. config.py exempts the same prefix for the same reason.
        if key.lower().startswith("pncli.keys."):
            continue
        # config's own compiled pattern, not a copy of it: two lists of credential key shapes drift,
        # and the copy in events.py is already the second one this repo has to keep in step.
        m = C._SECRET_KEY.search(key.rsplit(".", 1)[-1])
        if not m:
            continue
        value = value.strip().strip("`\"'")
        if value.startswith("<") and value.endswith(">"):
            continue
        first = value.split()[0] if value.split() else ""
        if len(first) < 3 or _PLACEHOLDER.match(first):
            continue
        return m.group(1).lower()
    return None


# ------------------------------------------------------------------------------ reading a repo


_HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.M)
_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_STAMP = re.compile(r"(\d{4})(\d{2})(\d{2})T?(\d{2})?(\d{2})?")


def _heading(text: str, fallback: str) -> str:
    m = _HEADING.search(text)
    return " ".join(m.group(1).split())[:120] if m else fallback


def _front_matter(text: str) -> dict:
    """The `key: value` block a friction file opens with. Not YAML; the template is flat."""
    m = _FRONT_MATTER.search(text)
    out: dict[str, str] = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _friction_date(name: str, front: dict) -> str:
    """The date on a friction STOP, from the file name the skill was told to use.

    `friction-log` names the file `<UTC yyyymmddTHHMM>-<skill>.md`, so the stamp is in the name and
    the front matter has no date field. Falling back to the file's mtime would be wrong: these files
    get copied between checkouts and the mtime is then the copy's, not the moment of the stop.
    """
    for source in (name, front.get("date", "")):
        m = _STAMP.search(source or "")
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


# The only `.agent/state.json` fields that ever leave the repository. One tuple, because there used
# to be two: `_state_text` rendered these keys and `_build` put the *whole parsed file* in the `data`
# column, so `looks_like_a_credential` inspected a projection while the original was what got
# stored. A `jira_token` written next to `phase` in somebody's state.json therefore passed the
# sweep, landed in `catalogue.sqlite` -- the file that gets copied between machines -- and came back
# out of `/api/show` and `/api/desk`. What is checked and what is kept are now the same dict.
STATE_KEYS = ("project", "phase", "active_ticket", "branch", "pr_url", "confluence_url",
              "last_updated")
STATE_LISTS = ("open_questions", "artifacts")
# A state file with two hundred open questions is a search result nobody reads and a row that
# dwarfs every other doc in the table.
STATE_LIST_CAP = 20


def _state_doc(state: dict) -> dict:
    """The projection of `.agent/state.json` the catalogue is allowed to keep.

    Everything outside `STATE_KEYS`/`STATE_LISTS` is dropped rather than carried: state.json is
    hand-editable JSON that the fleet only reads, and republishing whatever else somebody put in it
    is how a token, a share path or a customer name reaches a browser tab.
    """
    out: dict = {}
    for key in STATE_KEYS:
        value = state.get(key)
        if value not in (None, "", [], {}):
            out[key] = value
    for key in STATE_LISTS:
        values = state.get(key)
        if isinstance(values, list) and values:
            out[key] = values[:STATE_LIST_CAP]
    return out


def _state_text(doc: dict) -> str:
    """`_state_doc()`'s projection as lines a search can hit and a snippet can show.

    The raw JSON would index just as well and read appallingly in a result row -- and the row is the
    whole point of `ad-fleet where RDSD-22449`. Takes the projection, not the file, so the text the
    credential sweep runs against is the text of exactly what will be stored.
    """
    lines = [f"{key}: {doc[key]}" for key in STATE_KEYS if key in doc]
    lines += [f"open question: {q}" for q in doc.get("open_questions") or []]
    lines += [f"artifact: {a}" for a in doc.get("artifacts") or []]
    return "\n".join(lines)


class _Doc:
    """One row on its way into the database. Not part of the contract; `where`/`show` return dicts."""

    __slots__ = ("kind", "rel", "title", "text", "data", "mtime", "size")

    def __init__(self, kind, rel, title, text, data=None, mtime=0.0, size=0):
        self.kind, self.rel, self.title, self.text = kind, rel, title, text
        self.data, self.mtime, self.size = data, mtime, size


def _stat(repo_path: str, rel: str) -> tuple[float, int]:
    st = os.stat(textio.longpath(os.path.join(repo_path, *rel.split("/"))))
    return st.st_mtime, st.st_size


def _git_ref(repo_path: str) -> str:
    """The repo-relative ref file `.git/HEAD` points at, or "" for a detached HEAD or a packed ref."""
    try:
        head = _read(repo_path, GIT_HEAD).strip()
    except (OSError, ValueError):
        return ""
    if not head.startswith("ref:"):
        return ""
    rel = textio.norm_path(".git/" + head.split(":", 1)[1].strip())
    if not allows(rel) or not os.path.isfile(os.path.join(repo_path, *rel.split("/"))):
        return ""
    return rel


def _git_stamp(repo_path: str) -> tuple[float, int]:
    """The change stamp for the git doc: the newer of `.git/HEAD` and the ref it names.

    `git commit` does not touch `HEAD` -- it rewrites `.git/refs/heads/<branch>` -- so keying the
    git doc on HEAD alone would leave the dashboard showing the sha and date of whatever commit was
    current the first time the repo was indexed, for as long as the operator stayed on one branch.
    """
    mtime, size = _stat(repo_path, GIT_HEAD)
    ref = _git_ref(repo_path)
    if ref:
        try:
            mtime = max(mtime, _stat(repo_path, ref)[0])
        except OSError:
            pass
    return mtime, size


def _candidates(repo_path: str) -> list[tuple[str, str]]:
    """Every (kind, repo-relative path) this repo offers, in allow-list order.

    The two directories below are *listed*, never walked: one level under `.agent/friction`, one
    level under `.agent/pbip`, and only the four names in `PBIP_FILES`.
    """
    out: list[tuple[str, str]] = []
    for kind, name in FIXED.items():
        if os.path.isfile(os.path.join(repo_path, *name.split("/"))):
            out.append((kind, name))
    friction = os.path.join(repo_path, *FRICTION_DIR.split("/"))
    if os.path.isdir(friction):
        for name in sorted(os.listdir(friction)):
            if name.endswith(".md") and os.path.isfile(os.path.join(friction, name)):
                out.append(("friction", f"{FRICTION_DIR}/{name}"))
    pbip = os.path.join(repo_path, *PBIP_DIR.split("/"))
    if os.path.isdir(pbip):
        for project in sorted(os.listdir(pbip)):
            if not os.path.isdir(os.path.join(pbip, project)):
                continue
            for name, kind in PBIP_FILES.items():
                if os.path.isfile(os.path.join(pbip, project, name)):
                    out.append((kind, f"{PBIP_DIR}/{project}/{name}"))
    if os.path.isfile(os.path.join(repo_path, *GIT_HEAD.split("/"))):
        out.append(("git", GIT_HEAD))
    return out


def _build(repo_path: str, kind: str, rel: str) -> _Doc:
    """Read one allow-listed file and turn it into a doc. Raises OSError/ValueError on a bad file."""
    if kind == "git":
        return _git_doc(repo_path)
    mtime, size = _stat(repo_path, rel)

    raw = _read(repo_path, rel)
    name = rel.rsplit("/", 1)[-1]

    if kind == "state":
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError("state.json is not an object")
        doc = _state_doc(state)
        title = " ".join(x for x in (doc.get("project") or "", doc.get("phase") or "") if x)
        return _Doc(kind, rel, title or "state", _state_text(doc), doc, mtime, size)

    if kind == "friction":
        front = _front_matter(raw)
        date = _friction_date(name, front)
        kindof = front.get("type", "")
        data = {"type": kindof, "date": date, "severity": front.get("severity", ""),
                "ticket": front.get("ticket", ""), "skill": front.get("skill_in_use", ""),
                "unblock": _unblock(raw)}
        header = " · ".join(x for x in (kindof, date, front.get("severity", "")) if x)
        body = raw[_FRONT_MATTER.search(raw).end():] if _FRONT_MATTER.search(raw) else raw
        return _Doc(kind, rel, f"friction: {name[:-3]}", f"{header}\n{body}".strip(), data,
                    mtime, size)

    if kind == "pbip_meta":
        meta = json.loads(raw)
        project = rel.split("/")[2]
        sources = sorted((meta.get("sources") or {}).keys()) if isinstance(meta, dict) else []
        # the hashes are noise in a search result and a hash is the one thing in this file that
        # looks like a secret to a human reading a snippet; the source paths are what is useful.
        return _Doc(kind, rel, f"{project} sources", "\n".join(sources),
                    {"pbip": project, "sources": sources}, mtime, size)

    if kind.startswith("pbip_"):
        project = rel.split("/")[2]
        return _Doc(kind, rel, _heading(raw, f"{project}/{name}"), raw, {"pbip": project},
                    mtime, size)

    return _Doc(kind, rel, _heading(raw, name), raw, None, mtime, size)


_UNBLOCK = re.compile(r"##\s*What would unblock me\s*\n+(.+?)(?:\n#|\Z)", re.S | re.I)


def _unblock(text: str) -> str:
    m = _UNBLOCK.search(text)
    return " ".join((m.group(1) if m else "").split())[:300]


def _git_doc(repo_path: str) -> _Doc:
    """Branch and last-commit date from `.git/HEAD` and the ref it points at.

    Two file reads rather than `git rev-parse`: the index must be instant across a dozen repos on a
    laptop where every process launch is scanned by antivirus, and shelling out would also mean a
    `git` on PATH, which the allow-list argument does not cover.
    """
    head = _read(repo_path, GIT_HEAD).strip()
    mtime, size = _git_stamp(repo_path)
    branch, sha, when = "", "", ""
    if head.startswith("ref:"):
        # `refs/heads/feature/velocity-gate` is one branch, not a `feature` folder holding a
        # `velocity-gate`: the obvious rsplit("/") reports the branch as "velocity-gate", which is
        # the name that then fails to match anything the operator types or Bitbucket shows.
        ref_name = textio.norm_path(head.split(":", 1)[1].strip())
        branch = ref_name[len("refs/heads/"):] if ref_name.startswith("refs/heads/") else ref_name
        ref = _git_ref(repo_path)
        if ref:                       # a packed ref leaves the branch name, which is the useful half
            try:
                sha = _read(repo_path, ref).strip()[:40]
            except (OSError, ValueError):
                sha = ""
    else:
        branch, sha = "(detached)", head[:40]
    if mtime:
        when = time.strftime("%Y-%m-%d", time.localtime(mtime))
    text = "\n".join(x for x in (f"branch {branch}" if branch else "",
                                 f"commit {sha[:12]}" if sha else "",
                                 f"last commit {when}" if when else "") if x)
    return _Doc("git", GIT_HEAD, branch or "(no branch)", text,
                {"branch": branch, "commit": sha[:12], "last_commit": when}, mtime, size)


# -------------------------------------------------------------------------------- link facts

# Exactly the `AGENTS.md` facts and `state.json` fields `links.links_for()` reads, and nothing
# else. A tile renders in a browser, and handing it the whole fact block is how a Teradata
# hostname, a `\\share\dpm\runs` path or a TabularEditor install location ends up on a web page
# that the operator then screenshots into a ticket.
LINK_FACTS = ("jira_url", "jira_project", "jira_board_id", "report_id", "ds_id", "ws_id",
              "pbi_workspace", "bitbucket_url", "bitbucket_repo", "confluence_base",
              "confluence_space", "confluence_parent")
LINK_STATE = ("active_ticket", "branch", "pr_url", "confluence_url")


def _facts(repo_path: str) -> dict:
    """`config.project_facts` on the allow-listed `AGENTS.md`, with secret-looking keys dropped.

    The facts block is hand-edited prose. Nobody is *supposed* to write `jira_token:` there, and
    `config.save()` refuses exactly that key shape -- so the same refusal applies before a fact
    reaches the catalogue, rather than after someone copies the sqlite file to another machine.
    """
    try:
        agents = _inside(repo_path, FIXED["agents"])
    except ValueError:
        return {}          # a link out of the repository; `_build` refuses the same file by name
    facts = C.project_facts(agents)
    return {k: v for k, v in facts.items() if not C.looks_secret(k)}


# ------------------------------------------------------------------------------ the database


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS project(
    name TEXT PRIMARY KEY, path TEXT, branch TEXT, jira_project TEXT, board_id TEXT,
    pbip TEXT, workspace TEXT, facts TEXT, last_indexed TEXT);
CREATE TABLE IF NOT EXISTS doc(
    id INTEGER PRIMARY KEY, project TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
    title TEXT, mtime REAL, size INTEGER, text TEXT, data TEXT,
    UNIQUE(project, path));
CREATE INDEX IF NOT EXISTS doc_by_project ON doc(project);
"""


def _fts5_available(conn: sqlite3.Connection) -> bool:
    """Probe in the `temp` schema: a probe table in the catalogue itself would outlive the answer."""
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.fts_probe USING fts5(x)")
        conn.execute("DROP TABLE temp.fts_probe")
        return True
    except sqlite3.Error:
        return False


def _terms(query: str) -> list[str]:
    return [t for t in re.split(r"\s+", (query or "").strip()) if t]


def _match_expr(query: str) -> str:
    """Every term as a quoted FTS5 phrase.

    `ad-fleet where RDSD-22449` and `where velocity*` are both things an operator types, and both
    are FTS5 *syntax* -- a bare `-` or `(` raises `sqlite3.OperationalError: fts5: syntax error`
    out of a read-only search. Quoting turns the whole query back into words.
    """
    return " ".join('"' + t.replace('"', '""') + '"' for t in _terms(query))


class Catalogue:
    """`~/.agentdata/fleet/catalogue.sqlite`: one row per project, one row per allow-listed file.

    Opened read-write by `ad-fleet index` and read-only in effect by everything else. `self.fts`
    says whether FTS5 or the `LIKE` scan is answering, because "search found nothing" and "search
    is running on the fallback" look identical from a result set and only one of them is a bug.
    """

    def __init__(self, path: str | None = None, *, fts: bool | None = None):
        self.path = path or os.path.join(fleet_dir(), CATALOGUE)
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # `ad-fleet serve` answers SSE and search on different threads of one process; a connection
        # bound to its creating thread turns the first search into a ProgrammingError. The lock is
        # what actually makes that safe, not the flag.
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # The same trade `jira_cache` makes, for the same reason: this file is rebuildable by
        # definition -- `ad-fleet index --rebuild` re-reads every repository -- so fsyncing each
        # commit buys durability nobody needs and costs the indexer real time on Windows, where an
        # fsync goes through a corporate laptop's filter drivers. A torn catalogue is handled the
        # way a torn cache is: it is detected and rebuilt.
        for pragma in ("journal_mode = WAL", "synchronous = NORMAL"):
            try:
                self.conn.execute(f"PRAGMA {pragma}")
            except sqlite3.Error:
                pass
        self.conn.executescript(_SCHEMA_SQL)
        if fts is None:
            fts = not os.environ.get(NO_FTS_ENV) and _fts5_available(self.conn)
        self.fts = bool(fts)
        if self.fts:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(title, text)")
        self._check_mode()
        self.conn.commit()

    @classmethod
    def open(cls, path: str | None = None, *, fts: bool | None = None) -> "Catalogue":
        return cls(path, fts=fts)

    # ------------------------------------------------------------------ housekeeping

    def _meta(self, key: str, value: str | None = None) -> str:
        if value is not None:
            self.conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
            return value
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else ""

    def _check_mode(self) -> None:
        """A catalogue built on the LIKE fallback has an empty FTS table; searching it finds nothing.

        So the mode the file was built in is recorded, and a mismatch empties the docs rather than
        serving a silent zero-hit search on a machine that just gained (or lost) FTS5.
        """
        mode = "fts5" if self.fts else "like"
        stored = self._meta("mode")
        if str(self._meta("schema")) != str(SCHEMA) or (stored and stored != mode):
            self._wipe()
        self._meta("schema", str(SCHEMA))
        self._meta("mode", mode)

    def _wipe(self) -> None:
        self.conn.execute("DELETE FROM doc")
        self.conn.execute("DELETE FROM project")
        try:
            self.conn.execute("DELETE FROM doc_fts")
        except sqlite3.OperationalError:
            pass                      # built on the fallback: there is no FTS table to empty

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.commit()
            finally:
                self.conn.close()

    def stats(self) -> dict:
        with self._lock:
            projects = self.conn.execute("SELECT COUNT(*) n FROM project").fetchone()["n"]
            docs = self.conn.execute("SELECT COUNT(*) n FROM doc").fetchone()["n"]
            kinds = {r["kind"]: r["n"] for r in
                     self.conn.execute("SELECT kind, COUNT(*) n FROM doc GROUP BY kind "
                                       "ORDER BY kind")}
            last = self.conn.execute("SELECT MAX(last_indexed) m FROM project").fetchone()["m"]
        return {"path": textio.norm_path(self.path), "fts": self.fts, "projects": projects,
                "docs": docs, "kinds": kinds, "last_indexed": last or "",
                "bytes": os.path.getsize(self.path) if os.path.exists(self.path) else 0}

    # ---------------------------------------------------------------------- indexing

    def index(self, repos, rebuild: bool = False, on_event=None) -> dict:
        """Re-read what changed in each repo. Never raises because one repo is broken.

        Incremental on `(mtime, size)`, so a re-index of a dozen repos after one edit reads one
        file. `rebuild=True` re-reads everything, which is the answer whenever a doc's *shape*
        changed here rather than the file changing there.

        Returns `{projects, docs, skipped, elapsed, fts}` -- `docs` counts the docs actually read
        this run, which is what makes "I touched one file" observable -- plus `unchanged`,
        `removed`, `refused` and `problems` for the report `ad-fleet index` prints.
        """
        started = time.time()
        counts = {"projects": 0, "docs": 0, "skipped": 0, "unchanged": 0, "removed": 0}
        refused: list[dict] = []
        problems: list[dict] = []
        skipped: list[dict] = []

        def emit(payload: dict) -> None:
            if on_event:
                on_event(payload)

        for repo in _repo_list(repos):
            name, repo_path = _repo_name(repo), _repo_path(repo)
            if not os.path.isdir(repo_path):
                counts["skipped"] += 1
                entry = {"project": name, "path": textio.norm_path(repo_path),
                         "reason": "the directory is gone",
                         "hint": f"`ad-fleet repo remove {name}` if it moved for good"}
                skipped.append(entry)
                emit({"event": "skipped", **entry})
                continue
            try:
                got = self._index_repo(name, repo_path, rebuild, refused, problems, emit)
            except OSError as e:
                counts["skipped"] += 1
                entry = {"project": name, "path": textio.norm_path(repo_path),
                         "reason": f"unreadable: {e.__class__.__name__}",
                         "hint": "check the folder is not on a disconnected share, then re-run"}
                skipped.append(entry)
                emit({"event": "skipped", **entry})
                continue
            counts["projects"] += 1
            for key in ("docs", "unchanged", "removed"):
                counts[key] += got[key]
            emit({"event": "repo", "project": name, **got})

        with self._lock:
            self.conn.commit()
        out = {**counts, "elapsed": round(time.time() - started, 3), "fts": self.fts,
               "refused": refused, "problems": problems, "skipped_repos": skipped}
        emit({"event": "done", **out})
        return out

    def _index_repo(self, name, repo_path, rebuild, refused, problems, emit) -> dict:
        facts = _facts(repo_path)
        seen: set[str] = set()
        read = unchanged = 0
        branch = ""
        pbip: set[str] = set()

        with self._lock:
            known = {r["path"]: (r["mtime"], r["size"]) for r in
                     self.conn.execute("SELECT path, mtime, size FROM doc WHERE project=?", (name,))}

            for kind, rel in _candidates(repo_path):
                seen.add(rel)
                try:
                    stamp = _git_stamp(repo_path) if kind == "git" else _stat(repo_path, rel)
                except OSError:
                    continue                       # vanished between the listing and the stat
                if not rebuild and known.get(rel) == stamp:
                    unchanged += 1
                    if kind == "git":
                        branch = self._stored_branch(name) or branch
                    if kind.startswith("pbip_"):
                        pbip.add(rel.split("/")[2])
                    continue
                try:
                    doc = _build(repo_path, kind, rel)
                except (OSError, ValueError, KeyError, TypeError) as e:
                    entry = {"project": name, "path": rel, "kind": kind,
                             "reason": f"{e.__class__.__name__}: {e}"[:200],
                             "hint": f"fix {rel} in {textio.norm_path(repo_path)}; "
                                     "the rest of the repo is still indexed"}
                    problems.append(entry)
                    emit({"event": "problem", **entry})
                    self._delete(name, rel)
                    continue
                pattern = looks_like_a_credential(doc.text)
                if pattern:
                    entry = {"project": name, "path": rel, "kind": kind, "pattern": pattern,
                             "hint": f"move the {pattern} out of {rel} (keyring or pncli's own "
                                     "config), then re-run `ad-fleet index`"}
                    refused.append(entry)
                    emit({"event": "refused", **entry})
                    self._delete(name, rel)
                    continue
                self._put(name, doc)
                read += 1
                if kind == "git":
                    branch = (doc.data or {}).get("branch", "")
                if kind.startswith("pbip_"):
                    pbip.add(rel.split("/")[2])

            removed = 0
            for gone in sorted(set(known) - seen):
                self._delete(name, gone)
                removed += 1

            if not branch:
                branch = self._stored_branch(name)
            self.conn.execute(
                "INSERT INTO project(name, path, branch, jira_project, board_id, pbip, workspace, "
                "facts, last_indexed) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET path=excluded.path, branch=excluded.branch, "
                "jira_project=excluded.jira_project, board_id=excluded.board_id, "
                "pbip=excluded.pbip, workspace=excluded.workspace, facts=excluded.facts, "
                "last_indexed=excluded.last_indexed",
                (name, textio.norm_path(repo_path), branch, facts.get("jira_project", ""),
                 facts.get("jira_board_id", ""), ";".join(sorted(pbip)),
                 facts.get("pbi_workspace", ""), json.dumps(facts, sort_keys=True),
                 time.strftime("%Y-%m-%dT%H:%M:%S")))
        return {"docs": read, "unchanged": unchanged, "removed": removed}

    def _stored_branch(self, name: str) -> str:
        row = self.conn.execute("SELECT branch FROM project WHERE name=?", (name,)).fetchone()
        return row["branch"] if row and row["branch"] else ""

    def _delete(self, project: str, rel: str) -> None:
        row = self.conn.execute("SELECT id FROM doc WHERE project=? AND path=?",
                                (project, rel)).fetchone()
        if not row:
            return
        if self.fts:
            self.conn.execute("DELETE FROM doc_fts WHERE rowid=?", (row["id"],))
        self.conn.execute("DELETE FROM doc WHERE id=?", (row["id"],))

    def _put(self, project: str, doc: _Doc) -> None:
        self._delete(project, doc.rel)
        cur = self.conn.execute(
            "INSERT INTO doc(project, kind, path, title, mtime, size, text, data) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (project, doc.kind, doc.rel, doc.title, doc.mtime, doc.size, doc.text,
             json.dumps(doc.data, sort_keys=True) if doc.data is not None else None))
        if self.fts:
            self.conn.execute("INSERT INTO doc_fts(rowid, title, text) VALUES(?,?,?)",
                              (cur.lastrowid, doc.title, doc.text))

    # ------------------------------------------------------------------------ search

    def where(self, query: str, limit: int = 20) -> list[dict]:
        """Ranked projects for a query: `{project, kind, title, snippet, score}`, best first.

        One row per *project*, not per doc, because the question being asked is "which project owns
        Velocity" -- five hits from one repo's REPORT.md pushing the other four repos off the screen
        would answer a different question. Higher `score` is better in both search paths.
        """
        terms = _terms(query)
        if not terms:
            return []
        with self._lock:
            rows = self._search_fts(terms) if self.fts else self._search_like(terms)
        best: dict[str, dict] = {}
        for row in rows:
            current = best.get(row["project"])
            if current is None or row["score"] > current["score"]:
                best[row["project"]] = row
        ranked = sorted(best.values(), key=lambda r: (-r["score"], r["project"]))
        return ranked[:max(0, int(limit))]

    def _search_fts(self, terms: list[str]) -> list[dict]:
        expr = _match_expr(" ".join(terms))
        try:
            cur = self.conn.execute(
                "SELECT d.project, d.kind, d.title, d.text, d.data, "
                "       bm25(doc_fts, ?, 1.0) AS rank "
                "FROM doc_fts JOIN doc d ON d.id = doc_fts.rowid "
                "WHERE doc_fts MATCH ? ORDER BY rank LIMIT 500", (TITLE_WEIGHT, expr))
        except sqlite3.OperationalError as e:
            raise CatalogueError(f"the catalogue could not run that search ({e})",
                                 "try plain words; `ad-fleet where` is a word search, not a "
                                 "query language") from None
        # bm25 is negative and more negative is a better match; flip it so "higher is better" is
        # true of `score` whichever path produced it.
        return [{"project": r["project"], "kind": r["kind"], "title": r["title"],
                 "snippet": _snippet(r["kind"], r["text"], r["data"], terms),
                 "score": round(-float(r["rank"]), 4)} for r in cur]

    def _search_like(self, terms: list[str]) -> list[dict]:
        """The fallback when this interpreter's SQLite was built without FTS5.

        Every term must appear, in the title or the text -- the same implicit AND FTS5 applies --
        and the score is occurrences with the title weighted, so the top hit matches the FTS5 one
        on anything the operator would actually type.
        """
        where = " AND ".join(["(LOWER(title) LIKE ? OR LOWER(text) LIKE ?)"] * len(terms))
        args: list[str] = []
        for term in terms:
            like = f"%{term.lower()}%"
            args += [like, like]
        cur = self.conn.execute(
            f"SELECT project, kind, title, text, data FROM doc WHERE {where} LIMIT 500", args)
        out = []
        for r in cur:
            title, text = (r["title"] or "").lower(), (r["text"] or "").lower()
            score = sum(TITLE_WEIGHT * title.count(t.lower()) + text.count(t.lower())
                        for t in terms)
            out.append({"project": r["project"], "kind": r["kind"], "title": r["title"],
                        "snippet": _snippet(r["kind"], r["text"], r["data"], terms),
                        "score": round(float(score), 4)})
        return out

    # -------------------------------------------------------------------------- show

    def show(self, project: str) -> dict:
        """Everything the catalogue holds about one project, in the shape a tile renders.

        `friction` is every STOP the repo has written, newest first: a friction file has no
        "resolved" marker -- the only thing that says the human unblocked it is the repo's own
        `phase`, which is why `state` travels with it and the tile decides, not this module.
        """
        with self._lock:
            row = self.conn.execute("SELECT * FROM project WHERE name=?", (project,)).fetchone()
            if row is None:
                known = ", ".join(r["name"] for r in self.conn.execute(
                    "SELECT name FROM project ORDER BY name")) or "nothing indexed yet"
                raise CatalogueError(f"no project named {project!r} in the catalogue",
                                     f"indexed: {known}. Run `ad-fleet index` after registering it")
            docs = self.conn.execute(
                "SELECT kind, path, title, text, data FROM doc WHERE project=? ORDER BY path",
                (project,)).fetchall()

        facts = _json(row["facts"]) or {}
        state: dict = {}
        friction: list[dict] = []
        pbip: dict[str, dict] = {}
        for doc in docs:
            data = _json(doc["data"]) or {}
            if doc["kind"] == "state":
                state = data
            elif doc["kind"] == "friction":
                friction.append({"path": doc["path"], "title": doc["title"],
                                 "type": data.get("type", ""), "date": data.get("date", ""),
                                 "severity": data.get("severity", ""),
                                 "ticket": data.get("ticket", ""),
                                 "unblock": data.get("unblock", "")})
            elif doc["kind"].startswith("pbip_"):
                name = data.get("pbip") or doc["path"].split("/")[2]
                entry = pbip.setdefault(name, {"name": name, "model": "", "report": "",
                                               "lineage": "", "sources": []})
                if doc["kind"] == "pbip_meta":
                    entry["sources"] = data.get("sources", [])
                else:
                    entry[doc["kind"][5:]] = doc["title"]

        friction.sort(key=lambda f: (f["date"], f["path"]), reverse=True)
        links = {k: facts.get(k, "") for k in LINK_FACTS}
        links.update({k: (state.get(k) or "") for k in LINK_STATE})
        links["branch"] = links.get("branch") or row["branch"] or ""
        # `name` as well as `project`, because `links.links_for()` takes "anything with a .path
        # and a .name" and the dict this returns is what the tile slice hands it.
        return {"project": row["name"], "name": row["name"], "path": row["path"],
                "branch": row["branch"],
                "jira_project": row["jira_project"], "last_indexed": row["last_indexed"],
                "facts": facts, "state": state, "friction": friction,
                "pbip": [pbip[k] for k in sorted(pbip)], "links": links, "docs": len(docs)}


# ------------------------------------------------------------------------------- small helpers


def _json(raw):
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None


def _repo_list(repos) -> list:
    """A `Registry`, a list of `Repo`, or a list of dicts -- callers have all three to hand."""
    if hasattr(repos, "sorted"):
        return list(repos.sorted())
    return list(repos or [])


def _repo_name(repo) -> str:
    return str(repo["name"] if isinstance(repo, dict) else getattr(repo, "name", ""))


def _repo_path(repo) -> str:
    raw = repo["path"] if isinstance(repo, dict) else getattr(repo, "path", "")
    return os.path.abspath(C.expand(str(raw)))


def _snippet(kind: str, text: str, data, terms: list[str]) -> str:
    """One line: the matching sentence, with what the row cannot infer from it in front.

    A friction hit is the case that forced the lead. The matching line is a sentence out of "Where I
    got stuck", and the two things the operator needs before reading it -- was this ambiguity or a
    tool error, and was it today or in June -- are in the front matter, which the match is never in.
    """
    lead = ""
    if kind == "friction":
        meta = _json(data) if isinstance(data, str) else (data or {})
        meta = meta or {}
        bits = [x for x in (meta.get("type", ""), meta.get("date", "")) if x]
        lead = " · ".join(bits) + " — " if bits else ""
    lowered = [t.lower() for t in terms]
    chosen = ""
    for line in (text or "").splitlines():
        stripped = " ".join(line.split())
        if not stripped:
            continue
        if not chosen:
            chosen = stripped
        if any(t in stripped.lower() for t in lowered):
            chosen = stripped
            break
    room = max(20, SNIPPET_CHARS - len(lead))
    if len(chosen) > room:
        chosen = chosen[:room - 1].rstrip() + "…"
    return f"{lead}{chosen}".strip()
