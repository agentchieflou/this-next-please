"""What the desk serves of a script or a stylesheet: the file without its comments (#523, decision 19).

The source keeps its JSDoc types, which `tsc` reads (docs/desk-types.md), and its reasoning lives in
the tagalong `<file>.md` beside it. Neither belongs on the wire, so `serve._static` hands every `.js`
and `.css` it serves through `strip_js` or `strip_css`, and the payload budgets measure what comes
out (tests/test_fleet_serve.py, tests/test_fleet_ink.py).

A comment is found by tokenizing, never by a pattern over the text: `"//"` in a URL string, a `/*` in
a regular expression or a template literal, and `url(/*x*/)` in a stylesheet are code. Whether a `/`
opens a regular expression is decided by the token before it, as a parser does: after a value (a
name, a number, a string, `)` or `]`) it divides, after anything else it opens one.

What replaces a comment keeps the program the program it was:
* a comment alone on its lines goes with its lines;
* a comment at the end of a line goes with the spaces before it;
* anywhere else, in a script, it becomes a space, or a line break when it held one (a line break is
  what automatic semicolon insertion reads); in a stylesheet it becomes nothing, as it does when the
  stylesheet is tokenized (`.a/**/.b` is `.a.b`, and a space there would be a descendant combinator).

`tests/test_fleet_served_comments.py` proves it: every served file, stripped, parses to the same
program (acorn) or the same tokens (css-tree) as its source.
"""
from __future__ import annotations

import re

_LINE_ENDS = "\n\r  "

_JS_TOKEN = re.compile(r"""
    (?P<ws>[ \t\f\v﻿ \n\r  ]+)
  | (?P<line>//[^\n\r  ]*)
  | (?P<block>/\*.*?\*/)
  | (?P<str>"(?:[^"\\\n\r]|\\.)*"|'(?:[^'\\\n\r]|\\.)*')
  | (?P<num>(?:\d|\.\d)(?:[\w.]|(?<=[eE])[+-])*)
  | (?P<name>(?:[A-Za-z_$\u0080-￿#]|\\u)(?:[\w$\u0080-￿]|\\u)*)
  | (?P<tick>`)
  | (?P<punct>\.\.\.|\+\+|--|.)
""", re.X | re.S)
_TEMPLATE_BODY = re.compile(r"(?:[^`\\$]|\\.|\$(?!\{))*", re.S)
#: After one of these words a `/` opens a regular expression; after any other name it divides.
_REGEX_AFTER_WORD = frozenset({"return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
                               "throw", "case", "do", "else", "yield", "await"})


def js_comments(src: str) -> list[tuple[int, int]]:
    """Every comment in a script or a module, as `(start, end)` offsets. Raises `ValueError` on a
    string, comment, template or regular expression that does not end."""
    out: list[tuple[int, int]] = []
    i, n = 0, len(src)
    stack: list[str] = []      # "{" for a brace, "${" for a template's substitution
    value = False              # was the last token a value, so that a `/` divides?
    dot = False                # was it a `.`, so that `return` is a property name?

    def template(i: int) -> tuple[int, bool]:
        """From inside a template to after its closing backtick (end, False) or its next `${`."""
        j = _TEMPLATE_BODY.match(src, i).end()
        if j >= n:
            raise ValueError(f"an unterminated template literal before {i}")
        return (j + 1, False) if src[j] == "`" else (j + 2, True)

    while i < n:
        m = _JS_TOKEN.match(src, i)
        kind, text = m.lastgroup, m.group()
        if kind == "ws":
            i = m.end()
            continue
        if kind in ("line", "block"):
            out.append((i, m.end()))
            i = m.end()
            continue
        if src.startswith("/*", i):
            raise ValueError(f"an unterminated comment at {i}")
        if kind == "str":
            i, value = m.end(), True
        elif kind == "num":
            i, value = m.end(), True
        elif kind == "name":
            i, value = m.end(), dot or text not in _REGEX_AFTER_WORD
        elif kind == "tick":
            i, substitution = template(i + 1)
            if substitution:
                stack.append("${")
            value = not substitution
        elif text == "/" and not value:        # a regular expression, and its flags
            j, klass = i + 1, False
            while True:
                if j >= n or src[j] in _LINE_ENDS:
                    raise ValueError(f"an unterminated regular expression at {i}")
                d = src[j]
                if d == "\\":
                    j += 2
                    continue
                if klass:
                    klass = d != "]"
                elif d == "[":
                    klass = True
                elif d == "/":
                    break
                j += 1
            j += 1
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            i, value = j, True
        elif text in ("'", '"'):
            raise ValueError(f"an unterminated string at {i}")
        elif text == "{":
            stack.append("{")
            i, value = i + 1, False
        elif text == "}":
            if stack and stack[-1] == "${":
                stack.pop()
                i, substitution = template(i + 1)
                if substitution:
                    stack.append("${")
                value = not substitution
            else:
                if stack:
                    stack.pop()
                i, value = i + 1, False        # a block's end: a `/` after it opens a regex
        elif text in (")", "]"):
            i, value = i + 1, True
        elif text in ("++", "--"):
            i = m.end()                        # `a++ / 2` still divides
        else:
            i, value = m.end(), False
            dot = text == "."
            continue
        dot = False
    return out


