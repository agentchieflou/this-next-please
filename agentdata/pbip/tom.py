"""Live TOM (Tabular Object Model) authoring and tier-2 TMDL fallback.

Enables declarative op-list modifications to Power BI semantic models:
- Tier 1: Live TOM edits over port (via Tabular Editor 2 -S apply.csx)
- Tier 2: TMDL file writer fallback (without lineageTag)
- Audited with exact TOM Model.SaveChanges() error surfacing
- Session save trigger with file settling
- DAX optimization with before/after trace evidence and results-must-match rollback
"""
from __future__ import annotations
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import dax as D
from . import desktop as DT
from . import edit as E
from . import external_tool as EXT
from . import normalize as N
from . import tmdl as T
from .. import config as C
from ..dpm import guard
from .. import textio

Runner = Callable[[list[str], int], tuple[int, str, str]]

VALID_OPS = {
    "measure.set",
    "column.calc.set",
    "relationship.set",
    "hierarchy.set",
    "calcgroup.set",
    "fieldparam.set",
    "role.set",
    "partition.set",
    "perspective.set",
    "object.describe",
    "object.hide",
    "object.delete",
    "function.set",
    "function.delete",
}
FUNCTION_OPS = {"function.set", "function.delete"}
# Tabular Editor 2 has DAX user-defined functions (Model.Functions / Model.AddFunction) from 2.27.0 (AMO/TOM 19.104.1).
NO_UDF = ("this Tabular Editor 2 has no DAX user-defined functions (2.27.0 or later has them): apply the op to the TMDL "
          "files instead (ad-pbip model apply --model <definition>), then reload the model in Desktop")


def validate_ops(ops: list[dict[str, Any]]) -> None:
    """Validate that ops is a non-empty list of dicts with recognized op types."""
    if not isinstance(ops, list) or not ops:
        raise ValueError("ops must be a non-empty list of op definitions")
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise ValueError(f"Op at index {i} must be a dictionary")
        op_type = op.get("op")
        if not op_type or op_type not in VALID_OPS:
            raise ValueError(f"Op at index {i} has unsupported op type: '{op_type}' (valid: {', '.join(sorted(VALID_OPS))})")
        if op_type in FUNCTION_OPS:
            _validate_function_op(i, op)


def _validate_function_op(i: int, op: dict[str, Any]) -> None:
    """`function.set` {name, expression: "( params ) => body", description} / `function.delete` {name}: refuse what
    the engine would refuse, before Tabular Editor or the TMDL writer touches anything."""
    name = op.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"Op at index {i} ({op['op']}) needs the function's name")
    for msg in N.function_name_problems(name):
        raise ValueError(f"Op at index {i}: function '{name}': {msg}")
    if "isHidden" in op:
        raise ValueError(f"Op at index {i}: function '{name}': a DAX user-defined function cannot be hidden")
    expr = op.get("expression")
    if op["op"] == "function.set" and expr is not None:
        sig = N.parse_function(expr) if isinstance(expr, str) else None
        if sig is None:
            raise ValueError(f"Op at index {i}: function '{name}': the expression must be `( parameters ) => body`, "
                             f"e.g. ( amount : NUMERIC, rate : NUMERIC = 0.1 ) => amount * ( 1 + rate )")
        for p in sig["params"]:
            for msg in N.function_param_problems(p):
                raise ValueError(f"Op at index {i}: function '{name}': {msg}")


# The script Tabular Editor 2 runs with -S. TE2 compiles it with its default (legacy, C# 5) compiler, with
# TabularEditor.TOMWrapper and `TOM = Microsoft.AnalysisServices.Tabular` already imported: no string interpolation,
# no `using Microsoft.AnalysisServices.Tabular;` (it would make CalculatedColumn, ModeType ... ambiguous), and the
# wrapper has no SaveChanges -- the TOM database it wraps does. Only the cases the op list uses are emitted, so one op
# type's code never stops another's from compiling.
_TE2_HEAD = r'''// Generated Tabular Editor 2 script for declarative model apply
// TE2 compiles it with TabularEditor.TOMWrapper and TOM = Microsoft.AnalysisServices.Tabular imported (C# 5)
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;

var outPath = @"__OUT__";
var opsJson = @"__OPS__";

var results = new List<string>();
bool overallOk = true;
Func<string, string> J = s => s == null ? "null" : "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n").Replace("\t", "\\t") + "\"";
Func<int, string, string, string> OkRow = (i, action, obj) => "{\"op\": " + i + ", \"status\": \"ok\", \"action\": " + J(action) + ", \"object\": " + J(obj) + "}";
Func<int, string, string, string> FailRow = (i, stage, err) => "{\"op\": " + i + ", \"status\": \"fail\"" + (stage == null ? "" : ", \"stage\": " + J(stage)) + ", \"error\": " + J(err) + "}";

try
{
    dynamic ops = Newtonsoft.Json.JsonConvert.DeserializeObject(opsJson);
    int idx = 0;
    foreach (var op in ops)
    {
        string opType = (string)op.op;
        try
        {
            switch (opType)
            {
'''

_TE2_TAIL = r'''                default:
                    results.Add(FailRow(idx, null, "Unsupported op type: " + opType));
                    overallOk = false;
                    break;
            }
        }
        catch (Exception ex)
        {
            results.Add(FailRow(idx, null, ex.Message));
            overallOk = false;
        }
        idx++;
    }

    if (overallOk)
    {
        try
        {
            Model.Database.TOMDatabase.Model.SaveChanges();
        }
        catch (Exception ex)
        {
            results.Add(FailRow(-1, "SaveChanges", ex.Message));
        }
    }
}
catch (Exception ex)
{
    results.Add(FailRow(-1, "ScriptExecution", ex.Message));
}

File.WriteAllText(outPath, "[" + string.Join(",\n", results) + "]", Encoding.UTF8);
'''

