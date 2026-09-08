# PYTHON_ARGCOMPLETE_OK
"""ad-pbip: project · check · refs · lint · measure set. The PBIP is the source of truth; outputs are TOON + files."""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
from .textio import read_text
from . import completion
from . import config as C
from . import toon
from .console import utf8_stdout
from .model import AgentTable
from .model import OUT_DIR
from .pbip import audit as ADT
from .pbip import author as AU
from .pbip import brief as BR
from .pbip import catalog as CAT
from .pbip import check as CK
from .pbip import tom as TOM
from .pbip import dax as D
from .pbip import desktop as DT
from .pbip import dmv as DMV
from .pbip import edit as E
from .pbip import expr as EX
from .pbip import external_tool as EXT
from .pbip import normalize as N
from .pbip import pbir as P
from .pbip import probe as PRB
from .pbip import project as PJ
from .pbip import screenshot as SC
from .pbip import tmdl as T
from .pbip import trace as TR
from .policy import error, render
from . import policy, ui
from . import textio


def _resolve_desktop_target(a):
    """If --server, --pid, or --db are missing, prefer fresh .agent/desktop.json."""
    handoff = EXT.read_handoff()
    if handoff:
        if hasattr(a, "server") and not getattr(a, "server", None) and handoff.get("server"):
            a.server = handoff["server"]
        if hasattr(a, "db") and not getattr(a, "db", None) and handoff.get("database"):
            a.db = handoff["database"]
        if hasattr(a, "pid") and not getattr(a, "pid", None) and handoff.get("pid"):
            a.pid = handoff["pid"]
    return handoff


def _pbip_dir(arg: str | None) -> str:
    if arg:
        return arg
    facts = C.project_facts()
    if facts.get("pbip_path"):
        p = facts["pbip_path"]
        return os.path.dirname(p) or "." if p.lower().endswith(".pbip") else p
    if glob.glob("*.pbip") or glob.glob("*.Report"):
        return "."
    raise C.ConfigError("no PBIP given", hint="pass <pbip-dir> or set `pbip_path` in AGENTS.md")


def _findings_out(findings, source, extra=None, show=50):
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    order = {"error": 0, "warning": 1, "info": 2}
    findings = sorted(findings, key=lambda f: (order.get(f.severity, 3), f.where))
    meta = {"ok": errors == 0, "source": source, "errors": errors, "warnings": warnings, "infos": len(findings) - errors - warnings}
    if errors:
        meta["hint"] = findings[0].hint or findings[0].message
    if extra:
        meta.update(extra)
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k != "ok"], title=source, subtitle="ok" if meta["ok"] else "fail")
        if findings:
            ui.table(["severity", "kind", "where", "object", "message", "hint"],
                     [f.row() for f in findings[:show]],
                     title="findings", status_col=0, wrap=(4, 5))
        return 0 if errors == 0 else 1
    body = toon.table("findings", ["severity", "kind", "where", "object", "message", "hint"], [f.row() for f in findings[:show]])
    print("\n".join([toon.encode(meta, key="meta"), body]))
    return 0 if errors == 0 else 1


def cmd_project(a) -> int:
    pbip = _pbip_dir(a.pbip)
    model, report, norm = N.load_all(pbip, legacy_ok=a.legacy_ok)
    name = os.path.basename(os.path.abspath(pbip.rstrip("/\\")))
    out_dir = a.out or os.path.join(".agent", "pbip", name)
    res = PJ.write_projection(norm, model, report, out_dir, force=a.force)
    counts = {"tables": len(model.tables), "measures": sum(len(t["measures"]) for t in model.tables),
              "columns": sum(len(t["columns"]) for t in model.tables), "relationships": len(model.relationships),
              "pages": len(report.pages) if report else 0, "visuals": sum(len(p.visuals) for p in report.pages) if report else 0,
              "lint_errors": sum(1 for f in model.lint if f.severity == "error")}
    if policy.pretty():
        ui.facts([("pbip", textio.norm_path(pbip)), ("path", res["out_dir"]), ("skipped", res["skipped"]),
                  *[(k, v) for k, v in counts.items()]], title="ad-pbip project")
        if res.get("files"):
            ui.table(["file", "path"], [[f, textio.norm_path(os.path.join(res["out_dir"], f))] for f in res["files"]], title="projected files")
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-pbip project", "pbip": textio.norm_path(pbip), "skipped": res["skipped"],
                                    "path": res["out_dir"], "read": ["MODEL.md", "REPORT.md", "LINEAGE.md"] if report else ["MODEL.md"], **counts},
                           "files": res["files"]}))
    return 0


def cmd_check(a) -> int:
    _resolve_desktop_target(a)
    pbip = _pbip_dir(a.pbip)
    model, report, _ = N.load_all(pbip, legacy_ok=a.legacy_ok)
    findings = CK.check_model(model)
    extra = {"pbip": textio.norm_path(pbip), "report": bool(report), "te2": "skipped"}
    if report:
        findings += CK.check_report(report, model)
    else:
        findings.append(CK.Finding("warning", "report-missing", pbip, "", "no *.Report found; only the model was checked", "pass the folder that holds the .pbip"))
    cfg = C.load()
    if a.te2:
        te2 = a.te2_exe or C.get(cfg, "powerbi.tools.te2_exe") or C.project_facts().get("te2_exe")
        fs, info = CK.run_te2(model.definition_dir, te2, bpa=a.bpa)
        findings += fs
        extra["te2"] = "ran" if info.get("ran") else "not run"
    if a.server and report:
        fs, info = CK.evaluate_live(report, model, a.server, _dscmd(cfg, a.dscmd), a.db, file_flag=_file_flag(cfg))
        findings += fs
        extra.update({"live": a.server, "measures_probed": info.get("measures_probed", 0), "measures_failed": info.get("measures_failed", 0)})

    if getattr(a, "features", False):
        from .pbip import features as F
        feats = F.detect_features(model, report)
        feat_rows = []
        for f in feats:
            status = "ok" if f.present else "-"
            if a.server and f.present:
                v_res = F.verify_feature_live(f.feature, a.server, a.db or model.name or "Model")
                status = "ok" if v_res.get("verified") else f"fail: {v_res.get('error', '')}"
            feat_rows.append([f.feature, "true" if f.present else "false", ", ".join(f.objects) or "-", status])
        if policy.pretty():
            ui.table(["feature", "present", "objects", "status"], feat_rows, title="native features")
        else:
            print(toon.table("features", ["feature", "present", "objects", "status"], feat_rows))

    return _findings_out(findings, "ad-pbip check", extra)


def _dscmd(cfg, flag=None):
    return flag or C.get(cfg, "powerbi.tools.dscmd_exe") or C.project_facts().get("dscmd_exe") or ""


def _file_flag(cfg) -> bool:
    caps = C.get(cfg, "powerbi.tools.dscmd_caps") or {}
    return bool(caps.get("file_flag", True))


def _candidates() -> list[str]:
    facts = C.project_facts()
    c = [facts["pbip_path"]] if facts.get("pbip_path") else []
    return c + glob.glob("*.pbip") + glob.glob(os.path.join("*", "*.pbip"))


def cmd_desktop(a) -> int:
    cmd = getattr(a, "desktop_cmd", None)
    if cmd == "open":
        exe = getattr(a, "exe", None) or C.get(C.load(), "powerbi.tools.pbi_desktop_exe")
        res = DT.open_and_wait(a.path, wait_secs=getattr(a, "wait", 180), exe=exe)
        ok = res.get("ok", False)
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items() if k != "ok"], title="ad-pbip desktop open", subtitle="ok" if ok else "fail")
        else:
            print(toon.encode({"meta": res}))
        return 0 if ok else 1

    if cmd == "close":
        res = DT.close(a.pid, save=getattr(a, "save", False), discard=getattr(a, "discard", False))
        ok = res.get("ok", False)
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items() if k != "ok"], title="ad-pbip desktop close", subtitle="ok" if ok else "fail")
        else:
            print(toon.encode({"meta": res}))
        return 0 if ok else 1

    if cmd == "reload":
        res = DT.reload(a.pid, save=getattr(a, "save", False), discard=getattr(a, "discard", False), candidates=_candidates())
        ok = res.get("ok", False)
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items() if k != "ok"], title="ad-pbip desktop reload", subtitle="ok" if ok else "fail")
        else:
            print(toon.encode({"meta": res}))
        return 0 if ok else 1

    # Default / status:
    if not getattr(a, "pid", None):
        _resolve_desktop_target(a)
    pid = getattr(a, "pid", None)
    rows = [i.row() for i in DT.status(pid=pid, candidates=_candidates())]
    src = "ad-pbip desktop status" if cmd == "status" else "ad-pbip desktop"
    if not rows:
        if policy.pretty():
            ui.note("no running Power BI Desktop instance found; open the .pbip (ad-pbip launch <pbip>)")
        else:
            print(toon.encode({"meta": {"ok": True, "source": src, "instances": 0,
                                        "hint": "no running Power BI Desktop instance found; open the .pbip (ad-pbip launch <pbip>)"}}))
        return 0
    print(render(AgentTable.from_records(rows, name="desktop", source=src), extra={"instances": len(rows)}))
    return 0


def cmd_capabilities(a) -> int:
    pid = getattr(a, "pid", None)
    caps = DT.capabilities(pid=pid)
    avail = sum(1 for c in caps if c.get("available"))
    t = AgentTable.from_records(DT.capability_view(caps), name="capabilities", source="ad-pbip capabilities")
    print(render(t, extra={"available": avail, "total": len(caps)}))
    return 0


