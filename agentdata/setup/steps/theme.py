"""The `theme` step: terminal colours, prompt integration, and project palettes.

Introduces CLI themes with an in-terminal gallery, doctor checks for theme configuration
and integrations (directory hooks, Windows Terminal fragment, Oh My Posh, Clink, Nerd Font),
and prompts for default theme and optional integrations.
"""
from __future__ import annotations

import os
from typing import Any

from ..wizard import Context, QuickPrompter, Step
from ... import color
from ... import omp
from ... import shell
from ... import textio
from ... import theme
from ... import theme_project
from ... import ui


def probe_theme_hooks() -> list[tuple[str, str]]:
    """Probe candidate startup files for the directory theme hook without spawning processes."""
    from ... import completion

    found = []
    for sh, path in completion.candidate_startup_files():
        try:
            if os.path.isfile(path):
                content = textio.read_text(path)
                if theme_project.HOOK_MARKER in content or theme_project.HOOK_MARKER_LUA in content:
                    found.append((sh, textio.norm_path(path)))
        except OSError:
            continue

    # Clink Lua script for cmd.exe
    local_app = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    clink_lua = os.path.join(local_app, "clink", "oh-my-posh.lua")
    try:
        if os.path.isfile(clink_lua):
            content = textio.read_text(clink_lua)
            if theme_project.HOOK_MARKER in content or theme_project.HOOK_MARKER_LUA in content:
                found.append(("cmd", textio.norm_path(clink_lua)))
    except OSError:
        pass

    return found


