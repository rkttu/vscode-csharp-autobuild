#!/usr/bin/env -S dotnet --
#:property TargetFramework=net10.0
#:property PublishAot=false
#:property LogLevel=$([MSBuild]::ValueOrDefault('$(LOG_LEVEL)', 'Information'))
var filePath = AppContext.GetData("EntryPointFilePath") as string;
var directoryPath = AppContext.GetData("EntryPointFileDirectoryPath") as string;
Console.WriteLine($"File: {filePath}");
Console.WriteLine($"Directory: {directoryPath}");
var value = Environment.GetEnvironmentVariable("VARIABLE_NAME") ?? "defaultValue";
Console.WriteLine(value);
