"""Frozen two-profile native-F5 controls; never sends input or grants qualification."""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

REPO = Path(__file__).resolve().parents[3]
LIFECYCLE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "scripts/variant"))
sys.path.insert(0, str(LIFECYCLE))
import candidate
KIND = "native-f5-series-v1"
PROFILES = ("r01", "r02")
PREPARATION = ("baseVsix", "baseSha256", "runtimeVsix", "runtimeSha256", "editor", "editorCli", "dotnet", "sdkVersion")
CONDITIONS = ("editorProfile", "sdkCache", "nugetCache", "restore", "osCache", "network", "operator")
METADATA = ("osBuild", "nativeArchitecture", "editorChannel", "applicationRuntime", "languageServerRuntime", "upstreamCsharp", "upstreamRoslyn")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(file):
    return json.loads(Path(file).read_text(encoding="utf-8-sig"))


def proof(file):
    file = Path(file)
    require(file.is_file() and not file.is_symlink(), "Expected a regular retained file: " + str(file))
    data = file.read_bytes()
    return {"path": str(file.resolve()), "bytes": len(data), "sha256": digest(data)}


def publish(file, value):
    """Keep the staging original and atomically publish without replacement."""
    file = Path(file)
    staged = file.with_name(file.name + ".tmp")
    with staged.open("xb") as stream:
        stream.write((json.dumps(value, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    os.link(staged, file)


def contained(root, file):
    root, file = Path(root).resolve(), Path(file).resolve()
    require(file != root and file.is_relative_to(root), "Evidence escapes its owned directory")
    return file


def canonical_root(value):
    root = Path(value)
    require(root.is_absolute() and not root.is_symlink(), "Use an absolute, regular series directory")
    return root.resolve()


def owned_root(value):
    root = canonical_root(value)
    owner = read_json(root / "series-owner.json")
    require(owner == {"schema": 1, "kind": KIND, "root": str(root)}, "Not an owned native-F5 series directory")
    return root


def load_plan(root):
    value = read_json(root / "series-plan.json")
    require(value.get("schema") == 1 and value.get("kind") == KIND and value.get("root") == str(root), "Invalid series plan")
    require(value.get("profiles") == list(PROFILES) and value.get("cycles") == 10 and value.get("scenario") == "native-f5", "Plan must retain two profiles and ten cycles")
    require(value.get("nativeF5Input") in ("native-injected", "manual-native"), "Unknown frozen input mode")
    require(value.get("scope", {}).get("qualification") is False, "This control cannot grant qualification")
    return value


def source_snapshot():
    commit = subprocess.check_output(["git", "--no-optional-locks", "rev-parse", "HEAD"], cwd=REPO, text=True, timeout=30).strip()
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "Expected an exact source commit")
    status = subprocess.check_output(["git", "--no-optional-locks", "status", "--porcelain", "--untracked-files=all", "--", "scripts/variant"], cwd=REPO, text=True, timeout=30)
    require(not status.strip(), "Relevant source must be committed and clean")
    names = subprocess.check_output(["git", "--no-optional-locks", "ls-files", "scripts/variant"], cwd=REPO, text=True, timeout=30).splitlines()
    require("scripts/variant/lifecycle/series.py" in names, "Series controller must be committed")
    return {"commit": commit, "files": {name: proof(REPO / name) for name in names}}


def executable_version(name, path):
    arguments = [str(path), "--version"]
    if name == "powershell":
        arguments = [str(path), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"]
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=30, check=True)
    return result.stdout.strip()


def capture_inputs(config, observe_versions=True):
    values = {}
    for name in ("python", "node", "powershell"):
        pin = config["executables"][name]
        file = Path(pin["path"])
        require(file.is_absolute(), "Executable paths must be absolute")
        file = file.resolve(strict=True)
        version = executable_version(name, file) if observe_versions else pin["version"]
        require(version == pin["version"], "Executable version differs: " + name)
        values[name] = {**proof(file), "version": version}
    require(Path(sys.executable).resolve() == Path(values["python"]["path"]), "Invoke the controller with its pinned Python")
    for name in ("baseVsix", "runtimeVsix", "editor", "editorCli", "dotnet"):
        values[name] = proof(Path(config["preparation"][name]))
    require(values["baseVsix"]["sha256"] == config["preparation"]["baseSha256"], "Base VSIX hash differs")
    require(values["runtimeVsix"]["sha256"] == config["preparation"]["runtimeSha256"], "Runtime VSIX hash differs")
    editor_app = Path(config["preparation"]["editor"]).parent / "resources/app"
    for name in ("product.json", "package.json"):
        values["editor/" + name] = proof(editor_app / name)
    values["editorMetadata"] = {"product": read_json(editor_app / "product.json"), "package": read_json(editor_app / "package.json")}
    return values


def validate_config(config):
    require(config.get("schema") == 1, "Expected input config schema 1")
    require(config.get("nativeF5Input") in ("native-injected", "manual-native"), "Select a prospective native-F5 input mode")
    preparation = config.get("preparation", {})
    require(set(preparation) == set(PREPARATION), "Preparation requires the documented exact input keys")
    for name in ("baseSha256", "runtimeSha256"):
        require(isinstance(preparation[name], str) and SHA.fullmatch(preparation[name]), "Use lowercase SHA-256 pins")
    require(re.fullmatch(r"10\.0\.\d{3}", preparation["sdkVersion"]), "Pin an exact stable .NET 10 SDK")
    for name in ("baseVsix", "runtimeVsix", "editor", "editorCli", "dotnet"):
        require(Path(preparation[name]).is_absolute(), "Preparation paths must be absolute")
        preparation[name] = str(Path(preparation[name]).resolve(strict=True))
    require(set(config.get("executables", {})) == {"python", "node", "powershell"}, "Pin Python, Node and PowerShell")
    for value in config["executables"].values():
        require(set(value) == {"path", "version"} and isinstance(value["version"], str) and value["version"].strip(), "Pin executable path and exact version output")
    for section, names in (("conditions", CONDITIONS), ("declaredMetadata", METADATA)):
        require(set(config.get(section, {})) == set(names), "Record all " + section + " labels")
        require(all(isinstance(value, str) and value.strip() for value in config[section].values()), "Conditions and declared metadata must be nonblank")
    deadline = config.get("launcherDeadlineSeconds", 2400)
    require(type(deadline) is int and 60 <= deadline <= 3600, "Launcher safety cap must be 60..3600 seconds")
    config["launcherDeadlineSeconds"] = deadline
    return config


def freeze_snapshot(root, plan):
    require(not any((root / name).exists() for name in ("first-failure.json", "first-failure.json.tmp")), "Series stopped at its first failure")
    current = {"source": source_snapshot(), "inputs": capture_inputs(plan["config"], observe_versions=False),
               "plan": proof(root / "series-plan.json"), "candidate": proof(root / "candidate.vsix"),
               "candidateManifest": proof(root / "candidate-manifest.json")}
    require(current["source"] == plan["source"] and current["inputs"] == plan["inputs"], "Frozen source or execution input changed")
    require(current["candidate"] == plan["candidateFile"] and current["candidateManifest"] == plan["candidateManifest"], "Frozen candidate or manifest changed")
    return current


@contextmanager
def decision_lock(root):
    """Serialize first-failure selection with publication of a successful stage."""
    lock = root / "decision.lock"
    limit = time.monotonic() + 5
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            require(time.monotonic() < limit, "Another result publication is incomplete")
            time.sleep(0.01)
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def close_active_input(root, reason):
    """Only canonical profile paths are eligible for an external closure."""
    active = root / "operation.lock"
    if not active.exists():
        return
    operation = read_json(active)
    if operation.get("action") != "run" or operation.get("profile") not in PROFILES:
        return
    work = root / operation["profile"]
    require(not work.is_symlink() and work.resolve() == work, "Active profile is not its canonical owned directory")
    expected = read_json(work / "expected.json")
    nonce = expected.get("nativeF5", {}).get("nonce")
    require(isinstance(nonce, str) and nonce, "Active profile has no native-F5 nonce")
    closed = work / "f5-input-closed.json"
    if not closed.exists():
        try:
            publish(closed, {"schema": 1, "nonce": nonce, "reason": reason, "closedAtUtc": utc(), "closedBySeries": True})
        except FileExistsError:
            pass


def fail(root, action, profile, error):
    failure = root / "first-failure.json"
    def retain_failure():
        if not failure.exists() and not (root / "first-failure.json.tmp").exists():
            publish(failure, {"schema": 1, "action": action, "profile": profile, "failedAtUtc": utc(), "error": str(error)})
    try:
        try:
            with decision_lock(root):
                retain_failure()
        except Exception:
            # An abandoned decision lock must not prevent a conservative stop.
            # Exclusive publication still prevents replacing an earlier failure.
            try:
                retain_failure()
            except FileExistsError:
                pass
    finally:
        # Closing the input gate is cooperative, never an OS kill guarantee.
        try:
            close_active_input(root, str(error))
        except Exception:
            pass  # The original failure remains authoritative if closure fails.


def stage(root_value, action, profile, operation, exclusive=True, suffix=None):
    root = owned_root(root_value)  # Unknown directories are never poisoned.
    token = action + ("-" + profile if profile else "") + ("-" + suffix if suffix else "")
    attempt = root / (token + "-attempt.json")
    outcome = root / (token + "-result.json")
    lock = root / "operation.lock"
    acquired = False
    started = utc()
    try:
        if exclusive:
            with lock.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps({"action": action, "profile": profile, "startedAtUtc": started}))
            acquired = True
        publish(attempt, {"schema": 1, "action": action, "profile": profile, "startedAtUtc": started})
        plan = load_plan(root)
        with decision_lock(root):
            require(not (root / "first-failure.json.tmp").exists(), "Series stopped at its first failure")
        before = freeze_snapshot(root, plan)
        value = operation(root, plan)
        after = freeze_snapshot(root, plan)
        require(before == after, "Frozen inputs changed during the stage")
        result = {"schema": 1, "action": action, "profile": profile, "success": True, "startedAtUtc": started,
                  "completedAtUtc": utc(), "before": before, "after": after, **value}
        with decision_lock(root):
            require(not any((root / name).exists() for name in ("first-failure.json", "first-failure.json.tmp")), "First failure precedes result publication")
            publish(outcome, result)
        if action == "run" and profile == "r02":
            summary = verify_series(root, active_profile="r02")
            with decision_lock(root):
                require(not (root / "first-failure.json.tmp").exists(), "First failure precedes aggregate publication")
                publish(root / "series-result.json", summary)
        return result
    except Exception as error:
        fail(root, action, profile, error)
        if not outcome.exists() and not outcome.with_name(outcome.name + ".tmp").exists():
            observations = {}
            if "plan" in locals():
                for name, observe in (("source", source_snapshot), ("inputs", lambda: capture_inputs(plan["config"], observe_versions=False))):
                    try:
                        observations[name] = observe()
                    except Exception as observation_error:
                        observations[name] = {"captureError": str(observation_error)}
            publish(outcome, {"schema": 1, "action": action, "profile": profile, "success": False,
                              "startedAtUtc": started, "completedAtUtc": utc(), "error": traceback.format_exc(),
                              "before": locals().get("before"), "afterFailure": observations})
        raise
    finally:
        if acquired:
            try:
                require(read_json(lock) == {"action": action, "profile": profile, "startedAtUtc": started}, "Active operation lock changed")
                lock.unlink()
            except Exception as error:
                fail(root, action, profile, error)
                raise


def plan_series(root_value, config_file):
    root = canonical_root(root_value)
    require(not root.exists(), "Use a nonexistent series directory; retain every previous attempt")
    root.mkdir(parents=True)
    publish(root / "series-owner.json", {"schema": 1, "kind": KIND, "root": str(root)})
    try:
        publish(root / "plan-attempt.json", {"schema": 1, "startedAtUtc": utc(), "config": str(Path(config_file).resolve())})
        config = validate_config(read_json(config_file))
        before = {"source": source_snapshot(), "inputs": capture_inputs(config)}
        p = config["preparation"]
        built = candidate.build_candidate(Path(p["baseVsix"]), REPO / "scripts/variant/file-based-apps", "win32-arm64",
                                          before["source"]["commit"], root / "candidate.vsix", p["baseSha256"])
        publish(root / "candidate-manifest.json", {"schema": 1, "candidate": built})
        after = {"source": source_snapshot(), "inputs": capture_inputs(config)}
        require(before == after, "Source or execution inputs changed while planning")
        value = {"schema": 1, "kind": KIND, "root": str(root), "plannedAtUtc": utc(), "profiles": list(PROFILES),
                 "cycles": 10, "scenario": "native-f5", "nativeF5Input": config["nativeF5Input"], "config": config,
                 **before, "candidate": built, "candidateFile": proof(root / "candidate.vsix"),
                 "candidateManifest": proof(root / "candidate-manifest.json"), "phaseSafetyTimeoutMilliseconds": 90000,
                 "manualHelperSafetySeconds": 30, "manualWrapperSettlementSeconds": 30,
                 "scope": {"localOnly": True, "published": False, "qualification": False,
                           "target": "win32-arm64", "fixture": "one no-folder Slim HTTP Web file",
                           "hardwareInputIndependentlyVerified": False, "menu": False, "macOS": False},
                 "metadataMeaning": "declaredMetadata and conditions are operator declarations; executable versions, hashes and source are observed. Unknown declarations do not qualify a target.",
                 "deadlineMeaning": "Frozen harness safety caps; not calibrated product or qualification budgets."}
        publish(root / "series-plan.json", value)
        return value
    except Exception as error:
        fail(root, "plan", None, error)
        raise


def prepared(root, plan, profile):
    record = read_json(root / ("prepare-" + profile + "-result.json"))
    require(record.get("success") is True and record.get("exitCode") == 0, "Profile preparation did not pass")
    require(record["before"]["plan"] == proof(root / "series-plan.json"), "Series plan changed after preparation")
    work = root / profile
    require(proof(work / "expected.json") == record["expected"], "Prepared metadata changed")
    expected = read_json(work / "expected.json")
    require(expected.get("schema") == 1 and expected.get("scenario") == "native-f5" and expected.get("cycles") == 10, "Wrong prepared scenario/count")
    require(expected.get("scope", {}).get("qualification") is False and expected["scope"].get("localOnly") is True and expected["scope"].get("published") is False, "Prepared metadata overclaims its control scope")
    require(expected["nativeF5"].get("inputMode") == plan["nativeF5Input"], "Prepared input mode differs")
    local = work / "local-lifecycle.vsix"
    require(Path(expected["candidate"]["path"]) == local and proof(local)["sha256"] == plan["candidate"]["sha256"], "Profile does not reuse the exact candidate ZIP")
    require({k: v for k, v in expected["candidate"].items() if k != "path"} == {k: v for k, v in plan["candidate"].items() if k != "path"}, "Candidate identity differs")
    for key in ("profile", "extensions", "workspace", "driver", "appdata", "localappdata", "dotnet-home", "nuget-packages", "nuget-cache", "tmp"):
        require((work / key).is_dir() and (work / key).resolve().is_relative_to(work), "Profile directory is missing or escapes isolation")
    return expected


def prepare_profile(root, plan, profile):
    if profile == "r02":
        passed_profile(root, plan, "r01")
    else:
        require(not (root / "r02").exists(), "Second profile cannot precede the first")
    work = root / profile
    require(not work.exists(), "Retain the first profile preparation")
    p = plan["config"]["preparation"]
    flags = {"base-vsix": p["baseVsix"], "base-sha256": p["baseSha256"], "runtime-vsix": p["runtimeVsix"],
             "runtime-sha256": p["runtimeSha256"], "editor": p["editor"], "editor-cli": p["editorCli"],
             "dotnet": p["dotnet"], "sdk-version": p["sdkVersion"], "work-dir": str(work), "cycles": "10",
             "scenario": "native-f5", "native-f5-input": plan["nativeF5Input"],
             "candidate-manifest": str(root / "candidate-manifest.json"), "candidate-manifest-sha256": plan["candidateManifest"]["sha256"]}
    argv = [plan["inputs"]["python"]["path"], "-B", str(LIFECYCLE / "prepare.py")]
    for name, value in flags.items():
        argv += ["--" + name, value]
    with (root / ("prepare-" + profile + ".log")).open("xb") as log:
        result = subprocess.run(argv, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
    require(result.returncode == 0, "Profile preparation failed; retain its first output")
    expected = read_json(work / "expected.json")
    require(expected["cycles"] == 10 and expected["nativeF5"]["inputMode"] == plan["nativeF5Input"], "Preparation changed frozen count/mode")
    require(Path(expected["candidate"]["path"]) == work / "local-lifecycle.vsix", "Expected the profile-local candidate")
    require(proof(work / "local-lifecycle.vsix")["sha256"] == plan["candidate"]["sha256"], "Preparation did not reuse exact candidate bytes")
    return {"exitCode": result.returncode, "argv": argv, "expected": proof(work / "expected.json"), "log": proof(root / ("prepare-" + profile + ".log"))}


def retained_snapshot(work, snapshot):
    file = contained(work, snapshot["path"])
    actual = proof(file)
    require(actual["sha256"] == snapshot["sha256"] and actual["bytes"] == snapshot["size"], "Retained raw input evidence changed")
    if "base64" in snapshot:
        require(base64.b64decode(snapshot["base64"], validate=True) == file.read_bytes(), "Embedded input bytes differ")
    return read_json(file)


def embedded_snapshot(snapshot):
    data = base64.b64decode(snapshot["base64"], validate=True)
    require(len(data) == snapshot["size"] and digest(data) == snapshot["sha256"], "Invalid embedded source snapshot")
    return data


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def phase_labels():
    labels = ["verify installed local candidate", "native F5 setup-only keybinding logging"]
    for sequence in range(1, 11):
        if sequence > 1:
            labels.append(f"native F5 input {sequence} dirty repeat preparation after exact cleanup")
        labels += [f"native F5 input {sequence} breakpoint and HTTP revision", f"native F5 input {sequence} exact API Stop and actual cleanup"]
    return labels


def log_tail(work, snapshot):
    data = contained(work, snapshot["path"]).read_bytes().decode("utf-8").encode("utf-16-le")
    offset, length = snapshot["offsetCharacters"] * 2, snapshot["tailCharacters"] * 2
    require(type(offset) is int and type(length) is int and offset >= 0 and length >= 0 and offset + length <= len(data), "Invalid retained log range")
    prefix, tail = data[:offset].decode("utf-16-le"), data[offset:offset + length].decode("utf-16-le")
    require(digest(prefix.encode()) == snapshot["prefixSha256"] and digest(tail.encode()) == snapshot["tailSha256"], "Retained log evidence changed")
    return tail


def logged_builds(text, source):
    builds = []
    decoder = json.JSONDecoder()
    for line in text.splitlines():
        if not line.startswith("dotnet "):
            continue
        args, remaining = [], line[len("dotnet "):]
        while remaining:
            value, end = decoder.raw_decode(remaining)
            require(isinstance(value, str), "Logged build argument is not a string")
            args.append(value)
            remaining = remaining[end:].lstrip(" ")
        if len(args) > 1 and args[0] == "build" and Path(args[1]) == source:
            require("--output" in args and args.index("--output") + 1 < len(args), "Build has no owned output")
            builds.append({"args": args, "output": args[args.index("--output") + 1]})
    return builds


def validate_receipt(request, receipt, mode):
    require(request.get("schema") == receipt.get("schema") == 1, "Wrong native-input schema")
    require(request.get("action") == "press-key" and request.get("key") == "F5" and request.get("mechanism") == mode, "Wrong requested input")
    require(receipt.get("editorFocusedBeforeInput") is True and isinstance(receipt.get("observedWindowTitle"), str) and request["windowTitle"] in receipt["observedWindowTitle"], "Input lacks exact observed window/focus")
    require(request["nonce"] in request["windowTitle"], "Window title lacks profile nonce")
    require(receipt.get("inputMode", mode) == request.get("inputMode", mode) == mode, "Receipt changed input mode")
    manual_keys = ("actor", "attestedAtUtc", "evidenceKind", "oneF5KeyPressed", "inputOccurredDuringRequest", "automationUsed", "targetCommandApiUsed", "observationNote")
    if mode == "manual-native":
        require(all(key not in receipt for key in ("inputAtUtc", "windowId", "keyCallReturned", "arguments", "keyCallResult")), "Manual declaration contains injected measurements")
        require(receipt.get("tool") == "human-observer" and receipt.get("evidenceKind") == "human-attestation", "Wrong manual evidence kind")
        actor = receipt.get("actor", {})
        require(set(actor) == {"id", "type"} and actor["type"] == "human" and isinstance(actor["id"], str) and actor["id"].strip(), "Manual declaration lacks named human")
        require(isinstance(receipt.get("observationNote"), str) and receipt["observationNote"].strip(), "Manual declaration lacks observation")
        require(all(receipt.get(key) is True for key in ("oneF5KeyPressed", "inputOccurredDuringRequest")), "Missing one-key declaration")
        require(all(receipt.get(key) is False for key in ("automationUsed", "targetCommandApiUsed", "nativeExecutionVerified", "hardwareKeypressIndependentlyVerified")), "Manual declaration overclaims evidence")
        timestamp = receipt.get("attestedAtUtc")
    else:
        require(receipt.get("tool") == "sky.press_key" and all(key not in receipt for key in manual_keys), "Wrong injected evidence kind")
        window = receipt.get("windowId")
        require(type(window) in (str, int, float) and str(window) and (type(window) is str or math.isfinite(window)), "Injected receipt lacks window identifier")
        timestamp = receipt.get("inputAtUtc")
    times = []
    for value in (request.get("requestedAtUtc"), timestamp, request.get("expiresAtUtc")):
        require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?(?:Z|[+-]\d\d:\d\d)", value), "Ambiguous input timestamp")
        times.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
    require(times[0] <= times[1] <= times[2] and times[0] < times[2], "Input declaration is outside the request")


def validate_profile_evidence(root, plan, profile):
    work = root / profile
    expected = prepared(root, plan, profile)
    result = read_json(work / "result.json")
    launcher = read_json(work / "launcher-result.json")
    launch_record = read_json(work / "launch.json")
    require(launcher.get("success") is True and launcher.get("editorExitCode") == 0 and launcher.get("work") == str(work), "Launcher did not pass")
    require(launch_record.get("work") == str(work) and launch_record.get("freshProfile") is True and launch_record.get("visibleWindowRequested") is True, "Missing fresh visible-profile launch evidence")
    require(launcher.get("pid") == launch_record.get("pid") and launcher.get("candidateSha256") == plan["candidate"]["sha256"] and launcher.get("nativeInputMode") == plan["nativeF5Input"] and launcher.get("visibleWindowRequested") is True, "Launcher candidate/input identity differs")
    require(result.get("success") is True and not result.get("firstFailure") and result.get("cleanup") == [], "Driver failed or needed failure cleanup")
    require(result.get("expected") == expected and result.get("safetyTimeoutMilliseconds") == 90000, "Driver inputs differ")
    phases = result.get("phases", [])
    require([phase.get("label") for phase in phases] == phase_labels() and all(p.get("outcome") == "passed" and finite(p.get("elapsedMilliseconds")) and finite(p.get("startedAtMilliseconds")) for p in phases), "Missing or failed phase evidence")
    require(result.get("nativeF5", {}).get("inputMode") == plan["nativeF5Input"], "Driver input mode changed")
    scope = result.get("scope", {})
    require(scope.get("platform") == "win32-arm64" and scope.get("noFolderWindow") is True and scope.get("targetCommandApiLaunch") is False and scope.get("hardwareInputIndependentlyVerified") is False, "Driver scope overclaims or differs from the native control")
    require(scope.get("qualification") is False and scope.get("localOnly") is True and scope.get("published") is False, "Driver result contradicts its local, unqualified scope")
    inputs, launches = result["nativeF5"].get("inputs", []), result.get("launches", [])
    require(len(inputs) == len(launches) == 10 and [x.get("sequence") for x in inputs] == list(range(1, 11)), "Incomplete ten-cycle result")
    installed = result.get("installedExtension", {})
    require(Path(installed.get("path", "")).resolve().is_relative_to(work / "extensions"), "Loaded extension escapes the fresh profile")
    require(installed.get("build", {}).get("lifecycleBuildId") == plan["candidate"]["buildId"], "Loaded candidate identity differs")
    require(installed["build"].get("localCandidate") is True and installed["build"].get("target") == "win32-arm64" and installed["build"].get("lifecycleSourceCommit") == plan["source"]["commit"] and installed.get("version") == plan["candidate"]["version"], "Loaded candidate metadata differs")
    dependency = result.get("installedDependency", {})
    require(dependency.get("version") == "3.2.0" and Path(dependency.get("path", "")).resolve().is_relative_to(work / "extensions"), "Runtime dependency identity differs")
    require(result.get("installedModules") == plan["candidate"]["ownedModules"], "Loaded module hashes differ")
    for key in ("sessionId", "nonce", "output"):
        require(all(x.get(key) for x in launches) and len({x[key] for x in launches}) == 10, "Every cycle needs a distinct " + key)
    fixture = (LIFECYCLE / "fixtures/web.cs").read_bytes()
    marker_lines = [index + 1 for index, line in enumerate(fixture.decode("utf-8").splitlines()) if line.strip() == "marker += 2;"]
    require(len(marker_lines) == 1, "Frozen fixture must have one exact breakpoint statement")
    previous_source = fixture
    trace = [json.loads(line) for line in (work / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_api_actions = []
    for sequence, (item, launch) in enumerate(zip(inputs, launches), 1):
        label = "F5-" + str(sequence)
        revision = "initial" if sequence == 1 else "retry-f5-" + str(sequence)
        require(item.get("label") == launch.get("label") == label and launch.get("revision") == revision, "Cycle labels/revisions differ")
        require(Path(launch["source"]) == work / "workspace/a.cs", "Cycle source differs")
        request = retained_snapshot(work, item["requestSnapshot"])
        receipt = retained_snapshot(work, item["receiptSnapshot"])
        require(request == item["request"] and receipt == item["receipt"], "Raw request/receipt differs from driver evidence")
        require(Path(item["requestSnapshot"]["path"]) == work / f"needs-f5-input-{sequence:02}.json" and Path(item["receiptSnapshot"]["path"]) == work / f"f5-input-action-{sequence:02}.json", "Unexpected input artifact paths")
        require(receipt.get("requestSha256") == item["requestSnapshot"]["sha256"], "Receipt is not bound to raw request")
        for key in ("nonce", "sequence", "launchToken", "windowTitle", "action", "key", "mechanism"):
            require(receipt.get(key) == request.get(key), "Receipt binding differs: " + key)
        validate_receipt(request, receipt, plan["nativeF5Input"])
        require(request.get("nonce") == expected["nativeF5"]["nonce"] and request.get("launchToken") == launch["nonce"] and request.get("sequence") == sequence and request.get("mechanism") == plan["nativeF5Input"], "Input is not bound to the planned launch")
        require(request.get("isDirty") is (sequence > 1) and request.get("noFolderWindow") is True, "Missing dirty/no-folder evidence")
        retained_snapshot(work, item["observationSnapshot"])
        retained_snapshot(work, item["inputRecordSnapshot"])
        require(Path(receipt["observationPath"]) == Path(item["observationSnapshot"]["path"]) and Path(receipt["inputRecordPath"]) == Path(item["inputRecordSnapshot"]["path"]), "Raw attestation paths differ")
        if plan["nativeF5Input"] == "manual-native":
            require(receipt.get("actor", {}).get("type") == "human" and receipt.get("tool") == "human-observer" and receipt.get("evidenceKind") == "human-attestation" and receipt.get("automationUsed") is False and receipt.get("targetCommandApiUsed") is False, "Missing human-only attestation")
            wrapper = read_json(root / f"manual-input-{profile}-{sequence:02}-result.json")
            require(wrapper.get("success") is True and wrapper.get("exitCode") == 0 and wrapper.get("receipt") == proof(work / f"f5-input-action-{sequence:02}.json"), "Manual helper attempt did not pass through the series wrapper")
        else:
            require(receipt.get("tool") == "sky.press_key" and "actor" not in receipt, "Wrong injected input evidence")
        before = embedded_snapshot(request["diskBefore"])
        after = embedded_snapshot(item["diskAfter"])
        intended = fixture.replace(b'const string revision = "initial";', ('const string revision = "' + revision + '";').encode())
        require(before == previous_source and after == intended, "Source does not retain the exact planned fixture/revision sequence")
        require(Path(request["diskBefore"]["path"]) == Path(item["diskAfter"]["path"]) == work / "workspace/a.cs", "Source snapshot paths differ")
        require(digest(after) == request["bufferBefore"]["sha256"] and len(after) == request["bufferBefore"]["bytes"] and (before != after) is (sequence > 1), "Saved content does not match the requested dirty buffer")
        previous_source = after
        if sequence > 1:
            require(bool(item.get("savedEvents")), "Dirty repeat has no save event")
            require(any(Path(event["source"]) == work / "workspace/a.cs" and embedded_snapshot(event["disk"]) == after for event in item["savedEvents"]), "Save event does not bind the new source")
        route, builds = item.get("route", {}), item.get("builds", [])
        require(len(route.get("f5Dispatches", [])) == len(route.get("targetCommands", [])) == len(builds) == 1, "Native input did not route to exactly one command/build")
        require(builds[0].get("output") == launch["output"], "Build output differs from owned launch")
        tail = log_tail(work, route)
        dispatches = [line for line in tail.splitlines() if re.search(r"KeybindingService#dispatch\s+F5\s+", line)]
        commands = [line for line in tail.splitlines() if re.search(r"CommandService#executeCommand\s+netcoredbg\.debugActiveFile\s*$", line)]
        require(dispatches == route["f5Dispatches"] and commands == route["targetCommands"] and re.search(r"KeybindingService#dispatch\s+F5\s+\[ Will dispatch command netcoredbg\.debugActiveFile \]", dispatches[0]), "Renderer tail lacks exactly the native route")
        output = item.get("outputEvidence", {})
        output_tail = log_tail(work, output)
        completed = [line for line in output_tail.splitlines() if line.startswith("Phase completed: Starting netcoredbg")]
        require(logged_builds(output_tail, work / "workspace/a.cs") == builds == output.get("buildCommands") and len(completed) == 1 and output.get("completedPhaseDiagnostics") == completed, "Retained output lacks exactly the owned real build/start")
        require(item.get("breakpoint", {}).get("result") == "40" and item["breakpoint"].get("expression") == "marker" and item["breakpoint"].get("line") == marker_lines[0] and Path(item["breakpoint"]["source"]) == work / "workspace/a.cs", "Missing exact source breakpoint/evaluation")
        response = item.get("response", {})
        require(response == launch.get("response") and response.get("value") == 42 and response.get("nonce") == launch["nonce"] and response.get("revision") == revision and response.get("pid") == launch.get("pid"), "HTTP response ownership/revision differs")
        messages = [event["detail"]["message"] for event in trace if event.get("event") == "dap-receive" and event.get("detail", {}).get("label") == label and event["detail"].get("sessionId") == launch["sessionId"]]
        require(messages and messages == launch.get("dap"), "Raw DAP messages are not bound to the captured session trace")
        require(any(message.get("event") == "process" and message.get("body", {}).get("isLocalProcess") is True and message["body"].get("systemProcessId") == launch["pid"] for message in messages), "DAP lacks the owned process PID")
        require(any(message.get("event") == "stopped" and message.get("body", {}).get("reason") == "breakpoint" for message in messages), "DAP lacks source breakpoint stop")
        requests = [event["detail"]["message"] for event in trace if event.get("event") == "dap-send" and event.get("detail", {}).get("label") == label and event["detail"].get("sessionId") == launch["sessionId"]]
        for command in ("stackTrace", "evaluate"):
            matching = [request for request in requests if request.get("command") == command and (command != "evaluate" or request.get("arguments", {}).get("expression") == "marker")]
            require(matching, "Raw DAP lacks the source inspection request")
            replies = [message for message in messages if message.get("type") == "response" and message.get("command") == command and message.get("success") is True and message.get("request_seq") in {request["seq"] for request in matching}]
            if command == "evaluate":
                require(any(reply.get("body", {}).get("result") == "40" for reply in replies), "Raw DAP marker evaluation differs")
            else:
                require(any(reply.get("body", {}).get("stackFrames") and Path(reply["body"]["stackFrames"][0].get("source", {}).get("path", "")) == work / "workspace/a.cs" and reply["body"]["stackFrames"][0].get("line") == item["breakpoint"]["line"] for reply in replies), "Raw DAP source frame differs")
        require(any(event.get("event") == "http-ready" and event.get("detail", {}).get("label") == label and event["detail"].get("body") == response for event in trace), "HTTP response lacks its original trace")
        expected_api_actions += [{"action": "DAP continue", "sessionId": launch["sessionId"], "sequence": sequence}, {"action": "vscode.debug.stopDebugging", "sessionId": launch["sessionId"], "sequence": sequence}]
        sessions = launch.get("capturedSessions", [])
        require(len(sessions) == 1 and sessions[0].get("sessionId") == launch["sessionId"] and sessions[0].get("terminated") is True, "Exact session termination is missing")
        require(sessions[0].get("primary") is True and all(sessions[0].get(key) == launch.get(key) for key in ("pid", "program", "output", "terminatedAtMilliseconds")), "Captured exact session differs from owned launch")
        cleanup = launch.get("cleanupObservation", {})
        for key in ("base", "sessionId", "pid", "port", "output"):
            require(cleanup.get(key) == launch.get(key) and launch.get(key) is not None, "Cleanup is not bound to this launch: " + key)
        require(all(cleanup.get(key) is True for key in ("sessionTerminated", "pidExited", "portReusable", "outputAbsent", "terminalQueuesEmpty")), "Actual resource cleanup is incomplete")
        require(all(finite(cleanup.get("observedAtMilliseconds", {}).get(key)) for key in ("termination", "pid", "port", "outputAndQueues")), "Cleanup observations lack monotonic timings")
        for observed, recorded in (("termination", "terminatedAtMilliseconds"), ("pid", "pidGoneAtMilliseconds"), ("port", "portReusableAtMilliseconds"), ("outputAndQueues", "outputRemovedAtMilliseconds")):
            require(cleanup["observedAtMilliseconds"][observed] == launch.get(recorded), "Cleanup observation timing differs from owned launch")
    require(result["nativeF5"].get("postStartApiActions") == expected_api_actions, "Post-start API actions are missing or differ from the exact sessions")
    closed = read_json(work / "f5-input-closed.json")
    require(closed.get("nonce") == expected["nativeF5"]["nonce"] and not closed.get("closedBySeries"), "Input was externally stopped")
    return {"cycles": 10, "expected": proof(work / "expected.json"), "result": proof(work / "result.json"),
            "launcher": proof(work / "launcher-result.json"), "trace": proof(work / "trace.jsonl")}


def passed_profile(root, plan, profile):
    record = read_json(root / ("run-" + profile + "-result.json"))
    require(record.get("success") is True and record.get("exitCode") == 0, "Prior profile run did not pass")
    evidence = validate_profile_evidence(root, plan, profile)
    require(evidence == record["evidence"], "Prior profile evidence changed after its result")
    return evidence


def run_profile(root, plan, profile):
    if profile == "r02":
        passed_profile(root, plan, "r01")
    prepared(root, plan, profile)
    work = root / profile
    require(not any((work / name).exists() for name in ("attempt.json", "launch.json", "result.json", "launcher-result.json", "f5-input-closed.json")), "Retain the profile's first launch attempt")
    argv = [plan["inputs"]["powershell"]["path"], "-NoLogo", "-NoProfile", "-File", str(LIFECYCLE / "run.ps1"),
            "-WorkDir", str(work), "-DeadlineSeconds", str(plan["config"]["launcherDeadlineSeconds"]), "-ShowWindow"]
    with (root / ("run-" + profile + ".log")).open("xb") as log:
        result = subprocess.run(argv, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
    require(result.returncode == 0, "Native-F5 launcher failed")
    if plan["nativeF5Input"] == "manual-native":
        # The helper publishes before its wrapper postflight finishes. Join that
        # last wrapper outside the completed driver's unchanged 90-second phase.
        limit = time.monotonic() + plan["manualWrapperSettlementSeconds"]
        while not all((root / f"manual-input-{profile}-{sequence:02}-result.json").exists() for sequence in range(1, 11)):
            require(not (root / "first-failure.json.tmp").exists(), "Manual wrapper stopped the series")
            require(time.monotonic() < limit, "Manual wrapper settlement safety cap exceeded")
            time.sleep(0.05)
    evidence = validate_profile_evidence(root, plan, profile)
    return {"exitCode": result.returncode, "argv": argv, "evidence": evidence, "log": proof(root / ("run-" + profile + ".log"))}


def verify_series(root_value, active_profile=None):
    root = owned_root(root_value)
    plan = load_plan(root)
    before = freeze_snapshot(root, plan)
    def idle():
        require(not (root / "decision.lock").exists(), "A result publication is active or incomplete")
        if (root / "operation.lock").exists():
            active = read_json(root / "operation.lock")
            require(active_profile == "r02" and active.get("action") == "run" and active.get("profile") == active_profile, "A profile stage is active or incomplete")
        for profile in PROFILES:
            for action in ("prepare", "run"):
                token = action + "-" + profile
                require(not (root / (token + "-attempt.json.tmp")).exists() or (root / (token + "-result.json")).exists(), "A profile attempt is incomplete")
            for sequence in range(1, 11):
                token = f"manual-input-{profile}-{sequence:02}"
                require(not (root / (token + "-attempt.json.tmp")).exists() or (root / (token + "-result.json")).exists(), "A manual helper attempt is incomplete")
    idle()
    profiles = {profile: passed_profile(root, plan, profile) for profile in PROFILES}
    require(read_json(root / "r01/expected.json")["nativeF5"]["nonce"] != read_json(root / "r02/expected.json")["nativeF5"]["nonce"], "Profiles reused their native-F5 nonce")
    require(before == freeze_snapshot(root, plan), "Frozen inputs changed while verifying")
    idle()
    return {"schema": 1, "success": True, "profiles": profiles, "completedProfiles": 2, "completedCycles": 20,
            "candidateSha256": plan["candidate"]["sha256"], "buildId": plan["candidate"]["buildId"], "inputMode": plan["nativeF5Input"],
            "scope": plan["scope"], "qualification": False, "validationCompletedAtUtc": utc(),
            "meaning": "Point-in-time verification of this frozen control; a later stop remains authoritative."}


def stop_series(root_value, reason):
    root = owned_root(root_value)
    require(isinstance(reason, str) and reason.strip(), "Record the actual stop reason")
    fail(root, "operator-stop", None, reason.strip())
    return read_json(root / "first-failure.json")


def manual_input(root, plan, profile, options):
    require(plan["nativeF5Input"] == "manual-native", "Series was not planned for manual input")
    active = read_json(root / "operation.lock")
    require(active.get("action") == "run" and active.get("profile") == profile, "No matching active series run")
    prepared(root, plan, profile)
    require(options.confirm_human_f5, "Only the human who personally pressed F5 may confirm it")
    work = root / profile
    helper = work / "driver/native-f5-input.cjs"
    expected = read_json(work / "expected.json")
    require(proof(helper)["sha256"] == expected["harness"]["native-f5-input.cjs"], "Staged manual helper changed")
    argv = [plan["inputs"]["node"]["path"], str(helper), "--work-dir", str(work), "--sequence", str(options.sequence),
            "--observer", options.observer, "--observed-window-title", options.observed_window_title, "--note", options.note, "--confirm-human-f5"]
    logfile = root / f"manual-input-{profile}-{options.sequence:02}.log"
    with logfile.open("xb") as log:
        result = subprocess.run(argv, cwd=REPO, stdout=log, stderr=subprocess.STDOUT, timeout=plan["manualHelperSafetySeconds"])
    require(result.returncode == 0, "Manual receipt helper refused or could not publish; do not repeat input")
    return {"exitCode": 0, "argv": argv, "receipt": proof(work / f"f5-input-action-{options.sequence:02}.json"), "log": proof(logfile),
            "meaning": "Human declaration recorded; wrapper sends no key and provides no independent hardware-input proof."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("plan", "prepare", "run", "verify", "stop", "manual-input"):
        command = commands.add_parser(name)
        command.add_argument("--root", required=True, type=Path)
        if name == "plan":
            command.add_argument("--config", required=True, type=Path)
        if name in ("prepare", "run", "manual-input"):
            command.add_argument("--profile", choices=PROFILES, required=True)
        if name == "stop":
            command.add_argument("--reason", required=True)
        if name == "manual-input":
            command.add_argument("--sequence", type=int, choices=range(1, 11), required=True)
            command.add_argument("--observer", required=True)
            command.add_argument("--observed-window-title", required=True)
            command.add_argument("--note", required=True)
            command.add_argument("--confirm-human-f5", action="store_true")
    raw = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parser.parse_args(raw)
    except SystemExit as error:
        # A mistyped human receipt command after a key must not silently leave
        # a recognized, owned series open. Unknown roots remain untouched.
        if error.code and raw and raw[0] in ("prepare", "run", "manual-input") and raw.count("--root") == 1:
            try:
                index = raw.index("--root")
                root = owned_root(raw[index + 1])
                profile = raw[raw.index("--profile") + 1] if raw.count("--profile") == 1 else None
                fail(root, raw[0], profile if profile in PROFILES else None, "Series command arguments refused; retain the actual operator account")
            except (ValueError, OSError, IndexError, KeyError):
                pass
        raise
    if args.action == "plan":
        value = plan_series(args.root, args.config)
        output = {"planned": True, "root": value["root"], "candidateSha256": value["candidate"]["sha256"], "qualification": False}
    elif args.action == "verify":
        output = verify_series(args.root)
    elif args.action == "stop":
        output = stop_series(args.root, args.reason)
    elif args.action == "manual-input":
        output = stage(args.root, args.action, args.profile, lambda root, plan: manual_input(root, plan, args.profile, args), exclusive=False, suffix=f"{args.sequence:02}")
    else:
        operation = prepare_profile if args.action == "prepare" else run_profile
        output = stage(args.root, args.action, args.profile, lambda root, plan: operation(root, plan, args.profile))
    print(json.dumps(output))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Native-F5 series refused: " + str(error), file=sys.stderr)
        sys.exit(1)
