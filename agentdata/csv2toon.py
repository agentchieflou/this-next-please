"""python -m agentdata.csv2toon file.csv  -> TOON via policy (used for dscmd output)."""
import csv, sys
from .model import AgentTable, _coerce
from .policy import render

p = sys.argv[1]
with open(p, newline="", encoding="utf-8-sig") as f:
    r = list(csv.reader(f))
t = AgentTable("dax", r[0], [[_coerce(v) for v in row] for row in r[1:]], source=p)
print(render(t))
