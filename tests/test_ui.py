"""The pretty rendering, and the line it must never cross.

Luna parses TOON. A box-drawn table is not TOON, so the whole risk of this module is that a report renders as a
table in a context where something is parsing it. Every test here is either "does it stay off" or "does the plain
output still come out byte for byte".
"""
import pytest

from agentdata import color
from agentdata import policy
from agentdata import ui
from agentdata.model import AgentTable


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    for var in ("AGENTDATA_UI", "AGENTDATA_COLOR", "AGENTDATA_WIDTH", "NO_COLOR", "FORCE_COLOR",
                "PYCHARM_HOSTED", "TERM_PROGRAM", "WT_SESSION"):
        monkeypatch.delenv(var, raising=False)
    ui.reset_cache()
    color.reset_cache()
    yield
    ui.reset_cache()
    color.reset_cache()


def table(rows=3):
    return AgentTable(name="loans", columns=["loan_id", "amount", "status"],
                      rows=[[f"L-100{i}", 1000 + i, "ok" if i % 2 else "fail"] for i in range(rows)],
                      source="ad-td --sql 'SELECT ...'")


def test_it_is_off_whenever_a_machine_might_be_reading(monkeypatch):
    """capsys is not a TTY, which is exactly Luna's case."""
    assert ui.on() is False
    monkeypatch.setenv("AGENTDATA_COLOR", "always")           # a colour-capable console
    ui.reset_cache(); color.reset_cache()
    assert ui.on() is True
    monkeypatch.setenv("AGENTDATA_UI", "plain")               # ... and plain still wins
    ui.reset_cache()
    assert ui.on() is False


