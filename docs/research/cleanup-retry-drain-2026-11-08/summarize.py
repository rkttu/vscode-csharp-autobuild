"""Validate foreground-independent known-terminal cleanup retry unit evidence."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODULES = REPO / "scripts/variant/file-based-apps"
ORIGINAL_BASE = "eed65a94f826ccb8a6178fbf6eb85e4cae82cd16"
CHANGED = {"scripts/variant/file-based-apps/runtime.cjs", "scripts/variant/file-based-apps/test-runtime.cjs"}
NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs", "test-runtime.cjs"}
NODE = Path("C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
PYTHON = Path("C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")
PATTERN = "^(?:graceful disposal cancels fresh SDK work|a blocked older terminal cleanup retry|a late rejected terminal retry)"
BASELINE_ERRORS = ["Fresh SDK discovery must not wait for an older terminal deletion",
                   "Older terminal deletion must not hold three fresh same-file callers pending",
                   "A fresh launch must complete before an older retry rejects"]
ADAPTED_TESTS = [
    "an existing output with unavailable journal identity is retained and retried without direct deletion",
    "an incomplete tracked publication is retained when its original disappears before the move",
    "failed cleanup is retried by the next command without removing live session output",
    "cleanup logging failure preserves the original result and failed output can still recover",
    "persistent cleanup failures permit fresh launches and retry only one older output per command",
    "cleanup failure preserves quiet cancellation and the next command recovers its output",
    "command recovery chooses a local failed cleanup instead of introducing another global attempt",
    "command recovery does not wait for or duplicate a local retry while a global pass is already active",
]


def read(file):
    return json.loads(file.read_text(encoding="utf-8-sig"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def binding(file):
    data = file.read_bytes()
    return {"sha256": digest(data), "bytes": len(data)}


def verify(file, record):
    actual = binding(file)
    if actual["sha256"] != record["sha256"] or actual["bytes"] != record.get("bytes", record.get("size")):
        raise ValueError("Recorded bytes differ: " + str(file))
    return actual


def same(left, right):
    return str(Path(left).resolve()).casefold() == str(Path(right).resolve()).casefold()


def normalized(data):
    return data.replace(b"\r\n", b"\n")


def utc(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Expected an aware timestamp")
    return result


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO)


def counts(text, total, failures=0):
    values = {}
    for name in ("tests", "pass", "fail", "cancelled", "skipped", "todo"):
        found = re.findall(r"^(?:ℹ |# )?" + name + r"\s+(\d+)\s*$", text, re.MULTILINE)
        if len(found) != 1:
            raise ValueError("Expected one complete Node count: " + name)
        values[name] = int(found[0])
    if values != {"tests": total, "pass": total - failures, "fail": failures, "cancelled": 0, "skipped": 0, "todo": 0}:
        raise ValueError("Unexpected complete Node counts")
    return values


def validate_units(directory, base):
    if not re.fullmatch(r"[0-9a-f]{40}", base) or git("rev-parse", base + "^{commit}").decode().strip() != base:
        raise ValueError("Pass the complete merged PR44 base commit")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=REPO, check=True)
    manifest = read(directory / "source-manifest.json")
    if manifest["commit"] != base or not same(manifest["worktree"], REPO):
        raise ValueError("Frozen tests must use this worktree over merged PR44")
    files = sorted(name for name in git("ls-files", "--cached", "--others", "--exclude-standard", "scripts/variant").decode().splitlines()
                   if (REPO / name).is_file())
    records = manifest["source"]
    names = [record["path"] for record in records]
    if len(files) != 53 or len(set(names)) != 53 or sorted(names) != files:
        raise ValueError("Expected all 53 current archived variant source files")
    changes = set(git("diff", "--name-only", base, "--", "scripts/variant").decode().splitlines())
    if changes != CHANGED:
        raise ValueError("Only runtime and its test may change under scripts/variant")
    archive = {}
    for record in records:
        name = record["path"]
        verify(REPO / name, record)
        archive[name] = verify(directory / "source" / name, record)
        if name not in CHANGED and normalized((REPO / name).read_bytes()) != normalized(git("show", base + ":" + name)):
            raise ValueError("Unexpected other source difference: " + name)
    for name, executable in (("node", NODE), ("python", PYTHON)):
        if not same(manifest[name]["path"], executable):
            raise ValueError("Unexpected verification runtime: " + name)
        verify(executable, manifest[name])
    suites = ["scripts/variant/file-based-apps/test-" + name + ".cjs" for name in ("classify", "entry", "recovery", "runtime", "web")]
    commands = {
        "node": [str(NODE), "--unhandled-rejections=strict", "--test", *suites],
        "python": [str(PYTHON), "-B", "-m", "unittest", "discover", "-s", "scripts/variant", "-p", "test_*.py", "-v"],
        "driver": [str(NODE), "--unhandled-rejections=strict", "--test", "scripts/variant/lifecycle/host-loss/test-driver.cjs"],
    }
    if (set(manifest["commands"]) != {"node", "python"} or len(manifest["runs"]) != 2
            or len(manifest["additionalRuns"]) != 1 or "baselineDriver" in manifest):
        raise ValueError("Expected five-suite Node/Python and one separate current-driver run")
    rows = {}
    for run, additional in [(run, False) for run in manifest["runs"]] + [(run, True) for run in manifest["additionalRuns"]]:
        name = Path(run["log"]).stem
        if name not in commands or name in rows or additional != (name == "driver"):
            raise ValueError("Unexpected or duplicate verification log")
        argv, expected = run["argv"], commands[name]
        if (not same(argv[0], expected[0]) or argv[1:] != expected[1:]
                or (not additional and argv != manifest["commands"][name])
                or (additional and run["environmentOverrides"] != {})):
            raise ValueError("Exact verification argv or environment overrides differ: " + name)
        result_file, log = directory / (name + "-result.json"), directory / (name + ".log")
        result, text = read(result_file), log.read_text(encoding="utf-8")
        if (result != run["result"] or result["exitCode"] != 0 or (additional and result["expectedExitCode"] != 0)
                or digest(log.read_bytes()) != result["logSha256"]
                or not utc(manifest["frozenUtc"]) <= utc(result["startedUtc"]) <= utc(result["completedUtc"]) <= utc(manifest["finalSourceVerifiedUtc"])):
            raise ValueError("Incomplete or differing natural-exit result: " + name)
        if name == "python":
            if (len(re.findall(r"^Ran 39 tests in [0-9.]+s$", text, re.MULTILINE)) != 1
                    or len(re.findall(r"^OK$", text, re.MULTILINE)) != 1
                    or len(re.findall(r"^test_.* \.\.\. ok$", text, re.MULTILINE)) != 39
                    or re.search(r"^FAILED|skipped=|expected failures", text, re.MULTILINE)):
                raise ValueError("Expected all 39 Python cases without skips/failures")
            totals = {"tests": 39, "pass": 39, "fail": 0, "skipped": 0}
        else:
            totals = counts(text, 230 if name == "node" else 15)
        rows[name] = {"argv": argv, "result": result, "resultFile": binding(result_file), "log": binding(log), "counts": totals}
    return {"directory": str(directory), "manifestFile": binding(directory / "source-manifest.json"),
            "baseCommit": base, "changedProductAndTestPaths": sorted(changes),
            "frozenUtc": manifest["frozenUtc"], "finalSourceVerifiedUtc": manifest["finalSourceVerifiedUtc"],
            "runtimeInputs": {name: manifest[name] for name in ("node", "python")},
            "archivedSource": archive, "allOtherSourcesUnchanged": True, "runs": rows}


def validate_contrast(directory, base):
    manifest = read(directory / "manifest.json")
    if (manifest["baseCommit"] != ORIGINAL_BASE or manifest["pattern"] != PATTERN or manifest["currentSourceUnchanged"] is not True
            or not same(manifest["node"]["path"], NODE) or set(manifest["currentSource"]) != NAMES or len(manifest["runs"]) != 2):
        raise ValueError("Expected the original frozen three-case contrast")
    verify(NODE, manifest["node"])
    rows = {}
    for run in manifest["runs"]:
        variant = run["variant"]
        if variant not in ("baseline", "changed") or variant in rows or set(run["copiedSource"]) != NAMES:
            raise ValueError("Contrast source set or variant differs")
        argv = run["argv"]
        if (not same(argv[0], NODE) or argv[1:-1] != ["--unhandled-rejections=strict", "--test", "--test-reporter=spec", "--test-name-pattern", PATTERN]
                or not same(argv[-1], directory / variant / "test-runtime.cjs")):
            raise ValueError("Exact strict contrast argv differs")
        copies = {name: verify(directory / variant / name, record) for name, record in run["copiedSource"].items()}
        log = directory / (variant + ".log")
        if not same(run["log"]["path"], log):
            raise ValueError("Contrast log path differs")
        verify(log, run["log"])
        text = log.read_text(encoding="utf-8")
        totals = counts(text, 3, 3 if variant == "baseline" else 0)
        exit_code = 1 if variant == "baseline" else 0
        if (run["counts"] != {key: totals[key] for key in ("tests", "pass", "fail", "skipped")}
                or run["exitCode"] != exit_code or run["expectedExitCode"] != exit_code
                or not utc(run["startedUtc"]) <= utc(run["completedUtc"]) <= utc(manifest["completedUtc"])):
            raise ValueError("Original contrast result or timestamps differ")
        if variant == "baseline" and not all(message in text for message in BASELINE_ERRORS):
            raise ValueError("Baseline must fail at the intended foreground-progress assertions")
        rows[variant] = {"argv": argv, "exitCode": exit_code, "startedUtc": run["startedUtc"], "completedUtc": run["completedUtc"],
                         "counts": totals, "log": binding(log), "copiedSource": copies}
    for name in NAMES:
        before = (directory / "baseline" / name).read_bytes()
        after = (directory / "changed" / name).read_bytes()
        current = (MODULES / name).read_bytes()
        if normalized(after) != normalized(current):
            raise ValueError("Contrast changed/current source differs beyond checkout line endings: " + name)
        verify(directory / "changed" / name, manifest["currentSource"][name])
        if name == "runtime.cjs":
            original = git("show", ORIGINAL_BASE + ":scripts/variant/file-based-apps/runtime.cjs")
            merged = git("show", base + ":scripts/variant/file-based-apps/runtime.cjs")
            if before != original or normalized(before) != normalized(merged):
                raise ValueError("Baseline must equal original Git blob and normalized merged PR44 runtime")
        elif before != after:
            raise ValueError("Only runtime may differ between contrast copies: " + name)
        if name not in ("runtime.cjs", "test-runtime.cjs") and normalized(current) != normalized(git("show", base + ":scripts/variant/file-based-apps/" + name)):
            raise ValueError("An unrelated product module changed")
    return {"directory": str(directory), "manifestFile": binding(directory / "manifest.json"), "originalBaseCommit": ORIGINAL_BASE,
            "mergedBaseRuntimeNormalizedEqual": True, "sameChangedTestsForBothImplementations": True,
            "currentNormalizedSourceMatches": True, "runs": rows,
            "interpretation": "Identical changed tests fail at the three intended progress assertions against the previous runtime and pass against the new runtime. Dependency-injected providers use real temporary filesystem paths; this is not installed-editor measurement."}


def build_summary(tests, contrast, base_commit):
    return {"schema": 1, "kind": "foreground-independent known-terminal cleanup retry",
            "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18", "baseCommit": base_commit,
            "productChange": True, "qualification": False, "installedEditorRun": False,
            "verification": validate_units(tests.resolve(), base_commit),
            "regressionContrast": validate_contrast(contrast.resolve(), base_commit), "collector": binding(Path(__file__)),
            "developmentObservations": {
                "provenance": "Source-author report of development tool output only; complete raw development logs were not archived. These are not final validation records.",
                "initialRuntimeRun": {"toolChunk": "f6c9df", "exitCode": 1, "tests": 122, "pass": 114, "fail": 8,
                                      "cancelled": 0, "skipped": 0, "durationMilliseconds": 3162.047, "testNames": ADAPTED_TESTS},
                "reason": "Existing assertions expected older retry/deletion/log completion immediately after a fresh launch. Explicit waits now observe background completion while retaining ownership/error/fairness assertions without assuming concurrent failure completion order.",
                "laterFocusedRuntimeRun": {"toolChunk": "0787c9", "exitCode": 0, "tests": 122, "pass": 122, "fail": 0,
                                           "cancelled": 0, "skipped": 0, "durationMilliseconds": 3843.4786}},
            "limits": ["Only an older known-terminal cleanup retry leaves the fresh command's foreground await. Drain/output ownership remains until real settlement, including late failure.",
                       "Current-run failure cleanup, save, certificate work, editor handoff/session lifetime and non-cooperative SDK/filesystem waits remain outside this change; full AC6 stays open.",
                       "Issue45's unexplained unrelated B pause and failed installed compiler observation remain unresolved and are not overridden by unit results.",
                       "No new installed-editor, macOS, physical F5/menu, calibrated budget, descendant cleanup, language-service readiness or release qualification is claimed."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--contrast", type=Path, required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    value = build_summary(args.tests, args.contrast, args.base_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
