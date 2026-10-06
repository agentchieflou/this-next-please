"""The mobile contract's producer tests (#598): `contract/fleet-mobile.v1.schema.json` is what the laptop writes.

After the split (docs/plan-mobile.md; `.agent/out/ci-repo-restructure-plan.md` §5.2) the phone side depends on this
file, not on this package, so the file has to be exactly what `bridge.py` does:

* the version and every enum equal their Python sources, and the caps equal `bridge.LIMITS`;
* every record kind the bridge writes, written here by the bridge itself, validates, and so does every record the
  existing bridge tests write (`mobile_contract.contract_checked`, autouse in those modules);
* every example in `contract/examples/` validates, and each outbox example carries the producer's keys in the
  producer's order, so a flow's Parse JSON step generated from an example reads a real file;
* the five lists' columns and FleetDecide's inputs and response are the app's and the flow's;
* nothing in `contract/released/` is removed or tightened without a version bump (the guard, shown on fixture
  schemas below).
"""
from __future__ import annotations
import copy
import glob
import importlib.util
import json
import os
import re
import time
import zipfile

import pytest
from jsonschema import Draft202012Validator

import mobile_contract as MC
from agentdata import textio
from agentdata.fleet import approval, bridge, notify
from agentdata.fleet.agentstate import STATE_ROLES, STATES

from mobile_contract import contract_checked                     # noqa: F401 - autouse: every record written validates
from test_fleet_bridge import UPN, _cfg, _drop, _phone, _request, _row
from test_fleet_events import fleet_home                        # noqa: F401 - a fixture, used by name
from test_mobile_powerapp import CLOSED_SETS, COLUMNS, LISTS, SAMPLE

FLOWS = os.path.join(MC.REPO_ROOT, "mobile", "flows")
RECORDS = MC.OUTBOX_DEFS + MC.INBOX_DEFS


def _defs() -> dict:
    return MC.load()["$defs"]


def _example_def(path: str, record: dict) -> str:
    kind = record["kind"]
    if os.path.basename(path).startswith("inbox-"):
        return "inbox_" + kind
    return "decision_mirror" if kind == "decision" else kind


def _examples() -> dict[str, dict]:
    out = {}
    for path in sorted(glob.glob(os.path.join(MC.EXAMPLES, "*.json"))):
        with open(path, encoding="utf-8") as f:
            out[os.path.basename(path)] = json.load(f)
    return out


def _flow(name: str) -> dict:
    with open(os.path.join(FLOWS, f"{name}.definition.json"), encoding="utf-8") as f:
        return json.load(f)


def _actions(node) -> dict:
    """Every action of a flow definition by name, however deep the scopes nest."""
    found = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "actions" and isinstance(value, dict):
                for name, action in value.items():
                    found[name] = action
            found.update(_actions(value))
    elif isinstance(node, list):
        for value in node:
            found.update(_actions(value))
    return found


# ------------------------------------------------------------------------------------ the file and its version


def test_the_schema_is_draft_2020_12_and_its_version_is_the_bridges():
    schema = MC.load()
    Draft202012Validator.check_schema(schema)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["contract"] == bridge.MOBILE_CONTRACT == schema["$defs"]["contract"]["const"]
    assert os.path.basename(MC.SCHEMA_PATH) == f"fleet-mobile.v{bridge.MOBILE_CONTRACT}.schema.json"
    assert schema["$defs"]["schema"]["const"] == bridge.MOBILE_SCHEMA
    for name in RECORDS:
        assert schema["$defs"][name]["properties"]["schema"] == {"$ref": "#/$defs/schema"}, name
    for name in ("heartbeat", "pairing"):          # the two records the app reads the version from
        assert schema["$defs"][name]["properties"]["contract"] == {"$ref": "#/$defs/contract"}, name
    assert schema["oneOf"] == [{"$ref": f"#/$defs/{name}"} for name in RECORDS]


