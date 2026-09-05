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

**One test, one venv.** The cases are transitions -- git install to git install, editable to git
install -- so they are one function with the steps in order rather than several sharing a fixture.
Several would pass only in collection order, and CI deliberately runs the suite shuffled. Each
assertion names its step, so a failure still says which transition broke.

It is also what makes this affordable. Creating a venv and installing into it is the entire cost,
and on a hosted Windows runner that is minutes rather than seconds -- so the long sequence runs on
Linux and Windows runs `test_the_windows_launcher_and_scripts`, which keeps the parts that are
actually about Windows at two installs instead of six.

**Nothing here may hang.** Three CI runs were killed at their step cap with no failure and no
timeline, and the cause turned out to be two things compounding: a call that structurally could not
time out (see `run_bounded`), and a shallow origin repository that sent pip's partial clone chasing
a promisor remote that could never answer (see the `clone` fixture). Both are closed by
construction now, and a shared wall-clock budget means the test loses to itself -- with a named
command -- before it can ever lose to CI again.

Adding a case: put it in the sequence where its starting state already exists, and label the
assertion `(x)`. A case that needs no venv at all -- `store_alias`, say -- belongs outside.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

import pytest

import toon_read

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIT = shutil.which("git")
BRANCH = "lifecycle"

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(not GIT, reason="git is needed to build the local clone")]


# ------------------------------------------------------- running a command that cannot hang us


class Ran:
    """What a command did. `stdout` holds stdout and stderr together, in order."""

    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""          # merged into stdout; kept so callers can read either

    @property
    def output(self) -> str:
        return self.stdout


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process **and everything it started**.

    `Popen.kill()` ends one process. Windows has no process groups by default, so pip's `git`, and
    git's `upload-pack`, outlive it -- and they are the ones holding the handles we are waiting on.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], timeout=120,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.kill()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        pass


BUDGET_ENV = "AGENTDATA_LIFECYCLE_BUDGET_S"
_deadline: float | None = None


@pytest.fixture(autouse=True)
def _budget():
    """One wall-clock budget for the whole test, not a timeout per command.

    The per-call timeouts in this module sum to several hours against a ten-minute CI step, so
    bounding each call individually can never bound the test -- and a test that loses to the step
    cap is killed blind, with no failure and no timeline. With a shared deadline the test always
    loses to itself first, naming the command it was in.
    """
    global _deadline
    _deadline = time.monotonic() + int(os.environ.get(BUDGET_ENV, "540"))
    yield
    _deadline = None


def run_bounded(argv: list[str], *, cwd: str, env: dict, timeout: int, label: str = "") -> Ran:
    """Run a command so that it cannot take the whole job with it.

    Three deliberate differences from `subprocess.run(capture_output=True, timeout=...)`, each of
    which the Windows runner earned:

    * **stdin is /dev/null.** Anything that decides it wants to ask a question gets EOF instead of a
      wait nobody will end. pip shells out to git, and git can reach for a credential helper.
    * **output goes to a real file, not a pipe.** `capture_output` is not an escape hatch: when the
      timeout fires, `run()` kills the direct child and then waits for the pipe write-ends to close
      -- and a grandchild that inherited them keeps them open, so it blocks *past its own timeout*,
      indefinitely. A file has no reader thread to block on. This is why a test with a 420-second
      timeout was still running after 571 seconds with no `TimeoutExpired` in sight.
    * **the timeout kills the tree**, not the process.

    Returns stdout and stderr merged in the order they were written, which is also what a person
    pasting a failure would have seen.
    """
    what = label or argv[0]
    if _deadline is not None:
        left = _deadline - time.monotonic()
        if left <= 5:
            raise AssertionError(
                f"the lifecycle budget ran out before {what}. Raise {BUDGET_ENV} if the machine is "
                f"simply slow; otherwise the timeline above says which command ate it.")
        timeout = min(timeout, int(left))

    # Announced *before* the wait, on stderr, flushed: printed afterwards it says nothing at all
    # about the command that never returned, which is exactly the one worth naming.
    print(f"[lifecycle] {time.strftime('%H:%M:%S')} >>> {what}", file=sys.stderr, flush=True)
    started = time.time()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as sink:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=sink, stderr=subprocess.STDOUT, text=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            sink.seek(0)
            tail = sink.read()[-4000:]
            raise AssertionError(
                f"{label or argv[0]} did not finish within {timeout}s and was killed.\n"
                f"command: {' '.join(argv)}\ncwd: {cwd}\n--- output so far ---\n{tail}") from None
        print(f"[lifecycle] {time.strftime('%H:%M:%S')} <<< {what}  {time.time() - started:.1f}s "
              f"rc={code}", file=sys.stderr, flush=True)
        sink.seek(0)
        return Ran(code, sink.read())