def cmd_bridge(a) -> int:
    from .pbip import bridge as BR
    bcmd = getattr(a, "bridge_cmd", "probe")
    if bcmd == "probe":
        pid = getattr(a, "pid", None)
        res = BR.probe_bridge(pid=pid)
        ops = res.get("operations", [])
        t = AgentTable.from_records(
            [{"operation": op, "status": "declared"} for op in ops],
            name="bridge_operations",
            source="ad-pbip bridge probe",
        )
        meta = {
            "ok": True,
            "source": "ad-pbip bridge probe",
            "pipe_present": res.get("pipe_present", False),
            "pid": res.get("pid"),
            "rtt_ms": res.get("rtt_ms", 0),
            "version": res.get("version", "unknown"),
            "drift": res.get("drift", "unknown"),
            "drift_summary": res.get("drift_summary", ""),
        }
        if not res.get("pipe_present"):
            meta["hint"] = res.get("reason") or "bridge pipe not active (toggle preview feature or launch Desktop)"
        print(render(t, extra=meta))
        return 0

    if bcmd == "record":
        pid = getattr(a, "pid", None)
        if not pid:
            print(error("--pid is required to record bridge transcript", "pass --pid <pid>", "ad-pbip bridge record"))
            return 1
        try:
            out_file = BR.record_transcript(pid=pid, out_dir=getattr(a, "out", None))
            t = AgentTable.from_records([{"path": out_file, "status": "recorded"}], name="record", source="ad-pbip bridge record")
            print(render(t, extra={"ok": True, "source": "ad-pbip bridge record", "pid": pid, "out": out_file}))
            return 0
        except Exception as e:
            print(error(f"failed to record bridge transcript: {e}", "ensure Desktop bridge is running on pipe", "ad-pbip bridge record"))
            return 1

    return 0


# ------------------------------------------------------- the handoff, the ribbon file, the probe
#
# The verbs of epic #112. The ribbon costs one privileged write nobody on the machine that epic
# measured can perform, so the operator's side of it is three commands: hand off through whichever
# transport is actually live, produce (never place) the one file IT must place, and print what the
# machine offers so the answer arrives as evidence rather than as a guess.


def _handoff_refusal(res: dict) -> int:
    """Print what the gate saw, then stop. #41: two windows and no flag is a refusal, not a coin toss.

    A handoff writes a server address that the next twenty commands trust without re-checking, so
    the list of open documents is the point of the output, not decoration: the human reads it, picks
    one, and re-runs with the flag the hint names. `zorder` 0 is the window they touched last.
    """
    choices = res.get("choices") or []
    cols = ["zorder", "pid", "title", "file", "server"]
    rows = [[c.get("zorder") if c.get("zorder") is not None else "", c.get("pid"), c.get("title") or "",
             c.get("file") or "", c.get("server") or ""] for c in choices]
    if policy.pretty():
        ui.facts([("fail", res.get("fail")), ("hint", res.get("hint"))],
                 title="ad-pbip handoff", subtitle="refused")
        if rows:
            ui.table(cols, rows, title="open Power BI Desktop documents", wrap=(2, 3))
    else:
        print(error(f"handoff refused: {res.get('fail')}", res.get("hint", ""), "ad-pbip handoff"))
        if rows:
            print(toon.table("instances", cols, rows))
    # 2 when the human has to say which one they meant, 1 when there is nothing to hand off at all.
    return 2 if res.get("fail") in ("ambiguous", "no_match", "no_project", "no_zorder") else 1


def _handoff_out(res: dict) -> int:
    meta = {"ok": True, "source": "ad-pbip handoff",
            **{k: v for k, v in res.items() if k not in ("ok", "source", "choices", "instance")},
            "next": "ad-pbip desktop / dmv / visual-query now need no --server"}
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k != "ok"], title="ad-pbip handoff")
    else:
        print(toon.encode({"meta": meta}))
    return 0


def _click_transport() -> dict:
    r"""Which button was pressed, read off the machine rather than assumed.

    The ribbon and the Tabular Editor custom action launch the *same* command line -- `pbip handoff
    --server ... --database ...` -- so nothing in argv can say which one ran it. Two reads settle it
    without a flag Desktop has no way to pass: `agentdata.pbitool.json` is either in the machine's
    External Tools folder or it is not, and our action is either in this user's `CustomActions.json`
    or it is not. Both are reads; neither probes, elevates or writes.

    With neither installed the two fields are simply absent, which is what `.agent/desktop.json`
    looked like before transports existed and what `read_handoff()` already tolerates. An invented
    transport would be worse than a missing one -- `ad-doctor` would report a ribbon this machine
    does not have.
    """
    try:
        if os.path.exists(os.path.join(EXT.external_tools_dir(), EXT.TOOL_FILENAME)):
            return {"transport": "ribbon:machine", "database_source": "ribbon"}
        if DT.te2_action_state().get("installed"):
            return {"transport": "te2:local", "database_source": "te2"}
    except Exception:  # noqa: BLE001 - a handoff must never fail over a question about its own label
        pass
    return {}


def _merge_desktop_json(path: str | None, extra: dict) -> None:
    """Add the transport fields to the file `external_tool.handoff` just wrote, and only those.

    `external_tool.handoff` stays the single writer of `.agent/desktop.json`; this re-opens what it
    wrote and adds two keys, exactly as `desktop.handoff` does for the flag transports. A file we
    cannot read back is not worth failing a handoff over -- the server address is already in it.
    """
    if not extra or not path or not os.path.exists(path):
        return
    try:
        payload = json.loads(textio.read_text(path))
    except (OSError, ValueError):
        return
    if isinstance(payload, dict):
        payload.update(extra)
        textio.write_json(path, payload)


def cmd_handoff(a) -> int:
    """Hand the running Desktop instance over -- by gesture, by name, or from the ribbon's click.

    `--active` is the window on top (the one the human touched last), `--file <name>` the document
    they can name without switching windows; with neither flag, one open instance is used and said
    so, and two is a refusal that prints both. `--server`/`--database` is the other direction: the
    two values Power BI Desktop substitutes when its ribbon button is pressed, and the same two the
    Tabular Editor action passes -- there is nothing to resolve, so nothing is.
    """
    active, want_file = getattr(a, "active", False), getattr(a, "file", None)
    server, database = getattr(a, "server", None), getattr(a, "database", None)

    if (active or want_file) and (server or database):
        print(error("--active/--file and --server/--database answer the same question two ways",
                    "--active and --file resolve the instance here; --server/--database are what "
                    "Power BI Desktop substitutes when its ribbon button is pressed. Pass one or the other",
                    "ad-pbip handoff"))
        return 2
    if database and not server:
        print(error("--database without --server", "the two are substituted together; pass --server "
                    "localhost:<port> as well, or drop both and use --active", "ad-pbip handoff"))
        return 2

    if server:
        res = EXT.handoff(server, database or "", project_dir=getattr(a, "project", None))
        if not res.get("ok"):
            # The ribbon and the TE2 action both land here, and both launch from a cwd that is not
            # the user's, so a refusal is the only honest answer when no project resolves.
            return _handoff_refusal(res)
        extra = _click_transport()
        _merge_desktop_json(res.get("path"), extra)
        return _handoff_out({**res, **extra})

    res = DT.handoff(active=active, file=want_file, project_dir=getattr(a, "project", None),
                     candidates=_candidates())
    if not res.get("ok"):
        return _handoff_refusal(res)
    return _handoff_out(res)


def _register_direct(a, dest_dir: str | None = None, ribbon: dict | None = None) -> int:
    """Write the file into the External Tools folder, because this machine says we may."""
    mode = "agnostic" if getattr(a, "launcher", None) else None
    ok, dest, hint = EXT.register_tool(target_dir=dest_dir, python_exe=getattr(a, "python", None),
                                       project_dir=getattr(a, "project", None), mode=mode,
                                       launcher=getattr(a, "launcher", None))
    if not ok:
        # The probe said writable and the write still failed: report it and name the package, which
        # is the next cheapest step. Never a shell we have no evidence this user can open.
        print(error(f"could not write {textio.norm_path(dest)}", hint or "", "ad-pbip register-tool"))
        return 1
    meta = {"ok": True, "source": "ad-pbip register-tool", "wrote": "direct",
            "path": textio.norm_path(dest), "tool": EXT.TOOL_FILENAME}
    if ribbon:
        meta["ribbon"] = ribbon["state"]
        meta["evidence"] = ribbon["evidence"]
    meta["next"] = "open Power BI Desktop -> External Tools -> agentdata"
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k != "ok"], title="ad-pbip register-tool")
    else:
        print(toon.encode({"meta": meta}))
    return 0


def _register_package(a, ribbon: dict | None = None) -> int:
    """Write the file and the request that asks whoever owns Common Files to place it.

    This is the honest front door on the machine #112 measured: we never write there ourselves, and
    the folder this leaves behind is what gets attached to the ticket.
    """
    res = EXT.package(out_dir=getattr(a, "out", None), launcher=getattr(a, "launcher", None))
    if not res.get("ok"):
        # Measured, not guessed: no bare name on this user's PATH reaches agentdata from a fresh
        # cmd.exe, so the file would spend somebody's ticket on a button that does nothing.
        print(error(f'refused: {res["fail"]} ({res["evidence"]})', res["hint"],
                    "ad-pbip register-tool --package"))
        return 2
    meta = {"ok": True, "source": "ad-pbip register-tool --package", "dir": res["dir"],
            "tool_json": res["tool_json"], "request": res["request"],
            "destination": res["destination"], "sha256": res["sha256"],
            "launcher": res["launcher"], "launcher_verdict": res["verdict"],
            "launches": f'{res["path"]} {res["arguments"]}'}
    if res["verdict"] == "unknown":
        # Off Windows there is no cmd.exe to ask, so the file is rendered with the default name and
        # said to be unverified. Sending it anyway is the operator's call, but they get to make it.
        meta["warn"] = (f'the launcher was not measured ({res["evidence"]}) -- run `ad-pbip probe` in a '
                        "fresh cmd.exe on the Windows machine and check verdict.launcher before sending "
                        "this to IT")
    if ribbon:
        meta["ribbon"] = ribbon["state"]
        meta["evidence"] = ribbon["evidence"]
        if ribbon["state"] == DT.RIBBON_DISABLED:
            meta["warn"] = ("External Tools is switched off for this machine, so the file would change "
                            "nothing until that setting is changed; the handoff does not need it "
                            "(`ad-pbip handoff --active`)")
    meta["next"] = (f'send {res["dir"]} to whoever owns {os.path.dirname(res["destination"])} -- '
                    "REQUEST.md is the whole ticket, one Copy-Item line, and the same file works for "
                    "every user and every Python version. Meanwhile `ad-pbip handoff --active` needs none of it")
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k != "ok"], title="ad-pbip register-tool --package")
    else:
        print(toon.encode({"meta": meta}))
    return 0


