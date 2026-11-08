"""Validate retained installed native adapter-process loss and same-file retry."""
import argparse
import copy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path, PureWindowsPath
import re
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE = "2ef05e2d2c872774f8b6a54da0e107ada0b6cd91"
PREVIOUS = REPO / "docs/research/native-host-failure-2026-11-07/summarize.py"
spec = importlib.util.spec_from_file_location("adapter_loss_previous_summary", PREVIOUS)
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
prior.previous.BASE = BASE
build, web = prior.build, prior.web
read, binding, same, inside = prior.read, prior.binding, prior.same, prior.inside
snapshot, log_tail, commands = prior.snapshot, prior.log_tail, prior.commands


def validate_identity(work, expected, result):
    if result["expected"] != expected:
        raise ValueError("Result must retain its exact prepared expectation")
    core_harness = {name.removeprefix("scripts/variant/lifecycle/"): web.sha256(REPO / name) for name in web.HARNESS[:5]}
    harness = dict(core_harness)
    if expected["scenario"] == "native-adapter-loss":
        helper = REPO / "scripts/variant/lifecycle/adapter-loss.ps1"
        harness["adapter-loss.ps1"] = web.sha256(helper)
        if (not same(expected["adapterLoss"]["helper"], work / "driver/adapter-loss.ps1")
                or web.sha256(Path(expected["adapterLoss"]["helper"])) != harness["adapter-loss.ps1"]):
            raise ValueError("Executed process-loss helper differs from the current prepared source")
    if expected["harness"] != harness:
        raise ValueError("Complete prepared harness differs from current source")
    # The older product identity validator knows the original five harness
    # files. Validate the added helper above, then delegate using copies of
    # that explicit projection; raw expectation/result objects stay intact.
    core_expected = copy.deepcopy(expected)
    core_expected["harness"] = core_harness
    core_result = dict(result, expected=core_expected)
    return prior.previous.validate_identity(work, core_expected, core_result) | {"completeHarness": harness}


def validate_units(directory):
    metadata = read(directory / "source-manifest.json")
    if (metadata["commit"] != BASE or len(metadata["runs"]) != 2 or not same(metadata["worktree"], REPO)):
        raise ValueError("Expected this exact merged base and separate Node/Python attempts")
    sources = {item["path"]: item for item in metadata["source"]}
    tracked = set(subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "scripts/variant"], cwd=REPO, text=True).splitlines())
    if set(sources) != tracked or len(sources) != len(metadata["source"]):
        raise ValueError("Manifest must archive every tracked or new unignored scripts/variant source exactly once")
    for name, item in sources.items():
        file, historical = REPO / name, directory / "source" / name
        if (not inside(REPO / "scripts/variant", file) or web.sha256(file) != item["sha256"]
                or file.stat().st_size != item["size"] or file.read_bytes() != historical.read_bytes()):
            raise ValueError("Current or retained source differs from its pre-run bytes: " + name)
    for name in ("node", "python"):
        if web.sha256(Path(metadata[name]["path"])) != metadata[name]["sha256"]:
            raise ValueError("Pinned verification runtime differs: " + name)
    tests = [f"scripts/variant/file-based-apps/test-{name}.cjs" for name in ("classify", "entry", "recovery", "runtime", "web")]
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
            raise ValueError("Recorded argv, raw result, log or source-freeze timestamps differ")
        text = log.read_text(encoding="utf-8-sig")
        if record["log"] == "node.log":
            counts = {key: int(value) for key, value in re.findall(r"(?m)^(?:#|ℹ) (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$", text)}
            if counts != {"tests": 228, "pass": 228, "fail": 0, "cancelled": 0, "skipped": 0, "todo": 0}:
                raise ValueError("Expected the complete 228-case strict natural-exit Node suite")
        else:
            if re.findall(r"Ran (\d+) tests? in", text) != ["39"] or not re.search(r"(?m)^OK\s*$", text):
                raise ValueError("Expected all 39 Python helper cases")
            counts = {"tests": 39, "result": "OK"}
        rows.append({"record": record, "counts": counts, "rawLog": binding(log), "rawResult": binding(result_file)})
    return {"directory": str(directory), "manifest": metadata, "sourceCount": len(sources),
            "manifestFile": binding(directory / "source-manifest.json"), "runs": rows,
            "sourceObservation": "All tracked and new unignored scripts/variant pre-run source bytes and hashes are retained; current bytes and historical copies are checked against every entry."}


