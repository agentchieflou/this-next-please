"""The Command Center (docs/plan-command-center.md): every open ticket assigned to the operator that has
boundaries, seated at a free agent of its project, and all of them started with one press.

The operator, 2026-10-06: *"take all of the open Jira tickets assigned to a user and where applicable slate
them to begin work. Command center should only be possible for Jira tickets that have Acceptance Criteria /
Done state's so that an agent can have boundaries. It should never begin work on tickets that have
short/generic descriptions or no descriptions at all. In the command center option, all agents start at
the same time, but once that happens, they gate wherever they gate."* Their four decisions the same day:
criteria from a pinned field or the description; one ticket to each free checkout and the rest wait; only
*To Do* tickets are slated; forty words of description outside the criteria.

Four steps, each a function the desk and `ad-fleet command` share:

* **the slate** (`slate`): the board's query, with the description and the criteria field;
* **the gate** (`ready`): boundaries and a description that says what to do, or not slated -- a gate,
  never the pre-flight's courtesy, so a ticket it refuses has no tick and `run` refuses it if posted;
* **the seating** (`plan`): one ready ticket to one free checkout of its project, the rest waiting;
* **the start** (`run`): every ticked pair, back to back, each refusal its own row's.

Read-only towards Jira, like the board: nothing here transitions, comments or assigns.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time

from .. import config as C
from .. import textio
from . import board as B
from .registry import Registry, RegistryError, fleet_dir

CACHE = "command.json"
DEFAULT_MIN_WORDS = 40
#: Jira's status category keys: `new` is *To Do*, `indeterminate` *In Progress*.
TO_DO = "new"
IN_PROGRESS = "indeterminate"
#: Issue types that are not a unit of work an agent finishes.
NOT_WORK = ("epic",)
#: The custom fields criteria are kept in, by name, when the instance has one and none is pinned.
CRITERIA_FIELD_NAMES = ("acceptance criteria", "definition of done")
BASE_FIELDS = ("key", "summary", "status", "priority", "issuetype", "updated", "description")
PRIORITY = {"highest": 0, "blocker": 0, "critical": 0, "high": 1, "major": 1, "medium": 2, "minor": 3,
            "low": 3, "lowest": 4, "trivial": 4}
#: How long a discovered criteria field id is trusted before `/field` is asked again.
FIELDS_TTL_S = 24 * 3600


class CommandRefused(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = "refused"):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code


# ------------------------------------------------------------------------------- the text


_BLOCKS = {"paragraph", "heading", "bulletList", "orderedList", "taskList", "decisionList", "codeBlock",
           "blockquote", "panel", "rule", "table", "mediaSingle", "mediaGroup", "expand", "nestedExpand"}


def _inline(node) -> str:
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text") or "")
    if kind == "hardBreak":
        return "\n"
    if kind in ("mention", "emoji", "inlineCard", "status", "date"):
        attrs = node.get("attrs") or {}
        return str(attrs.get("text") or attrs.get("shortName") or attrs.get("url") or "")
    return "".join(_inline(c) for c in node.get("content") or [])


def adf_text(doc) -> str:
    """Atlassian Document Format (Cloud's descriptions and rich-text fields) as plain text, a line a block:
    a heading as `# text`, a list item as `- text` (`1. text` in an ordered list, `- [ ] text` a task), code
    as its own lines. Enough to find criteria and count words; nothing is rendered."""
    lines: list[str] = []

    def item_parts(item) -> tuple[str, list]:
        content = item.get("content") or []
        if item.get("type") in ("taskItem", "decisionItem") or not any(
                isinstance(c, dict) and c.get("type") in _BLOCKS for c in content):
            return "".join(_inline(c) for c in content).replace("\n", " ").strip(), []
        head = ""
        if content and isinstance(content[0], dict) and content[0].get("type") == "paragraph":
            head = _inline(content[0]).replace("\n", " ").strip()
            content = content[1:]
        return head, content

    def walk(node, depth: int = 0) -> None:
        if not isinstance(node, dict):
            return
        kind = node.get("type")
        content = node.get("content") or []
        if kind == "heading":
            lines.append("# " + "".join(_inline(c) for c in content).strip())
        elif kind == "paragraph":
            lines.extend("".join(_inline(c) for c in content).split("\n"))
        elif kind == "codeBlock":
            lines.extend("".join(_inline(c) for c in content).split("\n"))
        elif kind in ("bulletList", "orderedList", "taskList", "decisionList"):
            for i, item in enumerate(content, 1):
                if not isinstance(item, dict):
                    continue
                if kind == "orderedList":
                    mark = f"{i}. "
                elif kind == "taskList":
                    mark = "- [x] " if (item.get("attrs") or {}).get("state") == "DONE" else "- [ ] "
                else:
                    mark = "- "
                head, rest = item_parts(item)
                lines.append("  " * depth + mark + head)
                for sub in rest:
                    walk(sub, depth + 1)
        elif kind == "rule":
            lines.append("")
        else:
            for c in content:
                walk(c, depth)

    walk(doc)
    return "\n".join(lines).strip()


_WIKI_HEADING = re.compile(r"^\s*h[1-6]\.\s+(.*)$", re.I)
_WIKI_LIST = re.compile(r"^\s*([*#]+)\s+(\S.*)$")


def plain_text(value) -> str:
    """A description or a field's value, whatever shape Jira sent it in: ADF (Cloud) to text, wiki markup
    (Data Center) with its headings (`h3.`) as `# ` and its bullets (`*`, `**`) and numbered items (`#`) as
    `- `, a list of values a line each. `##` and deeper read as a pasted Markdown heading: in a ticket that
    is likelier than a numbered list nested twice."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return adf_text(value) if value.get("type") == "doc" else str(value.get("value") or value.get("name") or "")
    if isinstance(value, list):
        return "\n".join(plain_text(v) for v in value if v is not None).strip()
    lines = []
    for line in str(value).replace("\r\n", "\n").split("\n"):
        m = _WIKI_HEADING.match(line)
        if m:
            lines.append("# " + m.group(1).strip())
            continue
        m = _WIKI_LIST.match(line)
        if m and set(m.group(1)) == {"*"}:
            lines.append("  " * (len(m.group(1)) - 1) + "- " + m.group(2))
            continue
        if m and m.group(1) == "#":
            lines.append("- " + m.group(2))
            continue
        if m:
            lines.append("# " + m.group(2))
            continue
        lines.append(line)
    return "\n".join(lines).strip()


# ------------------------------------------------------------------------------- the gate


_LABEL = r"(acceptance\s+criteria|a\.?\s?c\.?|definition\s+of\s+done|d\.?o\.?d\.?|done\s+when|success\s+criteria)"
#: A line that opens the criteria: `Acceptance Criteria`, `## AC`, `*Definition of Done:*`, `AC: 1) x 2) y`.
CRITERIA_HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?[*_]{0,2}\s*" + _LABEL + r"\s*[*_]{0,2}\s*(?::\s*(.*))?$", re.I)
#: Any other heading: where a criteria section ends.
HEADING = re.compile(r"^\s*(?:#{1,6}\s+\S|[*_]{2}[^*_]+[*_]{2}\s*:?\s*$)")
LIST_ITEM = re.compile(r"^\s*(?:[-*•+]|\d+[.)]|\(?[a-z]\))\s+(?:\[[ xX]?\]\s*)?(\S.*)$")
GHERKIN = re.compile(r"^\s*(?:[-*•+]\s*|\d+[.)]\s*)?(given|when|then|and|but)\b", re.I)
INLINE_SPLIT = re.compile(r"\s*(?:;|\(\d+\)|\b\d+[.)])\s*")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
PLACEHOLDER = re.compile(r"\b(?:tbd|tbc|todo|to be (?:decided|confirmed|defined)|see title|see summary|as discussed|"
                         r"per (?:our )?(?:conversation|discussion|call|meeting)|details to follow|more to come|"
                         r"n/a|wip|placeholder|lorem ipsum|fill (?:this )?in)\b", re.I)


def _words(text: str) -> list[str]:
    return WORD.findall(text or "")


def criteria(description: str, field: str = "") -> dict:
    """The ticket's acceptance criteria, and where they were found: `{items, source, span}`.

    The pinned field first (`source: field`), when it holds anything: its list items, or its lines. Then a
    section of the description under a criteria heading -- *Acceptance Criteria*, *AC*, *Definition of
    Done*, *Done when*, *Success criteria* -- every line under it until the next heading (`source:
    section`), or its inline list (`AC: 1) x 2) y`). Then Given/When/Then anywhere: each *Then* is one
    (`source: gherkin`). Two bullets that merely sit in a description are not criteria. `span` is the
    description's lines the criteria took, which the word count leaves out."""
    field_text = (field or "").strip()
    if field_text:
        lines = [ln.strip() for ln in field_text.split("\n") if ln.strip()]
        items = [m.group(1) for m in (LIST_ITEM.match(ln) for ln in lines) if m] or lines
        items = [i for i in items if _words(i)]
        if items:
            return {"items": items, "source": "field", "span": []}
    lines = (description or "").split("\n")
    for i, line in enumerate(lines):
        m = CRITERIA_HEADING.match(line)
        if not m:
            continue
        items, span = [], [i]
        inline = (m.group(2) or "").strip()
        if inline:
            items.extend(p for p in INLINE_SPLIT.split(inline) if _words(p))
        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if HEADING.match(nxt) or CRITERIA_HEADING.match(nxt):
                break
            span.append(j)
            text = nxt.strip()
            if not text:
                continue
            got = LIST_ITEM.match(nxt)
            items.append(got.group(1) if got else text)
        items = [it for it in items if _words(it)]
        if items:
            return {"items": items, "source": "section", "span": span}
    then = [i for i, line in enumerate(lines) if GHERKIN.match(line) and GHERKIN.match(line).group(1).lower() == "then"]
    if then:
        span = [i for i, line in enumerate(lines) if GHERKIN.match(line)]
        return {"items": [lines[i].strip() for i in then], "source": "gherkin", "span": span}
    return {"items": [], "source": "", "span": []}


def ready(ticket: dict, *, min_words: int = DEFAULT_MIN_WORDS) -> dict:
    """Has this ticket boundaries, and does its description say what to do?

    `{ready, criteria, source, words, reasons}`: ready only when it has at least one criterion and at
    least `min_words` words outside them that are not placeholders, and the description is not empty, the
    summary over again, or a template's headings with nothing under them. Every reason that failed is a
    sentence the row prints."""
    description = ticket.get("description") or ""
    found = criteria(description, ticket.get("criteria") or "")
    lines = description.split("\n")
    outside = [ln for i, ln in enumerate(lines) if i not in set(found["span"])]
    body = [ln for ln in outside if not HEADING.match(ln) and not CRITERIA_HEADING.match(ln)]
    words = _words("\n".join(body))
    placeholders = PLACEHOLDER.findall("\n".join(body))
    counted = max(0, len(words) - sum(len(_words(p)) for p in placeholders))
    summary = {w.lower() for w in _words(ticket.get("summary") or "")}
    reasons = []
    if not found["items"]:
        reasons.append("no acceptance criteria: the agent would have to invent what done means")
    if not description.strip():
        reasons.append("no description: there is nothing for the agent to read")
    elif words and {w.lower() for w in words} <= summary:
        reasons.append("the description is the summary over again")
    elif counted < min_words:
        headings = sum(1 for ln in outside if HEADING.match(ln))
        if headings >= 2 and counted < min_words:
            reasons.append(f"a template's headings with {counted} words under them")
        elif placeholders:
            reasons.append(f"{counted} words of description once {placeholders[0]!r} and its like are left out "
                           f"(it needs {min_words})")
        else:
            reasons.append(f"{counted} words of description outside the criteria (it needs {min_words})")
    return {"ready": not reasons, "criteria": found["items"], "source": found["source"], "words": counted,
            "reasons": reasons}


# ------------------------------------------------------------------------------- the slate


def settings(cfg: dict | None = None) -> dict:
    cfg = C.load() if cfg is None else cfg
    try:
        min_words = max(0, int(C.get(cfg, "fleet.command.min_words", DEFAULT_MIN_WORDS)))
    except (TypeError, ValueError):
        min_words = DEFAULT_MIN_WORDS
    field = C.get(cfg, "fleet.command.criteria_field")
    pinned = [f.strip() for f in str(field).split(",") if f.strip()] if field else []
    return {"min_words": min_words, "criteria_fields": pinned, **B.settings(cfg)}


def cache_path() -> str:
    return os.path.join(fleet_dir(), CACHE)


def _read_cache() -> dict:
    try:
        return json.loads(textio.read_text(cache_path()))
    except (OSError, ValueError):
        return {}


def _write_cache(payload: dict) -> None:
    os.makedirs(fleet_dir(), exist_ok=True)
    textio.write_text(cache_path(), json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _client():
    from .. import cli_jira

    try:
        _cfg, client, _me = cli_jira._client()
    except Exception as e:                    # noqa: BLE001 - any credential or flavour failure
        raise CommandRefused(f"Jira is not reachable: {str(e)[:200]}",
                             "`ad-jira whoami` checks the token and the flavour; the Command Center uses the "
                             "same one pncli stores", code="jira_unreachable") from None
    return client


def criteria_field_ids(client, s: dict, cached: dict, now: float) -> list[str]:
    """The criteria field's ids: the pinned ones (`fleet.command.criteria_field`, ids or names), or, when
    none is pinned, whichever of the instance's fields is called *Acceptance Criteria* or *Definition of
    Done*, asked of `/field` once a day. `[]` when the instance has none: then the description alone."""
    wanted = s["criteria_fields"]
    known = cached.get("fields") or {}
    if (known.get("at") or 0) > now - FIELDS_TTL_S and known.get("pinned") == wanted:
        return list(known.get("ids") or [])
    try:
        listing = client.fields() if hasattr(client, "fields") else []
    except Exception:                         # noqa: BLE001 - no field list is no custom field, not a failure
        listing = []
    by_name = {str(f.get("name") or "").strip().lower(): str(f.get("id") or "") for f in listing or []}
    if wanted:
        ids = [w if w.startswith("customfield_") else by_name.get(w.lower(), "") for w in wanted]
    else:
        ids = [by_name[n] for n in CRITERIA_FIELD_NAMES if by_name.get(n)]
    ids = [i for i in ids if i]
    cached["fields"] = {"at": now, "pinned": wanted, "ids": ids}
    return ids


def slate(*, cfg: dict | None = None, client=None, force: bool = False, now: float | None = None) -> dict:
    """The operator's open tickets with their descriptions and criteria, from the board's query (`fleet.jql`),
    cached for the board's time (`fleet.board_ttl`) under its own key: the query and the fields."""
    s = settings(cfg)
    now = time.time() if now is None else now
    cached = _read_cache()
    if (not force and cached.get("rows") is not None and cached.get("jql") == s["jql"]
            and cached.get("pinned") == s["criteria_fields"]
            and now - float(cached.get("fetched_at") or 0) < s["ttl"]):
        return {"rows": cached.get("rows") or [], "cached": True, "age_s": int(now - float(cached.get("fetched_at") or 0)),
                "jql": s["jql"], "criteria_fields": (cached.get("fields") or {}).get("ids") or []}
    client = client or _client()
    ids = criteria_field_ids(client, s, cached, now)
    try:
        issues = client.search(s["jql"], list(BASE_FIELDS) + ids)
    except Exception as e:                    # noqa: BLE001 - Jira's own words are the hint
        raise CommandRefused("the Command Center's query failed", str(e)[:300], code="jira_failed") from None
    rows = []
    for issue, row in zip(issues or [], B.normalize(issues or [])):
        f = issue.get("fields") or {}
        row["description"] = plain_text(f.get("description"))
        row["criteria"] = "\n".join(t for t in (plain_text(f.get(i)) for i in ids) if t)
        rows.append(row)
    _write_cache({"jql": s["jql"], "pinned": s["criteria_fields"], "fetched_at": now, "rows": rows,
                  "fields": cached.get("fields") or {}})
    return {"rows": rows, "cached": False, "age_s": 0, "jql": s["jql"], "criteria_fields": ids}


# ------------------------------------------------------------------------------- the seating


def seats(registry: Registry, cfg: dict | None = None) -> dict:
    """Every registered checkout: `{name: {project, free, why, ticket}}`. Free is what `supervisor.start`
    would accept for a new ticket without `--force`: no live agent, no session the fleet did not start,
    no other ticket mid-way, and -- the Command Center's own -- not over its budget."""
    from . import adopt as A
    from . import lifecycle, supervisor
    from . import overrides as OV
    from .agentstate import TERMINAL_PHASES

    out = {}
    for repo in registry.sorted():
        name = repo.name
        seat = {"project": (repo.jira_project or "").upper(), "free": False, "why": "", "ticket": ""}
        try:
            state = repo.state() or {}
        except OSError:
            state = {}
        active, phase = str(state.get("active_ticket") or ""), str(state.get("phase") or "")
        seat["ticket"] = active
        lock = supervisor.live(name)
        if lock:
            seat["why"] = ("your own chat is open there" if lock.get("external")
                           else f"running {lock.get('ticket') or 'a prompt'}")
        elif active and phase not in TERMINAL_PHASES and phase not in ("", "idle"):
            seat["why"] = f"{active} is in phase {phase}"
        else:
            try:
                seen = A.outside(name, registry=registry, fresh_listing=False, wait=False)
            except Exception:                 # noqa: BLE001 - a listing that cannot be read names nobody
                seen = {}
            over, used, budget = lifecycle.over_budget(name, cfg=OV.for_agent(cfg, name))
            if seen.get("pid"):
                seat["why"] = "a session the fleet did not start is working there"
            elif over:
                seat["why"] = f"over its budget ({used:g} of {budget:g})"
            else:
                seat["free"] = True
        out[name] = seat
    return out


def _order(row: dict) -> int:
    """Jira's priority, highest first; a stable sort keeps the query's own order (most recently updated
    first, by default) within one priority."""
    return PRIORITY.get(str(row.get("priority") or "").lower(), 5)


def _plan_id(rows: list[dict]) -> str:
    stable = [[r["key"], r["verdict"], r.get("repo", ""), bool(r.get("ticked"))] for r in rows]
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def plan(*, cfg: dict | None = None, client=None, registry: Registry | None = None, force: bool = False,
         now: float | None = None) -> dict:
    """The preview: every open ticket on the slate with its verdict and, for a ready one, its seat.

    Verdicts: `ready` (ticked, seated), `not_ready` (the gate's reasons), `waiting` (ready, but every
    checkout of its project is taken: a later press), `held` (another checkout already has it), `in_progress`
    (In Progress in Jira: a person may hold it), `not_work` (an epic), `no_checkout` (no registered checkout
    declares its project). Ready tickets are seated in Jira's priority order, then its own (most recently
    updated first), one to a checkout."""
    cfg = C.load() if cfg is None else cfg
    s = settings(cfg)
    got = slate(cfg=cfg, client=client, force=force, now=now)
    try:
        reg = registry or Registry()
    except RegistryError:
        raise CommandRefused("the registry cannot be read", "`ad-fleet repo list`", code="registry") from None
    table = seats(reg, cfg)
    held = {seat["ticket"].upper(): name for name, seat in table.items() if seat["ticket"]}
    taken: set[str] = set()
    rows = []
    for row in sorted(got["rows"], key=_order):
        key = str(row.get("key") or "").upper()
        verdict = ready(row, min_words=s["min_words"])
        out = {k: row.get(k, "") for k in ("key", "summary", "status", "category", "type", "priority", "project")}
        out.update({"criteria": verdict["criteria"][:6], "criteria_n": len(verdict["criteria"]),
                    "source": verdict["source"], "words": verdict["words"], "reasons": list(verdict["reasons"]),
                    "repo": "", "repos": [], "ticked": False})
        mine = [n for n, seat in table.items() if seat["project"] and seat["project"] == out["project"]]
        if str(row.get("type") or "").lower() in NOT_WORK:
            out["verdict"] = "not_work"
            out["reasons"] = ["an epic is not a unit of work an agent finishes"] + out["reasons"]
        elif key in held:
            out.update(verdict="held", repo=held[key])
            out["reasons"] = [f"already with {held[key]}"]
        elif row.get("category") == IN_PROGRESS:
            out["verdict"] = "in_progress"
            out["reasons"] = ["in progress in Jira: a person may hold it, so it is not slated"] + out["reasons"]
        elif row.get("category") != TO_DO:
            out["verdict"] = "not_work"
            out["reasons"] = [f"its status is {row.get('status') or 'unknown'}, not To Do"]
        elif not verdict["ready"]:
            out["verdict"] = "not_ready"
        elif not mine:
            out["verdict"] = "no_checkout"
            out["reasons"] = [f"no registered checkout declares jira_project {out['project'] or '?'}"]
        else:
            free = [n for n in mine if table[n]["free"] and n not in taken]
            if free:
                out.update(verdict="ready", repo=free[0], repos=free, ticked=True)
                taken.add(free[0])
            else:
                out["verdict"] = "waiting"
                out["reasons"] = [f"waiting for a desk: every {out['project']} checkout has a ticket ("
                                  + "; ".join(f"{n}: {table[n]['why'] or 'seated above'}" for n in mine) + ")"]
        rows.append(out)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    ticked = sum(1 for r in rows if r["ticked"])
    return {"plan_id": _plan_id(rows), "rows": rows, "counts": counts, "ticked": ticked, "premium_turns": ticked,
            "jql": got["jql"], "cached": got["cached"], "age_s": got["age_s"], "min_words": s["min_words"],
            "criteria_fields": got.get("criteria_fields") or []}


def run(plan_id: str, start: list, *, cfg: dict | None = None, client=None,
        registry: Registry | None = None, now: float | None = None) -> dict:
    """Start every `{key, repo}` in `start`, back to back, after judging them again.

    Refused whole when nothing was previewed (`preview_first`), nothing is ticked (`nothing_ticked`) or the
    plan has moved since the preview (`plan_changed`: its id is a hash of every row's ticket, verdict and
    seat). Each pair then stands alone: a ticket the gate refuses (`not_ready`), a seat that is not one of
    its free checkouts or is taken twice (`seat_taken`), or any refusal of `supervisor.start` by its own
    code, is that row's, and the others start regardless."""
    from . import supervisor

    if not plan_id:
        raise CommandRefused("preview first", "`ad-fleet command --dry-run`, then `--confirm <plan_id>`",
                             code="preview_first")
    pairs = [(str(p.get("key") or "").upper(), str(p.get("repo") or "")) for p in start or [] if isinstance(p, dict)]
    if not pairs:
        raise CommandRefused("nothing is ticked", "tick the tickets to start", code="nothing_ticked")
    cfg = C.load() if cfg is None else cfg
    now_plan = plan(cfg=cfg, client=client, registry=registry, now=now)
    if now_plan["plan_id"] != plan_id:
        raise CommandRefused("the plan changed since the preview", "look at it again before starting",
                             code="plan_changed")
    rows = {r["key"]: r for r in now_plan["rows"]}
    board_rows = [{"key": r["key"], "summary": r["summary"], "status": r["status"], "category": r["category"]}
                  for r in now_plan["rows"]]
    reg = registry or Registry()
    used: set[str] = set()
    out = []
    for key, repo in pairs:
        row = rows.get(key)
        if row is None or row["verdict"] != "ready":
            out.append({"key": key, "repo": repo, "done": "skipped", "code": "not_ready",
                        "why": "; ".join((row or {}).get("reasons") or ["not on the slate"])})
            continue
        if repo not in row["repos"] or repo in used:
            out.append({"key": key, "repo": repo, "done": "skipped", "code": "seat_taken",
                        "why": f"{repo or 'no checkout'} is not a free {row['project']} checkout for it"})
            continue
        used.add(repo)
        try:
            lock = supervisor.start(repo, key=key, cfg=cfg, registry=reg, board_rows=board_rows,
                                    summary=row["summary"])
        except supervisor.SupervisorError as e:
            out.append({"key": key, "repo": repo, "done": "refused", "code": getattr(e, "code", "") or "refused",
                        "why": e.msg})
            continue
        out.append({"key": key, "repo": repo, "done": "started", "pid": lock.get("pid", 0)})
    return {"plan_id": plan_id, "rows": out, "started": sum(1 for r in out if r["done"] == "started")}
