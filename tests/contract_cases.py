"""One safe invocation per `ad-*` command, for the black-box contract test.

Every entry in `[project.scripts]` must appear here. Adding a command without one fails
`tests/test_contract.py` with a message naming it, so coverage is by construction rather than by
somebody remembering.

"Safe" means: no network, no writes outside the temp directory the test provides, and no dependence
on a tool being installed. A command whose real work needs a network or a licensed tool contributes
`--help` — which still proves the parser builds, the module imports, and the exit code is right.
"""
from __future__ import annotations
import os

# args -> the arguments after the command name.
# needs -> fixtures the case wants prepared; see `prepare()` below.
# toon -> whether stdout is expected to be TOON (a bare --help is not).
CASES: dict[str, dict] = {
    "doctor":     {"args": ["--quiet"], "toon": True},
    "update":     {"args": ["--check"], "toon": True},
    "state":      {"args": ["show"], "needs": ["state"], "toon": True},
    "help":       {"args": [], "toon": False},
    "view":       {"args": ["@tsv"], "needs": ["tsv"], "toon": True},
    "diff":       {"args": ["@tsv", "@tsv2", "--key", "id"], "needs": ["tsv", "tsv2"], "toon": True},
    "sql-check":  {"args": ["--dialect", "teradata", "--sql", "SELECT 1"], "toon": True},
    "graph":      {"args": ["build", "@repo", "--out", "@graphdir"], "needs": ["repo"], "toon": True},
    "test":       {"args": ["detect", "@repo"], "needs": ["repo"], "toon": True},
    "argv":       {"args": ["--", "one", "two"], "toon": True},
    # `repo list` on an empty registry: no `copilot`, no processes, and the fleet directory is the
    # temporary AGENTDATA_CONFIG's, so this touches nothing outside the test's own tmp dir.
    "fleet":      {"args": ["repo", "list"], "toon": True},

    # These reach a network, a licensed tool, or a Power BI install. `--help` still proves the
    # module imports, the parser builds, and the exit code is 0 -- which is most of what breaks.
    "setup":      {"args": ["--help"], "toon": False},
    "jira":       {"args": ["--help"], "toon": False},
    "pbip":       {"args": ["--help"], "toon": False},
    "pbi":        {"args": ["--help"], "toon": False},
    "pbiviz":     {"args": ["--help"], "toon": False},
    "uat":        {"args": ["--help"], "toon": False},
    "dpm":        {"args": ["--help"], "toon": False},
    "confluence": {"args": ["--help"], "toon": False},
    "pncli":      {"args": ["--help"], "toon": False},
    "td":         {"args": ["--help"], "toon": False},
    "ora":        {"args": ["--help"], "toon": False},
    "hive":       {"args": ["--help"], "toon": False},
    "impala":     {"args": ["--help"], "toon": False},
}


def prepare(tmp_path) -> dict[str, str]:
    """Materialise the fixtures the cases refer to as `@name`."""
    from agentdata import textio

    made: dict[str, str] = {}

    state = os.path.join(str(tmp_path), ".agent", "state.json")
    textio.write_json(state, {"project": "TEST", "phase": "idle", "open_questions": [],
                              "artifacts": [], "tools": {}})
    made["state"] = state

    tsv = os.path.join(str(tmp_path), "a.tsv")
    textio.write_text(tsv, "id\tvalue\n1\tone\n2\ttwo\n")
    made["tsv"] = tsv

    tsv2 = os.path.join(str(tmp_path), "b.tsv")
    textio.write_text(tsv2, "id\tvalue\n1\tone\n2\tTWO\n")
    made["tsv2"] = tsv2

    repo = os.path.join(str(tmp_path), "repo")
    textio.write_text(os.path.join(repo, "pyproject.toml"), '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    textio.write_text(os.path.join(repo, "app.py"), "def main():\n    return 1\n")
    textio.write_text(os.path.join(repo, "tests", "test_app.py"),
                      "from app import main\n\n\ndef test_main():\n    assert main() == 1\n")
    made["repo"] = repo
    made["graphdir"] = os.path.join(repo, ".agent", "graph")

    return made


def resolve(args: list[str], made: dict[str, str]) -> list[str]:
    return [made[a[1:]] if a.startswith("@") else a for a in args]
