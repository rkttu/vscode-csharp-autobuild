"""Check local lifecycle candidate isolation and payload preservation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import struct
import unittest
import warnings
import zipfile

spec = importlib.util.spec_from_file_location("lifecycle_preparation", Path(__file__).parent / "lifecycle/prepare.py")
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


class LifecyclePreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.modules = self.root / "modules"
        self.modules.mkdir()
        for name in preparation.FILE_APP_MODULES:
            (self.modules / name).write_text("new owned bytes: " + name)

    def base(self, target="win32-arm64", extra=()):
        base = self.root / "base.vsix"
        package = {"publisher": "dotnetdev-kr-custom", "name": "csharp-with-netcoredbg", "version": "11.7.18004",
                   "main": "./.netcoredbg/entry.cjs", "netcoredbgBuild": {"target": target, "upstreamMain": "./dist/extension"}}
        with zipfile.ZipFile(base, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("extension/package.json", json.dumps(package))
            archive.writestr("extension.vsixmanifest", "<PackageManifest><Metadata><DisplayName>Original</DisplayName></Metadata></PackageManifest>")
            for name in preparation.FILE_APP_MODULES:
                if name != "recovery.cjs":
                    archive.writestr("extension/.netcoredbg/" + name, "old owned bytes")
            archive.writestr("extension/dist/extension.js", b"unchanged upstream")
            archive.writestr("extension/.debugger/netcoredbg/netcoredbg.exe", b"unchanged native")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for name, content in extra:
                    # Windows ZipInfo construction normalizes backslashes. Set the
                    # raw name afterwards to model an externally produced ZIP.
                    entry = zipfile.ZipInfo()
                    entry.filename = name
                    archive.writestr(entry, content)
        return base

    def build(self, base, expected_sha=None):
        output = self.root / "candidate.vsix"
        result = preparation.build_candidate(base, self.modules, "win32-arm64", "0" * 40, output,
                                              expected_sha or hashlib.sha256(base.read_bytes()).hexdigest())
        return output, result

    def test_candidate_loads_new_owned_module_and_preserves_all_other_payload_bytes(self):
        base = self.base()
        before = base.read_bytes()
        output, result = self.build(base)
        self.assertEqual(base.read_bytes(), before)
        with zipfile.ZipFile(output) as candidate:
            self.assertEqual(candidate.read("extension/dist/extension.js"), b"unchanged upstream")
            self.assertEqual(candidate.read("extension/.debugger/netcoredbg/netcoredbg.exe"), b"unchanged native")
            for name in preparation.FILE_APP_MODULES:
                self.assertEqual(candidate.read("extension/.netcoredbg/" + name), (self.modules / name).read_bytes())
            metadata = json.loads(candidate.read("extension/package.json"))
            self.assertTrue(metadata["netcoredbgBuild"]["localCandidate"])
            self.assertEqual(metadata["netcoredbgBuild"]["lifecycleBuildId"], result["buildId"])
            self.assertIn("LOCAL", metadata["displayName"])
        self.assertEqual(result["sha256"], hashlib.sha256(output.read_bytes()).hexdigest())
        self.assertEqual(result["unchangedEntries"], 2)

    def test_mismatched_input_hash_and_native_target_fail_before_output(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.build(self.base(), "f" * 64)
        self.assertFalse((self.root / "candidate.vsix").exists())
        with self.assertRaisesRegex(ValueError, "target"):
            self.build(self.base(target="win32-x64"))
        self.assertFalse((self.root / "candidate.vsix").exists())

    def test_duplicate_and_path_escape_entries_are_rejected(self):
        for name in ("../outside", "/absolute", "C:/absolute", "extension\\outside", "extension/package.json"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsafe|Duplicate"):
                self.build(self.base(extra=((name, b"unsafe"),)))
        self.assertFalse((self.root / "candidate.vsix").exists())

    def test_existing_results_are_preserved_instead_of_reusing_a_profile(self):
        work = self.root / "existing"
        work.mkdir()
        failure = work / "result.json"
        failure.write_text('initial failure')
        with self.assertRaisesRegex(ValueError, "fresh"):
            preparation.fresh_directory(work)
        self.assertEqual(failure.read_text(), 'initial failure')

    def test_native_f5_control_keeps_each_input_and_profile_attestation_separate(self):
        for cycles in range(2, 11):
            with self.subTest(cycles=cycles):
                work = self.root / f"profile-{cycles}"
                control = preparation.native_f5_configuration(work, cycles)
                self.assertIn(control["nonce"], control["windowTitle"])
                self.assertEqual([item["sequence"] for item in control["inputs"]], list(range(1, cycles + 1)))
                paths = {Path(item[key]) for item in control["inputs"] for key in ("request", "receipt")}
                paths.add(Path(control["closed"]))
                self.assertEqual(len(paths), 2 * cycles + 1)
                self.assertTrue(all(path.parent == work and not path.exists() for path in paths))
                other = preparation.native_f5_configuration(self.root / f"other-{cycles}", cycles)
                other_paths = {Path(item[key]) for item in other["inputs"] for key in ("request", "receipt")}
                other_paths.add(Path(other["closed"]))
                self.assertTrue(paths.isdisjoint(other_paths))
                self.assertNotEqual(control["nonce"], other["nonce"])

    def test_native_f5_control_rejects_out_of_range_or_noninteger_counts(self):
        for cycles in (0, 1, 11, -1, 2.5, True):
            with self.subTest(cycles=cycles), self.assertRaisesRegex(ValueError, r"2\.\.10"):
                preparation.native_f5_configuration(self.root, cycles)

    def test_pe_machine_reports_truncated_headers_and_reads_native_target(self):
        executable = self.root / "editor.exe"
        header = b"MZ" + bytes(0x3C - 2) + struct.pack("<I", 0x40)
        complete = header + b"PE\0\0" + struct.pack("<H", 0xAA64)
        for data in (b"MZ", header[:-1], header, header + b"PE\0\0", complete[:-1]):
            with self.subTest(size=len(data)):
                executable.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "Truncated PE"):
                    preparation.pe_machine(executable)
        executable.write_bytes(complete)
        self.assertEqual(preparation.pe_machine(executable), 0xAA64)


if __name__ == "__main__":
    unittest.main()