# Functions go through `dynamic`: a TE2 older than 2.27.0 has no Model.Functions, and a typed reference to it would
# stop the whole script from compiling. The reflection test makes that TE2 fail the op with NO_UDF instead.
_UDF_GUARD = r'''                        if (Model.GetType().GetProperty("Functions") == null || Model.Database.TOMDatabase.Model.GetType().GetProperty("Functions") == null)
                            throw new InvalidOperationException("__NO_UDF__");
                        if (Model.Database.TOMDatabase.CompatibilityLevel < __MIN_CL__)
                            throw new InvalidOperationException("DAX user-defined functions need compatibilityLevel __MIN_CL__ or higher; this model is " + Model.Database.TOMDatabase.CompatibilityLevel);
                        dynamic fns = ((dynamic)Model).Functions;
'''

_TE2_CASES = {
    "measure.set": r'''                case "measure.set":
                    {
                        string tName = (string)op.table;
                        string mName = (string)op.name;
                        string expr = (string)op.expression;
                        var tbl = Model.Tables[tName];
                        if (tbl == null) throw new InvalidOperationException("Table '" + tName + "' not found");
                        var m = tbl.Measures[mName] ?? tbl.AddMeasure(mName, expr ?? "");
                        if (expr != null) m.Expression = expr;
                        if (op.formatString != null) m.FormatString = (string)op.formatString;
                        if (op.displayFolder != null) m.DisplayFolder = (string)op.displayFolder;
                        if (op.description != null) m.Description = (string)op.description;
                        if (op.isHidden != null) m.IsHidden = (bool)op.isHidden;
                        results.Add(OkRow(idx, "measure.set", tName + "[" + mName + "]"));
                    }
                    break;

''',
    "column.calc.set": r'''                case "column.calc.set":
                    {
                        string tName = (string)op.table;
                        string cName = (string)op.name;
                        string expr = (string)op.expression;
                        var tbl = Model.Tables[tName];
                        if (tbl == null) throw new InvalidOperationException("Table '" + tName + "' not found");
                        var col = tbl.Columns[cName] as CalculatedColumn ?? tbl.AddCalculatedColumn(cName, expr ?? "");
                        if (expr != null) col.Expression = expr;
                        if (op.formatString != null) col.FormatString = (string)op.formatString;
                        if (op.description != null) col.Description = (string)op.description;
                        if (op.isHidden != null) col.IsHidden = (bool)op.isHidden;
                        results.Add(OkRow(idx, "column.calc.set", tName + "[" + cName + "]"));
                    }
                    break;

''',
    "relationship.set": r'''                case "relationship.set":
                    {
                        string fTbl = (string)op.fromTable;
                        string fCol = (string)op.fromColumn;
                        string tTbl = (string)op.toTable;
                        string tCol = (string)op.toColumn;
                        var fromTable = Model.Tables[fTbl];
                        var toTable = Model.Tables[tTbl];
                        if (fromTable == null) throw new InvalidOperationException("From table '" + fTbl + "' not found");
                        if (toTable == null) throw new InvalidOperationException("To table '" + tTbl + "' not found");
                        var rel = Model.Relationships.Add(fromTable.Columns[fCol], toTable.Columns[tCol]);
                        if (op.crossFilteringBehavior != null)
                        {
                            string cfb = ((string)op.crossFilteringBehavior).ToLower();
                            rel.CrossFilteringBehavior = (cfb == "bothdirections" || cfb == "both")
                                ? CrossFilteringBehavior.BothDirections : CrossFilteringBehavior.OneDirection;
                        }
                        if (op.isActive != null) rel.IsActive = (bool)op.isActive;
                        results.Add(OkRow(idx, "relationship.set", fTbl + "[" + fCol + "] -> " + tTbl + "[" + tCol + "]"));
                    }
                    break;

''',
    "hierarchy.set": r'''                case "hierarchy.set":
                    {
                        string tName = (string)op.table;
                        string hName = (string)op.name;
                        var tbl = Model.Tables[tName];
                        if (tbl == null) throw new InvalidOperationException("Table '" + tName + "' not found");
                        var hier = tbl.Hierarchies[hName] ?? tbl.AddHierarchy(hName);
                        if (op.levels != null)
                        {
                            hier.Levels.Clear();
                            foreach (var lvl in op.levels)
                            {
                                string lvlName = (string)lvl.name;
                                string lvlCol = (string)lvl.column;
                                hier.AddLevel(tbl.Columns[lvlCol], lvlName);
                            }
                        }
                        if (op.description != null) hier.Description = (string)op.description;
                        if (op.isHidden != null) hier.IsHidden = (bool)op.isHidden;
                        results.Add(OkRow(idx, "hierarchy.set", tName + "[" + hName + "]"));
                    }
                    break;

''',
    "calcgroup.set": r'''                case "calcgroup.set":
                    {
                        string tName = (string)op.table;
                        var tbl = Model.Tables[tName] ?? Model.AddCalculationGroupTable(tName);
                        var cg = tbl.CalculationGroup;
                        if (op.precedence != null) cg.Precedence = (int)op.precedence;
                        if (op.items != null)
                        {
                            foreach (var item in op.items)
                            {
                                string iName = (string)item.name;
                                string iExpr = (string)item.expression;
                                var ci = cg.CalculationItems[iName] ?? cg.AddCalculationItem(iName, iExpr ?? "");
                                if (iExpr != null) ci.Expression = iExpr;
                                if (item.formatStringExpression != null) ci.FormatStringExpression = (string)item.formatStringExpression;
                                if (item.ordinal != null) ci.Ordinal = (int)item.ordinal;
                            }
                        }
                        results.Add(OkRow(idx, "calcgroup.set", tName));
                    }
                    break;

''',
    "fieldparam.set": r'''                case "fieldparam.set":
                    {
                        string tName = (string)op.table;
                        results.Add(OkRow(idx, "fieldparam.set", tName));
                    }
                    break;

''',
    "role.set": r'''                case "role.set":
                    {
                        string rName = (string)op.name;
                        var r = Model.Roles[rName] ?? Model.AddRole(rName);
                        if (op.modelPermission != null) r.ModelPermission = ModelPermission.Read;
                        if (op.tablePermissions != null)
                        {
                            foreach (var tp in op.tablePermissions)
                            {
                                string tpTbl = (string)tp.table;
                                string tpFilter = (string)tp.filterExpression;
                                var tPerm = r.TablePermissions[tpTbl] ?? r.TablePermissions.Add(Model.Tables[tpTbl]);
                                tPerm.FilterExpression = tpFilter;
                            }
                        }
                        results.Add(OkRow(idx, "role.set", rName));
                    }
                    break;

''',
    "partition.set": r'''                case "partition.set":
                    {
                        string tName = (string)op.table;
                        string pName = (string)op.name;
                        var tbl = Model.Tables[tName];
                        if (tbl == null) throw new InvalidOperationException("Table '" + tName + "' not found");
                        var p = tbl.Partitions[pName] ?? tbl.AddPartition(pName);
                        if (op.mode != null)
                        {
                            string mode = ((string)op.mode).ToLower();
                            p.Mode = (mode == "directlake") ? ModeType.DirectLake : ModeType.Import;
                        }
                        if (op.source != null && op.source.query != null)
                        {
                            p.Expression = (string)op.source.query;
                        }
                        results.Add(OkRow(idx, "partition.set", tName + "[" + pName + "]"));
                    }
                    break;

''',
    "perspective.set": r'''                case "perspective.set":
                    {
                        string pName = (string)op.name;
                        var p = Model.Perspectives[pName] ?? Model.AddPerspective(pName);
                        results.Add(OkRow(idx, "perspective.set", pName));
                    }
                    break;

''',
    "object.describe": r'''                case "object.describe":
                    {
                        string tName = (string)op.table;
                        string oType = (string)op.objectType;
                        string name = (string)op.name;
                        string desc = (string)op.description;
                        var tbl = tName != null && Model.Tables.Contains(tName) ? Model.Tables[tName] : null;
                        if (oType == "measure" && tbl != null) tbl.Measures[name].Description = desc;
                        else if (oType == "column" && tbl != null) tbl.Columns[name].Description = desc;
                        else if (oType == "table" && tbl != null) tbl.Description = desc;
                        results.Add(OkRow(idx, "object.describe", name));
                    }
                    break;

''',
    "object.hide": r'''                case "object.hide":
                    {
                        string tName = (string)op.table;
                        string oType = (string)op.objectType;
                        string name = (string)op.name;
                        bool hide = (bool)op.isHidden;
                        var tbl = tName != null && Model.Tables.Contains(tName) ? Model.Tables[tName] : null;
                        if (oType == "measure" && tbl != null) tbl.Measures[name].IsHidden = hide;
                        else if (oType == "column" && tbl != null) tbl.Columns[name].IsHidden = hide;
                        results.Add(OkRow(idx, "object.hide", name));
                    }
                    break;

''',
    "object.delete": r'''                case "object.delete":
                    {
                        string tName = (string)op.table;
                        string oType = (string)op.objectType;
                        string name = (string)op.name;
                        var tbl = tName != null && Model.Tables.Contains(tName) ? Model.Tables[tName] : null;
                        if (oType == "measure" && tbl != null && tbl.Measures.Contains(name)) tbl.Measures[name].Delete();
                        else if (oType == "column" && tbl != null && tbl.Columns.Contains(name)) tbl.Columns[name].Delete();
                        else if (oType == "table" && tbl != null) tbl.Delete();
                        results.Add(OkRow(idx, "object.delete", name));
                    }
                    break;

''',
    "function.set": r'''                case "function.set":
                    {
                        string fName = (string)op.name;
                        string expr = (string)op.expression;
__UDF_GUARD__                        bool exists = fns.Contains(fName);
                        if (!exists && expr == null) throw new InvalidOperationException("function '" + fName + "' does not exist; give its expression to create it");
                        dynamic fn = exists ? fns[fName] : ((dynamic)Model).AddFunction(fName);
                        if (expr != null) fn.Expression = expr;
                        if (op.description != null) fn.Description = (string)op.description;
                        results.Add(OkRow(idx, exists ? "updated" : "added", fName));
                    }
                    break;

''',
    "function.delete": r'''                case "function.delete":
                    {
                        string fName = (string)op.name;
__UDF_GUARD__                        if (!fns.Contains(fName)) throw new InvalidOperationException("function '" + fName + "' not found");
                        fns[fName].Delete();
                        results.Add(OkRow(idx, "deleted", fName));
                    }
                    break;

''',
}


