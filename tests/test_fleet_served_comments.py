"""What the desk serves is code: a served script or stylesheet carries no comment (#523).

Decision 18 on #429, the operator's words: *"For performance's sake, app.js shouldn't have comments.
It should have a tagalong file that covers documentation. We will eventually be having a hyper
optimization path to target sub 200ms load times everywhere, so raising the cap isn't an option."*

So every `.js` and `.css` file under `agentdata/fleet/static/` -- which `serve._static` serves, any
file there by its path -- holds code and nothing else, except the inline type casts `tsc` needs,
`/** @type {X} */ (expr)`. Its reasoning lives beside it in `<file>.md`, and the JSDoc types that
used to sit in `app.js` and `picker.js` live in a checked `<file>.d.ts` (`tsconfig.json`).
`vendor/` is the one exception: three.js is someone else's file, shipped as they built it, licence
header and all.

A comment is found by tokenizing, never by a pattern over the text: `"//"` in a URL string, a `/*`
inside a regular expression or a template literal, and `url(/*x*/)` in a stylesheet are code.
"""
from __future__ import annotations

import os
import re

from agentdata.fleet import serve as S

STATIC = S.STATIC
#: Someone else's files, served as they shipped: three.js keeps its licence header.
THIRD_PARTY = ("vendor",)


def served() -> list[str]:
    """Every script and stylesheet `serve._static` would answer for, by its path under `static/`."""
    out = []
    for root, dirs, files in os.walk(STATIC):
        rel_root = os.path.relpath(root, STATIC)
        if rel_root.split(os.sep)[0] in THIRD_PARTY:
            continue
        for n in files:
            if n.endswith((".js", ".css")):
                out.append(os.path.normpath(os.path.join(rel_root, n)).replace(os.sep, "/"))
    return sorted(out)


# ---- the scanner

_LINE_ENDS = "\n\r  "
_ID_START = re.compile(r"[A-Za-z_$\u0080-￿]")
_ID_PART = re.compile(r"[A-Za-z0-9_$\u0080-￿]")
#: After one of these words a `/` opens a regular expression; after any other name it divides.
_REGEX_AFTER_WORD = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void", "throw",
                     "case", "do", "else", "yield", "await"}


def js_comments(src: str) -> list[tuple[int, int]]:
    """Every comment in a script or a module, as `(start, end)` offsets.

    It steps over strings, template literals (with `${}` nested to any depth) and regular
    expression literals. Whether a `/` opens a regex is decided by the token before it, as a parser
    does: after a value (a name, a number, a string, `)` or `]`) it divides, after anything else it
    opens one. It agrees with acorn on every comment in every served file (#523's handover).
    """
    out: list[tuple[int, int]] = []
    i, n = 0, len(src)
    stack: list[str] = []      # "{" for a brace, "${" for a template's substitution
    value = False              # was the last token a value, so that a `/` divides?
    dot = False                # was it a `.`, so that `return` is a property name?

    def template(i: int) -> tuple[int, bool]:
        """From inside a template to its closing backtick (end, False) or its next `${` (after, True)."""
        while i < n:
            if src[i] == "\\":
                i += 2
            elif src[i] == "`":
                return i + 1, False
            elif src.startswith("${", i):
                return i + 2, True
            else:
                i += 1
        raise ValueError("an unterminated template literal")

    while i < n:
        c = src[i]
        if c in " \t\f\v﻿ " or c in _LINE_ENDS:
            i += 1
            continue
        if src.startswith("//", i):
            j = i + 2
            while j < n and src[j] not in _LINE_ENDS:
                j += 1
            out.append((i, j))
            i = j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise ValueError(f"an unterminated comment at {i}")
            out.append((i, j + 2))
            i = j + 2
            continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] in "\n\r":
                    raise ValueError(f"an unterminated string at {i}")
                j += 2 if src[j] == "\\" else 1
            i, value = j + 1, True
        elif c == "`":
            i, substitution = template(i + 1)
            if substitution:
                stack.append("${")
            value = not substitution
        elif c == "/":
            if value:                              # a division, or `/=`
                i += 2 if src.startswith("/=", i) else 1
                value = False
            else:                                  # a regular expression, and its flags
                j, klass = i + 1, False
                while j < n:
                    d = src[j]
                    if d == "\\":
                        j += 2
                        continue
                    if d in "\n\r":
                        raise ValueError(f"an unterminated regular expression at {i}")
                    if klass:
                        klass = d != "]"
                    elif d == "[":
                        klass = True
                    elif d == "/":
                        break
                    j += 1
                j += 1
                while j < n and _ID_PART.match(src[j]):
                    j += 1
                i, value = j, True
        elif c == "{":
            stack.append("{")
            i, value = i + 1, False
        elif c == "}":
            if stack and stack[-1] == "${":
                stack.pop()
                i, substitution = template(i + 1)
                if substitution:
                    stack.append("${")
                value = not substitution
            else:
                if stack:
                    stack.pop()
                i, value = i + 1, False            # a block's end: a `/` after it opens a regex
        elif c in ")]":
            i, value = i + 1, True
        elif c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i + 1
            while j < n and (_ID_PART.match(src[j]) or src[j] == "."
                             or (src[j] in "+-" and src[j - 1] in "eE" and not src.startswith("0x", i))):
                j += 1
            i, value = j, True
        elif _ID_START.match(c) or c in "\\#":
            j = i + 1
            while j < n and _ID_PART.match(src[j]):
                j += 1
            i, value = j, dot or src[i:j] not in _REGEX_AFTER_WORD
        elif src.startswith(("++", "--"), i):
            i += 2                                 # `a++ / 2` still divides
        elif src.startswith("...", i):
            i, value = i + 3, False
        else:
            i, value = i + 1, False                # any other punctuator
            dot = c == "."
            continue
        dot = False
    return out


