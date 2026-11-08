"""Validate save-phase progress and retained ordinary compiler-retry evidence."""
import argparse
import copy
import difflib
import importlib.util
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import struct
import zipfile
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODULES = REPO / "scripts/variant/file-based-apps"
BASE = "9cf30ef64ba53aea3dd153d802b43ec2d7068d01"
SOURCE_COMMIT = "bb5d03624d01c4e89331d24cc832e68d5691b061"
NODE_TESTS = 243
CONTRAST_TESTS = 6
CONTRAST_FAILURES = 6
PATTERN = "^save progress"
BASELINE_ERRORS = [
    "The save must be visible inside the cancellable command progress\n+ actual - expected\n\n+ []\n- [\n-   'Saving C# file'\n- ]",
    "Expected values to be strictly deep-equal:\n+ actual - expected\n\n+ []\n- [\n-   'Saving C# file'\n- ]",
    "Expected values to be strictly equal:\n\ntrue !== false",
    "An already cancelled progress token must precede the save provider\n\n1 !== 0",
    "Expected values to be strictly deep-equal:\n+ actual - expected\n\n+ []\n- [\n-   'Saving C# file'\n- ]",
    "Expected values to be strictly deep-equal:\n+ actual - expected\n\n+ []\n- [\n-   'Saving C# file'\n- ]"
]
BASELINE_TEST_NAMES = [
    "save progress retains a cancelled save for coalesced callers and a corrected retry",
    "save progress observes a late rejection after Cancel without starting preparation or notifying",
    "save progress cancellation before dispatch prevents the editor save and SDK work",
    "save progress honors an already cancelled notification before saving a dirty document",
    "save progress excludes save time from preparation while retaining total phase duration",
    "save progress permits another file while a cancelled save retains its captured document"
]
CHANGED = {"scripts/variant/file-based-apps/runtime.cjs", "scripts/variant/file-based-apps/test-runtime.cjs"}
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}
NAMES = MODULE_NAMES | {"test-runtime.cjs"}
NODE = Path("C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
PYTHON = Path("C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")
BASE_VSIX_SHA = "0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5"
DEPENDENCY_SHA = "a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541"
PREPARATION_HELPER_SHA = "efc9269e48c83ac03a5ede2b24fbe92ffb2e38d06009a4deeabd7e39f09663e3"
TRACE_IMPLEMENTATIONS = (
    ("resources/app/out/mainImpl.js", "9ac99204945c5b3fff2baf2260230a66329c4c3faeb4634f3b1b23b639a476fa"),
    ("resources/app/out/vs/workbench/workbench.desktop.main.js", "8d84032a329de378286c48b1524a126eb080b96b45ef5cf300c62f85884a1fd5"),
    ("resources/app/out/vs/workbench/api/node/extensionHostProcess.js", "ad8fbac184bee8bf1e027c95f0b72130c1c6eaed9ff732d7097c1a4f4eb097c2"),
)
BUILD_COLLECTOR = REPO / "docs/research/build-failure-retry-2026-11-05/summarize.py"


def load_module(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_module("save_progress_build_summary", BUILD_COLLECTOR)
web = build.web


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
    if base != BASE or not re.fullmatch(r"[0-9a-f]{40}", base) or git("rev-parse", base + "^{commit}").decode().strip() != base:
        raise ValueError("Pass the complete merged PR47 base commit")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=REPO, check=True)
    manifest = read(directory / "source-manifest.json")
    if manifest["commit"] != base or not same(manifest["worktree"], REPO):
        raise ValueError("Frozen tests must use this worktree over merged PR47")
    files = sorted(name for name in git("ls-files", "--cached", "--others", "--exclude-standard", "scripts/variant").decode().splitlines()
                   if (REPO / name).is_file())
    records = manifest["source"]
    names = [record["path"] for record in records]
    if len(files) != 53 or len(set(names)) != 53 or sorted(names) != files:
        raise ValueError("Expected all 53 current archived variant source files")
    changes = set(git("diff", "--name-only", base, "--", "scripts/variant").decode().splitlines())
    if changes != CHANGED:
        raise ValueError("Only runtime and its test may change under scripts/variant; the shared lifecycle harness must match merged PR47")
    archive = {}
    for record in records:
        name = record["path"]
        verify(REPO / name, record)
        if normalized((REPO / name).read_bytes()) != normalized(git("show", SOURCE_COMMIT + ":" + name)):
            raise ValueError("Frozen current source differs from its implementation commit: " + name)
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
            totals = counts(text, NODE_TESTS if name == "node" else 15)
        rows[name] = {"argv": argv, "result": result, "resultFile": binding(result_file), "log": binding(log), "counts": totals}
    return {"directory": str(directory), "manifestFile": binding(directory / "source-manifest.json"),
            "baseCommit": base, "changedProductAndTestPaths": sorted(changes),
            "frozenUtc": manifest["frozenUtc"], "finalSourceVerifiedUtc": manifest["finalSourceVerifiedUtc"],
            "runtimeInputs": {name: manifest[name] for name in ("node", "python")},
            "archivedSource": archive, "allOtherSourcesUnchanged": True, "runs": rows}



def assertion_errors(text):
    blocks = re.findall(r"^  error: \|-\n((?:    .*\n)+)", text, re.MULTILINE)
    if len(re.findall(r"^  error:", text, re.MULTILINE)) != len(blocks):
        raise ValueError("Expected the exact retained multiline save-progress assertion format")
    return ["\n".join(line[4:] for line in block.splitlines()).rstrip() for block in blocks]


def validate_contrast(directory, base):
    manifest = read(directory / "manifest.json")
    if (manifest["baseCommit"] != BASE or manifest["pattern"] != PATTERN or manifest["currentSourceUnchanged"] is not True
            or not same(manifest["node"]["path"], NODE) or set(manifest["currentSource"]) != NAMES or len(manifest["runs"]) != 2):
        raise ValueError("Expected the frozen selected save-progress contrast")
    verify(NODE, manifest["node"])
    rows = {}
    for run in manifest["runs"]:
        variant = run["variant"]
        if variant not in ("baseline", "changed") or variant in rows or set(run["copiedSource"]) != NAMES:
            raise ValueError("Contrast source set or variant differs")
        argv = run["argv"]
        if (not same(argv[0], NODE) or argv[1:-1] != ["--unhandled-rejections=strict", "--test", "--test-reporter=tap", "--test-name-pattern", PATTERN]
                or not same(argv[-1], directory / variant / "test-runtime.cjs")):
            raise ValueError("Exact strict contrast argv differs")
        copies = {name: verify(directory / variant / name, record) for name, record in run["copiedSource"].items()}
        log = directory / (variant + ".log")
        if not same(run["log"]["path"], log):
            raise ValueError("Contrast log path differs")
        verify(log, run["log"])
        text = log.read_text(encoding="utf-8")
        totals = counts(text, CONTRAST_TESTS, CONTRAST_FAILURES if variant == "baseline" else 0)
        exit_code = 1 if variant == "baseline" else 0
        if (run["counts"] != {**totals, "suites": 0}
                or re.findall(r"^# suites (\d+)\s*$", text, re.MULTILINE) != ["0"]
                or run["exitCode"] != exit_code or run["expectedExitCode"] != exit_code
                or not utc(run["startedUtc"]) <= utc(run["completedUtc"]) <= utc(manifest["completedUtc"])):
            raise ValueError("Contrast result or timestamps differ")
        if variant == "baseline" and (assertion_errors(text) != BASELINE_ERRORS
                or re.findall(r"^not ok \d+ - (.*)$", text, re.MULTILINE) != BASELINE_TEST_NAMES
                or len(re.findall(r"^  code: 'ERR_ASSERTION'$", text, re.MULTILINE)) != CONTRAST_FAILURES):
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
            original = git("show", BASE + ":scripts/variant/file-based-apps/runtime.cjs")
            merged = git("show", base + ":scripts/variant/file-based-apps/runtime.cjs")
            if before != original or normalized(before) != normalized(merged):
                raise ValueError("Baseline must equal the exact merged PR47 Git runtime blob")
        elif before != after:
            raise ValueError("Only runtime may differ between contrast copies: " + name)
        if name not in ("runtime.cjs", "test-runtime.cjs") and normalized(current) != normalized(git("show", base + ":scripts/variant/file-based-apps/" + name)):
            raise ValueError("An unrelated product module changed")
    return {"directory": str(directory), "manifestFile": binding(directory / "manifest.json"), "originalBaseCommit": BASE,
            "mergedBaseRuntimeNormalizedEqual": True, "sameChangedTestsForBothImplementations": True,
            "currentNormalizedSourceMatches": True, "runs": rows,
            "interpretation": "Identical changed save-progress tests run against the merged PR47 Git runtime and the current runtime; exact retained counts and intended baseline assertion failures remain separate from final full-suite verification. Dependency-injected providers use real temporary filesystem paths; this is not installed-editor measurement."}


def inside(directory, file):
    return Path(file).resolve().is_relative_to(directory.resolve()) and not same(directory, file)


def check_file(file, record):
    if not file.is_file() or file.is_symlink():
        raise ValueError("Expected a retained ordinary file: " + str(file))
    return verify(file, record)


def pe_machine(file):
    with file.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Expected a native Windows executable")
        stream.seek(0x3c)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError("Expected a valid PE executable")
        return struct.unpack("<H", stream.read(2))[0]


def validate_diagnostic_launcher(work, expected, result, base_vsix):
    before_file, baseline_file, diagnostic_file = (work / name for name in
        ("expected-before-diagnostic.json", "baseline-run.ps1", "diagnostic-run.ps1"))
    before = read(before_file)
    baseline = (REPO / "scripts/variant/lifecycle/run.ps1").read_bytes()
    needle = b"'--skip-welcome', '--skip-release-notes',"
    replacement = b"'--log', 'trace', '--skip-welcome', '--skip-release-notes',"
    if (baseline.count(needle) != 1 or baseline_file.read_bytes() != baseline
            or diagnostic_file.read_bytes() != baseline.replace(needle, replacement, 1)):
        raise ValueError("The copied launcher must add only --log trace to exact current shared bytes")
    current_harness = {name: digest((REPO / "scripts/variant/lifecycle" / name).read_bytes())
                       for name in ("prepare.py", "run.ps1", "driver.cjs", "extension-test.cjs", "fixtures/web.cs")}
    changed = copy.deepcopy(before)
    changed["harness"]["run.ps1"] = digest(diagnostic_file.read_bytes())
    if (before["harness"] != current_harness or expected != changed or result["expected"] != expected
            or before["candidate"]["sourceCommit"] != SOURCE_COMMIT):
        raise ValueError("Only the expectation's diagnostic launcher hash may change")
    for name in ("driver.cjs", "extension-test.cjs"):
        if digest((work / "driver" / name).read_bytes()) != current_harness[name]:
            raise ValueError("Executed harness differs from current source: " + name)
    if digest((work / "workspace/b.cs").read_bytes()) != current_harness["fixtures/web.cs"]:
        raise ValueError("Independent B must preserve the exact ordinary current fixture")
    receipt_file = work / "diagnostic-preparation.json"
    receipt = read(receipt_file)
    expected_diff = "".join(difflib.unified_diff(baseline.decode().splitlines(keepends=True),
        diagnostic_file.read_bytes().decode().splitlines(keepends=True),
        fromfile="baseline-run.ps1", tofile="diagnostic-run.ps1"))
    if (receipt["schema"] != 1 or receipt["baseCommit"] != SOURCE_COMMIT
            or receipt["scenario"] != "build-failure-retry" or receipt["cycles"] != expected["cycles"]
            or receipt["expectedSemanticChanges"] != ["harness.run.ps1"]
            or receipt["addedAppArguments"] != ["--log", "trace"] or receipt["addedLauncherBytes"] != 18
            or receipt["sourceCommit"] != SOURCE_COMMIT or receipt["exactDiff"] != expected_diff
            or any(receipt[name] != expected[name] for name in ("candidate", "dependency", "editor", "sdk"))
            or not receipt["controls"] or any(value is not True for value in receipt["controls"].values())):
        raise ValueError("Exact trace-only diagnostic preparation receipt differs")
    for name, path in (("baselineLauncher", REPO / "scripts/variant/lifecycle/run.ps1"),
                       ("retainedBaselineLauncher", baseline_file), ("diagnosticLauncher", diagnostic_file),
                       ("expectedBefore", before_file), ("expectedAfter", work / "expected.json")):
        if not same(receipt[name]["path"], path):
            raise ValueError("Diagnostic receipt binds an unexpected path")
        check_file(path, receipt[name])
    utc(receipt["preparedUtc"])
    helper = work.parent / "prepare-smoke.py"
    if (not same(receipt["helper"]["path"], helper) or receipt["helper"]["sha256"] != PREPARATION_HELPER_SHA):
        raise ValueError("Expected the exact frozen one-shot preparation helper")
    check_file(helper, receipt["helper"])
    inputs = {"baseVsix": base_vsix, "runtimeVsix": Path(expected["dependency"]["path"]),
              "editor": Path(expected["editor"]["executable"]), "editorCli": Path(expected["editor"]["cli"]),
              "dotnet": Path(expected["sdk"]["executable"])}
    if set(receipt["inputs"]) != set(inputs):
        raise ValueError("Preparation must retain every exact pinned input")
    for name, path in inputs.items():
        if not same(receipt["inputs"][name]["path"], path):
            raise ValueError("Preparation input path differs: " + name)
        check_file(path, receipt["inputs"][name])
    source_names = {"scripts/variant/file-based-apps/" + name for name in MODULE_NAMES} | {
        "scripts/variant/lifecycle/" + name for name in current_harness}
    if (set(receipt["sourceBindingsBefore"]) != source_names
            or receipt["sourceBindingsBefore"] != receipt["sourceBindingsAfter"]):
        raise ValueError("All product/shared-harness source bindings must remain identical during preparation")
    for name, proof in receipt["sourceBindingsBefore"].items():
        path = REPO / name
        if not same(proof["path"], path) or normalized(path.read_bytes()) != normalized(git("show", SOURCE_COMMIT + ":" + name)):
            raise ValueError("Prepared source must match the exact implementation commit: " + name)
        check_file(path, proof)
    traces = receipt["editorTraceImplementationBindings"]
    if len(traces) != len(TRACE_IMPLEMENTATIONS):
        raise ValueError("All three exact editor trace implementation files must be bound")
    for proof, (relative, sha256) in zip(traces, TRACE_IMPLEMENTATIONS):
        path = Path(expected["editor"]["executable"]).parent / relative
        if not same(proof["path"], path) or proof["sha256"] != sha256:
            raise ValueError("Pinned native editor trace implementation differs")
        check_file(path, proof)
    prior = work.parent.parent / "pr44-review-2026-11-08/c02"
    if set(receipt["priorBindings"]) != {"expected.json", "diagnostic-preparation.json"}:
        raise ValueError("Original PR44 preparation evidence must remain separately bound")
    for name, proof in receipt["priorBindings"].items():
        if not same(proof["path"], prior / name):
            raise ValueError("Historical preparation input path differs")
        check_file(prior / name, proof)
    command = [str(PYTHON), "-B", str(REPO / "scripts/variant/lifecycle/prepare.py"),
               "--base-vsix", str(base_vsix), "--base-sha256", BASE_VSIX_SHA,
               "--runtime-vsix", str(inputs["runtimeVsix"]), "--runtime-sha256", DEPENDENCY_SHA,
               "--editor", str(inputs["editor"]), "--editor-cli", str(inputs["editorCli"]),
               "--dotnet", str(inputs["dotnet"]), "--sdk-version", "10.0.403",
               "--scenario", "build-failure-retry", "--cycles", "3", "--work-dir", str(work)]
    if not same(receipt["prepareCommand"][0], PYTHON) or receipt["prepareCommand"][1:] != command[1:]:
        raise ValueError("Exact one-shot native preparation argv differs")
    quote = lambda file: '"' + str(file) + '"'
    arguments = ["--locale", "en", "--user-data-dir", quote(work / "profile"), "--extensions-dir", quote(work / "extensions"),
                 "--extensionDevelopmentPath", quote(work / "driver"), "--extensionTestsPath", quote(work / "driver/extension-test.cjs"),
                 "--log", "trace", "--skip-welcome", "--skip-release-notes", "--disable-gpu", "--disable-workspace-trust", "--no-sandbox", quote(work / "workspace")]
    launch, launcher = read(work / "launch.json"), read(work / "launcher-result.json")
    if (launch["arguments"] != arguments or launch["freshProfile"] is not True
            or launch["visibleWindowRequested"] is not False or launcher["visibleWindowRequested"] is not False
            or not same(launch["work"], work)):
        raise ValueError("Actual isolated editor launch must have only the intended trace argument delta")
    return {"currentSharedHarness": current_harness, "preparedHarness": expected["harness"],
            "preparationReceipt": {"file": binding(receipt_file), "record": receipt},
            "actualLaunch": launch,
            "retainedFiles": {path.name: binding(path) for path in (before_file, baseline_file, diagnostic_file)},
            "preparationInterpretation": "SourceBindingsBefore/After and productSourceUnchanged mean unchanged during preparation of this implementation commit, whose runtime differs from the merged base. The raw editorNotRun control records preparation time before the later single installed smoke."}


def validate_product(work, expected, result, base_vsix):
    candidate = expected["candidate"]
    if (candidate["sourceCommit"] != SOURCE_COMMIT or not candidate["localOnly"] or candidate["published"]
            or candidate["target"] != "win32-arm64" or candidate["version"] != "11.7.18004"
            or set(candidate["ownedModules"]) != MODULE_NAMES or candidate["baseVsixSha256"] != BASE_VSIX_SHA
            or digest(base_vsix.read_bytes()) != BASE_VSIX_SHA
            or not same(candidate["path"], work / "local-lifecycle.vsix")
            or digest(Path(candidate["path"]).read_bytes()) != candidate["sha256"]
            or result["installedModules"] != candidate["ownedModules"]):
        raise ValueError("Expected exact local native candidate bytes and committed current product identity")
    identity = {name: candidate[name] for name in ("baseVsixSha256", "sourceCommit", "target", "ownedModules")}
    if digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()) != candidate["buildId"]:
        raise ValueError("Content-derived local candidate build identity differs")
    if (expected["editor"]["version"] != "1.143.17232" or expected["editor"]["machine"] != "arm64"
            or expected["editor"]["commit"] != "c072cf642cbbadabefa22f39c58cc902a8b7427f"
            or result["editorApiVersion"] != "1.143.1" or expected["sdk"]["version"] != "10.0.403"
            or expected["dependency"]["version"] != "3.2.0" or expected["dependency"]["sha256"] != DEPENDENCY_SHA):
        raise ValueError("Expected the pinned native Windows ARM64 editor, SDK and runtime dependency")
    native = {}
    for name in ("editor", "sdk"):
        file = Path(expected[name]["executable"])
        if digest(file.read_bytes()) != expected[name]["sha256"] or pe_machine(file) != 0xaa64:
            raise ValueError("Pinned native ARM64 executable differs: " + name)
        native[name] = {"path": str(file), **binding(file), "peMachine": "0xAA64"}
    dependency = Path(expected["dependency"]["path"])
    if digest(dependency.read_bytes()) != DEPENDENCY_SHA:
        raise ValueError("Pinned dependency archive differs")
    installed = Path(result["installedExtension"]["path"])
    dependency_installed = Path(result["installedDependency"]["path"])
    if not inside(work / "extensions", installed) or not inside(work / "extensions", dependency_installed):
        raise ValueError("Candidate and dependency must be normally installed in the exact isolated profile")
    installed_package = read(installed / "package.json")
    dependency_package = read(dependency_installed / "package.json")
    if (not installed_package.get("__metadata") or installed_package["version"] != candidate["version"]
            or result["installedExtension"]["version"] != candidate["version"]
            or result["installedDependency"]["version"] != "3.2.0"
            or (dependency_package["publisher"], dependency_package["name"], dependency_package["version"])
                != ("ms-dotnettools", "vscode-dotnet-runtime", "3.2.0")):
        raise ValueError("Normal installed extension/dependency metadata differs")
    allowed = {"extension/package.json", "extension.vsixmanifest"} | {"extension/.netcoredbg/" + name for name in MODULE_NAMES}
    modules = {}
    with zipfile.ZipFile(base_vsix) as original, zipfile.ZipFile(candidate["path"]) as archive:
        if (len(archive.namelist()) != len(set(archive.namelist()))
                or set(archive.namelist()) != set(original.namelist()) | allowed):
            raise ValueError("Candidate archive entry set differs or contains duplicates")
        package = json.loads(archive.read("extension/package.json"))
        expected_package = json.loads(original.read("extension/package.json"))
        expected_package["displayName"] = "C# (netcoredbg) LOCAL WEB LIFECYCLE TEST"
        expected_package["netcoredbgBuild"].update(localCandidate=True,
            lifecycleBuildId=candidate["buildId"], lifecycleSourceCommit=SOURCE_COMMIT)
        expected_manifest = ET.fromstring(original.read("extension.vsixmanifest"))
        for element in expected_manifest.iter():
            if element.tag.rsplit("}", 1)[-1] == "DisplayName":
                element.text = expected_package["displayName"]
        installed_content = {name: value for name, value in installed_package.items() if name != "__metadata"}
        if (package != expected_package or installed_content != package
                or archive.read("extension/package.json") != (json.dumps(expected_package, indent=2) + "\n").encode()
                or archive.read("extension.vsixmanifest") != ET.tostring(expected_manifest, encoding="utf-8", xml_declaration=True)):
            raise ValueError("Only reviewed local-candidate metadata may differ in package/VSIX manifests")
        for metadata in (package["netcoredbgBuild"], installed_package["netcoredbgBuild"], result["installedExtension"]["build"]):
            if (metadata["target"] != "win32-arm64" or metadata["lifecycleBuildId"] != candidate["buildId"]
                    or metadata["lifecycleSourceCommit"] != SOURCE_COMMIT or metadata["localCandidate"] is not True):
                raise ValueError("Packaged/installed/observed candidate build metadata differs")
        for name in sorted(MODULE_NAMES):
            current = (MODULES / name).read_bytes()
            if (normalized(current) != normalized(git("show", SOURCE_COMMIT + ":scripts/variant/file-based-apps/" + name))
                    or digest(current) != candidate["ownedModules"][name]
                    or digest(archive.read("extension/.netcoredbg/" + name)) != digest(current)
                    or digest((installed / ".netcoredbg" / name).read_bytes()) != digest(current)):
                raise ValueError("Current/Git/archive/installed product module bytes differ: " + name)
            if name != "runtime.cjs" and normalized(current) != normalized(git("show", BASE + ":scripts/variant/file-based-apps/" + name)):
                raise ValueError("Only runtime may change among product modules")
            modules[name] = binding(MODULES / name)
        immutable = {name: digest(original.read(name)) for name in original.namelist() if name not in allowed}
        if (any(archive.read(name) != original.read(name) for name in immutable)
                or len(immutable) != candidate["unchangedEntries"]
                or digest(json.dumps(immutable, sort_keys=True).encode()) != candidate["unchangedPayloadDigest"]):
            raise ValueError("Non-owned candidate archive payload differs from the pinned release base")
        adapter = installed / ".debugger/netcoredbg/netcoredbg.exe"
        adapter_bytes = archive.read("extension/.debugger/netcoredbg/netcoredbg.exe")
        if adapter.read_bytes() != adapter_bytes or pe_machine(adapter) != 0xaa64:
            raise ValueError("Installed native ARM64 adapter differs from the unchanged archive/base payload")
        native["adapter"] = {"path": str(adapter), **binding(adapter), "peMachine": "0xAA64",
                             "archiveSha256": digest(adapter_bytes)}
    return {"sourceCommit": SOURCE_COMMIT, "baseCommit": BASE, "onlyRuntimeProductChange": True,
            "baseVsix": {"path": str(base_vsix), **binding(base_vsix)}, "candidate": candidate,
            "currentArchiveInstalledModules": modules, "nativeExecutables": native,
            "dependencyArchive": {"path": str(dependency), **binding(dependency)},
            "unchangedPayloadEntries": len(immutable), "unchangedPayloadDigest": candidate["unchangedPayloadDigest"],
            "addedOwnedArchiveEntries": sorted(set(archive.namelist()) - set(original.namelist()))}


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
        if " ".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in args) != payload:
            raise ValueError("Logged process arguments lost their exact JSON boundaries")
        if len(args) >= 2 and args[0] == "build" and same(args[1], source):
            commands.append({"args": args, "output": args[args.index("--output") + 1]})
    return commands



