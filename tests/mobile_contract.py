"""The mobile contract, for tests: `contract/fleet-mobile.v<N>.schema.json` loaded once, a validator per record, the
fixture that holds every record the bridge writes to it, and the breaking-change guard (#598).

Imported by the bridge's own test modules for `contract_checked`, an autouse fixture: while a test runs, every
`textio.write_json` into a bridge folder's `outbox/`, `pairing.json` or a `processed/*.result.json` copy is validated
against the schema before it is written, so a field the bridge starts writing without the contract saying so fails
the test that wrote it.
"""
from __future__ import annotations
import functools
import json
import os
import sys
from collections import Counter

import pytest

from agentdata import textio
from agentdata.fleet import bridge

try:
    from jsonschema import Draft202012Validator
except ImportError as e:                                   # pragma: no cover - the dev extra carries it
    raise ImportError("jsonschema is in the dev extra: pip install -e \".[dev]\"") from e

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACT_DIR = os.path.join(REPO_ROOT, "contract")
SCHEMA_PATH = os.path.join(CONTRACT_DIR, f"fleet-mobile.v{bridge.MOBILE_CONTRACT}.schema.json")
RELEASED_PATH = os.path.join(CONTRACT_DIR, "released", f"fleet-mobile.v{bridge.MOBILE_CONTRACT}.schema.json")
EXAMPLES = os.path.join(CONTRACT_DIR, "examples")

#: What the laptop writes, by `$defs` name: the record kinds of the outbox and `pairing.json`.
OUTBOX_DEFS = ("attention", "approval", "decision_mirror", "notification", "heartbeat", "result", "pairing")
#: What FleetDecide writes into `inbox/`.
INBOX_DEFS = ("inbox_decision", "inbox_reply")

#: Every record `contract_checked` validated in this process, by `$defs` name.
SEEN: Counter = Counter()


def load(path: str = SCHEMA_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@functools.lru_cache(maxsize=None)
def _schema() -> dict:
    return load()


@functools.lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    """A validator for one `$defs` entry, resolved against the whole file."""
    schema = _schema()
    return Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{name}"})


def errors(record, name: str) -> list[str]:
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<record>'}: {e.message}"
            for e in validator(name).iter_errors(record)]


def check(record, name: str, where: str = "") -> None:
    found = errors(record, name)
    assert not found, f"{where or name} breaks the mobile contract ({name}):\n  " + "\n  ".join(found)


def def_for_path(path: str) -> str:
    """The `$defs` name of what the bridge writes at `path`, or "" for a file the contract does not cover."""
    parts = textio.norm_path(os.path.abspath(path)).split("/")
    name = parts[-1]
    if name == bridge.PAIRING:
        return "pairing"
    if len(parts) >= 2 and parts[-2] == bridge.PROCESSED and name.endswith(".result.json"):
        return "result"
    if len(parts) >= 3 and parts[-3] == bridge.OUTBOX:
        sub = parts[-2]
        if sub == "approvals":
            return "decision_mirror" if name.endswith(".decision.json") else "approval"
        return {"attention": "attention", "notifications": "notification", "heartbeat": "heartbeat",
                "results": "result"}.get(sub, "")
    return ""


@pytest.fixture(autouse=True)
def contract_checked(monkeypatch):
    """Validate every record the bridge writes, before it is written (see the module docstring)."""
    real = textio.write_json

    def checked(path, data, *args, **kwargs):
        name = def_for_path(str(path))
        # The bridge's writes only: a test that plants a stub in the outbox (the pruning tests) is not the producer.
        if name and sys._getframe(1).f_globals.get("__name__", "").startswith("agentdata."):
            check(data, name, where=textio.norm_path(str(path)))
            SEEN[name] += 1
        return real(path, data, *args, **kwargs)

    monkeypatch.setattr(textio, "write_json", checked)
    yield


# ---------------------------------------------------------------------------------------------- the guard
#
# A change to the schema is breaking when a record the released schema accepts could be refused by the current one:
# something removed (a `$defs` entry, a property, an enum value, a `oneOf`/`anyOf` branch, a `limits` key) or
# tightened (a new `required` name, a narrower `type`, a lower maximum or a higher minimum, a new or changed `pattern`
# or `const`, `additionalProperties` closed, a new `allOf` rule, a lower `limits` cap). Anything else is additive:
# a new optional property, a new enum value, a new `$defs` entry or record kind, a raised cap. A breaking change is
# allowed only with a version bump: `contract` above the released one (and so a new `v<N>` file).

