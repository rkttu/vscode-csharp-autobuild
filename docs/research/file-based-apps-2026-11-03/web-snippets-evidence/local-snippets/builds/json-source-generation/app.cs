#!/usr/bin/env -S dotnet --
#:property TargetFramework=net10.0
#:property PublishAot=false
var value = new JsonModel("Ada");
var json = System.Text.Json.JsonSerializer.Serialize(value, AppJsonContext.Default.JsonModel);
Console.WriteLine(json);
internal sealed record JsonModel(string Name);
[System.Text.Json.Serialization.JsonSerializable(typeof(JsonModel))]
internal partial class AppJsonContext : System.Text.Json.Serialization.JsonSerializerContext
{
}
