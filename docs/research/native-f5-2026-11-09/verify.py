"""Validate the retained startup failure, without launching any check or editor."""
from datetime import datetime, timedelta
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

BASE = '2951f3478fba30d07a067e28a2c4bd5781f87a32'
SOURCE = '6a8b8431dfa7879ed65c8b2170dab91b946a13b9'
MODULE = 'scripts/variant/file-based-apps/'
CHANGED = {'scripts/variant/lifecycle/' + name for name in ('prepare.py', 'run.ps1', 'extension-test.cjs')} | {'scripts/variant/test_lifecycle_preparation.py'}
PINS = {
    'checks/record.json': 'fcb4240d33b08891b203e4432f7f08a179a55bafe0eaea7de69ce885fec49143',
    'preparation.json': '0d9aed778ecd28b5fdcbeaeb5d50cc3ca64d9693a4a0356b2d243e0f6d23876a',
    'native-run-before.json': '8232ceffc6bb5999cfc710a3349a4bddde639c8e3819edfc899b626451337e8c',
    'native-run-result.json': '009e16fe8d44ad99b353f3821e44147f7bca55a8bff26e55497354053363c973',
    'verifier-inputs/manifest.json': '4770236225c65861cd47b905edfb8484852d3fdfd950302c0fe17b4eaa6fc127',
    'n01/attempt.json': 'f384bfa6e84ea2528a693fb0d2bd876f5c5699f996ceacd61f5443fbafcf49c8',
    'n01/launch.json': '4b27c33c756337b5001c6699fd77073260008fb6792769ccac11864ee631c83b',
    'n01/launcher-result.json': '82848334653989e55a5a730a816e4b5d086d62837d45194be839335f482b5a4f',
    'n01/expected.json': 'aa958de11aff2bd73a32129cddf12cf0c576265e51a4847163ba5df659eb6aef',
    'n01/ui/startup-window-observation.json': '23060bc5e6f4df9089f3703cb2e4a086a4fda9b478720398b0e4c90185ca99e7',
    'n01/ui/observation-recorder-source.js': '2d8707e414584e7f2f63617189269955d3b11a35bf415c268455019af523c595',
    'n01/profile/User/settings.json': '49f018a7b2a4e21f212898bb3257c397458b1b83a49f64896a09604cb157a177',
    'n01/workspace/a.cs': '4d865a4bfb51e53379d0c73b306ad27ef7c925e192d2de3e9201f7acc4fd2cb6',
    'n01/workspace/b.cs': '4d865a4bfb51e53379d0c73b306ad27ef7c925e192d2de3e9201f7acc4fd2cb6',
    'n01/workspace/global.json': '5bc559894f23e9573817cddfaa9801374148727d9e1f29f71b07689e2ea9fa77',
    'n01/extensions/extensions.json': '15cb124360fcdd11303b9b503d3f398d05cc7a13cf5a5eb06c549134e382a78e',
    'n01/logs/candidate-install.txt': 'ca13b71adc308b9fb35f2ff31467274fd3b840799157c45620f668692e8c8a38',
    'n01/logs/editor-version.txt': '1ca55e24a51da42b1a6d8dd70bf736c4fe3a8c4fa40b445f548b953f8192bed6',
    'n01/logs/runtime-install.txt': 'eb72d0bf351fe250483100e064fe35d50867f1dbe2c8f497a6f487e55780c250',
    'n01/logs/sdk-version.txt': 'e4e6a678725873a4192c048849cd64d852983991bfcb210a40c3b80cc8fcf2eb',
    'n01/logs/stderr.txt': '45187661bfdbaf350018f1fceb704d9b00fd1aebccb4b5d539b80d19f840494b',
    'n01/logs/stdout.txt': '7eb70257593da06f682a3ddda54a9d260d4fc514f645237f5ca74b08f8da61a6',
    'n01/profile/logs/20261109T164817/cli.log': '4dc3f00562416b7fb40b4f5eab0a1c55ddfade46d2d0b4c708b2b197d0cb08e5',
    'n01/profile/logs/20261109T164818/cli.log': 'a140f404aa448987166c74970a130f0bce855fc83153a967c06ee2f3e5fd0433',
    'n01/driver/package.json': '11108560f11f39411ddb523aeb0ba287609b4423caddfe47c60223323a2657be',
    'preparation-n02.json': 'e628bc4ab01e33099c6106421785171cb51e62637042ed2acde20880fbce632a',
    'native-run-n02-result.json': '71479ba027e3c98886cebb408658e2f9edcbc73a6a5239ce94d6a68cc21430de',
    'n02/result.json': '9b6edd09617236151138ca960cc21d18b83ae73776387d2f3c9402c2a6250d81',
    'n02/trace.jsonl': '474b2d8ea9771ace5178815aa3d4ed1c6e6799392e990d2b753c204764c9e82c',
    'preparation-n03.json': 'eb937d37071b1641b84156d780036fadb192a8e2e22ba1f680917164a57689bb',
    'native-run-n03-result.json': '3c7a57a7e0dfd217e9e56d32aa21ed5dc872a9ee63d638d684cb0fda2305adf2',
    'n03/result.json': '02aac824766ac7c4686731226c74fcf5e0721bcabb87720446fa08f1b8f8bab6',
    'n03/trace.jsonl': '827e81d3af15725bf1b1b4f1a9064f76116dabe22c449c31702f0eb837b76c18',
    'native-key-producer-source.js': 'd150eaa4499fdda39f6ae6f3c9e8aa8dd656c7e088a09411a66ee869f2429d33',
    'acl-readback-after-attempts.json': 'a84b8470f6beb3f73f81fc42f9016ade05571436cd4f615a35041697dbed17d9',
}