def test_every_enum_equals_its_python_source():
    defs = _defs()
    assert defs["state"]["enum"] == list(STATES)
    assert defs["role"]["enum"] == list(dict.fromkeys(STATE_ROLES.values()))
    assert defs["severity"]["enum"] == list(notify.SEVERITIES)
    assert defs["notification_state"]["enum"] == list(notify.RULES)
    assert defs["decision"]["enum"] == [approval.APPROVED, approval.DENIED]
    mapped = {rule["if"]["properties"]["state"]["const"]: rule["then"]["properties"]["role"]["const"]
              for rule in defs["attention"]["allOf"]}
    assert mapped == STATE_ROLES, "attention's role is STATE_ROLES[state]"
    for (table, column), closed in CLOSED_SETS.items():
        assert set(defs[table]["properties"][column]["enum"]) == closed, (table, column)


# Every capped string, by where it sits: `(def, JSON pointer below it) -> LIMITS key`.
CAPPED = {
    ("attention", "repo"): "repo", ("attention", "project"): "project", ("attention", "says"): "says",
    ("attention", "last_said"): "last_said", ("attention", "approval_id"): "id",
    ("attention", "approvals/items"): "id", ("attention", "questions/items/q"): "q",
    ("attention", "questions/items/choices/items"): "choice", ("attention", "questions/items/default"): "default",
    ("approval", "id"): "id", ("approval", "repo"): "repo", ("approval", "summary"): "summary",
    ("decision_mirror", "id"): "id", ("decision_mirror", "reason"): "reason", ("decision_mirror", "by"): "by",
    ("notification", "repo"): "repo", ("notification", "ticket"): "ticket", ("notification", "title"): "title",
    ("notification", "body"): "body", ("notification", "approval_id"): "id",
    ("heartbeat", "operator"): "by", ("pairing", "operator"): "by",
    ("result", "id"): "id", ("result", "repo"): "repo", ("result", "error"): "reason", ("result", "hint"): "reason",
    ("inbox_reply", "repo"): "repo", ("inbox_reply", "message"): "message",
    ("inbox_reply", "answers/items/answer"): "answer", ("ticket", ""): "ticket",
}


def _at(schema: dict, pointer: str) -> dict:
    for part in [p for p in pointer.split("/") if p]:
        schema = schema[part] if part == "items" else schema["properties"][part]
    return schema


def test_the_limits_are_bridge_limits_and_every_capped_field_carries_its_cap():
    schema = MC.load()
    assert schema["limits"] == bridge.LIMITS
    defs = schema["$defs"]
    for (name, pointer), key in CAPPED.items():
        assert _at(defs[name], pointer)["maxLength"] == bridge.LIMITS[key], (name, pointer)
    assert set(bridge.LIMITS) - set(CAPPED.values()) == {"preview_bytes", "preview_head"}   # not a field's cap
    then = defs["approval"]["allOf"][0]["then"]["properties"]["payload_preview"]
    assert then["properties"]["head"]["maxLength"] == bridge.LIMITS["preview_head"]
    attention = defs["attention"]
    assert set(attention["properties"]) == set(attention["required"]) == bridge.ATTENTION_KEYS
    assert attention["properties"]["approvals"]["maxItems"] == bridge.APPROVALS_MAX
    assert attention["properties"]["questions"]["maxItems"] == bridge.QUESTIONS_MAX
    assert _at(attention, "questions/items/choices")["maxItems"] == bridge.CHOICES_MAX
    reply = defs["inbox_reply"]["properties"]
    assert reply["answers"]["maxItems"] == bridge.ANSWERS_MAX
    assert reply["answers"]["items"]["properties"]["id"]["maxLength"] == bridge.ANSWER_ID_MAX
    for name in ("heartbeat", "pairing"):
        expire = defs[name]["properties"]["expire_s"]
        assert (expire["minimum"], expire["maximum"]) == (bridge.EXPIRE_MIN_S, bridge.EXPIRE_MAX_S), name


# ------------------------------------------------------------------------------------ the producer


