"""Validate PR44 review corrections without rewriting its original failed evidence."""
import argparse
from datetime import datetime
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
ORIGINAL_REF = "eed65a94f826ccb8a6178fbf6eb85e4cae82cd16"
DRIVER_FIX_REF = "1b59dd3f306227940cdfc8d4cab461a4f838929c"
PRODUCT_REF = "32eae02d4c9594be42d85f93fa1e38b079184867"
APPROVED_REFS = {ORIGINAL_REF, DRIVER_FIX_REF}
ORIGINAL_SUMMARY_SHA = "febc422cdbbdf74c8a71d4bb064dffb284d5da87cc7e5798a969b20b45e313e7"
HISTORY = REPO / "docs/research/host-loss-2026-11-08"
spec = importlib.util.spec_from_file_location("pr44_review_history", HISTORY / "summarize.py")
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)
read, binding, same = history.read, history.binding, history.same
original_product_validator = history.validate_product


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check_file(file, proof):
    if (not file.is_file() or file.is_symlink() or sha(file.read_bytes()) != proof["sha256"]
            or file.stat().st_size != proof.get("bytes", proof.get("size"))):
        raise ValueError("Retained file differs: " + str(file))
    return binding(file)


def git_bytes(ref, name):
    return subprocess.check_output(["git", "show", f"{ref}:{name}"], cwd=REPO)


def validate_approved_product(work, expected, observations):
    """Admit only two reviewed provenance refs; keep the original identity assertions."""
    ref = expected["candidate"]["sourceCommit"]
    if ref not in APPROVED_REFS:
        raise ValueError("Unexpected candidate source ref")
    result = original_product_validator(work, expected, observations, base_commit=ref)
    for name in history.MODULE_NAMES:
        current = (REPO / "scripts/variant/file-based-apps" / name).read_bytes()
        baseline = git_bytes(PRODUCT_REF, "scripts/variant/file-based-apps/" + name)
        if current.replace(b"\r\n", b"\n") != baseline.replace(b"\r\n", b"\n"):
            raise ValueError("PR44 review must retain merged PR43 product content")
    return {**result, "unchangedProductContentFrom": PRODUCT_REF,
            "sourceRefPolicy": "Only the original PR44 ref and its reviewed test-driver correction are admitted; current/archive/installed bytes and all original product-identity assertions remain checked."}


def validate_history(root):
    file = HISTORY / "evidence-summary.json"
    data, value = file.read_bytes(), read(file)
    if (len(data) != 397360 or sha(data) != ORIGINAL_SUMMARY_SHA
            or value["overallStatus"] != "primary-pass-regression-fail"
            or value["primaryRun"]["success"] is not True or value["compilerRegression"]["success"] is not False
            or value["compilerRegression"]["bPauseObservation"]["initiator"] != "unproven"):
        raise ValueError("Original c01 FAIL and n01 PASS must remain unchanged")
    historical_docs = {}
    for name in ("README.md", "acceptance-audit.md", "summarize.py", "evidence-summary.json"):
        source = HISTORY / name
        reference = git_bytes(ORIGINAL_REF, "docs/research/host-loss-2026-11-08/" + name)
        if source.read_bytes().replace(b"\r\n", b"\n") != reference.replace(b"\r\n", b"\n"):
            raise ValueError("Historical PR44 documents may not be rewritten")
        historical_docs[name] = binding(source)
    observations = {}
    for key in ("primaryRun", "compilerRegression"):
        record = value[key]
        work = Path(record["directory"])
        observations[key] = {name: check_file(work / name, proof) for name, proof in record["rawEvidence"].items()}
    receipt_file = root / "original-regeneration.json"
    receipt = read(receipt_file)
    required = {"schema": 1, "kind": "historical PR44 full memory-only regeneration", "commit": ORIGINAL_REF,
                "sourceFilesRestoredFromPreRunArchive": 52, "sourceBytesRequireSameGitNormalizedContent": True,
                "collectorBytesSelectedOnlyByRecordedSha256": True, "summaryBytes": 397360,
                "summarySha256": ORIGINAL_SUMMARY_SHA, "fullBytesEqual": True,
                "status": "primary-pass-regression-fail", "noEditorOrSuiteRerun": True}
    if any(receipt.get(key) != expected for key, expected in required.items()):
        raise ValueError("Expected the exact historical byte-regeneration receipt")
    if receipt["relocation"] != "Only source-manifest worktree identity is mapped to this detached checkout during validation and restored before serialization; all content/hash/source-set/assertions remain unchanged.":
        raise ValueError("Historical relocation must retain its exact documented scope")
    return {"summary": binding(file), "status": value["overallStatus"], "unchangedDocuments": historical_docs,
            "rawEvidenceRechecked": observations, "originalCompilerFailure": value["compilerRegression"]["firstFailure"],
            "originalPauseObservation": value["compilerRegression"]["bPauseObservation"],
            "regenerationReceipt": {"file": binding(receipt_file), "record": receipt},
            "regenerationHelper": binding(root / "verify-original.py"),
            "earlierGitNewlineComparison": {"file": binding(root / "original-regeneration-git-lf.json"),
                                            "record": read(root / "original-regeneration-git-lf.json")},
            "interpretation": "The original raw summary and all original native logs remain unchanged. A detached original snapshot restored only source bytes selected by pre-run hashes and matching Git-normalized content, then regenerated the entire original summary in memory with source-manifest path relocation restored before serialization. The earlier Git-newline comparison is retained separately and is not another native attempt."}


