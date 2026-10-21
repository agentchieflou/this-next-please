"""`tnp`: the this-next-please menu. Setup (data sources, Power BI, this repo, toil's connections), a health check,
the fleet desk, and every `ad-*` command, browsed, searched and run from one place.

Laid out like toil's own menu (`toil` with no arguments), and built on `screen.py`: the wordmark and breadcrumb on
every screen, nothing wider or taller than the terminal, questions answered on the screen. Every setup screen
asks the same questions `ad-setup` asks -- the same steps, one at a time -- says before it starts which command
does the same, and when it is done prints that command with the answers filled in, so a person can script what
they just did.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import Callable, Iterator

from .. import config as C
from .. import facts as F
from .. import textio
from ..setup import jdbc
from ..setup import scope as S
from ..setup import wizard as W
from . import brand as B
from . import commands as K
from . import guide as G
from .prompter import TnpPrompter
from .screen import Back, Quit, Tui, fit, glyph

DOCS_URL = "https://github.com/agentchieflou/this-next-please/blob/main/docs/tnp.md"
Runner = Callable[[list[str], bool], tuple[int, str]]


def run_attached(argv: list[str], capture: bool) -> tuple[int, str]:
    """Run a command with the person's terminal (its own prompts and approvals work), or capture its output."""
    try:
        if capture:
            r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=600, env={**os.environ, "AGENTDATA_COLOR": "never"})
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        return subprocess.run(argv, check=False).returncode, ""
    except KeyboardInterrupt:
        return 130, "interrupted"
    except (OSError, subprocess.SubprocessError) as e:
        return 127, f"{type(e).__name__}: {e}"