def test_every_record_kind_the_bridge_writes_validates(fleet_home, tmp_path, monkeypatch):  # noqa: F811
    """One pass through everything the laptop writes: `contract_checked` validates each file before it lands."""
    cfg = _cfg(tmp_path)
    before = MC.SEEN.copy()
    bridge.init_tree(cfg)                                                            # pairing

    small, large = _request(), _request(payload={"rows": ["x" * 90] * 120})          # a preview, a truncated one
    laptop = _request(kind="jira-create")
    question = {"id": "q1", "q": "Which window?", "choices": ["calendar month", "last 30 days"],
                "want": "choice", "default": "calendar month", "blocking": True}
    rows = [_row("luna", state="needs_human", needs_human=True, asked=[question]), _row("rdsd-uat")]
    snapshot = {"repos": rows, "approvals": approval.pending()}
    bridge.export_once(cfg, snapshot)                                                # attention, approval, heartbeat
    approval.decide(laptop["id"], approval.DENIED, reason="wrong workspace")
    bridge.export_once(cfg, snapshot)                                                # a laptop decision's mirror

    _drop(cfg, _phone(small))                                                        # a phone decision: mirror, result
    _drop(cfg, _phone(large, reason="", decision="denied"))                          # refused: a result, rejected
    reply = {"schema": 1, "kind": "reply", "nonce": "r" * 32, "issued": bridge._utc(), "by": UPN,
             "expires": bridge._utc(time.time() + 600), "repo": "not-registered", "message": "go on"}
    _drop(cfg, reply, name="reply-x.json")                                           # a reply's result, rejected
    assert bridge.apply_once(cfg) == {"applied": 1, "rejected": 2, "retried": 0}

    item = notify.notification("luna", "waiting_approval", "a write is waiting", ticket="RDSD-131", seq=4)
    assert notify.send_mobile(item, cfg)                                             # notification

    seen = MC.SEEN - before
    assert set(seen) == set(MC.OUTBOX_DEFS), f"not every kind was written: {sorted(seen)}"
    assert seen["approval"] == 3 and seen["decision_mirror"] == 2 and seen["result"] >= 3


def test_a_decision_mirrors_decided_is_utc_with_a_z_like_every_other_outbox_stamp(fleet_home, tmp_path):  # noqa: F811
    """`FleetApprovals.DecidedAt` is `yyyy-MM-ddTHH:mm:ssZ`; the mirror of either side's decision writes that form."""
    cfg = _cfg(tmp_path)
    laptop, phone = _request(kind="jira-create"), _request()
    snapshot = {"repos": [], "approvals": approval.pending()}
    bridge.export_once(cfg, snapshot)                                                # both requests
    approval.decide(laptop["id"], approval.DENIED, reason="wrong workspace")
    bridge.export_once(cfg, snapshot)                                                # the laptop decision's mirror
    _drop(cfg, _phone(phone))                                                        # the phone decision's mirror
    assert bridge.apply_once(cfg)["applied"] == 1
    folder = bridge.check_folder(cfg)
    for request in (laptop, phone):
        mirror = textio.read_json(bridge.outbox_dir(folder, "approvals", f"{request['id']}.decision.json"), "mirror")
        on_disk = approval.read_decision(request["id"])["decided"]
        assert mirror["decided"] == bridge._utc(bridge._epoch(on_disk)), (mirror["via"], mirror["decided"])
        assert mirror["decided"].endswith("Z"), (mirror["via"], mirror["decided"])
    example = _examples()["decision-luna-a1c9.json"]
    assert example["decided"] == bridge.decision_mirror(example["id"], dict(example, decided="2026-09-25T16:06:40"))[
        "decided"] == "2026-09-25T16:06:40Z"


