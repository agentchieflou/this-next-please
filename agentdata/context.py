"""The project context: what a repository is, read in seconds, without a model or the network.

The operator, 2026-10-03: "the first time an agent sees a repository, no matter what the work is,
... we have a way for cheap to ingest that and create documentation from that so that a user could
get started quickly." Cheap means deterministic: everything here is a file walk, a few regexes and
three `git` calls, and the same repository always produces the same `context.json`. The one model
pass -- a sentence per directory, three first things to do -- is the `project-onboard` skill's,
and it reads `CONTEXT.md`, never the tree.

What is written, all under `.agent/context/`:

| File | What |
|---|---|
| `context.json` | the facts: inventory, entrypoints, tests, data assets, docs, git, detected facts |
| `CONTEXT.md` | the same facts as a page, with `<!-- model -->` blocks for the one narrow pass, exactly as `.agent/graph/understanding.md` does |
| `meta.json` | the file-list hash and the HEAD the facts were read at, so `status` can say `stale` |

The graph (`ad-graph`) is deeper and code-only; this is wider and shallow on purpose. A report
repository holds PBIP, TMDL and SQL and no Python, and its first page still has to say what it
is for, what feeds it, and how to check it.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
from collections import Counter

from . import config as C
from . import proc, textio
from .graph.builder import collect_files

DIR = os.path.join(".agent", "context")
JSON = "context.json"
PAGE = "CONTEXT.md"
META = "meta.json"
SCHEMA = 1
TOP_DIRS = 12
TOP_SQL_TABLES = 15
MAX_DOC_TITLES = 20

LANGUAGES = {
    ".py": "Python", ".ipynb": "Notebook", ".sql": "SQL", ".tmdl": "TMDL", ".pbip": "PBIP", ".pbir": "PBIR",
    ".dax": "DAX", ".m": "Power Query", ".pq": "Power Query", ".js": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".jsx": "JavaScript", ".cs": "C#", ".java": "Java", ".kt": "Kotlin", ".ps1": "PowerShell",
    ".psm1": "PowerShell", ".sh": "Shell", ".bat": "Batch", ".cmd": "Batch", ".md": "Markdown", ".rst": "Text",
    ".txt": "Text", ".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".csv": "CSV", ".tsv": "TSV",
    ".xlsx": "Excel", ".xlsm": "Excel", ".parquet": "Parquet", ".html": "HTML", ".css": "CSS", ".r": "R",
    ".scala": "Scala", ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C", ".cpp": "C++", ".vue": "Vue", ".svelte": "Svelte",
    ".tf": "Terraform", ".bicep": "Bicep", ".dockerfile": "Docker",
}
# Directory names whose role needs no reading. Anything else is the model pass's one sentence.
KNOWN_DIRS = {
    "tests": "the test suite", "test": "the test suite", "docs": "documentation", "doc": "documentation",
    "scripts": "scripts run by hand or by CI", "bin": "scripts run by hand or by CI", "src": "the source",
    "lib": "the source", ".github": "GitHub workflows and templates", "ci": "CI configuration",
    "notebooks": "notebooks", "sql": "SQL", "data": "data files", "config": "configuration",
    "migrations": "database migrations", "reports": "Power BI reports", "models": "semantic models or ML models",
    "assets": "static assets", "static": "static assets", "templates": "templates", "examples": "examples",
    "contract": "contracts and schemas", "schemas": "schemas", "infra": "infrastructure", "deploy": "deployment",
}
RE_SQL_TABLE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z0-9_.\"\[\]]+)", re.IGNORECASE)
RE_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.-]+):(?:\s|$)", re.MULTILINE)
RE_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-\d+\b")
RE_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
RE_MD_TITLE = re.compile(r"^#{1,2}\s+(.+?)\s*$", re.MULTILINE)
DETECTED_FACTS = ("pbip_path", "tmdl_path", "test_cmd", "jira_project")


class ContextError(Exception):
    def __init__(self, msg: str, hint: str = "", code: str = "context"):
        super().__init__(msg)
        self.msg, self.hint, self.code = msg, hint, code


# ------------------------------------------------------------------------------------- reading


def _read(root: str, rel: str, limit: int = 200_000) -> str:
    try:
        text = textio.read_text(os.path.join(root, rel))
    except (OSError, ValueError):
        return ""
    return text[:limit]


def _git(root: str, *args: str) -> str:
    """One git answer, or "" -- no git, no git facts, and the rest of the read still happens."""
    try:
        code, out, _err, _elapsed = proc.run(["git", *args], cwd=root, timeout=10)
    except Exception:                        # noqa: BLE001 - a missing git is "", never a crash
        return ""
    return (out or "").strip() if code == 0 else ""


def _fixture(rel: str) -> bool:
    """A file under a test or sample directory: listed as data, never proposed as the project's."""
    parts = rel.lower().split("/")
    return any(p in ("tests", "test", "fixtures", "fixture", "testdata", "samples", "examples") for p in parts[:-1])