# ------------------------------------------------------------------------------------ the world


def _git(*args: str, cwd: str) -> str:
    out = run_bounded([GIT, *args], cwd=cwd, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
                      timeout=180, label="git " + " ".join(args))
    assert out.returncode == 0, f"git {' '.join(args)}: {out.stdout}"
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
        seed = run_bounded([sys.executable, "-m", "venv", root], cwd=self.work,
                           env=dict(os.environ), timeout=300, label="python -m venv")
        assert seed.returncode == 0, seed.stdout[-2000:]
        # Build isolation creates a throwaway environment and fetches setuptools **per build**, and
        # this module builds the same package six or seven times. On a Windows runner that was the
        # difference between under two minutes and over twelve -- the job was cancelled at its cap
        # with one test still running. setuptools goes in once instead, and every later build reuses
        # it; `PIP_NO_BUILD_ISOLATION` is an environment setting, so `ad-update`'s own pip calls get
        # it too without the test having to reach into the command it runs.
        tools = run_bounded([self.python, "-m", "pip", "install", "-q", "setuptools", "wheel"],
                            cwd=self.work, timeout=300, label="pip install setuptools wheel",
                            env={**os.environ, "PIP_CACHE_DIR": cache,
                                 "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"})
        assert tools.returncode == 0, tools.stdout[-2000:]

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
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_BUILD_ISOLATION": "1",
                "PIP_NO_INPUT": "1", "NO_COLOR": "1", "AGENTDATA_UI": "plain",
                # Nothing here may ever wait for a person. pip shells out to git, and git that
                # decides it wants credentials blocks on a prompt no one will answer -- which on a
                # runner looks exactly like a slow test until the job is cancelled.
                "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
        base.update(extra)
        return base

    def pip(self, *args: str, check: bool = True) -> Ran:
        out = run_bounded([self.python, "-m", "pip", *args], cwd=self.work, env=self.env(),
                          timeout=420, label="pip " + " ".join(args))
        if check:
            assert out.returncode == 0, f"pip {' '.join(args)}\n{out.stdout[-3000:]}"
        return out

    def run(self, *args: str, **env: str) -> Ran:
        return run_bounded([self.python, "-m", "agentdata", *args], cwd=self.work,
                           env=self.env(**env), timeout=420,
                           label="python -m agentdata " + " ".join(args))

    def check(self) -> tuple[dict, str]:
        """(`meta` from `ad-update --check`, the whole output)."""
        out = self.run("update", "--check")
        assert out.returncode in (0, 1), out.stdout
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
    """A one-commit repository holding this checkout, **including uncommitted work**.

    Not `git clone` of the real repo. pip re-clones this seven times over the sequence, and cloning
    a repository with history is most of what those seven cost -- on a CI runner it was the
    difference between a couple of minutes and hitting the job's cap. `git archive HEAD` is the
    tree with no history at all, and the working tree's own changes go on top: what pip installs is
    then the code you are about to commit, not the code you last committed, which is the point of
    running this before a commit.
    """
    dst = str(tmp_path_factory.mktemp("origin") / "this-next-please")
    os.makedirs(dst, exist_ok=True)

    bundle = os.path.join(os.path.dirname(dst), "head.tar")
    _git("archive", "--format=tar", "-o", bundle, "HEAD", cwd=REPO_ROOT)
    with tarfile.open(bundle) as tar:
        tar.extractall(dst, filter="data")
    os.remove(bundle)

    # the working tree on top: modified and untracked-but-not-ignored, minus anything deleted
    deleted = set(_git("ls-files", "--deleted", cwd=REPO_ROOT).splitlines())
    for rel in _git("ls-files", "--modified", "--others", "--exclude-standard", cwd=REPO_ROOT).splitlines():
        if not rel.strip() or rel in deleted:
            continue
        target = os.path.join(dst, rel)
        os.makedirs(os.path.dirname(target) or dst, exist_ok=True)
        shutil.copy2(os.path.join(REPO_ROOT, rel), target)
    for rel in deleted:
        target = os.path.join(dst, rel)
        if rel.strip() and os.path.isfile(target):
            os.remove(target)

    _git("init", "--quiet", "--initial-branch", BRANCH, cwd=dst)
    _git("config", "user.email", "lifecycle@test.invalid", cwd=dst)
    _git("config", "user.name", "lifecycle test", cwd=dst)
    # Deliberately NOT `uploadpack.allowFilter`. pip clones with `--filter=blob:none`, and allowing
    # it turns this into a real partial clone with a *promisor* remote -- the machinery the hang was
    # traced to. Left disallowed, git says "filtering not recognized by server, ignoring" and does a
    # plain full clone, which for a one-commit origin costs a second and defers nothing.
    _git("add", "-A", cwd=dst)
    _git("commit", "--quiet", "-m", "lifecycle: the working tree as it stands", cwd=dst)

    _assert_pip_can_clone_this(dst)
    return dst


