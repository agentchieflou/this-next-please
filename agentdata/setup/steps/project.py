"""Step 4: project stub — copy templates/project-stub into a project directory and fill the facts we know
(env names, tool paths, workspace/model/XMLA, the first *.pbip found). Existing files are never overwritten."""
from __future__ import annotations
import os
import re
import agentdata
from ... import config as C
from ..wizard import Context, Step

_FACT_LINE = re.compile(r"^(\s*-\s*)([A-Za-z_][\w\-]*)(\s*:\s*)(<[^>]*>|\S+)(.*)$")


def template_dir() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(agentdata.__file__)))
    return os.path.join(root, "templates", "project-stub")


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
        return {"template": td, "template_ok": ctx.det.exists(os.path.join(td, "AGENTS.md")), "dir": ctx.project_dir}

    def check(self, ctx: Context, found: dict) -> None:
        if found["template_ok"]:
            ctx.add(self.key, "templates", "ok", C.display_path(found["template"]))
        else:
            ctx.add(self.key, "templates", "warn", "templates/project-stub not found next to the agentdata package",
                    "pip install -e <this-next-please> (editable) so ad-setup --project can find the templates")
        if found["dir"]:
            for rel in ("AGENTS.md", ".agent/state.json"):
                p = os.path.join(found["dir"], rel)
                ok = ctx.det.exists(p)
                ctx.add(self.key, rel, "ok" if ok else "warn", C.display_path(p), "" if ok else f"ad-setup --project {found['dir']}")

    def ask(self, ctx: Context, found: dict) -> None:
        d = ctx.project_dir
        if not d:
            if not ctx.ask.confirm("project.generate", "Generate or update a project stub (AGENTS.md, .agent/state.json) now?", False):
                return
            d = ctx.ask.ask("project.dir", "project directory", ".") or "."
        if not found["template_ok"]:
            ctx.add(self.key, "project", "fail", "templates missing", "pip install -e <this-next-please>")
            return
        facts = facts_from_config(ctx.cfg)
        facts["jira_project"] = ctx.ask.ask("project.jira_project", "Jira project key", ctx.facts.get("jira_project") or "")
        facts["confluence_space"] = ctx.ask.ask("project.confluence_space", "Confluence space key (blank = later)", ctx.facts.get("confluence_space") or "")
        facts["confluence_parent"] = ctx.ask.ask("project.confluence_parent", "Confluence parent page id (blank = later)", ctx.facts.get("confluence_parent") or "")
        pbips = [p for p in ctx.det.glob("**/*.pbip", d) if ".agent" not in p]
        if pbips:
            facts["pbip_path"] = os.path.relpath(pbips[0], d).replace("\\", "/")
        facts = {k: v for k, v in facts.items() if v}
        written: list[str] = []
        agents = os.path.join(d, "AGENTS.md")
        if ctx.det.exists(agents):
            ctx.add(self.key, "AGENTS.md", "skip", "exists; not overwritten", "edit the facts by hand, or delete it and re-run")
        else:
            ctx.det.write_text(agents, fill(ctx.det.read_text(os.path.join(found["template"], "AGENTS.md")), facts))
            written.append("AGENTS.md")
        state = os.path.join(d, ".agent", "state.json")
        if not ctx.det.exists(state):
            txt = ctx.det.read_text(os.path.join(found["template"], ".agent", "state.json"))
            ctx.det.write_text(state, txt.replace("<PROJECT_KEY>", facts.get("jira_project", "<PROJECT_KEY>")))
            written.append(".agent/state.json")
        gi = os.path.join(d, ".gitignore")
        add = ctx.det.read_text(os.path.join(found["template"], ".gitignore-additions"))
        cur = ctx.det.read_text(gi) if ctx.det.exists(gi) else ""
        if ".agent/out/" not in cur:
            ctx.det.write_text(gi, (cur.rstrip("\n") + "\n\n" if cur else "") + add.rstrip("\n") + "\n")
            written.append(".gitignore")
        ctx.add(self.key, "project", "ok", f"{C.display_path(d)}: wrote {', '.join(written) or 'nothing (all present)'} · facts {', '.join(sorted(facts))}")
