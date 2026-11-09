"""Standalone retained-evidence verifier; never produces a new native observation."""
import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

BASE = '6d438a5b603ca416698d8c6071394e141cb46e5d'
SOURCE = '1709198d4262dd3b7f58a59d9d01d36e11f5d76f'
FAILED_SOURCE = 'df9899ea4e881fcc4569eb81298833b14338f7d2'
CHANGED = {'scripts/variant/lifecycle/' + name for name in ('prepare.py', 'run.ps1', 'extension-test.cjs')} | {'scripts/variant/test_lifecycle_preparation.py'}
MODULE = 'scripts/variant/file-based-apps/'
EXE_HASHES = {'node': '8e55f00a0aca4c8d71ff6f68aa6285118fad18c29c0482973cc03ee5f0c2a98b',
              'python': '8fc34e1314ae172c7841832ae7c63ce3d59eb7394b3ca317d69c803f93ea5660'}
PINS = {
    'series-plan.json': 'e7a94973ca02438c9b9e0cac914b6539b45698ae562ff4ab52f3f9bb3b93520f',
    'verifier-inputs/manifest.json': '774344fbf6680bb7c85b9dc9e137263190b354a0542e33258c99a58acc61b49f',
    'checks/record.json': '4865041015fbd47d8f945427e3d7647e50b98feb0b21019da2ae4895083d2d42',
    'preparation-r01.json': '115d0aa410ce1141a367ba9bfe6af2342cf996e4a156a572d769d97fc5da7889',
    'native-run-r01-result.json': 'bdd055a2c3fe7490c1157461d84c9c107643df4a50143898466e69e8475cb086',
    'operator-observation-failure.json': '91514e7c367f4c5299edade407ad15f1db379a2a972612946726481384cdec1c',
    'series-stop.json': 'ba9c0ec2648e7b4c1ef6d0ea6706982a8dd22931ee0ab1bed5b8b03784e3b5f5',
    'r01/result.json': 'a3c52289af6b489787de2688a528bca36ad5f9c943a5ada36f7973e1feafbd67',
    'r01/trace.jsonl': '784dd8e40d629601173e7914c7c0b940348c5683570d2fe8faaa3da482738c0c',
}
FAILED_PINS = {
    'series-plan.json': 'c5d09ead888212c928cd31625b5a03336c259c904fa0314d91eb2a094776e693',
    'checks/record.json': 'd27a4ffb42877b4c05762cbda212f29ece25b43c40e94b9bcabf7daf839de66d',
    'preparation-r01.json': 'c6c644e5c9fd5b6043c2f54f7e799517ff23d69d5e2628557e63ef0fbb124a8d',
    'native-run-r01-before.json': 'e0c3f7ad6f2ece26d332b378b8c4c0f4f28ef1d0cf72e81ee5150ef0afaae15d',
    'native-run-r01-result.json': '013176833a3b0e74b1e578287faad9bffcf4d6d07310326e896910fd36983ef3',
    'series-stop.json': 'ff87876ae403d311504b27936176b31bbf4453578c1119db1571c1749a188dd9',
    'system-architecture-readback.json': 'da40bbd386180eaade1d00e6d1f9bebc9f7e6403f0e3b220a351398df84e1d44',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def proof(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def stamp(value):
    # Original receipts contain both +00:00 and +09:00. Compare aware instants
    # without rewriting or discarding their recorded offsets.
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None and result.utcoffset() is not None, 'Naive recorded time')
    return result


class Evidence:
    def __init__(self, root):
        self.root, self.repo = Path(root), Path(root) / 'worktree'
        self.inventory, self.blocked = {}, set()

    def read(self, file, binding=None, recorded_path=True):
        file = Path(file)
        # This lexical check precedes filesystem access. Actual execution argv
        # identities are verified from receipts; mutable original EXEs are not read.
        require(str(file).casefold() not in self.blocked, 'Original verifier EXE read forbidden')
        require(file.is_file() and not file.is_symlink(), 'Missing/nonregular input: ' + str(file))
        data = file.read_bytes()
        if binding:
            require(proof(data) == {key: binding[key] for key in ('bytes', 'sha256')}, 'Binding differs: ' + str(file))
            if recorded_path and 'path' in binding:
                require(Path(binding['path']) == file, 'Recorded path differs: ' + str(file))
        self.inventory[str(file)] = proof(data)
        return data

    def load(self, file):
        return json.loads(self.read(file).decode('utf-8-sig'))

    def bound(self, binding):
        return self.read(Path(binding['path']), binding)

    def pins(self, values):
        for name, sha in values.items():
            require(proof(self.read(self.root / name))['sha256'] == sha, 'Frozen input differs: ' + name)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo)

    def embedded(self, value, external=False):
        data = base64.b64decode(value['base64'], validate=True)
        require(proof(data) == {'bytes': value['size'], 'sha256': value['sha256']}, 'Embedded snapshot differs')
        if external:
            require(self.read(Path(value['path'])) == data, 'External snapshot differs')
        return data

    def tail(self, value):
        # JS string offsets count UTF-16 units; read_bytes avoids Windows newline
        # normalization before checking the original prefix and observed span.
        units = self.read(Path(value['path'])).decode('utf-8').encode('utf-16-le')
        boundary = value['offsetCharacters'] * 2
        prefix = units[:boundary].decode('utf-16-le', 'replace')
        require(proof(prefix.encode())['sha256'] == value['prefixSha256'], 'Historical log prefix differs')
        end = boundary + value['tailCharacters'] * 2 if 'tailCharacters' in value else None
        tail = units[boundary:end].decode('utf-16-le', 'replace')
        if 'tailSha256' in value:
            require(proof(tail.encode())['sha256'] == value['tailSha256'], 'Historical log span differs')
        return tail

    def inputs(self, checks):
        manifest_file = self.root / 'verifier-inputs/manifest.json'
        manifest = self.load(manifest_file)
        require(manifest['executionPathsUnchanged'] is True and manifest['originalBefore'] == manifest['originalAfter'], 'Capture original identities differ')
        require(set(manifest['copies']) == {'node', 'python'}, 'Verifier capture set differs')
        originals, retained = {}, {}
        for name in ('node', 'python'):
            original, copy = [manifest['copies'][name][key] for key in ('recordedOriginal', 'retained')]
            self.blocked.add(str(Path(original['path'])).casefold())
            require(original == manifest['originalBefore'][name] and original['sha256'] == EXE_HASHES[name], 'Original executable identity differs')
            require(proof(self.bound(copy)) == {key: original[key] for key in ('bytes', 'sha256')}, 'Retained EXE differs')
            originals[name], retained[name] = original, copy
        shell = checks['shell']
        self.blocked.add(str(Path(shell['originalPath'])).casefold())
        shell_binding = {'path': shell['retainedPath'], **{key: shell[key] for key in ('bytes', 'sha256')}}
        self.bound(shell_binding)
        originals['powershell'] = {'path': shell['originalPath'], **{key: shell[key] for key in ('bytes', 'sha256')}}
        retained['powershell'] = shell_binding
        self.bound(manifest['helper'])
        self.bound(manifest['common'])
        self.originals, self.retained, self.manifest, self.shell = originals, retained, manifest, shell
        self.manifest_proof = {'path': str(manifest_file), **proof(self.read(manifest_file))}
        return {'manifest': self.manifest_proof, 'originalExecutionIdentities': originals,
                'retainedReadPaths': retained, 'captureTime': manifest['capturedUtc'],
                'limits': 'EXE bytes only; no complete runnable runtime, standard library, OS or effective-token archive.'}

    def snapshot(self, value, shell=False):
        wanted = self.originals if shell else {key: self.originals[key] for key in ('node', 'python')}
        require(value['executables'] == wanted and value['manifest'] == self.manifest_proof, 'Execution/input snapshot differs')
        if shell:
            require(value['shell'] == self.shell, 'PowerShell snapshot differs')
        require(stamp(value['checkedUtc']) >= stamp(self.manifest['capturedUtc']), 'Snapshot precedes retention')
        return stamp(value['checkedUtc'])

    def source(self, checks, commit):
        require(checks['baseCommit'] == BASE and checks['sourceCommit'] == commit and Path(checks['worktree']) == self.repo, 'Checks source identity differs')
        paths = set(self.git('ls-tree', '-r', '--name-only', commit, 'scripts/variant').decode().splitlines())
        sources = checks['sourceBefore']
        require(len(paths) == 53 and set(sources) == paths and checks['sourceAfter'] == sources, 'Source set/prepost differs')
        require(set(self.git('diff', '--name-only', BASE, commit).decode().splitlines()) == CHANGED, 'Product/harness commit scope differs')
        for name in sorted(paths):
            data = self.read(self.repo / name, sources[name])
            require(data == self.read(self.root / 'checks/source' / name, sources[name], False), 'Archived source differs')
            require(data.replace(b'\r\n', b'\n') == self.git('show', commit + ':' + name).replace(b'\r\n', b'\n'), 'Committed source differs')
            if name not in CHANGED:
                require(self.git('show', BASE + ':' + name) == self.git('show', commit + ':' + name), 'Unchanged product/helper differs')
        self.sources = sources
        return {'commit': commit, 'archivedVariantSources': len(sources),
                'changedFiles': {name: sources[name] for name in sorted(CHANGED)},
                'unchangedProductModules': {name[len(MODULE):]: sources[name] for name in sorted(sources) if name.startswith(MODULE) and name[len(MODULE):] in ('entry.cjs', 'runtime.cjs', 'classify.cjs', 'web.cjs', 'recovery.cjs')}}

    def boundaries(self, record, start_key='startedUtc', shell=True):
        require(record['sourceBefore'] == record['sourceAfter'] == self.sources, 'Recorded sources changed')
        before, after = self.snapshot(record['inputsBefore'], shell), self.snapshot(record['inputsAfter'], shell)
        start, end = stamp(record[start_key]), stamp(record['completedUtc'])
        if start_key == 'beganUtc':
            # The checks helper samples inputsAfter before its final completedUtc;
            # prep/native helpers deliberately record completedUtc first.
            require(before <= start <= max(stamp(run['completedUtc']) for run in record['runs']) <= after <= end, 'Checks execution time order differs')
        else:
            require(before <= start <= end <= after, 'Recorded execution time order differs')
        for key, after in (('helper', 'helperAfter'), ('runner', 'runnerAfter'), ('common', 'commonAfter'), ('plan', 'planAfter')):
            if key in record:
                require(record[key] == record[after], 'Recorded helper/plan changed')
                self.bound(record[key])
        require(record.get('consistencyErrors', []) == [], 'Recorded consistency check failed')
        if record.get('log'):
            self.bound(record['log'])

    def checks(self, record, extra_binding=False):
        self.boundaries(record, 'beganUtc', False)
        names = ['javascript-syntax', 'python', 'powershell-parse']
        if extra_binding:
            names.append('powershell-parameter-binding')
        require(record['success'] is True and [run['name'] for run in record['runs']] == names, 'Frozen checks differ')
        initial = {key: val for key, val in record.items() if key not in ('sourceAfter', 'inputsAfter', 'runnerAfter', 'commonAfter', 'planAfter', 'completedUtc', 'success')}
        initial['runs'] = []
        require(self.load(self.root / 'checks/before.json') == initial, 'Checks initial record differs')
        self.read(self.root / 'checks/run-harness-checks.py', record['runner'], False)
        results = []
        for run in record['runs']:
            require(self.load(self.root / 'checks' / (run['name'] + '-result.json')) == run, 'Individual check receipt differs')
            require(run['exitCode'] == 0 and Path(run['cwd']) == self.repo, 'Check execution differs')
            require(self.snapshot(run['inputsBefore']) <= stamp(run['startedUtc']) <= stamp(run['completedUtc']) <= self.snapshot(run['inputsAfter']), 'Check time order differs')
            name = 'python' if run['name'] == 'python' else 'node' if run['name'] == 'javascript-syntax' else 'powershell'
            require(Path(run['argv'][0]) == Path(self.originals[name]['path']), 'Check executable path differs')
            log = self.bound(run['log']).decode('utf-8-sig')
            if name == 'python':
                require(run['argv'][1:] == ['-B', '-m', 'unittest', 'discover', '-s', 'scripts/variant', '-p', 'test_*.py', '-v'], 'Python test selection differs')
                require(re.search(r'^Ran 41 tests in [\d.]+s\s+OK\s*$', log, re.M), 'Expected 41 preparation/unit cases')
            elif name == 'node':
                require(run['argv'][1:] == ['--check', 'scripts/variant/lifecycle/extension-test.cjs'], 'JavaScript check differs')
            elif run['name'] == 'powershell-parse':
                require('Parser]::ParseFile' in run['argv'][-1] and log.strip() == 'PowerShell parser: PASS', 'PowerShell parse check differs')
            else:
                require('-DeadlineSeconds 2400 -ShowWindow' in run['argv'][-1] and "PathNotFound,*ResolvePathCommand" in run['argv'][-1], 'Expected-negative parameter guard differs')
                require('PASS; stopped at missing WorkDir before installation or GUI' in log, 'Parameter-binding outcome differs')
                require(not (self.repo / '__native_f5_binding_probe_missing__').exists(), 'Negative probe directory unexpectedly exists')
            results.append({'name': run['name'], 'exitCode': run['exitCode'], 'log': run['log'], 'argv': run['argv']})
        return {'runs': results, 'pythonCases': 41, 'productFileAppSuiteRerun': False}

    def preparation(self, profile, plan, candidate_sha=None):
        work = self.root / profile
        record = self.load(self.root / ('preparation-' + profile + '.json'))
        self.boundaries(record)
        require(record['sourceCommit'] == plan['sourceCommit'] and record['profile'] == profile and record['success'] is True and record['exitCode'] == 0 and record['editorNotRun'] is True, 'Preparation outcome/identity differs')
        require(record['nativeInputsBefore'] == record['nativeInputsAfter'] and record['traceImplementationBefore'] == record['traceImplementationAfter'] and record['editorCliBefore'] == record['editorCliAfter'], 'Preparation native inputs changed')
        for binding in record['nativeInputsBefore'] + record['traceImplementationBefore'] + [record['editorCliBefore']]:
            self.bound(binding)
        initial = {key: val for key, val in record.items() if key not in ('completedUtc', 'exitCode', 'log', 'sourceAfter', 'inputsAfter', 'helperAfter', 'commonAfter', 'planAfter', 'nativeInputsAfter', 'traceImplementationAfter', 'editorCliAfter', 'expected', 'candidate', 'consistencyErrors', 'candidateReuse', 'error')}
        initial['success'] = False
        require(self.load(self.root / ('preparation-' + profile + '-before.json')) == initial, 'Preparation before receipt differs')
        require(Path(record['argv'][0]) == Path(self.originals['python']['path']) and record['argv'][1:3] == ['-B', str(self.repo / 'scripts/variant/lifecycle/prepare.py')], 'Preparation executable/script differs')
        require(record['argv'][-8:] == ['--sdk-version', '10.0.403', '--scenario', 'native-f5', '--cycles', '10', '--work-dir', str(work)], 'Preparation scope/arguments differ')
        expected = self.load(work / 'expected.json')
        self.read(work / 'expected.json', record['expected'])
        require(expected['candidate'] == record['candidate'] and expected['scenario'] == 'native-f5' and expected['cycles'] == 10, 'Prepared candidate/scenario differs')
        require(expected['scope']['hardwareKeypress'] is False and expected['scope']['noFolderWindow'] is True and expected['scope']['qualification'] is False, 'Prepared scope differs')
        require([item['sequence'] for item in expected['nativeF5']['inputs']] == list(range(1, 11)), 'Prepared input paths differ')
        require(len({expected['nativeF5']['closed']} | {item[key] for item in expected['nativeF5']['inputs'] for key in ('request', 'receipt')}) == 21, 'Prepared paths collide')
        for key, sha in expected['harness'].items():
            require(self.sources['scripts/variant/lifecycle/' + key]['sha256'] == sha, 'Prepared harness differs')
        for name in ('driver.cjs', 'extension-test.cjs'):
            self.read(work / 'driver' / name, self.sources['scripts/variant/lifecycle/' + name], False)
        candidate = expected['candidate']
        require(candidate['sourceCommit'] == plan['sourceCommit'] and candidate['target'] == 'win32-arm64' and candidate['localOnly'] is True and candidate['published'] is False, 'Candidate source/scope differs')
        if candidate_sha:
            require(candidate['sha256'] == candidate_sha, 'Same-series candidate ZIP differs')
        require(proof(self.read(Path(candidate['path'])))['sha256'] == candidate['sha256'], 'Candidate ZIP differs')
        identity = {key: candidate[key] for key in ('baseVsixSha256', 'sourceCommit', 'target', 'ownedModules')}
        require(proof(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode())['sha256'] == candidate['buildId'], 'Candidate build identity differs')
        for name, sha in candidate['ownedModules'].items():
            require(self.sources[MODULE + name]['sha256'] == sha, 'Candidate product module differs')
        base_file = Path(record['nativeInputsBefore'][0]['path'])
        with zipfile.ZipFile(base_file) as base, zipfile.ZipFile(candidate['path']) as archive:
            names = archive.namelist()
            allowed = {'extension/.netcoredbg/' + name for name in candidate['ownedModules']} | {'extension/package.json', 'extension.vsixmanifest'}
            require(len(set(names)) == len(names) == 743 and set(names) == set(base.namelist()) | allowed, 'Candidate entry set differs')
            immutable = {name: proof(base.read(name))['sha256'] for name in base.namelist() if name not in allowed}
            require(len(immutable) == candidate['unchangedEntries'] == 736 and proof(json.dumps(immutable, sort_keys=True).encode())['sha256'] == candidate['unchangedPayloadDigest'], 'Candidate immutable digest differs')
            require(all(archive.read(name) == base.read(name) for name in immutable), 'Non-owned payload changed')
            require(all(proof(archive.read('extension/.netcoredbg/' + name))['sha256'] == sha for name, sha in candidate['ownedModules'].items()), 'Packaged modules differ')
        return record, expected

    def native_record(self, profile, expected, prep):
        record = self.load(self.root / ('native-run-' + profile + '-result.json'))
        self.boundaries(record)
        require(record['profile'] == profile and record['requestedExecutionContext'] == 'require_escalated' and record['effectivePermissionsIndependentlyMeasured'] is False, 'Native execution-context claim differs')
        require(record['launcherDeadlineSeconds'] == 2400 and record['phaseSafetyTimeoutMilliseconds'] == 90000 and record['historicalN01N02FailuresPreserved'] is True, 'Native safety/history policy differs')
        self.bound(record['preparation'])
        require(record['expectedBefore'] == record['expectedAfter'] == prep['expected'], 'Native expected metadata changed')
        require(record['argv'] == [self.originals['powershell']['path'], '-NoLogo', '-NoProfile', '-File', str(self.repo / 'scripts/variant/lifecycle/run.ps1'), '-WorkDir', str(self.root / profile), '-DeadlineSeconds', '2400', '-ShowWindow'], 'Native launcher argv differs')
        initial = {key: val for key, val in record.items() if key not in ('completedUtc', 'exitCode', 'log', 'inputsAfter', 'sourceAfter', 'expectedAfter', 'helperAfter', 'commonAfter', 'planAfter', 'consistencyErrors', 'result.json', 'trace.jsonl', 'launch.json', 'launcher-result.json', 'error')}
        initial['success'] = False
        require(self.load(self.root / ('native-run-' + profile + '-before.json')) == initial, 'Native before receipt differs')
        for key in ('result.json', 'trace.jsonl', 'launch.json', 'launcher-result.json'):
            if key in record:
                self.bound(record[key])
        return record