def _assert_pip_can_clone_this(origin: str) -> None:
    """Run the exact clone pip will run, and prove it comes back clean.

    The trigger that cost three CI runs, and it is invisible unless you look for it. `actions/checkout`
    clones with `fetch-depth: 1`, so a CI checkout is **shallow**; a `git clone` of it inherits that,
    and pip's `git clone --filter=blob:none file://<shallow>` then registers a *promisor* remote --
    a remote that has promised to serve objects on demand and cannot. Every later object lookup
    becomes a fetch that fails and retries, which is how one investigation reached roughly 1360 live
    git processes reproducing it.

    Building the origin from `git archive` avoids it by construction. This checks that it really did,
    rather than assuming, and it runs on a **green** run -- so the diagnosis stays settled instead of
    resting on the fact that the symptom stopped. Two seconds, on both OSes.
    """
    import tempfile as _tempfile

    assert _git("rev-parse", "--is-shallow-repository", cwd=origin) == "false", \
        "the origin is shallow: pip's partial clone will chase a promisor that cannot answer"

    with _tempfile.TemporaryDirectory() as probe_root:
        probe = os.path.join(probe_root, "probe")
        started = time.time()
        _git("clone", "--filter=blob:none", "--quiet", _url(origin), probe, cwd=probe_root)
        elapsed = time.time() - started

        promisor = run_bounded([GIT, "config", "--get", "remote.origin.promisor"], cwd=probe,
                               env=dict(os.environ), timeout=60, label="git config promisor")

        # The config key is diagnosis, not the property. git honours `--filter` over the local
        # transport, so a promisor remote is registered either way; what matters is whether the
        # thing it promised can actually be delivered. Walking every object forces exactly that --
        # against a shallow origin it is the fetch that can never be answered, and the loop that
        # took three CI runs to find. Bounded, so a broken promisor fails here and says so.
        walked = time.time()
        run_bounded([GIT, "rev-list", "--objects", "--all"], cwd=probe, env=dict(os.environ),
                    timeout=120, label="git rev-list --objects --all (forces any deferred fetch)")
        walk = time.time() - walked

        print(f"[lifecycle] pip-style clone {elapsed:.1f}s, object walk {walk:.1f}s, "
              f"promisor={promisor.stdout.strip() or 'unset'}, "
              f"shallow_origin=false", file=sys.stderr, flush=True)
        assert elapsed < 60, f"the clone pip performs took {elapsed:.0f}s; it should be about one"
        assert walk < 60, (f"resolving the clone's objects took {walk:.0f}s: the promisor cannot "
                           f"serve what it promised, which is the unbounded-fetch failure")


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


