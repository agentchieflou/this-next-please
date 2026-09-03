# PYTHON_ARGCOMPLETE_OK
"""ad-update: pick up a new version of this repo — the CLI and the skills — and prove which commit you are on.

Two things are installed per laptop and they update separately, which is the whole reason this command exists:
the `ad-*` CLI (pip, from git) and the skills (`gh skill install`, into ~/.copilot/skills). Updating one and not the
other leaves a skill telling the model to run a command the CLI does not have yet.

pip will not reinstall a git URL whose version has not changed, so the update uses `--force-reinstall --no-deps`:
force because the version often stays the same between commits, no-deps so a laptop behind a proxy does not
re-download teradatasql and friends on every update.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import time

from . import completion
from . import config as C
from . import proc
from . import toon
from .console import utf8_stdout
from . import ui
from .install import REPO_URL, editable_cmd, source_checkout

SKILL_SPEC = "agentchieflou/this-next-please"
SKILLS_CMD = ["gh", "skill", "install", SKILL_SPEC, "--all", "--scope", "user"]
SKILL_DIRS = ("~/.copilot/skills", "~/.config/copilot/skills", "~/.claude/skills")
STALE_DAYS = 1.0


def version() -> str:
    try:
        from importlib.metadata import version as _v
        return _v("agentdata")
    except Exception:  # noqa: BLE001
        return "unknown"


def direct_url() -> dict:
    """What pip recorded about where this copy came from: the git URL and the exact commit, or an editable dir."""
    try:
        from importlib.metadata import distribution
        raw = distribution("agentdata").read_text("direct_url.json")
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def cli_state() -> dict:
    import agentdata
    pkg = os.path.dirname(os.path.abspath(agentdata.__file__))
    du = direct_url()
    vcs = du.get("vcs_info") or {}
    checkout = source_checkout()
    editable = bool((du.get("dir_info") or {}).get("editable"))
    kind = ("editable install" if editable else "running from a checkout" if checkout
            else "git install" if vcs else "installed")
    return {"version": version(), "commit": (vcs.get("commit_id") or "")[:12], "source": du.get("url") or "",
            "editable": editable or bool(checkout), "kind": kind, "checkout_dir": (checkout or "").replace("\\", "/"),
            "path": pkg.replace("\\", "/"), "installed": _stamp(os.path.join(pkg, "__init__.py")),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} ({sys.executable})".replace("\\", "/")}


def _stamp(path: str) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
    except OSError:
        return ""


def skills_dir(explicit: str | None = None) -> str:
    if explicit:
        return C.expand(explicit)
    fact = C.project_facts().get("skills_dir")
    if fact and os.path.isdir(C.expand(fact)):
        return C.expand(fact)
    for d in SKILL_DIRS:
        if os.path.isdir(C.expand(d)):
            return C.expand(d)
    return C.expand(fact or SKILL_DIRS[0])


def skills_state(explicit: str | None = None) -> dict:
    d = skills_dir(explicit)
    files = sorted(glob.glob(os.path.join(d, "*", "SKILL.md")))
    newest_file = max(files, key=os.path.getmtime) if files else ""
    return {"dir": d.replace("\\", "/"), "installed": len(files), "newest": _stamp(newest_file) if newest_file else "",
            "newest_epoch": os.path.getmtime(newest_file) if newest_file else 0.0,
            "names": sorted(os.path.basename(os.path.dirname(f)) for f in files)}


def stale(skills: dict) -> bool:
    """Skills older than the CLI by more than a day: the usual half-update (pip run, gh skill install forgotten)."""
    import agentdata
    pkg_time = os.path.getmtime(os.path.join(os.path.dirname(os.path.abspath(agentdata.__file__)), "__init__.py"))
    return bool(skills["installed"]) and (pkg_time - skills["newest_epoch"]) > STALE_DAYS * 86400


def cli_command() -> list[str]:
    return [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", f"agentdata @ git+{REPO_URL}"]


def cli_command_text(extras: str | None = None) -> str:
    root = source_checkout()
    if root:
        return f'git -C "{root.replace(os.sep, "/")}" pull && {editable_cmd()}'
    spec = f"agentdata{f'[{extras}]' if extras else ''} @ git+{REPO_URL}"
    tail = "" if extras else " --no-deps"
    return f'python -m pip install --force-reinstall{tail} "{spec}"'


def _run(name: str, argv: list[str], rows: list[dict], timeout: int) -> bool:
    try:
        rc, out, err, el = proc.run(argv, timeout=timeout)
    except proc.ProcError as e:
        rows.append({"part": name, "ok": False, "detail": e.msg, "hint": e.hint})
        return False
    tail = [ln for ln in (out or "").strip().splitlines() if ln.strip()][-1:] or \
           [ln for ln in (err or "").strip().splitlines() if ln.strip()][-1:]
    rows.append({"part": name, "ok": rc == 0, "detail": (tail[0][:160] if tail else f"exit {rc}"),
                 "hint": "" if rc == 0 else f"run it yourself to see the whole output (exit {rc}, {round(el, 1)}s)"})
    return rc == 0


def _report(meta: dict, rows: list[dict], cmds: dict, payload: dict, show_commands: bool) -> None:
    """TOON for whoever is parsing, a panel and a table for whoever is reading -- one or the other, never both.
    `AGENTDATA_UI=plain` gives the TOON on a terminal, for pasting into a friction log."""
    if not ui.on():
        print(toon.encode(payload))
        return
    ui.facts([("status", ui.status_text("ok" if meta["ok"] else "fail")), ("version", meta["version"]),
              ("commit", meta["commit"]), ("install", meta["install"]), ("python", meta["python"]),
              ("skills", f"{meta['skills']} in {meta['skills_dir']}"),
              ("newest", meta.get("skills_newest") or ""), ("skipped", ", ".join(meta.get("skipped") or []))],
             title="ad-update")
    if rows:
        ui.table(["part", "status", "detail", "hint"],
                 [[r["part"], "ok" if r["ok"] else "fail", r.get("detail") or "", r.get("hint") or ""] for r in rows],
                 status_col=1, wrap=(2, 3), group_col=0)
    if show_commands:
        ui.table(["", "command"], [[k, v] for k, v in cmds.items()], title="what it runs", wrap=(1,), group_col=0)
    if meta.get("hint"):
        ui.note(str(meta["hint"]), style="hint")
    if meta.get("next"):
        ui.note(str(meta["next"]), style="muted")


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(prog="ad-update", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", "--dry-run", action="store_true", dest="check",
                    help="report what is installed and print the commands; run nothing")
    ap.add_argument("--cli", action="store_true", help="update only the ad-* CLI")
    ap.add_argument("--skills", action="store_true", help="update only the skills")
    ap.add_argument("--extras", help="extras to (re)install with the CLI, e.g. teradata,odbc,pbi")
    ap.add_argument("--pull", action="store_true",
                    help="in a checkout: `git pull --ff-only` there instead of skipping the CLI half")
    ap.add_argument("--from-git", action="store_true", dest="from_git",
                    help="replace a checkout / editable install with the published git install")
    ap.add_argument("--skills-dir", help="where the skills live (default: skills_dir fact, else ~/.copilot/skills)")
    ap.add_argument("--timeout", type=int, default=600)
    completion.autocomplete(ap)
    a = ap.parse_args(argv)
    both = not (a.cli or a.skills)
    before, skills = cli_state(), skills_state(a.skills_dir)
    unknown = "checkout" if before["editable"] else "n/a"     # same wording ad-doctor prints, so the two agree
    meta = {"ok": True, "source": "ad-update", "version": before["version"], "commit": before["commit"] or unknown,
            "install": before["kind"] + (f" at {before['checkout_dir']}" if before["checkout_dir"] else ""),
            "editable": before["editable"], "cli_installed": before["installed"], "skills_dir": skills["dir"],
            "skills": skills["installed"], "skills_newest": skills["newest"], "python": before["python"]}
    cmds = {"cli": cli_command_text(a.extras), "skills": " ".join(SKILLS_CMD)}

    if a.check:
        meta["stale_skills"] = stale(skills)
        meta["hint"] = ("skills look older than the CLI: run the skills command below, then start a new Copilot chat"
                        if meta["stale_skills"] else "run `ad-update` to apply both commands, then `ad-doctor`")
        _report(meta, [], cmds, {"meta": meta, "commands": cmds, "installed_skills": skills["names"]}, True)
        return 0

    rows: list[dict] = []
    ok = True
    skipped: list[str] = []
    from_checkout = before["editable"] and not a.from_git
    if both or a.cli:
        if from_checkout and a.pull and before["checkout_dir"]:
            ok &= _run("cli", ["git", "-C", before["checkout_dir"], "pull", "--ff-only"], rows, a.timeout)
        elif from_checkout:
            # a deliberate skip, not a failure: pip must not fight a checkout you are editing
            skipped.append("cli")
            rows.append({"part": "cli", "ok": True, "detail": f"skipped: {before['kind']}"
                         + (f" at {before['checkout_dir']}" if before["checkout_dir"] else ""),
                         "hint": f"{cmds['cli']} · or `ad-update --pull` · or `ad-update --from-git` to switch to the published install"})
        else:
            ok &= _run("cli", cli_command() if not a.extras else
                       [sys.executable, "-m", "pip", "install", "--force-reinstall", f"agentdata[{a.extras}] @ git+{REPO_URL}"],
                       rows, a.timeout)
    if both or a.skills:
        ok &= _run("skills", SKILLS_CMD, rows, a.timeout)
        if not rows[-1]["ok"] and not rows[-1]["hint"]:
            rows[-1]["hint"] = "install GitHub CLI (gh), or copy this repo's skills/ into " + skills["dir"]
    after, skills_after = cli_state(), skills_state(a.skills_dir)
    if skipped:
        meta["skipped"] = skipped
    meta.update({"ok": ok, "version": after["version"], "commit": after["commit"] or unknown,
                 "changed": after["commit"] != before["commit"] or after["installed"] != before["installed"],
                 "skills": skills_after["installed"], "skills_newest": skills_after["newest"],
                 "next": "restart your terminal's Python if a command still misbehaves, then start a NEW Copilot chat so the skills reload; verify with `ad-doctor`"})
    if not ok:
        meta["hint"] = "one part did not update; the rows say which. Run its command yourself: " + \
                       (cmds["cli"] if any(r["part"] == "cli" and not r["ok"] for r in rows) else cmds["skills"])
    elif skipped:
        meta["hint"] = ("the skills were updated; the CLI half was left alone because you are running a checkout "
                        "(that is what `commit: checkout` means). `--pull`, `--from-git`, or update it yourself.")
    _report(meta, rows, cmds, {"meta": meta, "parts": rows, "commands": cmds}, not ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
