"""Apply a checked, minimal C# integration overlay to a disposable upstream checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

import versioning


def replace_once(path, before, after):
    content = path.read_text()
    if content.count(before) != 1:
        raise ValueError(f"Upstream integration point changed: {path.name}: {before[:70]}")
    path.write_text(content.replace(before, after))


def apply(source, validated, target, version, repo, candidate):
    versioning.validate(candidate)
    assert candidate["version"] == version
    config = json.loads((repo / "config/variant.json").read_text())
    manifest = json.loads((validated / "validation-manifest.json").read_text())
    expected_targets = json.loads((repo / "config/netcoredbg.json").read_text())["targets"]
    assert manifest["success"] is True
    assert sorted(row["target"] for row in manifest["targets"]) == sorted(expected_targets)
    assert all(row["success"] is True for row in manifest["targets"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert target in expected_targets
    record = next(row for row in manifest["targets"] if row["target"] == target)
    archive = validated / record["archive"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == record["sha256"]
    extracted = validated / target
    with zipfile.ZipFile(archive) as zip_in:
        expected_names = {"netcoredbg/" + name for name in record["files"]}
        assert set(zip_in.namelist()) == expected_names
        assert all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in expected_names)
        zip_in.extractall(extracted)
    for name, digest in record["files"].items():
        assert hashlib.sha256((extracted / "netcoredbg" / name).read_bytes()).hexdigest() == digest
    if not target.startswith("win32"):
        (extracted / "netcoredbg/netcoredbg").chmod(0o755)

    pkg_path = source / "package.json"
    pkg = json.loads(pkg_path.read_text())
    upstream_sha = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    assert upstream_sha == candidate["csharpSha"]
    assert manifest["netcoredbgCommit"] == candidate["debuggerSha"]
    upstream_version = pkg["version"]
    pkg.update({key: config[key] for key in ("publisher", "name", "displayName")})
    pkg.update(version=version, icon="images/netcoredbgIcon.png",
               description="Community C# language support with the netcoredbg debugger.",
               repository={"type": "git", "url": "https://github.com/" + config["repository"]},
               bugs={"url": "https://github.com/" + config["repository"] + "/issues"})
    pkg["runtimeDependencies"] = [dep for dep in pkg["runtimeDependencies"] if dep.get("id") != "Debugger"]
    debugger = next(d for d in pkg["contributes"]["debuggers"] if d["type"] == "coreclr")
    debugger.update(program="./.debugger/netcoredbg/netcoredbg", args=["--interpreter=vscode"],
                    windows={"program": "./.debugger/netcoredbg/netcoredbg.exe"},
                    label="C# (netcoredbg)")
    # These debug types require other runtimes or Microsoft's adapter-specific protocols.
    pkg["contributes"]["debuggers"] = [debugger]
    pkg["netcoredbgBuild"] = dict(target=target, upstreamCsharpCommit=upstream_sha,
                                  upstreamCsharpVersion=candidate["csharpVersion"], upstreamCsharpTag=candidate["csharpTag"],
                                  upstreamPackageVersion=upstream_version, netcoredbgTag=candidate["debuggerTag"],
                                  packagingRevision=candidate["revision"], releaseTag=candidate["releaseTag"],
                                  versionPolicy=candidate["versionPolicy"],
                                  netcoredbgCommit=manifest["netcoredbgCommit"], debuggerArchiveSha256=record["sha256"],
                                  validationRunId=manifest["runId"], validationWorkflowCommit=manifest["workflowCommit"])
    pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
    shutil.copy2(repo / "assets/netcoredbg/icon.png", source / "images/netcoredbgIcon.png")
    with (source / ".vscodeignore").open("a") as ignore:
        ignore.write("\n!.debugger/netcoredbg/notices/**\n")
    for filename in ["src/constants/csharpExtensionId.ts", "src/razor/src/razorExtensionId.ts",
                     "src/lsptoolshost/logging/loggingUtils.ts"]:
        replace_once(source / filename, "'ms-dotnettools.csharp'", repr(config["publisher"] + "." + config["name"]))

    tasks = source / "tasks/packaging/offlinePackagingTasks.ts"
    replace_once(tasks, "await nbgv.setPackageVersion();", """await nbgv.setPackageVersion();
    const variantVersion = process.env.VARIANT_VERSION;
    if (!variantVersion || !/^\\d+\\.\\d+\\.\\d+$/.test(variantVersion)) {
        throw new Error('A fixed independent variant version is required.');
    }
    const variantPackage = JSON.parse(fs.readFileSync(path.join(rootPath, 'package.json'), 'utf8'));
    variantPackage.version = variantVersion;
    fs.writeFileSync(path.join(rootPath, 'package.json'), JSON.stringify(variantPackage, null, 2) + '\\n');""")
    replace_once(tasks, """export async function vsixReleasePackageTask(prerelease: boolean): Promise<void> {
    for (const entry of platformEntries) {""", """export async function vsixReleasePackageTask(prerelease: boolean): Promise<void> {
    const entries = platformEntries.filter((entry) => entry.vsixPlatform.vsceTarget === process.env.VSIX_TARGET);
    if (entries.length !== 1) {
        throw new Error('Exactly one supported variant target is required.');
    }
    for (const entry of entries) {""")
    replace_once(tasks, """async function installDebugger(packageJSON: any, platformInfo: PlatformInformation) {
    return await installPackageJsonDependency('Debugger', packageJSON, platformInfo);
}""", """async function installDebugger(_packageJSON: any, _platformInfo: PlatformInformation) {
    const debuggerInput = process.env.VALIDATED_DEBUGGER_DIRECTORY;
    if (!debuggerInput) {
        throw new Error('Validated debugger directory is required.');
    }
    await fsextra.copy(debuggerInput, path.join(codeExtensionPath, '.debugger', 'netcoredbg'));
    fs.writeFileSync(path.join(codeExtensionPath, '.debugger', 'install.complete'), '');
}""")
    factory = source / "src/coreclrDebug/activate.ts"
    for debug_type in ("clr", "monovsdbg", "monovsdbg_wasm", "coreclr_mobile"):
        replace_once(factory, f"    disposables.add(vscode.debug.registerDebugAdapterDescriptorFactory('{debug_type}', factory));\n", "")
    replace_once(factory, "import { BaseVsDbgConfigurationProvider } from '../shared/configurationProvider';\n", "")
    replace_once(factory, "    csharpOutputChannel: vscode.OutputChannel,", "    _csharpOutputChannel: vscode.OutputChannel,")
    replace_once(factory, """    /** 'clr' type does not have a intial configuration provider, but we need to register it to support the common debugger features listed in {@link BaseVsDbgConfigurationProvider} */
    context.subscriptions.push(
        vscode.debug.registerDebugConfigurationProvider(
            'clr',
            new BaseVsDbgConfigurationProvider(platformInformation, csharpOutputChannel)
        )
    );
""", "")
    content = factory.read_text()
    start = content.index("        // debugger has finished installation, kick off our debugger process")
    end = content.index("        return executable;", start) + len("        return executable;")
    content = content[:start] + """        if (_session.type !== 'coreclr' || !executable) {
            throw new Error('This build supports coreclr sessions with its bundled netcoredbg adapter.');
        }
        const dotNetInfo = await getDotnetInfo(omnisharpOptions.dotNetCliPaths);
        const requestedArchitecture = getTargetArchitecture(
            this.platformInfo,
            _session.configuration.targetArchitecture,
            dotNetInfo
        );
        const bundledArchitecture = this.packageJSON.netcoredbgBuild.target.endsWith('-arm64') ? 'arm64' : 'x86_64';
        if (requestedArchitecture && requestedArchitecture !== bundledArchitecture) {
            throw new Error('The selected .NET SDK architecture does not match this platform-specific netcoredbg package.');
        }
        const dotnetRoot = process.env.DOTNET_ROOT ?? (dotNetInfo.CliPath ? path.dirname(dotNetInfo.CliPath) : '');
        return new vscode.DebugAdapterExecutable(executable.command, executable.args, {
            ...executable.options,
            env: { ...executable.options?.env, ...(dotnetRoot ? { DOTNET_ROOT: dotnetRoot } : {}) },
        });""" + content[end:]
    factory.write_text(content)
    readme = source / "README.md"
    readme.write_text("""# C# (with netcoredbg)

This community build combines the upstream C# language extension with netcoredbg.
The publisher is dotnetdev-kr-custom. Microsoft and Samsung do not publish,
endorse, or provide support for this package.

The bundled debugger is built from [Samsung/netcoredbg](https://github.com/Samsung/netcoredbg).
Original Samsung source files remain unchanged; build inputs and compatibility
code are maintained in the [build repository](https://github.com/rkttu/vscode-csharp-autobuild).
Alpine packages include repository-owned CoreCLR hosting compatibility code.
macOS packages include a linked process-exit observer for Darwin runtime compatibility.
Component licenses accompany the package. This does not classify every component
of the upstream C# extension as MIT-licensed.

Use a native .NET SDK matching the installed extension target. The release gate
tests local coreclr launch and the required upstream DAP scenarios, including
local attach, on .NET 8 and .NET 10. Desktop .NET Framework, Unity,
mobile, WebAssembly, Hot Reload, and full C# Dev Kit debugger parity are outside
this validation scope. Enable only one C# language/debug extension in a workspace
to avoid competing coreclr registrations and language services.

Build provenance is available in package.json under netcoredbgBuild and in the
release validation manifest.

---

""" + readme.read_text())
    replace_once(readme, "Build provenance is available in package.json under netcoredbgBuild and in the\nrelease validation manifest.",
                 f"This package follows C# {candidate['csharpVersion']} ({candidate['csharpTag']}) and includes "
                 f"netcoredbg {candidate['debuggerTag']} at commit {candidate['debuggerSha']}. "
                 f"Packaging revision: {candidate['revision']}. VSIX version: {version}.\n\n"
                 "Build provenance is available in package.json under netcoredbgBuild and in the\nrelease validation manifest.")
    # Use the public registry for this community build, matching the existing autobuild.
    (source / ".npmrc").write_text("registry=https://registry.npmjs.org/\n")
    print(json.dumps(dict(version=version, target=target, debuggerDirectory=str(extracted / "netcoredbg"))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "validated", "candidate"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("target", "version"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    apply(args.source.resolve(), args.validated.resolve(), args.target, args.version, Path(__file__).resolve().parents[2],
          json.loads(args.candidate.read_text()))