# --------------------------------------------------------------------------- (a) .. (h), in order

# Run inside the installed venv, not here: the point is whether the *wheel* carries the static
# files, which a checkout can never tell us because they are on disk either way.
SERVE_A_PAGE = """
import threading, urllib.request
from agentdata.fleet import serve

server, token = serve.build(0)
threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
try:
    with urllib.request.urlopen(serve.url_for(server, token), timeout=20) as r:
        print(r.read().decode("utf-8")[:400])
finally:
    server.shutdown()
    server.server_close()
"""


@pytest.mark.posix
@pytest.mark.skipif(os.name == "nt", reason="six pip builds do not fit a Windows runner; the "
                                            "Windows-shaped half is test_the_windows_launcher_and_scripts")
def test_the_install_and_update_lifecycle(tmp_path_factory, clone, cache):
    """Every transition, in one environment, because every case is a transition out of the last one.

    One venv is what keeps this affordable: creating a venv and installing into it is the whole cost.
    Six pip builds is about ninety seconds here and roughly six times that on a hosted runner, which
    is why Windows runs the shorter, Windows-shaped sibling instead of this. Nothing between (c) and
    (g) is platform-specific -- an editable install, a `--pull`, a `--from-git` and a shadowing copy
    behave the same everywhere, and proving them twice buys nothing but runner minutes.
    """
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
        out = run_bounded([path, "--version"], cwd=v.work, env=v.env(), timeout=180,
                          label=name + " --version")
        if out.returncode != 0 or not out.stdout.strip():
            lines = out.stdout.strip().splitlines()
            broken.append(f"{name}: exit {out.returncode}, {lines[-1][:160] if lines else 'no output'}")
    assert not broken, "(a) console scripts:\n  " + "\n  ".join(broken)

    # (a) the dashboard's page ships in the wheel. Without the `package-data` entry, `ad-fleet
    # serve` installs perfectly and then answers 404 to every request -- and only ever on someone
    # else's machine, because in a checkout the files are simply there.
    out = run_bounded([v.python, "-c", SERVE_A_PAGE], cwd=v.work, env=v.env(), timeout=180,
                      label="ad-fleet serve from the wheel")
    assert out.returncode == 0, f"(a) the installed dashboard did not serve its page: {out.stdout}"
    assert "<title>fleet</title>" in out.stdout, f"(a) {out.stdout[-300:]}"

    # (a) `'ad-setup' is not recognized` reads like a failed install; it is almost always PATH. The
    # venv's Scripts directory is deliberately not on this process's PATH, which is exactly the
    # `pip install --user` situation on a managed laptop.
    assert meta.get("scripts_on_path") == "false", f"(a) {meta.get('scripts_on_path')}"
    assert meta.get("scripts_dir"), "(a) the report did not say where the scripts are"
    assert "not on PATH" in meta.get("hint", ""), f"(a) {meta.get('hint')}"
    assert "python -m agentdata" in meta.get("hint", ""), "(a) the hint must name the form that works"

    # (b) a second copy earlier on sys.path is the failure an update cannot see: it succeeds and
    # changes nothing. PYTHONPATH puts one there without a --user install, which a venv refuses.
    shadow = _shadow_copy(tmp_path_factory)
    out = v.run("update", "--check", PYTHONPATH=shadow)
    shadowed, rows = toon_read.meta(out.stdout), toon_read.table(out.stdout, "installs")
    assert len(rows) >= 2, f"(b) only one install seen: {rows}"
    assert shadowed.get("shadowed") == "true", f"(b) {shadowed}"
    assert "uninstall" in shadowed.get("hint", "").lower(), f"(b) {shadowed.get('hint')}"
    imported = run_bounded(
        [v.python, "-c", "import agentdata, os; print(os.path.dirname(agentdata.__file__))"],
        cwd=v.work, env=v.env(PYTHONPATH=shadow), timeout=180, label="import agentdata")
    assert imported.returncode == 0, imported.stdout
    assert shadow.replace("\\", "/") in imported.stdout.strip().replace("\\", "/"), \
        "(b) the shadow copy should be the one imported, or this proves nothing"
    doctor = v.run("doctor", "--quiet", PYTHONPATH=shadow)
    assert toon_read.meta(doctor.stdout).get("version") == "0.0.1", \
        f"(b) ad-doctor reported {toon_read.meta(doctor.stdout).get('version')}, not the imported copy"

    # (c) a new commit upstream is picked up. The console-script launcher's own behaviour --
    # refusing the CLI half, because pip cannot replace a launcher that is the running process --
    # is Windows-only and lives in test_the_windows_launcher_and_scripts.
    new_head = _commit(clone, "first")
    out = v.run("update", "--cli", "--no-reexec", "--timeout", "240")
    assert out.returncode == 0, f"(c) {out.stdout}"
    meta, _out = v.check()
    assert meta["commit"] == new_head[:12], f"(c) still on {meta['commit']}"

    # (d) the same commit again is a success, not a silent no-op failure. pip will not reinstall a
    # git URL whose *version* is unchanged, which is exactly why the real command forces it.
    out = v.run("update", "--cli", "--no-reexec", "--timeout", "240")
    assert out.returncode == 0, f"(d) {out.stdout}"
    meta, _out = v.check()
    assert meta["commit"] == new_head[:12], f"(d) {meta['commit']}"

    # (e) an editable checkout is reported as one, and the CLI half is skipped rather than failed:
    # reinstalling from git over a checkout would throw away someone's local work.
    v.pip("install", "--no-deps", "-e", clone)
    meta, _out = v.check()
    assert "editable" in meta["install"], f"(e) {meta['install']}"
    assert meta["editable"] == "true", "(e)"
    out = v.run("update", "--cli", "--no-reexec", "--timeout", "240")
    assert out.returncode == 0, f"(e) {out.stdout}"
    assert "skip" in out.stdout.lower(), f"(e) the skip was not reported: {out.stdout}"

    # (f) --pull is the checkout's version of an update: git pull --ff-only where it lives
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
    out = v.run("update", "--cli", "--pull", "--no-reexec", "--timeout", "240")
    assert out.returncode == 0, f"(f) {out.stdout}"
    assert _git("rev-parse", "HEAD", cwd=work) != before, "(f) the checkout was not moved"

    # (g) --from-git replaces a checkout with the published install
    out = v.run("update", "--cli", "--from-git", "--no-reexec", "--timeout", "240")
    assert out.returncode == 0, f"(g) {out.stdout}"
    meta, _out = v.check()
    assert meta["install"] == "git install", f"(g) {meta['install']}"
    assert meta["editable"] == "false", "(g)"

    # (h) uninstall leaves nothing behind. A leftover ad-pbip.exe pointing at a package that is
    # gone is a confusing way to fail.
    v.pip("uninstall", "-y", "agentdata")
    left = [n for n in _scripts() if os.path.isfile(v.script(n))]
    assert not left, f"(h) still installed after uninstall: {', '.join(left)}"
    out = v.run("--help")
    assert out.returncode != 0, "(h) python -m agentdata still worked after uninstall"
    assert "No module named" in out.stdout, f"(h) {out.stdout[-300:]}"


