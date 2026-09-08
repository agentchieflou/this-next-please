"""The cross-project catalogue: what it indexes, what it refuses, and what it never opens.

Four fixture repositories stand in for the operator's parent folder, and every one of them has a
planted `.env`, `localSettings.json` and `secrets.json` sitting next to the files the catalogue is
allowed to read — plus a `~/.pncli/config.json` in the temporary home. The open-recording fixture
below wraps `builtins.open` and the suite asserts on the *set of files that were actually opened*,
because "the allow-list is a constant at the top of the module" is a comment and this is a test.

No real repository, no network, no `git` binary: the git facts come from `.git/HEAD` and the ref it
names, which are the two files the epic's allow-list permits.
"""
from __future__ import annotations
import builtins
import json
import os
import sqlite3
import time

import pytest

from agentdata.fleet import catalogue as K
from agentdata.fleet.catalogue import Catalogue, CatalogueError, looks_like_a_credential
from agentdata.fleet.registry import Repo


# ------------------------------------------------------------------------------- the fixtures


PLANTED = {
    ".env": "JIRA_TOKEN=ghp_thisisnotarealtokenatall000000\n",
    "localSettings.json": '{"password": "hunter2"}\n',
    "secrets.json": '{"client_secret": "s3cr3t-value-here"}\n',
    ".agent/secrets.json": '{"token": "abc123abc123abc123"}\n',
    ".agent/out/RDSD-22449-findings.tsv": "a\tb\n1\t2\n",
    "src/etl.py": "PASSWORD = 'hunter2'\n",
}


def _write(root: str, rel: str, text: str) -> str:
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def make_repo(root, name: str, *, facts: str = "", state: dict | None = None,
              friction: dict | None = None, pbip: dict | None = None,
              branch: str = "main", agents_extra: str = "") -> str:
    """A folder shaped like something `ad-setup --project` produced, plus the traps."""
    path = os.path.join(str(root), name)
    _write(path, "AGENTS.md", f"# Project: {name}\n\n## Project facts\n{facts}\n{agents_extra}")
    _write(path, ".agent/state.json", json.dumps(state or {"project": name, "phase": "idle"}))
    for rel, body in (friction or {}).items():
        _write(path, f".agent/friction/{rel}", body)
    for rel, body in (pbip or {}).items():
        _write(path, f".agent/pbip/{rel}", body)
    if branch:
        _write(path, ".git/HEAD", f"ref: refs/heads/{branch}\n")
        _write(path, f".git/refs/heads/{branch}", "9f1c0a2b3d4e5f60718293a4b5c6d7e8f9a0b1c2\n")
    for rel, body in PLANTED.items():
        _write(path, rel, body)
    return path


FRICTION = """---
project: RDSD
ticket: RDSD-22449
skill_in_use: pbip-model
type: ambiguity
severity: blocker
model: test
---
## What I was doing
Reconciling the Velocity release gate.
## Where I got stuck
The acceptance criteria name two different sprint tables.
## What I tried
- ad-jira sprints --board 42
## What would unblock me
Which sprint table is authoritative for the gate.
"""

REPORT_MD = """# Report: RDSD - Crew Level Reporting

## Pages
- Velocity — committed vs completed points by sprint
- Burndown — remaining points by day

## Fields used on Velocity
'Sprint'[SprintName], [Committed Points], [Completed Points]
"""

MODEL_MD = """# Model: Crew Level Reporting

## Measures
- Committed Points
- Completed Points
"""

LINEAGE_MD = "# Lineage\n\nSprint <- DL_JIRA.JIRA_SPRINT\n"


