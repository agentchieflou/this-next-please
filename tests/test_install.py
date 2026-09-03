"""The CLI is a laptop-wide tool; project repos (Power BI reports, TMDL, SQL) are not Python projects.

Two regressions these tests pin down:
1. `pip install -e .` was the only documented install, so it failed inside a report repo ("neither 'setup.py' nor
   'pyproject.toml' found") — the install must work from GitHub with no clone.
2. the project stub lived outside the package, so `ad-setup --project` broke on any non-editable install.
"""
import fnmatch, os, re, subprocess, sys
import pytest
import agentdata
from agentdata import install as I
from agentdata.__main__ import COMMANDS, main as module_main
from agentdata.setup.steps import project as P

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.dirname(os.path.abspath(agentdata.__file__))


def test_templates_live_inside_the_package():
    td = I.templates_dir()
    assert os.path.commonpath([td, PKG]) == PKG, "the stub must be package data, not a sibling of the package"
    for src, _dest in P.STUB_FILES + [(P.GITIGNORE_TEMPLATE, None)]:
        assert os.path.exists(os.path.join(td, src)), f"missing packaged template {src}"
        assert not src.startswith("."), "dot-prefixed names are skipped by package-data globs; keep them dot-free"


def test_pyproject_ships_the_templates():
    text = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    patterns = re.findall(r'^agentdata = \[(.+)\]$', text, re.M)
    assert patterns, "pyproject must declare [tool.setuptools.package-data] for agentdata"
    globs = [g.strip().strip('"') for g in patterns[0].split(",")]
    for src, _dest in P.STUB_FILES + [(P.GITIGNORE_TEMPLATE, None)]:
        rel = f"templates/project-stub/{src}"
        assert any(fnmatch.fnmatch(rel, g) for g in globs), f"{rel} is not covered by package-data {globs}"


def test_install_cmd_adapts_to_the_install_kind(monkeypatch):
    monkeypatch.setattr(I, "source_checkout", lambda: "/opt/this-next-please")
    assert I.install_cmd("odbc").startswith('pip install -e ".[odbc]"')
    monkeypatch.setattr(I, "source_checkout", lambda: None)
    assert I.install_cmd("odbc") == 'pip install "agentdata[odbc] @ git+https://github.com/agentchieflou/this-next-please.git"'
    assert I.install_cmd() == 'pip install "agentdata @ git+https://github.com/agentchieflou/this-next-please.git"'


# Both need to be present no matter which connector extra a user picked: `ad-setup` reaches for keyring on
# any password-auth source, and offers ODBC as a connection MODE for Teradata/Hive/Impala independent of extras.
ALWAYS_NEEDED = ("keyring", "pyodbc")


def test_setup_time_dependencies_are_base_not_gated_behind_an_extra():
    """The reported bug: `ad-setup` picks a password-auth source, tries to store it, and dies mid-wizard with
    `keyring is not installed` -- but only for whichever install command the user happened to run, since keyring
    lived in the per-connector extras (`teradata`, `oracle`, ...) instead of the base install. Same shape of gap
    for `pyodbc`: ODBC is offered as a live choice in the wizard regardless of which extra was installed.

    No TOML parser here: `tomllib` needs 3.11+ and this repo's floor is 3.10 (same reason `_scripts()` in
    test_entrypoints.py slices pyproject.toml with plain string/regex instead)."""
    text = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    deps = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    extras = text.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    for pkg in ALWAYS_NEEDED:
        assert re.search(rf'"{pkg}(\W|")', deps), \
            f"{pkg} must be a base dependency: ad-setup can reach for it regardless of which extra was installed"
        for name, body in re.findall(r'^([\w-]+) = \[(.*?)\]\s*(?:#.*)?$', extras, re.M):
            assert pkg not in body.lower(), \
                f"{pkg} is redundant in the [{name}] extra now that it is a base dependency"


def test_source_checkout_detects_this_clone():
    assert I.source_checkout() == ROOT


def test_runtime_hints_never_tell_a_project_repo_to_pip_install_dash_e():
    """`pip install -e "."` only makes sense in a clone; skills print these hints verbatim."""
    offenders = []
    for dirpath, _dirs, files in os.walk(PKG):
        if "__pycache__" in dirpath:
            continue
        for f in files:
            if not f.endswith(".py"):
                continue
            if f == "install.py":
                continue  # it *generates* both forms
            p = os.path.join(dirpath, f)
            for i, line in enumerate(open(p, encoding="utf-8"), 1):
                if 'pip install -e' in line and "install_cmd" not in line and not line.lstrip().startswith("#"):
                    offenders.append(f"{os.path.relpath(p, ROOT)}:{i}")
    assert offenders == [], f"use install.install_cmd(extra) instead: {offenders}"


def test_module_entry_point_covers_every_console_script():
    text = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    scripts = dict(re.findall(r'^(ad-[\w-]+) = "([\w.:]+)"$', text, re.M))
    assert scripts, "no console scripts found in pyproject"
    for name, target in scripts.items():
        key = name[3:]
        assert key in COMMANDS, f"{name} has no `python -m agentdata {key}` equivalent"
        module, func, _help = COMMANDS[key]
        assert f"{module}:{func}" == target, f"{key} dispatches to {module}:{func}, console script uses {target}"


def test_module_main_usage_and_dispatch(monkeypatch, capsys):
    assert module_main([]) == 0 and "python -m agentdata" in capsys.readouterr().out
    assert module_main(["nope"]) == 2 and "unknown command" in capsys.readouterr().err
    called = {}
    import agentdata.cli_setup as cs
    monkeypatch.setattr(cs, "main_doctor", lambda: called.setdefault("argv", list(sys.argv)))
    module_main(["doctor", "--quiet"])
    assert called["argv"] == ["ad-doctor", "--quiet"]
    module_main(["ad-doctor", "--quiet"])  # the ad- prefix is tolerated
    assert called["argv"] == ["ad-doctor", "--quiet"]


@pytest.mark.slow
def test_wheel_install_writes_a_project_stub_without_a_pyproject(tmp_path):
    """The real regression: build, install into a clean venv, run in a repo that is not a Python project."""
    wheels = tmp_path / "w"
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheels), ROOT],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-500:]
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, timeout=300)
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    whl = next(iter(wheels.glob("*.whl")))
    subprocess.run([str(py), "-m", "pip", "install", "-q", str(whl)], check=True, timeout=300)
    repo = tmp_path / "reports-repo"          # no setup.py, no pyproject.toml: a Power BI repo
    (repo / "reports").mkdir(parents=True)
    env = {**os.environ, "AGENTDATA_CONFIG": str(tmp_path / "cfg.json")}
    r = subprocess.run([str(py), "-m", "agentdata", "setup", "--project", ".", "--non-interactive", "--offline"],
                       cwd=repo, capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / "AGENTS.md").exists() and (repo / ".agent" / "state.json").exists()
    assert ".agent/out/" in (repo / ".gitignore").read_text()
