"""Hardlink or copy, probed rather than assumed, and recorded rather than remembered.

A mapped drive letter says nothing about whether `CreateHardLink` works on the other end of it: most SMB shares do not
implement it, and a hardlink cannot cross volumes in any case. So the answer is measured on the volume the structure
will live on, and the fallback is not an error.
"""
from __future__ import annotations
import os

import pytest

from agentdata.sorting import links as L


def test_the_probe_answers_and_leaves_nothing_behind(tmp_path):
    target = tmp_path / "probe-here"
    answer = L.probe(str(target))
    assert answer["writable"] is True
    assert isinstance(answer["hardlinks"], bool) and answer["evidence"]
    assert list(target.iterdir()) == [], "the probe cleans up after itself"


def test_a_directory_that_cannot_be_written_says_so_rather_than_raising(tmp_path):
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        answer = L.probe(str(blocked))
    finally:
        blocked.chmod(0o700)
    if getattr(os, "geteuid", lambda: -1)() == 0 or os.name == "nt":
        pytest.skip("running as root or on Windows, which ignores the mode bits this test sets")
    assert answer["writable"] is False and "cannot create a file" in answer["evidence"]


def test_place_hardlinks_when_it_can(tmp_path):
    if not L.probe(str(tmp_path))["hardlinks"]:
        pytest.skip("this volume has no hardlinks")
    source = tmp_path / "a.pdf"
    source.write_text("bytes\n", encoding="utf-8")
    target = tmp_path / "views" / "a.pdf"
    assert L.place(str(source), str(target)) == L.HARDLINK
    assert source.stat().st_ino == target.stat().st_ino


def test_place_falls_back_to_a_copy_and_says_which_it_did(tmp_path, monkeypatch):
    """The fallback is the SMB case, and it is not an error -- it is a different storage bill."""
    def no_links(*a, **k):
        raise OSError("this share does not do hardlinks")

    monkeypatch.setattr(os, "link", no_links)
    source = tmp_path / "a.pdf"
    source.write_text("bytes\n", encoding="utf-8")
    target = tmp_path / "views" / "a.pdf"

    assert L.place(str(source), str(target)) == L.COPY
    assert target.read_text(encoding="utf-8") == "bytes\n"
    assert source.stat().st_ino != target.stat().st_ino


def test_asking_for_a_copy_never_makes_a_link(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_text("bytes\n", encoding="utf-8")
    target = tmp_path / "copies" / "a.pdf"
    assert L.place(str(source), str(target), prefer=L.COPY) == L.COPY
    assert source.stat().st_ino != target.stat().st_ino
