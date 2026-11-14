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
from lifecycle import candidate as candidate_tools


class LifecyclePreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest_count = 0
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

    def manifest(self, base=None, modules=None, source_commit="0" * 40):
        base = base or self.base()
        self.manifest_count += 1
        output = self.root / f"candidate-{self.manifest_count}.vsix"
        metadata = candidate_tools.build_candidate(base, modules or self.modules, "win32-arm64", source_commit,
                                                    output, hashlib.sha256(base.read_bytes()).hexdigest())
        manifest = self.root / f"candidate-manifest-{self.manifest_count}.json"
        document = {"schema": 1, "candidate": metadata}
        self.write_manifest(manifest, document)
        return base, output, manifest, document

    def write_manifest(self, manifest, document):
        manifest.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return hashlib.sha256(manifest.read_bytes()).hexdigest()

    def load_manifest(self, base, manifest, **overrides):
        inputs = {"manifest": manifest, "expected_manifest_sha": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                  "base": base, "modules": self.modules, "target": "win32-arm64", "source_commit": "0" * 40,
                  "expected_base_sha": hashlib.sha256(base.read_bytes()).hexdigest()}
        inputs.update(overrides)
        return candidate_tools.load_candidate_manifest(**inputs)

    def rewrite_candidate(self, output, manifest, document, replace=None, extra=(), drop=()):
        with zipfile.ZipFile(output) as archive:
            entries = [(info, archive.read(info)) for info in archive.infolist()]
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for info, data in entries:
                if info.filename not in drop:
                    archive.writestr(info, (replace or {}).get(info.filename, data))
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for name, data in extra:
                    entry = zipfile.ZipInfo()
                    entry.filename = name
                    archive.writestr(entry, data)
        document["candidate"]["sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        self.write_manifest(manifest, document)

    def staging_inputs(self):
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
        return ["prepare.py", "--base-vsix", str(base), "--base-sha256", hashlib.sha256(base.read_bytes()).hexdigest(),
                "--runtime-vsix", str(runtime), "--runtime-sha256", hashlib.sha256(runtime.read_bytes()).hexdigest(),
                "--editor", str(editor), "--editor-cli", str(cli), "--dotnet", str(dotnet), "--sdk-version", "10.0.403",
                "--scenario", "native-f5", "--cycles", "2"], base

    def test_shared_builder_compatibility_and_exact_candidate_reuse_without_rebuilding(self):
        self.assertIs(preparation.build_candidate, candidate_tools.build_candidate)
        self.assertIs(preparation.FILE_APP_MODULES, candidate_tools.FILE_APP_MODULES)
        base, output, manifest, document = self.manifest()
        original = output.read_bytes()
        before = json.loads(json.dumps(document["candidate"]))
        with mock.patch.object(candidate_tools, "build_candidate", side_effect=AssertionError("must not rebuild")):
            validated = self.load_manifest(base, manifest)
            # A validated in-memory snapshot prevents a source-file race.
            output.write_bytes(b"changed after validation")
            profile = self.root / "profile"
            profile.mkdir()
            local, reuse = candidate_tools.copy_candidate_manifest(validated, profile / "local-lifecycle.vsix")
        self.assertEqual((profile / "local-lifecycle.vsix").read_bytes(), original)
        self.assertEqual({**local, "path": before["path"]}, before)
        self.assertEqual(document["candidate"], before)
        self.assertEqual(local["buildId"], before["buildId"])
        self.assertEqual(reuse, {"manifestPath": str(manifest.resolve()),
                                "manifestSha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                "sourcePath": str(output.resolve()), "sourceSha256": before["sha256"], "method": "byte-copy"})

    def test_reuse_checks_raw_manifest_and_candidate_hashes(self):
        base, output, manifest, _ = self.manifest()
        with self.assertRaisesRegex(ValueError, "manifest SHA-256"):
            self.load_manifest(base, manifest, expected_manifest_sha="f" * 64)
        output.write_bytes(output.read_bytes() + b"altered raw container")
        with self.assertRaisesRegex(ValueError, "Candidate SHA-256"):
            self.load_manifest(base, manifest)
        self.assertFalse((self.root / "profile").exists())

    def test_reuse_requires_current_source_modules_base_and_native_identity(self):
        base, _, manifest, _ = self.manifest()
        for changes, message in (({"source_commit": "1" * 40}, "sourceCommit"),
                                 ({"target": "win32-x64"}, "target"),
                                 ({"expected_base_sha": "f" * 64}, "Base VSIX SHA-256")):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                self.load_manifest(base, manifest, **changes)
        module = self.modules / preparation.FILE_APP_MODULES[0]
        module.write_bytes(module.read_bytes() + b"different current module")
        with self.assertRaisesRegex(ValueError, "ownedModules"):
            self.load_manifest(base, manifest)

    def test_reuse_rejects_forged_metadata_even_with_a_rehashed_manifest(self):
        base, _, manifest, document = self.manifest()
        original = json.loads(json.dumps(document))
        changes = {"sourceCommit": "1" * 40, "target": "win32-x64", "baseVsixSha256": "f" * 64,
                   "ownedModules": {}, "buildId": "f" * 64, "version": "0.0.0", "localOnly": 1,
                   "published": True, "unchangedEntries": 999, "unchangedPayloadDigest": "f" * 64}
        for name, value in changes.items():
            changed = json.loads(json.dumps(original))
            changed["candidate"][name] = value
            self.write_manifest(manifest, changed)
            with self.subTest(field=name), self.assertRaisesRegex(ValueError, name):
                self.load_manifest(base, manifest)
        document["candidate"]["extraMetadata"] = "not a builder result"
        self.write_manifest(manifest, document)
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.load_manifest(base, manifest)

    def test_reuse_checks_all_payload_bytes_including_local_metadata_and_nonowned_entries(self):
        for entry in ("extension/dist/extension.js", "extension/.debugger/netcoredbg/netcoredbg.exe",
                      "extension/.netcoredbg/" + preparation.FILE_APP_MODULES[0], "extension/package.json", "extension.vsixmanifest"):
            with self.subTest(entry=entry):
                base, output, manifest, document = self.manifest()
                self.rewrite_candidate(output, manifest, document, {entry: b"changed but raw hash repinned"})
                with self.assertRaisesRegex(ValueError, "payload differs"):
                    self.load_manifest(base, manifest)
        base, output, manifest, document = self.manifest()
        self.rewrite_candidate(output, manifest, document, extra=(("unexpected.txt", b"extra"),))
        with self.assertRaisesRegex(ValueError, "unexpected or missing"):
            self.load_manifest(base, manifest)
        base, output, manifest, document = self.manifest()
        self.rewrite_candidate(output, manifest, document, drop=("extension/dist/extension.js",))
        with self.assertRaisesRegex(ValueError, "unexpected or missing"):
            self.load_manifest(base, manifest)

    def test_reuse_rejects_wrong_manifest_schema_and_missing_metadata(self):
        base, _, manifest, original = self.manifest()
        for document in ({"schema": 2, "candidate": original["candidate"]},
                         {"schema": True, "candidate": original["candidate"]},
                         {"schema": 1, "candidate": []}, {"schema": 1, "candidate": original["candidate"], "extra": 1}):
            self.write_manifest(manifest, document)
            with self.subTest(document=document), self.assertRaisesRegex(ValueError, "schema 1"):
                self.load_manifest(base, manifest)
        original["candidate"].pop("version")
        self.write_manifest(manifest, original)
        with self.assertRaisesRegex(ValueError, "version"):
            self.load_manifest(base, manifest)

    def test_reuse_rejects_unsafe_duplicate_and_aliased_candidate_entries(self):
        for entry in ("../outside", "/absolute", "C:/absolute", "extension\\outside",
                      "extension/./outside", "extension//outside", "extension/package.json", "EXTENSION/package.json",
                      "extension/outside.", "extension/outside ", "extension/CON.txt", "extension/LPT1"):
            with self.subTest(entry=entry):
                base, output, manifest, document = self.manifest()
                self.rewrite_candidate(output, manifest, document, extra=((entry, b"bad entry"),))
                with self.assertRaisesRegex(ValueError, "Unsafe|Duplicate"):
                    self.load_manifest(base, manifest)

    def test_reuse_rejects_source_path_aliases_and_exclusive_copy_preserves_existing_files(self):
        base, output, manifest, document = self.manifest()
        original = output.read_bytes()
        document["candidate"]["path"] = str(output.parent) + "/./" + output.name
        self.write_manifest(manifest, document)
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.load_manifest(base, manifest)
        document["candidate"]["path"] = str(output.resolve())
        self.write_manifest(manifest, document)
        validated = self.load_manifest(base, manifest)
        with self.assertRaisesRegex(ValueError, "aliases"):
            candidate_tools.copy_candidate_manifest(validated, output)
        profile = self.root / "profile"
        profile.mkdir()
        local = profile / "local-lifecycle.vsix"
        local.write_bytes(b"retain previous result")
        with self.assertRaises(FileExistsError):
            candidate_tools.copy_candidate_manifest(validated, local)
        self.assertEqual(local.read_bytes(), b"retain previous result")
        self.assertEqual(output.read_bytes(), original)

    def test_actual_copy_io_failure_retains_partial_evidence_and_preserves_source(self):
        base, output, manifest, _ = self.manifest()
        validated = self.load_manifest(base, manifest)
        original = output.read_bytes()
        profile = self.root / "profile"
        profile.mkdir()
        local = profile / "local-lifecycle.vsix"
        actual_open = Path.open

        class ShortWriter:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def write(self, raw):
                return self.stream.write(raw[:8])

            def __exit__(self, *args):
                self.stream.close()

        def fail_write(path, *args, **kwargs):
            stream = actual_open(path, *args, **kwargs)
            return ShortWriter(stream) if path == local else stream

        with mock.patch.object(Path, "open", fail_write), self.assertRaisesRegex(OSError, "Incomplete"):
            candidate_tools.copy_candidate_manifest(validated, local)
        self.assertEqual(local.read_bytes(), original[:8])
        self.assertEqual(output.read_bytes(), original)

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

    def test_candidate_builder_exclusively_creates_and_preserves_existing_outputs(self):
        base = self.base()
        output = self.root / "candidate.vsix"
        output.write_bytes(b"retain original candidate or failure")
        with self.assertRaises(FileExistsError):
            self.build(base)
        self.assertEqual(output.read_bytes(), b"retain original candidate or failure")

    def test_duplicate_and_path_escape_entries_are_rejected(self):
        for name in ("../outside", "/absolute", "C:/absolute", "extension\\outside", "extension/package.json",
                     "extension/outside.", "extension/outside ", "extension/CON.txt", "extension/LPT1"):
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
        common_argv, base = self.staging_inputs()
        modules = preparation.REPO / "scripts/variant/file-based-apps"
        _, source, manifest, document = self.manifest(base, modules, "f" * 40)
        source_bytes = source.read_bytes()
        for mode, reuse in ((mode, reuse) for mode in ("native-injected", "manual-native") for reuse in (False, True)):
            with self.subTest(mode=mode, reuse=reuse):
                work = self.root / (mode + ("-reuse" if reuse else "-build"))
                argv = common_argv + ["--work-dir", str(work)]
                if mode == "manual-native":
                    argv += ["--native-f5-input", mode]
                if reuse:
                    argv += ["--candidate-manifest", str(manifest), "--candidate-manifest-sha256", hashlib.sha256(manifest.read_bytes()).hexdigest()]
                builder = mock.patch.object(preparation, "build_candidate", side_effect=AssertionError("must copy the shared candidate")) if reuse else contextlib.nullcontext()
                with mock.patch("sys.argv", argv), mock.patch.object(preparation.subprocess, "check_output", return_value="f" * 40) as git, builder, contextlib.redirect_stdout(io.StringIO()):
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
                self.assertEqual("candidateReuse" in expected, reuse)
                self.assertEqual(Path(expected["candidate"]["path"]).parent, work)
                self.assertEqual(Path(expected["candidate"]["path"]).name, "local-lifecycle.vsix")
                if reuse:
                    self.assertEqual(Path(expected["candidate"]["path"]).read_bytes(), source_bytes)
                    self.assertEqual({**expected["candidate"], "path": document["candidate"]["path"]}, document["candidate"])
                    self.assertEqual(expected["candidateReuse"]["method"], "byte-copy")

    def test_invalid_reuse_is_rejected_before_profile_creation_and_actual_git_head_is_required(self):
        common_argv, base = self.staging_inputs()
        _, _, manifest, _ = self.manifest(base, preparation.REPO / "scripts/variant/file-based-apps", "f" * 40)
        for label, manifest_sha, git_head, message in (("bad-manifest", "e" * 64, "f" * 40, "manifest SHA-256"),
                                                       ("wrong-source", hashlib.sha256(manifest.read_bytes()).hexdigest(), "e" * 40, "sourceCommit")):
            work = self.root / label
            argv = common_argv + ["--work-dir", str(work), "--candidate-manifest", str(manifest), "--candidate-manifest-sha256", manifest_sha]
            with self.subTest(label=label), mock.patch("sys.argv", argv), mock.patch.object(preparation.subprocess, "check_output", return_value=git_head), self.assertRaisesRegex(ValueError, message):
                preparation.main()
            self.assertFalse(work.exists())
        work = self.root / "existing-reuse"
        work.mkdir()
        original = work / "result.json"
        original.write_bytes(b"retain failed result")
        argv = common_argv + ["--work-dir", str(work), "--candidate-manifest", str(manifest),
                              "--candidate-manifest-sha256", hashlib.sha256(manifest.read_bytes()).hexdigest()]
        with mock.patch("sys.argv", argv), mock.patch.object(preparation.subprocess, "check_output", return_value="f" * 40), self.assertRaisesRegex(ValueError, "fresh"):
            preparation.main()
        self.assertEqual(original.read_bytes(), b"retain failed result")
        self.assertFalse((work / "local-lifecycle.vsix").exists())

    def test_candidate_manifest_flags_require_each_other_and_native_f5_before_files_are_read(self):
        required = ["prepare.py", "--base-vsix", "missing", "--base-sha256", "0" * 64, "--runtime-vsix", "missing",
                    "--runtime-sha256", "0" * 64, "--editor", "missing", "--editor-cli", "missing", "--dotnet", "missing",
                    "--sdk-version", "10.0.403", "--work-dir", "missing"]
        for flags, message in ((["--candidate-manifest", "missing"], "required together"),
                               (["--candidate-manifest-sha256", "0" * 64], "required together"),
                               (["--candidate-manifest", "missing", "--candidate-manifest-sha256", "0" * 64], "only valid with --scenario native-f5")):
            error = io.StringIO()
            with self.subTest(flags=flags), mock.patch("sys.argv", required + flags), contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as caught:
                preparation.main()
            self.assertEqual(caught.exception.code, 2)
            self.assertIn(message, error.getvalue())

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
