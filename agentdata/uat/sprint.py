"""Committed vs completed story points for a sprint, reconstructed from the Jira changelog by BACKWARD replay.

A changelog holds transitions, not states. Start from each field's CURRENT value and undo every change newer than
the instant of interest (`value_at`). That is correct even when a field was set at issue creation without any
changelog entry — the classic source of wrong sprint numbers. All timestamps are tz-aware UTC; the boundary is
half-open (an event at exactly the sprint start counts as before the start).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from ..connectors.jira_api import parse_ts

_SPRINT_ID = re.compile(r"\bid=(\d+)")


@dataclass(order=True)
class Change:
    created: datetime
    changelog_id: int
    field_id: str = field(compare=False)
    from_id: str | None = field(default=None, compare=False)
    from_str: str | None = field(default=None, compare=False)
    to_id: str | None = field(default=None, compare=False)
    to_str: str | None = field(default=None, compare=False)


@dataclass
class IssueState:
    key: str
    issue_id: str
    is_subtask: bool
    created: datetime
    sprint_ids: set[int]          # CURRENT
    points: float | None          # CURRENT
    status_id: str | None         # CURRENT
    status_name: str | None
    changes: list[Change] = field(default_factory=list)


@dataclass
class SprintInfo:
    id: int
    name: str
    state: str
    start: datetime | None
    end: datetime | None
    complete: datetime | None
    board_id: int | None = None

    @classmethod
    def from_json(cls, j: dict) -> "SprintInfo":
        def ts(k):
            return parse_ts(j[k]) if j.get(k) else None
        return cls(int(j["id"]), str(j.get("name") or j["id"]), str(j.get("state") or ""), ts("startDate"), ts("endDate"),
                   ts("completeDate"), j.get("originBoardId"))


# ---------- decoding ----------
def parse_sprint_ids(v: Any) -> set[int]:
    """'12, 15' | None | [12, 15] | [{'id': 12}] | ['...Sprint@1a[id=12,rapidViewId=3,...]']."""
    if v in (None, ""):
        return set()
    if isinstance(v, (int, float)):
        return {int(v)}
    if isinstance(v, str):
        ids = {int(m) for m in _SPRINT_ID.findall(v)}
        if ids:
            return ids
        return {int(x) for x in v.split(",") if x.strip().isdigit()}
    out: set[int] = set()
    for item in v:
        if isinstance(item, dict) and item.get("id") is not None:
            out.add(int(item["id"]))
        else:
            out |= parse_sprint_ids(item)
    return out


def parse_points(v: Any) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def value_at(current: Any, changes: Iterable[Change], t: datetime, decode: Callable[[Change], Any]) -> Any:
    """Undo changes newer than t (created > t), newest first. Event exactly at t is kept (half-open boundary)."""
    v = current
    for c in sorted(changes, reverse=True):
        if c.created > t:
            v = decode(c)
        else:
            break
    return v


def _changes(i: IssueState, field_ids: Iterable[str]) -> list[Change]:
    wanted = {str(f) for f in field_ids}
    return [c for c in i.changes if str(c.field_id) in wanted]


def sprints_at(i: IssueState, sprint_field: str, t: datetime) -> set[int]:
    return value_at(set(i.sprint_ids), _changes(i, [sprint_field]), t, lambda c: parse_sprint_ids(c.from_id if c.from_id not in (None, "") else c.from_str))


def points_at(i: IssueState, points_fields: list[str], t: datetime) -> float | None:
    return value_at(i.points, _changes(i, points_fields), t, lambda c: parse_points(c.from_str if c.from_str not in (None, "") else c.from_id))


def status_id_at(i: IssueState, t: datetime) -> str | None:
    return value_at(i.status_id, _changes(i, ["status"]), t, lambda c: c.from_id if c.from_id not in (None, "") else (c.from_str or "").lower())


def category(status_cat: dict[str, str], status_id: str | None, status_name: str | None = None) -> str | None:
    if status_id is not None and str(status_id) in status_cat:
        return status_cat[str(status_id)]
    if status_name and status_name.lower() in status_cat:
        return status_cat[status_name.lower()]
    return None


def done_at(i: IssueState, t_close: datetime, status_cat: dict[str, str]) -> datetime | None:
    """Instant of the LAST transition into a done category at or before t_close, provided the issue is still done
    at t_close. No status change at all + currently done -> the issue was created done (its created time)."""
    sc = sorted(c for c in _changes(i, ["status"]) if c.created <= t_close)
    if not sc:
        return i.created if category(status_cat, i.status_id, i.status_name) == "done" and i.created <= t_close else None
    last = sc[-1]
    to_cat = category(status_cat, last.to_id, last.to_str)
    if to_cat != "done":
        return None
    # walk back to the first change of the final done streak
    when = last.created
    for c in reversed(sc[:-1]):
        if category(status_cat, c.to_id, c.to_str) == "done":
            when = c.created
        else:
            break
    return when


def build_issue_state(issue: dict, rows: Iterable[dict], sprint_field: str, points_fields: list[str]) -> IssueState:
    """From a Jira issue JSON (fields: created, issuetype, status, sprint field, points fields) and changelog rows."""
    f = issue.get("fields") or {}
    points = None
    for pf in points_fields:
        points = parse_points(f.get(pf))
        if points is not None:
            break
    st = f.get("status") or {}
    changes = []
    for r in rows:
        if r.get("key") != issue.get("key") or r.get("created_utc") in (None, ""):
            continue
        cid = r.get("changelog_id")
        changes.append(Change(parse_ts(r["created_utc"]), int(cid) if str(cid).isdigit() else 0, str(r.get("field_id") or r.get("field")),
                              r.get("from_id"), r.get("from_str"), r.get("to_id"), r.get("to_str")))
    created = parse_ts(f["created"]) if f.get("created") else datetime.fromtimestamp(0, tz=timezone.utc)
    return IssueState(issue.get("key"), str(issue.get("id") or ""), bool((f.get("issuetype") or {}).get("subtask", False)),
                      created, parse_sprint_ids(f.get(sprint_field)), points, str(st.get("id")) if st.get("id") is not None else None,
                      st.get("name"), sorted(changes))


# ---------- replay ----------
def replay(issues: Iterable[IssueState], sprint: SprintInfo, status_cat: dict[str, str], sprint_field: str,
           points_fields: list[str], *, points_at_mode: str = "close", include_subtasks: bool = False,
           now: datetime | None = None) -> tuple[list[dict], dict]:
    if sprint.start is None:
        raise ValueError(f"sprint {sprint.id} has not started (state={sprint.state})")
    t_start = sprint.start
    provisional = False
    if sprint.complete is not None:
        t_close = sprint.complete
    elif sprint.state.lower() == "active" or sprint.end is None:
        t_close, provisional = (now or datetime.now(timezone.utc)), True
    else:
        t_close = sprint.end
    S = sprint.id
    rows: list[dict] = []
    for i in issues:
        sp_start, sp_close = sprints_at(i, sprint_field, t_start), sprints_at(i, sprint_field, t_close)
        in_start, in_close = S in sp_start, S in sp_close
        if not (in_start or in_close or any(S in parse_sprint_ids(c.to_str if c.to_id in (None, "") else c.to_id) or S in parse_sprint_ids(c.from_str if c.from_id in (None, "") else c.from_id)
                                            for c in _changes(i, [sprint_field]) if t_start < c.created <= t_close)):
            continue  # never touched this sprint
        p_start, p_close = points_at(i, points_fields, t_start), points_at(i, points_fields, t_close)
        st_start, st_close = status_id_at(i, t_start), status_id_at(i, t_close)
        cat_close = category(status_cat, st_close, i.status_name if st_close == i.status_id else None)
        d_at = done_at(i, t_close, status_cat)
        subtask_excluded = i.is_subtask and not include_subtasks
        committed = in_start and not subtask_excluded
        completed = (in_close and cat_close == "done" and d_at is not None and t_start <= d_at <= t_close
                     and S in sprints_at(i, sprint_field, d_at) and not subtask_excluded)
        reopened = False
        prev = None
        for c in sorted(_changes(i, ["status"])):
            if t_start < c.created <= t_close:
                if prev == "done" and category(status_cat, c.to_id, c.to_str) != "done":
                    reopened = True
            prev = category(status_cat, c.to_id, c.to_str)
        rows.append({
            "key": i.key, "is_subtask": i.is_subtask, "in_at_start": in_start, "in_at_close": in_close,
            "points_start": p_start, "points_close": p_close,
            "status_start": _name(status_cat, st_start), "status_close": _name(status_cat, st_close), "cat_close": cat_close or "",
            "done_at_utc": d_at.strftime("%Y-%m-%dT%H:%M:%SZ") if d_at else None,
            "committed": committed, "completed": completed,
            "completed_in_another_sprint": bool(in_close and cat_close == "done" and not completed and not subtask_excluded),
            "added_after_start": bool(not in_start and in_close), "punted": bool(in_start and not in_close),
            "re_estimated": p_start is not None and p_close is not None and p_start != p_close,
            "estimated_mid_sprint": p_start is None and p_close is not None,
            "carried_over": bool(in_start and (sp_start - {S})), "reopened": reopened,
        })
    credit = (lambda r: r["points_close"]) if points_at_mode == "close" else (lambda r: r["points_start"])
    summary = {
        "sprint_id": S, "sprint_name": sprint.name, "state": sprint.state,
        "start_utc": t_start.strftime("%Y-%m-%dT%H:%M:%SZ"), "close_utc": t_close.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "provisional": provisional, "points_at": points_at_mode,
        "committed_points": round(sum(r["points_start"] or 0 for r in rows if r["committed"]), 2),
        "completed_points": round(sum(credit(r) or 0 for r in rows if r["completed"]), 2),
        "committed_issues": sum(1 for r in rows if r["committed"]), "completed_issues": sum(1 for r in rows if r["completed"]),
        "added": sum(1 for r in rows if r["added_after_start"]), "punted": sum(1 for r in rows if r["punted"]),
        "re_estimated": sum(1 for r in rows if r["re_estimated"]), "estimated_mid_sprint": sum(1 for r in rows if r["estimated_mid_sprint"]),
        "carried_over": sum(1 for r in rows if r["carried_over"]), "reopened": sum(1 for r in rows if r["reopened"]),
        "completed_in_another_sprint": sum(1 for r in rows if r["completed_in_another_sprint"]),
        "subtasks_excluded": sum(1 for r in rows if r["is_subtask"]) if not include_subtasks else 0,
        "issues_scanned": len(rows),
    }
    return rows, summary


def _name(status_cat: dict[str, str], status_id: str | None) -> str:
    return "" if status_id is None else str(status_id)


def sprintreport_delta(report: dict, rows: list[dict], summary: dict) -> dict:
    """Compare Jira's (undocumented) Sprint Report with the replay. Informational only."""
    c = report.get("contents") or {}
    def keys(section):
        return {i.get("key") for i in (c.get(section) or []) if isinstance(i, dict)}
    rep_completed = keys("completedIssues")
    rep_punted = keys("puntedIssues")
    rep_added = set((c.get("issueKeysAddedDuringSprint") or {}).keys())
    our_completed = {r["key"] for r in rows if r["completed"]}
    our_punted = {r["key"] for r in rows if r["punted"]}
    our_added = {r["key"] for r in rows if r["added_after_start"]}
    def num(section):
        v = (c.get(section) or {}).get("value")
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    rep_pts = num("completedIssuesEstimateSum")
    return {"report_completed_points": rep_pts,
            "completed_points_delta": None if rep_pts is None else round(summary["completed_points"] - rep_pts, 2),
            "punted_delta": len(our_punted) - len(rep_punted), "added_delta": len(our_added) - len(rep_added),
            "keys_only_in_report": sorted(rep_completed - our_completed)[:20],
            "keys_only_in_replay": sorted(our_completed - rep_completed)[:20]}
