param([Parameter(Mandatory=$true)][string]$WorkDir,
      [ValidateRange(60,600)][int]$DeadlineSeconds=180)
$ErrorActionPreference='Stop'
$work=(Resolve-Path -LiteralPath $WorkDir).Path
$expected=Get-Content -LiteralPath (Join-Path $work 'expected.json') -Raw | ConvertFrom-Json
if($expected.scenario -ne 'installed-interrupted-cleanup' -or !$expected.candidate.localOnly -or $expected.candidate.published){throw 'Expected a prepared local interruption control'}
if(Test-Path -LiteralPath (Join-Path $work 'interruption-attempt.json')){throw 'This control was already attempted; preserve it and prepare a fresh directory'}
function Assert-Hash([string]$file,[string]$hash){if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash){throw "Input hash mismatch: $file"}}
Assert-Hash $expected.editor.executable $expected.editor.sha256
Assert-Hash $expected.sdk.executable $expected.sdk.sha256
Assert-Hash $expected.candidate.path $expected.candidate.sha256
Assert-Hash $expected.dependency.path $expected.dependency.sha256
Assert-Hash (Join-Path $work 'driver/extension-test.cjs') $expected.harness.'extension-test.cjs'
Assert-Hash (Join-Path $work 'driver/driver.cjs') $expected.harness.'driver.cjs'
Assert-Hash (Join-Path $work 'workspace/a.cs') $expected.harness.'fixtures/web.cs'
Assert-Hash $PSCommandPath $expected.harness.'interrupted-cleanup/run.ps1'
$attempt=[IO.File]::Open((Join-Path $work 'interruption-attempt.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
try{$bytes=[Text.Encoding]::UTF8.GetBytes('{"schema":1,"attempted":true}');$attempt.Write($bytes,0,$bytes.Length)}finally{$attempt.Dispose()}
$names=@('APPDATA','LOCALAPPDATA','DOTNET_CLI_HOME','DOTNET_ROOT','NUGET_PACKAGES','NUGET_HTTP_CACHE_PATH','TEMP','TMP',
 'DOTNET_GENERATE_ASPNET_CERTIFICATE','DOTNET_CLI_TELEMETRY_OPTOUT','DOTNET_CLI_UI_LANGUAGE','DOTNET_NOLOGO','NETCOREDBG_LIFECYCLE_ROOT','PATH','ELECTRON_RUN_AS_NODE','VSCODE_PORTABLE')
$previous=@{};foreach($name in $names){$previous[$name]=[Environment]::GetEnvironmentVariable($name,'Process')}
$runner=@{schema=1;success=$false;work=$work;candidateSha256=$expected.candidate.sha256;launches=@();scope='Two explicit app launches in the same isolated profile; actual extension-host exit during injected terminal deletion, not automatic reload or publication qualification'}
$appProcess=$null
function Save-Json([string]$name,$value){$value|ConvertTo-Json -Depth 20|Set-Content -LiteralPath (Join-Path $work $name)}
function Alive([int]$taskPid){return $null -ne (Get-Process -Id $taskPid -ErrorAction SilentlyContinue)}
function Close-OwnedEditor($process){
 if($process -and !$process.HasExited){$owned=Get-CimInstance Win32_Process -Filter ('ProcessId='+$process.Id)
  if(!$owned -or !$owned.CommandLine -or !$owned.CommandLine.Contains($work)){throw 'Refusing to close editor without exact isolated command-line ownership'}
  $process.Kill();$process.WaitForExit(10000)|Out-Null;return $true};return $false
}
function Fixture-Shutdown{
 $actions=@();foreach($name in @('first-launch.json','retry-launch.json')){
  $file=Join-Path $work $name;if(!(Test-Path -LiteralPath $file)){continue}
  $launch=Get-Content -LiteralPath $file -Raw|ConvertFrom-Json
  if(!$launch.pid -or !(Alive $launch.pid)){continue}
  $action=@{pid=$launch.pid;port=$launch.port}
  try{$body=Invoke-RestMethod -Uri ($launch.origin+'/probe') -TimeoutSec 2
   if($body.pid -ne $launch.pid -or $body.nonce -cne $launch.nonce){throw 'Fixture nonce/PID mismatch'}
   $null=Invoke-RestMethod -Uri ($launch.origin+'/shutdown?token='+[Uri]::EscapeDataString($launch.nonce)) -Method Post -TimeoutSec 2;$action.requested=$true
  }catch{$action.error=$_.Exception.Message};$actions+=$action
 };return $actions
}
try{
 $env:APPDATA=Join-Path $work 'appdata';$env:LOCALAPPDATA=Join-Path $work 'localappdata';$env:DOTNET_CLI_HOME=Join-Path $work 'dotnet-home'
 $env:DOTNET_ROOT=$expected.sdk.root;$env:NUGET_PACKAGES=Join-Path $work 'nuget-packages';$env:NUGET_HTTP_CACHE_PATH=Join-Path $work 'nuget-cache'
 $env:TEMP=Join-Path $work 'tmp';$env:TMP=$env:TEMP;$env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false';$env:DOTNET_CLI_TELEMETRY_OPTOUT='1'
 $env:DOTNET_CLI_UI_LANGUAGE='en-US';$env:DOTNET_NOLOGO='true';$env:NETCOREDBG_LIFECYCLE_ROOT=$work;$env:PATH=$expected.sdk.root+';'+$env:PATH
 Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue;Remove-Item Env:VSCODE_PORTABLE -ErrorAction SilentlyContinue
 $profilePath=Join-Path $work 'profile';$extensions=Join-Path $work 'extensions';$logs=Join-Path $work 'logs'
 Push-Location (Join-Path $work 'workspace')
 try{$sdk=& $expected.sdk.executable --version 2>&1|Out-String;if($LASTEXITCODE -ne 0 -or $sdk.Trim() -ne $expected.sdk.version){throw "SDK version mismatch: $sdk"};[IO.File]::WriteAllText((Join-Path $logs 'sdk-version.txt'),$sdk)}finally{Pop-Location}
 $editor=& $expected.editor.cli --version 2>&1|Out-String
 if($LASTEXITCODE -ne 0 -or !$editor.Contains($expected.editor.version) -or !$editor.Contains($expected.editor.commit)){throw 'Editor version mismatch'}
 [IO.File]::WriteAllText((Join-Path $logs 'editor-version.txt'),$editor)
 foreach($item in @(@{name='runtime';path=$expected.dependency.path},@{name='candidate';path=$expected.candidate.path})){
  $install=& $expected.editor.cli --locale en --user-data-dir $profilePath --extensions-dir $extensions --install-extension $item.path --force 2>&1|Out-String
  $code=$LASTEXITCODE;[IO.File]::WriteAllText((Join-Path $logs ($item.name+'-install.txt')),$install);if($code -ne 0){throw 'Normal VSIX installation failed'}
 }
 foreach($phase in @('interrupt','recover')){
  Save-Json 'control-phase.json' @{schema=1;phase=$phase;nonce=$expected.interruption.nonce}
  $argsList=@('--locale','en','--user-data-dir',('"'+$profilePath+'"'),'--extensions-dir',('"'+$extensions+'"'),
   '--extensionDevelopmentPath',('"'+(Join-Path $work 'driver')+'"'),'--extensionTestsPath',('"'+(Join-Path $work 'driver/extension-test.cjs')+'"'),
   '--skip-welcome','--skip-release-notes','--disable-gpu','--disable-workspace-trust','--no-sandbox',('"'+(Join-Path $work 'workspace')+'"'))
  $appProcess=Start-Process -FilePath $expected.editor.executable -ArgumentList $argsList -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs ($phase+'-stdout.txt')) -RedirectStandardError (Join-Path $logs ($phase+'-stderr.txt'))
  $record=@{phase=$phase;editorPid=$appProcess.Id;arguments=$argsList;startedAtUtc=[DateTime]::UtcNow.ToString('o')};$runner.launches+=$record
  $deadline=[DateTime]::UtcNow.AddSeconds($DeadlineSeconds)
  if($phase -eq 'interrupt'){
   $readyFile=Join-Path $work 'crash-ready.json'
   while(!(Test-Path -LiteralPath $readyFile)){
    if($appProcess.HasExited){throw 'Editor exited before the published first-deletion crash barrier'}
    if([DateTime]::UtcNow -gt $deadline){throw 'First-deletion interruption safety deadline'};Start-Sleep -Milliseconds 100
   }
   $marker=Get-Content -LiteralPath $readyFile -Raw|ConvertFrom-Json
   if($marker.nonce -cne $expected.interruption.nonce -or !$marker.debuggeePidGone -or !$marker.portReusable -or !$marker.partialFileAbsent){throw 'Incomplete first-deletion resource/journal evidence'}
   $hostProcess=Get-CimInstance Win32_Process -Filter ('ProcessId='+$marker.hostPid)
   if(!$hostProcess -or $hostProcess.ExecutablePath -ine $expected.editor.executable){throw 'Marker host is not the expected VSCodium executable'}
   $lineage=@();$ancestor=$hostProcess;$owns=$false
   for($depth=0;$depth -lt 8 -and $ancestor;$depth++){
    $lineage+=($ancestor|Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine)
    if($ancestor.ProcessId -eq $appProcess.Id){$owns=$true;break}
    $ancestor=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ancestor.ParentProcessId)
   }
   if(!$owns){throw 'Host PID is not in the exact isolated editor process lineage'}
   Save-Json 'extension-host-process.json' @{schema=1;verified=$true;pid=$marker.hostPid;observedAtUtc=[DateTime]::UtcNow.ToString('o');lineage=$lineage}
   Save-Json 'crash-ack.json.tmp' @{schema=1;pid=$marker.hostPid;nonce=$marker.nonce}
   Move-Item -LiteralPath (Join-Path $work 'crash-ack.json.tmp') -Destination (Join-Path $work 'crash-ack.json')
   $exitDeadline=[DateTime]::UtcNow.AddSeconds(15)
   while(Alive $marker.hostPid){if([DateTime]::UtcNow -gt $exitDeadline){throw 'The acknowledged extension host did not actually exit'};Start-Sleep -Milliseconds 100}
   $record.extensionHostPid=$marker.hostPid;$record.extensionHostGoneObservedAtUtc=[DateTime]::UtcNow.ToString('o')
   $record.editorExitedNaturally=$appProcess.WaitForExit(10000)
   if(!$record.editorExitedNaturally){$record.exactOwnedEditorClosedForRelaunch=Close-OwnedEditor $appProcess}
   $record.editorExitCode=$appProcess.ExitCode
   Assert-Hash (Join-Path $marker.entry 'record.json') $marker.receiptSha256
   if(!(Test-Path -LiteralPath $marker.output) -or (Test-Path -LiteralPath $marker.partialFile) -or (Test-Path -LiteralPath $marker.originalOutput)){throw 'Interrupted published partial output not retained exactly'}
   New-Item -ItemType Directory -Path $marker.originalOutput | Out-Null
   $replacement=@{path=Join-Path $marker.originalOutput 'replacement-sentinel';content=($marker.nonce+':replacement')}
   [IO.File]::WriteAllText($replacement.path,$replacement.content);Save-Json 'replacement.json' $replacement
  }else{
   if(!$appProcess.WaitForExit($DeadlineSeconds*1000)){throw 'Recovery launch safety deadline'}
   $record.editorExitCode=$appProcess.ExitCode
   $result=Get-Content -LiteralPath (Join-Path $work 'result.json') -Raw|ConvertFrom-Json
   if($appProcess.ExitCode -ne 0 -or !$result.success){throw 'Second-launch recovery/retry failed'}
   if($result.extensionHostPid -eq $runner.launches[0].extensionHostPid){throw 'Same host PID cannot prove a new activation'}
  }
  $record.endedAtUtc=[DateTime]::UtcNow.ToString('o');Save-Json ('launch-'+$phase+'.json') $record
 }
 $runner.success=$true
}catch{
 $runner.error=$_.Exception.Message;$runner.fixtureShutdown=@(Fixture-Shutdown)
 try{$runner.exactOwnedEditorClosedOnFailure=Close-OwnedEditor $appProcess}catch{$runner.editorCloseError=$_.Exception.Message}
 throw
}finally{
 try{Save-Json 'control-runner-result.json' $runner}
 finally{foreach($name in $names){$value=$previous[$name];if($null -eq $value){$value=[System.Management.Automation.Language.NullString]::Value};[Environment]::SetEnvironmentVariable($name,$value,'Process')}}
}
