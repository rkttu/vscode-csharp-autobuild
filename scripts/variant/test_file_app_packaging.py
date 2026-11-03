"""Check owned file-app entry packaging without an upstream build or debugger."""
import json
from pathlib import Path
import tempfile
import unittest

import overlay


class FileAppPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        (self.source / ".vscodeignore").write_text("src/**\n")
        self.package = {"main": "./dist/extension", "contributes": {
            "commands": [{"command": "existing"}],
            "keybindings": [{"command": "existing", "key": "ctrl+f9"}],
        }, "activationEvents": ["onLanguage:csharp"], "netcoredbgBuild": {"target": "linux-x64"}}

    def install(self):
        overlay.install_file_app_support(self.source, self.package, Path(__file__).resolve().parents[2])

    def test_wraps_entry_and_packages_only_runtime_modules(self):
        original = json.loads(json.dumps(self.package))
        self.install()
        self.assertEqual(self.package["main"], "./.netcoredbg/entry.cjs")
        self.assertEqual(self.package["netcoredbgBuild"], {
            "target": "linux-x64", "upstreamMain": original["main"],
        })
        self.assertEqual(self.package["contributes"]["commands"][0], original["contributes"]["commands"][0])
        self.assertEqual(self.package["contributes"]["keybindings"][-1], {
            "command": overlay.FILE_APP_COMMAND, "key": "f5", "when": overlay.FILE_APP_WHEN,
        })
        self.assertIn("onCommand:" + overlay.FILE_APP_COMMAND, self.package["activationEvents"])
        modules = self.source / ".netcoredbg"
        self.assertEqual({p.name for p in modules.iterdir()}, set(overlay.FILE_APP_MODULES))
        self.assertIn("!.netcoredbg/**", (self.source / ".vscodeignore").read_text())

    def test_fails_if_upstream_claims_f5(self):
        self.package["contributes"]["keybindings"].append({"command": "upstream", "key": "F5"})
        with self.assertRaisesRegex(ValueError, "F5"):
            self.install()

    def test_rejects_invalid_entry_points(self):
        for entry in (None, "", "../elsewhere.js", "/absolute.js", "C:\\elsewhere.js", "./.netcoredbg/entry.cjs"):
            with self.subTest(entry=entry):
                self.package["main"] = entry
                with self.assertRaisesRegex(ValueError, "entry point"):
                    self.install()


if __name__ == "__main__":
    unittest.main()