def css_comments(src: str) -> list[tuple[int, int]]:
    """Every comment in a stylesheet. A `/*` inside a quoted string or an unquoted `url(...)` is part
    of it, not a comment; a backslash escapes the character after it."""
    out: list[tuple[int, int]] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise ValueError(f"an unterminated comment at {i}")
            out.append((i, j + 2))
            i = j + 2
        elif c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
        elif c == "\\":
            i += 2
        elif src[i:i + 4].lower() == "url(" and (i == 0 or not re.match(r"[\w-]", src[i - 1])):
            j = i + 4
            while j < n and src[j] in " \t\n\r\f":
                j += 1
            if j < n and src[j] in "'\"":
                i = j                              # a quoted url: the string is read as a string
            else:
                while j < n and src[j] != ")":
                    j += 2 if src[j] == "\\" else 1
                i = j + 1
        else:
            i += 1
    return out


_CAST = re.compile(r"/\*\*\s*@type\s*\{[^\n]*\}\s*\*/")


def is_type_cast(src: str, start: int, end: int) -> bool:
    """`/** @type {X} */ (expr)`: one line, one `@type` tag and nothing else, then a parenthesis."""
    text = src[start:end]
    return (bool(_CAST.fullmatch(text)) and text.count("@") == 1
            and src[end:].lstrip(" \t").startswith("("))


def comments_in(rel: str, src: str) -> list[str]:
    """The comments `rel` may not carry, each with its line number."""
    if rel.endswith(".css"):
        spans = css_comments(src)
    else:
        spans = [(s, e) for s, e in js_comments(src) if not is_type_cast(src, s, e)]
    return [f"{rel}:{src.count(chr(10), 0, s) + 1}: {src[s:e][:60]!r}" for s, e in spans]


# ---- the scanner, on the cases a pattern gets wrong

