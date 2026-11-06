"""Validate native interruption controls, unchanged recovery and retained tests."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[3]
DOCS = Path(__file__).parent
BASELINE = "5e98bf8fa6f78264f28220a8e2be13af84197818"


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def read(file):
    return json.loads(file.read_text(encoding="utf-8-sig"))


def raw_files(work):
    return {file.relative_to(work).as_posix(): {"sha256": sha(file), "bytes": file.stat().st_size}
            for file in sorted(work.rglob("*")) if file.is_file()}


def counts(file):
    return {key: int(value) for key, value in re.findall(
        r"(?m)^[ℹ#]\s+(tests|pass|fail|cancelled|skipped|todo)\s+(\d+)\s*$",
        file.read_text(encoding="utf-8-sig"))}


def validate_control(work, expected):
    result = read(work / "result.json")
    input_record = read(work / "input.json")
    if not result["success"] or result["input"] != input_record or result["desiredBehaviorObserved"] is not expected:
        raise ValueError("Native control result/input mismatch")
    for name, item in read(work / "hashes.json").items():
        file = work / name
        if sha(file) != item["sha256"] or file.stat().st_size != item["bytes"]:
            raise ValueError("Retained native control changed: " + name)
    for name, value in input_record["moduleSha256"].items():
        if sha(work / "modules" / name) != value:
            raise ValueError("Executed module identity mismatch")
    if (input_record["driverSha256"] != sha(work / "native-control.cjs")
            or input_record["driverSha256"] != sha(DOCS / "native-control.cjs")
            or input_record["runnerSha256"] != sha(DOCS / "run-native-control.py")
            or input_record["node"]["sha256"] != sha(Path(input_record["node"]["executable"]))):
        raise ValueError("Native driver/runner/executable differs from the pinned execution")
    before, after = read(work / "interruption-proof.json"), read(work / "recovery-proof.json")
    if result["interruption"] != before or result["coldRecovery"] != after:
        raise ValueError("Native process proof snapshot differs")
    processes = result["processes"]
    if ([item["exitCode"] for item in processes] != [73, 0]
            or processes[0]["pid"] != before["pid"] or processes[1]["pid"] != after["pid"]
            or before["pid"] == after["pid"] or after["interruptedPid"] != before["pid"]):
        raise ValueError("Expected abrupt first exit and successful independent cold process")
    if (before["publishedBeforeFirstDelete"] is not expected or not before["partialLeafRemoved"]
            or after["terminalJournalRecovered"] is not expected or after["residualExists"] is expected
            or after["recovery"] != ({"scanned": 1, "attempted": 1, "removed": 1} if expected else {"scanned": 0, "attempted": 0, "removed": 0})):
        raise ValueError("First-delete publication and cold recovery outcomes differ")
    if before["sourceIdentity"] != input_record["moduleSha256"] or after["sourceIdentity"] != before["sourceIdentity"]:
        raise ValueError("Cold processes used different product source")
    required = {"unmarked-output", "outside-extension-storage", "unpublished-staging-output", "active-stub-session-output"}
    if expected:
        required.add("replacement-at-original-output")
        if sha(REPO / "scripts/variant/file-based-apps/runtime.cjs") != input_record["moduleSha256"]["runtime.cjs"]:
            raise ValueError("Final runtime changed after native execution")
        if sha(REPO / "scripts/variant/file-based-apps/test-runtime.cjs") != input_record["moduleSha256"]["test-runtime.cjs"]:
            raise ValueError("Final tests changed after native execution")
        if len(before["ready"]) != 1 or before["ready"][0]["output"] != before["firstRecursiveDeleteTarget"]:
            raise ValueError("Published journal must identify the first recursive deletion target")
        marker = before["ready"][0]["record"]
        if marker["version"] != 1 or marker["kind"] != "netcoredbg-terminal-output":
            raise ValueError("Recovery format changed")
        if after["ready"] or Path(before["firstRecursiveDeleteTarget"]).exists():
            raise ValueError("Cold recovery did not remove the exact queued output")
    else:
        old = subprocess.check_output(["git", "show", f"{BASELINE}:scripts/variant/file-based-apps/runtime.cjs"], cwd=REPO)
        if (work / "modules/runtime.cjs").read_bytes() != old or before["ready"]:
            raise ValueError("Baseline must use the exact old runtime without a published journal")
    if {guard["kind"] for guard in after["observations"]} != required:
        raise ValueError("Missing unrelated/replacement guard")
    for guard in after["observations"]:
        if not guard["unchanged"] or sha(Path(guard["file"])) != guard["sha256"]:
            raise ValueError("A preserved sentinel changed: " + guard["kind"])
    if after["calls"]["sdkSelections"] or after["calls"]["launches"] or after["calls"]["stops"]:
        raise ValueError("Cold activation must recover without an SDK or debug-session action")
    traces = {phase: [json.loads(line) for line in (work / f"{phase}.trace.jsonl").read_text().splitlines()]
              for phase in ("interrupt", "recover")}
    if (not any(item["event"] == "abrupt-exit-before-removal-promise-settles" for item in traces["interrupt"])
            or traces["interrupt"][0]["pid"] != before["pid"] or traces["recover"][0]["pid"] != after["pid"]):
        raise ValueError("Actual process boundary trace is missing")
    return {"localArtifactDirectory": str(work), "record": result, "traces": traces, "rawEvidence": raw_files(work)}


def validate_tests(work):
    before, after, full = (read(work / name) for name in ("before-five.json", "after-five.json", "full-final-156.json"))
    expected_tests = sha(REPO / "scripts/variant/file-based-apps/test-runtime.cjs")
    if (before["exitCode"] != 1 or after["exitCode"] != 0 or full["exitCode"] != 0
            or any(item["testsSha256"] != expected_tests for item in (before, after, full))
            or sha(work / "baseline-five/test-runtime.cjs") != expected_tests):
        raise ValueError("Focused before/after must execute identical final test bytes")
    runtime = sha(REPO / "scripts/variant/file-based-apps/runtime.cjs")
    if after["runtimeSha256"] != runtime or full["runtimeSha256"] != runtime:
        raise ValueError("Final automated tests used a different runtime")
    expected = lambda total, passed, failed: {"tests": total, "pass": passed, "fail": failed, "cancelled": 0, "skipped": 0, "todo": 0}
    actual = {name: counts(work / name) for name in ("before-five.txt", "after-five.txt", "full-final-156.txt")}
    if (actual["before-five.txt"] != expected(5, 0, 5) or actual["after-five.txt"] != expected(5, 5, 0)
            or actual["full-final-156.txt"] != expected(156, 156, 0)):
        raise ValueError("Raw before/after/full test totals differ")
    commands = read(work / "commands.json")
    for command in commands["commands"]:
        if (sha(Path(command["stdoutAndStderr"])) != command["outputSha256"]
                or read(Path(command["metadata"])) != command["sourceIdentity"]):
            raise ValueError("Retained test command/output binding differs")
    return {"localArtifactDirectory": str(work), "finalCounts": actual,
            "historicalRunRecords": {file.name: read(file) for file in sorted(work.glob("*.json"))},
            "rawEvidence": raw_files(work)}


def validate_installed_probe(work):
    expected, result, runner = (read(work / name) for name in ("expected.json", "result.json", "control-runner-result.json"))
    marker, process, ack = (read(work / name) for name in ("crash-ready.json", "extension-host-process.json", "crash-ack.json"))
    if (not result["success"] or not runner["success"] or result["expected"] != expected
            or expected["scenario"] != "installed-interrupted-cleanup"
            or result["firstHost"] != marker or marker["nonce"] != expected["interruption"]["nonce"]
            or ack["nonce"] != marker["nonce"] or ack["pid"] != marker["hostPid"]):
        raise ValueError("Installed interruption result, identity or exact-host acknowledgement differs")
    candidate = expected["candidate"]
    if sha(Path(candidate["path"])) != candidate["sha256"] or runner["candidateSha256"] != candidate["sha256"]:
        raise ValueError("Installed interruption candidate differs from pinned VSIX")
    for name, value in candidate["ownedModules"].items():
        if (sha(REPO / "scripts/variant/file-based-apps" / name) != value
                or sha(Path(result["installedExtension"]["path"]) / ".netcoredbg" / name) != value
                or result["installedModules"][name] != value or marker["installedModules"][name] != value):
            raise ValueError("Installed interruption executed different product module: " + name)
    lifecycle = REPO / "scripts/variant/lifecycle"
    for name, value in expected["harness"].items():
        source = lifecycle / ("interrupted-cleanup/extension-test.cjs" if name == "extension-test.cjs" else name)
        if sha(source) != value:
            raise ValueError("Installed interruption harness changed after execution: " + name)
    if sha(work / "driver/extension-test.cjs") != expected["harness"]["extension-test.cjs"]:
        raise ValueError("Executed interruption driver differs from source")
    launches = runner["launches"]
    if (len(launches) != 2 or [item["phase"] for item in launches] != ["interrupt", "recover"]
            or [item["editorExitCode"] for item in launches] != [73, 0]
            or not launches[0]["editorExitedNaturally"] or launches[0].get("verifiedEditorKilledAfterHostExit")
            or launches[0]["extensionHostPid"] != marker["hostPid"]
            or result["extensionHostPid"] == marker["hostPid"] or launches[0]["editorPid"] == launches[1]["editorPid"]):
        raise ValueError("Expected natural first exit and two explicit app launches/extension hosts")
    lineage = process["lineage"]
    if (not process["verified"] or process["pid"] != marker["hostPid"]
            or lineage[0]["ProcessId"] != marker["hostPid"] or lineage[-1]["ProcessId"] != launches[0]["editorPid"]):
        raise ValueError("Native extension-host ownership evidence is missing")
    host_exit = f'Extension host with pid {marker["hostPid"]} exited with code: 73'
    if not any(host_exit in file.read_text(encoding="utf-8-sig") for file in (work / "profile/logs").glob("**/main.log")):
        raise ValueError("Actual editor log must confirm the intentional extension-host exit code")
    for index, item in enumerate(lineage):
        if Path(item["ExecutablePath"]) != Path(expected["editor"]["executable"]):
            raise ValueError("Unexpected executable in owned editor/host lineage")
        if index + 1 < len(lineage) and item["ParentProcessId"] != lineage[index + 1]["ProcessId"]:
            raise ValueError("Broken native host-to-editor lineage")
    receipt = marker["receipt"]
    receipt_bytes = (json.dumps(receipt, separators=(",", ":")) + "\n").encode()
    if (receipt["version"] != 1 or receipt["kind"] != "netcoredbg-terminal-output"
            or receipt["entryId"] != Path(marker["entry"]).name
            or hashlib.sha256(receipt_bytes).hexdigest() != marker["receiptSha256"]
            or Path(marker["output"]) != Path(marker["entry"]) / "output"
            or not marker["partialFileAbsent"] or not marker["debuggeePidGone"] or not marker["portReusable"]):
        raise ValueError("Published first-removal receipt/partial deletion or prior debuggee exit is unproven")
    if Path(marker["entry"]).exists():
        raise ValueError("Fresh installed activation did not recover the queued terminal entry")
    replacement = read(work / "replacement.json")
    for sentinel in marker["sentinels"] + [replacement]:
        if Path(sentinel["path"]).read_text() != sentinel["content"]:
            raise ValueError("Installed recovery changed an unrelated/replacement sentinel")
    retry = result["retry"]
    if (not retry["terminated"] or retry["response"]["pid"] != retry["pid"]
            or retry["response"]["nonce"] != retry["nonce"] or retry["response"]["value"] != 42
            or Path(retry["output"]).exists() or retry["output"] in (marker["output"], marker["originalOutput"])):
        raise ValueError("Actual installed retry must use fresh output and complete exact cleanup")
    observation = read(work / "post-exit-observation.json")
    if (not observation["terminalEntryAbsent"] or not observation["retryOutputAbsent"]
            or observation["remainingScopedProcesses"]
            or any(not value["unchanged"] or sha(Path(value["path"])) != value["sha256"] for value in observation["sentinels"])):
        raise ValueError("Final post-exit observation differs from preserved filesystem guards")
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
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--installed-regression", type=Path)
    parser.add_argument("--installed-probe", type=Path)
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--prepared-only", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, default=DOCS / "evidence-summary.json")
    args = parser.parse_args()
    baseline, fixed = validate_control(args.baseline.resolve(), False), validate_control(args.fixed.resolve(), True)
    if baseline["record"]["input"]["moduleSha256"]["recovery.cjs"] != fixed["record"]["input"]["moduleSha256"]["recovery.cjs"]:
        raise ValueError("Before/after must use identical recovery bytes")
    summary = {"schema": 1, "date": "2026-11-06", "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
               "baselineCommit": BASELINE, "qualification": False,
               "scope": "Actual native Node interruption/cold activation, controlled SDK and VS Code API; not host crash qualification",
               "sourceSha256": {name: sha(REPO / "scripts/variant/file-based-apps" / name) for name in ("runtime.cjs", "test-runtime.cjs", "recovery.cjs")},
               "evidenceToolsSha256": {name: sha(DOCS / name) for name in ("native-control.cjs", "run-native-control.py", "summarize.py")},
               "nativeControls": {"baseline": baseline, "fixed": fixed}, "automatedTests": validate_tests(args.tests.resolve())}
    if args.installed_regression:
        work = args.installed_regression.resolve()
        shared = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"
        spec = importlib.util.spec_from_file_location("installed_regression", shared)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        control = module.summarize_run(work, True)
        for name, value in read(work / "expected.json")["candidate"]["ownedModules"].items():
            if sha(REPO / "scripts/variant/file-based-apps" / name) != value:
                raise ValueError("Installed candidate differs from final runtime: " + name)
        summary["installedRegression"] = control
        summary["sharedInstalledSummarizerSha256"] = sha(shared)
    if args.installed_probe:
        work = args.installed_probe.resolve()
        summary["installedProbe"] = validate_installed_probe(work)
    if args.checks:
        work = args.checks.resolve()
        record = read(work / "python-final.json")
        if (record["exitCode"] != 0 or record["sourceRuntimeSha256"] != summary["sourceSha256"]["runtime.cjs"]
                or not re.search(r"Ran 39 tests in .+\n\s*\nOK", (work / "python-final.txt").read_text(encoding="utf-8-sig"))):
            raise ValueError("Final Python helper result must pass with the current runtime")
        summary["pythonHelpers"] = {"record": record, "testCount": 39, "rawEvidence": raw_files(work)}
    summary["unlaunchedPreparations"] = []
    for directory in args.prepared_only:
        work = directory.resolve()
        if any((work / name).exists() for name in ("attempt.json", "interruption-attempt.json", "launch.json", "result.json", "launcher-result.json", "control-runner-result.json")):
            raise ValueError("An attempted profile cannot be relabelled as preparation-only")
        expected = read(work / "expected.json")
        if sha(work / "local-lifecycle.vsix") != expected["candidate"]["sha256"]:
            raise ValueError("Prepared candidate differs from its pinned bytes")
        superseded = work / "superseded.json"
        if not superseded.exists():
            superseded = work / "superseded-unlaunched.json"
        record = read(superseded)
        if (record.get("installedEditorRunAttempted") is not False and record.get("executed") is not False):
            raise ValueError("Missing explicit unlaunched preparation record")
        summary["unlaunchedPreparations"].append({"localArtifactDirectory": str(work), "record": record,
            "candidateSha256": expected["candidate"]["sha256"], "expectedSha256": sha(work / "expected.json"),
            "recordSha256": sha(superseded)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), "sha256": sha(args.output)}))


if __name__ == "__main__":
    main()