def summarize_primary(work, expected, result):
    launcher = read(work / "launcher-result.json")
    if (not result["success"] or result.get("firstFailure") or result.get("observedProductGap")
            or not launcher["success"] or launcher["editorExitCode"] != 0
            or launcher["candidateSha256"] != expected["candidate"]["sha256"]):
        raise ValueError("A failed observational attempt cannot be relabelled as passing adapter-loss coverage")
    ordinary = [launch for launch in result["launches"] if "stopRequestedAtMilliseconds" in launch]
    initial = [launch for launch in result["launches"] if "stopRequestedAtMilliseconds" not in launch]
    if (len(initial) != 1 or initial[0]["label"] != "A-0"
            or len(ordinary) != expected["cycles"] + 1
            or len(result["launches"]) != expected["cycles"] + 2):
        raise ValueError("Distinguish the faulted initial A from three later ordinary A Stop cycles and B")
    launches = []
    for launch in ordinary:
        stopped = launch["stopRequestedAtMilliseconds"]
        timings = {label: round(launch[key] - stopped, 3) for label, key in (
            ("stopPromise", "stopPromiseResolvedAtMilliseconds"),
            ("matchingEditorTermination", "terminatedAtMilliseconds"),
            ("pidObservedGone", "pidGoneAtMilliseconds"),
            ("portRebindSucceeded", "portReusableAtMilliseconds"),
            ("outputAndQueuesClear", "outputRemovedAtMilliseconds"))}
        if any(delta < 0 for delta in timings.values()):
            raise ValueError("Ordinary lifecycle observations cannot predate their exact Stop")
        launches.append({key: launch[key] for key in ("label", "revision", "pid", "sessionId", "origin", "output", "response")} |
                        {"afterStopMilliseconds": timings})
    raw = web.raw_files(work)
    for file in (Path(expected["adapterLoss"]["marker"]), Path(expected["adapterLoss"]["receipt"]), Path(expected["adapterLoss"]["helper"])):
        raw[file.relative_to(work).as_posix()] = binding(file)
    raw.update(build.output_logs(work))
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    diagnostics = []
    fault_time = result["adapterLoss"]["aAdapterExits"][0]["atMilliseconds"]
    for event in trace:
        detail = event.get("detail", {})
        message = detail.get("message", {})
        if event["event"] == "adapter-error" or (event["event"] == "dap-receive" and message.get("success") is False):
            owner = next((launch for launch in result["launches"] if launch["label"] == detail.get("label")), None)
            stopped = owner.get("stopRequestedAtMilliseconds") if owner else None
            diagnostics.append(event | {"afterStopMilliseconds": round(event["atMilliseconds"] - stopped, 3) if stopped is not None else None,
                                        "afterAdapterLossMilliseconds": round(event["atMilliseconds"] - fault_time, 3) if owner and owner["label"] == "A-0" else None})
    runtime_modules = sorted({event["detail"]["message"]["body"]["module"].get("path", "") for event in trace
                              if event["event"] == "dap-receive" and event.get("detail", {}).get("message", {}).get("event") == "module"
                              and "Microsoft.NETCore.App" in event["detail"]["message"]["body"]["module"].get("path", "")})
    core_libraries = [file for file in runtime_modules if file.endswith("System.Private.CoreLib.dll")]
    if not core_libraries or any(PureWindowsPath(file).parent.name != "10.0.14" for file in core_libraries):
        raise ValueError("The source rationale must match the actual 10.0.14 core-library paths observed through native DAP")
    return {"name": work.name, "localArtifactDirectory": str(work), "success": True,
            "editorExitCode": launcher["editorExitCode"], "scope": result["scope"],
            "freshProfiles": 1, "initialFaultedALaunches": 1, "laterALaunchesAndStopCycles": expected["cycles"], "bLaunches": 1,
            "candidate": expected["candidate"], "editor": expected["editor"] | {"apiVersion": result["editorApiVersion"]},
            "sdk": expected["sdk"], "dependency": expected["dependency"],
            "installedExtension": result["installedExtension"], "installedDependency": result["installedDependency"],
            "installedOwnedModules": result["installedModules"], "harnessPinnedBeforeLaunch": expected["harness"],
            "checks": result["checks"], "phases": result["phases"], "elapsedMilliseconds": result["elapsedMilliseconds"],
            "initialFaultedA": initial[0], "ordinaryStopLaunches": launches,
            "adapterAndStopDiagnostics": diagnostics,
            "observedCoreRuntimeDirectories": sorted({str(PureWindowsPath(file).parent) for file in runtime_modules}),
            "observedCoreLibraryModulePaths": core_libraries,
            "successfulCommandControls": [{key: launch[key] for key in ("label", "commandInvocations", "commandResults", "capturedSessions")} for launch in result["launches"]],
            "rawEvidence": raw,
            "interpretation": "Deliberate exact adapter-process loss is distinct from ordinary Stop. Resource observations and later retry/Stop assertions passed; this is not a release-qualification claim."}


