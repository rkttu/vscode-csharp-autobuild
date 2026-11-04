$ErrorActionPreference = 'Stop'
$work = $PSScriptRoot
$repo = [IO.Path]::GetFullPath((Join-Path $work '../../..'))
$codeRoot = Join-Path $repo 'validation-artifacts/fba-f5/editor-smoke/portable-code'
$env:VSCODE_PORTABLE = Join-Path $work 'portable-data'
$env:APPDATA = Join-Path $work 'appdata'
$env:DOTNET_CLI_HOME = Join-Path $work 'dotnet-home'
$env:DOTNET_ROOT = 'C:\Program Files\dotnet'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_CLI_UI_LANGUAGE = 'en-US'
$env:PATH = 'C:\Program Files\dotnet;' + $env:PATH
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
$vsix = Join-Path $repo 'validation-artifacts/fba-web-snippets-release-2026-11-03/readback-11.7.18004/csharp-with-netcoredbg-win32-arm64-11.7.18004.vsix'
$installLog = & (Join-Path $codeRoot 'bin/code.cmd') --install-extension $vsix --extensions-dir (Join-Path $work 'extensions') --user-data-dir (Join-Path $work 'portable-data/user-data') --force 2>&1 | Out-String
[IO.File]::WriteAllText((Join-Path $work 'install.txt'), $installLog)
if ($installLog -notmatch 'successfully installed|already installed') { throw $installLog }
$arguments = @('--user-data-dir', ('"' + (Join-Path $work 'portable-data/user-data') + '"'),
 '--extensions-dir', ('"' + (Join-Path $work 'extensions') + '"'),
 '--extensionDevelopmentPath', ('"' + (Join-Path $work 'driver') + '"'),
 '--extensionTestsPath', ('"' + (Join-Path $work 'editor-test.cjs') + '"'),
 '--disable-gpu', '--skip-welcome', '--skip-release-notes', '--disable-workspace-trust', '--no-sandbox',
 ('"' + (Join-Path $work 'workspace') + '"'))
$started = Start-Process -FilePath (Join-Path $codeRoot 'Code.exe') -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $work 'stdout.txt') -RedirectStandardError (Join-Path $work 'stderr.txt')
@{pid=$started.Id; arguments=$arguments; isolatedProfile=$true} | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $work 'launch.json')
Write-Output "Cancellation control started PID $($started.Id)"