def _register_te2(a) -> int:
    """Install or remove the per-user Tabular Editor custom action. No privileged write anywhere."""
    cfg = C.load()
    mode = C.get(cfg, "powerbi.te2_action") or "process"
    path = EXT.custom_actions_path()
    try:
        if getattr(a, "remove", False):
            res = EXT.remove_custom_action(path=path)
        else:
            payload = EXT.te2_custom_action(mode=mode, launcher=getattr(a, "launcher", None))
            res = EXT.merge_custom_action(payload, path=path)
    except (ValueError, OSError) as e:
        print(error(str(e)[:300], "reinstall agentdata: the packaged handoff.te2.csx is missing or damaged",
                    "ad-pbip register-tool --te2"))
        return 2
    if not res.get("ok"):
        # A CustomActions.json that does not parse is a refusal, never a rewrite: Tabular Editor
        # drops every one of the user's actions on a syntax error.
        print(error(res.get("error", "cannot write the custom action"), res.get("hint", ""),
                    "ad-pbip register-tool --te2"))
        return 1
    meta = {"ok": True, "source": "ad-pbip register-tool --te2", "action": res["action"],
            "changed": res["changed"], "path": res["path"], "actions": res["count"]}
    if not getattr(a, "remove", False):
        meta["mode"] = mode
        meta["next"] = ("in Tabular Editor: File > Open > From DB > Local instance, pick the window, "
                        f'then right-click the model -> {EXT.TE2_ACTION_NAME}')
    else:
        meta["next"] = "the action is gone; `ad-pbip handoff --active` hands off without it"
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k != "ok"], title="ad-pbip register-tool --te2")
    else:
        print(toon.encode({"meta": meta}))
    return 0


def cmd_register_tool(a) -> int:
    r"""Put agentdata on the External Tools ribbon, or produce the file that asks someone who can.

    With no flags this reads the machine before it writes anything: the direct write happens only
    where `ad-pbip capabilities` says that folder accepts one. Everywhere else -- which is the
    managed laptop of #112 -- it does exactly what `--package` does and says where the file went,
    because `%CommonProgramFiles%` is Administrators-only and telling a user who cannot elevate to
    elevate is worse than saying nothing.
    """
    remove, te2, package = getattr(a, "remove", False), getattr(a, "te2", False), getattr(a, "package", False)
    if remove and not te2:
        print(error("--remove undoes the Tabular Editor custom action, so it needs --te2",
                    "run `ad-pbip register-tool --te2 --remove`", "ad-pbip register-tool"))
        return 2
    if te2:
        return _register_te2(a)
    if package:
        return _register_package(a)
    if getattr(a, "target_dir", None) or getattr(a, "python", None) or getattr(a, "project", None):
        return _register_direct(a, dest_dir=getattr(a, "target_dir", None))

    ribbon = DT.ribbon_state()
    if ribbon["state"] == DT.RIBBON_REGISTERED:
        meta = {"ok": True, "source": "ad-pbip register-tool", "wrote": "nothing",
                "ribbon": ribbon["state"], "path": ribbon["path"], "evidence": ribbon["evidence"],
                "next": "open Power BI Desktop -> External Tools -> agentdata"}
        if policy.pretty():
            ui.facts([(k, v) for k, v in meta.items() if k != "ok"], title="ad-pbip register-tool")
        else:
            print(toon.encode({"meta": meta}))
        return 0
    if ribbon["state"] == DT.RIBBON_WRITABLE:
        return _register_direct(a, ribbon=ribbon)
    return _register_package(a, ribbon=ribbon)


def cmd_probe(a) -> int:
    """The #113 read-only report: one command, one block to paste into the issue.

    Printed whole rather than through `policy.render`, which samples a table this long down to
    twenty rows. A sampled probe is a probe that answers a different question than the one asked,
    and the value of this output is that every row of it reaches the issue.
    """
    rows = PRB.report()
    cols = ["q", "name", "value", "reason"]
    human = sum(1 for r in rows if r.get("value") == PRB.HUMAN)
    verdicts = {r["name"]: r["value"] for r in rows if r["name"].startswith("verdict.")}
    meta = {"ok": True, "source": "ad-pbip probe", "rows": len(rows), "reads_only": True,
            **verdicts, "ask_a_human": human,
            "next": "paste this block into issue #113, and answer the ask-a-human rows by clicking"}
    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k != "ok"], title="ad-pbip probe")
        ui.table(cols, [[r["q"], r["name"], r["value"], r["reason"]] for r in rows],
                 title="machine probe", wrap=(2, 3))
    else:
        print("\n".join([toon.encode(meta, key="meta"),
                         toon.table("probe", cols, [[r["q"], r["name"], r["value"], r["reason"]] for r in rows])]))
    return 0


def cmd_screenshot(a) -> int:
    if getattr(a, "compare", None):
        if len(a.compare) != 2:
            print(error("--compare requires exactly 2 image paths", "pass: --compare <a.png> <b.png>", "ad-pbip"))
            return 2
        img_a, img_b = a.compare
        masks = []
        res = SC.compare_images(img_a, img_b, threshold=getattr(a, "threshold", 0.5), masks=masks)
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items()], title="ad-pbip screenshot compare", subtitle=res["verdict"])
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip screenshot compare", **res}}))
        return 0 if res["verdict"] == "same" else 1

    if not getattr(a, "pid", None):
        _resolve_desktop_target(a)

    if not getattr(a, "pid", None):
        print(error("give --pid <pid> (ad-pbip desktop) or --compare <a.png> <b.png>", "", "ad-pbip"))
        return 2

    pages, visuals = SC.screenshot_session(a.pid, page=getattr(a, "page", None), all_pages=getattr(a, "all", False),
                                           scale=getattr(a, "scale", 1), visual=getattr(a, "visual", None),
                                           settle_s=getattr(a, "settle", 0.5), out_dir=getattr(a, "out", None))
    if not pages:
        print(error("no pages captured", "check --pid and that Desktop window is open", "ad-pbip"))
        return 1

    t = AgentTable.from_records(pages, name="screenshots", source="ad-pbip screenshot")
    print(render(t, extra={"pages": len(pages), "visuals": len(visuals)}))
    return 0


def cmd_launch(a) -> int:
    exe = a.exe or C.get(C.load(), "powerbi.tools.pbi_desktop_exe")
    res = DT.launch(a.path, exe if exe and os.path.exists(exe) else None)
    if policy.pretty():
        ui.facts([("path", a.path), *[(k, v) for k, v in res.items()]], title="ad-pbip launch")
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-pbip launch", **res, "next": "wait for Desktop to load, then ad-pbip desktop"}}))
    return 0


def cmd_visual_query(a) -> int:
    _resolve_desktop_target(a)
    pbip = _pbip_dir(a.pbip)
    model, report, _ = N.load_all(pbip, legacy_ok=True)
    if not report:
        print(error("no report in this PBIP", "", "ad-pbip")); return 2
    needle = a.visual.lower()
    hits = [(p, v) for p in report.pages for v in p.visuals if (v.id.lower() == needle or (v.title or "").lower().find(needle) >= 0)
            and (not a.page or p.name.lower() == a.page.lower() or p.id.lower() == a.page.lower())]
    if len(hits) != 1:
        print(error(f"{len(hits)} visuals match {a.visual!r}", "use the visual id from REPORT.md, or add --page", "ad-pbip")); return 2
    page, visual = hits[0]
    dax, notes = D.visual_query(visual, N.ModelIndex(model, report), extra_filters=list(page.filters) + list(report.filters), top_n=a.top)
    os.makedirs(OUT_DIR, exist_ok=True)
    dax_path = textio.norm_path(os.path.join(OUT_DIR, f"{visual.id}_visual.dax"))
    with open(dax_path, "w", encoding="utf-8") as f:
        f.write(dax)
    if a.dry_run or not a.server:
        if policy.pretty():
            ui.facts([("visual", visual.id), ("title", visual.title or ""), ("page", page.name),
                      ("dax_path", dax_path), ("skipped", notes),
                      ("note", "no --server: query written, not executed")], title="ad-pbip visual-query")
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip visual-query", "visual": visual.id, "title": visual.title, "page": page.name,
                                        "dax_path": dax_path, "skipped": notes, "note": "no --server: query written, not executed"}}))
        print(dax)
        return 0
    cfg = C.load()
    try:
        t = D.run_dax(dax, a.server, _dscmd(cfg, a.dscmd), a.db, file_flag=_file_flag(cfg), name=a.name or f"visual_{visual.id[:8]}")
    except D.DaxError as e:
        print(error(str(e)[:300], "check --server (ad-pbip desktop) and the DAX in dax_path; a DAX error here is a real report failure", "ad-pbip"))
        return 1
    t.source = f"ad-pbip visual-query {visual.id} @ {a.server}"
    print(render(t, extra={"visual": visual.id, "title": visual.title or "", "dax_path": dax_path, "skipped": notes}))
    return 0


def cmd_lint(a) -> int:
    target = a.path
    files = [target] if os.path.isfile(target) else T.model_files(target)
    findings: list[CK.Finding] = []
    for p in files:
        tf = T.read_file(p)
        for f in T.lint_file(tf):
            findings.append(CK.Finding(f.severity, "tmdl-" + f.rule, f"{os.path.relpath(p, target if os.path.isdir(target) else os.path.dirname(target) or '.').replace(chr(92), '/')}:{f.line}", "", f.message, f.fix))
    return _findings_out(findings, "ad-pbip lint", {"files": len(files)})


