"""Remove comments and neutralize string literals before pattern matching, keeping line structure.

Literal handling: empty literals stay `''`; short alphabetic literals (date units such as 'MM', 'MONTH', status
names) are kept so unit-order rules can see them; everything else becomes `'§'`. Newlines inside comments and
literals are preserved so reported line numbers match the original text.
"""
from __future__ import annotations
import re

_SHORT_ALPHA = re.compile(r"^[A-Za-z]{1,8}$")


def strip(sql: str) -> str:
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":  # line comment
            j = sql.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif ch == "/" and nxt == "*":  # block comment (hints too; see rules with raw=True)
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(_blank(sql[i:j]))
            i = j
        elif ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            body = sql[i + 1:j]
            j = min(j + 1, n)
            if body == "":
                out.append("''")
            elif _SHORT_ALPHA.match(body):
                out.append(f"'{body}'")
            else:
                out.append("'§'" + _blank(body).replace(" ", ""))  # keep the newlines the literal contained
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _blank(text: str) -> str:
    return "".join("\n" if c == "\n" else " " for c in text)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1
