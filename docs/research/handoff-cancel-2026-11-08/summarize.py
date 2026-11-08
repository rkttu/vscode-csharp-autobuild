"""Validate actual editor progress Cancel during a held native-debug handoff."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE = "2b9b01252f85afd6f554c3d5b149a936845c5a18"
PREVIOUS = REPO / "docs/research/concurrent-files-2026-11-08/summarize.py"
spec = importlib.util.spec_from_file_location("handoff_cancel_previous_summary", PREVIOUS)
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
build, web = prior.build, prior.web
read, binding, same, inside = prior.read, prior.binding, prior.same, prior.inside
snapshot, log_tail, commands = prior.snapshot, prior.log_tail, prior.commands
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}


def validate_identity(work, expected, result, base_commit=BASE):
    candidate = expected["candidate"]
    if (result["expected"] != expected or candidate["sourceCommit"] != base_commit
            or not candidate["localOnly"] or candidate["published"]
            or set(candidate["ownedModules"]) != MODULE_NAMES
            or candidate["target"] != "win32-arm64" or candidate["version"] != "11.7.18004"
            or candidate["baseVsixSha256"] != "0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5"
            or expected["editor"]["version"] != "1.143.17232"
            or expected["editor"]["commit"] != "c072cf642cbbadabefa22f39c58cc902a8b7427f"
            or expected["editor"]["machine"] != "arm64" or result["scope"]["platform"] != "win32-arm64"
            or expected["sdk"]["version"] != "10.0.403" or expected["dependency"]["version"] != "3.2.0"
            or expected["dependency"]["sha256"] != "a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541"
            or result["scope"]["invocation"] != "command-api" or result["scope"]["physicalF5"]
            or result["scope"]["macOS"] or result["scope"]["qualification"]):
        raise ValueError("Expected an unreleased native Windows ARM64 candidate over merged PR42")
    identity = {key: candidate[key] for key in ("baseVsixSha256", "sourceCommit", "target", "ownedModules")}
    if hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != candidate["buildId"]:
        raise ValueError("Content build identity differs")
    for key in ("editor", "sdk"):
        if web.sha256(Path(expected[key]["executable"])) != expected[key]["sha256"]:
            raise ValueError("Pinned native executable differs: " + key)
    if web.sha256(Path(expected["dependency"]["path"])) != expected["dependency"]["sha256"]:
        raise ValueError("Pinned runtime dependency differs")
    if (not same(candidate["path"], work / "local-lifecycle.vsix")
            or web.sha256(Path(candidate["path"])) != candidate["sha256"]
            or result["installedModules"] != candidate["ownedModules"]):
        raise ValueError("Recorded candidate or loaded product identity differs")
    harness = {name.removeprefix("scripts/variant/lifecycle/"): web.sha256(REPO / name) for name in web.HARNESS[:5]}
    if expected["harness"] != harness:
        raise ValueError("Prepared harness differs from current source")
    for name in ("driver.cjs", "extension-test.cjs"):
        if web.sha256(work / "driver" / name) != harness[name]:
            raise ValueError("Executed driver differs from prepared/current source: " + name)
    if web.sha256(work / "workspace/b.cs") != harness["fixtures/web.cs"]:
        raise ValueError("Independent B must preserve the exact ordinary fixture")
    installed = Path(result["installedExtension"]["path"])
    if not inside(work / "extensions", installed):
        raise ValueError("Candidate must be normally installed in this isolated profile")
    modules = REPO / "scripts/variant/file-based-apps"
    with zipfile.ZipFile(candidate["path"]) as archive:
        metadata = json.loads(archive.read("extension/package.json"))["netcoredbgBuild"]
        if metadata["lifecycleBuildId"] != candidate["buildId"] or metadata["lifecycleSourceCommit"] != base_commit:
            raise ValueError("Packaged candidate identity differs")
        for name, value in candidate["ownedModules"].items():
            data = (modules / name).read_bytes()
            original = subprocess.check_output(["git", "show", f"{base_commit}:scripts/variant/file-based-apps/{name}"], cwd=REPO)
            if data.replace(b"\r\n", b"\n") != original.replace(b"\r\n", b"\n"):
                raise ValueError("This verification slice must not change product modules")
            if (hashlib.sha256(data).hexdigest() != value or web.sha256(installed / ".netcoredbg" / name) != value
                    or hashlib.sha256(archive.read("extension/.netcoredbg/" + name)).hexdigest() != value):
                raise ValueError("Current, installed and archived product bytes differ: " + name)
    if any(Path(launch["output"]).exists() for launch in result["launches"]):
        raise ValueError("Every exact captured ordinary output must remain absent after final Stop")
    return {"baseCommit": base_commit, "productModulesUnchanged": True,
            "currentOwnedModules": {name: binding(modules / name) for name in sorted(MODULE_NAMES)}, "completeHarness": harness}


def validate_handoff_cancel(work, expected, result):
    scope = result["scope"]
    if (expected["scenario"] != "native-handoff-cancel" or not scope["actualProgressCancelUi"]
            or not scope["injectedEditorHandoffGate"] or scope["injectedCancellationToken"]
            or any(scope[key] for key in ("actualCompilerFailure", "actualWebProfileFailure", "actualSdkSelectionFailure", "actualNativeHostFailure", "injectedEditorRejection", "nativeAdapterFailure", "actualAdapterProcessKill", "injectedTargetRuntime", "concurrentSeparateFiles"))
            or any(result[key] for key in ("failedBuildAttempts", "failedWebProfileAttempts", "failedSdkSelectionAttempts", "failedHandoffAttempts", "failedNativeHostAttempts", "cancelledBuildAttempts"))
            or len(result["cancelledHandoffAttempts"]) != 1 or result["cleanup"]):
        raise ValueError("Expected one actual UI Cancel with only the test-held editor provider, without injected token or safety cleanup")
    attempt = result["cancelledHandoffAttempts"][0]
    initial = next(launch for launch in result["launches"] if launch["label"] == "A-0")
    b = next(launch for launch in result["launches"] if launch["label"] == "B")
    source, profile = work / "workspace/a.cs", work / "workspace/a.run.json"
    original_source = snapshot(attempt["sourceSnapshot"], source)
    original_profile = json.loads(snapshot(initial["profileSnapshot"], profile))
    cancelled_profile_bytes = snapshot(attempt["profileSnapshot"], profile)
    cancelled_profile = json.loads(cancelled_profile_bytes)
    expected_profile = json.loads(json.dumps(original_profile))
    expected_profile["profiles"]["LifecycleHttp"]["environmentVariables"]["LIFECYCLE_TOKEN"] = attempt["nonce"]
    if (not attempt["expectedHandoffCancellation"] or not same(attempt["source"], source)
            or attempt["revision"] != initial["revision"] or attempt["port"] != initial["port"]
            or attempt["origin"] != initial["origin"] or cancelled_profile != expected_profile
            or original_source != snapshot(initial["sourceSnapshot"], source)
            or original_source != snapshot(attempt["sourceAfterSnapshot"], source)
            or cancelled_profile_bytes != snapshot(attempt["profileAfterSnapshot"], profile)
            or attempt["nonce"] in {launch["nonce"] for launch in result["launches"]}
            or attempt["commandInvocations"] != 3 or attempt["commandResults"] != [False] * 3 or attempt["commandPending"]):
        raise ValueError("Three cancelled callers must retain valid source and only their own fresh normal HTTP profile token")
    output, program, base = Path(attempt["output"]), Path(attempt["program"]), Path(attempt["base"])
    if (not inside(work, output) or not same(program, output / "FileApp.dll")
            or not same(base, output.parent.parent) or not same(base, Path(initial["output"]).parent.parent)
            or same(output, initial["output"]) or same(output, b["output"])
            or not re.fullmatch(r"run-[A-Za-z0-9]{6}", output.name) or len(attempt["providerCalls"]) != 1):
        raise ValueError("The one held provider callback must identify a fresh exact owned output")
    call = attempt["providerCalls"][0]
    config = call["configuration"]
    if (config["type"] != "coreclr" or config["request"] != "launch" or call["providerTokenCancelled"] is not False
            or not same(config["program"], program) or not same(config["__netcoredbgFileAppOutput"], output)
            or not same(config["cwd"], source.parent) or not same(config["env"]["DOTNET_ROOT"], expected["sdk"]["root"])
            or config["env"]["LIFECYCLE_TOKEN"] != attempt["nonce"] or config["env"]["ASPNETCORE_URLS"] != attempt["origin"]
            or config["checkForDevCert"] is not False or "serverReadyAction" in config or len(call["artifacts"]) != 2):
        raise ValueError("The provider must hold the valid generated configuration after a successful real build and HTTP preparation")
    held = attempt["heldAfterForeground"]
    if (not held["providerPending"] or held["gateSettled"] or not held["outputExists"]
            or not held["terminalQueuesEmpty"] or not held["portBindable"]
            or len(held["artifacts"]) != 2 or attempt["providerTokenCancelledAfterForeground"] is not False):
        raise ValueError("After foreground Cancel, the editor-init token must stay distinct and the unresolved held output must be preserved")
    for artifact, retained, name in zip(call["artifacts"], held["artifacts"], ("FileApp.dll", "FileApp.pdb")):
        if (not same(artifact["path"], output / name) or artifact["size"] <= 0
                or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
                or retained != artifact | {"retainedSha256": artifact["sha256"], "retainedSize": artifact["size"]}):
            raise ValueError("Exact DLL/PDB metadata must survive the actual foreground cancellation while held")
    cancelled_tail = prior.history.prior.previous.validate_build(attempt["log"], source, output, False)
    cancelled = [line for line in cancelled_tail.splitlines() if line.startswith("Phase cancelled: Starting netcoredbg")]
    web_prepared = [line for line in cancelled_tail.splitlines() if line.startswith("Phase completed: Preparing web launch settings")]
    if (attempt["log"]["handoffCancelledDiagnostics"] != cancelled or len(cancelled) != 1 or len(web_prepared) != 1
            or "Phase started: Starting netcoredbg" not in cancelled_tail
            or "Phase failed: Starting netcoredbg" in cancelled_tail or "Phase timed out:" in cancelled_tail
            or "The editor did not start the netcoredbg debug session." in cancelled_tail):
        raise ValueError("The exact foreground slice must distinguish actual handoff cancellation from failure, timeout or declined startup")
    ui = validate_ui(work, expected, attempt)
    if (not attempt["gateSettled"] or not attempt["gateReleased"] or attempt["gateMode"] != "valid-original"
            or not attempt["originalObjectReleased"] or attempt["providerPending"] or attempt["providerActive"]
            or not attempt["providerDisposed"] or attempt["providerDisposalCount"] != 1
            or attempt.get("providerDisposalError") or attempt["adapterCreationCount"] != 1 or attempt["editorStartCount"] != 1
            or len(attempt["capturedSessions"]) != 1 or not attempt["terminated"] or attempt["testStopRequested"]
            or not attempt["lateTerminationObservedWithoutTestStop"]):
        raise ValueError("Release the valid original config once, observe one late native session, and dispose the provider once after natural product cancellation cleanup")
    if not (attempt["invokedAtMilliseconds"] <= call["atMilliseconds"] <= attempt["uiRequestedAtMilliseconds"]
            <= attempt["returnedAtMilliseconds"] <= held["atMilliseconds"] <= attempt["gateSettledAtMilliseconds"]
            <= attempt["providerReturnedAtMilliseconds"] <= attempt["startedAtMilliseconds"]
            <= attempt["terminatedAtMilliseconds"] <= attempt["outputRemovedAtMilliseconds"]
            <= attempt["portReusableAtMilliseconds"] <= attempt["providerDisposedAtMilliseconds"]):
        raise ValueError("Held foreground cancellation, valid release, late session and cleanup must preserve their observed chronology")
    captured = attempt["capturedSessions"][0]
    if (captured["sessionId"] != attempt["sessionId"] or not captured["primary"] or not captured["terminated"]
            or not same(captured["program"], program) or not same(captured["output"], output)
            or captured["terminatedAtMilliseconds"] != attempt["terminatedAtMilliseconds"]):
        raise ValueError("Late cleanup must belong to the exact generated configuration and captured editor session")
    if attempt["pidReported"] != bool(attempt.get("pid")):
        raise ValueError("Reported PID classification must match the observed native process identity")
    process_pids = [message.get("body", {}).get("systemProcessId") for message in attempt["dap"] if message.get("event") == "process"
                    and type(message.get("body", {}).get("systemProcessId")) is int and message["body"]["systemProcessId"] > 0]
    if attempt["pidReported"]:
        if (process_pids != [attempt["pid"]] or captured.get("pid") != attempt["pid"]
                or not (attempt["terminatedAtMilliseconds"] <= attempt["reportedPidGoneAtMilliseconds"] <= attempt["outputRemovedAtMilliseconds"])):
            raise ValueError("The exact DAP/captured-session PID requires its independent exit observation before the subsequent output-removal observation")
    elif process_pids or captured.get("pid"):
        raise ValueError("A no-PID classification cannot discard a positive DAP or captured-session PID")
    requests = attempt["dapRequests"]
    initialize = [item for item in requests if item["message"].get("command") == "initialize"]
    launch_requests = [item for item in requests if item["message"].get("command") == "launch"]
    pair = attempt["nativeInitialize"]
    if (len(initialize) != 1 or pair["request"] != initialize[0] or pair["response"] not in attempt["dap"]
            or pair["response"].get("success") is not True or pair["response"].get("command") != "initialize"
            or pair["response"]["request_seq"] != initialize[0]["message"]["seq"]
            or len(launch_requests) > 1 or attempt["launchRequestObserved"] != bool(launch_requests)
            or attempt["nativeLaunchRequest"] != (launch_requests[0] if launch_requests else None)
            or initialize[0]["sessionId"] != attempt["sessionId"]):
        raise ValueError("The released valid configuration must reach correlated real native initialization, with launch presence measured separately")
    if launch_requests:
        native = launch_requests[0]["message"]["arguments"]
        if (launch_requests[0]["sessionId"] != attempt["sessionId"] or not same(native["program"], program)
                or not same(native["__netcoredbgFileAppOutput"], output)
                or native["env"]["LIFECYCLE_TOKEN"] != attempt["nonce"] or native["env"]["ASPNETCORE_URLS"] != attempt["origin"]):
            raise ValueError("Any observed late launch must retain the original provider's output and token")
    stops = [item for item in requests if item["message"].get("command") in ("terminate", "disconnect")]
    if not stops or stops != attempt["nativeStopRequests"] or any(item["atMilliseconds"] < attempt["gateSettledAtMilliseconds"] for item in stops):
        raise ValueError("Retain exact native stop/teardown requests after original-config release")
    full_output = Path(attempt["log"]["path"]).read_bytes().decode("utf-8")
    followup_message = "Retrying cancelled C# session Stop after adapter configuration: " + attempt["sessionId"]
    followup_lines = [line for line in full_output.splitlines() if line == followup_message]
    configuration_done = []
    for request in requests:
        if request["message"].get("command") == "configurationDone":
            configuration_done.extend({"request": request, "response": row} for row in attempt["dapTimeline"]
                                      if row["message"].get("type") == "response" and row["message"].get("command") == "configurationDone"
                                      and row["message"].get("request_seq") == request["message"]["seq"])
    if followup_lines:
        successful = [pair for pair in configuration_done if pair["response"]["message"].get("success") is True]
        if (len(followup_lines) != 1 or len(successful) != 1
                or not any(item["atMilliseconds"] < successful[0]["response"]["atMilliseconds"] for item in stops)
                or not any(item["atMilliseconds"] >= successful[0]["response"]["atMilliseconds"] for item in stops)):
            raise ValueError("A recorded product follow-up Stop must correlate with successful configuration and separate earlier/later native teardown requests")
    if output.exists() or not attempt["outputAbsent"] or not attempt["terminalQueuesEmpty"] or not attempt["portBindable"]:
        raise ValueError("The cancelled late output must remain absent after cleanup")
    for name in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1"):
        queue = base / name
        if queue.exists() and any(queue.iterdir()):
            raise ValueError("Owned terminal queues must remain empty")
    b_identity = {key: b[key] for key in ("sessionId", "pid", "nonce", "output", "response")}
    if attempt["bBefore"] != b_identity or held["b"] != b_identity or attempt["bAfter"] != b_identity:
        raise ValueError("B must preserve its original session/PID/token/HTTP body/output through hold, Cancel and late cleanup")
    retry = result["coalescedRetry"]
    retried = next(launch for launch in result["launches"] if launch["sessionId"] == retry["sessionId"])
    retry_source = snapshot(retry["sourceSnapshot"], source)
    before_revision = f'const string revision = "{initial["revision"]}";'.encode()
    after_revision = f'const string revision = "{retried["revision"]}";'.encode()
    retry_profile = json.loads(snapshot(retry["profileSnapshot"], profile))
    expected_profile["profiles"]["LifecycleHttp"]["environmentVariables"]["LIFECYCLE_TOKEN"] = retried["nonce"]
    if (retry["commandInvocations"] != 3 or retry["commandResults"] != [True] * 3
            or retry["sessionIds"] != [retry["sessionId"]] or not retry["freshOutput"]
            or not retry["providerDisposedBeforeRetry"] or not retry["freshToken"]
            or retry["failedNonce"] != attempt["nonce"] or retry["nonce"] != retried["nonce"]
            or not same(retry["failedOutput"], output) or same(retry["output"], output) or same(retry["output"], initial["output"])
            or retried["nonce"] in (attempt["nonce"], initial["nonce"])
            or original_source.count(before_revision) != 1 or original_source.replace(before_revision, after_revision, 1) != retry_source
            or retry_profile != expected_profile or retry["sourceSnapshot"] != retried["sourceSnapshot"]
            or retry["profileSnapshot"] != retried["profileSnapshot"]
            or attempt["providerDisposedAtMilliseconds"] > retried["startedAtMilliseconds"]):
        raise ValueError("After provider disposal, three dirty retry callers must share one saved revision, fresh session/output/token and ordinary profile")
    retry_tail = prior.history.prior.previous.validate_build(retry["log"], source, retry["output"], True)
    if "Phase cancelled: Starting netcoredbg" in retry_tail or "Phase failed: Starting netcoredbg" in retry_tail:
        raise ValueError("Corrected retry cannot inherit cancellation or startup failure in its exact log slice")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    owned = [event for event in trace if event.get("detail", {}).get("label") == attempt["label"]]
    sent = [{"sessionId": event["detail"]["sessionId"], "message": event["detail"]["message"], "atMilliseconds": event["atMilliseconds"]}
            for event in owned if event["event"] == "dap-send"]
    received = [event["detail"]["message"] for event in owned if event["event"] == "dap-receive"]
    received_timeline = [{"sessionId": event["detail"]["sessionId"], "message": event["detail"]["message"], "atMilliseconds": event["atMilliseconds"]}
                         for event in owned if event["event"] == "dap-receive"]
    # Tracker records its timestamp immediately before record() takes the trace
    # timestamp, so compare message/session identity and event ordering exactly;
    # raw trace and per-message monotonic times remain retained separately.
    identities = lambda rows: [{"sessionId": row["sessionId"], "message": row["message"]} for row in rows]
    if (identities(sent) != identities(requests) or received != attempt["dap"]
            or identities(received_timeline) != identities(attempt["dapTimeline"])
            or any(event["event"] == "stop-request" for event in owned)):
        raise ValueError("Exact native transcript must bind the late session, while the control issues no Stop for that attempt")
    terms = [event for event in owned if event["event"] == "editor-terminate"]
    starts = [event for event in owned if event["event"] == "editor-start"]
    exits = [event["detail"] for event in owned if event["event"] == "adapter-exit"]
    if (len(terms) != 1 or terms[0]["detail"]["sessionId"] != attempt["sessionId"] or len(starts) != 1
            or starts[0]["detail"]["sessionId"] != attempt["sessionId"]
            or exits != attempt["adapterExits"] or len(exits) != 1 or exits[0]["sessionId"] != attempt["sessionId"]):
        raise ValueError("Late adapter exit and matching editor termination must remain distinct captured observations")
    editor_config = starts[0]["detail"]["configuration"]
    if (not same(editor_config["program"], program) or not same(editor_config["__netcoredbgFileAppOutput"], output)
            or editor_config["env"]["LIFECYCLE_TOKEN"] != attempt["nonce"] or editor_config["env"]["ASPNETCORE_URLS"] != attempt["origin"]):
        raise ValueError("The exact late editor-start configuration must retain the held original program/output/token")
    provider_held = [event["detail"] for event in trace if event["event"] == "handoff-provider-held"]
    foreground = [event["detail"] for event in trace if event["event"] == "handoff-cancelled-foreground-output-retained"]
    gate_events = [event["detail"] for event in trace if event["event"] == "handoff-gate-settled"]
    provider_returned = [event["detail"] for event in trace if event["event"] == "handoff-provider-returned"]
    disposed = [event["detail"] for event in trace if event["event"] == "handoff-gate-provider-disposed"]
    if (provider_held != [{"label": attempt["label"], "nonce": attempt["nonce"], "call": call}] or foreground != [held]
            or gate_events != [{"label": attempt["label"], "mode": "valid-original", "originalObjectReleased": True}]
            or len(provider_returned) != 1 or provider_returned[0]["label"] != attempt["label"]
            or provider_returned[0]["gateMode"] != "valid-original" or not provider_returned[0]["originalObjectReturned"]
            or provider_returned[0]["providerTokenCancelled"] is not False
            or disposed != [{"label": attempt["label"], "count": 1}]
            or [event["detail"] for event in trace if event["event"] == "handoff-provider-token-cancelled"] != attempt["providerTokenEvents"]):
        raise ValueError("Provider hold, foreground retention, original-object release/return and disposal must be independently trace-bound")
    b_after_retry = [event for event in trace if event["event"] == "unrelated-preserved" and event["detail"] == {"label": "B", "sessionId": b["sessionId"], "pid": b["pid"]}
                     and retried["startedAtMilliseconds"] <= event["atMilliseconds"] < retried["stopRequestedAtMilliseconds"]]
    if not b_after_retry:
        raise ValueError("B needs an exact independent checkpoint after successful retry")
    return {"attempt": attempt, "coalescedRetry": retry, "ui": ui, "bPreservedAfterRetry": b_after_retry,
            "validatedOutputLogs": build.output_logs(work, (attempt["log"], retry["log"])),
            "mechanism": "An exact-token test provider holds the actual valid editor handoff after a real build; an actual progress Cancel releases foreground callers while the original configuration remains held, then real native initialization/teardown is observed after release.",
            "stopAttribution": "The control records no Stop or fallback for this attempt. Native terminate/disconnect requests are protocol observations; DAP alone does not identify the API caller. Product cancellation ownership is assessed with unchanged runtime source and this controlled trace.",
            "nativeOutcome": {"nativeInitializeSucceeded": True, "nativeLaunchRequestObserved": bool(launch_requests), "debuggeePidReported": attempt["pidReported"]},
            "productFollowupStopObservation": {"diagnostics": followup_lines, "configurationDone": configuration_done,
                                               "interpretation": "The exact-session product diagnostic and correlated readiness/native requests support the serialized follow-up Stop path when observed; DAP requests alone do not identify their API caller."},
            "pidObservation": "A reported native process PID requires a separate exit observation; missing DAP process events never establish OS-process absence.",
            "limits": "Provider-induced timing and discrete resource/B samples; retry follows late termination/cleanup and provider disposal. No unconstrained latency, pending-late-handoff overlap retry, physical F5 or cross-platform qualification."}


def validate_ui(work, expected, attempt):
    configured = expected["handoffCancellation"]
    if (not same(configured["request"], work / "needs-ui-cancel.json")
            or not same(configured["receipt"], work / "ui-cancel-action.json")
            or configured["windowTitle"] != "FBA handoff cancellation " + configured["nonce"]
            or read(work / "profile/User/settings.json")["window.title"] != configured["windowTitle"]
            or read(work / "launcher-result.json")["visibleWindowRequested"] is not True):
        raise ValueError("Actual UI cancellation needs this isolated visible editor and its unique prepared title")
    request_bytes = snapshot(attempt["uiRequestSnapshot"], Path(configured["request"]))
    receipt_bytes = snapshot(attempt["uiActionSnapshot"], Path(configured["receipt"]))
    if Path(configured["request"]).read_bytes() != request_bytes or Path(configured["receipt"]).read_bytes() != receipt_bytes:
        raise ValueError("The exact original UI request and action receipt must remain intact")
    request, receipt = json.loads(request_bytes), json.loads(receipt_bytes)
    if request != {"schema": 1, "nonce": configured["nonce"], "token": attempt["nonce"],
                   "windowTitle": configured["windowTitle"], "phase": "Starting netcoredbg", "stage": "provider-held",
                   "source": attempt["source"], "program": attempt["program"], "output": attempt["output"], "providerCallCount": 1}:
        raise ValueError("Actual UI request must bind the exact provider token, generated configuration and held phase")
    required = {"schema": 1, "nonce": configured["nonce"], "token": attempt["nonce"],
                "phase": "Starting netcoredbg", "stage": "provider-held", "automation": "@oai/sky", "method": "click",
                "control": "progress Cancel", "notificationTitle": "Debug C# file", "message": "Starting netcoredbg",
                "expectedWindowTitle": configured["windowTitle"]}
    if receipt != attempt["uiAction"] or any(receipt.get(key) != value for key, value in required.items()):
        raise ValueError("Action receipt must attest to this exact actual progress Cancel, rather than debugger-init cancellation")
    window = receipt["window"]
    if (configured["windowTitle"] not in window["title"] or window["id"] is None
            or not window["app"].startswith("process:") or not same(window["app"][len("process:"):], expected["editor"]["executable"])):
        raise ValueError("Tool-returned application/window identity must match the isolated editor's path and unique title")
    observations, image_files = [], {}
    for index, name in enumerate(("before", "after")):
        file = Path(receipt[name + "ObservationFile"])
        if not same(file, work / "ui" / (name + ".json")) or not inside(work, file):
            raise ValueError("UI observation must remain an exact file in this isolated profile")
        observation = read(file)
        metadata = attempt["uiObservations"][index]
        if (not same(metadata["path"], file) or metadata["size"] != file.stat().st_size or metadata["sha256"] != web.sha256(file)
                or receipt[name + "ObservationSha256"] != web.sha256(file)
                or any(observation.get(key) != required[key] for key in ("schema", "nonce", "token", "phase", "stage"))
                or observation["window"] != window or not observation["screenshots"]):
            raise ValueError("UI observations must match receipt hashes, gate identity and returned window")
        for screenshot in observation["screenshots"]:
            image_file = Path(screenshot["path"])
            if (not inside(work / "ui", image_file) or not screenshot["id"]
                    or type(screenshot["width"]) is not int or screenshot["width"] <= 0
                    or type(screenshot["height"]) is not int or screenshot["height"] <= 0
                    or screenshot["bytes"] != image_file.stat().st_size or screenshot["sha256"] != web.sha256(image_file)
                    or screenshot["mimeType"] not in ("image/jpeg", "image/png")):
                raise ValueError("Retained screenshot metadata must bind its original encoded image without visual reinspection")
            image_files[image_file.relative_to(work).as_posix()] = binding(image_file)
        observations.append(observation)
    utc = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not (utc(observations[0]["atUtc"]) <= utc(receipt["actionStartedUtc"]) <= utc(receipt["actionCompletedUtc"]) <= utc(observations[1]["atUtc"])):
        raise ValueError("UI before/click/after wall-clock chronology must remain separate and ordered")
    index = receipt["target"].get("element_index")
    tree = observations[0]["accessibility"]["tree"]
    lines = tree.splitlines()
    selected = [(position, line) for position, line in enumerate(lines) if re.match(rf"^\s*{re.escape(str(index))}\s+.*\bCancel\b", line)]
    if type(index) is not int or len(selected) != 1:
        raise ValueError("The saved pre-click accessibility tree must identify the exact selected Cancel element")
    position, selected_row = selected[0]
    list_parents = [(offset, len(line) - len(line.lstrip())) for offset, line in enumerate(lines[:position]) if " LIST " in line]
    if not list_parents:
        raise ValueError("Selected Cancel must belong to a saved notification container")
    start, indentation = list_parents[-1]
    end = next((offset for offset in range(position + 1, len(lines)) if lines[offset].strip()
                and len(lines[offset]) - len(lines[offset].lstrip()) <= indentation), len(lines))
    context = "\n".join(lines[start:end])
    if "Debug C# file: Starting netcoredbg" not in context:
        raise ValueError("The selected Cancel must share its notification container with the actual handoff phase")
    return {"request": request, "receipt": receipt,
            "beforeObservation": {"path": receipt["beforeObservationFile"], **binding(Path(receipt["beforeObservationFile"])),
                                  "atUtc": observations[0]["atUtc"], "window": window, "screenshots": observations[0]["screenshots"],
                                  "selectedCancelRow": selected_row, "notificationContext": context},
            "afterObservation": {"path": receipt["afterObservationFile"], **binding(Path(receipt["afterObservationFile"])),
                                 "atUtc": observations[1]["atUtc"], "window": window, "screenshots": observations[1]["screenshots"],
                                 "cachedCancelTextStillPresent": bool(re.search(rf"(?m)^\s*{index}\s+.*\bCancel\b", observations[1]["accessibility"]["tree"]))},
            "rawEvidence": ui_raw_files(work) | image_files,
            "interpretation": "The action receipt is a tool/operator attestation linked to returned window identity, exact pre-click Cancel element and saved observations. Images are bound by encoded-byte hash only, without reopening. An immediate post-click accessibility tree may be stale; absence of cached text is not required. Returned window metadata supplies no process PID."}


def validate_failure(work):
    result, launcher = read(work / "result.json"), read(work / "launcher-result.json")
    if result["success"] or not result.get("firstFailure") or launcher["success"]:
        raise ValueError("An unexpected failed attempt must retain its original failure")
    raw = web.raw_files(work)
    raw.update(build.output_logs(work))
    raw.update(ui_raw_files(work))
    return {"directory": str(work), "result": result, "launcher": launcher, "rawEvidence": raw,
            "interpretation": "Separate unexpected attempt; not passing actual UI handoff-cancellation coverage."}


def ui_raw_files(work):
    files = [work / name for name in ("needs-ui-cancel.json", "ui-cancel-action.json")]
    files.extend(sorted((work / "ui").glob("*.json")))
    return {file.relative_to(work).as_posix(): binding(file) for file in files if file.is_file()}


def language_service_fixture(work, attempt):
    logs = list((work / "profile/logs").glob("**/C#.log"))
    if len(logs) != 1:
        raise ValueError("Expected one unambiguous retained C# language-service log")
    file = logs[0]
    lines = file.read_text(encoding="utf-8-sig").splitlines()
    samples = {}
    for source in ("a.cs", "b.cs"):
        rows = [{"line": index + 1, "text": line} for index, line in enumerate(lines)
                if source + ".csproj" in line and "error NU1100:" in line
                and ("Microsoft.DotNet.ILCompiler" in line or "Microsoft.NET.ILLink.Tasks" in line)]
        if not rows:
            raise ValueError("Retain the separate language-service project-load errors visible in the UI observations")
        samples[source] = rows[:2]
    configurations = {}
    for relative in ("workspace/NuGet.Config", "appdata/NuGet/NuGet.Config"):
        config = work / relative
        if config.read_text(encoding="utf-8").strip() != "<configuration><packageSources><clear /></packageSources></configuration>":
            raise ValueError("Offline-fixture explanation requires the exact prepared cleared package sources")
        configurations[relative] = binding(config)
    debug_args = attempt["log"]["buildCommands"][0]["args"]
    if "-p:PublishAot=false" not in debug_args or len(attempt["log"]["buildCompletedPhaseDiagnostics"]) != 1:
        raise ValueError("The successful owned debug build must retain its separate PublishAot=false setting")
    return {"log": {"path": str(file), **binding(file), "lines": len(lines)}, "samples": samples,
            "offlineNugetConfigurations": configurations, "ownedDebugBuildArgs": debug_args,
            "interpretation": "Observed: this isolated fixture clears package sources; the language service separately restores a.cs/b.cs and reports unresolved AOT/linker/runtime packages, while the owned debug build sets PublishAot=false and succeeds. Inference: those project-load notifications are consistent with the offline fixture and differing restore settings, not evidence here of handoff/adapter failure. This control does not qualify language-service readiness or error-free UI/logs."}


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
    summary = web.summarize_run(work, REPO, require_current_harness=True)
    identity = validate_identity(work, expected, result)
    cancellation = validate_handoff_cancel(work, expected, result)
    fixture_context = language_service_fixture(work, result["cancelledHandoffAttempts"][0])
    summary["rawEvidence"].update(ui_raw_files(work))
    regression = args.compiler_regression.resolve()
    regression_expected, regression_result = read(regression / "expected.json"), read(regression / "result.json")
    regression_summary = build.summarize_run(regression, True)
    regression_identity = validate_identity(regression, regression_expected, regression_result)
    if regression_result.get("cancelledHandoffAttempts") or regression_result["scope"]["injectedEditorHandoffGate"] or regression_result["scope"]["actualProgressCancelUi"]:
        raise ValueError("The compiler regression must not enter the held-provider/UI cancellation branch")
    value = {"schema": 1, "kind": "installed actual UI progress cancellation during held debugger handoff and late native cleanup",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18", "qualification": False, "productChange": False,
             "primaryRun": summary, "primaryIdentity": identity, "handoffCancellation": cancellation,
             "languageServiceFixture": fixture_context,
             "compilerRegression": regression_summary, "compilerRegressionIdentity": regression_identity,
             "verification": prior.validate_units(args.tests.resolve(), base_commit=BASE),
             "unexpectedFailures": [validate_failure(directory.resolve()) for directory in args.failed_runs],
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), PREVIOUS, prior.PREVIOUS, prior.history.PREVIOUS, prior.history.prior.PREVIOUS, prior.history.prior.previous.BUILD_COLLECTOR, build.SHARED)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
