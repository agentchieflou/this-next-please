"""Local, opt-in record of what the format policy actually decided. Off by default.

`docs/data-format-policy.md` has deferred revisiting its thresholds three times -- v1 set 50/1500
and 500 as first guesses, and v1.1 and v1.2 both say "no threshold change" -- because nobody has
ever had a number to revisit them with. Nothing in this repository recorded which rule fired or
what a result cost. This is that number, and nothing more: it does not change a threshold, and
retuning one is a separate task with this file's output in hand.

**Three properties, in the order they matter.**

1. **Nothing sensitive is recorded, by construction rather than by filtering.** Only the shape of a
   result is written: which rule fired, how many rows and columns, the estimated tokens. No cell
   value, no query text, no path. In particular the command is reduced to its `ad-<name>` -- an
   `AgentTable.source` is a whole command line (`ad-td SELECT ... FROM ...`), so anything past the
   first token is thrown away rather than parsed, because a parser that keeps a subcommand also
   keeps the first word of somebody's SQL on the day the shape surprises it. A summary that says
   `ad-td` rather than `ad-td query` is worth the trade.
2. **It never leaves the machine.** This module opens a file. It imports nothing that can send one,
   and a test asserts that.
3. **It never breaks a command.** Instrumentation that can fail a query is worse than no
   instrumentation, so every write is wrapped and every failure is swallowed. That is the one place
   in this repository where a bare except is the right answer, and it is here.

Enable it with `metrics.enabled: true` in `~/.agentdata/config.json`; read it with `ad-metrics
summary`.
"""
from __future__ import annotations

import datetime
import os
import re

from . import config as C

DEFAULT_PATH = "~/.agentdata/metrics.tsv"
COLUMNS = ["ts", "command", "rule", "shape", "rows", "cols", "est_tokens"]

# The command, and only the command. Anchored, lowercase, and short: `ad-td` matches, the SQL that
# follows it cannot.
COMMAND = re.compile(r"^(ad-[a-z][a-z0-9-]{0,20})(?:\s|$)")
UNKNOWN = "unknown"

# The report reads this file; it does not get to be in it. See `record`.
SELF = "ad-metrics"

# A line longer than this is not a record this module wrote. Bounded so a corrupted file is skipped
# rather than read into memory.
MAX_LINE = 400


_CACHE: tuple[bool, str] | None = None


def _settings(cfg: dict | None = None) -> tuple[bool, str]:
    """(enabled, path), resolved once per process.

    `record()` runs on every rendered result. Reading and parsing `~/.agentdata/config.json` each
    time would make everyone pay for a feature that is off by default, so the answer is cached: a
    config file does not change under a running command, and `reset_cache()` is how the tests and
    `--pretty`-style re-reads get a fresh one.
    """
    global _CACHE
    if cfg is not None:
        return bool(C.get(cfg, "metrics.enabled")), _path_from(cfg)
    if _CACHE is None:
        loaded = C.load()
        _CACHE = (bool(C.get(loaded, "metrics.enabled")), _path_from(loaded))
    return _CACHE


def _path_from(cfg: dict) -> str:
    return C.expand(str(C.get(cfg, "metrics.path") or DEFAULT_PATH))


def reset_cache() -> None:
    global _CACHE
    _CACHE = None


def enabled(cfg: dict | None = None) -> bool:
    """Off unless the config says otherwise. Never an environment variable: turning on a file that
    accumulates should take an edit somebody can see afterwards."""
    return _settings(cfg)[0]


def path(cfg: dict | None = None) -> str:
    return _settings(cfg)[1]


def command_of(source: str) -> str:
    """`ad-td SELECT * FROM accounts` -> `ad-td`. Anything else -> `unknown`."""
    m = COMMAND.match((source or "").strip())
    return m.group(1) if m else UNKNOWN


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(*, source: str, rule: int, shape: str, rows: int, cols: int, est_tokens: int) -> list[str]:
    """One record, as strings. Every field is a count, a name this module chose, or a clock."""
    return [now(), command_of(source), str(int(rule)), str(shape or ""), str(int(rows)),
            str(int(cols)), str(int(est_tokens))]


