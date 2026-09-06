"""Restore an interrupted release's tested VSIX bytes and evidence without rebuilding."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

from discover import metadata
import versioning

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--candidate", type=Path, required=True)
parser.add_argument("--artifacts", type=Path, required=True)
args = parser.parse_args()
candidate = json.loads(args.candidate.read_text())
versioning.validate(candidate)
repo = json.loads((Path(__file__).resolve().parents[2] / "config/variant.json").read_text())["repository"]
tag = candidate["resumeRelease"]
assert tag == candidate["releaseTag"]
release = json.loads(subprocess.check_output(["gh", "release", "view", tag, "--repo", repo, "--json", "body"], text=True))
recorded = metadata(release["body"])
for key in ("fingerprint", "debuggerSha", "csharpSha", "version", "artifactPrefix", "revision", "releaseTag", "csharpVersion", "versionPolicy"):
    assert recorded[key] == candidate[key], "Preserved release identity mismatch"
subprocess.run(["gh", "release", "download", tag, "--repo", repo, "--dir", str(args.artifacts)], check=True)
with zipfile.ZipFile(args.artifacts / "native-validation-evidence.zip") as archive:
    assert len(archive.namelist()) == len(set(archive.namelist()))
    for name in archive.namelist():
        assert not Path(name).is_absolute() and ".." not in Path(name).parts and "\\" not in name
    archive.extractall(args.artifacts)
validated = args.artifacts / (candidate["artifactPrefix"] + "-validated")
validated.mkdir()
for file in [args.artifacts / "validation-manifest.json", *args.artifacts.glob("netcoredbg-*.zip")]:
    shutil.move(file, validated / file.name)
print("Restored preserved VSIX and native validation evidence. The publication gate will verify every hash again.")
