"""Step 3: Power BI — tool paths (Tabular Editor 2, DAX Studio dscmd, Desktop), Azure CLI sign-in, workspaces via
the Power BI REST API with percent-encoded XMLA URLs, and a TE2 smoke test per workspace/model. Nothing secret is
stored: Azure auth is interactive (az login)."""
from __future__ import annotations
import json
import os
import tempfile
import urllib.parse
from ... import config as C
from ..wizard import Context, Step

TOOLS = {
    "te2_exe": ("TabularEditor.exe", ["C:/Program Files (x86)/Tabular Editor/TabularEditor.exe",
                                      "C:/Program Files/Tabular Editor/TabularEditor.exe",
                                      "%LOCALAPPDATA%/TabularEditor/TabularEditor.exe",
                                      "C:/Tools/TabularEditor/TabularEditor.exe"]),
    "dscmd_exe": ("dscmd.exe", ["C:/Program Files/DAX Studio/dscmd.exe", "%LOCALAPPDATA%/DaxStudio/dscmd.exe",
                                "C:/Tools/DaxStudio/dscmd.exe"]),
    "pbi_desktop_exe": ("PBIDesktop.exe", ["C:/Program Files/Microsoft Power BI Desktop/bin/PBIDesktop.exe",
                                           "%LOCALAPPDATA%/Microsoft/WindowsApps/PBIDesktop.exe"]),
}
PBI_RESOURCE = "https://analysis.windows.net/powerbi/api"
GROUPS_URL = "https://api.powerbi.com/v1.0/myorg/groups"
PING_CSX = 'Info("tables=" + Model.Tables.Count.ToString());\n'


def xmla_url(workspace: str) -> str:
    """powerbi://api.powerbi.com/v1.0/myorg/<name> with the name RFC 3986 percent-encoded (spaces -> %20)."""
    return "powerbi://api.powerbi.com/v1.0/myorg/" + urllib.parse.quote(workspace, safe="")


