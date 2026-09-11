"""Handoff: D — scope in the page (issue #166).

A file dropped on a tile used to light the tile up and do nothing. It is resolved to the checkout by
its git blob hash now, and nothing but that hash leaves the browser until the operator clicks
*attach a copy*.
"""
from __future__ import annotations
import base64
import json
import os
import subprocess
import threading

import pytest

from agentdata.fleet import events as E, handoff as H, registry, scope as SC, serve as S
from agentdata.fleet.registry import Registry

from test_fleet import make_project
from test_fleet_desk_browser import launch_chromium


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(tmp_path / "fleet"))
    return tmp_path / "fleet"


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _checkout(tmp_path, name="luna"):
    """A registered checkout that is a real git repository, with one ignored file in it."""
    repo = make_project(tmp_path / name, ticket="RDSD-118")
    os.makedirs(os.path.join(repo, "models"), exist_ok=True)
    os.makedirs(os.path.join(repo, "copy"), exist_ok=True)
    _write(repo, "models/Velocity.tmdl", "table Velocity\n  measure Rate = 1\n")
    _write(repo, "copy/Velocity.tmdl", "table Velocity\n  measure Rate = 1\n")   # the same bytes
    _write(repo, ".gitignore", ".env\nsecrets.json\n")
    _write(repo, ".env", "TOKEN=not-for-an-agent\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "first")
    _write(repo, "notes.md", "written but never committed\n")
    Registry().add(repo, name=name)
    return repo


def _write(repo, rel, body):
    path = os.path.join(repo, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(body)
    return path


def _sha(repo, rel):
    with open(os.path.join(repo, rel.replace("/", os.sep)), "rb") as handle:
        return SC.blob_sha(handle.read())


# -------------------------------------------------------------------------------- the resolution


def test_the_hash_is_the_one_git_itself_would_give(fleet_home, tmp_path):
    """If this drifts from git, every resolution drifts with it."""
    repo = _checkout(tmp_path)
    got = _git(repo, "hash-object", "models/Velocity.tmdl")
    assert got.returncode == 0, got.stderr
    assert _sha(repo, "models/Velocity.tmdl") == got.stdout.strip()


def test_a_dropped_copy_resolves_to_the_checkouts_own_path(fleet_home, tmp_path):
    """Acceptance criterion: bytes equal to a tracked file resolve to its repo-relative path."""
    repo = _checkout(tmp_path)
    [row] = SC.resolve(repo, [{"name": "Velocity.tmdl", "size": 34,
                               "sha": _sha(repo, "models/Velocity.tmdl")}])
    # The same content is at two paths here, so this is honestly a pick rather than a guess.
    assert row["status"] == SC.AMBIGUOUS
    assert sorted(row["paths"]) == ["copy/Velocity.tmdl", "models/Velocity.tmdl"]
    assert row["how"] == SC.BY_HASH

    _git(repo, "rm", "-q", "copy/Velocity.tmdl")
    [row] = SC.resolve(repo, [{"name": "Velocity.tmdl", "size": 34,
                               "sha": _sha(repo, "models/Velocity.tmdl")}])
    assert row["status"] == SC.RESOLVED
    assert row["paths"] == ["models/Velocity.tmdl"]


def test_an_untracked_file_resolves_and_a_different_content_does_not(fleet_home, tmp_path):
    repo = _checkout(tmp_path)
    [fresh] = SC.resolve(repo, [{"name": "notes.md", "size": 28, "sha": _sha(repo, "notes.md")}])
    assert fresh["status"] == SC.RESOLVED, "untracked-but-not-ignored is part of the checkout"

    [other] = SC.resolve(repo, [{"name": "notes.md", "size": 3, "sha": "0" * 40}])
    assert other["status"] == SC.UNMATCHED
    assert "different" in other["why"]


def test_a_git_ignored_file_can_never_resolve(fleet_home, tmp_path):
    """Acceptance criterion: an ignored file never resolves, even when its bytes are dropped.

    Not by a rule that could be relaxed: `git ls-files --others --exclude-standard` does not list
    it, so it is not in the candidate set at all.
    """
    repo = _checkout(tmp_path)
    assert ".env" not in SC.candidates(repo)
    [row] = SC.resolve(repo, [{"name": ".env", "size": 25, "sha": _sha(repo, ".env")}])
    assert row["status"] == SC.UNMATCHED
    assert row["paths"] == []


def test_a_file_too_large_to_hash_is_matched_by_name_and_says_so(fleet_home, tmp_path):
    """The weaker claim is labelled as one, the way adoption labels its two."""
    repo = _checkout(tmp_path)
    size = os.path.getsize(os.path.join(repo, "notes.md"))
    [row] = SC.resolve(repo, [{"name": "notes.md", "size": size, "sha": ""}])
    assert row["status"] == SC.RESOLVED and row["how"] == SC.BY_NAME
    assert "too large to fingerprint" in row["why"]
    # A same-named file of a different size is not the same file.
    [miss] = SC.resolve(repo, [{"name": "notes.md", "size": 999_999, "sha": ""}])
    assert miss["status"] == SC.UNMATCHED


# ------------------------------------------------------------------------------- writing a scope


def test_the_scope_lands_only_under_agent_in_and_is_an_event(fleet_home, tmp_path):
    repo = _checkout(tmp_path)
    ev = SC.add("luna", repo, "RDSD-118", ["models/Velocity.tmdl"], why="dropped on the tile")
    assert ev["kind"] == "scope.added"
    assert ev["data"]["paths"] == ["models/Velocity.tmdl"]

    body = open(os.path.join(repo, ".agent", "in", "RDSD-118", "scope.toon"), encoding="utf-8").read()
    assert "scope[1]" in body and "models/Velocity.tmdl" in body
    rows = SC.read_scope(repo, "RDSD-118")
    assert rows[0]["path"] == "models/Velocity.tmdl"
    assert rows[0]["how"] == SC.BY_HASH and rows[0]["by"] == "operator"

    # A second drop of the same file is not a second row.
    again = SC.add("luna", repo, "RDSD-118", ["models/Velocity.tmdl"])
    assert again["data"]["paths"] == [] and again["data"]["already"] == ["models/Velocity.tmdl"]
    assert len(SC.read_scope(repo, "RDSD-118")) == 1

    written = []
    for root, _dirs, files in os.walk(os.path.join(repo, ".agent")):
        written += [os.path.join(root, f).replace("\\", "/") for f in files]
    assert all("/.agent/in/" in p or p.endswith("state.json") for p in written), written


def test_the_agents_own_output_and_anything_credential_shaped_are_refused(fleet_home, tmp_path):
    repo = _checkout(tmp_path)
    for rel in (".agent/out/rows.tsv", ".env", "config/secrets.json", "localSettings.json"):
        with pytest.raises(SC.ScopeError) as caught:
            SC.add("luna", repo, "RDSD-118", [rel])
        assert caught.value.code == "scope_refused", rel


def test_a_scope_row_with_a_comma_survives_the_round_trip(fleet_home, tmp_path):
    """TOON quotes a cell that holds its delimiter, and reading it back must unquote it."""
    repo = _checkout(tmp_path)
    SC.add("luna", repo, "RDSD-118", ["models/Velocity.tmdl"], why="answer to q4, the baseline")
    rows = SC.read_scope(repo, "RDSD-118")
    assert rows[0]["why"] == "answer to q4, the baseline"
    assert rows[0]["path"] == "models/Velocity.tmdl"


# ---------------------------------------------------------------------------------- the API pair


def test_resolve_writes_nothing_and_scope_writes_one_file(fleet_home, tmp_path):
    repo = _checkout(tmp_path)
    before = sorted(os.listdir(os.path.join(repo, ".agent")))
    out = S.act("scope/resolve", {"repo": "luna", "files": [
        {"name": "notes.md", "size": 28, "sha": _sha(repo, "notes.md")}]})
    assert out["files"][0]["status"] == SC.RESOLVED
    assert sorted(os.listdir(os.path.join(repo, ".agent"))) == before, "resolve writes nothing"

    S.act("scope", {"repo": "luna", "paths": ["notes.md"]})
    assert os.path.isfile(os.path.join(repo, ".agent", "in", "RDSD-118", "scope.toon"))


def test_attach_bytes_lands_in_agent_in_and_is_capped(fleet_home, tmp_path):
    repo = _checkout(tmp_path)
    payload = base64.b64encode(b"a,b\n1,2\n").decode()
    out = S.act("attach-bytes", {"repo": "luna", "name": "export.csv", "bytes": payload})
    assert out["attached"] is True
    assert out["dir"] == ".agent/in/RDSD-118"
    assert open(os.path.join(repo, ".agent", "in", "RDSD-118", "export.csv"), encoding="utf-8").read() == "a,b\n1,2\n"
    assert [e["kind"] for e in E.read("luna")].count("inbox.attached") == 1
    assert (E.read("luna")[-1]["data"]).get("source") == "drop"

    too_big = base64.b64encode(b"x" * (11 * 1024 * 1024)).decode()
    with pytest.raises(S.ServeError):
        S.act("attach-bytes", {"repo": "luna", "name": "huge.bin", "bytes": too_big})


def test_an_unregistered_repo_is_refused_with_a_code(fleet_home, tmp_path):
    _checkout(tmp_path)
    with pytest.raises(S.ServeError) as caught:
        S.act("scope/resolve", {"repo": "nowhere", "files": []})
    assert caught.value.code == "wrong_repo"


# --------------------------------------------------------------------------- the rendered page


@pytest.mark.browser
def test_a_dropped_file_resolves_on_the_page_and_only_a_hash_leaves_it(fleet_home, tmp_path):
    """Acceptance criteria, together: the drop resolves to a path on the card, and nothing but the
    hash request leaves the page until *attach a copy* is clicked."""
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    repo = _checkout(tmp_path)
    _git(repo, "rm", "-q", "copy/Velocity.tmdl")       # one path, so the drop resolves outright

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors, posted = [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("request", lambda r: posted.append(r.url) if r.method == "POST" else None)
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)

            page.evaluate("""(body) => {
              const tile = document.querySelector('.tile[data-repo="luna"]');
              const dt = new DataTransfer();
              dt.items.add(new File([body], 'Velocity.tmdl', {type: 'text/plain'}));
              tile.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
            }""", "table Velocity\n  measure Rate = 1\n")

            page.wait_for_selector('.tile[data-repo="luna"] .scope:not([hidden])', timeout=5000)
            card = page.locator('.tile[data-repo="luna"] .scope')
            page.wait_for_function(
                """() => /given to|queued/.test(
                     document.querySelector('.tile[data-repo="luna"] .scope-note').textContent)""",
                timeout=5000)
            row = card.locator(".scope-row:not([hidden])")
            assert row.count() == 1
            assert row.locator(".sc-path").inner_text().strip() == "models/Velocity.tmdl"
            assert row.locator(".sc-how").inner_text().strip().lower() == "fingerprint"

            # Only the two scope calls were posted. The file's bytes never left the page.
            assert not any("attach-bytes" in u for u in posted), posted
            assert sum("scope/resolve" in u for u in posted) == 1, posted

            # ...and the server wrote the scope it was told about.
            rows = SC.read_scope(repo, "RDSD-118")
            assert [r["path"] for r in rows] == ["models/Velocity.tmdl"]
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()


@pytest.mark.browser
def test_a_file_that_is_not_the_repos_offers_a_copy_and_says_so(fleet_home, tmp_path):
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    _checkout(tmp_path)

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with sync_playwright() as p:
            browser = launch_chromium(p)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/?t={token}", wait_until="domcontentloaded")
            page.wait_for_selector(".tile:visible", timeout=15000)

            page.evaluate("""() => {
              const tile = document.querySelector('.tile[data-repo="luna"]');
              const dt = new DataTransfer();
              dt.items.add(new File(['quarter,amount\\n'], 'from-downloads.csv', {type: 'text/csv'}));
              tile.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
            }""")

            page.wait_for_selector('.tile[data-repo="luna"] .scope:not([hidden])', timeout=5000)
            card = page.locator('.tile[data-repo="luna"] .scope')
            page.wait_for_selector('.tile[data-repo="luna"] .sc-attach:not([hidden])', timeout=5000)
            assert "not a file of luna" in card.locator(".scope-note").inner_text()

            card.locator(".sc-attach:not([hidden])").click()
            page.wait_for_function(
                """() => /attached/.test(document.querySelector(
                     '.tile[data-repo="luna"] .scope-row:not([hidden]) .sc-why').textContent)""",
                timeout=5000)
            assert "attached → .agent/in/RDSD-118" in card.locator(".scope-row:not([hidden]) .sc-why").inner_text()
            assert not errors, errors
            browser.close()
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
