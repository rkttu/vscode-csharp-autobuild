"""Prepare the dedicated two-launch installed interruption control."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent

def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()

def main():
    args = sys.argv[1:]
    if "--work-dir" not in args:
        raise ValueError("Pass the shared preparer's required --work-dir")
    work = Path(args[args.index("--work-dir") + 1]).resolve()
    subprocess.run([sys.executable, "-X", "utf8", str(HERE.parent / "prepare.py"), *args], check=True)
    test = work / "driver/extension-test.cjs"
    test.write_bytes((HERE / "extension-test.cjs").read_bytes())
    expected_file = work / "expected.json"
    expected = json.loads(expected_file.read_text())
    expected["scenario"] = "installed-interrupted-cleanup"
    expected["harness"]["extension-test.cjs"] = digest(test)
    expected["harness"]["interrupted-cleanup/prepare.py"] = digest(HERE / "prepare.py")
    expected["harness"]["interrupted-cleanup/run.ps1"] = digest(HERE / "run.ps1")
    expected["interruption"] = {"schema": 1, "nonce": str(uuid.uuid4()), "expectedHostExitCode": 73}
    expected_file.write_text(json.dumps(expected, indent=2) + "\n")
    print(json.dumps({"workDir": str(work), "candidateSha256": expected["candidate"]["sha256"],
                      "nonce": expected["interruption"]["nonce"]}))

if __name__ == "__main__":
    main()
