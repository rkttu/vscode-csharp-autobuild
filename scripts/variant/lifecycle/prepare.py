"""Prepare a local-only installed-editor lifecycle candidate and fresh profile."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import uuid
import zipfile

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts/variant"))
from lifecycle.candidate import (DISPLAY_NAME, EXTENSION_ID, FILE_APP_MODULES, build_candidate,
                                 copy_candidate_manifest, digest, load_candidate_manifest)


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


def native_f5_configuration(work, cycles, input_mode="native-injected"):
    """Freeze one native input mechanism and separate attestations per input."""
    if type(cycles) is not int or not 2 <= cycles <= 10:
        raise ValueError("The native F5 control requires 2..10 integer cycles")
    if input_mode not in ("native-injected", "manual-native"):
        raise ValueError("Unknown native F5 input mode")
    nonce = str(uuid.uuid4())
    return {"nonce": nonce, "windowTitle": "FBA native F5 " + nonce, "inputMode": input_mode,
            "inputs": [{"sequence": sequence,
                        "request": str(work / f"needs-f5-input-{sequence:02}.json"),
                        "receipt": str(work / f"f5-input-action-{sequence:02}.json")}
                       for sequence in range(1, cycles + 1)],
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
    parser.add_argument("--candidate-manifest", type=Path,
                        help="Reuse a pinned series candidate for a fresh native-f5 profile")
    parser.add_argument("--candidate-manifest-sha256")
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--native-f5-input", choices=("native-injected", "manual-native"),
                        help="Freeze the input mechanism for a new native-f5 profile (default: native-injected)")
    parser.add_argument("--scenario", choices=("web-lifecycle", "build-failure-retry", "native-build-cancel", "web-profile-failure-retry", "sdk-selection-failure-retry", "debug-handoff-declined-retry", "native-host-failure-retry", "native-adapter-loss", "concurrent-files", "native-handoff-cancel", "native-f5"), default="web-lifecycle")
    args = parser.parse_args()
    if not 2 <= args.cycles <= 10:
        parser.error("Use 2..10 cycles to exercise bounded same-file retry")
    if args.native_f5_input is not None and args.scenario != "native-f5":
        parser.error("--native-f5-input is only valid with --scenario native-f5")
    if (args.candidate_manifest is None) != (args.candidate_manifest_sha256 is None):
        parser.error("--candidate-manifest and --candidate-manifest-sha256 are required together")
    if args.candidate_manifest is not None and args.scenario != "native-f5":
        parser.error("--candidate-manifest is only valid with --scenario native-f5")
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
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    base = args.base_vsix.resolve(strict=True)
    modules = REPO / "scripts/variant/file-based-apps"
    validated = (load_candidate_manifest(args.candidate_manifest, args.candidate_manifest_sha256,
                                        base, modules, "win32-arm64", source_commit, args.base_sha256)
                 if args.candidate_manifest is not None else None)
    fresh_directory(work)
    candidate_reuse = None
    if validated is not None:
        candidate, candidate_reuse = copy_candidate_manifest(validated, work / "local-lifecycle.vsix")
    else:
        candidate = build_candidate(base, modules, "win32-arm64", source_commit,
                                    work / "local-lifecycle.vsix", args.base_sha256)
    for directory in ("profile/User", "extensions", "workspace", "driver", "appdata/NuGet", "localappdata",
                      "dotnet-home", "nuget-packages", "nuget-cache", "tmp", "logs"):
        (work / directory).mkdir(parents=True, exist_ok=True)
    for name in ("driver.cjs", "extension-test.cjs"):
        (work / "driver" / name).write_bytes((Path(__file__).parent / name).read_bytes())
    if args.scenario == "native-f5":
        (work / "driver/native-f5-input.cjs").write_bytes((Path(__file__).parent / "native-f5-input.cjs").read_bytes())
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
    native_f5 = native_f5_configuration(work, args.cycles, args.native_f5_input or "native-injected") if args.scenario == "native-f5" else None
    if native_f5:
        settings["window.title"] = native_f5["windowTitle"]
        settings["files.autoSave"] = "off"
    (work / "profile/User/settings.json").write_text(json.dumps(settings, indent=2))
    harness = {name: digest((Path(__file__).parent / name).read_bytes())
               for name in ("prepare.py", "candidate.py", "run.ps1", "driver.cjs", "extension-test.cjs", "fixtures/web.cs")}
    if native_f5:
        harness["native-f5-input.cjs"] = digest((Path(__file__).parent / "native-f5-input.cjs").read_bytes())
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
    if candidate_reuse is not None:
        expected["candidateReuse"] = candidate_reuse
    if native_cancellation:
        expected["nativeCancellation"] = native_cancellation
    if handoff_cancellation:
        expected["handoffCancellation"] = handoff_cancellation
    if native_f5:
        expected["nativeF5"] = native_f5
        del expected["scope"]["physicalF5"]
        manual = native_f5["inputMode"] == "manual-native"
        expected["scope"].update(invocation="manual-native-f5" if manual else "native-injected-f5",
                                 nativeInjectedF5=not manual, noFolderWindow=True,
                                 humanKeypressAttestationRequired=manual, hardwareInputIndependentlyVerified=False)
        if not manual:
            expected["scope"]["hardwareKeypress"] = False
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
