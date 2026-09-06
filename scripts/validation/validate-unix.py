"""Build original Samsung inputs and run the DAP fixture on native Unix hosts."""

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from audit import native_architecture, sha256, snapshot


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    family, arch = args.target.split("-")
    assert family in ("linux", "alpine", "darwin") and arch in ("x64", "arm64")
    repo = Path(__file__).resolve().parents[2]
    source, runtime = [repo / "validation-inputs" / p for p in ("netcoredbg", "runtime")]
    root = Path(os.environ["VALIDATION_ROOT"]).resolve()
    evidence, build, package = [root / p for p in ("evidence", "build", "package/netcoredbg")]
    for directory in (evidence, build, package):
        directory.mkdir(parents=True, exist_ok=True)
    dotnet_root = Path(os.environ["DOTNET_INSTALL_DIR"]).resolve()
    dotnet = str(dotnet_root / "dotnet")
    status = dict(success=False, stage="environment", target=args.target, architecture=arch,
                  netcoredbgTag=os.environ["NETCOREDBG_TAG"], netcoredbgCommit=os.environ["NETCOREDBG_SHA"],
                  coreclrCommit=os.environ["CORECLR_SHA"], sdk8=os.environ["SDK8_VERSION"],
                  sdk10=os.environ["SDK10_VERSION"], dbgshimVersion=os.environ["DBGSHIM_VERSION"],
                  workflowCommit=os.environ.get("GITHUB_SHA"), runId=os.environ.get("GITHUB_RUN_ID"),
                  runnerImage=os.environ.get("ImageOS"), runnerImageVersion=os.environ.get("ImageVersion"),
                  host=platform.platform(), sourceUnchanged=False, runtimeTests=[], error=None,
                  scope="Standalone source build and DAP launch; VSIX integration is a separate gate.")
    env = os.environ.copy()
    env.update(DOTNET_ROOT=str(dotnet_root), PATH=str(dotnet_root) + os.pathsep + env["PATH"],
               DOTNET_CLI_HOME=str(root / "dotnet-home"), NUGET_PACKAGES=str(root / "nuget-packages"),
               NUGET_HTTP_CACHE_PATH=str(root / "nuget-cache"), DOTNET_CLI_USE_MSBUILD_SERVER="0",
               MSBUILDDISABLENODEREUSE="1", DOTNET_GENERATE_ASPNET_CERTIFICATE="false",
               DirectoryBuildTargetsPath=str(repo / "scripts/validation/ManagedDependencies.targets"),
               CC="clang", CXX="clang++")
    env["DOTNET_ROOT_" + arch.upper()] = str(dotnet_root)

    def run(command, log, cwd=root):
        with (evidence / log).open("w", encoding="utf-8") as out:
            result = subprocess.run([str(x) for x in command], cwd=cwd, env=env,
                                    stdout=out, stderr=subprocess.STDOUT)
        print(f"{log}: exit {result.returncode}", flush=True)
        if result.returncode:
            print((evidence / log).read_text(errors="replace")[-16000:], flush=True)
            raise RuntimeError(f"{log}: exit {result.returncode}")

    before = {}
    try:
        observed_arch = {"x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine())
        assert observed_arch == arch, f"Expected native {arch}, found {platform.machine()}"
        assert (platform.system() == "Darwin") == (family == "darwin")
        assert Path("/etc/alpine-release").exists() == (family == "alpine")
        for directory, expected in ((source, status["netcoredbgCommit"]), (runtime, status["coreclrCommit"])):
            assert subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], text=True).strip() == expected
        before = snapshot(source)
        assert before
        write(evidence / "source-before.json", before)
        assert native_architecture(Path(dotnet)) == arch
        write(root / "global.json", {"sdk": {"version": status["sdk10"], "rollForward": "disable"}})
        for command, log in (([dotnet, "--info"], "dotnet-info.log"), ([dotnet, "--list-runtimes"], "dotnet-runtimes.log"),
                             (["cmake", "--version"], "cmake-version.log"), (["clang", "--version"], "compiler-version.log")):
            run(command, log)
        status["stage"] = "configure"
        rid = {"linux": "linux", "alpine": "linux-musl", "darwin": "osx"}[family]
        command = ["cmake", "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
                   f"-DCMAKE_INSTALL_PREFIX={package}", f"-DCORECLR_DIR={runtime}/src/coreclr", f"-DDOTNET_DIR={dotnet_root}",
                   "-DBUILD_MANAGED=OFF", "-DINTEROP_DEBUGGING=OFF", "-DBUILD_TESTING=OFF",
                   f"-DCLR_CMAKE_HOST_ARCH={arch}", f"-DCLR_CMAKE_TARGET_ARCH={arch}", f"-DRID_NAME={rid}"]
        if family == "alpine":
            command.append("-DCLR_CMAKE_LINUX_ID=alpine")
            command.append(f"-DCMAKE_CXX_FLAGS=-include {repo}/scripts/validation/musl-null-compat.h")
            status["externalCompatibilityHeader"] = "scripts/validation/musl-null-compat.h"
        if family == "darwin":
            command += [f"-DCMAKE_OSX_ARCHITECTURES={'x86_64' if arch == 'x64' else 'arm64'}", "-DCMAKE_OSX_DEPLOYMENT_TARGET=12.0"]
        run(command, "configure.log")
        status["stage"] = "native-build"
        run(["cmake", "--build", build, "--target", "netcoredbg", "--parallel", "4"], "build.log")
        run(["cmake", "--install", build], "install.log")
        status["stage"] = "managed-build"
        managed = root / "managed"
        run([dotnet, "publish", source / "src/managed/ManagedPart.csproj", "-r", f"{rid}-{arch}", "--self-contained",
             "-c", "Release", "-o", managed / "publish", f"-p:BaseIntermediateOutputPath={managed}/obj/",
             f"-p:BaseOutputPath={managed}/bin/", "-p:UseDbgShimDependency=true"], "managed-build.log")
        shim = "libdbgshim.dylib" if family == "darwin" else "libdbgshim.so"
        for name in [shim, "ManagedPart.dll", "Microsoft.CodeAnalysis.dll", "Microsoft.CodeAnalysis.CSharp.dll",
                     "Microsoft.CodeAnalysis.Scripting.dll", "Microsoft.CodeAnalysis.CSharp.Scripting.dll"]:
            shutil.copy2(managed / "publish" / name, package / name)
        libraries = json.loads((managed / "obj/project.assets.json").read_text())["libraries"]
        assert "Microsoft.Diagnostics.DbgShim/" + status["dbgshimVersion"] in libraries
        write(evidence / "resolved-libraries.json", libraries)
        notices = package / "notices"
        notices.mkdir()
        for file, name in [(source / "LICENSE", "Samsung-netcoredbg-LICENSE"),
                           (source / "third_party/linenoise-ng/LICENSE", "linenoise-ng-LICENSE"),
                           (source / "third_party/json/LICENSE.MIT", "json-LICENSE.MIT"),
                           (runtime / "LICENSE.TXT", "dotnet-runtime-LICENSE.TXT"),
                           (runtime / "THIRD-PARTY-NOTICES.TXT", "dotnet-runtime-THIRD-PARTY-NOTICES.TXT")]:
            shutil.copy2(file, notices / name)
        for file in Path(env["NUGET_PACKAGES"]).rglob("*"):
            if file.is_file() and file.name.upper().startswith(("LICENSE", "COPYING", "THIRD-PARTY-NOTICES")):
                dest = notices / "nuget" / file.relative_to(env["NUGET_PACKAGES"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, dest)
        relocated = root / "relocated/netcoredbg"
        shutil.copytree(package, relocated)
        debugger = relocated / "netcoredbg"
        files = [dict(file=p.name, architecture=native_architecture(p), sha256=sha256(p)) for p in [debugger, relocated / shim]]
        assert all(p["architecture"] == arch for p in files)
        write(evidence / "debugger-architectures.json", dict(success=True, expectedArchitecture=arch, files=files))
        run([debugger, "--version"], "debugger-version.log")
        status["stage"] = "runtime-tests"
        for version in ("8", "10"):
            test = dict(runtime=version, sdk=status["sdk" + version], success=False, error=None)
            status["runtimeTests"].append(test)
            try:
                fixture = root / ("fixture-net" + version)
                shutil.copytree(repo / "scripts/validation/fixture", fixture)
                write(fixture / "global.json", {"sdk": {"version": test["sdk"], "rollForward": "disable"}})
                observed = subprocess.check_output([dotnet, "--version"], cwd=fixture, env=env, text=True).strip()
                assert observed == test["sdk"], f"Expected SDK {test['sdk']}; got {observed}"
                run([dotnet, "build", "Probe.csproj", "-c", "Debug", "-o", "output", f"-p:ValidationTargetFramework=net{version}.0"],
                    f"fixture-net{version}-build.log", fixture)
                run([dotnet, fixture / "output/Probe.dll"], f"fixture-net{version}-direct.log", fixture)
                run([sys.executable, repo / "scripts/validation/dap_probe.py", "--engine", "netcoredbg", "--debugger", debugger,
                     "--program", fixture / "output/Probe.dll", "--source", fixture / "Program.cs", "--expected-arch", arch,
                     "--expected-runtime", version, "--log", evidence / f"dap-net{version}.jsonl",
                     "--result", evidence / f"dap-net{version}-result.json"], f"dap-net{version}-console.log", fixture)
                test["success"] = True
            except Exception as error:
                test["error"] = str(error)
        assert all(test["success"] for test in status["runtimeTests"]), "Runtime validation failed"
        status.update(success=True, stage="complete")
    except Exception as error:
        status["error"] = str(error)
        print(f"FAILED at {status['stage']}: {error}", flush=True)
    finally:
        changed = [name for name, digest in before.items() if not (source / name).is_file() or sha256(source / name) != digest]
        status["sourceUnchanged"] = bool(before) and not changed
        status["success"] = status["success"] and status["sourceUnchanged"]
        write(evidence / "source-integrity.json", dict(success=status["sourceUnchanged"], originalFileCount=len(before), changedOrMissing=changed))
        write(evidence / "package-sha256.json", [dict(file=p.relative_to(package).as_posix(), sha256=sha256(p))
                                                for p in sorted(package.rglob("*")) if p.is_file()])
        if (build / "CMakeCache.txt").exists():
            shutil.copy2(build / "CMakeCache.txt", evidence / "CMakeCache.txt")
        write(evidence / "result.json", status)
    return 0 if status["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
