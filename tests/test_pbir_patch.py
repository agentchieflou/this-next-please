"""`ad-pbip pbir patch`: any property of a PBIR file, written only once the result validates against its own `$schema`.

The verb is what loosened the "never hand-write visual JSON" rule: with Desktop 2.157's schemas vendored, a property no
verb covers is checked instead of banned. So the refusals are the point -- a violating edit, a protected pointer or
file, a schema that is not vendored, no jsonschema -- and each leaves the file byte for byte as it was. The same check
runs in `ad-pbip check` as the `schema-invalid` rule.
"""
import json
import shutil
from pathlib import Path

import pytest

import pbir_schema as S
from agentdata.cli_pbip import main
from agentdata.pbip import author as AU
from agentdata.pbip import check as CK
from agentdata.pbip import normalize as N
from agentdata.pbip import schema_check as SC

FIXTURES = Path(__file__).parent / "fixtures"
D2157 = FIXTURES / "pbip" / "desktop-2157"
REPORT = "Desktop2157.Report"
PAGE = "3f5e7a9b1c2d4e6f8a0b"
CARD = "6b8d0f2a4c6e8a0b2d4f"
VISUAL_FILE = f"definition/pages/{PAGE}/visuals/{CARD}/visual.json"
TITLE = {"properties": {"text": {"expr": {"Literal": {"Value": "'Total'"}}}}}


