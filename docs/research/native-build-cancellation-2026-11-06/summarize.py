"""Validate retained native Cancel/retry controls and retain all earlier failures."""
import argparse
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SHARED = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"
spec = importlib.util.spec_from_file_location("compiler_failure_summary", SHARED)
failure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(failure)
web = failure.web
EXTRA_RAW = ("needs-ui-cancel.json", "ui-cancel-action.json", "ui-observation.json",
             "ui-action-failure-01.json", "ui-cancel-action-attempt-01.json",
             "ui-window-inventory.json", "direct-build-ownership.json", "sdk-build-process.json", "progress/sdk-build-ready.json",
             "progress/release-sdk-build")


def raw_files(work):
    raw = web.raw_files(work)
    for name in EXTRA_RAW:
        file = work / name
        if file.is_file():
            raw[name] = {"sha256": web.sha256(file), "bytes": file.stat().st_size}
    for file in work.glob("ui-*.json"):
        raw[file.name] = {"sha256": web.sha256(file), "bytes": file.stat().st_size}
    return raw


def verify_current_sources(expected):
    for name, value in expected["candidate"]["ownedModules"].items():
        if web.sha256(REPO / "scripts/variant/file-based-apps" / name) != value:
            raise ValueError("Final installed candidate differs from the current runtime: " + name)
    for name, value in expected["harness"].items():
        if name == "prepared/a.cs":
            continue  # A is intentionally saved and changed during the test.
        source = REPO / "scripts/variant/lifecycle" / name
        if web.sha256(source) != value:
            raise ValueError("Final source differs from the latest run: " + name)
    native = expected.get("nativeCancellation")
    if native and web.sha256(Path(native["target"])) != expected["harness"]["fixtures/cancel-build.targets"]:
        raise ValueError("Executed cancellation target differs from its pinned fixture")


