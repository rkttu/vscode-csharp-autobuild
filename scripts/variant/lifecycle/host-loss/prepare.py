"""Prepare an isolated, normally installed driver for abrupt extension-host loss."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
DRIVER_ID = "local-lifecycle-test.host-loss-driver"


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def package_driver(work):
    package = {"publisher": "local-lifecycle-test", "name": "host-loss-driver", "version": "0.0.1",
               "displayName": "LOCAL abrupt host loss control", "description": "Isolated local lifecycle control only.",
               "main": "./driver.cjs", "engines": {"vscode": "^1.106.0"},
               "activationEvents": ["onStartupFinished"], "extensionKind": ["workspace"]}
    package_file = work / "driver/package.json"
    package_file.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    manifest = '''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
 <Metadata><Identity Language="en-US" Id="host-loss-driver" Version="0.0.1" Publisher="local-lifecycle-test" />
  <DisplayName>LOCAL abrupt host loss control</DisplayName><Description xml:space="preserve">Isolated local lifecycle control only.</Description>
  <Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.106.0" /></Properties></Metadata>
 <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code" /></Installation><Dependencies />
 <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" /></Assets>
</PackageManifest>
'''
    content_types = '''<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="json" ContentType="application/json" /><Default Extension="cjs" ContentType="application/javascript" />
 <Default Extension="vsixmanifest" ContentType="text/xml" />
</Types>
'''
    payload = {"extension/" + name: (work / "driver" / name).read_bytes()
               for name in ("package.json", "driver.cjs", "extension-test.cjs")}
    payload["extension.vsixmanifest"] = manifest.encode()
    payload["[Content_Types].xml"] = content_types.encode()
    output = work / "local-host-loss-driver.vsix"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    return {"id": DRIVER_ID, "version": "0.0.1", "path": str(output), "sha256": digest(output),
            "localOnly": True, "published": False,
            "payload": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}}


def main():
    args = sys.argv[1:]
    if "--work-dir" not in args or "--scenario" in args:
        raise ValueError("Pass shared preparation inputs and --work-dir; this wrapper selects its own scenario")
    work = Path(args[args.index("--work-dir") + 1]).resolve()
    subprocess.run([sys.executable, "-X", "utf8", str(HERE.parent / "prepare.py"), *args], check=True)
    for name in ("driver.cjs", "extension-test.cjs"):
        (work / "driver" / name).write_bytes((HERE / name).read_bytes())
    driver = package_driver(work)
    expected_file = work / "expected.json"
    expected = json.loads(expected_file.read_text())
    nonce = str(uuid.uuid4())
    settings_file = work / "profile/User/settings.json"
    settings = json.loads(settings_file.read_text())
    settings["debug.confirmOnExit"] = "never"
    settings["window.title"] = "FBA host loss " + nonce
    settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    (work / "prepared-settings.json").write_bytes(settings_file.read_bytes())
    expected["scenario"] = "abrupt-extension-host-loss"
    expected["testDriver"] = driver
    with zipfile.ZipFile(expected["candidate"]["path"]) as archive:
        native_sha = hashlib.sha256(archive.read("extension/.debugger/netcoredbg/netcoredbg.exe")).hexdigest()
    expected["hostLoss"] = {"schema": 1, "nonce": nonce, "appLaunches": 1,
                            "extensionDevelopmentPath": False, "extensionTestsPath": False,
                            "phaseCheckpoint": "phase.json", "ready": "fault-ready.json", "receipt": "host-kill-receipt.json",
                            "adapterRelativePath": ".debugger/netcoredbg/netcoredbg.exe", "adapterSha256": native_sha}
    for name in ("prepare.py", "run.ps1", "driver.cjs", "extension-test.cjs"):
        expected["harness"]["host-loss/" + name] = digest(HERE / name)
    for name in ("driver.cjs", "extension-test.cjs"):
        expected["harness"][name] = digest(work / "driver" / name)
    for name in ("driver/package.json", "profile/User/settings.json", "prepared-settings.json"):
        expected["harness"][name] = digest(work / name)
    expected_file.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"workDir": str(work), "candidateSha256": expected["candidate"]["sha256"],
                      "driverSha256": driver["sha256"], "nonce": nonce}))


if __name__ == "__main__":
    main()
