# PYTHON_ARGCOMPLETE_OK
"""ad-theme: list · show · gallery · apply · reset · set · unset · install · uninstall.

CLI theming: the terminal a human opens tells them where they are.
Pure TOON on stdout when piped, zero escape bytes for agents, status colours never move.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import color
from . import completion
from . import config
from . import console
from . import policy
from . import textio
from . import theme
from . import toon
from . import ui

THEME_COLS = ("name", "title", "ground", "accent", "light", "why")


def is_in_schedule(sched: dict, when: Any = None) -> bool:
    """Check if current time falls within scheduled after-until window."""
    if not sched or not isinstance(sched, dict):
        return False
    after = sched.get("after", "")
    until = sched.get("until", "")
    if not after or not until:
        return False
    import time
    now_tm = when or time.localtime()
    now_str = f"{now_tm.tm_hour:02d}:{now_tm.tm_min:02d}"
    if after <= until:
        return after <= now_str < until
    return now_str >= after or now_str < until


def _resolve_cwd_theme() -> tuple[str, str]:
    """Find the theme for current directory from config.json. Returns (theme_name, reason)."""
    cfg = config.load()
    cwd = os.path.abspath(os.getcwd())

    # Check schedule first
    sched = config.get(cfg, "theme.schedule", {})
    if is_in_schedule(sched):
        sched_theme = sched.get("theme", "greens")
        until = sched.get("until", "07:00")
        return str(sched_theme), f"'{sched_theme}' by schedule until {until}"

    # Check project-specific mappings
    projects = config.get(cfg, "theme.projects", {})
    if isinstance(projects, dict):
        # By directory path prefix or folder name
        for key, val in projects.items():
            if os.path.exists(key) and os.path.abspath(key) == cwd:
                return str(val), f"project mapping for '{key}'"
            if os.path.basename(cwd).lower() == key.lower():
                return str(val), f"project name match for '{key}'"

    # Default theme
    default = config.get(cfg, "theme.default", "none")
    return str(default), "configured default"


def cmd_list(a) -> int:
    """List available themes in TOON format."""
    themes = theme.list_themes()
    rows = []
    for t in themes:
        rows.append([
            t.name,
            t.title,
            t.ground or "",
            t.accent or "",
            "true" if t.light else "false",
            t.why
        ])

    if policy.pretty():
        ui.table(list(THEME_COLS), rows, title="Themes", status_col=0)
    else:
        # Piped: 100% clean TOON, no ANSI escapes
        print(toon.table("themes", list(THEME_COLS), rows))
    return 0


def cmd_show(a) -> int:
    """Show theme details or active theme for current directory."""
    if a.cwd or not a.name:
        name, reason = _resolve_cwd_theme()
    else:
        name = a.name
        reason = "requested by name"

    try:
        t = theme.get(name)
    except theme.ThemeError as e:
        print(f"error: {e} ({e.hint})", file=sys.stderr)
        return 1

    meta = {
        "name": t.name,
        "title": t.title,
        "why": t.why,
        "ground": t.ground or "",
        "text": t.text or "",
        "accent": t.accent or "",
        "light": "true" if t.light else "false",
        "reason": reason,
    }

    status_rows = [[k, v] for k, v in sorted(t.status.items())]

    if policy.pretty():
        ui.facts([(k, v) for k, v in meta.items()], title=f"Theme: {t.title}")
        if status_rows:
            ui.table(["role", "hex"], status_rows, title="Status Mapping")
    else:
        print(toon.encode({"theme": meta}))
        if status_rows:
            print(toon.table("status", ["role", "hex"], status_rows))
    return 0


def cmd_gallery(a) -> int:
    """Gallery: colored swatch on TTY, names only when piped."""
    themes = theme.list_themes()
    if not color.enabled():
        # Clean plain names when piped (contract requirement)
        for t in themes:
            print(t.name)
        return 0

    # On interactive TTY, show rich / ANSI preview
    print("\n--- CLI Theme Gallery ---\n")
    for t in themes:
        if t.ground and t.text:
            # Render using 24-bit truecolor or ANSI
            r_g, g_g, b_g = [int(x * 255) for x in theme.hex_to_rgb(t.ground)]
            r_t, g_t, b_t = [int(x * 255) for x in theme.hex_to_rgb(t.text)]
            r_a, g_a, b_a = [int(x * 255) for x in theme.hex_to_rgb(t.accent or t.text)]
            
            esc_bg = f"\x1b[48;2;{r_g};{g_g};{b_g}m"
            esc_fg = f"\x1b[38;2;{r_t};{g_t};{b_t}m"
            esc_acc = f"\x1b[38;2;{r_a};{g_a};{b_a}m"
            reset = "\x1b[0m"

            status_sample = " ".join(
                f"\x1b[38;2;{int(theme.hex_to_rgb(col)[0]*255)};{int(theme.hex_to_rgb(col)[1]*255)};{int(theme.hex_to_rgb(col)[2]*255)}m{ui.GLYPHS.get(role, '')} {role}{reset}{esc_bg}"
                for role, col in (("ok", t.status.get("ok", "#3FB950")),
                                  ("warn", t.status.get("warn", "#D29922")),
                                  ("fail", t.status.get("fail", "#F85149")))
            )

            print(f"{esc_bg}{esc_acc} {t.name:<16} {reset}{esc_bg}{esc_fg} {t.why:<55} {status_sample} {reset}")
        else:
            print(f" {t.name:<16}  {t.why}")
    print()
    return 0


def cmd_apply(a) -> int:
    """Recolour the current terminal."""
    if a.name:
        name = a.name
    else:
        name, _ = _resolve_cwd_theme()

    if not color.enabled():
        # Pipe/machine context: emit no escapes, report mechanism none
        print(toon.encode({"meta": {"ok": True, "theme": name, "mechanism": "none"}}))
        return 0

    try:
        t = theme.get(name)
    except theme.ThemeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    host = console.host()
    if host == "conhost":
        res = theme.apply_conhost(t, persist=getattr(a, "persist", False))
        print(toon.encode({"meta": {"ok": res.get("ok", True), "theme": name, "mechanism": "conhost-api"}}))
        return 0

    # For terminals with VT/OSC support
    seq = theme.escapes(t)
    if seq:
        sys.stdout.write(seq)
        sys.stdout.flush()

    print(toon.encode({"meta": {"ok": True, "theme": name, "mechanism": f"osc-{host}"}}))
    return 0


def cmd_reset(a) -> int:
    """Reset terminal colours."""
    if not color.enabled():
        print(toon.encode({"meta": {"ok": True, "action": "reset", "mechanism": "none"}}))
        return 0

    host = console.host()
    if host == "conhost":
        t = theme.NONE
        theme.apply_conhost(t)
    else:
        sys.stdout.write(theme.reset_escapes())
        sys.stdout.flush()

    print(toon.encode({"meta": {"ok": True, "action": "reset", "mechanism": f"reset-{host}"}}))
    return 0


def cmd_set(a) -> int:
    """Save theme configuration in ~/.agentdata/config.json."""
    cfg = config.load()
    target_desc = ""

    if getattr(a, "transient", None):
        val = (a.transient.lower() == "on")
        cfg.setdefault("theme", {})["transient_prompt"] = val
        target_desc = f"transient_prompt={val}"

    if getattr(a, "after", None) or getattr(a, "until", None):
        if not getattr(a, "name", None):
            print("error: --after / --until requires a theme name", file=sys.stderr)
            return 1
        try:
            t = theme.get(a.name)
        except theme.ThemeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        sched = {
            "theme": t.name,
            "after": a.after or "18:00",
            "until": a.until or "07:00",
        }
        cfg.setdefault("theme", {})["schedule"] = sched
        target_desc = f"schedule '{t.name}' (after {sched['after']} until {sched['until']})"
        config.save(cfg)
        try:
            theme_project.write_hooks()
        except Exception:
            pass
        print(toon.encode({"meta": {"ok": True, "set": t.name, "target": target_desc}}))
        return 0

    if not getattr(a, "name", None):
        if target_desc:
            config.save(cfg)
            print(toon.encode({"meta": {"ok": True, "target": target_desc}}))
            return 0
        print("error: theme name required", file=sys.stderr)
        return 1

    try:
        t = theme.get(a.name)
    except theme.ThemeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if a.project:
        proj_key = os.path.abspath(a.project) if os.path.isdir(a.project) else a.project
        projects = config.get(cfg, "theme.projects", {})
        if not isinstance(projects, dict):
            projects = {}
        projects[proj_key] = t.name
        cfg.setdefault("theme", {})["projects"] = projects
        target_desc = f"project '{proj_key}'"
    else:
        cfg.setdefault("theme", {})["default"] = t.name
        target_desc = "default"

    config.save(cfg)
    try:
        theme_project.write_hooks()
    except Exception:
        pass
    print(toon.encode({"meta": {"ok": True, "set": t.name, "target": target_desc}}))
    return 0


def cmd_unset(a) -> int:
    """Unset theme configuration."""
    cfg = config.load()
    if a.project:
        proj_key = os.path.abspath(a.project) if os.path.isdir(a.project) else a.project
        projects = config.get(cfg, "theme.projects", {})
        if isinstance(projects, dict) and proj_key in projects:
            del projects[proj_key]
            cfg.setdefault("theme", {})["projects"] = projects
            config.save(cfg)
            print(toon.encode({"meta": {"ok": True, "unset": f"project '{proj_key}'"}}))
            return 0
        print(toon.encode({"meta": {"ok": False, "reason": "not found"}}))
        return 1
    else:
        if "theme" in cfg and "default" in cfg["theme"]:
            del cfg["theme"]["default"]
            config.save(cfg)
            print(toon.encode({"meta": {"ok": True, "unset": "default"}}))
            return 0
        return 0


def cmd_install(a) -> int:
    """Install theme hooks, prompt integration, or terminal configuration."""
    from . import omp
    from . import theme_project

    if getattr(a, "prompt", None) == "omp":
        theme_name, _ = _resolve_cwd_theme()
        t = theme.get(theme_name)
        omp_path = omp.write_theme_omp(t)

        shells = [a.shell] if getattr(a, "shell", None) else ["pwsh", "bash", "cmd"]
        results = []
        for sh in shells:
            try:
                res = omp.install(sh, omp_path)
                results.append([res["shell"], res["path"], "installed" if res["changed"] else "already-there"])
            except Exception as e:
                results.append([sh, "error", str(e)])

        if policy.pretty():
            ui.table(["shell", "path", "status"], results, title="Oh My Posh Prompt Install")
        else:
            print(toon.table("installed", ["shell", "path", "status"], results))
        return 0

    if getattr(a, "hook", False):
        shells = [a.shell] if getattr(a, "shell", None) else ["pwsh", "bash", "cmd"]
        results = []
        for sh in shells:
            try:
                res = theme_project.install_hook(sh)
                results.append([res["shell"], res["path"], "installed" if res["changed"] else "already-there"])
            except Exception as e:
                results.append([sh, "error", str(e)])

        if policy.pretty():
            ui.table(["shell", "path", "status"], results, title="Directory Hook Install")
        else:
            print(toon.table("installed", ["shell", "path", "status"], results))
        return 0

    if getattr(a, "terminal", None) == "wt":
        p = theme_project.write_wt_fragment()
        print(toon.encode({"meta": {"ok": True, "action": "install", "target": "terminal-wt", "path": p}}))
        return 0

    print("Nothing to install. Specify --prompt omp, --hook, or --terminal wt.")
    return 0


def cmd_uninstall(a) -> int:
    """Uninstall theme hooks, prompt integration, or terminal configuration."""
    from . import omp
    from . import theme_project

    if getattr(a, "prompt", False):
        shells = [a.shell] if getattr(a, "shell", None) else ["pwsh", "bash", "cmd"]
        results = []
        for sh in shells:
            try:
                res = omp.uninstall(sh)
                results.append([res["shell"], res["path"], "removed" if res["removed"] else "not-installed"])
            except Exception as e:
                results.append([sh, "error", str(e)])

        if policy.pretty():
            ui.table(["shell", "path", "status"], results, title="Oh My Posh Prompt Uninstall")
        else:
            print(toon.table("uninstalled", ["shell", "path", "status"], results))
        return 0

    if getattr(a, "hook", False):
        shells = [a.shell] if getattr(a, "shell", None) else ["pwsh", "bash", "cmd"]
        results = []
        for sh in shells:
            try:
                res = theme_project.uninstall_hook(sh)
                results.append([res["shell"], res["path"], "removed" if res["removed"] else "not-installed"])
            except Exception as e:
                results.append([sh, "error", str(e)])

        if policy.pretty():
            ui.table(["shell", "path", "status"], results, title="Directory Hook Uninstall")
        else:
            print(toon.table("uninstalled", ["shell", "path", "status"], results))
        return 0

    if getattr(a, "terminal", False):
        ok = theme_project.remove_wt_fragment()
        print(toon.encode({"meta": {"ok": ok, "action": "uninstall", "target": "terminal-wt"}}))
        return 0

    print("Nothing to uninstall. Specify --prompt, --hook, or --terminal.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ad-theme",
        description="Terminal palettes, prompt theming, and project colours."
    )
    from . import version
    version.add_version(p)
    p.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")

    sub = p.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="list all available themes in TOON")
    p_list.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")

    p_show = sub.add_parser("show", help="show theme palette details")
    p_show.add_argument("name", nargs="?", help="theme name")
    p_show.add_argument("--cwd", action="store_true", help="show active theme for current directory")
    p_show.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")

    p_gal = sub.add_parser("gallery", help="gallery of themes (colored on TTY, names only when piped)")
    p_gal.add_argument("--prompt", action="store_true", help="include prompt designs")
    p_gal.add_argument("--pretty", action="store_true", help="draw it as a table for a person to read")

    p_apply = sub.add_parser("apply", help="recolour live terminal")
    p_apply.add_argument("name", nargs="?", help="theme name (defaults to current project or default)")
    p_apply.add_argument("--persist", action="store_true", help="persist to registry (conhost only)")

    p_reset = sub.add_parser("reset", help="reset terminal colours to default")

    p_set = sub.add_parser("set", help="set default, project or scheduled theme in config.json")
    p_set.add_argument("name", nargs="?", help="theme name")
    p_set.add_argument("--project", help="project directory or name")
    p_set.add_argument("--default", action="store_true", help="set as global default")
    p_set.add_argument("--after", help="schedule start time, e.g. 18:00")
    p_set.add_argument("--until", help="schedule end time, e.g. 07:00")
    p_set.add_argument("--transient", choices=["on", "off"], help="turn Oh My Posh transient prompt on or off")

    p_unset = sub.add_parser("unset", help="unset theme from config.json")
    p_unset.add_argument("--project", help="project directory or name")

    p_inst = sub.add_parser("install", help="install theme hooks, prompt or terminal configuration")
    p_inst.add_argument("--prompt", choices=["omp"], help="prompt integration (omp)")
    p_inst.add_argument("--hook", action="store_true", help="directory hook")
    p_inst.add_argument("--terminal", choices=["wt"], help="terminal fragment (wt)")
    p_inst.add_argument("--shell", choices=["pwsh", "bash", "cmd"], help="specific shell")
    p_inst.add_argument("--pretty", action="store_true", help="draw as table")

    p_uninst = sub.add_parser("uninstall", help="uninstall theme hooks, prompt or terminal configuration")
    p_uninst.add_argument("--prompt", action="store_true", help="remove prompt integration")
    p_uninst.add_argument("--hook", action="store_true", help="remove directory hook")
    p_uninst.add_argument("--terminal", action="store_true", help="remove terminal fragment")
    p_uninst.add_argument("--shell", choices=["pwsh", "bash", "cmd"], help="specific shell")
    p_uninst.add_argument("--pretty", action="store_true", help="draw as table")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    completion.autocomplete(parser)
    args = parser.parse_args(argv)

    if getattr(args, "pretty", False):
        os.environ["AGENTDATA_UI"] = "rich"
        ui.reset_cache()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "gallery": cmd_gallery,
        "apply": cmd_apply,
        "reset": cmd_reset,
        "set": cmd_set,
        "unset": cmd_unset,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
    }

    fn = commands.get(args.command)
    if not fn:
        parser.print_help()
        return 0
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
