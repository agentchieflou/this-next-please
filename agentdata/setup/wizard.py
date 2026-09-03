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

from .. import textio
from .. import config as C
from .. import toon
from ..console import eprint, prompt as _console_prompt, utf8_stdout
from .. import color
from .. import proc
from .. import ui

STATUS_ORDER = {"fail": 0, "warn": 1, "skip": 2, "ok": 3}


def has_tty() -> bool:
    """Is there a human to answer? A piped run (Luna's terminal, CI, `< /dev/null`) has nobody."""
    try:
        return bool(sys.stdin) and sys.stdin.isatty()
    except Exception:  # noqa: BLE001
        return False


@dataclass
class Check:
    step: str
    name: str
    status: str  # ok | warn | fail | skip
    detail: str = ""
    hint: str = ""
    keys: tuple[str, ...] = ()   # prompt keys (or prefixes) `ad-setup --patch` re-asks. EMPTY = no answer fixes
                                 # this row (install a package, create an ODBC DSN, get a TGT): --patch lists it
                                 # under `manual` with its hint instead of asking pointless questions.

    def row(self) -> list:
        return [self.step, self.name, color.status(self.status), self.detail, self.hint]

    def plain_row(self) -> list:
        return [self.step, self.name, self.status, self.detail, self.hint]

    def scope(self) -> tuple[str, ...]:
        return self.keys


