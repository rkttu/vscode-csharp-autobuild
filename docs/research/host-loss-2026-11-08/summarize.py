"""Validate an abrupt active extension-host loss and conservative fresh-host retry."""
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
BASE = "32eae02d4c9594be42d85f93fa1e38b079184867"
PREVIOUS = REPO / "docs/research/handoff-cancel-2026-11-08/summarize.py"
spec = importlib.util.spec_from_file_location("host_loss_previous_summary", PREVIOUS)
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)
build, web = prior.build, prior.web
read, binding, same, inside = prior.read, prior.binding, prior.same, prior.inside
snapshot, log_tail, commands = prior.snapshot, prior.log_tail, prior.commands
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}


def validate_product(work, expected, observations, base_commit=BASE):
    candidate = expected["candidate"]
    if (candidate["sourceCommit"] != base_commit or not candidate["localOnly"] or candidate["published"]
            or set(candidate["ownedModules"]) != MODULE_NAMES or candidate["target"] != "win32-arm64"
            or candidate["version"] != "11.7.18004"
            or candidate["baseVsixSha256"] != "0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5"
            or expected["editor"]["version"] != "1.143.17232"
            or expected["editor"]["commit"] != "c072cf642cbbadabefa22f39c58cc902a8b7427f"
            or expected["editor"]["machine"] != "arm64" or expected["sdk"]["version"] != "10.0.403"
            or expected["dependency"]["version"] != "3.2.0"
            or expected["dependency"]["sha256"] != "a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541"):
        raise ValueError("Expected an unreleased native Windows ARM64 candidate over merged PR43")
    identity = {key: candidate[key] for key in ("baseVsixSha256", "sourceCommit", "target", "ownedModules")}
    if hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != candidate["buildId"]:
        raise ValueError("Content build identity differs")
    for key in ("editor", "sdk"):
        if web.sha256(Path(expected[key]["executable"])) != expected[key]["sha256"]:
            raise ValueError("Pinned native executable differs: " + key)
    if (web.sha256(Path(expected["dependency"]["path"])) != expected["dependency"]["sha256"]
            or not same(candidate["path"], work / "local-lifecycle.vsix")
            or web.sha256(Path(candidate["path"])) != candidate["sha256"]):
        raise ValueError("Pinned dependency or local candidate differs")
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
            if hashlib.sha256(data).hexdigest() != value or hashlib.sha256(archive.read("extension/.netcoredbg/" + name)).hexdigest() != value:
                raise ValueError("Current/archive product module bytes differ: " + name)
            for observation in observations:
                installed = Path(observation["installed"]["path"])
                if (not inside(work / "extensions", installed) or observation["installedModules"] != candidate["ownedModules"]
                        or web.sha256(installed / ".netcoredbg" / name) != value):
                    raise ValueError("Each actual host must load the same normally installed pinned product module")
        native_relative = expected["hostLoss"]["adapterRelativePath"]
        if (native_relative != ".debugger/netcoredbg/netcoredbg.exe"
                or hashlib.sha256(archive.read("extension/" + native_relative)).hexdigest() != expected["hostLoss"]["adapterSha256"]
                or any(web.sha256(Path(observation["installed"]["path"]) / native_relative) != expected["hostLoss"]["adapterSha256"] for observation in observations)):
            raise ValueError("Both host observations must retain the archived normally installed native adapter bytes")
    return {"baseCommit": base_commit, "productModulesUnchanged": True,
            "currentOwnedModules": {name: binding(modules / name) for name in sorted(MODULE_NAMES)}}


def file_proof(record, file):
    if (not same(record["path"], file) or record["exists"] is not True or not file.is_file() or file.is_symlink()
            or record["size"] != file.stat().st_size or record["sha256"] != web.sha256(file)):
        raise ValueError("Retained file proof differs from the exact current regular file")
    return binding(file)


