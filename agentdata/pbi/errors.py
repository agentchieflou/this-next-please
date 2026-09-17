"""The one error every `ad-pbi` verb prints. Its own module so `auth` can raise it without importing `client`."""
from __future__ import annotations


class FabricError(Exception):
    """An error from the Fabric REST API, an XMLA tool launch, or the sign-in that both depend on."""

    def __init__(self, code: str, msg: str, hint: str = "", detail: dict | None = None):
        super().__init__(msg)
        self.code, self.msg, self.hint, self.detail = code, msg, hint, detail or {}

    def to_dict(self) -> dict:
        d = {"ok": False, "code": self.code, "error": self.msg}
        if self.hint:
            d["hint"] = self.hint
        if self.detail:
            d["detail"] = self.detail
        return d