def validate_adapter_loss(work, expected, result):
    scope = result["scope"]
    if (not scope["nativeAdapterFailure"] or not scope["actualAdapterProcessKill"]
            or scope["injectedEditorRejection"] or scope["injectedTargetRuntime"]
            or any(scope[key] for key in ("actualCompilerFailure", "actualWebProfileFailure", "actualSdkSelectionFailure", "actualNativeHostFailure"))
            or any(result[key] for key in ("failedBuildAttempts", "failedWebProfileAttempts", "failedSdkSelectionAttempts", "failedHandoffAttempts", "failedNativeHostAttempts", "cancelledBuildAttempts"))
            or result["cleanup"] or result.get("observedProductGap")):
        raise ValueError("Passing coverage requires the actual adapter fault and natural resource settlement, without fallback cleanup or another injected fault")
    loss, configured = result["adapterLoss"], expected["adapterLoss"]
    initial = next(launch for launch in result["launches"] if launch["label"] == "A-0")
    b = next(launch for launch in result["launches"] if launch["label"] == "B")
    if loss["nonce"] != configured["nonce"] or loss["observationOnly"] or loss.get("settlementWaitError"):
        raise ValueError("Expected the completed exact fault followed by successful retry")
    before = loss["before"]
    fixture_keys = ("sessionId", "pid", "nonce", "source", "program", "output", "port", "response")
    for key, launch in (("a", initial), ("b", b)):
        if before[key] != {name: launch[name] for name in fixture_keys}:
            raise ValueError("Pre-fault fixture identity differs from its exact captured launch")
    marker_bytes = snapshot(loss["markerSnapshot"], Path(configured["marker"]))
    receipt_bytes = snapshot(loss["receiptSnapshot"], Path(configured["receipt"]))
    if marker_bytes != Path(configured["marker"]).read_bytes() or receipt_bytes != Path(configured["receipt"]).read_bytes():
        raise ValueError("Preserved fault marker/receipt must retain their exact historical bytes")
    marker, receipt = json.loads(marker_bytes), json.loads(receipt_bytes)
    if (receipt != loss["receipt"] or marker["schema"] != 1 or receipt["schema"] != 1
            or marker["nonce"] != configured["nonce"] or receipt["nonce"] != configured["nonce"]
            or not same(marker["root"], work) or not same(receipt["root"], work)
            or marker["a"] != before["a"] or marker["b"] != before["b"]
            or receipt["markerSha256"] != loss["markerSnapshot"]["sha256"]
            or receipt["helperSha256"] != expected["harness"]["adapter-loss.ps1"]
            or not receipt["success"] or not receipt["killRequested"] or not receipt["killedOnlyAdapter"]):
        raise ValueError("Fault receipt must bind the fresh marker, exact helper and one successful adapter-only Kill")
    launcher = read(work / "launch.json")
    if launcher["pid"] != marker["editorPid"] or not same(launcher["work"], work):
        raise ValueError("Fault marker must identify this exact isolated editor launch")
    adapter = Path(result["installedExtension"]["path"]) / configured["adapterRelativePath"]
    if (configured["adapterRelativePath"] != ".debugger/netcoredbg/netcoredbg.exe"
            or not same(marker["adapter"]["path"], adapter)
            or marker["adapter"]["sha256"] != configured["adapterSha256"]
            or web.sha256(adapter) != configured["adapterSha256"]):
        raise ValueError("Killed adapter must be the exact normally installed native executable")
    with zipfile.ZipFile(expected["candidate"]["path"]) as archive:
        if hashlib.sha256(archive.read("extension/" + configured["adapterRelativePath"])).hexdigest() != configured["adapterSha256"]:
            raise ValueError("Installed native executable differs from its prepared candidate archive")
    identities = receipt["identities"]
    a_process, b_process = identities["aDebuggee"], identities["bDebuggee"]
    a_adapter, b_adapter = identities["aAdapter"], identities["bAdapter"]
    process_keys = {"processId", "parentProcessId", "creationUtc", "executablePath", "commandLine"}
    for item in (a_process, b_process, a_adapter, b_adapter, *identities["editorAncestry"]):
        if (set(item) != process_keys or type(item["processId"]) is not int or item["processId"] <= 0
                or type(item["parentProcessId"]) is not int or item["parentProcessId"] <= 0):
            raise ValueError("Process proof must retain its full positive PID/parent/creation/path/command identity")
    if (len({item["processId"] for item in (a_process, b_process, a_adapter, b_adapter)}) != 4
            or receipt["killedProcessId"] != a_adapter["processId"]
            or a_process["processId"] != initial["pid"] or b_process["processId"] != b["pid"]
            or a_process["parentProcessId"] != a_adapter["processId"]
            or b_process["parentProcessId"] != b_adapter["processId"]):
        raise ValueError("Kill must target A's verified adapter parent, distinct from both debuggees and B's adapter")
    utc = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))
    for process, launch, native in ((a_process, initial, a_adapter), (b_process, b, b_adapter)):
        if (not same(process["executablePath"], expected["sdk"]["executable"])
                or launch["program"].replace("/", "\\").casefold() not in process["commandLine"].replace("/", "\\").casefold()
                or not same(native["executablePath"], adapter)
                or not re.search(r"(?:^|\s)--interpreter=vscode(?:\s|$)", native["commandLine"])
                or native["parentProcessId"] != marker["extensionHostPid"]
                or utc(native["creationUtc"]) > utc(process["creationUtc"])):
            raise ValueError("Both debuggee-parent adapters must match executable, arguments, host lineage and creation order")
    ancestry = identities["editorAncestry"]
    if (not 1 <= len(ancestry) <= 8 or len({item["processId"] for item in ancestry}) != len(ancestry)
            or ancestry[0]["processId"] != marker["extensionHostPid"] or ancestry[-1]["processId"] != marker["editorPid"]
            or str(work).casefold() not in ancestry[-1]["commandLine"].casefold()
            or any(not same(item["executablePath"], expected["editor"]["executable"]) for item in ancestry)):
        raise ValueError("Adapter ancestry must reach this exact isolated editor through verified editor processes")
    for child, parent in zip([a_adapter, *ancestry[:-1]], ancestry):
        if child["parentProcessId"] != parent["processId"] or utc(parent["creationUtc"]) > utc(child["creationUtc"]):
            raise ValueError("Each editor-ancestry parent must precede its exact child")
    rechecked = receipt["rechecked"]
    if (any(rechecked[key] != identities[key] for key in ("aDebuggee", "bDebuggee", "aAdapter", "bAdapter"))
            or rechecked["extensionHost"] != ancestry[0] or rechecked["editor"] != ancestry[-1]
            or receipt["recheckedAncestry"] != ancestry
            or abs((utc(receipt["heldHandleStartUtc"]) - utc(a_adapter["creationUtc"])).total_seconds()) > 0.000001
            or not (utc(receipt["startedUtc"]) <= utc(receipt["killRequestedUtc"]) <= utc(receipt["adapterExitObservedUtc"]) <= utc(receipt["finishedUtc"]))):
        raise ValueError("Final CIM rechecks and retained OS process-handle creation identity must precede the one Kill")
    for key, launch in (("a", initial), ("b", b)):
        if receipt[key + "Before"] != launch["response"] or receipt[key + "ImmediatelyBeforeKill"] != launch["response"]:
            raise ValueError("Nonce/PID/revision HTTP ownership must be verified twice before the adapter fault")
    a_source = snapshot(before["aSource"], Path(initial["source"]))
    b_source = snapshot(before["bSource"], Path(b["source"]))
    a_profile = json.loads(snapshot(before["aProfile"], Path(initial["source"]).with_suffix(".run.json")))
    b_profile = json.loads(snapshot(before["bProfile"], Path(b["source"]).with_suffix(".run.json")))
    fixture = (REPO / "scripts/variant/lifecycle/fixtures/web.cs").read_bytes()
    if a_source != fixture or b_source != fixture or not loss["sourceAndProfilesUnchanged"]:
        raise ValueError("Adapter loss must preserve valid original source and ordinary per-file profiles")
    for profile, launch in ((a_profile, initial), (b_profile, b)):
        if profile != {"profiles": {"LifecycleHttp": {"commandName": "Project", "applicationUrl": launch["origin"], "launchBrowser": False,
                       "environmentVariables": {"LIFECYCLE_TOKEN": launch["nonce"], "ASPNETCORE_ENVIRONMENT": "Development"}}}}:
            raise ValueError("Only the explicit owned HTTP profiles may be used")
    before_dap, before_requests = before["aDap"], before["aRequests"]
    after_dap, after_requests = loss["aDapAfterFault"], loss["aRequestsAfterFault"]
    if (after_dap[:len(before_dap)] != before_dap or after_requests[:len(before_requests)] != before_requests
            or any(item["message"]["command"] in ("terminate", "disconnect") for item in before_requests)):
        raise ValueError("Initial successful native transcript must remain a prefix of the fault transcript, without a prior Stop")
    launch_requests = [item for item in before_requests if item["message"]["command"] == "launch"]
    configuration_requests = [item for item in before_requests if item["message"]["command"] == "configurationDone"]
    if len(launch_requests) != 1 or len(configuration_requests) != 1:
        raise ValueError("Initial A must have exactly one native launch and configuration request")
    arguments = launch_requests[0]["message"]["arguments"]
    if (launch_requests[0]["sessionId"] != initial["sessionId"] or not same(arguments["program"], initial["program"])
            or not same(arguments["__netcoredbgFileAppOutput"], initial["output"])
            or arguments["env"]["LIFECYCLE_TOKEN"] != initial["nonce"]
            or arguments["env"]["ASPNETCORE_URLS"] != initial["origin"]
            or not any(message.get("command") == "configurationDone" and message.get("request_seq") == configuration_requests[0]["message"]["seq"]
                       and message.get("success") is True for message in before_dap)
            or not any(message.get("event") == "process" and message.get("body", {}).get("systemProcessId") == initial["pid"] for message in before_dap)):
        raise ValueError("The actual adapter must have configured the exact healthy A debuggee before the fault")
    observations = loss["observations"]
    if [item["label"] for item in observations] != ["receipt", "after-250ms", "after-1000ms", "settlement"]:
        raise ValueError("Retain every distinct post-fault resource observation")
    for item in observations:
        for key in ("sessionId", "pid", "nonce", "source", "program", "output", "port", "response"):
            if item["b"][key] != before["b"][key]:
                raise ValueError("B must retain its exact session/PID/token/program/output/HTTP ownership at every observation")
        if not item["b"]["outputExists"] or not item["b"]["programExists"]:
            raise ValueError("B's live output must remain present")
        if item.get("aOwnedHttpResponse") is not None and item["aOwnedHttpResponse"] != initial["response"]:
            raise ValueError("Any surviving A HTTP sample must retain exact ownership")
    settled = observations[-1]
    if (not settled["aTerminated"] or settled["aPidRespondsToSignalZero"] or settled.get("aOwnedHttpResponse")
            or not settled["aPortBindable"] or settled["aProgramExists"] or settled["aOutputExists"]
            or not settled["terminalQueuesEmpty"] or loss["liveOwnedHttpAfterEditorTermination"]
            or loss["outputRemovedWhileOwnedHttpAlive"]):
        raise ValueError("Natural settlement must independently show A session/PID/HTTP/port/output release, without sampled live-output loss")
    if (loss["liveOwnedHttpAfterEditorTermination"] != any(item["aTerminated"] and bool(item.get("aOwnedHttpResponse")) for item in observations)
            or loss["outputRemovedWhileOwnedHttpAlive"] != any(not item["aOutputExists"] and bool(item.get("aOwnedHttpResponse")) for item in observations)):
        raise ValueError("Live-HTTP safety flags must be derived from retained observations")
    if (not (loss["helperRequestedAtMilliseconds"] <= loss["faultReceiptObservedAtMilliseconds"] <= observations[0]["atMilliseconds"]
             <= observations[1]["atMilliseconds"] <= observations[2]["atMilliseconds"] <= observations[3]["atMilliseconds"] <= loss["observationCompletedAtMilliseconds"])
            or loss["aEditorTerminatedAtMilliseconds"] != initial["terminatedAtMilliseconds"]):
        raise ValueError("Resource observations and matching termination must retain their measured chronology")
    retry = loss["retry"]
    retry_launch = next(launch for launch in result["launches"] if launch["sessionId"] == retry["sessionId"])
    if (retry["commandInvocations"] != 3 or retry["commandResults"] != [True] * 3
            or not all(retry[key] for key in ("freshOutput", "freshSession", "freshToken"))
            or retry["sessionId"] == initial["sessionId"] or same(retry["output"], initial["output"])
            or retry["nonce"] == initial["nonce"] or retry["port"] != initial["port"]
            or any(retry[key] != retry_launch[key] for key in fixture_keys)
            or len(retry_launch["capturedSessions"]) != 1
            or not (loss["observationCompletedAtMilliseconds"] <= retry_launch["startedAtMilliseconds"])):
        raise ValueError("Three retry callers must share one fresh saved build/session/token/output after natural resource settlement")
    corrected = snapshot(retry["sourceSnapshot"], Path(initial["source"]))
    before_revision = f'const string revision = "{initial["revision"]}";'.encode()
    after_revision = f'const string revision = "{retry_launch["revision"]}";'.encode()
    corrected_profile = json.loads(snapshot(retry["profileSnapshot"], Path(initial["source"]).with_suffix(".run.json")))
    expected_profile = copy.deepcopy(a_profile)
    expected_profile["profiles"]["LifecycleHttp"]["environmentVariables"]["LIFECYCLE_TOKEN"] = retry["nonce"]
    if a_source.count(before_revision) != 1 or a_source.replace(before_revision, after_revision, 1) != corrected or corrected_profile != expected_profile:
        raise ValueError("Dirty retry may change only the saved revision and fresh profile token")
    prior.previous.validate_build(retry["log"], Path(initial["source"]), retry["output"], True)
    config = retry["configuration"]
    if (not same(config["program"], retry["program"]) or not same(config["__netcoredbgFileAppOutput"], retry["output"])
            or config["env"]["LIFECYCLE_TOKEN"] != retry["nonce"] or config["env"]["ASPNETCORE_URLS"] != retry_launch["origin"]):
        raise ValueError("Corrected retry configuration must retain its exact normal generated launch identity")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    owned = [event for event in trace if event.get("detail", {}).get("label") == "A-0" and event["atMilliseconds"] <= loss["observationCompletedAtMilliseconds"]]
    received = [event["detail"]["message"] for event in owned if event["event"] == "dap-receive"]
    sent = [{"sessionId": event["detail"]["sessionId"], "message": event["detail"]["message"]} for event in owned if event["event"] == "dap-send"]
    exits = [event["detail"] for event in owned if event["event"] == "adapter-exit"]
    terminated = [event for event in owned if event["event"] == "editor-terminate"]
    if (received != after_dap or sent != after_requests or exits != loss["aAdapterExits"] or len(exits) != 1
            or exits[0]["sessionId"] != initial["sessionId"] or len(terminated) != 1
            or terminated[0]["detail"]["sessionId"] != initial["sessionId"]
            or type(exits[0]["code"]) is not int or type(receipt["adapterExitCode"]) is not int
            or exits[0]["code"] & 0xffffffff != receipt["adapterExitCode"] & 0xffffffff
            or any(event["event"] == "stop-request" for event in owned)):
        raise ValueError("Exact transcript must bind A's adapter exit and editor termination without a test Stop request")
    ready_events = [event["detail"] for event in trace if event["event"] == "exact-adapter-loss-ready"]
    receipt_events = [event["detail"] for event in trace if event["event"] == "exact-adapter-loss-receipt"]
    resource_events = [event["detail"] for event in trace if event["event"] == "adapter-loss-resource-observation"]
    if (ready_events != [{"marker": marker, "markerSha256": loss["markerSnapshot"]["sha256"]}]
            or receipt_events != [receipt] or resource_events != observations):
        raise ValueError("Raw trace must bind the exact helper marker/receipt and all resource snapshots")
    for launch in result["launches"]:
        if (launch["response"] != {"pid": launch["pid"], "nonce": launch["nonce"], "revision": launch["revision"], "value": 42}
                or not any(event["event"] == "http-ready" and event["detail"] == {"label": launch["label"], "origin": launch["origin"], "body": launch["response"]} for event in trace)):
            raise ValueError("Every successful launch must retain its independently owned HTTP readiness response")
    b_checkpoints = [event for event in trace if event["event"] == "unrelated-preserved" and event["detail"].get("label") == "B"]
    b_after_retry = [event for event in b_checkpoints if retry_launch["startedAtMilliseconds"] <= event["atMilliseconds"] < retry_launch["stopRequestedAtMilliseconds"]]
    if (not b_after_retry or any(event["detail"]["pid"] != b["pid"] or event["detail"]["sessionId"] != b["sessionId"] for event in b_checkpoints)):
        raise ValueError("B must retain its original PID/session at a distinct successful-retry checkpoint")
    queues = Path(initial["output"]).parent.parent
    if any((queues / name).exists() and any((queues / name).iterdir()) for name in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1")):
        raise ValueError("Terminal queues must remain empty after all final Stops")
    return {"observations": loss, "validatedRetryOutputLogs": build.output_logs(work, (retry["log"],)),
            "bPreservedAfterRetry": b_after_retry,
            "adapterExitRepresentation": {"helperSignedExitCode": receipt["adapterExitCode"], "editorTrackerExitCode": exits[0]["code"], "equalModulo32Bits": True},
            "postFaultEditorDisconnectRequests": [item for item in after_requests[len(before_requests):] if item["message"]["command"] == "disconnect"],
            "mechanism": "The retained OS process handle kills only the independently verified A adapter process after native/HTTP readiness; no product/debuggee binary or environment is altered.",
            "sampling": "Four discrete post-fault snapshots independently sample A PID signal-zero, owned HTTP, port and output/queue state while checking B. They do not establish continuous liveness, descendant cleanup or a cross-platform guarantee.",
            "runtimeSource": {"tag": "v10.0.14", "commit": "6aa72daa24f66c01c3d7b6a32519e9d21396deec",
                              "url": "https://github.com/dotnet/runtime/blob/6aa72daa24f66c01c3d7b6a32519e9d21396deec/src/coreclr/debug/ee/rcthread.cpp#L934",
                              "interpretation": "The Windows CLR debugger-process-handle path fatally terminates the managed process on controller loss. Local PID/HTTP/port observations are independent evidence consistent with that path, not proof that this exact source branch executed."}}


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
    if expected["scenario"] != "native-adapter-loss":
        raise ValueError("Expected the explicit installed native adapter-process loss scenario")
    summary = summarize_primary(work, expected, result)
    identity = validate_identity(work, expected, result)
    scenario = validate_adapter_loss(work, expected, result)
    regression = args.compiler_regression.resolve()
    regression_expected, regression_result = read(regression / "expected.json"), read(regression / "result.json")
    regression_summary = build.summarize_run(regression, True)
    regression_identity = validate_identity(regression, regression_expected, regression_result)
    value = {"schema": 1, "kind": "installed native adapter-process loss and same-file retry",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
             "qualification": False, "productChange": False,
             "primaryRun": summary, "primaryIdentity": identity, "adapterLoss": scenario,
             "compilerRegression": regression_summary, "compilerRegressionIdentity": regression_identity,
             "verification": validate_units(args.tests.resolve()),
             "unexpectedFailures": [prior.validate_failure(directory.resolve()) for directory in args.failed_runs],
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), PREVIOUS, prior.PREVIOUS, prior.previous.BUILD_COLLECTOR, build.SHARED)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
