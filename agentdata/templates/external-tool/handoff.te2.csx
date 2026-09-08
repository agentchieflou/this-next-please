// Hand off to agentdata -- Tabular Editor 2 custom action (transport te2:local, issue #115).
//
// TE2 runs fine from C:\Enforce; the only thing it cannot do on a locked-down laptop is appear in
// Power BI Desktop's External Tools ribbon, and it does not need to. Its own connect dialog offers
// *Local instance*, which lists the running Desktop windows by file name -- so the human's "this
// one" moves into TE2 with no privileged write anywhere. After connecting,
// Model.Database.ServerName is localhost:<port> and Model.Database.Name is the database GUID: the
// ribbon's %server% and %database%, verbatim, and the only transport that carries the database
// name with no DMV round-trip.
//
// This file ships two bodies. `external_tool.render_te2_script(mode=...)` selects one and
// `merge_custom_action()` stores it as the Execute text of one entry in
// %LOCALAPPDATA%\TabularEditor\CustomActions.json. `{{launcher}}` is substituted at render time.
//
//   process   the default: launch the approved Python so handoff() stays the single writer and
//             project resolution is shared with every other transport.
//   file      the fallback (config te2_action: file), for a site where starting a process from a
//             script is refused: write .agent/desktop.json here, with System.IO.

// ---8<--- body: process
// Launch the enterprise-approved Python with the same verb the ribbon would use. handoff() is the
// single writer: it finds the project from the open file and falls back to the per-user pointer,
// so this action never has to know where the project is.
var arguments = "-m agentdata pbip handoff --server \"" + Model.Database.ServerName + "\" --database \"" + Model.Database.Name + "\"";
var psi = new System.Diagnostics.ProcessStartInfo("{{launcher}}", arguments);
psi.UseShellExecute = false;      // required before the redirects below, and it keeps cmd out of the way
psi.CreateNoWindow = true;        // no console flashing over TE2
psi.RedirectStandardOutput = true;
psi.RedirectStandardError = true;
var proc = System.Diagnostics.Process.Start(psi);
var stdout = proc.StandardOutput.ReadToEnd().Trim();
var stderr = proc.StandardError.ReadToEnd().Trim();
proc.WaitForExit();
if (proc.ExitCode == 0)
    Info("agentdata: " + (stdout.Length > 0 ? stdout : "handed off " + Model.Database.ServerName));
else
    Info("agentdata handoff failed (exit " + proc.ExitCode + "): " + (stderr.Length > 0 ? stderr : stdout));
// ---8<--- end

// ---8<--- body: file
// Fallback body: write the payload here, with System.IO, for a site where a script may not start a
// process. It is second choice because it duplicates what handoff() does, so keep it in step.
//
// Where to write: the per-user pointer ad-setup keeps at %LOCALAPPDATA%\agentdata\pbi-handoff.json.
// That pointer exists precisely because the project is the one thing that changes over time, and a
// per-user file never needs a ticket.
Func<string, string, string> jsonString = (raw, key) => {
    var at = raw.IndexOf("\"" + key + "\"");
    if (at < 0) return null;
    var colon = raw.IndexOf(':', at);
    if (colon < 0) return null;
    var open = raw.IndexOf('"', colon + 1);
    if (open < 0) return null;
    var sb = new System.Text.StringBuilder();
    for (var i = open + 1; i < raw.Length; i++) {
        if (raw[i] == '\\' && i + 1 < raw.Length) { i++; sb.Append(raw[i]); continue; }
        if (raw[i] == '"') break;
        sb.Append(raw[i]);
    }
    return sb.ToString();
};
Func<string, string> esc = s => s == null ? null : s.Replace("\\", "\\\\").Replace("\"", "\\\"");

var local = System.Environment.GetFolderPath(System.Environment.SpecialFolder.LocalApplicationData);
var pointer = System.IO.Path.Combine(local, "agentdata", "pbi-handoff.json");
var project = System.IO.File.Exists(pointer) ? jsonString(System.IO.File.ReadAllText(pointer), "project") : null;
if (string.IsNullOrEmpty(project) || !System.IO.Directory.Exists(project)) {
    Info("agentdata: this model belongs to no known project. Run  ad-setup --project <folder>  once, then click again.");
    return;
}

var server = Model.Database.ServerName;
var database = Model.Database.Name;
var port = server.Substring(server.LastIndexOf(':') + 1).Trim();

// Every open Desktop document runs its own msmdsrv.exe; its workspace folder holds
// Data\msmdsrv.port.txt (UTF-16) with the port. That is the rule desktop.py already uses, so this
// body and `ad-pbip handoff` agree about which workspace a localhost:<port> is.
string workspace = null;
var roots = System.IO.Path.Combine(local, "Microsoft", "Power BI Desktop", "AnalysisServicesWorkspaces");
if (System.IO.Directory.Exists(roots)) {
    foreach (var dir in System.IO.Directory.GetDirectories(roots)) {
        var portFile = System.IO.Path.Combine(dir, "Data", "msmdsrv.port.txt");
        if (!System.IO.File.Exists(portFile)) continue;
        var text = System.IO.File.ReadAllText(portFile, System.Text.Encoding.Unicode).Trim().Trim('\0');
        if (text == port) { workspace = System.IO.Path.Combine(dir, "Data"); break; }
    }
}

// msmdsrv writes the port, never its own pid, and the parent PBIDesktop pid needs the process
// table. With one Desktop open that is unambiguous; with several, a null pid beats a wrong one --
// read_handoff() only checks liveness when a pid is there, and the timestamp still ages the file.
var desktops = System.Diagnostics.Process.GetProcessesByName("PBIDesktop");
var pid = desktops.Length == 1 ? desktops[0].Id.ToString() : "null";

var agentDir = System.IO.Path.Combine(project, ".agent");
System.IO.Directory.CreateDirectory(agentDir);
var payload = "{\n"
    + "  \"server\": \"" + esc(server) + "\",\n"
    + "  \"database\": \"" + esc(database) + "\",\n"
    + "  \"pid\": " + pid + ",\n"
    + "  \"file\": null,\n"
    + "  \"workspace_dir\": " + (workspace == null ? "null" : "\"" + esc(workspace) + "\"") + ",\n"
    + "  \"transport\": \"te2:local\",\n"
    + "  \"database_source\": \"te2\",\n"
    + "  \"handed_off_at\": \"" + System.DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.ffffff") + "+00:00\"\n"
    + "}\n";
var target = System.IO.Path.Combine(agentDir, "desktop.json");
System.IO.File.WriteAllText(target, payload, new System.Text.UTF8Encoding(false));
Info("agentdata: handed off " + server + " to " + target);
// ---8<--- end
