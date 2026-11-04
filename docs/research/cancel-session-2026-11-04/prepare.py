import json
from pathlib import Path
import shutil

work = Path(__file__).resolve().parent
repo = work.parents[2]
driver = work / 'driver'
driver.mkdir(parents=True, exist_ok=True)
(driver / 'package.json').write_text(json.dumps({'name':'cancel-session-control-driver','publisher':'local-test','version':'0.0.1','main':'./driver.cjs','engines':{'vscode':'^1.106.0'},'activationEvents':['*']}))
(driver / 'driver.cjs').write_text('exports.activate = function () {};\n')
user = work / 'portable-data/user-data/User'
user.mkdir(parents=True, exist_ok=True)
(user / 'settings.json').write_text(json.dumps({'extensions.autoUpdate':False,'extensions.autoCheckUpdates':False,'update.mode':'none','telemetry.telemetryLevel':'off','dotnetAcquisitionExtension.existingDotnetPath':[{'extensionId':'dotnetdev-kr-custom.csharp-with-netcoredbg','path':'C:\\Program Files\\dotnet\\dotnet.exe'}]}))
dependency = 'ms-dotnettools.vscode-dotnet-runtime-3.2.0'
shutil.copytree(repo / 'validation-artifacts/fba-web-snippets-release-2026-11-03/editor-web/extensions' / dependency, work / 'extensions' / dependency, dirs_exist_ok=True)
workspace = work / 'workspace'
workspace.mkdir(exist_ok=True)
(workspace / 'global.json').write_text(json.dumps({'sdk':{'version':'10.0.403','rollForward':'disable'}}))
nuget = '<configuration><packageSources><clear /></packageSources></configuration>'
(workspace / 'NuGet.Config').write_text(nuget)
(workspace / 'app.cs').write_text('#:property TargetFramework=net10.0\nint answer = 40;\nanswer += 2;\nConsole.WriteLine($"ANSWER={answer}");\n')
user_nuget = work / 'appdata/NuGet'
user_nuget.mkdir(parents=True, exist_ok=True)
(user_nuget / 'NuGet.Config').write_text(nuget)
print(work)