def _shadow_copy(tmp_path_factory) -> str:
    """A second `agentdata` with its own dist-info, for `PYTHONPATH` to put earlier on sys.path."""
    import agentdata

    extra = str(tmp_path_factory.mktemp("shadow"))
    shutil.copytree(os.path.dirname(os.path.abspath(agentdata.__file__)),
                    os.path.join(extra, "agentdata"),
                    ignore=shutil.ignore_patterns("__pycache__", ".agent"))
    dist = os.path.join(extra, "agentdata-0.0.1.dist-info")
    os.makedirs(dist)
    with open(os.path.join(dist, "METADATA"), "w", encoding="utf-8") as f:
        f.write("Metadata-Version: 2.1\nName: agentdata\nVersion: 0.0.1\n")
    with open(os.path.join(dist, "RECORD"), "w", encoding="utf-8") as f:
        f.write("")
    return extra


@pytest.mark.windows
@pytest.mark.skipif(os.name != "nt", reason="these are the Windows-shaped halves of the lifecycle")
def test_the_windows_launcher_and_scripts(tmp_path_factory, clone, cache):
    """The parts of the lifecycle that are about Windows, and only those.

    Two installs rather than six, because a hosted Windows runner charges minutes for each and the
    rest of the sequence -- editable, --pull, --from-git, shadowing -- is platform-independent and
    proven by `test_the_install_and_update_lifecycle` on Linux. What is left here cannot be proven
    anywhere else:

    * the console scripts are real `.exe` launchers, and they start;
    * `ad-update.exe` refuses the CLI half, because pip cannot replace a launcher that is the
      running process, and still serves the halves that do not touch it;
    * uninstall takes the `.exe` files with it.
    """
    v = Venv(str(tmp_path_factory.mktemp("winvenv") / "v"), _url(clone), cache)
    head = _git("rev-parse", "HEAD", cwd=clone)
    v.pip("install", "--no-deps", f"git+{v.repo_url}")

    meta, _out = v.check()
    assert meta["install"] == "git install", meta["install"]
    assert meta["commit"] == head[:12], f"reported {meta['commit']}, clone is at {head[:12]}"

    broken = []
    for name in _scripts():
        path = v.script(name)
        if not os.path.isfile(path):
            broken.append(f"{name}: not installed")
            continue
        out = run_bounded([path, "--version"], cwd=v.work, env=v.env(), timeout=180,
                          label=name + " --version")
        if out.returncode != 0 or not out.stdout.strip():
            lines = out.stdout.strip().splitlines()
            broken.append(f"{name}: exit {out.returncode}, {lines[-1][:160] if lines else 'no output'}")
    assert not broken, "console scripts:\n  " + "\n  ".join(broken)

    # the scripts are in the venv, which is deliberately not on this process's PATH -- the
    # `pip install --user` situation on a managed laptop
    assert meta.get("scripts_on_path") == "false", meta.get("scripts_on_path")
    assert "not on PATH" in meta.get("hint", ""), meta.get("hint")
    assert "python -m agentdata" in meta.get("hint", ""), "the hint must name the form that works"

    # the launcher refuses the CLI half, and says what to run instead
    launcher = v.script("ad-update")
    assert os.path.isfile(launcher), "the ad-update launcher was not installed"
    out = run_bounded([launcher, "--cli"], cwd=v.work, env=v.env(), timeout=300,
                      label="ad-update.exe --cli")
    refusal = toon_read.meta(out.stdout)
    assert out.returncode == 2, f"exit {out.returncode}: {out.stdout}"
    assert refusal.get("refused") == "true", refusal
    assert "-m agentdata update" in refusal.get("hint", ""), refusal.get("hint")
    assert os.path.isfile(launcher), "the launcher was touched by a command that refused"

    # ...and the half that goes nowhere near the launcher still works from it
    out = run_bounded([launcher, "--check"], cwd=v.work, env=v.env(), timeout=300,
                      label="ad-update.exe --check")
    assert out.returncode == 0, f"--check from the launcher: {out.stdout}"

    # uninstall takes the launchers with it
    v.pip("uninstall", "-y", "agentdata")
    left = [n for n in _scripts() if os.path.isfile(v.script(n))]
    assert not left, f"still installed after uninstall: {', '.join(left)}"


# ------------------------------------------------------------- Windows, without needing a venv


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