def validate_harness(work, expected, hosts):
    shared = REPO / "scripts/variant/lifecycle"
    own = shared / "host-loss"
    harness = {name: web.sha256(shared / name) for name in ("prepare.py", "run.ps1", "fixtures/web.cs")}
    for name in ("prepare.py", "run.ps1", "driver.cjs", "extension-test.cjs"):
        harness["host-loss/" + name] = web.sha256(own / name)
    for name in ("driver.cjs", "extension-test.cjs"):
        harness[name] = web.sha256(own / name)
        if web.sha256(work / "driver" / name) != harness[name]:
            raise ValueError("Prepared production-mode driver differs from its current source")
    original_settings = work / "prepared-settings.json"
    harness["driver/package.json"] = web.sha256(work / "driver/package.json")
    harness["profile/User/settings.json"] = web.sha256(original_settings)
    harness["prepared-settings.json"] = web.sha256(original_settings)
    if expected["harness"] != harness:
        raise ValueError("Complete recorded shared/actual host-loss harness differs from current and prepared bytes")
    before_settings = read(original_settings)
    current_settings_file = work / "profile/User/settings.json"
    after_settings = read(current_settings_file)
    normalized_settings = dict(after_settings)
    auto_update_normalized = before_settings.get("extensions.autoUpdate") is False and after_settings.get("extensions.autoUpdate") == "off"
    if auto_update_normalized:
        normalized_settings["extensions.autoUpdate"] = False
    if (normalized_settings != before_settings or before_settings.get("debug.confirmOnExit") != "never"
            or before_settings.get("window.title") != "FBA host loss " + expected["hostLoss"]["nonce"]):
        raise ValueError("Prepared profile settings may only undergo the observed editor false-to-off auto-update normalization")
    driver = expected["testDriver"]
    if (driver["id"] != "local-lifecycle-test.host-loss-driver" or driver["version"] != "0.0.1"
            or not driver["localOnly"] or driver["published"]
            or not same(driver["path"], work / "local-host-loss-driver.vsix") or web.sha256(Path(driver["path"])) != driver["sha256"]):
        raise ValueError("Expected the normally installed local-only test driver, distinct from the candidate")
    required_entries = {"extension/package.json", "extension/driver.cjs", "extension/extension-test.cjs", "extension.vsixmanifest", "[Content_Types].xml"}
    with zipfile.ZipFile(driver["path"]) as archive:
        if len(archive.namelist()) != len(required_entries) or set(archive.namelist()) != required_entries or set(driver["payload"]) != required_entries:
            raise ValueError("Local driver archive must retain its exact five-entry payload")
        for name, value in driver["payload"].items():
            if hashlib.sha256(archive.read(name)).hexdigest() != value:
                raise ValueError("Driver archive entry differs from its recorded payload")
        manifest = json.loads(archive.read("extension/package.json"))
    if manifest != read(work / "driver/package.json"):
        raise ValueError("Prepared and archived local driver manifests differ")
    if (manifest["publisher"] + "." + manifest["name"] != driver["id"] or manifest["version"] != driver["version"]
            or manifest["main"] != "./driver.cjs" or manifest["activationEvents"] != ["onStartupFinished"]
            or manifest["extensionKind"] != ["workspace"] or "contributes" in manifest):
        raise ValueError("Driver must use normal startup activation without debugger/provider contributions")
    installed_paths = []
    for host in hosts:
        recorded = host["driver"]
        installed = Path(recorded["path"])
        if (host["platform"] != "win32-arm64" or host["editorApiVersion"] != "1.143.1"
                or recorded["extensionMode"] != 1 or not inside(work / "extensions", installed)
                or not same(installed, work / "extensions" / (driver["id"] + "-" + driver["version"]))):
            raise ValueError("Both actual hosts must load the same normally installed driver in isolated production extension mode")
        for name in ("driver.cjs", "extension-test.cjs"):
            if (web.sha256(installed / name) != driver["payload"]["extension/" + name]
                    or web.sha256(work / "driver" / name) != driver["payload"]["extension/" + name]):
                raise ValueError("Actual installed/prepared driver code must retain exact archived bytes")
        file_proof(recorded["packageProof"], installed / "package.json")
        installed_manifest = read(installed / "package.json")
        metadata = installed_manifest.pop("__metadata", None)
        if not metadata or metadata != recorded["metadata"] or installed_manifest != manifest or recorded["manifest"] != manifest:
            raise ValueError("Installed driver manifest must differ only by its separately retained installer metadata")
        installed_paths.append(str(installed))
    return {"completeHarness": harness, "driver": driver, "installedDriverPaths": installed_paths,
            "settings": {"prepared": binding(original_settings), "postRun": binding(current_settings_file),
                         "extensionsAutoUpdateFalseToOffNormalization": auto_update_normalized},
            "interpretation": "The test driver is normally CLI-installed and runs in isolated production extension mode; that mode does not describe a deployed production environment. Driver code bytes are exact; installed package metadata is compared separately."}


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def trace_rows(work, phase, host):
    rows = [json.loads(line) for line in (work / f"trace-host-{phase}.jsonl").read_text(encoding="utf-8").splitlines()]
    if not rows or any(row["phase"] != phase or row["host"] != host for row in rows):
        raise ValueError("Native traces must belong to their exact actual extension host")
    if any(row["event"].startswith(("failure-", "first-failure", "observer-error")) for row in rows):
        raise ValueError("A passing primary must not hide original failures or fixture fallback")
    if any(utc(a["atUtc"]) > utc(b["atUtc"]) for a, b in zip(rows, rows[1:])):
        raise ValueError("Trace UTC chronology differs")
    return rows


def one(rows, event):
    values = [row for row in rows if row["event"] == event]
    if len(values) != 1:
        raise ValueError("Expected exactly one correlated trace event: " + event)
    return values[0]