def _load(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


@pytest.fixture
def d2157(tmp_path):
    target = tmp_path / "d2157"
    shutil.copytree(D2157, target)
    return target


def _run(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["pbir", "patch", *argv])
    return exc.value.code, capsys.readouterr().out


def test_a_valid_set_writes_the_file_and_reports_the_schema_it_validated_against(d2157, capsys):
    code, out = _run([str(d2157), "--page", "Overview", "--visual", CARD, "--set", "/position/x=300",
                      "--set", f"/visual/visualContainerObjects/title/-={json.dumps(TITLE)}"], capsys)
    assert code == 0, out
    assert "ok: true" in out and "validation: passed" in out and "written: true" in out
    assert f"file: {VISUAL_FILE}" in out
    assert "changed[2]: /position/x,/visual/visualContainerObjects/title/-" in out
    assert "visualContainer/2.12.0/schema.json" in out
    data = _load(d2157 / REPORT / VISUAL_FILE)
    assert data["position"]["x"] == 300
    # a missing intermediate object was created, and `-` appended to the (new) array
    assert data["visual"]["visualContainerObjects"]["title"] == [TITLE]
    assert S.file_errors(d2157 / REPORT / VISUAL_FILE) == []


def test_a_set_the_schema_refuses_is_refused_and_the_file_is_untouched(d2157, capsys):
    target = d2157 / REPORT / VISUAL_FILE
    before = target.read_bytes()
    code, out = _run([str(d2157), "--visual", CARD, "--set", '/position/x="wide"'], capsys)
    assert code == 2
    assert "ok: false" in out and "fail: schema_invalid" in out
    assert "$.position.x: 'wide' is not of type 'number'" in out
    assert target.read_bytes() == before

    # the same through the function: errors name the JSON path, nothing is written
    res = AU.patch_file(str(d2157), visual=CARD, sets=["/visual/visualType=42"])
    assert res["ok"] is False and res["fail"] == "schema_invalid"
    assert res["errors"] == ["$.visual.visualType: 42 is not of type 'string'"]
    assert target.read_bytes() == before


@pytest.mark.parametrize("pointer", ["/$schema", "$schema", "/name"])
def test_the_schema_and_name_pointers_are_protected(d2157, capsys, pointer):
    target = d2157 / REPORT / VISUAL_FILE
    before = target.read_bytes()
    code, out = _run([str(d2157), "--visual", CARD, "--set", f"{pointer}=x"], capsys)
    assert code == 2
    assert "fail: protected_pointer" in out and f"pointer: {pointer}" in out
    assert target.read_bytes() == before
    # --unset too: identity is never removed either
    res = AU.patch_file(str(d2157), visual=CARD, unsets=[pointer])
    assert res["fail"] == "protected_pointer"


@pytest.mark.parametrize("file", [".platform", "definition.pbir", "definition/version.json", "localSettings.json",
                                  "../Desktop2157.pbip", "StaticResources/RegisteredResources/x.json"])
def test_the_project_files_and_anything_outside_definition_are_protected(d2157, capsys, file):
    code, out = _run([str(d2157), "--file", file, "--set", "/a=1"], capsys)
    assert code == 2
    assert "fail: protected_file" in out
    # version.json exists in the fixture and is still byte for byte what it was
    assert _load(d2157 / REPORT / "definition" / "version.json") == _load(D2157 / REPORT / "definition" / "version.json")


def test_visual_resolves_the_visual_json_on_its_page_or_across_the_report(d2157):
    res = AU.patch_file(str(d2157), page="Overview", visual=CARD, sets=["/position/y=48"])
    assert res["ok"] and res["file"] == VISUAL_FILE
    res = AU.patch_file(str(d2157), visual=CARD.upper(), sets=["/position/y=64"])
    assert res["ok"] and res["file"] == VISUAL_FILE
    assert _load(d2157 / REPORT / VISUAL_FILE)["position"]["y"] == 64
    with pytest.raises(KeyError):
        AU.patch_file(str(d2157), page="Overview", visual="0000000000000000dead", sets=["/position/y=1"])
    # --page alone is the page.json; --file is relative to the .Report folder
    assert AU.patch_file(str(d2157), page="Overview", sets=["/displayOption=ActualSize"])["file"] == f"definition/pages/{PAGE}/page.json"
    assert AU.patch_file(str(d2157), file=VISUAL_FILE, sets=["/position/z=1"])["file"] == VISUAL_FILE


def test_dry_run_validates_and_writes_nothing(d2157, capsys):
    target = d2157 / REPORT / VISUAL_FILE
    before = target.read_bytes()
    code, out = _run([str(d2157), "--visual", CARD, "--set", "/position/x=300", "--dry-run"], capsys)
    assert code == 0
    assert "validation: passed" in out and "written: false" in out
    assert target.read_bytes() == before
    # a violation is still a refusal in a dry run
    code, out = _run([str(d2157), "--visual", CARD, "--set", "/position/x=null", "--dry-run"], capsys)
    assert code == 2 and "fail: schema_invalid" in out


def test_unset_removes_a_property_and_names_what_is_not_there(d2157, capsys):
    code, out = _run([str(d2157), "--visual", CARD, "--unset", "/position/tabOrder", "--unset", "/position/z"], capsys)
    assert code == 0 and "changed[2]: /position/tabOrder,/position/z" in out
    assert set(_load(d2157 / REPORT / VISUAL_FILE)["position"]) == {"x", "y", "height", "width"}
    # removing a required property is a schema refusal, not a write
    res = AU.patch_file(str(d2157), visual=CARD, unsets=["/visual/visualType"])
    assert res["fail"] == "schema_invalid" and "'visualType' is a required property" in res["errors"][0]
    with pytest.raises(ValueError, match="nothing at /position/nope"):
        AU.patch_file(str(d2157), visual=CARD, unsets=["/position/nope"])
    with pytest.raises(ValueError, match="nothing to do"):
        AU.patch_file(str(d2157), visual=CARD)


def test_a_value_is_json_when_it_parses_and_text_otherwise(d2157):
    assert AU.parse_set("/a/b=12") == ("/a/b", 12)
    assert AU.parse_set("/a=true") == ("/a", True)
    assert AU.parse_set('/a={"k": [1]}') == ("/a", {"k": [1]})
    assert AU.parse_set("/a=FitToPage") == ("/a", "FitToPage")
    assert AU.parse_pointer("/a/b~1c/~0d") == ["a", "b/c", "~d"]
    with pytest.raises(ValueError):
        AU.parse_set("/a")


def test_no_vendored_schema_and_no_checker_are_refusals_not_writes(d2157, monkeypatch):
    target = d2157 / REPORT / VISUAL_FILE
    data = _load(target)
    data["$schema"] = data["$schema"].replace("2.12.0", "99.0.0")
    target.write_text(json.dumps(data), "utf-8")
    before = target.read_bytes()
    res = AU.patch_file(str(d2157), visual=CARD, sets=["/position/x=1"])
    assert res["fail"] == "schema_unvendored" and "99.0.0" in res["schema"]
    assert target.read_bytes() == before

    monkeypatch.setattr(SC, "available", lambda: False)
    res = AU.patch_file(str(d2157), file=f"definition/pages/{PAGE}/page.json", sets=["/displayOption=ActualSize"])
    assert res["fail"] == "schema_checker_missing" and 'pip install "agentdata[pbi]"' in res["hint"]
    assert _load(d2157 / REPORT / "definition" / "pages" / PAGE / "page.json")["displayOption"] == "FitToPage"


def test_check_reports_schema_invalid_on_a_broken_copy_of_the_2157_fixture(d2157, capsys):
    target = d2157 / REPORT / VISUAL_FILE
    data = _load(target)
    data["position"]["tabOrder"] = "second"
    data["visual"]["notAThing"] = 1
    target.write_text(json.dumps(data), "utf-8")
    model, report, _ = N.load_all(str(d2157))
    found = [f for f in CK.check_report(report, model) if f.kind == "schema-invalid"]
    assert [(f.severity, f.where, f.object) for f in found] == [(CK.SCHEMA_SEVERITY, VISUAL_FILE, CARD)] * 2
    assert sorted(f.message for f in found) == [
        "$.position.tabOrder: 'second' is not of type 'number'",
        "$.visual: Additional properties are not allowed ('notAThing' was unexpected)"]
    assert found[0].hint == "fix the property named, or re-save in Desktop 2.157"
    with pytest.raises(SystemExit):
        main(["check", str(d2157)])
    assert "schema-invalid" in capsys.readouterr().out
    # the fixture as shipped, and the one `pbir patch` wrote, carry none
    model, report, _ = N.load_all(str(D2157))
    assert [f for f in CK.check_report(report, model) if f.kind.startswith("schema-")] == []


def test_check_says_once_when_it_could_not_validate(d2157, monkeypatch):
    monkeypatch.setattr(SC, "available", lambda: False)
    model, report, _ = N.load_all(str(d2157))
    found = [f for f in CK.check_report(report, model) if f.kind.startswith("schema-")]
    assert [(f.severity, f.kind, f.hint) for f in found] == [("info", "schema-check-skipped", 'pip install "agentdata[pbi]"')]


def test_the_test_helper_is_the_package_module():
    for name in ("SCHEMAS", "BASE", "REPORT_3_1", "DESKTOP_2157", "registry", "vendored", "errors", "file_errors"):
        assert getattr(S, name) is getattr(SC, name), name
    assert SC.SCHEMAS == Path(SC.__file__).resolve().parent / "schema"
    assert SC.available() is True
    assert not SC.vendored("https://example.com/schema.json")
