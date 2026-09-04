// Tabular Editor 2 Advanced Script for Analysis Services Trace
// Connects to local or remote Analysis Services and streams trace events to file and/or named pipe.
using System;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using Microsoft.AnalysisServices;
using Microsoft.AnalysisServices.Tabular;

var secondsStr = Environment.GetEnvironmentVariable("TE_TRACE_SECONDS") ?? "60";
int seconds = 60;
int.TryParse(secondsStr, out seconds);
if (seconds <= 0) seconds = 60;

var outFile = Environment.GetEnvironmentVariable("TE_TRACE_OUT");
var pipeName = Environment.GetEnvironmentVariable("TE_TRACE_PIPE");

NamedPipeClientStream pipe = null;
StreamWriter pipeWriter = null;
if (!string.IsNullOrEmpty(pipeName))
{
    try
    {
        var pName = pipeName.StartsWith(@"\\.\pipe\") ? pipeName.Substring(9) : pipeName;
        pipe = new NamedPipeClientStream(".", pName, PipeDirection.Out);
        pipe.Connect(3000);
        pipeWriter = new StreamWriter(pipe, Encoding.UTF8) { AutoFlush = true };
    }
    catch (Exception)
    {
        // Pipe optional; file output continues
    }
}

StreamWriter fileWriter = null;
if (!string.IsNullOrEmpty(outFile))
{
    try
    {
        var dir = Path.GetDirectoryName(outFile);
        if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir)) Directory.CreateDirectory(dir);
        fileWriter = new StreamWriter(outFile, true, Encoding.UTF8) { AutoFlush = true };
    }
    catch (Exception)
    {
    }
}

Action<string> emit = (line) =>
{
    if (fileWriter != null) { lock (fileWriter) { fileWriter.WriteLine(line); } }
    if (pipeWriter != null) { lock (pipeWriter) { pipeWriter.WriteLine(line); } }
};

var server = Model.Database.Server;
var traceName = "AgentDataTrace_" + Guid.NewGuid().ToString("N");
var trace = server.Traces.Add(traceName);

trace.Events.Add(TraceEventClass.QueryBegin);
trace.Events.Add(TraceEventClass.QueryEnd);
trace.Events.Add(TraceEventClass.DirectQueryEnd);
trace.Events.Add(TraceEventClass.VertiPaqSEQueryEnd);

trace.OnEvent += (sender, e) =>
{
    try
    {
        var ev = e.EventClass.ToString();
        var start = e.StartTime.ToString("o");
        var dur = e.Duration;
        var rawText = e.TextData ?? "";
        var text = rawText.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "").Replace("\n", "\\n");
        var db = (e.DatabaseName ?? "").Replace("\"", "\\\"");
        var sess = e.SessionID ?? "";
        var json = string.Format("{{\"event\":\"{0}\",\"start\":\"{1}\",\"duration_ms\":{2},\"text\":\"{3}\",\"database\":\"{4}\",\"session\":\"{5}\"}}",
            ev, start, dur, text, db, sess);
        emit(json);
    }
    catch (Exception)
    {
    }
};

try
{
    trace.Start();
    emit("{\"event\":\"TraceStarted\",\"start\":\"" + DateTime.UtcNow.ToString("o") + "\",\"duration_ms\":0,\"text\":\"Trace started\",\"database\":\"" + Model.Database.Name + "\",\"session\":\"\"}");
    Thread.Sleep(seconds * 1000);
}
finally
{
    try { trace.Stop(); } catch (Exception) {}
    try { trace.Drop(); } catch (Exception) {}
    if (pipeWriter != null) { try { pipeWriter.Dispose(); } catch (Exception) {} }
    if (pipe != null) { try { pipe.Dispose(); } catch (Exception) {} }
    if (fileWriter != null) { try { fileWriter.Dispose(); } catch (Exception) {} }
}
