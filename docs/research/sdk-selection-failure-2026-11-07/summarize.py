"""Validate retained installed SDK-selection failure and corrected retry evidence."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE = "da4b41e736fd73af00ca531f7bff3f0452563c44"
MODULES = REPO / "scripts/variant/file-based-apps"
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}
BUILD_COLLECTOR = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"
spec = importlib.util.spec_from_file_location("sdk_compiler_summary", BUILD_COLLECTOR)
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
        raise ValueError("Expected an unreleased native Windows ARM64 candidate over merged PR37")
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
    metadata = read(directory / "verification.json")
    if (metadata["baseCommit"] != BASE or len(metadata["records"]) != 2
            or {record["label"] for record in metadata["records"]} != {"node-full", "python-full"}
            or metadata["sourcesCapturedBeforeRun"] is not True or metadata["sourcesUnchangedAfterRun"] is not True):
        raise ValueError("Expected the final Node and Python checks over the recorded merge base")
    rows = []
    for record in metadata["records"]:
        log = directory / record["log"]
        if (record["exitCode"] != 0 or web.sha256(log) != record["sha256"]
                or log.stat().st_size != record["size"] or not same(record["cwd"], REPO)):
            raise ValueError("Final verification raw log differs or failed")
        text = log.read_text(encoding="utf-8-sig")
        if "--test" in record["command"]:
            counts = {key: int(value) for key, value in re.findall(
                r"(?m)^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", text)}
            if ("--unhandled-rejections=strict" not in record["command"] or "--test-force-exit" in record["command"]
                    or counts != {"tests": 228, "pass": 228, "fail": 0, "cancelled": 0, "skipped": 0, "todo": 0}):
                raise ValueError("Expected the complete frozen 228-case strict natural-exit Node suite")
        else:
            if re.findall(r"Ran (\d+) tests? in", text) != ["39"] or not re.search(r"(?m)^OK\s*$", text):
                raise ValueError("Expected all 39 Python helpers")
            counts = {"tests": 39, "result": "OK"}
        rows.append({"record": record, "counts": counts, "rawLog": binding(log)})
    for name, item in metadata["sources"].items():
        file = REPO / name
        frozen = Path(item["snapshot"])
        if (not inside(directory / "frozen-sources", frozen) or file.read_bytes() != frozen.read_bytes()
                or web.sha256(file) != item["sha256"] or file.stat().st_size != item["size"]):
            raise ValueError("Verified source differs: " + name)
    for name in ("node", "python"):
        item = metadata[name]
        file = Path(item["path"])
        if web.sha256(file) != item["sha256"] or file.stat().st_size != item["size"]:
            raise ValueError("Pinned verification runtime differs: " + name)
    return {"directory": str(directory), "manifest": metadata,
            "manifestFile": binding(directory / "verification.json"), "runs": rows}


def validate_sdk_failure(work, expected, result):
    if (not result["scope"]["actualSdkSelectionFailure"] or result["scope"]["actualCompilerFailure"]
            or result["scope"]["actualWebProfileFailure"] or result["failedBuildAttempts"]
            or result["failedWebProfileAttempts"] or result["cancelledBuildAttempts"]
            or len(result["failedSdkSelectionAttempts"]) != 1):
        raise ValueError("A passing SDK control must retain exactly its intended pre-allocation failure")
    attempt = result["failedSdkSelectionAttempts"][0]
    fixture = expected["sdkSelection"]
    source = work / "workspace/a.cs"
    profile = source.with_suffix(".run.json")
    global_json = work / "workspace/global.json"
    inventory = work / "logs/sdk-inventory.txt"
    original = snapshot(attempt["globalJsonSnapshot"], global_json)
    invalid = snapshot(attempt["invalidGlobalJsonSnapshot"], global_json)
    if (fixture["unavailableVersion"] != "99.0.100" or attempt["unavailableVersion"] != "99.0.100"
            or not same(fixture["globalJson"], global_json) or not same(fixture["inventory"], inventory)
            or digest(original) != fixture["originalGlobalJsonSha256"]
            or json.loads(original) != {"sdk": {"version": expected["sdk"]["version"], "rollForward": "disable"}}
            or json.loads(invalid) != {"sdk": {"version": "99.0.100", "rollForward": "disable"}}
            or snapshot(attempt["globalJsonAfterSnapshot"], global_json) != invalid
            or snapshot(attempt["restoredGlobalJsonSnapshot"], global_json) != original
            or global_json.read_bytes() != original or attempt.get("restorationError")):
        raise ValueError("The isolated unavailable SDK configuration must be restored byte-for-byte")
    inventory_bytes = snapshot(attempt["inventorySnapshot"], inventory)
    versions = re.findall(r"(?m)^(\S+)\s+\[", inventory_bytes.decode("utf-8-sig"))
    if (inventory.read_bytes() != inventory_bytes or versions != attempt["installedVersions"]
            or expected["sdk"]["version"] not in versions or "99.0.100" in versions):
        raise ValueError("Captured native SDK inventory must include the selected SDK and exclude the unavailable version")
    initial = next(launch for launch in result["launches"] if launch["label"] == "A-0")
    original_source = snapshot(attempt["sourceSnapshot"], source)
    original_profile = snapshot(attempt["profileSnapshot"], profile)
    if (not same(attempt["source"], source) or not original_source.startswith(b"#:sdk Microsoft.NET.Sdk.Web")
            or attempt["sourceWasDirty"] is not False or attempt["revision"] != initial["revision"]
            or attempt["nonce"] != initial["nonce"] or attempt["origin"] != initial["origin"]
            or attempt["port"] != initial["port"] or not same(attempt["previousOutput"], initial["output"])
            or original_source != snapshot(initial["sourceSnapshot"], source)
            or original_profile != snapshot(initial["profileSnapshot"], profile)
            or snapshot(attempt["sourceAfterSnapshot"], source) != original_source
            or snapshot(attempt["profileAfterSnapshot"], profile) != original_profile
            or attempt["ambientDotnetRootBefore"] != attempt["ambientDotnetRootAfter"]
            or not same(attempt["ambientDotnetRootBefore"], expected["sdk"]["root"])):
        raise ValueError("SDK selection must leave the earlier successful source/profile and ambient SDK root unchanged")
    if (attempt["commandResult"] is not False or attempt["commandPending"]
            or not all(attempt[key] for key in ("noSession", "noAdapter", "noProcessEvent", "noOutputAllocated"))
            or attempt["adapterCreationCount"] != 0 or attempt["editorStartCount"] != 0
            or attempt["capturedSessions"] or attempt["dap"]
            or any(attempt.get(key) is not None for key in ("output", "program", "sessionId", "pid"))):
        raise ValueError("The intended SDK failure must have no allocated output or new token-matched debugger handoff")
    failed_log = attempt["log"]
    failed_tail = log_tail(failed_log)
    projection = {
        "dotnetCommands": [line for line in failed_tail.splitlines() if line.startswith("dotnet ")],
        "sdkFailedPhaseDiagnostics": [line for line in failed_tail.splitlines() if line.startswith("Phase failed: Checking .NET SDK")],
        "sdkNotFoundDiagnostics": [line for line in failed_tail.splitlines() if "A compatible .NET SDK was not found." in line or "Requested SDK version: 99.0.100" in line],
    }
    if (any(failed_log[key] != value for key, value in projection.items())
            or commands(failed_tail) != [["--version"]] or len(projection["sdkFailedPhaseDiagnostics"]) != 1
            or "Phase started: Checking .NET SDK" not in failed_tail
            or "A compatible .NET SDK was not found." not in failed_tail
            or "Requested SDK version: 99.0.100" not in failed_tail
            or any(failed_log[key] for key in ("buildCommands", "compilerDiagnostics", "failedPhaseDiagnostics",
                "cancelledPhaseDiagnostics", "buildCompletedPhaseDiagnostics", "webPreparationFailedPhaseDiagnostics",
                "webProfileRootDiagnostics", "completedPhaseDiagnostics"))
            or any(f"Phase started: {name}" in failed_tail for name in (
                "Preparing build output", "Building file-based app", "Preparing web launch settings", "Starting netcoredbg"))):
        raise ValueError("Expected one native --version failure before --info, allocation, build, Web preparation or handoff")
    parent = Path(attempt["outputParent"])
    base = Path(attempt["base"])
    if (not same(parent, Path(initial["output"]).parent) or not same(base, parent.parent)
            or not inside(work, parent) or attempt["outputParentBefore"] != sorted(attempt["outputParentBefore"])
            or attempt["outputParentBefore"] != attempt["outputParentAfter"]
            or any(attempt[key] < attempt["returnedAtMilliseconds"] for key in (
                "resourcesCheckedAtMilliseconds", "portReusableAtMilliseconds", "globalJsonRestoredAtMilliseconds"))):
        raise ValueError("Known output-parent contents and resource samples must remain unchanged after command return")
    for name in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1"):
        queue = base / name
        if queue.exists() and any(queue.iterdir()):
            raise ValueError("Exact terminal queues must remain empty after completed controls")
    coalesced = result["coalescedRetry"]
    if (coalesced["commandInvocations"] != 3 or coalesced["commandResults"] != [True] * 3
            or coalesced["sessionIds"] != [coalesced["sessionId"]] or not coalesced["freshOutput"]
            or coalesced["failedAttemptAllocatedOutput"] is not False
            or not same(coalesced["previousOutput"], initial["output"])
            or same(coalesced["output"], initial["output"]) or "failedOutput" in coalesced
            or snapshot(coalesced["globalJsonSnapshot"], global_json) != original):
        raise ValueError("Corrected three-caller retry must share one fresh output after exact original SDK restoration")
    corrected = next(launch for launch in result["launches"] if launch["sessionId"] == coalesced["sessionId"])
    corrected_source = snapshot(coalesced["sourceSnapshot"], source)
    corrected_profile = json.loads(snapshot(coalesced["profileSnapshot"], profile))
    expected_profile = json.loads(original_profile)
    expected_profile["profiles"]["LifecycleHttp"]["environmentVariables"]["LIFECYCLE_TOKEN"] = corrected["nonce"]
    before_revision = f'const string revision = "{initial["revision"]}";'.encode()
    after_revision = f'const string revision = "{corrected["revision"]}";'.encode()
    if (coalesced["sourceSnapshot"] != corrected["sourceSnapshot"] or coalesced["profileSnapshot"] != corrected["profileSnapshot"]
            or original_source.count(before_revision) != 1
            or original_source.replace(before_revision, after_revision, 1) != corrected_source
            or corrected_profile != expected_profile or corrected["nonce"] == initial["nonce"]
            or corrected["port"] != initial["port"] or not same(corrected["output"], coalesced["output"])):
        raise ValueError("The corrected retry must save only its valid source revision and new ownership token")
    retry_tail = log_tail(coalesced["log"])
    retry_commands = commands(retry_tail)
    retry_builds = [args for args in retry_commands if len(args) > 1 and args[0] == "build" and same(args[1], source)]
    if (len(retry_builds) != 1 or len(coalesced["log"]["buildCommands"]) != 1
            or retry_builds[0] != coalesced["log"]["buildCommands"][0]["args"]
            or not same(retry_builds[0][retry_builds[0].index("--output") + 1], corrected["output"])
            or len(coalesced["log"]["buildCompletedPhaseDiagnostics"]) != 1
            or len(coalesced["log"]["completedPhaseDiagnostics"]) != 1
            or any(coalesced["log"][key] for key in ("compilerDiagnostics", "failedPhaseDiagnostics", "cancelledPhaseDiagnostics",
                "webPreparationFailedPhaseDiagnostics", "webProfileRootDiagnostics"))
            or "Phase failed: Checking .NET SDK" in retry_tail or "Requested SDK version: 99.0.100" in retry_tail):
        raise ValueError("Corrected retry must identify one successful real build/handoff with no stale SDK diagnostic")
    b = next(launch for launch in result["launches"] if launch["label"] == "B")
    b_identity = {key: b[key] for key in ("sessionId", "pid", "nonce", "output", "response")}
    if attempt["bBefore"] != b_identity or attempt["bAfter"] != b_identity:
        raise ValueError("The exact independent B session/PID/nonce/HTTP body/output must survive the SDK failure")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    if any(event["event"] in ("editor-start", "dap-send", "dap-receive", "adapter-error")
           and event.get("detail", {}).get("label") == attempt["label"] for event in trace):
        raise ValueError("No new debugger/API/DAP events may be captured for the failed request")
    checkpoints = [event for event in trace if event["event"] == "unrelated-preserved" and event["detail"].get("label") == "B"]
    retry_start = next(event["atMilliseconds"] for event in trace if event["event"] == "phase-start" and event["detail"]["label"] == "A cycle 1 dirty edit and installed-command retry")
    retry_done = next(event["atMilliseconds"] for event in trace if event["event"] == "coalesced-corrected-retry-confirmed")
    after_failure = [event for event in checkpoints if attempt["returnedAtMilliseconds"] <= event["atMilliseconds"] < retry_start]
    after_retry = [event for event in checkpoints if corrected["startedAtMilliseconds"] <= event["atMilliseconds"] <= retry_done]
    if (not after_failure or not after_retry
            or any(event["detail"]["pid"] != b["pid"] or event["detail"]["sessionId"] != b["sessionId"] for event in checkpoints)):
        raise ValueError("Independent B preservation must be checked after failure and corrected retry")
    return {"attempt": attempt, "coalescedRetry": coalesced,
            "sdkInventoryFile": binding(inventory), "bPreservedAfterFailure": after_failure, "bPreservedAfterRetry": after_retry,
            "validatedOutputLogs": build.output_logs(work, (failed_log, coalesced["log"])),
            "sampling": "Pre-allocation phase/log boundary and post-return parent/queue/port checks; discrete B checkpoints. The unchanged profile reuses stopped A-0's token, so only new failed-request captures are absent."}


def validate_failure(work):
    result, launcher = read(work / "result.json"), read(work / "launcher-result.json")
    if result["success"] or not result.get("firstFailure") or launcher["success"]:
        raise ValueError("A retained unexpected failure must remain a failed attempt")
    raw = web.raw_files(work)
    raw.update(build.output_logs(work))
    inventory = work / "logs/sdk-inventory.txt"
    if inventory.exists():
        raw["logs/sdk-inventory.txt"] = binding(inventory)
    return {"directory": str(work), "result": result, "launcher": launcher, "rawEvidence": raw,
            "interpretation": "Separate unexpected attempt; not passing SDK-selection coverage."}


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
    if expected["scenario"] != "sdk-selection-failure-retry":
        raise ValueError("Expected the explicit installed SDK-selection failure scenario")
    summary = web.summarize_run(work, REPO, require_current_harness=True)
    identity = validate_identity(work, expected, result)
    scenario = validate_sdk_failure(work, expected, result)
    regression = args.compiler_regression.resolve()
    regression_expected, regression_result = read(regression / "expected.json"), read(regression / "result.json")
    regression_summary = build.summarize_run(regression, True)
    regression_identity = validate_identity(regression, regression_expected, regression_result)
    if (regression_result.get("failedSdkSelectionAttempts") or regression_result["scope"].get("actualSdkSelectionFailure")
            or (regression / "logs/sdk-inventory.txt").exists()):
        raise ValueError("The old compiler regression must not enter the optional SDK-selection branch")
    value = {"schema": 1, "kind": "installed SDK-selection failure and corrected same-file retry",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
             "qualification": False, "productChange": False, "primaryRun": summary,
             "primaryIdentity": identity, "sdkSelectionFailure": scenario,
             "compilerRegression": regression_summary, "compilerRegressionIdentity": regression_identity,
             "verification": validate_units(args.tests.resolve()),
             "unexpectedFailures": [validate_failure(directory.resolve()) for directory in args.failed_runs],
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), BUILD_COLLECTOR, build.SHARED)},
             "limits": ["Command API only; no physical F5/menu or macOS qualification.",
                        "No token-matched adapter/session/DAP process event is a handoff observation, not proof of global OS-process absence.",
                        "SDK selection fails before output allocation; no failed output deletion is claimed.",
                        "Output-parent/queue/port checks follow command return; B liveness is checked at discrete checkpoints.",
                        "The unit test uses mocked CLI/editor inputs; actual SDK diagnostics come from the separate installed-editor control.",
                        "No certificate/trust/UI cancellation, active-host-loss, descendant-process or release qualification is added."]}
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
