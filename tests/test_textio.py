"""Files other tools wrote: Windows PowerShell 5.1 adds a UTF-8 BOM (Set-Content -Encoding utf8, Out-File) or writes
UTF-16 (`>`); Notepad may save cp1252. Every reader must cope; every writer stays UTF-8 without BOM."""
import sys
import pytest

from agentdata import cli_sqlcheck, textio
from agentdata.model import AgentTable


def test_decode_boms_and_fallbacks():
    assert textio.decode("héllo".encode("utf-8-sig")) == "héllo"
    assert textio.decode(b"\xff\xfe" + "héllo".encode("utf-16-le")) == "héllo"      # PowerShell `>` / Out-File default
    assert textio.decode(b"\xfe\xff" + "héllo".encode("utf-16-be")) == "héllo"
    assert textio.decode("abc\n".encode("utf-16-le")) == "abc\n"                     # BOM-less UTF-16 LE
    assert textio.decode("plain ü".encode("utf-8")) == "plain ü"
    assert textio.decode(b"caf\xe9") == "café"                                       # Notepad ANSI (cp1252)
    assert textio.decode(b"") == ""


def test_read_json_any_encoding_and_error_names_the_file(tmp_path):
    p = tmp_path / "answers.json"
    p.write_bytes('{"project.jira_project": "RDSD"}'.encode("utf-8-sig"))
    assert textio.read_json(str(p)) == {"project.jira_project": "RDSD"}
    p.write_bytes(b"\xff\xfe" + '{"a": 1}'.encode("utf-16-le"))
    assert textio.read_json(str(p)) == {"a": 1}
    p.write_bytes(b"\xef\xbb\xbf{not json")
    with pytest.raises(ValueError) as e:
        textio.read_json(str(p), "answers file")
    assert "answers file is not valid JSON" in str(e.value) and "answers.json" in str(e.value)


def test_write_text_is_utf8_no_bom_lf_and_atomic(tmp_path):
    p = str(tmp_path / "sub" / "y.txt")
    assert textio.write_text(p, "a\nb\n").endswith("sub/y.txt")
    assert open(p, "rb").read() == b"a\nb\n"
    textio.write_json(p, {"k": "vä"})
    raw = open(p, "rb").read()
    assert raw == b'{\n  "k": "v\xc3\xa4"\n}\n' and not (tmp_path / "sub" / "y.txt.tmp").exists()


def test_read_tsv_with_bom_and_utf16(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_bytes("a\tb\n1\tx\n".encode("utf-8-sig"))
    t = AgentTable.read_tsv(str(p))
    assert t.columns == ["a", "b"] and t.rows == [[1, "x"]]
    p.write_bytes(b"\xff\xfe" + "a\tb\r\n1\tx\r\n".encode("utf-16-le"))
    t = AgentTable.read_tsv(str(p))
    assert t.columns == ["a", "b"] and t.rows == [[1, "x"]]


def test_sql_check_strips_bom_from_sql_file(tmp_path, monkeypatch, capsys):
    p = tmp_path / "q.sql"
    p.write_bytes("SELECT 1".encode("utf-8-sig"))
    seen = {}
    monkeypatch.setattr(cli_sqlcheck, "check", lambda sql, dialect, caps: seen.update(sql=sql) or [])
    monkeypatch.setattr(sys, "argv", ["ad-sql-check", "--dialect", "teradata", str(p)])
    with pytest.raises(SystemExit) as e:
        cli_sqlcheck.main()
    assert e.value.code == 0 and seen["sql"] == "SELECT 1"