def cmd_refs(a) -> int:
    pbip = _pbip_dir(a.pbip)
    if getattr(a, "live", False):
        _resolve_desktop_target(a)
        if not getattr(a, "server", None):
            print(error("refs --live requires --server localhost:<port>", "pass --server or use Desktop External Tools", "ad-pbip"))
            return 2
        t = DMV.refs_live(pbip, a.server, database=getattr(a, "db", None))
        print(render(t, extra={"server": a.server, "live": True}))
        return 0

    model, report, norm = N.load_all(pbip, legacy_ok=True)
    lin = norm["lineage"]
    rows: list[dict] = []
    meta: dict = {"ok": True, "source": "ad-pbip refs"}
    if a.visual or a.page:
        if not report:
            print(error("no report in this PBIP", "refs --visual needs a *.Report", "ad-pbip")); return 2
        needle = (a.visual or a.page).lower()
        hits = [(p, v) for p in report.pages for v in p.visuals
                if (a.visual and (v.id.lower() == needle or (v.title or "").lower().find(needle) >= 0)) or (a.page and (p.name.lower() == needle or p.id.lower() == needle))]
        if not hits:
            print(error(f"no visual/page matches {needle!r}", "use the id or title from REPORT.md (ad-pbip project)", "ad-pbip")); return 2
        by_table = {t["name"]: t for t in model.tables}
        for p, v in hits:
            for r in v.fields:
                if not r.entity:
                    continue
                row = {"page": p.name, "visual": v.id, "title": v.title, "context": r.context, "kind": r.kind, "field": r.label(), "deps": "", "sources": ""}
                if r.kind == "measure":
                    t = by_table.get(r.entity)
                    m = next((x for x in (t["measures"] if t else []) if x["name"] == r.prop), None)
                    if m:
                        row["deps"] = ";".join(m["deps"]["columns"] + [f"[{d}]" for d in m["deps"]["measures"]])
                        tabs = {T.split_ref(d)[0] for d in m["deps"]["columns"]} | {r.entity}
                        row["sources"] = ";".join(sorted({s for tn in tabs if tn for s in lin["sources"].get(tn, [])}))
                else:
                    row["sources"] = ";".join(lin["sources"].get(r.entity, []))
                rows.append(row)
        meta["matched"] = len(hits)
    else:
        label = f"'{a.table}'[{a.column or a.measure}]" if (a.column or a.measure) else None
        if not a.table:
            print(error("give --table (with --column/--measure), --visual or --page", "", "ad-pbip")); return 2
        if label:
            for u in lin["field_usage"].get(label, []):
                rows.append({"where": "report", "page": u["page"], "visual": u["visual"], "title": u["title"], "context": u["context"], "object": label})
            for user in lin["measure_usage"].get(label if a.column else f"[{a.measure}]", []):
                rows.append({"where": "measure", "page": "", "visual": "", "title": "", "context": "dax", "object": user})
            for r in model.relationships:
                if a.column and ((r["fromTable"], r["fromColumn"]) == (a.table, a.column) or (r["toTable"], r["toColumn"]) == (a.table, a.column)):
                    rows.append({"where": "relationship", "page": "", "visual": "", "title": "", "context": r["name"], "object": f"{r['fromTable']}[{r['fromColumn']}] -> {r['toTable']}[{r['toColumn']}]"})
            for t in model.tables:
                for c in t["columns"]:
                    if a.column and t["name"] == a.table and c["sortByColumn"] == a.column:
                        rows.append({"where": "sortByColumn", "page": "", "visual": "", "title": "", "context": "", "object": f"'{t['name']}'[{c['name']}]"})
                for h in t["hierarchies"]:
                    if a.column and t["name"] == a.table and any(lv["column"] == a.column for lv in h["levels"]):
                        rows.append({"where": "hierarchy", "page": "", "visual": "", "title": "", "context": "", "object": f"'{t['name']}'[{h['name']}]"})
        else:
            for lbl, uses in lin["field_usage"].items():
                if lbl.startswith(f"'{a.table}'["):
                    for u in uses:
                        rows.append({"where": "report", "page": u["page"], "visual": u["visual"], "title": u["title"], "context": u["context"], "object": lbl})
        meta["object"] = label or f"table {a.table}"
        meta["sources"] = ";".join(lin["sources"].get(a.table, []))
    t = AgentTable.from_records(rows, name="refs", source="ad-pbip refs")
    if rows:
        print(render(t, extra={k: v for k, v in meta.items() if k not in ("ok", "source")}))
    elif policy.pretty():
        ui.facts([(k, v) for k, v in meta.items() if k not in ("ok", "source")] + [("rows", 0), ("note", "no uses found")], title="ad-pbip refs")
    else:
        print(toon.encode({"meta": {**meta, "rows": 0, "note": "no uses found"}}))
    return 0


def cmd_measure_set(a) -> int:
    pbip = _pbip_dir(a.pbip)
    defn = N.find_model_dir(pbip)
    expr = a.expr if a.expr is not None else read_text(a.expr_file)
    op = {
        "op": "measure.set",
        "table": a.table,
        "name": a.name,
        "expression": expr,
        "formatString": a.format_string,
        "displayFolder": a.display_folder,
        "description": a.description,
        "isHidden": True if a.hidden else None,
    }
    try:
        res = TOM.model_apply([op], definition_dir=defn, dry_run=a.dry_run)
    except (LookupError, ValueError) as e:
        print(error(str(e), "check the table name (MODEL.md) and the DAX; nothing was written", "ad-pbip"))
        return 2

    results = res.get("results", [])
    if results and results[0].get("status") == "fail":
        print(error(results[0].get("error", "apply failed"), "check DAX and table", "ad-pbip"))
        return 2

    apply_res = results[0] if results else {}
    fact_dict = {
        "action": apply_res.get("action", "applied"),
        "table": a.table,
        "measure": a.name,
        "file": f"tables/{a.table}.tmdl",
        "line": apply_res.get("line", 1),
        "dry_run": a.dry_run,
    }
    if policy.pretty():
        ui.facts([("table", a.table), ("name", a.name), *[(k, v) for k, v in fact_dict.items()]], title="ad-pbip measure set")
    else:
        print(toon.encode({"meta": {"ok": True, "source": "ad-pbip measure set", **fact_dict,
                                    "next": "ad-pbip check --te2, then reopen the PBIP in Desktop (it does not hot-reload TMDL)"}}))
    return 0


def cmd_trace(a) -> int:
    trace_cmd = getattr(a, "trace_cmd", None)
    if trace_cmd == "start":
        _resolve_desktop_target(a)
        if not getattr(a, "server", None) and not getattr(a, "pid", None):
            print(error("give --pid <pid> or --server localhost:<port>", "", "ad-pbip"))
            return 2
        server = a.server or f"localhost:{a.pid}"
        listener, out_file, meta = TR.start_trace(server, pid=getattr(a, "pid", None), seconds=getattr(a, "seconds", 60),
                                                  out_path=getattr(a, "out", None), database=getattr(a, "db", None))
        if policy.pretty():
            ui.facts([(k, v) for k, v in meta.items()], title="ad-pbip trace started")
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip trace start", **meta, "next": f"run actions, then ad-pbip trace report {out_file}"}}))
        return 0

    if trace_cmd == "report":
        pbip = None
        try:
            pbip = _pbip_dir(getattr(a, "pbip", None))
        except Exception:
            pass
        t = TR.report_trace(a.file, report_dir=pbip)
        print(render(t, extra={"events_file": a.file}))
        return 0

    return 0


def cmd_dmv(a) -> int:
    _resolve_desktop_target(a)
    if not getattr(a, "server", None):
        print(error("give --server localhost:<port> (or press External Tools -> agentdata in Desktop)", "", "ad-pbip"))
        return 2
    try:
        t = DMV.run_dmv(a.server, a.query, database=getattr(a, "db", None))
        if a.query.strip().lower() == "segments":
            t = DMV.normalize_segments(t)
    except Exception as e:
        print(error(str(e)[:300], "verify server address and that Desktop Analysis Services is running", "ad-pbip"))
        return 1
    print(render(t, extra={"server": a.server, "query": a.query}))
    return 0


def cmd_page_cost(a) -> int:
    _resolve_desktop_target(a)
    if not getattr(a, "pid", None):
        print(error("give --pid <pid> (ad-pbip desktop)", "", "ad-pbip"))
        return 2
    pbip = None
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
    except Exception:
        pass
    t = DMV.page_cost(a.pid, a.page, pbip_dir=pbip, seconds=getattr(a, "seconds", 15))
    print(render(t, extra=t.raw or {}))
    return 0


def cmd_schema(a) -> int:
    try:
        res = CAT.schema_update()
    except Exception as e:
        print(error(str(e), "run ad-pbip schema update", "ad-pbip"))
        return 1
    if policy.pretty():
        ui.facts([(k, v) for k, v in res.items() if k not in ("visual_types", "formatting_objects")], title="ad-pbip schema update")
    else:
        print(toon.encode({"meta": {"source": "ad-pbip schema update", **res}}))
    return 0


def cmd_catalog(a) -> int:
    sub_c = getattr(a, "catalog_cmd", None)
    try:
        if sub_c == "list":
            t = CAT.list_visuals()
            print(render(t))
            return 0
        if sub_c == "describe":
            t = CAT.describe_visual(a.type)
            print(render(t, extra=t.raw))
            return 0
        if sub_c == "formatting":
            t = CAT.formatting_catalog(visual_type=getattr(a, "type", None),
                                       object_name=getattr(a, "object", None),
                                       property_name=getattr(a, "property", None),
                                       search=getattr(a, "search", None))
            print(render(t))
            return 0
    except (KeyError, FileNotFoundError) as e:
        print(error(str(e), "check visual type with `ad-pbip catalog list`", "ad-pbip"))
        return 2
    return 0


