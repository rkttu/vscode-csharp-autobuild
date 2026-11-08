param(
    [Parameter(Mandatory=$true)][string]$WorkDir,
    [ValidateRange(60,600)][int]$DeadlineSeconds=300,
    [switch]$ShowWindow
)
$ErrorActionPreference='Stop'
$taskRoot=(Resolve-Path -LiteralPath $WorkDir).Path
$taskExpected=Get-Content -LiteralPath (Join-Path $taskRoot 'expected.json') -Raw|ConvertFrom-Json
if($taskExpected.scenario -cne 'abrupt-extension-host-loss' -or !$taskExpected.candidate.localOnly -or $taskExpected.candidate.published -or
    !$taskExpected.testDriver.localOnly -or $taskExpected.testDriver.published -or $taskExpected.hostLoss.extensionDevelopmentPath -or $taskExpected.hostLoss.extensionTestsPath){throw 'Expected a local production-mode host-loss preparation'}
function Same-Path([string]$left,[string]$right){return [string]::Equals([IO.Path]::GetFullPath($left),[IO.Path]::GetFullPath($right),[StringComparison]::OrdinalIgnoreCase)}
function Within-Root([string]$file){if(![IO.Path]::GetFullPath($file).StartsWith($taskRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Path escapes this isolated run'}}
function Hash([string]$file){return (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()}
function Assert-Hash([string]$file,[string]$hash){if((Hash $file) -cne $hash){throw ('Input hash differs: '+$file)}}
function Save-Json([string]$name,$value,[bool]$once=$false){
    $file=Join-Path $taskRoot $name;Within-Root $file
    if($once -and (Test-Path -LiteralPath $file)){throw ('Do not overwrite first evidence: '+$name)}
    $temporary=$file+'.'+[Guid]::NewGuid().ToString()+'.tmp';Within-Root $temporary
    [IO.File]::WriteAllText($temporary,($value|ConvertTo-Json -Depth 60)+"`n")
    if($once){[IO.File]::Move($temporary,$file)}else{Move-Item -LiteralPath $temporary -Destination $file -Force}
}
foreach($taskMarker in @('control-attempt.json','control-runner-result.json','host-kill-receipt.json','phase.json','fault-ready.json')){
    if(Test-Path -LiteralPath (Join-Path $taskRoot $taskMarker)){throw 'This run was already attempted; retain it and prepare a fresh directory'}
}
Assert-Hash $taskExpected.editor.executable $taskExpected.editor.sha256
Assert-Hash $taskExpected.sdk.executable $taskExpected.sdk.sha256
Assert-Hash $taskExpected.candidate.path $taskExpected.candidate.sha256
Assert-Hash $taskExpected.dependency.path $taskExpected.dependency.sha256
Assert-Hash $taskExpected.testDriver.path $taskExpected.testDriver.sha256
Assert-Hash $PSCommandPath $taskExpected.harness.'host-loss/run.ps1'
foreach($taskName in @('driver.cjs','extension-test.cjs')){Assert-Hash (Join-Path $taskRoot ('driver/'+$taskName)) $taskExpected.harness.$taskName}
foreach($taskName in @('driver/package.json','profile/User/settings.json','prepared-settings.json')){Assert-Hash (Join-Path $taskRoot $taskName) $taskExpected.harness.$taskName}
Assert-Hash (Join-Path $taskRoot 'workspace/a.cs') $taskExpected.harness.'fixtures/web.cs'
Save-Json 'control-attempt.json' @{schema=1;nonce=$taskExpected.hostLoss.nonce;attempted=$true} $true
$taskEnvironmentNames=@('APPDATA','LOCALAPPDATA','DOTNET_CLI_HOME','DOTNET_ROOT','NUGET_PACKAGES','NUGET_HTTP_CACHE_PATH','TEMP','TMP',
    'DOTNET_GENERATE_ASPNET_CERTIFICATE','DOTNET_CLI_TELEMETRY_OPTOUT','DOTNET_CLI_UI_LANGUAGE','DOTNET_NOLOGO','NETCOREDBG_LIFECYCLE_ROOT','PATH','ELECTRON_RUN_AS_NODE','VSCODE_PORTABLE')
$taskPrevious=@{};foreach($taskName in $taskEnvironmentNames){$taskPrevious[$taskName]=[Environment]::GetEnvironmentVariable($taskName,'Process')}
$taskRunner=[ordered]@{schema=1;success=$false;nonce=$taskExpected.hostLoss.nonce;work=$taskRoot;appLaunches=0;normallyInstalledDriver=$true;
    extensionDevelopmentPath=$false;extensionTestsPath=$false;visibleWindowRequested=[bool]$ShowWindow}
$taskApp=$null;$taskHeldHost=$null;$taskHeldAdapter=$null;$taskHeldDebuggee=$null;$taskCheckpoint=$null
$taskObservations=@()
function Snapshot([int]$processId){
    if($processId -le 0){throw 'Expected a positive exact PID'}
    $item=Get-CimInstance Win32_Process -Filter ('ProcessId='+$processId)
    if(!$item -or !$item.ExecutablePath -or !$item.CommandLine -or !$item.CreationDate){throw ('Could not identify exact process '+$processId)}
    return [ordered]@{processId=[int]$item.ProcessId;parentProcessId=[int]$item.ParentProcessId;creationUtc=$item.CreationDate.ToUniversalTime().ToString('o');executablePath=[string]$item.ExecutablePath;commandLine=[string]$item.CommandLine}
}
function Same-Process($before,$after){foreach($name in @('processId','parentProcessId','creationUtc','executablePath','commandLine')){if($before[$name] -cne $after[$name]){throw ('Exact process identity changed: '+$name)}}}
function Hold-Process($identity){
    $held=[Diagnostics.Process]::GetProcessById($identity.processId);$null=$held.Handle
    if([Math]::Abs(($held.StartTime.ToUniversalTime()-[DateTime]::Parse($identity.creationUtc).ToUniversalTime()).Ticks) -gt 10){$held.Dispose();throw 'Held process creation time differs from CIM identity'}
    return $held
}
function Lineage([int]$hostId){
    $chain=@();$next=$hostId
    for($depth=0;$depth -lt 8;$depth++){
        $item=Snapshot $next
        if($chain.processId -contains $item.processId){throw 'Process ancestry contains a cycle'}
        if(!(Same-Path $item.executablePath $taskExpected.editor.executable)){throw 'Unexpected executable in isolated editor ancestry'}
        if($chain.Count -and [DateTime]::Parse($item.creationUtc) -gt [DateTime]::Parse($chain[-1].creationUtc)){throw 'An ancestor was created after its alleged child'}
        $chain+=$item;if($item.processId -eq $taskApp.Id){break};$next=$item.parentProcessId
    }
    if($chain[-1].processId -ne $taskApp.Id -or $chain[-1].commandLine.IndexOf($taskRoot,[StringComparison]::OrdinalIgnoreCase) -lt 0){throw 'Host ancestry does not reach the exact isolated editor'}
    if($chain[-1].commandLine -match '(?i)--extensionDevelopmentPath|--extensionTestsPath'){throw 'Development/test host flags invalidate production crash recovery'}
    return $chain
}
function Await-File([string]$name){
    $file=Join-Path $taskRoot $name
    while(!(Test-Path -LiteralPath $file)){
        if($taskApp.HasExited){throw ('Editor exited before '+$name)}
        if([DateTime]::UtcNow -gt $taskDeadline){throw ('Control safety deadline waiting for '+$name)}
        Start-Sleep -Milliseconds 100
    }
    return Get-Content -LiteralPath $file -Raw|ConvertFrom-Json
}
function Ack-Host([int]$phase){
    $marker=Await-File ('host-'+$phase+'.json')
    if($marker.schema -ne 1 -or $marker.nonce -cne $taskExpected.hostLoss.nonce -or $marker.phase -ne $phase -or $marker.driver.extensionMode -ne 1){throw 'Production driver host handshake differs'}
    $driverPath=Join-Path $taskRoot ('extensions/'+$taskExpected.testDriver.id+'-'+$taskExpected.testDriver.version)
    if(!(Same-Path $marker.driver.path $driverPath)){throw 'Driver was not loaded from its normal isolated installation'}
    foreach($name in @('driver.cjs','extension-test.cjs')){Assert-Hash (Join-Path $driverPath $name) $taskExpected.testDriver.payload.('extension/'+$name)}
    foreach($name in @('entry.cjs','runtime.cjs','classify.cjs','web.cjs','recovery.cjs')){if($marker.installedModules.$name -cne $taskExpected.candidate.ownedModules.$name){throw 'Host loaded module identity differs'}}
    $chain=@(Lineage ([int]$marker.extensionHostPid))
    Save-Json ('host-'+$phase+'-process.json') @{schema=1;verified=$true;nonce=$marker.nonce;observedUtc=[DateTime]::UtcNow.ToString('o');marker=$marker;editorPid=$taskApp.Id;lineage=$chain} $true
    Save-Json ('ack-'+$phase+'.json') @{schema=1;nonce=$marker.nonce;extensionHostPid=$marker.extensionHostPid;editorPid=$taskApp.Id} $true
    return @{marker=$marker;lineage=$chain}
}
function Verify-Http($launch){
    $body=Invoke-RestMethod -Uri ($launch.origin+'/probe') -TimeoutSec 2
    if($body.pid -ne $launch.pid -or $body.nonce -cne $launch.nonce -or $body.revision -cne $launch.revision -or $body.value -ne 42){throw 'Exact debuggee HTTP nonce/PID/revision differs'}
    return $body
}
function Assert-PreservedFiles($launch){
    foreach($file in $launch.preservedFiles){Within-Root $file.path;$item=Get-Item -LiteralPath $file.path
        if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -ne $file.size){throw 'Preserved output/sentinel type or size differs'}
        Assert-Hash $file.path $file.sha256
    }
}
function Can-Bind([int]$port){$listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$port);try{$listener.Start();return $true}catch [Net.Sockets.SocketException]{return $false}finally{$listener.Stop()}}
function Queue-Empty([string]$base){foreach($name in @('terminal-cleanup-v1','terminal-cleanup-staging-v1')){$directory=Join-Path $base $name;if((Test-Path -LiteralPath $directory) -and @(Get-ChildItem -LiteralPath $directory -Force).Count){return $false}};return $true}
function Observe-Native([string]$label){
    $launch=$taskCheckpoint.launch
    $item=[ordered]@{label=$label;atUtc=[DateTime]::UtcNow.ToString('o');oldHostHasExited=$taskHeldHost.HasExited;adapterHasExited=$taskHeldAdapter.HasExited;
        debuggeeHasExited=$taskHeldDebuggee.HasExited;portBindable=(Can-Bind ([int]$launch.port));outputExists=(Test-Path -LiteralPath $launch.output);programExists=(Test-Path -LiteralPath $launch.program);terminalQueuesEmpty=(Queue-Empty $launch.base)}
    try{$item.http=Verify-Http $launch;$item.httpOwned=$true}catch{$item.httpOwned=$false;$item.httpError=$_.Exception.Message}
    try{Assert-PreservedFiles $launch;$item.unknownFilesPreserved=$true}catch{$item.unknownFilesPreserved=$false;$item.fileError=$_.Exception.Message}
    $script:taskObservations+=$item;Save-Json 'external-observations.json' @{schema=1;nonce=$taskExpected.hostLoss.nonce;observations=$script:taskObservations}
    return $item
}
function Fixture-Shutdown{
    $actions=@();$file=Join-Path $taskRoot 'owned-launches.json';if(!(Test-Path -LiteralPath $file)){return $actions}
    $state=Get-Content -LiteralPath $file -Raw|ConvertFrom-Json
    if($state.nonce -cne $taskExpected.hostLoss.nonce){throw 'Fixture state nonce differs'}
    foreach($launch in $state.launches){if(!$launch.pid -or !$launch.nonce){continue};$action=@{label=$launch.label;pid=$launch.pid;nonce=$launch.nonce}
        try{$null=Verify-Http $launch;$null=Invoke-RestMethod -Uri ($launch.origin+'/shutdown?token='+[Uri]::EscapeDataString($launch.nonce)) -Method Post -TimeoutSec 2;$action.exactHttpShutdownRequested=$true}catch{$action.detail=$_.Exception.Message};$actions+=$action
    };return $actions
}
try{
    $env:APPDATA=Join-Path $taskRoot 'appdata';$env:LOCALAPPDATA=Join-Path $taskRoot 'localappdata';$env:DOTNET_CLI_HOME=Join-Path $taskRoot 'dotnet-home';$env:DOTNET_ROOT=$taskExpected.sdk.root
    $env:NUGET_PACKAGES=Join-Path $taskRoot 'nuget-packages';$env:NUGET_HTTP_CACHE_PATH=Join-Path $taskRoot 'nuget-cache';$env:TEMP=Join-Path $taskRoot 'tmp';$env:TMP=$env:TEMP
    $env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false';$env:DOTNET_CLI_TELEMETRY_OPTOUT='1';$env:DOTNET_CLI_UI_LANGUAGE='en-US';$env:DOTNET_NOLOGO='true';$env:NETCOREDBG_LIFECYCLE_ROOT=$taskRoot;$env:PATH=$taskExpected.sdk.root+';'+$env:PATH
    Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue;Remove-Item Env:VSCODE_PORTABLE -ErrorAction SilentlyContinue
    $taskProfile=Join-Path $taskRoot 'profile';$taskExtensions=Join-Path $taskRoot 'extensions';$taskLogs=Join-Path $taskRoot 'logs'
    Push-Location (Join-Path $taskRoot 'workspace')
    try{$version=& $taskExpected.sdk.executable --version 2>&1|Out-String;if($LASTEXITCODE -ne 0 -or $version.Trim() -cne $taskExpected.sdk.version){throw 'Selected SDK differs'};[IO.File]::WriteAllText((Join-Path $taskLogs 'sdk-version.txt'),$version)}finally{Pop-Location}
    $version=& $taskExpected.editor.cli --version 2>&1|Out-String;if($LASTEXITCODE -ne 0 -or !$version.Contains($taskExpected.editor.version) -or !$version.Contains($taskExpected.editor.commit)){throw 'Selected editor differs'};[IO.File]::WriteAllText((Join-Path $taskLogs 'editor-version.txt'),$version)
    foreach($item in @(@{name='runtime';path=$taskExpected.dependency.path},@{name='candidate';path=$taskExpected.candidate.path},@{name='driver';path=$taskExpected.testDriver.path})){
        $install=& $taskExpected.editor.cli --locale en --user-data-dir $taskProfile --extensions-dir $taskExtensions --install-extension $item.path --force 2>&1|Out-String
        $code=$LASTEXITCODE;[IO.File]::WriteAllText((Join-Path $taskLogs ($item.name+'-install.txt')),$install);if($code -ne 0){throw ('Normal isolated installation failed: '+$item.name)}
    }
    $taskArguments=@('--locale','en','--user-data-dir',('"'+$taskProfile+'"'),'--extensions-dir',('"'+$taskExtensions+'"'),'--skip-welcome','--skip-release-notes','--disable-gpu','--disable-workspace-trust','--no-sandbox',('"'+(Join-Path $taskRoot 'workspace')+'"'))
    if(($taskArguments -join ' ') -match '(?i)--extensionDevelopmentPath|--extensionTestsPath'){throw 'Production driver requires both development/test flags absent'}
    $taskWindowStyle=if($ShowWindow){'Normal'}else{'Hidden'}
    $taskApp=Start-Process -FilePath $taskExpected.editor.executable -ArgumentList $taskArguments -WindowStyle $taskWindowStyle -PassThru -RedirectStandardOutput (Join-Path $taskLogs 'stdout.txt') -RedirectStandardError (Join-Path $taskLogs 'stderr.txt')
    $taskRunner.appLaunches=1;$taskRunner.editorPid=$taskApp.Id;$taskRunner.arguments=$taskArguments;$taskDeadline=[DateTime]::UtcNow.AddSeconds($DeadlineSeconds)
    Save-Json 'launch.json' @{schema=1;editorPid=$taskApp.Id;arguments=$taskArguments;work=$taskRoot;productionMode=$true} $true
    $taskFirst=Ack-Host 1
    $taskReady=Await-File 'fault-ready.json'
    if($taskReady.nonce -cne $taskExpected.hostLoss.nonce -or $taskReady.extensionHostPid -ne $taskFirst.marker.extensionHostPid -or $taskReady.editorPid -ne $taskApp.Id){throw 'Fault readiness nonce/host/editor differs'}
    Assert-Hash (Join-Path $taskRoot 'phase.json') $taskReady.phaseSha256
    $taskCheckpoint=Get-Content -LiteralPath (Join-Path $taskRoot 'phase.json') -Raw|ConvertFrom-Json
    if($taskCheckpoint.nonce -cne $taskExpected.hostLoss.nonce -or $taskCheckpoint.firstHost -ne $taskReady.extensionHostPid -or $taskCheckpoint.stage -cne 'armed'){throw 'Persistent phase identity differs'}
    $launch=$taskCheckpoint.launch;Within-Root $launch.output;Within-Root $launch.program
    $outputBase=Join-Path $taskRoot ('profile/User/globalStorage/'+$taskExpected.extensionId+'/file-based-apps')
    if(!(Same-Path $launch.source (Join-Path $taskRoot 'workspace/a.cs')) -or !(Same-Path $launch.program (Join-Path $launch.output 'FileApp.dll')) -or
        !(Same-Path $launch.base $outputBase) -or (Split-Path -Leaf $launch.output) -cnotmatch '^run-[A-Za-z0-9]{6}$' -or
        (Split-Path -Leaf (Split-Path -Parent $launch.output)) -cnotmatch '^[0-9a-f]{24}$'){throw 'Generated source/output ownership differs'}
    if($launch.dapProcessEvent.body.systemProcessId -ne $launch.pid -or !$launch.dapProcessEvent.body.isLocalProcess){throw 'Captured DAP PID does not match the verified app'}
    Assert-PreservedFiles $launch;if(!(Queue-Empty $launch.base)){throw 'An active run must not have a terminal cleanup receipt before the abrupt fault'}
    $taskNativePath=[IO.Path]::GetFullPath([string]$taskCheckpoint.adapter.path)
    Within-Root $taskNativePath;Assert-Hash $taskNativePath $taskExpected.hostLoss.adapterSha256
    $expectedAdapter=Join-Path $taskRoot ('extensions/'+$taskExpected.extensionId+'-'+$taskExpected.candidate.version+'/'+$taskExpected.hostLoss.adapterRelativePath)
    if(!(Same-Path $taskNativePath $expectedAdapter) -or $taskCheckpoint.adapter.sha256 -cne $taskExpected.hostLoss.adapterSha256){throw 'Native adapter path/archive identity differs'}
    $taskDebuggee=Snapshot ([int]$launch.pid);$taskAdapter=Snapshot $taskDebuggee.parentProcessId;$taskChain=@(Lineage ([int]$taskReady.extensionHostPid));$taskHost=$taskChain[0]
    if(!(Same-Path $taskDebuggee.executablePath $taskExpected.sdk.executable) -or $taskDebuggee.commandLine.Replace('/','\').IndexOf(([string]$launch.program).Replace('/','\'),[StringComparison]::OrdinalIgnoreCase) -lt 0){throw 'Exact app executable/program differs'}
    if(!(Same-Path $taskAdapter.executablePath $taskNativePath) -or $taskAdapter.commandLine -notmatch '(?:^|\s)--interpreter=vscode(?:\s|$)' -or $taskAdapter.parentProcessId -ne $taskHost.processId){throw 'App parent is not this isolated host native adapter'}
    if([DateTime]::Parse($taskHost.creationUtc) -gt [DateTime]::Parse($taskAdapter.creationUtc) -or [DateTime]::Parse($taskAdapter.creationUtc) -gt [DateTime]::Parse($taskDebuggee.creationUtc)){throw 'Native child creation ordering differs'}
    $taskHeldHost=Hold-Process $taskHost;$taskHeldAdapter=Hold-Process $taskAdapter;$taskHeldDebuggee=Hold-Process $taskDebuggee
    $taskBefore=Observe-Native 'before-kill'
    if($taskBefore.oldHostHasExited -or $taskBefore.adapterHasExited -or $taskBefore.debuggeeHasExited -or !$taskBefore.httpOwned -or $taskBefore.portBindable -or !$taskBefore.unknownFilesPreserved){throw 'The owned native run is not active immediately before the abrupt fault'}
    $taskBeforeHttp=Verify-Http $launch
    $taskRechecked=@{extensionHost=(Snapshot $taskHost.processId);adapter=(Snapshot $taskAdapter.processId);debuggee=(Snapshot $taskDebuggee.processId);editorAncestry=@($taskChain|ForEach-Object{Snapshot $_.processId})}
    Same-Process $taskHost $taskRechecked.extensionHost;Same-Process $taskAdapter $taskRechecked.adapter;Same-Process $taskDebuggee $taskRechecked.debuggee
    for($index=0;$index -lt $taskChain.Count;$index++){Same-Process $taskChain[$index] $taskRechecked.editorAncestry[$index]}
    Assert-Hash $taskExpected.editor.executable $taskExpected.editor.sha256;Assert-Hash $taskNativePath $taskExpected.hostLoss.adapterSha256
    Assert-Hash (Join-Path $taskRoot 'phase.json') $taskReady.phaseSha256;Assert-PreservedFiles $launch
    if($taskHeldHost.HasExited -or $taskHeldAdapter.HasExited -or $taskHeldDebuggee.HasExited){throw 'A captured native process exited before the fault'}
    $taskReceipt=[ordered]@{schema=1;success=$false;nonce=$taskExpected.hostLoss.nonce;editorPid=$taskApp.Id;phaseSha256=$taskReady.phaseSha256;
        readinessSha256=(Hash (Join-Path $taskRoot 'fault-ready.json'));identities=@{extensionHost=$taskHost;adapter=$taskAdapter;debuggee=$taskDebuggee;editorAncestry=$taskChain};
        rechecked=$taskRechecked;httpImmediatelyBeforeKill=$taskBeforeHttp;heldHostStartUtc=$taskHeldHost.StartTime.ToUniversalTime().ToString('o');killedOnlyExtensionHost=$false}
    $taskReceipt.killRequestedUtc=[DateTime]::UtcNow.ToString('o')
    $taskHeldHost.Kill() # This retained extension-host OS handle only; never its descendants.
    if(!$taskHeldHost.WaitForExit(5000)){throw 'The exact extension host did not exit'}
    $taskReceipt.killedProcessId=$taskHost.processId;$taskReceipt.killedOnlyExtensionHost=$true;$taskReceipt.hostExitCode=$taskHeldHost.ExitCode;$taskReceipt.killObservedUtc=[DateTime]::UtcNow.ToString('o');$taskReceipt.success=$true
    Save-Json 'host-kill-receipt.json' $taskReceipt $true
    $null=Observe-Native 'after-kill';Start-Sleep -Milliseconds 250;$null=Observe-Native 'after-250ms';Start-Sleep -Milliseconds 750;$null=Observe-Native 'after-1000ms'
    $taskSecond=Ack-Host 2
    if($taskSecond.marker.extensionHostPid -eq $taskFirst.marker.extensionHostPid){throw 'Extension host identity was not replaced'}
    $null=Observe-Native 'replacement-host-acknowledged'
    while(!$taskApp.HasExited){if([DateTime]::UtcNow -gt $taskDeadline){throw 'Host-loss control safety deadline'};Start-Sleep -Milliseconds 100}
    $taskApp.WaitForExit();$taskRunner.editorExitCode=$taskApp.ExitCode;$taskRunner.extensionHostPids=@($taskFirst.marker.extensionHostPid,$taskSecond.marker.extensionHostPid)
    $taskResult=Get-Content -LiteralPath (Join-Path $taskRoot 'result.json') -Raw|ConvertFrom-Json
    $taskRunner.mechanicsCompleted=$taskResult.mechanicsCompleted;$taskRunner.nativeResourcesReleased=$taskResult.nativeResourcesReleased;$taskRunner.unknownOutputAndGuardPreserved=$taskResult.unknownOutputAndGuardPreserved
    $taskPost=Observe-Native 'editor-exited';Save-Json 'post-exit-observation.json' $taskPost $true
    if($taskApp.ExitCode -ne 0 -or !$taskResult.mechanicsCompleted -or $taskResult.editorPid -ne $taskApp.Id -or $taskResult.firstHost -ne $taskFirst.marker.extensionHostPid -or $taskResult.host -ne $taskSecond.marker.extensionHostPid){throw 'Same-editor production-mode replacement mechanics failed'}
    Assert-PreservedFiles $launch
    if(!$taskResult.success -or !$taskResult.nativeResourcesReleased -or !$taskPost.debuggeeHasExited -or !$taskPost.adapterHasExited -or !$taskPost.portBindable){throw 'Original native resources did not naturally release; retain observations before fixture fallback'}
    Within-Root $taskResult.retry.output;if(Test-Path -LiteralPath $taskResult.retry.output){throw 'The newly owned retry output survived its exact Stop'}
    $taskRunner.success=$true
}catch{
    $taskRunner.error=$_.Exception.ToString();Save-Json 'runner-first-failure.json' @{schema=1;atUtc=[DateTime]::UtcNow.ToString('o');error=$taskRunner.error;observations=$taskObservations} $true
    try{$taskRunner.fixtureShutdown=@(Fixture-Shutdown)}catch{$taskRunner.fixtureShutdownError=$_.Exception.Message}
    if($taskApp -and !$taskApp.HasExited){
        try{$current=Snapshot $taskApp.Id;if(!(Same-Path $current.executablePath $taskExpected.editor.executable) -or $current.commandLine.IndexOf($taskRoot,[StringComparison]::OrdinalIgnoreCase) -lt 0){throw 'Refusing to close an unverified editor'};$taskApp.Kill();$taskApp.WaitForExit(10000)|Out-Null;$taskRunner.exactOwnedEditorClosedOnFailure=$true}catch{$taskRunner.editorCloseError=$_.Exception.Message}
    }
    throw
}finally{
    try{Save-Json 'control-runner-result.json' $taskRunner $true}
    finally{
        foreach($held in @($taskHeldHost,$taskHeldAdapter,$taskHeldDebuggee)){if($held){$held.Dispose()}}
        foreach($taskName in $taskEnvironmentNames){$value=$taskPrevious[$taskName];if($null -eq $value){$value=[System.Management.Automation.Language.NullString]::Value};[Environment]::SetEnvironmentVariable($taskName,$value,'Process')}
    }
}
