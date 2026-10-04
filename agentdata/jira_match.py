"""Which of the operator's open tickets a prompt belongs to -- scored, never judged.

The operator, 2026-10-03: "if we give an agent a prompt and it's not related to a ticket we're
working on, the agent goes and finds what ticket it's most related to and provides the user with an
option at least to ticket the work underneath that ticket or to just create another ticket ... The
goal is more so that we can still prompt our agents however we want. But if we're starting work
that's not ticketed yet, to remind the user to ticket the work."

Everything here is pure: the board rows in, a verdict and the one `ad-state ask` line out. The
scoring is word overlap, deliberately -- a cheap model asked "does this prompt fit RDSD-118?" says
yes to anything, and a number it did not compute is a number it cannot be wrong about. The rows
are the fleet's own board (`agentdata/fleet/board.py`: `assignee = currentUser() AND statusCategory
!= Done`, cached), so the agent reads what the operator's desk shows and nothing more.

Verdicts, in the order they are tried:

| verdict | when | `next` |
|---|---|---|
| `named`  | the prompt names a key | `continue` -- that ticket |
| `create` | the operator answered `new` to the last ticket question and no ticket is active | `jira-create` |
| `active` | the active ticket scores as well as any other, and scores at all | `continue` |
| `match`  | the best candidate shares enough words (`MATCH_SCORE` or `MATCH_SHARED`) | `ask-and-continue`: assume it |
| `weak`   | something overlaps, not enough to assume | `ask-and-continue` (`optional`) or `ask-and-stop` (`required`) |
| `none`   | nothing overlaps, or no open tickets | the same two, with `new` and `none` as the choices |

A `match` is assumed rather than asked, because re-scoping is reversible (`ad-state answer`
with another key moves the work) and a stop on every one-off prompt is the friction this exists
to remove. The assumption shows on the tile with the runner-up keys as choices.
"""
from __future__ import annotations
import re

KEY = re.compile(r"\b([A-Z][A-Z0-9_]+-\d+)\b")
WORD = re.compile(r"[a-z0-9]+")
# Function words and the words every ticket in a reporting team's Jira shares. A match on "report"
# or "update" alone is not a match.
STOP = frozenset("""
a an and are as at be by for from has have in into is it its of on or that the this to was were will
with we our you your i me my us they them their he she his her not no yes do does did done can could
should would may might must shall just also then than so if when where which who what how why all any
each per via into onto over under about after before between during without within up down out off
please make let get use new old same other some more most much many few one two three
ticket tickets jira issue issues story stories task tasks epic epics work working update updates
updated change changes changed fix fixes fixed add adds added remove removes removed check checks
checked review reviews reviewed report reports reporting data
""".split())
MATCH_SCORE = 0.5        # overlap coefficient at which a candidate is assumed
MATCH_SHARED = 3         # or this many shared words, whichever comes first
ACTIVE_SHARED = 1        # the active ticket keeps the work when it shares anything and nothing beats it
CANDIDATES = 3           # keys offered as choices
NONE_WORDS = ("none", "untracked", "no ticket", "no")


def tokens(text: str) -> set[str]:
    """Lower-case words of three letters or more, minus the stop list, plural `s` dropped."""
    out = set()
    for word in WORD.findall(str(text or "").lower()):
        if len(word) < 3 or word in STOP:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.add(word)
    return out


def keys_in(text: str) -> list[str]:
    """Every Jira key the prompt names, in order, once each."""
    seen: list[str] = []
    for key in KEY.findall(str(text or "").upper()):
        if key not in seen:
            seen.append(key)
    return seen


def score(prompt_words: set[str], row: dict) -> tuple[float, list[str]]:
    """(overlap coefficient, the shared words). Coefficient = shared / the smaller side, so a
    long prompt against a six-word summary is scored on the summary's words."""
    mine = tokens(" ".join(str(row.get(k) or "") for k in ("summary", "type", "labels", "components")))
    if not prompt_words or not mine:
        return 0.0, []
    shared = sorted(prompt_words & mine)
    return round(len(shared) / min(len(prompt_words), len(mine)), 2), shared


