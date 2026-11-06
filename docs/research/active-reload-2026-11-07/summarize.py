"""Validate actual Reload observations without relabelling failure cleanup as success."""
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
MODULES = REPO / "scripts/variant/file-based-apps"
HARNESS = REPO / "scripts/variant/lifecycle/active-reload"


def sha(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def read(file):
    return json.loads(file.read_text(encoding="utf-8-sig"))


def binding(file):
    return {"sha256": sha(file), "bytes": file.stat().st_size}


def retained_files(work):
    # Deliberately avoid editor cache, extension binaries and live named pipes.
    files = list(work.glob("*.*"))
    for child in ("driver", "logs", "executed-harness"):
        files.extend((work / child).rglob("*"))
    files.extend((work / "profile/logs").rglob("*.log"))
    files.append(work / "profile/User/settings.json")
    return {file.relative_to(work).as_posix(): binding(file)
            for file in sorted(set(files)) if file.is_file()}


def validate_empty(root):
    names = ("prototype-empty", "prototype-empty-02", "prototype-empty-03")
    values = []
    for index, name in enumerate(names):
        work = root / name
        runner = read(work / "launcher-result.json")
        if bool(runner["success"]) != (index == 2):
            raise ValueError("Empty prototype outcome changed: " + name)
        if ("--extensionTestsPath" in runner["args"]) != (index < 2):
            raise ValueError("Prototype activation mode differs")
        if index == 0 and ("Host is not exact isolated editor descendant" not in runner["error"] or not runner["closedOwnedEditor"]):
            raise ValueError("Retain the initial identity-check failure")
        if index == 1:
            if "Editor exited before host 2" not in runner["error"] or (work / "host-2.json").exists():
                raise ValueError("Retain the CLI-test-mode termination")
            logs = "\n".join(f.read_text(encoding="utf-8-sig") for f in (work / "profile/logs").rglob("exthost.log"))
            host = read(work / "host-1.json")["host"]
            if f"Extension host with pid {host} exiting with code 0" not in logs:
                raise ValueError("Missing the actual first-host zero exit log")
        if index == 2:
            result = read(work / "result.json")
            first, second = (read(work / f"host-{n}.json")["host"] for n in (1, 2))
            if not result["success"] or first == second or result["phase"]["firstHost"] != first or result["secondHost"] != second or runner["exitCode"] != 0:
                raise ValueError("The empty normal-activation Reload must replace its host")
            for n, host in ((1, first), (2, second)):
                lineage = read(work / f"lineage-{n}.json")
                ack = read(work / f"ack-{n}.json")
                if not lineage["verified"] or lineage["editorPid"] != runner["editorPid"] or lineage["lineage"][0]["ProcessId"] != host or lineage["lineage"][-1]["ProcessId"] != runner["editorPid"] or ack["host"] != host or ack["editorPid"] != runner["editorPid"]:
                    raise ValueError("Empty Reload requires two native lineages to the same app")
        values.append({"name": name, "runner": runner, "rawFiles": retained_files(work)})
    return values


def validate_product_archive(directory):
    manifest = read(directory / "archive.json")
    for name, item in manifest.items():
        file = directory / name
        if sha(file) != item["sha256"] or file.stat().st_size != item["size"]:
            raise ValueError("Intermediate source/test archive changed: " + name)
    return {"directory": str(directory), "manifest": manifest, "manifestFile": binding(directory / "archive.json")}


def validate_unit_evidence(directory, module_archive=None):
    combined = directory / "verification.json"
    if combined.exists():
        original = read(combined)
        python_records = [r for r in original["records"] if r["label"] == "python-full"]
        if len(python_records) != 1:
            raise ValueError("Expected one separately identified Python helper run")
        node = original | {"records": [r for r in original["records"] if r["label"] != "python-full"]}
        python = python_records[0]
        metadata_names = ("verification.json",)
    else:
        node = read(directory / "node-verification.json")
        python = read(directory / "python-verification.json")
        metadata_names = ("node-verification.json", "python-verification.json")
    rows = []
    for record in node["records"]:
        file = directory / record["log"]
        if sha(file) != record["logSha256"] or "--unhandled-rejections=strict" not in record["command"] or "--test" not in record["command"] or "--test-force-exit" in record["command"]:
            raise ValueError("Strict natural-exit Node evidence changed")
        counts = {key: int(value) for key, value in re.findall(r"(?m)^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", file.read_text(encoding="utf-8-sig"))}
        if set(counts) != {"tests", "pass", "fail", "cancelled", "skipped", "todo"} or any(counts[k] for k in ("cancelled", "skipped", "todo")):
            raise ValueError("Incomplete Node counts or hidden skipped/cancelled work")
        before = record["label"].startswith("before")
        if record["exitCode"] != (1 if before else 0) or bool(counts["fail"]) != before or counts["tests"] != counts["pass"] + counts["fail"]:
            raise ValueError("Focused before/final Node outcomes differ")
        rows.append({"record": record, "counts": counts, "rawLog": binding(file)})
    for name, item in node["sources"].items():
        original = Path(name)
        candidates = [original]
        if module_archive is not None:
            candidates.append(module_archive / "file-based-apps" / original.name)
        if any(p.is_file() and sha(p) == item["sha256"] and p.stat().st_size == item["size"] for p in candidates):
            continue
        if "baseline" in original.parts and original.name in ("entry.cjs", "runtime.cjs", "recovery.cjs"):
            data = subprocess.check_output(["git", "show", f"{node['baselineCommit']}:scripts/variant/file-based-apps/{original.name}"], cwd=REPO)
            if hashlib.sha256(data).hexdigest() == item["sha256"] and len(data) == item["size"]:
                continue
        raise ValueError("Executed unit source no longer matches a retained snapshot: " + name)
    identical_tests = {}
    for name in ("test-entry.cjs", "test-runtime.cjs"):
        values = {item["sha256"] for file, item in node["sources"].items() if Path(file).name == name}
        if len(values) != 1:
            raise ValueError("Before and after runs must execute identical final test bytes")
        identical_tests[name] = next(iter(values))
    snapshots = {}
    if combined.exists():
        for file in sorted((directory / "file-based-apps").rglob("*")):
            if file.is_file():
                name = file.relative_to(directory / "file-based-apps")
                if sha(file) != sha(MODULES / name):
                    raise ValueError("Retained final source snapshot differs from current source")
                snapshots[name.as_posix()] = binding(file)
        bridge = Path(node["baseline"]) / "file-based-apps"
        for name in ("entry.cjs", "runtime.cjs", "recovery.cjs"):
            if sha(directory / "before-modules" / name) != sha(bridge / name):
                raise ValueError("Focused fallback baseline must execute the preserved bridge-only product")
    pylog = directory / python["log"]
    text = pylog.read_text(encoding="utf-8-sig")
    matches = re.findall(r"Ran (\d+) tests? in", text)
    if python["exitCode"] != 0 or sha(pylog) != python["logSha256"] or len(matches) != 1 or not re.search(r"(?m)^OK\s*$", text):
        raise ValueError("Python helper evidence must complete successfully")
    return {"directory": str(directory), "node": {"metadata": node, "runs": rows},
            "python": {"metadata": python, "tests": int(matches[0]), "rawLog": binding(pylog)},
            "identicalBeforeAfterTestSha256": identical_tests, "retainedFinalSources": snapshots,
            "metadataFiles": {name: binding(directory / name) for name in metadata_names}}


def validate_regression(work, product_archive=None):
    shared = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"
    spec = importlib.util.spec_from_file_location("build_failure_summary", shared)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    summary = module.summarize_run(work, True)
    expected, result = read(work / "expected.json"), read(work / "result.json")
    installed = Path(result["installedExtension"]["path"])
    required = product_archive / "file-based-apps" if product_archive else MODULES
    with zipfile.ZipFile(expected["candidate"]["path"]) as archive:
        for name, value in expected["candidate"]["ownedModules"].items():
            if sha(required / name) != value or sha(installed / ".netcoredbg" / name) != value or hashlib.sha256(archive.read("extension/.netcoredbg/" + name)).hexdigest() != value:
                raise ValueError("Installed regression must bind to its exact current or archived product")
    for launch in result["launches"]:
        if Path(launch["output"]).exists():
            raise ValueError("A successful ordinary Stop must leave no captured owned output")
    return {"role": "bridge-only-historical" if product_archive else "final-current", "summary": summary,
            "sharedCollectors": {str(p.relative_to(REPO)): binding(p) for p in (shared, module.SHARED)}}


def validate_actual(work, outcome, historical, product_archive=None):
    expected, result, runner, post = (read(work / name) for name in
        ("expected.json", "result.json", "control-runner-result.json", "post-exit-observation.json"))
    clean = outcome == "clean"
    if expected["scenario"] != "actual-workbench-reload" or result["expected"] != expected or not result["mechanicsCompleted"]:
        raise ValueError("Actual Reload mechanics or input identity failed")
    if bool(result["success"]) != clean or bool(runner["success"]) != clean or post["baselineSuccess"] != clean:
        raise ValueError("Expected product outcome differs; never infer it from post-exit cleanup")
    if not clean and "Actual Reload baseline left original PID, port or output" not in runner["error"]:
        raise ValueError("The retained run must be an observed product result, not a harness failure")
    scope = result["scope"]
    if any(scope[name] for name in ("injectedTargetRuntime", "extensionTestsPath", "physicalF5", "macOS", "published", "qualification")) or not all(scope[name] for name in ("actualWorkbenchReload", "installedCandidate", "commandApi", "localOnly")):
        raise ValueError("Actual control scope differs")
    config = expected["actualReload"]
    if config["appLaunches"] != 1 or config["extensionTestsPath"] or config["command"] != "workbench.action.reloadWindow" or config["debug.confirmOnExit"] != "never" or runner["appLaunches"] != 1 or "--extensionTestsPath" in runner["arguments"]:
        raise ValueError("Expected one normal-activation app and actual workbench Reload")
    if runner["editorExitCode"] != 0 or result["editorPid"] != runner["editorPid"] or post["editorPid"] != runner["editorPid"] or result["firstHost"] == result["host"] or runner["extensionHostPids"] != [result["firstHost"], result["host"]]:
        raise ValueError("Reload must retain the app PID and replace its extension host")
    for n, host in ((1, result["firstHost"]), (2, result["host"])):
        marker, ack, process = (read(work / name) for name in (f"host-{n}.json", f"ack-{n}.json", f"extension-host-{n}-process.json"))
        if marker["phase"] != n or marker["nonce"] != config["nonce"] or marker["extensionHostPid"] != host or ack["extensionHostPid"] != host or ack["nonce"] != config["nonce"] or ack["editorPid"] != runner["editorPid"]:
            raise ValueError("Host handshake identity differs")
        lineage = process["lineage"]
        if not process["verified"] or process["editorPid"] != runner["editorPid"] or lineage[0]["ProcessId"] != host or lineage[-1]["ProcessId"] != runner["editorPid"]:
            raise ValueError("Both hosts require exact native app lineage")
        for index, node in enumerate(lineage):
            if node["ExecutablePath"].lower() != expected["editor"]["executable"].lower() or not node["CreationDate"] or (index + 1 < len(lineage) and node["ParentProcessId"] != lineage[index + 1]["ProcessId"]):
                raise ValueError("Every native lineage node must match the editor and link to its parent")
        if str(work).lower() not in lineage[-1]["CommandLine"].lower():
            raise ValueError("The editor must belong to the isolated control")
        if marker["installed"] != result["installed"]:
            raise ValueError("Both hosts must load the same normally installed candidate")
    for name in ("editor", "sdk", "candidate", "dependency"):
        file = Path(expected[name].get("executable", expected[name].get("path")))
        if sha(file) != expected[name]["sha256"]:
            raise ValueError("Pinned input changed: " + name)
    installed = Path(result["installed"]["path"])
    metadata = read(installed / "package.json")
    if metadata["version"] != expected["candidate"]["version"] or not metadata["__metadata"] or not metadata["netcoredbgBuild"]["localCandidate"] or metadata["netcoredbgBuild"]["lifecycleBuildId"] != expected["candidate"]["buildId"]:
        raise ValueError("Installed candidate metadata differs")
    with zipfile.ZipFile(expected["candidate"]["path"]) as archive:
        for name, value in expected["candidate"]["ownedModules"].items():
            data = archive.read("extension/.netcoredbg/" + name)
            if hashlib.sha256(data).hexdigest() != value or sha(installed / ".netcoredbg" / name) != value or result["installedModules"][name] != value:
                raise ValueError("Loaded/installed/archive module mismatch: " + name)
            if not historical and sha(MODULES / name) != value:
                raise ValueError("Final current product source differs: " + name)
            if product_archive is not None:
                if sha(product_archive / "file-based-apps" / name) != value:
                    raise ValueError("Intermediate candidate differs from its retained dirty-source archive")
            elif historical:
                original = subprocess.check_output(["git", "show", f"{expected['candidate']['sourceCommit']}:scripts/variant/file-based-apps/{name}"], cwd=REPO)
                if original.replace(b"\r\n", b"\n") != data.replace(b"\r\n", b"\n"):
                    raise ValueError("Historical installed product must match its pinned Git snapshot")
    for name in ("driver.cjs", "extension-test.cjs"):
        if sha(work / "driver" / name) != expected["harness"][name]:
            raise ValueError("Executed driver changed")
        if not historical and sha(HARNESS / name) != expected["harness"][name]:
            raise ValueError("Final harness source differs")
    if not historical:
        for name in ("prepare.py", "run.ps1"):
            if sha(HARNESS / name) != expected["harness"]["active-reload/" + name]:
                raise ValueError("Final control preparation/launcher differs")
    for name in ("driver.cjs", "extension-test.cjs", "prepare.py", "run.ps1"):
        snapshot = work / "executed-harness" / name
        if snapshot.exists() and sha(snapshot) != expected["harness"][name if name.endswith(".cjs") else "active-reload/" + name]:
            raise ValueError("Retained executed-harness snapshot differs from the executed manifest")
        if historical and not snapshot.exists():
            raise ValueError("Historical execution needs a retained hash-verified harness snapshot")
    if sha(work / "driver/package.json") != expected["harness"]["driver/package.json"]:
        raise ValueError("Prepared driver identity differs")
    settings_file = work / "profile/User/settings.json"
    settings_integrity = {"preparedSha256": expected["harness"]["profile/User/settings.json"],
                          "postRun": binding(settings_file), "byteIdentical": sha(settings_file) == expected["harness"]["profile/User/settings.json"]}
    prepared_settings = work / "prepared-settings.json"
    if not historical and not prepared_settings.exists():
        raise ValueError("The final run must retain its prepared settings snapshot")
    if prepared_settings.exists():
        if sha(prepared_settings) != settings_integrity["preparedSha256"] or sha(prepared_settings) != expected["harness"]["prepared-settings.json"]:
            raise ValueError("Prepared settings snapshot must match its input manifest")
        settings_integrity["preparedSnapshot"] = binding(prepared_settings)
    if not settings_integrity["byteIdentical"]:
        settings = read(settings_file)
        if settings.get("extensions.autoUpdate") != "off":
            raise ValueError("Unexpected post-run settings change")
        settings["extensions.autoUpdate"] = False
        reconstructed = (json.dumps(settings, indent=2) + "\n").replace("\n", "\r\n").encode()
        if hashlib.sha256(reconstructed).hexdigest() != settings_integrity["preparedSha256"]:
            raise ValueError("Only the observed false-to-off settings normalization may differ")
        settings_integrity["reconstruction"] = {"field": "extensions.autoUpdate", "prepared": False, "postRun": "off",
            "encoding": "UTF-8, two-space JSON indentation, trailing CRLF", "sha256": hashlib.sha256(reconstructed).hexdigest(),
            "originalPreparedSettingsFileRetained": prepared_settings.exists()}
    if read(work / "driver/package.json")["activationEvents"] != ["onStartupFinished"] or read(work / "profile/User/settings.json")["debug.confirmOnExit"] != "never":
        raise ValueError("Driver must use ordinary activation and recorded exit confirmation policy")
    old, retry = result["firstLaunch"], result["retry"]
    before = result["beforeReload"]
    if not before["pidAlive"] or not before["httpOwned"] or before["portBindable"] or not before["outputExists"] or old["pid"] == retry["pid"] or old["output"] == retry["output"] or not retry["terminated"]:
        raise ValueError("Require a live owned Web app before Reload and a fresh terminated retry")
    checkpoint = read(work / "phase.json")
    initial_log = result["newHostInitialRecoveryLog"]
    if len(checkpoint["firstHostLogPaths"]) != 1 or initial_log["path"].lower() in [p.lower() for p in checkpoint["firstHostLogPaths"]]:
        raise ValueError("Initial recovery must come from a distinct new-host logger path")
    if hashlib.sha256(initial_log["text"].encode()).hexdigest() != initial_log["sha256"] or not Path(initial_log["path"]).read_text(encoding="utf-8").startswith(initial_log["text"]):
        raise ValueError("The retained initial-recovery log prefix changed")
    if not re.search(r"(?m)^Terminal output recovery: scanned=\d+, attempted=\d+, removed=\d+$", initial_log["text"].replace("\r", "")):
        raise ValueError("Missing new-host initial recovery completion")
    initial = result["afterInitialRecovery"]
    observed_clean = not initial["pidAlive"] and initial["portBindable"] and not initial["outputExists"] and initial["terminalQueuesEmpty"]
    if result["reloadResourcesReleasedBeforeRetry"] != observed_clean:
        raise ValueError("Reload classification must be computed before public retry")
    if observed_clean != clean or not result["unmarkedGuardPreserved"] or sha(Path(old["guard"]["path"])) != old["guard"]["sha256"]:
        raise ValueError("The pre-retry initial-recovery resource/guard outcome is authoritative")
    if not clean:
        for name in ("immediateOldObservation", "afterInitialRecovery", "finalOldObservation"):
            snapshot = result[name]
            if snapshot["pidAlive"] or not snapshot["portBindable"] or not snapshot["outputExists"] or not snapshot["programExists"] or not snapshot["terminalQueuesEmpty"] or snapshot["pid"] != old["pid"] or snapshot["port"] != old["port"] or snapshot["output"].lower() != old["output"].lower():
                raise ValueError("This baseline specifically retains output after process/port release and no terminal receipt")
    if not all(post["hostsGone"]) or len(post["resources"]) != 2 or not all(r["pidGone"] and r["portReusable"] for r in post["resources"]):
        raise ValueError("Final process/port checks are incomplete")
    if not post["resources"][1]["outputAbsent"]:
        raise ValueError("The exact retry output must be removed")
    for observed, launch in zip(post["resources"], (old, retry)):
        if observed["pid"] != launch["pid"] or observed["port"] != launch["port"] or observed["output"].lower() != launch["output"].lower() or observed["label"] != launch["label"]:
            raise ValueError("Post-exit observations must refer to the exact captured resources")
    if Path(retry["output"]).exists() or Path(old["output"]).exists() == clean or (not clean and not Path(old["program"]).is_file()) or post["resources"][0]["outputAbsent"] != clean:
        raise ValueError("Current retained filesystem must agree with the exact post-exit output observations")
    if not result["finalOldObservation"]["terminalQueuesEmpty"]:
        raise ValueError("Both READY and STAGING must be empty after the retry Stop")
    if clean and not post["resources"][0]["outputAbsent"]:
        raise ValueError("Successful Reload requires original output cleanup")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text().splitlines()]
    reloads = [x for x in trace if x["event"] == "before-actual-reload"]
    if len(reloads) != 1 or reloads[0]["host"] != result["firstHost"] or reloads[0]["value"]["command"] != config["command"]:
        raise ValueError("Require one actual Reload trace from the original host")
    if not all(any(x["event"] == "real-web-ready" and x["host"] == host for x in trace) for host in (result["firstHost"], result["host"])):
        raise ValueError("Missing real Web readiness")
    events = [x["event"] for x in trace]
    first_ready = next(i for i, x in enumerate(trace) if x["event"] == "real-web-ready" and x["host"] == result["firstHost"])
    second_command = next(i for i, x in enumerate(trace) if x["event"] == "public-command-start" and x["host"] == result["host"])
    if not first_ready < events.index("before-actual-reload") < events.index("old-resources-after-actual-reload") < second_command < events.index("completed"):
        raise ValueError("Observe old resources before any new-host public command")
    old_session = old["sessionId"]
    old_messages = [x for x in trace if x["host"] == result["firstHost"] and x["event"] == "dap-from-adapter" and x["value"]["sessionId"] == old_session]
    old_lifecycle = [x for x in old_messages if x["value"]["message"].get("event") in ("exited", "terminated")]
    old_api_termination = [x for x in trace if x["host"] == result["firstHost"] and x["event"] == "debug-termination" and x["value"].get("sessionId") == old_session]
    fallback_line = f"Confirmed disposed C# session termination from paired DAP exited/terminated: {old_session} (exitCode=0)"
    old_logs = {p: {"file": binding(Path(p)), "fallbackLineOccurrences": Path(p).read_text(encoding="utf-8-sig").count(fallback_line)} for p in checkpoint["firstHostLogPaths"]}
    fallback_count = sum(item["fallbackLineOccurrences"] for item in old_logs.values())
    if clean:
        exited = [(i, x) for i, x in enumerate(old_lifecycle) if x["value"]["message"].get("type") == "event" and x["value"]["message"].get("event") == "exited" and type(x["value"]["message"].get("body", {}).get("exitCode")) is int and x["value"]["message"]["body"]["exitCode"] == 0]
        if fallback_count != 1 or not exited:
            raise ValueError("The final native control must exercise one logged exact-session paired-DAP fallback")
        exited_index, exited_event = exited[-1]
        terminated = [x for x in old_lifecycle[exited_index + 1:] if x["value"]["message"].get("type") == "event" and x["value"]["message"].get("event") == "terminated" and x["value"]["message"].get("body") == {}]
        if not terminated or exited_event["value"]["message"]["seq"] >= terminated[0]["value"]["message"]["seq"]:
            raise ValueError("Require exact first-host exited(exitCode=0) then terminated({}) evidence")
    retained_payload = {f.relative_to(old["output"]).as_posix(): binding(f) for f in sorted(Path(old["output"]).rglob("*")) if f.is_file()} if not clean else None
    return {"work": str(work), "expectedProductOutcome": outcome, "historicalProduct": historical,
            "productSourceProof": "hash-verified-dirty-source-archive" if product_archive else "pinned-Git-snapshot" if historical else "current-source",
            "result": result, "runner": runner, "postExit": post, "settingsIntegrity": settings_integrity,
            "firstHostTerminalEvidence": {"sessionId": old_session, "dapLifecycle": old_lifecycle,
                "editorApiTerminationObserved": bool(old_api_termination), "editorApiTerminationEvents": old_api_termination,
                "firstHostLogs": old_logs, "pairedDapFallbackLine": fallback_line, "pairedDapFallbackOccurrences": fallback_count},
            "retainedOldPayload": retained_payload, "rawFiles": retained_files(work)}, installed, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--intermediate-dir", type=Path)
    parser.add_argument("--intermediate-product-archive", type=Path)
    parser.add_argument("--bridge-regression", type=Path)
    parser.add_argument("--installed-regression", type=Path)
    parser.add_argument("--tests", type=Path)
    parser.add_argument("--expected-product-outcome", choices=("clean", "retained"), required=True)
    parser.add_argument("--historical-product", action="store_true")
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    root, work = args.artifact_root.resolve(), args.run_dir.resolve()
    actual, installed, expected = validate_actual(work, args.expected_product_outcome, args.historical_product)
    baseline = None
    audit_installed = installed
    if args.baseline_dir:
        baseline, audit_installed, _ = validate_actual(args.baseline_dir.resolve(), "retained", True)
    intermediate = None
    archive = None
    if bool(args.intermediate_dir) != bool(args.intermediate_product_archive):
        raise ValueError("Pass the failed intermediate run and its exact dirty-source archive together")
    if args.intermediate_dir:
        archive_dir = args.intermediate_product_archive.resolve()
        archive = validate_product_archive(archive_dir)
        intermediate, _, _ = validate_actual(args.intermediate_dir.resolve(), "retained", True, archive_dir)
    spec = importlib.util.spec_from_file_location("audit", HERE / "audit-local-sources.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    value = {"schema": 1, "kind": "actual-installed-active-web-reload", "artifactRoot": str(root),
             "emptyPrototypes": validate_empty(root), "actual": actual,
             "baseline": baseline,
             "failedBridgeOnlyIntermediate": intermediate,
             "bridgeOnlySourceAndTestArchive": archive,
             "localPrimarySourceAuditRole": "original-baseline" if baseline else "selected-actual-run",
             "localPrimarySourceAudit": audit.collect(Path(expected["editor"]["executable"]).parent, audit_installed),
             "researchScripts": {name: binding(HERE / name) for name in ("audit-local-sources.py", "summarize.py")},
             "limits": ["Actual Reload command API, not physical F5/menu input or macOS qualification.",
                        "Pre-retry initial-recovery snapshots establish Reload outcome; later command recovery, failure cleanup and post-exit observations are separate.",
                        "Unmarked/unknown output is never inferred terminal from a dead host PID."]}
    if archive is not None:
        value["bridgeOnlyUnitEvidence"] = validate_unit_evidence(archive_dir / "prior-evidence", archive_dir)
    if args.bridge_regression:
        if archive is None:
            raise ValueError("A bridge-only regression needs its intermediate product archive")
        value["bridgeOnlyInstalledRegression"] = validate_regression(args.bridge_regression.resolve(), archive_dir)
    if args.installed_regression:
        value["finalInstalledRegression"] = validate_regression(args.installed_regression.resolve())
    if args.tests:
        value["finalUnitEvidence"] = validate_unit_evidence(args.tests.resolve())
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