_CSS_TOKEN = re.compile(r"""
    (?P<comment>/\*.*?\*/)
  | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<url>(?<![\w-])[uU][rR][lL]\([ \t\n\r\f]*(?!["'])(?:[^)\\]|\\.)*\))
  | (?P<esc>\\.)
  | (?P<other>[^/"'\\uU]+|.)
""", re.X | re.S)


def css_comments(src: str) -> list[tuple[int, int]]:
    """Every comment in a stylesheet. A `/*` inside a quoted string or an unquoted `url(...)` is part
    of it, not a comment; a backslash escapes the character after it."""
    out: list[tuple[int, int]] = []
    i, n = 0, len(src)
    while i < n:
        m = _CSS_TOKEN.match(src, i)
        if m.lastgroup == "comment":
            out.append((i, m.end()))
        elif src.startswith("/*", i):
            raise ValueError(f"an unterminated comment at {i}")
        i = m.end()
    return out


def _strip(src: str, spans: list[tuple[int, int]], script: bool) -> str:
    out: list[str] = []
    at = 0                                     # everything before `at` is decided
    for s, e in spans:
        if s < at:                             # already taken with a line before it
            continue
        line_start = src.rfind("\n", 0, s) + 1
        line_end = src.find("\n", e)
        line_end = len(src) if line_end < 0 else line_end
        before, after = src[max(line_start, at):s], src[e:line_end]
        alone_before = line_start >= at and not before.strip(" \t")
        # A comment followed on its line only by spaces and other comments is at the end of it.
        rest = after
        for s2, e2 in spans:
            if s2 >= e and e2 <= line_end:
                rest = rest.replace(src[s2:e2], "", 1)
        at_end = not rest.strip(" \t\r")
        if alone_before and at_end:
            out.append(src[at:line_start])
            at = line_end + 1 if line_end < len(src) else line_end
            # Between two blank lines, one stays. The line after a comment's own line starts
            # outside any string or template, so a blank one there is only spacing.
            tail = next((piece for piece in reversed(out) if piece), "")
            if (tail.endswith("\n\n") or tail == "\n" and len(out) > 1 and "".join(out).endswith("\n\n")) \
                    and src.startswith(("\n", "\r\n"), at):
                at = src.index("\n", at) + 1
        elif at_end:
            a = s
            while a > at and src[a - 1] in " \t":
                a -= 1
            out.append(src[at:a])
            at = e
        else:
            out.append(src[at:s])
            if script and any(c in _LINE_ENDS for c in src[s:e]):
                out.append("\n")
            elif script and src[s - 1] not in " \t" and src[e] not in " \t":
                out.append(" ")                # `a/**/b` stays two names
            at = e
    out.append(src[at:])
    return "".join(out)


def strip_js(src: str) -> str:
    """A script or module without its comments. Raises `ValueError` if it cannot be tokenized."""
    return _strip(src, js_comments(src), script=True)


def strip_css(src: str) -> str:
    """A stylesheet without its comments. Raises `ValueError` if it cannot be tokenized."""
    return _strip(src, css_comments(src), script=False)
