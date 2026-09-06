"""Install pinned musl SDKs from official release metadata after SHA-512 verification."""
import hashlib
import json
import os
from pathlib import Path
import tarfile
import urllib.request

root = Path(os.environ["DOTNET_INSTALL_DIR"])
root.mkdir(parents=True, exist_ok=True)
records = []
for major in ("8", "10"):
    version = os.environ[f"SDK{major}_VERSION"]
    url = f"https://builds.dotnet.microsoft.com/dotnet/release-metadata/{major}.0/releases.json"
    with urllib.request.urlopen(url, timeout=60) as response:
        metadata = json.load(response)
    sdk = next(sdk for release in metadata["releases"] for sdk in release.get("sdks", [release["sdk"]])
               if sdk["version"] == version)
    rid = "linux-musl-" + os.environ["VALIDATION_ARCH"]
    item = next(file for file in sdk["files"] if file["rid"] == rid and file["name"].endswith(".tar.gz"))
    archive = root.parent / f"sdk-{version}-{rid}.tar.gz"
    urllib.request.urlretrieve(item["url"], archive)
    digest = hashlib.sha512(archive.read_bytes()).hexdigest()
    assert digest.lower() == item["hash"].lower(), f"SDK checksum mismatch: {version}/{rid}"
    with tarfile.open(archive) as tar:
        tar.extractall(root, filter="data")
    archive.unlink()
    records.append(dict(version=version, rid=rid, url=item["url"], sha512=digest))
evidence = Path(os.environ["VALIDATION_ROOT"]) / "evidence"
evidence.mkdir(parents=True, exist_ok=True)
(evidence / "sdk-downloads.json").write_text(json.dumps(records, indent=2) + "\n")
