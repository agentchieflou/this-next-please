"""The same call, with the same arguments, made more than once in one function body.

Pattern:        two or more calls in a single function that share a callee and an argument list made
                only of literals and plain names, with no assignment to any of those names between
                them. Memoize the result or hoist it to a local.
False positive: a call that is not pure. `next(it)` twice, or `time.time()` twice, is deliberate and
                this check will flag it -- the AST cannot tell a pure function from an effectful one.
                The container constructors in FRESH_EACH_TIME are excluded for the same reason,
                because there hoisting is an outright bug rather than a judgement call.
Confidence:     med
"""
from __future__ import annotations
import ast

from . import CheckContext, Finding

KIND = "repeated-call"
SEVERITY = "perf"
CONFIDENCE = "med"

# calling these twice makes two objects on purpose; hoisting them to one local is a bug, not a
# speedup, so they are never a repeated call
FRESH_EACH_TIME = {
    "set", "dict", "list", "tuple", "bytearray", "object", "defaultdict", "Counter", "OrderedDict",
    "deque", "Lock", "RLock", "Event", "Queue", "StringIO", "BytesIO",
}


def _callee_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        parts = [f.attr]
        cur = f.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
            return ".".join(reversed(parts))
    return None


def _arg_signature(call: ast.Call) -> tuple[str, ...] | None:
    """A comparable signature, or None when an argument is anything but a literal or a bare name."""
    sig: list[str] = []
    for a in call.args:
        if isinstance(a, ast.Constant):
            sig.append(f"c:{a.value!r}")
        elif isinstance(a, ast.Name):
            sig.append(f"n:{a.id}")
        else:
            return None
    for kw in call.keywords:
        if kw.arg is None:
            return None
        if isinstance(kw.value, ast.Constant):
            sig.append(f"{kw.arg}=c:{kw.value.value!r}")
        elif isinstance(kw.value, ast.Name):
            sig.append(f"{kw.arg}=n:{kw.value.id}")
        else:
            return None
    return tuple(sig)


def _names_in_signature(sig: tuple[str, ...]) -> set[str]:
    out = set()
    for part in sig:
        body = part.split("=", 1)[1] if "=" in part and not part.startswith("n:") else part
        if body.startswith("n:"):
            out.add(body[2:])
    return out


def _assigned_names(fn: ast.AST) -> dict[str, list[int]]:
    """Where each name is (re)bound in this function body, by line."""
    bound: dict[str, list[int]] = {}
    for n in ast.walk(fn):
        targets: list[ast.AST] = []
        if isinstance(n, ast.Assign):
            targets = list(n.targets)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            targets = [n.target]
        elif isinstance(n, ast.For):
            targets = [n.target]
        for t in targets:
            for sub in ast.walk(t):
                if isinstance(sub, ast.Name):
                    bound.setdefault(sub.id, []).append(getattr(n, "lineno", 0))
    return bound


def check(ctx: CheckContext) -> list[Finding]:
    out: list[Finding] = []
    for rel in ctx.python_files:
        tree = ctx.tree(rel)
        if tree is None:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            bound = _assigned_names(fn)
            groups: dict[tuple[str, tuple[str, ...]], list[int]] = {}
            for sub in ast.walk(fn):
                if not isinstance(sub, ast.Call):
                    continue
                name = _callee_name(sub)
                sig = _arg_signature(sub)
                if name is None or sig is None:
                    continue
                if name.rsplit(".", 1)[-1] in FRESH_EACH_TIME:
                    continue
                groups.setdefault((name, sig), []).append(sub.lineno)

            for (name, sig), lines in sorted(groups.items()):
                if len(lines) < 2:
                    continue
                lines.sort()
                # a rebind between the two calls means the second one is asking a different question
                rebound = any(
                    lines[0] < ln <= lines[-1]
                    for nm in _names_in_signature(sig)
                    for ln in bound.get(nm, [])
                )
                if rebound:
                    continue
                node = ctx.node_at(rel, lines[0])
                out.append(Finding(
                    kind=KIND,
                    node=node.id if node else rel,
                    where=ctx.where(rel, lines[0]),
                    severity=SEVERITY,
                    confidence=CONFIDENCE,
                    hint="hoist the call to a local above the first use, or memoize it",
                    evidence=f"`{name}({', '.join(sig)})` called {len(lines)}x at lines {lines} in `{fn.name}`",
                ))
    return out
