"""Validate retained installed editor-declined handoff and corrected retry evidence."""
import argparse
import base64
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
BASE = "9c2756eb4ac15f72053e11fb9c57ef750f36592e"
MODULES = REPO / "scripts/variant/file-based-apps"
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}
BUILD_COLLECTOR = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"
spec = importlib.util.spec_from_file_location("handoff_compiler_summary", BUILD_COLLECTOR)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
web = build.web
read = web.read_json
digest = lambda data: hashlib.sha256(data).hexdigest()


def binding(file):
    return {"sha256": web.sha256(file), "bytes": file.stat().st_size}


def same(left, right):
    return str(Path(left).resolve()).casefold() == str(Path(right).resolve()).casefold()


def inside(directory, file):
    return Path(file).resolve().is_relative_to(directory.resolve()) and not same(directory, file)


def snapshot(record, expected_path):
    data = base64.b64decode(record["base64"], validate=True)
    if (not same(record["path"], expected_path) or len(data) != record["size"]
            or digest(data) != record["sha256"]):
        raise ValueError("Historical snapshot differs from its exact path/size/hash")
    return data


def log_tail(log):
    build.validate_log_slice(log)
    units = Path(log["path"]).read_bytes().decode("utf-8").encode("utf-16-le")
    start = log["offsetCharacters"] * 2
    return units[start:start + log["tailCharacters"] * 2].decode("utf-16-le")


def commands(tail):
    rows = []
    token = re.compile(r'"(?:\\.|[^"\\])*"')
    for line in tail.splitlines():
        if not line.startswith("dotnet "):
            continue
        payload = line[len("dotnet "):]
        args = [json.loads(match.group()) for match in token.finditer(payload)]
        if " ".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in args) != payload:
            raise ValueError("Logged process arguments lost their JSON-quoted boundaries")
        rows.append(args)
    return rows


def validate_identity(work, expected, result, completed=True):
    candidate = expected["candidate"]
    if (result["expected"] != expected or candidate["sourceCommit"] != BASE
            or not candidate["localOnly"] or candidate["published"]
            or set(candidate["ownedModules"]) != MODULE_NAMES
            or candidate["target"] != "win32-arm64" or candidate["version"] != "11.7.18004"
            or candidate["baseVsixSha256"] != "0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5"
            or expected["editor"]["version"] != "1.143.17232"
            or expected["editor"]["commit"] != "c072cf642cbbadabefa22f39c58cc902a8b7427f"
            or expected["editor"]["machine"] != "arm64" or result["scope"]["platform"] != "win32-arm64"
            or expected["sdk"]["version"] != "10.0.403"
            or expected["dependency"]["version"] != "3.2.0"
            or expected["dependency"]["sha256"] != "a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541"
            or result["scope"]["invocation"] != "command-api" or result["scope"]["physicalF5"]
            or result["scope"]["macOS"] or result["scope"]["qualification"]):
        raise ValueError("Expected an unreleased native Windows ARM64 candidate over merged PR38")
    identity = {key: candidate[key] for key in ("baseVsixSha256", "sourceCommit", "target", "ownedModules")}
    if digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()) != candidate["buildId"]:
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
            raise ValueError("Executed driver differs: " + name)
    if web.sha256(work / "workspace/b.cs") != harness["fixtures/web.cs"]:
        raise ValueError("Independent B source must remain the pinned fixture")
    installed = Path(result["installedExtension"]["path"])
    if not inside(work / "extensions", installed):
        raise ValueError("Target must be normally installed in this isolated profile")
    with zipfile.ZipFile(candidate["path"]) as archive:
        metadata = json.loads(archive.read("extension/package.json"))["netcoredbgBuild"]
        if metadata["lifecycleBuildId"] != candidate["buildId"] or metadata["lifecycleSourceCommit"] != BASE:
            raise ValueError("Packaged candidate identity differs")
        for name, value in candidate["ownedModules"].items():
            data = (MODULES / name).read_bytes()
            original = subprocess.check_output(["git", "show", f"{BASE}:scripts/variant/file-based-apps/{name}"], cwd=REPO)
            if data.replace(b"\r\n", b"\n") != original.replace(b"\r\n", b"\n"):
                raise ValueError("This verification slice must not change shipped product modules")
            if (digest(data) != value or web.sha256(installed / ".netcoredbg" / name) != value
                    or digest(archive.read("extension/.netcoredbg/" + name)) != value):
                raise ValueError("Current, installed and archived module bytes differ: " + name)
    if completed and any(Path(launch["output"]).exists() for launch in result["launches"]):
        raise ValueError("Captured owned outputs must be absent after final Stop")
    return {"baseCommit": BASE, "productModulesUnchanged": True,
            "currentOwnedModules": {name: binding(MODULES / name) for name in sorted(MODULE_NAMES)}}


