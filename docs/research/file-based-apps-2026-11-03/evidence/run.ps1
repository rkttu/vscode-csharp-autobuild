param([string]$Debugger = (Join-Path $PSScriptRoot 'debugger/netcoredbg/netcoredbg.exe'))
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $env:DOTNET_CLI_HOME = Join-Path $PSScriptRoot 'cli-home'
    $env:NUGET_PACKAGES = Join-Path $PSScriptRoot 'nuget'
    $env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
    $env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
    dotnet --info | Out-File environment.txt
    dotnet build app/app.cs --configuration Debug --output app/output --nologo 2>&1 | Tee-Object app-default-build.log
    if ($LASTEXITCODE -ne 0) { throw 'File-based build failed' }
    dotnet build probe/probe.cs --configuration Debug --output probe/output --nologo 2>&1 | Tee-Object probe-build.log
    if ($LASTEXITCODE -ne 0) { throw 'DAP client build failed' }
    dotnet probe/output/probe.dll $Debugger app/output/app.dll app/app.cs fileapp
    if ($LASTEXITCODE -ne 0) { throw 'File-based DAP probe failed' }
    dotnet build project/Project.csproj --configuration Debug --output project/output --nologo 2>&1 | Tee-Object project-build.log
    if ($LASTEXITCODE -ne 0) { throw 'Project build failed' }
    dotnet probe/output/probe.dll $Debugger project/output/Project.dll app/app.cs project
    if ($LASTEXITCODE -ne 0) { throw 'Project DAP probe failed' }
} finally { Pop-Location }
