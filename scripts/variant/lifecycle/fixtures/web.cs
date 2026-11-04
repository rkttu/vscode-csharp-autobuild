#:sdk Microsoft.NET.Sdk.Web
#:property TargetFramework=net10.0

var marker = 40;
marker += 2;
const string revision = "initial";
var nonce = Environment.GetEnvironmentVariable("LIFECYCLE_TOKEN")
    ?? throw new InvalidOperationException("Missing owned lifecycle token.");
var builder = WebApplication.CreateSlimBuilder(args);
var app = builder.Build();

app.MapGet("/probe", () => Results.Json(new
{
    pid = Environment.ProcessId,
    nonce,
    revision,
    value = marker
}));

// This endpoint permits a failed test to release only its own verified server.
// It is a fixture facility, not a production debugger cleanup mechanism.
app.MapPost("/shutdown", (HttpContext context, IHostApplicationLifetime lifetime) =>
{
    if (context.Request.Query["token"].ToString() != nonce)
        return Results.Unauthorized();
    lifetime.StopApplication();
    return Results.Ok(new { pid = Environment.ProcessId, nonce });
});

app.Run();
