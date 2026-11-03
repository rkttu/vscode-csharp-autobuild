import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

root = Path(__file__).resolve().parent
result = json.loads((root / 'editor-result.json').read_text(encoding='utf-8'))
assert result['success'] and len(result['snippets']) == 21
expanded = {prefix: item['text'] for item in result['snippets'] for prefix in item['prefixes']}
assert all(prefix.startswith('fba-') for prefix in expanded)
assert expanded['fba-envproperty'].strip() == "#:property LogLevel=$([MSBuild]::ValueOrDefault('$(LOG_LEVEL)', 'Information'))"
assert 'Console.WriteLine($"File: {filePath}");' in expanded['fba-paths']
assert '\\"' not in expanded['fba-paths']
combine = lambda *parts: '\n'.join(part.rstrip() for part in parts) + '\n'
directives = combine(expanded['fba-shebang'], expanded['fba-framework'], expanded['fba-disableaot'])
cases = {
    'console': expanded['fba-console'],
    'web': expanded['fba-web'],
    'paths-envproperty': combine(directives, expanded['fba-envproperty'], expanded['fba-paths'], expanded['fba-env'], 'Console.WriteLine(value);'),
    'periodic': combine(directives, expanded['fba-periodic']),
    'configuration-endpoints': combine(directives, '#:sdk Microsoft.NET.Sdk.Web', expanded['fba-config'],
        'var builder = WebApplication.CreateBuilder(args);\nvar app = builder.Build();',
        expanded['fba-mapget'], expanded['fba-mapjson'], 'Console.WriteLine(configuration["Probe"] ?? "unset");\napp.Run();'),
    'json-source-generation': combine(directives, 'var value = new JsonModel("Ada");', expanded['fba-jsonserialize'],
        'Console.WriteLine(json);\ninternal sealed record JsonModel(string Name);', expanded['fba-jsoncontext']),
}
environment = {**os.environ,
    'DOTNET_CLI_HOME': str(root / 'dotnet-home'), 'APPDATA': str(root / 'appdata'),
    'NUGET_PACKAGES': str(root / 'nuget'), 'DOTNET_GENERATE_ASPNET_CERTIFICATE': 'false',
    'DOTNET_CLI_TELEMETRY_OPTOUT': '1', 'DOTNET_CLI_UI_LANGUAGE': 'en-US',
    'MSBUILDDISABLENODEREUSE': '1', 'DOTNET_CLI_USE_MSBUILD_SERVER': '0', 'UseSharedCompilation': 'false'}
environment.pop('LOG_LEVEL', None)
summary = dict(success=False, source='Actual installed VS Code static snippet expansions',
    sdk='10.0.402', applicationsExecuted=False, certificateCommandsExecuted=False,
    networkPackagesRequired=False, builds=[], propertyEvaluation=[])
try:
    for name, text in cases.items():
        directory = root / 'workspace/builds' / name
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / 'app.cs'
        source.write_text(text, encoding='utf-8', newline='\n')
        args = ['dotnet', 'build', str(source), '--configuration', 'Debug', '--output', str(directory / 'output'),
                '-p:PublishAot=false', '-p:DebugType=portable', '-p:UseSharedCompilation=false',
                '--disable-build-servers', '--nologo']
        started = time.monotonic()
        completed = subprocess.run(args, cwd=directory, env=environment, capture_output=True, text=True, encoding='utf-8', timeout=120)
        (directory / 'build.txt').write_text(completed.stdout + completed.stderr, encoding='utf-8')
        dll = directory / 'output/app.dll'
        pdb = directory / 'output/app.pdb'
        item = dict(name=name, source=str(source), arguments=args, exitCode=completed.returncode,
                    elapsedSeconds=round(time.monotonic() - started, 3), dllExists=dll.is_file(), pdbExists=pdb.is_file(),
                    sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest())
        summary['builds'].append(item)
        assert completed.returncode == 0 and dll.is_file() and pdb.is_file(), (name, completed.stdout, completed.stderr)
    directory = root / 'workspace/builds/paths-envproperty'
    for label, value in [('fallback', None), ('environment', 'Warning')]:
        env = dict(environment)
        if value is not None:
            env['LOG_LEVEL'] = value
        args = ['dotnet', 'build', str(directory / 'app.cs'), '-getProperty:LogLevel', '--nologo']
        completed = subprocess.run(args, cwd=directory, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
        (directory / f'property-{label}.txt').write_text(completed.stdout + completed.stderr, encoding='utf-8')
        expected = value or 'Information'
        summary['propertyEvaluation'].append(dict(case=label, expected=expected, actual=completed.stdout.strip(), exitCode=completed.returncode))
        assert completed.returncode == 0 and re.search(r'^\s*' + expected + r'\s*$', completed.stdout, re.MULTILINE), (label, completed.stdout, completed.stderr)
    summary['success'] = True
finally:
    (root / 'build-result.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
