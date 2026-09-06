"""Publish only a complete, hash-matched set; preserve immutable VSIX for retries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request
import zipfile


def sha256(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    settings = json.loads((repo / "config/netcoredbg.json").read_text())
    variant = json.loads((repo / "config/variant.json").read_text())
    candidate = json.loads(args.candidate.read_text())
    candidate.pop("resumeRelease", None)
    outputs = []
    for target in settings["targets"]:
        files = list(args.artifacts.rglob(f"{variant['name']}-{target}-{candidate['version']}.vsix"))
        assert len(files) == 1, f"Missing or duplicate VSIX: {target}"
        records = [json.loads(p.read_text()) for p in args.artifacts.glob(f"*-tested-{target}/vsix-result.json")]
        assert len(records) == 1, f"Missing or duplicate native VSIX verification: {target}"
        record = records[0]
        assert record["success"] is True and record["target"] == target and record["version"] == candidate["version"]
        assert record["runtimeTests"] == settings["runtimes"]
        assert record["sha256"] == sha256(files[0]), f"Untested or changed VSIX: {target}"
        assert record["netcoredbgBuild"]["netcoredbgCommit"] == candidate["debuggerSha"]
        assert record["netcoredbgBuild"]["upstreamCsharpCommit"] == candidate["csharpSha"]
        outputs.append(dict(target=target, file=files[0], sha256=record["sha256"]))
    release_manifest = dict(candidate=candidate, targets=[dict(target=p["target"], file=p["file"].name, sha256=p["sha256"]) for p in outputs])
    manifest_file = args.artifacts / "release-manifest.json"
    manifest_file.write_text(json.dumps(release_manifest, indent=2) + "\n")
    if not args.publish:
        print("Dry run: all eight VSIX packages have matching native DAP evidence. No publication requested.")
        return
    assert os.environ.get("OVSX_PAT"), "Open VSX token is missing"
    assert os.environ.get("GITHUB_REF") == "refs/heads/main", "Publication is restricted to main"
    release_tag = "csharp-netcoredbg-v" + candidate["version"]
    repository = variant["repository"]
    validated = args.artifacts / (candidate["artifactPrefix"] + "-validated")
    evidence_zip = args.artifacts / "native-validation-evidence.zip"
    with zipfile.ZipFile(evidence_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(args.artifacts.rglob("*")):
            if file.is_file() and ("/evidence/" in file.as_posix() or "-tested-" in file.as_posix()) and file.suffix in (".json", ".jsonl", ".log"):
                archive.write(file, file.relative_to(args.artifacts))
    notes = args.artifacts / "release-notes.md"
    meta = dict(candidate, published=False)
    notes.write_text(f"C# (with netcoredbg) {candidate['version']}\n\n"
                     f"C# source: {candidate['csharpTag']} ({candidate['csharpSha']})\n\n"
                     f"netcoredbg source: {candidate['debuggerTag']} ({candidate['debuggerSha']})\n\n"
                     "All eight native targets passed .NET 8/10 source-build and extracted-VSIX DAP validation. "
                     "These checks do not establish full IDE, attach, remote, or C# Dev Kit feature parity.\n\n"
                     "<!-- netcoredbg-variant: " + json.dumps(meta, separators=(",", ":")) + " -->\n")
    existing = subprocess.run(["gh", "release", "view", release_tag, "--repo", repository, "--json", "tagName"], capture_output=True)
    if existing.returncode:
        subprocess.run(["gh", "release", "create", release_tag, "--repo", repository, "--target", os.environ["GITHUB_SHA"],
                        "--title", "C# (with netcoredbg) " + candidate["version"], "--draft", "--latest=false", "--notes-file", str(notes),
                        str(manifest_file), str(evidence_zip), str(validated / "validation-manifest.json"),
                        *[str(p) for p in sorted(validated.glob("netcoredbg-*.zip"))],
                        *[str(p["file"]) for p in outputs]], check=True)
    else:
        preserved = args.artifacts / "preserved-release"
        subprocess.run(["gh", "release", "download", release_tag, "--repo", repository, "--dir", str(preserved)], check=True)
        assert json.loads((preserved / "release-manifest.json").read_text()) == release_manifest, "Existing release inputs differ; use its saved artifacts"
        for package in outputs:
            assert sha256(preserved / package["file"].name) == package["sha256"], "Existing release asset differs"
    for package in outputs:
        url = f"https://open-vsx.org/api/{variant['publisher']}/{variant['name']}/{package['target']}/{candidate['version']}"
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                published = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            subprocess.run(["ovsx", "publish", "--packagePath", str(package["file"])], check=True)
            with urllib.request.urlopen(url, timeout=60) as response:
                published = json.load(response)
        assert published["version"] == candidate["version"] and published["targetPlatform"] == package["target"]
        with urllib.request.urlopen(published["files"]["download"], timeout=120) as response:
            digest = hashlib.sha256(response.read()).hexdigest()
        assert digest == package["sha256"], "Published VSIX differs from the tested bytes"
        print(f"Verified Open VSX publication: {package['target']}")
    meta["published"] = True
    notes.write_text(notes.read_text().replace('"published":false', '"published":true'))
    subprocess.run(["gh", "release", "edit", release_tag, "--repo", repository, "--draft=false", "--latest=false", "--notes-file", str(notes)], check=True)


if __name__ == "__main__":
    main()
