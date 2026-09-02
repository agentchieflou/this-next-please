// TE2 C# script: refresh via TOM. Scope from env TE_REFRESH_SCOPE = full | table:<T> | partition:<T>/<P>
using Microsoft.AnalysisServices.Tabular;
var scope = System.Environment.GetEnvironmentVariable("TE_REFRESH_SCOPE") ?? "full";
var tom = Model.Database.TOMDatabase.Model;
if (scope == "full") tom.RequestRefresh(RefreshType.Full);
else if (scope.StartsWith("table:")) tom.Tables[scope.Substring(6)].RequestRefresh(RefreshType.Full);
else if (scope.StartsWith("partition:")) {
    var parts = scope.Substring(10).Split('/');
    tom.Tables[parts[0]].Partitions[parts[1]].RequestRefresh(RefreshType.Full);
}
else throw new System.Exception("bad TE_REFRESH_SCOPE: " + scope);
tom.SaveChanges(new SaveOptions { MaxParallelism = 4 });   // MUST follow RequestRefresh
Info("refresh submitted: " + scope);
