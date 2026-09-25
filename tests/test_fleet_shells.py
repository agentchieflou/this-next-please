"""The two IDE shells, checked from the Python side.

Neither can be compiled here — there is no JDK on this machine and packaging a `.vsix` is CI's job.
What *can* be checked, and matters more than compilation, is that they stayed shells: the moment
one grows its own idea of what an agent's state means, there are two answers to every question and
no way for an operator to tell which is current.

So the rule "a shell contains no rule logic" is an executable check here rather than a line on a
review checklist, and the two constants that have to agree with the server are read from the source
rather than trusted.

The spike's desktop window (#353, `ide/desktop/`) is held to the same per-file rules. The IDE checks
are the two IDE shells' own, and pywebview is never imported here: a fake stands in for it.
"""
from __future__ import annotations
import ast
import importlib.util
import json
import os
import re
import sys
import time
import types

import pytest

from agentdata.fleet import agentstate, notify as N, opener as O, serve as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE = os.path.join(ROOT, "ide", "vscode")
JETBRAINS = os.path.join(ROOT, "ide", "jetbrains")
DESKTOP = os.path.join(ROOT, "ide", "desktop")
DOC = os.path.join(ROOT, "docs", "fleet-ide.md")


def read(*parts) -> str:
    return open(os.path.join(*parts), encoding="utf-8").read()


def shell_sources() -> dict[str, str]:
    out = {}
    for base, suffix in ((VSCODE, ".ts"), (JETBRAINS, ".kt")):
        for dirpath, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ("node_modules", "out", "build", ".gradle")]
            for name in names:
                if name.endswith(suffix):
                    path = os.path.join(dirpath, name)
                    out[os.path.relpath(path, ROOT).replace("\\", "/")] = read(path)
    return out


def shells() -> dict[str, str]:
    """One blob per shell. Several checks are about a shell as a whole -- one file reading a field
    and another using it is the normal shape, not a violation."""
    joined = {"vscode": "", "jetbrains": ""}
    for path, body in shell_sources().items():
        joined["vscode" if "/vscode/" in path else "jetbrains"] += body
    return joined


def desktop_sources() -> dict[str, str]:
    """The spike's desktop window (#353). Only the per-file rule checks read it: it is a host, not
    an IDE shell, so `shells()` and the escape check stay the two IDE shells' own."""
    out = {}
    for dirpath, dirs, names in os.walk(DESKTOP):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            if name.endswith(".py"):
                path = os.path.join(dirpath, name)
                out[os.path.relpath(path, ROOT).replace("\\", "/")] = read(path)
    return out


# ------------------------------------------------------------------------ they are still shells


def test_both_shells_exist_and_were_found():
    found = shell_sources()
    assert any(p.endswith(".ts") for p in found), "no TypeScript sources found"
    assert any(p.endswith(".kt") for p in found), "no Kotlin sources found"


def test_no_shell_decides_what_an_agent_state_means():
    """`agentstate.classify` is the only place that turns events into a state. A shell that
    recognised `blocked` or `waiting_approval` would be a second implementation of the fold, and it
    would drift -- silently, and only for the people using that IDE."""
    # `needs_human` is excluded: it is also the name of a *field the server computes*, and reading
    # that field is the opposite of the thing being forbidden. The next test asserts they do read it.
    # `running`, `done` and `error` are words too common to grep for meaningfully.
    states = set(agentstate.STATES) - {"running", "done", "error", "needs_human"}
    for path, body in {**shell_sources(), **desktop_sources()}.items():
        for state in sorted(states):
            assert f'"{state}"' not in body, f"{path} names the agent state {state!r}"
        # ...and `needs_human` may be read as a field, never compared as a state.
        assert f'== "needs_human"' not in body, f"{path} compares against a state"


def test_no_shell_decides_when_to_interrupt_a_person():
    """Cooldowns, quiet hours and idle thresholds are `notify.py`'s. A shell that held one would
    hold a *different* one within a release."""
    for path, body in {**shell_sources(), **desktop_sources()}.items():
        for word in ("cooldown", "quiet_hours", "quietHours", "idle_minutes", "idleMinutes"):
            assert word not in body, f"{path} carries a notification rule ({word})"
        assert "needs_the_human" not in body and "needsTheHuman" not in body, path


