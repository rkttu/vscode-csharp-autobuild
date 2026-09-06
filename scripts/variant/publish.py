"""Publish only a complete, hash-matched set; preserve immutable VSIX for retries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

import versioning

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "validation"))
from upstream_suite import validate_result


def sha256(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def save_status(args, **values):
    file = args.artifacts / "publication-status.json"
    status = json.loads(file.read_text()) if file.exists() else dict(verifiedTargets=[])
    status.update(values)
    file.write_text(json.dumps(status, indent=2) + "\n")


def registry_metadata(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code != 404:
            raise
        return None


def wait_for_metadata(url, deadline):
    while True:
        published = registry_metadata(url)
        if published is not None:
            return published
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Open VSX publication is not publicly available: " + url)
        print("Waiting for Open VSX asynchronous publication: " + url, flush=True)
        time.sleep(min(15, remaining))


def execute(args):
    repo = Path(__file__).resolve().parents[2]
    settings = json.loads((repo / "config/netcoredbg.json").read_text())
    variant = json.loads((repo / "config/variant.json").read_text())
    candidate = json.loads(args.candidate.read_text())
    candidate.pop("resumeRelease", None)
    versioning.validate(candidate)
    save_status(args, stage="validate-artifacts", candidate=candidate, publicationRequested=args.publish)
    outputs = []
    for target in settings["targets"]:
        files = list(args.artifacts.rglob(f"{variant['name']}-{target}-{candidate['version']}.vsix"))
        assert len(files) == 1, f"Missing or duplicate VSIX: {target}"
        records = [json.loads(p.read_text()) for p in args.artifacts.glob(f"*-tested-{target}/vsix-result.json")]
        assert len(records) == 1, f"Missing or duplicate native VSIX verification: {target}"
        record = records[0]
        assert record["success"] is True and record["target"] == target and record["version"] == candidate["version"]
        assert record["runtimeTests"] == settings["runtimes"]
        assert set(record["upstreamTests"]) == set(settings["runtimes"])
        for runtime in settings["runtimes"]:
            validate_result(record["upstreamTests"][runtime], runtime, target.split("-")[1], record["debuggerSha256"])
        assert record["sha256"] == sha256(files[0]), f"Untested or changed VSIX: {target}"
        assert record["netcoredbgBuild"]["netcoredbgCommit"] == candidate["debuggerSha"]
        assert record["netcoredbgBuild"]["upstreamCsharpCommit"] == candidate["csharpSha"]
        for field, key in (("upstreamCsharpVersion", "csharpVersion"), ("netcoredbgTag", "debuggerTag"),
                           ("packagingRevision", "revision"), ("releaseTag", "releaseTag")):
            assert record["netcoredbgBuild"][field] == candidate[key], "VSIX version provenance mismatch: " + field
        outputs.append(dict(target=target, file=files[0], sha256=record["sha256"]))
    release_manifest = dict(candidate=candidate, targets=[dict(target=p["target"], file=p["file"].name, sha256=p["sha256"]) for p in outputs])
    manifest_file = args.artifacts / "release-manifest.json"
    manifest_file.write_text(json.dumps(release_manifest, indent=2) + "\n")
    if not args.publish:
        save_status(args, stage="dry-run-complete", success=True)
        print("Dry run: all eight VSIX packages have matching native DAP evidence. No publication requested.")
        return
    assert os.environ.get("OVSX_PAT"), "Open VSX token is missing"
    assert os.environ.get("GITHUB_REF") == "refs/heads/main", "Publication is restricted to main"
    release_tag = candidate["releaseTag"]
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
                     "The required upstream DAP suite also passed on both runtimes. These checks do not establish full IDE, remote, or C# Dev Kit feature parity.\n\n"
                     "<!-- netcoredbg-variant: " + json.dumps(meta, separators=(",", ":")) + " -->\n")
    save_status(args, stage="preserve-release", success=False)
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
    save_status(args, stage="publish-targets", verifiedTargets=[], submittedTargets=[])
    verified_targets = []
    pending = []

    def verify_public_bytes(package, published):
        assert published["version"] == candidate["version"] and published["targetPlatform"] == package["target"]
        with urllib.request.urlopen(published["files"]["download"], timeout=120) as response:
            digest = hashlib.sha256(response.read()).hexdigest()
        assert digest == package["sha256"], "Published VSIX differs from the tested bytes"
        verified_targets.append(package["target"])
        save_status(args, verifiedTargets=verified_targets)
        print(f"Verified Open VSX publication: {package['target']}")

    for package in outputs:
        save_status(args, target=package["target"])
        url = f"https://open-vsx.org/api/{variant['publisher']}/{variant['name']}/{package['target']}/{candidate['version']}"
        published = registry_metadata(url)
        if published is not None:
            verify_public_bytes(package, published)
            continue
        subprocess.run(["ovsx", "publish", "--packagePath", str(package["file"])], check=True)
        pending.append((package, url))
        save_status(args, submittedTargets=[p["target"] for p, _ in pending])

    # The server acknowledges uploads before asynchronous scans activate them.
    # Submit each missing target once, then use one bounded visibility deadline.
    deadline = time.monotonic() + 15 * 60
    for package, url in pending:
        save_status(args, stage="wait-for-publication", target=package["target"])
        verify_public_bytes(package, wait_for_metadata(url, deadline))
    save_status(args, stage="finalize-github-release")
    meta["published"] = True
    notes.write_text(notes.read_text().replace('"published":false', '"published":true'))
    subprocess.run(["gh", "release", "edit", release_tag, "--repo", repository, "--draft=false", "--latest=false", "--notes-file", str(notes)], check=True)

    save_status(args, stage="published", success=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    args.artifacts.mkdir(parents=True, exist_ok=True)
    try:
        execute(args)
    except Exception as error:
        save_status(args, success=False, error=str(error) or type(error).__name__)
        raise


if __name__ == "__main__":
    main()