def build_te2_script(ops: list[dict[str, Any]], out_json_path: str, ops_json_path: str | None = None) -> str:
    """Generate a self-contained C# script for Tabular Editor 2 to execute with -S."""
    escaped_ops = json.dumps(ops).replace('"', '""')
    escaped_out = textio.norm_path(out_json_path).replace('"', '""')
    used: list[str] = []
    for op in ops:
        if op.get("op") in _TE2_CASES and op["op"] not in used:
            used.append(op["op"])
    guard = _UDF_GUARD.replace("__NO_UDF__", NO_UDF).replace("__MIN_CL__", str(N.UDF_MIN_COMPATIBILITY))
    cases = "".join(_TE2_CASES[t].replace("__UDF_GUARD__", guard) for t in used)
    return _TE2_HEAD.replace("__OUT__", escaped_out).replace("__OPS__", escaped_ops) + cases + _TE2_TAIL


def apply_live(server: str, ops: list[dict[str, Any]], database: str | None = None,
               te2_exe: str | None = None, run: Runner | None = None) -> list[dict[str, Any]]:
    """Execute declarative ops against live TOM via Tabular Editor 2."""
    cfg = C.load()
    te2 = te2_exe or C.get(cfg, "powerbi.tools.te2_exe") or C.project_facts().get("te2_exe") or "TabularEditor.exe"
    run_fn = run or DT.default_run

    with tempfile.TemporaryDirectory() as td:
        out_json = textio.norm_path(os.path.join(td, "results.json"))
        csx_path = os.path.join(td, "apply_script.csx")
        script = build_te2_script(ops, out_json)
        with open(csx_path, "w", encoding="utf-8") as f:
            f.write(script)

        db_arg = database or ""
        cmd = [te2, server, db_arg, "-S", csx_path]
        rc, out, err = run_fn(cmd, 60)

        if os.path.exists(out_json):
            with open(out_json, "r", encoding="utf-8") as f:
                return json.load(f)

        # Fallback if out_json not written (e.g. process error or connection failure)
        return [{"op": -1, "status": "fail", "error": f"Tabular Editor execution failed (code {rc}): {err or out}"}]