def inventory(files: list[str]) -> dict:
    """Counts by language and by top-level directory; the roles of the directories it can name."""
    by_lang: Counter = Counter()
    by_dir: Counter = Counter()
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        name = os.path.basename(rel).lower()
        lang = LANGUAGES.get(ext) or ("Docker" if name == "dockerfile" else "other")
        by_lang[lang] += 1
        head = rel.split("/", 1)[0] if "/" in rel else "."
        by_dir[head] += 1
    dirs = []
    for head, n in by_dir.most_common():
        if head == ".":
            continue
        dirs.append({"dir": head, "files": n, "role": KNOWN_DIRS.get(head.lower(), "")})
    return {"files": len(files), "languages": [{"language": k, "files": v} for k, v in by_lang.most_common()],
            "dirs": dirs[:TOP_DIRS], "root_files": by_dir.get(".", 0)}


def entrypoints(root: str, files: list[str]) -> list[dict]:
    """Where a person starts: scripts a packaging file declares, make targets, root scripts, CI."""
    out = []
    pyproject = _read(root, "pyproject.toml") if "pyproject.toml" in files else ""
    if pyproject:
        body = pyproject.split("[project.scripts]", 1)
        if len(body) == 2:
            for name, target in re.findall(r'^([\w.-]+)\s*=\s*"([^"]+)"', body[1].split("\n[", 1)[0], re.M):
                out.append({"kind": "console script", "name": name, "where": f"pyproject.toml → {target}"})
    package = _read(root, "package.json") if "package.json" in files else ""
    if package:
        try:
            scripts = (json.loads(package).get("scripts") or {})
        except ValueError:
            scripts = {}
        for name, cmd in list(scripts.items())[:12]:
            out.append({"kind": "npm script", "name": f"npm run {name}", "where": str(cmd)[:80]})
    for mk in ("Makefile", "makefile", "justfile"):
        if mk in files:
            for target in RE_MAKE_TARGET.findall(_read(root, mk))[:12]:
                if not target.startswith("."):
                    out.append({"kind": "make target", "name": f"make {target}", "where": mk})
    for rel in files:
        if "/" not in rel and os.path.splitext(rel)[1].lower() in (".sh", ".ps1", ".bat", ".cmd"):
            out.append({"kind": "root script", "name": rel, "where": rel})
        if rel.endswith("__main__.py"):
            out.append({"kind": "python -m", "name": rel.rsplit("/", 1)[0].replace("/", ".") if "/" in rel else "__main__",
                        "where": rel})
    for rel in files:
        if rel.lower() in ("dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml"):
            out.append({"kind": "container", "name": rel, "where": rel})
    workflows = sorted(f for f in files if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")))
    for rel in workflows[:8]:
        out.append({"kind": "CI workflow", "name": os.path.basename(rel), "where": rel})
    return out


def tests_info(root: str) -> dict:
    """How the tests run, from the same detector `ad-test` uses; never a guess."""
    try:
        from .testing import detect as T

        info = T.detect_runner(root)
    except Exception:                        # noqa: BLE001 - a detector failure is "unknown", not a crash
        info = None
    if info is None:
        return {"runner": "", "cmd": "", "evidence": "no test runner detected"}
    return {"runner": info.runner, "cmd": info.cmd, "evidence": info.evidence}


def data_assets(root: str, files: list[str]) -> dict:
    """What the repository is about when it is not code: reports, models, SQL and the tables it reads."""
    pbips = sorted(f for f in files if f.lower().endswith(".pbip"))
    tmdl_dirs = sorted({f.rsplit("/", 1)[0] for f in files if f.lower().endswith("/model.tmdl")})
    sql = sorted(f for f in files if f.lower().endswith(".sql"))
    tables: Counter = Counter()
    for rel in sql[:300]:
        for name in RE_SQL_TABLE.findall(_read(root, rel, 100_000)):
            # One spelling per table: `DB.T` and `db.t` are the same object to every engine here.
            name = name.strip('"[]').lower()
            if name and not name.startswith("(") and name not in ("select", "dual"):
                tables[name] += 1
    notebooks = sorted(f for f in files if f.lower().endswith(".ipynb"))
    tabular = [f for f in files if os.path.splitext(f)[1].lower() in (".csv", ".tsv", ".xlsx", ".xlsm", ".parquet")]
    return {"pbip": pbips, "tmdl": tmdl_dirs, "sql_files": len(sql), "notebooks": len(notebooks),
            "tabular_files": len(tabular),
            "sql_tables": [{"table": t, "reads": n} for t, n in tables.most_common(TOP_SQL_TABLES)]}


def docs_info(root: str, files: list[str]) -> dict:
    """The README's own words, and the titles of every other page: what is already written down."""
    readme = next((f for f in files if f.lower() in ("readme.md", "readme.rst", "readme.txt", "readme")), "")
    title, first = "", ""
    if readme:
        text = _read(root, readme, 20_000)
        m = RE_HEADING.search(text)
        title = m.group(1).strip() if m else ""
        body = text[m.end():] if m else text
        for para in re.split(r"\n\s*\n", body):
            para = " ".join(para.split())
            if para and not para.startswith(("#", "[", "!", "|", "```", "<")):
                first = para[:400]
                break
    pages = []
    for rel in sorted(files):
        if rel == readme or not rel.lower().endswith((".md", ".rst")):
            continue
        if rel.count("/") > 2:
            continue
        m = RE_MD_TITLE.search(_read(root, rel, 4_000))
        pages.append({"path": rel, "title": (m.group(1).strip() if m else os.path.basename(rel))[:80]})
        if len(pages) >= MAX_DOC_TITLES:
            break
    others = [f for f in files if f.lower() in ("contributing.md", "changelog.md", "license", "license.md", "agents.md",
                                                 "claude.md", "gemini.md", "handoff.md", "security.md")]
    return {"readme": readme, "title": title, "first_paragraph": first, "pages": pages, "pages_total": sum(
        1 for f in files if f.lower().endswith((".md", ".rst")) and f != readme), "conventions": sorted(others)}


def git_info(root: str) -> dict:
    """Three cheap git calls: where HEAD is, how many branches, how many commits and since when."""
    head = _git(root, "rev-parse", "--short", "HEAD")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    branches = [b for b in _git(root, "for-each-ref", "refs/heads", "--format=%(refname:short)").splitlines() if b]
    log = _git(root, "log", "--format=%as", "-500")
    dates = [d for d in log.splitlines() if d]
    keys: Counter = Counter()
    for subject in _git(root, "log", "--format=%s", "-200").splitlines():
        for key in RE_KEY.findall(subject):
            keys[key] += 1
    for name in branches:
        for key in RE_KEY.findall(name.upper()):
            keys[key] += 1
    return {"head": head, "branch": branch, "branches": len(branches),
            "commits_sampled": len(dates), "first_commit": dates[-1] if dates else "", "last_commit": dates[0] if dates else "",
            "jira_projects": [{"project": k, "mentions": n} for k, n in keys.most_common(3)]}


def detected_facts(root: str, data: dict, tests: dict, git: dict) -> dict:
    """The `AGENTS.md` facts this read can propose, beside what the file records."""
    recorded = C.project_facts(os.path.join(root, "AGENTS.md"))
    found = {}
    # A fixture under tests/ is not the project's report: propose only what lives outside them.
    real_pbip = [p for p in data["pbip"] if not _fixture(p)]
    real_tmdl = [t for t in data["tmdl"] if not _fixture(t)]
    if real_pbip:
        found["pbip_path"] = real_pbip[0]
    if real_tmdl:
        found["tmdl_path"] = real_tmdl[0]
    if tests.get("cmd"):
        found["test_cmd"] = tests["cmd"]
    if git["jira_projects"] and git["jira_projects"][0]["mentions"] >= 2:
        found["jira_project"] = git["jira_projects"][0]["project"]
    rows = []
    for key in DETECTED_FACTS:
        have, saw = recorded.get(key, ""), found.get(key, "")
        if not have and not saw:
            continue
        verdict = "recorded" if have and not saw else ("agrees" if have == saw else ("differs" if have else "missing"))
        rows.append({"fact": key, "recorded": have, "detected": saw, "verdict": verdict})
    return {"agents_md": os.path.isfile(os.path.join(root, "AGENTS.md")), "rows": rows}


# ------------------------------------------------------------------------------------ building


def fingerprint(files: list[str], head: str) -> str:
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode("utf-8"))
        h.update(b"\n")
    h.update(head.encode("utf-8"))
    return h.hexdigest()[:16]