def test_a_shell_reads_the_servers_answer_rather_than_counting_for_itself():
    """`needs_human` per repo is computed by the server. The shells' status counts must be that
    number, not a re-derivation from the tiles."""
    for name, body in shells().items():
        assert "needingHuman" in body, f"the {name} shell shows no count at all"
        assert "needs_human" in body, f"the {name} shell counts without reading the server's field"


def test_the_only_event_kind_a_shell_acts_on_is_notify():
    """Acceptance criterion, executable. A shell that started reacting to `denied` or
    `phase_changed` would be deciding what they mean."""
    for path, body in {**shell_sources(), **desktop_sources()}.items():
        if "event: " not in body and '"notify"' not in body:
            continue
        acted_on = set(re.findall(r'== "([a-z_]+)"', body)) & set(N.RULES)
        assert not acted_on, f"{path} acts on {sorted(acted_on)}"
        assert '"notify"' in body, f"{path} reads the stream but never checks for notify frames"


def test_a_refusal_is_shown_in_the_servers_own_words():
    """Rewording a refusal in a shell gives the operator two explanations of one rule, and only one
    of them gets updated when the rule changes."""
    for path, body in shell_sources().items():
        if "/api/start" not in body:
            continue
        assert "hint" in body, f"{path} drops the server's hint"
        assert "error" in body, f"{path} drops the server's error text"


# ------------------------------------------------------------- they agree with the server


def test_both_shells_speak_the_contract_the_server_serves():
    """A shell built against an older contract mis-renders quietly. The number is checked at
    runtime by each shell; that it *starts* equal is checked here."""
    ts = read(VSCODE, "src", "fleet.ts")
    kt = read(JETBRAINS, "src", "main", "kotlin", "com", "agentdata", "fleet", "Fleet.kt")
    assert re.search(rf"CONTRACT\s*=\s*{S.CONTRACT}\b", ts), "the VS Code shell is a different age"
    assert re.search(rf"CONTRACT\s*=\s*{S.CONTRACT}\b", kt), "the JetBrains shell is a different age"


def test_both_shells_look_for_the_fleet_where_the_fleet_is():
    for body in (read(VSCODE, "src", "fleet.ts"),
                 read(JETBRAINS, "src", "main", "kotlin", "com", "agentdata", "fleet", "Fleet.kt")):
        assert "AGENTDATA_FLEET_DIR" in body, "the override the tests and the docs both use"
        assert ".agentdata" in body and "fleet" in body
        assert "serve.json" in body


def test_both_shells_fall_back_to_the_module_form():
    """`ad-fleet` is a console script and is frequently not on PATH -- the single most common way
    this package looks broken when it is merely unfound."""
    for body in (read(VSCODE, "src", "fleet.ts"),
                 read(JETBRAINS, "src", "main", "kotlin", "com", "agentdata", "fleet", "Fleet.kt")):
        assert "ad-fleet" in body
        assert '"agentdata"' in body and '"fleet"' in body, "no `python -m agentdata fleet` fallback"


def test_both_shells_use_the_one_anchor_for_focusing_a_tile():
    """`#tile=<repo>` is also what the Windows toasts use. Two ways to say "show me that one" is
    one way too many."""
    for body in (read(VSCODE, "src", "extension.ts"),
                 read(JETBRAINS, "src", "main", "kotlin", "com", "agentdata", "fleet",
                      "FleetToolWindow.kt")):
        assert "#tile=" in body


def test_each_shell_names_its_own_window_on_the_desk():
    """#230: every window without `?w=` shared the `main` record, so the PyCharm tool window and a
    browser tab followed each other's clicks -- and a zoom in one re-opened an agent in the other."""
    names = {"vscode": 'WINDOW = "vscode"', "jetbrains": 'WINDOW = "pycharm"'}
    for shell, body in shells().items():
        assert names[shell] in body, f"{shell} does not name its window"
        assert "windowUrl(" in body, f"{shell} loads the page without its window name"
    assert "w=<host>" in read(DOC)


def test_open_all_leaves_exactly_the_windows_the_shells_name():
    """`ad-fleet open --all` leaves each IDE view's window to its IDE, and `IDE_WINDOWS` is how it
    knows them. Read from the source rather than trusted: a shell that renamed its window would
    otherwise be given a browser tab sharing its record the next time the operator opened them all.
    The spike's desktop window (#353) is such a host too."""
    named = {m.group(1) for body in [*shells().values(), *desktop_sources().values()]
             for m in re.finditer(r'\bWINDOW = "([^"]+)"', body)}
    assert named == set(O.IDE_WINDOWS)