_MAXIMA = ("maxLength", "maxItems", "maximum", "exclusiveMaximum", "maxProperties")
_MINIMA = ("minLength", "minItems", "minimum", "exclusiveMinimum", "minProperties")


def _types(schema: dict) -> set | None:
    t = schema.get("type")
    return None if t is None else set([t] if isinstance(t, str) else t)


def _compare(old, new, path: str, out: list[str]) -> None:
    if old is False or new is True or old == new:
        return
    if new is False:
        out.append(f"{path}: now refuses everything")
        return
    if old is True:
        old = {}
    for key in ("$defs", "properties"):
        for name, sub in (old.get(key) or {}).items():
            if name not in (new.get(key) or {}):
                out.append(f"{path}/{key}/{name}: removed")
            else:
                _compare(sub, new[key][name], f"{path}/{key}/{name}", out)
    # A property named for the first time was held by `additionalProperties` before: closed, anything it says now is
    # a loosening; open, anything it says now is a tightening.
    for name, sub in (new.get("properties") or {}).items():
        if name not in (old.get("properties") or {}):
            _compare(old.get("additionalProperties", True), sub, f"{path}/properties/{name}", out)
    added = set(new.get("required") or ()) - set(old.get("required") or ())
    if added:
        out.append(f"{path}/required: now requires {sorted(added)}")
    if "enum" in new:
        lost = [v for v in old["enum"] if v not in new["enum"]] if "enum" in old else new["enum"]
        if lost:
            out.append(f"{path}/enum: {'removed' if 'enum' in old else 'now only'} {lost}")
    if "const" in new and old.get("const", object()) != new["const"]:
        out.append(f"{path}/const: {old.get('const', '<none>')!r} -> {new['const']!r}")
    was, now = _types(old), _types(new)
    if now is not None and (was is None or not was <= now):
        out.append(f"{path}/type: {sorted(was) if was else 'any'} -> {sorted(now)}")
    for key in _MAXIMA:
        if key in new and (key not in old or new[key] < old[key]):
            out.append(f"{path}/{key}: {old.get(key, '<none>')} -> {new[key]}")
    for key in _MINIMA:
        if key in new and (key not in old or new[key] > old[key]):
            out.append(f"{path}/{key}: {old.get(key, '<none>')} -> {new[key]}")
    if "pattern" in new and old.get("pattern") != new["pattern"]:
        out.append(f"{path}/pattern: {old.get('pattern', '<none>')!r} -> {new['pattern']!r}")
    if "additionalProperties" in new:
        _compare(old.get("additionalProperties", True), new["additionalProperties"], f"{path}/additionalProperties",
                 out)
    for key in ("items", "contains", "if", "then", "else", "not"):
        if key in new:
            _compare(old.get(key, True), new[key], f"{path}/{key}", out)
    old_all, new_all = old.get("allOf") or [], new.get("allOf") or []
    for i, sub in enumerate(new_all):
        _compare(old_all[i] if i < len(old_all) else True, sub, f"{path}/allOf/{i}", out)
    for key in ("anyOf", "oneOf"):
        old_any, new_any = old.get(key) or [], new.get(key) or []
        if key in new and key not in old:
            out.append(f"{path}/{key}: added")
        for i, sub in enumerate(old_any):
            if i >= len(new_any):
                out.append(f"{path}/{key}/{i}: removed")
            else:
                _compare(sub, new_any[i], f"{path}/{key}/{i}", out)
    if "$ref" in new and old.get("$ref") != new["$ref"]:
        out.append(f"{path}/$ref: {old.get('$ref', '<none>')} -> {new['$ref']}")
    old_limits, new_limits = old.get("limits"), new.get("limits")
    if isinstance(old_limits, dict):
        for key, cap in old_limits.items():
            if key not in (new_limits or {}):
                out.append(f"{path}/limits/{key}: removed")
            elif new_limits[key] < cap:
                out.append(f"{path}/limits/{key}: {cap} -> {new_limits[key]}")


def breaking_changes(released: dict, current: dict) -> list[str]:
    """What `current` removes or tightens relative to `released`; empty when every change is additive."""
    out: list[str] = []
    _compare(released, current, "#", out)
    return out


def guard(released: dict, current: dict) -> list[str]:
    """The breaking changes that are not allowed: all of them, unless `current` raises the contract version."""
    if int(current.get("contract", 0)) > int(released.get("contract", 0)):
        return []
    return breaking_changes(released, current)
