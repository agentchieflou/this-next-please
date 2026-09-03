"""How the CLI looks to a person, without changing a byte of what an agent reads.

Two audiences share these commands. Luna parses TOON, and a table drawn in box characters is not TOON -- so the
pretty rendering is only ever used when a HUMAN is at the console: `color.enabled()` is already false whenever
stdout is piped or captured, and `on()` is false with it. When in doubt the plain text wins.

The operator commands (`ad-setup`, `ad-doctor`, `ad-update`) render through here; the data commands
(`ad-td`, `ad-jira`, `ad-pbip`, `ad-uat`, `ad-dpm`, `ad-pncli`, ...) keep printing TOON in every context, because
their output IS the data. `AGENTDATA_UI=plain` forces TOON everywhere -- use it to paste a report into a ticket.

Rendering is `rich` when it is installed, and the module works without it: every helper falls back to the ANSI
text `color.py` already produced. On Windows, rich handles the console for us -- VT enabling, the CP437 box
characters a legacy PowerShell host can actually draw, and the double-width columns Asian text needs.
"""
from __future__ import annotations

import contextlib
import os
import sys

from . import color

# Deuteranopia-safe and legible on both a light and a dark console: status is carried by the glyph as well as
# the colour, so a screenshot in black and white still reads.
PALETTE = {
    "ok": "green", "warn": "yellow", "fail": "bold red", "skip": "dim", "error": "bold red",
    "label": "bold cyan", "value": "", "accent": "magenta", "muted": "dim", "border": "grey37",
    "title": "bold", "path": "cyan", "hint": "italic yellow",
}
GLYPHS = {"ok": "✓", "warn": "!", "fail": "✗", "skip": "–"}
ASCII_GLYPHS = {"ok": "+", "warn": "!", "fail": "x", "skip": "-"}

_console = None
_on: bool | None = None


def mode() -> str:
    """auto (pretty for a human, plain for a pipe) · rich (always pretty) · plain (never)."""
    m = (os.environ.get("AGENTDATA_UI") or "auto").strip().lower()
    return m if m in ("auto", "rich", "plain") else "auto"


def on() -> bool:
    """Cached. False whenever a machine might be reading, whatever the terminal says."""
    global _on
    if _on is None:
        if mode() == "plain":
            _on = False
        elif not (color.enabled() or mode() == "rich"):
            _on = False
        else:
            try:
                import rich  # noqa: F401
                _on = True
            except ImportError:
                _on = False
    return _on


def reset_cache() -> None:
    global _console, _on
    _console, _on = None, None


def console():
    """One rich Console for the process, or None. `force_terminal` covers PyCharm's run window and VS Code,
    which render ANSI without being a TTY -- `color.enabled()` already knows about them.

    `markup=False` is not optional: every string here is somebody else's text -- a Windows path, a hint naming
    `[IO.File]::WriteAllText`, a JQL with a bracket -- and rich would read the brackets as style tags. Styling is
    applied by passing a `Text` with a style, never by wrapping text in markup."""
    global _console
    if _console is None and on():
        from rich.console import Console
        try:
            tty = sys.stdout.isatty()
        except Exception:  # noqa: BLE001
            tty = False
        # A real Windows console that cannot do VT gets rich's ASCII box, which is right there. When stdout is
        # NOT a console at all -- PyCharm's window, VS Code, a capture -- "legacy console" is meaningless and the
        # Unicode box is correct, so say so rather than letting a failed GetConsoleMode decide.
        _console = Console(highlight=False, soft_wrap=False, markup=False,
                           force_terminal=None if tty else True, legacy_windows=None if tty else False,
                           width=int(os.environ["AGENTDATA_WIDTH"]) if os.environ.get("AGENTDATA_WIDTH") else None)
    return _console


def glyphs() -> dict:
    """A console that cannot encode ✓ prints `?`, which reads as a third status. Ask before using them."""
    try:
        "".join(GLYPHS.values()).encode(sys.stdout.encoding or "ascii")
        return GLYPHS
    except (UnicodeEncodeError, LookupError):
        return ASCII_GLYPHS


def status_text(value: str):
    """`✓ ok` in the status colour, as a rich Text (or the plain ANSI string when rich is off)."""
    key = str(value).strip().lower()
    if not on():
        return color.status(value)
    from rich.text import Text
    return Text(f"{glyphs().get(key, ' ')} {value}", style=PALETTE.get(key, ""))