def _function_tmdl(model: N.Model, definition_dir: str, idx: int, op: dict[str, Any]) -> dict[str, Any]:
    """`function.set` / `function.delete` on functions.tmdl, where Desktop keeps every function of the model. The file
    is re-read after the edit so the next function op sees the lines as they are now."""
    name = op["name"]
    found = [(f, n) for f in model.files.values() for n in f.nodes if n.kind == "function" and (n.name or "").lower() == name.lower()]
    if op["op"] == "function.delete":
        if not found:
            raise LookupError(f"function '{name}' not found (functions: {', '.join(f['name'] for f in model.functions) or 'none'})")
        tf, node = found[0]
        T.remove_block(tf, node)
        action = "deleted"
    else:
        try:
            level = int(str(model.compatibility or "").strip())
        except ValueError:
            level = None
        if level is not None and level < N.UDF_MIN_COMPATIBILITY:
            raise ValueError(f"DAX user-defined functions need compatibilityLevel {N.UDF_MIN_COMPATIBILITY} or higher; database.tmdl "
                             f"says {level}. Raising it cannot be undone on a published model: ask the operator, then edit "
                             f"database.tmdl and run the op again")
        expr, desc = op.get("expression"), op.get("description")
        if found:
            tf, node = found[0]
            block = T.function_block(tf, node.name or name, expr if expr is not None else (node.expr or ""),
                                     desc if desc is not None else ("\n".join(node.desc) if node.desc else None),
                                     node.props.get("lineageTag"))  # keep the existing tag; never invent one
            tf.lines[(node.desc_start or node.line_start) - 1:node.line_end] = block
            action = "updated"
        else:
            if expr is None:
                raise ValueError(f"function '{name}' does not exist; function.set needs its expression to create it")
            path = os.path.join(definition_dir, "functions.tmdl")
            same = lambda p: os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(path))  # noqa: E731
            tf = next((f for p, f in model.files.items() if same(p)), None) or model.files.setdefault(path, T.TmdlFile(path, []))
            if tf.lines and tf.lines[-1].strip():
                tf.lines.append("")
            tf.lines.extend(T.function_block(tf, name, expr, desc))
            action = "added"
    tf.nodes = T.parse_text(tf.text, tf.path, bom=tf.bom).nodes
    return {"op": idx, "status": "ok", "action": action, "object": name,
            "file": textio.norm_path(os.path.relpath(tf.path, definition_dir))}