def test_the_comment_scanner_steps_over_strings_regexes_and_templates():
    def found(src):
        return [src[s:e] for s, e in js_comments(src)]

    assert found('var u = "http://x/*y*/"; // one') == ["// one"]
    assert found("var u = 'a // b'; /* two */") == ["/* two */"]
    assert found(r'var s = "a \" // still a string";') == []
    assert found("var r = /\\/\\/[/*]/g; x = a / b / c; // three") == ["// three"]
    assert found("if (x) return /[/*]/.test(y); // four") == ["// four"]
    assert found("var t = `a // ${b /* five */ + `c /* ${d} */`} */`;") == ["/* five */"]
    assert found("var t = `${ {a: 1}.a }` // six") == ["// six"]
    assert found("x = a++ / 2; // seven") == ["// seven"]
    assert found("x = y.return / 2 // eight") == ["// eight"]
    assert found("x = (a) / 2 /* nine */ / 3") == ["/* nine */"]
    assert found("}\n/re*/.test(s) // ten") == ["// ten"]


def test_the_comment_scanner_steps_over_css_strings_and_urls():
    def found(src):
        return [src[s:e] for s, e in css_comments(src)]

    assert found('a { content: "/* not */"; } /* one */') == ["/* one */"]
    assert found("a { background: url(data:x/*y*/z); } /* two */") == ["/* two */"]
    assert found("a { background: url( '/*q*/' ); }") == []
    assert found(r'a { content: "\"/*"; } b::after { content: "*/" }') == []
    assert found("a { --x: 1/*three*/; }") == ["/*three*/"]


def test_a_type_cast_is_the_one_comment_a_script_may_carry():
    src = ("var a = /** @type {HTMLElement} */ (q('a'));\n"
           "/** @type {HTMLElement} */\nvar b = q('b');\n"
           "f(function (/** @type {Event} */ e) {});\n"
           "var c = /** @type {X} and why */ (d);\n")
    kept = [src[s:e] for s, e in js_comments(src) if is_type_cast(src, s, e)]
    assert kept == ["/** @type {HTMLElement} */"]
    assert len(comments_in("x.js", src)) == 3


# ---- the rule

def test_a_served_script_or_stylesheet_carries_no_comment_but_an_inline_type_cast():
    """The page's bytes are code. The reasoning is in the tagalong `.md` beside each file."""
    names = served()
    assert "app.js" in names and "app.css" in names and "ink/layer.js" in names, names
    # What the pages name, and the ink layer's modules, are among what is checked.
    for asset in S.ASSETS + S.INK_LAYER_MODULES:
        assert asset in names or asset.startswith(THIRD_PARTY), asset
    found = []
    for rel in names:
        found += comments_in(rel, open(os.path.join(STATIC, rel), encoding="utf-8").read())
    assert not found, (f"{len(found)} comments in served files; the reasoning goes in the file's "
                       f"tagalong <file>.md (#523):\n" + "\n".join(found[:20]))


def test_every_served_script_and_stylesheet_has_its_tagalong_md():
    """`<file>.md` beside each, headed by the file's own path, and no tagalong without its file."""
    names = served()
    missing = [rel for rel in names if not os.path.isfile(os.path.join(STATIC, rel + ".md"))]
    assert not missing, f"no tagalong .md for: {missing}"
    for rel in names:
        head = open(os.path.join(STATIC, rel + ".md"), encoding="utf-8").readline()
        assert head.strip() == f"# `{rel}`", (rel, head)
    orphans = []
    for root, _dirs, files in os.walk(STATIC):
        for n in files:
            if n.endswith(".md"):
                rel = os.path.relpath(os.path.join(root, n), STATIC).replace(os.sep, "/")
                if rel[:-3] not in names:
                    orphans.append(rel)
    assert not orphans, f"a tagalong whose file is gone: {orphans}"


def test_a_tagalong_and_a_declarations_file_are_never_served():
    """They sit beside the page's files and are refused by the server that serves those (`UNSERVED`):
    the prose and the types are for whoever reads the source, and never cost a page load."""
    import threading
    import urllib.error
    import urllib.request

    server, token = S.build(0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/static/app.js?t={token}", timeout=10) as r:
            assert r.status == 200
        for rel in ("app.js.md", "app.css.md", "ink/layer.js.md", "app.js.d.ts"):
            assert os.path.isfile(os.path.join(STATIC, rel)), rel
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/static/{rel}?t={token}", timeout=10)
                raise AssertionError(f"/static/{rel} was served")
            except urllib.error.HTTPError as refused:
                assert refused.code == 404, (rel, refused.code)
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
