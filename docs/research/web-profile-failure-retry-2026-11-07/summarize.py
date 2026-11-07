"""Validate retained installed Web-profile failure/corrected-retry controls."""
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
BASE = "0a837aebc153c2c51a93ad4a07efac102c11c8ee"
MODULES = REPO / "scripts/variant/file-based-apps"
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}
DIAGNOSTIC = "The web launch profile DOTNET_ROOT does not identify the selected dotnet installation."


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD_COLLECTOR = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"
build = load_module("compiler_failure_summary", BUILD_COLLECTOR)
web = build.web


def digest(data):
    return hashlib.sha256(data).hexdigest()


def binding(file):
    return {"sha256": web.sha256(file), "bytes": file.stat().st_size}


def read(file):
    return web.read_json(file)


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


def build_commands(tail, source):
    commands = []
    token = re.compile(r'"(?:\\.|[^"\\])*"')
    for line in tail.splitlines():
        if not line.startswith("dotnet "):
            continue
        payload = line[len("dotnet "):]
        args = [json.loads(match.group()) for match in token.finditer(payload)]
        # JS JSON.stringify leaves non-ASCII literal; there are no escaped
        # separators between logged arguments, so parse every quoted token.
        reconstructed = " ".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in args)
        if reconstructed != payload:
            raise ValueError("Logged process arguments lost their JSON-quoted boundaries")
        if len(args) >= 2 and args[0] == "build" and same(args[1], source):
            index = args.index("--output")
            commands.append({"args": args, "output": args[index + 1]})
    return commands


def validate_identity(work, expected, result, completed=True):
    if result["expected"] != expected:
        raise ValueError("The result must retain the exact prepared input")
    candidate = expected["candidate"]
    if (candidate["sourceCommit"] != BASE or not candidate["localOnly"] or candidate["published"]
            or set(candidate["ownedModules"]) != MODULE_NAMES
            or candidate["target"] != "win32-arm64" or candidate["version"] != "11.7.18004"
            or candidate["baseVsixSha256"] != "0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5"
            or expected["editor"]["version"] != "1.143.17232"
            or expected["editor"]["commit"] != "c072cf642cbbadabefa22f39c58cc902a8b7427f"
            or expected["sdk"]["version"] != "10.0.403"
            or expected["dependency"]["version"] != "3.2.0"
            or expected["dependency"]["sha256"] != "a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541"
            or result["scope"]["invocation"] != "command-api" or result["scope"]["physicalF5"]
            or result["scope"]["macOS"] or result["scope"]["qualification"]):
        raise ValueError("Expected an unreleased native candidate over merged PR35")
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
        raise ValueError("The exact prepared harness differs from current source")
    for name in ("driver.cjs", "extension-test.cjs"):
        if web.sha256(work / "driver" / name) != harness[name]:
            raise ValueError("Executed driver differs: " + name)
    if web.sha256(work / "workspace/b.cs") != harness["fixtures/web.cs"]:
        raise ValueError("The independent B source must remain the pinned fixture")
    installed = Path(result["installedExtension"]["path"])
    if not inside(work / "extensions", installed):
        raise ValueError("Target must be normally installed in this isolated profile")
    with zipfile.ZipFile(candidate["path"]) as archive:
        metadata = json.loads(archive.read("extension/package.json"))
        if metadata["netcoredbgBuild"]["lifecycleBuildId"] != candidate["buildId"]:
            raise ValueError("Packaged candidate identity differs")
        for name, value in candidate["ownedModules"].items():
            data = (MODULES / name).read_bytes()
            original = subprocess.check_output(["git", "show", f"{BASE}:scripts/variant/file-based-apps/{name}"], cwd=REPO)
            if data.replace(b"\r\n", b"\n") != original.replace(b"\r\n", b"\n"):
                raise ValueError("This verification slice must not change shipped product modules")
            if (digest(data) != value or web.sha256(installed / ".netcoredbg" / name) != value
                    or digest(archive.read("extension/.netcoredbg/" + name)) != value):
                raise ValueError("Current, installed and archived module bytes differ: " + name)
    for launch in result["launches"] if completed else ():
        if Path(launch["output"]).exists():
            raise ValueError("Exact captured owned outputs must be absent after final Stop")
    return {"baseCommit": BASE, "productModulesUnchanged": True,
            "currentOwnedModules": {name: binding(MODULES / name) for name in candidate["ownedModules"]}}