@pytest.fixture()
def folder(tmp_path, monkeypatch):
    """Four repositories under one parent folder, and a `~/.pncli/config.json` beside them."""
    monkeypatch.delenv(K.NO_FTS_ENV, raising=False)   # the default path is FTS5 where it exists
    root = tmp_path / "projects"
    root.mkdir()
    _write(str(tmp_path / "home"), ".pncli/config.json",
           '{"auth": {"jira": {"token": "ghp_notarealtoken00000000000000"}}}\n')

    make_repo(root, "rdsd-pbi-reporting",
              facts="- jira_project: RDSD\n- jira_board_id: 42\n- pbi_workspace: RDSD Reporting\n"
                    "- confluence_space: RDSD\n",
              state={"project": "RDSD", "phase": "building", "active_ticket": "RDSD-22449",
                     "branch": "feature/velocity-gate",
                     "pr_url": "https://bitbucket/pr/7", "open_questions": ["which sprint table"],
                     "artifacts": [".agent/out/RDSD-22449-findings.tsv"]},
              friction={"20260907T1010-pbip-model.md": FRICTION},
              pbip={"Velocity/REPORT.md": REPORT_MD, "Velocity/MODEL.md": MODEL_MD,
                    "Velocity/LINEAGE.md": LINEAGE_MD,
                    "Velocity/meta.json": json.dumps(
                        {"sources": {"C:/repos/rdsd/Model.SemanticModel/definition/model.tmdl": "ab"}})},
              branch="feature/velocity-gate")

    # a second repo that says the word "velocity" once, so the ranking test is a real contest
    make_repo(root, "cef-margin",
              facts="- jira_project: CEF\n- jira_board_id: 7\n",
              state={"project": "CEF", "phase": "idle", "active_ticket": "CEF-100"},
              agents_extra="\nSprint velocity is tracked by the RDSD team, not here.\n")

    make_repo(root, "admin-tools",
              facts="- jira_project: ADM\n",
              state={"project": "ADM", "phase": "idle"})

    make_repo(root, "leaky",
              facts="- jira_project: LEAK\n",
              state={"project": "LEAK", "phase": "idle"},
              agents_extra="\nCall the API with `Authorization: Bearer x` and it works.\n")
    return str(root)


def repos(folder: str) -> list[Repo]:
    return [Repo(name=n, path=os.path.join(folder, n))
            for n in sorted(os.listdir(folder))]


@pytest.fixture()
def cat(tmp_path):
    c = Catalogue.open(str(tmp_path / "catalogue.sqlite"))
    yield c
    c.close()


@pytest.fixture()
def opened(monkeypatch):
    """Every path handed to `builtins.open`, so a test can assert on what was *not* read."""
    seen: list[str] = []
    real = builtins.open

    def recording(file, *a, **kw):
        try:
            seen.append(os.path.abspath(os.fspath(file)))
        except TypeError:                        # a file descriptor, not a path
            pass
        return real(file, *a, **kw)

    monkeypatch.setattr(builtins, "open", recording)
    return seen


def under(paths: list[str], root: str) -> set[str]:
    """The recorded opens that landed inside `root`, as forward-slashed relative paths."""
    root = os.path.abspath(root)
    return {os.path.relpath(p, root).replace("\\", "/")
            for p in paths if os.path.abspath(p).startswith(root + os.sep)}


# ------------------------------------------------------------------- the allow-list, in the small


def test_the_allow_list_names_the_kinds_the_epic_fixed():
    assert K.ALLOWED_KINDS == ("agents", "state", "friction", "pbip_model", "pbip_report",
                               "pbip_lineage", "pbip_meta", "git")


@pytest.mark.parametrize("rel,kind", [
    ("AGENTS.md", "agents"),
    (".agent/state.json", "state"),
    (".agent/friction/20260907T1010-pbip.md", "friction"),
    (".agent/pbip/Velocity/MODEL.md", "pbip_model"),
    (".agent/pbip/Velocity/REPORT.md", "pbip_report"),
    (".agent/pbip/Velocity/LINEAGE.md", "pbip_lineage"),
    (".agent/pbip/Velocity/meta.json", "pbip_meta"),
    (".git/HEAD", "git"),
    (".git/refs/heads/main", "git"),
])
def test_every_allowed_kind_has_exactly_one_shape(rel, kind):
    assert K.allows(rel) == kind
    assert kind in K.ALLOWED_KINDS


@pytest.mark.parametrize("rel", [
    ".env", "localSettings.json", "secrets.json", ".agent/secrets.json", ".git/config",
    ".agent/out/RDSD-22449-findings.tsv", "src/etl.py", "AGENTS.md.bak", "agents.md",
    ".agent/friction/notes.txt", ".agent/pbip/Velocity/normalized.json",
    ".agent/pbip/Velocity/deep/MODEL.md", ".agent/pbip/../../.env", "../.env",
    "/etc/passwd", "C:/Users/x/.pncli/config.json", "", ".",
])
def test_everything_else_is_refused_by_the_allow_list(rel):
    assert K.allows(rel) == ""


def test_reading_off_the_allow_list_is_impossible_not_merely_unwise(tmp_path):
    """`_read` is the module's only door into a repository, and it checks the name, not the caller."""
    _write(str(tmp_path), ".env", "TOKEN=x\n")
    with pytest.raises(ValueError) as e:
        K._read(str(tmp_path), ".env")
    assert "allow-list" in str(e.value)


