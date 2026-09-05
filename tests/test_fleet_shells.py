"""The two IDE shells, checked from the Python side.

Neither can be compiled here — there is no JDK on this machine and packaging a `.vsix` is CI's job.
What *can* be checked, and matters more than compilation, is that they stayed shells: the moment
one grows its own idea of what an agent's state means, there are two answers to every question and
no way for an operator to tell which is current.

So the rule "a shell contains no rule logic" is an executable check here rather than a line on a
review checklist, and the two constants that have to agree with the server are read from the source
rather than trusted.
"""
from __future__ import annotations
import json
import os
import re

import pytest

from agentdata.fleet import agentstate, notify as N, serve as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VSCODE = os.path.join(ROOT, "ide", "vscode")
JETBRAINS = os.path.join(ROOT, "ide", "jetbrains")
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
    for path, body in shell_sources().items():
        for state in sorted(states):
            assert f'"{state}"' not in body, f"{path} names the agent state {state!r}"
        # ...and `needs_human` may be read as a field, never compared as a state.
        assert f'== "needs_human"' not in body, f"{path} compares against a state"


def test_no_shell_decides_when_to_interrupt_a_person():
    """Cooldowns, quiet hours and idle thresholds are `notify.py`'s. A shell that held one would
    hold a *different* one within a release."""
    for path, body in shell_sources().items():
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
    for path, body in shell_sources().items():
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


def test_both_shells_ping_before_starting_a_second_server():
    for body in (read(VSCODE, "src", "fleet.ts"),
                 read(JETBRAINS, "src", "main", "kotlin", "com", "agentdata", "fleet", "Fleet.kt")):
        assert "/api/ping" in body
        assert "startServer" in body


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


def test_the_doc_carries_the_contract_a_third_host_would_follow():
    text = read(DOC)
    assert "What a shell must do" in text
    for step in ("serve.json", "/api/ping", "/api/events", "#tile=", "contract"):
        assert step in text, f"the contract does not mention {step}"
    assert "no rule logic" in text
    assert "Unverified" in text or "unverified" in text, "the signing question must stay open"