def rule(title: str, style: str = "accent") -> None:
    """The `== step ==` separators, as a full-width rule when rich is on."""
    if not on():
        print(color.paint(f"\n== {title} ==", "bold"))
        return
    from rich.rule import Rule
    from rich.text import Text
    console().print(Rule(Text(title, style=PALETTE["title"]), style=PALETTE.get(style, style), align="left"))


def facts(pairs: list[tuple[str, object]], title: str = "", subtitle: str = "") -> None:
    """The screenshot's shape: a right-justified label column, values to the right, in a rounded panel."""
    if not on():
        line = " · ".join(f"{k} {v}" for k, v in pairs if v not in (None, ""))
        print(color.paint(title, "bold") + (" · " if title and line else "") + line)
        return
    from rich.table import Table
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style=PALETTE["label"], no_wrap=True)
    grid.add_column(overflow="fold")
    for k, v in pairs:
        if v in (None, ""):
            continue
        grid.add_row(str(k), v if hasattr(v, "__rich_console__") else _value(v))
    console().print(_panel(grid, title=title, subtitle=subtitle))


def _value(v: object):
    """A bare `False` in a report reads as a failure. Say what it means instead."""
    if isinstance(v, bool):
        from rich.text import Text
        return Text("yes" if v else "no", style=PALETTE["ok"] if v else PALETTE["muted"])
    return str(v)


def table(columns: list[str], rows: list[list], title: str = "", status_col: int | None = None,
          wrap: tuple[int, ...] = (), group_col: int | None = None) -> None:
    """A table a person reads. `status_col` gets the glyph treatment, `wrap` columns get the width, and
    `group_col` prints its value only when it changes -- the eye then reads one label per group, not a column
    of the same word repeated down the page."""
    if not on():
        return
    from rich import box
    from rich.table import Table
    from rich.text import Text
    t = Table(box=box.ROUNDED, border_style=PALETTE["border"], header_style=PALETTE["label"], expand=True,
              title=Text(title, style=PALETTE["title"]) if title else None, title_justify="left", pad_edge=False,
              padding=(0, 1))
    for n, c in enumerate(columns):
        t.add_column(c, overflow="fold", no_wrap=n not in wrap, ratio=3 if n in wrap else None,
                     justify="right" if n == group_col else "left",
                     style=PALETTE["accent"] if n == group_col else "")
    groups = [r[group_col] if group_col is not None and group_col < len(r) else None for r in rows]
    for i, r in enumerate(rows):
        cells = []
        for n, v in enumerate(r):
            if n == status_col:
                cells.append(status_text(v))
            elif n == group_col:
                cells.append("" if i and groups[i] == groups[i - 1] else str(v))
            else:
                cells.append("" if v is None else str(v))
        # the divider belongs to the LAST row of a group, so the next label starts under a fresh line
        t.add_row(*cells, end_section=i + 1 < len(rows) and groups[i + 1] != groups[i])
    console().print(t)


def problem(error: str, hint: str = "", title: str = "error") -> None:
    """A refusal a person can act on: what failed, then the one command that fixes it."""
    if not on():
        print(color.paint(f"{title}: {error}", "red", "bold") + (f"\n  hint: {hint}" if hint else ""))
        return
    from rich import box
    from rich.panel import Panel
    from rich.text import Text
    body = Text(error, style=PALETTE["fail"])
    if hint:
        body.append("\n")
        body.append(hint, style=PALETTE["hint"])
    console().print(Panel(body, title=Text(title, style=PALETTE["fail"]), title_align="left",
                          border_style="red", box=box.ROUNDED, padding=(0, 1)))


def note(text: str, style: str = "muted") -> None:
    if not on():
        print(color.paint(text, *(("dim",) if style == "muted" else ())))
        return
    from rich.text import Text
    console().print(Text(text, style=PALETTE.get(style, style)))


def commands(rows: list[tuple[str, str, str]], title: str, footer: str = "") -> None:
    """The front door (`python -m agentdata`): what exists, in one screen."""
    if not on():
        print(title)
        for a, b, c in rows:
            print(f"  {a:<12} {b:<18} {c}")
        if footer:
            print("\n" + footer)
        return
    from rich import box
    from rich.table import Table
    from rich.text import Text
    t = Table(box=box.SIMPLE_HEAD, border_style=PALETTE["border"], header_style=PALETTE["label"],
              title=Text(title, style=PALETTE["title"]), title_justify="left", pad_edge=False)
    t.add_column("module form", style=PALETTE["accent"], no_wrap=True)
    t.add_column("console script", style=PALETTE["path"], no_wrap=True)
    t.add_column("what it does", overflow="fold")
    for r in rows:
        t.add_row(*r)
    console().print(t)
    if footer:
        note(footer)