def read_meta(root: str) -> dict:
    try:
        return textio.read_json(os.path.join(root, DIR, META), "context meta")
    except (OSError, ValueError):
        return {}


def status(root: str = ".") -> dict:
    """Is the context there, and does it still describe this tree? Reads the file list, no more."""
    meta = read_meta(root)
    present = bool(meta) and os.path.isfile(os.path.join(root, DIR, PAGE))
    if not present:
        return {"present": False, "stale": True, "why": f"{DIR}/{PAGE} is not there yet", "built": ""}
    files = collect_files(root)
    now = fingerprint(files, _git(root, "rev-parse", "--short", "HEAD"))
    stale = now != str(meta.get("fingerprint") or "")
    return {"present": True, "stale": stale, "built": str(meta.get("built") or ""), "files": len(files),
            "why": "the file list or HEAD moved since it was built" if stale else "current"}


def build(root: str = ".", *, force: bool = False, today: str | None = None) -> dict:
    """Read the tree and write the three files. Skips when nothing moved, unless `force`."""
    root = os.path.abspath(root)
    files = collect_files(root)
    git = git_info(root)
    print_fp = fingerprint(files, git["head"])
    meta = read_meta(root)
    if not force and meta.get("fingerprint") == print_fp and os.path.isfile(os.path.join(root, DIR, PAGE)):
        return {"skipped": True, "why": "nothing moved since it was built; --force rebuilds", "path": os.path.join(DIR, PAGE),
                "files": len(files), "built": str(meta.get("built") or "")}
    tests = tests_info(root)
    data = data_assets(root, files)
    facts = {
        "schema": SCHEMA,
        "root": textio.norm_path(root),
        "inventory": inventory(files),
        "entrypoints": entrypoints(root, files),
        "tests": tests,
        "data": data,
        "docs": docs_info(root, files),
        "git": git,
    }
    facts["facts"] = detected_facts(root, data, tests, git)
    out_dir = os.path.join(root, DIR)
    os.makedirs(out_dir, exist_ok=True)
    existing = _read(root, os.path.join(DIR, PAGE))
    textio.write_json(os.path.join(out_dir, JSON), facts)
    textio.write_text(os.path.join(out_dir, PAGE), render(facts, existing))
    from datetime import datetime, timezone

    built = today or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    textio.write_json(os.path.join(out_dir, META), {"schema": SCHEMA, "fingerprint": print_fp, "built": built,
                                                    "head": git["head"], "files": len(files)})
    return {"skipped": False, "path": os.path.join(DIR, PAGE), "files": len(files), "built": built,
            "languages": [row["language"] for row in facts["inventory"]["languages"][:3]],
            "tests": tests["cmd"] or "", "pbip": len(data["pbip"]), "sql_files": data["sql_files"],
            "facts_missing": [r["fact"] for r in facts["facts"]["rows"] if r["verdict"] in ("missing", "differs")]}