def validate_diagnostic(work, adapter_identity):
    expected, result, launch, launcher = (read(work / name) for name in ("expected.json", "result.json", "launch.json", "launcher-result.json"))
    receipt_file = work / "diagnostic-preparation.json"
    receipt = read(receipt_file)
    before_file, base_file, diagnostic = (work / name for name in ("expected-before-diagnostic.json", "baseline-run.ps1", "diagnostic-run.ps1"))
    before = read(before_file)
    baseline = (REPO / "scripts/variant/lifecycle/run.ps1").read_bytes()
    needle = b"'--skip-welcome', '--skip-release-notes',"
    replacement = b"'--log', 'trace', '--skip-welcome', '--skip-release-notes',"
    if (baseline.count(needle) != 1 or base_file.read_bytes() != baseline
            or diagnostic.read_bytes() != baseline.replace(needle, replacement, 1)):
        raise ValueError("The diagnostic launcher must add only --log trace to the exact shared launcher")
    changed = json.loads(json.dumps(before))
    changed["harness"]["run.ps1"] = sha(diagnostic.read_bytes())
    if (expected != changed or result["expected"] != expected or before["candidate"]["sourceCommit"] != ORIGINAL_REF
            or expected["scenario"] != "build-failure-retry" or expected["cycles"] != 3):
        raise ValueError("Only the diagnostic expected launcher hash may change")
    shared = REPO / "scripts/variant/lifecycle"
    harness = {name: sha((shared / name).read_bytes()) for name in ("prepare.py", "run.ps1", "driver.cjs", "extension-test.cjs", "fixtures/web.cs")}
    if before["harness"] != harness:
        raise ValueError("The unchanged diagnostic preparation, driver and fixture must match shared source")
    expected_diff = "".join(difflib.unified_diff(baseline.decode().splitlines(keepends=True), diagnostic.read_bytes().decode().splitlines(keepends=True), fromfile="baseline-run.ps1", tofile="diagnostic-run.ps1"))
    if (receipt["schema"] != 1 or receipt["baseCommit"] != ORIGINAL_REF or receipt["scenario"] != expected["scenario"]
            or receipt["cycles"] != 3 or receipt["expectedSemanticChanges"] != ["harness.run.ps1"]
            or receipt["addedAppArguments"] != ["--log", "trace"] or receipt["exactDiff"] != expected_diff
            or receipt["candidate"] != expected["candidate"] or receipt["dependency"] != expected["dependency"]
            or receipt["editor"] != expected["editor"] or receipt["sdk"] != expected["sdk"]
            or not all(receipt["controls"].values())):
        raise ValueError("Diagnostic preparation receipt differs")
    for key, file in (("baselineLauncher", shared / "run.ps1"), ("retainedBaselineLauncher", base_file),
                      ("diagnosticLauncher", diagnostic), ("expectedBefore", before_file), ("expectedAfter", work / "expected.json")):
        if not same(receipt[key]["path"], file):
            raise ValueError("Diagnostic receipt path differs")
        check_file(file, receipt[key])
    for proof in receipt["editorTraceImplementationBindings"]:
        check_file(Path(proof["path"]), proof)
    quote = lambda file: '"' + str(file) + '"'
    arguments = ["--locale", "en", "--user-data-dir", quote(work / "profile"), "--extensions-dir", quote(work / "extensions"),
                 "--extensionDevelopmentPath", quote(work / "driver"), "--extensionTestsPath", quote(work / "driver/extension-test.cjs"),
                 "--log", "trace", "--skip-welcome", "--skip-release-notes", "--disable-gpu", "--disable-workspace-trust", "--no-sandbox", quote(work / "workspace")]
    if (launch["arguments"] != arguments or launch["visibleWindowRequested"] is not False
            or launch["freshProfile"] is not True or launcher["visibleWindowRequested"] is not False):
        raise ValueError("Actual diagnostic app launch must retain only the intended trace flag delta")
    product = validate_approved_product(work, {**expected, "hostLoss": adapter_identity},
                                        [{"installed": result["installedExtension"], "installedModules": result["installedModules"]}])
    # The historical behavioral validator is unchanged. Its optional current-
    # harness equality is replaced here by the stricter exact-one-delta checks
    # above, rather than changing a previous passing collector or result.
    control = history.build.summarize_run(work, False)
    rows = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    if (len(result["launches"]) != 4 or {item["label"] for item in result["launches"]} != {"A-0", "B", "A-1", "A-2"}
            or any(phase["outcome"] != "passed" for phase in result["phases"])
            or any(Path(item["output"]).exists() for item in result["launches"])
            or any(row["event"] == "dap-send" and row["detail"]["message"].get("command") == "pause" for row in rows)
            or any(row["event"] == "dap-receive" and row["detail"]["message"].get("body", {}).get("reason") == "pause" for row in rows)):
        raise ValueError("This trace-only diagnostic must retain its actual full passing cycles without a pause")
    files = {name: list((work / "profile/logs").glob("**/" + name)) for name in ("renderer.log", "exthost.log", "main.log")}
    if any(len(items) != 1 for items in files.values()):
        raise ValueError("Expected one unambiguous diagnostic editor log per process role")
    texts = {name: items[0].read_text(encoding="utf-8") for name, items in files.items()}
    patterns = ("CommandService#executeCommand", "ExtHostCommands#executeCommand", "KeybindingService#dispatch", "workbench.action.debug.pause")
    counts = {name: {pattern: text.count(pattern) for pattern in patterns} for name, text in texts.items()}
    owned = [line for line in texts["exthost.log"].splitlines() if "ExtHostCommands#executeCommand netcoredbg.debugActiveFile" in line]
    if (counts["renderer.log"]["CommandService#executeCommand"] <= 0 or counts["exthost.log"]["ExtHostCommands#executeCommand"] <= 0
            or len(owned) != 7 or any(row["KeybindingService#dispatch"] or row["workbench.action.debug.pause"] for row in counts.values())):
        raise ValueError("Trace must be active and retain the observed absence of a reproduced Pause route")
    return {"control": control, "productIdentity": product, "diagnosticPreparation": {"file": binding(receipt_file), "record": receipt},
            "actualLaunch": launch, "traceObservations": {"rows": len(rows), "pauseRequests": 0, "pauseStoppedEvents": 0,
                                                          "logCounts": counts, "ownedCommandLines": owned},
            "rawEvidence": history.raw_files(work),
            "interpretation": "The one separately identified trace-instrumented attempt passes three A Stop/retry cycles with B preservation and final cleanup. Standard renderer/EH command traces are populated, but no DAP Pause, standard Pause command or keybinding-dispatch route occurs. This is non-reproduction; tracing changes timing and does not identify or fix the original c01 initiator. The preparation receipt's editorNotRun field describes its pre-launch state only."}


