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
import platform
import re
import shutil
import sys
import time

from . import completion
from . import config as C
from . import proc
from . import toon
from .console import utf8_stdout
from . import ui
from . import shell as SH
from .install import REPO_URL, editable_cmd, source_checkout
from . import textio

SKILL_SPEC = "agentchieflou/this-next-please"
SKILLS_CMD = ["gh", "skill", "install", SKILL_SPEC, "--all", "--scope", "user"]
SKILL_DIRS = ("~/.copilot/skills", "~/.config/copilot/skills", "~/.claude/skills")
STALE_DAYS = 1.0
TAIL_LINES = 15
# `gh skill install` exits 1 when any skill already exists and names them on one line
ALREADY_INSTALLED = re.compile(r"skills? already installed:\s*(.+)", re.I)


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
            "editable": editable or bool(checkout), "kind": kind, "checkout_dir": textio.norm_path(checkout or ""),
            "path": textio.norm_path(pkg), "installed": _stamp(os.path.join(pkg, "__init__.py")),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
                      f" ({textio.norm_path(sys.executable)})"}


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
    return {"dir": textio.norm_path(d), "installed": len(files), "newest": _stamp(newest_file) if newest_file else "",
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
        return f'git -C "{textio.norm_path(root)}" pull && {editable_cmd()}'
    spec = f"agentdata{f'[{extras}]' if extras else ''} @ git+{REPO_URL}"
    tail = "" if extras else " --no-deps"
    return f'python -m pip install --force-reinstall{tail} "{spec}"'


# ------------------------------------------------------- where this ran, and what is installed


def launcher_kind(argv0: str | None = None) -> str:
    """`exe` when started through Scripts\\ad-update.exe, `cmd` through a shim, else `module`."""
    name = os.path.basename(argv0 if argv0 is not None else (sys.argv[0] or "")).lower()
    if name.endswith(".exe"):
        return "exe"
    if name.endswith((".cmd", ".bat")):
        return "cmd"
    return "module"


def reexec_argv(argv: list[str]) -> list[str]:
    return [sys.executable, "-m", "agentdata", "update", *argv]


def installed_distributions() -> list[dict]:
    """Every `agentdata` on this interpreter's path.

    Two of them is the shadowing failure: a --user copy in %APPDATA%\\Python that wins over the
    all-users one under Program Files, so a successful-looking update changes nothing.
    """
    out: list[dict] = []
    try:
        from importlib.metadata import distributions
        for dist in distributions():
            if (dist.metadata["Name"] or "").lower() != "agentdata":
                continue
            location = ""
            try:
                location = textio.norm_path(str(dist.locate_file("")))
            except Exception:  # noqa: BLE001
                pass
            out.append({"name": "agentdata", "version": dist.version, "location": location})
    except Exception:  # noqa: BLE001
        return out
    return sorted(out, key=lambda d: d["location"])


_VER_IN_PATH = re.compile(r"python[/\\ ]?(\d)[.\\/]?(\d{1,2})\b", re.I)


def _version_from_path(path: str) -> tuple[str, str]:
    """(version, how). Never launches the interpreter: `--check` is a dry run and a test enforces it.

    The exact version is only known for the interpreter we are already inside; for the others the
    directory name (`C:/Python311/python.exe`, `/usr/bin/python3.11`) is what a user reads anyway,
    and it answers the question that matters -- is something older sitting earlier on PATH.
    """
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(sys.executable)):
        return platform.python_version(), "running"
    m = _VER_IN_PATH.search(textio.norm_path(path))
    return (f"{m.group(1)}.{m.group(2)}", "from the path") if m else ("", "unknown")


def pythons_on_path() -> list[dict]:
    """Every `python` a shell would find. An older one earlier on PATH is why an install can
    succeed and the `ad-*` commands still resolve to the old copy."""
    names = ("python.exe", "python3.exe") if os.name == "nt" else ("python3", "python")
    paths: list[str] = []
    for name in names:
        found = shutil.which(name)
        if found and found not in paths:
            paths.append(found)
    pattern = "python*.exe" if os.name == "nt" else "python3*"
    for extra in sorted(glob.glob(os.path.join(os.path.dirname(sys.executable), pattern))):
        if os.path.isfile(extra) and extra not in paths:
            paths.append(extra)
    if sys.executable and sys.executable not in paths:
        paths.insert(0, sys.executable)

    seen: list[dict] = []
    for path in paths:
        ver, how = _version_from_path(path)
        try:
            too_old = bool(ver) and tuple(int(x) for x in ver.split(".")[:2]) < (3, 12)
        except ValueError:
            too_old = False
        seen.append({"path": textio.norm_path(path), "version": ver, "version_from": how, "too_old": too_old})
    return seen


