"""The opt-in usage file: what it records, what it must never record, and what it must not break.

`docs/data-format-policy.md` set 50/1500 and 500 as first guesses and then deferred revisiting them
three times, because nothing here ever recorded which rule fired or what a result cost. This is the
instrumentation that produces that number.

Three properties are worth testing and the rest is arithmetic:

**It records nothing sensitive.** An `AgentTable.source` is a whole command line — `ad-td SELECT
ssn, dob FROM customers WHERE name = 'Ada Lovelace'` — so the test that matters feeds exactly that,
plus row values that look like data somebody would mind leaking, and reads the file back looking for
any of it.

**It never breaks a command.** A query that fails because instrumentation could not write a log is
strictly worse than no instrumentation.

**It is off until somebody turns it on**, in a file they can see afterwards rather than an
environment variable that vanishes with the shell.
"""
from __future__ import annotations

import json
import os

import pytest

from agentdata import cli_metrics, metrics, policy
from agentdata import config as C
from agentdata.model import AgentTable

SECRETS = ["123-45-6789", "Ada Lovelace", "customers", "SELECT", "acct-99887766"]
SOURCE = "ad-td SELECT ssn, dob FROM customers WHERE name = 'Ada Lovelace'"


@pytest.fixture()
def collecting(tmp_path, monkeypatch):
    """A config with recording on, pointing at a file in tmp_path."""
    dest = tmp_path / "metrics.tsv"
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"version": 1,
                               "metrics": {"enabled": True, "path": str(dest)}}), encoding="utf-8")
    monkeypatch.setenv(C.CONFIG_ENV, str(cfg))
    monkeypatch.setattr(metrics, "_CACHE", None)
    monkeypatch.chdir(tmp_path)                   # write_tsv puts artifacts under .agent/out
    yield dest
    metrics.reset_cache()


@pytest.fixture()
def not_collecting(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"version": 1}), encoding="utf-8")
    monkeypatch.setenv(C.CONFIG_ENV, str(cfg))
    monkeypatch.setattr(metrics, "_CACHE", None)
    monkeypatch.chdir(tmp_path)
    yield tmp_path / "metrics.tsv"
    metrics.reset_cache()


def _table(n=3, source=SOURCE):
    return AgentTable(name="t", columns=["account", "holder"],
                      rows=[["acct-99887766", "Ada Lovelace"] for _ in range(n)], source=source)


# ------------------------------------------------------------------------------ off by default


def test_nothing_is_written_until_somebody_turns_it_on(not_collecting):
    policy.render(_table())
    assert not not_collecting.exists()


def test_an_absent_config_is_off_rather_than_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv(C.CONFIG_ENV, str(tmp_path / "does-not-exist.json"))
    metrics.reset_cache()
    assert metrics.enabled() is False
    assert policy.render(_table())               # the command still works
    metrics.reset_cache()


def test_the_config_is_read_once_per_process_not_once_per_render(not_collecting, monkeypatch):
    """`record()` runs on every rendered result. Re-reading and re-parsing the config each time
    would make everyone pay for a feature that is off."""
    reads = []
    real = C.load
    monkeypatch.setattr(C, "load", lambda *a, **k: (reads.append(1), real(*a, **k))[1])
    for _ in range(5):
        policy.render(_table())
    assert len(reads) <= 1, f"config was read {len(reads)} times for 5 renders"


# --------------------------------------------------------------------- what it must never hold


def test_no_cell_value_or_query_text_reaches_the_file(collecting):
    policy.render(_table(n=600))                 # rule 6, the largest shape
    policy.render(_table(n=3))                   # rule 4
    blob = collecting.read_text(encoding="utf-8")
    for secret in SECRETS:
        assert secret not in blob, f"{secret!r} leaked into the usage file"
    assert "ad-td" in blob, "the command name itself is the point and must survive"


def test_the_command_is_the_first_token_and_nothing_after_it():
    """A parser that keeps a subcommand also keeps the first word of somebody's SQL on the day the
    shape surprises it. Everything past `ad-<name>` is thrown away rather than parsed."""
    assert metrics.command_of(SOURCE) == "ad-td"
    assert metrics.command_of("ad-dpm extract-fields --schema secret.json") == "ad-dpm"
    for hostile in ("SELECT * FROM t", "", "  ", "/bin/sh -c rm", "ad_td query",
                    "AD-TD SELECT 1", "ad-" + "x" * 40 + " q"):
        assert metrics.command_of(hostile) == metrics.UNKNOWN, hostile


