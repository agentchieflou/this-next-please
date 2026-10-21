"""Step: this repository -- which environment of each data source it reads, and the Power BI semantic models and
reports it changes. Written to the repository's own AGENTS.md (`agentdata/facts.py`), never to the machine's config.

The machine-wide steps (`sources`, `powerbi`, `toil`) set up connections once per machine: Teradata `prod` and `uat`,
Hive `dev`, the Power BI workspaces this account can reach. This step says which of them THIS repository uses, so
ten repositories that all read Teradata share one connection, and the one that changes the Sales and Margin models
in two workspaces says so in its own file, where its team can read it.

Inside a repository it asks; in a folder of repositories (`PycharmProjects`) it lists each one's state instead and
points at `ad-setup --repo <name>` (or `tnp` -> This repo) for the ones that need answers.
"""
from __future__ import annotations

import json
import os

from ... import config as C
from ... import facts as F
from ... import textio
from ..scope import SOURCE_FACT, repo_summary
from ..wizard import Context, Step
from .sources import LABEL

GROUPS_URL = "https://api.powerbi.com/v1.0/myorg/groups"
PBI_RESOURCE = "https://analysis.windows.net/powerbi/api"


def _pick(answer: str, names: list[str]) -> list[str]:
    """Numbers (1-based) or names, comma-separated, into names; unknown entries kept as typed."""
    out = []
    for part in [p.strip() for p in (answer or "").split(",") if p.strip()]:
        if part.isdigit() and 1 <= int(part) <= len(names):
            part = names[int(part) - 1]
        if part not in out:
            out.append(part)
    return out


