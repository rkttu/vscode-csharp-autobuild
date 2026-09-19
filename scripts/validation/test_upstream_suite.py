"""Regression tests for cleanup without signaling real processes."""
import contextlib
import errno
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from upstream_suite import command


@unittest.skipIf(os.name == 'nt', 'POSIX process-group cleanup')
class CommandCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.process = Mock(pid=424242)
        self.process.wait.return_value = 0
        self.log = self.root / 'command.log'

    def execute(self, kill_error):
        with patch('upstream_suite.subprocess.Popen', return_value=self.process), \
             patch('upstream_suite.os.killpg', side_effect=kill_error), \
             contextlib.redirect_stderr(io.StringIO()):
            return command(['synthetic-command'], self.root, {}, self.log, 10)

    def test_success_survives_post_exit_permission_error_with_evidence(self):
        result = self.execute(PermissionError(errno.EPERM, 'Operation not permitted'))
        self.assertEqual(result['exitCode'], 0)
        self.assertFalse(result['timedOut'])
        self.assertIn('Operation not permitted', result['cleanupWarning'])
        self.assertIn(result['cleanupWarning'], self.log.read_text())

    def test_failed_command_remains_failed_after_cleanup_error(self):
        self.process.wait.return_value = 7
        result = self.execute(PermissionError(errno.EPERM, 'Operation not permitted'))
        self.assertEqual(result['exitCode'], 7)
        self.assertFalse(result['timedOut'])

    def test_timeout_remains_failed_after_post_exit_cleanup_error(self):
        self.process.wait.side_effect = [subprocess.TimeoutExpired('synthetic-command', 10), -9]
        result = self.execute([None, PermissionError(errno.EPERM, 'Operation not permitted')])
        self.assertEqual(result['exitCode'], -9)
        self.assertTrue(result['timedOut'])

    def test_permission_error_killing_running_command_is_not_ignored(self):
        self.process.wait.side_effect = subprocess.TimeoutExpired('synthetic-command', 10)
        with self.assertRaises(PermissionError):
            self.execute(PermissionError(errno.EPERM, 'Operation not permitted'))

    def test_already_gone_group_is_harmless(self):
        result = self.execute(ProcessLookupError(errno.ESRCH, 'No such process'))
        self.assertEqual(result['exitCode'], 0)
        self.assertNotIn('cleanupWarning', result)

    def test_unexpected_cleanup_error_is_not_ignored(self):
        with self.assertRaises(OSError):
            self.execute(OSError(errno.EIO, 'Unexpected I/O error'))


if __name__ == '__main__':
    unittest.main()