def test_a_path_in_the_source_does_not_reach_the_file(collecting):
    policy.render(_table(source="ad-confluence html C:/Users/someone/private/notes.md"))
    blob = collecting.read_text(encoding="utf-8")
    assert "someone" not in blob and "notes.md" not in blob
    assert "ad-confluence" in blob


def test_every_recorded_field_is_a_count_a_clock_or_a_name_this_module_chose(collecting):
    policy.render(_table())
    record = metrics.read(str(collecting))[0]
    assert set(record) == set(metrics.COLUMNS)
    assert record["command"] == "ad-td"
    assert record["ts"].endswith("Z")
    for number in ("rule", "rows", "cols", "est_tokens"):
        assert isinstance(record[number], int)
    assert record["shape"] in ("scalar", "record", "table", "nested")


def test_the_module_imports_nothing_that_could_send_the_file():
    """"Never leaves the machine" is a property of what this module can reach, not a promise."""
    source = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "agentdata", "metrics.py"), encoding="utf-8").read()
    for network in ("import socket", "import urllib", "import http", "import requests",
                    "import ftplib", "import smtplib", "subprocess"):
        assert network not in source, f"metrics.py reaches {network}"


# ----------------------------------------------------------------------- what it does record


def test_each_rule_is_recorded_as_the_rule_that_fired(collecting):
    policy.render(_table(n=3))                                        # rule 4: small table
    policy.render(_table(n=300))                                      # rule 5: medium
    policy.render(_table(n=600))                                      # rule 6: large
    policy.render(AgentTable("t", ["a"], [["x"]], source="ad-td q"))  # rule 3: scalar
    assert [r["rule"] for r in metrics.read(str(collecting))] == [4, 5, 6, 3]


def test_rule_1_is_recorded_even_though_its_output_never_names_a_rule(collecting):
    """Rule 1 returns the payload itself, so there is no `rule` in the text to read back. It would
    otherwise be the one rule that never appears in a report about the rules."""
    out = policy.render(AgentTable("t", ["a"], [["x"]], source="ad-td q", raw={"a": "x"}), raw=True)
    assert "rule" not in out
    assert metrics.read(str(collecting))[0]["rule"] == 1


def test_the_estimate_is_of_the_text_that_actually_reached_the_context(collecting):
    """A large result renders a 10-row sample. Measuring before the cut would be a number about a
    string nobody ever sees."""
    out = policy.render(_table(n=5000))
    assert metrics.read(str(collecting))[0]["est_tokens"] == policy.est_tokens(out)
    assert metrics.read(str(collecting))[0]["rows"] == 5000       # the result's size, not the sample's


def test_nested_payloads_are_recorded_too(collecting):
    """Rule 8 is the shape that could not be flattened -- records sharing almost no keys. A
    payload that *can* be flattened goes through `render` and is recorded as whichever rule that
    picked, which is the honest answer: rule 8 never fired."""
    ragged = [{f"only_in_{i}": i, f"also_{i}": [i]} for i in range(6)]
    assert not AgentTable.flatten_ok(ragged)
    policy.render_nested(ragged, name="n", source="ad-pncli jira get", raw_payload=None)
    record = metrics.read(str(collecting))[0]
    assert record["rule"] == 8 and record["command"] == "ad-pncli"
    assert record["shape"] == "nested" and record["rows"] == 6


# ------------------------------------------------------------------------------- robustness