# ------------------------------------------------------------------------------- indexing


def test_four_repos_index_in_under_two_seconds(folder, cat):
    out = cat.index(repos(folder))
    assert out["projects"] == 4
    assert out["docs"] >= 4 * 3
    assert out["elapsed"] < 2.0, out["elapsed"]
    assert out["fts"] is cat.fts
    assert cat.stats()["projects"] == 4


def test_the_index_opens_only_allow_listed_names(folder, cat, opened):
    cat.index(repos(folder))
    for name in sorted(os.listdir(folder)):
        touched = under(opened, os.path.join(folder, name))
        assert touched, name
        for rel in sorted(touched):
            assert K.allows(rel) != "", f"{name}/{rel} was opened but is not on the allow-list"


def test_a_planted_credential_file_is_never_opened(folder, cat, opened, tmp_path):
    """The three files the operator's laptop actually has, and the one in their home directory."""
    cat.index(repos(folder))
    forbidden = ("/.env", "/localSettings.json", "/secrets.json", "/.pncli/config.json",
                 "/etl.py", "/RDSD-22449-findings.tsv")
    for path in opened:
        norm = path.replace("\\", "/")
        assert not norm.endswith(forbidden), f"{norm} was opened"
    home = str(tmp_path / "home").replace("\\", "/")
    assert not [p for p in opened if p.replace("\\", "/").startswith(home + "/.pncli")]


def test_a_repo_that_moved_away_is_skipped_and_the_rest_still_index(folder, cat):
    listed = repos(folder) + [Repo(name="gone", path=os.path.join(folder, "not-here"))]
    out = cat.index(listed)
    assert out["projects"] == 4 and out["skipped"] == 1
    assert out["skipped_repos"][0]["project"] == "gone"
    assert "ad-fleet repo remove gone" in out["skipped_repos"][0]["hint"]


def test_a_file_that_will_not_parse_is_reported_and_the_repo_still_indexes(folder, cat):
    _write(os.path.join(folder, "admin-tools"), ".agent/state.json", "{not json at all")
    out = cat.index(repos(folder))
    assert out["projects"] == 4
    bad = [p for p in out["problems"] if p["project"] == "admin-tools"]
    assert bad and bad[0]["path"] == ".agent/state.json"
    assert "admin-tools" in bad[0]["hint"]
    assert cat.show("admin-tools")["facts"]["jira_project"] == "ADM"


