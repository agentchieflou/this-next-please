"""`tnp`: the menu (agentdata/tnp), its screen toolkit and in-screen questions, the command catalog it runs every
`ad-*` from, the JDBC URL reader (setup/jdbc.py), and the guide it shares with docs/tnp.md."""
import io
import os

import pytest

from agentdata import color, config as C, facts as F, textio
from agentdata.setup import jdbc
from agentdata.setup import wizard as W
from agentdata.tnp import app as A, brand as B, commands as K, guide as G, screen as SC
from tests.test_setup import FakeDet

STUB = os.path.join(os.path.dirname(W.__file__), "..", "templates", "project-stub", "AGENTS.md")
DOC = os.path.join(os.path.dirname(__file__), "..", "docs", "tnp.md")


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    p = tmp_path / "agentdata.json"
    monkeypatch.setenv(C.CONFIG_ENV, str(p))
    return p


def _repo(path, agents=True):
    (path / ".git").mkdir(parents=True)
    if agents:
        (path / "AGENTS.md").write_text(textio.read_text(STUB), encoding="utf-8")
    return path


class Runs:
    """A runner that records what tnp would have run."""

    def __init__(self, text="meta:\n  ok: true", rc=0):
        self.argv, self.text, self.rc = [], text, rc

    def __call__(self, argv, capture):
        self.argv.append(argv)
        return self.rc, self.text


def _app(cwd, keys, answers=None, det=None, repo=None, screen=False, **kw):
    """`screen=True`: no prompter given, so questions are answered on the screen with keys (TnpPrompter)."""
    out = io.StringIO()
    app = A.App(det=det or FakeDet(modules=("impala", "teradatasql", "keyring")),
                prompter=None if screen else W.AnswerPrompter(answers or {}), keys=iter(keys), out=out,
                cwd=str(cwd), repo=repo, **kw)
    return app, out


# ------------------------------------------------------------------ home


def test_home_says_where_it_is_and_what_it_writes(tmp_path, cfg_file):
    work = tmp_path / "PycharmProjects"
    _repo(work / "alpha")
    _repo(work / "beta", agents=False)
    app, out = _app(work, ["q"])
    assert app.run() == 0
    text = out.getvalue()
    assert B.WORDMARK[0].rstrip() in text and "this-next-please" in text
    assert "folder of 2 repos — a machine-wide setup" in text
    assert "Writes     machine config: " in text and C.display_path(C.path())[-30:] in text.replace("\n" + " " * 13, "")
    assert "toil 3 connections" in text and "not tested yet" in text
    for item in ("▸ 1  Test connections", "Repos in this folder", "6  Commands", "7  Fleet desk", "9  Help"):
        assert item in text


def test_home_in_a_repo_names_its_agents_md(tmp_path, cfg_file):
    root = _repo(tmp_path / "sales-bi")
    app, out = _app(root / ".git", ["down", "down", "q"])
    app.run()
    text = out.getvalue().replace("\n" + " " * 13, "")              # a long path wraps under itself
    assert "Scope      repo sales-bi" in text and "this repo: " + textio.norm_path(str(root / "AGENTS.md")) in text
    assert "This repo" in text


def test_needs_attention_is_one_line_per_row(tmp_path, cfg_file):
    app, out = _app(tmp_path, ["q"], det=FakeDet(conns=[], toil_bin=None))
    app.run()
    text = out.getvalue()
    att = text.split("Needs attention")[1].split("▸ 1")[0]
    assert "fix:" not in att                                       # the fixes live on Health check


def test_esc_goes_back_and_q_quits_from_anywhere(tmp_path, cfg_file):
    app, out = _app(tmp_path, ["2", "5", "esc", "esc", "up", "enter"])        # Spark, back, back, Quit
    assert app.run() == 0
    assert "TNP › Data sources › Spark (Thrift Server)" in out.getvalue()
    app, out = _app(tmp_path, ["2", "5", "q"])                                # q, three screens deep
    assert app.run() == 0


