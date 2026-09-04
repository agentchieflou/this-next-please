"""How this package actually reaches a laptop: install, update, shadow, uninstall.

Everything else about the lifecycle is asserted from strings -- `install_cmd()` returns the right
text, `cli_command_text()` composes the right line, the `direct_url.json` reader parses. None of
that proves `pip` did what the text says. This drives the real `pip` and the real `ad-update`
through a real venv and asserts on what `ad-update --check` reports afterwards.

**The `git+file://` trick.** `ad-update` installs from `install.repo_url()`, which is GitHub. A test
that used it would need the network, would install whatever `main` happens to be, and could not
create the interesting transitions at all. So the working tree is cloned into a temp directory and
`AGENTDATA_REPO_URL` points at it as a `file://` URL: the same code path, the same `pip`, the same
`--force-reinstall --no-deps`, and a repository the test can commit to between steps.

**One test, not seven.** The cases are transitions -- git install to git install, editable to git
install -- so they are one function with the steps in order rather than seven functions sharing a
fixture. Seven would pass only in collection order, and CI deliberately runs the suite shuffled.
Each assertion names its step, so a failure still says which transition broke.

Adding a case: put it in the sequence where its starting state already exists, and label the
assertion `(x)`. If it needs a *different* starting state it wants its own venv and its own test,
the way the shadowing case does.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys

import pytest

import toon_read

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT = shutil.which("git")
BRANCH = "lifecycle"

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(not GIT, reason="git is needed to build the local clone")]


# ------------------------------------------------------------------------------------ the world


def _git(*args: str, cwd: str) -> str:
    out = subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, f"git {' '.join(args)}: {out.stderr}"
    return out.stdout.strip()


def _url(path: str) -> str:
    """A `file://` URL that git and pip both accept, on both OSes.

    Fiddlier than it looks, and every wrong spelling was tried first:

    * `file://localhost/C:/...` is what PEP 508 wants, and git reads `localhost` as a UNC host.
    * `file:///C:/...` is the ordinary Windows spelling and git handles it -- *unless*
      `MSYS_NO_PATHCONV=1` is set, which `proc.child_env()` does for every child, so git-for-windows
      stops folding `/C:/...` back to `C:/...` and looks for a repository that is not there. That is
      the shape of the failure: `ad-update` could not clone what plain `pip` had just cloned.
    * `file://C:/...` survives both, and on POSIX the same expression yields `file:///path`, which
      is the standard spelling there.

    PEP 508 still refuses the POSIX form (no authority), which is why `install.cli_spec()` falls
    back to a bare URL -- the thing an air-gapped mirror needs anyway.
    """
    from agentdata import textio

    return "file://" + textio.norm_path(os.path.abspath(path))


class Venv:
    """A throwaway interpreter, and the few things a test needs to ask of it."""

    def __init__(self, root: str, repo_url: str, cache: str):
        self.root = root
        self.repo_url = repo_url
        self.cache = cache
        # Every command runs from here, never from the checkout: `python -m agentdata` puts the
        # current directory first on sys.path, so running in the repo imports the working tree and
        # reports "running from a checkout" whatever pip put in the venv.
        self.work = os.path.join(os.path.dirname(root), "work")
        os.makedirs(self.work, exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", root], check=True, timeout=600)

    @property
    def bin(self) -> str:
        return os.path.join(self.root, "Scripts" if os.name == "nt" else "bin")

    @property
    def python(self) -> str:
        return os.path.join(self.bin, "python.exe" if os.name == "nt" else "python")

    def script(self, name: str) -> str:
        return os.path.join(self.bin, f"{name}.exe" if os.name == "nt" else name)

    def env(self, **extra: str) -> dict:
        # A shared pip cache is what keeps this inside the Windows job's budget: the wheel is built
        # once and every later install in the run reuses it.
        base = {**os.environ, "AGENTDATA_REPO_URL": self.repo_url, "PIP_CACHE_DIR": self.cache,
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "NO_COLOR": "1", "AGENTDATA_UI": "plain"}
        base.update(extra)
        return base

    def pip(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        out = subprocess.run([self.python, "-m", "pip", *args], capture_output=True, text=True,
                             timeout=900, env=self.env(), cwd=self.work)
        if check:
            assert out.returncode == 0, f"pip {' '.join(args)}\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}"
        return out

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run([self.python, "-m", "agentdata", *args], capture_output=True,
                              text=True, timeout=900, cwd=self.work, env=self.env(**env))

    def check(self) -> tuple[dict, str]:
        """(`meta` from `ad-update --check`, the whole output)."""
        out = self.run("update", "--check")
        assert out.returncode in (0, 1), out.stdout + out.stderr
        return toon_read.meta(out.stdout), out.stdout


@pytest.fixture(scope="module")
def cache(tmp_path_factory) -> str:
    """One pip cache for every venv in this module.

    Venv creation and the first wheel build are the whole cost of these tests; a cache per venv
    rebuilt the wheel four times. Shared, the build happens once and the rest are unpacks -- which
    is what keeps the Windows job inside its budget.
    """
    return str(tmp_path_factory.mktemp("pipcache"))


@pytest.fixture(scope="module")
def clone(tmp_path_factory) -> str:
    """A git clone of this checkout **including uncommitted work**, for `AGENTDATA_REPO_URL`.

    `git clone` copies HEAD, so a clone alone would install the last commit and quietly test the
    code you are about to change rather than the code you just changed -- which is the opposite of
    what a pre-commit test is for. The working tree's modified and untracked-but-not-ignored files
    are copied over the clone and committed on top.
    """
    dst = str(tmp_path_factory.mktemp("origin") / "this-next-please")
    _git("clone", "--quiet", "--no-hardlinks", REPO_ROOT, dst, cwd=REPO_ROOT)
    # An identity, so committing here does not depend on the developer's git config.
    _git("config", "user.email", "lifecycle@test.invalid", cwd=dst)
    _git("config", "user.name", "lifecycle test", cwd=dst)
    # A named branch, always. `actions/checkout` leaves a detached HEAD, and a clone of a detached
    # repository is detached too -- so `rev-parse --abbrev-ref HEAD` answered "HEAD" and the push
    # in step (e) failed with "not a full refname". Green locally, red on CI, for a reason that has
    # nothing to do with what the test is about.
    _git("checkout", "--quiet", "-B", BRANCH, cwd=dst)

    changed = _git("ls-files", "--modified", "--others", "--exclude-standard", cwd=REPO_ROOT)
    deleted = set(_git("ls-files", "--deleted", cwd=REPO_ROOT).splitlines())
    for rel in changed.splitlines():
        if not rel.strip() or rel in deleted:
            continue
        src, target = os.path.join(REPO_ROOT, rel), os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target) or dst, exist_ok=True)
        shutil.copy2(src, target)
    for rel in deleted:
        target = os.path.join(dst, rel)
        if rel.strip() and os.path.isfile(target):
            os.remove(target)
    if _git("status", "--porcelain", cwd=dst):
        _git("add", "-A", cwd=dst)
        _git("commit", "--quiet", "-m", "lifecycle: the working tree as it stands", cwd=dst)
    return dst


def _commit(clone: str, text: str) -> str:
    """Move the clone's HEAD, so a reinstall has something to pick up. Returns the new sha."""
    with open(os.path.join(clone, "LIFECYCLE.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    _git("add", "LIFECYCLE.md", cwd=clone)
    _git("commit", "--quiet", "-m", f"lifecycle: {text}", cwd=clone)
    return _git("rev-parse", "HEAD", cwd=clone)


def _scripts() -> list[str]:
    import tomllib

    with open(os.path.join(REPO_ROOT, "pyproject.toml"), "rb") as f:
        return sorted(tomllib.load(f)["project"]["scripts"])


# --------------------------------------------------------------------------- (a) .. (g), in order


def test_the_install_and_update_lifecycle(tmp_path_factory, clone, cache):
    v = Venv(str(tmp_path_factory.mktemp("venv") / "v"), _url(clone), cache)

    # (a) a fresh git install knows the commit it came from
    head = _git("rev-parse", "HEAD", cwd=clone)
    v.pip("install", "--no-deps", f"git+{v.repo_url}")
    meta, _out = v.check()
    assert meta["install"] == "git install", f"(a) {meta['install']}"
    assert meta["commit"] == head[:12], f"(a) reported {meta['commit']}, clone is at {head[:12]}"
    assert meta["editable"] == "false", "(a)"

    # (a) every declared console script exists and starts. A script pip declared but that cannot
    # run is the failure a version string alone cannot see.
    broken = []
    for name in _scripts():
        path = v.script(name)
        if not os.path.isfile(path):
            broken.append(f"{name}: not installed")
            continue
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=180,
                             env=v.env(), cwd=v.work)
        if out.returncode != 0 or not out.stdout.strip():
            tail = out.stderr.strip().splitlines()[-1] if out.stderr.strip() else ""
            broken.append(f"{name}: exit {out.returncode}, stdout {out.stdout[:60]!r}, {tail[:140]}")
    assert not broken, "(a) console scripts:\n  " + "\n  ".join(broken)

    # (b) a new commit upstream is picked up
    new_head = _commit(clone, "first")
    out = v.run("update", "--cli", "--no-reexec")
    assert out.returncode == 0, f"(b) {out.stdout}{out.stderr}"
    meta, _out = v.check()
    assert meta["commit"] == new_head[:12], f"(b) still on {meta['commit']}"

    # (c) the same commit again is a success, not a silent no-op failure. pip will not reinstall a
    # git URL whose *version* is unchanged, which is exactly why the real command forces it.
    out = v.run("update", "--cli", "--no-reexec")
    assert out.returncode == 0, f"(c) {out.stdout}{out.stderr}"
    meta, _out = v.check()
    assert meta["commit"] == new_head[:12], f"(c) {meta['commit']}"

    # (d) an editable checkout is reported as one, and the CLI half is skipped rather than failed:
    # reinstalling from git over a checkout would throw away someone's local work.
    v.pip("install", "--no-deps", "-e", clone)
    meta, _out = v.check()
    assert "editable" in meta["install"], f"(d) {meta['install']}"
    assert meta["editable"] == "true", "(d)"
    out = v.run("update", "--cli", "--no-reexec")
    assert out.returncode == 0, f"(d) {out.stdout}{out.stderr}"
    assert "skip" in out.stdout.lower(), f"(d) the skip was not reported: {out.stdout}"

    # (e) --pull is the checkout's version of an update: git pull --ff-only where it lives
    parent = os.path.dirname(clone)
    bare, work = os.path.join(parent, "upstream.git"), os.path.join(parent, "work-tree")
    _git("clone", "--quiet", "--bare", clone, bare, cwd=parent)
    _git("clone", "--quiet", bare, work, cwd=parent)
    _git("config", "user.email", "lifecycle@test.invalid", cwd=work)
    _git("config", "user.name", "lifecycle test", cwd=work)
    _commit(clone, "for the pull")
    _git("push", "--quiet", bare, f"HEAD:refs/heads/{BRANCH}", cwd=clone)
    before = _git("rev-parse", "HEAD", cwd=work)
    v.pip("install", "--no-deps", "-e", work)
    out = v.run("update", "--cli", "--pull", "--no-reexec")
    assert out.returncode == 0, f"(e) {out.stdout}{out.stderr}"
    assert _git("rev-parse", "HEAD", cwd=work) != before, "(e) the checkout was not moved"

    # (f) --from-git replaces a checkout with the published install
    out = v.run("update", "--cli", "--from-git", "--no-reexec")
    assert out.returncode == 0, f"(f) {out.stdout}{out.stderr}"
    meta, _out = v.check()
    assert meta["install"] == "git install", f"(f) {meta['install']}"
    assert meta["editable"] == "false", "(f)"

    # (g) uninstall leaves nothing behind. A leftover ad-pbip.exe pointing at a package that is
    # gone is a confusing way to fail.
    v.pip("uninstall", "-y", "agentdata")
    left = [n for n in _scripts() if os.path.isfile(v.script(n))]
    assert not left, f"(g) still installed after uninstall: {', '.join(left)}"
    out = v.run("--help")
    assert out.returncode != 0, "(g) python -m agentdata still worked after uninstall"
    assert "No module named" in (out.stderr + out.stdout), f"(g) {out.stderr[-300:]}"


# -------------------------------------------------------------------------------- shadowing


def test_two_installs_are_reported_as_shadowed(tmp_path_factory, clone, cache):
    """The failure an update cannot see: it succeeds and changes nothing, because a second copy
    earlier on the path is the one Python imports.

    Its own venv, so it cannot disturb the sequence above. A second dist-info earlier on `sys.path`
    is what shadowing *is*; `PYTHONPATH` puts one there without needing a `--user` install, which a
    venv refuses anyway.
    """
    v = Venv(str(tmp_path_factory.mktemp("venv2") / "v"), _url(clone), cache)
    v.pip("install", "--no-deps", f"git+{v.repo_url}")

    extra = str(tmp_path_factory.mktemp("shadow"))
    import agentdata

    shutil.copytree(os.path.dirname(os.path.abspath(agentdata.__file__)),
                    os.path.join(extra, "agentdata"),
                    ignore=shutil.ignore_patterns("__pycache__", ".agent"))
    dist = os.path.join(extra, "agentdata-0.0.1.dist-info")
    os.makedirs(dist)
    with open(os.path.join(dist, "METADATA"), "w", encoding="utf-8") as f:
        f.write("Metadata-Version: 2.1\nName: agentdata\nVersion: 0.0.1\n")
    with open(os.path.join(dist, "RECORD"), "w", encoding="utf-8") as f:
        f.write("")

    out = v.run("update", "--check", PYTHONPATH=extra)
    meta = toon_read.meta(out.stdout)
    rows = toon_read.table(out.stdout, "installs")
    assert len(rows) >= 2, f"only one install seen: {rows}\n{out.stdout}"
    assert meta.get("shadowed") == "true", meta
    assert meta.get("hint"), "shadowing was reported without a hint"
    assert "uninstall" in meta["hint"].lower(), meta["hint"]

    # The version reported has to be the one Python actually imports, not the newest one found --
    # reporting the copy that is *not* winning is how a successful-looking update hides itself.
    doctor = v.run("doctor", "--quiet", PYTHONPATH=extra)
    imported = subprocess.run(
        [v.python, "-c", "import agentdata, os; print(os.path.dirname(agentdata.__file__))"],
        capture_output=True, text=True, timeout=180, cwd=v.work, env=v.env(PYTHONPATH=extra))
    assert imported.returncode == 0, imported.stderr
    assert extra.replace("\\", "/") in imported.stdout.strip().replace("\\", "/"), \
        "the shadow copy should be the one imported, or this test proves nothing"
    assert toon_read.meta(doctor.stdout).get("version") == "0.0.1", \
        f"ad-doctor reported {toon_read.meta(doctor.stdout).get('version')}, not the imported copy"


# ---------------------------------------------------------------------------- Windows specifics


@pytest.mark.windows
@pytest.mark.skipif(os.name != "nt", reason="the .exe launcher only exists on Windows")
def test_the_exe_launcher_updates_itself(tmp_path_factory, clone, cache):
    """`ad-update.exe` cannot be replaced by pip while it is the running process, so it re-execs
    through `python -m`. Without that, the update succeeds and the launcher stays on the old copy.
    """
    v = Venv(str(tmp_path_factory.mktemp("venv3") / "v"), _url(clone), cache)
    v.pip("install", "--no-deps", f"git+{v.repo_url}")

    launcher = v.script("ad-update")
    assert os.path.isfile(launcher), "ad-update.exe was not installed"
    _commit(clone, "for the launcher")

    out = subprocess.run([launcher, "--cli"], capture_output=True, text=True, timeout=900,
                         cwd=v.work, env=v.env())
    assert out.returncode == 0, out.stdout + out.stderr
    assert os.path.isfile(launcher), "the launcher was removed rather than replaced"
    assert toon_read.meta(v.check()[1]).get("commit") == \
        _git("rev-parse", "HEAD", cwd=clone)[:12], "the .exe path did not pick up the new commit"


@pytest.mark.windows
@pytest.mark.skipif(os.name != "nt", reason="the App Execution Alias is a Windows thing")
def test_a_store_alias_on_the_path_is_named(tmp_path):
    """`%LOCALAPPDATA%\\Microsoft\\WindowsApps\\python.exe` is a 0-byte stub that opens the Store.
    It ships enabled and sits early on PATH; when it wins, `pip install` goes nowhere and nothing
    says so."""
    from agentdata import update as U

    fake = tmp_path / "Microsoft" / "WindowsApps"
    fake.mkdir(parents=True)
    alias = fake / "python.exe"
    alias.write_bytes(b"")
    assert U.store_alias(str(alias)) is True

    real = fake / "python3.exe"
    real.write_bytes(b"MZ" + b"\x00" * 100)
    assert U.store_alias(str(real)) is False, "a real interpreter under WindowsApps is not an alias"
    assert U.store_alias(str(tmp_path / "python.exe")) is False, "a 0-byte file elsewhere is not one"


def test_the_scripts_directory_is_reported_when_it_is_not_on_the_path(tmp_path_factory, clone, cache):
    """`'ad-setup' is not recognized` reads like a failed install; it is almost always PATH.

    The venv's Scripts directory is deliberately not on this process's PATH, which is exactly the
    `pip install --user` situation on a managed laptop.
    """
    v = Venv(str(tmp_path_factory.mktemp("venv4") / "v"), _url(clone), cache)
    v.pip("install", "--no-deps", f"git+{v.repo_url}")

    meta, _out = v.check()
    assert meta.get("scripts_on_path") == "false", meta.get("scripts_on_path")
    assert meta.get("scripts_dir"), "the report did not say where the scripts are"
    assert "not on PATH" in meta.get("hint", ""), meta.get("hint")
    assert "python -m agentdata" in meta.get("hint", ""), "the hint must name the form that works"


# ----------------------------------------------------------- what ran, as data for the release


def test_the_verified_matrix_is_written_out_for_the_release_note():
    """A release PR should be able to paste what was verified, on which OS, rather than assert it.

    Written under `.agent/out/`, which is this project's own output convention and is gitignored --
    the one place a test may write inside the checkout.
    """
    from agentdata import toon

    cases = ["fresh git install", "console scripts start", "update to a new commit",
             "update to the same commit", "editable install", "editable skips the CLI half",
             "--pull moves the checkout", "--from-git returns to a git install",
             "uninstall leaves nothing", "shadowing is reported"]
    where = "windows" if os.name == "nt" else "posix"
    python = f"{sys.version_info.major}.{sys.version_info.minor}"

    out_dir = os.path.join(REPO_ROOT, ".agent", "out")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "lifecycle-verified.toon")
    text = (toon.encode({"meta": {"ok": True, "source": "tests/test_lifecycle.py",
                                  "os": where, "python": python}}) + "\n"
            + toon.table("verified", ["case", "os", "python"],
                         [[c, where, python] for c in cases]) + "\n")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

    assert not toon.validate(text), toon.validate(text)
    assert len(toon_read.table(text, "verified")) == len(cases)
