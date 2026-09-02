"""DPM (producer) -> data_remediation_foundry_DPM_fork (consumer) handoff contract. Skill: dpm-consumer-integration.

Invariants every module here enforces mechanically:
- the DPM run root is read, never written (SQLite opened `mode=ro&immutable=1`; a tree fingerprint before/after proves it);
- unsupported producer schema / manifest versions are refused before any work;
- generated artifacts land only beneath the consumer repository's governed artifact directory.
"""
from __future__ import annotations


class DpmError(Exception):
    """A contract refusal or a hard failure. `code` is machine-readable and is printed as `meta.refused`."""

    def __init__(self, code: str, msg: str, hint: str = ""):
        super().__init__(msg)
        self.code, self.msg, self.hint = code, msg, hint
