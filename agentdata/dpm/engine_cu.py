"""The Azure Content Understanding engine for `ad-dpm extract-fields`.

Same schema in, same rows out, same statuses. Nothing downstream -- the review file, the TOON
table, the provenance columns -- knows which engine ran, which is the whole point of the seam in
`extract.py`.

**What is different, and why it is worth saying out loud.** `SimpleEngine` searches the text for
each field's `hint`. This engine does not: the analyzer holds its own field schema, defined in the
Foundry portal, and the service decides what a field is. So the job's `hint` is *unused here*, and
the two schemas can disagree without anything failing -- which would show up as every field coming
back `not_found`, reading exactly like "the documents do not contain this". That is the failure
`load_schema` refuses to allow for typos, so this engine will not allow it either: a `not_found`
detail names the fields the analyzer actually returned, so the mismatch is legible on the first row
rather than after somebody re-scans a hundred documents by hand.

**One call per document, not one per field.** `extract()` calls `find()` once per field with the
same text, so the analysis is cached on that text. A twelve-field schema costs one request.

**The OCR bucket is decided before this engine is called.** `extract()` routes anything that is not
`native_text` to `needs_ocr_review` and never reaches an engine, so this one never returns that
status -- it is given text and answers about text.
"""
from __future__ import annotations

import hashlib
import re

from . import DpmError
from .extract import Engine, register

# Below this, a value is real but not one to act on unreviewed -- which is what `ambiguous` already
# means everywhere else in this command: a reviewer has to look. Configurable per run because what
# counts as low depends on the analyzer, not on this file.
DEFAULT_MIN_CONFIDENCE = 0.7

# How many of the analyzer's own field names a `not_found` detail lists before it gives up. Enough
# to see a naming mismatch; short enough to read in a table cell.
NAMES_SHOWN = 8


def key(name: str) -> str:
    """`LoanAmount`, `loan_amount` and `Loan Amount` are the same field.

    The job schema is written by whoever runs the job and the analyzer schema by whoever built the
    analyzer; they are rarely the same person, and casing is not a real disagreement.
    """
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


class ContentUnderstandingEngine(Engine):
    name = "azure-content-understanding"
    options = ("analyzer", "min_confidence", "mime_type")

    def __init__(self, **options):
        super().__init__(**options)
        self._cache: dict[str, dict] = {}
        self._analyzer = str(options.get("analyzer") or "")
        self._mime = str(options.get("mime_type") or "")
        try:
            self._floor = float(options.get("min_confidence", DEFAULT_MIN_CONFIDENCE))
        except (TypeError, ValueError):
            raise DpmError("bad_engine_option",
                           f"min_confidence must be a number, not {options.get('min_confidence')!r}",
                           "a confidence between 0 and 1, e.g. 0.7") from None

    # ---------------------------------------------------------------- the service, once per document

    def _cu(self):
        from ..connectors import content_understanding as CU

        return CU

    def analyzer(self) -> str:
        """The analyzer id: the option, else the configured default. Refuses rather than guesses --
        there is no sensible default analyzer, and an id that does not exist fails at the service
        with a message about the id rather than about the document."""
        if self._analyzer:
            return self._analyzer
        hint = ("--analyzer <id>, or set content_understanding.analyzer; "
                "`ad-foundry analyzers list` shows what the resource has")
        try:
            self._analyzer = self._cu().settings()["analyzer"]
        except Exception as e:                       # noqa: BLE001 - a config error is the same answer
            raise DpmError("no_analyzer",
                           f"no Content Understanding analyzer is configured: {e}", hint) from None
        if not self._analyzer:
            raise DpmError("no_analyzer", "no Content Understanding analyzer is configured", hint)
        return self._analyzer

    def _analyze(self, text: str) -> dict:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in self._cache:
            return self._cache[digest]
        CU = self._cu()
        try:
            result = CU.analyze(analyzer=self.analyzer(), data=text.encode("utf-8"),
                                mime_type=self._mime or CU.TEXT_PLAIN)
        except CU.ContentUnderstandingError as e:
            # Never a silent `not_found`. A service that could not be reached has said nothing
            # about the document, and a row that claims otherwise is the one lie this command
            # cannot afford.
            raise DpmError("content_understanding_failed", e.msg, e.hint) from None
        self._cache[digest] = result
        return result

    # ---------------------------------------------------------------------------- one field

    def find(self, text: str, field: dict) -> tuple[str, str, str]:
        if not text.strip():
            return "no_text", "", "the document has no extracted text"
        CU = self._cu()
        result = self._analyze(text)
        returned = {key(row["field"]): row for row in CU.fields_from_result(result)}
        row = returned.get(key(field["name"]))
        if row is None:
            return "not_found", "", self._mismatch(field["name"], returned)

        value = "" if row["value"] is None else str(row["value"]).strip()
        confidence = row.get("confidence")
        said = f"analyzer field {row['field']!r}"
        if confidence is not None:
            said += f", confidence {float(confidence):.2f}"
        if not value:
            return "not_found", "", f"{said}: the analyzer returned it with no value"
        if confidence is not None and float(confidence) < self._floor:
            return "ambiguous", value, (f"{said}: below the {self._floor:.2f} floor, so a reviewer "
                                        f"should confirm it")
        return "found", value, said

    def _mismatch(self, wanted: str, returned: dict) -> str:
        """The detail that makes a schema mismatch obvious instead of looking like an empty document."""
        if not returned:
            return (f"the analyzer {self.analyzer()!r} returned no fields at all -- it may not be "
                    f"the analyzer this schema was written for")
        names = sorted(row["field"] for row in returned.values())
        shown = ", ".join(names[:NAMES_SHOWN]) + ("..." if len(names) > NAMES_SHOWN else "")
        return (f"the analyzer {self.analyzer()!r} has no field matching {wanted!r}; it returned: "
                f"{shown}")


register(ContentUnderstandingEngine)
