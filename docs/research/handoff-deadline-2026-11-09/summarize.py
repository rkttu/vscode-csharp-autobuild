"""Validate the owned file-app editor handoff API deadline evidence."""
import argparse
import copy
import difflib
import importlib.util
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import struct
import zipfile
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODULES = REPO / "scripts/variant/file-based-apps"
BASE = "e0c9a1058b62243e8e4e48bdf537205bb09df490"
SOURCE_COMMIT = "0e6f5394a7cfb7b4b599d47d2715bb56922da95c"
NODE_TESTS = 291
CONTRAST_TESTS = 12
CONTRAST_FAILURES = 11
PATTERN = "^handoff deadline"
BASELINE_FAILURES = [
    {
        "test": "handoff deadline releases a timed-out start for a distinct coalesced retry while retaining the original request",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Cancellation or timeout must release the foreground before the held provider settles"
    },
    {
        "test": "handoff deadline stops a captured session but keeps output until exact termination and the pending API until settlement",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Cancellation or timeout must release the foreground before the held provider settles"
    },
    {
        "test": "handoff deadline retains its first timeout through a late decline without a captured session",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Cancellation or timeout must release the foreground before the held provider settles"
    },
    {
        "test": "handoff deadline retains its first timeout through a late rejection without a captured session",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Cancellation or timeout must release the foreground before the held provider settles"
    },
    {
        "test": "handoff deadline checks a delayed true response even when its timer callback has not run",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Expected values to be strictly equal:\n\ntrue !== false"
    },
    {
        "test": "handoff deadline checks a delayed false response even when its timer callback has not run",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "The input did not match the regular expression /Debugger handoff timed out.*101 ms \\(limit 100 ms\\)/. Input:\n\n'C# file debugging failed: The editor did not start the netcoredbg debug session. Check C# and Debug Console output for details before retrying. See the C# File Debugging output.'"
    },
    {
        "test": "handoff deadline disarms at an accepted response and preserves original errors without inferring an undelivered timeout",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Expected values to be strictly equal:\n\n0 !== 1"
    },
    {
        "test": "handoff deadline preserves user cancellation or timeout ahead of stale expiry and later progress errors",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Expected values to be strictly equal:\n\n0 !== 1"
    },
    {
        "test": "handoff deadline checkpoints phase progress and the actual queued API dispatch before starting the editor",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Expected values to be strictly equal:\n\ntrue !== false"
    },
    {
        "test": "handoff deadline disposal disarms its timer while retaining late exact-session and API ownership",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "Expected values to be strictly equal:\n\n0 !== 1"
    },
    {
        "test": "handoff deadline prepares foreign launch arguments before ownership transfer and permits a corrected retry",
        "failureType": "testCodeFailure",
        "code": "ERR_ASSERTION",
        "error": "The terminal output and its completed receipt must be removed"
    }
]
SELECTED_TEST_NAMES = [
    "handoff deadline releases a timed-out start for a distinct coalesced retry while retaining the original request",
    "handoff deadline stops a captured session but keeps output until exact termination and the pending API until settlement",
    "handoff deadline retains its first timeout through a late decline without a captured session",
    "handoff deadline retains its first timeout through a late rejection without a captured session",
    "handoff deadline checks a delayed true response even when its timer callback has not run",
    "handoff deadline checks a delayed false response even when its timer callback has not run",
    "handoff deadline disarms at an accepted response and preserves original errors without inferring an undelivered timeout",
    "handoff deadline preserves user cancellation or timeout ahead of stale expiry and later progress errors",
    "handoff deadline checkpoints phase progress and the actual queued API dispatch before starting the editor",
    "handoff deadline disposal disarms its timer while retaining late exact-session and API ownership",
    "handoff deadline excludes save, Web interaction and already dispatched selected-project debugging",
    "handoff deadline prepares foreign launch arguments before ownership transfer and permits a corrected retry"
]
BASELINE_SAFE_CONTROL_NAMES = [
    "handoff deadline excludes save, Web interaction and already dispatched selected-project debugging"
]
INITIAL_DEVELOPMENT_FAILURES = [{'test': 'stream output diagnostics preserve success through a throwing native stream sink',
  'failureType': 'testCodeFailure',
  'code': 'ERR_ASSERTION',
  'renderedErrorPayloads': [{'sha256': 'c45676acc934497162ae900903bd13e7a5f14abf41b1c10fe7fbfc9f3dc00590',
                             'characters': 13629,
                             'firstLine': 'The strict activation probe must complete within its safety limit',
                             'text': None,
                             'retainedInOriginalRawLog': True},
                            {'sha256': '1355fc5769bd53259123e37d43160328236a910a602a9ab3e6bc4a6dc6a952f3',
                             'characters': 118,
                             'firstLine': 'spawnSync '
                                          'C:\\\\Users\\\\rkttu\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin\\\\node.exe '
                                          'ETIMEDOUT',
                             'text': 'spawnSync '
                                     'C:\\\\Users\\\\rkttu\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin\\\\node.exe '
                                     'ETIMEDOUT',
                             'retainedInOriginalRawLog': True}],
  'normalizedTapDiagnostic': {'sha256': '0c5492152c746433da7ab3471dd2053e9a0ac1873f799008d0480b8254550fb7',
                              'characters': 15763}},
 {'test': 'stream output diagnostics preserve failure through a throwing native stream sink',
  'failureType': 'testCodeFailure',
  'code': 'ERR_ASSERTION',
  'renderedErrorPayloads': [{'sha256': 'de0778851aff82167a544a399ef7f383cf8f14f2a0b6a2b061851dc30f051935',
                             'characters': 13772,
                             'firstLine': 'The strict activation probe must complete within its safety limit',
                             'text': None,
                             'retainedInOriginalRawLog': True},
                            {'sha256': '1355fc5769bd53259123e37d43160328236a910a602a9ab3e6bc4a6dc6a952f3',
                             'characters': 118,
                             'firstLine': 'spawnSync '
                                          'C:\\\\Users\\\\rkttu\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin\\\\node.exe '
                                          'ETIMEDOUT',
                             'text': 'spawnSync '
                                     'C:\\\\Users\\\\rkttu\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin\\\\node.exe '
                                     'ETIMEDOUT',
                             'retainedInOriginalRawLog': True}],
  'normalizedTapDiagnostic': {'sha256': '68b95087d07bee504836ed387fcbee2db7c26edb318c7ef058c27738cec85550',
                              'characters': 16180}},
 {'test': 'stream output diagnostics preserve cancel through a throwing native stream sink',
  'failureType': 'testCodeFailure',
  'code': 'ERR_ASSERTION',
  'renderedErrorPayloads': [{'sha256': '3c169c75c24bcfbba0346472ba4314201a5ee0ca4668d49e3bd1f94bf5e07750',
                             'characters': 13769,
                             'firstLine': 'The strict activation probe must complete within its safety limit',
                             'text': None,
                             'retainedInOriginalRawLog': True},
                            {'sha256': '1355fc5769bd53259123e37d43160328236a910a602a9ab3e6bc4a6dc6a952f3',
                             'characters': 118,
                             'firstLine': 'spawnSync '
                                          'C:\\\\Users\\\\rkttu\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin\\\\node.exe '
                                          'ETIMEDOUT',
                             'text': 'spawnSync '
                                     'C:\\\\Users\\\\rkttu\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin\\\\node.exe '
                                     'ETIMEDOUT',
                             'retainedInOriginalRawLog': True}],
  'normalizedTapDiagnostic': {'sha256': '798c10c67f83ed8db19e1a11bf6445459740bb508dff223e62a7bf28a99e8817',
                              'characters': 16173}},
 {'test': 'stream output diagnostics preserve dispose through a throwing native stream sink',
  'failureType': 'testCodeFailure',
  'code': 'ERR_ASSERTION',
  'renderedErrorPayloads': [{'sha256': '0f9754a2739bdfe921d1a147a145ae06d0c35a4f8558332878ecc476b2246014',
                             'characters': 13770,
                             'firstLine': 'The strict activation probe must complete within its safety limit',
                             'text': None,
                             'retainedInOriginalRawLog': True},
                            {'sha256': '1355fc5769bd53259123e37d43160328236a910a602a9ab3e6bc4a6dc6a952f3',
                             'characters': 118,
                             'firstLine': 'spawnSync '
                                          'C:\\\\Users\\\\rkttu\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin\\\\node.exe '
                                          'ETIMEDOUT',
                             'text': 'spawnSync '
                                     'C:\\\\Users\\\\rkttu\\\\.cache\\\\codex-runtimes\\\\codex-primary-runtime\\\\dependencies\\\\node\\\\bin\\\\node.exe '
                                     'ETIMEDOUT',
                             'retainedInOriginalRawLog': True}],
  'normalizedTapDiagnostic': {'sha256': 'ba87b8d43b579aec3f4172906c6805a5f2952b3ab4d7ae303dfe0272641e6baa',
                              'characters': 16174}},
 {'test': 'adapter configuration ignores unrelated, failed and uncorrelated responses',
  'failureType': 'testCodeFailure',
  'code': 'ERR_ASSERTION',
  'renderedErrorPayloads': [{'sha256': '6f5d317245bdb6f94c6691981e2d0d561a06a10c6426b3883cb2de159afc324a',
                             'characters': 55,
                             'firstLine': 'The owned session must release after actual termination',
                             'text': 'The owned session must release after actual termination',
                             'retainedInOriginalRawLog': True}],
  'normalizedTapDiagnostic': {'sha256': '914bedeaee14229fab607a5de25b518159d260a01be72fd1f9e2d1a7e534fb58',
                              'characters': 916}},
 {'test': 'disposed exact session drains from DAP debuggee exit then non-restarting termination (-2147483648)',
  'failureType': 'testCodeFailure',
  'code': 'ERR_ASSERTION',
  'renderedErrorPayloads': [{'sha256': '152e4e20529b9f607b2751f18b473375dacbf902db7ada9b830ea7fa3f81a487',
                             'characters': 69,
                             'firstLine': 'The trusted DAP pair must complete owned cleanup without an API event',
                             'text': 'The trusted DAP pair must complete owned cleanup without an API event',
                             'retainedInOriginalRawLog': True}],
  'normalizedTapDiagnostic': {'sha256': 'b111f34f5c7a86377e6aace62f761c4e7b0452f9e1018c10cbf02372e4f57687',
                              'characters': 931}},
 {'test': 'disposed exact session drains from DAP debuggee exit then non-restarting termination (2147483647)',
  'failureType': 'testCodeFailure',
  'code': 'ERR_ASSERTION',
  'renderedErrorPayloads': [{'sha256': '152e4e20529b9f607b2751f18b473375dacbf902db7ada9b830ea7fa3f81a487',
                             'characters': 69,
                             'firstLine': 'The trusted DAP pair must complete owned cleanup without an API event',
                             'text': 'The trusted DAP pair must complete owned cleanup without an API event',
                             'retainedInOriginalRawLog': True}],
  'normalizedTapDiagnostic': {'sha256': 'ba1eb1b96988ef516e021ff02ddbf458cb8ce3a84fa4500c4854a930f86d0bae',
                              'characters': 931}}]
