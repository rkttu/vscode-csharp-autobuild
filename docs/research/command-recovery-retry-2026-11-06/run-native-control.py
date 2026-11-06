"""Retain real native writer/reader controls for a same-host recovery retry."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

REPO = Path(__file__).resolve().parents[3]
BASELINE = "bc94c900acadd09fd29a949497818b4c36b43edb"
MODULES = "scripts/variant/file-based-apps/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(file, value):
    with file.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def git_module(name):
    return subprocess.check_output(["git", "show", f"{BASELINE}:{MODULES}{name}"], cwd=REPO)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--reader-runtime", choices=("baseline", "current"), required=True)
    args = parser.parse_args()
    node = args.node.resolve(strict=True)
    work = args.work_dir.resolve()
    if work.exists() and any(work.iterdir()):
        raise ValueError("Retain the first attempt and choose a fresh directory")
    work.mkdir(parents=True, exist_ok=True)
    sources = {}
    for role in ("writer", "reader"):
        directory = work / (role + "-modules")
        directory.mkdir()
        sources[role] = {}
        for name in ("runtime.cjs", "recovery.cjs"):
            current = role == "reader" and name == "runtime.cjs" and args.reader_runtime == "current"
            data = (REPO / MODULES / name).read_bytes() if current else git_module(name)
            (directory / name).write_bytes(data)
            sources[role][name] = {"sha256": digest(data), "source": str(REPO / MODULES / name) if current else f"git:{BASELINE}:{MODULES}{name}"}
    test = REPO / MODULES / "test-runtime.cjs"
    (work / "test-runtime.cjs").write_bytes(test.read_bytes())
    driver = Path(__file__).with_name("native-control.cjs")
    snapshot = work / "native-control.cjs"
    snapshot.write_bytes(driver.read_bytes())
    input_record = {"schema": 1, "workDirectory": str(work), "nonce": str(uuid.uuid4()),
                    "expectedRecovery": args.reader_runtime == "current", "sources": sources,
                    "writerModules": {name: value["sha256"] for name, value in sources["writer"].items()},
                    "readerModules": {name: value["sha256"] for name, value in sources["reader"].items()},
                    "testRuntimeSha256": digest(test.read_bytes()),
                    "controlledTiming": {"sdkWaitsForOldDeleteEntry": args.reader_runtime == "current", "postCommandObservationMs": 0 if args.reader_runtime == "current" else 100},
                    "driverSha256": digest(snapshot.read_bytes()), "runnerSha256": digest(Path(__file__).read_bytes()),
                    "node": {"executable": str(node), "sha256": digest(node.read_bytes())},
                    "scope": {"nativeNodeProcesses": True, "actualProductRuntime": True, "actualFilesystem": True,
                              "sameReaderPid": True, "injectedSdkResults": True, "stubbedVSCodeApi": True,
                              "installedEditor": False, "actualDebuggee": False, "hostCrashQualification": False}}
    write_json(work / "input.json", input_record)
    processes = []
    try:
        for phase, expected_exit in (("write", 73), ("read", 0)):
            command = [str(node), "--unhandled-rejections=strict", str(snapshot), phase, str(work)]
            with (work / f"{phase}.stdout.txt").open("xb") as stdout, (work / f"{phase}.stderr.txt").open("xb") as stderr:
                child = subprocess.Popen(command, cwd=work, stdout=stdout, stderr=stderr)
                try:
                    code = child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()  # This runner's exact subprocess; never a name or process-tree sweep.
                    child.wait(timeout=5)
                    raise
            processes.append({"phase": phase, "pid": child.pid, "command": command, "exitCode": code, "expectedExitCode": expected_exit})
            if code != expected_exit:
                raise ValueError(f"Unexpected {phase} exit {code}; first evidence retained")
        publication = json.loads((work / "publication-proof.json").read_text(encoding="utf-8"))
        recovery = json.loads((work / "recovery-proof.json").read_text(encoding="utf-8"))
        startup = json.loads((work / "startup-proof.json").read_text(encoding="utf-8"))
        command_proof = json.loads((work / "command-proof.json").read_text(encoding="utf-8"))
        expected = input_record["expectedRecovery"]
        assert processes[0]["pid"] == publication["pid"] != recovery["pid"] == processes[1]["pid"]
        assert startup["pid"] == command_proof["pid"] == recovery["pid"]
        assert publication["published"] and not publication["recursiveDeleteExecuted"]
        assert startup["recovery"] == {"scanned": 1, "attempted": 1, "removed": 0}
        assert command_proof["commandResult"] and command_proof["commandLaunched"]
        assert recovery["desiredBehaviorObserved"] is expected and recovery["oldEntryAbsent"] is expected
        assert recovery["oldPayloadPresent"] is not expected
        assert recovery["ownOutputAbsent"] and recovery["outputDisposed"]
        assert all(value["unchanged"] for value in recovery["observations"])
        attempts = command_proof["oldDeletionAttempts"]
        assert len(attempts) == (2 if expected else 1) and attempts[0]["failed"] == "EBUSY"
        if expected:
            assert attempts[1]["releasedAfterCommandLaunch"] and attempts[1]["removed"]
        result = {"schema": 1, "success": True, "expectedBehavior": "same-host-command-retry" if expected else "baseline-no-retry-reproduced",
                  "desiredBehaviorObserved": expected, "processes": processes, "input": input_record,
                  "publication": publication, "startup": startup, "command": command_proof, "recovery": recovery}
        write_json(work / "result.json", result)
        files = [file for file in work.iterdir() if file.is_file()]
        for directory in (work / "writer-modules", work / "reader-modules"):
            files.extend(directory.iterdir())
        write_json(work / "hashes.json", {file.relative_to(work).as_posix(): {"sha256": digest(file.read_bytes()), "bytes": file.stat().st_size} for file in files})
        print(json.dumps({"workDirectory": str(work), "desiredBehaviorObserved": expected,
                          "pids": [value["pid"] for value in processes], "resultSha256": digest((work / "result.json").read_bytes())}))
    except Exception as error:
        write_json(work / "first-failure.json", {"schema": 1, "error": str(error), "processes": processes})
        raise


if __name__ == "__main__":
    main()
