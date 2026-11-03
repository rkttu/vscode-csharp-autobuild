using System.Text.Json;
if (args.Length != 1 || !Uri.TryCreate(args[0], UriKind.Absolute, out var uri) || uri.Scheme != "http" || !uri.IsLoopback)
    return 2;
File.AppendAllText(Path.Combine(AppContext.BaseDirectory, "browser-observation.jsonl"),
    JsonSerializer.Serialize(new { url = args[0], recordedAt = DateTimeOffset.UtcNow, processId = Environment.ProcessId }) + "\n");
return 0;
