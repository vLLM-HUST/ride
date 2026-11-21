#!/usr/bin/env python3
"""Install and run the SSH-only RIDE and SWE-smith deployment on dedicated Ubuntu machines."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import io
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
from urllib.parse import urlsplit
from urllib.request import url2pathname, urlopen

from run_machine_experiment import seal


BASE_PACKAGES = ("ca-certificates", "curl", "git", "iproute2", "openssh-client", "procps", "python3-venv", "rsync")
DEFAULT_WORKER_PARENT = "/opt/ride-clean"
CORE_ASSETS = ("python-runtime", "jump-wheelhouse", "worker-wheelhouse", "worker-debs", "model", "tokenizer", "swe-smith")
TOKEN_ENV = "RIDE_CONTROLLER_TOKEN"


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def hash_file(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def validate(config):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,30}", config["name"]):
        raise ValueError("Use a short deployment name")
    if config["ssh_user"] != "root":
        raise ValueError("Use root SSH on the dedicated Ubuntu workers")
    for key in ("ssh_key", "known_hosts"):
        if not Path(config[key]).is_absolute():
            raise ValueError(f"{key} must be an absolute path")
    worker_parent = Path(config.get("worker_work_parent", DEFAULT_WORKER_PARENT))
    if not worker_parent.is_absolute() or worker_parent == Path("/") or ".." in worker_parent.parts:
        raise ValueError("worker_work_parent must be an absolute dedicated directory")
    nodes = config["nodes"]
    expected = config["expected_nodes"]
    if type(expected) is not int or expected < 1 or len(nodes) != expected:
        raise ValueError(f"Inventory has {len(nodes)} nodes, expected {expected}")
    addresses = [str(ipaddress.IPv4Address(node["address"])) for node in nodes]
    if len(addresses) != len(set(addresses)):
        raise ValueError("Inventory contains duplicate node addresses")
    for node in nodes:
        if (type(node["cards"]) is not int or node["cards"] < 1
                or type(node["cpus"]) is not int or node["cpus"] < 4):
            raise ValueError("Each worker needs explicit positive card count and at least 4 CPUs")
    if not isinstance(config["model"], str) or not config["model"].strip():
        raise ValueError("Set a served model name")
    for value in config.get("model_args", []):
        if not isinstance(value, str) or value.split("=")[0] in (
            "--host", "--port", "--model", "--served-model-name", "--tensor-parallel-size",
        ):
            raise ValueError("Model args must preserve inventory routing and placement")
    if not config["installers"] or not config["environment_scripts"]:
        raise ValueError("Specify the CANN installers and runtime environment scripts")
    for path in config["environment_scripts"]:
        if not Path(path).is_absolute():
            raise ValueError("CANN environment scripts must be absolute paths")
    for installer in config["installers"]:
        if not isinstance(installer["args"], list) or not all(isinstance(x, str) for x in installer["args"]):
            raise ValueError("Installer arguments must be an array of strings")
    for name in [*CORE_ASSETS, *(item["asset"] for item in config["installers"])]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", name):
            raise ValueError("Invalid artifact name")
        asset = config["assets"][name]
        url = urlsplit(asset["url"])
        if (url.scheme not in ("https", "http", "file") or url.username or url.password
                or (url.scheme == "file" and (url.netloc or not url.path.startswith("/")))
                or url.query or url.fragment
                or (url.scheme != "file" and not url.hostname)
                or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])):
            raise ValueError(f"{name}: use a pinned HTTP(S) URL or host-local file URL and SHA-256")


def fetch(asset, destination):
    partial = destination.with_suffix(".partial")
    try:
        with urlopen(asset["url"], timeout=60) as response, partial.open("xb") as target:
            shutil.copyfileobj(response, target)
        if hash_file(partial) != asset["sha256"]:
            raise ValueError(f"SHA-256 mismatch for {destination.name}")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def unpack(archive, destination, *, runtime=False):
    destination = destination.resolve()
    destination.mkdir()
    with tarfile.open(archive, "r:*") as source:
        seen = set()
        for member in source:
            path = Path(member.name)
            target = destination / path
            allowed = member.isfile() or member.isdir() or (runtime and member.issym())
            if (path.is_absolute() or ".." in path.parts or path in seen or not allowed
                    or (path != Path(".") and not target.parent.resolve().is_relative_to(destination))):
                raise ValueError(f"Unsafe member in {archive.name}: {member.name}")
            seen.add(path)
            if member.issym():
                link = Path(member.linkname)
                if link.is_absolute() or not (target.parent / link).resolve().is_relative_to(destination):
                    raise ValueError(f"Unsafe link in {archive.name}: {member.name}")
            if target.is_symlink():
                raise ValueError(f"Archive member would overwrite a link: {member.name}")
            source.extract(member, destination, set_attrs=False)
            if runtime and member.isfile():
                target.chmod(0o600 | (member.mode & 0o100))


def install_base(prefix=(), log=None, packages=BASE_PACKAGES):
    subprocess.run([*prefix, "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "update"],
                   check=True, timeout=300, stdout=log, stderr=subprocess.STDOUT if log else None)
    subprocess.run([*prefix, "env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install",
                    "-y", "--no-install-recommends", *packages], check=True, timeout=300, stdout=log, stderr=subprocess.STDOUT if log else None)


def local_worker_asset(asset, root):
    url = urlsplit(asset["url"])
    path = Path(url2pathname(url.path))
    if (url.scheme != "file" or path.parent != root / "incoming"
            or hash_file(path) != asset["sha256"]):
        raise ValueError(f"Invalid staged worker artifact: {path.name}")
    return path


def environment(root, assets, role, log=None):
    if role == "worker":
        archive = local_worker_asset(assets["worker-wheelhouse"], root)
        runtime = local_worker_asset(assets["python-runtime"], root)
    else:
        archive = fetch(assets["jump-wheelhouse"], root / "wheelhouse.tar")
        runtime = fetch(assets["python-runtime"], root / "python-runtime.tar")
    unpack(archive, root / "wheelhouse")
    unpack(runtime, root / "python-runtime", runtime=True)
    wheels = root / "wheelhouse"
    interpreter = root / "python-runtime/python/bin/python3"
    subprocess.run([interpreter, "-m", "venv", str(root / "venv")], check=True)
    python = root / "venv/bin/python"
    subprocess.run([python, "-m", "pip", "install", "--no-index", "--find-links", wheels,
                    "--require-hashes", "-r", wheels / "requirements.lock"], check=True, stdout=log,
                   stderr=subprocess.STDOUT if log else None)
    return python


def source_command(scripts, command):
    setup = "set -e; " + "".join("source " + shlex.quote(path) + "; " for path in scripts)
    return ["bash", "-c", setup + 'exec "$@"', "ride-environment", *command]


def worker(root, config):
    evidence = root / "evidence"
    evidence.mkdir()
    subprocess.run(["cat", "/etc/os-release"], check=True)
    for tool in ("python3", "ray", "ride", "vllm", "npu-smi"):
        print("initial", tool, shutil.which(tool) or "MISSING", flush=True)
    if any(Path(path).exists() for path in config["environment_scripts"]):
        raise ValueError("A CANN environment already exists on the worker")
    addresses = subprocess.check_output(["hostname", "-I"], text=True).split()
    if config["address"] not in addresses:
        raise ValueError("SSH target does not own the inventory network address")
    python = environment(root, config["assets"], "worker")
    vendor_temp = root / "vendor-tmp"
    vendor_temp.mkdir(mode=0o700)
    install_env = {**os.environ, "PATH": str(python.parent) + ":" + os.environ["PATH"],
                   "TMPDIR": str(vendor_temp)}
    for installer in config["installers"]:
        asset = installer["asset"]
        path = local_worker_asset(config["assets"][asset], root)
        path.chmod(0o700)
        installed_scripts = [script for script in config["environment_scripts"] if Path(script).is_file()]
        subprocess.run(source_command(installed_scripts, [path, *installer["args"]]),
                       check=True, cwd=root, env=install_env)
    unpack(local_worker_asset(config["assets"]["model"], root), root / "model")
    if not (root / "model/config.json").is_file():
        raise ValueError("Model archive must have config.json at its root")
    probe = ("import sys, torch, torch_npu, vllm; "
             "import thunderagent_controller_mod.ride_managed; "
             "from ray.dashboard.modules.job.job_head import JobHead; "
             "n=torch.npu.device_count(); print('visible_npu_devices', n, flush=True); "
             "sys.exit(n != int(sys.argv[1]))")
    subprocess.run(source_command(config["environment_scripts"], [python, "-c", probe, str(config["cards"])]),
                   check=True)
    with (evidence / "packages.txt").open("w") as stream:
        subprocess.run([python, "-m", "pip", "freeze"], stdout=stream, check=True)
    with (evidence / "npu.txt").open("w") as stream:
        candidates = (shutil.which("npu-smi"), "/usr/local/Ascend/driver/tools/npu-smi")
        monitor = next((path for path in candidates if path and os.access(path, os.X_OK)), None)
        if monitor:
            result = subprocess.run([monitor, "info"], stdout=stream, stderr=subprocess.STDOUT)
            print("npu-smi exit", result.returncode, file=stream)
        else:
            print("npu-smi unavailable. The preceding torch.npu probe verified the card count.", file=stream)
            print("Visible device files:", *sorted(Path("/dev").glob("davinci*")), file=stream)



def ssh(config, address, command):
    return ["ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-o", "UserKnownHostsFile=" + config["known_hosts"],
            "-i", config["ssh_key"], "--", config["ssh_user"] + "@" + address, command]


def write_plans(config, root, remote, token):
    head = config["nodes"][0]["address"]
    workers = config["nodes"][1:]
    temp = "/tmp/ride-" + hashlib.sha256(config["name"].encode()).hexdigest()[:10]
    runtime = {"env_vars": {"PATH": f"{remote}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                            "RIDE_DEPLOYMENT_NAME": config["name"]}}
    ray_python = [f"{remote}/venv/bin/python", "-m", "ray.scripts.scripts", "start"]

    def ray_start(node, first):
        args = [*ray_python, "--node-ip-address", node["address"], "--num-cpus", str(node["cpus"]),
                "--num-gpus", "0", "--resources", json.dumps({"NPU": node["cards"]}),
                "--temp-dir", temp, "--disable-usage-stats"]
        if first:
            args += ["--head", "--port", "6379", "--dashboard-host", "0.0.0.0",
                     "--dashboard-port", "8265", "--include-dashboard=true",
                     "--autoscaling-config=$HOME/ray_bootstrap_config.yaml"]
            return shlex.join(args[:-1]) + ' "--autoscaling-config=$HOME/ray_bootstrap_config.yaml"'
        return shlex.join(args + ["--address", f"{head}:6379"])

    # Ray's local provider has a single worker start template. Each worker
    # sources its own already-pinned command, written before Ray starts.
    commands = {node["address"]: ray_start(node, index == 0) for index, node in enumerate(config["nodes"])}
    dump(root / "node-start-commands.json", commands)
    cluster = {
        "cluster_name": config["name"], "provider": {"type": "local", "head_ip": head,
                                                    "worker_ips": [node["address"] for node in workers]},
        "auth": {"ssh_user": config["ssh_user"], "ssh_private_key": config["ssh_key"]},
        "min_workers": len(workers), "max_workers": len(workers), "idle_timeout_minutes": 60,
        "upscaling_speed": 1, "file_mounts": {}, "setup_commands": [],
        "head_start_ray_commands": [commands[head]],
        "worker_start_ray_commands": [shlex.join(["bash", f"{remote}/start-ray.sh"])],
    }
    dump(root / "cluster.json", cluster)

    def placement(address):
        return {f"node:{address}": 0.001}

    models = [
        {"id": f"model-{index:02}", "type": "vllm", "model": f"{remote}/model",
         "endpoint": f"http://{node['address']}:8000", "port": 8000, "num_cpus": 2, "num_gpus": 0,
         "resources": {"NPU": node["cards"], **placement(node["address"])}, "runtime_env": runtime,
         "environment_scripts": config["environment_scripts"],
         "args": ["--served-model-name", config["model"], "--tensor-parallel-size", str(node["cards"]),
                  *config.get("model_args", [])]}
        for index, node in enumerate(config["nodes"], 1)
    ]
    management_url = f"http://{head}:19100"
    controller_url = f"http://{head}:19081"
    controller_file = root / "request-throttling.json"
    dump(controller_file, {
        "schema": "ride.controller/v1", "id": "request-throttling", "role": "requests",
        "endpoint": controller_url, "listen_host": "0.0.0.0", "state_file": f"{remote}/request.sqlite",
        "ride_endpoint": management_url, "control_token_env": TOKEN_ENV,
        "scheduler_interval_seconds": 0.5, "metrics_interval_seconds": 1,
        "model_services": {item["id"]: {"endpoint": item["endpoint"]} for item in models},
    })
    plan = {
        "schema": "ride.deployment/v1", "name": config["name"],
        "ray": {"mode": "bootstrap", "address": f"http://{head}:8265", "cluster_config": str(root / "cluster.json")},
        "management": {"endpoint": management_url, "listen": "0.0.0.0:19100", "runtime_env": runtime,
                       "resources": placement(head), "state_file": f"{remote}/management-state.json"},
        "model_services": models,
        "controllers": [
            {"id": "request-throttling", "type": "request-throttling-managed", "endpoint": controller_url,
             "configuration": f"{remote}/request-throttling.json", "configuration_sha256": hash_file(controller_file),
             "num_cpus": 0.1, "num_gpus": 0, "resources": placement(head),
             "runtime_env": {"env_vars": {**runtime["env_vars"], TOKEN_ENV: token}}}
        ],
        "model_bindings": [{"controller": "request-throttling", "token_env": TOKEN_ENV,
                            "model_services": [item["id"] for item in models]}],
        "readiness_timeout_seconds": config.get("readiness_timeout_seconds", 1200),
    }
    dump(root / "deployment.json", plan)
    return plan


def stage_worker_assets(config, root):
    artifacts = root / "worker-assets"
    artifacts.mkdir()
    sources = {"python-runtime": root / "python-runtime.tar"}
    for name in ("worker-wheelhouse", "model", *(item["asset"] for item in config["installers"])):
        asset = config["assets"][name]
        location = urlsplit(asset["url"])
        if location.scheme == "file":
            source = Path(url2pathname(location.path)).resolve()
            if not source.is_file() or hash_file(source) != asset["sha256"]:
                raise ValueError(f"SHA-256 mismatch for {name}")
            sources[name] = source
        else:
            sources[name] = fetch(asset, artifacts / f"{name}.artifact")
    debs = artifacts / "debs"
    unpack(fetch(config["assets"]["worker-debs"], artifacts / "worker-debs.tar"), debs)
    packages = sorted(debs.iterdir())
    if not packages or any(not item.is_file() or not re.fullmatch(r"[A-Za-z0-9_.+%~-]+\.deb", item.name)
                           for item in packages):
        raise ValueError("worker-debs must contain only flat .deb files")
    (artifacts / "worker-debs.sha256").write_text("".join(
        f"{hash_file(item)}  debs/{item.name}\n" for item in packages
    ))
    return sources, packages, artifacts / "worker-debs.sha256"


def prepare_node(config, node, remote, root, command, evidence, worker_assets):
    address = node["address"]
    sources, debs, deb_manifest = worker_assets
    node_config = {key: config[key] for key in ("installers", "environment_scripts")}
    installers = {item["asset"] for item in config["installers"]}
    incoming = {name: f"incoming/{name}" + (".run" if name in installers else "") for name in sources}
    node_config.update(cards=node["cards"], address=address, assets={
        name: {"url": Path(remote, incoming[name]).as_uri(), "sha256": config["assets"][name]["sha256"]}
        for name in sources
    })
    data = {"bootstrap.py": Path(__file__).read_bytes(),
            "run_machine_experiment.py": Path(__file__).with_name("run_machine_experiment.py").read_bytes(),
            "request-throttling.json": (root / "request-throttling.json").read_bytes(),
            "start-ray.sh": (command + "\n").encode(),
            "worker.json": json.dumps(node_config).encode()}
    setup = (
        "set -eu; umask 077; test \"$(id -u)\" = 0; "
        "for name in /proc/[0-9]*/comm; do "
        "if read -r process 2>/dev/null < \"$name\" && test \"$process\" = raylet; then "
        "echo 'Existing Ray node' >&2; exit 1; fi; done; "
        f"mkdir -p {shlex.quote(str(Path(remote).parent))}; mkdir {shlex.quote(remote)}; cd {shlex.quote(remote)}; tar -xf -; "
        "sha256sum -c worker-debs.sha256; "
        "mkdir apt-lists; DEBIAN_FRONTEND=noninteractive apt-get "
        "-o Dir::Etc::sourcelist=/dev/null -o Dir::Etc::sourceparts=- "
        "-o Dir::State::lists=\"$PWD/apt-lists\" -y --no-install-recommends install ./debs/*.deb; "
        "python3 bootstrap.py --worker worker.json"
    )
    log = evidence / f"install-{address}.log"
    with log.open("wb") as stream:
        with subprocess.Popen(ssh(config, address, setup), stdin=subprocess.PIPE,
                              stdout=stream, stderr=subprocess.STDOUT) as process:
            try:
                with tarfile.open(fileobj=process.stdin, mode="w|") as tar:
                    for name, contents in data.items():
                        item = tarfile.TarInfo(name)
                        item.mode = 0o600
                        item.size = len(contents)
                        tar.addfile(item, io.BytesIO(contents))
                    for name, path in sources.items():
                        tar.add(path, arcname=incoming[name])
                    for path in debs:
                        tar.add(path, arcname=f"debs/{path.name}")
                    tar.add(deb_manifest, arcname="worker-debs.sha256")
                process.stdin.close()
                code = process.wait(timeout=3600)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                raise
    print(f"Worker {address} installation exit {code}", flush=True)
    return code


def benchmark(root, output):
    from ray.util.state import list_nodes
    from ride.sdk import PeerClient

    plan = json.loads((root / "deployment.json").read_text())
    models = plan["model_services"]
    expected_cards = {
        urlsplit(item["endpoint"]).hostname: item["resources"]["NPU"] for item in models
    }
    nodes = list_nodes(address=plan["ray"]["address"], filters=[("state", "=", "ALIVE")],
                       limit=max(100, len(models) + 1), detail=True)
    observed_cards = {node.node_ip: (node.resources_total or {}).get("NPU") for node in nodes}
    dump(output / "ray-nodes.json", {"expected": expected_cards, "observed": observed_cards})
    if len(nodes) != len(expected_cards) or observed_cards != expected_cards:
        raise ValueError("Actual Ray node membership differs from the frozen machine list")
    controller = PeerClient(plan["controllers"][0]["endpoint"], timeout=10)
    dump(output / "controller-identity.json", controller.get("/identity"))
    workload = root / "swe-smith/workload"
    replayer = root / "swe-smith/experiments/workload/replay_sessions.py"
    command = [sys.executable, replayer, "--workload", workload, "--api", "chat",
               "--model", models[0]["args"][1], "--tokenizer", root / "tokenizer",
               "--chat-template-kwargs", '{"enable_thinking":false}',
               "--base-url", controller.endpoint + "/v1",
               "--evidence-type", "live", "--concurrency", "0", "--timeout", "-1",
               "--out", output / "swe-smith"]
    for item in models:
        command.extend(["--engine-url", item["endpoint"] + "/v1"])
    subprocess.run(command, check=True)
    result = json.loads((output / "swe-smith/summary.json").read_text())["result"]
    status = controller.get("/status")
    dump(output / "controller-final-status.json", status)
    if (result["sessions_completed"] <= 0 or result["sessions_unfinished"] or result["rounds_failed"]
            or result["rounds_succeeded"] != result["rounds"] or result["makespan_seconds"] is None
            or status["active_programs"] or status["waiting_requests"]):
        raise ValueError("SWE-smith batch incomplete or Controller still has live program state")


def orchestrate(config_file, output, jump_only=False):
    config = json.loads(config_file.read_text())
    validate(config)
    root = output.parent / (output.name + ".setup")
    if output.exists() or output.with_name(output.name + ".tar.gz").exists():
        raise ValueError("Choose a new result directory")
    root.mkdir(parents=True, mode=0o700)
    evidence = root / "bootstrap-evidence"
    evidence.mkdir()
    dump(evidence / "inventory.json", config)
    remote = str(Path(config.get("worker_work_parent", DEFAULT_WORKER_PARENT)) / config["name"])
    token = secrets.token_hex(32)
    (root / "controller-token").write_text(token + "\n")
    plan = write_plans(config, root, remote, token)
    commands = json.loads((root / "node-start-commands.json").read_text())
    bootstrap_exit = 1
    try:
        print("Installing jump-host tools and downloading benchmark inputs", flush=True)
        if os.geteuid() != 0 and not shutil.which("sudo"):
            raise ValueError("The jump host needs sudo for Ubuntu packages")
        with (evidence / "jump-install.log").open("w") as log:
            install_base(() if os.geteuid() == 0 else ("sudo", "-n"), log)
            python = environment(root, config["assets"], "jump", log)
        if not jump_only:
            for node in config["nodes"]:
                subprocess.run(ssh(config, node["address"], "true"), check=True, timeout=20)
        unpack(fetch(config["assets"]["tokenizer"], root / "tokenizer.tar"), root / "tokenizer")
        unpack(fetch(config["assets"]["swe-smith"], root / "swe-smith.tar"), root / "swe-smith")
        replay = root / "swe-smith/experiments/workload/replay_sessions.py"
        for path in (replay, root / "swe-smith/workload/sessions.csv",
                     root / "swe-smith/workload/manifest.json", root / "tokenizer/tokenizer_config.json"):
            if not path.is_file():
                raise ValueError(f"Required input is absent: {path.relative_to(root)}")
        with (evidence / "jump-validation.log").open("w") as log:
            subprocess.run([python, replay, "--help"], check=True, stdout=log, stderr=subprocess.STDOUT)
            subprocess.run([python, "-c", "from ray.dashboard.modules.job.job_head import JobHead; "
                            "from transformers import AutoTokenizer; import sys; "
                            "print(len(AutoTokenizer.from_pretrained(sys.argv[1], local_files_only=True)))",
                            root / "tokenizer"], check=True, stdout=log, stderr=subprocess.STDOUT)
        subprocess.run([python, "-m", "ride.deployment", "validate", root / "deployment.json", root / "state"],
                       check=True)
        with (evidence / "jump-packages.txt").open("w") as stream:
            subprocess.run([python, "-m", "pip", "freeze"], stdout=stream, check=True)

        if jump_only:
            bootstrap_exit = 0
            print(f"Jump host verified. Evidence: {root / 'bootstrap-evidence.tar.gz'}", flush=True)
            return 0

        print("Downloading worker packages once on the jump host", flush=True)
        worker_assets = stage_worker_assets(config, root)

        def prepare(node):
            return prepare_node(config, node, remote, root, commands[node["address"]], evidence, worker_assets)

        first_worker, *other_workers = config["nodes"]
        first_status = prepare(first_worker)
        if first_status:
            raise RuntimeError(f"Worker installation failed on {first_worker['address']}: {first_status}")
        with ThreadPoolExecutor(max_workers=4) as executor:
            statuses = list(executor.map(prepare, other_workers))
        if any(statuses):
            raise RuntimeError(f"Worker installation failed: {statuses}")
        bootstrap_exit = 0
    finally:
        dump(evidence / "status.json", {"stage": "jump-only" if jump_only else "bootstrap",
                                        "exit_code": bootstrap_exit})
        seal(evidence, root / "bootstrap-evidence.tar.gz")

    temp = "/tmp/ride-" + hashlib.sha256(config["name"].encode()).hexdigest()[:10]
    experiment = {
        "deployment": str(root / "deployment.json"), "state_directory": str(root / "state"),
        "ssh_key": config["ssh_key"], "known_hosts": config["known_hosts"],
        "initial_evidence": str(root / "bootstrap-evidence.tar.gz"),
        "benchmark_command": [str(python), str(Path(__file__).resolve()), "--benchmark", str(root)],
        "hosts": [{"name": model["id"], "destination": config["ssh_user"] + "@" + node["address"],
                   "paths": [f"{remote}/evidence", f"{temp}/session_latest/logs"],
                   "exclude": ["runtime_env_agent.log", "runtime_env_setup-*"]}
                  for node, model in zip(config["nodes"], plan["model_services"])],
    }
    dump(root / "experiment.json", experiment)
    env = {**os.environ, TOKEN_ENV: token, "PATH": str(python.parent) + ":" + os.environ["PATH"]}
    return subprocess.run([python, Path(__file__).with_name("run_machine_experiment.py"),
                           root / "experiment.json", output], env=env, check=False).returncode


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate inventory without contacting machines")
    mode.add_argument("--jump-only", action="store_true", help="verify only the jump-host supply chain")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--benchmark", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("configuration", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    args = parser.parse_args()
    if args.check:
        config = json.loads(args.configuration.read_text())
        validate(config)
        print(json.dumps({"nodes": len(config["nodes"]), "cards": sum(n["cards"] for n in config["nodes"])}))
        return 0
    if args.worker:
        worker(args.configuration.resolve().parent, json.loads(args.configuration.read_text()))
        return 0
    if args.output is None:
        parser.error("Provide a new result directory")
    if args.benchmark:
        benchmark(args.configuration.resolve(), args.output.resolve())
        return 0
    return orchestrate(args.configuration.resolve(), args.output.resolve(), args.jump_only)


if __name__ == "__main__":
    raise SystemExit(main())