def cmd_expr(a) -> int:
    sub_c = getattr(a, "expr_cmd", None)
    if sub_c == "encode":
        enc = EX.encode_expr(a.text)
        if policy.pretty():
            ui.facts([("input", a.text), ("encoded", json.dumps(enc))], title="ad-pbip expr encode")
        else:
            print(json.dumps(enc, indent=2))
        return 0
    if sub_c == "decode":
        dec = EX.decode_expr(a.json)
        if policy.pretty():
            ui.facts([("input", a.json), ("decoded", dec)], title="ad-pbip expr decode")
        else:
            print(dec)
        return 0
    return 0


def cmd_theme(a) -> int:
    sub_c = getattr(a, "theme_cmd", None)
    if sub_c == "shade":
        try:
            shaded = EX.shade_color(a.color, a.pct)
        except ValueError as e:
            print(error(str(e), "use format #RRGGBB and pct between -100 and 100", "ad-pbip"))
            return 2
        if policy.pretty():
            ui.facts([("color", a.color), ("pct", a.pct), ("result", shaded)], title="ad-pbip theme shade")
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip theme shade", "color": a.color, "pct": a.pct, "result": shaded}}))
        return 0
    if sub_c == "set":
        try:
            pbip = _pbip_dir(getattr(a, "pbip", None))
            res = AU.theme_set(pbip, a.file)
        except (FileNotFoundError, ValueError) as e:
            print(error(str(e), "check theme file path", "ad-pbip"))
            return 2
        if policy.pretty():
            ui.facts([(k, v) for k, v in res.items()], title="ad-pbip theme set")
        else:
            print(toon.encode({"meta": {"source": "ad-pbip theme set", **res}}))
        return 0
    return 0


def cmd_preview(a) -> int:
    sub_c = getattr(a, "preview_cmd", None)
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        rep = P.load_report(pbip)
    except Exception as e:
        print(error(str(e), "provide valid PBIP path", "ad-pbip"))
        return 2

    if sub_c == "pages":
        rows = [[p.id, p.name, p.ordinal, getattr(p, "width", 1280), getattr(p, "height", 720), len(p.visuals)] for p in rep.pages]
        t = AgentTable("preview_pages", ["page_id", "display_name", "ordinal", "width", "height", "visuals_count"], rows, source="ad-pbip preview pages")
        print(render(t))
        return 0
    if sub_c == "visuals":
        rows = []
        for p in rep.pages:
            for v in p.visuals:
                pos = v.position or {}
                rows.append([p.name, v.id, v.type or "", v.title or "", pos.get("x", 0), pos.get("y", 0), pos.get("width", 0), pos.get("height", 0), len(v.fields)])
        t = AgentTable("preview_visuals", ["page", "visual_id", "type", "title", "x", "y", "width", "height", "fields_count"], rows, source="ad-pbip preview visuals")
        print(render(t))
        return 0
    if sub_c == "filters":
        rows = []
        for flt in rep.filters:
            rows.append(["report", "-", "-", flt.get("name", ""), flt.get("type", ""), flt.get("field", "")])
        for p in rep.pages:
            for flt in p.filters:
                rows.append(["page", p.name, "-", flt.get("name", ""), flt.get("type", ""), flt.get("field", "")])
            for v in p.visuals:
                for flt in v.filters:
                    rows.append(["visual", p.name, v.id, flt.get("name", ""), flt.get("type", ""), flt.get("field", "")])
        t = AgentTable("preview_filters", ["scope", "page", "visual", "filter_name", "type", "field"], rows, source="ad-pbip preview filters")
        print(render(t))
        return 0
    if sub_c == "themes":
        rj_path = os.path.join(rep.root, "definition", "report.json")
        tc = {}
        if os.path.exists(rj_path):
            tc = (P._load(rj_path) or {}).get("themeCollection") or {}
        rows = []
        for k, v in tc.items():
            if isinstance(v, dict):
                rows.append([k, v.get("name", ""), v.get("type", ""), v.get("path", "-")])
        t = AgentTable("preview_themes", ["slot", "name", "type", "path"], rows, source="ad-pbip preview themes")
        print(render(t))
        return 0
    return 0


def cmd_page(a) -> int:
    sub_c = getattr(a, "page_cmd", None)
    if getattr(a, "brief", None):
        stat = BR.brief_status(a.brief)
        if stat != "current":
            print(error(f"brief status is '{stat}'; approve with `ad-pbip brief approve {a.brief}`", "brief approval required", "ad-pbip"))
            return 2
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        if sub_c == "add":
            res = AU.page_add(pbip, a.name, after=getattr(a, "after", None),
                              width=getattr(a, "width", 1280), height=getattr(a, "height", 720))
        elif sub_c == "remove":
            res = AU.page_remove(pbip, a.page)
        elif sub_c == "move":
            res = AU.page_move(pbip, a.page, after=getattr(a, "after", None))
        else:
            return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(error(str(e), "check page arguments", "ad-pbip"))
        return 2

    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in res.items()], title=f"ad-pbip page {sub_c}")
    else:
        print(toon.encode({"meta": {"source": f"ad-pbip page {sub_c}", **res}}))
    return 0


def cmd_visual(a) -> int:
    sub_c = getattr(a, "visual_cmd", None)
    if getattr(a, "brief", None):
        stat = BR.brief_status(a.brief)
        if stat != "current":
            print(error(f"brief status is '{stat}'; approve with `ad-pbip brief approve {a.brief}`", "brief approval required", "ad-pbip"))
            return 2
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        if sub_c == "add":
            pos = None
            if getattr(a, "position", None):
                pos = tuple(int(x.strip()) for x in a.position.split(","))

            # Validate against brief layout contract if brief is provided
            if getattr(a, "brief", None):
                _, brief_data, _ = BR.parse_brief_file(a.brief)
                matched = False
                for p in brief_data.get("pages", []):
                    if p.get("name") == a.page or p.get("title") == a.page:
                        for pl in (p.get("layout_contract") or {}).get("placements", []):
                            if pos and pl.get("position"):
                                ppos = pl["position"]
                                if (pos[0], pos[1], pos[2], pos[3]) == (ppos.get("x"), ppos.get("y"), ppos.get("width"), ppos.get("height")):
                                    matched = True
                                    break
                            elif not pos and pl.get("type") == a.type:
                                matched = True
                                break
                if not matched:
                    print(error(f"visual placement does not match approved layout_contract for page '{a.page}'", "use approved placement coordinates", "ad-pbip"))
                    return 2

            res = AU.visual_add(pbip, a.page, a.type, title=getattr(a, "title", None),
                                fields=getattr(a, "fields", None), position=pos)
        elif sub_c == "set":
            if "=" not in a.property:
                print(error("property must be format <object.property>=<value>", "", "ad-pbip"))
                return 2
            prop_path, val = a.property.split("=", 1)
            res = AU.visual_set(pbip, a.visual, prop_path, val)
        elif sub_c == "remove":
            res = AU.visual_remove(pbip, a.visual)
        else:
            return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(error(str(e), "check visual parameters with `ad-pbip catalog`", "ad-pbip"))
        return 2

    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in res.items()], title=f"ad-pbip visual {sub_c}")
    else:
        print(toon.encode({"meta": {"source": f"ad-pbip visual {sub_c}", **res}}))
    return 0


def cmd_brief(a) -> int:
    sub_c = getattr(a, "brief_cmd", None)
    if sub_c == "check":
        findings = BR.check_brief(a.spec)
        return _findings_out(findings, f"ad-pbip brief check {a.spec}")
    if sub_c == "approve":
        try:
            res = BR.approve_brief(a.spec)
        except (RuntimeError, ValueError) as e:
            print(error(str(e), "run interactively in terminal", "ad-pbip"))
            return 2
        if not res.get("approved"):
            print(error("brief approval aborted by user", "", "ad-pbip"))
            return 1
        if policy.pretty():
            ui.facts([(k, str(v)) for k, v in res.items()], title="ad-pbip brief approve")
        else:
            print(toon.encode({"meta": {"source": "ad-pbip brief approve", **res}}))
        return 0
    if sub_c == "status":
        stat = BR.brief_status(a.spec)
        if policy.pretty():
            ui.facts([("spec", a.spec), ("status", stat)], title="ad-pbip brief status")
        else:
            print(toon.encode({"meta": {"ok": stat == "current", "source": "ad-pbip brief status", "spec": a.spec, "status": stat}}))
        return 0 if stat == "current" else 1
    return 0


