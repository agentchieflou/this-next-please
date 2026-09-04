"""The two hypothesis profiles every `test_props_*.py` module shares.

`dev` (the default) keeps a local run to a couple of seconds; `ci` does the searching. Deadlines are
off in both: a Windows runner is slow enough that a per-example deadline produces flakes rather than
findings, and a flaky property test is one people learn to ignore.

Selected with `HYPOTHESIS_PROFILE`; CI sets it once for the whole workflow.
"""
from __future__ import annotations
import os

from hypothesis import HealthCheck, settings

CI = "ci"
DEV = "dev"
_loaded = False


def load_profiles() -> str:
    """Register both profiles once and select one. Returns the name selected."""
    global _loaded
    if not _loaded:
        settings.register_profile(CI, max_examples=200, deadline=None,
                                  suppress_health_check=[HealthCheck.function_scoped_fixture])
        settings.register_profile(DEV, max_examples=50, deadline=None,
                                  suppress_health_check=[HealthCheck.function_scoped_fixture])
        _loaded = True
    name = os.environ.get("HYPOTHESIS_PROFILE", DEV)
    settings.load_profile(name if name in (CI, DEV) else DEV)
    return name
