"""Validate installed independent-file concurrent builds and same-file retry."""
import argparse
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
BASE = "ae48926c7ba10d6f7cac21eeefe000cb49bd1461"
PREVIOUS = REPO / "docs/research/adapter-loss-2026-11-08/summarize.py"
spec = importlib.util.spec_from_file_location("concurrent_files_previous_summary", PREVIOUS)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)
build, web = history.build, history.web
read, binding, same, inside = history.read, history.binding, history.same, history.inside
snapshot, log_tail, commands = history.snapshot, history.log_tail, history.commands
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}
EARLIER_DRIVER_SHA256 = "fcf48fcae81094cf5568495851b89264d0f276144bf0e8a5a816d9c3e1f394e8"
OLD_DRAIN = "                await bounded(Promise.all(concurrentOperations.map(item => item.observed)), 'concurrent partial command failure drain', 15000);"
NEW_DRAIN = "                await bounded(Promise.all(concurrentOperations.flatMap(item => [item.observed, item.launch?.commandOperation].filter(Boolean))), 'concurrent partial command failure drain', 15000);"


def validate_units(directory, base_commit=BASE):
    metadata = read(directory / "source-manifest.json")
    if metadata["commit"] != base_commit or len(metadata["runs"]) != 2 or not same(metadata["worktree"], REPO):
        raise ValueError("Expected the exact merged base and separate Node/Python attempts")
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


def validate_identity(work, expected, result, historical=False, base_commit=BASE):
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
        raise ValueError("Expected an unreleased native Windows ARM64 candidate over merged PR41")
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
    harness = validate_harness(work, expected, result, historical)
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
        raise ValueError("Every exact captured output must remain absent after final Stop")
    return {"baseCommit": base_commit, "productModulesUnchanged": True,
            "currentOwnedModules": {name: binding(modules / name) for name in sorted(MODULE_NAMES)}, "completeHarness": harness,
            "historicalHarness": historical,
            "driverRelation": {"executed": binding(work / "driver/extension-test.cjs"),
                               "current": binding(REPO / "scripts/variant/lifecycle/extension-test.cjs"),
                               "onlyEarlierSourceDifference": {"old": OLD_DRAIN, "current": NEW_DRAIN} if historical else None}}


def validate_harness(work, expected, result, historical=False):
    harness = {name.removeprefix("scripts/variant/lifecycle/"): web.sha256(REPO / name) for name in web.HARNESS[:5]}
    if historical:
        copied = work / "driver/extension-test.cjs"
        old_source = copied.read_bytes().replace(b"\r\n", b"\n")
        current_source = (REPO / "scripts/variant/lifecycle/extension-test.cjs").read_bytes().replace(b"\r\n", b"\n")
        if (expected["scenario"] != "concurrent-files" or web.sha256(copied) != EARLIER_DRIVER_SHA256
                or old_source.count(OLD_DRAIN.encode()) != 1
                or old_source.replace(OLD_DRAIN.encode(), NEW_DRAIN.encode(), 1) != current_source):
            raise ValueError("Earlier passing control must retain its exact old driver and only the reviewed one-line failure-drain difference")
        harness["extension-test.cjs"] = EARLIER_DRIVER_SHA256
    for name in ("driver.cjs", "extension-test.cjs"):
        if web.sha256(work / "driver" / name) != harness[name]:
            raise ValueError("Executed driver differs from prepared/current source: " + name)
    if expected["scenario"] == "concurrent-files":
        target = REPO / "scripts/variant/lifecycle/fixtures/concurrent-build.targets"
        prepared_target = Path(expected["concurrent"]["target"])
        if not same(prepared_target, work / "workspace/concurrent-build.targets") or prepared_target.read_bytes() != target.read_bytes():
            raise ValueError("Prepared concurrent target differs from the exact current fixture")
        harness["fixtures/concurrent-build.targets"] = web.sha256(target)
        for entry in expected["concurrent"]["entries"]:
            harness["prepared/" + Path(entry["source"]).name] = hashlib.sha256(prepared_source(work, expected, entry)).hexdigest()
        b_entry = next(entry for entry in expected["concurrent"]["entries"] if entry["label"] == "B")
        if (work / "workspace/b.cs").read_bytes() != prepared_source(work, expected, b_entry):
            raise ValueError("Independent B must preserve its exact prepared source and directives")
    elif expected["scenario"] == "build-failure-retry":
        if web.sha256(work / "workspace/b.cs") != harness["fixtures/web.cs"]:
            raise ValueError("Compiler regression B must preserve the ordinary fixture")
    else:
        raise ValueError("Only the concurrency control and compiler regression are expected")
    if expected["harness"] != harness:
        raise ValueError("Complete prepared harness differs from current/executed source")
    return harness


