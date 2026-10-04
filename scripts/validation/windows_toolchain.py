"""Select an installed Visual Studio instance supported by the current CMake."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


COMPONENTS = {
    "x64": "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
    "arm64": "Microsoft.VisualStudio.Component.VC.Tools.ARM64",
}


def select_toolchain(installations, capabilities, architecture):
    """Choose the newest usable instance with a matching Visual Studio generator."""
    if architecture not in COMPONENTS:
        raise ValueError(f"Unsupported Windows architecture: {architecture}")
    if not isinstance(installations, list):
        raise ValueError("vswhere must return a JSON array of Visual Studio installations")
    if not isinstance(capabilities, dict) or not isinstance(capabilities.get("generators"), list):
        raise ValueError("CMake capabilities must contain a generators array")
    cmake_version = capabilities.get("version", {}).get("string")
    if not isinstance(cmake_version, str) or not cmake_version:
        raise ValueError("CMake capabilities must contain version.string")

    platform = "ARM64" if architecture == "arm64" else "x64"
    generators = {}
    for generator in capabilities["generators"]:
        if not isinstance(generator, dict):
            continue
        match = re.fullmatch(r"Visual Studio (\d+) \d{4}", generator.get("name", ""))
        if not match or generator.get("platformSupport") is not True:
            continue
        if "supportedPlatforms" in generator and platform not in generator["supportedPlatforms"]:
            continue
        generators[int(match[1])] = generator["name"]

    usable = []
    for installation in installations:
        if not isinstance(installation, dict):
            continue
        if installation.get("isComplete") is not True or installation.get("isLaunchable") is not True:
            continue
        version = installation.get("installationVersion", "")
        path = installation.get("installationPath", "")
        if not isinstance(version, str) or not re.fullmatch(r"\d+(?:\.\d+)*", version):
            continue
        if not isinstance(path, str) or not path.strip():
            continue
        version_key = tuple(map(int, version.split(".")))
        usable.append((version_key, installation))
    for version_key, installation in sorted(usable, key=lambda item: item[0], reverse=True):
        generator = generators.get(version_key[0])
        if generator:
            return {
                "generator": generator,
                "installationPath": installation["installationPath"],
                "installationVersion": installation["installationVersion"],
                "architecture": architecture,
                "cmakeVersion": cmake_version,
            }
    installed = ", ".join(item["installationVersion"] for _, item in usable) or "none"
    supported = ", ".join(generators.values()) or "none"
    raise ValueError(
        f"No usable Visual Studio/CMake pair for {architecture}. "
        f"Complete launchable C++ installations: {installed}; "
        f"CMake {cmake_version} generators for {platform}: {supported}"
    )


def read_json_command(arguments):
    result = subprocess.run(arguments, check=True, capture_output=True, encoding="utf-8-sig")
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=COMPONENTS, required=True)
    parser.add_argument("--vswhere", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        installations = read_json_command([
            str(args.vswhere), "-products", "*", "-requires", COMPONENTS[args.arch],
            "-format", "json", "-utf8",
        ])
        capabilities = read_json_command(["cmake", "-E", "capabilities"])
        toolchain = select_toolchain(installations, capabilities, args.arch)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(toolchain, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(toolchain))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        print(f"Windows toolchain selection failed: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
