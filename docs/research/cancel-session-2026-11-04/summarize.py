import hashlib
import json
from pathlib import Path

work = Path(__file__).resolve().parent
before = json.loads((work / 'before-terminal-guard.json').read_text())
after = json.loads((work / 'editor-result.json').read_text())
assert after['success']
assert not before['success']

def observations(run):
    events = run['sequence']
    first = next(e['at'] for e in events if e['event'] == 'progress-cancel')
    return [dict(event=e['event'], afterCancelMs=e['at']-first,
                 detail=e.get('detail')) for e in events
            if e['event'] in ['progress-cancel', 'foreground-cancel-returned',
                              'runtime-stop-request', 'runtime-stop-resolved',
                              'post-stop-resolve-output', 'editor-terminate']]

summary = {
    'date': '2026-11-04',
    'platform': 'Windows ARM64',
    'editorVersion': after['editorVersion'],
    'installedAdapterExtensionVersion': after['installedVersion'],
    'sdkVersion': '10.0.403',
    'runtimeVersion': '10.0.14',
    'scope': after['scope'],
    'checks': after['checks'],
    'beforeTerminalGuard': {'success': before['success'], 'runtimeSha256': before['runtimeSha256'],
                            'assertion': 'Stop API completion must not delete DLL before the actual termination event',
                            'observations': observations(before)},
    'afterTerminalGuard': {'success': after['success'], 'runtimeSha256': after['runtimeSha256'],
                           'observations': observations(after)},
    'artifactSha256': {name: hashlib.sha256((work/name).read_bytes()).hexdigest()
        for name in ['editor-test.cjs','prepare.py','run-editor.ps1','before-terminal-guard.json','editor-result.json']},
    'interpretation': 'Observed API completion before termination notification; no claim about process liveness in that interval. The fixed runtime retained the DLL until termination was observed and removed output afterward.',
}
(work/'evidence-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({'success': after['success'], 'checks': len(after['checks']), 'runtimeSha256': after['runtimeSha256']}))