def failed_series(root):
    e = Evidence(root)
    e.pins(FAILED_PINS)
    plan, checks = e.load(e.root / 'series-plan.json'), e.load(e.root / 'checks/record.json')
    require(plan['baseCommit'] == BASE and plan['sourceCommit'] == FAILED_SOURCE and plan['cycles'] == 10 and plan['profiles'] == ['r01', 'r02'] and plan['launcherDeadlineSeconds'] == 2400, 'Failed series plan differs')
    e.bound(plan['helper'])
    for binding in plan['operatorPrepared']:
        e.bound(binding)
    inputs = e.inputs(checks)
    sources = e.source(checks, FAILED_SOURCE)
    frozen_checks = e.checks(checks)
    prep, expected = e.preparation('r01', plan)
    run = e.native_record('r01', expected, prep)
    require(run['success'] is False and run['exitCode'] == 1, 'Original failed run changed')
    log = e.bound(run['log']).decode('utf-8-sig')
    require('2400' in log and '900' in log and 'DeadlineSeconds' in log, 'Parameter-binding failure differs')
    runner = e.read(e.repo / 'scripts/variant/lifecycle/run.ps1').decode('utf-8-sig')
    require('[ValidateRange(60, 900)]' in runner and '[int]$DeadlineSeconds = 300' in runner, 'Original runner cap differs')
    work = e.root / 'r01'
    absent = ['attempt.json', 'launch.json', 'launcher-result.json', 'result.json', 'trace.jsonl', 'f5-input-closed.json', 'progress/state.json']
    absent += [Path(item[key]).name for item in expected['nativeF5']['inputs'] for key in ('request', 'receipt')]
    require(all(not (work / name).exists() for name in absent), 'Unexpected failed-series launch/readiness evidence')
    require(not (e.root / 'r02').exists() and not (e.root / 'preparation-r02.json').exists(), 'Failed series continued after first failure')
    stop = e.load(e.root / 'series-stop.json')
    require(stop['profile'] == 'r01' and stop['detail']['exitCode'] == 1 and stamp(stop['stoppedUtc']) >= stamp(run['completedUtc']), 'First-failure stop differs')
    # This source never launched the editor; installed/activated/runtime resource
    # claims must not be borrowed from the successor or earlier n03 control.
    return {'directory': str(e.root), 'outcome': 'parameter-binding-failed-before-editor-launch', 'success': False,
            'plan': {'path': str(e.root / 'series-plan.json'), **proof(e.read(e.root / 'series-plan.json'))},
            'source': sources, 'checks': frozen_checks, 'inputs': inputs, 'run': {'path': str(e.root / 'native-run-r01-result.json'), **proof(e.read(e.root / 'native-run-r01-result.json'))},
            'firstFailure': stop, 'editorLaunches': 0, 'nativeKeyInputs': 0, 'secondProfilePrepared': False,
            'notConsecutiveWithSuccessor': True}, e


