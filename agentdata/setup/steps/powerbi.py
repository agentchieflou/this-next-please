"""Step 3: Power BI — tool paths (Tabular Editor 2, DAX Studio dscmd, Desktop), Azure CLI sign-in, workspaces via
the Power BI REST API with percent-encoded XMLA URLs, and a TE2 smoke test per workspace/model. Nothing secret is
stored: Azure auth is interactive (az login)."""
from __future__ import annotations
import json
import os
import sys
import tempfile
import urllib.parse
from ... import config as C
from ..wizard import Context, Step
from ... import textio

TOOLS = {
    "te2_exe": ("TabularEditor.exe", ["C:/Program Files (x86)/Tabular Editor/TabularEditor.exe",
                                      "C:/Program Files/Tabular Editor/TabularEditor.exe",
                                      "%LOCALAPPDATA%/TabularEditor/TabularEditor.exe",
                                      "C:/Tools/TabularEditor/TabularEditor.exe"]),
    "dscmd_exe": ("dscmd.exe", ["C:/Program Files/DAX Studio/dscmd.exe", "%LOCALAPPDATA%/DaxStudio/dscmd.exe",
                                "C:/Tools/DaxStudio/dscmd.exe"]),
    "pbi_desktop_exe": ("PBIDesktop.exe", ["C:/Program Files/Microsoft Power BI Desktop/bin/PBIDesktop.exe",
                                           "%LOCALAPPDATA%/Microsoft/WindowsApps/PBIDesktop.exe"]),
    # az is a .cmd, not an .exe; the MSI does not always leave wbin on PATH (proc.py searches these too)
    "az_exe": ("az", ["%ProgramFiles%/Microsoft SDKs/Azure/CLI2/wbin/az.cmd",
                      "%ProgramFiles(x86)%/Microsoft SDKs/Azure/CLI2/wbin/az.cmd",
                      "%LOCALAPPDATA%/Programs/Microsoft SDKs/Azure/CLI2/wbin/az.cmd"]),
}
PBI_RESOURCE = "https://analysis.windows.net/powerbi/api"
GROUPS_URL = "https://api.powerbi.com/v1.0/myorg/groups"
PING_CSX = 'Info("tables=" + Model.Tables.Count.ToString());\n'

# One sentence per transport: what the human actually does. The doctor, `pbi-router` and
# `pbi-observe` all have to say the same thing, and the thing that used to be said -- "press
# External Tools -> agentdata" -- was true on none of the four machines #112 measured.
TRANSPORT_GESTURE = {
    "ribbon:machine": "press External Tools -> agentdata in Power BI Desktop",
    "te2:local": 'in Tabular Editor pick the instance, then "Hand off to agentdata"',
    "zorder": "click the window you mean, then `ad-pbip handoff --active`",
    "file": "`ad-pbip handoff --file <name>` picks the instance by file name",
}
# The local Administrators group, by SID rather than by name: the group is called Administrateurs
# on a French laptop and the SID is the same everywhere.
ADMINISTRATORS_SID = "S-1-5-32-544"
# The one phrase this slice exists to delete from every row but one. Kept as a constant so the
# test that asserts its absence and the code that emits it cannot drift apart.
ELEVATED = "run elevated"


def xmla_url(workspace: str) -> str:
    """powerbi://api.powerbi.com/v1.0/myorg/<name> with the name RFC 3986 percent-encoded (spaces -> %20)."""
    return "powerbi://api.powerbi.com/v1.0/myorg/" + urllib.parse.quote(workspace, safe="")


def package_dir() -> str:
    """`.agent/out/external-tool` -- where the ticket for whoever owns Common Files is written.

    Read from `external_tool` rather than spelled again, because the doctor row names this path to
    a human who will then go looking for the folder, and two spellings would eventually disagree.
    """
    from ...pbip import external_tool as EXT
    return textio.norm_path(EXT.DEFAULT_PACKAGE_DIR)


