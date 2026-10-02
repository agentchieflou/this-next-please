"""DAX user-defined functions (GA in Power BI Desktop 2.155, June 2026) through the PBIP tools: the TMDL `function`
object in the projection and the normalizer, the `ad-pbip check` rules, `function.set` / `function.delete` in both
`model apply` tiers, the audit rules, and `ad-pbip model refresh` (the Calculate / Full step after a model reload).

The fixture is the native gallery model: `functions.tmdl` holds AddTax (one optional parameter) and MarginShare, and
the measure 'Sales'[Sales with Tax] calls AddTax with the optional argument left out."""
from __future__ import annotations
import json
import os
import shutil

import pytest

from agentdata import cli_pbip
from agentdata.pbip import audit as ADT
from agentdata.pbip import check as CK
from agentdata.pbip import desktop as DT
from agentdata.pbip import features as F
from agentdata.pbip import normalize as N
from agentdata.pbip import project as PJ
from agentdata.pbip import tmdl as T
from agentdata.pbip import tom as TOM

ROOT = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(ROOT, "fixtures", "pbip", "native")
NATIVE_MODEL = os.path.join(NATIVE, "Native.SemanticModel", "definition")
SAMPLE = os.path.join(ROOT, "fixtures", "sample.pbip")


@pytest.fixture()
def model_copy(tmp_path):
    dest = tmp_path / "Native"
    shutil.copytree(NATIVE, dest)
    return dest / "Native.SemanticModel" / "definition"


def _kinds(defn) -> list[str]:
    return [f.kind for f in CK.check_model(N.load_model(str(defn)))]


# ---------------------------------------------------------------------------------------------- the signature


def test_a_signature_gives_parameters_types_defaults_and_arity():
    sig = N.parse_function('( a, b : INT64, c : Scalar String = "x, (y)", d : ColumnRef, e : TABLE EXPR = ALL ( \'T\' ) ) => a')
    assert [p["name"] for p in sig["params"]] == ["a", "b", "c", "d", "e"]
    a, b, c, d, e = sig["params"]
    assert (a["type"], a["mode"], a["optional"]) == ("AnyVal", "val", False)       # nothing given = AnyVal val
    assert (b["type"], b["subtype"]) == ("Scalar", "Int64")                        # a subtype implies Scalar
    assert c["default"] == '"x, (y)"' and c["optional"]                           # a comma in a string is not a split
    assert (d["type"], d["mode"]) == ("ColumnRef", "expr")                         # the *Ref types are expr
    assert (e["type"], e["mode"], e["default"]) == ("Table", "expr", "ALL ( 'T' )")
    assert (sig["min_args"], sig["max_args"]) == (4, 5)                            # the rightmost required one is 4th
    assert sig["body"] == "a"
    assert N.parse_function("() => RANDBETWEEN ( 10, 100 )")["max_args"] == 0
    assert N.parse_function("// a note\n( x ) =>\n    x * 2")["body"] == "x * 2"
    assert N.parse_function("SUM ( Sales[Amount] )") is None
    assert N.parse_function("( x ) x * 2") is None


def test_calls_count_arguments_and_skip_strings_comments_and_lookalikes():
    expr = 'AddTax ( [A] ) + addtax([B], , ) + Ns.Fn ( 1, ( 2, 3 ) ) + AddTaxNot(1) // AddTax(1,2,3)\n& "AddTax(9)"'
    assert N.function_calls(expr, ["AddTax", "Ns.Fn"]) == [("AddTax", 1), ("AddTax", 3), ("Ns.Fn", 2)]
    assert N.functions_called("Fn () + Fn ( 1 )", ["Fn"]) == ["Fn"]
    assert N.function_calls("'T'[AddTax] + [AddTax]", ["AddTax"]) == []


def test_naming_rules():
    assert N.function_name_problems("Sales.AddTax") == [] and N.function_name_problems("_x1") == []
    assert N.function_name_problems("1abc") and N.function_name_problems("a..b") and N.function_name_problems("a.") and N.function_name_problems("has space")
    assert N.function_name_problems("Measure")                                             # a reserved word
    bad = N.parse_function("( c : COLUMNREF VAL, ok_1 ) => c")["params"]
    assert N.function_param_problems(bad[0]) and not N.function_param_problems(bad[1])


# ---------------------------------------------------------------------------------------------- normalizer + projection