def test_a_record_the_schema_accepts_is_one_the_applier_never_refuses_for_its_shape():
    """The inbox half: every shape `_check_common`, `_check_decision` and `_check_reply` refuse, the schema refuses."""
    examples = _examples()
    decision, reply = examples["inbox-decision-9f2c4b7e.json"], examples["inbox-reply-4b8e1f3a.json"]
    MC.check(decision, "inbox_decision")
    MC.check(reply, "inbox_reply")
    refused = [
        ("inbox_decision", dict(decision, schema=2)),
        ("inbox_decision", dict(decision, kind="vote")),
        ("inbox_decision", dict(decision, nonce="short")),
        ("inbox_decision", {k: v for k, v in decision.items() if k != "issued"}),
        ("inbox_decision", dict(decision, expires="tomorrow")),
        ("inbox_decision", dict(decision, decision="maybe")),
        ("inbox_decision", dict(decision, decision="denied", reason="  ")),
        ("inbox_decision", dict(decision, reason=7)),
        ("inbox_decision", dict(decision, device=["iOS"])),
        ("inbox_decision", dict(decision, id="a/b")),
        ("inbox_reply", dict(reply, repo="")),
        ("inbox_reply", dict(reply, repo="r" * (bridge.LIMITS["repo"] + 1))),
        ("inbox_reply", dict(reply, message="x" * (bridge.MESSAGE_MAX + 1))),
        ("inbox_reply", dict(reply, answers=[{"id": "q", "answer": "a"}] * (bridge.ANSWERS_MAX + 1))),
        ("inbox_reply", dict(reply, answers=[{"id": "q" * 33, "answer": "a"}])),
        ("inbox_reply", dict(reply, answers=[{"id": "q1", "answer": "   "}], message="")),
        ("inbox_reply", dict(reply, answers=None, message=None)),
    ]
    for name, record in refused:
        assert MC.errors(record, name), f"the schema accepts what the applier refuses: {record}"


# ------------------------------------------------------------------------------------ the examples


def test_every_example_validates_and_there_is_one_per_record_kind():
    examples = _examples()
    root = Draft202012Validator(MC.load())
    covered = set()
    for name, record in examples.items():
        which = _example_def(name, record)
        MC.check(record, which, where=f"contract/examples/{name}")
        assert not list(root.iter_errors(record)), f"{name}: the root schema does not accept it as exactly one kind"
        covered.add(which)
    assert covered == set(RECORDS)
    for path in glob.glob(os.path.join(MC.CONTRACT_DIR, "**", "*.json"), recursive=True):
        raw = open(path, "rb").read()
        assert b"\r" not in raw and raw.endswith(b"\n") and not raw.startswith(b"\xef\xbb\xbf"), path


def _keys(record) -> list:
    """The key order all the way down: what a Parse JSON schema generated from the file would see."""
    if isinstance(record, dict):
        return [(k, _keys(v)) for k, v in record.items()]
    if isinstance(record, list) and record:
        return [_keys(record[0])]
    return []


def test_each_outbox_example_has_the_producers_keys_in_the_producers_order(fleet_home, tmp_path):  # noqa: F811
    examples = _examples()
    cfg = _cfg(tmp_path)
    folder = bridge.check_folder(cfg)
    scrubber = bridge.Scrubber()
    question = {"id": "q1", "q": "Which window?", "choices": ["a", "b"], "want": "choice", "default": "a"}
    request = _request(repo="rdsd-uat", payload=examples["approval-rdsd-uat-7f3a.json"]["payload_preview"])
    nonce = "9f2c4b7e1d3a48c2b6e5f0a1d2c3b4e5"
    decided = {"decision": "approved", "reason": "", "by": f"mobile:{UPN}", "via": "mobile",
               "decided": "2026-09-25T16:06:40", "digest": request["digest"], "late": False, "nonce": nonce}
    item = notify.notification("luna", "needs_human", "asked", ticket="RDSD-118", seq=187)
    notify.send_mobile(item, cfg)
    [note] = os.listdir(bridge.outbox_dir(folder, "notifications"))

    def result(path):
        return textio.read_json(path, "result")

    produced = {
        "attention-luna-187.json": bridge.attention_row(_row("luna", asked=[question]), scrubber.scrub, []),
        "approval-rdsd-uat-7f3a.json": bridge.approval_record(request, scrubber, cfg),
        "decision-luna-a1c9.json": bridge.decision_mirror(request["id"], decided, scrubber.scrub),
        "notification-luna-needs_human-187.json": textio.read_json(
            bridge.outbox_dir(folder, "notifications", note), "notification"),
        "heartbeat-20260926-0915.json": bridge.heartbeat_record(cfg, bridge.read_state(), {}),
        "result-9f2c4b7e.json": result(bridge.write_result(folder, nonce, "decision", True, id="x", late=False)),
        "result-c0d3e6f9-rejected.json": result(bridge.write_result(
            folder, "c0d3e6f9a2b5c8d1e4f7a0b3c6d9e2f5", "decision", False, id="x", code="mobile_expired",
            error="e", hint="h")),
        "result-4b8e1f3a-reply.json": result(bridge.write_result(
            folder, "4b8e1f3a9c2d47e6b0a5d9c8f7e6b5a4", "reply", True, repo="luna", via="say", answered=["q1"])),
        "pairing-5e1c9a7b.json": bridge.init_tree(cfg)["pairing"],
    }
    outbox = {n for n, r in examples.items() if not n.startswith("inbox-")}
    assert outbox == set(produced), "an outbox example without a producer here, or the other way round"
    for name, record in produced.items():
        assert _keys(examples[name]) == _keys(record), f"{name} drifted from what the bridge writes"
    approval_ = examples["approval-rdsd-uat-7f3a.json"]
    assert approval_["payload_bytes"] == produced["approval-rdsd-uat-7f3a.json"]["payload_bytes"]


