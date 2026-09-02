"""ad-jira: Jira REST reusing pncli's token. whoami · fields · statuses · sprints · changelog · sprint-replay.
Never shells out to pncli; the token is read from pncli's config file by key name at call time."""
from __future__ import annotations
import argparse
import sys
from . import config as C
from . import toon
from .connectors import jira_api as J
from .console import utf8_stdout
from .model import AgentTable
from .policy import error, render
from .uat import sprint as SP

CHANGELOG_COLUMNS = ["key", "changelog_id", "created_utc", "author", "field", "field_id", "field_type",
                     "from_id", "from_str", "to_id", "to_str"]


def _client(redetect: bool = False):
    cfg = C.load()
    creds = J.load_credentials(cfg)
    j, me = J.detect_flavor(creds, cfg, redetect=redetect)
    if redetect or not C.get(cfg, "verified.jira"):
        J.remember_flavor(cfg, j)
        C.save(cfg)
    return cfg, j, me


def _name_map(fields_json: list[dict]) -> dict:
    return {str(f.get("name") or "").lower(): f.get("id") for f in fields_json}


def cmd_whoami(a) -> int:
    cfg, j, me = _client(a.redetect)
    J.remember_flavor(cfg, j)
    C.save(cfg)
    rec = {"base_url": j.creds.base_url, "flavor": j.flavor.kind, "auth": j.flavor.auth, "api": j.flavor.api,
           "token_source": j.creds.source, "display_name": me.get("displayName"),
           "account": me.get("accountId") or me.get("name"), "email": me.get("emailAddress"), "timezone": me.get("timeZone")}
    print(render(AgentTable.from_records([rec], name="whoami", source="ad-jira whoami"), raw=a.raw))
    return 0


def cmd_fields(a) -> int:
    cfg, j, _ = _client()
    fj = j.fields()
    recs = []
    for f in fj:
        name = str(f.get("name") or "")
        if a.like and a.like.lower() not in name.lower():
            continue
        sch = f.get("schema") or {}
        recs.append({"id": f.get("id"), "name": name, "custom": bool(f.get("custom")), "type": sch.get("type"),
                     "custom_type": (sch.get("custom") or "").rsplit(":", 1)[-1] or None})
    extra = None
    if a.pin:
        pins = J.pin_fields(fj)
        C.put(cfg, "jira.fields.sprint", pins["sprint"])
        C.put(cfg, "jira.fields.story_points", pins["story_points"])
        C.save(cfg)
        extra = {"pinned_sprint": pins["sprint"] or "", "pinned_story_points": pins["story_points"]}
    print(render(AgentTable.from_records(recs, name="fields", source="ad-jira fields"), raw=a.raw, extra=extra))
    return 0


def cmd_statuses(a) -> int:
    _, j, _ = _client()
    recs = [{"id": s.get("id"), "name": s.get("name"), "category": (s.get("statusCategory") or {}).get("key")}
            for s in j.get(f"{j.api}/status") or []]
    print(render(AgentTable.from_records(recs, name="statuses", source="ad-jira statuses"), raw=a.raw))
    return 0


def cmd_sprints(a) -> int:
    _, j, _ = _client()
    recs = [{"id": s.get("id"), "name": s.get("name"), "state": s.get("state"), "start": s.get("startDate"),
             "end": s.get("endDate"), "complete": s.get("completeDate")} for s in j.board_sprints(a.board, a.state)]
    print(render(AgentTable.from_records(recs, name="sprints", source=f"ad-jira sprints --board {a.board}"), raw=a.raw))
    return 0


def _utc(s: str | None) -> str | None:
    return J.parse_ts(s).strftime("%Y-%m-%dT%H:%M:%SZ") if s else None


def cmd_changelog(a) -> int:
    _, j, _ = _client()
    keys = list(a.keys)
    if a.jql:
        keys += [i["key"] for i in j.search(a.jql, ["key"]) if i.get("key") not in keys]
    if not keys:
        print(error("no issue keys", "pass KEY... or --jql", "ad-jira"))
        return 2
    fj = j.fields()
    name_to_id = _name_map(fj)
    wanted = J.resolve_field_ids(a.fields.split(","), fj) if a.fields else None
    if a.no_bulk or j.flavor.kind != "cloud":
        rows = [r for k in keys for r in j.changelog(k, name_to_id)]
    else:
        rows = j.bulk_changelog(keys, wanted, name_to_id)
    if wanted:
        w = {str(x).lower() for x in wanted}
        rows = [r for r in rows if str(r.get("field_id") or "").lower() in w or str(r.get("field") or "").lower() in w]
    since, until = _utc(a.since), _utc(a.until)
    if since:
        rows = [r for r in rows if (r.get("created_utc") or "") >= since]
    if until:
        rows = [r for r in rows if (r.get("created_utc") or "") <= until]
    rows.sort(key=lambda r: (r.get("key") or "", r.get("created_utc") or "", r.get("changelog_id") or 0))
    src = "ad-jira changelog " + " ".join(keys[:3]) + (" …" if len(keys) > 3 else "")
    print(render(AgentTable.from_records(rows, name=a.name or "changelog", source=src, fields=CHANGELOG_COLUMNS), raw=a.raw))
    return 0


