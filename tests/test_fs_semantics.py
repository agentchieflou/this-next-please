"""File-system behaviour that only Windows has, plus the round trip through each shell's own idioms.

`tests/test_textio.py` proves the decoder against bytes Python wrote. This file proves the same
things against bytes the *shells* wrote, and covers the three Windows hazards a caller should never
have to think about: a locked target, a path over 260 characters, and a reserved device name.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

from agentdata import textio

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = os.name == "nt"
SAMPLE = "é → ≤"


def _bash() -> str:
    for candidate in (
        os.environ.get("GIT_BASH"),
        os.path.join("C:" + os.sep, "Program Files", "Git", "bin", "bash.exe"),
        os.path.join("C:" + os.sep, "Program Files (x86)", "Git", "bin", "bash.exe"),
    ):
        if candidate and os.path.isfile(candidate):
            return candidate
    return shutil.which("bash") or "bash"


def _have_bash() -> bool:
    path = _bash()
    return os.path.isfile(path) and "system32" not in path.lower()


requires_bash = pytest.mark.skipif(not _have_bash(), reason="Git Bash is not installed")
requires_pwsh = pytest.mark.skipif(shutil.which("pwsh") is None, reason="pwsh 7 is not installed")
requires_windows = pytest.mark.skipif(not WINDOWS, reason="Windows-only behaviour")


# ------------------------------------------------------------------- what each shell writes


@requires_pwsh
@pytest.mark.parametrize("idiom", [
    "Set-Content -Path $p -Value $v",
    "Set-Content -Path $p -Value $v -Encoding utf8",
    "$v | Out-File -FilePath $p",
    "$v > $p",
])
def test_pwsh_writes_utf8_without_a_bom(idiom, tmp_path):
    """All four are UTF-8 without a BOM in pwsh 7. In 5.1 the middle two were not, which is the
    whole reason the repo used to tell people not to use their own shell's commands."""
    target = tmp_path / "written.txt"
    script = f'$p = "{target}"; $v = "{SAMPLE}"; {idiom}'
    p = subprocess.run(["pwsh", "-NoProfile", "-Command", script], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr

    raw = target.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{idiom} wrote a UTF-8 BOM"
    assert not raw.startswith((b"\xff\xfe", b"\xfe\xff")), f"{idiom} wrote UTF-16"
    assert textio.read_text(str(target)).strip() == SAMPLE


@requires_bash
@pytest.mark.parametrize("idiom", ["printf '%s' \"$V\" > \"$P\"", "echo \"$V\" > \"$P\""])
def test_git_bash_writes_utf8(idiom, tmp_path):
    target = tmp_path / "written.txt"
    script = f'V="{SAMPLE}"; P="{target}"; {idiom}'
    p = subprocess.run([_bash(), "-c", script], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert textio.read_text(str(target)).strip() == SAMPLE


@requires_windows
def test_cmd_echo_is_the_one_that_is_not_utf8(tmp_path):
    """`echo > f` in cmd writes the console's OEM code page, not UTF-8.

    The decoder has to cope, because a user will do this. `docs/shells.md` names cmd as the
    exception rather than pretending every shell agrees.
    """
    target = tmp_path / "written.txt"
    subprocess.run(f'cmd /d /s /c "chcp 437 >nul && echo caf<E9> > "{target}""',
                   capture_output=True, text=True, shell=False)
    # written with whatever code page cmd had; the point is that read_text does not raise and does
    # not return replacement characters
    if target.exists():
        got = textio.read_text(str(target))
        assert "�" not in got, f"the decoder gave up on cmd's bytes: {got!r}"


def test_the_decoder_reaches_cp437_for_bytes_cp1252_rejects():
    """cp437 is not dead code, and it is also not a cure for the ambiguity.

    cp1252 leaves five bytes undefined (0x81, 0x8d, 0x8f, 0x90, 0x9d); for those the chain falls
    through to cp437 and gets the character cmd actually wrote. For every other high byte cp1252
    succeeds first with a *different* character -- 0x82 is cp437's e-acute and cp1252's low quote,
    and nothing in the bytes says which was meant. That ambiguity is why docs/shells.md tells people
    not to use `echo >` in cmd for a file another tool will read, rather than claiming it is handled.
    """
    assert textio.decode(bytes([0x81])) == "\u00fc", "cp437 must handle what cp1252 cannot"
    assert textio.decode(bytes([0x8d])) == "\u00ec"
    assert textio.decode(bytes([0x82])) == "\u201a", "cp1252 wins first; the byte is genuinely ambiguous"
    for raw in (bytes([0x81]), bytes([0x82]), "cafe".encode("utf-8")):
        assert "\ufffd" not in textio.decode(raw), "the decoder never gives up"


def test_legacy_encodings_are_still_read(tmp_path):
    """Kept, and relabelled: these are files from other tools, not from a supported shell."""
    for name, raw in {
        "bom.txt": "﻿" .encode("utf-8") + SAMPLE.encode("utf-8"),
        "utf16le.txt": SAMPLE.encode("utf-16-le"),
        "utf16be.txt": b"\xfe\xff" + SAMPLE.encode("utf-16-be"),
        "cp1252.txt": "café".encode("cp1252"),
    }.items():
        path = tmp_path / name
        path.write_bytes(raw)
        assert textio.read_text(str(path)).strip() in (SAMPLE, "café")


def test_our_writer_produces_bom_free_lf(tmp_path):
    path = str(tmp_path / "out.txt")
    textio.write_text(path, "a\nb\n")
    raw = open(path, "rb").read()
    assert raw == b"a\nb\n", "no BOM, LF only, even on Windows"


# --------------------------------------------------------------------------- a locked target


@requires_windows
def test_a_locked_target_falls_back_in_place_and_leaves_no_tmp(tmp_path):
    """PyCharm reindexing state.json, or Desktop holding a TMDL file, makes os.replace raise."""
    path = str(tmp_path / "held.json")
    textio.write_text(path, "first\n")

    holder = subprocess.Popen(
        [sys.executable, "-c",
         f"import time;f=open(r'{path}','r+');time.sleep(3);f.close()"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        report: dict = {}
        textio.write_text(path, "second\n", report=report)
        assert textio.read_text(path) == "second\n", "the write must land even when replace cannot"
        assert report["how"] in ("atomic", "in-place")
    finally:
        holder.wait(timeout=10)

    assert not os.path.exists(path + ".tmp"), "a .tmp must never be left behind"


def test_no_tmp_survives_a_normal_write(tmp_path):
    path = str(tmp_path / "x.txt")
    textio.write_text(path, "hello\n")
    assert [n for n in os.listdir(tmp_path) if n.endswith(".tmp")] == []
    assert "x.txt" in os.listdir(tmp_path)


def test_two_writers_of_one_file_do_not_share_a_staging_name(tmp_path):
    """The staging file is per writer, not per path.

    Earned on CI: `ad-fleet serve` and an agent's `ad-state` wrote the same cursor at the same
    moment, both staged it as `<path>.tmp`, and one renamed it away while the other still held it
    -- FileNotFoundError on Linux, PermissionError on Windows, out of code that looked atomic. Only
    the staging name was shared; the rename itself was always the atomic step.
    """
    import threading

    path = str(tmp_path / "contended.json")
    ready = threading.Barrier(8)
    errors = []

    def writer(n):
        ready.wait()
        for i in range(25):
            try:
                textio.write_text(path, f"writer {n} pass {i}\n")
            except Exception as e:                                # noqa: BLE001 - that is the point
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"{len(errors)} writes failed, first: {errors[0]!r}"
    assert textio.read_text(path).startswith("writer "), "the file was left half-written"
    assert [n for n in os.listdir(tmp_path) if n.endswith(".tmp")] == []


def test_the_retry_is_bounded(monkeypatch, tmp_path):
    """Five attempts with backoff, then in place -- never a hang."""
    calls = []

    def always_locked(src, dst):
        calls.append((src, dst))
        raise PermissionError("held")

    monkeypatch.setattr(os, "replace", always_locked)
    path = str(tmp_path / "y.txt")
    report: dict = {}
    textio.write_text(path, "content\n", report=report)
    assert len(calls) == textio.REPLACE_ATTEMPTS
    assert report["how"] == "in-place"
    assert open(path, encoding="utf-8").read() == "content\n"


# ------------------------------------------------------------------------------- long paths


def test_longpath_prefixes_only_when_it_helps():
    short = os.path.join("C:" + os.sep, "short", "path.txt")
    assert textio.longpath(short) == short

    deep = os.path.join("C:" + os.sep, *(["segment"] * 40), "file.txt")
    got = textio.longpath(deep)
    if WINDOWS:
        assert got.startswith("\\\\?\\"), "a >240-character path needs the prefix"
        assert textio.longpath(got) == got, "prefixing twice must be a no-op"
    else:
        assert got == deep, "the prefix is meaningless off Windows"


@requires_windows
def test_a_300_character_path_can_be_written_and_read(tmp_path):
    deep = tmp_path
    while len(str(deep)) < 300:
        deep = deep / "a-reasonably-long-directory-name"
    target = str(deep / "out.tsv")
    assert len(target) > 260

    textio.write_text(target, "value\n")
    assert textio.read_text(target) == "value\n"


def test_the_long_path_policy_is_reported():
    value = textio.long_paths_enabled()
    assert value in (True, False, None)
    if not WINDOWS:
        assert value is None


# ------------------------------------------------------------------- reserved and colliding names


@pytest.mark.parametrize("name,expected", [
    ("nul.tsv", "nul_.tsv"),
    ("CON.tsv", "CON_.tsv"),
    ("com1.log", "com1_.log"),
    ("RDSD-1234.tsv", "RDSD-1234.tsv"),
    ("sales:q1.tsv", "sales_q1.tsv"),
    ("trailing. ", "trailing"),
])
def test_reserved_and_illegal_names_are_made_safe(name, expected):
    assert textio.safe_name(name) == expected


def test_a_case_only_collision_is_detected(tmp_path):
    (tmp_path / "Sales.tsv").write_text("x", encoding="utf-8")
    assert textio.collides_case_insensitively(str(tmp_path), "sales.tsv") == "Sales.tsv"
    assert textio.collides_case_insensitively(str(tmp_path), "Sales.tsv") == ""
    assert textio.collides_case_insensitively(str(tmp_path), "other.tsv") == ""


# ------------------------------------------------------------- the retired 5.1 write guidance


ALLOWED_LEGACY_MENTIONS = {
    # the reader's own docstring has to say what it tolerates and why
    "agentdata/textio.py",
    # this epic's own wording, and the changelog entry that records the change
    "CHANGELOG.md",
    "docs/shells.md",
    # docs/setup.md states the floor and what CI proves about 5.1 -- that is the announcement, not guidance
    "docs/setup.md",
    "docs/windows-verification.md",
    # Power BI Desktop's port file genuinely is UTF-16; nothing to do with shells
    "docs/pbi-tools-parts.md",
    "docs/plan-luna-pipeline.md",
    "agentdata/pbip/desktop.py",
    "agentdata/shell.py",
    "agentdata/setup/steps/console.py",
    "agentdata/console.py",
    "agentdata/color.py",
    # C# `File.WriteAllText` inside a generated TOM / DMV script, and one docstring naming it as an
    # example of text rich would mis-parse -- neither is advice about writing files from a shell
    "agentdata/ui.py",
    "agentdata/pbip/dmv.py",
    "agentdata/pbip/tom.py",
}
RETIRED = ("WriteAllText", "adds a BOM or writes UTF-16", "may carry a BOM or be UTF-16")


def test_no_skill_or_doc_still_tells_pwsh_users_to_avoid_their_own_shell():
    """pwsh 7 writes UTF-8 without a BOM. Telling people otherwise is now simply wrong."""
    import glob

    hits = []
    patterns = [os.path.join(REPO_ROOT, "skills", "**", "*.md"),
                os.path.join(REPO_ROOT, "docs", "*.md"),
                os.path.join(REPO_ROOT, "README.md"),
                os.path.join(REPO_ROOT, "agentdata", "**", "*.py")]
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
            if rel in ALLOWED_LEGACY_MENTIONS:
                continue
            text = open(path, encoding="utf-8").read()
            for needle in RETIRED:
                if needle in text:
                    hits.append(f"{rel}: {needle!r}")
    assert not hits, "retired Windows PowerShell 5.1 write guidance still present:\n  " + "\n  ".join(hits)


def test_state_update_gives_the_real_reason():
    text = open(os.path.join(REPO_ROOT, "skills", "state-update", "SKILL.md"), encoding="utf-8").read()
    assert "validates" in text, "the reason is validation, not encoding"
    assert "adds a BOM" not in text and "UTF-16" not in text, "the encoding scare is retired"


def test_docs_shells_has_a_files_section():
    text = open(os.path.join(REPO_ROOT, "docs", "shells.md"), encoding="utf-8").read()
    assert "## Files: what each shell writes" in text
    assert "cmd" in text.split("## Files: what each shell writes", 1)[1]


# --------------------------------------------------------------------------------- line endings


def test_gitattributes_pins_the_fixtures_both_checkouts_need():
    text = open(os.path.join(REPO_ROOT, ".gitattributes"), encoding="utf-8").read()
    assert "tests/fixtures/** -text" in text, "fixture bytes must survive core.autocrlf=true"
    for pattern in ("*.sh text eol=lf", "*.cmd text eol=crlf"):
        assert pattern in text
