#!/usr/bin/env python3
"""Deploy, benchmark and collect evidence from a dedicated RIDE machine list."""

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile


def run_logged(command, log):
    with log.open("w") as output:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace") as process:
            try:
                for line in process.stdout:
                    output.write(line)
                    output.flush()
                    print(line, end="", flush=True)
            except BaseException:
                process.kill()
                raise
            return process.wait()


def collect(host, config, output):
    sources = [
        item for source in host["paths"] for item in ("-C", "/", str(Path(source).relative_to("/")))
    ]
    exclusions = ["--exclude=" + pattern for pattern in host.get("exclude", [])]
    remote = shlex.join(["tar", "-czf", "-", *exclusions, *sources])
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
        "-o", "ConnectTimeout=10", "-o", "UserKnownHostsFile=" + config["known_hosts"],
        "-i", config["ssh_key"], "--", host["destination"], remote,
    ]
    destination = output / (host["name"] + ".tar.gz")
    with destination.open("wb") as archive, (output / (host["name"] + ".log")).open("w") as log:
        result = subprocess.run(command, stdout=archive, stderr=log, timeout=120, check=False)
    with tarfile.open(destination, "r:gz") as archive:
        members = archive.getnames()
    return {"exit_code": result.returncode, "members": members}


def seal(output, archive_path):
    records = {}
    for file in sorted(output.rglob("*")):
        if file.is_file():
            digest = hashlib.sha256()
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            records[file.relative_to(output).as_posix()] = digest.hexdigest()
    (output / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in records.items()))
    with tarfile.open(archive_path, "x:gz") as archive:
        archive.add(output, arcname=output.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.configuration.read_text())
    if not config["hosts"] or len({host["name"] for host in config["hosts"]}) != len(config["hosts"]):
        parser.error("Specify at least one host and unique host names")
    for host in config["hosts"]:
        name = host["name"]
        if name in {".", ".."} or not name or Path(name).name != name or not host["paths"]:
            parser.error("Each host needs a simple name and at least one evidence path")
        if any(not Path(path).is_absolute() or Path(path) == Path("/") or ".." in Path(path).parts
               for path in host["paths"]):
            parser.error("Evidence paths must be absolute paths to specific files or directories")
    output = args.output.resolve()
    archive_path = output.parent / (output.name + ".tar.gz")
    if archive_path.exists():
        parser.error("Result archive already exists")
    output.mkdir(mode=0o700, parents=True)
    (output / "experiment.json").write_text(args.configuration.read_text())
    if config.get("initial_evidence"):
        shutil.copyfile(config["initial_evidence"], output / "bootstrap-evidence.tar.gz")
    status = {"stages": {}, "nodes": {}}
    deployment = [sys.executable, "-m", "ride.deployment"]
    try:
        steps = [("validate", deployment + ["validate", config["deployment"], config["state_directory"]])]
        if config.get("prepare_command"):
            steps.append(("prepare", config["prepare_command"]))
        steps.append(("up", deployment + ["up", config["deployment"], config["state_directory"]]))
        for stage, command in steps:
            print(stage, flush=True)
            status["stages"][stage] = run_logged(
                command,
                output / (stage + ".log"),
            )
            if status["stages"][stage]:
                break
        else:
            print("benchmark", flush=True)
            status["stages"]["benchmark"] = run_logged(
                [*config["benchmark_command"], str(output)], output / "benchmark.log",
            )
    finally:
        print("collect", flush=True)
        for host in config["hosts"]:
            try:
                status["nodes"][host["name"]] = collect(host, config, output)
            except (OSError, subprocess.SubprocessError, tarfile.TarError) as error:
                status["nodes"][host["name"]] = {"error": str(error)}
        success = (
            status["stages"].get("benchmark") == 0
            and all(node.get("exit_code") == 0 and node["members"] for node in status["nodes"].values())
        )
        status["status"] = "PASS" if success else "FAIL"
        (output / "status.json").write_text(json.dumps(status, indent=2) + "\n")
        seal(output, archive_path)
        print(f'{status["status"]} {archive_path}', flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
