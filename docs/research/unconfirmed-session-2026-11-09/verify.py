"""Read retained checks; emit deterministic UTF-8/LF JSON. Runs only read-only Git."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

BASE = 'b2549b9c4eb7f12b1272468021d2de9ab761ae09'
SOURCE = '97ed767b789fe9bcd1e88889fa4ec18cd0cfe496'
MODULE = 'scripts/variant/file-based-apps/'
NAMES = ('entry.cjs', 'runtime.cjs', 'classify.cjs', 'web.cjs', 'recovery.cjs', 'test-runtime.cjs')
CHANGED = {MODULE + 'runtime.cjs', MODULE + 'test-runtime.cjs', 'docs/file-based-apps.md'}
HELPER = {'bytes': 6136, 'sha256': 'f285007020102911c2cfc1551750f226e12b2c45ff09bc3adb2ec34d3d4458e0'}
POOL = {'bytes': 3230, 'sha256': 'ed5f4e0d930b6262207bebb54e34cec17f5c81028fbd4613236c0f7351b80f97'}
CAPTURE = {'bytes': 2818, 'sha256': 'bc7c3bc135c376333ac9f4a86e2caebd5ff64519f7468d9ada39110e74e412f5'}
RECORDS = {'initial-contrast': '73f4c28f0a0ea7f28d5babad5b9cb2cb7255e9621481837269eae3f9f193f61c',
           'initial-full': '71a6d9bd33a392d73598453492180e8165daaa33e4b7c492e63ab6f254716118'}
TITLES = [
    'preserve an accepted result and independent retry while retaining unobserved output',
    'confirm only the exact late session once and ignore duplicate or unrelated events',
    'keep a cancelled late acceptance false and quiet while stopping only its later exact session',
    'identify pending accepted and captured disposal ownership without early cleanup',
    'stay absent when exact events already arrived or the API declined or rejected',
    'contain throwing sinks and reentrant disposal after updating ownership state',
]
TITLES = ['unconfirmed launch diagnostics ' + name for name in TITLES]

def require(ok, message):
    if not ok:
        raise ValueError(message)

def proof(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def read(file, expected=None):
    require(file.is_file() and not file.is_symlink(), 'Missing/nonregular input: ' + str(file))
    data = file.read_bytes()
    require(expected is None or proof(data) == expected, 'Byte binding differs: ' + str(file))
    return data

def load(file):
    return json.loads(read(file))

def stamp(value):
    result = datetime.fromisoformat(value)
    require(result.utcoffset() == timedelta(0), 'Expected aware UTC: ' + value)
    return result

def normalized(data):
    return data.replace(b'\r\n', b'\n')

def build_summary(root):
    repo = root / 'worktree'
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo)
    require(set(git('diff', '--name-only', BASE, SOURCE).decode().splitlines()) == CHANGED, 'Source commit scope differs')
    paths = set(git('ls-tree', '-r', '--name-only', SOURCE, 'scripts/variant').decode().splitlines()) | {'docs/file-based-apps.md'}
    require(len(paths) == 54, 'Expected 53 variant sources plus user documentation')
    manifest_file = root / 'verifier-inputs/manifest.json'
    manifest = json.loads(read(manifest_file, POOL))
    read(root / 'capture-verifier-inputs.py', CAPTURE)
    require(manifest['schema'] == 1 and manifest['executionPathsUnchanged'] is True, 'Capture schema differs')
    require(manifest['helper'] == {'path': str(root / 'capture-verifier-inputs.py'), **CAPTURE}, 'Capture helper differs')
    captured = stamp(manifest['capturedUtc'])
    executables = {}
    for name in ('node', 'python'):
        pair = manifest['copies'][name]
        original, retained = pair['recordedOriginal'], pair['retained']
        expected = {key: original[key] for key in ('bytes', 'sha256')}
        require(manifest['originalBefore'][name] == manifest['originalAfter'][name] == original, 'Capture identity differs')
        require(Path(retained['path']) == root / 'verifier-inputs' / (name + '-' + original['sha256'] + '.exe'), 'Unexpected retained path')
        read(Path(retained['path']), expected)
        require({key: retained[key] for key in expected} == expected, 'Retained identity differs')
        executables[name] = {'originalPath': original['path'], 'retainedPath': retained['path'], **expected}
    def snapshot(value):
        require(value['manifest'] == POOL and value['executables'] == executables, 'Run verifier inputs differ')
        checked = stamp(value['checkedUtc'])
        require(captured <= checked, 'Run predates capture')
        return checked
    records, frozen = [], None
    for attempt, record_hash in RECORDS.items():
        folder = root / 'checks' / attempt
        raw = read(folder / 'record.json')
        require(proof(raw)['sha256'] == record_hash, 'Frozen record differs')
        record = json.loads(raw)
        mode = 'contrast' if attempt == 'initial-contrast' else 'full'
        require(record['schema'] == 1 and record['mode'] == mode and record['baseCommit'] == BASE and record['worktree'] == str(repo), 'Record identity differs')
        require(record['helper'] == record['helperAfter'] == HELPER, 'Runner changed')
        read(folder / 'record-checks.py', HELPER)
        before = {key: value for key, value in record.items() if key not in ('sourceAfter', 'inputsAfter', 'completedUtc', 'helperAfter')}
        before['runs'] = []
        require(load(folder / 'before.json') == before, 'Before record differs')
        sources = record['sourceBefore']
        require(set(sources) == paths and record['sourceAfter'] == sources and (frozen is None or frozen == sources), 'Frozen sources differ')
        if frozen is None:
            for name in sorted(paths):
                require(normalized(read(repo / name, sources[name])) == normalized(git('show', SOURCE + ':' + name)), 'Source commit bytes differ: ' + name)
                if name not in CHANGED:
                    require(git('show', SOURCE + ':' + name) == git('show', BASE + ':' + name), 'Unchanged base source differs: ' + name)
        frozen = sources
        for name in sorted(paths):
            read(folder / 'source' / name, sources[name])
        began, completed = stamp(record['beganUtc']), stamp(record['completedUtc'])
        require(snapshot(record['inputsBefore']) <= began <= completed and snapshot(record['inputsAfter']) <= completed, 'Attempt time order differs')
        variants = ['baseline', 'changed'] if mode == 'contrast' else ['full']
        require([run['variant'] for run in record['runs']] == variants, 'Run set differs')
        runs, previous = [], began
        for run in record['runs']:
            variant = run['variant']
            require(load(folder / (variant + '-result.json')) == run, 'Run result differs')
            started, ended = stamp(run['startedUtc']), stamp(run['completedUtc'])
            require(previous <= snapshot(run['inputsBefore']) <= started <= ended <= snapshot(run['inputsAfter']) <= completed, 'Run time order differs')
            previous = snapshot(run['inputsAfter'])
            argv = [executables['node']['originalPath'], '--unhandled-rejections=strict', '--test', '--test-reporter=tap']
            argv += ['--test-name-pattern', '^unconfirmed launch diagnostics', str(folder / variant / 'test-runtime.cjs')] if mode == 'contrast' else [MODULE + 'test-' + name + '.cjs' for name in ('classify', 'entry', 'recovery', 'runtime', 'web')]
            require(run['argv'] == argv and run['cwd'] == str(repo), 'Recorded argv/cwd differs')
            require(set(run['copiedSource']) == (set(NAMES) if mode == 'contrast' else set()), 'Contrast copy set differs')
            for name in run['copiedSource']:
                data = read(folder / variant / name, run['copiedSource'][name])
                expected = git('show', BASE + ':' + MODULE + name) if variant == 'baseline' and name == 'runtime.cjs' else read(folder / 'source' / (MODULE + name))
                require(data == expected, 'Contrast changed more than baseline runtime: ' + name)
            require(run['log']['file'] == variant + '.log', 'Log path differs')
            text = normalized(read(folder / run['log']['file'], {k: run['log'][k] for k in ('bytes', 'sha256')})).decode()
            counts = {key: re.findall(r'^# ' + key + r' (\d+)\s*$', text, re.M) for key in ('tests', 'suites', 'pass', 'fail', 'cancelled', 'skipped', 'todo')}
            require(all(len(value) == 1 for value in counts.values()), 'Incomplete TAP footer')
            counts = {key: int(value[0]) for key, value in counts.items()}
            expected = dict(zip(counts, (6, 0, 1, 5, 0, 0, 0) if variant == 'baseline' else (6 if mode == 'contrast' else 321, 0, 6 if mode == 'contrast' else 321, 0, 0, 0, 0)))
            require(run['counts'] == counts == expected and run['exitCode'] == (1 if variant == 'baseline' else 0), 'Unexpected TAP outcome')
            cases = re.findall(r'^(not ok|ok) (\d+) - ([^\n]+)\n(.*?)(?=^# Subtest:|^1\.\.|\Z)', text, re.M | re.S)
            require(len(cases) == counts['tests'] and sum(status == 'ok' for status, *_ in cases) == counts['pass'], 'Rendered TAP cases differ')
            selected = []
            if mode == 'contrast':
                require([name for _, _, name, _ in cases] == TITLES and [int(number) for _, number, _, _ in cases] == list(range(1, 7)), 'Selected test names differ')
                for index, (status, _, name, diagnostic) in enumerate(cases):
                    require(status == ('not ok' if variant == 'baseline' and index != 4 else 'ok'), 'Selected control outcome differs')
                    item = {'name': name, 'passed': status == 'ok'}
                    if status == 'not ok':
                        require("code: 'ERR_ASSERTION'" in diagnostic and "failureType: 'testCodeFailure'" in diagnostic, 'Unexpected baseline failure kind')
                        item.update(diagnosticSha256=proof(diagnostic.encode())['sha256'], diagnostic=diagnostic)
                    selected.append(item)
            runs.append({'variant': variant, 'argv': argv, 'startedUtc': run['startedUtc'], 'completedUtc': run['completedUtc'], 'exitCode': run['exitCode'], 'counts': counts, 'log': {'path': str(folder / run['log']['file']), **{k: run['log'][k] for k in ('bytes', 'sha256')}}, 'selected': selected})
        records.append({'record': {'path': str(folder / 'record.json'), **proof(raw)}, 'runner': HELPER, 'archivedSourcesVerified': 54, 'runs': runs})
    return {'schema': 1, 'scope': 'Controlled editor acceptance/event diagnostics; no native session-delivery qualification.', 'baseCommit': BASE, 'sourceCommit': SOURCE,
            'sourcesVerified': 54, 'changedFiles': {name: frozen[name] for name in sorted(CHANGED)}, 'verifierManifest': {'path': str(manifest_file), **POOL}, 'verifierExecutables': executables,
            'inputLimits': 'Original argv identities are recorded; replay reads retained EXE bytes, not current cache EXEs. No complete Python environment is retained.', 'checks': records}

if __name__ == '__main__':
    root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parents[4]
    require(len(sys.argv) <= 2, 'Usage: verify.py [ARTIFACT_ROOT]')
    sys.stdout.buffer.write((json.dumps(build_summary(root), indent=2) + '\n').encode())
