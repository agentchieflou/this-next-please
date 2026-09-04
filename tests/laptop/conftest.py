"""Shared machinery for the laptop verification suite.

Every module here is marked `laptop` and skipped unless `AGENTDATA_LAPTOP=1`, so an ordinary
`pytest -q` -- on CI or on anyone's machine -- collects and runs none of it.

The point of the suite is that `docs/windows-verification.md` stops being prose ending in "paste
results back". Each step runs the real command and appends a record to
`.agent/out/verification-<ts>.toon`; that file is what goes into an issue, instead of a photograph
of a terminal that cannot be diffed, searched, or turned into a regression test.
"""
from __future__ import annotations
import os
import sys
import time

import pytest

from agentdata import verification

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.laptop


HERE = os.path.dirname(os.path.abspath(__file__))


def pytest_collection_modifyitems(config, items):  # pragma: no cover - collection hook
    """Skip *this directory's* tests without the env flag.

    A collection hook sees every collected item, not only the ones under the conftest that defines
    it -- so the path check is not decoration; without it this skips the entire suite.
    """
    if verification.enabled():
        return
    skip = pytest.mark.skip(reason=f"set {verification.ENV_FLAG}=1 to run the laptop suite")
    for item in items:
        if str(item.fspath).startswith(HERE):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def recorder():
    """One evidence file per run, written at the end whatever happened."""
    rec = verification.Recorder(verification.path_for(REPO_ROOT))
    yield rec
    path = rec.write()
    print(f"\nverification evidence: {path}")


@pytest.fixture()
def run(recorder, request):
    """Run one command, record it, and hand back (exit_code, stdout, stderr).

    Commands are given in the shell-neutral `python -m agentdata ...` form so the same suite runs
    from Git Bash and from pwsh without a second copy.
    """
    import subprocess

    section = request.module.__name__.rsplit(".", 1)[-1]

    def _run(step: str, args: list[str], *, timeout: int = 300, **paste):
        argv = [sys.executable, "-m", "agentdata", *args]
        started = time.time()
        p = subprocess.run(argv, capture_output=True, text=True, cwd=REPO_ROOT,
                           encoding="utf-8", errors="replace", timeout=timeout)
        elapsed = time.time() - started
        recorder.step(section, step, " ".join(["python", "-m", "agentdata", *args]),
                      p.returncode, detail=(p.stdout or p.stderr or "").strip(),
                      seconds=elapsed, **paste)
        return p.returncode, p.stdout, p.stderr

    return _run


@pytest.fixture()
def ask():
    """Ask the human to do something a command cannot, and wait.

    Uses the console prompt from #67, so it reads from a real terminal rather than echoing into the
    scrollback -- and it is skipped rather than hanging when there is nothing to read from.
    """
    from agentdata import console

    def _ask(instruction: str) -> str:
        if not (sys.stdin and sys.stdin.isatty()):
            pytest.skip("needs a person at a terminal")
        return console.prompt(f"{instruction}\n  press Enter when done (or type `skip`)", default="")

    return _ask