def environment() -> dict:
    """Shell and console facts, so a pasted failure says where it ran.

    The failure this slice fixes cost a round trip because the report did not say which shell it
    came from -- and the answer turned out to be "both", which is itself the diagnosis.
    """
    detected = SH.detect()
    label = detected
    if detected == "bash" and os.environ.get("MSYSTEM"):
        label = f"bash (MSYSTEM={os.environ['MSYSTEM']})"
    elif detected == "windows-powershell":
        label = "windows-powershell 5.1 (unsupported)"

    code_page = ""
    if os.name == "nt":
        try:
            import ctypes
            code_page = str(ctypes.windll.kernel32.GetConsoleOutputCP())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            code_page = ""

    env = {
        "shell": label,
        "host": (os.environ.get("TERM_PROGRAM") or ("Windows Terminal" if os.environ.get("WT_SESSION") else "")
                 or os.environ.get("TERMINAL_EMULATOR") or ""),
        "launcher": launcher_kind(),
        "stdin_tty": sys.stdin.isatty() if sys.stdin else False,
        "stdout_tty": sys.stdout.isatty() if sys.stdout else False,
        "stderr_tty": sys.stderr.isatty() if sys.stderr else False,
        "code_page": code_page,
        "encoding": (sys.stdout.encoding or "").lower(),
    }
    if detected == "windows-powershell":
        env["shell_hint"] = SH.SWITCH_HINT
    return env


# ----------------------------------------------------------------------- the skills half, idempotent


def parse_already_installed(text: str) -> list[str]:
    m = ALREADY_INSTALLED.search(text or "")
    if not m:
        return []
    names = [n.strip().rstrip(".") for n in m.group(1).replace("...", ",").split(",")]
    return [n for n in names if n and n != "..." and "/" not in n and "\\" not in n]