class Detectors:
    """Everything that touches the machine or the network, so tests can replace it wholesale."""

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def exists(self, p: str) -> bool:
        return bool(p) and os.path.exists(C.expand(p))

    def read_json(self, p: str) -> Any:
        return json.loads(textio.read_text(C.expand(p)))

    def read_text(self, p: str) -> str:
        return textio.read_text(C.expand(p))

    def write_text(self, p: str, text: str) -> None:
        os.makedirs(os.path.dirname(C.expand(p)) or ".", exist_ok=True)
        with open(C.expand(p), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def glob(self, pattern: str, root: str = ".") -> list[str]:
        return sorted(_glob.glob(os.path.join(root, pattern), recursive=True))

    def run(self, args: list[str], timeout: int = 120) -> tuple[int, str, str]:
        # `az` is az.cmd and `pncli` is pncli.cmd on Windows: proc resolves PATHEXT + npm shims (never bare CreateProcess)
        try:
            rc, out, err, _el = proc.run(args, timeout=timeout)
        except proc.ProcError as e:
            return (124 if e.code == "timeout" else 127), "", f"{args[0]}: {e.msg}"
        return rc, out, err

    def run_interactive(self, args: list[str]) -> int:
        try:
            return subprocess.call(proc.command(args))
        except (proc.ProcError, FileNotFoundError):
            return 127

    def launcher(self, name: str, exe: str | None = None) -> dict:
        """How `name` resolves, plus `--version` proof that it starts. Faked wholesale in tests."""
        info = proc.resolve(name, exe=exe)
        if info["found"]:
            # probe the path we resolved: a pinned launcher is usually NOT on PATH, so the bare name would fail
            rc, out, err = self.run([info["path"], "--version"], timeout=60)
            lines = (out or err).strip().splitlines()
            info["rc"], info["version"] = rc, (lines[0][:60] if lines else "")
        return info

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


class ScopedPrompter(Prompter):
    """`ad-setup --patch`: prompt only for the keys a failing check named. Every other question silently keeps its
    stored answer (the steps always pass the current value as the default), so one bad setting costs one question."""

    def __init__(self, inner: Prompter, scope, reasons: dict | None = None) -> None:
        super().__init__()
        self.inner, self.scope, self.reasons = inner, tuple(scope), dict(reasons or {})
        self.asked: list[str] = []
        self.said = getattr(inner, "said", [])

    def in_scope(self, key: str) -> bool:
        return any(key == s or key.startswith(s) for s in self.scope)

    def _why(self, key: str) -> None:
        for s, why in list(self.reasons.items()):
            if why and (key == s or key.startswith(s)):
                self.inner.say(f"  ! {why}")
                self.reasons[s] = ""

    def ask(self, key, text, default=None, choices=None, secret=False):
        if not self.in_scope(key):
            return str(default) if default not in (None, "") else (choices[0] if choices else "")
        self._why(key)
        self.asked.append(key)
        return self.inner.ask(key, text, default, choices, secret)

    def confirm(self, key, text, default=False):
        if not self.in_scope(key):
            return default
        self._why(key)
        self.asked.append(key)
        return self.inner.confirm(key, text, default)

    def say(self, text: str) -> None:
        self.inner.say(text)


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

    def add(self, step: str, name: str, status: str, detail: str = "", hint: str = "", keys: tuple[str, ...] = ()) -> None:
        self.checks.append(Check(step, name, status, detail, hint, keys))

    def say(self, text: str) -> None:
        self.ask.say(text)

    def rule(self, title: str) -> None:
        """A step separator. A rule when a person is watching; the old `== title ==` line otherwise, because a
        non-interactive run's transcript ends up in a friction log."""
        if ui.on():
            ui.rule(title)
        else:
            self.say(color.paint(f"\n== {title} ==", "bold"))


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
    text, _meta, _shown, ok = check_report(ctx, source, extra, quiet)
    return text, ok


def check_report(ctx: Context, source: str, extra: dict | None = None,
                 quiet: bool = False) -> tuple[str, dict, list[Check], bool]:
    """One place builds the report, two render it: TOON for whoever is parsing, a table for whoever is reading.
    `meta` is returned unpainted so the pretty renderer can style it itself."""
    checks = sorted(ctx.checks, key=lambda c: (STATUS_ORDER.get(c.status, 9), c.step))
    failed = sum(1 for c in checks if c.status == "fail")
    warned = sum(1 for c in checks if c.status == "warn")
    from ..update import cli_state
    ver = cli_state()
    meta = {"ok": failed == 0, "source": source, "version": ver["version"],
            "commit": ver["commit"] or ("checkout" if ver["editable"] else "n/a"),
            "config": C.display_path(C.path()), "online": ctx.online, "checks": len(checks),
            "failed": failed, "warned": warned}
    if extra:
        meta.update(extra)
    if failed and "hint" not in meta:
        meta["hint"] = "`ad-setup --patch` re-asks only the settings behind the fail rows (nothing else is touched)"
    shown = [c for c in checks if c.status != "ok"] if quiet else checks
    painted = dict(meta)
    if color.enabled():
        painted["ok"] = color.status("true" if failed == 0 else "false")
        painted["failed"] = color.paint(str(failed), *(("red", "bold") if failed else ()))
        painted["warned"] = color.paint(str(warned), "yellow") if warned else warned
    body = toon.table("checks", ["step", "check", "status", "detail", "hint"], [c.row() for c in shown])
    return "\n".join([toon.encode(painted, key="meta"), body]), meta, shown, failed == 0


def print_checks(ctx: Context, source: str, extra: dict | None = None, quiet: bool = False) -> bool:
    """Print the report the way this audience needs it. -> ok"""
    text, meta, shown, ok = check_report(ctx, source, extra, quiet)
    if not ui.on():
        print(text)
        return ok
    scalars = [(k, v) for k, v in meta.items() if k not in ("ok", "source", "error", "hint") and not isinstance(v, (list, dict))]
    ui.facts([("status", ui.status_text("ok" if ok else "fail")), *scalars], title=meta.get("source", source))
    if shown:
        ui.table(["step", "check", "status", "detail", "hint"], [c.plain_row() for c in shown],
                 title=f"{len(shown)} checks" + (" — failures and warnings only" if quiet else ""),
                 status_col=2, wrap=(3, 4), group_col=0)
    for key in ("manual", "needs_answers", "asked", "repairing", "skipped"):
        if isinstance(meta.get(key), list) and meta[key]:
            ui.note(f"{key}: " + "; ".join(str(x) for x in meta[key]))
    if meta.get("error"):
        ui.problem(str(meta["error"]), str(meta.get("hint") or ""), title=source)
    elif meta.get("hint"):
        ui.note(str(meta["hint"]), style="hint")
    return ok


def load_answers(path: str | None, sets: list[str] | None = None) -> dict:
    """--answers JSON (any encoding PowerShell writes: UTF-8 BOM, UTF-16) merged with --set key=value pairs, which win."""
    data: dict = {}
    if path:
        p = C.expand(path)
        if not os.path.isfile(p):
            raise C.ConfigError(f"answers file not found: {path}", hint="pass --set key=value instead of a file")
        try:
            data = textio.read_json(p, "answers file")
        except ValueError as e:
            raise C.ConfigError(str(e), hint="use --set key=value instead of a file, or write the file with "
                                "[IO.File]::WriteAllText (UTF-8 without BOM)") from None
        if not isinstance(data, dict):
            raise C.ConfigError("answers file must be a JSON object", hint='{"project.jira_project": "RDSD"}')
    for item in sets or []:
        if "=" not in item:
            raise C.ConfigError(f"--set expects key=value, got {item!r}", hint="example: --set project.jira_project=RDSD")
        k, v = item.split("=", 1)
        k, v = k.strip(), v.strip()
        data[k] = True if v.lower() == "true" else False if v.lower() == "false" else v
    return data


def run_doctor(argv: list[str] | None = None, det: Detectors | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ad-doctor", description="Offline health check of the agentdata setup. "
                                 "Exit 1 when something fails; every row carries the fix in `hint`.")
    ap.add_argument("--online", action="store_true", help="also run network checks (Jira, SELECT 1, XMLA)")
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                    help="colour output (default auto: on for a terminal, off when piped; NO_COLOR / AGENTDATA_COLOR also apply)")
    ap.add_argument("--quiet", action="store_true", help="show only non-ok rows")
    ap.add_argument("--only", action="append", help="step key(s), comma-separated: pncli,sources,powerbi,project")
    a = ap.parse_args(argv)
    utf8_stdout()
    color.set_enabled(None if a.color == "auto" else a.color == "always")
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
        return 0 if print_checks(ctx, "ad-doctor", quiet=a.quiet) else 1
    except C.ConfigError as e:
        print(toon.encode({"meta": {"ok": False, "source": "ad-doctor", "error": str(e), "hint": e.hint}}))
        ui.problem(str(e), e.hint or "", title="ad-doctor")
        return 2