class App(Tui):
    def __init__(self, det: W.Detectors | None = None, prompter: W.Prompter | None = None,
                 keys: Iterator[str] | None = None, out=None, cwd: str | None = None, repo: str | None = None,
                 cfg: dict | None = None, height: int | None = None, width: int | None = None,
                 runner: Runner | None = None) -> None:
        super().__init__(keys=keys, out=out, height=height, width=width)
        self.det = det or W.Detectors()
        self.scope = S.detect(cwd, repo)
        self.cfg = C.load() if cfg is None else cfg
        self.prompter = prompter or (TnpPrompter(self) if self.interactive else W.Prompter())
        self.runner = runner or run_attached
        self.form_crumbs: tuple[str, ...] = ()
        self.form_intro: list[str] = []
        self._attention: list[W.Check] | None = None

    # ------------------------------------------------------------------ shared pieces

    def header_lines(self) -> list[str]:
        if self.rows is not None and self.rows < 36:        # a short terminal: the menu before the brand
            return [""] + self.compact_header()
        return [""] + B.wordmark() + [""]

    def cmd_line(self, command: str, note: str = "") -> str:
        return "  " + B.muted("$ ") + B.accent(command) + (B.muted(f"   {note}") if note else "")

    def begin(self, crumbs: tuple[str, ...], stage: str = "", intro: list[str] | None = None) -> None:
        """A new form: the screen every question of one stage is asked on."""
        self.form_crumbs = crumbs
        self.form_intro = ([B.label("  " + stage), ""] if stage else []) + list(intro or [])
        if isinstance(self.prompter, TnpPrompter):
            self.prompter.begin()

    def say(self, line: str) -> None:
        """A line into the current form (or onto the output, off a terminal)."""
        if isinstance(self.prompter, TnpPrompter):
            self.prompter.say(line)
        else:
            self.out.write(line + "\n")

    def context(self, online: bool = False, scope: S.Scope | None = None) -> W.Context:
        where = scope or self.scope
        return W.Context(cfg=self.cfg, det=self.det, ask=self.prompter, online=online,
                         interactive=not isinstance(self.prompter, W.AnswerPrompter),
                         facts=C.project_facts(where.agents_md) if where.agents_md else {}, scope=where)

    def save(self) -> str:
        return C.display_path(C.save(self.cfg))

    def show(self, crumbs: tuple[str, ...], body: list[str], actions: list[tuple[str, str]] | None = None) -> int:
        """A result: scrolls when long; Enter (or the action's digit) returns the action, Esc goes back."""
        return self.pager(crumbs, body, actions)

    def busy(self, crumbs: tuple[str, ...], text: str) -> None:
        if self.tty:
            self.draw(crumbs, [B.muted(f"  {text}")], [], "working…")

    def replay(self, only: str, extra: list[str] | None = None) -> str:
        """The `ad-setup` line that repeats what was just answered: every key and answer, secrets left out."""
        sets = []
        if isinstance(self.prompter, TnpPrompter):
            sets = [f"--set {shlex.quote(f'{k}={v}')}" for k, v in self.prompter.answers.items()
                    if not k.startswith("tnp.")]
        return " ".join(["ad-setup --non-interactive", f"--only {only}", *(extra or []), *sets])

    # ------------------------------------------------------------------ home

    def counts(self) -> tuple[int, int]:
        conns = sum(len(C.get(self.cfg, f"sources.{s}.envs", {}) or {}) for s in C.SOURCES)
        toil = len((self.det.toil(self.cfg) or {}).get("connections") or [])
        return conns, toil

    def tested(self) -> str:
        stamps = [v for v in (self.cfg.get("verified") or {}).values() if isinstance(v, str)]
        return f"last tested {max(stamps)}" if stamps else "not tested yet"

    def attention(self) -> list[W.Check]:
        """Offline rows for what the home screen can afford to check: toil, the data sources, this repo."""
        if self._attention is None:
            from ..setup.steps import repo, sources, toil
            ctx = self.context()
            for step in (toil.ToilStep(), sources.SourcesStep(), repo.RepoStep()):
                try:
                    step.check(ctx, step.detect(ctx))
                except Exception as e:  # noqa: BLE001 -- one broken step must not hide the menu
                    ctx.add(step.key, step.key, "fail", f"{type(e).__name__}: {e}", f"ad-doctor --only {step.key}")
            order = {"fail": 0, "warn": 1}
            self._attention = sorted([c for c in ctx.checks if c.status in order], key=lambda c: order[c.status])
        return self._attention

    def branch(self) -> tuple[str, str]:
        def git(*args: str) -> str:
            try:
                r = subprocess.run(["git", "-C", self.scope.root, *args], capture_output=True, text=True, timeout=5)
                return r.stdout.strip() if r.returncode == 0 else ""
            except (OSError, subprocess.SubprocessError):
                return ""
        return git("rev-parse", "--abbrev-ref", "HEAD"), git("remote", "get-url", "origin")

    def home_body(self) -> list[str]:
        from ..update import version
        conns, toil = self.counts()
        att = self.attention()
        fails = sum(c.status == "fail" for c in att)
        warns = len(att) - fails
        state = " · ".join(x for x in ((f"{fails} to fix" if fails else ""),
                                       (f"{warns} warning{'s' * (warns != 1)}" if warns else "")) if x)
        compact = self.rows is not None and self.rows < 36
        out = ([] if compact else ["  " + B.gradient(B.NAME, bold=True), ""]) + [
               B.muted(f"  agentdata {version()} · {state or 'no warnings'} · {conns} data connection"
                       f"{'s' * (conns != 1)} · toil {toil} connection{'s' * (toil != 1)} · {self.tested()}"), ""]
        sc = self.scope
        label = {"repo": f"repo {sc.name}", "folder": f"folder of {len(sc.repos)} repos — a machine-wide setup",
                 "machine": "machine — no repo here"}[sc.kind]
        out.append(self.fact("Scope", label))
        if sc.kind == "repo":
            out.append(self.fact("Repo", textio.norm_path(sc.root)))
            br, remote = self.branch()
            if br:
                out.append(self.fact("Branch", br + (B.muted(f"  from {remote}") if remote else "")))
        else:
            out.append(self.fact("Folder", textio.norm_path(sc.root)))
        for what, where in sc.writes():
            out.append(self.fact("Writes", B.muted(f"{what}: ") + where))
        out.append("")
        if att:
            out.append(self.heading("Needs attention"))
            room = self.rows
            show = 4 if room is None else max(min(4, room - 30), 1)
            out += [self.check_line(c) for c in att[:show]]
            if len(att) > show:
                out.append(B.muted(f"    … {len(att) - show} more under Health check"))
        return out

    def home_items(self) -> list[tuple[str, str, Callable[[], None]]]:
        sc = self.scope
        repo_item = {"repo": ("This repo", f"Which environments and Power BI targets {sc.name} uses (its AGENTS.md)"),
                     "folder": ("Repos in this folder", f"{len(sc.repos)} repos: what each uses; set one up"),
                     "machine": ("Repos", "No repo here: how a repo gets its own settings")}[sc.kind]
        return [
            ("Test connections", "One query against each data source, one read against each toil connection",
             self.test_connections),
            ("Data sources", "Teradata, Hive, Impala, Oracle, Spark: add, change, test", self.data_sources),
            ("Power BI", "This machine's tools and sign-in; the models and reports each repo changes", self.power_bi),
            (*repo_item, self.repos),
            ("Service connections", "Jira, Confluence, Bitbucket, GitHub, set up in toil", self.services),
            ("Commands", "Browse, search and run every ad-* command", self.commands),
            ("Fleet desk", "Open the agents' desk in the browser, or start one", self.fleet),
            ("Health check", "Every check ad-doctor runs, with the fix for each", self.health),
            ("Help", "How tnp works, where each answer is written, keys, the docs", self.help),
            ("Quit", "Back to your shell", self._quit),
        ]

    @staticmethod
    def _quit() -> None:
        raise Quit

    def run(self) -> int:
        from . import keys
        if not self.tty:
            return self._run()
        with keys.held():
            self.out.write("\x1b[?25l")                         # no blinking cursor over a menu
            try:
                return self._run()
            finally:
                self.out.write("\x1b[?25h\x1b[2J\x1b[H")
                self.out.flush()

    def _run(self) -> int:
        self.busy((), "Reading this machine: connections, toil, this repo…")
        try:
            while True:
                items = self.home_items()
                i = self.choose((), [(a, b) for a, b, _ in items], body=self.home_body(), home=True)
                if isinstance(self.prompter, TnpPrompter):
                    self.prompter.reset()
                try:
                    items[i][2]()
                except Back:
                    pass
                self._attention = None
        except (Quit, StopIteration, EOFError):
            return 0
        except KeyboardInterrupt:
            self.out.write("\n")
            return 130

    def loop(self, crumbs: tuple[str, ...], items: Callable[[], list[tuple[str, str, Callable[[], None]]]],
             body: Callable[[], list[str]]) -> None:
        """A menu screen: pick, run, come back here; Esc leaves."""
        while True:
            entries = items()
            try:
                i = self.choose(crumbs, [(a, b) for a, b, _ in entries], body=body())
            except Back:
                return
            if isinstance(self.prompter, TnpPrompter):
                self.prompter.reset()
            try:
                entries[i][2]()
            except Back:
                pass

    # ------------------------------------------------------------------ test connections

    def test_connections(self) -> None:
        from ..setup.steps import sources, toil
        crumbs = ("Test connections",)
        self.busy(crumbs, "Connecting: a SELECT 1 per data source, one authenticated read per toil connection…")
        ctx = self.context(online=True)
        for step in (sources.SourcesStep(), toil.ToilStep()):
            step.verify(ctx)
        C.save(self.cfg)
        body = [self.cmd_line("ad-doctor --online --only sources,toil"), ""]
        body += self.check_rows(ctx.checks) or ["  Nothing to test yet: add a connection under Data sources, "
                                                "or in toil."]
        self.show(crumbs, body + self.command_lines("ad-doctor --online --only sources,toil"))

    # ------------------------------------------------------------------ data sources

    def envs(self, s: str) -> dict:
        return dict(C.get(self.cfg, f"sources.{s}.envs", {}) or {})

    def data_sources(self) -> None:
        from ..setup.steps.sources import LABEL
        self.loop(("Data sources",),
                  lambda: [(LABEL[s], ", ".join(self.envs(s)) or "none yet", lambda s=s: self.source(s))
                           for s in C.SOURCES],
                  lambda: self.wrap("Connections are machine-wide: add one once and every repo on this machine can "
                                    "use it. Each repo says which one it reads in its AGENTS.md (This repo).") + [""])

    def source(self, s: str) -> None:
        from ..setup.steps.sources import LABEL, SourcesStep
        g = G.SOURCES[s]

        def items():
            envs = list(self.envs(s))
            out = [("Add a connection", "Walks you through it; paste a JDBC URL to skip most questions",
                    lambda: self.add_connection(s))]
            out += [(f"Change {e}", "Asks again, with today's answers as the defaults",
                     lambda e=e: self.add_connection(s, e)) for e in envs]
            if envs:
                out += [("Test", f"SELECT 1 against each {LABEL[s]} connection", lambda: self.test_source(s)),
                        ("Remove a connection", "Deletes it from the machine config",
                         lambda: self.remove_connection(s))]
            return out

        def body():
            ctx = self.context()
            step = SourcesStep()
            step.check(ctx, step.detect(ctx))
            mine = [c for c in ctx.checks if c.name.startswith(f"{s}:")]
            out = self.wrap(g["what"]) + ["", self.heading("Have ready")]
            for h in g["have"]:
                out += self.bullet(h)
            out += [self.heading("Where to find it")] + self.wrap(g["find"], indent=4) + [""]
            if mine:
                out += [self.heading("On this machine")] + [self.check_line(c) for c in mine]
            return out

        self.loop(("Data sources", LABEL[s]), items, body)

    def add_connection(self, s: str, env: str | None = None) -> None:
        from ..setup.steps.sources import LABEL, SourcesStep
        g = G.SOURCES[s]
        sc = self.scope
        repo_step = sc.kind == "repo" and os.path.exists(sc.agents_md)
        crumbs = ("Data sources", LABEL[s], f"Change {env}" if env else "Add a connection")
        stages = (["name", "JDBC URL"] if env is None else []) + ["connection details", "test"] + \
                 (["this repo"] if repo_step else [])
        n = len(stages)

        def stage(title: str) -> str:
            return f"Step {stages.index(title) + 1} of {n}: {title}"

        same = self.cmd_line("ad-setup --only sources", "asks the same, for every connection")
        ask = self.prompter
        filled: dict = {}
        if env is None:
            self.begin(crumbs, stage("name"), [same, ""] + self.wrap(
                "Then: " + " · ".join(g["questions"][1:]), muted=True) + [""])
            existing = self.envs(s)
            env = ask.ask(f"tnp.{s}.name", f"Name for this {LABEL[s]} connection (prod, uat, ...)",
                          "" if existing else "prod").strip()
            if not env:
                return
            if env in existing and not ask.confirm(f"tnp.{s}.overwrite", f"{env} exists. Change it?", True):
                return
            self.begin(crumbs, stage("JDBC URL"), [same, ""] + self.wrap(
                f"Paste the JDBC URL your SQL tool shows (DBeaver, SQL Developer, Hue), and the answers it holds "
                f"become the defaults. e.g. {jdbc.EXAMPLE[s]}", muted=True) + [""])
            url = ask.ask(f"tnp.{s}.jdbc", "JDBC URL (blank = type every answer yourself)", "").strip()
            if url:
                try:
                    filled = jdbc.parse(s, url)
                except ValueError as e:
                    self.say(f"  {glyph('warn')} {e}. Carrying on without it.")
                else:
                    C.put_leaf(self.cfg, f"sources.{s}.envs", env, {**(existing.get(env) or {}), **filled})
        from_url = ["  " + glyph("ok") + " From the URL: " + ", ".join(f"{k} {v}" for k, v in filled.items()
                                                                      if k != "mode"), ""] if filled else []
        self.begin(crumbs + (env,), stage("connection details"), [same, ""] + from_url)
        ctx = self.context()
        step = SourcesStep()
        step.ask_env(ctx, step.detect(ctx), s, env)
        where = self.save()
        result = [x for x in from_url if x] + [f"  {glyph('ok')} Saved {s}:{env} to the machine config ({where})."]
        result += self.check_rows([c for c in ctx.checks if c.status != "ok"])
        replay = self.replay("sources")

        self.begin(crumbs + (env,), stage("test"), result + [""])
        if ask.confirm(f"tnp.{s}.test", f"Test {s}:{env} now (SELECT 1)?", True):
            self.busy(crumbs + (env,), f"Connecting to {s}:{env}…")
            result += self.smoke_lines(s, env)
        if repo_step:
            fact = S.SOURCE_FACT[s]
            self.begin(crumbs + (env,), stage("this repo"), result + [""])
            current = C.project_facts(sc.agents_md).get(fact)
            if current != env and ask.confirm(
                    f"tnp.{s}.repo", f"Make {env} the {LABEL[s]} environment {sc.name} reads "
                                     f"({fact} in {textio.norm_path(sc.agents_md)})?", not current):
                F.set_facts(sc.agents_md, {fact: env})
                result.append(f"  {glyph('ok')} {fact}: {env} written to {textio.norm_path(sc.agents_md)}")
        self.show(crumbs + (env,), result + self.command_lines(
            replay, g["test"].replace("<env>", env).replace("<name>", env)))

    def smoke_lines(self, s: str, env: str) -> list[str]:
        try:
            r = self.det.smoke(s, env, self.cfg)
        except Exception as e:  # noqa: BLE001 -- a driver's own error is the message a person needs
            out = [f"  {glyph('fail')} {s}:{env}  {type(e).__name__}: {str(e)[:160]}"]
            if isinstance(e, C.ConfigError):                    # ours: it already says what to do
                return out + (self.wrap(f"fix: {e.hint}", indent=6, muted=True) if e.hint else [])
            for sign, fix in G.SOURCES[s]["fails"]:
                out += self.wrap(f"if it says {sign}: {fix}", indent=6, muted=True)
            return out
        C.stamp(self.cfg, f"{s}:{env}")
        C.save(self.cfg)
        return [f"  {glyph('ok')} {s}:{env}  answered in {r.get('elapsed_s', '?')}s"]

    def test_source(self, s: str) -> None:
        crumbs = ("Data sources", s, "Test")
        self.busy(crumbs, f"Connecting to every {s} connection…")
        body = [self.cmd_line("ad-doctor --online --only sources"), ""]
        for env in self.envs(s):
            body += self.smoke_lines(s, env)
        self.show(crumbs, body)

    def remove_connection(self, s: str) -> None:
        envs = list(self.envs(s))
        self.begin(("Data sources", s, "Remove"), "", [])
        name = self.prompter.ask(f"tnp.{s}.remove", "Which connection", envs[0], envs)
        if name in envs and self.prompter.confirm(f"tnp.{s}.remove_ok", f"Remove {s}:{name} from the machine "
                                                  "config? Repos that read it will say so in Health check.", False):
            (C.get(self.cfg, f"sources.{s}.envs") or {}).pop(name, None)
            self.save()

    # ------------------------------------------------------------------ Power BI

    def power_bi(self) -> None:
        sc = self.scope

        def items():
            out = [("This machine", "Tools, sign-in and the workspaces this account can reach", self.pbi_machine)]
            if sc.kind == "repo":
                out.append((f"{sc.name}'s models and reports",
                            "Which workspaces, semantic models and reports this repo changes",
                            lambda: self.pbi_repo(sc)))
            elif sc.kind == "folder":
                out.append(("A repo's models and reports", "Pick the repo, then its workspaces, models, reports",
                            lambda: self.pbi_repo(self.pick_repo(("Power BI",)))))
            return out

        def body():
            out = self.wrap(G.POWER_BI["why"]) + ["", self.heading("This machine", "(machine config, once)")]
            for line in G.POWER_BI["machine"]:
                out += self.bullet(line)
            out.append(self.heading("Each repo", "(its AGENTS.md, only the repos that need it)"))
            for line in G.POWER_BI["repo"]:
                out += self.bullet(line)
            out.append("")
            if sc.kind == "repo" and os.path.exists(sc.agents_md):
                out += self.target_lines(sc.agents_md)
            elif sc.kind == "folder":
                with_pbi = [r for r in (S.repo_summary(r, self.cfg) for r in sc.repos) if r["pbi_targets"]]
                out.append(self.heading("Repos here with Power BI targets") + "  " +
                           (", ".join(f"{r['name']} ({r['pbi_targets']})" for r in with_pbi) or "none yet"))
            return out

        self.loop(("Power BI",), items, body)

    def pbi_machine(self) -> None:
        from ..setup.steps import powerbi
        crumbs = ("Power BI", "This machine")
        self.begin(crumbs, "Tools, sign-in, workspaces", [
            self.cmd_line("ad-setup --only powerbi", "asks the same"),
            B.muted(f"  Writes: the machine config ({C.display_path(C.path())})"), ""])
        ctx = self.context(online=True)
        step = powerbi.PowerBIStep()
        step.ask(ctx, step.detect(ctx))
        self.save()
        self.show(crumbs, self.check_rows(ctx.checks, only_problems=True) + self.command_lines(
            self.replay("powerbi")))

    def pbi_repo(self, target: S.Scope | None) -> None:
        from ..setup.steps import repo
        if target is None:
            return
        crumbs = ("Power BI", target.name)
        ctx = self.context(online=True, scope=target)
        step = repo.RepoStep()
        found = step.detect(ctx)
        if not found.get("exists"):
            if self.show(crumbs, self.wrap(f"{target.name} has no AGENTS.md yet, so there is nowhere to write its "
                                           "Power BI targets. Setting the repo up creates it, then asks about "
                                           "Power BI."), [("Set the repo up", f"Creates {target.name}/AGENTS.md "
                                                                             "from the project stub")]) == 0:
                self.repo_setup(target)
            return
        self.begin(crumbs, "Workspaces, then each one's semantic models and reports", [
            self.cmd_line(self.repo_command(target), "asks the same"),
            B.muted(f"  Writes: {textio.norm_path(target.agents_md)} (## Power BI targets)"), ""])
        step._ask_pbi(ctx, found)
        self.show(crumbs, self.check_rows(ctx.checks) + [""] + self.target_lines(target.agents_md) +
                  self.command_lines(self.replay("repo", [] if target is self.scope else
                                                 ["--repo", shlex.quote(target.name)])))

    def target_lines(self, md: str) -> list[str]:
        rows = F.pbi_targets(md)
        out = [self.heading("Power BI targets", f"({textio.norm_path(md)})")]
        if not rows:
            out.append("    none: this repo does not change Power BI")
        for n, t in enumerate(rows, 1):
            what = " / ".join(x for x in (t["workspace"], t["model"], t["report"]) if x)
            ids = "" if t["ws_id"] and (t["ds_id"] or not t["model"]) else B.muted("  (ids not looked up yet)")
            out.append(f"    {n}. {what}{ids}")
        return out

    # ------------------------------------------------------------------ repos

    def repo_command(self, target: S.Scope) -> str:
        return "ad-setup --only repo" if target is self.scope else f"ad-setup --repo {shlex.quote(target.name)}"

    def pick_repo(self, crumbs: tuple[str, ...]) -> S.Scope | None:
        sc = self.scope
        if not sc.repos:
            return None
        items = []
        for r in (S.repo_summary(r, self.cfg) for r in sc.repos):
            if not r["agents_md"]:
                items.append((r["name"], "no AGENTS.md yet"))
                continue
            used = ", ".join(f"{s} {e}" for s, e in r["sources"].items()) or "no data sources"
            pbi = f" · {r['pbi_targets']} Power BI" if r["pbi_targets"] else ""
            bad = f" · missing here: {', '.join(r['unknown'])}" if r["unknown"] else ""
            items.append((r["name"], used + pbi + bad))
        i = self.choose(crumbs + ("Pick a repo",), items, body=self.wrap(
            f"{len(items)} repos in {textio.norm_path(sc.root)}. What each one reads comes from its AGENTS.md.")
            + [""])
        root = sc.repos[i]
        return S.Scope("repo", sc.cwd, root, [root])

    def repos(self) -> None:
        sc = self.scope
        if sc.kind == "machine":
            self.show(("Repos",), self.wrap(G.SCOPES["machine"]) + [""] + self.wrap(
                "Run tnp inside a repo, or in the folder that holds your repos (PycharmProjects), to give a repo "
                "its own settings. Or: `tnp --repo <path>`."))
            return
        if sc.kind == "repo":
            self.repo_setup(sc)
            return
        while True:
            try:
                target = self.pick_repo(("Repos in this folder",))
            except Back:
                return
            try:
                self.repo_setup(target)
            except Back:
                pass

    def repo_setup(self, target: S.Scope | None) -> None:
        from ..setup.steps import repo
        if target is None:
            return
        crumbs = ("This repo" if target is self.scope else "Repos in this folder", target.name)
        self.begin(crumbs, "Which environment of each source it reads, then its Power BI targets", [
            self.cmd_line(self.repo_command(target), "asks the same"),
            B.muted(f"  Writes only {textio.norm_path(target.agents_md)}. Connections stay machine-wide."), ""])
        ctx = self.context(online=True, scope=target)
        step = repo.RepoStep()
        step.ask(ctx, step.detect(ctx))
        ctx.checks.clear()
        step.check(ctx, step.detect(ctx))
        extra = [] if target is self.scope else ["--repo", shlex.quote(target.name)]
        self.show(crumbs, self.check_rows(ctx.checks) + self.command_lines(
            self.replay("repo", extra), "ad-doctor --only repo" + (f" --repo {shlex.quote(target.name)}"
                                                                  if extra else "")))

    # ------------------------------------------------------------------ toil services

    def services(self) -> None:
        from ..setup.steps import toil

        def body():
            found = self.det.toil(self.cfg) or {}
            conns = found.get("connections") or []
            out = self.wrap(G.SERVICES["what"]) + [""]
            if found.get("error"):
                out.append(f"  {glyph('fail')} {found['error']}")
                out += self.wrap(f"fix: {found.get('fix') or toil.T.install_hint(self.cfg)}", indent=6, muted=True)
            elif not conns:
                out.append("  toil has no connections yet.")
            else:
                out.append(B.label(f"  {'NAME':<18} {'AREA':<16} {'HOST':<28} {'WRITES':<10} DEFAULT"))
                for c in conns:
                    out.append(f"  {str(c.get('name')):<18} {str(c.get('area')):<16} "
                               f"{str(c.get('host') or '-'):<28} {'on' if c.get('writes') else 'read only':<10} "
                               f"{'yes' if c.get('isDefault') else ''}")
            return out + [""] + self.wrap(G.SERVICES["add"], muted=True) + self.wrap(G.SERVICES["writes"], muted=True)

        def test():
            crumbs = ("Service connections", "Test")
            self.busy(crumbs, "One authenticated read per connection…")
            ctx = self.context(online=True)
            toil.ToilStep().verify(ctx)
            self.show(crumbs, [self.cmd_line("ad-doctor --online --only toil"), ""] + self.check_rows(ctx.checks)
                      + self.command_lines("ad-doctor --online --only toil", "toil connections test <name>"))

        self.loop(("Service connections",),
                  lambda: [("Open toil", "Add a connection, sign in again, turn writes on", self.launch_toil),
                           ("Test them", "One authenticated read per connection", test)], body)

    def launch_toil(self) -> None:
        from .. import proc
        from ..connectors import toil as T
        found = self.det.toil(self.cfg) or {}
        if not (found.get("where") or {}).get("found"):
            self.show(("Service connections", "Open toil"), self.wrap(f"toil is not installed. {T.install_hint(self.cfg)}"))
            return
        if self.tty:
            self.out.write("\x1b[2J\x1b[H" + B.muted("  Opening toil. Quit it (q) to come back to tnp.\n"))
            self.out.flush()
        from . import keys
        try:
            self.out.write("\x1b[?25h")
            with keys.released():
                subprocess.run(proc.command(["toil"], exe=T.exe(self.cfg), path=T.search_path()), check=False)
            self.out.write("\x1b[?25l")
        except (OSError, KeyboardInterrupt) as e:
            self.show(("Service connections", "Open toil"), [f"  could not start toil: {e}"])
        if hasattr(self.det, "_toil"):
            del self.det._toil                                   # read them again: toil may have changed them

    # ------------------------------------------------------------------ every ad-* command

    def commands(self) -> None:
        self.busy(("Commands",), "Reading every command's options…")
        roots = K.catalog()
        self.loop(("Commands",),
                  lambda: [("Find a command", "Search every command and subcommand by name or what it does",
                            self.find_command)] +
                          [(c.title, c.help, lambda c=c: self.command(c)) for c in roots],
                  lambda: self.wrap(f"Every ad-* command and its {sum(1 for _ in K.walk()) - len(roots)} "
                                    "subcommands, read from the commands themselves. Pick one to see its "
                                    "arguments and flags, then run it here.") + [""])

    def find_command(self) -> None:
        crumbs = ("Commands", "Find")
        self.begin(crumbs, "", self.wrap('Words to look for in a command or what it does, such as "refresh", '
                                         '"pr" or "sprint".') + [""])
        words = self.prompter.ask("tnp.find", "Find", "")
        hits = K.find(words)
        crumbs = crumbs + (f'"{words}"',)
        if not hits:
            self.show(crumbs, [f"  Nothing matches {words!r}. Try fewer words, or browse the list."])
            return
        self.loop(crumbs, lambda: [(c.title, c.help, lambda c=c: self.command(c)) for c in hits],
                  lambda: [B.muted(f"  {len(hits)} match{'es' * (len(hits) != 1)}"), ""])

    def command(self, cmd: K.Command) -> None:
        crumbs = ("Commands", *cmd.title.split())
        if cmd.children:
            runnable = self._runs_without_subcommand(cmd)
            self.loop(crumbs,
                      lambda: ([(f"Run {cmd.title}", "On its own, without a subcommand",
                                 lambda: self.run_command(cmd))] if runnable else []) +
                              [(c.path[-1], c.help, lambda c=c: self.command(c)) for c in cmd.children],
                      lambda: self.wrap(cmd.help) + [""])
            return
        while True:
            try:
                self.pager(crumbs, self.command_page(cmd), [("Run it", "Asks for its arguments, then flags")])
            except Back:
                return
            try:
                self.run_command(cmd)
            except Back:
                pass

    @staticmethod
    def _runs_without_subcommand(cmd: K.Command) -> bool:
        import argparse
        for a in (cmd.parser._actions if cmd.parser else []):    # noqa: SLF001
            if isinstance(a, argparse._SubParsersAction):        # noqa: SLF001
                return not a.required
        return True

    def command_page(self, cmd: K.Command) -> list[str]:
        pos, opt = cmd.arguments()
        out = self.wrap(cmd.help) + ["", self.cmd_line(cmd.usage.split("\n")[0].strip())]
        out += [B.muted("    " + line.strip()) for line in cmd.usage.split("\n")[1:]]
        if pos:
            out += ["", self.heading("Arguments")]
            for a in pos:
                need = "" if a.nargs in ("?", "*") else B.muted("  required")
                out.append(fit(f"    {a.name:<28} {a.help}", self.cols - 12) + need)
        if opt:
            out += ["", self.heading("Flags")]
            for a in opt:
                flag = ", ".join(a.flags) + (f" <{a.metavar or a.dest}>" if a.takes_value else "")
                choices = f" ({'/'.join(a.choices)})" if a.choices else ""
                need = B.muted("  required") if a.required else ""
                out.append(fit(f"    {flag:<28} {a.help}{choices}", self.cols - (12 if need else 2)) + need)
        return out

    def run_command(self, cmd: K.Command) -> None:
        crumbs = ("Commands", *cmd.title.split(), "Run")
        pos, opt = cmd.arguments()
        self.begin(crumbs, f"$ {cmd.title} …", [])
        values: list[str] = []
        for a in pos:
            optional = a.nargs in ("?", "*")
            label = f"{a.name}" + (" (optional)" if optional else "") + (f": {a.help}" if a.help else "")
            if a.choices:
                got = self.prompter.ask(f"tnp.arg.{a.dest}", label, a.choices[0], a.choices + (["(none)"] if optional
                                                                                              else []))
                got = "" if got == "(none)" else got
            else:
                got = self.prompter.ask(f"tnp.arg.{a.dest}", label, "")
            if got:
                values += shlex.split(got) if a.nargs in ("*", "+") else [got]
            elif not optional:
                self.show(crumbs, [f"  {a.name} is required: nothing was run."])
                return
        for a in [o for o in opt if o.required]:           # a required flag is asked like an argument
            label = f"{a.name}" + (f": {a.help}" if a.help else "")
            got = (self.prompter.ask(f"tnp.flag.{a.dest}", label, a.choices[0], a.choices) if a.choices
                   else self.prompter.ask(f"tnp.flag.{a.dest}", label, ""))
            if not got:
                self.show(crumbs, [f"  {a.name} is required: nothing was run."])
                return
            values += [a.name] + ([got] if a.takes_value else [])
        opt = [o for o in opt if not o.required]
        if opt:
            names = "  ".join(a.flags[0] for a in opt)
            self.begin(crumbs, f"$ {K.shown(cmd, values)} …", self.wrap("Flags: " + names, muted=True) + [""])
            flags = self.prompter.ask("tnp.flags", "Flags (optional; enter runs it)", "")
            try:
                values += shlex.split(flags)
            except ValueError as e:
                self.show(crumbs, [f"  Could not read the flags: {e}. Nothing was run."])
                return
        self.execute(crumbs, cmd, values)

    def execute(self, crumbs: tuple[str, ...], cmd: K.Command, values: list[str]) -> None:
        line = K.shown(cmd, values)
        if self.tty:                                              # the person's own terminal: prompts work
            self.out.write("\x1b[2J\x1b[H\n" + self.crumb_line(crumbs) + "\n\n" + self.cmd_line(line) + "\n\n")
            self.out.flush()
            from . import keys
            self.out.write("\x1b[?25h")
            with keys.released():
                rc, _ = self.runner(K.argv(cmd, values), False)
            self.out.write("\x1b[?25l")
            self.out.write("\n" + B.muted(f"  exit {rc}") + "\n")
            self.out.write(B.muted("  Each step above is a plain command: run it yourself any time.") + "\n\n")
            self.out.write(B.muted("  enter back   q quit"))
            self.out.flush()
            if self.key() in ("q", "Q"):
                raise Quit
            return
        rc, text = self.runner(K.argv(cmd, values), True)
        body = [self.cmd_line(line), ""] + ["  " + x for x in text.rstrip("\n").split("\n")]
        body += ["", B.muted(f"  exit {rc}")] + self.command_lines(line)
        self.show(crumbs, body)

    # ------------------------------------------------------------------ the fleet desk

    def fleet(self) -> None:
        from ..fleet import opener

        def body():
            live = {}
            try:
                live = opener.running()
            except Exception:  # noqa: BLE001 -- a broken record is "not running"
                live = {}
            out = self.wrap("The desk is a page in your browser that shows every agent the fleet runs: what each "
                            "is doing, the writes waiting for your approval, and their replies.") + [""]
            if live:
                out.append(self.fact("Desk", f"running on port {live.get('port')}"))
            else:
                out.append(self.fact("Desk", "not running"))
            return out + [""]

        def run(*args: str) -> Callable[[], None]:
            return lambda: self.execute(("Fleet desk",), K.Command(("fleet", *args[:1]), "", None), list(args[1:]))

        sc = self.scope                     # quickstart scans a folder OF repos: inside one, its parent
        folder = os.path.dirname(sc.root.rstrip("/\\")) if sc.kind == "repo" else sc.root
        self.loop(("Fleet desk",),
                  lambda: [("Open the desk", "In your browser; starts it when it is not running",
                            run("open")),
                           ("Quickstart this folder", f"Scan {textio.norm_path(folder)} for repos, index, serve",
                            run("quickstart", folder)),
                           ("Every fleet command", "Browse ad-fleet's commands",
                            lambda: self.command(next(c for c in K.catalog() if c.path == ("fleet",))))], body)

    # ------------------------------------------------------------------ health and help

    def environment(self) -> list[str]:
        from ..version import version_string
        toil = (self.det.toil(self.cfg) or {}).get("where") or {}
        cfg_path = C.path()
        try:
            keyring = self.det.keyring_backend()
        except Exception:  # noqa: BLE001
            keyring = "unavailable"
        out = [self.fact("agentdata", version_string().replace("agentdata ", "")),
               self.fact("Python", f"{sys.version.split()[0]} at {textio.norm_path(sys.executable)}"),
               self.fact("Config", C.display_path(cfg_path) + ("" if os.path.exists(cfg_path) else
                                                               B.muted("  (not created yet)"))),
               self.fact("Keyring", str(keyring)),
               self.fact("toil", (f"{toil.get('version') or '?'} at {textio.norm_path(toil.get('path') or '')}"
                                  if toil.get("found") else "not found"))]
        sc = self.scope
        out.append(self.fact("Scope", f"{sc.kind} {sc.name}" if sc.kind == "repo" else sc.kind))
        return out

    def health(self) -> None:
        crumbs = ("Health check",)
        self.busy(crumbs, "Checking…")
        ctx = self.context()
        for step in W.registry():
            try:
                step.check(ctx, step.detect(ctx))
            except Exception as e:  # noqa: BLE001
                ctx.add(step.key, step.key, "fail", f"{type(e).__name__}: {e}", f"ad-doctor --only {step.key}")
        ok = sum(c.status in ("ok", "info") for c in ctx.checks)
        problems = len(ctx.checks) - ok
        body = [self.cmd_line("ad-doctor"), ""] + self.environment() + [""]
        body.append(f"  {ok} of {len(ctx.checks)} checks fine." + ("" if problems else "  No warnings."))
        body += [""] + self.check_rows(ctx.checks, only_problems=True)
        body += self.command_lines("ad-doctor", "ad-setup --patch          # asks again only what is wrong")
        actions = [("Repair", "Asks again only the settings behind the rows above (ad-setup --patch)")] if problems \
            else None
        if self.show(crumbs, body, actions) == 0 and actions:
            setup = next(c for c in K.catalog() if c.path == ("setup",))
            self.execute(crumbs + ("Repair",), setup, ["--patch"])

    def help(self) -> None:
        from ..update import version
        body = [self.heading("How tnp works")]
        body += self.wrap("tnp is the menu over this-next-please. Setup screens ask the questions ad-setup asks and "
                          "write the same files; Commands runs any ad-* command; the fleet desk opens the agents' "
                          "page. Every screen says which command does the same, so anything done here can be "
                          "scripted or handed to an agent.")
        body += ["", self.heading("Where things are written")] + self.wrap(G.SCOPES[self.scope.kind])
        for what, why in G.WHERE:
            body += self.wrap(f"{what}: {why}", indent=4, hang=2)
        body += ["", self.heading("Keys")]
        body += ["    up/down or j/k   move          enter      select / go on",
                 "    1-9              jump          space      tick a box",
                 "    esc, backspace   back          ctrl-u     clear a field",
                 "    q                quit tnp      pgup/pgdn  scroll a long page"]
        body += ["", self.heading("Commands")]
        width = max(len(c) for c, _ in G.CHEATSHEET) + 2
        body += [f"    {B.accent(cmd.ljust(width))} {what}" for cmd, what in G.CHEATSHEET]
        body += ["", self.fact("Docs", DOCS_URL), self.fact("Version", f"agentdata {version()}")]
        self.show(("Help",), body)
