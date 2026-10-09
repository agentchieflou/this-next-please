"""Validate a PBIR file against Microsoft's published JSON schema: `agentdata.pbip.schema_check`, re-exported.

The logic lives in the package now (`ad-pbip pbir patch` and `ad-pbip check` run it); this name stays so every test
keeps `import pbir_schema as S`. jsonschema is the `pbi` extra and is in `dev` too: a test that cannot import it fails
rather than skips, because that check is what stands between a change and a report Desktop refuses to open.
"""
from __future__ import annotations

from agentdata.pbip import schema_check as _SC
from agentdata.pbip.schema_check import (  # noqa: F401
    BASE, DESKTOP_2157, REPORT_3_1, SCHEMAS, available, errors, file_errors, install_hint, instance_errors,
    registry, vendored,
)

if not _SC.available():  # pragma: no cover - environment guard
    raise ImportError('jsonschema is in the dev extra: pip install -e ".[dev]"')
