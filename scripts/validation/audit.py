"""Source integrity and PE architecture checks for the validation-only workflow."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(source):
    names = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"])
    return {
        name: sha256(source / name)
        for name in names.decode("utf-8").split("\0") if name
    }


def pe_architecture(path):
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError(f"Not a PE file: {path}")
        stream.seek(0x3C)
        offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b"PE\0\0":
            raise ValueError(f"Invalid PE signature: {path}")
        machine = struct.unpack("<H", stream.read(2))[0]
    return {0x8664: "x64", 0xAA64: "arm64", 0x14C: "x86"}.get(machine, hex(machine))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    before = sub.add_parser("snapshot")
    before.add_argument("--source", type=Path, required=True)
    before.add_argument("--output", type=Path, required=True)
    after = sub.add_parser("compare")
    after.add_argument("--source", type=Path, required=True)
    after.add_argument("--before", type=Path, required=True)
    after.add_argument("--output", type=Path, required=True)
    pe = sub.add_parser("pe")
    pe.add_argument("--arch", choices=["x64", "arm64"], required=True)
    pe.add_argument("--output", type=Path, required=True)
    pe.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    success = True
    if args.command == "snapshot":
        result = snapshot(args.source)
    elif args.command == "compare":
        original = json.loads(args.before.read_text(encoding="utf-8"))
        changed = [name for name, digest in original.items()
                   if not (args.source / name).is_file() or sha256(args.source / name) != digest]
        success = not changed and bool(original)
        result = {"success": success, "originalFileCount": len(original), "changedOrMissing": changed,
                  "scope": "Original tracked input files; generated files are excluded."}
    else:
        records = [{"file": str(path), "architecture": pe_architecture(path), "sha256": sha256(path)}
                   for path in args.files]
        success = all(record["architecture"] == args.arch for record in records)
        result = {"success": success, "expectedArchitecture": args.arch, "files": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{args.command}: {'passed' if success else 'FAILED'}; evidence: {args.output}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
