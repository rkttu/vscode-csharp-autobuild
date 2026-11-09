"""Prepare a local-only installed-editor lifecycle candidate and fresh profile."""
import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts/variant"))
from overlay import FILE_APP_MODULES

EXTENSION_ID = "dotnetdev-kr-custom.csharp-with-netcoredbg"
DISPLAY_NAME = "C# (netcoredbg) LOCAL WEB LIFECYCLE TEST"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_candidate(base, modules, target, source_commit, output, expected_sha):
    """Replace only owned modules and local-only metadata; verify all other bytes."""
    if digest(base.read_bytes()) != expected_sha.lower():
        raise ValueError("Base VSIX SHA-256 differs from the pinned input")
    with zipfile.ZipFile(base) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries")
        # ZipInfo.filename normalizes backslashes on Windows; validate the
        # original central-directory spelling before trusting normalized names.
        for info in archive.infolist():
            name = info.orig_filename
            parts = PurePosixPath(name)
            if parts.is_absolute() or ".." in parts.parts or "\\" in name or ":" in name:
                raise ValueError("Unsafe ZIP entry")
        package = json.loads(archive.read("extension/package.json"))
        if package.get("netcoredbgBuild", {}).get("target") != target:
            raise ValueError("Base VSIX target differs from the selected native target")
        if f"{package.get('publisher')}.{package.get('name')}" != EXTENSION_ID:
            raise ValueError("Unexpected extension ID")
        if package.get("main") != "./.netcoredbg/entry.cjs":
            raise ValueError("Base VSIX must already contain the owned entry wrapper")
        owned = {name: (modules / name).read_bytes() for name in FILE_APP_MODULES}
        identity = {"baseVsixSha256": expected_sha.lower(), "sourceCommit": source_commit,
                    "target": target, "ownedModules": {name: digest(data) for name, data in owned.items()}}
        build_id = digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
        package["displayName"] = DISPLAY_NAME
        package["netcoredbgBuild"].update(localCandidate=True, lifecycleBuildId=build_id,
                                           lifecycleSourceCommit=source_commit)
        replacements = {f"extension/.netcoredbg/{name}": data for name, data in owned.items()}
        replacements["extension/package.json"] = (json.dumps(package, indent=2) + "\n").encode()
        manifest = ET.fromstring(archive.read("extension.vsixmanifest"))
        for element in manifest.iter():
            if element.tag.rsplit("}", 1)[-1] == "DisplayName":
                element.text = DISPLAY_NAME
        replacements["extension.vsixmanifest"] = ET.tostring(manifest, encoding="utf-8", xml_declaration=True)
        allowed = set(replacements)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as candidate:
            for info in archive.infolist():
                candidate.writestr(copy.copy(info), replacements.pop(info.filename, archive.read(info.filename)))
            for name, data in replacements.items():
                candidate.writestr(name, data)
        with zipfile.ZipFile(output) as candidate:
            if set(candidate.namelist()) != set(names) | allowed:
                raise ValueError("Candidate contains unexpected entries")
            immutable = {}
            for name in names:
                if name not in allowed:
                    original = archive.read(name)
                    if candidate.read(name) != original:
                        raise ValueError("Non-owned payload changed: " + name)
                    immutable[name] = digest(original)
        return {**identity, "buildId": build_id, "sha256": digest(output.read_bytes()),
                "path": str(output), "version": package["version"], "localOnly": True,
                "published": False, "unchangedEntries": len(immutable),
                "unchangedPayloadDigest": digest(json.dumps(immutable, sort_keys=True).encode())}


def fresh_directory(directory):
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Work directory must be fresh; retain earlier failures in their original directory")
    directory.mkdir(parents=True, exist_ok=True)


