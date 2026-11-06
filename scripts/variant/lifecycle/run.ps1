param(
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [ValidateRange(60, 900)][int]$DeadlineSeconds = 300,
    [switch]$ShowWindow
)
$ErrorActionPreference = 'Stop'
$work = (Resolve-Path -LiteralPath $WorkDir).Path
$expected = Get-Content -LiteralPath (Join-Path $work 'expected.json') -Raw | ConvertFrom-Json
if ($expected.schema -ne 1 -or !$expected.candidate.localOnly -or $expected.candidate.published) { throw 'Expected a local lifecycle preparation' }
foreach ($marker in @('attempt.json', 'launch.json', 'launcher-result.json')) {
    if (Test-Path -LiteralPath (Join-Path $work $marker)) { throw 'This profile has already been attempted; use a fresh work directory and retain its first result' }
}
function Assert-Hash([string]$path, [string]$sha) {
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sha.ToLowerInvariant()) { throw "Input changed after preparation: $path" }
}
Assert-Hash $expected.editor.executable $expected.editor.sha256
Assert-Hash $expected.sdk.executable $expected.sdk.sha256
Assert-Hash $expected.candidate.path $expected.candidate.sha256
Assert-Hash $expected.dependency.path $expected.dependency.sha256
Assert-Hash $PSCommandPath $expected.harness.'run.ps1'
foreach ($driverFile in @('driver.cjs', 'extension-test.cjs')) {
    Assert-Hash (Join-Path $work ('driver/' + $driverFile)) $expected.harness.$driverFile
}
foreach ($fixture in @('a.cs', 'b.cs')) {
    $fixtureHash = if ($fixture -eq 'a.cs' -and $expected.harness.'prepared/a.cs') { $expected.harness.'prepared/a.cs' } else { $expected.harness.'fixtures/web.cs' }
    Assert-Hash (Join-Path $work ('workspace/' + $fixture)) $fixtureHash
}
if ($expected.nativeCancellation) { Assert-Hash $expected.nativeCancellation.target $expected.harness.'fixtures/cancel-build.targets' }
$attempt = [IO.File]::Open((Join-Path $work 'attempt.json'), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
try {
    $bytes = [Text.Encoding]::UTF8.GetBytes('{"schema":1,"attempted":true}')
    $attempt.Write($bytes, 0, $bytes.Length)
} finally { $attempt.Dispose() }

$environmentNames = @('APPDATA', 'LOCALAPPDATA', 'DOTNET_CLI_HOME', 'DOTNET_ROOT', 'NUGET_PACKAGES',
    'NUGET_HTTP_CACHE_PATH', 'TEMP', 'TMP', 'DOTNET_GENERATE_ASPNET_CERTIFICATE', 'DOTNET_CLI_TELEMETRY_OPTOUT',
    'DOTNET_CLI_UI_LANGUAGE', 'DOTNET_NOLOGO', 'NETCOREDBG_LIFECYCLE_ROOT', 'PATH', 'ELECTRON_RUN_AS_NODE', 'VSCODE_PORTABLE')
$previousEnvironment = @{}
foreach ($name in $environmentNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
$env:APPDATA = Join-Path $work 'appdata'
$env:LOCALAPPDATA = Join-Path $work 'localappdata'
$env:DOTNET_CLI_HOME = Join-Path $work 'dotnet-home'
$env:DOTNET_ROOT = $expected.sdk.root
$env:NUGET_PACKAGES = Join-Path $work 'nuget-packages'
$env:NUGET_HTTP_CACHE_PATH = Join-Path $work 'nuget-cache'
$env:TEMP = Join-Path $work 'tmp'
$env:TMP = $env:TEMP
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_CLI_UI_LANGUAGE = 'en-US'
$env:DOTNET_NOLOGO = 'true'
$env:NETCOREDBG_LIFECYCLE_ROOT = $work
$env:PATH = $expected.sdk.root + ';' + $env:PATH
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
Remove-Item Env:VSCODE_PORTABLE -ErrorAction SilentlyContinue
$editorProfile = Join-Path $work 'profile'
$extensions = Join-Path $work 'extensions'
$logs = Join-Path $work 'logs'
$launcher = @{ schema = 1; success = $false; work = $work; candidateSha256 = $expected.candidate.sha256;
    visibleWindowRequested = [bool]$ShowWindow;
    scope = 'normally installed local candidate and dependency; isolated VSCodium command API control, not qualification' }
$process = $null

function Request-OwnedFixtureShutdown {
    $stateFile = Join-Path $work 'progress/state.json'
    if (!(Test-Path -LiteralPath $stateFile)) { return @() }
    $state = $null
    for ($readAttempt = 0; $readAttempt -lt 3; $readAttempt++) {
        try { $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json; break }
        catch {
            if ($readAttempt -eq 2) { return @(@{ error = 'Could not read fixture ownership snapshot'; detail = $_.Exception.Message }) }
            Start-Sleep -Milliseconds 100
        }
    }
    $actions = @()
    foreach ($launch in $state.launches) {
        if (!$launch.pid -or !$launch.nonce -or !$launch.port) { continue }
        $origin = 'http://127.0.0.1:' + [int]$launch.port
        $action = @{ sessionId = $launch.sessionId; pid = $launch.pid; port = $launch.port }
        try {
            $owner = Invoke-RestMethod -Uri ($origin + '/probe') -TimeoutSec 2
            if ($owner.pid -ne $launch.pid -or $owner.nonce -cne $launch.nonce) { throw 'Fixture ownership mismatch; no shutdown requested' }
            $token = [Uri]::EscapeDataString([string]$launch.nonce)
            $null = Invoke-RestMethod -Uri ($origin + '/shutdown?token=' + $token) -Method Post -TimeoutSec 2
            $action.requested = $true
        } catch { $action.detail = $_.Exception.Message }
        $actions += $action
    }
    return $actions
}

try {
    Push-Location (Join-Path $work 'workspace')
    try {
        $sdkOutput = & $expected.sdk.executable --version 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -or ($sdkOutput.Trim() -split '\r?\n')[-1] -ne $expected.sdk.version) { throw "Selected SDK differs: $sdkOutput" }
        [IO.File]::WriteAllText((Join-Path $logs 'sdk-version.txt'), $sdkOutput)
    } finally { Pop-Location }
    $editorVersion = & $expected.editor.cli --version 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or !$editorVersion.Contains($expected.editor.version) -or !$editorVersion.Contains($expected.editor.commit)) { throw "Editor version differs: $editorVersion" }
    [IO.File]::WriteAllText((Join-Path $logs 'editor-version.txt'), $editorVersion)
    foreach ($item in @(@{name='runtime'; path=$expected.dependency.path}, @{name='candidate'; path=$expected.candidate.path})) {
        $install = & $expected.editor.cli --locale en --user-data-dir $editorProfile --extensions-dir $extensions --install-extension $item.path --force 2>&1 | Out-String
        $installExit = $LASTEXITCODE
        [IO.File]::WriteAllText((Join-Path $logs ($item.name + '-install.txt')), $install)
        if ($installExit -ne 0) { throw "Installation failed ($($item.name)): $install" }
    }
    $quoted = { param($path) '"' + $path + '"' }
    $arguments = @('--locale', 'en', '--user-data-dir', (& $quoted $editorProfile), '--extensions-dir', (& $quoted $extensions),
        '--extensionDevelopmentPath', (& $quoted (Join-Path $work 'driver')),
        '--extensionTestsPath', (& $quoted (Join-Path $work 'driver/extension-test.cjs')),
        '--skip-welcome', '--skip-release-notes', '--disable-gpu', '--disable-workspace-trust', '--no-sandbox',
        (& $quoted (Join-Path $work 'workspace')))
    # Explicit opt-in is needed when an operator will exercise native UI input.
    $windowStyle = if ($ShowWindow) { 'Normal' } else { 'Hidden' }
    $process = Start-Process -FilePath $expected.editor.executable -ArgumentList $arguments -WindowStyle $windowStyle -PassThru `
        -RedirectStandardOutput (Join-Path $logs 'stdout.txt') -RedirectStandardError (Join-Path $logs 'stderr.txt')
    $launcher.pid = $process.Id
    @{ pid=$process.Id; arguments=$arguments; work=$work; freshProfile=$true; visibleWindowRequested=[bool]$ShowWindow } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $work 'launch.json')
    if (!$process.WaitForExit($DeadlineSeconds * 1000)) {
        $launcher.fixtureShutdown = @(Request-OwnedFixtureShutdown)
        $ownedEditor = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $process.Id)
        if ($ownedEditor -and $ownedEditor.CommandLine -and $ownedEditor.CommandLine.Contains($work)) { $process.Kill(); $process.WaitForExit(10000) | Out-Null }
        throw 'Editor test safety deadline exceeded; first evidence retained'
    }
    $launcher.editorExitCode = $process.ExitCode
    $resultPath = Join-Path $work 'result.json'
    if (!(Test-Path -LiteralPath $resultPath)) { throw 'Editor returned without a result; retain logs' }
    $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    if ($process.ExitCode -ne 0 -or !$result.success) { throw 'Lifecycle scenario failed; see the retained first failure and logs' }
    $launcher.success = $true
} catch {
    $launcher.error = $_.Exception.Message
    if (!$launcher.fixtureShutdown) { $launcher.fixtureShutdown = @(Request-OwnedFixtureShutdown) }
    throw
} finally {
    $launcher | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $work 'launcher-result.json')
}
} finally {
    foreach ($name in $environmentNames) {
        $previousValue = $previousEnvironment[$name]
        if ($null -eq $previousValue) { $previousValue = [System.Management.Automation.Language.NullString]::Value }
        [Environment]::SetEnvironmentVariable($name, $previousValue, 'Process')
    }
}
