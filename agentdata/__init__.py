"""agentdata: normalize any tabular/JSON source into AgentTable, then emit TOON/TSV/JSON by policy."""
from .model import AgentTable
from .policy import render
from .toon import encode as toon_encode

__all__ = ["AgentTable", "render", "toon_encode", "from_df"]


def from_df(df, name="result", source="pandas"):
    """pandas.DataFrame -> AgentTable (import-free unless called)."""
    cols = [str(c) for c in df.columns]
    rows = [list(r) for r in df.astype(object).where(df.notna(), None).itertuples(index=False, name=None)]
    return AgentTable(name=name, columns=cols, rows=rows, source=source)