def validate_units(directory):
    metadata = read(directory / "source-manifest.json")
    if (metadata["commit"] != BASE or len(metadata["runs"]) != 3 or len(metadata["source"]) != 46
            or not same(metadata["worktree"], REPO)):
        raise ValueError("Expected retained initial invocation failure plus final Node/Python checks over the recorded base")
    sources = {item["path"]: item for item in metadata["source"]}
    required = {f"scripts/variant/file-based-apps/{name}" for name in MODULE_NAMES}
    tests = [f"scripts/variant/file-based-apps/test-{name}.cjs" for name in ("classify", "entry", "recovery", "runtime", "web")]
    required.update(tests)
    required.update(web.HARNESS)
    if len(sources) != 46 or not required.issubset(sources):
        raise ValueError("Pre-run source hash manifest must include every product module, intended Node suite and shared harness")
    for name, item in sources.items():
        file = REPO / name
        if not inside(REPO / "scripts/variant", file) or web.sha256(file) != item["sha256"] or file.stat().st_size != item["size"]:
            raise ValueError("Verified source differs from its pre-run hash: " + name)
    for name in ("node", "python"):
        item = metadata[name]
        if web.sha256(Path(item["path"])) != item["sha256"]:
            raise ValueError("Pinned verification runtime differs: " + name)
    expected_argv = {
        "node.log": [metadata["node"]["path"], "--unhandled-rejections=strict", "--test", *tests],
        "node-unconfigured-integration.log": [metadata["node"]["path"], "--unhandled-rejections=strict", "--test",
                                              "scripts/variant/test-factory.cjs", "scripts/variant/test-packaging.cjs", *tests],
        "python.log": [metadata["python"]["path"], "-m", "unittest", "discover", "-s", "scripts/variant", "-p", "test_*.py", "-v"],
    }
    frozen = datetime.fromisoformat(metadata["frozenUtc"].replace("Z", "+00:00"))
    verified = datetime.fromisoformat(metadata["finalSourceVerifiedUtc"].replace("Z", "+00:00"))
    rows = []
    if {record["log"] for record in metadata["runs"]} != set(expected_argv):
        raise ValueError("Every attempted unit invocation must remain distinct")
    for record in metadata["runs"]:
        log = directory / record["log"]
        result = record["result"]
        result_name = {"node.log": "node-result.json", "python.log": "python-result.json",
                       "node-unconfigured-integration.log": "node-unconfigured-integration-result.json"}[record["log"]]
        result_file = directory / result_name
        if (record["argv"] != expected_argv[record["log"]] or read(result_file) != result
                or web.sha256(log) != result["logSha256"]
                or not (frozen <= datetime.fromisoformat(result["startedUtc"].replace("Z", "+00:00"))
                        <= datetime.fromisoformat(result["completedUtc"].replace("Z", "+00:00")) <= verified)):
            raise ValueError("Recorded argv, raw invocation result, log or source-freeze timestamps differ")
        text = log.read_text(encoding="utf-8-sig")
        if "--test" in record["argv"]:
            counts = {key: int(value) for key, value in re.findall(
                r"(?m)^(?:#|ℹ) (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$", text)}
            initial = record["log"] == "node-unconfigured-integration.log"
            expected_counts = {"tests": 230 if initial else 228, "pass": 228, "fail": 2 if initial else 0,
                               "cancelled": 0, "skipped": 0, "todo": 0}
            if counts != expected_counts or result["exitCode"] != int(initial):
                raise ValueError("Expected the complete frozen 228-case strict natural-exit Node suite")
            if initial:
                if ("ERR_INVALID_ARG_TYPE" not in text or record["failedUpstreamArgumentWrappers"] != 2
                        or record["ordinaryFileAppTests"] != 228 or record["passedFileAppTests"] != 228
                        or any(f"scripts\\variant\\{name}:1:1" not in text for name in ("test-factory.cjs", "test-packaging.cjs"))):
                    raise ValueError("Retain the initial missing-upstream-argument wrapper failures as runner-selection error")
            elif (record["tests"] != 228 or record["passed"] != 228
                  or "coalesced declined debug starts permit coalesced retry while their notification remains open" not in text):
                raise ValueError("Final intended suite must include the strengthened declined-start notification control")
        else:
            if (result["exitCode"] != 0 or record["tests"] != 39 or record["passed"] != 39
                    or re.findall(r"Ran (\d+) tests? in", text) != ["39"] or not re.search(r"(?m)^OK\s*$", text)):
                raise ValueError("Expected all 39 Python helpers")
            counts = {"tests": 39, "result": "OK"}
        rows.append({"record": record, "counts": counts, "rawLog": binding(log), "rawResult": binding(result_file),
                     "interpretation": "Retained initial runner-selection error; two upstream-argument integration wrappers failed while all 228 intended file-app tests passed."
                     if record["log"] == "node-unconfigured-integration.log" else "Final intended suite passed."})
    return {"directory": str(directory), "manifest": metadata,
            "manifestFile": binding(directory / "source-manifest.json"), "runs": rows,
            "sourceObservation": "Pre-run source hashes and final verification timestamp; current bytes are rechecked against all 46 entries. Separate historical source-byte copies are not retained."}


