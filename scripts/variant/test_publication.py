"""Exercise interrupted publication using real manifests/files and fake remote services."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import publish
import resume
import versioning
from upstream_suite import policy


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.remote = self.root / 'remote'
        self.remote.mkdir()
        self.artifacts = self.root / 'first'
        self.artifacts.mkdir()
        self.candidate = dict(versioning.identity('v2.148.23-prerelease', '3.2.0-1092', 'a' * 40, 1),
                              csharpTag='v2.148.23-prerelease', csharpSha='b' * 40,
                              debuggerTag='3.2.0-1092', debuggerSha='a' * 40,
                              fingerprint='c' * 64, artifactPrefix='c' * 16, recipe='d' * 64)
        self.candidate_file = self.root / 'candidate.json'
        self.write(self.candidate_file, self.candidate)
        self.targets = json.loads((Path(__file__).resolve().parents[2] / 'config/netcoredbg.json').read_text())['targets']
        validated = self.artifacts / (self.candidate['artifactPrefix'] + '-validated')
        validated.mkdir()
        rows = []
        for target in self.targets:
            file = self.artifacts / f"csharp-with-netcoredbg-{target}-{self.candidate['version']}.vsix"
            file.write_bytes(('Synthetic VSIX ' + target).encode())
            evidence = self.artifacts / (self.candidate['artifactPrefix'] + '-tested-' + target)
            evidence.mkdir()
            self.write(evidence / 'vsix-result.json', dict(success=True, target=target, version=self.candidate['version'],
                runtimeTests=['8', '10'], debuggerSha256='f' * 64,
                upstreamTests={runtime: dict(success=True, runtime=runtime, architecture=target.split('-')[1],
                    debuggerSha256='f' * 64, sourceUnchanged=True,
                    tests=[dict(name=name, success=True, exitCode=0, timedOut=False) for name in policy()['tests']])
                    for runtime in ('8', '10')}, sha256=publish.sha256(file), netcoredbgBuild=dict(
                    netcoredbgCommit='a' * 40, upstreamCsharpCommit='b' * 40, upstreamCsharpVersion='2.148.23',
                    netcoredbgTag='3.2.0-1092', packagingRevision=1, releaseTag=self.candidate['releaseTag'])))
            archive = validated / f'netcoredbg-{target}.zip'
            archive.write_bytes(('Synthetic debugger ' + target).encode())
            rows.append(dict(target=target, success=True, archive=archive.name, sha256=publish.sha256(archive)))
        self.write(validated / 'validation-manifest.json', dict(success=True, targets=rows, netcoredbgCommit='a' * 40))
        self.registry = {}
        self.uploads = []
        self.finalized = False
        self.draft = False
        self.fail_target = None
        self.fail_finalize = False
        for patcher in (patch.dict(os.environ, OVSX_PAT='fake-test-token', GITHUB_REF='refs/heads/main', GITHUB_SHA='e' * 40),
                        patch('subprocess.run', side_effect=self.command),
                        patch('subprocess.check_output', side_effect=self.output),
                        patch('urllib.request.urlopen', side_effect=self.urlopen)):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def write(file, value):
        file.write_text(json.dumps(value))

    def command(self, command, **kwargs):
        if command[:3] == ['gh', 'release', 'view']:
            return subprocess.CompletedProcess(command, 0 if self.draft else 1)
        if command[:3] == ['gh', 'release', 'create']:
            for arg in command:
                file = Path(arg)
                if file.is_file():
                    shutil.copy2(file, self.remote / file.name)
            self.draft = True
        elif command[:3] == ['gh', 'release', 'download']:
            destination = Path(command[command.index('--dir') + 1])
            destination.mkdir(exist_ok=True, parents=True)
            for file in self.remote.iterdir():
                shutil.copy2(file, destination / file.name)
        elif command[:3] == ['gh', 'release', 'edit']:
            if self.fail_finalize:
                raise subprocess.CalledProcessError(1, command)
            self.finalized = True
        elif command[:2] == ['ovsx', 'publish']:
            file = Path(command[-1])
            target = next(target for target in self.targets if f'-{target}-' in file.name)
            if target == self.fail_target:
                raise subprocess.CalledProcessError(1, command)
            self.registry[target] = file.read_bytes()
            self.uploads.append(target)
        else:
            raise AssertionError('Unexpected command: ' + repr(command))
        return subprocess.CompletedProcess(command, 0)

    def output(self, command, **kwargs):
        self.assertEqual(command[:3], ['gh', 'release', 'view'])
        return json.dumps({'body': (self.remote / 'release-notes.md').read_text()})

    def urlopen(self, url, **kwargs):
        if url.startswith('https://test.invalid/'):
            return io.BytesIO(self.registry[url.rsplit('/', 1)[1]])
        target = url.split('/')[-2]
        if target not in self.registry:
            raise urllib.error.HTTPError(url, 404, 'Not found', {}, None)
        return io.BytesIO(json.dumps(dict(version=self.candidate['version'], targetPlatform=target,
            files=dict(download='https://test.invalid/' + target))).encode())

    def publish(self):
        with contextlib.redirect_stdout(io.StringIO()):
            publish.main(['--artifacts', str(self.artifacts), '--candidate', str(self.candidate_file), '--publish'])

    def restore(self):
        self.artifacts = self.root / 'retry'
        self.artifacts.mkdir()
        self.write(self.candidate_file, dict(self.candidate, resumeRelease=self.candidate['releaseTag']))
        with contextlib.redirect_stdout(io.StringIO()):
            resume.main(['--artifacts', str(self.artifacts), '--candidate', str(self.candidate_file)])

    def test_partial_upload_resumes_only_missing_targets_from_saved_bytes(self):
        self.fail_target = self.targets[3]
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.assertEqual(self.uploads, self.targets[:3])
        self.assertFalse(self.finalized)
        self.restore()
        self.fail_target = None
        self.publish()
        self.assertEqual(self.uploads, self.targets)
        self.assertTrue(self.finalized)

    def test_finalization_only_retry_does_not_upload_again(self):
        self.fail_finalize = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        self.assertEqual(self.uploads, self.targets)
        self.restore()
        self.fail_finalize = False
        self.publish()
        self.assertEqual(self.uploads, self.targets)
        self.assertTrue(self.finalized)

    def test_existing_identical_bytes_are_skipped(self):
        first = self.targets[0]
        self.registry[first] = next(self.artifacts.glob(f'*-{first}-*.vsix')).read_bytes()
        self.publish()
        self.assertEqual(self.uploads, self.targets[1:])
        self.assertTrue(self.finalized)

    def test_existing_different_bytes_stop_publication(self):
        self.registry[self.targets[0]] = b'Different public bytes'
        with self.assertRaisesRegex(AssertionError, 'Published VSIX differs'):
            self.publish()
        self.assertEqual(self.uploads, [])
        self.assertFalse(self.finalized)

    def test_missing_preserved_vsix_stops_retry(self):
        self.fail_target = self.targets[0]
        with self.assertRaises(subprocess.CalledProcessError):
            self.publish()
        next(self.remote.glob('*.vsix')).unlink()
        self.restore()
        self.fail_target = None
        with self.assertRaisesRegex(AssertionError, 'Missing or duplicate VSIX'):
            self.publish()
        self.assertEqual(self.uploads, [])
        self.assertFalse(self.finalized)


    def test_missing_native_suite_blocks_all_external_writes(self):
        record_file = next(self.artifacts.glob('*-tested-*/vsix-result.json'))
        record = json.loads(record_file.read_text())
        record['upstreamTests'].pop('10')
        self.write(record_file, record)
        with self.assertRaises(AssertionError):
            self.publish()
        self.assertFalse(self.draft)
        self.assertEqual(self.uploads, [])


    def test_all_missing_targets_are_submitted_before_visibility_wait(self):
        original = self.urlopen

        def registry(url, **kwargs):
            target = url.split('/')[-2]
            if target in self.registry:
                self.assertEqual(self.uploads, self.targets)
            return original(url, **kwargs)

        with patch('urllib.request.urlopen', side_effect=registry):
            self.publish()
        self.assertTrue(self.finalized)

    def test_visibility_timeout_resumes_without_reupload(self):
        with patch.object(publish, 'wait_for_metadata', side_effect=TimeoutError('Still processing')):
            with self.assertRaises(TimeoutError):
                self.publish()
        self.assertEqual(self.uploads, self.targets)
        self.assertFalse(self.finalized)
        self.restore()
        self.publish()
        self.assertEqual(self.uploads, self.targets)
        self.assertTrue(self.finalized)


class VisibilityTests(unittest.TestCase):
    def test_waits_for_metadata_after_accepted_upload(self):
        expected = {'version': '2.148.23001'}
        with patch.object(publish, 'registry_metadata', side_effect=[None, None, expected]), \
             patch('time.monotonic', side_effect=[0, 15]), patch('time.sleep') as sleep, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(publish.wait_for_metadata('https://test.invalid/metadata', 60), expected)
        self.assertEqual(sleep.call_count, 2)

    def test_inactive_version_reaches_bounded_failure(self):
        with patch.object(publish, 'registry_metadata', return_value=None), \
             patch('time.monotonic', return_value=60), patch('time.sleep') as sleep:
            with self.assertRaisesRegex(TimeoutError, 'not publicly available'):
                publish.wait_for_metadata('https://test.invalid/metadata', 60)
        sleep.assert_not_called()

    def test_authentication_error_is_not_retried_as_pending(self):
        error = urllib.error.HTTPError('https://test.invalid', 403, 'Forbidden', {}, None)
        with patch('urllib.request.urlopen', side_effect=error), patch('time.sleep') as sleep:
            with self.assertRaises(urllib.error.HTTPError):
                publish.wait_for_metadata('https://test.invalid/metadata', 60)
        sleep.assert_not_called()

if __name__ == '__main__':
    unittest.main()
