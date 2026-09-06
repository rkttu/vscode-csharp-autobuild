"""Test tag discovery and interrupted-upload selection without network access."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import discover


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = json.loads((discover.ROOT / "config/netcoredbg.json").read_text())
        self.debuggers = {self.config["baselineTag"]: self.config["baselineCommit"]}
        self.csharp = {"v2.148.23-prerelease": "c" * 40}

    def run_discovery(self, releases=()):
        old = Path.cwd()
        os.chdir(self.root)
        try:
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.root / "output"), "GITHUB_RUN_NUMBER": "7",
                                          "INPUT_DEBUGGER_TAG": "", "INPUT_CSHARP_TAG": ""}), \
                 patch.object(discover, "tags", side_effect=lambda name: self.debuggers if name == "Samsung/netcoredbg" else self.csharp), \
                 patch.object(discover, "gh_pages", return_value=list(releases)), \
                 patch.object(discover, "recipe_fingerprint", return_value="recipe"), \
                 contextlib.redirect_stdout(io.StringIO()):
                discover.discover()
            return json.loads((self.root / "candidate-matrix.json").read_text())["include"]
        finally:
            os.chdir(old)

    def release(self, candidate, published):
        return dict(draft=not published, tag_name="csharp-netcoredbg-v" + candidate["version"],
                    body="<!-- netcoredbg-variant: " + json.dumps(dict(candidate, published=published)) + " -->")

    def test_detects_tag_without_release(self):
        self.debuggers["3.3.0-1100"] = "d" * 40
        self.assertEqual({c["debuggerTag"] for c in self.run_discovery()}, set(self.debuggers))

    def test_moved_baseline_tag_is_rejected(self):
        self.debuggers[self.config["baselineTag"]] = "e" * 40
        with self.assertRaisesRegex(AssertionError, "moved"):
            self.run_discovery()

    def test_identical_published_inputs_are_skipped(self):
        candidate = self.run_discovery()[0]
        self.assertEqual(self.run_discovery([self.release(candidate, True)]), [])

    def test_new_csharp_revalidates_last_published_debugger(self):
        candidate = self.run_discovery()[0]
        self.csharp["v2.149.1-prerelease"] = "d" * 40
        found = self.run_discovery([self.release(candidate, True)])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["csharpSha"], "d" * 40)

    def test_failed_older_tag_does_not_hide_new_tag(self):
        self.debuggers["3.3.0-1100"] = "d" * 40
        self.debuggers["3.4.0-1200"] = "e" * 40
        candidates = self.run_discovery()
        self.assertEqual(candidates[0]["debuggerTag"], "3.4.0-1200")
        self.assertEqual(len(candidates), 3)

    def test_interrupted_upload_reuses_original_version(self):
        candidate = self.run_discovery()[0]
        candidate["version"] = "0.1.2"
        candidates = self.run_discovery([self.release(candidate, False)])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].pop("resumeRelease"), "csharp-netcoredbg-v0.1.2")
        self.assertEqual(candidates[0], candidate)


if __name__ == "__main__":
    unittest.main()