DIAGNOSTIC = "The editor did not start the netcoredbg debug session. Check C# and Debug Console output for details before retrying"


def validate_build(log, source, output, handoff):
    tail = log_tail(log)
    rows = commands(tail)
    builds = [args for args in rows if len(args) > 1 and args[0] == "build" and same(args[1], source)]
    prefixes = {
        "failedPhaseDiagnostics": "Phase failed: Building file-based app",
        "cancelledPhaseDiagnostics": "Phase cancelled: Building file-based app",
        "buildCompletedPhaseDiagnostics": "Phase completed: Building file-based app",
        "webPreparationFailedPhaseDiagnostics": "Phase failed: Preparing web launch settings",
        "completedPhaseDiagnostics": "Phase completed: Starting netcoredbg",
    }
    projections = {key: [line for line in tail.splitlines() if line.startswith(prefix)] for key, prefix in prefixes.items()}
    projections.update(compilerDiagnostics=[line for line in tail.splitlines() if "CS0103" in line],
                       webProfileRootDiagnostics=[line for line in tail.splitlines() if "The web launch profile DOTNET_ROOT does not identify the selected dotnet installation." in line])
    if (any(log[key] != value for key, value in projections.items())
            or len(builds) != 1 or len(log["buildCommands"]) != 1
            or builds[0] != log["buildCommands"][0]["args"]
            or not same(builds[0][builds[0].index("--output") + 1], output)
            or not same(log["buildCommands"][0]["output"], output)
            or len(log["buildCompletedPhaseDiagnostics"]) != 1
            or len(log["completedPhaseDiagnostics"]) != int(handoff)
            or any(log[key] for key in ("compilerDiagnostics", "failedPhaseDiagnostics", "cancelledPhaseDiagnostics",
                                       "webPreparationFailedPhaseDiagnostics", "webProfileRootDiagnostics"))
            or any(args and args[0] == "dev-certs" for args in rows)):
        raise ValueError("Expected one real successful HTTP build and the specified handoff outcome")
    return tail


