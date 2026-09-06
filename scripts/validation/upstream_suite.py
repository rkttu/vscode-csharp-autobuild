"""Run Samsung's required DAP scenarios with external SDK projects and strict results."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from audit import native_architecture, sha256

REPO = Path(__file__).resolve().parents[2]


def policy():
    return json.loads((REPO / 'config/upstream-dap-tests.json').read_text(encoding='utf-8'))


def validate_result(result, runtime, arch, debugger_hash):
    expected = policy()['tests']
    assert result['success'] is True, result.get('error', 'Upstream DAP suite failed')
    assert result['runtime'] == runtime and result['architecture'] == arch
    assert result['debuggerSha256'] == debugger_hash, 'Suite ran a different debugger'
    assert result['sourceUnchanged'] is True
    assert [test['name'] for test in result['tests']] == expected, 'Missing, duplicate or reordered upstream tests'
    assert all(test['success'] is True and test['exitCode'] == 0 and not test['timedOut']
               for test in result['tests']), 'Failed or timed-out upstream test'


def command(cmd, cwd, env, log, timeout):
    started = time.monotonic()
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen([str(x) for x in cmd], cwd=cwd, env=env, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=os.name != 'nt')
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=stream, stderr=stream)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            code = process.wait(timeout=15)
        finally:
            if os.name != 'nt':
                # Remove only descendants in the process group created for this command.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    return dict(exitCode=code, timedOut=timed_out, durationSeconds=round(time.monotonic() - started, 2))


def run(source, debugger, dotnet, runtime, sdk, arch, work, evidence):
    work.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    rules = policy()
    result = dict(success=False, runtime=runtime, sdk=sdk, architecture=arch,
                  debuggerSha256=sha256(debugger), sourceUnchanged=False, tests=[], stage='prepare')
    files = {}
    env = os.environ.copy()
    for key in ('DirectoryBuildTargetsPath', 'DirectoryBuildPropsPath', 'TargetFramework', 'TargetFrameworks'):
        env.pop(key, None)
    env.update(DOTNET_ROOT=str(dotnet.parent), PATH=str(dotnet.parent) + os.pathsep + env['PATH'],
               DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_NOLOGO='1', DOTNET_CLI_UI_LANGUAGE='en-US',
               UseSharedCompilation='false', MSBUILDDISABLENODEREUSE='1', DOTNET_CLI_USE_MSBUILD_SERVER='0')
    env['DOTNET_ROOT_' + arch.upper()] = str(dotnet.parent)
    try:
        assert native_architecture(dotnet) == arch and native_architecture(debugger) == arch
        (work / 'global.json').write_text(json.dumps({'sdk': {'version': sdk, 'rollForward': 'disable'}}))
        assert subprocess.check_output([str(dotnet), '--version'], cwd=work, env=env, text=True).strip() == sdk
        suite = source / 'test-suite'
        script = suite / 'run_tests.sh'
        names = re.findall(r'"(VSCode[^"]+)"', script.read_text().split('# Skipped tests:')[0])
        assert names == rules['tests'], 'Upstream default DAP test list changed; review and update the required suite'
        files[script] = sha256(script)
        test_sources = {}
        for name in ['TestRunner', 'LocalDebugger', 'NetcoreDbgTest'] + names:
            original = suite / name / (name + '.csproj')
            files[original] = sha256(original)
            project = ET.parse(original)
            assert project.getroot().attrib == {'Sdk': 'Microsoft.NET.Sdk'}, 'Unexpected upstream project SDK'
            assert len(project.findall('.//TargetFramework')) == 1
            # Generate an external project; never rewrite Samsung's source or project file.
            project.find('.//TargetFramework').text = f'net{runtime}.0'
            props = ET.SubElement(project.getroot(), 'PropertyGroup')
            ET.SubElement(props, 'EnableDefaultCompileItems').text = 'false'
            items = ET.SubElement(project.getroot(), 'ItemGroup')
            sources = [p for p in sorted((suite / name).rglob('*.cs')) if 'obj' not in p.parts and 'bin' not in p.parts]
            assert sources, 'No test sources: ' + name
            for file in sources:
                files[file] = sha256(file)
                ET.SubElement(items, 'Compile', Include=str(file))
            test_sources[name] = sources
            destination = work / 'projects' / name / original.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            project.write(destination, encoding='utf-8', xml_declaration=True)
        result['stage'] = 'build-runner'
        build_args = [dotnet, 'build', '--artifacts-path', work / 'build', '-v:q']
        build = command([*build_args, work / 'projects/TestRunner/TestRunner.csproj'], work, env,
                        evidence / f'upstream-net{runtime}-runner-build.log', 300)
        assert build['exitCode'] == 0 and not build['timedOut'], 'Upstream TestRunner build failed'
        for name in names:
            record = dict(name=name, success=False, stage='build')
            result['tests'].append(record)
            result['stage'] = name
            log_prefix = evidence / f'upstream-net{runtime}-{name}'
            built = command([*build_args, work / 'projects' / name / (name + '.csproj')], work, env,
                            Path(str(log_prefix) + '-build.log'), 300)
            record.update(built)
            if built['exitCode'] == 0 and not built['timedOut']:
                record['stage'] = 'execute'
                log = Path(str(log_prefix) + '.log')
                executed = command([dotnet, work / 'build/bin/TestRunner/debug/TestRunner.dll',
                    '--local', debugger, '--proto', 'vscode', '--test', name,
                    '--sources', ';'.join(str(p) for p in test_sources[name]),
                    '--assembly', work / 'build/bin' / name / 'debug' / (name + '.dll'),
                    '--dotnet', dotnet], work, env, log, rules['testTimeoutSeconds'])
                record.update(executed)
                marker = f'Success: Test case "{name}" is passed!!!'
                record['success'] = executed['exitCode'] == 0 and not executed['timedOut'] and marker in log.read_text(errors='replace')
            print(f'Upstream .NET {runtime}: {name}: {"PASS" if record["success"] else "FAIL"}', flush=True)
        failures = [test['name'] for test in result['tests'] if not test['success']]
        assert not failures, 'Upstream DAP failures: ' + ', '.join(failures)
        result.update(success=True, stage='complete')
    except Exception as error:
        result['error'] = str(error) or type(error).__name__
    finally:
        changed = [str(file.relative_to(source)) for file, digest in files.items() if not file.is_file() or sha256(file) != digest]
        result['sourceUnchanged'] = bool(files) and not changed
        result['success'] = result['success'] and result['sourceUnchanged']
        result['changedOrMissing'] = changed
        result['sourceFileHashes'] = {file.relative_to(source).as_posix(): digest for file, digest in files.items()}
        (evidence / f'upstream-net{runtime}-result.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'debugger', 'dotnet', 'work', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('runtime', 'sdk', 'arch'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    result = run(args.source.resolve(), args.debugger.resolve(), args.dotnet.resolve(), args.runtime, args.sdk, args.arch,
                 args.work.resolve(), args.evidence.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != 'sourceFileHashes'}, ensure_ascii=False))
    sys.exit(0 if result['success'] else 1)