def test_each_inbox_example_is_what_fleet_decide_composes():
    examples = _examples()
    actions = _actions(_flow("FleetDecide"))
    for name, action in (("inbox-decision-9f2c4b7e.json", "Compose_decision_record"),
                         ("inbox-reply-4b8e1f3a.json", "Compose_reply_record")):
        assert list(examples[name]) == list(actions[action]["inputs"]), name


# ------------------------------------------------------------------------------------ the lists and the flow


#: Columns a list may define beyond the ones this repository's app copy reads, each optional: `Operator` tags every row
#: when several operators' fleets share one site's lists (agentchieflou/Koa, the multi-operator layout).
OPTIONAL_COLUMNS = {"Operator"}


def test_the_five_lists_are_the_apps_columns_and_every_sample_row_validates():
    defs = _defs()
    assert set(LISTS) == set(COLUMNS)
    for table in LISTS:
        columns = list(defs[table]["properties"])
        assert defs[table]["required"] == COLUMNS[table] == columns[:len(COLUMNS[table])], table
        assert set(columns[len(COLUMNS[table]):]) <= OPTIONAL_COLUMNS, f"{table}: an extra column must be optional"
        with open(os.path.join(SAMPLE, f"{table}.json"), encoding="utf-8") as f:
            for row in json.load(f):
                MC.check(row, table, where=f"mobile/powerapp/sample/{table}.json {row['Title']}")


def test_fleet_decides_inputs_and_response_are_the_flows():
    defs = _defs()
    flow = _flow("FleetDecide")["properties"]["definition"]
    trigger = flow["triggers"]["manual"]["inputs"]["schema"]
    titles = [p["title"] for p in trigger["properties"].values()]
    assert titles == list(defs["fleet_decide_inputs"]["properties"]) == defs["fleet_decide_inputs"]["required"]
    for key, prop in trigger["properties"].items():
        want = defs["fleet_decide_inputs"]["properties"][prop["title"]]
        assert ("number" if key.startswith("number") else "string") == want.get("type", "string"), prop["title"]
    responses = [a for a in _actions(flow).values() if a.get("type") == "Response"]
    assert len(responses) == 3
    for response in responses:
        assert list(response["inputs"]["body"]) == list(defs["fleet_decide_response"]["properties"])


