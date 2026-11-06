"""Prepare one installed editor/host control for command-triggered recovery retry."""
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
    expected["scenario"] = "installed-command-recovery-retry"
    expected["harness"]["extension-test.cjs"] = digest(test)
    for name in ("prepare.py", "run.ps1"):
        expected["harness"]["command-recovery/" + name] = digest(HERE / name)
    expected["commandRecovery"] = {
        "schema": 1, "nonce": str(uuid.uuid4()), "appLaunches": 1,
        "terminalPayload": "synthetic fixture published by a separate recovery controller after target activation",
        "fault": "EBUSY injected only for the exact published fixture output",
    }
    expected_file.write_text(json.dumps(expected, indent=2) + "\n")
    print(json.dumps({"workDir": str(work), "candidateSha256": expected["candidate"]["sha256"],
                      "nonce": expected["commandRecovery"]["nonce"]}))


if __name__ == "__main__":
    main()