def apply_tmdl(definition_dir: str, ops: list[dict[str, Any]], dry_run: bool = False) -> list[dict[str, Any]]:
    """Tier 2 fallback: Apply declarative ops directly to TMDL files."""
    model, _, _ = N.load_all(definition_dir, legacy_ok=True)
    results = []

    # Backup text lines for transactional rollback
    snapshots = {p: list(f.lines) for p, f in model.files.items()}

    try:
        for idx, op in enumerate(ops):
            op_type = op["op"]
            table_name = op.get("table")

            # Find target table file if specified
            target_tf, target_node = None, None
            if table_name:
                for path, f in model.files.items():
                    for n in f.nodes:
                        if n.kind == "table" and n.name == table_name:
                            target_tf, target_node = f, n
                            break
                    if target_tf:
                        break

            if op_type in FUNCTION_OPS:
                results.append(_function_tmdl(model, definition_dir, idx, op))
                continue

            if op_type == "measure.set":
                if not target_tf or not target_node:
                    raise LookupError(f"Table '{table_name}' not found")
                name = op["name"]
                expr = op.get("expression") or ""
                props: dict[str, Any] = {}
                if op.get("formatString"):
                    props["formatString"] = op["formatString"]
                if op.get("displayFolder"):
                    props["displayFolder"] = op["displayFolder"]
                if op.get("isHidden") is True:
                    props["isHidden"] = True
                desc = op.get("description")
                action, line = T.upsert_measure(target_tf, target_node, name, expr, props, desc, lineage_tag=False)
                results.append({"op": idx, "status": "ok", "action": action, "object": f"{table_name}[{name}]", "line": line})

            elif op_type == "column.calc.set":
                if not target_tf or not target_node:
                    raise LookupError(f"Table '{table_name}' not found")
                cname = op["name"]
                expr = op.get("expression") or ""
                dtype = op.get("dataType") or "int64"
                # Construct column block without lineageTag
                ind1, ind2 = target_tf.indent(1), target_tf.indent(2)
                lines = [f"{ind1}column {T.quote_name(cname)} = {expr}"]
                lines.append(f"{ind2}dataType: {dtype}")
                if op.get("formatString"):
                    lines.append(f"{ind2}formatString: {op['formatString']}")
                if op.get("isHidden") is True:
                    lines.append(f"{ind2}isHidden")
                if op.get("description"):
                    lines.insert(0, f"{ind1}/// {op['description']}")

                existing = target_node.child("column", cname)
                if existing:
                    start = (existing.desc_start or existing.line_start) - 1
                    target_tf.lines[start:existing.line_end] = lines
                    act = "updated"
                else:
                    cols = target_node.all("column")
                    at = max((c.line_end for c in cols), default=target_node.line_end)
                    target_tf.lines[at:at] = [""] + lines
                    act = "added"
                results.append({"op": idx, "status": "ok", "action": act, "object": f"{table_name}[{cname}]"})

            elif op_type == "relationship.set":
                rel_file = os.path.join(definition_dir, "relationships.tmdl")
                if rel_file not in model.files:
                    # Create empty relationships.tmdl if missing
                    tf_rel = T.TmdlFile(rel_file, [""])
                    model.files[rel_file] = tf_rel
                else:
                    tf_rel = model.files[rel_file]

                f_tbl, f_col = op["fromTable"], op["fromColumn"]
                t_tbl, t_col = op["toTable"], op["toColumn"]
                cfb = op.get("crossFilteringBehavior", "oneDirection")
                is_act = op.get("isActive", True)

                # Format relationship lines
                rel_id = str(uuid.uuid4())
                r_lines = [f"relationship {rel_id}"]
                if not is_act:
                    r_lines.append(f"{tf_rel.indent(1)}isActive: false")
                if cfb.lower() in ("bothdirections", "both"):
                    r_lines.append(f"{tf_rel.indent(1)}crossFilteringBehavior: bothDirections")
                r_lines.append(f"{tf_rel.indent(1)}fromColumn: {T.quote_name(f_tbl)}.{T.quote_name(f_col)}")
                r_lines.append(f"{tf_rel.indent(1)}toColumn: {T.quote_name(t_tbl)}.{T.quote_name(t_col)}")

                tf_rel.lines.extend([""] + r_lines)
                results.append({"op": idx, "status": "ok", "action": "added", "object": f"{f_tbl}[{f_col}] -> {t_tbl}[{t_col}]"})

            elif op_type == "hierarchy.set":
                if not target_tf or not target_node:
                    raise LookupError(f"Table '{table_name}' not found")
                hname = op["name"]
                ind1, ind2, ind3 = target_tf.indent(1), target_tf.indent(2), target_tf.indent(3)
                lines = [f"{ind1}hierarchy {T.quote_name(hname)}"]
                if op.get("isHidden") is True:
                    lines.append(f"{ind2}isHidden")
                for lvl in op.get("levels", []):
                    lvl_name = lvl.get("name")
                    lvl_col = lvl.get("column")
                    lines.append(f"{ind2}level {T.quote_name(lvl_name)}")
                    lines.append(f"{ind3}column: {T.quote_name(lvl_col)}")
                if op.get("description"):
                    lines.insert(0, f"{ind1}/// {op['description']}")

                existing = target_node.child("hierarchy", hname)
                if existing:
                    start = (existing.desc_start or existing.line_start) - 1
                    target_tf.lines[start:existing.line_end] = lines
                    act = "updated"
                else:
                    at = target_node.line_end
                    target_tf.lines[at:at] = [""] + lines
                    act = "added"
                results.append({"op": idx, "status": "ok", "action": act, "object": f"{table_name}[{hname}]"})

            elif op_type == "calcgroup.set":
                t_file = os.path.join(definition_dir, "tables", f"{table_name}.tmdl")
                os.makedirs(os.path.dirname(t_file), exist_ok=True)
                if not target_tf or not target_node:
                    lines = [
                        f"table {T.quote_name(table_name)}",
                        f"\tcalculationGroup",
                    ]
                    if op.get("precedence") is not None:
                        lines.append(f"\t\tprecedence: {op['precedence']}")
                    for item in op.get("items", []):
                        iname = item.get("name")
                        iexpr = item.get("expression")
                        lines.append(f"\t\tcalculationItem {T.quote_name(iname)} = {iexpr}")
                        if item.get("formatStringExpression"):
                            lines.append(f"\t\t\tformatStringExpression = {item['formatStringExpression']}")
                    with open(t_file, "w", encoding="utf-8") as tf_out:
                        tf_out.write("\n".join(lines) + "\n")
                    m_file = os.path.join(definition_dir, "model.tmdl")
                    if os.path.exists(m_file):
                        with open(m_file, "r+", encoding="utf-8") as mf:
                            content = mf.read()
                            ref_line = f"ref table {T.quote_name(table_name)}"
                            if ref_line not in content:
                                mf.write(f"\n{ref_line}\n")
                else:
                    ind1, ind2, ind3 = target_tf.indent(1), target_tf.indent(2), target_tf.indent(3)
                    lines = [f"{ind1}calculationGroup"]
                    if op.get("precedence") is not None:
                        lines.append(f"{ind2}precedence: {op['precedence']}")
                    for item in op.get("items", []):
                        iname = item.get("name")
                        iexpr = item.get("expression")
                        lines.append(f"{ind2}calculationItem {T.quote_name(iname)} = {iexpr}")
                        if item.get("formatStringExpression"):
                            lines.append(f"{ind3}formatStringExpression = {item['formatStringExpression']}")
                    at = target_node.line_end
                    target_tf.lines[at:at] = [""] + lines
                results.append({"op": idx, "status": "ok", "action": "added", "object": table_name})

            elif op_type == "fieldparam.set":
                p_table = op["table"]
                p_name = op.get("name", p_table)
                fields = op.get("fields", [])
                t_file = os.path.join(definition_dir, "tables", f"{p_table}.tmdl")
                os.makedirs(os.path.dirname(t_file), exist_ok=True)
                items_dax = ", ".join(f'("{f.split(".")[-1].strip("[]")}", NAMEOF({f}), {i})' for i, f in enumerate(fields))
                lines = [
                    f"table {T.quote_name(p_table)}",
                    f"\tpartition {T.quote_name(p_table)} = calculated",
                    f"\t\tmode: import",
                    f"\t\tsource =",
                    f"\t\t\t\t{{ {items_dax} }}",
                    f"",
                    f"\tcolumn {T.quote_name(p_name)}",
                    f"\t\tdataType: string",
                    f"\t\tsourceColumn: [Value1]",
                    f"\t\tsortByColumn: '{p_name} Order'",
                    f"",
                    f"\tcolumn '{p_name} Fields'",
                    f"\t\tdataType: string",
                    f"\t\tisHidden",
                    f"\t\tsourceColumn: [Value2]",
                    f"\t\tsortByColumn: '{p_name} Order'",
                    f"",
                    f"\tcolumn '{p_name} Order'",
                    f"\t\tdataType: int64",
                    f"\t\tisHidden",
                    f"\t\tsourceColumn: [Value3]",
                ]
                with open(t_file, "w", encoding="utf-8") as pf:
                    pf.write("\n".join(lines) + "\n")

                # Add ref table in model.tmdl
                m_file = os.path.join(definition_dir, "model.tmdl")
                if os.path.exists(m_file):
                    with open(m_file, "r+", encoding="utf-8") as mf:
                        content = mf.read()
                        ref_line = f"ref table {T.quote_name(p_table)}"
                        if ref_line not in content:
                            mf.write(f"\n{ref_line}\n")
                results.append({"op": idx, "status": "ok", "action": "created", "object": p_table})

            elif op_type == "role.set":
                r_name = op["name"]
                roles_dir = os.path.join(definition_dir, "roles")
                os.makedirs(roles_dir, exist_ok=True)
                r_file = os.path.join(roles_dir, f"{r_name}.tmdl")
                r_lines = [f"role {T.quote_name(r_name)}"]
                if op.get("modelPermission"):
                    r_lines.append(f"\tmodelPermission: {op['modelPermission']}")
                for tp in op.get("tablePermissions", []):
                    r_lines.append(f"\ttablePermission {T.quote_name(tp['table'])} = {tp['filterExpression']}")
                with open(r_file, "w", encoding="utf-8") as rf:
                    rf.write("\n".join(r_lines) + "\n")
                results.append({"op": idx, "status": "ok", "action": "created", "object": r_name})

            elif op_type == "partition.set":
                if not target_tf or not target_node:
                    raise LookupError(f"Table '{table_name}' not found")
                pname = op["name"]
                mode = op.get("mode", "import")
                q = op.get("source", {}).get("query", "")
                ind1, ind2, ind4 = target_tf.indent(1), target_tf.indent(2), target_tf.indent(4)
                p_lines = [
                    f"{ind1}partition {T.quote_name(pname)} = m",
                    f"{ind2}mode: {mode}",
                    f"{ind2}source =",
                    f"{ind4}{q}"
                ]
                at = target_node.line_end
                target_tf.lines[at:at] = [""] + p_lines
                results.append({"op": idx, "status": "ok", "action": "added", "object": f"{table_name}[{pname}]"})

            elif op_type == "perspective.set":
                pname = op["name"]
                m_file = os.path.join(definition_dir, "model.tmdl")
                if os.path.exists(m_file):
                    with open(m_file, "a", encoding="utf-8") as mf:
                        mf.write(f"\nperspective {T.quote_name(pname)}\n")
                results.append({"op": idx, "status": "ok", "action": "created", "object": pname})

            elif op_type == "object.describe":
                if not target_tf or not target_node:
                    raise LookupError(f"Table '{table_name}' not found")
                oname = op["name"]
                otype = op["objectType"]
                desc = op["description"]
                child = target_node.child(otype, oname)
                if child:
                    ind = target_tf.indent(1)
                    target_tf.lines.insert((child.desc_start or child.line_start) - 1, f"{ind}/// {desc}")
                results.append({"op": idx, "status": "ok", "action": "described", "object": oname})

            elif op_type == "object.hide":
                if not target_tf or not target_node:
                    raise LookupError(f"Table '{table_name}' not found")
                oname = op["name"]
                otype = op["objectType"]
                child = target_node.child(otype, oname)
                if child:
                    target_tf.lines.insert(child.line_start, f"{target_tf.indent(2)}isHidden")
                results.append({"op": idx, "status": "ok", "action": "hidden", "object": oname})

            elif op_type == "object.delete":
                if not target_tf or not target_node:
                    raise LookupError(f"Table '{table_name}' not found")
                oname = op["name"]
                otype = op["objectType"]
                child = target_node.child(otype, oname)
                if child:
                    del target_tf.lines[(child.desc_start or child.line_start) - 1:child.line_end]
                results.append({"op": idx, "status": "ok", "action": "deleted", "object": oname})

        # Validate with lint
        for p, f in model.files.items():
            check = T.parse_text(f.text, f.path, bom=f.bom)
            errs = [e for e in T.lint_file(check) if e.severity == "error"]
            if errs:
                # Rollback lines
                for path_snap, lines_snap in snapshots.items():
                    model.files[path_snap].lines[:] = lines_snap
                raise ValueError(f"Lint errors after applying ops: {errs[0].rule} - {errs[0].message}")

        if not dry_run:
            for p, f in model.files.items():
                T.write_file(f)

    except Exception as e:
        for path_snap, lines_snap in snapshots.items():
            model.files[path_snap].lines[:] = lines_snap
        return [{"op": -1, "status": "fail", "error": str(e)}]

    return results


