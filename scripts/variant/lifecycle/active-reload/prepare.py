"""Prepare normally installed candidate and normal-activation actual Reload driver."""
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
    for name in ("extension-test.cjs", "driver.cjs"):
        (work / "driver" / name).write_bytes((HERE / name).read_bytes())
    package_file = work / "driver/package.json"
    package = json.loads(package_file.read_text())
    package["activationEvents"] = ["onStartupFinished"]
    package_file.write_text(json.dumps(package, indent=2) + "\n")
    settings_file = work / "profile/User/settings.json"
    settings = json.loads(settings_file.read_text())
    settings["debug.confirmOnExit"] = "never"
    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    # Editors may migrate settings on startup; retain the exact prepared input.
    prepared_settings = work / "prepared-settings.json"
    prepared_settings.write_bytes(settings_file.read_bytes())
    expected_file = work / "expected.json"
    expected = json.loads(expected_file.read_text())
    expected["scenario"] = "actual-workbench-reload"
    for name in ("extension-test.cjs", "driver.cjs"):
        expected["harness"][name] = digest(work / "driver" / name)
    for name in ("prepare.py", "run.ps1"):
        expected["harness"]["active-reload/" + name] = digest(HERE / name)
    expected["harness"]["driver/package.json"] = digest(package_file)
    expected["harness"]["profile/User/settings.json"] = digest(settings_file)
    expected["harness"]["prepared-settings.json"] = digest(prepared_settings)
    expected["actualReload"] = {
        "schema": 1, "nonce": str(uuid.uuid4()), "appLaunches": 1,
        "command": "workbench.action.reloadWindow", "extensionTestsPath": False,
        "debug.confirmOnExit": "never", "phaseCheckpoint": "phase.json",
    }
    expected_file.write_text(json.dumps(expected, indent=2) + "\n")
    print(json.dumps({"workDir": str(work), "candidateSha256": expected["candidate"]["sha256"],
                      "nonce": expected["actualReload"]["nonce"]}))


if __name__ == "__main__":
    main()