def validate_units(directory, historical_root):
    result = history.prior.prior.validate_units(directory, base_commit=DRIVER_FIX_REF)
    manifest = result["manifest"]
    if result["sourceCount"] != 53:
        raise ValueError("Expected all 53 frozen sources including the driver regressions")
    baseline = manifest["baselineDriver"]
    baseline_file = historical_root / "n01/driver/driver.cjs"
    if (not same(baseline["path"], baseline_file) or baseline["sha256"] != "9cc443985cc756c6e45faf6b7430f4f6ab9de9c75a0ea7d9ada8ea402ed6914e"
            or baseline_file.read_bytes().replace(b"\r\n", b"\n") != git_bytes(ORIGINAL_REF, "scripts/variant/lifecycle/host-loss/driver.cjs").replace(b"\r\n", b"\n")):
        raise ValueError("Negative regression control must execute the actual original installed driver")
    check_file(baseline_file, baseline)
    extra = manifest["additionalRuns"]
    if [entry["log"] for entry in extra] != ["driver.log", "baseline-driver.log"]:
        raise ValueError("Both new and original-driver attempts must remain separate")
    expected_argv = [manifest["node"]["path"], "--unhandled-rejections=strict", "--test", "scripts/variant/lifecycle/host-loss/test-driver.cjs"]
    previous_time = datetime.fromisoformat(manifest["runs"][-1]["result"]["completedUtc"].replace("Z", "+00:00"))
    verified = datetime.fromisoformat(manifest["finalSourceVerifiedUtc"].replace("Z", "+00:00"))
    verified_runs = []
    for index, entry in enumerate(extra):
        outcome = entry["result"]
        result_file = directory / entry["log"].replace(".log", "-result.json")
        log_file = directory / entry["log"]
        expected_environment = {} if index == 0 else {"HOST_LOSS_TEST_DRIVER_SOURCE": str(baseline_file)}
        began = datetime.fromisoformat(outcome["startedUtc"].replace("Z", "+00:00"))
        ended = datetime.fromisoformat(outcome["completedUtc"].replace("Z", "+00:00"))
        if (entry["argv"] != expected_argv or entry["environmentOverrides"] != expected_environment
                or read(result_file) != outcome or sha(log_file.read_bytes()) != outcome["logSha256"]
                or outcome["exitCode"] != index or outcome["expectedExitCode"] != index
                or not previous_time <= began <= ended <= verified):
            raise ValueError("Driver positive/negative verification arguments, result, log or ordering differ")
        counts = {key: int(value) for key, value in re.findall(r"(?m)^(?:#|ℹ) (tests|pass|fail|cancelled|skipped|todo) (\d+)\s*$", log_file.read_text(encoding="utf-8-sig"))}
        expected_counts = {"tests": 15, "pass": 15 if index == 0 else 2, "fail": 0 if index == 0 else 13,
                           "cancelled": 0, "skipped": 0, "todo": 0}
        if counts != expected_counts:
            raise ValueError("Expected all 15 corrected-driver cases and the original driver's 13 failures")
        previous_time = ended
        verified_runs.append({"record": entry, "counts": counts, "rawLog": binding(log_file), "rawResult": binding(result_file)})
    return {**result, "additionalDriverRuns": verified_runs, "negativeControlDriver": binding(baseline_file),
            "interpretation": "The unchanged five-suite Node228 and Python39 checks pass. Separately, all 15 guarded-driver cases pass and the same 15 cases against the actual old installed driver yield 13 failures/2 passes and natural exit1. Negative controls are not passing product qualification."}