def validate_handoff_failure(work, expected, result):
    scope = result["scope"]
    if (not scope["injectedEditorRejection"] or scope["nativeAdapterFailure"] or scope["injectedTargetRuntime"]
            or any(scope[key] for key in ("actualCompilerFailure", "actualWebProfileFailure", "actualSdkSelectionFailure"))
            or any(result[key] for key in ("failedBuildAttempts", "failedWebProfileAttempts", "failedSdkSelectionAttempts", "cancelledBuildAttempts"))
            or len(result["failedHandoffAttempts"]) != 1):
        raise ValueError("Expected exactly the test-injected editor configuration rejection")
    attempt = result["failedHandoffAttempts"][0]
    source, profile = work / "workspace/a.cs", work / "workspace/a.run.json"
    initial = next(launch for launch in result["launches"] if launch["label"] == "A-0")
    b = next(launch for launch in result["launches"] if launch["label"] == "B")
    original_source = snapshot(attempt["sourceSnapshot"], source)
    original_profile = snapshot(initial["profileSnapshot"], profile)
    failed_profile = snapshot(attempt["profileSnapshot"], profile)
    parsed_profile = json.loads(failed_profile)
    initial_profile = json.loads(original_profile)
    expected_profile = json.loads(original_profile)
    expected_profile["profiles"]["LifecycleHttp"]["environmentVariables"]["LIFECYCLE_TOKEN"] = attempt["nonce"]
    if (not same(attempt["source"], source) or not attempt["expectedHandoffDeclined"]
            or attempt["sourceWasDirty"] is not False or attempt["revision"] != initial["revision"]
            or attempt["origin"] != initial["origin"] or attempt["port"] != initial["port"]
            or attempt["nonce"] in {launch["nonce"] for launch in result["launches"]}
            or original_source != snapshot(initial["sourceSnapshot"], source)
            or parsed_profile != expected_profile
            or snapshot(attempt["sourceAfterSnapshot"], source) != original_source
            or snapshot(attempt["profileAfterSnapshot"], profile) != failed_profile
            or attempt["ambientDotnetRootBefore"] != attempt["ambientDotnetRootAfter"]
            or not same(attempt["ambientDotnetRootBefore"], expected["sdk"]["root"])):
        raise ValueError("The failed request must preserve valid source and its fresh isolated HTTP-token profile")
    selected = parsed_profile["profiles"]["LifecycleHttp"]
    if (selected["commandName"] != "Project" or selected["applicationUrl"] != attempt["origin"]
            or selected["launchBrowser"] is not False or attempt["origin"] != f"http://127.0.0.1:{attempt['port']}"
            or selected["environmentVariables"] != {"LIFECYCLE_TOKEN": attempt["nonce"], "ASPNETCORE_ENVIRONMENT": "Development"}
            or initial_profile["profiles"]["LifecycleHttp"]["environmentVariables"]["LIFECYCLE_TOKEN"] != initial["nonce"]):
        raise ValueError("Expected the explicit valid HTTP launch profile without a certificate or runtime-root fault")
    if (attempt["commandInvocations"] != 3 or attempt["commandResults"] != [False] * 3
            or attempt["commandPending"] or len(attempt["providerCalls"]) != 1
            or attempt["adapterCreationCount"] != 0 or attempt["editorStartCount"] != 0
            or attempt["capturedSessions"] or attempt["dap"]
            or not all(attempt[key] for key in ("noSession", "noAdapter", "noProcessEvent", "outputAbsentAfterReturn", "terminalQueuesEmpty"))
            or any(attempt.get(key) is not None for key in ("sessionId", "pid"))):
        raise ValueError("Three callers must share one rejected provider callback with no failed-token adapter/API/DAP captures")
    call = attempt["providerCalls"][0]
    config = call["configuration"]
    output, program, base = Path(attempt["output"]), Path(attempt["program"]), Path(attempt["base"])
    if (config["type"] != "coreclr" or config["request"] != "launch"
            or not same(config["program"], program) or not same(config["__netcoredbgFileAppOutput"], output)
            or not same(program, output / "FileApp.dll") or not inside(work, output)
            or not same(base, output.parent.parent) or not same(base, Path(initial["output"]).parent.parent)
            or not re.fullmatch(r"run-[A-Za-z0-9]{6}", output.name)
            or same(output, initial["output"]) or not same(config["cwd"], source.parent)
            or not same(config["env"]["DOTNET_ROOT"], expected["sdk"]["root"])
            or config["env"]["LIFECYCLE_TOKEN"] != attempt["nonce"]
            or config["env"]["ASPNETCORE_URLS"] != attempt["origin"]
            or config["checkForDevCert"] is not False or "serverReadyAction" in config
            or len(call["artifacts"]) != 2):
        raise ValueError("Provider callback must identify the owned generated launch configuration and output")
    for artifact, name in zip(call["artifacts"], ("FileApp.dll", "FileApp.pdb")):
        if (not same(artifact["path"], output / name) or artifact["size"] <= 0
                or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])):
            raise ValueError("Callback must capture exact DLL/PDB path, positive byte count and SHA-256 before cleanup")
    if (attempt["providerActive"] or not attempt["providerDisposed"] or attempt["providerDisposalCount"] != 1
            or attempt.get("providerDisposalError")
            or not (attempt["providerRegisteredAtMilliseconds"] <= attempt["invokedAtMilliseconds"]
                    <= call["atMilliseconds"] <= attempt["returnedAtMilliseconds"]
                    <= attempt["outputRemovedAtMilliseconds"] <= attempt["providerDisposedAtMilliseconds"])
            or not (attempt["returnedAtMilliseconds"] <= attempt["portReusableAtMilliseconds"] <= attempt["providerDisposedAtMilliseconds"])):
        raise ValueError("Provider must be disarmed once in finally after post-return resource checks")
    if output.exists():
        raise ValueError("The exact failed output must remain absent")
    for name in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1"):
        queue = base / name
        if queue.exists() and any(queue.iterdir()):
            raise ValueError("The exact terminal cleanup queues must remain empty")
    failed_tail = validate_build(attempt["log"], source, output, False)
    projections = {
        "webPreparationCompletedPhaseDiagnostics": [line for line in failed_tail.splitlines() if line.startswith("Phase completed: Preparing web launch settings")],
        "handoffFailedPhaseDiagnostics": [line for line in failed_tail.splitlines() if line.startswith("Phase failed: Starting netcoredbg")],
        "declinedStartDiagnostics": [line for line in failed_tail.splitlines() if DIAGNOSTIC in line],
    }
    if (any(attempt["log"][key] != value for key, value in projections.items())
            or len(projections["webPreparationCompletedPhaseDiagnostics"]) != 1
            or len(projections["handoffFailedPhaseDiagnostics"]) != 1 or not projections["declinedStartDiagnostics"]
            or "Phase started: Starting netcoredbg" not in failed_tail):
        raise ValueError("Exact log slice must retain completed Web preparation and the editor-declined handoff diagnostic")
    coalesced = result["coalescedRetry"]
    corrected = next(launch for launch in result["launches"] if launch["sessionId"] == coalesced["sessionId"])
    corrected_source = snapshot(coalesced["sourceSnapshot"], source)
    corrected_profile = json.loads(snapshot(coalesced["profileSnapshot"], profile))
    expected_profile = json.loads(original_profile)
    expected_profile["profiles"]["LifecycleHttp"]["environmentVariables"]["LIFECYCLE_TOKEN"] = corrected["nonce"]
    before_revision = f'const string revision = "{initial["revision"]}";'.encode()
    after_revision = f'const string revision = "{corrected["revision"]}";'.encode()
    if (coalesced["commandInvocations"] != 3 or coalesced["commandResults"] != [True] * 3
            or coalesced["sessionIds"] != [coalesced["sessionId"]] or not coalesced["freshOutput"]
            or not same(coalesced["failedOutput"], output) or same(coalesced["output"], output)
            or same(coalesced["output"], initial["output"])
            or corrected["nonce"] in (attempt["nonce"], initial["nonce"])
            or corrected["port"] != initial["port"] or corrected_profile != expected_profile
            or original_source.count(before_revision) != 1
            or original_source.replace(before_revision, after_revision, 1) != corrected_source
            or coalesced["sourceSnapshot"] != corrected["sourceSnapshot"]
            or coalesced["profileSnapshot"] != corrected["profileSnapshot"]
            or coalesced["providerDisposedBeforeRetry"] is not True or coalesced["freshToken"] is not True
            or coalesced["failedNonce"] != attempt["nonce"] or coalesced["nonce"] != corrected["nonce"]
            or not same(corrected["output"], coalesced["output"])):
        raise ValueError("Corrected dirty three-caller retry must save only its new revision/token and share one fresh session/output")
    retry_tail = validate_build(coalesced["log"], source, corrected["output"], True)
    if DIAGNOSTIC in retry_tail or "Phase failed: Starting netcoredbg" in retry_tail:
        raise ValueError("Corrected retry cannot retain a stale rejection in its exact slice")
    b_identity = {key: b[key] for key in ("sessionId", "pid", "nonce", "output", "response")}
    if attempt["bBefore"] != b_identity or attempt["bAfter"] != b_identity:
        raise ValueError("The exact independent B session/PID/token/HTTP body/output must survive the rejection")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    if any(event["event"] in ("editor-start", "dap-send", "dap-receive", "adapter-error")
           and event.get("detail", {}).get("label") == attempt["label"] for event in trace):
        raise ValueError("No new debugger/API/DAP event may be captured for the fresh failed token")
    callbacks = [event for event in trace if event["event"] == "injected-editor-rejection"]
    registered = [event for event in trace if event["event"] == "injected-editor-rejection-provider-registered"]
    disposed = [event for event in trace if event["event"] == "injected-editor-rejection-provider-disposed"]
    if (len(callbacks) != 1 or callbacks[0]["detail"] != {"label": attempt["label"], "nonce": attempt["nonce"], "call": call}
            or len(registered) != 1 or len(disposed) != 1):
        raise ValueError("Exact trace must bind the one provider callback and disposal")
    checkpoints = [event for event in trace if event["event"] == "unrelated-preserved" and event["detail"].get("label") == "B"]
    retry_start = next(event["atMilliseconds"] for event in trace if event["event"] == "phase-start" and event["detail"]["label"] == "A cycle 1 dirty edit and installed-command retry")
    retry_done = next(event["atMilliseconds"] for event in trace if event["event"] == "coalesced-corrected-retry-confirmed")
    after_failure = [event for event in checkpoints if attempt["returnedAtMilliseconds"] <= event["atMilliseconds"] < retry_start]
    after_retry = [event for event in checkpoints if corrected["startedAtMilliseconds"] <= event["atMilliseconds"] <= retry_done]
    if (not after_failure or not after_retry or attempt["providerDisposedAtMilliseconds"] > retry_start
            or max(initial[key] for key in ("terminatedAtMilliseconds", "pidGoneAtMilliseconds", "portReusableAtMilliseconds", "outputRemovedAtMilliseconds")) > attempt["invokedAtMilliseconds"]
            or any(event["detail"]["pid"] != b["pid"] or event["detail"]["sessionId"] != b["sessionId"] for event in checkpoints)):
        raise ValueError("Provider must be disposed before retry and B must survive failure and retry checkpoints")
    return {"attempt": attempt, "coalescedRetry": coalesced, "providerTrace": registered + callbacks + disposed,
            "bPreservedAfterFailure": after_failure, "bPreservedAfterRetry": after_retry,
            "validatedOutputLogs": build.output_logs(work, (attempt["log"], coalesced["log"])),
            "mechanism": "Test-only exact-token coreclr configuration provider returns undefined in the actual installed editor, preventing startup before adapter creation. Provider-chain relative ordering is unspecified.",
            "artifactObservation": "DLL/PDB path, byte count and SHA-256 are captured by the callback while present; artifact bytes are not retained after owned cleanup.",
            "sampling": "Output/queue/port checks follow command return and log flush; B preservation is checked at discrete checkpoints. Empty failed-token captures do not establish global OS-process absence."}


