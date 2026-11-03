# File-based debugging experiment evidence

Observed November 3, 2026 on Windows ARM64 with SDK 10.0.402 and runtime 10.0.13. See [the research report](../../2026-11-03-file-based-app-debugging.md) for scope and conclusions.

- `fileapp.*`: default Debug build of `app/app.cs`, without a project file.
- `example.*`: fresh copy of the documented example under a directory named `editor example`, including spaces in source and output paths.
- `project.*`: the same source built through `project/Project.csproj` as a regression control.
- `provenance.json`: exact debugger release, archive/executable hashes, SDK, and commands.
- `environment.txt` and `*-build.txt`: captured SDK/build output.
- `probe/probe.cs`: dependency-free C# DAP client used for all three sessions.

Each result contains assertions for breakpoint/source line, local variable, expression evaluation, Step Over, changed variable value, stdout, and exit code. The protocol traces retain requests and responses, including source mapping. `<probe-root>`, `<dotnet-root>`, and `<user-profile>` replace local paths; normalization is the only change to the captured results and traces. Build logs use `.txt` in this archive.

No editor UI or installed-extension session was exercised. The ARM64 archive belongs to the published distribution; the experiment did not extract an installed VSIX. The regression control is a single .NET 10 app, not the complete release test suite.

## Reproduce the DAP checks

Use an ARM64 Windows host, native .NET SDK **10.0.402**, and its .NET 10 runtime for the same environment. The evidence's `global.json` pins that exact SDK. The editor example's separate `global.json` accepts stable .NET 10 feature bands.

Copy this evidence directory into an ignored work directory so that rerunning the probe does not overwrite the archived records. Run the following from the repository root in PowerShell:

```powershell
$researchWork = Join-Path (Get-Location) 'validation-artifacts/fileapp-reproduction'
New-Item -ItemType Directory -Path $researchWork -Force | Out-Null
Copy-Item 'docs/research/file-based-apps-2026-11-03/evidence/*' $researchWork -Recurse -Force
$debuggerUri = 'https://github.com/rkttu/vscode-csharp-autobuild/releases/download/csharp-v11.7.18-netcoredbg-v3.2.0-1092-g9744e1f05186-r1/netcoredbg-win32-arm64.zip'
$archivePath = Join-Path $researchWork 'netcoredbg-win32-arm64.zip'
Invoke-WebRequest $debuggerUri -OutFile $archivePath
$expectedHash = '09746c136b177fe5a2e7ee4f558f051169d7322227d525ac2b919aba7e6be58e'
if ((Get-FileHash $archivePath -Algorithm SHA256).Hash -ne $expectedHash) {
    throw 'Debugger archive hash mismatch'
}
Expand-Archive $archivePath -DestinationPath (Join-Path $researchWork 'debugger') -Force
# Use the SDK root that contains dotnet.exe, matching the adapter environment.
$env:DOTNET_ROOT = Split-Path (Get-Command dotnet).Source
& (Join-Path $researchWork 'run.ps1')
```

`run.ps1` builds the file app and DAP client directly from `.cs`, then checks both the file app and project control. It accepts `-Debugger <path>` for an already extracted copy. It writes fresh logs/results into the copied work directory. Other platforms require their matching debugger archive and equivalent commands; they were not tested here.

To reproduce the exact editor example's path-with-spaces case, after the preceding commands:

```powershell
$exampleWork = Join-Path $researchWork 'editor example'
New-Item -ItemType Directory -Path $exampleWork -Force | Out-Null
Copy-Item 'docs/research/file-based-apps-2026-11-03/example/app.cs' $exampleWork -Force
Copy-Item 'docs/research/file-based-apps-2026-11-03/example/global.json' $exampleWork -Force
Push-Location $exampleWork
try {
    dotnet build app.cs --configuration Debug --output .file-based-debug/app
    if ($LASTEXITCODE -ne 0) { throw 'Example build failed' }
} finally { Pop-Location }
$debuggerPath = Join-Path $researchWork 'debugger/netcoredbg/netcoredbg.exe'
$clientDll = Join-Path $researchWork 'probe/output/probe.dll'
$exampleDll = Join-Path $exampleWork '.file-based-debug/app/app.dll'
$sourcePath = Join-Path $exampleWork 'app.cs'
dotnet $clientDll $debuggerPath $exampleDll $sourcePath (Join-Path $researchWork 'example')
if ($LASTEXITCODE -ne 0) { throw 'Example DAP probe failed' }
```

For actual editor use, copy the separate [example configuration](../example) into a new folder as described in the report. That route requires the installed C# (with netcoredbg) extension and does not need this DAP client or a manual debugger download.