def validate_cycle_review(root):
    receipt_file = root / "powershell-cycle-review.json"
    receipt = read(receipt_file)
    expected = {"schema": 1, "sourceSha256": sha((REPO / "scripts/variant/lifecycle/host-loss/run.ps1").read_bytes()),
                "actualLineageDefinitionExtracted": True, "mockOnlyNoProcessQueries": True, "mockCycle": [10, 20, 10],
                "observedError": "Process ancestry contains a cycle", "projected": [10, 20], "contains10": True, "contains20": True}
    if receipt != expected:
        raise ValueError("Expected the exact-source mock-only PowerShell cycle reproduction")
    return {"file": binding(receipt_file), "record": receipt, "helper": binding(root / "verify-cycle.ps1")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--historical-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    root, historical_root = args.artifact_root.resolve(), args.historical_root.resolve()
    historical = validate_history(root)
    run = root / "n02"
    if read(run / "expected.json")["candidate"]["sourceCommit"] != DRIVER_FIX_REF:
        raise ValueError("Guarded-driver installed control must use the reviewed driver-fix ref")
    history.validate_product = validate_approved_product
    try:
        guarded = history.validate_primary(run)
    finally:
        history.validate_product = original_product_validator
    diagnostic = validate_diagnostic(root / "c02", read(run / "expected.json")["hostLoss"])
    units = validate_units(root / "tests", historical_root)
    cycle = validate_cycle_review(root)
    collectors = {name: binding(REPO / name) for name in read(HISTORY / "evidence-summary.json")["collectors"]}
    collectors[str(Path(__file__).relative_to(REPO))] = binding(Path(__file__))
    value = {"schema": 1, "kind": "PR44 guarded-driver review and separately traced compiler diagnostic", "qualification": False,
             "productChange": False, "sourceRefs": {"originalPr44": ORIGINAL_REF, "guardedDriver": DRIVER_FIX_REF, "unchangedProduct": PRODUCT_REF},
             "overallStatus": "review-controls-pass-original-regression-unresolved", "historicalEvidence": historical,
             "guardedDriverInstalledControl": guarded, "traceCompilerDiagnostic": diagnostic, "verification": units, "collectors": collectors,
             "cycleReview": cycle,
             "reviewDisposition": {"evidenceOnlyMergeScope": True, "originalHeldDispositionPreserved": True, "originalC01StillFailed": True,
                                   "issue45Resolved": False, "issue18Closed": False, "allPassQualification": False,
                                   "explanation": "Review accepts the test/evidence-only change after correcting its driver and independently validating current controls. It does not accept the original regression as fixed: #45 remains open and blocks an all-pass qualification/release claim. Historical held-for-investigation wording remains untouched; this is a separate explicit review disposition."},
             "limits": ["One diagnostic non-reproduction does not establish the original Pause initiator or repair it.",
                        "Trace logging changes timing; the separate c02 is not silently substituted for original c01.",
                        "Unknown host-loss output remains deliberately preserved; no terminal cleanup receipt is invented from process death.",
                        "Issue18 AC6's indefinitely unsettled foreground/drain boundary remains open.",
                        "Native macOS, physical F5/menu, arbitrary descendants, calibrated latency, language-service readiness and the full repeated CI/publication matrix remain unqualified."]}
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
