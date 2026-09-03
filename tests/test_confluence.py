"""Markdown -> Confluence storage format.

The bug this file guards shipped: the page body went up as raw Markdown, so the reader got `## mismatch` and
`- L-1001` as literal text. Everything here is about the two ways that happens -- nobody converted, or the
"conversion" produced markup Confluence rejects -- plus the escaping that a hand-written body always gets wrong.
"""
import xml.etree.ElementTree as ET

import pytest

from agentdata import cli_confluence as CLI
from agentdata import confluence as C

FINDINGS = """# RDSD-22399 UAT findings — 2026-09-03

key `loan_id` · metrics amount · window 2026-01-01..2026-03-31

## mismatch — the tiers disagree **materially**

- L-1001 amount: hist 1,200.00 < pbi 1,250.00 — warehouse & report differ
- L-1002 rate: 3 > 2
  - nested note

| key | expected | pbi |
| --- | -------: | --: |
| L-1001 | 1,250.00 | 1,250.00 |

```sql
SELECT loan_id FROM t WHERE x < 5 AND y > 2;
```

> Do not patch the warehouse to match the report.

See https://example.atlassian.net/browse/RDSD-22399 and [the run](.agent/out/r.tsv).
"""


AC = "{http://atlassian.com/content}"


def parse(html):
    """Storage format is XHTML; this is the same parse Confluence does before it accepts a page."""
    return ET.fromstring(f"<root {C.NS}>{html}</root>")


def test_a_findings_file_becomes_markup_not_text():
    html, info = C.to_storage(FINDINGS)
    root = parse(html)
    assert info["title"] == "RDSD-22399 UAT findings — 2026-09-03"      # lifted, so the page does not repeat it
    assert "RDSD-22399 UAT findings" not in html
    assert info["blocks"] == {"heading": 1, "paragraph": 2, "list": 1, "table": 1, "code": 1, "quote": 1}
    assert [e.tag for e in root] == ["p", "h2", "ul", "table", AC + "structured-macro", "blockquote", "p"]
    assert "#" not in html and "- L-1001" not in html                    # no Markdown survived
    assert root.find("h2/strong").text == "materially"
    assert len(root.findall("ul/li")) == 2 and root.find("ul/li/ul/li").text.strip() == "nested note"
    assert [e.tag for e in root.findall("table/tbody/tr/*")[:3]] == ["th", "th", "th"]
    assert root.find('table/tbody/tr[2]/td[2]').get("style") == "text-align: right;"


def test_the_characters_that_break_a_hand_written_body():
    html, _ = C.to_storage("a < b & c > d and 5 \"quoted\" <notatag>")
    assert "&lt;" in html and "&amp;" in html and "&gt;" in html
    assert parse(html).find("p").text == 'a < b & c > d and 5 "quoted" <notatag>'   # round trips to the same text


def test_named_entities_become_characters_because_storage_format_has_only_five():
    html, _ = C.to_storage("2026 &mdash; done &amp; dusted &#8212; &nbsp;x &notarealentity;")
    text = parse(html).find("p").text
    assert "—" in text and "& dusted" in text and " x" in text
    assert "&notarealentity;" in text                                     # unknown: kept as visible text, not markup


def test_code_blocks_use_the_macro_and_survive_cdata_hostile_content():
    html, info = C.to_storage("```python\nif a < b and c > d: x = '&'\n```")
    macro = parse(html).find(AC + "structured-macro")
    assert macro.get(AC + "name") == "code"
    assert macro.find(AC + "parameter").text == "python"
    assert macro.find(AC + "plain-text-body").text == "if a < b and c > d: x = '&'"   # raw, not escaped
    html, _ = C.to_storage("```\nprintf(\"]]>\");\n```")
    assert parse(html).find(f"{AC}structured-macro/{AC}plain-text-body").text == 'printf("]]>");'
    assert C.to_storage("```pwsh\nls\n```")[0].count("powershell") == 1   # alias
    assert "ac:parameter" not in C.to_storage("```klingon\nls\n```")[0]   # unknown: no parameter, not a bad one
    assert info["blocks"]["code"] == 1


def test_an_unclosed_fence_is_reported_not_dropped():
    html, info = C.to_storage("text\n\n```sql\nSELECT 1")
    assert "SELECT 1" in html and info["warnings"] == ["unclosed code fence: closed it at end of file"]


