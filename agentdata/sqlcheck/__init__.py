"""Dialect pre-flight lint for the SQL an agent is about to run (Teradata 20, Hive, Impala, Oracle).
Errors block the query with a fix; warnings ride along in meta.warnings. See rules.py."""
from .rules import DIALECTS, Finding, check, to_toon  # noqa: F401