class PowerBIStep(Step):
    key = "powerbi"
    title = "Power BI (Tabular Editor 2, DAX Studio, Desktop, workspaces)"

    def _find_tool(self, ctx: Context, name: str) -> str | None:
        exe, candidates = TOOLS[name]
        configured = C.get(ctx.cfg, f"powerbi.tools.{name}") or ctx.facts.get(name)
        if configured and ctx.det.exists(configured):
            return configured
        w = ctx.det.which(exe)
        if w:
            return w.replace("\\", "/")
        for c in candidates:
            p = C.expand(c)
            if ctx.det.exists(p):
                return p.replace("\\", "/")
        return configured  # configured but missing: check() flags it

    def detect(self, ctx: Context) -> dict:
        return {"tools": {n: self._find_tool(ctx, n) for n in TOOLS}, "az": ctx.det.which("az"),
                "workspaces": list(C.get(ctx.cfg, "powerbi.workspaces", []) or [])}

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        for n, p in found["tools"].items():
            if p and ctx.det.exists(p):
                ctx.add(k, n, "ok", p)
            elif p:
                ctx.add(k, n, "fail", f"configured path missing: {p}", "ad-setup --only powerbi")
            else:
                ctx.add(k, n, "warn", "not found", f"install it or set powerbi.tools.{n} (ad-setup --only powerbi)")
        if found["az"]:
            ctx.add(k, "az cli", "ok", found["az"])
        else:
            ctx.add(k, "az cli", "warn", "az not on PATH", "install Azure CLI (workspace listing, refresh status)")
        if not found["workspaces"]:
            ctx.add(k, "workspaces", "warn", "none configured", "ad-setup --only powerbi")
        for ws in found["workspaces"]:
            v = C.get(ctx.cfg, f"verified.powerbi:xmla:{ws.get('name')}")
            detail = f"{ws.get('xmla')} · models {', '.join(ws.get('models', []))}" + (f" · verified {v}" if v else "")
            ctx.add(k, f"workspace {ws.get('name')}", "ok" if v else "warn", detail,
                    "" if v else "ad-doctor --online (needs te2_exe and a model name)")

    def ask(self, ctx: Context, found: dict) -> None:
        cfg = ctx.cfg
        if not ctx.ask.confirm("powerbi.use", "Use Power BI tooling?", bool(any(found["tools"].values()) or found["workspaces"])):
            return
        for n, (exe, _) in TOOLS.items():
            p = ctx.ask.ask(f"powerbi.{n}", f"path to {exe} (blank = not installed)", found["tools"][n] or "")
            if p:
                C.put(cfg, f"powerbi.tools.{n}", p.replace("\\", "/"))
                if not ctx.det.exists(p):
                    ctx.add(self.key, n, "warn", f"path not found: {p}", "check the path (ad-setup --only powerbi)")
            else:
                (C.get(cfg, "powerbi.tools") or {}).pop(n, None)
        if not ctx.ask.confirm("powerbi.workspaces.configure", "Configure Power BI Service workspaces (XMLA)?",
                               bool(found["workspaces"] or found["az"])):
            return
        groups: list[dict] = []
        if ctx.online and found["az"]:
            rc, out, err = ctx.det.run(["az", "account", "show", "-o", "json"], 60)
            if rc != 0 and ctx.interactive and ctx.ask.confirm("powerbi.az_login", "Not signed in to Azure CLI. Run `az login --allow-no-subscriptions` now?", True):
                ctx.det.run_interactive(["az", "login", "--allow-no-subscriptions"])
                rc, out, err = ctx.det.run(["az", "account", "show", "-o", "json"], 60)
            if rc == 0:
                try:
                    acct = json.loads(out or "{}")
                except ValueError:
                    acct = {}
                if acct.get("tenantId"):
                    C.put(cfg, "powerbi.tenant_id", acct["tenantId"])
                rc2, out2, err2 = ctx.det.run(["az", "rest", "--resource", PBI_RESOURCE, "--url", GROUPS_URL, "-o", "json"], 120)
                if rc2 == 0:
                    try:
                        groups = [{"name": g.get("name"), "id": g.get("id")} for g in json.loads(out2).get("value", [])]
                    except ValueError:
                        groups = []
                else:
                    ctx.add(self.key, "workspaces", "warn", f"az rest failed: {(err2 or out2).strip()[-160:]}",
                            "check Power BI permissions; workspace names can be typed manually")
            else:
                ctx.add(self.key, "az login", "warn", "not signed in", "az login --allow-no-subscriptions")
        existing = {w["name"]: w for w in found["workspaces"] if w.get("name")}
        if groups:
            for i, g in enumerate(groups, 1):
                ctx.say(f"    {i}. {g['name']}")
            sel = ctx.ask.ask("powerbi.workspaces.select", "workspaces to use (numbers or names, comma-separated)", ",".join(existing))
            names = []
            for tok in [t.strip() for t in sel.split(",") if t.strip()]:
                names.append(groups[int(tok) - 1]["name"] if tok.isdigit() and 1 <= int(tok) <= len(groups) else tok)
        else:
            sel = ctx.ask.ask("powerbi.workspaces.select", "workspace names (comma-separated)", ",".join(existing))
            names = [t.strip() for t in sel.split(",") if t.strip()]
        by_name = {g["name"]: g for g in groups}
        result = []
        for name in names:
            prev = existing.get(name, {})
            raw = ctx.ask.ask(f"powerbi.workspace.{name}.models", f"[{name}] semantic model names (comma-separated)", ",".join(prev.get("models", [])))
            models = [m.strip() for m in raw.split(",") if m.strip()]
            result.append({"name": name, "id": by_name.get(name, {}).get("id") or prev.get("id"), "xmla": xmla_url(name), "models": models})
        C.put(cfg, "powerbi.workspaces", result)
        ctx.add(self.key, "workspaces", "ok" if result else "warn", ", ".join(w["name"] for w in result) or "none",
                "" if result else "ad-setup --only powerbi")

    def verify(self, ctx: Context) -> None:
        te2 = C.get(ctx.cfg, "powerbi.tools.te2_exe")
        dscmd = C.get(ctx.cfg, "powerbi.tools.dscmd_exe")
        if dscmd and ctx.det.exists(dscmd):
            rc, out, err = ctx.det.run([dscmd, "csv", "--help"], 60)
            text = (out or "") + (err or "")
            C.put(ctx.cfg, "powerbi.tools.dscmd_caps", {"file_flag": ("--file" in text) or (" -f" in text), "help_rc": rc})
        for ws in C.get(ctx.cfg, "powerbi.workspaces", []) or []:
            name, tag = ws.get("name"), f"workspace {ws.get('name')}"
            if not (te2 and ctx.det.exists(te2)):
                ctx.add(self.key, tag, "skip", "no te2_exe for the XMLA smoke test")
                continue
            if not ws.get("models"):
                ctx.add(self.key, tag, "skip", "no model names to test")
                continue
            with tempfile.TemporaryDirectory() as td:
                csx = os.path.join(td, "ping.csx")
                with open(csx, "w", encoding="utf-8") as f:
                    f.write(PING_CSX)
                rc, out, err = ctx.det.run([te2, ws["xmla"], ws["models"][0], "-S", csx], 180)
            if rc == 0:
                C.stamp(ctx.cfg, f"powerbi:xmla:{name}")
                ctx.add(self.key, tag, "ok", f"Tabular Editor connected to {ws['models'][0]}")
            else:
                ctx.add(self.key, tag, "fail", ((out or "") + (err or "")).strip()[-200:] or f"exit {rc}",
                        "XMLA read needs Premium/PPU with the endpoint enabled; check workspace/model names; az login")
