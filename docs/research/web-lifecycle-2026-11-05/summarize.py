"""Summarize retained local Web lifecycle runs without rerunning the editor."""
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath


REPO = Path(__file__).resolve().parents[3]
HARNESS = (
    "scripts/variant/lifecycle/prepare.py",
    "scripts/variant/lifecycle/run.ps1",
    "scripts/variant/lifecycle/driver.cjs",
    "scripts/variant/lifecycle/extension-test.cjs",
    "scripts/variant/lifecycle/fixtures/web.cs",
    "scripts/variant/test_lifecycle_preparation.py",
)


def sha256(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def read_json(file):
    return json.loads(file.read_text(encoding="utf-8-sig"))


def raw_files(work):
    files = [work / name for name in ("result.json", "expected.json", "trace.jsonl", "launcher-result.json",
                                     "attempt.json", "launch.json", "progress/state.json")]
    files += sorted((work / "logs").glob("*"))
    for pattern in ("**/*C# File Debugging.log", "**/exthost.log", "**/C#.log"):
        files += sorted((work / "profile/logs").glob(pattern))
    return {file.relative_to(work).as_posix(): {"sha256": sha256(file), "bytes": file.stat().st_size}
            for file in files if file.is_file()}


def summarize_run(work, repo, require_current_harness=False, historical=None):
    expected = read_json(work / "expected.json")
    result = read_json(work / "result.json")
    launcher = read_json(work / "launcher-result.json")
    if not result["success"] or result.get("firstFailure") or not launcher["success"] or launcher["editorExitCode"] != 0:
        raise ValueError("A failing run must retain its failure, not become a passing summary: " + str(work))
    candidate = expected["candidate"]
    if sha256(work / "local-lifecycle.vsix") != candidate["sha256"]:
        raise ValueError("Candidate no longer matches the recorded run")
    if result["installedModules"] != candidate["ownedModules"]:
        raise ValueError("Installed owned modules differ from expected")
    if launcher["candidateSha256"] != candidate["sha256"]:
        raise ValueError("Launcher candidate differs from expected")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    launches = []
    for launch in result["launches"]:
        stopped = launch["stopRequestedAtMilliseconds"]
        timings = {}
        for label, key in (
            ("stopPromise", "stopPromiseResolvedAtMilliseconds"),
            ("matchingEditorTermination", "terminatedAtMilliseconds"),
            ("pidObservedGone", "pidGoneAtMilliseconds"),
            ("portRebindSucceeded", "portReusableAtMilliseconds"),
            ("outputAndQueuesClear", "outputRemovedAtMilliseconds"),
        ):
            delta = launch[key] - stopped
            if delta < 0:
                raise ValueError("Lifecycle observation predates Stop: " + launch["label"])
            timings[label] = round(delta, 3)
        launches.append({key: launch[key] for key in ("label", "revision", "pid", "sessionId", "origin", "output", "response")} |
                        {"afterStopMilliseconds": timings,
                         "stopPromiseToTerminationMilliseconds": round(launch["terminatedAtMilliseconds"] - launch["stopPromiseResolvedAtMilliseconds"], 3)})
    diagnostics = []
    for event in trace:
        detail = event.get("detail", {})
        message = detail.get("message", {})
        if event["event"] == "adapter-error" or (event["event"] == "dap-receive" and message.get("success") is False):
            owner = next((launch for launch in result["launches"] if launch["label"] == detail.get("label")), None)
            diagnostics.append(event | {"afterStopMilliseconds": round(event["atMilliseconds"] - owner["stopRequestedAtMilliseconds"], 3) if owner else None})
    runtime_modules = sorted({event["detail"]["message"]["body"]["module"].get("path", "") for event in trace
                              if event["event"] == "dap-receive"
                              and event.get("detail", {}).get("message", {}).get("event") == "module"
                              and "Microsoft.NETCore.App" in event["detail"]["message"]["body"]["module"].get("path", "")})
    final_sources = {name.removeprefix("scripts/variant/lifecycle/"): sha256(repo / name) for name in HARNESS[:5]}
    executed_copies = {"driver.cjs": sha256(work / "driver/driver.cjs"),
                       "extension-test.cjs": sha256(work / "driver/extension-test.cjs"),
                       "fixtures/web.cs": sha256(work / "workspace/b.cs")}
    recorded_harness = expected.get("harness")
    if recorded_harness:
        if any(recorded_harness[name] != value for name, value in executed_copies.items()):
            raise ValueError("Executed driver or unchanged B fixture differs from pinned harness")
    elif historical:
        if executed_copies != historical["executedCopiesSha256"]:
            raise ValueError("Historical executed copies differ from their retained evidence")
    else:
        raise ValueError("An unpinned historical harness needs its previously retained evidence")
    if require_current_harness and recorded_harness != final_sources:
        raise ValueError("Final source files differ from the latest run's pinned harness")
    summary = {
        "name": work.name, "localArtifactDirectory": str(work), "success": True,
        "editorExitCode": launcher["editorExitCode"], "scope": result["scope"],
        "freshProfiles": 1, "aLaunchesAndStopCycles": expected["cycles"], "bLaunches": 1,
        "candidate": candidate, "editor": expected["editor"] | {"apiVersion": result["editorApiVersion"]},
        "sdk": expected["sdk"], "dependency": expected["dependency"],
        "installedExtension": result["installedExtension"], "installedDependency": result.get("installedDependency"),
        "installedOwnedModules": result["installedModules"], "harnessPinnedBeforeLaunch": recorded_harness,
        "executedCopiesSha256": executed_copies, "checks": result["checks"],
        "phases": result["phases"], "elapsedMilliseconds": result["elapsedMilliseconds"],
        "launches": launches,
        "unrelatedSessionPreserved": [event for event in trace if event["event"] == "unrelated-preserved"],
        "stopDiagnostics": diagnostics,
        "observedCoreRuntimeDirectories": sorted({str(PureWindowsPath(file).parent) for file in runtime_modules}),
        "observedCoreLibraryModulePaths": [file for file in runtime_modules if file.endswith("System.Private.CoreLib.dll")],
        "rawEvidence": raw_files(work),
        "interpretation": "Behavioral lifecycle assertions passed. Stop-time adapter errors remain recorded; this is not an error-free-log or release-qualification claim.",
    }
    if historical and summary != historical:
        raise ValueError("Historical run evidence changed; retain and investigate the original: " + str(work))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True, help="Retained runs in chronological order")
    parser.add_argument("--failed-preparation-dir", type=Path)
    parser.add_argument("--duplicate-attempt-check", type=Path)
    parser.add_argument("--dependency-download", type=Path)
    parser.add_argument("--review-followup-check", type=Path)
    parser.add_argument("--review-followup-failure", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("evidence-summary.json"))
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    # Earlier controls retain their own harness identity. Only the latest run
    # must match current source bytes; old rows must remain structurally equal
    # to the already retained summary, rather than being relabelled.
    previous = read_json(args.output) if args.output.exists() else {}
    historical = {run["name"]: run for run in previous.get("runs", [])}
    runs = [summarize_run(work.resolve(), repo, index == len(args.runs) - 1,
                          historical.get(work.name) if index < len(args.runs) - 1 else None)
            for index, work in enumerate(args.runs)]
    summary = {
        "schema": 1, "date": "2026-11-05", "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
        "kind": "local installed VSCodium Web lifecycle control", "qualification": False,
        "recordedEnvironment": {"windowsBuild": "26300.9711", "displayVersion": "26H2",
            "node": "24.22.1 win32 arm64", "python": "3.12.14",
            "source": "Local registry/API/tool observations; editor native architecture is separately checked by PE header and extension host."},
        "finalHarnessRun": runs[-1]["name"], "finalHarnessFreshProfiles": 1,
        "finalHarnessACycles": runs[-1]["aLaunchesAndStopCycles"],
        "harnessSourceSha256AtSummary": {name: sha256(repo / name) for name in HARNESS},
        "summarizerSha256": sha256(Path(__file__).resolve()),
        "preparationHistory": [{"name": "run-01", "outcome": "preparation failed before editor launch",
            "cause": "Reusing source ZipInfo objects for output mutated their offsets before the unchanged-payload comparison read them again.",
            "fix": "copy.copy(info) isolates output metadata; payload preservation regression verifies original and candidate bytes.",
            "rawTracebackRetained": False, "editorScenarioAttempted": False},
            {"name": "unsafe-name unit case", "outcome": "initial negative test failed",
             "cause": "Python on Windows normalizes ZIP backslashes before filename-based validation.",
             "fix": "Validate original ZIP names (orig_filename); construct a raw backslash fixture after ZipInfo initialization.",
             "editorScenarioAttempted": False}],
        "runs": runs,
    }
    if args.failed_preparation_dir:
        failed = args.failed_preparation_dir.resolve()
        summary["preparationHistory"][0]["localArtifactDirectory"] = str(failed)
        summary["preparationHistory"][0]["retainedFiles"] = {
            file.name: {"sha256": sha256(file), "bytes": file.stat().st_size}
            for file in sorted(failed.iterdir()) if file.is_file()
        }
    for key, file in (("duplicateAttemptCheck", args.duplicate_attempt_check), ("dependencyDownload", args.dependency_download),
                      ("reviewFollowupCheck", args.review_followup_check),
                      ("reviewFollowupFailure", args.review_followup_failure)):
        if file:
            summary[key] = {"path": str(file.resolve()), "sha256": sha256(file), "record": read_json(file)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), "sha256": sha256(args.output), "runs": len(runs)}))


if __name__ == "__main__":
    main()
