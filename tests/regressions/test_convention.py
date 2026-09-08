"""The regression convention itself.

Every file here records a real failure seen on a real machine, so that it cannot come back quietly.
A file without the symptom quoted and the issue linked is a test whose reason will be forgotten,
which is how a "flaky" test gets deleted a year later.
"""
from __future__ import annotations
import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = re.compile(r"^test_(\d{8})_(bash|pwsh|cmd|powershell|any)_[a-z0-9_]+\.py$")


def regression_files():
    return [p for p in sorted(glob.glob(os.path.join(HERE, "test_*.py")))
            if os.path.basename(p) != "test_convention.py"]


def test_there_are_regressions_recorded():
    assert regression_files(), "the first three from 2026-09-03 should be here"


def test_every_regression_names_its_date_and_shell():
    for path in regression_files():
        assert NAME.match(os.path.basename(path)), (
            f"{os.path.basename(path)}: name it test_<yyyymmdd>_<shell>_<short>.py so the failure's "
            "date and shell are visible without opening it")


def test_every_regression_quotes_the_symptom_and_links_the_issue():
    for path in regression_files():
        text = open(path, encoding="utf-8").read()
        doc = text.split('"""', 2)[1] if text.count('"""') >= 2 else ""
        assert doc.strip(), f"{os.path.basename(path)} has no module docstring"
        assert "Symptom" in doc, f"{os.path.basename(path)}: quote what the machine actually printed"
        assert "github.com/agentchieflou/this-next-please/issues/" in doc, \
            f"{os.path.basename(path)}: link the issue"
