#:property PublishAot=false
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

string debugger = Path.GetFullPath(args[0]);
string program = Path.GetFullPath(args[1]);
string source = Path.GetFullPath(args[2]);
string prefix = Path.GetFullPath(args[3]);
var result = new JsonObject { ["success"] = false, ["program"] = program, ["source"] = source };
var checks = new JsonArray(); result["checks"] = checks;
await using var d = new Dap(debugger, prefix + ".dap.jsonl");
try
{
    await d.Request("initialize", new { adapterID="coreclr", clientID="fileapp-research", linesStartAt1=true, columnsStartAt1=true, pathFormat="path", supportsRunInTerminalRequest=false });
    int launch = await d.Send("launch", new { program, cwd=Path.GetDirectoryName(source), stopAtEntry=false, justMyCode=true, console="internalConsole", env=new Dictionary<string,string?> { ["DOTNET_ROOT"]=Environment.GetEnvironmentVariable("DOTNET_ROOT") } });
    await d.Event("initialized");
    await d.Request("setBreakpoints", new { source = new { path=source }, breakpoints=new[] { new { line=2 } } });
    await d.Request("configurationDone");
    await d.Response(launch);
    var stopped = await d.Event("stopped");
    Assert(stopped["reason"]!.GetValue<string>()=="breakpoint", "Expected breakpoint");
    int thread = stopped["threadId"]!.GetValue<int>();
    var frames = (await d.Request("stackTrace", new { threadId=thread }))["stackFrames"]!.AsArray();
    Assert(frames[0]!["line"]!.GetValue<int>()==2, "Expected source line 2");
    checks.Add("breakpoint at app.cs:2");
    int frame = frames[0]!["id"]!.GetValue<int>();
    var scopes = (await d.Request("scopes", new { frameId=frame }))["scopes"]!.AsArray();
    var variables = new JsonArray();
    foreach(var scope in scopes) { var list=(await d.Request("variables",new { variablesReference=scope!["variablesReference"]!.GetValue<int>() }))["variables"]!.AsArray(); foreach(var variable in list) variables.Add(variable!.DeepClone()); }
    Assert(variables.Any(v=>v!["name"]!.GetValue<string>()=="answer"&&v["value"]!.GetValue<string>()=="40"),"Expected answer=40");
    result["locals"] = variables; checks.Add("locals: answer=40");
    var value = await d.Request("evaluate", new { frameId=frame, expression="answer + 2", context="watch" });
    Assert(value["result"]!.GetValue<string>()=="42", "Expected evaluate=42"); checks.Add("evaluate: answer + 2=42");
    await d.Request("next", new { threadId=thread }); stopped=await d.Event("stopped");
    Assert(stopped["reason"]!.GetValue<string>()=="step", "Expected step stop");
    frames=(await d.Request("stackTrace",new {threadId=stopped["threadId"]!.GetValue<int>()}))["stackFrames"]!.AsArray();
    Assert(frames[0]!["line"]!.GetValue<int>()==3, "Expected step to line 3"); checks.Add("step over to app.cs:3");
    value=await d.Request("evaluate", new {frameId=frames[0]!["id"]!.GetValue<int>(),expression="answer",context="watch"});
    Assert(value["result"]!.GetValue<string>()=="42", "Expected answer after step=42"); checks.Add("locals after step: answer=42");
    await d.Request("continue", new {threadId=thread});
    var exited=await d.Event("exited"); Assert(exited["exitCode"]!.GetValue<int>()==0,"Expected clean exit");
    await d.Event("terminated"); Assert(d.Output.Contains("ANSWER=42"),"Expected output ANSWER=42"); checks.Add("stdout ANSWER=42; exit 0");
    result["success"]=true;
}
catch(Exception e) { result["error"]=e.ToString(); }
finally { result["output"]=d.Output; await d.Close(); result["stderr"]=await d.Stderr; await File.WriteAllTextAsync(prefix+".result.json",result.ToJsonString(new JsonSerializerOptions{WriteIndented=true})); }
Console.WriteLine(result.ToJsonString(new JsonSerializerOptions{WriteIndented=true}));
return result["success"]!.GetValue<bool>()?0:1;

static void Assert(bool condition,string message) { if(!condition) throw new Exception(message); }

sealed class Dap : IAsyncDisposable
{
    readonly Process proc;
    readonly Stream input;
    readonly Stream output;
    readonly StreamWriter log;
    readonly List<JsonNode> pending=[];
    int seq;
    public string Output {get;private set;}="";
    public Task<string> Stderr {get;}
    public Dap(string debugger,string path) { var psi=new ProcessStartInfo(debugger){UseShellExecute=false,RedirectStandardInput=true,RedirectStandardOutput=true,RedirectStandardError=true}; psi.ArgumentList.Add("--interpreter=vscode"); proc=Process.Start(psi)!; input=proc.StandardInput.BaseStream; output=proc.StandardOutput.BaseStream; log=new StreamWriter(path){AutoFlush=true}; Stderr=proc.StandardError.ReadToEndAsync(); }
    public async Task<int> Send(string command,object? arguments=null) { int id=++seq; var message=new {seq=id,type="request",command,arguments}; string json=JsonSerializer.Serialize(message); await log.WriteLineAsync(JsonSerializer.Serialize(new{direction="send",message})); byte[] bytes=Encoding.UTF8.GetBytes(json); await input.WriteAsync(Encoding.ASCII.GetBytes($"Content-Length: {bytes.Length}\r\n\r\n")); await input.WriteAsync(bytes); await input.FlushAsync(); return id; }
    async Task<JsonNode> Wait(Func<JsonNode,bool> predicate) { using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(25)); while(true) { var match=pending.FindIndex(x=>predicate(x)); if(match>=0) { var item=pending[match]; pending.RemoveAt(match); return item; } var header=new List<byte>(); while(true) { byte[] one=new byte[1]; if(await output.ReadAsync(one,timeout.Token)==0) throw new EndOfStreamException("Adapter stdout closed"); header.Add(one[0]); if(header.Count>=4&&header.TakeLast(4).SequenceEqual(new byte[]{13,10,13,10})) break; } string text=Encoding.ASCII.GetString(header.ToArray()); int length=int.Parse(text.Split('\r','\n').First(x=>x.StartsWith("Content-Length:")).Split(':')[1]); byte[] payload=new byte[length]; await output.ReadExactlyAsync(payload,timeout.Token); JsonNode node=JsonNode.Parse(payload)!; await log.WriteLineAsync(JsonSerializer.Serialize(new {direction="receive",message=node})); if(node["event"]?.GetValue<string>()=="output") Output+=node["body"]?["output"]?.GetValue<string>(); pending.Add(node); } }
    public async Task<JsonNode> Response(int id) { var response=await Wait(x=>x["type"]?.GetValue<string>()=="response"&&x["request_seq"]!.GetValue<int>()==id); if(response["success"]?.GetValue<bool>()!=true) throw new Exception(response.ToJsonString()); return response["body"]??new JsonObject(); }
    public async Task<JsonNode> Request(string command,object? arguments=null)=>await Response(await Send(command,arguments));
    public async Task<JsonNode> Event(string name)=>(await Wait(x=>x["type"]?.GetValue<string>()=="event"&&x["event"]?.GetValue<string>()==name))["body"]??new JsonObject();
    public async Task Close() { if(!proc.HasExited) { try { await Request("disconnect",new{terminateDebuggee=true}); await proc.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(3)); } catch { if(!proc.HasExited) proc.Kill(entireProcessTree:true); } } }
    public async ValueTask DisposeAsync() { await Close(); await log.DisposeAsync(); proc.Dispose(); }
}