def test_both_shells_ping_before_starting_a_second_server():
    for body in (read(VSCODE, "src", "fleet.ts"),
                 read(JETBRAINS, "src", "main", "kotlin", "com", "agentdata", "fleet", "Fleet.kt")):
        assert "/api/ping" in body
        assert "startServer" in body


# ---------------------------------------------------------- the spike's desktop window (#353)


FLEET_WINDOW = os.path.join(DESKTOP, "fleet_window.py")
RECORD = {"url": "http://127.0.0.1:8765/?t=tok", "token": "tok", "port": 8765}


def fleet_window() -> types.ModuleType:
    """The spike, loaded from its path the way `python ide/desktop/fleet_window.py` runs it: it is
    not in the wheel, so there is no module name to import it by."""
    spec = importlib.util.spec_from_file_location("fleet_window", FLEET_WINDOW)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def imported_on_load(node: ast.AST) -> set[str]:
    """The modules a file imports as it loads -- at the top, under an `if` or a `try` -- and not
    those that only calling one of its functions imports."""
    names: set[str] = set()
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Import):
            names.update(alias.name.split(".")[0] for alias in child.names)
        elif isinstance(child, ast.ImportFrom) and child.module:
            names.add(child.module.split(".")[0])
        names |= imported_on_load(child)
    return names


def test_the_desktop_window_is_a_shell():
    """#353: the spike finds its desk the way `ad-fleet open` does and names its own window record,
    and CI and the wheel never need pywebview: only `main()` imports it. It starts no process
    itself -- `current_desk` starts the desk."""
    assert "ide/desktop/fleet_window.py" in desktop_sources(), "the rule checks above cannot see it"
    body = read(FLEET_WINDOW)
    assert "opener.current_desk(" in body
    assert 'WINDOW = "desktop"' in body
    tree = ast.parse(body)
    assert "webview" not in imported_on_load(tree), "pywebview is imported when the file loads"
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert any(isinstance(n, ast.Import) and any(a.name == "webview" for a in n.names)
               for n in ast.walk(main)), "main() is where the spike imports pywebview"
    assert "subprocess" not in body


def test_the_desktop_window_without_pywebview_says_how_to_get_it(monkeypatch, capsys):
    """No pywebview: one line saying how to get it, and exit 2 -- before a desk is started that
    there would be no window to show."""
    monkeypatch.setitem(sys.modules, "webview", None)  # `import webview` raises ImportError
    monkeypatch.setattr(O, "current_desk",
                        lambda *a, **k: pytest.fail("started a desk with no window to show it in"))
    assert fleet_window().main([]) == 2
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and "pip install pywebview" in out[0], out


def test_the_desktop_window_keeps_its_geometry_in_the_fleet_dir(monkeypatch, tmp_path):
    """Where the window was closed is where it reopens, and the file moves with
    `AGENTDATA_FLEET_DIR` like the rest of the fleet. A monitor left of the main one has a
    negative x, and that is a place too."""
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path))
    spike = fleet_window()
    assert spike._saved_geometry() == {}, "nothing saved yet: pywebview's own size, centred"
    spike._save_geometry(types.SimpleNamespace(x=-1270, y=40, width=1200, height=900))
    saved = json.loads((tmp_path / "desktop.json").read_text(encoding="utf-8"))
    assert saved == {"x": -1270, "y": 40, "width": 1200, "height": 900}
    assert spike._saved_geometry() == saved
    (tmp_path / "desktop.json").write_text("{not json", encoding="utf-8")
    assert spike._saved_geometry() == {}, "a file it cannot read never keeps the window shut"


