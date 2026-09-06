"""Verify a VSIX identity, native payload and validation provenance; optionally run DAP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

import versioning

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts/validation"))
from audit import native_architecture


def verify(vsix, validated, target, version, root, run_dap):
    config = json.loads((REPO / "config/variant.json").read_text())
    validation = json.loads((validated / "validation-manifest.json").read_text())
    assert validation["success"] is True
    record = next(row for row in validation["targets"] if row["target"] == target)
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    result = dict(success=False, target=target, version=version, vsix=vsix.name,
                  sha256=hashlib.sha256(vsix.read_bytes()).hexdigest(), runtimeTests=[])
    try:
        with zipfile.ZipFile(vsix) as zip_in:
            names = zip_in.namelist()
            assert len(names) == len(set(names)), "Duplicate archive entries"
            assert all(not Path(name).is_absolute() and ".." not in Path(name).parts and "\\" not in name for name in names)
            pkg = json.loads(zip_in.read("extension/package.json"))
            for key in ("publisher", "name", "displayName"):
                assert pkg[key] == config[key], f"Wrong extension {key}"
            assert pkg["version"] == version
            build = pkg["netcoredbgBuild"]
            versioning.validate(dict(version=pkg["version"], csharpTag=build["upstreamCsharpTag"],
                                     csharpSha=build["upstreamCsharpCommit"], csharpVersion=build["upstreamCsharpVersion"],
                                     debuggerTag=build["netcoredbgTag"], debuggerSha=build["netcoredbgCommit"],
                                     revision=build["packagingRevision"], releaseTag=build["releaseTag"],
                                     versionPolicy=build["versionPolicy"]))
            identity = next(e for e in ET.fromstring(zip_in.read("extension.vsixmanifest")).iter()
                            if e.tag.endswith("}Identity") or e.tag == "Identity")
            assert identity.attrib["TargetPlatform"] == target
            assert identity.attrib["Version"] == version
            assert identity.attrib["Publisher"] == config["publisher"]
            assert pkg["netcoredbgBuild"]["target"] == target
            assert pkg["netcoredbgBuild"]["netcoredbgCommit"] == validation["netcoredbgCommit"]
            assert pkg["netcoredbgBuild"]["debuggerArchiveSha256"] == record["sha256"]
            assert pkg["netcoredbgBuild"]["validationRunId"] == validation["runId"]
            assert not any(dep.get("id") == "Debugger" for dep in pkg["runtimeDependencies"])
            assert not any("vsdbg" in Path(name).name.lower() for name in names), "Proprietary debugger payload found"
            debugger = pkg["contributes"]["debuggers"]
            assert len(debugger) == 1 and debugger[0]["type"] == "coreclr"
            assert debugger[0]["program"] == "./.debugger/netcoredbg/netcoredbg"
            assert debugger[0]["windows"]["program"] == "./.debugger/netcoredbg/netcoredbg.exe"
            assert debugger[0]["args"] == ["--interpreter=vscode"]
            icon = zip_in.read("extension/" + pkg["icon"])
            assert icon == (REPO / "assets/netcoredbg/icon.png").read_bytes()
            prefix = "extension/.debugger/netcoredbg/"
            actual = {name[len(prefix):]: hashlib.sha256(zip_in.read(name)).hexdigest()
                      for name in names if name.startswith(prefix) and not name.endswith("/")}
            assert actual == record["files"], "Bundled payload differs from the validated package"
            exe_name = "netcoredbg.exe" if target.startswith("win32") else "netcoredbg"
            if not target.startswith("win32"):
                assert (zip_in.getinfo(prefix + exe_name).external_attr >> 16) & 0o111, "Executable permission missing"
            zip_in.extractall(root / "unpacked")
        adapter = root / "unpacked/extension/.debugger/netcoredbg" / exe_name
        assert native_architecture(adapter) == target.split("-")[1]
        if run_dap:
            host_arch = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
            assert host_arch == target.split("-")[1], "Native OS architecture differs from the VSIX target"
            assert (os.name == "nt") == target.startswith("win32")
            assert (sys.platform == "darwin") == target.startswith("darwin")
            assert Path("/etc/alpine-release").exists() == target.startswith("alpine")
            adapter.chmod(0o755)
            settings = json.loads((REPO / "config/netcoredbg.json").read_text())
            env = os.environ.copy()
            dotnet_root = str(Path(env["DOTNET_INSTALL_DIR"]).resolve())
            env.update(DOTNET_ROOT=dotnet_root, PATH=dotnet_root + os.pathsep + env["PATH"],
                       DOTNET_CLI_HOME=str(root / "dotnet-home"), DOTNET_GENERATE_ASPNET_CERTIFICATE="false",
                       UseSharedCompilation="false", MSBUILDDISABLENODEREUSE="1", DOTNET_CLI_USE_MSBUILD_SERVER="0")
            env["DOTNET_ROOT_" + target.split("-")[1].upper()] = dotnet_root
            dotnet = Path(dotnet_root) / ("dotnet.exe" if os.name == "nt" else "dotnet")
            assert native_architecture(dotnet) == target.split("-")[1]
            for runtime in settings["runtimes"]:
                fixture = root / ("fixture-net" + runtime)
                shutil.copytree(REPO / "scripts/validation/fixture", fixture)
                (fixture / "global.json").write_text(json.dumps({"sdk": {"version": settings["sdk" + runtime], "rollForward": "disable"}}))
                with (evidence / f"fixture-net{runtime}-build.log").open("w") as log:
                    subprocess.run([str(dotnet), "build", "Probe.csproj", "-c", "Debug", "-o", "output",
                                    f"-p:ValidationTargetFramework=net{runtime}.0"], cwd=fixture, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
                subprocess.run([sys.executable, str(REPO / "scripts/validation/dap_probe.py"), "--engine", "netcoredbg",
                                "--debugger", str(adapter), "--program", str(fixture / "output/Probe.dll"),
                                "--source", str(fixture / "Program.cs"), "--expected-arch", target.split("-")[1],
                                "--expected-runtime", runtime, "--log", str(evidence / f"dap-net{runtime}.jsonl"),
                                "--result", str(evidence / f"dap-net{runtime}-result.json")], env=env, check=True)
                result["runtimeTests"].append(runtime)
        result["success"] = True
        result["netcoredbgBuild"] = pkg["netcoredbgBuild"]
    except Exception as error:
        result["error"] = str(error) or type(error).__name__
    result["scope"] = "VSIX identity, permissions, exact bundled hashes" + (" and extracted-adapter DAP launch; no IDE UI test" if run_dap else "")
    (evidence / "vsix-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("vsix", "validated", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("target", "version"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--run-dap", action="store_true")
    args = parser.parse_args()
    outcome = verify(args.vsix.resolve(), args.validated.resolve(), args.target, args.version, args.output.resolve(), args.run_dap)
    sys.exit(0 if outcome["success"] else 1)