def require(ok, message):
    if not ok:
        raise ValueError(message)

def proof(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.utcoffset() == timedelta(0), 'Expected aware UTC')
    return result

def build_summary(root):
    repo, work, inventory = root / 'worktree', root / 'n01', {}
    def read(file, expected=None):
        require(file.is_file() and not file.is_symlink(), 'Missing/nonregular input: ' + str(file))
        data = file.read_bytes()
        if expected:
            require(proof(data) == {k: expected[k] for k in ('bytes', 'sha256')}, 'Binding differs: ' + str(file))
            if 'path' in expected:
                require(Path(expected['path']) == file, 'Recorded path differs')
        inventory[str(file)] = proof(data)
        return data
    def load(file):
        return json.loads(read(file).decode('utf-8-sig'))
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo)
    for name, sha in PINS.items():
        require(proof(read(root / name))['sha256'] == sha, 'Frozen input differs: ' + name)
    checks, prep, run = [load(root / name) for name in ('checks/record.json', 'preparation.json', 'native-run-result.json')]
    expected, launch, launcher = [load(work / name) for name in ('expected.json', 'launch.json', 'launcher-result.json')]
    manifest = load(root / 'verifier-inputs/manifest.json')
    read(Path(manifest['helper']['path']), manifest['helper'])
    require(manifest['originalBefore'] == manifest['originalAfter'] and manifest['executionPathsUnchanged'] is True, 'Capture changed')
    originals, retained, checked_inputs = {}, {}, {}
    for name, pair in manifest['copies'].items():
        original, copy = pair['recordedOriginal'], pair['retained']
        require(manifest['originalBefore'][name] == original and proof(read(Path(copy['path']), copy)) == {k: original[k] for k in ('bytes', 'sha256')}, 'Verifier copy differs')
        originals[name], retained[name] = original, copy
        checked_inputs[name] = {'originalPath': original['path'], 'retainedPath': copy['path'], **{k: original[k] for k in ('bytes', 'sha256')}}
    shell = checks['shell']
    read(Path(shell['retainedPath']), shell)
    originals['powershell'] = {'path': shell['originalPath'], **{k: shell[k] for k in ('bytes', 'sha256')}}
    retained['powershell'] = {'path': shell['retainedPath'], **{k: shell[k] for k in ('bytes', 'sha256')}}
    def snapshot(value, kind):
        wanted = checked_inputs if kind == 'checks' else {k: v for k, v in originals.items() if kind == 'run' or k != 'powershell'}
        require(value['executables'] == wanted, 'Original execution identities differ')
        if kind != 'run':
            require({k: value['manifest'][k] for k in ('bytes', 'sha256')} == proof(read(root / 'verifier-inputs/manifest.json')), 'Manifest snapshot differs')
        if kind == 'prep':
            require(value['shell'] == shell, 'PowerShell identity differs')
        require(stamp(manifest['capturedUtc']) <= stamp(value['checkedUtc']), 'Run predates capture')
        return stamp(value['checkedUtc'])
    require(set(git('diff', '--name-only', BASE, SOURCE).decode().splitlines()) == CHANGED, 'Code commit scope differs')
    paths = set(git('ls-tree', '-r', '--name-only', SOURCE, 'scripts/variant').decode().splitlines())
    sources = checks['sourceBefore']
    require(len(paths) == 53 and set(sources) == paths and checks['sourceAfter'] == sources, 'Source set or post-run hashes differ')
    for name in sorted(paths):
        data = read(repo / name, sources[name])
        require(read(root / 'checks/source' / name, sources[name]) == data, 'Source archive differs')
        require(data.replace(b'\r\n', b'\n') == git('show', SOURCE + ':' + name).replace(b'\r\n', b'\n'), 'Git source differs')
        if name not in CHANGED:
            require(git('show', BASE + ':' + name) == git('show', SOURCE + ':' + name), 'Unchanged variant source differs')
    for value in (prep['sourceBefore'], prep['sourceAfter'], run['sourceBefore'], run['sourceAfter']):
        require(value == {name: {'path': str(repo / name), **sources[name]} for name in sources}, 'Preparation/native sources differ')
    for folder, key, name in ((root / 'checks', 'runner', 'run-harness-checks.py'), (root, 'helper', 'prepare-native-f5.py'), (root, 'helper', 'run-native-f5.py')):
        record = checks if key == 'runner' else prep if name.startswith('prepare') else run
        read(folder / name, record[key])
    require(checks['runner'] == checks['runnerAfter'], 'Check runner changed')
    read(root / 'capture-verifier-inputs.py', manifest['helper'])
    require(checks['baseCommit'] == BASE and checks['worktree'] == str(repo) and prep['sourceCommit'] == SOURCE, 'Record identity differs')
    before = dict(checks)
    for key in ('sourceAfter', 'inputsAfter', 'runnerAfter', 'completedUtc'):
        before.pop(key)
    before['runs'] = []
    require(load(root / 'checks/before.json') == before, 'Checks before record differs')
    require([item['name'] for item in checks['runs']] == ['javascript-syntax', 'python', 'powershell-parse'], 'Check set differs')
    for item in checks['runs']:
        require(load(root / 'checks' / (item['name'] + '-result.json')) == item and item['exitCode'] == 0 and item['cwd'] == str(repo), 'Check result differs')
        require(snapshot(item['inputsBefore'], 'checks') <= stamp(item['startedUtc']) <= stamp(item['completedUtc']) <= snapshot(item['inputsAfter'], 'checks'), 'Check time order differs')
        read(root / 'checks' / item['log']['file'], item['log'])
        require(Path(item['argv'][0]) == Path(originals['python' if item['name'] == 'python' else 'node' if item['name'] == 'javascript-syntax' else 'powershell']['path']), 'Check executable differs')
    python_log = (root / 'checks/python.log').read_text(encoding='utf-8')
    require(re.search(r'^Ran 40 tests in [\d.]+s\s+OK\s*$', python_log, re.M), 'Expected Python 40 PASS')
    require('test_native_f5_control_has_two_distinct_input_receipts_in_one_fresh_profile' in python_log, 'New preparation case missing')
    for value in (checks, prep, run):
        kind = 'checks' if value is checks else 'prep' if value is prep else 'run'
        require(snapshot(value['inputsBefore'], kind) <= stamp(value.get('startedUtc', value.get('beganUtc'))) <= stamp(value['completedUtc']) <= snapshot(value['inputsAfter'], kind), 'Outer time order differs')
    require(prep['exitCode'] == 0 and prep['editorNotRun'] is True and run['exitCode'] == 1, 'Preparation/run outcome differs')
    for record in (prep, run):
        read(Path(record['log']['path']), record['log'])
    read(work / 'expected.json', prep['expected'])
    require(run['expectedBefore'] == run['expectedAfter'] == prep['expected'], 'Expected metadata changed')
    before = {k: v for k, v in run.items() if k not in ('exitCode', 'completedUtc', 'log', 'inputsAfter', 'sourceAfter', 'expectedAfter')}
    require(load(root / 'native-run-before.json') == before, 'Native before record differs')
    candidate = expected['candidate']
    require(prep['candidate'] == candidate and candidate['sourceCommit'] == SOURCE and candidate['localOnly'] is True and candidate['published'] is False, 'Candidate identity differs')
    read(Path(candidate['path']), {'bytes': 73342223, 'sha256': candidate['sha256']})
    identity = {k: candidate[k] for k in ('baseVsixSha256', 'sourceCommit', 'target', 'ownedModules')}
    require(proof(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode())['sha256'] == candidate['buildId'], 'Build ID differs')
    for name, sha in candidate['ownedModules'].items():
        require(sources[MODULE + name]['sha256'] == sha, 'Owned module source differs')
    for name, sha in expected['harness'].items():
        require(sources['scripts/variant/lifecycle/' + name]['sha256'] == sha, 'Harness differs')
    for name in ('driver.cjs', 'extension-test.cjs'):
        read(work / 'driver' / name, sources['scripts/variant/lifecycle/' + name])
    base_file, dependency_file = [Path(item['path']) for item in prep['nativeInputs'][:2]]
    for item in prep['nativeInputs'][:2]:
        read(Path(item['path']), item)
    installed = {}
    with zipfile.ZipFile(base_file) as base, zipfile.ZipFile(candidate['path']) as archive:
        allowed = {'extension/.netcoredbg/' + name for name in candidate['ownedModules']} | {'extension/package.json', 'extension.vsixmanifest'}
        require(len(archive.namelist()) == len(set(archive.namelist())) == 743 and set(archive.namelist()) == set(base.namelist()) | allowed, 'Candidate payload set differs')
        immutable = {name: proof(base.read(name))['sha256'] for name in base.namelist() if name not in allowed}
        require(len(immutable) == candidate['unchangedEntries'] == 736 and proof(json.dumps(immutable, sort_keys=True).encode())['sha256'] == candidate['unchangedPayloadDigest'], 'Immutable payload digest differs')
        require(all(archive.read(name) == base.read(name) for name in immutable), 'Non-owned payload changed')
        require(all(proof(archive.read('extension/.netcoredbg/' + name))['sha256'] == sha for name, sha in candidate['ownedModules'].items()), 'Packaged modules differ')
    def installed_files(at):
        values = {}
        for label, archive_file, directory, count in [('candidate', Path(candidate['path']), at / 'extensions/dotnetdev-kr-custom.csharp-with-netcoredbg-11.7.18004', 742), ('dependency', dependency_file, at / 'extensions/ms-dotnettools.vscode-dotnet-runtime-3.2.0', 26)]:
            with zipfile.ZipFile(archive_file) as archive:
                mapping = {name[10:]: name for name in archive.namelist() if name.startswith('extension/') and not name.endswith('/')}
                mapping['.vsixmanifest'] = 'extension.vsixmanifest'
                files = {file.relative_to(directory).as_posix(): file for file in directory.rglob('*') if file.is_file()}
                extras = set(files) - set(mapping)
                bridge = '''Microsoft.CodeAnalysis.CSharp.Scripting.dll Microsoft.CodeAnalysis.CSharp.dll Microsoft.CodeAnalysis.Scripting.dll Microsoft.CodeAnalysis.dll
Microsoft.Diagnostics.BrowserDebugHost.dll Microsoft.Diagnostics.BrowserDebugHost.pdb Microsoft.Diagnostics.BrowserDebugHost.runtimeconfig.json Microsoft.Diagnostics.BrowserDebugHost.staticwebassets.endpoints.json
Microsoft.Diagnostics.BrowserDebugProxy.dll Microsoft.Diagnostics.BrowserDebugProxy.pdb Microsoft.FileFormats.dll Microsoft.NET.WebAssembly.Webcil.dll Microsoft.SymbolStore.dll
Newtonsoft.Json.dll System.Collections.Immutable.dll System.Reflection.Metadata.dll install.Lock'''.split()
                caches = {'n02': '.roslyn/cache/razor.mef.WhSKc4WZu8LyCYvjOXGl9A.cache', 'n03': '.roslyn/cache/razor.mef.2_jfeM4hQgKunSrw8m1Qwg.cache'}
                allowed_extras = {'.vswebassemblybridge/' + name for name in bridge} | {caches[at.name]} if label == 'candidate' and at.name != 'n01' else set()
                require(set(mapping) <= set(files) and len(mapping) == count and extras == allowed_extras, 'Installed artifact set differs')
                metadata = None
                for name in mapping:
                    file = files[name]
                    actual, original = read(file), archive.read(mapping[name])
                    if name == 'package.json':
                        actual, original = json.loads(actual), json.loads(original)
                        metadata = actual.pop('__metadata')
                        require(isinstance(metadata, dict), 'Installer metadata absent')
                        original.pop('__metadata', None)
                    require(actual == original, 'Installed bytes differ: ' + name)
                values[label] = {'packagedFiles': count, 'observedFiles': len(files), 'additionalFiles': {name: proof(read(files[name])) for name in sorted(extras)}, 'installerMetadata': metadata}
        return values
    installed = installed_files(work)
    require(expected['scenario'] == 'native-f5' and expected['cycles'] == 2 and expected['scope']['hardwareKeypress'] is False, 'Planned scope differs')
    require(launcher['success'] is False and launcher['pid'] == launch['pid'] == 15196 and launcher['editorExitCode'] == -2147483645 and launcher['fixtureShutdown'] == [], 'Failed launcher outcome differs')
    require(launcher['error'] == 'Editor returned without a result; retain logs' and launcher['candidateSha256'] == candidate['sha256'], 'Launcher failure differs')
    require(launch['freshProfile'] is True and launch['visibleWindowRequested'] is True and launch['arguments'][-1].strip('"') == str(work / 'workspace/a.cs'), 'Planned visible file launch differs')
    require(load(work / 'profile/User/settings.json')['files.autoSave'] == 'off', 'Planned autosave setting differs')
    absent = ['result.json', 'trace.jsonl', 'progress/state.json', 'f5-input-closed.json'] + [Path(item[key]).name for item in expected['nativeF5']['inputs'] for key in ('request', 'receipt')]
    require(all(not (work / name).exists() for name in absent), 'Input/readiness/driver evidence unexpectedly exists')
    require({file.relative_to(work).as_posix() for file in (work / 'profile/logs').rglob('*') if file.is_file()} == {'profile/logs/20261109T164817/cli.log', 'profile/logs/20261109T164818/cli.log'}, 'Runtime logs unexpectedly exist')
    stderr = read(work / 'logs/stderr.txt').decode('utf-8-sig')
    require('FATAL:electron\\shell\\browser\\win\\install_dir_access.cc:52' in stderr and 'Sandboxed processes cannot read' in stderr, 'Startup diagnostic differs')
    ui = load(work / 'ui/startup-window-observation.json')
    require(ui['f5KeyInputs'] == 0 and ui['tool'] == 'sky.list_windows' and ui['captureAttempt']['outcome'] == 'error', 'Startup UI record differs')
    require(all(item['app'] == 'process:csrss.exe' for item in ui['returnedErrorWindows']), 'Unexpected UI scope')
    attempts = [{'attempt': 'n01', 'outcome': 'editor-startup-failed-before-input', 'success': False, 'installedFiles': installed,
                 'inputRequests': 0, 'inputReceipts': 0, 'rootAttestedF5Keys': 0, 'driverResult': None,
                 'sessionDAPHTTPAndCleanup': 'not observed; no successful execution or cleanup inferred', 'installedIdentityAndActivation': 'not observed', 'launcher': launcher, 'ui': ui}]
    def embedded(value, external=False):
        data = base64.b64decode(value['base64'], validate=True)
        require(proof(data) == {'bytes': value['size'], 'sha256': value['sha256']}, 'Embedded snapshot differs')
        if external:
            require(read(Path(value['path'])) == data, 'External snapshot differs')
        return data
    def tail(value):
        text = read(Path(value['path'])).decode('utf-8')
        encoded = text.encode('utf-16-le')
        boundary = value['offsetCharacters'] * 2
        prefix = encoded[:boundary].decode('utf-16-le', 'replace')
        require(proof(prefix.encode())['sha256'] == value['prefixSha256'], 'Historical log prefix differs')
        end = boundary + value['tailCharacters'] * 2 if 'tailCharacters' in value else None
        result = encoded[boundary:end].decode('utf-16-le', 'replace')
        if 'tailSha256' in value:
            require(proof(result.encode())['sha256'] == value['tailSha256'], 'Historical log span differs')
        return result
    for number in ('02', '03'):
        at = root / ('n' + number)
        p, r, exp, result, launched, outer = [load(file) for file in (root / ('preparation-n' + number + '.json'), root / ('native-run-n' + number + '-result.json'), at / 'expected.json', at / 'result.json', at / 'launch.json', at / 'launcher-result.json')]
        require(p['exitCode'] == 0 and p['editorNotRun'] is True and p['sourceCommit'] == SOURCE, 'Later preparation differs')
        for record in (p, r):
            require(record['sourceBefore'] == record['sourceAfter'] == prep['sourceAfter'], 'Later source binding differs')
            require(snapshot(record['inputsBefore'], 'prep' if record is p else 'run') <= stamp(record['startedUtc']) <= stamp(record['completedUtc']) <= snapshot(record['inputsAfter'], 'prep' if record is p else 'run'), 'Later time order differs')
            read(Path(record['helper']['path']), record['helper'])
            read(Path(record['log']['path']), record['log'])
        require(r['argv'] == [*run['argv'][:6], str(at), *run['argv'][7:]] and r['requestedExecutionContext'] == 'require_escalated', 'Later execution request differs')
        require(r['expectedBefore'] == r['expectedAfter'] == p['expected'], 'Later expected binding changed')
        prior = {k: v for k, v in r.items() if k not in ('exitCode', 'completedUtc', 'log', 'inputsAfter', 'sourceAfter', 'expectedAfter')}
        require(load(root / ('native-run-n' + number + '-before.json')) == prior, 'Later before record differs')
        reuse = p['candidateReuse']
        generated = read(Path(reuse['retainedGeneratedCandidate']['path']), reuse['retainedGeneratedCandidate'])
        require(proof(generated) == {k: reuse['generatedCandidateBefore'][k] for k in ('bytes', 'sha256')}, 'Generated archive historical binding differs')
        generated_expected = json.loads(read(Path(reuse['expectedBefore']['path']), reuse['expectedBefore']))
        require(generated_expected['candidate']['sha256'] == proof(generated)['sha256'] and reuse['semanticChanges'] == ['candidate.sha256'], 'Reuse delta differs')
        generated_expected['candidate']['sha256'] = candidate['sha256']
        require(generated_expected == exp and exp == result['expected'] and exp['harness'] == expected['harness'], 'Expected semantic reuse differs')
        read(Path(reuse['expectedAfter']['path']), reuse['expectedAfter'])
        require(read(Path(reuse['reusedFrom']['path']), reuse['reusedFrom']) == read(Path(reuse['candidateAfter']['path']), reuse['candidateAfter']), 'Exact ZIP reuse differs')
        require({k: v for k, v in exp['candidate'].items() if k != 'path'} == {k: v for k, v in candidate.items() if k != 'path'}, 'Candidate identity differs across attempts')
        with zipfile.ZipFile(Path(reuse['retainedGeneratedCandidate']['path'])) as generated_zip, zipfile.ZipFile(candidate['path']) as used_zip:
            require(generated_zip.namelist() == used_zip.namelist() and all(generated_zip.read(name) == used_zip.read(name) for name in used_zip.namelist()), 'Generated/reused uncompressed payload differs')
        require(p['nativeInputs'] == prep['nativeInputs'] and p['traceImplementation'] == prep['traceImplementation'], 'Recorded native inputs differ')
        require(result['safetyTimeoutMilliseconds'] == 90000 and result['editorApiVersion'] == '1.143.1' and result['installedModules'] == candidate['ownedModules'], 'Runtime identity or threshold differs')
        require(result['scope']['targetCommandApiLaunch'] is False and result['scope']['hardwareKeypress'] is False and result['scope']['noFolderWindow'] is True, 'Runtime scope differs')
        require(Path(result['installedExtension']['path']) == at / 'extensions/dotnetdev-kr-custom.csharp-with-netcoredbg-11.7.18004' and result['installedExtension']['build']['lifecycleBuildId'] == candidate['buildId'], 'Loaded candidate differs')
        require(Path(result['installedDependency']['path']) == at / 'extensions/ms-dotnettools.vscode-dotnet-runtime-3.2.0', 'Loaded dependency differs')
        trace = [json.loads(line) for line in read(at / 'trace.jsonl').decode().splitlines()]
        require(all(a['atMilliseconds'] <= b['atMilliseconds'] for a, b in zip(trace, trace[1:])), 'Trace order differs')
        inputs, observed = result['nativeF5']['inputs'], []
        require(len(inputs) == (1 if number == '02' else 2) and len(result['launches']) == len(inputs), 'Observed input/launch count differs')
        for item, owned in zip(inputs, result['launches']):
            request, receipt = item['request'], item['receipt']
            for key in ('profileSnapshot', 'requestSnapshot', 'receiptSnapshot', 'observationSnapshot', 'inputRecordSnapshot'):
                embedded(item[key], external=key != 'profileSnapshot')
            require(json.loads(embedded(item['requestSnapshot'])) == request and json.loads(embedded(item['receiptSnapshot'])) == receipt, 'Request/receipt objects differ')
            require(request['workspaceFolders'] == [] and request['activeDebugSessionId'] is None and request['languageId'] == 'csharp', 'Input context differs')
            require(Path(request['activeSource']) == Path(request['source']) == at / 'workspace/a.cs' and request['nonce'] == exp['nativeF5']['nonce'], 'Input source/nonce differs')
            require(all(receipt[key] == request[key] for key in ('nonce', 'sequence', 'launchToken', 'windowTitle', 'action', 'key', 'mechanism')), 'Input attestation differs')
            require(receipt['requestSha256'] == item['requestSnapshot']['sha256'] and stamp(request['requestedAtUtc']) <= stamp(receipt['inputAtUtc']) <= stamp(request['expiresAtUtc']), 'Input lease/hash differs')
            key_record = json.loads(embedded(item['inputRecordSnapshot']))
            require(key_record['tool'] == receipt['tool'] == 'sky.press_key' and key_record['arguments']['key'] == 'F5' and key_record['keyCallReturned'] is True, 'Native key record differs')
            require('producerSha256' not in key_record if number == '02' else key_record['producerSha256'] == PINS['native-key-producer-source.js'], 'Retained input producer schema differs')
            require(key_record['arguments']['window']['id'] == receipt['windowId'] and request['windowTitle'] in receipt['observedWindowTitle'], 'Native window attestation differs')
            observation = json.loads(embedded(item['observationSnapshot']))
            require(observation['imagePayloadRetained'] is False, 'Unexpected retained image claim')
            read(Path(key_record['afterObservationPath']))
            embedded(request['diskBefore'])
            profile = json.loads(embedded(item['profileSnapshot']))['profiles']['LifecycleHttp']
            require(profile['environmentVariables']['LIFECYCLE_TOKEN'] == owned['nonce'] == request['launchToken'] and profile['applicationUrl'] == owned['origin'] and profile['launchBrowser'] is False, 'Profile/token differs')
            renderer = tail(item.get('route', item['rendererBefore']))
            dispatches = [line for line in renderer.splitlines() if re.search(r'KeybindingService#dispatch\s+F5\s+\[ Will dispatch command netcoredbg\.debugActiveFile \]', line)]
            commands = [line for line in renderer.splitlines() if re.search(r'CommandService#executeCommand\s+netcoredbg\.debugActiveFile\s*$', line)]
            require(len(dispatches) == len(commands) == 1, 'Independent native route differs')
            tail(item['outputBefore'])
            detail = {'sequence': item['sequence'], 'inputAtUtc': receipt['inputAtUtc'], 'requestToInputSeconds': (stamp(receipt['inputAtUtc']) - stamp(request['requestedAtUtc'])).total_seconds(), 'rendererDispatch': dispatches[0], 'targetCommand': commands[0], 'isDirtyBefore': request['isDirty']}
            if number == '03':
                require(item['route']['f5Dispatches'] == dispatches and item['route']['targetCommands'] == commands and len(item['builds']) == 1, 'Captured route/build differs')
                require(item['breakpoint']['line'] == 5 and item['breakpoint']['result'] == '40' and Path(item['breakpoint']['source']) == Path(request['source']), 'Breakpoint differs')
                require(item['response'] == owned['response'] == {'pid': owned['pid'], 'nonce': owned['nonce'], 'revision': owned['revision'], 'value': 42}, 'Owned HTTP response differs')
                require(len(owned['capturedSessions']) == 1 and owned['capturedSessions'][0]['terminated'] is True and owned['capturedSessions'][0]['sessionId'] == owned['sessionId'], 'Exact terminal session differs')
                require(owned['startedAtMilliseconds'] <= owned['stopRequestedAtMilliseconds'] <= owned['terminatedAtMilliseconds'] <= owned['pidGoneAtMilliseconds'] <= owned['portReusableAtMilliseconds'] <= owned['outputRemovedAtMilliseconds'], 'Resource observations differ')
                require(not Path(owned['output']).exists(), 'Owned output remains')
                require(item['diskAfter']['sha256'] == request['bufferBefore']['sha256'], 'Saved buffer differs')
                embedded(item['diskAfter'])
                if item['sequence'] == 2:
                    require(request['isDirty'] is True and len(item['savedEvents']) == 1 and request['diskBefore']['sha256'] != item['diskAfter']['sha256'], 'Dirty save witness differs')
                    embedded(item['savedEvents'][0]['disk'])
                else:
                    require(request['isDirty'] is False and request['diskBefore']['sha256'] == request['bufferBefore']['sha256'], 'Saved first input differs')
                messages = [entry['detail']['message'] for entry in trace if entry['event'] == 'dap-receive' and entry['detail'].get('sessionId') == owned['sessionId']]
                require(any(message.get('event') == 'process' and message['body'].get('systemProcessId') == owned['pid'] for message in messages) and any(message.get('event') == 'stopped' and message['body'].get('reason') == 'breakpoint' for message in messages), 'DAP PID/breakpoint differs')
                sent = [entry['detail']['message'] for entry in trace if entry['event'] == 'dap-send' and entry['detail'].get('sessionId') == owned['sessionId']]
                evaluates = [message for message in sent if message.get('command') == 'evaluate' and message.get('arguments', {}).get('expression') == 'marker']
                require(len(evaluates) == 1 and any(message.get('request_seq') == evaluates[0]['seq'] and message.get('success') is True and message.get('body', {}).get('result') == '40' for message in messages), 'Correlated DAP evaluation differs')
                require(any(entry['event'] == 'http-ready' and entry['detail']['label'] == owned['label'] and entry['detail']['body'] == owned['response'] for entry in trace), 'HTTP trace differs')
                require(any(entry['event'] == 'editor-terminate' and entry['detail']['sessionId'] == owned['sessionId'] for entry in trace) and any(entry['event'] == 'owned-resources-released' and entry['detail']['pid'] == owned['pid'] and Path(entry['detail']['output']) == Path(owned['output']) for entry in trace), 'Terminal/resource trace differs')
                detail.update(sessionId=owned['sessionId'], pid=owned['pid'], revision=owned['revision'], output=owned['output'], breakpoint=item['breakpoint'], response=item['response'], resourceObservations={k: v for k, v in owned.items() if k.endswith('AtMilliseconds')})
            observed.append(detail)
        closed = load(Path(exp['nativeF5']['closed']))
        require(closed['nonce'] == exp['nativeF5']['nonce'], 'Closed gate differs')
        files = installed_files(at)
        for directory in ('logs', 'ui', 'profile/logs'):
            for file in (at / directory).rglob('*'):
                if file.is_file():
                    read(file)
        for name in ('launch.json', 'launcher-result.json', 'expected.json', 'attempt.json'):
            read(at / name)
        if number == '02':
            require(r['exitCode'] == 1 and result['success'] is False and 'Safety timeout' in result['firstFailure']['error'] and result['cleanup'] == [{'label': 'F5-1'}], 'n02 first failure differs')
            require(result['launches'][0]['capturedSessions'] == [] and result['nativeF5']['postStartApiActions'] == [], 'n02 partial coverage differs')
            require(not Path(exp['nativeF5']['inputs'][1]['request']).exists() and not Path(exp['nativeF5']['inputs'][1]['receipt']).exists(), 'n02 second input unexpectedly exists')
            require(observed[0]['requestToInputSeconds'] == 85.247, 'n02 operator wait differs')
            attempts.append({'attempt': 'n02', 'outcome': 'harness-window-failed-after-one-observed-native-route', 'success': False, 'installedFiles': files, 'installedIdentityAndActivation': 'passed driver checks', 'inputs': observed, 'firstFailure': result['firstFailure'], 'cleanup': 'not demonstrated', 'secondsFromKeyToFailure': (stamp(closed['closedAtUtc']) - stamp(inputs[0]['receipt']['inputAtUtc'])).total_seconds()})
        else:
            require(r['exitCode'] == 0 and result['success'] is True and outer['success'] is True and outer['editorExitCode'] == 0 and not result.get('firstFailure') and result['cleanup'] == [], 'n03 control outcome differs')
            require(len(result['phases']) == 7 and all(phase['outcome'] == 'passed' for phase in result['phases']), 'n03 phases differ')
            require(all(len({owned[key] for owned in result['launches']}) == 2 for key in ('nonce', 'sessionId', 'output', 'pid')), 'n03 launches are not distinct')
            require(result['launches'][0]['outputRemovedAtMilliseconds'] < result['launches'][1]['startedAtMilliseconds'], 'n03 repeat preceded cleanup')
            require(read(at / 'workspace/a.cs') == embedded(inputs[-1]['diskAfter']), 'Final source differs from saved retry')
            require(len([entry for entry in trace if entry['event'] == 'adapter-error' and entry['detail']['error'] == 'Error: read error']) == 2, 'Retained adapter diagnostics differ')
            attempts.append({'attempt': 'n03', 'outcome': 'two-native-input-http-control-passed', 'success': True, 'installedFiles': files, 'installedIdentityAndActivation': 'passed driver checks', 'elapsedMillisecondsIncludingOperatorWait': result['elapsedMilliseconds'], 'inputs': observed, 'cleanup': 'exact-session/PID/port/output/queue checks passed', 'adapterReadErrorsAfterStop': 2})
    read(root / 'native-key-producer-source.js')
    readback = load(root / 'acl-readback-after-attempts.json')
    require(stamp(readback['capturedUtc']) > stamp(r['completedUtc']) and all(item['allS1_15Count'] == 0 and item['readSucceeded'] is True for item in readback['paths']), 'After-attempt ACL observation differs')
    csharp = list((root / 'n03/profile/logs').rglob('C#.log'))
    lsp = list((root / 'n03/profile/logs').rglob('C# LSP Trace Logs.log'))
    require(len(csharp) == len(lsp) == 1, 'Expected language-service logs')
    require(proof(read(csharp[0]))['sha256'] == '9ed8538e13271156b5174fd93f0d67af6760a0a2ae73563aa1c7fac34a10c4ec' and proof(read(lsp[0]))['sha256'] == '3aea9e5c3d3fcf89ff8f42a5de82ebd408c6ce4b65e8d68c74c39bc2616eaeb2', 'Retained language-service logs differ')
    require(sum('NU1100' in line for line in read(csharp[0]).decode('utf-8').splitlines()) == 27 and 'There were problems loading project a.cs. See log for details.' in read(lsp[0]).decode('utf-8'), 'Retained language-service failures differ')
    for config in (root / 'n03/appdata/NuGet/NuGet.Config', root / 'n03/workspace/NuGet.Config'):
        require('<packageSources><clear /></packageSources>' in read(config).decode('utf-8'), 'Offline fixture configuration differs')
    return {'schema': 1, 'outcome': 'mixed-recorded-outcomes', 'allAttemptsPassed': False, 'baseCommit': BASE, 'sourceCommit': SOURCE,
            'checks': {'python': 40, 'javascriptSyntax': 'PASS', 'powershellParse': 'PASS', 'productFileAppSuiteRerun': False, 'archivedVariantSources': 53},
            'changedSourceFiles': {name: sources[name] for name in sorted(CHANGED)}, 'unchangedProductModules': candidate['ownedModules'],
            'candidate': candidate, 'installedArtifacts': installed, 'preflightEditor': expected['editor'], 'preflightSDK': expected['sdk'], 'nativeInputBindingsRecordedAtPreparation': prep['nativeInputs'],
            'attempts': attempts, 'languageService': {'NU1100Lines': 27, 'projectLoadErrorToastRetained': True, 'fixturePackageSourcesCleared': True, 'qualified': False}, 'postAttemptACLReadback': readback, 'originalExecutableIdentities': originals, 'retainedExecutableReadPaths': retained,
            'limits': 'EXE bytes only; original cache executables are not read. n01/n02 remain FAIL. Requested execution context and fresh-profile differences do not prove a unique cause. UI records are attestations/metadata; no screenshot pixels are retained. LSP and full qualification remain open.',
            'files': {name: inventory[name] for name in sorted(inventory) if not any(part in name.replace('\\', '/') for part in ('/extensions/', '/checks/source/', '/worktree/scripts/variant/'))}}

if __name__ == '__main__':
    require(len(sys.argv) <= 2, 'Usage: verify.py [ARTIFACT_ROOT]')
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parents[4]
    sys.stdout.buffer.write((json.dumps(build_summary(root), indent=2) + '\n').encode('utf-8'))
