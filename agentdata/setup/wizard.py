"""Step registry + runners for ad-setup / ad-doctor.

A Step has four hooks: detect() gathers machine facts (no prompts), check() turns them into offline
verdicts (doctor), ask() talks to the user and writes config, verify() does network checks (setup, or
doctor --online). Adding a data source or tool = one new Step module in steps/.
"""
from __future__ import annotations
import argparse
import getpass
import glob as _glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from .. import config as C
from .. import toon
from ..console import eprint, prompt as _console_prompt, utf8_stdout

STATUS_ORDER = {"fail": 0, "warn": 1, "skip": 2, "ok": 3}


@dataclass
class Check:
    step: str
    name: str
    status: str  # ok | warn | fail | skip
    detail: str = ""
    hint: str = ""

    def row(self) -> list:
        return [self.step, self.name, self.status, self.detail, self.hint]


class Detectors:
    """Everything that touches the machine or the network, so tests can replace it wholesale."""

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def exists(self, p: str) -> bool:
        return bool(p) and os.path.exists(C.expand(p))

    def read_json(self, p: str) -> Any:
        with open(C.expand(p), encoding="utf-8") as f:
            return json.load(f)

    def read_text(self, p: str) -> str:
        with open(C.expand(p), encoding="utf-8") as f:
            return f.read()

    def write_text(self, p: str, text: str) -> None:
        os.makedirs(os.path.dirname(C.expand(p)) or ".", exist_ok=True)
        with open(C.expand(p), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def glob(self, pattern: str, root: str = ".") -> list[str]:
        return sorted(_glob.glob(os.path.join(root, pattern), recursive=True))

    def run(self, args: list[str], timeout: int = 120) -> tuple[int, str, str]:
        exe = shutil.which(args[0]) or args[0]  # `az` is az.cmd on Windows
        try:
            p = subprocess.run([exe, *args[1:]], capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            return 127, "", f"{args[0]}: not found"
        except subprocess.TimeoutExpired:
            return 124, "", f"{args[0]}: timed out after {timeout}s"
        return p.returncode, p.stdout, p.stderr

    def run_interactive(self, args: list[str]) -> int:
        exe = shutil.which(args[0]) or args[0]
        try:
            return subprocess.call([exe, *args[1:]])
        except FileNotFoundError:
            return 127

    def module(self, name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    def odbc_drivers(self) -> list[str]:
        from ..connectors import odbc
        return odbc.drivers()

    def odbc_dsns(self) -> dict[str, str]:
        from ..connectors import odbc
        return odbc.data_sources()

    def keyring_backend(self) -> str:
        from ..connectors import secrets
        return secrets.backend_name()

    def has_password(self, source: str, env: str, user: str) -> bool:
        from ..connectors import secrets
        return secrets.has_password(source, env, user)

    def set_password(self, source: str, env: str, user: str, password: str) -> None:
        from ..connectors import secrets
        secrets.set_password(source, env, user, password)

    def smoke(self, source: str, env: str, cfg: dict) -> dict:
        from ..connectors import probe
        return probe.smoke(source, env, cfg)

    def jira_whoami(self, cfg: dict, redetect: bool = False) -> dict:
        """Detect flavor with the pncli token, cache it in cfg, return a small non-secret summary."""
        from ..connectors import jira_api as J
        creds = J.load_credentials(cfg)
        j, me = J.detect_flavor(creds, cfg, redetect=redetect)
        J.remember_flavor(cfg, j)
        return {"base_url": j.creds.base_url, "flavor": j.flavor.kind, "auth": j.flavor.auth, "api": j.flavor.api,
                "token_source": creds.source, "display_name": (me or {}).get("displayName"),
                "account": (me or {}).get("accountId") or (me or {}).get("name")}

    def env(self, name: str) -> str | None:
        return os.environ.get(name)

    def home(self) -> str:
        return os.path.expanduser("~")

    def getuser(self) -> str:
        return getpass.getuser()

    def is_windows(self) -> bool:
        return os.name == "nt"

    def python_bits(self) -> int:
        return 64 if sys.maxsize > 2 ** 32 else 32


class Prompter:
    """Interactive prompts on stderr. Keys are stable identifiers used by AnswerPrompter."""

    def __init__(self) -> None:
        self.unanswered: list[str] = []

    def ask(self, key: str, text: str, default: str | None = None, choices: list[str] | None = None,
            secret: bool = False) -> str:
        if choices:
            text = f"{text} ({'/'.join(choices)})"
        while True:
            ans = _console_prompt(text, default, secret=secret)
            if not choices or ans in choices or ans == "":
                return ans
            eprint(f"  choose one of: {', '.join(choices)}")

    def confirm(self, key: str, text: str, default: bool = False) -> bool:
        ans = self.ask(key, f"{text} [{'Y/n' if default else 'y/N'}]", None)
        if not ans.strip():
            return default
        return ans.strip().lower() in ("y", "yes", "true", "1")

    def say(self, text: str) -> None:
        eprint(text)


class AnswerPrompter(Prompter):
    """Non-interactive: answers from a dict (answers file / tests); missing -> default."""

    def __init__(self, answers: dict | None = None) -> None:
        super().__init__()
        self.answers = dict(answers or {})
        self.said: list[str] = []
        for k in self.answers:
            if C.looks_secret(k):
                raise C.ConfigError(f"answers file must not contain a password/token ({k})",
                                    hint="store passwords in keyring first (interactive ad-setup), then re-run")

    def ask(self, key, text, default=None, choices=None, secret=False):
        if key in self.answers:
            v = self.answers[key]
            if isinstance(v, bool):
                return "y" if v else "n"
            if isinstance(v, list):
                return ",".join(str(x) for x in v)
            return str(v)
        self.unanswered.append(key)
        if default not in (None, ""):
            return str(default)
        return choices[0] if choices else ""

    def confirm(self, key, text, default=False):
        if key in self.answers:
            v = self.answers[key]
            return v if isinstance(v, bool) else str(v).strip().lower() in ("y", "yes", "true", "1")
        self.unanswered.append(key)
        return default

    def say(self, text: str) -> None:
        self.said.append(text)


@dataclass
class Context:
    cfg: dict
    det: Detectors
    ask: Prompter
    online: bool = False
    interactive: bool = True
    facts: dict = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    project_dir: str | None = None

    def add(self, step: str, name: str, status: str, detail: str = "", hint: str = "") -> None:
        self.checks.append(Check(step, name, status, detail, hint))

    def say(self, text: str) -> None:
        self.ask.say(text)


class Step:
    key = ""
    title = ""

    def detect(self, ctx: Context) -> dict:
        return {}

    def check(self, ctx: Context, found: dict) -> None:
        pass

    def ask(self, ctx: Context, found: dict) -> None:
        pass

    def verify(self, ctx: Context) -> None:
        pass


def registry() -> list[Step]:
    from .steps import pncli_import, powerbi, project, sources
    return [pncli_import.PncliStep(), sources.SourcesStep(), powerbi.PowerBIStep(), project.ProjectStep()]


def _select(steps: list[Step], only: list[str] | None) -> list[Step]:
    if not only:
        return steps
    wanted = {x.strip() for item in only for x in item.split(",") if x.strip()}
    unknown = wanted - {s.key for s in steps}
    if unknown:
        raise C.ConfigError(f"unknown step(s): {', '.join(sorted(unknown))}",
                            hint=f"choose from {', '.join(s.key for s in steps)}")
    return [s for s in steps if s.key in wanted]


def render_checks(ctx: Context, source: str, extra: dict | None = None, quiet: bool = False) -> tuple[str, bool]:
    checks = sorted(ctx.checks, key=lambda c: (STATUS_ORDER.get(c.status, 9), c.step))
    failed = sum(1 for c in checks if c.status == "fail")
    warned = sum(1 for c in checks if c.status == "warn")
    meta = {"ok": failed == 0, "source": source, "config": C.display_path(C.path()), "online": ctx.online,
            "checks": len(checks), "failed": failed, "warned": warned}
    if extra:
        meta.update(extra)
    shown = [c for c in checks if c.status != "ok"] if quiet else checks
    body = toon.table("checks", ["step", "check", "status", "detail", "hint"], [c.row() for c in shown])
    return "\n".join([toon.encode(meta, key="meta"), body]), failed == 0


def load_answers(path: str | None) -> dict:
    if not path:
        return {}
    with open(C.expand(path), encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise C.ConfigError("answers file must be a JSON object")
    return data


def run_doctor(argv: list[str] | None = None, det: Detectors | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ad-doctor", description="Offline health check of the agentdata setup. "
                                 "Exit 1 when something fails; every row carries the fix in `hint`.")
    ap.add_argument("--online", action="store_true", help="also run network checks (Jira, SELECT 1, XMLA)")
    ap.add_argument("--quiet", action="store_true", help="show only non-ok rows")
    ap.add_argument("--only", action="append", help="step key(s), comma-separated: pncli,sources,powerbi,project")
    a = ap.parse_args(argv)
    utf8_stdout()
    try:
        cfg = C.load()
        ctx = Context(cfg=cfg, det=det or Detectors(), ask=AnswerPrompter({}), online=a.online, interactive=False,
                      facts=C.project_facts())
        for step in _select(registry(), a.only):
            found = step.detect(ctx)
            step.check(ctx, found)
            if a.online:
                step.verify(ctx)
        if a.online:
            C.save(cfg)
        out, ok = render_checks(ctx, "ad-doctor", quiet=a.quiet)
        print(out)
        return 0 if ok else 1
    except C.ConfigError as e:
        print(toon.encode({"meta": {"ok": False, "source": "ad-doctor", "error": str(e), "hint": e.hint}}))
        return 2


def run_setup(argv: list[str] | None = None, det: Detectors | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ad-setup", description="Guided setup: import pncli config, data sources "
                                 "(native or ODBC), Power BI tools and workspaces, project stub. Re-run any time; "
                                 "existing values are the defaults. Secrets go to keyring, never to a file.")
    ap.add_argument("--check", action="store_true", help="doctor mode (no prompts, offline); same as ad-doctor")
    ap.add_argument("--only", action="append", help="step key(s), comma-separated: pncli,sources,powerbi,project")
    ap.add_argument("--non-interactive", action="store_true", help="no prompts: defaults + --answers")
    ap.add_argument("--answers", help="JSON file of prompt-key -> answer (never passwords)")
    ap.add_argument("--offline", action="store_true", help="skip network verification")
    ap.add_argument("--project", metavar="DIR", help="generate/update a project stub (AGENTS.md, .agent/state.json) in DIR")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    utf8_stdout()
    if a.check:
        rest = ["--quiet"] if a.quiet else []
        for o in a.only or []:
            rest += ["--only", o]
        return run_doctor(rest, det)
    try:
        cfg = C.load()
        interactive = not a.non_interactive
        prompter: Prompter = Prompter() if interactive else AnswerPrompter(load_answers(a.answers))
        ctx = Context(cfg=cfg, det=det or Detectors(), ask=prompter, online=not a.offline, interactive=interactive,
                      facts=C.project_facts(), project_dir=a.project)
        only = a.only
        if a.project and not only:
            only = ["project"]
        ctx.say(f"agentdata setup · config {C.display_path(C.path())} · "
                f"{'online' if ctx.online else 'offline'} · secrets → keyring only")
        for step in _select(registry(), only):
            ctx.say(f"\n== {step.title} ==")
            found = step.detect(ctx)
            step.ask(ctx, found)
            C.save(cfg)  # persist after every step so an aborted run keeps its progress
            if ctx.online:
                step.verify(ctx)
                C.save(cfg)
        saved = C.save(cfg)
        extra = {"saved": saved}
        if getattr(prompter, "unanswered", None):
            extra["unanswered"] = len(prompter.unanswered)
        out, ok = render_checks(ctx, "ad-setup", extra=extra, quiet=a.quiet)
        print(out)
        return 0 if ok else 1
    except (C.ConfigError,) as e:
        print(toon.encode({"meta": {"ok": False, "source": "ad-setup", "error": str(e), "hint": e.hint}}))
        return 2
    except (EOFError, KeyboardInterrupt):
        print(toon.encode({"meta": {"ok": False, "source": "ad-setup", "error": "interrupted",
                                    "hint": "progress up to the last completed step was saved; re-run ad-setup"}}))
        return 130
