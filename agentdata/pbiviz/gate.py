"""The enterprise gate on SDK-built custom visuals: the `pbi_sdk_visuals` project fact.

The enterprise blocks every custom visual that is not Microsoft-certified, and a visual built with the
Power BI SDK (`pbiviz`) is not certified: it is a private .pbiviz until Microsoft certifies it on AppSource.
The operator is seeking workspace approval for SDK visuals. Until it exists, `pbi_sdk_visuals` is `blocked`
-- also when the fact is absent or misspelt, so the gate fails closed -- and every `ad-pbiviz` verb that
builds, serves, packages or imports one refuses with `sdk_visuals_blocked`, and `ad-pbip check` and
`ad-pbi publish report` treat a private visual in a report as an error on every tenant.

The SDK toolchain (Node.js, npm, powerbi-visuals-tools) is also outside the tools this package may ask a
machine for (Tabular Editor 2, DAX Studio's dscmd, the Azure CLI), so approving SDK visuals is the operator's
approval of that toolchain too. While blocked, nothing here probes for it or tells anyone to install it.

`approved` is the operator's to write, once the approval exists, optionally with `pbi_sdk_workspace` naming the
approved workspace (its name or id): `ad-pbi publish report` then refuses any other workspace for a report that
carries an SDK visual, and `ad-pbip check` does the same against the project's `pbi_workspace` / `ws_id`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

FACT = "pbi_sdk_visuals"
WORKSPACE_FACT = "pbi_sdk_workspace"
STATES = ("blocked", "approved")
CODE = "sdk_visuals_blocked"
TOOLCHAIN = "Node.js, npm and powerbi-visuals-tools"
APPROVED_TOOLS = "te2, dscmd and az"
# the verbs that need the SDK, its toolchain, or put an SDK visual in a report
GATED_VERBS = ("new", "dev", "stop", "package", "import")

BLOCKED = ("the enterprise blocks every custom visual that is not Microsoft-certified, and a visual built with "
           "the Power BI SDK is not certified: SDK visuals wait on workspace approval (pbi_sdk_visuals: blocked)")
HINT = (f"set `- {FACT}: approved` in AGENTS.md only after the operator has workspace approval for SDK visuals "
        f"(and `- {WORKSPACE_FACT}: <workspace name or id>` naming it); the SDK toolchain ({TOOLCHAIN}) is outside "
        f"the approved tool set ({APPROVED_TOOLS}), so it needs the operator's approval too. Meanwhile skill "
        "`pbi-custom-visual` routes native, then certified (Deneb)")


@dataclass(frozen=True)
class SdkGate:
    state: str          # blocked | approved
    workspace: str      # pbi_sdk_workspace, "" when unset
    written: str        # the fact as AGENTS.md has it, lower-cased; "" when absent

    @property
    def approved(self) -> bool:
        return self.state == "approved"

    @property
    def invalid(self) -> bool:
        """Written, but neither state: read as blocked."""
        return bool(self.written) and self.written not in STATES

    def workspace_matches(self, *names: str | None) -> bool:
        """Whether any of `names` (a workspace's id or display name) is the approved one; True when none is set."""
        if not self.workspace:
            return True
        want = self.workspace.strip().lower()
        return any(n and str(n).strip().lower() == want for n in names)


def gate(facts: Mapping[str, Any] | None) -> SdkGate:
    """The gate from the project's AGENTS.md facts. Anything but `approved` is blocked."""
    facts = facts or {}
    written = str(facts.get(FACT) or "").strip().lower()
    return SdkGate("approved" if written == "approved" else "blocked",
                   str(facts.get(WORKSPACE_FACT) or "").strip(), written)


def refusal(verb: str, g: SdkGate) -> dict[str, Any]:
    """The structured refusal an `ad-pbiviz` verb prints while SDK visuals are blocked."""
    return {"ok": False, "source": f"ad-pbiviz {verb}", "code": CODE, "error": f"ad-pbiviz {verb} refused: {BLOCKED}",
            "hint": HINT, FACT: g.written or "blocked (absent)"}


def doctor_rows(g: SdkGate) -> list[dict[str, Any]]:
    """What `ad-pbiviz doctor` reports first. While blocked it is all it reports: the toolchain is not probed,
    and no row names an install command."""
    if g.approved:
        where = f"for workspace '{g.workspace}'" if g.workspace else f"({WORKSPACE_FACT} not recorded)"
        hint = "" if g.workspace else f"record `- {WORKSPACE_FACT}: <workspace>`: the approval is per workspace"
        return [{"check": "sdk_visuals", "status": "ok", "detail": f"{FACT}: approved {where}", "hint": hint}]
    written = g.written or "absent"
    return [
        {"check": "sdk_visuals", "status": "blocked", "detail": f"{FACT}: {written}; {BLOCKED}", "hint": HINT},
        {"check": "toolchain", "status": "not_offered",
         "detail": f"{TOOLCHAIN} are not probed: outside the approved tool set ({APPROVED_TOOLS})", "hint": ""},
    ]
