"""The drawing and input toolkit `tnp` is built on: a screen is a list of lines, fitted to the terminal, and every
widget (menu, text field, checkbox list, pager) draws one and reads keys until it has an answer.

toil's menu is the model, and these are the parts of it TNP lacked:

* **The header stays on every screen.** The wordmark (or one compact line, in a short terminal) and the
  breadcrumb, so a person always sees where they are.
* **Nothing wraps sideways.** A line wider than the terminal is cut with `…`; descriptions never break mid-word.
* **Nothing scrolls the header away.** Body text that does not fit is cut to the room left; a list longer than
  the room scrolls, with `↑ N more` / `↓ N more`.
* **Questions are answered on the screen**, in a text field (`host: tdprod.corp▏`), a pick list or a checkbox
  list, and every answer so far stays visible above the next question.

Keys: up/down (and j/k in lists), Enter, digits 1-9 jump, Esc or Backspace goes back one screen, q quits tnp
from anywhere. Without a terminal (a pipe, a test with no keys) every widget falls back to one numbered line
prompt, so `tnp` still works over a dumb pipe.
"""
from __future__ import annotations

import re
import shutil
import sys
import textwrap
from typing import Iterator

from . import brand as B

ANSI = re.compile(r"\x1b\[[0-9;]*m")
GLYPH = {"ok": "✓", "warn": "!", "fail": "✗", "info": "·", "skip": "–"}
SHADE = {"ok": (46, 160, 67), "warn": (210, 153, 34), "fail": (218, 54, 51), "info": B.MUTED, "skip": B.MUTED}
SEP = " › "
NAMED = {"up", "down", "left", "right", "home", "end", "pgup", "pgdn", "delete", "enter", "esc", "backspace", "tab",
         "space", "ctrl-u"}


class Back(Exception):
    """Leave the current screen (Esc)."""


class Quit(Exception):
    """Leave tnp (q, from anywhere)."""


def visible(s: str) -> int:
    return len(ANSI.sub("", s))