def validate_primary(work):
    expected, result = read(work / "expected.json"), read(work / "result.json")
    nonce = expected["hostLoss"]["nonce"]
    phase, ready, receipt = (read(work / name) for name in ("phase.json", "fault-ready.json", "host-kill-receipt.json"))
    hosts = [read(work / f"host-{index}.json") for index in (1, 2)]
    processes = [read(work / f"host-{index}-process.json") for index in (1, 2)]
    runner, app = read(work / "control-runner-result.json"), read(work / "launch.json")
    external = read(work / "external-observations.json")
    if (expected["scenario"] != "abrupt-extension-host-loss" or result["expected"] != expected
            or result["success"] is not True or not result["mechanicsCompleted"] or not result["nativeResourcesReleased"]
            or not result["unknownOutputAndGuardPreserved"] or result.get("firstFailure")
            or result["phase"] != 2 or not isinstance(result["candidateAlreadyActiveBeforeExplicitActivation"], bool)):
        raise ValueError("Expected the original passing native host-loss result, separate from qualification")
    scope = {"installedCandidate": True, "normallyInstalledDriver": True, "extensionDevelopmentPath": False,
             "extensionTestsPath": False, "actualAbruptHostKill": True, "activeBuildAtFault": False,
             "injectedTargetRuntime": False, "commandApi": True, "unrelatedEditorB": False,
             "physicalF5": False, "macOS": False, "localOnly": True, "published": False, "qualification": False}
    if result["scope"] != scope:
        raise ValueError("Native control scope differs")
    product = validate_product(work, expected, hosts + [result])
    harness = validate_harness(work, expected, hosts)
    old_host, new_host = (host["extensionHostPid"] for host in hosts)
    editor = runner["editorPid"]
    if (not all(isinstance(pid, int) and pid > 0 for pid in (old_host, new_host, editor))
            or len({old_host, new_host, editor}) != 3 or result["host"] != new_host or result["firstHost"] != old_host
            or result["editorPid"] != editor or phase["firstHost"] != old_host or phase["editorPid"] != editor
            or phase["stage"] != "armed" or result["firstLaunch"] != phase["launch"]
            or ready["launch"] != phase["launch"] or ready["adapter"] != phase["adapter"]
            or ready["extensionHostPid"] != old_host or ready["editorPid"] != editor
            or ready["phaseSha256"] != web.sha256(work / "phase.json")):
        raise ValueError("Immutable fault gate must bind the exact old host, native launch, adapter and same main editor")
    for index, (host, process) in enumerate(zip(hosts, processes), 1):
        ack = read(work / f"ack-{index}.json")
        if (host["schema"] != 1 or host["nonce"] != nonce or host["phase"] != index
                or process["schema"] != 1 or not process["verified"] or process["nonce"] != nonce
                or process["marker"] != host or process["editorPid"] != editor
                or ack != {"schema": 1, "nonce": nonce, "extensionHostPid": host["extensionHostPid"], "editorPid": editor}):
            raise ValueError("Each host handshake must bind its exact externally verified process/lineage and acknowledgement")
        lineage = process["lineage"]
        if (len(lineage) < 2 or lineage[0]["processId"] != host["extensionHostPid"] or lineage[-1]["processId"] != editor
                or any(a["parentProcessId"] != b["processId"] for a, b in zip(lineage, lineage[1:]))
                or any(not same(item["executablePath"], expected["editor"]["executable"]) for item in lineage)
                or str(work / "profile").casefold() not in lineage[0]["commandLine"].casefold()
                or str(work / "extensions").casefold() not in lineage[-1]["commandLine"].casefold()):
            raise ValueError("Both actual host lineages must reach the same isolated normally launched editor")
    arguments = runner["arguments"]
    settings = expected["hostLoss"]
    if (any(record.get("nonce") != nonce for record in (phase, ready, receipt, runner, external))
            or settings["schema"] != 1 or settings["appLaunches"] != 1
            or settings["extensionDevelopmentPath"] or settings["extensionTestsPath"]
            or (settings["phaseCheckpoint"], settings["ready"], settings["receipt"]) != ("phase.json", "fault-ready.json", "host-kill-receipt.json")
            or runner["schema"] != 1 or not runner["success"] or runner["editorExitCode"] != 0
            or not runner["normallyInstalledDriver"] or runner["appLaunches"] != 1 or runner["extensionHostPids"] != [old_host, new_host]
            or runner["extensionDevelopmentPath"] or runner["extensionTestsPath"] or runner["visibleWindowRequested"]
            or not all(runner[key] for key in ("mechanicsCompleted", "nativeResourcesReleased", "unknownOutputAndGuardPreserved"))
            or not same(runner["work"], work) or app["arguments"] != arguments or app["editorPid"] != editor
            or not app["productionMode"] or not same(app["work"], work)
            or any("extensiondevelopmentpath" in arg.casefold() or "extensiontestspath" in arg.casefold() for arg in arguments)):
        raise ValueError("Expected one normal isolated app launch and an original successful runner result without development/test CLI flags")
    for flag, file in (("--user-data-dir", work / "profile"), ("--extensions-dir", work / "extensions")):
        if arguments.count(flag) != 1 or not same(arguments[arguments.index(flag) + 1].strip('"'), file):
            raise ValueError("Normal CLI profile boundaries differ")
    if not same(arguments[-1].strip('"'), work / "workspace"):
        raise ValueError("Normal CLI workspace differs")
    attempt = read(work / "control-attempt.json")
    if attempt != {"schema": 1, "nonce": nonce, "attempted": True}:
        raise ValueError("Control must retain its original single-attempt marker")
    if any((work / name).exists() for name in ("runner-first-failure.json", "phase-1-failure.json", "phase-2-failure.json", "driver-error.txt")):
        raise ValueError("Passing primary cannot discard an original failed attempt")
    old, retry = phase["launch"], result["retry"]
    native_adapter = Path(hosts[0]["installed"]["path"]) / settings["adapterRelativePath"]
    identities = receipt["identities"]
    if (receipt["schema"] != 1 or not receipt["success"] or receipt["editorPid"] != editor
            or receipt["killedProcessId"] != old_host or not receipt["killedOnlyExtensionHost"] or receipt["hostExitCode"] != -1
            or receipt["phaseSha256"] != web.sha256(work / "phase.json") or receipt["readinessSha256"] != web.sha256(work / "fault-ready.json")
            or receipt["rechecked"] != identities or identities["editorAncestry"] != processes[0]["lineage"]
            or identities["extensionHost"] != processes[0]["lineage"][0]
            or identities["adapter"]["parentProcessId"] != old_host
            or identities["debuggee"]["parentProcessId"] != identities["adapter"]["processId"]
            or identities["debuggee"]["processId"] != old["pid"]
            or len({old_host, identities["adapter"]["processId"], old["pid"], editor}) != 4
            or not same(identities["adapter"]["executablePath"], native_adapter)
            or "--interpreter=vscode" not in identities["adapter"]["commandLine"]
            or not same(identities["debuggee"]["executablePath"], expected["sdk"]["executable"])
            or old["program"].casefold() not in identities["debuggee"]["commandLine"].casefold()
            or abs((utc(receipt["heldHostStartUtc"]) - utc(identities["extensionHost"]["creationUtc"])).total_seconds()) > 0.000001
            or receipt["httpImmediatelyBeforeKill"] != old["response"]
            or not same(phase["adapter"]["path"], native_adapter) or phase["adapter"]["sha256"] != settings["adapterSha256"]):
        raise ValueError("Held-handle fault must target only the repeatedly verified exact old extension-host instance/lineage")
    file_proof(result["killReceiptProof"], work / "host-kill-receipt.json")
    for key in ("driver", "installedModules"):
        if phase[key] != hosts[0][key] or result[key] != hosts[1][key]:
            raise ValueError("Both phase payloads must bind their own actual host identity")
    if result["installed"] != hosts[1]["installed"]:
        raise ValueError("Replacement result installation differs from its real host handshake")
    traces = [trace_rows(work, index, host) for index, host in enumerate((old_host, new_host), 1)]
    for launch, rows, callers, dirty in ((old, traces[0], 1, False), (retry, traces[1], 3, True)):
        source = work / "workspace/a.cs"
        if (not same(launch["source"], source) or not inside(work / "profile", launch["output"])
                or not same(launch["program"], Path(launch["output"]) / "FileApp.dll")
                or not same(launch["base"], Path(launch["output"]).parent.parent)
                or launch["origin"] != "http://127.0.0.1:" + str(launch["port"])
                or launch["commandPending"] or not launch["started"] or launch["commandResults"] != [True] * callers
                or launch["response"] != {"pid": launch["pid"], "nonce": launch["nonce"], "revision": launch["revision"], "value": 42}):
            raise ValueError("Each public command must bind exactly one owned native Web app/output/token")
        captured = launch["capturedSessions"]
        if (len(captured) != 1 or captured[0]["sessionId"] != launch["sessionId"] or captured[0]["pid"] != launch["pid"]
                or not same(captured[0]["program"], launch["program"]) or not same(captured[0]["output"], launch["output"])):
            raise ValueError("Native PID/program/output must bind the exact sole captured editor session")
        received = [row["detail"]["message"] for row in rows if row["event"] == "dap-receive" and row["detail"]["sessionId"] == launch["sessionId"]]
        sent = [row["detail"]["message"] for row in rows if row["event"] == "dap-send" and row["detail"]["sessionId"] == launch["sessionId"]]
        if received[:len(launch["dap"])] != launch["dap"] or sent[:len(launch["requests"])] != launch["requests"]:
            raise ValueError("Serialized native checkpoint must equal its exact-session trace prefix")
        if launch is retry and (received != launch["dap"] or sent != launch["requests"]):
            raise ValueError("Completed retry transcript must equal its entire exact-session trace")
        if launch is old and any(message.get("command") in ("terminate", "disconnect") for message in sent):
            raise ValueError("The old host's complete trace must not hide a Stop after the immutable fault checkpoint")
        events = [message for message in received if message.get("event") == "process" and message.get("body", {}).get("isLocalProcess")]
        if events != [launch["dapProcessEvent"]] or events[0]["body"]["systemProcessId"] != launch["pid"]:
            raise ValueError("Real native DAP process event must corroborate the owned HTTP/captured PID")
        for command in ("initialize", "launch", "configurationDone"):
            request = [message for message in sent if message.get("command") == command]
            if len(request) != 1 or not any(message.get("type") == "response" and message.get("command") == command
                    and message.get("request_seq") == request[0]["seq"] and message.get("success") is True for message in received):
                raise ValueError("Expected successful correlated actual native setup: " + command)
        native_launch = next(message for message in sent if message.get("command") == "launch")["arguments"]
        if (not same(native_launch["program"], launch["program"]) or native_launch["env"]["LIFECYCLE_TOKEN"] != launch["nonce"]
                or native_launch["env"]["ASPNETCORE_URLS"] != launch["origin"]):
            raise ValueError("Native launch payload must match the exact app/profile token and HTTP origin")
        if one(rows, "public-command-start")["detail"] != {"label": launch["label"], "command": "netcoredbg.debugActiveFile", "callers": callers, "dirty": dirty}:
            raise ValueError("Actual public command callers/dirty save differ")
        if one(rows, "editor-start")["detail"] != {"sessionId": launch["sessionId"], "token": launch["nonce"]}:
            raise ValueError("Expected one exact native editor start")
        ready_launch = one(rows, "real-web-ready")["detail"]
        for key in ready_launch:
            if key not in ("dap", "requests", "capturedSessions") and ready_launch[key] != launch[key]:
                raise ValueError("Owned HTTP-ready checkpoint differs from final launch identity")
    if (old["label"] != "A-before-abrupt-host-loss" or old["revision"] != "initial"
            or retry["label"] != "A-after-abrupt-host-loss" or retry["revision"] != "host-loss-retry"
            or any(old[key] == retry[key] for key in ("nonce", "sessionId", "output", "pid"))
            or "testStopRequestedAtUtc" in old or any(message.get("command") in ("terminate", "disconnect") for message in old["requests"])
            or any(row["event"] == "exact-stop-request" for row in traces[0])
            or one(traces[0], "armed-for-exact-host-kill")["detail"] != phase):
        raise ValueError("Original live app must be faulted without test Stop; replacement retry must use fresh ownership")
    original = (REPO / "scripts/variant/lifecycle/fixtures/web.cs").read_bytes()
    old_source = old["sourceProof"]
    if (not same(old_source["path"], work / "workspace/a.cs") or not old_source["exists"]
            or old_source["size"] != len(original) or old_source["sha256"] != hashlib.sha256(original).hexdigest()):
        raise ValueError("Original source checkpoint must match the pinned untouched fixture")
    current_source = (work / "workspace/a.cs").read_bytes().replace(b"\r\n", b"\n")
    if current_source != original.replace(b"\r\n", b"\n").replace(b'const string revision = "initial";', b'const string revision = "host-loss-retry";'):
        raise ValueError("Dirty retry must save only the expected revision edit, allowing editor EOL normalization")
    file_proof(retry["sourceProof"], work / "workspace/a.cs")
    file_proof(retry["profileProof"], work / "workspace/a.run.json")
    profile = lambda launch: {"profiles": {"LifecycleHttp": {"commandName": "Project", "applicationUrl": launch["origin"], "launchBrowser": False,
        "environmentVariables": {"LIFECYCLE_TOKEN": launch["nonce"], "ASPNETCORE_ENVIRONMENT": "Development"}}}}
    old_profile_bytes = (json.dumps(profile(old), ensure_ascii=False, indent=2) + "\n").encode()
    if (old["profileProof"]["sha256"] != hashlib.sha256(old_profile_bytes).hexdigest()
            or old["profileProof"]["size"] != len(old_profile_bytes) or not old["profileProof"]["exists"]
            or not same(old["profileProof"]["path"], work / "workspace/a.run.json")
            or read(work / "workspace/a.run.json") != profile(retry)):
        raise ValueError("Historical profile metadata and current retry profile must bind their separate exact nonce/origin")
    preserved = old["preservedFiles"]
    if (len(preserved) != 4 or not same(preserved[0]["path"], old["program"])
            or not same(preserved[1]["path"], Path(old["output"]) / "FileApp.pdb")
            or not same(preserved[2]["path"], Path(old["output"]) / "host-loss-owned-sentinel.txt")
            or not same(Path(preserved[3]["path"]).parent.parent, Path(old["output"]).parent)
            or same(Path(preserved[3]["path"]).parent, old["output"])
            or Path(preserved[3]["path"]).name != "unmarked-host-loss-guard.txt"):
        raise ValueError("Original DLL/PDB/sentinel and unrelated unmarked sibling guard must remain separately identified")
    for proof in preserved:
        file_proof(proof, Path(proof["path"]))
    if any(Path(proof["path"]).read_bytes() != nonce.encode() for proof in preserved[2:]):
        raise ValueError("Original unknown-path guard contents must retain the exact fault nonce")
    observations = external["observations"]
    if [item["label"] for item in observations] != ["before-kill", "after-kill", "after-250ms", "after-1000ms", "replacement-host-acknowledged", "editor-exited"]:
        raise ValueError("External held-handle observations must retain their original ordered labels")
    times = [utc(item["atUtc"]) for item in observations]
    if (times != sorted(times) or not times[0] < utc(receipt["killRequestedUtc"]) <= utc(receipt["killObservedUtc"]) <= times[1]
            or read(work / "post-exit-observation.json") != observations[-1]):
        raise ValueError("External fault chronology and post-editor-exit corroboration differ")
    for index, item in enumerate(observations):
        if (any(item[key] is not (index > 0) for key in ("oldHostHasExited", "adapterHasExited", "debuggeeHasExited", "portBindable"))
                or item["httpOwned"] is not (index == 0)
                or not all(item[key] is True for key in ("outputExists", "programExists", "terminalQueuesEmpty", "unknownFilesPreserved"))
                or (index == 0 and item["http"] != old["response"])):
            raise ValueError("Independent retained-handle/HTTP/port observations must remain distinct from conservative unknown-output preservation")
    native_old_snapshots = [("before", phase["before"], True),
                            ("before-explicit-activation", result["immediateOldObservationBeforeExplicitActivation"], False),
                            ("after-initial-recovery", result["afterInitialRecovery"], False),
                            ("final", result["finalOldObservation"], False)]
    for label, item, alive in native_old_snapshots:
        if (item["pid"] != old["pid"] or item["port"] != old["port"] or not same(item["output"], old["output"])
                or item["pidRespondsToSignalZero"] is not alive or item["httpOwned"] is not alive or item["portBindable"] is not (not alive)
                or not all(item[key] for key in ("outputExists", "programExists", "terminalQueuesEmpty", "unknownFilesPreserved"))
                or item["files"] != preserved or (alive and item["http"] != old["response"])):
            raise ValueError("Exact old native resource/unknown-file checkpoint differs: " + label)
        if "adapterPid" in item and (item["adapterPid"] != identities["adapter"]["processId"] or item["adapterPidRespondsToSignalZero"]):
            raise ValueError("Old adapter signal-zero check must bind the exact captured adapter PID")
    for directory in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1"):
        queue = Path(old["base"]) / directory
        if queue.exists() and any(queue.iterdir()):
            raise ValueError("Final terminal queues must remain empty without inventing a terminal receipt for unknown active output")
    if Path(retry["output"]).exists() or not Path(old["output"]).is_dir():
        raise ValueError("Fresh terminal retry output must be absent while original unknown active output remains")
    recovery = result["newHostInitialRecoveryLog"]
    if not inside(work / "profile/logs", recovery["path"]):
        raise ValueError("Replacement-host recovery log must stay in the isolated profile")
    recovery_tail = log_tail({**recovery, "offsetCharacters": recovery["prefixCharacters"]})
    if (recovery_tail != recovery["text"] or not recovery["exists"] or recovery["size"] != len(recovery_tail.encode())
            or recovery["sha256"] != hashlib.sha256(recovery_tail.encode()).hexdigest()
            or not re.fullmatch(r"Terminal output recovery: scanned=0, attempted=0, removed=0\r?\n", recovery_tail)):
        raise ValueError("Historical initial recovery slice must be exact, independently of its later enlarged whole log")
    if recovery["kind"] != "new-log" or recovery["prefixCharacters"] != 0 or any(same(recovery["path"], file) for file in phase["firstHostLogPaths"]):
        raise ValueError("This retained run must bind its actually observed distinct new-host initial log, not an old-host flush")
    for old_log in phase["firstHostLogs"]:
        file = Path(old_log["path"])
        units = file.read_bytes().decode("utf-8").encode("utf-16-le")
        prefix = units[:old_log["prefixCharacters"] * 2].decode("utf-16-le")
        initial_builds = [args for args in commands(prefix) if args and args[0] == "build"]
        if (not inside(work / "profile/logs", file) or hashlib.sha256(prefix.encode()).hexdigest() != old_log["prefixSha256"]
                or not same(file, phase["firstHostLogPaths"][0]) or len(initial_builds) != 1
                or not same(initial_builds[0][1], old["source"])):
            raise ValueError("Original host's successful build prefix must remain exact and separate from replacement-host recovery")
    retry_log = result["retryLog"]
    tail = log_tail({**retry_log, "offsetCharacters": retry_log["prefixCharacters"]})
    args = [args for args in commands(tail) if args and args[0] == "build"]
    if (not same(retry_log["path"], recovery["path"]) or retry_log["prefixCharacters"] != recovery["tailCharacters"]
            or retry_log["prefixSha256"] != recovery["tailSha256"] or len(args) != 1 or args != retry_log["commands"]
            or args[0][0] != "build" or not same(args[0][1], retry["source"])
            or not same(args[0][args[0].index("--output") + 1], retry["output"]) or "-p:PublishAot=false" not in args[0]
            or tail.count("Phase completed: Building file-based app") != 1 or tail.count("Phase completed: Starting netcoredbg") != 1):
        raise ValueError("Three dirty corrected callers must coalesce into exactly one real SDK build and native handoff")
    stop = one(traces[1], "exact-stop-request")
    terminated = one(traces[1], "editor-terminate")
    if (stop["detail"] != {"sessionId": retry["sessionId"], "pid": retry["pid"]}
            or stop["atUtc"] != retry["testStopRequestedAtUtc"] or not retry["terminated"] or not retry["capturedSessions"][0]["terminated"]
            or terminated["detail"]["sessionId"] != retry["sessionId"]
            or not utc(retry["commandReturnedAtUtc"]) <= utc(stop["atUtc"]) <= utc(terminated["atUtc"]) <= utc(retry["resourcesReleasedAtUtc"]) <= times[-1]
            or one(traces[1], "exact-retry-cleanup")["detail"] != retry
            or one(traces[1], "observational-control-completed")["detail"] != result
            or not any(message.get("command") in ("terminate", "disconnect") for message in retry["requests"])):
        raise ValueError("Fresh retry must receive exact test Stop, matching API termination and independently observed output/PID/port cleanup")
    return {"directory": str(work), "success": True, "qualification": False, "scope": scope,
            "productIdentity": product, "harnessIdentity": harness, "normallyInstalledHosts": hosts,
            "mainEditorPid": editor, "oldExtensionHostPid": old_host, "replacementExtensionHostPid": new_host,
            "verifiedHostProcesses": processes, "faultGate": {"phase": phase, "ready": ready}, "killReceipt": receipt,
            "externalHeldHandleObservations": observations, "oldNativeSnapshots": {name: value for name, value, _ in native_old_snapshots},
            "candidateAlreadyActiveBeforeExplicitActivation": result["candidateAlreadyActiveBeforeExplicitActivation"],
            "firstLaunch": old, "retry": retry, "newHostInitialRecoveryLog": recovery, "retryLog": retry_log,
            "currentWholeRecoveryLog": binding(Path(recovery["path"])), "runner": runner,
            "rawEvidence": raw_files(work),
            "interpretation": "Exact old extension host alone was force-killed through its retained verified OS handle. Same main editor replaced it; old adapter/debuggee handles/HTTP/port were independently sampled as released. Unknown old output and unmarked guard files remained intact; three dirty retry callers used fresh output and one native session/build, then exact Stop cleaned only that retry. Initial snapshot is before explicit activation, not necessarily before automatic activation/recovery. Observation timestamps are non-atomic discrete measurements; delay labels are not calibrated latency bounds."}


