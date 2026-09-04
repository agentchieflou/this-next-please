"""A function that calls itself with nothing that obviously stops it.

Pattern:        a self-call, and no `return`/`raise` anywhere under an `if` in the same body. A base
                case in Python almost always looks like a conditional early exit, so its absence is
                worth a look.
False positive: plenty. The guard may be a `while` that breaks, a recursion depth passed as an
                argument, a conditional expression, or a bound the caller enforces. This is an
                AST-level heuristic and its confidence says so.
Confidence:     low
"""
from __future__ import annotations
import ast

from . import CheckContext, Finding

KIND = "recursion-no-guard"
SEVERITY = "logic"
CONFIDENCE = "low"


def _calls_itself(fn: ast.AST, name: str) -> int | None:
    for sub in ast.walk(fn):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        hit = (isinstance(f, ast.Name) and f.id == name) or (isinstance(f, ast.Attribute) and f.attr == name)
        if hit:
            return sub.lineno
    return None


def _has_conditional_exit(fn: ast.AST) -> bool:
    for sub in ast.walk(fn):
        if not isinstance(sub, ast.If):
            continue
        for inner in ast.walk(sub):
            if isinstance(inner, (ast.Return, ast.Raise)):
                return True
    return False


def check(ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    for rel in ctx.python_files:
        tree = ctx.tree(rel)
        if tree is None:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            line = _calls_itself(fn, fn.name)
            if line is None or _has_conditional_exit(fn):
                continue
            node = ctx.node_at(rel, fn.lineno)
            out.append(Finding(
                kind=KIND, node=node.id if node else rel,
                where=ctx.where(rel, fn.lineno),
                severity=SEVERITY, confidence=CONFIDENCE,
                hint="confirm the base case; if the bound is a caller's job, say so in the docstring",
                evidence=f"`{fn.name}` calls itself at line {line}; no conditional return or raise in the body",
            ))
    return out