def run_patch(ctx: Context, steps: list[Step], prompter: Prompter, *, include_warnings: bool = False,
              quiet: bool = False, targets: list[str] | None = None) -> int:
    """Repair mode.

    `ad-setup --patch` checks everything, then re-asks ONLY the settings the failing rows name — fixing one wrong DSN
    costs that env's questions, not the whole wizard. A row with no keys (a missing package, an ODBC DSN that does not
    exist, no Kerberos ticket) is reported under `manual` with its hint: no answer fixes it, so it is never asked.
    `ad-setup --patch sources.oracle` skips the scan and re-asks exactly that area on demand."""
    scope: list[str] = []
    reasons: dict[str, str] = {}
    manual: list[Check] = []
    broken: list[Check] = []
    found: dict[str, dict] = {}

    if targets:
        known = {s.key for s in steps}
        bad = [t for t in targets if t.split(".")[0] not in known]
        if bad:
            raise C.ConfigError("nothing to repair for: " + ", ".join(bad),
                                hint="a target starts with a step key: " + ", ".join(sorted(known)) +
                                     " (e.g. sources.oracle, powerbi.az_exe)")
        scope = list(dict.fromkeys(targets))
        todo = [s for s in steps if any(t.split(".")[0] == s.key for t in targets)]
        for step in todo:
            found[step.key] = step.detect(ctx)
    else:
        for step in steps:
            found[step.key] = step.detect(ctx)
            step.check(ctx, found[step.key])
            if ctx.online:
                step.verify(ctx)          # a failing SELECT 1 is repairable too; --offline skips this
        wanted = ("fail", "warn") if include_warnings else ("fail",)
        hits = [c for c in ctx.checks if c.status in wanted]
        broken = [c for c in hits if c.keys]
        manual = [c for c in hits if not c.keys]
        for c in broken:
            for key in c.scope():
                if key not in scope:
                    scope.append(key)
                reasons.setdefault(key, f"{c.step}/{c.name}: {c.detail}" + (f" — {c.hint}" if c.hint else ""))
        todo = [s for s in steps if any(c.step == s.key for c in broken)]
        if not broken:
            note = ("nothing to repair by answering a question" if manual else "nothing to repair")
            if not include_warnings and any(c.status == "warn" for c in ctx.checks):
                note += "; --include-warnings covers warn rows too"
            extra = {"repaired": 0, "note": note}
            if manual:
                extra["manual"] = [f"{c.step}/{c.name}: {c.detail} -> {c.hint}" for c in manual][:10]
                extra["hint"] = "these need an install or an action, not an answer; run each hint, then ad-doctor"
            print_checks(ctx, "ad-setup --patch", extra=extra, quiet=quiet)
            return 0 if not manual else 1

    if ctx.interactive and not has_tty():
        # dying on EOF at the first prompt taught nobody anything; name the keys instead
        print_checks(ctx, "ad-setup --patch", quiet=quiet, extra={
            "repaired": 0, "error": "no terminal to ask on", "needs_answers": scope[:20],
            "hint": "run it in a terminal, or answer inline: " +
                    " ".join(f"--set {k.rstrip('.')}=<value>" for k in scope[:3]) + " --non-interactive"})
        return 2
    ctx.rule("repairing")
    for c in broken:
        ctx.say(f"  {color.status(c.status)}: {color.paint(c.step + '/' + c.name, 'cyan')} · {c.detail}")
    for c in manual:
        ctx.say(f"  {color.status('skip')}: {c.step}/{c.name} needs an action, not an answer · {c.hint}")
    if targets:
        ctx.say("  " + color.paint("asking for: " + ", ".join(scope), "cyan"))
    scoped = ScopedPrompter(prompter, scope, reasons)
    ctx.ask = scoped
    for step in todo:
        ctx.rule(step.title)
        step.ask(ctx, found[step.key])
        C.save(ctx.cfg)
    ctx.checks = []                      # report the state AFTER the repair, not the rows that led to it
    for step in todo:
        f = step.detect(ctx)
        step.check(ctx, f)
        if ctx.online:
            step.verify(ctx)
    saved = C.save(ctx.cfg)
    extra = {"saved": saved, "was_failing": len(broken) + len(manual), "repaired": len(scoped.asked),
             "asked": scoped.asked[:20]}
    if broken:
        extra["repairing"] = [f"{c.step}/{c.name}: {c.detail}" for c in broken][:10]
    if manual:
        extra["manual"] = [f"{c.step}/{c.name}: {c.detail} -> {c.hint}" for c in manual][:10]
    if targets and not scoped.asked:
        extra["hint"] = "no prompt matched those targets; `ad-setup --only <step>` walks the whole step"
    return 0 if print_checks(ctx, "ad-setup --patch", extra=extra, quiet=quiet) else 1


