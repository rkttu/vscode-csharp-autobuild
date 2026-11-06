"""Prepare a fresh native VSCodium profile for the direct-runtime disposal control."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]


def sha256(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    args, forwarded = parser.parse_known_args()
    work = args.work_dir.resolve()
    preparer = REPO / "scripts/variant/lifecycle/prepare.py"
    subprocess.run([sys.executable, str(preparer), "--work-dir", str(work), *forwarded], check=True)
    control = Path(__file__).with_name("control.cjs")
    driver = Path(__file__).with_name("driver.cjs")
    # These edits are part of preparation, before an attempt marker or editor
    # installation. Earlier attempted profiles are refused by the shared preparer.
    if any((work / name).exists() for name in ("attempt.json", "launch.json", "launcher-result.json")):
        raise ValueError("Refuse to change an attempted profile")
    (work / "driver/extension-test.cjs").write_bytes(control.read_bytes())
    (work / "driver/driver.cjs").write_bytes(driver.read_bytes())
    expected_file = work / "expected.json"
    expected = json.loads(expected_file.read_text(encoding="utf-8"))
    expected["harness"]["extension-test.cjs"] = sha256(control)
    expected["harness"]["driver.cjs"] = sha256(driver)
    expected["scenario"] = "graceful-disposal-control"
    expected["scope"].update(invocation="direct-runtime-api-control", actualHostShutdown=False,
                             directRuntimeActivation=True, timingInjection=["document.save", "debug.startDebugging"])
    expected["controlPreparation"] = {
        "prepareSha256": sha256(Path(__file__)), "controlSha256": sha256(control), "driverSha256": sha256(driver),
        "sharedPrepareSha256": sha256(preparer),
        "description": "Installed native adapter and real SDK; runtime activated in controlled same-host contexts",
    }
    expected_file.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"workDir": str(work), "scenario": expected["scenario"],
                      "controlSha256": sha256(control)}))


if __name__ == "__main__":
    main()
