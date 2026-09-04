"""Step 4: project stub — write AGENTS.md and .agent/state.json into a project directory and fill the facts we know
(env names, tool paths, workspace/model/XMLA, the first *.pbip found). Existing files are never overwritten.

The templates ship inside the package (agentdata/templates/project-stub), so this works from any install kind. A
project repo needs nothing installed: it holds PBIP folders and TMDL, not Python.
"""
from __future__ import annotations
import os
import re
import sys
from ... import config as C
from ...install import install_cmd, templates_dir
from ..wizard import Context, Step

_FACT_LINE = re.compile(r"^(\s*-\s*)([A-Za-z_][\w\-]*)(\s*:\s*)(<[^>]*>|\S+)(.*)$")
# packaged file name -> path written into the project (dot-free in the package so every packaging tool ships it)
STUB_FILES = [("AGENTS.md", "AGENTS.md"), ("agent-state.json", os.path.join(".agent", "state.json"))]
GITIGNORE_TEMPLATE = "gitignore-additions.txt"


def template_dir() -> str:
    return templates_dir()


def fill(template_text: str, facts: dict) -> str:
    """Replace the value of `- key: <placeholder>` lines whose key we know. Comments are kept."""
    out = []
    for line in template_text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        m = _FACT_LINE.match(body)
        key = m.group(2).lower() if m else None
        if m and key in facts and facts[key] not in (None, ""):
            nl = line[len(body):]
            out.append(f"{m.group(1)}{m.group(2)}{m.group(3)}{facts[key]}{m.group(5)}{nl}")
        else:
            out.append(line)
    return "".join(out)


def facts_from_config(cfg: dict) -> dict:
    f: dict = {}
    for s, key in (("teradata", "env"), ("hive", "hive_env"), ("impala", "impala_env"), ("oracle", "oracle_env")):
        envs = list(C.get(cfg, f"sources.{s}.envs", {}) or {})
        if envs:
            f[key] = envs[0]
    for n in ("te2_exe", "dscmd_exe"):
        v = C.get(cfg, f"powerbi.tools.{n}")
        if v:
            f[n] = v
    ws = (C.get(cfg, "powerbi.workspaces", []) or [None])[0]
    if ws:
        f["pbi_workspace"], f["pbi_xmla"], f["ws_id"] = ws.get("name"), ws.get("xmla"), ws.get("id")
        if ws.get("models"):
            f["pbi_model"] = ws["models"][0]
    return {k: v for k, v in f.items() if v}


