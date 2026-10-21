"""The setup steps' questions, answered on `tnp`'s screen instead of a line prompt.

Every step (`setup/steps/*.py`) asks through a `Prompter`: `ask`, `confirm`, `pick_many`, `say`. `ad-setup`
answers on stderr, `--non-interactive` from `--set`, and this one draws each question in the current screen:
a choice is a pick list, yes/no is a two-row list, free text is a field prefilled with the default, a password is
a field of dots, and several-of-many is a checkbox list. Every answer so far stays on the screen above the next
question, as toil's own step 3 does, so a person can see what they have said before they say the next thing.
"""
from __future__ import annotations

from ..setup import wizard as W
from . import brand as B
from .screen import Back


class TnpPrompter(W.Prompter):
    def __init__(self, app) -> None:
        super().__init__()
        self.app = app
        self.log: list[str] = []
        self.answers: dict[str, str] = {}       # key -> answer, secrets never: the replayable `--set` line

    # ------------------------------------------------------------------ the screen around a question

    def begin(self) -> None:
        self.log = []

    def reset(self) -> None:
        """A new flow: forget the answers the last one would replay."""
        self.log, self.answers = [], {}

    def body(self, question: str = "") -> list[str]:
        app = self.app
        out = list(app.form_intro)
        out += self.log
        if question:
            out += [""] + app.wrap(question, indent=2)
        return out

    def _answered(self, text: str, answer: str) -> None:
        q = text if len(text) < 44 else text[:41] + "…"
        self.log.append("  " + B.muted(q.ljust(44)) + "  " + (answer if answer else B.muted("(blank)")))

    # ------------------------------------------------------------------ the Prompter interface

    def ask(self, key: str, text: str, default: str | None = None, choices: list[str] | None = None,
            secret: bool = False, confident: bool = False) -> str:
        app = self.app
        if choices:
            sel = choices.index(default) if default in choices else 0
            i = app.choose(app.form_crumbs, [(c, "") for c in choices], body=self.body(_label(text)), sel=sel,
                           tail=True)
            ans = choices[i]
        else:
            ans = app.field(app.form_crumbs, _label(text), default or "", secret=secret, body=self.body())
        self._answered(_label(text), "•" * 6 if secret and ans else ans)
        if not secret:
            self.answers[key] = ans
        return ans

    def confirm(self, key: str, text: str, default: bool = False, confident: bool = False) -> bool:
        app = self.app
        i = app.choose(app.form_crumbs, [("Yes", ""), ("No", "")], body=self.body(text), sel=0 if default else 1,
                       tail=True)
        self._answered(text, "yes" if i == 0 else "no")
        self.answers[key] = "true" if i == 0 else "false"
        return i == 0

    def pick_many(self, key: str, text: str, options: list[str], defaults: list[str],
                  confident: bool = False) -> list[str]:
        app = self.app
        chosen = [d for d in defaults if d in options]
        typed = [d for d in defaults if d not in options]
        if not options:                                   # nothing to list (offline): names, typed
            raw = app.field(app.form_crumbs, _label(text) + " (names, comma-separated)", ", ".join(defaults),
                            body=self.body())
            got = W.pick(raw, [])
        else:
            ticked = {options.index(d) for d in chosen}
            idx, other = app.checklist(app.form_crumbs, [(o, "") for o in options], ticked,
                                       body=self.body(text + "  (space ticks, enter goes on)"),
                                       other="Another, not listed…")
            got = [options[i] for i in idx]
            if other:
                raw = app.field(app.form_crumbs, "Names not in the list (comma-separated)", ", ".join(typed),
                                body=self.body())
                got += [n for n in W.pick(raw, []) if n not in got]
            else:
                got += typed
        self._answered(_label(text), ", ".join(got) or "none")
        self.answers[key] = ", ".join(got)
        return got

    def say(self, text: str) -> None:
        self.log.append(text if text.startswith(" ") else "  " + text)


def _label(text: str) -> str:
    """`[spark:prod] host` -> `host`: the breadcrumb already says which connection. A tag without a colon
    (`[Finance BI] reports it changes`) names the subject, and stays."""
    if text.startswith("[") and "] " in text and ":" in text.split("] ", 1)[0]:
        return text.split("] ", 1)[1]
    return text


__all__ = ["TnpPrompter", "Back"]
