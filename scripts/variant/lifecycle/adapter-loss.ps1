param(
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [ValidateRange(10, 180)][int]$WaitSeconds = 90
)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath $WorkDir).Path
$taskExpected = Get-Content -LiteralPath (Join-Path $taskRoot 'expected.json') -Raw | ConvertFrom-Json
if ($taskExpected.schema -ne 1 -or $taskExpected.scenario -cne 'native-adapter-loss' -or
    !$taskExpected.candidate.localOnly -or $taskExpected.candidate.published) { throw 'Expected an isolated adapter-loss preparation' }
function Same-Path([string]$left, [string]$right) {
    return [string]::Equals([IO.Path]::GetFullPath($left), [IO.Path]::GetFullPath($right), [StringComparison]::OrdinalIgnoreCase)
}
function Assert-OwnedPath([string]$value) {
    $absolute = [IO.Path]::GetFullPath($value)
    if (!$absolute.StartsWith($taskRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes this isolated preparation' }
}
function Hash([string]$file) { return (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() }
foreach ($taskKey in @('marker', 'receipt', 'helper')) { Assert-OwnedPath $taskExpected.adapterLoss.$taskKey }
if (!(Same-Path $PSCommandPath $taskExpected.adapterLoss.helper) -or
    (Hash $PSCommandPath) -cne $taskExpected.harness.'adapter-loss.ps1') { throw 'Prepared helper identity differs' }
if (!(Same-Path $taskExpected.adapterLoss.marker (Join-Path $taskRoot 'progress/needs-adapter-loss.json')) -or
    !(Same-Path $taskExpected.adapterLoss.receipt (Join-Path $taskRoot 'progress/adapter-loss-receipt.json'))) { throw 'Unexpected adapter-loss receipt paths' }
if (Test-Path -LiteralPath $taskExpected.adapterLoss.receipt) { throw 'Adapter loss was already attempted; preserve the first receipt' }
$taskDeadline = [DateTime]::UtcNow.AddSeconds($WaitSeconds)
while (!(Test-Path -LiteralPath $taskExpected.adapterLoss.marker)) {
    if ([DateTime]::UtcNow -ge $taskDeadline) { throw 'Timed out waiting for the exact A/B readiness marker' }
    Start-Sleep -Milliseconds 100
}
$taskMarker = Get-Content -LiteralPath $taskExpected.adapterLoss.marker -Raw | ConvertFrom-Json
$taskReceipt = [ordered]@{ schema = 1; success = $false; nonce = $taskExpected.adapterLoss.nonce; root = $taskRoot;
    markerSha256 = (Hash $taskExpected.adapterLoss.marker); helperSha256 = (Hash $PSCommandPath);
    startedUtc = [DateTime]::UtcNow.ToString('o'); killRequested = $false; killedOnlyAdapter = $false }
$taskHeldAdapter = $null
function Snapshot([int]$processId) {
    if ($processId -le 0) { throw 'Expected a positive exact process ID' }
    $item = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $processId)
    if (!$item -or !$item.ExecutablePath -or !$item.CommandLine -or !$item.CreationDate) { throw ('Could not identify exact process ' + $processId) }
    return [ordered]@{ processId = [int]$item.ProcessId; parentProcessId = [int]$item.ParentProcessId;
        creationUtc = $item.CreationDate.ToUniversalTime().ToString('o'); executablePath = [string]$item.ExecutablePath;
        commandLine = [string]$item.CommandLine }
}
function Assert-SameProcess($before, $after) {
    foreach ($name in @('processId', 'parentProcessId', 'creationUtc', 'executablePath', 'commandLine')) {
        if ($before[$name] -cne $after[$name]) { throw ('Exact process identity changed: ' + $name) }
    }
}
function Verify-Fixture($fixture) {
    if ([int]$fixture.pid -le 0 -or [int]$fixture.port -le 0 -or [int]$fixture.port -gt 65535 -or !$fixture.nonce) { throw 'Invalid owned HTTP fixture identity' }
    $body = Invoke-RestMethod -Uri ('http://127.0.0.1:' + [int]$fixture.port + '/probe') -TimeoutSec 2
    if ($body.pid -ne $fixture.pid -or $body.nonce -cne $fixture.nonce -or $body.revision -cne $fixture.response.revision -or $body.value -ne 42) { throw 'Exact nonce/PID/revision fixture verification failed' }
    return $body
}
try {
    if ($taskMarker.schema -ne 1 -or $taskMarker.nonce -cne $taskExpected.adapterLoss.nonce -or
        !(Same-Path $taskMarker.root $taskRoot) -or !$taskMarker.extensionHostPid -or !$taskMarker.editorPid) { throw 'Readiness marker identity differs' }
    $taskLaunch = Get-Content -LiteralPath (Join-Path $taskRoot 'launch.json') -Raw | ConvertFrom-Json
    if ($taskLaunch.pid -ne $taskMarker.editorPid -or !(Same-Path $taskLaunch.work $taskRoot)) { throw 'Isolated editor launcher identity differs' }
    foreach ($taskFixture in @($taskMarker.a, $taskMarker.b)) {
        Assert-OwnedPath $taskFixture.program
        Assert-OwnedPath $taskFixture.output
        if (!(Same-Path (Split-Path -Parent $taskFixture.program) $taskFixture.output)) { throw 'Fixture output/program ownership differs' }
    }
    Assert-OwnedPath $taskMarker.adapter.path
    $taskExpectedAdapter = Join-Path $taskRoot ('extensions/' + $taskExpected.extensionId + '-' + $taskExpected.candidate.version + '/.debugger/netcoredbg/netcoredbg.exe')
    if (!(Same-Path $taskMarker.adapter.path $taskExpectedAdapter) -or
        $taskMarker.adapter.sha256 -cne $taskExpected.adapterLoss.adapterSha256 -or
        (Hash $taskMarker.adapter.path) -cne $taskExpected.adapterLoss.adapterSha256) { throw 'Installed native adapter path/hash differs from the prepared archive' }
    $taskReceipt.aBefore = Verify-Fixture $taskMarker.a
    $taskReceipt.bBefore = Verify-Fixture $taskMarker.b
    $taskA = Snapshot ([int]$taskMarker.a.pid)
    $taskB = Snapshot ([int]$taskMarker.b.pid)
    foreach ($taskPair in @(@{ process = $taskA; fixture = $taskMarker.a }, @{ process = $taskB; fixture = $taskMarker.b })) {
        if (!(Same-Path $taskPair.process.executablePath $taskExpected.sdk.executable) -or
            $taskPair.process.commandLine.Replace('/', '\').IndexOf(([string]$taskPair.fixture.program).Replace('/', '\'), [StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'Debuggee executable or exact program argument differs' }
    }
    $taskAdapterA = Snapshot $taskA.parentProcessId
    $taskAdapterB = Snapshot $taskB.parentProcessId
    if ($taskA.processId -eq $taskB.processId -or $taskAdapterA.processId -eq $taskAdapterB.processId -or
        $taskAdapterA.processId -eq $taskA.processId -or $taskAdapterA.processId -eq $taskB.processId) { throw 'A and B must have distinct adapter/debuggee identities' }
    foreach ($taskAdapter in @($taskAdapterA, $taskAdapterB)) {
        if (!(Same-Path $taskAdapter.executablePath $taskMarker.adapter.path) -or
            $taskAdapter.commandLine -notmatch '(?:^|\s)--interpreter=vscode(?:\s|$)' -or
            $taskAdapter.parentProcessId -ne $taskMarker.extensionHostPid) { throw 'Native adapter is not an exact child of the captured extension host' }
    }
    if ([DateTime]::Parse($taskAdapterA.creationUtc) -gt [DateTime]::Parse($taskA.creationUtc) -or
        [DateTime]::Parse($taskAdapterB.creationUtc) -gt [DateTime]::Parse($taskB.creationUtc)) { throw 'A parent adapter was created after its alleged debuggee' }
    $taskAncestry = @()
    $taskAncestorId = [int]$taskMarker.extensionHostPid
    for ($taskIndex = 0; $taskIndex -lt 8; $taskIndex++) {
        $taskAncestor = Snapshot $taskAncestorId
        if ($taskAncestry.processId -contains $taskAncestor.processId) { throw 'Process ancestry contains a cycle' }
        if (!(Same-Path $taskAncestor.executablePath $taskExpected.editor.executable)) { throw 'Unexpected executable in isolated editor ancestry' }
        $taskChildCreation = if ($taskAncestry.Count) { $taskAncestry[-1].creationUtc } else { $taskAdapterA.creationUtc }
        if ([DateTime]::Parse($taskAncestor.creationUtc) -gt [DateTime]::Parse($taskChildCreation)) { throw 'An ancestor was created after its alleged child' }
        $taskAncestry += $taskAncestor
        if ($taskAncestor.processId -eq $taskMarker.editorPid) { break }
        $taskAncestorId = $taskAncestor.parentProcessId
    }
    if ($taskAncestry[-1].processId -ne $taskMarker.editorPid -or
        $taskAncestry[-1].commandLine.IndexOf($taskRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) { throw 'Adapter ancestry does not reach this exact isolated editor' }
    $taskReceipt.identities = @{ aDebuggee = $taskA; bDebuggee = $taskB; aAdapter = $taskAdapterA; bAdapter = $taskAdapterB; editorAncestry = $taskAncestry }
    # Acquire and retain the actual process handle before the final CIM recheck.
    # Kill uses this handle, rather than resolving a potentially reused PID later.
    $taskHeldAdapter = [Diagnostics.Process]::GetProcessById($taskAdapterA.processId)
    $null = $taskHeldAdapter.Handle
    $taskStartUtc = $taskHeldAdapter.StartTime.ToUniversalTime()
    $taskReceipt.heldHandleStartUtc = $taskStartUtc.ToString('o')
    if ([Math]::Abs(($taskStartUtc - [DateTime]::Parse($taskAdapterA.creationUtc).ToUniversalTime()).Ticks) -gt 10) { throw 'Held OS handle creation time differs from CIM identity' }
    $taskReceipt.aImmediatelyBeforeKill = Verify-Fixture $taskMarker.a
    $taskReceipt.bImmediatelyBeforeKill = Verify-Fixture $taskMarker.b
    $taskRecheck = @{ aDebuggee = (Snapshot $taskA.processId); bDebuggee = (Snapshot $taskB.processId);
        aAdapter = (Snapshot $taskAdapterA.processId); bAdapter = (Snapshot $taskAdapterB.processId);
        extensionHost = (Snapshot ([int]$taskMarker.extensionHostPid)); editor = (Snapshot ([int]$taskMarker.editorPid)) }
    Assert-SameProcess $taskA $taskRecheck.aDebuggee
    Assert-SameProcess $taskB $taskRecheck.bDebuggee
    Assert-SameProcess $taskAdapterA $taskRecheck.aAdapter
    Assert-SameProcess $taskAdapterB $taskRecheck.bAdapter
    Assert-SameProcess $taskAncestry[0] $taskRecheck.extensionHost
    Assert-SameProcess $taskAncestry[-1] $taskRecheck.editor
    $taskReceipt.recheckedAncestry = @($taskAncestry | ForEach-Object {
        $current = Snapshot $_.processId
        Assert-SameProcess $_ $current
        $current
    })
    if ((Hash $taskMarker.adapter.path) -cne $taskMarker.adapter.sha256 -or
        (Hash $taskExpected.adapterLoss.marker) -cne $taskReceipt.markerSha256 -or $taskHeldAdapter.HasExited) { throw 'Adapter or marker changed immediately before the fault' }
    $taskReceipt.rechecked = $taskRecheck
    $taskReceipt.killRequestedUtc = [DateTime]::UtcNow.ToString('o')
    $taskReceipt.killRequested = $true
    $taskHeldAdapter.Kill() # This exact retained adapter process only; never a process tree.
    if (!$taskHeldAdapter.WaitForExit(5000)) { throw 'The exact adapter did not exit after Kill' }
    $taskReceipt.killedOnlyAdapter = $true
    $taskReceipt.killedProcessId = $taskAdapterA.processId
    $taskReceipt.adapterExitCode = $taskHeldAdapter.ExitCode
    $taskReceipt.adapterExitObservedUtc = [DateTime]::UtcNow.ToString('o')
    $taskReceipt.success = $true
} catch {
    $taskReceipt.error = $_.Exception.ToString()
    throw
} finally {
    if ($taskHeldAdapter) { $taskHeldAdapter.Dispose() }
    $taskReceipt.finishedUtc = [DateTime]::UtcNow.ToString('o')
    $taskTemporaryReceipt = $taskExpected.adapterLoss.receipt + '.tmp'
    Assert-OwnedPath $taskTemporaryReceipt
    if ((Test-Path -LiteralPath $taskExpected.adapterLoss.receipt) -or (Test-Path -LiteralPath $taskTemporaryReceipt)) { throw 'Do not overwrite an earlier adapter-loss receipt' }
    [IO.File]::WriteAllText($taskTemporaryReceipt, ($taskReceipt | ConvertTo-Json -Depth 12) + "`n")
    [IO.File]::Move($taskTemporaryReceipt, $taskExpected.adapterLoss.receipt)
}
