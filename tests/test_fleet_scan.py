"""The scan that proposes repositories, and the two promises it lives or dies on.

**It reads nothing but the markers.** Every test here that walks a tree does it with `builtins.open`
recorded, and asserts the recorded set is a subset of `scan.READS` per candidate. That is not
belt-and-braces: the planted `.env` and `secrets.json` in `alpha/` are exactly the files a
convenience ("while we are here, pick up the Jira URL from `.env`") would open, and the recording
is the only thing that would notice.

**It writes nothing.** The tree and the fleet directory are fingerprinted before and after.
Registration stays `Registry.add`, called by the confirmation step the CLI slice owns.
"""
from __future__ import annotations
import builtins
import json
import os
import time

import pytest

from agentdata.fleet import registry, scan
from agentdata.fleet.registry import Registry
from agentdata.fleet.scan import Candidate, ScanError


@pytest.fixture()
def fleet_home(tmp_path, monkeypatch):
    """A fleet directory of our own, so nothing here can see a developer's real one."""
    home = tmp_path / "fleet"
    monkeypatch.setenv(registry.FLEET_DIR_ENV, str(home))
    return home


def make_repo(path, *, project="RDSD", agents_md=True, state=True, branch="main",
              pyproject=False, pbip="", age_days=0) -> str:
    """A folder shaped like a checkout `ad-setup --project` has been run in."""
    path = str(path)
    os.makedirs(os.path.join(path, ".git"), exist_ok=True)
    with open(os.path.join(path, ".git", "HEAD"), "w", encoding="utf-8", newline="\n") as f:
        f.write(f"ref: refs/heads/{branch}\n")
    if agents_md:
        with open(os.path.join(path, "AGENTS.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"# Project\n\n- jira_project: {project}\n- owner: <name>\n")
    if state:
        os.makedirs(os.path.join(path, ".agent"), exist_ok=True)
        with open(os.path.join(path, ".agent", "state.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"project": project, "phase": "idle"}, f)
    if pyproject:
        with open(os.path.join(path, "pyproject.toml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("[project]\nname = 'x'\n")
    if pbip:
        with open(os.path.join(path, f"{pbip}.pbip"), "w", encoding="utf-8", newline="\n") as f:
            f.write("{}\n")
    if age_days:
        when = time.time() - age_days * 86400
        os.utime(os.path.join(path, ".git", "HEAD"), (when, when))
    return path


def plant_credentials(path) -> list[str]:
    """The files that must never be opened. Values are fake and stay fake -- see the epic rule."""
    planted = []
    for name, body in ((".env", "JIRA_URL=https://example.invalid\n"),
                       ("secrets.json", '{"note": "not a real credential"}\n'),
                       ("localSettings.json", "{}\n")):
        full = os.path.join(str(path), name)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        planted.append(full)
    return planted


@pytest.fixture()
def tree(tmp_path):
    """Four repositories, a bare folder, a node_modules, and one repository three levels down."""
    root = tmp_path / "PycharmProjects"
    make_repo(root / "alpha", project="RDSD", age_days=5)
    plant_credentials(root / "alpha")
    make_repo(root / "beta", project="CEF", pbip="Velocity", branch="feature/RDSD-22449")
    make_repo(root / "gamma", agents_md=False, state=False, pyproject=True)   # a repo, not a project
    make_repo(root / "delta", project="ADMIN")
    (root / "just-a-folder").mkdir(parents=True)
    (root / "just-a-folder" / "notes.md").write_text("nothing here\n", encoding="utf-8")
    make_repo(root / "node_modules" / "some-package")
    make_repo(root / "outer" / "mid" / "inner", project="DEEP")
    return str(root)


class Opens:
    """Every path handed to `builtins.open`, so a test can say which files were read."""

    def __init__(self, monkeypatch, under: str):
        self.paths: list[str] = []
        self.under = os.path.abspath(under).replace("\\", "/").rstrip("/")
        real = builtins.open

        def recording(file, *a, **kw):
            try:
                full = os.path.abspath(os.fspath(file)).replace("\\", "/")
            except TypeError:                       # a file descriptor, not a path
                full = ""
            if full.startswith(self.under + "/"):
                self.paths.append(full[len(self.under) + 1:])
            return real(file, *a, **kw)

        monkeypatch.setattr(builtins, "open", recording)

    def file_kinds(self) -> set[str]:
        """`outer/mid/inner/.git/HEAD` -> `.git/HEAD`, so the set compares with `scan.READS`.

        Matched as a suffix rather than by splitting off one leading segment: the tree has a
        repository three levels down, and a helper that only stripped the first one would have
        reported `mid/inner/AGENTS.md` as an unexpected read.
        """
        kinds = set()
        for p in self.paths:
            kinds.add(next((r for r in scan.READS if p == r or p.endswith("/" + r)), p))
        return kinds


def fingerprint(root: str) -> dict:
    """Every path under `root` with its size and mtime. Any write shows up as a difference."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for n in sorted(filenames):
            full = os.path.join(dirpath, n)
            st = os.stat(full)
            out[os.path.relpath(full, root)] = (st.st_size, st.st_mtime_ns)
    return out


# ---------------------------------------------------------------------------- what it proposes


def test_the_four_projects_are_proposed_and_nothing_else(fleet_home, tree):
    """A candidate needs a `.git` *and* a marker: the bare folder has neither, `node_modules` is
    denied by name, and the depth-3 repository is out of reach of the default depth."""
    found = scan.scan(tree, registry=Registry())
    assert [c.name for c in found] == ["alpha", "beta", "delta", "gamma"], [c.path for c in found]
    assert all(isinstance(c, Candidate) for c in found)
    assert not any("node_modules" in c.path for c in found)
    assert not any("just-a-folder" in c.path for c in found)


def test_the_nested_repository_needs_the_depth_it_is_actually_at(fleet_home, tree):
    assert "inner" not in [c.name for c in scan.scan(tree, depth=2, registry=Registry())]
    deep = scan.scan(tree, depth=3, registry=Registry())
    assert "inner" in [c.name for c in deep]
    assert len(deep) == 5


def test_depth_one_is_only_the_folders_directly_underneath(fleet_home, tree):
    names = [c.name for c in scan.scan(tree, depth=1, registry=Registry())]
    assert names == ["alpha", "beta", "delta", "gamma"]


def test_pointing_at_a_single_repository_proposes_that_repository(fleet_home, tree):
    """Depth counts levels *below* the folder, so `--scan .` inside a checkout is not a no-op."""
    found = scan.scan(os.path.join(tree, "alpha"), depth=0, registry=Registry())
    assert [c.name for c in found] == ["alpha"]


def test_the_row_carries_what_the_human_decides_on(fleet_home, tree):
    by_name = {c.name: c for c in scan.scan(tree, registry=Registry())}

    alpha = by_name["alpha"]
    assert alpha.branch == "main" and alpha.jira_project == "RDSD"
    assert alpha.has_agents_md and alpha.has_state and alpha.ready
    assert alpha.last_commit_age_days == 5, "the ref mtime is the only age available without opening git"
    assert alpha.already_registered is False and alpha.reparse is False

    beta = by_name["beta"]
    assert beta.branch == "feature/RDSD-22449", "a slash in a branch name is not a path separator"
    assert beta.pbip == "Velocity" and beta.jira_project == "CEF"

    gamma = by_name["gamma"]
    assert gamma.ready is False, "a repo with only a pyproject.toml is not an agent project yet"
    assert "AGENTS.md" in gamma.why and "ad-setup --project" in gamma.why, gamma.why
    assert gamma.jira_project == ""


def test_a_placeholder_fact_does_not_become_a_value(fleet_home, tree):
    """`- owner: <name>` is the AGENTS.md template's own placeholder; `project_facts` drops it and
    the proposal must not resurrect it as the string `<name>`."""
    alpha = {c.name: c for c in scan.scan(tree, registry=Registry())}["alpha"]
    assert "<" not in alpha.to_json()["jira_project"]
    assert "<" not in alpha.why


def test_a_detached_head_reports_the_sha_rather_than_a_wrong_branch(fleet_home, tmp_path):
    repo = make_repo(tmp_path / "root" / "detached")
    with open(os.path.join(repo, ".git", "HEAD"), "w", encoding="utf-8", newline="\n") as f:
        f.write("9f1c0a3e5b7d9f1c0a3e5b7d9f1c0a3e5b7d9f1c\n")
    found = scan.scan(str(tmp_path / "root"), registry=Registry())
    assert found[0].branch == "9f1c0a3"


def test_a_git_file_instead_of_a_git_directory_is_proposed_without_a_branch(fleet_home, tmp_path):
    """A worktree's `.git` is a file holding `gitdir: ...`. Following it would be reading another
    repository's internals from inside this one, which is the rule this module is built around."""
    root = tmp_path / "root"
    repo = root / "worktree"
    os.makedirs(str(repo))
    (repo / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("- jira_project: RDSD\n", encoding="utf-8")
    found = scan.scan(str(root), registry=Registry())
    assert [c.name for c in found] == ["worktree"]
    assert found[0].branch == "" and found[0].last_commit_age_days is None


# ----------------------------------------------------------------------------- what it may open


def test_the_scan_opens_only_agents_md_and_git_head(fleet_home, tree, monkeypatch):
    """The whole safety argument in one assertion: an allow-list of two file names."""
    reg = Registry()                          # built before recording; its own file is not the point
    opens = Opens(monkeypatch, tree)
    scan.scan(tree, depth=3, registry=reg)

    assert opens.paths, "the recorder did not see the AGENTS.md reads, so it proves nothing"
    assert opens.file_kinds() <= set(scan.READS), sorted(set(opens.paths))
    for read in opens.paths:
        assert read.endswith("AGENTS.md") or read.endswith(".git/HEAD"), read


def test_a_planted_credential_file_is_proposed_and_never_opened(fleet_home, tree, monkeypatch):
    """`alpha/` has a `.env`, a `secrets.json` and a `localSettings.json`. The folder is still a
    perfectly good candidate; the files are decided by name and stay shut."""
    reg = Registry()
    opens = Opens(monkeypatch, tree)
    found = scan.scan(tree, depth=3, registry=reg)

    assert "alpha" in [c.name for c in found]
    for forbidden in (".env", "secrets.json", "localSettings.json", ".agent/state.json",
                      "pyproject.toml", "Velocity.pbip"):
        assert not any(p.endswith(forbidden) for p in opens.paths), \
            f"{forbidden} was opened: {sorted(opens.paths)}"


def test_a_credential_value_never_reaches_a_proposed_row(fleet_home, tree):
    """Nothing in `.env` may appear in the TOON the operator (and a screenshot) will see."""
    blob = json.dumps([c.to_json() for c in scan.scan(tree, depth=3, registry=Registry())])
    assert "example.invalid" not in blob and "JIRA_URL" not in blob


def test_the_scan_writes_nothing_anywhere(fleet_home, tree):
    before_tree = fingerprint(tree)
    scan.scan(tree, depth=3, registry=Registry())
    assert fingerprint(tree) == before_tree, "the scan modified the folder it was reading"
    assert not os.path.exists(str(fleet_home)), "the scan created fleet state; only `repo add` may"


# ----------------------------------------------------------------------- refusals and the OS


def test_a_folder_that_is_not_there_says_what_to_pass(fleet_home, tmp_path):
    with pytest.raises(ScanError) as e:
        scan.scan(str(tmp_path / "nope"), registry=Registry())
    assert "no such folder" in e.value.msg
    assert "--scan" in e.value.hint


def test_a_subtree_the_os_refuses_is_skipped_with_its_reason(fleet_home, tree, monkeypatch):
    """`C:/Users/<user>/Application Data` is a junction the account cannot traverse and it sits
    directly under the folder the operator will point this at. One refused subtree must cost that
    subtree, not the scan."""
    real = os.scandir
    refused = os.path.join(tree, "beta")

    def scandir(path, *a, **kw):
        if str(path).replace("\\", "/").rstrip("/").endswith("/beta"):
            raise PermissionError(13, "Access is denied")
        return real(path, *a, **kw)

    monkeypatch.setattr(os, "scandir", scandir)
    skips: list[tuple[str, str]] = []
    found = scan.scan(tree, registry=Registry(), on_skip=lambda p, why: skips.append((p, why)))

    assert [c.name for c in found] == ["alpha", "delta", "gamma"], "the scan died on one bad folder"
    assert any(p.endswith("/beta") and "PermissionError" in why for p, why in skips), skips
    assert refused


def test_the_deny_list_is_reported_rather_than_silently_dropped(fleet_home, tree):
    skips: list[tuple[str, str]] = []
    scan.scan(tree, registry=Registry(), on_skip=lambda p, why: skips.append((p, why)))
    assert any(p.endswith("/node_modules") and why == "deny-list" for p, why in skips), skips
    assert "node_modules" in scan.DENY_DIRS and ".venv" in scan.DENY_DIRS


def test_a_bad_depth_is_refused_by_name(fleet_home, tree):
    with pytest.raises(ScanError) as e:
        scan.scan(tree, depth="two", registry=Registry())
    assert "--depth" in e.value.msg


# ------------------------------------------------------------------------------- Windows facts


@pytest.mark.posix
@pytest.mark.skipif(os.name == "nt", reason="os.symlink needs a privilege on Windows; the "
                                            "reparse *attribute* path is the nt one")
def test_a_junction_is_reported_and_not_walked_through(fleet_home, tmp_path):
    """A junction, a mapped drive and a OneDrive placeholder are all reparse points, and walking
    through one either loops or proposes the same repository twice under two names."""
    root = tmp_path / "PycharmProjects"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "omega"
    make_repo(outside, project="OMEGA")
    make_repo(outside / "nested", project="NESTED")
    os.symlink(str(outside), str(root / "omega-link"))

    found = scan.scan(str(root), depth=3, registry=Registry())
    names = [c.name for c in found]
    assert names == ["omega-link"], names
    assert found[0].reparse is True
    assert "not followed" in found[0].why, found[0].why
    assert "nested" not in names, "the walk followed a reparse point"


def test_a_msys_style_folder_argument_is_understood(fleet_home, tree, monkeypatch):
    """Git Bash converts most arguments, but a folder that reached us through a config file or an
    AGENTS.md fact never saw a shell (#68)."""
    monkeypatch.setattr(os, "name", "nt", raising=False)
    converted = scan.textio.from_msys("/c/Users/x/PycharmProjects")
    monkeypatch.undo()
    assert converted == "C:/Users/x/PycharmProjects"
    assert scan.scan(tree, registry=Registry()), "the ordinary path still scans"


# ----------------------------------------------------------------------- names and registration


def test_a_proposed_name_never_collides_with_another_proposal(fleet_home, tmp_path):
    """Two `.../<team>/reporting` folders both want `reporting`, and `Registry.add` refuses the
    second -- halfway through a `--yes` run, with the first half already written."""
    root = tmp_path / "root"
    make_repo(root / "rdsd" / "reporting")
    make_repo(root / "cef" / "reporting")
    names = [c.name for c in scan.scan(str(root), depth=2, registry=Registry())]
    assert len(set(names)) == 2, names
    assert "reporting" in names and "rdsd-reporting" in names, names


def test_a_registered_repository_keeps_its_registered_name_and_is_flagged(fleet_home, tree):
    reg = Registry()
    reg.add(os.path.join(tree, "alpha"), name="alpha-prime")

    found = {c.path: c for c in scan.scan(tree, registry=Registry())}
    alpha = found[os.path.join(tree, "alpha").replace("\\", "/")]
    assert alpha.already_registered is True
    assert alpha.name == "alpha-prime", "renaming it on a rerun would orphan every other command"
    assert "already registered" in alpha.why


def test_the_confirmation_step_is_registry_add_unchanged(fleet_home, tree):
    """The scan proposes; `Registry.add` writes. A rerun then proposes 0 new and flags 0 drift."""
    reg = Registry()
    for candidate in scan.scan(tree, registry=reg):
        if candidate.ready:
            reg.add(candidate.path, name=candidate.name)

    assert sorted(Registry().repos) == ["alpha", "beta", "delta"]
    assert Registry().get("beta").jira_project == "CEF"

    again = scan.scan(tree, registry=Registry())
    assert [c.name for c in again if not c.already_registered] == ["gamma"], "gamma is not a project yet"
    assert scan.drift(Registry()) == []


# ----------------------------------------------------------------------------------- the drift


def test_a_deleted_folder_is_flagged_and_never_removed(fleet_home, tree):
    import shutil

    reg = Registry()
    reg.add(os.path.join(tree, "alpha"), name="alpha")
    reg.add(os.path.join(tree, "beta"), name="beta")

    shutil.rmtree(os.path.join(tree, "alpha"))
    rows = scan.drift(Registry())

    assert len(rows) == 1 and rows[0]["name"] == "alpha" and rows[0]["reason"] == "missing"
    assert "repo remove alpha" in rows[0]["hint"]
    assert "nothing is removed for you" in rows[0]["hint"]
    assert sorted(Registry().repos) == ["alpha", "beta"], "drift removed an entry"


def test_a_folder_that_stopped_being_a_project_is_drift_too(fleet_home, tree):
    reg = Registry()
    reg.add(os.path.join(tree, "delta"), name="delta")
    os.remove(os.path.join(tree, "delta", ".agent", "state.json"))

    rows = scan.drift(Registry())
    assert [r["reason"] for r in rows] == ["not_a_project"]
    assert ".agent/state.json" in rows[0]["detail"]
    assert list(Registry().repos) == ["delta"]


def test_drift_is_quiet_when_a_disconnected_drive_comes_back(fleet_home, tree):
    """The point of never removing: a repository on a mapped drive is "missing" every morning the
    drive is not connected yet, and it is perfectly fine an hour later."""
    reg = Registry()
    reg.add(os.path.join(tree, "beta"), name="beta")
    assert scan.drift(Registry()) == []
