# PYTHON_ARGCOMPLETE_OK
"""Shell tab-completion for ad-* commands and python -m agentdata.

The completions themselves come from `agentdata.complete`, a hidden verb that walks the argparse
tree. What lives here is the small script each shell needs to call it, and the `--install` that
puts one line in a startup file.

Two things the previous version got wrong, both of which meant a user pressing Tab got nothing:

* the bash script only did anything **if `register-python-argcomplete` was on PATH**. It ships in
  the `completion` extra, into the same `Scripts` directory whose absence from PATH is the reason
  `python -m agentdata` exists. So on the machine where it mattered most it was a no-op.
* the PowerShell script registered a completer whose body was a **comment**. It returned nothing,
  forever, and looked installed.

Neither needs argcomplete now, and the interpreter that generated the script is baked into it, so
completion keeps working when `ad-*` itself is not on PATH.
"""
from __future__ import annotations
import argparse
import os
import sys

PARSE_ONLY = "AGENTDATA_PARSE_ONLY"
COMPLETE_ENV = "AGENTDATA_COMPLETE"
SHELLS = ("bash", "zsh", "powershell")
# Both startup files get this line, so `--install` can tell "already there" from "not there" without
# parsing the file, and a person can find what put it there.
MARKER = "# agentdata tab-completion"


def all_commands() -> list[str]:
    """Every `ad-*` command a person can type, from the one place they are declared.

    This was a hand-kept list and it had drifted: `ad-pbi`, `ad-pbiviz`, `ad-graph` and `ad-test`
    were all missing, so four commands quietly had no completion at all. Reading `__main__.COMMANDS`
    means adding a command is enough. Imported inside the function because `__main__` is also the
    module form's entry point.
    """
    from . import __main__ as M

    return [f"ad-{name}" for name in M.COMMANDS if name not in M.HIDDEN]


class ParserCaptured(BaseException):
    """Carries a parser out of a `main()` that was never going to finish -- see `agentdata.complete`.

    A `BaseException`, deliberately: an `except Exception` in a command's prologue would swallow it
    and the command would then really run, during a keypress.
    """

    def __init__(self, parser: argparse.ArgumentParser):
        super().__init__("parser captured for completion")
        self.parser = parser


def _parse_only_wrapper(parser: argparse.ArgumentParser) -> None:
    """With AGENTDATA_PARSE_ONLY=1, stop after parsing and print what was parsed.

    This is how every command line printed in a skill, a doc or the README is checked against the
    real parser: the arguments are validated, and then nothing is read, launched or written. Wiring
    it here rather than into each `main()` means a new command cannot forget it -- every parser in
    this package already calls `autocomplete()` immediately before `parse_args()`.
    """
    if os.environ.get(PARSE_ONLY) != "1":
        return
    original = parser.parse_args

    def parse_and_stop(args=None, namespace=None):
        parsed = original(args, namespace)
        from . import toon

        payload = {k: ("" if v is None else v) for k, v in sorted(vars(parsed).items())
                   if not callable(v)}
        print(toon.encode({"meta": {"ok": True, "source": parser.prog, "parse_only": True},
                           "args": payload}))
        raise SystemExit(0)

    parser.parse_args = parse_and_stop           # type: ignore[method-assign]


def autocomplete(parser: argparse.ArgumentParser) -> None:
    """Activate argcomplete if installed and completing; inert otherwise.

    Also the single place `AGENTDATA_PARSE_ONLY` is honoured -- see `_parse_only_wrapper` -- and
    the seam `python -m agentdata _complete` takes the parser out through. Both work here for the
    same reason: every parser in this package calls this immediately before `parse_args()`, so
    neither can be forgotten by a new command, and neither lets the command itself run.
    """
    if os.environ.get(COMPLETE_ENV) == "1":
        raise ParserCaptured(parser)
    _parse_only_wrapper(parser)
    try:
        import argcomplete
        argcomplete.autocomplete(parser)
    except Exception:  # noqa: BLE001  argcomplete is optional and must never break a real run
        pass


# ----------------------------------------------------------------------------------- the scripts