def capture(renderable) -> str:
    """Render to a string so a caller that `print`s a report keeps working. rich keeps the ANSI."""
    with console().capture() as cap:
        console().print(renderable)
    return cap.get().rstrip("\n")


def _meta_grid(meta: dict, skip: tuple[str, ...] = ()):
    from rich.table import Table
    grid = Table.grid(padding=(0, 2))
    grid.add_column(justify="right", style=PALETTE["label"], no_wrap=True)
    grid.add_column(overflow="fold")
    for k, v in meta.items():
        if k in skip or v in (None, "", [], {}):
            continue
        grid.add_row(k, ", ".join(str(x) for x in v) if isinstance(v, list) else _value(v))
    return grid


def _panel(renderable, title: str = "", subtitle: str = ""):
    from rich import box
    from rich.panel import Panel
    from rich.text import Text
    return Panel(renderable, title=Text(title, style=PALETTE["title"]) if title else None, title_align="left",
                 subtitle=Text(subtitle, style=PALETTE["muted"]) if subtitle else None, subtitle_align="right",
                 border_style=PALETTE["border"], box=box.ROUNDED, padding=(0, 1))


def _cell(value) -> object:
    """A `fail` or an `ok` in a result column is a status, and reads far faster in its colour."""
    text = "" if value is None else str(value)
    style = PALETTE.get(text.strip().lower())
    if style and text.strip().lower() in ("ok", "warn", "fail", "error", "skip"):
        from rich.text import Text
        return Text(text, style=style)
    return text


def record_view(record: dict, meta: dict) -> str:
    """One row (a `SELECT 1`, a whoami) as the labelled panel, not a table with a single line in it."""
    return capture(_panel(_meta_grid(record), title=str(meta.get("source") or ""),
                          subtitle=f"rule {meta.get('rule')}"))


def data_view(t, rows: list, meta: dict, stats: dict | None = None) -> str:
    """A query result for a person: the source and row counts above, the sampled rows below, `path` last --
    it is the file to script over when the sample is not the whole answer."""
    from rich import box
    from rich.console import Group
    from rich.table import Table
    numeric = _numeric_columns(t.columns, rows)
    from rich.text import Text
    table_ = Table(box=box.ROUNDED, border_style=PALETTE["border"], header_style=PALETTE["label"],
                   title=Text(str(t.name), style=PALETTE["title"]), title_justify="left", pad_edge=False,
                   padding=(0, 1))
    for n, c in enumerate(t.columns):
        table_.add_column(str(c), justify="right" if n in numeric else "left", overflow="fold",
                          style=PALETTE["value"])
    for r in rows:
        table_.add_row(*[_cell(v) for v in r])
    parts = [_panel(_meta_grid(meta, skip=("ok", "rule")), subtitle=f"rule {meta.get('rule')}"), table_]
    if stats:
        parts.append(_panel(_meta_grid({k: v for k, v in stats.items()}), title="stats"))
    return capture(Group(*parts))


def _numeric_columns(columns: list, rows: list) -> set:
    """Numbers right-align or the eye cannot compare them. Decided from the data, not from a driver's type."""
    out = set()
    for n in range(len(columns)):
        seen = [r[n] for r in rows[:50] if n < len(r) and r[n] not in (None, "")]
        if seen and all(isinstance(v, (int, float)) and not isinstance(v, bool) or
                        (isinstance(v, str) and _numberish(v)) for v in seen):
            out.add(n)
    return out


def _numberish(s: str) -> bool:
    try:
        float(s.replace(",", "").replace("%", "").lstrip("$").strip())
        return True
    except ValueError:
        return False


@contextlib.contextmanager
def progress(description: str):
    """Show transient progress on sys.stderr for long-running operations.
    Never emits anything to stdout. No-op when piped, mode is plain, or rich unavailable.
    """
    if mode() == "plain":
        yield
        return
    force = os.environ.get("AGENTDATA_PROGRESS", "").lower() in ("1", "true", "always")
    stderr_is_tty = False
    try:
        stderr_is_tty = bool(sys.stderr) and sys.stderr.isatty()
    except Exception:
        pass
    if not force and not (on() and stderr_is_tty):
        yield
        return
    try:
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
        stderr_console = Console(stderr=True, force_terminal=True if force else None, highlight=False)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=stderr_console,
            transient=True,
        ) as prog:
            prog.add_task(description)
            prog.refresh()
            yield prog
    except Exception:
        yield

