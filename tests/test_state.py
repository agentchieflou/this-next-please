"""ad-state: the only writer of .agent/state.json — validated keys, clean encoding, tolerant reads."""
import json
import os

from agentdata import cli_state
from agentdata import state as S

STUB = {"project": "RDSD", "phase": "idle", "active_ticket": None, "branch": None, "pr_url": None, "confluence_url": None,
        "open_questions": [], "artifacts": [], "tools": {"pncli_verified": None, "doctor_verified": None}, "last_updated": None}


def _init(tmp_path, monkeypatch, raw=None):
    monkeypatch.chdir(tmp_path)
    os.makedirs(".agent")
    p = os.path.join(".agent", "state.json")
    with open(p, "wb") as f:
        f.write(raw if raw is not None else json.dumps(STUB).encode("utf-8"))
    return p


def test_set_validates_keys_and_writes_clean_utf8(tmp_path, monkeypatch, capsys):
    p = _init(tmp_path, monkeypatch)
    rc = cli_state.main(["set", "phase=querying", "active_ticket=RDSD-22399", "--artifact", ".agent\\out\\x.tsv=jira rows", "--run-id", "r1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ok: true" in out and "state: phase=querying ticket=RDSD-22399" in out
    raw = open(p, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw and raw.endswith(b"}\n")
    st = json.loads(raw)
    assert st["phase"] == "querying" and st["active_ticket"] == "RDSD-22399" and st["last_updated"].endswith("Z")
    assert st["artifacts"] == [{"path": ".agent/out/x.tsv", "what": "jira rows", "run_id": "r1", "added": st["last_updated"][:10]}]
    assert cli_state.main(["set", "phase=flying"]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "one of idle" in out
    assert cli_state.main(["set", "tickets=RDSD-1"]) == 2 and "unknown state key" in capsys.readouterr().out
    assert cli_state.main(["set", "phase"]) == 2 and "key=value" in capsys.readouterr().out
    assert cli_state.main(["set", "active_ticket=null"]) == 0
    assert json.load(open(p, encoding="utf-8"))["active_ticket"] is None and json.load(open(p, encoding="utf-8"))["phase"] == "querying"


def test_blocked_questions_tools_and_bom_state_rewritten_clean(tmp_path, monkeypatch, capsys):
    p = _init(tmp_path, monkeypatch, raw=json.dumps(STUB).encode("utf-8-sig"))   # a PowerShell ConvertTo-Json | Set-Content write
    assert cli_state.main(["set", "phase=blocked", "--question", "which directory is governed for DPM artifacts?"]) == 0
    raw = open(p, "rb").read()
    assert not raw.startswith(b"\xef\xbb\xbf")
    st = json.loads(raw)
    # A record with an id, not a bare string (#231): a string could only ever be cleared, never answered.
    assert st["phase"] == "blocked" and [(q["id"], q["q"], q["blocking"]) for q in st["open_questions"]] == [
        ("q1", "which directory is governed for DPM artifacts?", True)]
    assert cli_state.main(["set", "phase=blocked", "--question", "which directory is governed for DPM artifacts?"]) == 0
    assert len(json.load(open(p, encoding="utf-8"))["open_questions"]) == 1          # no duplicates
    assert cli_state.main(["set", "phase=triaged", "--clear-questions", "--tool", "doctor_verified=2026-09-02"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert st["open_questions"] == [] and st["tools"]["doctor_verified"] == "2026-09-02" and st["tools"]["pncli_verified"] is None
    assert cli_state.main(["set", "--tool", "nope=1"]) == 2
    capsys.readouterr()
    assert cli_state.main(["show"]) == 0
    out = capsys.readouterr().out
    assert "phase: triaged" in out and "state: phase=triaged ticket=None" in out


def test_a_question_asked_with_set_can_be_answered_and_the_answer_unblocks(tmp_path, monkeypatch, capsys):
    """#231: `friction-log` and `codebase-map` asked with `set phase=blocked --question`, which stored
    a string with no id. `ad-state answer` refused it, the tile's card sent `qid=""` and was refused
    too, so `--clear-questions` was the only way out -- and a clear is exactly what the fold never
    heard about. Now it has an id, and the phase it interrupted comes back when it is answered."""
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["set", "phase=querying"]) == 0
    assert cli_state.main(["set", "phase=blocked", "--question", "which sprint table?"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert st["open_questions"][0]["id"] == "q1" and st["blocked_from"] == "querying"
    assert cli_state.main(["answer", "q1", "sprint_2026"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert st["open_questions"] == [] and st["phase"] == "querying"
    assert st["answered_questions"][0]["answer"] == "sprint_2026"


def test_a_cleared_question_never_gives_its_id_to_the_next_one(tmp_path, monkeypatch, capsys):
    """#231: ids came from the open and answered lists, and a cleared question is in neither -- so
    the next ask got `q1` back, and a tile drawn a moment earlier answered the wrong question."""
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["ask", "first?"]) == 0
    assert cli_state.main(["set", "phase=idle", "--clear-questions"]) == 0
    assert cli_state.main(["ask", "second?"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert [q["id"] for q in st["open_questions"]] == ["q2"]
    assert st["question_seq"] == 2


def test_a_string_written_before_ids_gets_one_at_the_next_write(tmp_path, monkeypatch, capsys):
    """A state.json from before #231 keeps its bare strings until `ad-state` next writes it, and then
    each becomes a record -- text, order and blocking kept -- so the operator can answer it at last."""
    legacy = dict(STUB, phase="blocked", open_questions=["legacy one", {"id": "q4", "q": "a record"}, "legacy two"])
    p = _init(tmp_path, monkeypatch, raw=json.dumps(legacy).encode("utf-8"))
    assert cli_state.main(["set", "branch=feature"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert [(q["id"], q["q"]) for q in st["open_questions"]] == [
        ("q5", "legacy one"), ("q4", "a record"), ("q6", "legacy two")]
    assert all(q.get("blocking", True) for q in st["open_questions"])


def test_an_input_is_recorded_once_and_show_lists_it(tmp_path, monkeypatch, capsys):
    """#132: the fleet's Downloads tray copies a file into `.agent/in/<KEY>/` on a click and then
    asks `ad-state` to record it, because `ad-state` is the only writer of state.json. Without
    `--input` that ask exited 2 -- `unrecognized arguments: --input` -- and every attach reported
    `recorded: false`, so the criterion "`ad-state show` lists the input" was never met."""
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["set", "active_ticket=RDSD-22449",
                           "--input", ".agent/in/RDSD-22449/export.md"]) == 0
    assert "inputs: 1" in capsys.readouterr().out
    assert json.load(open(p, encoding="utf-8"))["inputs"] == [".agent/in/RDSD-22449/export.md"]

    # the Windows spelling of the same file is the same input, not a second one
    assert cli_state.main(["set", "--input", ".agent\\in\\RDSD-22449\\export.md",
                           "--input", ".agent/in/RDSD-22449/second.md"]) == 0
    assert json.load(open(p, encoding="utf-8"))["inputs"] == [".agent/in/RDSD-22449/export.md",
                                                              ".agent/in/RDSD-22449/second.md"]
    capsys.readouterr()
    assert cli_state.main(["show"]) == 0
    out = capsys.readouterr().out
    assert "inputs[2]: .agent/in/RDSD-22449/export.md,.agent/in/RDSD-22449/second.md" in out


def test_an_empty_input_records_nothing_and_the_list_is_bounded(tmp_path, monkeypatch, capsys):
    """An empty value is skipped the way an empty `--question` is, and the count in the summary says
    so. The cap drops the oldest rather than refusing the newest: the file itself is under
    `.agent/in/` either way, and a state.json that grows without end is the worse failure."""
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["set", "--input", "   "]) == 0
    assert "inputs: 0" in capsys.readouterr().out
    assert "inputs" not in json.load(open(p, encoding="utf-8"))       # nothing to record, no key

    many = [f".agent/in/RDSD-1/f{n}.md" for n in range(S.INPUTS_CAP + 5)]
    argv = ["set"]
    for one in many:
        argv += ["--input", one]
    assert cli_state.main(argv) == 0
    recorded = json.load(open(p, encoding="utf-8"))["inputs"]
    assert len(recorded) == S.INPUTS_CAP and recorded[0] == many[5] and recorded[-1] == many[-1]


def test_prune_and_missing_file_hint(tmp_path, monkeypatch, capsys):
    arts = [{"path": "a", "added": "2026-08-01"}, {"path": "b", "added": "2026-08-26"}, {"path": "c"}, "junk"]
    assert [a["path"] for a in S.prune(arts, "2026-09-02")] == ["b", "c"]
    monkeypatch.chdir(tmp_path)
    assert cli_state.main(["show"]) == 2
    assert "ad-setup --project ." in capsys.readouterr().out
    os.makedirs(".agent")
    with open(os.path.join(".agent", "state.json"), "wb") as f:
        f.write(b"\xef\xbb\xbf{broken")
    assert cli_state.main(["set", "phase=idle"]) == 2
    assert "not valid JSON" in capsys.readouterr().out
    from agentdata.__main__ import COMMANDS
    assert COMMANDS["state"][0] == "agentdata.cli_state"


# ------------------------------------------------------------------ scope (friction scan 1.1)


def test_a_question_belongs_to_its_ticket_and_parks_when_the_ticket_changes(tmp_path, monkeypatch, capsys):
    """A blocking question asked on one ticket used to stop every later request in the checkout:
    the router read `open_questions` globally. It is scoped now -- it still blocks its own ticket,
    and it comes back the moment that ticket is active again."""
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["set", "active_ticket=RDSD-1", "phase=querying"]) == 0
    assert cli_state.main(["ask", "which sprint table?"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert st["phase"] == "blocked" and st["open_questions"][0]["ticket"] == "RDSD-1"

    assert cli_state.main(["set", "active_ticket=RDSD-2"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert st["phase"] == "idle" and "blocked_from" not in st
    assert [q["id"] for q in st["open_questions"]] == ["q1"]          # parked, not dropped
    capsys.readouterr()
    assert cli_state.main(["blocking"]) == 0
    out = capsys.readouterr().out
    assert "blocking: 0" in out and "parked: 1" in out and "next: continue" in out

    assert cli_state.main(["set", "active_ticket=RDSD-1", "phase=triaged"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert st["phase"] == "blocked" and st["blocked_from"] == "triaged"
    capsys.readouterr()
    assert cli_state.main(["blocking", "--ticket", "RDSD-1"]) == 0
    out = capsys.readouterr().out
    assert "blocking: 1" in out and "which sprint table?" in out
    assert cli_state.main(["answer", "q1", "sprint_2026"]) == 0
    assert json.load(open(p, encoding="utf-8"))["phase"] == "triaged"


def test_a_question_from_before_scopes_still_blocks_every_ticket(tmp_path, monkeypatch, capsys):
    """No `ticket` key: written before scopes existed, so it keeps meaning what it meant."""
    legacy = dict(STUB, phase="blocked", blocked_from="querying", active_ticket="RDSD-1",
                  open_questions=[{"id": "q1", "q": "old?", "blocking": True}])
    p = _init(tmp_path, monkeypatch, raw=json.dumps(legacy).encode("utf-8"))
    assert cli_state.main(["set", "active_ticket=RDSD-9"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert st["phase"] == "blocked"
    capsys.readouterr()
    assert cli_state.main(["blocking"]) == 0
    assert "blocking: 1" in capsys.readouterr().out


def test_superseding_closes_one_question_with_the_instruction_that_replaced_it(tmp_path, monkeypatch, capsys):
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["set", "phase=querying"]) == 0
    assert cli_state.main(["ask", "deploy to UAT or PROD?", "--choice", "UAT", "--choice", "PROD"]) == 0
    assert cli_state.main(["ask", "which sprint?"]) == 0
    assert cli_state.main(["supersede", "q1", "skip the deploy, just open the PR"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert [q["id"] for q in st["open_questions"]] == ["q2"] and st["phase"] == "blocked"
    done = st["answered_questions"][0]
    assert done["superseded"] is True and done["answer"] == "skip the deploy, just open the PR"
    assert cli_state.main(["supersede", "q9", "anything"]) == 2
    assert "no open question" in capsys.readouterr().out
    assert cli_state.main(["supersede", "q2", "use the current sprint"]) == 0
    assert json.load(open(p, encoding="utf-8"))["phase"] == "querying"


def test_a_followup_is_recorded_and_never_stops_the_agent(tmp_path, monkeypatch, capsys):
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["set", "phase=validating", "active_ticket=RDSD-3"]) == 0
    assert cli_state.main(["ask", "also rename the page title?", "--followup"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    assert st["phase"] == "validating"
    assert st["open_questions"][0]["kind"] == "followup" and st["open_questions"][0]["blocking"] is False
    capsys.readouterr()
    assert cli_state.main(["ask", "x?", "--followup", "--assume", "y"]) == 2
    assert "two different answers" in capsys.readouterr().out
    assert cli_state.main(["ask", "is pwsh allowed?", "--want", "access", "--ticket", "any"]) == 0
    st = json.load(open(p, encoding="utf-8"))
    access = st["open_questions"][-1]
    assert access["want"] == "access" and access["ticket"] is None and st["phase"] == "blocked"


def test_the_file_carries_its_schema_and_a_newer_one_is_refused_by_name(tmp_path, monkeypatch, capsys):
    """Friction scan 1.6 / §3 item 6: version the state.json schema. Every write stamps it; a file a
    newer `ad-state` wrote is refused with the fix, never read as if its keys meant what they used to."""
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["set", "phase=querying"]) == 0
    assert json.load(open(p, encoding="utf-8"))["schema"] == S.SCHEMA
    future = dict(STUB, schema=S.SCHEMA + 1)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(future, f)
    capsys.readouterr()
    assert cli_state.main(["show"]) == 2
    out = capsys.readouterr().out
    assert "newer ad-state" in out and "ad-update" in out
    stub = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "agentdata", "templates", "project-stub", "agent-state.json"),
                          encoding="utf-8"))
    assert stub["schema"] == S.SCHEMA, "a new project starts on the schema the CLI writes"
