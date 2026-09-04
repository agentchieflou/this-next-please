"""Extractor base interface for source code graph extraction."""
from __future__ import annotations
import abc
from typing import Any

from ..model import Edge, Node


class Extractor(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def extract(self, relpath: str, text: str, project_context: dict[str, Any] | None = None) -> tuple[list[Node], list[Edge]]:
        """Extract nodes and edges from source text."""
        raise NotImplementedError
