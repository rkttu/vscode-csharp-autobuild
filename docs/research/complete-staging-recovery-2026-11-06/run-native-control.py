"""Retain actual native Node processes across complete-STAGING publication loss."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

REPO = Path(__file__).resolve().parents[3]
BASELINE = "8681a7b6e46201fb29c87efd03ae1e418c5d28e9"
MODULES = "scripts/variant/file-based-apps/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(file, value):
    with file.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--recovery-ref")
    parser.add_argument("--expect-recovered", choices=("yes", "no"), required=True)
    args = parser.parse_args()
    node = args.node.resolve(strict=True)
    work = args.work_dir.resolve()
    if work.exists() and any(work.iterdir()):
        raise ValueError("Retain the first attempt and choose a fresh directory")
    work.mkdir(parents=True, exist_ok=True)
    modules = work / "modules"
    modules.mkdir()
    source = {}
    for name in ("runtime.cjs", "recovery.cjs", "test-recovery.cjs"):
        revision = BASELINE if name == "runtime.cjs" else args.recovery_ref
        data = subprocess.check_output(["git", "show", f"{revision}:{MODULES}{name}"], cwd=REPO) if revision else (REPO / MODULES / name).read_bytes()
        (modules / name).write_bytes(data)
        source[name] = {"sha256": digest(data), "source": f"git:{revision}:{MODULES}{name}" if revision else str(REPO / MODULES / name)}
    assert (modules / "runtime.cjs").read_bytes().replace(b"\r\n", b"\n") == (REPO / MODULES / "runtime.cjs").read_bytes().replace(b"\r\n", b"\n")
    driver = Path(__file__).with_name("native-control.cjs")
    snapshot = work / "native-control.cjs"
    snapshot.write_bytes(driver.read_bytes())
    input_record = {"schema": 1, "workDirectory": str(work), "nonce": str(uuid.uuid4()),
                    "expectedRecovery": args.expect_recovered == "yes", "source": source,
                    "moduleSha256": {name: value["sha256"] for name, value in source.items()},
                    "driverSha256": digest(snapshot.read_bytes()), "runnerSha256": digest(Path(__file__).read_bytes()),
                    "node": {"executable": str(node), "sha256": digest(node.read_bytes())},
                    "scope": {"nativeNodeProcesses": True, "actualProductRuntime": True, "actualFilesystem": True,
                              "injectedSdkResults": True, "stubbedVSCodeApi": True, "installedEditor": False,
                              "actualDebuggee": False, "hostCrashQualification": False}}
    write_json(work / "input.json", input_record)
    processes = []
    try:
        for phase, expected_exit in (("interrupt", 73), ("recover", 0)):
            command = [str(node), "--unhandled-rejections=strict", str(snapshot), phase, str(work)]
            with (work / f"{phase}.stdout.txt").open("xb") as stdout, (work / f"{phase}.stderr.txt").open("xb") as stderr:
                child = subprocess.Popen(command, cwd=work, stdout=stdout, stderr=stderr)
                try:
                    code = child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()  # Exact subprocess owned by this runner, never a name/tree sweep.
                    child.wait(timeout=5)
                    raise
            processes.append({"phase": phase, "pid": child.pid, "command": command, "exitCode": code, "expectedExitCode": expected_exit})
            if code != expected_exit:
                raise ValueError(f"Unexpected {phase} exit {code}; first evidence retained")
        before = json.loads((work / "interruption-proof.json").read_text(encoding="utf-8"))
        after = json.loads((work / "recovery-proof.json").read_text(encoding="utf-8"))
        expected = args.expect_recovered == "yes"
        assert processes[0]["pid"] == before["pid"] != after["pid"] == processes[1]["pid"]
        assert before["completeBeforePublication"] and before["sourceMoveCompleted"] and not before["publicationRenameExecuted"]
        assert not before["calls"]["removals"]
        assert all(value["unchanged"] for value in after["observations"])
        assert after["completeStageRecovered"] == expected and after["residualExists"] != expected
        assert not after["readyExists"] and after["readyQueueEmpty"]
        assert after["stagingExists"] != expected
        if expected:
            assert 1 <= after["recovery"]["scanned"] <= 32
            assert after["recovery"]["attempted"] == 1 and after["recovery"]["removed"] == 1
            assert len(after["removals"]) == 1
            assert after["removals"][0]["directory"] == str(Path(before["readyEntry"]) / "output")
        else:
            assert after["recovery"] == {"scanned": 0, "attempted": 0, "removed": 0}
            assert not after["removals"]
        result = {"schema": 1, "success": True, "expectedBehavior": "complete-stage-recovered" if expected else "baseline-gap-reproduced",
                  "desiredBehaviorObserved": expected, "processes": processes, "input": input_record, "interruption": before, "coldRecovery": after}
        write_json(work / "result.json", result)
        files = [file for file in work.iterdir() if file.is_file()] + list(modules.iterdir())
        write_json(work / "hashes.json", {file.relative_to(work).as_posix(): {"sha256": digest(file.read_bytes()), "bytes": file.stat().st_size} for file in files})
        print(json.dumps({"workDirectory": str(work), "desiredBehaviorObserved": expected,
                          "pids": [value["pid"] for value in processes], "resultSha256": digest((work / "result.json").read_bytes())}))
    except Exception as error:
        write_json(work / "first-failure.json", {"schema": 1, "error": str(error), "processes": processes})
        raise


if __name__ == "__main__":
    main()