def run_setup(argv: list[str] | None = None, det: Detectors | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ad-setup", description="Guided setup: import pncli config, data sources "
                                 "(native or ODBC), Power BI tools and workspaces, project stub. Re-run any time; "
                                 "existing values are the defaults. Secrets go to keyring, never to a file.")
    ap.add_argument("--check", action="store_true", help="doctor mode (no prompts, offline); same as ad-doctor")
    ap.add_argument("--patch", nargs="*", metavar="KEY", default=None,
                    help="repair mode: run the checks, then re-ask ONLY the settings behind the rows that fail "
                         "(--include-warnings covers warn rows). Name targets to skip the scan and re-ask just those, "
                         "e.g. `--patch sources.oracle` or `--patch powerbi.az_exe`")
    ap.add_argument("--include-warnings", action="store_true", help="with --patch: repair warn rows as well as fail rows")
    ap.add_argument("--only", action="append", help="step key(s), comma-separated: pncli,sources,powerbi,project")
    ap.add_argument("--non-interactive", action="store_true", help="no prompts: defaults + --set / --answers")
    ap.add_argument("--set", action="append", metavar="KEY=VALUE", help="answer one prompt key inline, e.g. project.jira_project=RDSD "
                    "(repeatable; true/false for yes-no prompts; wins over --answers)")
    ap.add_argument("--answers", help="JSON file of prompt-key -> answer (never passwords); any encoding PowerShell writes is accepted")
    ap.add_argument("--offline", action="store_true", help="skip network verification")
    ap.add_argument("--project", metavar="DIR", help="generate/update a project stub (AGENTS.md, .agent/state.json) in DIR")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                    help="colour output (default auto: on for a terminal, off when piped)")
    a = ap.parse_args(argv)
    utf8_stdout()
    color.set_enabled(None if a.color == "auto" else a.color == "always")
    if a.check:
        rest = ["--quiet"] if a.quiet else []
        for o in a.only or []:
            rest += ["--only", o]
        return run_doctor(rest, det)
    try:
        cfg = C.load()
        interactive = not a.non_interactive
        prompter: Prompter = Prompter() if interactive else AnswerPrompter(load_answers(a.answers, a.set))
        ctx = Context(cfg=cfg, det=det or Detectors(), ask=prompter, online=not a.offline, interactive=interactive,
                      facts=C.project_facts(), project_dir=a.project)
        only = a.only
        if a.project and not only:
            only = ["project"]
        if ui.on() and not a.quiet:
            ui.facts([("config", C.display_path(C.path())), ("network", "online" if ctx.online else "offline"),
                      ("secrets", "keyring only — never a file, never this screen"),
                      ("steps", ", ".join(s.key for s in _select(registry(), only)))], title="agentdata setup")
        else:
            ctx.say(color.paint("agentdata setup", "bold") + f" · config {C.display_path(C.path())} · "
                    f"{'online' if ctx.online else 'offline'} · " + color.paint("secrets → keyring only", "dim"))
        if a.patch is not None:
            return run_patch(ctx, _select(registry(), only), prompter, include_warnings=a.include_warnings,
                             quiet=a.quiet, targets=a.patch or None)
        steps = _select(registry(), only)
        if interactive and not has_tty():
            print(toon.encode({"meta": {"ok": False, "source": "ad-setup", "error": "no terminal to ask on",
                                        "steps": [s.key for s in steps],
                                        "hint": "run it in a terminal, or use --non-interactive with --set key=value "
                                                "(`ad-doctor` lists what is wrong; `ad-setup --patch` repairs just that)"}}))
            return 2
        for step in steps:
            ctx.rule(step.title)
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
        return 0 if print_checks(ctx, "ad-setup", extra=extra, quiet=a.quiet) else 1
    except (C.ConfigError,) as e:
        print(toon.encode({"meta": {"ok": False, "source": "ad-setup", "error": str(e), "hint": e.hint}}))
        ui.problem(str(e), e.hint or "", title="ad-setup")
        return 2
    except (EOFError, KeyboardInterrupt):
        print(toon.encode({"meta": {"ok": False, "source": "ad-setup", "error": "interrupted",
                                    "hint": "progress up to the last completed step was saved; re-run ad-setup"}}))
        return 130