def test_a_registry_can_be_handed_straight_to_index(folder, cat, tmp_path, monkeypatch):
    from agentdata.fleet import registry as R

    monkeypatch.setenv(R.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    reg = R.Registry()
    reg.add(os.path.join(folder, "rdsd-pbi-reporting"), name="rdsd")
    out = cat.index(reg)
    assert out["projects"] == 1
    assert cat.show("rdsd")["jira_project"] == "RDSD"


# ------------------------------------------------------------------------------- incremental


def touch(path: str, text: str | None = None) -> None:
    """Rewrite a file and move its mtime forward, so a same-second edit is still a change."""
    if text is not None:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    later = time.time() + 5
    os.utime(path, (later, later))


def test_a_second_index_reads_nothing_and_touching_one_file_reads_one_doc(folder, cat):
    first = cat.index(repos(folder))
    assert first["docs"] > 0

    second = cat.index(repos(folder))
    assert second["docs"] == 0, "an unchanged folder must not be re-read"
    assert second["unchanged"] == first["docs"]

    touch(os.path.join(folder, "cef-margin", ".agent", "state.json"),
          json.dumps({"project": "CEF", "phase": "review", "active_ticket": "CEF-101"}))
    third = cat.index(repos(folder))
    assert third["docs"] == 1, third
    assert cat.show("cef-margin")["state"]["active_ticket"] == "CEF-101"


def test_rebuild_re_reads_everything(folder, cat):
    first = cat.index(repos(folder))
    again = cat.index(repos(folder), rebuild=True)
    assert again["docs"] == first["docs"] and again["unchanged"] == 0


def test_a_commit_re_indexes_the_git_doc_even_though_HEAD_did_not_change(folder, cat):
    """`git commit` rewrites `.git/refs/heads/<branch>`, never `.git/HEAD`."""
    cat.index(repos(folder))
    assert cat.index(repos(folder))["docs"] == 0
    touch(os.path.join(folder, "admin-tools", ".git", "refs", "heads", "main"),
          "1111111111111111111111111111111111111111\n")
    out = cat.index(repos(folder))
    assert out["docs"] == 1
    assert "admin-tools" in [r["project"] for r in cat.where("main") if r["kind"] == "git"]
    row = cat.conn.execute("SELECT text FROM doc WHERE project='admin-tools' AND kind='git'"
                           ).fetchone()
    assert "111111111111" in row["text"]


def test_a_deleted_friction_file_leaves_the_catalogue(folder, cat):
    cat.index(repos(folder))
    assert cat.show("rdsd-pbi-reporting")["friction"]
    os.remove(os.path.join(folder, "rdsd-pbi-reporting", ".agent", "friction",
                           "20260907T1010-pbip-model.md"))
    out = cat.index(repos(folder))
    assert out["removed"] == 1
    assert cat.show("rdsd-pbi-reporting")["friction"] == []


# ------------------------------------------------------------------------------- searching


def test_where_velocity_ranks_the_report_that_names_the_page_first(folder, cat):
    cat.index(repos(folder))
    hits = cat.where("velocity")
    assert hits, "velocity is in a REPORT.md, a friction file and an AGENTS.md"
    assert hits[0]["project"] == "rdsd-pbi-reporting"
    assert hits[0]["kind"].startswith("pbip_")
    assert "Velocity" in hits[0]["snippet"] or "Velocity" in hits[0]["title"]
    assert [h["project"] for h in hits].count("rdsd-pbi-reporting") == 1, "one row per project"


def test_where_a_ticket_key_finds_the_repo_whose_state_holds_it(folder, cat):
    cat.index(repos(folder))
    hits = cat.where("RDSD-22449")
    assert hits[0]["project"] == "rdsd-pbi-reporting"
    assert "RDSD-22449" in hits[0]["snippet"]


def test_a_friction_snippet_carries_its_type_and_date(folder, cat):
    cat.index(repos(folder))
    hits = [h for h in cat.where("sprint tables") if h["kind"] == "friction"]
    assert hits, [h["kind"] for h in cat.where("sprint tables")]
    assert "ambiguity" in hits[0]["snippet"]
    assert "2026-09-07" in hits[0]["snippet"]


def test_a_query_full_of_fts5_syntax_is_a_search_not_an_error(folder, cat):
    """`where RDSD-22449` and `where velocity*` are both things an operator types."""
    cat.index(repos(folder))
    for query in ("RDSD-22449", "velocity*", "(velocity", 'say "hello"', "a OR b", "-x"):
        assert isinstance(cat.where(query), list)


def test_an_empty_query_finds_nothing_rather_than_everything(folder, cat):
    cat.index(repos(folder))
    assert cat.where("") == [] and cat.where("   ") == []


def test_limit_is_honoured(folder, cat):
    cat.index(repos(folder))
    assert len(cat.where("jira", limit=2)) <= 2


# ------------------------------------------------------------------------- the LIKE fallback


def test_the_like_fallback_returns_the_same_top_hit_as_fts5(folder, tmp_path):
    """CI forces the fallback the laptop's Python 3.14 will never take, and compares the two."""
    fast = Catalogue.open(str(tmp_path / "fts.sqlite"), fts=True)
    slow = Catalogue.open(str(tmp_path / "like.sqlite"), fts=False)
    try:
        if not fast.fts:
            pytest.skip("this interpreter's SQLite has no FTS5, so there is nothing to compare")
        assert slow.fts is False
        fast.index(repos(folder))
        slow.index(repos(folder))
        for query in ("velocity", "RDSD-22449", "burndown", "sprint tables"):
            a, b = fast.where(query), slow.where(query)
            assert [h["project"] for h in a][:1] == [h["project"] for h in b][:1], query
            assert {h["project"] for h in a} == {h["project"] for h in b}, query
    finally:
        fast.close()
        slow.close()


def test_the_env_var_forces_the_fallback(folder, tmp_path, monkeypatch):
    monkeypatch.setenv(K.NO_FTS_ENV, "1")
    c = Catalogue.open(str(tmp_path / "c.sqlite"))
    try:
        assert c.fts is False
        assert c.index(repos(folder))["fts"] is False
        assert c.stats()["fts"] is False
        assert c.where("velocity")[0]["project"] == "rdsd-pbi-reporting"
    finally:
        c.close()


def test_a_catalogue_built_on_the_fallback_is_rebuilt_when_fts5_returns(folder, tmp_path):
    """Otherwise the FTS table is empty and every search silently answers nothing."""
    path = str(tmp_path / "c.sqlite")
    slow = Catalogue.open(path, fts=False)
    slow.index(repos(folder))
    slow.close()

    fast = Catalogue.open(path, fts=True)
    try:
        if not fast.fts:
            pytest.skip("no FTS5 in this interpreter's SQLite")
        assert fast.stats()["docs"] == 0, "the stale rows must go, not be searched with an empty index"
        fast.index(repos(folder))
        assert fast.where("velocity")[0]["project"] == "rdsd-pbi-reporting"
    finally:
        fast.close()


def test_the_search_mode_is_visible_to_the_doctor_row(folder, cat):
    cat.index(repos(folder))
    stats = cat.stats()
    assert stats["fts"] in (True, False)
    assert stats["path"].endswith("catalogue.sqlite")
    assert stats["kinds"]["state"] == 4


# ---------------------------------------------------------------------- the credential refusal


def test_a_bearer_line_makes_the_index_refuse_that_doc_and_say_so(folder, cat):
    out = cat.index(repos(folder))
    refused = [r for r in out["refused"] if r["project"] == "leaky"]
    assert refused, out["refused"]
    assert refused[0]["path"] == "AGENTS.md" and refused[0]["pattern"] == "bearer"
    assert "re-run `ad-fleet index`" in refused[0]["hint"]
    assert "Bearer" not in json.dumps(out), "the refusal must not carry the line it refused"
    assert cat.where("Bearer") == []
    assert cat.show("leaky")["project"] == "leaky", "the repo is still catalogued"


def test_no_indexed_text_anywhere_carries_a_credential_shape(folder, cat):
    """The catalogue-wide sweep the epic asks for: every stored doc, every stored fact."""
    cat.index(repos(folder))
    rows = cat.conn.execute("SELECT project, path, title, text FROM doc").fetchall()
    assert rows
    for row in rows:
        found = looks_like_a_credential(f"{row['title']}\n{row['text']}")
        assert found is None, f"{row['project']}/{row['path']} carries a {found}"
    for row in cat.conn.execute("SELECT name, facts FROM project"):
        assert looks_like_a_credential(row["facts"] or "") is None, row["name"]


def test_a_refused_doc_is_dropped_from_a_catalogue_that_already_had_it(folder, cat):
    clean = os.path.join(folder, "admin-tools", "AGENTS.md")
    cat.index(repos(folder))
    assert cat.where("ADM")

    touch(clean, "# Project: admin-tools\n\n- jira_project: ADM\n- jira_token: abcdef123456\n")
    out = cat.index(repos(folder))
    assert [r["pattern"] for r in out["refused"] if r["project"] == "admin-tools"] == ["token"]
    assert cat.conn.execute("SELECT COUNT(*) n FROM doc WHERE project='admin-tools' "
                            "AND kind='agents'").fetchone()["n"] == 0


@pytest.mark.parametrize("text,pattern", [
    ("Authorization: Bearer x", "bearer"),
    ("- jira_token: abcdef123456", "token"),
    ("password = hunter2", "password"),
    ("client_secret: s3cr3t-value", "client_secret"),
    ("API_KEY=abcdef123456", "api_key"),
])
def test_looks_like_a_credential_names_the_pattern(text, pattern):
    assert looks_like_a_credential(text) == pattern


@pytest.mark.parametrize("text", [
    "- jira_project: RDSD",
    "- jira_token: <set in pncli>",            # the stub `ad-setup --project` writes
    "- pncli.keys.jira_token: auth.jira.token",  # a key *name*, which is what AGENTS.md should say
    "- pbi_workspace: RDSD Reporting",
    "",
])
def test_looks_like_a_credential_leaves_ordinary_facts_alone(text):
    assert looks_like_a_credential(text) is None


def test_a_refusal_never_carries_the_value(folder, cat):
    """The one thing a refusal must not do is copy the credential into the report it prints."""
    touch(os.path.join(folder, "admin-tools", "AGENTS.md"),
          "# admin-tools\n\n- jira_token: ghp_averyrecognisablesecret123\n")
    out = cat.index(repos(folder))
    assert "averyrecognisablesecret" not in json.dumps(out)


# ------------------------------------------------------------------------------------ show


def test_show_returns_the_facts_state_friction_pbip_and_link_facts(folder, cat):
    cat.index(repos(folder))
    shown = cat.show("rdsd-pbi-reporting")

    assert shown["jira_project"] == "RDSD"
    assert shown["branch"] == "feature/velocity-gate"
    assert shown["facts"]["pbi_workspace"] == "RDSD Reporting"
    assert shown["state"]["active_ticket"] == "RDSD-22449"
    assert shown["state"]["open_questions"] == ["which sprint table"]

    assert [f["type"] for f in shown["friction"]] == ["ambiguity"]
    assert shown["friction"][0]["date"] == "2026-09-07"
    assert "sprint table" in shown["friction"][0]["unblock"]

    assert [p["name"] for p in shown["pbip"]] == ["Velocity"]
    assert "Crew Level Reporting" in shown["pbip"][0]["report"]
    assert shown["pbip"][0]["model"].startswith("Model:")
    assert shown["pbip"][0]["sources"], "meta.json names the TMDL it was projected from"

    links = shown["links"]
    assert links["jira_project"] == "RDSD" and links["jira_board_id"] == "42"
    assert links["active_ticket"] == "RDSD-22449"
    assert links["pr_url"] == "https://bitbucket/pr/7"
    assert links["branch"] == "feature/velocity-gate"


def test_a_branch_name_with_a_slash_survives(folder, cat):
    """`refs/heads/feature/velocity-gate` is one branch, not a folder and a branch."""
    cat.index(repos(folder))
    assert cat.show("rdsd-pbi-reporting")["branch"] == "feature/velocity-gate"
    assert cat.show("admin-tools")["branch"] == "main"


def test_show_hands_the_tile_only_the_link_facts_it_needs(folder, cat):
    """A tile renders in a browser; the whole fact block would put share paths on a web page."""
    cat.index(repos(folder))
    links = cat.show("rdsd-pbi-reporting")["links"]
    assert set(links) == set(K.LINK_FACTS) | set(K.LINK_STATE) | {"branch"}


def test_show_names_the_projects_that_are_indexed_when_asked_for_one_that_is_not(folder, cat):
    cat.index(repos(folder))
    with pytest.raises(CatalogueError) as e:
        cat.show("nope")
    assert "cef-margin" in e.value.hint
    assert "ad-fleet index" in e.value.hint


def test_show_on_an_empty_catalogue_says_so(cat):
    with pytest.raises(CatalogueError) as e:
        cat.show("anything")
    assert "nothing indexed yet" in e.value.hint


# ------------------------------------------------------------------------- where it all lives


def test_the_catalogue_lives_under_the_fleet_directory(tmp_path, monkeypatch, folder):
    from agentdata.fleet import registry as R

    monkeypatch.setenv(R.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    c = Catalogue.open()
    try:
        c.index(repos(folder))
        assert c.path.replace("\\", "/").endswith("fleet/catalogue.sqlite")
        assert os.path.isfile(c.path)
    finally:
        c.close()
    # nothing was written into any repository
    for name in os.listdir(folder):
        assert not os.path.exists(os.path.join(folder, name, ".agent", "catalogue.sqlite"))


def test_the_index_writes_nothing_into_a_repository(folder, cat):
    before = {}
    for name in sorted(os.listdir(folder)):
        root = os.path.join(folder, name)
        before[name] = {os.path.relpath(os.path.join(d, f), root)
                        for d, _dirs, files in os.walk(root) for f in files}
    cat.index(repos(folder))
    for name, files in before.items():
        root = os.path.join(folder, name)
        after = {os.path.relpath(os.path.join(d, f), root)
                 for d, _dirs, files_ in os.walk(root) for f in files_}
        assert after == files, name


def test_the_connection_survives_a_second_thread(folder, cat):
    """`ad-fleet serve` answers SSE and search on different threads of one process."""
    import threading

    cat.index(repos(folder))
    out: list = []
    t = threading.Thread(target=lambda: out.append(cat.where("velocity")))
    t.start()
    t.join(10)
    assert out and out[0][0]["project"] == "rdsd-pbi-reporting"


def test_close_is_safe_and_the_file_is_a_plain_sqlite_database(folder, tmp_path):
    path = str(tmp_path / "c.sqlite")
    c = Catalogue.open(path)
    c.index(repos(folder))
    c.close()
    conn = sqlite3.connect(path)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"project", "doc", "meta"} <= names
    finally:
        conn.close()
