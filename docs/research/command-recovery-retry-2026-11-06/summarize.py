"""Validate same-reader recovery retry controls and their retained source identities."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[3]
DOCS = Path(__file__).parent
BASELINE = "bc94c900acadd09fd29a949497818b4c36b43edb"
MODULES = REPO / "scripts/variant/file-based-apps"


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def read(file):
    return json.loads(file.read_text(encoding="utf-8-sig"))


def raw_files(work):
    return {file.relative_to(work).as_posix(): {"sha256": sha(file), "bytes": file.stat().st_size}
            for file in sorted(work.rglob("*")) if file.is_file()}


def git_module(name):
    return subprocess.check_output(["git", "show", f"{BASELINE}:scripts/variant/file-based-apps/{name}"], cwd=REPO)


def counts(file):
    return {key: int(value) for key, value in re.findall(
        r"(?m)^[ℹ#]\s+(tests|pass|fail|cancelled|skipped|todo)\s+(\d+)\s*$", file.read_text(encoding="utf-8-sig"))}


def validate_control(work, expected):
    result, inputs = read(work / "result.json"), read(work / "input.json")
    if not result["success"] or result["input"] != inputs or result["desiredBehaviorObserved"] is not expected or inputs["expectedRecovery"] is not expected:
        raise ValueError("Native result/input mismatch")
    if inputs["controlledTiming"] != {"sdkWaitsForOldDeleteEntry": expected, "postCommandObservationMs": 0 if expected else 100}:
        raise ValueError("Retained control timing differs")
    for name, item in read(work / "hashes.json").items():
        if sha(work / name) != item["sha256"] or (work / name).stat().st_size != item["bytes"]:
            raise ValueError("Retained native evidence changed: " + name)
    for role in ("writer", "reader"):
        for name, value in inputs[role + "Modules"].items():
            data = (work / (role + "-modules") / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != value:
                raise ValueError("Executed module changed")
            required = (MODULES / name).read_bytes() if expected and role == "reader" and name == "runtime.cjs" else git_module(name)
            if data != required:
                raise ValueError("Native control must change only the reader runtime")
    if (sha(DOCS / "native-control.cjs") != inputs["driverSha256"] or sha(work / "native-control.cjs") != inputs["driverSha256"]
            or sha(DOCS / "run-native-control.py") != inputs["runnerSha256"]
            or sha(Path(inputs["node"]["executable"])) != inputs["node"]["sha256"]
            or sha(work / "test-runtime.cjs") != inputs["testRuntimeSha256"] or sha(MODULES / "test-runtime.cjs") != inputs["testRuntimeSha256"]):
        raise ValueError("Native executable, runner, driver or final test source differs")
    publication, startup, command, recovery = (read(work / name) for name in ("publication-proof.json", "startup-proof.json", "command-proof.json", "recovery-proof.json"))
    if result["publication"] != publication or result["startup"] != startup or result["command"] != command or result["recovery"] != recovery:
        raise ValueError("Native proof snapshot differs")
    processes = result["processes"]
    if (len(processes) != 2 or [item["phase"] for item in processes] != ["write", "read"] or [item["exitCode"] for item in processes] != [73, 0]
            or processes[0]["pid"] != publication["pid"] or processes[1]["pid"] != recovery["pid"]
            or publication["pid"] == recovery["pid"] or recovery["writerPid"] != publication["pid"]
            or startup["pid"] != command["pid"] or startup["pid"] != recovery["pid"]):
        raise ValueError("Expected writer exit 73 and one unchanged reader PID for startup and valid command")
    for process in processes:
        if process["command"] != [inputs["node"]["executable"], "--unhandled-rejections=strict", str(work / "native-control.cjs"), process["phase"], str(work)]:
            raise ValueError("Executed process arguments differ")
    entry, output = Path(publication["readyEntry"]), Path(publication["output"])
    receipt = publication["receipt"]
    if (publication["boundary"] != "published-ready-before-first-delete" or not publication["published"] or publication["recursiveDeleteExecuted"]
            or entry.parent.name != "terminal-cleanup-v1" or output != entry / "output"
            or Path(publication["stagingEntry"]).name != entry.name
            or receipt != {"version": 1, "kind": "netcoredbg-terminal-output", "entryId": entry.name}
            or hashlib.sha256((json.dumps(receipt, separators=(",", ":")) + "\n").encode()).hexdigest() != publication["receiptSha256"]):
        raise ValueError("Expected an intact published terminal receipt before any deletion")
    if (startup["recovery"] != {"scanned": 1, "attempted": 1, "removed": 0} or not startup["oldReceiptPresent"] or not startup["oldPayloadPresent"]
            or startup["oldDeletionAttempts"] != 1 or any(startup[name] for name in ("sdkSelections", "builds", "launches", "stops"))):
        raise ValueError("Reader activation must settle a single busy attempt without SDK/editor work")
    attempts = command["oldDeletionAttempts"]
    if (not command["commandResult"] or not command["commandLaunched"] or len(command["builds"]) != 1 or len(command["launches"]) != 1
            or len(attempts) != (2 if expected else 1) or attempts[0]["failed"] != "EBUSY"
            or command["freshOutput"] in (publication["original"], publication["output"])):
        raise ValueError("The same reader must start a fresh controlled session after startup EBUSY")
    if expected:
        if (attempts[1]["locked"] or attempts[1]["commandLaunched"] or not attempts[1]["commandStarted"]
                or not attempts[1]["releasedAfterCommandLaunch"] or not attempts[1]["removed"] or not command["oldEntryAbsent"]
                or command["oldReceiptPresent"] or command["oldPayloadPresent"] or entry.exists()):
            raise ValueError("A command must progress while its single background recovery waits for launch")
    else:
        if not command["oldReceiptPresent"] or not command["oldPayloadPresent"] or not entry.is_dir():
            raise ValueError("The baseline must retain the previous owner's receipt after the valid command")
        if sha(entry / "record.json") != publication["receiptSha256"]:
            raise ValueError("Baseline receipt changed")
        for payload in publication["payload"]:
            if sha(Path(payload["file"])) != payload["sha256"]:
                raise ValueError("Baseline retained payload changed")
    required = {"unmarked-output", "outside-extension-storage", "replacement-at-original-output", "incomplete-record-without-output"}
    if {item["kind"] for item in recovery["observations"]} != required:
        raise ValueError("Missing preservation guard")
    for guard in recovery["observations"]:
        if not guard["unchanged"] or sha(Path(guard["file"])) != guard["sha256"]:
            raise ValueError("Native sentinel changed")
    if recovery["calls"]["errors"]:
        raise ValueError("Recovery must not add a foreground launch error")
    if (recovery["desiredBehaviorObserved"] is not expected or recovery["oldEntryAbsent"] is not expected
            or recovery["oldPayloadPresent"] is expected or not recovery["ownOutputAbsent"] or not recovery["outputDisposed"]
            or Path(command["freshOutput"]).exists()):
        raise ValueError("Final native recovery/drain outcome differs")
    record_guard = next(item for item in recovery["observations"] if item["kind"] == "incomplete-record-without-output")
    incomplete = Path(record_guard["file"]).parent
    if (recovery["readyNames"] != ([] if expected else [entry.name]) or recovery["stagingNames"] != [incomplete.name]
            or (incomplete / "output").exists() or read(incomplete / "record.json") != {"version": 1, "kind": "netcoredbg-terminal-output", "entryId": incomplete.name}):
        raise ValueError("Only the deliberate record-only stage and baseline ready entry may remain")
    pass_counts = [tuple(map(int, match)) for line in recovery["calls"]["logs"] for match in re.findall(
        r"^Terminal output recovery: scanned=(\d+), attempted=(\d+), removed=(\d+)$", line)]
    if expected and pass_counts != [(1, 1, 0), (1, 1, 1)]:
        raise ValueError("The fixed reader must record one failed startup and one successful bounded command pass")
    traces = {phase: [json.loads(line) for line in (work / f"{phase}.trace.jsonl").read_text().splitlines()] for phase in ("write", "read")}
    for phase in ("write", "read"):
        if traces[phase][0]["architecture"] != "arm64" or any(item["pid"] != processes[0 if phase == "write" else 1]["pid"] for item in traces[phase]):
            raise ValueError("Expected native ARM64 process traces")
    events = [item["event"] for item in traces["read"]]
    if not events.index("startup-recovery-settled-busy") < events.index("same-reader-valid-command") < events.index("valid-command-stub-session-start"):
        raise ValueError("Expected settled startup followed by valid command in the same reader")
    if expected and not events.index("command-recovery-delete-waiting-for-launch") < events.index("valid-command-stub-session-start") < events.index("recursive-delete-complete"):
        raise ValueError("Background deletion must remain pending until foreground command starts its session")
    return {"localArtifactDirectory": str(work), "record": result, "traces": traces, "rawEvidence": raw_files(work)}


def validate_tests(work):
    names = ("focused-before-final", "focused-after-final", "full-after")
    records = {name: read(work / (name + ".json")) for name in names}
    source = {name: sha(MODULES / name) for name in ("runtime.cjs", "test-runtime.cjs")}
    for name in names:
        record = records[name]
        if record["testSha256"] != source["test-runtime.cjs"] or record["outputSha256"] != sha(work / (name + ".txt")):
            raise ValueError("Final runtime test or raw output differs")
        if name != "focused-before-final" and record["runtimeSha256"] != source["runtime.cjs"]:
            raise ValueError("Final runtime differs from tested source")
        if "--unhandled-rejections=strict" not in record["command"]:
            raise ValueError("Expected strict unhandled rejection checks")
    actual = {name: counts(work / (name + ".txt")) for name in names}
    desired = lambda total, passed, failed: {"tests": total, "pass": passed, "fail": failed, "cancelled": 0, "skipped": 0, "todo": 0}
    if (actual["focused-before-final"] != desired(11, 2, 9) or actual["focused-after-final"] != desired(11, 11, 0)
            or actual["full-after"] != desired(182, 182, 0)
            or [records[name]["exitCode"] for name in names] != [1, 0, 0]):
        raise ValueError("Final focused/full results differ")
    before = work / "before-source"
    if ((before / "runtime.cjs").read_bytes().replace(b"\r\n", b"\n") != git_module("runtime.cjs").replace(b"\r\n", b"\n")
            or sha(before / "runtime.cjs") != records["focused-before-final"]["runtimeSha256"]
            or sha(before / "test-runtime.cjs") != source["test-runtime.cjs"]):
        raise ValueError("Focused baseline must use identical final tests and old runtime source")
    history = read(work / "implementation-summary.json")
    for name, value in history["sources"].items():
        if sha(REPO / name) != value:
            raise ValueError("Implementation summary source differs")
    return {"finalCounts": actual, "records": {file.name: read(file) for file in work.glob("*.json")},
            "historicalPreparations": history["preparations"], "rawEvidence": raw_files(work)}


def validate_installed_probe(work):
    expected, result, runner = (read(work / name) for name in ("expected.json", "result.json", "control-runner-result.json"))
    marker, ack, ownership, observation = (read(work / name) for name in ("host-ready.json", "host-ack.json", "extension-host-process.json", "post-exit-observation.json"))
    if (not result["success"] or not runner["success"] or result["expected"] != expected
            or expected["scenario"] != "installed-command-recovery-retry" or runner["appLaunches"] != 1
            or runner["editorExitCode"] != 0 or not expected["candidate"]["localOnly"] or expected["candidate"]["published"]
            or expected["candidate"]["target"] != "win32-arm64"):
        raise ValueError("Expected one successful normally installed native candidate control")
    host, editor, nonce = result["extensionHostPid"], result["editorPid"], expected["commandRecovery"]["nonce"]
    if (host != runner["extensionHostPid"] or host != marker["extensionHostPid"] or host != ack["extensionHostPid"]
            or host != result["final"]["sameExtensionHostPid"] or editor != runner["editorPid"] or editor != ack["editorPid"]
            or marker["nonce"] != nonce or ack["nonce"] != nonce or result["final"]["editorPid"] != editor):
        raise ValueError("App and actual extension host must remain the same throughout")
    lineage = ownership["lineage"]
    if not ownership["verified"] or lineage[0]["ProcessId"] != host or lineage[-1]["ProcessId"] != editor:
        raise ValueError("Missing exact host-to-editor native lineage")
    for index, item in enumerate(lineage):
        if Path(item["ExecutablePath"]) != Path(expected["editor"]["executable"]) or not item["CreationDate"]:
            raise ValueError("Native lineage executable/creation identity differs")
        if index + 1 < len(lineage) and item["ParentProcessId"] != lineage[index + 1]["ProcessId"]:
            raise ValueError("Native lineage parent differs")
    for item in (expected["editor"], expected["sdk"]):
        if sha(Path(item["executable"])) != item["sha256"]:
            raise ValueError("Native SDK/editor executable changed")
    for item in (expected["candidate"], expected["dependency"]):
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("Installed VSIX identity differs")
    candidate = expected["candidate"]
    if runner["candidateSha256"] != candidate["sha256"] or result["installedExtension"]["build"]["lifecycleBuildId"] != candidate["buildId"]:
        raise ValueError("Installed candidate/build ID differs")
    installed = Path(result["installedExtension"]["path"])
    if not installed.is_relative_to(work / "extensions") or not Path(result["installedExtension"]["dependencyPath"]).is_relative_to(work / "extensions"):
        raise ValueError("Target and dependency must be normally installed in the isolated profile")
    with zipfile.ZipFile(candidate["path"]) as package:
        metadata = json.loads(package.read("extension/package.json"))
        if metadata["version"] != candidate["version"] or metadata["netcoredbgBuild"]["lifecycleBuildId"] != candidate["buildId"]:
            raise ValueError("Candidate archive metadata differs")
        for name, value in candidate["ownedModules"].items():
            if (sha(MODULES / name) != value or sha(installed / ".netcoredbg" / name) != value or result["installedModules"][name] != value
                    or hashlib.sha256(package.read("extension/.netcoredbg/" + name)).hexdigest() != value):
                raise ValueError("Current, archived and loaded product module identities differ")
    lifecycle = REPO / "scripts/variant/lifecycle"
    for name, value in expected["harness"].items():
        source = lifecycle / ("command-recovery/extension-test.cjs" if name == "extension-test.cjs" else name)
        if sha(source) != value:
            raise ValueError("Installed probe harness changed: " + name)
    for name in ("extension-test.cjs", "driver.cjs"):
        if sha(work / "driver" / name) != expected["harness"][name]:
            raise ValueError("Executed installed driver differs")
    installed_metadata = read(installed / "package.json")
    if (not installed_metadata.get("__metadata") or result["installedExtension"]["version"] != candidate["version"]
            or result["installedExtension"]["dependencyVersion"] != expected["dependency"]["version"]
            or result["scope"]["actualOldHost"] or not result["scope"]["syntheticForeignControllerReceipt"]
            or result["scope"]["hostReload"] or result["scope"]["appLaunches"] != 1):
        raise ValueError("Installed metadata and evidence scope differ")
    fixture = result["fixture"]
    if fixture != read(work / "fixture.json") or fixture["actualOldHost"] or fixture["targetRuntimeOwnsOriginal"]:
        raise ValueError("This installed control uses a synthetic separate-controller terminal fixture")
    entry, output = Path(fixture["entry"]), Path(fixture["output"])
    receipt = {"version": 1, "kind": "netcoredbg-terminal-output", "entryId": fixture["entryId"]}
    if (fixture["receipt"] != receipt or entry.name != fixture["entryId"] or entry.parent.name != "terminal-cleanup-v1"
            or output != entry / "output" or entry.exists()
            or hashlib.sha256((json.dumps(receipt, separators=(",", ":")) + "\n").encode()).hexdigest() != fixture["receiptSha256"]
            or hashlib.sha256(fixture["payload"]["content"].encode()).hexdigest() != fixture["payload"]["sha256"]):
        raise ValueError("Installed terminal receipt/payload publication or cleanup differs")
    faults = result["faultCalls"]
    if faults != read(work / "fault-calls.json") or len(faults) != 2:
        raise ValueError("Expected exactly one busy pass and one later successful pass")
    options = {"recursive": True, "force": True, "maxRetries": 3, "retryDelay": 50}
    for index, item in enumerate(faults):
        if item["attempt"] != index + 1 or Path(item["directory"]) != output or item["options"] != options or item["unlocked"] is not bool(index):
            raise ValueError("Fault must apply only to the exact known-terminal output")
    if faults[0]["injectedCode"] != "EBUSY" or not faults[0]["rejectedAtUtc"] < faults[1]["invokedAtUtc"] or not faults[1]["removedAtUtc"]:
        raise ValueError("Installed EBUSY must settle before the later successful retry")
    failed = read(work / "failed-pass.json")
    if not failed["receiptRetained"] or not failed["payloadRetained"] or failed["rmAttempts"] != 1:
        raise ValueError("Busy pass must retain its receipt and complete payload")
    initial = result["initialRecoveryCompletions"]
    completions = initial + ["Terminal output recovery: scanned=1, attempted=1, removed=0", "Terminal output recovery: scanned=1, attempted=1, removed=1"]
    if (not initial or any(not line.endswith("attempted=0, removed=0") for line in initial)
            or failed["completions"] != completions[:-1] or result["outputLog"]["recoveryCompletions"] != completions):
        raise ValueError("Commands must produce two separate bounded passes without a queued rerun")
    launches = result["launches"]
    if [item["label"] for item in launches] != ["B-live", "A-gated", "A-retry"]:
        raise ValueError("Expected independent B plus gated and corrected A sessions")
    for index, launch in enumerate(launches):
        callers = 1 if index == 0 else 3
        revision = "command-retry" if index == 2 else "initial"
        if (launch["commandInvocations"] != callers or launch["commandResults"] != [True] * callers or not launch["terminated"]
                or len(launch["capturedSessions"]) != 1 or launch["capturedSessions"][0]["sessionId"] != launch["sessionId"]
                or launch["response"] != {"pid": launch["pid"], "nonce": launch["nonce"], "revision": revision, "value": 42}
                or Path(launch["output"]).exists() or Path(launch["program"]).parent != Path(launch["output"])):
            raise ValueError("Actual A/B HTTP/session identity or resource cleanup differs")
    if not launches[2]["dirtyBeforeCommand"] or len({item["output"] for item in launches}) != 3 or len({item["pid"] for item in launches}) != 3:
        raise ValueError("Corrected A must save dirty text and use a fresh output/debuggee")
    traces = [json.loads(line) for line in (work / "trace.jsonl").read_text().splitlines()]
    gated_ready = next(item for item in traces if item["event"] == "real-launch-ready" and item["value"]["label"] == "A-gated")
    if not faults[0]["invokedAtUtc"] <= gated_ready["atUtc"] < faults[0]["rejectedAtUtc"]:
        raise ValueError("Actual A must reach HTTP readiness while background deletion is still blocked")
    preserved_traces = [item for item in traces if item["event"] == "unrelated-preserved"]
    if len(preserved_traces) < 4:
        raise ValueError("Missing repeated independent B preservation observations")
    for item in preserved_traces:
        if item["event"] == "unrelated-preserved":
            if item["value"]["pid"] != launches[0]["pid"] or item["value"]["response"] != launches[0]["response"]:
                raise ValueError("Independent B changed during the control")
    record_only = Path(fixture["recordOnly"])
    if (read(record_only / "record.json") != {"version": 1, "kind": "netcoredbg-terminal-output", "entryId": fixture["recordOnlyId"]}
            or (record_only / "output").exists() or list((Path(fixture["base"]) / "terminal-cleanup-v1").iterdir())
            or [item.name for item in (Path(fixture["base"]) / "terminal-cleanup-staging-v1").iterdir()] != [fixture["recordOnlyId"]]):
        raise ValueError("Installed queues must preserve only the deliberate incomplete stage")
    if len(fixture["sentinels"]) != 4:
        raise ValueError("Expected unmarked/external/replacement and incomplete receipt guards")
    for sentinel in fixture["sentinels"]:
        if Path(sentinel["path"]).read_text() != sentinel["content"]:
            raise ValueError("Installed preservation guard changed")
    if (observation["appLaunches"] != 1 or observation["editorPid"] != editor or observation["extensionHostPid"] != host
            or observation["editorExitCode"] != 0 or not observation["hostGone"] or not observation["readyEmpty"] or not observation["recordOnlyStagePreserved"]
            or len(observation["resources"]) != 3 or not result["final"]["allExactDebuggeePidsGone"] or not result["final"]["allOutputsGone"]):
        raise ValueError("Installed post-exit app/host/resources proof differs")
    for resource, launch in zip(observation["resources"], launches):
        if (resource["pid"] != launch["pid"] or resource["port"] != launch["port"] or resource["output"] != launch["output"]
                or not resource["pidGone"] or not resource["portReusable"] or not resource["outputAbsent"]):
            raise ValueError("External exact PID/port/output observation differs")
    if {item["path"] for item in observation["sentinels"]} != {item["path"] for item in fixture["sentinels"]}:
        raise ValueError("External sentinel observations differ")
    for item in observation["sentinels"]:
        if not item["unchanged"] or sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("External sentinel hash differs")
    log = Path(result["outputLog"]["path"]); data = log.read_bytes()
    if (hashlib.sha256(data[:result["outputLog"]["bytes"]]).hexdigest() != result["outputLog"]["sha256"]
            or sha(log) != observation["outputLog"]["sha256"] or len(data) != observation["outputLog"]["bytes"]
            or [line for line in data.decode("utf-8-sig").splitlines() if line.startswith("Terminal output recovery:")] != completions
            or "Owned command-recovery fixture EBUSY" not in data.decode("utf-8-sig")):
        raise ValueError("Retained output log prefix/pass counts/EBUSY evidence differs")
    actual_builds = []
    for line in data.decode("utf-8-sig").splitlines():
        if not line.startswith("dotnet "):
            continue
        payload = line[7:]
        args = [json.loads(match) for match in re.findall(r'"(?:\\.|[^"\\])*"', payload)]
        if " ".join(json.dumps(arg, ensure_ascii=False, separators=(",", ":")) for arg in args) != payload:
            raise ValueError("Raw SDK command cannot be reconstructed")
        if args and args[0] == "build":
            actual_builds.append({"args": args, "output": args[args.index("--output") + 1]})
    if sorted(actual_builds, key=lambda item: item["output"]) != sorted(result["outputLog"]["buildCommands"], key=lambda item: item["output"]):
        raise ValueError("Raw build command log differs from the three recorded real builds")
    if len(actual_builds) != 3 or {item["output"] for item in actual_builds} != {item["output"] for item in launches}:
        raise ValueError("Each actual session must bind to exactly one fresh SDK build")
    files = [file for file in work.iterdir() if file.is_file() and file.suffix in (".json", ".jsonl", ".txt", ".cjs", ".ps1")]
    for name in ("driver", "logs", "profile/logs"):
        files.extend(file for file in (work / name).rglob("*") if file.is_file())
    return {"localArtifactDirectory": str(work), "record": result, "runner": runner, "nativeHostOwnership": ownership,
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
    parser.add_argument("--output", type=Path, default=DOCS / "evidence-summary.json")
    args = parser.parse_args()
    baseline, fixed = validate_control(args.baseline.resolve(), False), validate_control(args.fixed.resolve(), True)
    if baseline["record"]["input"]["writerModules"] != fixed["record"]["input"]["writerModules"] or baseline["record"]["input"]["readerModules"]["recovery.cjs"] != fixed["record"]["input"]["readerModules"]["recovery.cjs"]:
        raise ValueError("Both controls must keep the writer and recovery modules identical")
    if baseline["record"]["input"]["driverSha256"] != fixed["record"]["input"]["driverSha256"]:
        raise ValueError("Both controls must execute identical drivers")
    if (MODULES / "recovery.cjs").read_bytes().replace(b"\r\n", b"\n") != git_module("recovery.cjs").replace(b"\r\n", b"\n"):
        raise ValueError("The recovery module must remain unchanged")
    summary = {"schema": 1, "date": "2026-11-06", "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18", "baselineCommit": BASELINE,
               "qualification": False, "scope": "Real native writer exit and same-reader startup EBUSY then valid-command recovery retry, controlled SDK/editor APIs",
               "sourceSha256": {name: sha(MODULES / name) for name in ("runtime.cjs", "recovery.cjs", "test-runtime.cjs")},
               "evidenceToolsSha256": {name: sha(DOCS / name) for name in ("native-control.cjs", "run-native-control.py", "summarize.py")},
               "nativeControls": {"baseline": baseline, "fixed": fixed}}
    if args.tests:
        summary["automatedTests"] = validate_tests(args.tests.resolve())
    if args.checks:
        work = args.checks.resolve(); record = read(work / "python-final.json")
        for name, value in record["sourceHashes"].items():
            if sha(REPO / name) != value:
                raise ValueError("Python helper source snapshot differs")
        if record["outputSha256"] != sha(work / "python-final.txt") or record["tests"] != 39 or record["passes"] != 39:
            raise ValueError("Python helper output or count differs")
        if record["exitCode"] != 0 or not re.search(r"Ran 39 tests in .+\n\s*\nOK", (work / "python-final.txt").read_text(encoding="utf-8-sig")):
            raise ValueError("Final Python helpers must pass")
        summary["pythonHelpers"] = {"record": record, "testCount": 39, "rawEvidence": raw_files(work)}
    if args.installed_regression:
        work = args.installed_regression.resolve(); shared = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"
        spec = importlib.util.spec_from_file_location("installed_regression", shared); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        summary["installedRegression"] = module.summarize_run(work, True)
        for name, value in read(work / "expected.json")["candidate"]["ownedModules"].items():
            if sha(MODULES / name) != value:
                raise ValueError("Installed regression differs from current modules")
        summary["sharedInstalledSummarizerSha256"] = sha(shared)
    if args.installed_probe:
        summary["installedProbe"] = validate_installed_probe(args.installed_probe.resolve())
        if args.installed_regression and summary["installedProbe"]["record"]["expected"]["candidate"]["buildId"] != read(args.installed_regression.resolve() / "expected.json")["candidate"]["buildId"]:
            raise ValueError("Installed regression and probe must use the same final build identity")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), "sha256": sha(args.output)}))


if __name__ == "__main__":
    main()