def record(*, source: str, rule: int, shape: str, rows: int, cols: int, est_tokens: int,
           cfg: dict | None = None) -> bool:
    """Append one line if recording is on. Returns whether it wrote; never raises.

    A failure here -- unwritable home directory, a full disk, a config that will not parse -- must
    not fail the command the user actually ran, so everything is swallowed.
    """
    try:
        on, dest = _settings(cfg)
        if not on or command_of(source) == SELF:
            # The report is a rendered result like any other, so it would record itself -- and
            # `ad-metrics` rows would accumulate in the very file whose point is saying which
            # commands are expensive. Measuring the ruler is not measurement.
            return False
        return _append(dest, row(source=source, rule=rule, shape=shape, rows=rows, cols=cols,
                                 est_tokens=est_tokens))
    except Exception:                             # noqa: BLE001 - see the module docstring
        return False


def _append(dest: str, values: list[str]) -> bool:
    """UTF-8, no BOM, LF -- the same bytes `textio.write_text` produces.

    Appended rather than rewritten: `write_text` replaces a file atomically, which is right for an
    artifact and wrong for a log that two commands may reach at the same moment. A short line
    appended in one call is the part POSIX and Windows both keep whole.
    """
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    new = not os.path.exists(dest)
    with open(dest, "a", encoding="utf-8", newline="") as f:
        if new:
            f.write("\t".join(COLUMNS) + "\n")
        f.write("\t".join(v.replace("\t", " ").replace("\n", " ") for v in values) + "\n")
    return True


# ------------------------------------------------------------------------------- reading it back


def read(dest: str | None = None, cfg: dict | None = None) -> list[dict]:
    """Every record, skipping the header and anything that does not look like one.

    Tolerant on purpose: this file is appended to by concurrent processes, and one torn line should
    cost one row, not the report.
    """
    dest = dest or path(cfg)
    if not os.path.exists(dest):
        return []
    out = []
    with open(dest, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line or len(line) > MAX_LINE or line.startswith(COLUMNS[0] + "\t"):
                continue
            parts = line.split("\t")
            if len(parts) != len(COLUMNS):
                continue
            record_ = dict(zip(COLUMNS, parts))
            try:
                for number in ("rule", "rows", "cols", "est_tokens"):
                    record_[number] = int(record_[number])
            except ValueError:
                continue
            out.append(record_)
    return out


SUMMARY_COLS = ["group", "key", "calls", "rows_total", "tokens_total", "tokens_median", "tokens_max"]


def summary(records: list[dict]) -> list[list]:
    """Per rule and per command: how often, and what it cost.

    The median as well as the total, because the question these thresholds turn on is what a
    *typical* result costs -- one 400,000-row export moves a mean and answers nothing.
    """
    rows = []
    for group, field in (("rule", "rule"), ("command", "command")):
        buckets: dict = {}
        for r in records:
            buckets.setdefault(r[field], []).append(r)
        for key in sorted(buckets, key=lambda k: (-len(buckets[k]), str(k))):
            got = buckets[key]
            tokens = sorted(r["est_tokens"] for r in got)
            rows.append([group, str(key), len(got), sum(r["rows"] for r in got), sum(tokens),
                         tokens[len(tokens) // 2], tokens[-1]])
    return rows


def totals(records: list[dict]) -> dict:
    if not records:
        return {"records": 0}
    tokens = sorted(r["est_tokens"] for r in records)
    return {"records": len(records), "commands": len({r["command"] for r in records}),
            "tokens_total": sum(tokens), "tokens_median": tokens[len(tokens) // 2],
            "tokens_max": tokens[-1],
            "first": min(r["ts"] for r in records), "last": max(r["ts"] for r in records)}
