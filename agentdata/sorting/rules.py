"""The rules file: what claims a document, and where it goes. An input, never something built in here.

A rule set is small on purpose. It says three things per rule -- what to match, which folder to file it under, and what
to call it there -- and everything it can say is derived from the *name* of a file, because that is all `plan` is
allowed to look at.

    {
      "version": 1,
      "into": "sorted",
      "rules": [
        {"name": "loan-packets",
         "match": {"glob": "*.pdf", "regex": "^(?P<loan>\\\\d{8})[-_ ]"},
         "into": "loans/{loan}"}
      ]
    }

`glob` is matched against the file's name, `regex` is searched in it (Python syntax, named groups become placeholders).
A rule with both must satisfy both. First matching rule wins, so the order in the file is the precedence -- stated
rather than sorted by specificity, because a human reading a heap's plan has to be able to predict it.

Placeholders available to `into` and `rename`: every named group of the rule's `regex`, plus `{stem}`, `{ext}`,
`{original}` (the file's own name), `{ext_nodot}`, and the date parts of the file's mtime -- `{year}`, `{month}`,
`{day}`. Nothing else; an unknown placeholder is a refusal at load time, not a folder called `{loan}` at apply time.
"""
from __future__ import annotations
import fnmatch
import hashlib
import json
import os
import re

from . import SortError
from .. import textio

VERSION = 1

# Placeholders every rule may use whatever its regex captures. A rule's own named groups are added to this set when it
# is checked, so a typo in `{borrwer}` is caught while reading the file rather than as a folder nobody meant.
BUILTIN_FIELDS = ("stem", "ext", "ext_nodot", "original", "year", "month", "day")

_FIELD = re.compile(r"\{([^{}]*)\}")

STARTER = {
    "version": VERSION,
    "into": "sorted",
    "rules": [
        {"name": "loan-packets",
         "match": {"glob": "*.pdf", "regex": r"^(?P<loan>\d{8})[-_ ]"},
         "into": "loans/{loan}"},
        {"name": "spreadsheets-by-month",
         "match": {"glob": "*.xlsx"},
         "into": "spreadsheets/{year}-{month}",
         "rename": "{year}-{month}-{day}-{stem}{ext}"},
        {"name": "everything-else-that-is-a-document",
         "match": {"glob": "*.docx"},
         "into": "documents"},
    ],
}


def sha256(rules: dict) -> str:
    """A stable digest of the rules a plan was made under, so `apply` can say which file it was."""
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _fields(template: str) -> list[str]:
    return _FIELD.findall(template or "")


def _check_template(rule_name: str, key: str, template: str, allowed: set) -> None:
    for field in _fields(template):
        if field not in allowed:
            raise SortError("unknown_placeholder",
                            f"rule {rule_name!r}: {key} uses {{{field}}}, which nothing supplies",
                            f"available here: {', '.join(sorted(allowed))} -- a named group in the rule's regex "
                            f"adds to this list, e.g. (?P<{field}>...)")


def _check_rule(rule, index: int) -> dict:
    if not isinstance(rule, dict):
        raise SortError("bad_rules", f"rules[{index}] is {type(rule).__name__}, not an object",
                        "each rule is an object with name, match, into and an optional rename")
    name = rule.get("name") or f"rules[{index}]"
    match = rule.get("match")
    if not isinstance(match, dict) or not (match.get("glob") or match.get("regex")):
        raise SortError("bad_rules", f"rule {name!r} matches nothing",
                        'give it "match": {"glob": "*.pdf"} or a "regex", or both')
    groups: set = set()
    if match.get("regex"):
        try:
            groups = set(re.compile(match["regex"]).groupindex)
        except re.error as e:
            raise SortError("bad_rules", f"rule {name!r}: regex does not compile: {e}",
                            "Python regular expression syntax; name a capture with (?P<loan>...)") from None
    if not rule.get("into"):
        raise SortError("bad_rules", f"rule {name!r} has no `into`",
                        'every rule says which folder its files go to, e.g. "into": "loans/{loan}"')
    allowed = set(BUILTIN_FIELDS) | groups
    _check_template(name, "into", rule["into"], allowed)
    _check_template(name, "rename", rule.get("rename", ""), allowed)
    return {"name": name, "match": match, "into": rule["into"], "rename": rule.get("rename", "")}


def check(rules) -> dict:
    """Validate a rule set and return it normalised. Every refusal names the rule it is about."""
    if not isinstance(rules, dict):
        raise SortError("bad_rules", f"the rules file is {type(rules).__name__}, not an object",
                        "see `ad-sort rules --write <path>` for the shape")
    version = rules.get("version")
    if version != VERSION:
        raise SortError("unsupported_rules_version", f"rules version {version!r}, and this build reads {VERSION}",
                        "regenerate with `ad-sort rules --write <path>` and re-add your rules")
    listed = rules.get("rules")
    if not isinstance(listed, list) or not listed:
        raise SortError("bad_rules", "the rules file lists no rules",
                        "a heap with no rules would be entirely unmatched, which is a plan nobody needs")
    into_val = str(rules.get("into", "sorted") or "sorted")
    if into_val.startswith(("/", "\\")) or os.path.isabs(os.path.expanduser(into_val)) or bool(os.path.splitdrive(into_val)[0]):
        raise SortError("absolute_into", f'top-level "into" is absolute: {rules.get("into")}',
                        "it is resolved against --dest, so it must be relative")
    return {"version": VERSION, "into": rules.get("into", "sorted") or "sorted",
            "rules": [_check_rule(r, i) for i, r in enumerate(listed)]}


def load(path: str) -> dict:
    """Read and validate a rules file."""
    if not path or not os.path.isfile(path):
        raise SortError("rules_missing", f"no rules file at {textio.norm_path(path or '')}",
                        "`ad-sort rules --write <path>` writes a starter to edit; the rule set is an input, "
                        "supplied or agreed by whoever owns the heap")
    return check(textio.read_json(path, "rules file"))


def matches(rule: dict, name: str) -> dict | None:
    """The rule's captured fields for this filename, or None. Name only -- the file is never opened."""
    match = rule["match"]
    glob = match.get("glob")
    if glob and not fnmatch.fnmatch(name.lower(), glob.lower()):
        return None
    pattern = match.get("regex")
    if not pattern:
        return {}
    found = re.search(pattern, name)
    return dict(found.groupdict(default="")) if found else None