def installed_files(e, work, expected, prep):
    bridge = '''Microsoft.CodeAnalysis.CSharp.Scripting.dll Microsoft.CodeAnalysis.CSharp.dll Microsoft.CodeAnalysis.Scripting.dll Microsoft.CodeAnalysis.dll
Microsoft.Diagnostics.BrowserDebugHost.dll Microsoft.Diagnostics.BrowserDebugHost.pdb Microsoft.Diagnostics.BrowserDebugHost.runtimeconfig.json Microsoft.Diagnostics.BrowserDebugHost.staticwebassets.endpoints.json
Microsoft.Diagnostics.BrowserDebugProxy.dll Microsoft.Diagnostics.BrowserDebugProxy.pdb Microsoft.FileFormats.dll Microsoft.NET.WebAssembly.Webcil.dll Microsoft.SymbolStore.dll
Newtonsoft.Json.dll System.Collections.Immutable.dll System.Reflection.Metadata.dll install.Lock'''.split()
    extras_wanted = {'.vswebassemblybridge/' + name for name in bridge} | {'.roslyn/cache/razor.mef.BQv5e2A7QRAGaFOU2mRvFg.cache'}
    result = {}
    archives = [('candidate', Path(expected['candidate']['path']), work / 'extensions/dotnetdev-kr-custom.csharp-with-netcoredbg-11.7.18004', 742),
                ('dependency', Path(prep['nativeInputsBefore'][1]['path']), work / 'extensions/ms-dotnettools.vscode-dotnet-runtime-3.2.0', 26)]
    for label, archive_file, directory, count in archives:
        with zipfile.ZipFile(archive_file) as archive:
            mapping = {name[10:]: name for name in archive.namelist() if name.startswith('extension/') and not name.endswith('/')}
            mapping['.vsixmanifest'] = 'extension.vsixmanifest'
            files = {file.relative_to(directory).as_posix(): file for file in directory.rglob('*') if file.is_file()}
            extras = set(files) - set(mapping)
            require(len(mapping) == count and set(mapping) <= set(files) and extras == (extras_wanted if label == 'candidate' else set()), 'Installed file set differs')
            metadata = None
            for name in mapping:
                actual, original = e.read(files[name]), archive.read(mapping[name])
                if name == 'package.json':
                    actual, original = json.loads(actual), json.loads(original)
                    metadata = actual.pop('__metadata')
                    require(isinstance(metadata, dict), 'Installer metadata absent')
                    original.pop('__metadata', None)
                require(actual == original, 'Installed packaged bytes differ: ' + name)
            result[label] = {'packagedFiles': count, 'observedFiles': len(files), 'installerMetadata': metadata,
                             'additionalFiles': {name: proof(e.read(files[name])) for name in sorted(extras)}}
    return result