def test_every_line_fits_the_terminal_and_the_header_survives(tmp_path, cfg_file):
    app, out = _app(tmp_path, ["q"], height=24, width=60, det=FakeDet(conns=[], toil_bin=None))
    app.run()
    lines = out.getvalue().split("\n")
    assert all(SC.visible(x) <= 59 for x in lines)
    assert "TNP" in lines[0] or "TNP" in lines[1] or B.WORDMARK[0].rstrip()[:8] in out.getvalue()
    assert "up/down move" in lines[-2] or "up/down move" in out.getvalue().rstrip().split("\n")[-1]
    frame = out.getvalue().rstrip("\n").split("\n")
    assert len(frame) <= 24


def test_a_long_list_scrolls_with_more_markers(tmp_path, cfg_file):
    work = tmp_path / "PycharmProjects"
    for i in range(30):
        _repo(work / f"repo{i:02d}", agents=False)
    app, out = _app(work, ["4"] + ["down"] * 20 + ["q"], height=30)
    app.run()
    text = out.getvalue()
    assert "↓" in text and "more" in text and "↑" in text
    assert "repo20" in text


def test_wordmark_is_teal_into_blue_and_selection_is_readable(monkeypatch):
    monkeypatch.setenv("COLORTERM", "truecolor")
    color.set_enabled(True)
    try:
        line = B.gradient("████")
        assert "38;2;%d;%d;%d" % B.TEAL in line and "38;2;%d;%d;%d" % B.BLUE in line
        assert "38;2;%d;%d;%d" % B.SKY in B.select("x")              # not the 3.8:1 blue
        monkeypatch.delenv("COLORTERM")
        monkeypatch.delenv("WT_SESSION", raising=False)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        assert "38;5;" in B.gradient("██")
    finally:
        color.set_enabled(False)
    assert B.gradient("██") == "██"


def _lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_text_colours_reach_4_5_to_1_on_black():
    for rgb in (B.SKY, B.MUTED, B.LABEL, B.TEAL):
        assert (_lum(rgb) + 0.05) / 0.05 >= 4.5, rgb
    assert (_lum(B.BLUE) + 0.05) / 0.05 < 4.5                      # which is why it is the wordmark's end only


# ------------------------------------------------------------------ the toolkit


def test_fit_cuts_visible_width_and_keeps_escapes_whole():
    painted = "\x1b[1mhello world\x1b[0m"
    cut = SC.fit(painted, 6)
    assert SC.visible(cut) == 6 and cut.endswith("…\x1b[0m") and cut.startswith("\x1b[1m")
    assert SC.fit("short", 10) == "short"


def test_window_keeps_the_selection_visible():
    t = SC.Tui(keys=iter([]))
    assert t.window(5, 0, None) == (0, 5)
    start, end = t.window(50, 40, 10)
    assert start <= 40 < end and end - start == 8


def test_field_types_edits_and_goes_back():
    t = SC.Tui(keys=iter(["ctrl-u", "T", "D", "space", "x", "backspace", "1", "enter"]), out=io.StringIO())
    assert t.field(("A",), "host", "old") == "TD 1"
    t = SC.Tui(keys=iter(["jdbc:hive2://h:1/", "enter"]), out=io.StringIO())     # a paste arrives whole
    assert t.field(("A",), "url") == "jdbc:hive2://h:1/"
    t = SC.Tui(keys=iter(["esc"]), out=io.StringIO())
    with pytest.raises(SC.Back):
        t.field(("A",), "host")
    out = io.StringIO()
    t = SC.Tui(keys=iter(["s", "e", "c", "enter"]), out=out)
    assert t.field(("A",), "password", secret=True) == "sec" and "sec" not in out.getvalue()


def test_checklist_ticks_and_other():
    t = SC.Tui(keys=iter(["space", "down", "down", "space", "enter"]), out=io.StringIO())
    assert t.checklist(("A",), [("a", ""), ("b", ""), ("c", "")], set()) == ([0, 2], False)
    t = SC.Tui(keys=iter(["down", "down", "enter"]), out=io.StringIO())
    assert t.checklist(("A",), [("a", ""), ("b", "")], {1}, other="more…") == ([1], True)


def test_off_a_terminal_every_widget_is_one_line_prompt(monkeypatch):
    answers = iter(["2", "typed", "1,3"])
    monkeypatch.setattr("builtins.input", lambda: next(answers))
    t = SC.Tui(keys=None, out=io.StringIO())
    t.tty = False
    assert t.choose(("A",), [("x", ""), ("y", "")]) == 1
    assert t.field(("A",), "host", "d") == "typed"
    assert t.checklist(("A",), [("a", ""), ("b", ""), ("c", "")], set()) == ([0, 2], False)