def validate_failure(work):
    names = ("result.json", "control-runner-result.json", "runner-first-failure.json", "phase-1-failure.json", "phase-2-failure.json",
             "phase.json", "fault-ready.json", "host-kill-receipt.json", "external-observations.json", "post-exit-observation.json")
    records = {name: read(work / name) for name in names if (work / name).is_file()}
    runner = records.get("control-runner-result.json", {})
    if runner.get("success") or not (runner.get("error") or any(name in records for name in ("runner-first-failure.json", "phase-1-failure.json", "phase-2-failure.json"))):
        raise ValueError("An unexpected attempt must retain its original failed runner/phase evidence")
    result = records.get("result.json", {})
    return {"directory": str(work), "retainedRecords": records, "rawEvidence": raw_files(work),
            "mechanicsCompleted": result.get("mechanicsCompleted", False), "nativeResourcesReleased": result.get("nativeResourcesReleased", False),
            "interpretation": "Separate original unexpected attempt. Completed crash/restart mechanics do not override a failed native-resource/ownership result; any later fixture cleanup remains failure safety, not passing coverage."}


def validate_failed_compiler(work, native_settings):
    """Observe this retained failing regression without relaxing a passing collector."""
    expected, result, launcher = (read(work / name) for name in ("expected.json", "result.json", "launcher-result.json"))
    if (expected["scenario"] != "build-failure-retry" or result["expected"] != expected or result["success"] is not False
            or launcher["success"] is not False or launcher["editorExitCode"] != 1 or not result["firstFailure"]
            or "TimeoutError" not in result["firstFailure"]["error"] or result["scope"]["qualification"]
            or result["scope"]["invocation"] != "command-api" or result["scope"]["physicalF5"] or result["scope"]["macOS"]):
        raise ValueError("Expected the original failed compiler regression and its failed editor exit")
    # Reuse product-only identity checks. No success/output-absence projection is
    # passed to any previous passing collector; the original result stays intact.
    identity = validate_product(work, {**expected, "hostLoss": native_settings},
                                [{"installed": result["installedExtension"], "installedModules": result["installedModules"]}])
    harness = {name: web.sha256(REPO / "scripts/variant/lifecycle" / name)
               for name in ("prepare.py", "run.ps1", "driver.cjs", "extension-test.cjs", "fixtures/web.cs")}
    if expected["harness"] != harness or any(web.sha256(work / "driver" / name) != harness[name] for name in ("driver.cjs", "extension-test.cjs")):
        raise ValueError("Failed regression must still bind its exact unchanged shared driver and prepared source")
    if web.sha256(work / "workspace/b.cs") != harness["fixtures/web.cs"]:
        raise ValueError("B source must preserve the exact independent ordinary fixture")
    rows = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    failure = one(rows, "first-failure")
    if failure["detail"] != result["firstFailure"] or failure["atMilliseconds"] < result["firstFailure"]["atMilliseconds"]:
        raise ValueError("Original first failure must remain bound to the full recorded trace")
    launches = {launch["label"]: launch for launch in result["launches"]}
    if set(launches) != {"A-0", "B", "A-1"} or any(launch["commandPending"] for launch in launches.values()):
        raise ValueError("Retain the three actual launches, without fabricating later cycles")
    a0, b, retry = (launches[label] for label in ("A-0", "B", "A-1"))
    for launch in launches.values():
        ready_rows = [row for row in rows if row["event"] == "http-ready" and row["detail"]["label"] == launch["label"]]
        if (len(ready_rows) != 1 or ready_rows[0]["detail"]["body"] != launch["response"]
                or launch["response"] != {"pid": launch["pid"], "nonce": launch["nonce"], "revision": launch["revision"], "value": 42}
                or launch["commandResults"] != [True] * launch["commandInvocations"]
                or len(launch["capturedSessions"]) != 1 or launch["capturedSessions"][0]["sessionId"] != launch["sessionId"]):
            raise ValueError("Partial successful launch evidence must match its exact owned readiness event")
    attempts = result["failedBuildAttempts"]
    if len(attempts) != 1:
        raise ValueError("Retain exactly the actual deliberate compiler failure before the unexpected regression failure")
    attempt = attempts[0]
    build.validate_log_slice(attempt["log"])
    failed_tail = log_tail(attempt["log"])
    if (attempt["commandResult"] is not False or not attempt["sourceSaved"] or not attempt["noSession"] or attempt["capturedSessions"]
            or not attempt["log"]["failedPhaseDiagnostics"] or "CS0103" not in failed_tail
            or not attempt["returnedAtMilliseconds"] <= attempt["outputRemovedAtMilliseconds"] <= attempt["portReusableAtMilliseconds"]
            or Path(attempt["output"]).exists()):
        raise ValueError("Actual compiler-error handling/no-session/owned cleanup must remain measured before the later B regression failure")
    coalesced = result["coalescedRetry"]
    build.validate_log_slice(coalesced["log"])
    retry_tail = log_tail(coalesced["log"])
    retry_builds = [args for args in commands(retry_tail) if args and args[0] == "build"]
    if (coalesced["commandInvocations"] != 3 or coalesced["commandResults"] != [True] * 3
            or coalesced["sessionId"] != retry["sessionId"] or coalesced["sessionIds"] != [retry["sessionId"]]
            or not coalesced["freshOutput"] or not same(coalesced["output"], retry["output"])
            or not same(coalesced["failedOutput"], attempt["output"]) or len(retry_builds) != 1
            or retry_builds != [item["args"] for item in coalesced["log"]["buildCommands"]]
            or not same(retry_builds[0][1], retry["source"]) or not same(retry_builds[0][retry_builds[0].index("--output") + 1], retry["output"])):
        raise ValueError("Corrected A launch itself must retain three true callers/one actual SDK build/exact session")
    b_rows = [row for row in rows if isinstance(row.get("detail"), dict) and row["detail"].get("sessionId") == b["sessionId"]]
    pauses = [row for row in b_rows if row["event"] == "dap-send" and row["detail"]["message"].get("command") == "pause"]
    stops = [row for row in b_rows if row["event"] == "dap-receive" and row["detail"]["message"].get("event") == "stopped"
             and row["detail"]["message"].get("body", {}).get("reason") == "pause"]
    if len(pauses) != 1 or len(stops) != 1:
        raise ValueError("Failed control must retain the actually observed B pause request/stopped event")
    pause, stopped = pauses[0], stops[0]
    response = [row for row in b_rows if row["event"] == "dap-receive" and row["detail"]["message"].get("type") == "response"
                and row["detail"]["message"].get("command") == "pause" and row["detail"]["message"].get("request_seq") == pause["detail"]["message"]["seq"]]
    a_ready = next(row for row in rows if row["event"] == "http-ready" and row["detail"]["label"] == "A-1")
    if (len(response) != 1 or response[0]["detail"]["message"].get("success") is not True
            or not pause["atMilliseconds"] <= stopped["atMilliseconds"] <= a_ready["atMilliseconds"] < failure["atMilliseconds"]
            or any(row["event"] == "dap-send" and row["detail"]["message"].get("command") == "continue"
                   and pause["atMilliseconds"] <= row["atMilliseconds"] <= failure["atMilliseconds"] for row in b_rows)):
        raise ValueError("Original B pause/no-continue interval must remain distinct from the later failure safety Stop")
    cleanup = result["cleanup"]
    for launch in (b, retry):
        entry = next(item for item in cleanup if item.get("sessionId") == launch["sessionId"])
        terminations = [row for row in rows if row["event"] == "dap-send" and row["detail"].get("sessionId") == launch["sessionId"]
                        and row["detail"]["message"].get("command") == "terminate"]
        if not entry["exactSessionStopRequested"] or not entry["pidGone"] or not terminations or terminations[0]["atMilliseconds"] <= failure["atMilliseconds"]:
            raise ValueError("Post-failure exact-session safety cleanup must not become a passing preservation assertion")
    if Path(a0["output"]).exists() or not Path(b["output"]).exists() or not Path(retry["output"]).exists():
        raise ValueError("This failed run must retain its actual sampled output states: A0 gone, B/A1 retained")
    state = {}
    for launch in launches.values():
        output = Path(launch["output"])
        state[launch["label"]] = {"path": str(output), "exists": output.exists(),
            "retainedFiles": {str(file.relative_to(output)): binding(file) for file in sorted(output.rglob("*")) if file.is_file()} if output.exists() else {}}
    return {"directory": str(work), "success": False, "qualification": False, "firstFailure": result["firstFailure"],
            "elapsedMilliseconds": result["elapsedMilliseconds"], "identity": identity, "harness": harness,
            "completedChecks": result["checks"], "phases": result["phases"], "launches": result["launches"],
            "actualCompilerFailure": attempt, "correctedACoalescedLaunch": coalesced,
            "bPauseObservation": {"request": pause, "stopped": stopped, "response": response[0], "noContinueBeforeFirstFailure": True,
                                  "aRetryHttpReady": a_ready, "initiator": "unproven"},
            "postFailureSafetyCleanup": cleanup, "sampledOutputState": state, "launcher": launcher,
            "rawEvidence": raw_files(work),
            "interpretation": "Original regression FAIL, retained without automatic resume or rerun. A compiler failure/cleanup and corrected coalesced A launch succeeded, but unrelated B received editor-to-adapter pause/stopped and no continue before its HTTP probe timed out. Trace establishes that paused interval, not the higher-level caller/trigger. Exact-session Stop/PID observations and later fixture shutdown attempts are failure safety, not successful B preservation or output cleanup. Prior passing compiler assertions remain unchanged."}