def _python() -> str:
    """The interpreter that owns this install, spelled for a shell.

    Baked into the script rather than looked up: `ad-*` and `python` can resolve to different
    installs on a laptop with more than one Python, and completion that answers for the wrong one
    is worse than none.
    """
    from . import textio

    return textio.norm_path(sys.executable)


def _bash_body(cmds: list[str], py: str) -> str:
    """bash 4.4-clean. `mapfile` is 4.0; nothing here needs 4.4 itself, which is the floor."""
    return f"""{MARKER} (bash) -- generated by: ad-setup --print-completion bash
# Sourcing this twice is harmless: the function is redefined and `complete` re-registers.
_agentdata_complete() {{
    # bash sets COMP_LINE and COMP_POINT as shell variables, not exported ones, so they are passed
    # across explicitly. The `:-` defaults are what let this be called by hand, and by shellcheck.
    local line=${{COMP_LINE:-}} point=${{COMP_POINT:-0}}
    COMPREPLY=()
    mapfile -t COMPREPLY < <(COMP_LINE="$line" COMP_POINT="$point" \\
        "{py}" -m agentdata _complete 2>/dev/null)
}}
complete -o default -o bashdefault -F _agentdata_complete {" ".join(cmds)}
"""


def _powershell_body(cmds: list[str], py: str) -> str:
    """Windows PowerShell 5.1 syntax only: no `??`, no ternary, no `-Parallel`.

    5.1 is not a supported shell for running `ad-*` (see docs/shells.md), but a completer costs
    nothing to keep compatible and a person on a locked-down laptop still gets Tab.
    """
    names = ", ".join(f"'{c}'" for c in cmds)
    return f"""{MARKER} (PowerShell) -- generated by: ad-setup --print-completion powershell
$AgentdataCompleter = {{
    param($wordToComplete, $commandAst, $cursorPosition)
    # The interpreter is written in, not looked up: a script block keeps the session state it was
    # defined in, so a variable would vanish if someone dot-sourced this inside a function.
    $py = '{py}'
    $line = $commandAst.ToString()
    # The AST has the trailing space trimmed off, so `ad-graph <TAB>` arrives as `ad-graph` with the
    # cursor one past the end. Padding puts the space back; clamping the cursor instead made every
    # "what can follow" press complete the command's own name.
    if ($cursorPosition -gt $line.Length) {{
        $line = $line + (' ' * ($cursorPosition - $line.Length))
    }}
    $items = @()
    try {{
        $items = & $py -m agentdata _complete --line $line --cursor $cursorPosition
    }} catch {{
        return
    }}
    $word = $wordToComplete
    if ($null -eq $word) {{ $word = '' }}
    foreach ($item in $items) {{
        # Filtered against the word PowerShell says is being completed as well as against the line:
        # the two can disagree at a quote boundary, and offering a candidate that does not start
        # with what was typed makes the menu jump.
        if ($item -and $item.StartsWith($word)) {{
            [System.Management.Automation.CompletionResult]::new(
                $item, $item, 'ParameterValue', $item)
        }}
    }}
}}
foreach ($AgentdataCommand in @({names})) {{
    Register-ArgumentCompleter -Native -CommandName $AgentdataCommand -ScriptBlock $AgentdataCompleter
}}
"""


def completion_script(shell: str, commands: list[str] | None = None) -> str:
    cmds = commands or all_commands()
    shell = shell.lower().strip()
    py = _python()
    if shell == "bash":
        return _bash_body(cmds, py)
    if shell == "zsh":
        # zsh runs the bash completer through bashcompinit, which is what argcomplete's own zsh
        # support does. One body, so the two shells cannot answer differently.
        return ("autoload -U +X bashcompinit && bashcompinit\n" + _bash_body(cmds, py))
    if shell == "powershell":
        return _powershell_body(cmds, py)
    raise ValueError(f"unknown shell: {shell!r} (choose {', '.join(SHELLS)})")


def print_completion(shell: str) -> None:
    sys.stdout.write(completion_script(shell))
    sys.stdout.flush()


# ----------------------------------------------------------------------------------- installing


