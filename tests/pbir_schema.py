"""Validate a PBIR file against Microsoft's published JSON schema.

The schemas are vendored under `agentdata/pbip/schema/fabric/`, each at the path its URL names
(`https://developer.microsoft.com/json-schemas/<path>`), so a `$ref` resolves to a file on disk and
nothing is fetched: a `$ref` to a schema that is not vendored raises instead of reaching the network.
"""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

try:
    from jsonschema import Draft7Validator
    from referencing import Registry, Resource
except ImportError as e:  # pragma: no cover - environment guard
    raise ImportError("jsonschema is in the dev extra: pip install -e \".[dev]\"") from e

SCHEMAS = Path(__file__).resolve().parent.parent / "agentdata" / "pbip" / "schema"
BASE = "https://developer.microsoft.com/json-schemas/"
REPORT_3_1 = BASE + "fabric/item/report/definition/report/3.1.0/schema.json"


@lru_cache(maxsize=1)
def registry() -> Registry:
    resources = []
    for path in sorted((SCHEMAS / "fabric").rglob("*.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents)
        # A $ref names the file's URL, and the refs inside a file resolve against its own $id -- which can
        # differ: filterConfiguration/1.2.0/schema-embedded.json says it is "schema.embedded.json".
        for uri in {BASE + path.relative_to(SCHEMAS).as_posix(), contents.get("$id")} - {None}:
            resources.append((uri, resource))
    return Registry().with_resources(resources)


def errors(instance: object, schema_url: str = REPORT_3_1) -> list[str]:
    """Every violation of `schema_url` in `instance`, as `<JSON path>: <message>`; empty when it validates."""
    reg = registry()
    validator = Draft7Validator(reg.contents(schema_url), registry=reg)
    found = sorted(validator.iter_errors(instance), key=lambda e: (e.json_path, e.message))
    return [f"{e.json_path}: {e.message}" for e in found]
