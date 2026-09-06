"""Negative tests for the publication boundary, using synthetic evidence only."""
import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from aggregate import aggregate
from audit import sha256


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = json.loads((Path(__file__).resolve().parents[2] / "config/netcoredbg.json").read_text())
        for target in self.config["targets"]:
            root = self.root / "inputs" / f"netcoredbg-{target}-1"
            evidence, package = root / "evidence", root / "package/netcoredbg"
            evidence.mkdir(parents=True)
            package.mkdir(parents=True)
            exe = "netcoredbg.exe" if target.startswith("win32") else "netcoredbg"
            shim = "dbgshim.dll" if target.startswith("win32") else ("libdbgshim.dylib" if target.startswith("darwin") else "libdbgshim.so")
            for name in [exe, shim, "ManagedPart.dll", "Microsoft.CodeAnalysis.dll", "Microsoft.CodeAnalysis.CSharp.dll",
                         "Microsoft.CodeAnalysis.Scripting.dll", "Microsoft.CodeAnalysis.CSharp.Scripting.dll",
                         "notices/Samsung-netcoredbg-LICENSE", "notices/dotnet-runtime-LICENSE.TXT"]:
                file = package / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("Synthetic fixture, not executable: " + name)
            self.write(evidence / "package-sha256.json", [dict(file=p.relative_to(package).as_posix(), sha256=sha256(p)) for p in package.rglob("*") if p.is_file()])
            arch = target.split("-")[1]
            self.write(evidence / "debugger-architectures.json", dict(success=True, expectedArchitecture=arch,
                       files=[dict(file=name, sha256=sha256(package / name), architecture=arch) for name in (exe, shim)]))
            self.write(evidence / "source-integrity.json", dict(success=True, originalFileCount=498, changedOrMissing=[]))
            for version in self.config["runtimes"]:
                self.write(evidence / f"dap-net{version}-result.json", dict(success=True, checks=list(range(8)), expectedArchitecture=arch, expectedRuntime=version))
            self.write(evidence / "result.json", dict(success=True, sourceUnchanged=True, target=target, architecture=arch,
                netcoredbgCommit="a" * 40, workflowCommit="b" * 40, runId="123", coreclrCommit=self.config["coreclrCommit"],
                sdk8=self.config["sdk8"], sdk10=self.config["sdk10"], dbgshimVersion=self.config["dbgshimVersion"],
                runtimeTests=[dict(runtime=v, success=True) for v in self.config["runtimes"]]))

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value))

    def run_gate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return aggregate(self.root / "inputs", self.config, "a" * 40, "b" * 40, "123", self.root / "output")

    def change(self, target, name, update):
        file = self.root / "inputs" / f"netcoredbg-{target}-1/evidence" / name
        data = json.loads(file.read_text())
        update(data)
        self.write(file, data)

    def test_complete_evidence_passes(self):
        self.assertTrue(self.run_gate()["success"])

    def test_missing_target_fails(self):
        shutil.rmtree(self.root / "inputs/netcoredbg-alpine-arm64-1")
        self.assertFalse(self.run_gate()["success"])

    def test_changed_package_fails(self):
        (self.root / "inputs/netcoredbg-linux-x64-1/package/netcoredbg/netcoredbg").write_text("changed after validation")
        self.assertFalse(self.run_gate()["success"])

    def test_wrong_source_sha_fails(self):
        self.change("win32-arm64", "result.json", lambda d: d.update(netcoredbgCommit="c" * 40))
        self.assertFalse(self.run_gate()["success"])

    def test_wrong_validation_run_fails(self):
        self.change("darwin-x64", "result.json", lambda d: d.update(runId="122"))
        self.assertFalse(self.run_gate()["success"])

    def test_missing_runtime_fails(self):
        self.change("linux-arm64", "result.json", lambda d: d["runtimeTests"].pop())
        self.assertFalse(self.run_gate()["success"])

    def test_source_integrity_disagreement_fails(self):
        self.change("alpine-x64", "source-integrity.json", lambda d: d.update(success=False))
        self.assertFalse(self.run_gate()["success"])

    def test_swapped_cpu_evidence_fails(self):
        self.change("win32-x64", "dap-net10-result.json", lambda d: d.update(expectedArchitecture="arm64"))
        self.assertFalse(self.run_gate()["success"])

    def test_untested_native_binary_fails(self):
        self.change("darwin-arm64", "debugger-architectures.json", lambda d: d.update(files=[]))
        self.assertFalse(self.run_gate()["success"])


if __name__ == "__main__":
    unittest.main()
