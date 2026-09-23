"""A proven need for a visual that nothing native or certified can draw: logged, never built.

A non-certified visual in a report is invisible to every viewer on a tenant that renders certified
visuals only, and one reached production that way. So the routing never builds one to deliver a
report. When every native route and every Microsoft-certified visual has been tried, and each lacks
something the requirement needs, the need is written down here: a candidate the team may build and
publish to AppSource, where it can be certified.

Saying "can't" costs a reason per route, and the command refuses without one. The routes are the
sections of `skills/pbi-custom-visual/references/delivery-routes.md`, id for id.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from typing import Any

import yaml

from .. import textio

ROUTES: tuple[tuple[str, str], ...] = (
    ("N1", "data-label fields: Value, Detail and Title, per series"),
    ("N2", "format strings: three sections, or a dynamic format string"),
    ("N3", "SVG measure: Image URL in a table, matrix, card or slicer"),
    ("N4", "analytics and conditional formatting: reference lines, error bars, bands, colour rules, icons"),
    ("N5", "composition: combo chart, small multiples, field parameters, visual calculations, tooltip pages"),
    ("N6", "paginated report visual: labels and shapes from expressions"),
    ("N7", "R or Python visual, where the tenant enables them"),
    ("C1", "Deneb: a Vega or Vega-Lite specification in the certified visual"),
    ("C2", "another Microsoft-certified visual"),
)
ROUTE_IDS = tuple(r for r, _ in ROUTES)

# A reason has to name what the requirement needs that the route lacks. These say nothing of the kind.
THIN = {"n/a", "na", "no", "none", "nope", "-", "tried", "tried it", "not possible", "impossible", "can't",
        "cant", "cannot", "can not", "doesn't work", "does not work", "didn't work", "not supported",
        "unsupported", "no good", "not applicable", "won't work", "will not work"}
MIN_REASON = 20

DEFAULT_ROOT = os.path.join(".agent", "pbiviz", "candidates")
STATUSES = ("logged", "building", "submitted", "certified", "declined")


class CandidateError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str):
        super().__init__(message)
        self.code = code
        self.hint = hint


def _thin(reason: str) -> bool:
    text = " ".join(reason.split()).strip().strip(".").lower()
    return len(text) < MIN_REASON or text in THIN


def validate(requirement: str, tried: dict[str, str]) -> None:
    """Refuse a candidate that has not earned its "can't"."""
    if not requirement.strip():
        raise CandidateError("candidate_no_requirement", "the requirement is empty",
                             "write what a viewer must see, e.g. \"variance label at each bar end\"")
    unknown = sorted(set(tried) - set(ROUTE_IDS))
    if unknown:
        raise CandidateError("candidate_unknown_route", f"no route is called {', '.join(unknown)}",
                             f"the routes are {', '.join(ROUTE_IDS)}")
    missing = [r for r in ROUTE_IDS if r not in tried]
    if missing:
        raise CandidateError(
            "candidate_unproven", f"no reason recorded for {', '.join(missing)}",
            "try each route first; then pass --tried <id>=\"<what the requirement needs that it lacks>\" for every "
            "one (skill pbi-custom-visual, references/delivery-routes.md)")
    thin = [r for r in ROUTE_IDS if _thin(tried[r])]
    if thin:
        raise CandidateError(
            "candidate_reason_too_thin", f"the reason for {', '.join(thin)} does not say what the route lacks",
            f"name what the requirement needs that the route cannot do, in {MIN_REASON} characters or more")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-") or "candidate"


def record(requirement: str, tried: dict[str, str], *, where: str | None = None, ticket: str | None = None,
           tenant: str | None = None, root: str = DEFAULT_ROOT, today: str | None = None) -> dict[str, Any]:
    """Write `<root>/<yyyymmdd>-<slug>.md` and return what was written."""
    validate(requirement, tried)
    day = today or _dt.date.today().isoformat()
    os.makedirs(root, exist_ok=True)
    base = f"{day.replace('-', '')}-{_slug(requirement)}"
    path, n = os.path.join(root, base + ".md"), 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(root, f"{base}-{n}.md")

    q = lambda s: json.dumps(s, ensure_ascii=False)  # noqa: E731 -- a JSON string is a YAML scalar
    front = [f"requirement: {q(requirement)}", f"logged: {day}",
             "status: logged        # the team's to change: " + " | ".join(STATUSES[1:]),
             f"tenant: {q(tenant or 'unrecorded')}"]
    if ticket:
        front.append(f"ticket: {q(ticket)}")
    if where:
        front.append(f"where: {q(where)}")
    cell = lambda s: " ".join(s.split()).replace("|", "\\|")  # noqa: E731
    rows = [f"| {rid} | {name} | {cell(tried[rid])} |" for rid, name in ROUTES]
    body = "\n".join(["---", *front, "---", f"# Candidate: {requirement}", "",
                      "Logged because no native route and no Microsoft-certified visual meets the requirement. A",
                      "candidate is a proposal to build a visual and publish it to AppSource for certification. It",
                      "is never a visual in a report: until it is certified, a tenant that renders certified visuals",
                      "only shows viewers an error in its place.", "",
                      "| Route | | Why it does not meet the requirement |", "|---|---|---|", *rows, ""])
    textio.write_text(path, body)
    return {"ok": True, "path": textio.norm_path(path), "requirement": requirement, "routes": len(rows),
            "status": "logged"}


def listing(root: str = DEFAULT_ROOT) -> list[dict[str, Any]]:
    """Every candidate under `root`, oldest first, from each file's front matter."""
    rows = []
    if not os.path.isdir(root):
        return rows
    for name in sorted(os.listdir(root)):
        if not name.endswith(".md"):
            continue
        path = os.path.join(root, name)
        text = textio.read_text(path)
        meta: dict[str, Any] = {}
        if text.startswith("---"):
            head = text.split("---", 2)[1]
            meta = yaml.safe_load(head) or {}
        rows.append({"logged": str(meta.get("logged", "")), "status": meta.get("status", ""),
                     "requirement": meta.get("requirement", ""), "ticket": meta.get("ticket", ""),
                     "path": textio.norm_path(path)})
    return rows
