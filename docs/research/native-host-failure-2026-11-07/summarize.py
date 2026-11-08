"""Validate retained real .NET host startup failure and corrected retry evidence."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE = "c712ede7edb303d42b95d083a724315adf44aa3d"
PREVIOUS = REPO / "docs/research/debug-handoff-declined-2026-11-07/summarize.py"
spec = importlib.util.spec_from_file_location("native_host_previous_summary", PREVIOUS)
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
# Reuse the identity contract against this exact merged base; the older
# scenario-specific editor-rejection validator is not used.
previous.BASE = BASE
build, web = previous.build, previous.web
read, binding, same, inside = previous.read, previous.binding, previous.same, previous.inside
snapshot, log_tail, commands = previous.snapshot, previous.log_tail, previous.commands
DIAGNOSTIC = "Invalid value for environment variable 'DOTNET_ROLL_FORWARD'."
INVALID_ROLL_FORWARD = "LIFECYCLE_INVALID_ROLL_FORWARD"


def validate_units(directory):
    metadata = read(directory / "source-manifest.json")
    if (metadata["commit"] != BASE or len(metadata["runs"]) != 2
            or not same(metadata["worktree"], REPO)):
        raise ValueError("Expected the exact recorded base and separate Node/Python attempts")
    sources = {item["path"]: item for item in metadata["source"]}
    tests = [f"scripts/variant/file-based-apps/test-{name}.cjs" for name in ("classify", "entry", "recovery", "runtime", "web")]
    required = {f"scripts/variant/file-based-apps/{name}" for name in previous.MODULE_NAMES}
    required.update(tests)
    required.update(web.HARNESS)
    if len(sources) != 46 or len(sources) != len(metadata["source"]) or not required.issubset(sources):
        raise ValueError("Source manifest must bind every product module, selected Node suite and executed harness")
    for name, item in sources.items():
        file = REPO / name
        historical = directory / "source" / name
        if (not inside(REPO / "scripts/variant", file) or web.sha256(file) != item["sha256"]
                or file.stat().st_size != item["size"] or file.read_bytes() != historical.read_bytes()):
            raise ValueError("Current or retained source differs from pre-run hash: " + name)
    for name in ("node", "python"):
        if web.sha256(Path(metadata[name]["path"])) != metadata[name]["sha256"]:
            raise ValueError("Pinned verification runtime differs: " + name)
    expected_argv = {
        "node.log": [metadata["node"]["path"], "--unhandled-rejections=strict", "--test", *tests],
        "python.log": [metadata["python"]["path"], "-B", "-m", "unittest", "discover", "-s", "scripts/variant", "-p", "test_*.py", "-v"],
    }
    if {record["log"] for record in metadata["runs"]} != set(expected_argv):
        raise ValueError("Every attempted unit invocation must remain distinct")
    frozen = datetime.fromisoformat(metadata["frozenUtc"].replace("Z", "+00:00"))
    verified = datetime.fromisoformat(metadata["finalSourceVerifiedUtc"].replace("Z", "+00:00"))
    rows = []
    for record in metadata["runs"]:
        log = directory / record["log"]
        result_file = directory / record["log"].replace(".log", "-result.json")
        result = record["result"]
        if (record["argv"] != expected_argv[record["log"]] or read(result_file) != result
                or web.sha256(log) != result["logSha256"] or result["exitCode"] != 0
                or not (frozen <= datetime.fromisoformat(result["startedUtc"].replace("Z", "+00:00"))
                        <= datetime.fromisoformat(result["completedUtc"].replace("Z", "+00:00")) <= verified)):
            raise ValueError("Recorded argv, result, log or source-freeze timestamps differ")
        text = log.read_text(encoding="utf-8-sig")
        if record["log"] == "node.log":
            counts = {key: int(value) for key, value in re.findall(
                r"(?m)^(?:#|ℹ) (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$", text)}
            if counts != {"tests": 228, "pass": 228, "fail": 0, "cancelled": 0, "skipped": 0, "todo": 0}:
                raise ValueError("Expected the complete 228-case strict natural-exit Node suite")
        else:
            if (re.findall(r"Ran (\d+) tests? in", text) != ["39"] or not re.search(r"(?m)^OK\s*$", text)):
                raise ValueError("Expected all 39 Python helpers")
            counts = {"tests": 39, "result": "OK"}
        rows.append({"record": record, "counts": counts, "rawLog": binding(log), "rawResult": binding(result_file)})
    return {"directory": str(directory), "manifest": metadata,
            "manifestFile": binding(directory / "source-manifest.json"), "runs": rows,
            "sourceObservation": "Every pre-run source byte copy, hash and final verification timestamp is retained; current bytes and historical copies are rechecked against every manifest entry."}


def validate_failure(work):
    result, launcher = read(work / "result.json"), read(work / "launcher-result.json")
    if result["success"] or not result.get("firstFailure") or launcher["success"]:
        raise ValueError("An unexpected failed attempt must retain its original failure")
    raw = web.raw_files(work)
    raw.update(build.output_logs(work))
    return {"directory": str(work), "result": result, "launcher": launcher, "rawEvidence": raw,
            "interpretation": "Separate unexpected attempt; not passing native-host-failure coverage."}


def validate_native_failure(work, expected, result):
    scope = result["scope"]
    if (not scope["actualNativeHostFailure"] or scope["nativeAdapterFailure"]
            or scope["injectedEditorRejection"] or scope["injectedTargetRuntime"]
            or any(scope[key] for key in ("actualCompilerFailure", "actualWebProfileFailure", "actualSdkSelectionFailure"))
            or any(result[key] for key in ("failedBuildAttempts", "failedWebProfileAttempts", "failedSdkSelectionAttempts", "failedHandoffAttempts", "cancelledBuildAttempts"))
            or len(result["failedNativeHostAttempts"]) != 1 or result["cleanup"]):
        raise ValueError("Expected one deliberately induced real native host failure without test safety cleanup")
    attempt = result["failedNativeHostAttempts"][0]
    initial = next(launch for launch in result["launches"] if launch["label"] == "A-0")
    b = next(launch for launch in result["launches"] if launch["label"] == "B")
    source, profile = work / "workspace/a.cs", work / "workspace/a.run.json"
    original_source = snapshot(attempt["sourceSnapshot"], source)
    original_profile = json.loads(snapshot(initial["profileSnapshot"], profile))
    failed_profile_bytes = snapshot(attempt["profileSnapshot"], profile)
    failed_profile = json.loads(failed_profile_bytes)
    expected_profile = json.loads(json.dumps(original_profile))
    environment = expected_profile["profiles"]["LifecycleHttp"]["environmentVariables"]
    environment.update(LIFECYCLE_TOKEN=attempt["nonce"], DOTNET_ROLL_FORWARD=INVALID_ROLL_FORWARD)
    if (not attempt["expectedNativeHostFailure"] or attempt["invalidRollForward"] != INVALID_ROLL_FORWARD
            or not same(attempt["source"], source) or attempt["sourceWasDirty"] is not False
            or attempt["revision"] != initial["revision"] or attempt["port"] != initial["port"]
            or attempt["origin"] != initial["origin"] or failed_profile != expected_profile
            or original_source != snapshot(initial["sourceSnapshot"], source)
            or original_source != snapshot(attempt["sourceAfterSnapshot"], source)
            or failed_profile_bytes != snapshot(attempt["profileAfterSnapshot"], profile)
            or attempt["ambientDotnetRootBefore"] != attempt["ambientDotnetRootAfter"]
            or not same(attempt["ambientDotnetRootBefore"], expected["sdk"]["root"])
            or attempt["ambientRollForwardBefore"] != attempt["ambientRollForwardAfter"]
            or attempt["nonce"] in {launch["nonce"] for launch in result["launches"]}):
        raise ValueError("Only the failed file's HTTP token and roll-forward environment may change; source and ambient environment must remain intact")
    command_results = attempt["commandResults"]
    if (attempt["commandInvocations"] != 3 or len(command_results) != 3
            or any(type(value) is not bool for value in command_results)
            or len(set(command_results)) != 1 or attempt["commandPending"]
            or attempt["adapterCreationCount"] != 1 or attempt["editorStartCount"] not in (0, 1)
            or len(attempt["capturedSessions"]) != 1 or not attempt["terminated"]
            or not attempt["terminationObservedWithoutTestStop"]
            or not attempt["outputAbsent"] or not attempt["terminalQueuesEmpty"]):
        raise ValueError("Three callers must share one measured native attempt which terminates without test Stop and releases its owned resources")
    output, program, base = Path(attempt["output"]), Path(attempt["program"]), Path(attempt["base"])
    config = attempt["capturedConfiguration"]
    captured = attempt["capturedSessions"][0]
    if (config["type"] != "coreclr" or config["request"] != "launch"
            or not same(config["program"], program) or not same(config["__netcoredbgFileAppOutput"], output)
            or not same(program, output / "FileApp.dll") or not inside(work, output)
            or not same(base, output.parent.parent) or not same(base, Path(initial["output"]).parent.parent)
            or not same(attempt["expectedBase"], base) or not same(attempt["previousOutput"], initial["output"])
            or not re.fullmatch(r"run-[A-Za-z0-9]{6}", output.name)
            or output in (Path(initial["output"]), Path(b["output"]))
            or not same(config["cwd"], source.parent) or not same(config["env"]["DOTNET_ROOT"], expected["sdk"]["root"])
            or config["env"]["DOTNET_ROLL_FORWARD"] != INVALID_ROLL_FORWARD
            or config["env"]["LIFECYCLE_TOKEN"] != attempt["nonce"]
            or config["env"]["ASPNETCORE_URLS"] != attempt["origin"]
            or config["checkForDevCert"] is not False or "serverReadyAction" in config
            or captured["sessionId"] != attempt["sessionId"] or not captured["primary"] or not captured["terminated"]
            or not same(captured["program"], program) or not same(captured["output"], output)):
        raise ValueError("The normal generated program/output and exact captured session must own the real native launch")
    artifacts = attempt["builtArtifacts"]
    if len(artifacts) != 3:
        raise ValueError("DLL, PDB and runtimeconfig metadata must be sampled while present")
    for artifact, name in zip(artifacts, ("FileApp.dll", "FileApp.pdb", "FileApp.runtimeconfig.json")):
        if (not same(artifact["path"], output / name) or artifact["size"] <= 0
                or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])):
            raise ValueError("Native launch artifact metadata differs")
    runtime_bytes = snapshot(attempt["runtimeConfigSnapshot"], output / "FileApp.runtimeconfig.json")
    if (len(runtime_bytes) != artifacts[2]["size"] or hashlib.sha256(runtime_bytes).hexdigest() != artifacts[2]["sha256"]
            or not any(framework["name"] == "Microsoft.NETCore.App"
                       for framework in json.loads(runtime_bytes)["runtimeOptions"]["frameworks"])):
        raise ValueError("The unmodified SDK runtimeconfig must retain its real framework reference")
    requests = attempt["dapRequests"]
    for command, successful, key in (("initialize", True, "initializeResponse"), ("configurationDone", False, "configurationDoneFailure")):
        request_rows = [item for item in requests if item["message"]["type"] == "request" and item["message"]["command"] == command]
        pair = attempt[key]
        if (len(request_rows) != 1 or pair["request"] != request_rows[0]
                or request_rows[0]["sessionId"] != attempt["sessionId"]
                or pair["response"] not in attempt["dap"] or pair["response"]["type"] != "response"
                or pair["response"]["command"] != command or pair["response"]["success"] is not successful
                or pair["response"]["request_seq"] != request_rows[0]["message"]["seq"]):
            raise ValueError("The healthy adapter initialize and native configurationDone failure must correlate to their exact requests")
    launch_requests = [item for item in requests if item["message"]["type"] == "request" and item["message"]["command"] == "launch"]
    if len(launch_requests) != 1 or attempt["nativeLaunchRequest"] != launch_requests[0]:
        raise ValueError("Expected one real native launch request")
    native_args = launch_requests[0]["message"]["arguments"]
    native_launch_responses = [message for message in attempt["dap"] if message.get("type") == "response"
                               and message.get("command") == "launch"
                               and message.get("request_seq") == launch_requests[0]["message"]["seq"]]
    if (launch_requests[0]["sessionId"] != attempt["sessionId"] or not same(native_args["program"], program)
            or not same(native_args["__netcoredbgFileAppOutput"], output)
            or native_args["env"]["LIFECYCLE_TOKEN"] != attempt["nonce"]
            or native_args["env"]["DOTNET_ROLL_FORWARD"] != INVALID_ROLL_FORWARD
            or len(native_launch_responses) != 1 or native_launch_responses[0]["success"] is not True):
        raise ValueError("Native DAP launch must retain the generated output and exact failed-file environment")
    diagnostics = [message for message in attempt["dap"] if message.get("event") == "output"
                   and DIAGNOSTIC in message.get("body", {}).get("output", "")]
    process_events = [message for message in attempt["dap"] if message.get("event") == "process"]
    if (not diagnostics or any(message["body"].get("category") != "stderr" for message in diagnostics)
            or attempt["hostDiagnostics"] != diagnostics or attempt["processEvents"] != process_events):
        raise ValueError("The real .NET host diagnostic and measured process events must be projected from retained DAP")
    if attempt.get("pid") is not None and not attempt.get("reportedPidGoneAtMilliseconds"):
        raise ValueError("Any captured failed-host PID must have its own observed exit")
    tail = previous.validate_build(attempt["log"], source, output, command_results[0])
    web_complete = [line for line in tail.splitlines() if line.startswith("Phase completed: Preparing web launch settings")]
    handoff_failed = [line for line in tail.splitlines() if line.startswith("Phase failed: Starting netcoredbg")]
    if (attempt["log"]["webPreparationCompletedPhaseDiagnostics"] != web_complete or len(web_complete) != 1
            or attempt["log"]["handoffFailedPhaseDiagnostics"] != handoff_failed
            or len(handoff_failed) != int(not command_results[0])):
        raise ValueError("The exact build log must distinguish measured API handoff status from later native failure")
    if (output.exists() or not (attempt["invokedAtMilliseconds"] <= attempt["returnedAtMilliseconds"] <= attempt["outputRemovedAtMilliseconds"]
                               and attempt["terminatedAtMilliseconds"] <= attempt["outputRemovedAtMilliseconds"] <= attempt["portReusableAtMilliseconds"])):
        raise ValueError("Failed output cleanup and port observations must follow the captured command and termination")
    for name in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1"):
        queue = base / name
        if queue.exists() and any(queue.iterdir()):
            raise ValueError("The exact terminal cleanup queues must remain empty")
    coalesced = result["coalescedRetry"]
    corrected = next(launch for launch in result["launches"] if launch["sessionId"] == coalesced["sessionId"])
    corrected_source = snapshot(coalesced["sourceSnapshot"], source)
    corrected_profile = json.loads(snapshot(coalesced["profileSnapshot"], profile))
    expected_profile = json.loads(json.dumps(original_profile))
    expected_profile["profiles"]["LifecycleHttp"]["environmentVariables"]["LIFECYCLE_TOKEN"] = corrected["nonce"]
    before_revision = f'const string revision = "{initial["revision"]}";'.encode()
    after_revision = f'const string revision = "{corrected["revision"]}";'.encode()
    if (coalesced["commandInvocations"] != 3 or coalesced["commandResults"] != [True] * 3
            or coalesced["sessionIds"] != [coalesced["sessionId"]] or not coalesced["freshOutput"]
            or not same(coalesced["failedOutput"], output) or same(coalesced["output"], output)
            or same(coalesced["output"], initial["output"]) or corrected["nonce"] in (attempt["nonce"], initial["nonce"])
            or corrected["port"] != initial["port"] or corrected_profile != expected_profile
            or original_source.count(before_revision) != 1 or original_source.replace(before_revision, after_revision, 1) != corrected_source
            or coalesced["sourceSnapshot"] != corrected["sourceSnapshot"] or coalesced["profileSnapshot"] != corrected["profileSnapshot"]
            or not coalesced["correctedRollForwardProfile"] or not coalesced["freshToken"]
            or coalesced["failedNonce"] != attempt["nonce"] or coalesced["nonce"] != corrected["nonce"]
            or "DOTNET_ROLL_FORWARD" in coalesced["nativeLaunchEnvironment"]
            or coalesced["nativeLaunchEnvironment"]["LIFECYCLE_TOKEN"] != corrected["nonce"]
            or not same(coalesced["nativeLaunchEnvironment"]["DOTNET_ROOT"], expected["sdk"]["root"])
            or not same(corrected["output"], coalesced["output"])):
        raise ValueError("Corrected dirty retry must remove the invalid environment and share one saved build, fresh session/token/output across three callers")
    previous.validate_build(coalesced["log"], source, corrected["output"], True)
    b_identity = {key: b[key] for key in ("sessionId", "pid", "nonce", "output", "response")}
    if attempt["bBefore"] != b_identity or attempt["bAfter"] != b_identity:
        raise ValueError("B must retain its exact session/PID/token/HTTP body/output")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    owned_trace = [event for event in trace if event.get("detail", {}).get("label") == attempt["label"]]
    sent = [{"sessionId": event["detail"]["sessionId"], "message": event["detail"]["message"]}
            for event in owned_trace if event["event"] == "dap-send"]
    received = [event["detail"]["message"] for event in owned_trace if event["event"] == "dap-receive"]
    terminations = [event for event in owned_trace if event["event"] == "editor-terminate"]
    exits = [event["detail"] for event in owned_trace if event["event"] == "adapter-exit"]
    if (sent != requests or received != attempt["dap"] or len(terminations) != 1
            or terminations[0]["detail"]["sessionId"] != attempt["sessionId"]
            or attempt["adapterExits"] != exits or len(exits) != 1 or exits[0]["code"] != 0
            or exits[0]["sessionId"] != attempt["sessionId"]
            or exits[0]["atMilliseconds"] > attempt["terminatedAtMilliseconds"]
            or any(event["event"] == "stop-request" for event in owned_trace)):
        raise ValueError("Exact trace must bind the native transcript and automatic matching editor termination")
    checkpoints = [event for event in trace if event["event"] == "unrelated-preserved" and event["detail"].get("label") == "B"]
    retry_start = next(event["atMilliseconds"] for event in trace if event["event"] == "phase-start" and event["detail"]["label"] == "A cycle 1 dirty edit and installed-command retry")
    retry_done = next(event["atMilliseconds"] for event in trace if event["event"] == "coalesced-corrected-retry-confirmed")
    after_failure = [event for event in checkpoints if attempt["returnedAtMilliseconds"] <= event["atMilliseconds"] < retry_start]
    after_retry = [event for event in checkpoints if corrected["startedAtMilliseconds"] <= event["atMilliseconds"] <= retry_done]
    if (not after_failure or not after_retry
            or max(initial[key] for key in ("terminatedAtMilliseconds", "pidGoneAtMilliseconds", "portReusableAtMilliseconds", "outputRemovedAtMilliseconds")) > attempt["invokedAtMilliseconds"]
            or any(event["detail"]["pid"] != b["pid"] or event["detail"]["sessionId"] != b["sessionId"] for event in checkpoints)):
        raise ValueError("Initial A must be fully stopped before the fault, and B must survive failure and retry checkpoints")
    return {"attempt": attempt, "coalescedRetry": coalesced,
            "bPreservedAfterFailure": after_failure, "bPreservedAfterRetry": after_retry,
            "validatedOutputLogs": build.output_logs(work, (attempt["log"], coalesced["log"])),
            "mechanism": "A deliberately invalid per-file DOTNET_ROLL_FORWARD reaches the real .NET host through the normal installed adapter; healthy initialize precedes a correlated native configurationDone failure.",
            "apiObservation": {"commandResults": command_results, "nativeLaunchResponse": native_launch_responses[0], "nativeStartupSucceeded": False},
            "artifactObservation": "DLL/PDB/runtimeconfig path, size and hashes are captured before normal owned cleanup; only runtimeconfig bytes are retained.",
            "sampling": "Exact editor termination, output/queue cleanup and port reuse are observed. B preservation is sampled at discrete checkpoints. Missing process events do not prove global process absence or a failed-host PID exit."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--compiler-regression", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--failed-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    work = args.run.resolve()
    expected, result = read(work / "expected.json"), read(work / "result.json")
    if expected["scenario"] != "native-host-failure-retry":
        raise ValueError("Expected the explicit real native .NET host startup failure scenario")
    summary = web.summarize_run(work, REPO, require_current_harness=True)
    identity = previous.validate_identity(work, expected, result)
    scenario = validate_native_failure(work, expected, result)
    regression = args.compiler_regression.resolve()
    regression_expected, regression_result = read(regression / "expected.json"), read(regression / "result.json")
    regression_summary = build.summarize_run(regression, True)
    regression_identity = previous.validate_identity(regression, regression_expected, regression_result)
    if regression_result.get("failedNativeHostAttempts") or regression_result["scope"].get("actualNativeHostFailure"):
        raise ValueError("The compiler regression must not enter the new native-host-failure branch")
    value = {"schema": 1, "kind": "installed real .NET host startup failure and corrected same-file retry",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
             "qualification": False, "productChange": False, "primaryRun": summary,
             "primaryIdentity": identity, "nativeHostFailure": scenario,
             "compilerRegression": regression_summary, "compilerRegressionIdentity": regression_identity,
             "verification": validate_units(args.tests.resolve()),
             "unexpectedFailures": [validate_failure(directory.resolve()) for directory in args.failed_runs],
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), PREVIOUS, previous.BUILD_COLLECTOR, build.SHARED)},
             "limits": ["A deliberately invalid per-file DOTNET_ROLL_FORWARD causes a real .NET host startup failure; no native adapter executable failure or injected editor rejection is claimed.",
                        "Command API only; no physical F5/menu or macOS qualification.",
                        "Missing DAP process events do not establish global OS-process absence or independently prove a failed host PID exited.",
                        "B liveness and resource absence are checked at discrete checkpoints.",
                        "No certificate/trust/UI cancellation, active-host-loss, descendant-process or release qualification is added."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
