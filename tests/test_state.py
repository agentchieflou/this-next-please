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
    assert st["phase"] == "blocked" and st["open_questions"] == ["which directory is governed for DPM artifacts?"]
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


def test_an_empty_input_is_refused_and_the_list_is_bounded(tmp_path, monkeypatch, capsys):
    """The cap drops the oldest rather than refusing the newest: the file itself is under
    `.agent/in/` either way, and a state.json that grows without end is the worse failure."""
    p = _init(tmp_path, monkeypatch)
    assert cli_state.main(["set", "--input", "   "]) == 2
    assert "--input expects a path" in capsys.readouterr().out
    assert "inputs" not in json.load(open(p, encoding="utf-8"))       # nothing recorded, nothing left

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