class ProjectStep(Step):
    key = "project"
    title = "project stub (AGENTS.md + .agent/state.json)"

    def detect(self, ctx: Context) -> dict:
        td = template_dir()
        d = ctx.project_dir or "."
        from ...testing import detect as test_detect
        runner_info = test_detect.detect_runner(d, det=ctx.det)
        runner_ok = False
        runner_err = ""
        runner_hint = ""
        if runner_info:
            cmd_parts = runner_info.cmd.split()
            first_cmd = cmd_parts[0] if cmd_parts else ""
            if first_cmd == "python":
                first_cmd = sys.executable
            info = ctx.det.launcher(first_cmd)
            if info.get("found"):
                if "rc" in info:
                    runner_ok = (info["rc"] == 0)
                else:
                    rc, out, err = ctx.det.run([info["path"], "--version"])
                    runner_ok = (rc == 0)
                    if not runner_ok:
                        rc2, out2, err2 = ctx.det.run([info["path"], "--help"])
                        runner_ok = (rc2 == 0)
                if not runner_ok:
                    runner_err = f"runner failed to start ({runner_info.cmd})"
                    runner_hint = f"check {runner_info.runner} installation or set project.test_cmd in AGENTS.md"
            else:
                runner_err = f"{first_cmd}: executable not found"
                runner_hint = f"install {runner_info.runner} and put it on PATH"
        return {
            "template": td,
            "template_ok": ctx.det.exists(os.path.join(td, "AGENTS.md")),
            "dir": ctx.project_dir,
            "runner": runner_info.runner if runner_info else None,
            "runner_cmd": runner_info.cmd if runner_info else None,
            "runner_ok": runner_ok,
            "runner_err": runner_err,
            "runner_hint": runner_hint,
        }

    def check(self, ctx: Context, found: dict) -> None:
        if found["template_ok"]:
            ctx.add(self.key, "templates", "ok", C.display_path(found["template"]))
        else:
            ctx.add(self.key, "templates", "fail", f"project stub missing from the package at {C.display_path(found['template'])}",
                    f"reinstall agentdata: {install_cmd()}")
        if found["dir"]:
            for _src, rel in STUB_FILES:
                p = os.path.join(found["dir"], rel)
                ok = ctx.det.exists(p)
                ctx.add(self.key, rel.replace(os.sep, "/"), "ok" if ok else "warn", C.display_path(p),
                        "" if ok else f"ad-setup --project {found['dir']}")

        if found.get("runner_ok"):
            ctx.add(self.key, "tests/runner", "ok", f"{found['runner']}: {found['runner_cmd']}",
                    keys=("project.test_cmd",))
        elif found.get("runner"):
            ctx.add(self.key, "tests/runner", "fail",
                    found.get("runner_err") or f"cannot start test runner ({found['runner_cmd']})",
                    found.get("runner_hint") or f"install {found['runner']} or set project.test_cmd in AGENTS.md",
                    keys=("project.test_cmd",))
        else:
            ctx.add(self.key, "tests/runner", "warn", "no test runner detected",
                    "set test_cmd in AGENTS.md", keys=("project.test_cmd",))

    def ask(self, ctx: Context, found: dict) -> None:
        d = ctx.project_dir
        if not d:
            if not ctx.ask.confirm("project.generate", "Generate or update a project stub (AGENTS.md, .agent/state.json) now?", False):
                return
            d = ctx.ask.ask("project.dir", "project directory", ".") or "."
        if not found["template_ok"]:
            ctx.add(self.key, "project", "fail", "packaged project stub missing", f"reinstall agentdata: {install_cmd()}")
            return
        facts = facts_from_config(ctx.cfg)
        facts["jira_project"] = ctx.ask.ask("project.jira_project", "Jira project key", ctx.facts.get("jira_project") or "")
        facts["confluence_space"] = ctx.ask.ask("project.confluence_space", "Confluence space key (blank = later)", ctx.facts.get("confluence_space") or "")
        facts["confluence_parent"] = ctx.ask.ask("project.confluence_parent", "Confluence parent page id (blank = later)", ctx.facts.get("confluence_parent") or "")
        facts["test_cmd"] = ctx.ask.ask("project.test_cmd", "Test command (blank = auto-detect)", ctx.facts.get("test_cmd") or "")
        facts["graph_min_coverage"] = ctx.ask.ask(
            "project.graph_min_coverage", "Per-node coverage ad-graph guard requires (blank = 0.8)",
            ctx.facts.get("graph_min_coverage") or "")
        pbips = [p for p in ctx.det.glob("**/*.pbip", d) if ".agent" not in p]
        if pbips:
            facts["pbip_path"] = os.path.relpath(pbips[0], d).replace("\\", "/")
        facts = {k: v for k, v in facts.items() if v}
        written: list[str] = []
        for src, rel in STUB_FILES:
            target = os.path.join(d, rel)
            if ctx.det.exists(target):
                ctx.add(self.key, rel.replace(os.sep, "/"), "skip", "exists; not overwritten",
                        "edit it by hand, or delete it and re-run" if rel == "AGENTS.md" else "")
                continue
            text = ctx.det.read_text(os.path.join(found["template"], src))
            text = fill(text, facts) if src.endswith(".md") else text.replace("<PROJECT_KEY>", facts.get("jira_project", "<PROJECT_KEY>"))
            ctx.det.write_text(target, text)
            written.append(rel.replace(os.sep, "/"))
        gi = os.path.join(d, ".gitignore")
        add = ctx.det.read_text(os.path.join(found["template"], GITIGNORE_TEMPLATE))
        cur = ctx.det.read_text(gi) if ctx.det.exists(gi) else ""
        if ".agent/out/" not in cur:
            ctx.det.write_text(gi, (cur.rstrip("\n") + "\n\n" if cur else "") + add.rstrip("\n") + "\n")
            written.append(".gitignore")
        ctx.add(self.key, "project", "ok", f"{C.display_path(d)}: wrote {', '.join(written) or 'nothing (all present)'} · facts {', '.join(sorted(facts))}")