def prepared_source(work, expected, entry):
    label = entry["label"]
    if (label not in ("A", "B") or entry["revision"] != "parallel-" + label.lower()
            or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", entry["nonce"])
            or not same(entry["source"], work / "workspace" / (label.lower() + ".cs"))
            or not same(entry["marker"], work / "progress" / ("concurrent-" + label.lower() + "-ready.json"))
            or not same(entry["release"], work / "progress" / ("concurrent-" + label.lower() + "-release"))):
        raise ValueError("Each barrier must retain an exact file-specific source/revision/nonce/marker/release identity")
    directives = "\n".join((
        "#:property LifecycleConcurrentEnabled=true",
        "#:property CustomAfterMicrosoftCommonTargets=" + Path(expected["concurrent"]["target"]).as_posix(),
        "#:property LifecycleConcurrentSource=" + Path(entry["source"]).as_posix(),
        "#:property LifecycleConcurrentMarker=" + Path(entry["marker"]).as_posix(),
        "#:property LifecycleConcurrentRelease=" + Path(entry["release"]).as_posix(),
        "#:property LifecycleConcurrentNonce=" + entry["nonce"],
    )) + "\n"
    fixture = (REPO / "scripts/variant/lifecycle/fixtures/web.cs").read_bytes().replace(b"\r\n", b"\n")
    return directives.encode() + fixture.replace(b'const string revision = "initial";', ('const string revision = "' + entry["revision"] + '";').encode())


def summarize_primary(work, expected, result):
    launcher = read(work / "launcher-result.json")
    if (not result["success"] or result.get("firstFailure") or not launcher["success"]
            or launcher["editorExitCode"] != 0 or launcher["candidateSha256"] != expected["candidate"]["sha256"]):
        raise ValueError("An unexpected failed attempt cannot become passing concurrency coverage")
    if len(result["launches"]) != expected["cycles"] + 1:
        raise ValueError("Expected initial A/B followed by the bounded A Stop/retry cycles")
    launches = []
    for launch in result["launches"]:
        stopped = launch["stopRequestedAtMilliseconds"]
        timings = {label: round(launch[key] - stopped, 3) for label, key in (
            ("stopPromise", "stopPromiseResolvedAtMilliseconds"),
            ("matchingEditorTermination", "terminatedAtMilliseconds"),
            ("pidObservedGone", "pidGoneAtMilliseconds"),
            ("portRebindSucceeded", "portReusableAtMilliseconds"),
            ("outputAndQueuesClear", "outputRemovedAtMilliseconds"))}
        if any(delta < 0 for delta in timings.values()):
            raise ValueError("Lifecycle observations cannot predate their exact Stop")
        launches.append({key: launch[key] for key in ("label", "revision", "pid", "sessionId", "origin", "output", "response")} |
                        {"afterStopMilliseconds": timings})
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    diagnostics = []
    for event in trace:
        detail, message = event.get("detail", {}), event.get("detail", {}).get("message", {})
        if event["event"] == "adapter-error" or event["event"] == "dap-receive" and message.get("success") is False:
            owner = next((launch for launch in result["launches"] if launch["label"] == detail.get("label")), None)
            diagnostics.append(event | {"afterStopMilliseconds": round(event["atMilliseconds"] - owner["stopRequestedAtMilliseconds"], 3) if owner else None})
    runtime_modules = sorted({event["detail"]["message"]["body"]["module"].get("path", "") for event in trace
                              if event["event"] == "dap-receive" and event.get("detail", {}).get("message", {}).get("event") == "module"
                              and "Microsoft.NETCore.App" in event["detail"]["message"]["body"]["module"].get("path", "")})
    raw = web.raw_files(work)
    raw.update(build.output_logs(work))
    for file in [Path(expected["concurrent"]["target"]), *[Path(entry[key]) for entry in expected["concurrent"]["entries"] for key in ("marker", "release")]]:
        raw[file.relative_to(work).as_posix()] = binding(file)
    return {"name": work.name, "localArtifactDirectory": str(work), "success": True, "editorExitCode": launcher["editorExitCode"],
            "scope": result["scope"], "freshProfiles": 1, "aLaunchesAndStopCycles": expected["cycles"], "bLaunches": 1,
            "candidate": expected["candidate"], "editor": expected["editor"] | {"apiVersion": result["editorApiVersion"]},
            "sdk": expected["sdk"], "dependency": expected["dependency"], "installedExtension": result["installedExtension"],
            "installedDependency": result["installedDependency"], "installedOwnedModules": result["installedModules"],
            "harnessPinnedBeforeLaunch": expected["harness"], "checks": result["checks"], "phases": result["phases"],
            "elapsedMilliseconds": result["elapsedMilliseconds"], "launches": launches,
            "adapterAndStopDiagnostics": diagnostics,
            "observedCoreRuntimeDirectories": sorted({str(PureWindowsPath(file).parent) for file in runtime_modules}),
            "observedCoreLibraryModulePaths": [file for file in runtime_modules if file.endswith("System.Private.CoreLib.dll")],
            "rawEvidence": raw,
            "interpretation": "Actual independent-file builds are held concurrently by deliberate fixture barriers; later native launch, resource cleanup and retry are separately observed. This is not unconstrained timing or release qualification."}


