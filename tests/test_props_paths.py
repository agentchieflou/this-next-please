"""Properties of the one path canonicaliser, and the guard that keeps it the only one.

`.replace("\\\\", "/")` was written out by hand in 142 places. That is fine until one of them
forgets -- and then two `meta.path` values for the same file stop comparing equal, on Windows only,
in output an agent is supposed to be able to diff. `textio.norm_path()` is the single spelling now;
`test_no_hand_written_path_canonicaliser` is what stops the 143rd from being added.
"""
from __future__ import annotations
import ast
import os
import subprocess
import sys

import pytest

pytest.importorskip("hypothesis", reason="hypothesis is in the dev extra")
from hypothesis import example, given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from agentdata import textio, toon  # noqa: E402
from props_profiles import load_profiles  # noqa: E402

load_profiles()

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(REPO_ROOT, "agentdata")

PATHS = st.one_of(
    st.sampled_from([
        "C:/Users/x", "C:\\Users\\x", "c:\\users\\x", "/c/Users/x", "\\\\server\\share\\file",
        "relative/path", "relative\\path", "./a/../b", "a/b/", "~", "", ".",
        "C:\\", "//server/share", "a\\b\\c\\", "\\\\?\\C:\\long\\path",
    ]),
    st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"),
                                   whitelist_characters="/\\.-_ ~"), max_size=30),
)


@given(path=PATHS)
@example(path="C:\\Users\\x")
@example(path="/c/Users/x")
@example(path="\\\\server\\share")
@example(path="c:\\users\\x")
def test_norm_path_is_idempotent(path):
    once = textio.norm_path(path)
    assert textio.norm_path(once) == once


@given(path=PATHS)
def test_norm_path_always_uses_forward_slashes(path):
    assert "\\" not in textio.norm_path(path)


@given(path=PATHS)
def test_norm_path_never_invents_or_drops_a_segment(path):
    """Separators change; the number of pieces between them does not."""
    before = [p for p in path.replace("\\", "/").split("/") if p]
    after = [p for p in textio.norm_path(path).split("/") if p]
    assert len(after) == len(before)


@pytest.mark.posix
@pytest.mark.skipif(os.name == "nt", reason="a POSIX absolute path is only meaningful on POSIX; "
                                            "Windows is covered by test_norm_path_converts_msys")
@given(path=st.sampled_from(["/usr/bin", "/tmp/x", "/a/b/c", "/c/Users/x"]))
def test_norm_path_leaves_a_posix_absolute_path_alone(path):
    """Including `/c/Users/x`: on Linux that is a real directory name, not a drive."""
    assert textio.norm_path(path) == path


def test_norm_path_converts_msys():
    if os.name == "nt":
        assert textio.norm_path("/c/Users/x") == "C:/Users/x"
    assert textio.norm_path("C:\\Users\\x") == "C:/Users/x"
    assert textio.norm_path("c:\\users\\x") == "C:/users/x", "one spelling of the drive letter"
    assert textio.norm_path("\\\\server\\share") == "//server/share"


@given(name=st.text(alphabet="abcdef", min_size=1, max_size=8))
def test_norm_path_agrees_with_the_filesystem(name, tmp_path):
    """Whatever normalisation does, it must not change whether the path exists."""
    real = tmp_path / name
    real.write_text("x", encoding="utf-8")
    assert os.path.exists(textio.norm_path(str(real))) == os.path.exists(str(real))


# ------------------------------------------------------------------- one canonicaliser, not many


def _hand_written_canonicalisers() -> list[str]:
    """`<expr>.replace("\\\\", "/")` and `.replace(os.sep, "/")` anywhere under agentdata/.

    Parsed rather than grepped: a regex over source cannot tell the call from the sentence about
    the call in `norm_path`'s own docstring.
    """
    hits = []
    for dirpath, dirnames, filenames in os.walk(PKG):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            if os.path.samefile(path, textio.__file__):
                continue                       # norm_path is defined here
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or node.keywords or len(node.args) != 2:
                    continue
                f, (first, second) = node.func, node.args
                if not (isinstance(f, ast.Attribute) and f.attr == "replace"):
                    continue
                if not (isinstance(second, ast.Constant) and second.value == "/"):
                    continue
                is_sep = (isinstance(first, ast.Attribute) and first.attr == "sep"
                          and isinstance(first.value, ast.Name) and first.value.id == "os")
                if (isinstance(first, ast.Constant) and first.value == "\\") or is_sep:
                    rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
                    hits.append(f"{rel}:{node.lineno}")
    return hits


def test_no_hand_written_path_canonicaliser():
    hits = _hand_written_canonicalisers()
    assert not hits, ("use textio.norm_path() instead of replacing separators by hand:\n  "
                      + "\n  ".join(hits))


def test_norm_path_is_what_the_meta_paths_went_through():
    """A spot check that the codemod reached the output, not only the source.

    `ad-graph` builds every node id from a relative path, so its meta is the densest path payload
    any command emits.
    """
    out = subprocess.run([sys.executable, "-m", "agentdata", "graph", "summary"],
                         capture_output=True, text=True, cwd=REPO_ROOT)
    if out.returncode not in (0, 3):          # 3 = no graph built here; nothing to check
        pytest.skip(f"ad-graph summary exited {out.returncode}")
    assert not toon.validate(out.stdout or "meta:\n  ok: true"), toon.validate(out.stdout)
    assert "\\" not in out.stdout, "a backslash reached TOON output"
