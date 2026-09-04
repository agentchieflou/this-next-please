"""Handlers where a failure disappears.

Pattern:        a bare `except:` or `except Exception:` whose body is only `pass`, `...`, `continue`,
                or a single logging/print call -- no re-raise, no return of a fallback value, nothing
                the caller can notice.
False positive: a deliberate best-effort cleanup. `except Exception: pass` around a cache warm-up is
                a decision, not a bug -- but it is a decision worth seeing in a list.
Confidence:     high
"""
from __future__ import annotations
import ast

from . import CheckContext, Finding

KIND = "swallowed-exception"
SEVERITY = "logic"
CONFIDENCE = "high"

_LOG_NAMES = {"print", "log", "debug", "info", "warning", "warn", "error", "exception", "critical"}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    t = handler.type
    if isinstance(t, ast.Name) and t.id in ("Exception", "BaseException"):
        return True
    return False


def _only_logs_or_passes(body: list[ast.stmt]) -> str | None:
    """The reason this handler is empty, or None when it does something real."""
    if len(body) != 1:
        return None
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return "body is `pass`"
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
        return "body is `...`"
    if isinstance(stmt, ast.Continue):
        return "body is `continue`"
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        f = stmt.value.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
        if name in _LOG_NAMES:
            return f"body only calls `{name}(...)`"
    return None


def check(ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    for rel in ctx.python_files:
        tree = ctx.tree(rel)
        if tree is None:
            continue
        for h in ast.walk(tree):
            if not isinstance(h, ast.ExceptHandler) or not _is_broad(h):
                continue
            reason = _only_logs_or_passes(h.body)
            if reason is None:
                continue
            node = ctx.node_at(rel, h.lineno)
            clause = "except:" if h.type is None else f"except {ast.unparse(h.type)}:"
            out.append(Finding(
                kind=KIND, node=node.id if node else rel,
                where=ctx.where(rel, h.lineno),
                severity=SEVERITY, confidence=CONFIDENCE,
                hint="catch the specific exception and let the rest propagate, or return a value the caller can check",
                evidence=f"`{clause}` at line {h.lineno}, {reason}",
            ))
    return out
