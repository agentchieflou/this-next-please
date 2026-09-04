"""The `console` step: which shell and code page this command is running under.

It never fails the doctor. An unsupported shell is something for the user to change, not a broken
install, and a `fail` here would stop them seeing the rows that say what else is wrong.
"""
from __future__ import annotations
import sys
from typing import Any

from ..wizard import Context, Step
from ... import shell as S
from ... import ui


class ConsoleStep(Step):
    key = "console"
    title = "console (shell, encoding)"

    def detect(self, ctx: Context) -> dict:
        return {"shell": S.check_row(), "encoding": (sys.stdout.encoding or "unknown").lower()}

    def check(self, ctx: Context, found: dict) -> None:
        row = found["shell"]
        ctx.add(self.key, "shell", row["status"], row["detail"], row["hint"])

        enc = found["encoding"]
        unicode_ok = ui.glyphs() is not ui.ASCII_GLYPHS
        if unicode_ok:
            ctx.add(self.key, "encoding", "ok", f"{enc} (box glyphs available)")
        else:
            ctx.add(self.key, "encoding", "warn", f"{enc} cannot encode the status glyphs",
                    "tables fall back to ASCII; `chcp 65001` or use Windows Terminal for the box drawing")
