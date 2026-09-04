"""Generic text-based extractor for non-Python or unknown languages."""
from __future__ import annotations
import hashlib
import os
import re
from typing import Any

from . import Extractor
from ..model import Edge, Node

# Regex tables per language/extension
RE_JS_TS_IMPORT = re.compile(r"""(?:import\s+.*?from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""")
RE_CSHARP_USING = re.compile(r"""^\s*using\s+([A-Za-z0-9_.]+);""", re.MULTILINE)
RE_JAVA_IMPORT = re.compile(r"""^\s*import\s+(?:static\s+)?([A-Za-z0-9_.]+);""", re.MULTILINE)
RE_SQL_TABLE = re.compile(r"""\b(?:FROM|JOIN)\s+([A-Za-z0-9_."]+)""", re.IGNORECASE)
RE_TMDL_REF = re.compile(r"""\bref\s+table\s+['"]?([A-Za-z0-9_ ]+)['"]?""", re.IGNORECASE)


class GenericExtractor(Extractor):
    name: str = "generic"

    def extract(self, relpath: str, text: str, project_context: dict[str, Any] | None = None) -> tuple[list[Node], list[Edge]]:
        lines = text.splitlines()
        loc = max(1, len(lines))
        file_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        norm_path = relpath.replace("\\", "/")
        file_name = os.path.basename(norm_path)

        file_node = Node(
            id=norm_path,
            kind="file",
            name=file_name,
            where=f"{norm_path}:1-{loc}",
            sha=file_sha,
            loc=loc,
            complexity=1,
            tags=[],
        )

        nodes: list[Node] = [file_node]
        edges: list[Edge] = []

        ext = os.path.splitext(norm_path)[1].lower()

        # Extract language-specific imports / refs
        if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
            for m in RE_JS_TS_IMPORT.finditer(text):
                mod = m.group(1) or m.group(2)
                if mod:
                    edges.append(Edge(source=norm_path, target=f"ext:{mod}", kind="imports", source_type="static"))
        elif ext in (".cs", ".csx"):
            for m in RE_CSHARP_USING.finditer(text):
                ns = m.group(1)
                edges.append(Edge(source=norm_path, target=f"ext:{ns}", kind="imports", source_type="static"))
        elif ext in (".java", ".kt", ".scala"):
            for m in RE_JAVA_IMPORT.finditer(text):
                ns = m.group(1)
                edges.append(Edge(source=norm_path, target=f"ext:{ns}", kind="imports", source_type="static"))
        elif ext in (".sql", ".hql"):
            for m in RE_SQL_TABLE.finditer(text):
                tbl = m.group(1).strip('"')
                if tbl.upper() not in ("SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT"):
                    edges.append(Edge(source=norm_path, target=f"ext:{tbl}", kind="imports", source_type="static"))
        elif ext in (".tmdl", ".dax"):
            for m in RE_TMDL_REF.finditer(text):
                tbl = m.group(1)
                edges.append(Edge(source=norm_path, target=f"ext:{tbl}", kind="imports", source_type="static"))

        return nodes, edges
