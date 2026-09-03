"""Truthful version reporting for ad-* commands."""
from __future__ import annotations
import argparse


def version_string() -> str:
    from .update import cli_state, version as get_version
    st = cli_state()
    v = get_version()
    commit = st.get("commit") or ("checkout" if st.get("editable") else "n/a")
    return f"agentdata {v} ({commit})"


def add_version(parser: argparse.ArgumentParser) -> None:
    """Add --version to parser if not already present."""
    # Check if --version is already in actions
    for action in parser._actions:
        if "--version" in action.option_strings:
            return
    parser.add_argument("--version", action="version", version=version_string())