def test_a_failure_to_write_never_fails_the_command(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    # a path whose parent is a *file*: makedirs cannot create it, on either OS
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    cfg.write_text(json.dumps({"version": 1, "metrics": {"enabled": True,
                                                         "path": str(blocker / "m.tsv")}}),
                   encoding="utf-8")
    monkeypatch.setenv(C.CONFIG_ENV, str(cfg))
    monkeypatch.chdir(tmp_path)
    metrics.reset_cache()
    assert metrics.record(source="ad-td q", rule=4, shape="table", rows=1, cols=1,
                          est_tokens=10) is False
    assert policy.render(_table())               # and the command still returns its result
    metrics.reset_cache()


def test_a_broken_config_never_fails_the_command(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv(C.CONFIG_ENV, str(cfg))
    monkeypatch.chdir(tmp_path)
    metrics.reset_cache()
    assert policy.render(_table())
    metrics.reset_cache()


def test_a_torn_line_costs_one_row_not_the_report(collecting):
    policy.render(_table())
    with open(collecting, "a", encoding="utf-8") as f:
        f.write("2026-09-05T00:00:00Z\tad-td\tnot-a-number\ttable\t1\t1\t1\n")
        f.write("half a line with no tabs at all\n")
        f.write("\t".join(["x"] * 40) + "\n")
    policy.render(_table())
    assert len(metrics.read(str(collecting))) == 2


def test_the_file_is_utf8_without_bom_and_lf(collecting):
    """The same bytes every other file this repo writes has."""
    policy.render(_table())
    raw = collecting.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in raw
    assert raw.decode("utf-8").startswith("\t".join(metrics.COLUMNS))


def test_appending_keeps_what_earlier_runs_wrote(collecting):
    """Two commands in a row are two records, not the second replacing the first."""
    policy.render(_table())
    metrics.reset_cache()
    policy.render(_table(n=600))
    assert len(metrics.read(str(collecting))) == 2


# ------------------------------------------------------------------------------- the report


def test_the_summary_groups_by_rule_and_by_command(collecting):
    for source, n in (("ad-td q", 3), ("ad-td q", 600), ("ad-hive q", 600)):
        policy.render(_table(n=n, source=source))
    rows = {(g, k): rest for g, k, *rest in metrics.summary(metrics.read(str(collecting)))}
    assert rows[("rule", "6")][0] == 2
    assert rows[("rule", "4")][0] == 1
    assert rows[("command", "ad-td")][0] == 2
    assert rows[("command", "ad-hive")][0] == 1


def test_the_summary_reports_a_median_not_only_a_total():
    """The question these thresholds turn on is what a *typical* result costs. One enormous export
    moves a mean and answers nothing."""
    records = [{"ts": "t", "command": "ad-td", "rule": 4, "shape": "table", "rows": 1, "cols": 1,
                "est_tokens": n} for n in (10, 12, 14, 16, 100000)]
    row = next(r for r in metrics.summary(records) if r[:2] == ["rule", "4"])
    assert row[5] == 14 and row[6] == 100000     # median, max
    assert metrics.totals(records)["tokens_median"] == 14


def test_totals_of_nothing_is_a_count_of_nothing():
    assert metrics.totals([]) == {"records": 0}


# ---------------------------------------------------------------------------- the CLI


def test_ad_metrics_summary_goes_through_the_format_policy(collecting, capsys):
    """The point of the file is retuning those rules; a report that dodged them would be the one
    output nobody could compare with the rest."""
    policy.render(_table())
    metrics.reset_cache()
    assert cli_metrics.main(["summary"]) == 0
    out = capsys.readouterr().out
    assert "rule:" in out and "usage[" in out
    assert "ad-td" in out and "records: 1" in out


def test_the_report_does_not_record_itself(collecting, capsys):
    """It is a rendered result like any other, so it would — and `ad-metrics` rows would accumulate
    in the very file whose point is saying which commands are expensive."""
    policy.render(_table())
    metrics.reset_cache()
    for _ in range(3):
        cli_metrics.main(["summary"])
    capsys.readouterr()
    assert [r["command"] for r in metrics.read(str(collecting))] == ["ad-td"]


def test_ad_metrics_summary_says_how_to_turn_it_on_when_it_is_off(not_collecting, capsys):
    assert cli_metrics.main(["summary"]) == 0
    out = capsys.readouterr().out
    assert "recording: false" in out and "metrics" in out and "enabled" in out


def test_ad_metrics_summary_distinguishes_on_but_empty_from_off(collecting, capsys):
    assert cli_metrics.main(["summary"]) == 0
    out = capsys.readouterr().out
    assert "recording: true" in out and "nothing has been rendered yet" in out


def test_ad_metrics_path_reports_where_and_whether(collecting, capsys):
    assert cli_metrics.main(["path"]) == 0
    out = capsys.readouterr().out
    assert "recording: true" in out and "metrics.tsv" in out and "exists: false" in out


def test_ad_metrics_clear_refuses_without_yes_because_it_is_the_only_copy(collecting, capsys):
    policy.render(_table())
    metrics.reset_cache()
    assert cli_metrics.main(["clear"]) == 2
    assert "--yes" in capsys.readouterr().out
    assert collecting.exists()

    assert cli_metrics.main(["clear", "--yes"]) == 0
    assert "removed: 1" in capsys.readouterr().out
    assert not collecting.exists()


def test_ad_metrics_clear_on_a_file_that_is_not_there_is_not_an_error(collecting, capsys):
    assert cli_metrics.main(["clear", "--yes"]) == 0
    assert "nothing to remove" in capsys.readouterr().out