def summarize_run(work, current=True):
    result = web.read_json(work / "result.json")
    expected = web.read_json(work / "expected.json")
    if result["expected"] != expected:
        raise ValueError("Preparation metadata differs from the executed result snapshot")
    if expected.get("scenario") != "native-build-cancel":
        raise ValueError("Expected explicit native-build-cancel scenario")
    summary = web.summarize_run(work, REPO)
    if current:
        verify_current_sources(expected)
    native = expected["nativeCancellation"]
    request = web.read_json(work / "needs-ui-cancel.json")
    receipt = web.read_json(work / "ui-cancel-action.json")
    if (request["nonce"] != native["nonce"] or receipt["nonce"] != native["nonce"]
            or receipt["windowTitle"] != native["windowTitle"] or receipt["action"] != "click-cancel"
            or (work / "progress/release-sdk-build").exists()):
        raise ValueError("UI receipt/fixture identity mismatch or success relied on barrier release")
    attempts = result["cancelledBuildAttempts"]
    if len(attempts) != 1 or result["failedBuildAttempts"]:
        raise ValueError("Expected exactly one native-cancel attempt, not a compiler-failure branch")
    attempt = attempts[0]
    marker = attempt["marker"]
    if (attempt["commandInvocations"] != 3 or attempt["commandResults"] != [False, False, False]
            or not attempt["sourceSaved"] or not attempt["noSession"] or attempt["capturedSessions"]
            or marker["nonce"] != native["nonce"] or marker["pid"] != request["pid"]
            or marker["pid"] != attempt["buildPid"]):
        raise ValueError("Expected saved, coalesced cancellation with no session and nonce-owned direct PID")
    process = web.read_json(work / "sdk-build-process.json")
    exact = process.get("exactProcess") or {}
    normalize = lambda value: str(value).replace("\\", "/").casefold()
    command = normalize(exact.get("CommandLine", ""))
    if (process.get("schema") != 1 or process.get("directSdkBuild") is not True
            or process.get("pid") != marker["pid"] or exact.get("ProcessId") != marker["pid"]
            or normalize(exact.get("ExecutablePath", "")) != normalize(expected["sdk"]["executable"])
            or " build " not in command or normalize(attempt["source"]) not in command
            or normalize(attempt["output"]) not in command or "-p:assemblyname=fileapp" not in command):
        raise ValueError("Marker PID must be externally tied to the exact direct SDK build, source and output")
    for key in ("buildPidGoneObservedAtMilliseconds", "outputRemovedAtMilliseconds", "portReusableAtMilliseconds"):
        if attempt[key] < attempt["returnedAtMilliseconds"]:
            raise ValueError("Post-return observation predates return: " + key)
    log = attempt["log"]
    if (len(log["buildCommands"]) != 1 or len(log["cancelledPhaseDiagnostics"]) != 1
            or log["failedPhaseDiagnostics"] or log["completedPhaseDiagnostics"]):
        raise ValueError("Expected one cancelled real build, distinct from failure/handoff")
    retry = result["coalescedRetry"]
    if (retry["commandInvocations"] != 3 or retry["commandResults"] != [True, True, True]
            or retry["sessionIds"] != [retry["sessionId"]] or not retry["freshOutput"]
            or retry["failedOutput"] != attempt["output"] or retry["output"] == attempt["output"]
            or len(retry["log"]["buildCommands"]) != 1
            or len(retry["log"]["completedPhaseDiagnostics"]) != 1
            or retry["log"]["failedPhaseDiagnostics"] or retry["log"]["cancelledPhaseDiagnostics"]):
        raise ValueError("Expected one successful dirty retry shared by three callers with fresh output")
    if not any(launch["sessionId"] == retry["sessionId"] and launch["output"] == retry["output"]
               for launch in result["launches"]):
        raise ValueError("Retry session/output must identify a captured ordinary launch")
    for retained in (log, retry["log"]):
        failure.validate_log_slice(retained)
    summary.update(scenario=expected["scenario"], nativeCancellation=native, cancelledBuildAttempts=attempts,
                   coalescedRetry=retry, uiRequest=request, uiAction=receipt, directSdkBuildProcess=process,
                   uiReceiptInterpretation="Operator attestation; consult retained UI tool trace/observation for actual click evidence.")
    observation = web.read_json(work / "ui-observation.json")
    before = observation.get("before") or {}
    observed_window = before.get("window") or {}
    tree = (before.get("accessibility") or {}).get("tree", "")
    index = receipt.get("elementIndex")
    if (observation.get("actualCancelClicked") is not True
            or observed_window.get("id") != receipt.get("windowId")
            or native["windowTitle"] not in observed_window.get("title", "")
            or not isinstance(index, int) or not re.search(rf"(?m)^\s*{index}\s+.*\bCancel\b", tree)):
        raise ValueError("Passing native control must retain an actual Cancel UI observation/action record")
    if datetime.fromisoformat(process["observedAtUtc"]) > datetime.fromisoformat(receipt["clickedAtUtc"]):
        raise ValueError("Direct SDK process ownership must be observed before the actual UI click")
    summary["uiObservation"] = observation
    summary["rawEvidence"].update(raw_files(work))
    summary["rawEvidence"].update(failure.output_logs(work, (log, retry["log"])))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="*", default=[])
    parser.add_argument("--failed-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--normal-control", type=Path)
    parser.add_argument("--gate-preflight", type=Path)
    parser.add_argument("--fixture-controls", type=Path)
    parser.add_argument("--checks", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("evidence-summary.json"))
    args = parser.parse_args()
    supplied = args.runs + args.failed_runs + ([args.normal_control] if args.normal_control else [])
    failed_paths = {work.resolve() for work in args.failed_runs}
    for parent in {work.resolve().parent for work in supplied}:
        for result_file in parent.glob("run-*/result.json"):
            if not web.read_json(result_file).get("success") and result_file.parent.resolve() not in failed_paths:
                raise ValueError("Retained failed profile omitted from --failed-runs: " + str(result_file.parent))
    runs = [summarize_run(work.resolve(), index == len(args.runs) - 1)
            for index, work in enumerate(args.runs)]
    failures = []
    for directory in args.failed_runs:
        work = directory.resolve()
        retained = {name: web.read_json(work / name)
                    for name in ("result.json", "launcher-result.json", "needs-ui-cancel.json",
                                 "ui-observation.json", "sdk-build-process.json")
                    if (work / name).exists()}
        if retained.get("result.json", {}).get("success"):
            raise ValueError("A successful run cannot be relabelled as a failure")
        failures.append({"name": work.name, "localArtifactDirectory": str(work),
                         "retainedResults": retained, "rawEvidence": raw_files(work)})
    summary = {
        "schema": 1, "date": "2026-11-06", "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
        "kind": "local installed VSCodium native build cancellation and concurrent retry control",
        "qualification": False, "nativeCancellationPassed": bool(runs),
        "finalHarnessRun": runs[-1]["name"] if runs else None,
        "finalHarnessFreshProfiles": 1 if runs else 0,
        "harnessSourceSha256AtSummary": {name: web.sha256(REPO / name) for name in web.HARNESS +
            ("scripts/variant/lifecycle/fixtures/cancel-build.targets", "scripts/variant/file-based-apps/test-runtime.cjs")},
        "summarizerSha256": web.sha256(Path(__file__).resolve()),
        "sharedSummarizersSha256": {"compilerFailure": web.sha256(SHARED), "webLifecycle": web.sha256(failure.SHARED)},
        "unexpectedFailures": failures, "runs": runs,
    }
    if args.normal_control:
        work = args.normal_control.resolve()
        expected = web.read_json(work / "expected.json")
        result = web.read_json(work / "result.json")
        if (expected.get("scenario") != "web-lifecycle" or result["failedBuildAttempts"]
                or result["cancelledBuildAttempts"] or result.get("coalescedRetry") is not None):
            raise ValueError("Normal regression must exercise only the unchanged default branch")
        verify_current_sources(expected)
        control = web.summarize_run(work, REPO)
        control.update(scenario=expected["scenario"])
        summary["normalControl"] = control
    if args.gate_preflight:
        work = args.gate_preflight.resolve()
        ownership = web.read_json(work / "ownership.json")
        if not ownership["verified"] or ownership["marker"]["nonce"] not in ownership["directBuildCommand"]:
            raise ValueError("CLI fixture preflight must retain direct-build ownership evidence")
        summary["gatePreflight"] = {
            "localArtifactDirectory": str(work), "ownership": ownership,
            "scope": "CLI fixture mechanics only; not editor Cancel evidence",
            "rawEvidence": {file.relative_to(work).as_posix(): {"sha256": web.sha256(file), "bytes": file.stat().st_size}
                for file in work.iterdir() if file.is_file()},
        }
    if args.fixture_controls:
        work = args.fixture_controls.resolve()
        record = web.read_json(work / "result.json")
        target_hash = web.sha256(REPO / "scripts/variant/lifecycle/fixtures/cancel-build.targets")
        expected_cases = {"default-assembly": False, "design-time-fileapp": False, "regular-fileapp": True}
        if (not record["success"] or record["targetSha256"] != target_hash
                or {case["name"]: case["expectedMarker"] for case in record["cases"]} != expected_cases):
            raise ValueError("Expected all three controls of the final filtered fixture")
        files = [file for file in work.iterdir() if file.is_file()]
        for case in record["cases"]:
            directory = work / case["name"]
            if (not case["success"] or case["buildExitCode"] != 0 or not case["noCs0162"]
                    or case["markerExists"] != case["expectedMarker"]
                    or web.sha256(directory / "cancel-build.targets") != target_hash
                    or web.sha256(directory / "probe.cs") != case["sourceSha256"]):
                raise ValueError("Filtered fixture input/result mismatch: " + case["name"])
            if case["expectedMarker"]:
                ownership = case["ownership"]
                if (not ownership["verified"] or ownership["marker"]["pid"] != case["directChildPid"]
                        or ownership["marker"]["nonce"] != case["nonce"]
                        or not case["releasedAfterNoncePidAndCimVerification"]):
                    raise ValueError("Positive fixture control needs exact direct-build ownership and release")
            files.extend(file for file in directory.iterdir() if file.is_file())
        summary["filteredFixtureControls"] = {
            "localArtifactDirectory": str(work), "record": record,
            "scope": "Final fixture selection/barrier mechanics only; not editor Cancel evidence",
            "rawEvidence": {file.relative_to(work).as_posix(): {"sha256": web.sha256(file), "bytes": file.stat().st_size}
                            for file in files},
        }
    if args.checks:
        work = args.checks.resolve()
        record = web.read_json(work / "result.json")
        rows = {row["name"]: row for row in record["checks"]}
        if not record["success"] or any(row["exitCode"] != 0 for row in rows.values()):
            raise ValueError("Final retained automated checks must all pass")
        for source in record["sourceHashes"]:
            if web.sha256(REPO / source["path"]) != source["sha256"]:
                raise ValueError("Automated check source differs from final files: " + source["path"])
        node = rows["strict-node"]
        stdout = Path(node["stdout"]).read_text(encoding="utf-8-sig")
        counts = {name: int(value) for name, value in re.findall(
            r"(?m)^[ℹ#]\s+(tests|pass|fail|cancelled|skipped|todo)\s+(\d+)\s*$", stdout)}
        required = {"tests": 151, "pass": 151, "fail": 0, "cancelled": 0, "skipped": 0, "todo": 0}
        python = rows["python-helpers"]
        stderr = Path(python["stderr"]).read_text(encoding="utf-8-sig")
        if (counts != required or node["counts"] != counts or python["testCount"] != 39
                or not re.search(r"Ran 39 tests in .+\n\s*\nOK", stderr)):
            raise ValueError("Retained raw Node/Python outputs must match the final reported counts")
        summary["automatedChecks"] = {
            "localArtifactDirectory": str(work), "record": record,
            "rawEvidence": {file.name: {"sha256": web.sha256(file), "bytes": file.stat().st_size}
                            for file in work.iterdir() if file.is_file()},
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), "sha256": web.sha256(args.output),
                      "runs": len(runs), "failures": len(failures)}))


if __name__ == "__main__":
    main()