def test_no_rich_installed_is_not_an_error(monkeypatch):
    monkeypatch.setenv("AGENTDATA_UI", "rich")
    ui.reset_cache()
    real = __import__

    def fail(name, *a, **kw):
        if name == "rich":
            raise ImportError("no rich")
        return real(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", fail)
    assert ui.on() is False
    ui.rule("step"); ui.note("hello"); ui.problem("broke", "fix it")     # all fall back, none raise


def test_query_results_stay_toon_on_a_terminal(monkeypatch, tmp_path):
    """`auto` cannot tell Luna's shell from a person's, so a data command is never prettified by accident.
    Only asking for it explicitly draws a table."""
    monkeypatch.setenv("AGENTDATA_OUT", str(tmp_path))
    monkeypatch.setenv("AGENTDATA_COLOR", "always")
    ui.reset_cache(); color.reset_cache()
    plain = policy.render(table())
    assert plain.startswith("meta:") and "loans[3]{loan_id,amount,status}:" in plain and "╭" not in plain

    monkeypatch.setenv("AGENTDATA_UI", "rich")
    ui.reset_cache()
    pretty = policy.render(table())
    assert "╭" in pretty and "loan_id" in pretty and "meta:" not in pretty


def test_the_toon_is_byte_identical_whether_or_not_rich_is_there(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTDATA_OUT", str(tmp_path))
    t = table()
    with_rich = policy.render(t)
    monkeypatch.setenv("AGENTDATA_UI", "plain")
    ui.reset_cache()
    assert policy.render(t) == with_rich
    assert color.strip(with_rich) == with_rich          # nothing painted when nobody is watching


def test_a_single_row_is_a_panel_not_a_one_line_table(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTDATA_OUT", str(tmp_path))
    monkeypatch.setenv("AGENTDATA_UI", "rich")
    monkeypatch.setenv("AGENTDATA_WIDTH", "80")
    ui.reset_cache()
    one = AgentTable(name="whoami", columns=["flavor", "api"], rows=[["cloud", "3"]], source="ad-jira whoami")
    out = color.strip(policy.render(one))
    assert "flavor" in out and "cloud" in out and "rule 3" in out and "─" in out


def test_status_words_and_booleans_read_as_what_they_mean(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTDATA_OUT", str(tmp_path))
    monkeypatch.setenv("AGENTDATA_UI", "rich")
    monkeypatch.setenv("AGENTDATA_COLOR", "always")
    monkeypatch.setenv("AGENTDATA_WIDTH", "100")
    ui.reset_cache(); color.reset_cache()
    out = policy.render(table())
    assert "\x1b[32mok" in out and "\x1b[1;31mfail" in out          # coloured by meaning, not by column
    assert "truncated  no" in color.strip(out)                      # not a bare `False`, which reads as a failure


def test_numbers_are_right_aligned_so_they_can_be_compared(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTDATA_OUT", str(tmp_path))
    monkeypatch.setenv("AGENTDATA_UI", "rich")
    monkeypatch.setenv("AGENTDATA_WIDTH", "100")
    ui.reset_cache()
    t = AgentTable(name="n", columns=["key", "amount"], rows=[["a", "5"], ["b", "1250.00"]], source="x")
    lines = color.strip(policy.render(t)).splitlines()
    amount = lambda text: text.split("│")[2]                    # noqa: E731 - the amount column of a row line
    short, long = [ln for ln in lines if "│a" in ln][0], [ln for ln in lines if "1250.00" in ln][0]
    assert amount(short).endswith("5") and amount(short).startswith(" ")
    assert len(amount(short)) == len(amount(long))              # one right edge, so the digits line up
    header = [ln for ln in lines if "key" in ln and "amount" in ln][0]
    assert header.split("│")[1].startswith("key")               # text stays left


def test_a_group_column_prints_its_label_once(monkeypatch, capsys):
    monkeypatch.setenv("AGENTDATA_UI", "rich")
    monkeypatch.setenv("AGENTDATA_WIDTH", "70")
    ui.reset_cache()
    ui.table(["step", "check", "status"],
             [["pncli", "launcher", "fail"], ["pncli", "config", "fail"], ["sources", "oracle", "ok"]],
             status_col=2, group_col=0)
    out = color.strip(capsys.readouterr().out)
    assert out.count("pncli ") == 1 or len([l for l in out.splitlines() if "pncli" in l and "launcher" not in l]) == 0
    g = ui.glyphs()
    assert "sources" in out and f"{g['ok']} ok" in out and f"{g['fail']} fail" in out


def test_glyphs_fall_back_when_the_console_cannot_encode_them(monkeypatch):
    class Ascii:
        encoding = "cp437"
    monkeypatch.setattr("sys.stdout", Ascii())
    assert ui.glyphs() == ui.ASCII_GLYPHS
    monkeypatch.setattr("sys.stdout", type("U", (), {"encoding": "utf-8"})())
    assert ui.glyphs() == ui.GLYPHS


def test_doctor_prints_toon_for_a_pipe_and_a_report_for_a_person(monkeypatch, capsys, tmp_path):
    from agentdata.setup import wizard as W
    from tests.test_setup import FakeDet                       # the hermetic machine stand-in
    monkeypatch.setenv("AGENTDATA_CONFIG", str(tmp_path / "c.json"))
    assert W.run_doctor([], det=FakeDet()) == 1
    plain = capsys.readouterr().out
    assert plain.startswith("meta:") and "checks[" in plain and "╭" not in plain

    monkeypatch.setenv("AGENTDATA_UI", "rich")
    monkeypatch.setenv("AGENTDATA_WIDTH", "100")
    ui.reset_cache()
    assert W.run_doctor([], det=FakeDet()) == 1
    pretty = color.strip(capsys.readouterr().out)
    assert "╭" in pretty and "ad-doctor" in pretty and f"{ui.glyphs()['fail']} fail" in pretty
    assert "meta:" not in pretty and "checks[" not in pretty
    for line in plain.splitlines():                            # every failing check is still named
        if line.strip().startswith("pncli,"):
            assert line.split(",")[1] in pretty


def test_brackets_in_somebody_elses_text_are_not_style_tags(monkeypatch, capsys):
    """A Windows hint says `[IO.File]::WriteAllText`, a source carries a JQL with a bracket. rich would read
    either as markup: eat it, or raise MissingStyle. Nothing here is rendered as markup."""
    monkeypatch.setenv("AGENTDATA_UI", "rich")
    monkeypatch.setenv("AGENTDATA_WIDTH", "120")
    ui.reset_cache()
    hint = "write it with [IO.File]::WriteAllText($p, $t)"
    ui.note(hint)
    ui.rule("a [step] title")
    ui.problem("labels[0] is missing", hint)
    ui.facts([("jql", 'project = X AND labels in ("a[1]")')], title="ad-jira [search]")
    ui.table(["k", "v"], [["path", r"C:\repo\a[1].pbix"]], title="files [1]", wrap=(1,))
    out = color.strip(capsys.readouterr().out)
    for literal in ("[IO.File]::WriteAllText", "a [step] title", "labels[0] is missing", 'labels in ("a[1]")',
                    "ad-jira [search]", r"a[1].pbix", "files [1]"):
        assert literal in out, literal


def test_a_data_view_does_not_read_its_own_cells_as_markup(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTDATA_OUT", str(tmp_path))
    monkeypatch.setenv("AGENTDATA_UI", "rich")
    monkeypatch.setenv("AGENTDATA_WIDTH", "120")
    ui.reset_cache()
    one = AgentTable(name="m[1]", columns=["expr"], rows=[["DIVIDE([Margin], [Total Sales])"]],
                     source="ad-pbip refs --visual [chart]")
    out = color.strip(policy.render(one))                       # rule 3: the labelled panel
    assert "DIVIDE([Margin], [Total Sales])" in out and "--visual [chart]" in out
    many = AgentTable(name="measures [all]", columns=["name", "expr"],
                      rows=[["Margin %", "DIVIDE([Margin], [Total Sales])"], ["Sales", "SUM(f[amount])"]],
                      source="ad-pbip refs --visual [chart]")
    out = color.strip(policy.render(many))                      # rule 4: the table
    assert "measures [all]" in out and "DIVIDE([Margin], [Total Sales])" in out and "SUM(f[amount])" in out


def test_newly_wired_commands_help_mentions_pretty(capsys):
    from agentdata import cli_state, cli_confluence, cli_pbip, cli_uat, cli_dpm, cli_jira
    cases = [
        (cli_state, ["show", "--help"]),
        (cli_state, ["set", "--help"]),
        (cli_confluence, ["html", "--help"]),
        (cli_confluence, ["check", "--help"]),
        (cli_pbip, ["check", "--help"]),
        (cli_pbip, ["project", "--help"]),
        (cli_pbip, ["lint", "--help"]),
        (cli_pbip, ["refs", "--help"]),
        (cli_uat, ["expect", "--help"]),
        (cli_uat, ["plan", "--help"]),
        (cli_uat, ["reconcile", "--help"]),
        (cli_dpm, ["locate", "--help"]),
        (cli_dpm, ["inspect", "--help"]),
        (cli_dpm, ["validate", "--help"]),
        (cli_dpm, ["convert", "--help"]),
        (cli_dpm, ["lineage", "--help"]),
        (cli_dpm, ["binding", "--help"]),
        (cli_jira, ["whoami", "--help"]),
        (cli_jira, ["fields", "--help"]),
        (cli_jira, ["statuses", "--help"]),
        (cli_jira, ["transitions", "--help"]),
        (cli_jira, ["transition", "--help"]),
        (cli_jira, ["sprints", "--help"]),
        (cli_jira, ["changelog", "--help"]),
        (cli_jira, ["sprint-replay", "--help"]),
    ]
    for mod, argv in cases:
        with pytest.raises(SystemExit) as exc:
            mod.main(argv)
        assert exc.value.code == 0, f"{mod.__name__} {argv} exited with {exc.value.code}"
        out = capsys.readouterr().out
        assert "--pretty" in out, f"{mod.__name__} {argv} help does not mention --pretty"


def test_ad_state_pretty_vs_plain(monkeypatch, capsys, tmp_path):
    from agentdata import cli_state, state as S
    st_file = tmp_path / "state.json"
    S.save({"project": "PROJ", "phase": "idle", "active_ticket": "RDSD-101", "artifacts": []}, str(st_file))

    # Piped / non-terminal without --pretty: raw TOON
    assert cli_state.main(["--file", str(st_file), "show"]) == 0
    plain = capsys.readouterr().out
    assert plain.startswith("meta:") and "phase: idle" in plain and "╭" not in plain

    # With --pretty: rich panel
    monkeypatch.setenv("AGENTDATA_WIDTH", "100")
    assert cli_state.main(["--file", str(st_file), "show", "--pretty"]) == 0
    pretty = color.strip(capsys.readouterr().out)
    assert "╭" in pretty and "ad-state show" in pretty and "meta:" not in pretty and "phase" in pretty


def test_ad_confluence_pretty_vs_plain(monkeypatch, capsys, tmp_path):
    from agentdata import cli_confluence
    doc = tmp_path / "page.html"
    doc.write_text("<p>Hello world</p>", encoding="utf-8")

    assert cli_confluence.main(["check", str(doc)]) == 0
    plain = capsys.readouterr().out
    assert plain.startswith("meta:") and "well_formed: true" in plain and "╭" not in plain

    monkeypatch.setenv("AGENTDATA_WIDTH", "100")
    assert cli_confluence.main(["check", str(doc), "--pretty"]) == 0
    pretty = color.strip(capsys.readouterr().out)
    assert "╭" in pretty and "ad-confluence check" in pretty and "meta:" not in pretty


def test_ad_pbip_lint_pretty_vs_plain(monkeypatch, capsys, tmp_path):
    from agentdata import cli_pbip
    tmdl = tmp_path / "model.tmdl"
    tmdl.write_text("table Sales\n\tlineageTag: abc\n", encoding="utf-8")

    assert cli_pbip.main(["lint", str(tmdl)]) == 0
    plain = capsys.readouterr().out
    assert plain.startswith("meta:") and "╭" not in plain

    monkeypatch.setenv("AGENTDATA_WIDTH", "100")
    assert cli_pbip.main(["lint", str(tmdl), "--pretty"]) == 0
    pretty = color.strip(capsys.readouterr().out)
    assert "╭" in pretty and "ad-pbip lint" in pretty and "meta:" not in pretty