class RepoStep(Step):
    key = "repo"
    title = "this repo (its data source environments and Power BI targets, in its AGENTS.md)"

    def detect(self, ctx: Context) -> dict:
        scope = ctx.scope
        found: dict = {"scope": scope.kind if scope else "machine", "envs": {
            s: list(C.get(ctx.cfg, f"sources.{s}.envs", {}) or {}) for s in SOURCE_FACT}}
        if scope is None or scope.kind != "repo":
            found["repos"] = [repo_summary(r, ctx.cfg) for r in (scope.repos if scope else [])]
            return found
        md = scope.agents_md
        found.update(agents_md=md, exists=os.path.exists(md), repo=scope.name)
        found["facts"] = C.project_facts(md) if found["exists"] else {}
        found["targets"] = F.pbi_targets(md, found["facts"]) if found["exists"] else []
        found["catalog"] = list(C.get(ctx.cfg, "powerbi.workspaces", []) or [])
        return found

    # ------------------------------------------------------------------ check

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        if found["scope"] != "repo":
            for r in found.get("repos", []):
                if not r["agents_md"]:
                    ctx.add(k, f"repo {r['name']}", "info", "no AGENTS.md: no repo settings yet",
                            f"ad-setup --repo {r['name']}")
                    continue
                used = " · ".join(f"{s} {e}" for s, e in r["sources"].items()) or "no data sources"
                pbi = f" · {r['pbi_targets']} Power BI target(s)" if r["pbi_targets"] else ""
                if r["unknown"]:
                    ctx.add(k, f"repo {r['name']}", "warn", f"{used}{pbi}; not on this machine: {', '.join(r['unknown'])}",
                            f"add them machine-wide (`ad-setup --only sources`), or `ad-setup --repo {r['name']}`")
                else:
                    ctx.add(k, f"repo {r['name']}", "info", used + pbi)
            return
        rel = textio.norm_path(found["agents_md"])
        if not found["exists"]:
            ctx.add(k, "AGENTS.md", "warn", f"{rel} does not exist: this repo has no settings of its own",
                    "ad-setup (inside the repo) offers to create it", ("repo.create",))
            return
        ctx.add(k, "AGENTS.md", "info", rel)
        for s, fact in SOURCE_FACT.items():
            env = found["facts"].get(fact)
            if not env:
                continue
            if env in found["envs"][s]:
                ctx.add(k, f"{s} env", "ok", f"{fact}: {env}")
            else:
                ctx.add(k, f"{s} env", "fail", f"{fact}: {env}, which this machine has no {LABEL[s]} connection for",
                        f"add `{env}` machine-wide (`ad-setup --only sources`, or `tnp` -> Data sources), or pick "
                        "another (`ad-setup --patch repo`)", (f"repo.{fact}",))
        for t in found["targets"]:
            what = " / ".join(x for x in (t.get("workspace"), t.get("model"), t.get("report")) if x)
            missing = [c for c, n in (("ws_id", "workspace"), ("ds_id", "model"), ("report_id", "report"))
                       if t.get(n) and not t.get(c)]
            if missing:
                ctx.add(k, "power bi target", "warn", f"{what}: no {', '.join(missing)} yet",
                        "sign in (`ad-pbi auth`), then `tnp` -> Power BI, or `ad-setup --patch repo`: the ids are looked up",
                        ("repo.pbi.use",))
            else:
                ctx.add(k, "power bi target", "ok", what)

    # ------------------------------------------------------------------ ask

    def ask(self, ctx: Context, found: dict) -> None:
        if found["scope"] != "repo":
            ctx.say("  Not inside a repository: this run sets the machine up. A repository's own settings: "
                    "`ad-setup --repo <name>`, or run it inside the repository.")
            return
        md, repo = found["agents_md"], found["repo"]
        ctx.say(f"  Writes: {textio.norm_path(md)} (this repo's facts). Connections themselves stay machine-wide.")
        if not found["exists"]:
            if not ctx.ask.confirm("repo.create", f"{repo} has no AGENTS.md. Create it from the project stub?", True):
                return
            self._create(ctx, md)
            found["facts"] = C.project_facts(md)
        values: dict[str, str | None] = {}
        for s, fact in SOURCE_FACT.items():
            envs = found["envs"][s]
            if not envs:
                continue
            current = found["facts"].get(fact, "")
            listing = ", ".join(envs)
            got = ctx.ask.ask(f"repo.{fact}", f"[{repo}] {LABEL[s]} environment it reads ({listing}; blank = none)",
                              current, confident=bool(current) and current in envs).strip()
            if got and got not in envs:
                ctx.add(self.key, f"{s} env", "fail", f"{got} is not a {LABEL[s]} environment on this machine",
                        f"one of {listing}, or add it machine-wide first (`ad-setup --only sources`)", (f"repo.{fact}",))
                continue
            if got != current:
                values[fact] = got or None
        if values:
            done = F.set_facts(md, values)
            ctx.add(self.key, "facts", "ok", ", ".join(f"{k} {v}" for k, v in sorted(done.items())))
        self._ask_pbi(ctx, found)
        ctx.facts.update(C.project_facts(md))

    def _create(self, ctx: Context, md: str) -> None:
        from .project import STUB_FILES, fill, template_dir
        tools = {n: C.get(ctx.cfg, f"powerbi.tools.{n}") for n in ("te2_exe", "dscmd_exe")}
        root = os.path.dirname(md)
        for src, rel in STUB_FILES:
            target = os.path.join(root, rel)
            if os.path.exists(target):
                continue
            text = textio.read_text(os.path.join(template_dir(), src))
            text = fill(text, {k: v for k, v in tools.items() if v}) if src.endswith(".md") else text
            os.makedirs(os.path.dirname(target), exist_ok=True)
            textio.write_text(target, text)
        ctx.add(self.key, "AGENTS.md", "ok", f"created {textio.norm_path(md)} from the project stub")

    # ------------------------------------------------------------------ Power BI

    def _rest(self, ctx: Context, url: str) -> list[dict] | None:
        az = C.get(ctx.cfg, "powerbi.tools.az_exe") or ctx.det.which("az")
        if not az or not ctx.online:
            return None
        rc, out, _err = ctx.det.run([az, "rest", "--resource", PBI_RESOURCE, "--url", url, "-o", "json"], 120)
        if rc != 0:
            return None
        try:
            return list((json.loads(out) or {}).get("value") or [])
        except (ValueError, AttributeError):
            return None

    def _ask_pbi(self, ctx: Context, found: dict) -> None:
        repo, targets = found["repo"], list(found["targets"])
        if not ctx.ask.confirm("repo.pbi.use", f"Does {repo} change Power BI semantic models or reports?",
                               bool(targets), confident=bool(targets)):
            return
        for i, t in enumerate(targets, 1):
            ctx.say(f"    now {i}. " + " / ".join(x for x in (t.get("workspace"), t.get("model"), t.get("report")) if x))
        catalog = {w.get("name"): w for w in found["catalog"] if w.get("name")}
        groups = self._rest(ctx, GROUPS_URL)
        if groups:
            for g in groups:
                catalog.setdefault(g.get("name"), {"name": g.get("name"), "id": g.get("id")})
                if not catalog[g["name"]].get("id"):
                    catalog[g["name"]]["id"] = g.get("id")
        names = sorted(n for n in catalog if n)
        for i, n in enumerate(names, 1):
            ctx.say(f"    {i}. {n}")
        default = ", ".join(dict.fromkeys(t["workspace"] for t in targets if t.get("workspace")))
        chosen = _pick(ctx.ask.ask("repo.pbi.workspaces", f"[{repo}] workspaces it changes (numbers or names)",
                                   default, confident=bool(default)), names)
        result: list[dict] = []
        for ws in chosen:
            ws_id = (catalog.get(ws) or {}).get("id") or next((t["ws_id"] for t in targets if t["workspace"] == ws
                                                              and t.get("ws_id")), "")
            models = self._rest(ctx, f"{GROUPS_URL}/{ws_id}/datasets") if ws_id else None
            reports = self._rest(ctx, f"{GROUPS_URL}/{ws_id}/reports") if ws_id else None
            model_ids = {m.get("name"): m.get("id") for m in models or []}
            for m in (catalog.get(ws) or {}).get("models") or []:
                model_ids.setdefault(m, "")
            report_rows = {r.get("name"): r for r in reports or []}
            mine = [t for t in targets if t["workspace"] == ws]
            mnames = sorted(model_ids)
            for i, n in enumerate(mnames, 1):
                ctx.say(f"      model {i}. {n}")
            mdef = ", ".join(dict.fromkeys(t["model"] for t in mine if t.get("model")))
            pick_m = _pick(ctx.ask.ask(f"repo.pbi.{ws}.models", f"[{ws}] semantic models it changes (numbers or names; "
                                       "blank = none)", mdef, confident=bool(mdef)), mnames)
            rnames = sorted(report_rows)
            for i, n in enumerate(rnames, 1):
                ctx.say(f"      report {i}. {n}")
            rdef = ", ".join(dict.fromkeys(t["report"] for t in mine if t.get("report")))
            pick_r = _pick(ctx.ask.ask(f"repo.pbi.{ws}.reports", f"[{ws}] reports it changes (numbers or names; "
                                       "blank = none)", rdef, confident=bool(rdef)), rnames)
            by_id = {v: k for k, v in model_ids.items() if v}
            covered = set()
            for r in pick_r:
                row = report_rows.get(r) or {}
                prev = next((t for t in mine if t.get("report") == r), {})
                model = by_id.get(row.get("datasetId"), "") or prev.get("model", "")
                covered.add(model)
                result.append({"workspace": ws, "ws_id": ws_id, "model": model,
                               "ds_id": model_ids.get(model) or prev.get("ds_id", ""), "report": r,
                               "report_id": row.get("id") or prev.get("report_id", "")})
            for m in pick_m:
                if m in covered:
                    continue
                prev = next((t for t in mine if t.get("model") == m), {})
                result.append({"workspace": ws, "ws_id": ws_id, "model": m,
                               "ds_id": model_ids.get(m) or prev.get("ds_id", ""), "report": "", "report_id": ""})
        F.set_targets(found["agents_md"], result)
        ctx.add(self.key, "power bi targets", "ok" if result else "info",
                f"{len(result)} written to {textio.norm_path(found['agents_md'])}" if result else "none")
