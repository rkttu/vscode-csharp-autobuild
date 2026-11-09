"""Check local lifecycle candidate isolation and payload preservation."""
import hashlib
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import struct
import unittest
from unittest import mock
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
                self.assertEqual(control["inputMode"], "native-injected")
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

    def test_native_f5_input_mode_is_frozen_with_the_staged_shared_validator(self):
        editor = self.root / "editor/VSCodium.exe"
        editor.parent.mkdir()
        editor.write_bytes(b"MZ" + bytes(0x3C - 2) + struct.pack("<I", 0x40) + b"PE\0\0" + struct.pack("<H", 0xAA64))
        app = editor.parent / "resources/app"
        app.mkdir(parents=True)
        (app / "product.json").write_text(json.dumps({"applicationName": "codium", "commit": "f" * 40}))
        (app / "package.json").write_text(json.dumps({"version": "1.0.0"}))
        cli, dotnet = self.root / "codium.cmd", self.root / "dotnet.exe"
        cli.write_text("synthetic CLI; never executed")
        dotnet.write_text("synthetic SDK; never executed")
        runtime = self.root / "runtime.vsix"
        with zipfile.ZipFile(runtime, "w") as archive:
            archive.writestr("extension/package.json", json.dumps({"publisher": "ms-dotnettools", "name": "vscode-dotnet-runtime", "version": "3.2.0"}))
        base = self.base()
        for mode in ("native-injected", "manual-native"):
            with self.subTest(mode=mode):
                work = self.root / mode
                argv = ["prepare.py", "--base-vsix", str(base), "--base-sha256", hashlib.sha256(base.read_bytes()).hexdigest(),
                        "--runtime-vsix", str(runtime), "--runtime-sha256", hashlib.sha256(runtime.read_bytes()).hexdigest(),
                        "--editor", str(editor), "--editor-cli", str(cli), "--dotnet", str(dotnet), "--sdk-version", "10.0.403",
                        "--scenario", "native-f5", "--cycles", "2", "--work-dir", str(work)]
                if mode == "manual-native":
                    argv += ["--native-f5-input", mode]
                with mock.patch("sys.argv", argv), mock.patch.object(preparation.subprocess, "check_output", return_value="f" * 40) as git, contextlib.redirect_stdout(io.StringIO()):
                    preparation.main()
                git.assert_called_once_with(["git", "rev-parse", "HEAD"], cwd=preparation.REPO, text=True)
                expected = json.loads((work / "expected.json").read_text())
                self.assertEqual(expected["nativeF5"]["inputMode"], mode)
                staged = (work / "driver/native-f5-input.cjs").read_bytes()
                self.assertEqual(staged, (Path(preparation.__file__).parent / "native-f5-input.cjs").read_bytes())
                self.assertEqual(hashlib.sha256(staged).hexdigest(), expected["harness"]["native-f5-input.cjs"])
                manual = mode == "manual-native"
                self.assertEqual(expected["scope"]["humanKeypressAttestationRequired"], manual)
                self.assertEqual(expected["scope"]["nativeInjectedF5"], not manual)
                self.assertFalse(expected["scope"]["hardwareInputIndependentlyVerified"])
                self.assertFalse(expected["scope"]["qualification"])
                self.assertEqual("hardwareKeypress" in expected["scope"], not manual)
                self.assertFalse((work / "attempt.json").exists())

    def test_native_f5_rejects_unknown_input_mechanisms(self):
        for mode in ("", "manual", "sky.press_key", None, True):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "input mode"):
                preparation.native_f5_configuration(self.root, 2, mode)

    def test_native_input_option_is_rejected_for_other_scenarios_before_files_are_read(self):
        for mode in ("manual-native", "native-injected"):
            argv = ["prepare.py", "--base-vsix", "missing", "--base-sha256", "0" * 64, "--runtime-vsix", "missing",
                    "--runtime-sha256", "0" * 64, "--editor", "missing", "--editor-cli", "missing", "--dotnet", "missing",
                    "--sdk-version", "10.0.403", "--work-dir", "missing", "--native-f5-input", mode]
            error = io.StringIO()
            with self.subTest(mode=mode), mock.patch("sys.argv", argv), contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                preparation.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn("only valid with --scenario native-f5", error.getvalue())

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