def _resolve_sprint(j: J.Jira, spec: str, board: int | None) -> dict:
    if spec.isdigit():
        return j.sprint(int(spec))
    if not board:
        raise J.JiraError(f"--sprint '{spec}' is a name; --board is required to resolve it", hint="ad-jira sprints --board <jira_board_id>")
    cands = j.board_sprints(board)
    exact = [s for s in cands if str(s.get("name", "")).lower() == spec.lower()]
    subs = [s for s in cands if spec.lower() in str(s.get("name", "")).lower()]
    hit = exact or subs
    if len(hit) != 1:
        names = ", ".join(f"{s.get('id')}={s.get('name')}" for s in (hit or cands)[:15])
        raise J.JiraError(f"sprint '{spec}' matched {len(hit)} sprints on board {board}", hint=f"use the id: {names}")
    return hit[0]


def cmd_sprint_replay(a) -> int:
    cfg, j, _ = _client()
    sj = _resolve_sprint(j, a.sprint, a.board)
    sprint = SP.SprintInfo.from_json(sj)
    board = a.board or sj.get("originBoardId")
    fj = j.fields()
    pins = J.pin_fields(fj)
    sprint_field = C.get(cfg, "jira.fields.sprint") or pins["sprint"]
    points_fields = list(C.get(cfg, "jira.fields.story_points") or pins["story_points"] or [])
    if not sprint_field or not points_fields:
        print(error("Sprint / Story Points field ids unknown", "run ad-jira fields --pin (or --like sprint / --like point)", "ad-jira"))
        return 2
    status_cat = j.statuses()
    fields = ["key", "issuetype", "created", "status", sprint_field, *points_fields]
    issues = {i["key"]: i for i in j.search(f"sprint = {sprint.id}", fields)}
    if a.jql:
        for i in j.search(a.jql, fields):
            issues.setdefault(i["key"], i)
    keys = list(issues)
    name_to_id = _name_map(fj)
    if j.flavor.kind == "cloud" and not a.no_bulk:
        rows_cl = j.bulk_changelog(keys, [sprint_field, "status", *points_fields], name_to_id,
                                   id_to_key={str(v.get("id")): k for k, v in issues.items()})
    else:
        rows_cl = [r for k in keys for r in j.changelog(k, name_to_id)]
    states = [SP.build_issue_state(issues[k], rows_cl, sprint_field, points_fields) for k in keys]
    try:
        rows, summary = SP.replay(states, sprint, status_cat, sprint_field, points_fields, points_at_mode=a.points_at,
                                  include_subtasks=a.include_subtasks, now=J.parse_ts(a.now) if a.now else None)
    except ValueError as e:
        print(error(str(e), "pick a started sprint (ad-jira sprints --board ... --state closed)", "ad-jira"))
        return 2
    out: dict = {"summary": summary}
    if a.compare_sprintreport:
        if not board:
            print(error("--compare-sprintreport needs --board", "pass --board <jira_board_id>", "ad-jira"))
            return 2
        out["sprintreport_delta"] = SP.sprintreport_delta(j.sprintreport(board, sprint.id), rows, summary)
    name = a.name or f"sprint_{sprint.id}"
    print(render(AgentTable.from_records(rows, name=name, source=f"ad-jira sprint-replay {sprint.id}"), raw=a.raw))
    print(toon.encode(out))
    return 0


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-jira", description="Jira REST via pncli's token: history the current-state search cannot give.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("whoami", help="detect Cloud/DC flavor and auth; caches it in config")
    p.add_argument("--redetect", action="store_true"); p.add_argument("--raw", action="store_true"); p.set_defaults(fn=cmd_whoami)
    p = sub.add_parser("fields", help="field name <-> id map; --pin stores Sprint / Story Points ids")
    p.add_argument("--like"); p.add_argument("--pin", action="store_true"); p.add_argument("--raw", action="store_true"); p.set_defaults(fn=cmd_fields)
    p = sub.add_parser("statuses", help="status id, name, category (done|indeterminate|new)")
    p.add_argument("--raw", action="store_true"); p.set_defaults(fn=cmd_statuses)
    p = sub.add_parser("sprints", help="sprints of a board")
    p.add_argument("--board", type=int, required=True); p.add_argument("--state", choices=["active", "closed", "future"])
    p.add_argument("--raw", action="store_true"); p.set_defaults(fn=cmd_sprints)
    p = sub.add_parser("changelog", help="field history rows for issues")
    p.add_argument("keys", nargs="*", metavar="KEY"); p.add_argument("--jql"); p.add_argument("--fields", help='e.g. status,Sprint,"Story Points"')
    p.add_argument("--since"); p.add_argument("--until"); p.add_argument("--no-bulk", action="store_true")
    p.add_argument("--name"); p.add_argument("--raw", action="store_true"); p.set_defaults(fn=cmd_changelog)
    p = sub.add_parser("sprint-replay", help="committed vs completed points by backward changelog replay")
    p.add_argument("--sprint", required=True, help="sprint id, or name (needs --board)"); p.add_argument("--board", type=int)
    p.add_argument("--jql", help="widen the candidate set, e.g. project = X AND updated >= '<start-1d>' (needed to see punted issues)")
    p.add_argument("--points-at", choices=["commit", "close"], default="close"); p.add_argument("--include-subtasks", action="store_true")
    p.add_argument("--compare-sprintreport", action="store_true"); p.add_argument("--now"); p.add_argument("--no-bulk", action="store_true")
    p.add_argument("--name"); p.add_argument("--raw", action="store_true"); p.set_defaults(fn=cmd_sprint_replay)
    a = ap.parse_args()
    try:
        sys.exit(a.fn(a))
    except J.JiraError as e:
        print(error(str(e), e.hint or "ad-jira whoami --redetect", "ad-jira")); sys.exit(1)
    except C.ConfigError as e:
        print(error(str(e), e.hint or "ad-setup --only pncli", "ad-jira")); sys.exit(2)
