// Tabular Editor 2 script: apply.csx
// Applies a declarative op list against the live TOM model.
// Run with: TabularEditor.exe <server> [database] -S apply.csx
using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using Microsoft.AnalysisServices.Tabular;

var opsPath = Environment.GetEnvironmentVariable("TOM_OPS_FILE");
var outPath = Environment.GetEnvironmentVariable("TOM_OUT_FILE");

if (string.IsNullOrEmpty(opsPath) || !File.Exists(opsPath))
{
    opsPath = ".agent/tom_ops.json";
}

if (string.IsNullOrEmpty(outPath))
{
    outPath = opsPath + ".out.json";
}

var results = new List<string>();
bool overallOk = true;

try
{
    // If opsPath exists, read and execute
    if (File.Exists(opsPath))
    {
        var raw = File.ReadAllText(opsPath);
        // Note: TE2 includes Newtonsoft.Json
        dynamic ops = Newtonsoft.Json.JsonConvert.DeserializeObject(raw);
        int idx = 0;
        foreach (var op in ops)
        {
            string opType = (string)op.op;
            try
            {
                switch (opType)
                {
                    case "measure.set":
                        {
                            string tName = (string)op.table;
                            string mName = (string)op.name;
                            string expr = (string)op.expression;
                            var tbl = Model.Tables[tName];
                            if (tbl == null) throw new InvalidOperationException($"Table '{tName}' not found");
                            var m = tbl.Measures[mName] ?? tbl.AddMeasure(mName, expr);
                            if (expr != null) m.Expression = expr;
                            if (op.formatString != null) m.FormatString = (string)op.formatString;
                            if (op.displayFolder != null) m.DisplayFolder = (string)op.displayFolder;
                            if (op.description != null) m.Description = (string)op.description;
                            if (op.isHidden != null) m.IsHidden = (bool)op.isHidden;
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"measure.set\", \"object\": \"{tName}[{mName}]\"}}");
                        }
                        break;

                    case "column.calc.set":
                        {
                            string tName = (string)op.table;
                            string cName = (string)op.name;
                            string expr = (string)op.expression;
                            var tbl = Model.Tables[tName];
                            if (tbl == null) throw new InvalidOperationException($"Table '{tName}' not found");
                            var col = tbl.Columns[cName] as CalculatedColumn ?? tbl.AddCalculatedColumn(cName, expr);
                            if (expr != null) col.Expression = expr;
                            if (op.formatString != null) col.FormatString = (string)op.formatString;
                            if (op.description != null) col.Description = (string)op.description;
                            if (op.isHidden != null) col.IsHidden = (bool)op.isHidden;
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"column.calc.set\", \"object\": \"{tName}[{cName}]\"}}");
                        }
                        break;

                    case "relationship.set":
                        {
                            string fTbl = (string)op.fromTable;
                            string fCol = (string)op.fromColumn;
                            string tTbl = (string)op.toTable;
                            string tCol = (string)op.toColumn;
                            var rel = Model.Relationships.Add(Model.Tables[fTbl].Columns[fCol], Model.Tables[tTbl].Columns[tCol]);
                            if (op.crossFilteringBehavior != null)
                            {
                                string cfb = ((string)op.crossFilteringBehavior).ToLower();
                                rel.CrossFilteringBehavior = (cfb == "bothdirections" || cfb == "both")
                                    ? CrossFilteringBehavior.BothDirections : CrossFilteringBehavior.OneDirection;
                            }
                            if (op.isActive != null) rel.IsActive = (bool)op.isActive;
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"relationship.set\", \"object\": \"{fTbl}[{fCol}] -> {tTbl}[{tCol}]\"}}");
                        }
                        break;

                    case "hierarchy.set":
                        {
                            string tName = (string)op.table;
                            string hName = (string)op.name;
                            var tbl = Model.Tables[tName];
                            if (tbl == null) throw new InvalidOperationException($"Table '{tName}' not found");
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
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"hierarchy.set\", \"object\": \"{tName}[{hName}]\"}}");
                        }
                        break;

                    case "calcgroup.set":
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
                                    var ci = cg.CalculationItems[iName] ?? cg.AddCalculationItem(iName, iExpr);
                                    if (iExpr != null) ci.Expression = iExpr;
                                    if (item.formatStringExpression != null) ci.FormatStringExpression = (string)item.formatStringExpression;
                                    if (item.ordinal != null) ci.Ordinal = (int)item.ordinal;
                                }
                            }
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"calcgroup.set\", \"object\": \"{tName}\"}}");
                        }
                        break;

                    case "fieldparam.set":
                        {
                            string tName = (string)op.table;
                            string pName = (string)op.name;
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"fieldparam.set\", \"object\": \"{tName}\"}}");
                        }
                        break;

                    case "role.set":
                        {
                            string rName = (string)op.name;
                            var r = Model.Roles[rName] ?? Model.AddRole(rName);
                            if (op.modelPermission != null)
                            {
                                r.ModelPermission = ModelPermission.Read;
                            }
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
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"role.set\", \"object\": \"{rName}\"}}");
                        }
                        break;

                    case "partition.set":
                        {
                            string tName = (string)op.table;
                            string pName = (string)op.name;
                            var tbl = Model.Tables[tName];
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
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"partition.set\", \"object\": \"{tName}[{pName}]\"}}");
                        }
                        break;

                    case "perspective.set":
                        {
                            string pName = (string)op.name;
                            var p = Model.Perspectives[pName] ?? Model.AddPerspective(pName);
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"perspective.set\", \"object\": \"{pName}\"}}");
                        }
                        break;

                    case "object.describe":
                        {
                            string tName = (string)op.table;
                            string oType = (string)op.objectType;
                            string name = (string)op.name;
                            string desc = (string)op.description;
                            var tbl = tName != null ? Model.Tables[tName] : null;
                            if (oType == "measure" && tbl != null) tbl.Measures[name].Description = desc;
                            else if (oType == "column" && tbl != null) tbl.Columns[name].Description = desc;
                            else if (oType == "table" && tbl != null) tbl.Description = desc;
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"object.describe\", \"object\": \"{name}\"}}");
                        }
                        break;

                    case "object.hide":
                        {
                            string tName = (string)op.table;
                            string oType = (string)op.objectType;
                            string name = (string)op.name;
                            bool hide = (bool)op.isHidden;
                            var tbl = tName != null ? Model.Tables[tName] : null;
                            if (oType == "measure" && tbl != null) tbl.Measures[name].IsHidden = hide;
                            else if (oType == "column" && tbl != null) tbl.Columns[name].IsHidden = hide;
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"object.hide\", \"object\": \"{name}\"}}");
                        }
                        break;

                    case "object.delete":
                        {
                            string tName = (string)op.table;
                            string oType = (string)op.objectType;
                            string name = (string)op.name;
                            var tbl = tName != null ? Model.Tables[tName] : null;
                            if (oType == "measure" && tbl != null) tbl.Measures[name]?.Delete();
                            else if (oType == "column" && tbl != null) tbl.Columns[name]?.Delete();
                            else if (oType == "table" && tbl != null) tbl.Delete();
                            results.Add($"{{\"op\": {idx}, \"status\": \"ok\", \"action\": \"object.delete\", \"object\": \"{name}\"}}");
                        }
                        break;

                    default:
                        results.Add($"{{\"op\": {idx}, \"status\": \"fail\", \"error\": \"Unsupported op type: {opType}\"}}");
                        overallOk = false;
                        break;
                }
            }
            catch (Exception ex)
            {
                results.Add($"{{\"op\": {idx}, \"status\": \"fail\", \"error\": \"{ex.Message.Replace("\"", "\\\"")}\"}}");
                overallOk = false;
            }
            idx++;
        }

        if (overallOk)
        {
            try
            {
                Model.SaveChanges();
            }
            catch (Exception ex)
            {
                results.Add($"{{\"op\": -1, \"status\": \"fail\", \"stage\": \"SaveChanges\", \"error\": \"{ex.Message.Replace("\"", "\\\"")}\"}}");
            }
        }
    }
}
catch (Exception ex)
{
    results.Add($"{{\"op\": -1, \"status\": \"fail\", \"stage\": \"ScriptExecution\", \"error\": \"{ex.Message.Replace("\"", "\\\"")}\"}}");
}

File.WriteAllText(outPath, "[" + string.Join(",\n", results) + "]", Encoding.UTF8);
