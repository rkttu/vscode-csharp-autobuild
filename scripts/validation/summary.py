"""Expose artifact failures in the Actions job summary without changing gate results."""
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--evidence', type=Path, required=True)
parser.add_argument('--stage', required=True)
args = parser.parse_args()
lines = [f'## netcoredbg: {args.stage}', '']
candidate = json.loads(os.environ.get('CANDIDATE_JSON') or '{}')
for key in ('version', 'releaseTag', 'csharpTag', 'csharpSha', 'debuggerTag', 'debuggerSha'):
    if key in candidate:
        lines.append(f'- {key}: `{candidate[key]}`')
lines += [f'- Workflow commit: `{os.environ.get("GITHUB_SHA", "local")}`',
          f'- Target: `{os.environ.get("VALIDATION_TARGET", "all")}`']
found = False
for name in ('result.json', 'vsix-result.json', 'publication-status.json', 'validation-manifest.json'):
    file = args.evidence / name
    if not file.exists():
        continue
    found = True
    data = json.loads(file.read_text(encoding='utf-8-sig'))
    for key in ('success', 'stage', 'error', 'errors', 'sourceUnchanged', 'verifiedTargets', 'netcoredbgTag', 'netcoredbgCommit'):
        if key in data:
            lines.append(f'- {key}: `{data[key]}`')
for file in sorted(args.evidence.glob('upstream-net*-result.json')):
    data = json.loads(file.read_text(encoding='utf-8'))
    passed = sum(test.get('success') is True for test in data['tests'])
    lines.append(f'- .NET {data["runtime"]} upstream DAP: {passed}/{len(data["tests"])} passed; suite success: `{data["success"]}`')
    for test in data['tests']:
        if not test['success']:
            lines.append(f'  - `{test["name"]}`: stage `{test["stage"]}`, exit `{test.get("exitCode")}`, timeout `{test.get("timedOut")}`')
if not found:
    lines.append('- No final evidence file. Inspect the failed step and uploaded logs; this is not a passing validation.')
lines += ['', 'Validation failure blocks publication. A partially uploaded release resumes from its saved bytes.',
          'See the run artifacts for complete test transcripts and source-integrity records.', '']
text = '\n'.join(lines)
print(text)
if os.environ.get('GITHUB_STEP_SUMMARY'):
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
        stream.write(text)