def test_links_are_converted_once_and_never_nested():
    html, _ = C.to_storage("[a **b**](https://x.test/q?a=1&b=2) then https://y.test/p, done")
    root = parse(html)
    hrefs = [a.get("href") for a in root.iter("a")]
    assert hrefs == ["https://x.test/q?a=1&b=2", "https://y.test/p"]       # the & is escaped in the source, decoded here
    assert root.find("p/a/strong").text == "b"
    assert root.findall("p/a")[1].text == "https://y.test/p"               # trailing comma not swallowed
    assert "<a href=\"<a" not in html                                      # the autolinker did not reach into the href


def test_inline_code_is_not_re_marked_up():
    html, _ = C.to_storage("use `--body <html>` and `a * b * c`, not *this*")
    root = parse(html)
    assert [c.text for c in root.iter("code")] == ["--body <html>", "a * b * c"]
    assert root.find("p/em").text == "this"
    assert "<em>" not in html.split("</code>")[0]


def test_every_shape_stays_well_formed_under_junk():
    for md in ["", "   \n\n", "#", "- ", "|", "|a|\n|-|\n|b|c|d|", "> \n> \n", "***", "1) one\n2) two",
               "- a\n    - b\n  - c\n- d", "a\nb\n\nc", "text\x00with\x07control\x08chars", "#### deep"]:
        html, _ = C.to_storage(md)
        parse(html)                                                        # raises if not well-formed
    assert "\x00" not in C.to_storage("text\x00park\x01forge\x02")[0]      # placeholders cannot be forged


def test_validate_refuses_a_body_confluence_would_reject():
    C.validate("<p>fine</p><br /><ac:structured-macro ac:name='x' />")
    with pytest.raises(C.ConfluenceError) as e:
        C.validate("<p>unclosed<br>and & bare")
    assert "not well-formed" in str(e.value) and "XHTML" in e.value.hint


@pytest.mark.parametrize("body,why", [
    ("## Findings\n\ntext", "# heading"),
    ("- one\n- two", "- bullet"),
    ("```sql\nSELECT 1\n```", "``` code fence"),
    ("see [the run](x.tsv)", "[text](link)"),
    ("| a | b |\n| - | - |", "| table |"),
    ("<h2>Findings</h2><ul><li>- not a bullet</li></ul>", ""),            # real markup: silent
    ("<p># 1 on the list</p>", ""),
    ("plain sentence with a - hyphen and 5 * 3", ""),
])
def test_markdown_is_recognised_before_it_is_published(body, why):
    assert C.looks_like_markdown(body) == why


def test_cli_writes_the_body_and_names_the_publish_command(tmp_path, capsys):
    src = tmp_path / "RDSD-1-uat-findings.md"
    src.write_text(FINDINGS, encoding="utf-8")
    out = tmp_path / "page.html"
    assert CLI.main(["html", str(src), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    parse(out.read_text(encoding="utf-8"))
    assert "ok: true" in printed and "--body-file" in printed and "create-page" in printed
    assert "title: RDSD-22399 UAT findings" in printed and "table: 1" in printed
    assert CLI.main(["check", str(out)]) == 0 and "well_formed: true" in capsys.readouterr().out


def test_cli_defaults_the_output_beside_the_source_and_can_keep_the_title(tmp_path, capsys):
    src = tmp_path / "notes.md"
    src.write_text("# Title\n\nbody\n", encoding="utf-8")
    assert CLI.main(["html", str(src)]) == 0
    assert (tmp_path / "notes.html").read_text(encoding="utf-8") == "<p>body</p>"
    capsys.readouterr()
    assert CLI.main(["html", str(src), "--keep-title", "--stdout"]) == 0
    assert capsys.readouterr().out.strip() == "<h1>Title</h1><p>body</p>"


def test_cli_refuses_a_hand_written_body_it_cannot_parse(tmp_path, capsys):
    bad = tmp_path / "hand.html"
    bad.write_text("<p>unclosed<br>", encoding="utf-8")
    assert CLI.main(["check", str(bad)]) == 2
    out = capsys.readouterr().out
    assert "ok: false" in out and "hint:" in out