def fit(s: str, width: int) -> str:
    """`s` cut to `width` visible columns with `…`, escape codes kept whole and closed."""
    if visible(s) <= width:
        return s
    out, n, i = [], 0, 0
    while i < len(s):
        m = ANSI.match(s, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        if n >= width - 1:
            break
        out.append(s[i])
        n += 1
        i += 1
    return "".join(out) + "…" + ("\x1b[0m" if "\x1b[" in s else "")


def glyph(status: str) -> str:
    return B.rgb(GLYPH.get(status, "?"), SHADE.get(status, B.MUTED), True)


class Tui:
    """Drawing and widgets. The app supplies `header_lines()`; tests pass `keys` (an iterator of key names or
    pasted text) and a `height`."""

    def __init__(self, keys: Iterator[str] | None = None, out=None, height: int | None = None,
                 width: int | None = None) -> None:
        self.out = out or sys.stdout
        self.keys = keys
        self.tty = keys is None and sys.stdin.isatty() and getattr(self.out, "isatty", lambda: False)()
        self._height, self._width = height, width

    # ------------------------------------------------------------------ geometry

    @property
    def cols(self) -> int:
        return self._width or shutil.get_terminal_size((100, 40)).columns

    @property
    def rows(self) -> int | None:
        """The screen height, or None (print everything) off a terminal."""
        if self._height:
            return self._height
        return shutil.get_terminal_size((100, 40)).lines if self.tty else None

    @property
    def interactive(self) -> bool:
        return self.tty or self.keys is not None

    # ------------------------------------------------------------------ text helpers (return lines)

    def wrap(self, text: str, indent: int = 2, muted: bool = False, hang: int = 0) -> list[str]:
        width = max(self.cols - 2, 30)
        lines = textwrap.wrap(text, width, initial_indent=" " * indent, subsequent_indent=" " * (indent + hang),
                              break_on_hyphens=False) or [""]
        return [B.muted(x) if muted else x for x in lines]

    def bullet(self, text: str) -> list[str]:
        width = max(self.cols - 2, 30)
        return textwrap.wrap(text, width, initial_indent="    • ", subsequent_indent="      ") or [""]

    def heading(self, text: str, note: str = "") -> str:
        return "  " + B.select(text) + (B.muted(f"  {note}") if note else "")

    def fact(self, label: str, value: str) -> str:
        """`Label      value`. A value too wide (a path, above all) wraps under itself rather than being cut:
        where a file is written is the one thing these lines exist to say."""
        room = max(self.cols - 14, 20)
        if visible(value) <= room:
            return f"  {B.label(label.ljust(10))} {value}"
        plain = ANSI.sub("", value)
        parts = [plain[i:i + room] for i in range(0, len(plain), room)]
        return f"  {B.label(label.ljust(10))} {parts[0]}" + "".join("\n" + " " * 13 + p for p in parts[1:])

    def check_rows(self, checks, only_problems: bool = False, hints: bool = True) -> list[str]:
        out = []
        width = max(self.cols - 29, 24)
        for c in checks:
            if only_problems and c.status in ("ok", "info"):
                continue
            detail = textwrap.wrap(c.detail, width) or [""]
            out.append(f"  {glyph(c.status)} {c.name:<22} {detail[0]}")
            out += [" " * 27 + more for more in detail[1:]]
            if hints and c.hint and c.status in ("fail", "warn"):
                out += self.wrap(f"fix: {c.hint}", indent=6, muted=True)
        return out

    def check_line(self, c) -> str:
        """One check on one line: the home screen's Needs attention."""
        return fit(f"  {glyph(c.status)} {c.name:<22} {c.detail}", self.cols - 1)

    def command_lines(self, *commands: str) -> list[str]:
        out = ["", B.muted("  Each step above is a plain command: run it yourself any time.")]
        width = max(self.cols - 6, 30)
        for cmd in commands:                                  # a long one wraps at its spaces, never cut
            lines = textwrap.wrap(cmd, width, break_on_hyphens=False, break_long_words=False) or [cmd]
            out += ["    " + B.accent(lines[0])] + ["      " + B.accent(x) for x in lines[1:]]
        return out

    # ------------------------------------------------------------------ drawing

    def header_lines(self) -> list[str]:
        return []

    def crumb_line(self, crumbs: tuple[str, ...]) -> str:
        parts = "".join(B.muted(SEP) + (B.select(p) if i == len(crumbs) - 1 else p) for i, p in enumerate(crumbs))
        return "  " + B.accent("TNP") + parts

    def draw(self, crumbs: tuple[str, ...], body: list[str], widget: list[str], footer: str,
             tail: bool = False, home: bool = False) -> None:
        """One screen. Body lines that do not fit are cut (from the top when `tail`: the newest answers matter
        most), the widget is drawn whole (callers window it), the footer is always the last line."""
        head = self.header_lines()
        body = [x for line in body for x in line.split("\n")]       # a wrapped fact is several rows
        widget = [x for line in widget for x in line.split("\n")]
        top = head + ([self.crumb_line(crumbs), ""] if crumbs else [])
        bottom = [""] + widget + ["", B.muted("  " + footer)]
        rows = self.rows
        if rows is not None:
            room = rows - len(top) - len(bottom)
            if room < 0 and len(head) > 2:                  # a short terminal: the compact header
                top = self.compact_header() + top[len(head):]
                room = rows - len(top) - len(bottom)
            if len(body) > max(room, 0):
                keep = max(room - 1, 0)
                cut = len(body) - keep
                note = B.muted(f"  … {cut} line{'s' * (cut != 1)} " + ("above" if tail else "below"))
                body = ([note] + body[cut:] if tail else body[:keep] + [note]) if keep >= 0 and room > 0 else []
        lines = [fit(x, self.cols - 1) for line in top + body + bottom for x in line.split("\n")]
        if self.tty:
            self.out.write("\x1b[2J\x1b[H" + "\n".join(lines))
            self.out.flush()
        else:
            self.out.write("\n".join(lines) + "\n")

    def compact_header(self) -> list[str]:
        return ["  " + B.gradient("TNP", bold=True) + "  " + B.muted(B.NAME), ""]

    def room(self, crumbs: tuple[str, ...], body: list[str], extra: int = 0) -> int | None:
        """Rows a widget may use under `body`, or None (unlimited)."""
        rows = self.rows
        if rows is None:
            return None
        head = len(self.header_lines())
        body = [x for line in body for x in line.split("\n")]
        fixed = head + (2 if crumbs else 0) + 3 + extra
        if rows - fixed - len(body) < 6 and head > 2:
            fixed = fixed - head + 2
        return max(rows - fixed - len(body), 3)

    # ------------------------------------------------------------------ input

    def key(self) -> str:
        if self.keys is not None:
            return next(self.keys)
        from .keys import read_key
        return read_key()

    def _line(self, prompt: str) -> str:
        self.out.write(prompt)
        self.out.flush()
        return input().strip()

    # ------------------------------------------------------------------ widgets

    def window(self, n: int, sel: int, room: int | None) -> tuple[int, int]:
        if room is None or n <= room:
            return 0, n
        size = max(room - 2, 1)                              # the two more-markers
        start = min(max(sel - size // 2, 0), n - size)
        return start, start + size

    def choose(self, crumbs: tuple[str, ...], items: list[tuple[str, str]], body: list[str] | None = None,
               sel: int = 0, home: bool = False, tail: bool = False) -> int:
        """The index chosen. Esc raises Back (home: Quit), q raises Quit."""
        body = list(body or [])
        if not self.interactive:
            return self._choose_line(crumbs, items, body, sel, home)
        lw = max([len(a) for a, _ in items] + [8]) + 3
        while True:
            room = self.room(crumbs, body if not tail else body[-3:])
            if room is not None and room < len(items) and not tail:
                # the choices win the room: the body above is cut (draw() says how much), keeping 4 lines of it
                room = max(min(len(items), (self.room(crumbs, []) or 0) - 4), room)
            start, end = self.window(len(items), sel, room)
            rows = [B.muted(f"    ↑ {start} more")] if start else []
            for i in range(start, end):
                label, desc = items[i]
                n = str(i + 1) if i < 9 else " "
                mark = B.accent("▸") if i == sel else " "
                text = f"{n}  {label.ljust(lw)}"
                rest = max(self.cols - 6 - len(text), 0)
                d = fit(desc, rest) if desc else ""
                rows.append(f"  {mark} " + (B.select(text) if i == sel else text) + B.muted(d))
            if end < len(items):
                rows.append(B.muted(f"    ↓ {len(items) - end} more"))
            jump = f"   1-{min(len(items), 9)} jump" if len(items) > 1 else ""
            self.draw(crumbs, body, rows, "up/down move   enter select" + jump +
                      ("   q quit" if home else "   esc back   q quit"), tail=tail, home=home)
            k = self.key()
            if k in ("up", "k"):
                sel = (sel - 1) % len(items)
            elif k in ("down", "j", "tab"):
                sel = (sel + 1) % len(items)
            elif k in ("home", "pgup"):
                sel = 0 if k == "home" else max(sel - (room or 10), 0)
            elif k in ("end", "pgdn"):
                sel = len(items) - 1 if k == "end" else min(sel + (room or 10), len(items) - 1)
            elif k in ("enter", "right", "space"):
                return sel
            elif len(k) == 1 and k.isdigit() and 1 <= int(k) <= min(len(items), 9):
                return int(k) - 1
            elif k in ("esc", "backspace", "left"):
                if home:
                    raise Quit
                raise Back
            elif k in ("q", "Q"):
                raise Quit

    def _choose_line(self, crumbs, items, body, sel, home) -> int:
        self.draw(crumbs, body, [f"    {i + 1}  {a}  " + B.muted(d) for i, (a, d) in enumerate(items)],
                  "a number, enter for " + str(sel + 1) + (", q quits" if home else ", b goes back, q quits"),
                  home=home)
        got = self._line("  choose: ").lower()
        if got in ("q", "quit"):
            raise Quit
        if got in ("b", "back", "esc"):
            raise Back
        if got.isdigit() and 1 <= int(got) <= len(items):
            return int(got) - 1
        for i, (a, _d) in enumerate(items):
            if got and a.lower() == got:
                return i
        return sel

    def field(self, crumbs: tuple[str, ...], label: str, default: str = "", secret: bool = False,
              body: list[str] | None = None, hint: str = "") -> str:
        """A text field on the screen, prefilled with `default`. Enter accepts, Esc goes back (raises Back),
        Ctrl-U clears. A secret is drawn as dots."""
        body = list(body or [])
        if not self.interactive:
            self.draw(crumbs, body, [], "type, then enter")
            shown = "" if secret or not default else f" [{default}]"
            if secret:
                import getpass
                return getpass.getpass(f"  {label}: ") or (default or "")
            return self._line(f"  {label}{shown}: ") or (default or "")
        value = default or ""
        while True:
            shown = "•" * len(value) if secret else value
            room = self.cols - 6
            if len(label) + len(shown) + 3 > room:            # a long question: its own line, the field under it
                lines = self.wrap(label, indent=2) + [fit("  " + B.select("› ") + shown, room) + "▏"]
            else:
                lines = [f"  {label}: " + B.select(shown) + "▏"]
            if hint:
                lines += self.wrap(hint, indent=2, muted=True)
            self.draw(crumbs, body, lines, "type   enter go on   ctrl-u clear   esc back", tail=True)
            k = self.key()
            if k == "enter":
                return value
            if k == "esc":
                raise Back
            if k == "backspace":
                value = value[:-1]
            elif k == "ctrl-u":
                value = ""
            elif k == "space":
                value += " "
            elif k in NAMED:
                continue
            else:
                value += k                                    # one character, or a pasted string

    def checklist(self, crumbs: tuple[str, ...], items: list[tuple[str, str]], ticked: set[int],
                  body: list[str] | None = None, other: str = "") -> tuple[list[int], bool]:
        """Indices ticked, and whether the last row (`other`, when given) was chosen. Space ticks, Enter goes
        on, Esc goes back."""
        body = list(body or [])
        rows_src = items + ([(other, "")] if other else [])
        ticked = set(ticked)
        if not self.interactive:
            self.draw(crumbs, body, [f"    {i + 1}  [{'x' if i in ticked else ' '}] {a}  " + B.muted(d)
                                     for i, (a, d) in enumerate(items)], "numbers, comma-separated; enter keeps")
            got = self._line("  ticks: ")
            if not got:
                return sorted(ticked), False
            picks = {int(x) - 1 for x in got.replace(" ", "").split(",") if x.isdigit()}
            return sorted(i for i in picks if 0 <= i < len(items)), False
        sel = 0
        lw = max([len(a) for a, _ in rows_src] + [8]) + 2
        while True:
            room = self.room(crumbs, body)
            start, end = self.window(len(rows_src), sel, room)
            rows = [B.muted(f"    ↑ {start} more")] if start else []
            for i in range(start, end):
                label, desc = rows_src[i]
                box = "   " if other and i == len(items) else ("[x]" if i in ticked else "[ ]")
                mark = B.accent("▸") if i == sel else " "
                text = f"{box} {label.ljust(lw)}"
                d = fit(desc, max(self.cols - 6 - len(text), 0)) if desc else ""
                rows.append(f"  {mark} " + (B.select(text) if i == sel else text) + B.muted(d))
            if end < len(rows_src):
                rows.append(B.muted(f"    ↓ {len(rows_src) - end} more"))
            self.draw(crumbs, body, rows, "up/down move   space tick   enter go on   esc back   q quit")
            k = self.key()
            if k in ("up", "k"):
                sel = (sel - 1) % len(rows_src)
            elif k in ("down", "j", "tab"):
                sel = (sel + 1) % len(rows_src)
            elif k == "space":
                if other and sel == len(items):
                    return sorted(ticked), True
                ticked ^= {sel}
            elif k == "enter":
                return sorted(ticked), bool(other and sel == len(items))
            elif k in ("esc", "backspace", "left"):
                raise Back
            elif k in ("q", "Q"):
                raise Quit

    def pager(self, crumbs: tuple[str, ...], body: list[str], actions: list[tuple[str, str]] | None = None) -> int:
        """Read-only text that scrolls (up/down, page keys), then the actions under it; Enter on an action
        returns its index. With no actions, Enter or Esc goes back."""
        if not self.interactive:
            self.draw(crumbs, body, [], "the end")
            if actions:
                return self._choose_line(crumbs, actions, [], 0, False)
            return -1
        top = 0
        while True:
            room = self.room(crumbs, [], extra=len(actions or []) + 1) or len(body)
            if len(body) <= room:
                view, top = body, 0
            else:
                top = min(max(top, 0), len(body) - room + 1)
                view = ([B.muted(f"    ↑ {top} more")] if top else []) + body[top + bool(top):top + room - 1] + \
                       ([B.muted(f"    ↓ {len(body) - top - room + 1} more")] if top + room - 1 < len(body) else [])
            if actions:
                rows = ["  " + B.accent("▸") + " " + B.select(f"1  {actions[0][0]}") + "   " + B.muted(actions[0][1])]
                rows += [f"    {i + 1}  {a}   " + B.muted(d) for i, (a, d) in enumerate(actions[1:], 1)]
            else:
                rows = []
            scroll = "up/down scroll   " if len(body) > room else ""
            self.draw(crumbs, view, rows, scroll + ("enter " + actions[0][0].lower() + "   esc back" if actions
                                                    else "enter or esc back") + "   q quit")
            k = self.key()
            if k in ("up", "k"):
                top -= 1
            elif k in ("down", "j"):
                top += 1
            elif k == "pgup":
                top -= room
            elif k in ("pgdn", "space"):
                top += room
            elif k == "enter":
                return 0 if actions else -1
            elif actions and len(k) == 1 and k.isdigit() and 1 <= int(k) <= len(actions):
                return int(k) - 1
            elif k in ("esc", "backspace", "left"):
                if actions:
                    raise Back
                return -1
            elif k in ("q", "Q"):
                raise Quit