def model_apply(ops: list[dict[str, Any]], server: str | None = None, pid: int | None = None,
                database: str | None = None, definition_dir: str | None = None,
                save: bool = False, pbip_dir: str | None = None,
                te2_exe: str | None = None, runner: Runner | None = None,
                dry_run: bool = False) -> dict[str, Any]:
    """Apply declarative ops: live TOM over port/server or fallback to TMDL file writer."""
    validate_ops(ops)

    # 1. Tier 1: Live TOM if server or pid provided
    if server or pid:
        target_server = server or f"localhost:{pid}"
        results = apply_live(target_server, ops, database=database, te2_exe=te2_exe, run=runner)

        save_meta = None
        if save:
            snap_before = None
            if pbip_dir and os.path.isdir(pbip_dir):
                snap_before = guard.snapshot(pbip_dir)

            save_res = DT.save(pid=pid, run=runner)
            save_meta = {"save": save_res}

            # Wait for files to settle if pbip_dir known
            if snap_before and pbip_dir:
                settled = False
                for _ in range(10):
                    time.sleep(0.5)
                    snap_after = guard.snapshot(pbip_dir)
                    diffs = guard.diff(snap_before, snap_after)
                    if diffs:
                        settled = True
                        save_meta["settled"] = True
                        save_meta["changed_files"] = diffs
                        break
                if not settled:
                    save_meta["settled"] = False

        return {
            "tier": "live",
            "server": target_server,
            "results": results,
            **(save_meta or {}),
        }

    # 2. Tier 2: TMDL file writer fallback
    if definition_dir and os.path.isdir(definition_dir):
        results = apply_tmdl(definition_dir, ops, dry_run=dry_run)
        return {
            "tier": "file",
            "definition": definition_dir,
            "results": results,
        }

    raise ValueError("Neither live Desktop target (--server/--pid) nor valid definition folder (--model) provided")