def startup_file(shell: str) -> str:
    """The file that shell reads at startup, expanded.

    Git Bash reads `~/.bashrc`; PowerShell's `$PROFILE` is per-host, so the path is asked of the
    interpreter that is actually installed rather than guessed at -- 5.1 and pwsh 7 use different
    files, and getting that wrong installs completion into a shell nobody runs.
    """
    shell = shell.lower().strip()
    if shell in ("bash", "zsh"):
        return os.path.join(os.path.expanduser("~"), ".bashrc" if shell == "bash" else ".zshrc")
    if shell != "powershell":
        raise ValueError(f"unknown shell: {shell!r} (choose {', '.join(SHELLS)})")

    from . import proc

    for exe in ("pwsh", "powershell"):
        found = proc.which(exe)
        if not found:
            continue
        rc, out, _err, _el = proc.run([found, "-NoProfile", "-NonInteractive", "-Command",
                                       "$PROFILE.CurrentUserAllHosts"], timeout=20)
        if rc == 0 and out.strip():
            return out.strip().splitlines()[0].strip()
    # No PowerShell to ask: the documented default, so `--install` still says where it would go.
    docs = "Documents"
    return os.path.join(os.path.expanduser("~"), docs, "PowerShell", "profile.ps1")


def install_line(shell: str) -> str:
    """The one line a startup file gets. It re-generates the script at shell start, so an update
    that adds a command does not need the line re-installed."""
    py = _python()
    if shell in ("bash", "zsh"):
        return f'eval "$("{py}" -m agentdata setup --print-completion {shell})"  {MARKER}'
    return (f"& '{py}' -m agentdata setup --print-completion powershell | "
            f"Out-String | Invoke-Expression  {MARKER}")


def install(shell: str, path: str | None = None) -> dict:
    """Append the install line to the shell's startup file, once.

    Idempotent by the marker rather than by the whole line, so an interpreter that moved does not
    leave two lines behind -- the stale one is replaced.
    """
    from . import textio

    shell = shell.lower().strip()
    if shell not in SHELLS:
        raise ValueError(f"unknown shell: {shell!r} (choose {', '.join(SHELLS)})")
    target = path or startup_file(shell)
    line = install_line(shell)

    existing = textio.read_text(target) if os.path.isfile(target) else ""
    kept = [ln for ln in existing.splitlines() if MARKER not in ln]
    already = len(kept) != len(existing.splitlines())
    body = "\n".join(kept).rstrip("\n")
    new = (body + "\n\n" if body else "") + line + "\n"
    changed = new != existing
    if changed:
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        textio.write_text(target, new)
    return {"shell": shell, "path": textio.norm_path(target), "changed": changed,
            "replaced": already, "line": line}


def installed_in(shell: str, path: str | None = None) -> bool:
    """Whether the startup file already registers the completer."""
    from . import textio

    target = path or startup_file(shell)
    if not os.path.isfile(target):
        return False
    return MARKER in textio.read_text(target)


def candidate_startup_files() -> list[tuple[str, str]]:
    """(shell, path) for every startup file that could carry the line, **without spawning anything**.

    `ad-doctor` is a dry run -- `--check`'s contract and a test both say so -- so it cannot ask
    PowerShell where `$PROFILE` is. These are the documented locations instead, including the
    OneDrive-redirected `Documents` that a managed Windows laptop usually has.
    """
    home = os.path.expanduser("~")
    out = [("bash", os.path.join(home, ".bashrc")), ("zsh", os.path.join(home, ".zshrc"))]
    for docs in (os.path.join(home, "Documents"), os.path.join(home, "OneDrive", "Documents")):
        out.append(("pwsh 7", os.path.join(docs, "PowerShell", "profile.ps1")))
        out.append(("PowerShell 5.1", os.path.join(docs, "WindowsPowerShell", "profile.ps1")))
    return out


def where_installed() -> list[tuple[str, str]]:
    """(shell, path) for each startup file that already registers the completer."""
    from . import textio

    found = []
    for shell, path in candidate_startup_files():
        try:
            if os.path.isfile(path) and MARKER in textio.read_text(path):
                found.append((shell, textio.norm_path(path)))
        except OSError:
            continue
    return found
