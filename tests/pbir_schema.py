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

from agentdata.pbip import pbir as P

SCHEMAS = Path(__file__).resolve().parent.parent / "agentdata" / "pbip" / "schema"
BASE = "https://developer.microsoft.com/json-schemas/"
REPORT_3_1 = BASE + "fabric/item/report/definition/report/3.1.0/schema.json"
# What Power BI Desktop 2.157 writes, kind -> schema URL (the table is agentdata.pbip.pbir.DESKTOP_SCHEMAS)
DESKTOP_2157 = {kind: P.schema_url(kind) for kind in P.DESKTOP_SCHEMAS}


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


def vendored(schema_url: str) -> bool:
    return (SCHEMAS / schema_url.removeprefix(BASE)).is_file()


def errors(instance: object, schema_url: str = REPORT_3_1) -> list[str]:
    """Every violation of `schema_url` in `instance`, as `<JSON path>: <message>`; empty when it validates."""
    reg = registry()
    validator = Draft7Validator(reg.contents(schema_url), registry=reg)
    found = sorted(validator.iter_errors(instance), key=lambda e: (e.json_path, e.message))
    return [f"{e.json_path}: {e.message}" for e in found]


def file_errors(path: str | Path) -> list[str]:
    """Every violation of the schema a PBIR file names in its own `$schema`; that schema must be vendored."""
    instance = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    url = instance.get("$schema")
    if not url or not vendored(url):
        raise LookupError(f"{path}: its $schema {url!r} is not vendored under {SCHEMAS / 'fabric'}")
    return errors(instance, url)