# ------------------------------------------------------------------------------------- the page


MODEL_OPEN, MODEL_CLOSE = "<!-- model -->", "<!-- /model -->"


def model_blocks(text: str) -> dict[str, str]:
    """What the model wrote last time, by the heading above each block, so a rebuild keeps it.

    Line by line rather than one regex: a lazy `.+?` under DOTALL once swallowed two headings and
    filed the last block under the wrong one.
    """
    out: dict[str, str] = {}
    heading, inside, buf = "", False, []
    for line in (text or "").splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            continue
        if line.strip() == MODEL_OPEN:
            inside, buf = True, []
            continue
        if line.strip() == MODEL_CLOSE:
            body = "\n".join(buf).strip()
            if body and not body.startswith("<") and heading:
                out[heading] = body
            inside = False
            continue
        if inside:
            buf.append(line)
    return out


def _block(kept: dict, heading: str, prompt: str) -> str:
    body = kept.get(heading) or f"<{prompt}>"
    return f"{MODEL_OPEN}\n{body}\n{MODEL_CLOSE}"


def render(facts: dict, existing: str = "") -> str:
    """The facts as a page, with one model block per section the pass must write."""
    kept = model_blocks(existing)
    inv, docs, git, tests, data = facts["inventory"], facts["docs"], facts["git"], facts["tests"], facts["data"]
    lines = [f"# Project context: {docs['title'] or os.path.basename(facts['root'])}", "",
             f"_Generated by `ad-context build` from {inv['files']} files at `{git['head'] or 'no git'}`; the facts are the "
             f"command's, the sentences between the model markers are the `project-onboard` pass's. Re-run the "
             f"command after the tree moves; the sentences are kept._", "",
             "## What this is", "",
             f"README: **{docs['title'] or 'none'}**. " + (docs["first_paragraph"] or "_The README has no opening paragraph._"), "",
             _block(kept, "What this is", "two sentences: what the repository is for, and who uses what it produces"), "",
             "## Layout", "", "| Directory | Files | Role |", "|---|---|---|"]
    for row in inv["dirs"]:
        lines.append(f"| `{row['dir']}/` | {row['files']} | {row['role'] or '_(model: one sentence)_'} |")
    lines += ["", _block(kept, "Layout", "one sentence per directory whose Role is blank, in a list: `dir/` -- what lives there"), "",
              "## Languages", "", ", ".join(f"{r['language']} ({r['files']})" for r in inv["languages"][:8]) or "none", "",
              "## Where to start", ""]
    if facts["entrypoints"]:
        lines += ["| Kind | Name | Where |", "|---|---|---|"]
        lines += [f"| {e['kind']} | `{e['name']}` | {e['where']} |" for e in facts["entrypoints"][:20]]
    else:
        lines.append("_No console script, make target, root script, container or CI workflow found._")
    lines += ["", "## Tests", "",
              (f"`{tests['cmd']}` ({tests['runner']}; {tests['evidence']})" if tests["cmd"] else f"_{tests['evidence']}_"), "",
              "## Data and reports", ""]
    if data["pbip"] or data["tmdl"] or data["sql_files"] or data["notebooks"] or data["tabular_files"]:
        for p in data["pbip"]:
            lines.append(f"- PBIP: `{p}`")
        for t in data["tmdl"]:
            lines.append(f"- TMDL model: `{t}/`")
        if data["sql_files"]:
            lines.append(f"- SQL files: {data['sql_files']}; most-read tables: " +
                         (", ".join(f"`{r['table']}` ({r['reads']})" for r in data["sql_tables"][:8]) or "none found"))
        if data["notebooks"]:
            lines.append(f"- Notebooks: {data['notebooks']}")
        if data["tabular_files"]:
            lines.append(f"- Tabular data files (csv/tsv/xlsx/parquet): {data['tabular_files']}")
    else:
        lines.append("_No reports, models, SQL, notebooks or data files._")
    lines += ["", "## Already written down", ""]
    if docs["pages"]:
        lines += [f"- `{p['path']}`: {p['title']}" for p in docs["pages"]]
        if docs["pages_total"] > len(docs["pages"]):
            lines.append(f"- … and {docs['pages_total'] - len(docs['pages'])} more pages")
    else:
        lines.append("_No pages beside the README._")
    if docs["conventions"]:
        lines.append(f"- Conventions: {', '.join(f'`{c}`' for c in docs['conventions'])}")
    lines += ["", "## History", "",
              f"Branch `{git['branch'] or '?'}` at `{git['head'] or '?'}`; {git['branches']} local branches; "
              f"{git['commits_sampled']} commits sampled, {git['first_commit'] or '?'} → {git['last_commit'] or '?'}."
              + (" Jira keys seen: " + ", ".join(f"{r['project']} ({r['mentions']})" for r in git["jira_projects"]) + "."
                 if git["jira_projects"] else ""), "",
              "## Facts for AGENTS.md", ""]
    rows = facts["facts"]["rows"]
    if rows:
        lines += ["| Fact | Recorded | Detected | Verdict |", "|---|---|---|---|"]
        lines += [f"| `{r['fact']}` | {r['recorded'] or '-'} | {r['detected'] or '-'} | {r['verdict']} |" for r in rows]
        if not facts["facts"]["agents_md"]:
            lines.append("\n_No `AGENTS.md` yet: `ad-setup --only project --non-interactive --offline --project .` writes the stub._")
    else:
        lines.append("_Nothing detected that AGENTS.md would record._")
    lines += ["", "## First three things to do", "",
              _block(kept, "First three things to do",
                     "three numbered lines, each a command from this page and what it proves; nothing invented"), ""]
    return "\n".join(lines)