def _workbook():
    """`mobile/data/make_workbook.py` as a module: its `ROWS` import without openpyxl, which only building needs."""
    path = os.path.join(MC.REPO_ROOT, "mobile", "data", "make_workbook.py")
    spec = importlib.util.spec_from_file_location("make_workbook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cell(value) -> str:
    """A record value as FleetOutboxToLists writes it into a text column (`@string(...)` for objects and lists)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return "" if value is None else str(value)


def _result_columns(result: dict) -> dict:
    """The `result` case: `Result` from ok, `ResultText` = trim(concat(error, ' ', hint)) truncated to 255."""
    return {"Result": "applied" if result["ok"] else "rejected", "ResultCode": result["code"],
            "ResultText": f"{result['error']} {result['hint']}".strip()[:255], "ResultAt": result["at"]}


def test_the_workbooks_sample_rows_are_what_the_flows_write_from_the_contract_examples():
    """`mobile/data/README.md`: the rows are what `contract/examples/*.json` would have produced, column by column,
    by the mapping in `mobile/flows/README.md`. Every row is also a valid list row."""
    ex, rows = _examples(), _workbook().ROWS

    def row(table, title):
        [found] = [r for r in rows[table] if r["Title"] == title]
        return found

    a = ex["attention-luna-187.json"]
    want = {"FleetAttention": {a["repo"]: {
        "Title": a["repo"], "Project": a["project"], "Ticket": a["ticket"], "State": a["state"], "Role": a["role"],
        "NeedsHuman": _cell(a["needs_human"]), "Says": a["says"], "LastSaid": a["last_said"],
        "AgeSeconds": _cell(a["age_s"]), "At": a["at"], "Generated": a["generated"], "ApprovalId": a["approval_id"],
        "ApprovalsJson": _cell(a["approvals"]), "QuestionsJson": _cell(a["questions"]),
        "RunNumber": _cell(a["run"]["n"]), "RunOrigin": a["run"]["origin"], "RunLive": _cell(a["run"]["live"]),
        "Model": a["model"], "SpendLine": a["spend"]["line"], "SpendTotal": _cell(a["spend"]["total"]),
        "SpendToday": _cell(a["spend"]["today"]), "SpendBudget": _cell(a["spend"]["budget"]),
        "Turns": _cell(a["spend"]["turns"]), "Supervised": _cell(a["supervised"]), "External": _cell(a["external"]),
        "Digest": a["digest"], "Seq": _cell(a["seq"])}}}

    p, m = ex["approval-rdsd-uat-7f3a.json"], ex["decision-luna-a1c9.json"]
    want["FleetApprovals"] = {
        p["id"]: {"Title": p["id"], "Repo": p["repo"], "Ticket": p["ticket"], "ApprovalKind": p["approval_kind"],
                  "Summary": p["summary"], "PayloadPreview": _cell(p["payload_preview"]),
                  "PayloadTruncated": _cell(p["payload_truncated"]), "PayloadBytes": _cell(p["payload_bytes"]),
                  "Digest": p["digest"], "Created": p["created"], "Expires": p["expires"],
                  "WaitingSeconds": _cell(p["waiting_s"]), "Status": "pending", "DecidedBy": "", "DecidedAt": "",
                  "Reason": "", "Via": "", "Late": "", "Nonce": "", "ResultCode": "", "ResultText": "",
                  "SourceFile": p["id"] + ".json"},
        m["id"]: {"Title": m["id"], "Status": m["decision"], "DecidedBy": m["by"], "DecidedAt": m["decided"],
                  "Via": m["via"], "Late": _cell(m["late"]), "Reason": m["reason"], "Nonce": m["nonce"],
                  "Digest": m["digest"]},
    }

    d, r = ex["inbox-decision-9f2c4b7e.json"], ex["inbox-reply-4b8e1f3a.json"]
    applied, rejected = ex["result-9f2c4b7e.json"], ex["result-c0d3e6f9-rejected.json"]
    want["FleetDecisions"] = {
        d["nonce"]: {"Title": d["nonce"], "Kind": d["kind"], "ApprovalId": d["id"], "Decision": d["decision"],
                     "Reason": d["reason"], "Message": "", "AnswersJson": "", "Digest": d["digest"], "By": d["by"],
                     "Device": d["device"], "Issued": d["issued"], "Expires": d["expires"],
                     "InboxFile": f"{d['kind']}-{d['nonce']}.json", **_result_columns(applied)},
        # The reply row is FleetDecide's, before its result lands: `sent`, the result columns empty.
        r["nonce"]: {"Title": r["nonce"], "Kind": r["kind"], "ApprovalId": "", "Repo": r["repo"], "Decision": "",
                     "Reason": "", "Message": r["message"], "AnswersJson": _cell(r["answers"]), "Digest": "",
                     "By": r["by"], "Device": r["device"], "Issued": r["issued"], "Expires": r["expires"],
                     "InboxFile": f"{r['kind']}-{r['nonce']}.json", "Result": "sent", "ResultCode": "",
                     "ResultText": "", "ResultAt": ""},
        rejected["nonce"]: {"Title": rejected["nonce"], "Kind": rejected["kind_of"], "ApprovalId": rejected["id"],
                            **_result_columns(rejected)},
    }
    assert d["id"] == applied["id"] == m["id"] and d["nonce"] == applied["nonce"] == m["nonce"]
    assert m["decided"] == applied["at"], "the phone's decision is applied when it is decided"

    n = ex["notification-luna-needs_human-187.json"]
    want["FleetNotifications"] = {n["key"]: {
        "Title": n["key"], "Repo": n["repo"], "Ticket": n["ticket"], "State": n["state"], "Severity": n["severity"],
        "TitleText": n["title"], "Body": n["body"], "At": n["at"], "Seq": _cell(n["seq"]), "Quiet": _cell(n["quiet"]),
        "ApprovalId": n["approval_id"]}}

    h = ex["heartbeat-20260926-0915.json"]
    beat = {"Title": "laptop", "At": h["at"], "EverySeconds": _cell(h["every_s"]),
            "ExpireSeconds": _cell(h["expire_s"]), "Contract": _cell(h["contract"]), "Operator": h["operator"],
            "Bridge": h["bridge"], "LaptopId": h["laptop_id"], "ServeUp": _cell(h["serve_up"]),
            "DeskStreams": _cell(h["desk_streams"]), "Repos": _cell(h["counts"]["repos"]),
            "NeedsHuman": _cell(h["counts"]["needs_human"]), "ApprovalsPending": _cell(h["counts"]["approvals_pending"]),
            "Notifications24h": _cell(h["counts"]["notifications_24h"]),
            "Rejected24h": _cell(h["counts"]["rejected_24h"]), "InboxLastSeen": h["inbox_last_seen"]}
    assert [b for b in rows["FleetHeartbeat"] if b["At"] == h["at"]] == [beat]

    off = [f"{table} {title} {c}: {row(table, title)[c]!r}, the example says {v!r}"
           for table, by_title in want.items() for title, columns in by_title.items()
           for c, v in columns.items() if row(table, title)[c] != v]
    assert off == [], "the workbook disagrees with contract/examples/:\n" + "\n".join(off)
    for table in LISTS:
        for sample in rows[table]:
            MC.check(sample, table, where=f"mobile/data/make_workbook.py {table} {sample['Title']}")


def _letter(i: int) -> str:
    """Excel's column letters: 1 -> A, 27 -> AA."""
    out = ""
    while i:
        i, rest = divmod(i - 1, 26)
        out = chr(65 + rest) + out
    return out


def test_the_committed_workbook_holds_exactly_the_generators_rows():
    """`FleetAgent.xlsx` is `make_workbook.py`'s output, sheet by sheet and cell by cell. Read with the standard
    library (openpyxl writes every cell as an inline string), so the check runs without openpyxl."""
    import xml.etree.ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    wb = _workbook()
    with zipfile.ZipFile(wb.OUT) as z:
        names = [e.get("name") for e in ET.fromstring(z.read("xl/workbook.xml")).iterfind("m:sheets/m:sheet", ns)]
        assert names == list(wb.COLUMNS)
        for n, table in enumerate(names, start=1):
            grid = []
            for r in ET.fromstring(z.read(f"xl/worksheets/sheet{n}.xml")).iterfind("m:sheetData/m:row", ns):
                cells = {re.match(r"[A-Z]+", c.get("r")).group(): "".join(t.text or "" for t in c.iterfind(".//m:t", ns))
                         for c in r.iterfind("m:c", ns)}
                grid.append(cells)
            columns = wb.COLUMNS[table]
            letters = [_letter(i) for i in range(1, len(columns) + 1)]
            got = [[g.get(x, "") for x in letters] for g in grid]
            assert got == [columns] + [[row[c] for c in columns] for row in wb.ROWS[table]], \
                f"{table}: FleetAgent.xlsx is stale; run python mobile/data/make_workbook.py"


# ------------------------------------------------------------------------------------ the breaking-change guard


def test_the_released_copy_is_this_version_and_nothing_in_it_was_removed_or_tightened():
    released, current = MC.load(MC.RELEASED_PATH), MC.load()
    assert released["contract"] == current["contract"] == bridge.MOBILE_CONTRACT
    assert MC.guard(released, current) == []


def _mutate(change):
    schema = copy.deepcopy(MC.load())
    change(schema)
    return schema


def _drop_says(s):
    del s["$defs"]["attention"]["properties"]["says"]
    s["$defs"]["attention"]["required"].remove("says")


BREAKING = {
    "a property removed": (_drop_says, "properties/says: removed"),
    "a record removed": (lambda s: s["$defs"].pop("pairing"), "$defs/pairing: removed"),
    "an enum value removed": (lambda s: s["$defs"]["state"]["enum"].remove("error"), "enum: removed ['error']"),
    "a field newly required": (lambda s: s["$defs"]["result"]["required"].append("late"), "now requires ['late']"),
    "a cap lowered": (lambda s: s["$defs"]["attention"]["properties"]["says"].update(maxLength=200),
                      "maxLength: 300 -> 200"),
    "a type narrowed": (lambda s: s["$defs"]["inbox_decision"]["properties"]["reason"].update(type="string"),
                        "type: ['null', 'string'] -> ['string']"),
    "a pattern added": (lambda s: s["$defs"]["attention"]["properties"]["repo"].update(pattern="^[a-z]+$"),
                        "pattern: '<none>'"),
    "a const changed": (lambda s: s["$defs"]["schema"].update(const=2), "const: 1 -> 2"),
    "a record kind removed from the root": (lambda s: s["oneOf"].pop(), "oneOf/8: removed"),
    "a rule added": (lambda s: s["$defs"]["heartbeat"].setdefault("allOf", []).append(
        {"properties": {"every_s": {"const": 300}}}), "allOf/0"),
    "a limit lowered": (lambda s: s["limits"].update(says=200), "limits/says: 300 -> 200"),
}
ADDITIVE = {
    "an optional property added": lambda s: s["$defs"]["attention"]["properties"].update(mood={"type": "string"}),
    "an enum value added": lambda s: s["$defs"]["state"]["enum"].append("paused"),
    "a record kind added": lambda s: (s["$defs"].update(ping={"type": "object"}),
                                      s["oneOf"].append({"$ref": "#/$defs/ping"})),
    "a cap raised": lambda s: s["$defs"]["attention"]["properties"]["says"].update(maxLength=400),
    "a limit raised": lambda s: s["limits"].update(says=400),
    "a requirement dropped": lambda s: s["$defs"]["result"]["required"].remove("hint"),
    "a type widened": lambda s: s["$defs"]["attention"]["properties"]["age_s"].update(type=["integer", "null"]),
}


@pytest.mark.parametrize("case", sorted(BREAKING))
def test_the_guard_refuses_a_removal_or_a_tightening_unless_the_version_is_bumped(case):
    change, needle = BREAKING[case]
    released, current = MC.load(MC.RELEASED_PATH), _mutate(change)
    found = MC.guard(released, current)
    assert any(needle in line for line in found), f"{case}: {found}"
    current["contract"] = released["contract"] + 1
    assert MC.guard(released, current) == [], "a bumped version may break anything"


@pytest.mark.parametrize("case", sorted(ADDITIVE))
def test_the_guard_lets_an_additive_change_keep_the_version(case):
    assert MC.guard(MC.load(MC.RELEASED_PATH), _mutate(ADDITIVE[case])) == [], case


def test_the_guard_refuses_closing_an_open_object():
    released = {"contract": 1, "$defs": {"x": {"type": "object"}}}
    current = {"contract": 1, "$defs": {"x": {"type": "object", "additionalProperties": False}}}
    assert MC.guard(released, current) == ["#/$defs/x/additionalProperties: now refuses everything"]


# ------------------------------------------------------------------------------------ the docs


def test_the_contract_page_states_the_two_versioning_rules():
    with open(os.path.join(MC.REPO_ROOT, "docs", "fleet-mobile.md"), encoding="utf-8") as f:
        page = f.read()
    section = page[page.index("## The contract, versioned"):]
    section = section[:section.index("\n## ", 1)]
    assert "An additive change keeps the version" in section
    assert "A breaking change raises `bridge.MOBILE_CONTRACT`" in section
    for path in ("contract/fleet-mobile.v1.schema.json", "contract/examples/", "contract/released/"):
        assert path in section, path