def validate_save_phase_visibility(log, source):
    tail = log_tail(log)
    lines = tail.splitlines()
    started = [index for index, line in enumerate(lines) if line == "Phase started: Saving C# file"]
    completed = [(index, match) for index, line in enumerate(lines)
                 if (match := re.fullmatch(r"Phase completed: Saving C# file \((\d+) ms; total (\d+) ms\)", line))]
    sdk = [index for index, line in enumerate(lines) if line == "Phase started: Locating .NET SDK"]
    build_phase = [index for index, line in enumerate(lines) if line == "Phase started: Building file-based app"]
    commands = build_commands(tail, source)
    builds = [index for index, line in enumerate(lines) if line.startswith('dotnet "build" ')]
    if (len(started) != 1 or len(completed) != 1 or len(sdk) != 1 or len(build_phase) != 1
            or len(commands) != 1 or len(builds) != 1
            or not started[0] < completed[0][0] < sdk[0] < build_phase[0] < builds[0]
            or any(line.startswith(("Phase failed: Saving C# file", "Phase cancelled: Saving C# file", "Phase not saved: Saving C# file")) for line in lines)):
        raise ValueError("One actual dirty save must visibly start/complete before SDK/build in the exact retained native log slice")
    phase_ms, total_ms = map(int, completed[0][1].groups())
    return {"log": log, "startedLine": lines[started[0]], "completedLine": lines[completed[0][0]],
            "sdkStartedLine": lines[sdk[0]], "buildStartedLine": lines[build_phase[0]],
            "lineOrder": {"saveStarted": started[0], "saveCompleted": completed[0][0], "sdkStarted": sdk[0],
                          "buildStarted": build_phase[0], "buildCommand": builds[0]},
            "reportedSavePhaseMilliseconds": phase_ms, "reportedTotalAtSaveCompletionMilliseconds": total_ms,
            "interpretation": "Ordinary installed dirty-save phase visibility and ordering in a bound UTF-16-offset log slice; not native save-cancellation or hard-deadline measurement"}