# ------------------------------------------------------------------ adding a connection


def test_add_spark_from_a_jdbc_url_tests_it_and_offers_the_repo(tmp_path, cfg_file):
    root = _repo(tmp_path / "sales-bi")
    det = FakeDet(modules=("impala", "keyring"))
    app, out = _app(root, ["2", "5", "1", "enter", "q"], det=det,
                    answers={"tnp.spark.name": "prod", "tnp.spark.jdbc": jdbc.EXAMPLE["spark"]})
    assert app.run() == 0
    e = C.load()["sources"]["spark"]["envs"]["prod"]
    assert (e["host"], e["port"], e["transport"], e["http_path"], e["auth"], e["service_name"]) == (
        "sparkts.corp.example", 10001, "http", "cliservice", "GSSAPI", "hive")
    assert C.project_facts(str(root / "AGENTS.md"))["spark_env"] == "prod"
    text = out.getvalue()
    assert "TNP › Data sources › Spark (Thrift Server) › Add a connection › prod" in text
    assert "From the URL: host sparkts.corp.example" in text and "spark:prod  answered" in text
    assert 'ad-spark --env prod "SELECT 1"' in text
    assert C.get_leaf(C.load(), "verified", "spark:prod")


def test_add_teradata_by_hand_and_a_failing_test_explains(tmp_path, cfg_file):
    det = FakeDet(modules=("teradatasql", "keyring"), smoke_error="[Error 8017] logon failed")
    app, out = _app(tmp_path, ["2", "1", "1", "enter", "q"], det=det,
                    answers={"tnp.teradata.name": "uat", "sources.teradata.uat.host": "tduat.corp",
                             "sources.teradata.uat.logmech": "KRB5"})
    app.run()
    assert C.load()["sources"]["teradata"]["envs"]["uat"]["host"] == "tduat.corp"
    text = out.getvalue()
    assert "8017 / logon failed" in text and "this repo" not in text.split("Saved teradata:uat")[-1]


def test_bad_jdbc_url_is_said_and_skipped(tmp_path, cfg_file):
    app, out = _app(tmp_path, ["2", "4", "1", "enter", "q"],
                    answers={"tnp.oracle.name": "ORA1", "tnp.oracle.jdbc": "jdbc:hive2://x:1/",
                             "sources.oracle.ORA1.host": "ora", "sources.oracle.ORA1.service_name": "SVC"})
    app.run()
    assert "is not a oracle connection" in out.getvalue()
    assert C.load()["sources"]["oracle"]["envs"]["ORA1"]["service_name"] == "SVC"


def test_add_hive_on_the_screen_with_keys_only(tmp_path, cfg_file):
    """The in-screen questions: name field (prefilled), pasted URL, pick lists, yes/no, all by key."""
    det = FakeDet(modules=("impala", "keyring"))
    keys = ["2", "2", "1",                                   # Data sources > Hive > Add a connection
            "ctrl-u", "dev", "enter",                        # Step 1: name
            "jdbc:hive2://hive.corp:10000/default;principal=hive/_HOST@CORP", "enter",   # Step 2: URL
            "enter",                                         # mode: native (the only one)
            "enter", "enter",                                # host and port, from the URL
            "enter",                                         # auth: GSSAPI, from the URL
            "enter",                                         # TLS? No
            "enter",                                         # Step 4: test now? Yes
            "enter", "q"]                                    # the summary, then quit
    app, out = _app(tmp_path, keys, det=det, screen=True)
    assert app.run() == 0
    e = C.load()["sources"]["hive"]["envs"]["dev"]
    assert (e["host"], e["port"], e["auth"]) == ("hive.corp", 10000, "GSSAPI")
    text = out.getvalue()
    assert "Step 1 of 4: name" in text and "Step 3 of 4: connection details" in text and "Step 4 of 4: test" in text
    assert "$ ad-setup --only sources" in text
    assert "host                                          hive.corp" in text   # answers stay on screen
    assert "ad-setup --non-interactive --only sources" in text and "sources.hive.dev.host=hive.corp" in text
    assert "hive:dev  answered" in text


