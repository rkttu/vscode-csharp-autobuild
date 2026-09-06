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
import versioning


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
        return dict(draft=not published, tag_name=candidate["releaseTag"],
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
        self.assertEqual(candidates[-1]["debuggerTag"], "3.4.0-1200")
        self.assertEqual([c["revision"] for c in candidates], [1, 2, 3])
        self.assertEqual(len(candidates), 3)

    def test_interrupted_upload_reuses_original_version(self):
        candidate = self.run_discovery()[0]
        candidate.update(versioning.identity(candidate["csharpTag"], candidate["debuggerTag"], candidate["debuggerSha"], 7))
        candidates = self.run_discovery([self.release(candidate, False)])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].pop("resumeRelease"), candidate["releaseTag"])
        self.assertEqual(candidates[0], candidate)

    def test_first_version_follows_csharp(self):
        self.assertEqual(self.run_discovery()[0]["version"], "2.148.23001")

    def test_debugger_update_increments_same_csharp_revision(self):
        first = self.run_discovery()[0]
        self.debuggers["3.3.0-1100"] = "d" * 40
        found = self.run_discovery([self.release(first, True)])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["version"], "2.148.23002")

    def test_new_csharp_patch_resets_revision(self):
        first = self.run_discovery()[0]
        self.csharp["v2.148.24-prerelease"] = "d" * 40
        found = self.run_discovery([self.release(first, True)])
        self.assertEqual(found[0]["version"], "2.148.24001")

    def test_dry_runs_do_not_consume_revisions(self):
        self.assertEqual(self.run_discovery()[0]["version"], self.run_discovery()[0]["version"])

    def test_old_failed_tag_cannot_downgrade_published_engine(self):
        self.debuggers["3.3.0-1100"] = "d" * 40
        latest = self.run_discovery()[-1]
        self.assertEqual(self.run_discovery([self.release(latest, True)]), [])

    def test_draft_reserves_revision_for_other_candidates(self):
        first = self.run_discovery()[0]
        self.debuggers["3.3.0-1100"] = "d" * 40
        candidates = self.run_discovery([self.release(first, False)])
        self.assertEqual([c["revision"] for c in candidates], [1, 2])


if __name__ == "__main__":
    unittest.main()