def validate_smoke(work, base_vsix):
    expected, result = read(work / "expected.json"), read(work / "result.json")
    scope = result["scope"]
    if (expected["scenario"] != "build-failure-retry" or expected["cycles"] != 3
            or scope["scenario"] != "build-failure-retry" or scope["platform"] != "win32-arm64"
            or scope["invocation"] != "command-api" or scope["actualCompilerFailure"] is not True
            or not scope["installedCandidate"] or not scope["localOnly"]
            or any(scope[name] for name in ("physicalF5", "macOS", "qualification", "published", "hostReload", "injectedTargetRuntime", "injectedCancellationToken"))
            or result["cleanup"] or result.get("observedProductGap")
            or any(result[name] for name in ("cancelledBuildAttempts", "cancelledHandoffAttempts", "failedWebProfileAttempts", "failedSdkSelectionAttempts", "failedHandoffAttempts", "failedNativeHostAttempts"))):
        raise ValueError("Expected one ordinary installed compiler-failure/retry smoke without injected faults or fallback cleanup")
    diagnostic = validate_diagnostic_launcher(work, expected, result, base_vsix)
    product = validate_product(work, expected, result, base_vsix)
    # The shared collectors remain unchanged. Only optional current-run.ps1
    # equality is disabled here, replaced by the stricter exact-one-delta check.
    summary = build.summarize_run(work, False)
    attempts = result["failedBuildAttempts"]
    if (len(attempts) != 1 or len(result["launches"]) != expected["cycles"] + 1
            or {launch["label"] for launch in result["launches"]} != {"A-0", "B", "A-1", "A-2"}
            or any(phase["outcome"] != "passed" for phase in result["phases"])):
        raise ValueError("Expected one actual compiler failure and all three ordinary A Stop/retry cycles plus B")
    attempt = attempts[0]
    source = work / "workspace/a.cs"
    if (attempt["commandResult"] is not False or attempt["commandPending"] is not False
            or not same(attempt["source"], source) or attempt["capturedSessions"]
            or attempt.get("sessionId") is not None or attempt.get("pid") is not None
            or not attempt["sourceSaved"] or not attempt["noSession"]):
        raise ValueError("The ordinary failed command must save source and return false without a captured session/process")
    failed_tail = log_tail(attempt["log"])
    failed_commands = build_commands(failed_tail, source)
    if (len(failed_commands) != 1 or failed_commands != attempt["log"]["buildCommands"]
            or not same(failed_commands[0]["output"], attempt["output"])
            or not same(Path(attempt["output"]) / "FileApp.dll", attempt["program"])
            or not same(Path(attempt["output"]).parent.parent, attempt["base"])
            or not inside(work, attempt["output"]) or Path(attempt["output"]).exists()
            or not any("CS0103" in line for line in failed_tail.splitlines())
            or not any(line.startswith("Phase failed: Building file-based app") for line in failed_tail.splitlines())
            or "Phase started: Starting netcoredbg" in failed_tail):
        raise ValueError("Exact retained compiler log must bind one failed build and its eventually removed owned output")
    coalesced = result["coalescedRetry"]
    corrected = next(launch for launch in result["launches"] if launch["sessionId"] == coalesced["sessionId"])
    retry_tail = log_tail(coalesced["log"])
    dirty_check = "Dirty compiler correction retries with three concurrent commands sharing one build/session and fresh output while B survives"
    if result["checks"].count(dirty_check) != 1 or attempt["sourceSaved"] is not True:
        raise ValueError("Actual compiler saved-source flag and exact executed dirty-correction check must remain retained")
    save_visibility = {
        "failedCompilerAttempt": validate_save_phase_visibility(attempt["log"], source),
        "correctedCoalescedRetry": validate_save_phase_visibility(coalesced["log"], source),
        "failedAttemptSourceSaved": attempt["sourceSaved"], "dirtyCorrectionCheck": dirty_check,
        "scope": "Ordinary native save progress visibility only; cancellation/held save providers are unit controls",
    }
    if (not same(coalesced["failedOutput"], attempt["output"]) or same(coalesced["output"], attempt["output"])
            or not same(coalesced["output"], corrected["output"])
            or build_commands(retry_tail, source) != coalesced["log"]["buildCommands"]
            or len(coalesced["log"]["buildCommands"]) != 1
            or any("CS0103" in line for line in retry_tail.splitlines())
            or not any(line.startswith("Phase completed: Starting netcoredbg") for line in retry_tail.splitlines())):
        raise ValueError("Three corrected callers must share exactly one successful fresh build/session/output")
    if (attempt["returnedAtMilliseconds"] < attempt["invokedAtMilliseconds"]
            or any(attempt[name] < attempt["returnedAtMilliseconds"] for name in ("outputRemovedAtMilliseconds", "portReusableAtMilliseconds"))
            or any(Path(launch["output"]).exists() for launch in result["launches"])):
        raise ValueError("Resource samples must occur after return and all exact captured outputs must remain absent")
    for name in ("terminal-cleanup-v1", "terminal-cleanup-staging-v1"):
        queue = Path(attempt["base"]) / name
        if queue.exists() and any(queue.iterdir()):
            raise ValueError("Exact owned terminal queues must remain empty after completed smoke")
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    if any(row["event"] in ("editor-start", "dap-send", "dap-receive", "adapter-error")
           and row.get("detail", {}).get("label") == attempt["label"] for row in trace):
        raise ValueError("Failed compiler token must not produce adapter/session/DAP events")
    b = next(launch for launch in result["launches"] if launch["label"] == "B")
    checkpoints = [row for row in trace if row["event"] == "unrelated-preserved" and row["detail"].get("label") == "B"]
    retry_start = next(row["atMilliseconds"] for row in trace if row["event"] == "phase-start" and row["detail"]["label"] == "A cycle 1 dirty edit and installed-command retry")
    retry_done = next(row["atMilliseconds"] for row in trace if row["event"] == "coalesced-corrected-retry-confirmed")
    after_failure = [row for row in checkpoints if attempt["returnedAtMilliseconds"] <= row["atMilliseconds"] < retry_start]
    after_retry = [row for row in checkpoints if corrected["startedAtMilliseconds"] <= row["atMilliseconds"] <= retry_done]
    if (not after_failure or not after_retry
            or any(row["detail"]["pid"] != b["pid"] or row["detail"]["sessionId"] != b["sessionId"] for row in checkpoints)):
        raise ValueError("Exact unrelated B must be independently observed after both compiler failure and corrected retry")
    raw = dict(summary["rawEvidence"])
    raw.update({path.relative_to(work).as_posix(): binding(path)
                for path in sorted((work / "profile/logs").rglob("*")) if path.is_file()})
    raw.update({name: binding(work / name) for name in ("diagnostic-preparation.json", "expected-before-diagnostic.json", "baseline-run.ps1", "diagnostic-run.ps1")})
    return {"control": summary, "productIdentity": product, "traceOnlyLauncher": diagnostic,
            "compilerFailure": attempt, "coalescedRetry": coalesced, "saveProgressVisibility": save_visibility,
            "bPreservedAfterFailure": after_failure, "bPreservedAfterRetry": after_retry, "rawEvidence": raw,
            "sampling": "Post-return eventual output/queue/port observations and discrete B checkpoints; no exact deletion ordering or continuous liveness claim"}