def validate_failure(work):
    result, launcher = read(work / "result.json"), read(work / "launcher-result.json")
    if result["success"] or not result.get("firstFailure") or launcher["success"]:
        raise ValueError("A retained unexpected failure must remain a failed attempt")
    raw = web.raw_files(work)
    raw.update(build.output_logs(work))
    return {"directory": str(work), "result": result, "launcher": launcher, "rawEvidence": raw,
            "interpretation": "Separate unexpected attempt; not passing editor-rejection coverage."}


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
    if expected["scenario"] != "debug-handoff-declined-retry":
        raise ValueError("Expected the explicit installed editor-rejection scenario")
    summary = web.summarize_run(work, REPO, require_current_harness=True)
    identity = validate_identity(work, expected, result)
    scenario = validate_handoff_failure(work, expected, result)
    regression = args.compiler_regression.resolve()
    regression_expected, regression_result = read(regression / "expected.json"), read(regression / "result.json")
    regression_summary = build.summarize_run(regression, True)
    regression_identity = validate_identity(regression, regression_expected, regression_result)
    if regression_result.get("failedHandoffAttempts") or regression_result["scope"].get("injectedEditorRejection"):
        raise ValueError("The old compiler regression must not enter the injected editor-rejection branch")
    value = {"schema": 1, "kind": "installed editor-declined handoff and corrected same-file retry",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
             "qualification": False, "productChange": False, "primaryRun": summary,
             "primaryIdentity": identity, "editorRejection": scenario,
             "compilerRegression": regression_summary, "compilerRegressionIdentity": regression_identity,
             "verification": validate_units(args.tests.resolve()),
             "unexpectedFailures": [validate_failure(directory.resolve()) for directory in args.failed_runs],
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), BUILD_COLLECTOR, build.SHARED)},
             "limits": ["Actual editor rejection is injected with a test-only provider; no native adapter executable/process failure or target-runtime injection is claimed.",
                        "Command API only; no physical F5/menu or macOS qualification.",
                        "No failed-token adapter/session/DAP process event is a handoff observation, not proof of global OS-process absence.",
                        "DLL/PDB metadata is sampled in the provider callback; artifact bytes are removed and not retained.",
                        "Output/queue/port checks follow command return and log flush; B liveness is checked at discrete checkpoints.",
                        "The unresolved-notification contract is covered by a mocked unit; installed-editor notification-toast visibility is not measured.",
                        "No certificate/trust/UI cancellation, active-host-loss, descendant-process or release qualification is added."]}
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