def prior_mixed(e, directory):
    prior = Path(directory)
    paths = {
        'worktree/docs/research/native-f5-2026-11-09/README.md': '827c4ef8c6c7493a966d602a4de0a04f0da10a424dc45a8bc85cb6424dc755d8',
        'worktree/docs/research/native-f5-2026-11-09/verify.py': '6bf8b847726e95164125cf29df586e735af651d6f042de31bfcb365140fa72e8',
        'worktree/docs/research/native-f5-2026-11-09/evidence-summary.json': '20dda91cce8a112467d46b7a827765d31a7d6053d066da63177c243a6a5dd705',
        'native-run-result.json': '009e16fe8d44ad99b353f3821e44147f7bca55a8bff26e55497354053363c973',
        'native-run-n02-result.json': '71479ba027e3c98886cebb408658e2f9edcbc73a6a5239ce94d6a68cc21430de',
        'native-run-n03-result.json': '3c7a57a7e0dfd217e9e56d32aa21ed5dc872a9ee63d638d684cb0fda2305adf2',
        'n02/result.json': '9b6edd09617236151138ca960cc21d18b83ae73776387d2f3c9402c2a6250d81',
        'n03/result.json': '02aac824766ac7c4686731226c74fcf5e0721bcabb87720446fa08f1b8f8bab6',
    }
    bindings = {}
    for name, sha in paths.items():
        data = e.read(prior / name)
        require(proof(data)['sha256'] == sha, 'Historical frozen reference changed')
        bindings[name] = proof(data)
        if name.startswith('worktree/docs/'):
            require(data.replace(b'\r\n', b'\n') == e.git('show', BASE + ':' + name[len('worktree/'):]).replace(b'\r\n', b'\n'), 'Historical committed document differs')
    value = e.load(prior / 'worktree/docs/research/native-f5-2026-11-09/evidence-summary.json')
    require(value['outcome'] == 'mixed-recorded-outcomes' and value['allAttemptsPassed'] is False and [item['success'] for item in value['attempts']] == [False, False, True], 'Historical mixed status differs')
    return {'directory': str(prior), 'frozenReferences': bindings, 'n01': 'startup FAIL retained', 'n02': 'late-input harness FAIL retained', 'n03': 'two-input scoped PASS retained',
            'historicalCollectorExecuted': False, 'historicalAllInputsRevalidatedHere': False, 'notConsecutiveWithRepeatSeries': True}