def validate_units(directory):
    metadata = read(directory / "verification.json")
    if (metadata["baseCommit"] != BASE or len(metadata["records"]) != 2
            or {record["label"] for record in metadata["records"]} != {"after-full", "python-full"}):
        raise ValueError("Expected one final Node and one Python check over the recorded base")
    rows = []
    for record in metadata["records"]:
        log = directory / record["log"]
        if record["exitCode"] != 0 or web.sha256(log) != record["logSha256"]:
            raise ValueError("Final verification raw log differs or failed")
        text = log.read_text(encoding="utf-8-sig")
        if "--test" in record["command"]:
            if "--unhandled-rejections=strict" not in record["command"] or "--test-force-exit" in record["command"]:
                raise ValueError("Node verification must use strict natural exit")
            counts = {key: int(value) for key, value in re.findall(
                r"(?m)^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", text)}
            if set(counts) != {"tests", "pass", "fail", "cancelled", "skipped", "todo"} or any(counts[key] for key in ("fail", "cancelled", "skipped", "todo")) or counts["tests"] != counts["pass"]:
                raise ValueError("Incomplete or failing Node verification")
            if counts["tests"] != 217:
                raise ValueError("Expected the complete frozen 217-case Node suite")
        else:
            match = re.findall(r"Ran (\d+) tests? in", text)
            if len(match) != 1 or not re.search(r"(?m)^OK\s*$", text):
                raise ValueError("Incomplete Python helper verification")
            if int(match[0]) != 39:
                raise ValueError("Expected all 39 Python helpers")
            counts = {"tests": int(match[0]), "result": "OK"}
        rows.append({"record": record, "counts": counts, "rawLog": binding(log)})
    for name, item in metadata["sources"].items():
        file = Path(name)
        if web.sha256(file) != item["sha256"] or file.stat().st_size != item.get("size", item.get("bytes")):
            raise ValueError("Verified source differs: " + name)
    return {"directory": str(directory), "manifest": metadata,
            "manifestFile": binding(directory / "verification.json"), "runs": rows,
            "preparatoryFocusedLog": {"file": binding(directory / "focused.log"),
                "scope": metadata["notes"]}}


def validate_failure(work):
    expected, result, launcher = (read(work / name) for name in ("expected.json", "result.json", "launcher-result.json"))
    if (expected["scenario"] != "web-profile-failure-retry" or result["success"]
            or not result.get("firstFailure") or launcher["success"] or launcher["editorExitCode"] != 1
            or result["failedWebProfileAttempts"] or result["failedBuildAttempts"]
            or len(result["launches"]) != 1 or result["launches"][0]["label"] != "A-0"
            or result["launches"][0]["commandResults"] != [False]
            or result["launches"][0]["capturedSessions"]):
        raise ValueError("Retain the failed initial launch as an unintended failure, not Web-profile coverage")
    identity = validate_identity(work, expected, result, completed=False)
    paths = sorted((work / "profile/logs").glob("**/*C# File Debugging.log"))
    if len(paths) != 1:
        raise ValueError("Expected one exact initial-launch output log")
    text = paths[0].read_bytes().decode("utf-8")
    error_lines = [line for line in text.splitlines() if "ENAMETOOLONG" in line and "mkdtemp" in line]
    phase_lines = [line for line in text.splitlines() if line.startswith("Phase failed: Preparing build output")]
    if (len(error_lines) != 1 or len(phase_lines) != 1 or build_commands(text, work / "workspace/a.cs")
            or "Phase started: Building file-based app" in text or DIAGNOSTIC in text):
        raise ValueError("The first failure must remain the observed pre-build path-length boundary")
    if launcher.get("fixtureShutdown"):
        raise ValueError("No debuggee was launched in the failed initial profile")
    return {"directory": str(work), "role": "unintended initial-launch failure before the selected Web-profile scenario",
            "result": result, "launcher": launcher, "identity": identity,
            "observedError": error_lines, "observedPhase": phase_lines,
            "rawEvidence": web.raw_files(work), "outputLog": {str(paths[0]): binding(paths[0])},
            "interpretation": "The long isolated custom profile path produced ENAMETOOLONG during mkdtemp before actual build or Web preparation. Shorter fresh paths change the test location, not the product or harness. This Windows path-length limitation remains open."}