def owned_by_us(folder: str) -> bool:
    """True only when the folder is one of ours: a SKILL.md whose frontmatter name is the folder.

    A foreign skill that happens to share a name must survive; deleting someone else's work to make
    our own install idempotent would be a far worse bug than the one being fixed.
    """
    path = os.path.join(folder, "SKILL.md")
    if not os.path.isfile(path):
        return False
    try:
        text = textio.read_text(path)
    except Exception:  # noqa: BLE001
        return False
    m = re.search(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return False
    name = re.search(r"(?m)^name:\s*[\"']?([\w\-]+)", m.group(1))
    return bool(name) and name.group(1) == os.path.basename(folder.rstrip("/\\"))


def supports_force(run=proc.run) -> bool:
    try:
        rc, out, err, _el = run(["gh", "skill", "install", "--help"], timeout=30)
    except Exception:  # noqa: BLE001
        return False
    return "--force" in f"{out}{err}" if rc == 0 else False


def remove_our_skills(directory: str, names: list[str]) -> list[str]:
    removed = []
    for name in names:
        folder = os.path.join(directory, name)
        if os.path.isdir(folder) and owned_by_us(folder):
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(name)
    return removed


def tail_lines(out: str, err: str, limit: int = TAIL_LINES) -> str:
    """The last `limit` non-empty lines of both streams, stderr first.

    The old version kept the last line of stdout *or*, only if stdout was empty, of stderr. pip
    prints its uninstall banner to stdout and the actual error to stderr, so on the failure that
    started this issue the report said `Uninstalling agentdata-0.5.3:` and threw the reason away.
    """
    e = [ln.rstrip() for ln in (err or "").splitlines() if ln.strip()]
    o = [ln.rstrip() for ln in (out or "").splitlines() if ln.strip()]
    return "\n".join((e + o)[-limit:])


def diagnose(rc: int, out: str, err: str) -> str:
    """A specific hint for a known failure signature, or "" when we have not seen this one.

    Every entry here is a failure someone actually hit. An unrecognised failure gets the last
    lines verbatim rather than a guess.
    """
    text = f"{err or ''}\n{out or ''}"
    low = text.lower()

    if "requires a different python" in low or "requires-python" in low:
        return (f"this `python` is {platform.python_version()} at {sys.executable}; agentdata 0.6+ needs 3.12 "
                f"or newer -- run the install with the newer interpreter (`py -3.14 -m agentdata update`, "
                f"or its full path)")
    if "winerror 32" in low or ("uninstalling" in low and "in use" in low) or "being used by another process" in low:
        return ("the `ad-update.exe` launcher is locked by this very run: use `python -m agentdata update`. "
                "`ad-update` re-execs itself that way now, so this should not recur")
    if "winerror 5" in low or "access is denied" in low or "permission denied" in low:
        return (f"the CLI is installed for all users under {sys.prefix}; run this from an elevated shell, or "
                f"reinstall once with `--user` and let `ad-update` manage that copy")
    if "defaulting to user installation" in low:
        return ("pip fell back to a --user install, which shadows the all-users copy: `ad-update --check` lists "
                "both, and the one to uninstall")
    if "already installed" in low:
        return "some skills are already installed; ad-update removes only its own copies and retries"
    for needle in ("proxy", "sslerror", "certificate verify failed", "tlsv1", "max retries exceeded"):
        if needle in low:
            return ("network or TLS: set HTTPS_PROXY / REQUESTS_CA_BUNDLE for this shell, or run the pip line "
                    "yourself to see the handshake")
    return ""


def _run(name: str, argv: list[str], rows: list[dict], timeout: int) -> bool:
    try:
        rc, out, err, el = proc.run(argv, timeout=timeout, progress=f"Updating {name}...")
    except proc.ProcError as e:
        rows.append({"part": name, "ok": False, "detail": e.msg, "hint": e.hint})
        return False
    if rc == 0:
        last = [ln for ln in (out or "").strip().splitlines() if ln.strip()][-1:]
        rows.append({"part": name, "ok": True, "detail": (last[0][:160] if last else "ok"), "hint": ""})
        return True

    detail = tail_lines(out, err)
    hint = diagnose(rc, out, err)
    rows.append({
        "part": name, "ok": False, "detail": detail or f"exit {rc}",
        "hint": hint or f"run it yourself to see the whole output (exit {rc}, {round(el, 1)}s)",
        "exit_code": rc, "seconds": round(el, 1),
    })
    return False


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
    from . import version
    version.add_version(ap)
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
    ap.add_argument("--no-reexec", action="store_true",
                    help="do not re-exec through `python -m` when started as ad-update.exe (for tests)")
    completion.autocomplete(ap)
    a = ap.parse_args(argv)

    # pip cannot replace the Scripts\ad-update.exe launcher while that launcher is the running
    # process, so a self-update started that way fails with WinError 32. The module form holds
    # nothing open: re-exec through it and hand back its exit code.
    if not a.check and not a.no_reexec and launcher_kind() in ("exe", "cmd") and argv is None:
        import subprocess
        cmd = reexec_argv(sys.argv[1:])
        print(toon.encode({"meta": {"ok": True, "source": "ad-update", "launcher": "exe → module",
                                    "note": "re-executed through `python -m agentdata update`; the .exe launcher "
                                            "cannot replace itself", "cmd": " ".join(cmd)}}))
        return subprocess.run(cmd).returncode

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
        dists, pythons = installed_distributions(), pythons_on_path()
        meta.update(environment())
        meta["shadowed"] = len(dists) > 1
        meta["hint"] = ("skills look older than the CLI: run the skills command below, then start a new Copilot chat"
                        if meta["stale_skills"] else "run `ad-update` to apply both commands, then `ad-doctor`")
        if meta["shadowed"]:
            keep = next((d for d in dists if d["location"] and d["location"] in textio.norm_path(sys.executable)), None)
            meta["hint"] = ("two agentdata installs are on this path and the first one wins: uninstall the one you "
                            "are not using (`python -m pip uninstall agentdata`, once per copy) then re-run "
                            "`ad-update`" + (f"; this interpreter loads {keep['location']}" if keep else ""))
        too_old = [p for p in pythons if p.get("too_old")]
        if too_old:
            meta["hint"] = (f"{too_old[0]['path']} is Python {too_old[0]['version']}, below the 3.12 floor, and is on "
                            f"PATH: run the install with a 3.12+ interpreter or the `ad-*` commands will keep "
                            f"resolving to the old one")
        _report(meta, [], cmds, {"meta": meta, "commands": cmds, "installed_skills": skills["names"],
                                 "installs": dists, "pythons": pythons}, True)
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
        if not rows[-1]["ok"]:
            # "already installed" is not a failure, it is this command being run twice. Remove only
            # the copies we recognise as ours and try once more.
            already = parse_already_installed(rows[-1]["detail"])
            if already:
                removed = remove_our_skills(skills["dir"], already)
                skipped_foreign = [n for n in already if n not in removed]
                rows.pop()
                cmd = SKILLS_CMD + ["--force"] if supports_force() else SKILLS_CMD
                retry_ok = _run("skills", cmd, rows, a.timeout)
                ok &= retry_ok
                rows[-1]["reinstalled"] = ", ".join(removed)
                if skipped_foreign:
                    rows[-1]["hint"] = ((rows[-1].get("hint") or "") +
                                        f" · left alone (not ours): {', '.join(skipped_foreign)}").strip(" ·")
            elif not rows[-1]["hint"]:
                rows[-1]["hint"] = "install GitHub CLI (gh), or copy this repo's skills/ into " + skills["dir"]
    after, skills_after = cli_state(), skills_state(a.skills_dir)
    if skipped:
        meta["skipped"] = skipped
    meta.update({"ok": ok, "version": after["version"], "commit": after["commit"] or unknown,
                 "changed": after["commit"] != before["commit"] or after["installed"] != before["installed"],
                 "skills": skills_after["installed"], "skills_newest": skills_after["newest"],
                 "next": "restart your terminal's Python if a command still misbehaves, then start a NEW Copilot chat so the skills reload; verify with `ad-doctor`"})
    if not ok:
        # a pasted failure has to say where it ran: this one turned out to fail identically in
        # pwsh and Git Bash, which is itself the diagnosis
        meta.update(environment())
        meta["hint"] = "one part did not update; the rows say which. Run its command yourself: " + \
                       (cmds["cli"] if any(r["part"] == "cli" and not r["ok"] for r in rows) else cmds["skills"])
    elif skipped:
        meta["hint"] = ("the skills were updated; the CLI half was left alone because you are running a checkout "
                        "(that is what `commit: checkout` means). `--pull`, `--from-git`, or update it yourself.")
    _report(meta, rows, cmds, {"meta": meta, "parts": rows, "commands": cmds}, not ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