def validate_failed_smoke(work):
    launcher = read(work / "launcher-result.json")
    result = read(work / "result.json") if (work / "result.json").is_file() else None
    if launcher.get("success") is not False or not (launcher.get("error") or result and result.get("firstFailure")):
        raise ValueError("A retained failed smoke must keep its original explicit failure")
    raw = web.raw_files(work)
    raw.update(build.output_logs(work))
    raw.update({path.relative_to(work).as_posix(): binding(path)
                for path in sorted((work / "profile/logs").rglob("*")) if path.is_file()})
    for name in ("diagnostic-preparation.json", "expected-before-diagnostic.json", "baseline-run.ps1", "diagnostic-run.ps1"):
        if (work / name).is_file():
            raw[name] = binding(work / name)
    return {"directory": str(work), "success": False, "firstFailure": result.get("firstFailure") if result else None,
            "launcher": launcher, "result": result, "rawEvidence": raw,
            "interpretation": "Original first-attempt failure retained separately; no passing coverage is inferred from it"}




def validate_setup_transcriptions(root):
    development_file, contrast_file = root / "development-setup-error.json", root / "contrast-setup-error.json"
    development, contrast = read(development_file), read(contrast_file)
    if (development["stage"] != "development-runner-mkdir-before-node-launch"
            or not same(development["cwd"], REPO) or not same(development["resolvedArtifactRoot"], root)
            or development["noNodeLaunched"] is not True or development["noTestCounts"] is not True
            or development["recordType"] != "operator transcription of the failed tool invocation; not a test runner result or raw process log"
            or not same(development["command"][0], PYTHON) or development["command"][1] != "-B"
            or not same(development["command"][2], root / "run-development.py")
            or development["command"][3:] != ["initial-current-selected", "--selected"]
            or "WinError 5" not in development["error"]):
        raise ValueError("Reported development setup failure must remain a pre-Node operator transcription without counts")
    if (contrast["kind"] != "operator transcription of pre-launch sandbox setup failure"
            or not same(contrast["cwd"], REPO) or not same(contrast["target"], root / "regression-contrast")
            or contrast["noNodeLaunched"] is not True or contrast["noTestCounts"] is not True
            or contrast["errorClass"] != "PermissionError" or contrast["winError"] != 5
            or not same(contrast["argv"][0], PYTHON) or contrast["argv"][1] != "-B"
            or not same(contrast["argv"][2], root / "run-contrast.py") or len(contrast["argv"]) != 3):
        raise ValueError("Reported contrast setup failure must remain a pre-Node operator transcription without counts")
    utc(contrast["recordedUtc"])
    return {"development": {"file": binding(development_file), "record": development},
            "contrast": {"file": binding(contrast_file), "record": contrast},
            "interpretation": "Operator transcriptions of setup/tool failures before Node launch; not raw process logs, executable test attempts or test-count records"}