RESPONSIVENESS_HELPER_SHA = "e97db370ab4272abb408847b94d517962e3005a3997c27c0469d08caf2e3296d"
CONTRAST_SUITES = ["test-runtime.cjs"]
CHANGED = {"scripts/variant/file-based-apps/" + name for name in ("runtime.cjs", "test-runtime.cjs")}
PRODUCT_CHANGES = {"runtime.cjs"}
MODULE_NAMES = {"entry.cjs", "runtime.cjs", "classify.cjs", "web.cjs", "recovery.cjs"}
NAMES = MODULE_NAMES | {"test-runtime.cjs", "test-web.cjs"}
NODE = Path("C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
PYTHON = Path("C:/Users/rkttu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")
BASE_VSIX_SHA = "0d239dff83d3120786ff3596a046fd0866b045f1d883c86fb83c64a7d808d0c5"
DEPENDENCY_SHA = "a4cff5409f66e3827ee2c6a727ae59382290a182a653ca0f9ac97c63536ee541"
PREPARATION_HELPER_SHA = "1cd9668700e2965cbb7629eb11c8c6899a7febc64856fb52917c79cec650a28d"
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


build = load_module("handoff_deadline_build_summary", BUILD_COLLECTOR)
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



def generic_run_process_bytes(data):
    data = normalized(data)
    start = data.index(b"function runProcess(")
    end = data.index(b"\nfunction stdout(", start)
    return data[start:end]


def validate_units(directory, base):
    if base != BASE or not re.fullmatch(r"[0-9a-f]{40}", base) or git("rev-parse", base + "^{commit}").decode().strip() != base:
        raise ValueError("Pass the complete specified merged base base commit")
    subprocess.run(["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=REPO, check=True)
    manifest = read(directory / "source-manifest.json")
    user_documentation = REPO / "docs/file-based-apps.md"
    if normalized(user_documentation.read_bytes()) != normalized(git("show", SOURCE_COMMIT + ":docs/file-based-apps.md")):
        raise ValueError("Current user documentation differs from the implementation commit")
    current_runtime = (MODULES / "runtime.cjs").read_bytes()
    baseline_runtime = git("show", BASE + ":scripts/variant/file-based-apps/runtime.cjs")
    if generic_run_process_bytes(current_runtime) != generic_run_process_bytes(baseline_runtime):
        raise ValueError("The generic exported runProcess callback/close contract must remain byte-equal modulo line endings")
    if manifest["commit"] != base or not same(manifest["worktree"], REPO):
        raise ValueError("Frozen tests must use this worktree over specified merged base")
    files = sorted(name for name in git("ls-files", "--cached", "--others", "--exclude-standard", "scripts/variant").decode().splitlines()
                   if (REPO / name).is_file())
    records = manifest["source"]
    names = [record["path"] for record in records]
    if len(files) != 53 or len(set(names)) != 53 or sorted(names) != files:
        raise ValueError("Expected all 53 current archived variant source files")
    changes = set(git("diff", "--name-only", base, "--", "scripts/variant").decode().splitlines())
    if changes != CHANGED:
        raise ValueError("Only runtime and its test may change under scripts/variant; Web and shared lifecycle harness must match specified merged base")
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
            "archivedSource": archive, "allOtherSourcesUnchanged": True, "genericRunProcessSourceUnchanged": True,
            "implementationUserDocumentation": {"path": "docs/file-based-apps.md", **binding(user_documentation),
                "sourceCommit": SOURCE_COMMIT, "includedInArchived53VariantSources": False,
                "scope": "Current bytes at collection match implementation Git content modulo checkout line endings; no pre-run/post-run documentation archive is claimed"},
            "runs": rows}





def tap_failures(text):
    rows = []
    for match in re.finditer(r"^not ok \d+ - (.*)\n((?:[ \t].*\n)+)", text, re.MULTILINE):
        lines = match[2].splitlines()
        def scalar(key):
            matches = [line[len(key) + 4:] for line in lines if line.startswith("  " + key + ": ")]
            if len(matches) != 1:
                raise ValueError("Expected one failure field: " + key)
            value = matches[0]
            return value[1:-1].replace("''", "'") if value.startswith("'") and value.endswith("'") else value
        error_lines = [index for index, line in enumerate(lines) if line.startswith("  error: ")]
        if len(error_lines) != 1:
            raise ValueError("Expected one error payload in a failed TAP case")
        error_index = error_lines[0]
        if lines[error_index] == "  error: |-":
            parts = []
            for line in lines[error_index + 1:]:
                if not line.startswith("    "):
                    break
                parts.append(line[4:])
            error = "\n".join(parts).rstrip()
        else:
            error = scalar("error")
        row = {"test": match[1], "failureType": scalar("failureType"), "code": scalar("code"), "error": error}
        if error == "":
            stack_indices = [index for index, line in enumerate(lines) if line == "  stack: |-"]
            if len(stack_indices) != 1:
                raise ValueError("An empty TAP error requires its exact retained stack")
            parts = []
            for line in lines[stack_indices[0] + 1:]:
                if not line.startswith("    "): break
                parts.append(line[4:])
            row["stack"] = "\n".join(parts).rstrip()
        rows.append(row)
    return rows




def validate_contrast(directory, base):
    if (SELECTED_TEST_NAMES is None or len(SELECTED_TEST_NAMES) != CONTRAST_TESTS
            or any(not name.startswith("handoff deadline ") for name in SELECTED_TEST_NAMES)):
        raise ValueError("Count only actual handoff deadline selected cases, never a no-match whole-file PASS")
    manifest = read(directory / "manifest.json")
    if (manifest["schema"] != 1 or manifest["baseCommit"] != BASE or base != BASE
            or manifest["pattern"] != PATTERN or manifest["currentSourceUnchanged"] is not True
            or not same(manifest["node"]["path"], NODE) or set(manifest["currentSource"]) != NAMES or len(manifest["runs"]) != 2):
        raise ValueError("Expected the exact seven-source/single-suite handoff deadline contrast")
    verify(NODE, manifest["node"])
    rows = {}
    for run in manifest["runs"]:
        variant = run["variant"]
        if variant not in ("baseline", "changed") or variant in rows or set(run["copiedSource"]) != NAMES:
            raise ValueError("Contrast variant/source set differs")
        argv = run["argv"]
        expected_tail = [directory / variant / name for name in CONTRAST_SUITES]
        if (not same(argv[0], NODE) or argv[1:-len(CONTRAST_SUITES)] != ["--unhandled-rejections=strict", "--test", "--test-reporter=tap", "--test-name-pattern", PATTERN]
                or any(not same(value, expected) for value, expected in zip(argv[-len(CONTRAST_SUITES):], expected_tail))):
            raise ValueError("Exact strict runtime-only contrast argv differs")
        copies = {name: verify(directory / variant / name, proof) for name, proof in run["copiedSource"].items()}
        log = directory / (variant + ".log")
        if not same(run["log"]["path"], log):
            raise ValueError("Contrast raw log path differs")
        verify(log, run["log"])
        text = log.read_text(encoding="utf-8")
        totals = counts(text, CONTRAST_TESTS, CONTRAST_FAILURES if variant == "baseline" else 0)
        expected_exit = 1 if variant == "baseline" else 0
        if (run["counts"] != {**totals, "suites": 0} or re.findall(r"^# suites (\d+)\s*$", text, re.MULTILINE) != ["0"]
                or run["exitCode"] != expected_exit or run["expectedExitCode"] != expected_exit
                or not utc(run["startedUtc"]) <= utc(run["completedUtc"]) <= utc(manifest["completedUtc"])
                or re.findall(r"^(?:not )?ok \d+ - (.*)$", text, re.MULTILINE) != SELECTED_TEST_NAMES):
            raise ValueError("Exact contrast result/counts/test selection/timestamps differ")
        failures = tap_failures(text)
        if variant == "baseline":
            if failures != BASELINE_FAILURES or re.findall(r"^ok \d+ - (.*)$", text, re.MULTILINE) != BASELINE_SAFE_CONTROL_NAMES:
                raise ValueError("Baseline must retain the exact intended handoff deadline failure payloads and safe controls")
        elif failures:
            raise ValueError("Current implementation must pass all selected handoff deadline cases")
        rows[variant] = {"argv": argv, "exitCode": expected_exit, "startedUtc": run["startedUtc"], "completedUtc": run["completedUtc"],
                         "counts": totals, "failureRecords": failures, "log": binding(log), "copiedSource": copies}
    for name in NAMES:
        before, after, current = (directory / "baseline" / name).read_bytes(), (directory / "changed" / name).read_bytes(), (MODULES / name).read_bytes()
        if normalized(after) != normalized(current):
            raise ValueError("Contrast changed/current source differs beyond checkout line endings: " + name)
        verify(directory / "changed" / name, manifest["currentSource"][name])
        if name in PRODUCT_CHANGES:
            if before != git("show", BASE + ":scripts/variant/file-based-apps/" + name):
                raise ValueError("Baseline runtime must equal the exact specified merged base Git blob: " + name)
        elif before != after:
            raise ValueError("Only runtime product bytes may differ between the contrast copies: " + name)
        if name in MODULE_NAMES and name not in PRODUCT_CHANGES and normalized(current) != normalized(git("show", BASE + ":scripts/variant/file-based-apps/" + name)):
            raise ValueError("Unrelated product modules must remain unchanged")
    return {"directory": str(directory), "manifestFile": binding(directory / "manifest.json"), "baseCommit": BASE,
            "baselineRuntimeExactGitBlob": True, "sameChangedTestsForBothImplementations": True,
            "currentNormalizedSourceMatches": True, "runs": rows, "passingBaselineSafeControls": BASELINE_SAFE_CONTROL_NAMES,
            "interpretation": "Eleven intended ERR_ASSERTION baseline failures and one preserved exclusion safe control become twelve current passes. Four baseline cases fail at the bounded foreground-outcome assertion rather than a missing-timer guard; other failures retain normal-response, timer-bookkeeping, queued-dispatch and terminal-output witness payloads. Exact names and complete scalar/multiline error payloads are pinned. Current controlled API-deadline fixtures preserve late exact-session Stop, pending starts, output ownership and actual drain; they do not measure native cancellation latency or establish an OS/session-event deadline."}



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
            "preparationInterpretation": "SourceBindingsBefore/After and productSourceUnchanged mean unchanged during preparation of this implementation commit; merged-base comparisons are verified separately. The raw editorNotRun control records preparation time before the later single installed smoke."}



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
            if name not in PRODUCT_CHANGES and normalized(current) != normalized(git("show", BASE + ":scripts/variant/file-based-apps/" + name)):
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
    return {"sourceCommit": SOURCE_COMMIT, "baseCommit": BASE, "changedProductModules": sorted(PRODUCT_CHANGES),
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
    if (not corrected["origin"].startswith("http://127.0.0.1:")
            or corrected["response"]["pid"] != corrected["pid"] or corrected["response"]["nonce"] != corrected["nonce"]):
        raise ValueError("Ordinary installed regression must retain the exact corrected HTTP launch/response")
    ordinary_http = {"origin": corrected["origin"], "response": corrected["response"],
                     "scope": "Ordinary installed compiler-failure/dirty-retry HTTP regression; no native delayed editor acceptance or handoff-timeout injection"}

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
            "compilerFailure": attempt, "coalescedRetry": coalesced, "ordinaryHttpRegression": ordinary_http,
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






def development_failure_records(text):
    # Node renders an asserted spawnSync Error with duplicate diagnostic error/stack
    # keys. Preserve every rendered error occurrence, without treating it as YAML.
    rows = []
    for match in re.finditer(r"^not ok \d+ - (.*)\n((?:[ \t].*\n)+)", text, re.MULTILINE):
        lines = match[2].splitlines()
        def scalar(key):
            values = [line[len(key) + 4:] for line in lines if line.startswith("  " + key + ": ")]
            if len(values) != 1: raise ValueError("Expected one development failure field: " + key)
            value = values[0]
            return value[1:-1].replace("''", "'") if value.startswith("'") and value.endswith("'") else value
        errors = []
        for index, line in enumerate(lines):
            if not line.startswith("  error: "): continue
            if line == "  error: |-":
                parts = []
                for following in lines[index + 1:]:
                    if not following.startswith("    "): break
                    parts.append(following[4:])
                value = "\n".join(parts).rstrip()
            else:
                value = line[len("  error: "):]
                if value.startswith("'") and value.endswith("'"): value = value[1:-1].replace("''", "'")
            errors.append({"sha256": digest(value.encode("utf-8")), "characters": len(value),
                           "firstLine": value.splitlines()[0] if value else "",
                           "text": value if len(value) <= 2048 else None,
                           "retainedInOriginalRawLog": True})
        if not errors: raise ValueError("Retain every development failure's rendered error payload")
        rows.append({"test": match[1], "failureType": scalar("failureType"), "code": scalar("code"),
                     "renderedErrorPayloads": errors,
                     "normalizedTapDiagnostic": {"sha256": digest(match[2].encode("utf-8")), "characters": len(match[2])}})
    return rows


def validate_development(directory):
    if INITIAL_DEVELOPMENT_FAILURES is None: raise ValueError("Pin the seven actual retained development failures")
    suite = "scripts/variant/file-based-apps/test-runtime.cjs"
    selected = ["--unhandled-rejections=strict", "--test", "--test-reporter=tap", "--test-name-pattern", PATTERN, suite]
    focused = ["--unhandled-rejections=strict", "--test", "--test-reporter=tap", suite]
    cases = {"initial-current-selected": (12, 0, selected, False),
             "initial-current-runtime": (171, 7, focused, True),
             "second-current-runtime": (171, 0, focused, True)}
    if {path.name for path in directory.iterdir()} != {name + suffix for name in cases for suffix in (".json", ".log", "-source")}:
        raise ValueError("Retain the exact three actual development result/log/seven-source snapshots")
    rows = {}
    previous_finished = None
    full_source_bindings = None
    for name, (total, failures, arguments, current_tests) in cases.items():
        result_file, log_file, archive = directory / (name + ".json"), directory / (name + ".log"), directory / (name + "-source")
        record = read(result_file)
        if (not same(record["argv"][0], NODE) or record["argv"][1:] != arguments or not same(record["cwd"], REPO)
                or record["exitCode"] != (1 if failures else 0) or digest(log_file.read_bytes()) != record["logSha256"]
                or not utc(record["started"]) <= utc(record["finished"])
                or previous_finished is not None and utc(record["started"]) < previous_finished
                or record["currentSourceUnchanged"] is not True or set(record["source"]) != NAMES
                or not same(record["sourceArchive"], archive) or not same(record["node"]["path"], NODE)
                or {path.name for path in archive.iterdir()} != NAMES):
            raise ValueError("Actual development argv/result/log/source/runtime/time identity differs: " + name)
        previous_finished = utc(record["finished"])
        check_file(NODE, record["node"])
        copies = {module: check_file(archive / module, proof) for module, proof in record["source"].items()}
        matches = {module: (archive / module).read_bytes() == (MODULES / module).read_bytes() for module in sorted(NAMES)}
        if (any(not matches[module] for module in NAMES - {"test-runtime.cjs"})
                or matches["test-runtime.cjs"] is not current_tests):
            raise ValueError("Initial historical test helper and both current full-source scopes differ")
        if current_tests:
            if full_source_bindings is None: full_source_bindings = copies
            if copies != full_source_bindings: raise ValueError("Both full development attempts must have identical exact final source bytes")
        text = log_file.read_text(encoding="utf-8")
        totals = counts(text, total, failures)
        errors = development_failure_records(text)
        names = re.findall(r"^(?:not )?ok \d+ - (.*)$", text, re.MULTILINE)
        if (re.findall(r"^# suites (\d+)\s*$", text, re.MULTILINE) != ["0"]
                or errors != (INITIAL_DEVELOPMENT_FAILURES if failures else [])
                or [value for value in names if value.startswith("handoff deadline ")] != SELECTED_TEST_NAMES):
            raise ValueError("Actual development counts/selected cases/failure payloads differ: " + name)
        rows[name] = {"record": record, "resultFile": binding(result_file), "log": binding(log_file),
                      "counts": totals, "failureRecords": errors, "sourceCopies": copies,
                      "matchesCurrentSourceBytes": matches, "currentSourceCoverage": current_tests,
                      "passingCurrentSourceValidation": current_tests and failures == 0}
    return {"directory": str(directory), "attempts": rows,
            "interpretation": "Three retained formal attempts preserve exact argv/Node/log/result/seven-source/time bindings. Initial selected twelve cases pass with a historical fake-clock helper. Both full runtime attempts use identical final source: the first has four spawnSync ETIMEDOUT probe guard failures and three cleanup-readiness assertion failures (164 pass/7 fail); the second passes all 171. Every rendered error occurrence and its complete normalized diagnostic are hash-bound to the original retained raw log, including Node's duplicate error/stack rendering. No cause for the first failure set is established, and the later pass does not erase it. currentSourceCoverage does not imply passing validation. The development orchestration was inline without a retained runner program; completeness of all discovery/development/tool history is not claimed"}


def validate_responsiveness(directory, development):
    helper, file = directory / "responsiveness.py", directory / "responsiveness-01.json"
    if {path.name for path in directory.iterdir()} != {helper.name, file.name}:
        raise ValueError("Retain exactly the one post-development observation and its original helper")
    record = read(file)
    if (set(record) != {"schema", "kind", "startedUtc", "completedUtc", "node", "helper", "limits", "process", "sourceRead"}
            or record["schema"] != 1 or record["kind"] != "independent post-development responsiveness observation"
            or not same(record["node"]["path"], NODE) or not same(record["helper"]["path"], helper)
            or record["helper"]["sha256"] != RESPONSIVENESS_HELPER_SHA):
        raise ValueError("Post-development observation identity differs")
    check_file(NODE, record["node"]); check_file(helper, record["helper"])
    process = record["process"]
    if (set(process) != {"argv", "exitCode", "stdout", "stderr", "elapsedMilliseconds"}
            or not same(process["argv"][0], NODE) or process["argv"][1:] != ["-e", 'process.stdout.write("ready")']
            or process["exitCode"] != 0 or process["stdout"] != "ready" or process["stderr"] != ""
            or not math.isfinite(process["elapsedMilliseconds"]) or process["elapsedMilliseconds"] < 0):
        raise ValueError("Exact retained one-off Node observation differs")
    source = record["sourceRead"]
    if (set(source) != {"path", "bytes", "sha256", "elapsedMilliseconds"}
            or not same(source["path"], MODULES / "test-runtime.cjs")
            or not math.isfinite(source["elapsedMilliseconds"]) or source["elapsedMilliseconds"] < 0):
        raise ValueError("Exact retained source-read observation differs")
    check_file(MODULES / "test-runtime.cjs", source)
    latest = max(utc(attempt["record"]["finished"]) for attempt in development["attempts"].values())
    if (not latest <= utc(record["startedUtc"]) <= utc(record["completedUtc"])
            or record["limits"] != ["This is not a product test, benchmark or a causal diagnosis of the earlier seven guard failures.",
                                    "This observation occurs after both development runtime attempts; it cannot establish their earlier conditions."]):
        raise ValueError("Post-development observation ordering or scope differs")
    return {"record": record, "recordFile": binding(file), "helperFile": binding(helper),
            "afterAllRetainedDevelopmentAttempts": True,
            "interpretation": "One later pinned-Node ready/read observation only. It occurred after both full development attempts and neither reconstructs their earlier conditions nor diagnoses the seven failures; it is not a product test, benchmark or native handoff-latency qualification. The original helper is read and hashed, never executed during collection"}


def build_summary(tests, contrast, smoke, development, base_vsix, failed_smokes=()):
    if (not SOURCE_COMMIT or NODE_TESTS is None or CONTRAST_TESTS is None or CONTRAST_FAILURES is None
            or not PREPARATION_HELPER_SHA or BASELINE_FAILURES is None or CONTRAST_SUITES is None or CHANGED is None
            or git("rev-parse", SOURCE_COMMIT + "^{commit}").decode().strip() != SOURCE_COMMIT):
        raise ValueError("Pin the implementation commit, final source scope/counts, exact contrast and actual development records before generation")
    subprocess.run(["git", "merge-base", "--is-ancestor", SOURCE_COMMIT, "HEAD"], cwd=REPO, check=True)
    development_records = validate_development(development.resolve())
    return {"schema": 1, "kind": "owned file-app editor handoff API deadline",
            "issue": "https://github.com/rkttu/vscode-csharp-autobuild/issues/18", "baseCommit": BASE,
            "implementationCommit": SOURCE_COMMIT, "productChange": True, "qualification": False,
            "verification": validate_units(tests.resolve(), BASE),
            "regressionContrast": validate_contrast(contrast.resolve(), BASE),
            "installedCompilerSmoke": validate_smoke(smoke.resolve(), base_vsix.resolve()),
            "unexpectedSmokeFailures": [validate_failed_smoke(path.resolve()) for path in failed_smokes],
            "developmentObservations": development_records,
            "postDevelopmentResponsiveness": validate_responsiveness(development.resolve().parent / "diagnostics", development_records),
            "collectors": {str(path.relative_to(REPO)): binding(path) for path in (Path(__file__), BUILD_COLLECTOR, build.SHARED)},
            "limits": ["The owned file-app Starting netcoredbg API wait has a separate default five-minute automatic deadline using existing monotonic time/scheduler and an injected handoffTimeoutMs option; the pre-dispatch check and post-await checks on normal true/false responses preserve elapsed-time selection. An API rejection retains its original error unless the actual timer or another abort already selected a reason.",
                       "Timeout notification is emitted once. The original pending editor API stays tracked until its promise settles, and a late exact owned session is stopped. Output cleanup requires terminal proof; exact owned-session termination can precede API settlement while disposal still retains the pending API. A distinct same-file retry may proceed while the previous editor API remains pending; this differs from the general held-save source gate.",
                       "Save, Web/certificate interaction and selected-project delegation do not receive this deadline. True editor acceptance followed by a missing session-start event remains outside this API-wait bound.",
                       "Deadline callbacks require a responsive event loop and do not establish OS-request preemption, actual drain/disposal bounds or eventual provider settlement.",
                       "The single installed ordinary HTTP control is normal-flow regression only, without delayed editor acceptance or handoff-timeout injection.",
                       "Full issue18 AC6 and issue45's earlier unexplained B pause/failed compiler observation remain open. No physical F5/menu, macOS, calibrated total-phase budget, descendant cleanup, language-service readiness, CI, release or publication qualification is claimed."]}


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
