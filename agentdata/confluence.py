"""Markdown -> Confluence storage format, deterministically.

Confluence does not render Markdown. A page body posted as Markdown shows up as one grey block of `#`, `-`
and backticks, which is what `confluence-publish` was doing: the skill asked the model to "write HTML" from a
Markdown file, and a cheap model pastes the Markdown through. Rule 0 of this repo is mechanize what a cheap
model gets wrong, so the model no longer writes the body at all -- this does.

Storage format is XHTML, not HTML: every tag closes, `&` `<` `>` are escaped, only XML entities exist, and code
goes inside an `ac:structured-macro`. `to_storage` returns nothing that has not been parsed as XML first, so a
page either publishes or is refused here with the text that broke it -- never rejected by Confluence.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.entities import html5

# Confluence's code macro silently drops a language it does not know; send only names it publishes.
CODE_LANGUAGES = {
    "actionscript3", "applescript", "bash", "c", "coldfusion", "cpp", "csharp", "css", "delphi", "diff",
    "erlang", "go", "groovy", "haskell", "html", "java", "javafx", "javascript", "json", "kotlin", "none",
    "objectivec", "perl", "php", "powershell", "python", "r", "ruby", "rust", "sass", "scala", "shell",
    "sql", "swift", "text", "typescript", "vb", "xml", "yaml",
}
LANGUAGE_ALIASES = {
    "sh": "bash", "zsh": "bash", "console": "bash", "shell-session": "shell", "ps": "powershell",
    "ps1": "powershell", "pwsh": "powershell", "posh": "powershell", "py": "python", "rb": "ruby",
    "js": "javascript", "ts": "typescript", "yml": "yaml", "md": "none", "markdown": "none",
    "toon": "none", "tsv": "none", "csv": "none", "txt": "text", "plain": "text",
    "dax": "none", "tmdl": "none", "jql": "sql", "psql": "sql", "cs": "csharp", "c#": "csharp",
    "htm": "html", "xhtml": "html", "jsonc": "json", "golang": "go",
}
# The two namespaces every storage-format document uses. Declared only for the validation parse.
NS = 'xmlns:ac="http://atlassian.com/content" xmlns:ri="http://atlassian.com/resource/identifier"'
# Markers for spans already converted, and for an escaped pipe inside a table cell. All three are control
# characters, which XML forbids and `_ILLEGAL` strips from the input first, so no document can forge one.
PARK_OPEN, PARK_CLOSE, PIPE = chr(0), chr(1), chr(2)
# XML 1.0 allows only these; one character outside them makes the whole page unparseable.
XML_RANGES = ((0x09, 0x0A), (0x20, 0xD7FF), (0xE000, 0xFFFD), (0x10000, 0x10FFFF))

_ILLEGAL = re.compile("[^" + "".join(f"{chr(a)}-{chr(b)}" for a, b in XML_RANGES) + "]")
_ENTITY = re.compile(r"&(#\d{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([^`\s]*).*$")
_RULE = re.compile(r"^\s{0,3}(?:-\s*-\s*-[-\s]*|\*\s*\*\s*\*[*\s]*|_\s*_\s*_[_\s]*)$")
_ITEM = re.compile(r"^(\s*)(?:([-*+])|(\d{1,9})[.)])\s+(.*)$")
_DELIM = re.compile(r"^\s*\|?(?:\s*:?-{1,}:?\s*\|)+\s*:?-{1,}:?\s*\|?\s*$")
_CODESPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
_LINK = re.compile(r"\[([^\]]*)\]\(\s*<?([^)<>\s]+)>?(?:\s+\"([^\"]*)\")?\s*\)")
_URL = re.compile(r"(?<![\w@])(https?://[^\s<>\"'\[\])]+[^\s<>\"'\[\]).,;:!?])")
_BOLD = re.compile(r"\*\*(\S(?:.*?\S)?)\*\*|__(\S(?:.*?\S)?)__", re.S)
_EM = re.compile(r"(?<![*\w])\*(\S(?:[^*]*?\S)?)\*(?!\*)|(?<![_\w])_(\S(?:[^_]*?\S)?)_(?![_\w])", re.S)
_STRIKE = re.compile(r"~~(\S(?:.*?\S)?)~~", re.S)
_PARKED = re.compile(re.escape(PARK_OPEN) + r"(\d+)" + re.escape(PARK_CLOSE))


class ConfluenceError(Exception):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


def _unentity(s: str) -> str:
    """`&mdash;` and `&#8212;` both become the character. Storage format allows only the five XML entities,
    so a named HTML entity left in place is what makes Confluence reject the whole page."""
    def sub(m: re.Match) -> str:
        body = m.group(1)
        if body[0] == "#":
            try:
                cp = int(body[2:], 16) if body[1] in "xX" else int(body[1:])
            except ValueError:
                return m.group(0)
            return chr(cp) if 0 <= cp <= 0x10FFFF else m.group(0)
        return html5.get(body + ";") or html5.get(body) or m.group(0)
    return _ENTITY.sub(sub, s)


def esc(s: str, attr: bool = False) -> str:
    s = _unentity(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s.replace('"', "&quot;") if attr else s


def plain_text(s: str) -> str:
    """A Markdown line -> the words in it. Used for the page title, which is text, not markup."""
    s = _CODESPAN.sub(lambda m: m.group(2), s)
    s = _LINK.sub(lambda m: m.group(1) or m.group(2), s)
    s = _BOLD.sub(lambda m: m.group(1) or m.group(2) or "", s)
    s = _EM.sub(lambda m: m.group(1) or m.group(2) or "", s)
    s = _STRIKE.sub(lambda m: m.group(1), s)
    return _unentity(s).strip()


def _code_language(info: str) -> str:
    lang = (info or "").strip().lower().split(",")[0]
    lang = LANGUAGE_ALIASES.get(lang, lang)
    return lang if lang in CODE_LANGUAGES else ""


def code_macro(text: str, language: str = "") -> str:
    """`]]>` inside a CDATA section ends it early and the rest of the page becomes markup. Split it instead."""
    body = text.replace("]]>", "]]]]><![CDATA[>")
    param = f'<ac:parameter ac:name="language">{esc(language)}</ac:parameter>' if language else ""
    return ('<ac:structured-macro ac:name="code" ac:schema-version="1">' + param
            + f"<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body></ac:structured-macro>")


def inline(s: str) -> str:
    """One line of Markdown -> escaped storage-format markup. Converted spans are parked as placeholders so a
    later rule cannot reach inside them: no bolding a URL, no auto-linking the href we just wrote."""
    parked: list[str] = []

    def park(html: str) -> str:
        parked.append(html)
        return PARK_OPEN + str(len(parked) - 1) + PARK_CLOSE

    s = _CODESPAN.sub(lambda m: park("<code>" + esc(m.group(2).strip()) + "</code>"), s)
    s = esc(s)
    s = _LINK.sub(lambda m: park(f'<a href="{esc(m.group(2), attr=True)}">' + (inline(m.group(1)) or esc(m.group(2))) + "</a>"), s)
    s = _URL.sub(lambda m: park(f'<a href="{m.group(1)}">{m.group(1)}</a>'), s)
    s = _STRIKE.sub(lambda m: "<s>" + m.group(1) + "</s>", s)
    s = _BOLD.sub(lambda m: "<strong>" + (m.group(1) or m.group(2)) + "</strong>", s)
    s = _EM.sub(lambda m: "<em>" + (m.group(1) or m.group(2)) + "</em>", s)
    s = re.sub(r"(?:  +|\\)$", "<br />", s)
    return _PARKED.sub(lambda m: parked[int(m.group(1))], s)


def _cells(line: str) -> list[str]:
    row = line.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") else row
    return [c.strip().replace(PIPE, "|") for c in row.replace("\\|", PIPE).split("|")]


def _alignments(delim: str) -> list[str]:
    out = []
    for c in _cells(delim):
        out.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "")
    return out


class _Lists:
    """Open `<li>`s stay open so a nested list lands inside its parent item, which is where XHTML wants it."""

    def __init__(self, out: list[str]):
        self.out: list[str] = out
        self.stack: list[tuple[int, str]] = []

    def item(self, indent: int, tag: str, html: str) -> None:
        while self.stack and indent < self.stack[-1][0]:
            self.out.append(f"</li></{self.stack.pop()[1]}>")
        if self.stack and indent == self.stack[-1][0]:
            if self.stack[-1][1] == tag:
                self.out.append(f"</li><li>{html}")
                return
            self.out.append(f"</li></{self.stack.pop()[1]}>")
        self.out.append(f"<{tag}>")
        self.stack.append((indent, tag))
        self.out.append(f"<li>{html}")

    def lazy(self, html: str) -> None:
        self.out.append(" " + html)

    def close(self) -> None:
        while self.stack:
            self.out.append(f"</li></{self.stack.pop()[1]}>")

    def __bool__(self) -> bool:
        return bool(self.stack)


def to_storage(md: str, lift_title: bool = True) -> tuple[str, dict]:
    """Markdown -> (storage-format XHTML, info). `info` carries the lifted `title` and a count per block kind,
    so a caller can see at a glance that a 40-line findings file did not collapse into one paragraph."""
    text = _ILLEGAL.sub("", md.replace("\r\n", "\n").replace("\r", "\n")).expandtabs(4)
    lines = text.split("\n")
    out: list[str] = []
    lists = _Lists(out)
    counts = {"heading": 0, "paragraph": 0, "list": 0, "table": 0, "code": 0, "quote": 0, "rule": 0}
    warnings: list[str] = []
    title = ""
    para: list[str] = []
    quote: list[str] = []
    i = 0

    def flush() -> None:
        nonlocal para, quote
        if para:
            out.append("<p>" + "\n".join(inline(x) for x in para) + "</p>")
            counts["paragraph"] += 1
            para = []
        if quote:
            inner, _ = to_storage("\n".join(quote), lift_title=False)
            out.append("<blockquote>" + inner + "</blockquote>")
            counts["quote"] += 1
            quote = []
        lists.close()

    while i < len(lines):
        line = lines[i].rstrip()
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker, body, i = fence.group(1), [], i + 1
            closer = re.compile(r"^\s{0,3}" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$")
            while i < len(lines) and not closer.match(lines[i]):
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                warnings.append("unclosed code fence: closed it at end of file")
            out.append(code_macro("\n".join(body), _code_language(fence.group(2))))
            counts["code"] += 1
            i += 1
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        head = _HEADING.match(line)
        if head:
            flush()
            level, body = len(head.group(1)), head.group(2)
            if lift_title and level == 1 and not title and not out:
                title = plain_text(body)
                i += 1
                continue
            out.append(f"<h{level}>{inline(body)}</h{level}>")
            counts["heading"] += 1
            i += 1
            continue
        if _RULE.match(line):
            flush()
            out.append("<hr />")
            counts["rule"] += 1
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _DELIM.match(lines[i + 1]) and len(_cells(line)) > 1:
            flush()
            header, align = _cells(line), _alignments(lines[i + 1])
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1

            def cell(tag: str, value: str, n: int) -> str:
                style = f' style="text-align: {align[n]};"' if n < len(align) and align[n] else ""
                return f"<{tag}{style}>{inline(value)}</{tag}>"

            body = ["<tr>" + "".join(cell("th", c, n) for n, c in enumerate(header)) + "</tr>"]
            for r in rows:
                r = (r + [""] * len(header))[:len(header)]
                body.append("<tr>" + "".join(cell("td", c, n) for n, c in enumerate(r)) + "</tr>")
            out.append("<table><tbody>" + "".join(body) + "</tbody></table>")
            counts["table"] += 1
            continue
        if line.lstrip().startswith(">"):
            if para or lists:
                flush()
            quote.append(re.sub(r"^\s*>\s?", "", line))
            i += 1
            continue
        item = _ITEM.match(line)
        if item:
            if para or quote:
                flush()
            indent, bullet, body = len(item.group(1)), item.group(2), item.group(4)
            if not lists:
                counts["list"] += 1
            lists.item(indent, "ul" if bullet else "ol", inline(body))
            i += 1
            continue
        if lists and not para:
            lists.lazy(inline(line.strip()))          # a wrapped line under the open bullet, not a new paragraph
            i += 1
            continue
        para.append(line.strip())
        i += 1
    flush()

    html = "".join(out)
    validate(html)
    return html, {"title": title, "blocks": {k: v for k, v in counts.items() if v},
                  "warnings": warnings, "chars": len(html)}


def looks_like_markdown(body: str) -> str:
    """Name the Markdown construct in a body that carries no markup at all, else "". The last gate before a
    page is posted: Confluence renders Markdown literally, so `# Findings` reaches the reader as `# Findings`.
    Requiring zero tags keeps it quiet on a real storage-format body that happens to mention a hyphen."""
    if re.search(r"<[a-zA-Z/!]", body):
        return ""
    for pattern, what in ((r"^\s{0,3}#{1,6}\s+\S", "# heading"), (r"^\s{0,3}(?:```|~~~)", "``` code fence"),
                          (r"^\s{0,3}[-*+]\s+\S", "- bullet"), (r"^\s{0,3}\d{1,9}[.)]\s+\S", "1. numbered item"),
                          (r"\[[^\]]+\]\([^)\s]+\)", "[text](link)"), (r"\*\*\S", "**bold**"),
                          (r"`[^`]+`", "`code span`"), (r"^\s*\|.*\|\s*$", "| table |")):
        if re.search(pattern, body, re.M):
            return what
    return ""


def validate(html: str) -> None:
    """Parse it as XML, because that is what Confluence does. Refusing here beats a 400 with no line number."""
    try:
        ET.fromstring(f"<root {NS}>{html}</root>")
    except ET.ParseError as e:
        _, col = getattr(e, "position", (0, 0))
        near = html[max(0, col - 60):col + 60]
        raise ConfluenceError(f"not well-formed XML: {e}" + (f" near: {near}" if near else ""),
                              hint="storage format is XHTML: every tag closes and & < > are escaped; "
                                   "if the body was hand-written, fix it at the source") from None