def test_the_native_model_carries_its_functions_and_who_calls_them():
    model, _report, norm = N.load_all(os.path.join(NATIVE, "Native.pbip"))
    assert model.compatibility == "1702"
    add, share = model.functions
    assert (add["name"], add["file"], add["min_args"], add["max_args"]) == ("AddTax", "functions.tmdl", 1, 2)
    assert [(p["name"], p["subtype"], p["optional"], p["default"]) for p in add["parameters"]] == \
        [("amount", "Numeric", False, None), ("taxRate", "Numeric", True, "0.1")]
    assert add["description"] == "AddTax takes in amount and returns amount including tax"
    assert add["parameters"][1]["doc"].startswith("Optional tax rate") and add["returns"] == "The amount including tax"
    assert share["body"] == "DIVIDE ( [Margin], value )" and share["deps"]["measures"] == ["Margin"]   # multi-line form
    sales = next(t for t in model.tables if t["name"] == "Sales")
    with_tax = next(m for m in sales["measures"] if m["name"] == "Sales with Tax")
    assert with_tax["deps"] == {"columns": [], "measures": ["Total Sales"], "functions": ["AddTax"]}
    assert norm["model"]["functions"] == model.functions
    assert norm["lineage"]["function_usage"] == {"AddTax": ["'Sales'[Sales with Tax]"], "MarginShare": []}
    assert "function MarginShare" in norm["lineage"]["measure_usage"]["[Margin]"]   # `refs --measure Margin` sees it