def rank(prompt: str, rows: list[dict], *, active: str | None = None) -> list[dict]:
    """Every row scored and sorted: best first, the active ticket first among equals."""
    words = tokens(prompt)
    named = keys_in(prompt)
    out = []
    for row in rows:
        key = str(row.get("key") or "")
        pts, shared = score(words, row)
        if key in named:
            pts, shared = 1.0, [key.lower()] + shared
        out.append({"key": key, "status": str(row.get("status") or ""), "summary": str(row.get("summary") or ""),
                    "score": pts, "shared": shared, "active": key == (active or "")})
    out.sort(key=lambda r: (-r["score"], -len(r["shared"]), not r["active"], r["key"]))
    return out


def last_ticket_answer(state: dict) -> str:
    """What the operator last said to a `kind: ticket` question, or ""."""
    for q in reversed(state.get("answered_questions") or []):
        if isinstance(q, dict) and q.get("kind") == "ticket" and not q.get("superseded"):
            return str(q.get("answer") or "").strip()
    return ""


def verdict(prompt: str, rows: list[dict], *, active: str | None = None, policy: str = "optional",
            last_answer: str = "") -> dict:
    """The decision, and the one `ad-state ask` line that carries it out."""
    ranked = rank(prompt, rows, active=active)
    named = keys_in(prompt)
    policy = (policy or "optional").strip().lower()
    top = ranked[0] if ranked else None
    out = {"verdict": "none", "next": "continue", "ticket": active or "", "ask": "",
           "candidates": ranked[:CANDIDATES], "policy": policy, "why": ""}
    if named:
        out.update({"verdict": "named", "ticket": named[0], "why": f"the request names {named[0]}"})
        return out
    if not active and last_answer.lower() == "new":
        out.update({"verdict": "create", "next": "jira-create",
                    "why": "the operator answered `new` to the last ticket question"})
        return out
    mine = next((r for r in ranked if r["active"]), None)
    if mine and len(mine["shared"]) >= ACTIVE_SHARED and mine["score"] >= (top["score"] if top else 0):
        out.update({"verdict": "active", "why": f"{active} shares {', '.join(mine['shared'])} and nothing beats it"})
        return out
    choices = [r["key"] for r in ranked[:CANDIDATES]]
    if top and (top["score"] >= MATCH_SCORE or len(top["shared"]) >= MATCH_SHARED):
        question = f"This reads like {top['key']} ({top['summary'][:60]}). Track it there?"
        out.update({"verdict": "match", "next": "ask-and-continue", "ticket": top["key"],
                    "ask": ask_line(question, choices, assume=top["key"]),
                    "why": f"{top['key']} shares {', '.join(top['shared'])} (score {top['score']:g})"})
        return out
    kind = "weak" if top and top["score"] > 0 else "none"
    question = ("No open ticket matches this work. Track it under one?" if kind == "none"
                else f"Nothing fits well; nearest is {top['key']}. Track it under a ticket?")
    if policy == "required":
        out.update({"verdict": kind, "next": "ask-and-stop", "ticket": "",
                    "ask": ask_line(question, choices), "why": "ticket_policy is required"})
    else:
        out.update({"verdict": kind, "next": "ask-and-continue", "ticket": "",
                    "ask": ask_line(question, choices, assume="none"),
                    "why": "untracked work; the reminder stays on the tile"})
    return out


def ask_line(question: str, choices: list[str], *, assume: str = "") -> str:
    """The exact `ad-state ask` to run. Quoting is the agent's shell's; the question holds no quotes."""
    parts = ["ad-state ask", _q(question), "--kind ticket"]
    for key in choices:
        parts += ["--choice", key]
    parts += ["--choice", "new", "--choice", "none"]
    if assume:
        parts += ["--assume", assume]
    return " ".join(parts)


def _q(text: str) -> str:
    return '"' + str(text).replace('"', "'") + '"'


def is_key(text: str) -> str:
    """The key an answer names, upper-cased, or ""."""
    m = KEY.fullmatch(str(text or "").strip().upper())
    return m.group(1) if m else ""


def is_none(text: str) -> bool:
    return str(text or "").strip().lower() in NONE_WORDS
