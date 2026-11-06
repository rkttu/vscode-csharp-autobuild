"""Validate complete-STAGING native and installed-host publication controls."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[3]
DOCS = Path(__file__).parent
BASELINE = "8681a7b6e46201fb29c87efd03ae1e418c5d28e9"


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def read(file):
    return json.loads(file.read_text(encoding="utf-8-sig"))


def raw_files(work):
    return {file.relative_to(work).as_posix(): {"sha256": sha(file), "bytes": file.stat().st_size}
            for file in sorted(work.rglob("*")) if file.is_file()}


def counts(file):
    return {key: int(value) for key, value in re.findall(
        r"(?m)^[ℹ#]\s+(tests|pass|fail|cancelled|skipped|todo)\s+(\d+)\s*$", file.read_text(encoding="utf-8-sig"))}


def baseline_module(name):
    return subprocess.check_output(["git", "show", f"{BASELINE}:scripts/variant/file-based-apps/{name}"], cwd=REPO)


def validate_control(work, expected):
    result, input_record = read(work / "result.json"), read(work / "input.json")
    if not result["success"] or result["input"] != input_record or result["desiredBehaviorObserved"] is not expected:
        raise ValueError("Native result/input mismatch")
    for name, item in read(work / "hashes.json").items():
        file = work / name
        if sha(file) != item["sha256"] or file.stat().st_size != item["bytes"]:
            raise ValueError("Retained native evidence changed: " + name)
    for name, value in input_record["moduleSha256"].items():
        if sha(work / "modules" / name) != value:
            raise ValueError("Executed module differs: " + name)
    if ((work / "modules/runtime.cjs").read_bytes() != baseline_module("runtime.cjs")
            or input_record["driverSha256"] != sha(work / "native-control.cjs")
            or input_record["driverSha256"] != sha(DOCS / "native-control.cjs")
            or input_record["runnerSha256"] != sha(DOCS / "run-native-control.py")
            or input_record["node"]["sha256"] != sha(Path(input_record["node"]["executable"]))):
        raise ValueError("Runtime, driver, runner or native executable identity differs")
    current_runtime = (REPO / "scripts/variant/file-based-apps/runtime.cjs").read_bytes().replace(b"\r\n", b"\n")
    if current_runtime != baseline_module("runtime.cjs").replace(b"\r\n", b"\n"):
        raise ValueError("The runtime must remain unchanged between these recovery controls")
    if expected:
        for name in ("recovery.cjs", "test-recovery.cjs"):
            if sha(REPO / "scripts/variant/file-based-apps" / name) != input_record["moduleSha256"][name]:
                raise ValueError("Final recovery/test source changed after execution")
    elif (work / "modules/recovery.cjs").read_bytes() != baseline_module("recovery.cjs"):
        raise ValueError("Baseline must execute the exact previous recovery module")
    before, after = read(work / "interruption-proof.json"), read(work / "recovery-proof.json")
    if result["interruption"] != before or result["coldRecovery"] != after:
        raise ValueError("Process proof snapshot differs")
    processes = result["processes"]
    if ([item["exitCode"] for item in processes] != [73, 0]
            or processes[0]["pid"] != before["pid"] or processes[1]["pid"] != after["pid"]
            or before["pid"] == after["pid"] or after["interruptedPid"] != before["pid"]):
        raise ValueError("Expected two actual processes and observed exits 73 then 0")
    if (before["sourceIdentity"] != input_record["moduleSha256"] or after["sourceIdentity"] != before["sourceIdentity"]
            or before["boundary"] != "complete-staging-before-ready-rename"
            or not before["completeBeforePublication"] or not before["sourceMoveCompleted"]
            or before["publicationRenameExecuted"] or before["calls"]["removals"]):
        raise ValueError("Expected complete staging before final publication and before any deletion")
    entry, ready = Path(before["stagingEntry"]), Path(before["readyEntry"])
    receipt = before["receipt"]
    receipt_bytes = (json.dumps(receipt, separators=(",", ":")) + "\n").encode()
    if (entry.parent.name != "terminal-cleanup-staging-v1" or ready.parent.name != "terminal-cleanup-v1"
            or entry.name != ready.name or Path(before["stagedOutput"]) != entry / "output"
            or receipt != {"version": 1, "kind": "netcoredbg-terminal-output", "entryId": entry.name}
            or hashlib.sha256(receipt_bytes).hexdigest() != before["receiptSha256"]):
        raise ValueError("Complete staging receipt or fixed path differs")
    if (after["completeStageRecovered"] is not expected or after["residualExists"] is expected
            or after["stagingExists"] is expected or after["readyExists"] or not after["readyQueueEmpty"]):
        raise ValueError("Staging publication/recovery outcome differs")
    recovered = after["recovery"]
    if expected:
        if (not 1 <= recovered["scanned"] <= 32 or recovered["attempted"] != 1 or recovered["removed"] != 1
                or len(after["removals"]) != 1 or Path(after["removals"][0]["directory"]) != ready / "output"
                or entry.exists() or ready.exists()):
            raise ValueError("New activation must promote and remove only one eligible terminal output")
    else:
        if recovered != {"scanned": 0, "attempted": 0, "removed": 0} or after["removals"] or not entry.exists():
            raise ValueError("The previous recovery must reproduce the ignored complete-stage gap")
        for file in before["payload"]:
            if sha(Path(file["file"])) != file["sha256"]:
                raise ValueError("Baseline's uncollected staging payload changed")
    required = {"unmarked-output", "outside-extension-storage", "incomplete-record-without-output",
                "malformed-staging-output", "malformed-staging-record", "active-stub-session-output", "replacement-at-original-output"}
    if {guard["kind"] for guard in after["observations"]} != required:
        raise ValueError("Missing unrelated/incomplete/replacement preservation guard")
    for guard in after["observations"]:
        if not guard["unchanged"] or sha(Path(guard["file"])) != guard["sha256"]:
            raise ValueError("Preserved sentinel changed: " + guard["kind"])
    if after["calls"]["sdkSelections"] or after["calls"]["launches"] or after["calls"]["stops"]:
        raise ValueError("Cold recovery must not select an SDK or operate a debug session")
    traces = {phase: [json.loads(line) for line in (work / f"{phase}.trace.jsonl").read_text().splitlines()]
              for phase in ("interrupt", "recover")}
    if (not any(item["event"] == "abrupt-exit-before-publication-promise-settles" for item in traces["interrupt"])
            or traces["interrupt"][0]["pid"] != before["pid"] or traces["recover"][0]["pid"] != after["pid"]
            or any(traces[phase][0]["architecture"] != "arm64" for phase in ("interrupt", "recover"))):
        raise ValueError("Actual process-boundary trace is missing")
    return {"localArtifactDirectory": str(work), "record": result, "traces": traces, "rawEvidence": raw_files(work)}


def validate_tests(work):
    focused, full = read(work / "focused-final.json"), read(work / "full-final.json")
    test_hash = sha(REPO / "scripts/variant/file-based-apps/test-recovery.cjs")
    recovery_hash = sha(REPO / "scripts/variant/file-based-apps/recovery.cjs")
    if (focused["beforeExitCode"] != 1 or focused["afterExitCode"] != 0 or full["exitCode"] != 0
            or focused["testRecoverySha256"] != test_hash or focused["baselineTestRecoverySha256"] != test_hash
            or full["testRecoverySha256"] != test_hash or focused["recoverySha256"] != recovery_hash
            or full["recoverySha256"] != recovery_hash
            or sha(work / "baseline-final/test-recovery.cjs") != test_hash
            or (work / "baseline-final/recovery.cjs").read_bytes() != baseline_module("recovery.cjs")
            or sha(work / "baseline-final/recovery.cjs") != focused["baselineRecoverySha256"]):
        raise ValueError("Before/after must execute identical final tests and pinned recovery modules")
    expected = lambda total, passed, failed: {"tests": total, "pass": passed, "fail": failed, "cancelled": 0, "skipped": 0, "todo": 0}
    actual = {name: counts(work / name) for name in ("before-final.txt", "after-final.txt", "full-final.txt")}
    if (actual["before-final.txt"] != expected(8, 0, 8) or actual["after-final.txt"] != expected(8, 8, 0)
            or actual["full-final.txt"] != expected(171, 171, 0)):
        raise ValueError("Raw focused/full test totals differ from the final record")
    return {"localArtifactDirectory": str(work), "finalCounts": actual,
            "historicalRunRecords": {file.name: read(file) for file in sorted(work.glob("*.json"))},
            "rawEvidence": raw_files(work)}


def validate_installed_probe(work):
    expected, result, runner = (read(work / name) for name in ("expected.json", "result.json", "control-runner-result.json"))
    marker, process, ack = (read(work / name) for name in ("crash-ready.json", "extension-host-process.json", "crash-ack.json"))
    if (not result["success"] or not runner["success"] or result["expected"] != expected
            or expected["scenario"] != "installed-interrupted-publication"
            or result["firstHost"] != marker or marker["nonce"] != expected["interruption"]["nonce"]
            or ack["nonce"] != marker["nonce"] or ack["pid"] != marker["hostPid"]):
        raise ValueError("Installed publication proof, identity or exact-host acknowledgement differs")
    candidate = expected["candidate"]
    if sha(Path(candidate["path"])) != candidate["sha256"] or runner["candidateSha256"] != candidate["sha256"]:
        raise ValueError("Installed publication candidate differs")
    for name, value in candidate["ownedModules"].items():
        if (sha(REPO / "scripts/variant/file-based-apps" / name) != value
                or sha(Path(result["installedExtension"]["path"]) / ".netcoredbg" / name) != value
                or result["installedModules"][name] != value or marker["installedModules"][name] != value):
            raise ValueError("Installed publication executed a different product module")
    lifecycle = REPO / "scripts/variant/lifecycle"
    for name, value in expected["harness"].items():
        source = lifecycle / ("interrupted-publication/extension-test.cjs" if name == "extension-test.cjs" else name)
        if sha(source) != value:
            raise ValueError("Installed publication harness changed: " + name)
    if sha(work / "driver/extension-test.cjs") != expected["harness"]["extension-test.cjs"]:
        raise ValueError("Executed publication driver differs from source")
    launches = runner["launches"]
    if (len(launches) != 2 or [item["phase"] for item in launches] != ["interrupt", "recover"]
            or [item["editorExitCode"] for item in launches] != [73, 0] or not launches[0]["editorExitedNaturally"]
            or launches[0]["extensionHostPid"] != marker["hostPid"]
            or result["extensionHostPid"] == marker["hostPid"] or launches[0]["editorPid"] == launches[1]["editorPid"]):
        raise ValueError("Expected natural exit and two explicit app/host launches")
    lineage = process["lineage"]
    if (not process["verified"] or process["pid"] != marker["hostPid"]
            or lineage[0]["ProcessId"] != marker["hostPid"] or lineage[-1]["ProcessId"] != launches[0]["editorPid"]):
        raise ValueError("Native host ownership is missing")
    host_exit = f'Extension host with pid {marker["hostPid"]} exited with code: 73'
    if not any(host_exit in file.read_text(encoding="utf-8-sig") for file in (work / "profile/logs").glob("**/main.log")):
        raise ValueError("Actual editor log must confirm host exit 73")
    for index, item in enumerate(lineage):
        if Path(item["ExecutablePath"]) != Path(expected["editor"]["executable"]):
            raise ValueError("Unexpected executable in host lineage")
        if index + 1 < len(lineage) and item["ParentProcessId"] != lineage[index + 1]["ProcessId"]:
            raise ValueError("Broken host-to-editor lineage")
    if (marker["boundary"] != "complete-staging-before-ready-rename" or not marker["sourceMoved"]
            or not marker["readyAbsent"] or marker["publicationRenameInvoked"]
            or not marker["debuggeePidGone"] or not marker["portReusable"]):
        raise ValueError("Installed checkpoint must precede final publication, after debuggee termination")
    entry, ready = Path(marker["entry"]), Path(marker["readyEntry"])
    receipt = marker["receipt"]
    if (entry.parent.name != "terminal-cleanup-staging-v1" or ready.parent.name != "terminal-cleanup-v1"
            or entry.name != ready.name or Path(marker["output"]) != entry / "output"
            or receipt != {"version": 1, "kind": "netcoredbg-terminal-output", "entryId": entry.name}
            or hashlib.sha256((json.dumps(receipt, separators=(",", ":")) + "\n").encode()).hexdigest() != marker["receiptSha256"]):
        raise ValueError("Installed complete-stage receipt/path differs")
    if entry.exists() or ready.exists():
        raise ValueError("Fresh installed activation left the interrupted stage or ready entry")
    expected_payload = {"FileApp.dll", "FileApp.pdb", "interrupted-owned-sentinel"}
    if ({Path(item["path"]).name for item in marker["payload"]} != expected_payload
            or any(Path(item["path"]).parent != entry / "output" or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                   for item in marker["payload"])):
        raise ValueError("Complete pre-publication payload must retain all three exact hashes")
    replacement = read(work / "replacement.json")
    guards = marker["preservedStagingEntries"]
    if len(marker["sentinels"]) != 5 or len(guards) != 2 or len(set(guards)) != 2:
        raise ValueError("Installed proof must retain unmarked/external and both incomplete/invalid staging guards")
    record_only, unsupported = (Path(item) for item in guards)
    if (any(directory.parent != entry.parent for directory in (record_only, unsupported))
            or read(record_only / "record.json") != {"version": 1, "kind": "netcoredbg-terminal-output", "entryId": record_only.name}
            or (record_only / "output").exists() or read(unsupported / "record.json")["version"] != 99
            or not (unsupported / "output/invalid-stage-sentinel").is_file()):
        raise ValueError("Incomplete or unsupported staging preservation differs")
    for sentinel in marker["sentinels"] + [replacement]:
        if Path(sentinel["path"]).read_text() != sentinel["content"]:
            raise ValueError("Installed recovery changed an unrelated/replacement sentinel")
    retry = result["retry"]
    if (not retry["terminated"] or retry["response"]["pid"] != retry["pid"]
            or retry["response"]["nonce"] != retry["nonce"] or retry["response"]["value"] != 42
            or Path(retry["output"]).exists() or retry["output"] in (marker["output"], marker["originalOutput"])):
        raise ValueError("Installed retry must use fresh output and complete cleanup")
    observation = read(work / "post-exit-observation.json")
    if (not observation["stageEntryAbsent"] or not observation["readyEntryAbsent"] or not observation["retryOutputAbsent"]
            or {item["path"] for item in observation["sentinels"]} != {item["path"] for item in marker["sentinels"] + [replacement]}
            or any(not value["unchanged"] or sha(Path(value["path"])) != value["sha256"] for value in observation["sentinels"])):
        raise ValueError("Installed post-exit observation differs")
    files = [file for file in work.iterdir() if file.is_file() and file.suffix in (".json", ".jsonl", ".txt", ".cjs", ".ps1")]
    for name in ("driver", "logs", "profile/logs"):
        files.extend(file for file in (work / name).rglob("*") if file.is_file())
    return {"localArtifactDirectory": str(work), "record": result, "runner": runner, "nativeHostOwnership": process,
            "postExitObservation": observation,
            "rawEvidence": {file.relative_to(work).as_posix(): {"sha256": sha(file), "bytes": file.stat().st_size} for file in sorted(set(files))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--fixed", type=Path, required=True)
    parser.add_argument("--tests", type=Path)
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--installed-regression", type=Path)
    parser.add_argument("--installed-probe", type=Path)
    parser.add_argument("--prepared-only", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, default=DOCS / "evidence-summary.json")
    args = parser.parse_args()
    baseline, fixed = validate_control(args.baseline.resolve(), False), validate_control(args.fixed.resolve(), True)
    if baseline["record"]["input"]["moduleSha256"]["runtime.cjs"] != fixed["record"]["input"]["moduleSha256"]["runtime.cjs"]:
        raise ValueError("Both native controls must execute identical runtime bytes")
    summary = {"schema": 1, "date": "2026-11-06", "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
               "baselineCommit": BASELINE, "qualification": False,
               "scope": "Actual native Node complete-STAGING publication interruption and cold activation, controlled SDK and VS Code API",
               "sourceSha256": {name: sha(REPO / "scripts/variant/file-based-apps" / name) for name in ("runtime.cjs", "recovery.cjs", "test-recovery.cjs")},
               "evidenceToolsSha256": {name: sha(DOCS / name) for name in ("native-control.cjs", "run-native-control.py", "summarize.py")},
               "nativeControls": {"baseline": baseline, "fixed": fixed}}
    if args.tests:
        summary["automatedTests"] = validate_tests(args.tests.resolve())
    if args.installed_regression:
        work = args.installed_regression.resolve()
        shared = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"
        spec = importlib.util.spec_from_file_location("installed_regression", shared)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        control = module.summarize_run(work, True)
        for name, value in read(work / "expected.json")["candidate"]["ownedModules"].items():
            if sha(REPO / "scripts/variant/file-based-apps" / name) != value:
                raise ValueError("Installed regression differs from current source")
        summary["installedRegression"] = control
        summary["sharedInstalledSummarizerSha256"] = sha(shared)
    if args.installed_probe:
        summary["installedProbe"] = validate_installed_probe(args.installed_probe.resolve())
    if args.checks:
        work = args.checks.resolve(); record = read(work / "python-final.json")
        if (record["exitCode"] != 0 or record["sourceRecoverySha256"] != summary["sourceSha256"]["recovery.cjs"]
                or not re.search(r"Ran 39 tests in .+\n\s*\nOK", (work / "python-final.txt").read_text(encoding="utf-8-sig"))):
            raise ValueError("Final Python helper result must pass")
        summary["pythonHelpers"] = {"record": record, "testCount": 39, "rawEvidence": raw_files(work)}
    summary["unlaunchedPreparations"] = []
    for directory in args.prepared_only:
        work = directory.resolve()
        if any((work / name).exists() for name in ("attempt.json", "interruption-attempt.json", "launch.json", "result.json", "launcher-result.json", "control-runner-result.json")):
            raise ValueError("Attempted profile cannot be labelled preparation-only")
        expected = read(work / "expected.json")
        if sha(work / "local-lifecycle.vsix") != expected["candidate"]["sha256"]:
            raise ValueError("Prepared candidate differs from pinned bytes")
        superseded = work / "superseded.json"
        if not superseded.exists():
            superseded = work / "superseded-unlaunched.json"
        record = read(superseded)
        if record.get("installedEditorRunAttempted") is not False and record.get("executed") is not False:
            raise ValueError("Missing unlaunched preparation record")
        summary["unlaunchedPreparations"].append({"localArtifactDirectory": str(work), "record": record,
            "candidateSha256": expected["candidate"]["sha256"], "expectedSha256": sha(work / "expected.json"), "recordSha256": sha(superseded)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), "sha256": sha(args.output)}))


if __name__ == "__main__":
    main()