def test_the_projection_lists_functions_and_a_model_without_them_has_no_functions_file(tmp_path):
    model, report, norm = N.load_all(os.path.join(NATIVE, "Native.pbip"))
    res = PJ.write_projection(norm, model, report, str(tmp_path / "native"))
    assert "functions.tsv" in res["files"]
    md = (tmp_path / "native" / "MODEL.md").read_text(encoding="utf-8")
    assert "2 functions" in md and "## Functions (DAX UDFs) — `functions.tmdl`" in md
    assert "- **AddTax**(amount : NUMERIC, [taxRate : NUMERIC = 0.1]) — 1–2 args" in md
    assert "used by 'Sales'[Sales with Tax]" in md and "**MarginShare**(value : SCALAR NUMERIC VAL) — 1 args" in md
    assert "| Sales with Tax | $ #,##0 |  | [Total Sales], AddTax() |" in md
    rows = (tmp_path / "native" / "functions.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0].split("\t")[:5] == ["function", "parameters", "min_args", "max_args", "optional"]
    assert rows[1].split("\t")[4] == "taxRate" and "'Sales'[Sales with Tax]" in rows[1]
    assert "- AddTax(): 'Sales'[Sales with Tax]" in (tmp_path / "native" / "LINEAGE.md").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "native" / "meta.json").read_text(encoding="utf-8"))["counts"]["functions"] == 2

    model, report, norm = N.load_all(SAMPLE)
    res = PJ.write_projection(norm, model, report, str(tmp_path / "sample"))
    assert "functions.tsv" not in res["files"] and "Functions" not in (tmp_path / "sample" / "MODEL.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------- ad-pbip check


def test_check_needs_compatibility_1702_for_functions(model_copy):
    assert [k for k in _kinds(model_copy) if k.startswith("udf")] == []
    db = model_copy / "database.tmdl"
    db.write_text(db.read_text(encoding="utf-8").replace("1702", "1600"), encoding="utf-8")
    finding = next(f for f in CK.check_model(N.load_model(str(model_copy))) if f.kind == "udf-compatibility-level")
    assert finding.severity == "error" and finding.where == "database.tmdl" and "1600" in finding.message
    (model_copy / "functions.tmdl").unlink()                                       # no functions, no rule
    assert "udf-compatibility-level" not in _kinds(model_copy)


def test_check_catches_a_broken_function(model_copy):
    fns = model_copy / "functions.tmdl"
    fns.write_text(fns.read_text(encoding="utf-8") + (
        "\nfunction NoSignature = SUM ( Sales[Quantity] )\n"
        "\nfunction 'Bad..Name' = ( x ) => x\n"
        "\nfunction RefByValue = ( c : ColumnRef VAL, n : Scalar Wrong ) => c\n"
        "\nfunction Loop = ( x ) => Loop ( x )\n"
        "\nfunction AddTax = ( y ) => y\n"), encoding="utf-8")
    sales = model_copy / "tables" / "Sales.tmdl"
    sales.write_text(sales.read_text(encoding="utf-8").replace("AddTax ( [Total Sales] )", "AddTax ( [Total Sales], 0.2, 3 )"),
                     encoding="utf-8")
    found = {(f.kind, f.object) for f in CK.check_model(N.load_model(str(model_copy)))}
    assert ("udf-signature", "function NoSignature") in found
    assert ("udf-name-invalid", "function Bad..Name") in found
    assert ("udf-parameter", "function RefByValue") in found and ("udf-parameter-type", "function RefByValue") in found
    assert ("udf-recursive", "function Loop") in found
    assert ("udf-name-dup", "function AddTax") in found
    assert ("udf-call-arity", "'Sales'[Sales with Tax]") in found


def test_leaving_an_optional_argument_out_or_empty_is_not_an_arity_finding(model_copy):
    sales = model_copy / "tables" / "Sales.tmdl"
    text = sales.read_text(encoding="utf-8")
    for call in ("AddTax ( [Total Sales], 0.2 )", "AddTax ( [Total Sales], )"):
        sales.write_text(text.replace("AddTax ( [Total Sales] )", call), encoding="utf-8")
        assert "udf-call-arity" not in _kinds(model_copy), call
    sales.write_text(text.replace("AddTax ( [Total Sales] )", "AddTax ( )"), encoding="utf-8")
    assert "udf-call-arity" in _kinds(model_copy)


# ---------------------------------------------------------------------------------------------- model apply: TMDL tier


def test_function_ops_on_the_tmdl_files(model_copy):
    res = TOM.model_apply([
        {"op": "function.set", "name": "AddTax", "description": "Amount with tax"},
        {"op": "function.set", "name": "Sales.Discount", "description": "Amount after a discount",
         "expression": "( amount : NUMERIC, pct : NUMERIC = 0.05 ) =>\nVAR d = amount * pct\nRETURN amount - d"},
        {"op": "function.delete", "name": "MarginShare"},
    ], definition_dir=str(model_copy))
    assert res["tier"] == "file" and [r["action"] for r in res["results"]] == ["updated", "added", "deleted"]
    text = (model_copy / "functions.tmdl").read_text(encoding="utf-8")
    assert text.startswith("/// Amount with tax\nfunction AddTax = ( amount : NUMERIC, taxRate : NUMERIC = 0.1 ) => amount * ( 1 + taxRate )\n"
                           "\tlineageTag: 10000000-0000-0000-0000-0000000000f1\n")   # expression and tag kept
    assert "/// Amount after a discount\nfunction 'Sales.Discount' = ```\n\t\t( amount : NUMERIC, pct : NUMERIC = 0.05 ) =>\n" in text
    assert "MarginShare" not in text and text.count("lineageTag") == 1             # no invented tag on the new one
    model = N.load_model(str(model_copy))
    assert [f["name"] for f in model.functions] == ["AddTax", "Sales.Discount"]
    assert model.functions[1]["min_args"] == 1 and model.functions[1]["body"].startswith("VAR d")
    assert CK.check_model(model) == []


def test_function_ops_create_functions_tmdl_and_refuse_what_the_engine_would(model_copy):
    (model_copy / "functions.tmdl").unlink()
    sales = model_copy / "tables" / "Sales.tmdl"
    sales.write_text(sales.read_text(encoding="utf-8").replace("AddTax ( [Total Sales] )", "[Total Sales] * 1.1"), encoding="utf-8")
    res = TOM.model_apply([{"op": "function.set", "name": "Twice", "expression": "( x ) => x * 2"}], definition_dir=str(model_copy))
    assert res["results"][0]["status"] == "ok"
    assert (model_copy / "functions.tmdl").read_text(encoding="utf-8") == "function Twice = ( x ) => x * 2\n"
    gone = TOM.model_apply([{"op": "function.delete", "name": "Nope"}], definition_dir=str(model_copy))
    assert gone["results"][0]["status"] == "fail" and "not found" in gone["results"][0]["error"]
    new_without_expr = TOM.model_apply([{"op": "function.set", "name": "New"}], definition_dir=str(model_copy))
    assert "needs its expression" in new_without_expr["results"][0]["error"]
    db = model_copy / "database.tmdl"
    db.write_text(db.read_text(encoding="utf-8").replace("1702", "1600"), encoding="utf-8")
    old = TOM.model_apply([{"op": "function.set", "name": "Thrice", "expression": "( x ) => x * 3"}], definition_dir=str(model_copy))
    assert old["results"][0]["status"] == "fail" and "compatibilityLevel 1702" in old["results"][0]["error"]
    assert "Thrice" not in (model_copy / "functions.tmdl").read_text(encoding="utf-8")
    for op, why in (({"op": "function.set", "name": "has space", "expression": "( x ) => x"}, "function name"),
                    ({"op": "function.set", "name": "F", "expression": "x * 2"}, "( parameters ) => body"),
                    ({"op": "function.set", "name": "F", "expression": "( c : MeasureRef VAL ) => c"}, "not allowed"),
                    ({"op": "function.set", "name": "F", "expression": "( x ) => x", "isHidden": True}, "cannot be hidden"),
                    ({"op": "function.delete"}, "needs the function's name")):
        with pytest.raises(ValueError, match=r".*" + why.replace("(", r"\(").replace(")", r"\)")):
            TOM.validate_ops([op])


def test_cli_model_apply_runs_function_ops(model_copy, tmp_path, capsys):
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps([{"op": "function.set", "name": "Half", "expression": "( x : NUMERIC ) => x / 2"}]), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli_pbip.main(["model", "apply", "--model", str(model_copy), "--ops", str(ops)])
    assert exc.value.code == 0
    assert "Half" in capsys.readouterr().out and "function Half" in (model_copy / "functions.tmdl").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------- model apply: live tier


def test_the_live_script_emits_only_the_cases_it_uses_and_guards_functions(tmp_path):
    ops = [{"op": "function.set", "name": "AddTax", "expression": "( a : NUMERIC ) => a * 1.1", "description": 'say "hi"'},
           {"op": "function.delete", "name": "Old"}]
    script = TOM.build_te2_script(ops, str(tmp_path / "out.json"))
    assert 'case "function.set":' in script and 'case "function.delete":' in script and 'case "measure.set":' not in script
    assert 'GetProperty("Functions") == null' in script and TOM.NO_UDF in script   # an old TE2 fails closed
    assert "CompatibilityLevel < 1702" in script and "((dynamic)Model).AddFunction(fName)" in script
    assert '$"' not in script and "using Microsoft.AnalysisServices.Tabular;" not in script   # TE2's C# 5 compiler
    assert "Model.Database.TOMDatabase.Model.SaveChanges();" in script
    assert '""description"": ""say \\""hi\\""""' in script                         # the ops JSON in a verbatim string
    both = TOM.build_te2_script([{"op": "measure.set", "table": "Sales", "name": "M", "expression": "1"}], "o.json")
    assert 'case "measure.set":' in both and "function" not in both.split("switch (opType)")[1]

    def fake_te2(args, timeout=60):
        text = open(args[args.index("-S") + 1], encoding="utf-8").read()
        out = [ln for ln in text.splitlines() if "var outPath =" in ln][0].split('@"')[1].split('";')[0]
        with open(out, "w", encoding="utf-8") as f:
            json.dump([{"op": 0, "status": "fail", "error": TOM.NO_UDF}], f)
        return 0, "", ""

    res = TOM.model_apply(ops[:1], server="localhost:5000", runner=fake_te2)
    assert res["tier"] == "live" and res["results"][0]["error"] == TOM.NO_UDF


# ---------------------------------------------------------------------------------------------- model refresh


def test_refresh_steps_run_targeted_and_refuse_a_model_wide_full():
    assert TOM.refresh_steps("calculate") == [("calculate", "")]
    assert TOM.refresh_steps("full", ["Sales", "Dates", "Sales"]) == [("full", "Sales"), ("full", "Dates")]
    assert TOM.refresh_steps("full", all_tables=True) == [("full", "")]
    for args, why in ((("full",), "--all"), (("full", ["Sales"], True), "not both"), (("process",), "one of")):
        with pytest.raises(ValueError, match=why):
            TOM.refresh_steps(*args)
    script = TOM.build_refresh_script([("full", "Sales"), ("full", "It's \"x\"")], "C:/out.json")
    assert 'new string[] { "full", "Sales" }, new string[] { "full", "It\'s \\"x\\"" }' in script
    assert "TOM.RefreshType.Full : TOM.RefreshType.Calculate" in script and "tom.Tables.Find(step[1])" in script
    assert script.count("tom.SaveChanges();") == 1 and "break;" in script and '$"' not in script


def _fake_refresh(rows, seen):
    def run(args, timeout=60):
        seen.append(args)
        text = open(args[args.index("-S") + 1], encoding="utf-8").read()
        out = [ln for ln in text.splitlines() if "var outPath =" in ln][0].split('@"')[1].split('";')[0]
        with open(out, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        return 0, "", ""
    return run


def test_model_refresh_reports_each_step_and_the_verifying_query():
    seen: list = []
    ok = TOM.model_refresh("localhost:5000", "full", ["Sales Fact"], te2_exe="te2.exe",
                           run=_fake_refresh([{"type": "full", "table": "Sales Fact", "status": "ok", "ms": 9}], seen))
    assert seen[0][:3] == ["te2.exe", "localhost:5000", ""] and seen[0][3] == "-S"
    assert ok["ok"] and ok["not_run"] == []
    assert "ad-pbip dax --server localhost:5000 --query \"EVALUATE { COUNTROWS('Sales Fact') }\"" in ok["next"]
    bad = TOM.model_refresh("localhost:5000", "full", ["A", "B"], te2_exe="te2.exe",
                            run=_fake_refresh([{"type": "full", "table": "A", "status": "fail", "error": "no creds"}], seen))
    assert not bad["ok"] and bad["not_run"] == [{"type": "full", "table": "B"}] and "next" not in bad
    silent = TOM.model_refresh("localhost:5000", "calculate", te2_exe="te2.exe", run=lambda a, t=60: (1, "", "TE2 crashed"))
    assert not silent["ok"] and "TE2 crashed" in silent["steps"][0]["error"]


def test_cli_model_refresh(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)                                                    # rendered tables land in .agent/out
    seen: list = []
    monkeypatch.setattr(DT, "default_run", _fake_refresh([{"type": "calculate", "table": "", "status": "ok", "ms": 4}], seen))
    with pytest.raises(SystemExit) as exc:
        cli_pbip.main(["model", "refresh", "--type", "calculate", "--server", "localhost:5000", "--te2-exe", "te2.exe"])
    out = capsys.readouterr().out
    assert exc.value.code == 0 and "source: ad-pbip model refresh" in out
    assert "table: (model)\nstatus: ok\nms: 4" in out                             # one step renders as a record
    assert "EVALUATE { [<the measure you changed>] }" in out
    with pytest.raises(SystemExit) as exc:
        cli_pbip.main(["model", "refresh", "--type", "full", "--server", "localhost:5000"])
    assert exc.value.code == 2 and "--all" in capsys.readouterr().out and len(seen) == 1   # refused before TE2 ran


# ---------------------------------------------------------------------------------------------- audit + features


def test_audit_reads_function_bodies_and_flags_undocumented_or_unused_functions(model_copy):
    fns = model_copy / "functions.tmdl"
    fns.write_text(fns.read_text(encoding="utf-8") + "\nfunction RegionCount = () => DISTINCTCOUNT ( 'Customers'[Region] )\n",
                   encoding="utf-8")
    findings = ADT.audit_model(N.load_model(str(model_copy)))
    rows = {(f.rule_id, f.obj) for f in findings}
    assert ("unused-columns", "'Customers'[Region]") not in rows                   # read inside a function body
    assert ("unused-columns", "'Customers'[CustomerName]") in rows
    assert ("udf-missing-description", "function RegionCount") in rows
    assert ("unused-function", "function MarginShare") in rows and ("unused-function", "function AddTax") not in rows
    for f in findings:
        if f.fix:
            assert f.fix["op"] in TOM.VALID_OPS
            TOM.validate_ops([f.fix])


def test_udf_is_a_native_feature_with_a_live_check():
    model = N.load_model(NATIVE_MODEL)
    udf = next(f for f in F.detect_features(model, None) if f.feature == "udf")
    assert udf.present and udf.objects == ["AddTax", "MarginShare"]
    assert not next(f for f in F.detect_features(N.load_model(os.path.join(SAMPLE, "Sample.SemanticModel", "definition")), None)
                    if f.feature == "udf").present
    seen = []

    def fake_dscmd(args, timeout=30):
        seen.append(args)
        with open(args[2], "w", encoding="utf-8") as f:
            f.write("Name,State\nAddTax,Ready\n")
        return 0, "", ""

    dscmd = os.path.join(ROOT, "conftest.py")                                      # any existing file stands in for dscmd.exe
    res = F.verify_feature_live("udf", "localhost:5000", "Model", runner=fake_dscmd, dscmd_exe=dscmd)
    assert res["verified"] and res["query"] == "EVALUATE INFO.USERDEFINEDFUNCTIONS()"


def test_a_tmdl_function_round_trips_byte_for_byte():
    path = os.path.join(NATIVE_MODEL, "functions.tmdl")
    tf = T.read_file(path)
    assert [n.kind for n in tf.nodes] == ["function", "function"] and T.lint_file(tf) == []
    assert tf.text.encode("utf-8") == open(path, "rb").read()
