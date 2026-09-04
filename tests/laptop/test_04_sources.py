"""Section 4: data sources.

Passwords go to keyring, and the config file must stay safe to paste.
"""
from __future__ import annotations
import os
import shutil

import pytest

pytestmark = pytest.mark.laptop

def test_the_config_holds_no_secret():
    from agentdata import config

    cfg = config.load()
    config.assert_no_secrets(cfg)      # raises if anything credential-looking is stored


def test_sql_check_lints_a_real_query(run):
    import glob

    from agentdata import config

    sqls = glob.glob(os.path.join(".agent", "sql", "*.sql"))
    if not sqls:
        pytest.skip("no .agent/sql/*.sql on this laptop")
    dialect = "teradata" if config.project_facts().get("env") else "teradata"
    rc, out, _err = run("ad-sql-check", ["sql-check", "--dialect", dialect, sqls[0]])
    assert rc in (0, 2), out