def elevation_avenue(run=None) -> dict:
    """Is there anything for this user to elevate *to*? `{available, evidence}`.

    The bug that started #112 was not the permission error. It was the line under it: `run
    elevated`, printed to a user whose account is not in the local Administrators group, so there
    was no elevated shell for them to open and the advice cost them an afternoon. So the phrase is
    now gated on a measurement, and the measurement is the membership -- not whether the write
    failed, which on a managed laptop it always will.

    Two reads, both read-only and neither of them an attempt. `shell32!IsUserAnAdmin` answers "this
    process is already elevated", which settles it. Otherwise `whoami /groups` is asked for the
    Administrators SID: membership means a UAC prompt would succeed even though this process is
    filtered, and no membership means there is nothing to consent to. The SID is used rather than
    the localised group name, and the call goes through the injected `Runner` so the fakes drive
    both answers on Linux.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.shell32.IsUserAnAdmin():
                return {"available": True, "evidence": "this process is already elevated (shell32!IsUserAnAdmin)"}
        except Exception as e:  # noqa: BLE001 - a user32/shell32 that will not answer is not an avenue
            if run is None:
                return {"available": False, "evidence": f"could not ask shell32!IsUserAnAdmin ({type(e).__name__})"}
    if run is None:
        return {"available": False, "evidence": f"no runner to ask with (sys.platform={sys.platform})"}
    rc, out, err = run(["whoami", "/groups", "/fo", "csv", "/nh"], 20)
    if rc != 0:
        return {"available": False,
                "evidence": f"whoami /groups did not answer ({(err or out or '').strip()[:80] or f'exit {rc}'})"}
    if ADMINISTRATORS_SID in (out or ""):
        return {"available": True,
                "evidence": f"this account is in the local Administrators group ({ADMINISTRATORS_SID}), "
                            "so a UAC prompt would elevate"}
    return {"available": False,
            "evidence": f"this account is not in the local Administrators group ({ADMINISTRATORS_SID}): "
                        "there is no elevated shell for this user to open"}


def next_cheapest_step(ribbon: dict, te2: dict) -> tuple[str, tuple[str, ...]]:
    """The cheapest thing that would improve the gesture, and the settings `--patch` would re-ask.

    Cheapest first, and cheapness here is measured in *who has to be involved*: the Tabular Editor
    action is one per-user file this user owns, a direct ribbon write is one file this user has been
    measured able to create, and the package is a ticket for whoever owns Common Files. That order
    is why `te2:local` is offered ahead of the ribbon even on a machine whose folder happens to be
    writable -- the ribbon is nicer, but it is never the *next* step when a free one is left.

    The package step carries no keys on purpose: no answer to any `ad-setup` question places a file
    in a machine-scoped folder, so `--patch` must list it under `manual` with this hint rather than
    ask questions that cannot help (HANDOFF.md).
    """
    from ...pbip import desktop as DT
    if ribbon["state"] == DT.RIBBON_REGISTERED:
        return "", ()
    if te2.get("present") and not te2.get("installed"):
        return ("`ad-pbip register-tool --te2` installs the Tabular Editor action -- per-user, no privileged write",
                ("powerbi.te2_custom_action",))
    if ribbon["state"] == DT.RIBBON_WRITABLE:
        return ("`ad-pbip register-tool` writes the ribbon file: this folder accepts a write from this user",
                ("powerbi.external_tool",))
    if ribbon["state"] == DT.RIBBON_DISABLED:
        return ("External Tools is switched off for this machine, so no file would appear on the ribbon; "
                "the handoff does not need it", ())
    return (f"`ad-pbip register-tool --package`, and send {package_dir()} to whoever owns Common Files -- "
            "one file, once, for every user on every laptop", ())


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
            return textio.norm_path(w)
        for c in candidates:
            p = C.expand(c)
            if ctx.det.exists(p):
                return textio.norm_path(p)
        return configured  # configured but missing: check() flags it

    def detect(self, ctx: Context) -> dict:
        tools = {n: self._find_tool(ctx, n) for n in TOOLS}
        return {"tools": tools, "az": tools["az_exe"], "workspaces": list(C.get(ctx.cfg, "powerbi.workspaces", []) or [])}

    def check(self, ctx: Context, found: dict) -> None:
        k = self.key
        for n, p in found["tools"].items():
            keys = (f"powerbi.{n}",)
            if p and ctx.det.exists(p):
                ctx.add(k, n, "ok", p)
            elif p:
                ctx.add(k, n, "fail", f"configured path missing: {p}", "ad-setup --patch", keys)
            elif n == "az_exe":
                ctx.add(k, n, "warn", "az not found on PATH or in the Azure CLI install dirs",
                        r"install Azure CLI, or `ad-setup --patch` and give the path (usually "
                        r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd)", keys)
            else:
                ctx.add(k, n, "warn", "not found", f"install it or set powerbi.tools.{n} (ad-setup --patch)", keys)
        if not found["workspaces"]:
            ctx.add(k, "workspaces", "warn", "none configured", "ad-setup --patch",
                    ("powerbi.workspaces.configure", "powerbi.workspaces.select"))
        for ws in found["workspaces"]:
            v = C.get_leaf(ctx.cfg, "verified", f"powerbi:xmla:{ws.get('name')}")
            detail = f"{ws.get('xmla')} · models {', '.join(ws.get('models', []))}" + (f" · verified {v}" if v else "")
            ctx.add(k, f"workspace {ws.get('name')}", "ok" if v else "warn", detail,
                    "" if v else "ad-doctor --online (needs te2_exe and a model name)",
                    ("powerbi.te2_exe", f"powerbi.workspace.{ws.get('name')}.models"))

        # desktop/version
        dt_exe = found["tools"].get("pbi_desktop_exe")
        dt_keys = ("powerbi.pbi_desktop_exe", "powerbi.tools.pbi_desktop_exe")
        if dt_exe and ctx.det.exists(dt_exe):
            ver = None
            if hasattr(ctx.det, "version"):
                ver = ctx.det.version("PBIDesktop.exe")
            if not ver:
                from ...pbip import desktop as DT
                ver, _ = DT.probe_desktop_version(None, {"Path": dt_exe})
            ver_text = f"PBIDesktop.exe · {ver}" if ver else "PBIDesktop.exe"
            ctx.add(k, "desktop/version", "ok", ver_text)
        else:
            ctx.add(k, "desktop/version", "warn", "PBIDesktop.exe not found or not executable",
                    "install Power BI Desktop or set powerbi.tools.pbi_desktop_exe (ad-setup --patch)", dt_keys)

        # desktop/capabilities
        from ...pbip import desktop as DT
        # The runner is injected all the way down: every probe under `capabilities()` -- the
        # kill-switch registry reads, the External Tools writable probe, the Z-order enumeration --
        # is then the same fake on Linux CI that it is a real read on the laptop.
        caps = DT.capabilities(run=ctx.det.run)
        avail = sum(1 for c in caps if c.get("available"))
        total = len(caps)
        cap_summary = f"{avail}/{total} capabilities available"
        cap_keys = ("powerbi.tools.dscmd_exe", "powerbi.tools.te2_exe", "powerbi.tools.pbi_desktop_exe")
        if avail >= 2:
            ctx.add(k, "desktop/capabilities", "ok", cap_summary)
        else:
            ctx.add(k, "desktop/capabilities", "warn", cap_summary, "ad-setup --patch", cap_keys)

        self._transport_rows(ctx, caps)

    def _transport_rows(self, ctx: Context, caps: list[dict]) -> None:
        """`powerbi/external_tool` and `powerbi/ribbon`: which handoff is live, and what the button is doing.

        These used to be one row, and that row was the bug #112 was filed about. It answered "is our
        file in Common Files", called the answer `not registered`, and hinted `run elevated` -- three
        mistakes in one line on the laptop that reported it: the handoff worked there (`zorder` needs
        no file at all), the folder is Administrators-only so *no* user answer fixes it, and the
        account cannot elevate, so the hint named an action the reader could not take.

        So they are two rows now, because they are two questions with two owners. `external_tool`
        asks *can this human hand a window over*, and is `ok` the moment any of the four transports
        works. `ribbon` is a fact about the machine, reported at `info` -- it never fails a doctor
        run and never counts as a warning, because a missing button is not a broken install. Its
        hint is the ticket, with the folder to attach; `run elevated` appears there only when the
        folder refused a write *and* `elevation_avenue()` measured somewhere to elevate to.

        The transport comes out of the `capabilities()` list rather than from a second
        `external_tools_row()` call, deliberately: that probe creates and deletes a file in the
        folder Power BI Desktop reads its ribbon from, and `session-bootstrap` runs `ad-doctor` every
        session. One probe per row is the budget, not one per question asked about it.
        """
        from ...pbip import desktop as DT
        k = self.key

        ext = next((c for c in caps if c.get("capability") == "external_tools"), None) or \
            DT.external_tools_row(run=ctx.det.run)
        ribbon = DT.ribbon_state(run=ctx.det.run)
        te2 = DT.te2_action_state()
        hint, keys = next_cheapest_step(ribbon, te2)

        via = ext.get("via") or "none"
        if ext.get("available"):
            gesture = TRANSPORT_GESTURE.get(via, "`ad-pbip handoff --active`")
            ctx.add(k, "powerbi/external_tool", "ok", f"{via} · {gesture}", hint, keys)
        else:
            # No transport at all. On Windows this only happens with no Desktop window open, which
            # is a state the human fixes by opening one; off Windows it is simply not applicable.
            # The ladder is deliberately NOT the hint here: it upgrades a handoff that works, and
            # "file a ticket for a ribbon button" is not the next step on a machine with nothing to
            # hand off yet.
            ctx.add(k, "powerbi/external_tool", "warn", f"no handoff transport · {ext.get('evidence', '')}",
                    "open a Power BI Desktop window, then `ad-pbip handoff --active`",
                    ("powerbi.tools.pbi_desktop_exe", "powerbi.tools.te2_exe"))

        state = ribbon["state"]
        detail = f"{state} · {ribbon['evidence']}"
        if state == DT.RIBBON_REGISTERED:
            ctx.add(k, "powerbi/ribbon", "info", detail)
            return
        if state == DT.RIBBON_WRITABLE:
            ctx.add(k, "powerbi/ribbon", "info", detail,
                    "`ad-pbip register-tool` writes it, or answer yes to powerbi.external_tool in `ad-setup --patch`",
                    ("powerbi.external_tool",))
            return
        if state == DT.RIBBON_DISABLED:
            # No keys: a Group Policy value is not an answer any prompt of ours can change, so
            # `--patch` lists this under `manual` rather than asking questions that cannot help.
            ctx.add(k, "powerbi/ribbon", "info", detail,
                    "the handoff does not need the ribbon; ask whoever set the policy if you want the button")
            return

        # needs-it-file: the ticket, and the folder to attach to it. Never a shell we have no
        # evidence this user can open -- that is measured, not assumed.
        ticket = (f"`ad-pbip register-tool --package` writes {package_dir()}; send that folder to whoever owns "
                  f"{textio.norm_path(ribbon['dir'])} -- REQUEST.md is the whole ticket, and the same file works "
                  "for every user and every Python version")
        if ribbon.get("writable") is False and ctx.det.is_windows():
            avenue = elevation_avenue(ctx.det.run)
            if avenue["available"]:
                ticket += f". Or {ELEVATED}: {avenue['evidence']}"
        ctx.add(k, "powerbi/ribbon", "info", detail, ticket)

    def ask(self, ctx: Context, found: dict) -> None:
        cfg = ctx.cfg
        if not ctx.ask.confirm("powerbi.use", "Use Power BI tooling?", bool(any(found["tools"].values()) or found["workspaces"])):
            return
        for n, (exe, _) in TOOLS.items():
            tool_path = found["tools"][n] or ""
            is_conf = bool(tool_path and ctx.det.exists(tool_path))
            p = ctx.ask.ask(f"powerbi.{n}", f"path to {exe} (blank = not installed)", tool_path, confident=is_conf)
            if p:
                C.put(cfg, f"powerbi.tools.{n}", textio.norm_path(p))
                if not ctx.det.exists(p):
                    ctx.add(self.key, n, "warn", f"path not found: {p}", "check the path (ad-setup --patch)", (f"powerbi.{n}",))
            else:
                (C.get(cfg, "powerbi.tools") or {}).pop(n, None)

        dt_found = bool(found["tools"].get("pbi_desktop_exe"))
        te2_found = bool(found["tools"].get("te2_exe"))
        self._ask_te2_action(ctx, te2_found and dt_found)
        self._ask_ribbon(ctx, dt_found)

        if not ctx.ask.confirm("powerbi.workspaces.configure", "Configure Power BI Service workspaces (XMLA)?",
                                bool(found["workspaces"] or found["az"])):
            return
        groups: list[dict] = []
        if ctx.online and found["az"]:
            az = found["az"] or "az"     # the resolved az.cmd: never the bare name (CreateProcess only tries az.exe)
            rc, out, err = ctx.det.run([az, "account", "show", "-o", "json"], 60)
            if rc != 0 and ctx.interactive and ctx.ask.confirm("powerbi.az_login", "Not signed in to Azure CLI. Run `az login --allow-no-subscriptions` now?", True):
                ctx.det.run_interactive([az, "login", "--allow-no-subscriptions"])
                rc, out, err = ctx.det.run([az, "account", "show", "-o", "json"], 60)
            if rc == 0:
                try:
                    acct = json.loads(out or "{}")
                except ValueError:
                    acct = {}
                if acct.get("tenantId"):
                    C.put(cfg, "powerbi.tenant_id", acct["tenantId"])
                rc2, out2, err2 = ctx.det.run([az, "rest", "--resource", PBI_RESOURCE, "--url", GROUPS_URL, "-o", "json"], 120)
                if rc2 == 0:
                    try:
                        groups = [{"name": g.get("name"), "id": g.get("id")} for g in json.loads(out2).get("value", [])]
                    except ValueError:
                        groups = []
                else:
                    ctx.add(self.key, "workspaces", "warn", f"az rest failed: {(err2 or out2).strip()[-160:]}",
                            "check Power BI permissions; workspace names can be typed manually",
                            ("powerbi.workspaces.select",))
            else:
                ctx.add(self.key, "az login", "warn", "not signed in", "az login --allow-no-subscriptions",
                        ("powerbi.az_login", "powerbi.az_exe"))
        existing = {w["name"]: w for w in found["workspaces"] if w.get("name")}
        if groups:
            for i, g in enumerate(groups, 1):
                ctx.say(f"    {i}. {g['name']}")
            default_ws = "1" if len(groups) == 1 and not existing else ",".join(existing)
            sel = ctx.ask.ask("powerbi.workspaces.select", "workspaces to use (numbers or names, comma-separated)",
                              default_ws, confident=len(groups) == 1)
            names = []
            for tok in [t.strip() for t in sel.split(",") if t.strip()]:
                names.append(groups[int(tok) - 1]["name"] if tok.isdigit() and 1 <= int(tok) <= len(groups) else tok)
        else:
            sel = ctx.ask.ask("powerbi.workspaces.select", "workspace names (comma-separated)",
                              ",".join(existing), confident=bool(existing and len(existing) == 1))
            names = [t.strip() for t in sel.split(",") if t.strip()]
        by_name = {g["name"]: g for g in groups}
        result = []
        for name in names:
            prev = existing.get(name, {})
            models_default = ",".join(prev.get("models", []))
            raw = ctx.ask.ask(f"powerbi.workspace.{name}.models", f"[{name}] semantic model names (comma-separated)",
                              models_default, confident=bool(prev.get("models") and len(prev.get("models")) == 1))
            models = [m.strip() for m in raw.split(",") if m.strip()]
            result.append({"name": name, "id": by_name.get(name, {}).get("id") or prev.get("id"), "xmla": xmla_url(name), "models": models})
        C.put(cfg, "powerbi.workspaces", result)
        ctx.add(self.key, "workspaces", "ok" if result else "warn", ", ".join(w["name"] for w in result) or "none",
                "" if result else "ad-setup --only powerbi")

    def _ask_te2_action(self, ctx: Context, default: bool) -> None:
        """Offer the per-user Tabular Editor action (#115.2). No privileged write, so no ticket.

        This is the cheapest of the four transports to install and the only one that carries
        `%database%` without a DMV round-trip, which is why `ad-setup` offers it before it offers
        anything involving Common Files. `merge_custom_action` is idempotent -- it replaces our
        entry by `Name` or appends it and leaves every other action alone -- so answering yes twice
        writes once and reports `unchanged` the second time.

        Answering *no* never removes an installed action. `ad-setup --patch` runs this prompt with
        whatever default the machine suggests when the key is out of scope, so a silent `no` is not
        evidence that anybody asked for a removal; `ad-pbip register-tool --te2 --remove` is the
        verb that means it, and the row names it.

        Offered only where Power BI Desktop is here too: an action that hands a Desktop instance
        over is worth nothing on a machine that has no Desktop.
        """
        from ...pbip import desktop as DT
        from ...pbip import external_tool as EXT
        state = DT.te2_action_state()
        if not state["present"]:
            return
        if not ctx.ask.confirm("powerbi.te2_custom_action",
                               f'Install the Tabular Editor custom action "{EXT.TE2_ACTION_NAME}"?', default):
            C.put(ctx.cfg, "powerbi.te2_custom_action", False)
            if state["installed"]:
                ctx.add(self.key, "powerbi/te2_action", "info", f'"{EXT.TE2_ACTION_NAME}" · {state["path"]}',
                        "`ad-pbip register-tool --te2 --remove` takes it out again")
            return
        mode = C.get(ctx.cfg, "powerbi.te2_action") or "process"
        try:
            res = EXT.merge_custom_action(EXT.te2_custom_action(mode=mode))
        except (ValueError, OSError) as e:
            ctx.add(self.key, "powerbi/te2_action", "warn", str(e)[:200],
                    "reinstall agentdata: the packaged handoff.te2.csx is missing or damaged")
            return
        if not res.get("ok"):
            # A CustomActions.json that does not parse is a refusal, never a rewrite: Tabular Editor
            # drops every one of the user's actions on a syntax error, so replacing the file would
            # destroy work that has nothing to do with us.
            ctx.add(self.key, "powerbi/te2_action", "warn", res.get("error", "cannot write the custom action"),
                    res.get("hint", ""), ("powerbi.te2_custom_action",))
            return
        C.put(ctx.cfg, "powerbi.te2_custom_action", True)
        ctx.add(self.key, "powerbi/te2_action", "ok", f'{res["changed"]} · {res["path"]}',
                "in Tabular Editor: File > Open > From DB > Local instance, pick the window, then "
                f'right-click the model -> {EXT.TE2_ACTION_NAME}')

    def _ask_ribbon(self, ctx: Context, default: bool) -> None:
        """Offer the ribbon, and do whichever of the three things this machine actually allows.

        The old version of this prompt called `register_tool()` unconditionally and, on the
        `PermissionError` that a machine-scoped folder always gives an unprivileged user, printed
        `run elevated`. That is the line #112 was filed about. So the machine is read first: the
        direct write happens only where the folder has been *measured* to accept one, and everywhere
        else this writes the package -- the file plus the one-page request -- and names the folder to
        attach to the ticket. Nothing here ever asks for elevation, because nothing here has any
        evidence that this user has any.
        """
        from ...pbip import desktop as DT
        from ...pbip import external_tool as EXT
        if not ctx.ask.confirm("powerbi.external_tool",
                               "Put agentdata on the Power BI Desktop External Tools ribbon?", default):
            return
        ribbon = DT.ribbon_state(run=ctx.det.run)
        if ribbon["state"] == DT.RIBBON_REGISTERED:
            C.put(ctx.cfg, "powerbi.external_tool", True)
            ctx.add(self.key, "powerbi/external_tool", "ok", f"registered · {ribbon['path']}")
            return
        if ribbon["state"] == DT.RIBBON_WRITABLE:
            ok, dest, hint = EXT.register_tool()
            if ok:
                C.put(ctx.cfg, "powerbi.external_tool", True)
                ctx.add(self.key, "powerbi/external_tool", "ok", f"registered · {textio.norm_path(dest)}")
                return
            # Measured writable and the write still failed: report it and name the package, which is
            # the next cheapest step, not a shell we have no evidence this user can open.
            ctx.add(self.key, "powerbi/external_tool", "warn", f"could not write {textio.norm_path(dest)}",
                    hint or f"`ad-pbip register-tool --package` writes {package_dir()} instead")
            return
        res = EXT.package()
        note = (f"send {res['dir']} to whoever owns {os.path.dirname(res['destination'])} -- REQUEST.md is the "
                "whole ticket, one Copy-Item line, and the same file works for every user and every Python version")
        if ribbon["state"] == DT.RIBBON_DISABLED:
            note = ("External Tools is switched off for this machine, so the file would change nothing until "
                    "that setting does; `ad-pbip handoff --active` needs none of it")
        ctx.add(self.key, "powerbi/external_tool", "info", f"{ribbon['state']} · packaged at {res['dir']}", note)

    def verify(self, ctx: Context) -> None:
        te2 = C.get(ctx.cfg, "powerbi.tools.te2_exe")
        dscmd = C.get(ctx.cfg, "powerbi.tools.dscmd_exe")
        if dscmd and ctx.det.exists(dscmd):
            rc, out, err = ctx.det.run([dscmd, "csv", "--help"], 60)
            text = (out or "") + (err or "")
            C.put(ctx.cfg, "powerbi.tools.dscmd_caps", {"file_flag": ("--file" in text) or (" -f" in text), "help_rc": rc})

        # powerbi/feature_decay check
        if ctx.online:
            features_md = os.path.join("docs", "power-bi-features.md")
            if os.path.exists(features_md):
                try:
                    import datetime
                    recheck_days = int(C.get(ctx.cfg, "powerbi.feature_recheck_days", 30) or 30)
                    now = datetime.datetime.now(datetime.timezone.utc).date()
                    decayed = []
                    checked = 0
                    with open(features_md, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("| `"):
                                parts = [p.strip() for p in line.split("|")[1:-1]]
                                if len(parts) >= 5:
                                    feat_name = parts[0].strip("`")
                                    v_date_str = parts[4]
                                    try:
                                        v_date = datetime.date.fromisoformat(v_date_str)
                                        days = (now - v_date).days
                                        checked += 1
                                        if days > recheck_days:
                                            decayed.append(f"{feat_name} ({days}d > {recheck_days}d)")
                                    except ValueError:
                                        pass
                    if decayed:
                        ctx.add(self.key, "powerbi/feature_decay", "warn",
                                f"{len(decayed)} features have decayed verifications: {', '.join(decayed[:3])}",
                                "re-verify features with `ad-pbip check --server ... --features` and update docs/power-bi-features.md")
                    else:
                        ctx.add(self.key, "powerbi/feature_decay", "ok", f"all {checked} features verified within {recheck_days}d")
                except Exception as e:
                    ctx.add(self.key, "powerbi/feature_decay", "warn", f"decay check failed: {e}")

        # powerbi/bridge_drift check (warn-only)
        try:
            from ...pbip import bridge as BR
            b_probe = BR.probe_bridge()
            if b_probe.get("pipe_present"):
                if b_probe.get("drift") != "none":
                    ctx.add(self.key, "powerbi/bridge_drift", "warn",
                            f"Bridge manifest drift detected: {b_probe.get('drift_summary')}",
                            "run `ad-pbip bridge record --pid <pid>` to update baseline transcript")
                else:
                    ctx.add(self.key, "powerbi/bridge_drift", "ok",
                            f"Bridge manifest matches baseline ({len(b_probe.get('operations', []))} ops, rtt {b_probe.get('rtt_ms')}ms)")
            else:
                ctx.add(self.key, "powerbi/bridge_drift", "ok", "no active bridge pipe (optional preview transport)")
        except Exception as e:
            ctx.add(self.key, "powerbi/bridge_drift", "warn", f"bridge probe failed: {e}")

        workspaces = list(C.get(ctx.cfg, "powerbi.workspaces", []) or [])
        if not workspaces:
            return

        def _run_te2_smoke(ws):
            with tempfile.TemporaryDirectory() as td:
                csx = os.path.join(td, "ping.csx")
                with open(csx, "w", encoding="utf-8") as f:
                    f.write(PING_CSX)
                rc, out, err = ctx.det.run([te2, ws["xmla"], ws["models"][0], "-S", csx], 180)
            return ws, rc, out, err

        import concurrent.futures
        futures = {}
        max_workers = min(8, max(1, len(workspaces)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            for ws in workspaces:
                if (te2 and ctx.det.exists(te2)) and ws.get("models"):
                    futures[ws.get("name")] = pool.submit(_run_te2_smoke, ws)

            for ws in workspaces:
                name, tag = ws.get("name"), f"workspace {ws.get('name')}"
                if not (te2 and ctx.det.exists(te2)):
                    ctx.add(self.key, tag, "skip", "no te2_exe for the XMLA smoke test")
                    continue
                if not ws.get("models"):
                    ctx.add(self.key, tag, "skip", "no model names to test")
                    continue
                _ws, rc, out, err = futures[name].result()
                if rc == 0:
                    C.stamp(ctx.cfg, f"powerbi:xmla:{name}")
                    ctx.add(self.key, tag, "ok", f"Tabular Editor connected to {ws['models'][0]}")
                else:
                    ctx.add(self.key, tag, "fail", ((out or "") + (err or "")).strip()[-200:] or f"exit {rc}",
                            "XMLA read needs Premium/PPU with the endpoint enabled; check workspace/model names; az login")

            # powerbi/refresh_history online probe
            az = C.get(ctx.cfg, "powerbi.az_exe") or getattr(ctx.det, "az", None) or "az"
            if az and workspaces:
                first_ws = workspaces[0]
                ws_name = first_ws.get("name")
                models = first_ws.get("models", [])
                tag = "powerbi/refresh_history"
                keys = ("powerbi.workspaces.select", "powerbi.az_login")
                if models and ws_name:
                    try:
                        from ...pbi.client import FabricClient
                        fc = FabricClient(az_exe=az, runner=ctx.det.run)
                        ws_id, _ = fc.resolve_workspace(ws_name)
                        m_id, _ = fc.resolve_item(ws_id, models[0], kind="model")
                        rc, data, _, _ = fc.rest_call("GET", f"https://api.fabric.microsoft.com/v1/workspaces/{ws_id}/semanticModels/{m_id}/refreshes", check=False)
                        if rc == 0:
                            ctx.add(self.key, tag, "ok", f"endpoint readable for {ws_name}/{models[0]}")
                        else:
                            ctx.add(self.key, tag, "warn", f"could not read refresh history (exit {rc})", "check permissions or run az login", keys)
                    except Exception as e:
                        ctx.add(self.key, tag, "warn", f"refresh history probe failed: {e}", "check permissions or run az login", keys)