class ThemeStep(Step):
    key = "theme"
    title = "theme (terminal colours, prompt)"

    def detect(self, ctx: Context) -> dict[str, Any]:
        from ... import console as CON

        omp_info = omp.detect()
        wt_frag = theme_project.wt_fragment_path()
        wt_dir = os.path.dirname(wt_frag)
        hooks = probe_theme_hooks()

        default_theme = ctx.cfg.get("theme", {}).get("default") or "none"

        current_shell = shell.detect()
        if current_shell in ("unknown", "posix"):
            current_shell = "bash" if os.name != "nt" else "pwsh"
        elif current_shell == "windows-powershell":
            current_shell = "pwsh"

        return {
            "host": CON.host(),
            "shell": current_shell,
            "omp_installed": omp_info.get("installed", False),
            "omp_version": omp_info.get("version"),
            "omp_exe": omp_info.get("exe"),
            "clink_installed": omp_info.get("clink", False),
            "clink_exe": omp_info.get("clink_exe"),
            "nerd_font": omp_info.get("nerd_font", False),
            "wt_present": os.path.isdir(wt_dir) or os.path.isfile(wt_frag),
            "wt_fragment_exists": os.path.isfile(wt_frag),
            "wt_frag_path": wt_frag,
            "default_theme": default_theme,
            "hooks": hooks,
        }

    def check(self, ctx: Context, found: dict) -> None:
        # 1. theme/default (the chosen theme, or none)
        chosen = found.get("default_theme") or "none"
        if chosen != "none":
            ctx.add(self.key, "default", "ok", f"'{chosen}'", keys=("theme.default",))
        else:
            ctx.add(
                self.key,
                "default",
                "warn",
                "no default theme configured (none)",
                "run 'ad-setup --only theme' or 'ad-theme apply <name>' to pick one",
                keys=("theme.default",),
            )

        # 2. theme/hook (which startup files carry the line, probed like console/completion)
        hooks = found.get("hooks") or []
        if hooks:
            ctx.add(
                self.key,
                "hook",
                "ok",
                ", ".join(f"{sh}: {p}" for sh, p in hooks),
                keys=("theme.hook",),
            )
        else:
            ctx.add(
                self.key,
                "hook",
                "warn",
                "directory theme hook is not installed in any startup file",
                "ad-setup --only theme or ad-theme hook --install",
                keys=("theme.hook",),
            )

        # 3. theme/terminal (fragment present and current)
        wt_exists = found.get("wt_fragment_exists", False)
        if wt_exists:
            ctx.add(
                self.key,
                "terminal",
                "ok",
                f"fragment present ({found.get('wt_frag_path')})",
                keys=("theme.terminal",),
            )
        else:
            ctx.add(
                self.key,
                "terminal",
                "warn",
                "Windows Terminal fragment not installed",
                "ad-setup --only theme or ad-theme fragment --install",
                keys=("theme.terminal",),
            )

        # 4. theme/oh-my-posh
        if found.get("omp_installed"):
            detail = f"{found.get('omp_version') or 'installed'} ({found.get('omp_exe')})"
            ctx.add(self.key, "oh-my-posh", "ok", detail, keys=())
        else:
            ctx.add(
                self.key,
                "oh-my-posh",
                "warn",
                "not installed on PATH",
                "winget install JanDeDobbeleer.OhMyPosh (optional prompt engine)",
                keys=(),
            )

        # 5. theme/clink
        if found.get("clink_installed"):
            detail = f"installed ({found.get('clink_exe')})"
            ctx.add(self.key, "clink", "ok", detail, keys=())
        else:
            ctx.add(
                self.key,
                "clink",
                "warn",
                "not installed",
                "winget install chrisant996.clink (optional for cmd.exe)",
                keys=(),
            )

        # 6. theme/nerd-font
        if found.get("nerd_font"):
            ctx.add(self.key, "nerd-font", "ok", "detected (powerline glyphs available)", keys=())
        else:
            ctx.add(
                self.key,
                "nerd-font",
                "warn",
                "not detected in environment",
                "set NERD_FONT=1 or use a Nerd Font (e.g. Cascadia Code NF) for powerline glyphs",
                keys=(),
            )

    def ask(self, ctx: Context, found: dict) -> None:
        # --quick accepts nothing here: a theme is a taste, never an "unambiguous detected default";
        # the step prints `[quick] theme: left as is` and moves on.
        is_quick = isinstance(ctx.ask, QuickPrompter) or isinstance(getattr(ctx.ask, "inner", None), QuickPrompter)
        if is_quick:
            ctx.say("  [quick] theme: left as is")
            return

        # If interactive and not in scoped patch skipping gallery
        if ctx.interactive and not getattr(ctx.ask, "inner", None):
            ctx.say("\nCLI Themes gallery:")
            for t in theme.list_themes():
                ctx.say(f"  {t.name:16} · {t.why}")

        current_default = ctx.cfg.get("theme", {}).get("default") or "none"
        choices = [t.name for t in theme.list_themes()]
        if "none" not in choices:
            choices.append("none")

        chosen = ctx.ask.ask(
            "theme.default",
            "default theme",
            default=current_default,
            choices=choices,
        )

        # --non-interactive: reads --set theme.default=greens and does nothing without it
        if not chosen or chosen == "none":
            if "theme" in ctx.cfg and "default" in ctx.cfg["theme"]:
                ctx.cfg["theme"]["default"] = "none"
            return

        ctx.cfg.setdefault("theme", {})["default"] = chosen

        # Non-interactive without specific opt-in installs nothing
        if not ctx.interactive:
            # Check if any installation keys were explicitly set in answers
            answers = getattr(ctx.ask, "answers", {})
            if not any(k in answers for k in ("theme.apply", "theme.hook", "theme.terminal", "theme.omp")):
                return

        # When answer is not none, offers in order:
        # 1. apply now (#137)
        # 2. install the directory hook (#139)
        # 3. the Windows Terminal fragment
        # 4. and Oh My Posh (#138)
        # Each a yes/no with the exact writes listed.
        try:
            t = theme.get(chosen)
        except Exception:
            t = theme.GREENS

        shell_name = found.get("shell") or "pwsh"

        # 1. Apply now
        ctx.say(f"  apply theme '{chosen}' to current terminal (OSC palette sequences)")
        if ctx.ask.confirm("theme.apply", f"apply theme '{chosen}' now?", default=False):
            theme.apply(t)

        # 2. Directory hook
        d_hook = theme_project.themes_dir()
        hook_ps1 = textio.norm_path(os.path.join(d_hook, "hook.ps1"))
        hook_sh = textio.norm_path(os.path.join(d_hook, "hook.sh"))
        hook_lua = textio.norm_path(os.path.join(d_hook, "hook.lua"))
        try:
            startup_hook = textio.norm_path(omp.startup_file(shell_name))
        except Exception:
            startup_hook = textio.norm_path(os.path.expanduser("~/.bashrc"))

        ctx.say(f"  write directory hooks to {hook_ps1}, {hook_sh}, {hook_lua} and add hook line to {startup_hook}")
        if ctx.ask.confirm("theme.hook", f"install directory hook in {startup_hook}?", default=False):
            theme_project.install_hook(shell_name)

        # 3. Windows Terminal fragment
        wt_frag = textio.norm_path(found.get("wt_frag_path") or theme_project.wt_fragment_path())
        ctx.say(f"  write Windows Terminal fragment to {wt_frag}")
        if ctx.ask.confirm("theme.terminal", f"install Windows Terminal fragment in {wt_frag}?", default=False):
            theme_project.write_wt_fragment(wt_frag)

        # 4. Oh My Posh
        omp_target = textio.norm_path(os.path.join(omp.omp_dir(), f"{chosen}.omp.json"))
        try:
            startup_omp = textio.norm_path(omp.startup_file(shell_name))
        except Exception:
            startup_omp = textio.norm_path(os.path.expanduser("~/.bashrc"))

        ctx.say(f"  write Oh My Posh config to {omp_target} and add init line to {startup_omp}")
        if ctx.ask.confirm("theme.omp", f"install Oh My Posh prompt config in {startup_omp}?", default=False):
            omp_path = omp.write_theme_omp(t, omp_target)
            omp.install(shell_name, omp_path, startup_omp)
