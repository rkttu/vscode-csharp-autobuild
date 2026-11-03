#!/usr/bin/env -S dotnet --
#:property TargetFramework=net10.0
#:property PublishAot=false
#:sdk Microsoft.NET.Sdk.Web
var configurationBuilder = new Microsoft.Extensions.Configuration.ConfigurationBuilder();
Microsoft.Extensions.Configuration.FileConfigurationExtensions.SetBasePath(
    configurationBuilder, AppContext.GetData("EntryPointFileDirectoryPath") as string ?? AppContext.BaseDirectory);
Microsoft.Extensions.Configuration.JsonConfigurationExtensions.AddJsonFile(
    configurationBuilder, "appsettings.json", optional: true, reloadOnChange: false);
Microsoft.Extensions.Configuration.EnvironmentVariablesExtensions.AddEnvironmentVariables(configurationBuilder);
var configuration = configurationBuilder.Build();
var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();
app.MapGet("/", () => "Hello, World!");
app.MapGet("/random", () => new
{
    timestamp = DateTimeOffset.UtcNow,
    value = Random.Shared.Next(0, 100)
});
Console.WriteLine(configuration["Probe"] ?? "unset");
app.Run();