class FakeEvent:
    """`window.events.<name>` in pywebview: handlers join with `+=`, and a `closing` handler that
    returns False keeps the window open."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def set(self) -> list:
        return [handler() for handler in self.handlers]


def fake_webview(opened: list, sessions: list) -> types.ModuleType:
    """Just enough pywebview for `main()`. A window keeps how it was made, and each `start()` plays
    the next of `sessions`: what the operator does with the window before closing it."""
    webview = types.ModuleType("webview")

    def create_window(title, url, **made_with):
        events = types.SimpleNamespace(closing=FakeEvent(), minimized=FakeEvent(),
                                       restored=FakeEvent(), maximized=FakeEvent())
        window = types.SimpleNamespace(title=title, url=url, made_with=made_with, started_with={},
                                       x=0, y=0, width=800, height=600, events=events)
        opened.append(window)
        return window

    def start(**started_with):
        window = opened[-1]
        window.started_with = started_with
        sessions.pop(0)(window)
        assert False not in window.events.closing.set(), "a closing handler kept the window open"

    webview.create_window, webview.start = create_window, start
    return webview


def moved_to_another_monitor(window) -> None:
    window.x, window.y, window.width, window.height = 1930, 12, 1200, 1000


def minimised(window) -> None:
    """Where Windows parks a minimised window, and the size of its title bar."""
    window.events.minimized.set()
    window.x, window.y, window.width, window.height = -32000, -32000, 160, 28


def test_the_desktop_window_hosts_the_desk_as_its_own_window(monkeypatch, tmp_path, capsys):
    """What `main()` asks of pywebview, against a fake: the desk as `w=desktop` in a window titled
    `fleet` on Edge's engine, `/probe` as shell `desktop` with `--probe`, the start time on one
    line, and the geometry saved on close and given back on the next start -- unless it was closed
    minimised. Only the laptop (#354) shows that pywebview and WebView2 do what the fake does."""
    monkeypatch.setenv("AGENTDATA_FLEET_DIR", str(tmp_path))
    opened: list = []
    sessions = [moved_to_another_monitor, minimised]
    monkeypatch.setitem(sys.modules, "webview", fake_webview(opened, sessions))
    monkeypatch.setattr(O, "current_desk", lambda *a, **k: (RECORD, "started"))

    before = time.time()
    spike = fleet_window()
    assert spike.main([]) == 0
    after = time.time()
    desk = opened[-1]
    assert (desk.title, desk.url) == ("fleet", O.url_of(RECORD, window="desktop"))
    assert "w=desktop" in desk.url
    assert desk.started_with.get("gui") == "edgechromium"
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1, lines
    started = float(re.search(r"\d+\.\d+", lines[0]).group(0))
    assert before <= started <= after, "the line carries the script's own time.time()"

    assert spike.main(["--probe"]) == 0
    probe = opened[-1]
    assert probe.url == O.page_urls(RECORD, "probe", {"shell": "desktop"})[0]
    where = {"x": 1930, "y": 12, "width": 1200, "height": 1000}
    assert {k: probe.made_with.get(k) for k in where} == where, "it reopens where it was closed"
    assert spike._saved_geometry() == where, "closed minimised, it keeps the place it had before"


# --------------------------------------------------------------------- nothing mangled them


# What each language actually accepts after a backslash in a string literal. A regex literal has
# its own alphabet and is skipped.
KOTLIN_ESCAPES = set("tbnr'\"\\$u")
TS_ESCAPES = set("tbnrfv'\"\\`0xu")
REGEXY = ("Regex(", "RegExp(", "= /", "(/", "split(/", "match(/", "replace(/")


def test_no_source_carries_a_broken_escape():
    """A fast pre-filter for one specific way these files get damaged.

    Writing a file through a heredoc in some tooling eats one level of backslash, so a regex like
    `[0-9]+` written as a shorthand class arrives with its backslash gone. Kotlin rejects the
    result outright; TypeScript quietly reinterprets it. The Kotlin's only other check is a
    ten-minute CI job, so a one-second local one earns its place -- this exact fault reached CI.

    **It catches invalid escape *letters* and nothing more.** A mangled char literal like
    `replace('<backslash>', '/')` still looks like a legal escaped quote to any check this cheap,
    and only the compiler sees it. That case is CI's; this is the one that fails in a second.
    """
    problems = []
    for path, body in shell_sources().items():
        allowed = KOTLIN_ESCAPES if path.endswith(".kt") else TS_ESCAPES
        for number, line in enumerate(body.splitlines(), 1):
            if any(marker in line for marker in REGEXY):
                continue
            for match in re.finditer(r"\\(.)", line):
                if match.group(1) not in allowed:
                    problems.append(f"{path}:{number}: backslash-{match.group(1)}")
    assert not problems, "escape sequences no compiler here would accept:\n  " + "\n  ".join(problems)


# ------------------------------------------------------------------- the packaging is coherent


def test_every_command_the_manifest_declares_is_registered():
    """A command in `package.json` with no handler is an entry in the palette that does nothing."""
    manifest = json.loads(read(VSCODE, "package.json"))
    declared = {c["command"] for c in manifest["contributes"]["commands"]}
    source = read(VSCODE, "src", "extension.ts")
    registered = set(re.findall(r'registerCommand\("([\w.]+)"', source))
    assert declared == registered, f"declared {sorted(declared)}, registered {sorted(registered)}"


def test_every_setting_the_manifest_declares_is_read():
    manifest = json.loads(read(VSCODE, "package.json"))
    declared = {k.split(".", 1)[1] for k in manifest["contributes"]["configuration"]["properties"]}
    source = read(VSCODE, "src", "extension.ts")
    for key in sorted(declared):
        assert f'"{key}"' in source, f"the setting fleet.{key} is declared and never read"


def test_the_extension_declares_the_view_it_provides():
    manifest = json.loads(read(VSCODE, "package.json"))
    views = {v["id"] for v in manifest["contributes"]["views"]["fleet"]}
    assert "fleet.dashboard" in views
    assert 'registerWebviewViewProvider("fleet.dashboard"' in read(VSCODE, "src", "extension.ts")


def test_the_plugin_manifest_is_well_formed_and_wires_what_it_names():
    import xml.etree.ElementTree as ET

    path = os.path.join(JETBRAINS, "src", "main", "resources", "META-INF", "plugin.xml")
    root = ET.parse(path).getroot()
    classes = {e.get("factoryClass") or e.get("serviceImplementation") or e.get("class")
               for e in root.iter() if e.tag in ("toolWindow", "applicationService", "action")}
    classes.discard(None)
    assert classes, "the manifest names no classes"
    for fqn in sorted(classes):
        source = os.path.join(JETBRAINS, "src", "main", "kotlin", *fqn.split(".")[:-1])
        name = fqn.split(".")[-1]
        found = any(f"class {name}" in read(source, f) for f in os.listdir(source) if f.endswith(".kt"))
        assert found, f"{fqn} is declared in plugin.xml and not defined"

    groups = {e.get("id") for e in root.iter("notificationGroup")}
    assert "agentdata.fleet" in groups
    kotlin = read(JETBRAINS, "src", "main", "kotlin", "com", "agentdata", "fleet", "FleetToolWindow.kt")
    assert 'getNotificationGroup("agentdata.fleet")' in kotlin, "the balloon group is not the one declared"


def test_jcef_is_guarded_rather_than_assumed():
    """An IDE started without JCEF shows a blank tool window, which reads as a broken plugin. The
    actual answer -- use the browser -- is one sentence, so it should be that sentence."""
    kotlin = read(JETBRAINS, "src", "main", "kotlin", "com", "agentdata", "fleet", "FleetToolWindow.kt")
    assert "JBCefApp.isSupported()" in kotlin
    assert "ad-fleet open" in kotlin, "the fallback must name the command that works"


def test_ci_builds_both_shells_and_windows_too():
    """The plugin build is the only verification the Kotlin gets: nobody can compile it on the
    laptop this was written on. Windows is in the matrix because the IntelliJ Gradle plugin is
    where path bugs live."""
    workflow = read(ROOT, ".github", "workflows", "tests.yml")
    assert "ide · vscode extension" in workflow and "ide · jetbrains plugin" in workflow
    assert "windows-latest" in workflow.split("jetbrains-plugin:")[1]
    assert "buildPlugin" in workflow


def test_neither_shell_is_shipped_in_the_python_wheel():
    body = read(ROOT, "pyproject.toml")
    assert "ide/" not in body, "the shells are IDE artefacts, not package data"


def test_a_shell_posts_paths_and_nothing_else():
    """Step 8 (#167): a host with file paths may hand them over, and may not decide anything.

    The temptation is for a shell to work out which checkout a file belongs to, or to skip a file
    it thinks the agent should not read. Both would be a second place the rule lives, and the two
    would drift. So the shells post to `/api/scope` and name no file type, no size, and no
    repository rule.
    """
    for name, body in shells().items():
        assert "/api/scope" in body, f"{name} has no way to give the agent a file"
        for forbidden in (".tmdl", ".pbix", ".xlsx", "max_mb", " MB", "scope_wrong_repo",
                          "ls-files", "jira_project"):
            assert forbidden not in body, f"{name} names {forbidden!r}: that decision is the server's"


def test_the_doc_carries_the_contract_a_third_host_would_follow():
    text = read(DOC)
    assert "What a shell must do" in text
    for step in ("serve.json", "/api/ping", "/api/events", "#tile=", "contract"):
        assert step in text, f"the contract does not mention {step}"
    assert "no rule logic" in text
    assert "Unverified" in text or "unverified" in text, "the signing question must stay open"
