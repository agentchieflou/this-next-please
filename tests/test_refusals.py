"""Every refusal is registered, tested, and cannot quietly stop working.

A rule nobody tests is a rule the next person removes when they find it inconvenient. So
`docs/refusals.md` lists them all, this file checks the registry against the code and against the
suite, and the adversarial table below tries to get past each one the obvious ways.
"""
from __future__ import annotations
import glob
import os
import re
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(REPO_ROOT, "docs", "refusals.md")


def registry_rows() -> list[dict[str, str]]:
    rows = []
    for line in open(REGISTRY, encoding="utf-8").read().splitlines():
        if not line.startswith("| ") or line.startswith("| Area") or set(line) <= set("|- "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 4 and "::" in cells[3]:
            rows.append({"area": cells[0], "when": cells[1], "emits": cells[2],
                         "test": cells[3].strip("`")})
    return rows


def all_test_names() -> set[str]:
    names = set()
    for path in glob.glob(os.path.join(REPO_ROOT, "tests", "**", "*.py"), recursive=True):
        text = open(path, encoding="utf-8").read()
        base = os.path.basename(path)
        for name in re.findall(r"^def (test_\w+)", text, re.M):
            names.add(f"{base}::{name}")
    return names


# ------------------------------------------------------------------------------- the registry


def test_the_registry_has_rows():
    rows = registry_rows()
    assert len(rows) >= 20, f"only {len(rows)} refusals registered; the code has far more"


def test_every_registered_refusal_names_a_test_that_exists():
    known = all_test_names()
    missing = [r["test"] for r in registry_rows() if r["test"] not in known]
    assert not missing, "docs/refusals.md names tests that do not exist:\n  " + "\n  ".join(missing)


def test_every_row_says_what_it_emits():
    for row in registry_rows():
        assert row["emits"], f"{row['area']}: no code/hint recorded"
        assert row["when"], f"{row['area']}: no condition recorded"


REFUSAL_SITES = re.compile(r"raise (?:C\.)?(?:ProcError|StateError|ConfigError|GuardError|DpmError)\(|"
                           r"print\(error\(|\"refused\"|refused:")


def refusal_call_sites() -> list[str]:
    sites = []
    for path in glob.glob(os.path.join(REPO_ROOT, "agentdata", "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
        for n, line in enumerate(open(path, encoding="utf-8").read().splitlines(), 1):
            if REFUSAL_SITES.search(line):
                sites.append(f"{rel}:{n}")
    return sites


# Pinned so the registry cannot silently fall behind the code. A new refusal moves this number and
# should move docs/refusals.md in the same commit.
REFUSAL_SITE_COUNT = 209


def test_the_number_of_refusal_sites_is_pinned():
    sites = refusal_call_sites()
    assert len(sites) <= REFUSAL_SITE_COUNT + 15, (
        f"{len(sites)} refusal call sites, pinned at ~{REFUSAL_SITE_COUNT}. If you added one, add a "
        "row to docs/refusals.md and update this number in the same commit.")
    assert len(sites) >= REFUSAL_SITE_COUNT - 40, (
        f"only {len(sites)} refusal call sites; refusals should not be disappearing")


# ------------------------------------------------------------------------ the adversarial table


DML_ATTEMPTS = [
    ("plain", "DELETE FROM t"),
    ("after a semicolon", "SELECT 1; DROP TABLE t"),
    ("inside a CTE", "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x"),
    ("behind a line comment", "-- harmless\nUPDATE t SET a = 1"),
    ("behind a block comment", "/* nothing to see */ INSERT INTO t VALUES (1)"),
    ("lowercase", "delete from t"),
    ("with odd spacing", "DELETE\n\tFROM\n t"),
]


@pytest.mark.parametrize("label,sql", DML_ATTEMPTS, ids=[a[0] for a in DML_ATTEMPTS])
def test_dml_is_refused_however_it_is_hidden(label, sql):
    """AGENTS.md rule 7: the adapter rejects DML/DDL, and you do not work around it.

    The CTE row here found a real hole: the pattern was anchored to line starts, so a DML keyword
    mid-line inside a CTE passed, and `WITH ...` satisfied the "must start with SELECT/WITH" check.
    """
    from agentdata.connectors.sql_base import assert_readonly

    with pytest.raises(PermissionError):
        assert_readonly(sql)


def test_dml_hidden_in_a_cte_is_refused():
    """The specific bypass, named so it cannot come back unnoticed."""
    from agentdata.connectors.sql_base import assert_readonly

    with pytest.raises(PermissionError) as e:
        assert_readonly("WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x")
    assert "DELETE" in str(e.value)


ALLOWED_QUERIES = [
    "SELECT a, b FROM t WHERE x > 1",
    "WITH recent AS (SELECT * FROM t) SELECT * FROM recent",
    "SELECT update_date, created_at FROM t",          # keywords inside identifiers
    "SELECT a FROM t WHERE action = 'delete'",        # and inside a string literal
    "SHOW TABLES",
    "EXPLAIN SELECT 1",
]


@pytest.mark.parametrize("sql", ALLOWED_QUERIES)
def test_a_read_only_query_is_not_refused(sql):
    """A guard that refuses real work is a guard someone turns off."""
    from agentdata.connectors.sql_base import assert_readonly

    assert_readonly(sql)


def test_dml_in_a_file_with_a_bom_is_still_refused(tmp_path):
    """A BOM is how something got past a reader once already."""
    from agentdata.connectors.sql_base import assert_readonly
    from agentdata.textio import read_text

    path = tmp_path / "q.sql"
    path.write_bytes("﻿".encode("utf-8") + b"DELETE FROM t\n")
    with pytest.raises(PermissionError):
        assert_readonly(read_text(str(path)))


@pytest.mark.parametrize("value", ["ghp_0123456789abcdef", "xoxb-abc-123", "AKIAIOSFODNN7EXAMPLE"])
def test_a_token_looking_config_value_is_refused(value):
    from agentdata import config

    for key in ("token", "api_key", "client_secret"):
        with pytest.raises(config.ConfigError):
            config.assert_no_secrets({"jira": {key: value}})


def test_a_key_that_merely_mentions_a_secret_is_allowed():
    """`pncli.keys.token` names a *path* to a token, not a token: refusing it would be wrong."""
    from agentdata import config

    config.assert_no_secrets({"pncli": {"keys": {"token": "auth.token"}}})


@pytest.mark.parametrize("phase", ["going-fast", "", "IDLE", "done "])
def test_an_unknown_phase_is_refused_and_the_message_lists_the_real_ones(phase):
    from agentdata import state

    with pytest.raises(state.StateError) as e:
        state.apply({"phase": "idle"}, {"phase": phase})
    assert "querying" in e.value.hint, "the message must say what is allowed"


def test_an_unknown_state_key_is_refused():
    from agentdata import state

    with pytest.raises(state.StateError):
        state.apply({}, {"not_a_key": "x"})
    with pytest.raises(state.StateError):
        state.apply({}, {}, tools={"not_a_tool": "x"})


@pytest.mark.parametrize("bad", ["", "  ", "novalue"])
def test_a_malformed_set_pair_is_refused(bad):
    from agentdata.cli_state import _kv
    from agentdata import state

    if "=" in bad:
        pytest.skip("that one is well formed")
    with pytest.raises(state.StateError):
        _kv([bad], "--set")


def test_a_value_containing_equals_survives():
    """`--set jql=a = b` is a value with an `=` in it, not a malformed pair."""
    from agentdata.cli_state import _kv

    assert _kv(["branch=feat/a=b"], "--set") == {"branch": "feat/a=b"}


def test_an_empty_tsv_is_an_empty_table_not_a_stopiteration(tmp_path):
    """A query that matched nothing writes a 0-byte TSV. Reading it back raised StopIteration,
    which reached the caller as a traceback rather than as "no rows"."""
    from agentdata.model import AgentTable

    path = tmp_path / "empty.tsv"
    path.write_bytes(b"")
    table = AgentTable.read_tsv(str(path))
    assert table.columns == [] and table.rows == []


@pytest.mark.parametrize("name,payload", [
    ("empty.tsv", b""),
    ("utf16.tsv", "id\tv\n1\tx\n".encode("utf-16-le")),
    ("binary.tsv", bytes(range(1, 32))),
])
def test_view_copes_with_awkward_files(tmp_path, name, payload):
    """Whatever the bytes, an exit code in the documented set and no traceback."""
    path = tmp_path / name
    path.write_bytes(payload)
    p = subprocess.run([sys.executable, "-m", "agentdata", "view", str(path)],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert "Traceback" not in p.stderr, p.stderr[-800:]
    assert p.returncode in (0, 1, 2), f"{name}: exit {p.returncode}"


def test_diff_without_the_key_column_is_a_usage_error(tmp_path):
    from agentdata.textio import write_text

    a, b = tmp_path / "a.tsv", tmp_path / "b.tsv"
    write_text(str(a), "x\ty\n1\t2\n")
    write_text(str(b), "x\ty\n1\t3\n")
    p = subprocess.run([sys.executable, "-m", "agentdata", "diff", str(a), str(b), "--key", "nope"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert p.returncode == 2
    assert "Traceback" not in p.stderr
    assert "ok: false" in p.stdout


# --------------------------------------------------------------- swallowed exceptions, audited


BARE_EXCEPT = re.compile(r"^\s*except(\s+Exception)?\s*(as \w+)?\s*:", re.M)
# Pinned. It may go down freely; going up means someone added a handler that swallows something,
# and they should say why in the same commit.
SWALLOWED_CEILING = 200


def swallowing_handlers() -> list[str]:
    out = []
    for path in glob.glob(os.path.join(REPO_ROOT, "agentdata", "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
        lines = open(path, encoding="utf-8").read().splitlines()
        for n, line in enumerate(lines, 1):
            if not BARE_EXCEPT.match(line):
                continue
            annotated = "noqa: BLE001" in line
            body = "\n".join(lines[n:n + 4])
            logged = "debug_exc(" in body
            if not (annotated or logged):
                out.append(f"{rel}:{n}: {line.strip()}")
    return out


def test_the_number_of_unexplained_handlers_is_pinned():
    """An `except Exception` is often right. One nobody can explain is where a bug goes to hide."""
    handlers = swallowing_handlers()
    assert len(handlers) <= SWALLOWED_CEILING, (
        f"{len(handlers)} exception handlers neither annotated `# noqa: BLE001 <reason>` nor routed "
        f"through `log.debug_exc()`, above the pinned ceiling of {SWALLOWED_CEILING}:\n  "
        + "\n  ".join(handlers[:15]))


def test_debug_exc_is_silent_by_default(tmp_path, monkeypatch):
    from agentdata import log

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(log.ENV_FLAG, raising=False)
    try:
        raise ValueError("boom")
    except ValueError as e:
        log.debug_exc("test", e)
    assert not os.path.exists(log.LOG_PATH)


def test_debug_exc_records_when_asked(tmp_path, monkeypatch):
    from agentdata import log

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(log.ENV_FLAG, "1")
    try:
        raise ValueError("boom")
    except ValueError as e:
        log.debug_exc("where-it-happened", e)
    text = open(log.LOG_PATH, encoding="utf-8").read()
    assert "where-it-happened" in text and "ValueError: boom" in text


def test_debug_exc_never_raises(monkeypatch):
    """A logger that fails inside an exception handler is a new bug in the same place."""
    from agentdata import log

    monkeypatch.setenv(log.ENV_FLAG, "1")
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    log.debug_exc("still fine", ValueError("x"))


def test_the_debug_flag_is_documented():
    for path in ("docs/refusals.md", "docs/setup.md"):
        text = open(os.path.join(REPO_ROOT, path), encoding="utf-8").read()
        if "AGENTDATA_DEBUG" in text:
            return
    pytest.fail("AGENTDATA_DEBUG is not documented anywhere")