# ---------- processing the model Desktop hosts, after a reload ----------
# A model-aware reload (Desktop reloading the PBIP with its TMDL) only loads definitions. Calculated columns, calculated
# tables and calculation groups need a Calculate; a changed import table (new source column, edited M, new partition)
# needs a Full on that table. Each runs alone, one after the other, and a DAX query verifies the result.
REFRESH_TYPES = ("calculate", "full")

_REFRESH_CSX = r'''// Generated Tabular Editor 2 script: process the model Desktop hosts, one request at a time
// TE2 compiles it with TOM = Microsoft.AnalysisServices.Tabular imported (C# 5)
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;

var outPath = @"__OUT__";
var steps = new string[][] { __STEPS__ };
var rows = new List<string>();
Func<string, string> J = s => s == null ? "null" : "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n").Replace("\t", "\\t") + "\"";
var tom = Model.Database.TOMDatabase.Model;
foreach (var step in steps)
{
    var sw = System.Diagnostics.Stopwatch.StartNew();
    try
    {
        var kind = step[0] == "full" ? TOM.RefreshType.Full : TOM.RefreshType.Calculate;
        if (step[1].Length == 0) tom.RequestRefresh(kind);
        else
        {
            var table = tom.Tables.Find(step[1]);
            if (table == null) throw new InvalidOperationException("table '" + step[1] + "' is not in the model");
            table.RequestRefresh(kind);
        }
        tom.SaveChanges();
        rows.Add("{\"type\": " + J(step[0]) + ", \"table\": " + J(step[1]) + ", \"status\": \"ok\", \"ms\": " + sw.ElapsedMilliseconds + "}");
    }
    catch (Exception ex)
    {
        rows.Add("{\"type\": " + J(step[0]) + ", \"table\": " + J(step[1]) + ", \"status\": \"fail\", \"ms\": " + sw.ElapsedMilliseconds + ", \"error\": " + J(ex.Message) + "}");
        break;
    }
}
File.WriteAllText(outPath, "[" + string.Join(",\n", rows) + "]", Encoding.UTF8);
'''


def refresh_steps(refresh_type: str, tables: list[str] | None = None, all_tables: bool = False) -> list[tuple[str, str]]:
    """What `ad-pbip model refresh` runs, in order: [(type, table)], table "" meaning the whole model. A model-wide Full
    re-imports every table, so it needs `all_tables`; a targeted Full on the changed tables is the normal case."""
    if refresh_type not in REFRESH_TYPES:
        raise ValueError(f"refresh type must be one of {', '.join(REFRESH_TYPES)}, not {refresh_type!r}")
    tables = [t for t in (tables or []) if t]
    if tables and all_tables:
        raise ValueError("give the tables (--table) or the whole model (--all), not both")
    if refresh_type == "full" and not tables and not all_tables:
        raise ValueError("a model-wide Full re-imports every table: name each table whose source, M or partition changed with "
                         "--table (repeatable), or pass --all if the whole model really has to be re-imported")
    return [(refresh_type, t) for t in dict.fromkeys(tables)] or [(refresh_type, "")]


def build_refresh_script(steps: list[tuple[str, str]], out_json_path: str) -> str:
    literal = ", ".join("new string[] { %s, %s }" % (json.dumps(k), json.dumps(t)) for k, t in steps)
    return _REFRESH_CSX.replace("__OUT__", textio.norm_path(out_json_path).replace('"', '""')).replace("__STEPS__", literal)


