"""`tnp`: the menu over setup. Every screen says where you are (repo, folder of repos, machine), what it will write
and where, then asks the same questions `ad-setup` asks -- the same steps, called one at a time -- and ends with the
plain command that does the same thing, so nothing here is a separate way of configuring.

Laid out like toil's own menu (`toil` with no arguments): the wordmark, one status line, where you are, what needs
attention, a numbered menu; up/down and Enter, or the digit; q goes back, and quits from home.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from typing import Callable, Iterator

from .. import config as C
from .. import facts as F
from .. import textio
from ..setup import jdbc
from ..setup import scope as S
from ..setup import wizard as W
from . import brand as B
from . import guide as G

GLYPH = {"ok": "✓", "warn": "!", "fail": "✗", "info": "·", "skip": "–"}
SHADE = {"ok": (46, 160, 67), "warn": (210, 153, 34), "fail": (218, 54, 51), "info": B.MUTED, "skip": B.MUTED}
SEP = " › "


class Back(Exception):
    """Leave the current screen."""


class App:
    def __init__(self, det: W.Detectors | None = None, prompter: W.Prompter | None = None,
                 keys: Iterator[str] | None = None, out=None, cwd: str | None = None, repo: str | None = None,
                 cfg: dict | None = None) -> None:
        self.det = det or W.Detectors()
        self.scope = S.detect(cwd, repo)
        self.cfg = C.load() if cfg is None else cfg
        self.prompter = prompter or W.Prompter()
        self.out = out or sys.stdout
        self.keys = keys
        self.tty = keys is None and sys.stdin.isatty() and getattr(self.out, "isatty", lambda: False)()
        self._attention: list[W.Check] | None = None

    # ------------------------------------------------------------------ drawing and input

    def w(self, line: str = "") -> None:
        self.out.write(line + "\n")

    def para(self, text: str, indent: int = 2, muted: bool = False) -> None:
        """`text` word-wrapped to the terminal, every line at `indent`. Colour goes on after wrapping, so the
        escape codes never count as width."""
        width = max(shutil.get_terminal_size((100, 40)).columns - 2, 40)
        for line in textwrap.wrap(text, width, initial_indent=" " * indent, subsequent_indent=" " * indent,
                                  break_on_hyphens=False, break_long_words=True) or [""]:
            self.w(B.muted(line) if muted else line)

    def clear(self) -> None:
        if self.tty:
            self.out.write("\x1b[2J\x1b[H")

    def crumb(self, *parts: str) -> None:
        self.w()
        self.w("  " + B.accent("TNP") + "".join(B.muted(SEP) + (B.blue(p) if i == len(parts) - 1 else p)
                                              for i, p in enumerate(parts)))
        self.w()

    def key(self) -> str:
        if self.keys is not None:
            return next(self.keys)
        if self.tty:
            from .keys import read_key
            return read_key()
        got = input("  choose (number, q = back): ").strip().lower()
        return got or "enter"

    def menu(self, items: list[tuple[str, str]], draw: Callable[[], None], quit_word: str = "back") -> int | None:
        """Index of the chosen item, or None for q / Esc / Backspace."""
        sel = 0
        width = max(len(label) for label, _ in items) + 3
        while True:
            self.clear()
            draw()
            for i, (label, desc) in enumerate(items):
                n = str(i + 1) if i < 9 else " "
                mark = B.accent("▸") if i == sel and (self.tty or self.keys is not None) else " "
                text = f"{n}  {label.ljust(width)}"
                self.w(f"  {mark} " + (B.blue(text) if i == sel else text) + B.muted(desc))
            self.w()
            self.w(B.muted(f"  up/down move   enter select   1-{min(len(items), 9)} jump   q {quit_word}"))
            k = self.key()
            if k in ("up", "down"):
                sel = (sel + (1 if k == "down" else -1)) % len(items)
            elif k == "enter":
                return sel
            elif k.isdigit() and 1 <= int(k) <= len(items):
                return int(k) - 1
            elif k in ("q", "esc", "back", "left"):
                return None

    def bullet(self, text: str) -> None:
        width = max(shutil.get_terminal_size((100, 40)).columns - 2, 40)
        lines = textwrap.wrap(text, width, initial_indent="    • ", subsequent_indent="      ") or [""]
        for line in lines:
            self.w(line)

    def pause(self) -> None:
        self.w()
        self.w(B.muted("  enter or q: back"))
        self.key()

    def rows(self, checks: list[W.Check], only_problems: bool = False) -> None:
        for c in checks:
            if only_problems and c.status in ("ok", "info"):
                continue
            glyph = B.rgb(GLYPH.get(c.status, "?"), SHADE.get(c.status, B.MUTED), True)
            width = max(shutil.get_terminal_size((100, 40)).columns - 29, 30)
            detail = textwrap.wrap(c.detail, width) or [""]
            self.w(f"  {glyph} {c.name:<22} {detail[0]}")
            for more in detail[1:]:
                self.w(" " * 27 + more)
            if c.hint and c.status in ("fail", "warn"):
                self.para(f"fix: {c.hint}", indent=6, muted=True)

    def plain(self, *commands: str) -> None:
        self.w()
        self.w(B.muted("  Each step above is a plain command; run it yourself any time:"))
        for cmd in commands:
            self.w("    " + B.accent(cmd))

    def context(self, online: bool = False, scope: S.Scope | None = None) -> W.Context:
        where = scope or self.scope
        return W.Context(cfg=self.cfg, det=self.det, ask=self.prompter, online=online,
                         interactive=not isinstance(self.prompter, W.AnswerPrompter),
                         facts=C.project_facts(where.agents_md) if where.agents_md else {}, scope=where)

    def save(self) -> str:
        return C.display_path(C.save(self.cfg))

    # ------------------------------------------------------------------ home

    def counts(self) -> tuple[int, int]:
        conns = sum(len(C.get(self.cfg, f"sources.{s}.envs", {}) or {}) for s in C.SOURCES)
        toil = len((self.det.toil(self.cfg) or {}).get("connections") or [])
        return conns, toil

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

    def header(self) -> None:
        from ..update import version
        self.w()
        for line in B.wordmark():
            self.w(line)
        self.w()
        self.w("  " + B.gradient(B.NAME, bold=True))
        self.w()
        conns, toil = self.counts()
        att = self.attention()
        fails = sum(c.status == "fail" for c in att)
        warns = len(att) - fails
        state = (f"{fails} to fix" if fails else "") + (" · " if fails and warns else "") + \
                (f"{warns} warning{'s' * (warns != 1)}" if warns else "")
        self.w(B.muted(f"  agentdata {version()} · {conns} data connection{'s' * (conns != 1)} · "
                       f"toil {toil} connection{'s' * (toil != 1)} · {state or 'no warnings'}"))
        self.w()
        sc = self.scope
        label = {"repo": f"repo {sc.name}", "folder": f"folder of {len(sc.repos)} repos — a machine-wide setup",
                 "machine": "machine — no repo here"}[sc.kind]
        self.w(f"  {'Scope':<10} {label}")
        if sc.kind == "repo":
            self.w(f"  {'Repo':<10} {textio.norm_path(sc.root)}")
            br, remote = self.branch()
            if br:
                self.w(f"  {'Branch':<10} {br}" + (B.muted(f"  from {remote}") if remote else ""))
        else:
            self.w(f"  {'Folder':<10} {textio.norm_path(sc.root)}")
        for what, where in sc.writes():
            self.w(f"  {'Writes':<10} " + B.muted(f"{what}: ") + where)
        self.w()
        if att:
            self.w("  " + B.blue("Needs attention"))
            self.rows(att[:4])
            if len(att) > 4:
                self.w(B.muted(f"    … {len(att) - 4} more under Health check"))
            self.w()

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
            ("Health check", "Every check ad-doctor runs, with the fix for each", self.health),
            ("Help", "How tnp works, where each answer is written, a command cheatsheet", self.help),
            ("Quit", "Back to your shell", lambda: None),
        ]

    def run(self) -> int:
        try:
            while True:
                items = self.home_items()
                i = self.menu([(a, b) for a, b, _ in items], self.header, quit_word="quit")
                if i is None or i == len(items) - 1:
                    return 0
                try:
                    items[i][2]()
                except Back:
                    pass
                self._attention = None
        except (StopIteration, EOFError):
            return 0
        except KeyboardInterrupt:
            self.w()
            return 130

    # ------------------------------------------------------------------ test connections

    def test_connections(self) -> None:
        from ..setup.steps import sources, toil
        self.clear()
        self.crumb("Test connections")
        self.w(B.muted("  Connecting… (a SELECT 1 per data source, one authenticated read per toil connection)"))
        ctx = self.context(online=True)
        for step in (sources.SourcesStep(), toil.ToilStep()):
            step.verify(ctx)
        if not ctx.checks:
            self.w("  Nothing to test yet: add a connection under Data sources, or in toil.")
        self.rows(ctx.checks)
        C.save(self.cfg)
        self.plain("ad-doctor --online --only sources,toil")
        self.pause()

    # ------------------------------------------------------------------ data sources

    def envs(self, s: str) -> dict:
        return dict(C.get(self.cfg, f"sources.{s}.envs", {}) or {})

    def data_sources(self) -> None:
        from ..setup.steps.sources import LABEL
        while True:
            items = [(LABEL[s], ", ".join(self.envs(s)) or "none yet") for s in C.SOURCES] + [("Back", "")]

            def draw() -> None:
                self.crumb("Data sources")
                self.w("  Connections are machine-wide: add one once and every repo on this machine can use it.")
                self.w("  Each repo says which one it reads in its AGENTS.md (This repo).")
                self.w()
            i = self.menu(items, draw)
            if i is None or i == len(C.SOURCES):
                return
            self.source(C.SOURCES[i])

    def source(self, s: str) -> None:
        from ..setup.steps.sources import LABEL, SourcesStep
        g = G.SOURCES[s]
        while True:
            envs = list(self.envs(s))
            items = [("Add a connection", "Walks you through it; paste a JDBC URL to skip most questions")]
            items += [(f"Change {e}", "Re-ask its questions with today's answers as defaults") for e in envs]
            items += [("Test", f"SELECT 1 against each {LABEL[s]} connection")] if envs else []
            items += [("Remove a connection", "Deletes it from the machine config")] if envs else []
            items += [("Back", "")]
            ctx = self.context()
            step = SourcesStep()
            step.check(ctx, step.detect(ctx))
            mine = [c for c in ctx.checks if c.name.startswith(f"{s}:")]

            def draw() -> None:
                self.crumb("Data sources", LABEL[s])
                self.w(f"  {g['what']}")
                self.w()
                self.w("  " + B.blue("Have ready"))
                for h in g["have"]:
                    self.bullet(h)
                self.w("  " + B.blue("Where to find it"))
                self.para(g["find"], indent=4)
                self.w()
                if mine:
                    self.w("  " + B.blue("On this machine"))
                    self.rows(mine)
                    self.w()
            i = self.menu(items, draw)
            if i is None or items[i][0] == "Back":
                return
            label = items[i][0]
            if label == "Add a connection":
                self.add_connection(s)
            elif label.startswith("Change "):
                self.add_connection(s, label[len("Change "):])
            elif label == "Test":
                self.test_source(s)
            elif label == "Remove a connection":
                self.remove_connection(s)

    def add_connection(self, s: str, env: str | None = None) -> None:
        from ..setup.steps.sources import LABEL, SourcesStep
        g = G.SOURCES[s]
        self.clear()
        self.crumb("Data sources", LABEL[s], f"Change {env}" if env else "Add a connection")
        self.w("  You will be asked, in this order:")
        for n, q in enumerate(g["questions"], 1):
            self.w(B.muted(f"    {n}. {q}"))
        self.w(B.muted("  Enter keeps the answer in [brackets]. Passwords go to the OS keyring, never a file."))
        self.w()
        ask = self.prompter
        if env is None:
            existing = self.envs(s)
            env = ask.ask(f"tnp.{s}.name", f"Name for this {LABEL[s]} connection (prod, uat, ...)",
                          "" if existing else "prod").strip()
            if not env:
                return
            if env in existing and not ask.confirm(f"tnp.{s}.overwrite", f"{env} exists. Change it?", True):
                return
            url = ask.ask(f"tnp.{s}.jdbc", "Paste a JDBC URL to fill in the answers (blank = type them yourself)",
                          "").strip()
            if url:
                try:
                    filled = jdbc.parse(s, url)
                except ValueError as e:
                    self.w(f"  {B.rgb('!', SHADE['warn'], True)} {e}. Carrying on without it.")
                else:
                    merged = {**(existing.get(env) or {}), **filled}
                    C.put_leaf(self.cfg, f"sources.{s}.envs", env, merged)
                    shown = ", ".join(f"{k} {v}" for k, v in filled.items() if k != "mode")
                    self.para(f"✓ From the URL: {shown}. They are the defaults below.")
        ctx = self.context()
        step = SourcesStep()
        step.ask_env(ctx, step.detect(ctx), s, env)
        where = self.save()
        self.w()
        self.w(f"  {B.rgb('✓', SHADE['ok'], True)} Saved {s}:{env} to the machine config ({where}).")
        self.rows([c for c in ctx.checks if c.status != "ok"])
        if ask.confirm(f"tnp.{s}.test", f"Test {s}:{env} now (SELECT 1)?", True):
            self.test_source(s, [env], pause=False)
        sc = self.scope
        fact = S.SOURCE_FACT[s]
        if sc.kind == "repo" and os.path.exists(sc.agents_md):
            current = C.project_facts(sc.agents_md).get(fact)
            if current != env and ask.confirm(
                    f"tnp.{s}.repo", f"Make {env} the {LABEL[s]} environment {sc.name} reads "
                                     f"({fact} in {textio.norm_path(sc.agents_md)})?", not current):
                F.set_facts(sc.agents_md, {fact: env})
                self.w(f"  {B.rgb('✓', SHADE['ok'], True)} {fact}: {env} written to {textio.norm_path(sc.agents_md)}")
        self.plain(f"ad-setup --only sources          # every {LABEL[s]} question, for all connections",
                   g["test"].replace("<env>", env).replace("<name>", env))
        self.pause()

    def test_source(self, s: str, envs: list[str] | None = None, pause: bool = True) -> None:
        if pause:
            self.clear()
            self.crumb("Data sources", s, "Test")
        for env in envs or list(self.envs(s)):
            try:
                r = self.det.smoke(s, env, self.cfg)
                C.stamp(self.cfg, f"{s}:{env}")
                self.w(f"  {B.rgb('✓', SHADE['ok'], True)} {s}:{env}  answered in {r.get('elapsed_s', '?')}s")
            except Exception as e:  # noqa: BLE001 -- a driver's own error is the message a person needs
                self.w(f"  {B.rgb('✗', SHADE['fail'], True)} {s}:{env}  {type(e).__name__}: {str(e)[:160]}")
                if isinstance(e, C.ConfigError):        # ours: it already says what to do
                    if e.hint:
                        self.para(f"fix: {e.hint}", indent=6, muted=True)
                    continue
                for sign, fix in G.SOURCES[s]["fails"]:
                    self.para(f"if it says {sign}: {fix}", indent=6, muted=True)
        C.save(self.cfg)
        if pause:
            self.pause()

    def remove_connection(self, s: str) -> None:
        envs = list(self.envs(s))
        name = self.prompter.ask(f"tnp.{s}.remove", f"Which one ({', '.join(envs)})", "").strip()
        if name in envs and self.prompter.confirm(f"tnp.{s}.remove_ok", f"Remove {s}:{name} from the machine "
                                                  f"config? Repos that read it will say so in Health check.", False):
            (C.get(self.cfg, f"sources.{s}.envs") or {}).pop(name, None)
            self.save()

    # ------------------------------------------------------------------ Power BI

    def power_bi(self) -> None:
        from ..setup.steps import powerbi, repo
        while True:
            sc = self.scope
            items = [("This machine", "Tools, sign-in and the workspaces this account can reach")]
            if sc.kind == "repo":
                items.append((f"{sc.name}'s models and reports", "Which workspaces, semantic models and reports "
                                                                  "this repo changes"))
            elif sc.kind == "folder":
                items.append(("A repo's models and reports", "Pick the repo, then its workspaces, models, reports"))
            items.append(("Back", ""))

            def draw() -> None:
                self.crumb("Power BI")
                self.para(G.POWER_BI["why"])
                self.w()
                self.w("  " + B.blue("This machine") + B.muted("  (machine config, once)"))
                for line in G.POWER_BI["machine"]:
                    self.bullet(line)
                self.w("  " + B.blue("Each repo") + B.muted("  (its AGENTS.md, only the repos that need it)"))
                for line in G.POWER_BI["repo"]:
                    self.bullet(line)
                self.w()
                if sc.kind == "repo" and os.path.exists(sc.agents_md):
                    self.targets(sc.agents_md)
                elif sc.kind == "folder":
                    with_pbi = [S.repo_summary(r, self.cfg) for r in sc.repos]
                    with_pbi = [r for r in with_pbi if r["pbi_targets"]]
                    self.w("  " + B.blue("Repos here with Power BI targets") + ": " +
                           (", ".join(f"{r['name']} ({r['pbi_targets']})" for r in with_pbi) or "none yet"))
                    self.w()
            i = self.menu(items, draw)
            if i is None or items[i][0] == "Back":
                return
            if i == 0:
                self.clear()
                self.crumb("Power BI", "This machine")
                self.w(B.muted(f"  Writes: the machine config ({C.display_path(C.path())})"))
                ctx = self.context(online=True)
                step = powerbi.PowerBIStep()
                step.ask(ctx, step.detect(ctx))
                self.save()
                self.rows(ctx.checks, only_problems=True)
                self.plain("ad-setup --only powerbi")
                self.pause()
            else:
                target = sc if sc.kind == "repo" else self.pick_repo("Power BI")
                if target is None:
                    continue
                self.clear()
                self.crumb("Power BI", target.name)
                ctx = self.context(online=True, scope=target)
                step = repo.RepoStep()
                found = step.detect(ctx)
                if not found.get("exists"):
                    self.w(f"  {target.name} has no AGENTS.md yet: set the repo up first (Repos).")
                    self.pause()
                    continue
                self.w(B.muted(f"  Writes: {textio.norm_path(target.agents_md)} (## Power BI targets)"))
                step._ask_pbi(ctx, found)
                self.rows(ctx.checks)
                self.targets(target.agents_md)
                self.plain(f"ad-setup --repo {target.name}" if target is not sc else "ad-setup --only repo")
                self.pause()

    def targets(self, md: str) -> None:
        rows = F.pbi_targets(md)
        self.w("  " + B.blue("Power BI targets") + B.muted(f"  ({textio.norm_path(md)})"))
        if not rows:
            self.w("    none: this repo does not change Power BI")
        for n, t in enumerate(rows, 1):
            what = " / ".join(x for x in (t["workspace"], t["model"], t["report"]) if x)
            ids = "" if t["ws_id"] and (t["ds_id"] or not t["model"]) else B.muted("  (ids not looked up yet)")
            self.w(f"    {n}. {what}{ids}")
        self.w()

    # ------------------------------------------------------------------ repos

    def pick_repo(self, *crumbs: str) -> S.Scope | None:
        sc = self.scope
        if not sc.repos:
            return None
        summaries = [S.repo_summary(r, self.cfg) for r in sc.repos]
        items = []
        for r in summaries:
            if not r["agents_md"]:
                items.append((r["name"], "no AGENTS.md yet"))
                continue
            used = ", ".join(f"{s} {e}" for s, e in r["sources"].items()) or "no data sources"
            pbi = f" · {r['pbi_targets']} Power BI" if r["pbi_targets"] else ""
            bad = f" · missing here: {', '.join(r['unknown'])}" if r["unknown"] else ""
            items.append((r["name"], used + pbi + bad))
        i = self.menu(items + [("Back", "")], lambda: (self.crumb(*crumbs, "Pick a repo"), self.w(
            f"  {len(items)} repos in {textio.norm_path(sc.root)}. What each one reads comes from its AGENTS.md."),
            self.w()))
        if i is None or i == len(items):
            return None
        root = sc.repos[i]
        return S.Scope("repo", sc.cwd, root, [root])

    def repos(self) -> None:
        sc = self.scope
        if sc.kind == "machine":
            self.clear()
            self.crumb("Repos")
            self.w(f"  {G.SCOPES['machine']}")
            self.w("  Run tnp inside a repo, or in the folder that holds your repos (PycharmProjects), to give a repo")
            self.w("  its own settings. Or: `tnp --repo <path>`.")
            self.pause()
            return
        while True:
            target = sc if sc.kind == "repo" else self.pick_repo("Repos in this folder")
            if target is None:
                return
            self.repo_setup(target)
            if sc.kind == "repo":
                return

    def repo_setup(self, target: S.Scope) -> None:
        from ..setup.steps import repo
        self.clear()
        self.crumb("This repo" if target is self.scope else "Repos in this folder", target.name)
        ctx = self.context(online=True, scope=target)
        step = repo.RepoStep()
        step.ask(ctx, step.detect(ctx))
        ctx.checks.clear()
        step.check(ctx, step.detect(ctx))
        self.w()
        self.rows(ctx.checks)
        self.plain("ad-setup --only repo" if target is self.scope else f"ad-setup --repo {target.name}",
                   "ad-doctor --only repo")
        self.pause()

    # ------------------------------------------------------------------ toil services

    def services(self) -> None:
        from ..setup.steps import toil
        while True:
            found = self.det.toil(self.cfg) or {}
            conns = found.get("connections") or []

            def draw() -> None:
                self.crumb("Service connections")
                self.w(f"  {G.SERVICES['what']}")
                self.w()
                if found.get("error"):
                    self.w(f"  {B.rgb('✗', SHADE['fail'], True)} {found['error']}")
                    self.w(B.muted(f"      fix: {found.get('fix') or toil.T.install_hint(self.cfg)}"))
                elif not conns:
                    self.w("  toil has no connections yet.")
                else:
                    self.w(B.muted(f"  {'name':<18} {'area':<16} {'host':<28} writes  default"))
                    for c in conns:
                        self.w(f"  {str(c.get('name')):<18} {str(c.get('area')):<16} {str(c.get('host') or ''):<28} "
                               f"{'on' if c.get('writes') else 'off':<7} {'yes' if c.get('isDefault') else ''}")
                self.w()
                self.w(f"  {G.SERVICES['add']}")
                self.w(f"  {G.SERVICES['writes']}")
                self.w()
            items = [("Open toil", "Add a connection, sign in again, turn writes on"),
                     ("Test them", "One authenticated read per connection"), ("Back", "")]
            i = self.menu(items, draw)
            if i is None or i == 2:
                return
            if i == 0:
                self.launch_toil(found)
                if hasattr(self.det, "_toil"):
                    del self.det._toil                       # read them again after toil changed them
            else:
                self.clear()
                self.crumb("Service connections", "Test")
                ctx = self.context(online=True)
                toil.ToilStep().verify(ctx)
                self.rows(ctx.checks)
                self.plain("ad-doctor --online --only toil", "toil connections test <name>")
                self.pause()

    def launch_toil(self, found: dict) -> None:
        from .. import proc
        from ..connectors import toil as T
        where = found.get("where") or {}
        if not where.get("found"):
            self.w(f"  toil is not installed. {T.install_hint(self.cfg)}")
            self.pause()
            return
        self.w(B.muted("  Opening toil. Quit it (q) to come back here."))
        try:
            subprocess.run(proc.command(["toil"], exe=T.exe(self.cfg), path=T.search_path()), check=False)
        except OSError as e:
            self.w(f"  could not start toil: {e}")
            self.pause()

    # ------------------------------------------------------------------ health and help

    def health(self) -> None:
        self.clear()
        self.crumb("Health check")
        ctx = self.context()
        for step in W.registry():
            try:
                step.check(ctx, step.detect(ctx))
            except Exception as e:  # noqa: BLE001
                ctx.add(step.key, step.key, "fail", f"{type(e).__name__}: {e}", f"ad-doctor --only {step.key}")
        ok = sum(c.status in ("ok", "info") for c in ctx.checks)
        self.w(f"  {ok} of {len(ctx.checks)} checks fine.")
        self.w()
        self.rows(ctx.checks, only_problems=True)
        self.plain("ad-doctor", "ad-setup --patch          # re-asks only what is wrong")
        self.pause()

    def help(self) -> None:
        pages: list[tuple[str, str, Callable[[], None]]] = [
            ("Where things are written", "Machine config, keyring, a repo's AGENTS.md, toil", self.help_where),
            ("Adding a data connection", "Teradata, Hive, Impala, Oracle, Spark, step by step", self.help_sources),
            ("Power BI for one repo", "Workspaces, semantic models and reports per repo", self.help_pbi),
            ("Commands", "The plain command behind each screen", self.help_commands),
            ("Back", "", lambda: None),
        ]
        while True:
            i = self.menu([(a, b) for a, b, _ in pages], lambda: (self.crumb("Help"), self.w(
                "  The full guide, with screens: docs/tnp.md in this-next-please."), self.w()))
            if i is None or i == len(pages) - 1:
                return
            self.clear()
            self.crumb("Help", pages[i][0])
            pages[i][2]()
            self.pause()

    def help_where(self) -> None:
        self.w(f"  {G.SCOPES[self.scope.kind]}")
        self.w()
        for what, why in G.WHERE:
            self.w("  " + B.blue(what))
            self.w(f"    {why}")
        self.w()
        for what, where in self.scope.writes():
            self.w(f"  {'Writes':<8} " + B.muted(f"{what}: ") + where)

    def help_sources(self) -> None:
        from ..setup.steps.sources import LABEL
        self.w("  Data sources → pick one → Add a connection. Paste the JDBC URL your SQL tool shows and most")
        self.w("  answers are filled in; then test it, and (inside a repo) say whether this repo reads it.")
        for s in C.SOURCES:
            g = G.SOURCES[s]
            self.w()
            self.w("  " + B.blue(LABEL[s]) + B.muted(f"  {g['command']}"))
            self.w(f"    {g['what']}")
            self.w(B.muted(f"    asks: {'; '.join(g['questions'])}"))
            self.w(B.muted(f"    test: {g['test']}"))

    def help_pbi(self) -> None:
        self.w(f"  {G.POWER_BI['why']}")
        for title, key in (("Once per machine", "machine"), ("Per repo", "repo")):
            self.w()
            self.w("  " + B.blue(title))
            for line in G.POWER_BI[key]:
                self.bullet(line)

    def help_commands(self) -> None:
        width = max(len(c) for c, _ in G.CHEATSHEET) + 2
        for cmd, what in G.CHEATSHEET:
            self.w(f"  {B.accent(cmd.ljust(width))} {what}")