def successor_failure(e, plan, prep, expected):
    work = e.root / 'r01'
    run = e.native_record('r01', expected, prep)
    result, launch, launcher = [e.load(work / name) for name in ('result.json', 'launch.json', 'launcher-result.json')]
    require(run['exitCode'] == 1 and run['success'] is False and result['success'] is False and launcher['success'] is False and launcher['editorExitCode'] == 1, 'Successor failed outcome differs')
    require(result['expected'] == expected and result['safetyTimeoutMilliseconds'] == 90000, 'Driver expected/safety metadata differs')
    require(launcher['pid'] == launch['pid'] and launcher['candidateSha256'] == expected['candidate']['sha256'] and launcher['fixtureShutdown'] == [], 'Launcher identity differs')
    require(launch['freshProfile'] is True and launch['visibleWindowRequested'] is True and launch['arguments'][-1].strip('"') == str(work / 'workspace/a.cs') and '--new-window' in launch['arguments'] and launch['arguments'][launch['arguments'].index('--log') + 1] == 'trace', 'Visible no-folder launch differs')
    require(result['scope']['targetCommandApiLaunch'] is False and result['scope']['hardwareKeypress'] is False and result['scope']['noFolderWindow'] is True, 'Observed driver scope differs')
    require(Path(result['installedExtension']['path']) == work / 'extensions/dotnetdev-kr-custom.csharp-with-netcoredbg-11.7.18004' and result['installedExtension']['build']['lifecycleBuildId'] == expected['candidate']['buildId'] and result['installedExtension']['build']['lifecycleSourceCommit'] == SOURCE, 'Activated candidate differs')
    require(result['installedModules'] == expected['candidate']['ownedModules'] and Path(result['installedDependency']['path']) == work / 'extensions/ms-dotnettools.vscode-dotnet-runtime-3.2.0', 'Activated dependency/modules differ')
    require([p['outcome'] for p in result['phases']] == ['passed', 'passed', 'failed'] and len(result['nativeF5']['inputs']) == len(result['launches']) == 1, 'Partial phase/input set differs')
    require('Safety timeout: native F5 input 1 breakpoint and HTTP revision' in result['firstFailure']['error'] and result['phases'][2]['error'] == result['firstFailure']['error'], 'Retained first failure differs')
    require(result['cleanup'] == [{'label': 'F5-1'}] and result['launches'][0]['capturedSessions'] == [] and result['nativeF5']['postStartApiActions'] == [], 'No-session partial cleanup differs')
    require(result['nativeF5']['setupCommands'] == [{'command': 'workbench.action.toggleKeybindingsLog', 'purpose': 'input diagnostics only; not a debugger launch'}], 'Setup command scope differs')
    require(result['nativeF5']['installedBinding'] == {'command': 'netcoredbg.debugActiveFile', 'key': 'f5', 'when': 'editorTextFocus && editorLangId == csharp && !inDebugMode'}, 'Installed binding differs')
    item, owned = result['nativeF5']['inputs'][0], result['launches'][0]
    request = item['request']
    require(item['sequence'] == request['sequence'] == 1 and item['label'] == owned['label'] == 'F5-1' and owned['revision'] == 'initial', 'First-input request differs')
    require(json.loads(e.embedded(item['requestSnapshot'], True)) == request, 'Request object/snapshot differs')
    e.embedded(item['profileSnapshot'], True)
    disk = e.embedded(request['diskBefore'], True)
    require(proof(disk) == request['bufferBefore'] and request['isDirty'] is False and b'const string revision = "initial";' in disk, 'Saved first source differs')
    require(request['nonce'] == expected['nativeF5']['nonce'] and request['windowTitle'] == expected['nativeF5']['windowTitle'] and request['launchToken'] == owned['nonce'], 'Request ownership differs')
    require(Path(request['activeSource']) == Path(request['source']) == work / 'workspace/a.cs' and request['workspaceFolders'] == [] and request['activeDebugSessionId'] is None and request['languageId'] == 'csharp', 'Request source context differs')
    require(request['action'] == 'press-key' and request['key'] == 'F5' and request['mechanism'] == 'native-injected' and (stamp(request['expiresAtUtc']) - stamp(request['requestedAtUtc'])).total_seconds() == 90, 'Request action/lease differs')
    profile = json.loads(e.embedded(item['profileSnapshot']))['profiles']['LifecycleHttp']
    require(profile['environmentVariables']['LIFECYCLE_TOKEN'] == owned['nonce'] and profile['applicationUrl'] == owned['origin'] and profile['launchBrowser'] is False, 'HTTP preparation profile differs')
    require(not any(key in item for key in ('receipt', 'route', 'builds', 'breakpoint', 'response', 'diskAfter', 'savedEvents')), 'Unexpected input/runtime observation')
    renderer, output = e.tail(item['rendererBefore']), e.tail(item['outputBefore'])
    require(not re.search(r'KeybindingService#dispatch\s+F5\s', renderer) and not re.search(r'CommandService#executeCommand\s+netcoredbg\.debugActiveFile\s*$', renderer, re.M), 'Unexpected F5 dispatch or owned target command')
    require(not re.search(r'^dotnet ', output, re.M), 'Unexpected file-debug command/build')
    trace = [json.loads(line) for line in e.read(work / 'trace.jsonl').decode().splitlines()]
    require(all(a['atMilliseconds'] <= b['atMilliseconds'] for a, b in zip(trace, trace[1:])), 'Trace ordering differs')
    require([entry['event'] for entry in trace] == ['phase-start', 'phase-end', 'phase-start', 'phase-end', 'phase-start', 'needs-f5-input', 'phase-end', 'f5-input-closed', 'first-failure'], 'Partial trace scope differs')
    require(trace[5]['detail']['requestSha256'] == item['requestSnapshot']['sha256'] and trace[-1]['detail'] == result['firstFailure'], 'Trace request/first failure differs')
    closed = e.load(Path(expected['nativeF5']['closed']))
    require(closed == trace[-2]['detail'] and closed['nonce'] == expected['nativeF5']['nonce'], 'First-failure input closure differs')
    for entry in expected['nativeF5']['inputs']:
        require(not Path(entry['receipt']).exists(), 'Unexpected native receipt')
        if entry['sequence'] > 1:
            require(not Path(entry['request']).exists(), 'Unexpected later input request')
    require(not (e.root / 'r02').exists() and not (e.root / 'preparation-r02.json').exists(), 'Successor continued after failure')
    stop = e.load(e.root / 'series-stop.json')
    require(stop['profile'] == 'r01' and stop['detail']['exitCode'] == 1 and stamp(stop['stoppedUtc']) >= stamp(run['completedUtc']), 'Successor series stop differs')
    operator = e.load(e.root / 'operator-observation-failure.json')
    require(operator['profile'] == 'r01' and operator['sequence'] == 1 and operator['requestedWindowTitle'] == request['windowTitle'] and request['windowTitle'] in operator['windowLastSelected']['title'], 'Operator selected-window metadata differs')
    require(operator['captureAttempts'] == 2 and operator['nativeKeyCalls'] == 0 and operator['targetCommandApiFallback'] is False and operator['uiInputStopped'] is True and operator['imagePayloadRetained'] is False, 'Operator failure/input scope differs')
    require('IGraphicsCaptureItemInterop.CreateForMonitor' in operator['error'] and '0x80070057' in operator['error'] and stamp(request['requestedAtUtc']) <= stamp(operator['recordedUtc']) <= stamp(closed['closedAtUtc']), 'Operator capture failure timing differs')
    settings = e.load(work / 'profile/User/settings.json')
    require(settings['files.autoSave'] == 'off' and settings['window.title'] == request['windowTitle'], 'Profile/autosave setting differs')
    for directory in ('logs', 'ui', 'profile/logs'):
        for file in sorted((work / directory).rglob('*')):
            if file.is_file():
                e.read(file)
    e.load(work / 'attempt.json')
    csharp, lsp = [list((work / 'profile/logs').rglob(name)) for name in ('C#.log', 'C# LSP Trace Logs.log')]
    require(len(csharp) == len(lsp) == 1, 'Language-service log set differs')
    require(proof(e.read(csharp[0]))['sha256'] == '140c1f30c0d4860c5a112c78fc63b4902d9bc3994ecdcf555a77508381375131' and proof(e.read(lsp[0]))['sha256'] == '1744fd1fbf1c349fe5a495eab80b896c9b7639718b5d8e73725f191748439be7', 'Language-service failure bytes differ')
    require(sum('NU1100' in line for line in e.read(csharp[0]).decode('utf-8').splitlines()) == 9 and 'There were problems loading project a.cs. See log for details.' in e.read(lsp[0]).decode('utf-8'), 'Language-service diagnostics differ')
    for config in (work / 'appdata/NuGet/NuGet.Config', work / 'workspace/NuGet.Config'):
        require('<packageSources><clear /></packageSources>' in e.read(config).decode('utf-8'), 'Offline fixture configuration differs')
    return {'outcome': 'pre-key-ui-capture-failure-and-harness-safety-timeout', 'success': False,
            'installedAndActivatedIdentity': 'passed driver checks', 'installedArtifacts': installed_files(e, work, expected, prep),
            'phases': result['phases'], 'firstFailure': result['firstFailure'], 'elapsedMilliseconds': result['elapsedMilliseconds'],
            'readinessRequests': 1, 'nativeKeyInputs': 0, 'nativeReceipts': 0, 'targetCommandRoutes': 0, 'targetBuilds': 0,
            'ownedSessions': 0, 'DAPBreakpointOrEvaluation': False, 'HTTPResponse': False, 'successfulResourceCleanup': False,
            'cleanupAsRecorded': result['cleanup'], 'fixtureShutdownAsRecorded': launcher['fixtureShutdown'],
            'operatorReport': operator, 'inputClosed': closed, 'seriesStop': stop, 'secondProfilePrepared': False,
            'languageService': {'NU1100Lines': 9, 'projectLoadErrorToastRetained': True, 'qualified': False}}