def test_power_bi_for_a_repo_with_checkboxes(tmp_path, cfg_file):
    from tests.test_repo_scope import PbiDet

    class Det(FakeDet):
        run = PbiDet.run

        def which(self, name):
            return "C:/az.cmd" if name == "az" else None

    work = tmp_path / "PycharmProjects"
    _repo(work / "alpha")
    _repo(work / "sales-bi")
    keys = ["3", "2", "2",                                   # Power BI > a repo's targets > sales-bi
            "1",                                             # changes Power BI? Yes
            "space", "down", "space", "enter",               # workspaces: Ops, Sales WS
            "enter", "enter",                                # Ops: no models, no reports
            "space", "enter",                                # Sales WS models (Margin, Sales): Margin
            "space", "enter",                                # Sales WS reports: Sales Report
            "enter", "q"]
    app, out = _app(work, keys, det=Det(), screen=True)
    app.run()
    rows = F.pbi_targets(str(work / "sales-bi" / "AGENTS.md"))
    assert [(r["workspace"], r["model"], r["report"]) for r in rows] == [("Sales WS", "Sales", "Sales Report"),
                                                                        ("Sales WS", "Margin", "")]
    text = out.getvalue()
    assert "[x] Ops" in text and "Another, not listed…" in text
    assert "$ ad-setup --repo sales-bi" in text
    assert F.pbi_targets(str(work / "alpha" / "AGENTS.md")) == []


def test_folder_repo_setup_writes_only_that_repo(tmp_path, cfg_file):
    work = tmp_path / "PycharmProjects"
    _repo(work / "alpha")
    _repo(work / "beta", agents=False)
    C.save({"sources": {"hive": {"envs": {"dev": {"host": "h"}}}}})
    app, out = _app(work, ["4", "2", "enter", "q"], answers={"repo.create": True, "repo.hive_env": "dev",
                                                            "repo.pbi.use": False})
    app.run()
    assert C.project_facts(str(work / "beta" / "AGENTS.md"))["hive_env"] == "dev"
    assert "hive_env" not in C.project_facts(str(work / "alpha" / "AGENTS.md"))
    text = out.getvalue()
    assert "TNP › Repos in this folder › beta" in text and "--repo beta" in text


def test_a_repo_without_agents_md_is_offered_its_setup(tmp_path, cfg_file):
    work = tmp_path / "PycharmProjects"
    _repo(work / "gamma", agents=False)
    app, out = _app(work, ["3", "2", "1", "enter", "enter", "q"], answers={"repo.create": True,
                                                                         "repo.pbi.use": False})
    app.run()
    assert "Set the repo up" in out.getvalue() and (work / "gamma" / "AGENTS.md").exists()


# ------------------------------------------------------------------ every ad-* command


def test_the_catalog_reads_every_command_and_subcommand():
    roots = K.catalog()
    names = {c.title for c in roots}
    assert {"ad-setup", "ad-td", "ad-spark", "ad-fleet", "ad-pbip"} <= names and "ad-_complete" not in names
    every = {c.title for c in K.walk()}
    assert {"ad-pbip check", "ad-git pr", "ad-jira sprints"} <= every and len(every) > 150
    check = next(c for c in K.walk() if c.title == "ad-sql-check")
    pos, opt = check.arguments()
    assert [a.name for a in pos] == ["file"] and "--dialect" in [a.name for a in opt]
    assert next(a for a in opt if a.name == "--dialect").choices == ["teradata", "hive", "impala", "oracle", "spark"]
    assert check.usage.startswith("ad-sql-check ")


def test_find_ranks_the_name_first():
    assert K.find("pr")[0].title == "ad-git pr"
    assert K.find("sprint replay")[0].title == "ad-jira sprint-replay"
    assert K.find("") == []