def cmd_model(a) -> int:
    cmd = getattr(a, "model_cmd", None)
    if cmd == "apply":
        _resolve_desktop_target(a)
        ops_raw = a.ops.strip()
        if os.path.exists(ops_raw):
            with open(ops_raw, "r", encoding="utf-8") as f:
                ops = json.load(f)
        else:
            try:
                ops = json.loads(ops_raw)
            except Exception as e:
                print(error(f"Failed to parse --ops: {e}", "provide valid path to JSON file or JSON array", "ad-pbip"))
                return 2

        server = getattr(a, "server", None)
        pid = getattr(a, "pid", None)
        model_dir = getattr(a, "model", None)
        pbip_dir = getattr(a, "pbip", None)

        if not server and not pid and not model_dir:
            if pbip_dir:
                model_dir = N.find_model_dir(pbip_dir)
            else:
                try:
                    cands = PJ.find_pbip(os.getcwd())
                    if cands:
                        model_dir = N.find_model_dir(cands[0])
                        pbip_dir = cands[0]
                except Exception:
                    pass

        try:
            res = TOM.model_apply(
                ops,
                server=server,
                pid=pid,
                database=getattr(a, "db", None),
                definition_dir=model_dir,
                save=getattr(a, "save", False),
                pbip_dir=pbip_dir,
                dry_run=getattr(a, "dry_run", False),
            )
        except Exception as e:
            print(error(str(e), "check ops definition and model state", "ad-pbip"))
            return 2

        tier = res.get("tier")
        results = res.get("results", [])
        has_fails = any(r.get("status") == "fail" for r in results)

        if policy.pretty():
            ui.facts([("tier", tier), ("ops", len(ops)), ("status", "fail" if has_fails else "ok")], title=f"ad-pbip model apply ({tier})")
            rows = []
            for r in results:
                rows.append([r.get("op", ""), r.get("status", ""), r.get("action", ""), r.get("object", ""), r.get("error", "")])
            t = AgentTable(["op", "status", "action", "object", "error"], rows, name="apply_results", source="ad-pbip model apply")
            print(render(t))
        else:
            print(toon.encode({"meta": {"ok": not has_fails, "source": "ad-pbip model apply", **res}}))
        return 2 if has_fails else 0

    elif cmd == "audit":
        _resolve_desktop_target(a)
        target = getattr(a, "definition", None)
        pbip = None
        defn = None
        if target:
            if os.path.exists(os.path.join(target, "model.tmdl")):
                defn = target
            else:
                try:
                    pbip = _pbip_dir(target)
                    defn = N.find_model_dir(pbip)
                except Exception:
                    defn = target
        else:
            try:
                cands = PJ.find_pbip(os.getcwd())
                if cands:
                    pbip = cands[0]
                    defn = N.find_model_dir(pbip)
            except Exception:
                pass

        if not defn or not os.path.isdir(defn):
            print(error("Could not find SemanticModel definition folder", "pass definition folder or PBIP path", "ad-pbip"))
            return 2

        model, report, _ = N.load_all(defn if not pbip else pbip, legacy_ok=True)

        if getattr(a, "copilot", False):
            copilot_res = ADT.audit_copilot(model)
            summary = copilot_res.summary()
            if policy.pretty():
                ui.facts([("score", f"{summary['score']}%"), ("passed", summary["passed"]), ("failed", summary["failed"])],
                         title="Copilot AI Readiness Audit")
                rows = [[it["category"], it["target"], it["status"], it["detail"]] for it in summary["items"]]
                t = AgentTable(["category", "target", "status", "detail"], rows, name="copilot_audit", source="ad-pbip model audit --copilot")
                print(render(t))
            else:
                print(toon.encode({"meta": {"ok": True, "source": "ad-pbip model audit --copilot", **summary}}))
            return 0

        findings = ADT.audit_model(model, report=report)
        if getattr(a, "bpa", False):
            cfg = C.load()
            te2_exe = C.get(cfg, "powerbi.tools.te2_exe") or C.project_facts().get("te2_exe")
            if te2_exe and os.path.exists(te2_exe):
                te2_findings, _ = CK.run_te2(defn, te2_exe, bpa=True)
                for tf in te2_findings:
                    findings.append(ADT.AuditFinding(
                        rule_id=f"te2-bpa:{tf.rule}",
                        severity=tf.severity,
                        what=tf.message,
                        why="Tabular Editor Best Practice Analyzer rule violation",
                        obj=tf.where,
                        where=tf.where,
                    ))

        rows = [f.row() for f in findings]
        errors = [f for f in findings if f.severity == "error"]
        if policy.pretty():
            ui.facts([("rules_evaluated", "8+"), ("findings", len(findings)), ("errors", len(errors))], title="Model Audit")
            t_rows = [[f.severity, f.rule_id, f.obj, f.what, json.dumps(f.fix) if f.fix else ""] for f in findings]
            t = AgentTable(["severity", "rule", "object", "what", "fix"], t_rows, name="audit_findings", source="ad-pbip model audit")
            print(render(t))
        else:
            print(toon.encode({
                "meta": {"ok": len(errors) == 0, "source": "ad-pbip model audit", "findings": len(findings), "errors": len(errors)},
                "rows": rows,
            }))
        return 2 if errors else 0

    elif cmd == "optimize":
        _resolve_desktop_target(a)
        server = getattr(a, "server", None)
        pid = getattr(a, "pid", None)
        if not server and not pid:
            print(error("give --pid <pid> or --server localhost:<port>", "model optimize runs against live instance", "ad-pbip"))
            return 2
        try:
            res = TOM.model_optimize(
                measure=a.measure,
                pid=pid,
                server=server,
                pbip_dir=getattr(a, "pbip", None),
                database=getattr(a, "db", None),
            )
        except Exception as e:
            print(error(str(e), "optimization failed or regressed", "ad-pbip"))
            return 2

        if policy.pretty():
            facts = [(k, str(v)) for k, v in res.items() if not k.endswith("_expression")]
            ui.facts(facts, title=f"DAX Optimization: [{a.measure}]")
        else:
            print(toon.encode({"meta": {"ok": True, "source": "ad-pbip model optimize", **res}}))
        return 0

    return 0


def cmd_filter(a) -> int:
    sub_c = getattr(a, "filter_cmd", None)
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        if sub_c == "set":
            vals = [v.strip() for v in a.values.split(",")] if getattr(a, "values", None) else None
            bw = tuple(x.strip() for x in a.between.split(",")) if getattr(a, "between", None) else None
            res = AU.filter_set(pbip, a.scope, a.field, values=vals, between=bw,
                                top=getattr(a, "top", None), page=getattr(a, "page", None),
                                visual_id=getattr(a, "visual", None))
        else:
            return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(error(str(e), "check filter parameters", "ad-pbip"))
        return 2

    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in res.items()], title=f"ad-pbip filter {sub_c}")
    else:
        print(toon.encode({"meta": {"source": f"ad-pbip filter {sub_c}", **res}}))
    return 0


