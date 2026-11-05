"""Retain installed-command compiler-failure/retry evidence and normal cleanup."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SHARED = REPO / "docs/research/web-lifecycle-2026-11-05/summarize.py"
spec = importlib.util.spec_from_file_location("web_lifecycle_summary", SHARED)
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


def output_logs(work, logs=()):
    paths = set((work / "profile/logs").glob("**/*C# File Debugging.log"))
    paths.update(Path(log["path"]) for log in logs)
    manifest = {}
    for file in sorted(paths):
        relative = file.resolve().relative_to(work.resolve()).as_posix()
        manifest[relative] = {"sha256": web.sha256(file), "bytes": file.stat().st_size}
    return manifest


def validate_log_slice(log):
    # JS records UTF-16 string offsets. Preserve original CRLF bytes and BOM
    # when reconstructing the exact prefix/tail used by the editor driver.
    text = Path(log["path"]).read_bytes().decode("utf-8")
    units = text.encode("utf-16-le")
    start = log["offsetCharacters"] * 2
    end = start + log["tailCharacters"] * 2
    prefix = units[:start].decode("utf-16-le")
    tail = units[start:end].decode("utf-16-le")
    digest = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
    if len(units) < end or digest(prefix) != log["prefixSha256"] or digest(tail) != log["tailSha256"]:
        raise ValueError("Retained compiler-output slice differs from its recorded prefix/tail")


def summarize_run(work, latest):
    result = web.read_json(work / "result.json")
    if result["expected"].get("scenario") != "build-failure-retry":
        raise ValueError("Expected the explicit build-failure-retry scenario")
    summary = web.summarize_run(work, REPO, require_current_harness=latest)
    attempts = result["failedBuildAttempts"]
    if not attempts:
        raise ValueError("A passing build-failure control must retain its failed attempts")
    for attempt in attempts:
        if (attempt["commandResult"] is not False or not attempt["sourceSaved"] or not attempt["noSession"]
                or not attempt["log"]["compilerDiagnostics"] or not attempt["log"]["failedPhaseDiagnostics"]):
            raise ValueError("Expected compiler-failure, save and no-session evidence")
    coalesced = result["coalescedRetry"]
    if coalesced["commandInvocations"] != 3 or coalesced["commandResults"] != [True, True, True]:
        raise ValueError("Expected three successful callers for the corrected retry")
    if coalesced["sessionIds"] != [coalesced["sessionId"]]:
        raise ValueError("The corrected retry must identify exactly one captured session")
    if len(coalesced["log"]["buildCommands"]) != 1 or not coalesced["freshOutput"]:
        raise ValueError("Corrected coalesced retry must have one build and fresh output")
    if not any(launch["sessionId"] == coalesced["sessionId"] and launch["output"] == coalesced["output"]
               for launch in result["launches"]):
        raise ValueError("Coalesced retry does not identify a captured successful session")
    logs = [attempt["log"] for attempt in attempts] + [coalesced["log"]]
    for log in logs:
        validate_log_slice(log)
    summary["validatedOutputLogs"] = output_logs(work, logs)
    summary["rawEvidence"].update(summary["validatedOutputLogs"])
    summary.update(scenario=result["expected"]["scenario"], failedBuildAttempts=attempts, coalescedRetry=coalesced)
    summary["successfulCommandControls"] = [
        {key: launch[key] for key in ("label", "commandInvocations", "commandResults", "capturedSessions")}
        for launch in result["launches"]]
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--failed-runs", type=Path, nargs="*", default=[])
    parser.add_argument("--preflight-dirs", type=Path, nargs="*", default=[])
    parser.add_argument("--normal-control", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("evidence-summary.json"))
    args = parser.parse_args()
    runs = [summarize_run(work.resolve(), index == len(args.runs) - 1)
            for index, work in enumerate(args.runs)]
    failures = []
    for directory in args.failed_runs:
        work = directory.resolve()
        retained = {name: web.read_json(work / name) for name in ("result.json", "launcher-result.json")
                    if (work / name).exists()}
        raw = web.raw_files(work)
        raw.update(output_logs(work))
        failures.append({"localArtifactDirectory": str(work), "retainedResults": retained, "rawEvidence": raw})
    preflights = []
    for directory in args.preflight_dirs:
        work = directory.resolve()
        if (work / "launch.json").exists() or (work / "result.json").exists():
            raise ValueError("An executed profile cannot be relabelled as preparation-only")
        record = work / "not-executed.json"
        expected = web.read_json(work / "expected.json")
        candidate_sha = web.sha256(work / "local-lifecycle.vsix")
        if candidate_sha != expected["candidate"]["sha256"]:
            raise ValueError("Preflight candidate differs from its recorded preparation")
        preflights.append({"localArtifactDirectory": str(work), "record": web.read_json(record),
                           "recordSha256": web.sha256(record), "expectedSha256": web.sha256(work / "expected.json"),
                           "candidateSha256": candidate_sha})
    summary = {
        "schema": 1, "date": "2026-11-05", "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18",
        "kind": "local installed VSCodium compiler-failure and same-file retry control",
        "qualification": False, "finalHarnessRun": runs[-1]["name"],
        "finalHarnessFreshProfiles": 1, "finalHarnessACycles": runs[-1]["aLaunchesAndStopCycles"],
        "harnessSourceSha256AtSummary": {name: web.sha256(REPO / name) for name in web.HARNESS},
        "summarizerSha256": web.sha256(Path(__file__).resolve()),
        "sharedSummarizerSha256": web.sha256(SHARED),
        "unexecutedPreflights": preflights, "unexpectedFailures": failures, "runs": runs,
    }
    if args.normal_control:
        work = args.normal_control.resolve()
        expected = web.read_json(work / "expected.json")
        if expected.get("scenario") != "web-lifecycle":
            raise ValueError("The separate normal control must use the default web-lifecycle scenario")
        result = web.read_json(work / "result.json")
        if result["failedBuildAttempts"] or result.get("coalescedRetry") is not None:
            raise ValueError("The default normal control must not include the new compiler-failure branch")
        control = web.summarize_run(work, REPO, require_current_harness=True)
        control.update(scenario=expected["scenario"], validatedOutputLogs=output_logs(work),
                       failedBuildAttempts=result["failedBuildAttempts"], coalescedRetry=None)
        control["rawEvidence"].update(control["validatedOutputLogs"])
        summary["normalControl"] = control
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), "sha256": web.sha256(args.output), "runs": len(runs)}))


if __name__ == "__main__":
    main()
