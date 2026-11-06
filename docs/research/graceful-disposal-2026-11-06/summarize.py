"""Retain graceful-disposal runtime, regression and same-host control evidence."""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path, PureWindowsPath


REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).parent


def module_from_file(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


web = module_from_file("web_lifecycle_summary", REPO / "docs/research/web-lifecycle-2026-11-05/summarize.py")
build = module_from_file("build_failure_summary", REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py")


def file_manifest(file):
    return {"path": str(file.resolve()), "sha256": web.sha256(file), "bytes": file.stat().st_size}


def raw_files(work):
    files = web.raw_files(work)
    for file in (work / "profile/logs").glob("**/*Disposal control *.log"):
        if file.is_file():
            files[file.relative_to(work).as_posix()] = {"sha256": web.sha256(file), "bytes": file.stat().st_size}
    return files


def verify_candidate(work, expected):
    candidate = expected["candidate"]
    if web.sha256(work / "local-lifecycle.vsix") != candidate["sha256"]:
        raise ValueError("Candidate differs from its recorded preparation")
    return candidate


def ordering_events(work):
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    return [event for event in trace if event["event"].startswith("helper-")
            or event["event"] in ("releasing-late-actual-start", "debuggee-process")
            or (event["event"] in ("dap-request", "dap-response", "adapter-event")
                and event.get("detail", {}).get("label") == "late-A")]


def late_ordering(work, result):
    events = ordering_events(work)
    def first(event_name, command=None, adapter_event=None):
        for event in events:
            detail = event.get("detail", {})
            message = detail.get("message", {})
            if (event["event"] == event_name and detail.get("label") == "late-A"
                    and (command is None or message.get("command") == command)
                    and (adapter_event is None or message.get("event") == adapter_event)):
                return event["atMilliseconds"]
        return None
    helper = next((helper for helper in result["helperContexts"] if helper["label"] == "late-A"), {})
    stops = helper.get("stopOutcomes", [])
    observed = {"configurationDoneRequestAtMilliseconds": first("dap-request", command="configurationDone"),
                "configurationDoneResponseAtMilliseconds": first("dap-response", command="configurationDone"),
                "terminateRequestAtMilliseconds": first("dap-request", command="terminate"),
                "terminateResponseAtMilliseconds": first("dap-response", command="terminate"),
                "disconnectRequestAtMilliseconds": first("dap-request", command="disconnect"),
                "nativeExitedAtMilliseconds": first("adapter-event", adapter_event="exited"),
                "nativeTerminatedAtMilliseconds": first("adapter-event", adapter_event="terminated"),
                "firstStopApiRequestedAtMilliseconds": stops[0]["requestedAtMilliseconds"] if stops else None,
                "followupStopApiRequestedAtMilliseconds": stops[1]["requestedAtMilliseconds"] if len(stops) > 1 else None}
    terminate = observed["terminateRequestAtMilliseconds"]
    configure = observed["configurationDoneRequestAtMilliseconds"]
    followup = observed["followupStopApiRequestedAtMilliseconds"]
    native_terminal = observed["nativeTerminatedAtMilliseconds"]
    observed["terminateRequestBeforeConfigurationDoneRequest"] = terminate < configure if terminate is not None and configure is not None else None
    observed["nativeTerminationBeforeFollowupApiStop"] = native_terminal < followup if native_terminal is not None and followup is not None else None
    return observed


def summarize_control(work, require_current=True):
    expected = web.read_json(work / "expected.json")
    result = web.read_json(work / "result.json")
    launcher = web.read_json(work / "launcher-result.json")
    if not result["success"] or result.get("firstFailure") or not launcher["success"] or launcher["editorExitCode"] != 0:
        raise ValueError("A failed control must retain its failure rather than become a passing result")
    if expected["scenario"] != "graceful-disposal-control" or result["expected"] != expected:
        raise ValueError("Expected the pinned direct-runtime disposal control")
    candidate = verify_candidate(work, expected)
    current_modules = {name: web.sha256(REPO / "scripts/variant/file-based-apps" / name)
                       for name in candidate["ownedModules"]}
    if result["installedModules"] != candidate["ownedModules"] or (require_current and current_modules != candidate["ownedModules"]):
        raise ValueError("The tested installed runtime must match current owned module bytes")
    preparation = expected["controlPreparation"]
    for name, key in (("prepare.py", "prepareSha256"), ("control.cjs", "controlSha256"), ("driver.cjs", "driverSha256")):
        if require_current and web.sha256(HERE / name) != preparation[key]:
            raise ValueError("Current control source differs from preparation: " + name)
    if (web.sha256(work / "driver/extension-test.cjs") != preparation["controlSha256"]
            or result["controlSha256"] != preparation["controlSha256"]
            or web.sha256(work / "driver/driver.cjs") != preparation["driverSha256"]):
        raise ValueError("Executed control copies differ from their preparation")
    for name, file in (("prepare.py", REPO / "scripts/variant/lifecycle/prepare.py"),
                       ("run.ps1", REPO / "scripts/variant/lifecycle/run.ps1"),
                       ("fixtures/web.cs", work / "workspace/b.cs")):
        if (require_current or name == "fixtures/web.cs") and web.sha256(file) != expected["harness"][name]:
            raise ValueError("Shared launcher/preparer/fixture differs from preparation: " + name)
    if require_current and web.sha256(REPO / "scripts/variant/lifecycle/prepare.py") != preparation["sharedPrepareSha256"]:
        raise ValueError("Shared preparation provenance differs")
    if launcher["candidateSha256"] != candidate["sha256"]:
        raise ValueError("Launcher candidate differs from expected")
    for helper in result["helperContexts"]:
        if (helper["registeredDisposeCalls"] != 1 or helper["outputDisposeCalls"] != 1
                or helper["listenersActive"] != 0 or helper["listenerDisposeCalls"] != {"start": 1, "terminate": 1}
                or helper["postDisposalWrites"] != 0 or helper["errors"] or helper["postDisposalResult"] is not False):
            raise ValueError("Helper resources did not drain exactly once without post-disposal writes")
        if require_current and helper["trackerDisposeCalls"] != 1:
            raise ValueError("The owned readiness tracker must drain exactly once")
        if require_current:
            count = len(helper["stopOutcomes"])
            limits = {"save-A": (0, 0), "active-A": (1, 1), "late-A": (1, 2)}
            minimum, maximum = limits[helper["label"]]
            if helper["stopRequests"] != count or not minimum <= count <= maximum:
                raise ValueError("Only the bounded exact-session Stop attempts are permitted")
    if {helper["label"] for helper in result["helperContexts"]} != {"active-A", "late-A", "save-A"}:
        raise ValueError("Expected all three direct-runtime disposal cases")
    save = next(helper for helper in result["helperContexts"] if helper["label"] == "save-A")
    if save["saveRequests"] != 1 or save["sdkFinderCalls"] != 0 or save["startRequests"] != 0:
        raise ValueError("A disposed pending save must not start SDK/debug work")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    return {
        "name": work.name, "localArtifactDirectory": str(work), "success": True,
        "elapsedMilliseconds": result["elapsedMilliseconds"], "scope": result["scope"],
        "candidate": candidate, "editor": expected["editor"] | {"apiVersion": result["editorApiVersion"]},
        "sdk": expected["sdk"], "dependency": expected["dependency"],
        "installedExtension": result["installedExtension"], "installedDependency": result["installedDependency"],
        "installedOwnedModules": result["installedModules"], "controlPreparation": preparation,
        "harnessPinnedBeforeLaunch": expected["harness"], "checks": result["checks"], "phases": result["phases"],
        "launches": result["launches"], "helperContexts": result["helperContexts"], "helperLogs": result["helperLogs"],
        "resourceObservations": [{"label": launch["label"], "capturedPid": launch.get("pid"),
                                  "pidExitAsserted": "pidGoneAtMilliseconds" in launch,
                                  "terminationObserved": bool(launch.get("terminated")),
                                  "portRebound": "portReusableAtMilliseconds" in launch,
                                  "outputRemoved": "outputRemovedAtMilliseconds" in launch}
                                 for launch in result["launches"]],
        "unrelatedSessionPreserved": [event for event in trace if event["event"] == "unrelated-preserved"],
        "orderingAndProtocolEvents": ordering_events(work),
        "lateSessionOrdering": late_ordering(work, result),
        "adapterDiagnostics": [event for event in trace if event["event"] == "adapter-error"],
        "rawEvidence": raw_files(work),
    }


def summarize_failure(work):
    result = web.read_json(work / "result.json")
    if result["success"]:
        raise ValueError("A passing control cannot be labelled as a failure")
    expected = web.read_json(work / "expected.json")
    preparation = expected["controlPreparation"]
    if (web.sha256(work / "driver/extension-test.cjs") != preparation["controlSha256"]
            or result["controlSha256"] != preparation["controlSha256"]
            or web.sha256(work / "driver/driver.cjs") != preparation["driverSha256"]):
        raise ValueError("Historical failed-control copies differ from their own preparation")
    package_files = list((work / "extensions").glob(expected["extensionId"] + "-*/package.json"))
    matching = [file for file in package_files if web.read_json(file).get("version") == expected["candidate"]["version"]]
    if len(matching) != 1:
        raise ValueError("Expected one normally installed candidate file for failed precondition investigation")
    package = web.read_json(matching[0])
    error = result["firstFailure"]["error"]
    kind = "control integration defect"
    if "__metadata" in error or "Normally installed candidate metadata must exist" in error:
        cause = "The extension API packageJSON omitted installer-private __metadata; raw installed package.json contains it."
        fix = "Inspect installer metadata in the installed file and match the public API identity separately."
    elif "linkPresentationRules" in error:
        cause = "Spreading the editor API object evaluated a proposed-API getter before helper SDK cases began."
        fix = "Construct an explicit stable-API facade without reading unrelated proposed getters."
    elif "read-only and non-configurable" in json.dumps(result["helperContexts"]):
        cause = "A controlled document Proxy violated the frozen save-property invariant; the save gate never opened and the control safety timer expired."
        fix = "Use an explicit document facade forwarding uri/isDirty/getText and gating the real save, with fail-fast gate waiting."
    elif "Safety timeout: pending handoff disposal observes and stops actual late session" in error:
        kind = "unexpected native late-session failure"
        cause = "The late native session did not terminate during the disposal phase; it terminated only after control-failure cleanup."
        fix = "Unresolved in this record; subsequent instrumented controls investigate Stop/start-settlement ordering."
    elif work.name == "run-07" and "Only the bounded exact-session Stop attempts are permitted" in error and any(
            helper["label"] == "save-A" and helper.get("stopRequests") == 0 and helper.get("stopOutcomes") == []
            for helper in result["helperContexts"]):
        cause = "The control bound assertion read a nonexistent internal stopRequests field; the serialized count correctly came from the empty stopOutcomes array."
        fix = "Assert stopOutcomes.length directly, retaining the same zero/one/bounded-two request limits."
    else:
        raise ValueError("An unclassified control failure needs an investigation record: " + work.name)
    return {"name": work.name, "localArtifactDirectory": str(work), "success": False,
            "scope": result["scope"], "controlPreparation": preparation,
            "harnessPinnedBeforeLaunch": expected["harness"], "executedControlSha256": result["controlSha256"],
            "kind": kind, "cause": cause, "fix": fix,
            "helperSdkCasesExecuted": any(helper["sdkFinderCalls"] > 0 for helper in result["helperContexts"]),
            "firstFailure": result["firstFailure"], "phases": result["phases"],
            "launches": result["launches"], "helperContexts": result["helperContexts"],
            "cleanup": result["cleanup"],
            "resourceObservations": [{"label": launch["label"], "capturedPid": launch.get("pid"),
                                      "terminationObserved": bool(launch.get("terminated")),
                                      "pidExitAsserted": "pidGoneAtMilliseconds" in launch}
                                     for launch in result["launches"]],
            "candidate": verify_candidate(work, expected),
            "installedPackageInvestigation": file_manifest(matching[0]) | {"installerMetadataPresent": bool(package.get("__metadata"))},
            "orderingAndProtocolEvents": ordering_events(work),
            "lateSessionOrdering": late_ordering(work, result),
            "launcher": web.read_json(work / "launcher-result.json"), "rawEvidence": raw_files(work)}


def test_evidence(artifacts):
    records = []
    record_files = sorted({file for pattern in ("baseline-regressions*.json", "strict-node-tests*.json",
                                               "configuration-retry-regressions*.json")
                           for file in artifacts.glob(pattern)})
    if not {"baseline-regressions.json", "strict-node-tests.json", "configuration-retry-regressions.json",
            "strict-node-tests-final.json"}.issubset({file.name for file in record_files}):
        raise ValueError("Original and final focused/full test records must be present")
    for record_file in record_files:
        name = record_file.stem
        output_file = artifacts / (name + ".txt")
        record = web.read_json(record_file)
        if record["outputSha256"] != web.sha256(output_file):
            raise ValueError("Test output differs from recorded hash: " + name)
        text = output_file.read_text(encoding="utf-8-sig")
        metrics = {key: int(value) for key, value in re.findall(r"^(?:ℹ|#) (tests|pass|fail|skipped) (\d+)$", text, re.MULTILINE)}
        if name in ("configuration-retry-regressions", "strict-node-tests-final"):
            if record["testRuntimeSha256"] != web.sha256(REPO / "scripts/variant/file-based-apps/test-runtime.cjs"):
                raise ValueError("Before/after regressions must use the current test fixture")
        if name == "strict-node-tests-final" and (record["runtimeSha256"] != web.sha256(REPO / "scripts/variant/file-based-apps/runtime.cjs")
                or metrics.get("tests", 0) < 1 or metrics.get("pass") != metrics["tests"]
                or metrics.get("fail") != 0 or metrics.get("skipped") != 0):
            raise ValueError("Expected the complete passing strict suite for current runtime")
        if name == "baseline-regressions" and (metrics.get("tests", 0) < 1 or metrics.get("pass") != 0
                or metrics.get("fail") != metrics["tests"] or metrics.get("skipped") != 0):
            raise ValueError("Expected all current regressions to fail the original runtime")
        if name == "configuration-retry-regressions":
            if metrics != {"tests": record["cases"], "pass": record["passCount"], "fail": record["failCount"], "skipped": 0}:
                raise ValueError("Focused readiness baseline counts differ from their recorded investigation")
            if metrics["fail"] < 1 or metrics["pass"] + metrics["fail"] != metrics["tests"]:
                raise ValueError("Focused readiness baseline must retain its failures and compatibility pass")
        source_role = "final current-source strict suite" if name == "strict-node-tests-final" else (
            "focused readiness regressions against initial ownership fix" if name == "configuration-retry-regressions" else "historical")
        entry = {"name": name, "sourceRole": source_role, "record": record, "metrics": metrics,
                 "recordFile": file_manifest(record_file), "output": file_manifest(output_file)}
        if name == "strict-node-tests-final":
            entry["focusedConfigurationPasses"] = [line for line in text.splitlines()
                                                   if re.match(r"^(?:✔ |ok \d+ - )adapter configuration ", line)]
        records.append(entry)
    by_name = {record["name"]: record for record in records}
    focused = by_name["configuration-retry-regressions"]
    if focused["record"]["runtimeSha256"] != by_name["strict-node-tests"]["record"]["runtimeSha256"]:
        raise ValueError("The readiness baseline must identify the initial ownership fix")
    if len(by_name["strict-node-tests-final"]["focusedConfigurationPasses"]) != focused["record"]["cases"]:
        raise ValueError("The final full suite must include every focused configuration case")
    return records


def compact_event(event):
    detail = event.get("detail", {})
    message = detail.get("message", {})
    item = {"event": event["event"], "atMilliseconds": event["atMilliseconds"], "label": detail.get("label")}
    for key in ("sessionId", "requestedAtMilliseconds", "actualInvokedAtMilliseconds", "resolvedAtMilliseconds", "result",
                "registeredDisposeCalls", "outputDisposeCalls", "trackerDisposeCalls", "listenersActive", "postDisposalWrites"):
        if key in detail:
            item[key] = detail[key]
    for key in ("command", "seq", "request_seq", "success"):
        if key in message:
            item[key] = message[key]
    if "event" in message:
        item["adapterEvent"] = message["event"]
    if "terminateDebuggee" in message.get("arguments", {}):
        item["terminateDebuggee"] = message["arguments"]["terminateDebuggee"]
    return item


def compact_log(log):
    retained = {key: value for key, value in log.items() if key != "buildCommands"}
    retained["buildCommands"] = [{"output": command["output"]} for command in log["buildCommands"]]
    return retained


def compact_run(row):
    row = dict(row)
    work = row["localArtifactDirectory"]
    runtime_dirs = set(row.pop("observedCoreRuntimeDirectories", []))
    launches = []
    for original in row.get("launches", []):
        runtime_dirs.update(str(PureWindowsPath(file).parent) for file in original.get("coreRuntimeModules", []))
        launch = {key: value for key, value in original.items() if key not in ("coreRuntimeModules", "capturedSessions", "program", "source")}
        if "capturedSessions" in original:
            launch["capturedSessions"] = [{key: owned[key] for key in ("sessionId", "pid", "terminated") if key in owned}
                                          for owned in original["capturedSessions"]]
        launches.append(launch)
    if "launches" in row:
        row["launches"] = launches
    row["uniqueCoreRuntimeDirectories"] = sorted(runtime_dirs)
    for key in ("helperLogs", "editor", "sdk", "dependency", "installedDependency", "observedCoreLibraryModulePaths",
                "successfulCommandControls", "validatedOutputLogs"):
        row.pop(key, None)
    if "installedOwnedModules" in row:
        row.pop("installedOwnedModules")
        row["installedModuleHashesVerified"] = True
    if "installedExtension" in row:
        row["installedExtension"] = {key: value for key, value in row["installedExtension"].items() if key in ("path", "version", "metadata")}
    for phase in row.get("phases", []):
        if "error" in phase:
            phase["error"] = phase["error"].splitlines()[0]
    failure = row.get("firstFailure")
    if failure:
        failure["errorSha256"] = hashlib.sha256(failure["error"].encode()).hexdigest()
        failure["error"] = failure["error"].splitlines()[0]
    for helper in row.get("helperContexts", []):
        for outcome in helper.get("startOutcomes", []):
            outcome.pop("program", None)
    if "orderingAndProtocolEvents" in row:
        row["orderingAndProtocolEvents"] = [compact_event(event) for event in row["orderingAndProtocolEvents"]]
    for attempt in row.get("failedBuildAttempts", []):
        for key in ("program", "base", "source"):
            attempt.pop(key, None)
        attempt["log"] = compact_log(attempt["log"])
    if row.get("coalescedRetry"):
        row["coalescedRetry"]["log"] = compact_log(row["coalescedRetry"]["log"])
    if "candidate" in row:
        row["candidate"].pop("path", None)
    # Keep one absolute artifact root per run; nested paths are relative views.
    def relative(value):
        if isinstance(value, dict):
            return {key: relative(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relative(item) for item in value]
        if isinstance(value, str):
            for prefix in (work, work.replace('\\', '/')):
                value = re.sub(re.escape(prefix), '<run>', value, flags=re.IGNORECASE)
        return value
    compacted = relative(row)
    compacted["localArtifactDirectory"] = work
    return compacted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--failed-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--regression-run", type=Path)
    parser.add_argument("--historical-regression-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--diagnostic-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--confirmation-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--test-artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    observed_failures = {file.parent.resolve() for file in args.run.resolve().parent.glob("run-*/result.json")
                         if web.read_json(file).get("success") is False}
    omitted = observed_failures - {work.resolve() for work in args.failed_runs}
    if omitted:
        raise ValueError("Retained failed controls must be included explicitly: " + ", ".join(sorted(str(work) for work in omitted)))
    control = summarize_control(args.run.resolve())
    summary = {"schema": 1, "date": "2026-11-06", "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
               "kind": "graceful runtime disposal and direct same-host native editor control", "qualification": False,
               "runtimeSha256": web.sha256(REPO / "scripts/variant/file-based-apps/runtime.cjs"),
               "testRuntimeSha256": web.sha256(REPO / "scripts/variant/file-based-apps/test-runtime.cjs"),
               "summarizerSha256": web.sha256(Path(__file__).resolve()), "control": control,
               "tests": test_evidence(args.test_artifacts.resolve())}
    summary["independentFinalReviewLogs"] = {name: file_manifest(args.test_artifacts.resolve() / name)
        for name in ("final-review-node.txt", "final-review-python.txt") if (args.test_artifacts.resolve() / name).exists()}
    summary["failedControls"] = [summarize_failure(work.resolve()) for work in args.failed_runs]
    summary["diagnosticControls"] = [summarize_control(work.resolve(), require_current=False) |
                                     {"interpretation": "Diagnostic control result; a pass alone does not resolve an earlier native failure."}
                                     for work in args.diagnostic_runs]
    summary["confirmationControls"] = [summarize_control(work.resolve()) for work in args.confirmation_runs]
    for confirmation in summary["confirmationControls"]:
        if (confirmation["candidate"]["ownedModules"] != control["candidate"]["ownedModules"]
                or confirmation["controlPreparation"] != control["controlPreparation"]):
            raise ValueError("Confirmation controls must keep the final runtime and control source pins")
    if args.regression_run:
        regression = build.summarize_run(args.regression_run.resolve(), latest=True)
        if regression["candidate"]["ownedModules"] != control["candidate"]["ownedModules"]:
            raise ValueError("Installed-command regression and direct control must test identical owned runtime bytes")
        summary["installedCommandRegression"] = regression
    summary["historicalInstalledCommandRegressions"] = [build.summarize_run(work.resolve(), latest=False) |
        {"interpretation": "Historical installed-command control; retain its own candidate/runtime identity, not the final repair identity."}
        for work in args.historical_regression_runs]
    summary["sharedProvenance"] = {key: control[key] for key in ("editor", "sdk", "dependency")}
    summary["sharedProvenance"]["packagedBuild"] = {key: value for key, value in control["installedExtension"]["build"].items()
                                                  if key not in ("localCandidate", "lifecycleBuildId", "lifecycleSourceCommit")}
    summary["pathConvention"] = "Nested <run> paths are relative to each row's localArtifactDirectory; full raw results/traces remain hashed and unchanged."
    summary["control"] = compact_run(summary["control"])
    for key in ("failedControls", "diagnosticControls", "confirmationControls", "historicalInstalledCommandRegressions"):
        summary[key] = [compact_run(row) for row in summary[key]]
    if "installedCommandRegression" in summary:
        summary["installedCommandRegression"] = compact_run(summary["installedCommandRegression"])
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), "sha256": web.sha256(args.output)}))


if __name__ == "__main__":
    main()