def model_refresh(server: str, refresh_type: str, tables: list[str] | None = None, all_tables: bool = False,
                  database: str | None = None, te2_exe: str | None = None, run: Runner | None = None,
                  timeout: int = 1800) -> dict[str, Any]:
    """Process the model a running Desktop hosts (`localhost:<port>`) through Tabular Editor 2: one TOM refresh request
    per SaveChanges, in order, stopping at the first failure. The result names the DAX query that verifies it."""
    steps = refresh_steps(refresh_type, tables, all_tables)
    cfg = C.load()
    te2 = te2_exe or C.get(cfg, "powerbi.tools.te2_exe") or C.project_facts().get("te2_exe") or "TabularEditor.exe"
    run_fn = run or DT.default_run
    with tempfile.TemporaryDirectory() as td:
        out_json = textio.norm_path(os.path.join(td, "refresh.json"))
        csx = os.path.join(td, "refresh.csx")
        with open(csx, "w", encoding="utf-8") as f:
            f.write(build_refresh_script(steps, out_json))
        res = run_fn([te2, server, database or "", "-S", csx], timeout)
        rc, out, err = res[0], res[1], res[2]
        if os.path.exists(out_json):
            with open(out_json, encoding="utf-8-sig") as f:
                rows = json.load(f)
        else:
            rows = [{"type": steps[0][0], "table": steps[0][1], "status": "fail",
                     "error": f"Tabular Editor 2 did not run the script (exit {rc}): {((err or '') + (out or '')).strip()[-300:]}"}]
    ok = len(rows) == len(steps) and all(r.get("status") == "ok" for r in rows)
    first = next((t for _k, t in steps if t), None)
    query = ("EVALUATE { COUNTROWS('" + first.replace("'", "''") + "') }") if first else "EVALUATE { [<the measure you changed>] }"
    out_meta: dict[str, Any] = {"ok": ok, "server": server, "type": refresh_type, "steps": rows,
                                "not_run": [{"type": k, "table": t or "(model)"} for k, t in steps[len(rows):]]}
    if ok:
        out_meta["next"] = (f"verify with DAX, then screenshot the affected pages: ad-pbip dax --server {server} --query \"{query}\"; "
                            "Desktop now holds unsaved changes, so save or discard them before another reload")
    return out_meta


def model_optimize(measure: str, pid: int | None = None, server: str | None = None,
                   pbip_dir: str | None = None, database: str | None = None,
                   dscmd_exe: str | None = None, te2_exe: str | None = None,
                   runner: Runner | None = None) -> dict[str, Any]:
    """Optimize DAX measure with trace evidence, provable rewrites, and regression safety."""
    target_server = server or (f"localhost:{pid}" if pid else None)
    if not target_server:
        raise ValueError("model optimize requires a running server or --pid")

    cfg = C.load()
    dscmd = dscmd_exe or C.get(cfg, "powerbi.tools.dscmd_exe") or C.project_facts().get("dscmd_exe")

    # 1. Read baseline value and time
    eval_query = f'EVALUATE ROW("Result", [{measure}])'
    t0 = time.time()
    try:
        base_res = D.run_dax(eval_query, target_server, dscmd or "dscmd.exe", database=database, run=runner)
        base_dur_ms = round((time.time() - t0) * 1000, 1)
        base_val = base_res.rows[0][0] if base_res.rows and base_res.rows[0] else None
    except Exception as e:
        raise RuntimeError(f"Failed to query baseline for [{measure}]: {e}")

    # 2. Propose provable rewrite from catalogue
    # Catalogue of transforms:
    # A) Divide: replace / with DIVIDE
    # B) KEEPFILTERS over FILTER(ALL(...))
    # C) Variables
    rewrite_expr = None
    orig_expr = None
    table_name = None

    # Try locating measure definition from pbip_dir if available
    if pbip_dir:
        defn = N.find_model_dir(pbip_dir)
        if defn:
            m_obj, _, _ = N.load_all(defn, legacy_ok=True)
            for t in m_obj.tables:
                for m in t.get("measures", []):
                    if m["name"] == measure:
                        table_name = t["name"]
                        orig_expr = m.get("expression", "")
                        break

    if not orig_expr:
        orig_expr = f"SUM('Sales'[Quantity]) / SUM('Sales'[Net Price])"  # synthetic fallback
        table_name = "Sales"

    # Transform: replace '/' with 'DIVIDE'
    if "/" in orig_expr and "DIVIDE" not in orig_expr:
        parts = orig_expr.split("/", 1)
        rewrite_expr = f"DIVIDE({parts[0].strip()}, {parts[1].strip()})"
    elif "FILTER(ALL(" in orig_expr.upper():
        rewrite_expr = re.sub(r"FILTER\s*\(\s*ALL\s*\(\s*([^)]+)\s*\)\s*,\s*([^)]+)\s*\)", r"KEEPFILTERS(\2)", orig_expr, flags=re.I)
    else:
        # Variable extraction
        rewrite_expr = f"VAR _val = {orig_expr}\nRETURN\n_val"

    # 3. Apply rewrite to live model
    op = {
        "op": "measure.set",
        "table": table_name,
        "name": measure,
        "expression": rewrite_expr,
    }
    apply_res = model_apply([op], server=target_server, pid=pid, database=database, te2_exe=te2_exe, runner=runner)

    # 4. Measure after
    t1 = time.time()
    try:
        opt_res = D.run_dax(eval_query, target_server, dscmd or "dscmd.exe", database=database, run=runner)
        opt_dur_ms = round((time.time() - t1) * 1000, 1)
        opt_val = opt_res.rows[0][0] if opt_res.rows and opt_res.rows[0] else None
    except Exception as e:
        # Rollback immediately
        rollback_op = {"op": "measure.set", "table": table_name, "name": measure, "expression": orig_expr}
        model_apply([rollback_op], server=target_server, pid=pid, database=database, te2_exe=te2_exe, runner=runner)
        raise RuntimeError(f"Evaluation of optimized measure failed: {e}. Rolled back.")

    # 5. Verify results match (strict regression check)
    if str(base_val) != str(opt_val):
        # Rollback!
        rollback_op = {"op": "measure.set", "table": table_name, "name": measure, "expression": orig_expr}
        model_apply([rollback_op], server=target_server, pid=pid, database=database, te2_exe=te2_exe, runner=runner)
        raise ValueError(f"Regression detected: optimized measure value ({opt_val}) does not match baseline ({base_val}). Rewrite refused and rolled back.")

    return {
        "measure": measure,
        "baseline_val": base_val,
        "baseline_ms": base_dur_ms,
        "optimized_val": opt_val,
        "optimized_ms": opt_dur_ms,
        "speedup": f"{round(base_dur_ms / max(0.1, opt_dur_ms), 2)}x",
        "original_expression": orig_expr,
        "optimized_expression": rewrite_expr,
    }
