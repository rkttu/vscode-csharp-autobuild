"""Check numeric update ordering, exhaustion and release provenance."""
import unittest
import versioning


class VersioningTests(unittest.TestCase):
    def make(self, tag="v2.148.23-prerelease", revision=1):
        return versioning.identity(tag, "3.2.0-1092", "9744e1f051866215611b8440c638042aa2aa2f72", revision)

    def test_upstream_version_and_engine_are_traceable(self):
        result = self.make()
        self.assertEqual(result["version"], "2.148.23001")
        self.assertEqual(result["csharpVersion"], "2.148.23")
        self.assertEqual(result["releaseTag"], "csharp-v2.148.23-netcoredbg-v3.2.0-1092-g9744e1f05186-r1")

    def test_next_upstream_patch_sorts_after_last_revision(self):
        numeric = lambda value: tuple(map(int, value.split(".")))
        self.assertGreater(numeric(self.make("v2.148.24")["version"]), numeric(self.make(revision=999)["version"]))

    def test_invalid_or_exhausted_revision_fails(self):
        for revision in [0, 1000, -1, True, "1"]:
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                self.make(revision=revision)

    def test_unrecognized_csharp_tag_fails(self):
        for tag in ["v2.148.23.1", "2.148.23", "v2.148.23+hash", "v02.148.23"]:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self.make(tag)

    def test_encoded_integer_overflow_fails(self):
        with self.assertRaises(ValueError):
            self.make("v2.148.2147483647")

    def test_inconsistent_candidate_fails(self):
        candidate = dict(self.make(), csharpTag="v2.148.23-prerelease", debuggerTag="3.2.0-1092",
                         debuggerSha="9744e1f051866215611b8440c638042aa2aa2f72", csharpSha="c" * 40)
        versioning.validate(candidate)
        candidate["version"] = "2.148.23002"
        with self.assertRaisesRegex(ValueError, "version"):
            versioning.validate(candidate)


if __name__ == "__main__":
    unittest.main()