def validate_web_failure(work, expected, result):
    if (not result["scope"]["actualWebProfileFailure"] or result["scope"]["actualCompilerFailure"]
            or result["failedBuildAttempts"] or result["cancelledBuildAttempts"]
            or len(result["failedWebProfileAttempts"]) != 1):
        raise ValueError("A passing profile control must retain exactly its intended late failure")
    attempt = result["failedWebProfileAttempts"][0]
    source = Path(attempt["source"])
    profile_path = source.with_suffix(".run.json")
    original_source = snapshot(attempt["sourceSnapshot"], source)
    bad_bytes = snapshot(attempt["profileSnapshot"], profile_path)
    profile = json.loads(bad_bytes)["profiles"]["LifecycleHttp"]
    environment = profile["environmentVariables"]
    if (attempt["commandResult"] is not False or attempt["commandPending"]
            or not attempt["sourceUnchanged"] or attempt["sourceAfterSha256"] != digest(original_source)
            or attempt["sourceWasDirty"] is not False or attempt["profileAfterSha256"] != digest(bad_bytes)
            or attempt["ambientDotnetRootBefore"] != attempt["ambientDotnetRootAfter"]
            or not same(attempt["ambientDotnetRootBefore"], expected["sdk"]["root"])
            or profile["applicationUrl"] != attempt["origin"]
            or attempt["origin"] != f"http://127.0.0.1:{attempt['port']}"
            or profile["commandName"] != "Project" or profile["launchBrowser"] is not False
            or environment["LIFECYCLE_TOKEN"] != attempt["nonce"]
            or environment["ASPNETCORE_ENVIRONMENT"] != "Development"
            or not same(environment["DOTNET_ROOT"], attempt["invalidRoot"])
            or same(attempt["invalidRoot"], expected["sdk"]["root"])
            or not inside(work, attempt["invalidRoot"]) or Path(attempt["invalidRoot"]).exists()):
        raise ValueError("Expected a source-preserving A-only HTTP profile root fault")
    if (not all(attempt[key] for key in ("noSession", "noAdapter", "noProcessEvent"))
            or attempt["adapterCreationCount"] != 0 or attempt["editorStartCount"] != 0
            or attempt["capturedSessions"] or attempt["dap"]
            or attempt.get("sessionId") is not None or attempt.get("pid") is not None):
        raise ValueError("The profile failure must precede token-matched adapter/session/DAP handoff")
    initial = next(launch for launch in result["launches"] if launch["label"] == "A-0")
    if (attempt["revision"] != initial["revision"]
            or digest(original_source) != initial["sourceSnapshot"]["sha256"]
            or original_source != snapshot(initial["sourceSnapshot"], source)):
        raise ValueError("The failed source must be byte-identical to the earlier actual successful Web source")
    failed_log = attempt["log"]
    failed_tail = log_tail(failed_log)
    projection = {
        "buildCompletedPhaseDiagnostics": [line for line in failed_tail.splitlines() if line.startswith("Phase completed: Building file-based app")],
        "webPreparationFailedPhaseDiagnostics": [line for line in failed_tail.splitlines() if line.startswith("Phase failed: Preparing web launch settings")],
        "webProfileRootDiagnostics": [line for line in failed_tail.splitlines() if DIAGNOSTIC in line],
    }
    if (any(failed_log[key] != value for key, value in projection.items())
            or len(projection["buildCompletedPhaseDiagnostics"]) != 1
            or len(projection["webPreparationFailedPhaseDiagnostics"]) != 1
            or not projection["webProfileRootDiagnostics"]
            or any(failed_log[key] for key in ("compilerDiagnostics", "failedPhaseDiagnostics", "cancelledPhaseDiagnostics", "completedPhaseDiagnostics"))
            or "Phase started: Starting netcoredbg" in failed_tail or 'dotnet "dev-certs"' in failed_tail):
        raise ValueError("Expected successful real build then the exact Web-profile diagnostic before handoff")
    commands = build_commands(failed_tail, source)
    if (commands != failed_log["buildCommands"] or len(commands) != 1
            or not same(commands[0]["output"], attempt["output"])
            or not same(Path(attempt["output"]) / "FileApp.dll", attempt["program"])
            or not same(Path(attempt["output"]).parent.parent, attempt["base"])
            or not inside(work, attempt["output"]) or Path(attempt["output"]).exists()):
        raise ValueError("The exact logged failed output must be owned, distinct and absent")
    if any(attempt[key] < attempt["returnedAtMilliseconds"] for key in ("outputRemovedAtMilliseconds", "portReusableAtMilliseconds")):
        raise ValueError("Failed-attempt resource samples must be post-return observations")
    for name in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1"):
        queue = Path(attempt["base"]) / name
        if queue.exists() and any(queue.iterdir()):
            raise ValueError("The exact terminal queues must remain empty after the completed control")
    coalesced = result["coalescedRetry"]
    if (coalesced["commandInvocations"] != 3 or coalesced["commandResults"] != [True] * 3
            or coalesced["sessionIds"] != [coalesced["sessionId"]]
            or not coalesced["freshOutput"] or same(coalesced["output"], attempt["output"])
            or not same(coalesced["failedOutput"], attempt["output"])):
        raise ValueError("A corrected three-caller retry must share exactly one fresh session/output")
    corrected = next(launch for launch in result["launches"] if launch["sessionId"] == coalesced["sessionId"])
    corrected_profile = json.loads(snapshot(coalesced["profileSnapshot"], profile_path))["profiles"]["LifecycleHttp"]
    corrected_source = snapshot(coalesced["sourceSnapshot"], source)
    if (coalesced["profileSnapshot"] != corrected["profileSnapshot"] or coalesced["sourceSnapshot"] != corrected["sourceSnapshot"]
            or "DOTNET_ROOT" in corrected_profile["environmentVariables"]
            or corrected_profile["environmentVariables"]["LIFECYCLE_TOKEN"] != corrected["nonce"]
            or corrected["nonce"] == attempt["nonce"] or corrected["port"] != attempt["port"]
            or not same(corrected["output"], coalesced["output"])):
        raise ValueError("The corrected profile must identify the exact captured new session and omit its bad root")
    profile_without_fault = json.loads(bad_bytes)["profiles"]["LifecycleHttp"]
    del profile_without_fault["environmentVariables"]["DOTNET_ROOT"]
    profile_without_fault["environmentVariables"]["LIFECYCLE_TOKEN"] = corrected["nonce"]
    if profile_without_fault != corrected_profile:
        raise ValueError("The HTTP profile correction must remove only the bad root apart from the new ownership token")
    before_revision = f'const string revision = "{attempt["revision"]}";'.encode()
    after_revision = f'const string revision = "{corrected["revision"]}";'.encode()
    if original_source.count(before_revision) != 1 or original_source.replace(before_revision, after_revision, 1) != corrected_source:
        raise ValueError("The corrected retry must save only its valid source revision change")
    retry_tail = log_tail(coalesced["log"])
    if (build_commands(retry_tail, source) != coalesced["log"]["buildCommands"]
            or len(coalesced["log"]["buildCommands"]) != 1
            or len(coalesced["log"]["completedPhaseDiagnostics"]) != 1
            or len(coalesced["log"]["buildCompletedPhaseDiagnostics"]) != 1
            or any(coalesced["log"][key] for key in ("compilerDiagnostics", "failedPhaseDiagnostics", "cancelledPhaseDiagnostics", "webPreparationFailedPhaseDiagnostics", "webProfileRootDiagnostics"))
            or not same(coalesced["log"]["buildCommands"][0]["output"], corrected["output"])
            or DIAGNOSTIC in retry_tail or 'dotnet "dev-certs"' in retry_tail):
        raise ValueError("The corrected retry must have one successful build/handoff and no stale Web failure")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    if any(event["event"] in ("editor-start", "dap-send", "dap-receive", "adapter-error")
           and event.get("detail", {}).get("label") == attempt["label"] for event in trace):
        raise ValueError("A profile-failed token must not produce adapter/API/DAP events")
    b = next(launch for launch in result["launches"] if launch["label"] == "B")
    checkpoints = [event for event in trace if event["event"] == "unrelated-preserved" and event["detail"].get("label") == "B"]
    retry_start = next(event["atMilliseconds"] for event in trace if event["event"] == "phase-start" and event["detail"]["label"] == "A cycle 1 dirty edit and installed-command retry")
    retry_done = next(event["atMilliseconds"] for event in trace if event["event"] == "coalesced-corrected-retry-confirmed")
    after_failure = [event for event in checkpoints if attempt["returnedAtMilliseconds"] <= event["atMilliseconds"] < retry_start]
    after_retry = [event for event in checkpoints if corrected["startedAtMilliseconds"] <= event["atMilliseconds"] <= retry_done]
    if (not after_failure or not after_retry
            or any(event["detail"]["pid"] != b["pid"] or event["detail"]["sessionId"] != b["sessionId"] for event in checkpoints)
            or b["response"]["nonce"] != b["nonce"] or b["response"]["pid"] != b["pid"]):
        raise ValueError("Independent B ownership must be observed after both failure and corrected retry")
    return {"attempt": attempt, "coalescedRetry": coalesced,
            "bPreservedAfterFailure": after_failure, "bPreservedAfterRetry": after_retry,
            "validatedOutputLogs": build.output_logs(work, (failed_log, coalesced["log"])),
            "sampling": "Post-return output/port and discrete B checkpoints; no exact deletion time or continuous liveness claim"}


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
    if expected["scenario"] != "web-profile-failure-retry":
        raise ValueError("Expected the explicit installed Web-profile failure scenario")
    summary = web.summarize_run(work, REPO, require_current_harness=True)
    identity = validate_identity(work, expected, result)
    scenario = validate_web_failure(work, expected, result)
    regression = args.compiler_regression.resolve()
    regression_expected, regression_result = read(regression / "expected.json"), read(regression / "result.json")
    regression_summary = build.summarize_run(regression, True)
    regression_identity = validate_identity(regression, regression_expected, regression_result)
    failures = [validate_failure(directory.resolve()) for directory in args.failed_runs]
    value = {"schema": 1, "kind": "installed Web-profile failure and corrected same-file retry",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
             "qualification": False, "productChange": False, "primaryRun": summary,
             "primaryIdentity": identity, "webProfileFailure": scenario,
             "compilerRegression": regression_summary, "compilerRegressionIdentity": regression_identity,
             "verification": validate_units(args.tests.resolve()), "unexpectedFailures": failures,
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), BUILD_COLLECTOR, build.SHARED)},
             "limits": ["Command API only; no physical F5/menu or macOS qualification.",
                        "No token-matched adapter/session/DAP process event is an observed handoff boundary, not proof of global OS-process absence.",
                        "Output and port observations are after command return/log flushing; no continuous or exact deletion ordering is claimed.",
                        "No certificate/trust/UI cancellation, active-host-loss or descendant-process qualification is added."]}
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
