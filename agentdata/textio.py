"""Reading files other tools wrote. Windows PowerShell 5.1 writes a UTF-8 BOM with `Set-Content -Encoding utf8` /
`Out-File`, and UTF-16 LE with `>`; Notepad may save cp1252. Every `ad-*` reader goes through here so a worker model
can write a file any way its shell likes and the loader still copes. Writers stay UTF-8 without BOM, LF."""
from __future__ import annotations
import json
import locale
import os

BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe\x00\x00", "utf-32-le"), (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be"))


def decode(raw: bytes) -> str:
    """BOM-sniffed decode; without a BOM: UTF-8, then the console's preferred encoding, then cp1252, then latin-1."""
    for bom, enc in BOMS:
        if raw.startswith(bom):
            return raw[len(bom):].decode(enc) if enc != "utf-8-sig" else raw.decode(enc)
    if len(raw) >= 2 and raw[1:2] == b"\x00" and raw[0:1] != b"\x00":   # BOM-less UTF-16 LE (ASCII text)
        try:
            return raw.decode("utf-16-le")
        except UnicodeDecodeError:
            pass
    tried = ["utf-8"]
    pref = locale.getpreferredencoding(False) or ""
    if pref and pref.lower().replace("-", "") not in ("utf8", "cp65001"):
        tried.append(pref)
    tried += ["cp1252", "latin-1"]
    for enc in tried:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1")


def read_text(path: str) -> str:
    with open(path, "rb") as f:
        return decode(f.read()).lstrip("﻿")


def read_json(path: str, what: str = "file"):
    """JSON from any encoding PowerShell/Notepad produce. Raises ValueError with the path on bad JSON."""
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as e:
        raise ValueError(f"{what} is not valid JSON: {path} ({e.msg}, line {e.lineno})") from None


def write_text(path: str, text: str) -> str:
    """UTF-8 without BOM, LF, atomic replace. Returns the path with forward slashes."""
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)
    return path.replace("\\", "/")


def write_json(path: str, data, indent: int = 2) -> str:
    return write_text(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")