def validate_concurrency(work, expected, result):
    scope = result["scope"]
    if (expected["scenario"] != "concurrent-files" or not scope["concurrentSeparateFiles"]
            or any(scope[key] for key in ("actualCompilerFailure", "actualWebProfileFailure", "actualSdkSelectionFailure", "actualNativeHostFailure", "injectedEditorRejection", "nativeAdapterFailure", "actualAdapterProcessKill", "injectedTargetRuntime"))
            or any(result[key] for key in ("failedBuildAttempts", "failedWebProfileAttempts", "failedSdkSelectionAttempts", "failedHandoffAttempts", "failedNativeHostAttempts", "cancelledBuildAttempts"))
            or result["cleanup"] or result.get("adapterLoss") or result.get("coalescedRetry")):
        raise ValueError("Expected only the deliberately held independent-file build scenario, without faults or safety cleanup")
    configured, concurrent = expected["concurrent"], result["concurrent"]
    entries = configured["entries"]
    if ([entry["label"] for entry in entries] != ["A", "B"] or concurrent["entries"] != entries
            or entries[0]["nonce"] == entries[1]["nonce"]):
        raise ValueError("Two ordered file-specific barriers must retain distinct nonce identities")
    target = Path(configured["target"])
    if snapshot(concurrent["targetSnapshot"], target) != target.read_bytes():
        raise ValueError("Executed target snapshot differs from the pinned prepared task")
    initial = next(launch for launch in result["launches"] if launch["label"] == "A-0")
    b = next(launch for launch in result["launches"] if launch["label"] == "B")
    launches = [initial, b]
    held = concurrent["beforeFirstRelease"]
    markers, identities = held["markers"], held["identities"]
    if (len(markers) != 2 or len(identities) != 2 or len(held["markerSnapshots"]) != 2
            or len(concurrent["sourceSnapshots"]) != 2 or len(concurrent["dispatch"]) != 2
            or len(concurrent["builds"]) != 2 or len(concurrent["releases"]) != 2
            or held["pidAlive"] != [True, True] or held["commandPending"] != [True, True]
            or held["operationsSettled"] != [False, False] or held["releasesAbsent"] != [True, True]
            or type(markers[0]["pid"]) is not int or type(markers[1]["pid"]) is not int
            or markers[0]["pid"] <= 0 or markers[1]["pid"] <= 0 or markers[0]["pid"] == markers[1]["pid"]):
        raise ValueError("Both distinct real SDK processes and both three-caller commands must be pending at the same pre-release checkpoint")
    held_tail = log_tail(held["log"])
    held_commands = commands(held_tail)
    initial_tail = log_tail(concurrent["log"])
    initial_commands = commands(initial_tail)
    if (concurrent["log"]["offsetCharacters"] != held["log"]["offsetCharacters"]
            or concurrent["log"]["prefixSha256"] != held["log"]["prefixSha256"]
            or not initial_tail.startswith(held_tail)):
        raise ValueError("Held and completed initial builds must retain exact prefix-preserving output slices")
    for index, (entry, launch, marker, identity) in enumerate(zip(entries, launches, markers, identities)):
        original = prepared_source(work, expected, entry)
        if (snapshot(concurrent["sourceSnapshots"][index], Path(entry["source"])) != original
                or snapshot(concurrent["builds"][index]["sourceSnapshot"], Path(entry["source"])) != original):
            raise ValueError("Each source must preserve its exact prepared directives and unique revision through initial native readiness")
        marker_bytes = snapshot(held["markerSnapshots"][index], Path(entry["marker"]))
        if json.loads(marker_bytes) != marker or Path(entry["marker"]).read_bytes() != marker_bytes:
            raise ValueError("Every readiness marker must retain its complete original bytes")
        if (marker["schema"] != 1 or marker["nonce"] != entry["nonce"] or not same(marker["source"], entry["source"])
                or not same(marker["executable"], expected["sdk"]["executable"])
                or not any(same(source, entry["source"]) for source in marker["compileInputs"].split(";"))
                or any(same(source, entries[1-index]["source"]) for source in marker["compileInputs"].split(";"))
                or not inside(work, marker["output"]) or not re.fullmatch(r"run-[A-Za-z0-9]{6}", Path(marker["output"]).name)):
            raise ValueError("The in-process SDK marker must bind its nonce, real Compile item and separate owned output")
        process_command = identity["commandLine"].replace("/", "\\").casefold()
        if (identity["processId"] != marker["pid"] or not same(identity["executablePath"], expected["sdk"]["executable"])
                or entry["source"].replace("/", "\\").casefold() not in process_command
                or str(Path(marker["output"]).resolve()).replace("/", "\\").casefold() not in process_command
                or "--output" not in process_command
                or abs((datetime.fromisoformat(identity["creationUtc"]) - datetime.fromisoformat(marker["startUtc"])).total_seconds()) > 0.001):
            raise ValueError("Live CIM PID/executable/source/output/creation identity must corroborate each in-process marker")
        dispatch = concurrent["dispatch"][index]
        if (dispatch["label"] != entry["label"] or not same(dispatch["source"], entry["source"])
                or not same(dispatch["activeSource"], entry["source"]) or dispatch["nonce"] != launch["nonce"]
                or dispatch["commandInvocations"] != 3 or not dispatch["atMilliseconds"] <= held["atMilliseconds"]):
            raise ValueError("Each three-caller dispatch must capture its own active file before the common barrier checkpoint")
        expected_rows = [args for args in held_commands if len(args) > 1 and args[0] == "build" and same(args[1], entry["source"])]
        final_rows = [args for args in initial_commands if len(args) > 1 and args[0] == "build" and same(args[1], entry["source"])]
        held_build = held["log"]["builds"][index]
        build_row = concurrent["builds"][index]
        if (held_build["source"] != entry["source"] or len(held_build["commands"]) != 1 or len(expected_rows) != 1
                or final_rows != expected_rows or held_build["commands"][0]["args"] != expected_rows[0]
                or build_row["commands"] != held_build["commands"]
                or not same(expected_rows[0][expected_rows[0].index("--output") + 1], marker["output"])
                or not same(held_build["commands"][0]["output"], marker["output"])
                or not same(build_row["output"], marker["output"]) or not same(launch["output"], marker["output"])):
            raise ValueError("All six calls must map to exactly one quoted real build per source, with stable marker/native output mapping")
        if (build_row["label"] != entry["label"] or not same(build_row["source"], entry["source"])
                or build_row["sdkPid"] != marker["pid"] or build_row["sessionId"] != launch["sessionId"]
                or build_row["commandResults"] != [True] * 3 or launch["commandResults"] != [True] * 3
                or launch["commandInvocations"] != 3 or len(build_row["capturedSessions"]) != 1
                or len(launch["capturedSessions"]) != 1
                or build_row["response"] != launch["response"] or launch["revision"] != entry["revision"]
                or launch["response"] != {"pid": launch["pid"], "nonce": launch["nonce"], "revision": entry["revision"], "value": 42}
                or not same(build_row["program"], Path(marker["output"]) / "FileApp.dll")
                or not same(launch["program"], build_row["program"])
                or not (held["atMilliseconds"] <= build_row["sdkPidGoneObservedAtMilliseconds"] <= concurrent["completedAtMilliseconds"])):
            raise ValueError("Each independent build must produce exactly one distinct owned native session and its own HTTP revision")
        early_session, stopped_session = build_row["capturedSessions"][0], launch["capturedSessions"][0]
        if (any(early_session[key] != stopped_session[key] for key in ("sessionId", "primary", "program", "output", "pid"))
                or early_session["sessionId"] != launch["sessionId"] or not early_session["primary"]
                or early_session.get("terminated", False) or not stopped_session["terminated"]
                or stopped_session["terminatedAtMilliseconds"] != launch["terminatedAtMilliseconds"]):
            raise ValueError("The live initial session snapshot and later terminated snapshot must retain the exact same ownership")
        config = build_row["configuration"]
        if (config["type"] != "coreclr" or config["request"] != "launch"
                or not same(config["program"], launch["program"]) or not same(config["__netcoredbgFileAppOutput"], launch["output"])
                or config["env"]["LIFECYCLE_TOKEN"] != launch["nonce"] or config["env"]["ASPNETCORE_URLS"] != launch["origin"]
                or not same(config["env"]["DOTNET_ROOT"], expected["sdk"]["root"])):
            raise ValueError("Each captured configuration must preserve its native source-specific program/output/environment")
        artifacts = build_row["artifacts"]
        if len(artifacts) != 2:
            raise ValueError("Initial DLL/PDB metadata must be sampled before cleanup")
        for artifact, name in zip(artifacts, ("FileApp.dll", "FileApp.pdb")):
            if (not same(artifact["path"], Path(marker["output"]) / name) or artifact["size"] <= 0
                    or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])):
                raise ValueError("Each session's generated artifact must retain positive size and exact path/hash")
        profile = json.loads(snapshot(build_row["profileSnapshot"], Path(entry["source"]).with_suffix(".run.json")))
        if profile != {"profiles": {"LifecycleHttp": {"commandName": "Project", "applicationUrl": launch["origin"], "launchBrowser": False,
                       "environmentVariables": {"LIFECYCLE_TOKEN": launch["nonce"], "ASPNETCORE_ENVIRONMENT": "Development"}}}}:
            raise ValueError("Each native launch must read its own ordinary HTTP profile and fresh ownership token")
        release = concurrent["releases"][index]
        release_bytes = snapshot(release["snapshot"], Path(entry["release"]))
        if (release["label"] != entry["label"] or release["pid"] != marker["pid"] or release["nonce"] != entry["nonce"]
                or release["safetyCleanup"] or release_bytes != (entry["nonce"] + "\n").encode()
                or Path(entry["release"]).read_bytes() != release_bytes
                or not (held["atMilliseconds"] <= release["atMilliseconds"] <= launch["startedAtMilliseconds"])):
            raise ValueError("Only the exact captured live SDK nonce barrier may be released after both are held, before its native launch")
    if (not concurrent["dispatch"][0]["atMilliseconds"] <= concurrent["dispatch"][1]["atMilliseconds"]
            or not concurrent["releases"][0]["atMilliseconds"] <= concurrent["releases"][1]["atMilliseconds"]
            or any(initial[key] == b[key] for key in ("output", "sessionId", "pid", "nonce", "revision"))
            or not len({Path(marker["output"]).parent.name for marker in markers}) == 2):
        raise ValueError("A-then-B dispatch, held-before-release ordering and distinct file/output/session/PID/token/revision identities must be preserved")
    for key, prefix, count in (("buildCompletedPhaseDiagnostics", "Phase completed: Building file-based app", 2),
                               ("completedPhaseDiagnostics", "Phase completed: Starting netcoredbg", 2),
                               ("failedPhaseDiagnostics", "Phase failed: Building file-based app", 0),
                               ("cancelledPhaseDiagnostics", "Phase cancelled: Building file-based app", 0)):
        projection = [line for line in initial_tail.splitlines() if line.startswith(prefix)]
        if concurrent["log"][key] != projection or len(projection) != count:
            raise ValueError("Initial exact log slice must retain two successful builds/handoffs and no failed/cancelled build")
    retry = concurrent["retry"]
    retried = next(launch for launch in result["launches"] if launch["sessionId"] == retry["sessionId"])
    if (retry["commandInvocations"] != 3 or retry["commandResults"] != [True] * 3
            or retried["commandInvocations"] != 3 or retried["commandResults"] != [True] * 3 or len(retried["capturedSessions"]) != 1
            or not all(retry[key] for key in ("disabledBarrier", "freshOutput", "freshSession", "freshToken"))
            or any(retry[key] != retried[key] for key in ("label", "source", "revision", "nonce", "pid", "sessionId", "output", "response"))
            or retry["output"] == initial["output"] or retry["sessionId"] == initial["sessionId"] or retry["nonce"] == initial["nonce"]
            or max(initial[key] for key in ("terminatedAtMilliseconds", "pidGoneAtMilliseconds", "portReusableAtMilliseconds", "outputRemovedAtMilliseconds")) > retried["startedAtMilliseconds"]):
        raise ValueError("After exact A Stop, three dirty retry callers must share one fresh source-specific native session/output/token")
    original = prepared_source(work, expected, entries[0]).replace(b"\r\n", b"\n")
    corrected = snapshot(retry["sourceSnapshot"], Path(initial["source"]))
    expected_corrected = original.replace(b"#:property LifecycleConcurrentEnabled=true", b"#:property LifecycleConcurrentEnabled=false", 1).replace(
        ('const string revision = "' + entries[0]["revision"] + '";').encode(), ('const string revision = "' + retry["revision"] + '";').encode(), 1)
    if corrected.replace(b"\r\n", b"\n") != expected_corrected:
        raise ValueError("Dirty A retry may only disable its one-shot barrier and change its revision, allowing editor newline normalization")
    profile = json.loads(snapshot(retry["profileSnapshot"], Path(initial["source"]).with_suffix(".run.json")))
    if profile != {"profiles": {"LifecycleHttp": {"commandName": "Project", "applicationUrl": retried["origin"], "launchBrowser": False,
                   "environmentVariables": {"LIFECYCLE_TOKEN": retried["nonce"], "ASPNETCORE_ENVIRONMENT": "Development"}}}}:
        raise ValueError("A retry must preserve its normal HTTP profile with a fresh token")
    history.prior.previous.validate_build(retry["log"], Path(initial["source"]), retry["output"], True)
    checkpoint = retry["bCheckpoint"]
    if (any(checkpoint[key] != b[key] for key in ("sessionId", "pid", "response", "output"))
            or checkpoint["sourceSnapshot"] != concurrent["builds"][1]["sourceSnapshot"]
            or checkpoint["profileSnapshot"] != concurrent["builds"][1]["profileSnapshot"]):
        raise ValueError("B must preserve its exact live session/response/output and byte-identical source/profile after A's dirty retry")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    projections = (("concurrent-file-command-dispatched", concurrent["dispatch"]),
                   ("concurrent-builds-held-before-first-release", [held]),
                   ("concurrent-build-barrier-released", concurrent["releases"]),
                   ("concurrent-files-dirty-retry-confirmed", [retry]))
    for event_name, expected_rows in projections:
        if [event["detail"] for event in trace if event["event"] == event_name] != expected_rows:
            raise ValueError("Raw trace must bind all dispatch/barrier/release/retry evidence: " + event_name)
    initial_confirmation = {key: value for key, value in concurrent.items() if key != "retry"}
    if [event["detail"] for event in trace if event["event"] == "concurrent-files-confirmed"] != [initial_confirmation]:
        raise ValueError("Initial completed concurrency proof must retain its exact pre-retry trace snapshot")
    for launch in result["launches"]:
        events = [event for event in trace if event.get("detail", {}).get("label") == launch["label"]]
        native = [event["detail"]["message"] for event in events if event["event"] == "dap-send"
                  and event["detail"]["message"].get("command") == "launch"]
        if len(native) != 1:
            raise ValueError("Every captured session must have one actual native launch request")
        config = native[0]["arguments"]
        if (not same(config["program"], launch["program"]) or not same(config["__netcoredbgFileAppOutput"], launch["output"])
                or config["env"]["LIFECYCLE_TOKEN"] != launch["nonce"] or config["env"]["ASPNETCORE_URLS"] != launch["origin"]
                or not same(config["cwd"], Path(launch["source"]).parent)
                or not any(event["event"] == "http-ready" and event["detail"] == {"label": launch["label"], "origin": launch["origin"], "body": launch["response"]} for event in events)):
            raise ValueError("Native launch and HTTP ownership must map back to the exact captured file/output/session")
    b_after_retry = [event for event in trace if event["event"] == "unrelated-preserved" and event["detail"] == {"label": "B", "sessionId": b["sessionId"], "pid": b["pid"]}
                     and retried["startedAtMilliseconds"] <= event["atMilliseconds"] < retried["stopRequestedAtMilliseconds"]]
    if not b_after_retry:
        raise ValueError("B preservation requires a distinct raw-trace checkpoint after A's successful retry")
    return {"evidence": concurrent, "bPreservedAfterRetry": b_after_retry,
            "validatedOutputLogs": build.output_logs(work, (held["log"], concurrent["log"], retry["log"])),
            "mechanism": "Two nonce-specific inline tasks deliberately hold separate real SDK builds before CoreCompile. Both live process identities and pending command groups are observed before either release. Native sessions and same-file coalescing are then checked independently.",
            "sourceObservation": "Exact initial prepared source bytes and snapshots are bound; dirty retry permits only barrier disablement, revision change and editor CRLF/LF normalization.",
            "limits": "Barrier-induced overlap proves independent in-flight preparation under this fixture, not unconstrained production timing, throughput, continuous B liveness or release qualification."}