def pe_machine(executable):
    with executable.open("rb") as stream:
        def read_exact(size):
            value = stream.read(size)
            if len(value) != size:
                raise ValueError("Truncated PE executable")
            return value

        if stream.read(2) != b"MZ":
            raise ValueError("Expected a Windows editor executable")
        stream.seek(0x3C)
        offset = struct.unpack("<I", read_exact(4))[0]
        stream.seek(offset)
        if read_exact(4) != b"PE\0\0":
            raise ValueError("Invalid PE executable")
        return struct.unpack("<H", read_exact(2))[0]


def native_f5_configuration(work, cycles):
    """Two externally injected keys; never reuse another input's attestation."""
    if cycles != 2:
        raise ValueError("The native F5 control requires exactly two cycles, not full qualification")
    nonce = str(uuid.uuid4())
    return {"nonce": nonce, "windowTitle": "FBA native F5 " + nonce,
            "inputs": [{"sequence": sequence,
                        "request": str(work / f"needs-f5-input-{sequence:02}.json"),
                        "receipt": str(work / f"f5-input-action-{sequence:02}.json")}
                       for sequence in (1, 2)],
            "closed": str(work / "f5-input-closed.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-vsix", type=Path, required=True)
    parser.add_argument("--base-sha256", required=True)
    parser.add_argument("--runtime-vsix", type=Path, required=True)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--editor", type=Path, required=True)
    parser.add_argument("--editor-cli", type=Path, required=True)
    parser.add_argument("--dotnet", type=Path, required=True)
    parser.add_argument("--sdk-version", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--scenario", choices=("web-lifecycle", "build-failure-retry", "native-build-cancel", "web-profile-failure-retry", "sdk-selection-failure-retry", "debug-handoff-declined-retry", "native-host-failure-retry", "native-adapter-loss", "concurrent-files", "native-handoff-cancel", "native-f5"), default="web-lifecycle")
    args = parser.parse_args()
    if not 2 <= args.cycles <= 10:
        parser.error("Use 2..10 cycles to exercise bounded same-file retry")
    if args.scenario == "native-f5" and args.cycles != 2:
        parser.error("The native F5 control requires --cycles 2")
    editor = args.editor.resolve(strict=True)
    editor_cli = args.editor_cli.resolve(strict=True)
    dotnet = args.dotnet.resolve(strict=True)
    runtime = args.runtime_vsix.resolve(strict=True)
    if pe_machine(editor) != 0xAA64:
        parser.error("This initial runner requires native Windows ARM64 VSCodium")
    if digest(runtime.read_bytes()) != args.runtime_sha256.lower():
        parser.error("Runtime dependency SHA-256 differs from pinned input")
    with zipfile.ZipFile(runtime) as archive:
        dependency = json.loads(archive.read("extension/package.json"))
    if (dependency.get("publisher"), dependency.get("name"), dependency.get("version")) != ("ms-dotnettools", "vscode-dotnet-runtime", "3.2.0"):
        parser.error("Expected the pinned .NET runtime extension 3.2.0")
    app = editor.parent / "resources/app"
    product = json.loads((app / "product.json").read_text(encoding="utf-8"))
    editor_package = json.loads((app / "package.json").read_text(encoding="utf-8"))
    if product.get("applicationName") != "codium":
        parser.error("Use VSCodium for this baseline control")
    work = args.work_dir.resolve()
    fresh_directory(work)
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    candidate = build_candidate(args.base_vsix.resolve(strict=True), REPO / "scripts/variant/file-based-apps",
                                "win32-arm64", source_commit, work / "local-lifecycle.vsix", args.base_sha256)
    for directory in ("profile/User", "extensions", "workspace", "driver", "appdata/NuGet", "localappdata",
                      "dotnet-home", "nuget-packages", "nuget-cache", "tmp", "logs"):
        (work / directory).mkdir(parents=True, exist_ok=True)
    for name in ("driver.cjs", "extension-test.cjs"):
        (work / "driver" / name).write_bytes((Path(__file__).parent / name).read_bytes())
    if args.scenario == "native-adapter-loss":
        (work / "driver/adapter-loss.ps1").write_bytes((Path(__file__).parent / "adapter-loss.ps1").read_bytes())
    (work / "driver/package.json").write_text(json.dumps({"publisher": "local-lifecycle-test", "name": "web-lifecycle-driver",
        "version": "0.0.1", "main": "./driver.cjs", "engines": {"vscode": "^1.106.0"}, "activationEvents": ["*"]}))
    fixture = (Path(__file__).parent / "fixtures/web.cs").read_bytes()
    for name in ("a.cs", "b.cs"):
        (work / "workspace" / name).write_bytes(fixture)
    native_cancellation = None
    concurrent = None
    if args.scenario == "concurrent-files":
        target = work / "workspace/concurrent-build.targets"
        target.write_bytes((Path(__file__).parent / "fixtures/concurrent-build.targets").read_bytes())
        concurrent = {"target": str(target), "entries": []}
        for name in ("a", "b"):
            source = work / "workspace" / (name + ".cs")
            entry = {"label": name.upper(), "source": str(source), "nonce": str(uuid.uuid4()),
                     "revision": "parallel-" + name,
                     "marker": str(work / "progress" / ("concurrent-" + name + "-ready.json")),
                     "release": str(work / "progress" / ("concurrent-" + name + "-release"))}
            concurrent["entries"].append(entry)
            directives = "\n".join((
                "#:property LifecycleConcurrentEnabled=true",
                "#:property CustomAfterMicrosoftCommonTargets=" + target.as_posix(),
                "#:property LifecycleConcurrentSource=" + source.as_posix(),
                "#:property LifecycleConcurrentMarker=" + Path(entry["marker"]).as_posix(),
                "#:property LifecycleConcurrentRelease=" + Path(entry["release"]).as_posix(),
                "#:property LifecycleConcurrentNonce=" + entry["nonce"],
            )) + "\n"
            source.write_bytes(directives.encode() + fixture.replace(b'\r\n', b'\n').replace(b'const string revision = "initial";',
                ('const string revision = "' + entry["revision"] + '";').encode()))
    if args.scenario == "native-build-cancel":
        nonce = str(uuid.uuid4())
        target = work / "workspace/cancel-build.targets"
        target.write_bytes((Path(__file__).parent / "fixtures/cancel-build.targets").read_bytes())
        native_cancellation = {"target": str(target), "marker": str(work / "progress/sdk-build-ready.json"),
                               "release": str(work / "progress/release-sdk-build"), "nonce": nonce,
                               "windowTitle": "FBA cancellation " + nonce}
        directives = "\n".join((
            "#:property LifecycleCancelEnabled=false",
            "#:property CustomAfterMicrosoftCommonTargets=" + target.as_posix(),
            "#:property LifecycleCancelMarker=" + Path(native_cancellation["marker"]).as_posix(),
            "#:property LifecycleCancelRelease=" + Path(native_cancellation["release"]).as_posix(),
            "#:property LifecycleCancelNonce=" + nonce,
        )) + "\n"
        (work / "workspace/a.cs").write_bytes(directives.encode() + fixture)
    (work / "workspace/global.json").write_text(json.dumps({"sdk": {"version": args.sdk_version, "rollForward": "disable"}}))
    nuget = '<configuration><packageSources><clear /></packageSources></configuration>\n'
    for name in ("workspace/NuGet.Config", "appdata/NuGet/NuGet.Config"):
        (work / name).write_text(nuget)
    settings = {"extensions.autoUpdate": False, "extensions.autoCheckUpdates": False, "update.mode": "none",
                "telemetry.telemetryLevel": "off", "extensions.ignoreRecommendations": True,
                "dotnetAcquisitionExtension.existingDotnetPath": [{"extensionId": EXTENSION_ID, "path": str(dotnet)}]}
    if native_cancellation:
        settings["window.title"] = native_cancellation["windowTitle"]
    handoff_cancellation = None
    if args.scenario == "native-handoff-cancel":
        nonce = str(uuid.uuid4())
        handoff_cancellation = {"nonce": nonce, "windowTitle": "FBA handoff cancellation " + nonce,
                                "request": str(work / "needs-ui-cancel.json"),
                                "receipt": str(work / "ui-cancel-action.json")}
        settings["window.title"] = handoff_cancellation["windowTitle"]
    native_f5 = native_f5_configuration(work, args.cycles) if args.scenario == "native-f5" else None
    if native_f5:
        settings["window.title"] = native_f5["windowTitle"]
        settings["files.autoSave"] = "off"
    (work / "profile/User/settings.json").write_text(json.dumps(settings, indent=2))
    harness = {name: digest((Path(__file__).parent / name).read_bytes())
               for name in ("prepare.py", "run.ps1", "driver.cjs", "extension-test.cjs", "fixtures/web.cs")}
    if native_cancellation:
        harness["fixtures/cancel-build.targets"] = digest(target.read_bytes())
        harness["prepared/a.cs"] = digest((work / "workspace/a.cs").read_bytes())
    if concurrent:
        harness["fixtures/concurrent-build.targets"] = digest(target.read_bytes())
        for name in ("a.cs", "b.cs"):
            harness["prepared/" + name] = digest((work / "workspace" / name).read_bytes())
    if args.scenario == "native-adapter-loss":
        harness["adapter-loss.ps1"] = digest((Path(__file__).parent / "adapter-loss.ps1").read_bytes())
    expected = {"schema": 1, "extensionId": EXTENSION_ID, "candidate": candidate, "cycles": args.cycles,
                "scenario": args.scenario,
                "harness": harness,
                "editor": {"executable": str(editor), "cli": str(editor_cli), "version": editor_package["version"],
                           "commit": product["commit"], "sha256": digest(editor.read_bytes()), "machine": "arm64"},
                "sdk": {"executable": str(dotnet), "root": str(dotnet.parent), "version": args.sdk_version,
                        "sha256": digest(dotnet.read_bytes())},
                "dependency": {"path": str(runtime), "sha256": args.runtime_sha256.lower(), "version": "3.2.0"},
                "scope": {"localOnly": True, "published": False, "qualification": False, "physicalF5": False,
                          "macOS": False, "invocation": "command-api", "freshProfiles": 1}}
    if native_cancellation:
        expected["nativeCancellation"] = native_cancellation
    if handoff_cancellation:
        expected["handoffCancellation"] = handoff_cancellation
    if native_f5:
        expected["nativeF5"] = native_f5
        # Avoid the older ambiguous physicalF5 label: this is native injected
        # input in a visible window, not an assertion about human hardware.
        del expected["scope"]["physicalF5"]
        expected["scope"].update(invocation="native-injected-f5", nativeInjectedF5=True,
                                 hardwareKeypress=False, noFolderWindow=True)
    if concurrent:
        expected["concurrent"] = concurrent
    if args.scenario == "native-adapter-loss":
        with zipfile.ZipFile(candidate["path"]) as archive:
            native_adapter_sha256 = digest(archive.read("extension/.debugger/netcoredbg/netcoredbg.exe"))
        expected["adapterLoss"] = {"nonce": str(uuid.uuid4()),
                                   "marker": str(work / "progress/needs-adapter-loss.json"),
                                   "receipt": str(work / "progress/adapter-loss-receipt.json"),
                                   "helper": str(work / "driver/adapter-loss.ps1"),
                                   "adapterRelativePath": ".debugger/netcoredbg/netcoredbg.exe",
                                   "adapterSha256": native_adapter_sha256}
    if args.scenario == "sdk-selection-failure-retry":
        expected["sdkSelection"] = {"unavailableVersion": "99.0.100",
                                    "globalJson": str(work / "workspace/global.json"),
                                    "originalGlobalJsonSha256": digest((work / "workspace/global.json").read_bytes()),
                                    "inventory": str(work / "logs/sdk-inventory.txt")}
    (work / "expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    print(json.dumps({"workDir": str(work), "candidateSha256": candidate["sha256"], "buildId": candidate["buildId"]}))


if __name__ == "__main__":
    main()
