"""Validate retained Windows long-output allocation evidence without reruns."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
BASE = "9caef5773991a8bad468d7588297ade1f6585857"
MODULES = REPO / "scripts/variant/file-based-apps"
PROFILE_COLLECTOR = REPO / "docs/research/web-profile-failure-retry-2026-11-07/summarize.py"
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profile = load_module("late_web_profile_summary", PROFILE_COLLECTOR)
web, build = profile.web, profile.build
read, same, inside = profile.read, profile.same, profile.inside
digest = lambda data: hashlib.sha256(data).hexdigest()


def binding(file):
    return {"sha256": web.sha256(file), "bytes": file.stat().st_size}


def original_module(name):
    return subprocess.check_output(["git", "show", f"{BASE}:scripts/variant/file-based-apps/{name}"], cwd=REPO)


def validate_identity(work, historical=False):
    expected, result = read(work / "expected.json"), read(work / "result.json")
    candidate = expected["candidate"]
    if (result["expected"] != expected or not candidate["localOnly"] or candidate["published"]
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
        raise ValueError("Expected an exact local native Windows ARM64 installed candidate")
    if not historical and candidate["sourceCommit"] != BASE:
        raise ValueError("Final candidate must record the merged PR36 source base")
    identity = {key: candidate[key] for key in ("baseVsixSha256", "sourceCommit", "target", "ownedModules")}
    if digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()) != candidate["buildId"]:
        raise ValueError("Candidate content build identity differs")
    for key in ("editor", "sdk"):
        if web.sha256(Path(expected[key]["executable"])) != expected[key]["sha256"]:
            raise ValueError("Pinned native executable differs: " + key)
    if web.sha256(Path(expected["dependency"]["path"])) != expected["dependency"]["sha256"]:
        raise ValueError("Pinned runtime dependency differs")
    if (not same(candidate["path"], work / "local-lifecycle.vsix")
            or web.sha256(Path(candidate["path"])) != candidate["sha256"]
            or result["installedModules"] != candidate["ownedModules"]):
        raise ValueError("Candidate or loaded product identity differs")
    harness = {name.removeprefix("scripts/variant/lifecycle/"): web.sha256(REPO / name) for name in web.HARNESS[:5]}
    if expected["harness"] != harness:
        raise ValueError("Prepared harness must match unchanged current harness bytes")
    for name in ("driver.cjs", "extension-test.cjs"):
        if web.sha256(work / "driver" / name) != harness[name]:
            raise ValueError("Executed driver differs: " + name)
    if web.sha256(work / "workspace/b.cs") != harness["fixtures/web.cs"]:
        raise ValueError("Independent B source must remain the pinned fixture")
    installed = Path(result["installedExtension"]["path"])
    if not inside(work / "extensions", installed):
        raise ValueError("Target must be normally installed in this isolated profile")
    modules = {}
    with zipfile.ZipFile(candidate["path"]) as archive:
        metadata = json.loads(archive.read("extension/package.json"))
        if (metadata["netcoredbgBuild"]["lifecycleBuildId"] != candidate["buildId"]
                or metadata["netcoredbgBuild"]["lifecycleSourceCommit"] != candidate["sourceCommit"]):
            raise ValueError("Packaged candidate identity differs")
        for name, expected_hash in candidate["ownedModules"].items():
            data = archive.read("extension/.netcoredbg/" + name)
            baseline = original_module(name)
            if (digest(data) != expected_hash or web.sha256(installed / ".netcoredbg" / name) != expected_hash):
                raise ValueError("ZIP and installed module bytes differ: " + name)
            if historical:
                if data.replace(b"\r\n", b"\n") != baseline.replace(b"\r\n", b"\n"):
                    raise ValueError("Historical product differs from the pre-repair Git base")
            else:
                if (MODULES / name).read_bytes() != data:
                    raise ValueError("Final installed/ZIP module differs from current source: " + name)
                if name != "runtime.cjs" and data.replace(b"\r\n", b"\n") != baseline.replace(b"\r\n", b"\n"):
                    raise ValueError("This repair must leave entry/classification/Web/recovery modules unchanged")
            modules[name] = {"sha256": expected_hash, "bytes": len(data),
                             "matchesBaseIgnoringCheckoutNewlines": data.replace(b"\r\n", b"\n") == baseline.replace(b"\r\n", b"\n")}
    if not historical and modules["runtime.cjs"]["matchesBaseIgnoringCheckoutNewlines"]:
        raise ValueError("Final candidate must contain the changed output allocator")
    return {"directory": str(work), "historicalPreRepair": historical, "gitBase": BASE,
            "candidate": candidate, "modules": modules}, expected, result


def validate_baseline(work):
    identity, expected, result = validate_identity(work, True)
    launcher = read(work / "launcher-result.json")
    if (expected["scenario"] != "web-profile-failure-retry" or result["success"]
            or not result.get("firstFailure") or launcher["success"] or launcher["editorExitCode"] != 1
            or result["failedWebProfileAttempts"] or result["failedBuildAttempts"]
            or len(result["launches"]) != 1 or result["launches"][0]["label"] != "A-0"
            or result["launches"][0]["commandResults"] != [False]
            or result["launches"][0]["capturedSessions"] or launcher.get("fixtureShutdown")):
        raise ValueError("Baseline must remain the original initial-launch pre-build failure")
    logs = sorted((work / "profile/logs").glob("**/*C# File Debugging.log"))
    if len(logs) != 1:
        raise ValueError("Expected one baseline output logger")
    text = logs[0].read_bytes().decode("utf-8")
    errors = [line for line in text.splitlines() if "ENAMETOOLONG" in line and "mkdtemp" in line]
    phases = [line for line in text.splitlines() if line.startswith("Phase failed: Preparing build output")]
    if (len(errors) != 1 or len(phases) != 1 or profile.build_commands(text, work / "workspace/a.cs")
            or "Phase started: Building file-based app" in text or profile.DIAGNOSTIC in text):
        raise ValueError("Baseline must fail output allocation before SDK build or intended Web-profile failure")
    match = re.search(r"mkdtemp '(.+)'", errors[0])
    if not match or len(match[1]) != 248 or not match[1].endswith("run-XXXXXX"):
        raise ValueError("Retain the exact observed 248-character Windows template")
    return {"identity": identity, "result": result, "launcher": launcher,
            "observedError": errors, "observedPhase": phases,
            "failedTemplate": match[1], "templateCharacters": len(match[1]),
            "outputLog": {str(logs[0]): binding(logs[0])}, "rawEvidence": web.raw_files(work)}


def validate_probes(directory):
    manifest = read(directory / "manifest.json")
    if manifest["schema"] != 1 or "Post-run" not in manifest["timing"]:
        raise ValueError("Native probe mirror must state its post-run provenance")
    expected_names = {"probe.cjs", "recovery-probe.cjs", "result-node.json", "result-editor.json", "result-recovery-node.json", "result-recovery-editor.json"}
    if {row["name"] for row in manifest["files"]} != expected_names:
        raise ValueError("Incomplete native probe mirror")
    for row in manifest["files"]:
        copied = directory / row["name"]
        original = Path(row["originalPath"])
        if (not same(copied, row["copiedPath"]) or binding(copied) != {"sha256": row["sha256"], "bytes": row["bytes"]}
                or copied.read_bytes() != original.read_bytes()):
            raise ValueError("Native probe mirror differs from original executed evidence")
        if row["name"].endswith(".cjs") and (HERE / row["name"]).read_bytes() != copied.read_bytes():
            raise ValueError("Committed native source mirror differs from executed script")
    records = []
    for runtime in ("node", "editor"):
        native = read(directory / f"result-{runtime}.json")
        info = native["node"]
        if info["arch"] != "arm64" or info["platform"] != "win32":
            raise ValueError("Expected a native ARM64 Windows filesystem observation")
        cases = {row["variant"]: row for row in native["cases"]}
        if (set(cases) != {"bare-mkdtemp", "namespaced-mkdtemp", "bare-mkdir", "namespaced-mkdir"}
                or cases["bare-mkdtemp"]["error"]["code"] != "ENAMETOOLONG"
                or cases["bare-mkdtemp"].get("created") or not native["ownedRootRemoved"] or native["cleanupErrors"]
                or native["originalFailure"]["templateCharacters"] != 248
                or native["originalFailure"]["parentCharacters"] != 237):
            raise ValueError("Native filesystem counterexample or exact-owned cleanup differs")
        original_log = Path(native["originalFailure"]["sourceLog"])
        if web.sha256(original_log) != native["originalFailure"]["sha256"]:
            raise ValueError("Probe's original failure input log differs")
        for name in ("namespaced-mkdtemp", "bare-mkdir", "namespaced-mkdir"):
            row = cases[name]
            if (row["expectedOutputCharacters"] != 248 or not all(row[key] for key in ("created", "nameEligible", "fileReadback", "fileRemoved", "directoryRemoved"))):
                raise ValueError("Incomplete native directory/file I/O observation")
        if (cases["namespaced-mkdtemp"]["currentRuntimeInsideDirectory"] is not False
                or cases["bare-mkdir"]["currentRuntimeInsideDirectory"] is not True
                or cases["namespaced-mkdir"]["currentRuntimeInsideDirectory"] is not True):
            raise ValueError("Retain the ordinary-path ownership guard comparison")
        recovery = read(directory / f"result-recovery-{runtime}.json")
        if (not recovery["success"] or not all(recovery[key] for key in ("published", "sourceAbsentAfterPublication", "readyEmpty", "stagingEmpty", "guardsPreserved"))
                or recovery["recovery"] != {"scanned": 1, "attempted": 1, "removed": 1}
                or len(recovery["source"]) != 248
                or not re.search(r"[\\/]([0-9a-f]{24})[\\/]run-[A-Za-z0-9]{6}$", recovery["source"])
                or Path(recovery["source"]).exists()):
            raise ValueError("The existing v1 recovery helper must remove only the exact terminal long output")
        executable = Path(recovery["runtime"]["executable"])
        if not same(info["executable"], executable) or web.sha256(executable) != recovery["runtime"]["sha256"]:
            raise ValueError("Native probe runtime executable differs")
        for item in recovery["inputs"].values():
            if web.sha256(Path(item["path"])) != item["sha256"]:
                raise ValueError("Native recovery probe source/input differs")
        if recovery["inputs"]["recovery"]["sha256"] != web.sha256(MODULES / "recovery.cjs"):
            raise ValueError("Recovery helper must remain unchanged")
        if len(recovery["guards"]) != 2:
            raise ValueError("Expected unmarked and external native recovery guards")
        for guard in recovery["guards"]:
            if web.sha256(Path(guard["path"])) != guard["sha256"]:
                raise ValueError("Native recovery guard no longer matches")
        if info["version"] != recovery["runtime"]["version"]:
            raise ValueError("Filesystem and recovery runtimes differ")
        if runtime == "editor" and (info["version"] != "v24.21.0" or info["versions"]["electron"] != "43.7.7" or recovery["command"]["electronRunAsNode"] != "1"):
            raise ValueError("Expected the pinned editor's embedded Node CLI mode")
        records.append({"filesystem": native, "terminalRecovery": recovery})
    return {"directory": str(directory), "manifest": manifest, "manifestFile": binding(directory / "manifest.json"),
            "sourceMirror": {name: binding(HERE / name) for name in ("probe.cjs", "recovery-probe.cjs")},
            "records": records,
            "scope": "Native filesystem and separate recovery controllers in the same process per runtime; no editor-host or SDK/DAP qualification"}


def node_counts(text):
    counts = {key: int(value) for key, value in re.findall(
        r"(?m)^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", text)}
    if set(counts) != {"tests", "pass", "fail", "cancelled", "skipped", "todo"}:
        raise ValueError("Incomplete Node TAP counts")
    return counts


def validate_units(directory):
    metadata = read(directory / "verification.json")
    if metadata.get("baseCommit", metadata.get("baselineCommit")) != BASE:
        raise ValueError("Verification must record merged PR36 as the pre-repair base")
    records = metadata["records"]
    if len(records) != 4 or {record["label"] for record in records} != {"before-focused", "after-focused", "after-full", "python-full"}:
        raise ValueError("Expected old/new native functional cases, final full Node and Python checks")
    rows, before, after, focused = [], None, None, None
    for record in records:
        log = directory / record["log"]
        if web.sha256(log) != record["logSha256"]:
            raise ValueError("Verification raw log differs")
        text = log.read_text(encoding="utf-8-sig")
        if "--test" in record["command"]:
            if "--unhandled-rejections=strict" not in record["command"] or "--test-force-exit" in record["command"]:
                raise ValueError("Node verification must use strict natural exit")
            counts = node_counts(text)
            if any(counts[key] for key in ("cancelled", "skipped", "todo")):
                raise ValueError("No verification cases may be skipped or cancelled")
            if record["exitCode"] == 1:
                if (before is not None or counts != {"tests": 1, "pass": 0, "fail": 1, "cancelled": 0, "skipped": 0, "todo": 0}
                        or "--test-name-pattern" not in record["command"]
                        or "Windows long storage allocates, launches and journals terminal output without namespace paths" not in text
                        or "ENAMETOOLONG" not in text):
                    raise ValueError("The same-final-test baseline must reproduce the real long allocation failure")
                before = record
            elif record["exitCode"] == 0 and record["label"] == "after-focused":
                if (focused is not None or counts != {"tests": 1, "pass": 1, "fail": 0, "cancelled": 0, "skipped": 0, "todo": 0}
                        or "--test-name-pattern" not in record["command"]):
                    raise ValueError("The final focused native case must pass once")
                focused = record
            elif record["exitCode"] == 0:
                if (after is not None or counts["tests"] != 227 or counts["pass"] != 227 or counts["fail"]):
                    raise ValueError("Expected the complete final 227-case strict Node suite")
                after = record
            else:
                raise ValueError("Unexpected Node verification outcome")
        else:
            if record["exitCode"] != 0:
                raise ValueError("Python helpers failed")
            match = re.findall(r"Ran (\d+) tests? in", text)
            if match != ["39"] or not re.search(r"(?m)^OK\s*$", text):
                raise ValueError("Expected all 39 Python helpers")
            counts = {"tests": 39, "result": "OK"}
        rows.append({"record": record, "counts": counts, "rawLog": binding(log)})
    if before is None or after is None or focused is None:
        raise ValueError("Missing old/final-focused/full Node verification")
    for name, item in metadata["sources"].items():
        file = Path(name)
        if web.sha256(file) != item["sha256"] or file.stat().st_size != item.get("size", item.get("bytes")):
            raise ValueError("Verified source differs: " + name)
    old_test = next(Path(value) for value in before["command"] if value.endswith("test-runtime.cjs"))
    if old_test.read_bytes() != (MODULES / "test-runtime.cjs").read_bytes():
        raise ValueError("Before and after must execute byte-identical final functional tests")
    if (old_test.parent / "runtime.cjs").read_bytes().replace(b"\r\n", b"\n") != original_module("runtime.cjs").replace(b"\r\n", b"\n"):
        raise ValueError("Before functional case must execute the original Git-base runtime")
    for name, item in metadata["preliminaryBindings"].items():
        file = directory / name
        if web.sha256(file) != item["sha256"] or file.stat().st_size != item["size"]:
            raise ValueError("Preparatory raw/reconstructed source binding differs")
    if "Post-run reconstructions" not in metadata["preliminaryRuns"]["sourceProvenance"]:
        raise ValueError("Preparatory source copies must not be relabelled as pre-run inputs")
    initial = (directory / "first-focused.log").read_text(encoding="utf-8-sig")
    corrected = (directory / "focused-fixed.log").read_text(encoding="utf-8-sig")
    if (node_counts(initial) != {"tests": 10, "pass": 9, "fail": 1, "cancelled": 0, "skipped": 0, "todo": 0}
            or "assert(!fs.existsSync(queue) || fs.readdirSync(queue).length === 0)" not in initial
            or node_counts(corrected) != {"tests": 10, "pass": 10, "fail": 0, "cancelled": 0, "skipped": 0, "todo": 0}):
        raise ValueError("Retain the distinct preparatory queue-sampling failure and corrected focused run")
    return {"directory": str(directory), "manifest": metadata, "manifestFile": binding(directory / "verification.json"),
            "runs": rows, "preparatoryFocused": {
                "first": binding(directory / "first-focused.log"), "corrected": binding(directory / "focused-fixed.log"),
                "sourceAndSetupProvenance": metadata["preliminaryRuns"],
                "reconstructionRunners": {name: binding(directory / name) for name in ("verify.py", "verify-initial.py")},
                "scope": "The first focused run failed a queue-empty assertion; final test waits for disposal drain. Preliminary copies are post-run reconstructions, not pre-run snapshots or identical final test bytes."}}


def validate_long_run(work):
    identity, expected, result = validate_identity(work)
    if expected["scenario"] != "web-profile-failure-retry":
        raise ValueError("The long installed control must exercise the late Web-profile scenario")
    summary = web.summarize_run(work, REPO, require_current_harness=True)
    contract = profile.validate_web_failure(work, expected, result)
    paths = [launch["output"] for launch in result["launches"]]
    paths += [attempt["output"] for attempt in result["failedWebProfileAttempts"]]
    if len(paths) != 5 or len(set(paths)) != 5:
        raise ValueError("Expected four captured successful outputs and one distinct Web-rejected output")
    logs = sorted((work / "profile/logs").glob("**/*C# File Debugging.log"))
    text = "\n".join(file.read_bytes().decode("utf-8") for file in logs)
    prefix = "Created Windows file-app output after mkdtemp ENAMETOOLONG: "
    fallback_lines = [line for line in text.splitlines() if line.startswith(prefix)]
    if len(fallback_lines) != len(paths):
        raise ValueError("Every long allocation must log exactly one confirmed fallback")
    for value in paths:
        output = Path(value)
        if (len(value) != 248 or value.startswith("\\\\?\\") or Path(value).exists()
                or not inside(work, output)
                or not re.fullmatch(r"run-[A-Za-z0-9]{6}", output.name)
                or not re.fullmatch(r"[0-9a-f]{24}", output.parent.name)
                or sum(same(line[len(prefix):], value) for line in fallback_lines) != 1):
            raise ValueError("Long output must remain ordinary, eligible, exactly logged and absent after cleanup")
        base = output.parent.parent
        for name in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1"):
            directory = base / name
            if directory.exists() and any(directory.iterdir()):
                raise ValueError("Both terminal queues must remain empty after the final control")
    return {"lifecycle": summary, "identity": identity, "webProfileContract": contract,
            "longAllocation": {"observedOutputCharacters": 248, "outputs": paths, "fallbackLines": fallback_lines,
                               "boundOutputLogs": {str(file): binding(file) for file in logs},
                               "scope": "Confirmed fallback under this exact custom user-data path; not an arbitrary Windows length guarantee"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--compiler-regression", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--native-probes", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    regression = args.compiler_regression.resolve()
    regression_identity, _, _ = validate_identity(regression)
    short_logs = sorted((regression / "profile/logs").glob("**/*C# File Debugging.log"))
    if not short_logs or any("Created Windows file-app output after mkdtemp ENAMETOOLONG:" in file.read_bytes().decode("utf-8") for file in short_logs):
        raise ValueError("The short regression must preserve normal allocation without fallback")
    value = {"schema": 1, "kind": "Windows long file-app output allocation",
             "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18", "qualification": False,
             "longInstalledControl": validate_long_run(args.run.resolve()),
             "shortCompilerRegression": build.summarize_run(regression, True),
             "shortCompilerIdentity": regression_identity,
             "shortAllocationFallbackCount": 0,
             "originalInstalledFailure": validate_baseline(args.baseline.resolve()),
             "nativeFilesystemAndRecovery": validate_probes(args.native_probes.resolve()),
             "verification": validate_units(args.tests.resolve()),
             "collectors": {str(file.relative_to(REPO)): binding(file) for file in (Path(__file__), PROFILE_COLLECTOR, profile.BUILD_COLLECTOR, build.SHARED)},
             "limits": ["Measured 248-character output names under pinned Windows ARM64 runtimes; no universal Windows threshold or arbitrary path support claim.",
                        "Native probes use filesystem operations and separate controllers in the same process, not editor/SDK/DAP or cold-host qualification.",
                        "Installed controls invoke the command API, not physical F5/menu or macOS.",
                        "No UNC/network, certificate trust/cancellation, active-host-loss, descendant-process or release qualification is added."]}
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