def validate_failure(work):
    result, launcher = read(work / "result.json"), read(work / "launcher-result.json")
    if result["success"] or not result.get("firstFailure") or launcher["success"]:
        raise ValueError("An unexpected failed attempt must retain its original failure")
    raw = web.raw_files(work)
    raw.update(build.output_logs(work))
    for entry in result["expected"].get("concurrent", {}).get("entries", []):
        for key in ("marker", "release"):
            file = Path(entry[key])
            if file.is_file():
                raw[file.relative_to(work).as_posix()] = binding(file)
    return {"directory": str(work), "result": result, "launcher": launcher, "rawEvidence": raw,
            "interpretation": "Separate unexpected attempt; not passing independent-file concurrency coverage."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--compiler-regression", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--earlier-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--failed-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    work = args.run.resolve()
    expected, result = read(work / "expected.json"), read(work / "result.json")
    summary = summarize_primary(work, expected, result)
    identity = validate_identity(work, expected, result)
    concurrency = validate_concurrency(work, expected, result)
    regression = args.compiler_regression.resolve()
    regression_expected, regression_result = read(regression / "expected.json"), read(regression / "result.json")
    regression_summary = build.summarize_run(regression, True)
    regression_identity = validate_identity(regression, regression_expected, regression_result)
    earlier = []
    for directory in args.earlier_runs:
        previous_work = directory.resolve()
        previous_expected, previous_result = read(previous_work / "expected.json"), read(previous_work / "result.json")
        earlier.append({"run": summarize_primary(previous_work, previous_expected, previous_result),
                        "identity": validate_identity(previous_work, previous_expected, previous_result, historical=True),
                        "concurrentFiles": validate_concurrency(previous_work, previous_expected, previous_result),
                        "interpretation": "Earlier passing editor control with its original driver. A later one-line failure-safety drain change includes any underlying command still pending after a callback failure; this earlier pass is neither a failed run nor a current-harness control."})
    value = {"schema": 1, "kind": "installed independent-file concurrent SDK builds and same-file retry",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18", "qualification": False, "productChange": False,
             "primaryRun": summary, "primaryIdentity": identity, "concurrentFiles": concurrency,
             "compilerRegression": regression_summary, "compilerRegressionIdentity": regression_identity,
             "verification": validate_units(args.tests.resolve()),
             "earlierPassingRuns": earlier,
             "unexpectedFailures": [validate_failure(directory.resolve()) for directory in args.failed_runs],
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), PREVIOUS, history.PREVIOUS, history.prior.PREVIOUS, history.prior.previous.BUILD_COLLECTOR, build.SHARED)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
