"""Properties of the bytes-in, bytes-out seam: decoding, writing, and output file names.

The example-based tests cover the encodings someone has already been bitten by. These generate the
ones nobody has thought of. Every seam here loses data if it is wrong, and loses it silently: a byte
decoded as the wrong character, a BOM that survives into a parser, a name Windows will not create.

`--hypothesis-seed` reproduces a failure exactly; a counter-example worth keeping is pinned with
`@example` so it runs every time rather than waiting for the generator to find it again.
"""
from __future__ import annotations
import os

import pytest

pytest.importorskip("hypothesis", reason="hypothesis is in the dev extra")
from hypothesis import assume, example, given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from agentdata import textio  # noqa: E402
from props_profiles import load_profiles  # noqa: E402

load_profiles()

# NUL cannot survive a text file, and a lone surrogate cannot be encoded at all: neither is a
# property of our code.
TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
    max_size=200,
)
INTERESTING = ["→ · ≤", "café", "𝄞 clef", "", " ", "tab\there", "a\nb", "a\r\nb", "ünïcödé"]


# ------------------------------------------------------------------------------------ decoding


@given(text=TEXT)
@example(text="→ · ≤")
@example(text="café")
@example(text="𝄞")
def test_utf8_round_trips(text):
    assert textio.decode(text.encode("utf-8")) == text


@given(text=TEXT)
@example(text="→ · ≤")
def test_a_utf8_bom_is_stripped_and_the_rest_survives(text):
    raw = "﻿".encode("utf-8") + text.encode("utf-8")
    assert textio.decode(raw).lstrip("﻿") == text


@given(text=TEXT)
@example(text="café")
def test_utf16_with_a_bom_round_trips(text):
    assume(text)
    for encoding in ("utf-16-le", "utf-16-be"):
        bom = b"\xff\xfe" if encoding.endswith("le") else b"\xfe\xff"
        assert textio.decode(bom + text.encode(encoding)) == text


@given(text=TEXT)
def test_the_decoder_never_raises_and_never_gives_up(text):
    """Whatever the bytes, a string comes back -- readers are the last line before a traceback."""
    for raw in (text.encode("utf-8"), text.encode("utf-16-le"), b"\x81\x8d" + text.encode("utf-8")):
        got = textio.decode(raw)
        assert isinstance(got, str)


# ------------------------------------------------------------------------------------- writing


# The strategy is passed by keyword: hypothesis fills the *rightmost* parameters positionally, so
# `@given(TEXT)` here would hand the text to `tmp_path` and then look for a `text` fixture.
@given(text=TEXT)
@example(text="a\r\nb\r\n")
@example(text="→ · ≤\n")
def test_write_then_read_round_trips_with_lf(text, tmp_path):
    path = str(tmp_path / "round.txt")
    textio.write_text(path, text)
    assert textio.read_text(path) == text.replace("\r\n", "\n") or textio.read_text(path) == text
    with open(path, "rb") as f:
        raw = f.read()
    assert not raw.startswith(b"\xef\xbb\xbf"), "our writer never emits a BOM"


# Deliberately not `@given`: a function-scoped `monkeypatch` is *not* undone between hypothesis
# examples, so the patched `os.replace` would still be raising when the second example set the file
# up. A fixed list of inputs wants `parametrize` anyway.
@pytest.mark.parametrize("text", INTERESTING)
def test_a_failed_write_leaves_the_old_content_intact(text, tmp_path, monkeypatch):
    """The point of writing through a .tmp: a crash must not truncate what was there."""
    path = str(tmp_path / "atomic.txt")
    textio.write_text(path, "original\n")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    monkeypatch.setattr(textio, "_replace_with_retry", boom)
    with pytest.raises(OSError):
        textio.write_text(path, text)
    assert textio.read_text(path) == "original\n"


# --------------------------------------------------------------------------------------- names


RESERVED_OR_ODD = st.one_of(
    st.sampled_from(["nul", "CON", "aux.tsv", "com1", "lpt9.log", "normal.tsv", "a b.tsv"]),
    st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=1, max_size=20),
)


@given(name=RESERVED_OR_ODD)
@example(name="nul.tsv")
@example(name="CON")
def test_safe_name_is_idempotent_and_never_empty(name):
    once = textio.safe_name(name)
    assert once, "a name must never become empty"
    assert textio.safe_name(once) == once, "safe_name must be idempotent"
    assert not any(ch in once for ch in '<>:"/\\|?*')


@given(name=RESERVED_OR_ODD)
def test_safe_name_never_leaves_a_reserved_device_name(name):
    stem = textio.safe_name(name).split(".", 1)[0].lower()
    assert stem not in textio.RESERVED_NAMES, f"{name!r} -> a name Windows will not create"
