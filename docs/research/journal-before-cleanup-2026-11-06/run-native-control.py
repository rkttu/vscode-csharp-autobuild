"""Retain two native Node processes at the product's first cleanup boundary."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

REPO = Path(__file__).resolve().parents[3]
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
    parser.add_argument("--runtime-ref")
    parser.add_argument("--recovery-ref", default="5e98bf8fa6f78264f28220a8e2be13af84197818")
    parser.add_argument("--expect-published", choices=("yes", "no"), required=True)
    args = parser.parse_args()
    node = args.node.resolve(strict=True)
    work = args.work_dir.resolve()
    if work.exists() and any(work.iterdir()):
        raise ValueError("Retain this first attempt and choose a fresh work directory")
    work.mkdir(parents=True, exist_ok=True)
    modules = work / "modules"
    modules.mkdir()
    source = {}
    for name in ("runtime.cjs", "recovery.cjs", "test-runtime.cjs"):
        revision = args.recovery_ref if name == "recovery.cjs" else args.runtime_ref
        data = subprocess.check_output(["git", "show", f"{revision}:{MODULES}{name}"], cwd=REPO) if revision else (REPO / MODULES / name).read_bytes()
        (modules / name).write_bytes(data)
        source[name] = {"sha256": digest(data), "source": f"git:{revision}:{MODULES}{name}" if revision else str(REPO / MODULES / name)}
    current_recovery = (REPO / MODULES / "recovery.cjs").read_bytes().replace(b"\r\n", b"\n")
    assert (modules / "recovery.cjs").read_bytes().replace(b"\r\n", b"\n") == current_recovery
    driver = Path(__file__).with_name("native-control.cjs")
    driver_snapshot = work / "native-control.cjs"
    driver_snapshot.write_bytes(driver.read_bytes())
    input_record = {"schema": 1, "workDirectory": str(work), "nonce": str(uuid.uuid4()),
                    "expectedPublishedBeforeDelete": args.expect_published == "yes", "source": source,
                    "moduleSha256": {name: value["sha256"] for name, value in source.items()},
                    "driverSha256": digest(driver_snapshot.read_bytes()), "runnerSha256": digest(Path(__file__).read_bytes()),
                    "node": {"executable": str(node), "sha256": digest(node.read_bytes())},
                    "scope": {"nativeNodeProcesses": True, "actualProductRuntime": True, "actualFilesystem": True,
                              "injectedSdkResults": True, "stubbedVSCodeApi": True, "installedEditor": False,
                              "actualDebuggee": False, "hostCrashQualification": False}}
    write_json(work / "input.json", input_record)
    processes = []
    try:
        for phase, expected_exit in (("interrupt", 73), ("recover", 0)):
            command = [str(node), "--unhandled-rejections=strict", str(driver_snapshot), phase, str(work)]
            with (work / f"{phase}.stdout.txt").open("xb") as stdout, (work / f"{phase}.stderr.txt").open("xb") as stderr:
                child = subprocess.Popen(command, cwd=work, stdout=stdout, stderr=stderr)
                try:
                    code = child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()  # Exact child of this runner, never a process-tree/name sweep.
                    child.wait(timeout=5)
                    raise
            processes.append({"phase": phase, "pid": child.pid, "command": command, "exitCode": code, "expectedExitCode": expected_exit})
            if code != expected_exit:
                raise ValueError(f"Unexpected {phase} exit {code}; first logs retained")
        before = json.loads((work / "interruption-proof.json").read_text(encoding="utf-8"))
        after = json.loads((work / "recovery-proof.json").read_text(encoding="utf-8"))
        expected = args.expect_published == "yes"
        assert processes[0]["pid"] == before["pid"] != after["pid"] == processes[1]["pid"]
        assert before["publishedBeforeFirstDelete"] == expected and before["partialLeafRemoved"]
        assert all(value["unchanged"] for value in after["observations"])
        assert after["terminalJournalRecovered"] == expected and after["residualExists"] != expected
        assert after["recovery"] == ({"scanned": 1, "attempted": 1, "removed": 1} if expected else {"scanned": 0, "attempted": 0, "removed": 0})
        result = {"schema": 1, "success": True, "expectedBehavior": "published-before-first-delete" if expected else "baseline-gap-reproduced",
                  "desiredBehaviorObserved": expected, "processes": processes, "input": input_record, "interruption": before, "coldRecovery": after}
        write_json(work / "result.json", result)
        files = [file for file in work.iterdir() if file.is_file()] + list(modules.iterdir())
        write_json(work / "hashes.json", {file.relative_to(work).as_posix(): {"sha256": digest(file.read_bytes()), "bytes": file.stat().st_size} for file in files})
        print(json.dumps({"workDirectory": str(work), "expectedPublishedBeforeDelete": expected, "desiredBehaviorObserved": expected,
                          "pids": [value["pid"] for value in processes], "resultSha256": digest((work / "result.json").read_bytes())}))
    except Exception as error:
        write_json(work / "first-failure.json", {"schema": 1, "error": str(error), "processes": processes})
        raise


if __name__ == "__main__":
    main()