def test_run_a_command_from_the_menu(tmp_path, cfg_file):
    runs = Runs(text="meta:\n  ok: true\n  source: ad-sql-check")
    keys = ["6", "1", "sql", "enter",                        # Commands > Find "sql"
            "enter",                                         # ad-sql-check
            "enter",                                         # Run it
            "q.sql", "enter",                                # its file
            "--dialect teradata", "enter",                   # flags
            "enter", "q"]
    app, out = _app(tmp_path, keys, screen=True, runner=runs)
    app.run()
    assert runs.argv[0][-4:] == ["sql-check", "q.sql", "--dialect", "teradata"]
    assert runs.argv[0][1:3] == ["-m", "agentdata"]
    text = out.getvalue()
    assert "$ ad-sql-check q.sql --dialect teradata" in text and "source: ad-sql-check" in text
    assert "Flags" in text and "--dialect <dialect>" in text           # the detail page listed them


def test_a_required_argument_left_blank_runs_nothing(tmp_path, cfg_file):
    runs = Runs()
    cmd = next(c for c in K.walk() if c.title == "ad-diff")
    app, out = _app(tmp_path, ["enter", "enter"], screen=True, runner=runs)
    app.run_command(cmd)
    assert runs.argv == [] and "required: nothing was run" in out.getvalue()


def test_required_flags_are_asked_like_arguments(tmp_path, cfg_file):
    runs = Runs()
    cmd = next(c for c in K.walk() if c.title == "ad-pbi refresh")
    app, out = _app(tmp_path, ["Finance BI", "enter", "Budget", "enter", "--wait 0", "enter", "enter"],
                    screen=True, runner=runs)
    app.run_command(cmd)
    assert runs.argv[0][-8:] == ["pbi", "refresh", "--workspace", "Finance BI", "--model", "Budget", "--wait", "0"]
    assert "$ ad-pbi refresh --workspace 'Finance BI' --model Budget --wait 0" in out.getvalue()


def test_fleet_desk_opens_through_ad_fleet(tmp_path, cfg_file, monkeypatch):
    from agentdata.fleet import opener
    monkeypatch.setattr(opener, "running", lambda: {})
    runs = Runs()
    app, out = _app(tmp_path, ["7", "1", "enter", "q"], runner=runs)
    app.run()
    assert runs.argv[0][-2:] == ["fleet", "open"] and "Desk       not running" in out.getvalue()


# ------------------------------------------------------------------ health and help


def test_health_check_shows_the_environment_and_offers_repair(tmp_path, cfg_file):
    runs = Runs()
    app, out = _app(tmp_path, ["8", "enter", "q"], runner=runs, det=FakeDet(conns=[], toil_bin=None))
    app.run()
    text = out.getvalue().replace("\n" + " " * 13, "")
    for label in ("agentdata", "Python", "Config", "Keyring", "toil", "Scope"):
        assert f"  {label.ljust(10)} " in text, label
    assert "(not created yet)" in text and "checks fine" in text
    assert runs.argv and runs.argv[0][-2:] == ["setup", "--patch"]


def test_help_is_one_page_with_keys_docs_and_version(tmp_path, cfg_file):
    app, out = _app(tmp_path, ["9", "esc", "q"])
    app.run()
    text = out.getvalue()
    assert "How tnp works" in text and "esc, backspace   back" in text and A.DOCS_URL in text
    assert "ad-setup --repo <name>" in text


def test_main_print_and_bad_repo(tmp_path, cfg_file, monkeypatch, capsys):
    from agentdata import tnp
    monkeypatch.chdir(tmp_path)
    assert tnp.main(["--print", "--color", "never"]) == 0
    assert "machine — no repo here" in capsys.readouterr().out
    assert tnp.main(["--repo", "nope"]) == 2
    assert "not a git repository" in capsys.readouterr().err


# ------------------------------------------------------------------ the bugs the comparison found


