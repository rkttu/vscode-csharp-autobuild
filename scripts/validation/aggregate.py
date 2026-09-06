"""Require every target, both runtime tests and exact artifact hashes before promotion."""
import argparse
import json
from pathlib import Path
import sys
import zipfile

from audit import sha256


def aggregate(inputs, config, expected_sha, workflow_sha, run_id, output, prefix="netcoredbg"):
    output.mkdir(parents=True, exist_ok=True)
    rows, errors = [], []
    for target in config["targets"]:
        try:
            roots = list(inputs.glob(f"{prefix}-{target}-*"))
            assert roots, "Missing target artifact"
            root = max(roots, key=lambda p: int(p.name.rsplit("-", 1)[1]))
            evidence, package = root / "evidence", root / "package/netcoredbg"
            result = json.loads((evidence / "result.json").read_text(encoding="utf-8-sig"))
            assert result["success"] is True and result["sourceUnchanged"] is True, result.get("error")
            for key, expected in (("netcoredbgCommit", expected_sha), ("workflowCommit", workflow_sha), ("runId", run_id),
                                  ("coreclrCommit", config["coreclrCommit"]), ("sdk8", config["sdk8"]),
                                  ("sdk10", config["sdk10"]), ("dbgshimVersion", config["dbgshimVersion"])):
                assert str(result[key]) == str(expected), f"{key} mismatch"
            assert result["architecture"] == target.split("-")[1]
            assert result["target"] == target
            integrity = json.loads((evidence / "source-integrity.json").read_text(encoding="utf-8-sig"))
            assert integrity["success"] is True and integrity["originalFileCount"] > 0 and integrity["changedOrMissing"] == []
            assert sorted(t["runtime"] for t in result["runtimeTests"]) == sorted(config["runtimes"])
            assert all(t["success"] is True for t in result["runtimeTests"])
            for runtime in config["runtimes"]:
                dap = json.loads((evidence / f"dap-net{runtime}-result.json").read_text(encoding="utf-8-sig"))
                assert dap["success"] is True and len(dap["checks"]) == 8, f"Incomplete DAP checks: .NET {runtime}"
                assert dap["expectedArchitecture"] == target.split("-")[1] and dap["expectedRuntime"] == runtime
            files = json.loads((evidence / "package-sha256.json").read_text(encoding="utf-8-sig"))
            expected_files = {item["file"].replace("\\", "/"): item["sha256"] for item in files}
            actual_files = {p.relative_to(package).as_posix(): sha256(p) for p in package.rglob("*") if p.is_file()}
            assert actual_files and expected_files == actual_files, "Package file set/hash mismatch"
            native = json.loads((evidence / "debugger-architectures.json").read_text(encoding="utf-8-sig"))
            assert native["success"] is True and native["expectedArchitecture"] == target.split("-")[1]
            exe = "netcoredbg.exe" if target.startswith("win32") else "netcoredbg"
            shim = "dbgshim.dll" if target.startswith("win32") else ("libdbgshim.dylib" if target.startswith("darwin") else "libdbgshim.so")
            assert {p["file"].replace("\\", "/").split("/")[-1] for p in native["files"]} == {exe, shim}
            required = {exe, shim, "ManagedPart.dll", "Microsoft.CodeAnalysis.dll", "Microsoft.CodeAnalysis.CSharp.dll",
                        "Microsoft.CodeAnalysis.Scripting.dll", "Microsoft.CodeAnalysis.CSharp.Scripting.dll",
                        "notices/Samsung-netcoredbg-LICENSE", "notices/dotnet-runtime-LICENSE.TXT"}
            assert required <= set(actual_files), "Required runtime files or notices missing"
            for item in native["files"]:
                # Windows paths remain Windows paths when aggregation runs on Linux.
                name = item["file"].replace("\\", "/").split("/")[-1]
                assert actual_files[name] == item["sha256"], "Tested binary differs from packaged binary"
            archive = output / f"netcoredbg-{target}.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_out:
                for name in sorted(actual_files):
                    info = zipfile.ZipInfo("netcoredbg/" + name, (2026, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = (0o100755 if name == "netcoredbg" else 0o100644) << 16
                    zip_out.writestr(info, (package / name).read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
            rows.append(dict(target=target, success=True, archive=archive.name, sha256=sha256(archive), files=actual_files))
        except Exception as error:
            errors.append(f"{target}: {error}")
            rows.append(dict(target=target, success=False, error=str(error)))
    manifest = dict(schemaVersion=1, success=not errors, netcoredbgCommit=expected_sha,
                    workflowCommit=workflow_sha, runId=run_id, config=config, targets=rows, errors=errors)
    (output / "validation-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("\n".join(errors) if errors else "All eight targets and sixteen runtime combinations passed.")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "config", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("sha", "workflow-sha", "run-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--prefix", default="netcoredbg")
    args = parser.parse_args()
    result = aggregate(args.inputs, json.loads(args.config.read_text()), args.sha, args.workflow_sha, args.run_id, args.output, args.prefix)
    sys.exit(0 if result["success"] else 1)
