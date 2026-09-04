"""Linear scans inside a loop -- the accidental O(n^2).

Pattern:        either (a) an `in` / `not in` membership test against a local bound to a list or tuple
                literal, or (b) a loop whose iterable is a collection built by the enclosing loop.
                Both turn one pass into a pass per item.
False positive: a list that is always tiny -- membership against a three-element tuple of flags is
                this shape and is faster than a set. The check cannot see the collection's size at
                runtime, only how it was written.
Confidence:     med
"""
from __future__ import annotations
import ast

from . import CheckContext, Finding

KIND = "quadratic-scan"
SEVERITY = "perf"
CONFIDENCE = "med"

_LOOPS = (ast.For, ast.AsyncFor, ast.While)


def _list_locals(fn: ast.AST) -> dict[str, int]:
    """Names bound to a list/tuple literal, comprehension, or `list(...)`, and where."""
    out: dict[str, int] = {}
    for n in ast.walk(fn):
        if not isinstance(n, ast.Assign) or len(n.targets) != 1:
            continue
        target = n.targets[0]
        if not isinstance(target, ast.Name):
            continue
        v = n.value
        is_seq = isinstance(v, (ast.List, ast.Tuple, ast.ListComp))
        is_seq = is_seq or (isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id in ("list", "tuple"))
        if is_seq:
            out[target.id] = n.lineno
    return out


def _appended_names(loop: ast.AST) -> set[str]:
    """Names this loop grows: `x.append(...)`, `x += [...]`, `x.extend(...)`."""
    grown: set[str] = set()
    for n in ast.walk(loop):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("append", "extend", "add"):
            if isinstance(n.func.value, ast.Name):
                grown.add(n.func.value.id)
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            grown.add(n.target.id)
    return grown


def check(ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    for rel in ctx.python_files:
        tree = ctx.tree(rel)
        if tree is None:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seq_locals = _list_locals(fn)

            for loop in ast.walk(fn):
                if not isinstance(loop, _LOOPS):
                    continue

                # (a) membership against a list/tuple local, inside the loop body
                for sub in ast.walk(loop):
                    if not isinstance(sub, ast.Compare) or len(sub.ops) != 1:
                        continue
                    if not isinstance(sub.ops[0], (ast.In, ast.NotIn)):
                        continue
                    rhs = sub.comparators[0]
                    name = rhs.id if isinstance(rhs, ast.Name) else None
                    if name is None or name not in seq_locals:
                        continue
                    node = ctx.node_at(rel, sub.lineno)
                    out.append(Finding(
                        kind=KIND, node=node.id if node else rel,
                        where=ctx.where(rel, sub.lineno),
                        severity=SEVERITY, confidence=CONFIDENCE,
                        hint=f"build `{name}` as a set once before the loop; membership is then O(1)",
                        evidence=f"`in {name}` inside a loop; `{name}` bound to a sequence at line {seq_locals[name]}",
                    ))

                # (b) an inner loop over a collection the outer loop is still filling
                grown = _appended_names(loop)
                for sub in ast.walk(loop):
                    if sub is loop or not isinstance(sub, (ast.For, ast.AsyncFor)):
                        continue
                    it = sub.iter
                    name = it.id if isinstance(it, ast.Name) else None
                    if name is None or name not in grown:
                        continue
                    node = ctx.node_at(rel, sub.lineno)
                    out.append(Finding(
                        kind=KIND, node=node.id if node else rel,
                        where=ctx.where(rel, sub.lineno),
                        severity=SEVERITY, confidence=CONFIDENCE,
                        hint="the inner loop re-walks a collection the outer loop is still growing; index it instead",
                        evidence=f"inner loop iterates `{name}`, which the enclosing loop appends to",
                    ))
    return out
