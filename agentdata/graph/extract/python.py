"""Python AST extractor (stdlib ast) extracting file, class, function, test nodes and edges."""
from __future__ import annotations
import ast
import hashlib
import os
from typing import Any

from . import Extractor
from ..model import Edge, Node
from ..tags import is_io_call

BRANCH_TYPES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.IfExp,
)


def calc_complexity(node: ast.AST) -> int:
    """Cyclomatic complexity: 1 + number of branches."""
    count = 1
    for child in ast.walk(node):
        if isinstance(child, BRANCH_TYPES):
            count += 1
        elif isinstance(child, ast.BoolOp):
            # Each 'and'/'or' adds an alternative branch
            count += len(child.values) - 1
    return count


def resolve_call_name(node: ast.AST) -> str:
    """Extract string representation of call target."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = resolve_call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


class PythonExtractor(Extractor):
    name: str = "python"

    def extract(
        self, relpath: str, text: str, project_context: dict[str, Any] | None = None
    ) -> tuple[list[Node], list[Edge]]:
        norm_path = relpath.replace("\\", "/")
        file_name = os.path.basename(norm_path)
        lines = text.splitlines(keepends=True)
        total_loc = max(1, len(lines))
        file_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()

        context = project_context or {}
        entrypoint_targets = set(context.get("entrypoints", []))  # e.g. "path/to/file.py::func"

        nodes: list[Node] = []
        edges: list[Edge] = []

        is_test_file = (
            "test" in file_name.lower()
            or norm_path.startswith("tests/")
            or "/tests/" in norm_path
        )

        try:
            tree = ast.parse(text, filename=norm_path)
        except SyntaxError:
            # If parse fails, fallback to basic file node
            file_node = Node(
                id=norm_path,
                kind="file",
                name=file_name,
                where=f"{norm_path}:1-{total_loc}",
                sha=file_sha,
                loc=total_loc,
                complexity=1,
                tags=[],
            )
            return [file_node], []

        file_tags: list[str] = []
        if norm_path.endswith("__main__.py"):
            file_tags.append("entrypoint")

        file_node = Node(
            id=norm_path,
            kind="file",
            name=file_name,
            where=f"{norm_path}:1-{total_loc}",
            sha=file_sha,
            loc=total_loc,
            complexity=1,
            tags=file_tags,
        )
        nodes.append(file_node)

        # Track imported names: alias/name -> module_or_target
        imports_map: dict[str, str] = {}
        # Track defined top-level and class symbols
        defined_symbols: dict[str, str] = {}  # name -> node_id

        # First pass: collect imports and if __name__ == "__main__"
        main_block_calls: set[str] = set()

        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    name = alias.asname or alias.name
                    target = alias.name
                    imports_map[name] = target
                    edges.append(
                        Edge(
                            source=norm_path,
                            target=f"ext:{target}",
                            kind="imports",
                            where=f"{norm_path}:{stmt.lineno}",
                            source_type="static",
                        )
                    )
            elif isinstance(stmt, ast.ImportFrom):
                mod = stmt.module or ""
                for alias in stmt.names:
                    name = alias.asname or alias.name
                    target = f"{mod}.{alias.name}" if mod else alias.name
                    imports_map[name] = target
                    edges.append(
                        Edge(
                            source=norm_path,
                            target=f"ext:{mod}" if mod else f"ext:{target}",
                            kind="imports",
                            where=f"{norm_path}:{stmt.lineno}",
                            source_type="static",
                        )
                    )
            elif isinstance(stmt, ast.If):
                # Check for if __name__ == "__main__":
                is_main = False
                test = stmt.test
                if isinstance(test, ast.Compare):
                    if (
                        isinstance(test.left, ast.Name)
                        and test.left.id == "__name__"
                    ):
                        for comp in test.comparators:
                            if isinstance(comp, ast.Constant) and comp.value == "__main__":
                                is_main = True
                if is_main:
                    file_node.tags = sorted(list(set(file_node.tags + ["entrypoint"])))
                    for inner in ast.walk(stmt):
                        if isinstance(inner, ast.Call):
                            cname = resolve_call_name(inner.func)
                            if cname:
                                main_block_calls.add(cname)

        # Helper to compute source sha for AST node
        def get_source_slice_sha(lineno: int, end_lineno: int) -> tuple[str, int]:
            sub_lines = lines[lineno - 1 : end_lineno]
            sub_text = "".join(sub_lines)
            return hashlib.sha256(sub_text.encode("utf-8")).hexdigest(), len(sub_lines)

        # Helper to extract calls within a function
        def extract_calls(
            fn_node: ast.FunctionDef | ast.AsyncFunctionDef,
            fn_id: str,
            class_name: str | None = None,
        ) -> tuple[list[Edge], bool]:
            fn_edges: list[Edge] = []
            has_io = False

            # Stack-based AST visitor to track loop depth
            class CallVisitor(ast.NodeVisitor):
                def __init__(self) -> None:
                    self.loop_depth = 0

                def visit_For(self, node: ast.For) -> None:
                    self.loop_depth += 1
                    self.generic_visit(node)
                    self.loop_depth -= 1

                def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
                    self.loop_depth += 1
                    self.generic_visit(node)
                    self.loop_depth -= 1

                def visit_While(self, node: ast.While) -> None:
                    self.loop_depth += 1
                    self.generic_visit(node)
                    self.loop_depth -= 1

                def visit_Call(self, node: ast.Call) -> None:
                    nonlocal has_io
                    cname = resolve_call_name(node.func)
                    if cname:
                        if is_io_call(cname):
                            has_io = True

                        target_id: str
                        if class_name and (cname.startswith("self.") or cname.startswith("cls.")):
                            method = cname.split(".", 1)[1]
                            target_id = f"{norm_path}::{class_name}.{method}"
                        elif cname in defined_symbols:
                            target_id = defined_symbols[cname]
                        elif cname in imports_map:
                            target_id = f"ext:{imports_map[cname]}"
                        else:
                            target_id = f"unresolved:{cname}"

                        context_data: dict[str, Any] = {}
                        if self.loop_depth > 0:
                            context_data["loop_depth"] = self.loop_depth

                        fn_edges.append(
                            Edge(
                                source=fn_id,
                                target=target_id,
                                kind="calls",
                                source_type="static",
                                where=f"{norm_path}:{node.lineno}",
                                context=context_data,
                            )
                        )
                    self.generic_visit(node)

            CallVisitor().visit(fn_node)
            return fn_edges, has_io

        # Pass 2: Discover classes and functions
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_id = f"{norm_path}::{stmt.name}"
                defined_symbols[stmt.name] = fn_id
            elif isinstance(stmt, ast.ClassDef):
                cls_id = f"{norm_path}::{stmt.name}"
                defined_symbols[stmt.name] = cls_id
                for item in stmt.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_id = f"{norm_path}::{stmt.name}.{item.name}"
                        defined_symbols[f"{stmt.name}.{item.name}"] = method_id

        # Pass 3: Construct nodes and edges
        for stmt in tree.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_lineno = stmt.end_lineno or stmt.lineno
                fn_sha, fn_loc = get_source_slice_sha(stmt.lineno, end_lineno)
                fn_id = f"{norm_path}::{stmt.name}"
                fn_complexity = calc_complexity(stmt)

                fn_calls, has_io = extract_calls(stmt, fn_id)
                edges.extend(fn_calls)

                # Determine kind
                is_test = (
                    is_test_file
                    and (stmt.name.startswith("test_") or stmt.name.startswith("test"))
                )
                kind = "test" if is_test else "function"

                # Determine tags
                tags: list[str] = []
                if (
                    fn_id in entrypoint_targets
                    or stmt.name in main_block_calls
                    or (norm_path.endswith("__main__.py") and stmt.name == "main")
                ):
                    tags.append("entrypoint")
                if has_io:
                    tags.append("io")

                fn_node = Node(
                    id=fn_id,
                    kind=kind,
                    name=stmt.name,
                    where=f"{norm_path}:{stmt.lineno}-{end_lineno}",
                    sha=fn_sha,
                    loc=fn_loc,
                    complexity=fn_complexity,
                    tags=tags,
                )
                nodes.append(fn_node)
                edges.append(
                    Edge(
                        source=norm_path,
                        target=fn_id,
                        kind="defines",
                        source_type="static",
                        where=f"{norm_path}:{stmt.lineno}",
                    )
                )

                # Heuristic tests edge: test_foo -> foo
                if is_test:
                    target_name = stmt.name
                    if target_name.startswith("test_"):
                        target_name = target_name[5:]
                    elif target_name.startswith("test"):
                        target_name = target_name[4:].lstrip("_")
                    if target_name:
                        # Link by name
                        edges.append(
                            Edge(
                                source=fn_id,
                                target=f"name:{target_name}",
                                kind="tests",
                                source_type="name",
                                where=f"{norm_path}:{stmt.lineno}",
                            )
                        )

            elif isinstance(stmt, ast.ClassDef):
                end_lineno = stmt.end_lineno or stmt.lineno
                cls_sha, cls_loc = get_source_slice_sha(stmt.lineno, end_lineno)
                cls_id = f"{norm_path}::{stmt.name}"
                cls_complexity = calc_complexity(stmt)

                cls_node = Node(
                    id=cls_id,
                    kind="class",
                    name=stmt.name,
                    where=f"{norm_path}:{stmt.lineno}-{end_lineno}",
                    sha=cls_sha,
                    loc=cls_loc,
                    complexity=cls_complexity,
                    tags=[],
                )
                nodes.append(cls_node)
                edges.append(
                    Edge(
                        source=norm_path,
                        target=cls_id,
                        kind="defines",
                        source_type="static",
                        where=f"{norm_path}:{stmt.lineno}",
                    )
                )

                # Class methods
                for item in stmt.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_end = item.end_lineno or item.lineno
                        m_sha, m_loc = get_source_slice_sha(item.lineno, m_end)
                        method_id = f"{norm_path}::{stmt.name}.{item.name}"
                        m_complexity = calc_complexity(item)

                        m_calls, has_io = extract_calls(item, method_id, class_name=stmt.name)
                        edges.extend(m_calls)

                        is_test = (
                            is_test_file
                            and (item.name.startswith("test_") or item.name.startswith("test"))
                        )
                        kind = "test" if is_test else "function"

                        tags = []
                        if method_id in entrypoint_targets:
                            tags.append("entrypoint")
                        if has_io:
                            tags.append("io")

                        method_node = Node(
                            id=method_id,
                            kind=kind,
                            name=f"{stmt.name}.{item.name}",
                            where=f"{norm_path}:{item.lineno}-{m_end}",
                            sha=m_sha,
                            loc=m_loc,
                            complexity=m_complexity,
                            tags=tags,
                        )
                        nodes.append(method_node)
                        edges.append(
                            Edge(
                                source=cls_id,
                                target=method_id,
                                kind="contains",
                                source_type="static",
                                where=f"{norm_path}:{item.lineno}",
                            )
                        )

                        if is_test:
                            target_name = item.name
                            if target_name.startswith("test_"):
                                target_name = target_name[5:]
                            elif target_name.startswith("test"):
                                target_name = target_name[4:].lstrip("_")
                            if target_name:
                                edges.append(
                                    Edge(
                                        source=method_id,
                                        target=f"name:{target_name}",
                                        kind="tests",
                                        source_type="name",
                                        where=f"{norm_path}:{item.lineno}",
                                    )
                                )

        return nodes, edges