def validate_development(directory):
    selected = ["--unhandled-rejections=strict", "--test", "--test-reporter=tap", "--test-name-pattern", PATTERN,
                "scripts/variant/file-based-apps/test-runtime.cjs"]
    focused = ["--unhandled-rejections=strict", "--test", "--test-reporter=tap", "scripts/variant/file-based-apps/test-runtime.cjs"]
    cases = {"initial-current-selected": (6, 0, 0, selected, "complete selected development run"),
             "initial-current-runtime": (75, 1, 1, focused, "interrupted incomplete focused attempt"),
             "corrected-current-runtime": (135, 0, 0, focused, "complete corrected focused development run")}
    expected_entries = {name + suffix for name in cases for suffix in (".json", ".log", "-source")}
    if {path.name for path in directory.iterdir()} != expected_entries:
        raise ValueError("Retain the exact three actual development result/log/source-copy groups")
    rows = {}
    for name, (total, failures, exit_code, arguments, kind) in cases.items():
        result_file, log_file = directory / (name + ".json"), directory / (name + ".log")
        record = read(result_file)
        archive = directory / (name + "-source")
        if (not same(record["argv"][0], NODE) or record["argv"][1:] != arguments or not same(record["cwd"], REPO)
                or record["exitCode"] != exit_code or digest(log_file.read_bytes()) != record["logSha256"]
                or not utc(record["started"]) <= utc(record["finished"])
                or record["currentSourceUnchanged"] is not True or set(record["source"]) != NAMES
                or not same(record["sourceArchive"], archive) or not same(record["node"]["path"], NODE)
                or {path.name for path in archive.iterdir()} != NAMES):
            raise ValueError("Development attempt argv/result/log/source identity differs: " + name)
        check_file(NODE, record["node"])
        copied = {module: check_file(archive / module, proof) for module, proof in record["source"].items()}
        for module in MODULE_NAMES:
            if (archive / module).read_bytes() != (MODULES / module).read_bytes():
                raise ValueError("Product runtime/modules must remain unchanged across these development attempts: " + name)
        totals = counts(log_file.read_text(encoding="utf-8"), total, failures)
        if re.findall(r"^# suites (\d+)\s*$", log_file.read_text(encoding="utf-8"), re.MULTILINE) != ["0"]:
            raise ValueError("Expected one complete reported TAP suites footer in development log")
        current_tests_equal = (archive / "test-runtime.cjs").read_bytes() == (MODULES / "test-runtime.cjs").read_bytes()
        if name == "corrected-current-runtime" and not current_tests_equal:
            raise ValueError("Corrected focused attempt must retain the actual final test source")
        rows[name] = {"kind": kind, "record": record, "resultFile": binding(result_file), "log": binding(log_file),
                      "reportedNodeFooter": totals, "sourceCopies": copied,
                      "currentTestBytesEqual": current_tests_equal,
                      "completeExpectedRuntimeCoverage": name == "corrected-current-runtime"}
    interrupted = rows["initial-current-runtime"]
    interruption_file = directory.parent / "development-interruption.json"
    interruption = read(interruption_file)
    if (interruption["attempt"] != "development/initial-current-runtime.json"
            or interruption["log"] != "development/initial-current-runtime.log"
            or interruption["logSha256"] != interrupted["record"]["logSha256"]
            or interruption["completedUtc"] != interrupted["record"]["finished"]
            or not same(interruption["terminatedExecutable"], NODE)
            or interruption["fullRuntimeSuiteCompleted"] is not False or interruption["naturalTestResult"] is not False
            or interruption["productFailureClaim"] is not False or interruption["lastCompletedCaseBeforeInterruption"] != 74
            or interruption["blockedCase"] != "concurrent dirty-file commands share a cancelled save and permit a corrected retry"
            or interruption["recordType"] != "operator transcription of process identification and termination tool results; supplements the original runner result and partial log"
            or any(not isinstance(interruption[key], int) or interruption[key] <= 0 for key in ("runnerPid", "nodeParentPid", "terminatedWorkerPid"))):
        raise ValueError("Interrupted attempt must retain its explicit operator intervention and incomplete-result scope")
    text = (directory / "initial-current-runtime.log").read_text(encoding="utf-8")
    if "exitCode: 4294967295" not in text or "code: 'ERR_TEST_FAILURE'" not in text or len(re.findall(r"^not ok ", text, re.MULTILINE)) != 1:
        raise ValueError("Interrupted raw log must retain its actual file-worker failure footer")
    return {"directory": str(directory), "attempts": rows,
            "expectedCompleteFocusedRuntimeCases": 135,
            "interruption": {"file": binding(interruption_file), "record": interruption},
            "setupFailureTranscriptions": validate_setup_transcriptions(directory.parent),
            "runnerHelpersAtSummary": {name: binding(directory.parent / name) for name in ("run-development.py", "run-contrast.py")},
            "interpretation": "Three retained executable attempts have exact six-module source copies, argv/log/result/runtime bindings. The interrupted 75/74/1 footer is incomplete expected-135 coverage after a reported owned-worker intervention, not a natural passing result or product-failure claim. The two setup failures and intervention are explicitly operator transcriptions, not raw process logs. No completeness of all development/tool history is inferred"}