def cmd_bookmark(a) -> int:
    sub_c = getattr(a, "bookmark_cmd", None)
    try:
        pbip = _pbip_dir(getattr(a, "pbip", None))
        if sub_c == "add":
            v_list = [v.strip() for v in a.visuals.split(",")] if getattr(a, "visuals", None) else None
            res = AU.bookmark_add(pbip, a.name, a.page, visuals=v_list)
        else:
            return 0
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(error(str(e), "check bookmark parameters", "ad-pbip"))
        return 2

    if policy.pretty():
        ui.facts([(k, str(v)) for k, v in res.items()], title=f"ad-pbip bookmark {sub_c}")
    else:
        print(toon.encode({"meta": {"source": f"ad-pbip bookmark {sub_c}", **res}}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ad-pbip", description="PBIP projection, model<->report validation, TMDL lint and mechanical edits.")
    from . import version
    version.add_version(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("project", help="write the LLM projection (.agent/pbip/<name>/)")
    p.add_argument("pbip", nargs="?"); p.add_argument("--out"); p.add_argument("--force", action="store_true"); p.add_argument("--legacy-ok", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_project)
    p = sub.add_parser("check", help="cross-validate report fields against the TMDL model (+ TE2 build)")
    p.add_argument("pbip", nargs="?"); p.add_argument("--te2", action="store_true"); p.add_argument("--te2-exe"); p.add_argument("--bpa", action="store_true")
    p.add_argument("--server", help="localhost:<port> (ad-pbip desktop) or an XMLA URL: evaluate every measure the report uses")
    p.add_argument("--db"); p.add_argument("--dscmd"); p.add_argument("--legacy-ok", action="store_true")
    p.add_argument("--features", action="store_true", help="list native feature coverage table and run live checks per used feature")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_check)
    p_dt = sub.add_parser("desktop", help="Power BI Desktop session control: status, open, close, reload")
    p_dt.add_argument("--pid", type=int, help="filter by process id (status)")
    p_dt.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    dt_sub = p_dt.add_subparsers(dest="desktop_cmd", required=False)

    p_stat = dt_sub.add_parser("status", help="list running Desktop instances (pid, port, pages, unsaved, version)")
    p_stat.add_argument("--pid", type=int, help="filter by process id")
    p_stat.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_stat.set_defaults(fn=cmd_desktop)

    p_open = dt_sub.add_parser("open", help="open a .pbip/.pbix in Desktop and wait until ready")
    p_open.add_argument("path", help="path to .pbip or .pbix")
    p_open.add_argument("--wait", type=int, default=180, help="seconds to wait for Desktop readiness (default: 180; 0=fire-and-forget)")
    p_open.add_argument("--exe", help="explicit path to PBIDesktop.exe")
    p_open.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_open.set_defaults(fn=cmd_desktop)

    p_close = dt_sub.add_parser("close", help="close a running Desktop instance cleanly via WM_CLOSE")
    p_close.add_argument("--pid", type=int, required=True, help="process id to close")
    g_close = p_close.add_mutually_exclusive_group()
    g_close.add_argument("--save", action="store_true", help="save changes if prompted")
    g_close.add_argument("--discard", action="store_true", help="discard changes if prompted")
    p_close.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_close.set_defaults(fn=cmd_desktop)

    p_reload = dt_sub.add_parser("reload", help="reload a running Desktop instance after file edits")
    p_reload.add_argument("--pid", type=int, required=True, help="process id to reload")
    g_rel = p_reload.add_mutually_exclusive_group()
    g_rel.add_argument("--save", action="store_true", help="save changes before reload if prompted")
    g_rel.add_argument("--discard", action="store_true", help="discard changes before reload if prompted")
    p_reload.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_reload.set_defaults(fn=cmd_desktop)

    p_dt.set_defaults(fn=cmd_desktop)

    p_cap = sub.add_parser("capabilities", help="probe Power BI Desktop and toolchain capabilities table")
    p_cap.add_argument("--pid", type=int, help="evaluate capabilities for a specific Desktop pid")
    p_cap.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p_cap.set_defaults(fn=cmd_capabilities)

    # Bridge
    p_brg = sub.add_parser("bridge", help="Desktop bridge wire adapter probe and record")
    brg_sub = p_brg.add_subparsers(dest="bridge_cmd", required=True)
    p_bp = brg_sub.add_parser("probe", help="probe bridge pipe presence, manifest, RTT, and transcript drift")
    p_bp.add_argument("--pid", type=int, help="Power BI Desktop PID")
    p_bp.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_bp.set_defaults(fn=cmd_bridge)
    p_br_rec = brg_sub.add_parser("record", help="record golden transcript from live bridge pipe")
    p_br_rec.add_argument("--pid", type=int, required=True, help="Power BI Desktop PID")
    p_br_rec.add_argument("--out", help="output directory for transcript (default: tests/fixtures/bridge/<ver>)")
    p_br_rec.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_br_rec.set_defaults(fn=cmd_bridge)

    p_shot = sub.add_parser("screenshot", help="capture page or visual screenshots, or compare before/after images")
    p_shot.add_argument("--pid", type=int, help="running Desktop process id to capture")
    p_shot.add_argument("--page", help="page id or displayName to capture")
    p_shot.add_argument("--all", action="store_true", help="capture all pages")
    p_shot.add_argument("--scale", type=int, default=1, choices=[1, 2, 3], help="rendering scale multiplier (default: 1)")
    p_shot.add_argument("--visual", help="visual title or id to crop from page")
    p_shot.add_argument("--settle", type=float, default=0.5, help="seconds to wait for render settle (default: 0.5)")
    p_shot.add_argument("--out", help="output directory for captured images (default: .agent/out/shots/<ts>/)")
    p_shot.add_argument("--compare", nargs=2, metavar=("A", "B"), help="compare two images: --compare <a.png> <b.png>")
    p_shot.add_argument("--threshold", type=float, default=0.5, help="change ratio threshold for verdict (default: 0.5)")
    p_shot.add_argument("--mask", action="append", help="visual id to mask during compare")
    p_shot.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p_shot.set_defaults(fn=cmd_screenshot)

    p_hand = sub.add_parser("handoff", help="hand the running Desktop instance to this project (--active, --file, or the ribbon's --server/--database)")
    g_hand = p_hand.add_mutually_exclusive_group()
    g_hand.add_argument("--active", action="store_true", help="the Power BI Desktop window on top: the one you clicked last")
    g_hand.add_argument("--file", help="the open document whose file name or title matches, without switching windows")
    p_hand.add_argument("--server", help="Analysis Services localhost:<port> address, as Desktop's ribbon substitutes it")
    p_hand.add_argument("--database", help="Analysis Services database GUID, substituted by the same click")
    p_hand.add_argument("--project", help="explicit project folder to write .agent/desktop.json into")
    p_hand.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_hand.set_defaults(fn=cmd_handoff)

    p_reg = sub.add_parser("register-tool", help="put agentdata on the External Tools ribbon, or package the one file IT must place")
    g_reg = p_reg.add_mutually_exclusive_group()
    g_reg.add_argument("--package", action="store_true", help="write the tool file and REQUEST.md to send to whoever owns Common Files")
    g_reg.add_argument("--te2", action="store_true", help="install the per-user Tabular Editor custom action (no privileged write)")
    p_reg.add_argument("--remove", action="store_true", help="with --te2: take the custom action out again")
    p_reg.add_argument("--out", help="directory for --package (default: .agent/out/external-tool/)")
    p_reg.add_argument("--launcher", help="what the file launches instead of `python` (a venv site's agentdata-handoff.cmd)")
    p_reg.add_argument("--python", help="explicit python executable path (default: sys.executable)")
    p_reg.add_argument("--target-dir", help="custom destination directory for .pbitool.json (testing/mock)")
    p_reg.add_argument("--project", help="explicit project directory to bake into tool arguments")
    p_reg.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_reg.set_defaults(fn=cmd_register_tool)

    p_prb = sub.add_parser("probe", help="read-only report of what this machine offers the handoff (paste it into the issue)")
    p_prb.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_prb.set_defaults(fn=cmd_probe)

    p = sub.add_parser("launch", help="open a .pbip in Power BI Desktop")
    p.add_argument("path"); p.add_argument("--exe")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_launch)
    p = sub.add_parser("visual-query", help="build the visual's DAX (SUMMARIZECOLUMNS) and run it via dscmd")
    p.add_argument("pbip", nargs="?"); p.add_argument("--visual", required=True); p.add_argument("--page"); p.add_argument("--server")
    p.add_argument("--db"); p.add_argument("--dscmd"); p.add_argument("--top", type=int, default=500); p.add_argument("--dry-run", action="store_true")
    p.add_argument("--name")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_visual_query)
    p = sub.add_parser("lint", help="TMDL syntax lint for a definition folder or one .tmdl file")
    p.add_argument("path")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_lint)
    p = sub.add_parser("refs", help="where is a column/measure used; what feeds a visual or page")
    p.add_argument("pbip", nargs="?"); p.add_argument("--table"); p.add_argument("--column"); p.add_argument("--measure"); p.add_argument("--visual"); p.add_argument("--page")
    p.add_argument("--live", action="store_true", help="reconcile against live DISCOVER_CALC_DEPENDENCY from server")
    p.add_argument("--server", help="Analysis Services server for --live")
    p.add_argument("--db", help="database name for --live")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_refs)

    p_dmv = sub.add_parser("dmv", help="run Analysis Services DMV query or shortcut (deps, segments, sessions, schema)")
    p_dmv.add_argument("query", help="DMV SQL query or shortcut name (deps, segments, sessions, schema)")
    p_dmv.add_argument("--server", help="localhost:<port> address")
    p_dmv.add_argument("--db", help="database name")
    p_dmv.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_dmv.set_defaults(fn=cmd_dmv)

    p_cost = sub.add_parser("page-cost", help="navigate to page and benchmark visual query latencies via trace")
    p_cost.add_argument("pbip", nargs="?")
    p_cost.add_argument("--pid", type=int, help="running Desktop process id")
    p_cost.add_argument("--page", required=True, help="page id or displayName to evaluate")
    p_cost.add_argument("--seconds", type=int, default=15, help="trace duration in seconds (default: 15)")
    p_cost.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_cost.set_defaults(fn=cmd_page_cost)

    p_tr = sub.add_parser("trace", help="Analysis Services trace control and aggregation")
    tr_sub = p_tr.add_subparsers(dest="trace_cmd", required=True)
    p_ts = tr_sub.add_parser("start", help="start trace listener and launch TE2 trace script")
    p_ts.add_argument("--pid", type=int, help="running Desktop process id")
    p_ts.add_argument("--server", help="localhost:<port> address")
    p_ts.add_argument("--db", help="database name")
    p_ts.add_argument("--seconds", type=int, default=60, help="duration in seconds (default: 60)")
    p_ts.add_argument("--out", help="output .jsonl file path (default: .agent/out/trace-<ts>.jsonl)")
    p_ts.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ts.set_defaults(fn=cmd_trace)

    p_tr_rep = tr_sub.add_parser("report", help="aggregate and correlate trace .jsonl events to visuals")
    p_tr_rep.add_argument("file", help="path to trace .jsonl file")
    p_tr_rep.add_argument("pbip", nargs="?", help="optional PBIP path to correlate visual names")
    p_tr_rep.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_tr_rep.set_defaults(fn=cmd_trace)
    m = sub.add_parser("measure", help="mechanical measure edits").add_subparsers(dest="mcmd", required=True)
    p = m.add_parser("set", help="add or replace a measure with correct TMDL layout")
    p.add_argument("pbip", nargs="?"); p.add_argument("--table", required=True); p.add_argument("--name", required=True)
    g = p.add_mutually_exclusive_group(required=True); g.add_argument("--expr"); g.add_argument("--expr-file")
    p.add_argument("--format-string"); p.add_argument("--display-folder"); p.add_argument("--description"); p.add_argument("--hidden", action="store_true")
    p.add_argument("--lineage-tag", action="store_true", help="write a new lineageTag (default: none; Desktop assigns on save)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read (same as AGENTDATA_UI=rich)")
    p.set_defaults(fn=cmd_measure_set)

    # Schema
    p_sc = sub.add_parser("schema", help="vendored PBIR JSON schema validation and updates")
    sc_sub = p_sc.add_subparsers(dest="schema_cmd", required=True)
    p_sc_up = sc_sub.add_parser("update", help="validate and refresh vendored schemas against VERSION metadata")
    p_sc_up.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_sc_up.set_defaults(fn=cmd_schema)

    # Catalog
    p_cat = sub.add_parser("catalog", help="schema-driven visual catalog: visual types, roles, and formatting")
    cat_sub = p_cat.add_subparsers(dest="catalog_cmd", required=True)
    p_cl = cat_sub.add_parser("list", help="list available visual types, roles, and deprecation status")
    p_cl.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_cl.set_defaults(fn=cmd_catalog)
    p_cd = cat_sub.add_parser("describe", help="describe roles and cardinality constraints for visual type")
    p_cd.add_argument("type", help="visual type name (e.g. columnChart, cardVisual, tableEx)")
    p_cd.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_cd.set_defaults(fn=cmd_catalog)
    p_cf = cat_sub.add_parser("formatting", help="inspect formatting objects, properties, and enum values")
    p_cf.add_argument("type", nargs="?", help="optional visual type name")
    p_cf.add_argument("--object", help="filter by formatting object name (e.g. title, background)")
    p_cf.add_argument("--property", help="filter by property name (e.g. text, color)")
    p_cf.add_argument("--search", help="search formatting descriptions and names")
    p_cf.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_cf.set_defaults(fn=cmd_catalog)

    # Expr
    p_ex = sub.add_parser("expr", help="QueryExpressionContainer encoding and decoding")
    ex_sub = p_ex.add_subparsers(dest="expr_cmd", required=True)
    p_ee = ex_sub.add_parser("encode", help="encode human field reference into QueryExpressionContainer JSON")
    p_ee.add_argument("text", help="field reference (e.g. 'Sales'[Amount], [Margin], Sum('Sales'[Qty]))")
    p_ee.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ee.set_defaults(fn=cmd_expr)
    p_ed = ex_sub.add_parser("decode", help="decode QueryExpressionContainer JSON into human field reference")
    p_ed.add_argument("json", help="QueryExpressionContainer JSON string")
    p_ed.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ed.set_defaults(fn=cmd_expr)

    # Theme
    p_th = sub.add_parser("theme", help="report theme shading and registration")
    th_sub = p_th.add_subparsers(dest="theme_cmd", required=True)
    p_ts = th_sub.add_parser("shade", help="shade (darken) or tint (lighten) a hex color")
    p_ts.add_argument("--color", required=True, help="hex color (e.g. #1F77B4)")
    p_ts.add_argument("--pct", type=float, required=True, help="percentage to darken (negative) or lighten (positive), e.g. -20")
    p_ts.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ts.set_defaults(fn=cmd_theme)
    p_tset = th_sub.add_parser("set", help="register custom theme in report.json and copy to StaticResources")
    p_tset.add_argument("pbip", nargs="?", help="PBIP root path")
    p_tset.add_argument("--file", required=True, help="path to theme.json file")
    p_tset.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_tset.set_defaults(fn=cmd_theme)

    # Preview
    p_prev = sub.add_parser("preview", help="preview report structure as tabular views")
    prev_sub = p_prev.add_subparsers(dest="preview_cmd", required=True)
    for pslot in ("pages", "visuals", "filters", "themes"):
        pp = prev_sub.add_parser(pslot, help=f"preview report {pslot}")
        pp.add_argument("pbip", nargs="?", help="PBIP root path")
        pp.add_argument("--pretty", action="store_true", help="draw it as a table")
        pp.set_defaults(fn=cmd_preview)

    # Page
    p_pg = sub.add_parser("page", help="mechanical page edits (add, remove, move)")
    pg_sub = p_pg.add_subparsers(dest="page_cmd", required=True)
    p_pa = pg_sub.add_parser("add", help="add new page")
    p_pa.add_argument("pbip", nargs="?", help="PBIP root path")
    p_pa.add_argument("--name", required=True, help="display name of the page")
    p_pa.add_argument("--after", help="insert after this page id or display name")
    p_pa.add_argument("--width", type=int, default=1280, help="canvas width (default: 1280)")
    p_pa.add_argument("--height", type=int, default=720, help="canvas height (default: 720)")
    p_pa.add_argument("--brief", help="path to approved report-spec.md (validates approval and layout contract)")
    p_pa.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_pa.set_defaults(fn=cmd_page)
    p_pr = pg_sub.add_parser("remove", help="remove page")
    p_pr.add_argument("pbip", nargs="?", help="PBIP root path")
    p_pr.add_argument("--page", required=True, help="page id or display name to remove")
    p_pr.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_pr.set_defaults(fn=cmd_page)
    p_pm = pg_sub.add_parser("move", help="reorder page in pages.json")
    p_pm.add_argument("pbip", nargs="?", help="PBIP root path")
    p_pm.add_argument("--page", required=True, help="page id or display name to move")
    p_pm.add_argument("--after", help="place after this page id or display name (default: move to first)")
    p_pm.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_pm.set_defaults(fn=cmd_page)

    # Visual
    p_vis = sub.add_parser("visual", help="mechanical visual edits (add, set, remove)")
    vis_sub = p_vis.add_subparsers(dest="visual_cmd", required=True)
    p_va = vis_sub.add_parser("add", help="add visual with schema validation")
    p_va.add_argument("pbip", nargs="?", help="PBIP root path")
    p_va.add_argument("--page", required=True, help="page id or display name")
    p_va.add_argument("--type", required=True, help="visual type (e.g. columnChart, cardVisual, tableEx)")
    p_va.add_argument("--title", help="visual title text")
    p_va.add_argument("--fields", nargs="+", help="fields in format 'Table'[Column] or [Measure]")
    p_va.add_argument("--position", help="position format x,y,width,height (e.g. 20,20,500,300)")
    p_va.add_argument("--brief", help="path to approved report-spec.md (validates approval and layout contract)")
    p_va.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_va.set_defaults(fn=cmd_visual)
    p_vs = vis_sub.add_parser("set", help="set visual formatting or position property")
    p_vs.add_argument("pbip", nargs="?", help="PBIP root path")
    p_vs.add_argument("--visual", required=True, help="visual id (20-hex)")
    p_vs.add_argument("--property", required=True, help="property in format <object.property>=<value> or position.x=10")
    p_vs.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_vs.set_defaults(fn=cmd_visual)
    p_vr = vis_sub.add_parser("remove", help="remove visual")
    p_vr.add_argument("pbip", nargs="?", help="PBIP root path")
    p_vr.add_argument("--visual", required=True, help="visual id (20-hex) to remove")
    p_vr.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_vr.set_defaults(fn=cmd_visual)

    # Filter
    p_flt = sub.add_parser("filter", help="mechanical filter edits")
    flt_sub = p_flt.add_subparsers(dest="filter_cmd", required=True)
    p_fs = flt_sub.add_parser("set", help="set report, page, or visual level filter")
    p_fs.add_argument("pbip", nargs="?", help="PBIP root path")
    p_fs.add_argument("--scope", required=True, choices=["report", "page", "visual"], help="filter scope")
    p_fs.add_argument("--page", help="page id or display name (for page scope)")
    p_fs.add_argument("--visual", help="visual id (for visual scope)")
    p_fs.add_argument("--field", required=True, help="field reference 'Table'[Column]")
    g_flt = p_fs.add_mutually_exclusive_group(required=True)
    g_flt.add_argument("--values", help="comma-separated values for categorical filter (e.g. 2024,2025)")
    g_flt.add_argument("--between", help="lower,upper bounds for between filter")
    g_flt.add_argument("--top", type=int, help="top count for TopN filter")
    p_fs.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_fs.set_defaults(fn=cmd_filter)

    # Bookmark
    p_bm = sub.add_parser("bookmark", help="mechanical bookmark edits")
    bm_sub = p_bm.add_subparsers(dest="bookmark_cmd", required=True)
    p_ba = bm_sub.add_parser("add", help="create new bookmark")
    p_ba.add_argument("pbip", nargs="?", help="PBIP root path")
    p_ba.add_argument("--name", required=True, help="bookmark display name")
    p_ba.add_argument("--page", required=True, help="active page id or display name")
    p_ba.add_argument("--visuals", help="comma-separated list of visual ids to capture")
    p_ba.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ba.set_defaults(fn=cmd_bookmark)

    # Brief
    p_br = sub.add_parser("brief", help="report specification and design brief validation and approval")
    br_sub = p_br.add_subparsers(dest="brief_cmd", required=True)
    p_bc = br_sub.add_parser("check", help="validate brief layout_contract, space_audit, and model fields")
    p_bc.add_argument("spec", help="path to report-spec.md file")
    p_bc.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_bc.set_defaults(fn=cmd_brief)
    p_ba_app = br_sub.add_parser("approve", help="terminal-only interactive human approval gate")
    p_ba_app.add_argument("spec", help="path to report-spec.md file")
    p_ba_app.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ba_app.set_defaults(fn=cmd_brief)
    p_bs = br_sub.add_parser("status", help="check brief approval status (current, stale, missing)")
    p_bs.add_argument("spec", help="path to report-spec.md file")
    p_bs.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_bs.set_defaults(fn=cmd_brief)

    # Model
    p_mod = sub.add_parser("model", help="semantic model live TOM authoring, audit, and optimization")
    mod_sub = p_mod.add_subparsers(dest="model_cmd", required=True)

    # model apply
    p_ma = mod_sub.add_parser("apply", help="apply declarative op list to live TOM model or TMDL files")
    p_ma.add_argument("--ops", required=True, help="path to ops JSON file or raw JSON string")
    p_ma.add_argument("--server", help="Analysis Services server (localhost:<port>)")
    p_ma.add_argument("--pid", type=int, help="Power BI Desktop PID")
    p_ma.add_argument("--db", help="database name")
    p_ma.add_argument("--model", help="path to SemanticModel definition folder (Tier 2 fallback)")
    p_ma.add_argument("--pbip", help="PBIP root folder (for settle wait on --save)")
    p_ma.add_argument("--save", action="store_true", help="trigger Desktop save via UIA/Ctrl+S after apply")
    p_ma.add_argument("--dry-run", action="store_true", help="validate without writing changes")
    p_ma.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_ma.set_defaults(fn=cmd_model)

    # model audit
    p_mau = mod_sub.add_parser("audit", help="audit semantic model for best practices and anti-patterns")
    p_mau.add_argument("definition", nargs="?", help="path to SemanticModel definition folder or PBIP")
    p_mau.add_argument("--server", help="Analysis Services server (localhost:<port>)")
    p_mau.add_argument("--pid", type=int, help="Power BI Desktop PID")
    p_mau.add_argument("--db", help="database name")
    p_mau.add_argument("--bpa", action="store_true", help="include Tabular Editor BPA rules")
    p_mau.add_argument("--copilot", action="store_true", help="evaluate Copilot AI readiness scored checklist")
    p_mau.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_mau.set_defaults(fn=cmd_model)

    # model optimize
    p_mo = mod_sub.add_parser("optimize", help="optimize slow DAX measure with before/after trace evidence")
    p_mo.add_argument("--measure", required=True, help="measure name to optimize")
    p_mo.add_argument("--server", help="Analysis Services server (localhost:<port>)")
    p_mo.add_argument("--pid", type=int, help="Power BI Desktop PID")
    p_mo.add_argument("--db", help="database name")
    p_mo.add_argument("--pbip", help="PBIP root folder")
    p_mo.add_argument("--pretty", action="store_true", help="draw it as a table")
    p_mo.set_defaults(fn=cmd_model)
    return ap


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = build_parser()
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    if getattr(a, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()
    try:
        sys.exit(a.fn(a))
    except (FileNotFoundError, ValueError) as e:
        print(error(str(e)[:300], "pass the folder that contains the .pbip (or set pbip_path in AGENTS.md)", "ad-pbip")); sys.exit(2)
    except C.ConfigError as e:
        print(error(str(e), e.hint, "ad-pbip")); sys.exit(2)


if __name__ == "__main__":
    main()