def build_summary(root):
    """Validate both separately failed series; never execute an evidence producer."""
    e = Evidence(root)
    e.pins(PINS)
    plan, checks = e.load(e.root / 'series-plan.json'), e.load(e.root / 'checks/record.json')
    require(plan['baseCommit'] == BASE and plan['sourceCommit'] == SOURCE and plan['cycles'] == 10 and plan['profiles'] == ['r01', 'r02'], 'Unexpected successor source/plan')
    require(plan['phaseSafetyTimeoutMilliseconds'] == 90000 and plan['launcherDeadlineSeconds'] == 2400 and plan['scope']['qualification'] is False and plan['scope']['policyAC146Approved'] is False and plan['scope']['issue45Resolved'] is False, 'Plan safety/qualification scope differs')
    e.bound(plan['helper'])
    for binding in plan['operatorPrepared']:
        e.bound(binding)
    producer = e.load(e.root / 'producer-prepared-before-launch.json')
    require(producer['profileNotLaunched'] is True and producer['perKeyObservationRequired'] is True and producer['imagesRetained'] is False and producer['producerSha256'] == proof(e.read(e.root / 'native-key-producer-source.js'))['sha256'], 'Prepared producer identity/scope differs')
    require(stamp(producer['preparedUtc']) <= stamp(plan['plannedUtc']) <= stamp(checks['beganUtc']), 'Prospective producer/plan order differs')
    inputs = e.inputs(checks)
    source = e.source(checks, SOURCE)
    frozen_checks = e.checks(checks, True)
    runner = e.read(e.repo / 'scripts/variant/lifecycle/run.ps1')
    old_runner = e.git('show', FAILED_SOURCE + ':scripts/variant/lifecycle/run.ps1')
    require(old_runner.replace(b'[ValidateRange(60, 900)]', b'[ValidateRange(60, 3600)]') == runner.replace(b'\r\n', b'\n'), 'Successor parameter-only correction differs')
    require(set(e.git('diff', '--name-only', FAILED_SOURCE, SOURCE).decode().splitlines()) == {'scripts/variant/lifecycle/run.ps1'}, 'Investigation correction expanded scope')
    prep, expected = e.preparation('r01', plan)
    require(prep['priorProfile'] is None and stamp(checks['completedUtc']) <= stamp(prep['startedUtc']), 'First profile preparation/check order differs')
    successor = successor_failure(e, plan, prep, expected)
    failed, first_e = failed_series(Path(plan['firstSeriesInvestigation']['directory']))
    require(plan['firstSeriesInvestigation']['notConsecutiveWithThisSeries'] is True and failed['run'] == plan['firstSeriesInvestigation']['nativeRun'], 'Failed-series investigation binding differs')
    e.bound(plan['firstSeriesInvestigation']['seriesStop'])
    require(stamp(failed['firstFailure']['stoppedUtc']) <= stamp(plan['plannedUtc']), 'Successor plan preceded preserved failure')
    historical = prior_mixed(e, plan['priorEvidence']['directory'])
    require(plan['priorEvidence']['notConsecutiveWithThisSeries'] is True, 'Historical consecutive-count boundary differs')
    architecture = first_e.load(first_e.root / 'system-architecture-readback.json')
    readback = e.load(e.root / 'environment-and-probe-readback.json')
    require(architecture['processArchitecture'] == architecture['osArchitecture'] == readback['processArchitecture'] == readback['osArchitecture'] == 'Arm64', 'Separate architecture readback differs')
    require(architecture['os'] is None and architecture['processors'] == [] and plan['system']['machine'] == 'AMD64', 'Recorded architecture limitations differ')
    require(readback['parameterProbeExistsAfterChecksAndAttempt'] is False and Path(readback['parameterProbePath']) == e.repo / '__native_f5_binding_probe_missing__', 'After-attempt negative-probe readback differs')
    require(stamp(readback['observedUtc']) >= stamp(e.load(e.root / 'native-run-r01-result.json')['completedUtc']), 'Environment readback is not after attempt')
    # PE header is checked as bytes; it is not executed by this verifier.
    editor = e.read(Path(expected['editor']['executable']))
    pe = int.from_bytes(editor[0x3c:0x40], 'little')
    require(editor[pe:pe+4] == b'PE\0\0' and int.from_bytes(editor[pe+4:pe+6], 'little') == 0xaa64, 'Native editor PE is not ARM64')
    inventory = {**first_e.inventory, **e.inventory}
    inventory = {name: inventory[name] for name in sorted(inventory)}
    for name, binding in inventory.items():
        require(proof(e.read(Path(name))) == binding, 'Original input changed during collection: ' + name)
    compact = {name: val for name, val in inventory.items() if not any(part in name.replace('\\', '/') for part in ('/extensions/', '/checks/source/', '/worktree/scripts/variant/'))}
    return {'schema': 1, 'outcome': 'two-separately-failed-repeat-series', 'allSeriesPassed': False,
            'baseCommit': BASE, 'sourceCommit': SOURCE, 'plannedProfilesPerSeries': 2, 'plannedCyclesPerProfile': 10,
            'completedTenCycleProfiles': 0, 'actualNativeF5InputsAcrossTheseSeries': 0,
            'firstSeries': failed, 'successor': successor, 'source': source, 'checks': frozen_checks,
            'successorCandidate': expected['candidate'], 'preflightEditor': expected['editor'], 'preflightSDK': expected['sdk'],
            'successorInputs': inputs, 'priorMixedReference': historical,
            'architecture': {'planProcessEnvironment': plan['system'], 'beforeFirstSeriesReadback': architecture, 'afterSuccessorReadback': readback, 'nativeEditorPEMachine': '0xaa64'},
            'scope': {'repeatedNativeF5Qualified': False, 'AC7Completed': False, 'policyAC146Approved': False, 'macOS': False, 'menu': False, 'LSPQualified': False, 'issue45Resolved': False, 'fullMatrix': False, 'published': False},
            'limits': 'No F5 key was injected in either repeat series. The first failed before editor launch; the successor failed after readiness and two operator-reported capture errors. No product timeout, F5 defect, actual session cleanup or 2x10 success is inferred. Historical n01/n02 remain failures and n03 remains a separate two-input observation. Retained EXE bytes do not reconstruct the execution environment or effective security token.',
            'verifiedInputCount': len(inventory), 'verifiedInputInventorySha256': proof(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode())['sha256'],
            'retainedRecordAndLogBindings': compact}


if __name__ == '__main__':
    require(len(sys.argv) <= 2, 'Usage: verify.py [ARTIFACT_ROOT]')
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parents[4]
    sys.stdout.buffer.write((json.dumps(build_summary(root), indent=2) + '\n').encode('utf-8'))