def build_summary(tests, contrast, smoke, development, base_vsix, failed_smokes=()):
    if (not SOURCE_COMMIT or NODE_TESTS is None or CONTRAST_TESTS is None
            or CONTRAST_FAILURES is None or not PREPARATION_HELPER_SHA or not PATTERN
            or len(BASELINE_ERRORS) != CONTRAST_FAILURES
            or git("rev-parse", SOURCE_COMMIT + "^{commit}").decode().strip() != SOURCE_COMMIT):
        raise ValueError("Pin the implementation commit, final counts, exact selector/assertions, preparation helper and actual development format before generation")
    subprocess.run(["git", "merge-base", "--is-ancestor", SOURCE_COMMIT, "HEAD"], cwd=REPO, check=True)
    return {"schema": 1, "kind": "save inside one cancellable file-command progress operation",
            "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18", "baseCommit": BASE,
            "implementationCommit": SOURCE_COMMIT, "productChange": True, "qualification": False,
            "verification": validate_units(tests.resolve(), BASE),
            "regressionContrast": validate_contrast(contrast.resolve(), BASE),
            "installedCompilerSmoke": validate_smoke(smoke.resolve(), base_vsix.resolve()),
            "unexpectedSmokeFailures": [validate_failed_smoke(path.resolve()) for path in failed_smokes],
            "developmentObservations": validate_development(development.resolve()),
            "collectors": {str(path.relative_to(REPO)): binding(path) for path in (Path(__file__), BUILD_COLLECTOR, build.SHARED)},
            "limits": ["The command observes actual save settlement and preserves same-file coalescing/disposal ownership; cancellation during save suppresses downstream SDK work after settlement without preempting save itself.",
                       "The preparation timer begins after actual save settlement while the total operation clock includes save. No hard save or total-phase deadline is claimed.",
                       "Existing unresolved/captured editor session ownership and actual terminal cleanup drain remain conservative until their real evidence/settlement; this slice does not release those resources early.",
                       "The single installed ordinary compiler-failure/dirty-retry smoke exercises normal flow, not native save cancellation or a blocked/non-cooperative save provider.",
                       "Full issue18 AC6 and issue45's unexplained earlier B pause/failed compiler observation remain open; a new normal-flow pass does not supersede them.",
                       "No physical F5/menu, macOS, calibrated total-phase budget, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--contrast", type=Path, required=True)
    parser.add_argument("--smoke", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--base-vsix", type=Path, required=True)
    parser.add_argument("--failed-smokes", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, default=HERE / "evidence-summary.json")
    args = parser.parse_args()
    value = build_summary(args.tests, args.contrast, args.smoke, args.development, args.base_vsix, args.failed_smokes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": str(args.output), **binding(args.output)}))


if __name__ == "__main__":
    main()
