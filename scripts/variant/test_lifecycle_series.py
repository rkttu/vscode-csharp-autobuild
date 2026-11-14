"""Synthetic series protocol tests: no editor, native input or human attestation."""
import argparse
import base64
import copy
import contextlib
import importlib.util
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("lifecycle_series", Path(__file__).parent / "lifecycle/series.py")
series = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(series)


class SeriesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name).resolve()
        self.root = self.parent / "series"
        self.source = {"commit": "a" * 40, "files": {"synthetic": {"sha256": "b" * 64}}}
        self.inputs = {name: {"path": str(self.parent / (name + ".exe")), "sha256": "c" * 64, "bytes": 1, "version": "synthetic"}
                       for name in ("python", "node", "powershell")}
        self.config = {"schema": 1, "nativeF5Input": "native-injected", "launcherDeadlineSeconds": 2400,
                       "executables": {name: {"path": value["path"], "version": value["version"]} for name, value in self.inputs.items()},
                       "preparation": {}, "conditions": {name: "declared synthetic condition" for name in series.CONDITIONS},
                       "declaredMetadata": {name: "declared synthetic metadata" for name in series.METADATA}}
        for name in ("baseVsix", "runtimeVsix", "editor", "editorCli", "dotnet"):
            file = self.parent / name
            file.write_bytes(b"inert unit fixture")
            self.config["preparation"][name] = str(file)
        self.config["preparation"].update(baseSha256=series.digest(b"inert unit fixture"), runtimeSha256=series.digest(b"inert unit fixture"), sdkVersion="10.0.403")
        self.config_file = self.parent / "inputs.json"
        self.write(self.config_file, self.config)

    @staticmethod
    def write(file, value):
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def snapshot(file, data=None):
        data = file.read_bytes() if data is None else data
        return {"path": str(file), "size": len(data), "sha256": series.digest(data), "base64": base64.b64encode(data).decode()}

    def plan(self, mode="native-injected"):
        self.config["nativeF5Input"] = mode
        self.write(self.config_file, self.config)

        def build(base, modules, target, commit, output, expected_sha):
            output.write_bytes(b"one immutable synthetic ZIP")
            return {"path": str(output), "sha256": series.digest(output.read_bytes()), "buildId": "d" * 64,
                    "sourceCommit": commit, "target": target, "ownedModules": {"entry.cjs": "e" * 64},
                    "localOnly": True, "published": False, "version": "11.7.18004", "baseVsixSha256": expected_sha}
        with mock.patch.object(series, "source_snapshot", return_value=self.source), mock.patch.object(series, "capture_inputs", return_value=self.inputs), mock.patch.object(series.candidate, "build_candidate", side_effect=build) as builder:
            result = series.plan_series(self.root, self.config_file)
        self.assertEqual(builder.call_count, 1)
        return result

    def pins(self):
        return mock.patch.multiple(series, source_snapshot=mock.Mock(return_value=self.source), capture_inputs=mock.Mock(return_value=self.inputs))

    def fake_preparation(self, plan, profile="r01"):
        work = self.root / profile
        for directory in ("profile", "extensions", "workspace", "driver", "appdata", "localappdata", "dotnet-home", "nuget-packages", "nuget-cache", "tmp", "profile/logs"):
            (work / directory).mkdir(parents=True, exist_ok=True)
        local = work / "local-lifecycle.vsix"
        local.write_bytes((self.root / "candidate.vsix").read_bytes())
        candidate = {**plan["candidate"], "path": str(local)}
        expected = {"schema": 1, "scenario": "native-f5", "cycles": 10, "candidate": candidate,
                    "nativeF5": {"nonce": "profile-" + profile, "inputMode": plan["nativeF5Input"]},
                    "scope": {"localOnly": True, "published": False, "qualification": False},
                    "harness": {"native-f5-input.cjs": series.digest(b"inert helper")}}
        (work / "driver/native-f5-input.cjs").write_bytes(b"inert helper")
        self.write(work / "expected.json", expected)
        return expected

    def passing_profile(self, plan, profile="r01"):
        work = self.root / profile
        expected = self.fake_preparation(plan, profile)
        with self.pins():
            before = series.freeze_snapshot(self.root, plan)
        self.write(self.root / ("prepare-" + profile + "-result.json"), {"success": True, "exitCode": 0, "expected": series.proof(work / "expected.json"), "before": before})
        self.write(work / "launch.json", {"work": str(work), "freshProfile": True, "visibleWindowRequested": True, "pid": 123})
        self.write(work / "launcher-result.json", {"success": True, "editorExitCode": 0, "work": str(work), "pid": 123,
                   "candidateSha256": plan["candidate"]["sha256"], "visibleWindowRequested": True, "nativeInputMode": plan["nativeF5Input"]})
        fixture = (series.LIFECYCLE / "fixtures/web.cs").read_bytes()
        source = work / "workspace/a.cs"
        previous_source = fixture
        renderer = work / "profile/logs/renderer.log"
        renderer_text, output_text, trace = "", "", []
        output_log = work / "profile/logs/output.log"
        result = {"success": True, "expected": expected, "safetyTimeoutMilliseconds": 90000, "cleanup": [],
                  "phases": [{"label": label, "outcome": "passed", "elapsedMilliseconds": 1, "startedAtMilliseconds": index} for index, label in enumerate(series.phase_labels())],
                  "scope": {"platform": "win32-arm64", "noFolderWindow": True, "targetCommandApiLaunch": False, "hardwareInputIndependentlyVerified": False,
                            "localOnly": True, "published": False, "qualification": False},
                  "nativeF5": {"inputMode": plan["nativeF5Input"], "inputs": [], "postStartApiActions": []},
                  "installedExtension": {"path": str(work / "extensions/local-candidate"), "version": plan["candidate"]["version"],
                                         "build": {"lifecycleBuildId": plan["candidate"]["buildId"], "localCandidate": True, "target": "win32-arm64", "lifecycleSourceCommit": plan["source"]["commit"]}},
                  "installedDependency": {"path": str(work / "extensions/runtime"), "version": "3.2.0"},
                  "installedModules": plan["candidate"]["ownedModules"], "launches": []}
        for sequence in range(1, 11):
            suffix = f"{sequence:02}"
            nonce = profile + "-launch-" + suffix
            revision = "initial" if sequence == 1 else "retry-f5-" + str(sequence)
            saved = fixture.replace(b'const string revision = "initial";', ('const string revision = "' + revision + '";').encode())
            request_file, receipt_file = work / ("needs-f5-input-" + suffix + ".json"), work / ("f5-input-action-" + suffix + ".json")
            observation, action = work / ("observation-" + suffix + ".json"), work / ("action-" + suffix + ".json")
            request = {"schema": 1, "nonce": expected["nativeF5"]["nonce"], "sequence": sequence, "launchToken": nonce,
                       "windowTitle": "native " + expected["nativeF5"]["nonce"], "source": str(source), "isDirty": sequence > 1,
                       "action": "press-key", "key": "F5", "inputMode": plan["nativeF5Input"], "mechanism": plan["nativeF5Input"], "noFolderWindow": True,
                       "diskBefore": self.snapshot(source, previous_source), "bufferBefore": {"bytes": len(saved), "sha256": series.digest(saved)},
                       "requestedAtUtc": "2026-11-09T00:00:00.000Z", "expiresAtUtc": "2026-11-09T00:01:30.000Z"}
            self.write(request_file, request)
            receipt = {key: request[key] for key in ("schema", "nonce", "sequence", "launchToken", "windowTitle", "action", "key", "inputMode", "mechanism")}
            receipt.update(requestSha256=series.proof(request_file)["sha256"], editorFocusedBeforeInput=True,
                           observedWindowTitle=request["windowTitle"], observationPath=str(observation), inputRecordPath=str(action))
            if plan["nativeF5Input"] == "manual-native":
                receipt.update(tool="human-observer", actor={"id": "synthetic-test-only", "type": "human"}, evidenceKind="human-attestation",
                               automationUsed=False, targetCommandApiUsed=False, nativeExecutionVerified=False, hardwareKeypressIndependentlyVerified=False,
                               oneF5KeyPressed=True, inputOccurredDuringRequest=True, observationNote="SYNTHETIC; no key pressed", attestedAtUtc="2026-11-09T00:00:01.000Z")
            else:
                receipt.update(tool="sky.press_key", windowId="synthetic-only", inputAtUtc="2026-11-09T00:00:01.000Z")
            for file, value in ((receipt_file, receipt), (observation, {"synthetic": True}), (action, {"synthetic": True})):
                self.write(file, value)
            if plan["nativeF5Input"] == "manual-native":
                self.write(self.root / f"manual-input-{profile}-{suffix}-result.json", {"success": True, "exitCode": 0, "receipt": series.proof(receipt_file)})
            dispatch = f"[{sequence}] KeybindingService#dispatch F5 [ Will dispatch command netcoredbg.debugActiveFile ]"
            command = f"[{sequence}] CommandService#executeCommand netcoredbg.debugActiveFile"
            tail = dispatch + "\n" + command + "\n"
            route = {"path": str(renderer), "offsetCharacters": len(renderer_text.encode("utf-16-le")) // 2,
                     "prefixSha256": series.digest(renderer_text.encode()), "tailCharacters": len(tail), "tailSha256": series.digest(tail.encode()),
                     "f5Dispatches": [dispatch], "targetCommands": [command]}
            renderer_text += tail
            output = work / "tmp" / ("output-" + suffix)
            pid = 1000 + sequence
            response = {"value": 42, "nonce": nonce, "revision": revision, "pid": pid}
            launch = {"label": "F5-" + str(sequence), "source": str(source), "revision": revision, "sessionId": profile + "-session-" + suffix,
                      "nonce": nonce, "output": str(output), "base": str(work / "tmp"), "program": str(output / "FileApp.dll"), "pid": pid, "port": 19000,
                      "response": response, "terminatedAtMilliseconds": 1, "pidGoneAtMilliseconds": 2, "portReusableAtMilliseconds": 3, "outputRemovedAtMilliseconds": 4}
            launch["capturedSessions"] = [{"sessionId": launch["sessionId"], "terminated": True, "primary": True, "pid": pid,
                                          "program": launch["program"], "output": launch["output"], "terminatedAtMilliseconds": 1}]
            launch["cleanupObservation"] = {key: launch[key] for key in ("base", "sessionId", "pid", "port", "output")}
            launch["cleanupObservation"].update(sessionTerminated=True, pidExited=True, portReusable=True, outputAbsent=True,
                                                terminalQueuesEmpty=True, observedAtMilliseconds={"termination": 1, "pid": 2, "port": 3, "outputAndQueues": 4})
            item = {"sequence": sequence, "label": launch["label"], "request": request, "receipt": receipt,
                    "requestSnapshot": self.snapshot(request_file), "receiptSnapshot": self.snapshot(receipt_file),
                    "observationSnapshot": self.snapshot(observation), "inputRecordSnapshot": self.snapshot(action),
                    "diskAfter": self.snapshot(source, saved), "savedEvents": [{"source": str(source), "disk": self.snapshot(source, saved)}],
                    "route": route, "builds": [{"output": str(output), "args": ["build", str(source), "--output", str(output)]}],
                    "breakpoint": {"source": str(source), "expression": "marker", "result": "40", "line": 5}, "response": response}
            output_tail = "dotnet " + " ".join(json.dumps(arg) for arg in item["builds"][0]["args"]) + "\nPhase completed: Starting netcoredbg\n"
            item["outputEvidence"] = {"path": str(output_log), "offsetCharacters": len(output_text), "prefixSha256": series.digest(output_text.encode()),
                                      "tailCharacters": len(output_tail), "tailSha256": series.digest(output_tail.encode()),
                                      "buildCommands": item["builds"], "completedPhaseDiagnostics": ["Phase completed: Starting netcoredbg"]}
            output_text += output_tail
            launch["dap"] = [
                {"type": "event", "event": "process", "body": {"isLocalProcess": True, "systemProcessId": pid}},
                {"type": "event", "event": "stopped", "body": {"reason": "breakpoint"}},
                {"type": "response", "command": "stackTrace", "request_seq": 10, "success": True, "body": {"stackFrames": [{"source": {"path": str(source)[0].lower() + str(source)[1:]}, "line": 5}]}},
                {"type": "response", "command": "evaluate", "request_seq": 11, "success": True, "body": {"result": "40"}},
            ]
            for request_message in ({"type": "request", "command": "stackTrace", "seq": 10}, {"type": "request", "command": "evaluate", "seq": 11, "arguments": {"expression": "marker"}}):
                trace.append({"event": "dap-send", "detail": {"label": launch["label"], "sessionId": launch["sessionId"], "message": request_message}})
            for message in launch["dap"]:
                trace.append({"event": "dap-receive", "detail": {"label": launch["label"], "sessionId": launch["sessionId"], "message": message}})
            trace.append({"event": "http-ready", "detail": {"label": launch["label"], "body": response}})
            result["nativeF5"]["postStartApiActions"] += [{"action": "DAP continue", "sessionId": launch["sessionId"], "sequence": sequence}, {"action": "vscode.debug.stopDebugging", "sessionId": launch["sessionId"], "sequence": sequence}]
            result["nativeF5"]["inputs"].append(item)
            result["launches"].append(launch)
            previous_source = saved
        renderer.write_text(renderer_text, encoding="utf-8", newline="")
        output_log.write_text(output_text, encoding="utf-8", newline="")
        source.write_bytes(previous_source)
        self.write(work / "result.json", result)
        self.write(work / "f5-input-closed.json", {"nonce": expected["nativeF5"]["nonce"], "reason": "10-cycle control completed"})
        (work / "trace.jsonl").write_text("".join(json.dumps(event) + "\n" for event in trace), encoding="utf-8")
        return result

    def test_plan_builds_once_and_requires_a_new_root(self):
        plan = self.plan()
        self.assertEqual(plan["profiles"], ["r01", "r02"])
        self.assertEqual(plan["cycles"], 10)
        self.assertFalse(plan["scope"]["qualification"])
        original = (self.root / "series-plan.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "nonexistent"):
            series.plan_series(self.root, self.config_file)
        self.assertEqual(original, (self.root / "series-plan.json").read_bytes())

    def test_plan_failure_is_retained_in_owned_root(self):
        with mock.patch.object(series, "validate_config", side_effect=ValueError("bad pin")):
            with self.assertRaisesRegex(ValueError, "bad pin"):
                series.plan_series(self.root, self.config_file)
        self.assertEqual(series.read_json(self.root / "first-failure.json")["action"], "plan")
        self.assertFalse((self.root / "series-plan.json").exists())

    def test_unknown_root_is_never_poisoned(self):
        self.root.mkdir()
        (self.root / "existing").write_text("preserve")
        with self.assertRaises(FileNotFoundError):
            series.stage(self.root, "run", "r01", lambda *_: self.fail("must not run"))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["existing"])

    def test_source_and_executable_changes_fail_before_operation(self):
        for section in ("source_snapshot", "capture_inputs"):
            with self.subTest(section=section):
                self.root = self.parent / section
                plan = self.plan()
                with self.pins(), mock.patch.object(series, section, return_value={"changed": True}):
                    with self.assertRaisesRegex(ValueError, "changed"):
                        series.stage(self.root, "prepare", "r01", lambda *_: self.fail("must not run"))
                self.assertFalse(series.read_json(self.root / "prepare-r01-result.json")["success"])
                self.assertTrue((self.root / "first-failure.json").exists())

    def test_profile_two_cannot_be_prepared_before_complete_profile_one(self):
        self.plan()
        with self.pins(), self.assertRaises(FileNotFoundError):
            series.stage(self.root, "prepare", "r02", lambda root, plan: series.prepare_profile(root, plan, "r02"))
        self.assertFalse((self.root / "r02").exists())
        self.assertTrue((self.root / "first-failure.json").exists())

    def test_preparer_receives_exact_manifest_and_no_second_build(self):
        plan = self.plan()
        def prepare(argv, **kwargs):
            self.assertEqual(argv[argv.index("--candidate-manifest") + 1], str(self.root / "candidate-manifest.json"))
            self.assertEqual(argv[argv.index("--candidate-manifest-sha256") + 1], plan["candidateManifest"]["sha256"])
            self.fake_preparation(plan)
            return subprocess.CompletedProcess(argv, 0)
        with self.pins(), mock.patch.object(series.subprocess, "run", side_effect=prepare), mock.patch.object(series.candidate, "build_candidate", side_effect=AssertionError("must reuse")):
            record = series.stage(self.root, "prepare", "r01", lambda root, value: series.prepare_profile(root, value, "r01"))
        self.assertTrue(record["success"])
        self.assertEqual((self.root / "candidate.vsix").read_bytes(), (self.root / "r01/local-lifecycle.vsix").read_bytes())

    def test_overlap_and_replay_latch_failure(self):
        plan = self.plan()
        self.write(self.root / "operation.lock", {"action": "run", "profile": "r01"})
        self.fake_preparation(plan)
        with self.pins(), self.assertRaises(FileExistsError):
            series.stage(self.root, "prepare", "r02", lambda *_: {})
        self.assertTrue((self.root / "r01/f5-input-closed.json").exists())
        self.assertTrue((self.root / "operation.lock").exists())

    def test_stop_preserves_first_failure_and_closes_only_active_profile(self):
        plan = self.plan()
        self.fake_preparation(plan)
        self.write(self.root / "operation.lock", {"action": "run", "profile": "r01"})
        series.stop_series(self.root, "observed uncertain input")
        original = (self.root / "first-failure.json").read_bytes()
        closed = series.read_json(self.root / "r01/f5-input-closed.json")
        self.assertTrue(closed["closedBySeries"])
        self.assertEqual(closed["nonce"], "profile-r01")
        series.stop_series(self.root, "later reason cannot replace first")
        self.assertEqual(original, (self.root / "first-failure.json").read_bytes())
        self.assertFalse((self.root / "r02").exists())

    def test_partial_failure_marker_blocks_every_next_stage(self):
        plan = self.plan()
        (self.root / "first-failure.json.tmp").write_bytes(b"partial")
        with self.pins(), self.assertRaisesRegex(ValueError, "first failure"):
            series.stage(self.root, "prepare", "r01", lambda *_: self.fail("must not run"))
        self.assertEqual((self.root / "first-failure.json.tmp").read_bytes(), b"partial")

    def test_stop_selected_at_publication_boundary_cannot_leave_success(self):
        plan = self.plan()
        actual = series.freeze_snapshot
        calls = 0
        def snapshot(root, value):
            nonlocal calls
            result = actual(root, value)
            calls += 1
            if calls == 2:
                series.stop_series(root, "stop after postflight")
            return result
        with self.pins(), mock.patch.object(series, "freeze_snapshot", side_effect=snapshot), self.assertRaisesRegex(ValueError, "First failure"):
            series.stage(self.root, "prepare", "r01", lambda *_: {})
        self.assertFalse(series.read_json(self.root / "prepare-r01-result.json")["success"])

    def test_full_synthetic_injected_and_manual_evidence_pass(self):
        for mode in ("native-injected", "manual-native"):
            with self.subTest(mode=mode):
                self.root = self.parent / mode
                plan = self.plan(mode)
                self.passing_profile(plan)
                self.assertEqual(series.validate_profile_evidence(self.root, plan, "r01")["cycles"], 10)

    def test_incomplete_or_forged_evidence_never_passes(self):
        mutations = {
            "nine launches": lambda result: result["launches"].pop(),
            "first failure": lambda result: result.update(firstFailure={"error": "original"}),
            "cleanup false": lambda result: result["launches"][0]["cleanupObservation"].update(terminalQueuesEmpty=False),
            "wrong HTTP": lambda result: result["nativeF5"]["inputs"][0]["response"].update(value=41),
            "wrong source": lambda result: result["nativeF5"]["inputs"][1]["diskAfter"].update(sha256="f" * 64),
            "route not F5": lambda result: result["nativeF5"]["inputs"][0]["route"].update(f5Dispatches=["unrelated"]),
            "wrong breakpoint": lambda result: result["nativeF5"]["inputs"][0]["breakpoint"].update(result="41"),
            "session not terminated": lambda result: result["launches"][0]["capturedSessions"][0].update(terminated=False),
            "mode switched": lambda result: result["nativeF5"].update(inputMode="manual-native"),
            "missing phase": lambda result: result["phases"].pop(),
            "wrong DAP": lambda result: result["launches"][0]["dap"][3]["body"].update(result="41"),
            "missing output": lambda result: result["nativeF5"]["inputs"][0].pop("outputEvidence"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.root = self.parent / name
                plan = self.plan()
                result = self.passing_profile(plan)
                mutate(result)
                self.write(self.root / "r01/result.json", result)
                with self.assertRaises((ValueError, KeyError)):
                    series.validate_profile_evidence(self.root, plan, "r01")

    def test_zero_exit_with_incomplete_driver_result_records_failed_run(self):
        plan = self.plan()
        result = self.passing_profile(plan)
        result["launches"].pop()
        self.write(self.root / "r01/result.json", result)
        # Emulate a fresh launch whose mock child writes these fixture results.
        generated = {name: (self.root / "r01" / name).read_bytes() for name in ("launch.json", "result.json", "launcher-result.json", "f5-input-closed.json")}
        for name in generated:
            (self.root / "r01" / name).unlink()
        def launch(argv, **kwargs):
            for name, data in generated.items():
                (self.root / "r01" / name).write_bytes(data)
            return subprocess.CompletedProcess(argv, 0)
        with self.pins(), mock.patch.object(series.subprocess, "run", side_effect=launch), self.assertRaisesRegex(ValueError, "Incomplete"):
            series.stage(self.root, "run", "r01", lambda root, value: series.run_profile(root, value, "r01"))
        self.assertFalse(series.read_json(self.root / "run-r01-result.json")["success"])
        self.assertTrue((self.root / "first-failure.json").exists())

    def test_manual_helper_refusal_latches_failure_without_sending_input(self):
        plan = self.plan("manual-native")
        self.passing_profile(plan)
        self.write(self.root / "operation.lock", {"action": "run", "profile": "r01"})
        # Remove synthetic wrapper evidence; the attempted helper is mocked.
        (self.root / "manual-input-r01-01-result.json").unlink()
        options = argparse.Namespace(sequence=1, observer="synthetic", observed_window_title="synthetic", note="synthetic only", confirm_human_f5=True)
        with self.pins(), mock.patch.object(series.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as child, self.assertRaisesRegex(ValueError, "refused"):
            series.stage(self.root, "manual-input", "r01", lambda root, value: series.manual_input(root, value, "r01", options), exclusive=False, suffix="01")
        self.assertEqual(child.call_count, 1)
        self.assertIn("native-f5-input.cjs", child.call_args.args[0][1])
        self.assertTrue((self.root / "first-failure.json").exists())
        self.assertFalse(series.read_json(self.root / "manual-input-r01-01-result.json")["success"])

    def test_verify_is_read_only_and_requires_two_complete_profiles(self):
        plan = self.plan()
        evidence = self.passing_profile(plan)
        self.write(self.root / "run-r01-result.json", {"success": True, "exitCode": 0, "evidence": series.validate_profile_evidence(self.root, plan, "r01")})
        before = sorted(str(file.relative_to(self.root)) for file in self.root.rglob("*"))
        with self.pins(), self.assertRaises(FileNotFoundError):
            series.verify_series(self.root)
        self.assertEqual(before, sorted(str(file.relative_to(self.root)) for file in self.root.rglob("*")))
        self.passing_profile(plan, "r02")
        self.write(self.root / "run-r02-result.json", {"success": True, "exitCode": 0, "evidence": series.validate_profile_evidence(self.root, plan, "r02")})
        with self.pins():
            summary = series.verify_series(self.root)
        self.assertEqual(summary["completedCycles"], 20)
        self.assertFalse(summary["qualification"])

    def test_postflight_change_and_repeated_stage_cannot_publish_success(self):
        self.plan()
        with self.pins():
            def changed(root, plan):
                self.source = {"commit": "f" * 40, "files": {}}
                return {}
            with mock.patch.object(series, "source_snapshot", side_effect=lambda: self.source), self.assertRaisesRegex(ValueError, "changed"):
                series.stage(self.root, "prepare", "r01", changed)
        self.assertFalse(series.read_json(self.root / "prepare-r01-result.json")["success"])
        original = (self.root / "prepare-r01-attempt.json").read_bytes()
        with self.pins(), self.assertRaises(FileExistsError):
            series.stage(self.root, "prepare", "r01", lambda *_: {})
        self.assertEqual(original, (self.root / "prepare-r01-attempt.json").read_bytes())

    def test_manual_final_wrapper_is_joined_after_completed_driver(self):
        plan = self.plan("manual-native")
        self.passing_profile(plan)
        work = self.root / "r01"
        generated = {name: (work / name).read_bytes() for name in ("launch.json", "result.json", "launcher-result.json", "f5-input-closed.json")}
        wrapper = self.root / "manual-input-r01-10-result.json"
        wrapper_bytes = wrapper.read_bytes()
        wrapper.unlink()
        for name in generated:
            (work / name).unlink()
        def launch(argv, **kwargs):
            for name, data in generated.items():
                (work / name).write_bytes(data)
            return subprocess.CompletedProcess(argv, 0)
        with self.pins(), mock.patch.object(series.subprocess, "run", side_effect=launch), mock.patch.object(series.time, "sleep", side_effect=lambda _: wrapper.write_bytes(wrapper_bytes)) as wait:
            result = series.stage(self.root, "run", "r01", lambda root, value: series.run_profile(root, value, "r01"))
        self.assertTrue(result["success"])
        self.assertEqual(wait.call_count, 1)

    def test_verify_rechecks_stop_and_rejects_active_or_incomplete_stage(self):
        plan = self.plan()
        for profile in series.PROFILES:
            self.passing_profile(plan, profile)
            self.write(self.root / f"run-{profile}-result.json", {"success": True, "exitCode": 0, "evidence": series.validate_profile_evidence(self.root, plan, profile)})
        actual = series.passed_profile
        def during_verification(root, value, profile):
            evidence = actual(root, value, profile)
            if profile == "r01":
                series.stop_series(root, "operator stopped during point-in-time read")
            return evidence
        with self.pins(), mock.patch.object(series, "passed_profile", side_effect=during_verification), self.assertRaisesRegex(ValueError, "first failure"):
            series.verify_series(self.root)
        self.assertFalse((self.root / "series-result.json").exists())

    def test_bad_manual_arguments_latch_failure_in_known_series(self):
        self.plan("manual-native")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            series.main(["manual-input", "--root", str(self.root), "--profile", "r01", "--sequence", "1"])
        self.assertEqual(series.read_json(self.root / "first-failure.json")["action"], "manual-input")

    def test_self_consistent_dap_and_breakpoint_cannot_move_the_fixture_line(self):
        plan = self.plan()
        result = self.passing_profile(plan)
        result["nativeF5"]["inputs"][0]["breakpoint"]["line"] = 6
        result["launches"][0]["dap"][2]["body"]["stackFrames"][0]["line"] = 6
        trace_file = self.root / "r01/trace.jsonl"
        trace = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
        for event in trace:
            detail = event.get("detail", {})
            if event.get("event") == "dap-receive" and detail.get("label") == "F5-1" and detail.get("message", {}).get("command") == "stackTrace":
                detail["message"]["body"]["stackFrames"][0]["line"] = 6
        trace_file.write_text("".join(json.dumps(event) + "\n" for event in trace), encoding="utf-8")
        self.write(self.root / "r01/result.json", result)
        with self.assertRaisesRegex(ValueError, "exact source breakpoint"):
            series.validate_profile_evidence(self.root, plan, "r01")


if __name__ == "__main__":
    unittest.main()
