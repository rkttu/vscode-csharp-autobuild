"""Regressions for hosted-runner Visual Studio and CMake version changes."""
import unittest

from windows_toolchain import select_toolchain


def instance(version, **overrides):
    return dict(installationVersion=version, installationPath=f"C:/VS/{version}",
                isComplete=True, isLaunchable=True, **overrides)


def capabilities(*majors, platforms=("x64", "ARM64")):
    years = {17: 2022, 18: 2026}
    return dict(version={"string": "4.4.3"}, generators=[
        dict(name=f"Visual Studio {major} {years[major]}", platformSupport=True,
             supportedPlatforms=list(platforms)) for major in majors
    ])


class WindowsToolchainTests(unittest.TestCase):
    def test_vs17_x64_runner_keeps_its_installed_generator(self):
        selected = select_toolchain([instance("17.14.36510.44")], capabilities(17, 18), "x64")
        self.assertEqual(selected["generator"], "Visual Studio 17 2022")
        self.assertEqual(selected["architecture"], "x64")

    def test_vs18_arm64_runner_uses_new_generator(self):
        selected = select_toolchain([instance("18.10.12217.157")], capabilities(17, 18), "arm64")
        self.assertEqual(selected, dict(generator="Visual Studio 18 2026",
            installationPath="C:/VS/18.10.12217.157", installationVersion="18.10.12217.157",
            architecture="arm64", cmakeVersion="4.4.3"))

    def test_multiple_compatible_instances_choose_newest_numeric_version(self):
        installed = [instance("18.9.12009.81"), instance("17.14.36510.44"), instance("18.10.12217.157")]
        selected = select_toolchain(installed, capabilities(17, 18), "arm64")
        self.assertEqual(selected["installationVersion"], "18.10.12217.157")

    def test_unsupported_newer_instance_falls_back_to_matching_generator(self):
        selected = select_toolchain([instance("18.10.12217.157"), instance("17.14.36510.44")],
                                    capabilities(17), "x64")
        self.assertEqual(selected["generator"], "Visual Studio 17 2022")

    def test_missing_installation_fails_with_available_generator_diagnostic(self):
        with self.assertRaisesRegex(ValueError, "installations: none.*Visual Studio 18 2026"):
            select_toolchain([], capabilities(18), "arm64")

    def test_installed_major_without_matching_generator_fails(self):
        with self.assertRaisesRegex(ValueError, "18.10.12217.157.*Visual Studio 17 2022"):
            select_toolchain([instance("18.10.12217.157")], capabilities(17), "arm64")

    def test_incomplete_or_unlaunchable_newer_instances_are_excluded(self):
        installed = [instance("17.14.36510.44")]
        for status in ("isComplete", "isLaunchable"):
            broken = instance("18.10.12217.157")
            broken[status] = False
            installed.append(broken)
        selected = select_toolchain(installed, capabilities(17, 18), "arm64")
        self.assertEqual(selected["generator"], "Visual Studio 17 2022")

    def test_generator_without_requested_platform_is_excluded(self):
        with self.assertRaisesRegex(ValueError, "generators for ARM64: none"):
            select_toolchain([instance("18.10.12217.157")], capabilities(18, platforms=("x64",)), "arm64")

    def test_optional_platform_list_is_not_required(self):
        available = capabilities(18)
        del available["generators"][0]["supportedPlatforms"]
        selected = select_toolchain([instance("18.10.12217.157")], available, "arm64")
        self.assertEqual(selected["generator"], "Visual Studio 18 2026")

    def test_cmake_version_is_required_for_evidence(self):
        available = capabilities(18)
        available["version"] = {}
        with self.assertRaisesRegex(ValueError, "version.string"):
            select_toolchain([instance("18.10.12217.157")], available, "arm64")


if __name__ == "__main__":
    unittest.main()
