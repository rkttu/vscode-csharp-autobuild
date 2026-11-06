param([Parameter(Mandatory=$true)][string]$WorkDir,
      [ValidateRange(60,600)][int]$DeadlineSeconds=240)
$ErrorActionPreference='Stop'
$work=(Resolve-Path -LiteralPath $WorkDir).Path
$expected=Get-Content -LiteralPath (Join-Path $work 'expected.json') -Raw|ConvertFrom-Json
if($expected.scenario -ne 'actual-workbench-reload' -or !$expected.candidate.localOnly -or $expected.candidate.published -or $expected.actualReload.extensionTestsPath){throw 'Expected a prepared local actual Reload control'}
if(Test-Path -LiteralPath (Join-Path $work 'control-attempt.json')){throw 'This control was already attempted; retain it and prepare a fresh directory'}
function Assert-Hash([string]$file,[string]$hash){if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash){throw "Input hash mismatch: $file"}}
Assert-Hash $expected.editor.executable $expected.editor.sha256
Assert-Hash $expected.sdk.executable $expected.sdk.sha256
Assert-Hash $expected.candidate.path $expected.candidate.sha256
Assert-Hash $expected.dependency.path $expected.dependency.sha256
foreach($name in @('extension-test.cjs','driver.cjs')){Assert-Hash (Join-Path $work ('driver/'+$name)) $expected.harness.$name}
foreach($name in @('driver/package.json','profile/User/settings.json')){Assert-Hash (Join-Path $work $name) $expected.harness.$name}
Assert-Hash (Join-Path $work 'prepared-settings.json') $expected.harness.'prepared-settings.json'
Assert-Hash (Join-Path $work 'workspace/a.cs') $expected.harness.'fixtures/web.cs'
Assert-Hash (Join-Path $work 'workspace/b.cs') $expected.harness.'fixtures/web.cs'
Assert-Hash $PSCommandPath $expected.harness.'active-reload/run.ps1'
$attempt=[IO.File]::Open((Join-Path $work 'control-attempt.json'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
try{$bytes=[Text.Encoding]::UTF8.GetBytes('{"schema":1,"attempted":true}');$attempt.Write($bytes,0,$bytes.Length)}finally{$attempt.Dispose()}
$names=@('APPDATA','LOCALAPPDATA','DOTNET_CLI_HOME','DOTNET_ROOT','NUGET_PACKAGES','NUGET_HTTP_CACHE_PATH','TEMP','TMP',
 'DOTNET_GENERATE_ASPNET_CERTIFICATE','DOTNET_CLI_TELEMETRY_OPTOUT','DOTNET_CLI_UI_LANGUAGE','DOTNET_NOLOGO','NETCOREDBG_LIFECYCLE_ROOT','PATH','ELECTRON_RUN_AS_NODE','VSCODE_PORTABLE')
$previous=@{};foreach($name in $names){$previous[$name]=[Environment]::GetEnvironmentVariable($name,'Process')}
$runner=@{schema=1;success=$false;work=$work;candidateSha256=$expected.candidate.sha256;appLaunches=0;environmentVariablesManaged=$names;
 scope='Actual workbench Reload with live installed Web session; normal driver activation, same app and two hosts; public command API, not physical F5 or macOS qualification'}
$appProcess=$null
function Save-Json([string]$name,$value){$value|ConvertTo-Json -Depth 30|Set-Content -LiteralPath (Join-Path $work $name)}
function Alive([int]$taskPid){return $null -ne (Get-Process -Id $taskPid -ErrorAction SilentlyContinue)}
function Assert-WithinWork([string]$path){$full=[IO.Path]::GetFullPath($path);if(!$full.StartsWith($work+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw "Evidence path outside isolated work directory: $path"}}
function Can-Bind([int]$port){$listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$port);try{$listener.Start();return $true}catch [Net.Sockets.SocketException]{return $false}finally{$listener.Stop()}}
function Close-OwnedEditor($process){if($process -and !$process.HasExited){$owned=Get-CimInstance Win32_Process -Filter ('ProcessId='+$process.Id);if(!$owned -or !$owned.CommandLine -or !$owned.CommandLine.Contains($work)){throw 'Refusing to close editor without exact isolated command-line ownership'};$process.Kill();$process.WaitForExit(10000)|Out-Null;return $true};return $false}
function Fixture-Shutdown{
 $actions=@();$file=Join-Path $work 'owned-launches.json';if(!(Test-Path -LiteralPath $file)){return $actions}
 $state=Get-Content -LiteralPath $file -Raw|ConvertFrom-Json
 foreach($launch in $state.launches){if(!$launch.pid -or !(Alive $launch.pid)){continue};$action=@{pid=$launch.pid;port=$launch.port;label=$launch.label}
  try{$body=Invoke-RestMethod -Uri ($launch.origin+'/probe') -TimeoutSec 2;if($body.pid -ne $launch.pid -or $body.nonce -cne $launch.nonce){throw 'Fixture nonce/PID mismatch'}
   $null=Invoke-RestMethod -Uri ($launch.origin+'/shutdown?token='+[Uri]::EscapeDataString($launch.nonce)) -Method Post -TimeoutSec 2;$action.requested=$true
  }catch{$action.error=$_.Exception.Message};$actions+=$action};return $actions
}
try{
 $env:APPDATA=Join-Path $work 'appdata';$env:LOCALAPPDATA=Join-Path $work 'localappdata';$env:DOTNET_CLI_HOME=Join-Path $work 'dotnet-home';$env:DOTNET_ROOT=$expected.sdk.root
 $env:NUGET_PACKAGES=Join-Path $work 'nuget-packages';$env:NUGET_HTTP_CACHE_PATH=Join-Path $work 'nuget-cache';$env:TEMP=Join-Path $work 'tmp';$env:TMP=$env:TEMP
 $env:DOTNET_GENERATE_ASPNET_CERTIFICATE='false';$env:DOTNET_CLI_TELEMETRY_OPTOUT='1';$env:DOTNET_CLI_UI_LANGUAGE='en-US';$env:DOTNET_NOLOGO='true';$env:NETCOREDBG_LIFECYCLE_ROOT=$work;$env:PATH=$expected.sdk.root+';'+$env:PATH
 Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue;Remove-Item Env:VSCODE_PORTABLE -ErrorAction SilentlyContinue
 $profilePath=Join-Path $work 'profile';$extensions=Join-Path $work 'extensions';$logs=Join-Path $work 'logs'
 Push-Location (Join-Path $work 'workspace')
 try{$sdk=& $expected.sdk.executable --version 2>&1|Out-String;if($LASTEXITCODE -ne 0 -or $sdk.Trim() -ne $expected.sdk.version){throw "SDK version mismatch: $sdk"};[IO.File]::WriteAllText((Join-Path $logs 'sdk-version.txt'),$sdk)}finally{Pop-Location}
 $editor=& $expected.editor.cli --version 2>&1|Out-String;if($LASTEXITCODE -ne 0 -or !$editor.Contains($expected.editor.version) -or !$editor.Contains($expected.editor.commit)){throw 'Editor version mismatch'};[IO.File]::WriteAllText((Join-Path $logs 'editor-version.txt'),$editor)
 foreach($item in @(@{name='runtime';path=$expected.dependency.path},@{name='candidate';path=$expected.candidate.path})){
  $install=& $expected.editor.cli --locale en --user-data-dir $profilePath --extensions-dir $extensions --install-extension $item.path --force 2>&1|Out-String
  $code=$LASTEXITCODE;[IO.File]::WriteAllText((Join-Path $logs ($item.name+'-install.txt')),$install);if($code -ne 0){throw 'Normal VSIX installation failed'}
 }
 $argsList=@('--locale','en','--user-data-dir',('"'+$profilePath+'"'),'--extensions-dir',('"'+$extensions+'"'),'--extensionDevelopmentPath',('"'+(Join-Path $work 'driver')+'"'),
  '--skip-welcome','--skip-release-notes','--disable-gpu','--disable-workspace-trust','--no-sandbox',('"'+(Join-Path $work 'workspace')+'"'))
 $appProcess=Start-Process -FilePath $expected.editor.executable -ArgumentList $argsList -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'stdout.txt') -RedirectStandardError (Join-Path $logs 'stderr.txt')
 $runner.appLaunches=1;$runner.editorPid=$appProcess.Id;$runner.arguments=$argsList;$runner.startedAtUtc=[DateTime]::UtcNow.ToString('o');$hostPids=@()
 $deadline=[DateTime]::UtcNow.AddSeconds($DeadlineSeconds)
 foreach($n in 1,2){
  while(!(Test-Path -LiteralPath (Join-Path $work "host-$n.json"))){if($appProcess.HasExited){throw "Editor exited before actual Reload host $n handshake"};if([DateTime]::UtcNow -gt $deadline){throw "Safety deadline host $n"};Start-Sleep -Milliseconds 100}
  $marker=Get-Content -LiteralPath (Join-Path $work "host-$n.json") -Raw|ConvertFrom-Json
  if($marker.nonce -cne $expected.actualReload.nonce -or $marker.phase -ne $n){throw 'Host marker identity mismatch'}
  $hostProcess=Get-CimInstance Win32_Process -Filter ('ProcessId='+$marker.extensionHostPid)
  if(!$hostProcess -or $hostProcess.ExecutablePath -ine $expected.editor.executable){throw 'Marker host is not expected VSCodium executable'}
  $lineage=@();$ancestor=$hostProcess;$owns=$false
  for($depth=0;$depth -lt 8 -and $ancestor;$depth++){$lineage+=($ancestor|Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine);if($ancestor.ProcessId -eq $appProcess.Id){$owns=$true;break};$ancestor=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ancestor.ParentProcessId)}
  if(!$owns){throw 'Host PID is not in exact isolated editor lineage'}
  if($n -eq 2 -and $marker.extensionHostPid -eq $hostPids[0]){throw 'Actual Reload did not replace extension host'}
  $hostPids+=,$marker.extensionHostPid
  Save-Json "extension-host-$n-process.json" @{schema=1;verified=$true;observedAtUtc=[DateTime]::UtcNow.ToString('o');editorPid=$appProcess.Id;lineage=$lineage}
  Save-Json "ack-$n.json.tmp" @{schema=1;nonce=$marker.nonce;extensionHostPid=$marker.extensionHostPid;editorPid=$appProcess.Id}
  Move-Item -LiteralPath (Join-Path $work "ack-$n.json.tmp") -Destination (Join-Path $work "ack-$n.json")
 }
 while(!$appProcess.HasExited){if([DateTime]::UtcNow -gt $deadline){throw 'Actual Reload control safety deadline'};Start-Sleep -Milliseconds 100}
 $appProcess.WaitForExit();$runner.editorExitCode=$appProcess.ExitCode;$runner.endedAtUtc=[DateTime]::UtcNow.ToString('o');$runner.extensionHostPids=$hostPids
 $result=Get-Content -LiteralPath (Join-Path $work 'result.json') -Raw|ConvertFrom-Json
 if($appProcess.ExitCode -ne 0 -or !$result.mechanicsCompleted -or $result.editorPid -ne $appProcess.Id -or $result.firstHost -ne $hostPids[0] -or $result.host -ne $hostPids[1]){throw 'Actual Reload mechanics or identity failed'}
 $resources=@();foreach($launch in @($result.firstLaunch,$result.retry)){
  Assert-WithinWork $launch.output;$resources+=@{label=$launch.label;pid=$launch.pid;pidGone=!(Alive $launch.pid);port=$launch.port;portReusable=(Can-Bind $launch.port);outputAbsent=!(Test-Path -LiteralPath $launch.output);output=$launch.output}
 }
 Save-Json 'post-exit-observation.json' @{schema=1;observedAtUtc=[DateTime]::UtcNow.ToString('o');editorPid=$appProcess.Id;extensionHostPids=$hostPids;hostsGone=@($hostPids|ForEach-Object{!(Alive $_)});resources=$resources;baselineSuccess=$result.success}
 if(!$result.success){throw 'Actual Reload baseline left original PID, port or output; preserve the first observed result'}
 foreach($hostPid in $hostPids){if(Alive $hostPid){throw 'A captured extension host survived successful editor exit'}}
 foreach($resource in $resources){if(!$resource.pidGone -or !$resource.portReusable -or !$resource.outputAbsent){throw 'Exact captured PID, port or output survived successful editor exit'}}
 $runner.success=$true
}catch{
 $runner.error=$_.Exception.Message;$runner.fixtureShutdown=@(Fixture-Shutdown)
 try{$runner.exactOwnedEditorClosedOnFailure=Close-OwnedEditor $appProcess}catch{$runner.editorCloseError=$_.Exception.Message}
 throw
}finally{
 try{Save-Json 'control-runner-result.json' $runner}
 finally{foreach($name in $names){$value=$previous[$name];if($null -eq $value){$value=[System.Management.Automation.Language.NullString]::Value};[Environment]::SetEnvironmentVariable($name,$value,'Process')}}
}
