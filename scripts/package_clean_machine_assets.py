#!/usr/bin/env python3
"""Build the hash-locked wheelhouse or the SWE-smith archive consumed by machines-clean."""

import argparse
from email.parser import BytesParser
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import zipfile

from clean_machine_deployment import hash_file


def metadata(wheel):
    with zipfile.ZipFile(wheel) as package:
        name = next(item for item in package.namelist() if item.endswith(".dist-info/METADATA"))
        headers = BytesParser().parsebytes(package.read(name), headersonly=True)
    return headers["Name"], headers["Version"]


def wheelhouse(directory, output):
    wheels = sorted(directory.glob("*.whl"))
    if not wheels:
        raise ValueError("Download the complete platform-specific wheels first")
    requirements = []
    seen = set()
    for wheel in wheels:
        name, version = metadata(wheel)
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in seen:
            raise ValueError(f"Multiple wheel candidates for {name}; select one for the target Python and CPU")
        seen.add(normalized)
        requirements.append(f"{name}=={version} --hash=sha256:{hash_file(wheel)}\n")
    with tarfile.open(output, "x:gz") as archive:
        for wheel in wheels:
            archive.add(wheel, arcname=wheel.name)
        contents = "".join(requirements).encode()
        lock = tarfile.TarInfo("requirements.lock")
        lock.size = len(contents)
        archive.addfile(lock, io.BytesIO(contents))


def swe_smith(repository, revision, workload, output):
    revision = subprocess.check_output(["git", "-C", repository, "rev-parse", "--verify",
                                        revision + "^{commit}"], text=True).strip()
    with tempfile.TemporaryFile() as tree:
        subprocess.run(["git", "-C", repository, "archive", revision, "experiments/workload"],
                       stdout=tree, check=True)
        tree.seek(0)
        with tarfile.open(fileobj=tree) as source, tarfile.open(output, "x:gz") as archive:
            for entry in source:
                if entry.isfile():
                    archive.addfile(entry, source.extractfile(entry))
            for file in ("sessions.csv", "manifest.json"):
                archive.add(workload / file, arcname="workload/" + file, recursive=False)
            contents = (json.dumps({"commit": revision, "sessions_sha256": hash_file(workload / "sessions.csv"),
                                     "manifest_sha256": hash_file(workload / "manifest.json")}) + "\n").encode()
            receipt = tarfile.TarInfo("REVISION")
            receipt.size = len(contents)
            archive.addfile(receipt, io.BytesIO(contents))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    wheels = commands.add_parser("wheelhouse")
    wheels.add_argument("directory", type=Path)
    wheels.add_argument("output", type=Path)
    replay = commands.add_parser("swe-smith")
    replay.add_argument("repository", type=Path)
    replay.add_argument("revision")
    replay.add_argument("workload", type=Path)
    replay.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.action == "wheelhouse":
        wheelhouse(args.directory, args.output)
    else:
        swe_smith(args.repository, args.revision, args.workload, args.output)
    print(hash_file(args.output), args.output)


if __name__ == "__main__":
    main()