def test_no_color_beats_color_always(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    try:
        color.from_flag("always")
        assert color.enabled() is False
        monkeypatch.delenv("NO_COLOR")
        monkeypatch.setenv("AGENTDATA_COLOR", "never")
        color.from_flag("always")
        assert color.enabled() is False
        monkeypatch.delenv("AGENTDATA_COLOR")
        color.from_flag("always")
        assert color.enabled() is True
    finally:
        color.set_enabled(False)


def test_tnp_is_in_the_front_door_and_completion():
    from agentdata import __main__ as M, complete, completion
    assert "tnp" in M.USAGE and "_complete" not in M.USAGE
    assert "tnp" in completion.registered() and "'tnp'" in completion.completion_script("powershell")
    assert complete.parser_for("tnp") is not None
    assert "--repo" in complete.complete("tnp --r")


def test_step_keys_in_the_help_are_the_registry():
    assert tuple(s.key for s in W.registry()) == W.STEP_KEYS


def test_a_refusal_prints_once(tmp_path, cfg_file, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert W.run_setup(["--non-interactive", "--offline", "--repo", "nope"], FakeDet()) == 2
    out = capsys.readouterr().out
    assert out.count("not a git repository") == 1 and out.startswith("meta:")


def test_pick_many_off_the_screen_takes_numbers_or_names():
    p = W.AnswerPrompter({"k": "2, Other"})
    assert p.pick_many("k", "which", ["a", "b"], []) == ["b", "Other"]
    assert W.AnswerPrompter({}).pick_many("k", "which", ["a", "b"], ["a"]) == ["a"]


def test_sql_check_says_a_missing_file_instead_of_a_traceback(capsys):
    from agentdata import cli_sqlcheck
    assert cli_sqlcheck.main(["--dialect", "teradata", "no-such.sql"]) == 2
    assert "cannot read no-such.sql" in capsys.readouterr().out


# ------------------------------------------------------------------ JDBC URLs


@pytest.mark.parametrize("source,url,want", [
    ("teradata", jdbc.EXAMPLE["teradata"], {"host": "tdprod.corp.example", "logmech": "KRB5", "tmode": "ANSI"}),
    ("hive", jdbc.EXAMPLE["hive"], {"host": "hive.corp.example", "port": 10000, "auth": "GSSAPI"}),
    ("hive", "jdbc:hive2://h:10000/db;user=me;ssl=true", {"host": "h", "auth": "LDAP", "user": "me", "ssl": True}),
    ("impala", jdbc.EXAMPLE["impala"], {"host": "impala.corp.example", "port": 21050, "auth": "GSSAPI"}),
    ("impala", "jdbc:impala://h:21050;AuthMech=3;UID=me", {"host": "h", "auth": "LDAP", "user": "me"}),
    ("oracle", jdbc.EXAMPLE["oracle"], {"style": "basic", "host": "ora.corp.example", "port": 1521,
                                        "service_name": "SALESPRD"}),
    ("oracle", "jdbc:oracle:thin:@ora:1521:ORCL", {"style": "basic", "sid": "ORCL"}),
    ("oracle", "jdbc:oracle:thin:@//ora/SVC", {"host": "ora", "port": 1521, "service_name": "SVC"}),
    ("oracle", "jdbc:oracle:thin:@OIMPROD1_ROSVC", {"style": "tns", "dsn": "OIMPROD1_ROSVC"}),
    ("oracle", "jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(HOST=h)))", {"style": "tns"}),
    ("spark", jdbc.EXAMPLE["spark"], {"transport": "http", "http_path": "cliservice", "port": 10001,
                                      "service_name": "hive"}),
    ("spark", "jdbc:hive2://s:10000/default;transportMode=binary", {"transport": "binary", "port": 10000}),
])
def test_jdbc_parse(source, url, want):
    got = jdbc.parse(source, url)
    assert {k: got.get(k) for k in want} == want and got["mode"] == "native"
    if source in ("hive", "impala"):
        assert "transport" not in got


@pytest.mark.parametrize("source,url", [("hive", "hive2://h"), ("teradata", "jdbc:oracle:thin:@x"),
                                        ("oracle", "jdbc:oracle:thin:nohost")])
def test_jdbc_parse_refuses(source, url):
    with pytest.raises(ValueError):
        jdbc.parse(source, url)


# ------------------------------------------------------------------ the guide and its doc


def test_doc_walks_through_every_connection():
    doc = textio.read_text(DOC)
    from agentdata.setup.steps.sources import LABEL
    for s, g in G.SOURCES.items():
        assert f"## {LABEL[s]}" in doc, s
        assert g["test"] in doc, s
        assert jdbc.EXAMPLE[s] in doc, s
    for what, _ in G.WHERE:
        assert what in doc
    for cmd, _ in G.CHEATSHEET:
        assert f"`{cmd}`" in doc
