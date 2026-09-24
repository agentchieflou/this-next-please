"""Subprocesses that import the checkout under test, not whatever `agentdata` site-packages holds (#297).

A test that spawns `python -m agentdata ...` with `cwd=tmp_path` imports `agentdata` only if it is
installed or on `PYTHONPATH`. On an uninstalled checkout that was 73 failures reading
`No module named agentdata`, none of them about the code; with an older non-editable install in
site-packages it was worse, a green run of the wrong copy. Every such spawn goes through here.
"""
from __future__ import annotations
import os
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def agentdata_env(extra=None):
    """A copy of `os.environ` plus `extra`, with the checkout first on `PYTHONPATH`, never twice."""
    env = dict(os.environ)
    if extra:
        env.update(extra)
    parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    parts = [p for p in parts if os.path.normcase(os.path.abspath(p)) != os.path.normcase(REPO_ROOT)]
    env["PYTHONPATH"] = os.pathsep.join([REPO_ROOT, *parts])
    return env


def run_agentdata(args, *, cwd, timeout=120, env=None, input=None):
    """Run `args` (a full argv, `sys.executable, "-m", "agentdata..."`) against the checkout.

    Returns `(rc, out, err)` as UTF-8 text, undecodable bytes replaced.
    """
    p = subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=agentdata_env(env), input=input)
    return p.returncode, p.stdout, p.stderr