def raw_files(work):
    files = set(file for pattern in ("*.json", "trace*.jsonl", "driver-error.txt") for file in work.glob(pattern) if file.is_file())
    files.update(file for file in (work / "logs").glob("*") if file.is_file())
    for pattern in ("**/main.log", "**/renderer.log", "**/exthost.log", "**/C#.log", "**/*C# File Debugging.log"):
        files.update(file for file in (work / "profile/logs").glob(pattern) if file.is_file())
    return {file.relative_to(work).as_posix(): binding(file) for file in sorted(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--compiler-regression", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--failed-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    primary = validate_primary(args.run.resolve())
    regression = args.compiler_regression.resolve()
    regression_expected, regression_result = read(regression / "expected.json"), read(regression / "result.json")
    if regression_result["success"]:
        regression_summary = build.summarize_run(regression, True)
        regression_identity = prior.validate_identity(regression, regression_expected, regression_result, base_commit=BASE)
    else:
        regression_summary = validate_failed_compiler(regression, read(args.run.resolve() / "expected.json")["hostLoss"])
        regression_identity = regression_summary["identity"]
    value = {"schema": 1, "kind": "installed abrupt extension-host loss and conservative same-editor fresh-host retry",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18", "qualification": False, "productChange": False,
             "overallStatus": "primary-pass-regression-fail" if not regression_result["success"] else "controls-pass",
             "primaryRun": primary, "compilerRegression": regression_summary, "compilerRegressionIdentity": regression_identity,
             "verification": prior.prior.validate_units(args.tests.resolve(), base_commit=BASE),
             "unexpectedAttempts": [validate_failure(directory.resolve()) for directory in args.failed_runs],
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), PREVIOUS, prior.PREVIOUS, prior.prior.PREVIOUS,
                                                                                 prior.prior.history.PREVIOUS, prior.prior.history.prior.PREVIOUS,
                                                                                 prior.prior.history.prior.previous.BUILD_COLLECTOR, build.SHARED)},
             "acceptanceAudit": {"path": str((HERE / "acceptance-audit.md").relative_to(REPO)), **binding(HERE / "acceptance-audit.md")},
             "limits": ["Unknown original active output and unmarked guard bytes are deliberately preserved; dead host/PID/adapter alone is not a terminal cleanup receipt.",
                        "A new command may use fresh output without proving the old unknown path is eligible for deletion.",
                        "Native process/port/resource observations are discrete and do not establish descendant-tree cleanup or cross-platform behavior.",
                        "Issue18's indefinitely unsettled machine-I/O/total-phase-bound gap remains open; this control is not release qualification."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
