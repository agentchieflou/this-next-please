"""Fabric REST item-definition transport for Power BI reports and semantic models."""
from .client import FabricClient, FabricError

__all__ = ["FabricClient", "FabricError"]
