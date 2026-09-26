"""The desk's types: checked, never compiled (#236, plan-panes §G).

`tsconfig.json` puts `common.js` and `app.js` in one program and `tsc --noEmit` reads their JSDoc
against their code. CI runs it as a step of its own; the last test here runs the same command, so a
type error is also a failing test on a laptop that has Node. The rest need no Node at all: they hold
the pin in one place, keep the types the page declares in step with the records the server writes,
and keep the check from being quietly switched off a line at a time. `docs/desk-types.md` says what
is typed and what the check found.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from agentdata.fleet import serve as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "agentdata", "fleet", "static")

#: The compiler, exactly. A range would let a new release change what "clean" means under a
#: branch nobody touched; moving it is a commit that says so, in this file and in the workflow.
TYPESCRIPT = "7.0.2"
COMMAND = f"npx --yes -p typescript@{TYPESCRIPT} tsc -p tsconfig.json"


def _tsconfig() -> dict:
    """`tsconfig.json` as tsc reads it. JSONC; this one keeps its comments on lines of their own."""
    text = open(os.path.join(ROOT, "tsconfig.json"), encoding="utf-8").read()
    return json.loads("\n".join(line for line in text.splitlines()
                                if not line.lstrip().startswith("//")))


def _source(name: str) -> str:
    return open(os.path.join(STATIC, name), encoding="utf-8").read()


def _typedef(name: str) -> set[str]:
    """The property names a `@typedef {Object} <name>` in app.js declares."""
    js = _source("app.js")
    m = re.search(r"/\*\*((?:(?!\*/).)*?)@typedef \{Object\} " + re.escape(name) + r"\b(.*?)\*/",
                  js, re.S)
    assert m, f"no @typedef {{Object}} {name} in app.js"
    found = set()
    for line in m.group(2).splitlines():
        at = line.find("@property {")
        if at < 0:
            continue
        # The type can nest braces -- `Object<string, {cols: number, rows: number} | number>` --
        # so the name is whatever follows the brace that closes the first one.
        depth, i = 0, line.index("{", at)
        for i in range(i, len(line)):
            depth += {"{": 1, "}": -1}.get(line[i], 0)
            if depth == 0:
                break
        found.add(line[i + 1:].split()[0].strip("[]"))
    return found


def test_the_program_is_the_one_the_plan_names():
    """Checked and never emitted, strict off to begin with, and the files in one program: `app.js`
    is a classic script that reads `common.js`'s globals, and a global resolves only inside one.
    `picker.js` (#362) sits between them, as the pages load it."""
    cfg = _tsconfig()
    opts = cfg["compilerOptions"]
    assert opts["allowJs"] is True and opts["checkJs"] is True and opts["noEmit"] is True
    assert opts["strict"] is False, "turning strict on is a decision the plan leaves to its number"
    assert cfg["files"] == ["agentdata/fleet/static/common.js", "agentdata/fleet/static/picker.js",
                            "agentdata/fleet/static/app.js"]
    for rel in cfg["files"]:
        assert os.path.isfile(os.path.join(ROOT, rel)), rel
    # Dev-only: nothing about the check reaches the page or the wheel.
    assert not [n for n in os.listdir(STATIC) if n.endswith((".ts", ".map")) or n == "tsconfig.json"]


def test_ci_and_the_docs_run_the_same_pinned_compiler():
    """One version, said three times and held together here, so none of the three can move alone."""
    workflow = open(os.path.join(ROOT, ".github", "workflows", "tests.yml"), encoding="utf-8").read()
    assert COMMAND in workflow, "the CI step runs a different compiler from this test"
    docs = open(os.path.join(ROOT, "docs", "desk-types.md"), encoding="utf-8").read()
    assert COMMAND in docs
    assert COMMAND in open(os.path.join(ROOT, "tsconfig.json"), encoding="utf-8").read()
    assert len(set(re.findall(r"typescript@([0-9][^ \s`]*)", workflow + docs))) == 1


def test_nothing_in_the_program_is_silenced():
    """The number the plan asks for -- how many real defects the check found -- means nothing if a
    diagnostic can be switched off where it stands. A cast says what a value is; these say only
    "do not look", and the check is not allowed them."""
    for name in _tsconfig()["files"]:
        body = open(os.path.join(ROOT, name), encoding="utf-8").read()
        for pragma in ("@ts-nocheck", "@ts-ignore", "@ts-expect-error"):
            assert pragma not in body, f"{name} carries {pragma}"


def test_the_records_are_typed_as_the_server_writes_them(monkeypatch):
    """The page's types for the desk are only true while they name what `serve.py` sends. A field
    added to the window record, or to the desk, fails here until the typedef says what it is."""
    monkeypatch.setattr(S, "_desk_loaded", True)
    assert _typedef("DeskRecord") == set(S.desk_state())
    assert _typedef("WindowRecord") == set(S.WINDOW_FIELDS)
    assert _typedef("Arrangement") == set(S._blank_arrangement())
    # And what the page writes is a part of the record, never a field the server would drop.
    assert _typedef("WindowWrite") < set(S.WINDOW_FIELDS)
    # The tier widths the theme payload carries (#235), as the settings module reads them.
    from agentdata.fleet import settings as SET
    assert _typedef("Tiers") == set(SET.tiers({}))


@pytest.mark.network
@pytest.mark.real_home
def test_the_desk_type_checks():
    """`tsc --noEmit`, exactly as CI runs it. `npx` fetches the pinned compiler the first time, so
    this reaches the network until it is cached -- in the real home, where npm keeps its cache and
    a laptop keeps its proxy settings. `AGENTDATA_OFFLINE` says not to."""
    if os.environ.get("AGENTDATA_OFFLINE"):
        pytest.skip(f"AGENTDATA_OFFLINE is set, and `{COMMAND}` may have to fetch the compiler")
    npx = shutil.which("npx")
    if not npx:
        pytest.skip("no npx on this machine: the type check needs Node")
    p = subprocess.run([npx, *COMMAND.split()[1:]], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240, stdin=subprocess.DEVNULL)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0 and "error TS" not in out:
        # No diagnostic at all: npx never got as far as the compiler (no registry, no proxy). That
        # is a machine without the tool, not a page with a type error; CI's own step still fails.
        pytest.skip(f"typescript@{TYPESCRIPT} could not be fetched or run "
                    f"(set AGENTDATA_OFFLINE to skip without trying): {out.strip()[-300:]}")
    assert p.returncode == 0, out
