"""Diagnose a previously built Alpine artifact without rebuilding or promoting it."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

repo = Path(__file__).resolve().parents[2]
root = Path(os.environ["VALIDATION_ROOT"])
root.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
dotnet = Path(env["DOTNET_INSTALL_DIR"]) / "dotnet"
env.update(DOTNET_ROOT=str(dotnet.parent), PATH=str(dotnet.parent) + os.pathsep + env["PATH"],
           DOTNET_CLI_HOME=str(root / "dotnet-home"), DOTNET_GENERATE_ASPNET_CERTIFICATE="false",
           UseSharedCompilation="false", MSBUILDDISABLENODEREUSE="1", LOG_OUTPUT="stderr")
adapter = repo / "diagnostic-input/package/netcoredbg/netcoredbg"
adapter.chmod(0o755)
settings = json.loads((repo / "config/netcoredbg.json").read_text())
for version in settings["runtimes"]:
    fixture = root / ("fixture-net" + version)
    shutil.copytree(repo / "scripts/validation/fixture", fixture)
    (fixture / "global.json").write_text(json.dumps({"sdk": {"version": settings["sdk" + version], "rollForward": "disable"}}))
    subprocess.run([str(dotnet), "build", "Probe.csproj", "-c", "Debug", "-o", "output", f"-p:ValidationTargetFramework=net{version}.0"],
                   cwd=fixture, env=env, check=True)
    subprocess.run([sys.executable, str(repo / "scripts/validation/dap_probe.py"), "--engine", "netcoredbg", "--debugger", str(adapter),
                    "--program", str(fixture / "output/Probe.dll"), "--source", str(fixture / "Program.cs"),
                    "--expected-arch", env["VALIDATION_ARCH"], "--expected-runtime", version,
                    "--log", str(root / f"dap-net{version}.jsonl"), "--result", str(root / f"dap-net{version}-result.json"),
                    "--diagnose-hang"], cwd=fixture, env=env, check=False)
    for index, core in enumerate(sorted(fixture.glob('core.*'))):
        with (root / f'net{version}-core-{index + 1}.stacks.log').open('w') as output:
            subprocess.run(['gdb', '-nx', '-batch', str(adapter), str(core), '-ex', 'set pagination off',
                            '-ex', 'set debuginfod enabled off', '-ex', 'thread apply all bt'],
                           stdout=output, stderr=subprocess.STDOUT, timeout=30)
        core.unlink()
print('Diagnostic collection finished. This workflow cannot promote a debugger or publish VSIX packages.')
